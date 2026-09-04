"""add approval-gated card campaigns and delivery evidence

Revision ID: 87a0d9b1e3f2
Revises: 86f9c8a0d2e1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "87a0d9b1e3f2"
down_revision: str | None = "86f9c8a0d2e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid(name: str = "id", *, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()") if name == "id" else None,
        nullable=nullable,
    )


def _now(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "card_provider_connections",
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column(
            "state",
            sa.String(24),
            server_default="disconnected",
            nullable=False,
        ),
        sa.Column("account_reference_hash", sa.String(64), nullable=True),
        sa.Column("display_label", sa.String(120), nullable=True),
        sa.Column("last_error_code", sa.String(120), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.PrimaryKeyConstraint("provider", name="pk_card_provider_connections"),
        sa.CheckConstraint(
            "state IN ('disconnected', 'connected', 'error')",
            name="ck_card_provider_connections_state",
        ),
        sa.CheckConstraint("version > 0", name="ck_card_provider_connections_version"),
        sa.CheckConstraint(
            "account_reference_hash IS NULL OR "
            "account_reference_hash ~ '^[0-9a-f]{64}$'",
            name="ck_card_provider_connections_account_hash",
        ),
    )

    op.create_table(
        "card_campaigns",
        _uuid(),
        _uuid("request_id"),
        sa.Column("draft_payload_hash", sa.String(64), nullable=False),
        sa.Column(
            "provider",
            sa.String(32),
            server_default="send_out_cards",
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column(
            "purpose",
            sa.String(32),
            server_default="celebrations",
            nullable=False,
        ),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("include_birthdays", sa.Boolean(), nullable=False),
        sa.Column("include_home_anniversaries", sa.Boolean(), nullable=False),
        _uuid("audience_ref"),
        sa.Column("audience_checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("default_birthday_message", sa.Text(), nullable=False),
        sa.Column("default_anniversary_message", sa.Text(), nullable=False),
        sa.Column("birthday_design_key", sa.String(120), nullable=False),
        sa.Column("anniversary_design_key", sa.String(120), nullable=False),
        sa.Column("estimated_cost_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("approved_by_actor", sa.String(120), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_version", sa.Integer(), nullable=True),
        _uuid("send_request_id", nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_card_campaigns"),
        sa.UniqueConstraint("request_id", name="uq_card_campaigns_request_id"),
        sa.UniqueConstraint(
            "send_request_id", name="uq_card_campaigns_send_request_id"
        ),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_card_campaigns_month"),
        sa.CheckConstraint(
            "include_birthdays OR include_home_anniversaries",
            name="ck_card_campaigns_selection",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'needs_addresses', 'needs_connection', "
            "'ready_for_review', 'approved', 'sending', 'sent', "
            "'partially_sent', 'failed', 'delivery_uncertain')",
            name="ck_card_campaigns_status",
        ),
        sa.CheckConstraint(
            "purpose = 'celebrations'", name="ck_card_campaigns_purpose"
        ),
        sa.CheckConstraint(
            "draft_payload_hash ~ '^[0-9a-f]{64}$' AND "
            "audience_checksum ~ '^[0-9a-f]{64}$'",
            name="ck_card_campaigns_checksum",
        ),
        sa.CheckConstraint(
            "estimated_cost_cents IS NULL OR estimated_cost_cents >= 0",
            name="ck_card_campaigns_cost",
        ),
        sa.CheckConstraint(
            "version > 0 AND (approved_version IS NULL OR "
            "(approved_version > 0 AND approved_version <= version))",
            name="ck_card_campaigns_version",
        ),
        sa.CheckConstraint(
            "((status IN ('draft', 'needs_addresses', 'needs_connection', "
            "'ready_for_review') AND approved_by_actor IS NULL AND "
            "approved_at IS NULL AND approved_version IS NULL AND "
            "send_request_id IS NULL) OR "
            "(status IN ('approved', 'sending', 'sent', 'partially_sent', "
            "'failed', 'delivery_uncertain') AND approved_by_actor IS NOT NULL "
            "AND approved_at IS NOT NULL AND approved_version IS NOT NULL AND "
            "send_request_id IS NOT NULL))",
            name="ck_card_campaigns_approval_shape",
        ),
    )
    op.create_index(
        "ix_card_campaigns_status_created",
        "card_campaigns",
        ["status", "created_at", "id"],
    )

    op.create_table(
        "card_campaign_recipients",
        _uuid(),
        _uuid("campaign_id"),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("celebration_kind", sa.String(32), nullable=False),
        sa.Column("celebration_month", sa.Integer(), nullable=False),
        sa.Column("celebration_day", sa.Integer(), nullable=False),
        sa.Column("celebration_year", sa.Integer(), nullable=True),
        sa.Column("celebration_year_quality", sa.String(24), nullable=False),
        sa.Column("celebration_origin", sa.String(24), nullable=False),
        sa.Column("display_name_snapshot", sa.String(255), nullable=False),
        sa.Column("message_snapshot", sa.Text(), nullable=False),
        sa.Column("design_key_snapshot", sa.String(120), nullable=False),
        sa.Column("address_status", sa.String(24), nullable=False),
        sa.Column("address_id", sa.Integer(), nullable=True),
        sa.Column("address_snapshot_json", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("excluded", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("exclusion_reason", sa.String(500), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_card_campaign_recipients"),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["card_campaigns.id"],
            name="fk_card_campaign_recipients_campaign",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["crm_contacts.id"],
            name="fk_card_campaign_recipients_contact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["address_id"],
            ["crm_contact_addresses.id"],
            name="fk_card_campaign_recipients_address",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "contact_id",
            "celebration_kind",
            name="uq_card_campaign_recipients_contact_kind",
        ),
        sa.UniqueConstraint(
            "id",
            "campaign_id",
            name="uq_card_campaign_recipients_id_campaign",
        ),
        sa.CheckConstraint(
            "celebration_kind IN ('birthday', 'home_anniversary') AND "
            "celebration_month BETWEEN 1 AND 12 AND "
            "celebration_day BETWEEN 1 AND 31 AND "
            "celebration_year_quality IN "
            "('verified', 'yearless', 'sentinel', 'unknown') AND "
            "celebration_origin IN ('internal_crm', 'recovered')",
            name="ck_card_campaign_recipients_celebration",
        ),
        sa.CheckConstraint(
            "address_status IN ('ready', 'missing') AND "
            "((address_status = 'ready' AND address_id IS NOT NULL AND "
            "address_snapshot_json IS NOT NULL) OR "
            "(address_status = 'missing' AND address_id IS NULL AND "
            "address_snapshot_json IS NULL))",
            name="ck_card_campaign_recipients_address_shape",
        ),
        sa.CheckConstraint(
            "address_snapshot_json IS NULL OR "
            "(address_snapshot_json IS JSON OBJECT WITH UNIQUE KEYS AND "
            "octet_length(address_snapshot_json) <= 4096)",
            name="ck_card_campaign_recipients_address_json",
        ),
        sa.CheckConstraint(
            "((excluded AND exclusion_reason IS NOT NULL) OR "
            "(NOT excluded AND exclusion_reason IS NULL))",
            name="ck_card_campaign_recipients_exclusion_shape",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_card_campaign_recipients_content_hash",
        ),
    )
    op.create_index(
        "ix_card_campaign_recipients_campaign_status",
        "card_campaign_recipients",
        ["campaign_id", "excluded", "address_status", "id"],
    )

    op.create_table(
        "card_delivery_attempts",
        _uuid(),
        _uuid("campaign_id"),
        _uuid("recipient_id"),
        _uuid("request_id"),
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        _uuid("provider_idempotency_key"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("intended_by_actor", sa.String(120), nullable=False),
        _now("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_card_delivery_attempts"),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["card_campaigns.id"],
            name="fk_card_delivery_attempts_campaign",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id", "campaign_id"],
            ["card_campaign_recipients.id", "card_campaign_recipients.campaign_id"],
            name="fk_card_delivery_attempts_recipient_campaign",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "recipient_id",
            "request_id",
            name="uq_card_delivery_attempts_recipient_request",
        ),
        sa.UniqueConstraint(
            "provider_idempotency_key",
            name="uq_card_delivery_attempts_provider_key",
        ),
        sa.UniqueConstraint(
            "id",
            "campaign_id",
            "recipient_id",
            name="uq_card_delivery_attempts_identity",
        ),
        sa.CheckConstraint(
            "attempt_number > 0", name="ck_card_delivery_attempts_number"
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_card_delivery_attempts_content_hash",
        ),
    )
    op.create_index(
        "ix_card_delivery_attempts_campaign_created",
        "card_delivery_attempts",
        ["campaign_id", "created_at", "id"],
    )

    op.create_table(
        "card_provider_receipts",
        _uuid(),
        _uuid("attempt_id"),
        _uuid("campaign_id"),
        _uuid("recipient_id"),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("provider_receipt_id", sa.String(255), nullable=True),
        sa.Column("provider_receipt_hash", sa.String(64), nullable=True),
        sa.Column("provider_status", sa.String(64), nullable=False),
        sa.Column("detail_code", sa.String(120), nullable=True),
        sa.Column("details_json", sa.Text(), server_default="{}", nullable=False),
        _now("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_card_provider_receipts"),
        sa.ForeignKeyConstraint(
            ["attempt_id", "campaign_id", "recipient_id"],
            [
                "card_delivery_attempts.id",
                "card_delivery_attempts.campaign_id",
                "card_delivery_attempts.recipient_id",
            ],
            name="fk_card_provider_receipts_attempt_identity",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("attempt_id", name="uq_card_provider_receipts_attempt"),
        sa.CheckConstraint(
            "outcome IN ('confirmed', 'rejected', 'ambiguous')",
            name="ck_card_provider_receipts_outcome",
        ),
        sa.CheckConstraint(
            "((provider_receipt_id IS NULL AND provider_receipt_hash IS NULL) OR "
            "(provider_receipt_id IS NOT NULL AND provider_receipt_hash ~ "
            "'^[0-9a-f]{64}$')) AND "
            "(outcome <> 'confirmed' OR provider_receipt_id IS NOT NULL)",
            name="ck_card_provider_receipts_provider_reference",
        ),
        sa.CheckConstraint(
            "details_json IS JSON OBJECT WITH UNIQUE KEYS AND "
            "octet_length(details_json) <= 4096",
            name="ck_card_provider_receipts_details_json",
        ),
    )
    op.create_index(
        "uq_card_provider_receipts_provider_reference",
        "card_provider_receipts",
        ["provider", "provider_receipt_hash"],
        unique=True,
        postgresql_where=sa.text("provider_receipt_hash IS NOT NULL"),
    )
    op.create_index(
        "ix_card_provider_receipts_campaign_created",
        "card_provider_receipts",
        ["campaign_id", "created_at", "id"],
    )

    op.execute(
        sa.text(
            "CREATE FUNCTION card_campaign_reject_append_only_mutation() "
            "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
            "'card campaign evidence is append-only'; END; $$"
        )
    )
    for table in ("card_delivery_attempts", "card_provider_receipts"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE "
                f"ON {table} FOR EACH ROW EXECUTE FUNCTION "
                "card_campaign_reject_append_only_mutation()"
            )
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "LOCK TABLE card_provider_receipts, card_delivery_attempts, "
            "card_campaign_recipients, card_campaigns, card_provider_connections "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM card_campaigns LIMIT 1) OR "
            "EXISTS (SELECT 1 FROM card_provider_connections LIMIT 1) THEN "
            "RAISE EXCEPTION 'revision 87 downgrade refused: card campaign "
            "evidence exists'; END IF; END $$;"
        )
    )
    for table in ("card_provider_receipts", "card_delivery_attempts"):
        op.execute(sa.text(f"DROP TRIGGER trg_{table}_append_only ON {table}"))
    op.execute(sa.text("DROP FUNCTION card_campaign_reject_append_only_mutation()"))
    op.drop_index(
        "ix_card_provider_receipts_campaign_created",
        table_name="card_provider_receipts",
    )
    op.drop_index(
        "uq_card_provider_receipts_provider_reference",
        table_name="card_provider_receipts",
    )
    op.drop_table("card_provider_receipts")
    op.drop_index(
        "ix_card_delivery_attempts_campaign_created",
        table_name="card_delivery_attempts",
    )
    op.drop_table("card_delivery_attempts")
    op.drop_index(
        "ix_card_campaign_recipients_campaign_status",
        table_name="card_campaign_recipients",
    )
    op.drop_table("card_campaign_recipients")
    op.drop_index("ix_card_campaigns_status_created", table_name="card_campaigns")
    op.drop_table("card_campaigns")
    op.drop_table("card_provider_connections")
