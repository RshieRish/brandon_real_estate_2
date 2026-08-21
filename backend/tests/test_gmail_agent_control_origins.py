from __future__ import annotations

import asyncio
import gc
import json
import threading
import traceback
import weakref
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "83c6f4e8a1b2"
UTC = timezone.utc


class _URL:
    path = "/api/v1/agent-control/workspace/gmail/send"


class _Request:
    method = "POST"
    url = _URL()


def test_intent_claim_repr_never_exposes_refresh_token() -> None:
    from services.gmail_origin_service import _IntentClaim

    raw_canary = "private-refresh-token-canary"
    claim = _IntentClaim(
        origin=SimpleNamespace(),
        refresh_token=raw_canary,
        account_email="brandon@example.test",
    )

    assert raw_canary not in repr(claim)


@pytest.fixture(scope="module")
def origin_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def origin_runtime(origin_database):
    url, sync_engine = origin_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE gmail_sync_accounts, agent_action_audits, "
                "settings CASCADE"
            )
        )
    engine = create_async_engine(async_test_url(url), pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessionmaker, sync_engine
    finally:
        await engine.dispose()


def _payload(
    *,
    request_id: UUID | None = None,
    retry_of_request_id: UUID | None = None,
    subject: str = "Inspection follow-up",
    body_text: str = "I will send the inspection summary Friday.",
):
    from schemas.agent_control import WorkspaceGmailSendRequest

    values = {
        "to": ["Client@Example.Test"],
        "cc": ["Assistant@Example.Test"],
        "bcc": [],
        "subject": subject,
        "body_text": body_text,
        "confirmed_by_brandon": True,
        "confirmation_note": "Confirmed privately.",
    }
    if request_id is not None:
        values["request_id"] = request_id
    if retry_of_request_id is not None:
        values["retry_of_request_id"] = retry_of_request_id
    return WorkspaceGmailSendRequest(**values)


async def _seed_account(sessionmaker, *, email: str = "brandon@example.test"):
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting

    row = GmailSyncAccount(
        workspace_email=email,
        committed_history_id="100",
        mode="shadow",
    )
    async with sessionmaker() as session:
        session.add(row)
        await session.flush()
        session.add_all(
            [
                Setting(
                    key="google_workspace_gmail_account_id",
                    value=str(row.id),
                ),
                Setting(
                    key="google_workspace_refresh_token",
                    value="database-bound-refresh-token",
                ),
            ]
        )
        await session.commit()
        await session.refresh(row)
    return row


def test_send_schema_requires_caller_uuid_and_types_optional_retry_uuid() -> None:
    from schemas.agent_control import WorkspaceGmailSendRequest

    with pytest.raises(ValidationError):
        WorkspaceGmailSendRequest(
            to=["client@example.test"],
            subject="Missing request UUID",
            body_text="Do not send.",
            confirmed_by_brandon=True,
        )
    with pytest.raises(ValidationError):
        WorkspaceGmailSendRequest(
            to=["client@example.test"],
            subject="Bad request UUID",
            body_text="Do not send.",
            confirmed_by_brandon=True,
            request_id="not-a-uuid",
        )
    with pytest.raises(ValidationError):
        WorkspaceGmailSendRequest(
            to=["client@example.test"],
            subject="Bad retry UUID",
            body_text="Do not send.",
            confirmed_by_brandon=True,
            request_id=uuid4(),
            retry_of_request_id="not-a-uuid",
        )
    request_id = uuid4()
    retry_id = uuid4()
    payload = _payload(request_id=request_id, retry_of_request_id=retry_id)
    assert payload.request_id == request_id
    assert payload.retry_of_request_id == retry_id


async def test_agent_control_route_uses_durable_origin_orchestration_not_legacy_send() -> None:
    from routers import agent_control

    request_id = uuid4()
    result = SimpleNamespace(
        request_id=request_id,
        message_id="route-message",
        thread_id="route-thread",
        delivery_state="succeeded",
        replayed=False,
    )
    db = SimpleNamespace()
    with (
        patch(
            "routers.agent_control.send_agent_gmail_with_origin",
            new_callable=AsyncMock,
            return_value=result,
        ) as durable_send,
        patch("routers.agent_control.send_gmail_message") as legacy_send,
        patch(
            "routers.agent_control.load_workspace_refresh_token_from_db",
            new_callable=AsyncMock,
        ) as legacy_token_load,
    ):
        response = await agent_control.workspace_gmail_send(
            payload=_payload(request_id=request_id),
            request=_Request(),
            db=db,
            agent={"actor": "hermes"},
        )

    durable_send.assert_awaited_once()
    kwargs = durable_send.await_args.kwargs
    assert kwargs["db"] is db
    assert kwargs["payload"].request_id == request_id
    assert kwargs["request"].url.path.endswith("/gmail/send")
    assert kwargs["actor"] == "hermes"
    legacy_send.assert_not_called()
    legacy_token_load.assert_not_awaited()
    assert response.request_id == request_id
    assert response.message_id == "route-message"
    assert response.thread_id == "route-thread"
    assert response.delivery_state == "succeeded"
    assert response.replayed is False


@pytest.mark.parametrize(
    ("status_code", "category"),
    [
        (409, "gmail_send_reconciliation_required"),
        (503, "gmail_account_not_bound"),
    ],
)
async def test_agent_control_route_maps_bounded_origin_conflicts(
    status_code: int,
    category: str,
) -> None:
    from fastapi import HTTPException
    from routers import agent_control
    from services.gmail_origin_service import GmailSendConflict

    db = SimpleNamespace()
    with patch(
        "routers.agent_control.send_agent_gmail_with_origin",
        new_callable=AsyncMock,
        side_effect=GmailSendConflict(category, status_code=status_code),
    ) as durable_send:
        with pytest.raises(HTTPException) as raised:
            await agent_control.workspace_gmail_send(
                payload=_payload(request_id=uuid4()),
                request=_Request(),
                db=db,
                agent={"actor": "hermes"},
            )
    durable_send.assert_awaited_once()
    assert raised.value.status_code == status_code
    assert raised.value.detail == category


async def test_agent_control_route_maps_uncertain_result_without_provider_detail() -> None:
    from fastapi import HTTPException
    from routers import agent_control

    with patch(
        "routers.agent_control.send_agent_gmail_with_origin",
        new_callable=AsyncMock,
        side_effect=RuntimeError("gmail_send_delivery_uncertain"),
    ):
        with pytest.raises(HTTPException) as raised:
            await agent_control.workspace_gmail_send(
                payload=_payload(request_id=uuid4()),
                request=_Request(),
                db=SimpleNamespace(),
                agent={"actor": "hermes"},
            )
    assert raised.value.status_code == 503
    assert raised.value.detail == "gmail_send_delivery_uncertain"


def test_canonical_hash_excludes_request_ids_and_normalizes_envelope() -> None:
    import base64
    from email import policy
    from email.parser import BytesParser

    from services.gmail_origin_service import canonicalize_gmail_send
    from services.workspace_service import _build_raw_email

    first = canonicalize_gmail_send(
        account_email=" Brandon@Example.Test ",
        payload=_payload(request_id=uuid4()),
        intended_thread_id=None,
    )
    second = canonicalize_gmail_send(
        account_email="brandon@example.test",
        payload=_payload(request_id=uuid4(), retry_of_request_id=uuid4()),
        intended_thread_id=None,
    )
    assert first.canonical_send_hash == second.canonical_send_hash
    assert first.canonical_envelope_hash == second.canonical_envelope_hash
    assert first.canonical_body_hash == second.canonical_body_hash
    assert len(first.canonical_send_hash) == 64
    assert len(first.canonical_envelope_hash) == 64
    assert len(first.canonical_body_hash) == 64
    serialized = first.canonical_envelope_bytes.decode("utf-8")
    assert "brandon@example.test" in serialized
    assert "client@example.test" in serialized
    assert "assistant@example.test" in serialized
    assert str(_payload(request_id=uuid4()).request_id) not in serialized

    wire_payload = _payload(
        request_id=uuid4(),
        subject="  Wire subject  ",
        body_text="Wire line one\r\nWire line two",
    )
    assert wire_payload.subject == "Wire subject"
    raw = _build_raw_email(
        to=wire_payload.to,
        cc=wire_payload.cc,
        bcc=wire_payload.bcc,
        subject=wire_payload.subject,
        body_text=wire_payload.body_text,
    )
    parsed = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(raw.encode("ascii"))
    )
    provider_body = parsed.get_content()
    assert provider_body == "Wire line one\nWire line two\n"
    intent_canonical = canonicalize_gmail_send(
        account_email="brandon@example.test",
        payload=wire_payload,
        intended_thread_id=None,
    )
    provider_canonical = canonicalize_gmail_send(
        account_email="brandon@example.test",
        payload=wire_payload.model_copy(update={"body_text": provider_body}),
        intended_thread_id=None,
    )
    assert intent_canonical.canonical_body_hash == provider_canonical.canonical_body_hash
    assert intent_canonical.canonical_send_hash == provider_canonical.canonical_send_hash


