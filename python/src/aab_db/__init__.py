"""Engine, schema creation and every SQL statement in the system.

Application code calls these functions; nothing else writes SQL.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

import sqlalchemy as sa
from sqlalchemy import delete, func, insert, select, update

from aab_core import Conflict, NotFound, new_id, sha256_hex, utcnow

from .models import (
    admin_audit, assets, audio_renders, blocks, chapters, characters, editions,
    feature_flags, jobs, job_events, library_entries, metadata, narration_segments,
    performance_directives, playback_progress, render_claims, render_sets,
    revisions, sessions, uploads, users, voice_profiles, works,
)

__all__ = ["make_engine", "init_db", "metadata"]


def make_engine(url: str) -> sa.Engine:
    kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = sa.create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        @sa.event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _record):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()
    return engine


_SIMPLE_DEFAULT_RE = re.compile(r"^-?\d+(\.\d+)?$|^'.*'$|^(true|false|null)$", re.I)


def init_db(engine: sa.Engine) -> None:
    metadata.create_all(engine)
    _migrate_additive(engine)


def _migrate_additive(engine: sa.Engine) -> None:
    """``create_all`` never alters existing tables; add columns introduced after launch.

    Only plain columns — nullable or with a simple server default — are carried, which
    covers every schema change so far. Works identically on SQLite and PostgreSQL, so the
    run-default database upgrades itself in place.
    """
    inspector = sa.inspect(engine)
    table_names = set(inspector.get_table_names())
    preparer = engine.dialect.identifier_preparer
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            if table.name not in table_names:
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                parts = [preparer.quote(column.name),
                         column.type.compile(engine.dialect)]
                if column.server_default is not None:
                    arg = column.server_default.arg
                    default = getattr(arg, "text", None) or str(arg)
                    if not _SIMPLE_DEFAULT_RE.fullmatch(default):
                        default = "'" + default.replace("'", "''") + "'"
                    parts.append(f"DEFAULT {default}")
                conn.execute(sa.text(
                    f"ALTER TABLE {preparer.quote(table.name)} ADD COLUMN "
                    + " ".join(parts)))


# ---------------------------------------------------------------- works / revisions

def create_work(conn, *, title: str, author: str | None, language: str,
                rights_basis: str, description: str | None = None,
                owner_id: str | None = None) -> dict:
    wid = new_id("bk")
    conn.execute(insert(works).values(
        id=wid, title=title, author=author, language=language,
        rights_basis=rights_basis, description=description,
        shareable=rights_basis.startswith("public_domain"),
        owner_id=owner_id, status="new", created_at=utcnow(),
    ))
    return get_work(conn, wid)


def get_work(conn, work_id: str) -> dict:
    row = conn.execute(select(works).where(works.c.id == work_id)).mappings().first()
    if not row:
        raise NotFound("work not found")
    return dict(row)


def list_works(conn, *, shareable_only: bool = False,
               owner_id: str | None = None) -> list[dict]:
    """Catalogue rows. ``owner_id`` widens the filter: shareable works plus the caller's own."""
    chapter_count = (
        select(chapters.c.revision_id, func.count().label("n"))
        .group_by(chapters.c.revision_id).subquery()
    )
    query = (
        select(
            works,
            func.coalesce(func.max(chapter_count.c.n), 0).label("chapters"),
        )
        .join(revisions, revisions.c.work_id == works.c.id, isouter=True)
        .join(chapter_count, chapter_count.c.revision_id == revisions.c.id, isouter=True)
        .group_by(works.c.id)
        .order_by(works.c.created_at.desc())
    )
    if shareable_only:
        if owner_id:
            query = query.where(sa.or_(works.c.shareable.is_(True),
                                       works.c.owner_id == owner_id))
        else:
            query = query.where(works.c.shareable.is_(True))
    rows = conn.execute(query).mappings().all()
    return [dict(r) for r in rows]


def create_revision(conn, *, work_id: str, source_path: str, language: str) -> dict:
    rid = new_id("rev")
    eid = new_id("ed")
    conn.execute(insert(editions).values(
        id=eid, work_id=work_id, source="upload", language=language))
    conn.execute(insert(revisions).values(
        id=rid, work_id=work_id, edition_id=eid, source_path=source_path,
        language=language, status="pending", created_at=utcnow(),
    ))
    return get_revision(conn, rid)


