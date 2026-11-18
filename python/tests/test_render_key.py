from __future__ import annotations

import unicodedata

import pytest

from aab_tts import canonical_bytes, key_payload, render_key

BASE = dict(
    text="You are mistaken, Mr. Darcy.",
    phon="You are mistaken, Mister Darcy.",
    lang="en-GB",
    spk="chr_7f3a",
    voice={"src": "preset", "preset_id": "af_heart", "rev": 1},
    model={"id": "kokoro-82m", "ver": "1.0-int8", "w": "abc123"},
    params={"seed": 1234, "t_bp": 7000, "p_bp": 9000, "s_pm": 1000},
    perf={"emotion": "indignant", "intensity": 2, "pace": "normal", "style": "clipped"},
    policy="tts-0.1",
    pre="pre-2026-11-a",
)

GOLDEN = "rk1:e9a057d94329326227d0bd4ba6127066a0dbeb7f4cd9353c2f0a72ed5e0e0e71"


def test_key_is_stable() -> None:
    assert render_key(**BASE) == render_key(**BASE)


def test_key_is_versioned() -> None:
    assert render_key(**BASE).startswith("rk1:")


def test_golden_key() -> None:
    assert render_key(**BASE) == GOLDEN


@pytest.mark.parametrize("field,value", [
    ("text", "You are mistaken, Mr Darcy."),
    ("phon", "You are mistaken, Mister Darcy"),
    ("lang", "en-US"),
    ("spk", "chr_0000"),
    ("voice", {"src": "preset", "preset_id": "af_bella", "rev": 1}),
    ("voice", {"src": "preset", "preset_id": "af_heart", "rev": 2}),
    ("model", {"id": "kokoro-82m", "ver": "1.0-int8", "w": "def456"}),
    ("params", {"seed": 1235, "t_bp": 7000, "p_bp": 9000, "s_pm": 1000}),
    ("perf", {"emotion": "indignant", "intensity": 3, "pace": "normal", "style": "clipped"}),
    ("policy", "tts-0.2"),
    ("pre", "pre-2026-11-b"),
])
def test_every_field_changes_the_key(field: str, value) -> None:
    mutated = {**BASE, field: value}
    assert render_key(**mutated) != render_key(**BASE), f"{field} is not in the key"


def test_key_covers_every_payload_field() -> None:
    payload = key_payload(**BASE)
    assert set(payload) == {
        "v", "text", "phon", "lang", "spk", "voice", "model", "params", "perf",
        "policy", "pre",
    }


def test_canonical_bytes_ignores_dict_order() -> None:
    a = {"b": 1, "a": 2, "c": {"y": 1, "x": 2}}
    b = {"c": {"x": 2, "y": 1}, "a": 2, "b": 1}
    assert canonical_bytes(a) == canonical_bytes(b)


def test_unicode_normalisation() -> None:
    composed = "café"
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    key_a = render_key(**{**BASE, "text": composed})
    key_b = render_key(**{**BASE, "text": decomposed})
    assert key_a == key_b


def test_floats_are_rejected() -> None:
    with pytest.raises(ValueError):
        canonical_bytes({"x": float("nan")})


def test_no_ambient_inputs() -> None:
    """Same inputs give the same key regardless of dict construction order."""
    first = render_key(**dict(sorted(BASE.items())))
    second = render_key(**dict(reversed(list(BASE.items()))))
    assert first == second
