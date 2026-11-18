# 10. Directory map and runtime flows

This is the **as-built** map of the $0 launch system: where each directory sits in the call
graph, and every flow that a request, job, file or build takes through it. Spec
[02](02-system-architecture.md) describes the *target* architecture (Postgres, S3, Cognito,
paid inference); this document describes the code that runs today. Where the two differ,
ADR-0007 is the decision record.

Diagrams are Mermaid. Node labels name real directories, modules, routes or tables so the chart
can be used as a navigation index.

## 0. One-screen overview

This is the **map of maps**. It deliberately hides implementation detail so the whole system fits
on one screen. Follow the section numbers in each node to the detailed diagram below; the
[flow index](#28-flow-index) is the text-only version of the same map.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 32, "rankSpacing": 42}}}%%
flowchart LR
  subgraph EDGE["Enter"]
    WEBCLIENT["Web · fallback · CLI<br/>§3 · §5 · §23"]
    BUILD["Contracts · Docker · CI · smoke<br/>§4 · §6 · §7 · §8"]
  end

  subgraph HTTPREQ["Request side"]
    GATE["Gates + errors<br/>§9 · §27"]
    BOOKS["Upload + whole-book<br/>§10 · §24"]
    READS["Read · rights · media<br/>§11"]
    AUTHN["Auth + library<br/>§12 · §20"]
    PLAY["Audio + polling<br/>§13 · §25"]
    ADMIN["Admin + audit<br/>§21"]
  end

  subgraph STATE["Shared state"]
    DB[("aab_db + media<br/>§2")]
    QUEUE[("jobs + job_events<br/>§14")]
  end

  subgraph WORK["Worker side"]
    LOOP["Worker loop<br/>§26"]
    INGEST["Ingest<br/>§15"]
    RENDER["Render<br/>§16"]
    CACHE["Cache + provider<br/>§17 · §18"]
    MASTER["Mastering<br/>§19"]
    RECOVER["Crash recovery<br/>§22"]
  end

  WEBCLIENT --> GATE
  BUILD --> WEBCLIENT
  BUILD --> GATE
  GATE --> BOOKS
  GATE --> READS
  GATE --> AUTHN
  GATE --> PLAY
  GATE --> ADMIN
  BOOKS --> QUEUE
  PLAY --> QUEUE
  QUEUE --> LOOP
  LOOP --> INGEST
  LOOP --> RENDER
  INGEST --> DB
  RENDER --> CACHE
  RENDER --> DB
  CACHE --> MASTER
  MASTER --> DB
  READS --> DB
  AUTHN --> DB
  ADMIN --> DB
  RECOVER -.-> QUEUE
  RECOVER -.-> CACHE
```

If you need literal pan/zoom over every diagram at once, the alternative is a standalone HTML/SVG
viewer; Mermaid in Markdown cannot do that natively.

## 1. Directory dependency map

```mermaid
flowchart TB
  subgraph CLIENT["Client"]
    WEBUI["apps/web/app/ · components/ · lib/<br/>typed Next.js player"]
    FALLBACK["apps/web/index.html<br/>zero-build player"]
    OPERATOR["curl · scripts/import_book.py"]
  end

  subgraph CONTRACTS["packages/contracts/"]
    OPENAPI["openapi.json<br/>generated from FastAPI"]
    TYPES["src/api.d.ts + src/index.ts<br/>@aab/contracts"]
  end

  subgraph HTTP["services/api/"]
    ROUTERS["routers/<br/>meta · books · chapters · jobs · media<br/>auth · library · admin · web"]
    SVC["services/<br/>use cases"]
    DEP["dependencies.py · errors.py<br/>gates + error envelope"]
    APP["app.py · main.py<br/>create_app + uvicorn"]
  end

  subgraph WORKER["services/worker/worker/"]
    MAIN["main.py<br/>poll loop + handlers"]
    INGEST["jobs/ingest.py"]
    TTS["jobs/tts.py · jobs/common.py"]
  end

  subgraph PY["python/src/"]
    CORE["aab_core/<br/>settings · ids · errors"]
    DB["aab_db/<br/>models.py + all SQL"]
    ING["aab_ingest/ · aab_story/ · aab_tts/"]
    AUDIO["aab_audio/<br/>WAV · AAC · manifest"]
    PROV["aab_providers/<br/>fake · kokoro"]
    JOBS["aab_jobs/<br/>claim · lease · retry · drain"]
  end

  subgraph BUILD["Build and operations"]
    SCRIPTS["scripts/<br/>dev · dev-web · smoke · setup_tts<br/>export_openapi · generate_contracts"]
    DOCKER["Dockerfile · Dockerfile.web · compose.yaml<br/>scripts/docker-entrypoint.sh"]
    CI[".github/workflows/ci.yml"]
  end

  subgraph DATA["Data (var/ locally, /data volume in Docker)"]
    SQLITE[("aab.db + WAL")]
    MEDIA["media/<br/>uploads · segments · books · models"]
  end

  WEBUI -->|"same-origin /api/* and /media/*"| ROUTERS
  WEBUI -. "compile-time types" .-> TYPES
  FALLBACK --> ROUTERS
  OPERATOR --> ROUTERS
  OPERATOR --> MAIN
  TYPES -. "generated from" .-> OPENAPI
  APP --> ROUTERS
  ROUTERS --> DEP
  ROUTERS --> SVC
  SVC --> DB
  ROUTERS --> FALLBACK
  MAIN --> JOBS
  MAIN --> INGEST
  MAIN --> TTS
  INGEST --> ING
  INGEST --> DB
  TTS --> DB
  TTS --> AUDIO
  TTS --> PROV
  JOBS --> DB
  CORE --> DB
  CORE --> APP
  CORE --> MAIN
  SCRIPTS --> OPENAPI
  SCRIPTS --> APP
  DOCKER --> APP
  DOCKER --> MAIN
  CI --> SCRIPTS
  CI --> DOCKER
  DB --> SQLITE
  TTS --> MEDIA
  SVC --> MEDIA
```

Import direction: `aab_core` imports nothing from the project; `aab_db` owns every SQL statement;
only `aab_providers` knows a vendor exists. The HTTP layer never imports worker handlers, and
the worker never imports FastAPI.

## 2. Data directory flow

```mermaid
flowchart LR
  HOME["AAB_HOME<br/>./var locally · /data in Docker"]
  HOME --> DB[("aab.db<br/>SQLite + WAL")]
  HOME --> MEDIA["media/"]
  HOME --> MODELS["models/<br/>kokoro-v1.0.int8.onnx<br/>voices-v1.0.bin"]
  HOME --> UPLOADS["uploads/<br/>original source files"]
  MEDIA --> SEG["segments/aa/<br/>content-addressed rk1 WAVs"]
  MEDIA --> BOOKS["books/{work_id}/chapters/{ordinal}/"]
  BOOKS --> MASTER["master.m4a<br/>master.wav without ffmpeg"]
  BOOKS --> MANIFEST["manifest.json<br/>complete flag + per-segment keys"]
  DB -. "audio_renders.asset_id → assets.path" .-> SEG
  DB -. "render_sets.manifest_path" .-> MANIFEST
```

Rendered bytes are immutable and content-addressed by `render_key`; the database stores paths,
not blobs. Deleting `aab.db` leaves orphaned audio; deleting `media/` breaks every render row.

## 3. Web delivery flow

```mermaid
flowchart LR
  subgraph LOCAL["Local, no build"]
    A1["Browser → :8000 /"]
    A2["services/api/routers/web.py"]
    A3["apps/web/index.html"]
    A1 --> A2 --> A3
  end
  subgraph NEXT["Next.js :3000"]
    B1["Browser → :3000 /"]
    B2["app/page.tsx · /library · /admin"]
    B3["next.config.ts rewrites"]
    B4["AAB_API_URL<br/>localhost:8000 locally · api:8000 in Docker"]
    B1 --> B2 --> B3 --> B4
  end
  B4 --> API["services/api/"]
  API --> DB[("aab_db")]
```

The zero-build page is served straight from the API and needs no Node toolchain. The typed app
keeps the browser same-origin (`/api/*`, `/media/*`), which is what lets HttpOnly refresh cookies
and `?token=` media URLs behave identically in both modes.

## 4. Contract generation flow

```mermaid
flowchart LR
  APP["services/api/app.py<br/>create_app()"] --> EXPORT["scripts/export_openapi.py<br/>fake provider + in-memory DB"]
  EXPORT --> JSON["packages/contracts/openapi.json<br/>deterministic, sorted"]
  GEN["scripts/generate_contracts.sh"] --> EXPORT
  GEN --> OTS["npm run contracts:generate<br/>openapi-typescript"]
  JSON --> OTS
  OTS --> DTS["packages/contracts/src/api.d.ts<br/>generated — never hand-edited"]
  DTS --> IDX["packages/contracts/src/index.ts<br/>hand-written aliases"]
  IDX --> CLIENT["apps/web/lib/api.ts<br/>typed API client"]
  CLIENT --> UI["app/ · components/"]
  CI["ci.yml: regenerate + git diff --exit-code"] -. "fails on drift" .- JSON
```

The FastAPI schema is the single source of truth. `api.d.ts` and `openapi.json` are committed so
the web image can build with Node only.

## 5. Local development flow

```mermaid
flowchart TD
  A["./scripts/dev.sh"] --> B["AAB_HOME defaults to ./var"]
  B --> C{"venv exists?"}
  C -- no --> D["uv venv"]
  C -- yes --> E{"fastapi importable?"}
  D --> E
  E -- no --> F["uv pip install -e python[kokoro,dev]"]
  E -- yes --> G["start uvicorn :8000"]
  F --> G
  G --> H["start worker poll loop"]
  H --> I["wait -n; trap kills both"]

  J["./scripts/dev-web.sh"] --> K{"API healthy on AAB_API_URL?"}
  K -- no --> A
  K -- yes --> L["npm run dev → Next :3000"]
```

## 6. Docker runtime flow

```mermaid
flowchart TB
  ENV[".env.example → .env<br/>ports, provider, secrets, extras"] --> CMP["docker compose up --build -d"]
  CMP --> PYIMG["Dockerfile<br/>python:3.12-slim · ffmpeg · uid 10001<br/>pip install -e python[dev|kokoro,dev]"]
  CMP --> WEBIMG["Dockerfile.web<br/>deps → builder → runner<br/>next start :3000"]
  PYIMG --> EP["scripts/docker-entrypoint.sh<br/>AAB_ROLE"]
  EP --> API["api role: uvicorn :8000 + healthcheck"]
  EP --> WORK["worker role: poll loop, waits for api healthy"]
  EP --> MOD["models profile: one-shot setup_tts.sh"]
  WEBIMG --> WEB["web role: rewrites → http://api:8000"]
  API --> VOL[("aab-data volume<br/>/data: db, media, models")]
  WORK --> VOL
  MOD --> VOL
  WEB -->|"/api/* and /media/*"| API
  CMP --> CI["ci.yml docker job:<br/>config → build → up → health → down -v"]
```

`AAB_ROLE=all` (the default for a bare `docker run`) starts the API and worker in one container;
Compose runs them as separate services. Secrets stay in `.env`, never in the image.

## 7. CI flow

```mermaid
flowchart TD
  PUSH["push / pull_request"] --> VJOB
  PUSH --> DJOB
  subgraph VJOB["verify"]
    V1["setup-python 3.11 + setup-uv + setup-node 20"] --> V2["uv venv; uv pip install -e python[dev]"]
    V2 --> V3["npm ci"]
    V3 --> V4["pytest python/tests"]
    V4 --> V5["scripts/smoke.sh — HTTP e2e, fake voice"]
    V5 --> V6["generate contracts; git diff --exit-code"]
    V6 --> V7["npm run typecheck"]
    V7 --> V8["npm run build"]
  end
  subgraph DJOB["docker"]
    D1["docker compose config --quiet"] --> D2["docker compose build"]
    D2 --> D3["docker compose up -d"]
    D3 --> D4["poll :8000/api/v1/health and :3000/"]
    D4 --> D5["docker compose down -v, always"]
  end
```

## 8. HTTP smoke flow

```mermaid
sequenceDiagram
  participant S as scripts/smoke.sh
  participant API as API :8123
  participant W as Worker
  S->>API: GET /api/v1/health (provider, speech)
  S->>API: POST /api/v1/books (multipart fixture)
  API->>API: create work + revision, enqueue ingest
  API-->>S: 201 book_id
  loop until work.status = ready
    S->>API: GET /api/v1/books/{id}
    API->>W: ingest.revision via jobs table
  end
  S->>API: POST /api/v1/chapters/{id}/audio
  API-->>S: 200 or 202
  loop until manifest ready
    S->>API: GET /api/v1/chapters/{id}/audio
    W->>W: tts.chapter render + master
  end
  API-->>S: 200 manifest (rk1 keys, complete)
  S->>API: GET /media/.../master.m4a
  API-->>S: 200 full file
  S->>API: GET master with Range: bytes=0-99
  API-->>S: 206 Partial Content
  S->>API: GET /api/v1/books
  API-->>S: 200 catalogue contains the public book
```

## 9. Request pipeline and error envelope

```mermaid
flowchart TD
  REQ["HTTP request<br/>/api/v1 or /api alias"] --> APP["services/api/app.py<br/>create_app: routers under both prefixes"]
  APP --> ROUTER["matched routers/*.py"]
  ROUTER --> GATE{"dependencies.py<br/>require_user / require_writer<br/>require_admin / can_view"}
  GATE -- denied --> ERR["errors.py<br/>one JSON error envelope<br/>401 · 403 · 404 · 409 · 416 · 422"]
  GATE -- allowed --> SVC["services/*.py<br/>use case"]
  SVC --> DB[("aab_db")]
  DB --> RESULT["pydantic schema in services/api/schemas/"]
  RESULT --> RESP["JSON or /media bytes"]
```

`/api/v1` is canonical; `/api` is an alias for the shared routers. Auth, library and admin are
v1-only. `require_writer` accepts the operator token or any authenticated account;
`require_admin` accepts the operator token or a JWT with `role=admin` and gates every admin route.
`require_user` requires a real account — the operator token alone does not satisfy it.
`GET /api/v1/jobs/{job_id}` has no gate; job ids are opaque but unscoped.

## 10. Upload and ingest request flow

```mermaid
sequenceDiagram
  participant U as Web / operator
  participant API as routers/books.py
  participant SVC as services/books.py
  participant DB as aab_db
  participant W as worker ingest.revision
  U->>API: POST /api/v1/books (multipart file + rights_basis)
  API->>SVC: validate extension, title, author, rights
  SVC->>SVC: copy source into media/uploads/
  SVC->>DB: create_work(shareable = rights cleared)
  SVC->>DB: create_revision(source_path, language)
  SVC->>DB: enqueue(ingest.revision, idempotency_key = ingest:{revision_id})
  DB-->>API: work id
  API-->>U: 201 book_id
  W->>DB: claim job (lease)
  W->>W: parse → chapters → cast → attribution → voice profiles → segments
  W->>DB: mark revision + work ready (or failed)
```

`rights_basis` is per work and `shareable` is derived from it at creation; `can_view` is a
query-time predicate, never an assumption. The UI defaults new uploads to `public_domain_us`,
but a parse failure marks both revision and work `failed` instead of leaving them pending.
`POST /books/{id}/generate` and `POST /chapters/{id}/audio` use `require_writer` only — they do
**not** call `can_view` — while the corresponding `GET` routes do.

## 11. Read, rights and media flow

```mermaid
flowchart TD
  GET["GET /books · /books/{id} · /chapters/{id}/audio · /media/{path}"] --> CALLER{"resolve caller<br/>JWT / operator token / anonymous"}
  CALLER --> VIS{"can_view(work, caller) · shareable/owner check"}
  VIS -- "shareable · rights cleared" --> OK["200 · list entry / book page / manifest / bytes"]
  VIS -- "owner or admin" --> OK
  VIS -- "private and not owner" --> NF["404 not_found<br/>do not confirm existence"]
  OK --> MEDIA{"path under media/"}
  MEDIA -- "Range header" --> R206["206 Partial Content + Content-Range"]
  MEDIA -- "no Range" --> R200["200 full file"]
  OK --> TOKEN{"audio element?"}
  TOKEN -- yes --> Q["?token= JWT/operator credential on /media only<br/>an audio element cannot send headers"]
```

The anonymous catalogue only contains works whose rights allow sharing. A private work is absent
from listings and returns `404` on its page, manifest and media to callers without a token. Media
resolves paths against `media_dir` with a traversal guard, and non-admins may only read
`media/books/{work_id}/...` for a shareable work they own; `uploads/` and raw `segments/` are
operator-only. `?token=` is accepted **only** on `/media`, because an `<audio>` element cannot
send headers. Range support is `bytes=start-end` with an open end allowed and the end clamped to
the file size; suffix ranges, `ETag`/`If-Range` and `HEAD` are not implemented.

## 12. Authentication flow

```mermaid
flowchart TD
  subgraph ENABLED["AAB_JWT_SECRET set"]
    REG["POST /api/v1/auth/register"] --> FIRST{"first user?"}
    FIRST -- yes --> ADMIN["role = admin"]
    FIRST -- no --> USER["role = user"]
    LOGIN["POST /api/v1/auth/login"] --> TOK["HS256 access token in memory<br/>30 min"]
    LOGIN --> COOKIE["aab_refresh cookie<br/>HttpOnly · SameSite=lax · 30 d<br/>SHA-256 digest in sessions"]
    COOKIE --> REF["POST /auth/refresh<br/>rotate digest, revoke old"]
    COOKIE --> OUT["POST /auth/logout<br/>delete session"]
    TOK --> GATE["require_user gates library/progress<br/>require_admin gates admin"]
  end
  subgraph DISABLED["AAB_JWT_SECRET unset"]
    SO["single-operator mode<br/>account routes 403 auth_disabled<br/>admin routes open"]
  end
```

The browser keeps the access token in memory only and calls `/auth/refresh` on mount; the refresh
cookie is scoped to `/api/v1/auth` and is `Secure` when `AAB_PUBLIC_BASE_URL` is HTTPS. Roles are
read from JWT claims at request time, not re-read from `users.role`. Works carry `owner_id`, while
the table is `library_entries` and is scoped by `user_id`. Private works are visible to the owner,
admins and the operator token only.

## 13. Audio generation and playback flow

```mermaid
sequenceDiagram
  participant U as Web / operator
  participant API as routers/chapters.py + services/audio.py
  participant DB as aab_db
  participant W as worker tts.chapter
  U->>API: POST /api/v1/chapters/{id}/audio
  API->>API: resolve provider → model_family
  API->>DB: get_or_create_render_set(chapter, revision, policy, model)
  API->>DB: enqueue(tts.chapter, idempotency_key = tts:{render_set_id})
  DB-->>API: render_set
  API-->>U: 202 queued/rendering (POST is always 202)
  loop poll GET /audio until manifest
    U->>API: GET /api/v1/chapters/{id}/audio
    API->>API: can_view(work, caller) else 404
    API-->>U: 202 rendering/queued/preparing / 200 manifest
  end
  W->>DB: claim tts.chapter job
  W->>W: plan → cache → claims → synthesize → master → manifest
  W->>DB: set_render_outputs(ready) + finish_job
  U->>API: GET /media/books/{work}/chapters/{n}/master.m4a
  API-->>U: 200 / 206 with seek support
```

The player deep link `/?book=<id>` restores a selected work, and
`/api/v1/library/progress/…` restores the listening position per chapter.

## 14. Job lifecycle

```mermaid
flowchart TD
  ENQ["enqueue(kind, target, idempotency_key)"] --> DUP{"key exists?"}
  DUP -- "yes: queued/running" --> NOOP["return existing id · no new job"]
  DUP -- "yes: failed/cancelled/dead" --> REQ["requeue same row: queued<br/>attempts 0 · leases/error cleared<br/>job_events: requeued"]
  DUP -- no --> Q["state = queued<br/>job_events: queued"]
  REQ --> Q
  Q --> CLAIM["aab_jobs.run_once → requeue_stale → claim_job<br/>state = running · lease 15 min · attempts + 1"]
  CLAIM --> HANDLER{"handler for kind?"}
  HANDLER -- no --> FAIL["fail_job: unknown_kind, not retryable"]
  HANDLER -- "ingest.revision" --> I["services/worker/jobs/ingest.py"]
  HANDLER -- "tts.chapter" --> T["services/worker/jobs/tts.py"]
  I --> OK{"handler returned?"}
  T --> OK
  OK -- yes --> DONE["finish_job → succeeded<br/>job_events: succeeded"]
  OK -- "AabError / ProviderError" --> RETRY{"retryable and attempts < max_attempts?"}
  RETRY -- yes --> Q
  RETRY -- no --> FAIL
  OK -- "unexpected Exception" --> FAIL2["fail_job: internal_error, retryable"]
  FAIL2 --> Q
  STALE["running job whose lease expired"] --> STALEQ["requeue_stale on next run_once<br/>state = queued · lease cleared<br/>no event · no dead state · attempts unchanged"]
  STALEQ --> CLAIM
  ADMIN["admin retry / cancel"] --> RETRYA["retry: failed/cancelled/dead → queued<br/>attempts 0 · event admin_retry · audited"]
  ADMIN --> CANCEL["cancel: queued/failed/dead → cancelled<br/>event admin_cancel · audited<br/>running jobs cannot be cancelled"]
  RETRYA --> Q
```

There is no broker: the `jobs` table is the queue. `drain()` is used by tests, `--once` and the
CLI; the long-running worker polls the same functions. Running jobs cannot be cancelled in v1.

## 15. Ingest handler flow

```mermaid
flowchart LR
  J["claimed ingest.revision<br/>target_id = revision id"] --> LOAD["load revision + source file"]
  LOAD --> PARSE["aab_ingest<br/>TXT · Markdown · HTML · EPUB<br/>boilerplate + chapter headings + chunks"]
  PARSE --> STORY["aab_story<br/>cast extraction · name folding · gender priors<br/>quotative / pronoun / alternation attribution"]
  STORY --> SEG["aab_tts.speakable + segmentation<br/>normalised text, directives, gap_after_ms"]
  SEG --> WRITE["aab_db: chapters · blocks · characters<br/>voice_profiles · narration_segments<br/>performance_directives"]
  PARSE -. "unsupported format / parse error" .-> FAILED["revision + work → failed"]
  WRITE --> STATUS["revision + work → ready"]
```

Each narrator and character gets a distinct preset in `voice_profiles`; the character id is
never part of a render key.

## 16. TTS render handler flow

```mermaid
flowchart TD
  J["claimed tts.chapter<br/>target_id = render_set id"] --> LOAD["load render_set, chapter, work,<br/>segments, voice profiles"]
  LOAD --> PLAN["for each segment:<br/>render_key(text, phon, lang, spk, voice,<br/>model, params, perf, policy, pre)"]
  PLAN --> EXIST["existing_render_keys(unique keys)"]
  EXIST --> RELEASE["release_claims(existing keys)<br/>drop leftovers from a killed worker"]
  RELEASE --> MISSING["missing keys"]
  MISSING --> CLAIM["claim_render_keys(missing, job id, 20 min)<br/>steals expired claims"]
  CLAIM --> BATCH["_batches: group by voice profile,<br/>16 lines per batch"]
  BATCH --> SYNTH["_render_batch → provider.synthesize(lines, voice)"]
  SYNTH --> WRITE["write_wav → insert_asset → insert_render<br/>keyed by rk1 render_key"]
  WRITE --> PROG["update_progress + update_render_progress"]
  PROG --> UNCLAIM["release_claims(all claimed keys)"]
  UNCLAIM --> FINAL["_finalise"]
  FINAL --> MASTER["renders_for_keys → build_master<br/>manifest.json → set_render_outputs<br/>ready / ready_with_gaps"]
  SYNTH -. "provider omits a line" .-> GAP["missing key becomes a gap<br/>complete=false but manifest still written"]
```

The seed inside `params` is derived from the text, not from the segment id. That is what makes
an identical line in two books resolve to the same key. Claims make concurrent workers unable to
synthesise the same key twice; expired claims are stolen on the next attempt.

## 17. Cache reuse and voice invalidation

```mermaid
flowchart TD
  A["two books contain the same line"] --> B{"same text · phonemes · language · voice · model · performance · policy?"}
  B -- yes --> C["same rk1 key<br/>existing_render_keys hit<br/>0 new renders"]
  B -- "no: voice profile revision changed" --> D["only that character's keys change<br/>other characters and narrator still cached"]
  B -- "no: model family / weights changed" --> E["new render set<br/>new keys under the new model identity"]
  C --> F["audio_renders row reused across books<br/>shareable flag from the work"]
  D --> G["new render set for the work; old audio remains immutable"]
  E --> G
```

A fallback model therefore produces a *new render set*, never a new voice mid-book. The manifest
records model family, policy version and every render key so substitutions are never silent.

## 18. Provider selection

```mermaid
flowchart TD
  S["AAB_TTS_PROVIDER"] --> A{"auto or kokoro?"}
  A -- "kokoro" --> K["KokoroProvider(settings)<br/>numpy + kokoro_onnx + weights required<br/>unavailable → raise"]
  A -- "auto" --> TRY{"Kokoro import and weights OK?"}
  TRY -- yes --> K
  TRY -- no --> F["FakeProvider<br/>deterministic formant speech"]
  A -- "fake" --> F
  A -- "unrecognised value" --> F
  K --> ID["model_id + model_version + weights_sha256<br/>become the model block of the render key"]
  F --> ID2["fake-formant identity<br/>still a full pipeline, no downloads"]
```

Only `aab_providers` knows a vendor exists. Health reports which provider is live; a paid
provider would be one more module plus a registry entry (ADR-0005).

## 19. Mastering and delivery

```mermaid
flowchart TD
  M["build_master(paths, gaps, out_base)"] --> FF{"ffmpeg on PATH?"}
  FF -- yes --> CONCAT["concat list → raw.wav → loudnorm<br/>→ AAC 64 kbps mono 24 kHz .m4a"]
  CONCAT --> PROBE["ffprobe duration when available"]
  FF -- no --> STD["stdlib wave: read, peak-normalise,<br/>join with silence → .wav"]
  PROBE --> MAN["manifest.json: duration, complete,<br/>per-segment keys and speakers"]
  STD --> MAN
  MAN --> SERVE["services/api/routers/media.py<br/>GET /media/{path} · Range → 206"]
```

The ffmpeg branch produces `.m4a` and is used whenever the binary is present; the Docker image
installs it. Without ffmpeg the stdlib branch produces `.wav`. `ffprobe` duration parsing also
falls back to a `wave` frame count on any failure.

## 20. Library and progress

```mermaid
flowchart LR
  USER["signed-in user · require_user"] --> LIB["GET /api/v1/library/ · POST/DELETE works/{id}<br/>library_entries scoped by user_id"]
  USER --> PROG["PUT/GET /api/v1/library/progress/{chapter}<br/>GET works/{id}/progress<br/>playback_progress scoped by user_id"]
  LIB --> UI["apps/web/app/library/page.tsx<br/>shelf + deep link /?book=id"]
  PROG --> PLAY["apps/web/components/PlayerApp.tsx + PlayerBar.tsx<br/>resume playback"]
  OWNER["another account / operator token / anonymous"] --> DENY["401 login required or 404 · no cross-user data"]
```

Account routes return `403 auth_disabled` when `AAB_JWT_SECRET` is unset; the instance keeps its
single-operator behavior. Adding a work or saving progress validates that the id exists but does
not call `can_view`; `user_id` scoping prevents cross-user library and progress reads.

## 21. Admin mutations and audit

```mermaid
flowchart TD
  UI["apps/web/app/admin/page.tsx<br/>overview · jobs · books · flags · providers"] --> TYPE["apps/web/lib/api.ts api.admin*"]
  TYPE --> GATE["require_admin(request)"]
  GATE --> TX["services/api/services/admin.py<br/>one engine.begin() transaction"]
  TX --> CHANGE["retry · cancel · work shareable/status<br/>flag set (upsert) / delete"]
  TX --> AUDIT["record_admin_action<br/>admin_audit row: actor · before · after · reason"]
  CHANGE --> EVENTS["job_events: admin_retry / admin_cancel"]
  PROVIDERS["GET providers · read-only registry"] --> GATE
```

Every admin route is gated by `require_admin` at the router level. The exact canonical routes are:

| Route | Purpose |
|---|---|
| `GET /api/v1/admin/overview` | counts, queue depth, recent `admin_audit` rows |
| `GET /api/v1/admin/jobs` | filtered/paginated job list |
| `GET /api/v1/admin/jobs/{job_id}` | job detail plus `job_events` timeline |
| `POST /api/v1/admin/jobs/{job_id}/retry` | `failed/cancelled/dead` → `queued`, attempts reset, `admin_retry` event |
| `POST /api/v1/admin/jobs/{job_id}/cancel` | `queued/failed/dead` → `cancelled`, `admin_cancel` event; running jobs are not cancelable |
| `GET /api/v1/admin/works` | all works, including private |
| `PATCH /api/v1/admin/works/{work_id}` | change `shareable` and/or `status` |
| `GET /api/v1/admin/flags` | list feature flags |
| `PUT /api/v1/admin/flags/{key}` | upsert a flag |
| `DELETE /api/v1/admin/flags/{key}` | delete a flag |
| `GET /api/v1/admin/providers` | read-only provider registry |

That is eleven routes; the UI groups them into five tabs (overview, jobs, books, flags,
providers). Every mutation requires a typed reason; the audit row and the change commit in one
`engine.begin()` transaction. Full audit browsing, budgets and provider routing remain deferred.

## 22. Crash recovery and the kill drill

```mermaid
sequenceDiagram
  participant W1 as worker 1
  participant DB as jobs + render_claims
  participant W2 as worker 2
  W1->>DB: claim tts.chapter (lease 15 min)
  W1->>DB: claim render keys, write first batch
  W1--xW1: SystemExit — simulated SIGKILL
  Note over W1,DB: job stays running, claims held, no _finalise
  W2->>DB: run_once → requeue_stale (lease still live)
  DB-->>W2: no job — refuses to duplicate work
  W1->>DB: expire lease and claims (timeout)
  W2->>DB: requeue_stale → queued, claim job
  W2->>DB: existing keys skipped, orphan claims released
  W2->>DB: render remaining batches, release claims
  W2->>DB: set_render_outputs(ready), finish_job
  Note over W2: manifest complete, one render per key
```

`python/tests/test_resilience.py` performs this drill. It also exposed the orphan-claim leak:
keys rendered before the kill were never released on recovery, fixed by
`release_claims(existing)` during planning.

## 23. CLI import flow

```mermaid
flowchart LR
  CMD["scripts/import_book.py path/to/book.epub<br/>--title --author --chapter"] --> SET["AAB_TTS_PROVIDER, AAB_MODELS_DIR, AAB_HOME"]
  SET --> STORE["copy source into media/uploads/"]
  STORE --> CREATE["create work + revision + enqueue ingest"]
  CREATE --> DRAIN["aab_jobs.drain(engine, worker_id, HANDLERS, settings)"]
  DRAIN --> OUT["media/books/{work}/chapters/{n}/master.m4a<br/>+ manifest.json"]
```

`--chapter 0` renders every chapter; `--chapter 2` renders only the second.

## 24. Whole-book generation flow

```mermaid
sequenceDiagram
  participant U as Web / operator
  participant API as routers/books.py + services/audio.py
  participant DB as aab_db
  participant W as worker
  U->>API: POST /api/v1/books/{id}/generate
  API->>API: require_writer (no can_view)
  API->>DB: db.get_work + db.list_chapters
  loop every chapter
    API->>DB: get_or_create_render_set(chapter, policy, model_family)
    API->>DB: enqueue(tts.chapter, idempotency_key = tts:{render_set_id})
    API->>DB: set render_sets.job_id
  end
  API-->>U: 202 GenerateResult (chapters, jobs_created)
  W->>W: drain queued tts.chapter jobs
  U->>API: poll GET chapter audio and GET books for progress
```

`jobs_created` counts only newly enqueued jobs; an existing `queued`/`running` job is reused, and a
previous `failed`/`cancelled`/`dead` row is requeued in place. The browser entry point is
`PlayerApp.generateAll()` behind the “Generate all” button in `BookDetail`.

## 25. Job status and health polling flows

```mermaid
flowchart LR
  subgraph P["Job status"]
    JREQ["GET /api/v1/jobs/{job_id}<br/>ungated"] --> JDB["db.get_job"]
    JDB --> JOUT["id · kind · state · progress · total · error"]
  end
  subgraph H["Health"]
    HREQ["GET /api/v1/health<br/>also /api/health alias"] --> HSVC["routers/meta.py health()"]
    HSVC --> HDB["db.queue_depth"]
    HSVC --> HSVC2["status · provider · provider_version<br/>speech · queue · auth_required"]
  end
  WEB["PlayerApp + useHealth"] -- "every 30 s" --> HREQ
  WEB -- "every 12 s" --> BOOKS["GET /api/v1/books"]
  WEB -- "every 1.5 s while rendering" --> RENDER["GET /api/v1/chapters/{id}/audio"]
  WEB --> JREQ
```

`auth_required` is `bool(AAB_ADMIN_TOKEN or AAB_JWT_SECRET)`. Health never contacts a TTS model or
a provider; it only reports the configured provider identity and local queue depth.

## 26. Worker loop modes

```mermaid
flowchart TD
  START["python -m services.worker.worker.main"] --> SET["Settings.load → make_engine → init_db"]
  SET --> ONCE{"--once?"}
  ONCE -- yes --> DRAIN["aab_jobs.drain<br/>run_once until empty · 10 000 job safety stop"]
  DRAIN --> EXIT["process exits"]
  ONCE -- no --> SIG["install SIGINT / SIGTERM handlers"]
  SIG --> LOOP["run_once: requeue_stale → claim_job"]
  LOOP --> GOT{"job claimed?"}
  GOT -- yes --> HAND{"handler registered?"}
  HAND -- yes --> RUN["handler: ingest.revision or tts.chapter"]
  HAND -- no --> UNK["fail_job unknown_kind · non-retryable"]
  RUN --> LOOP
  UNK --> LOOP
  GOT -- no --> IDLE["sleep 1 s"]
  IDLE --> LOOP
  LOOP -. "exception outside run_once" .-> BACK["sleep 2 s"]
  BACK --> LOOP
  SIG -. "signal" .-> STOP["set stop flag; exit after current run_once"]
```

`--once` is used for deterministic tests and local drains; the long-running worker uses the same
`run_once` function in a signal-aware loop. In Docker the `worker` role execs this module and waits
for the API healthcheck before polling.

## 27. Route surface and gates

```mermaid
flowchart LR
  ROOT["Route surface"] --> SHARED["/api/v1 + /api<br/>health · books · chapters · jobs"]
  ROOT --> AUTH["/api/v1/auth<br/>register · login · refresh · logout · me"]
  ROOT --> LIBR["/api/v1/library<br/>list · add · remove · progress get/set · book progress"]
  ROOT --> ADM["/api/v1/admin<br/>11 routes listed in §21"]
  ROOT --> MED["/media/{path}<br/>allow_query=True · range support"]
  ROOT --> WEBR["/<br/>apps/web/index.html fallback"]
```

| Group | Exact routes | Gate |
|---|---|---|
| Shared | `GET /health`, `GET /books`, `GET /books/{book_id}`, `POST /books`, `POST /books/{book_id}/generate`, `POST /chapters/{chapter_id}/audio`, `GET /chapters/{chapter_id}/audio`, `GET /jobs/{job_id}` | `GET` routes public with visibility filtering; `POST` routes `require_writer`; `GET /jobs/{id}` ungated |
| Auth | `POST /register`, `POST /login`, `POST /refresh`, `POST /logout`, `GET /me` under `/api/v1/auth` | account existence via `AAB_JWT_SECRET`; `GET /me` uses `require_user` |
| Library | `GET /`, `POST /works/{work_id}`, `DELETE /works/{work_id}`, `PUT /progress/{chapter_id}`, `GET /progress/{chapter_id}`, `GET /works/{work_id}/progress` under `/api/v1/library` | `require_user` and `user_id` scoping |
| Admin | the 11 routes in §21, all under `/api/v1/admin` | router-level `require_admin` |
| Static | `GET /media/{path:path}`, `GET /` | media visibility/owner check; traversal guard; `/` public |

Legacy `GET /api/books` returns a bare list; `GET /api/v1/books` returns a paginated `BookPage`.
All other shared routes exist identically under both prefixes.

## 28. Flow index

| Flow | Entry point | Tables / output |
|---|---|---|
| Web delivery | `services/api/routers/web.py`, `apps/web/next.config.ts` | `apps/web/index.html`, `.next/` |
| Contracts | `scripts/export_openapi.py` → `scripts/generate_contracts.sh` | `openapi.json`, `api.d.ts` |
| Local dev | `scripts/dev.sh`, `scripts/dev-web.sh` | API :8000, worker, Next :3000 |
| Docker | `compose.yaml`, `scripts/docker-entrypoint.sh` | `aab-data` volume |
| CI | `.github/workflows/ci.yml` | test, smoke, contract, build, Docker gates |
| HTTP smoke | `scripts/smoke.sh` | health → upload → ingest → render → 200/206 media |
| Upload | `POST /api/v1/books` | `works`, `revisions`, `uploads`, `jobs` |
| Whole-book generation | `POST /api/v1/books/{id}/generate` | `render_sets`, `jobs` |
| Chapter audio request | `POST /api/v1/chapters/{id}/audio` | `render_sets`, `jobs` |
| Read / rights | `GET /api/v1/books`, `GET /books/{id}`, `GET /chapters/{id}/audio` | 200 / 202 / 404 |
| Media delivery | `GET /media/{path}` | 200 / 206 / 404 / 416 |
| Job status / health | `GET /api/v1/jobs/{id}`, `GET /api/v1/health` | job state, provider identity, queue depth |
| Auth | `/api/v1/auth/*` | `users`, `sessions` |
| Ingest | `services/worker/worker/jobs/ingest.py` | `chapters`, `blocks`, `characters`, `voice_profiles`, `narration_segments`, `performance_directives` |
| Render | `services/worker/worker/jobs/tts.py` | `audio_renders`, `assets`, `render_claims`, manifest |
| Job lifecycle | `aab_jobs.run_once`, `aab_db.enqueue` | `jobs`, `job_events`, `render_claims` |
| Mastering | `aab_audio.build_master` | `master.m4a` / `master.wav`, `manifest.json` |
| Library | `/api/v1/library/*` | `library_entries`, `playback_progress` |
| Admin | 11 routes under `/api/v1/admin` | `admin_audit`, `job_events` |
| Worker modes | `python -m services.worker.worker.main [--once]` | drain or signal-aware poll loop |
| CLI import | `scripts/import_book.py` | work, revision, drain, manifest |
