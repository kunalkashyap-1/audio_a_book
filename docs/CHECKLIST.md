# Project checklist

Updated as work progresses. Two gates are tracked separately: the **launch gate**, which is
met at $0, and the **quality-tier gate**, which is only reachable once paid inference is
enabled.

## Launch — complete

The complete flow runs on one machine with no cloud account, credits or paid keys.

- [x] Zero-cost profile recorded in [ADR-0007](adr/0007-zero-cost-local-first-launch.md):
      SQLite + local filesystem + Kokoro-82M int8 on CPU + static web player
- [x] One Python distribution (`python/`) and two entrypoints (`services/api`,
      `services/worker`) — no Docker, no Node build
- [x] `uv venv` + `uv pip install -e "python[kokoro,dev]"` installs cleanly
- [x] `scripts/setup_tts.sh` downloads and verifies the Apache-2.0 Kokoro int8 weights
      (89 MB) and voice bank (27 MB) into `var/models`
- [x] Deterministic fake-speech fallback so the pipeline runs before the model exists, and
      so CI never needs weights
- [x] Ingestion: TXT, Markdown, HTML, EPUB; Gutenberg boilerplate stripped; chapter headings
      detected at paragraph boundaries; unstructured text chunked
- [x] Story intelligence without an LLM: cast extraction, full-name folding, gender priors,
      quotative tags, single-mention, pronoun and two-hander alternation attribution, with
      per-segment `method` and `confidence`
- [x] Narration segmentation, speakable normalisation (abbreviations, dashes, quotes),
      sentence-aware splitting with a hard character budget
- [x] Canonical `rk1:` render key with golden vector and sensitivity tests
- [x] Voice identity as a preset/reference binding; the key's `spk` slot is the voice, never
      a per-book character id
- [x] SQLite schema created from the same SQLAlchemy metadata as the Postgres target; WAL,
      foreign keys and busy timeout enabled
- [x] Job queue with priorities, leases, retries, requeue-after-failure, and idempotency keys
- [x] Render claims so two concurrent requests cannot synthesise the same segment twice
- [x] Segment WAVs stored content-addressed; chapter masters AAC 64 kbps mono 24 kHz;
      manifest written beside the master with per-segment keys and speaker names
- [x] HTTP API: health, list/upload/get book, request chapter audio (202), poll manifest,
      generate a whole book, job status, range-capable `/media/{path}`
- [x] Optional `AAB_ADMIN_TOKEN` (header or bearer) gating writes; public reads
- [x] Local accounts: argon2id passwords, JWT access + rotating opaque refresh cookie,
      roles `user/admin`, first registrant is admin, opt-in via `AAB_JWT_SECRET` (still $0)
- [x] Owner-scoped user data: `owner_id` on works, library shelf and per-chapter playback
      progress endpoints; additive SQLite column migration on startup
- [x] Static player: book list, cast chips, chapter list, upload, generation polling,
      autoplay, resume position, error surfacing (zero-build fallback served at `/`)
- [x] Typed Next.js web app in `apps/web`: App Router + TS + Tailwind 4, npm workspaces
      (no pnpm/corepack), same-origin rewrites for `/api/*` and `/media/*`
- [x] Generated contracts: `scripts/export_openapi.py` → `openapi.json` → `api.d.ts`, re-exported
      as `@aab/contracts`; no hand-written API types in the web app
- [x] Web flows: catalogue, book/cast/chapters, generate all, render polling, audio playback,
      upload, library shelf with deep links, tabbed admin management UI, sign-in UI
- [x] Admin plane: canonical `/api/v1/admin` with overview, job retry/cancel and event timeline,
      book `shareable`/`status` controls, feature-flag CRUD, read-only provider registry; every
      mutation requires a typed reason and appends an `admin_audit` row atomically
- [x] Browser auth: refresh on mount from HttpOnly cookie, access token in memory only,
      `Authorization` on API calls, `?token=` on media URLs, operator token still supported
- [x] Web verification: `npm run build` + `tsc --noEmit` pass; live e2e through :3000 rewrites
      registered, uploaded, generated, fetched a 356 KB manifest master, added to library and
      saved progress
- [x] Failed ingest marks revision and work `failed` instead of leaving them pending
- [x] Cross-book cache verified: second identical book `14 unique, 14 cached, 0 to render`,
      0.9 s vs 12.1 s
- [x] Voice change verified to invalidate one character's segments only
- [x] Layered API: routers → use-case services → `aab_db`, pydantic IO schemas, one error
      envelope, `/api/v1` with `/api` aliases, paginated catalogue, OpenAPI docs at `/docs`
- [x] 119 tests passing, including an HTTP contract suite (upload → ingest → 202 → 200
      manifest → range delivery, error envelope, privacy matrix, both prefixes), an auth
      contract suite (register/login/me, 409/401/403, first-user admin, refresh rotation +
      revocation, owner visibility, library and progress scoping), an admin contract suite
      (gate matrix, retry/cancel state transitions + events, conflict cases, private catalogue
      visibility, audited work/flag writes, read-only providers, overview counts), render-claim
      exclusivity/expiry tests, and a worker kill drill (hard crash mid-render, live lease
      blocks a second worker, stale lease/claims recover to exactly one render per key)
