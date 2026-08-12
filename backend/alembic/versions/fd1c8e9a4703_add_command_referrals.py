"""add internal command referrals"""
from alembic import op
import sqlalchemy as sa

revision = "fd1c8e9a4703"
down_revision = "fc0e8a4b9422"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("crm_referrals", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id"), nullable=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("source", sa.String(255), server_default=""), sa.Column("status", sa.String(32), server_default="new"), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))

def downgrade(): op.drop_table("crm_referrals")
