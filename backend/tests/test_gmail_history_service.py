from __future__ import annotations

import asyncio
import gc
import hashlib
import logging
import traceback
import weakref
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "83c6f4e8a1b2"
UTC = timezone.utc


async def _noop_alert_sink(**_event) -> None:
    return None


@pytest.fixture(scope="module")
def history_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def history_runtime(history_database):
    url, sync_engine = history_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE gmail_sync_accounts, agent_action_audits CASCADE"
            )
        )
    engine = create_async_engine(async_test_url(url), pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessionmaker
    finally:
        await engine.dispose()


async def _seed_account(sessionmaker, *, cursor: str = "100", email: str | None = None):
    from models.gmail_task_intake import GmailSyncAccount

    account = GmailSyncAccount(
        workspace_email=email or f"account-{uuid4()}@example.test",
        committed_history_id=cursor,
        mode="shadow",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.commit()
        await session.refresh(account)
    return account


def _metadata(message_id: str, thread_id: str, labels: tuple[str, ...]):
    from services.gmail_history_adapter import GmailMessageMetadata

    return GmailMessageMetadata(
        message_id=message_id,
        thread_id=thread_id,
        label_ids=labels,
        message_at=datetime(2026, 8, 21, 14, 0, tzinfo=UTC),
        headers={
            "subject": f"Subject {message_id}",
            "from": "client@example.test",
            "to": "account@example.test",
        },
    )


def _page(
    *,
    history_id: str,
    next_page_token: str | None,
    messages: tuple[tuple[str, str], ...],
    history_min: str,
    history_max: str,
):
    from services.gmail_history_adapter import GmailHistoryMessageRef, GmailHistoryPage

    return GmailHistoryPage(
        history_id=history_id,
        next_page_token=next_page_token,
        messages=tuple(
            GmailHistoryMessageRef(message_id=message_id, thread_id=thread_id)
            for message_id, thread_id in messages
        ),
        discovered_history_id_min=history_min,
        discovered_history_id_max=history_max,
    )


class _ScriptedAdapter:
    def __init__(self, pages, metadata, *, pause: asyncio.Event | None = None):
        self.pages = pages
        self.metadata = metadata
        self.pause = pause
        self.entered = asyncio.Event()
        self.history_calls: list[tuple[str, str, str | None]] = []
        self.metadata_calls: list[tuple[str, str]] = []

    async def list_history(
        self,
        *,
        account_key: str,
        start_history_id: str,
        page_token: str | None,
    ):
        self.history_calls.append((account_key, start_history_id, page_token))
        self.entered.set()
        if self.pause is not None:
            await self.pause.wait()
        result = self.pages[page_token]
        if isinstance(result, BaseException):
            raise result
        return result

    async def get_message_metadata(self, *, account_key: str, message_id: str):
        self.metadata_calls.append((account_key, message_id))
        return self.metadata[message_id]


async def test_each_page_commits_but_only_terminal_page_advances_cursor(
    history_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")
    first_page = _page(
        history_id="102",
        next_page_token="page-2",
        messages=(("message-1", "thread-1"),),
        history_min="101",
        history_max="102",
    )
    crashing_adapter = _ScriptedAdapter(
        {
            None: first_page,
            "page-2": RuntimeError("synthetic worker crash"),
        },
        {"message-1": _metadata("message-1", "thread-1", ("INBOX",))},
    )
    service = GmailHistoryService(
        engine=engine,
        adapter=crashing_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )

    verifier = await engine.connect()

    try:
        with pytest.raises(RuntimeError, match="synthetic worker crash"):
            await service.sync_account(account.id)
        from services.integration_advisory_locks import (
            release_session_advisory_lock,
            try_session_advisory_lock,
        )

        assert await try_session_advisory_lock(verifier, account.id)
        assert await release_session_advisory_lock(verifier, account.id)
        await verifier.commit()
    finally:
        await verifier.close()

    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )
        checkpoints = list(
            (
                await session.scalars(
                    sa.select(GmailSyncPageCheckpoint).where(
                        GmailSyncPageCheckpoint.run_id == run.id
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

    assert stored_account.committed_history_id == "100"
    assert run.start_history_id == "100"
    assert run.next_page_token == "page-2"
    assert run.state == "running"
    assert [(item.page_number, item.next_page_token) for item in checkpoints] == [
        (1, "page-2")
    ]
    assert [(item.gmail_message_id, item.processing_state) for item in receipts] == [
        ("message-1", "pending")
    ]

    second_page = _page(
        history_id="105",
        next_page_token=None,
        messages=(("message-2", "thread-2"),),
        history_min="103",
        history_max="105",
    )
    resume_adapter = _ScriptedAdapter(
        {"page-2": second_page},
        {"message-2": _metadata("message-2", "thread-2", ("SENT",))},
    )
    resumed = GmailHistoryService(
        engine=engine,
        adapter=resume_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    result = await resumed.sync_account(account.id)

    assert result.lock_acquired is True
    assert result.start_history_id == "100"
    assert result.committed_history_id == "105"
    assert result.pages_committed == 1
    assert resume_adapter.history_calls == [(str(account.id), "100", "page-2")]

    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )
        checkpoints = list(
            (
                await session.scalars(
                    sa.select(GmailSyncPageCheckpoint)
                    .where(GmailSyncPageCheckpoint.run_id == run.id)
                    .order_by(GmailSyncPageCheckpoint.page_number)
                )
            ).all()
        )
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt)
                    .where(GmailMessageReceipt.account_id == account.id)
                    .order_by(GmailMessageReceipt.gmail_message_id)
                )
            ).all()
        )

    assert stored_account.committed_history_id == "105"
    assert run.state == "completed"
    assert run.terminal_history_id == "105"
    assert run.next_page_token is None
    assert [(item.page_number, item.next_page_token) for item in checkpoints] == [
        (1, "page-2"),
        (2, None),
    ]
    assert [(item.gmail_message_id, item.direction) for item in receipts] == [
        ("message-1", "received"),
        ("message-2", "sent"),
    ]


async def test_session_lock_excludes_same_account_but_not_another_account(
    history_runtime,
) -> None:
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    first_account = await _seed_account(sessionmaker, cursor="200")
    second_account = await _seed_account(sessionmaker, cursor="300")
    release = asyncio.Event()
    first_adapter = _ScriptedAdapter(
        {
            None: _page(
                history_id="201",
                next_page_token=None,
                messages=(),
                history_min="201",
                history_max="201",
            )
        },
        {},
        pause=release,
    )
    same_adapter = _ScriptedAdapter({}, {})
    other_adapter = _ScriptedAdapter(
        {
            None: _page(
                history_id="301",
                next_page_token=None,
                messages=(),
                history_min="301",
                history_max="301",
            )
        },
        {},
    )
    first_service = GmailHistoryService(
        engine=engine,
        adapter=first_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    same_service = GmailHistoryService(
        engine=engine,
        adapter=same_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    other_service = GmailHistoryService(
        engine=engine,
        adapter=other_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )

    first_task = asyncio.create_task(first_service.sync_account(first_account.id))
    await asyncio.wait_for(first_adapter.entered.wait(), timeout=2)
    same_result = await asyncio.wait_for(
        same_service.sync_account(first_account.id), timeout=1
    )
    other_result = await asyncio.wait_for(
        other_service.sync_account(second_account.id), timeout=1
    )

    assert same_result.lock_acquired is False
    assert same_adapter.history_calls == []
    assert other_result.lock_acquired is True
    assert other_result.committed_history_id == "301"

    release.set()
    first_result = await asyncio.wait_for(first_task, timeout=2)
    assert first_result.lock_acquired is True
    assert first_result.committed_history_id == "201"


async def test_same_backend_session_lock_survives_page_commit_then_unlocks_in_finally(
    history_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
    )
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="350")
    other = await _seed_account(sessionmaker, cursor="450")

    class _PageBoundaryAdapter:
        def __init__(self):
            self.second_page_entered = asyncio.Event()
            self.release_second_page = asyncio.Event()

        async def list_history(self, *, page_token, **_kwargs):
            if page_token is None:
                return _page(
                    history_id="351",
                    next_page_token="page-2",
                    messages=(("mid-message", "mid-thread"),),
                    history_min="351",
                    history_max="351",
                )
            self.second_page_entered.set()
            await self.release_second_page.wait()
            return _page(
                history_id="352",
                next_page_token=None,
                messages=(),
                history_min="352",
                history_max="352",
            )

        async def get_message_metadata(self, **_kwargs):
            return _metadata("mid-message", "mid-thread", ("INBOX",))

    adapter = _PageBoundaryAdapter()
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    verifier = await engine.connect()
    verifier_pid = await verifier.scalar(sa.text("SELECT pg_backend_pid()"))
    running = asyncio.create_task(service.sync_account(account.id))
    await asyncio.wait_for(adapter.second_page_entered.wait(), timeout=2)

    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
    )

    assert not await try_session_advisory_lock(verifier, account.id)
    await verifier.commit()

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        checkpoint_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncPageCheckpoint)
        )
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
    assert stored.committed_history_id == "350"
    assert checkpoint_count == 1
    assert receipt_count == 1

    contender = GmailHistoryService(
        engine=engine,
        adapter=_ScriptedAdapter({}, {}),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    same = await asyncio.wait_for(contender.sync_account(account.id), timeout=1)
    assert same.lock_acquired is False
    other_service = GmailHistoryService(
        engine=engine,
        adapter=_ScriptedAdapter(
            {
                None: _page(
                    history_id="451",
                    next_page_token=None,
                    messages=(),
                    history_min="451",
                    history_max="451",
                )
            },
            {},
        ),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    other_result = await asyncio.wait_for(other_service.sync_account(other.id), timeout=1)
    assert other_result.committed_history_id == "451"

    adapter.release_second_page.set()
    result = await asyncio.wait_for(running, timeout=2)
    assert len(result.page_backend_pids) == 2
    assert len(set(result.page_backend_pids)) == 1
    assert result.page_backend_pids[0] != verifier_pid

    try:
        assert await try_session_advisory_lock(verifier, account.id)
        assert await release_session_advisory_lock(verifier, account.id)
        await verifier.commit()
    finally:
        await verifier.close()


async def test_asyncio_cancellation_releases_session_lock_without_partial_page(
    history_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
    )
    from services.gmail_history_service import GmailHistoryService
    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
    )

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")
    pause = asyncio.Event()
    adapter = _ScriptedAdapter(
        {
            None: _page(
                history_id="101",
                next_page_token=None,
                messages=(("cancel-message", "cancel-thread"),),
                history_min="101",
                history_max="101",
            )
        },
        {
            "cancel-message": _metadata(
                "cancel-message", "cancel-thread", ("INBOX",)
            )
        },
        pause=pause,
    )
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    verifier = await engine.connect()
    verifier_pid = await verifier.scalar(sa.text("SELECT pg_backend_pid()"))
    pending = asyncio.create_task(service.sync_account(account.id))
    try:
        await asyncio.wait_for(adapter.entered.wait(), timeout=2)
        assert not await try_session_advisory_lock(verifier, account.id)
        await verifier.commit()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

        assert await try_session_advisory_lock(verifier, account.id)
        assert await release_session_advisory_lock(verifier, account.id)
        await verifier.commit()
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await verifier.close()

    assert verifier_pid is not None
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
        checkpoint_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncPageCheckpoint)
        )
    assert stored.committed_history_id == "100"
    assert receipt_count == 0
    assert checkpoint_count == 0


