from __future__ import annotations

import calendar
from datetime import date

from ..clock import stamp
from ..database import Database
from ..errors import APIError
from ..models import serialize
from ..repositories import Changes, Resources
from ..schemas import aware_timestamp, date_string, month_string
from .pages import PageService


def week_of(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year:04d}-W{week:02d}"


class CalendarService:
    def __init__(self, database: Database):
        self.database = database

    def _read(
        self, start: date, end: date, ym: str, weeks: list[str], pages: list[str] | None = None
    ) -> dict:
        with self.database.transaction() as session:
            resources = Resources(session)
            weekly = {week: [] for week in weeks}
            for row in resources.goals("week", weeks):
                weekly[row.period].append(serialize("goal", row))
            result = {
                "ym": ym,
                "notes": resources.dated("note", start.isoformat(), end.isoformat()),
                "media": resources.dated("media", start.isoformat(), end.isoformat()),
                "events": resources.dated("event", start.isoformat(), end.isoformat()),
                "goals": {
                    "month": [serialize("goal", row) for row in resources.goals("month", [ym])],
                    "weeks": weekly,
                },
                "photos": resources.dated("photo", start.isoformat(), end.isoformat()),
            }
            if pages is not None:
                result["decorated_pages"] = PageService.decorated_pages(session, pages)
            return result

    def month(self, ym: str) -> dict:
        try:
            month_string(ym)
        except ValueError as exc:
            raise APIError(400, "validation_error", "ym 必须为有效的 YYYY-MM 月份", field="ym") from exc
        first = date.fromisoformat(ym + "-01")
        days = calendar.monthrange(first.year, first.month)[1]
        last = first.replace(day=days)
        weeks = list(dict.fromkeys(week_of(first.replace(day=day)) for day in range(1, days + 1)))
        pages = [f"day:{first.replace(day=day).isoformat()}" for day in range(1, days + 1)]
        return self._read(first, last, ym, weeks, [*pages, f"month:{ym}"])

    def day(self, value: str) -> dict:
        try:
            parsed = date.fromisoformat(date_string(value))
        except ValueError as exc:
            raise APIError(
                400, "validation_error", "date 必须为有效的 YYYY-MM-DD 日期", field="date"
            ) from exc
        result = self._read(parsed, parsed, value[:7], [week_of(parsed)])
        return {"date": value, **result}

    def changes(self, actor: str, since: str, limit: int) -> dict:
        try:
            timestamp = stamp(aware_timestamp(since))
        except (ValueError, OverflowError) as exc:
            raise APIError(
                400, "validation_error", "since 必须为带时区的 ISO8601 时间", field="since"
            ) from exc
        with self.database.transaction() as session:
            return Changes(session).since(actor, timestamp, limit)
