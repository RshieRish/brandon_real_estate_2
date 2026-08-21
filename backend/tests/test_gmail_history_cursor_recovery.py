from __future__ import annotations

import asyncio
import hashlib
import traceback
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "83c6f4e8a1b2"
UTC = timezone.utc


@pytest.fixture(scope="module")
def recovery_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def recovery_runtime(recovery_database):
    url, sync_engine = recovery_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE gmail_sync_accounts, agent_action_audits, "
                "admin_users CASCADE"
            )
        )
    engine = create_async_engine(async_test_url(url), pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessionmaker
    finally:
        await engine.dispose()


async def _seed_account(sessionmaker, *, cursor: str = "700"):
    from models.gmail_task_intake import GmailSyncAccount

    account = GmailSyncAccount(
        workspace_email=f"recovery-{uuid4()}@example.test",
        committed_history_id=cursor,
        mode="shadow",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.commit()
        await session.refresh(account)
    return account


class _ExpiredAdapter:
    def __init__(self, *, email_address: str = "unused@example.test"):
        self.history_calls = 0
        self.profile_calls = 0
        self.email_address = email_address

    async def list_history(self, **_kwargs):
        from services.gmail_history_adapter import GmailProviderFailure

        self.history_calls += 1
        raise GmailProviderFailure("history_cursor_expired")

    async def get_profile(self, **_kwargs):
        from services.gmail_history_adapter import GmailProfile

        self.profile_calls += 1
        return GmailProfile(
            email_address=self.email_address,
            history_id="999",
        )


async def test_expired_cursor_blocks_without_advancing_and_alerts_once(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker)
    adapter = _ExpiredAdapter(email_address=account.workspace_email)
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="history_cursor_expired"):
        await service.sync_account(account.id)

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )

    assert stored.committed_history_id == "700"
    assert stored.reseed_history_id == "999"
    assert stored.blocked_reason == "history_cursor_expired"
    assert stored.last_error_category == "history_cursor_expired"
    assert run.start_history_id == "700"
    assert run.state == "blocked_expired_cursor"
    assert run.terminal_history_id is None
    assert run.next_page_token is None
    assert alerts == [
        {
            "provider": "gmail_task_intake",
            "account_id": str(account.id),
            "event": "history_cursor_expired",
            "dedupe_key": (
                f"gmail-task-intake:{account.id}:history-cursor-expired:"
                + hashlib.sha256(b"700").hexdigest()[:16]
            ),
        }
    ]

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="history_cursor_expired"):
        await reconstructed.sync_account(account.id)
    assert adapter.history_calls == 1
    assert adapter.profile_calls == 1
    assert len(alerts) == 1

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.committed_history_id = "701"
        stored.reseed_history_id = None
        stored.blocked_reason = None
        stored.last_error_category = None
        stored.last_error_message = None
        await session.commit()
    later_adapter = _ExpiredAdapter(email_address=account.workspace_email)
    later = GmailHistoryService(
        engine=engine,
        adapter=later_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="history_cursor_expired"):
        await later.sync_account(account.id)
    assert len(alerts) == 2
    assert alerts[1]["dedupe_key"].endswith(
        hashlib.sha256(b"701").hexdigest()[:16]
    )


async def test_expired_cursor_profile_identity_mismatch_never_sets_reseed(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    service = GmailHistoryService(
        engine=engine,
        adapter=_ExpiredAdapter(email_address="different@example.test"),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="gmail_account_identity_mismatch"):
        await service.sync_account(account.id)

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )
    assert stored.committed_history_id == "700"
    assert stored.reseed_history_id is None
    assert stored.blocked_reason == "gmail_account_identity_mismatch"
    assert run.state == "failed"
    assert alerts[0]["event"] == "gmail_account_identity_mismatch"


@pytest.mark.parametrize(
    "invalid_reseed_history_id",
    ["0", "699", "bad-reseed", "18446744073709551616"],
)
async def test_expired_cursor_invalid_profile_history_id_is_restart_resumable(
    recovery_runtime,
    invalid_reseed_history_id: str,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_adapter import GmailProfile, GmailProviderFailure
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    class _InvalidThenValidProfileAdapter:
        history_calls = 0
        profile_calls = 0

        async def list_history(self, **_kwargs):
            self.history_calls += 1
            raise GmailProviderFailure("history_cursor_expired")

        async def get_profile(self, **_kwargs):
            self.profile_calls += 1
            return GmailProfile(
                email_address=account.workspace_email,
                history_id=(
                    invalid_reseed_history_id
                    if self.profile_calls == 1
                    else "999"
                ),
            )

    adapter = _InvalidThenValidProfileAdapter()
    first = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailProviderFailure, match="^malformed_provider$"):
        await first.sync_account(account.id)

    async with sessionmaker() as session:
        incomplete = await session.get(GmailSyncAccount, account.id)
        failed_run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )
    assert incomplete.committed_history_id == "700"
    assert incomplete.reseed_history_id is None
    assert incomplete.blocked_reason == "history_cursor_expired"
    assert incomplete.last_error_category == "malformed_provider"
    assert failed_run.state == "failed"
    assert alerts == []

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="^history_cursor_expired$"):
        await reconstructed.sync_account(account.id)

    async with sessionmaker() as session:
        recovered = await session.get(GmailSyncAccount, account.id)
    assert recovered.committed_history_id == "700"
    assert recovered.reseed_history_id == "999"
    assert recovered.blocked_reason == "history_cursor_expired"
    assert alerts == [
        {
            "provider": "gmail_task_intake",
            "account_id": str(account.id),
            "event": "history_cursor_expired",
            "dedupe_key": (
                f"gmail-task-intake:{account.id}:history-cursor-expired:"
                + hashlib.sha256(b"700").hexdigest()[:16]
            ),
        }
    ]


@pytest.mark.parametrize("dependency_category", ["rate_limited", "transient_provider"])
async def test_expired_cursor_profile_dependency_failure_is_restart_resumable(
    recovery_runtime,
    caplog: pytest.LogCaptureFixture,
    dependency_category: str,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_adapter import GmailProfile, GmailProviderFailure
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(
        sessionmaker,
        cursor="700",
    )
    secret = f"raw-profile-dependency-{dependency_category}-canary"
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    class _RecoveringProfileAdapter:
        history_calls = 0
        profile_calls = 0

        async def list_history(self, **_kwargs):
            self.history_calls += 1
            raise GmailProviderFailure("history_cursor_expired")

        async def get_profile(self, **_kwargs):
            self.profile_calls += 1
            if self.profile_calls == 1:
                raise GmailProviderFailure(dependency_category) from RuntimeError(
                    secret
                )
            return GmailProfile(
                email_address=account.workspace_email,
                history_id="999",
            )

    adapter = _RecoveringProfileAdapter()
    first = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with caplog.at_level("ERROR"):
        with pytest.raises(
            GmailProviderFailure, match=f"^{dependency_category}$"
        ) as raised:
            await first.sync_account(account.id)

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        failed_run = await session.scalar(
            sa.select(GmailSyncRun)
            .where(GmailSyncRun.account_id == account.id)
            .order_by(GmailSyncRun.started_at.desc())
        )
    assert stored.committed_history_id == "700"
    assert stored.reseed_history_id is None
    assert stored.blocked_reason == "history_cursor_expired"
    assert stored.last_error_category == dependency_category
    assert failed_run.state == "failed"
    assert failed_run.failure_category == dependency_category
    assert alerts == []
    assert secret not in caplog.text
    assert secret not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__suppress_context__ is True

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(
        GmailAccountBlocked, match="^history_cursor_expired$"
    ):
        await reconstructed.sync_account(account.id)
    assert adapter.history_calls == 1
    assert adapter.profile_calls == 2
    assert len(alerts) == 1

    async with sessionmaker() as session:
        recovered = await session.get(GmailSyncAccount, account.id)
    assert recovered.committed_history_id == "700"
    assert recovered.reseed_history_id == "999"
    assert recovered.blocked_reason == "history_cursor_expired"
    assert recovered.last_error_category == "history_cursor_expired"

    final_restart = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="^history_cursor_expired$"):
        await final_restart.sync_account(account.id)
    assert adapter.history_calls == 1
    assert adapter.profile_calls == 2
    assert len(alerts) == 1


async def test_current_oauth_revoke_during_cursor_recovery_blocks_until_reconnect(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from services.gmail_history_adapter import GmailProfile, GmailProviderFailure
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")

    class _OAuthRecoveryAdapter:
        history_calls = 0
        profile_calls = 0

        async def list_history(self, **_kwargs):
            self.history_calls += 1
            raise GmailProviderFailure("history_cursor_expired")

        async def get_profile(self, **_kwargs):
            self.profile_calls += 1
            if self.profile_calls == 1:
                raise GmailProviderFailure("oauth_revoked")
            return GmailProfile(
                email_address=account.workspace_email,
                history_id="999",
            )

    async def current_credential(_session):
        return True

    async def alert_sink(**_event):
        return None

    adapter = _OAuthRecoveryAdapter()
    first = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
        credential_is_current=current_credential,
    )
    with pytest.raises(GmailProviderFailure, match="^oauth_revoked$"):
        await first.sync_account(account.id)

    async with sessionmaker() as session:
        blocked = await session.get(GmailSyncAccount, account.id)
    assert blocked.committed_history_id == "700"
    assert blocked.reseed_history_id is None
    assert blocked.blocked_reason == "oauth_revoked"
    assert blocked.last_error_category == "oauth_revoked"

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
        credential_is_current=current_credential,
    )
    with pytest.raises(GmailAccountBlocked, match="^oauth_revoked$"):
        await reconstructed.sync_account(account.id)
    assert adapter.history_calls == 1
    assert adapter.profile_calls == 1

    async with sessionmaker() as session:
        reconnected = await session.get(GmailSyncAccount, account.id)
        reconnected.blocked_reason = None
        reconnected.last_error_category = None
        reconnected.last_error_message = None
        await session.commit()

    with pytest.raises(GmailAccountBlocked, match="^history_cursor_expired$"):
        await reconstructed.sync_account(account.id)
    assert adapter.history_calls == 2
    assert adapter.profile_calls == 2
    async with sessionmaker() as session:
        recovering = await session.get(GmailSyncAccount, account.id)
    assert recovering.blocked_reason == "history_cursor_expired"
    assert recovering.reseed_history_id == "999"


async def test_expired_cursor_alert_failure_is_restart_resumable_and_deduped(
    recovery_runtime,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    adapter = _ExpiredAdapter(email_address=account.workspace_email)
    secret = "raw-alert-persistence-canary"
    attempts = 0
    durable_alerts: list[dict[str, str]] = []

    async def recovering_alert_sink(**event):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError(secret)
        durable_alerts.append(event)

    first = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=recovering_alert_sink,
    )
    with caplog.at_level("ERROR"):
        with pytest.raises(
            RuntimeError, match="^gmail_history_alert_enqueue_failed$"
        ) as raised:
            await first.sync_account(account.id)

    async with sessionmaker() as session:
        incomplete = await session.get(GmailSyncAccount, account.id)
    assert incomplete.committed_history_id == "700"
    assert incomplete.reseed_history_id == "999"
    assert incomplete.blocked_reason == "history_cursor_expired"
    assert incomplete.last_error_category == "history_cursor_expired_alert_pending"
    assert durable_alerts == []
    assert secret not in caplog.text
    assert secret not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__suppress_context__ is True

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=recovering_alert_sink,
    )
    with pytest.raises(
        GmailAccountBlocked, match="^history_cursor_expired$"
    ):
        await reconstructed.sync_account(account.id)
    assert attempts == 2
    assert len(durable_alerts) == 1
    assert adapter.history_calls == 1
    assert adapter.profile_calls == 1

    after_successful_alert = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=recovering_alert_sink,
    )
    with pytest.raises(GmailAccountBlocked, match="^history_cursor_expired$"):
        await after_successful_alert.sync_account(account.id)
    assert attempts == 2
    assert len(durable_alerts) == 1
    async with sessionmaker() as session:
        recovered = await session.get(GmailSyncAccount, account.id)
    assert recovered.last_error_category == "history_cursor_expired"


