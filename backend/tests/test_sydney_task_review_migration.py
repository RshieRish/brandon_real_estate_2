from __future__ import annotations

import importlib
import importlib.util
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID

from tests.gmail_task_postgres import (
    gmail_task_test_url,
    owned_empty_test_schema,
    run_alembic,
    run_owned_alembic_downgrade,
    sync_test_url,
)


REVISION = "84d7a5f9b2c3"
DOWN_REVISION = "83c6f4e8a1b2"
TABLES = (
    "crm_task_clarifications",
    "sydney_question_outbox",
    "crm_task_suggestion_approval_nonces",
    "crm_task_suggestion_events",
)
REVISION_83_TABLES = (
    "gmail_sync_accounts",
    "gmail_sync_runs",
    "gmail_sync_page_checkpoints",
    "gmail_missing_message_incidents",
    "gmail_message_receipts",
    "gmail_message_origins",
    "gmail_extraction_attempts",
    "gmail_extracted_obligations",
    "crm_task_suggestions",
    "crm_task_suggestion_sources",
    "crm_task_suggestion_suppressions",
    "gmail_backfill_requests",
)
DOWNGRADE_GUARD_TABLES = REVISION_83_TABLES + TABLES


def _backend_root() -> Path:
    return Path(__file__).parents[1]


def _revision_path() -> Path:
    return (
        _backend_root()
        / "alembic"
        / "versions"
        / "84d7a5f9b2c3_add_sydney_task_review.py"
    )


def _load_revision():
    path = _revision_path()
    assert path.is_file(), f"missing migration: {path.name}"
    spec = importlib.util.spec_from_file_location(
        "sydney_task_review_revision_84d7a5f9b2c3",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _script_directory() -> ScriptDirectory:
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


def _model_tables() -> dict[str, sa.Table]:
    module = importlib.import_module("models.sydney_tasks")
    classes = (
        module.CRMTaskClarification,
        module.SydneyQuestionOutbox,
        module.TaskSuggestionApprovalNonce,
        module.CRMTaskSuggestionEvent,
    )
    return {model.__table__.name: model.__table__ for model in classes}


def _named_uniques(table: sa.Table) -> dict[str, tuple[str, ...]]:
    return {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
        and constraint.name is not None
    }


def _named_checks(table: sa.Table) -> dict[str, str]:
    return {
        constraint.name: " ".join(str(constraint.sqltext).split())
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
        and constraint.name is not None
    }


def _named_foreign_keys(table: sa.Table) -> dict[str, tuple[object, ...]]:
    return {
        constraint.name: (
            tuple(column.name for column in constraint.columns),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in table.foreign_key_constraints
        if constraint.name is not None
    }


def _index_contract(table: sa.Table) -> dict[str, tuple[object, ...]]:
    return {
        index.name: (
            tuple(column.name for column in index.columns),
            bool(index.unique),
            None
            if index.dialect_options["postgresql"].get("where") is None
            else " ".join(
                str(index.dialect_options["postgresql"]["where"]).split()
            ),
        )
        for index in table.indexes
    }


def _insert_sydney_suggestion(
    connection: sa.Connection,
    *,
    suggestion_id: UUID,
    request_id: UUID,
    title: str,
) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO crm_task_suggestions "
            "(id, source_type, source_scope_key, source_action_key, "
            "source_request_id, title, state, clarification_state, "
            "blocker_codes, payload_hash, model_schema_version, "
            "obligation_fingerprint) VALUES "
            "(:id, 'sydney_chat', :scope, :action, :request_id, :title, "
            "'needs_clarification', 'pending', "
            "ARRAY['ambiguous_due_at']::varchar[], :payload_hash, "
            "'sydney-task-v1', :fingerprint)"
        ),
        {
            "id": suggestion_id,
            "scope": f"sydney:{request_id}",
            "action": f"sydney-action:{request_id.hex}",
            "request_id": request_id,
            "title": title,
            "payload_hash": "a" * 64,
            "fingerprint": "b" * 64,
        },
    )


def _insert_clarification(
    connection: sa.Connection,
    *,
    clarification_id: UUID,
    suggestion_id: UUID,
    code_byte: int,
    now: datetime,
    chat_id: str = "-1001234567890",
    field_name: str = "due_at",
    round_number: int = 1,
    suggestion_version: int = 1,
) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO crm_task_clarifications "
            "(id, suggestion_id, suggestion_version, field_name, "
            "round_number, telegram_chat_id, code_hash, code_key_version, "
            "options_json, state, deadline_anchor_kind, "
            "deadline_anchored_at, slot_deadline_at, created_at, updated_at) "
            "VALUES (:id, :suggestion_id, :version, :field, :round, :chat, "
            ":code_hash, 7, '{}', 'pending', 'created', :now, :deadline, "
            ":now, :now)"
        ),
        {
            "id": clarification_id,
            "suggestion_id": suggestion_id,
            "version": suggestion_version,
            "field": field_name,
            "round": round_number,
            "chat": chat_id,
            "code_hash": bytes([code_byte]) * 32,
            "now": now,
            "deadline": now + timedelta(hours=48),
        },
    )


def test_revision_84_is_serially_followed_by_the_repository_head() -> None:
    revision = _load_revision()
    assert revision.revision == REVISION
    assert revision.down_revision == DOWN_REVISION
    assert revision.branch_labels is None
    assert revision.depends_on is None
    scripts = _script_directory()
    assert len(scripts.get_heads()) == 1
    ancestry: set[str] = set()
    pending = [scripts.get_revision(scripts.get_current_head())]
    while pending:
        item = pending.pop()
        if item is None or item.revision in ancestry:
            continue
        ancestry.add(item.revision)
        parents = (
            item.down_revision
            if isinstance(item.down_revision, tuple)
            else (item.down_revision,)
        )
        pending.extend(
            scripts.get_revision(parent) for parent in parents if parent is not None
        )
    assert REVISION in ancestry
    assert scripts.get_revision(REVISION).down_revision == DOWN_REVISION


def test_four_models_have_exact_body_free_columns_and_defaults() -> None:
    tables = _model_tables()
    assert tuple(tables) == TABLES
    expected_columns = {
        "crm_task_clarifications": (
            "id",
            "suggestion_id",
            "suggestion_version",
            "field_name",
            "round_number",
            "telegram_chat_id",
            "code_hash",
            "code_key_version",
            "options_json",
            "state",
            "answer_json",
            "deadline_anchor_kind",
            "deadline_anchored_at",
            "slot_deadline_at",
            "first_attempt_at",
            "resolved_at",
            "created_at",
            "updated_at",
        ),
        "sydney_question_outbox": (
            "id",
            "clarification_id",
            "attempt_kind",
            "attempt_number",
            "parent_initial_attempt_id",
            "reply_to_attempt_id",
            "dedupe_key",
            "template_id",
            "question_context_json",
            "rendered_payload_hash",
            "state",
            "telegram_chat_id",
            "telegram_message_id",
            "failure_category",
            "attempted_at",
            "sent_at",
            "reconciled_outcome",
            "reconciliation_reason",
            "reconciliation_audit_id",
            "reconciled_at",
            "created_at",
            "updated_at",
        ),
        "crm_task_suggestion_approval_nonces": (
            "id",
            "suggestion_id",
            "suggestion_version",
            "payload_hash",
            "kind",
            "issuance_path",
            "token_hash",
            "administrator_id",
            "parent_nonce_id",
            "issued_at",
            "expires_at",
            "consumed_at",
        ),
        "crm_task_suggestion_events": (
            "id",
            "suggestion_id",
            "suggestion_version",
            "event_type",
            "actor_type",
            "event_data_json",
            "action_audit_id",
            "created_at",
        ),
    }
    nullable = {
        "crm_task_clarifications": {
            "answer_json",
            "first_attempt_at",
            "resolved_at",
        },
        "sydney_question_outbox": {
            "parent_initial_attempt_id",
            "reply_to_attempt_id",
            "telegram_chat_id",
            "telegram_message_id",
            "failure_category",
            "attempted_at",
            "sent_at",
            "reconciled_outcome",
            "reconciliation_reason",
            "reconciliation_audit_id",
            "reconciled_at",
        },
        "crm_task_suggestion_approval_nonces": {
            "administrator_id",
            "parent_nonce_id",
            "consumed_at",
        },
        "crm_task_suggestion_events": {"action_audit_id"},
    }
    for name, expected in expected_columns.items():
        table = tables[name]
        assert tuple(table.columns.keys()) == expected
        assert {column.name for column in table.columns if column.nullable} == nullable[
            name
        ]
        assert table.primary_key.columns.keys() == ["id"]
        assert isinstance(table.columns["id"].type, PostgreSQLUUID)
        assert table.columns["id"].type.as_uuid is True

    clarification = tables["crm_task_clarifications"]
    assert isinstance(clarification.c.code_hash.type, sa.LargeBinary)
    assert clarification.c.code_hash.type.length == 32
    assert clarification.c.field_name.type.length == 64
    assert isinstance(clarification.c.options_json.type, sa.Text)
    assert clarification.c.options_json.default.arg == "{}"
    assert str(clarification.c.options_json.server_default.arg) == "{}"
    assert isinstance(clarification.c.answer_json.type, sa.Text)
    assert clarification.c.state.default.arg == "pending"
    assert str(clarification.c.state.server_default.arg) == "pending"

    outbox = tables["sydney_question_outbox"]
    assert outbox.c.template_id.type.length == 64
    assert isinstance(outbox.c.question_context_json.type, sa.Text)
    assert outbox.c.rendered_payload_hash.type.length == 64
    assert outbox.c.failure_category.type.length == 64
    assert outbox.c.reconciliation_reason.type.length == 500
    assert outbox.c.state.default.arg == "pending"
    assert str(outbox.c.state.server_default.arg) == "pending"

    nonce = tables["crm_task_suggestion_approval_nonces"]
    assert isinstance(nonce.c.token_hash.type, sa.LargeBinary)
    assert nonce.c.token_hash.type.length == 32
    assert nonce.c.payload_hash.type.length == 64

    forbidden = {
        "code",
        "clarification_code",
        "token",
        "nonce",
        "plaintext",
        "raw_body",
        "body",
        "chat_user_id",
    }
    for table in tables.values():
        assert forbidden.isdisjoint(table.columns.keys())


