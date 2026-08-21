from __future__ import annotations

import asyncio
import gc
import hashlib
import hmac
import json
import logging
import math
import traceback
import weakref
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "83c6f4e8a1b2"
UTC = timezone.utc
HASH_KEY = b"0123456789abcdef0123456789abcdef"


def _content(
    *,
    labels: tuple[str, ...],
    from_value: str,
    to_value: str,
    body_text: str = "Please call me tomorrow.",
    cc_value: str = "",
    subject: str = "Showing follow-up",
    extra_headers: dict[str, str] | None = None,
    body_media_type: str = "text/plain",
):
    from services.gmail_history_adapter import GmailMessageContent

    headers = {
        "subject": subject,
        "from": from_value,
        "to": to_value,
        "cc": cc_value,
    }
    headers.update(extra_headers or {})
    return GmailMessageContent(
        message_id=f"message-{uuid4()}",
        thread_id=f"thread-{uuid4()}",
        label_ids=labels,
        message_at=datetime(2026, 8, 21, 14, 0, tzinfo=UTC),
        headers=headers,
        body_text=body_text,
        body_media_type=body_media_type,
    )


def test_runtime_config_defaults_are_disabled_and_have_no_hash_key_fallback() -> None:
    from config import Settings

    config = Settings(
        JWT_SECRET="test-secret",
        GMAIL_PARTICIPANT_HASH_KEY="",
        GMAIL_HISTORY_DATABASE_URL="",
    )
    assert config.GMAIL_TASK_INTAKE_ENABLED is False
    assert config.GMAIL_PARTICIPANT_HASH_KEY == ""
    assert config.GMAIL_HISTORY_DATABASE_URL == ""
    assert config.INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS == 10.0
    assert config.INTEGRATION_PROVIDER_DEADLINE_SECONDS == 30.0
    assert config.INTEGRATION_PROVIDER_MAX_WORKERS == 4
    assert config.GMAIL_HISTORY_MAX_PAGES_PER_RUN == 100
    assert config.GMAIL_HISTORY_JOB_DEADLINE_SECONDS == 300.0
    assert config.GMAIL_RECEIPT_PROCESSING_DEADLINE_SECONDS == 30.0
    assert config.GMAIL_RECEIPT_PROCESSING_STALE_AFTER_SECONDS == 120.0


@pytest.mark.parametrize(
    ("overrides", "category"),
    [
        ({"GMAIL_PARTICIPANT_HASH_KEY": ""}, "participant_hash_key_invalid"),
        ({"GMAIL_PARTICIPANT_HASH_KEY": "  x" * 16}, "participant_hash_key_invalid"),
        ({"GMAIL_PARTICIPANT_HASH_KEY": "x" * 31}, "participant_hash_key_invalid"),
        ({"GMAIL_PARTICIPANT_HASH_KEY": "x" * 31 + "é"}, "participant_hash_key_invalid"),
        ({"INTEGRATION_PROVIDER_MAX_WORKERS": 0}, "provider_workers_invalid"),
        ({"INTEGRATION_PROVIDER_DEADLINE_SECONDS": 0}, "provider_deadline_invalid"),
        ({"INTEGRATION_PROVIDER_DEADLINE_SECONDS": math.inf}, "provider_deadline_invalid"),
        ({"INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS": 0}, "provider_socket_timeout_invalid"),
        ({"INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS": math.nan}, "provider_socket_timeout_invalid"),
        (
            {
                "INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS": 31,
                "INTEGRATION_PROVIDER_DEADLINE_SECONDS": 30,
            },
            "provider_socket_timeout_exceeds_deadline",
        ),
        ({"GMAIL_HISTORY_MAX_PAGES_PER_RUN": 0}, "gmail_history_max_pages_invalid"),
        ({"GMAIL_HISTORY_JOB_DEADLINE_SECONDS": 0}, "gmail_history_job_deadline_invalid"),
        (
            {"GMAIL_RECEIPT_PROCESSING_DEADLINE_SECONDS": 0},
            "gmail_receipt_processing_deadline_invalid",
        ),
        (
            {
                "GMAIL_RECEIPT_PROCESSING_DEADLINE_SECONDS": 30,
                "GMAIL_RECEIPT_PROCESSING_STALE_AFTER_SECONDS": 30,
            },
            "gmail_receipt_stale_threshold_invalid",
        ),
    ],
)
def test_enabled_runtime_rejects_unsafe_provider_and_hash_configuration(
    overrides,
    category: str,
) -> None:
    from config import Settings
    from services.gmail_message_sanitizer import validate_gmail_runtime_settings

    values = {
        "JWT_SECRET": "test-secret",
        "GMAIL_TASK_INTAKE_ENABLED": True,
        "GMAIL_PARTICIPANT_HASH_KEY": "x" * 32,
        "GOOGLE_WORKSPACE_CLIENT_ID": "workspace-client-id",
        "GOOGLE_WORKSPACE_CLIENT_SECRET": "workspace-client-secret",
        "GOOGLE_WORKSPACE_REDIRECT_URI": "https://example.test/workspace/callback",
        "DATABASE_URL": (
            "postgresql+asyncpg://fixture:fixture@localhost/"
            "brandon_gmail_config_test?ssl=require"
        ),
        "GMAIL_HISTORY_DATABASE_URL": (
            "postgresql+asyncpg://fixture:fixture@localhost/"
            "brandon_gmail_config_test?ssl=require"
        ),
        **overrides,
    }
    config = Settings(**values)
    with pytest.raises(RuntimeError) as raised:
        validate_gmail_runtime_settings(config)
    assert str(raised.value) == category
    participant_hash_key = values["GMAIL_PARTICIPANT_HASH_KEY"]
    if participant_hash_key:
        assert participant_hash_key not in str(raised.value)


def test_disabled_runtime_does_not_break_unrelated_worker_on_dormant_gmail_config() -> None:
    from config import Settings
    from services.gmail_message_sanitizer import validate_gmail_runtime_settings

    config = Settings(JWT_SECRET="test-secret", GMAIL_TASK_INTAKE_ENABLED=False)
    validated = validate_gmail_runtime_settings(config)
    assert validated.participant_hash_key is None
    assert validated.socket_timeout_seconds == 10.0
    assert validated.deadline_seconds == 30.0

    for history_url in (
        "not-even-a-database-url",
        (
            "postgresql+asyncpg://fixture@ep-name-pooler.us-east-2.aws."
            "neon.tech/other_database?ssl=disable&pgbouncer=true"
        ),
        "postgresql+asyncpg://fixture@localhost/wrong_database?sslmode=disable",
    ):
        dormant_invalid = Settings(
            JWT_SECRET="test-secret",
            GMAIL_TASK_INTAKE_ENABLED=False,
            GMAIL_PARTICIPANT_HASH_KEY=" invalid-non-ascii-é ",
            DATABASE_URL=(
                "postgresql+asyncpg://fixture@localhost/"
                "brandon_gmail_config_test?ssl=require"
            ),
            GMAIL_HISTORY_DATABASE_URL=history_url,
            INTEGRATION_PROVIDER_MAX_WORKERS=0,
            INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS=40,
            INTEGRATION_PROVIDER_DEADLINE_SECONDS=30,
        )
        dormant = validate_gmail_runtime_settings(dormant_invalid)
        assert dormant.participant_hash_key is None


