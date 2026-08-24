from __future__ import annotations

import importlib
import importlib.util
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.schema import CreateIndex

from tests.gmail_task_postgres import (
    fail_closed,
    gmail_task_test_url,
    owned_empty_test_schema,
    run_alembic,
    run_owned_alembic_downgrade,
    sync_test_url,
    verify_exact_ownership,
)


REVISION = "83c6f4e8a1b2"
DOWN_REVISION = "82b5e3d7f0a1"
TABLES = (
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

TASK5_OVERLAY_COLUMNS = {
    "gmail_extracted_obligations": {"owner_ambiguous"},
    "crm_task_suggestions": {
        "owner_clarification_pending",
        "task_details_clarification_pending",
        "contact_resolution_state",
        "contact_resolution_hash",
    },
}
TASK5_OVERLAY_INDEXES = {
    "gmail_extracted_obligations": {
        "ix_gmail_extracted_obligations_suggestion_owner_ambiguous"
    },
}
TASK5_OVERLAY_CHECKS = {
    "crm_task_suggestions": {
        "ck_crm_task_suggestions_clarification_pending_cause",
        "ck_crm_task_suggestions_contact_resolution",
    },
}

NULLABLE_COLUMNS = {
    "gmail_sync_accounts": {
        "committed_history_id",
        "reseed_history_id",
        "blocked_reason",
        "last_succeeded_at",
        "last_error_category",
        "last_error_message",
    },
    "gmail_sync_runs": {
        "terminal_history_id",
        "next_page_token",
        "lease_owner",
        "lease_expires_at",
        "failure_category",
        "failure_message",
        "discovered_at",
        "completed_at",
    },
    "gmail_sync_page_checkpoints": {
        "request_page_token",
        "next_page_token",
        "discovered_history_id_min",
        "discovered_history_id_max",
    },
    "gmail_missing_message_incidents": {
        "request_page_token",
        "alerted_at",
        "acknowledged_by_admin_id",
        "acknowledgement_reason",
        "action_audit_id",
        "acknowledged_at",
    },
    "gmail_message_receipts": {
        "sender_hmac",
        "subject_preview",
        "body_hash",
        "classification",
        "failure_category",
        "failure_message",
        "processing_started_at",
        "processed_at",
    },
    "gmail_message_origins": {
        "request_id",
        "retry_of_origin_id",
        "canonical_send_hash",
        "canonical_envelope_hash",
        "canonical_body_hash",
        "intended_thread_id",
        "gmail_message_id",
        "gmail_thread_id",
        "reconciled_outcome",
        "action_audit_id",
        "failure_category",
        "failure_message",
        "quarantine_category",
        "quarantine_evidence",
        "reconciled_at",
    },
    "gmail_extraction_attempts": {
        "error_category",
        "error_message",
        "completed_at",
    },
    "gmail_extracted_obligations": {
        "due_at",
        "timezone_basis",
        "requested_owner",
        "requested_link_type",
        "requested_link_id",
        "contact_hint",
        "reconciled_suggestion_id",
        "reconciled_suppression_id",
    },
    "crm_task_suggestions": {
        "gmail_account_id",
        "gmail_thread_id",
        "duplicate_of_suggestion_id",
        "contact_id",
        "due_at",
        "source_request_id",
        "application_idempotency_key",
        "applied_task_id",
        "primary_instance_digest",
        "contact_resolution_hash",
    },
    "crm_task_suggestion_sources": set(),
    "crm_task_suggestion_suppressions": {
        "reprocess_override_at",
        "reprocess_override_consumed_at",
        "reprocess_override_by_admin_id",
        "reprocess_override_audit_id",
    },
    "gmail_backfill_requests": {
        "run_id",
        "result_category",
        "result_message",
        "started_at",
        "completed_at",
    },
}

EXPECTED_FOREIGN_KEYS = {
    "gmail_sync_accounts": {},
    "gmail_sync_runs": {
        "fk_gmail_sync_runs_account_id": (
            ("account_id",),
            "gmail_sync_accounts",
            ("id",),
            "RESTRICT",
        )
    },
    "gmail_sync_page_checkpoints": {
        "fk_gmail_sync_page_checkpoints_run_id": (
            ("run_id",),
            "gmail_sync_runs",
            ("id",),
            "RESTRICT",
        )
    },
    "gmail_missing_message_incidents": {
        "fk_gmail_missing_message_incidents_account_id": (
            ("account_id",),
            "gmail_sync_accounts",
            ("id",),
            "RESTRICT",
        ),
        "fk_gmail_missing_message_incidents_run_account": (
            ("run_id", "account_id"),
            "gmail_sync_runs",
            ("id", "account_id"),
            "RESTRICT",
        ),
        "fk_gmail_missing_message_incidents_admin_id": (
            ("acknowledged_by_admin_id",),
            "admin_users",
            ("id",),
            "RESTRICT",
        ),
        "fk_gmail_missing_message_incidents_audit_id": (
            ("action_audit_id",),
            "agent_action_audits",
            ("id",),
            "RESTRICT",
        ),
    },
    "gmail_message_receipts": {
        "fk_gmail_message_receipts_account_id": (
            ("account_id",),
            "gmail_sync_accounts",
            ("id",),
            "RESTRICT",
        )
    },
    "gmail_message_origins": {
        "fk_gmail_message_origins_account_id": (
            ("account_id",),
            "gmail_sync_accounts",
            ("id",),
            "RESTRICT",
        ),
        "fk_gmail_message_origins_retry_of_origin_id": (
            ("retry_of_origin_id",),
            "gmail_message_origins",
            ("id",),
            "RESTRICT",
        ),
        "fk_gmail_message_origins_action_audit_id": (
            ("action_audit_id",),
            "agent_action_audits",
            ("id",),
            "RESTRICT",
        ),
    },
    "gmail_extraction_attempts": {
        "fk_gmail_extraction_attempts_receipt_id": (
            ("receipt_id",),
            "gmail_message_receipts",
            ("id",),
            "RESTRICT",
        )
    },
    "gmail_extracted_obligations": {
        "fk_gmail_extracted_obligations_receipt_id": (
            ("receipt_id",),
            "gmail_message_receipts",
            ("id",),
            "RESTRICT",
        ),
        "fk_gmail_extracted_obligations_attempt_receipt": (
            ("extraction_attempt_id", "receipt_id"),
            "gmail_extraction_attempts",
            ("id", "receipt_id"),
            "RESTRICT",
        ),
        "fk_gmail_extracted_obligations_suggestion_id": (
            ("reconciled_suggestion_id",),
            "crm_task_suggestions",
            ("id",),
            "RESTRICT",
        ),
        "fk_gmail_extracted_obligations_suppression_id": (
            ("reconciled_suppression_id",),
            "crm_task_suggestion_suppressions",
            ("id",),
            "RESTRICT",
        ),
    },
    "crm_task_suggestions": {
        "fk_crm_task_suggestions_gmail_account_id": (
            ("gmail_account_id",),
            "gmail_sync_accounts",
            ("id",),
            "RESTRICT",
        ),
        "fk_crm_task_suggestions_duplicate_id": (
            ("duplicate_of_suggestion_id",),
            "crm_task_suggestions",
            ("id",),
            "RESTRICT",
        ),
        "fk_crm_task_suggestions_duplicate_gmail_scope": (
            (
                "duplicate_of_suggestion_id",
                "gmail_account_id",
                "gmail_thread_id",
            ),
            "crm_task_suggestions",
            ("id", "gmail_account_id", "gmail_thread_id"),
            "RESTRICT",
        ),
        "fk_crm_task_suggestions_duplicate_source_scope": (
            (
                "duplicate_of_suggestion_id",
                "source_type",
                "source_scope_key",
            ),
            "crm_task_suggestions",
            ("id", "source_type", "source_scope_key"),
            "RESTRICT",
        ),
        "fk_crm_task_suggestions_contact_id": (
            ("contact_id",),
            "crm_contacts",
            ("id",),
            "RESTRICT",
        ),
        "fk_crm_task_suggestions_applied_task_id": (
            ("applied_task_id",),
            "crm_tasks",
            ("id",),
            "RESTRICT",
        ),
    },
    "crm_task_suggestion_sources": {
        "fk_crm_task_suggestion_sources_suggestion_origin": (
            ("suggestion_id", "gmail_account_id", "gmail_thread_id"),
            "crm_task_suggestions",
            ("id", "gmail_account_id", "gmail_thread_id"),
            "RESTRICT",
        ),
        "fk_crm_task_suggestion_sources_obligation_receipt": (
            ("obligation_id", "receipt_id"),
            "gmail_extracted_obligations",
            ("id", "receipt_id"),
            "RESTRICT",
        ),
        "fk_crm_task_suggestion_sources_obligation_disposition": (
            ("obligation_id", "receipt_id", "suggestion_id"),
            "gmail_extracted_obligations",
            ("id", "receipt_id", "reconciled_suggestion_id"),
            "RESTRICT",
        ),
        "fk_crm_task_suggestion_sources_receipt_origin": (
            (
                "receipt_id",
                "gmail_account_id",
                "gmail_thread_id",
                "direction",
            ),
            "gmail_message_receipts",
            ("id", "account_id", "gmail_thread_id", "direction"),
            "RESTRICT",
        ),
    },
    "crm_task_suggestion_suppressions": {
        "fk_crm_task_suggestion_suppressions_admin_id": (
            ("dismissed_by_admin_id",),
            "admin_users",
            ("id",),
            "RESTRICT",
        ),
        "fk_crm_task_suggestion_suppressions_audit_id": (
            ("dismissal_audit_id",),
            "agent_action_audits",
            ("id",),
            "RESTRICT",
        ),
        "fk_crm_task_suggestion_suppressions_override_admin_id": (
            ("reprocess_override_by_admin_id",),
            "admin_users",
            ("id",),
            "RESTRICT",
        ),
        "fk_crm_task_suggestion_suppressions_override_audit_id": (
            ("reprocess_override_audit_id",),
            "agent_action_audits",
            ("id",),
            "RESTRICT",
        ),
    },
    "gmail_backfill_requests": {
        "fk_gmail_backfill_requests_account_id": (
            ("account_id",),
            "gmail_sync_accounts",
            ("id",),
            "RESTRICT",
        ),
        "fk_gmail_backfill_requests_administrator_id": (
            ("administrator_id",),
            "admin_users",
            ("id",),
            "RESTRICT",
        ),
        "fk_gmail_backfill_requests_audit_id": (
            ("audit_id",),
            "agent_action_audits",
            ("id",),
            "RESTRICT",
        ),
        "fk_gmail_backfill_requests_run_account": (
            ("run_id", "account_id"),
            "gmail_sync_runs",
            ("id", "account_id"),
            "RESTRICT",
        ),
    },
}

TYPE_GROUPS = {
    "gmail_sync_accounts": {
        "uuid": ("id",),
        "datetime": ("last_succeeded_at", "created_at", "updated_at"),
        "strings": {
            320: ("workspace_email",),
            64: (
                "committed_history_id",
                "reseed_history_id",
                "blocked_reason",
                "last_error_category",
            ),
            32: ("mode",),
            500: ("last_error_message",),
        },
    },
    "gmail_sync_runs": {
        "uuid": ("id", "account_id"),
        "datetime": (
            "lease_expires_at",
            "started_at",
            "updated_at",
            "discovered_at",
            "completed_at",
        ),
        "strings": {
            64: (
                "start_history_id",
                "terminal_history_id",
                "failure_category",
            ),
            1024: ("next_page_token",),
            32: ("run_kind", "state"),
            128: ("lease_owner",),
            500: ("failure_message",),
        },
    },
    "gmail_sync_page_checkpoints": {
        "uuid": ("id", "run_id"),
        "integer": ("page_number", "receipt_count"),
        "datetime": ("committed_at",),
        "strings": {
            1024: ("request_page_token", "next_page_token"),
            64: (
                "discovered_history_id_min",
                "discovered_history_id_max",
            ),
        },
    },
    "gmail_missing_message_incidents": {
        "uuid": ("id", "account_id", "run_id"),
        "integer": (
            "page_number",
            "version",
            "acknowledged_by_admin_id",
            "action_audit_id",
        ),
        "datetime": (
            "alerted_at",
            "created_at",
            "updated_at",
            "acknowledged_at",
        ),
        "strings": {
            255: ("gmail_message_id", "gmail_thread_id"),
            64: ("start_history_id",),
            1024: ("request_page_token",),
            32: ("state", "alert_state"),
            500: ("acknowledgement_reason",),
        },
    },
    "gmail_message_receipts": {
        "uuid": ("id", "account_id"),
        "text": ("recipient_hmacs_json", "labels_json"),
        "datetime": (
            "message_at",
            "processing_started_at",
            "processed_at",
            "created_at",
            "updated_at",
        ),
        "strings": {
            255: ("gmail_message_id", "gmail_thread_id", "subject_preview"),
            16: ("direction",),
            64: (
                "sender_hmac",
                "body_hash",
                "classification",
                "failure_category",
            ),
            32: ("processing_state",),
            500: ("failure_message",),
        },
    },
    "gmail_message_origins": {
        "uuid": ("id", "account_id", "request_id", "retry_of_origin_id"),
        "integer": ("version", "action_audit_id"),
        "datetime": ("reconciled_at", "created_at", "updated_at"),
        "strings": {
            64: (
                "canonical_send_hash",
                "canonical_envelope_hash",
                "canonical_body_hash",
                "failure_category",
                "quarantine_category",
            ),
            255: (
                "intended_thread_id",
                "gmail_message_id",
                "gmail_thread_id",
            ),
            32: ("origin_kind", "delivery_state", "reconciled_outcome"),
            500: ("failure_message", "quarantine_evidence"),
        },
    },
    "gmail_extraction_attempts": {
        "uuid": ("id", "receipt_id"),
        "integer": ("attempt_number",),
        "datetime": ("started_at", "completed_at"),
        "strings": {
            64: ("schema_version", "error_category"),
            32: ("state",),
            500: ("error_message",),
        },
    },
    "gmail_extracted_obligations": {
        "uuid": (
            "id",
            "receipt_id",
            "extraction_attempt_id",
            "reconciled_suggestion_id",
            "reconciled_suppression_id",
        ),
        "text": ("description", "evaluator_result_json"),
        "boolean": ("owner_ambiguous", "taxonomy_fallback"),
        "numeric_5_4": ("confidence",),
        "datetime": ("due_at", "created_at"),
        "strings": {
            128: ("action_key", "requested_owner"),
            64: (
                "schema_version",
                "timezone_basis",
                "requested_link_type",
                "obligation_fingerprint",
                "identity_instance_digest",
                "reconciliation_material_hash",
            ),
            255: ("title", "requested_link_id", "contact_hint"),
            32: ("priority",),
            500: ("evidence_preview",),
        },
    },
    "crm_task_suggestions": {
        "uuid": (
            "id",
            "gmail_account_id",
            "duplicate_of_suggestion_id",
            "source_request_id",
            "application_idempotency_key",
        ),
        "integer": ("contact_id", "applied_task_id", "version"),
        "text": ("description",),
        "numeric_5_4": ("confidence",),
        "array_string_64": ("blocker_codes",),
        "boolean": (
            "owner_clarification_pending",
            "task_details_clarification_pending",
        ),
        "datetime": ("due_at", "created_at", "updated_at"),
        "strings": {
            255: ("gmail_thread_id", "title"),
            32: (
                "priority",
                "task_status",
                "state",
                "clarification_state",
                "contact_resolution_state",
            ),
            64: (
                "source_type",
                "payload_hash",
                "model_schema_version",
                "obligation_fingerprint",
                "primary_instance_digest",
                "contact_resolution_hash",
            ),
            512: ("source_scope_key",),
            128: ("source_action_key",),
            500: ("rationale",),
        },
    },
    "crm_task_suggestion_sources": {
        "uuid": (
            "id",
            "suggestion_id",
            "obligation_id",
            "receipt_id",
            "gmail_account_id",
        ),
        "datetime": ("created_at",),
        "strings": {
            16: ("direction",),
            255: ("gmail_thread_id", "source_label"),
        },
    },
    "crm_task_suggestion_suppressions": {
        "uuid": ("id",),
        "integer": (
            "dismissed_by_admin_id",
            "dismissal_audit_id",
            "reprocess_override_by_admin_id",
            "reprocess_override_audit_id",
        ),
        "datetime": (
            "dismissed_at",
            "reprocess_override_at",
            "reprocess_override_consumed_at",
        ),
        "strings": {
            64: (
                "source_type",
                "obligation_fingerprint",
                "identity_instance_digest",
            ),
            512: ("source_scope_key",),
            128: ("source_action_key",),
            500: ("dismissal_reason",),
        },
    },
    "gmail_backfill_requests": {
        "uuid": ("id", "account_id", "run_id"),
        "integer": ("administrator_id", "audit_id"),
        "datetime": (
            "window_start",
            "window_end",
            "created_at",
            "started_at",
            "completed_at",
        ),
        "strings": {
            500: ("reason", "result_message"),
            64: (
                "expired_history_id",
                "reseed_history_id",
                "result_category",
            ),
            32: ("state",),
        },
    },
}

EXPECTED_SERVER_DEFAULTS = {
    "gmail_sync_accounts": {
        "id": "uuid",
        "mode": "shadow",
        "created_at": "now",
        "updated_at": "now",
    },
    "gmail_sync_runs": {
        "id": "uuid",
        "state": "running",
        "started_at": "now",
        "updated_at": "now",
    },
    "gmail_sync_page_checkpoints": {
        "id": "uuid",
        "receipt_count": "0",
        "committed_at": "now",
    },
    "gmail_missing_message_incidents": {
        "id": "uuid",
        "state": "pending",
        "version": "1",
        "alert_state": "pending",
        "created_at": "now",
        "updated_at": "now",
    },
    "gmail_message_receipts": {
        "id": "uuid",
        "recipient_hmacs_json": "[]",
        "labels_json": "[]",
        "processing_state": "pending",
        "created_at": "now",
        "updated_at": "now",
    },
    "gmail_message_origins": {
        "id": "uuid",
        "version": "1",
        "created_at": "now",
        "updated_at": "now",
    },
    "gmail_extraction_attempts": {
        "id": "uuid",
        "state": "running",
        "started_at": "now",
    },
    "gmail_extracted_obligations": {
        "id": "uuid",
        "description": "",
        "priority": "normal",
        "confidence": "0",
        "evaluator_result_json": "{}",
        "evidence_preview": "",
        "created_at": "now",
    },
    "crm_task_suggestions": {
        "id": "uuid",
        "description": "",
        "priority": "normal",
        "task_status": "open",
        "state": "pending_review",
        "clarification_state": "not_required",
        "blocker_codes": "{}",
        "confidence": "0",
        "rationale": "",
        "version": "1",
        "created_at": "now",
        "updated_at": "now",
    },
    "crm_task_suggestion_sources": {"id": "uuid", "created_at": "now"},
    "crm_task_suggestion_suppressions": {
        "id": "uuid",
        "dismissed_at": "now",
    },
    "gmail_backfill_requests": {
        "id": "uuid",
        "state": "requested",
        "created_at": "now",
    },
}


def _backend_root() -> Path:
    return Path(__file__).parents[1]


def _revision_path() -> Path:
    return (
        _backend_root()
        / "alembic"
        / "versions"
        / "83c6f4e8a1b2_add_gmail_task_intake.py"
    )


def _load_revision():
    revision_path = _revision_path()
    assert revision_path.is_file(), f"missing migration: {revision_path.name}"
    spec = importlib.util.spec_from_file_location(
        "gmail_task_intake_revision_83c6f4e8a1b2",
        revision_path,
    )
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


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


def _named_unique_columns(table: sa.Table) -> dict[str, tuple[str, ...]]:
    return {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint) and constraint.name is not None
    }


def _named_checks(table: sa.Table) -> dict[str, str]:
    return {
        constraint.name: " ".join(str(constraint.sqltext).split())
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint) and constraint.name is not None
    }


def _indexes(table: sa.Table) -> dict[str, sa.Index]:
    return {index.name: index for index in table.indexes}


def _compiled_index(index: sa.Index) -> str:
    return str(CreateIndex(index).compile(dialect=postgresql.dialect()))


def _model_tables() -> dict[str, sa.Table]:
    module = importlib.import_module("models.gmail_task_intake")
    classes = (
        module.GmailSyncAccount,
        module.GmailSyncRun,
        module.GmailSyncPageCheckpoint,
        module.GmailMissingMessageIncident,
        module.GmailMessageReceipt,
        module.GmailMessageOrigin,
        module.GmailExtractionAttempt,
        module.GmailExtractedObligation,
        module.CRMTaskSuggestion,
        module.CRMTaskSuggestionSource,
        module.CRMTaskSuggestionSuppression,
        module.GmailBackfillRequest,
    )
    return {model.__table__.name: model.__table__ for model in classes}


def _assert_uuid(column: sa.Column, *, nullable: bool) -> None:
    assert isinstance(column.type, PostgreSQLUUID)
    assert column.type.as_uuid is True
    assert column.nullable is nullable


def _type_signature(column_type: sa.types.TypeEngine) -> tuple[object, ...]:
    if isinstance(column_type, postgresql.ARRAY):
        item_type = column_type.item_type
        assert isinstance(item_type, sa.String)
        return ("array_string", item_type.length)
    if isinstance(column_type, PostgreSQLUUID):
        return ("uuid", column_type.as_uuid)
    if isinstance(column_type, sa.Text):
        return ("text",)
    if isinstance(column_type, sa.Boolean):
        return ("boolean",)
    if isinstance(column_type, sa.String):
        return ("string", column_type.length)
    if isinstance(column_type, sa.Integer):
        return ("integer",)
    if isinstance(column_type, sa.DateTime):
        return ("datetime", column_type.timezone)
    if isinstance(column_type, sa.Numeric):
        return ("numeric", column_type.precision, column_type.scale)
    raise AssertionError(f"uncontracted SQL type: {column_type!r}")


