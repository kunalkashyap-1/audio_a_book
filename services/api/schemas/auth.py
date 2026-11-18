from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Credentials(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    created_at: datetime


class TokenPair(BaseModel):
    """Access token in the body; the refresh token travels only in an HttpOnly cookie."""

    access_token: str
    token_type: str
    expires_in: int
    user: UserOut