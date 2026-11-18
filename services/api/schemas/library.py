from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ProgressUpdate(BaseModel):
    position_ms: int = 0
    duration_ms: int | None = None


class ProgressState(BaseModel):
    chapter_id: str
    position_ms: int
    duration_ms: int | None
    updated_at: datetime | None


class BookProgress(BaseModel):
    work_id: str
    chapters: list[ProgressState]
    last: ProgressState | None


class LibraryEntry(BaseModel):
    work_id: str
    added_at: datetime


class LibraryItem(BaseModel):
    """A work on the user's shelf, with the time it was added."""

    id: str
    title: str
    author: str | None
    language: str
    status: str
    rights_basis: str
    added_at: datetime


class LibraryPage(BaseModel):
    items: list[LibraryItem]
    total: int