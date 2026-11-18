# 06. Administration and Operations

**Launch note (ADR-0007).** No spend to control at $0 and no external identity provider. Two
local gates exist: `AAB_ADMIN_TOKEN` (shared operator token) and `AAB_JWT_SECRET`
(email+password accounts, roles `user/admin`, first registrant becomes admin). With neither
set, the instance is single-operator by assumption. Catalogue filtering by `shareable` plus the
owner predicate keeps private uploads invisible to anonymous callers and to other users,
including their media; library and playback progress are owner-scoped.

**Phase D (shipped).** A canonical `/api/v1/admin` plane is now live and gated by `require_admin`:
`GET /overview`; `GET /jobs` with state/kind filters and paging, `GET /jobs/{id}` with its event
timeline, `POST /jobs/{id}/retry`, `POST /jobs/{id}/cancel`; `GET /works` including private
works and `PATCH /works/{id}` limited to `shareable`/`status`; `GET/PUT/DELETE /flags`; and a
read-only `GET /providers`. Running jobs cannot be cancelled (workers have no cooperative
cancellation), and retries reset attempts so an operator can re-drive a terminal job. Every
mutation writes an `admin_audit` row (actor, before, after, reason) in the same transaction;
the web UI requires a typed reason for each one. The Next.js admin screen has five tabs —
Overview, Jobs, Books, Flags and Providers.

**Still deferred.** Full audit browsing, budgets/spend controls, provider routing, cast
approval and content editing. The detailed target design below — including roles beyond
`user`/`admin`, cost dashboards and `ops.audit_log` schema-level write protection — becomes
current with the first paid provider.

## 1. Principles

1. **Operate without a deploy.** Providers, routing, flags, budgets, cast approvals and
   job retries are all runtime operations. If an incident requires `git push`, the admin
   surface has failed.
2. **Read-only by default in production.** Destructive actions require a typed confirmation
   and are recorded in `ops.audit_log` with a reason string.
3. **Every mutation is audited.** Who, what, before, after, why, request id. The application's
   database role cannot `UPDATE` or `DELETE` the audit table.
4. **The admin sees money.** Every page that can trigger spend shows the estimated cost and
   the current budget state.
5. **The admin cannot edit content.** No page lets an operator rewrite a book's text or
   replace audio bytes. Corrections go through the same overlay path users use, so they are
   reproducible and revertible.

## 2. Roles

| Capability | `user` | `curator` | `admin` | `finance` |
|---|---|---|---|---|
| Browse, play, upload, cast own books | ✓ | ✓ | ✓ | ✓ |
| View catalogue items, propose merge | | ✓ | ✓ | |
| Approve imports, rights, dedupe merges | | ✓ | ✓ | |
| Review attribution corrections | | ✓ | ✓ | |
| Approve voice casts (system voices) | | ✓ | ✓ | |
| Enable/disable providers, models | | | ✓ | |
| Edit routing chains | | | ✓ | |
| Create/raise budgets | | | ✓ | ✓ |
| Set spend caps, engage kill switch | | | ✓ | ✓ |
| Retry/cancel jobs | | ✓ | ✓ | |
| Feature flags, config versions | | | ✓ | |
| Read audit log | | | ✓ | ✓ |
| Read cost dashboards | | | ✓ | ✓ |
| Delete user data (GDPR request) | | | ✓ | |

Roles live in our database (`users.role`), not in the token, so revocation is immediate.
An admin acting on a book they do not own sees a banner: "You are acting as staff; this action
is audited."

## 3. Navigation

```
/admin
├── Overview            health, spend, queue, alerts
├── Catalogue           works, editions, imports, dedupe proposals, rights
├── Books               revisions, chapters, storypacks, cast, render sets
├── Review
│   ├── Attributions    uncertain speakers, low confidence, corrections
│   ├── Voices          cast approval, drift failures, reference clips
│   └── QC              ASR failures, silence, clipping, repeat loops
├── Jobs                queue, running, dead letters, retries
├── Providers           providers, models, capabilities, health, price schedules
├── Routing             chains, dry-run explain, per-capability view
├── Spend               budgets, burn rate, per-provider/per-book breakdown
├── Users               quotas, roles, deletion requests
├── Config              feature flags, policy versions, rollback
└── Audit               append-only log, export
```

## 4. Overview page

Six cards, all above the fold, refreshed every 10 s:

| Card | Contents | Red when |
|---|---|---|
| Queue | depth by priority band, oldest job age | `user_waiting` > 20 or oldest > 5 min |
| Health | provider status, host CPU/mem/disk, S3/CF errors | any provider `down`, disk > 80% |
| Spend | month-to-date, burn rate, projected month-end, cap | projection > 90% of cap |
| Cache | minute-weighted hit ratio (24 h), misses by model | hit ratio < 50% |
| Quality | chapter failure rate, QC failures by kind | failure rate > 5% |
| Incidents | active alerts, last deploy, config version | any active P1 |

Every card links to the page that can fix it. A dashboard that only informs is a dashboard
nobody opens.

## 5. Provider and model management

### 5.1 Provider list

Columns: id, kind, enabled, health (with age of last check), models (enabled/total), current
hour spend, error rate (15 min), p95 latency, actions.

Actions: enable/disable, run health probe, run capability probe, edit credential reference,
view recent errors (redacted).

**Disabling a provider** is a single click that takes effect within 5 s: the router re-reads
`config_version` per job claim. In-flight calls are allowed to finish; queued jobs route
around it. The confirmation dialog states the routing consequence: "3 chains will lose their
primary candidate; 1 has no fallback."

### 5.2 Model editor

Fields mirror `ops.ai_models`: id, provider, version, display name, capabilities (JSON editor
with schema validation), limits, price schedule (a table, append-only), weights hash, licence,
terms version, data class, enabled, deprecation date.

Guardrails:

- Changing `weights_sha256` on a model used by an active render set warns that this is a new
  identity and creates a new model row instead. The field is immutable after first use.
- Adding a price entry with `effective_from` in the past is rejected; prices are append-only
  history. A correction is a new entry plus a note.
- Setting `enabled = false` on the last model in a chain is blocked unless the chain is
  disabled too, so the platform cannot silently lose a capability.

### 5.3 Price change workflow

1. Provider announces a change (email, status page).
2. Operator adds a `price_schedule` entry with the effective date and a `note`.
3. The cost dashboard shows a "pending price change" banner with the projected monthly delta.
4. On the effective date the new entry becomes authoritative automatically.
5. `docs/CHECKLIST.md` keeps the verification cadence: re-check every enabled provider on the
   1st of each month.

The placeholder entry with `null` prices (spec 04 §6) makes an unpriced model *ineligible*
rather than cheap. That failure is loud at the right time — during routing, not on the invoice.

## 6. Routing editor

Per capability (`llm.chapter_analysis`, `llm.work_consolidation`, `tts.clone`,
`tts.preview`, `embedding.text`):

- ordered chain, drag to reorder
- requirements (languages, data class, minimum context, cloning)
- live status per candidate: enabled, healthy, price, estimated cost per typical call
- **dry-run explainer**: paste a requirement (or pick a real book) and see the resolved chain
  with every rejection reason

```
tts.clone  for  book=Pride and Prejudice  lang=en-GB  data_class=public_ok
  1. modal/qwen3-tts-1.7b-base   ✓ selected   RTF est 0.25   $0.20/audio h
  2. runpod/qwen3-tts-1.7b-base  ✓ fallback   same weights, different host
  3. polly/neural                ✗ rejected   no reference-clone support
  4. chirp3-hd                   ✗ rejected   no reference-clone support
```

Note the last two: the fallback chain for cloning is short by nature. That is a real
operational risk and the page says so explicitly rather than pretending the chain is deep.

## 7. Spend controls

### 7.1 Budget model

| Scope | Default | Hard stop | Behaviour at cap |
|---|---|---|---|
| Global, monthly | set by finance | yes | all generation pauses; cached playback continues |
| Provider, monthly | optional | yes | that provider is skipped by the router |
| User, monthly | 5 audio hours of new generation | no | queued until next month, with a clear message |
| Book, total | 2× estimate | yes | job fails with `budget_exceeded`, admin alerted |
| Curation run | per-run cap | yes | run pauses, resumes next window |

### 7.2 Enforcement path

1. Before a call, the adapter's `estimate()` returns a cost.
2. The job runner asks `budget.can_spend(scope, estimate)`.
3. The reservation is written (`ops.usage_records` with `cache_read=false`, `quantity` reserved)
   so two concurrent jobs cannot both pass the check.
4. After the call, the reservation is reconciled with actual usage; the delta is recorded.
5. A reaper releases reservations from dead jobs older than 1 hour.

The 60-second requirement (spec 01, NFR "Cost guard") is met because the check happens per
batch, not per chapter.