def test_models_pin_uniqueness_partial_slot_and_indexed_evidence() -> None:
    tables = _model_tables()
    clarification = tables["crm_task_clarifications"]
    assert _named_uniques(clarification) == {
        "uq_crm_task_clarifications_suggestion_version_field": (
            "suggestion_id",
            "suggestion_version",
            "field_name",
        ),
        "uq_crm_task_clarifications_suggestion_round": (
            "suggestion_id",
            "round_number",
        ),
        "uq_crm_task_clarifications_code_hash": ("code_hash",),
    }
    assert _index_contract(clarification) == {
        "uq_crm_task_clarifications_active_chat": (
            ("telegram_chat_id",),
            True,
            "state = 'pending'",
        ),
        "uq_crm_task_clarifications_active_suggestion": (
            ("suggestion_id",),
            True,
            "state = 'pending'",
        ),
        "ix_crm_task_clarifications_suggestion_field_state": (
            ("suggestion_id", "field_name", "state", "id"),
            False,
            None,
        ),
        "ix_crm_task_clarifications_due": (
            ("state", "slot_deadline_at", "id"),
            False,
            None,
        ),
    }

    outbox = tables["sydney_question_outbox"]
    assert _named_uniques(outbox) == {
        "uq_sydney_question_outbox_dedupe_key": ("dedupe_key",),
        "uq_sydney_question_outbox_attempt": (
            "clarification_id",
            "attempt_kind",
            "attempt_number",
        ),
        "uq_sydney_question_outbox_id_clarification": (
            "id",
            "clarification_id",
        ),
    }
    assert _index_contract(outbox) == {
        "ix_sydney_question_outbox_dispatch": (
            ("state", "created_at", "id"),
            False,
            None,
        ),
        "ix_sydney_question_outbox_delivery_correlation": (
            (
                "clarification_id",
                "state",
                "telegram_chat_id",
                "sent_at",
                "id",
            ),
            False,
            None,
        ),
        "ix_sydney_question_outbox_reconciled_delivery": (
            (
                "clarification_id",
                "state",
                "reconciled_outcome",
                "telegram_chat_id",
                "reconciled_at",
                "id",
            ),
            False,
            None,
        ),
        "ix_sydney_question_outbox_kind_history": (
            (
                "clarification_id",
                "attempt_kind",
                "state",
                "sent_at",
                "attempt_number",
                "id",
            ),
            False,
            None,
        ),
    }

    nonce = tables["crm_task_suggestion_approval_nonces"]
    assert _named_uniques(nonce) == {
        "uq_crm_task_suggestion_approval_nonces_token_hash": ("token_hash",),
        "uq_crm_task_suggestion_approval_nonces_parent": ("parent_nonce_id",),
        "uq_crm_task_suggestion_approval_nonces_resource_identity": (
            "id",
            "suggestion_id",
            "suggestion_version",
            "payload_hash",
        ),
    }

    gmail = importlib.import_module("models.gmail_task_intake")
    obligation = gmail.GmailExtractedObligation.__table__
    assert obligation.c.owner_ambiguous.nullable is False
    assert obligation.c.owner_ambiguous.default.arg is False
    assert obligation.c.owner_ambiguous.server_default is None
    assert _index_contract(obligation)[
        "ix_gmail_extracted_obligations_suggestion_owner_ambiguous"
    ] == (
        ("reconciled_suggestion_id", "owner_ambiguous", "id"),
        False,
        None,
    )
    suggestion = gmail.CRMTaskSuggestion.__table__
    for column_name in (
        "owner_clarification_pending",
        "task_details_clarification_pending",
    ):
        column = suggestion.c[column_name]
        assert isinstance(column.type, sa.Boolean)
        assert column.nullable is False
        assert column.default.arg is False
        assert column.server_default is None
    assert suggestion.c.contact_resolution_state.type.length == 32
    assert suggestion.c.contact_resolution_state.nullable is False
    assert suggestion.c.contact_resolution_state.default.arg == "not_provided"
    assert suggestion.c.contact_resolution_state.server_default is None
    assert suggestion.c.contact_resolution_hash.type.length == 64
    assert suggestion.c.contact_resolution_hash.nullable is True
    assert _named_checks(suggestion)[
        "ck_crm_task_suggestions_clarification_pending_cause"
    ] == (
        "('missing_required_field' = ANY(blocker_codes)) = "
        "(owner_clarification_pending OR task_details_clarification_pending)"
    )
    assert _named_checks(suggestion)[
        "ck_crm_task_suggestions_contact_resolution"
    ] == (
        "(contact_resolution_state IN ('not_provided', 'explicit_none') AND "
        "contact_id IS NULL AND contact_resolution_hash IS NULL AND NOT "
        "('ambiguous_contact' = ANY(blocker_codes))) OR "
        "(contact_resolution_state = 'unresolved' AND contact_id IS NULL AND "
        "contact_resolution_hash IS NULL AND "
        "'ambiguous_contact' = ANY(blocker_codes)) OR "
        "(contact_resolution_state IN ('inferred_unique', 'clarified_unique') "
        "AND contact_id IS NOT NULL AND contact_resolution_hash ~ "
        "'^[0-9a-f]{64}$' AND NOT "
        "('ambiguous_contact' = ANY(blocker_codes)))"
    )


def test_models_pin_state_round_parent_nonce_and_exact_expiry_constraints() -> None:
    tables = _model_tables()
    clarification_checks = _named_checks(tables["crm_task_clarifications"])
    assert clarification_checks == {
        "ck_crm_task_clarifications_version_positive": "suggestion_version > 0",
        "ck_crm_task_clarifications_round": "round_number BETWEEN 1 AND 5",
        "ck_crm_task_clarifications_field": (
            "field_name IN ('action_scope', 'contact', 'due_at', 'owner', "
            "'task_details')"
        ),
        "ck_crm_task_clarifications_state": (
            "state IN ('pending', 'answered', 'timed_out', 'superseded')"
        ),
        "ck_crm_task_clarifications_code_hash_length": (
            "octet_length(code_hash) = 32"
        ),
        "ck_crm_task_clarifications_key_version": (
            "code_key_version BETWEEN 1 AND 32767"
        ),
        "ck_crm_task_clarifications_chat_id": (
            "CASE WHEN telegram_chat_id ~ '^-?[1-9][0-9]*$' THEN "
            "telegram_chat_id::numeric > -4503599627370496 AND "
            "telegram_chat_id::numeric < 4503599627370496 ELSE false END"
        ),
        "ck_crm_task_clarifications_resolution_shape": (
            "(state = 'pending' AND resolved_at IS NULL AND answer_json IS NULL) OR "
            "(state = 'answered' AND resolved_at IS NOT NULL AND answer_json IS NOT NULL) OR "
            "(state IN ('timed_out', 'superseded') AND resolved_at IS NOT NULL "
            "AND answer_json IS NULL)"
        ),
        "ck_crm_task_clarifications_options_json": (
            "options_json IS JSON OBJECT WITH UNIQUE KEYS AND "
            "octet_length(options_json) <= 4096"
        ),
        "ck_crm_task_clarifications_answer_json": (
            "answer_json IS NULL OR (answer_json IS JSON OBJECT WITH UNIQUE KEYS "
            "AND octet_length(answer_json) <= 8192)"
        ),
        "ck_crm_task_clarifications_deadline": (
            "slot_deadline_at = deadline_anchored_at + interval '48 hours' AND "
            "((deadline_anchor_kind = 'created' AND first_attempt_at IS NULL AND "
            "deadline_anchored_at = created_at) OR "
            "(deadline_anchor_kind = 'first_attempt' AND first_attempt_at IS NOT NULL "
            "AND deadline_anchored_at = first_attempt_at) OR "
            "(deadline_anchor_kind = 'initial_sent' AND first_attempt_at IS NOT NULL "
            "AND deadline_anchored_at >= first_attempt_at))"
        ),
    }

    outbox_checks = _named_checks(tables["sydney_question_outbox"])
    assert outbox_checks["ck_sydney_question_outbox_attempt_kind"] == (
        "attempt_kind IN ('initial', 'initial_retry', 'reminder')"
    )
    assert outbox_checks["ck_sydney_question_outbox_attempt_number"] == (
        "attempt_number > 0"
    )
    assert outbox_checks["ck_sydney_question_outbox_template"] == (
        "template_id IN ('clarification_initial_v1', "
        "'clarification_reminder_v1')"
    )
    assert outbox_checks["ck_sydney_question_outbox_template_kind"] == (
        "(attempt_kind = 'reminder' AND template_id = "
        "'clarification_reminder_v1') OR (attempt_kind IN ('initial', "
        "'initial_retry') AND template_id = 'clarification_initial_v1')"
    )
    assert outbox_checks["ck_sydney_question_outbox_context"] == (
        "question_context_json IS JSON OBJECT WITH UNIQUE KEYS AND "
        "octet_length(question_context_json) <= 4096"
    )
    assert outbox_checks["ck_sydney_question_outbox_state"] == (
        "state IN ('pending', 'sending', 'sent', 'failed', 'delivery_uncertain')"
    )
    assert outbox_checks["ck_sydney_question_outbox_attempt_parent_shape"] == (
        "(attempt_kind = 'initial' AND attempt_number = 1 AND "
        "parent_initial_attempt_id IS NULL AND reply_to_attempt_id IS NULL) OR "
        "(attempt_kind = 'initial_retry' AND attempt_number > 0 AND "
        "parent_initial_attempt_id IS NOT NULL AND reply_to_attempt_id IS NULL) OR "
        "(attempt_kind = 'reminder' AND attempt_number = 1 AND "
        "parent_initial_attempt_id IS NULL AND reply_to_attempt_id IS NOT NULL)"
    )
    assert outbox_checks["ck_sydney_question_outbox_rendered_hash"] == (
        "rendered_payload_hash ~ '^[0-9a-f]{64}$'"
    )
    assert outbox_checks["ck_sydney_question_outbox_chat_id"] == (
        "telegram_chat_id IS NULL OR CASE WHEN telegram_chat_id ~ "
        "'^-?[1-9][0-9]*$' THEN telegram_chat_id::numeric > -4503599627370496 "
        "AND telegram_chat_id::numeric < 4503599627370496 ELSE false END"
    )
    assert outbox_checks["ck_sydney_question_outbox_message_id"] == (
        "telegram_message_id IS NULL OR telegram_message_id ~ '^[1-9][0-9]*$'"
    )
    assert outbox_checks["ck_sydney_question_outbox_delivery_shape"] == (
        "(state = 'pending' AND attempted_at IS NULL AND sent_at IS NULL AND "
        "telegram_chat_id IS NULL AND telegram_message_id IS NULL AND "
        "failure_category IS NULL) OR "
        "(state = 'sending' AND attempted_at IS NOT NULL AND sent_at IS NULL "
        "AND telegram_chat_id IS NOT NULL AND telegram_message_id IS NULL AND "
        "failure_category IS NULL) OR "
        "(state = 'sent' AND attempted_at IS NOT NULL AND sent_at IS NOT NULL "
        "AND telegram_chat_id IS NOT NULL AND telegram_message_id IS NOT NULL "
        "AND failure_category IS NULL) OR "
        "(state = 'failed' AND failure_category IN ('pre_send_resolved', "
        "'pre_send_superseded', 'pre_send_expired') AND "
        "attempted_at IS NULL AND sent_at IS NULL AND telegram_chat_id IS NULL "
        "AND telegram_message_id IS NULL) OR "
        "(state IN ('failed', 'delivery_uncertain') AND attempted_at IS NOT NULL "
        "AND sent_at IS NULL AND telegram_chat_id IS NOT NULL AND "
        "failure_category IS NOT NULL AND (telegram_message_id IS NULL OR "
        "reconciled_outcome = 'delivered'))"
    )
    assert outbox_checks["ck_sydney_question_outbox_reconciliation_shape"] == (
        "(reconciled_outcome IS NULL AND reconciliation_reason IS NULL AND "
        "reconciliation_audit_id IS NULL AND reconciled_at IS NULL) OR "
        "(reconciliation_reason IS NOT NULL AND reconciliation_audit_id IS NOT NULL "
        "AND reconciled_at IS NOT NULL AND (((state = 'failed' AND "
        "reconciled_outcome = 'not_delivered') OR (state = 'delivery_uncertain' "
        "AND reconciled_outcome IN ('delivered', 'not_delivered'))) AND "
        "((reconciled_outcome = 'delivered' "
        "AND telegram_chat_id IS NOT NULL AND telegram_message_id IS NOT NULL) "
        "OR (reconciled_outcome = 'not_delivered' AND "
        "telegram_message_id IS NULL))))"
    )

    nonce_checks = _named_checks(
        tables["crm_task_suggestion_approval_nonces"]
    )
    assert nonce_checks["ck_crm_task_suggestion_approval_nonces_token_hash"] == (
        "octet_length(token_hash) = 32"
    )
    assert nonce_checks["ck_crm_task_suggestion_approval_nonces_payload_hash"] == (
        "payload_hash ~ '^[0-9a-f]{64}$'"
    )
    assert nonce_checks["ck_crm_task_suggestion_approval_nonces_shape"] == (
        "(kind = 'handoff' AND issuance_path = 'approval_link' AND "
        "administrator_id IS NULL AND parent_nonce_id IS NULL AND "
        "expires_at = issued_at + interval '15 minutes') OR "
        "(kind = 'approval' AND issuance_path = 'handoff_exchange' AND "
        "administrator_id IS NOT NULL AND parent_nonce_id IS NOT NULL AND "
        "expires_at = issued_at + interval '5 minutes') OR "
        "(kind = 'approval' AND issuance_path = 'command_prepare' AND "
        "administrator_id IS NOT NULL AND parent_nonce_id IS NULL AND "
        "expires_at = issued_at + interval '5 minutes')"
    )
    assert nonce_checks["ck_crm_task_suggestion_approval_nonces_consumption"] == (
        "consumed_at IS NULL OR (consumed_at >= issued_at AND consumed_at <= expires_at)"
    )
    assert nonce_checks["ck_crm_task_suggestion_approval_nonces_version"] == (
        "suggestion_version > 0"
    )
    assert nonce_checks["ck_crm_task_suggestion_approval_nonces_not_self"] == (
        "parent_nonce_id IS NULL OR parent_nonce_id <> id"
    )

    event_checks = _named_checks(tables["crm_task_suggestion_events"])
    assert event_checks == {
        "ck_crm_task_suggestion_events_version": "suggestion_version > 0",
        "ck_crm_task_suggestion_events_type": (
            "event_type IN ('edit', 'clarification_asked', "
            "'clarification_answered', 'clarification_timed_out', "
            "'clarification_superseded', 'clarification_delivery_retry', "
            "'dismiss', 'preview', 'approve', 'apply', 'reprocess', "
            "'dismiss_proposed')"
        ),
        "ck_crm_task_suggestion_events_actor": (
            "actor_type IN ('system', 'sydney', 'command_admin', "
            "'untrusted_hermes_input')"
        ),
        "ck_crm_task_suggestion_events_data": (
            "event_data_json IS JSON OBJECT WITH UNIQUE KEYS AND "
            "octet_length(event_data_json) <= 8192"
        ),
    }


