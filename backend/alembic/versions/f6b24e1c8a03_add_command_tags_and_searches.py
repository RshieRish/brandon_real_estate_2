"""add command tags and saved searches"""
from alembic import op
import sqlalchemy as sa
revision="f6b24e1c8a03"
down_revision="f3a91c2d7e10"
branch_labels=None
depends_on=None
def upgrade():
    op.create_table("crm_tags",sa.Column("id",sa.Integer,primary_key=True),sa.Column("name",sa.String(80),nullable=False,unique=True))
    op.create_table("crm_saved_searches",sa.Column("id",sa.Integer,primary_key=True),sa.Column("contact_id",sa.Integer,sa.ForeignKey("crm_contacts.id")),sa.Column("name",sa.String(255),nullable=False),sa.Column("criteria",sa.Text,server_default="{}"),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.func.now()))
def downgrade():
    op.drop_table("crm_saved_searches");op.drop_table("crm_tags")
