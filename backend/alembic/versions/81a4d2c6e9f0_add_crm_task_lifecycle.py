"""add CRM task lifecycle persistence"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "81a4d2c6e9f0"
down_revision = "7d1f3a5b6c8e"
branch_labels = None
depends_on = None


_PRESERVATION_COUNTS_TABLE = (
    "_crm_task_lifecycle_counts_81a4d2c6e9f0"
)


def _capture_preservation_counts() -> None:
    op.execute(
        sa.text(
            f"""
            CREATE TEMPORARY TABLE {_PRESERVATION_COUNTS_TABLE}
            ON COMMIT DROP AS
            SELECT
                (SELECT count(*) FROM crm_tasks) AS normalized_task_count,
                (
                    SELECT count(*)
                    FROM crm_tasks
                    WHERE status = 'archived'
                ) AS legacy_archived_count,
                (
                    SELECT count(*)
                    FROM crm_contact_source_occurrences
                ) AS source_occurrence_count
            """
        )
    )


def _assert_preservation_counts() -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            DECLARE
                expected_tasks bigint;
                expected_legacy_archived bigint;
                expected_source_occurrences bigint;
            BEGIN
                SELECT
                    normalized_task_count,
                    legacy_archived_count,
                    source_occurrence_count
                INTO
                    expected_tasks,
                    expected_legacy_archived,
                    expected_source_occurrences
                FROM {_PRESERVATION_COUNTS_TABLE};

                IF (SELECT count(*) FROM crm_tasks) <> expected_tasks THEN
                    RAISE EXCEPTION
                        'normalized CRM task count changed during 81a4d2c6e9f0';
                END IF;

                IF (
                    SELECT count(*)
                    FROM crm_tasks
                    WHERE archived_at IS NOT NULL
                      AND archived_by_type = 'migration'
                      AND archived_by_id = '81a4d2c6e9f0'
                      AND archive_reason = 'legacy_status_migration'
                      AND status = 'open'
                ) <> expected_legacy_archived THEN
                    RAISE EXCEPTION
                        'legacy archived CRM task normalization count changed';
                END IF;

                IF (
                    SELECT count(*)
                    FROM crm_contact_source_occurrences
                ) <> expected_source_occurrences THEN
                    RAISE EXCEPTION
                        'source-only recovered evidence count changed during '
                        '81a4d2c6e9f0';
                END IF;
            END
            $$
            """
        )
    )


def upgrade() -> None:
    _capture_preservation_counts()

    op.add_column(
        "crm_tasks",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "crm_tasks",
        sa.Column("archived_by_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "crm_tasks",
        sa.Column("archived_by_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "crm_tasks",
        sa.Column("archive_reason", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "crm_tasks",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.create_check_constraint(
        "ck_crm_tasks_version_positive",
        "crm_tasks",
        "version > 0",
    )
    op.execute(
        sa.text(
            """
            UPDATE crm_tasks
            SET archived_at = COALESCE(updated_at, created_at),
                archived_by_type = 'migration',
                archived_by_id = '81a4d2c6e9f0',
                archive_reason = 'legacy_status_migration',
                status = 'open'
            WHERE status = 'archived'
            """
        )
    )

    op.create_table(
        "crm_task_creation_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'applying'"),
        ),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column(
            "metadata_json",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("result_version", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["crm_tasks.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "scope",
            "idempotency_key",
            name="uq_crm_task_creation_request_scope_key",
        ),
        sa.CheckConstraint(
            "state IN ('applying', 'applied', 'failed')",
            name="ck_crm_task_creation_requests_state",
        ),
    )
    op.create_table(
        "crm_task_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("source_key", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["crm_tasks.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "source_type",
            "source_id",
            "source_key",
            name="uq_crm_task_source_identity",
        ),
    )
    op.create_table(
        "crm_record_lifecycle_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column(
            "request_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column(
            "result_json",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "metadata_json",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "entity_type",
            "entity_id",
            "action",
            "request_id",
            name="uq_crm_record_lifecycle_event_request",
        ),
    )

    op.create_index(
        "ix_crm_task_creation_requests_task_id",
        "crm_task_creation_requests",
        ["task_id"],
    )
    op.create_index(
        "ix_crm_task_sources_task_id",
        "crm_task_sources",
        ["task_id"],
    )
    op.create_index(
        "ix_crm_record_lifecycle_events_entity_created_at",
        "crm_record_lifecycle_events",
        ["entity_type", "entity_id", "created_at"],
    )
    op.create_index(
        "ix_crm_tasks_active_status_due_id",
        "crm_tasks",
        ["status", "due_at", "id"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "ix_crm_tasks_active_contact_status_id",
        "crm_tasks",
        ["contact_id", "status", "id"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "ix_crm_tasks_archived_at_id",
        "crm_tasks",
        ["archived_at", "id"],
        postgresql_where=sa.text("archived_at IS NOT NULL"),
    )

    _assert_preservation_counts()


def downgrade() -> None:
    """Downgrade cannot reconstruct a task's pre-archive workflow status."""

    op.execute(
        sa.text(
            "UPDATE crm_tasks SET status = 'archived' "
            "WHERE archived_at IS NOT NULL"
        )
    )

    op.drop_index(
        "ix_crm_tasks_archived_at_id", table_name="crm_tasks"
    )
    op.drop_index(
        "ix_crm_tasks_active_contact_status_id", table_name="crm_tasks"
    )
    op.drop_index(
        "ix_crm_tasks_active_status_due_id", table_name="crm_tasks"
    )
    op.drop_index(
        "ix_crm_record_lifecycle_events_entity_created_at",
        table_name="crm_record_lifecycle_events",
    )
    op.drop_index(
        "ix_crm_task_sources_task_id", table_name="crm_task_sources"
    )
    op.drop_index(
        "ix_crm_task_creation_requests_task_id",
        table_name="crm_task_creation_requests",
    )

    op.drop_table("crm_record_lifecycle_events")
    op.drop_table("crm_task_sources")
    op.drop_table("crm_task_creation_requests")
    op.drop_constraint(
        "ck_crm_tasks_version_positive",
        "crm_tasks",
        type_="check",
    )
    op.drop_column("crm_tasks", "version")
    op.drop_column("crm_tasks", "archive_reason")
    op.drop_column("crm_tasks", "archived_by_id")
    op.drop_column("crm_tasks", "archived_by_type")
    op.drop_column("crm_tasks", "archived_at")
