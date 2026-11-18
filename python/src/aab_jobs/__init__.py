"""Job policy: claim, lease, retry, dispatch. Storage lives in ``aab_db``."""

from __future__ import annotations

import logging
import time
from typing import Callable

import sqlalchemy as sa

from aab_core import AabError, Settings, utcnow
from aab_db import claim_job, fail_job, finish_job, get_job, requeue_stale
from aab_providers import ProviderError

log = logging.getLogger("aab.jobs")

Handler = Callable[[sa.Engine, dict, Settings], None]


def run_once(engine: sa.Engine, worker_id: str, handlers: dict[str, Handler],
             settings: Settings) -> bool:
    """Claim and execute one job. Returns False when the queue is empty."""
    with engine.begin() as conn:
        requeue_stale(conn)
        job = claim_job(conn, worker_id)
    if job is None:
        return False

    handler = handlers.get(job["kind"])
    if handler is None:
        with engine.begin() as conn:
            fail_job(conn, job["id"], code="unknown_kind",
                     message=f"no handler for {job['kind']}", retryable=False)
        return True

    started = time.monotonic()
    log.info("start  %s %s", job["kind"], job["id"])
    try:
        handler(engine, job, settings)
    except (AabError, ProviderError) as exc:
        code = getattr(exc, "code", "unknown")
        retryable = getattr(exc, "retryable", False)
        with engine.begin() as conn:
            state = fail_job(conn, job["id"], code=code, message=str(exc),
                             retryable=retryable)
        log.warning("fail   %s %s [%s] -> %s: %s", job["kind"], job["id"], code, state, exc)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("crash  %s %s", job["kind"], job["id"])
        with engine.begin() as conn:
            fail_job(conn, job["id"], code="internal_error",
                     message=f"{type(exc).__name__}: {exc}", retryable=True)
    else:
        with engine.begin() as conn:
            finish_job(conn, job["id"])
        log.info("done   %s %s in %.1fs", job["kind"], job["id"],
                 time.monotonic() - started)
    return True


def drain(engine: sa.Engine, worker_id: str, handlers: dict[str, Handler],
          settings: Settings) -> int:
    """Run until the queue is empty. Used by tests and the ``--once`` CLI mode."""
    count = 0
    while run_once(engine, worker_id, handlers, settings):
        count += 1
        if count > 10_000:
            raise RuntimeError("drain loop did not terminate")
    return count


def job_status(engine: sa.Engine, job_id: str) -> dict:
    with engine.connect() as conn:
        job = get_job(conn, job_id)
    return {
        "id": job["id"],
        "kind": job["kind"],
        "state": job["state"],
        "progress": job["progress"],
        "total": job["total"],
        "error": job["error"],
        "updated_at": job["updated_at"].isoformat() + "Z",
        "age_s": int((utcnow() - job["created_at"]).total_seconds()),
    }
