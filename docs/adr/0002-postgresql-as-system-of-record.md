# 0002. PostgreSQL + pgvector as system of record

- **Status:** Accepted; launch database amended by ADR-0007
- **Date:** 2026-11-17
- **Deciders:** architecture, backend

## Context

The brief lists DynamoDB, S3, PostgreSQL and pgvector as candidates, and explicitly warns
against introducing a dedicated vector database without justification.

The data is strongly relational in ways that matter to correctness, not just convenience:

- A chapter's narration is `segments × characters × voice_profiles × renders`. Resolving
  "which segments are unrendered for this render set" is a join across four tables.
- Reprocessing requires diffing a new revision against an old one and preserving human
  corrections keyed by span.
- Job claiming must be transactional with the state change that makes the job meaningful
  (insert the render placeholder and claim the job atomically).
- Admin and cost queries are ad hoc and change weekly; they are easier to write in SQL than
  to pre-model as access patterns.

DynamoDB would require denormalising all of the above into item collections and would make
every one of these queries a new access-pattern design exercise.

## Decision

We will use **PostgreSQL 16 as the single system of record**, with **pgvector** for
embeddings. S3 holds immutable blobs only. There will be no DynamoDB table and no dedicated
vector database.

Deployment is self-managed Postgres on the application host at MVP (WAL-G to S3 for backups),
with a documented path to managed Postgres (Neon/Supabase/RDS) when the operational burden
or availability requirement justifies it.

## Consequences

**Good**
- One consistent transactional boundary for job claiming, render deduplication and audit
  writes. This eliminates an entire class of race conditions that the brief calls out
  (duplicate billing, conflicting asset writes, inconsistent cache state).
- Schema migrations are ordinary and reviewable.
- `jsonb` absorbs the evolving StoryPack and provider-capability shapes without migrations.
- Embeddings live next to the rows they describe; retrieval is a join, not a second system
  with its own consistency model and its own bill.
- Zero marginal cost at MVP.

**Bad**
- We own backup, restore, upgrade and failover. Mitigated by nightly WAL-G, a restore
  runbook, and a monthly restore drill.
- Vertical write scaling is bounded. Not a concern below ~2,000 writes/s.
- JSONB can become a dumping ground. Mitigated by keeping the *queryable* fields as real
  columns and using JSONB only for genuinely open-ended payloads (`persona`, `params`,
  `capabilities`).

## Rejected alternatives

- **DynamoDB for everything.** Access-pattern-first design makes the reprocessing and
  admin-query requirements painful; the always-free tier (25 GB, 25 WCU/RCU) is attractive
  but only applies to provisioned capacity, so on-demand requests are billed from the first
  write. Not worth the modelling cost.
- **DynamoDB + PostgreSQL.** Two stores means dual writes and a consistency problem with no
  requirement driving it.
- **Aurora Serverless v2.** Minimum capacity of 0.5 ACU is roughly $43/month before storage —
  more than the entire rest of the MVP infrastructure.
- **Pinecone/Weaviate/Qdrant.** At 10⁵–10⁷ vectors, pgvector with HNSW is sufficient. A
  second datastore adds a second backup, a second failure mode and a second bill to solve a
  problem we do not have.
- **SQLite.** Tempting for a single host, but concurrent writers from API and worker
  processes, plus the need for `FOR UPDATE SKIP LOCKED`, rule it out. *Amended by ADR-0007:*
  SQLite is the launch database under a single-writer constraint, with the same schema and
  job semantics, because the launch environment has no Postgres and the directive is a $0,
  account-free launch. Postgres remains the target once concurrency or scale requires it.

## Revisit when

- Managed Postgres cost is under the value of the ops time it saves (likely around 500+ MAU).
- Embedding count exceeds ~10⁷ *and* measured retrieval p95 exceeds 200 ms *and* recall
  tuning has been exhausted.
- Write throughput approaches 2,000/s sustained.