def _expected_type_signatures(table_name: str) -> dict[str, tuple[object, ...]]:
    groups = TYPE_GROUPS[table_name]
    expected: dict[str, tuple[object, ...]] = {}
    for name in groups.get("uuid", ()):
        expected[name] = ("uuid", True)
    for name in groups.get("integer", ()):
        expected[name] = ("integer",)
    for name in groups.get("datetime", ()):
        expected[name] = ("datetime", True)
    for name in groups.get("text", ()):
        expected[name] = ("text",)
    for name in groups.get("boolean", ()):
        expected[name] = ("boolean",)
    for name in groups.get("numeric_5_4", ()):
        expected[name] = ("numeric", 5, 4)
    for name in groups.get("array_string_64", ()):
        expected[name] = ("array_string", 64)
    for length, names in groups.get("strings", {}).items():
        for name in names:
            expected[name] = ("string", length)
    return expected


def _canonical_default(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).strip().split())
    lowered = normalized.lower()
    if "gen_random_uuid()" in lowered:
        return "uuid"
    if lowered in {"now()", "current_timestamp"}:
        return "now"
    literal_match = re.fullmatch(r"'([^']*)'(?:::[a-zA-Z0-9_ \[\]]+)?", normalized)
    if literal_match:
        return literal_match.group(1)
    if normalized in {"0", "1"}:
        return normalized
    return normalized


def _normalized_sql(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).strip().split()).lower()
    normalized = normalized.replace("character varying", "varchar")
    normalized = re.sub(
        r"::(?:varchar|text|numeric|interval)(?:\[\])?",
        "",
        normalized,
    )
    normalized = re.sub(
        r"trim\(both from ([a-z_][a-z0-9_]*)\)",
        r"trim(\1)",
        normalized,
    )
    normalized = re.sub(r"\(([a-z_][a-z0-9_]*)\)", r"\1", normalized)
    normalized = re.sub(
        r"([a-z_][a-z0-9_]*)\s*=\s*any\s*\(\s*\(?\s*"
        r"array\[(.*?)\]\s*\)?\s*\)",
        lambda match: f"{match.group(1)} in ({match.group(2)})",
        normalized,
    )
    normalized = re.sub(r"\binterval\s+('[^']*')", r"\1", normalized)
    while normalized.startswith("(") and normalized.endswith(")"):
        depth = 0
        wraps_entire_expression = True
        for index, character in enumerate(normalized):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(normalized) - 1:
                    wraps_entire_expression = False
                    break
        if not wraps_entire_expression:
            break
        normalized = normalized[1:-1].strip()
    binary_group = re.fullmatch(
        r"\((.+)\)\s+(and|or)\s+\((.+)\)",
        normalized,
    )
    if binary_group:
        normalized = (
            f"{binary_group.group(1)} {binary_group.group(2)} {binary_group.group(3)}"
        )
    return normalized


def _normalized_check_sql(value: object | None) -> str | None:
    normalized = _normalized_sql(value)
    if normalized is None:
        return None
    return normalized.replace("(", "").replace(")", "")


def _model_foreign_key_contract(table: sa.Table) -> dict[str, tuple[object, ...]]:
    result: dict[str, tuple[object, ...]] = {}
    for constraint in table.foreign_key_constraints:
        assert constraint.name is not None
        element = tuple(constraint.elements)
        assert element
        target_table = element[0].column.table.name
        result[constraint.name] = (
            tuple(column.name for column in constraint.columns),
            target_table,
            tuple(item.column.name for item in element),
            constraint.ondelete,
        )
    return result


def _model_index_contract(table: sa.Table) -> dict[str, tuple[object, ...]]:
    return {
        index.name: (
            tuple(column.name for column in index.columns),
            bool(index.unique),
            _normalized_sql(index.dialect_options["postgresql"].get("where")),
        )
        for index in table.indexes
    }


def _inspector_index_contract(
    inspector: sa.Inspector,
    table_name: str,
) -> dict[str, tuple[object, ...]]:
    return {
        index["name"]: (
            tuple(index["column_names"]),
            bool(index["unique"]),
            _normalized_sql(index.get("dialect_options", {}).get("postgresql_where")),
        )
        for index in inspector.get_indexes(table_name)
        if index["name"] and not index.get("duplicates_constraint")
    }


def _inspector_unique_contract(
    inspector: sa.Inspector,
    table_name: str,
) -> dict[str, tuple[str, ...]]:
    return {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint["name"]
    }


def _inspector_foreign_key_contract(
    inspector: sa.Inspector,
    table_name: str,
) -> dict[str, tuple[object, ...]]:
    return {
        constraint["name"]: (
            tuple(constraint["constrained_columns"]),
            constraint["referred_table"],
            tuple(constraint["referred_columns"]),
            constraint.get("options", {}).get("ondelete"),
        )
        for constraint in inspector.get_foreign_keys(table_name)
        if constraint["name"]
    }


def _inspector_check_contract(
    inspector: sa.Inspector,
    table_name: str,
) -> dict[str, str | None]:
    return {
        constraint["name"]: _normalized_check_sql(constraint["sqltext"])
        for constraint in inspector.get_check_constraints(table_name)
        if constraint["name"]
    }


def _assert_real_schema_matches_models(
    connection: sa.Connection,
    tables: dict[str, sa.Table],
    *,
    omit_task5_overlays: bool = False,
) -> None:
    inspector = sa.inspect(connection)
    assert set(TABLES).issubset(inspector.get_table_names())
    for table_name, model_table in tables.items():
        omitted_columns = (
            TASK5_OVERLAY_COLUMNS.get(table_name, set())
            if omit_task5_overlays
            else set()
        )
        omitted_indexes = (
            TASK5_OVERLAY_INDEXES.get(table_name, set())
            if omit_task5_overlays
            else set()
        )
        omitted_checks = (
            TASK5_OVERLAY_CHECKS.get(table_name, set())
            if omit_task5_overlays
            else set()
        )
        inspected_columns = inspector.get_columns(table_name)
        assert tuple(column["name"] for column in inspected_columns) == tuple(
            name for name in model_table.columns.keys() if name not in omitted_columns
        )
        assert {
            column["name"] for column in inspected_columns if column["nullable"]
        } == NULLABLE_COLUMNS[table_name] - omitted_columns
        assert {
            column["name"]: _type_signature(column["type"])
            for column in inspected_columns
        } == {
            name: signature
            for name, signature in _expected_type_signatures(table_name).items()
            if name not in omitted_columns
        }
        assert {
            column["name"]: _canonical_default(column["default"])
            for column in inspected_columns
            if column["default"] is not None
        } == {
            name: default
            for name, default in EXPECTED_SERVER_DEFAULTS[table_name].items()
            if name not in omitted_columns
        }
        primary_key = inspector.get_pk_constraint(table_name)
        assert primary_key["constrained_columns"] == ["id"]
        assert primary_key["name"] == f"{table_name}_pkey"
        assert _inspector_unique_contract(
            inspector, table_name
        ) == _named_unique_columns(model_table)
        assert (
            _inspector_foreign_key_contract(inspector, table_name)
            == EXPECTED_FOREIGN_KEYS[table_name]
        )
        assert _inspector_check_contract(inspector, table_name) == {
            name: _normalized_check_sql(sqltext)
            for name, sqltext in _named_checks(model_table).items()
            if name not in omitted_checks
        }
        assert _inspector_index_contract(inspector, table_name) == {
            name: contract
            for name, contract in _model_index_contract(model_table).items()
            if name not in omitted_indexes
        }


def _seed_existing_crm(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO crm_contacts (id, first_name, last_name) "
            "VALUES (8301, 'Preexisting', 'Contact')"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO crm_tasks "
            "(id, contact_id, title, description, status, priority, version, "
            "created_at, updated_at) VALUES "
            "(8302, 8301, 'Preserve through Gmail intake', '', 'open', "
            "'normal', 1, :now, :now)"
        ),
        {"now": datetime(2026, 8, 20, tzinfo=timezone.utc)},
    )


def _seed_all_intake_tables(connection: sa.Connection) -> dict[str, UUID]:
    ids = {
        table_name: UUID(f"00000000-0000-4000-8300-{index:012d}")
        for index, table_name in enumerate(TABLES, start=1)
    }
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    admin_id = connection.scalar(
        sa.text(
            "INSERT INTO admin_users (email, hashed_password) "
            "VALUES ('downgrade-admin@example.test', 'test-only') RETURNING id"
        )
    )
    audit_id = connection.scalar(
        sa.text(
            "INSERT INTO agent_action_audits "
            "(actor, action_id, method, path, status_code, allowed, "
            "request_meta, response_meta) VALUES "
            "('command_admin', 'migration.guard', 'POST', '/test', 200, true, "
            "'{}', '{}') RETURNING id"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO gmail_sync_accounts "
            "(id, workspace_email, committed_history_id) "
            "VALUES (:id, 'downgrade@example.test', 'history-1')"
        ),
        {"id": ids["gmail_sync_accounts"]},
    )
    connection.execute(
        sa.text(
            "INSERT INTO gmail_sync_runs "
            "(id, account_id, start_history_id, terminal_history_id, run_kind, "
            "state, discovered_at, completed_at) VALUES "
            "(:id, :account_id, 'history-1', 'history-2', 'backfill', "
            "'completed', :now, :now)"
        ),
        {
            "id": ids["gmail_sync_runs"],
            "account_id": ids["gmail_sync_accounts"],
            "now": now,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO gmail_sync_page_checkpoints "
            "(id, run_id, page_number, receipt_count) "
            "VALUES (:id, :run_id, 1, 1)"
        ),
        {
            "id": ids["gmail_sync_page_checkpoints"],
            "run_id": ids["gmail_sync_runs"],
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO gmail_missing_message_incidents "
            "(id, account_id, run_id, gmail_message_id, gmail_thread_id, "
            "start_history_id, page_number) VALUES "
            "(:id, :account_id, :run_id, 'missing-message-guard', "
            "'missing-thread-guard', 'history-1', 1)"
        ),
        {
            "id": ids["gmail_missing_message_incidents"],
            "account_id": ids["gmail_sync_accounts"],
            "run_id": ids["gmail_sync_runs"],
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO gmail_message_receipts "
            "(id, account_id, gmail_message_id, gmail_thread_id, direction, "
            "message_at, sender_hmac, body_hash) VALUES "
            "(:id, :account_id, 'message-guard', 'thread-guard', 'received', "
            ":now, :sender_hmac, :body_hash)"
        ),
        {
            "id": ids["gmail_message_receipts"],
            "account_id": ids["gmail_sync_accounts"],
            "now": now,
            "sender_hmac": "a" * 64,
            "body_hash": "b" * 64,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO gmail_message_origins "
            "(id, account_id, gmail_message_id, gmail_thread_id, origin_kind, "
            "delivery_state) VALUES "
            "(:id, :account_id, 'origin-message', 'thread-guard', "
            "'human_send', 'succeeded')"
        ),
        {
            "id": ids["gmail_message_origins"],
            "account_id": ids["gmail_sync_accounts"],
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO gmail_extraction_attempts "
            "(id, receipt_id, schema_version, attempt_number, state, "
            "completed_at) VALUES (:id, :receipt_id, 'gmail-task-v1', 1, "
            "'succeeded', :now)"
        ),
        {
            "id": ids["gmail_extraction_attempts"],
            "receipt_id": ids["gmail_message_receipts"],
            "now": now,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO crm_task_suggestions "
            "(id, gmail_account_id, gmail_thread_id, source_type, "
            "source_scope_key, source_action_key, title, payload_hash, "
            "model_schema_version, obligation_fingerprint, "
            "primary_instance_digest) VALUES "
            "(:id, :account_id, 'thread-guard', 'gmail_message', "
            "'gmail:guard-account:thread-guard', 'guard-action', "
            "'Guard suggestion', :payload_hash, 'gmail-task-v1', "
            ":fingerprint, :instance_digest)"
        ),
        {
            "id": ids["crm_task_suggestions"],
            "account_id": ids["gmail_sync_accounts"],
            "payload_hash": "d" * 64,
            "fingerprint": "c" * 64,
            "instance_digest": "e" * 64,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO gmail_extracted_obligations "
            "(id, receipt_id, extraction_attempt_id, action_key, "
            "schema_version, title, taxonomy_fallback, "
            "obligation_fingerprint, identity_instance_digest, "
            "reconciliation_material_hash, reconciled_suggestion_id) VALUES "
            "(:id, :receipt_id, :attempt_id, 'guard-action', "
            "'gmail-task-v1', 'Guard obligation', false, :fingerprint, "
            ":instance_digest, :material_hash, :suggestion_id)"
        ),
        {
            "id": ids["gmail_extracted_obligations"],
            "receipt_id": ids["gmail_message_receipts"],
            "attempt_id": ids["gmail_extraction_attempts"],
            "fingerprint": "c" * 64,
            "instance_digest": "e" * 64,
            "material_hash": "f" * 64,
            "suggestion_id": ids["crm_task_suggestions"],
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO crm_task_suggestion_sources "
            "(id, suggestion_id, obligation_id, receipt_id, gmail_account_id, "
            "gmail_thread_id, direction, source_label) VALUES "
            "(:id, :suggestion_id, :obligation_id, :receipt_id, :account_id, "
            "'thread-guard', 'received', "
            "'Received Gmail message')"
        ),
        {
            "id": ids["crm_task_suggestion_sources"],
            "suggestion_id": ids["crm_task_suggestions"],
            "obligation_id": ids["gmail_extracted_obligations"],
            "receipt_id": ids["gmail_message_receipts"],
            "account_id": ids["gmail_sync_accounts"],
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO crm_task_suggestion_suppressions "
            "(id, source_type, source_scope_key, source_action_key, "
            "obligation_fingerprint, identity_instance_digest, "
            "dismissal_reason, dismissed_by_admin_id, dismissal_audit_id) VALUES "
            "(:id, 'gmail_message', 'account:thread-guard', 'guard-action', "
            ":fingerprint, :instance_digest, 'Guard suppression', :admin_id, "
            ":audit_id)"
        ),
        {
            "id": ids["crm_task_suggestion_suppressions"],
            "fingerprint": "c" * 64,
            "instance_digest": "e" * 64,
            "admin_id": admin_id,
            "audit_id": audit_id,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO gmail_backfill_requests "
            "(id, account_id, administrator_id, reason, window_start, "
            "window_end, expired_history_id, reseed_history_id, audit_id, "
            "run_id, state, completed_at) VALUES "
            "(:id, :account_id, :admin_id, 'Guard backfill', :start, :end, "
            "'history-1', 'history-2', :audit_id, :run_id, 'completed', :now)"
        ),
        {
            "id": ids["gmail_backfill_requests"],
            "account_id": ids["gmail_sync_accounts"],
            "admin_id": admin_id,
            "start": datetime(2026, 8, 13, tzinfo=timezone.utc),
            "end": now,
            "audit_id": audit_id,
            "run_id": ids["gmail_sync_runs"],
            "now": now,
        },
    )
    return ids


def _retain_only_intake_table(
    connection: sa.Connection,
    target_table: str,
    *,
    expected_database: str,
    run_marker: str,
) -> None:
    if target_table not in TABLES:
        fail_closed("refusing evidence isolation for an unknown intake table")
    verify_exact_ownership(
        connection,
        expected_database=expected_database,
        run_marker=run_marker,
    )
    connection.exec_driver_sql("SET LOCAL session_replication_role = replica")
    for table_name in reversed(TABLES):
        if table_name != target_table:
            connection.exec_driver_sql(f'DELETE FROM "{table_name}"')


def test_revision_83_directly_follows_82_and_remains_in_serial_history() -> None:
    revision = _load_revision()
    assert revision.revision == REVISION
    assert revision.down_revision == DOWN_REVISION
    assert revision.branch_labels is None
    assert revision.depends_on is None
    scripts = _script_directory()
    heads = scripts.get_heads()
    assert len(heads) == 1
    ancestor_revisions = {
        candidate.revision
        for candidate in scripts.walk_revisions(base="base", head=heads[0])
    }
    assert REVISION in ancestor_revisions
    assert scripts.get_revision(REVISION).down_revision == DOWN_REVISION


def test_all_twelve_models_have_exact_columns_defaults_and_no_raw_secrets() -> None:
    tables = _model_tables()
    assert tuple(tables) == TABLES
    assert {table.name for table in tables.values()} == set(TABLES)

    expected_columns = {
        "gmail_sync_accounts": (
            "id",
            "workspace_email",
            "committed_history_id",
            "reseed_history_id",
            "mode",
            "blocked_reason",
            "last_succeeded_at",
            "last_error_category",
            "last_error_message",
            "created_at",
            "updated_at",
        ),
        "gmail_sync_runs": (
            "id",
            "account_id",
            "start_history_id",
            "terminal_history_id",
            "next_page_token",
            "run_kind",
            "state",
            "lease_owner",
            "lease_expires_at",
            "failure_category",
            "failure_message",
            "started_at",
            "updated_at",
            "discovered_at",
            "completed_at",
        ),
        "gmail_sync_page_checkpoints": (
            "id",
            "run_id",
            "page_number",
            "request_page_token",
            "next_page_token",
            "discovered_history_id_min",
            "discovered_history_id_max",
            "receipt_count",
            "committed_at",
        ),
        "gmail_missing_message_incidents": (
            "id",
            "account_id",
            "run_id",
            "gmail_message_id",
            "gmail_thread_id",
            "start_history_id",
            "page_number",
            "request_page_token",
            "state",
            "version",
            "alert_state",
            "alerted_at",
            "acknowledged_by_admin_id",
            "acknowledgement_reason",
            "action_audit_id",
            "created_at",
            "updated_at",
            "acknowledged_at",
        ),
        "gmail_message_receipts": (
            "id",
            "account_id",
            "gmail_message_id",
            "gmail_thread_id",
            "direction",
            "message_at",
            "sender_hmac",
            "recipient_hmacs_json",
            "subject_preview",
            "body_hash",
            "labels_json",
            "processing_state",
            "classification",
            "failure_category",
            "failure_message",
            "processing_started_at",
            "processed_at",
            "created_at",
            "updated_at",
        ),
        "gmail_message_origins": (
            "id",
            "account_id",
            "request_id",
            "retry_of_origin_id",
            "canonical_send_hash",
            "canonical_envelope_hash",
            "canonical_body_hash",
            "intended_thread_id",
            "gmail_message_id",
            "gmail_thread_id",
            "origin_kind",
            "delivery_state",
            "reconciled_outcome",
            "version",
            "action_audit_id",
            "failure_category",
            "failure_message",
            "quarantine_category",
            "quarantine_evidence",
            "reconciled_at",
            "created_at",
            "updated_at",
        ),
        "gmail_extraction_attempts": (
            "id",
            "receipt_id",
            "schema_version",
            "attempt_number",
            "state",
            "error_category",
            "error_message",
            "started_at",
            "completed_at",
        ),
        "gmail_extracted_obligations": (
            "id",
            "receipt_id",
            "extraction_attempt_id",
            "action_key",
            "schema_version",
            "title",
            "description",
            "priority",
            "due_at",
            "timezone_basis",
            "requested_owner",
            "requested_link_type",
            "requested_link_id",
            "contact_hint",
            "owner_ambiguous",
            "taxonomy_fallback",
            "obligation_fingerprint",
            "identity_instance_digest",
            "reconciliation_material_hash",
            "reconciled_suggestion_id",
            "reconciled_suppression_id",
            "confidence",
            "evaluator_result_json",
            "evidence_preview",
            "created_at",
        ),
        "crm_task_suggestions": (
            "id",
            "gmail_account_id",
            "gmail_thread_id",
            "source_type",
            "source_scope_key",
            "source_action_key",
            "source_request_id",
            "duplicate_of_suggestion_id",
            "contact_id",
            "title",
            "description",
            "priority",
            "due_at",
            "task_status",
            "state",
            "clarification_state",
            "blocker_codes",
            "owner_clarification_pending",
            "task_details_clarification_pending",
            "contact_resolution_state",
            "contact_resolution_hash",
            "payload_hash",
            "application_idempotency_key",
            "applied_task_id",
            "model_schema_version",
            "obligation_fingerprint",
            "primary_instance_digest",
            "confidence",
            "rationale",
            "version",
            "created_at",
            "updated_at",
        ),
        "crm_task_suggestion_sources": (
            "id",
            "suggestion_id",
            "obligation_id",
            "receipt_id",
            "gmail_account_id",
            "gmail_thread_id",
            "direction",
            "source_label",
            "created_at",
        ),
        "crm_task_suggestion_suppressions": (
            "id",
            "source_type",
            "source_scope_key",
            "source_action_key",
            "obligation_fingerprint",
            "identity_instance_digest",
            "dismissal_reason",
            "dismissed_by_admin_id",
            "dismissal_audit_id",
            "dismissed_at",
            "reprocess_override_at",
            "reprocess_override_consumed_at",
            "reprocess_override_by_admin_id",
            "reprocess_override_audit_id",
        ),
        "gmail_backfill_requests": (
            "id",
            "account_id",
            "administrator_id",
            "reason",
            "window_start",
            "window_end",
            "expired_history_id",
            "reseed_history_id",
            "audit_id",
            "run_id",
            "state",
            "result_category",
            "result_message",
            "created_at",
            "started_at",
            "completed_at",
        ),
    }
    for name, expected in expected_columns.items():
        assert tuple(tables[name].columns.keys()) == expected
        assert {
            column.name for column in tables[name].columns if column.nullable
        } == NULLABLE_COLUMNS[name]
        expected_types = _expected_type_signatures(name)
        assert set(expected_types) == set(expected)
        assert {
            column.name: _type_signature(column.type) for column in tables[name].columns
        } == expected_types
        assert {
            column.name: _canonical_default(
                None if column.server_default is None else column.server_default.arg
            )
            for column in tables[name].columns
            if column.server_default is not None
        } == EXPECTED_SERVER_DEFAULTS[name]

    for table in tables.values():
        _assert_uuid(table.columns["id"], nullable=False)
        assert table.primary_key.columns.keys() == ["id"]

    account = tables["gmail_sync_accounts"]
    assert account.columns["workspace_email"].type.length == 320
    assert account.columns["mode"].default.arg == "shadow"
    assert str(account.columns["mode"].server_default.arg) == "shadow"
    assert account.columns["last_error_message"].type.length == 500

    run = tables["gmail_sync_runs"]
    assert run.columns["next_page_token"].type.length == 1024
    assert run.columns["failure_message"].type.length == 500
    assert run.columns["state"].default.arg == "running"
    assert str(run.columns["state"].server_default.arg) == "running"

    checkpoint = tables["gmail_sync_page_checkpoints"]
    assert checkpoint.columns["receipt_count"].default.arg == 0
    assert str(checkpoint.columns["receipt_count"].server_default.arg) == "0"

    incident = tables["gmail_missing_message_incidents"]
    assert incident.columns["state"].default.arg == "pending"
    assert str(incident.columns["state"].server_default.arg) == "pending"
    assert incident.columns["version"].default.arg == 1
    assert str(incident.columns["version"].server_default.arg) == "1"
    assert incident.columns["alert_state"].default.arg == "pending"
    assert str(incident.columns["alert_state"].server_default.arg) == "pending"
    assert incident.columns["acknowledgement_reason"].type.length == 500

    receipt = tables["gmail_message_receipts"]
    assert receipt.columns["subject_preview"].type.length == 255
    assert receipt.columns["failure_message"].type.length == 500
    assert receipt.columns["processing_state"].default.arg == "pending"
    assert str(receipt.columns["processing_state"].server_default.arg) == "pending"
    assert receipt.columns["recipient_hmacs_json"].default.arg == "[]"
    assert str(receipt.columns["recipient_hmacs_json"].server_default.arg) == "[]"

    origin = tables["gmail_message_origins"]
    _assert_uuid(origin.columns["request_id"], nullable=True)
    _assert_uuid(origin.columns["retry_of_origin_id"], nullable=True)
    assert origin.columns["version"].default.arg == 1
    assert str(origin.columns["version"].server_default.arg) == "1"
    for name in (
        "canonical_send_hash",
        "canonical_envelope_hash",
        "canonical_body_hash",
    ):
        assert origin.columns[name].type.length == 64
    assert origin.columns["failure_message"].type.length == 500
    assert origin.columns["quarantine_evidence"].type.length == 500

    obligation = tables["gmail_extracted_obligations"]
    assert obligation.columns["title"].type.length == 255
    assert obligation.columns["evidence_preview"].type.length == 500

    suggestion = tables["crm_task_suggestions"]
    assert suggestion.columns["task_status"].default.arg == "open"
    assert str(suggestion.columns["task_status"].server_default.arg) == "open"
    assert suggestion.columns["state"].default.arg == "pending_review"
    assert str(suggestion.columns["state"].server_default.arg) == "pending_review"
    assert suggestion.columns["clarification_state"].default.arg == "not_required"
    assert (
        str(suggestion.columns["clarification_state"].server_default.arg)
        == "not_required"
    )
    assert callable(suggestion.columns["blocker_codes"].default.arg)
    first_default = suggestion.columns["blocker_codes"].default.arg(None)
    second_default = suggestion.columns["blocker_codes"].default.arg(None)
    assert first_default == [] and second_default == []
    assert first_default is not second_default
    assert str(suggestion.columns["blocker_codes"].server_default.arg) == "{}"
    assert suggestion.columns["version"].default.arg == 1
    assert str(suggestion.columns["version"].server_default.arg) == "1"
    _assert_uuid(suggestion.columns["gmail_account_id"], nullable=True)
    _assert_uuid(suggestion.columns["source_request_id"], nullable=True)
    _assert_uuid(suggestion.columns["application_idempotency_key"], nullable=True)

    suppression = tables["crm_task_suggestion_suppressions"]
    assert suppression.columns["dismissal_reason"].type.length == 500
    backfill = tables["gmail_backfill_requests"]
    assert backfill.columns["reason"].type.length == 500
    assert backfill.columns["result_message"].type.length == 500
    assert backfill.columns["state"].default.arg == "requested"

    forbidden_exact = {
        "raw_body",
        "body",
        "body_text",
        "html_body",
        "access_token",
        "refresh_token",
        "oauth_token",
        "oauth_credentials",
        "credential_json",
        "secret",
    }
    for table in tables.values():
        assert forbidden_exact.isdisjoint(table.columns.keys())


