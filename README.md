# Open Audio Book

Self-hostable platform that turns books into multi-character audiobooks, and shares the
processed text and generated audio across users where rights allow.

**Status: Phase 1 — working end to end at $0.** Upload a book, get chapters, a cast with
per-character voices, and a downloadable, seekable chapter master. No cloud account, no
credits, no card, no paid API keys.

The design is intentionally unchanged from the specifications: one modular monolith, two
processes (API and worker), a canonical render key, and a provider boundary. Only the
launch adapters differ — SQLite and the local filesystem instead of PostgreSQL and S3, and
Kokoro-82M on CPU instead of serverless GPUs. See
[ADR-0007](docs/adr/0007-zero-cost-local-first-launch.md).

## What is verified working

- **Real speech, local**: Kokoro-82M int8 ONNX on CPU, one distinct preset per character.
  A two-chapter sample book produced 36 s and 17 s masters (AAC 64 kbps mono, 24 kHz).
- **Cross-book cache reuse**: a second identical book rendered `14 unique, 14 cached,
  0 to render` in 0.9 s, against 12.1 s for the first render.
- **Idempotency**: two consumers asking for the same chapter produce no additional audio
  rows; a duplicate enqueue is a no-op; a failed job is requeued rather than duplicated.
- **Voice blast radius**: changing one character's voice profile re-renders only that
  character's segments, not the narrator's.
- **Rights enforcement**: non-public-domain uploads are invisible to anonymous callers —
  `404` on the book page, the manifest and the media — while the operator token sees all.
- **HTTP surface**: upload, ingest polling, `202` → `200` generation, manifest with per
  segment render keys, range requests (`206`), admin-token `401`, unknown chapter `404`,
  and failed ingest marking the book `failed`.
- **119 tests** covering the render key golden vector, ingestion, attribution, the pipeline,
  the cache, the invalidation rules, the public/private catalogue split, the HTTP API
  contract, local accounts, token rotation, owner-scoped user data, the admin plane and
  worker-kill recovery.
- **Typed web app**: a Next.js App Router player with generated TypeScript types from the API's
  own OpenAPI schema; browser calls stay same-origin through rewrites, so cookie auth and media
  tokens work in dev. The zero-build `index.html` remains as the fallback served by the API.

## Quickstart

