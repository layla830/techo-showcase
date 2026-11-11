from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_ZONE = ZoneInfo("Asia/Shanghai")
_zone = DEFAULT_ZONE


def configure(zone: ZoneInfo) -> None:
    global _zone
    _zone = zone


def current_zone() -> ZoneInfo:
    return _zone


def now() -> datetime:
    return datetime.now(_zone)


def stamp(value: datetime | None = None) -> str:
    return (value or now()).astimezone(_zone).isoformat(timespec="microseconds")


def parse_stamp(value: str) -> datetime:
    return datetime.fromisoformat(value)
