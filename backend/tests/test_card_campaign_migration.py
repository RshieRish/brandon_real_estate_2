from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from tests.gmail_task_postgres import migrated_test_database

REVISION = "87a0d9b1e3f2"
DOWN_REVISION = "86f9c8a0d2e1"
TABLES = {
    "card_provider_connections",
    "card_campaigns",
    "card_campaign_recipients",
    "card_delivery_attempts",
    "card_provider_receipts",
}


def _backend_root() -> Path:
    return Path(__file__).parents[1]


def _load_revision():
    path = (
        _backend_root() / "alembic" / "versions" / "87a0d9b1e3f2_add_card_campaigns.py"
    )
    assert path.is_file(), f"missing migration: {path.name}"
    spec = importlib.util.spec_from_file_location("card_campaign_revision_87", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scripts() -> ScriptDirectory:
    config = Config(str(_backend_root() / "alembic.ini"))
    config.set_main_option("script_location", str(_backend_root() / "alembic"))
    return ScriptDirectory.from_config(config)


def _render(function_name: str) -> str:
    revision = _load_revision()
    output = StringIO()
    revision.op = Operations(
        MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": output},
        )
    )
    getattr(revision, function_name)()
    return " ".join(output.getvalue().split())


def test_revision_87_is_the_single_serial_head() -> None:
    revision = _load_revision()
    scripts = _scripts()

    assert revision.revision == REVISION
    assert revision.down_revision == DOWN_REVISION
    assert revision.branch_labels is None
    assert revision.depends_on is None
    assert scripts.get_heads() == [REVISION]
    assert scripts.get_revision(REVISION).down_revision == DOWN_REVISION


def test_revision_87_defines_guarded_campaign_delivery_evidence() -> None:
    sql = _render("upgrade")

    for table in TABLES:
        assert f"CREATE TABLE {table}" in sql
    assert "uq_card_campaigns_request_id" in sql
    assert "uq_card_campaign_recipients_contact_kind" in sql
    assert "uq_card_delivery_attempts_recipient_request" in sql
    assert "uq_card_provider_receipts_attempt" in sql
    assert "card_campaign_reject_append_only_mutation" in sql
    assert "trg_card_delivery_attempts_append_only" in sql
    assert "trg_card_provider_receipts_append_only" in sql
    assert "SEND_OUT_CARDS_API_TOKEN" not in sql


def test_revision_87_upgrades_real_postgresql_and_enforces_append_only() -> None:
    with migrated_test_database(REVISION) as (_url, engine):
        inspector = sa.inspect(engine)
        assert TABLES <= set(inspector.get_table_names())
        campaign_checks = {
            item["name"] for item in inspector.get_check_constraints("card_campaigns")
        }
        assert {
            "ck_card_campaigns_status",
            "ck_card_campaigns_selection",
            "ck_card_campaigns_approval_shape",
            "ck_card_campaigns_checksum",
        } <= campaign_checks
        recipient_uniques = {
            item["name"]
            for item in inspector.get_unique_constraints("card_campaign_recipients")
        }
        assert "uq_card_campaign_recipients_contact_kind" in recipient_uniques

        with engine.begin() as connection:
            contact_id = connection.execute(
                sa.text(
                    "INSERT INTO crm_contacts "
                    "(first_name, last_name, stage) VALUES "
                    "('Append', 'Only', 'lead') RETURNING id"
                )
            ).scalar_one()
            campaign_id = connection.execute(
                sa.text(
                    "INSERT INTO card_campaigns "
                    "(request_id, draft_payload_hash, provider, title, purpose, "
                    "month, include_birthdays, include_home_anniversaries, "
                    "audience_ref, audience_checksum, status, "
                    "default_birthday_message, default_anniversary_message, "
                    "birthday_design_key, anniversary_design_key) VALUES "
                    "(gen_random_uuid(), :hash, 'send_out_cards', 'September', "
                    "'celebrations', 9, true, true, gen_random_uuid(), :hash, "
                    "'ready_for_review', 'Happy birthday', 'Happy anniversary', "
                    "'birthday-classic', 'anniversary-classic') RETURNING id"
                ),
                {"hash": "a" * 64},
            ).scalar_one()
            recipient_id = connection.execute(
                sa.text(
                    "INSERT INTO card_campaign_recipients "
                    "(campaign_id, contact_id, celebration_kind, "
                    "celebration_month, celebration_day, celebration_year_quality, "
                    "celebration_origin, display_name_snapshot, message_snapshot, "
                    "design_key_snapshot, address_status, address_id, "
                    "address_snapshot_json, content_hash) VALUES "
                    "(:campaign, :contact, 'birthday', 9, 8, 'yearless', "
                    "'recovered', 'Append Only', 'Happy birthday', "
                    "'birthday-classic', 'missing', NULL, NULL, :hash) RETURNING id"
                ),
                {"campaign": campaign_id, "contact": contact_id, "hash": "b" * 64},
            ).scalar_one()
            attempt_id = connection.execute(
                sa.text(
                    "INSERT INTO card_delivery_attempts "
                    "(campaign_id, recipient_id, request_id, attempt_number, "
                    "provider, provider_idempotency_key, content_hash, "
                    "intended_by_actor) VALUES "
                    "(:campaign, :recipient, gen_random_uuid(), 1, "
                    "'send_out_cards', gen_random_uuid(), :hash, 'admin:test') "
                    "RETURNING id"
                ),
                {"campaign": campaign_id, "recipient": recipient_id, "hash": "b" * 64},
            ).scalar_one()
            receipt_id = connection.execute(
                sa.text(
                    "INSERT INTO card_provider_receipts "
                    "(attempt_id, campaign_id, recipient_id, provider, outcome, "
                    "provider_status, details_json) VALUES "
                    "(:attempt, :campaign, :recipient, 'send_out_cards', "
                    "'ambiguous', 'timeout', '{}') RETURNING id"
                ),
                {
                    "attempt": attempt_id,
                    "campaign": campaign_id,
                    "recipient": recipient_id,
                },
            ).scalar_one()

        for table, row_id in (
            ("card_delivery_attempts", attempt_id),
            ("card_provider_receipts", receipt_id),
        ):
            with engine.begin() as connection:
                try:
                    connection.execute(
                        sa.text(
                            f"UPDATE {table} SET created_at = now() WHERE id = :id"
                        ),
                        {"id": row_id},
                    )
                except sa.exc.DBAPIError as exc:
                    assert "append-only" in str(exc.orig)
                else:
                    raise AssertionError(f"{table} accepted an update")


def test_revision_87_downgrade_refuses_to_discard_campaign_evidence() -> None:
    sql = _render("downgrade")
    assert "IN ACCESS EXCLUSIVE MODE" in sql
    assert "revision 87 downgrade refused" in sql
    assert sql.index("revision 87 downgrade refused") < sql.index(
        "DROP TABLE card_provider_receipts"
    )