async def test_missing_or_ambiguous_bound_account_fails_before_audit_or_provider(
    origin_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailSyncAccount
    from models.setting import Setting
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    provider_calls = 0

    def transport(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {"id": "provider-message", "thread_id": "provider-thread"}

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    try:
        with pytest.raises(GmailSendConflict) as missing:
            await service.send(
                payload=_payload(request_id=uuid4()),
                request=_Request(),
                actor="hermes",
            )
        assert missing.value.category == "gmail_account_not_bound"
        assert missing.value.status_code == 503

        async with sessionmaker() as session:
            session.add_all(
                [
                    GmailSyncAccount(
                        workspace_email="first@example.test",
                        committed_history_id="1",
                        mode="shadow",
                    ),
                    GmailSyncAccount(
                        workspace_email="second@example.test",
                        committed_history_id="1",
                        mode="shadow",
                    ),
                    Setting(
                        key="google_workspace_gmail_account_id",
                        value="not-a-canonical-uuid",
                    ),
                    Setting(
                        key="google_workspace_refresh_token",
                        value="database-bound-refresh-token",
                    ),
                ]
            )
            await session.commit()
        with pytest.raises(GmailSendConflict) as ambiguous:
            await service.send(
                payload=_payload(request_id=uuid4()),
                request=_Request(),
                actor="hermes",
            )
        assert ambiguous.value.category == "gmail_account_binding_ambiguous"
        assert ambiguous.value.status_code == 409
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    async with sessionmaker() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(GmailMessageOrigin)) == 0
        assert await session.scalar(sa.select(sa.func.count()).select_from(AgentActionAudit)) == 0
    assert provider_calls == 0


async def test_dangling_binding_or_missing_database_token_fails_before_provider(
    origin_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin
    from models.setting import Setting
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    calls = 0

    def transport(**_kwargs):
        nonlocal calls
        calls += 1
        return {"id": "never", "thread_id": "never"}

    async with sessionmaker() as session:
        session.add(
            Setting(
                key="google_workspace_gmail_account_id",
                value=str(uuid4()),
            )
        )
        await session.commit()
    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    try:
        with pytest.raises(GmailSendConflict) as dangling:
            await service.send(
                payload=_payload(request_id=uuid4()),
                request=_Request(),
                actor="hermes",
            )
        assert dangling.value.category == "gmail_account_binding_dangling"
    finally:
        executor.shutdown()
    assert calls == 0
    async with sessionmaker() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(GmailMessageOrigin)) == 0
        assert await session.scalar(sa.select(sa.func.count()).select_from(AgentActionAudit)) == 0


async def test_single_account_is_never_guessed_without_binding_and_valid_binding_needs_db_token(
    origin_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailSyncAccount
    from models.setting import Setting
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = GmailSyncAccount(
        workspace_email="only-account@example.test",
        committed_history_id="1",
        mode="shadow",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.commit()
        await session.refresh(account)
    calls = 0

    def transport(**_kwargs):
        nonlocal calls
        calls += 1
        return {"id": "never", "thread_id": "never"}

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    try:
        with pytest.raises(GmailSendConflict) as unbound:
            await service.send(
                payload=_payload(request_id=uuid4()),
                request=_Request(),
                actor="hermes",
            )
        assert unbound.value.category == "gmail_account_not_bound"

        async with sessionmaker() as session:
            session.add(
                Setting(
                    key="google_workspace_gmail_account_id",
                    value=str(account.id),
                )
            )
            await session.commit()
        with pytest.raises(GmailSendConflict) as token_missing:
            await service.send(
                payload=_payload(request_id=uuid4()),
                request=_Request(),
                actor="hermes",
            )
        assert token_missing.value.category == "gmail_database_token_missing"
    finally:
        executor.shutdown()
    assert calls == 0
    async with sessionmaker() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(GmailMessageOrigin)) == 0
        assert await session.scalar(sa.select(sa.func.count()).select_from(AgentActionAudit)) == 0


async def test_tx1_commits_intent_and_fail_closed_audit_before_zero_retry_provider(
    origin_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    request_id = uuid4()
    observed: dict[str, object] = {}

    def transport(**kwargs):
        observed["kwargs"] = kwargs
        with sync_engine.connect() as connection:
            row = connection.execute(
                sa.text(
                    "SELECT o.delivery_state, o.version, o.action_audit_id, "
                    "a.action_id, a.request_meta, a.response_meta "
                    "FROM gmail_message_origins AS o "
                    "JOIN agent_action_audits AS a ON a.id = o.action_audit_id "
                    "WHERE o.account_id = :account_id AND o.request_id = :request_id"
                ),
                {"account_id": account.id, "request_id": request_id},
            ).one()
        observed["intent"] = row
        return {"id": "provider-message-1", "thread_id": "provider-thread-1"}

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    expected_canonical = service.canonical_for_account(
        account.workspace_email,
        _payload(request_id=request_id),
    )
    try:
        result = await service.send(
            payload=_payload(request_id=request_id),
            request=_Request(),
            actor="hermes",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert result.request_id == request_id
    assert result.delivery_state == "succeeded"
    assert result.message_id == "provider-message-1"
    assert result.thread_id == "provider-thread-1"
    assert result.replayed is False
    assert observed["intent"][:4] == (
        "sending",
        1,
        observed["intent"].action_audit_id,
        "workspace.gmail.send.intent",
    )
    assert observed["intent"].action_audit_id is not None
    assert "inspection summary" not in observed["intent"].request_meta.lower()
    assert "inspection summary" not in observed["intent"].response_meta.lower()
    assert observed["kwargs"]["num_retries"] == 0
    assert observed["kwargs"]["refresh_token"] == "database-bound-refresh-token"
    assert observed["kwargs"]["account_email"] == account.workspace_email

    async with sessionmaker() as session:
        origin = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account.id,
                GmailMessageOrigin.request_id == request_id,
            )
        )
        audit = await session.get(AgentActionAudit, origin.action_audit_id)
        receipt = await session.scalar(
            sa.select(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id,
                GmailMessageReceipt.gmail_message_id == "provider-message-1",
            )
        )
    assert origin.delivery_state == "succeeded"
    assert origin.version == 2
    assert origin.gmail_message_id == "provider-message-1"
    assert origin.canonical_send_hash == expected_canonical.canonical_send_hash
    assert origin.canonical_envelope_hash == expected_canonical.canonical_envelope_hash
    assert origin.canonical_body_hash == expected_canonical.canonical_body_hash
    assert receipt.gmail_thread_id == "provider-thread-1"
    assert receipt.direction == "sent"
    assert receipt.processing_state == "pending"
    request_meta = json.loads(audit.request_meta_json)
    assert request_meta == {
        "to_count": 1,
        "cc_count": 1,
        "bcc_count": 0,
        "subject_length": 20,
        "body_length": 42,
        "confirmed_by_brandon": True,
        "confirmation_note_length": 20,
        "request_id": str(request_id),
        "retry_of_request_id": None,
    }


@pytest.mark.parametrize(
    (
        "workspace_client_id",
        "workspace_client_secret",
        "legacy_client_id",
        "legacy_client_secret",
        "expected_client_id",
        "expected_client_secret",
    ),
    [
        (
            "bound-client-id",
            "bound-client-secret",
            "",
            "",
            "bound-client-id",
            "bound-client-secret",
        ),
        (
            "",
            "",
            "legacy-client-id",
            "legacy-client-secret",
            "legacy-client-id",
            "legacy-client-secret",
        ),
    ],
)
async def test_default_route_helper_builds_transport_from_committed_database_binding(
    origin_runtime,
    monkeypatch: pytest.MonkeyPatch,
    workspace_client_id: str,
    workspace_client_secret: str,
    legacy_client_id: str,
    legacy_client_secret: str,
    expected_client_id: str,
    expected_client_secret: str,
) -> None:
    from config import settings
    from models.gmail_task_intake import GmailMessageOrigin
    import services.gmail_origin_service as origin_module
    from services.integration_health_service import BoundedProviderExecutor

    _engine, sessionmaker, sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    request_id = uuid4()
    gmail = Mock()
    execute = gmail.users.return_value.messages.return_value.send.return_value.execute
    execute.return_value = {
        "id": "default-wiring-message",
        "threadId": "default-wiring-thread",
    }
    observed: dict[str, object] = {}

    def bound_client_builder(**kwargs):
        observed["builder_kwargs"] = kwargs
        with sync_engine.connect() as connection:
            observed["committed_intent"] = connection.execute(
                sa.text(
                    "SELECT o.delivery_state, a.action_id "
                    "FROM gmail_message_origins AS o "
                    "JOIN agent_action_audits AS a ON a.id = o.action_audit_id "
                    "WHERE o.account_id = :account_id AND o.request_id = :request_id"
                ),
                {"account_id": account.id, "request_id": request_id},
            ).one()
        return gmail

    executor = BoundedProviderExecutor(max_workers=1)
    monkeypatch.setattr(
        origin_module,
        "get_agent_gmail_provider_executor",
        lambda: executor,
    )
    monkeypatch.setattr(
        origin_module,
        "build_gmail_service",
        bound_client_builder,
    )
    monkeypatch.setattr(
        settings,
        "GOOGLE_WORKSPACE_CLIENT_ID",
        workspace_client_id,
    )
    monkeypatch.setattr(
        settings,
        "GOOGLE_WORKSPACE_CLIENT_SECRET",
        workspace_client_secret,
    )
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", legacy_client_id)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", legacy_client_secret)
    monkeypatch.setattr(settings, "GOOGLE_CALENDAR_CLIENT_ID", "")
    monkeypatch.setattr(settings, "GOOGLE_CALENDAR_CLIENT_SECRET", "")
    monkeypatch.setattr(
        settings,
        "GOOGLE_WORKSPACE_REDIRECT_URI",
        "https://example.test/workspace/callback",
    )
    monkeypatch.setattr(
        settings,
        "GOOGLE_WORKSPACE_REFRESH_TOKEN",
        "ambient-refresh-token-must-not-be-used",
    )
    monkeypatch.setattr(
        settings,
        "INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS",
        6.5,
    )
    monkeypatch.setattr(
        settings,
        "INTEGRATION_PROVIDER_DEADLINE_SECONDS",
        9.0,
    )

    try:
        async with sessionmaker() as db:
            result = await origin_module.send_agent_gmail_with_origin(
                db=db,
                payload=_payload(request_id=request_id),
                request=_Request(),
                actor="hermes",
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert observed["builder_kwargs"] == {
        "refresh_token": "database-bound-refresh-token",
        "client_id": expected_client_id,
        "client_secret": expected_client_secret,
        "socket_timeout_seconds": 6.5,
    }
    assert observed["committed_intent"] == (
        "sending",
        "workspace.gmail.send.intent",
    )
    gmail.users.return_value.messages.return_value.send.assert_called_once()
    execute.assert_called_once_with(num_retries=0)
    assert result.request_id == request_id
    assert result.message_id == "default-wiring-message"
    assert result.thread_id == "default-wiring-thread"
    async with sessionmaker() as session:
        stored = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account.id,
                GmailMessageOrigin.request_id == request_id,
            )
        )
    assert stored.delivery_state == "succeeded"


async def test_default_route_missing_resolved_oauth_config_fails_before_intent(
    origin_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import settings
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin
    import services.gmail_origin_service as origin_module

    _engine, sessionmaker, _sync_engine = origin_runtime
    await _seed_account(sessionmaker)
    for name in (
        "GOOGLE_WORKSPACE_CLIENT_ID",
        "GOOGLE_WORKSPACE_CLIENT_SECRET",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_CALENDAR_CLIENT_ID",
        "GOOGLE_CALENDAR_CLIENT_SECRET",
        "GOOGLE_WORKSPACE_REDIRECT_URI",
        "GOOGLE_CALENDAR_REDIRECT_URI",
    ):
        monkeypatch.setattr(settings, name, "")

    provider_calls = 0

    def forbidden_provider(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("missing OAuth config must fail before provider setup")

    monkeypatch.setattr(origin_module, "build_gmail_service", forbidden_provider)
    async with sessionmaker() as db:
        with pytest.raises(
            RuntimeError,
            match="^gmail_workspace_oauth_config_required$",
        ):
            await origin_module.send_agent_gmail_with_origin(
                db=db,
                payload=_payload(request_id=uuid4()),
                request=_Request(),
                actor="hermes",
            )
    async with sessionmaker() as session:
        origins = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageOrigin)
        )
        audits = await session.scalar(
            sa.select(sa.func.count()).select_from(AgentActionAudit)
        )
    assert provider_calls == 0
    assert origins == 0
    assert audits == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"to": []},
        {"to": ["not-an-email"]},
        {"to": ["victim@example.test\r\nBcc: attacker@example.test"]},
        {"subject": ""},
        {"body_text": ""},
    ],
)
def test_send_schema_rejects_invalid_envelope_before_service(overrides) -> None:
    from schemas.agent_control import WorkspaceGmailSendRequest

    values = {
        "request_id": uuid4(),
        "to": ["client@example.test"],
        "cc": [],
        "bcc": [],
        "subject": "Valid subject",
        "body_text": "Valid body",
        "confirmed_by_brandon": True,
    }
    values.update(overrides)
    with pytest.raises(ValidationError):
        WorkspaceGmailSendRequest(**values)


async def test_unconfirmed_send_fails_before_intent_audit_or_provider(
    origin_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    await _seed_account(sessionmaker)
    provider_calls = 0

    def transport(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {"id": "never", "thread_id": "never"}

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    payload = _payload(request_id=uuid4()).model_copy(
        update={"confirmed_by_brandon": False}
    )
    try:
        with pytest.raises(GmailSendConflict) as raised:
            await service.send(payload=payload, request=_Request(), actor="hermes")
    finally:
        executor.shutdown()
    assert raised.value.category == "gmail_send_confirmation_required"
    assert provider_calls == 0
    async with sessionmaker() as session:
        assert await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageOrigin)
        ) == 0
        assert await session.scalar(
            sa.select(sa.func.count()).select_from(AgentActionAudit)
        ) == 0


async def test_audit_failure_rolls_back_intent_and_makes_zero_provider_calls(
    origin_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    await _seed_account(sessionmaker)
    calls = 0

    def transport(**_kwargs):
        nonlocal calls
        calls += 1
        return {"id": "never", "thread_id": "never"}

    async def failing_audit(*_args, **_kwargs):
        raise RuntimeError("synthetic audit flush failure")

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
        transactional_audit_writer=failing_audit,
    )
    try:
        with pytest.raises(RuntimeError, match="agent_send_audit_failed"):
            await service.send(
                payload=_payload(request_id=uuid4()),
                request=_Request(),
                actor="hermes",
            )
    finally:
        executor.shutdown()
    assert calls == 0
    async with sessionmaker() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(GmailMessageOrigin)) == 0
        assert await session.scalar(sa.select(sa.func.count()).select_from(AgentActionAudit)) == 0


