"""add_agent_action_audits

Revision ID: e2f4a6b8c901
Revises: d5e9f1a2b3c4
Create Date: 2026-06-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f4a6b8c901"
down_revision: Union[str, None] = "d5e9f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_action_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("action_id", sa.String(length=120), nullable=False),
        sa.Column("method", sa.String(length=12), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("request_meta", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("response_meta", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_agent_action_audits_created_at",
        "agent_action_audits",
        ["created_at"],
    )
    op.create_index(
        "ix_agent_action_audits_action_id",
        "agent_action_audits",
        ["action_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_action_audits_action_id", table_name="agent_action_audits")
    op.drop_index("ix_agent_action_audits_created_at", table_name="agent_action_audits")
    op.drop_table("agent_action_audits")
