"""Print the OpenAPI schema to stdout — the single source for generated web types.

Uses an in-memory database and the fake provider so exporting never touches real data or
needs model weights::

    .venv/bin/python scripts/export_openapi.py > packages/contracts/openapi.json
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aab_core import Settings  # noqa: E402
from services.api.app import create_app  # noqa: E402


def main() -> None:
    base = Settings.load()
    settings = dataclasses.replace(base, tts_provider="fake",
                                   database_url="sqlite://")
    json.dump(create_app(settings).openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