@pytest.mark.parametrize(
    ("history_url", "database_url", "category"),
    [
        (
            "",
            "postgresql+asyncpg://fixture@localhost/brandon_gmail_config_test?ssl=require",
            "gmail_history_database_url_required",
        ),
        (
            "postgresql+asyncpg://fixture@ep-name-pooler.us-east-2.aws.neon.tech/brandon_gmail_config_test?ssl=require",
            "postgresql+asyncpg://fixture@localhost/brandon_gmail_config_test?ssl=require",
            "gmail_history_direct_database_required",
        ),
        (
            "postgresql+asyncpg://fixture@localhost/brandon_other_test?ssl=require",
            "postgresql+asyncpg://fixture@localhost/brandon_gmail_config_test?ssl=require",
            "gmail_history_database_mismatch",
        ),
        (
            "postgresql+asyncpg://fixture@localhost/brandon_gmail_config_test",
            "postgresql+asyncpg://fixture@localhost/brandon_gmail_config_test?ssl=require",
            "gmail_history_tls_required",
        ),
        (
            "sqlite+aiosqlite:///brandon_gmail_config_test",
            "postgresql+asyncpg://fixture@localhost/brandon_gmail_config_test?ssl=require",
            "gmail_history_postgresql_required",
        ),
        (
            "postgresql+asyncpg://fixture@localhost/brandon_gmail_config_test?ssl=require&pgbouncer=true",
            "postgresql+asyncpg://fixture@localhost/brandon_gmail_config_test?ssl=require",
            "gmail_history_direct_database_required",
        ),
        (
            "postgresql+asyncpg://fixture@localhost/brandon_gmail_config_test?ssl=disable",
            "postgresql+asyncpg://fixture@localhost/brandon_gmail_config_test?ssl=require",
            "gmail_history_tls_required",
        ),
        (
            "postgresql+asyncpg://fixture@localhost/brandon_gmail_config_test?sslmode=prefer",
            "postgresql+asyncpg://fixture@localhost/brandon_gmail_config_test?ssl=require",
            "gmail_history_tls_required",
        ),
    ],
)
def test_enabled_runtime_requires_explicit_direct_tls_session_affine_database(
    history_url: str,
    database_url: str,
    category: str,
) -> None:
    from config import Settings
    from services.gmail_message_sanitizer import validate_gmail_runtime_settings

    config = Settings(
        JWT_SECRET="test-secret",
        DATABASE_URL=database_url,
        GMAIL_HISTORY_DATABASE_URL=history_url,
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="x" * 32,
        GOOGLE_WORKSPACE_CLIENT_ID="workspace-client-id",
        GOOGLE_WORKSPACE_CLIENT_SECRET="workspace-client-secret",
        GOOGLE_WORKSPACE_REDIRECT_URI="https://example.test/workspace/callback",
    )
    with pytest.raises(RuntimeError, match=category):
        validate_gmail_runtime_settings(config)


@pytest.mark.parametrize(
    "missing_name",
    [
        "GOOGLE_WORKSPACE_CLIENT_ID",
        "GOOGLE_WORKSPACE_CLIENT_SECRET",
        "GOOGLE_WORKSPACE_REDIRECT_URI",
    ],
)
def test_enabled_runtime_requires_one_resolved_workspace_oauth_configuration(
    missing_name: str,
) -> None:
    from config import Settings
    from services.gmail_message_sanitizer import validate_gmail_runtime_settings

    values = {
        "JWT_SECRET": "test-secret",
        "DATABASE_URL": (
            "postgresql+asyncpg://fixture@localhost/"
            "brandon_gmail_config_test?ssl=require"
        ),
        "GMAIL_HISTORY_DATABASE_URL": (
            "postgresql+asyncpg://fixture@localhost/"
            "brandon_gmail_config_test?ssl=require"
        ),
        "GMAIL_TASK_INTAKE_ENABLED": True,
        "GMAIL_PARTICIPANT_HASH_KEY": "x" * 32,
        "GOOGLE_WORKSPACE_CLIENT_ID": "workspace-client-id",
        "GOOGLE_WORKSPACE_CLIENT_SECRET": "workspace-client-secret",
        "GOOGLE_WORKSPACE_REDIRECT_URI": "https://example.test/workspace/callback",
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "",
        "GOOGLE_CALENDAR_CLIENT_ID": "",
        "GOOGLE_CALENDAR_CLIENT_SECRET": "",
        "GOOGLE_CALENDAR_REDIRECT_URI": "",
    }
    values[missing_name] = ""
    with pytest.raises(
        RuntimeError,
        match="^gmail_workspace_oauth_config_required$",
    ):
        validate_gmail_runtime_settings(Settings(**values))


def test_enabled_runtime_accepts_complete_legacy_workspace_oauth_fallback() -> None:
    from config import Settings
    from services.gmail_message_sanitizer import validate_gmail_runtime_settings

    config = Settings(
        JWT_SECRET="test-secret",
        DATABASE_URL=(
            "postgresql+asyncpg://fixture@localhost/"
            "brandon_gmail_config_test?ssl=require"
        ),
        GMAIL_HISTORY_DATABASE_URL=(
            "postgresql+asyncpg://fixture@localhost/"
            "brandon_gmail_config_test?ssl=require"
        ),
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="x" * 32,
        GOOGLE_WORKSPACE_CLIENT_ID="",
        GOOGLE_WORKSPACE_CLIENT_SECRET="",
        GOOGLE_WORKSPACE_REDIRECT_URI="",
        GOOGLE_CLIENT_ID="legacy-client-id",
        GOOGLE_CLIENT_SECRET="legacy-client-secret",
        GOOGLE_CALENDAR_REDIRECT_URI="https://example.test/legacy/callback",
    )
    validated = validate_gmail_runtime_settings(config)
    assert validated.workspace_oauth_client_id == "legacy-client-id"
    assert validated.workspace_oauth_redirect_uri == (
        "https://example.test/legacy/callback"
    )
    assert "legacy-client-secret" not in repr(validated)


