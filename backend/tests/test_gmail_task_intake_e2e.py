from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi import HTTPException, Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "84d7a5f9b2c3"
UTC = timezone.utc
NOW = datetime(2026, 8, 23, 14, 0, tzinfo=UTC)
CHAT_ID = "8675309"
CODE_KEY = bytes(range(32))
CODE_KEY_VERSION = 7
PARTICIPANT_KEY = b"task-nine-participant-key-32bytes"


@pytest.fixture(scope="module")
def e2e_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def e2e_runtime(e2e_database):
    from models.lead import Lead

    assert Lead.__table__.name == "leads"
    url, sync_engine = e2e_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE gmail_sync_accounts, settings, admin_users, "
                "crm_contacts, crm_tasks, integration_health_states, "
                "notification_jobs CASCADE"
            )
        )
    engine = create_async_engine(
        async_test_url(url),
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessions
    finally:
        await engine.dispose()


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "query_string": b"",
            "headers": [],
            "scheme": "https",
            "server": ("testserver", 443),
        }
    )


async def _seed_account(sessions, *, cursor: str = "100"):
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting

    account = GmailSyncAccount(
        workspace_email="brandon@example.test",
        committed_history_id=cursor,
        mode="shadow",
    )
    async with sessions() as session:
        session.add(account)
        await session.flush()
        session.add_all(
            (
                Setting(
                    key="google_workspace_gmail_account_id",
                    value=str(account.id),
                ),
                Setting(
                    key="google_workspace_refresh_token",
                    value="disposable-test-refresh-token",
                ),
            )
        )
        await session.commit()
        await session.refresh(account)
    return account


async def _seed_admin(sessions):
    from models.admin_user import AdminUser

    admin = AdminUser(email=f"admin-{uuid4()}@example.test", hashed_password="test")
    async with sessions() as session:
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
    return admin


async def _replay_from_cursor(sessions, *, account_id: UUID, cursor: str) -> None:
    from models.gmail_task_intake import GmailSyncAccount

    async with sessions() as session:
        account = await session.get(GmailSyncAccount, account_id)
        assert account is not None
        account.committed_history_id = cursor
        await session.commit()


def _message(
    *,
    message_id: str,
    thread_id: str,
    direction: str,
    body: str,
    subject: str = "Follow-up",
):
    from services.gmail_history_adapter import GmailMessageContent

    if direction == "received":
        labels = ("INBOX",)
        sender = "client@example.test"
        recipient = "brandon@example.test"
    else:
        labels = ("SENT",)
        sender = "brandon@example.test"
        recipient = "client@example.test"
    return GmailMessageContent(
        message_id=message_id,
        thread_id=thread_id,
        label_ids=labels,
        message_at=NOW,
        headers={
            "subject": subject,
            "from": sender,
            "to": recipient,
        },
        body_text=body,
    )


class _ControlledGmailAdapter:
    def __init__(self, messages):
        self.messages = {message.message_id: message for message in messages}
        self.history_calls: list[tuple[str, str | None]] = []
        self.content_calls: list[str] = []

    async def list_history(
        self,
        *,
        account_key: str,
        start_history_id: str,
        page_token: str | None,
    ):
        from services.gmail_history_adapter import (
            GmailHistoryMessageRef,
            GmailHistoryPage,
        )

        del account_key
        self.history_calls.append((start_history_id, page_token))
        terminal = str(max(int(start_history_id), 101))
        return GmailHistoryPage(
            history_id=terminal,
            next_page_token=None,
            messages=tuple(
                GmailHistoryMessageRef(
                    message_id=message.message_id,
                    thread_id=message.thread_id,
                )
                for message in self.messages.values()
            ),
            discovered_history_id_min=terminal,
            discovered_history_id_max=terminal,
        )

    async def get_message_metadata(self, *, account_key: str, message_id: str):
        from services.gmail_history_adapter import GmailMessageMetadata

        del account_key
        message = self.messages[message_id]
        return GmailMessageMetadata(
            message_id=message.message_id,
            thread_id=message.thread_id,
            label_ids=message.label_ids,
            message_at=message.message_at,
            headers=message.headers,
        )

    async def get_message_content(self, *, account_key: str, message_id: str):
        del account_key
        self.content_calls.append(message_id)
        return self.messages[message_id]


def _model_action(*, kind: str, ambiguous_due: bool = False):
    return {
        "kind": kind,
        "semantic_action": "send",
        "semantic_object": "seller_disclosure",
        "title": "Send the disclosure package",
        "description": "Send the seller disclosure package to the client.",
        "priority": "high",
        "due_at": None if ambiguous_due else "2026-08-24T14:00:00-04:00",
        "timezone_basis": None if ambiguous_due else "America/New_York",
        "due_at_ambiguous": ambiguous_due,
        "requested_owner": None,
        "owner_ambiguous": False,
        "requested_link_type": None,
        "requested_link_id": None,
        "contact_hint": None,
        "confidence": 0.97,
        "rationale": "The message contains an explicit disclosure follow-up.",
    }


@dataclass
class _ReceiptHarness:
    history: object
    receipts: object
    executor: object

    async def close(self) -> None:
        await self.executor.wait_for_tracked_calls()
        self.executor.shutdown()


def _receipt_harness(
    *,
    engine,
    sessions,
    adapter,
    model_call,
    origin_observer=None,
    max_workers: int = 2,
    provider_deadline_seconds: float = 1,
    receipt_processing_deadline_seconds: float = 2,
):
    from services.gmail_history_service import GmailHistoryService
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )
    from services.gmail_task_extractor import GmailTaskExtractor
    from services.integration_health_service import BoundedProviderExecutor
    from workers.jobs.gmail_receipts import GmailReceiptJob

    executor = BoundedProviderExecutor(max_workers=max_workers)
    history = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=PARTICIPANT_KEY,
        origin_observer=origin_observer,
        receipt_processing_deadline_seconds=receipt_processing_deadline_seconds,
        receipt_processing_stale_after_seconds=10,
        clock=lambda: NOW,
    )
    extractor = GmailTaskExtractor(
        executor=executor,
        model_call=model_call,
        deadline_seconds=provider_deadline_seconds,
    )
    receipts = GmailReceiptJob(
        enabled=True,
        sessionmaker=sessions,
        history_service=history,
        extractor=extractor,
        reconciliation_service=GmailObligationReconciliationService(
            sessionmaker=sessions,
        ),
        batch_size=20,
        clock=lambda: NOW,
    )
    return _ReceiptHarness(history=history, receipts=receipts, executor=executor)