async def test_success_replay_returns_stored_result_and_payload_mismatch_fails_closed(
    origin_runtime,
) -> None:
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    await _seed_account(sessionmaker)
    calls = 0

    def transport(**_kwargs):
        nonlocal calls
        calls += 1
        return {"id": "provider-replay", "thread_id": "thread-replay"}

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    request_id = uuid4()
    try:
        first = await service.send(
            payload=_payload(request_id=request_id), request=_Request(), actor="hermes"
        )
        replay = await service.send(
            payload=_payload(request_id=request_id), request=_Request(), actor="hermes"
        )
        with pytest.raises(GmailSendConflict) as mismatch:
            await service.send(
                payload=_payload(request_id=request_id, subject="Changed subject"),
                request=_Request(),
                actor="hermes",
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    assert first.replayed is False
    assert replay.replayed is True
    assert replay.message_id == "provider-replay"
    assert mismatch.value.category == "gmail_send_idempotency_mismatch"
    assert mismatch.value.status_code == 409
    assert calls == 1


async def test_system_automation_send_persists_suppressed_receipt_origin(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: {
            "id": "automation-message",
            "thread_id": "automation-thread",
        },
        deadline_seconds=1,
    )
    try:
        result = await service.send(
            payload=_payload(request_id=uuid4()),
            request=_Request(),
            actor="system:notification",
            origin_kind="system_automation",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert result.delivery_state == "succeeded"
    async with sessionmaker() as session:
        origin = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account.id
            )
        )
        receipt = await session.scalar(
            sa.select(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
    assert origin.origin_kind == "system_automation"
    assert receipt.processing_state == "ignored"
    assert receipt.classification == "ignored_system_automation"


@pytest.mark.parametrize(
    ("failure", "category"),
    [
        (RuntimeError("private rejection client@example.test"), "transient_provider"),
        (ValueError("malformed private provider response"), "malformed_provider"),
    ],
)
async def test_post_intent_provider_failures_become_sanitized_uncertain_without_retry(
    origin_runtime,
    failure: Exception,
    category: str,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    calls = 0

    def transport(**_kwargs):
        nonlocal calls
        calls += 1
        raise failure

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    request_id = uuid4()
    try:
        with pytest.raises(RuntimeError, match="gmail_send_delivery_uncertain") as raised:
            await service.send(
                payload=_payload(request_id=request_id),
                request=_Request(),
                actor="hermes",
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    assert calls == 1
    assert "private" not in str(raised.value)
    assert "private" not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__suppress_context__ is True
    async with sessionmaker() as session:
        origin = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account.id,
                GmailMessageOrigin.request_id == request_id,
            )
        )
    assert origin.delivery_state == "delivery_uncertain"
    assert origin.failure_category == category
    assert "private" not in (origin.failure_message or "")
    assert origin.gmail_message_id is None
    assert origin.gmail_thread_id is None


@pytest.mark.parametrize(
    ("field_name", "provider_id"),
    [
        ("id", "message with spaces"),
        ("thread_id", "thread\twith-control"),
        ("id", "message-non-ascii-é"),
    ],
)
async def test_send_rejects_provider_ids_outside_history_parser_contract(
    origin_runtime,
    field_name: str,
    provider_id: str,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    request_id = uuid4()
    provider_result = {
        "id": "valid-message-id",
        "thread_id": "valid-thread-id",
    }
    provider_result[field_name] = provider_id

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: provider_result,
        deadline_seconds=1,
    )
    try:
        with pytest.raises(RuntimeError, match="^gmail_send_delivery_uncertain$"):
            await service.send(
                payload=_payload(request_id=request_id),
                request=_Request(),
                actor="hermes",
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    async with sessionmaker() as session:
        origin = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account.id,
                GmailMessageOrigin.request_id == request_id,
            )
        )
    assert origin.delivery_state == "delivery_uncertain"
    assert origin.failure_category == "malformed_provider"
    assert origin.gmail_message_id is None
    assert origin.gmail_thread_id is None


async def test_timeout_and_cancellation_become_uncertain_and_never_recall_provider(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def stalled(**_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)
        return {"id": "late-id", "thread_id": "late-thread"}

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=stalled,
        deadline_seconds=0.05,
    )
    request_id = uuid4()
    payload = _payload(request_id=request_id)
    try:
        with pytest.raises(RuntimeError, match="gmail_send_delivery_uncertain"):
            await service.send(payload=payload, request=_Request(), actor="hermes")
        with pytest.raises(GmailSendConflict) as unresolved:
            await service.send(payload=payload, request=_Request(), actor="hermes")
        assert unresolved.value.category == "gmail_send_reconciliation_required"
    finally:
        release.set()
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    assert calls == 1
    async with sessionmaker() as session:
        origin = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account.id,
                GmailMessageOrigin.request_id == request_id,
            )
        )
    assert origin.delivery_state == "delivery_uncertain"
    assert origin.failure_category == "provider_timeout"


async def test_history_success_committed_before_timeout_is_never_downgraded(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def accepted_but_stalled(**_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)
        return {
            "id": "history-proved-message",
            "thread_id": "history-proved-thread",
        }

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=accepted_but_stalled,
        deadline_seconds=0.5,
    )
    request_id = uuid4()
    payload = _payload(request_id=request_id)
    pending = asyncio.create_task(
        service.send(payload=payload, request=_Request(), actor="hermes")
    )
    try:
        assert await asyncio.to_thread(started.wait, 1)
        async with sessionmaker() as session:
            pending_origin = await session.scalar(
                sa.select(GmailMessageOrigin).where(
                    GmailMessageOrigin.request_id == request_id
                )
            )
        observed = await service.observe_history_sent(
            account_id=account.id,
            message=GmailMessageContent(
                message_id="history-proved-message",
                thread_id="history-proved-thread",
                label_ids=("SENT",),
                message_at=pending_origin.created_at,
                headers={
                    "subject": payload.subject,
                    "from": account.workspace_email,
                    "to": payload.to[0],
                    "cc": payload.cc[0],
                    "bcc": "",
                },
                # Match EmailMessage.set_content() wire semantics.
                body_text=f"{payload.body_text}\n",
            ),
        )
        assert observed.delivery_state == "succeeded"
        with pytest.raises(RuntimeError, match="gmail_send_delivery_uncertain"):
            await pending

        replay = await service.send(
            payload=payload,
            request=_Request(),
            actor="hermes",
        )
        assert replay.delivery_state == "succeeded"
        assert replay.replayed is True
    finally:
        release.set()
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert calls == 1
    async with sessionmaker() as session:
        origin = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account.id,
                GmailMessageOrigin.request_id == request_id,
            )
        )
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt).where(
                        GmailMessageReceipt.account_id == account.id
                    )
                )
            ).all()
        )
    assert origin.delivery_state == "succeeded"
    assert origin.version == 2
    assert origin.failure_category is None
    assert origin.gmail_message_id == "history-proved-message"
    assert origin.gmail_thread_id == "history-proved-thread"
    assert len(receipts) == 1
    assert receipts[0].gmail_message_id == "history-proved-message"


async def test_provider_identity_conflict_after_history_success_is_quarantined(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    started = threading.Event()
    release_provider = threading.Event()
    quarantine_ready = asyncio.Event()
    release_quarantine = asyncio.Event()
    calls = 0

    def accepted_with_different_identity(**_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        release_provider.wait(timeout=5)
        return {
            "id": "provider-authoritative-message-b",
            "thread_id": "provider-authoritative-thread-b",
        }

    executor = BoundedProviderExecutor(max_workers=1)

    async def before_quarantine_commit() -> None:
        quarantine_ready.set()
        await release_quarantine.wait()

    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=accepted_with_different_identity,
        deadline_seconds=3,
        before_finalize_commit=before_quarantine_commit,
    )
    request_id = uuid4()
    payload = _payload(request_id=request_id)
    pending = asyncio.create_task(
        service.send(payload=payload, request=_Request(), actor="hermes")
    )
    try:
        assert await asyncio.to_thread(started.wait, 1)
        async with sessionmaker() as session:
            intent = await session.scalar(
                sa.select(GmailMessageOrigin).where(
                    GmailMessageOrigin.request_id == request_id
                )
            )
        history_message = GmailMessageContent(
            message_id="history-message-a",
            thread_id="history-thread-a",
            label_ids=("SENT",),
            message_at=intent.created_at,
            headers={
                "subject": payload.subject,
                "from": account.workspace_email,
                "to": payload.to[0],
                "cc": payload.cc[0],
                "bcc": "",
            },
            body_text=f"{payload.body_text}\n",
        )
        history = await service.observe_history_sent(
            account_id=account.id,
            message=history_message,
        )
        assert history.delivery_state == "succeeded"
        assert history.message_id == "history-message-a"

        release_provider.set()
        await asyncio.wait_for(quarantine_ready.wait(), timeout=2)
        replay_task = asyncio.create_task(
            service.send(
                payload=payload,
                request=_Request(),
                actor="hermes",
            )
        )
        await asyncio.sleep(0.05)
        assert replay_task.done() is False
        assert calls == 1
        release_quarantine.set()
        with pytest.raises(RuntimeError, match="gmail_send_delivery_uncertain"):
            await pending

        history_replay = await service.observe_history_sent(
            account_id=account.id,
            message=history_message,
        )
        assert history_replay.quarantine_category == "provider_identity_conflict"
        assert history_replay.failure_category == "provider_identity_conflict"
        with pytest.raises(GmailSendConflict) as replay_blocked:
            await replay_task
        assert replay_blocked.value.category == "gmail_send_quarantined"
    finally:
        release_provider.set()
        release_quarantine.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert calls == 1
    async with sessionmaker() as session:
        stored = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account.id,
                GmailMessageOrigin.request_id == request_id,
            )
        )
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt).where(
                        GmailMessageReceipt.account_id == account.id
                    )
                )
            ).all()
        )
    assert stored.delivery_state == "succeeded"
    assert stored.gmail_message_id == "history-message-a"
    assert stored.gmail_thread_id == "history-thread-a"
    assert stored.quarantine_category == "provider_identity_conflict"
    assert stored.failure_category == "provider_identity_conflict"
    assert stored.version == 3
    assert [(row.gmail_message_id, row.gmail_thread_id) for row in receipts] == [
        ("history-message-a", "history-thread-a")
    ]


async def test_actual_asyncio_cancellation_after_intent_commit_marks_uncertain(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def stalled(**_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)
        return {"id": "cancelled-late", "thread_id": "cancelled-thread"}

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=stalled,
        deadline_seconds=3,
    )
    request_id = uuid4()
    payload = _payload(request_id=request_id)
    task = asyncio.create_task(
        service.send(payload=payload, request=_Request(), actor="hermes")
    )
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with sessionmaker() as session:
            origin = await session.scalar(
                sa.select(GmailMessageOrigin).where(
                    GmailMessageOrigin.account_id == account.id,
                    GmailMessageOrigin.request_id == request_id,
                )
            )
        assert origin.delivery_state == "delivery_uncertain"
        assert origin.failure_category == "provider_cancelled"
        with pytest.raises(GmailSendConflict) as unresolved:
            await service.send(payload=payload, request=_Request(), actor="hermes")
        assert unresolved.value.category == "gmail_send_reconciliation_required"
    finally:
        release.set()
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    assert calls == 1


async def test_inflight_sending_cannot_be_reconciled_not_delivered_or_retried(
    origin_runtime,
) -> None:
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    entered = threading.Event()
    release = threading.Event()
    first_calls = 0
    second_calls = 0

    def first_transport(**_kwargs):
        nonlocal first_calls
        first_calls += 1
        entered.set()
        release.wait(timeout=5)
        return {"id": "late-first", "thread_id": "late-first-thread"}

    def second_transport(**_kwargs):
        nonlocal second_calls
        second_calls += 1
        raise AssertionError("an in-flight predecessor must never release a retry")

    first_executor = BoundedProviderExecutor(max_workers=1)
    second_executor = BoundedProviderExecutor(max_workers=1)
    first_service = GmailOriginService(
        engine=engine,
        provider_executor=first_executor,
        transport=first_transport,
        deadline_seconds=3,
    )
    second_service = GmailOriginService(
        engine=engine,
        provider_executor=second_executor,
        transport=second_transport,
        deadline_seconds=1,
    )
    request_id = uuid4()
    pending = asyncio.create_task(
        first_service.send(
            payload=_payload(request_id=request_id),
            request=_Request(),
            actor="hermes",
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        with pytest.raises(GmailSendConflict) as premature:
            await second_service.mark_not_delivered(
                account_id=account.id,
                request_id=request_id,
                expected_state="sending",
                expected_version=1,
                reason="Provider call is still live and cannot be released.",
                request=_Request(),
                actor="admin:1",
            )
        assert premature.value.category == "gmail_reconciliation_state_conflict"
        with pytest.raises(GmailSendConflict) as retry:
            await second_service.send(
                payload=_payload(
                    request_id=uuid4(),
                    retry_of_request_id=request_id,
                ),
                request=_Request(),
                actor="hermes",
            )
        assert retry.value.category == "gmail_send_retry_parent_invalid"
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    finally:
        if not pending.done():
            pending.cancel()
            try:
                await pending
            except (asyncio.CancelledError, RuntimeError):
                pass
        release.set()
        await first_executor.wait_for_tracked_calls()
        await second_executor.wait_for_tracked_calls()
        first_executor.shutdown()
        second_executor.shutdown()

    assert first_calls == 1
    assert second_calls == 0


async def test_tx2_commit_failure_after_provider_acceptance_marks_uncertain_fresh_session(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    calls = 0

    def transport(**_kwargs):
        nonlocal calls
        calls += 1
        return {"id": "accepted-but-not-finalized", "thread_id": "provider-thread"}

    finalize_attempts = 0

    async def fail_before_finalize_commit():
        nonlocal finalize_attempts
        finalize_attempts += 1
        raise RuntimeError("synthetic finalize commit failure")

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
        before_finalize_commit=fail_before_finalize_commit,
    )
    request_id = uuid4()
    try:
        with pytest.raises(RuntimeError, match="gmail_send_delivery_uncertain"):
            await service.send(
                payload=_payload(request_id=request_id),
                request=_Request(),
                actor="hermes",
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    assert calls == 1
    assert finalize_attempts == 1
    async with sessionmaker() as session:
        origin = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account.id,
                GmailMessageOrigin.request_id == request_id,
            )
        )
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
    assert origin.delivery_state == "delivery_uncertain"
    assert origin.failure_category == "post_provider_persistence"
    assert origin.gmail_message_id is None
    assert receipt_count == 0


async def test_malformed_provider_success_payload_becomes_uncertain(origin_runtime) -> None:
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: {"id": "", "thread_id": ""},
        deadline_seconds=1,
    )
    request_id = uuid4()
    try:
        with pytest.raises(RuntimeError, match="gmail_send_delivery_uncertain"):
            await service.send(
                payload=_payload(request_id=request_id),
                request=_Request(),
                actor="hermes",
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    async with sessionmaker() as session:
        origin = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account.id,
                GmailMessageOrigin.request_id == request_id,
            )
        )
    assert origin.delivery_state == "delivery_uncertain"
    assert origin.failure_category == "malformed_provider"