def test_enabled_runtime_rejects_workspace_credentials_with_calendar_redirect() -> None:
    from config import Settings
    from services.gmail_message_sanitizer import validate_gmail_runtime_settings

    config = Settings(
        JWT_SECRET="test-secret",
        DATABASE_URL=(
            "postgresql+asyncpg://fixture@localhost/"
            "brandon_gmail_config_test?ssl=require"
        ),
        GMAIL_HISTORY_DATABASE_URL=(
            "postgresql+asyncpg://fixture@localhost/"
            "brandon_gmail_config_test?ssl=require"
        ),
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="x" * 32,
        GOOGLE_WORKSPACE_CLIENT_ID="workspace-client-id",
        GOOGLE_WORKSPACE_CLIENT_SECRET="workspace-client-secret",
        GOOGLE_WORKSPACE_REDIRECT_URI="",
    )

    with pytest.raises(
        RuntimeError,
        match="^gmail_workspace_oauth_config_required$",
    ):
        validate_gmail_runtime_settings(config)


def test_runtime_settings_repr_redacts_history_database_credentials() -> None:
    from config import Settings
    from services.gmail_message_sanitizer import validate_gmail_runtime_settings

    database_url = (
        "postgresql+asyncpg://fixture:db-password-canary@localhost/"
        "brandon_gmail_config_test?ssl=require"
    )
    validated = validate_gmail_runtime_settings(
        Settings(
            JWT_SECRET="test-secret",
            DATABASE_URL=database_url,
            GMAIL_HISTORY_DATABASE_URL=database_url,
            GMAIL_TASK_INTAKE_ENABLED=True,
            GMAIL_PARTICIPANT_HASH_KEY="x" * 32,
            GOOGLE_WORKSPACE_CLIENT_ID="workspace-client-id",
            GOOGLE_WORKSPACE_CLIENT_SECRET="workspace-client-secret",
            GOOGLE_WORKSPACE_REDIRECT_URI="https://example.test/workspace/callback",
        )
    )

    assert "db-password-canary" not in repr(validated)


def test_participant_hmac_is_v1_domain_separated_and_canonical() -> None:
    from services.gmail_message_sanitizer import participant_hmac

    expected = hmac.new(
        HASH_KEY,
        b"sws:gmail-task-intake:participant:v1\x00client@example.test",
        hashlib.sha256,
    ).hexdigest()
    assert participant_hmac(" Client@Example.Test ", HASH_KEY) == expected
    assert participant_hmac("client@example.test", HASH_KEY) == expected
    assert participant_hmac("other@example.test", HASH_KEY) != expected


@pytest.mark.parametrize(
    ("labels", "from_value", "to_value", "origin_kind", "direction", "classification", "state"),
    [
        (("INBOX",), "Client <client@example.test>", "Brandon <brandon@example.test>", None, "received", "eligible", "pending"),
        (("SENT",), "Brandon <brandon@example.test>", "Client <client@example.test>", None, "sent", "eligible", "pending"),
        (("INBOX", "SENT"), "Brandon <brandon@example.test>", "Brandon <brandon@example.test>", None, "self_copy", "eligible", "pending"),
        (("SENT",), "Brandon <brandon@example.test>", "Brandon <brandon@example.test>", None, "self_copy", "eligible", "pending"),
        ((), "Brandon <brandon@example.test>", "Brandon <brandon@example.test>", None, "received", "eligible", "pending"),
        (("CUSTOM",), "Brandon <brandon@example.test>", "Brandon <brandon@example.test>", None, "received", "eligible", "pending"),
        (("INBOX",), "Brandon <brandon@example.test>", "Client <client@example.test>", None, "received", "eligible", "pending"),
        (("DRAFT",), "Brandon <brandon@example.test>", "Client <client@example.test>", None, "received", "ignored_draft", "ignored"),
        (("DRAFT", "SENT", "INBOX"), "Brandon <brandon@example.test>", "Client <client@example.test>", None, "sent", "ignored_draft", "ignored"),
        (("SPAM", "TRASH", "INBOX"), "Client <client@example.test>", "Brandon <brandon@example.test>", None, "received", "ignored_spam", "ignored"),
        (("SPAM", "INBOX"), "Client <client@example.test>", "Brandon <brandon@example.test>", None, "received", "ignored_spam", "ignored"),
        (("TRASH", "SENT"), "Brandon <brandon@example.test>", "Client <client@example.test>", None, "sent", "ignored_trash", "ignored"),
        (("SENT",), "Brandon <brandon@example.test>", "Client <client@example.test>", "system_automation", "sent", "ignored_system_automation", "ignored"),
        (("SENT",), "Brandon <brandon@example.test>", "Client <client@example.test>", "sydney_client_send", "sent", "eligible", "pending"),
        (("SENT",), "Brandon <brandon@example.test>", "Client <client@example.test>", "human_send", "sent", "eligible", "pending"),
    ],
)
def test_direction_and_durable_eligibility_rules(
    labels,
    from_value,
    to_value,
    origin_kind,
    direction,
    classification,
    state,
) -> None:
    from services.gmail_message_sanitizer import sanitize_gmail_message

    sanitized = sanitize_gmail_message(
        _content(labels=labels, from_value=from_value, to_value=to_value),
        mailbox_email="brandon@example.test",
        participant_hash_key=HASH_KEY,
        origin_kind=origin_kind,
    )
    assert sanitized.direction == direction
    assert sanitized.classification == classification
    assert sanitized.processing_state == state
    sender_address = from_value.split("<")[-1].rstrip(">").strip().lower()
    recipient_address = to_value.split("<")[-1].rstrip(">").strip().lower()
    assert sanitized.sender_hmac == participant_hmac_fixture(sender_address)
    assert sanitized.recipient_hmacs == (
        participant_hmac_fixture(recipient_address),
    )


@pytest.mark.parametrize(
    "extra_headers",
    [
        {"auto-submitted": "auto-generated"},
        {"precedence": "bulk"},
        {"precedence": "list"},
        {"list-id": "newsletter.example.test"},
    ],
)
def test_durable_automation_headers_are_ignored(extra_headers: dict[str, str]) -> None:
    from services.gmail_message_sanitizer import sanitize_gmail_message

    sanitized = sanitize_gmail_message(
        _content(
            labels=("INBOX",),
            from_value="automation@example.test",
            to_value="brandon@example.test",
            extra_headers=extra_headers,
        ),
        mailbox_email="brandon@example.test",
        participant_hash_key=HASH_KEY,
        origin_kind=None,
    )
    assert sanitized.classification == "ignored_automation"
    assert sanitized.processing_state == "ignored"


def test_automation_looking_subject_alone_does_not_suppress_message() -> None:
    from services.gmail_message_sanitizer import sanitize_gmail_message

    sanitized = sanitize_gmail_message(
        _content(
            labels=("INBOX",),
            from_value="client@example.test",
            to_value="brandon@example.test",
            subject="AUTOMATED DELIVERY NOTICE - please call me",
        ),
        mailbox_email="brandon@example.test",
        participant_hash_key=HASH_KEY,
        origin_kind=None,
    )
    assert sanitized.classification == "eligible"
    assert sanitized.processing_state == "pending"


