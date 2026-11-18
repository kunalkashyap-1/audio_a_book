"""Auth routes: register, login, refresh (rotating), logout, me.

Mounted under ``/api/v1/auth``. The refresh token travels only in an
``aab_refresh`` HttpOnly cookie; access tokens are bearer JWTs sent in
``Authorization: Bearer <token>``. Routes return 403 ``auth_disabled`` when
``AAB_JWT_SECRET`` is unset.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from aab_core import Settings
from services.api.dependencies import get_caller, get_engine, get_settings, require_user
from services.api.schemas.auth import Credentials, TokenPair, UserOut
from services.api.services import auth as auth_service

router = APIRouter(tags=["auth"])


def _set_refresh_cookie(response: Response, settings: Settings, token: str) -> None:
    secure = settings.public_base_url.startswith("https")
    response.set_cookie(
        key="aab_refresh", value=token, httponly=True, samesite="lax",
        path="/api/v1/auth", secure=secure,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.set_cookie(
        key="aab_refresh", value="", httponly=True, samesite="lax",
        path="/api/v1/auth", max_age=0, expires=0,
    )


@router.post("/register", status_code=201, response_model=TokenPair)
def register(response: Response, credentials: Credentials,
             settings: Settings = Depends(get_settings),
             engine=Depends(get_engine)) -> dict:
    pair = auth_service.register(settings, engine, email=credentials.email,
                                 password=credentials.password)
    _set_refresh_cookie(response, settings, pair["refresh_token"])
    return pair


@router.post("/login", response_model=TokenPair)
def login(response: Response, credentials: Credentials,
          settings: Settings = Depends(get_settings),
          engine=Depends(get_engine)) -> dict:
    pair = auth_service.login(settings, engine, email=credentials.email,
                              password=credentials.password)
    _set_refresh_cookie(response, settings, pair["refresh_token"])
    return pair


@router.post("/refresh", response_model=TokenPair)
def refresh(response: Response, request: Request,
            settings: Settings = Depends(get_settings),
            engine=Depends(get_engine)) -> dict:
    token = request.cookies.get("aab_refresh")
    pair = auth_service.refresh(settings, engine, refresh_token=token)
    _set_refresh_cookie(response, settings, pair["refresh_token"])
    return pair


@router.post("/logout", status_code=204)
def logout(response: Response, request: Request,
           settings: Settings = Depends(get_settings),
           engine=Depends(get_engine)) -> None:
    token = request.cookies.get("aab_refresh")
    auth_service.logout(settings, engine, refresh_token=token)
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserOut)
def me(request: Request, caller=Depends(require_user),
       engine=Depends(get_engine)) -> dict:
    return auth_service.me(engine, caller.user_id)