async def test_receipts_and_checkpoint_roll_back_together_on_page_failure(
    history_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
    )
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailPagePersistenceError,
    )

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")
    adapter = _ScriptedAdapter(
        {
            None: _page(
                history_id="101",
                next_page_token=None,
                messages=(
                    ("valid-first", "valid-thread"),
                    ("invalid-second", "x" * 300),
                ),
                history_min="101",
                history_max="101",
            )
        },
        {
            "valid-first": _metadata("valid-first", "valid-thread", ("INBOX",)),
            "invalid-second": _metadata("invalid-second", "x" * 300, ("INBOX",)),
        },
    )
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    with pytest.raises(
        GmailPagePersistenceError, match="gmail_history_page_persistence_failed"
    ):
        await service.sync_account(account.id)

    assert adapter.metadata_calls == [
        (str(account.id), "valid-first"),
        (str(account.id), "invalid-second"),
    ]

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
        checkpoint_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncPageCheckpoint)
        )
    assert stored.committed_history_id == "100"
    assert receipt_count == 0
    assert checkpoint_count == 0


async def test_history_ingestion_persists_label_and_origin_suppression_matrix(
    history_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageMetadata
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(
        sessionmaker,
        cursor="100",
        email="brandon@example.test",
    )
    async with sessionmaker() as session:
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
        origin = GmailMessageOrigin(
            account_id=account.id,
            request_id=uuid4(),
            canonical_send_hash="a" * 64,
            canonical_envelope_hash="b" * 64,
            canonical_body_hash="c" * 64,
            gmail_message_id="labels-automation",
            gmail_thread_id="thread-automation",
            origin_kind="system_automation",
            delivery_state="succeeded",
            version=2,
            action_audit_id=audit.id,
        )
        session.add(origin)
        await session.commit()

    page = _page(
        history_id="101",
        next_page_token=None,
        messages=(
            ("labels-received", "thread-received"),
            ("labels-sent", "thread-sent"),
            ("labels-draft", "thread-draft"),
            ("labels-spam", "thread-spam"),
            ("labels-trash", "thread-trash"),
            ("labels-self", "thread-self"),
            ("labels-header-automation", "thread-header-automation"),
            ("labels-automation", "thread-automation"),
        ),
        history_min="101",
        history_max="101",
    )

    def metadata(
        message_id,
        thread_id,
        labels,
        from_value,
        to_value,
        extra_headers=None,
    ):
        headers = {
            "subject": message_id,
            "from": from_value,
            "to": to_value,
        }
        headers.update(extra_headers or {})
        return GmailMessageMetadata(
            message_id=message_id,
            thread_id=thread_id,
            label_ids=labels,
            message_at=datetime(2026, 8, 21, 14, 0, tzinfo=UTC),
            headers=headers,
        )

    adapter = _ScriptedAdapter(
        {None: page},
        {
            "labels-received": metadata(
                "labels-received",
                "thread-received",
                ("INBOX",),
                "client@example.test",
                account.workspace_email,
            ),
            "labels-sent": metadata(
                "labels-sent",
                "thread-sent",
                ("SENT",),
                account.workspace_email,
                "client@example.test",
            ),
            "labels-draft": metadata(
                "labels-draft",
                "thread-draft",
                ("DRAFT", "SENT"),
                account.workspace_email,
                "client@example.test",
            ),
            "labels-spam": metadata(
                "labels-spam",
                "thread-spam",
                ("SPAM", "INBOX"),
                "spam@example.test",
                account.workspace_email,
            ),
            "labels-trash": metadata(
                "labels-trash",
                "thread-trash",
                ("TRASH", "SENT"),
                account.workspace_email,
                "client@example.test",
            ),
            "labels-self": metadata(
                "labels-self",
                "thread-self",
                ("INBOX", "SENT"),
                account.workspace_email,
                account.workspace_email,
            ),
            "labels-header-automation": metadata(
                "labels-header-automation",
                "thread-header-automation",
                ("INBOX",),
                "automation@example.test",
                account.workspace_email,
                {"auto-submitted": "auto-generated"},
            ),
            "labels-automation": metadata(
                "labels-automation",
                "thread-automation",
                ("SENT",),
                account.workspace_email,
                "client@example.test",
            ),
        },
    )
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    await service.sync_account(account.id)

    async with sessionmaker() as session:
        rows = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt)
                    .where(GmailMessageReceipt.account_id == account.id)
                    .order_by(GmailMessageReceipt.gmail_message_id)
                )
            ).all()
        )
    assert [
        (
            row.gmail_message_id,
            row.direction,
            row.classification,
            row.processing_state,
        )
        for row in rows
    ] == [
        ("labels-automation", "sent", "ignored_system_automation", "ignored"),
        ("labels-draft", "sent", "ignored_draft", "ignored"),
        ("labels-header-automation", "received", "ignored_automation", "ignored"),
        ("labels-received", "received", "eligible", "pending"),
        ("labels-self", "self_copy", "eligible", "pending"),
        ("labels-sent", "sent", "eligible", "pending"),
        ("labels-spam", "received", "ignored_spam", "ignored"),
        ("labels-trash", "sent", "ignored_trash", "ignored"),
    ]


async def test_history_pipeline_composes_sent_origin_convergence_and_human_send(
    history_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from models.setting import Setting
    from schemas.agent_control import WorkspaceGmailSendRequest
    from services.gmail_history_adapter import (
        GmailMessageContent,
        GmailMessageMetadata,
    )
    from services.gmail_history_service import GmailHistoryService
    from services.gmail_message_sanitizer import participant_hmac
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker = history_runtime
    account = await _seed_account(
        sessionmaker,
        cursor="100",
        email="brandon@example.test",
    )
    async with sessionmaker() as session:
        session.add_all(
            [
                Setting(
                    key="google_workspace_gmail_account_id",
                    value=str(account.id),
                ),
                Setting(
                    key="google_workspace_refresh_token",
                    value="compose-database-token",
                ),
            ]
        )
        await session.commit()

    class _URL:
        path = "/api/v1/agent-control/workspace/gmail/send"

    class _Request:
        method = "POST"
        url = _URL()

    payload = WorkspaceGmailSendRequest(
        request_id=uuid4(),
        to=["client@example.test"],
        cc=[],
        bcc=[],
        subject="Composed Sydney commitment",
        body_text="I will send the report Friday.",
        confirmed_by_brandon=True,
    )
    executor = BoundedProviderExecutor(max_workers=1)
    origin_service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History must never send"),
        deadline_seconds=1,
    )
    intent = await origin_service.claim_intent_only(
        payload=payload,
        request=_Request(),
        actor="hermes",
    )
    await origin_service.mark_delivery_uncertain(
        origin_id=intent.id,
        expected_version=1,
        category="provider_timeout",
    )

    messages = {
        "compose-sydney": GmailMessageContent(
            message_id="compose-sydney",
            thread_id="compose-thread-sydney",
            label_ids=("SENT",),
            message_at=intent.created_at,
            headers={
                "subject": payload.subject,
                "from": account.workspace_email,
                "to": payload.to[0],
                "cc": "",
                "bcc": "",
            },
            body_text=f"{payload.body_text}\n",
        ),
        "compose-human": GmailMessageContent(
            message_id="compose-human",
            thread_id="compose-thread-human",
            label_ids=("SENT",),
            message_at=intent.created_at,
            headers={
                "subject": "Manual follow-up",
                "from": account.workspace_email,
                "to": "other@example.test",
                "cc": "",
                "bcc": "",
            },
            body_text="Manual sent-message body canary.\n",
        ),
    }

    class _ComposedAdapter(_ScriptedAdapter):
        async def get_message_content(self, *, account_key, message_id):
            assert account_key == str(account.id)
            return messages[message_id]

    page = _page(
        history_id="101",
        next_page_token=None,
        messages=(
            ("compose-sydney", "compose-thread-sydney"),
            ("compose-human", "compose-thread-human"),
        ),
        history_min="101",
        history_max="101",
    )
    metadata = {
        message_id: GmailMessageMetadata(
            message_id=message.message_id,
            thread_id=message.thread_id,
            label_ids=message.label_ids,
            message_at=message.message_at,
            headers=message.headers,
        )
        for message_id, message in messages.items()
    }
    service = GmailHistoryService(
        engine=engine,
        adapter=_ComposedAdapter({None: page}, metadata),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        origin_observer=origin_service,
    )
    try:
        await service.sync_account(account.id)
        replay_page = _page(
            history_id="102",
            next_page_token=None,
            messages=(
                ("compose-sydney", "compose-thread-sydney"),
                ("compose-human", "compose-thread-human"),
            ),
            history_min="102",
            history_max="102",
        )
        replay = GmailHistoryService(
            engine=engine,
            adapter=_ComposedAdapter({None: replay_page}, metadata),
            participant_hash_key=b"test-participant-key-with-32-bytes",
            origin_observer=origin_service,
        )
        await replay.sync_account(account.id)
    finally:
        executor.shutdown()

    async with sessionmaker() as session:
        origins = list(
            (
                await session.scalars(
                    sa.select(GmailMessageOrigin)
                    .where(GmailMessageOrigin.account_id == account.id)
                    .order_by(GmailMessageOrigin.gmail_message_id)
                )
            ).all()
        )
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt)
                    .where(GmailMessageReceipt.account_id == account.id)
                    .order_by(GmailMessageReceipt.gmail_message_id)
                )
            ).all()
        )
    assert [(row.gmail_message_id, row.origin_kind) for row in origins] == [
        ("compose-human", "human_send"),
        ("compose-sydney", "sydney_client_send"),
    ]
    assert origins[1].id == intent.id
    assert origins[1].delivery_state == "succeeded"
    assert [row.gmail_message_id for row in receipts] == [
        "compose-human",
        "compose-sydney",
    ]
    assert all(row.processing_state == "pending" for row in receipts)
    expected_sender = participant_hmac(
        account.workspace_email,
        b"test-participant-key-with-32-bytes",
    )
    expected_recipients = {
        "compose-human": [
            participant_hmac(
                "other@example.test",
                b"test-participant-key-with-32-bytes",
            )
        ],
        "compose-sydney": [
            participant_hmac(
                "client@example.test",
                b"test-participant-key-with-32-bytes",
            )
        ],
    }
    assert all(row.sender_hmac == expected_sender for row in receipts)
    assert {
        row.gmail_message_id: __import__("json").loads(row.recipient_hmacs_json)
        for row in receipts
    } == expected_recipients
    assert all(row.classification == "eligible" for row in receipts)
    persisted = "|".join(
        str(value)
        for row in receipts
        for value in (
            row.subject_preview,
            row.body_hash,
            row.classification,
            row.failure_message,
        )
    )
    assert "Manual sent-message body canary" not in persisted
    assert payload.body_text not in persisted