def test_message_sanitizer_strips_quote_signature_tracking_and_html_and_caps_body() -> None:
    from services.gmail_message_sanitizer import sanitize_gmail_message

    private_quote = "PRIVATE OLD THREAD BODY"
    raw = (
        "Please call me tomorrow.\r\n"
        "<div>Confirm <b>Friday</b>.</div>\n"
        "https://tracking.example.test/pixel?secret=private\n"
        "-- \nBrandon Sweeney\nMobile: 555-0100\n"
        + ("x" * 50000)
        + f"\nOn Tue, Jane wrote:\n> {private_quote}\n"
    )
    sanitized = sanitize_gmail_message(
        _content(
            labels=("INBOX",),
            from_value="client@example.test",
            to_value="brandon@example.test",
            body_text=raw,
            body_media_type="text/html",
        ),
        mailbox_email="brandon@example.test",
        participant_hash_key=HASH_KEY,
        max_body_chars=12000,
    )
    assert sanitized.transient_body_text.startswith("Please call me tomorrow.")
    assert "Confirm Friday." in sanitized.transient_body_text
    assert "tracking.example.test" not in sanitized.transient_body_text
    assert "555-0100" not in sanitized.transient_body_text
    assert private_quote not in sanitized.transient_body_text
    assert len(sanitized.transient_body_text) <= 12000
    assert sanitized.body_truncated is True
    assert sanitized.body_hash == hashlib.sha256(
        sanitized.transient_body_text.encode("utf-8")
    ).hexdigest()


@pytest.fixture(scope="module")
def processing_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def processing_runtime(processing_database):
    url, sync_engine = processing_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text("TRUNCATE TABLE gmail_sync_accounts CASCADE")
        )
    engine = create_async_engine(async_test_url(url), pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessionmaker, sync_engine
    finally:
        await engine.dispose()


async def test_receipt_processing_requires_transient_consumer_before_completion(
    processing_runtime,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker, sync_engine = processing_runtime
    secret_body = "PRIVATE BODY TOKEN user-secret@example.test"
    account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="brandon@example.test",
        committed_history_id="1000",
        mode="shadow",
    )
    receipt = GmailMessageReceipt(
        account_id=account.id,
        gmail_message_id="message-private",
        gmail_thread_id="thread-private",
        direction="received",
        message_at=datetime(2026, 8, 21, 14, 0, tzinfo=UTC),
        labels_json='["INBOX"]',
        processing_state="pending",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)

    class _ContentAdapter:
        def __init__(self):
            self.calls = 0

        async def get_message_content(self, **_kwargs):
            self.calls += 1
            return GmailMessageContent(
                message_id="message-private",
                thread_id="thread-private",
                label_ids=("INBOX",),
                message_at=datetime(2026, 8, 21, 14, 0, tzinfo=UTC),
                headers={
                    "subject": "Private request",
                    "from": "client@example.test",
                    "to": "brandon@example.test",
                },
                body_text=secret_body,
            )

    adapter = _ContentAdapter()
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=HASH_KEY,
    )
    with caplog.at_level(logging.INFO):
        pending = await service.process_receipt(receipt.id, consumer=None)

    assert pending.receipt_id == receipt.id
    assert pending.processing_state == "pending"
    assert not hasattr(pending, "body_text")
    assert adapter.calls == 0
    async with sessionmaker() as session:
        unchanged = await session.get(GmailMessageReceipt, receipt.id)
    assert unchanged.processing_state == "pending"
    assert unchanged.body_hash is None

    seen_transient: list[str] = []
    seen_repr: list[str] = []
    consumer_calls = 0

    async def consumer(transient):
        nonlocal consumer_calls
        consumer_calls += 1
        seen_transient.append(transient.transient_body_text)
        seen_repr.append(repr(transient))
        assert secret_body not in repr(transient)
        assert transient.body_hash == hashlib.sha256(secret_body.encode()).hexdigest()
        return SimpleConsumerResult(
            classification=f"{secret_body}-consumer-classification-{'x' * 100}"
        )

    with caplog.at_level(logging.INFO):
        result = await service.process_receipt(receipt.id, consumer=consumer)

    assert result.receipt_id == receipt.id
    assert result.classification == "eligible"
    assert consumer_calls == 1
    assert not hasattr(result, "body_text")
    assert seen_transient == [secret_body]
    assert all(secret_body not in value for value in seen_repr)
    assert adapter.calls == 1
    assert secret_body not in caplog.text

    async with sessionmaker() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
    assert stored.processing_state == "processed"
    assert stored.classification == "eligible"
    assert stored.body_hash == hashlib.sha256(secret_body.encode()).hexdigest()
    assert stored.sender_hmac == participant_hmac_fixture("client@example.test")
    assert json.loads(stored.recipient_hmacs_json) == [
        participant_hmac_fixture("brandon@example.test")
    ]

    with sync_engine.connect() as connection:
        columns = {
            row.column_name
            for row in connection.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' "
                    "AND table_name = 'gmail_message_receipts'"
                )
            )
        }
        stored_text = connection.scalar(
            sa.text(
                "SELECT concat_ws('|', subject_preview, sender_hmac, "
                "recipient_hmacs_json, body_hash, labels_json, "
                "classification, failure_category, failure_message) "
                "FROM gmail_message_receipts WHERE id = :id"
            ),
            {"id": receipt.id},
        )
    assert "body" not in {name for name in columns if name != "body_hash"}
    assert secret_body not in (stored_text or "")
    assert "user-secret@example.test" not in (stored_text or "")


class SimpleConsumerResult:
    def __init__(self, *, classification: str):
        self.classification = classification


