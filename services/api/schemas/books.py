from __future__ import annotations

from pydantic import BaseModel


class BookSummary(BaseModel):
    id: str
    title: str
    author: str | None
    language: str
    status: str
    chapters: int


class BookPage(BaseModel):
    """Paginated catalogue. Anonymous callers see shareable works only."""

    items: list[BookSummary]
    total: int
    limit: int
    offset: int


class WorkInfo(BaseModel):
    id: str
    title: str
    author: str | None
    language: str
    status: str
    rights_basis: str


class ChapterState(BaseModel):
    id: str
    ordinal: int
    title: str
    word_count: int
    status: str
    progress: int
    total: int


class CastMember(BaseModel):
    character_id: str | None
    name: str
    voice: str | None
    profile_id: str


class BookDetail(BaseModel):
    work: WorkInfo
    chapters: list[ChapterState]
    cast: list[CastMember]


class UploadResult(BaseModel):
    book_id: str
    revision_id: str
    job_id: str
