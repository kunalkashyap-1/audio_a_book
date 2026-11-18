"""Application factory. ``services.api.main:app`` is the uvicorn entrypoint.

The factory takes ``Settings`` explicitly so tests can build isolated instances; nothing
reads ambient configuration outside ``Settings.load()``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

import aab_db as db
from aab_core import Settings
from aab_providers import build_provider
from services.api.errors import install_error_handlers
from services.api.routers import (admin, auth, books, chapters, jobs, library,
                                  media, meta, web)

REPO_ROOT = Path(__file__).resolve().parents[2]

API_PREFIXES = ("/api/v1", "/api")   # v1 is canonical; /api stays as a stable alias.


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    engine = db.make_engine(settings.database_url)
    db.init_db(engine)
    provider = build_provider(settings)

    app = FastAPI(
        title="Open Audio Book",
        version="0.2.0",
        description="Turns books into multi-character audiobooks, with a shared render cache.",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.provider = provider
    app.state.web_index = REPO_ROOT / "apps" / "web" / "index.html"

    install_error_handlers(app)

    shared = [meta.router, books.router, chapters.router, jobs.router]
    for router in shared:
        app.include_router(router, prefix="/api/v1")
        app.include_router(router, prefix="/api")
    # Auth and library are Phase B (account-scoped): canonical v1 only.
    app.include_router(auth.router, prefix="/api/v1/auth")
    app.include_router(library.router, prefix="/api/v1/library")
    # Admin is Phase D: canonical v1 only, every route gated by require_admin.
    app.include_router(admin.router, prefix="/api/v1/admin")
    # The catalogue has two shapes: paginated on v1, the original bare list on the alias.
    app.include_router(books.list_v1, prefix="/api/v1")
    app.include_router(books.list_legacy, prefix="/api")

    app.include_router(media.router)   # /media is unversioned: URLs live in manifests.
    app.include_router(web.router)     # static player until the Next.js app takes over
    return app
