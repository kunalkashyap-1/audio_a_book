#!/usr/bin/env bash
# Full-stack dev: start the Python API + worker if needed, then the Next.js app.
# The Next rewrites proxy /api/* and /media/* so the browser stays same-origin.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_URL="${AAB_API_URL:-http://localhost:8000}"
LOG="${TMPDIR:-/tmp/opencode}/aab-api-web.log"
mkdir -p "$(dirname "$LOG")"
API_PID=""

if ! curl -fsS "$API_URL/api/v1/health" >/dev/null 2>&1; then
  echo "Starting API + worker on :8000 …"
  ./scripts/dev.sh >"$LOG" 2>&1 &
  API_PID=$!
  for _ in $(seq 1 30); do
    if curl -fsS "$API_URL/api/v1/health" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi

cleanup() { kill "${API_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "Web      http://localhost:3000"
echo "API      $API_URL  (log: $LOG)"
npm run dev
