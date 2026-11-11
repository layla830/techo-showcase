"""Photos, page decorations and handwriting strokes."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    # Only new tables: existing journal rows, change log and receipts stay untouched.
    op.create_table(
        "photos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("author", sa.String(8), nullable=False),
        sa.Column("updated_by", sa.String(8), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("deleted_at", sa.String(32)),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("caption", sa.Text()),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("hash", sa.String(12), nullable=False),
        sa.Column("full_path", sa.String(120), nullable=False),
        sa.Column("thumb_path", sa.String(120), nullable=False),
    )
    op.create_index("ix_photos_date_deleted", "photos", ["date", "deleted_at"])
    op.create_table(
        "pages",
        sa.Column("page", sa.String(16), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("updated_by", sa.String(8), nullable=False),
    )
    op.create_table(
        "decorations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("page", sa.String(16), sa.ForeignKey("pages.page"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(8), nullable=False),
        sa.Column("ref", sa.String(100)),
        sa.Column("text", sa.Text()),
        sa.Column("color", sa.String(7)),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("scale", sa.Float(), nullable=False),
        sa.Column("rotation", sa.Float(), nullable=False),
        sa.Column("z", sa.Integer(), nullable=False),
        sa.CheckConstraint("item_type IN ('sticker','photo','text')", name="ck_decorations_item_type"),
    )
    op.create_index("ix_decorations_page_position", "decorations", ["page", "position"])
    op.create_table(
        "strokes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("page", sa.String(16), nullable=False),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("points", sa.JSON(), nullable=False),
        sa.Column("author", sa.String(8), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("deleted_at", sa.String(32)),
    )
    op.create_index("ix_strokes_page_deleted", "strokes", ["page", "deleted_at"])


def downgrade():
    op.drop_index("ix_strokes_page_deleted", table_name="strokes")
    op.drop_table("strokes")
    op.drop_index("ix_decorations_page_position", table_name="decorations")
    op.drop_table("decorations")
    op.drop_table("pages")
    op.drop_index("ix_photos_date_deleted", table_name="photos")
    op.drop_table("photos")
