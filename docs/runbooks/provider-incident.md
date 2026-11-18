# Runbook: provider incident

**Use when:** error rate for a provider exceeds 10% for 5 minutes, latency triples, or the
overview shows a provider `down`.

**Goal:** restore generation in < 10 minutes, without a deploy, without losing cached playback.

## 1. Triage (2 minutes)

From `/admin/overview`:

| Question | Where | Interpretation |
|---|---|---|
| Is it one provider or all? | Health card | All → our network or credentials, not the vendor |
| Which error codes? | Provider detail | `AUTH`/`QUOTA_EXCEEDED` will not fix themselves |
| Is it only TTS or also LLM? | Queue card by kind | TTS-only → GPU capacity; both → our egress |
| Did spend just spike? | Spend card | A runaway retry loop can look like a provider outage |

Check the provider's status page before changing anything; if they have announced a
maintenance window, the correct action is often to wait and keep the queue paused.

## 2. Contain (2 minutes)

**Disable the provider.** `/admin/providers/{id}` → Disable. Takes effect within 5 s; the
router re-reads `config_version` at the next job claim.

The confirmation dialog states which chains lose their primary and which have no fallback.
Read it. A TTS chain with no fallback means disabling the provider stops all new generation —
that may still be better than a 100% error rate, but it is a decision, not a reflex.

## 3. Verify rerouting (2 minutes)

Open `/admin/routing/tts.clone` and use the dry-run explainer with a real book:

```
1. runpod/qwen3-tts-1.7b-base  ✓ selected
2. modal/qwen3-tts-1.7b-base   ✗ disabled
```

Then request one chapter and watch the job's `routing_chain` in the job detail. If the chain
is still the old one, the worker has not picked up the config version — check that the
scheduler is alive, since it writes heartbeats.

## 4. If the chain is exhausted

| Situation | Action |
|---|---|
| All TTS candidates down | Set `cache_only`. Playback continues; new chapters show "narration paused". Post a status notice. |
| All LLM candidates down | Ingestion and TTS continue. Attribution falls back to rules-only with lower confidence. Do not fail the book. |
| Only the managed fallback remains | Check the cost impact first: 10% of traffic on Chirp 3 HD costs more than the entire infrastructure. Prefer `cache_only` over an accidental 10× bill. |

## 5. Communicate

- Public status note if `cache_only` lasts > 15 minutes.
- Internal note with: provider, error code, start time, jobs affected, workaround.
- No speculation about the vendor's cause in public text.

## 6. Recover

1. Re-enable the provider.
2. Watch the error rate for 10 minutes at reduced traffic (pause curation first).
3. Resume curation (`curation.enabled = true`) only after an hour of clean traffic.
4. Check for jobs that went `dead` during the incident and retry them by group from the
   dead-letter page.

## 7. Close out

- Add the provider's incident id and timeline to the incident record.
- If the failure changed a routing assumption, update `docs/specs/04-ai-providers.md` §5.1.
- If the fallback chain turned out to be too shallow, that is a Phase-level finding: record it
  as a risk, not a one-line fix.
- Confirm no render set mixed two models during the incident:

  ```sql
  select render_set_id, count(distinct model_id)
    from shared.audio_renders
   where created_at > now() - interval '2 hours'
   group by 1 having count(distinct model_id) > 1;
  ```

  Any row here is a correctness bug: supersede those sets and re-render.
