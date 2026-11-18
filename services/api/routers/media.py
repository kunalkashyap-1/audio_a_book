from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import Engine

from aab_core import Settings
from services.api.dependencies import can_view, get_caller, get_engine, get_settings
from services.api.services import media as media_service

router = APIRouter(tags=["media"])


@router.get("/media/{path:path}", response_model=None)
def media(path: str, request: Request,
          settings: Settings = Depends(get_settings),
          engine: Engine = Depends(get_engine)) -> Response:
    caller = get_caller(request, allow_query=True)
    target = media_service.resolve_media(settings, engine, path,
                                         admin=caller.admin,
                                         user_id=caller.user_id)
    return media_service.media_response(target, request.headers.get("range"))