async def test_history_composition_metadata_gates_ignored_sent_without_body_fetch(
    history_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import (
        GmailMessageOrigin,
        GmailMessageReceipt,
    )
    from services.gmail_history_adapter import GmailMessageMetadata
    from services.gmail_history_service import GmailHistoryService
    from services.gmail_message_sanitizer import participant_hmac
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker = history_runtime
    account = await _seed_account(
        sessionmaker,
        cursor="100",
        email="brandon@example.test",
    )
    async with sessionmaker() as session:
        audit = AgentActionAudit(
            actor="system:notification",
            action_id="workspace.gmail.send.intent",
            method="POST",
            path="/internal/notification",
            status_code=202,
            allowed=True,
            request_meta_json="{}",
            response_meta_json="{}",
        )
        session.add(audit)
        await session.flush()
        origin = GmailMessageOrigin(
            account_id=account.id,
            request_id=uuid4(),
            canonical_send_hash="a" * 64,
            canonical_envelope_hash="b" * 64,
            canonical_body_hash="c" * 64,
            gmail_message_id="ignored-system",
            gmail_thread_id="thread-ignored-system",
            origin_kind="system_automation",
            delivery_state="succeeded",
            version=2,
            action_audit_id=audit.id,
        )
        session.add(origin)
        session.add(
            GmailMessageReceipt(
                account_id=account.id,
                gmail_message_id="ignored-system",
                gmail_thread_id="thread-ignored-system",
                direction="sent",
                message_at=datetime(2026, 8, 21, 19, 0, tzinfo=UTC),
                sender_hmac=None,
                recipient_hmacs_json="[]",
                subject_preview=None,
                body_hash="c" * 64,
                labels_json='["SENT"]',
                processing_state="ignored",
                classification="ignored_system_automation",
            )
        )
        await session.commit()

    definitions = {
        "ignored-draft": (("DRAFT", "SENT"), {}),
        "ignored-spam": (("SPAM", "SENT"), {}),
        "ignored-trash": (("TRASH", "SENT"), {}),
        "ignored-header": (("SENT",), {"auto-submitted": "auto-generated"}),
        "ignored-system": (("SENT",), {}),
    }
    metadata = {
        message_id: GmailMessageMetadata(
            message_id=message_id,
            thread_id=f"thread-{message_id}",
            label_ids=labels,
            message_at=datetime(2026, 8, 21, 19, 0, tzinfo=UTC),
            headers={
                "subject": message_id,
                "from": account.workspace_email,
                "to": "client@example.test",
                **extra_headers,
            },
        )
        for message_id, (labels, extra_headers) in definitions.items()
    }
    page = _page(
        history_id="101",
        next_page_token=None,
        messages=tuple(
            (message_id, f"thread-{message_id}") for message_id in definitions
        ),
        history_min="101",
        history_max="101",
    )

    class _IgnoredAdapter(_ScriptedAdapter):
        content_calls: list[str] = []

        async def get_message_content(self, *, account_key, message_id):
            self.content_calls.append(message_id)
            raise AssertionError("ignored metadata must never fetch a Gmail body")

    adapter = _IgnoredAdapter({None: page}, metadata)
    executor = BoundedProviderExecutor(max_workers=1)
    origin_service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History must never send"),
        deadline_seconds=1,
    )
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        origin_observer=origin_service,
    )
    try:
        await service.sync_account(account.id)
    finally:
        executor.shutdown()

    assert adapter.content_calls == []
    async with sessionmaker() as session:
        rows = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt)
                    .where(GmailMessageReceipt.account_id == account.id)
                    .order_by(GmailMessageReceipt.gmail_message_id)
                )
            ).all()
        )
        origins = list(
            (
                await session.scalars(
                    sa.select(GmailMessageOrigin).where(
                        GmailMessageOrigin.account_id == account.id
                    )
                )
            ).all()
        )
    assert [(row.gmail_message_id, row.classification) for row in rows] == [
        ("ignored-draft", "ignored_draft"),
        ("ignored-header", "ignored_automation"),
        ("ignored-spam", "ignored_spam"),
        ("ignored-system", "ignored_system_automation"),
        ("ignored-trash", "ignored_trash"),
    ]
    expected_sender = participant_hmac(
        account.workspace_email,
        b"test-participant-key-with-32-bytes",
    )
    expected_recipient = participant_hmac(
        "client@example.test",
        b"test-participant-key-with-32-bytes",
    )
    assert all(row.processing_state == "ignored" for row in rows)
    assert all(row.sender_hmac == expected_sender for row in rows)
    assert all(
        __import__("json").loads(row.recipient_hmacs_json)
        == [expected_recipient]
        for row in rows
    )
    assert [(row.gmail_message_id, row.origin_kind) for row in origins] == [
        ("ignored-system", "system_automation")
    ]


async def test_history_composition_releases_each_sent_body_before_fetching_next(
    history_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import (
        GmailMessageContent,
        GmailMessageMetadata,
    )
    from services.gmail_history_service import GmailHistoryService
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker = history_runtime
    account = await _seed_account(
        sessionmaker,
        cursor="100",
        email="brandon@example.test",
    )
    message_ids = tuple(f"stream-sent-{index}" for index in range(3))
    metadata = {
        message_id: GmailMessageMetadata(
            message_id=message_id,
            thread_id=f"thread-{message_id}",
            label_ids=("SENT",),
            message_at=datetime(2026, 8, 21, 20, index, tzinfo=UTC),
            headers={
                "subject": f"Stream {index}",
                "from": account.workspace_email,
                "to": f"client-{index}@example.test",
            },
        )
        for index, message_id in enumerate(message_ids)
    }
    page = _page(
        history_id="101",
        next_page_token=None,
        messages=tuple(
            (message_id, f"thread-{message_id}") for message_id in message_ids
        ),
        history_min="101",
        history_max="101",
    )

    class _StreamingAdapter(_ScriptedAdapter):
        def __init__(self):
            super().__init__({None: page}, metadata)
            self.body_refs: list[weakref.ReferenceType] = []

        async def get_message_content(self, *, account_key, message_id):
            assert account_key == str(account.id)
            gc.collect()
            assert all(reference() is None for reference in self.body_refs)
            row = metadata[message_id]
            content = GmailMessageContent(
                message_id=row.message_id,
                thread_id=row.thread_id,
                label_ids=row.label_ids,
                message_at=row.message_at,
                headers=row.headers,
                body_text=f"transient raw body {message_id}\n",
            )
            self.body_refs.append(weakref.ref(content))
            return content

    adapter = _StreamingAdapter()
    executor = BoundedProviderExecutor(max_workers=1)
    origin_service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History must never send"),
        deadline_seconds=1,
    )
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        origin_observer=origin_service,
    )
    try:
        await service.sync_account(account.id)
    finally:
        executor.shutdown()
    gc.collect()
    assert all(reference() is None for reference in adapter.body_refs)

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
    assert len(origins) == len(message_ids)
    assert {row.origin_kind for row in origins} == {"human_send"}
    assert len(receipts) == len(message_ids)
    persisted = "|".join(
        str(value)
        for row in receipts
        for value in row.__dict__.values()
    )
    assert "transient raw body" not in persisted


@pytest.mark.parametrize("failure_mode", ["identity_mismatch", "sanitize_failure"])
async def test_history_composition_releases_raw_before_failure_persistence(
    history_runtime,
    failure_mode: str,
) -> None:
    from services.gmail_history_adapter import (
        GmailMessageContent,
        GmailMessageMetadata,
        GmailProviderFailure,
    )
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(
        sessionmaker,
        cursor="100",
        email="brandon@example.test",
    )
    message_id = f"history-raw-failure-{failure_mode}"
    thread_id = f"history-raw-thread-{failure_mode}"
    metadata = GmailMessageMetadata(
        message_id=message_id,
        thread_id=thread_id,
        label_ids=("SENT",),
        message_at=datetime(2026, 8, 21, 20, 30, tzinfo=UTC),
        headers={
            "subject": "History raw lifetime",
            "from": account.workspace_email,
            "to": "client@example.test",
        },
    )
    raw_canary = f"history-raw-{failure_mode}-canary"
    raw_ref: weakref.ReferenceType | None = None

    class _FailureAdapter(_ScriptedAdapter):
        async def get_message_content(self, **_kwargs):
            nonlocal raw_ref
            content = GmailMessageContent(
                message_id=(
                    "wrong-history-message"
                    if failure_mode == "identity_mismatch"
                    else message_id
                ),
                thread_id=thread_id,
                label_ids=("SENT",),
                message_at=metadata.message_at,
                headers=metadata.headers,
                body_text=raw_canary,
                body_media_type=(
                    "invalid/media"
                    if failure_mode == "sanitize_failure"
                    else "text/plain"
                ),
            )
            raw_ref = weakref.ref(content)
            return content

    adapter = _FailureAdapter(
        {
            None: _page(
                history_id="101",
                next_page_token=None,
                messages=((message_id, thread_id),),
                history_min="101",
                history_max="101",
            )
        },
        {message_id: metadata},
    )
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        origin_observer=object(),
        alert_sink=_noop_alert_sink,
    )
    original_persist_failure = service._persist_provider_failure

    async def assert_released_before_failure_persistence(*args, **kwargs):
        gc.collect()
        assert raw_ref is not None and raw_ref() is None
        await original_persist_failure(*args, **kwargs)

    service._persist_provider_failure = assert_released_before_failure_persistence
    with pytest.raises(GmailProviderFailure, match="^malformed_provider$") as raised:
        await service.sync_account(account.id)

    assert raw_canary not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


