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
    "gmail_message_receipts",
    "gmail_message_origins",
    "gmail_extraction_attempts",
    "gmail_extracted_obligations",
    "crm_task_suggestions",
    "crm_task_suggestion_sources",
    "crm_task_suggestion_suppressions",
    "gmail_backfill_requests",
)

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
    },
    "crm_task_suggestion_sources": set(),
    "crm_task_suggestion_suppressions": {
        "reprocess_override_at",
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
        "uuid": ("id", "receipt_id", "extraction_attempt_id"),
        "text": ("description", "evaluator_result_json"),
        "numeric_5_4": ("confidence",),
        "datetime": ("due_at", "created_at"),
        "strings": {
            128: ("action_key", "requested_owner"),
            64: (
                "schema_version",
                "timezone_basis",
                "requested_link_type",
                "obligation_fingerprint",
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
        "datetime": ("due_at", "created_at", "updated_at"),
        "strings": {
            255: ("gmail_thread_id", "title"),
            32: ("priority", "task_status", "state", "clarification_state"),
            64: (
                "source_type",
                "payload_hash",
                "model_schema_version",
                "obligation_fingerprint",
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
        "datetime": ("dismissed_at", "reprocess_override_at"),
        "strings": {
            64: ("source_type", "obligation_fingerprint"),
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
            f"{binary_group.group(1)} {binary_group.group(2)} "
            f"{binary_group.group(3)}"
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
            _normalized_sql(
                index.get("dialect_options", {}).get("postgresql_where")
            ),
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
) -> None:
    inspector = sa.inspect(connection)
    assert set(TABLES).issubset(inspector.get_table_names())
    for table_name, model_table in tables.items():
        inspected_columns = inspector.get_columns(table_name)
        assert tuple(column["name"] for column in inspected_columns) == tuple(
            model_table.columns.keys()
        )
        assert {
            column["name"] for column in inspected_columns if column["nullable"]
        } == NULLABLE_COLUMNS[table_name]
        assert {
            column["name"]: _type_signature(column["type"])
            for column in inspected_columns
        } == _expected_type_signatures(table_name)
        assert {
            column["name"]: _canonical_default(column["default"])
            for column in inspected_columns
            if column["default"] is not None
        } == EXPECTED_SERVER_DEFAULTS[table_name]
        primary_key = inspector.get_pk_constraint(table_name)
        assert primary_key["constrained_columns"] == ["id"]
        assert primary_key["name"] == f"{table_name}_pkey"
        assert _inspector_unique_contract(
            inspector, table_name
        ) == _named_unique_columns(model_table)
        assert _inspector_foreign_key_contract(
            inspector, table_name
        ) == EXPECTED_FOREIGN_KEYS[table_name]
        assert _inspector_check_contract(inspector, table_name) == {
            name: _normalized_check_sql(sqltext)
            for name, sqltext in _named_checks(model_table).items()
        }
        assert _inspector_index_contract(
            inspector, table_name
        ) == _model_index_contract(model_table)


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
            "INSERT INTO gmail_extracted_obligations "
            "(id, receipt_id, extraction_attempt_id, action_key, "
            "schema_version, title, obligation_fingerprint) VALUES "
            "(:id, :receipt_id, :attempt_id, 'guard-action', "
            "'gmail-task-v1', 'Guard obligation', :fingerprint)"
        ),
        {
            "id": ids["gmail_extracted_obligations"],
            "receipt_id": ids["gmail_message_receipts"],
            "attempt_id": ids["gmail_extraction_attempts"],
            "fingerprint": "c" * 64,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO crm_task_suggestions "
            "(id, gmail_account_id, gmail_thread_id, source_type, source_scope_key, "
            "source_action_key, title, payload_hash, model_schema_version, "
            "obligation_fingerprint) VALUES "
            "(:id, :account_id, 'thread-guard', 'gmail_message', "
            "'gmail:guard-account:thread-guard', 'guard-action', "
            "'Guard suggestion', :payload_hash, "
            "'gmail-task-v1', :fingerprint)"
        ),
        {
            "id": ids["crm_task_suggestions"],
            "account_id": ids["gmail_sync_accounts"],
            "payload_hash": "d" * 64,
            "fingerprint": "c" * 64,
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
            "obligation_fingerprint, dismissal_reason, dismissed_by_admin_id, "
            "dismissal_audit_id) VALUES "
            "(:id, 'gmail_message', 'account:thread-guard', 'guard-action', "
            ":fingerprint, 'Guard suppression', :admin_id, :audit_id)"
        ),
        {
            "id": ids["crm_task_suggestion_suppressions"],
            "fingerprint": "c" * 64,
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


def test_revision_83_is_the_sole_serial_head_after_revision_82() -> None:
    revision = _load_revision()
    assert revision.revision == REVISION
    assert revision.down_revision == DOWN_REVISION
    assert revision.branch_labels is None
    assert revision.depends_on is None
    scripts = _script_directory()
    assert scripts.get_heads() == [REVISION]
    assert scripts.get_revision(REVISION).down_revision == DOWN_REVISION


def test_all_eleven_models_have_exact_columns_defaults_and_no_raw_secrets() -> None:
    tables = _model_tables()
    assert tuple(tables) == TABLES
    assert {
        table.name for table in tables.values()
    } == set(TABLES)

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
            "obligation_fingerprint",
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
            "payload_hash",
            "application_idempotency_key",
            "applied_task_id",
            "model_schema_version",
            "obligation_fingerprint",
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
            "dismissal_reason",
            "dismissed_by_admin_id",
            "dismissal_audit_id",
            "dismissed_at",
            "reprocess_override_at",
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
            column.name: _type_signature(column.type)
            for column in tables[name].columns
        } == expected_types
        assert {
            column.name: _canonical_default(
                None
                if column.server_default is None
                else column.server_default.arg
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
    assert str(suggestion.columns["clarification_state"].server_default.arg) == "not_required"
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
    }
    assert _named_unique_columns(tables["crm_task_suggestions"]) == {
        "uq_crm_task_suggestions_application_key": (
            "application_idempotency_key",
        ),
        "uq_crm_task_suggestions_source_request": (
            "source_request_id",
        ),
        "uq_crm_task_suggestions_gmail_identity": (
            "id",
            "gmail_account_id",
            "gmail_thread_id",
        ),
    }
    assert _named_unique_columns(tables["crm_task_suggestion_sources"]) == {
        "uq_crm_task_suggestion_sources_suggestion_obligation": (
            "suggestion_id",
            "obligation_id",
        )
    }
    assert _named_unique_columns(tables["crm_task_suggestion_suppressions"]) == {
        "uq_crm_task_suggestion_suppressions_scope": (
            "source_type",
            "source_scope_key",
            "source_action_key",
            "obligation_fingerprint",
        )
    }
    assert _named_unique_columns(tables["gmail_backfill_requests"]) == {}
    for table_name, table in tables.items():
        assert _model_foreign_key_contract(table) == EXPECTED_FOREIGN_KEYS[
            table_name
        ]

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
        for column in origin_indexes[
            "ix_gmail_message_origins_account_thread"
        ].columns
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

    suggestion_indexes = _indexes(tables["crm_task_suggestions"])
    assert tuple(
        column.name
        for column in suggestion_indexes[
            "ix_crm_task_suggestions_review_state"
        ].columns
    ) == ("state", "updated_at", "id")
    assert _compiled_index(
        suggestion_indexes["ix_crm_task_suggestions_gmail_reconciliation"]
    ) == (
        "CREATE INDEX ix_crm_task_suggestions_gmail_reconciliation ON "
        "crm_task_suggestions (gmail_account_id, gmail_thread_id, "
        "source_action_key, id) WHERE source_type = 'gmail_message'"
    )
    source_indexes = _indexes(tables["crm_task_suggestion_sources"])
    assert tuple(
        column.name
        for column in source_indexes[
            "ix_crm_task_suggestion_sources_receipt"
        ].columns
    ) == ("receipt_id", "id")

    assert {
        table_name: _model_index_contract(table)
        for table_name, table in tables.items()
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
        "gmail_extracted_obligations": {},
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
            "workspace_email = lower(trim(workspace_email)) AND "
            "workspace_email <> ''"
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
        "ck_gmail_sync_page_checkpoints_receipts_nonnegative": (
            "receipt_count >= 0"
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
            "origin_kind IN ('sydney_client_send', 'human_send', "
            "'system_automation')"
        ),
        "ck_gmail_message_origins_delivery_state": (
            "delivery_state IN ('sending', 'succeeded', "
            "'delivery_uncertain')"
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
        "ck_crm_task_suggestions_priority": (
            "priority IN ('low', 'normal', 'high')"
        ),
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
        "ck_crm_task_suggestions_confidence": (
            "confidence >= 0 AND confidence <= 1"
        ),
        "ck_crm_task_suggestions_version_positive": "version > 0",
        "ck_crm_task_suggestions_applied_result": (
            "(state = 'applied' AND applied_task_id IS NOT NULL AND "
            "application_idempotency_key IS NOT NULL) OR (state <> "
            "'applied' AND applied_task_id IS NULL)"
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
        "ck_crm_task_suggestion_suppressions_override_shape": (
            "(reprocess_override_at IS NULL AND "
            "reprocess_override_by_admin_id IS NULL AND "
            "reprocess_override_audit_id IS NULL) OR "
            "(reprocess_override_at IS NOT NULL AND "
            "reprocess_override_by_admin_id IS NOT NULL AND "
            "reprocess_override_audit_id IS NOT NULL)"
        )
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
    assert rfc3339_payload.due_at == datetime(
        2026, 8, 21, 13, 0, tzinfo=timezone.utc
    )
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
    env_source = (_backend_root() / "alembic" / "env.py").read_text(
        encoding="utf-8"
    )
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
                .returning(
                    database.Base.metadata.tables[
                        "gmail_sync_accounts"
                    ].c.id
                )
            )
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    database.Base.metadata.tables[
                        "gmail_sync_accounts"
                    ].insert().values(workspace_email=" SQLite@example.test ")
                )
        assert set(TABLES).issubset(table_names)
        assert isinstance(generated_id, UUID)
    finally:
        engine.dispose()


def test_revision_83_generated_ddl_has_all_tables_and_refuses_nonempty_downgrade() -> None:
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
    for forbidden in (
        "raw_body",
        "body_text",
        "access_token",
        "refresh_token",
        "oauth_token",
    ):
        assert forbidden not in upgrade

    downgrade = _render("downgrade")
    expected_lock = (
        "LOCK TABLE " + ", ".join(TABLES) + " IN ACCESS EXCLUSIVE MODE"
    )
    assert expected_lock in downgrade
    assert "revision 83 downgrade refused: Gmail task intake evidence exists" in downgrade
    for table in TABLES:
        assert f"EXISTS (SELECT 1 FROM {table} LIMIT 1)" in downgrade
        assert f"DROP TABLE {table}" in downgrade
    assert downgrade.index(expected_lock) < downgrade.index("EXISTS (SELECT 1")
    assert downgrade.index("EXISTS (SELECT 1") < downgrade.index("DROP TABLE")


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
                assert connection.scalar(
                    sa.text("SHOW server_version_num")
                ).startswith("16")
                assert connection.scalar(
                    sa.text(
                        "SELECT ssl FROM pg_stat_ssl "
                        "WHERE pid = pg_backend_pid()"
                    )
                ) is True
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == REVISION
                _assert_real_schema_matches_models(connection, _model_tables())
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
                    origin_indexes["uq_gmail_message_origins_unresolved_send"]
                    ["dialect_options"]["postgresql_where"]
                )
                assert "IS DISTINCT FROM 'not_delivered'" in unresolved_where
                assert "<>" not in unresolved_where and "!=" not in unresolved_where
                assert origin_indexes[
                    "ix_gmail_message_origins_account_thread"
                ]["unique"] is False
                receipt_indexes = {
                    index["name"]: index
                    for index in inspector.get_indexes("gmail_message_receipts")
                }
                assert receipt_indexes[
                    "ix_gmail_message_receipts_account_thread"
                ]["unique"] is False

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
                        "request_id": UUID(
                            "00000000-0000-4000-8000-000000008312"
                        ),
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
                            "request_id": UUID(
                                "00000000-0000-4000-8000-000000008313"
                            ),
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
                        "request_id": UUID(
                            "00000000-0000-4000-8000-000000008314"
                        ),
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
                            "request_id": UUID(
                                "00000000-0000-4000-8000-000000008315"
                            ),
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
                            "request_id": UUID(
                                "00000000-0000-4000-8000-000000008316"
                            ),
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
            assert heads.count(f"{REVISION} (head)") == 1

            with engine.begin() as connection:
                verify_exact_ownership(
                    connection,
                    expected_database=expected_database,
                    run_marker=run_marker,
                )
                connection.execute(
                    sa.text("DELETE FROM gmail_message_origins")
                )
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
                assert connection.scalar(
                    sa.text("SELECT title FROM crm_tasks WHERE id = 8302")
                ) == "Preserve through Gmail intake"
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
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == REVISION
                assert connection.scalar(
                    sa.text(f'SELECT count(*) FROM "{target_table}" WHERE id = :id'),
                    {"id": evidence_ids[target_table]},
                ) == 1
                assert all(
                    connection.scalar(
                        sa.text(f'SELECT count(*) FROM "{table_name}"')
                    )
                    == (1 if table_name == target_table else 0)
                    for table_name in TABLES
                )
                assert connection.scalar(
                    sa.text("SELECT title FROM crm_tasks WHERE id = 8302")
                ) == "Preserve through Gmail intake"
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
                evidence_id = UUID(
                    "00000000-0000-4000-8000-000000008391"
                )
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
                        pytest.fail(
                            "downgrade did not wait for the evidence writer"
                        )
                    writer_transaction.commit()
                    downgrade_error = future.result(timeout=10)

            assert (
                "revision 83 downgrade refused: Gmail task intake evidence exists"
                in downgrade_error
            )
            with engine.connect() as connection:
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == REVISION
                assert connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM gmail_sync_accounts WHERE id = :id"
                    ),
                    {"id": evidence_id},
                ) == 1
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
                    backend_pid = connection.scalar(
                        sa.text("SELECT pg_backend_pid()")
                    )
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
                assert connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM gmail_message_origins "
                        "WHERE account_id = :account_id "
                        "AND canonical_send_hash = :send_hash "
                        "AND reconciled_outcome IS NULL"
                    ),
                    {"account_id": account_id, "send_hash": "a" * 64},
                ) == 1
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
                            "obligation_fingerprint, dismissal_reason, "
                            "dismissed_by_admin_id, dismissal_audit_id) VALUES "
                            "('gmail_message', :scope, 'send-disclosure', "
                            ":fingerprint, "
                            "'Not a task', :admin_id, :audit_id)"
                        ),
                        {
                            "scope": scope,
                            "fingerprint": "f" * 64,
                            "admin_id": admin_id,
                            "audit_id": audit_id,
                        },
                    )
                assert connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM crm_task_suggestion_suppressions "
                        "WHERE obligation_fingerprint = :fingerprint"
                    ),
                    {"fingerprint": "f" * 64},
                ) == 2
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
                                "gmail:00000000-0000-4000-8000-000000008321:"
                                "thread-a"
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
                            "request_id": UUID(
                                "00000000-0000-4000-8000-000000008352"
                            ),
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
                            "request_id": UUID(
                                "00000000-0000-4000-8000-000000008353"
                            ),
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
                        "INSERT INTO gmail_extracted_obligations "
                        "(id, receipt_id, extraction_attempt_id, action_key, "
                        "schema_version, title, obligation_fingerprint) VALUES "
                        "(:one, :receipt_one, :attempt_one, 'action-one', "
                        "'gmail-task-v1', 'First obligation', :fingerprint_one), "
                        "(:two, :receipt_two, :attempt_two, 'action-two', "
                        "'gmail-task-v1', 'Second obligation', :fingerprint_two), "
                        "(:three, :receipt_three, :attempt_three, 'action-three', "
                        "'gmail-task-v1', 'Third obligation', :fingerprint_three)"
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
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_task_suggestions "
                        "(id, gmail_account_id, gmail_thread_id, source_type, "
                        "source_scope_key, "
                        "source_action_key, title, payload_hash, "
                        "model_schema_version, obligation_fingerprint) VALUES "
                        "(:id, :account_id, 'thread-one', 'gmail_message', "
                        "'gmail:provenance:thread-one', 'action-one', "
                        "'Suggestion', :payload_hash, "
                        "'gmail-task-v1', :fingerprint)"
                    ),
                    {
                        "id": suggestion_id,
                        "account_id": account_id,
                        "payload_hash": "c" * 64,
                        "fingerprint": "a" * 64,
                    },
                )

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO gmail_extracted_obligations "
                            "(receipt_id, extraction_attempt_id, action_key, "
                            "schema_version, title, obligation_fingerprint) "
                            "VALUES (:receipt_two, :attempt_one, 'cross-wired', "
                            "'gmail-task-v1', 'Cross-wired obligation', "
                            ":fingerprint)"
                        ),
                        {
                            "receipt_two": receipt_two,
                            "attempt_one": attempt_one,
                            "fingerprint": "d" * 64,
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

            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO crm_task_suggestions "
                            "(gmail_account_id, gmail_thread_id, source_type, "
                            "source_scope_key, "
                            "source_action_key, title, state, applied_task_id, "
                            "payload_hash, model_schema_version, "
                            "obligation_fingerprint) VALUES "
                            "(:account_id, 'applied-without-key', 'gmail_message', "
                            "'gmail:provenance:applied-without-key', "
                            "'invalid-applied', 'Invalid applied', "
                            "'applied', 8302, :payload_hash, 'gmail-task-v1', "
                            ":fingerprint)"
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
                            "model_schema_version, obligation_fingerprint) "
                            "VALUES (:account_id, 'pending-with-task', "
                            "'gmail_message', "
                            "'gmail:provenance:pending-with-task', "
                            "'invalid-pending', 'Invalid pending', "
                            "'pending_review', 8302, :application_key, "
                            ":payload_hash, 'gmail-task-v1', :fingerprint)"
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
                            "model_schema_version, obligation_fingerprint) VALUES "
                            "(:account_id, 'duplicate-blockers', 'gmail_message', "
                            "'gmail:provenance:duplicate-blockers', "
                            "'invalid-blockers', 'Invalid blockers', "
                            "ARRAY['unsupported_owner', 'unsupported_owner']"
                            "::varchar[], :payload_hash, 'gmail-task-v1', "
                            ":fingerprint)"
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
                        "model_schema_version, obligation_fingerprint) VALUES "
                        "(:account_id, 'failed-keyed', 'gmail_message', "
                        "'gmail:provenance:failed-keyed', 'failed-action', "
                        "'Failed keyed result', 'failed', "
                        ":failed_key, NULL, :failed_hash, 'gmail-task-v1', "
                        ":failed_fingerprint), "
                        "(:account_id, 'applied-complete', 'gmail_message', "
                        "'gmail:provenance:applied-complete', 'applied-action', "
                        "'Applied result', 'applied', "
                        ":applied_key, 8302, :applied_hash, 'gmail-task-v1', "
                        ":applied_fingerprint)"
                    ),
                    {
                        "account_id": account_id,
                        "failed_key": UUID(
                            "00000000-0000-4000-8000-000000008370"
                        ),
                        "failed_hash": "4" * 64,
                        "failed_fingerprint": "5" * 64,
                        "applied_key": UUID(
                            "00000000-0000-4000-8000-000000008371"
                        ),
                        "applied_hash": "6" * 64,
                        "applied_fingerprint": "7" * 64,
                    },
                )
                assert connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM crm_task_suggestions WHERE "
                        "(state = 'failed' AND applied_task_id IS NULL) OR "
                        "(state = 'applied' AND applied_task_id = 8302)"
                    )
                ) == 2
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
                        "model_schema_version, obligation_fingerprint) VALUES "
                        "(NULL, NULL, 'sydney_chat', 'agent-control:sydney', "
                        "'draft-task', "
                        ":request_id, 'Direct Sydney draft', :payload_hash, "
                        "'gmail-task-v1', :fingerprint), "
                        "(:account_id, 'thread-one', 'gmail_message', "
                        "'gmail:account-one:thread-one', "
                        "'action-one', NULL, 'Gmail suggestion', :gmail_hash, "
                        "'gmail-task-v1', :gmail_fingerprint)"
                    ),
                    {
                        "request_id": request_id,
                        "account_id": account_id,
                        "payload_hash": "8" * 64,
                        "fingerprint": "9" * 64,
                        "gmail_hash": "c" * 64,
                        "gmail_fingerprint": "d" * 64,
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
                    "source_request_id": UUID(
                        "00000000-0000-4000-8000-000000008383"
                    ),
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
                    "source_request_id": UUID(
                        "00000000-0000-4000-8000-000000008384"
                    ),
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
                    "source_request_id": UUID(
                        "00000000-0000-4000-8000-000000008385"
                    ),
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
                                "model_schema_version, obligation_fingerprint) "
                                "VALUES (:gmail_account_id, :gmail_thread_id, "
                                ":source_type, "
                                ":source_scope, :source_action, "
                                ":source_request_id, :title, :payload_hash, "
                                "'gmail-task-v1', :fingerprint)"
                            ),
                            {
                                **shape,
                                "source_scope": f"invalid:{index}",
                                "source_action": f"invalid-{index}",
                                "title": f"Invalid source shape {index}",
                                "payload_hash": f"{index:x}" * 64,
                                "fingerprint": f"{index + 4:x}" * 64,
                            },
                        )
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
                            "request_id": UUID(
                                "00000000-0000-4000-8000-000000008332"
                            ),
                            "send_hash": "1" * 64,
                            "envelope_hash": "2" * 64,
                            "body_hash": "3" * 64,
                            "audit_id": audit_id,
                        },
                    )
    finally:
        engine.dispose()


def test_task2_is_appended_to_the_dedicated_workflow_command_only() -> None:
    workflow = (
        _backend_root().parent
        / ".github"
        / "workflows"
        / "gmail-sydney-task-intake.yml"
    ).read_text(encoding="utf-8")
    assert workflow.count("tests/test_gmail_task_intake_migration.py") == 1
    assert "name: Run the Task 1 and Task 2 persistence contracts" in workflow
    command = workflow.split(
        "name: Run the Task 1 and Task 2 persistence contracts", 1
    )[1].split("- name:", 1)[0]
    assert command.rstrip().endswith("tests/test_gmail_task_intake_migration.py")
    assert "test_gmail_history_adapter.py" not in command
