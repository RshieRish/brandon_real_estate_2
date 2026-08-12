"""add private contact celebrations

Revision ID: a2d7e4b9c118
Revises: fd1c8e9a4703
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa


revision = "a2d7e4b9c118"
down_revision = "fd1c8e9a4703"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crm_contacts", sa.Column("birthday", sa.Date(), nullable=True))
    op.add_column("crm_contacts", sa.Column("anniversary", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("crm_contacts", "anniversary")
    op.drop_column("crm_contacts", "birthday")
