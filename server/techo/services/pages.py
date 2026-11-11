from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import delete, func, select, union

from ..clock import now, parse_stamp, stamp
from ..database import Database
from ..errors import APIError
from ..models import Decoration, Page, Photo, Stroke, serialize_decoration, serialize_stroke
from ..schemas import page_string

MAX_PAGE_STROKES = 3000
PHOTO_REF = re.compile(r"[1-9][0-9]{0,17}")


def check_page(value: str) -> str:
    try:
        return page_string(value)
    except ValueError as exc:
        raise APIError(400, "validation_error", str(exc), field="page") from exc


def item_error(index: int, field: str, message: str) -> APIError:
    return APIError(400, "validation_error", message, field=f"items.{index}.{field}", index=index)


def check_item(index: int, item: dict) -> dict:
    """Type-specific rules that the field-level schema cannot express."""
    kind, ref, text = item["item_type"], item["ref"], item["text"]
    if kind == "sticker":
        if ref is None or not 1 <= len(ref) <= 100 or not ref.startswith(("emoji:", "pack:")):
            raise item_error(index, "ref", "sticker 的 ref 必须为 1–100 字符，以 emoji: 或 pack: 开头")
        if text is not None:
            raise item_error(index, "text", "sticker 的 text 必须为 null")
    elif kind == "photo":
        if not isinstance(ref, str) or not PHOTO_REF.fullmatch(ref):
            raise item_error(index, "ref", "photo 的 ref 必须为十进制照片 id")
        if text is not None:
            text = text.strip() or None
            if text is not None and len(text) > 200:
                raise item_error(index, "text", "photo 的 text 不能超过 200 字符")
    else:
        text = text.strip() if isinstance(text, str) else ""
        if not 1 <= len(text) <= 200:
            raise item_error(index, "text", "text 物件的 text 去空白后必须为 1–200 字符")
        if ref is not None and not 1 <= len(ref) <= 40:
            raise item_error(index, "ref", "text 物件的 ref 必须为空或 1–40 字符的样式名")
    return {**item, "text": text}


def ordered(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda item: item["z"])  # stable: original order breaks ties


def same_version(current: str | None, expected: str | None) -> bool:
    # Versions are formatted in the configured timezone at write time, so compare instants.
    if current is None or expected is None:
        return current is None and expected is None
    return parse_stamp(current) == parse_stamp(expected)


class PageService:
    def __init__(self, database: Database):
        self.database = database

    def decorations(self, page: str) -> dict:
        page = check_page(page)
        with self.database.transaction() as session:
            row = session.get(Page, page)
            items = session.scalars(
                select(Decoration).where(Decoration.page == page).order_by(Decoration.position)
            )
            return {
                "page": page,
                "version": row.version if row is not None else None,
                "items": ordered([serialize_decoration(item) for item in items]),
            }

    def replace_decorations(self, page: str, version: str | None, items: list[dict], actor: str) -> dict:
        page = check_page(page)
        items = [check_item(index, item) for index, item in enumerate(items)]
        with self.database.transaction(write=True) as session:
            row = session.get(Page, page)
            if not same_version(row.version if row is not None else None, version):
                raise APIError(409, "conflict", "这一页已被修改，请重新读取后再保存", field="version")
            photo_ids = {int(item["ref"]) for item in items if item["item_type"] == "photo"}
            live = set(
                session.scalars(select(Photo.id).where(Photo.id.in_(photo_ids), Photo.deleted_at.is_(None)))
            )
            for index, item in enumerate(items):
                if item["item_type"] == "photo" and int(item["ref"]) not in live:
                    raise item_error(index, "ref", "照片不存在或已删除")
            current = now()
            if row is not None:
                current = max(current, parse_stamp(row.version) + timedelta(microseconds=1))
                session.execute(delete(Decoration).where(Decoration.page == page))
            else:
                row = Page(page=page)
                session.add(row)
            row.version = stamp(current)
            row.updated_by = actor
            session.flush()
            session.add_all(
                Decoration(page=page, position=position, **item) for position, item in enumerate(items)
            )
            return {"page": page, "version": row.version, "items": ordered(items)}

    def strokes(self, page: str) -> dict:
        page = check_page(page)
        with self.database.transaction() as session:
            rows = session.scalars(
                select(Stroke).where(Stroke.page == page, Stroke.deleted_at.is_(None)).order_by(Stroke.id)
            )
            return {"page": page, "strokes": [serialize_stroke(row) for row in rows]}

    def add_strokes(self, page: str, strokes: list[dict], actor: str) -> dict:
        page = check_page(page)
        with self.database.transaction(write=True) as session:
            count = session.scalar(
                select(func.count())
                .select_from(Stroke)
                .where(Stroke.page == page, Stroke.deleted_at.is_(None))
            )
            if count + len(strokes) > MAX_PAGE_STROKES:
                raise APIError(
                    409, "conflict", f"一页最多 {MAX_PAGE_STROKES} 笔，当前已有 {count} 笔", field="strokes"
                )
            at = stamp()
            rows = [
                Stroke(page=page, author=actor, created_at=at, deleted_at=None, **item) for item in strokes
            ]
            session.add_all(rows)
            session.flush()
            return {"strokes": [serialize_stroke(row) for row in rows]}

    def delete_stroke(self, stroke_id: int) -> None:
        with self.database.transaction(write=True) as session:
            row = session.get(Stroke, stroke_id)
            if row is None:
                raise APIError(404, "not_found", "笔画不存在")
            if row.deleted_at is None:
                row.deleted_at = stamp()

    @staticmethod
    def decorated_pages(session, pages: list[str]) -> list[str]:
        decorated = union(
            select(Decoration.page).where(Decoration.page.in_(pages)),
            select(Stroke.page).where(Stroke.page.in_(pages), Stroke.deleted_at.is_(None)),
        ).subquery()
        return sorted(session.scalars(select(decorated.c.page)))
