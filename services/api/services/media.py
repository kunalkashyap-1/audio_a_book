"""Media resolution and byte serving: path traversal guard, privacy predicate, ranges."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi.responses import FileResponse, Response
from sqlalchemy import Engine

import aab_db as db
from aab_core import AabError, NotFound, RangeNotSatisfiable, Settings

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def resolve_media(settings: Settings, engine: Engine, path: str, *,
                  admin: bool = False, user_id: str | None = None) -> Path:
    """Resolve a media path to a file, enforcing traversal and visibility rules.

    Anonymous callers may read only audio belonging to a shareable work. Everything else —
    uploads and raw cached segments — is operator-only, because a segment can contain the
    text of a private upload.
    """
    root = settings.media_dir.resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise NotFound("not found")

    if not admin:
        parts = Path(path).parts
        if len(parts) < 2 or parts[0] != "books":
            raise NotFound("not found")
        with engine.connect() as conn:
            try:
                work = db.get_work(conn, parts[1])
            except AabError:
                raise NotFound("not found") from None
        if not admin and not work["shareable"] and \
                not (user_id and work.get("owner_id") == user_id):
            raise NotFound("not found")
    return target


def media_response(target: Path, range_header: str | None) -> Response:
    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    size = target.stat().st_size
    if not range_header:
        return FileResponse(target, media_type=mime,
                            headers={"Accept-Ranges": "bytes"})

    match = RANGE_RE.fullmatch(range_header.strip())
    if not match:
        raise RangeNotSatisfiable("invalid range")
    start = int(match.group(1) or 0)
    end = int(match.group(2)) if match.group(2) else size - 1
    end = min(end, size - 1)
    if start > end:
        raise RangeNotSatisfiable("range not satisfiable")

    with target.open("rb") as handle:
        handle.seek(start)
        chunk = handle.read(end - start + 1)
    return Response(
        chunk, status_code=206, media_type=mime,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(chunk)),
        },
    )
