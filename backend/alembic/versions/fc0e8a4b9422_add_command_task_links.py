"""add generic internal task links"""
from alembic import op
import sqlalchemy as sa

revision = "fc0e8a4b9422"
down_revision = "fb74d2c0a611"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("crm_task_links", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("task_id", sa.Integer(), sa.ForeignKey("crm_tasks.id"), nullable=False), sa.Column("entity_type", sa.String(50), nullable=False), sa.Column("entity_id", sa.Integer(), nullable=False))
    op.create_index("ix_crm_task_links_task_id", "crm_task_links", ["task_id"])


def downgrade():
    op.drop_index("ix_crm_task_links_task_id", table_name="crm_task_links")
    op.drop_table("crm_task_links")
