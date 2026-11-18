# Runbook: kill switch

**Use when:** spend is running away, a provider is returning corrupted audio, or a rights
takedown requires an immediate stop to generation.

**Effect:** provider calls stop within 5 seconds. Cached playback is unaffected. This is the
fastest safe action available to an operator.

> **Launch profile (ADR-0007).** There is no admin control plane and no provider spend at
> $0. The launch kill switch is the worker process: send it `SIGTERM` and it stops claiming
> jobs. Cached playback continues because `/media` is served by the API from static files.
> Use `SIGKILL` only if a job is wedged; the lease expires and the job is requeued, and
> render claims prevent duplicate synthesis. The modes below become available with the
> admin plane and the first paid provider.

## Launch procedure

```bash
# stop generation, keep serving
pkill -TERM -f "services.worker.worker.main"

# resume
.venv/bin/python -m services.worker.worker.main
```

To stop everything, including playback, stop `scripts/dev.sh`. Per-work takedown is
enforced: a work whose `rights_basis` is not public-domain is excluded from the public
catalogue, and direct requests for its pages, manifests and media return `404` to anonymous
callers. The operator (valid token, or a query token for `<audio>`) still sees everything.

## Modes

| Mode | Provider calls | Queued jobs | In-flight | Playback |
|---|---|---|---|---|
| `normal` | allowed | run | continue | normal |
| `cache_only` | **stopped** | paused | finish current batch, then stop | normal |
| `hard_stop` | **stopped** | paused | cancelled at next segment boundary | normal |

Use `cache_only` unless the audio itself is suspect. Use `hard_stop` when a bad model version
is producing wrong voices and you do not want another segment written.

## Engage

Admin UI: `/admin` → Overview → **Kill switch** → choose mode → type the reason → confirm.

CLI (if the API is healthy but the UI is not):

```bash
curl -X POST https://api.example.com/admin/kill-switch \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Idempotency-Key: ks-$(date +%s)" \
  -d '{"mode": "cache_only", "reason": "cost spike, investigating"}'
```

Direct database (last resort, if the API is down — the switch is read from `config_versions`):

```sql
insert into ops.config_versions (version, actor_id, note, diff)
values ((select max(version)+1 from ops.config_versions), 'ops:manual',
        'kill switch', '{"kill_switch": "cache_only"}');
```

Workers poll every 5 s, so no restart is required.

## Verify (within 60 seconds)

1. `/admin/spend` — new spend stops increasing. This is the only verification that matters.
2. `/admin/jobs` — running jobs show `cancelling` (hard stop) or complete their batch then
   stop.
3. A cached chapter still plays in the browser. If it does not, the problem is not inference;
   stop and treat it as a CDN or database incident.
4. New chapter requests return 202 with a longer ETA, not an error.

## What still works

- Playback of everything already rendered.
- Browsing, search, library, uploads (queued, not processed).
- Auth, admin, cost dashboards.
- Audio exports of already-mastered chapters.

## Resume

1. Fix the cause. Do not resume to "see if it is better".
2. Set `normal`.
3. Watch the first 10 jobs individually before walking away.
4. If the cause was a bad model version, disable that version first, then resume — otherwise
   the queue immediately reproduces the incident.

## Monthly test

On the first of the month, in production, for 60 seconds:

1. Engage `cache_only`.
2. Confirm spend flatlines and a new chapter request returns 202.
3. Return to `normal`.
4. Confirm generation resumes.

Record the time-to-effect. If it exceeds 5 s, the polling interval or the config cache is
broken — fix it while it is still a drill.