def get_revision(conn, revision_id: str) -> dict:
    row = conn.execute(
        select(revisions).where(revisions.c.id == revision_id)).mappings().first()
    if not row:
        raise NotFound("revision not found")
    return dict(row)


def set_revision_status(conn, revision_id: str, status: str,
                        *, word_count: int | None = None,
                        text_sha256: str | None = None,
                        error: str | None = None) -> None:
    values: dict[str, Any] = {"status": status, "error": error}
    if word_count is not None:
        values["word_count"] = word_count
    if text_sha256 is not None:
        values["text_sha256"] = text_sha256
    conn.execute(update(revisions).where(revisions.c.id == revision_id).values(**values))


def active_revision(conn, work_id: str) -> dict | None:
    row = conn.execute(
        select(revisions).where(revisions.c.work_id == work_id, revisions.c.status == "ready")
        .order_by(revisions.c.created_at.desc()).limit(1)
    ).mappings().first()
    return dict(row) if row else None


# ---------------------------------------------------------------- structure

def insert_chapters(conn, revision_id: str, items: Sequence[dict]) -> list[dict]:
    out = []
    for ordinal, item in enumerate(items):
        cid = new_id("ch")
        conn.execute(insert(chapters).values(
            id=cid, revision_id=revision_id, ordinal=ordinal, title=item["title"],
            char_start=item.get("char_start", 0), char_end=item.get("char_end", 0),
            word_count=len(item["text"].split()),
        ))
        out.append({**item, "id": cid, "ordinal": ordinal})
    return out


def insert_blocks(conn, chapter_id: str, items: Sequence[dict]) -> list[dict]:
    out = []
    for ordinal, item in enumerate(items):
        bid = new_id("blk")
        conn.execute(insert(blocks).values(
            id=bid, chapter_id=chapter_id, ordinal=ordinal, kind=item["kind"],
            text=item["text"], text_hash=sha256_hex(item["text"]),
        ))
        out.append({**item, "id": bid, "ordinal": ordinal})
    return out


def insert_characters(conn, work_id: str, items: Sequence[dict]) -> list[dict]:
    out = []
    for item in items:
        cid = new_id("chr")
        try:
            with conn.begin_nested():
                conn.execute(insert(characters).values(
                    id=cid, work_id=work_id, canonical_name=item["name"],
                    role=item.get("role"), description=item.get("description"),
                    confidence=item.get("confidence", 0.0), status="auto",
                ))
        except sa.exc.IntegrityError:
            continue
        out.append({**item, "id": cid})
    return out


def insert_segments(conn, revision_id: str, chapter_id: str,
                    items: Sequence[dict]) -> list[dict]:
    out = []
    for ordinal, item in enumerate(items):
        sid = new_id("sg")
        conn.execute(insert(narration_segments).values(
            id=sid, revision_id=revision_id, chapter_id=chapter_id, ordinal=ordinal,
            kind=item["kind"], text=item["text"],
            text_hash=sha256_hex(item["text"]), phon_hash=sha256_hex(item["phon"]),
            language=item.get("language", "en"), speaker_kind=item["speaker_kind"],
            character_id=item.get("character_id"), char_count=len(item["text"]),
            gap_after_ms=item.get("gap_after_ms", 120),
        ))
        conn.execute(insert(performance_directives).values(
            segment_id=sid, emotion=item.get("emotion", "neutral"),
            intensity=item.get("intensity", 1), pace=item.get("pace", "normal"),
            style=item.get("style", "plain"), source=item.get("source", "rules"),
            confidence=item.get("confidence", 1.0),
        ))
        out.append({**item, "id": sid, "ordinal": ordinal})
    return out


def get_chapter(conn, chapter_id: str) -> dict:
    row = conn.execute(select(chapters).where(chapters.c.id == chapter_id)).mappings().first()
    if not row:
        raise NotFound("chapter not found")
    return dict(row)


def list_chapters(conn, work_id: str) -> list[dict]:
    rev = active_revision(conn, work_id)
    if not rev:
        return []
    rows = conn.execute(
        select(chapters).where(chapters.c.revision_id == rev["id"])
        .order_by(chapters.c.ordinal)
    ).mappings().all()
    return [dict(r) for r in rows]