async def _approve_once(
    sessions,
    *,
    suggestion,
    admin,
    path: str,
    request_id: UUID,
    handoff_token: str | None = None,
    approval_start: datetime = NOW,
):
    from routers.command_task_suggestions import (
        approve_task_suggestion,
        exchange_task_suggestion_handoff,
        prepare_task_suggestion_approval,
    )
    from schemas.agent_control_crm import (
        ApprovalRequest,
        HandoffExchangeRequest,
        SuggestionVersion,
    )
    from services.crm_task_suggestion_service import (
        CRMTaskSuggestionService,
        canonical_task_payload_hash,
    )
    from services.task_suggestion_approval_service import (
        TaskSuggestionApprovalService,
    )

    async def durable_counts() -> dict[str, int]:
        tables = (
            "crm_tasks",
            "crm_task_creation_requests",
            "crm_task_sources",
            "crm_record_lifecycle_events",
            "crm_activities",
            "crm_task_suggestion_events",
            "agent_action_audits",
            "crm_task_suggestion_approval_nonces",
        )
        async with sessions() as session:
            return {
                table: int(
                    await session.scalar(sa.text(f"SELECT count(*) FROM {table}")) or 0
                )
                for table in tables
            }

    def assert_preview(prepared) -> None:
        expected_task = CRMTaskSuggestionService.preview_payload(suggestion)
        assert prepared.suggestion_id == suggestion.id
        assert prepared.suggestion_version == suggestion.version
        assert prepared.payload_hash == suggestion.payload_hash
        assert prepared.task == expected_task
        assert prepared.payload_hash == canonical_task_payload_hash(
            title=prepared.task.title,
            description=prepared.task.description,
            priority=prepared.task.priority,
            due_at=prepared.task.due_at,
            contact_id=prepared.task.contact_id,
            status=prepared.task.status,
        )

    async def command_call_at(when: datetime, call):
        import services.task_suggestion_approval_service as approval_module

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return when.replace(tzinfo=None)
                return when.astimezone(tz)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(approval_module, "datetime", _FixedDateTime)
            return await call()

    service = TaskSuggestionApprovalService()
    before_issuance = await durable_counts()
    extra_approval = None
    if path == "command_prepare":
        prepared_responses = []
        for offset in range(2):

            async def prepare():
                async with sessions() as session:
                    return await prepare_task_suggestion_approval(
                        suggestion.id,
                        SuggestionVersion(
                            expected_version=suggestion.version,
                            expected_payload_hash=suggestion.payload_hash,
                        ),
                        _request(
                            f"/api/v1/command/task-suggestions/{suggestion.id}"
                            "/approval/prepare"
                        ),
                        Response(),
                        str(admin.id),
                        session,
                    )

            prepared = await command_call_at(
                approval_start + timedelta(seconds=offset),
                prepare,
            )
            assert_preview(prepared)
            prepared_responses.append(prepared)
        assert prepared_responses[0].approval != prepared_responses[1].approval
        extra_approval = prepared_responses[0].approval
        issued_approval = prepared_responses[1].approval
        expected_nonce_delta = 2
    else:
        if handoff_token is None:
            async with sessions() as session, session.begin():
                _, handoff = await service.issue_handoff(
                    session,
                    suggestion_id=suggestion.id,
                    expected_version=suggestion.version,
                    expected_payload_hash=suggestion.payload_hash,
                    now=approval_start,
                )
            handoff_token = handoff.token
            expected_nonce_delta = 2
        else:
            expected_nonce_delta = 1

        async def exchange():
            async with sessions() as session:
                return await exchange_task_suggestion_handoff(
                    suggestion.id,
                    HandoffExchangeRequest(
                        handoff=handoff_token,
                        expected_version=suggestion.version,
                        expected_payload_hash=suggestion.payload_hash,
                    ),
                    _request(
                        f"/api/v1/command/task-suggestions/{suggestion.id}"
                        "/handoff/exchange"
                    ),
                    Response(),
                    str(admin.id),
                    session,
                )

        prepared = await command_call_at(
            approval_start + timedelta(seconds=1),
            exchange,
        )
        assert_preview(prepared)
        issued_approval = prepared.approval
        with pytest.raises(HTTPException) as replayed_exchange:
            await command_call_at(
                approval_start + timedelta(seconds=2),
                exchange,
            )
        assert replayed_exchange.value.status_code == 409
        assert replayed_exchange.value.detail == "handoff_invalid"

    after_issuance = await durable_counts()
    for table in (
        "crm_tasks",
        "crm_task_creation_requests",
        "crm_task_sources",
        "crm_record_lifecycle_events",
        "crm_activities",
        "crm_task_suggestion_events",
        "agent_action_audits",
    ):
        assert after_issuance[table] == before_issuance[table]
    assert (
        after_issuance["crm_task_suggestion_approval_nonces"]
        == before_issuance["crm_task_suggestion_approval_nonces"] + expected_nonce_delta
    )

    async def approve(approval: str, *, replay_request_id: UUID):
        async with sessions() as session:
            return await approve_task_suggestion(
                suggestion.id,
                ApprovalRequest(
                    approval=approval,
                    expected_version=suggestion.version,
                    expected_payload_hash=suggestion.payload_hash,
                    request_id=replay_request_id,
                    client_timezone="America/New_York",
                ),
                _request(f"/api/v1/command/task-suggestions/{suggestion.id}/approve"),
                Response(),
                str(admin.id),
                session,
            )

    first = await command_call_at(
        approval_start + timedelta(seconds=3),
        lambda: approve(issued_approval, replay_request_id=request_id),
    )
    assert first.replayed is False
    replay = await command_call_at(
        approval_start + timedelta(minutes=3),
        lambda: approve(issued_approval, replay_request_id=request_id),
    )
    assert replay.replayed is True
    assert replay.task_id == first.task_id
    after_approval_replay = await durable_counts()
    expected_deltas = {
        "crm_tasks": 1,
        "crm_task_creation_requests": 1,
        "crm_task_sources": 1,
        "crm_record_lifecycle_events": 1,
        "crm_activities": 0,
        "crm_task_suggestion_events": 2,
        "agent_action_audits": 1,
    }
    for table, delta in expected_deltas.items():
        assert after_approval_replay[table] == after_issuance[table] + delta
    assert (
        after_approval_replay["crm_task_suggestion_approval_nonces"]
        == after_issuance["crm_task_suggestion_approval_nonces"]
    )
    if extra_approval is not None:
        with pytest.raises(HTTPException) as stale_approval:
            await command_call_at(
                approval_start + timedelta(minutes=4),
                lambda: approve(extra_approval, replay_request_id=uuid4()),
            )
        assert stale_approval.value.status_code == 409
        assert stale_approval.value.detail == "suggestion_stale"
        assert await durable_counts() == after_approval_replay
    return first