def test_models_pin_exact_uniqueness_indexes_and_postgresql_predicates() -> None:
    tables = _model_tables()
    assert _named_unique_columns(tables["gmail_sync_accounts"]) == {
        "uq_gmail_sync_accounts_workspace_email": ("workspace_email",)
    }
    assert _named_unique_columns(tables["gmail_sync_page_checkpoints"]) == {
        "uq_gmail_sync_page_checkpoints_run_page": ("run_id", "page_number")
    }
    assert _named_unique_columns(tables["gmail_missing_message_incidents"]) == {
        "uq_gmail_missing_message_incidents_run_message_thread_page": (
            "account_id",
            "run_id",
            "gmail_message_id",
            "gmail_thread_id",
            "page_number",
        )
    }
    assert _named_unique_columns(tables["gmail_sync_runs"]) == {
        "uq_gmail_sync_runs_id_account": ("id", "account_id")
    }
    assert _named_unique_columns(tables["gmail_message_receipts"]) == {
        "uq_gmail_message_receipts_account_message": (
            "account_id",
            "gmail_message_id",
        ),
        "uq_gmail_message_receipts_source_identity": (
            "id",
            "account_id",
            "gmail_thread_id",
            "direction",
        ),
    }
    assert _named_unique_columns(tables["gmail_message_origins"]) == {
        "uq_gmail_message_origins_account_request": (
            "account_id",
            "request_id",
        ),
        "uq_gmail_message_origins_retry_parent": ("retry_of_origin_id",),
    }
    assert _named_unique_columns(tables["gmail_extraction_attempts"]) == {
        "uq_gmail_extraction_attempts_receipt_schema_attempt": (
            "receipt_id",
            "schema_version",
            "attempt_number",
        ),
        "uq_gmail_extraction_attempts_id_receipt": ("id", "receipt_id"),
    }
    assert _named_unique_columns(tables["gmail_extracted_obligations"]) == {
        "uq_gmail_extracted_obligations_source_action": (
            "receipt_id",
            "action_key",
            "schema_version",
        ),
        "uq_gmail_extracted_obligations_id_receipt": ("id", "receipt_id"),
        "uq_gmail_extracted_obligations_source_disposition": (
            "id",
            "receipt_id",
            "reconciled_suggestion_id",
        ),
    }
    assert _named_unique_columns(tables["crm_task_suggestions"]) == {
        "uq_crm_task_suggestions_application_key": ("application_idempotency_key",),
        "uq_crm_task_suggestions_source_request": ("source_request_id",),
        "uq_crm_task_suggestions_gmail_identity": (
            "id",
            "gmail_account_id",
            "gmail_thread_id",
        ),
        "uq_crm_task_suggestions_source_identity": (
            "id",
            "source_type",
            "source_scope_key",
        ),
    }
    assert _named_unique_columns(tables["crm_task_suggestion_sources"]) == {
        "uq_crm_task_suggestion_sources_suggestion_obligation": (
            "suggestion_id",
            "obligation_id",
        ),
        "uq_crm_task_suggestion_sources_obligation": ("obligation_id",),
    }
    assert _named_unique_columns(tables["crm_task_suggestion_suppressions"]) == {
        "uq_crm_task_suggestion_suppressions_scope": (
            "source_type",
            "source_scope_key",
            "source_action_key",
            "obligation_fingerprint",
            "identity_instance_digest",
        ),
        "uq_crm_task_suggestion_suppressions_override_audit": (
            "reprocess_override_audit_id",
        ),
    }
    assert _named_unique_columns(tables["gmail_backfill_requests"]) == {}
    for table_name, table in tables.items():
        assert _model_foreign_key_contract(table) == EXPECTED_FOREIGN_KEYS[table_name]

    run_indexes = _indexes(tables["gmail_sync_runs"])
    assert _compiled_index(run_indexes["uq_gmail_sync_runs_active_account"]) == (
        "CREATE UNIQUE INDEX uq_gmail_sync_runs_active_account ON "
        "gmail_sync_runs (account_id) WHERE state IN ('running', 'discovered')"
    )
    account_indexes = _indexes(tables["gmail_sync_accounts"])
    assert _compiled_index(account_indexes["ix_gmail_sync_accounts_blocked"]) == (
        "CREATE INDEX ix_gmail_sync_accounts_blocked ON gmail_sync_accounts "
        "(blocked_reason, id) WHERE blocked_reason IS NOT NULL"
    )
    receipt_indexes = _indexes(tables["gmail_message_receipts"])
    assert receipt_indexes["ix_gmail_message_receipts_account_thread"].unique is False
    assert tuple(
        column.name
        for column in receipt_indexes[
            "ix_gmail_message_receipts_account_thread"
        ].columns
    ) == ("account_id", "gmail_thread_id")
    assert _compiled_index(receipt_indexes["ix_gmail_message_receipts_pending"]) == (
        "CREATE INDEX ix_gmail_message_receipts_pending ON "
        "gmail_message_receipts (processing_state, created_at, id) WHERE "
        "processing_state IN ('pending', 'failed')"
    )

    origin_indexes = _indexes(tables["gmail_message_origins"])
    assert origin_indexes["ix_gmail_message_origins_account_thread"].unique is False
    assert tuple(
        column.name
        for column in origin_indexes["ix_gmail_message_origins_account_thread"].columns
    ) == ("account_id", "gmail_thread_id")
    assert _compiled_index(
        origin_indexes["uq_gmail_message_origins_account_message"]
    ) == (
        "CREATE UNIQUE INDEX uq_gmail_message_origins_account_message ON "
        "gmail_message_origins (account_id, gmail_message_id) WHERE "
        "gmail_message_id IS NOT NULL"
    )
    unresolved = origin_indexes["uq_gmail_message_origins_unresolved_send"]
    assert _compiled_index(unresolved) == (
        "CREATE UNIQUE INDEX uq_gmail_message_origins_unresolved_send ON "
        "gmail_message_origins (account_id, canonical_send_hash) WHERE "
        "delivery_state IN ('sending', 'delivery_uncertain') AND "
        "reconciled_outcome IS DISTINCT FROM 'not_delivered'"
    )
    predicate = str(unresolved.dialect_options["postgresql"].get("where"))
    assert predicate == (
        "delivery_state IN ('sending', 'delivery_uncertain') AND "
        "reconciled_outcome IS DISTINCT FROM 'not_delivered'"
    )
    assert "!=" not in predicate and "<>" not in predicate

    obligation_indexes = _indexes(tables["gmail_extracted_obligations"])
    assert _compiled_index(
        obligation_indexes["ix_gmail_extracted_obligations_suggestion_instance"]
    ) == (
        "CREATE INDEX ix_gmail_extracted_obligations_suggestion_instance ON "
        "gmail_extracted_obligations (reconciled_suggestion_id, "
        "identity_instance_digest, reconciliation_material_hash, id)"
    )
    assert _compiled_index(
        obligation_indexes["ix_gmail_extracted_obligations_suggestion_taxonomy"]
    ) == (
        "CREATE INDEX ix_gmail_extracted_obligations_suggestion_taxonomy ON "
        "gmail_extracted_obligations (reconciled_suggestion_id, "
        "taxonomy_fallback, id)"
    )
    assert _compiled_index(
        obligation_indexes["ix_gmail_extracted_obligations_suggestion_owner_ambiguous"]
    ) == (
        "CREATE INDEX "
        "ix_gmail_extracted_obligations_suggestion_owner_ambiguous ON "
        "gmail_extracted_obligations (reconciled_suggestion_id, "
        "owner_ambiguous, id)"
    )
    assert _compiled_index(
        obligation_indexes["ix_gmail_extracted_obligations_suggestion_contact_hint"]
    ) == (
        "CREATE INDEX ix_gmail_extracted_obligations_suggestion_contact_hint "
        "ON gmail_extracted_obligations (reconciled_suggestion_id, "
        "contact_hint, id)"
    )
    assert _compiled_index(
        obligation_indexes["ix_gmail_extracted_obligations_attempt_replay"]
    ) == (
        "CREATE INDEX ix_gmail_extracted_obligations_attempt_replay ON "
        "gmail_extracted_obligations (extraction_attempt_id, created_at, id)"
    )

    suggestion_indexes = _indexes(tables["crm_task_suggestions"])
    assert tuple(
        column.name
        for column in suggestion_indexes["ix_crm_task_suggestions_review_state"].columns
    ) == ("state", "updated_at", "id")
    assert _compiled_index(
        suggestion_indexes["ix_crm_task_suggestions_gmail_reconciliation"]
    ) == (
        "CREATE INDEX ix_crm_task_suggestions_gmail_reconciliation ON "
        "crm_task_suggestions (gmail_account_id, gmail_thread_id, "
        "source_action_key, id) WHERE source_type = 'gmail_message'"
    )
    assert _compiled_index(
        suggestion_indexes["ix_crm_task_suggestions_gmail_thread_order"]
    ) == (
        "CREATE INDEX ix_crm_task_suggestions_gmail_thread_order ON "
        "crm_task_suggestions (gmail_account_id, gmail_thread_id, "
        "source_type, created_at, id)"
    )
    source_indexes = _indexes(tables["crm_task_suggestion_sources"])
    assert tuple(
        column.name
        for column in source_indexes["ix_crm_task_suggestion_sources_receipt"].columns
    ) == ("receipt_id", "id")

    assert {
        table_name: _model_index_contract(table) for table_name, table in tables.items()
    } == {
        "gmail_sync_accounts": {
            "ix_gmail_sync_accounts_blocked": (
                ("blocked_reason", "id"),
                False,
                "blocked_reason is not null",
            )
        },
        "gmail_sync_runs": {
            "uq_gmail_sync_runs_active_account": (
                ("account_id",),
                True,
                "state in ('running', 'discovered')",
            )
        },
        "gmail_sync_page_checkpoints": {},
        "gmail_missing_message_incidents": {
            "ix_gmail_missing_message_incidents_pending": (
                ("account_id", "created_at", "id"),
                False,
                "state = 'pending'",
            )
        },
        "gmail_message_receipts": {
            "ix_gmail_message_receipts_account_thread": (
                ("account_id", "gmail_thread_id"),
                False,
                None,
            ),
            "ix_gmail_message_receipts_pending": (
                ("processing_state", "created_at", "id"),
                False,
                "processing_state in ('pending', 'failed')",
            ),
        },
        "gmail_message_origins": {
            "ix_gmail_message_origins_account_thread": (
                ("account_id", "gmail_thread_id"),
                False,
                None,
            ),
            "uq_gmail_message_origins_account_message": (
                ("account_id", "gmail_message_id"),
                True,
                "gmail_message_id is not null",
            ),
            "uq_gmail_message_origins_unresolved_send": (
                ("account_id", "canonical_send_hash"),
                True,
                "delivery_state in ('sending', 'delivery_uncertain') and "
                "reconciled_outcome is distinct from 'not_delivered'",
            ),
        },
        "gmail_extraction_attempts": {},
        "gmail_extracted_obligations": {
            "ix_gmail_extracted_obligations_suggestion_instance": (
                (
                    "reconciled_suggestion_id",
                    "identity_instance_digest",
                    "reconciliation_material_hash",
                    "id",
                ),
                False,
                None,
            ),
            "ix_gmail_extracted_obligations_suggestion_taxonomy": (
                (
                    "reconciled_suggestion_id",
                    "taxonomy_fallback",
                    "id",
                ),
                False,
                None,
            ),
            "ix_gmail_extracted_obligations_suggestion_owner_ambiguous": (
                (
                    "reconciled_suggestion_id",
                    "owner_ambiguous",
                    "id",
                ),
                False,
                None,
            ),
            "ix_gmail_extracted_obligations_suggestion_contact_hint": (
                (
                    "reconciled_suggestion_id",
                    "contact_hint",
                    "id",
                ),
                False,
                None,
            ),
            "ix_gmail_extracted_obligations_attempt_replay": (
                ("extraction_attempt_id", "created_at", "id"),
                False,
                None,
            ),
        },
        "crm_task_suggestions": {
            "ix_crm_task_suggestions_review_state": (
                ("state", "updated_at", "id"),
                False,
                None,
            ),
            "ix_crm_task_suggestions_gmail_reconciliation": (
                (
                    "gmail_account_id",
                    "gmail_thread_id",
                    "source_action_key",
                    "id",
                ),
                False,
                "source_type = 'gmail_message'",
            ),
            "ix_crm_task_suggestions_gmail_thread_order": (
                (
                    "gmail_account_id",
                    "gmail_thread_id",
                    "source_type",
                    "created_at",
                    "id",
                ),
                False,
                None,
            ),
        },
        "crm_task_suggestion_sources": {
            "ix_crm_task_suggestion_sources_receipt": (
                ("receipt_id", "id"),
                False,
                None,
            )
        },
        "crm_task_suggestion_suppressions": {},
        "gmail_backfill_requests": {},
    }