def chapter_segments(conn, chapter_id: str) -> list[dict]:
    rows = conn.execute(
        select(narration_segments, performance_directives,
               characters.c.canonical_name)
        .join(performance_directives,
              performance_directives.c.segment_id == narration_segments.c.id)
        .join(characters, characters.c.id == narration_segments.c.character_id, isouter=True)
        .where(narration_segments.c.chapter_id == chapter_id)
        .order_by(narration_segments.c.ordinal)
    ).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- voices

def ensure_voices(conn, work_id: str, model_family: str, presets: Sequence[str]) -> dict:
    """One narrator profile plus one profile per character, deterministic by order."""
    existing = conn.execute(
        select(voice_profiles).where(voice_profiles.c.work_id == work_id)).mappings().all()
    if existing:
        return {("narrator" if p["character_id"] is None else p["character_id"]): dict(p)
                for p in existing}

    created: dict[str, dict] = {}
    vid = new_id("vp")
    conn.execute(insert(voice_profiles).values(
        id=vid, scope="system", character_id=None, work_id=work_id, revision=1,
        source_type="preset", preset_id=presets[0], model_family=model_family,
        params={"speed": 1.0}, persona={"role": "narrator"}, locked=True,
    ))
    created["narrator"] = {"id": vid, "preset_id": presets[0], "revision": 1}

    chars = conn.execute(
        select(characters).where(characters.c.work_id == work_id)
        .order_by(characters.c.canonical_name)
    ).mappings().all()
    bank = presets[1:] or presets
    for i, ch in enumerate(chars):
        vid = new_id("vp")
        preset = bank[i % len(bank)]
        conn.execute(insert(voice_profiles).values(
            id=vid, scope="system", character_id=ch["id"], work_id=work_id, revision=1,
            source_type="preset", preset_id=preset, model_family=model_family,
            params={"speed": 1.0}, persona={"role": ch["role"] or "character"},
            locked=False,
        ))
        created[ch["id"]] = {"id": vid, "preset_id": preset, "revision": 1}
    return created


def list_voice_profiles(conn, work_id: str) -> list[dict]:
    rows = conn.execute(
        select(voice_profiles, characters.c.canonical_name)
        .join(characters, characters.c.id == voice_profiles.c.character_id, isouter=True)
        .where(voice_profiles.c.work_id == work_id)
    ).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- render sets / cache

def get_or_create_render_set(conn, *, chapter_id: str, revision_id: str,
                             policy_version: str, model_family: str) -> dict:
    existing = conn.execute(
        select(render_sets).where(
            render_sets.c.chapter_id == chapter_id,
            render_sets.c.policy_version == policy_version,
            render_sets.c.model_family == model_family,
        )
    ).mappings().first()
    if existing:
        return dict(existing)
    rsid = new_id("rs")
    conn.execute(insert(render_sets).values(
        id=rsid, chapter_id=chapter_id, revision_id=revision_id, scope="system",
        policy_version=policy_version, model_family=model_family, status="draft",
        is_active=False, created_at=utcnow(),
    ))
    conn.execute(update(render_sets)
                 .where(render_sets.c.chapter_id == chapter_id,
                        render_sets.c.id != rsid)
                 .values(is_active=False))
    conn.execute(update(render_sets).where(render_sets.c.id == rsid).values(is_active=True))
    return dict(conn.execute(
        select(render_sets).where(render_sets.c.id == rsid)).mappings().one())


def set_render_set_status(conn, render_set_id: str, status: str) -> None:
    conn.execute(update(render_sets).where(render_sets.c.id == render_set_id)
                 .values(status=status))


def get_render_set(conn, render_set_id: str) -> dict:
    row = conn.execute(select(render_sets)
                       .where(render_sets.c.id == render_set_id)).mappings().first()
    if not row:
        raise NotFound("render set not found")
    return dict(row)


def active_render_set(conn, chapter_id: str) -> dict | None:
    row = conn.execute(
        select(render_sets).where(render_sets.c.chapter_id == chapter_id,
                                  render_sets.c.is_active.is_(True))
        .order_by(render_sets.c.created_at.desc()).limit(1)
    ).mappings().first()
    return dict(row) if row else None


