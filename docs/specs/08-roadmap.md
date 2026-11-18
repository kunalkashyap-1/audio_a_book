# 08. Roadmap

## 1. Shape of the plan

Seven phases. Each ends with something demonstrable and a gate that can fail. Effort is in
engineer-weeks for **two engineers working full time**, and is an estimate, not a commitment.

| Phase | Deliverable | Effort | Gate |
|---|---|---|---|
| 0 | Specification + benchmarks | 2 (remaining) | RTF ≤ 0.35, attribution F1 ≥ 0.85 |
| 1 | Walking skeleton: one book, one voice, playable audio | 3 | `curl` → audio bytes, end to end |
| 2 | Ingestion + catalogue | 3 | 5 formats parse; 200 titles importable |
| 3 | BookBrain | 5 | 87%+ dialogue attributed on the eval set |
| 4 | Voices + TTS + cache | 5 | cache hit ≥ 90% on repeat requests |
| 5 | Mastering, player, export | 3 | multi-voice chapter with chapter markers |
| 6 | Admin + Android | 4 | operator can run an incident without a deploy |
| 7 | Cloning, OCR, multilingual | 6 | consent flow, scanned PDF, second language |

**Critical path:** Phase 0 benchmarks → Phase 1 skeleton → Phase 4 cache correctness.
Everything else can slip a week without moving the launch date; those three cannot.

### 1.1 Current position

- Phase 0 is complete as a **specification**; its measurement gates are deferred because they
  require paid GPU access and a labelled corpus.
- Phase 1 is **implemented and verified at $0**: upload → ingest → cast → per-character
  segment rendering → AAC chapter master → browser playback, with the shared cache and
  idempotency proven by tests and by a second-book run. The measured cache result was
  `14 unique, 14 cached, 0 to render` in 0.9 s versus 12.1 s for the first render.
- The launch adapter choices are recorded in ADR-0007. They do not change the phase gates;
  they change which implementation satisfies Phase 1 first.
- Five hardening phases have since shipped on top of that skeleton without changing the
  product: **A** layered API + OpenAPI, **B** local accounts + owner-scoped library/progress,
  **C** generated contracts + typed Next.js web app, **D** the admin plane, and **E** crash
  drills + CI. See the checklist for each gate.
- Phases 2–7 below are unchanged in intent. Where a phase lists cloud or LLM work, treat that
  work as the **quality-tier** path and keep the local implementation as the fallback.

### 1.1 The walking-skeleton rule

Phase 1 must produce a *complete* thin slice — upload one TXT, one voice, one chapter, audio
out, played in a browser — before any phase adds breadth. The three most expensive mistakes
in this project (wrong cache key, wrong voice identity model, wrong provider boundary) are all
cheap to fix when there is one book and expensive when there are two hundred.

## 2. Phase 0 — Specification (complete; benchmark gates deferred)

### Done

- Requirements analysis, conflict resolution, nine specifications, six ADRs, licence register.

### Remaining, in order

1. **TTS throughput benchmark** (2 days). Qwen3-TTS 1.7B and 0.6B on an L4 at batch 1/8/16/32.
   Produces RTF, VRAM, cost per audio hour.
2. **Voice stability run** (1 day). 200 segments, one reference clip, speaker-embedding
   distribution + 20-sample ABX.
3. **Attribution evaluation** (3 days). 200 hand-labelled segments, three novels; F1 for
   DeepSeek V4.1 Flash and one alternative; failure taxonomy.
4. **End-to-end cost run** (1 day). Three books through the full pipeline once Phase 1 exists;
   before that, an offline simulation is acceptable.
5. **Legal review** (parallel). Public-domain stance, Gutenberg terms, cloning policy draft.
6. **Go/no-go memo** (half a day).

### Gate