def test_models_pin_exact_states_and_cross_field_constraints() -> None:
    tables = _model_tables()
    assert _named_checks(tables["gmail_sync_accounts"]) == {
        "ck_gmail_sync_accounts_mode": "mode IN ('shadow', 'live')",
        "ck_gmail_sync_accounts_workspace_email_canonical": (
            "workspace_email = lower(trim(workspace_email)) AND workspace_email <> ''"
        ),
    }
    assert _named_checks(tables["gmail_sync_runs"]) == {
        "ck_gmail_sync_runs_kind": "run_kind IN ('poll', 'backfill')",
        "ck_gmail_sync_runs_state": (
            "state IN ('running', 'discovered', 'completed', 'failed', "
            "'blocked_expired_cursor')"
        ),
    }
    assert _named_checks(tables["gmail_sync_page_checkpoints"]) == {
        "ck_gmail_sync_page_checkpoints_page_positive": "page_number > 0",
        "ck_gmail_sync_page_checkpoints_receipts_nonnegative": ("receipt_count >= 0"),
    }
    assert _named_checks(tables["gmail_missing_message_incidents"]) == {
        "ck_gmail_missing_message_incidents_state": (
            "state IN ('pending', 'acknowledged')"
        ),
        "ck_gmail_missing_message_incidents_page_positive": "page_number > 0",
        "ck_gmail_missing_message_incidents_version_positive": "version > 0",
        "ck_gmail_missing_message_incidents_alert_shape": (
            "alert_state IN ('pending', 'sent') AND ((alert_state = 'pending' "
            "AND alerted_at IS NULL) OR (alert_state = 'sent' AND alerted_at "
            "IS NOT NULL))"
        ),
        "ck_gmail_missing_message_incidents_ack_shape": (
            "(state = 'pending' AND acknowledged_by_admin_id IS NULL AND "
            "acknowledgement_reason IS NULL AND action_audit_id IS NULL AND "
            "acknowledged_at IS NULL) OR (state = 'acknowledged' AND "
            "acknowledged_by_admin_id IS NOT NULL AND acknowledgement_reason "
            "IS NOT NULL AND acknowledgement_reason = "
            "trim(acknowledgement_reason) AND acknowledgement_reason <> '' "
            "AND action_audit_id IS NOT NULL AND acknowledged_at IS NOT NULL "
            "AND alert_state = 'sent')"
        ),
    }
    assert _named_checks(tables["gmail_message_receipts"]) == {
        "ck_gmail_message_receipts_direction": (
            "direction IN ('received', 'sent', 'self_copy')"
        ),
        "ck_gmail_message_receipts_processing_state": (
            "processing_state IN ('pending', 'processing', 'processed', "
            "'ignored', 'failed')"
        ),
    }
    origin_checks = _named_checks(tables["gmail_message_origins"])
    assert origin_checks == {
        "ck_gmail_message_origins_kind": (
            "origin_kind IN ('sydney_client_send', 'human_send', 'system_automation')"
        ),
        "ck_gmail_message_origins_delivery_state": (
            "delivery_state IN ('sending', 'succeeded', 'delivery_uncertain')"
        ),
        "ck_gmail_message_origins_reconciled_outcome": (
            "reconciled_outcome IS NULL OR reconciled_outcome IN "
            "('delivered', 'not_delivered')"
        ),
        "ck_gmail_message_origins_version_positive": "version > 0",
        "ck_gmail_message_origins_provider_ids": (
            "(delivery_state = 'succeeded' AND gmail_message_id IS NOT NULL "
            "AND gmail_thread_id IS NOT NULL) OR (delivery_state IN "
            "('sending', 'delivery_uncertain') AND gmail_message_id IS NULL "
            "AND gmail_thread_id IS NULL)"
        ),
        "ck_gmail_message_origins_intent_shape": (
            "(origin_kind = 'human_send' AND request_id IS NULL AND "
            "canonical_send_hash IS NULL AND canonical_envelope_hash IS NULL "
            "AND canonical_body_hash IS NULL AND action_audit_id IS NULL) OR "
            "(origin_kind IN ('sydney_client_send', 'system_automation') AND "
            "request_id IS NOT NULL AND canonical_send_hash IS NOT NULL AND "
            "canonical_envelope_hash IS NOT NULL AND canonical_body_hash IS "
            "NOT NULL AND action_audit_id IS NOT NULL)"
        ),
        "ck_gmail_message_origins_human_succeeded": (
            "origin_kind <> 'human_send' OR delivery_state = 'succeeded'"
        ),
        "ck_gmail_message_origins_reconciliation_state": (
            "reconciled_outcome IS NULL OR (reconciled_outcome = 'delivered' "
            "AND delivery_state = 'succeeded') OR (reconciled_outcome = "
            "'not_delivered' AND delivery_state IN ('sending', "
            "'delivery_uncertain'))"
        ),
    }
    assert _named_checks(tables["gmail_extraction_attempts"]) == {
        "ck_gmail_extraction_attempts_number_positive": "attempt_number > 0",
        "ck_gmail_extraction_attempts_state": (
            "state IN ('running', 'succeeded', 'failed')"
        ),
    }
    assert _named_checks(tables["gmail_extracted_obligations"]) == {
        "ck_gmail_extracted_obligations_priority": (
            "priority IN ('low', 'normal', 'high')"
        ),
        "ck_gmail_extracted_obligations_confidence": (
            "confidence >= 0 AND confidence <= 1"
        ),
        "ck_gmail_extracted_obligations_instance_digest": (
            "identity_instance_digest ~ '^[0-9a-f]{64}$'"
        ),
        "ck_gmail_extracted_obligations_material_hash": (
            "reconciliation_material_hash ~ '^[0-9a-f]{64}$'"
        ),
        "ck_gmail_extracted_obligations_disposition": (
            "(reconciled_suggestion_id IS NOT NULL) <> "
            "(reconciled_suppression_id IS NOT NULL)"
        ),
    }
    suggestion_checks = _named_checks(tables["crm_task_suggestions"])
    assert suggestion_checks == {
        "ck_crm_task_suggestions_source_type": (
            "source_type IN ('gmail_message', 'sydney_chat')"
        ),
        "ck_crm_task_suggestions_source_shape": (
            "(source_type = 'gmail_message' AND gmail_account_id IS NOT NULL "
            "AND gmail_thread_id IS NOT NULL AND source_request_id IS NULL) "
            "OR (source_type = 'sydney_chat' AND gmail_account_id IS NULL AND "
            "gmail_thread_id IS NULL AND source_request_id IS NOT NULL)"
        ),
        "ck_crm_task_suggestions_priority": ("priority IN ('low', 'normal', 'high')"),
        "ck_crm_task_suggestions_task_status": "task_status = 'open'",
        "ck_crm_task_suggestions_state": (
            "state IN ('needs_clarification', 'possible_duplicate', "
            "'pending_review', 'approved', 'dismissed', 'applied', 'failed')"
        ),
        "ck_crm_task_suggestions_clarification_state": (
            "clarification_state IN ('not_required', 'pending', 'answered', "
            "'timed_out', 'manual_review_required')"
        ),
        "ck_crm_task_suggestions_blocker_codes": (
            "cardinality(blocker_codes) <= 8 AND blocker_codes <@ "
            "ARRAY['missing_required_field', 'ambiguous_due_at', "
            "'ambiguous_contact', 'multiple_actions', 'unsupported_owner', "
            "'unsupported_link']::varchar[]"
        ),
        "ck_crm_task_suggestions_blocker_codes_unique": (
            "cardinality(array_positions(blocker_codes, "
            "'missing_required_field')) <= 1 AND "
            "cardinality(array_positions(blocker_codes, "
            "'ambiguous_due_at')) <= 1 AND "
            "cardinality(array_positions(blocker_codes, "
            "'ambiguous_contact')) <= 1 AND "
            "cardinality(array_positions(blocker_codes, "
            "'multiple_actions')) <= 1 AND "
            "cardinality(array_positions(blocker_codes, "
            "'unsupported_owner')) <= 1 AND "
            "cardinality(array_positions(blocker_codes, "
            "'unsupported_link')) <= 1"
        ),
        "ck_crm_task_suggestions_clarification_pending_cause": (
            "('missing_required_field' = ANY(blocker_codes)) = "
            "(owner_clarification_pending OR "
            "task_details_clarification_pending)"
        ),
        "ck_crm_task_suggestions_contact_resolution": (
            "(contact_resolution_state IN ('not_provided', "
            "'explicit_none') AND contact_id IS NULL AND "
            "contact_resolution_hash IS NULL AND NOT "
            "('ambiguous_contact' = ANY(blocker_codes))) OR "
            "(contact_resolution_state = 'unresolved' AND contact_id IS NULL "
            "AND contact_resolution_hash IS NULL AND "
            "'ambiguous_contact' = ANY(blocker_codes)) OR "
            "(contact_resolution_state IN ('inferred_unique', "
            "'clarified_unique') AND contact_id IS NOT NULL AND "
            "contact_resolution_hash ~ '^[0-9a-f]{64}$' AND NOT "
            "('ambiguous_contact' = ANY(blocker_codes)))"
        ),
        "ck_crm_task_suggestions_confidence": ("confidence >= 0 AND confidence <= 1"),
        "ck_crm_task_suggestions_version_positive": "version > 0",
        "ck_crm_task_suggestions_applied_result": (
            "(state = 'applied' AND applied_task_id IS NOT NULL AND "
            "application_idempotency_key IS NOT NULL) OR (state <> "
            "'applied' AND applied_task_id IS NULL)"
        ),
        "ck_crm_task_suggestions_duplicate_not_self": (
            "duplicate_of_suggestion_id IS NULL OR duplicate_of_suggestion_id <> id"
        ),
        "ck_crm_task_suggestions_primary_instance_digest": (
            "primary_instance_digest IS NULL OR "
            "primary_instance_digest ~ '^[0-9a-f]{64}$'"
        ),
        "ck_crm_task_suggestions_gmail_instance_digest": (
            "source_type <> 'gmail_message' OR primary_instance_digest IS NOT NULL"
        ),
    }
    assert _named_checks(tables["crm_task_suggestion_sources"]) == {
        "ck_crm_task_suggestion_sources_direction": (
            "direction IN ('received', 'sent', 'self_copy')"
        )
    }
    assert _named_checks(tables["crm_task_suggestion_suppressions"]) == {
        "ck_crm_task_suggestion_suppressions_source_type": (
            "source_type IN ('gmail_message', 'sydney_chat')"
        ),
        "ck_crm_task_suggestion_suppressions_instance_digest": (
            "identity_instance_digest ~ '^[0-9a-f]{64}$'"
        ),
        "ck_crm_task_suggestion_suppressions_override_shape": (
            "(reprocess_override_at IS NULL AND "
            "reprocess_override_by_admin_id IS NULL AND "
            "reprocess_override_audit_id IS NULL AND "
            "reprocess_override_consumed_at IS NULL) OR "
            "(reprocess_override_at IS NOT NULL AND "
            "reprocess_override_by_admin_id IS NOT NULL AND "
            "reprocess_override_audit_id IS NOT NULL AND "
            "reprocess_override_at >= dismissed_at AND "
            "(reprocess_override_consumed_at IS NULL OR "
            "reprocess_override_consumed_at >= reprocess_override_at))"
        ),
    }
    assert _named_checks(tables["gmail_backfill_requests"]) == {
        "ck_gmail_backfill_requests_window": (
            "window_end >= window_start AND window_end <= window_start + "
            "INTERVAL '7 days'"
        ),
        "ck_gmail_backfill_requests_state": (
            "state IN ('requested', 'running', 'completed', 'failed')"
        ),
    }


def test_gmail_intake_schemas_are_strict_bounded_and_separate_manual_review() -> None:
    schemas = importlib.import_module("schemas.gmail_task_intake")
    payload = schemas.GmailTaskPayload(
        title="Follow up with seller",
        description="Send the disclosure package.",
        priority="high",
        due_at=datetime(2026, 8, 21, 13, 0, tzinfo=timezone.utc),
        contact_id=8301,
    )
    assert payload.status == "open"
    assert payload.model_dump()["title"] == "Follow up with seller"
    assert schemas.TaskPriority.__args__ == ("low", "normal", "high")
    assert schemas.SuggestionState.__args__ == (
        "needs_clarification",
        "possible_duplicate",
        "pending_review",
        "approved",
        "dismissed",
        "applied",
        "failed",
    )
    assert "manual_review_required" not in schemas.SuggestionState.__args__
    assert "manual_review_required" in schemas.ClarificationState.__args__
    assert set(schemas.BlockerCode.__args__) == {
        "missing_required_field",
        "ambiguous_due_at",
        "ambiguous_contact",
        "multiple_actions",
        "unsupported_owner",
        "unsupported_link",
    }
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(
            title=" ",
            description="",
            priority="normal",
            contact_id=None,
        )
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(
            title="Valid",
            description="",
            priority="normal",
            contact_id=None,
            owner="someone-else",
        )
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(
            title="Valid",
            description="",
            priority="normal",
            contact_id=None,
            status="completed",
        )
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(
            title="x" * 256,
            description="",
            priority="normal",
            contact_id=None,
        )
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(
            title="Valid",
            description="x" * 5001,
            priority="normal",
            contact_id=None,
        )
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(
            title="Valid",
            description="",
            priority="normal",
            contact_id=0,
        )
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(
            title="Valid",
            priority="urgent",
        )
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(
            title="Valid",
            due_at=datetime(2026, 8, 21, 13, 0),
        )
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(
            title="Valid",
            due_at="2026-08-21 13:00:00Z",
        )
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(title="Valid", due_at=123)
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(
            title="Valid",
            due_at="2026-02-30T13:00:00Z",
        )
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(title="Valid", contact_id=True)
    with pytest.raises(ValidationError):
        schemas.GmailTaskPayload(title="Valid", contact_id=2_147_483_648)

    rfc3339_payload = schemas.GmailTaskPayload(
        title="Valid",
        due_at="2026-08-21T13:00:00Z",
        contact_id=2_147_483_647,
    )
    assert rfc3339_payload.due_at == datetime(2026, 8, 21, 13, 0, tzinfo=timezone.utc)
    json_payload = schemas.GmailTaskPayload.model_validate_json(
        '{"title":"Valid JSON","due_at":"2026-08-21T13:00:00-04:00",'
        '"contact_id":2147483647}'
    )
    assert json_payload.due_at is not None
    assert json_payload.due_at.utcoffset() is not None


def test_models_are_registered_for_application_and_alembic() -> None:
    models = importlib.import_module("models")
    module = importlib.import_module("models.gmail_task_intake")
    admin_module = importlib.import_module("models.admin_user")
    expected_names = {
        "GmailSyncAccount",
        "GmailSyncRun",
        "GmailSyncPageCheckpoint",
        "GmailMissingMessageIncident",
        "GmailMessageReceipt",
        "GmailMessageOrigin",
        "GmailExtractionAttempt",
        "GmailExtractedObligation",
        "CRMTaskSuggestion",
        "CRMTaskSuggestionSource",
        "CRMTaskSuggestionSuppression",
        "GmailBackfillRequest",
    }
    assert expected_names.issubset(set(models.__all__))
    for name in expected_names:
        assert getattr(models, name) is getattr(module, name)
    assert models.AdminUser is admin_module.AdminUser
    gmail_model_source = (
        _backend_root() / "models" / "gmail_task_intake.py"
    ).read_text(encoding="utf-8")
    assert "import models.admin_user" not in gmail_model_source
    env_source = (_backend_root() / "alembic" / "env.py").read_text(encoding="utf-8")
    assert env_source.count("import models.gmail_task_intake") == 1


def test_importing_models_preserves_legacy_sqlite_metadata_bootstrap() -> None:
    importlib.import_module("models")
    importlib.import_module("models.lead")
    database = importlib.import_module("database")
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    try:
        database.Base.metadata.create_all(engine)
        with engine.begin() as connection:
            table_names = set(sa.inspect(connection).get_table_names())
            generated_id = connection.scalar(
                database.Base.metadata.tables["gmail_sync_accounts"]
                .insert()
                .values(workspace_email="sqlite-default@example.test")
                .returning(database.Base.metadata.tables["gmail_sync_accounts"].c.id)
            )
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    database.Base.metadata.tables["gmail_sync_accounts"]
                    .insert()
                    .values(workspace_email=" SQLite@example.test ")
                )
        assert set(TABLES).issubset(table_names)
        assert isinstance(generated_id, UUID)
    finally:
        engine.dispose()


def test_revision_83_generated_ddl_has_all_tables_and_refuses_nonempty_downgrade() -> (
    None
):
    upgrade = _render("upgrade")
    for table in TABLES:
        assert f"CREATE TABLE {table}" in upgrade
    assert (
        "delivery_state IN ('sending', 'delivery_uncertain') AND "
        "reconciled_outcome IS DISTINCT FROM 'not_delivered'"
    ) in upgrade
    assert "gmail_sync_states" not in upgrade
    assert "gmail_history_runs" not in upgrade
    assert "crm_task_email_sources" not in upgrade
    assert "gmail_obligation_suppressions" not in upgrade
    assert "gmail_task_intake_reject_evidence_mutation" in upgrade
    assert "trg_gmail_extracted_obligations_append_only" in upgrade
    assert "trg_crm_task_suggestion_sources_append_only" in upgrade
    assert "gmail_task_intake_guard_suppression_identity" in upgrade
    assert "trg_crm_task_suggestion_suppressions_identity_immutable" in upgrade
    for forbidden in (
        "raw_body",
        "body_text",
        "access_token",
        "refresh_token",
        "oauth_token",
    ):
        assert forbidden not in upgrade

    downgrade = _render("downgrade")
    expected_lock = "LOCK TABLE " + ", ".join(TABLES) + " IN ACCESS EXCLUSIVE MODE"
    assert expected_lock in downgrade
    assert (
        "revision 83 downgrade refused: Gmail task intake evidence exists" in downgrade
    )
    for table in TABLES:
        assert f"EXISTS (SELECT 1 FROM {table} LIMIT 1)" in downgrade
        assert f"DROP TABLE {table}" in downgrade
    assert downgrade.index(expected_lock) < downgrade.index("EXISTS (SELECT 1")
    assert downgrade.index("EXISTS (SELECT 1") < downgrade.index("DROP TABLE")
    assert "DROP FUNCTION gmail_task_intake_reject_evidence_mutation" in downgrade
    assert "DROP FUNCTION gmail_task_intake_guard_suppression_identity" in downgrade


def test_revision_83_upgrades_real_postgresql_and_enforces_contracts() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ) as run_marker:
            run_alembic(url, "upgrade", DOWN_REVISION)
            with engine.begin() as connection:
                _seed_existing_crm(connection)

            run_alembic(url, "upgrade", REVISION)
            with engine.connect() as connection:
                assert connection.scalar(sa.text("SHOW server_version_num")).startswith(
                    "16"
                )
                assert (
                    connection.scalar(
                        sa.text(
                            "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
                        )
                    )
                    is True
                )
                assert (
                    connection.scalar(
                        sa.text("SELECT version_num FROM alembic_version")
                    )
                    == REVISION
                )
                _assert_real_schema_matches_models(
                    connection,
                    _model_tables(),
                    omit_task5_overlays=True,
                )
                assert connection.execute(
                    sa.text(
                        "SELECT c.first_name, t.title, t.version "
                        "FROM crm_contacts AS c JOIN crm_tasks AS t "
                        "ON t.contact_id = c.id WHERE t.id = 8302"
                    )
                ).one() == (
                    "Preexisting",
                    "Preserve through Gmail intake",
                    1,
                )
                inspector = sa.inspect(connection)
                origin_indexes = {
                    index["name"]: index
                    for index in inspector.get_indexes("gmail_message_origins")
                }
                unresolved_where = str(
                    origin_indexes["uq_gmail_message_origins_unresolved_send"][
                        "dialect_options"
                    ]["postgresql_where"]
                )
                assert "IS DISTINCT FROM 'not_delivered'" in unresolved_where
                assert "<>" not in unresolved_where and "!=" not in unresolved_where
                assert (
                    origin_indexes["ix_gmail_message_origins_account_thread"]["unique"]
                    is False
                )
                receipt_indexes = {
                    index["name"]: index
                    for index in inspector.get_indexes("gmail_message_receipts")
                }
                assert (
                    receipt_indexes["ix_gmail_message_receipts_account_thread"][
                        "unique"
                    ]
                    is False
                )

            account_id = UUID("00000000-0000-4000-8000-000000008311")
            audit_id: int
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'origin@example.test')"
                    ),
                    {"id": account_id},
                )
                audit_id = connection.scalar(
                    sa.text(
                        "INSERT INTO agent_action_audits "
                        "(actor, action_id, method, path, status_code, allowed, "
                        "request_meta, response_meta) VALUES "
                        "('hermes', 'gmail.send', 'POST', '/test', 202, true, "
                        "'{}', '{}') RETURNING id"
                    )
                )
                original_origin_id = connection.scalar(
                    sa.text(
                        "INSERT INTO gmail_message_origins "
                        "(account_id, request_id, canonical_send_hash, "
                        "canonical_envelope_hash, canonical_body_hash, "
                        "origin_kind, delivery_state, action_audit_id) VALUES "
                        "(:account_id, :request_id, :send_hash, :envelope_hash, "
                        ":body_hash, 'sydney_client_send', 'sending', :audit_id) "
                        "RETURNING id"
                    ),
                    {
                        "account_id": account_id,
                        "request_id": UUID("00000000-0000-4000-8000-000000008312"),
                        "send_hash": "c" * 64,
                        "envelope_hash": "d" * 64,
                        "body_hash": "e" * 64,
                        "audit_id": audit_id,
                    },
                )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO gmail_message_origins "
                            "(account_id, request_id, canonical_send_hash, "
                            "canonical_envelope_hash, canonical_body_hash, "
                            "origin_kind, delivery_state, action_audit_id) VALUES "
                            "(:account_id, :request_id, :send_hash, :envelope_hash, "
                            ":body_hash, 'system_automation', "
                            "'delivery_uncertain', :audit_id)"
                        ),
                        {
                            "account_id": account_id,
                            "request_id": UUID("00000000-0000-4000-8000-000000008313"),
                            "send_hash": "c" * 64,
                            "envelope_hash": "f" * 64,
                            "body_hash": "0" * 64,
                            "audit_id": audit_id,
                        },
                    )
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE gmail_message_origins SET "
                        "reconciled_outcome = 'not_delivered', "
                        "reconciled_at = :now WHERE account_id = :account_id"
                    ),
                    {
                        "now": datetime(2026, 8, 20, tzinfo=timezone.utc),
                        "account_id": account_id,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_message_origins "
                        "(account_id, request_id, retry_of_origin_id, "
                        "canonical_send_hash, "
                        "canonical_envelope_hash, canonical_body_hash, "
                        "origin_kind, delivery_state, action_audit_id) VALUES "
                        "(:account_id, :request_id, :retry_of_origin_id, "
                        ":send_hash, :envelope_hash, "
                        ":body_hash, 'system_automation', "
                        "'delivery_uncertain', :audit_id)"
                    ),
                    {
                        "account_id": account_id,
                        "request_id": UUID("00000000-0000-4000-8000-000000008314"),
                        "retry_of_origin_id": original_origin_id,
                        "send_hash": "c" * 64,
                        "envelope_hash": "f" * 64,
                        "body_hash": "0" * 64,
                        "audit_id": audit_id,
                    },
                )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO gmail_message_origins "
                            "(account_id, request_id, retry_of_origin_id, "
                            "canonical_send_hash, canonical_envelope_hash, "
                            "canonical_body_hash, origin_kind, delivery_state, "
                            "action_audit_id) VALUES "
                            "(:account_id, :request_id, :retry_of_origin_id, "
                            ":send_hash, :envelope_hash, :body_hash, "
                            "'system_automation', 'delivery_uncertain', :audit_id)"
                        ),
                        {
                            "account_id": account_id,
                            "request_id": UUID("00000000-0000-4000-8000-000000008315"),
                            "retry_of_origin_id": original_origin_id,
                            "send_hash": "9" * 64,
                            "envelope_hash": "8" * 64,
                            "body_hash": "7" * 64,
                            "audit_id": audit_id,
                        },
                    )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO gmail_message_origins "
                            "(account_id, request_id, retry_of_origin_id, "
                            "canonical_send_hash, canonical_envelope_hash, "
                            "canonical_body_hash, origin_kind, delivery_state, "
                            "action_audit_id) VALUES "
                            "(:account_id, :request_id, :retry_of_origin_id, "
                            ":send_hash, :envelope_hash, :body_hash, "
                            "'system_automation', 'delivery_uncertain', :audit_id)"
                        ),
                        {
                            "account_id": account_id,
                            "request_id": UUID("00000000-0000-4000-8000-000000008316"),
                            "retry_of_origin_id": UUID(
                                "00000000-0000-4000-8000-000000009999"
                            ),
                            "send_hash": "6" * 64,
                            "envelope_hash": "5" * 64,
                            "body_hash": "4" * 64,
                            "audit_id": audit_id,
                        },
                    )

            heads = run_alembic(url, "heads")
            repository_head = _script_directory().get_current_head()
            assert repository_head is not None
            assert heads.count(f"{repository_head} (head)") == 1

            with engine.begin() as connection:
                verify_exact_ownership(
                    connection,
                    expected_database=expected_database,
                    run_marker=run_marker,
                )
                connection.execute(sa.text("DELETE FROM gmail_message_origins"))
                connection.execute(sa.text("DELETE FROM gmail_sync_accounts"))
            run_owned_alembic_downgrade(
                url,
                DOWN_REVISION,
                expected_database=expected_database,
                run_marker=run_marker,
            )
            with engine.connect() as connection:
                inspector = sa.inspect(connection)
                assert set(TABLES).isdisjoint(inspector.get_table_names())
                assert (
                    connection.scalar(
                        sa.text("SELECT title FROM crm_tasks WHERE id = 8302")
                    )
                    == "Preserve through Gmail intake"
                )
    finally:
        engine.dispose()


@pytest.mark.parametrize("target_table", TABLES)
def test_revision_83_refuses_each_nonempty_owned_table_without_data_loss(
    target_table: str,
) -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ) as run_marker:
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                _seed_existing_crm(connection)
                evidence_ids = _seed_all_intake_tables(connection)
                _retain_only_intake_table(
                    connection,
                    target_table,
                    expected_database=expected_database,
                    run_marker=run_marker,
                )

            with pytest.raises(
                RuntimeError,
                match="revision 83 downgrade refused: Gmail task intake evidence exists",
            ):
                run_owned_alembic_downgrade(
                    url,
                    DOWN_REVISION,
                    expected_database=expected_database,
                    run_marker=run_marker,
                )

            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        sa.text("SELECT version_num FROM alembic_version")
                    )
                    == REVISION
                )
                assert (
                    connection.scalar(
                        sa.text(
                            f'SELECT count(*) FROM "{target_table}" WHERE id = :id'
                        ),
                        {"id": evidence_ids[target_table]},
                    )
                    == 1
                )
                assert all(
                    connection.scalar(sa.text(f'SELECT count(*) FROM "{table_name}"'))
                    == (1 if table_name == target_table else 0)
                    for table_name in TABLES
                )
                assert (
                    connection.scalar(
                        sa.text("SELECT title FROM crm_tasks WHERE id = 8302")
                    )
                    == "Preserve through Gmail intake"
                )
    finally:
        engine.dispose()


