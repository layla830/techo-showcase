"""Preserve automatic-entry identities across edits and deletion."""

import hashlib
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.sqlite import insert

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

KEY_FIELDS = {
    "note": ("notes", ("date", "text")),
    "media": ("media", ("date", "title")),
    "event": ("events", ("date", "title")),
    "goal": ("goals", ("scope", "period", "text")),
}


def upgrade():
    op.create_table(
        "batch_receipts",
        sa.Column("key", sa.String(72), primary_key=True),
        sa.Column("resource_type", sa.String(8), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_batch_receipts_resource", "batch_receipts", ["resource_type", "resource_id"])
    connection = op.get_bind()
    receipts = sa.table(
        "batch_receipts",
        sa.column("key"),
        sa.column("resource_type"),
        sa.column("resource_id"),
        sa.column("created_at"),
    )

    def remember(kind, record_id, values, at):
        identity = {field: values[field].strip() for field in KEY_FIELDS[kind][1]}
        identity["type"] = kind
        encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        key = "content:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        connection.execute(
            insert(receipts)
            .values(key=key, resource_type=kind, resource_id=record_id, created_at=at)
            .on_conflict_do_nothing(index_elements=["key"])
        )

    changes = sa.table(
        "changes",
        sa.column("id"),
        sa.column("resource_type"),
        sa.column("resource_id"),
        sa.column("at"),
        sa.column("snapshot", sa.JSON()),
    )
    statement = sa.select(changes).where(changes.c.resource_type.in_(KEY_FIELDS)).order_by(changes.c.id)
    for change in connection.execute(statement).mappings():
        remember(change["resource_type"], change["resource_id"], change["snapshot"], change["at"])
    for kind, (name, fields) in KEY_FIELDS.items():
        table = sa.table(
            name, sa.column("id"), sa.column("created_at"), *(sa.column(field) for field in fields)
        )
        for row in connection.execute(sa.select(table).order_by(table.c.id)).mappings():
            remember(kind, row["id"], row, row["created_at"])


def downgrade():
    op.drop_index("ix_batch_receipts_resource", table_name="batch_receipts")
    op.drop_table("batch_receipts")
