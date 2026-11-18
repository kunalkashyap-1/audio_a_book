from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import Engine

import aab_db as db
from aab_core import Settings
from services.api.dependencies import get_engine, get_provider, get_settings
from services.api.schemas.meta import Health

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=Health)
def health(
    settings: Settings = Depends(get_settings),
    engine: Engine = Depends(get_engine),
    provider=Depends(get_provider),
) -> dict:
    with engine.connect() as conn:
        queue = db.queue_depth(conn)
    return {
        "status": "ok",
        "provider": provider.model_id,
        "provider_version": provider.model_version,
        "speech": provider.id,
        "queue": queue,
        "auth_required": bool(settings.admin_token or settings.jwt_secret),
    }
