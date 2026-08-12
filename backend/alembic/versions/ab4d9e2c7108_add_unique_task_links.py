"""enforce unique internal task links

Revision ID: ab4d9e2c7108
Revises: e8f2c4a6b901
Create Date: 2026-08-12
"""
from alembic import op


revision = "ab4d9e2c7108"
down_revision = "e8f2c4a6b901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_crm_task_link", "crm_task_links", ["task_id", "entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_constraint("uq_crm_task_link", "crm_task_links", type_="unique")
