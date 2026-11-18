#!/usr/bin/env bash
# Regenerate the TypeScript contract from the live FastAPI OpenAPI schema.
# Run after any change under services/api/schemas or routers.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi

"$PYTHON" scripts/export_openapi.py > packages/contracts/openapi.json
npm run contracts:generate

echo "contracts: packages/contracts/openapi.json + src/api.d.ts regenerated"
