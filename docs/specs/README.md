# Specifications

The nine engineering deliverables from Phase 0, plus the as-built directory and flow map.
Written to be read in order by someone joining the project, and to be edited as measurements
replace assumptions. Each engineering spec opens with its **launch profile** where the
implemented $0 build differs from the target architecture;
[ADR-0007](../adr/0007-zero-cost-local-first-launch.md) records that decision.

| # | File | Contents |
|---|---|---|
| 1 | [01-product-requirements.md](01-product-requirements.md) | Goals, personas, journeys, MVP boundary, metrics |
| 2 | [02-system-architecture.md](02-system-architecture.md) | Components, flows, failure matrix, rejected infrastructure |
| 3 | [03-data-and-bookbrain.md](03-data-and-bookbrain.md) | Schema, S3 layout, JSON contracts, versioning, dedupe |
| 4 | [04-ai-providers.md](04-ai-providers.md) | Adapters, routing, model comparison, benchmarks, voice strategy |
| 5 | [05-audio-and-cache.md](05-audio-and-cache.md) | Render keys, batching, QC, prefetch, concurrency, lifecycle |
| 6 | [06-admin.md](06-admin.md) | Pages, provider management, flags, cost controls, audit |
| 7 | [07-infrastructure-and-cost.md](07-infrastructure-and-cost.md) | The $0 launch profile, verified prices, and the paid opt-in scenarios |
| 8 | [08-roadmap.md](08-roadmap.md) | Phases, acceptance criteria, effort, risks, critical path |
| 9 | [09-project-structure.md](09-project-structure.md) | Repository shape, boundary rules, enforcement |
| 10 | [10-directory-map-and-flows.md](10-directory-map-and-flows.md) | As-built directory map and flowcharts for every runtime path |

## Conventions

- **Measured** means we ran it. **Vendor claim** means the source published it. **Assumption**
  means it is a planning number that must be replaced in Phase 0.
- Costs are USD list prices as of November 2026 unless stated.
- "MVP" means Phase 1–5: catalogue, BookBrain, story engine, voice + cache, admin, web.
  Android is Phase 6; cloning, OCR and multilingual are Phase 7.