async def test_uncertain_system_automation_observed_by_history_stays_ignored(
    history_runtime,
) -> None:
    from types import SimpleNamespace

    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import (
        GmailMessageContent,
        GmailMessageMetadata,
    )
    from services.gmail_history_service import GmailHistoryService
    from services.gmail_origin_service import (
        GmailOriginService,
        canonicalize_gmail_send,
    )
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker = history_runtime
    account = await _seed_account(
        sessionmaker,
        cursor="100",
        email="brandon@example.test",
    )
    payload = SimpleNamespace(
        to=("client@example.test",),
        cc=(),
        bcc=(),
        subject="Automated status",
        body_text="Automated status body.",
    )
    canonical = canonicalize_gmail_send(
        account_email=account.workspace_email,
        payload=payload,
        intended_thread_id=None,
    )
    async with sessionmaker() as session:
        audit = AgentActionAudit(
            actor="system:notification",
            action_id="workspace.gmail.send.intent",
            method="POST",
            path="/internal/notification",
            status_code=202,
            allowed=True,
            request_meta_json="{}",
            response_meta_json="{}",
        )
        session.add(audit)
        await session.flush()
        origin = GmailMessageOrigin(
            account_id=account.id,
            request_id=uuid4(),
            canonical_send_hash=canonical.canonical_send_hash,
            canonical_envelope_hash=canonical.canonical_envelope_hash,
            canonical_body_hash=canonical.canonical_body_hash,
            origin_kind="system_automation",
            delivery_state="delivery_uncertain",
            version=2,
            action_audit_id=audit.id,
            failure_category="provider_timeout",
            failure_message="Gmail delivery could not be verified.",
        )
        session.add(origin)
        await session.commit()
        await session.refresh(origin)
        origin_created_at = origin.created_at

    content = GmailMessageContent(
        message_id="uncertain-automation-message",
        thread_id="uncertain-automation-thread",
        label_ids=("SENT",),
        message_at=origin_created_at,
        headers={
            "subject": payload.subject,
            "from": account.workspace_email,
            "to": payload.to[0],
        },
        body_text=f"{payload.body_text}\n",
    )
    metadata = GmailMessageMetadata(
        message_id=content.message_id,
        thread_id=content.thread_id,
        label_ids=content.label_ids,
        message_at=content.message_at,
        headers=content.headers,
    )

    class _Adapter(_ScriptedAdapter):
        async def get_message_content(self, **_kwargs):
            return content

    executor = BoundedProviderExecutor(max_workers=1)
    observer = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History must never send"),
        deadline_seconds=1,
    )
    service = GmailHistoryService(
        engine=engine,
        adapter=_Adapter(
            {
                None: _page(
                    history_id="101",
                    next_page_token=None,
                    messages=((content.message_id, content.thread_id),),
                    history_min="101",
                    history_max="101",
                )
            },
            {content.message_id: metadata},
        ),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        origin_observer=observer,
    )
    try:
        await service.sync_account(account.id)
    finally:
        executor.shutdown()

    async with sessionmaker() as session:
        stored_origin = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account.id
            )
        )
        receipt = await session.scalar(
            sa.select(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
    assert stored_origin.origin_kind == "system_automation"
    assert stored_origin.delivery_state == "succeeded"
    assert receipt.processing_state == "ignored"
    assert receipt.classification == "ignored_system_automation"


async def test_origin_receipt_enrichment_never_reopens_concurrent_processing(
    history_runtime,
) -> None:
    from types import SimpleNamespace

    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import (
        GmailMessageContent,
        GmailMessageMetadata,
    )
    from services.gmail_history_service import GmailHistoryService
    from services.gmail_origin_service import (
        GmailOriginService,
        canonicalize_gmail_send,
    )
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker = history_runtime
    account = await _seed_account(
        sessionmaker,
        cursor="100",
        email="brandon@example.test",
    )
    payload = SimpleNamespace(
        to=("client@example.test",),
        cc=(),
        bcc=(),
        subject="Enrichment race",
        body_text="Process this exactly once.",
    )
    canonical = canonicalize_gmail_send(
        account_email=account.workspace_email,
        payload=payload,
        intended_thread_id=None,
    )
    async with sessionmaker() as session:
        audit = AgentActionAudit(
            actor="hermes",
            action_id="workspace.gmail.send.intent",
            method="POST",
            path="/api/v1/agent-control/workspace/gmail/send",
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
                canonical_send_hash=canonical.canonical_send_hash,
                canonical_envelope_hash=canonical.canonical_envelope_hash,
                canonical_body_hash=canonical.canonical_body_hash,
                gmail_message_id="enrichment-race-message",
                gmail_thread_id="enrichment-race-thread",
                origin_kind="sydney_client_send",
                delivery_state="succeeded",
                version=2,
                action_audit_id=audit.id,
            )
        )
        placeholder = GmailMessageReceipt(
            account_id=account.id,
            gmail_message_id="enrichment-race-message",
            gmail_thread_id="enrichment-race-thread",
            direction="sent",
            message_at=datetime(2026, 8, 21, 21, 30, tzinfo=UTC),
            sender_hmac=None,
            recipient_hmacs_json="[]",
            subject_preview=None,
            body_hash=canonical.canonical_body_hash,
            labels_json='["SENT"]',
            processing_state="pending",
            classification="eligible",
        )
        session.add(placeholder)
        await session.commit()
        await session.refresh(placeholder)

    content = GmailMessageContent(
        message_id=placeholder.gmail_message_id,
        thread_id=placeholder.gmail_thread_id,
        label_ids=("SENT",),
        message_at=placeholder.message_at,
        headers={
            "subject": payload.subject,
            "from": account.workspace_email,
            "to": payload.to[0],
        },
        body_text=f"{payload.body_text}\n",
    )
    metadata = GmailMessageMetadata(
        message_id=content.message_id,
        thread_id=content.thread_id,
        label_ids=content.label_ids,
        message_at=content.message_at,
        headers=content.headers,
    )

    class _Adapter(_ScriptedAdapter):
        async def get_message_content(self, **_kwargs):
            return content

    adapter = _Adapter(
        {
            None: _page(
                history_id="101",
                next_page_token=None,
                messages=((content.message_id, content.thread_id),),
                history_min="101",
                history_max="101",
            )
        },
        {content.message_id: metadata},
    )
    executor = BoundedProviderExecutor(max_workers=1)
    observer = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("History must never send"),
        deadline_seconds=1,
    )
    looked_up = asyncio.Event()
    release_persist = asyncio.Event()

    async def after_stale_lookup():
        looked_up.set()
        await release_persist.wait()

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        origin_observer=observer,
        after_receipt_lookup=after_stale_lookup,
    )
    pending_sync = asyncio.create_task(service.sync_account(account.id))
    consumer_calls = 0
    consumer_entered = asyncio.Event()
    release_consumer = asyncio.Event()

    async def consumer(_transient):
        nonlocal consumer_calls
        consumer_calls += 1
        consumer_entered.set()
        await release_consumer.wait()

    pending_processing = None
    try:
        await asyncio.wait_for(looked_up.wait(), timeout=2)
        pending_processing = asyncio.create_task(
            service.process_receipt(
                placeholder.id,
                consumer=consumer,
            )
        )
        await asyncio.wait_for(consumer_entered.wait(), timeout=2)
        release_consumer.set()
        processed = await asyncio.wait_for(pending_processing, timeout=2)
        assert processed.processing_state == "processed"
        release_persist.set()
        await asyncio.wait_for(pending_sync, timeout=2)

        async def duplicate_consumer(_transient):
            raise AssertionError("processed receipt must never run a second consumer")

        replay = await service.process_receipt(
            placeholder.id,
            consumer=duplicate_consumer,
        )
        assert replay.claimed is False
        assert replay.processing_state == "processed"
    finally:
        release_persist.set()
        release_consumer.set()
        if not pending_sync.done():
            pending_sync.cancel()
            await asyncio.gather(pending_sync, return_exceptions=True)
        if pending_processing is not None and not pending_processing.done():
            pending_processing.cancel()
            await asyncio.gather(pending_processing, return_exceptions=True)
        executor.shutdown()

    assert consumer_calls == 1
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageReceipt, placeholder.id)
    assert stored.processing_state == "processed"
    assert stored.processed_at is not None
    assert stored.processing_started_at is not None


async def test_ignored_enrichment_row_lock_prevents_concurrent_consumer_claim(
    history_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")
    async with sessionmaker() as session:
        placeholder = GmailMessageReceipt(
            account_id=account.id,
            gmail_message_id="ignored-lock-message",
            gmail_thread_id="ignored-lock-thread",
            direction="received",
            message_at=datetime(2026, 8, 21, 21, 45, tzinfo=UTC),
            sender_hmac=None,
            recipient_hmacs_json="[]",
            subject_preview=None,
            body_hash=None,
            labels_json='["INBOX"]',
            processing_state="pending",
            classification="eligible",
        )
        session.add(placeholder)
        await session.commit()
        await session.refresh(placeholder)

    metadata = _metadata(
        placeholder.gmail_message_id,
        placeholder.gmail_thread_id,
        ("INBOX", "TRASH"),
    )
    adapter = _ScriptedAdapter(
        {
            None: _page(
                history_id="101",
                next_page_token=None,
                messages=((placeholder.gmail_message_id, placeholder.gmail_thread_id),),
                history_min="101",
                history_max="101",
            )
        },
        {placeholder.gmail_message_id: metadata},
    )
    receipt_locked = asyncio.Event()
    release_history = asyncio.Event()

    async def after_receipt_lock():
        receipt_locked.set()
        await release_history.wait()

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        after_receipt_lock=after_receipt_lock,
    )
    sync_task = asyncio.create_task(service.sync_account(account.id))
    consumer_calls = 0

    async def consumer(_transient):
        nonlocal consumer_calls
        consumer_calls += 1

    processing_task = None
    try:
        await asyncio.wait_for(receipt_locked.wait(), timeout=2)
        processing_task = asyncio.create_task(
            service.process_receipt(placeholder.id, consumer=consumer)
        )
        await asyncio.sleep(0.05)
        assert processing_task.done() is False
        assert consumer_calls == 0
        release_history.set()
        await asyncio.wait_for(sync_task, timeout=2)
        result = await asyncio.wait_for(processing_task, timeout=2)
    finally:
        release_history.set()
        if not sync_task.done():
            sync_task.cancel()
        if processing_task is not None and not processing_task.done():
            processing_task.cancel()
        await asyncio.gather(
            sync_task,
            *(tuple([processing_task]) if processing_task is not None else ()),
            return_exceptions=True,
        )

    assert result.claimed is False
    assert result.processing_state == "ignored"
    assert consumer_calls == 0
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageReceipt, placeholder.id)
    assert stored.processing_state == "ignored"
    assert stored.classification == "ignored_trash"
    assert stored.processing_started_at is None


async def test_receipt_lock_order_does_not_deadlock_provider_finalize(
    history_runtime,
) -> None:
    from types import SimpleNamespace

    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageContent, GmailMessageMetadata
    from services.gmail_history_service import GmailHistoryService
    from services.gmail_origin_service import (
        GmailOriginService,
        canonicalize_gmail_send,
    )
    from services.integration_health_service import BoundedProviderExecutor

    engine, sessionmaker = history_runtime
    account = await _seed_account(
        sessionmaker,
        cursor="100",
        email="brandon@example.test",
    )
    payload = SimpleNamespace(
        to=("client@example.test",),
        cc=(),
        bcc=(),
        subject="Receipt lock order",
        body_text="Do not deadlock.",
    )
    canonical = canonicalize_gmail_send(
        account_email=account.workspace_email,
        payload=payload,
        intended_thread_id=None,
    )
    async with sessionmaker() as session:
        audit = AgentActionAudit(
            actor="hermes",
            action_id="workspace.gmail.send.intent",
            method="POST",
            path="/api/v1/agent-control/workspace/gmail/send",
            status_code=202,
            allowed=True,
            request_meta_json="{}",
            response_meta_json="{}",
        )
        session.add(audit)
        await session.flush()
        origin = GmailMessageOrigin(
            account_id=account.id,
            request_id=uuid4(),
            canonical_send_hash=canonical.canonical_send_hash,
            canonical_envelope_hash=canonical.canonical_envelope_hash,
            canonical_body_hash=canonical.canonical_body_hash,
            gmail_message_id="lock-order-message",
            gmail_thread_id="lock-order-thread",
            origin_kind="sydney_client_send",
            delivery_state="succeeded",
            version=2,
            action_audit_id=audit.id,
        )
        receipt = GmailMessageReceipt(
            account_id=account.id,
            gmail_message_id=origin.gmail_message_id,
            gmail_thread_id=origin.gmail_thread_id,
            direction="sent",
            message_at=datetime(2026, 8, 21, 22, 0, tzinfo=UTC),
            sender_hmac=None,
            recipient_hmacs_json="[]",
            body_hash=canonical.canonical_body_hash,
            labels_json='["SENT"]',
            processing_state="pending",
            classification="eligible",
        )
        session.add_all([origin, receipt])
        await session.commit()
        await session.refresh(origin)

    content = GmailMessageContent(
        message_id=receipt.gmail_message_id,
        thread_id=receipt.gmail_thread_id,
        label_ids=("SENT",),
        message_at=receipt.message_at,
        headers={
            "subject": payload.subject,
            "from": account.workspace_email,
            "to": payload.to[0],
        },
        body_text=f"{payload.body_text}\n",
    )
    metadata = GmailMessageMetadata(
        message_id=content.message_id,
        thread_id=content.thread_id,
        label_ids=content.label_ids,
        message_at=content.message_at,
        headers=content.headers,
    )

    class _Adapter(_ScriptedAdapter):
        async def get_message_content(self, **_kwargs):
            return content

    adapter = _Adapter(
        {
            None: _page(
                history_id="101",
                next_page_token=None,
                messages=((receipt.gmail_message_id, receipt.gmail_thread_id),),
                history_min="101",
                history_max="101",
            )
        },
        {receipt.gmail_message_id: metadata},
    )
    bulk_lookup_complete = asyncio.Event()
    release_history = asyncio.Event()

    async def after_receipt_lookup():
        bulk_lookup_complete.set()
        await release_history.wait()

    executor = BoundedProviderExecutor(max_workers=1)
    origin_service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: pytest.fail("finalize must not send"),
        deadline_seconds=1,
    )
    history = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        origin_observer=origin_service,
        after_receipt_lookup=after_receipt_lookup,
    )
    sync_task = asyncio.create_task(history.sync_account(account.id))
    finalize_task = None
    try:
        await asyncio.wait_for(bulk_lookup_complete.wait(), timeout=2)
        finalize_task = asyncio.create_task(
            origin_service.finalize_success(
                origin_id=origin.id,
                expected_version=2,
                message_id=origin.gmail_message_id,
                thread_id=origin.gmail_thread_id,
            )
        )
        # History has completed its bulk receipt lookup but has not locked the
        # origin. Provider finalization must be able to take origin -> receipt
        # and finish. A blanket receipt FOR UPDATE in the bulk query would make
        # this wait while History later waits on the origin: a deadlock cycle.
        finalized = await asyncio.wait_for(finalize_task, timeout=1)
        release_history.set()
        await asyncio.wait_for(sync_task, timeout=2)
    finally:
        release_history.set()
        if not sync_task.done():
            sync_task.cancel()
        if finalize_task is not None and not finalize_task.done():
            finalize_task.cancel()
        await asyncio.gather(
            sync_task,
            *(tuple([finalize_task]) if finalize_task is not None else ()),
            return_exceptions=True,
        )
        executor.shutdown()

    assert finalized.delivery_state == "succeeded"
    assert finalized.replayed is True
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
    assert stored.gmail_thread_id == "lock-order-thread"
    assert stored.processing_state == "pending"
    assert stored.classification == "eligible"