@pytest.mark.asyncio
async def test_controlled_received_history_replay_approves_exactly_one_task(
    e2e_runtime,
):
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        GmailMessageReceipt,
    )

    engine, sessions = e2e_runtime
    account = await _seed_account(sessions)
    admin = await _seed_admin(sessions)
    adapter = _ControlledGmailAdapter(
        [
            _message(
                message_id="received-e2e-1",
                thread_id="received-thread-1",
                direction="received",
                body="Please send me the seller disclosures tomorrow.",
            )
        ]
    )
    harness = _receipt_harness(
        engine=engine,
        sessions=sessions,
        adapter=adapter,
        model_call=lambda _request: {
            "schema_version": "gmail-task-v1",
            "actions": [_model_action(kind="incoming_request")],
        },
    )
    try:
        await harness.history.sync_account(account.id)
        await _replay_from_cursor(sessions, account_id=account.id, cursor="100")
        await harness.history.sync_account(account.id)
        await harness.receipts.run()
        await harness.receipts.run()
    finally:
        await harness.close()

    async with sessions() as session:
        receipts = list((await session.scalars(sa.select(GmailMessageReceipt))).all())
        suggestions = list((await session.scalars(sa.select(CRMTaskSuggestion))).all())
    assert len(receipts) == 1
    assert receipts[0].processing_state == "processed"
    assert len(suggestions) == 1
    assert suggestions[0].state == "pending_review"

    await _approve_once(
        sessions,
        suggestion=suggestions[0],
        admin=admin,
        path="command_prepare",
        request_id=UUID("00000000-0000-0000-0000-000000000901"),
    )
    async with sessions() as session:
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 1
        assert (
            await session.scalar(
                sa.text("SELECT count(*) FROM crm_task_creation_requests")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_controlled_agent_send_uuid_origin_and_receipt_replay_create_one_task(
    e2e_runtime,
):
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        GmailMessageOrigin,
        GmailMessageReceipt,
    )
    from schemas.agent_control import WorkspaceGmailSendRequest
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessions = e2e_runtime
    account = await _seed_account(sessions)
    admin = await _seed_admin(sessions)
    request_id = UUID("00000000-0000-0000-0000-000000000902")
    payload = WorkspaceGmailSendRequest(
        request_id=request_id,
        to=["client@example.test"],
        cc=[],
        bcc=[],
        subject="Disclosure follow-up",
        body_text="I will send the seller disclosures tomorrow.",
        confirmed_by_brandon=True,
        confirmation_note="Controlled local fixture.",
    )
    provider_executor = BoundedProviderExecutor(max_workers=1)
    origin_service = GmailOriginService(
        engine=engine,
        provider_executor=provider_executor,
        transport=lambda **_kwargs: {
            "id": "sent-e2e-1",
            "thread_id": "sent-thread-1",
        },
        deadline_seconds=1,
        participant_hash_key=PARTICIPANT_KEY,
        clock=lambda: NOW,
    )
    try:
        first_send = await origin_service.send(
            payload=payload,
            request=_request("/api/v1/agent-control/workspace/gmail/send"),
            actor="hermes",
        )
        replay_send = await origin_service.send(
            payload=payload,
            request=_request("/api/v1/agent-control/workspace/gmail/send"),
            actor="hermes",
        )
    finally:
        await provider_executor.wait_for_tracked_calls()
        provider_executor.shutdown()
    assert replay_send.replayed is True
    assert replay_send.origin_id == first_send.origin_id

    adapter = _ControlledGmailAdapter(
        [
            _message(
                message_id="sent-e2e-1",
                thread_id="sent-thread-1",
                direction="sent",
                body=payload.body_text,
                subject=payload.subject,
            )
        ]
    )
    harness = _receipt_harness(
        engine=engine,
        sessions=sessions,
        adapter=adapter,
        origin_observer=origin_service,
        model_call=lambda _request: {
            "schema_version": "gmail-task-v1",
            "actions": [_model_action(kind="outgoing_commitment")],
        },
    )
    try:
        await harness.history.sync_account(account.id)
        await _replay_from_cursor(sessions, account_id=account.id, cursor="100")
        await harness.history.sync_account(account.id)
        await harness.receipts.run()
        await harness.receipts.run()
    finally:
        await harness.close()

    async with sessions() as session:
        assert (
            await session.scalar(sa.select(sa.func.count(GmailMessageOrigin.id))) == 1
        )
        assert (
            await session.scalar(sa.select(sa.func.count(GmailMessageReceipt.id))) == 1
        )
        suggestions = list((await session.scalars(sa.select(CRMTaskSuggestion))).all())
    assert len(suggestions) == 1
    await _approve_once(
        sessions,
        suggestion=suggestions[0],
        admin=admin,
        path="command_prepare",
        request_id=UUID("00000000-0000-0000-0000-000000000903"),
    )
    async with sessions() as session:
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 1


@pytest.mark.asyncio
async def test_received_request_and_sydney_commitment_in_one_thread_have_two_sources(
    e2e_runtime,
):
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
    )
    from schemas.agent_control import WorkspaceGmailSendRequest
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessions = e2e_runtime
    account = await _seed_account(sessions)
    admin = await _seed_admin(sessions)
    send_request_id = UUID("00000000-0000-0000-0000-000000000904")
    payload = WorkspaceGmailSendRequest(
        request_id=send_request_id,
        to=["client@example.test"],
        cc=[],
        bcc=[],
        subject="Re: Disclosure request",
        body_text="I will send the seller disclosure package tomorrow.",
        confirmed_by_brandon=True,
        confirmation_note="Controlled local fixture.",
    )
    send_executor = BoundedProviderExecutor(max_workers=1)
    origin_service = GmailOriginService(
        engine=engine,
        provider_executor=send_executor,
        transport=lambda **_kwargs: {
            "id": "merged-sent-1",
            "thread_id": "merged-thread-1",
        },
        deadline_seconds=1,
        participant_hash_key=PARTICIPANT_KEY,
        clock=lambda: NOW,
    )
    try:
        await origin_service.send(
            payload=payload,
            request=_request("/api/v1/agent-control/workspace/gmail/send"),
            actor="hermes",
        )
    finally:
        await send_executor.wait_for_tracked_calls()
        send_executor.shutdown()

    messages = (
        _message(
            message_id="merged-received-1",
            thread_id="merged-thread-1",
            direction="received",
            body="Please send the seller disclosure package tomorrow.",
            subject="Disclosure request",
        ),
        _message(
            message_id="merged-sent-1",
            thread_id="merged-thread-1",
            direction="sent",
            body=payload.body_text,
            subject=payload.subject,
        ),
    )
    adapter = _ControlledGmailAdapter(messages)

    def model_call(request):
        kind = (
            "incoming_request"
            if request.direction == "received"
            else "outgoing_commitment"
        )
        return {
            "schema_version": "gmail-task-v1",
            "actions": [_model_action(kind=kind)],
        }

    harness = _receipt_harness(
        engine=engine,
        sessions=sessions,
        adapter=adapter,
        model_call=model_call,
        origin_observer=origin_service,
    )
    try:
        await harness.history.sync_account(account.id)
        await harness.receipts.run()
        await _replay_from_cursor(sessions, account_id=account.id, cursor="100")
        await harness.history.sync_account(account.id)
        await harness.receipts.run()
    finally:
        await harness.close()

    async with sessions() as session:
        suggestions = list((await session.scalars(sa.select(CRMTaskSuggestion))).all())
        source_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestionSource.id))
        )
    assert len(suggestions) == 1
    assert source_count == 2
    await _approve_once(
        sessions,
        suggestion=suggestions[0],
        admin=admin,
        path="handoff_exchange",
        request_id=UUID("00000000-0000-0000-0000-000000000905"),
    )
    async with sessions() as session:
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 1