def test_downgrade_lock_closes_the_concurrent_evidence_insert_race() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url), pool_size=3, max_overflow=0)
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ) as run_marker:
            run_alembic(url, "upgrade", REVISION)

            def attempt_downgrade() -> str:
                try:
                    run_owned_alembic_downgrade(
                        url,
                        DOWN_REVISION,
                        expected_database=expected_database,
                        run_marker=run_marker,
                    )
                except RuntimeError as error:
                    return str(error)
                return "downgrade unexpectedly succeeded"

            with engine.connect() as writer:
                writer_transaction = writer.begin()
                evidence_id = UUID("00000000-0000-4000-8000-000000008391")
                writer.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'downgrade-race@example.test')"
                    ),
                    {"id": evidence_id},
                )
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(attempt_downgrade)
                    deadline = time.monotonic() + 5
                    waiting_for_exclusive_lock = False
                    while time.monotonic() < deadline:
                        with engine.connect() as monitor:
                            waiting_for_exclusive_lock = bool(
                                monitor.scalar(
                                    sa.text(
                                        "SELECT EXISTS ("
                                        "SELECT 1 FROM pg_locks AS locks "
                                        "JOIN pg_class AS relation ON "
                                        "relation.oid = locks.relation "
                                        "WHERE relation.relname = "
                                        "'gmail_sync_accounts' AND "
                                        "locks.mode = 'AccessExclusiveLock' "
                                        "AND NOT locks.granted)"
                                    )
                                )
                            )
                        if waiting_for_exclusive_lock:
                            break
                        time.sleep(0.05)
                    if not waiting_for_exclusive_lock or future.done():
                        writer_transaction.rollback()
                        future.result(timeout=10)
                        pytest.fail("downgrade did not wait for the evidence writer")
                    writer_transaction.commit()
                    downgrade_error = future.result(timeout=10)

            assert (
                "revision 83 downgrade refused: Gmail task intake evidence exists"
                in downgrade_error
            )
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        sa.text("SELECT version_num FROM alembic_version")
                    )
                    == REVISION
                )
                assert (
                    connection.scalar(
                        sa.text(
                            "SELECT count(*) FROM gmail_sync_accounts WHERE id = :id"
                        ),
                        {"id": evidence_id},
                    )
                    == 1
                )
    finally:
        engine.dispose()


def test_unresolved_send_partial_index_serializes_two_null_outcome_sessions() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url), pool_size=2, max_overflow=0)
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            account_id = UUID("00000000-0000-4000-8000-000000008341")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'race@example.test')"
                    ),
                    {"id": account_id},
                )
                audit_id = connection.scalar(
                    sa.text(
                        "INSERT INTO agent_action_audits "
                        "(actor, action_id, method, path, status_code, allowed, "
                        "request_meta, response_meta) VALUES "
                        "('hermes', 'gmail.send.race', 'POST', '/test', 202, "
                        "true, '{}', '{}') RETURNING id"
                    )
                )

            barrier = threading.Barrier(2)

            def insert_origin(request_id: UUID) -> tuple[int, str]:
                with engine.connect() as connection:
                    transaction = connection.begin()
                    backend_pid = connection.scalar(sa.text("SELECT pg_backend_pid()"))
                    barrier.wait(timeout=5)
                    try:
                        connection.execute(
                            sa.text(
                                "INSERT INTO gmail_message_origins "
                                "(account_id, request_id, canonical_send_hash, "
                                "canonical_envelope_hash, canonical_body_hash, "
                                "origin_kind, delivery_state, action_audit_id) "
                                "VALUES (:account_id, :request_id, :send_hash, "
                                ":envelope_hash, :body_hash, "
                                "'sydney_client_send', 'sending', :audit_id)"
                            ),
                            {
                                "account_id": account_id,
                                "request_id": request_id,
                                "send_hash": "a" * 64,
                                "envelope_hash": "b" * 64,
                                "body_hash": "c" * 64,
                                "audit_id": audit_id,
                            },
                        )
                        transaction.commit()
                        return backend_pid, "inserted"
                    except sa.exc.IntegrityError:
                        transaction.rollback()
                        return backend_pid, "conflict"

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        insert_origin,
                        UUID("00000000-0000-4000-8000-000000008342"),
                    ),
                    executor.submit(
                        insert_origin,
                        UUID("00000000-0000-4000-8000-000000008343"),
                    ),
                ]
                results = [future.result(timeout=10) for future in futures]

            assert len({backend_pid for backend_pid, _ in results}) == 2
            assert sorted(status for _, status in results) == [
                "conflict",
                "inserted",
            ]
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        sa.text(
                            "SELECT count(*) FROM gmail_message_origins "
                            "WHERE account_id = :account_id "
                            "AND canonical_send_hash = :send_hash "
                            "AND reconciled_outcome IS NULL"
                        ),
                        {"account_id": account_id, "send_hash": "a" * 64},
                    )
                    == 1
                )
    finally:
        engine.dispose()


def test_workspace_email_identity_is_lowercase_trimmed_and_nonblank() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (workspace_email) "
                        "VALUES ('canonical@example.test')"
                    )
                )
            for invalid_email in (
                "Canonical@example.test",
                " canonical@example.test",
                "canonical@example.test ",
                "   ",
            ):
                with pytest.raises(sa.exc.IntegrityError):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "INSERT INTO gmail_sync_accounts "
                                "(workspace_email) VALUES (:workspace_email)"
                            ),
                            {"workspace_email": invalid_email},
                        )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO gmail_sync_accounts (workspace_email) "
                            "VALUES ('canonical@example.test')"
                        )
                    )
    finally:
        engine.dispose()


def test_suppression_scope_allows_same_fingerprint_in_unrelated_threads() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                admin_id = connection.scalar(
                    sa.text(
                        "INSERT INTO admin_users (email, hashed_password) "
                        "VALUES ('admin@example.test', 'test-only') RETURNING id"
                    )
                )
                audit_id = connection.scalar(
                    sa.text(
                        "INSERT INTO agent_action_audits "
                        "(actor, action_id, method, path, status_code, allowed, "
                        "request_meta, response_meta) VALUES "
                        "('command_admin', 'suggestion.dismiss', 'POST', "
                        "'/test', 200, true, '{}', '{}') RETURNING id"
                    )
                )
                for scope in (
                    "gmail:00000000-0000-4000-8000-000000008321:thread-a",
                    "gmail:00000000-0000-4000-8000-000000008321:thread-b",
                ):
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestion_suppressions "
                            "(source_type, source_scope_key, source_action_key, "
                            "obligation_fingerprint, identity_instance_digest, "
                            "dismissal_reason, "
                            "dismissed_by_admin_id, dismissal_audit_id) VALUES "
                            "('gmail_message', :scope, 'send-disclosure', "
                            ":fingerprint, :instance_digest, "
                            "'Not a task', :admin_id, :audit_id)"
                        ),
                        {
                            "scope": scope,
                            "fingerprint": "f" * 64,
                            "instance_digest": "e" * 64,
                            "admin_id": admin_id,
                            "audit_id": audit_id,
                        },
                    )
                assert (
                    connection.scalar(
                        sa.text(
                            "SELECT count(*) FROM crm_task_suggestion_suppressions "
                            "WHERE obligation_fingerprint = :fingerprint"
                        ),
                        {"fingerprint": "f" * 64},
                    )
                    == 2
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestion_suppressions "
                        "(source_type, source_scope_key, source_action_key, "
                        "obligation_fingerprint, identity_instance_digest, "
                        "dismissal_reason, dismissed_by_admin_id, "
                        "dismissal_audit_id) VALUES "
                        "('gmail_message', :scope, 'send-disclosure', "
                        ":fingerprint, :instance_digest, 'Different instance', "
                        ":admin_id, :audit_id)"
                    ),
                    {
                        "scope": (
                            "gmail:00000000-0000-4000-8000-000000008321:thread-a"
                        ),
                        "fingerprint": "f" * 64,
                        "instance_digest": "d" * 64,
                        "admin_id": admin_id,
                        "audit_id": audit_id,
                    },
                )
                assert (
                    connection.scalar(
                        sa.text(
                            "SELECT count(*) FROM "
                            "crm_task_suggestion_suppressions WHERE "
                            "obligation_fingerprint = :fingerprint"
                        ),
                        {"fingerprint": "f" * 64},
                    )
                    == 3
                )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestion_suppressions "
                            "(source_type, source_scope_key, source_action_key, "
                            "obligation_fingerprint, identity_instance_digest, "
                            "dismissal_reason, dismissed_by_admin_id, "
                            "dismissal_audit_id) VALUES "
                            "('gmail_message', :scope, 'send-disclosure', "
                            ":fingerprint, :instance_digest, 'Exact duplicate', "
                            ":admin_id, :audit_id)"
                        ),
                        {
                            "scope": (
                                "gmail:00000000-0000-4000-8000-000000008321:thread-a"
                            ),
                            "fingerprint": "f" * 64,
                            "instance_digest": "e" * 64,
                            "admin_id": admin_id,
                            "audit_id": audit_id,
                        },
                    )
            with engine.begin() as connection:
                override_audit_id = connection.scalar(
                    sa.text(
                        "INSERT INTO agent_action_audits "
                        "(actor, action_id, method, path, status_code, allowed, "
                        "request_meta, response_meta) VALUES "
                        "('admin', 'gmail_task_intake.reprocess', 'POST', "
                        "'/api/v1/admin/integrations/gmail-task-intake/reprocess/"
                        "00000000-0000-4000-8000-000000008322', 200, true, "
                        "'{}', '{}') RETURNING id"
                    )
                )
                connection.execute(
                    sa.text(
                        "UPDATE crm_task_suggestion_suppressions SET "
                        "reprocess_override_at = CURRENT_TIMESTAMP, "
                        "reprocess_override_by_admin_id = :admin_id, "
                        "reprocess_override_audit_id = :audit_id "
                        "WHERE source_scope_key = :scope AND "
                        "identity_instance_digest = :instance_digest"
                    ),
                    {
                        "admin_id": admin_id,
                        "audit_id": override_audit_id,
                        "instance_digest": "e" * 64,
                        "scope": (
                            "gmail:00000000-0000-4000-8000-000000008321:thread-a"
                        ),
                    },
                )
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE crm_task_suggestion_suppressions SET "
                        "reprocess_override_consumed_at = CURRENT_TIMESTAMP "
                        "WHERE source_scope_key = :scope AND "
                        "identity_instance_digest = :instance_digest"
                    ),
                    {
                        "scope": (
                            "gmail:00000000-0000-4000-8000-000000008321:thread-a"
                        ),
                        "instance_digest": "e" * 64,
                    },
                )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "UPDATE crm_task_suggestion_suppressions SET "
                            "reprocess_override_consumed_at = "
                            "reprocess_override_at - INTERVAL '1 second' "
                            "WHERE source_scope_key = :scope AND "
                            "identity_instance_digest = :instance_digest"
                        ),
                        {
                            "scope": (
                                "gmail:00000000-0000-4000-8000-000000008321:thread-a"
                            ),
                            "instance_digest": "e" * 64,
                        },
                    )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "UPDATE crm_task_suggestion_suppressions SET "
                            "dismissed_at = reprocess_override_at + "
                            "INTERVAL '1 second' WHERE source_scope_key = :scope "
                            "AND identity_instance_digest = :instance_digest"
                        ),
                        {
                            "scope": (
                                "gmail:00000000-0000-4000-8000-000000008321:thread-a"
                            ),
                            "instance_digest": "e" * 64,
                        },
                    )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "UPDATE crm_task_suggestion_suppressions SET "
                            "reprocess_override_at = CURRENT_TIMESTAMP, "
                            "reprocess_override_by_admin_id = :admin_id, "
                            "reprocess_override_audit_id = :audit_id "
                            "WHERE source_scope_key = :scope"
                        ),
                        {
                            "admin_id": admin_id,
                            "audit_id": override_audit_id,
                            "scope": (
                                "gmail:00000000-0000-4000-8000-000000008321:thread-b"
                            ),
                        },
                    )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestion_suppressions "
                            "(source_type, source_scope_key, source_action_key, "
                            "obligation_fingerprint, dismissal_reason, "
                            "dismissed_by_admin_id, dismissal_audit_id) VALUES "
                            "('gmail_message', :scope, 'send-disclosure', "
                            ":fingerprint, "
                            "'Duplicate', :admin_id, :audit_id)"
                        ),
                        {
                            "scope": (
                                "gmail:00000000-0000-4000-8000-000000008321:thread-a"
                            ),
                            "fingerprint": "f" * 64,
                            "admin_id": admin_id,
                            "audit_id": audit_id,
                        },
                    )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestion_suppressions "
                            "(source_type, source_scope_key, source_action_key, "
                            "obligation_fingerprint, dismissal_reason, "
                            "dismissed_by_admin_id, dismissal_audit_id) VALUES "
                            "('gmail', 'legacy:thread', 'legacy-action', "
                            ":fingerprint, 'Legacy alias', :admin_id, :audit_id)"
                        ),
                        {
                            "fingerprint": "e" * 64,
                            "admin_id": admin_id,
                            "audit_id": audit_id,
                        },
                    )
    finally:
        engine.dispose()


def test_origin_kind_and_reconciliation_states_fail_closed_on_real_postgresql() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            account_id = UUID("00000000-0000-4000-8000-000000008351")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'origin-state@example.test')"
                    ),
                    {"id": account_id},
                )
                audit_id = connection.scalar(
                    sa.text(
                        "INSERT INTO agent_action_audits "
                        "(actor, action_id, method, path, status_code, allowed, "
                        "request_meta, response_meta) VALUES "
                        "('hermes', 'gmail.send.state', 'POST', '/test', 202, "
                        "true, '{}', '{}') RETURNING id"
                    )
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_message_origins "
                        "(account_id, gmail_message_id, gmail_thread_id, "
                        "origin_kind, delivery_state) VALUES "
                        "(:account_id, 'human-message', 'human-thread', "
                        "'human_send', 'succeeded')"
                    ),
                    {"account_id": account_id},
                )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO gmail_message_origins "
                            "(account_id, origin_kind, delivery_state) VALUES "
                            "(:account_id, 'human_send', 'sending')"
                        ),
                        {"account_id": account_id},
                    )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO gmail_message_origins "
                            "(account_id, request_id, canonical_send_hash, "
                            "canonical_envelope_hash, canonical_body_hash, "
                            "origin_kind, delivery_state, reconciled_outcome, "
                            "action_audit_id) VALUES "
                            "(:account_id, :request_id, :send_hash, "
                            ":envelope_hash, :body_hash, 'sydney_client_send', "
                            "'delivery_uncertain', 'delivered', :audit_id)"
                        ),
                        {
                            "account_id": account_id,
                            "request_id": UUID("00000000-0000-4000-8000-000000008352"),
                            "send_hash": "1" * 64,
                            "envelope_hash": "2" * 64,
                            "body_hash": "3" * 64,
                            "audit_id": audit_id,
                        },
                    )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO gmail_message_origins "
                            "(account_id, request_id, canonical_send_hash, "
                            "canonical_envelope_hash, canonical_body_hash, "
                            "gmail_message_id, gmail_thread_id, origin_kind, "
                            "delivery_state, reconciled_outcome, action_audit_id) "
                            "VALUES (:account_id, :request_id, :send_hash, "
                            ":envelope_hash, :body_hash, 'provider-message', "
                            "'provider-thread', 'system_automation', "
                            "'succeeded', 'not_delivered', :audit_id)"
                        ),
                        {
                            "account_id": account_id,
                            "request_id": UUID("00000000-0000-4000-8000-000000008353"),
                            "send_hash": "4" * 64,
                            "envelope_hash": "5" * 64,
                            "body_hash": "6" * 64,
                            "audit_id": audit_id,
                        },
                    )
    finally:
        engine.dispose()


