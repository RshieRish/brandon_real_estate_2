"""add immutable recovered archive catalog"""
from alembic import op
import sqlalchemy as sa

revision = "fe2a1c4b8d75"
down_revision = "fb74d2c0a611"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "crm_archive_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_path", sa.String(length=1000), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("text_preview", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_path", name="uq_crm_archive_artifact_source_path"),
    )


def downgrade():
    op.drop_table("crm_archive_artifacts")