@pytest.mark.asyncio
async def test_provider_timeout_attempt_is_durable_before_receipt_deadline(
    e2e_runtime,
) -> None:
    from models.gmail_task_intake import GmailExtractionAttempt, GmailMessageReceipt

    engine, sessions = e2e_runtime
    account = await _seed_account(sessions)
    adapter = _ControlledGmailAdapter(
        [
            _message(
                message_id="provider-timeout-finalization-1",
                thread_id="provider-timeout-finalization-thread-1",
                direction="received",
                body="Please send the disclosure package tomorrow.",
            )
        ]
    )
    provider_entered = threading.Event()
    provider_release = threading.Event()

    def stalled_model_call(_request):
        provider_entered.set()
        provider_release.wait(timeout=5)
        return {
            "schema_version": "gmail-task-v1",
            "actions": [_model_action(kind="incoming_request")],
        }

    harness = _receipt_harness(
        engine=engine,
        sessions=sessions,
        adapter=adapter,
        model_call=stalled_model_call,
        max_workers=1,
        provider_deadline_seconds=0.05,
        receipt_processing_deadline_seconds=0.5,
    )
    try:
        await harness.history.sync_account(account.id)
        await harness.receipts.run()
        assert provider_entered.is_set()
        async with sessions() as session:
            receipt = await session.scalar(sa.select(GmailMessageReceipt))
            attempt = await session.scalar(sa.select(GmailExtractionAttempt))
        assert receipt is not None and receipt.processing_state == "failed"
        assert receipt.failure_category == "transient_processing"
        assert attempt is not None and attempt.state == "failed"
        assert attempt.error_category == "provider_timeout"
        assert attempt.completed_at is not None
    finally:
        provider_release.set()
        await harness.close()


@pytest.mark.asyncio
async def test_running_provider_future_adds_no_no_call_extraction_attempts(
    e2e_runtime,
) -> None:
    from models.gmail_task_intake import GmailExtractionAttempt, GmailMessageReceipt

    engine, sessions = e2e_runtime
    account = await _seed_account(sessions)
    adapter = _ControlledGmailAdapter(
        [
            _message(
                message_id="running-provider-attempt-1",
                thread_id="running-provider-thread-1",
                direction="received",
                body="Please send the disclosure package tomorrow.",
            )
        ]
    )
    provider_entered = threading.Event()
    provider_release = threading.Event()
    model_calls = 0

    def model_call(_request):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            provider_entered.set()
            provider_release.wait(timeout=5)
        return {
            "schema_version": "gmail-task-v1",
            "actions": [_model_action(kind="incoming_request")],
        }

    harness = _receipt_harness(
        engine=engine,
        sessions=sessions,
        adapter=adapter,
        model_call=model_call,
        max_workers=1,
        provider_deadline_seconds=0.05,
        receipt_processing_deadline_seconds=0.5,
    )
    try:
        await harness.history.sync_account(account.id)
        await harness.receipts.run()
        assert provider_entered.is_set()
        await asyncio.gather(*(harness.receipts.run() for _ in range(4)))
        await harness.receipts.run()
        async with sessions() as session:
            attempts_while_running = list(
                (
                    await session.scalars(
                        sa.select(GmailExtractionAttempt).order_by(
                            GmailExtractionAttempt.attempt_number
                        )
                    )
                ).all()
            )
            receipt = await session.scalar(sa.select(GmailMessageReceipt))
        assert len(attempts_while_running) == 1
        assert attempts_while_running[0].state == "failed"
        assert attempts_while_running[0].error_category == "provider_timeout"
        assert receipt is not None and receipt.processing_state == "failed"
        assert model_calls == 1

        provider_release.set()
        await harness.executor.wait_for_tracked_calls()
        await harness.receipts.run()
        await harness.receipts.run()
        async with sessions() as session:
            attempts_after_exit = list(
                (
                    await session.scalars(
                        sa.select(GmailExtractionAttempt).order_by(
                            GmailExtractionAttempt.attempt_number
                        )
                    )
                ).all()
            )
        assert [attempt.state for attempt in attempts_after_exit] == [
            "failed",
            "succeeded",
        ]
        assert model_calls == 2
    finally:
        provider_release.set()
        await harness.close()