Requirements: Linux or macOS, Python ≥ 3.11, [`uv`](https://docs.astral.sh/uv/), and
`ffmpeg`/`ffprobe` on `PATH`. No Docker, no database server. Node ≥ 20 is optional — needed
only for the built Next.js web app; the zero-build player works without it.

```bash
uv venv
uv pip install -e "python[kokoro,dev]"
./scripts/setup_tts.sh          # one-time, ~116 MB of Apache-2.0 weights
./scripts/dev.sh                # API + worker, data in ./var
```

Open <http://localhost:8000>, choose a `.txt`, `.md`, `.html` or `.epub`, upload, then press
**Generate** on a chapter. The first chapter of a 100k-word book takes a few minutes on CPU;
identical lines in another book are free.

If you skip `setup_tts.sh`, the pipeline still runs using a deterministic formant synthesiser
so the flow can be exercised without the download. `/api/health` reports which one is live.

### Command line, no browser

```bash
AAB_TTS_PROVIDER=kokoro AAB_MODELS_DIR=$PWD/var/models \
  .venv/bin/python scripts/import_book.py path/to/book.epub \
  --title "Book Title" --author "Author" --chapter 0
```

`--chapter 0` renders every chapter; `--chapter 2` renders only the second. Output lands in
`var/media/books/<work>/chapters/<NNN>/master.m4a` with a `manifest.json` beside it.

### Rights and visibility

Reads and playback of **public-domain** works are public. Anything else — `user_owned`,
`unknown` — is private: it is absent from the anonymous catalogue, and its page, manifest and
audio return `404` to callers without the token. Set a token to require one for uploads and
generation:

```bash
AAB_ADMIN_TOKEN=secret ./scripts/dev.sh
curl -H "x-admin-token: secret" -X POST http://localhost:8000/api/books \
  -F "file=@book.txt" -F "title=Book Title" -F "rights_basis=user_owned"
```

`Authorization: Bearer secret` works too, and the player accepts the token in its upload form
(stored in `localStorage`). `<audio>` cannot send headers, so media requests accept
`?token=` as well — a shared-operator convenience, not a per-user credential. With no token
configured the write endpoints are open, which is the right default for a machine on your own
network and the wrong default for the public internet.

### Accounts (still $0)

For multi-user hosting, set `AAB_JWT_SECRET` (>= 32 bytes) to enable local email+password
accounts — no external identity provider, no email service. The first account becomes
`admin`; later ones are `user`. The API lives under `/api/v1/auth`:

```bash
AAB_JWT_SECRET="$(openssl rand -hex 32)" ./scripts/dev.sh
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-long-password"}'
```

Registration/login return a short-lived (30 min) bearer access token in the body and set a
30-day `aab_refresh` cookie (HttpOnly, SameSite=lax, `/api/v1/auth` path, Secure on HTTPS).
`POST /auth/refresh` rotates it — the old cookie stops working immediately — and
`POST /auth/logout` revokes the session. Pass the access token as
`Authorization: Bearer <token>` on write endpoints (or use the admin token). Uploads made by
a signed-in user carry `owner_id`, so private works are visible to that owner, to admins and
to the operator token, and to nobody else.

Signed-in users also get `/api/v1/library/` (their shelf) and `/api/v1/library/progress/…`
(listening position per chapter), both scoped to the authenticated user. When
`AAB_JWT_SECRET` is unset, these account routes return `403 auth_disabled` and the instance
keeps its single-operator behavior.

### Next.js web app (optional build)

The API serves `apps/web/index.html` at `/` — a complete player with no build step. For the
typed React app, install Node ≥ 20 and run both stacks:

```bash
npm install                       # once; npm workspaces, no pnpm/corepack needed
./scripts/dev-web.sh              # starts API + worker if needed, then Next on :3000
```

Open <http://localhost:3000>. The app has three screens: **Listen** (catalogue, cast, chapter
generation, playback, upload), **Library** (your shelf with deep links back to the player) and
**Admin** (tabbed overview, jobs, books, flags and providers). Next rewrites `/api/*` and
`/media/*` to `AAB_API_URL` (default `http://localhost:8000`), so the browser makes same-origin
requests — the HttpOnly refresh cookie and `?token=` media links work unchanged.

Types come from the schema, never from hand-written copies:

```bash
./scripts/generate_contracts.sh   # FastAPI → openapi.json → packages/contracts/src/api.d.ts
npm run typecheck                 # tsc --noEmit
npm run build                     # production build of apps/web
```

After changing any router or schema, regenerate contracts in the same commit; a stale
`api.d.ts` is a type error, not a runtime surprise. The generated files are
`packages/contracts/openapi.json` and `packages/contracts/src/api.d.ts`.

### Admin plane

`/api/v1/admin` is canonical v1 only and every route requires either `AAB_ADMIN_TOKEN` or a
signed-in `admin` account (with neither secret set, the instance is single-operator and the
routes are open):

| Group | Endpoints |
|---|---|
| Overview | `GET /overview` — queue/job/work counts, active provider, recent actions |
| Jobs | `GET /jobs` (state/kind filters + paging), `GET /jobs/{id}` (event timeline), `POST /jobs/{id}/retry`, `POST /jobs/{id}/cancel` |
| Books | `GET /works` (includes private works), `PATCH /works/{id}` — `shareable` and `status` only |
| Flags | `GET /flags`, `PUT /flags/{key}`, `DELETE /flags/{key}` |
| Providers | `GET /providers` — read-only local registry |

Retries apply to `failed`/`cancelled`/`dead` jobs and reset attempts; cancellation applies to
`queued`/`failed`/`dead` jobs (running jobs cannot be interrupted — no cooperative worker
cancellation in this version). Every mutation appends an `admin_audit` row with actor, before,
after and reason in the same transaction. The web UI requires a typed reason for every
mutation. Full audit browsing, budgets, provider routing and cast approval remain future work.

