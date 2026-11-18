# Architecture Decision Records

One file per decision that would be expensive to reverse. Format is deliberately short:
context, decision, consequences, what was rejected, and the condition under which we revisit.

A decision that is cheap to reverse belongs in a code comment, not here.

## Index

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-modular-monolith-on-one-host.md) | Modular monolith on a single commodity host; AWS for storage, delivery, identity | Accepted |
| [0002](0002-postgresql-as-system-of-record.md) | PostgreSQL + pgvector as system of record; no DynamoDB, no vector database | Accepted |
| [0003](0003-voice-identity-is-a-reference-clip.md) | Voice identity is a reference clip + model binding, not a text description | Accepted |
| [0004](0004-render-key-and-immutability.md) | Canonical render key with discretised directives; audio is immutable | Accepted |
| [0005](0005-provider-boundary.md) | No vendor SDK outside `aab_providers`; no price or model literal outside the registry | Accepted |
| [0006](0006-pre-generation-before-lazy-generation.md) | Pre-generate popular catalogue works; lazy generation is the fallback | Accepted (prefetch fleet deferred) |
| [0007](0007-zero-cost-local-first-launch.md) | Launch runs at $0 local-first: SQLite, local media, Kokoro on CPU; paid services are later opt-ins | Accepted |

## Template

```markdown
# NNNN. Title

- **Status:** Proposed | Accepted | Superseded by ADR-NNNN
- **Date:** YYYY-MM-DD
- **Deciders:** who must agree

## Context
What forces are at play. Include the numbers that make the decision non-arbitrary.

## Decision
One paragraph, active voice. "We will ..."

## Consequences
Good, bad, and the operational burden. Be honest about the bad.

## Rejected alternatives
Each with the reason it lost.

## Revisit when
A measurable trigger, not a vague "if it becomes a problem".
```