async def test_stale_sending_reconciliation_marks_uncertain_without_provider_call(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    calls = 0

    def transport(**_kwargs):
        nonlocal calls
        calls += 1
        return {"id": "never", "thread_id": "never"}

    executor = BoundedProviderExecutor(max_workers=1)
    now = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
        clock=lambda: now,
        sending_stale_after_seconds=120,
    )
    payload = _payload(request_id=uuid4())
    intent = await service.claim_intent_only(
        payload=payload, request=_Request(), actor="hermes"
    )
    with pytest.raises(GmailSendConflict) as fresh:
        await service.reconcile_stale_sending(
            account_id=account.id,
            request_id=payload.request_id,
            expected_version=1,
            reason="A fresh intent must not be taken over.",
        )
    assert fresh.value.category == "gmail_send_still_in_flight"
    async with sessionmaker() as session:
        unchanged = await session.get(GmailMessageOrigin, intent.id)
        assert unchanged.delivery_state == "sending"
        unchanged.created_at = now - timedelta(seconds=121)
        unchanged.updated_at = now - timedelta(seconds=121)
        await session.commit()

    reconciled = await service.reconcile_stale_sending(
        account_id=account.id,
        request_id=payload.request_id,
        expected_version=1,
        reason="Worker restart found a committed stale intent.",
    )
    executor.shutdown()
    assert reconciled.delivery_state == "delivery_uncertain"
    assert reconciled.failure_category == "stale_sending"
    assert reconciled.version == 2
    assert calls == 0
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageOrigin, intent.id)
    assert stored.delivery_state == "delivery_uncertain"


async def test_two_first_intents_same_hash_allow_one_commit_and_one_provider_call(
    origin_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    barrier_ready = asyncio.Event()
    barrier_release = asyncio.Event()
    barrier_lock = asyncio.Lock()
    arrived = 0
    calls = 0

    def transport(**_kwargs):
        nonlocal calls
        calls += 1
        return {"id": f"race-message-{calls}", "thread_id": "race-thread"}

    async def before_intent_flush():
        nonlocal arrived
        async with barrier_lock:
            arrived += 1
            if arrived == 2:
                barrier_ready.set()
        await barrier_release.wait()

    executor = BoundedProviderExecutor(max_workers=2)
    first_service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=2,
        before_intent_flush=before_intent_flush,
    )
    second_service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=2,
        before_intent_flush=before_intent_flush,
    )
    first = asyncio.create_task(
        first_service.send(
            payload=_payload(request_id=uuid4()), request=_Request(), actor="hermes"
        )
    )
    second = asyncio.create_task(
        second_service.send(
            payload=_payload(request_id=uuid4()), request=_Request(), actor="hermes"
        )
    )
    try:
        await asyncio.wait_for(barrier_ready.wait(), timeout=2)
        assert arrived == 2
        barrier_release.set()
        results = await asyncio.wait_for(
            asyncio.gather(first, second, return_exceptions=True), timeout=3
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    successes = [item for item in results if not isinstance(item, BaseException)]
    conflicts = [item for item in results if isinstance(item, GmailSendConflict)]
    assert len(successes) == 1
    assert successes[0].delivery_state == "succeeded"
    assert len(conflicts) == 1
    assert conflicts[0].category == "gmail_send_reconciliation_required"
    assert calls == 1
    async with sessionmaker() as session:
        origins = list(
            (
                await session.scalars(
                    sa.select(GmailMessageOrigin).where(
                        GmailMessageOrigin.account_id == account.id
                    )
                )
            ).all()
        )
        intent_audits = list(
            (
                await session.scalars(
                    sa.select(AgentActionAudit).where(
                        AgentActionAudit.action_id
                        == "workspace.gmail.send.intent"
                    )
                )
            ).all()
        )
    assert len(origins) == 1
    assert len(intent_audits) == 1
    assert origins[0].action_audit_id == intent_audits[0].id


async def test_only_predecessor_bound_successor_after_not_delivered_can_send_once(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    calls = 0

    def transport(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("provider rejected before delivery")
        return {
            "id": f"retry-message-{calls}",
            "thread_id": f"retry-thread-{calls}",
        }

    executor = BoundedProviderExecutor(max_workers=2)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    parent_request = uuid4()
    try:
        with pytest.raises(RuntimeError, match="gmail_send_delivery_uncertain"):
            await service.send(
                payload=_payload(request_id=parent_request),
                request=_Request(),
                actor="hermes",
            )
        with pytest.raises(GmailSendConflict) as fresh:
            await service.send(
                payload=_payload(request_id=uuid4()), request=_Request(), actor="hermes"
            )
        assert fresh.value.category == "gmail_send_reconciliation_required"
        with pytest.raises(GmailSendConflict) as unresolved_parent:
            await service.send(
                payload=_payload(
                    request_id=uuid4(), retry_of_request_id=parent_request
                ),
                request=_Request(),
                actor="hermes",
            )
        assert unresolved_parent.value.category == "gmail_send_retry_parent_invalid"

        parent = await service.mark_not_delivered(
            account_id=account.id,
            request_id=parent_request,
            expected_state="delivery_uncertain",
            expected_version=2,
            reason="Provider confirmed no accepted message.",
            request=_Request(),
            actor="admin:1",
        )
        assert parent.reconciled_outcome == "not_delivered"
        assert parent.version == 3

        with pytest.raises(GmailSendConflict) as unbound:
            await service.send(
                payload=_payload(request_id=uuid4()), request=_Request(), actor="hermes"
            )
        assert unbound.value.category == "gmail_send_retry_parent_required"
        with pytest.raises(GmailSendConflict) as unrelated:
            await service.send(
                payload=_payload(
                    request_id=uuid4(), retry_of_request_id=uuid4()
                ),
                request=_Request(),
                actor="hermes",
            )
        assert unrelated.value.category == "gmail_send_retry_parent_invalid"
        with pytest.raises(GmailSendConflict) as mismatched_hash:
            await service.send(
                payload=_payload(
                    request_id=uuid4(),
                    retry_of_request_id=parent_request,
                    subject="A different canonical send",
                ),
                request=_Request(),
                actor="hermes",
            )
        assert mismatched_hash.value.category == "gmail_send_retry_parent_mismatch"

        successor_request = uuid4()
        successor = await service.send(
            payload=_payload(
                request_id=successor_request,
                retry_of_request_id=parent_request,
            ),
            request=_Request(),
            actor="hermes",
        )
        assert successor.delivery_state == "succeeded"
        with pytest.raises(GmailSendConflict) as second_successor:
            await service.send(
                payload=_payload(
                    request_id=uuid4(), retry_of_request_id=parent_request
                ),
                request=_Request(),
                actor="hermes",
            )
        assert second_successor.value.category == "gmail_send_retry_parent_used"
        with pytest.raises(GmailSendConflict) as delivered_parent:
            await service.send(
                payload=_payload(
                    request_id=uuid4(), retry_of_request_id=successor_request
                ),
                request=_Request(),
                actor="hermes",
            )
        assert delivered_parent.value.category == "gmail_send_retry_parent_invalid"

        later_independent = await service.send(
            payload=_payload(request_id=uuid4()),
            request=_Request(),
            actor="hermes",
        )
        assert later_independent.delivery_state == "succeeded"
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    assert calls == 3
    async with sessionmaker() as session:
        successor_row = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.request_id == successor_request
            )
        )
        parent_row = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.request_id == parent_request
            )
        )
    assert successor_row.retry_of_origin_id == parent_row.id
    async with sessionmaker() as session:
        reconciliation_audit = await session.scalar(
            sa.select(__import__("models.agent_action_audit", fromlist=["AgentActionAudit"]).AgentActionAudit)
            .where(
                __import__("models.agent_action_audit", fromlist=["AgentActionAudit"]).AgentActionAudit.action_id
                == "workspace.gmail.send.reconcile.not_delivered"
            )
        )
    assert reconciliation_audit.actor == "admin:1"
    assert "Provider confirmed" not in reconciliation_audit.request_meta_json


async def test_retry_parent_from_another_account_is_never_resolved_globally(
    origin_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailSyncAccount
    from services.gmail_origin_service import (
        GmailOriginService,
        GmailSendConflict,
        canonicalize_gmail_send,
    )
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    bound_account = await _seed_account(sessionmaker)
    parent_request_id = uuid4()
    retry_payload = _payload(
        request_id=uuid4(),
        retry_of_request_id=parent_request_id,
    )
    canonical = canonicalize_gmail_send(
        account_email=bound_account.workspace_email,
        payload=retry_payload,
        intended_thread_id=None,
    )
    async with sessionmaker() as session:
        other_account = GmailSyncAccount(
            workspace_email="other-account@example.test",
            committed_history_id="200",
            mode="shadow",
        )
        audit = AgentActionAudit(
            actor="hermes",
            action_id="workspace.gmail.send.intent",
            method="POST",
            path=_Request.url.path,
            status_code=202,
            allowed=True,
            request_meta_json="{}",
            response_meta_json="{}",
        )
        session.add_all([other_account, audit])
        await session.flush()
        session.add(
            GmailMessageOrigin(
                account_id=other_account.id,
                request_id=parent_request_id,
                canonical_send_hash=canonical.canonical_send_hash,
                canonical_envelope_hash=canonical.canonical_envelope_hash,
                canonical_body_hash=canonical.canonical_body_hash,
                origin_kind="sydney_client_send",
                delivery_state="delivery_uncertain",
                reconciled_outcome="not_delivered",
                version=3,
                action_audit_id=audit.id,
                failure_category="provider_timeout",
                failure_message="Gmail delivery could not be verified.",
                reconciled_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
            )
        )
        await session.commit()
        before_origins = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageOrigin)
        )
        before_audits = await session.scalar(
            sa.select(sa.func.count()).select_from(AgentActionAudit)
        )

    provider_calls = 0

    def transport(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("cross-account retry must never call Gmail")

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    try:
        with pytest.raises(GmailSendConflict) as rejected:
            await service.send(
                payload=retry_payload,
                request=_Request(),
                actor="hermes",
            )
        assert rejected.value.category == "gmail_send_retry_parent_invalid"
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    async with sessionmaker() as session:
        after_origins = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageOrigin)
        )
        after_audits = await session.scalar(
            sa.select(sa.func.count()).select_from(AgentActionAudit)
        )
    assert after_origins == before_origins
    assert after_audits == before_audits
    assert provider_calls == 0


