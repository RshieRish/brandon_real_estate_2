"""add internal command goals

Revision ID: b7e1f2d4a906
Revises: a2d7e4b9c118
Create Date: 2026-08-12
"""
from alembic import op
import sqlalchemy as sa

revision = "b7e1f2d4a906"
down_revision = "a2d7e4b9c118"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("crm_goals", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("target_value", sa.Integer(), nullable=False), sa.Column("current_value", sa.Integer(), nullable=False, server_default="0"), sa.Column("period", sa.String(32), nullable=False, server_default="monthly"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))

def downgrade() -> None:
    op.drop_table("crm_goals")
