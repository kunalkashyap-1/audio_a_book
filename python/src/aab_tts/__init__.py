"""Render key and segmentation.

The key is the most expensive thing in the project to get wrong: too few fields and two
different performances collide, too many and the cache never hits. ADR-0004 explains each
field; this module is the single implementation.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

KEY_VERSION = "rk1"
POLICY_VERSION = "tts-0.1"
PAYLOAD_FIELDS = ("v", "text", "phon", "lang", "spk", "voice", "model", "params",
                  "perf", "policy", "pre")

_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "jr", "sr", "vs", "etc", "no",
                  "vol", "ch", "p", "pp", "e.g", "i.e", "cf", "prof", "capt", "col",
                  "gen", "lt", "sgt", "rev", "hon"}


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _sha(value: str) -> str:
    return hashlib.sha256(_nfc(value).encode("utf-8")).hexdigest()


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def render_key(
    *,
    text: str,
    phon: str,
    lang: str,
    spk: str,
    voice: dict,
    model: dict,
    params: dict,
    perf: dict,
    policy: str,
    pre: str,
) -> str:
    """``rk1:<sha256>`` over a canonical payload. Pure: same inputs, same key, always."""
    payload = {
        "v": 1,
        "text": _sha(text),
        "phon": _sha(phon),
        "lang": _nfc(lang).lower(),
        "spk": spk,
        "voice": voice,
        "model": model,
        "params": params,
        "perf": perf,
        "policy": policy,
        "pre": pre,
    }
    return f"{KEY_VERSION}:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()


def key_payload(*, text: str, phon: str, lang: str, spk: str, voice: dict, model: dict,
                params: dict, perf: dict, policy: str, pre: str) -> dict:
    return {
        "v": 1, "text": _sha(text), "phon": _sha(phon), "lang": _nfc(lang).lower(),
        "spk": spk, "voice": voice, "model": model, "params": params, "perf": perf,
        "policy": policy, "pre": pre,
    }


def voice_block(*, source: str, revision: int, ref: str | None = None,
                preset_id: str | None = None, design_hash: str | None = None) -> dict:
    block: dict = {"src": source, "rev": int(revision)}
    if source == "reference_clone":
        block["ref"] = ref
    elif source == "preset":
        block["preset_id"] = preset_id
    elif source == "designed":
        block["design_hash"] = design_hash
    else:
        raise ValueError(f"unknown voice source: {source}")
    return block


def model_block(*, model_id: str, version: str, weights_sha256: str) -> dict:
    return {"id": model_id, "ver": version, "w": weights_sha256}


def speaker_identity(voice: dict) -> str:
    """A book-independent name for the voice, used as the key's speaker slot.

    A character id would make every book's copy of the same line unique and destroy the
    shared cache. ``voice`` already pins identity, so this is a stable label for it.
    """
    return (voice.get("preset_id") or voice.get("ref") or voice.get("design_hash")
            or "default")


def params_block(*, seed: int, temperature: float = 0.7, top_p: float = 0.9,
                 speed: float = 1.0) -> dict:
    return {
        "seed": int(seed),
        "t_bp": int(round(temperature * 10_000)),
        "p_bp": int(round(top_p * 10_000)),
        "s_pm": int(round(speed * 1000)),
    }


def perf_block(*, emotion: str, intensity: int, pace: str, style: str) -> dict:
    return {"emotion": emotion, "intensity": int(intensity), "pace": pace, "style": style}


# ---------------------------------------------------------------- segmentation

_ABBREV = {
    "mr.": "mister", "mrs.": "missus", "ms.": "miz", "dr.": "doctor",
    "st.": "saint", "jr.": "junior", "sr.": "senior", "vs.": "versus",
    "etc.": "et cetera", "no.": "number", "col.": "colonel", "capt.": "captain",
}


def speakable(text: str) -> str:
    """The form sent to the model. Hashing this (not the raw text) is what makes
    ``phon_hash`` meaningful: changing "Mr." to "Mister" must not invalidate audio
    that already says the same thing."""
    out = text
    def _long(match: re.Match[str]) -> str:
        word = match.group(0)
        replacement = _ABBREV[word.lower()]
        return replacement.capitalize() if word[:1].isupper() else replacement
    for short in _ABBREV:
        out = re.sub(rf"\b{re.escape(short)}", _long, out, flags=re.IGNORECASE)
    out = out.replace("—", ", ").replace("–", ", ")
    out = re.sub(r"\[\d+\]", "", out)
    return re.sub(r"\s+", " ", out).strip()

_SENTENCE = re.compile(r"(?<=[.!?])[\"”’)]?\s+")


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE.split(text) if p.strip()]
    out: list[str] = []
    for part in parts:
        if out:
            last_word = re.split(r"[\s(\"“]", out[-1].rstrip("\"”’").strip())[-1].lower()
            last_word = re.sub(r"[^\w]+$", "", last_word)
            if last_word in _ABBREVIATIONS and len(out[-1]) < 120:
                out[-1] = f"{out[-1]} {part}"
                continue
        out.append(part)
    return out


def split_for_tts(text: str, max_chars: int = 320) -> list[str]:
    """Pack sentences into lines the model can handle without drifting."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return [text] if text else []

    chunks: list[str] = []
    current = ""
    for sentence in sentences(text):
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            chunks.append(current)
            current = sentence

        while len(current) > max_chars:
            cut = max(current.rfind(", ", 0, max_chars), current.rfind("; ", 0, max_chars),
                      current.rfind(" ", 0, max_chars))
            if cut <= 0:
                cut = max_chars
            chunks.append(current[:cut].strip())
            current = current[cut:].strip()
    if current:
        chunks.append(current)
    return [c for c in chunks if c]