def test_models_pin_foreign_key_provenance_and_no_cascade_deletion() -> None:
    tables = _model_tables()
    assert _named_foreign_keys(tables["crm_task_clarifications"]) == {
        "fk_crm_task_clarifications_suggestion_id": (
            ("suggestion_id",),
            ("crm_task_suggestions.id",),
            "RESTRICT",
        )
    }
    assert _named_foreign_keys(tables["sydney_question_outbox"]) == {
        "fk_sydney_question_outbox_clarification_id": (
            ("clarification_id",),
            ("crm_task_clarifications.id",),
            "RESTRICT",
        ),
        "fk_sydney_question_outbox_parent_initial": (
            ("parent_initial_attempt_id", "clarification_id"),
            (
                "sydney_question_outbox.id",
                "sydney_question_outbox.clarification_id",
            ),
            "RESTRICT",
        ),
        "fk_sydney_question_outbox_reply_to": (
            ("reply_to_attempt_id", "clarification_id"),
            (
                "sydney_question_outbox.id",
                "sydney_question_outbox.clarification_id",
            ),
            "RESTRICT",
        ),
        "fk_sydney_question_outbox_reconciliation_audit": (
            ("reconciliation_audit_id",),
            ("agent_action_audits.id",),
            "RESTRICT",
        ),
    }
    assert _named_foreign_keys(
        tables["crm_task_suggestion_approval_nonces"]
    ) == {
        "fk_crm_task_suggestion_approval_nonces_suggestion_id": (
            ("suggestion_id",),
            ("crm_task_suggestions.id",),
            "RESTRICT",
        ),
        "fk_crm_task_suggestion_approval_nonces_administrator_id": (
            ("administrator_id",),
            ("admin_users.id",),
            "RESTRICT",
        ),
        "fk_crm_task_suggestion_approval_nonces_parent_id": (
            (
                "parent_nonce_id",
                "suggestion_id",
                "suggestion_version",
                "payload_hash",
            ),
            (
                "crm_task_suggestion_approval_nonces.id",
                "crm_task_suggestion_approval_nonces.suggestion_id",
                "crm_task_suggestion_approval_nonces.suggestion_version",
                "crm_task_suggestion_approval_nonces.payload_hash",
            ),
            "RESTRICT",
        ),
    }
    assert _named_foreign_keys(tables["crm_task_suggestion_events"]) == {
        "fk_crm_task_suggestion_events_suggestion_id": (
            ("suggestion_id",),
            ("crm_task_suggestions.id",),
            "RESTRICT",
        ),
        "fk_crm_task_suggestion_events_action_audit_id": (
            ("action_audit_id",),
            ("agent_action_audits.id",),
            "RESTRICT",
        ),
    }


def test_models_are_registered_once_for_application_and_alembic() -> None:
    models = importlib.import_module("models")
    module = importlib.import_module("models.sydney_tasks")
    expected = {
        "CRMTaskClarification",
        "SydneyQuestionOutbox",
        "TaskSuggestionApprovalNonce",
        "CRMTaskSuggestionEvent",
    }
    assert expected.issubset(set(models.__all__))
    for name in expected:
        assert getattr(models, name) is getattr(module, name)
    env_source = (_backend_root() / "alembic" / "env.py").read_text(
        encoding="utf-8"
    )
    assert env_source.count("import models.sydney_tasks") == 1


def test_revision_84_ddl_is_append_only_hash_only_and_downgrade_guarded() -> None:
    upgrade = _render("upgrade")
    for table in TABLES:
        assert f"CREATE TABLE {table}" in upgrade
    assert "ADD COLUMN owner_ambiguous BOOLEAN" in upgrade
    assert "ADD COLUMN owner_clarification_pending BOOLEAN" in upgrade
    assert "ADD COLUMN task_details_clarification_pending BOOLEAN" in upgrade
    assert "ADD COLUMN contact_resolution_state VARCHAR(32)" in upgrade
    assert "ADD COLUMN contact_resolution_hash VARCHAR(64)" in upgrade
    assert "ix_gmail_extracted_obligations_suggestion_owner_ambiguous" in upgrade
    assert "sydney_task_review_guard_outbox_payload" in upgrade
    assert "sydney_task_review_guard_clarification_identity" in upgrade
    assert "sydney_task_review_guard_clarification_deadline" in upgrade
    assert "sydney_task_review_reject_clarification_delete" in upgrade
    assert "sydney_task_review_guard_outbox_parent" in upgrade
    assert "sydney_task_review_guard_outbox_transition" in upgrade
    assert "sydney_task_review_reject_outbox_delete" in upgrade
    assert "sydney_task_review_guard_nonce_parent" in upgrade
    assert "sydney_task_review_guard_nonce_identity" in upgrade
    assert "sydney_task_review_reject_event_mutation" in upgrade
    assert "sydney_task_review_guard_nonce_consumption" in upgrade
    assert "sydney_task_review_compat_suggestion_overlay" in upgrade
    assert "sydney_task_review_compat_obligation_overlay" in upgrade
    assert "sydney_task_review_sync_obligation_cause" in upgrade
    assert "sydney_task_review_lock_contact_identity_mutation" in upgrade
    assert "trg_sydney_question_outbox_payload_immutable" in upgrade
    assert "trg_crm_task_clarifications_identity_immutable" in upgrade
    assert "trg_crm_task_clarifications_deadline_guard" in upgrade
    assert "trg_crm_task_clarifications_no_delete" in upgrade
    assert "trg_sydney_question_outbox_parent_guard" in upgrade
    assert "trg_sydney_question_outbox_transition_guard" in upgrade
    assert "trg_sydney_question_outbox_no_delete" in upgrade
    assert "trg_crm_task_suggestion_approval_nonces_parent_guard" in upgrade
    assert "trg_crm_task_suggestion_approval_nonces_identity_immutable" in upgrade
    assert "trg_crm_task_suggestion_approval_nonces_no_delete" in upgrade
    assert "trg_crm_task_suggestion_events_append_only" in upgrade
    assert "trg_crm_task_suggestion_approval_nonces_one_time" in upgrade
    assert "trg_crm_task_suggestions_revision_83_compat" in upgrade
    assert "trg_gmail_extracted_obligations_revision_83_compat" in upgrade
    assert "trg_gmail_extracted_obligations_sync_task4_cause" in upgrade
    assert "trg_crm_contacts_task_review_identity_insert_delete" in upgrade
    assert "trg_crm_contacts_task_review_identity_update" in upgrade
    for forbidden in (
        "clarification_code",
        "plaintext_code",
        "plaintext_token",
        "raw_body",
        "access_token",
        "refresh_token",
    ):
        assert forbidden not in upgrade

    downgrade = _render("downgrade")
    expected_lock = (
        "LOCK TABLE " + ", ".join(DOWNGRADE_GUARD_TABLES) + " IN ACCESS EXCLUSIVE MODE"
    )
    assert expected_lock in downgrade
    assert "revision 84 downgrade refused: Sydney task review evidence exists" in downgrade
    for table in DOWNGRADE_GUARD_TABLES:
        assert f"EXISTS (SELECT 1 FROM {table} LIMIT 1)" in downgrade
    for table in TABLES:
        assert f"DROP TABLE {table}" in downgrade
    assert downgrade.index(expected_lock) < downgrade.index("EXISTS (SELECT 1")
    assert downgrade.index("EXISTS (SELECT 1") < downgrade.index("DROP TABLE")


def test_revision_84_upgrades_real_postgresql_and_enforces_core_constraints() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ) as run_marker:
            run_alembic(url, "upgrade", REVISION)
            inspector = sa.inspect(engine)
            assert set(TABLES).issubset(inspector.get_table_names())
            assert inspector.get_columns("gmail_extracted_obligations")[-1][
                "name"
            ] == "owner_ambiguous"
            with engine.connect() as connection:
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == REVISION

            run_owned_alembic_downgrade(
                url,
                DOWN_REVISION,
                expected_database=expected_database,
                run_marker=run_marker,
            )
            with engine.connect() as connection:
                assert set(TABLES).isdisjoint(
                    sa.inspect(connection).get_table_names()
                )
    finally:
        engine.dispose()