async def test_transient_consumer_failure_stays_retryable_and_never_leaks_raw_body(
    processing_runtime,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_history_service import GmailHistoryService, GmailReceiptProcessingError

    engine, sessionmaker, sync_engine = processing_runtime
    secret_body = "PRIVATE FAILURE BODY bearer-value user@example.test"
    now = datetime(2026, 8, 21, 15, 5, tzinfo=UTC)
    account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="brandon@example.test",
        committed_history_id="1001",
        mode="shadow",
    )
    receipt = GmailMessageReceipt(
        account_id=account.id,
        gmail_message_id="message-failure",
        gmail_thread_id="thread-failure",
        direction="received",
        message_at=datetime(2026, 8, 21, 15, 0, tzinfo=UTC),
        labels_json='["INBOX"]',
        processing_state="processing",
        processing_started_at=now - timedelta(seconds=121),
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)

    class _ContentAdapter:
        raw_ref = None

        async def get_message_content(self, **_kwargs):
            content = GmailMessageContent(
                message_id="message-failure",
                thread_id="thread-failure",
                label_ids=("INBOX",),
                message_at=datetime(2026, 8, 21, 15, 0, tzinfo=UTC),
                headers={
                    "subject": "Failure request",
                    "from": "client@example.test",
                    "to": "brandon@example.test",
                },
                body_text=secret_body,
            )
            self.raw_ref = weakref.ref(content)
            return content

    adapter = _ContentAdapter()

    async def failing_consumer(_transient):
        gc.collect()
        assert adapter.raw_ref is not None
        assert adapter.raw_ref() is None
        raise RuntimeError(secret_body)

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=HASH_KEY,
        clock=lambda: now,
        receipt_processing_deadline_seconds=30,
        receipt_processing_stale_after_seconds=120,
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(GmailReceiptProcessingError) as raised:
            await service.process_receipt(receipt.id, consumer=failing_consumer)
    assert str(raised.value) == "gmail_receipt_processing_failed"
    assert secret_body not in repr(raised.value)
    assert secret_body not in caplog.text
    assert secret_body not in "".join(
        traceback.format_exception(raised.value)
    )
    assert raised.value.__suppress_context__ is True

    async with sessionmaker() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
    assert stored.processing_state == "failed"
    assert stored.failure_category == "transient_processing"
    assert stored.failure_message == "Gmail receipt processing failed."
    assert stored.body_hash is None
    assert stored.processing_started_at is None
    with sync_engine.connect() as connection:
        persisted = connection.scalar(
            sa.text(
                "SELECT concat_ws('|', subject_preview, sender_hmac, "
                "recipient_hmacs_json, body_hash, labels_json, "
                "classification, failure_category, failure_message) "
                "FROM gmail_message_receipts WHERE id = :id"
            ),
            {"id": receipt.id},
        )
    assert secret_body not in (persisted or "")

    async def successful_consumer(_transient):
        return SimpleConsumerResult(classification="eligible")

    retried = await service.process_receipt(
        receipt.id,
        consumer=successful_consumer,
    )
    assert retried.claimed is True
    assert retried.processing_state == "processed"


async def test_receipt_releases_raw_and_transient_before_finalize_failure(
    processing_runtime,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailReceiptProcessingError,
    )

    engine, sessionmaker, _sync_engine = processing_runtime
    raw_canary = "private-finalize-body-canary"
    account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="brandon@example.test",
        committed_history_id="1001",
        mode="shadow",
    )
    receipt = GmailMessageReceipt(
        account_id=account.id,
        gmail_message_id="message-finalize-failure",
        gmail_thread_id="thread-finalize-failure",
        direction="received",
        message_at=datetime(2026, 8, 21, 15, 15, tzinfo=UTC),
        labels_json='["INBOX"]',
        processing_state="pending",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)

    raw_ref: weakref.ReferenceType | None = None
    transient_ref: weakref.ReferenceType | None = None

    class _ContentAdapter:
        async def get_message_content(self, **_kwargs):
            nonlocal raw_ref
            content = GmailMessageContent(
                message_id=receipt.gmail_message_id,
                thread_id=receipt.gmail_thread_id,
                label_ids=("INBOX",),
                message_at=receipt.message_at,
                headers={
                    "subject": "Finalize failure",
                    "from": "client@example.test",
                    "to": account.workspace_email,
                },
                body_text=raw_canary,
            )
            raw_ref = weakref.ref(content)
            return content

    async def consumer(transient):
        nonlocal transient_ref
        transient_ref = weakref.ref(transient)

    async def fail_finalize() -> None:
        gc.collect()
        assert raw_ref is not None and raw_ref() is None
        assert transient_ref is not None and transient_ref() is None
        raise RuntimeError(raw_canary)

    service = GmailHistoryService(
        engine=engine,
        adapter=_ContentAdapter(),
        participant_hash_key=HASH_KEY,
        before_receipt_finalize=fail_finalize,
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(GmailReceiptProcessingError) as raised:
            await service.process_receipt(receipt.id, consumer=consumer)

    assert str(raised.value) == "gmail_receipt_processing_failed"
    assert raw_canary not in caplog.text
    assert raw_canary not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__suppress_context__ is True
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
    assert stored.processing_state == "failed"
    assert stored.failure_category == "transient_processing"
    assert stored.body_hash is None


@pytest.mark.parametrize("failure_mode", ["identity_mismatch", "sanitize_failure"])
async def test_receipt_releases_raw_before_failure_state_persistence(
    processing_runtime,
    failure_mode: str,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailReceiptProcessingError,
    )

    engine, sessionmaker, _sync_engine = processing_runtime
    raw_canary = f"raw-pre-sanitize-{failure_mode}-canary"
    account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="brandon@example.test",
        committed_history_id="1001",
        mode="shadow",
    )
    receipt = GmailMessageReceipt(
        account_id=account.id,
        gmail_message_id=f"message-{failure_mode}",
        gmail_thread_id=f"thread-{failure_mode}",
        direction="received",
        message_at=datetime(2026, 8, 21, 15, 20, tzinfo=UTC),
        labels_json='["INBOX"]',
        processing_state="pending",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)

    raw_ref: weakref.ReferenceType | None = None

    class _ContentAdapter:
        calls = 0

        async def get_message_content(self, **_kwargs):
            nonlocal raw_ref
            self.calls += 1
            content = GmailMessageContent(
                message_id=(
                    "wrong-message-id"
                    if failure_mode == "identity_mismatch"
                    else receipt.gmail_message_id
                ),
                thread_id=receipt.gmail_thread_id,
                label_ids=("INBOX",),
                message_at=receipt.message_at,
                headers={
                    "subject": "Failure before extraction",
                    "from": "client@example.test",
                    "to": account.workspace_email,
                },
                body_text=raw_canary,
                body_media_type=(
                    "invalid/media"
                    if failure_mode == "sanitize_failure"
                    else "text/plain"
                ),
            )
            raw_ref = weakref.ref(content)
            return content

    adapter = _ContentAdapter()
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=HASH_KEY,
        alert_sink=alert_sink,
    )
    original_failure_persist = service._persist_deterministic_receipt_failure

    async def assert_released_before_failure_persistence(*args, **kwargs):
        gc.collect()
        assert raw_ref is not None and raw_ref() is None
        return await original_failure_persist(*args, **kwargs)

    service._persist_deterministic_receipt_failure = (
        assert_released_before_failure_persistence
    )
    with pytest.raises(GmailReceiptProcessingError) as raised:
        await service.process_receipt(
            receipt.id,
            consumer=lambda _transient: pytest.fail("consumer must not run"),
        )

    expected_category = (
        "receipt_content_mismatch"
        if failure_mode == "identity_mismatch"
        else "receipt_content_invalid"
    )
    assert str(raised.value) == f"gmail_{expected_category}"
    assert raw_canary not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
        stored_account = await session.get(GmailSyncAccount, account.id)
    assert stored.processing_state == "ignored"
    assert stored.classification == f"ignored_{expected_category}"
    assert stored.failure_category == expected_category
    assert stored.body_hash is None
    assert stored_account.blocked_reason == expected_category
    assert len(alerts) == 1
    replay = await service.process_receipt(
        receipt.id,
        consumer=lambda _transient: pytest.fail("consumer must not run"),
    )
    assert replay.claimed is False
    assert replay.processing_state == "ignored"
    assert adapter.calls == 1


