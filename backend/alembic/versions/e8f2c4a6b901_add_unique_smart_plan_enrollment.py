"""enforce unique Smart Plan enrollment per contact

Revision ID: e8f2c4a6b901
Revises: c3a8b5e1d204
Create Date: 2026-08-12
"""
from alembic import op


revision = "e8f2c4a6b901"
down_revision = "c3a8b5e1d204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_crm_smart_plan_enrollment",
        "crm_smart_plan_enrollments",
        ["smart_plan_id", "contact_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_crm_smart_plan_enrollment", "crm_smart_plan_enrollments", type_="unique")