def test_provenance_and_applied_result_shapes_fail_closed_on_real_postgresql() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            account_id = UUID("00000000-0000-4000-8000-000000008361")
            other_account_id = UUID("00000000-0000-4000-8000-000000008372")
            receipt_one = UUID("00000000-0000-4000-8000-000000008362")
            receipt_two = UUID("00000000-0000-4000-8000-000000008363")
            receipt_three = UUID("00000000-0000-4000-8000-000000008373")
            attempt_one = UUID("00000000-0000-4000-8000-000000008364")
            attempt_two = UUID("00000000-0000-4000-8000-000000008365")
            attempt_three = UUID("00000000-0000-4000-8000-000000008374")
            obligation_one = UUID("00000000-0000-4000-8000-000000008366")
            obligation_two = UUID("00000000-0000-4000-8000-000000008367")
            obligation_three = UUID("00000000-0000-4000-8000-000000008375")
            suggestion_id = UUID("00000000-0000-4000-8000-000000008368")
            suggestion_two = UUID("00000000-0000-4000-8000-000000008377")
            suggestion_three = UUID("00000000-0000-4000-8000-000000008378")
            now = datetime(2026, 8, 20, tzinfo=timezone.utc)
            with engine.begin() as connection:
                _seed_existing_crm(connection)
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'provenance@example.test'), "
                        "(:other_id, 'other-provenance@example.test')"
                    ),
                    {"id": account_id, "other_id": other_account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_message_receipts "
                        "(id, account_id, gmail_message_id, gmail_thread_id, "
                        "direction, message_at) VALUES "
                        "(:one, :account_id, 'message-one', 'thread-one', "
                        "'received', :now), "
                        "(:two, :account_id, 'message-two', 'thread-two', "
                        "'sent', :now), "
                        "(:three, :other_account_id, 'message-three', "
                        "'thread-one', 'received', :now)"
                    ),
                    {
                        "one": receipt_one,
                        "two": receipt_two,
                        "three": receipt_three,
                        "account_id": account_id,
                        "other_account_id": other_account_id,
                        "now": now,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extraction_attempts "
                        "(id, receipt_id, schema_version, attempt_number) VALUES "
                        "(:one, :receipt_one, 'gmail-task-v1', 1), "
                        "(:two, :receipt_two, 'gmail-task-v1', 1), "
                        "(:three, :receipt_three, 'gmail-task-v1', 1)"
                    ),
                    {
                        "one": attempt_one,
                        "two": attempt_two,
                        "three": attempt_three,
                        "receipt_one": receipt_one,
                        "receipt_two": receipt_two,
                        "receipt_three": receipt_three,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, title, "
                        "payload_hash, model_schema_version, "
                        "obligation_fingerprint, primary_instance_digest) "
                        "VALUES (:one, :account_id, 'thread-one', "
                        "'gmail_message', 'gmail:provenance:thread-one', "
                        "'action-one', 'Suggestion one', :payload_one, "
                        "'gmail-task-v1', :fingerprint_one, :digest_one), "
                        "(:two, :account_id, 'thread-two', 'gmail_message', "
                        "'gmail:provenance:thread-two', 'action-two', "
                        "'Suggestion two', :payload_two, 'gmail-task-v1', "
                        ":fingerprint_two, :digest_two), "
                        "(:three, :other_account_id, 'thread-one', "
                        "'gmail_message', 'gmail:other-provenance:thread-one', "
                        "'action-three', 'Suggestion three', :payload_three, "
                        "'gmail-task-v1', :fingerprint_three, :digest_three)"
                    ),
                    {
                        "one": suggestion_id,
                        "two": suggestion_two,
                        "three": suggestion_three,
                        "account_id": account_id,
                        "other_account_id": other_account_id,
                        "payload_one": "c" * 64,
                        "payload_two": "d" * 64,
                        "payload_three": "e" * 64,
                        "fingerprint_one": "a" * 64,
                        "fingerprint_two": "b" * 64,
                        "fingerprint_three": "8" * 64,
                        "digest_one": "1" * 64,
                        "digest_two": "2" * 64,
                        "digest_three": "3" * 64,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extracted_obligations "
                        "(id, receipt_id, extraction_attempt_id, action_key, "
                        "schema_version, title, taxonomy_fallback, "
                        "obligation_fingerprint, identity_instance_digest, "
                        "reconciliation_material_hash, "
                        "reconciled_suggestion_id) VALUES "
                        "(:one, :receipt_one, :attempt_one, 'action-one', "
                        "'gmail-task-v1', 'First obligation', false, "
                        ":fingerprint_one, :digest_one, :material_one, "
                        ":suggestion_one), "
                        "(:two, :receipt_two, :attempt_two, 'action-two', "
                        "'gmail-task-v1', 'Second obligation', false, "
                        ":fingerprint_two, :digest_two, :material_two, "
                        ":suggestion_two), "
                        "(:three, :receipt_three, :attempt_three, "
                        "'action-three', 'gmail-task-v1', 'Third obligation', "
                        "false, :fingerprint_three, :digest_three, "
                        ":material_three, :suggestion_three)"
                    ),
                    {
                        "one": obligation_one,
                        "two": obligation_two,
                        "three": obligation_three,
                        "receipt_one": receipt_one,
                        "receipt_two": receipt_two,
                        "receipt_three": receipt_three,
                        "attempt_one": attempt_one,
                        "attempt_two": attempt_two,
                        "attempt_three": attempt_three,
                        "fingerprint_one": "a" * 64,
                        "fingerprint_two": "b" * 64,
                        "fingerprint_three": "8" * 64,
                        "digest_one": "1" * 64,
                        "digest_two": "2" * 64,
                        "digest_three": "3" * 64,
                        "material_one": "4" * 64,
                        "material_two": "5" * 64,
                        "material_three": "6" * 64,
                        "suggestion_one": suggestion_id,
                        "suggestion_two": suggestion_two,
                        "suggestion_three": suggestion_three,
                    },
                )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO gmail_extracted_obligations "
                            "(receipt_id, extraction_attempt_id, action_key, "
                            "schema_version, title, taxonomy_fallback, "
                            "obligation_fingerprint, identity_instance_digest, "
                            "reconciliation_material_hash, "
                            "reconciled_suggestion_id) "
                            "VALUES (:receipt_two, :attempt_one, 'cross-wired', "
                            "'gmail-task-v1', 'Cross-wired obligation', false, "
                            ":fingerprint, :digest, :material_hash, "
                            ":suggestion_id)"
                        ),
                        {
                            "receipt_two": receipt_two,
                            "attempt_one": attempt_one,
                            "fingerprint": "d" * 64,
                            "digest": "7" * 64,
                            "material_hash": "9" * 64,
                            "suggestion_id": suggestion_two,
                        },
                    )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestion_sources "
                            "(suggestion_id, obligation_id, receipt_id, "
                            "gmail_account_id, gmail_thread_id, direction, "
                            "source_label) VALUES "
                            "(:suggestion_id, :obligation_one, :receipt_two, "
                            ":account_id, 'thread-two', 'sent', 'Wrong receipt')"
                        ),
                        {
                            "suggestion_id": suggestion_id,
                            "obligation_one": obligation_one,
                            "receipt_two": receipt_two,
                            "account_id": account_id,
                        },
                    )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestion_sources "
                            "(suggestion_id, obligation_id, receipt_id, "
                            "gmail_account_id, gmail_thread_id, direction, "
                            "source_label) VALUES "
                            "(:suggestion_id, :obligation_one, :receipt_one, "
                            ":account_id, 'thread-one', 'sent', 'Wrong direction')"
                        ),
                        {
                            "suggestion_id": suggestion_id,
                            "obligation_one": obligation_one,
                            "receipt_one": receipt_one,
                            "account_id": account_id,
                        },
                    )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestion_sources "
                            "(suggestion_id, obligation_id, receipt_id, "
                            "gmail_account_id, gmail_thread_id, direction, "
                            "source_label) VALUES "
                            "(:suggestion_id, :obligation_two, :receipt_two, "
                            ":account_id, 'thread-two', 'sent', "
                            "'Cross-thread suggestion source')"
                        ),
                        {
                            "suggestion_id": suggestion_id,
                            "obligation_two": obligation_two,
                            "receipt_two": receipt_two,
                            "account_id": account_id,
                        },
                    )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestion_sources "
                            "(suggestion_id, obligation_id, receipt_id, "
                            "gmail_account_id, gmail_thread_id, direction, "
                            "source_label) VALUES "
                            "(:suggestion_id, :obligation_three, :receipt_three, "
                            ":other_account_id, 'thread-one', 'received', "
                            "'Cross-account suggestion source')"
                        ),
                        {
                            "suggestion_id": suggestion_id,
                            "obligation_three": obligation_three,
                            "receipt_three": receipt_three,
                            "other_account_id": other_account_id,
                        },
                    )

            second_suggestion_id = UUID("00000000-0000-4000-8000-000000008376")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, title, payload_hash, "
                        "model_schema_version, obligation_fingerprint, "
                        "primary_instance_digest) VALUES "
                        "(:id, :account_id, 'thread-one', 'gmail_message', "
                        "'gmail:provenance:thread-one', 'action-successor', "
                        "'Second suggestion', :payload_hash, 'gmail-task-v1', "
                        ":fingerprint, :instance_digest)"
                    ),
                    {
                        "id": second_suggestion_id,
                        "account_id": account_id,
                        "payload_hash": "9" * 64,
                        "fingerprint": "a" * 64,
                        "instance_digest": "1" * 64,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestion_sources "
                        "(suggestion_id, obligation_id, receipt_id, "
                        "gmail_account_id, gmail_thread_id, direction, "
                        "source_label) VALUES "
                        "(:suggestion_id, :obligation_id, :receipt_id, "
                        ":account_id, 'thread-one', 'received', 'First source')"
                    ),
                    {
                        "suggestion_id": suggestion_id,
                        "obligation_id": obligation_one,
                        "receipt_id": receipt_one,
                        "account_id": account_id,
                    },
                )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestion_sources "
                            "(suggestion_id, obligation_id, receipt_id, "
                            "gmail_account_id, gmail_thread_id, direction, "
                            "source_label) VALUES "
                            "(:suggestion_id, :obligation_id, :receipt_id, "
                            ":account_id, 'thread-one', 'received', "
                            "'Second source for one obligation')"
                        ),
                        {
                            "suggestion_id": second_suggestion_id,
                            "obligation_id": obligation_one,
                            "receipt_id": receipt_one,
                            "account_id": account_id,
                        },
                    )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestions "
                            "(gmail_account_id, gmail_thread_id, source_type, "
                            "source_scope_key, "
                            "source_action_key, title, state, applied_task_id, "
                            "payload_hash, model_schema_version, "
                            "obligation_fingerprint, primary_instance_digest) "
                            "VALUES "
                            "(:account_id, 'applied-without-key', 'gmail_message', "
                            "'gmail:provenance:applied-without-key', "
                            "'invalid-applied', 'Invalid applied', "
                            "'applied', 8302, :payload_hash, 'gmail-task-v1', "
                            ":fingerprint, repeat('a', 64))"
                        ),
                        {
                            "account_id": account_id,
                            "payload_hash": "e" * 64,
                            "fingerprint": "f" * 64,
                        },
                    )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestions "
                            "(gmail_account_id, gmail_thread_id, source_type, "
                            "source_scope_key, "
                            "source_action_key, title, state, applied_task_id, "
                            "application_idempotency_key, payload_hash, "
                            "model_schema_version, obligation_fingerprint, "
                            "primary_instance_digest) "
                            "VALUES (:account_id, 'pending-with-task', "
                            "'gmail_message', "
                            "'gmail:provenance:pending-with-task', "
                            "'invalid-pending', 'Invalid pending', "
                            "'pending_review', 8302, :application_key, "
                            ":payload_hash, 'gmail-task-v1', :fingerprint, "
                            "repeat('a', 64))"
                        ),
                        {
                            "application_key": UUID(
                                "00000000-0000-4000-8000-000000008369"
                            ),
                            "account_id": account_id,
                            "payload_hash": "0" * 64,
                            "fingerprint": "1" * 64,
                        },
                    )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestions "
                            "(gmail_account_id, gmail_thread_id, source_type, "
                            "source_scope_key, "
                            "source_action_key, title, blocker_codes, payload_hash, "
                            "model_schema_version, obligation_fingerprint, "
                            "primary_instance_digest) VALUES "
                            "(:account_id, 'duplicate-blockers', 'gmail_message', "
                            "'gmail:provenance:duplicate-blockers', "
                            "'invalid-blockers', 'Invalid blockers', "
                            "ARRAY['unsupported_owner', 'unsupported_owner']"
                            "::varchar[], :payload_hash, 'gmail-task-v1', "
                            ":fingerprint, repeat('a', 64))"
                        ),
                        {
                            "account_id": account_id,
                            "payload_hash": "2" * 64,
                            "fingerprint": "3" * 64,
                        },
                    )

            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, "
                        "source_action_key, title, state, "
                        "application_idempotency_key, applied_task_id, payload_hash, "
                        "model_schema_version, obligation_fingerprint, "
                        "primary_instance_digest) VALUES "
                        "(:account_id, 'failed-keyed', 'gmail_message', "
                        "'gmail:provenance:failed-keyed', 'failed-action', "
                        "'Failed keyed result', 'failed', "
                        ":failed_key, NULL, :failed_hash, 'gmail-task-v1', "
                        ":failed_fingerprint, repeat('a', 64)), "
                        "(:account_id, 'applied-complete', 'gmail_message', "
                        "'gmail:provenance:applied-complete', 'applied-action', "
                        "'Applied result', 'applied', "
                        ":applied_key, 8302, :applied_hash, 'gmail-task-v1', "
                        ":applied_fingerprint, repeat('b', 64))"
                    ),
                    {
                        "account_id": account_id,
                        "failed_key": UUID("00000000-0000-4000-8000-000000008370"),
                        "failed_hash": "4" * 64,
                        "failed_fingerprint": "5" * 64,
                        "applied_key": UUID("00000000-0000-4000-8000-000000008371"),
                        "applied_hash": "6" * 64,
                        "applied_fingerprint": "7" * 64,
                    },
                )
                assert (
                    connection.scalar(
                        sa.text(
                            "SELECT count(*) FROM crm_task_suggestions WHERE "
                            "(state = 'failed' AND applied_task_id IS NULL) OR "
                            "(state = 'applied' AND applied_task_id = 8302)"
                        )
                    )
                    == 2
                )
    finally:
        engine.dispose()


def test_direct_sydney_draft_source_identity_is_truthful_and_idempotent() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            request_id = UUID("00000000-0000-4000-8000-000000008381")
            account_id = UUID("00000000-0000-4000-8000-000000008382")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'direct-draft@example.test')"
                    ),
                    {"id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, "
                        "source_request_id, title, payload_hash, "
                        "model_schema_version, obligation_fingerprint, "
                        "primary_instance_digest) VALUES "
                        "(NULL, NULL, 'sydney_chat', 'agent-control:sydney', "
                        "'draft-task', "
                        ":request_id, 'Direct Sydney draft', :payload_hash, "
                        "'gmail-task-v1', :fingerprint, NULL), "
                        "(:account_id, 'thread-one', 'gmail_message', "
                        "'gmail:account-one:thread-one', "
                        "'action-one', NULL, 'Gmail suggestion', :gmail_hash, "
                        "'gmail-task-v1', :gmail_fingerprint, "
                        ":gmail_instance_digest)"
                    ),
                    {
                        "request_id": request_id,
                        "account_id": account_id,
                        "payload_hash": "8" * 64,
                        "fingerprint": "9" * 64,
                        "gmail_hash": "c" * 64,
                        "gmail_fingerprint": "d" * 64,
                        "gmail_instance_digest": "1" * 64,
                    },
                )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestions "
                            "(source_type, source_scope_key, source_action_key, "
                            "source_request_id, title, payload_hash, "
                            "model_schema_version, obligation_fingerprint) "
                            "VALUES ('sydney_chat', 'forged:changed-scope', "
                            "'changed-action', :request_id, 'Replay', :payload_hash, "
                            "'gmail-task-v1', :fingerprint)"
                        ),
                        {
                            "request_id": request_id,
                            "payload_hash": "e" * 64,
                            "fingerprint": "f" * 64,
                        },
                    )

            invalid_shapes = (
                {
                    "source_type": "sydney_chat",
                    "gmail_account_id": None,
                    "gmail_thread_id": "fabricated-thread",
                    "source_request_id": UUID("00000000-0000-4000-8000-000000008383"),
                },
                {
                    "source_type": "sydney_chat",
                    "gmail_account_id": None,
                    "gmail_thread_id": None,
                    "source_request_id": None,
                },
                {
                    "source_type": "gmail_message",
                    "gmail_account_id": account_id,
                    "gmail_thread_id": "thread-with-request",
                    "source_request_id": UUID("00000000-0000-4000-8000-000000008384"),
                },
                {
                    "source_type": "gmail_message",
                    "gmail_account_id": account_id,
                    "gmail_thread_id": None,
                    "source_request_id": None,
                },
                {
                    "source_type": "sydney_chat",
                    "gmail_account_id": account_id,
                    "gmail_thread_id": None,
                    "source_request_id": UUID("00000000-0000-4000-8000-000000008385"),
                },
            )
            for index, shape in enumerate(invalid_shapes, start=1):
                with pytest.raises(sa.exc.IntegrityError):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "INSERT INTO crm_task_suggestions "
                                "(gmail_account_id, gmail_thread_id, source_type, "
                                "source_scope_key, source_action_key, "
                                "source_request_id, title, payload_hash, "
                                "model_schema_version, obligation_fingerprint, "
                                "primary_instance_digest) "
                                "VALUES (:gmail_account_id, :gmail_thread_id, "
                                ":source_type, "
                                ":source_scope, :source_action, "
                                ":source_request_id, :title, :payload_hash, "
                                "'gmail-task-v1', :fingerprint, "
                                ":instance_digest)"
                            ),
                            {
                                **shape,
                                "source_scope": f"invalid:{index}",
                                "source_action": f"invalid-{index}",
                                "title": f"Invalid source shape {index}",
                                "payload_hash": f"{index:x}" * 64,
                                "fingerprint": f"{index + 4:x}" * 64,
                                "instance_digest": (
                                    "a" * 64
                                    if shape["source_type"] == "gmail_message"
                                    else None
                                ),
                            },
                        )
    finally:
        engine.dispose()


def test_duplicate_suggestions_are_source_scope_safe_and_never_self_reference() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            first_account = UUID("00000000-0000-4000-8000-0000000083a1")
            second_account = UUID("00000000-0000-4000-8000-0000000083a2")
            root_id = UUID("00000000-0000-4000-8000-0000000083a3")
            sydney_root_id = UUID("00000000-0000-4000-8000-0000000083a4")
            sydney_root_request_id = UUID("00000000-0000-4000-8000-0000000083a5")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:first, 'duplicate-scope-a@example.test'), "
                        "(:second, 'duplicate-scope-b@example.test')"
                    ),
                    {"first": first_account, "second": second_account},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, title, payload_hash, "
                        "model_schema_version, obligation_fingerprint, "
                        "primary_instance_digest) VALUES "
                        "(:id, :account_id, 'thread-safe', 'gmail_message', "
                        "'gmail:duplicate-scope:thread-safe', 'root-action', "
                        "'Root suggestion', :payload_hash, 'gmail-task-v1', "
                        ":fingerprint, :instance_digest)"
                    ),
                    {
                        "id": root_id,
                        "account_id": first_account,
                        "payload_hash": "a" * 64,
                        "fingerprint": "b" * 64,
                        "instance_digest": "c" * 64,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, source_type, source_scope_key, source_action_key, "
                        "source_request_id, title, payload_hash, "
                        "model_schema_version, obligation_fingerprint) VALUES "
                        "(:id, 'sydney_chat', 'sydney:chat:root', "
                        "'sydney-root-action', :request_id, 'Sydney root', "
                        ":payload_hash, 'gmail-task-v1', :fingerprint)"
                    ),
                    {
                        "id": sydney_root_id,
                        "request_id": sydney_root_request_id,
                        "payload_hash": "c" * 64,
                        "fingerprint": "d" * 64,
                    },
                )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "UPDATE crm_task_suggestions "
                            "SET duplicate_of_suggestion_id = id WHERE id = :id"
                        ),
                        {"id": root_id},
                    )

            invalid_scopes = (
                (second_account, "thread-safe", "cross-account"),
                (first_account, "thread-other", "cross-thread"),
            )
            for index, (account_id, thread_id, label) in enumerate(
                invalid_scopes,
                start=1,
            ):
                with pytest.raises(sa.exc.IntegrityError):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "INSERT INTO crm_task_suggestions "
                                "(gmail_account_id, gmail_thread_id, source_type, "
                                "source_scope_key, source_action_key, "
                                "duplicate_of_suggestion_id, title, payload_hash, "
                                "model_schema_version, obligation_fingerprint, "
                                "primary_instance_digest) "
                                "VALUES (:account_id, :thread_id, 'gmail_message', "
                                ":scope, :action, :root_id, :title, :payload_hash, "
                                "'gmail-task-v1', :fingerprint, "
                                ":instance_digest)"
                            ),
                            {
                                "account_id": account_id,
                                "thread_id": thread_id,
                                "scope": f"gmail:duplicate-scope:{label}",
                                "action": f"invalid-{label}",
                                "root_id": root_id,
                                "title": f"Invalid {label} duplicate",
                                "payload_hash": f"{index + 1:x}" * 64,
                                "fingerprint": f"{index + 3:x}" * 64,
                                "instance_digest": "d" * 64,
                            },
                        )

            with engine.begin() as connection:
                valid_id = connection.scalar(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, "
                        "duplicate_of_suggestion_id, title, payload_hash, "
                        "model_schema_version, obligation_fingerprint, "
                        "primary_instance_digest) "
                        "VALUES (:account_id, 'thread-safe', 'gmail_message', "
                        "'gmail:duplicate-scope:thread-safe', 'valid-child', "
                        ":root_id, "
                        "'Valid scoped duplicate', :payload_hash, "
                        "'gmail-task-v1', :fingerprint, :instance_digest) "
                        "RETURNING id"
                    ),
                    {
                        "account_id": first_account,
                        "root_id": root_id,
                        "payload_hash": "6" * 64,
                        "fingerprint": "7" * 64,
                        "instance_digest": "8" * 64,
                    },
                )
                assert valid_id is not None

            invalid_source_scopes = (
                (
                    "sydney_chat",
                    "gmail:duplicate-scope:thread-safe",
                    root_id,
                    UUID("00000000-0000-4000-8000-0000000083a6"),
                    "cross-source",
                ),
                (
                    "sydney_chat",
                    "sydney:chat:other",
                    sydney_root_id,
                    UUID("00000000-0000-4000-8000-0000000083a7"),
                    "cross-sydney-scope",
                ),
            )
            for (
                source_type,
                source_scope,
                duplicate_id,
                request_id,
                label,
            ) in invalid_source_scopes:
                with pytest.raises(sa.exc.IntegrityError):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "INSERT INTO crm_task_suggestions "
                                "(source_type, source_scope_key, "
                                "source_action_key, source_request_id, "
                                "duplicate_of_suggestion_id, title, "
                                "payload_hash, model_schema_version, "
                                "obligation_fingerprint) VALUES "
                                "(:source_type, :source_scope, :action, "
                                ":request_id, :duplicate_id, :title, "
                                ":payload_hash, 'gmail-task-v1', :fingerprint)"
                            ),
                            {
                                "source_type": source_type,
                                "source_scope": source_scope,
                                "action": f"invalid-{label}",
                                "request_id": request_id,
                                "duplicate_id": duplicate_id,
                                "title": f"Invalid {label} duplicate",
                                "payload_hash": "e" * 64,
                                "fingerprint": "f" * 64,
                            },
                        )

            with engine.begin() as connection:
                valid_sydney_id = connection.scalar(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(source_type, source_scope_key, source_action_key, "
                        "source_request_id, duplicate_of_suggestion_id, title, "
                        "payload_hash, model_schema_version, "
                        "obligation_fingerprint) VALUES "
                        "('sydney_chat', 'sydney:chat:root', 'sydney-child', "
                        ":request_id, :root_id, 'Valid Sydney duplicate', "
                        ":payload_hash, 'gmail-task-v1', :fingerprint) "
                        "RETURNING id"
                    ),
                    {
                        "request_id": UUID("00000000-0000-4000-8000-0000000083a8"),
                        "root_id": sydney_root_id,
                        "payload_hash": "1" * 64,
                        "fingerprint": "2" * 64,
                    },
                )
                assert valid_sydney_id is not None
    finally:
        engine.dispose()


def test_task_intake_evidence_rows_are_append_only_on_real_postgresql() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            account_id = UUID("00000000-0000-4000-8000-0000000083c1")
            receipt_id = UUID("00000000-0000-4000-8000-0000000083c2")
            attempt_id = UUID("00000000-0000-4000-8000-0000000083c3")
            suggestion_id = UUID("00000000-0000-4000-8000-0000000083c4")
            obligation_id = UUID("00000000-0000-4000-8000-0000000083c5")
            source_id = UUID("00000000-0000-4000-8000-0000000083c6")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'append-only@example.test')"
                    ),
                    {"id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_message_receipts "
                        "(id, account_id, gmail_message_id, gmail_thread_id, "
                        "direction, message_at, processing_state, "
                        "classification, body_hash) VALUES "
                        "(:id, :account_id, 'append-only-message', "
                        "'append-only-thread', 'received', CURRENT_TIMESTAMP, "
                        "'processed', 'eligible', :body_hash)"
                    ),
                    {
                        "id": receipt_id,
                        "account_id": account_id,
                        "body_hash": "a" * 64,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extraction_attempts "
                        "(id, receipt_id, schema_version, attempt_number, "
                        "state, completed_at) VALUES "
                        "(:id, :receipt_id, 'gmail-task-v1', 1, 'succeeded', "
                        "CURRENT_TIMESTAMP)"
                    ),
                    {"id": attempt_id, "receipt_id": receipt_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, title, "
                        "payload_hash, model_schema_version, "
                        "obligation_fingerprint, primary_instance_digest) "
                        "VALUES (:id, :account_id, 'append-only-thread', "
                        "'gmail_message', :scope, 'append-only-action', "
                        "'Append-only suggestion', :payload_hash, "
                        "'gmail-task-v1', :fingerprint, :instance_digest)"
                    ),
                    {
                        "id": suggestion_id,
                        "account_id": account_id,
                        "scope": f"gmail:{account_id}:append-only-thread",
                        "payload_hash": "b" * 64,
                        "fingerprint": "c" * 64,
                        "instance_digest": "d" * 64,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extracted_obligations "
                        "(id, receipt_id, extraction_attempt_id, action_key, "
                        "schema_version, title, obligation_fingerprint, "
                        "taxonomy_fallback, "
                        "identity_instance_digest, "
                        "reconciliation_material_hash, "
                        "reconciled_suggestion_id) "
                        "VALUES (:id, :receipt_id, :attempt_id, "
                        "'append-only-action', 'gmail-task-v1', "
                        "'Append-only obligation', :fingerprint, false, "
                        ":instance_digest, :material_hash, :suggestion_id)"
                    ),
                    {
                        "id": obligation_id,
                        "receipt_id": receipt_id,
                        "attempt_id": attempt_id,
                        "fingerprint": "c" * 64,
                        "instance_digest": "d" * 64,
                        "material_hash": "e" * 64,
                        "suggestion_id": suggestion_id,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestion_sources "
                        "(id, suggestion_id, obligation_id, receipt_id, "
                        "gmail_account_id, gmail_thread_id, direction, "
                        "source_label) VALUES (:id, :suggestion_id, "
                        ":obligation_id, :receipt_id, :account_id, "
                        "'append-only-thread', 'received', 'gmail:received:test')"
                    ),
                    {
                        "id": source_id,
                        "suggestion_id": suggestion_id,
                        "obligation_id": obligation_id,
                        "receipt_id": receipt_id,
                        "account_id": account_id,
                    },
                )

            for mutation in (
                "UPDATE gmail_extracted_obligations SET title = "
                "'Rewritten' WHERE id = :id",
                "UPDATE gmail_extracted_obligations SET "
                "reconciliation_material_hash = repeat('f', 64) "
                "WHERE id = :id",
                "DELETE FROM gmail_extracted_obligations WHERE id = :id",
            ):
                with pytest.raises(sa.exc.DBAPIError) as raised:
                    with engine.begin() as connection:
                        connection.execute(sa.text(mutation), {"id": obligation_id})
                assert "gmail_task_intake_evidence_append_only" in str(
                    raised.value.orig
                )
            for mutation in (
                "UPDATE crm_task_suggestion_sources SET source_label = "
                "'rewritten' WHERE id = :id",
                "DELETE FROM crm_task_suggestion_sources WHERE id = :id",
            ):
                with pytest.raises(sa.exc.DBAPIError) as raised:
                    with engine.begin() as connection:
                        connection.execute(sa.text(mutation), {"id": source_id})
                assert "gmail_task_intake_evidence_append_only" in str(
                    raised.value.orig
                )
    finally:
        engine.dispose()