@pytest.mark.parametrize(
    ("labels", "extra_headers", "classification"),
    [
        (("SENT", "TRASH"), {}, "ignored_trash"),
        (
            ("SENT",),
            {"auto-submitted": "auto-generated"},
            "ignored_automation",
        ),
    ],
)
async def test_ignored_history_enrichment_terminalizes_failed_sparse_receipt(
    history_runtime,
    labels: tuple[str, ...],
    extra_headers: dict[str, str],
    classification: str,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt
    from services.gmail_history_adapter import GmailMessageMetadata
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(
        sessionmaker,
        cursor="100",
        email="brandon@example.test",
    )
    message_id = f"failed-ignored-{classification}"
    thread_id = f"thread-{message_id}"
    async with sessionmaker() as session:
        receipt = GmailMessageReceipt(
            account_id=account.id,
            gmail_message_id=message_id,
            gmail_thread_id=thread_id,
            direction="sent",
            message_at=datetime(2026, 8, 21, 21, 45, tzinfo=UTC),
            sender_hmac=None,
            recipient_hmacs_json="[]",
            subject_preview=None,
            body_hash=None,
            labels_json='["SENT"]',
            processing_state="failed",
            classification="eligible",
            failure_category="consumer_failed",
            failure_message="Safe retryable failure.",
        )
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)
        receipt_id = receipt.id

    metadata = GmailMessageMetadata(
        message_id=message_id,
        thread_id=thread_id,
        label_ids=labels,
        message_at=datetime(2026, 8, 21, 21, 45, tzinfo=UTC),
        headers={
            "subject": "Ignored after delivery",
            "from": account.workspace_email,
            "to": "client@example.test",
            **extra_headers,
        },
    )

    class _MetadataOnlyAdapter(_ScriptedAdapter):
        content_calls = 0

        async def get_message_content(self, **_kwargs):
            self.content_calls += 1
            raise AssertionError("ignored metadata must never fetch raw content")

    adapter = _MetadataOnlyAdapter(
        {
            None: _page(
                history_id="101",
                next_page_token=None,
                messages=((message_id, thread_id),),
                history_min="101",
                history_max="101",
            )
        },
        {message_id: metadata},
    )
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    await service.sync_account(account.id)

    consumer_calls = 0

    async def forbidden_consumer(_message):
        nonlocal consumer_calls
        consumer_calls += 1
        raise AssertionError("ignored receipt must not become retryable")

    result = await service.process_receipt(
        receipt_id,
        consumer=forbidden_consumer,
    )
    async with sessionmaker() as session:
        stored = await session.get(GmailMessageReceipt, receipt_id)
    assert adapter.content_calls == 0
    assert consumer_calls == 0
    assert result.processing_state == "ignored"
    assert stored.processing_state == "ignored"
    assert stored.classification == classification
    assert stored.failure_category is None
    assert stored.failure_message is None


async def test_dedicated_history_engine_uses_nullpool_and_passes_real_session_probe(
    history_database,
) -> None:
    from config import Settings
    from services.gmail_history_database import (
        create_gmail_history_engine,
        probe_gmail_history_session_affinity,
    )

    url, _sync_engine = history_database
    direct_url = async_test_url(url).render_as_string(hide_password=False)
    config = Settings(
        JWT_SECRET="test-secret",
        DATABASE_URL=direct_url,
        GMAIL_HISTORY_DATABASE_URL=direct_url,
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="x" * 32,
    )
    engine = create_gmail_history_engine(config)
    primary_engine = create_async_engine(direct_url, pool_pre_ping=True)
    verifier = await primary_engine.connect()
    history_lock_ready = asyncio.Event()
    release_probe = asyncio.Event()
    captured_key: list[int] = []

    async def after_history_lock_commit(key: int):
        captured_key.append(key)
        history_lock_ready.set()
        await release_probe.wait()

    try:
        assert isinstance(engine.pool, NullPool)
        pending = asyncio.create_task(
            probe_gmail_history_session_affinity(
                history_engine=engine,
                primary_engine=primary_engine,
                after_history_lock_commit=after_history_lock_commit,
            )
        )
        await asyncio.wait_for(history_lock_ready.wait(), timeout=2)
        key = captured_key[0]
        contended = await verifier.scalar(
            sa.text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
        )
        assert contended is False
        await verifier.commit()
        release_probe.set()
        proof = await asyncio.wait_for(pending, timeout=2)
        acquired_after = await verifier.scalar(
            sa.text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
        )
        assert acquired_after is True
        assert await verifier.scalar(
            sa.text("SELECT pg_advisory_unlock(:key)"), {"key": key}
        ) is True
        await verifier.commit()
    finally:
        release_probe.set()
        await verifier.close()
        await engine.dispose()
        await primary_engine.dispose()

    assert proof.backend_pid > 0
    assert proof.backend_pid_before_commit == proof.backend_pid_after_commit
    assert proof.lock_survived_commit is True
    assert proof.unlock_succeeded is True
    assert proof.primary_contended_before_release is True
    assert proof.primary_acquired_after_release is True


async def test_dedicated_history_engine_normalizes_accepted_sslmode_for_asyncpg(
    history_database,
) -> None:
    from config import Settings
    from services.gmail_history_database import create_gmail_history_engine

    url, _sync_engine = history_database
    direct_url = async_test_url(url).render_as_string(hide_password=False)
    direct_url = direct_url.replace("ssl=require", "sslmode=require")
    config = Settings(
        JWT_SECRET="test-secret",
        DATABASE_URL=direct_url,
        GMAIL_HISTORY_DATABASE_URL=direct_url,
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="x" * 32,
    )
    engine = create_gmail_history_engine(config)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(sa.text("SELECT 1")) == 1
    finally:
        await engine.dispose()


async def test_session_affinity_probe_fails_closed_when_backend_pid_changes(
    history_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import Settings
    import services.gmail_history_database as database_module
    from services.gmail_history_database import (
        create_gmail_history_engine,
        probe_gmail_history_session_affinity,
    )

    url, _sync_engine = history_database
    direct_url = async_test_url(url).render_as_string(hide_password=False)
    config = Settings(
        JWT_SECRET="test-secret",
        DATABASE_URL=direct_url,
        GMAIL_HISTORY_DATABASE_URL=direct_url,
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="x" * 32,
    )
    observed = iter((41001, 41002))
    calls: list[str] = []

    async def changing_pid(_connection):
        calls.append("pid")
        return next(observed)

    async def forbidden_lock_acquisition(*_args, **_kwargs):
        calls.append("lock")
        raise AssertionError("PID mismatch must fail before acquiring a session lock")

    monkeypatch.setattr(database_module, "_read_backend_pid", changing_pid)
    monkeypatch.setattr(
        database_module,
        "_acquire_probe_lock",
        forbidden_lock_acquisition,
    )
    engine = create_gmail_history_engine(config)
    primary_engine = create_async_engine(direct_url, pool_pre_ping=True)
    try:
        with pytest.raises(
            RuntimeError, match="^gmail_history_session_affinity_required$"
        ):
            await probe_gmail_history_session_affinity(
                history_engine=engine,
                primary_engine=primary_engine,
            )
    finally:
        await engine.dispose()
        await primary_engine.dispose()
    assert calls == ["pid", "pid"]


async def test_session_affinity_probe_releases_history_lock_when_primary_does_not_contend(
    history_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import Settings
    import services.gmail_history_database as database_module
    from services.gmail_history_database import (
        create_gmail_history_engine,
        probe_gmail_history_session_affinity,
    )

    url, _sync_engine = history_database
    direct_url = async_test_url(url).render_as_string(hide_password=False)
    config = Settings(
        JWT_SECRET="test-secret",
        DATABASE_URL=direct_url,
        GMAIL_HISTORY_DATABASE_URL=direct_url,
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="x" * 32,
    )
    history_engine = create_gmail_history_engine(config)
    primary_engine = create_async_engine(direct_url, pool_pre_ping=True)
    released: list[int] = []
    original_release = database_module._release_probe_lock

    async def primary_wrongly_acquires(_connection, _key):
        return True

    async def tracked_release(connection, key):
        released.append(key)
        return await original_release(connection, key)

    monkeypatch.setattr(
        database_module, "_primary_try_probe_lock", primary_wrongly_acquires
    )
    monkeypatch.setattr(database_module, "_release_probe_lock", tracked_release)
    try:
        with pytest.raises(
            RuntimeError, match="^gmail_history_session_affinity_required$"
        ):
            await probe_gmail_history_session_affinity(
                history_engine=history_engine,
                primary_engine=primary_engine,
            )
    finally:
        await history_engine.dispose()
        await primary_engine.dispose()
    assert len(released) >= 1


async def test_runtime_pid_change_after_page_commit_blocks_before_next_provider_call(
    history_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailSessionAffinityLost,
    )

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")
    adapter = _ScriptedAdapter(
        {
            None: _page(
                history_id="101",
                next_page_token="page-2",
                messages=(("pid-message-1", "pid-thread-1"),),
                history_min="101",
                history_max="101",
            ),
            "page-2": _page(
                history_id="102",
                next_page_token=None,
                messages=(("pid-message-2", "pid-thread-2"),),
                history_min="102",
                history_max="102",
            ),
        },
        {
            "pid-message-1": _metadata(
                "pid-message-1", "pid-thread-1", ("INBOX",)
            ),
            "pid-message-2": _metadata(
                "pid-message-2", "pid-thread-2", ("INBOX",)
            ),
        },
    )
    pids = iter((52001, 52001, 52002))

    async def backend_pid_reader(_connection):
        return next(pids)

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        backend_pid_reader=backend_pid_reader,
    )
    with pytest.raises(
        GmailSessionAffinityLost, match="^gmail_history_session_affinity_lost$"
    ):
        await service.sync_account(account.id)

    assert adapter.history_calls == [(str(account.id), "100", None)]
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt).where(
                        GmailMessageReceipt.account_id == account.id
                    )
                )
            ).all()
        )
        checkpoints = list(
            (
                await session.scalars(
                    sa.select(GmailSyncPageCheckpoint)
                    .join(
                        GmailSyncRun,
                        GmailSyncRun.id == GmailSyncPageCheckpoint.run_id,
                    )
                    .where(GmailSyncRun.account_id == account.id)
                )
            ).all()
        )
    assert stored.committed_history_id == "100"
    assert stored.blocked_reason == "session_affinity_lost"
    assert stored.last_error_category == "session_affinity_lost"
    assert [row.gmail_message_id for row in receipts] == ["pid-message-1"]
    assert len(checkpoints) == 1


async def test_initial_lock_commit_pid_drift_blocks_before_poll_provider_or_cursor(
    history_runtime,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailSessionAffinityLost,
    )

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")

    class _NeverCalledAdapter:
        calls = 0

        async def list_history(self, **_kwargs):
            self.calls += 1
            raise AssertionError("provider must not run after initial affinity loss")

    pids = iter((61001, 61002))

    async def backend_pid_reader(_connection):
        return next(pids)

    adapter = _NeverCalledAdapter()
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        backend_pid_reader=backend_pid_reader,
    )
    with pytest.raises(
        GmailSessionAffinityLost, match="^gmail_history_session_affinity_lost$"
    ):
        await service.sync_account(account.id)

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncRun).where(
                GmailSyncRun.account_id == account.id
            )
        )
    assert adapter.calls == 0
    assert stored.committed_history_id == "100"
    assert stored.blocked_reason == "session_affinity_lost"
    assert stored.last_error_category == "session_affinity_lost"
    assert run_count == 0


