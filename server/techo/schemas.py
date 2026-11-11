from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .clock import stamp


def date_string(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date 格式应为 YYYY-MM-DD")
    date.fromisoformat(value)
    return value


def month_string(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValueError("月份格式应为 YYYY-MM")
    date.fromisoformat(value + "-01")
    return value


def period_scope(value: str) -> str:
    if re.fullmatch(r"\d{4}-W\d{2}", value):
        year, week = value.split("-W")
        date.fromisocalendar(int(year), int(week), 1)
        return "week"
    month_string(value)
    return "month"


def time_string(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("time 格式应为 HH:MM")
    return value


def aware_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("since 必须为带时区的 ISO8601 时间")
    return parsed


def timestamp_string(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("版本必须为带时区的 ISO8601 时间")
    try:
        return stamp(aware_timestamp(value))
    except (ValueError, OverflowError) as exc:
        raise ValueError("版本必须为带时区的 ISO8601 时间") from exc


def page_string(value: Any) -> str:
    if isinstance(value, str):
        if re.fullmatch(r"day:\d{4}-\d{2}-\d{2}", value):
            try:
                date.fromisoformat(value[4:])
                return value
            except ValueError:
                pass
        elif re.fullmatch(r"month:\d{4}-\d{2}", value):
            try:
                month_string(value[6:])
                return value
            except ValueError:
                pass
    raise ValueError("page 应为 day:YYYY-MM-DD 或 month:YYYY-MM")


def optional_caption(value: Any) -> Any:
    # Captions trim to null when empty; length is checked after trimming.
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


TimestampString = Annotated[str, BeforeValidator(timestamp_string)]
SourceKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
DateString = Annotated[str, BeforeValidator(date_string)]
TimeString = Annotated[str, BeforeValidator(time_string)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NoteText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
MediaKind = Literal["book", "film", "series", "show", "other"]
EventKind = Literal["plan", "anniversary"]
GoalScope = Literal["week", "month"]
GoalStatus = Literal["open", "done", "dropped"]


Caption = Annotated[
    Annotated[str, StringConstraints(max_length=200)] | None, BeforeValidator(optional_caption)
]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


def finite(low: float, high: float):
    return Annotated[float, Field(strict=True, ge=low, le=high, allow_inf_nan=False)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoteCreate(Input):
    date: DateString
    text: NoteText
    mood: str | None = None


class NotePatch(Input):
    date: DateString | None = None
    text: NoteText | None = None
    mood: str | None = None


class MediaCreate(Input):
    date: DateString
    kind: MediaKind
    title: Text
    note: str | None = None


class MediaPatch(Input):
    date: DateString | None = None
    kind: MediaKind | None = None
    title: Text | None = None
    note: str | None = None


class EventCreate(Input):
    date: DateString
    time: TimeString | None = None
    title: Text
    kind: EventKind = "plan"
    place: str | None = None


class EventPatch(Input):
    date: DateString | None = None
    time: TimeString | None = None
    title: Text | None = None
    kind: EventKind | None = None
    place: str | None = None


class GoalCreate(Input):
    scope: GoalScope
    period: str
    text: Text
    status: GoalStatus = "open"
    sort: Annotated[int, Field(strict=True, ge=0)] | None = None

    @field_validator("sort")
    @classmethod
    def check_sort(cls, value):
        if value is None:
            raise ValueError("sort 不能为 null；省略时自动追加")
        return value

    @model_validator(mode="after")
    def check_period(self):
        if period_scope(self.period) != self.scope:
            raise ValueError("scope 和 period 不匹配")
        return self


class GoalPatch(Input):
    scope: GoalScope | None = None
    period: str | None = None
    text: Text | None = None
    status: GoalStatus | None = None
    sort: Annotated[int, Field(strict=True, ge=0)] | None = None


class Reorder(Input):
    period: str
    ids: list[Annotated[int, Field(strict=True, gt=0)]]
    versions: dict[Annotated[int, Field(gt=0)], TimestampString]

    @field_validator("period")
    @classmethod
    def check_period(cls, value):
        period_scope(value)
        return value


class BatchNote(NoteCreate):
    type: Literal["note"]
    source_key: SourceKey | None = None


class BatchMedia(MediaCreate):
    type: Literal["media"]
    source_key: SourceKey | None = None


class BatchEvent(EventCreate):
    type: Literal["event"]
    source_key: SourceKey | None = None


class BatchGoal(GoalCreate):
    type: Literal["goal"]
    source_key: SourceKey | None = None


BatchItem = Annotated[BatchNote | BatchMedia | BatchEvent | BatchGoal, Field(discriminator="type")]


class Batch(Input):
    items: list[BatchItem] = Field(min_length=1, max_length=1000)


class PhotoCreate(Input):
    date: DateString
    caption: Caption = None


class PhotoPatch(Input):
    date: DateString | None = None
    caption: Caption = None


class DecorationItem(Input):
    item_type: Literal["sticker", "photo", "text"]
    ref: str | None = None
    text: str | None = None
    color: Color | None = None
    x: finite(-0.25, 1.25)
    y: finite(-0.25, 1.25)
    scale: finite(0.1, 8) = 1.0
    rotation: finite(-360, 360) = 0.0
    z: Annotated[int, Field(strict=True, ge=0, le=10000)] = 0


class DecorationsPut(Input):
    # version is required (null for a never-decorated page) so a client cannot skip the check.
    version: TimestampString | None
    items: list[DecorationItem] = Field(max_length=200)


class StrokeCreate(Input):
    color: Color
    width: finite(0.0005, 0.05)
    points: list[Annotated[int, Field(strict=True)]] = Field(min_length=3, max_length=15000)

    @field_validator("points")
    @classmethod
    def check_points(cls, value):
        if len(value) % 3:
            raise ValueError("points 长度必须是 3 的倍数")
        for offset in range(0, len(value), 3):
            x, y, pressure = value[offset : offset + 3]
            if not (-2500 <= x <= 12500 and -2500 <= y <= 12500):
                raise ValueError("points 的 x、y 必须在 -2500 到 12500 之间")
            if not 0 <= pressure <= 255:
                raise ValueError("points 的压感必须在 0 到 255 之间")
        return value


class StrokesCreate(Input):
    strokes: list[StrokeCreate] = Field(min_length=1, max_length=50)


class Login(Input):
    password: str = Field(min_length=1, max_length=1024)


CREATE_SCHEMAS = {"note": NoteCreate, "media": MediaCreate, "event": EventCreate, "goal": GoalCreate}
