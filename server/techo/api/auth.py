from datetime import timedelta, timezone

from fastapi import APIRouter, Request, Response

from ..auth import check_origin
from ..clock import now
from ..schemas import Login
from .dependencies import Authenticated

router = APIRouter(tags=["authentication"])


@router.post("/login")
def login(payload: Login, request: Request, response: Response):
    settings = request.app.state.settings
    check_origin(request, settings)
    token = request.app.state.auth.login(
        payload.password, request.client.host if request.client else "unknown"
    )
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.session_days * 86400,
        expires=(now() + timedelta(days=settings.session_days)).astimezone(timezone.utc),
        path=settings.base_path + "/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return {"author": "human"}


@router.post("/logout")
def logout(request: Request, response: Response, actor: Authenticated):
    settings = request.app.state.settings
    request.app.state.auth.logout(request.cookies.get(settings.cookie_name))
    response.delete_cookie(
        settings.cookie_name, path=settings.base_path + "/", secure=True, httponly=True, samesite="lax"
    )
    return {"ok": True}


@router.get("/me")
def me(actor: Authenticated):
    return {"author": actor.name}