## Docker (full stack)

Everything — API, worker and the built Next.js web app — comes up with one command. Docker and
Compose are the only requirements; no local Python, Node or model download is needed.

```bash
cp .env.example .env          # optional; the defaults work out of the box
docker compose up --build -d
```

- Web: <http://localhost:3000> (typed Next.js app, proxies `/api/*` and `/media/*` to the API)
- API: <http://localhost:8000/api/v1/health> and <http://localhost:8000/docs>
- Data: named volume `aab-data` holds the SQLite DB, uploads, audio and models;
  `docker compose down -v` deletes it.

The Python image defaults to the lean `dev` extras, so speech comes from the deterministic fake
provider. For real local Kokoro voices, build with the model extras and run the one-shot
download into the same volume:

```bash
AAB_PY_EXTRAS=kokoro,dev docker compose build --no-cache
docker compose --profile models run --rm models
docker compose up -d
```

Only rights-cleared content should be uploaded to a publicly reachable instance: with no
`AAB_JWT_SECRET` or `AAB_ADMIN_TOKEN`, write endpoints are open (single-operator mode). Set
both in `.env` before exposing ports. `AAB_PUBLIC_BASE_URL` should match the browser-facing
origin; the default assumes the web app on port 3000.

`AAB_ROLE` selects the process inside the Python image (`api`, `worker`, `all`, `models`); a
bare `docker run` defaults to `all`, starting API and worker together. CI builds both images and
boots the stack on every push.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `AAB_HOME` | `./var` | Root for the database, media and models |
| `AAB_DATABASE_URL` | `sqlite:///$AAB_HOME/aab.db` | Any SQLAlchemy URL; Postgres for scale |
| `AAB_MEDIA_DIR` | `$AAB_HOME/media` | Segment WAVs, chapter masters, manifests, uploads |
| `AAB_MODELS_DIR` | `$AAB_HOME/models` | Kokoro ONNX weights and voice bank |
| `AAB_TTS_PROVIDER` | `auto` | `auto`, `kokoro` or `fake`; `auto` uses Kokoro when present |
| `AAB_ADMIN_TOKEN` | empty | Shared token for write endpoints; empty means open |
| `AAB_JWT_SECRET` | empty | Enables local accounts when set (use ≥ 32 bytes); empty = single-operator |
| `AAB_PUBLIC_BASE_URL` | `http://localhost:8000` | Used when building absolute URLs; HTTPS makes the refresh cookie Secure |
| `AAB_API_URL` | `http://localhost:8000` | Where the Next.js dev server proxies `/api/*` and `/media/*` |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Bind address for `scripts/dev.sh` |

## How the audio is keyed

Every segment is identified by `rk1:` — a SHA-256 over canonical JSON containing the text,
its phoneme form, language, **voice identity**, model weights hash, discretised performance
directives, policy version and a seed derived from the text.

The speaker slot is the *voice*, never a per-book character id. That is what allows the same
line, spoken by the same voice, to be reused across two different books: in the verified run
the second book paid for nothing. A character's identity is a voice-preset binding
(`characters` → `voice_profiles`), so changing one character's voice invalidates only that
character's segments.

## Layout

```
apps/web/index.html          zero-build fallback player served by the API at /
apps/web/app/                Next.js App Router pages: listen, library, admin
apps/web/components/         typed player, sidebar, upload, auth and header components
apps/web/lib/                generated-type API client, auth context, helpers
packages/contracts/          openapi.json + generated src/api.d.ts, re-exported as @aab/contracts
services/api/                layered HTTP surface: routers → services → aab_db
                             main.py (entrypoint) · app.py (factory) · dependencies · errors
                             schemas/ (pydantic IO models) · routers/ · services/ (use cases)
services/worker/worker/      job runner; ingest and tts handlers
python/src/aab_core/         ids, errors, settings, hashing
python/src/aab_db/           schema and every SQL statement
python/src/aab_ingest/       TXT, Markdown, HTML, EPUB → chapters
python/src/aab_story/        cast extraction, gender priors, speaker attribution
python/src/aab_tts/          render key, normalisation, segmentation
python/src/aab_audio/        WAV writing, AAC mastering, manifests
python/src/aab_providers/    the only place vendor SDKs may live
python/src/aab_jobs/         claim/lease/retry/requeue, drain loop
scripts/                     dev.sh, dev-web.sh, generate_contracts.sh, setup_tts.sh,
                             export_openapi.py, import_book.py, smoke.sh,
                             docker-entrypoint.sh (AAB_ROLE dispatch)
Dockerfile                   Python image: API, worker, model download
Dockerfile.web               multi-stage Next.js build → next start
compose.yaml                 api + worker + web, shared aab-data volume, optional models profile
.env.example                 Docker configuration template
docs/                        ADRs, specs, runbooks, licence register
```

