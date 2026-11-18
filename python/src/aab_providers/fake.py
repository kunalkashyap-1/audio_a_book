"""Deterministic synthetic voice for development, tests and offline machines.

Not speech. Every line gets a stable, distinct timbre derived from (voice, text) so that
pipeline behaviour — durations, cache hits, voice switching — is fully exercised with no
model download and no GPU.
"""

from __future__ import annotations

import hashlib
import math
from array import array

from . import AudioPart, TTSLine, TTSProvider, Voice

_FRAME = 1.0 / 60.0


class FakeProvider(TTSProvider):
    id = "local"
    model_id = "fake-formant"
    model_version = "1"
    weights_sha256 = "0" * 64
    max_chars_per_line = 320
    presets = [
        "narrator_warm", "voice_a", "voice_b", "voice_c", "voice_d",
        "voice_e", "voice_f", "voice_g", "voice_h",
    ]

    def synthesize(self, lines: list[TTSLine], voice: Voice) -> list[AudioPart]:
        parts = []
        for line in lines:
            rate = 0.88 if line.pace == "slow" else 1.12 if line.pace == "fast" else 1.0
            duration = max(0.45, len(line.text) / 14.5) / rate
            parts.append(AudioPart(
                line_id=line.line_id,
                pcm=self._render(line.text, voice.preset_id or "narrator_warm", duration,
                                 line.emotion),
                sample_rate=self.sample_rate,
                duration_ms=int(duration * 1000),
            ))
        return parts

    def _render(self, text: str, preset: str, duration: float, emotion: str) -> bytes:
        digest = hashlib.sha256(f"{preset}|{text}".encode()).digest()
        base = 92.0 + (digest[0] / 255.0) * 120.0
        vibrato = 4.0 + (digest[1] / 255.0) * 3.0
        brightness = 0.15 + (digest[2] / 255.0) * 0.25
        if emotion in {"tense", "angry", "urgent"}:
            base *= 1.08
        elif emotion in {"afraid", "tender", "sad"}:
            base *= 0.94

        sr = self.sample_rate
        total = int(duration * sr)
        buf = array("h", bytes(2 * total))
        words = max(1, len(text.split()))
        for i in range(total):
            t = i / sr
            # Word-rate envelope gives audible syllable structure.
            word_pos = (t / duration) * words
            envelope = 0.5 + 0.5 * math.sin(math.pi * (word_pos % 1.0))
            fade = min(1.0, t / 0.05, max(0.0, (duration - t)) / 0.08)
            f0 = base * (1.0 + 0.012 * math.sin(2 * math.pi * vibrato * t))
            sample = (
                math.sin(2 * math.pi * f0 * t)
                + brightness * math.sin(2 * math.pi * f0 * 2 * t)
                + brightness * 0.6 * math.sin(2 * math.pi * f0 * 3 * t)
            )
            value = 0.22 * envelope * fade * sample
            buf[i] = int(max(-1.0, min(1.0, value)) * 32767)
        return buf.tobytes()
