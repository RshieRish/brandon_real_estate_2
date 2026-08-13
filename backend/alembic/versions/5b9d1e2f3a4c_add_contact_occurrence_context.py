"""add contact occurrence context"""

import sqlalchemy as sa

from alembic import op

revision = "5b9d1e2f3a4c"
down_revision = "4a8c0d1e2f3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("crm_activities") as batch_op:
        batch_op.add_column(
            sa.Column("source_record_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_crm_activities_source_record_id",
            "crm_source_records",
            ["source_record_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "uq_crm_activities_source_record_id",
            ["source_record_id"],
            unique=True,
        )

    op.create_table(
        "crm_contact_source_occurrences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("section_capture_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=False),
        sa.Column("occurrence_ordinal", sa.Integer(), nullable=False),
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
            ["contact_id"], ["crm_contacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["section_capture_id"],
            ["crm_contact_section_captures.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["crm_source_records.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "source_record_id",
            name="uq_crm_contact_source_occurrence_source",
        ),
        sa.UniqueConstraint(
            "section_capture_id",
            "occurrence_ordinal",
            name="uq_crm_contact_source_occurrence_section_ordinal",
        ),
        sa.CheckConstraint(
            "occurrence_ordinal > 0",
            name="ck_crm_contact_source_occurrence_ordinal",
        ),
    )
    op.create_index(
        "ix_crm_contact_source_occurrence_contact_section",
        "crm_contact_source_occurrences",
        ["contact_id", "section_capture_id", "id"],
    )

    with op.batch_alter_table("crm_contact_timeline_events") as batch_op:
        batch_op.alter_column(
            "occurred_at",
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=False,
            nullable=True,
        )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "contact occurrence downgrade requires an online losslessness preflight"
        )
    connection = op.get_bind()
    null_count = connection.scalar(
        sa.text(
            "SELECT count(*) FROM crm_contact_timeline_events "
            "WHERE occurred_at IS NULL"
        )
    )
    if null_count:
        raise RuntimeError(
            "cannot restore a non-null recovered timeline timestamp while null "
            "source observations exist"
        )

    with op.batch_alter_table("crm_contact_timeline_events") as batch_op:
        batch_op.alter_column(
            "occurred_at",
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
            nullable=False,
        )

    op.drop_index(
        "ix_crm_contact_source_occurrence_contact_section",
        table_name="crm_contact_source_occurrences",
    )
    op.drop_table("crm_contact_source_occurrences")

    with op.batch_alter_table("crm_activities") as batch_op:
        batch_op.drop_index("uq_crm_activities_source_record_id")
        batch_op.drop_constraint(
            "fk_crm_activities_source_record_id", type_="foreignkey"
        )
        batch_op.drop_column("source_record_id")
