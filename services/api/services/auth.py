"""Account use cases: register, login, refresh, logout, profile.

Cookie handling stays in the router; this layer owns validation, first-user-admin,
sessions and token issuance. Access tokens are short-lived JWTs; refresh tokens are
opaque and stored only as SHA-256 digests, rotated on every refresh.
"""

from __future__ import annotations

import re

from sqlalchemy import Engine

import aab_auth
import aab_db as db
from aab_core import InvalidInput, Settings, utcnow
from aab_auth import (
    ACCESS_TTL_MINUTES, AuthDisabled, InvalidCredentials, REFRESH_TTL_DAYS,
    create_access_token, create_refresh_token, expiry_from_now, hash_password,
    token_sha256, verify_password,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _guard(settings: Settings) -> None:
    if not settings.jwt_secret:
        raise AuthDisabled("set AAB_JWT_SECRET to enable accounts")


def _validate_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 320 or not EMAIL_RE.fullmatch(email):
        raise InvalidInput("a valid email address is required")
    return email


def _public(user: dict) -> dict:
    return {"id": user["id"], "email": user["email"], "role": user["role"],
            "created_at": user["created_at"]}


def _access(settings: Settings, user: dict) -> str:
    return create_access_token(secret=settings.jwt_secret,
                               user_id=user["id"], role=user["role"])


def _tokens(settings: Settings, conn, user: dict) -> dict:
    refresh, digest = create_refresh_token()
    db.create_session(conn, user_id=user["id"], token_hash=digest,
                      expires_at=expiry_from_now())
    return {
        "access_token": _access(settings, user),
        "token_type": "bearer",
        "expires_in": ACCESS_TTL_MINUTES * 60,
        "refresh_token": refresh,
        "user": _public(user),
    }


def register(settings: Settings, engine: Engine, *, email: str, password: str) -> dict:
    _guard(settings)
    email = _validate_email(email)
    if len(password) < 8:
        raise InvalidInput("password must be at least 8 characters")
    with engine.begin() as conn:
        first = db.count_users(conn) == 0
        user = db.create_user(conn, email=email, password_hash=hash_password(password),
                              role="admin" if first else "user")
        return _tokens(settings, conn, user)


def login(settings: Settings, engine: Engine, *, email: str, password: str) -> dict:
    _guard(settings)
    email = _validate_email(email)
    with engine.connect() as conn:
        user = db.get_user_by_email(conn, email)
    if not user or not verify_password(user["password_hash"], password):
        raise InvalidCredentials("email or password is incorrect")
    with engine.begin() as conn:
        return _tokens(settings, conn, user)


def refresh(settings: Settings, engine: Engine, *, refresh_token: str | None) -> dict:
    _guard(settings)
    if not refresh_token:
        raise InvalidCredentials("missing refresh token")
    with engine.begin() as conn:
        session = db.get_session_by_hash(conn, token_sha256(refresh_token))
        if (not session or session["revoked_at"] is not None
                or session["expires_at"] < utcnow()):
            raise InvalidCredentials("refresh token is invalid or expired")
        user = db.get_user(conn, session["user_id"])
        # Rotation: this token dies with the transaction; the response carries its successor.
        new_refresh, new_digest = create_refresh_token()
        db.rotate_session(conn, session["id"], token_hash=new_digest,
                          expires_at=expiry_from_now())
    return {
        "access_token": _access(settings, user),
        "token_type": "bearer",
        "expires_in": ACCESS_TTL_MINUTES * 60,
        "refresh_token": new_refresh,
        "user": _public(user),
    }


def logout(settings: Settings, engine: Engine, *, refresh_token: str | None) -> None:
    _guard(settings)
    if not refresh_token:
        return
    with engine.begin() as conn:
        session = db.get_session_by_hash(conn, token_sha256(refresh_token))
        if session:
            db.revoke_session(conn, session["id"])


def me(engine: Engine, user_id: str) -> dict:
    with engine.connect() as conn:
        return _public(db.get_user(conn, user_id))
