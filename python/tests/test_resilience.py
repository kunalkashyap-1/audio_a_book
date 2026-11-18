"""Worker-kill drill: a hard crash mid-render must not duplicate audio on recovery."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import sqlalchemy as sa

import aab_db as db
from aab_core import utcnow
from aab_jobs import drain, run_once
from services.worker.worker.jobs import tts
from services.worker.worker.main import HANDLERS

from test_pipeline import count_renders, render_chapter, seed_book


def _chapter(engine, settings, sample_path) -> dict:
    seeded = seed_book(engine, settings, sample_path)
    drain(engine, settings.worker_id, HANDLERS, settings)
    with engine.connect() as conn:
        return db.list_chapters(conn, seeded["work"]["id"])[0]


def _tts_job(engine) -> dict:
    with engine.connect() as conn:
        row = conn.execute(
            sa.select(db.jobs).where(db.jobs.c.kind == "tts.chapter")
        ).mappings().one()
    return dict(row)


def test_hard_kill_then_recovery_renders_each_line_once(
    engine, settings, sample_path, monkeypatch
) -> None:
    chapter = _chapter(engine, settings, sample_path)
    render_set_id = render_chapter(engine, settings, chapter)
    job_id = _tts_job(engine)["id"]

    original = tts._render_batch
    synthesized: list[str] = []
    calls = {"n": 0}

    def crash_on_second_batch(*args, **kwargs) -> None:
        calls["n"] += 1
        batch = args[-1]
        synthesized.extend(item["segment"]["id"] for item in batch)
        if calls["n"] == 2:
            # After the first batch has committed, but before _finalise runs.
            raise SystemExit("simulated SIGKILL")
        return original(*args, **kwargs)

    monkeypatch.setattr(tts, "_render_batch", crash_on_second_batch)

    with pytest.raises(SystemExit, match="simulated SIGKILL"):
        drain(engine, settings.worker_id, HANDLERS, settings)

    assert calls["n"] == 2

    # A hard kill leaves no cleanup: the job keeps its running state and lease, and the
    # render claims taken at planning time are still held.
    killed = _tts_job(engine)
    assert killed["id"] == job_id
    assert killed["state"] == "running"
    assert killed["lease_owner"] == settings.worker_id
    assert killed["lease_expires_at"] is not None
    assert killed["attempts"] == 1
    with engine.connect() as conn:
        held_claims = int(conn.execute(
            sa.select(sa.func.count()).select_from(db.render_claims)
        ).scalar_one())
    assert held_claims > 0
    assert count_renders(engine) > 0

    # While the lease is live, a second worker must not pick the job up.
    assert run_once(engine, "worker-b", {}, settings) is False
    assert _tts_job(engine)["state"] == "running"

    # Expire both the job lease and the render claims, as a real timeout would.
    stale = utcnow() - timedelta(days=1)
    with engine.begin() as conn:
        conn.execute(sa.update(db.jobs).where(db.jobs.c.id == job_id).values(
            lease_expires_at=stale))
        conn.execute(sa.update(db.render_claims).values(expires_at=stale))

    monkeypatch.setattr(tts, "_render_batch", original)
    drain(engine, settings.worker_id, HANDLERS, settings)

    with engine.connect() as conn:
        job = db.get_job(conn, job_id)
        render_set = db.get_render_set(conn, render_set_id)
        keys = [seg["render_key"] for seg in json.loads(
            (settings.media_dir / render_set["manifest_path"]).read_text()
        )["segments"]]
        renders = db.renders_for_keys(conn, keys)
        claims_left = int(conn.execute(
            sa.select(sa.func.count()).select_from(db.render_claims)
        ).scalar_one())

    assert job["state"] == "succeeded"
    assert job["attempts"] == 2
    assert render_set["status"] == "ready"
    assert render_set["progress"] == render_set["total"] > 0
    assert claims_left == 0

    manifest = json.loads((settings.media_dir / render_set["manifest_path"]).read_text())
    assert manifest["complete"] is True
    assert manifest["rendered_count"] == manifest["segment_count"]
    assert len(renders) == len(set(keys))
    assert count_renders(engine) == len(renders)
    assert len(synthesized) == len(set(synthesized)), "a line was synthesised twice"


def test_render_claims_are_exclusive_until_expired(engine) -> None:
    keys = ["rk1:claim-a", "rk1:claim-b"]
    with engine.begin() as conn:
        assert db.claim_render_keys(conn, keys, "job-1") == set(keys)
    with engine.begin() as conn:
        assert db.claim_render_keys(conn, keys, "job-2") == set()

    with engine.begin() as conn:
        conn.execute(sa.update(db.render_claims).values(expires_at=utcnow() - timedelta(days=1)))
    with engine.begin() as conn:
        assert db.claim_render_keys(conn, keys, "job-2") == set(keys)

    with engine.begin() as conn:
        db.release_claims(conn, keys)
    with engine.connect() as conn:
        assert int(conn.execute(
            sa.select(sa.func.count()).select_from(db.render_claims)
        ).scalar_one()) == 0


def test_stale_job_is_requeued_by_requeue_stale(engine, settings, sample_path) -> None:
    chapter = _chapter(engine, settings, sample_path)
    render_chapter(engine, settings, chapter)
    job_id = _tts_job(engine)["id"]

    with engine.begin() as conn:
        conn.execute(sa.update(db.jobs).where(db.jobs.c.id == job_id).values(
            state="running",
            lease_owner="dead-worker",
            lease_expires_at=utcnow() - timedelta(days=1),
        ))

    with engine.begin() as conn:
        requeued = db.requeue_stale(conn)
    assert requeued == 1
    assert _tts_job(engine)["state"] == "queued"
    assert _tts_job(engine)["lease_owner"] is None

    drain(engine, settings.worker_id, HANDLERS, settings)
    assert _tts_job(engine)["state"] == "succeeded"
