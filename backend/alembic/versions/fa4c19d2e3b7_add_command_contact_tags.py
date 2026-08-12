"""add command contact tag assignments"""
from alembic import op
import sqlalchemy as sa
revision="fa4c19d2e3b7"
down_revision="f9d83a7b2c61"
branch_labels=None
depends_on=None
def upgrade():
    op.create_table("crm_contact_tags",sa.Column("id",sa.Integer,primary_key=True),sa.Column("contact_id",sa.Integer,sa.ForeignKey("crm_contacts.id"),nullable=False),sa.Column("tag_id",sa.Integer,sa.ForeignKey("crm_tags.id"),nullable=False),sa.UniqueConstraint("contact_id","tag_id",name="uq_crm_contact_tag"))
def downgrade(): op.drop_table("crm_contact_tags")
