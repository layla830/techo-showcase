from __future__ import annotations

from pydantic import ValidationError

from ..batch_keys import content_key, source_key
from ..clock import parse_stamp, stamp
from ..database import Database
from ..errors import APIError, invalid
from ..models import FIELDS, serialize
from ..repositories import BatchReceipts, Changes, Resources
from ..schemas import CREATE_SCHEMAS

NULLABLE = {"note": {"mood"}, "media": {"note"}, "event": {"time", "place"}, "goal": set()}


def require_version(row, expected_updated_at: str) -> None:
    # Compare instants, not strings: rows written under different TECHO_TIMEZONE values
    # have different offsets but may still be the same version.
    if parse_stamp(row.updated_at) != parse_stamp(expected_updated_at):
        raise APIError(409, "conflict", "条目已被修改，请重新读取后再操作", field="If-Match")


class JournalService:
    def __init__(self, database: Database):
        self.database = database

    def validate(self, kind: str, values: dict) -> dict:
        try:
            return CREATE_SCHEMAS[kind].model_validate(values).model_dump(mode="json")
        except ValidationError as exc:
            raise invalid(exc) from exc

    def _create(self, session, kind: str, values: dict, actor: str, **internal) -> dict:
        return self._insert(session, kind, self.validate(kind, values), actor, **internal)

    def _insert(self, session, kind: str, values: dict, actor: str, **internal) -> dict:
        resources = Resources(session)
        if kind == "goal" and values["sort"] is None:
            values["sort"] = resources.next_sort(values["scope"], values["period"])
        changes = Changes(session)
        at = changes.timestamp()
        row = resources.insert(kind, values, actor, at, **internal)
        changes.append(kind, row, actor, "created", at)
        BatchReceipts(session).remember(content_key(kind, values), kind, row.id, at)
        return serialize(kind, row)

    def create(self, kind: str, values: dict, actor: str) -> dict:
        with self.database.transaction(write=True) as session:
            return self._create(session, kind, values, actor)

    def patch(self, kind: str, record_id: int, values: dict, actor: str, *, expected_updated_at: str) -> dict:
        if not values:
            raise APIError(400, "validation_error", "PATCH 至少需要一个字段")
        for field, value in values.items():
            if value is None and field not in NULLABLE[kind]:
                raise APIError(400, "validation_error", "必填字段不能清空", field=field)
        with self.database.transaction(write=True) as session:
            resources = Resources(session)
            row = resources.get(kind, record_id)
            require_version(row, expected_updated_at)
            merged = self.validate(kind, {**{field: getattr(row, field) for field in FIELDS[kind]}, **values})
            if (
                kind == "goal"
                and "sort" not in values
                and (merged["scope"], merged["period"]) != (row.scope, row.period)
            ):
                merged["sort"] = resources.next_sort(merged["scope"], merged["period"])
            if all(getattr(row, field) == value for field, value in merged.items()):
                return serialize(kind, row)
            for field, value in merged.items():
                setattr(row, field, value)
            changes = Changes(session)
            row.updated_at = changes.timestamp()
            row.updated_by = actor
            changes.append(kind, row, actor, "updated", row.updated_at)
            BatchReceipts(session).remember(content_key(kind, merged), kind, row.id, row.updated_at)
            return serialize(kind, row)

    def delete(self, kind: str, record_id: int, actor: str, *, expected_updated_at: str) -> None:
        with self.database.transaction(write=True) as session:
            row = Resources(session).get(kind, record_id)
            require_version(row, expected_updated_at)
            changes = Changes(session)
            row.updated_at = row.deleted_at = changes.timestamp()
            row.updated_by = actor
            changes.append(kind, row, actor, "deleted", row.updated_at)
            BatchReceipts(session).remember(
                content_key(kind, serialize(kind, row)), kind, row.id, row.updated_at
            )

    def batch(self, items: list[dict], actor: str) -> dict:
        if actor != "agent":
            raise APIError(403, "forbidden", "批量写入只接受 Agent token")
        created, skipped = [], []
        with self.database.transaction(write=True) as session:
            resources = Resources(session)
            receipts = BatchReceipts(session)
            for index, item in enumerate(items):
                kind = item["type"]
                try:
                    values = self.validate(
                        kind, {key: value for key, value in item.items() if key not in {"type", "source_key"}}
                    )
                    content = content_key(kind, values)
                    identity = (
                        source_key(item["source_key"]) if item.get("source_key") is not None else content
                    )
                    previous = receipts.get(identity, kind)
                    if previous is not None:
                        skipped.append({"index": index, "type": kind, "id": previous.resource_id})
                        continue
                    duplicate = resources.duplicate(kind, values)
                    if duplicate is not None:
                        record_id = duplicate.id
                        skipped.append({"index": index, "type": kind, "id": record_id})
                    else:
                        row = self._insert(session, kind, values, actor)
                        record_id = row["id"]
                        created.append({"index": index, "type": kind, "item": row})
                    at = stamp()
                    receipts.remember(identity, kind, record_id, at)
                    receipts.remember(content, kind, record_id, at)
                except APIError as exc:
                    exc.index = index
                    raise
        return {"created": created, "skipped": skipped}

    def reorder(self, period: str, ids: list[int], actor: str, *, versions: dict[int, str]) -> dict:
        scope = "week" if "-W" in period else "month"
        with self.database.transaction(write=True) as session:
            rows = Resources(session).goals(scope, [period])
            if len(ids) != len(set(ids)) or set(ids) != {row.id for row in rows}:
                raise APIError(
                    409, "conflict", "目标列表已变化，ids 必须包含该周期全部目标且不能重复", field="ids"
                )
            if set(versions) != set(ids) or any(
                parse_stamp(versions[row.id]) != parse_stamp(row.updated_at) for row in rows
            ):
                raise APIError(
                    409, "conflict", "目标已被修改或重新排序，请重新读取后再操作", field="versions"
                )
            by_id = {row.id: row for row in rows}
            changes = Changes(session)
            for order, record_id in enumerate(ids):
                row = by_id[record_id]
                if row.sort != order:
                    row.sort = order
                    row.updated_at = changes.timestamp()
                    row.updated_by = actor
                    changes.append("goal", row, actor, "updated", row.updated_at)
        return {"period": period, "ids": ids}