async def _seed_admin_and_audit(sessionmaker) -> tuple[int, int]:
    from models.admin_user import AdminUser
    from models.agent_action_audit import AgentActionAudit

    async with sessionmaker() as session:
        admin = AdminUser(
            email=f"admin-{uuid4()}@example.test",
            hashed_password="not-a-real-password",
        )
        audit = AgentActionAudit(
            actor="admin",
            action_id="gmail.backfill.request",
            method="POST",
            path="/test/backfill",
            status_code=200,
            allowed=True,
            request_meta_json="{}",
            response_meta_json="{}",
        )
        session.add_all([admin, audit])
        await session.commit()
        await session.refresh(admin)
        await session.refresh(audit)
        return admin.id, audit.id


@pytest.mark.parametrize("failure_stage", ["metadata", "content"])
async def test_missing_poll_message_requires_admin_ack_then_resumes_exact_run(
    recovery_runtime,
    failure_stage: str,
) -> None:
    import httpx
    from fastapi import FastAPI
    from jose import jwt

    from config import settings
    from database import get_db
    from middleware.auth import ADMIN_SESSION_SCOPE, ADMIN_SESSION_TOKEN_TYPE
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import (
        GmailMessageReceipt,
        GmailMissingMessageIncident,
        GmailSyncAccount,
        GmailSyncRun,
    )
    from routers import agent_control
    from services.gmail_history_adapter import (
        GmailHistoryMessageRef,
        GmailHistoryPage,
        GmailMessageMetadata,
        GmailProviderFailure,
    )
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, _audit_id = await _seed_admin_and_audit(sessionmaker)
    message_at = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)

    class _Observer:
        def prepare_history_sent_observation(self, **_kwargs):
            raise AssertionError("missing content must not create an observation")

        async def observe_history_sent_in_session(self, *_args, **_kwargs):
            raise AssertionError("missing content must not reach persistence")

    class _DeletedMessageAdapter:
        list_calls = 0
        metadata_calls: list[str] = []
        content_calls: list[str] = []

        async def list_history(self, **_kwargs):
            self.list_calls += 1
            return GmailHistoryPage(
                history_id="701",
                messages=(
                    GmailHistoryMessageRef("gone-message", "gone-thread"),
                    GmailHistoryMessageRef("kept-message", "kept-thread"),
                ),
                next_page_token=None,
                discovered_history_id_min="701",
                discovered_history_id_max="701",
            )

        async def get_message_metadata(self, *, message_id, **_kwargs):
            self.metadata_calls.append(message_id)
            if message_id == "gone-message" and failure_stage == "metadata":
                raise GmailProviderFailure("message_not_found")
            if message_id == "gone-message":
                return GmailMessageMetadata(
                    message_id=message_id,
                    thread_id="gone-thread",
                    label_ids=("SENT",),
                    message_at=message_at,
                    headers={
                        "From": account.workspace_email,
                        "To": "client@example.test",
                        "Subject": "Deleted after History discovery",
                    },
                )
            return GmailMessageMetadata(
                message_id=message_id,
                thread_id="kept-thread",
                label_ids=("INBOX",),
                message_at=message_at,
                headers={
                    "From": "client@example.test",
                    "To": account.workspace_email,
                    "Subject": "Still available",
                },
            )

        async def get_message_content(self, *, message_id, **_kwargs):
            self.content_calls.append(message_id)
            raise GmailProviderFailure("message_not_found")

    adapter = _DeletedMessageAdapter()
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
        origin_observer=(_Observer() if failure_stage == "content" else None),
    )
    with pytest.raises(GmailAccountBlocked, match="^message_not_found$"):
        await service.sync_account(account.id)

    async with sessionmaker() as session:
        incident = await session.scalar(
            sa.select(GmailMissingMessageIncident).where(
                GmailMissingMessageIncident.account_id == account.id
            )
        )
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )
        stored = await session.get(GmailSyncAccount, account.id)
    assert incident is not None
    assert incident.gmail_message_id == "gone-message"
    assert incident.gmail_thread_id == "gone-thread"
    assert incident.start_history_id == "700"
    assert incident.page_number == 1
    assert incident.request_page_token is None
    assert incident.state == "pending"
    assert incident.alert_state == "sent"
    assert run.state == "running"
    assert stored.committed_history_id == "700"
    assert stored.blocked_reason == "message_not_found"
    assert len(alerts) == 1
    assert alerts[0]["dedupe_key"].endswith(str(incident.id))
    assert alerts[0]["incident_id"] == str(incident.id)
    assert alerts[0]["detail_path"] == (
        "/api/v1/agent-control/gmail/missing-message/incidents/"
        f"{incident.id}"
    )
    assert set(alerts[0]) == {
        "provider",
        "account_id",
        "event",
        "dedupe_key",
        "incident_id",
        "detail_path",
    }

    app = FastAPI()
    app.include_router(agent_control.router, prefix="/api/v1/agent-control")

    async def override_db():
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_db
    token = jwt.encode(
        {
            "sub": str(admin_id),
            "token_type": ADMIN_SESSION_TOKEN_TYPE,
            "scope": ADMIN_SESSION_SCOPE,
            "exp": datetime.now(tz=UTC) + timedelta(minutes=10),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test.example",
    ) as client:
        incident_from_alert = alerts[0]["incident_id"]
        assert incident_from_alert == str(incident.id)
        unauthorized_detail = await client.get(
            f"/api/v1/agent-control/gmail/missing-message/incidents/"
            f"{incident_from_alert}"
        )
        assert unauthorized_detail.status_code == 401
        missing_detail = await client.get(
            f"/api/v1/agent-control/gmail/missing-message/incidents/{uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert missing_detail.status_code == 404
        assert (
            missing_detail.json()["detail"]
            == "gmail_missing_message_incident_not_found"
        )
        detail = await client.get(
            f"/api/v1/agent-control/gmail/missing-message/incidents/"
            f"{incident_from_alert}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail.status_code == 200
        detail_payload = detail.json()
        assert detail_payload == {
            "incident_id": str(incident.id),
            "account_id": str(account.id),
            "run_id": str(run.id),
            "gmail_message_id": "gone-message",
            "gmail_thread_id": "gone-thread",
            "expected_start_history_id": "700",
            "expected_page_number": 1,
            "expected_request_page_token": None,
            "expected_version": 1,
            "backfill_request_id": None,
            "expected_reseed_history_id": None,
        }
        assert not any(
            forbidden in key
            for key in detail_payload
            for forbidden in ("body", "subject", "sender", "recipient")
        )
        payload = {
            **detail_payload,
            "reason": "Acknowledge the provider-confirmed deletion and resume.",
        }
        unauthorized = await client.post(
            "/api/v1/agent-control/gmail/missing-message/acknowledge",
            json=payload,
        )
        assert unauthorized.status_code == 401
        stale = await client.post(
            "/api/v1/agent-control/gmail/missing-message/acknowledge",
            json={**payload, "expected_version": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"] == "gmail_missing_message_ack_conflict"
        acknowledged = await client.post(
            "/api/v1/agent-control/gmail/missing-message/acknowledge",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert acknowledged.status_code == 200
        assert acknowledged.json()["version"] == 2

    resumed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
        origin_observer=(_Observer() if failure_stage == "content" else None),
    )
    result = await resumed.sync_account(account.id)
    assert result.committed_history_id == "701"
    assert adapter.list_calls == 2
    assert adapter.metadata_calls.count("gone-message") == 1
    assert adapter.content_calls == (
        ["gone-message"] if failure_stage == "content" else []
    )
    assert len(alerts) == 1

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored_run = await session.get(GmailSyncRun, run.id)
        stored_incident = await session.get(GmailMissingMessageIncident, incident.id)
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
                    sa.select(AgentActionAudit).where(
                        AgentActionAudit.action_id
                        == "gmail.missing_message.acknowledge"
                    )
                )
            ).all()
        )
    assert stored.committed_history_id == "701"
    assert stored.blocked_reason is None
    assert stored_run.state == "completed"
    assert stored_incident.state == "acknowledged"
    assert stored_incident.version == 2
    assert [row.gmail_message_id for row in receipts] == ["kept-message"]
    assert len(audits) == 1
    assert audits[0].actor == f"admin:{admin_id}"


@pytest.mark.parametrize("failure_stage", ["metadata", "content"])
async def test_missing_backfill_message_ack_resumes_same_request_and_promotes(
    recovery_runtime,
    failure_stage: str,
) -> None:
    from types import SimpleNamespace

    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailMissingMessageIncident,
        GmailSyncAccount,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import (
        GmailHistoryMessageRef,
        GmailMessageListPage,
        GmailMessageMetadata,
        GmailProviderFailure,
    )
    from services.gmail_history_service import (
        GmailAccountBlocked,
        GmailHistoryService,
        GmailMissingMessageAcknowledgementError,
        acknowledge_missing_message_incident,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    message_at = start + timedelta(hours=1)

    class _Observer:
        def prepare_history_sent_observation(self, **_kwargs):
            raise AssertionError("missing content must not create an observation")

        async def observe_history_sent_in_session(self, *_args, **_kwargs):
            raise AssertionError("missing content must not reach persistence")

    class _DeletedBackfillAdapter:
        list_calls = 0
        metadata_calls: list[str] = []
        content_calls: list[str] = []

        async def list_messages_for_backfill(self, **_kwargs):
            self.list_calls += 1
            return GmailMessageListPage(
                messages=(
                    GmailHistoryMessageRef("gone-backfill", "gone-thread"),
                    GmailHistoryMessageRef("kept-backfill", "kept-thread"),
                ),
                next_page_token=None,
            )

        async def get_message_metadata(self, *, message_id, **_kwargs):
            self.metadata_calls.append(message_id)
            if message_id == "gone-backfill" and failure_stage == "metadata":
                raise GmailProviderFailure("message_not_found")
            if message_id == "gone-backfill":
                return GmailMessageMetadata(
                    message_id=message_id,
                    thread_id="gone-thread",
                    label_ids=("SENT",),
                    message_at=message_at,
                    headers={
                        "From": account.workspace_email,
                        "To": "client@example.test",
                        "Subject": "Deleted during bounded backfill",
                    },
                )
            return GmailMessageMetadata(
                message_id=message_id,
                thread_id="kept-thread",
                label_ids=("INBOX",),
                message_at=message_at,
                headers={
                    "From": "client@example.test",
                    "To": account.workspace_email,
                    "Subject": "Available backfill message",
                },
            )

        async def get_message_content(self, *, message_id, **_kwargs):
            self.content_calls.append(message_id)
            raise GmailProviderFailure("message_not_found")

    adapter = _DeletedBackfillAdapter()
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
        origin_observer=(_Observer() if failure_stage == "content" else None),
    )
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Recover the bounded window with explicit deletion review.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    with pytest.raises(GmailAccountBlocked, match="^message_not_found$"):
        await service.run_backfill(request.id)

    async with sessionmaker() as session:
        stored_request = await session.get(GmailBackfillRequest, request.id)
        run = await session.get(GmailSyncRun, stored_request.run_id)
        incident = await session.scalar(
            sa.select(GmailMissingMessageIncident).where(
                GmailMissingMessageIncident.run_id == run.id
            )
        )
    assert stored_request.state == "running"
    assert run.state == "running"
    assert incident.state == "pending"
    assert incident.alert_state == "sent"
    assert len(alerts) == 1

    from routers.agent_control import get_gmail_missing_message_incident

    async with sessionmaker() as session:
        detail = await get_gmail_missing_message_incident(
            incident.id,
            admin_id,
            session,
        )
    assert detail.model_dump() == {
        "incident_id": incident.id,
        "account_id": account.id,
        "run_id": run.id,
        "gmail_message_id": "gone-backfill",
        "gmail_thread_id": "gone-thread",
        "expected_start_history_id": "700",
        "expected_page_number": 1,
        "expected_request_page_token": None,
        "expected_version": 1,
        "backfill_request_id": request.id,
        "expected_reseed_history_id": "999",
    }

    call = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(
            path="/api/v1/agent-control/gmail/missing-message/acknowledge"
        ),
    )
    kwargs = {
        "request": call,
        "incident_id": incident.id,
        "account_id": account.id,
        "run_id": run.id,
        "gmail_message_id": "gone-backfill",
        "gmail_thread_id": "gone-thread",
        "expected_start_history_id": "700",
        "expected_page_number": 1,
        "expected_request_page_token": None,
        "expected_version": 1,
        "reason": "Acknowledge the exact deleted backfill message.",
        "backfill_request_id": request.id,
        "expected_reseed_history_id": "999",
    }
    async with sessionmaker() as session:
        with pytest.raises(
            GmailMissingMessageAcknowledgementError,
            match="^gmail_missing_message_admin_required$",
        ):
            await acknowledge_missing_message_incident(
                session,
                administrator_id=admin_id + 100_000,
                **kwargs,
            )
        await session.rollback()
    async with sessionmaker() as session:
        with pytest.raises(
            GmailMissingMessageAcknowledgementError,
            match="^gmail_missing_message_ack_conflict$",
        ):
            await acknowledge_missing_message_incident(
                session,
                administrator_id=admin_id,
                **{**kwargs, "expected_version": 2},
            )
        await session.rollback()
    async with sessionmaker() as session:
        acknowledged = await acknowledge_missing_message_incident(
            session,
            administrator_id=admin_id,
            **kwargs,
        )
        await session.commit()
    assert acknowledged.state == "acknowledged"

    await service.run_backfill(request.id)
    promoted = await service.promote_reseed_after_backfill(request.id)
    assert promoted.committed_history_id == "999"
    assert adapter.list_calls == 2
    assert adapter.metadata_calls.count("gone-backfill") == 1
    assert adapter.content_calls == (
        ["gone-backfill"] if failure_stage == "content" else []
    )
    assert len(alerts) == 1
    async with sessionmaker() as session:
        final_request = await session.get(GmailBackfillRequest, request.id)
        final_run = await session.get(GmailSyncRun, run.id)
        final_incident = await session.get(
            GmailMissingMessageIncident,
            incident.id,
        )
    assert final_request.state == "completed"
    assert final_run.state == "completed"
    assert final_incident.state == "acknowledged"


@pytest.mark.parametrize("run_kind", ["poll", "backfill"])
async def test_acknowledged_missing_message_does_not_waive_thread_drift(
    recovery_runtime,
    run_kind: str,
) -> None:
    from types import SimpleNamespace

    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailMissingMessageIncident,
        GmailSyncAccount,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import (
        GmailHistoryMessageRef,
        GmailHistoryPage,
        GmailMessageListPage,
        GmailProviderFailure,
    )
    from services.gmail_history_service import (
        GmailAccountBlocked,
        GmailHistoryService,
        acknowledge_missing_message_incident,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    if run_kind == "backfill":
        async with sessionmaker() as session:
            stored_account = await session.get(GmailSyncAccount, account.id)
            stored_account.blocked_reason = "history_cursor_expired"
            stored_account.reseed_history_id = "999"
            await session.commit()

    class _ThreadDriftAdapter:
        provider_calls = 0
        metadata_calls: list[tuple[str, str]] = []

        def _ref(self):
            thread_id = "thread-a" if self.provider_calls == 1 else "thread-b"
            return GmailHistoryMessageRef("gone-message", thread_id)

        async def list_history(self, **_kwargs):
            self.provider_calls += 1
            return GmailHistoryPage(
                history_id="701",
                messages=(self._ref(),),
                next_page_token=None,
                discovered_history_id_min="701",
                discovered_history_id_max="701",
            )

        async def list_messages_for_backfill(self, **_kwargs):
            self.provider_calls += 1
            return GmailMessageListPage(
                messages=(self._ref(),),
                next_page_token=None,
            )

        async def get_message_metadata(self, *, message_id, **_kwargs):
            thread_id = "thread-a" if len(self.metadata_calls) == 0 else "thread-b"
            self.metadata_calls.append((message_id, thread_id))
            raise GmailProviderFailure("message_not_found")

    adapter = _ThreadDriftAdapter()
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    request = None
    if run_kind == "backfill":
        start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
        request = await service.create_backfill_request(
            account_id=account.id,
            administrator_id=admin_id,
            reason="Prove an acknowledgement cannot waive thread drift.",
            window_start=start,
            window_end=start + timedelta(days=1),
            audit_id=audit_id,
        )

    async def execute() -> None:
        if request is None:
            await service.sync_account(account.id)
        else:
            await service.run_backfill(request.id)

    with pytest.raises(GmailAccountBlocked, match="^message_not_found$"):
        await execute()
    async with sessionmaker() as session:
        first_incident = await session.scalar(
            sa.select(GmailMissingMessageIncident).where(
                GmailMissingMessageIncident.account_id == account.id,
                GmailMissingMessageIncident.gmail_thread_id == "thread-a",
            )
        )
        run = await session.scalar(
            sa.select(GmailSyncRun).where(GmailSyncRun.account_id == account.id)
        )
    assert first_incident is not None
    assert run is not None

    call = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(
            path="/api/v1/agent-control/gmail/missing-message/acknowledge"
        ),
    )
    async with sessionmaker() as session:
        await acknowledge_missing_message_incident(
            session,
            request=call,
            administrator_id=admin_id,
            incident_id=first_incident.id,
            account_id=account.id,
            run_id=run.id,
            gmail_message_id="gone-message",
            gmail_thread_id="thread-a",
            expected_start_history_id="700",
            expected_page_number=1,
            expected_request_page_token=None,
            expected_version=1,
            reason="Acknowledge only the exact message and thread evidence.",
            backfill_request_id=(request.id if request is not None else None),
            expected_reseed_history_id=("999" if request is not None else None),
        )
        await session.commit()

    with pytest.raises(GmailAccountBlocked, match="^message_not_found$"):
        await execute()

    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        incidents = list(
            (
                await session.scalars(
                    sa.select(GmailMissingMessageIncident)
                    .where(GmailMissingMessageIncident.account_id == account.id)
                    .order_by(GmailMissingMessageIncident.created_at)
                )
            ).all()
        )
        stored_request = (
            await session.get(GmailBackfillRequest, request.id)
            if request is not None
            else None
        )
    assert stored_account.committed_history_id == "700"
    assert [row.gmail_thread_id for row in incidents] == ["thread-a", "thread-b"]
    assert [row.state for row in incidents] == ["acknowledged", "pending"]
    assert adapter.metadata_calls == [
        ("gone-message", "thread-a"),
        ("gone-message", "thread-b"),
    ]
    assert len(alerts) == 2
    assert alerts[0]["dedupe_key"] != alerts[1]["dedupe_key"]
    if stored_request is not None:
        assert stored_request.state == "running"


async def test_two_missing_messages_on_one_page_each_alert_and_resume_once(
    recovery_runtime,
) -> None:
    from types import SimpleNamespace

    from models.gmail_task_intake import (
        GmailMissingMessageIncident,
        GmailSyncAccount,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import (
        GmailHistoryMessageRef,
        GmailHistoryPage,
        GmailProviderFailure,
    )
    from services.gmail_history_service import (
        GmailAccountBlocked,
        GmailHistoryService,
        acknowledge_missing_message_incident,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, _audit_id = await _seed_admin_and_audit(sessionmaker)

    class _TwoDeletedMessagesAdapter:
        list_calls = 0
        metadata_calls: list[str] = []

        async def list_history(self, **_kwargs):
            self.list_calls += 1
            return GmailHistoryPage(
                history_id="701",
                messages=(
                    GmailHistoryMessageRef("gone-one", "thread-one"),
                    GmailHistoryMessageRef("gone-two", "thread-two"),
                ),
                next_page_token=None,
                discovered_history_id_min="701",
                discovered_history_id_max="701",
            )

        async def get_message_metadata(self, *, message_id, **_kwargs):
            self.metadata_calls.append(message_id)
            raise GmailProviderFailure("message_not_found")

    adapter = _TwoDeletedMessagesAdapter()
    alerts: list[dict[str, str]] = []

    async def alert_sink(**event):
        alerts.append(event)

    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    call = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(
            path="/api/v1/agent-control/gmail/missing-message/acknowledge"
        ),
    )

    async def acknowledge_pending() -> None:
        async with sessionmaker() as session:
            incident = await session.scalar(
                sa.select(GmailMissingMessageIncident)
                .where(
                    GmailMissingMessageIncident.account_id == account.id,
                    GmailMissingMessageIncident.state == "pending",
                )
                .order_by(GmailMissingMessageIncident.created_at)
            )
            run = await session.scalar(
                sa.select(GmailSyncRun).where(
                    GmailSyncRun.account_id == account.id,
                    GmailSyncRun.state == "running",
                )
            )
            assert incident is not None
            assert run is not None
            await acknowledge_missing_message_incident(
                session,
                request=call,
                administrator_id=admin_id,
                incident_id=incident.id,
                account_id=account.id,
                run_id=run.id,
                gmail_message_id=incident.gmail_message_id,
                gmail_thread_id=incident.gmail_thread_id,
                expected_start_history_id="700",
                expected_page_number=1,
                expected_request_page_token=None,
                expected_version=1,
                reason="Acknowledge this exact provider-confirmed deletion.",
            )
            await session.commit()

    with pytest.raises(GmailAccountBlocked, match="^message_not_found$"):
        await service.sync_account(account.id)
    await acknowledge_pending()
    with pytest.raises(GmailAccountBlocked, match="^message_not_found$"):
        await service.sync_account(account.id)
    await acknowledge_pending()
    result = await service.sync_account(account.id)

    assert result.committed_history_id == "701"
    assert adapter.list_calls == 3
    assert adapter.metadata_calls == ["gone-one", "gone-two"]
    assert len(alerts) == 2
    assert alerts[0]["incident_id"] != alerts[1]["incident_id"]
    assert alerts[0]["dedupe_key"] != alerts[1]["dedupe_key"]
    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        incidents = list(
            (
                await session.scalars(
                    sa.select(GmailMissingMessageIncident)
                    .where(GmailMissingMessageIncident.account_id == account.id)
                    .order_by(GmailMissingMessageIncident.gmail_message_id)
                )
            ).all()
        )
    assert stored_account.committed_history_id == "701"
    assert stored_account.blocked_reason is None
    assert [row.gmail_message_id for row in incidents] == ["gone-one", "gone-two"]
    assert [row.state for row in incidents] == ["acknowledged", "acknowledged"]


@pytest.mark.parametrize("run_kind", ["poll", "backfill"])
async def test_pending_incident_alert_retries_before_affinity_or_provider_work(
    recovery_runtime,
    run_kind: str,
) -> None:
    from models.gmail_task_intake import (
        GmailMissingMessageIncident,
        GmailSyncAccount,
    )
    from services.gmail_history_adapter import (
        GmailHistoryMessageRef,
        GmailHistoryPage,
        GmailMessageListPage,
        GmailProviderFailure,
    )
    from services.gmail_history_service import GmailAccountBlocked, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    if run_kind == "backfill":
        async with sessionmaker() as session:
            stored_account = await session.get(GmailSyncAccount, account.id)
            stored_account.blocked_reason = "history_cursor_expired"
            stored_account.reseed_history_id = "999"
            await session.commit()

    class _DeletedMessageAdapter:
        provider_calls = 0
        metadata_calls = 0

        async def list_history(self, **_kwargs):
            self.provider_calls += 1
            return GmailHistoryPage(
                history_id="701",
                messages=(GmailHistoryMessageRef("gone", "gone-thread"),),
                next_page_token=None,
                discovered_history_id_min="701",
                discovered_history_id_max="701",
            )

        async def list_messages_for_backfill(self, **_kwargs):
            self.provider_calls += 1
            return GmailMessageListPage(
                messages=(GmailHistoryMessageRef("gone", "gone-thread"),),
                next_page_token=None,
            )

        async def get_message_metadata(self, **_kwargs):
            self.metadata_calls += 1
            raise GmailProviderFailure("message_not_found")

    adapter = _DeletedMessageAdapter()
    alert_attempts = 0
    delivered_alerts: list[dict[str, str]] = []

    async def fail_once_alert_sink(**event):
        nonlocal alert_attempts
        alert_attempts += 1
        if alert_attempts == 1:
            raise RuntimeError("test alert sink failure")
        delivered_alerts.append(event)

    first = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=fail_once_alert_sink,
    )
    request = None
    if run_kind == "backfill":
        start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
        request = await first.create_backfill_request(
            account_id=account.id,
            administrator_id=admin_id,
            reason="Prove pending incident alert recovery precedes provider work.",
            window_start=start,
            window_end=start + timedelta(days=1),
            audit_id=audit_id,
        )
    with pytest.raises(
        RuntimeError,
        match="^gmail_history_alert_enqueue_failed$",
    ):
        if request is None:
            await first.sync_account(account.id)
        else:
            await first.run_backfill(request.id)

    async with sessionmaker() as session:
        incident = await session.scalar(
            sa.select(GmailMissingMessageIncident).where(
                GmailMissingMessageIncident.account_id == account.id
            )
        )
    assert incident is not None
    assert incident.state == "pending"
    assert incident.alert_state == "pending"

    affinity_calls = 0

    async def forbidden_pid_reader(_connection):
        nonlocal affinity_calls
        affinity_calls += 1
        raise AssertionError("pending incident must block before affinity probing")

    reconstructed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=fail_once_alert_sink,
        backend_pid_reader=forbidden_pid_reader,
    )
    with pytest.raises(GmailAccountBlocked, match="^message_not_found$"):
        await reconstructed.sync_account(account.id)
    assert alert_attempts == 2
    assert len(delivered_alerts) == 1
    assert delivered_alerts[0]["incident_id"] == str(incident.id)
    assert affinity_calls == 0
    assert adapter.provider_calls == 1
    assert adapter.metadata_calls == 1

    restarted_again = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=fail_once_alert_sink,
        backend_pid_reader=forbidden_pid_reader,
    )
    with pytest.raises(GmailAccountBlocked, match="^message_not_found$"):
        if request is None:
            await restarted_again.sync_account(account.id)
        else:
            await restarted_again.run_backfill(request.id)
    assert alert_attempts == 2
    assert len(delivered_alerts) == 1
    assert affinity_calls == 0
    assert adapter.provider_calls == 1
    async with sessionmaker() as session:
        stored_incident = await session.get(
            GmailMissingMessageIncident,
            incident.id,
        )
    assert stored_incident.alert_state == "sent"
    assert stored_incident.alerted_at is not None