@pytest.mark.asyncio
async def test_saturated_provider_adds_no_attempt_until_capacity_can_make_call(
    e2e_runtime,
) -> None:
    from models.gmail_task_intake import GmailExtractionAttempt
    from services.integration_health_service import ProviderCallTimedOut

    engine, sessions = e2e_runtime
    account = await _seed_account(sessions)
    adapter = _ControlledGmailAdapter(
        [
            _message(
                message_id="saturated-provider-attempt-1",
                thread_id="saturated-provider-thread-1",
                direction="received",
                body="Please send the disclosure package tomorrow.",
            )
        ]
    )
    blocker_entered = threading.Event()
    blocker_release = threading.Event()
    model_calls = 0

    def model_call(_request):
        nonlocal model_calls
        model_calls += 1
        return {
            "schema_version": "gmail-task-v1",
            "actions": [_model_action(kind="incoming_request")],
        }

    def blocker() -> None:
        blocker_entered.set()
        blocker_release.wait(timeout=5)

    harness = _receipt_harness(
        engine=engine,
        sessions=sessions,
        adapter=adapter,
        model_call=model_call,
        max_workers=1,
        provider_deadline_seconds=0.05,
        receipt_processing_deadline_seconds=0.5,
    )
    try:
        blocking_call = asyncio.create_task(
            harness.executor.run(
                key="unrelated-provider-call",
                function=blocker,
                deadline_seconds=0.05,
            )
        )
        assert await asyncio.to_thread(blocker_entered.wait, 1)
        with pytest.raises(ProviderCallTimedOut, match="provider_timeout"):
            await blocking_call
        await harness.history.sync_account(account.id)
        await asyncio.gather(*(harness.receipts.run() for _ in range(4)))
        await harness.receipts.run()
        async with sessions() as session:
            attempt_count = await session.scalar(
                sa.select(sa.func.count(GmailExtractionAttempt.id))
            )
        assert attempt_count == 0
        assert model_calls == 0

        blocker_release.set()
        await harness.executor.wait_for_tracked_calls()
        await harness.receipts.run()
        async with sessions() as session:
            attempts = list(
                (await session.scalars(sa.select(GmailExtractionAttempt))).all()
            )
        assert len(attempts) == 1
        assert attempts[0].state == "succeeded"
        assert model_calls == 1
    finally:
        blocker_release.set()
        await harness.close()


@pytest.mark.asyncio
async def test_invalid_model_output_is_lease_bound_atomic_and_has_no_n_plus_one_call(
    e2e_runtime,
):
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
        GmailExtractionAttempt,
        GmailMessageReceipt,
    )

    engine, sessions = e2e_runtime
    account = await _seed_account(sessions)
    adapter = _ControlledGmailAdapter(
        [
            _message(
                message_id="invalid-output-e2e-1",
                thread_id="invalid-output-thread-1",
                direction="received",
                body="Please send the disclosure package tomorrow.",
            )
        ]
    )
    model_calls = 0

    def invalid_model_call(_request):
        nonlocal model_calls
        model_calls += 1
        return {"schema_version": "gmail-task-v1", "actions": "not-a-list"}

    harness = _receipt_harness(
        engine=engine,
        sessions=sessions,
        adapter=adapter,
        model_call=invalid_model_call,
    )
    try:
        await harness.history.sync_account(account.id)
        for _attempt in range(5):
            await harness.receipts.run()
    finally:
        await harness.close()

    async with sessions() as session:
        receipt = await session.scalar(sa.select(GmailMessageReceipt))
        attempts = list(
            (
                await session.scalars(
                    sa.select(GmailExtractionAttempt).order_by(
                        GmailExtractionAttempt.attempt_number
                    )
                )
            ).all()
        )
        counts = (
            await session.scalar(sa.select(sa.func.count(GmailExtractedObligation.id))),
            await session.scalar(sa.select(sa.func.count(CRMTaskSuggestion.id))),
            await session.scalar(sa.select(sa.func.count(CRMTaskSuggestionSource.id))),
        )
    assert receipt is not None
    assert receipt.processing_state == "processed"
    assert receipt.body_hash is not None
    assert receipt.classification == "eligible"
    assert [attempt.attempt_number for attempt in attempts] == [1, 2, 3]
    assert [attempt.state for attempt in attempts] == ["failed"] * 3
    assert [attempt.error_category for attempt in attempts] == [
        "invalid_model_output"
    ] * 3
    assert model_calls == 3
    assert counts == (0, 0, 0)


class _MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class _InlineExecutor:
    async def run(self, *, function, **_kwargs):
        return function()


def _telegram_response(*, message_id: int):
    from services.sydney_telegram_dispatcher import TelegramHTTPResponse

    return TelegramHTTPResponse(
        status_code=200,
        payload={
            "ok": True,
            "result": {"message_id": message_id, "chat": {"id": int(CHAT_ID)}},
        },
    )


def _clarification_service(sessions):
    from services.sydney_clarification_service import SydneyClarificationService

    return SydneyClarificationService(
        sessionmaker=sessions,
        brandon_chat_id=CHAT_ID,
        clarification_code_keys={CODE_KEY_VERSION: CODE_KEY},
        active_code_key_version=CODE_KEY_VERSION,
    )


def _clarification_code(row) -> str:
    from services.sydney_clarification_service import derive_clarification_code

    return derive_clarification_code(
        key=CODE_KEY,
        key_version=row.code_key_version,
        clarification_id=row.id,
        suggestion_id=row.suggestion_id,
        suggestion_version=row.suggestion_version,
        field_name=row.field_name,
        round_number=row.round_number,
    )


