"""APIRouter aggregates. Routers parse, authorise and delegate; they never write SQL."""

from __future__ import annotations

from . import admin, auth, books, chapters, jobs, library, media, meta, web

__all__ = ["admin", "auth", "books", "chapters", "jobs", "library", "media", "meta", "web"]
