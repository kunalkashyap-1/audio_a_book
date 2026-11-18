# 0007. Zero-cost local-first launch profile

- **Status:** Accepted
- **Date:** 2026-11-18
- **Deciders:** architecture, backend
- **Supersedes:** the launch-time portions of ADR-0001 (cloud storage/delivery/identity),
  ADR-0002 (PostgreSQL as the launch database) and ADR-0006 (pre-generation fleet).

## Context

The product brief requires a public SaaS, cloud-first inference, and a very limited budget.
The original specifications answered that with a commodity VM running PostgreSQL, S3 +
CloudFront for media, Cognito for identity, and serverless GPUs for TTS. Every one of those
pieces needs something the project does not have at launch:

| Piece | What it needs before the first playable chapter |
|---|---|
| S3 / CloudFront / Cognito | an AWS account, a payment method, and acceptance of credit-based free tiers |
| Serverless GPU | a RunPod or Modal account with a card on file |
| Managed Postgres (Neon/Supabase/RDS) | an account and, past the trial, a subscription |
| LLM analysis (DeepSeek/Gemini) | an API key tied to a funded account |
| Next.js web app | a Node toolchain and a build step before anything renders |

The directive for this phase is explicit: **launch must work end to end at $0, with no
credits, no accounts and no paid services.** Paid components are added later, as opt-ins,
without rewriting the pipeline.

AWS Free Tier does not satisfy this. Since July 2025 new accounts receive credits
($100, plus up to $100 for completing activities) for six months, and the account is closed
at expiry unless upgraded to a paid plan. That is a trial, not a zero-cost launch, and it
requires a card up front.

At the same time, three invariants must survive unchanged, because they are what makes the
platform worth building:

1. the canonical render key (ADR-0004),
2. the voice-identity model (ADR-0003),
3. the provider boundary (ADR-0005).

## Decision

We will ship the launch as a **local-first profile of the same modular monolith**. The
architecture does not fork; only the adapters underneath it change.

| Concern | Launch implementation | Post-launch replacement |
|---|---|---|
| Database | SQLite 3 (WAL, foreign keys on, 5 s busy timeout) through the same SQLAlchemy metadata | PostgreSQL 16 + pgvector via `AAB_DATABASE_URL` |
| Job queue | same `jobs` table; `FOR UPDATE SKIP LOCKED` on Postgres, guarded `UPDATE … WHERE state = 'queued'` + rowcount check on SQLite | unchanged |
| Media | local filesystem under `AAB_MEDIA_DIR`, content-addressed segment WAVs, AAC masters, JSON manifests | S3-compatible object store behind the same path convention |
| Delivery | FastAPI `GET /media/{path}` with HTTP range support | CloudFront / any CDN in front of the same URLs |
| Speech | Kokoro-82M int8 ONNX on CPU, Apache-2.0, downloaded once, no account | Qwen3-TTS 1.7B on serverless GPU for the quality tier |
| Story intelligence | deterministic attribution rules in `aab_story` — quotative tags, pronoun/gender priors, two-hander alternation | LLM Pass A/B behind the existing provider boundary |
| Web | one static `apps/web/index.html` served by FastAPI, no build step | Next.js app against the same HTTP API |
| Identity | public read/play; writes gated by an optional shared `AAB_ADMIN_TOKEN` | Cognito (or any OIDC provider) |
| Pre-generation | none; on-demand rendering with shared-cache reuse | priority bands from ADR-0006 on a scheduler |

Two supporting rules make the profile honest:

- **The pipeline never silently degrades to nothing.** If the Kokoro weights are absent,
  `build_provider()` falls back to a deterministic formant synthesiser so upload → ingest →
  render → play still completes. The fallback announces itself in `/api/health` and in the
  manifest's `model_family`, and it is not an acceptable quality tier.
- **No vendor SDK, price or model identifier escapes `aab_providers`.** Adding a paid
  provider means adding an adapter and a registry row, not editing jobs.

## Consequences

**Good**

- The complete flow runs with `uv`, `ffmpeg`, and two processes. No cloud account, no card,
  no expiring credit, no region choice, no IAM policy.
- It works offline after the one-time model download, which also makes development and CI
  deterministic.
- The cross-book cache is demonstrable without infrastructure: in the verified run, a second
  identical book rendered `14 unique, 14 cached, 0 to render` in 0.9 s against 12.1 s for
  the first.
- Every later migration is adapter-level: database URL, media root, auth dependency,
  provider registry. The render key, schema and job semantics stay put.
- Operating cost is genuinely zero in cash terms: the machine, its electricity and its
  internet connection already exist. This document does not pretend those are free; it
  claims only that no *new* spend is required.

**Bad**

- **Single writer.** SQLite serialises writes. One API process plus one worker is the
  supported launch shape; a second worker adds contention, not throughput.
- **No horizontal scale, no CDN, no managed backups.** Media durability is the operator's
  responsibility until object storage is enabled.
- **CPU speech is slower than a GPU** and the voice set is Kokoro's presets, not cloned
  voices. Quality tier and cloning remain post-launch work.
- **Attribution is rule-based**, so unusual prose (nested quotes, unattributed multi-party
  scenes) will be wrong more often than an LLM would be. The data model already stores
  `method` and `confidence` per segment, so the correction path exists.
- **Auth is a shared token.** It protects write endpoints, not per-user libraries. Multi-user
  accounts are a post-launch feature and are not claimed here.
- **No billing, quotas or spend controls.** There is nothing to spend on at launch; those
  controls arrive with the first paid adapter.

## Rejected alternatives

- **Use AWS/GCP free tiers as the launch.** Requires a card, expires in six months, and the
  account is closed unless upgraded. It also contradicts the directive's "no credit".
- **Require a GPU from day one.** No free, durable, account-free GPU exists; this would make
  the launch conditional on funding.
- **Wait for funding before building the slice.** The expensive-to-reverse decisions (key,
  voice identity, provider boundary) are cheap to validate now and expensive to validate
  later with a corpus.
- **Piper instead of Kokoro.** Piper's per-voice licence audit is incomplete; Kokoro-82M is
  Apache-2.0 with published int8 ONNX weights, and one download covers the whole voice set.
- **`espeak-ng` as the only speech path.** It is not installed on the target machine and
  sounds unacceptable for a product demo; it is a fallback, not a launch voice.
- **Keep Postgres-only SQL and require Docker.** Docker and a local Postgres are unavailable
  in the launch environment. A schema that cannot be created is not a working system.
- **A Node build step for a one-page player.** It adds a toolchain and a failure mode without
  adding a feature, and delays the first end-to-end run.

## Revisit when

- A second concurrent worker is needed, or write contention appears in `busy_timeout`.
- Media outgrows the host disk, or a second host must serve the same audio → object storage
  and CDN, in that order.
- The first non-operator user needs their own library → real identity, then quotas.
- Listeners complain about voice quality or attribution → enable the GPU TTS and LLM
  adapters; the manifest already records model family and key policy per chapter.
- Cash becomes available: the migration order is **storage → identity → GPU TTS → LLM**, each
  independently revertible.
