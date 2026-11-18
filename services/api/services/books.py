"""Book use cases: upload, catalogue listing, detail.

SQL lives in ``aab_db``; this layer owns validation, file placement and transaction
boundaries. Routers never touch the engine directly.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import Engine

import aab_db as db
from aab_core import InvalidInput, NotFound, Settings, new_id
from aab_ingest import detect_format

MAX_UPLOAD = 25 * 1024 * 1024


def title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return stem.title() or "Untitled"


def create_upload(settings: Settings, engine: Engine, *, filename: str, content: bytes,
                  title: str, author: str, language: str, rights_basis: str,
                  owner_id: str | None = None) -> dict:
    """Validate, store the source bytes, create the work/revision and enqueue ingest."""
    if len(content) > MAX_UPLOAD:
        raise InvalidInput("file larger than 25 MB")
    detect_format(filename, content)

    upload_id = new_id("up")
    suffix = Path(filename).suffix.lower() or ".txt"
    stored = settings.media_dir / "uploads" / f"{upload_id}{suffix}"
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(content)

    with engine.begin() as conn:
        work = db.create_work(
            conn,
            title=title.strip() or title_from_filename(filename),
            author=author.strip() or None,
            language=language or "en",
            rights_basis=rights_basis,
            owner_id=owner_id,
        )
        revision = db.create_revision(conn, work_id=work["id"],
                                      source_path=str(stored), language=language or "en")
        db.insert_upload(conn, upload_id=upload_id, filename=filename,
                         path=str(stored), size=len(content))
        job_id, _created = db.enqueue(
            conn, kind="ingest.revision", target_type="revision",
            target_id=revision["id"], priority=50,
            idempotency_key=f"ingest:{revision['id']}",
        )
    return {"book_id": work["id"], "revision_id": revision["id"], "job_id": job_id}


def _summary(row: dict) -> dict:
    return {
        "id": row["id"], "title": row["title"], "author": row["author"],
        "language": row["language"], "status": row["status"],
        "chapters": int(row["chapters"]),
    }


def list_books(engine: Engine, *, shareable_only: bool, limit: int = 100,
               offset: int = 0, owner_id: str | None = None) -> dict:
    with engine.connect() as conn:
        rows = db.list_works(conn, shareable_only=shareable_only, owner_id=owner_id)
    items = [_summary(row) for row in rows]
    return {"items": items[offset:offset + limit], "total": len(items),
            "limit": limit, "offset": offset}


def book_detail(engine: Engine, book_id: str) -> dict:
    """Full detail payload. Raises ``NotFound`` for an unknown id; the caller authorises."""
    with engine.connect() as conn:
        work = db.get_work(conn, book_id)
        chapters = db.list_chapters(conn, book_id)
        profile_rows = db.list_voice_profiles(conn, book_id)
        chapter_states = []
        for chapter in chapters:
            render_set = db.active_render_set(conn, chapter["id"])
            chapter_states.append({
                "id": chapter["id"],
                "ordinal": chapter["ordinal"],
                "title": chapter["title"],
                "word_count": chapter["word_count"],
                "status": render_set["status"] if render_set else "not_started",
                "progress": render_set["progress"] if render_set else 0,
                "total": render_set["total"] if render_set else 0,
            })
    return {
        "work": dict(work),
        "chapters": chapter_states,
        "cast": [
            {
                "character_id": row["character_id"],
                "name": row["canonical_name"] or "Narrator",
                "voice": row["preset_id"],
                "profile_id": row["id"],
            }
            for row in profile_rows
        ],
    }


def get_work(engine: Engine, book_id: str) -> dict:
    with engine.connect() as conn:
        return dict(db.get_work(conn, book_id))


def unknown_book(book_id: str) -> NotFound:
    return NotFound("book not found")
