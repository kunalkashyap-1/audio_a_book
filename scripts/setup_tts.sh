#!/usr/bin/env bash
# Download the free CPU voice model. Idempotent; safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS="${AAB_MODELS_DIR:-$ROOT/var/models}"
mkdir -p "$MODELS"

BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

fetch() {
  local name="$1" size="$2"
  if [ -f "$MODELS/$name" ]; then
    echo "have  $name"
    return
  fi
  echo "fetch $name (~$size)"
  curl -fL --retry 3 -o "$MODELS/$name.part" "$BASE/$name"
  mv "$MODELS/$name.part" "$MODELS/$name"
}

fetch kokoro-v1.0.int8.onnx 89M
fetch voices-v1.0.bin 27M

echo
echo "Models in $MODELS:"
ls -lh "$MODELS"
echo
echo "Install the runtime with:  uv pip install -e 'python[kokoro]'"