def set_work_status(conn, work_id: str, status: str) -> None:
    conn.execute(update(works).where(works.c.id == work_id).values(status=status))


def work_for_chapter(conn, chapter_id: str) -> dict:
    row = conn.execute(
        select(works).join(revisions, revisions.c.work_id == works.c.id)
        .join(chapters, chapters.c.revision_id == revisions.c.id)
        .where(chapters.c.id == chapter_id)
    ).mappings().first()
    if not row:
        raise NotFound("work not found for chapter")
    return dict(row)


def existing_render_keys(conn, keys: Sequence[str]) -> set[str]:
    if not keys:
        return set()
    rows = conn.execute(
        select(audio_renders.c.render_key).where(audio_renders.c.render_key.in_(keys))
    ).scalars().all()
    return set(rows)


def claim_render_keys(conn, keys: Sequence[str], job_id: str, minutes: int = 20) -> set[str]:
    """Return the subset of keys this job now owns. Stale claims are stolen.

    A savepoint is used so a losing INSERT does not abort the surrounding transaction on
    PostgreSQL (SQLite tolerates it, but the code should not depend on that).
    """
    if not keys:
        return set()
    now = utcnow()
    expiry = now + _minutes(minutes)
    claimed: set[str] = set()
    for key in keys:
        try:
            with conn.begin_nested():
                conn.execute(insert(render_claims).values(
                    render_key=key, job_id=job_id, expires_at=expiry))
            claimed.add(key)
            continue
        except sa.exc.IntegrityError:
            pass
        row = conn.execute(select(render_claims)
                           .where(render_claims.c.render_key == key)).mappings().first()
        if row and row["expires_at"] < now:
            conn.execute(update(render_claims)
                         .where(render_claims.c.render_key == key)
                         .values(job_id=job_id, expires_at=expiry))
            claimed.add(key)
    return claimed


def _minutes(n: int):
    from datetime import timedelta
    return timedelta(minutes=n)


def release_claims(conn, keys: Sequence[str]) -> None:
    if keys:
        conn.execute(sa.delete(render_claims).where(render_claims.c.render_key.in_(keys)))


def insert_asset(conn, *, kind: str, path: str, sha256: str, size: int,
                 mime: str, duration_ms: int | None) -> str:
    """Content-addressed by path: an identical render key reuses the existing asset row."""
    existing = conn.execute(
        select(assets.c.id).where(assets.c.path == path)).scalar_one_or_none()
    if existing:
        return existing
    aid = new_id("as")
    try:
        with conn.begin_nested():
            conn.execute(insert(assets).values(
                id=aid, kind=kind, path=path, sha256=sha256, bytes=size, mime=mime,
                duration_ms=duration_ms, created_at=utcnow()))
    except sa.exc.IntegrityError:
        return conn.execute(
            select(assets.c.id).where(assets.c.path == path)).scalar_one()
    return aid


def insert_render(conn, *, render_key: str, segment_id: str, asset_id: str,
                  voice_profile_id: str, voice_profile_rev: int, model_id: str,
                  model_version: str, render_set_id: str, duration_ms: int,
                  shareable: bool = True) -> bool:
    """Returns True if this call created the row. Losing the race is not an error."""
    try:
        with conn.begin_nested():
            conn.execute(insert(audio_renders).values(
                render_key=render_key, segment_id=segment_id, asset_id=asset_id,
                voice_profile_id=voice_profile_id, voice_profile_rev=voice_profile_rev,
                model_id=model_id, model_version=model_version,
                render_set_id=render_set_id, duration_ms=duration_ms,
                qc_status="passed", generated_by="system", shareable=shareable,
                created_at=utcnow(),
            ))
        return True
    except sa.exc.IntegrityError:
        return False


def renders_for_keys(conn, keys: Sequence[str]) -> dict[str, dict]:
    """Renders are global: the key is the identity, not the render set that first paid for it.

    This is what makes one book's audio reusable by another book with the same line and
    voice, and it is why ``audio_renders`` is queried by key rather than by render set.
    """
    if not keys:
        return {}
    rows = conn.execute(
        select(audio_renders, assets)
        .join(assets, assets.c.id == audio_renders.c.asset_id)
        .where(audio_renders.c.render_key.in_(keys))
    ).mappings().all()
    return {row["render_key"]: dict(row) for row in rows}


