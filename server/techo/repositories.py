from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .clock import now, parse_stamp, stamp
from .errors import APIError
from .models import FIELDS, MODELS, BatchReceipt, Change, Goal, serialize


class Resources:
    def __init__(self, session: Session):
        self.session = session

    def get(self, kind: str, record_id: int):
        row = self.session.get(MODELS[kind], record_id)
        if row is None or row.deleted_at is not None:
            raise APIError(404, "not_found", "条目不存在")
        return row

    def dated(self, kind: str, start: str, end: str) -> list[dict]:
        model = MODELS[kind]
        statement = select(model).where(model.deleted_at.is_(None), model.date >= start, model.date <= end)
        ordering = (model.date, model.time, model.id) if kind == "event" else (model.date, model.id)
        return [serialize(kind, row) for row in self.session.scalars(statement.order_by(*ordering))]

    def goals(self, scope: str, periods: list[str]) -> list:
        statement = select(Goal).where(
            Goal.deleted_at.is_(None), Goal.scope == scope, Goal.period.in_(periods)
        )
        return list(self.session.scalars(statement.order_by(Goal.period, Goal.sort, Goal.id)))

    def next_sort(self, scope: str, period: str) -> int:
        maximum = self.session.scalar(
            select(func.max(Goal.sort)).where(
                Goal.deleted_at.is_(None), Goal.scope == scope, Goal.period == period
            )
        )
        return 0 if maximum is None else maximum + 1

    def duplicate(self, kind: str, values: dict):
        model = MODELS[kind]
        key_fields = (
            ("scope", "period", "text") if kind == "goal" else ("date", "text" if kind == "note" else "title")
        )
        statement = select(model).where(
            model.deleted_at.is_(None), *(getattr(model, field) == values[field] for field in key_fields)
        )
        return self.session.scalars(statement.order_by(model.id)).first()

    def insert(self, kind: str, values: dict, actor: str, at: str, **internal):
        fields = {field: values[field] for field in FIELDS[kind]}
        row = MODELS[kind](
            **fields,
            author=actor,
            updated_by=actor,
            created_at=at,
            updated_at=at,
            deleted_at=None,
            **internal,
        )
        self.session.add(row)
        self.session.flush()
        return row


class BatchReceipts:
    def __init__(self, session: Session):
        self.session = session

    def get(self, key: str, kind: str) -> BatchReceipt | None:
        receipt = self.session.get(BatchReceipt, key)
        if receipt is not None and receipt.resource_type != kind:
            raise APIError(409, "conflict", "source_key 已绑定到其他资源类型", field="source_key")
        return receipt

    def remember(self, key: str, kind: str, record_id: int, at: str) -> None:
        if self.get(key, kind) is None:
            self.session.add(BatchReceipt(key=key, resource_type=kind, resource_id=record_id, created_at=at))
            self.session.flush()


class Changes:
    def __init__(self, session: Session):
        self.session = session

    def timestamp(self) -> str:
        previous = self.session.info.get("last_change_at")
        if previous is None:
            row = self.session.scalars(select(Change).order_by(Change.id.desc()).limit(1)).first()
            previous = row.at if row is not None else None
        current = now()
        if previous is not None:
            current = max(current, parse_stamp(previous) + timedelta(microseconds=1))
        value = stamp(current)
        self.session.info["last_change_at"] = value
        return value

    def append(self, kind: str, row, actor: str, op: str, at: str) -> None:
        self.session.add(
            Change(
                actor=actor,
                resource_type=kind,
                resource_id=row.id,
                op=op,
                at=at,
                snapshot=serialize(kind, row),
            )
        )
        self.session.flush()

    def since(self, actor: str, since: str, limit: int) -> dict:
        # The watermark and rows must come from the same SQLite read snapshot.
        watermark_row = self.session.scalars(select(Change).order_by(Change.id.desc()).limit(1)).first()
        watermark = watermark_row.at if watermark_row is not None else None
        other = "agent" if actor == "human" else "human"
        since_at = parse_stamp(since)
        # Stored offsets can differ after a timezone change; filter and order by instant.
        rows = [
            row
            for row in self.session.scalars(select(Change).where(Change.actor == other).order_by(Change.id))
            if parse_stamp(row.at) > since_at
        ]
        rows.sort(key=lambda row: parse_stamp(row.at))
        has_more = len(rows) > limit
        rows = rows[:limit]
        if has_more:
            cursor = rows[-1].at
        elif watermark is not None and parse_stamp(watermark) > since_at:
            cursor = watermark
        else:
            cursor = since
        return {
            "changes": [
                {
                    "change_id": row.id,
                    "type": row.resource_type,
                    "id": row.resource_id,
                    "op": row.op,
                    "at": row.at,
                    "data": row.snapshot,
                }
                for row in rows
            ],
            "cursor": cursor,
            "has_more": has_more,
        }