- [x] Crash hardening: recovery releases claims for keys rendered before the kill, so a
      successful retry leaves no orphan `render_claims` rows
- [x] CI: `.github/workflows/ci.yml` runs pytest, HTTP smoke, generated-contract diff check,
      web typecheck and web build on every push and pull request, plus a second job that builds
      both Docker images and boots the stack
- [x] Docker: one `Dockerfile` for API/worker/models (`AAB_ROLE`), a multi-stage `Dockerfile.web`,
      and `compose.yaml` wiring all three services to a persistent `aab-data` volume; `docker
      compose up --build -d` is the whole stack
- [x] Docker safety: non-root image user, ffmpeg for AAC masters, health checks, `init: true`,
      restart policies, secrets via `.env`, and `.dockerignore` keeping venv/node_modules/data
      out of the build context
- [x] Range requests verified (`206 Partial Content` with correct `Content-Range`)
- [x] Rights enforcement verified: non-public-domain uploads are absent from the anonymous
      catalogue; their book page, manifest and media return `404`; the operator token (header
      or `?token=` for `<audio>`) still reaches them
- [x] `scripts/smoke.sh` exercises the HTTP path headlessly
- [x] `.gitignore` covers data, virtualenv, caches and build artefacts

## Specification — complete

- [x] Requirements analysis; conflicts identified (free tier, lazy generation, cache vs
      personalisation, cross-book identity)
- [x] Nine specifications and seven ADRs
- [x] Licence register with approved, restricted and blocked dependencies
- [x] Runbooks: provider incident, kill switch, backup/restore
- [x] AWS pricing and free-tier terms recorded for the later opt-in path
- [x] TTS candidates reviewed: Qwen3-TTS 0.6B/1.7B, Kokoro-82M, Chatterbox, CosyVoice 3,
      MOSS-TTS, Piper, Phonon, Chirp 3 HD, Polly, ElevenLabs
- [x] Non-commercial and copyleft licences excluded (XTTS-v2 CPML, F5-TTS CC-BY-NC,
      ebooklib AGPL, PyMuPDF AGPL); Piper per-voice audit outstanding
- [x] Catalogue sources reviewed: Gutendex, Project Gutenberg, Standard Ebooks, Open Library

## Quality-tier gate — outstanding

Everything here requires either a paid account or a corpus that does not exist yet. None of
it blocks the $0 launch.

- [ ] Kokoro CPU throughput at a larger sample than the launch run (single observed sample:
      15 segments / 35.9 s of audio / 12.1 s wall **including cold model load**, i.e. an
      RTF around 0.34; not a benchmark)
- [ ] Qwen3-TTS 1.7B RTF on L4 at batch 1 / 8 / 16 — the number that decides the paid tier
- [ ] Qwen3-TTS 0.6B RTF at the same batch sizes
- [ ] Time-to-first-audio, cold and warm worker (cloud)
- [ ] Voice-identity stability: 200 segments from one reference clip, speaker-embedding
      cosine ≥ 0.85, plus a 20-sample ABX
- [ ] Kokoro on a mid-range Android (GPU delegate): RTF, APK/asset size, battery
- [ ] End-to-end book cost on 3 titles including 20% retry/QC overhead
- [ ] Attribution F1 against a 200-segment hand-labelled set across 3 novels, for DeepSeek
      V4.1 Flash, Gemini 3.5 Flash-Lite and Qwen3.8-Flash
- [ ] Alias recall and character precision on the same set
- [ ] Failure taxonomy for the rule-based attributor (invented speaker, missed attribution,
      merged characters), which shapes the correction UI
- [ ] SQLite → Postgres migration drill with a real dataset
- [ ] Local disk → object storage + CDN migration drill

## Legal and policy — outstanding

- [ ] Public-domain determination by territory; confirm US-only launch stance
- [ ] Project Gutenberg terms review: bulk access, attribution, mirroring
- [ ] Standard Ebooks attribution requirements
- [ ] Voice-cloning consent policy drafted (feature is off)
- [ ] Data-processing terms for private uploads: which providers may see user content
      (relevant only once an LLM adapter is enabled)
- [ ] Piper per-voice licence audit, if Piper is ever used

## Decisions — accepted

- [x] ADR-0001 modular monolith on one host
- [x] ADR-0002 PostgreSQL as target system of record (launch amended)
- [x] ADR-0003 voice identity is a reference clip or preset binding
- [x] ADR-0004 render key and immutability
- [x] ADR-0005 provider boundary
- [x] ADR-0006 pre-generation before lazy generation (deferred at launch)
- [x] ADR-0007 zero-cost local-first launch profile
