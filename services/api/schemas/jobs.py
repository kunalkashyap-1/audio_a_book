from __future__ import annotations

from pydantic import BaseModel


class JobStatus(BaseModel):
    id: str
    kind: str
    state: str
    progress: int
    total: int
    error: dict | None
