from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa

import aab_db as db
from aab_jobs import drain
from aab_tts import POLICY_VERSION, render_key, speakable
from services.worker.worker.jobs.common import get_provider
from services.worker.worker.main import HANDLERS


def seed_book(engine, settings, path: Path, title: str = "The Orchard") -> dict:
    """Do exactly what the upload endpoint does, minus HTTP."""
    stored = settings.media_dir / "uploads" / f"{path.stem}-{title.replace(' ', '_')}.txt"
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(path.read_bytes())

    with engine.begin() as conn:
        work = db.create_work(conn, title=title, author="Test Author", language="en",
                              rights_basis="public_domain_us")
        revision = db.create_revision(conn, work_id=work["id"],
                                      source_path=str(stored), language="en")
        db.enqueue(conn, kind="ingest.revision", target_type="revision",
                   target_id=revision["id"], priority=10,
                   idempotency_key=f"ingest:{revision['id']}")
    return {"work": work, "revision": revision}


def render_chapter(engine, settings, chapter: dict, key_suffix: str = "") -> str:
    provider = get_provider(settings)
    with engine.begin() as conn:
        render_set = db.get_or_create_render_set(
            conn, chapter_id=chapter["id"], revision_id=chapter["revision_id"],
            policy_version=POLICY_VERSION, model_family=provider.model_id,
        )
        db.enqueue(conn, kind="tts.chapter", target_type="render_set",
                   target_id=render_set["id"], priority=10,
                   idempotency_key=f"tts:{render_set['id']}{key_suffix}")
    return render_set["id"]


def count_renders(engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(
            sa.select(sa.func.count()).select_from(db.audio_renders)).scalar_one())


def test_ingest_produces_chapters_cast_and_segments(engine, settings, sample_path) -> None:
    seeded = seed_book(engine, settings, sample_path)
    drain(engine, settings.worker_id, HANDLERS, settings)

    with engine.connect() as conn:
        work = db.get_work(conn, seeded["work"]["id"])
        chapters = db.list_chapters(conn, work["id"])
        assert work["status"] == "ready"
        assert len(chapters) == 2
        assert [c["title"] for c in chapters] == ["Chapter I", "Chapter II"]

        segments = db.chapter_segments(conn, chapters[0]["id"])
        assert len(segments) >= 6
        assert {s["speaker_kind"] for s in segments} == {"narrator", "character"}
        speakers = {s["canonical_name"] for s in segments if s["character_id"]}
        assert "Elizabeth" in speakers
        assert "Darcy" in speakers

        profiles = db.list_voice_profiles(conn, work["id"])
        assert any(p["character_id"] is None for p in profiles)
        # narrator and every character have distinct presets
        presets = [p["preset_id"] for p in profiles]
        assert len(presets) == len(set(presets))


def test_render_produces_a_playable_manifest(engine, settings, sample_path) -> None:
    seeded = seed_book(engine, settings, sample_path)
    drain(engine, settings.worker_id, HANDLERS, settings)

    with engine.connect() as conn:
        chapter = db.list_chapters(conn, seeded["work"]["id"])[0]
    render_set_id = render_chapter(engine, settings, chapter)
    drain(engine, settings.worker_id, HANDLERS, settings)

    with engine.connect() as conn:
        render_set = db.get_render_set(conn, render_set_id)
        chapter = db.get_chapter(conn, chapter["id"])
        work = db.get_work(conn, seeded["work"]["id"])

    assert render_set["status"] == "ready"
    assert render_set["progress"] == render_set["total"] > 0
    assert render_set["master_path"]

    master = settings.media_dir / render_set["master_path"]
    assert master.exists() and master.stat().st_size > 1000

    manifest = json.loads((settings.media_dir / render_set["manifest_path"]).read_text())
    assert manifest["complete"] is True
    assert manifest["rendered_count"] == manifest["segment_count"]
    assert manifest["duration_ms"] > 10_000
    assert manifest["master_url"].startswith("/media/")
    assert all(seg["render_key"].startswith("rk1:") for seg in manifest["segments"])
    speakers = {seg["speaker"] for seg in manifest["segments"]}
    assert {"Elizabeth", "Darcy"} <= speakers


def test_second_request_renders_nothing(engine, settings, sample_path) -> None:
    seeded = seed_book(engine, settings, sample_path)
    drain(engine, settings.worker_id, HANDLERS, settings)
    with engine.connect() as conn:
        chapter = db.list_chapters(conn, seeded["work"]["id"])[0]

    render_chapter(engine, settings, chapter)
    drain(engine, settings.worker_id, HANDLERS, settings)
    after_first = count_renders(engine)

    # A different caller (different idempotency key) asks for the same chapter again.
    render_chapter(engine, settings, chapter, key_suffix=":manual")
    before = count_renders(engine)
    drain(engine, settings.worker_id, HANDLERS, settings)
    assert count_renders(engine) == before
    assert after_first == before


