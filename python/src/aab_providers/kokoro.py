"""Kokoro-82M on CPU, via ONNX Runtime.

Apache-2.0 weights, ~90 MB int8, real speech at zero cost. This is the launch provider;
Qwen3-TTS on a serverless GPU is the quality upgrade, and it produces a different render
set because the model identity is in the key.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from aab_core import Settings

from . import AudioPart, ProviderUnavailable, TTSLine, TTSProvider, Voice

VOICE_BANK = [
    "af_heart", "am_michael", "bf_emma", "bm_george", "af_bella",
    "am_adam", "bf_isabella", "bm_lewis", "af_nicole", "am_onyx",
]
_LANGS = {"en": "en-us", "en-us": "en-us", "en-gb": "en-gb", "es": "es",
          "fr": "fr-fr", "it": "it", "pt": "pt-br", "hi": "hi", "ja": "ja", "zh": "cmn"}


class KokoroProvider(TTSProvider):
    id = "local"
    model_id = "kokoro-82m"
    model_version = "1.0-int8"
    sample_rate = 24000
    max_chars_per_line = 400
    presets = VOICE_BANK

    def __init__(self, settings: Settings) -> None:
        try:
            import numpy  # noqa: F401
            from kokoro_onnx import Kokoro
        except Exception as exc:  # pragma: no cover - optional dependency
            raise ProviderUnavailable(
                "kokoro-onnx not installed. Run: uv pip install -e '.[kokoro]'") from exc

        model = self._find(settings.models_dir, ["kokoro-v1.0.int8.onnx", "kokoro-v1.0.onnx"])
        voices = self._find(settings.models_dir, ["voices-v1.0.bin", "voices.bin"])
        if not model or not voices:
            raise ProviderUnavailable(
                f"Kokoro model files not found in {settings.models_dir}. Run scripts/setup_tts.sh")

        self.weights_sha256 = self._file_hash(model)
        self._kokoro = Kokoro(str(model), str(voices))
        self._lock = threading.Lock()
        self._available: list[str] | None = None

    @staticmethod
    def _find(directory: Path, names: list[str]) -> Path | None:
        for name in names:
            candidate = directory / name
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _file_hash(path: Path) -> str:
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if sidecar.exists():
            return sidecar.read_text().strip()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        value = digest.hexdigest()
        try:
            sidecar.write_text(value)
        except OSError:
            pass
        return value

    def _voices(self) -> list[str]:
        if self._available is None:
            try:
                self._available = list(self._kokoro.get_voices())
            except Exception:
                self._available = list(VOICE_BANK)
        return self._available

    def synthesize(self, lines: list[TTSLine], voice: Voice) -> list[AudioPart]:
        import numpy as np

        requested = voice.preset_id or self.presets[0]
        available = self._voices()
        if requested not in available:
            requested = available[0]

        parts: list[AudioPart] = []
        with self._lock:
            for line in lines:
                speed = voice.speed * {"slow": 0.9, "fast": 1.1}.get(line.pace, 1.0)
                speed = max(0.6, min(1.6, speed))
                lang = _LANGS.get(line.lang.lower(), "en-us")
                samples, sr = self._kokoro.create(
                    line.text, voice=requested, speed=speed, lang=lang)
                pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
                duration_ms = int(len(samples) / sr * 1000)
                parts.append(AudioPart(line_id=line.line_id, pcm=pcm,
                                       sample_rate=sr, duration_ms=duration_ms))
        return parts

    def capabilities(self) -> dict:
        caps = super().capabilities()
        caps.update({
            "languages": ["en", "es", "fr", "it", "pt", "hi", "ja", "zh"],
            "max_batch_lines": 32,
            "note": "emotion is expressed only through pace at this model; "
                    "the directive still enters the render key",
        })
        return caps
