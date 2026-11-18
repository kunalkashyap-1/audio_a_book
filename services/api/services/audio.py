"""Render use cases: request a chapter render, read render status, generate a whole book.

Idempotency lives here: requesting audio for an already-rendered or in-flight chapter
creates nothing, and a failed job is requeued rather than duplicated.
"""

from __future__ import annotations

import json

from sqlalchemy import Engine, text

import aab_db as db
from aab_core import AabError, NotFound, Settings
from aab_providers import TTSProvider
from aab_tts import POLICY_VERSION


def chapter_work(engine: Engine, chapter_id: str) -> dict:
    """The work a chapter belongs to. Raises ``NotFound`` for an unknown chapter."""
    with engine.connect() as conn:
        db.get_chapter(conn, chapter_id)          # 404 for an unknown id
        return dict(db.work_for_chapter(conn, chapter_id))


def request_render(engine: Engine, provider: TTSProvider, chapter_id: str) -> dict:
    with engine.connect() as conn:
        chapter = db.get_chapter(conn, chapter_id)
        render_set = db.active_render_set(conn, chapter_id)
        live_job = None
        if render_set and render_set["job_id"]:
            try:
                live_job = db.get_job(conn, render_set["job_id"])
            except AabError:
                live_job = None

    if render_set:
        if render_set["status"] in {"ready", "ready_with_gaps"}:
            return {
                "job_id": render_set["job_id"], "status": render_set["status"],
                "progress": render_set["progress"], "total": render_set["total"],
            }
        if live_job and live_job["state"] in {"queued", "running"}:
            return {
                "job_id": live_job["id"], "status": "rendering",
                "progress": render_set["progress"], "total": render_set["total"],
            }
        # A failed or dead job falls through and is requeued by enqueue().

    with engine.begin() as conn:
        render_set = db.get_or_create_render_set(
            conn, chapter_id=chapter_id, revision_id=chapter["revision_id"],
            policy_version=POLICY_VERSION, model_family=provider.model_id,
        )
        job_id, _created = db.enqueue(
            conn, kind="tts.chapter", target_type="render_set",
            target_id=render_set["id"], priority=10,
            idempotency_key=f"tts:{render_set['id']}", total=0,
        )
        conn.execute(text("UPDATE render_sets SET job_id = :j WHERE id = :r"),
                     {"j": job_id, "r": render_set["id"]})
    return {"job_id": job_id, "status": "queued"}


def render_status(settings: Settings, engine: Engine, chapter_id: str) -> tuple[int, dict]:
    """``(200, manifest)`` when a manifest exists, else ``(202, pending-state)``."""
    with engine.connect() as conn:
        render_set = db.active_render_set(conn, chapter_id)
    if not render_set or not render_set["manifest_path"]:
        return 202, {
            "status": render_set["status"] if render_set else "not_started",
            "progress": render_set["progress"] if render_set else 0,
            "total": render_set["total"] if render_set else 0,
            "job_id": render_set["job_id"] if render_set else None,
        }
    manifest_file = settings.media_dir / render_set["manifest_path"]
    if not manifest_file.exists():
        return 202, {"status": "preparing"}
    return 200, json.loads(manifest_file.read_text())


def generate_book(engine: Engine, provider: TTSProvider, book_id: str) -> dict:
    with engine.connect() as conn:
        chapters = db.list_chapters(conn, book_id)
        db.get_work(conn, book_id)
    queued = 0
    for chapter in chapters:
        with engine.begin() as conn:
            render_set = db.get_or_create_render_set(
                conn, chapter_id=chapter["id"], revision_id=chapter["revision_id"],
                policy_version=POLICY_VERSION, model_family=provider.model_id,
            )
            job_id, created = db.enqueue(
                conn, kind="tts.chapter", target_type="render_set",
                target_id=render_set["id"], priority=50,
                idempotency_key=f"tts:{render_set['id']}",
            )
            conn.execute(text("UPDATE render_sets SET job_id = :j WHERE id = :r"),
                         {"j": job_id, "r": render_set["id"]})
            queued += int(created)
    return {"chapters": len(chapters), "jobs_created": queued}


def job_status(engine: Engine, job_id: str) -> dict:
    with engine.connect() as conn:
        job = db.get_job(conn, job_id)
    return {
        "id": job["id"], "kind": job["kind"], "state": job["state"],
        "progress": job["progress"], "total": job["total"],
        "error": job["error"],
    }


def unknown_chapter(chapter_id: str) -> NotFound:
    return NotFound("chapter not found")
