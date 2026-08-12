"""store recovered archive bytes in internal database"""
from alembic import op
import sqlalchemy as sa

revision = "ff7d8e1a9234"
down_revision = "fe2a1c4b8d75"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("crm_archive_artifacts", sa.Column("content_bytes", sa.LargeBinary(), nullable=True))


def downgrade():
    op.drop_column("crm_archive_artifacts", "content_bytes")