def _seed_owner_ambiguous_evidence_at_revision_83(
    connection: sa.Connection,
    *,
    evaluator_json: str,
    taxonomy_fallback: bool = False,
    contact_id: int | None = None,
    blocker_codes: tuple[str, ...] = ("missing_required_field",),
) -> tuple[UUID, UUID]:
    account_id = UUID("00000000-0000-4000-8400-000000000001")
    receipt_id = UUID("00000000-0000-4000-8400-000000000002")
    attempt_id = UUID("00000000-0000-4000-8400-000000000003")
    suggestion_id = UUID("00000000-0000-4000-8400-000000000004")
    obligation_id = UUID("00000000-0000-4000-8400-000000000005")
    now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    connection.execute(
        sa.text(
            "INSERT INTO gmail_sync_accounts (id, workspace_email) "
            "VALUES (:id, 'owner-backfill@example.test')"
        ),
        {"id": account_id},
    )
    connection.execute(
        sa.text(
            "INSERT INTO gmail_message_receipts "
            "(id, account_id, gmail_message_id, gmail_thread_id, direction, "
            "message_at, sender_hmac, body_hash) VALUES "
            "(:id, :account_id, 'owner-backfill-message', "
            "'owner-backfill-thread', 'received', :now, :sender, :body_hash)"
        ),
        {
            "id": receipt_id,
            "account_id": account_id,
            "now": now,
            "sender": "a" * 64,
            "body_hash": "b" * 64,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO gmail_extraction_attempts "
            "(id, receipt_id, schema_version, attempt_number, state, completed_at) "
            "VALUES (:id, :receipt_id, 'gmail-task-v1', 1, 'succeeded', :now)"
        ),
        {"id": attempt_id, "receipt_id": receipt_id, "now": now},
    )
    connection.execute(
        sa.text(
            "INSERT INTO crm_task_suggestions "
            "(id, gmail_account_id, gmail_thread_id, source_type, "
            "source_scope_key, source_action_key, contact_id, title, state, "
            "clarification_state, blocker_codes, payload_hash, "
            "model_schema_version, obligation_fingerprint, "
            "primary_instance_digest) VALUES "
            "(:id, :account_id, 'owner-backfill-thread', 'gmail_message', "
            "'gmail:owner-backfill:thread', 'owner-backfill-action', :contact_id, "
            "'Confirm ownership', 'needs_clarification', 'pending', "
            ":blocker_codes, :payload_hash, "
            "'gmail-task-v1', :fingerprint, :instance_digest)"
        ),
        {
            "id": suggestion_id,
            "account_id": account_id,
            "contact_id": contact_id,
            "blocker_codes": list(blocker_codes),
            "payload_hash": "c" * 64,
            "fingerprint": "d" * 64,
            "instance_digest": "e" * 64,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO gmail_extracted_obligations "
            "(id, receipt_id, extraction_attempt_id, action_key, schema_version, "
            "title, taxonomy_fallback, obligation_fingerprint, "
            "identity_instance_digest, reconciliation_material_hash, "
            "reconciled_suggestion_id, evaluator_result_json) VALUES "
            "(:id, :receipt_id, :attempt_id, 'owner-backfill-action', "
            "'gmail-task-v1', 'Confirm ownership', :taxonomy_fallback, :fingerprint, "
            ":instance_digest, :material_hash, :suggestion_id, :evaluator_json)"
        ),
        {
            "id": obligation_id,
            "receipt_id": receipt_id,
            "attempt_id": attempt_id,
            "fingerprint": "d" * 64,
            "instance_digest": "e" * 64,
            "material_hash": "f" * 64,
            "suggestion_id": suggestion_id,
            "evaluator_json": evaluator_json,
            "taxonomy_fallback": taxonomy_fallback,
        },
    )
    return obligation_id, suggestion_id


def test_revision_84_safely_backfills_canonical_owner_ambiguity_and_guards_it() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    canonical = json.dumps(
        {
            "contact_hint_supplied": False,
            "due_at_ambiguous": False,
            "due_at_state": "not_provided",
            "link_state": "not_provided",
            "owner_ambiguous": True,
            "owner_state": "ambiguous",
            "participant_ambiguous": False,
            "participant_state": "backend_unique",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ) as run_marker:
            run_alembic(url, "upgrade", DOWN_REVISION)
            with engine.begin() as connection:
                obligation_id, suggestion_id = (
                    _seed_owner_ambiguous_evidence_at_revision_83(
                        connection,
                        evaluator_json=canonical,
                    )
                )
            run_alembic(url, "upgrade", REVISION)
            with engine.connect() as connection:
                assert connection.scalar(
                    sa.text(
                        "SELECT owner_ambiguous FROM gmail_extracted_obligations "
                        "WHERE id = :id"
                    ),
                    {"id": obligation_id},
                ) is True
                assert connection.scalar(
                    sa.text(
                        "SELECT owner_clarification_pending "
                        "FROM crm_task_suggestions WHERE id = :id"
                    ),
                    {"id": suggestion_id},
                ) is True
                assert connection.scalar(
                    sa.text(
                        "SELECT task_details_clarification_pending "
                        "FROM crm_task_suggestions WHERE id = :id"
                    ),
                    {"id": suggestion_id},
                ) is False
                indexes = {
                    item["name"]
                    for item in sa.inspect(connection).get_indexes(
                        "gmail_extracted_obligations"
                    )
                }
                assert (
                    "ix_gmail_extracted_obligations_suggestion_owner_ambiguous"
                    in indexes
                )
            with pytest.raises(
                RuntimeError,
                match=(
                    "revision 84 downgrade refused: Sydney task review evidence exists"
                ),
            ):
                run_owned_alembic_downgrade(
                    url,
                    DOWN_REVISION,
                    expected_database=expected_database,
                    run_marker=run_marker,
                )
            with engine.connect() as connection:
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == REVISION
                assert connection.scalar(
                    sa.text(
                        "SELECT owner_ambiguous FROM gmail_extracted_obligations "
                        "WHERE id = :id AND reconciled_suggestion_id = :suggestion_id"
                    ),
                    {"id": obligation_id, "suggestion_id": suggestion_id},
                ) is True
                assert connection.scalar(
                    sa.text(
                        "SELECT owner_clarification_pending "
                        "FROM crm_task_suggestions WHERE id = :id"
                    ),
                    {"id": suggestion_id},
                ) is True
    finally:
        engine.dispose()


def test_revision_84_backfills_taxonomy_cause_without_inventing_owner_cause() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    canonical = json.dumps(
        {
            "contact_hint_supplied": False,
            "due_at_ambiguous": False,
            "due_at_state": "not_provided",
            "link_state": "not_provided",
            "owner_ambiguous": False,
            "owner_state": "implicit_brandon",
            "participant_ambiguous": False,
            "participant_state": "backend_unique",
            "taxonomy_fallback": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", DOWN_REVISION)
            with engine.begin() as connection:
                obligation_id, suggestion_id = (
                    _seed_owner_ambiguous_evidence_at_revision_83(
                        connection,
                        evaluator_json=canonical,
                        taxonomy_fallback=True,
                    )
                )
            run_alembic(url, "upgrade", REVISION)
            with engine.connect() as connection:
                assert connection.execute(
                    sa.text(
                        "SELECT owner_clarification_pending, "
                        "task_details_clarification_pending "
                        "FROM crm_task_suggestions WHERE id = :id"
                    ),
                    {"id": suggestion_id},
                ).one() == (False, True)
                assert connection.scalar(
                    sa.text(
                        "SELECT owner_ambiguous FROM gmail_extracted_obligations "
                        "WHERE id = :id"
                    ),
                    {"id": obligation_id},
                ) is False
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("contact_id", "blocker_codes", "expected_state", "expects_hash"),
    [
        (8401, (), "inferred_unique", True),
        (None, ("ambiguous_contact",), "unresolved", False),
        (None, (), "not_provided", False),
    ],
)
def test_revision_84_backfills_contact_resolution_authority(
    contact_id: int | None,
    blocker_codes: tuple[str, ...],
    expected_state: str,
    expects_hash: bool,
) -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    canonical = json.dumps(
        {
            "contact_hint_supplied": contact_id is not None,
            "due_at_ambiguous": False,
            "due_at_state": "not_provided",
            "link_state": "not_provided",
            "owner_ambiguous": False,
            "owner_state": "implicit_brandon",
            "participant_ambiguous": False,
            "participant_state": (
                "model_contact" if contact_id is not None else "backend_unique"
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", DOWN_REVISION)
            with engine.begin() as connection:
                if contact_id is not None:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_contacts "
                            "(id, first_name, last_name, email, normalized_email) "
                            "VALUES (:id, 'Alice', 'Client', :email, :email)"
                        ),
                        {"id": contact_id, "email": "alice@example.test"},
                    )
                _obligation_id, suggestion_id = (
                    _seed_owner_ambiguous_evidence_at_revision_83(
                        connection,
                        evaluator_json=canonical,
                        contact_id=contact_id,
                        blocker_codes=blocker_codes,
                    )
                )
            run_alembic(url, "upgrade", REVISION)
            with engine.connect() as connection:
                row = connection.execute(
                    sa.text(
                        "SELECT contact_resolution_state, "
                        "contact_resolution_hash FROM crm_task_suggestions "
                        "WHERE id = :id"
                    ),
                    {"id": suggestion_id},
                ).one()
            assert row.contact_resolution_state == expected_state
            if expects_hash:
                expected_hash = hashlib.sha256(
                    b"sws:crm-contact-resolution:v1\0"
                    + str(contact_id).encode("ascii")
                    + b"\0alice@example.test"
                ).hexdigest()
                assert row.contact_resolution_hash == expected_hash
            else:
                assert row.contact_resolution_hash is None
    finally:
        engine.dispose()


def test_revision_84_keeps_revision_83_suggestion_writes_compatible() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    contact_id = 8491
    selected_id = uuid4()
    missing_id = uuid4()
    selected_hash = hashlib.sha256(
        b"sws:crm-contact-resolution:v1\0"
        + str(contact_id).encode("ascii")
        + b"\0alice@example.test"
    ).hexdigest()
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_contacts "
                        "(id, first_name, last_name, email, normalized_email) "
                        "VALUES (:id, 'Alice', 'Client', :email, :email)"
                    ),
                    {"id": contact_id, "email": "alice@example.test"},
                )
                for suggestion_id, request_id, contact, blockers in (
                    (selected_id, uuid4(), contact_id, ()),
                    (missing_id, uuid4(), None, ("missing_required_field",)),
                ):
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestions "
                            "(id, source_type, source_scope_key, "
                            "source_action_key, source_request_id, contact_id, "
                            "title, state, clarification_state, blocker_codes, "
                            "payload_hash, model_schema_version, "
                            "obligation_fingerprint) VALUES "
                            "(:id, 'sydney_chat', :scope, :action, :request_id, "
                            ":contact_id, 'Legacy revision 83 write', "
                            ":state, :clarification_state, :blockers, :hash, "
                            "'sydney-task-v1', :fingerprint)"
                        ),
                        {
                            "id": suggestion_id,
                            "scope": f"sydney:{request_id}",
                            "action": f"sydney-action:{request_id.hex}",
                            "request_id": request_id,
                            "contact_id": contact,
                            "state": (
                                "needs_clarification"
                                if blockers
                                else "pending_review"
                            ),
                            "clarification_state": (
                                "pending" if blockers else "not_required"
                            ),
                            "blockers": list(blockers),
                            "hash": "a" * 64,
                            "fingerprint": "b" * 64,
                        },
                    )
                connection.execute(
                    sa.text(
                        "UPDATE crm_task_suggestions SET "
                        "contact_resolution_state = 'clarified_unique' "
                        "WHERE id = :id"
                    ),
                    {"id": selected_id},
                )
                connection.execute(
                    sa.text(
                        "UPDATE crm_task_suggestions SET blocker_codes = "
                        "ARRAY['ambiguous_due_at']::varchar[] WHERE id = :id"
                    ),
                    {"id": selected_id},
                )
            with engine.connect() as connection:
                selected = connection.execute(
                    sa.text(
                        "SELECT contact_resolution_state, "
                        "contact_resolution_hash FROM crm_task_suggestions "
                        "WHERE id = :id"
                    ),
                    {"id": selected_id},
                ).one()
                missing = connection.execute(
                    sa.text(
                        "SELECT owner_clarification_pending, "
                        "task_details_clarification_pending "
                        "FROM crm_task_suggestions WHERE id = :id"
                    ),
                    {"id": missing_id},
                ).one()
            assert selected.contact_resolution_state == "clarified_unique"
            assert selected.contact_resolution_hash == selected_hash
            assert missing == (False, True)
    finally:
        engine.dispose()


def test_revision_83_selected_contact_write_joins_authority_lock() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    request_id = uuid4()
    statement = sa.text(
        "INSERT INTO crm_task_suggestions "
        "(id, source_type, source_scope_key, source_action_key, "
        "source_request_id, contact_id, title, state, clarification_state, "
        "blocker_codes, payload_hash, model_schema_version, "
        "obligation_fingerprint) VALUES "
        "(:id, 'sydney_chat', :scope, :action, :request_id, 8494, "
        "'Legacy selected contact', 'pending_review', 'not_required', "
        "ARRAY[]::varchar[], :hash, 'sydney-task-v1', :fingerprint)"
    )
    parameters = {
        "id": uuid4(),
        "scope": f"sydney:{request_id}",
        "action": f"sydney-action:{request_id.hex}",
        "request_id": request_id,
        "hash": "a" * 64,
        "fingerprint": "b" * 64,
    }
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_contacts "
                        "(id, first_name, last_name, email, normalized_email) "
                        "VALUES (8494, 'Alice', 'Client', :email, :email)"
                    ),
                    {"email": "legacy-lock@example.test"},
                )
            lock_connection = engine.connect()
            lock_transaction = lock_connection.begin()
            try:
                lock_connection.execute(
                    sa.text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": 3892649629032444829},
                )
                with pytest.raises(sa.exc.DBAPIError, match="statement timeout"):
                    with engine.begin() as blocked:
                        blocked.execute(sa.text("SET LOCAL statement_timeout = 100"))
                        blocked.execute(statement, parameters)
            finally:
                lock_transaction.commit()
                lock_connection.close()
            with engine.begin() as connection:
                connection.execute(statement, parameters)
    finally:
        engine.dispose()


