"""link private command files to agreements"""
from alembic import op
import sqlalchemy as sa

revision = "fb74d2c0a611"
down_revision = "fa4c19d2e3b7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("crm_file_assets", sa.Column("agreement_id", sa.Integer(), sa.ForeignKey("crm_agreements.id"), nullable=True))


def downgrade():
    op.drop_column("crm_file_assets", "agreement_id")
