from typing import Annotated

from fastapi import Depends, Header, Request

from ..auth import Actor
from ..errors import APIError
from ..schemas import timestamp_string
from ..services.calendar import CalendarService
from ..services.journal import JournalService
from ..services.pages import PageService
from ..services.photos import PhotoService


def current_actor(request: Request) -> Actor:
    return request.app.state.auth.authenticate(request)


def journal_service(request: Request) -> JournalService:
    return request.app.state.journal


def calendar_service(request: Request) -> CalendarService:
    return request.app.state.calendar


def photo_service(request: Request) -> PhotoService:
    return request.app.state.photos


def page_service(request: Request) -> PageService:
    return request.app.state.pages


def expected_version(if_match: Annotated[str, Header(alias="If-Match")]) -> str:
    value = if_match.strip()
    if len(value) < 2 or not value.startswith('"') or not value.endswith('"'):
        raise APIError(400, "validation_error", "If-Match 必须为当前版本的强 ETag", field="If-Match")
    try:
        return timestamp_string(value[1:-1])
    except ValueError as exc:
        raise APIError(400, "validation_error", "If-Match 必须为当前版本的强 ETag", field="If-Match") from exc


ExpectedVersion = Annotated[str, Depends(expected_version)]
Authenticated = Annotated[Actor, Depends(current_actor)]
Journal = Annotated[JournalService, Depends(journal_service)]
Calendar = Annotated[CalendarService, Depends(calendar_service)]
Photos = Annotated[PhotoService, Depends(photo_service)]
Pages = Annotated[PageService, Depends(page_service)]
