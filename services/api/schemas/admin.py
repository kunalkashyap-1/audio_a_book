"""Pydantic IO models for the admin plane. Every admin route has a typed response."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AdminJob(BaseModel):
    id: str
    kind: str
    state: str
    target_type: str
    target_id: str
    priority: int
    attempts: int
    max_attempts: int
    progress: int
    total: int
    error: dict | None
    lease_owner: str | None
    created_at: datetime
    updated_at: datetime


class AdminJobPage(BaseModel):
    items: list[AdminJob]
    total: int
    limit: int
    offset: int


class JobEvent(BaseModel):
    event: str
    detail: dict | None
    created_at: datetime


class AdminJobDetail(BaseModel):
    job: AdminJob
    events: list[JobEvent]


class JobAction(BaseModel):
    """Optional reason recorded in the audit trail for a retry/cancel."""

    reason: str | None = Field(default=None, max_length=500)


class AdminWork(BaseModel):
    id: str
    title: str
    author: str | None
    language: str
    rights_basis: str
    shareable: bool
    owner_id: str | None
    status: str
    chapters: int
    created_at: datetime


class AdminWorkPage(BaseModel):
    items: list[AdminWork]
    total: int


class WorkUpdate(BaseModel):
    """The only work fields an operator may change. Content bytes are never editable."""

    shareable: bool | None = None
    status: str | None = Field(default=None, max_length=20)
    reason: str | None = Field(default=None, max_length=500)


class FeatureFlag(BaseModel):
    key: str
    value: Any
    updated_at: datetime


class FlagValue(BaseModel):
    value: Any
    reason: str | None = Field(default=None, max_length=500)


class ProviderInfo(BaseModel):
    id: str
    model_id: str
    model_version: str
    active: bool
    capabilities: dict
    presets: int
    note: str | None = None


class AdminAction(BaseModel):
    id: str
    actor: str
    action: str
    target_type: str
    target_id: str
    before: Any
    after: Any
    reason: str | None
    created_at: datetime


class AdminOverview(BaseModel):
    queue: dict[str, int]
    jobs_by_state: dict[str, int]
    works_by_status: dict[str, int]
    users: int
    provider: ProviderInfo
    recent_actions: list[AdminAction]