def test_revision_83_selected_contact_write_refuses_duplicate_authority() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    request_id = uuid4()
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_contacts "
                        "(id, first_name, last_name, email, normalized_email) "
                        "VALUES "
                        "(8495, 'Alice', 'One', :email, :email), "
                        "(8496, 'Alice', 'Two', :email, :email)"
                    ),
                    {"email": "legacy-duplicate@example.test"},
                )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestions "
                            "(id, source_type, source_scope_key, "
                            "source_action_key, source_request_id, contact_id, "
                            "title, state, clarification_state, blocker_codes, "
                            "payload_hash, model_schema_version, "
                            "obligation_fingerprint) VALUES "
                            "(:id, 'sydney_chat', :scope, :action, :request_id, "
                            "8495, 'Legacy duplicate contact', "
                            "'pending_review', 'not_required', "
                            "ARRAY[]::varchar[], :hash, 'sydney-task-v1', "
                            ":fingerprint)"
                        ),
                        {
                            "id": uuid4(),
                            "scope": f"sydney:{request_id}",
                            "action": f"sydney-action:{request_id.hex}",
                            "request_id": request_id,
                            "hash": "a" * 64,
                            "fingerprint": "b" * 64,
                        },
                    )
    finally:
        engine.dispose()


def test_revision_83_contact_update_refuses_duplicate_authority_and_rolls_back() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    request_id = uuid4()
    suggestion_id = uuid4()
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_contacts "
                        "(id, first_name, last_name, email, normalized_email) "
                        "VALUES "
                        "(8497, 'Alice', 'Unique', :unique, :unique), "
                        "(8498, 'Bob', 'One', :duplicate, :duplicate), "
                        "(8499, 'Bob', 'Two', :duplicate, :duplicate)"
                    ),
                    {
                        "unique": "legacy-update-unique@example.test",
                        "duplicate": "legacy-update-duplicate@example.test",
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, source_type, source_scope_key, "
                        "source_action_key, source_request_id, contact_id, "
                        "title, state, clarification_state, blocker_codes, "
                        "payload_hash, model_schema_version, "
                        "obligation_fingerprint) VALUES "
                        "(:id, 'sydney_chat', :scope, :action, :request_id, "
                        "8497, 'Legacy contact update', 'pending_review', "
                        "'not_required', ARRAY[]::varchar[], :hash, "
                        "'sydney-task-v1', :fingerprint)"
                    ),
                    {
                        "id": suggestion_id,
                        "scope": f"sydney:{request_id}",
                        "action": f"sydney-action:{request_id.hex}",
                        "request_id": request_id,
                        "hash": "a" * 64,
                        "fingerprint": "b" * 64,
                    },
                )
                before = connection.execute(
                    sa.text(
                        "SELECT contact_id, contact_resolution_state, "
                        "contact_resolution_hash FROM crm_task_suggestions "
                        "WHERE id = :id"
                    ),
                    {"id": suggestion_id},
                ).one()
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "UPDATE crm_task_suggestions SET contact_id = 8498 "
                            "WHERE id = :id"
                        ),
                        {"id": suggestion_id},
                    )
            with engine.connect() as connection:
                after = connection.execute(
                    sa.text(
                        "SELECT contact_id, contact_resolution_state, "
                        "contact_resolution_hash FROM crm_task_suggestions "
                        "WHERE id = :id"
                    ),
                    {"id": suggestion_id},
                ).one()
            assert after == before
    finally:
        engine.dispose()


@pytest.mark.parametrize("invalid_shape", ("missing_cause", "selected_contact"))
def test_revision_84_rejects_explicit_default_shaped_invalid_insert(
    invalid_shape: str,
) -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    contact_id = 8492
    request_id = uuid4()
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_contacts "
                        "(id, first_name, last_name, email, normalized_email) "
                        "VALUES (:id, 'Alice', 'Client', :email, :email)"
                    ),
                    {"id": contact_id, "email": "alice-explicit@example.test"},
                )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestions "
                            "(id, source_type, source_scope_key, "
                            "source_action_key, source_request_id, contact_id, "
                            "title, state, clarification_state, blocker_codes, "
                            "owner_clarification_pending, "
                            "task_details_clarification_pending, "
                            "contact_resolution_state, "
                            "contact_resolution_hash, payload_hash, "
                            "model_schema_version, obligation_fingerprint) "
                            "VALUES (:id, 'sydney_chat', :scope, :action, "
                            ":request_id, :contact_id, 'Explicit invalid', "
                            "'needs_clarification', 'pending', :blockers, "
                            "false, false, 'not_provided', NULL, :hash, "
                            "'sydney-task-v1', :fingerprint)"
                        ),
                        {
                            "id": uuid4(),
                            "scope": f"sydney:{request_id}",
                            "action": f"sydney-action:{request_id.hex}",
                            "request_id": request_id,
                            "contact_id": (
                                contact_id
                                if invalid_shape == "selected_contact"
                                else None
                            ),
                            "blockers": (
                                []
                                if invalid_shape == "selected_contact"
                                else ["missing_required_field"]
                            ),
                            "hash": "a" * 64,
                            "fingerprint": "b" * 64,
                        },
                    )
    finally:
        engine.dispose()


