"""Library and playback-progress use cases: a signed-in user's shelf and listening state."""

from __future__ import annotations

from sqlalchemy import Engine

import aab_db as db
from aab_core import NotFound


def list_library(engine: Engine, user_id: str) -> list[dict]:
    with engine.connect() as conn:
        return db.list_library(conn, user_id)


def add_to_library(engine: Engine, user_id: str, book_id: str) -> dict:
    with engine.begin() as conn:
        db.get_work(conn, book_id)          # 404 for an unknown id
        return db.add_library_entry(conn, user_id=user_id, work_id=book_id)


def remove_from_library(engine: Engine, user_id: str, book_id: str) -> None:
    with engine.begin() as conn:
        db.get_work(conn, book_id)
        db.remove_library_entry(conn, user_id=user_id, work_id=book_id)


def set_progress(engine: Engine, user_id: str, chapter_id: str, *,
                 position_ms: int, duration_ms: int | None) -> dict:
    with engine.begin() as conn:
        db.get_chapter(conn, chapter_id)    # 404 for an unknown id
        work = db.work_for_chapter(conn, chapter_id)
        return db.upsert_progress(conn, user_id=user_id, work_id=work["id"],
                                  chapter_id=chapter_id, position_ms=position_ms,
                                  duration_ms=duration_ms)


def get_progress(engine: Engine, user_id: str, chapter_id: str) -> dict | None:
    with engine.connect() as conn:
        db.get_chapter(conn, chapter_id)
        return db.get_progress(conn, user_id=user_id, chapter_id=chapter_id)


def book_progress(engine: Engine, user_id: str, book_id: str) -> dict:
    """Per-chapter progress plus the row to resume from (most recently played)."""
    with engine.begin() as conn:
        db.get_work(conn, book_id)
        rows = db.list_work_progress(conn, user_id=user_id, work_id=book_id)
    chapters = [{
        "chapter_id": r["chapter_id"], "position_ms": r["position_ms"],
        "duration_ms": r["duration_ms"], "updated_at": r["updated_at"],
    } for r in rows]
    return {"work_id": book_id, "chapters": chapters, "last": chapters[0] if rows else None}