@pytest.mark.parametrize("run_kind", ["poll", "backfill"])
async def test_incident_created_after_preflight_survives_initial_affinity_loss(
    recovery_runtime,
    run_kind: str,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailMissingMessageIncident,
        GmailSyncAccount,
        GmailSyncRun,
    )
    from services.gmail_history_service import (
        GmailAccountBlocked,
        GmailHistoryService,
        GmailMissingMessageDetected,
    )
    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)

    class _NeverCalledAdapter:
        calls = 0

        async def list_history(self, **_kwargs):
            self.calls += 1
            raise AssertionError("incident must win before provider work")

        async def list_messages_for_backfill(self, **_kwargs):
            self.calls += 1
            raise AssertionError("incident must win before provider work")

    async def alert_sink(**_event):
        return None

    adapter = _NeverCalledAdapter()
    setup = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
    )
    request = None
    if run_kind == "backfill":
        async with sessionmaker() as session:
            stored = await session.get(GmailSyncAccount, account.id)
            stored.blocked_reason = "history_cursor_expired"
            stored.reseed_history_id = "999"
            await session.commit()
        start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
        request = await setup.create_backfill_request(
            account_id=account.id,
            administrator_id=admin_id,
            reason="Preserve the exact pending incident during affinity loss.",
            window_start=start,
            window_end=start + timedelta(days=1),
            audit_id=audit_id,
        )
    async with sessionmaker() as session:
        run = GmailSyncRun(
            account_id=account.id,
            start_history_id="700",
            next_page_token=None,
            run_kind=run_kind,
            state="running",
        )
        session.add(run)
        await session.flush()
        run_id = run.id
        if request is not None:
            stored_request = await session.get(GmailBackfillRequest, request.id)
            stored_request.run_id = run_id
            stored_request.state = "running"
            stored_request.started_at = datetime.now(tz=UTC)
        await session.commit()

    async def before_pid(_connection):
        return 64001

    async def drifted_probe(_connection, _account_id):
        return 64002, True

    first = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=alert_sink,
        backend_pid_reader=before_pid,
        post_lock_probe=drifted_probe,
    )
    original_preflight = first._block_on_pending_incident_before_history

    async def preflight_then_second_worker_incident(**kwargs):
        await original_preflight(**kwargs)
        second_connection = await engine.connect()
        try:
            assert await try_session_advisory_lock(second_connection, account.id)
            await setup._block_missing_message(
                second_connection,
                account_id=account.id,
                run_id=run_id,
                missing=GmailMissingMessageDetected(
                    message_id="between-preflight-message",
                    thread_id="between-preflight-thread",
                ),
                start_history_id="700",
                page_number=1,
                request_page_token=None,
                backfill_request_id=(request.id if request is not None else None),
            )
            assert await release_session_advisory_lock(
                second_connection,
                account.id,
            )
            await second_connection.commit()
        finally:
            await second_connection.close()

    first._block_on_pending_incident_before_history = (
        preflight_then_second_worker_incident
    )
    with pytest.raises(GmailAccountBlocked, match="^message_not_found$"):
        if request is None:
            await first.sync_account(account.id)
        else:
            await first.run_backfill(request.id)

    assert adapter.calls == 0
    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        stored_run = await session.get(GmailSyncRun, run_id)
        stored_request = (
            await session.get(GmailBackfillRequest, request.id)
            if request is not None
            else None
        )
        incident = await session.scalar(
            sa.select(GmailMissingMessageIncident).where(
                GmailMissingMessageIncident.account_id == account.id,
                GmailMissingMessageIncident.run_id == run_id,
            )
        )
    assert stored_account.blocked_reason == (
        "history_cursor_expired" if request is not None else "message_not_found"
    )
    assert stored_run.state == "running"
    assert stored_run.failure_category == "message_not_found"
    assert incident is not None
    assert incident.state == "pending"
    assert incident.alert_state == "sent"
    if stored_request is not None:
        assert stored_request.state == "running"
        assert stored_request.result_category == "message_not_found"


