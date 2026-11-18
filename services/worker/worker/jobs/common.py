"""Shared worker helpers."""

from __future__ import annotations

from aab_core import Settings
from aab_providers import TTSProvider, build_provider

_cache: dict[tuple[str, str], TTSProvider] = {}


def get_provider(settings: Settings) -> TTSProvider:
    key = (settings.tts_provider, str(settings.models_dir))
    if key not in _cache:
        _cache[key] = build_provider(settings)
    return _cache[key]