@pytest.mark.asyncio
async def test_direct_sydney_draft_uses_evaluator_question_answer_and_handoff_once(
    e2e_runtime,
):
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox
    from routers.agent_control_crm import create_task_draft
    from schemas.agent_control_crm import AgentTaskDraftRequest
    from services.sydney_clarification_service import SydneyClarificationError
    from services.sydney_telegram_dispatcher import (
        SydneyTelegramDispatcher,
        SydneyTelegramDispatcherConfig,
    )
    from workers.jobs.sydney_questions import SydneyQuestionsJob

    _engine, sessions = e2e_runtime
    admin = await _seed_admin(sessions)
    draft_request_id = UUID("00000000-0000-0000-0000-000000000906")
    payload = AgentTaskDraftRequest(
        request_id=draft_request_id,
        title="Prepare the inspection follow-up",
        description="",
    )
    async with sessions() as session:
        first = await create_task_draft(
            payload,
            _request("/api/v1/agent-control/crm/task-drafts"),
            session,
            {"actor": "hermes"},
        )
    async with sessions() as session:
        replay = await create_task_draft(
            payload,
            _request("/api/v1/agent-control/crm/task-drafts"),
            session,
            {"actor": "hermes"},
        )
    assert replay.id == first.id
    assert replay.state == "needs_clarification"

    clock = _MutableClock(NOW)
    sent_messages: list[dict[str, object]] = []

    def send_message(**kwargs):
        sent_messages.append(kwargs["payload"])
        return _telegram_response(message_id=700 + len(sent_messages))

    clarification_service = _clarification_service(sessions)
    dispatcher = SydneyTelegramDispatcher(
        sessionmaker=sessions,
        executor=_InlineExecutor(),
        send_message=send_message,
        config=SydneyTelegramDispatcherConfig(
            enabled=True,
            bot_token="123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd",
            brandon_chat_id=CHAT_ID,
            clarification_code_keys={CODE_KEY_VERSION: CODE_KEY},
            active_code_key_version=CODE_KEY_VERSION,
            provider_deadline_seconds=2,
            provider_socket_timeout_seconds=1,
        ),
        clock=clock,
    )
    questions = SydneyQuestionsJob(
        enabled=True,
        sessionmaker=sessions,
        clarification_service=clarification_service,
        dispatcher=dispatcher,
        batch_size=20,
        clock=clock,
    )
    await questions.run()
    await questions.run()
    assert len(sent_messages) == 1

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, first.id)
        clarification = await session.scalar(sa.select(CRMTaskClarification))
        assert suggestion is not None and clarification is not None
        code = _clarification_code(clarification)
    result = await clarification_service.answer(
        code=code,
        expected_suggestion_version=suggestion.version,
        answer={
            "kind": "task_details",
            "decision": "replace",
            "title": "Prepare the inspection follow-up",
            "description": "Send the inspection agenda to the buyer.",
            "priority": "normal",
        },
        now=NOW + timedelta(minutes=1),
    )
    assert result.handoff_link is not None
    assert "#handoff=" in result.handoff_link
    with pytest.raises(SydneyClarificationError, match="stale_clarification"):
        await clarification_service.answer(
            code=code,
            expected_suggestion_version=suggestion.version,
            answer={"kind": "task_details", "decision": "confirm_current"},
            now=NOW + timedelta(minutes=2),
        )

    handoff_token = result.handoff_link.split("#handoff=", 1)[1]
    async with sessions() as session:
        current = await session.get(CRMTaskSuggestion, first.id)
        assert current is not None
        current_version = current.version
        current_hash = current.payload_hash
    task_request_id = UUID("00000000-0000-0000-0000-000000000907")
    assert current_version == current.version
    assert current_hash == current.payload_hash
    await _approve_once(
        sessions,
        suggestion=current,
        admin=admin,
        path="handoff_exchange",
        request_id=task_request_id,
        handoff_token=handoff_token,
        approval_start=NOW + timedelta(minutes=2),
    )
    async with sessions() as session:
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 1
        assert (
            await session.scalar(sa.select(sa.func.count(SydneyQuestionOutbox.id))) == 1
        )


@pytest.mark.asyncio
async def test_question_job_has_one_reminder_fixed_release_and_stale_late_answer(
    e2e_runtime,
):
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox
    from services.crm_task_suggestion_service import canonical_task_payload_hash
    from services.sydney_clarification_service import SydneyClarificationError
    from services.sydney_telegram_dispatcher import (
        SydneyTelegramDispatcher,
        SydneyTelegramDispatcherConfig,
        TelegramDispatchError,
    )
    from workers.jobs.sydney_questions import SydneyQuestionsJob

    _engine, sessions = e2e_runtime
    suggestion = CRMTaskSuggestion(
        source_type="sydney_chat",
        source_scope_key="sydney:clock-e2e",
        source_action_key="sydney-clock-e2e",
        source_request_id=UUID("00000000-0000-0000-0000-000000000908"),
        contact_resolution_state="not_provided",
        title="Send the disclosure package",
        description="Send it after Brandon confirms the timing.",
        priority="normal",
        task_status="open",
        state="needs_clarification",
        clarification_state="pending",
        blocker_codes=["ambiguous_due_at"],
        payload_hash=canonical_task_payload_hash(
            title="Send the disclosure package",
            description="Send it after Brandon confirms the timing.",
            priority="normal",
            due_at=None,
            contact_id=None,
            status="open",
        ),
        model_schema_version="sydney-task-v1",
        obligation_fingerprint="9" * 64,
        confidence=1,
        rationale="Controlled clock fixture.",
        version=1,
    )
    async with sessions() as session:
        session.add(suggestion)
        await session.commit()
        await session.refresh(suggestion)

    clock = _MutableClock(NOW)
    sent = 0

    def send_message(**_kwargs):
        from services.sydney_telegram_dispatcher import TelegramHTTPResponse

        nonlocal sent
        sent += 1
        if sent == 1:
            return TelegramHTTPResponse(
                status_code=400,
                payload={"ok": False, "error_code": 400},
            )
        return _telegram_response(message_id=800 + sent)

    clarification_service = _clarification_service(sessions)
    dispatcher = SydneyTelegramDispatcher(
        sessionmaker=sessions,
        executor=_InlineExecutor(),
        send_message=send_message,
        config=SydneyTelegramDispatcherConfig(
            enabled=True,
            bot_token="123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd",
            brandon_chat_id=CHAT_ID,
            clarification_code_keys={CODE_KEY_VERSION: CODE_KEY},
            active_code_key_version=CODE_KEY_VERSION,
            provider_deadline_seconds=2,
            provider_socket_timeout_seconds=1,
        ),
        clock=clock,
    )
    job = SydneyQuestionsJob(
        enabled=True,
        sessionmaker=sessions,
        clarification_service=clarification_service,
        dispatcher=dispatcher,
        batch_size=20,
        clock=clock,
    )
    await job.run()
    async with sessions() as session:
        clarification = await session.scalar(sa.select(CRMTaskClarification))
        assert clarification is not None
        code = _clarification_code(clarification)
        initial = await session.scalar(
            sa.select(SydneyQuestionOutbox).where(
                SydneyQuestionOutbox.attempt_kind == "initial"
            )
        )
        assert initial is not None and initial.state == "failed"
        initial_snapshot = (
            initial.id,
            initial.dedupe_key,
            initial.question_context_json,
            initial.rendered_payload_hash,
        )
        audit = AgentActionAudit(
            actor="command_admin",
            action_id="task9-e2e-telegram-retry",
            method="POST",
            path="/api/v1/admin/sydney/reconcile",
            status_code=200,
            allowed=True,
        )
        session.add(audit)
        await session.commit()
        await session.refresh(audit)
    await dispatcher.reconcile_attempt(
        initial.id,
        "failed",
        "not_delivered",
        "Controlled provider rejection.",
        audit.id,
        None,
        None,
    )
    retry_id = await dispatcher.create_initial_retry(
        initial.id,
        "Controlled provider rejection.",
        audit.id,
    )
    with pytest.raises(TelegramDispatchError, match="telegram_retry_stale"):
        await dispatcher.create_initial_retry(
            initial.id,
            "Controlled provider rejection.",
            audit.id,
        )
    await job.run()
    await job.run()

    clock.value = NOW + timedelta(hours=24)
    await job.run()
    await job.run()
    async with sessions() as session:
        attempts_at_24h = await session.scalar(
            sa.select(sa.func.count(SydneyQuestionOutbox.id))
        )
        attempts = list(
            (
                await session.scalars(
                    sa.select(SydneyQuestionOutbox).order_by(
                        SydneyQuestionOutbox.created_at,
                        SydneyQuestionOutbox.id,
                    )
                )
            ).all()
        )
    assert attempts_at_24h == 3
    assert sent == 3
    attempts_by_kind = {attempt.attempt_kind: attempt for attempt in attempts}
    assert set(attempts_by_kind) == {"initial", "initial_retry", "reminder"}
    assert attempts_by_kind["initial_retry"].id == retry_id
    assert attempts_by_kind["initial_retry"].parent_initial_attempt_id == initial.id
    assert attempts_by_kind["reminder"].reply_to_attempt_id == retry_id
    assert (
        attempts_by_kind["initial"].id,
        attempts_by_kind["initial"].dedupe_key,
        attempts_by_kind["initial"].question_context_json,
        attempts_by_kind["initial"].rendered_payload_hash,
    ) == initial_snapshot

    clock.value = NOW + timedelta(hours=48)
    await job.run()
    await job.run()
    async with sessions() as session:
        clarification = await session.get(CRMTaskClarification, clarification.id)
        assert clarification is not None and clarification.state == "timed_out"
    with pytest.raises(SydneyClarificationError, match="stale_clarification"):
        await clarification_service.answer(
            code=code,
            expected_suggestion_version=1,
            answer={
                "kind": "due_at",
                "decision": "no_due_date",
            },
            now=clock.value + timedelta(seconds=1),
        )
    async with sessions() as session:
        assert (
            await session.scalar(sa.select(sa.func.count(SydneyQuestionOutbox.id))) == 3
        )


