from typing import Annotated

from fastapi import APIRouter, Query

from .dependencies import Authenticated, Calendar

router = APIRouter(tags=["calendar"])


@router.get("/month")
def month(ym: str, actor: Authenticated, calendar: Calendar):
    return calendar.month(ym)


@router.get("/day")
def day(date: str, actor: Authenticated, calendar: Calendar):
    return calendar.day(date)


@router.get("/changes")
def changes(
    since: str, actor: Authenticated, calendar: Calendar, limit: Annotated[int, Query(ge=1, le=1000)] = 500
):
    return calendar.changes(actor.name, since, limit)