@pytest.mark.parametrize(
    ("category", "expected_state", "expected_classification", "expected_block"),
    [
        (
            "message_not_found",
            "ignored",
            "ignored_message_not_found",
            None,
        ),
        (
            "malformed_provider",
            "ignored",
            "ignored_malformed_provider",
            "malformed_provider",
        ),
        ("oauth_revoked", "failed", None, "oauth_revoked"),
    ],
)
async def test_deterministic_receipt_provider_failure_does_not_refetch(
    processing_runtime,
    category: str,
    expected_state: str,
    expected_classification: str | None,
    expected_block: str | None,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from services.gmail_history_adapter import GmailProviderFailure
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailReceiptProcessingError,
    )

    engine, sessionmaker, _sync_engine = processing_runtime
    account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="brandon@example.test",
        committed_history_id="1001",
        mode="shadow",
    )
    receipt = GmailMessageReceipt(
        account_id=account.id,
        gmail_message_id=f"deterministic-{category}",
        gmail_thread_id=f"deterministic-thread-{category}",
        direction="received",
        message_at=datetime(2026, 8, 21, 15, 25, tzinfo=UTC),
        labels_json='["INBOX"]',
        processing_state="pending",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)

    class _FailingAdapter:
        calls = 0

        async def get_message_content(self, **_kwargs):
            self.calls += 1
            raise GmailProviderFailure(category)

    adapter = _FailingAdapter()
    consumer_calls = 0
    alerts: list[dict[str, str]] = []

    async def consumer(_transient):
        nonlocal consumer_calls
        consumer_calls += 1

    async def alert_sink(**event):
        alerts.append(event)

    async def current_credential(_session):
        return True

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=HASH_KEY,
        alert_sink=alert_sink,
        credential_is_current=current_credential,
    )
    with pytest.raises(
        GmailReceiptProcessingError,
        match=f"^gmail_receipt_{category}$",
    ):
        await service.process_receipt(receipt.id, consumer=consumer)

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=HASH_KEY,
        alert_sink=alert_sink,
        credential_is_current=current_credential,
    )
    replay = await reconstructed.process_receipt(receipt.id, consumer=consumer)
    assert replay.claimed is False
    assert replay.processing_state == expected_state
    assert adapter.calls == 1
    assert consumer_calls == 0
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
        stored_account = await session.get(GmailSyncAccount, account.id)
    assert stored.processing_state == expected_state
    assert stored.classification == expected_classification
    assert stored.failure_category == category
    assert stored.processing_started_at is None
    assert stored_account.blocked_reason == expected_block
    assert len(alerts) == (0 if category == "oauth_revoked" else 1)


async def test_receipt_missing_message_alert_retries_on_reconstructed_sync(
    processing_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from services.gmail_history_adapter import GmailHistoryPage, GmailProviderFailure
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker, _sync_engine = processing_runtime
    account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="brandon@example.test",
        committed_history_id="1001",
        mode="shadow",
    )
    receipt = GmailMessageReceipt(
        account_id=account.id,
        gmail_message_id="missing-receipt-restart",
        gmail_thread_id="missing-receipt-restart-thread",
        direction="received",
        message_at=datetime(2026, 8, 21, 15, 28, tzinfo=UTC),
        labels_json='["INBOX"]',
        processing_state="pending",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)

    class _RecoveringAdapter:
        content_calls = 0
        history_calls = 0

        async def get_message_content(self, **_kwargs):
            self.content_calls += 1
            raise GmailProviderFailure("message_not_found")

        async def list_history(self, **_kwargs):
            self.history_calls += 1
            return GmailHistoryPage(
                history_id="1002",
                messages=(),
                next_page_token=None,
                discovered_history_id_min=None,
                discovered_history_id_max=None,
            )

    adapter = _RecoveringAdapter()
    alert_attempts: list[str] = []
    delivered: list[dict[str, str]] = []

    async def fail_once_alert_sink(**event):
        alert_attempts.append(event["dedupe_key"])
        if len(alert_attempts) == 1:
            raise RuntimeError("alert-sink-transient")
        delivered.append(event)

    first = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=HASH_KEY,
        alert_sink=fail_once_alert_sink,
    )
    with pytest.raises(
        RuntimeError,
        match="^gmail_history_alert_enqueue_failed$",
    ):
        await first.process_receipt(
            receipt.id,
            consumer=lambda _transient: pytest.fail("consumer must not run"),
        )

    async with sessionmaker() as session:
        pending_alert_receipt = await session.get(GmailMessageReceipt, receipt.id)
        pending_alert_account = await session.get(GmailSyncAccount, account.id)
    assert pending_alert_receipt.processing_state == "ignored"
    assert (
        pending_alert_receipt.failure_category
        == "message_not_found_alert_pending"
    )
    assert pending_alert_account.blocked_reason is None
    assert (
        pending_alert_account.last_error_category
        == "message_not_found_alert_pending"
    )

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=HASH_KEY,
        alert_sink=fail_once_alert_sink,
    )
    result = await reconstructed.sync_account(account.id)
    assert result.committed_history_id == "1002"
    assert adapter.content_calls == 1
    assert adapter.history_calls == 1
    assert alert_attempts[0] == alert_attempts[1]
    assert len(delivered) == 1
    async with sessionmaker() as session:
        alerted_receipt = await session.get(GmailMessageReceipt, receipt.id)
    assert alerted_receipt.failure_category == "message_not_found"
    replay = await reconstructed.process_receipt(
        receipt.id,
        consumer=lambda _transient: pytest.fail("consumer must not run"),
    )
    assert replay.claimed is False
    assert adapter.content_calls == 1