@pytest.mark.parametrize("with_incident", [False, True])
async def test_missing_alert_sink_never_marks_recovery_notification_sent(
    recovery_runtime,
    with_incident: bool,
) -> None:
    from models.gmail_task_intake import (
        GmailMissingMessageIncident,
        GmailSyncAccount,
        GmailSyncRun,
    )
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    incident_id = None
    event = "max_pages"
    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        if with_incident:
            event = "message_not_found"
            stored_account.blocked_reason = event
            run = GmailSyncRun(
                account_id=account.id,
                start_history_id="700",
                run_kind="poll",
                state="running",
            )
            session.add(run)
            await session.flush()
            incident = GmailMissingMessageIncident(
                account_id=account.id,
                run_id=run.id,
                gmail_message_id="missing-alert-message",
                gmail_thread_id="missing-alert-thread",
                start_history_id="700",
                page_number=1,
            )
            session.add(incident)
            await session.flush()
            incident_id = incident.id
        else:
            stored_account.blocked_reason = event
        await session.commit()

    service = GmailHistoryService(
        engine=engine,
        adapter=object(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        alert_sink=None,
    )
    for _attempt in range(2):
        with pytest.raises(
            RuntimeError,
            match="^gmail_history_alert_enqueue_failed$",
        ) as raised:
            await service._enqueue_expiry_alert(
                None,
                account_id=account.id,
                event=event,
                incident_id=incident_id,
            )
        assert raised.value.__suppress_context__ is True

    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        stored_incident = (
            await session.get(GmailMissingMessageIncident, incident_id)
            if incident_id is not None
            else None
        )
    assert stored_account.blocked_reason == event
    assert stored_account.last_error_category == f"{event}_alert_pending"
    if stored_incident is not None:
        assert stored_incident.state == "pending"
        assert stored_incident.alert_state == "pending"
        assert stored_incident.alerted_at is None


async def test_backfill_request_requires_authenticated_reason_and_seven_day_bound(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from services.gmail_history_service import GmailBackfillValidationError, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    service = GmailHistoryService(
        engine=engine,
        adapter=_ExpiredAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    start = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

    invalid_cases = [
        {"administrator_id": None, "reason": "Recover requested mail", "window_end": start + timedelta(days=1)},
        {"administrator_id": admin_id, "reason": "", "window_end": start + timedelta(days=1)},
        {"administrator_id": admin_id, "reason": "   ", "window_end": start + timedelta(days=1)},
        {"administrator_id": admin_id, "reason": "x" * 501, "window_end": start + timedelta(days=1)},
        {"administrator_id": admin_id, "reason": "Recover requested mail", "window_end": start - timedelta(seconds=1)},
        {"administrator_id": admin_id, "reason": "Recover requested mail", "window_end": start},
        {"administrator_id": admin_id, "reason": "Recover requested mail", "window_end": start + timedelta(days=7, seconds=1)},
    ]
    for case in invalid_cases:
        with pytest.raises(GmailBackfillValidationError):
            await service.create_backfill_request(
                account_id=account.id,
                administrator_id=case["administrator_id"],
                reason=case["reason"],
                window_start=start,
                window_end=case["window_end"],
                audit_id=audit_id,
            )

    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Recover the bounded missed-mail window.",
        window_start=start,
        window_end=start + timedelta(days=7),
        audit_id=audit_id,
    )
    assert request.state == "requested"
    assert request.expired_history_id == "700"
    assert request.reseed_history_id == "999"

    with pytest.raises(GmailBackfillValidationError, match="active_backfill_exists"):
        await service.create_backfill_request(
            account_id=account.id,
            administrator_id=admin_id,
            reason="A competing recovery must not be admitted.",
            window_start=start,
            window_end=start + timedelta(days=1),
            audit_id=audit_id,
        )


@pytest.mark.parametrize(
    ("expired_history_id", "reseed_history_id"),
    [("bad-expired", "999"), ("700", "bad-reseed"), ("999", "700")],
)
async def test_backfill_rejects_invalid_persisted_cursor_snapshot_before_provider(
    recovery_runtime,
    expired_history_id: str,
    reseed_history_id: str,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount, GmailSyncRun
    from services.gmail_history_service import GmailBackfillValidationError, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor=expired_history_id)
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = reseed_history_id
        await session.commit()

    provider_calls = 0

    class _ForbiddenAdapter:
        async def list_messages_for_backfill(self, **_kwargs):
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("invalid snapshot must fail before provider")

    service = GmailHistoryService(
        engine=engine,
        adapter=_ForbiddenAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    with pytest.raises(
        GmailBackfillValidationError,
        match="^gmail_backfill_snapshot_invalid$",
    ):
        await service.create_backfill_request(
            account_id=account.id,
            administrator_id=admin_id,
            reason="Reject a corrupt local cursor snapshot.",
            window_start=start,
            window_end=start + timedelta(days=1),
            audit_id=audit_id,
        )
    assert provider_calls == 0
    async with sessionmaker() as session:
        run_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncRun).where(
                GmailSyncRun.account_id == account.id
            )
        )
    assert run_count == 0


async def test_admitted_backfill_revalidates_cursor_snapshot_before_execution(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailSyncAccount,
        GmailSyncRun,
    )
    from services.gmail_history_service import GmailBackfillValidationError, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()

    provider_calls = 0

    class _ForbiddenAdapter:
        async def list_messages_for_backfill(self, **_kwargs):
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("corrupt admitted snapshot must not call provider")

    service = GmailHistoryService(
        engine=engine,
        adapter=_ForbiddenAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Admit one valid bounded recovery request.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        stored_request = await session.get(GmailBackfillRequest, request.id)
        stored_account.reseed_history_id = "bad-reseed"
        stored_request.reseed_history_id = "bad-reseed"
        await session.commit()

    with pytest.raises(
        GmailBackfillValidationError,
        match="^gmail_backfill_snapshot_changed$",
    ):
        await service.run_backfill(request.id)
    assert provider_calls == 0
    async with sessionmaker() as session:
        run_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncRun).where(
                GmailSyncRun.account_id == account.id
            )
        )
    assert run_count == 0


