# Runbook: backup and restore (launch profile)

**Use when:** taking a scheduled backup, moving the install to another machine, recovering
from a bad import or a deleted book.
**Applies to:** the $0 launch profile — SQLite + local media (ADR-0007).

The target-database procedure is in [restore-postgres.md](restore-postgres.md); it does not
apply until `AAB_DATABASE_URL` points at Postgres.

## What to back up

| Path | Why | Replaceable? |
|---|---|---|
| `$AAB_HOME/aab.db` | works, chapters, cast, jobs, render keys, voice profiles | **No** |
| `$AAB_HOME/media/` | uploads, segment WAVs, chapter masters, manifests | Only by paying to re-render |
| `$AAB_HOME/models/` | Kokoro ONNX weights and voice bank | Yes, `scripts/setup_tts.sh` |
| `AAB_ADMIN_TOKEN` | write access | Yes, but rotating logs everyone out |

Everything lives under `AAB_HOME` (default `./var`), so one directory covers the state. Keep
the token in a password manager, not in the backup.

## Backup

Stop the API and worker first if the copy can be cold. For a live copy, use SQLite's backup
API — **do not** `cp` a database that is being written, because the WAL is separate and the
copy can be torn.

```bash
set -euo pipefail
AAB_HOME="${AAB_HOME:-$PWD/var}"
DEST="${1:?usage: backup.sh DEST_DIR}"
mkdir -p "$DEST"

# Consistent database snapshot, safe while the API is running.
.venv/bin/python - "$AAB_HOME/aab.db" "$DEST/aab.db" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
    d.execute("PRAGMA integrity_check").fetchone()
PY

# Media: content-addressed and append-only, so a live rsync is safe.
rsync -a --delete "$AAB_HOME/media/" "$DEST/media/"

echo "backup written to $DEST"
du -sh "$DEST"
```

Models are deliberately excluded: they are a download, not state. Copy them only when the
target machine has no network.

Suggested cadence at launch: after each import session, and nightly if the instance is
public. Retention is two generations plus one monthly; audio dominates size (~200 MB per
rendered audio hour), so prune whole books rather than segments.

## Restore

1. **Stop writes.** Stop `scripts/dev.sh` (or the API and worker). Playback from the current
   media directory keeps working until the files move.
2. **Move the broken state aside** rather than deleting it. A partial recovery is often
   better than none.
3. **Restore the database and media** from the same backup generation. Mixing a database
   snapshot with a newer media tree is survivable (unreferenced files are harmless), but the
   reverse loses audio that rows point at.
4. **Check integrity before starting.**
5. **Start and verify.**

```bash
set -euo pipefail
AAB_HOME="${AAB_HOME:-$PWD/var}"
SRC="${1:?usage: restore.sh BACKUP_DIR}"

mv "$AAB_HOME/aab.db" "$AAB_HOME/aab.db.broken.$(date +%s)" 2>/dev/null || true
mv "$AAB_HOME/media" "$AAB_HOME/media.broken.$(date +%s)" 2>/dev/null || true

cp "$SRC/aab.db" "$AAB_HOME/aab.db"
mkdir -p "$AAB_HOME/media"
rsync -a "$SRC/media/" "$AAB_HOME/media/"

.venv/bin/python - "$AAB_HOME/aab.db" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as conn:
    ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
    books = conn.execute("select count(*) from works").fetchone()[0]
print(f"integrity: {ok}; works: {books}")
assert ok == "ok"
PY

./scripts/dev.sh
```

Verification, in order:

```bash
curl -s localhost:8000/api/health
curl -s localhost:8000/api/books
# then play the last chapter you know was rendered and seek within it
```

A successful `/api/health` only proves the database opened. Prove audio by requesting a known
chapter: it must return `200` with a manifest, not `202`, and the master must be range-capable.
If the manifest is missing but segments exist, re-requesting the chapter re-masters from cache
without re-synthesising anything.

## Failure notes

| Symptom | Cause | Action |
|---|---|---|
| `database is locked` | two workers, or a long write transaction | run one worker; check `busy_timeout` is 5000 |
| manifest 404, segments present | media restored without `media/books` | re-request the chapter; masters rebuild from cached segments |
| chapter `202` forever | no worker running | start the worker; check `queue` in `/api/health` |
| audio 404 for an old book | media restored from an older generation than the database | restore matching generations, or re-render that chapter |
| `PRAGMA integrity_check` not `ok` | torn copy (usually `cp` of a live database) | restore from the previous generation; do not run `VACUUM` on a corrupt file |

There are no replicas at launch. A disk failure without a backup is unrecoverable, and that
is the strongest argument for the first paid step being object storage.
