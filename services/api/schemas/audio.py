from __future__ import annotations

from pydantic import BaseModel


class RenderRequest(BaseModel):
    """Response to ``POST /chapters/{id}/audio``: 202 body, or the live render state."""

    job_id: str | None
    status: str
    progress: int | None = None
    total: int | None = None


class RenderPending(BaseModel):
    """Response to ``GET /chapters/{id}/audio`` while there is no manifest yet."""

    status: str
    progress: int = 0
    total: int = 0
    job_id: str | None = None


class GenerateResult(BaseModel):
    """Response to ``POST /books/{id}/generate``: how many chapters were targeted."""

    chapters: int
    jobs_created: int


class ManifestSegment(BaseModel):
    """One synthesised segment as stored in the chapter's manifest.json."""

    ordinal: int
    segment_id: str
    render_key: str
    kind: str
    speaker: str
    text: str
    duration_ms: int


class ChapterManifest(BaseModel):
    """The 200 response to ``GET /chapters/{id}/audio`` — the player's data source."""

    chapter_id: str
    chapter_title: str | None
    chapter_ordinal: int
    work_id: str
    render_set_id: str
    policy_version: str
    model_family: str
    duration_ms: int
    complete: bool
    segment_count: int
    rendered_count: int
    master_url: str | None
    segments: list[ManifestSegment]