async def test_two_sessions_admit_only_one_active_backfill_request(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import GmailBackfillRequest, GmailSyncAccount
    from services.gmail_history_service import (
        GmailBackfillValidationError,
        GmailHistoryService,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()

    ready = asyncio.Event()
    release = asyncio.Event()
    mutex = asyncio.Lock()
    arrived = 0

    async def before_backfill_admission():
        nonlocal arrived
        async with mutex:
            arrived += 1
            if arrived == 2:
                ready.set()
        await release.wait()

    services = [
        GmailHistoryService(
            engine=engine,
            adapter=_ExpiredAdapter(email_address=account.workspace_email),
            participant_hash_key=b"test-participant-key-with-32-bytes",
            before_backfill_admission=before_backfill_admission,
        )
        for _ in range(2)
    ]
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    tasks = [
        asyncio.create_task(
            service.create_backfill_request(
                account_id=account.id,
                administrator_id=admin_id,
                reason="Concurrent bounded recovery.",
                window_start=start,
                window_end=start + timedelta(days=1),
                audit_id=audit_id,
            )
        )
        for service in services
    ]
    await asyncio.wait_for(ready.wait(), timeout=2)
    release.set()
    results = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=True), timeout=3
    )
    successes = [item for item in results if isinstance(item, GmailBackfillRequest)]
    failures = [
        item for item in results if isinstance(item, GmailBackfillValidationError)
    ]
    assert len(successes) == 1
    assert len(failures) == 1
    assert str(failures[0]) == "active_backfill_exists"
    async with sessionmaker() as session:
        count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailBackfillRequest).where(
                GmailBackfillRequest.account_id == account.id,
                GmailBackfillRequest.state.in_(("requested", "running")),
            )
        )
    assert count == 1


async def test_backfill_promotion_serializes_against_new_request_admission(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_service import GmailBackfillValidationError, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()

    base = GmailHistoryService(
        engine=engine,
        adapter=_ExpiredAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    completed_request = await base.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Complete the first authenticated recovery.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    async with sessionmaker() as session:
        run = GmailSyncRun(
            account_id=account.id,
            start_history_id="700",
            terminal_history_id="999",
            next_page_token=None,
            run_kind="backfill",
            state="completed",
        )
        session.add(run)
        await session.flush()
        session.add(
            GmailSyncPageCheckpoint(
                run_id=run.id,
                page_number=1,
                request_page_token=None,
                next_page_token=None,
                receipt_count=0,
            )
        )
        stored_request = await session.get(
            GmailBackfillRequest,
            completed_request.id,
        )
        stored_request.run_id = run.id
        stored_request.state = "running"
        await session.commit()

    admission_paused = asyncio.Event()
    release_admission = asyncio.Event()

    async def before_backfill_admission() -> None:
        admission_paused.set()
        await release_admission.wait()

    admitting = GmailHistoryService(
        engine=engine,
        adapter=_ExpiredAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        before_backfill_admission=before_backfill_admission,
    )
    new_request_task = asyncio.create_task(
        admitting.create_backfill_request(
            account_id=account.id,
            administrator_id=admin_id,
            reason="A stale admission must not survive completed recovery.",
            window_start=start,
            window_end=start + timedelta(days=1),
            audit_id=audit_id,
        )
    )
    try:
        await asyncio.wait_for(admission_paused.wait(), timeout=2)
        promoted = await asyncio.wait_for(
            base.promote_reseed_after_backfill(completed_request.id),
            timeout=2,
        )
        assert promoted.committed_history_id == "999"
        release_admission.set()
        with pytest.raises(
            GmailBackfillValidationError,
            match="^gmail_backfill_not_available$",
        ):
            await asyncio.wait_for(new_request_task, timeout=2)
    finally:
        release_admission.set()
        if not new_request_task.done():
            new_request_task.cancel()
            await asyncio.gather(new_request_task, return_exceptions=True)

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        active_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailBackfillRequest).where(
                GmailBackfillRequest.account_id == account.id,
                GmailBackfillRequest.state.in_(("requested", "running")),
            )
        )
        old_request = await session.get(
            GmailBackfillRequest,
            completed_request.id,
        )
    assert stored.committed_history_id == "999"
    assert stored.reseed_history_id is None
    assert stored.blocked_reason is None
    assert old_request.state == "completed"
    assert active_count == 0


async def test_bounded_messages_list_backfill_persists_pages_then_promotes_snapshot(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import (
        GmailHistoryMessageRef,
        GmailMessageListPage,
        GmailMessageMetadata,
    )
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()

    start = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    end = start + timedelta(days=3)
    calls: list[tuple] = []
    content_calls: list[str] = []

    class _BackfillAdapter:
        async def list_messages_for_backfill(
            self, *, account_key, window_start, window_end, page_token
        ):
            calls.append(
                ("list", account_key, window_start, window_end, page_token)
            )
            if page_token is None:
                return GmailMessageListPage(
                    messages=(
                        GmailHistoryMessageRef(
                            message_id="backfill-at-start",
                            thread_id="backfill-thread-at-start",
                        ),
                        GmailHistoryMessageRef(
                            message_id="backfill-before-start",
                            thread_id="backfill-thread-before-start",
                        ),
                        GmailHistoryMessageRef(
                            message_id="backfill-at-end",
                            thread_id="backfill-thread-at-end",
                        ),
                        GmailHistoryMessageRef(
                            message_id="backfill-message-1",
                            thread_id="backfill-thread-1",
                        ),
                        GmailHistoryMessageRef(
                            message_id="backfill-message-2",
                            thread_id="backfill-thread-2",
                        ),
                    ),
                    next_page_token="backfill-page-2",
                )
            assert page_token == "backfill-page-2"
            return GmailMessageListPage(
                messages=(
                    GmailHistoryMessageRef(
                        message_id="backfill-message-2",
                        thread_id="backfill-thread-2",
                    ),
                    GmailHistoryMessageRef(
                        message_id="backfill-message-3",
                        thread_id="backfill-thread-3",
                    ),
                ),
                next_page_token=None,
            )

        async def get_message_metadata(self, *, account_key, message_id):
            calls.append(("metadata", account_key, message_id))
            boundary_times = {
                "backfill-at-start": start,
                "backfill-before-start": start - timedelta(microseconds=1),
                "backfill-at-end": end,
            }
            if message_id in boundary_times:
                out_of_window = message_id in {
                    "backfill-before-start",
                    "backfill-at-end",
                }
                return GmailMessageMetadata(
                    message_id=message_id,
                    thread_id=message_id.replace("backfill-", "backfill-thread-"),
                    label_ids=(("SENT",) if out_of_window else ("INBOX",)),
                    message_at=boundary_times[message_id],
                    headers={
                        "subject": "Backfill boundary",
                        "from": (
                            account.workspace_email
                            if out_of_window
                            else "boundary-client@example.test"
                        ),
                        "to": (
                            "boundary-client@example.test"
                            if out_of_window
                            else account.workspace_email
                        ),
                    },
                )
            index = int(message_id.rsplit("-", 1)[1])
            return GmailMessageMetadata(
                message_id=message_id,
                thread_id=f"backfill-thread-{index}",
                label_ids=("INBOX",),
                message_at=start + timedelta(hours=index),
                headers={
                    "subject": f"Backfill {index}",
                    "from": f"client-{index}@example.test",
                    "to": account.workspace_email,
                },
            )

        async def get_message_content(self, *, account_key, message_id):
            content_calls.append(message_id)
            raise AssertionError(
                "out-of-window backfill metadata must be filtered before body fetch"
            )

    service = GmailHistoryService(
        engine=engine,
        adapter=_BackfillAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=3,
        # A non-null observer would hydrate eligible SENT evidence. The only
        # SENT rows in this fixture are outside the exact authorized window.
        origin_observer=object(),
    )
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Execute a bounded messages-list recovery.",
        window_start=start,
        window_end=end,
        audit_id=audit_id,
    )
    executed = await service.run_backfill(request.id)

    assert executed.pages_committed == 2
    assert calls[0] == ("list", str(account.id), start, end, None)
    assert ("list", str(account.id), start, end, "backfill-page-2") in calls
    assert not any(call[0] == "history" for call in calls)
    assert content_calls == []
    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        stored_request = await session.get(GmailBackfillRequest, request.id)
        run = await session.get(GmailSyncRun, stored_request.run_id)
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
    assert stored_account.committed_history_id == "700"
    assert stored_account.blocked_reason == "history_cursor_expired"
    assert stored_request.state == "running"
    assert run.run_kind == "backfill"
    assert run.start_history_id == "700"
    assert run.state == "completed"
    assert run.terminal_history_id == "999"
    assert run.next_page_token is None
    assert [row.next_page_token for row in checkpoints] == [
        "backfill-page-2",
        None,
    ]
    assert [row.gmail_message_id for row in receipts] == [
        "backfill-at-start",
        "backfill-message-1",
        "backfill-message-2",
        "backfill-message-3",
    ]

    promoted = await service.promote_reseed_after_backfill(request.id)
    assert promoted.committed_history_id == "999"
    assert promoted.blocked_reason is None


