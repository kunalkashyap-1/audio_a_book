"""Admin management plane — canonical v1 only, operator/admin token required.

This router never writes SQL itself: it authorises, parses input and delegates to
``services.api.services.admin``. Every mutation there records an audit row atomically.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Engine

from services.api.dependencies import (Caller, get_engine, get_provider,
                                       get_settings, require_admin)
from services.api.schemas.admin import (AdminJob, AdminJobDetail, AdminJobPage,
                                        AdminOverview, AdminWork, AdminWorkPage,
                                        FeatureFlag, FlagValue, JobAction,
                                        ProviderInfo, WorkUpdate)
from services.api.services import admin as admin_service

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin)])


# ---------------------------------------------------------------- overview

@router.get("/overview", response_model=AdminOverview)
def overview(
    engine: Engine = Depends(get_engine),
    settings=Depends(get_settings),
    provider=Depends(get_provider),
) -> dict:
    return admin_service.overview(engine, settings, provider)


# ---------------------------------------------------------------- jobs

@router.get("/jobs", response_model=AdminJobPage)
def list_jobs(
    state: str | None = None,
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    engine: Engine = Depends(get_engine),
) -> dict:
    return admin_service.list_jobs(
        engine, state=state, kind=kind, limit=limit, offset=offset)


@router.get("/jobs/{job_id}", response_model=AdminJobDetail)
def job_detail(job_id: str, engine: Engine = Depends(get_engine)) -> dict:
    return admin_service.job_detail(engine, job_id)


@router.post("/jobs/{job_id}/retry", response_model=AdminJob)
def retry_job(
    job_id: str,
    payload: JobAction | None = None,
    caller: Caller = Depends(require_admin),
    engine: Engine = Depends(get_engine),
) -> dict:
    return admin_service.retry_job(
        engine, job_id, caller, reason=payload.reason if payload else None)


@router.post("/jobs/{job_id}/cancel", response_model=AdminJob)
def cancel_job(
    job_id: str,
    payload: JobAction | None = None,
    caller: Caller = Depends(require_admin),
    engine: Engine = Depends(get_engine),
) -> dict:
    return admin_service.cancel_job(
        engine, job_id, caller, reason=payload.reason if payload else None)


# ---------------------------------------------------------------- works

@router.get("/works", response_model=AdminWorkPage)
def list_works(engine: Engine = Depends(get_engine)) -> dict:
    return admin_service.list_works(engine)


@router.patch("/works/{work_id}", response_model=AdminWork)
def update_work(
    work_id: str,
    payload: WorkUpdate,
    caller: Caller = Depends(require_admin),
    engine: Engine = Depends(get_engine),
) -> dict:
    return admin_service.update_work(
        engine, work_id, caller,
        shareable=payload.shareable, status=payload.status, reason=payload.reason)


# ---------------------------------------------------------------- flags

@router.get("/flags", response_model=list[FeatureFlag])
def list_flags(engine: Engine = Depends(get_engine)) -> list[dict]:
    return admin_service.list_flags(engine)


@router.put("/flags/{key}", response_model=FeatureFlag)
def set_flag(
    key: str,
    payload: FlagValue,
    caller: Caller = Depends(require_admin),
    engine: Engine = Depends(get_engine),
) -> dict:
    return admin_service.set_flag(
        engine, key, payload.value, caller, reason=payload.reason)


@router.delete("/flags/{key}", status_code=204)
def delete_flag(
    key: str,
    caller: Caller = Depends(require_admin),
    engine: Engine = Depends(get_engine),
    reason: str | None = None,
) -> None:
    admin_service.delete_flag(engine, key, caller, reason=reason)
    return None


# ---------------------------------------------------------------- providers (read-only)

@router.get("/providers", response_model=list[ProviderInfo])
def providers(
    settings=Depends(get_settings),
    provider=Depends(get_provider),
) -> list[dict]:
    return admin_service.provider_registry(settings, provider)