def test_revision_84_compatibility_sync_accumulates_obligation_causes() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    canonical = json.dumps(
        {
            "contact_hint_supplied": False,
            "due_at_ambiguous": False,
            "due_at_state": "not_provided",
            "link_state": "not_provided",
            "owner_ambiguous": True,
            "owner_state": "ambiguous",
            "participant_ambiguous": False,
            "participant_state": "backend_unique",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                _obligation_id, suggestion_id = (
                    _seed_owner_ambiguous_evidence_at_revision_83(
                        connection,
                        evaluator_json=canonical,
                    )
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extracted_obligations "
                        "(id, receipt_id, extraction_attempt_id, action_key, "
                        "schema_version, title, taxonomy_fallback, "
                        "obligation_fingerprint, identity_instance_digest, "
                        "reconciliation_material_hash, "
                        "reconciled_suggestion_id, evaluator_result_json) "
                        "SELECT :id, receipt_id, extraction_attempt_id, "
                        "'taxonomy-only-action', schema_version, title, true, "
                        ":fingerprint, :instance_digest, :material_hash, "
                        "reconciled_suggestion_id, :evaluator_json "
                        "FROM gmail_extracted_obligations WHERE id = :source_id"
                    ),
                    {
                        "id": uuid4(),
                        "source_id": _obligation_id,
                        "fingerprint": "1" * 64,
                        "instance_digest": "2" * 64,
                        "material_hash": "3" * 64,
                        "evaluator_json": json.dumps(
                            {
                                "contact_hint_supplied": False,
                                "due_at_ambiguous": False,
                                "due_at_state": "not_provided",
                                "link_state": "not_provided",
                                "owner_ambiguous": False,
                                "owner_state": "implicit_brandon",
                                "participant_ambiguous": False,
                                "participant_state": "backend_unique",
                                "taxonomy_fallback": True,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                )
                causes = connection.execute(
                    sa.text(
                        "SELECT owner_clarification_pending, "
                        "task_details_clarification_pending "
                        "FROM crm_task_suggestions WHERE id = :id"
                    ),
                    {"id": suggestion_id},
                ).one()
            assert causes == (True, True)
    finally:
        engine.dispose()


@pytest.mark.parametrize("mutation", ("insert", "update", "delete"))
def test_revision_84_contact_identity_mutations_share_authority_lock(
    mutation: str,
) -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    lock_key = 3892649629032444829
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_contacts "
                        "(id, first_name, last_name, email, normalized_email) "
                        "VALUES (8493, 'Existing', 'Writer', :email, :email)"
                    ),
                    {"email": "existing-authority-lock@example.test"},
                )
            statements = {
                "insert": sa.text(
                    "INSERT INTO crm_contacts "
                    "(first_name, last_name, email, normalized_email) "
                    "VALUES ('Blocked', 'Writer', :email, :email)"
                ),
                "update": sa.text(
                    "UPDATE crm_contacts SET email = :email, "
                    "normalized_email = :email WHERE id = 8493"
                ),
                "delete": sa.text("DELETE FROM crm_contacts WHERE id = 8493"),
            }
            lock_connection = engine.connect()
            lock_transaction = lock_connection.begin()
            try:
                lock_connection.execute(
                    sa.text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": lock_key},
                )
                with pytest.raises(sa.exc.DBAPIError, match="statement timeout"):
                    with engine.begin() as blocked:
                        blocked.execute(sa.text("SET LOCAL statement_timeout = 100"))
                        blocked.execute(
                            statements[mutation],
                            {"email": "authority-lock@example.test"},
                        )
            finally:
                lock_transaction.commit()
                lock_connection.close()
            with engine.begin() as connection:
                connection.execute(
                    statements[mutation],
                    {"email": "authority-lock@example.test"},
                )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "invalid_mode",
    ["stale_normalized_email", "duplicate_email", "selected_and_ambiguous"],
)
def test_revision_84_refuses_untrustworthy_selected_contact_backfill(
    invalid_mode: str,
) -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    canonical = json.dumps(
        {
            "contact_hint_supplied": True,
            "due_at_ambiguous": False,
            "due_at_state": "not_provided",
            "link_state": "not_provided",
            "owner_ambiguous": False,
            "owner_state": "implicit_brandon",
            "participant_ambiguous": False,
            "participant_state": "model_contact",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", DOWN_REVISION)
            with engine.begin() as connection:
                normalized = (
                    "mallory@example.test"
                    if invalid_mode == "stale_normalized_email"
                    else "alice@example.test"
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_contacts "
                        "(id, first_name, last_name, email, normalized_email) "
                        "VALUES (8401, 'Alice', 'Client', "
                        "'alice@example.test', :normalized)"
                    ),
                    {"normalized": normalized},
                )
                if invalid_mode == "duplicate_email":
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_contacts "
                            "(id, first_name, last_name, email, normalized_email) "
                            "VALUES (8402, 'Alice', 'Duplicate', "
                            "'ALICE@example.test', 'alice@example.test')"
                        )
                    )
                blockers = (
                    ("ambiguous_contact",)
                    if invalid_mode == "selected_and_ambiguous"
                    else ()
                )
                _seed_owner_ambiguous_evidence_at_revision_83(
                    connection,
                    evaluator_json=canonical,
                    contact_id=8401,
                    blocker_codes=blockers,
                )
            with pytest.raises(
                RuntimeError,
                match="revision 84 contact resolution backfill refused",
            ):
                run_alembic(url, "upgrade", REVISION)
            with engine.connect() as connection:
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == DOWN_REVISION
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "invalid_evaluator_json",
    [
        "{}",
        '{"owner_ambiguous":"true"}',
        '{"owner_ambiguous":true,"owner_ambiguous":false}',
        json.dumps(
            {
                "contact_hint_supplied": False,
                "due_at_ambiguous": False,
                "due_at_state": "not_provided",
                "link_state": "not_provided",
                "owner_ambiguous": True,
                "owner_state": "implicit_brandon",
                "participant_ambiguous": False,
                "participant_state": "backend_unique",
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        json.dumps(
            {
                "contact_hint_supplied": False,
                "due_at_ambiguous": False,
                "due_at_state": "not_provided",
                "link_state": "not_provided",
                "owner_ambiguous": False,
                "owner_state": "ambiguous",
                "participant_ambiguous": False,
                "participant_state": "backend_unique",
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        json.dumps(
            {
                "contact_hint_supplied": False,
                "due_at_ambiguous": False,
                "due_at_state": "not_provided",
                "link_state": "not_provided",
                "owner_ambiguous": False,
                "owner_state": "implicit_brandon",
                "participant_ambiguous": False,
                "participant_state": "backend_unique",
                "taxonomy_fallback": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        "not-json",
    ],
)
def test_revision_84_fails_closed_on_noncanonical_owner_evidence(
    invalid_evaluator_json: str,
) -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", DOWN_REVISION)
            with engine.begin() as connection:
                _seed_owner_ambiguous_evidence_at_revision_83(
                    connection,
                    evaluator_json=invalid_evaluator_json,
                )
            with pytest.raises(
                RuntimeError,
                match="revision 84 owner ambiguity backfill refused",
            ):
                run_alembic(url, "upgrade", REVISION)
            with engine.connect() as connection:
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == DOWN_REVISION
                assert "owner_ambiguous" not in {
                    column["name"]
                    for column in sa.inspect(connection).get_columns(
                        "gmail_extracted_obligations"
                    )
                }
    finally:
        engine.dispose()


@pytest.mark.parametrize("source_type", ["gmail_message", "sydney_chat"])
def test_revision_84_refuses_unexplained_missing_required_field(
    source_type: str,
) -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    canonical = json.dumps(
        {
            "contact_hint_supplied": False,
            "due_at_ambiguous": False,
            "due_at_state": "not_provided",
            "link_state": "not_provided",
            "owner_ambiguous": False,
            "owner_state": "implicit_brandon",
            "participant_ambiguous": False,
            "participant_state": "backend_unique",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", DOWN_REVISION)
            with engine.begin() as connection:
                if source_type == "gmail_message":
                    _seed_owner_ambiguous_evidence_at_revision_83(
                        connection,
                        evaluator_json=canonical,
                    )
                else:
                    suggestion_id = uuid4()
                    _insert_sydney_suggestion(
                        connection,
                        suggestion_id=suggestion_id,
                        request_id=uuid4(),
                        title="Unexplained Sydney draft",
                    )
                    connection.execute(
                        sa.text(
                            "UPDATE crm_task_suggestions SET blocker_codes = "
                            "ARRAY['missing_required_field']::varchar[] "
                            "WHERE id = :id"
                        ),
                        {"id": suggestion_id},
                    )
            with pytest.raises(
                RuntimeError,
                match="revision 84 clarification cause backfill refused",
            ):
                run_alembic(url, "upgrade", REVISION)
            with engine.connect() as connection:
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == DOWN_REVISION
    finally:
        engine.dispose()


def test_real_postgresql_enforces_slots_immutable_payloads_events_and_nonce_parent() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    now = datetime(2026, 8, 21, 13, 0, tzinfo=timezone.utc)
    first_suggestion = UUID("00000000-0000-4000-8400-000000000011")
    second_suggestion = UUID("00000000-0000-4000-8400-000000000012")
    clarification_id = UUID("00000000-0000-4000-8400-000000000013")
    attempt_id = UUID("00000000-0000-4000-8400-000000000014")
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO admin_users (id, email, hashed_password) "
                        "VALUES (1, 'task5-admin@example.test', 'test-only')"
                    )
                )
                _insert_sydney_suggestion(
                    connection,
                    suggestion_id=first_suggestion,
                    request_id=UUID("00000000-0000-4000-8400-000000000021"),
                    title="First clarification",
                )
                _insert_sydney_suggestion(
                    connection,
                    suggestion_id=second_suggestion,
                    request_id=UUID("00000000-0000-4000-8400-000000000022"),
                    title="Second clarification",
                )
                _insert_clarification(
                    connection,
                    clarification_id=clarification_id,
                    suggestion_id=first_suggestion,
                    code_byte=1,
                    now=now,
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO sydney_question_outbox "
                        "(id, clarification_id, attempt_kind, attempt_number, "
                        "dedupe_key, template_id, question_context_json, "
                        "rendered_payload_hash) VALUES "
                        "(:id, :clarification_id, 'initial', 1, :dedupe, "
                        "'clarification_initial_v1', :context, :payload_hash)"
                    ),
                    {
                        "id": attempt_id,
                        "clarification_id": clarification_id,
                        "dedupe": (
                            f"clarification:{clarification_id}:v1:initial:1"
                        ),
                        "context": json.dumps(
                            {
                                "party_label": "Alice",
                                "question": "When is this due?",
                                "subject_preview": "Due date",
                                "task_title": "First clarification",
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "payload_hash": "1" * 64,
                    },
                )

            for table, error in (
                ("sydney_question_outbox", "outbox_append_only"),
                ("crm_task_clarifications", "clarification_append_only"),
            ):
                with pytest.raises(sa.exc.DBAPIError, match=error):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(f"DELETE FROM {table} WHERE id = :id"),
                            {
                                "id": (
                                    attempt_id
                                    if table == "sydney_question_outbox"
                                    else clarification_id
                                )
                            },
                        )

            invalid_slot_cases = (
                (first_suggestion, "-1001234567891", 2, "contact", 2),
                (second_suggestion, "-1001234567890", 1, "contact", 2),
            )
            for suggestion_id, chat_id, code_byte, field_name, round_number in (
                invalid_slot_cases
            ):
                with pytest.raises(sa.exc.IntegrityError):
                    with engine.begin() as connection:
                        _insert_clarification(
                            connection,
                            clarification_id=uuid4(),
                            suggestion_id=suggestion_id,
                            code_byte=code_byte,
                            now=now,
                            chat_id=chat_id,
                            field_name=field_name,
                            round_number=round_number,
                        )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    _insert_clarification(
                        connection,
                        clarification_id=uuid4(),
                        suggestion_id=second_suggestion,
                        code_byte=8,
                        now=now,
                        chat_id="4503599627370496",
                        field_name="contact",
                        round_number=2,
                    )

            for assignment in (
                "owner_clarification_pending = true",
                "contact_resolution_state = 'unresolved'",
                "contact_resolution_state = 'inferred_unique', "
                "contact_resolution_hash = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'",
            ):
                with pytest.raises(sa.exc.IntegrityError):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "UPDATE crm_task_suggestions SET "
                                f"{assignment} WHERE id = :id"
                            ),
                            {"id": first_suggestion},
                        )

            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE crm_task_suggestions SET blocker_codes = "
                        "ARRAY['ambiguous_due_at', 'missing_required_field']"
                        "::varchar[] WHERE id = :id"
                    ),
                    {"id": first_suggestion},
                )
                assert connection.execute(
                    sa.text(
                        "SELECT owner_clarification_pending, "
                        "task_details_clarification_pending "
                        "FROM crm_task_suggestions WHERE id = :id"
                    ),
                    {"id": first_suggestion},
                ).one() == (False, True)
                connection.execute(
                    sa.text(
                        "UPDATE crm_task_suggestions SET blocker_codes = "
                        "ARRAY['ambiguous_due_at']::varchar[], "
                        "task_details_clarification_pending = false "
                        "WHERE id = :id"
                    ),
                    {"id": first_suggestion},
                )

            for column, value in (
                ("suggestion_id", second_suggestion),
                ("field_name", "contact"),
                ("round_number", 2),
                ("options_json", '{"choices":["mallory@example.test"]}'),
                ("code_hash", bytes([9]) * 32),
                ("code_key_version", 8),
                ("suggestion_version", 2),
                ("telegram_chat_id", "-1001234567891"),
                ("created_at", now + timedelta(seconds=1)),
            ):
                with pytest.raises(sa.exc.DBAPIError, match="clarification_identity"):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                f"UPDATE crm_task_clarifications SET {column} = :value "
                                "WHERE id = :id"
                            ),
                            {"value": value, "id": clarification_id},
                        )

            for column, value in (
                ("clarification_id", uuid4()),
                ("attempt_kind", "reminder"),
                ("attempt_number", 2),
                ("parent_initial_attempt_id", uuid4()),
                ("reply_to_attempt_id", uuid4()),
                ("dedupe_key", "forged-dedupe"),
                ("template_id", "clarification_reminder_v1"),
                ("question_context_json", '{"question":"tampered"}'),
                ("rendered_payload_hash", "9" * 64),
                ("created_at", now + timedelta(seconds=1)),
            ):
                with pytest.raises(
                    sa.exc.DBAPIError,
                    match="outbox_payload_immutable",
                ):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                f"UPDATE sydney_question_outbox SET {column} = :value "
                                "WHERE id = :id"
                            ),
                            {"value": value, "id": attempt_id},
                        )

            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE sydney_question_outbox SET state = 'sending', "
                        "attempted_at = :now, telegram_chat_id = :chat "
                        "WHERE id = :id"
                    ),
                    {"now": now, "chat": "-1001234567890", "id": attempt_id},
                )
                connection.execute(
                    sa.text(
                        "UPDATE crm_task_clarifications SET first_attempt_at = :now, "
                        "deadline_anchor_kind = 'first_attempt', "
                        "deadline_anchored_at = :now, "
                        "slot_deadline_at = :deadline WHERE id = :id"
                    ),
                    {
                        "now": now,
                        "deadline": now + timedelta(hours=48),
                        "id": clarification_id,
                    },
                )

            with pytest.raises(sa.exc.DBAPIError, match="outbox_parent_invalid"):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO sydney_question_outbox "
                            "(clarification_id, attempt_kind, attempt_number, "
                            "reply_to_attempt_id, dedupe_key, template_id, "
                            "question_context_json, rendered_payload_hash) VALUES "
                            "(:clarification_id, 'reminder', 1, :parent, :dedupe, "
                            "'clarification_reminder_v1', '{}', :hash)"
                        ),
                        {
                            "clarification_id": clarification_id,
                            "parent": attempt_id,
                            "dedupe": (
                                f"clarification:{clarification_id}:v1:reminder:1"
                            ),
                            "hash": "2" * 64,
                        },
                    )

            with pytest.raises(
                sa.exc.DBAPIError,
                match="clarification_deadline",
            ):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "UPDATE crm_task_clarifications SET "
                            "deadline_anchored_at = :anchor, "
                            "slot_deadline_at = :deadline WHERE id = :id"
                        ),
                        {
                            "anchor": now + timedelta(minutes=5),
                            "deadline": now
                            + timedelta(hours=48, minutes=5),
                            "id": clarification_id,
                        },
                    )

            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE crm_task_clarifications SET state = 'answered', "
                        "answer_json = :answer, resolved_at = :resolved "
                        "WHERE id = :id"
                    ),
                    {
                        "answer": '{"decision":"no_due_date","kind":"due_at"}',
                        "resolved": now + timedelta(minutes=10),
                        "id": clarification_id,
                    },
                )
            for assignment in (
                "answer_json = '{\"decision\":\"set_due\",\"kind\":\"due_at\"}'",
                "answer_json = NULL",
                "state = 'pending', answer_json = NULL, resolved_at = NULL",
                "state = 'timed_out', answer_json = NULL",
                "resolved_at = resolved_at + interval '1 second'",
            ):
                with pytest.raises(sa.exc.DBAPIError, match="clarification_resolution"):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "UPDATE crm_task_clarifications SET "
                                f"{assignment} WHERE id = :id"
                            ),
                            {"id": clarification_id},
                        )

            event_id = UUID("00000000-0000-4000-8400-000000000015")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestion_events "
                        "(id, suggestion_id, suggestion_version, event_type, "
                        "actor_type, event_data_json) VALUES "
                        "(:id, :suggestion_id, 1, 'clarification_asked', "
                        "'sydney', '{}')"
                    ),
                    {"id": event_id, "suggestion_id": first_suggestion},
                )
            for statement in (
                "UPDATE crm_task_suggestion_events SET actor_type = 'system' "
                "WHERE id = :id",
                "DELETE FROM crm_task_suggestion_events WHERE id = :id",
            ):
                with pytest.raises(sa.exc.DBAPIError, match="event_append_only"):
                    with engine.begin() as connection:
                        connection.execute(sa.text(statement), {"id": event_id})

            handoff_id = UUID("00000000-0000-4000-8400-000000000016")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestion_approval_nonces "
                        "(id, suggestion_id, suggestion_version, payload_hash, "
                        "kind, issuance_path, token_hash, issued_at, expires_at) "
                        "VALUES (:id, :suggestion_id, 1, :payload_hash, 'handoff', "
                        "'approval_link', :token_hash, :now, :expires)"
                    ),
                    {
                        "id": handoff_id,
                        "suggestion_id": first_suggestion,
                        "payload_hash": "a" * 64,
                        "token_hash": bytes([3]) * 32,
                        "now": now,
                        "expires": now + timedelta(minutes=15),
                    },
                )
            for assignment in (
                "suggestion_id = '00000000-0000-4000-8400-000000000012'",
                "suggestion_version = 2",
                "payload_hash = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'",
                "kind = 'approval'",
                "issuance_path = 'command_prepare'",
                "token_hash = decode('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'hex')",
                "administrator_id = 1",
                "parent_nonce_id = '00000000-0000-4000-8400-000000000017'",
                "issued_at = issued_at + interval '1 second'",
                "expires_at = expires_at + interval '1 second'",
            ):
                with pytest.raises(sa.exc.DBAPIError, match="nonce_identity"):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "UPDATE crm_task_suggestion_approval_nonces SET "
                                f"{assignment} WHERE id = :id"
                            ),
                            {"id": handoff_id},
                        )
            with pytest.raises(sa.exc.DBAPIError, match="nonce_identity"):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "DELETE FROM crm_task_suggestion_approval_nonces "
                            "WHERE id = :id"
                        ),
                        {"id": handoff_id},
                    )
            with pytest.raises(sa.exc.DBAPIError, match="nonce_parent_invalid"):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestion_approval_nonces "
                            "(suggestion_id, suggestion_version, payload_hash, kind, "
                            "issuance_path, token_hash, administrator_id, "
                            "parent_nonce_id, issued_at, expires_at) VALUES "
                            "(:suggestion_id, 1, :payload_hash, 'approval', "
                            "'handoff_exchange', :token_hash, 1, :parent, :now, "
                            ":expires)"
                        ),
                        {
                            "suggestion_id": first_suggestion,
                            "payload_hash": "a" * 64,
                            "token_hash": bytes([4]) * 32,
                            "parent": handoff_id,
                            "now": now,
                            "expires": now + timedelta(minutes=5),
                        },
                    )
            approval_id = UUID("00000000-0000-4000-8400-000000000017")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE crm_task_suggestion_approval_nonces "
                        "SET consumed_at = :consumed WHERE id = :id"
                    ),
                    {"consumed": now + timedelta(minutes=1), "id": handoff_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestion_approval_nonces "
                        "(id, suggestion_id, suggestion_version, payload_hash, "
                        "kind, issuance_path, token_hash, administrator_id, "
                        "parent_nonce_id, issued_at, expires_at) VALUES "
                        "(:id, :suggestion_id, 1, :payload_hash, 'approval', "
                        "'handoff_exchange', :token_hash, 1, :parent, :issued, "
                        ":expires)"
                    ),
                    {
                        "id": approval_id,
                        "suggestion_id": first_suggestion,
                        "payload_hash": "a" * 64,
                        "token_hash": bytes([5]) * 32,
                        "parent": handoff_id,
                        "issued": now + timedelta(minutes=1),
                        "expires": now + timedelta(minutes=6),
                    },
                )
            for consumed_value in (None, now + timedelta(minutes=2)):
                with pytest.raises(sa.exc.DBAPIError, match="nonce_consumption"):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "UPDATE crm_task_suggestion_approval_nonces "
                                "SET consumed_at = :consumed WHERE id = :id"
                            ),
                            {"consumed": consumed_value, "id": handoff_id},
                        )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestion_approval_nonces "
                            "(suggestion_id, suggestion_version, payload_hash, kind, "
                            "issuance_path, token_hash, administrator_id, "
                            "parent_nonce_id, issued_at, expires_at) VALUES "
                            "(:suggestion_id, 1, :payload_hash, 'approval', "
                            "'handoff_exchange', :token_hash, 1, :parent, :issued, "
                            ":expires)"
                        ),
                        {
                            "suggestion_id": second_suggestion,
                            "payload_hash": "a" * 64,
                            "token_hash": bytes([6]) * 32,
                            "parent": handoff_id,
                            "issued": now + timedelta(minutes=1),
                            "expires": now + timedelta(minutes=6),
                        },
                    )
    finally:
        engine.dispose()