@pytest.mark.parametrize(
    "fatal_category",
    ["malformed_provider", "oauth_revoked"],
)
async def test_fatal_backfill_message_failure_terminalizes_run_and_allows_new_request(
    recovery_runtime,
    fatal_category: str,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailSyncAccount,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import (
        GmailHistoryMessageRef,
        GmailMessageListPage,
        GmailProviderFailure,
    )
    from services.gmail_history_service import (
        GmailBackfillValidationError,
        GmailHistoryService,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()

    class _FatalMetadataAdapter:
        list_calls = 0
        metadata_calls = 0

        async def list_messages_for_backfill(self, **_kwargs):
            self.list_calls += 1
            return GmailMessageListPage(
                messages=(
                    GmailHistoryMessageRef(
                        message_id="fatal-backfill-message",
                        thread_id="fatal-backfill-thread",
                    ),
                ),
                next_page_token=None,
            )

        async def get_message_metadata(self, **_kwargs):
            self.metadata_calls += 1
            raise GmailProviderFailure(fatal_category)

    adapter = _FatalMetadataAdapter()
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Terminalize a definite backfill provider failure.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    with pytest.raises(GmailProviderFailure, match=f"^{fatal_category}$"):
        await service.run_backfill(request.id)

    assert adapter.list_calls == 1
    assert adapter.metadata_calls == 1
    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        stored_request = await session.get(GmailBackfillRequest, request.id)
        run = await session.get(GmailSyncRun, stored_request.run_id)
    assert stored_account.committed_history_id == "700"
    assert stored_account.reseed_history_id == "999"
    assert stored_account.blocked_reason == (
        "oauth_revoked"
        if fatal_category == "oauth_revoked"
        else "history_cursor_expired"
    )
    assert stored_request.state == "failed"
    assert stored_request.result_category == fatal_category
    assert run.state == "failed"
    assert run.failure_category == fatal_category

    if fatal_category == "oauth_revoked":
        with pytest.raises(
            GmailBackfillValidationError,
            match="^gmail_backfill_snapshot_changed$",
        ):
            await service.run_backfill(request.id)
        assert adapter.list_calls == 1
        assert adapter.metadata_calls == 1
        async with sessionmaker() as session:
            reconnected = await session.get(GmailSyncAccount, account.id)
            reconnected.blocked_reason = "history_cursor_expired"
            reconnected.last_error_category = None
            reconnected.last_error_message = None
            await session.commit()

    later = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="A later authenticated recovery remains possible.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    assert later.state == "requested"
    assert later.id != request.id


async def test_backfill_crash_resumes_from_committed_messages_list_page(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import (
        GmailHistoryMessageRef,
        GmailMessageListPage,
        GmailMessageMetadata,
    )
    from services.gmail_history_service import GmailHistoryService
    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()
    start = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    end = start + timedelta(days=2)

    def page(message_id: str, next_token: str | None):
        return GmailMessageListPage(
            messages=(
                GmailHistoryMessageRef(
                    message_id=message_id,
                    thread_id=f"thread-{message_id}",
                ),
            ),
            next_page_token=next_token,
        )

    def metadata(message_id: str):
        return GmailMessageMetadata(
            message_id=message_id,
            thread_id=f"thread-{message_id}",
            label_ids=("INBOX",),
            message_at=start + timedelta(hours=1),
            headers={
                "subject": message_id,
                "from": "client@example.test",
                "to": account.workspace_email,
            },
        )

    class _CrashingBackfillAdapter:
        calls: list[str | None] = []

        async def list_messages_for_backfill(self, *, page_token, **_kwargs):
            self.calls.append(page_token)
            if page_token is None:
                return page("resume-message-1", "resume-page-2")
            raise RuntimeError("synthetic backfill crash")

        async def get_message_metadata(self, *, message_id, **_kwargs):
            return metadata(message_id)

    crashing_adapter = _CrashingBackfillAdapter()
    service = GmailHistoryService(
        engine=engine,
        adapter=crashing_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Crash-resumable bounded recovery.",
        window_start=start,
        window_end=end,
        audit_id=audit_id,
    )
    verifier = await engine.connect()
    try:
        with pytest.raises(RuntimeError, match="synthetic backfill crash"):
            await service.run_backfill(request.id)
        assert await try_session_advisory_lock(verifier, account.id)
        assert await release_session_advisory_lock(verifier, account.id)
        await verifier.commit()
    finally:
        await verifier.close()

    async with sessionmaker() as session:
        stored_request = await session.get(GmailBackfillRequest, request.id)
        run = await session.get(GmailSyncRun, stored_request.run_id)
        first_receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt).where(
                        GmailMessageReceipt.account_id == account.id
                    )
                )
            ).all()
        )
        first_checkpoints = list(
            (
                await session.scalars(
                    sa.select(GmailSyncPageCheckpoint).where(
                        GmailSyncPageCheckpoint.run_id == run.id
                    )
                )
            ).all()
        )
    assert stored_request.state == "running"
    assert run.state == "running"
    assert run.next_page_token == "resume-page-2"
    assert [row.gmail_message_id for row in first_receipts] == [
        "resume-message-1"
    ]
    assert len(first_checkpoints) == 1

    class _ResumeBackfillAdapter:
        calls: list[str | None] = []

        async def list_messages_for_backfill(self, *, page_token, **_kwargs):
            self.calls.append(page_token)
            assert page_token == "resume-page-2"
            return page("resume-message-2", None)

        async def get_message_metadata(self, *, message_id, **_kwargs):
            return metadata(message_id)

    resume_adapter = _ResumeBackfillAdapter()
    resumed = GmailHistoryService(
        engine=engine,
        adapter=resume_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    await resumed.run_backfill(request.id)
    await resumed.promote_reseed_after_backfill(request.id)

    assert crashing_adapter.calls == [None, "resume-page-2"]
    assert resume_adapter.calls == ["resume-page-2"]
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        receipts = list(
            (
                await session.scalars(
                    sa.select(GmailMessageReceipt)
                    .where(GmailMessageReceipt.account_id == account.id)
                    .order_by(GmailMessageReceipt.gmail_message_id)
                )
            ).all()
        )
    assert stored.committed_history_id == "999"
    assert [row.gmail_message_id for row in receipts] == [
        "resume-message-1",
        "resume-message-2",
    ]


async def test_resumed_backfill_enforces_max_pages_across_durable_checkpoints(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import GmailMessageListPage
    from services.gmail_history_service import GmailHistoryService, GmailPaginationGuard

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()
    start = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)

    class _CrashAfterTwoPages:
        calls = 0

        async def list_messages_for_backfill(self, *, page_token, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                assert page_token is None
                return GmailMessageListPage(
                    messages=(), next_page_token="cumulative-backfill-2"
                )
            if self.calls == 2:
                assert page_token == "cumulative-backfill-2"
                return GmailMessageListPage(
                    messages=(), next_page_token="cumulative-backfill-3"
                )
            raise RuntimeError("synthetic backfill restart after two commits")

    first = GmailHistoryService(
        engine=engine,
        adapter=_CrashAfterTwoPages(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=10,
    )
    request = await first.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Cumulative checkpoint bound.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    with pytest.raises(RuntimeError, match="synthetic backfill restart"):
        await first.run_backfill(request.id)

    class _MustNotCallProvider:
        calls = 0

        async def list_messages_for_backfill(self, **_kwargs):
            self.calls += 1
            raise AssertionError("persisted max-page bound must run before provider")

    adapter = _MustNotCallProvider()
    resumed = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=2,
    )
    with pytest.raises(GmailPaginationGuard, match="gmail_backfill_max_pages"):
        await resumed.run_backfill(request.id)
    assert adapter.calls == 0

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored_request = await session.get(GmailBackfillRequest, request.id)
        run = await session.get(GmailSyncRun, stored_request.run_id)
        checkpoints = list(
            (
                await session.scalars(
                    sa.select(GmailSyncPageCheckpoint).where(
                        GmailSyncPageCheckpoint.run_id == run.id
                    )
                )
            ).all()
        )
    assert stored.committed_history_id == "700"
    assert stored_request.state == "failed"
    assert stored_request.result_category == "max_pages"
    assert len(checkpoints) == 2


async def test_terminal_backfill_page_commit_resumes_without_provider_recall(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailMessageReceipt,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import (
        GmailHistoryMessageRef,
        GmailMessageListPage,
        GmailMessageMetadata,
    )
    from services.gmail_history_service import GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

    class _TerminalAdapter:
        calls = 0

        async def list_messages_for_backfill(self, **_kwargs):
            self.calls += 1
            return GmailMessageListPage(
                messages=(
                    GmailHistoryMessageRef(
                        message_id="terminal-backfill-message",
                        thread_id="terminal-backfill-thread",
                    ),
                ),
                next_page_token=None,
            )

        async def get_message_metadata(self, **_kwargs):
            return GmailMessageMetadata(
                message_id="terminal-backfill-message",
                thread_id="terminal-backfill-thread",
                label_ids=("INBOX",),
                message_at=start + timedelta(hours=1),
                headers={
                    "subject": "Terminal committed evidence",
                    "from": "client@example.test",
                    "to": account.workspace_email,
                },
            )

    async def crash_after_terminal_commit():
        raise RuntimeError("synthetic crash after terminal backfill commit")

    adapter = _TerminalAdapter()
    first = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        after_terminal_page_commit=crash_after_terminal_commit,
    )
    request = await first.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Terminal checkpoint crash recovery.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    with pytest.raises(RuntimeError, match="terminal backfill commit"):
        await first.run_backfill(request.id)
    assert adapter.calls == 1

    async with sessionmaker() as session:
        stored_request = await session.get(GmailBackfillRequest, request.id)
        run = await session.get(GmailSyncRun, stored_request.run_id)
        receipt_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailMessageReceipt).where(
                GmailMessageReceipt.account_id == account.id
            )
        )
        checkpoint = await session.scalar(
            sa.select(GmailSyncPageCheckpoint).where(
                GmailSyncPageCheckpoint.run_id == run.id
            )
        )
    assert run.state == "completed"
    assert run.terminal_history_id == "999"
    assert checkpoint.next_page_token is None
    assert receipt_count == 1

    class _NoRecallAdapter:
        calls = 0

        async def list_messages_for_backfill(self, **_kwargs):
            self.calls += 1
            raise AssertionError("terminal evidence must resume without page-one recall")

    no_recall = _NoRecallAdapter()
    resumed = GmailHistoryService(
        engine=engine,
        adapter=no_recall,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=1,
    )
    await resumed.run_backfill(request.id)
    promoted = await resumed.promote_reseed_after_backfill(request.id)
    assert no_recall.calls == 0
    assert promoted.committed_history_id == "999"


