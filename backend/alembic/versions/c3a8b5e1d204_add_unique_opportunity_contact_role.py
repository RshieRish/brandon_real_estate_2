"""enforce unique opportunity contact roles

Revision ID: c3a8b5e1d204
Revises: b7e1f2d4a906
Create Date: 2026-08-12
"""
from alembic import op

revision = "c3a8b5e1d204"
down_revision = "b7e1f2d4a906"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_unique_constraint("uq_crm_opportunity_contact_role", "crm_opportunity_contacts", ["opportunity_id", "contact_id", "role"])

def downgrade() -> None:
    op.drop_constraint("uq_crm_opportunity_contact_role", "crm_opportunity_contacts", type_="unique")