| Criterion | Threshold | If missed |
|---|---|---|
| RTF at chosen batch | ≤ 0.35 | try 0.6B, then Kokoro; if still bad, managed TTS becomes primary and the model changes |
| Cost per audio hour | ≤ $0.35 | re-scope: fewer pre-generated titles, stricter quotas |
| Attribution F1 | ≥ 0.85 | correction UI moves from Phase 6 to Phase 4; launch with fewer titles |
| Voice stability | median cosine ≥ 0.85 | raise reference clip quality bar; test an alternate model |
| Licence review | no blockers | stop; do not write code against unclear weights |

If three of five pass, proceed with a written record of the misses. If fewer than three pass,
the product thesis needs revisiting before Phase 1.

## 3. Phase 1 — Walking skeleton

**Goal:** a single command produces audio from a text file, and a browser plays it.

**Status: implemented and verified at $0.**

| Workstream | Launch implementation | Deferred to the quality tier |
|---|---|---|
| Repo | one Python distribution + npm workspaces (`uv`, pytest; npm not pnpm) | mypy, import-linter, CI contract-diff check |
| Database | SQLite from the same SQLAlchemy metadata | Postgres 16 + pgvector, Alembic |
| Jobs | claim/lease/retry/requeue, idempotency, render claims | a service-level retry endpoint |
| Storage | local filesystem, content-addressed segments | S3 wrapper with `put_if_absent` |
| Auth | shared admin token + local JWT accounts, roles `user/admin` | Cognito/OIDC, enterprise SSO |
| API | v1 health/books/chapter audio/media, auth, library, progress | signed URLs, catalogue search |
| Worker | `ingest.revision`, `tts.chapter`, real Kokoro + fake provider | parallel worker pool |
| Render key | real function, golden vector, sensitivity tests | — |
| Web | zero-build player at `/` plus typed Next.js app on :3000 | admin management actions, mobile |
| Deploy | `scripts/dev.sh` on one machine | Compose, Caddy, SSH deploy |

### Gate

- [x] One command yields a working stack: `./scripts/dev.sh`, no Docker required.
- [x] Upload → parse → cast → TTS → playable audio, through the HTTP API.
- [x] Second request for the same chapter renders nothing; a second book reuses cached
      segments (0 new renders).
- [x] Kill the worker mid-job and restart; assert no duplicate renders. `test_resilience.py`
      kills a render between batches with `SystemExit`, checks the job keeps its lease while
      another worker refuses it, expires the lease and render claims, then drains again and
      asserts one render per key, a complete manifest and no orphan claims. The drill found and
      fixed a claim leak: keys rendered before the crash were never released on recovery.
- [x] `pytest` green: 119 tests in under a minute. `npm run typecheck` and `npm run build` pass;
      the web flows were verified end to end through the :3000 rewrites against the live API.
      `.github/workflows/ci.yml` reruns tests, HTTP smoke, contract regeneration, typecheck and
      build on every push and pull request, and builds/boots both Docker images in a second job.
- [x] Docker packaging: `compose.yaml` brings up API + worker + built Next.js web app with one
      command and a persistent data volume; optional `models` profile downloads Kokoro weights.

### Deliberately absent

Real LLM analysis, cloud deploy, admin management actions (the read-only dashboard exists),
mobile, quotas and billing.

## 4. Phase 2 — Ingestion and catalogue

| Workstream | Items |
|---|---|
| Parsers | EPUB (container + OPF, no AGPL libraries), TXT, DOCX, HTML, text PDF |
| Normalisation | unicode, whitespace, de-hyphenation, Gutenberg boilerplate stripping |
| Chapters | heading heuristics + confidence; manual override endpoint |
| Blocks | narration / dialogue / heading / verse segmentation |
| Fingerprints | 5-gram MinHash, duplicate candidates, no auto-merge |
| Catalogue | Gutendex + Standard Ebooks connectors, on-demand ingest, rights fields |
| Uploads | presigned PUT, magic-byte validation, size/page caps, private by default |
| Tests | fixture corpus of 20 books including a nasty EPUB and a two-column PDF |

