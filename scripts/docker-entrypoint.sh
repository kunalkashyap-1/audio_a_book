#!/usr/bin/env bash
# One image, several roles. Compose sets AAB_ROLE; `docker run` defaults to api + worker.
set -euo pipefail

PORT="${PORT:-8000}"
role="${AAB_ROLE:-all}"

api() {
  exec uvicorn services.api.main:app --host 0.0.0.0 --port "$PORT"
}

worker() {
  exec python -m services.worker.worker.main
}

all() {
  uvicorn services.api.main:app --host 0.0.0.0 --port "$PORT" &
  api_pid=$!
  python -m services.worker.worker.main &
  worker_pid=$!
  trap 'kill "$api_pid" "$worker_pid" 2>/dev/null || true' EXIT INT TERM
  wait -n "$api_pid" "$worker_pid"
}

case "$role" in
  api) api ;;
  worker) worker ;;
  all) all ;;
  models)
    echo "Downloading Kokoro weights into ${AAB_MODELS_DIR:-/data/models} …"
    exec bash scripts/setup_tts.sh
    ;;
  *)
    echo "unknown AAB_ROLE: $role (expected api, worker, all or models)" >&2
    exit 2
    ;;
esac
