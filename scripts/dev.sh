#!/usr/bin/env bash
# Local run: API + worker, one machine, no cloud account, no card.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export AAB_HOME="${AAB_HOME:-$ROOT/var}"
mkdir -p "$AAB_HOME"

if [ ! -d .venv ]; then
  echo "Creating virtualenv…"
  uv venv
fi

if ! .venv/bin/python -c "import fastapi" 2>/dev/null; then
  echo "Installing dependencies…"
  uv pip install -e "python[kokoro,dev]"
fi

cleanup() { kill "${API_PID:-}" "${WORKER_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "API      http://localhost:${PORT:-8000}"
echo "Data     $AAB_HOME"
echo

.venv/bin/uvicorn services.api.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" &
API_PID=$!

.venv/bin/python -m services.worker.worker.main &
WORKER_PID=$!

wait -n "$API_PID" "$WORKER_PID"