def set_render_outputs(conn, render_set_id: str, *, master_path: str | None,
                       manifest_path: str | None, status: str,
                       progress: int, total: int) -> None:
    conn.execute(update(render_sets).where(render_sets.c.id == render_set_id).values(
        master_path=master_path, manifest_path=manifest_path, status=status,
        progress=progress, total=total))


def update_render_progress(conn, render_set_id: str, progress: int, total: int) -> None:
    conn.execute(update(render_sets).where(render_sets.c.id == render_set_id)
                 .values(progress=progress, total=total, status="rendering"))


def chapter_progress(conn, chapter_id: str, render_set_id: str) -> tuple[int, int]:
    row = conn.execute(select(render_sets.c.progress, render_sets.c.total)
                       .where(render_sets.c.id == render_set_id)).mappings().first()
    return (int(row["progress"]), int(row["total"])) if row else (0, 0)


# ---------------------------------------------------------------- jobs

def enqueue(conn, *, kind: str, target_type: str, target_id: str,
            priority: int = 100, idempotency_key: str, total: int = 0) -> tuple[str, bool]:
    """Returns (job_id, created). A duplicate enqueue is a no-op unless the previous
    attempt failed, in which case the existing job is requeued rather than duplicated."""
    existing = conn.execute(
        select(jobs.c.id, jobs.c.state).where(jobs.c.idempotency_key == idempotency_key)
    ).mappings().first()
    if existing:
        if existing["state"] in {"failed", "cancelled", "dead"}:
            conn.execute(update(jobs).where(jobs.c.id == existing["id"]).values(
                state="queued", attempts=0, error=None, lease_owner=None,
                lease_expires_at=None, updated_at=utcnow()))
            conn.execute(insert(job_events).values(
                job_id=existing["id"], event="requeued",
                detail={"reason": "duplicate request after failure"}, created_at=utcnow()))
            return existing["id"], True
        return existing["id"], False
    jid = new_id("job")
    try:
        with conn.begin_nested():
            conn.execute(insert(jobs).values(
                id=jid, kind=kind, target_type=target_type, target_id=target_id,
                priority=priority, state="queued", idempotency_key=idempotency_key,
                attempts=0, max_attempts=3, total=total, created_at=utcnow(),
                updated_at=utcnow()))
    except sa.exc.IntegrityError:
        jid = conn.execute(select(jobs.c.id).where(
            jobs.c.idempotency_key == idempotency_key)).scalar_one()
        return jid, False
    conn.execute(insert(job_events).values(
        job_id=jid, event="queued", detail={"kind": kind}, created_at=utcnow()))
    return jid, True


def claim_job(conn, worker_id: str, lease_minutes: int = 15) -> dict | None:
    now = utcnow()
    sel = (select(jobs.c.id).where(jobs.c.state == "queued")
           .order_by(jobs.c.priority, jobs.c.created_at).limit(1))
    if conn.engine.dialect.name == "postgresql":
        sel = sel.with_for_update(skip_locked=True)
    jid = conn.execute(sel).scalar_one_or_none()
    if not jid:
        return None
    res = conn.execute(update(jobs).where(jobs.c.id == jid, jobs.c.state == "queued")
                       .values(state="running", lease_owner=worker_id,
                               lease_expires_at=now + _minutes(lease_minutes),
                               attempts=jobs.c.attempts + 1, updated_at=now))
    if not res.rowcount:
        return None
    conn.execute(insert(job_events).values(
        job_id=jid, event="claimed", detail={"worker": worker_id}, created_at=now))
    return dict(conn.execute(select(jobs).where(jobs.c.id == jid)).mappings().one())


def update_progress(conn, job_id: str, done: int, total: int) -> None:
    conn.execute(update(jobs).where(jobs.c.id == job_id)
                 .values(progress=done, total=total, updated_at=utcnow()))


def finish_job(conn, job_id: str) -> None:
    conn.execute(update(jobs).where(jobs.c.id == job_id)
                 .values(state="succeeded", progress=jobs.c.total, updated_at=utcnow()))
    conn.execute(insert(job_events).values(
        job_id=job_id, event="succeeded", created_at=utcnow()))


