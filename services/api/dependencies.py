"""FastAPI dependencies: app state access, caller resolution and the authorisation gates.

Three credentials can identify a caller: the operator token (``AAB_ADMIN_TOKEN``), an
access JWT (``AAB_JWT_SECRET`` must be set), or neither — anonymous. An instance with
neither secret configured is the operator's own machine: everything is visible, which is
what keeps the single-operator workflow unchanged.
"""

from __future__ import annotations

import dataclasses
import hmac
from pathlib import Path

from fastapi import Request
from sqlalchemy import Engine

import aab_auth
from aab_core import Settings, Unauthorized


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


def get_provider(request: Request):
    return request.app.state.provider


def get_web_index(request: Request) -> Path:
    return request.app.state.web_index


@dataclasses.dataclass(frozen=True)
class Caller:
    """Who is asking. ``admin_token`` covers the operator token and open instances."""

    user_id: str | None = None
    role: str | None = None
    admin_token: bool = False

    @property
    def admin(self) -> bool:
        return self.admin_token or self.role == "admin"

    @property
    def authenticated(self) -> bool:
        return bool(self.user_id)


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:] if header.lower().startswith("bearer ") else ""


def get_caller(request: Request, *, allow_query: bool = False) -> Caller:
    """Resolve the caller.

    ``allow_query`` accepts ``?token=`` — needed for ``<audio>`` sources, which cannot send
    custom headers, and honoured only on media routes. A supplied credential that fails to
    verify raises (401) rather than silently degrading to anonymous.
    """
    settings: Settings = get_settings(request)
    supplied = request.headers.get("x-admin-token", "") or _bearer_token(request)
    if allow_query and not supplied:
        supplied = request.query_params.get("token", "")

    if not settings.admin_token and not settings.jwt_secret:
        return Caller(admin_token=True)          # single-operator instance: everything visible
    if settings.admin_token and supplied and \
            hmac.compare_digest(settings.admin_token, supplied):
        return Caller(admin_token=True)
    if settings.jwt_secret and supplied:
        claims = aab_auth.decode_access_token(settings.jwt_secret, supplied)
        return Caller(user_id=claims["sub"], role=claims.get("role", "user"))
    return Caller()


def is_admin(request: Request, *, allow_query: bool = False) -> bool:
    return get_caller(request, allow_query=allow_query).admin


def require_admin(request: Request) -> Caller:
    """Admin-only gate. Returns the caller so audit rows can record who acted."""
    caller = get_caller(request)
    if not caller.admin:
        raise Unauthorized("admin token required")
    return caller


def require_writer(request: Request) -> Caller:
    """Publishing gate: operator token, admin user, or any signed-in user (upload/generate)."""
    caller = get_caller(request)
    if caller.admin or caller.authenticated:
        return caller
    raise Unauthorized("admin token or account required")


def require_user(request: Request) -> Caller:
    """Per-user data gate (library, progress, profile): a real account, not a token."""
    caller = get_caller(request)
    if not caller.authenticated:
        raise Unauthorized("login required")
    return caller


def can_view(work: dict, caller: Caller) -> bool:
    """Shareable works are public; private works belong to their owner or the operator."""
    if work["shareable"] or caller.admin:
        return True
    return bool(caller.user_id) and work.get("owner_id") == caller.user_id