async def test_stale_oauth_receipt_failure_is_silent_and_retries_with_new_credential(
    processing_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from services.gmail_history_adapter import (
        GmailMessageContent,
        GmailProviderFailure,
    )
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailReceiptProcessingError,
    )

    engine, sessionmaker, _sync_engine = processing_runtime
    account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="brandon@example.test",
        committed_history_id="1001",
        mode="shadow",
    )
    receipt = GmailMessageReceipt(
        account_id=account.id,
        gmail_message_id="stale-oauth-receipt",
        gmail_thread_id="stale-oauth-thread",
        direction="received",
        message_at=datetime(2026, 8, 21, 15, 30, tzinfo=UTC),
        labels_json='["INBOX"]',
        processing_state="pending",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)

    class _RotatedAdapter:
        calls = 0

        async def get_message_content(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise GmailProviderFailure("oauth_revoked")
            return GmailMessageContent(
                message_id=receipt.gmail_message_id,
                thread_id=receipt.gmail_thread_id,
                label_ids=("INBOX",),
                message_at=receipt.message_at,
                headers={
                    "subject": "Retry with rotated credential",
                    "from": "client@example.test",
                    "to": account.workspace_email,
                },
                body_text="Process once with the current credential.",
            )

    adapter = _RotatedAdapter()
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    async def stale_credential(_session):
        return False

    stale_service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=HASH_KEY,
        alert_sink=alert_sink,
        credential_is_current=stale_credential,
    )
    with pytest.raises(
        GmailReceiptProcessingError,
        match="^gmail_receipt_stale_credential_result$",
    ):
        await stale_service.process_receipt(
            receipt.id,
            consumer=lambda _transient: pytest.fail("stale call cannot consume"),
        )

    async with sessionmaker() as session:
        stale_receipt = await session.get(GmailMessageReceipt, receipt.id)
        healthy_account = await session.get(GmailSyncAccount, account.id)
    assert stale_receipt.processing_state == "failed"
    assert stale_receipt.failure_category == "stale_credential_result"
    assert healthy_account.blocked_reason is None
    assert healthy_account.last_error_category is None
    assert alerts == []

    consumer_calls = 0

    async def consumer(_transient):
        nonlocal consumer_calls
        consumer_calls += 1

    async def current_credential(_session):
        return True

    current_service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=HASH_KEY,
        alert_sink=alert_sink,
        credential_is_current=current_credential,
    )
    recovered = await current_service.process_receipt(
        receipt.id,
        consumer=consumer,
    )
    assert recovered.claimed is True
    assert recovered.processing_state == "processed"
    assert adapter.calls == 2
    assert consumer_calls == 1
    assert alerts == []


async def test_two_workers_claim_one_receipt_and_run_one_transient_consumer(
    processing_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker, _sync_engine = processing_runtime
    account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="brandon@example.test",
        committed_history_id="1002",
        mode="shadow",
    )
    receipt = GmailMessageReceipt(
        account_id=account.id,
        gmail_message_id="message-claim",
        gmail_thread_id="thread-claim",
        direction="received",
        message_at=datetime(2026, 8, 21, 16, 0, tzinfo=UTC),
        labels_json='["INBOX"]',
        processing_state="pending",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)

    claim_ready = asyncio.Event()
    release_claim = asyncio.Event()
    claim_mutex = asyncio.Lock()
    claim_arrived = 0
    fetch_calls = 0
    consumer_calls = 0

    class _BlockingAdapter:
        async def get_message_content(self, **_kwargs):
            nonlocal fetch_calls
            fetch_calls += 1
            return GmailMessageContent(
                message_id="message-claim",
                thread_id="thread-claim",
                label_ids=("INBOX",),
                message_at=datetime(2026, 8, 21, 16, 0, tzinfo=UTC),
                headers={
                    "subject": "Claim",
                    "from": "client@example.test",
                    "to": "brandon@example.test",
                },
                body_text="One transient consumer only.",
            )

    async def consumer(_transient):
        nonlocal consumer_calls
        consumer_calls += 1
        return SimpleConsumerResult(classification="eligible")

    async def before_receipt_claim_flush():
        nonlocal claim_arrived
        async with claim_mutex:
            claim_arrived += 1
            if claim_arrived == 2:
                claim_ready.set()
        await release_claim.wait()

    adapter = _BlockingAdapter()
    services = [
        GmailHistoryService(
            engine=engine,
            adapter=adapter,
            participant_hash_key=HASH_KEY,
            before_receipt_claim_flush=before_receipt_claim_flush,
        )
        for _ in range(2)
    ]
    tasks = [
        asyncio.create_task(item.process_receipt(receipt.id, consumer=consumer))
        for item in services
    ]
    await asyncio.wait_for(claim_ready.wait(), timeout=2)
    release_claim.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)
    assert sum(result.claimed for result in results) == 1
    assert any(result.processing_state == "processed" for result in results)
    assert fetch_calls == 1
    assert consumer_calls == 1


@pytest.mark.parametrize(
    ("suppression", "labels", "expected_classification"),
    [
        ("label", ("DRAFT",), "ignored_draft"),
        ("label", ("SPAM", "INBOX"), "ignored_spam"),
        ("label", ("TRASH", "INBOX"), "ignored_trash"),
        ("origin", ("SENT",), "ignored_system_automation"),
    ],
)
async def test_receipt_refetch_suppression_skips_transient_consumer(
    processing_runtime,
    suppression: str,
    labels: tuple[str, ...],
    expected_classification: str,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import (
        GmailMessageOrigin,
        GmailMessageReceipt,
        GmailSyncAccount,
    )
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker, _sync_engine = processing_runtime
    account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="brandon@example.test",
        committed_history_id="suppression-100",
        mode="shadow",
    )
    receipt = GmailMessageReceipt(
        account_id=account.id,
        gmail_message_id=f"message-refetch-{suppression}",
        gmail_thread_id=f"thread-refetch-{suppression}",
        direction="received",
        message_at=datetime(2026, 8, 21, 16, 30, tzinfo=UTC),
        labels_json='["INBOX"]',
        processing_state="pending",
        classification="eligible",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add(receipt)
        if suppression == "origin":
            audit = AgentActionAudit(
                actor="system:notification",
                action_id="workspace.gmail.send",
                method="POST",
                path="/internal/system-send",
                status_code=202,
                allowed=True,
                request_meta_json="{}",
                response_meta_json="{}",
            )
            session.add(audit)
            await session.flush()
            session.add(
                GmailMessageOrigin(
                    account_id=account.id,
                    request_id=uuid4(),
                    canonical_send_hash="a" * 64,
                    canonical_envelope_hash="b" * 64,
                    canonical_body_hash="c" * 64,
                    gmail_message_id=receipt.gmail_message_id,
                    gmail_thread_id=receipt.gmail_thread_id,
                    origin_kind="system_automation",
                    delivery_state="succeeded",
                    version=2,
                    action_audit_id=audit.id,
                )
            )
        await session.commit()
        await session.refresh(receipt)

    class _Adapter:
        async def get_message_content(self, **_kwargs):
            return GmailMessageContent(
                message_id=receipt.gmail_message_id,
                thread_id=receipt.gmail_thread_id,
                label_ids=labels,
                message_at=receipt.message_at,
                headers={
                    "subject": "Now suppressed",
                    "from": (
                        "brandon@example.test"
                        if suppression == "origin"
                        else "client@example.test"
                    ),
                    "to": (
                        "client@example.test"
                        if suppression == "origin"
                        else "brandon@example.test"
                    ),
                },
                body_text="suppressed-private-body-canary",
            )

    consumer_calls = 0

    async def forbidden_consumer(_transient):
        nonlocal consumer_calls
        consumer_calls += 1
        raise AssertionError("suppressed message must not reach extractor")

    service = GmailHistoryService(
        engine=engine,
        adapter=_Adapter(),
        participant_hash_key=HASH_KEY,
    )
    result = await service.process_receipt(receipt.id, consumer=forbidden_consumer)

    assert result.claimed is True
    assert result.processing_state == "ignored"
    assert result.classification == expected_classification
    assert consumer_calls == 0
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
    assert stored.processing_state == "ignored"
    assert stored.classification == expected_classification
    assert "suppressed-private-body-canary" not in repr(result)


async def test_recent_processing_receipt_is_not_reclaimed(
    processing_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker, _sync_engine = processing_runtime
    now = datetime(2026, 8, 21, 17, 0, tzinfo=UTC)
    account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="brandon@example.test",
        committed_history_id="1003",
        mode="shadow",
    )
    receipt = GmailMessageReceipt(
        account_id=account.id,
        gmail_message_id="message-recent-processing",
        gmail_thread_id="thread-recent-processing",
        direction="received",
        message_at=now,
        labels_json='["INBOX"]',
        processing_state="processing",
        processing_started_at=now - timedelta(seconds=10),
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)

    class _NoFetchAdapter:
        calls = 0

        async def get_message_content(self, **_kwargs):
            self.calls += 1
            raise AssertionError("recent live processing must not be duplicated")

    adapter = _NoFetchAdapter()
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=HASH_KEY,
        clock=lambda: now,
        receipt_processing_deadline_seconds=30,
        receipt_processing_stale_after_seconds=120,
    )
    result = await service.process_receipt(
        receipt.id,
        consumer=lambda _transient: pytest.fail("consumer must not run"),
    )

    assert result.processing_state == "processing"
    assert result.claimed is False
    assert adapter.calls == 0


