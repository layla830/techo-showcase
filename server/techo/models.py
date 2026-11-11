from __future__ import annotations

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author: Mapped[str] = mapped_column(String(8))
    updated_by: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    deleted_at: Mapped[str | None] = mapped_column(String(32))


class Note(Record, Base):
    __tablename__ = "notes"
    __table_args__ = (Index("ix_notes_date_deleted", "date", "deleted_at"),)
    date: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    mood: Mapped[str | None] = mapped_column(Text)


class Media(Record, Base):
    __tablename__ = "media"
    __table_args__ = (
        CheckConstraint("kind IN ('book','film','series','show','other')", name="ck_media_kind"),
        Index("ix_media_date_deleted", "date", "deleted_at"),
    )
    date: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class Event(Record, Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("kind IN ('plan','anniversary')", name="ck_events_kind"),
        Index("ix_events_date_deleted", "date", "deleted_at"),
    )
    date: Mapped[str] = mapped_column(String(10))
    time: Mapped[str | None] = mapped_column(String(5))
    title: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(12))
    place: Mapped[str | None] = mapped_column(Text)


class SeedOccurrence(Base):
    __tablename__ = "seed_occurrences"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)


class Goal(Record, Base):
    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint("scope IN ('week','month')", name="ck_goals_scope"),
        CheckConstraint("status IN ('open','done','dropped')", name="ck_goals_status"),
        CheckConstraint("sort >= 0", name="ck_goals_sort"),
        Index("ix_goals_period_deleted", "scope", "period", "deleted_at", "sort"),
    )
    scope: Mapped[str] = mapped_column(String(5))
    period: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(7))
    sort: Mapped[int] = mapped_column(Integer)


class Photo(Record, Base):
    __tablename__ = "photos"
    __table_args__ = (Index("ix_photos_date_deleted", "date", "deleted_at"),)
    date: Mapped[str] = mapped_column(String(10))
    caption: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    hash: Mapped[str] = mapped_column(String(12))
    # Paths are relative to data/photos and never leave the server.
    full_path: Mapped[str] = mapped_column(String(120))
    thumb_path: Mapped[str] = mapped_column(String(120))


class Page(Base):
    __tablename__ = "pages"
    page: Mapped[str] = mapped_column(String(16), primary_key=True)
    version: Mapped[str] = mapped_column(String(32))
    updated_by: Mapped[str] = mapped_column(String(8))


class Decoration(Base):
    __tablename__ = "decorations"
    __table_args__ = (
        CheckConstraint("item_type IN ('sticker','photo','text')", name="ck_decorations_item_type"),
        Index("ix_decorations_page_position", "page", "position"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page: Mapped[str] = mapped_column(ForeignKey("pages.page"))
    position: Mapped[int] = mapped_column(Integer)
    item_type: Mapped[str] = mapped_column(String(8))
    ref: Mapped[str | None] = mapped_column(String(100))
    text: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(7))
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    scale: Mapped[float] = mapped_column(Float)
    rotation: Mapped[float] = mapped_column(Float)
    z: Mapped[int] = mapped_column(Integer)


class Stroke(Base):
    __tablename__ = "strokes"
    __table_args__ = (Index("ix_strokes_page_deleted", "page", "deleted_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page: Mapped[str] = mapped_column(String(16))
    color: Mapped[str] = mapped_column(String(7))
    width: Mapped[float] = mapped_column(Float)
    points: Mapped[list] = mapped_column(JSON)
    author: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[str] = mapped_column(String(32))
    deleted_at: Mapped[str | None] = mapped_column(String(32))


class Change(Base):
    __tablename__ = "changes"
    __table_args__ = (Index("ix_changes_actor_at", "actor", "at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(8))
    resource_type: Mapped[str] = mapped_column(String(8))
    resource_id: Mapped[int] = mapped_column(Integer)
    op: Mapped[str] = mapped_column(String(8))
    at: Mapped[str] = mapped_column(String(32), unique=True)
    snapshot: Mapped[dict] = mapped_column(JSON)


class BatchReceipt(Base):
    __tablename__ = "batch_receipts"
    __table_args__ = (Index("ix_batch_receipts_resource", "resource_type", "resource_id"),)
    key: Mapped[str] = mapped_column(String(72), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(8))
    resource_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(32))


class BrowserSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[str] = mapped_column(String(32), index=True)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_ip_at", "ip_hash", "at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_hash: Mapped[str] = mapped_column(String(64))
    at: Mapped[str] = mapped_column(String(32))


MODELS = {"note": Note, "media": Media, "event": Event, "goal": Goal, "photo": Photo}
FIELDS = {
    "note": ("date", "text", "mood"),
    "media": ("date", "kind", "title", "note"),
    "event": ("date", "time", "title", "kind", "place"),
    "goal": ("scope", "period", "text", "status", "sort"),
    "photo": ("date", "caption", "width", "height", "hash"),
}
DECORATION_FIELDS = ("item_type", "ref", "text", "color", "x", "y", "scale", "rotation", "z")
STROKE_FIELDS = ("id", "page", "color", "width", "points", "author", "created_at")
COMMON_FIELDS = ("id", "author", "updated_by", "created_at", "updated_at", "deleted_at")


def serialize(kind: str, row: Record) -> dict:
    return {field: getattr(row, field) for field in (*COMMON_FIELDS, *FIELDS[kind])}


def serialize_decoration(row: Decoration) -> dict:
    return {field: getattr(row, field) for field in DECORATION_FIELDS}


def serialize_stroke(row: Stroke) -> dict:
    return {field: getattr(row, field) for field in STROKE_FIELDS}