async def test_two_racing_successors_after_not_delivered_yield_one_provider_call(
    origin_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    calls = 0

    def initial_transport(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("known provider rejection")
        return {"id": f"successor-{calls}", "thread_id": "successor-thread"}

    executor = BoundedProviderExecutor(max_workers=2)
    parent_service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=initial_transport,
        deadline_seconds=2,
    )
    parent_request = uuid4()
    with pytest.raises(RuntimeError, match="gmail_send_delivery_uncertain"):
        await parent_service.send(
            payload=_payload(request_id=parent_request),
            request=_Request(),
            actor="hermes",
        )
    await parent_service.mark_not_delivered(
        account_id=account.id,
        request_id=parent_request,
        expected_state="delivery_uncertain",
        expected_version=2,
        reason="Verified not delivered.",
        request=_Request(),
        actor="admin:1",
    )
    async with sessionmaker() as session:
        intent_audits_before_race = await session.scalar(
            sa.select(sa.func.count()).select_from(AgentActionAudit).where(
                AgentActionAudit.action_id == "workspace.gmail.send.intent"
            )
        )

    ready = asyncio.Event()
    release = asyncio.Event()
    mutex = asyncio.Lock()
    arrived = 0

    async def before_intent_flush():
        nonlocal arrived
        async with mutex:
            arrived += 1
            if arrived == 2:
                ready.set()
        await release.wait()

    services = [
        GmailOriginService(
            engine=engine,
            provider_executor=executor,
            transport=initial_transport,
            deadline_seconds=2,
            before_intent_flush=before_intent_flush,
        )
        for _ in range(2)
    ]
    tasks = [
        asyncio.create_task(
            item.send(
                payload=_payload(
                    request_id=uuid4(), retry_of_request_id=parent_request
                ),
                request=_Request(),
                actor="hermes",
            )
        )
        for item in services
    ]
    try:
        await asyncio.wait_for(ready.wait(), timeout=2)
        release.set()
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=3
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    successes = [item for item in results if not isinstance(item, BaseException)]
    conflicts = [item for item in results if isinstance(item, GmailSendConflict)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].category == "gmail_send_retry_parent_used"
    assert calls == 2
    async with sessionmaker() as session:
        origins = list(
            (
                await session.scalars(
                    sa.select(GmailMessageOrigin)
                    .where(GmailMessageOrigin.account_id == account.id)
                    .order_by(GmailMessageOrigin.created_at)
                )
            ).all()
        )
        intent_audits_after_race = await session.scalar(
            sa.select(sa.func.count()).select_from(AgentActionAudit).where(
                AgentActionAudit.action_id == "workspace.gmail.send.intent"
            )
        )
    assert len(origins) == 2
    assert intent_audits_after_race == intent_audits_before_race + 1
    assert len({row.action_audit_id for row in origins}) == 2


@pytest.mark.parametrize("audit_mode", ["raises", "none", "wrong_type"])
async def test_not_delivered_audit_failure_rolls_back_and_keeps_retry_gate_closed(
    origin_runtime,
    audit_mode: str,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    provider_calls = 0

    def transport(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {"id": "must-not-send", "thread_id": "must-not-send"}

    executor = BoundedProviderExecutor(max_workers=1)
    normal = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    request_id = uuid4()
    intent = await normal.claim_intent_only(
        payload=_payload(request_id=request_id), request=_Request(), actor="hermes"
    )
    await normal.mark_delivery_uncertain(
        origin_id=intent.id, expected_version=1, category="provider_timeout"
    )

    async def failing_audit(*_args, **_kwargs):
        if audit_mode == "raises":
            raise RuntimeError("private audit storage failure")
        if audit_mode == "wrong_type":
            return object()
        return None

    failing = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
        transactional_audit_writer=failing_audit,
    )
    with pytest.raises(RuntimeError, match="^gmail_reconciliation_audit_failed$"):
        await failing.mark_not_delivered(
            account_id=account.id,
            request_id=request_id,
            expected_state="delivery_uncertain",
            expected_version=2,
            reason="Provider verified that no message was accepted.",
            request=_Request(),
            actor="admin:1",
        )
    for expected_state, expected_version in (
        ("sending", 2),
        ("delivery_uncertain", 1),
    ):
        with pytest.raises(GmailSendConflict) as stale:
            await normal.mark_not_delivered(
                account_id=account.id,
                request_id=request_id,
                expected_state=expected_state,
                expected_version=expected_version,
                reason="Stale reconciliation must fail.",
                request=_Request(),
                actor="admin:1",
            )
        assert stale.value.category == "gmail_reconciliation_state_conflict"

    with pytest.raises(GmailSendConflict) as successor:
        await normal.send(
            payload=_payload(
                request_id=uuid4(), retry_of_request_id=request_id
            ),
            request=_Request(),
            actor="hermes",
        )
    assert successor.value.category == "gmail_send_retry_parent_invalid"
    assert provider_calls == 0
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageOrigin, intent.id)
        reconciliation_audits = await session.scalar(
            sa.select(sa.func.count()).select_from(AgentActionAudit).where(
                AgentActionAudit.action_id.like(
                    "workspace.gmail.send.reconcile.not_delivered%"
                )
            )
        )
    assert stored.delivery_state == "delivery_uncertain"
    assert stored.version == 2
    assert stored.reconciled_outcome is None
    assert reconciliation_audits == 0


@pytest.mark.parametrize("candidate_outcome", ["verified", "quarantine"])
@pytest.mark.parametrize("audit_mode", ["raises", "none", "wrong_type"])
async def test_delivered_reconciliation_audit_failure_rolls_back_all_state(
    origin_runtime,
    candidate_outcome: str,
    audit_mode: str,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent, GmailProfile
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    send_calls = 0

    def transport(**_kwargs):
        nonlocal send_calls
        send_calls += 1
        return {"id": "must-not-send", "thread_id": "must-not-send"}

    executor = BoundedProviderExecutor(max_workers=1)
    normal = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    raw_canary = "private-reconciliation-raw-body-canary"
    payload = _payload(request_id=uuid4(), body_text=raw_canary)
    intent = await normal.claim_intent_only(
        payload=payload, request=_Request(), actor="hermes"
    )
    await normal.mark_delivery_uncertain(
        origin_id=intent.id, expected_version=1, category="provider_timeout"
    )

    async def failing_audit(*_args, **_kwargs):
        gc.collect()
        assert raw_refs
        assert all(reference() is None for reference in raw_refs)
        if audit_mode == "raises":
            raise RuntimeError("private reconciliation audit failure")
        if audit_mode == "wrong_type":
            return object()
        return None

    failing = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
        transactional_audit_writer=failing_audit,
    )

    raw_refs: list[weakref.ReferenceType] = []

    def fetcher(**kwargs):
        if kwargs["kind"] == "profile":
            return GmailProfile(
                email_address=account.workspace_email,
                history_id="1000",
            )
        content = GmailMessageContent(
            message_id="audit-candidate-message",
            thread_id="audit-candidate-thread",
            label_ids=("SENT",),
            message_at=intent.created_at,
            headers={
                "subject": payload.subject,
                "from": account.workspace_email,
                "to": (
                    payload.to[0]
                    if candidate_outcome == "verified"
                    else "wrong@example.test"
                ),
                "cc": payload.cc[0],
                "bcc": "",
            },
            body_text=payload.body_text,
        )
        raw_refs.append(weakref.ref(content))
        return content

    try:
        with pytest.raises(
            RuntimeError, match="^gmail_reconciliation_audit_failed$"
        ) as raised:
            await failing.reconcile_delivered_candidate(
                account_id=account.id,
                request_id=payload.request_id,
                expected_state="delivery_uncertain",
                expected_version=2,
                reason="Atomic audit failure test.",
                candidate_message_id="audit-candidate-message",
                candidate_thread_id="audit-candidate-thread",
                fetcher=fetcher,
                request=_Request(),
                actor="admin:1",
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert send_calls == 0
    assert raw_canary not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__suppress_context__ is True
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageOrigin, intent.id)
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
        reconciliation_audits = await session.scalar(
            sa.select(sa.func.count()).select_from(AgentActionAudit).where(
                AgentActionAudit.action_id.like(
                    "workspace.gmail.send.reconcile.delivered%"
                )
            )
        )
    assert stored.delivery_state == "delivery_uncertain"
    assert stored.version == 2
    assert stored.gmail_message_id is None
    assert stored.gmail_thread_id is None
    assert stored.reconciled_outcome is None
    assert stored.quarantine_category is None
    assert stored.quarantine_evidence is None
    assert receipt_count == 0
    assert reconciliation_audits == 0


async def test_history_observation_dedupes_route_origin_in_both_finalize_orders(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: {"id": "unused", "thread_id": "unused"},
        deadline_seconds=1,
    )
    payload = _payload(request_id=uuid4())
    canonical = service.canonical_for_account(account.workspace_email, payload)
    try:
        intent = await service.claim_intent_only(
            payload=payload, request=_Request(), actor="hermes"
        )
        observed = GmailMessageContent(
            message_id="history-first-message",
            thread_id="history-first-thread",
            label_ids=("SENT",),
            message_at=intent.created_at,
            headers={
                "subject": payload.subject,
                "from": account.workspace_email,
                "to": payload.to[0],
                "cc": payload.cc[0],
                "bcc": "",
            },
            body_text=payload.body_text,
        )
        history_result = await service.observe_history_sent(
            account_id=account.id,
            message=observed,
        )
        finalized = await service.finalize_success(
            origin_id=intent.id,
            expected_version=1,
            message_id="history-first-message",
            thread_id="history-first-thread",
        )
        assert history_result.origin_id == intent.id
        assert finalized.origin_id == intent.id
        assert finalized.replayed is True
        assert canonical.canonical_send_hash == intent.canonical_send_hash

        provider_first_payload = _payload(request_id=uuid4())
        provider_first_intent = await service.claim_intent_only(
            payload=provider_first_payload,
            request=_Request(),
            actor="hermes",
        )
        provider_first = await service.finalize_success(
            origin_id=provider_first_intent.id,
            expected_version=1,
            message_id="provider-first-message",
            thread_id="provider-first-thread",
        )
        provider_first_observed = GmailMessageContent(
            message_id="provider-first-message",
            thread_id="provider-first-thread",
            label_ids=("SENT",),
            message_at=datetime(2026, 8, 21, 14, 30, tzinfo=UTC),
            headers={
                "subject": provider_first_payload.subject,
                "from": account.workspace_email,
                "to": provider_first_payload.to[0],
                "cc": provider_first_payload.cc[0],
                "bcc": "",
            },
            body_text=provider_first_payload.body_text,
        )
        after_history = await service.observe_history_sent(
            account_id=account.id,
            message=provider_first_observed,
        )
        assert provider_first.delivery_state == "succeeded"
        assert after_history.origin_id == provider_first_intent.id
        assert after_history.replayed is True

        human_message = GmailMessageContent(
            message_id="human-history-message",
            thread_id="human-history-thread",
            label_ids=("SENT",),
                message_at=intent.created_at,
            headers={
                "subject": "Human sent",
                "from": account.workspace_email,
                "to": "another@example.test",
            },
            body_text="A manual message.",
        )
        human = await service.observe_history_sent(
            account_id=account.id,
            message=human_message,
        )
        replay = await service.observe_history_sent(
            account_id=account.id,
            message=human_message,
        )
    finally:
        executor.shutdown()

    assert human.origin_kind == "human_send"
    assert human.delivery_state == "succeeded"
    assert human.request_id is None
    assert replay.origin_id == human.origin_id
    async with sessionmaker() as session:
        origin_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account.id
            )
        )
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
    assert origin_count == 3
    assert receipt_count == 3


async def test_history_replay_same_message_different_thread_fails_without_mutation(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History must never send"),
        deadline_seconds=1,
    )
    message_at = datetime.now(tz=UTC)

    def message(thread_id: str) -> GmailMessageContent:
        return GmailMessageContent(
            message_id="immutable-history-message",
            thread_id=thread_id,
            label_ids=("SENT",),
            message_at=message_at,
            headers={
                "subject": "Immutable History identity",
                "from": account.workspace_email,
                "to": "client@example.test",
            },
            body_text="The provider thread identity must never change.",
        )

    try:
        first = await service.observe_history_sent(
            account_id=account.id,
            message=message("immutable-thread-a"),
        )
        with pytest.raises(GmailSendConflict) as raised:
            await service.observe_history_sent(
                account_id=account.id,
                message=message("immutable-thread-b"),
            )
    finally:
        executor.shutdown()

    assert raised.value.category == "gmail_send_provider_identity_conflict"
    async with sessionmaker() as session:
        stored_origin = await session.get(GmailMessageOrigin, first.origin_id)
        stored_receipt = await session.scalar(
            sa.select(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id,
                GmailMessageReceipt.gmail_message_id == "immutable-history-message",
            )
        )
    assert stored_origin.gmail_thread_id == "immutable-thread-a"
    assert stored_origin.version == first.version
    assert stored_receipt.gmail_thread_id == "immutable-thread-a"


async def test_history_replay_rejects_existing_receipt_thread_mismatch(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History must never send"),
        deadline_seconds=1,
    )
    message = GmailMessageContent(
        message_id="receipt-thread-mismatch-message",
        thread_id="receipt-thread-a",
        label_ids=("SENT",),
        message_at=datetime.now(tz=UTC),
        headers={
            "subject": "Receipt identity",
            "from": account.workspace_email,
            "to": "client@example.test",
        },
        body_text="Receipt identity must be immutable too.",
    )
    first = await service.observe_history_sent(
        account_id=account.id,
        message=message,
    )
    async with sessionmaker() as session:
        receipt = await session.scalar(
            sa.select(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id,
                GmailMessageReceipt.gmail_message_id == message.message_id,
            )
        )
        receipt.gmail_thread_id = "receipt-thread-corrupt"
        await session.commit()

    try:
        with pytest.raises(GmailSendConflict) as raised:
            await service.observe_history_sent(
                account_id=account.id,
                message=message,
            )
    finally:
        executor.shutdown()

    assert raised.value.category == "gmail_send_provider_identity_conflict"
    async with sessionmaker() as session:
        stored_origin = await session.get(GmailMessageOrigin, first.origin_id)
        stored_receipt = await session.scalar(
            sa.select(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id,
                GmailMessageReceipt.gmail_message_id == message.message_id,
            )
        )
    assert stored_origin.gmail_thread_id == "receipt-thread-a"
    assert stored_origin.version == first.version
    assert stored_receipt.gmail_thread_id == "receipt-thread-corrupt"


