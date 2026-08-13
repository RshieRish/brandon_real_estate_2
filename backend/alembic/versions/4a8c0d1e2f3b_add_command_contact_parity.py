"""add Command contact parity tables"""

from alembic import op
import sqlalchemy as sa


revision = "4a8c0d1e2f3b"
down_revision = "2e7f9a0b1c2d"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def _contact_foreign_key() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["contact_id"], ["crm_contacts.id"], ondelete="CASCADE"
    )


def _source_foreign_key() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["source_record_id"], ["crm_source_records.id"], ondelete="RESTRICT"
    )


def _source_key_unique(name: str) -> sa.UniqueConstraint:
    return sa.UniqueConstraint("contact_id", "source_key", name=name)


def upgrade() -> None:
    op.create_table(
        "crm_contact_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False, unique=True),
        sa.Column(
            "recovered_identity_hash", sa.String(length=64), nullable=True, unique=True
        ),
        sa.Column("legal_name", sa.String(length=255), nullable=True),
        sa.Column("preferred_name", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("lead_source", sa.String(length=255), nullable=True),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("health_score", sa.Integer(), nullable=True),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_interaction_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("birth_month", sa.Integer(), nullable=True),
        sa.Column("birth_day", sa.Integer(), nullable=True),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column(
            "birth_year_quality",
            sa.String(length=24),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("birth_raw", sa.String(length=64), nullable=True),
        sa.Column("anniversary_month", sa.Integer(), nullable=True),
        sa.Column("anniversary_day", sa.Integer(), nullable=True),
        sa.Column("anniversary_year", sa.Integer(), nullable=True),
        sa.Column(
            "anniversary_year_quality",
            sa.String(length=24),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("anniversary_raw", sa.String(length=64), nullable=True),
        *_timestamps(),
        _contact_foreign_key(),
        sa.CheckConstraint(
            "health_score IS NULL OR health_score BETWEEN 0 AND 100",
            name="ck_crm_contact_profile_health_score",
        ),
        sa.CheckConstraint(
            "birth_month IS NULL OR birth_month BETWEEN 1 AND 12",
            name="ck_crm_contact_profile_birth_month",
        ),
        sa.CheckConstraint(
            "birth_day IS NULL OR birth_day BETWEEN 1 AND 31",
            name="ck_crm_contact_profile_birth_day",
        ),
        sa.CheckConstraint(
            "anniversary_month IS NULL OR anniversary_month BETWEEN 1 AND 12",
            name="ck_crm_contact_profile_anniversary_month",
        ),
        sa.CheckConstraint(
            "anniversary_day IS NULL OR anniversary_day BETWEEN 1 AND 31",
            name="ck_crm_contact_profile_anniversary_day",
        ),
        sa.CheckConstraint(
            "birth_year_quality IN ('verified', 'yearless', 'sentinel', 'unknown')",
            name="ck_crm_contact_profile_birth_year_quality",
        ),
        sa.CheckConstraint(
            "anniversary_year_quality IN "
            "('verified', 'yearless', 'sentinel', 'unknown')",
            name="ck_crm_contact_profile_anniversary_year_quality",
        ),
    )

    op.create_table(
        "crm_contact_methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=True),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("raw_value", sa.String(length=500), nullable=True),
        sa.Column("normalized_value", sa.String(length=500), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        *_timestamps(),
        _contact_foreign_key(),
        _source_foreign_key(),
        _source_key_unique("uq_crm_contact_method_source_key"),
        sa.CheckConstraint(
            "kind IN ('email', 'phone')", name="ck_crm_contact_method_kind"
        ),
    )
    op.create_index(
        "ix_crm_contact_methods_kind_normalized",
        "crm_contact_methods",
        ["kind", "normalized_value"],
        unique=False,
    )

    op.create_table(
        "crm_contact_addresses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=True),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("address_type", sa.String(length=64), nullable=True),
        sa.Column("line1", sa.String(length=255), nullable=True),
        sa.Column("line2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=120), nullable=True),
        sa.Column("postal_code", sa.String(length=32), nullable=True),
        sa.Column("country", sa.String(length=120), nullable=True),
        sa.Column("formatted", sa.String(length=500), nullable=True),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=True),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        *_timestamps(),
        _contact_foreign_key(),
        _source_foreign_key(),
        _source_key_unique("uq_crm_contact_address_source_key"),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_crm_contact_address_latitude",
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_crm_contact_address_longitude",
        ),
    )

    op.create_table(
        "crm_contact_neighborhoods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=True),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=True),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=True),
        *_timestamps(),
        _contact_foreign_key(),
        _source_foreign_key(),
        _source_key_unique("uq_crm_contact_neighborhood_source_key"),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_crm_contact_neighborhood_latitude",
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_crm_contact_neighborhood_longitude",
        ),
    )

    op.create_table(
        "crm_contact_ownerships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=True),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("provider_actor_id", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        *_timestamps(),
        _contact_foreign_key(),
        _source_foreign_key(),
        _source_key_unique("uq_crm_contact_ownership_source_key"),
        sa.CheckConstraint(
            "role IN ('owner', 'assignee', 'collaborator')",
            name="ck_crm_contact_ownership_role",
        ),
    )

    op.create_table(
        "crm_contact_relationships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=True),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("relationship_type", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column(
            "related_source_contact_id", sa.String(length=24), nullable=True
        ),
        sa.Column("related_contact_id", sa.Integer(), nullable=True),
        *_timestamps(),
        _contact_foreign_key(),
        _source_foreign_key(),
        sa.ForeignKeyConstraint(
            ["related_contact_id"], ["crm_contacts.id"], ondelete="SET NULL"
        ),
        _source_key_unique("uq_crm_contact_relationship_source_key"),
    )

    op.create_table(
        "crm_contact_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=True),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("preference_key", sa.String(length=255), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False, server_default="{}"),
        *_timestamps(),
        _contact_foreign_key(),
        _source_foreign_key(),
        _source_key_unique("uq_crm_contact_preference_source_key"),
    )

    source_contact_hex_remainder = "source_contact_id"
    for hex_character in "0123456789abcdef":
        source_contact_hex_remainder = (
            f"replace({source_contact_hex_remainder}, '{hex_character}', '')"
        )

    op.create_table(
        "crm_contact_capture_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=False),
        sa.Column("bundle_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("capture_ordinal", sa.Integer(), nullable=False),
        sa.Column("source_contact_id", sa.String(length=24), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "capture_quality",
            sa.String(length=24),
            nullable=False,
            server_default="complete",
        ),
        sa.Column(
            "limitations_json", sa.Text(), nullable=False, server_default="[]"
        ),
        *_timestamps(),
        _contact_foreign_key(),
        _source_foreign_key(),
        sa.UniqueConstraint(
            "bundle_fingerprint",
            "capture_ordinal",
            name="uq_crm_contact_capture_bundle_ordinal",
        ),
        sa.UniqueConstraint(
            "bundle_fingerprint",
            "source_contact_id",
            name="uq_crm_contact_capture_bundle_source",
        ),
        sa.UniqueConstraint(
            "source_record_id", name="uq_crm_contact_capture_source_record"
        ),
        sa.CheckConstraint(
            "capture_ordinal > 0", name="ck_crm_contact_capture_ordinal"
        ),
        sa.CheckConstraint(
            "length(source_contact_id) = 24 "
            "AND source_contact_id = lower(source_contact_id) "
            f"AND {source_contact_hex_remainder} = ''",
            name="ck_crm_contact_capture_source_contact_id",
        ),
        sa.CheckConstraint(
            "capture_quality IN ('complete', 'partial', 'shell', 'error')",
            name="ck_crm_contact_capture_quality",
        ),
    )
    op.create_index(
        "ix_crm_contact_capture_lookup",
        "crm_contact_capture_positions",
        ["contact_id", "bundle_fingerprint"],
        unique=False,
    )

    op.create_table(
        "crm_contact_section_captures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("capture_position_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=False),
        sa.Column("section_name", sa.String(length=32), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "capture_quality",
            sa.String(length=24),
            nullable=False,
            server_default="complete",
        ),
        sa.Column(
            "is_empty", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "limitations_json", sa.Text(), nullable=False, server_default="[]"
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["capture_position_id"],
            ["crm_contact_capture_positions.id"],
            ondelete="CASCADE",
        ),
        _source_foreign_key(),
        sa.UniqueConstraint(
            "capture_position_id",
            "section_name",
            name="uq_crm_contact_position_section",
        ),
        sa.UniqueConstraint(
            "source_record_id", name="uq_crm_contact_section_source_record"
        ),
        sa.CheckConstraint(
            "section_name IN "
            "('timeline', 'opportunities', 'smart_plans', 'notes', "
            "'saved_searches', 'tasks_to_do', 'tasks_completed', 'tasks_archived')",
            name="ck_crm_contact_section_name",
        ),
        sa.CheckConstraint(
            "capture_quality IN ('complete', 'partial', 'shell', 'error')",
            name="ck_crm_contact_section_quality",
        ),
        sa.CheckConstraint(
            "row_count >= 0", name="ck_crm_contact_section_row_count"
        ),
    )
    op.create_index(
        "ix_crm_contact_section_lookup",
        "crm_contact_section_captures",
        ["capture_position_id", "section_name"],
        unique=False,
    )

    op.create_table(
        "crm_contact_timeline_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("source_event_key", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("actor_label", sa.String(length=255), nullable=True),
        sa.Column("channel", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "attributes_json", sa.Text(), nullable=False, server_default="{}"
        ),
        *_timestamps(),
        _contact_foreign_key(),
        _source_foreign_key(),
        sa.UniqueConstraint(
            "source_system",
            "source_event_key",
            name="uq_crm_contact_timeline_source_event",
        ),
        sa.UniqueConstraint(
            "source_record_id", name="uq_crm_contact_timeline_source_record"
        ),
    )
    op.create_index(
        "ix_crm_contact_timeline_order",
        "crm_contact_timeline_events",
        ["contact_id", "occurred_at", "id"],
        unique=False,
    )

    op.create_table(
        "crm_contact_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("actor_subject", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("after_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        _contact_foreign_key(),
    )
    op.create_index(
        "ix_crm_contact_audit_order",
        "crm_contact_audit_events",
        ["contact_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crm_contact_audit_order", table_name="crm_contact_audit_events"
    )
    op.drop_table("crm_contact_audit_events")
    op.drop_index(
        "ix_crm_contact_timeline_order", table_name="crm_contact_timeline_events"
    )
    op.drop_table("crm_contact_timeline_events")
    op.drop_index(
        "ix_crm_contact_section_lookup", table_name="crm_contact_section_captures"
    )
    op.drop_table("crm_contact_section_captures")
    op.drop_index(
        "ix_crm_contact_capture_lookup", table_name="crm_contact_capture_positions"
    )
    op.drop_table("crm_contact_capture_positions")
    op.drop_table("crm_contact_preferences")
    op.drop_table("crm_contact_relationships")
    op.drop_table("crm_contact_ownerships")
    op.drop_table("crm_contact_neighborhoods")
    op.drop_table("crm_contact_addresses")
    op.drop_index(
        "ix_crm_contact_methods_kind_normalized", table_name="crm_contact_methods"
    )
    op.drop_table("crm_contact_methods")
    op.drop_table("crm_contact_profiles")
