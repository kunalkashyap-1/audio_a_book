from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import Engine

from aab_core import NotFound, Settings
from services.api.dependencies import (Caller, can_view, get_caller, get_engine,
                                       get_provider, get_settings, require_writer)
from services.api.schemas.audio import GenerateResult
from services.api.schemas.books import (BookDetail, BookPage, BookSummary, UploadResult)
from services.api.services import audio as audio_service
from services.api.services import books as books_service

router = APIRouter(tags=["books"])

# The paginated catalogue is the v1 shape; the legacy alias keeps the bare list.
list_v1 = APIRouter(tags=["books"])
list_legacy = APIRouter(tags=["books"])


def _catalogue_shareable(caller: Caller) -> tuple[bool, str | None]:
    """Open instance / operator token → everything. Signed-in user → shareable + own works.
    Anonymous → shareable only."""
    if caller.admin:
        return False, None
    if caller.authenticated:
        return True, caller.user_id
    return True, None


@list_v1.get("/books", response_model=BookPage)
def list_books_v1(request: Request,
                  limit: int = Query(100, ge=1, le=500),
                  offset: int = Query(0, ge=0),
                  engine: Engine = Depends(get_engine)) -> dict:
    caller = get_caller(request)
    shareable_only, owner_id = _catalogue_shareable(caller)
    page = books_service.list_books(engine, shareable_only=shareable_only,
                                    owner_id=owner_id, limit=limit, offset=offset)
    return page


@list_legacy.get("/books", response_model=list[BookSummary])
def list_books_legacy(request: Request, engine: Engine = Depends(get_engine)) -> list[dict]:
    caller = get_caller(request)
    shareable_only, owner_id = _catalogue_shareable(caller)
    page = books_service.list_books(engine, shareable_only=shareable_only,
                                    owner_id=owner_id)
    return page["items"]


@router.get("/books/{book_id}", response_model=BookDetail)
def get_book(book_id: str, request: Request,
             engine: Engine = Depends(get_engine)) -> dict:
    caller = get_caller(request)
    detail = books_service.book_detail(engine, book_id)
    if not can_view(detail["work"], caller):
        raise NotFound("book not found")
    work = detail["work"]
    return {
        "work": {
            "id": work["id"], "title": work["title"], "author": work["author"],
            "language": work["language"], "status": work["status"],
            "rights_basis": work["rights_basis"],
        },
        "chapters": detail["chapters"],
        "cast": detail["cast"],
    }


@router.post("/books/{book_id}/generate", status_code=202,
             response_model=GenerateResult)
def generate_book(
    book_id: str,
    _: None = Depends(require_writer),
    engine: Engine = Depends(get_engine),
    provider=Depends(get_provider),
) -> dict:
    """Queue a render for every chapter of the book. Idempotent per chapter."""
    return audio_service.generate_book(engine, provider, book_id)


@router.post("/books", status_code=201, response_model=UploadResult)
async def create_book(
    file: UploadFile = File(...),
    title: str = Form(""),
    author: str = Form(""),
    language: str = Form("en"),
    rights_basis: str = Form("public_domain_us"),
    caller: Caller = Depends(require_writer),
    settings: Settings = Depends(get_settings),
    engine: Engine = Depends(get_engine),
) -> dict:
    content = await file.read(books_service.MAX_UPLOAD + 1)
    return books_service.create_upload(
        settings, engine,
        filename=file.filename or "book.txt",
        content=content,
        title=title,
        author=author,
        language=language,
        rights_basis=rights_basis,
        owner_id=caller.user_id if caller.authenticated else None,
    )
