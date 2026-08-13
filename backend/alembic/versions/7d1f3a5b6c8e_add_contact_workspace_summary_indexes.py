"""add contact workspace summary query indexes"""

from alembic import op

revision = "7d1f3a5b6c8e"
down_revision = "6c0e2f4a5b7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_crm_tasks_contact_status_id",
        "crm_tasks",
        ["contact_id", "status", "id"],
    )
    op.create_index(
        "ix_crm_notes_contact_id",
        "crm_notes",
        ["contact_id", "id"],
    )
    op.create_index(
        "ix_crm_saved_searches_contact_id",
        "crm_saved_searches",
        ["contact_id", "id"],
    )
    op.create_index(
        "ix_crm_smart_plan_enrollments_contact_status_id",
        "crm_smart_plan_enrollments",
        ["contact_id", "status", "id"],
    )
    op.create_index(
        "ix_crm_opportunity_contacts_contact_opportunity",
        "crm_opportunity_contacts",
        ["contact_id", "opportunity_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crm_opportunity_contacts_contact_opportunity",
        table_name="crm_opportunity_contacts",
    )
    op.drop_index(
        "ix_crm_smart_plan_enrollments_contact_status_id",
        table_name="crm_smart_plan_enrollments",
    )
    op.drop_index(
        "ix_crm_saved_searches_contact_id",
        table_name="crm_saved_searches",
    )
    op.drop_index(
        "ix_crm_notes_contact_id",
        table_name="crm_notes",
    )
    op.drop_index(
        "ix_crm_tasks_contact_status_id",
        table_name="crm_tasks",
    )
