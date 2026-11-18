# Runbook: restore PostgreSQL

**Use when:** the database is corrupt, a bad migration destroyed data, or the host is lost.
**Target:** RPO ≤ 5 minutes, RTO ≤ 30 minutes.

> **Does not apply to the launch profile.** The $0 launch uses SQLite and local media; follow
> [backup-restore.md](backup-restore.md) instead. This runbook becomes current when
> `AAB_DATABASE_URL` points at Postgres (ADR-0007).

## Before you start

- Confirm the failure is real: `pg_isready`, then `select 1`, then check disk and OOM killer
  (`dmesg -T | tail -50`). A full disk looks like corruption.
- Announce in the incident channel: who is restoring, what is affected, expected downtime.
- Put the API into `cache_only` (see kill-switch runbook) so no writes race the restore.

## Prerequisites

| Item | Where |
|---|---|
| WAL-G binary | `/usr/local/bin/wal-g` |
| Backup credentials | SSM `/aab/prod/backup/*` |
| Base backups | `s3://aab-prod-backups/pg/base/` |
| WAL archive | `s3://aab-prod-backups/pg/wal/` |
| Latest good backup timestamp | `wal-g backup-list` |

## Steps

1. **Verify the backups exist before touching the broken instance.**

   ```bash
   export WALG_S3_PREFIX=s3://aab-prod-backups/pg
   wal-g backup-list | tail -5
   ```

2. **Stop the writers.** `docker compose stop api worker scheduler` (keep Caddy up so cached
   audio continues to serve — it does not touch Postgres).

3. **Preserve the broken instance** if it may still hold data:

   ```bash
   docker compose stop postgres
   mv /var/lib/postgresql/16/main /var/lib/postgresql/16/main.broken.$(date +%s)
   ```

4. **Restore the latest base backup.**

   ```bash
   wal-g backup-fetch /var/lib/postgresql/16/main LATEST
   ```

5. **Configure recovery** — write `postgresql.auto.conf`:

   ```
   restore_command = 'wal-g wal-fetch %f %p'
   recovery_target_timeline = 'latest'
   ```

   and create `recovery.signal`. Do **not** set `recovery_target_time` unless you are doing a
   point-in-time recovery to just before the bad migration; if you are, state the exact
   timestamp in the incident channel first.

6. **Start Postgres and watch the log** until `database system is ready to accept connections`.

7. **Verify before restarting writers.**

   ```sql
   select count(*) from shared.books_revisions;      -- > 0
   select max(created_at) from ops.jobs;             -- close to the incident time
   select count(*) from ops.audit_log where created_at > now() - interval '1 day';
   select version from ops.config_versions order by version desc limit 1;
   ```

   Then run the smoke suite: `uv run pytest -m smoke services/api/tests`.

8. **Restart writers** and watch the first 20 jobs. `docker compose up -d api worker scheduler`.

9. **Confirm** a cached chapter plays, a new chapter enqueues, and the spend dashboard
   increments.

## If it does not work

- `wal-g backup-fetch` fails with a missing WAL segment: try the previous backup with
  `wal-g backup-fetch ... <backup_name>`; data loss is bounded by the base interval.
- Postgres starts but queries fail: check `pg_control` version matches the image tag. Mixing
  a 16.x data directory with a 17 binary is the most common cause.
- The host is gone: provision a new VM, install Docker and WAL-G, restore, repoint DNS. This is
  the 30-minute path and it has been rehearsed.

## After

- Write the timeline: detection, first action, restore start, service restored.
- Add a test that would have caught the failure.
- If data was lost, produce the list of affected users **before** communicating.
