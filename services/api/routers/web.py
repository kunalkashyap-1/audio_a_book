from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from services.api.dependencies import get_web_index

router = APIRouter(tags=["web"], include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def index(web_index: Path = Depends(get_web_index)) -> str:
    if web_index.exists():
        return web_index.read_text()
    return "<h1>Open Audio Book</h1><p>Player not installed.</p>"
