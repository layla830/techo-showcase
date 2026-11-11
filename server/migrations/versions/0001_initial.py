"""Initial journal, audit and authentication tables."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def record_columns():
    return [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("author", sa.String(8), nullable=False),
        sa.Column("updated_by", sa.String(8), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("deleted_at", sa.String(32)),
    ]


def upgrade():
    op.create_table(
        "notes",
        *record_columns(),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("mood", sa.Text()),
    )
    op.create_index("ix_notes_date_deleted", "notes", ["date", "deleted_at"])
    op.create_table(
        "media",
        *record_columns(),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.CheckConstraint("kind IN ('book','film','series','show','other')", name="ck_media_kind"),
    )
    op.create_index("ix_media_date_deleted", "media", ["date", "deleted_at"])
    op.create_table(
        "events",
        *record_columns(),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("time", sa.String(5)),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("place", sa.Text()),
        sa.CheckConstraint("kind IN ('plan','anniversary')", name="ck_events_kind"),
    )
    op.create_index("ix_events_date_deleted", "events", ["date", "deleted_at"])
    op.create_table(
        "seed_occurrences",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
    )
    op.create_index("ix_seed_occurrences_event_id", "seed_occurrences", ["event_id"])
    op.create_table(
        "goals",
        *record_columns(),
        sa.Column("scope", sa.String(5), nullable=False),
        sa.Column("period", sa.String(8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(7), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.CheckConstraint("scope IN ('week','month')", name="ck_goals_scope"),
        sa.CheckConstraint("status IN ('open','done','dropped')", name="ck_goals_status"),
        sa.CheckConstraint("sort >= 0", name="ck_goals_sort"),
    )
    op.create_index("ix_goals_period_deleted", "goals", ["scope", "period", "deleted_at", "sort"])
    op.create_table(
        "changes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor", sa.String(8), nullable=False),
        sa.Column("resource_type", sa.String(8), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("op", sa.String(8), nullable=False),
        sa.Column("at", sa.String(32), nullable=False, unique=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
    )
    op.create_index("ix_changes_actor_at", "changes", ["actor", "at"])
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("at", sa.String(32), nullable=False),
    )
    op.create_index("ix_login_attempts_ip_at", "login_attempts", ["ip_hash", "at"])


def downgrade():
    for table in (
        "login_attempts",
        "sessions",
        "changes",
        "goals",
        "seed_occurrences",
        "events",
        "media",
        "notes",
    ):
        op.drop_table(table)