async def test_two_sessions_racing_stale_reclaim_fetch_and_consume_once(
    processing_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker, _sync_engine = processing_runtime
    now = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)
    account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="brandon@example.test",
        committed_history_id="1004",
        mode="shadow",
    )
    receipt = GmailMessageReceipt(
        account_id=account.id,
        gmail_message_id="message-stale-processing",
        gmail_thread_id="thread-stale-processing",
        direction="received",
        message_at=now,
        labels_json='["INBOX"]',
        processing_state="processing",
        processing_started_at=now - timedelta(seconds=121),
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)

    claim_ready = asyncio.Event()
    release_claim = asyncio.Event()
    claim_mutex = asyncio.Lock()
    claim_arrived = 0
    fetch_calls = 0
    consumer_calls = 0

    class _BlockingAdapter:
        async def get_message_content(self, **_kwargs):
            nonlocal fetch_calls
            fetch_calls += 1
            return GmailMessageContent(
                message_id="message-stale-processing",
                thread_id="thread-stale-processing",
                label_ids=("INBOX",),
                message_at=now,
                headers={
                    "subject": "Recovered request",
                    "from": "client@example.test",
                    "to": "brandon@example.test",
                },
                body_text="Recover this obligation once.",
            )

    async def consumer(_transient):
        nonlocal consumer_calls
        consumer_calls += 1
        return SimpleConsumerResult(classification="eligible")

    async def before_receipt_claim_flush():
        nonlocal claim_arrived
        async with claim_mutex:
            claim_arrived += 1
            if claim_arrived == 2:
                claim_ready.set()
        await release_claim.wait()

    kwargs = {
        "engine": engine,
        "adapter": _BlockingAdapter(),
        "participant_hash_key": HASH_KEY,
        "clock": lambda: now,
        "receipt_processing_deadline_seconds": 30,
        "receipt_processing_stale_after_seconds": 120,
        "before_receipt_claim_flush": before_receipt_claim_flush,
    }
    first_service = GmailHistoryService(**kwargs)
    second_service = GmailHistoryService(**kwargs)
    tasks = [
        asyncio.create_task(first_service.process_receipt(receipt.id, consumer=consumer)),
        asyncio.create_task(second_service.process_receipt(receipt.id, consumer=consumer)),
    ]
    await asyncio.wait_for(claim_ready.wait(), timeout=2)
    release_claim.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)

    assert sum(result.claimed for result in results) == 1
    assert any(result.processing_state == "processed" for result in results)
    assert fetch_calls == 1
    assert consumer_calls == 1
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
    assert stored.processing_started_at == now
    assert stored.processed_at == now


async def test_full_receipt_processing_deadline_bounds_stalled_consumer(
    processing_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_history_service import GmailHistoryService, GmailReceiptProcessingError

    engine, sessionmaker, _sync_engine = processing_runtime
    account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="brandon@example.test",
        committed_history_id="1005",
        mode="shadow",
    )
    receipt = GmailMessageReceipt(
        account_id=account.id,
        gmail_message_id="message-consumer-timeout",
        gmail_thread_id="thread-consumer-timeout",
        direction="received",
        message_at=datetime(2026, 8, 21, 19, 0, tzinfo=UTC),
        labels_json='["INBOX"]',
        processing_state="pending",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)

    class _Adapter:
        async def get_message_content(self, **_kwargs):
            return GmailMessageContent(
                message_id=receipt.gmail_message_id,
                thread_id=receipt.gmail_thread_id,
                label_ids=("INBOX",),
                message_at=receipt.message_at,
                headers={
                    "subject": "Deadline",
                    "from": "client@example.test",
                    "to": "brandon@example.test",
                },
                body_text="consumer-timeout-body-canary",
            )

    entered = asyncio.Event()
    release = asyncio.Event()

    async def stalled_consumer(_transient):
        entered.set()
        await release.wait()

    service = GmailHistoryService(
        engine=engine,
        adapter=_Adapter(),
        participant_hash_key=HASH_KEY,
        receipt_processing_deadline_seconds=0.05,
        receipt_processing_stale_after_seconds=1,
    )
    try:
        pending = asyncio.create_task(
            service.process_receipt(receipt.id, consumer=stalled_consumer)
        )
        await asyncio.wait_for(entered.wait(), timeout=1)
        with pytest.raises(GmailReceiptProcessingError) as raised:
            await pending
    finally:
        release.set()

    assert str(raised.value) == "gmail_receipt_processing_timeout"
    assert "consumer-timeout-body-canary" not in "".join(
        traceback.format_exception(raised.value)
    )
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
    assert stored.processing_state == "failed"
    assert stored.failure_category == "processing_timeout"
    assert stored.processing_started_at is None


def test_receipt_stale_threshold_must_exceed_full_processing_deadline() -> None:
    from services.gmail_history_service import GmailHistoryService

    with pytest.raises(ValueError, match="gmail_receipt_stale_threshold_invalid"):
        GmailHistoryService(
            engine=object(),
            adapter=object(),
            participant_hash_key=HASH_KEY,
            receipt_processing_deadline_seconds=30,
            receipt_processing_stale_after_seconds=30,
        )


def participant_hmac_fixture(address: str) -> str:
    return hmac.new(
        HASH_KEY,
        b"sws:gmail-task-intake:participant:v1\x00" + address.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