def test_suggestion_source_must_match_obligation_disposition_on_postgresql() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            account_id = UUID("00000000-0000-4000-8000-0000000083f1")
            receipt_id = UUID("00000000-0000-4000-8000-0000000083f2")
            attempt_id = UUID("00000000-0000-4000-8000-0000000083f3")
            suggestion_a = UUID("00000000-0000-4000-8000-0000000083f4")
            suggestion_b = UUID("00000000-0000-4000-8000-0000000083f5")
            obligation_id = UUID("00000000-0000-4000-8000-0000000083f6")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'source-disposition@example.test')"
                    ),
                    {"id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_message_receipts "
                        "(id, account_id, gmail_message_id, gmail_thread_id, "
                        "direction, message_at, processing_state, "
                        "classification) VALUES (:id, :account_id, "
                        "'source-disposition-message', "
                        "'source-disposition-thread', 'received', "
                        "CURRENT_TIMESTAMP, 'processed', 'eligible')"
                    ),
                    {"id": receipt_id, "account_id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extraction_attempts "
                        "(id, receipt_id, schema_version, attempt_number, "
                        "state, completed_at) VALUES (:id, :receipt_id, "
                        "'gmail-task-v1', 1, 'succeeded', CURRENT_TIMESTAMP)"
                    ),
                    {"id": attempt_id, "receipt_id": receipt_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, title, "
                        "payload_hash, model_schema_version, "
                        "obligation_fingerprint, primary_instance_digest) "
                        "VALUES (:suggestion_a, :account_id, :thread_id, "
                        "'gmail_message', :scope, 'source-disposition-a', "
                        "'Suggestion A', :payload_a, 'gmail-task-v1', "
                        ":fingerprint, :instance_digest), "
                        "(:suggestion_b, :account_id, :thread_id, "
                        "'gmail_message', :scope, 'source-disposition-b', "
                        "'Suggestion B', :payload_b, 'gmail-task-v1', "
                        ":fingerprint, :instance_digest)"
                    ),
                    {
                        "suggestion_a": suggestion_a,
                        "suggestion_b": suggestion_b,
                        "account_id": account_id,
                        "thread_id": "source-disposition-thread",
                        "scope": f"gmail:{account_id}:source-disposition-thread",
                        "payload_a": "a" * 64,
                        "payload_b": "b" * 64,
                        "fingerprint": "c" * 64,
                        "instance_digest": "d" * 64,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extracted_obligations "
                        "(id, receipt_id, extraction_attempt_id, action_key, "
                        "schema_version, title, obligation_fingerprint, "
                        "taxonomy_fallback, "
                        "identity_instance_digest, "
                        "reconciliation_material_hash, "
                        "reconciled_suggestion_id) VALUES (:id, :receipt_id, "
                        ":attempt_id, 'source-disposition-action', "
                        "'gmail-task-v1', 'Source disposition obligation', "
                        ":fingerprint, false, :instance_digest, :material_hash, "
                        ":suggestion_id)"
                    ),
                    {
                        "id": obligation_id,
                        "receipt_id": receipt_id,
                        "attempt_id": attempt_id,
                        "fingerprint": "c" * 64,
                        "instance_digest": "d" * 64,
                        "material_hash": "e" * 64,
                        "suggestion_id": suggestion_a,
                    },
                )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestion_sources "
                            "(suggestion_id, obligation_id, receipt_id, "
                            "gmail_account_id, gmail_thread_id, direction, "
                            "source_label) VALUES (:suggestion_id, "
                            ":obligation_id, :receipt_id, :account_id, "
                            "'source-disposition-thread', 'received', "
                            "'Cross-wired same-scope source')"
                        ),
                        {
                            "suggestion_id": suggestion_b,
                            "obligation_id": obligation_id,
                            "receipt_id": receipt_id,
                            "account_id": account_id,
                        },
                    )

            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestion_sources "
                        "(suggestion_id, obligation_id, receipt_id, "
                        "gmail_account_id, gmail_thread_id, direction, "
                        "source_label) VALUES (:suggestion_id, :obligation_id, "
                        ":receipt_id, :account_id, "
                        "'source-disposition-thread', 'received', "
                        "'Correctly bound source')"
                    ),
                    {
                        "suggestion_id": suggestion_a,
                        "obligation_id": obligation_id,
                        "receipt_id": receipt_id,
                        "account_id": account_id,
                    },
                )
                assert (
                    connection.scalar(
                        sa.text(
                            "SELECT suggestion_id FROM crm_task_suggestion_sources "
                            "WHERE obligation_id = :obligation_id"
                        ),
                        {"obligation_id": obligation_id},
                    )
                    == suggestion_a
                )
    finally:
        engine.dispose()


def test_suppression_identity_is_immutable_but_redismissal_fields_remain_mutable() -> (
    None
):
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            suppression_id = UUID("00000000-0000-4000-8000-0000000083e1")
            with engine.begin() as connection:
                admin_id = connection.scalar(
                    sa.text(
                        "INSERT INTO admin_users (email, hashed_password) "
                        "VALUES ('immutable-suppression@example.test', "
                        "'test-only') RETURNING id"
                    )
                )
                audit_id = connection.scalar(
                    sa.text(
                        "INSERT INTO agent_action_audits "
                        "(actor, action_id, method, path, status_code, allowed, "
                        "request_meta, response_meta) VALUES "
                        "('admin', 'suggestion.dismiss', 'POST', '/test', 200, "
                        "true, '{}', '{}') RETURNING id"
                    )
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestion_suppressions "
                        "(id, source_type, source_scope_key, source_action_key, "
                        "obligation_fingerprint, identity_instance_digest, "
                        "dismissal_reason, dismissed_by_admin_id, "
                        "dismissal_audit_id) VALUES (:id, 'gmail_message', "
                        "'gmail:immutable:thread', 'action-v1:immutable', "
                        ":fingerprint, :instance_digest, 'Handled', :admin_id, "
                        ":audit_id)"
                    ),
                    {
                        "id": suppression_id,
                        "fingerprint": "a" * 64,
                        "instance_digest": "b" * 64,
                        "admin_id": admin_id,
                        "audit_id": audit_id,
                    },
                )

            for mutation in (
                "UPDATE crm_task_suggestion_suppressions SET "
                "identity_instance_digest = :replacement WHERE id = :id",
                "UPDATE crm_task_suggestion_suppressions SET "
                "source_action_key = 'action-v1:rewritten' WHERE id = :id",
                "DELETE FROM crm_task_suggestion_suppressions WHERE id = :id",
            ):
                with pytest.raises(sa.exc.DBAPIError) as raised:
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(mutation),
                            {
                                "id": suppression_id,
                                "replacement": "c" * 64,
                            },
                        )
                assert "gmail_task_intake_suppression_identity_immutable" in str(
                    raised.value.orig
                )

            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE crm_task_suggestion_suppressions SET "
                        "dismissal_reason = 'Dismissed again under audited "
                        "authority' WHERE id = :id"
                    ),
                    {"id": suppression_id},
                )
                assert (
                    connection.scalar(
                        sa.text(
                            "SELECT dismissal_reason FROM "
                            "crm_task_suggestion_suppressions WHERE id = :id"
                        ),
                        {"id": suppression_id},
                    )
                    == "Dismissed again under audited authority"
                )
    finally:
        engine.dispose()


def test_instance_digest_and_disposition_shapes_fail_closed_on_postgresql() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            account_id = UUID("00000000-0000-4000-8000-0000000083d1")
            receipt_id = UUID("00000000-0000-4000-8000-0000000083d2")
            attempt_id = UUID("00000000-0000-4000-8000-0000000083d3")
            suggestion_id = UUID("00000000-0000-4000-8000-0000000083d4")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'instance-shape@example.test')"
                    ),
                    {"id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_message_receipts "
                        "(id, account_id, gmail_message_id, gmail_thread_id, "
                        "direction, message_at, processing_state, "
                        "classification) VALUES (:id, :account_id, "
                        "'instance-shape-message', 'instance-shape-thread', "
                        "'received', CURRENT_TIMESTAMP, 'processed', 'eligible')"
                    ),
                    {"id": receipt_id, "account_id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extraction_attempts "
                        "(id, receipt_id, schema_version, attempt_number, "
                        "state, completed_at) VALUES (:id, :receipt_id, "
                        "'gmail-task-v1', 1, 'succeeded', CURRENT_TIMESTAMP)"
                    ),
                    {"id": attempt_id, "receipt_id": receipt_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, title, "
                        "payload_hash, model_schema_version, "
                        "obligation_fingerprint, primary_instance_digest) "
                        "VALUES (:id, :account_id, 'instance-shape-thread', "
                        "'gmail_message', :scope, 'instance-shape-action', "
                        "'Instance shape', :payload_hash, 'gmail-task-v1', "
                        ":fingerprint, :instance_digest)"
                    ),
                    {
                        "id": suggestion_id,
                        "account_id": account_id,
                        "scope": f"gmail:{account_id}:instance-shape-thread",
                        "payload_hash": "a" * 64,
                        "fingerprint": "b" * 64,
                        "instance_digest": "c" * 64,
                    },
                )
                admin_id = connection.scalar(
                    sa.text(
                        "INSERT INTO admin_users (email, hashed_password) "
                        "VALUES ('instance-admin@example.test', 'test-only') "
                        "RETURNING id"
                    )
                )
                audit_id = connection.scalar(
                    sa.text(
                        "INSERT INTO agent_action_audits "
                        "(actor, action_id, method, path, status_code, allowed, "
                        "request_meta, response_meta) VALUES "
                        "('admin', 'suggestion.dismiss', 'POST', '/test', 200, "
                        "true, '{}', '{}') RETURNING id"
                    )
                )
                suppression_id = connection.scalar(
                    sa.text(
                        "INSERT INTO crm_task_suggestion_suppressions "
                        "(source_type, source_scope_key, source_action_key, "
                        "obligation_fingerprint, identity_instance_digest, "
                        "dismissal_reason, dismissed_by_admin_id, "
                        "dismissal_audit_id) VALUES ('gmail_message', :scope, "
                        "'instance-shape-action', :fingerprint, "
                        ":instance_digest, 'Handled', :admin_id, :audit_id) "
                        "RETURNING id"
                    ),
                    {
                        "scope": f"gmail:{account_id}:instance-shape-thread",
                        "fingerprint": "b" * 64,
                        "instance_digest": "c" * 64,
                        "admin_id": admin_id,
                        "audit_id": audit_id,
                    },
                )

            invalid_suggestions = (None, "C" * 64, "c" * 63)
            for index, digest in enumerate(invalid_suggestions, start=1):
                with pytest.raises(sa.exc.IntegrityError):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "INSERT INTO crm_task_suggestions "
                                "(gmail_account_id, gmail_thread_id, source_type, "
                                "source_scope_key, source_action_key, title, "
                                "payload_hash, model_schema_version, "
                                "obligation_fingerprint, "
                                "primary_instance_digest) VALUES "
                                "(:account_id, 'instance-shape-thread', "
                                "'gmail_message', :scope, :action, :title, "
                                ":payload_hash, 'gmail-task-v1', :fingerprint, "
                                ":instance_digest)"
                            ),
                            {
                                "account_id": account_id,
                                "scope": f"gmail:{account_id}:instance-shape-thread",
                                "action": f"invalid-suggestion-{index}",
                                "title": f"Invalid suggestion {index}",
                                "payload_hash": f"{index}" * 64,
                                "fingerprint": "d" * 64,
                                "instance_digest": digest,
                            },
                        )

            invalid_obligations = (
                ("c" * 64, "d" * 64, None, None),
                ("c" * 64, "d" * 64, suggestion_id, suppression_id),
                ("C" * 64, "d" * 64, suggestion_id, None),
                ("c" * 64, "D" * 64, suggestion_id, None),
            )
            for index, (
                digest,
                material_hash,
                reconciled_suggestion_id,
                reconciled_suppression_id,
            ) in enumerate(invalid_obligations, start=1):
                with pytest.raises(sa.exc.IntegrityError):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "INSERT INTO gmail_extracted_obligations "
                                "(receipt_id, extraction_attempt_id, action_key, "
                                "schema_version, title, obligation_fingerprint, "
                                "taxonomy_fallback, "
                                "identity_instance_digest, "
                                "reconciliation_material_hash, "
                                "reconciled_suggestion_id, "
                                "reconciled_suppression_id) VALUES "
                                "(:receipt_id, :attempt_id, :action, "
                                "'gmail-task-v1', :title, :fingerprint, "
                                "false, :instance_digest, :material_hash, "
                                ":suggestion_id, "
                                ":suppression_id)"
                            ),
                            {
                                "receipt_id": receipt_id,
                                "attempt_id": attempt_id,
                                "action": f"invalid-obligation-{index}",
                                "title": f"Invalid obligation {index}",
                                "fingerprint": "e" * 64,
                                "instance_digest": digest,
                                "material_hash": material_hash,
                                "suggestion_id": reconciled_suggestion_id,
                                "suppression_id": reconciled_suppression_id,
                            },
                        )
    finally:
        engine.dispose()


def test_gmail_thread_candidate_limit_uses_generic_plan_safe_ordered_index() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            account_id = UUID("00000000-0000-4000-8000-0000000083b1")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'candidate-index@example.test')"
                    ),
                    {"id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, title, payload_hash, "
                        "model_schema_version, obligation_fingerprint, "
                        "primary_instance_digest, created_at) "
                        "SELECT gen_random_uuid(), :account_id, 'thread-indexed', "
                        "'gmail_message', 'gmail:candidate-index:thread-indexed', "
                        "'action-' || value::text, 'Candidate ' || value::text, "
                        "md5(value::text) || md5(value::text), 'gmail-task-v1', "
                        "md5((value + 1000)::text) || md5((value + 1000)::text), "
                        "repeat('f', 64), "
                        "TIMESTAMPTZ '2026-08-21T00:00:00Z' + "
                        "value * INTERVAL '1 second' FROM generate_series(1, 256) "
                        "AS value"
                    ),
                    {"account_id": account_id},
                )
                connection.execute(sa.text("ANALYZE crm_task_suggestions"))
                connection.execute(sa.text("SET LOCAL enable_seqscan = off"))
                connection.execute(
                    sa.text("SET LOCAL plan_cache_mode = force_generic_plan")
                )
                connection.execute(
                    sa.text(
                        "PREPARE gmail_thread_candidates "
                        "(text, uuid, text, integer) AS SELECT id FROM "
                        "crm_task_suggestions WHERE source_type = $1 AND "
                        "gmail_account_id = $2 AND gmail_thread_id = $3 "
                        "ORDER BY created_at, id LIMIT $4 FOR UPDATE"
                    )
                )
                plan_rows = connection.execute(
                    sa.text(
                        "EXPLAIN (COSTS OFF) EXECUTE gmail_thread_candidates "
                        "('gmail_message', "
                        "'00000000-0000-4000-8000-0000000083b1', "
                        "'thread-indexed', 11)"
                    )
                ).all()
                connection.execute(sa.text("DEALLOCATE gmail_thread_candidates"))
            plan = "\n".join(str(row[0]) for row in plan_rows)
            assert "ix_crm_task_suggestions_gmail_thread_order" in plan
            assert "Sort" not in plan
    finally:
        engine.dispose()


def test_instance_material_membership_uses_bounded_generic_index_probe() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            account_id = UUID("00000000-0000-4000-8000-0000000083e1")
            receipt_id = UUID("00000000-0000-4000-8000-0000000083e2")
            attempt_id = UUID("00000000-0000-4000-8000-0000000083e3")
            suggestion_id = UUID("00000000-0000-4000-8000-0000000083e4")
            instance_digest = "c" * 64
            material_hash = "d" * 64
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'membership-index@example.test')"
                    ),
                    {"id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_message_receipts "
                        "(id, account_id, gmail_message_id, gmail_thread_id, "
                        "direction, message_at, processing_state, "
                        "classification) VALUES (:id, :account_id, "
                        "'membership-index-message', 'membership-index-thread', "
                        "'received', CURRENT_TIMESTAMP, 'processed', 'eligible')"
                    ),
                    {"id": receipt_id, "account_id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extraction_attempts "
                        "(id, receipt_id, schema_version, attempt_number, "
                        "state, completed_at) VALUES (:id, :receipt_id, "
                        "'gmail-task-v1', 1, 'succeeded', CURRENT_TIMESTAMP)"
                    ),
                    {"id": attempt_id, "receipt_id": receipt_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, title, payload_hash, "
                        "model_schema_version, obligation_fingerprint, "
                        "primary_instance_digest) VALUES (:id, :account_id, "
                        "'membership-index-thread', 'gmail_message', :scope, "
                        "'membership-index-action', 'Membership index', "
                        ":payload_hash, 'gmail-task-v1', :fingerprint, "
                        ":instance_digest)"
                    ),
                    {
                        "id": suggestion_id,
                        "account_id": account_id,
                        "scope": f"gmail:{account_id}:membership-index-thread",
                        "payload_hash": "a" * 64,
                        "fingerprint": "b" * 64,
                        "instance_digest": instance_digest,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, title, "
                        "payload_hash, model_schema_version, "
                        "obligation_fingerprint, primary_instance_digest) "
                        "SELECT :account_id, 'membership-unrelated-' || "
                        "value::text, 'gmail_message', "
                        "'gmail:membership-unrelated:' || value::text, "
                        "'membership-unrelated-' || value::text, "
                        "'Membership unrelated ' || value::text, "
                        "md5(value::text) || md5(value::text), "
                        "'gmail-task-v1', md5((value + 2048)::text) || "
                        "md5((value + 2048)::text), repeat('e', 64) "
                        "FROM generate_series(1, 2048) AS value"
                    ),
                    {"account_id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extracted_obligations "
                        "(receipt_id, extraction_attempt_id, action_key, "
                        "schema_version, title, obligation_fingerprint, "
                        "taxonomy_fallback, "
                        "identity_instance_digest, "
                        "reconciliation_material_hash, "
                        "reconciled_suggestion_id) SELECT :receipt_id, "
                        ":attempt_id, 'membership-' || value::text, "
                        "'gmail-task-v1', 'Membership ' || value::text, "
                        ":fingerprint, false, CASE WHEN value = 1 THEN "
                        ":instance_digest ELSE md5(value::text) || "
                        "md5(value::text) END, CASE WHEN value = 1 THEN "
                        ":material_hash ELSE md5((value + 1000)::text) || "
                        "md5((value + 1000)::text) END, "
                        ":suggestion_id FROM generate_series(1, 256) AS value"
                    ),
                    {
                        "receipt_id": receipt_id,
                        "attempt_id": attempt_id,
                        "fingerprint": "b" * 64,
                        "instance_digest": instance_digest,
                        "material_hash": material_hash,
                        "suggestion_id": suggestion_id,
                    },
                )
                connection.execute(sa.text("ANALYZE gmail_extracted_obligations"))
                connection.execute(sa.text("SET LOCAL enable_seqscan = off"))
                connection.execute(
                    sa.text("SET LOCAL plan_cache_mode = force_generic_plan")
                )
                connection.execute(
                    sa.text(
                        "PREPARE gmail_instance_material_membership "
                        "(uuid, varchar, varchar) AS SELECT EXISTS "
                        "(SELECT id FROM gmail_extracted_obligations WHERE "
                        "reconciled_suggestion_id = $1 AND "
                        "identity_instance_digest = $2 AND "
                        "reconciliation_material_hash = $3 LIMIT 1)"
                    )
                )
                connection.execute(
                    sa.text(
                        "PREPARE gmail_instance_candidate_membership "
                        "(uuid[], varchar) AS SELECT "
                        "candidate_ids.suggestion_id FROM unnest($1) AS "
                        "candidate_ids(suggestion_id) WHERE EXISTS "
                        "(SELECT id FROM gmail_extracted_obligations WHERE "
                        "reconciled_suggestion_id = "
                        "candidate_ids.suggestion_id AND "
                        "identity_instance_digest = $2)"
                    )
                )
                plan_rows = connection.execute(
                    sa.text(
                        "EXPLAIN (ANALYZE, COSTS OFF) EXECUTE "
                        "gmail_instance_material_membership "
                        "('00000000-0000-4000-8000-0000000083e4', "
                        ":instance_digest, :material_hash)"
                    ),
                    {
                        "instance_digest": instance_digest,
                        "material_hash": material_hash,
                    },
                ).all()
                candidate_plan_rows = connection.execute(
                    sa.text(
                        "EXPLAIN (ANALYZE, COSTS OFF) EXECUTE "
                        "gmail_instance_candidate_membership "
                        "(ARRAY['00000000-0000-4000-8000-0000000083e4'::uuid], "
                        ":instance_digest)"
                    ),
                    {"instance_digest": instance_digest},
                ).all()
                connection.execute(
                    sa.text("DEALLOCATE gmail_instance_material_membership")
                )
                connection.execute(
                    sa.text("DEALLOCATE gmail_instance_candidate_membership")
                )
            plan = "\n".join(str(row[0]) for row in plan_rows)
            assert "ix_gmail_extracted_obligations_suggestion_instance" in plan
            assert "Seq Scan on gmail_extracted_obligations" not in plan
            index_lines = [
                line
                for line in plan.splitlines()
                if "ix_gmail_extracted_obligations_suggestion_instance" in line
            ]
            assert len(index_lines) == 1
            assert "rows=1 loops=1" in index_lines[0]
            candidate_plan = "\n".join(str(row[0]) for row in candidate_plan_rows)
            assert (
                "ix_gmail_extracted_obligations_suggestion_instance" in candidate_plan
            )
            assert "Seq Scan on gmail_extracted_obligations" not in (candidate_plan)
            assert "Seq Scan on crm_task_suggestions" not in candidate_plan
            assert "Function Scan on unnest candidate_ids" in candidate_plan
            candidate_index_line = next(
                line
                for line in candidate_plan.splitlines()
                if "ix_gmail_extracted_obligations_suggestion_instance" in line
            )
            assert "rows=1 loops=1" in candidate_index_line
    finally:
        engine.dispose()


