"""Admin use cases: queue operations, catalogue controls, feature flags and provider registry.

Routers authorise and delegate here; all persistence goes through ``aab_db``. Every mutation
appends an ``admin_audit`` row in the same transaction as the change, so a failure never leaves
an untracked action behind.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine

import aab_db as db
from aab_core import NotFound, Settings
from services.api.dependencies import Caller


def actor_of(caller: Caller) -> str:
    return f"user:{caller.user_id}" if caller.user_id else "operator"


def _job(row: dict) -> dict:
    return {
        "id": row["id"], "kind": row["kind"], "state": row["state"],
        "target_type": row["target_type"], "target_id": row["target_id"],
        "priority": row["priority"], "attempts": row["attempts"],
        "max_attempts": row["max_attempts"], "progress": row["progress"],
        "total": row["total"], "error": row["error"],
        "lease_owner": row["lease_owner"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _work(row: dict) -> dict:
    return {
        "id": row["id"], "title": row["title"], "author": row["author"],
        "language": row["language"], "rights_basis": row["rights_basis"],
        "shareable": bool(row["shareable"]), "owner_id": row["owner_id"],
        "status": row["status"], "chapters": int(row["chapters"]),
        "created_at": row["created_at"],
    }


def _action(row: dict) -> dict:
    return {
        "id": row["id"], "actor": row["actor"], "action": row["action"],
        "target_type": row["target_type"], "target_id": row["target_id"],
        "before": row["before"], "after": row["after"], "reason": row["reason"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------- provider registry (read-only)

def _provider_info(source: Any, *, active: bool, note: str | None) -> dict:
    if isinstance(source, type):
        capabilities = {
            "kind": "tts",
            "languages": ["en"],
            "max_chars_per_line": source.max_chars_per_line,
            "sample_rates": [source.sample_rate],
            "weights_sha256": getattr(source, "weights_sha256", "unknown"),
        }
    else:
        capabilities = source.capabilities()
    return {
        "id": source.id,
        "model_id": source.model_id,
        "model_version": source.model_version,
        "active": active,
        "capabilities": capabilities,
        "presets": len(source.presets),
        "note": note,
    }


def provider_registry(settings: Settings, active_provider: Any) -> list[dict]:
    """The two implemented local providers. No cloud provider is wired in at launch."""
    from aab_providers.fake import FakeProvider
    from aab_providers.kokoro import KokoroProvider

    weights = list(settings.models_dir.glob("kokoro-v1.0*.onnx"))
    info = [
        _provider_info(active_provider, active=True, note="selected by AAB_TTS_PROVIDER"),
    ]
    if active_provider.model_id != FakeProvider.model_id:
        info.append(_provider_info(FakeProvider, active=False,
                                   note="deterministic fallback, always available"))
    if active_provider.model_id != KokoroProvider.model_id:
        note = ("weights present" if weights else
                "weights missing — run scripts/setup_tts.sh")
        info.append(_provider_info(KokoroProvider, active=False, note=note))
    return info


# ---------------------------------------------------------------- overview

def overview(engine: Engine, settings: Settings, provider: Any) -> dict:
    with engine.connect() as conn:
        queue = db.queue_depth(conn)
        jobs = db.jobs_by_state(conn)
        works = db.works_by_status(conn)
        users = db.count_users(conn)
        actions = db.list_admin_actions(conn, limit=10)
    return {
        "queue": {key: int(value) for key, value in queue.items()},
        "jobs_by_state": jobs,
        "works_by_status": works,
        "users": users,
        "provider": provider_registry(settings, provider)[0],
        "recent_actions": [_action(row) for row in actions],
    }


# ---------------------------------------------------------------- jobs

def list_jobs(engine: Engine, *, state: str | None, kind: str | None,
              limit: int, offset: int) -> dict:
    with engine.connect() as conn:
        page = db.list_jobs(conn, state=state, kind=kind, limit=limit, offset=offset)
    return {
        "items": [_job(row) for row in page["items"]],
        "total": page["total"], "limit": limit, "offset": offset,
    }


def job_detail(engine: Engine, job_id: str) -> dict:
    with engine.connect() as conn:
        job = db.get_job(conn, job_id)
        events = db.job_timeline(conn, job_id)
    return {"job": _job(job), "events": events}


def retry_job(engine: Engine, job_id: str, caller: Caller,
              reason: str | None = None) -> dict:
    with engine.begin() as conn:
        before = db.get_job(conn, job_id)["state"]
        job = db.admin_retry_job(conn, job_id)
        db.record_admin_action(
            conn, actor=actor_of(caller), action="job.retry",
            target_type="job", target_id=job_id,
            before={"state": before}, after={"state": job["state"]}, reason=reason,
        )
    return _job(job)


def cancel_job(engine: Engine, job_id: str, caller: Caller,
               reason: str | None = None) -> dict:
    with engine.begin() as conn:
        before = db.get_job(conn, job_id)["state"]
        job = db.admin_cancel_job(conn, job_id)
        db.record_admin_action(
            conn, actor=actor_of(caller), action="job.cancel",
            target_type="job", target_id=job_id,
            before={"state": before}, after={"state": job["state"]}, reason=reason,
        )
    return _job(job)


# ---------------------------------------------------------------- works

def list_works(engine: Engine) -> dict:
    with engine.connect() as conn:
        rows = db.list_all_works(conn)
    return {"items": [_work(row) for row in rows], "total": len(rows)}


def update_work(engine: Engine, work_id: str, caller: Caller, *,
                shareable: bool | None, status: str | None,
                reason: str | None = None) -> dict:
    with engine.begin() as conn:
        before = db.get_work(conn, work_id)
        work = db.admin_update_work(
            conn, work_id, shareable=shareable, status=status)
        db.record_admin_action(
            conn, actor=actor_of(caller), action="work.update",
            target_type="work", target_id=work_id,
            before={"shareable": bool(before["shareable"]), "status": before["status"]},
            after={"shareable": bool(work["shareable"]), "status": work["status"]},
            reason=reason,
        )
    # list_all_works adds the chapter count; fetch it for the typed response.
    with engine.connect() as conn:
        row = next((row for row in db.list_all_works(conn) if row["id"] == work_id), None)
    if row is None:  # pragma: no cover - the update above guarantees the row exists
        raise NotFound("work not found")
    return _work(row)


# ---------------------------------------------------------------- feature flags

def list_flags(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        return db.list_flags(conn)


def set_flag(engine: Engine, key: str, value: Any, caller: Caller,
             reason: str | None = None) -> dict:
    with engine.begin() as conn:
        previous = db.get_flag_value(conn, key)
        flag = db.set_flag(conn, key=key, value=value)
        db.record_admin_action(
            conn, actor=actor_of(caller), action="flag.set",
            target_type="flag", target_id=key,
            before={"value": previous}, after={"value": value}, reason=reason,
        )
    return flag


def delete_flag(engine: Engine, key: str, caller: Caller,
                reason: str | None = None) -> None:
    with engine.begin() as conn:
        if not db.delete_flag(conn, key):
            raise NotFound("feature flag not found")
        db.record_admin_action(
            conn, actor=actor_of(caller), action="flag.delete",
            target_type="flag", target_id=key, reason=reason,
        )


# ---------------------------------------------------------------- audit

def recent_actions(engine: Engine, limit: int = 20) -> list[dict]:
    with engine.connect() as conn:
        return [_action(row) for row in db.list_admin_actions(conn, limit=limit)]
