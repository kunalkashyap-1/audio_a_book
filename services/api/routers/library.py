"""Library and playback-progress routes. Signed-in users only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from services.api.dependencies import get_engine, require_user
from services.api.schemas.library import (BookProgress, LibraryEntry, LibraryPage,
                                          ProgressState, ProgressUpdate)
from services.api.services import library as library_service

router = APIRouter(tags=["library"])


@router.get("/", response_model=LibraryPage)
def list_library(request: Request, caller=Depends(require_user),
                 engine=Depends(get_engine)) -> dict:
    rows = library_service.list_library(engine, caller.user_id)
    return {"items": rows, "total": len(rows)}


@router.post("/works/{work_id}", status_code=201, response_model=LibraryEntry)
def add_to_library(request: Request, work_id: str,
                   caller=Depends(require_user),
                   engine=Depends(get_engine)):
    entry = library_service.add_to_library(engine, caller.user_id, work_id)
    return LibraryEntry(work_id=work_id, added_at=entry["created_at"])


@router.delete("/works/{work_id}", status_code=204)
def remove_from_library(request: Request, work_id: str,
                        caller=Depends(require_user),
                        engine=Depends(get_engine)):
    library_service.remove_from_library(engine, caller.user_id, work_id)
    return None


@router.put("/progress/{chapter_id}", response_model=ProgressState)
def set_progress(request: Request, chapter_id: str, payload: ProgressUpdate,
                 caller=Depends(require_user),
                 engine=Depends(get_engine)):
    return library_service.set_progress(engine, caller.user_id, chapter_id,
                                        position_ms=payload.position_ms,
                                        duration_ms=payload.duration_ms)


@router.get("/progress/{chapter_id}", response_model=ProgressState | None)
def get_progress(request: Request, chapter_id: str,
                 caller=Depends(require_user),
                 engine=Depends(get_engine)):
    return library_service.get_progress(engine, caller.user_id, chapter_id)


@router.get("/works/{work_id}/progress", response_model=BookProgress)
def book_progress(request: Request, work_id: str,
                  caller=Depends(require_user),
                  engine=Depends(get_engine)):
    return library_service.book_progress(engine, caller.user_id, work_id)