def fail_job(conn, job_id: str, *, code: str, message: str, retryable: bool) -> str:
    row = conn.execute(select(jobs).where(jobs.c.id == job_id)).mappings().one()
    state = "queued" if retryable and row["attempts"] < row["max_attempts"] else "failed"
    conn.execute(update(jobs).where(jobs.c.id == job_id).values(
        state=state, error={"code": code, "message": message},
        lease_owner=None, lease_expires_at=None, updated_at=utcnow()))
    conn.execute(insert(job_events).values(
        job_id=job_id, event=state, detail={"code": code, "message": message},
        created_at=utcnow()))
    return state


def get_job(conn, job_id: str) -> dict:
    row = conn.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
    if not row:
        raise NotFound("job not found")
    return dict(row)


def requeue_stale(conn, lease_minutes: int = 15) -> int:
    cutoff = utcnow() - _minutes(lease_minutes)
    res = conn.execute(update(jobs).where(
        jobs.c.state == "running", jobs.c.lease_expires_at < cutoff)
        .values(state="queued", lease_owner=None, lease_expires_at=None, updated_at=utcnow()))
    return int(res.rowcount or 0)


# ---------------------------------------------------------------- uploads

def create_upload(conn, *, filename: str, path: str, size: int) -> str:
    return insert_upload(conn, upload_id=new_id("up"), filename=filename, path=path, size=size)


def insert_upload(conn, *, upload_id: str, filename: str, path: str, size: int) -> str:
    conn.execute(insert(uploads).values(
        id=upload_id, filename=filename, path=path, size=size, status="received",
        created_at=utcnow()))
    return upload_id


def update_upload(conn, upload_id: str, **values) -> None:
    conn.execute(update(uploads).where(uploads.c.id == upload_id).values(**values))


def queue_depth(conn) -> dict:
    rows = conn.execute(
        select(jobs.c.state, func.count()).group_by(jobs.c.state)).all()
    return {state: int(n) for state, n in rows}


# ---------------------------------------------------------------- users / sessions

def count_users(conn) -> int:
    return int(conn.execute(select(func.count()).select_from(users)).scalar_one())


def create_user(conn, *, email: str, password_hash: str, role: str = "user") -> dict:
    uid = new_id("usr")
    try:
        with conn.begin_nested():
            conn.execute(insert(users).values(
                id=uid, email=email, password_hash=password_hash, role=role,
                created_at=utcnow()))
    except sa.exc.IntegrityError:
        raise Conflict("email already registered") from None
    return get_user(conn, uid)


def get_user(conn, user_id: str) -> dict:
    row = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
    if not row:
        raise NotFound("user not found")
    return dict(row)


def get_user_by_email(conn, email: str) -> dict | None:
    row = conn.execute(select(users).where(users.c.email == email)).mappings().first()
    return dict(row) if row else None


def create_session(conn, *, user_id: str, token_hash: str, expires_at) -> str:
    sid = new_id("ses")
    conn.execute(insert(sessions).values(
        id=sid, user_id=user_id, token_hash=token_hash,
        expires_at=expires_at, created_at=utcnow()))
    return sid


def get_session_by_hash(conn, token_hash: str) -> dict | None:
    row = conn.execute(
        select(sessions).where(sessions.c.token_hash == token_hash)).mappings().first()
    return dict(row) if row else None


def rotate_session(conn, session_id: str, *, token_hash: str, expires_at) -> None:
    """Refresh-token rotation: the old digest stops matching the moment this commits."""
    conn.execute(update(sessions).where(sessions.c.id == session_id).values(
        token_hash=token_hash, expires_at=expires_at))


def revoke_session(conn, session_id: str) -> None:
    conn.execute(update(sessions)
                 .where(sessions.c.id == session_id, sessions.c.revoked_at.is_(None))
                 .values(revoked_at=utcnow()))


# ---------------------------------------------------------------- library