async def test_racing_history_same_message_different_threads_rejects_reload_mismatch(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    executor = BoundedProviderExecutor(max_workers=1)
    ready = asyncio.Event()
    release = asyncio.Event()
    mutex = asyncio.Lock()
    arrived = 0

    async def after_empty_selection() -> None:
        nonlocal arrived
        async with mutex:
            arrived += 1
            if arrived == 2:
                ready.set()
        await release.wait()

    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History must never send"),
        deadline_seconds=1,
        before_history_flush=after_empty_selection,
    )
    message_at = datetime.now(tz=UTC)

    def message(thread_id: str) -> GmailMessageContent:
        return GmailMessageContent(
            message_id="racing-history-message",
            thread_id=thread_id,
            label_ids=("SENT",),
            message_at=message_at,
            headers={
                "subject": "Racing History identity",
                "from": account.workspace_email,
                "to": "client@example.test",
            },
            body_text="Only one immutable provider identity may win.",
        )

    tasks = [
        asyncio.create_task(
            service.observe_history_sent(
                account_id=account.id,
                message=message("racing-thread-a"),
            )
        ),
        asyncio.create_task(
            service.observe_history_sent(
                account_id=account.id,
                message=message("racing-thread-b"),
            )
        ),
    ]
    try:
        await asyncio.wait_for(ready.wait(), timeout=2)
        release.set()
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=3,
        )
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        executor.shutdown()

    conflicts = [result for result in results if isinstance(result, GmailSendConflict)]
    successes = [result for result in results if not isinstance(result, BaseException)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].category == "gmail_send_provider_identity_conflict"
    async with sessionmaker() as session:
        origins = list(
            (
                await session.scalars(
                    sa.select(GmailMessageOrigin).where(
                        GmailMessageOrigin.account_id == account.id,
                        GmailMessageOrigin.gmail_message_id
                        == "racing-history-message",
                    )
                )
            ).all()
        )
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt).where(
                        GmailMessageReceipt.account_id == account.id,
                        GmailMessageReceipt.gmail_message_id
                        == "racing-history-message",
                    )
                )
            ).all()
        )
    assert len(origins) == len(receipts) == 1
    assert origins[0].gmail_thread_id == receipts[0].gmail_thread_id
    assert origins[0].gmail_thread_id in {"racing-thread-a", "racing-thread-b"}


async def test_history_observation_prefers_unresolved_successor_over_not_delivered_parent(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History must never send"),
        deadline_seconds=1,
    )
    parent_payload = _payload(request_id=uuid4())
    try:
        parent = await service.claim_intent_only(
            payload=parent_payload,
            request=_Request(),
            actor="hermes",
        )
        parent = await service.mark_delivery_uncertain(
            origin_id=parent.id,
            expected_version=1,
            category="provider_timeout",
        )
        await service.mark_not_delivered(
            account_id=account.id,
            request_id=parent.request_id,
            expected_state="delivery_uncertain",
            expected_version=parent.version,
            reason="Provider verified the predecessor was not delivered.",
            request=_Request(),
            actor="admin:1",
        )
        successor_payload = _payload(
            request_id=uuid4(),
            retry_of_request_id=parent.request_id,
        )
        successor = await service.claim_intent_only(
            payload=successor_payload,
            request=_Request(),
            actor="hermes",
        )
        successor = await service.mark_delivery_uncertain(
            origin_id=successor.id,
            expected_version=1,
            category="provider_timeout",
        )
        async with sessionmaker() as session:
            successor_row = await session.get(GmailMessageOrigin, successor.id)
        observed = await service.observe_history_sent(
            account_id=account.id,
            message=GmailMessageContent(
                message_id="successor-history-message",
                thread_id="successor-history-thread",
                label_ids=("SENT",),
                message_at=successor_row.created_at,
                headers={
                    "subject": successor_payload.subject,
                    "from": account.workspace_email,
                    "to": successor_payload.to[0],
                    "cc": successor_payload.cc[0],
                    "bcc": "",
                },
                body_text=successor_payload.body_text,
            ),
        )
    finally:
        executor.shutdown()

    assert observed.origin_id == successor.id
    async with sessionmaker() as session:
        stored_parent = await session.get(GmailMessageOrigin, parent.id)
        stored_successor = await session.get(
            GmailMessageOrigin,
            successor.id,
        )
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt).where(
                        GmailMessageReceipt.account_id == account.id
                    )
                )
            ).all()
        )
    assert stored_parent.reconciled_outcome == "not_delivered"
    assert stored_parent.delivery_state == "delivery_uncertain"
    assert stored_successor.delivery_state == "succeeded"
    assert stored_successor.gmail_message_id == "successor-history-message"
    assert [row.gmail_message_id for row in receipts] == [
        "successor-history-message"
    ]


async def test_history_reselects_successor_when_selected_parent_is_released(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    selected = asyncio.Event()
    release = asyncio.Event()

    async def after_history_selection() -> None:
        selected.set()
        await release.wait()

    executor = BoundedProviderExecutor(max_workers=1)
    normal = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History must never send"),
        deadline_seconds=1,
    )
    racing = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History must never send"),
        deadline_seconds=1,
        before_history_flush=after_history_selection,
    )
    parent_payload = _payload(request_id=uuid4(), subject="Selection race")
    parent = await normal.claim_intent_only(
        payload=parent_payload,
        request=_Request(),
        actor="hermes",
    )
    parent = await normal.mark_delivery_uncertain(
        origin_id=parent.id,
        expected_version=1,
        category="provider_timeout",
    )
    async with sessionmaker() as session:
        parent_row = await session.get(GmailMessageOrigin, parent.id)
        message_at = parent_row.created_at + timedelta(minutes=1)
    message = GmailMessageContent(
        message_id="selection-race-message",
        thread_id="selection-race-thread",
        label_ids=("SENT",),
        message_at=message_at,
        headers={
            "subject": parent_payload.subject,
            "from": account.workspace_email,
            "to": parent_payload.to[0],
            "cc": parent_payload.cc[0],
            "bcc": "",
        },
        body_text=parent_payload.body_text,
    )
    history_task = asyncio.create_task(
        racing.observe_history_sent(account_id=account.id, message=message)
    )
    successor = None
    try:
        await asyncio.wait_for(selected.wait(), timeout=2)
        await normal.mark_not_delivered(
            account_id=account.id,
            request_id=parent.request_id,
            expected_state="delivery_uncertain",
            expected_version=parent.version,
            reason="Provider verified the selected predecessor was not delivered.",
            request=_Request(),
            actor="admin:1",
        )
        successor_payload = _payload(
            request_id=uuid4(),
            retry_of_request_id=parent.request_id,
            subject=parent_payload.subject,
        )
        successor = await normal.claim_intent_only(
            payload=successor_payload,
            request=_Request(),
            actor="hermes",
        )
        successor = await normal.mark_delivery_uncertain(
            origin_id=successor.id,
            expected_version=1,
            category="provider_timeout",
        )
        release.set()
        observed = await asyncio.wait_for(history_task, timeout=3)
    finally:
        release.set()
        if not history_task.done():
            history_task.cancel()
            with suppress(asyncio.CancelledError):
                await history_task
        executor.shutdown()

    assert successor is not None
    assert observed.origin_id == successor.id
    async with sessionmaker() as session:
        stored_parent = await session.get(GmailMessageOrigin, parent.id)
        stored_successor = await session.get(GmailMessageOrigin, successor.id)
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt).where(
                        GmailMessageReceipt.account_id == account.id
                    )
                )
            ).all()
        )
    assert stored_parent.reconciled_outcome == "not_delivered"
    assert stored_parent.delivery_state == "delivery_uncertain"
    assert stored_parent.gmail_message_id is None
    assert stored_successor.delivery_state == "succeeded"
    assert stored_successor.gmail_message_id == message.message_id
    assert [row.gmail_message_id for row in receipts] == [message.message_id]


async def test_history_and_provider_finalize_race_converges_to_one_origin_and_receipt(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    executor = BoundedProviderExecutor(max_workers=1)
    ready = asyncio.Event()
    release = asyncio.Event()
    mutex = asyncio.Lock()
    arrived = 0

    async def before_convergence_flush():
        nonlocal arrived
        async with mutex:
            arrived += 1
            if arrived == 2:
                ready.set()
        await release.wait()

    base = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("race must not recall provider"),
        deadline_seconds=1,
    )
    payload = _payload(request_id=uuid4(), subject="Race convergence")
    intent = await base.claim_intent_only(
        payload=payload, request=_Request(), actor="hermes"
    )
    message = GmailMessageContent(
        message_id="race-converged-message",
        thread_id="race-converged-thread",
        label_ids=("SENT",),
        message_at=datetime(2026, 8, 21, 16, 0, tzinfo=UTC),
        headers={
            "subject": payload.subject,
            "from": account.workspace_email,
            "to": payload.to[0],
            "cc": payload.cc[0],
            "bcc": "",
        },
        body_text=payload.body_text,
    )
    history_service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("history must not send"),
        deadline_seconds=1,
        before_history_flush=before_convergence_flush,
    )
    finalize_service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("finalize must not resend"),
        deadline_seconds=1,
        before_finalize_flush=before_convergence_flush,
    )
    history_task = asyncio.create_task(
        history_service.observe_history_sent(account_id=account.id, message=message)
    )
    finalize_task = asyncio.create_task(
        finalize_service.finalize_success(
            origin_id=intent.id,
            expected_version=1,
            message_id=message.message_id,
            thread_id=message.thread_id,
        )
    )
    try:
        await asyncio.wait_for(ready.wait(), timeout=2)
        release.set()
        results = await asyncio.wait_for(
            asyncio.gather(history_task, finalize_task), timeout=3
        )
    finally:
        executor.shutdown()

    assert {result.origin_id for result in results} == {intent.id}
    async with sessionmaker() as session:
        origins = list(
            (
                await session.scalars(
                    sa.select(GmailMessageOrigin).where(
                        GmailMessageOrigin.account_id == account.id
                    )
                )
            ).all()
        )
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt).where(
                        GmailMessageReceipt.account_id == account.id
                    )
                )
            ).all()
        )
    assert len(origins) == 1
    assert origins[0].origin_kind == "sydney_client_send"
    assert origins[0].delivery_state == "succeeded"
    assert len(receipts) == 1
    assert receipts[0].gmail_message_id == message.message_id


