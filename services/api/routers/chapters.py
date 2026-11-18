from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Engine

from aab_core import NotFound
from services.api.dependencies import (can_view, get_caller, get_engine, get_provider,
                                       get_settings, require_writer)
from services.api.schemas.audio import (ChapterManifest, RenderPending, RenderRequest)
from services.api.services import audio as audio_service

router = APIRouter(tags=["audio"])


@router.post("/chapters/{chapter_id}/audio", status_code=202,
             response_model=RenderRequest)
def request_audio(
    chapter_id: str,
    _: None = Depends(require_writer),
    engine: Engine = Depends(get_engine),
    provider=Depends(get_provider),
) -> dict:
    return audio_service.request_render(engine, provider, chapter_id)


@router.get("/chapters/{chapter_id}/audio", response_model=None,
            responses={200: {"model": ChapterManifest}, 202: {"model": RenderPending}})
def get_audio(
    chapter_id: str,
    request: Request,
    settings=Depends(get_settings),
    engine: Engine = Depends(get_engine),
) -> Response:
    caller = get_caller(request)
    work = audio_service.chapter_work(engine, chapter_id)
    if not can_view(work, caller):
        raise NotFound("chapter not found")
    status, payload = audio_service.render_status(settings, engine, chapter_id)
    return JSONResponse(status_code=status, content=payload)