def add_library_entry(conn, *, user_id: str, work_id: str) -> dict:
    existing = conn.execute(
        select(library_entries).where(library_entries.c.user_id == user_id,
                                      library_entries.c.work_id == work_id)
    ).mappings().first()
    if existing:
        return dict(existing)
    lid = new_id("lib")
    try:
        with conn.begin_nested():
            conn.execute(insert(library_entries).values(
                id=lid, user_id=user_id, work_id=work_id, created_at=utcnow()))
    except sa.exc.IntegrityError:
        pass
    row = conn.execute(
        select(library_entries).where(library_entries.c.user_id == user_id,
                                      library_entries.c.work_id == work_id)
    ).mappings().one()
    return dict(row)


def remove_library_entry(conn, *, user_id: str, work_id: str) -> bool:
    res = conn.execute(sa.delete(library_entries)
                       .where(library_entries.c.user_id == user_id,
                              library_entries.c.work_id == work_id))
    return bool(res.rowcount)


def list_library(conn, user_id: str) -> list[dict]:
    rows = conn.execute(
        select(works, library_entries.c.created_at.label("added_at"))
        .join(library_entries, library_entries.c.work_id == works.c.id)
        .where(library_entries.c.user_id == user_id)
        .order_by(library_entries.c.created_at.desc())
    ).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- playback progress

def upsert_progress(conn, *, user_id: str, work_id: str, chapter_id: str,
                    position_ms: int, duration_ms: int | None) -> dict:
    row = conn.execute(
        select(playback_progress).where(playback_progress.c.user_id == user_id,
                                        playback_progress.c.chapter_id == chapter_id)
    ).mappings().first()
    if row:
        conn.execute(update(playback_progress)
                     .where(playback_progress.c.id == row["id"])
                     .values(position_ms=position_ms, duration_ms=duration_ms,
                             updated_at=utcnow()))
    else:
        pid = new_id("pg")
        try:
            with conn.begin_nested():
                conn.execute(insert(playback_progress).values(
                    id=pid, user_id=user_id, work_id=work_id, chapter_id=chapter_id,
                    position_ms=position_ms, duration_ms=duration_ms,
                    updated_at=utcnow()))
        except sa.exc.IntegrityError:
            conn.execute(update(playback_progress)
                         .where(playback_progress.c.user_id == user_id,
                                playback_progress.c.chapter_id == chapter_id)
                         .values(position_ms=position_ms, duration_ms=duration_ms,
                                 updated_at=utcnow()))
    return get_progress(conn, user_id=user_id, chapter_id=chapter_id)


def get_progress(conn, *, user_id: str, chapter_id: str) -> dict | None:
    row = conn.execute(
        select(playback_progress).where(playback_progress.c.user_id == user_id,
                                        playback_progress.c.chapter_id == chapter_id)
    ).mappings().first()
    return dict(row) if row else None


def list_work_progress(conn, *, user_id: str, work_id: str) -> list[dict]:
    """Progress rows for a book, most recently played first."""
    rows = conn.execute(
        select(playback_progress)
        .where(playback_progress.c.user_id == user_id,
               playback_progress.c.work_id == work_id)
        .order_by(playback_progress.c.updated_at.desc())
    ).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- admin: jobs

def list_jobs(conn, *, state: str | None = None, kind: str | None = None,
              limit: int = 50, offset: int = 0) -> dict:
    """Admin job queue with optional filters; newest first. ``total`` ignores paging."""
    query = select(jobs)
    if state:
        query = query.where(jobs.c.state == state)
    if kind:
        query = query.where(jobs.c.kind == kind)
    total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = conn.execute(
        query.order_by(jobs.c.created_at.desc()).limit(limit).offset(offset)
    ).mappings().all()
    return {"items": [dict(r) for r in rows], "total": int(total)}


def job_timeline(conn, job_id: str) -> list[dict]:
    rows = conn.execute(
        select(job_events).where(job_events.c.job_id == job_id)
        .order_by(job_events.c.created_at, job_events.c.id)
    ).mappings().all()
    return [dict(r) for r in rows]


def admin_retry_job(conn, job_id: str) -> dict:
    """Requeue a terminal job. Manual retries reset attempts; they do not consume max_attempts."""
    job = get_job(conn, job_id)
    if job["state"] not in {"failed", "cancelled", "dead"}:
        raise Conflict("only failed, cancelled or dead jobs can be retried")
    conn.execute(update(jobs).where(jobs.c.id == job_id).values(
        state="queued", attempts=0, error=None, progress=0,
        lease_owner=None, lease_expires_at=None, updated_at=utcnow()))
    conn.execute(insert(job_events).values(
        job_id=job_id, event="admin_retry",
        detail={"from": job["state"]}, created_at=utcnow()))
    return get_job(conn, job_id)


