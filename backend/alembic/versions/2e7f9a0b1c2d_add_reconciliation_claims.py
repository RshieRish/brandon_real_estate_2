"""add exclusive reconciliation worker claims"""

from alembic import op
import sqlalchemy as sa


revision = "2e7f9a0b1c2d"
down_revision = "1d6e7f8a9b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_reconciliation_runs",
        sa.Column(
            "claim_token",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "crm_reconciliation_runs",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("crm_reconciliation_runs", "claimed_at")
    op.drop_column("crm_reconciliation_runs", "claim_token")
