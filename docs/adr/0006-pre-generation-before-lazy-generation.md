# 0006. Pre-generation before lazy generation

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** architecture, product

## Context

The product brief describes demand-driven generation: user presses play, chapter is rendered
if missing, playback starts as soon as enough audio exists. This is the right *fallback* and
the right behaviour for uploads.

It is the wrong *default* for a public catalogue, for three measured reasons:

1. **Cold start dominates.** A serverless GPU worker takes 20–90 s to become ready, plus model
   load. A 30-minute chapter then takes minutes of GPU time. The user's first experience is a
   spinner, and the p95 experience is worse because the queue is shared.
2. **Generation is ~10× cheaper when batched.** Cost per 10-hour book: ~$1.70–3.80 self-hosted
   versus $16–41 on managed TTS. Within self-hosting, batching 20–60 segments per call and
   running at off-peak GPU rates is materially cheaper than one-segment-at-a-time interactive
   rendering.
3. **Popular public-domain titles have enormous reuse.** One render of *Pride and Prejudice*
   serves every listener, forever. The marginal cost of the 1,000th listener is bandwidth,
   not inference.

Demand-driven generation optimises for storage and for the long tail, at the cost of latency
and unit economics — precisely the wrong trade for the top of the catalogue.

## Decision

We will run **three generation modes, in priority order**:

1. **Curation / pre-generation (default for catalogue).** A scheduled queue renders the top N
   titles (start: top 200 by catalogue popularity) chapter by chapter, at lowest priority, off
   peak, with a per-run budget. Results are ordinary shared renders.
2. **Prefetch during playback.** When a listener is within the adaptive horizon of an
   uncached chapter, enqueue it at `prefetch` priority.
3. **User-waiting (fallback).** For uploads, long-tail titles and overrides, enqueue at
   `user_waiting` priority and show an honest ETA with a preview-first path (first ~60 s of
   audio rendered ahead of the rest).

Priority ordering is explicit in the job table (`user_waiting` = 10, `prefetch` = 50,
`curation` = 200) so that a curation run can never starve an interactive request.

## Consequences

**Good**
- The common path is a cache hit: time-to-first-audio under 2 s.
- Inference spend is predictable: curation is a budgeted batch, not a tail of user-triggered
  spikes.
- The player experience is decoupled from GPU availability.

**Bad**
- Pre-generation spends money on titles that may never be listened to. Mitigated by the
  popularity threshold and by starting small (top 200, one chapter each, then expand).
- Storage grows ahead of demand. 200 books × 10 h × 28.8 MB ≈ 58 GB ≈ $1.30/month — trivial
  compared to the same audio generated 200 times on demand.
- Curation jobs compete with interactive jobs for the same GPU quota. Mitigated by priority
  and by pausing curation when `user_waiting` depth exceeds a threshold.

## Rejected alternatives

- **Pure lazy generation.** Best storage efficiency, worst latency and unit cost, and it makes
  the first user of every title pay the full cold-start penalty.
- **Full pre-generation of the entire catalogue.** Tens of thousands of titles; cost and time
  are unbounded. Rejected in favour of popularity-ranked incremental pre-generation.
- **Pre-generate on first request only ("warm after one user").** Second user still waits for
  a chapter the first user didn't reach. Partially adopted via prefetch.

## Revisit when

- GPU cost falls far enough that the batching advantage disappears, or interactive latency
  drops below ~10 s p95, at which point lazy generation becomes defensible as the default.