def admin_cancel_job(conn, job_id: str) -> dict:
    """Cancel a non-running job. Running jobs are left alone — workers cannot be interrupted."""
    job = get_job(conn, job_id)
    if job["state"] not in {"queued", "failed", "dead"}:
        raise Conflict("only queued, failed or dead jobs can be cancelled")
    conn.execute(update(jobs).where(jobs.c.id == job_id).values(
        state="cancelled", lease_owner=None, lease_expires_at=None, updated_at=utcnow()))
    conn.execute(insert(job_events).values(
        job_id=job_id, event="admin_cancel",
        detail={"from": job["state"]}, created_at=utcnow()))
    return get_job(conn, job_id)


def jobs_by_state(conn) -> dict[str, int]:
    rows = conn.execute(select(jobs.c.state, func.count()).group_by(jobs.c.state)).all()
    return {state: int(n) for state, n in rows}


# ---------------------------------------------------------------- admin: works / flags / audit

def list_all_works(conn) -> list[dict]:
    """Every work including private ones, with a chapter count — the admin catalogue."""
    chapter_count = (
        select(chapters.c.revision_id, func.count().label("n"))
        .group_by(chapters.c.revision_id).subquery()
    )
    query = (
        select(works, func.coalesce(func.max(chapter_count.c.n), 0).label("chapters"))
        .join(revisions, revisions.c.work_id == works.c.id, isouter=True)
        .join(chapter_count, chapter_count.c.revision_id == revisions.c.id, isouter=True)
        .group_by(works.c.id)
        .order_by(works.c.created_at.desc())
    )
    return [dict(r) for r in conn.execute(query).mappings().all()]


def admin_update_work(conn, work_id: str, *, shareable: bool | None = None,
                      status: str | None = None) -> dict:
    get_work(conn, work_id)  # raises NotFound before any write
    values = {}
    if shareable is not None:
        values["shareable"] = shareable
    if status is not None:
        values["status"] = status
    if values:
        conn.execute(update(works).where(works.c.id == work_id).values(**values))
    return get_work(conn, work_id)


def works_by_status(conn) -> dict[str, int]:
    rows = conn.execute(select(works.c.status, func.count()).group_by(works.c.status)).all()
    return {status: int(n) for status, n in rows}


def list_flags(conn) -> list[dict]:
    rows = conn.execute(
        select(feature_flags).order_by(feature_flags.c.key)
    ).mappings().all()
    return [dict(r) for r in rows]


def get_flag_value(conn, key: str):
    return conn.execute(
        select(feature_flags.c.value).where(feature_flags.c.key == key)
    ).scalar_one_or_none()


def set_flag(conn, *, key: str, value) -> dict:
    now = utcnow()
    existing = conn.execute(
        select(feature_flags.c.updated_at)
        .where(feature_flags.c.key == key)
    ).mappings().first()
    if existing:
        conn.execute(update(feature_flags).where(feature_flags.c.key == key).values(
            value=value, updated_at=now))
    else:
        conn.execute(insert(feature_flags).values(key=key, value=value, updated_at=now))
    return {"key": key, "value": value, "updated_at": now}


def delete_flag(conn, key: str) -> bool:
    res = conn.execute(delete(feature_flags).where(feature_flags.c.key == key))
    return int(res.rowcount or 0) > 0


def record_admin_action(conn, *, actor: str, action: str, target_type: str,
                        target_id: str, before=None, after=None,
                        reason: str | None = None) -> str:
    """Append-only trail for every admin mutation; never updated or deleted by the app."""
    audit_id = new_id("aud")
    conn.execute(insert(admin_audit).values(
        id=audit_id, actor=actor, action=action, target_type=target_type,
        target_id=target_id, before=before, after=after,
        reason=reason, created_at=utcnow()))
    return audit_id


def list_admin_actions(conn, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        select(admin_audit).order_by(admin_audit.c.created_at.desc())
        .limit(limit)
    ).mappings().all()
    return [dict(r) for r in rows]
