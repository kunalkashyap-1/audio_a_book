"""Provider boundary. The only package allowed to know a vendor exists.

At zero-cost launch the "vendor" is a local ONNX model or a deterministic fake. Adding a
paid provider is one module plus one registry entry; no call site changes (ADR-0005).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from aab_core import Settings


class ProviderError(Exception):
    code = "unknown"
    retryable = False


class ProviderUnavailable(ProviderError):
    code = "unavailable"
    retryable = True


@dataclass(frozen=True)
class TTSLine:
    line_id: str
    text: str
    lang: str = "en"
    emotion: str = "neutral"
    intensity: int = 1
    pace: str = "normal"
    style: str = "plain"
    seed: int = 0


@dataclass(frozen=True)
class AudioPart:
    line_id: str
    pcm: bytes          # signed 16-bit little-endian, mono
    sample_rate: int
    duration_ms: int


@dataclass(frozen=True)
class Voice:
    preset_id: str | None = None
    reference_path: str | None = None
    revision: int = 1
    speed: float = 1.0


class TTSProvider(ABC):
    id: str
    model_id: str
    model_version: str
    weights_sha256: str
    sample_rate: int = 24000
    max_chars_per_line: int = 320
    presets: list[str]

    @abstractmethod
    def synthesize(self, lines: list[TTSLine], voice: Voice) -> list[AudioPart]:
        """One call, many lines. Batching is part of the contract, not an optimisation."""

    def capabilities(self) -> dict:
        return {
            "kind": "tts",
            "languages": ["en"],
            "voice_sources": ["preset"],
            "emotion_control": "none",
            "max_chars_per_line": self.max_chars_per_line,
            "max_batch_lines": 32,
            "deterministic_seed": True,
            "sample_rates": [self.sample_rate],
            "weights_sha256": self.weights_sha256,
        }


def build_provider(settings: Settings) -> TTSProvider:
    """Resolve the provider from configuration, degrading rather than failing.

    ``auto`` prefers real speech, then the deterministic fake. The pipeline must always
    run, even on a machine with no models downloaded.
    """
    choice = settings.tts_provider.lower()
    if choice in {"auto", "kokoro"}:
        try:
            from .kokoro import KokoroProvider
            return KokoroProvider(settings)
        except Exception:
            if choice == "kokoro":
                raise
    from .fake import FakeProvider
    return FakeProvider()
