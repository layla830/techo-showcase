from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

from pydantic import Field, model_validator
from sqlalchemy import select

from ..clock import now
from ..database import Database
from ..models import Event, SeedOccurrence
from ..schemas import Input, Text
from .journal import JournalService


class SeedRule(Input):
    title: Text
    month_day: str | None = None
    day_of_month: int | None = Field(default=None, strict=True, ge=1, le=31)

    @model_validator(mode="after")
    def check_rule(self):
        if (self.month_day is None) == (self.day_of_month is None):
            raise ValueError("seed 需要且只能有 month_day 或 day_of_month")
        if self.month_day is not None:
            if not re.fullmatch(r"\d{2}-\d{2}", self.month_day):
                raise ValueError("month_day 必须为 MM-DD")
            date.fromisoformat("2000-" + self.month_day)
        return self


def seed(database: Database, path: Path, *, today: date | None = None) -> int:
    if not path.exists():
        return 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("seed.json must contain a list")
    rules = [SeedRule.model_validate(item) for item in raw]
    start = today or now().date()
    try:
        end = start.replace(year=start.year + 2)
    except ValueError:
        end = start.replace(year=start.year + 2, day=28)
    journal = JournalService(database)
    count = 0
    with database.transaction(write=True) as session:
        day = start
        while day < end:
            for rule in rules:
                if not (rule.month_day == day.strftime("%m-%d") or rule.day_of_month == day.day):
                    continue
                source = json.dumps(
                    {"title": rule.title, "date": day.isoformat()}, ensure_ascii=False, sort_keys=True
                )
                key = hashlib.sha256(source.encode()).hexdigest()
                if session.get(SeedOccurrence, key) is not None:
                    continue
                existing_id = session.scalar(
                    select(Event.id)
                    .where(Event.date == day.isoformat(), Event.title == rule.title)
                    .order_by(Event.id)
                    .limit(1)
                )
                if existing_id is None:
                    item = journal._create(
                        session,
                        "event",
                        {"date": day.isoformat(), "title": rule.title, "kind": "anniversary"},
                        "seed",
                    )
                    existing_id = item["id"]
                    count += 1
                session.add(SeedOccurrence(key=key, event_id=existing_id))
                session.flush()
            day += timedelta(days=1)
    return count