@pytest.mark.parametrize("transaction_lock_acquired", [False, True])
async def test_initial_affinity_loss_keeps_serialization_until_block_is_durable(
    history_runtime,
    transaction_lock_acquired: bool,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailSessionAffinityLost,
    )

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")
    persist_started = asyncio.Event()
    allow_persist = asyncio.Event()

    class _NeverCalledAdapter:
        calls = 0

        async def list_history(self, **_kwargs):
            self.calls += 1
            raise AssertionError("provider must remain serialized behind drift")

    async def before_pid(_connection):
        return 61001

    async def drifted_post_probe(_connection, _account_id):
        return 61002, transaction_lock_acquired

    first_adapter = _NeverCalledAdapter()
    first = GmailHistoryService(
        engine=engine,
        adapter=first_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        backend_pid_reader=before_pid,
        post_lock_probe=drifted_post_probe,
    )
    original_persist = first._persist_initial_affinity_loss
    connection_open_at_handoff = False

    async def paused_persist(**kwargs):
        nonlocal connection_open_at_handoff
        handoff_connection = kwargs.get("connection")
        connection_open_at_handoff = (
            handoff_connection is None or not handoff_connection.closed
        )
        persist_started.set()
        await allow_persist.wait()
        await original_persist(**kwargs)

    first._persist_initial_affinity_loss = paused_persist
    first_task = asyncio.create_task(first.sync_account(account.id))
    await asyncio.wait_for(persist_started.wait(), timeout=1)

    competitor_adapter = _NeverCalledAdapter()
    competitor = GmailHistoryService(
        engine=engine,
        adapter=competitor_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    try:
        competitor_result = await competitor.sync_account(account.id)
    finally:
        allow_persist.set()
    with pytest.raises(
        GmailSessionAffinityLost,
        match="^gmail_history_session_affinity_lost$",
    ):
        await first_task

    assert connection_open_at_handoff is True
    assert competitor_result.lock_acquired is False
    assert first_adapter.calls == 0
    assert competitor_adapter.calls == 0
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
    assert stored.committed_history_id == "100"
    assert stored.blocked_reason == "session_affinity_lost"


async def test_dead_owner_release_reestablishes_serialization_before_block(
    history_runtime,
    monkeypatch,
) -> None:
    import services.gmail_history_service as history_module
    from models.gmail_task_intake import GmailSyncAccount
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailSessionAffinityLost,
    )

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")
    persist_serialized = asyncio.Event()
    allow_persist = asyncio.Event()

    class _TerminalAdapter:
        calls = 0

        async def list_history(self, **_kwargs):
            self.calls += 1
            return _page(
                history_id="101",
                next_page_token=None,
                messages=(),
                history_min="101",
                history_max="101",
            )

    async def close_owner_then_raise(connection, _account_id):
        await connection.invalidate()
        raise ConnectionError("release-owner-secret-canary")

    async def pause_after_fresh_serialization():
        persist_serialized.set()
        await allow_persist.wait()

    monkeypatch.setattr(
        history_module,
        "release_session_advisory_lock",
        close_owner_then_raise,
    )
    first_adapter = _TerminalAdapter()
    first = GmailHistoryService(
        engine=engine,
        adapter=first_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        before_release_affinity_persist=pause_after_fresh_serialization,
    )
    first_task = asyncio.create_task(first.sync_account(account.id))
    await asyncio.wait_for(persist_serialized.wait(), timeout=2)

    competitor_adapter = _TerminalAdapter()
    competitor = GmailHistoryService(
        engine=engine,
        adapter=competitor_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    try:
        competitor_result = await competitor.sync_account(account.id)
    finally:
        allow_persist.set()
    with pytest.raises(
        GmailSessionAffinityLost,
        match="^gmail_history_session_affinity_lost$",
    ) as raised:
        await first_task

    assert "release-owner-secret-canary" not in "".join(
        traceback.format_exception(raised.value)
    )
    assert competitor_result.lock_acquired is False
    assert first_adapter.calls == 1
    assert competitor_adapter.calls == 0
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
    assert stored.committed_history_id == "101"
    assert stored.blocked_reason == "session_affinity_lost"


async def test_terminal_page_pid_change_blocks_before_cursor_cas_and_releases_lock(
    history_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailSessionAffinityLost,
    )
    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
    )

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")
    adapter = _ScriptedAdapter(
        {
            None: _page(
                history_id="101",
                next_page_token=None,
                messages=(("terminal-pid-message", "terminal-pid-thread"),),
                history_min="101",
                history_max="101",
            )
        },
        {
            "terminal-pid-message": _metadata(
                "terminal-pid-message", "terminal-pid-thread", ("INBOX",)
            )
        },
    )
    pids = iter((53001, 53001, 53002))

    async def backend_pid_reader(_connection):
        return next(pids)

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        backend_pid_reader=backend_pid_reader,
    )
    verifier = await engine.connect()
    try:
        with pytest.raises(
            GmailSessionAffinityLost,
            match="^gmail_history_session_affinity_lost$",
        ):
            await service.sync_account(account.id)
        assert await try_session_advisory_lock(verifier, account.id)
        assert await release_session_advisory_lock(verifier, account.id)
        await verifier.commit()
    finally:
        await verifier.close()

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt).where(
                        GmailMessageReceipt.account_id == account.id
                    )
                )
            ).all()
        )
    assert stored.committed_history_id == "100"
    assert stored.blocked_reason == "session_affinity_lost"
    assert [row.gmail_message_id for row in receipts] == [
        "terminal-pid-message"
    ]


async def test_crash_after_terminal_page_commit_resumes_only_cursor_cas(
    history_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")

    async def crash_after_terminal_commit(*_args, **_kwargs):
        raise RuntimeError("synthetic crash after terminal commit")

    adapter = _ScriptedAdapter(
        {
            None: _page(
                history_id="101",
                next_page_token=None,
                messages=(("terminal-crash-message", "terminal-crash-thread"),),
                history_min="101",
                history_max="101",
            )
        },
        {
            "terminal-crash-message": _metadata(
                "terminal-crash-message", "terminal-crash-thread", ("INBOX",)
            )
        },
    )
    crashing = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        after_terminal_page_commit=crash_after_terminal_commit,
    )
    with pytest.raises(RuntimeError, match="synthetic crash after terminal commit"):
        await crashing.sync_account(account.id)

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
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
        checkpoints = list(
            (
                await session.scalars(
                    sa.select(GmailSyncPageCheckpoint).where(
                        GmailSyncPageCheckpoint.run_id == run.id
                    )
                )
            ).all()
        )
    assert stored.committed_history_id == "100"
    assert run.state == "discovered"
    assert run.next_page_token is None
    assert run.terminal_history_id == "101"
    assert [row.gmail_message_id for row in receipts] == [
        "terminal-crash-message"
    ]
    assert len(checkpoints) == 1
    assert checkpoints[0].next_page_token is None

    class _NoRefetchAdapter:
        calls = 0

        async def list_history(self, **_kwargs):
            self.calls += 1
            raise AssertionError("terminal page must not be refetched after commit")

    resume_adapter = _NoRefetchAdapter()
    resumed = GmailHistoryService(
        engine=engine,
        adapter=resume_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    result = await resumed.sync_account(account.id)
    assert result.committed_history_id == "101"
    assert resume_adapter.calls == 0
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
    assert stored.committed_history_id == "101"
    assert receipt_count == 1


@pytest.mark.parametrize("run_state", ["running", "discovered"])
async def test_resumed_poll_run_rejects_changed_account_cursor_snapshot(
    history_runtime,
    run_state: str,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_service import (
        GmailAccountBlocked,
        GmailCursorConflict,
        GmailHistoryService,
    )

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")
    async with sessionmaker() as session:
        run = GmailSyncRun(
            account_id=account.id,
            start_history_id="100",
            terminal_history_id=("101" if run_state == "discovered" else None),
            next_page_token=("snapshot-page-2" if run_state == "running" else None),
            run_kind="poll",
            state=run_state,
        )
        session.add(run)
        stored = await session.get(GmailSyncAccount, account.id)
        stored.committed_history_id = "999"
        await session.commit()

    class _ForbiddenAdapter:
        calls = 0

        async def list_history(self, **_kwargs):
            self.calls += 1
            raise AssertionError("stale run must fail before provider")

    adapter = _ForbiddenAdapter()
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(
        GmailCursorConflict,
        match="^gmail_cursor_compare_and_set_failed$",
    ):
        await service.sync_account(account.id)

    assert adapter.calls == 0
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored_run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )
    assert stored.committed_history_id == "999"
    assert stored.blocked_reason == "cursor_conflict"
    assert stored_run.start_history_id == "100"
    assert stored_run.state == "failed"
    assert stored_run.failure_category == "cursor_conflict"
    assert len(alerts) == 1

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="^cursor_conflict$"):
        await reconstructed.sync_account(account.id)
    assert adapter.calls == 0
    assert len(alerts) == 1


async def test_replayed_history_is_idempotent_and_thread_ids_are_not_unique(
    history_runtime,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="400")
    page = _page(
        history_id="401",
        next_page_token=None,
        messages=(
            ("message-a", "thread-shared"),
            ("message-b", "thread-shared"),
            ("message-a", "thread-shared"),
        ),
        history_min="401",
        history_max="401",
    )
    adapter = _ScriptedAdapter(
        {None: page},
        {
            "message-a": _metadata("message-a", "thread-shared", ("INBOX",)),
            "message-b": _metadata("message-b", "thread-shared", ("INBOX",)),
        },
    )
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    await service.sync_account(account.id)

    async with sessionmaker() as session:
        stored = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt)
                    .where(GmailMessageReceipt.account_id == account.id)
                    .order_by(GmailMessageReceipt.gmail_message_id)
                )
            ).all()
        )
    assert [(row.gmail_message_id, row.gmail_thread_id) for row in stored] == [
        ("message-a", "thread-shared"),
        ("message-b", "thread-shared"),
    ]
    assert adapter.metadata_calls == [
        (str(account.id), "message-a"),
        (str(account.id), "message-b"),
    ]

    replay_adapter = _ScriptedAdapter(
        {
            None: _page(
                history_id="402",
                next_page_token=None,
                messages=(
                    ("message-a", "thread-shared"),
                    ("message-c", "thread-shared"),
                ),
                history_min="402",
                history_max="402",
            )
        },
        {
            "message-a": _metadata("message-a", "thread-shared", ("INBOX",)),
            "message-c": _metadata("message-c", "thread-shared", ("INBOX",)),
        },
    )
    replay_service = GmailHistoryService(
        engine=engine,
        adapter=replay_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    replay_result = await replay_service.sync_account(account.id)

    assert replay_result.committed_history_id == "402"
    async with sessionmaker() as session:
        stored = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt)
                    .where(GmailMessageReceipt.account_id == account.id)
                    .order_by(GmailMessageReceipt.gmail_message_id)
                )
            ).all()
        )
    assert [row.gmail_message_id for row in stored] == [
        "message-a",
        "message-b",
        "message-c",
    ]