### Gate

- 20/20 fixtures parse without human intervention; 18/20 with correct chapter counts.
- A 200-title catalogue import completes in under an hour at `curation` priority.
- Duplicate detection finds the three known same-work pairs in the fixture set with no false
  positives.
- No AGPL dependency in the tree (CI check).

## 5. Phase 3 — BookBrain

| Workstream | Items |
|---|---|
| Pass A | per-chapter prompt, strict schema, retry with validator errors, provenance |
| Pass B | consolidation from digests, character registry, aliases, relationships |
| Attribution | quotative rules first, then LLM, then alternation fallback; explicit certainty |
| Scenes | boundary detection from blocks + digests |
| Corrections | overlay table, application after derivation, survives reprocessing |
| Review queue | uncertain/unattributed list, sorted by impact |
| Evaluation | the 200-segment set wired into CI as a regression test |

### Gate

- Attribution F1 ≥ 0.85 on the evaluation set (`certain` + `probable`).
- Character precision ≥ 0.90; ≤ 2 invented characters per chapter.
- Re-running analysis on unchanged input produces an identical storypack (modulo timestamps).
- A correction applied to revision 1 still applies after revision 2 is ingested.
- Cost per book ≤ $0.50 measured from `ops.usage_records`.

## 6. Phase 4 — Voices, TTS and the cache

The phase where the product's economics are decided.

| Workstream | Items |
|---|---|
| Voice factory | persona → 8 candidates → QC → diversity check → curator pick → immutable clip |
| Casting | system library for 12 archetypes, per-book assignment, narrator selection |
| TTS adapter | Qwen3-TTS on serverless GPU, batch 8–32, `weights_sha256` assertion |
| Cache | render key, render sets, `INSERT ... ON CONFLICT`, cross-book reuse |
| Idempotency | concurrent request test, worker-kill test, prefetch/curation collision test |
| QC | duration, silence, clipping, loudness, ASR round-trip, speaker drift |
| Router | capability filter, budget check, health, fallback chain, provenance |
| Cost guards | estimates before calls, reservations, caps |

### Gate

- **Cache correctness:** 1,000 segments across 3 books produce exactly the expected number of
  unique keys; a second identical request renders zero segments.
- **Blast radius:** changing one character's voice re-renders only that character's segments.
- **Concurrency:** 50 simultaneous requests for one chapter → one job, one render per key.
- **Stability:** median speaker cosine ≥ 0.85 over 200 segments.
- **Cost:** ≤ $0.35 per audio hour, measured.

If any of the first three fail, stop and fix. They are the invariants the business rests on.

## 7. Phase 5 — Mastering, player, export

| Workstream | Items |
|---|---|
| Mastering | concat with gaps, two-pass loudnorm, AAC master, deterministic |
| Manifests | segment manifest, HLS, byte-range seeking, `complete` flag |
| Player (web) | chapter nav, speed, skip, bookmarks, resume, keyboard, sleep timer |
| Preview | 60-second first-batch path with honest ETA |
| Prefetch | 55% trigger, lookahead 2, suppression rules |
| Export | M4B with chapter markers, queued at `user_waiting` |
| Accessibility | WCAG 2.1 AA on player and library |

### Gate

- Time-to-first-audio: cached < 2 s p50; uncached < 45 s p50 for a 30-minute chapter.
- Seeking to 80% of a chapter starts audio in < 1.5 s.
- M4B plays in VLC, Apple Books and a Android player with correct chapter markers.
- Lighthouse accessibility ≥ 95.

## 8. Phase 6 — Admin and Android

| Workstream | Items |
|---|---|
| Admin | overview, providers, models, routing + dry-run, jobs, spend, flags, audit, review queues |
| Kill switch | three modes, tested monthly |
| Android | React Native, Media3/ExoPlayer, background playback, lock screen, Bluetooth, download |
| Offline | chapter download, local manifest, sync of position |
| Resilience | dead-letter page, retry-all, incident runbook |

