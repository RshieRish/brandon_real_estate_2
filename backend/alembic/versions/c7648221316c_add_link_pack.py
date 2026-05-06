"""add_link_pack

Revision ID: c7648221316c
Revises: 7efdda0d6b65
Create Date: 2026-05-06 07:23:57.604504

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c7648221316c'
down_revision: Union[str, None] = '7efdda0d6b65'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "link_pack",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("profile_bio", sa.Text(), nullable=False, server_default=""),
        sa.Column("profile_photo_data", sa.LargeBinary(), nullable=True),
        sa.Column("profile_photo_mime", sa.String(100), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("social_phone", sa.String(50), nullable=True),
        sa.Column("social_email", sa.String(255), nullable=True),
        sa.Column("social_instagram", sa.String(255), nullable=True),
        sa.Column("social_facebook", sa.String(255), nullable=True),
        sa.Column("social_youtube", sa.String(255), nullable=True),
        sa.Column("social_website", sa.String(255), nullable=True),
        sa.Column("social_tiktok", sa.String(255), nullable=True),
        sa.Column("social_x", sa.String(255), nullable=True),
        sa.Column("theme", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("background_image_data", sa.LargeBinary(), nullable=True),
        sa.Column("background_image_mime", sa.String(100), nullable=True),
        sa.Column("published_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("has_unpublished_changes", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "link_pack_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        # link_pack_id is always 1 in v1 (singleton); the application layer sets this explicitly.
        sa.Column("link_pack_id", sa.Integer(), sa.ForeignKey("link_pack.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("link_pack_items.id", ondelete="CASCADE"), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("thumbnail_data", sa.LargeBinary(), nullable=True),
        sa.Column("thumbnail_mime", sa.String(100), nullable=True),
        sa.Column("gated_file_data", sa.LargeBinary(), nullable=True),
        sa.Column("gated_file_mime", sa.String(100), nullable=True),
        sa.Column("gated_filename", sa.String(255), nullable=True),
        sa.Column("gate_modal_headline", sa.String(255), nullable=True),
        sa.Column("gate_modal_subtext", sa.Text(), nullable=True),
        sa.Column("animation", sa.String(20), nullable=False, server_default="none"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_link_pack_items_parent", "link_pack_items", ["parent_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_link_pack_items_parent", table_name="link_pack_items")
    op.drop_table("link_pack_items")
    op.drop_table("link_pack")
