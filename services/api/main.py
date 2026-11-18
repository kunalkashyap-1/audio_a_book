"""Uvicorn entrypoint: ``uvicorn services.api.main:app``."""

from __future__ import annotations

from aab_core import Settings
from services.api.app import create_app

app = create_app(Settings.load())
