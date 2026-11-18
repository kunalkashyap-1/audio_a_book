# 0001. Modular monolith on a single commodity host

- **Status:** Accepted; launch delivery/storage amended by ADR-0007
- **Date:** 2026-11-17
- **Deciders:** architecture, backend

## Context

The platform needs an HTTP API, a background worker pool for long-running jobs (parsing,
LLM analysis, TTS rendering, audio mastering), a relational database, scheduled jobs
(prefetch, catalogue sync, garbage collection) and an admin surface.

The initial budget is very small. The AWS-native equivalent of this shape has a fixed floor:

| Component | Fixed monthly floor |
|---|---|
| Application Load Balancer | ~$16 |
| ECS Fargate (2 small tasks) | ~$20 |
| RDS PostgreSQL (db.t4g.micro, single AZ) | ~$15 |
| **Total before any usage** | **~$51** |

A single small VM runs all of it for $5–12. Inference is external and billed per use either
way, so this is purely a fixed-cost decision.

At the same time, the workload has genuinely independent scaling axes: API latency is
sensitive to worker CPU contention, and video/audio mastering is CPU-bursty. A single
process would be wrong; a single *host* with separate processes is fine.

## Decision

We will build a **modular monolith**: one container image, two entrypoints (`api`,
`worker`), one PostgreSQL instance, deployed to a single commodity VM behind a reverse
proxy. Object storage and delivery stay on AWS (S3 + CloudFront), identity stays on
Cognito.

Module boundaries are enforced inside the monolith (see ADR-0005) so that any module can be
extracted into its own service later without touching call sites.

## Consequences

**Good**
- Fixed infrastructure cost of ~$7–12/month at MVP, versus ~$51+.
- One deploy, one log stream, one database, one migration path. For a team of two this is
  the difference between shipping and operating.
- No cross-service latency or distributed transaction problems in the hot paths (job
  claim, render deduplication) where correctness matters most.

**Bad**
- A single host is a single point of failure for *generation*. Cached audio keeps serving
  from CloudFront because it never touches the host, so the blast radius of a host outage
  is "no new generation, existing books still play".
- Vertical scaling has a ceiling. Around 50–100 concurrent generation jobs, or when the
  API p95 degrades because a mastering job is pegging the CPU, this decision must be
  revisited.
- Backups, upgrades and failover are our job, not RDS's.

**Operational burden accepted:** ~1 hour/month (OS patching, Postgres minor upgrades) plus
a documented 30-minute restore runbook (WAL-G from S3).

## Rejected alternatives

- **API Gateway + Lambda per route.** Hard 15-minute invocation limit is wrong for chapter
  renders; cold starts on a heavy Python image (ffmpeg, parsing, SDKs) are 2–5 s; per-request
  pricing punishes chatty clients; local development diverges from production.
- **ECS Fargate + ALB + RDS.** Correct architecture, wrong price at this stage. Add ~$44/month
  of fixed cost for benefits we cannot yet use.
- **Kubernetes.** No. One deployable does not need a control plane.
- **Microservices per subsystem.** Would multiply the fixed cost and the operational surface
  while the domain boundaries are still being discovered.

## Revisit when

- Any of: p95 API latency >500 ms sustained, >60 concurrent generation jobs, host CPU
  saturation >70% for a week, or a second region is required.
- Migration path: the worker container already has no inbound HTTP, so it moves to Fargate
  or a second host first; the API follows; Postgres moves to RDS last.
