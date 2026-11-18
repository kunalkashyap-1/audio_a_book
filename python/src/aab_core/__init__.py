"""Core primitives: identifiers, hashing, errors, settings.

Every other package may import this one; this one imports nothing from the project.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id(prefix: str) -> str:
    """Prefixed, sortable, opaque id: ``bk_01JB8Z0C4Q7M2X9K``."""
    ms = int(time.time() * 1000)
    stamp = ""
    for _ in range(10):
        stamp = CROCKFORD[ms & 31] + stamp
        ms >>= 5
    return f"{prefix}_{stamp}{''.join(secrets.choice(CROCKFORD) for _ in range(8))}"


def utcnow() -> datetime:
    """Naive UTC, because SQLite drops tzinfo and mixing the two causes subtle bugs."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = unicodedata.normalize("NFC", data).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def normalise_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00ad", "")  # soft hyphen
    return text


class AabError(Exception):
    code = "internal_error"
    status = 500

    def __init__(self, message: str, **detail):
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotFound(AabError):
    code = "not_found"
    status = 404


class Forbidden(AabError):
    code = "forbidden"
    status = 404  # 404 on purpose: do not confirm existence


class Unauthorized(AabError):
    code = "unauthorized"
    status = 401


class InvalidInput(AabError):
    code = "invalid_input"
    status = 422


class RangeNotSatisfiable(AabError):
    code = "range_not_satisfiable"
    status = 416


class Conflict(AabError):
    code = "conflict"
    status = 409


@dataclass(frozen=True)
class Settings:
    home: Path
    database_url: str
    media_dir: Path
    models_dir: Path
    tts_provider: str = "auto"
    admin_token: str = ""
    public_base_url: str = "http://localhost:8000"
    jwt_secret: str = ""
    worker_id: str = field(default_factory=lambda: f"w_{secrets.token_hex(3)}")

    @classmethod
    def load(cls) -> "Settings":
        home = Path(os.environ.get("AAB_HOME", Path.cwd() / "var")).resolve()
        home.mkdir(parents=True, exist_ok=True)
        media = Path(os.environ.get("AAB_MEDIA_DIR", home / "media")).resolve()
        media.mkdir(parents=True, exist_ok=True)
        models = Path(os.environ.get("AAB_MODELS_DIR", home / "models")).resolve()
        db = os.environ.get("AAB_DATABASE_URL", f"sqlite:///{home / 'aab.db'}")
        return cls(
            home=home,
            database_url=db,
            media_dir=media,
            models_dir=models,
            tts_provider=os.environ.get("AAB_TTS_PROVIDER", "auto"),
            admin_token=os.environ.get("AAB_ADMIN_TOKEN", ""),
            public_base_url=os.environ.get("AAB_PUBLIC_BASE_URL", "http://localhost:8000"),
            jwt_secret=os.environ.get("AAB_JWT_SECRET", ""),
        )

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")