@pytest.mark.parametrize(
    ("scenario", "category"),
    [
        ("wrong_profile", "candidate_account_mismatch"),
        ("missing_message", "candidate_message_missing"),
        ("wrong_message", "candidate_message_mismatch"),
        ("missing_sent", "candidate_not_sent"),
        ("candidate_thread", "candidate_thread_mismatch"),
        ("intended_thread", "candidate_intended_thread_mismatch"),
        ("from", "candidate_envelope_mismatch"),
        ("missing_from", "candidate_envelope_mismatch"),
        ("to", "candidate_envelope_mismatch"),
        ("cc", "candidate_envelope_mismatch"),
        ("bcc", "candidate_envelope_mismatch"),
        ("subject", "candidate_envelope_mismatch"),
        ("body", "candidate_body_mismatch"),
        ("old_time", "candidate_time_mismatch"),
        ("late_time", "candidate_time_mismatch"),
        ("ambiguous_mime", "candidate_mime_ambiguous"),
        ("truncated_body", "candidate_body_truncated"),
    ],
)
async def test_delivered_reconciliation_quarantines_unverified_candidates(
    origin_runtime,
    scenario: str,
    category: str,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import (
        GmailMessageContent,
        GmailProfile,
        GmailProviderFailure,
    )
    from services.gmail_origin_service import GmailOriginService, GmailSendConflict
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    sends = 0

    def transport(**_kwargs):
        nonlocal sends
        sends += 1
        return {"id": "must-not-send", "thread_id": "must-not-send"}

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    payload = _payload(request_id=uuid4())
    intent = await service.claim_intent_only(
        payload=payload, request=_Request(), actor="hermes"
    )
    await service.mark_delivery_uncertain(
        origin_id=intent.id,
        expected_version=1,
        category="provider_timeout",
    )
    if scenario == "intended_thread":
        async with sessionmaker() as session:
            stored = await session.get(GmailMessageOrigin, intent.id)
            stored.intended_thread_id = "bound-intended-thread"
            await session.commit()

    headers = {
        "subject": payload.subject,
        "from": account.workspace_email,
        "to": payload.to[0],
        "cc": payload.cc[0],
        "bcc": "",
    }
    message = GmailMessageContent(
        message_id="candidate-message",
        thread_id="candidate-thread",
        label_ids=("SENT",),
        message_at=intent.created_at,
        headers=headers,
        body_text=payload.body_text,
    )
    if scenario == "wrong_message":
        message.message_id = "wrong-returned-message"
    elif scenario == "missing_sent":
        message.label_ids = ("INBOX",)
    elif scenario == "candidate_thread":
        message.thread_id = "wrong-returned-thread"
    elif scenario == "missing_from":
        message.headers["from"] = ""
    elif scenario in {"from", "to", "cc", "bcc", "subject"}:
        message.headers[scenario] = f"wrong-{scenario}@example.test"
    elif scenario == "body":
        message.body_text = "wrong body private-canary"
    elif scenario == "old_time":
        message.message_at = intent.created_at - timedelta(minutes=5, seconds=1)
    elif scenario == "late_time":
        message.message_at = intent.created_at + timedelta(minutes=5, seconds=1)
    elif scenario == "ambiguous_mime":
        message.body_transport_compatible = False
    elif scenario == "truncated_body":
        # The bounded prefix is identical to the intent, but the provider told
        # us additional visible body bytes existed. A prefix is never exact
        # proof that this intent was delivered.
        message.body_truncated = True

    fetch_calls: list[dict] = []
    main_thread = threading.current_thread()

    def fetcher(**kwargs):
        fetch_calls.append({**kwargs, "thread": threading.current_thread()})
        assert kwargs["num_retries"] == 0
        if kwargs["kind"] == "profile":
            return GmailProfile(
                email_address=(
                    "wrong-account@example.test"
                    if scenario == "wrong_profile"
                    else account.workspace_email
                ),
                history_id="1000",
            )
        if scenario == "missing_message":
            raise GmailProviderFailure("message_not_found")
        return message

    try:
        result = await service.reconcile_delivered_candidate(
            account_id=account.id,
            request_id=payload.request_id,
            expected_state="delivery_uncertain",
            expected_version=2,
            reason="Operator verification attempt 1.",
            candidate_message_id="candidate-message",
            candidate_thread_id="candidate-thread",
            fetcher=fetcher,
            request=_Request(),
            actor="admin:1",
        )
        assert result.delivery_state == "delivery_uncertain"
        assert result.quarantine_category == category
        fetch_count_after_quarantine = len(fetch_calls)
        with pytest.raises(GmailSendConflict) as quarantined:
            await service.reconcile_delivered_candidate(
                account_id=account.id,
                request_id=payload.request_id,
                expected_state="delivery_uncertain",
                expected_version=result.version,
                reason="A second admin candidate must not bypass quarantine.",
                candidate_message_id="candidate-message",
                candidate_thread_id="candidate-thread",
                fetcher=fetcher,
                request=_Request(),
                actor="admin:1",
            )
        assert quarantined.value.category == "gmail_send_quarantined"
        assert len(fetch_calls) == fetch_count_after_quarantine

        async with sessionmaker() as session:
            audit_count_before_release = await session.scalar(
                sa.select(sa.func.count()).select_from(AgentActionAudit)
            )
        with pytest.raises(GmailSendConflict) as release_blocked:
            await service.mark_not_delivered(
                account_id=account.id,
                request_id=payload.request_id,
                expected_state="delivery_uncertain",
                expected_version=result.version,
                reason="Quarantined evidence cannot release a duplicate retry.",
                request=_Request(),
                actor="admin:1",
            )
        assert release_blocked.value.category == "gmail_send_quarantined"
        with pytest.raises(GmailSendConflict) as retry_blocked:
            await service.send(
                payload=_payload(
                    request_id=uuid4(),
                    retry_of_request_id=payload.request_id,
                ),
                request=_Request(),
                actor="hermes",
            )
        assert retry_blocked.value.category == "gmail_send_retry_parent_invalid"
        async with sessionmaker() as session:
            still_quarantined = await session.get(GmailMessageOrigin, intent.id)
            audit_count_after_release = await session.scalar(
                sa.select(sa.func.count()).select_from(AgentActionAudit)
            )
        assert still_quarantined.version == result.version
        assert still_quarantined.reconciled_outcome is None
        assert audit_count_after_release == audit_count_before_release

        with pytest.raises(GmailSendConflict) as blocked:
            await service.send(
                payload=_payload(request_id=uuid4()),
                request=_Request(),
                actor="hermes",
            )
        assert blocked.value.category == "gmail_send_reconciliation_required"

        genuine = GmailMessageContent(
            message_id=f"history-genuine-{scenario}",
            thread_id=(
                "bound-intended-thread"
                if scenario == "intended_thread"
                else f"history-thread-{scenario}"
            ),
            label_ids=("SENT",),
            message_at=intent.created_at,
            headers={
                "subject": payload.subject,
                "from": account.workspace_email,
                "to": payload.to[0],
                "cc": payload.cc[0],
                "bcc": "",
            },
            body_text=payload.body_text,
        )
        recovered = await service.observe_history_sent(
            account_id=account.id,
            message=genuine,
        )
        replay = await service.observe_history_sent(
            account_id=account.id,
            message=genuine,
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    assert sends == 0
    assert fetch_calls
    assert all(call["thread"] is not main_thread for call in fetch_calls)
    expected_per_attempt = 1 if scenario == "wrong_profile" else 2
    assert len(fetch_calls) == expected_per_attempt
    assert recovered.origin_id == intent.id
    assert replay.origin_id == intent.id
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageOrigin, intent.id)
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt).where(
                        GmailMessageReceipt.account_id == account.id
                    )
                )
            ).all()
        )
        audits = list(
            (
                await session.scalars(
                    sa.select(AgentActionAudit)
                    .where(
                        AgentActionAudit.action_id
                        == "workspace.gmail.send.reconcile.delivered.quarantine"
                    )
                    .order_by(AgentActionAudit.id)
                )
            ).all()
        )
    assert stored.delivery_state == "succeeded"
    assert stored.gmail_message_id == genuine.message_id
    assert stored.quarantine_evidence == "Candidate Gmail message did not verify."
    assert [row.gmail_message_id for row in receipts] == [genuine.message_id]
    assert len(audits) == 1
    assert all(row.actor == "admin:1" and row.allowed is False for row in audits)
    serialized_audits = "".join(
        row.request_meta_json + row.response_meta_json for row in audits
    )
    for forbidden in (
        payload.body_text,
        "private-canary",
        account.workspace_email,
        payload.to[0],
    ):
        assert forbidden not in serialized_audits


@pytest.mark.parametrize("fetch_kind", ["profile", "message"])
@pytest.mark.parametrize("category", ["rate_limited", "transient_provider"])
async def test_delivered_reconciliation_provider_failure_is_retryable_without_mutation(
    origin_runtime,
    caplog: pytest.LogCaptureFixture,
    fetch_kind: str,
    category: str,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import (
        GmailMessageContent,
        GmailProfile,
        GmailProviderFailure,
    )
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    sends = 0

    def transport(**_kwargs):
        nonlocal sends
        sends += 1
        raise AssertionError("reconciliation must never invoke Gmail send")

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    payload = _payload(request_id=uuid4())
    intent = await service.claim_intent_only(
        payload=payload,
        request=_Request(),
        actor="hermes",
    )
    uncertain = await service.mark_delivery_uncertain(
        origin_id=intent.id,
        expected_version=1,
        category="provider_timeout",
    )
    secret = f"private-{fetch_kind}-{category}-provider-canary"
    calls: list[tuple[str, int]] = []

    def fetcher(**kwargs):
        calls.append((kwargs["kind"], kwargs["num_retries"]))
        if kwargs["kind"] == fetch_kind:
            raise GmailProviderFailure(category) from RuntimeError(secret)
        if kwargs["kind"] == "profile":
            return GmailProfile(
                email_address=account.workspace_email,
                history_id="reconciliation-profile-1",
            )
        return GmailMessageContent(
            message_id="candidate-message",
            thread_id="candidate-thread",
            label_ids=("SENT",),
            message_at=intent.created_at,
            headers={
                "subject": payload.subject,
                "from": account.workspace_email,
                "to": payload.to[0],
                "cc": payload.cc[0],
                "bcc": "",
            },
            body_text=payload.body_text,
        )

    try:
        with caplog.at_level("ERROR"):
            with pytest.raises(
                GmailProviderFailure, match=f"^{category}$"
            ) as raised:
                await service.reconcile_delivered_candidate(
                    account_id=account.id,
                    request_id=payload.request_id,
                    expected_state="delivery_uncertain",
                    expected_version=uncertain.version,
                    reason="Retryable provider verification failure.",
                    candidate_message_id="candidate-message",
                    candidate_thread_id="candidate-thread",
                    fetcher=fetcher,
                    request=_Request(),
                    actor="admin:1",
                )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert sends == 0
    assert calls == (
        [("profile", 0)]
        if fetch_kind == "profile"
        else [("profile", 0), ("message", 0)]
    )
    assert secret not in caplog.text
    assert secret not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__suppress_context__ is True
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageOrigin, intent.id)
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt)
        )
        reconciliation_audit_count = await session.scalar(
            sa.select(sa.func.count()).select_from(AgentActionAudit).where(
                AgentActionAudit.action_id.like(
                    "workspace.gmail.send.reconcile.delivered%"
                )
            )
        )
    assert stored.delivery_state == "delivery_uncertain"
    assert stored.version == uncertain.version
    assert stored.reconciled_outcome is None
    assert stored.quarantine_category is None
    assert stored.quarantine_evidence is None
    assert stored.gmail_message_id is None
    assert stored.gmail_thread_id is None
    assert receipt_count == 0
    assert reconciliation_audit_count == 0


async def test_delivered_reconciliation_fetch_deadline_does_not_block_health_or_mutate(
    origin_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailProviderFailure, GmailProfile
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    sends = 0

    def transport(**_kwargs):
        nonlocal sends
        sends += 1
        raise AssertionError("reconciliation must never invoke Gmail send")

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=0.05,
    )
    payload = _payload(request_id=uuid4())
    intent = await service.claim_intent_only(
        payload=payload,
        request=_Request(),
        actor="hermes",
    )
    uncertain = await service.mark_delivery_uncertain(
        origin_id=intent.id,
        expected_version=1,
        category="provider_timeout",
    )
    entered = threading.Event()
    release = threading.Event()

    def stalled_fetcher(**kwargs):
        assert kwargs["kind"] == "profile"
        assert kwargs["num_retries"] == 0
        entered.set()
        release.wait(timeout=5)
        return GmailProfile(
            email_address=account.workspace_email,
            history_id="late-profile",
        )

    pending = asyncio.create_task(
        service.reconcile_delivered_candidate(
            account_id=account.id,
            request_id=payload.request_id,
            expected_state="delivery_uncertain",
            expected_version=uncertain.version,
            reason="Deadline-bounded provider verification.",
            candidate_message_id="candidate-message",
            candidate_thread_id="candidate-thread",
            fetcher=stalled_fetcher,
            request=_Request(),
            actor="admin:1",
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 1)

        async def health_probe() -> str:
            await asyncio.sleep(0)
            return "healthy"

        assert await asyncio.wait_for(health_probe(), timeout=0.1) == "healthy"
        with pytest.raises(
            GmailProviderFailure, match="^transient_provider$"
        ):
            await asyncio.wait_for(pending, timeout=0.5)
    finally:
        release.set()
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert sends == 0
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageOrigin, intent.id)
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt)
        )
        reconciliation_audit_count = await session.scalar(
            sa.select(sa.func.count()).select_from(AgentActionAudit).where(
                AgentActionAudit.action_id.like(
                    "workspace.gmail.send.reconcile.delivered%"
                )
            )
        )
    assert stored.delivery_state == "delivery_uncertain"
    assert stored.version == uncertain.version
    assert stored.reconciled_outcome is None
    assert stored.quarantine_category is None
    assert receipt_count == 0
    assert reconciliation_audit_count == 0


