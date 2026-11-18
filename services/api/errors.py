from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from aab_core import AabError


def install_error_handlers(app: FastAPI) -> None:
    """One error envelope for every failure: ``{"code", "message", ...detail}``."""

    @app.exception_handler(AabError)
    async def _aab_error(_request: Request, exc: AabError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"code": exc.code, "message": exc.message, **exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "request failed validation",
                "detail": jsonable_encoder(exc.errors()),
            },
        )
