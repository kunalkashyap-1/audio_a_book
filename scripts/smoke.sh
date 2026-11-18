#!/usr/bin/env bash
# Headless end-to-end smoke test over HTTP.
#
#   ./scripts/smoke.sh
#   AAB_TTS_PROVIDER=kokoro ./scripts/smoke.sh    # real speech, slower
#
# Starts API + worker on a free-ish port with a throwaway data directory, uploads the
# fixture, renders one chapter, and asserts the manifest and range delivery. Exits non-zero
# on the first failed assertion. Requires curl and ffmpeg-free is fine (fake provider).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${SMOKE_PORT:-8123}"
PROVIDER="${AAB_TTS_PROVIDER:-fake}"
BASE="http://127.0.0.1:$PORT"
HOME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aab-smoke.XXXXXX")"
LOG="$HOME_DIR/server.log"
SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  if [ "${SMOKE_KEEP:-0}" = "1" ]; then
    echo "kept $HOME_DIR"
  else
    rm -rf "$HOME_DIR"
  fi
}
trap cleanup EXIT INT TERM

[ -x .venv/bin/python ] || { echo "no .venv; run: uv venv && uv pip install -e 'python[kokoro,dev]'" >&2; exit 1; }

say() { printf '%-28s %s\n' "$1" "$2"; }

echo "smoke: provider=$PROVIDER home=$HOME_DIR"
AAB_HOME="$HOME_DIR" AAB_TTS_PROVIDER="$PROVIDER" PORT="$PORT" \
  ./scripts/dev.sh >"$LOG" 2>&1 &
SERVER_PID=$!

# ---- health
for _ in $(seq 1 60); do
  if curl -sf "$BASE/api/v1/health" -o "$HOME_DIR/health.json"; then break; fi
  kill -0 "$SERVER_PID" 2>/dev/null || { echo "server died; see $LOG" >&2; tail -30 "$LOG" >&2; exit 1; }
  sleep 1
done
curl -sf "$BASE/api/v1/health" -o "$HOME_DIR/health.json" || {
  echo "health never came up; see $LOG" >&2; tail -30 "$LOG" >&2; exit 1
}
say "health" "$(.venv/bin/python -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d["provider"], d["speech"])' "$HOME_DIR/health.json")"

# ---- upload
CODE=$(curl -s -o "$HOME_DIR/upload.json" -w '%{http_code}' \
  -X POST "$BASE/api/v1/books" \
  -F "file=@python/tests/fixtures/sample.txt" \
  -F "title=Smoke Test Book" \
  -F "author=Fixture" \
  -F "rights_basis=public_domain_us")
[ "$CODE" = "201" ] || { echo "upload returned $CODE" >&2; cat "$HOME_DIR/upload.json" >&2; exit 1; }
BOOK=$(.venv/bin/python -c 'import json,sys;print(json.load(open(sys.argv[1]))["book_id"])' "$HOME_DIR/upload.json")
say "upload" "$BOOK"

# ---- ingest
STATUS=""
for _ in $(seq 1 60); do
  curl -sf "$BASE/api/v1/books/$BOOK" -o "$HOME_DIR/book.json"
  STATUS=$(.venv/bin/python -c 'import json,sys;print(json.load(open(sys.argv[1]))["work"]["status"])' "$HOME_DIR/book.json")
  [ "$STATUS" = "ready" ] && break
  [ "$STATUS" = "failed" ] && { echo "ingest failed; see $LOG" >&2; tail -20 "$LOG" >&2; exit 1; }
  sleep 1
done
[ "$STATUS" = "ready" ] || { echo "ingest did not finish (last: $STATUS)" >&2; exit 1; }
CHAPTER=$(.venv/bin/python -c 'import json,sys;print(json.load(open(sys.argv[1]))["chapters"][0]["id"])' "$HOME_DIR/book.json")
COUNT=$(.venv/bin/python -c 'import json,sys;print(len(json.load(open(sys.argv[1]))["chapters"]))' "$HOME_DIR/book.json")
say "ingest" "$COUNT chapters, first=$CHAPTER"

# ---- render
CODE=$(curl -s -o "$HOME_DIR/request.json" -w '%{http_code}' -X POST "$BASE/api/v1/chapters/$CHAPTER/audio")
case "$CODE" in 200|202) ;; *) echo "request audio returned $CODE" >&2; cat "$HOME_DIR/request.json" >&2; exit 1;; esac

MANIFEST="$HOME_DIR/manifest.json"
DONE=0
for _ in $(seq 1 240); do
  CODE=$(curl -s -o "$MANIFEST" -w '%{http_code}' "$BASE/api/v1/chapters/$CHAPTER/audio")
  if [ "$CODE" = "200" ]; then DONE=1; break; fi
  [ "$CODE" = "202" ] || { echo "manifest poll returned $CODE" >&2; cat "$MANIFEST" >&2; exit 1; }
  sleep 1
done
[ "$DONE" = "1" ] || { echo "render did not finish; see $LOG" >&2; tail -30 "$LOG" >&2; exit 1; }

.venv/bin/python - "$MANIFEST" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
assert m["complete"] is True, m
assert m["segment_count"] == m["rendered_count"] > 0, m
assert m["duration_ms"] > 0, m
assert m["master_url"] and m["master_url"].startswith("/media/"), m
assert all(s["render_key"].startswith("rk1:") for s in m["segments"]), m
speakers = sorted({s["speaker"] for s in m["segments"]})
print(f'manifest: {m["segment_count"]} segments, {m["duration_ms"]} ms, '
      f'model={m["model_family"]}, speakers={", ".join(speakers)}')
PY

MASTER=$(.venv/bin/python -c 'import json,sys;print(json.load(open(sys.argv[1]))["master_url"])' "$MANIFEST")

# ---- delivery
FULL=$(curl -s -o "$HOME_DIR/master.bin" -w '%{http_code}' "$BASE$MASTER")
[ "$FULL" = "200" ] || { echo "master download returned $FULL" >&2; exit 1; }
RANGE=$(curl -s -o "$HOME_DIR/chunk.bin" -w '%{http_code}' -H 'Range: bytes=0-99' "$BASE$MASTER")
[ "$RANGE" = "206" ] || { echo "range request returned $RANGE" >&2; exit 1; }
SIZE=$(wc -c < "$HOME_DIR/master.bin")
say "delivery" "$SIZE bytes, range 206"

# ---- privacy: a private work must not appear in the public catalogue
CODE=$(curl -s -o "$HOME_DIR/catalogue.json" -w '%{http_code}' "$BASE/api/v1/books")
[ "$CODE" = "200" ] || { echo "catalogue returned $CODE" >&2; exit 1; }
.venv/bin/python - "$HOME_DIR/catalogue.json" "$BOOK" <<'PY'
import json, sys
books = json.load(open(sys.argv[1]))["items"]
assert any(b["id"] == sys.argv[2] for b in books), books
print(f"catalogue: {len(books)} shareable book(s)")
PY

say "result" "PASS"
