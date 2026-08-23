"""add integration runtime health and notification leases

Revision ID: 82b5e3d7f0a1
Revises: 81a4d2c6e9f0
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "82b5e3d7f0a1"
down_revision: Union[str, None] = "81a4d2c6e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_health_states",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "transition_epoch",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_integration_health_consecutive_failures_nonnegative",
        ),
        sa.CheckConstraint(
            "transition_epoch > 0",
            name="ck_integration_health_transition_epoch_positive",
        ),
        sa.PrimaryKeyConstraint("provider"),
    )
    op.create_table(
        "integration_worker_heartbeats",
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("booted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_job", sa.String(length=128), nullable=True),
        sa.Column("last_completed_job", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.add_column(
        "notification_jobs",
        sa.Column("provider_key", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "notification_jobs",
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "notification_jobs",
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "notification_jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_notification_jobs_provider_dedupe",
        "notification_jobs",
        ["provider_key", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text(
            "provider_key IS NOT NULL AND dedupe_key IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_notification_jobs_claimable",
        "notification_jobs",
        ["status", "next_attempt_at", "lease_expires_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_jobs_claimable",
        table_name="notification_jobs",
    )
    op.drop_index(
        "uq_notification_jobs_provider_dedupe",
        table_name="notification_jobs",
    )
    op.drop_column("notification_jobs", "lease_expires_at")
    op.drop_column("notification_jobs", "lease_owner")
    op.drop_column("notification_jobs", "dedupe_key")
    op.drop_column("notification_jobs", "provider_key")
    op.drop_table("integration_worker_heartbeats")
    op.drop_table("integration_health_states")