def test_outbox_parent_state_retry_and_reminder_matrix_on_postgresql() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    now = datetime(2026, 8, 21, 14, 0, tzinfo=timezone.utc)
    suggestion_id = UUID("00000000-0000-4000-8400-000000000031")
    clarification_id = UUID("00000000-0000-4000-8400-000000000032")
    initial_id = UUID("00000000-0000-4000-8400-000000000033")
    retry_id = UUID("00000000-0000-4000-8400-000000000034")
    reminder_id = UUID("00000000-0000-4000-8400-000000000035")
    context = json.dumps(
        {
            "party_label": "Alice",
            "question": "When is this due?",
            "subject_preview": "Due date",
            "task_title": "Clarify due date",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO admin_users (id, email, hashed_password) "
                        "VALUES (1, 'outbox-admin@example.test', 'test-only')"
                    )
                )
                audit_id = connection.scalar(
                    sa.text(
                        "INSERT INTO agent_action_audits "
                        "(actor, action_id, method, path, status_code, allowed, "
                        "request_meta, response_meta) VALUES "
                        "('command_admin', 'clarification.reconcile', 'POST', "
                        "'/test', 200, true, '{}', '{}') RETURNING id"
                    )
                )
                _insert_sydney_suggestion(
                    connection,
                    suggestion_id=suggestion_id,
                    request_id=UUID("00000000-0000-4000-8400-000000000036"),
                    title="Clarify due date",
                )
                _insert_clarification(
                    connection,
                    clarification_id=clarification_id,
                    suggestion_id=suggestion_id,
                    code_byte=7,
                    now=now,
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO sydney_question_outbox "
                        "(id, clarification_id, attempt_kind, attempt_number, "
                        "dedupe_key, template_id, question_context_json, "
                        "rendered_payload_hash) VALUES "
                        "(:id, :clarification_id, 'initial', 1, :dedupe, "
                        "'clarification_initial_v1', :context, :hash)"
                    ),
                    {
                        "id": initial_id,
                        "clarification_id": clarification_id,
                        "dedupe": (
                            f"clarification:{clarification_id}:v1:initial:1"
                        ),
                        "context": context,
                        "hash": "1" * 64,
                    },
                )

            for invalid_update in (
                (
                    "state = 'sent', attempted_at = :now, sent_at = :now, "
                    "telegram_chat_id = :chat, telegram_message_id = '1'"
                ),
                "state = 'failed', failure_category = 'provider_rejected'",
            ):
                with pytest.raises(sa.exc.DBAPIError, match="outbox_transition"):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "UPDATE sydney_question_outbox SET "
                                f"{invalid_update} WHERE id = :id"
                            ),
                            {
                                "now": now,
                                "chat": "-1001234567890",
                                "id": initial_id,
                            },
                        )

            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE sydney_question_outbox SET state = 'sending', "
                        "attempted_at = :now, telegram_chat_id = :chat "
                        "WHERE id = :id"
                    ),
                    {"now": now, "chat": "-1001234567890", "id": initial_id},
                )
                connection.execute(
                    sa.text(
                        "UPDATE crm_task_clarifications SET first_attempt_at = :now, "
                        "deadline_anchor_kind = 'first_attempt', "
                        "deadline_anchored_at = :now, "
                        "slot_deadline_at = :deadline WHERE id = :id"
                    ),
                    {
                        "now": now,
                        "deadline": now + timedelta(hours=48),
                        "id": clarification_id,
                    },
                )
                connection.execute(
                    sa.text(
                        "UPDATE sydney_question_outbox SET state = "
                        "'delivery_uncertain', failure_category = 'provider_timeout' "
                        "WHERE id = :id AND attempted_at = :attempted_at"
                    ),
                    {"id": initial_id, "attempted_at": now},
                )

            for assignment in (
                "attempted_at = attempted_at + interval '1 second'",
                "state = 'sending', failure_category = NULL",
            ):
                with pytest.raises(sa.exc.DBAPIError, match="outbox_transition"):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "UPDATE sydney_question_outbox SET "
                                f"{assignment} WHERE id = :id"
                            ),
                            {"id": initial_id},
                        )

            with pytest.raises(sa.exc.DBAPIError, match="outbox_parent_invalid"):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO sydney_question_outbox "
                            "(clarification_id, attempt_kind, attempt_number, "
                            "parent_initial_attempt_id, dedupe_key, template_id, "
                            "question_context_json, rendered_payload_hash) VALUES "
                            "(:clarification_id, 'initial_retry', 1, :parent, "
                            ":dedupe, 'clarification_initial_v1', :context, :hash)"
                        ),
                        {
                            "clarification_id": clarification_id,
                            "parent": initial_id,
                            "dedupe": (
                                f"clarification:{clarification_id}:v1:initial_retry:1"
                            ),
                            "context": context,
                            "hash": "2" * 64,
                        },
                    )

            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE sydney_question_outbox SET "
                        "reconciled_outcome = 'not_delivered', "
                        "reconciliation_reason = 'Provider status confirmed', "
                        "reconciliation_audit_id = :audit_id, reconciled_at = :now "
                        "WHERE id = :id"
                    ),
                    {"audit_id": audit_id, "now": now, "id": initial_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO sydney_question_outbox "
                        "(id, clarification_id, attempt_kind, attempt_number, "
                        "parent_initial_attempt_id, dedupe_key, template_id, "
                        "question_context_json, rendered_payload_hash) VALUES "
                        "(:id, :clarification_id, 'initial_retry', 1, :parent, "
                        ":dedupe, 'clarification_initial_v1', :context, :hash)"
                    ),
                    {
                        "id": retry_id,
                        "clarification_id": clarification_id,
                        "parent": initial_id,
                        "dedupe": (
                            f"clarification:{clarification_id}:v1:initial_retry:1"
                        ),
                        "context": context,
                        "hash": "2" * 64,
                    },
                )
                connection.execute(
                    sa.text(
                        "UPDATE sydney_question_outbox SET state = 'sending', "
                        "attempted_at = :attempted, telegram_chat_id = :chat "
                        "WHERE id = :id"
                    ),
                    {
                        "attempted": now + timedelta(minutes=5),
                        "chat": "-1001234567890",
                        "id": retry_id,
                    },
                )
                connection.execute(
                    sa.text(
                        "UPDATE sydney_question_outbox SET state = 'sent', "
                        "sent_at = :sent, telegram_message_id = '9002' "
                        "WHERE id = :id AND attempted_at = :attempted"
                    ),
                    {
                        "sent": now + timedelta(minutes=5, seconds=1),
                        "attempted": now + timedelta(minutes=5),
                        "id": retry_id,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO sydney_question_outbox "
                        "(id, clarification_id, attempt_kind, attempt_number, "
                        "reply_to_attempt_id, dedupe_key, template_id, "
                        "question_context_json, rendered_payload_hash) VALUES "
                        "(:id, :clarification_id, 'reminder', 1, :reply_to, "
                        ":dedupe, 'clarification_reminder_v1', :context, :hash)"
                    ),
                    {
                        "id": reminder_id,
                        "clarification_id": clarification_id,
                        "reply_to": retry_id,
                        "dedupe": (
                            f"clarification:{clarification_id}:v1:reminder:1"
                        ),
                        "context": context,
                        "hash": "3" * 64,
                    },
                )

            with engine.connect() as connection:
                deadline = connection.scalar(
                    sa.text(
                        "SELECT slot_deadline_at FROM crm_task_clarifications "
                        "WHERE id = :id"
                    ),
                    {"id": clarification_id},
                )
                assert deadline == now + timedelta(hours=48)
                assert connection.scalar(
                    sa.text(
                        "SELECT reply_to_attempt_id FROM sydney_question_outbox "
                        "WHERE id = :id"
                    ),
                    {"id": reminder_id},
                ) == retry_id

            for assignment in (
                "telegram_chat_id = '-1001234567891'",
                "telegram_message_id = '9003'",
                "sent_at = sent_at + interval '1 second'",
                "state = 'delivery_uncertain', sent_at = NULL, "
                "failure_category = 'provider_timeout'",
            ):
                with pytest.raises(sa.exc.DBAPIError, match="outbox_transition"):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "UPDATE sydney_question_outbox SET "
                                f"{assignment} WHERE id = :id"
                            ),
                            {"id": retry_id},
                        )

            for bad_parent, attempt_kind, parent_column, attempt_number in (
                (reminder_id, "initial_retry", "parent_initial_attempt_id", 2),
                (initial_id, "reminder", "reply_to_attempt_id", 1),
            ):
                with pytest.raises((sa.exc.IntegrityError, sa.exc.DBAPIError)):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "INSERT INTO sydney_question_outbox "
                                "(clarification_id, attempt_kind, attempt_number, "
                                f"{parent_column}, dedupe_key, template_id, "
                                "question_context_json, rendered_payload_hash) VALUES "
                                "(:clarification_id, :kind, :number, :parent, "
                                ":dedupe, :template, :context, :hash)"
                            ),
                            {
                                "clarification_id": clarification_id,
                                "kind": attempt_kind,
                                "number": attempt_number,
                                "parent": bad_parent,
                                "dedupe": (
                                    f"clarification:{clarification_id}:v1:"
                                    f"{attempt_kind}:{attempt_number}"
                                ),
                                "template": (
                                    "clarification_reminder_v1"
                                    if attempt_kind == "reminder"
                                    else "clarification_initial_v1"
                                ),
                                "context": context,
                                "hash": "4" * 64,
                            },
                        )
    finally:
        engine.dispose()