@pytest.mark.parametrize("guard", ["repeated_token", "max_pages"])
async def test_backfill_pagination_guards_leave_expired_cursor_blocked(
    recovery_runtime,
    guard: str,
) -> None:
    from models.gmail_task_intake import GmailBackfillRequest, GmailSyncAccount
    from services.gmail_history_adapter import GmailMessageListPage
    from services.gmail_history_service import GmailHistoryService, GmailPaginationGuard

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(
        sessionmaker,
        cursor="700",
    )
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

    class _LoopingAdapter:
        calls = 0

        async def list_messages_for_backfill(self, *, page_token, **_kwargs):
            self.calls += 1
            if guard == "repeated_token":
                next_token = "repeat-token"
            else:
                next_token = f"page-{self.calls + 1}"
            return GmailMessageListPage(messages=(), next_page_token=next_token)

    adapter = _LoopingAdapter()
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        max_pages_per_run=1 if guard == "max_pages" else 4,
    )
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Guard the bounded recovery pagination.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    with pytest.raises(GmailPaginationGuard) as raised:
        await service.run_backfill(request.id)
    assert str(raised.value) == f"gmail_backfill_{guard}"
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored_request = await session.get(GmailBackfillRequest, request.id)
    assert stored.committed_history_id == "700"
    assert stored.blocked_reason == "history_cursor_expired"
    assert stored_request.state == "failed"
    assert stored_request.result_category == guard


