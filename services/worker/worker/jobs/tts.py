"""Render a chapter: compute keys, reuse what exists, synthesise only what is missing."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import sqlalchemy as sa

import aab_db as db
from aab_audio import build_master, duration_ms, write_wav
from aab_tts import (model_block, params_block, perf_block, render_key, speakable,
                     speaker_identity, voice_block)
from aab_core import sha256_hex

from .common import get_provider

log = logging.getLogger("aab.tts")

BATCH_LINES = 16
POLICY_VERSION = "tts-0.1"


def handle(engine: sa.Engine, job: dict, settings) -> None:
    provider = get_provider(settings)
    render_set_id = job["target_id"]

    with engine.connect() as conn:
        render_set = db.get_render_set(conn, render_set_id)
        chapter = db.get_chapter(conn, render_set["chapter_id"])
        work = db.work_for_chapter(conn, chapter["id"])
        segments = db.chapter_segments(conn, chapter["id"])
        profiles = db.list_voice_profiles(conn, work["id"])

    if not segments:
        raise RuntimeError("chapter has no narration segments")

    narrator = next((p for p in profiles if p["character_id"] is None), None)
    by_character = {p["character_id"]: p for p in profiles if p["character_id"]}
    if narrator is None:
        raise RuntimeError("work has no narrator voice profile")

    model = model_block(model_id=provider.model_id, version=provider.model_version,
                        weights_sha256=provider.weights_sha256)

    plan = []
    for segment in segments:
        profile = by_character.get(segment["character_id"], narrator)
        voice = voice_block(source="preset", revision=int(profile["revision"]),
                            preset_id=profile["preset_id"] or narrator["preset_id"])
        speed = float((profile["params"] or {}).get("speed", 1.0))
        # The seed is derived from the text, not from the segment id: two books that share a
        # line must produce the same key, otherwise the shared cache is a per-book cache.
        seed = int(sha256_hex(segment["text"])[:8], 16) % (2 ** 31)
        key = render_key(
            text=segment["text"],
            phon=speakable(segment["text"]),
            lang=segment["language"],
            spk=speaker_identity(voice),
            voice=voice,
            model=model,
            params=params_block(seed=seed, speed=speed),
            perf=perf_block(emotion=segment["emotion"], intensity=segment["intensity"],
                            pace=segment["pace"], style=segment["style"]),
            policy=render_set["policy_version"],
            pre=POLICY_VERSION,
        )
        plan.append({
            "segment": segment, "key": key, "profile": profile, "voice": voice,
            "speed": speed, "seed": seed,
        })

    keys = [item["key"] for item in plan]
    unique_keys = list(dict.fromkeys(keys))
    with engine.begin() as conn:
        existing = db.existing_render_keys(conn, unique_keys)
        # A killed worker can leave claims behind for keys it already rendered. Those keys
        # are no longer work, so drop their claims as part of planning; otherwise the claims
        # linger after a successful retry even though the audio is safely cached.
        db.release_claims(conn, list(existing))
        missing = [key for key in unique_keys if key not in existing]
        claimed = db.claim_render_keys(conn, missing, job["id"])
        db.update_render_progress(conn, render_set_id, len(existing), len(unique_keys))

    # Two identical lines in one chapter share a key and therefore one render.
    to_render: list[dict] = []
    queued: set[str] = set()
    for item in plan:
        if item["key"] in claimed and item["key"] not in queued:
            queued.add(item["key"])
            to_render.append(item)

    log.info("plan  %s: %d segments, %d unique, %d cached, %d to render",
             chapter["id"], len(plan), len(unique_keys), len(existing), len(to_render))

    done = len(existing)
    for batch in _batches(to_render):
        _render_batch(engine, job, settings, provider, render_set, chapter, work, batch)
        done += len(batch)
        with engine.begin() as conn:
            db.update_progress(conn, job["id"], done, len(unique_keys))
            db.update_render_progress(conn, render_set_id, done, len(unique_keys))

    with engine.begin() as conn:
        db.release_claims(conn, list(claimed))

    _finalise(engine, settings, render_set, chapter, work, plan)


def _batches(items: list[dict]) -> list[list[dict]]:
    """Group by voice while keeping ordinal order inside each group."""
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item["profile"]["id"], []).append(item)
    batches: list[list[dict]] = []
    for group in groups.values():
        for start in range(0, len(group), BATCH_LINES):
            batches.append(group[start:start + BATCH_LINES])
    return batches


def _render_batch(engine, job, settings, provider, render_set, chapter, work, batch) -> None:
    from aab_providers import TTSLine, Voice

    first = batch[0]
    lines = [
        TTSLine(
            line_id=item["segment"]["id"],
            text=speakable(item["segment"]["text"]),
            lang=item["segment"]["language"],
            emotion=item["segment"]["emotion"],
            intensity=int(item["segment"]["intensity"]),
            pace=item["segment"]["pace"],
            style=item["segment"]["style"],
            seed=item["seed"],
        )
        for item in batch
    ]
    voice = Voice(preset_id=first["voice"]["preset_id"], revision=first["voice"]["rev"],
                  speed=first["speed"])
    parts = provider.synthesize(lines, voice)
    by_line = {part.line_id: part for part in parts}

    with engine.begin() as conn:
        for item in batch:
            part = by_line.get(item["segment"]["id"])
            if part is None:
                continue
            safe = item["key"].replace(":", "_")
            path = settings.media_dir / "segments" / safe[:2] / f"{safe}.wav"
            write_wav(path, part.pcm, part.sample_rate)
            relative = str(path.relative_to(settings.media_dir))
            asset_id = db.insert_asset(
                conn, kind="audio_segment", path=relative,
                sha256=sha256_hex(part.pcm), size=len(part.pcm),
                mime="audio/wav", duration_ms=part.duration_ms,
            )
            db.insert_render(
                conn,
                render_key=item["key"],
                segment_id=item["segment"]["id"],
                asset_id=asset_id,
                voice_profile_id=item["profile"]["id"],
                voice_profile_rev=int(item["profile"]["revision"]),
                model_id=provider.model_id,
                model_version=provider.model_version,
                render_set_id=render_set["id"],
                duration_ms=part.duration_ms,
                shareable=bool(work["shareable"]),
            )


def _finalise(engine, settings, render_set, chapter, work, plan) -> None:
    keys = [item["key"] for item in plan]
    with engine.connect() as conn:
        renders = db.renders_for_keys(conn, keys)

    available = [(item, renders[item["key"]]) for item in plan if item["key"] in renders]
    complete = len(available) == len(plan)

    chapter_dir = (settings.media_dir / "books" / work["id"] / "chapters"
                   / f"{chapter['ordinal']:03d}")
    chapter_dir.mkdir(parents=True, exist_ok=True)

    master_rel = None
    total_ms = 0
    if available:
        paths = [settings.media_dir / row["path"] for _, row in available]
        gaps = [int(item["segment"]["gap_after_ms"]) for item, _ in available]
        master = build_master(paths, gaps, chapter_dir / "master")
        total_ms = duration_ms(master)
        master_rel = str(master.relative_to(settings.media_dir))

    manifest = {
        "chapter_id": chapter["id"],
        "chapter_title": chapter["title"],
        "chapter_ordinal": chapter["ordinal"],
        "work_id": work["id"],
        "render_set_id": render_set["id"],
        "policy_version": render_set["policy_version"],
        "model_family": render_set["model_family"],
        "duration_ms": total_ms,
        "complete": complete,
        "segment_count": len(plan),
        "rendered_count": len(available),
        "master_url": f"/media/{master_rel}" if master_rel else None,
        "segments": [
            {
                "ordinal": item["segment"]["ordinal"],
                "segment_id": item["segment"]["id"],
                "render_key": item["key"],
                "kind": item["segment"]["kind"],
                "speaker": (item["segment"]["canonical_name"]
                            if item["segment"]["canonical_name"] else "Narrator"),
                "text": item["segment"]["text"],
                "duration_ms": row["duration_ms"],
            }
            for item, row in available
        ],
    }
    manifest_path = chapter_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    with engine.begin() as conn:
        db.set_render_outputs(
            conn, render_set["id"],
            master_path=master_rel,
            manifest_path=str(manifest_path.relative_to(settings.media_dir)),
            status="ready" if complete else "ready_with_gaps",
            progress=len(available), total=len(plan),
        )
    log.info("ready %s: %d/%d segments, master %s", render_set["id"],
             len(available), len(plan), master_rel)
