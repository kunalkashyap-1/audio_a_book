"""Turn an uploaded file into chapters, blocks, characters and narration segments."""

from __future__ import annotations

import logging
from pathlib import Path

import sqlalchemy as sa

import aab_db as db
from aab_core import AabError, sha256_hex
from aab_ingest import parse
from aab_story import Unit, analyse_chapter, extract_cast, infer_genders, merge_short
from aab_tts import speakable, split_for_tts

from .common import get_provider

log = logging.getLogger("aab.ingest")


def handle(engine: sa.Engine, job: dict, settings) -> None:
    revision_id = job["target_id"]
    with engine.connect() as conn:
        revision = db.get_revision(conn, revision_id)
        work = db.get_work(conn, revision["work_id"])

    provider = get_provider(settings)
    source = Path(revision["source_path"])
    try:
        parsed = parse(source.name, source.read_bytes(), work["language"])
    except AabError as exc:
        with engine.begin() as conn:
            db.set_revision_status(conn, revision_id, "failed", error=str(exc))
            db.set_work_status(conn, work["id"], "failed")
        raise

    full_text = "\n\n".join(chapter.text for chapter in parsed.chapters)
    cast = extract_cast(full_text)
    genders = infer_genders(full_text, cast.names)
    log.info("parsed %s: %d chapters, %d words, %d cast",
             revision_id, len(parsed.chapters), parsed.word_count, len(cast.names))

    with engine.begin() as conn:
        db.set_revision_status(conn, revision_id, "parsing",
                               word_count=parsed.word_count,
                               text_sha256=sha256_hex(full_text))

        chapter_rows = db.insert_chapters(conn, revision_id, [
            {"title": chapter.title, "text": chapter.text} for chapter in parsed.chapters
        ])
        char_rows = db.insert_characters(conn, work["id"], [
            {"name": name, "role": cast.roles.get(name), "confidence": 0.5}
            for name in cast.names
        ])
        name_to_id = {row["name"]: row["id"] for row in char_rows}
        db.ensure_voices(conn, work["id"], provider.model_id, provider.presets)

        total_segments = 0
        for chapter_row, source_chapter in zip(chapter_rows, parsed.chapters):
            units = merge_short(analyse_chapter(source_chapter.text, cast.names, genders))
            db.insert_blocks(conn, chapter_row["id"], [
                {"kind": _block_kind(unit), "text": unit.text} for unit in units
            ])
            segments = _segments(units, name_to_id, provider.max_chars_per_line,
                                 work["language"])
            db.insert_segments(conn, revision_id, chapter_row["id"], segments)
            total_segments += len(segments)

        db.set_revision_status(conn, revision_id, "ready")
        db.set_work_status(conn, work["id"], "ready")

    log.info("ready %s: %d segments", revision_id, total_segments)


def _block_kind(unit: Unit) -> str:
    return {"heading": "heading", "dialogue": "dialogue"}.get(unit.kind, "narration")


def _segments(units: list[Unit], name_to_id: dict[str, str], max_chars: int,
              language: str) -> list[dict]:
    out: list[dict] = []
    for unit in units:
        chunks = split_for_tts(unit.text, max_chars)
        is_narrator = unit.speaker in (None, "narrator") or unit.speaker not in name_to_id
        for index, chunk in enumerate(chunks):
            out.append({
                "kind": "heading" if unit.kind == "heading" else unit.kind,
                "text": chunk,
                "phon": speakable(chunk),
                "language": language,
                "speaker_kind": "narrator" if is_narrator else "character",
                "character_id": None if is_narrator else name_to_id[unit.speaker],
                "gap_after_ms": unit.gap_after_ms if index == len(chunks) - 1 else 60,
                "emotion": unit.emotion,
                "intensity": unit.intensity,
                "pace": unit.pace,
                "confidence": unit.confidence,
                "source": unit.method,
            })
    return out