async def test_backfill_execution_retains_account_lock_across_page_commits(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
    )
    from services.gmail_history_adapter import GmailMessageListPage
    from services.gmail_history_service import (
        GmailBackfillExecutionBusy,
        GmailHistoryService,
    )
    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    other = await _seed_account(sessionmaker, cursor="800")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        for row, reseed in (
            (account, "999"),
            (other, "1099"),
        ):
            stored = await session.get(GmailSyncAccount, row.id)
            stored.blocked_reason = "history_cursor_expired"
            stored.reseed_history_id = reseed
        await session.commit()
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    request_service = GmailHistoryService(
        engine=engine,
        adapter=object(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    main_request = await request_service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Retained-lock main recovery.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    other_request = await request_service.create_backfill_request(
        account_id=other.id,
        administrator_id=admin_id,
        reason="Independent-account recovery.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )

    second_page_entered = asyncio.Event()
    release_second_page = asyncio.Event()

    class _MainAdapter:
        calls: list[str | None] = []

        async def list_messages_for_backfill(self, *, page_token, **_kwargs):
            self.calls.append(page_token)
            if page_token is None:
                return GmailMessageListPage(
                    messages=(), next_page_token="lock-page-2"
                )
            second_page_entered.set()
            await release_second_page.wait()
            return GmailMessageListPage(messages=(), next_page_token=None)

    class _ForbiddenCompetitorAdapter:
        calls = 0

        async def list_messages_for_backfill(self, **_kwargs):
            self.calls += 1
            raise AssertionError("same-request contender must not call provider")

    class _OtherAdapter:
        calls = 0

        async def list_messages_for_backfill(self, **_kwargs):
            self.calls += 1
            return GmailMessageListPage(messages=(), next_page_token=None)

    main_adapter = _MainAdapter()
    competitor_adapter = _ForbiddenCompetitorAdapter()
    other_adapter = _OtherAdapter()
    main_service = GmailHistoryService(
        engine=engine,
        adapter=main_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    competitor_service = GmailHistoryService(
        engine=engine,
        adapter=competitor_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    other_service = GmailHistoryService(
        engine=engine,
        adapter=other_adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    verifier = await engine.connect()
    main_task = asyncio.create_task(main_service.run_backfill(main_request.id))
    try:
        await asyncio.wait_for(second_page_entered.wait(), timeout=2)
        async with sessionmaker() as session:
            stored_request = await session.get(GmailBackfillRequest, main_request.id)
            checkpoint_count = await session.scalar(
                sa.select(sa.func.count())
                .select_from(GmailSyncPageCheckpoint)
                .where(GmailSyncPageCheckpoint.run_id == stored_request.run_id)
            )
        assert checkpoint_count == 1
        assert not await try_session_advisory_lock(verifier, account.id)
        await verifier.commit()

        with pytest.raises(
            GmailBackfillExecutionBusy, match="^gmail_backfill_already_running$"
        ):
            await competitor_service.run_backfill(main_request.id)
        other_result = await asyncio.wait_for(
            other_service.run_backfill(other_request.id), timeout=1
        )
        assert other_result.pages_committed == 1

        release_second_page.set()
        main_result = await asyncio.wait_for(main_task, timeout=2)
        assert len(set(main_result.page_backend_pids)) == 1
        assert await try_session_advisory_lock(verifier, account.id)
        assert await release_session_advisory_lock(verifier, account.id)
        await verifier.commit()
    finally:
        release_second_page.set()
        if not main_task.done():
            main_task.cancel()
            await asyncio.gather(main_task, return_exceptions=True)
        await verifier.close()

    assert main_adapter.calls == [None, "lock-page-2"]
    assert competitor_adapter.calls == 0
    assert other_adapter.calls == 1


async def test_backfill_asyncio_cancellation_releases_lock_and_leaves_resumable_run(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import GmailMessageListPage
    from services.gmail_history_service import GmailHistoryService
    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    entered = asyncio.Event()
    release = asyncio.Event()

    class _PausedAdapter:
        async def list_messages_for_backfill(self, **_kwargs):
            entered.set()
            await release.wait()
            return GmailMessageListPage(messages=(), next_page_token=None)

    service = GmailHistoryService(
        engine=engine,
        adapter=_PausedAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Cancellation cleanup recovery.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    verifier = await engine.connect()
    pending = asyncio.create_task(service.run_backfill(request.id))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert not await try_session_advisory_lock(verifier, account.id)
        await verifier.commit()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert await try_session_advisory_lock(verifier, account.id)
        assert await release_session_advisory_lock(verifier, account.id)
        await verifier.commit()
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await verifier.close()

    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        stored_request = await session.get(GmailBackfillRequest, request.id)
        run = (
            await session.get(GmailSyncRun, stored_request.run_id)
            if stored_request.run_id is not None
            else None
        )
        checkpoint_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncPageCheckpoint)
        )
    assert stored_account.committed_history_id == "700"
    assert stored_account.blocked_reason == "history_cursor_expired"
    assert stored_request.state in {"requested", "running"}
    if run is not None:
        assert run.state == "running"
        assert run.next_page_token is None
    assert checkpoint_count == 0


@pytest.mark.parametrize("terminal_page", [False, True])
async def test_backfill_pid_drift_terminalizes_request_and_allows_later_recovery(
    recovery_runtime,
    terminal_page: bool,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import GmailMessageListPage
    from services.gmail_history_service import (
        GmailBackfillNotComplete,
        GmailHistoryService,
        GmailSessionAffinityLost,
    )
    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

    class _OnePageAdapter:
        calls = 0

        async def list_messages_for_backfill(self, **_kwargs):
            self.calls += 1
            return GmailMessageListPage(
                messages=(),
                next_page_token=None if terminal_page else "unreached-page-2",
            )

    pid_reads = 0

    async def drifting_pid(_connection):
        nonlocal pid_reads
        pid_reads += 1
        return 41001 if pid_reads <= 2 else 41002

    adapter = _OnePageAdapter()
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        backend_pid_reader=drifting_pid,
    )
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Recover after a direct-session endpoint repair.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    verifier = await engine.connect()
    try:
        with pytest.raises(
            GmailSessionAffinityLost,
            match="^gmail_history_session_affinity_lost$",
        ):
            await service.run_backfill(request.id)
        assert await try_session_advisory_lock(verifier, account.id)
        assert await release_session_advisory_lock(verifier, account.id)
        await verifier.commit()
    finally:
        await verifier.close()

    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        stored_request = await session.get(GmailBackfillRequest, request.id)
        run = await session.get(GmailSyncRun, stored_request.run_id)
        checkpoints = list(
            (
                await session.scalars(
                    sa.select(GmailSyncPageCheckpoint).where(
                        GmailSyncPageCheckpoint.run_id == run.id
                    )
                )
            ).all()
        )
    assert adapter.calls == 1
    assert stored_account.committed_history_id == "700"
    assert stored_account.reseed_history_id == "999"
    assert stored_account.blocked_reason == "session_affinity_lost"
    assert stored_account.last_error_category == "session_affinity_lost"
    assert stored_request.state == "failed"
    assert stored_request.result_category == "session_affinity_lost"
    assert run.state == "failed"
    assert run.failure_category == "session_affinity_lost"
    assert len(checkpoints) == 1
    assert checkpoints[0].next_page_token == (
        None if terminal_page else "unreached-page-2"
    )
    with pytest.raises(GmailBackfillNotComplete):
        await service.promote_reseed_after_backfill(request.id)

    # Once the direct endpoint is repaired, the existing failed request cannot
    # poison the active-request uniqueness gate for a new explicit recovery.
    async with sessionmaker() as session:
        repaired = await session.get(GmailSyncAccount, account.id)
        repaired.blocked_reason = "history_cursor_expired"
        repaired.last_error_category = None
        repaired.last_error_message = None
        await session.commit()
    replacement = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Retry after the direct-session endpoint was repaired.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    assert replacement.state == "requested"
    assert replacement.id != request.id


async def test_initial_lock_commit_pid_drift_fails_backfill_before_provider(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import GmailBackfillRequest, GmailSyncAccount
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailSessionAffinityLost,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()

    class _NeverCalledAdapter:
        calls = 0

        async def list_messages_for_backfill(self, **_kwargs):
            self.calls += 1
            raise AssertionError("provider must not run after initial affinity loss")

    pids = iter((62001, 62002))

    async def backend_pid_reader(_connection):
        return next(pids)

    adapter = _NeverCalledAdapter()
    service = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        backend_pid_reader=backend_pid_reader,
    )
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Recover after initial direct-session affinity loss.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )

    with pytest.raises(
        GmailSessionAffinityLost, match="^gmail_history_session_affinity_lost$"
    ):
        await service.run_backfill(request.id)

    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        stored_request = await session.get(GmailBackfillRequest, request.id)
    assert adapter.calls == 0
    assert stored_account.committed_history_id == "700"
    assert stored_account.reseed_history_id == "999"
    assert stored_account.blocked_reason == "session_affinity_lost"
    assert stored_request.state == "failed"
    assert stored_request.result_category == "session_affinity_lost"
    assert stored_request.run_id is None


async def test_resumed_backfill_initial_pid_drift_fails_bound_active_run(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import GmailMessageListPage
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailSessionAffinityLost,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    service = GmailHistoryService(
        engine=engine,
        adapter=object(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Resume a checkpoint only on the retained backend.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    async with sessionmaker() as session:
        stored_request = await session.get(GmailBackfillRequest, request.id)
        run = GmailSyncRun(
            account_id=account.id,
            start_history_id="700",
            next_page_token="page-2",
            run_kind="backfill",
            state="running",
        )
        session.add(run)
        await session.flush()
        session.add(
            GmailSyncPageCheckpoint(
                run_id=run.id,
                page_number=1,
                request_page_token=None,
                next_page_token="page-2",
                receipt_count=0,
            )
        )
        stored_request.run_id = run.id
        stored_request.state = "running"
        stored_request.started_at = datetime.now(tz=UTC)
        await session.commit()
        run_id = run.id

    class _NeverCalledAdapter:
        calls = 0

        async def list_messages_for_backfill(self, **_kwargs):
            self.calls += 1
            raise AssertionError("provider must not run after initial PID drift")

    async def before_pid(_connection):
        return 62001

    async def drifted_post_probe(_connection, _account_id):
        return 62002, True

    adapter = _NeverCalledAdapter()
    drifted = GmailHistoryService(
        engine=engine,
        adapter=adapter,
        participant_hash_key=b"test-participant-key-with-32-bytes",
        backend_pid_reader=before_pid,
        post_lock_probe=drifted_post_probe,
    )
    with pytest.raises(
        GmailSessionAffinityLost,
        match="^gmail_history_session_affinity_lost$",
    ):
        await drifted.run_backfill(request.id)

    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        stored_request = await session.get(GmailBackfillRequest, request.id)
        stored_run = await session.get(GmailSyncRun, run_id)
        active_run_count = await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncRun).where(
                GmailSyncRun.account_id == account.id,
                GmailSyncRun.state.in_(("running", "discovered")),
            )
        )
    assert adapter.calls == 0
    assert stored_account.committed_history_id == "700"
    assert stored_account.blocked_reason == "session_affinity_lost"
    assert stored_request.state == "failed"
    assert stored_request.result_category == "session_affinity_lost"
    assert stored_run.state == "failed"
    assert stored_run.failure_category == "session_affinity_lost"
    assert active_run_count == 0

    async with sessionmaker() as session:
        repaired = await session.get(GmailSyncAccount, account.id)
        repaired.blocked_reason = "history_cursor_expired"
        repaired.last_error_category = None
        repaired.last_error_message = None
        await session.commit()
    replacement = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Continue after the direct History endpoint is repaired.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )

    class _TerminalAdapter:
        async def list_messages_for_backfill(self, **_kwargs):
            return GmailMessageListPage(messages=(), next_page_token=None)

    repaired_service = GmailHistoryService(
        engine=engine,
        adapter=_TerminalAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    result = await repaired_service.run_backfill(replacement.id)
    assert result.pages_committed == 1
    async with sessionmaker() as session:
        replacement_row = await session.get(GmailBackfillRequest, replacement.id)
        replacement_run = await session.get(GmailSyncRun, replacement_row.run_id)
    assert replacement_run.id != run_id
    assert replacement_run.state == "completed"


@pytest.mark.parametrize("run_kind", ["poll", "backfill"])
@pytest.mark.parametrize(
    "release_failure",
    ["pid_drift", "false_unlock", "unlock_error"],
)
async def test_post_finalize_lock_release_failure_is_visible_and_recoverable(
    recovery_runtime,
    monkeypatch,
    run_kind: str,
    release_failure: str,
) -> None:
    import services.gmail_history_service as history_module
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_adapter import (
        GmailHistoryPage,
        GmailMessageListPage,
    )
    from services.gmail_history_service import (
        GmailHistoryService,
        GmailSessionAffinityLost,
    )
    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
    )

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    if run_kind == "backfill":
        async with sessionmaker() as session:
            stored = await session.get(GmailSyncAccount, account.id)
            stored.blocked_reason = "history_cursor_expired"
            stored.reseed_history_id = "999"
            await session.commit()

    class _TerminalAdapter:
        async def list_history(self, **_kwargs):
            return GmailHistoryPage(
                history_id="701",
                messages=(),
                next_page_token=None,
                discovered_history_id_min=None,
                discovered_history_id_max=None,
            )

        async def list_messages_for_backfill(self, **_kwargs):
            return GmailMessageListPage(messages=(), next_page_token=None)

    post_probe_calls = 0

    async def fixed_before_pid(_connection):
        return 73001

    async def scripted_post_probe(_connection, _account_id):
        nonlocal post_probe_calls
        post_probe_calls += 1
        if post_probe_calls == 1:
            return 73001, True
        return (
            (73002, True)
            if release_failure == "pid_drift"
            else (73001, True)
        )

    if release_failure == "false_unlock":

        async def false_unlock(_connection, _account_id):
            return False

        monkeypatch.setattr(
            history_module,
            "release_session_advisory_lock",
            false_unlock,
        )
    elif release_failure == "unlock_error":

        async def broken_unlock(_connection, _account_id):
            raise RuntimeError("release-provider-secret-canary")

        monkeypatch.setattr(
            history_module,
            "release_session_advisory_lock",
            broken_unlock,
        )

    service = GmailHistoryService(
        engine=engine,
        adapter=_TerminalAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
        backend_pid_reader=fixed_before_pid,
        post_lock_probe=scripted_post_probe,
    )
    request = None
    if run_kind == "backfill":
        start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
        request = await service.create_backfill_request(
            account_id=account.id,
            administrator_id=admin_id,
            reason="Prove final lock release cannot fail silently.",
            window_start=start,
            window_end=start + timedelta(days=1),
            audit_id=audit_id,
        )
    with pytest.raises(
        GmailSessionAffinityLost,
        match="^gmail_history_session_affinity_lost$",
    ) as raised:
        if request is None:
            await service.sync_account(account.id)
        else:
            await service.run_backfill(request.id)
    assert "release-provider-secret-canary" not in "".join(
        traceback.format_exception(raised.value)
    )
    assert post_probe_calls == 2

    verifier = await engine.connect()
    try:
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
        stored_request = (
            await session.get(GmailBackfillRequest, request.id)
            if request is not None
            else None
        )
    assert stored_account.committed_history_id == (
        "701" if request is None else "700"
    )
    assert stored_account.blocked_reason == "session_affinity_lost"
    assert run.state == "completed"
    assert len(checkpoints) == 1
    if stored_request is not None:
        assert stored_request.state == "failed"
        assert stored_request.result_category == "session_affinity_lost"


async def test_reseed_promotes_only_after_bound_backfill_run_finishes_final_page(
    recovery_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_service import GmailBackfillNotComplete, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()

    service = GmailHistoryService(
        engine=engine,
        adapter=_ExpiredAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    start = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Recover a controlled three-day window.",
        window_start=start,
        window_end=start + timedelta(days=3),
        audit_id=audit_id,
    )
    async with sessionmaker() as session:
        run = GmailSyncRun(
            account_id=account.id,
            start_history_id="700",
            terminal_history_id=None,
            next_page_token="page-2",
            run_kind="backfill",
            state="running",
        )
        session.add(run)
        await session.flush()
        session.add(
            GmailSyncPageCheckpoint(
                run_id=run.id,
                page_number=1,
                request_page_token=None,
                next_page_token="page-2",
                discovered_history_id_min=None,
                discovered_history_id_max=None,
                receipt_count=2,
            )
        )
        stored_request = await session.get(GmailBackfillRequest, request.id)
        stored_request.run_id = run.id
        stored_request.state = "running"
        await session.commit()
        run_id = run.id

    with pytest.raises(GmailBackfillNotComplete, match="backfill_final_page_required"):
        await service.promote_reseed_after_backfill(request.id)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
    assert stored.committed_history_id == "700"
    assert stored.blocked_reason == "history_cursor_expired"

    async with sessionmaker() as session:
        run = await session.get(GmailSyncRun, run_id)
        run.state = "completed"
        run.terminal_history_id = "999"
        run.next_page_token = None
        session.add(
            GmailSyncPageCheckpoint(
                run_id=run.id,
                page_number=2,
                request_page_token="page-2",
                next_page_token=None,
                discovered_history_id_min=None,
                discovered_history_id_max=None,
                receipt_count=1,
            )
        )
        await session.commit()

    result = await service.promote_reseed_after_backfill(request.id)
    assert result.committed_history_id == "999"
    assert result.reseed_history_id is None
    assert result.blocked_reason is None
    async with sessionmaker() as session:
        stored_request = await session.get(GmailBackfillRequest, request.id)
    assert stored_request.state == "completed"
    assert stored_request.result_category == "completed"


@pytest.mark.parametrize(
    "mutation",
    [
        "completed_without_final_checkpoint",
        "wrong_terminal_history_id",
        "changed_reseed_snapshot",
        "changed_committed_cursor",
        "account_no_longer_blocked",
        "wrong_run_start_history_id",
        "nonterminal_final_checkpoint",
        "request_not_running",
    ],
)
async def test_stale_or_incomplete_backfill_cannot_promote_reseed(
    recovery_runtime,
    mutation: str,
) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_service import GmailBackfillNotComplete, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()
    service = GmailHistoryService(
        engine=engine,
        adapter=_ExpiredAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Controlled stale-snapshot test.",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    async with sessionmaker() as session:
        run = GmailSyncRun(
            account_id=account.id,
            start_history_id="700",
            terminal_history_id="999",
            next_page_token=None,
            run_kind="backfill",
            state="completed",
        )
        session.add(run)
        await session.flush()
        if mutation != "completed_without_final_checkpoint":
            session.add(
                GmailSyncPageCheckpoint(
                    run_id=run.id,
                    page_number=1,
                    request_page_token=None,
                    next_page_token=None,
                    receipt_count=0,
                )
            )
        stored_request = await session.get(GmailBackfillRequest, request.id)
        stored_request.run_id = run.id
        stored_request.state = "running"
        stored_account = await session.get(GmailSyncAccount, account.id)
        if mutation == "wrong_terminal_history_id":
            run.terminal_history_id = "different-terminal"
        elif mutation == "changed_reseed_snapshot":
            stored_account.reseed_history_id = "1000"
        elif mutation == "changed_committed_cursor":
            stored_account.committed_history_id = "701"
        elif mutation == "account_no_longer_blocked":
            stored_account.blocked_reason = None
        elif mutation == "wrong_run_start_history_id":
            run.start_history_id = "699"
        elif mutation == "nonterminal_final_checkpoint":
            checkpoint = await session.scalar(
                sa.select(GmailSyncPageCheckpoint).where(
                    GmailSyncPageCheckpoint.run_id == run.id
                )
            )
            checkpoint.next_page_token = "still-has-another-page"
        elif mutation == "request_not_running":
            stored_request.state = "requested"
        await session.commit()

    with pytest.raises(GmailBackfillNotComplete):
        await service.promote_reseed_after_backfill(request.id)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored_request = await session.get(GmailBackfillRequest, request.id)
    assert stored.committed_history_id != "999"
    assert stored_request.state == (
        "requested" if mutation == "request_not_running" else "running"
    )
    assert stored_request.completed_at is None


async def test_poll_run_cannot_be_used_to_promote_reseed(recovery_runtime) -> None:
    from models.gmail_task_intake import (
        GmailBackfillRequest,
        GmailSyncAccount,
        GmailSyncPageCheckpoint,
        GmailSyncRun,
    )
    from services.gmail_history_service import GmailBackfillNotComplete, GmailHistoryService

    engine, sessionmaker = recovery_runtime
    account = await _seed_account(sessionmaker, cursor="700")
    admin_id, audit_id = await _seed_admin_and_audit(sessionmaker)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        stored.blocked_reason = "history_cursor_expired"
        stored.reseed_history_id = "999"
        await session.commit()
    service = GmailHistoryService(
        engine=engine,
        adapter=_ExpiredAdapter(),
        participant_hash_key=b"test-participant-key-with-32-bytes",
    )
    start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    request = await service.create_backfill_request(
        account_id=account.id,
        administrator_id=admin_id,
        reason="Bounded recovery",
        window_start=start,
        window_end=start + timedelta(days=1),
        audit_id=audit_id,
    )
    async with sessionmaker() as session:
        run = GmailSyncRun(
            account_id=account.id,
            start_history_id="700",
            terminal_history_id="999",
            next_page_token=None,
            run_kind="poll",
            state="completed",
        )
        session.add(run)
        await session.flush()
        session.add(
            GmailSyncPageCheckpoint(
                run_id=run.id,
                page_number=1,
                request_page_token=None,
                next_page_token=None,
                receipt_count=0,
            )
        )
        stored_request = await session.get(GmailBackfillRequest, request.id)
        stored_request.run_id = run.id
        stored_request.state = "running"
        await session.commit()

    with pytest.raises(GmailBackfillNotComplete, match="backfill_run_kind_required"):
        await service.promote_reseed_after_backfill(request.id)
    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
    assert stored.committed_history_id == "700"
