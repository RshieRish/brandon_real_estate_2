"""add command opportunity and agreement relationships"""
from alembic import op
import sqlalchemy as sa
revision="f9d83a7b2c61"
down_revision="f6b24e1c8a03"
branch_labels=None
depends_on=None
def upgrade():
    op.create_table("crm_opportunity_contacts",sa.Column("id",sa.Integer,primary_key=True),sa.Column("opportunity_id",sa.Integer,sa.ForeignKey("crm_opportunities.id"),nullable=False),sa.Column("contact_id",sa.Integer,sa.ForeignKey("crm_contacts.id"),nullable=False),sa.Column("role",sa.String(50),server_default="client"))
    op.create_table("crm_opportunity_vendors",sa.Column("id",sa.Integer,primary_key=True),sa.Column("opportunity_id",sa.Integer,sa.ForeignKey("crm_opportunities.id"),nullable=False),sa.Column("name",sa.String(255),nullable=False),sa.Column("role",sa.String(80),server_default="vendor"))
    op.create_table("crm_opportunity_offers",sa.Column("id",sa.Integer,primary_key=True),sa.Column("opportunity_id",sa.Integer,sa.ForeignKey("crm_opportunities.id"),nullable=False),sa.Column("amount_cents",sa.Integer),sa.Column("status",sa.String(32),server_default="draft"))
    op.create_table("crm_agreement_recipients",sa.Column("id",sa.Integer,primary_key=True),sa.Column("agreement_id",sa.Integer,sa.ForeignKey("crm_agreements.id"),nullable=False),sa.Column("name",sa.String(255),nullable=False),sa.Column("email",sa.String(255),nullable=False),sa.Column("role",sa.String(50),server_default="recipient"))
def downgrade():
    op.drop_table("crm_agreement_recipients");op.drop_table("crm_opportunity_offers");op.drop_table("crm_opportunity_vendors");op.drop_table("crm_opportunity_contacts")