### 7.3 Kill switch

One control, three modes:

| Mode | Effect |
|---|---|
| `normal` | everything runs |
| `cache_only` | no provider calls; queued jobs pause; playback unaffected |
| `hard_stop` | as above, plus in-flight batches are cancelled at the next segment boundary |

The switch is a row in `config_versions`; workers poll it every 5 s. It is the first thing in
the runbook and it is tested monthly by engaging it for 60 seconds in production.

## 8. Job monitor

Filters: kind, state, priority band, age, target, error code, provider.

Row detail shows: attempts with timestamps, lease owner, routing chain actually resolved,
estimated vs actual cost, the `job_events` timeline, and the redacted error.

Actions:

- **Retry** — resets to `queued`, increments a manual-retry counter (does not consume
  `max_attempts`).
- **Cancel** — `queued` → `cancelled`; `running` → flags for cooperative cancellation at the
  next batch boundary.
- **Requeue with overrides** — e.g. force a specific model, useful for isolating a bad
  provider. Overrides are recorded on the job and shown in the timeline.

Dead-letter view: jobs with `state = dead`, grouped by error code, with a "retry all of this
group" action. This is the page used during the first incident, so it must be one click from
the overview.

## 9. Catalogue curation

### 9.1 Import

- Search Gutendex / Standard Ebooks / Open Library from the admin.
- Preview: title, author, edition, language, rights basis, territory, source URL, word count.
- Import creates `works`/`editions`/`sources` rows and enqueues `ingest.catalogue` at
  `curation` priority.
- Rights are explicit at import: `public_domain_us` is the default; anything else requires a
  written justification field.

### 9.2 Dedupe proposals

The fingerprint matcher (spec 03 §9) proposes merges. The review screen shows:

- the two works side by side, with differing metadata highlighted
- Jaccard similarity and the sample of matching shingles
- consequences: which editions, revisions, renders and cast assignments would move

Merge is curator-only, audited, and reversible (the merge record keeps both original ids).

Never auto-merge. The cost of a wrong merge is a book whose chapters are silently duplicated
or missing, which is unrecoverable from the user's perspective.

### 9.3 Rights

A work's rights panel shows basis, territories, source terms, and the date last verified.
Changing `shareable` from true to false immediately stops shared delivery (it is a query
predicate, not an asset change) and queues an alert to review any curation runs targeting it.

## 10. Attribution review

The highest-value human workflow in the product. Entered from a book, a chapter, or the global
queue of `uncertain`/`unattributed` segments.

Layout:

```
┌───────────────────────────────────────────────┬──────────────────────────┐
│  Context (±3 blocks, current dialogue boxed)  │  Cast                    │
│                                               │  ○ Elizabeth Bennet 0.94 │
│  "You are mistaken, Mr. Darcy," she said,     │  ○ Mr. Darcy        0.61 │
│  colouring.                                   │  ○ Jane Bennet      0.03 │
│                                               │  ○ + new character       │
│  [◀ prev]  [next ▶]           confidence 0.41 │  [assign & next]         │
├───────────────────────────────────────────────┴──────────────────────────┤
│  Evidence: quotative "she said" → nearest female antecedent: Elizabeth    │
│  Previous 5 attributions: E, E, D, E, ?                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

Behaviour:

- Assigning writes a `story_corrections` row keyed by `span_hash`, applied after every
  derivation, so it survives reprocessing.
- The UI shows how many segments will be re-rendered before saving. One line = one render.
- A correction that would flip a chapter's speaker distribution by more than 20% warns the
  curator — usually a sign the character registry has a merge bug.
- Keyboard-driven: `1..9` assign, `n` new character, `u` unattributed, `→` next. A curator
  should clear 100 ambiguous lines in 15 minutes.

## 11. Voice casting

### 11.1 Cast view per book

Table of characters: name, role, segment share, assigned profile, confidence, lock, preview
button, drift score.

Batch actions: "audition all unassigned", "re-render cast samples", "lock all".

### 11.2 Casting a character

1. Persona is pre-filled from the storypack (role, age band, register, energy).
2. Operator edits persona fields, picks candidate count (default 8), generates.
3. Candidates play inline with: duration, SNR, ASR transcript match, cosine to neighbouring
   cast members (similarity warning if > 0.75).
4. Select one → preview 3 sentences from the actual book → confirm.
5. Confirmation writes the voice profile (revision 1), copies the reference clip to the
   immutable asset store, and shows the re-render cost estimate for the book.

A "regenerate with same seed" button exists and is used more than expected: it is the fastest
way to get a second draw after a near-miss.

### 11.3 Drift review

List of chapters with `qc_status = failed_drift`, with the failing segments and their cosine
scores. Actions: re-render failed segments (new seed), re-clone from a new reference, or
accept and annotate. Accepting is audited — it is a quality decision.

## 12. Config and feature flags

### 12.1 Config versions

Every admin write that changes behaviour produces a new `config_versions` row containing a
diff. Workers pick up the new version at the next job claim and record it on the job, so a
job's behaviour is always attributable to a version.

Rollback = publish the previous version. There is no "undo" that mutates history.

### 12.2 Flags

| Flag | Default | Purpose |
|---|---|---|
| `tts.enabled` | true | global synthesis on/off (same as `cache_only`) |
| `tts.provider_fallback` | true | allow chain fallback within a job |
| `voice.cloning` | **false** | user voice cloning (needs consent flow) |
| `story.corrections_public` | false | whether corrections affect shared renders |
| `curation.enabled` | true | scheduled pre-generation |
| `curation.max_titles` | 200 | catalogue pre-generation breadth |
| `prefetch.enabled` | true | adaptive prefetch |
| `upload.pdf` | true | PDF ingestion |
| `upload.max_mb` | 25 | per-file limit |
| `search.connectors` | `["gutendex"]` | enabled catalogue connectors |
| `player.preview_first` | true | 60-second preview path |
| `exports.m4b` | true | M4B export endpoint |

Flags are typed (`bool`, `int`, `string`, `json`) and validated on write. A flag read on a hot
path is cached for 5 s per process, so a change is effectively immediate but does not hammer
Postgres.

## 13. Audit

Every mutation records:

```json
{
  "audit_id": 918273,
  "actor_id": "usr_01JB...",
  "actor_role": "admin",
  "action": "routing.chain.update",
  "target_type": "routing_rule",
  "target_id": "rr_tts_clone",
  "before": {"chain": [{"provider": "modal", "model": "qwen3-tts-1.7b-base"}]},
  "after":  {"chain": [{"provider": "runpod", "model": "qwen3-tts-1.7b-base"}]},
  "reason": "Modal incident 2026-11-20",
  "request_id": "req_01JB...",
  "created_at": "2026-11-20T14:03:11Z"
}
```

Retention: 24 months. Exportable as CSV by date range for finance and legal. The table has no
update or delete grant for the application role; a row is final.

## 14. Admin API

All under `/admin`, all require `admin` or the specific role, all return 404 (not 403) for
unauthorised access to a resource the actor cannot see.

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/overview` | dashboard aggregates |
| GET | `/admin/providers` | list with health |
| POST | `/admin/providers/{id}/probe` | run capability probe |
| PATCH | `/admin/providers/{id}` | enable/disable, credential ref |
| GET/POST | `/admin/models` | list, create |
| PATCH | `/admin/models/{id}/{version}` | edit capabilities, price entry |
| GET | `/admin/routing/{capability}` | chain + dry-run |
| PUT | `/admin/routing/{capability}` | replace chain |
| GET | `/admin/jobs` | filtered list |
| POST | `/admin/jobs/{id}/retry` | retry |
| POST | `/admin/jobs/{id}/cancel` | cancel |
| GET | `/admin/spend` | by scope/period |
| POST | `/admin/budgets` | create/update |
| POST | `/admin/kill-switch` | set mode |
| GET/PUT | `/admin/flags/{key}` | read/write |
| GET | `/admin/audit` | query |
| POST | `/admin/corrections` | apply attribution correction |
| POST | `/admin/works/{id}/merge` | merge works |
| POST | `/admin/users/{id}/purge` | GDPR deletion |

Every write endpoint requires `Idempotency-Key` and `reason`.

## 15. What the admin deliberately cannot do

| Forbidden | Why |
|---|---|
| Edit or replace audio bytes | Breaks immutability and cache correctness |
| Delete audit rows | Compliance and incident forensics |
| Change a text revision in place | Reprocessing must be additive |
| Force a specific render key | The key is derived, not chosen |
| Disable all models in a chain | Would silently remove a capability |
| Merge works without review | Irreversible from the user's perspective |
| Turn on cloning without a consent flow | Legal exposure |
| Bypass budget caps | The cap exists to be the last line of defence |

These are enforced in the service layer with explicit exceptions, not by hiding buttons.