async def test_final_cursor_compare_and_set_refuses_a_racing_cursor_change(
    history_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_service import (
        GmailAccountBlocked,
        GmailCursorConflict,
        GmailHistoryService,
    )

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="500")
    release = asyncio.Event()
    adapter = _ScriptedAdapter(
        {
            None: _page(
                history_id="501",
                next_page_token=None,
                messages=(("terminal-cas-message", "terminal-cas-thread"),),
                history_min="501",
                history_max="501",
            )
        },
        {
            "terminal-cas-message": _metadata(
                "terminal-cas-message", "terminal-cas-thread", ("INBOX",)
            )
        },
        pause=release,
    )
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    verifier = await engine.connect()
    verifier_pid = await verifier.scalar(sa.text("SELECT pg_backend_pid()"))
    pending = asyncio.create_task(service.sync_account(account.id))
    await asyncio.wait_for(adapter.entered.wait(), timeout=2)

    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
    )

    assert not await try_session_advisory_lock(verifier, account.id)
    await verifier.commit()

    async with sessionmaker() as session:
        await session.execute(
            sa.update(GmailSyncAccount)
            .where(GmailSyncAccount.id == account.id)
            .values(committed_history_id="999")
        )
        await session.commit()

    release.set()
    with pytest.raises(GmailCursorConflict, match="gmail_cursor_compare_and_set_failed"):
        await pending

    assert await try_session_advisory_lock(verifier, account.id)
    assert await release_session_advisory_lock(verifier, account.id)
    await verifier.commit()
    assert verifier_pid is not None
    await verifier.close()

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
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
        checkpoints = list(
            (
                await session.scalars(
                    sa.select(GmailSyncPageCheckpoint).where(
                        GmailSyncPageCheckpoint.run_id == run.id
                    )
                )
            ).all()
        )
    assert stored.committed_history_id == "999"
    assert stored.blocked_reason == "cursor_conflict"
    assert run.state == "failed"
    assert run.failure_category == "cursor_conflict"
    assert [row.gmail_message_id for row in receipts] == ["terminal-cas-message"]
    assert len(checkpoints) == 1
    assert checkpoints[0].next_page_token is None
    assert len(alerts) == 1

    provider_call_count = len(adapter.history_calls)
    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="^cursor_conflict$"):
        await reconstructed.sync_account(account.id)
    assert len(adapter.history_calls) == provider_call_count
    assert len(alerts) == 1


@pytest.mark.parametrize(
    ("category", "expected_message", "blocked_reason"),
    [
        (
            "oauth_revoked",
            "Google Workspace authorization must be reconnected.",
            "oauth_revoked",
        ),
        (
            "rate_limited",
            "Gmail provider rate limit reached.",
            None,
        ),
        (
            "transient_provider",
            "Provider request failed temporarily.",
            None,
        ),
        (
            "malformed_provider",
            "Gmail provider returned an invalid response.",
            "malformed_provider",
        ),
    ],
)
async def test_provider_failure_persists_only_a_sanitized_category_and_log(
    history_runtime,
    caplog: pytest.LogCaptureFixture,
    category: str,
    expected_message: str,
    blocked_reason: str | None,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_adapter import GmailProviderFailure
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="600")
    secret = "private-message-body bearer-token client@example.test"

    class _FailingAdapter:
        async def list_history(self, **_kwargs):
            raise GmailProviderFailure(category) from RuntimeError(secret)

    service = GmailHistoryService(
        engine=engine,
        adapter=_FailingAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=_noop_alert_sink,
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(GmailProviderFailure, match=f"^{category}$") as raised:
            await service.sync_account(account.id)

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )

    assert stored.committed_history_id == "600"
    assert stored.blocked_reason == blocked_reason
    assert stored.last_error_category == category
    assert stored.last_error_message == expected_message
    assert run.state == (
        "running"
        if category in {"rate_limited", "transient_provider"}
        else "failed"
    )
    assert run.failure_category == category
    assert run.failure_message == expected_message
    assert secret not in caplog.text
    assert secret not in (stored.last_error_message or "")
    assert secret not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__suppress_context__ is True


@pytest.mark.parametrize("stage", ["page", "metadata"])
async def test_malformed_poll_failure_blocks_recall_on_later_cycle(
    history_runtime,
    stage: str,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_adapter import GmailProviderFailure
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    class _MalformedAdapter:
        history_calls = 0
        metadata_calls = 0

        async def list_history(self, **_kwargs):
            self.history_calls += 1
            if stage == "page":
                return _page(
                    history_id="invalid-history-id",
                    next_page_token=None,
                    messages=(),
                    history_min=None,
                    history_max=None,
                )
            return _page(
                history_id="101",
                next_page_token=None,
                messages=(("malformed-message", "malformed-thread"),),
                history_min="101",
                history_max="101",
            )

        async def get_message_metadata(self, **_kwargs):
            self.metadata_calls += 1
            raise GmailProviderFailure("malformed_provider")

    adapter = _MalformedAdapter()
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailProviderFailure, match="^malformed_provider$"):
        await service.sync_account(account.id)

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="^malformed_provider$"):
        await reconstructed.sync_account(account.id)
    assert adapter.history_calls == 1
    assert adapter.metadata_calls == (1 if stage == "metadata" else 0)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        runs = list(
            (
                await session.scalars(
                    sa.select(GmailSyncRun).where(
                        GmailSyncRun.account_id == account.id
                    )
                )
            ).all()
        )
    assert stored.committed_history_id == "100"
    assert stored.blocked_reason == "malformed_provider"
    assert len(runs) == 1
    assert len(alerts) == 1
    assert alerts[0]["event"] == "malformed_provider"


@pytest.mark.parametrize("stored_kind", ["receipt", "origin"])
async def test_persisted_message_thread_mismatch_blocks_before_message_fetch(
    history_runtime,
    stored_kind: str,
) -> None:
    from models.gmail_task_intake import (
        GmailMessageOrigin,
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import GmailProviderFailure
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")
    message_id = f"persisted-thread-mismatch-{stored_kind}"
    async with sessionmaker() as session:
        if stored_kind == "receipt":
            session.add(
                GmailMessageReceipt(
                    account_id=account.id,
                    gmail_message_id=message_id,
                    gmail_thread_id="persisted-thread-a",
                    direction="received",
                    message_at=datetime(2026, 8, 21, 14, 0, tzinfo=UTC),
                    sender_hmac="a" * 64,
                    recipient_hmacs_json="[]",
                    labels_json='["INBOX"]',
                    processing_state="processed",
                    classification="eligible",
                    processed_at=datetime(2026, 8, 21, 14, 1, tzinfo=UTC),
                )
            )
        else:
            session.add(
                GmailMessageOrigin(
                    account_id=account.id,
                    request_id=None,
                    canonical_send_hash=None,
                    canonical_envelope_hash=None,
                    canonical_body_hash=None,
                    gmail_message_id=message_id,
                    gmail_thread_id="persisted-thread-a",
                    origin_kind="human_send",
                    delivery_state="succeeded",
                    version=1,
                    action_audit_id=None,
                )
            )
        await session.commit()

    adapter = _ScriptedAdapter(
        {
            None: _page(
                history_id="101",
                next_page_token=None,
                messages=((message_id, "provider-thread-b"),),
                history_min="101",
                history_max="101",
            )
        },
        {message_id: _metadata(message_id, "provider-thread-b", ("INBOX",))},
    )
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    first = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailProviderFailure, match="^malformed_provider$"):
        await first.sync_account(account.id)

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="^malformed_provider$"):
        await reconstructed.sync_account(account.id)

    assert len(adapter.history_calls) == 1
    assert adapter.metadata_calls == []
    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        runs = list(
            (
                await session.scalars(
                    sa.select(GmailSyncRun).where(
                        GmailSyncRun.account_id == account.id
                    )
                )
            ).all()
        )
        checkpoint_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncPageCheckpoint)
        )
    assert stored_account.committed_history_id == "100"
    assert stored_account.blocked_reason == "malformed_provider"
    assert len(runs) == 1
    assert runs[0].state == "failed"
    assert checkpoint_count == 0
    assert [event["event"] for event in alerts] == ["malformed_provider"]


async def test_blocked_poll_alert_failure_is_restart_resumable_and_deduped(
    history_runtime,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")
    secret = "raw-guard-alert-canary"
    attempts = 0
    durable_alerts: list[dict[str, str]] = []

    async def recovering_alert_sink(**event):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError(secret)
        durable_alerts.append(event)

    class _GuardedAdapter:
        history_calls = 0

        async def list_history(self, **_kwargs):
            self.history_calls += 1
            return _page(
                history_id="101",
                next_page_token="page-2",
                messages=(),
                history_min="101",
                history_max="101",
            )

    adapter = _GuardedAdapter()
    first = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=1,
        alert_sink=recovering_alert_sink,
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(
            RuntimeError, match="^gmail_history_alert_enqueue_failed$"
        ) as raised:
            await first.sync_account(account.id)

    async with sessionmaker() as session:
        incomplete = await session.get(GmailSyncAccount, account.id)
    assert incomplete.committed_history_id == "100"
    assert incomplete.blocked_reason == "max_pages"
    assert incomplete.last_error_category == "max_pages_alert_pending"
    assert durable_alerts == []
    assert adapter.history_calls == 1
    assert secret not in caplog.text
    assert secret not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__suppress_context__ is True

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=1,
        alert_sink=recovering_alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="^max_pages$"):
        await reconstructed.sync_account(account.id)
    assert attempts == 2
    assert len(durable_alerts) == 1
    assert adapter.history_calls == 1

    after_successful_alert = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=1,
        alert_sink=recovering_alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="^max_pages$"):
        await after_successful_alert.sync_account(account.id)
    assert attempts == 2
    assert len(durable_alerts) == 1
    assert adapter.history_calls == 1


async def test_block_commit_before_alert_crash_retries_alert_on_restart(
    history_runtime,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")

    class _GuardedAdapter:
        history_calls = 0

        async def list_history(self, **_kwargs):
            self.history_calls += 1
            return _page(
                history_id="101",
                next_page_token="page-2",
                messages=(),
                history_min="101",
                history_max="101",
            )

    adapter = _GuardedAdapter()
    first = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=1,
    )

    async def crash_after_block_commit(*_args, **_kwargs):
        raise SystemExit("synthetic process loss before alert enqueue")

    first._enqueue_expiry_alert = crash_after_block_commit
    with pytest.raises(SystemExit, match="process loss before alert"):
        await first.sync_account(account.id)

    async with sessionmaker() as session:
        incomplete = await session.get(GmailSyncAccount, account.id)
    assert incomplete.blocked_reason == "max_pages"
    assert incomplete.last_error_category == "max_pages_alert_pending"
    assert adapter.history_calls == 1

    durable_alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        durable_alerts.append(event)

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=1,
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="^max_pages$"):
        await reconstructed.sync_account(account.id)
    assert len(durable_alerts) == 1
    assert durable_alerts[0]["event"] == "max_pages"
    assert adapter.history_calls == 1

@pytest.mark.parametrize(
    "category",
    ["rate_limited", "transient_provider", "provider_timeout"],
)
async def test_retryable_poll_failure_resumes_from_committed_page_token(
    history_runtime,
    category: str,
) -> None:
    from models.gmail_task_intake import (
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import GmailProviderFailure
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")

    class _RetryingAdapter:
        page_tokens: list[str | None] = []
        failed_once = False

        async def list_history(self, *, page_token, **_kwargs):
            self.page_tokens.append(page_token)
            if page_token is None:
                return _page(
                    history_id="101",
                    next_page_token="resume-page-2",
                    messages=(),
                    history_min="101",
                    history_max="101",
                )
            assert page_token == "resume-page-2"
            if not self.failed_once:
                self.failed_once = True
                raise GmailProviderFailure(category)
            return _page(
                history_id="102",
                next_page_token=None,
                messages=(),
                history_min="102",
                history_max="102",
            )

    adapter = _RetryingAdapter()
    first = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    with pytest.raises(GmailProviderFailure, match=f"^{category}$"):
        await first.sync_account(account.id)

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )
        checkpoint_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(GmailSyncPageCheckpoint)
            .where(GmailSyncPageCheckpoint.run_id == run.id)
        )
    assert stored.committed_history_id == "100"
    assert stored.last_error_category == category
    assert run.state == "running"
    assert run.next_page_token == "resume-page-2"
    assert run.failure_category == category
    assert checkpoint_count == 1

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    result = await reconstructed.sync_account(account.id)
    assert result.committed_history_id == "102"
    assert adapter.page_tokens == [None, "resume-page-2", "resume-page-2"]
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run = await session.get(GmailSyncRun, run.id)
    assert stored.committed_history_id == "102"
    assert stored.last_error_category is None
    assert run.state == "completed"
    assert run.failure_category is None