def test_duplicate_enqueue_is_a_no_op(engine, settings, sample_path) -> None:
    seeded = seed_book(engine, settings, sample_path)
    with engine.begin() as conn:
        _, created_first = db.enqueue(
            conn, kind="ingest.revision", target_type="revision",
            target_id=seeded["revision"]["id"], priority=10,
            idempotency_key=f"ingest:{seeded['revision']['id']}")
    assert created_first is False


def test_identical_line_in_two_books_shares_one_render(engine, settings,
                                                      sample_path) -> None:
    """The whole point of the cache: a second book with the same line pays nothing."""
    first = seed_book(engine, settings, sample_path, title="Book One")
    drain(engine, settings.worker_id, HANDLERS, settings)
    with engine.connect() as conn:
        chapter = db.list_chapters(conn, first["work"]["id"])[0]
    render_chapter(engine, settings, chapter)
    drain(engine, settings.worker_id, HANDLERS, settings)
    renders_after_first = count_renders(engine)

    second = seed_book(engine, settings, sample_path, title="Book Two")
    drain(engine, settings.worker_id, HANDLERS, settings)
    with engine.connect() as conn:
        chapter_two = db.list_chapters(conn, second["work"]["id"])[0]
    render_chapter(engine, settings, chapter_two)
    drain(engine, settings.worker_id, HANDLERS, settings)

    assert count_renders(engine) == renders_after_first

    with engine.connect() as conn:
        render_set = db.active_render_set(conn, chapter_two["id"])
    assert render_set["status"] == "ready"


def test_voice_change_invalidates_only_that_character(engine, settings,
                                                      sample_path) -> None:
    seeded = seed_book(engine, settings, sample_path)
    drain(engine, settings.worker_id, HANDLERS, settings)
    with engine.connect() as conn:
        chapter = db.list_chapters(conn, seeded["work"]["id"])[0]
    render_chapter(engine, settings, chapter)
    drain(engine, settings.worker_id, HANDLERS, settings)

    with engine.begin() as conn:
        profiles = db.list_voice_profiles(conn, seeded["work"]["id"])
        character = next(p for p in profiles if p["character_id"])
        conn.execute(sa.update(db.voice_profiles)
                     .where(db.voice_profiles.c.id == character["id"])
                     .values(revision=2, preset_id="af_bella"))

    # A new set is required because the voice identity changed for one speaker only.
    with engine.connect() as conn:
        chapter = db.get_chapter(conn, chapter["id"])
    render_set_id = render_chapter(engine, settings, chapter, key_suffix=":v2")
    drain(engine, settings.worker_id, HANDLERS, settings)

    with engine.connect() as conn:
        renders = conn.execute(
            sa.select(db.audio_renders.c.voice_profile_id,
                      db.audio_renders.c.voice_profile_rev,
                      sa.func.count()).group_by(db.audio_renders.c.voice_profile_id,
                                                db.audio_renders.c.voice_profile_rev)
        ).all()
    narrator = next(p for p in profiles if p["character_id"] is None)
    revisions = {(profile_id, rev) for profile_id, rev, _ in renders}
    # The narrator was never re-rendered; the changed character exists at both revisions.
    assert {rev for profile_id, rev in revisions if profile_id == narrator["id"]} == {1}
    assert {rev for profile_id, rev in revisions if profile_id == character["id"]} == {1, 2}


def test_private_work_is_not_in_public_listing(engine, settings, sample_path) -> None:
    """The catalogue is a sharing surface, not a filesystem listing."""
    shared = seed_book(engine, settings, sample_path, title="Shared Book")
    with engine.begin() as conn:
        private = db.create_work(conn, title="Private Draft", author=None, language="en",
                                 rights_basis="user_upload_private")

    with engine.connect() as conn:
        public_ids = {w["id"] for w in db.list_works(conn, shareable_only=True)}
        all_ids = {w["id"] for w in db.list_works(conn)}

    assert shared["work"]["id"] in public_ids
    assert private["id"] not in public_ids
    assert private["id"] in all_ids


def test_render_key_ignores_book_identity(engine, settings, sample_path) -> None:
    provider = get_provider(settings)
    voice = {"src": "preset", "preset_id": "af_heart", "rev": 1}
    model = {"id": provider.model_id, "ver": provider.model_version,
             "w": provider.weights_sha256}
    text = "You are mistaken, Mr. Darcy."
    kwargs = dict(
        text=text, phon=speakable(text), lang="en", voice=voice, model=model,
        params={"seed": 7, "t_bp": 7000, "p_bp": 9000, "s_pm": 1000},
        perf={"emotion": "neutral", "intensity": 1, "pace": "normal", "style": "plain"},
        policy=POLICY_VERSION, pre="pre-2026-11-a",
    )
    a = render_key(spk="af_heart", **kwargs)
    b = render_key(spk="af_heart", **kwargs)
    assert a == b
    assert render_key(spk="af_bella", **kwargs) != a
