# 0005. Provider boundary

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** architecture, backend

## Context

The brief requires that AI providers be interchangeable and that changing a model must not
require rewriting the application. That is a common stated goal and a rare achieved one,
because the abstraction erodes whenever a developer needs "just one field" from a vendor
response.

The concrete forces here:

- Model availability and pricing move monthly. Observed during this research: Gemini Flash
  prices double on 1 Jan 2027; Gemini 4 doubles on 1 Dec 2026; OpenAI retires `tts-1`,
  `tts-1-hd` and `gpt-4o-mini-tts` on 6 Jan 2027.
- Providers differ structurally: character-based pricing vs token-based, streaming vs batch,
  cloning vs no cloning, 5k vs 5M context.
- Cost guards must run *before* a call, which means every adapter must be able to estimate.

## Decision

1. **All vendor SDK imports are confined to `python/aab_providers`.** Enforced by an
   import-linter contract in CI. Nothing else in the tree may import `openai`, `anthropic`,
   `google.genai`, `boto3`'s Polly client, or any GPU-host SDK.

2. **Four protocols define the entire surface:** `LLMProvider`, `TTSProvider`,
   `EmbeddingProvider`, `OCRProvider`. Each declares `capabilities()`, `health()`,
   `estimate()`, and its execution methods. There is no generic "invoke" escape hatch.

3. **Vendor errors are mapped to a closed taxonomy** (`RATE_LIMITED`, `UNAVAILABLE`,
   `INVALID_INPUT`, `CONTENT_REJECTED`, `TIMEOUT`, `AUTH`, `QUOTA_EXCEEDED`, `UNKNOWN`) before
   leaving the adapter. The router never parses vendor messages.

4. **Providers, models, capability flags and prices live in the database**, not in code.
   `ai_models` carries `capabilities jsonb`, `price_schedule jsonb` with `effective_from`,
   `deprecated_at`, and `weights_sha256`. Deployment does not change which model is used;
   configuration does.

5. **Routing is a pure function** of `(requirements, policy, health, budget)` returning an
   ordered candidate list. The resolved chain is persisted on the job for provenance.

## Consequences

**Good**
- Adding a provider is one file plus one row. No call-site changes.
- Cost guards, health checks, fallback and quotas are written once, against the protocol.
- A provider incident is a routing change, not a deploy.
- Tests use a fake provider implementing the same protocol, so the pipeline is testable
  without network access or spend.

**Bad**
- Lowest-common-denominator risk: a genuinely novel capability (e.g. two-speaker dialogue
  synthesis) does not fit a single-speaker protocol and needs a new optional method rather
  than a bespoke integration.
- The abstraction adds indirection when reading code — you cannot see the HTTP call in the
  caller.
- Capability flags can lie. Mitigated by a nightly capability probe per enabled model that
  performs a minimal real call and records drift.

## Rejected alternatives

- **A unified model gateway (LiteLLM, OpenRouter) as the only integration.** Useful as *one
  adapter*, but making it the only path adds a margin, a single point of failure, and a third
  party in the data path for private uploads. It is implemented as an adapter instead.
- **Direct SDK calls with a shared helper.** This is what actually happens in most codebases
  and it is how the abstraction dies.
- **One "AI service" microservice.** Adds a network hop and a second deployable to solve a
  problem import-linting solves for free.

## Revisit when

- The protocol needs more than two optional methods, which would indicate that the providers
  have diverged enough that a lowest-common-denominator abstraction is actively harmful.