async def test_first_enable_seeds_current_profile_cursor_without_scanning_history(
    history_runtime,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_adapter import GmailProfile
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor=None)

    class _SeedAdapter:
        history_calls = 0

        async def get_profile(self, **_kwargs):
            return GmailProfile(
                email_address=account.workspace_email,
                history_id="9000",
            )

        async def list_history(self, **_kwargs):
            self.history_calls += 1
            raise AssertionError("first enable must not scan history")

    adapter = _SeedAdapter()
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    result = await service.sync_account(account.id)
    assert result.seeded is True
    assert result.committed_history_id == "9000"
    assert adapter.history_calls == 0
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncRun).where(
                GmailSyncRun.account_id == account.id
            )
        )
    assert stored.committed_history_id == "9000"
    assert run_count == 0


async def test_first_enable_profile_identity_mismatch_writes_no_cursor_or_page_state(
    history_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import GmailProfile
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService
    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
    )

    engine, sessionmaker = history_runtime
    account = await _seed_account(
        sessionmaker,
        cursor=None,
        email="bound-mailbox@example.test",
    )

    class _WrongProfileAdapter:
        async def get_profile(self, **_kwargs):
            return GmailProfile(
                email_address="different-mailbox@example.test",
                history_id="poison-cursor-9000",
            )

        async def list_history(self, **_kwargs):
            raise AssertionError("identity mismatch must not scan history")

    verifier = await engine.connect()
    service = GmailHistoryService(
        engine=engine,
        adapter=_WrongProfileAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=_noop_alert_sink,
    )
    try:
        with pytest.raises(
            GmailAccountBlocked, match="^gmail_account_identity_mismatch$"
        ):
            await service.sync_account(account.id)
        assert await try_session_advisory_lock(verifier, account.id)
        assert await release_session_advisory_lock(verifier, account.id)
        await verifier.commit()
    finally:
        await verifier.close()

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncRun).where(
                GmailSyncRun.account_id == account.id
            )
        )
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
        checkpoint_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncPageCheckpoint)
        )
    assert stored.committed_history_id is None
    assert stored.reseed_history_id is None
    assert stored.blocked_reason == "gmail_account_identity_mismatch"
    assert run_count == 0
    assert receipt_count == 0
    assert checkpoint_count == 0


@pytest.mark.parametrize(
    "invalid_history_id",
    ["", "0", "01", "not-numeric", "18446744073709551616"],
)
async def test_first_enable_rejects_invalid_profile_history_id_without_state(
    history_runtime,
    invalid_history_id: str,
) -> None:
    from models.gmail_task_intake import (
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import GmailProfile, GmailProviderFailure
    from services.gmail_history_service import GmailHistoryService
    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
    )

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor=None)

    class _InvalidProfileAdapter:
        async def get_profile(self, **_kwargs):
            return GmailProfile(
                email_address=account.workspace_email,
                history_id=invalid_history_id,
            )

        async def list_history(self, **_kwargs):
            raise AssertionError("invalid seed must not scan History")

    verifier = await engine.connect()
    service = GmailHistoryService(
        engine=engine,
        adapter=_InvalidProfileAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=_noop_alert_sink,
    )
    try:
        with pytest.raises(GmailProviderFailure, match="^malformed_provider$"):
            await service.sync_account(account.id)
        assert await try_session_advisory_lock(verifier, account.id)
        assert await release_session_advisory_lock(verifier, account.id)
        await verifier.commit()
    finally:
        await verifier.close()

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncRun).where(
                GmailSyncRun.account_id == account.id
            )
        )
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
        checkpoint_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncPageCheckpoint)
        )
    assert stored.committed_history_id is None
    assert stored.reseed_history_id is None
    assert stored.blocked_reason == "malformed_provider"
    assert stored.last_error_category == "malformed_provider"
    assert stored.last_error_message == "Gmail provider returned an invalid response."
    assert run_count == 0
    assert receipt_count == 0
    assert checkpoint_count == 0


async def test_first_enable_malformed_profile_blocks_and_dedupes_after_restart(
    history_runtime,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_adapter import GmailProfile, GmailProviderFailure
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor=None)
    profile_calls = 0
    alerts: list[dict[str, str]] = []

    class _MalformedProfileAdapter:
        async def get_profile(self, **_kwargs):
            nonlocal profile_calls
            profile_calls += 1
            return GmailProfile(
                email_address=account.workspace_email,
                history_id="not-a-history-id",
            )

        async def list_history(self, **_kwargs):
            raise AssertionError("malformed seed must not scan History")

    async def alert_sink(**event):
        alerts.append(event)

    first = GmailHistoryService(
        engine=engine,
        adapter=_MalformedProfileAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailProviderFailure, match="^malformed_provider$"):
        await first.sync_account(account.id)

    restarted = GmailHistoryService(
        engine=engine,
        adapter=_MalformedProfileAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="^malformed_provider$"):
        await restarted.sync_account(account.id)

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncRun).where(
                GmailSyncRun.account_id == account.id
            )
        )
    assert profile_calls == 1
    assert stored.committed_history_id is None
    assert stored.blocked_reason == "malformed_provider"
    assert stored.last_error_category == "malformed_provider"
    assert run_count == 0
    assert [event["event"] for event in alerts] == ["malformed_provider"]
    assert len({event["dedupe_key"] for event in alerts}) == 1


@pytest.mark.parametrize(
    ("start_history_id", "terminal_history_id", "history_min", "history_max"),
    [
        ("700", "bad-terminal", "701", "701"),
        ("700", "699", "699", "699"),
        ("700", "702", "700", "701"),
        ("700", "702", "701", "703"),
    ],
)
async def test_service_rejects_invalid_or_nonmonotone_history_page_before_metadata(
    history_runtime,
    start_history_id: str,
    terminal_history_id: str,
    history_min: str,
    history_max: str,
) -> None:
    from models.gmail_task_intake import (
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import GmailProviderFailure
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor=start_history_id)
    adapter = _ScriptedAdapter(
        {
            None: _page(
                history_id=terminal_history_id,
                next_page_token=None,
                messages=(("must-not-hydrate", "thread"),),
                history_min=history_min,
                history_max=history_max,
            )
        },
        {"must-not-hydrate": _metadata("must-not-hydrate", "thread", ("INBOX",))},
    )
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=_noop_alert_sink,
    )
    with pytest.raises(GmailProviderFailure, match="^malformed_provider$"):
        await service.sync_account(account.id)

    assert adapter.metadata_calls == []
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt)
        )
        checkpoint_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncPageCheckpoint)
        )
    assert stored.committed_history_id == start_history_id
    assert stored.last_error_category == "malformed_provider"
    assert run.state == "failed"
    assert receipt_count == 0
    assert checkpoint_count == 0


async def test_invalid_persisted_cursor_fails_closed_before_provider_call(
    history_runtime,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_adapter import GmailProviderFailure
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="corrupt-local-cursor")
    adapter = _ScriptedAdapter({}, {})
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=_noop_alert_sink,
    )
    with pytest.raises(GmailProviderFailure, match="^malformed_provider$"):
        await service.sync_account(account.id)

    assert adapter.history_calls == []
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncRun).where(
                GmailSyncRun.account_id == account.id
            )
        )
    assert stored.committed_history_id == "corrupt-local-cursor"
    assert stored.blocked_reason == "malformed_provider"
    assert stored.last_error_category == "malformed_provider"
    assert run_count == 0


@pytest.mark.parametrize("guard", ["repeated_token", "max_pages"])
async def test_pagination_guards_prevent_infinite_job_and_cursor_advance(
    history_runtime,
    guard: str,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_service import (
        GmailAccountBlocked,
        GmailHistoryService,
        GmailPaginationGuard,
    )

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="7000")

    class _LoopAdapter:
        calls = 0

        async def list_history(self, *, page_token, **_kwargs):
            self.calls += 1
            next_token = "repeat" if self.calls > 1 else "repeat"
            if guard == "max_pages":
                next_token = f"page-{self.calls + 1}"
            return _page(
                history_id=str(8000 + self.calls),
                next_page_token=next_token,
                messages=(),
                history_min=str(8000 + self.calls),
                history_max=str(8000 + self.calls),
            )

    adapter = _LoopAdapter()
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=2,
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailPaginationGuard):
        await asyncio.wait_for(service.sync_account(account.id), timeout=2)
    assert adapter.calls <= 2

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=2,
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match=f"^{guard}$"):
        await reconstructed.sync_account(account.id)
    assert adapter.calls == 2
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        runs = list(
            (
                await session.scalars(
                    sa.select(GmailSyncRun).where(
                        GmailSyncRun.account_id == account.id
                    )
                )
            ).all()
        )
    assert stored.committed_history_id == "7000"
    assert stored.blocked_reason == guard
    assert stored.last_error_category == guard
    assert len(runs) == 1
    assert len(alerts) == 1
    assert alerts[0]["event"] == guard
    assert alerts[0]["dedupe_key"].endswith(
        hashlib.sha256(b"7000").hexdigest()[:16]
    )


async def test_resumed_poll_enforces_max_pages_across_durable_checkpoints(
    history_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_service import GmailHistoryService, GmailPaginationGuard

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")

    class _CrashAfterTwoPages:
        calls = 0

        async def list_history(self, *, page_token, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                assert page_token is None
                return _page(
                    history_id="101",
                    next_page_token="cumulative-page-2",
                    messages=(),
                    history_min="101",
                    history_max="101",
                )
            if self.calls == 2:
                assert page_token == "cumulative-page-2"
                return _page(
                    history_id="102",
                    next_page_token="cumulative-page-3",
                    messages=(),
                    history_min="102",
                    history_max="102",
                )
            raise RuntimeError("synthetic poll restart after two commits")

    first = GmailHistoryService(
        engine=engine,
        adapter=_CrashAfterTwoPages(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=10,
    )
    with pytest.raises(RuntimeError, match="synthetic poll restart"):
        await first.sync_account(account.id)

    class _MustNotCallProvider:
        calls = 0

        async def list_history(self, **_kwargs):
            self.calls += 1
            raise AssertionError("persisted max-page bound must run before provider")

    adapter = _MustNotCallProvider()
    resumed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=2,
        alert_sink=_noop_alert_sink,
    )
    with pytest.raises(GmailPaginationGuard, match="gmail_history_max_pages"):
        await resumed.sync_account(account.id)
    assert adapter.calls == 0

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )
        checkpoints = list(
            (
                await session.scalars(
                    sa.select(GmailSyncPageCheckpoint).where(
                        GmailSyncPageCheckpoint.run_id == run.id
                    )
                )
            ).all()
        )
    assert stored.committed_history_id == "100"
    assert run.failure_category == "max_pages"
    assert len(checkpoints) == 2


async def test_missing_message_metadata_blocks_manual_recovery_without_cursor_advance(
    history_runtime,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_adapter import GmailProviderFailure
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = history_runtime
    account = await _seed_account(sessionmaker, cursor="100")

    class _MissingAdapter:
        async def list_history(self, **_kwargs):
            return _page(
                history_id="101",
                next_page_token=None,
                messages=(("gone-message", "gone-thread"),),
                history_min="101",
                history_max="101",
            )

        async def get_message_metadata(self, **_kwargs):
            raise GmailProviderFailure("message_not_found")

    service = GmailHistoryService(
        engine=engine,
        adapter=_MissingAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=_noop_alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="message_not_found"):
        await service.sync_account(account.id)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )
    assert stored.committed_history_id == "100"
    assert stored.blocked_reason == "message_not_found"
    assert run.state == "running"
    assert run.failure_category == "message_not_found"
    assert run.next_page_token is None