## Tests

```bash
.venv/bin/python -m pytest python/tests -q
./scripts/smoke.sh            # HTTP end to end; uses the fake voice by default
npm run typecheck             # Next.js + generated contract types
npm run build                 # production web build
```

The same checks run in `.github/workflows/ci.yml` on every push and pull request, including a
diff check that fails if generated contracts were not regenerated after an API change.

`python/tests/test_resilience.py` is the worker-kill drill: a render is interrupted between
batches, the job keeps its live lease, a second worker refuses it, and recovery after lease
expiry produces exactly one render per key with no orphan claims.

The golden render-key vector in `python/tests/test_render_key.py` must not change without a
policy-version bump. It is the contract that keeps existing audio reusable.

## What is deliberately absent from the $0 launch

Nothing below is required to run the product; each is a later, independently revertible
opt-in, and the adapter boundary already exists.

| Absent | Why it waits | What enabling it touches |
|---|---|---|
| Cloud storage + CDN | local disk is enough for one host | media root / URL issuance |
| Postgres + pgvector | one writer is the launch shape | `AAB_DATABASE_URL` only |
| Managed identity (Cognito/OIDC) | local email+password accounts with JWT + rotating refresh | OIDC/enterprise SSO when paid |
| GPU TTS (Qwen3-TTS) | needs a paid account | one provider adapter |
| LLM story analysis | rules are free and deterministic | one provider adapter |
| Audit browsing, budgets, provider routing | admin plane ships with job/book/flag controls; costing has no data at $0 | schema + admin UI |
| Quotas, billing, multi-tenant libraries | there is no spend and no tenant yet | API + schema |

## Constraints that shape every decision

- **No DRM bypass, no licence laundering.** Formats are parsed, never decrypted. Only
  rights-cleared content is shared system-wide; user uploads default to private.
- **Public domain is jurisdictional.** Every work carries a `rights_basis` and territory;
  sharing is a query-time predicate, not an assumption.
- **Characters outlive models.** Voices are pinned to a preset or reference clip plus a model
  binding. A fallback model produces a *new render set*, never a new voice mid-book.
- **No silent substitution.** The manifest records model family, policy version and the
  render key for every segment.
- **No Kafka, Kubernetes, dedicated vector database or permanent GPU** without a measured
  reason. At launch there is no queue broker beyond the `jobs` table.

## Read next

| Document | Answers |
|---|---|
| [`docs/adr/`](docs/adr/) | Which decisions are locked, and why |
| [`docs/specs/01-product-requirements.md`](docs/specs/01-product-requirements.md) | What we are building and for whom |
| [`docs/specs/07-infrastructure-and-cost.md`](docs/specs/07-infrastructure-and-cost.md) | The $0 profile, and what each paid step buys |
| [`docs/specs/09-project-structure.md`](docs/specs/09-project-structure.md) | Repository shape and boundary rules |
| [`docs/specs/10-directory-map-and-flows.md`](docs/specs/10-directory-map-and-flows.md) | Directory map and flowcharts for every runtime path |
| [`docs/CHECKLIST.md`](docs/CHECKLIST.md) | What is done, measured, and still open |
| [`docs/licences/register.md`](docs/licences/register.md) | Approved, restricted and blocked dependencies |