### Gate

- Operator can disable a provider, verify rerouting and restore it, with no deploy, in < 5 min.
- Kill switch stops all provider calls within 5 s (measured).
- Android: 60 minutes of background playback with screen off, correct lock-screen metadata,
  resume within 2 s of a web session.
- Every admin mutation appears in the audit log with before/after.

## 9. Phase 7 — Cloning, OCR, multilingual

| Workstream | Items |
|---|---|
| Cloning | consent record, ownership verification, blocklist, deletion cascade, UI |
| OCR | `OCRProvider`, scanned-PDF detection, new revision on OCR |
| Multilingual | language detection per block, per-language voices, UI strings, bidi |
| Series | character links across books, continuity checks, "same voice in book 2" |

### Gate

- Cloning requires a consent record and a verified right to the voice; deletion removes the
  reference and every render derived from it within 24 h.
- Scanned PDF produces a searchable revision with WER < 15% on a 10-page sample.
- A second language (Spanish) renders end to end with correct segmentation and a
  language-appropriate voice.
- Book 2 of a series inherits book 1's character voices with zero curator intervention.

## 10. Risks

| # | Risk | Likelihood | Impact | Mitigation | Early signal |
|---|---|---|---|---|---|
| R1 | RTF worse than 0.35 | Medium | High | 0.6B fallback; managed TTS for long tail; fewer pre-generated titles | Phase 0 benchmark |
| R2 | Attribution F1 < 0.75 | Medium | High | Correction UI earlier; rule-based quotatives; launch with fewer titles | Eval set |
| R3 | Voice drifts over 10 h | Medium | High | Reference-clip conditioning; per-chapter drift QC; profile revision | 200-segment run |
| R4 | Cache key wrong (collisions) | Low | Severe | Golden + sensitivity tests; `rk2` escape hatch | Any user report of wrong voice |
| R5 | Provider price/terms change | High | Medium | Registry, price schedules, monthly re-verification | Pending-price banner |
| R6 | Rights challenge on a title | Medium | Medium | Territory flags, per-title takedown, `shareable` predicate | Rights review |
| R7 | Cost overrun from a routing bug | Medium | High | Provider-mix alert, per-provider caps, budget hard stop | Spend dashboard |
| R8 | Scope creep into social/payments | High | Medium | The MVP boundary in spec 01 is a contract | Any new epic |
| R9 | Single-host failure | Low | Medium | Cached playback survives; 30-min restore runbook | Uptime alert |
| R10 | Cloning abuse at launch | Medium | High | Feature off until Phase 7; consent + blocklist | Feature flag |

## 11. What to cut, in order

If schedule slips, cut in this order — each cut costs less than the one before it:

1. M4B export (nice-to-have; the player works).
2. Sleep timer and bookmarks.
3. Android offline downloads (streaming only).
4. Curation breadth (200 titles → 80).
5. Admin cost dashboards beyond the overview card.
6. Multilingual UI (keep the data model, drop the locale switch).
7. OCR.
8. Series-level character links.

Never cut: cache correctness, voice stability QC, idempotency, the audit log, the kill switch.

## 12. Demo script for the Phase 5 milestone

Five minutes, no slides:

1. Open the catalogue, search "Austen", open *Pride and Prejudice*.
2. Show the cast: six characters, each with a 5-second sample.
3. Press play on chapter 3 — audio starts in under 2 s (pre-generated).
4. Jump to chapter 12 — 202, honest ETA, preview audio within 20 s.
5. Change Elizabeth's voice — show "re-rendering 84 of 412 segments", hear the new voice.
6. Open the admin, show spend for this book, the routing chain, and the cache hit ratio.
7. Kill the worker container mid-render; show the job requeue and complete without duplicates.

Every one of those steps is a gate from this document.
