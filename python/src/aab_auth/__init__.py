"""Passwords, tokens and session secrets.

Pure crypto/token logic: no SQL, no HTTP. ``aab_db`` owns the session rows; the API wires
both together. Passwords use argon2id; access tokens are short-lived JWTs (HS256); refresh
tokens are opaque secrets stored only as SHA-256 digests.
"""

from __future__ import annotations

import calendar
import hashlib
import secrets
import datetime as dt

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError

from aab_core import AabError

_hasher = PasswordHasher()          # argon2id with library defaults

ACCESS_TTL_MINUTES = 30
REFRESH_TTL_DAYS = 30


class InvalidCredentials(AabError):
    code = "invalid_credentials"
    status = 401


class AuthDisabled(AabError):
    code = "auth_disabled"
    status = 403


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ---------------------------------------------------------------- access tokens

def create_access_token(*, secret: str, user_id: str, role: str,
                        ttl_minutes: int = ACCESS_TTL_MINUTES) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + dt.timedelta(minutes=ttl_minutes),
        "typ": "access",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(secret: str, token: str) -> dict:
    """Returns the claims or raises ``InvalidCredentials``. ``exp`` is verified."""
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise InvalidCredentials(f"invalid token: {exc.__class__.__name__}") from None
    if claims.get("typ") != "access" or not claims.get("sub"):
        raise InvalidCredentials("invalid token")
    return claims


# ---------------------------------------------------------------- refresh tokens

def create_refresh_token() -> tuple[str, str]:
    """Returns ``(token, token_sha256)``. Only the digest is ever stored."""
    token = secrets.token_urlsafe(48)
    return token, token_sha256(token)


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def expiry_from_now(days: int = REFRESH_TTL_DAYS) -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(days=days)


def epoch_ms(when: dt.datetime) -> int:
    return calendar.timegm(when.timetuple()) * 1000