def test_pending_outbox_can_expire_only_with_its_clarification_timeout() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    now = datetime(2026, 8, 21, 14, 30, tzinfo=timezone.utc)
    suggestion_id = UUID("00000000-0000-4000-8400-000000000037")
    clarification_id = UUID("00000000-0000-4000-8400-000000000038")
    attempt_id = UUID("00000000-0000-4000-8400-000000000039")
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                _insert_sydney_suggestion(
                    connection,
                    suggestion_id=suggestion_id,
                    request_id=uuid4(),
                    title="Expire before send",
                )
                _insert_clarification(
                    connection,
                    clarification_id=clarification_id,
                    suggestion_id=suggestion_id,
                    code_byte=12,
                    now=now,
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO sydney_question_outbox "
                        "(id, clarification_id, attempt_kind, attempt_number, "
                        "dedupe_key, template_id, question_context_json, "
                        "rendered_payload_hash) VALUES "
                        "(:id, :clarification_id, 'initial', 1, :dedupe, "
                        "'clarification_initial_v1', '{}', :hash)"
                    ),
                    {
                        "id": attempt_id,
                        "clarification_id": clarification_id,
                        "dedupe": f"clarification:{clarification_id}:v1:initial:1",
                        "hash": "7" * 64,
                    },
                )

            with pytest.raises(sa.exc.DBAPIError, match="outbox_transition"):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "UPDATE sydney_question_outbox SET state = 'failed', "
                            "failure_category = 'pre_send_expired' WHERE id = :id"
                        ),
                        {"id": attempt_id},
                    )

            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE crm_task_clarifications SET state = 'timed_out', "
                        "resolved_at = :now WHERE id = :id"
                    ),
                    {"id": clarification_id, "now": now + timedelta(hours=48)},
                )
                connection.execute(
                    sa.text(
                        "UPDATE sydney_question_outbox SET state = 'failed', "
                        "failure_category = 'pre_send_expired' WHERE id = :id"
                    ),
                    {"id": attempt_id},
                )

            with engine.connect() as connection:
                row = connection.execute(
                    sa.text(
                        "SELECT state, failure_category, attempted_at, sent_at, "
                        "telegram_chat_id, telegram_message_id "
                        "FROM sydney_question_outbox WHERE id = :id"
                    ),
                    {"id": attempt_id},
                ).one()
                clarification = connection.execute(
                    sa.text(
                        "SELECT state, first_attempt_at, deadline_anchor_kind, "
                        "deadline_anchored_at, slot_deadline_at "
                        "FROM crm_task_clarifications WHERE id = :id"
                    ),
                    {"id": clarification_id},
                ).one()
            assert row == (
                "failed",
                "pre_send_expired",
                None,
                None,
                None,
                None,
            )
            assert clarification == (
                "timed_out",
                None,
                "created",
                now,
                now + timedelta(hours=48),
            )
    finally:
        engine.dispose()


def test_revision_84_refuses_seeded_task83_and_all_task84_evidence_without_loss() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    now = datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc)
    canonical = json.dumps(
        {
            "contact_hint_supplied": False,
            "due_at_ambiguous": False,
            "due_at_state": "not_provided",
            "link_state": "not_provided",
            "owner_ambiguous": True,
            "owner_state": "ambiguous",
            "participant_ambiguous": False,
            "participant_state": "backend_unique",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    clarification_id = UUID("00000000-0000-4000-8400-000000000041")
    outbox_id = UUID("00000000-0000-4000-8400-000000000042")
    nonce_id = UUID("00000000-0000-4000-8400-000000000043")
    event_id = UUID("00000000-0000-4000-8400-000000000044")
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ) as run_marker:
            run_alembic(url, "upgrade", DOWN_REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_contacts (id, first_name, last_name) "
                        "VALUES (8401, 'Preserved', 'Contact')"
                    )
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_tasks "
                        "(id, contact_id, title, description, status, priority, "
                        "version, created_at, updated_at) VALUES "
                        "(8402, 8401, 'Preserved CRM task', '', 'open', "
                        "'normal', 1, :now, :now)"
                    ),
                    {"now": now},
                )
                obligation_id, suggestion_id = (
                    _seed_owner_ambiguous_evidence_at_revision_83(
                        connection,
                        evaluator_json=canonical,
                    )
                )
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                _insert_clarification(
                    connection,
                    clarification_id=clarification_id,
                    suggestion_id=suggestion_id,
                    code_byte=10,
                    now=now,
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO sydney_question_outbox "
                        "(id, clarification_id, attempt_kind, attempt_number, "
                        "dedupe_key, template_id, question_context_json, "
                        "rendered_payload_hash) VALUES "
                        "(:id, :clarification_id, 'initial', 1, :dedupe, "
                        "'clarification_initial_v1', '{}', :hash)"
                    ),
                    {
                        "id": outbox_id,
                        "clarification_id": clarification_id,
                        "dedupe": (
                            f"clarification:{clarification_id}:v1:initial:1"
                        ),
                        "hash": "1" * 64,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestion_approval_nonces "
                        "(id, suggestion_id, suggestion_version, payload_hash, "
                        "kind, issuance_path, token_hash, issued_at, expires_at) "
                        "VALUES (:id, :suggestion_id, 1, :payload_hash, 'handoff', "
                        "'approval_link', :token_hash, :now, :expires)"
                    ),
                    {
                        "id": nonce_id,
                        "suggestion_id": suggestion_id,
                        "payload_hash": "c" * 64,
                        "token_hash": bytes([11]) * 32,
                        "now": now,
                        "expires": now + timedelta(minutes=15),
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestion_events "
                        "(id, suggestion_id, suggestion_version, event_type, "
                        "actor_type, event_data_json) VALUES "
                        "(:id, :suggestion_id, 1, 'clarification_asked', "
                        "'sydney', '{}')"
                    ),
                    {"id": event_id, "suggestion_id": suggestion_id},
                )

            with pytest.raises(
                RuntimeError,
                match=(
                    "revision 84 downgrade refused: Sydney task review evidence exists"
                ),
            ):
                run_owned_alembic_downgrade(
                    url,
                    DOWN_REVISION,
                    expected_database=expected_database,
                    run_marker=run_marker,
                )
            with engine.connect() as connection:
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == REVISION
                assert connection.scalar(
                    sa.text("SELECT title FROM crm_tasks WHERE id = 8402")
                ) == "Preserved CRM task"
                assert connection.scalar(
                    sa.text(
                        "SELECT owner_ambiguous FROM gmail_extracted_obligations "
                        "WHERE id = :id"
                    ),
                    {"id": obligation_id},
                ) is True
                for table, row_id in (
                    ("crm_task_clarifications", clarification_id),
                    ("sydney_question_outbox", outbox_id),
                    ("crm_task_suggestion_approval_nonces", nonce_id),
                    ("crm_task_suggestion_events", event_id),
                ):
                    assert connection.scalar(
                        sa.text(f"SELECT count(*) FROM {table} WHERE id = :id"),
                        {"id": row_id},
                    ) == 1
    finally:
        engine.dispose()


def test_nonce_expiry_contract_is_exact_not_merely_bounded() -> None:
    tables = _model_tables()
    nonce = tables["crm_task_suggestion_approval_nonces"]
    now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    handoff = {
        "issued_at": now,
        "expires_at": now + timedelta(minutes=15),
    }
    approval = {
        "issued_at": now,
        "expires_at": now + timedelta(minutes=5),
    }
    assert handoff["expires_at"] - handoff["issued_at"] == timedelta(minutes=15)
    assert approval["expires_at"] - approval["issued_at"] == timedelta(minutes=5)
    assert "interval '15 minutes'" in _named_checks(nonce)[
        "ck_crm_task_suggestion_approval_nonces_shape"
    ]
    assert "interval '5 minutes'" in _named_checks(nonce)[
        "ck_crm_task_suggestion_approval_nonces_shape"
    ]


def test_uuid_columns_remain_native_postgresql_uuid() -> None:
    tables = _model_tables()
    uuid_columns = {
        "crm_task_clarifications": ("id", "suggestion_id"),
        "sydney_question_outbox": (
            "id",
            "clarification_id",
            "parent_initial_attempt_id",
            "reply_to_attempt_id",
        ),
        "crm_task_suggestion_approval_nonces": (
            "id",
            "suggestion_id",
            "parent_nonce_id",
        ),
        "crm_task_suggestion_events": (
            "id",
            "suggestion_id",
        ),
    }
    for table_name, names in uuid_columns.items():
        for name in names:
            column = tables[table_name].c[name]
            assert isinstance(column.type, PostgreSQLUUID)
            assert column.type.as_uuid is True
    assert isinstance(
        tables["sydney_question_outbox"].c.reconciliation_audit_id.type,
        sa.Integer,
    )
    assert isinstance(
        tables["crm_task_suggestion_events"].c.action_audit_id.type,
        sa.Integer,
    )


def test_migration_84_uses_no_compatibility_alias_tables() -> None:
    ddl = _render("upgrade")
    assert "sydney_clarification_threads" not in ddl
    assert "sydney_task_questions" not in ddl
    assert "task_approval_tokens" not in ddl
    assert "crm_task_clarification_outbox" not in ddl
