"""add Command provenance and reconciliation tables"""
from alembic import op
import sqlalchemy as sa


revision = "1d6e7f8a9b10"
down_revision = "f0c8a6d9e431"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_source_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("record_kind", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("evidence_level", sa.String(length=32), nullable=False),
        sa.Column(
            "display_label",
            sa.String(length=500),
            nullable=False,
            server_default="",
        ),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "capture_quality",
            sa.String(length=32),
            nullable=False,
            server_default="complete",
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
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
        sa.UniqueConstraint(
            "source_system",
            "module",
            "record_kind",
            "source_key",
            "parser_version",
            name="uq_crm_source_record_identity",
        ),
    )
    op.create_index(
        "ix_crm_source_records_module_level",
        "crm_source_records",
        ["source_system", "module", "evidence_level"],
        unique=False,
    )

    op.create_table(
        "crm_source_record_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_record_id", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column(
            "relation",
            sa.String(length=32),
            nullable=False,
            server_default="evidence",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["crm_source_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["crm_archive_artifacts.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "source_record_id",
            "artifact_id",
            name="uq_crm_source_record_artifact",
        ),
    )

    op.create_table(
        "crm_entity_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["crm_source_records.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "source_record_id",
            "entity_type",
            name="uq_crm_source_entity_type",
        ),
        sa.UniqueConstraint(
            "entity_type",
            "entity_id",
            "source_record_id",
            name="uq_crm_entity_source",
        ),
    )
    op.create_index(
        "ix_crm_entity_sources_entity",
        "crm_entity_sources",
        ["entity_type", "entity_id"],
        unique=False,
    )

    op.create_table(
        "crm_reconciliation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bundle_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "requested_modules_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("error_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_crm_reconciliation_runs_bundle_fingerprint",
        "crm_reconciliation_runs",
        ["bundle_fingerprint"],
        unique=False,
    )

    op.create_table(
        "crm_reconciliation_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("expected_count", sa.Integer(), nullable=True),
        sa.Column("observed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rendered_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("normalized_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "evidence_only_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("unmatched_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "duplicate_content_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["crm_reconciliation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "run_id",
            "source_system",
            "module",
            name="uq_crm_reconciliation_result",
        ),
    )


def downgrade() -> None:
    op.drop_table("crm_reconciliation_results")
    op.drop_index(
        "ix_crm_reconciliation_runs_bundle_fingerprint",
        table_name="crm_reconciliation_runs",
    )
    op.drop_table("crm_reconciliation_runs")
    op.drop_index(
        "ix_crm_entity_sources_entity",
        table_name="crm_entity_sources",
    )
    op.drop_table("crm_entity_sources")
    op.drop_table("crm_source_record_artifacts")
    op.drop_index(
        "ix_crm_source_records_module_level",
        table_name="crm_source_records",
    )
    op.drop_table("crm_source_records")