async def test_fully_verified_delivered_candidate_succeeds_without_sending(
    origin_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent, GmailProfile
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    sends = 0

    def transport(**_kwargs):
        nonlocal sends
        sends += 1
        return {"id": "never", "thread_id": "never"}

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
    )
    payload = _payload(request_id=uuid4())
    intent = await service.claim_intent_only(
        payload=payload, request=_Request(), actor="hermes"
    )
    uncertain = await service.mark_delivery_uncertain(
        origin_id=intent.id, expected_version=1, category="provider_timeout"
    )

    fetch_calls: list[dict] = []
    main_thread = threading.current_thread()

    def fetcher(**kwargs):
        fetch_calls.append({**kwargs, "thread": threading.current_thread()})
        assert kwargs["num_retries"] == 0
        if kwargs["kind"] == "profile":
            return GmailProfile(
                email_address=account.workspace_email,
                history_id="1000",
            )
        return GmailMessageContent(
            message_id="verified-message",
            thread_id="verified-thread",
            label_ids=("SENT",),
            message_at=intent.created_at,
            headers={
                "subject": payload.subject,
                "from": account.workspace_email,
                "to": payload.to[0],
                "cc": payload.cc[0],
                "bcc": "",
            },
            body_text=payload.body_text,
        )

    try:
        result = await service.reconcile_delivered_candidate(
            account_id=account.id,
            request_id=payload.request_id,
            expected_state="delivery_uncertain",
            expected_version=uncertain.version,
            reason="Verified against Gmail.",
            candidate_message_id="verified-message",
            candidate_thread_id="verified-thread",
            fetcher=fetcher,
            request=_Request(),
            actor="admin:1",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    assert result.delivery_state == "succeeded"
    assert result.reconciled_outcome == "delivered"
    assert result.message_id == "verified-message"
    assert sends == 0
    assert [(call["kind"], call.get("message_id")) for call in fetch_calls] == [
        ("profile", None),
        ("message", "verified-message"),
    ]
    assert all(call["thread"] is not main_thread for call in fetch_calls)
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageOrigin, intent.id)
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt).where(
                        GmailMessageReceipt.account_id == account.id
                    )
                )
            ).all()
        )
        audit = await session.scalar(
            sa.select(AgentActionAudit).where(
                AgentActionAudit.action_id
                == "workspace.gmail.send.reconcile.delivered"
            )
        )
    assert stored.delivery_state == "succeeded"
    assert stored.version == 3
    assert stored.gmail_message_id == "verified-message"
    assert stored.gmail_thread_id == "verified-thread"
    assert stored.reconciled_outcome == "delivered"
    assert len(receipts) == 1
    assert receipts[0].gmail_message_id == "verified-message"
    assert receipts[0].processing_state == "pending"
    assert audit.actor == "admin:1"
    assert audit.allowed is True


@pytest.mark.parametrize(
    ("labels", "extra_headers", "expected_classification"),
    [
        (("SENT", "DRAFT"), {}, "ignored_draft"),
        (("SENT", "SPAM"), {}, "ignored_spam"),
        (("SENT", "TRASH"), {}, "ignored_trash"),
        (("SENT",), {"auto-submitted": "auto-generated"}, "ignored_automation"),
        (("SENT",), {"list-id": "<list.example.test>"}, "ignored_automation"),
    ],
)
async def test_verified_delivery_uses_sanitizer_suppression_for_receipt(
    origin_runtime,
    labels: tuple[str, ...],
    extra_headers: dict[str, str],
    expected_classification: str,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent, GmailProfile
    from services.gmail_message_sanitizer import participant_hmac
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    sends = 0

    def transport(**_kwargs):
        nonlocal sends
        sends += 1
        raise AssertionError("delivery reconciliation must never send")

    participant_key = b"test-participant-key-with-32-bytes"
    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=transport,
        deadline_seconds=1,
        participant_hash_key=participant_key,
    )
    payload = _payload(request_id=uuid4())
    intent = await service.claim_intent_only(
        payload=payload,
        request=_Request(),
        actor="hermes",
    )
    uncertain = await service.mark_delivery_uncertain(
        origin_id=intent.id,
        expected_version=1,
        category="provider_timeout",
    )
    candidate = GmailMessageContent(
        message_id="ignored-verified-message",
        thread_id="ignored-verified-thread",
        label_ids=labels,
        message_at=intent.created_at,
        headers={
            "subject": payload.subject,
            "from": account.workspace_email,
            "to": payload.to[0],
            "cc": payload.cc[0],
            "bcc": "",
            **extra_headers,
        },
        body_text=payload.body_text,
    )

    def fetcher(**kwargs):
        if kwargs["kind"] == "profile":
            return GmailProfile(
                email_address=account.workspace_email,
                history_id="1000",
            )
        return candidate

    try:
        result = await service.reconcile_delivered_candidate(
            account_id=account.id,
            request_id=payload.request_id,
            expected_state="delivery_uncertain",
            expected_version=uncertain.version,
            reason="Verified delivery with suppressed extraction metadata.",
            candidate_message_id=candidate.message_id,
            candidate_thread_id=candidate.thread_id,
            fetcher=fetcher,
            request=_Request(),
            actor="admin:1",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert result.delivery_state == "succeeded"
    assert sends == 0
    async with sessionmaker() as session:
        receipt = await session.scalar(
            sa.select(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
    assert receipt.processing_state == "ignored"
    assert receipt.classification == expected_classification
    assert receipt.sender_hmac == participant_hmac(
        account.workspace_email,
        participant_key,
    )
    assert json.loads(receipt.recipient_hmacs_json) == [
        participant_hmac(payload.to[0], participant_key),
        participant_hmac(payload.cc[0], participant_key),
    ]


@pytest.mark.parametrize(
    ("offset_seconds", "matches_intent"),
    [(-1, False), (0, True), (300, True), (301, False)],
)
async def test_history_send_proof_uses_inclusive_five_minute_evidence_window(
    origin_runtime,
    offset_seconds: int,
    matches_intent: bool,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History observation must not send"),
        deadline_seconds=1,
    )
    payload = _payload(request_id=uuid4())
    intent = await service.claim_intent_only(
        payload=payload,
        request=_Request(),
        actor="hermes",
    )
    uncertain = await service.mark_delivery_uncertain(
        origin_id=intent.id,
        expected_version=1,
        category="provider_timeout",
    )
    message = GmailMessageContent(
        message_id=f"temporal-message-{offset_seconds}",
        thread_id=f"temporal-thread-{offset_seconds}",
        label_ids=("SENT",),
        message_at=intent.created_at + timedelta(seconds=offset_seconds),
        headers={
            "subject": payload.subject,
            "from": account.workspace_email,
            "to": payload.to[0],
            "cc": payload.cc[0],
            "bcc": "",
        },
        body_text=payload.body_text,
    )
    try:
        result = await service.observe_history_sent(
            account_id=account.id,
            message=message,
        )
    finally:
        executor.shutdown()

    async with sessionmaker() as session:
        stored_intent = await session.get(GmailMessageOrigin, intent.id)
        origins = list(
            (
                await session.scalars(
                    sa.select(GmailMessageOrigin).where(
                        GmailMessageOrigin.account_id == account.id
                    )
                )
            ).all()
        )
    if matches_intent:
        assert result.origin_id == intent.id
        assert stored_intent.delivery_state == "succeeded"
        assert len(origins) == 1
    else:
        assert result.origin_id != intent.id
        assert result.origin_kind == "human_send"
        assert stored_intent.delivery_state == uncertain.delivery_state
        assert len(origins) == 2


@pytest.mark.parametrize(
    ("body_transport_compatible", "body_truncated"),
    [(False, False), (True, True)],
)
async def test_inexact_history_body_evidence_cannot_prove_sydney_intent(
    origin_runtime,
    body_transport_compatible: bool,
    body_truncated: bool,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History observation must not send"),
        deadline_seconds=1,
    )
    payload = _payload(request_id=uuid4())
    intent = await service.claim_intent_only(
        payload=payload,
        request=_Request(),
        actor="hermes",
    )
    uncertain = await service.mark_delivery_uncertain(
        origin_id=intent.id,
        expected_version=1,
        category="provider_timeout",
    )
    try:
        result = await service.observe_history_sent(
            account_id=account.id,
            message=GmailMessageContent(
                message_id=f"inexact-history-message-{body_truncated}",
                thread_id=f"inexact-history-thread-{body_truncated}",
                label_ids=("SENT",),
                message_at=intent.created_at,
                headers={
                    "subject": payload.subject,
                    "from": account.workspace_email,
                    "to": payload.to[0],
                    "cc": payload.cc[0],
                    "bcc": "",
                },
                body_text=payload.body_text,
                body_transport_compatible=body_transport_compatible,
                body_truncated=body_truncated,
            ),
        )
    finally:
        executor.shutdown()

    async with sessionmaker() as session:
        stored = await session.get(GmailMessageOrigin, intent.id)
    assert result.origin_kind == "human_send"
    assert result.origin_id != intent.id
    assert stored.delivery_state == uncertain.delivery_state


async def test_predecessor_evidence_cannot_prove_a_later_retry_intent(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_history_adapter import GmailMessageContent, GmailProfile
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("Evidence verification must not send"),
        deadline_seconds=1,
    )
    predecessor_payload = _payload(request_id=uuid4())
    predecessor = await service.claim_intent_only(
        payload=predecessor_payload,
        request=_Request(),
        actor="hermes",
    )
    predecessor = await service.mark_delivery_uncertain(
        origin_id=predecessor.id,
        expected_version=1,
        category="provider_timeout",
    )
    async with sessionmaker() as session:
        predecessor_row = await session.get(GmailMessageOrigin, predecessor.id)
        predecessor_created_at = predecessor_row.created_at
    predecessor = await service.mark_not_delivered(
        account_id=account.id,
        request_id=predecessor.request_id,
        expected_state="delivery_uncertain",
        expected_version=predecessor.version,
        reason="The predecessor provider attempt was not delivered.",
        request=_Request(),
        actor="admin:1",
    )
    retry_payload = _payload(
        request_id=uuid4(),
        retry_of_request_id=predecessor.request_id,
    )
    retry = await service.claim_intent_only(
        payload=retry_payload,
        request=_Request(),
        actor="hermes",
    )
    async with sessionmaker() as session:
        stored_retry = await session.get(GmailMessageOrigin, retry.id)
        stored_retry.created_at = predecessor_created_at + timedelta(minutes=2)
        await session.commit()
        await session.refresh(stored_retry)
        retry_created_at = stored_retry.created_at
    retry = await service.mark_delivery_uncertain(
        origin_id=retry.id,
        expected_version=1,
        category="provider_timeout",
    )

    def evidence(message_id: str, thread_id: str) -> GmailMessageContent:
        return GmailMessageContent(
            message_id=message_id,
            thread_id=thread_id,
            label_ids=("SENT",),
            message_at=predecessor_created_at,
            headers={
                "subject": retry_payload.subject,
                "from": account.workspace_email,
                "to": retry_payload.to[0],
                "cc": retry_payload.cc[0],
                "bcc": "",
            },
            body_text=retry_payload.body_text,
        )

    try:
        history = await service.observe_history_sent(
            account_id=account.id,
            message=evidence("delayed-predecessor", "delayed-predecessor-thread"),
        )

        def fetcher(**kwargs):
            if kwargs["kind"] == "profile":
                return GmailProfile(
                    email_address=account.workspace_email,
                    history_id="1000",
                )
            return evidence("admin-delayed-predecessor", "admin-delayed-thread")

        admin = await service.reconcile_delivered_candidate(
            account_id=account.id,
            request_id=retry.request_id,
            expected_state="delivery_uncertain",
            expected_version=retry.version,
            reason="Delayed predecessor evidence must not prove the retry.",
            candidate_message_id="admin-delayed-predecessor",
            candidate_thread_id="admin-delayed-thread",
            fetcher=fetcher,
            request=_Request(),
            actor="admin:1",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert predecessor_created_at < retry_created_at
    assert history.origin_kind == "human_send"
    assert history.origin_id != retry.id
    assert admin.delivery_state == "delivery_uncertain"
    assert admin.quarantine_category == "candidate_time_mismatch"
    async with sessionmaker() as session:
        stored_retry = await session.get(GmailMessageOrigin, retry.id)
    assert stored_retry.delivery_state == "delivery_uncertain"
    assert stored_retry.gmail_message_id is None


async def test_direct_history_observer_releases_raw_content_before_db_mutation(
    origin_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin
    from services.gmail_history_adapter import GmailMessageContent
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker, _sync_engine = origin_runtime
    account = await _seed_account(sessionmaker)
    raw_canary = "direct-history-private-body-canary"
    raw_ref: weakref.ReferenceType | None = None

    async def before_history_flush() -> None:
        gc.collect()
        assert raw_ref is not None
        assert raw_ref() is None
        raise RuntimeError("history_observer_test_barrier")

    executor = BoundedProviderExecutor(max_workers=1)
    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History observation must not send"),
        deadline_seconds=1,
        before_history_flush=before_history_flush,
    )

    def make_message() -> GmailMessageContent:
        nonlocal raw_ref
        content = GmailMessageContent(
            message_id="direct-history-raw-lifetime",
            thread_id="direct-history-raw-lifetime-thread",
            label_ids=("SENT",),
            message_at=datetime.now(tz=UTC),
            headers={
                "subject": "Manual raw lifetime",
                "from": account.workspace_email,
                "to": "client@example.test",
            },
            body_text=raw_canary,
        )
        raw_ref = weakref.ref(content)
        return content

    try:
        with pytest.raises(
            RuntimeError, match="^history_observer_test_barrier$"
        ) as raised:
            await service.observe_history_sent(
                account_id=account.id,
                message=make_message(),
            )
    finally:
        executor.shutdown()

    assert raw_canary not in "".join(traceback.format_exception(raised.value))
    async with sessionmaker() as session:
        origin_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageOrigin)
        )
    assert origin_count == 0