@pytest.mark.asyncio
async def test_question_job_recovers_only_restart_stale_sending_attempt_once(
    e2e_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox
    from services.crm_task_suggestion_service import canonical_task_payload_hash
    from services.integration_health_service import BoundedProviderExecutor
    from services.sydney_telegram_dispatcher import (
        SydneyTelegramDispatcher,
        SydneyTelegramDispatcherConfig,
        TelegramDispatchError,
    )
    from workers.jobs.sydney_questions import SydneyQuestionsJob

    _engine, sessions = e2e_runtime
    suggestion = CRMTaskSuggestion(
        source_type="sydney_chat",
        source_scope_key="sydney:restart-recovery-e2e",
        source_action_key="sydney-restart-recovery-e2e",
        source_request_id=UUID("00000000-0000-0000-0000-000000000910"),
        contact_resolution_state="not_provided",
        title="Confirm the restart-safe follow-up time",
        description="The due time remains ambiguous after a worker restart.",
        priority="normal",
        task_status="open",
        state="needs_clarification",
        clarification_state="pending",
        blocker_codes=["ambiguous_due_at"],
        payload_hash=canonical_task_payload_hash(
            title="Confirm the restart-safe follow-up time",
            description="The due time remains ambiguous after a worker restart.",
            priority="normal",
            due_at=None,
            contact_id=None,
            status="open",
        ),
        model_schema_version="sydney-task-v1",
        obligation_fingerprint="8" * 64,
        confidence=1,
        rationale="Controlled restart recovery fixture.",
        version=1,
    )
    async with sessions() as session:
        session.add(suggestion)
        await session.commit()

    clock = _MutableClock(NOW)
    provider_entered = threading.Event()
    provider_release = threading.Event()
    send_calls = 0

    def stalled_send(**_kwargs):
        nonlocal send_calls
        send_calls += 1
        provider_entered.set()
        provider_release.wait(timeout=5)
        return _telegram_response(message_id=910)

    provider_deadline = 2.0
    recovery_margin = 5.0
    active_executor = BoundedProviderExecutor(max_workers=1)
    clarification_service = _clarification_service(sessions)
    telegram_config = SydneyTelegramDispatcherConfig(
        enabled=True,
        bot_token="123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd",
        brandon_chat_id=CHAT_ID,
        clarification_code_keys={CODE_KEY_VERSION: CODE_KEY},
        active_code_key_version=CODE_KEY_VERSION,
        provider_deadline_seconds=provider_deadline,
        provider_socket_timeout_seconds=1,
    )
    active_dispatcher = SydneyTelegramDispatcher(
        sessionmaker=sessions,
        executor=active_executor,
        send_message=stalled_send,
        config=telegram_config,
        clock=clock,
    )
    active_job = SydneyQuestionsJob(
        enabled=True,
        sessionmaker=sessions,
        clarification_service=clarification_service,
        dispatcher=active_dispatcher,
        batch_size=20,
        clock=clock,
    )
    active_run = asyncio.create_task(active_job.run())
    try:
        assert await asyncio.to_thread(provider_entered.wait, 1)
        async with sessions() as session:
            clarification = await session.scalar(sa.select(CRMTaskClarification))
            initial = await session.scalar(
                sa.select(SydneyQuestionOutbox).where(
                    SydneyQuestionOutbox.attempt_kind == "initial"
                )
            )
        assert clarification is not None
        assert initial is not None and initial.state == "sending"

        clock.value = NOW + timedelta(seconds=provider_deadline + recovery_margin + 1)
        await active_job.run()
        async with sessions() as session:
            active_attempt = await session.get(SydneyQuestionOutbox, initial.id)
        assert active_attempt is not None and active_attempt.state == "sending"
        assert send_calls == 1

        provider_release.set()
        await asyncio.wait_for(active_run, timeout=2)
        async with sessions() as session:
            sent_attempt = await session.get(SydneyQuestionOutbox, initial.id)
        assert sent_attempt is not None and sent_attempt.state == "sent"

        clock.value = sent_attempt.sent_at + timedelta(hours=24)
        reminder_id = await active_dispatcher.enqueue_due_reminder(clarification.id)
        assert isinstance(reminder_id, UUID)
        crash_started_at = clock.value
        async with sessions() as session, session.begin():
            reminder = await session.get(SydneyQuestionOutbox, reminder_id)
            assert reminder is not None and reminder.state == "pending"
            reminder.state = "sending"
            reminder.attempted_at = crash_started_at
            reminder.telegram_chat_id = CHAT_ID
            reminder.updated_at = crash_started_at

        restart_clock = _MutableClock(
            crash_started_at + timedelta(seconds=provider_deadline + recovery_margin)
        )
        restart_send_calls = 0

        def forbidden_restart_send(**_kwargs):
            nonlocal restart_send_calls
            restart_send_calls += 1
            return _telegram_response(message_id=911)

        restarted_dispatcher = SydneyTelegramDispatcher(
            sessionmaker=sessions,
            executor=_InlineExecutor(),
            send_message=forbidden_restart_send,
            config=telegram_config,
            clock=restart_clock,
        )
        restarted_job = SydneyQuestionsJob(
            enabled=True,
            sessionmaker=sessions,
            clarification_service=clarification_service,
            dispatcher=restarted_dispatcher,
            batch_size=20,
            clock=restart_clock,
        )
        await restarted_job.run()
        async with sessions() as session:
            boundary_attempt = await session.get(SydneyQuestionOutbox, reminder_id)
        assert boundary_attempt is not None and boundary_attempt.state == "sending"

        restart_clock.value += timedelta(microseconds=1)
        await asyncio.gather(restarted_job.run(), restarted_job.run())
        recovered_at = restart_clock.value
        async with sessions() as session:
            recovered = await session.get(SydneyQuestionOutbox, reminder_id)
            audit = AgentActionAudit(
                actor="command_admin",
                action_id="task9-restart-telegram-reconciliation",
                method="POST",
                path="/api/v1/admin/sydney/reconcile",
                status_code=200,
                allowed=True,
            )
            session.add(audit)
            await session.commit()
            await session.refresh(audit)
        assert recovered is not None and recovered.state == "delivery_uncertain"
        assert recovered.failure_category == "worker_interrupted"
        assert recovered.updated_at == recovered_at
        assert restart_send_calls == 0
        assert send_calls == 1

        assert await restarted_dispatcher.reconcile_attempt(
            reminder_id,
            "delivery_uncertain",
            "not_delivered",
            "Operator verified the interrupted reminder was not delivered.",
            audit.id,
            None,
            None,
        )
        with pytest.raises(
            TelegramDispatchError,
            match="telegram_reconciliation_stale",
        ):
            await restarted_dispatcher.reconcile_attempt(
                reminder_id,
                "delivery_uncertain",
                "not_delivered",
                "Replay must not mutate the attempt.",
                audit.id,
                None,
                None,
            )
    finally:
        provider_release.set()
        if not active_run.done():
            active_run.cancel()
            await asyncio.gather(active_run, return_exceptions=True)
        await active_executor.wait_for_tracked_calls()
        active_executor.shutdown()


def test_task7_task8_rollout_flags_keep_all_task9_jobs_dormant_by_default() -> None:
    from config import Settings
    from workers.integration_worker import build_job_registry

    config = Settings(JWT_SECRET="test-secret")
    registry = build_job_registry(config=config)
    registry.initialize()
    snapshot = {
        name: enabled for name, enabled, _interval in registry.readiness_snapshot()
    }
    assert snapshot == {
        "gmail_history": False,
        "gmail_receipts": False,
        "instagram_health": False,
        "integration_alerts": True,
        "notification_delivery": True,
        "sydney_questions": False,
    }
    assert config.GMAIL_TASK_INTAKE_ENABLED is False
    assert config.SYDNEY_TASK_QUESTIONS_ENABLED is False
    assert config.CRM_TASK_ARCHIVE_ENABLED is False


@pytest.mark.asyncio
async def test_question_job_enforces_five_round_ceiling_without_sixth_outbox(
    e2e_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox
    from services.crm_task_suggestion_service import canonical_task_payload_hash

    _engine, sessions = e2e_runtime
    suggestion = CRMTaskSuggestion(
        source_type="sydney_chat",
        source_scope_key="sydney:round-ceiling-e2e",
        source_action_key="sydney-round-ceiling-e2e",
        source_request_id=UUID("00000000-0000-0000-0000-000000000909"),
        contact_resolution_state="not_provided",
        title="Confirm the follow-up time",
        description="The due time remains ambiguous.",
        priority="normal",
        task_status="open",
        state="needs_clarification",
        clarification_state="pending",
        blocker_codes=["ambiguous_due_at"],
        payload_hash=canonical_task_payload_hash(
            title="Confirm the follow-up time",
            description="The due time remains ambiguous.",
            priority="normal",
            due_at=None,
            contact_id=None,
            status="open",
        ),
        model_schema_version="sydney-task-v1",
        obligation_fingerprint="8" * 64,
        confidence=1,
        rationale="Controlled round-ceiling fixture.",
        version=6,
    )
    async with sessions() as session:
        session.add(suggestion)
        await session.flush()
        for round_number in range(1, 6):
            session.add(
                CRMTaskClarification(
                    suggestion_id=suggestion.id,
                    suggestion_version=round_number,
                    field_name="due_at",
                    round_number=round_number,
                    telegram_chat_id=CHAT_ID,
                    code_hash=bytes([round_number]) * 32,
                    code_key_version=CODE_KEY_VERSION,
                    options_json="{}",
                    state="answered",
                    answer_json='{"decision":"no_due_date","kind":"due_at"}',
                    deadline_anchor_kind="created",
                    deadline_anchored_at=NOW - timedelta(days=round_number),
                    slot_deadline_at=(
                        NOW - timedelta(days=round_number) + timedelta(hours=48)
                    ),
                    resolved_at=NOW,
                    created_at=NOW - timedelta(days=round_number),
                    updated_at=NOW,
                )
            )
        await session.commit()
        await session.refresh(suggestion)

    result = await _clarification_service(sessions).enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Client",
        subject_preview="Follow-up time",
        now=NOW,
    )
    assert result.created is False
    assert result.reason == "clarification_round_limit"
    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion.id)
        clarification_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskClarification.id)).where(
                CRMTaskClarification.suggestion_id == suggestion.id
            )
        )
        outbox_count = await session.scalar(
            sa.select(sa.func.count(SydneyQuestionOutbox.id))
        )
    assert stored is not None
    assert stored.clarification_state == "manual_review_required"
    assert clarification_count == 5
    assert outbox_count == 0


def test_no_raw_gmail_body_is_declared_on_any_durable_intake_model() -> None:
    from models.gmail_task_intake import (
        GmailExtractedObligation,
        GmailExtractionAttempt,
        GmailMessageOrigin,
        GmailMessageReceipt,
    )

    durable_columns = {
        column.name
        for model in (
            GmailMessageReceipt,
            GmailMessageOrigin,
            GmailExtractionAttempt,
            GmailExtractedObligation,
        )
        for column in model.__table__.columns
    }
    assert "body" not in durable_columns
    assert "body_text" not in durable_columns
    assert "raw_body" not in durable_columns
    assert "raw_response" not in durable_columns