def test_obligation_authority_queries_use_bounded_generic_index_probes() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            account_id = UUID("00000000-0000-4000-8000-0000000083f1")
            receipt_id = UUID("00000000-0000-4000-8000-0000000083f2")
            attempt_id = UUID("00000000-0000-4000-8000-0000000083f3")
            suggestion_id = UUID("00000000-0000-4000-8000-0000000083f4")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'authority-index@example.test')"
                    ),
                    {"id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_message_receipts "
                        "(id, account_id, gmail_message_id, gmail_thread_id, "
                        "direction, message_at, processing_state, "
                        "classification) VALUES (:id, :account_id, "
                        "'authority-index-message', 'authority-index-thread', "
                        "'received', CURRENT_TIMESTAMP, 'processed', 'eligible')"
                    ),
                    {"id": receipt_id, "account_id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extraction_attempts "
                        "(id, receipt_id, schema_version, attempt_number, "
                        "state, completed_at) VALUES (:id, :receipt_id, "
                        "'gmail-task-v1', 1, 'succeeded', CURRENT_TIMESTAMP)"
                    ),
                    {"id": attempt_id, "receipt_id": receipt_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, title, payload_hash, "
                        "model_schema_version, obligation_fingerprint, "
                        "primary_instance_digest) VALUES (:id, :account_id, "
                        "'authority-index-thread', 'gmail_message', :scope, "
                        "'authority-index-action', 'Authority index', "
                        ":payload_hash, 'gmail-task-v1', :fingerprint, "
                        ":instance_digest)"
                    ),
                    {
                        "id": suggestion_id,
                        "account_id": account_id,
                        "scope": f"gmail:{account_id}:authority-index-thread",
                        "payload_hash": "a" * 64,
                        "fingerprint": "b" * 64,
                        "instance_digest": "c" * 64,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, title, "
                        "payload_hash, model_schema_version, "
                        "obligation_fingerprint, primary_instance_digest) "
                        "SELECT :account_id, 'unrelated-' || value::text, "
                        "'gmail_message', 'gmail:unrelated:' || value::text, "
                        "'unrelated-' || value::text, "
                        "'Unrelated ' || value::text, "
                        "md5(value::text) || md5(value::text), "
                        "'gmail-task-v1', md5((value + 4096)::text) || "
                        "md5((value + 4096)::text), repeat('e', 64) "
                        "FROM generate_series(1, 2048) AS value"
                    ),
                    {"account_id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extracted_obligations "
                        "(receipt_id, extraction_attempt_id, action_key, "
                        "schema_version, title, contact_hint, "
                        "taxonomy_fallback, obligation_fingerprint, "
                        "identity_instance_digest, "
                        "reconciliation_material_hash, "
                        "reconciled_suggestion_id) SELECT :receipt_id, "
                        ":attempt_id, 'authority-' || value::text, "
                        "'gmail-task-v1', 'Authority ' || value::text, "
                        "'client-' || lpad(value::text, 4, '0') || "
                        "'@example.test', value = 2048, :fingerprint, "
                        ":instance_digest, :material_hash, :suggestion_id "
                        "FROM generate_series(1, 2048) AS value"
                    ),
                    {
                        "receipt_id": receipt_id,
                        "attempt_id": attempt_id,
                        "fingerprint": "b" * 64,
                        "instance_digest": "c" * 64,
                        "material_hash": "d" * 64,
                        "suggestion_id": suggestion_id,
                    },
                )
                connection.execute(sa.text("ANALYZE gmail_extracted_obligations"))
                connection.execute(sa.text("SET LOCAL enable_seqscan = off"))
                connection.execute(
                    sa.text("SET LOCAL plan_cache_mode = force_generic_plan")
                )
                connection.execute(
                    sa.text(
                        "PREPARE gmail_taxonomy_fallback_authority "
                        "(uuid[]) AS SELECT "
                        "candidate_ids.suggestion_id FROM unnest($1) AS "
                        "candidate_ids(suggestion_id) WHERE EXISTS "
                        "(SELECT id FROM gmail_extracted_obligations WHERE "
                        "reconciled_suggestion_id = "
                        "candidate_ids.suggestion_id AND "
                        "taxonomy_fallback IS TRUE)"
                    )
                )
                connection.execute(
                    sa.text(
                        "PREPARE gmail_contact_hint_first (uuid) AS SELECT "
                        "contact_hint FROM gmail_extracted_obligations WHERE "
                        "reconciled_suggestion_id = $1 AND "
                        "contact_hint IS NOT NULL ORDER BY contact_hint ASC, "
                        "id ASC LIMIT 1"
                    )
                )
                connection.execute(
                    sa.text(
                        "PREPARE gmail_contact_hint_last (uuid) AS SELECT "
                        "contact_hint FROM gmail_extracted_obligations WHERE "
                        "reconciled_suggestion_id = $1 AND "
                        "contact_hint IS NOT NULL ORDER BY contact_hint DESC, "
                        "id DESC LIMIT 1"
                    )
                )
                taxonomy_plan = connection.execute(
                    sa.text(
                        "EXPLAIN (ANALYZE, COSTS OFF) EXECUTE "
                        "gmail_taxonomy_fallback_authority "
                        "(ARRAY['00000000-0000-4000-8000-0000000083f4'::uuid])"
                    )
                ).all()
                first_plan = connection.execute(
                    sa.text(
                        "EXPLAIN (ANALYZE, COSTS OFF) EXECUTE "
                        "gmail_contact_hint_first "
                        "('00000000-0000-4000-8000-0000000083f4')"
                    )
                ).all()
                last_plan = connection.execute(
                    sa.text(
                        "EXPLAIN (ANALYZE, COSTS OFF) EXECUTE "
                        "gmail_contact_hint_last "
                        "('00000000-0000-4000-8000-0000000083f4')"
                    )
                ).all()
                for prepared in (
                    "gmail_taxonomy_fallback_authority",
                    "gmail_contact_hint_first",
                    "gmail_contact_hint_last",
                ):
                    connection.execute(sa.text(f"DEALLOCATE {prepared}"))

            plans = (
                (
                    "\n".join(str(row[0]) for row in taxonomy_plan),
                    "ix_gmail_extracted_obligations_suggestion_taxonomy",
                ),
                (
                    "\n".join(str(row[0]) for row in first_plan),
                    "ix_gmail_extracted_obligations_suggestion_contact_hint",
                ),
                (
                    "\n".join(str(row[0]) for row in last_plan),
                    "ix_gmail_extracted_obligations_suggestion_contact_hint",
                ),
            )
            for plan, index_name in plans:
                assert index_name in plan
                assert "Seq Scan on gmail_extracted_obligations" not in plan
                assert "Seq Scan on crm_task_suggestions" not in plan
                index_lines = [line for line in plan.splitlines() if index_name in line]
                assert len(index_lines) == 1
                assert "rows=1 loops=1" in index_lines[0]
            assert "Function Scan on unnest candidate_ids" in plans[0][0]
            assert "rows=1 loops=1" in next(
                line
                for line in plans[0][0].splitlines()
                if "Function Scan on unnest candidate_ids" in line
            )
    finally:
        engine.dispose()


def test_succeeded_attempt_replay_uses_bounded_ordered_index() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            account_id = UUID("00000000-0000-4000-8000-000000008401")
            target_receipt_id = UUID("00000000-0000-4000-8000-000000008403")
            target_attempt_id = UUID("00000000-0000-4000-8000-000000008405")
            suggestion_id = UUID("00000000-0000-4000-8000-000000008406")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'attempt-replay-index@example.test')"
                    ),
                    {"id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_message_receipts "
                        "(id, account_id, gmail_message_id, gmail_thread_id, "
                        "direction, message_at, processing_state, "
                        "classification) VALUES (:target_id, :account_id, "
                        "'replay-target-message', "
                        "'replay-index-thread', 'received', CURRENT_TIMESTAMP, "
                        "'processed', 'eligible')"
                    ),
                    {
                        "target_id": target_receipt_id,
                        "account_id": account_id,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_message_receipts "
                        "(id, account_id, gmail_message_id, gmail_thread_id, "
                        "direction, message_at, processing_state, "
                        "classification) SELECT "
                        "md5('replay-receipt-' || value::text)::uuid, "
                        ":account_id, 'replay-unrelated-message-' || "
                        "value::text, 'replay-unrelated-thread-' || value::text, "
                        "'received', CURRENT_TIMESTAMP, 'processed', 'eligible' "
                        "FROM generate_series(1, 2048) AS value"
                    ),
                    {"account_id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extraction_attempts "
                        "(id, receipt_id, schema_version, attempt_number, "
                        "state, completed_at) VALUES (:target_id, "
                        ":target_receipt_id, 'gmail-task-v1', 1, "
                        "'succeeded', CURRENT_TIMESTAMP)"
                    ),
                    {
                        "target_id": target_attempt_id,
                        "target_receipt_id": target_receipt_id,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extraction_attempts "
                        "(id, receipt_id, schema_version, attempt_number, "
                        "state, completed_at) SELECT "
                        "md5('replay-attempt-' || value::text)::uuid, "
                        "md5('replay-receipt-' || value::text)::uuid, "
                        "'gmail-task-v1', 1, 'succeeded', CURRENT_TIMESTAMP "
                        "FROM generate_series(1, 2048) AS value"
                    )
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, source_action_key, title, payload_hash, "
                        "model_schema_version, obligation_fingerprint, "
                        "primary_instance_digest) VALUES (:id, :account_id, "
                        "'replay-index-thread', 'gmail_message', :scope, "
                        "'replay-index-action', 'Replay index', :payload_hash, "
                        "'gmail-task-v1', :fingerprint, :instance_digest)"
                    ),
                    {
                        "id": suggestion_id,
                        "account_id": account_id,
                        "scope": f"gmail:{account_id}:replay-index-thread",
                        "payload_hash": "a" * 64,
                        "fingerprint": "b" * 64,
                        "instance_digest": "c" * 64,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extracted_obligations "
                        "(receipt_id, extraction_attempt_id, action_key, "
                        "schema_version, title, taxonomy_fallback, "
                        "obligation_fingerprint, identity_instance_digest, "
                        "reconciliation_material_hash, "
                        "reconciled_suggestion_id) SELECT "
                        "md5('replay-receipt-' || value::text)::uuid, "
                        "md5('replay-attempt-' || value::text)::uuid, "
                        "'unrelated', 'gmail-task-v1', 'Replay unrelated ' || "
                        "value::text, false, :fingerprint, :instance_digest, "
                        ":material_hash, :suggestion_id "
                        "FROM generate_series(1, 2048) AS value"
                    ),
                    {
                        "fingerprint": "b" * 64,
                        "instance_digest": "c" * 64,
                        "material_hash": "d" * 64,
                        "suggestion_id": suggestion_id,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_extracted_obligations "
                        "(receipt_id, extraction_attempt_id, action_key, "
                        "schema_version, title, taxonomy_fallback, "
                        "obligation_fingerprint, identity_instance_digest, "
                        "reconciliation_material_hash, "
                        "reconciled_suggestion_id) SELECT :receipt_id, "
                        ":attempt_id, 'target-' || value::text, "
                        "'gmail-task-v1', 'Replay target ' || value::text, "
                        "false, :fingerprint, :instance_digest, :material_hash, "
                        ":suggestion_id FROM generate_series(1, 20) AS value"
                    ),
                    {
                        "receipt_id": target_receipt_id,
                        "attempt_id": target_attempt_id,
                        "fingerprint": "b" * 64,
                        "instance_digest": "c" * 64,
                        "material_hash": "d" * 64,
                        "suggestion_id": suggestion_id,
                    },
                )
                connection.execute(sa.text("ANALYZE gmail_extracted_obligations"))
                connection.execute(sa.text("SET LOCAL enable_seqscan = off"))
                connection.execute(
                    sa.text("SET LOCAL plan_cache_mode = force_generic_plan")
                )
                connection.execute(
                    sa.text(
                        "PREPARE gmail_succeeded_attempt_replay (uuid) AS "
                        "SELECT id FROM gmail_extracted_obligations WHERE "
                        "extraction_attempt_id = $1 ORDER BY created_at, id"
                    )
                )
                plan_rows = connection.execute(
                    sa.text(
                        "EXPLAIN (ANALYZE, COSTS OFF) EXECUTE "
                        "gmail_succeeded_attempt_replay "
                        "('00000000-0000-4000-8000-000000008405')"
                    )
                ).all()
                connection.execute(sa.text("DEALLOCATE gmail_succeeded_attempt_replay"))
            plan = "\n".join(str(row[0]) for row in plan_rows)
            assert "ix_gmail_extracted_obligations_attempt_replay" in plan
            assert "Seq Scan on gmail_extracted_obligations" not in plan
            assert "Sort" not in plan
            index_line = next(
                line
                for line in plan.splitlines()
                if "ix_gmail_extracted_obligations_attempt_replay" in line
            )
            assert "rows=20 loops=1" in index_line
    finally:
        engine.dispose()


def test_backfill_window_and_origin_versions_fail_closed_on_real_postgresql() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            account_id = UUID("00000000-0000-4000-8000-000000008331")
            other_account_id = UUID("00000000-0000-4000-8000-000000008333")
            other_run_id = UUID("00000000-0000-4000-8000-000000008334")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'window@example.test'), "
                        "(:other_id, 'other-window@example.test')"
                    ),
                    {"id": account_id, "other_id": other_account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_runs "
                        "(id, account_id, start_history_id, run_kind, state) "
                        "VALUES (:id, :account_id, 'history-1', 'backfill', "
                        "'completed')"
                    ),
                    {"id": other_run_id, "account_id": other_account_id},
                )
                admin_id = connection.scalar(
                    sa.text(
                        "INSERT INTO admin_users (email, hashed_password) "
                        "VALUES ('window-admin@example.test', 'test-only') "
                        "RETURNING id"
                    )
                )
                audit_id = connection.scalar(
                    sa.text(
                        "INSERT INTO agent_action_audits "
                        "(actor, action_id, method, path, status_code, allowed, "
                        "request_meta, response_meta) VALUES "
                        "('command_admin', 'gmail.backfill', 'POST', '/test', "
                        "202, true, '{}', '{}') RETURNING id"
                    )
                )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO gmail_backfill_requests "
                            "(account_id, administrator_id, reason, window_start, "
                            "window_end, expired_history_id, reseed_history_id, "
                            "audit_id, run_id) VALUES "
                            "(:account_id, :admin_id, 'Cross-account run', "
                            ":start, :end, 'old', 'new', :audit_id, :run_id)"
                        ),
                        {
                            "account_id": account_id,
                            "admin_id": admin_id,
                            "start": datetime(2026, 8, 1, tzinfo=timezone.utc),
                            "end": datetime(2026, 8, 2, tzinfo=timezone.utc),
                            "audit_id": audit_id,
                            "run_id": other_run_id,
                        },
                    )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO gmail_backfill_requests "
                            "(account_id, administrator_id, reason, window_start, "
                            "window_end, expired_history_id, reseed_history_id, "
                            "audit_id) VALUES "
                            "(:account_id, :admin_id, 'Too broad', :start, :end, "
                            "'old', 'new', :audit_id)"
                        ),
                        {
                            "account_id": account_id,
                            "admin_id": admin_id,
                            "start": datetime(2026, 8, 1, tzinfo=timezone.utc),
                            "end": datetime(2026, 8, 9, tzinfo=timezone.utc),
                            "audit_id": audit_id,
                        },
                    )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO gmail_message_origins "
                            "(account_id, request_id, canonical_send_hash, "
                            "canonical_envelope_hash, canonical_body_hash, "
                            "origin_kind, delivery_state, action_audit_id, version) "
                            "VALUES (:account_id, :request_id, :send_hash, "
                            ":envelope_hash, :body_hash, 'sydney_client_send', "
                            "'sending', :audit_id, 0)"
                        ),
                        {
                            "account_id": account_id,
                            "request_id": UUID("00000000-0000-4000-8000-000000008332"),
                            "send_hash": "1" * 64,
                            "envelope_hash": "2" * 64,
                            "body_hash": "3" * 64,
                            "audit_id": audit_id,
                        },
                    )
    finally:
        engine.dispose()


def test_missing_message_ack_shape_fails_closed_on_real_postgresql() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            account_id = UUID("00000000-0000-4000-8000-000000008341")
            run_id = UUID("00000000-0000-4000-8000-000000008342")
            now = datetime(2026, 8, 20, tzinfo=timezone.utc)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_accounts (id, workspace_email) "
                        "VALUES (:id, 'incident-shape@example.test')"
                    ),
                    {"id": account_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_sync_runs "
                        "(id, account_id, start_history_id, run_kind, state) "
                        "VALUES (:id, :account_id, '8300', 'poll', 'failed')"
                    ),
                    {"id": run_id, "account_id": account_id},
                )
                admin_id = connection.scalar(
                    sa.text(
                        "INSERT INTO admin_users (email, hashed_password) "
                        "VALUES ('incident-shape-admin@example.test', "
                        "'test-only') RETURNING id"
                    )
                )
                audit_id = connection.scalar(
                    sa.text(
                        "INSERT INTO agent_action_audits "
                        "(actor, action_id, method, path, status_code, allowed, "
                        "request_meta, response_meta) VALUES "
                        "('command_admin', 'gmail.missing.ack', 'POST', "
                        "'/test', 200, true, '{}', '{}') RETURNING id"
                    )
                )

            invalid_shapes = (
                ("", "sent", now),
                ("   ", "sent", now),
                (" padded reason ", "sent", now),
                ("Canonical reason", "pending", None),
            )
            for index, (reason, alert_state, alerted_at) in enumerate(
                invalid_shapes,
                start=1,
            ):
                with pytest.raises(sa.exc.IntegrityError):
                    with engine.begin() as connection:
                        connection.execute(
                            sa.text(
                                "INSERT INTO gmail_missing_message_incidents "
                                "(account_id, run_id, gmail_message_id, "
                                "gmail_thread_id, start_history_id, page_number, "
                                "state, alert_state, alerted_at, "
                                "acknowledged_by_admin_id, acknowledgement_reason, "
                                "action_audit_id, acknowledged_at) VALUES "
                                "(:account_id, :run_id, :message_id, "
                                "'incident-thread', '8300', :page_number, "
                                "'acknowledged', :alert_state, :alerted_at, "
                                ":admin_id, :reason, :audit_id, :now)"
                            ),
                            {
                                "account_id": account_id,
                                "run_id": run_id,
                                "message_id": f"invalid-incident-{index}",
                                "page_number": index,
                                "alert_state": alert_state,
                                "alerted_at": alerted_at,
                                "admin_id": admin_id,
                                "reason": reason,
                                "audit_id": audit_id,
                                "now": now,
                            },
                        )

            valid_id = UUID("00000000-0000-4000-8000-000000008343")
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO gmail_missing_message_incidents "
                        "(id, account_id, run_id, gmail_message_id, "
                        "gmail_thread_id, start_history_id, page_number, state, "
                        "alert_state, alerted_at, acknowledged_by_admin_id, "
                        "acknowledgement_reason, action_audit_id, "
                        "acknowledged_at) VALUES "
                        "(:id, :account_id, :run_id, 'valid-incident', "
                        "'incident-thread', '8300', 5, 'acknowledged', 'sent', "
                        ":now, :admin_id, 'Canonical reason', :audit_id, :now)"
                    ),
                    {
                        "id": valid_id,
                        "account_id": account_id,
                        "run_id": run_id,
                        "now": now,
                        "admin_id": admin_id,
                        "audit_id": audit_id,
                    },
                )
                assert (
                    connection.scalar(
                        sa.text(
                            "SELECT acknowledgement_reason FROM "
                            "gmail_missing_message_incidents WHERE id = :id"
                        ),
                        {"id": valid_id},
                    )
                    == "Canonical reason"
                )
    finally:
        engine.dispose()


def test_task2_is_included_once_before_task5_in_the_dedicated_workflow() -> None:
    workflow = (
        _backend_root().parent
        / ".github"
        / "workflows"
        / "gmail-sydney-task-intake.yml"
    ).read_text(encoding="utf-8")
    assert workflow.count("tests/test_gmail_task_intake_migration.py") == 1
    step_name = "name: Run the Task 1 through Task 9 persistence, concurrency, and E2E contracts"
    assert step_name in workflow
    command = workflow.split(step_name, 1)[1].split("- name:", 1)[0]
    assert command.index("tests/test_gmail_task_intake_migration.py") < command.index(
        "tests/test_gmail_history_adapter.py"
    )
    assert command.index("tests/test_gmail_history_adapter.py") < command.index(
        "tests/test_gmail_task_extractor.py"
    )
    assert command.index("tests/test_gmail_task_extractor.py") < command.index(
        "tests/test_crm_task_suggestions.py"
    )
    assert command.index("tests/test_crm_task_suggestions.py") < command.index(
        "tests/test_sydney_task_review_migration.py"
    )


def test_task7_frontend_contract_is_pinned_in_the_dedicated_workflow() -> None:
    workflow = (
        _backend_root().parent
        / ".github"
        / "workflows"
        / "gmail-sydney-task-intake.yml"
    ).read_text(encoding="utf-8")
    assert workflow.count("task7-command-review:") == 1
    job = workflow.split("task7-command-review:", 1)[1]
    assert 'node-version: "22"' in job
    assert "working-directory: frontend" in job
    assert "npm ci" in job
    assert "npm run typecheck" in job
    assert job.count("src/lib/command/task-suggestions.test.ts") == 2
    assert job.count("src/components/command/TaskSuggestionsWorkspace.test.tsx") == 2
    assert job.count("src/components/command/shell/commandNavigation.test.ts") == 2
    assert job.count("src/components/command/shell/CommandShell.test.tsx") == 2
    lint_step = job.split("name: Lint only the Task 7 frontend scope", 1)[1]
    for path in (
        "src/instrumentation-client.ts",
        "src/proxy.ts",
        "src/app/admin/layout.tsx",
        "src/app/admin/command/task-suggestions/page.tsx",
        "src/app/admin/login/page.tsx",
        "src/lib/command/task-suggestion-handoff.ts",
        "src/lib/command/task-suggestions.ts",
        "src/lib/command/task-suggestions.test.ts",
        "src/components/command/TaskSuggestionsWorkspace.tsx",
        "src/components/command/TaskSuggestionsWorkspace.test.tsx",
        "src/components/command/shell/commandNavigation.ts",
        "src/components/command/shell/commandNavigation.test.ts",
        "src/components/command/shell/CommandShell.test.tsx",
    ):
        assert lint_step.count(path) == 1
