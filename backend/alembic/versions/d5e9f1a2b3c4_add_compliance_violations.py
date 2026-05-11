"""add_compliance_violations

Revision ID: d5e9f1a2b3c4
Revises: a1b2c3d4e5f6
Create Date: 2026-05-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e9f1a2b3c4"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compliance_violations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="investor_report"),
        sa.Column("rule_id", sa.String(50), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("field_path", sa.String(100), nullable=False),
        sa.Column("matched_text", sa.Text(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=False),
        sa.Column("rewrite_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolution", sa.String(50), nullable=False),
    )
    op.create_index(
        "ix_compliance_violations_created_at",
        "compliance_violations",
        ["created_at"],
    )
    op.create_index(
        "ix_compliance_violations_lead_id",
        "compliance_violations",
        ["lead_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_compliance_violations_lead_id", table_name="compliance_violations")
    op.drop_index("ix_compliance_violations_created_at", table_name="compliance_violations")
    op.drop_table("compliance_violations")
