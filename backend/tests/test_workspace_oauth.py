import tempfile
import asyncio
import contextvars
import traceback
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import settings
from services import workspace_service
from tests.gmail_task_postgres import async_test_url, migrated_test_database


class WorkspaceOAuthTests(unittest.TestCase):
    def test_full_access_scopes_include_core_workspace_apps(self):
        scopes = set(workspace_service.WORKSPACE_FULL_ACCESS_SCOPES)

        self.assertIn("https://mail.google.com/", scopes)
        self.assertIn("https://www.googleapis.com/auth/calendar", scopes)
        self.assertIn("https://www.googleapis.com/auth/drive", scopes)
        self.assertIn("https://www.googleapis.com/auth/documents", scopes)
        self.assertIn("https://www.googleapis.com/auth/spreadsheets", scopes)
        self.assertIn("https://www.googleapis.com/auth/presentations", scopes)
        self.assertIn("https://www.googleapis.com/auth/contacts", scopes)
        self.assertIn("https://www.googleapis.com/auth/tasks", scopes)

    @patch("services.workspace_service.Flow")
    def test_get_auth_url_requests_offline_access_with_full_consent_prompt(self, mock_flow_cls):
        mock_flow = Mock()
        mock_flow.authorization_url.return_value = ("https://example.com/workspace-auth", "oauth-state")
        mock_flow_cls.from_client_config.return_value = mock_flow

        auth_url, returned_state = workspace_service.get_auth_url("signed-state")

        self.assertEqual(auth_url, "https://example.com/workspace-auth")
        self.assertEqual(returned_state, "oauth-state")
        mock_flow.authorization_url.assert_called_once_with(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state="signed-state",
        )

    @patch("services.workspace_service.Flow")
    def test_exchange_code_returns_credential_bundle_without_side_effects(
        self,
        mock_flow_cls,
    ):
        original_token = settings.GOOGLE_WORKSPACE_REFRESH_TOKEN
        mock_flow = Mock()
        mock_flow.credentials = Mock(
            refresh_token="fresh-workspace-token",
            id_token="signed-google-id-token",
        )
        mock_flow_cls.from_client_config.return_value = mock_flow

        credentials = workspace_service.exchange_code("sample-code", "signed-state")

        self.assertEqual(credentials.refresh_token, "fresh-workspace-token")
        self.assertEqual(credentials.id_token, "signed-google-id-token")
        mock_flow.fetch_token.assert_called_once_with(code="sample-code")
        self.assertEqual(settings.GOOGLE_WORKSPACE_REFRESH_TOKEN, original_token)

    def test_persist_refresh_token_replaces_existing_env_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "GOOGLE_WORKSPACE_CLIENT_ID=test-client\n"
                "GOOGLE_WORKSPACE_REFRESH_TOKEN=old-token\n",
                encoding="utf-8",
            )

            workspace_service.persist_refresh_token("new-token", env_path=env_path)

            self.assertIn(
                "GOOGLE_WORKSPACE_REFRESH_TOKEN=new-token\n",
                env_path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()


REVISION = "83c6f4e8a1b2"


@pytest.fixture(scope="module")
def oauth_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def oauth_runtime(oauth_database):
    url, sync_engine = oauth_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE gmail_sync_accounts, settings CASCADE"
            )
        )
    engine = create_async_engine(async_test_url(url), pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessionmaker
    finally:
        await engine.dispose()


def _verified_identity(*, email: str, refresh_token: str = "db-refresh-token"):
    from services.workspace_service import WorkspaceOAuthIdentity

    return WorkspaceOAuthIdentity(
        refresh_token=refresh_token,
        email=email,
        email_verified=True,
        issuer="https://accounts.google.com",
        audience="workspace-client-id",
    )


async def test_verified_identity_token_account_and_binding_persist_atomically(
    oauth_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from routers.workspace import (
        WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY,
        WORKSPACE_REFRESH_TOKEN_KEY,
        bind_workspace_gmail_identity,
    )

    _engine, sessionmaker = oauth_runtime
    monkeypatch.setattr(settings, "GOOGLE_WORKSPACE_CLIENT_ID", "workspace-client-id")
    async with sessionmaker() as session:
        account = await bind_workspace_gmail_identity(
            session,
            _verified_identity(email=" Brandon@Example.Test "),
        )
        await session.commit()

    assert account.workspace_email == "brandon@example.test"
    assert account.committed_history_id is None
    async with sessionmaker() as session:
        stored_account = await session.get(GmailSyncAccount, account.id)
        settings_by_key = {
            row.key: row.value
            for row in (
                await session.scalars(
                    sa.select(Setting).where(
                        Setting.key.in_(
                            [
                                WORKSPACE_REFRESH_TOKEN_KEY,
                                WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY,
                            ]
                        )
                    )
                )
            ).all()
        }
    assert stored_account.workspace_email == "brandon@example.test"
    assert settings_by_key == {
        WORKSPACE_REFRESH_TOKEN_KEY: "db-refresh-token",
        WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY: str(account.id),
    }


@pytest.mark.parametrize(
    "identity",
    [
        lambda: _verified_identity(email=""),
        lambda: _verified_identity(email="not-an-email"),
        lambda: workspace_service.WorkspaceOAuthIdentity(
            refresh_token="db-refresh-token",
            email="brandon@example.test",
            email_verified=False,
            issuer="https://accounts.google.com",
            audience="workspace-client-id",
        ),
        lambda: workspace_service.WorkspaceOAuthIdentity(
            refresh_token="db-refresh-token",
            email="brandon@example.test",
            email_verified=True,
            issuer="https://evil.example.test",
            audience="workspace-client-id",
        ),
        lambda: workspace_service.WorkspaceOAuthIdentity(
            refresh_token="db-refresh-token",
            email="brandon@example.test",
            email_verified=True,
            issuer="https://accounts.google.com",
            audience="wrong-client-id",
        ),
        lambda: workspace_service.WorkspaceOAuthIdentity(
            refresh_token="",
            email="brandon@example.test",
            email_verified=True,
            issuer="https://accounts.google.com",
            audience="workspace-client-id",
        ),
    ],
)
async def test_invalid_identity_rolls_back_all_binding_state(
    oauth_runtime,
    monkeypatch: pytest.MonkeyPatch,
    identity,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from routers.workspace import bind_workspace_gmail_identity

    _engine, sessionmaker = oauth_runtime
    monkeypatch.setattr(settings, "GOOGLE_WORKSPACE_CLIENT_ID", "workspace-client-id")
    async with sessionmaker() as session:
        with pytest.raises(RuntimeError, match="workspace_identity_invalid"):
            await bind_workspace_gmail_identity(session, identity())
        await session.rollback()
    async with sessionmaker() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(GmailSyncAccount)) == 0
        assert await session.scalar(sa.select(sa.func.count()).select_from(Setting)) == 0


async def test_same_email_rotates_token_but_different_email_cannot_rebind(
    oauth_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from routers.workspace import WORKSPACE_REFRESH_TOKEN_KEY, bind_workspace_gmail_identity

    _engine, sessionmaker = oauth_runtime
    monkeypatch.setattr(settings, "GOOGLE_WORKSPACE_CLIENT_ID", "workspace-client-id")
    async with sessionmaker() as session:
        first = await bind_workspace_gmail_identity(
            session,
            _verified_identity(email="brandon@example.test", refresh_token="first-token"),
        )
        await session.commit()
    async with sessionmaker() as session:
        rotated = await bind_workspace_gmail_identity(
            session,
            _verified_identity(email="BRANDON@example.test", refresh_token="second-token"),
        )
        await session.commit()
    assert rotated.id == first.id
    async with sessionmaker() as session:
        with pytest.raises(RuntimeError, match="workspace_account_rebind_forbidden"):
            await bind_workspace_gmail_identity(
                session,
                _verified_identity(email="other@example.test", refresh_token="other-token"),
            )
        await session.rollback()
        accounts = list((await session.scalars(sa.select(GmailSyncAccount))).all())
        token = await session.scalar(
            sa.select(Setting.value).where(Setting.key == WORKSPACE_REFRESH_TOKEN_KEY)
        )
    assert [(row.id, row.workspace_email) for row in accounts] == [
        (first.id, "brandon@example.test")
    ]
    assert token == "second-token"


async def test_concurrent_first_bindings_serialize_to_one_account_and_identity(
    oauth_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from routers.workspace import bind_workspace_gmail_identity

    _engine, sessionmaker = oauth_runtime
    monkeypatch.setattr(settings, "GOOGLE_WORKSPACE_CLIENT_ID", "workspace-client-id")
    ready = asyncio.Event()
    release = asyncio.Event()
    mutex = asyncio.Lock()
    arrived = 0

    async def before_binding_lock():
        nonlocal arrived
        async with mutex:
            arrived += 1
            if arrived == 2:
                ready.set()
        await release.wait()

    async def bind(email: str):
        async with sessionmaker() as session:
            try:
                row = await bind_workspace_gmail_identity(
                    session,
                    _verified_identity(email=email, refresh_token=f"token-{email}"),
                    before_binding_lock=before_binding_lock,
                )
                await session.commit()
                return row
            except Exception as exc:
                await session.rollback()
                return exc

    tasks = [
        asyncio.create_task(bind("first@example.test")),
        asyncio.create_task(bind("second@example.test")),
    ]
    await asyncio.wait_for(ready.wait(), timeout=2)
    release.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)
    successes = [item for item in results if isinstance(item, GmailSyncAccount)]
    failures = [item for item in results if isinstance(item, RuntimeError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert str(failures[0]) == "workspace_account_rebind_forbidden"
    async with sessionmaker() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(GmailSyncAccount)) == 1
        binding_count = await session.scalar(
            sa.select(sa.func.count()).select_from(Setting).where(
                Setting.key == "google_workspace_gmail_account_id"
            )
        )
    assert binding_count == 1


async def test_oauth_exchange_and_identity_verification_run_off_event_loop() -> None:
    import threading
    import time

    from services.integration_health_service import BoundedProviderExecutor
    from services.workspace_service import run_workspace_oauth_exchange
    from workers.health_app import create_health_app

    started = threading.Event()
    release = threading.Event()

    def stalled_exchange(*_args, **_kwargs):
        started.set()
        release.wait(timeout=5)
        return _verified_identity(email="brandon@example.test")

    executor = BoundedProviderExecutor(max_workers=1)
    client = TestClient(create_health_app(lambda: ("database",)))
    try:
        pending = asyncio.create_task(
            run_workspace_oauth_exchange(
                executor=executor,
                code="opaque-code",
                state="signed-state",
                deadline_seconds=0.05,
                socket_timeout_seconds=0.01,
                exchange=stalled_exchange,
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        started_at = time.monotonic()
        health = await asyncio.to_thread(client.get, "/health")
        assert time.monotonic() - started_at < 0.5
        assert health.status_code == 200
        with pytest.raises(RuntimeError, match="workspace_oauth_provider_timeout"):
            await pending
    finally:
        release.set()
        await executor.wait_for_tracked_calls()
        executor.shutdown()


async def test_workspace_status_is_off_loop_bounded_and_does_not_overlap_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    import time

    from services.integration_health_service import BoundedProviderExecutor
    from services.workspace_service import get_workspace_connection_status_bounded
    from workers.health_app import create_health_app

    for name, value in (
        ("GOOGLE_WORKSPACE_CLIENT_ID", "status-client-id"),
        ("GOOGLE_WORKSPACE_CLIENT_SECRET", "status-client-secret"),
        ("GOOGLE_WORKSPACE_REDIRECT_URI", "https://example.test/status/callback"),
        ("GOOGLE_WORKSPACE_REFRESH_TOKEN", "status-refresh-token"),
    ):
        monkeypatch.setattr(settings, name, value)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def stalled_status_check(**_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)
        return {
            "configured": True,
            "connected": True,
            "can_connect": True,
            "detail": "must not escape after the caller timed out",
        }

    executor = BoundedProviderExecutor(max_workers=2)
    client = TestClient(create_health_app(lambda: ("database",)))
    try:
        pending = asyncio.create_task(
            get_workspace_connection_status_bounded(
                executor=executor,
                deadline_seconds=0.05,
                socket_timeout_seconds=0.01,
                status_check=stalled_status_check,
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        started_at = time.monotonic()
        health = await asyncio.to_thread(client.get, "/health")
        assert time.monotonic() - started_at < 0.5
        assert health.status_code == 200
        timed_out = await pending
        assert timed_out == {
            "configured": True,
            "connected": False,
            "can_connect": True,
            "detail": (
                "Workspace credentials are present, but the connection check "
                "did not complete. Try again shortly."
            ),
        }

        second_started_at = time.monotonic()
        overlapping = await get_workspace_connection_status_bounded(
            executor=executor,
            deadline_seconds=0.05,
            socket_timeout_seconds=0.01,
            status_check=stalled_status_check,
        )
        assert time.monotonic() - second_started_at < 0.5
        assert overlapping == timed_out
        assert calls == 1
    finally:
        release.set()
        await executor.wait_for_tracked_calls()
        executor.shutdown()


async def test_callback_error_is_fixed_escaped_and_never_reflects_query_detail() -> None:
    from routers.workspace import complete_workspace_oauth_callback

    secret = '<script>alert("private-token")</script>'
    response = await complete_workspace_oauth_callback(
        code=None,
        state=None,
        error=secret,
        db=object(),
    )
    body = response.body.decode("utf-8")
    assert response.status_code == 400
    assert secret not in body
    assert "private-token" not in body
    assert "Google authorization was not completed." in body


@pytest.mark.parametrize(
    "issuer", ["accounts.google.com", "https://accounts.google.com"]
)
async def test_raw_id_token_is_verified_with_exact_audience_off_loop(
    issuer: str,
) -> None:
    from services.integration_health_service import BoundedProviderExecutor
    from services.workspace_service import (
        WorkspaceOAuthCredentials,
        run_workspace_oauth_exchange,
    )

    raw_id_token = "signed-id-token-canary"
    refresh_token = "refresh-token-canary"
    request_object = object()
    verifier_calls = []

    def exchange(_code: str, _state: str):
        return WorkspaceOAuthCredentials(
            refresh_token=refresh_token,
            id_token=raw_id_token,
        )

    def verifier(token, request, audience):
        verifier_calls.append((token, request, audience))
        return {
            "sub": "google-subject-123",
            "aud": "workspace-client-id",
            "iss": issuer,
            "email": "Brandon@Example.Test",
            "email_verified": True,
        }

    executor = BoundedProviderExecutor(max_workers=1)
    try:
        identity = await run_workspace_oauth_exchange(
            executor=executor,
            code="opaque-code",
            state="signed-state",
            client_id="workspace-client-id",
            deadline_seconds=1,
            socket_timeout_seconds=0.25,
            exchange=exchange,
            verifier=verifier,
            oauth_request_factory=lambda timeout: (request_object, timeout),
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert verifier_calls == [
        (raw_id_token, (request_object, 0.25), "workspace-client-id")
    ]
    assert identity.subject == "google-subject-123"
    assert identity.email == "brandon@example.test"
    assert identity.refresh_token == refresh_token


async def test_stalled_raw_id_token_verifier_is_off_loop_deadline_bounded_and_secret_free(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import threading
    import time
    import traceback

    from services.integration_health_service import BoundedProviderExecutor
    from services.workspace_service import (
        WorkspaceOAuthCredentials,
        run_workspace_oauth_exchange,
    )
    from workers.health_app import create_health_app

    raw_id_token = "signed-id-token-private-canary"
    started = threading.Event()
    release = threading.Event()

    def exchange(_code: str, _state: str):
        return WorkspaceOAuthCredentials(
            refresh_token="refresh-token-private-canary",
            id_token=raw_id_token,
        )

    def stalled_verifier(_token, _request, _audience):
        started.set()
        release.wait(timeout=5)
        return {
            "sub": "subject",
            "aud": "workspace-client-id",
            "iss": "https://accounts.google.com",
            "email": "brandon@example.test",
            "email_verified": True,
        }

    executor = BoundedProviderExecutor(max_workers=1)
    client = TestClient(create_health_app(lambda: ("database",)))
    try:
        pending = asyncio.create_task(
            run_workspace_oauth_exchange(
                executor=executor,
                code="opaque-code",
                state="signed-state",
                client_id="workspace-client-id",
                deadline_seconds=0.05,
                socket_timeout_seconds=0.01,
                exchange=exchange,
                verifier=stalled_verifier,
                oauth_request_factory=lambda timeout: (object(), timeout),
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        started_at = time.monotonic()
        health = await asyncio.to_thread(client.get, "/health")
        assert time.monotonic() - started_at < 0.5
        assert health.status_code == 200
        with pytest.raises(RuntimeError) as raised:
            await pending
    finally:
        release.set()
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert str(raised.value) == "workspace_oauth_provider_timeout"
    assert raw_id_token not in traceback.format_exception_only(
        type(raised.value), raised.value
    )[0]
    assert raw_id_token not in caplog.text


@pytest.mark.parametrize(
    "claims_or_error",
    [
        ValueError("invalid signature signed-id-token-canary"),
        {
            "sub": "",
            "aud": "workspace-client-id",
            "iss": "https://accounts.google.com",
            "email": "brandon@example.test",
            "email_verified": True,
        },
        {
            "sub": "google-subject-123",
            "aud": "wrong-audience",
            "iss": "https://accounts.google.com",
            "email": "brandon@example.test",
            "email_verified": True,
        },
        {
            "sub": "google-subject-123",
            "aud": "workspace-client-id",
            "iss": "https://evil.example.test",
            "email": "brandon@example.test",
            "email_verified": True,
        },
        {
            "sub": "google-subject-123",
            "aud": "workspace-client-id",
            "iss": "https://accounts.google.com",
            "email": "brandon@example.test",
            "email_verified": False,
        },
        {
            "sub": "google-subject-123",
            "aud": "workspace-client-id",
            "iss": "https://accounts.google.com",
            "email": "",
            "email_verified": True,
        },
    ],
)
async def test_invalid_verified_claims_fail_fixed_and_write_nothing(
    oauth_runtime,
    claims_or_error,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from services.integration_health_service import BoundedProviderExecutor
    from services.workspace_service import (
        WorkspaceOAuthCredentials,
        run_workspace_oauth_exchange,
    )

    _engine, sessionmaker = oauth_runtime
    canary = "signed-id-token-canary"

    def exchange(_code: str, _state: str):
        return WorkspaceOAuthCredentials(
            refresh_token="refresh-token-canary",
            id_token=canary,
        )

    def verifier(_token, _request, _audience):
        if isinstance(claims_or_error, BaseException):
            raise claims_or_error
        return claims_or_error

    executor = BoundedProviderExecutor(max_workers=1)
    try:
        with pytest.raises(
            RuntimeError, match="^workspace_identity_invalid$"
        ) as raised:
            await run_workspace_oauth_exchange(
                executor=executor,
                code="opaque-code",
                state="signed-state",
                client_id="workspace-client-id",
                deadline_seconds=1,
                socket_timeout_seconds=0.25,
                exchange=exchange,
                verifier=verifier,
                oauth_request_factory=lambda timeout: (object(), timeout),
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert canary not in caplog.text
    assert canary not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__suppress_context__ is True
    async with sessionmaker() as session:
        assert await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncAccount)
        ) == 0
        assert await session.scalar(
            sa.select(sa.func.count()).select_from(Setting)
        ) == 0


async def test_complete_callback_commits_bound_tuple_before_success_response_without_env_mutation(
    oauth_runtime,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from routers import workspace as workspace_router
    from routers.workspace import (
        WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY,
        WORKSPACE_REFRESH_TOKEN_KEY,
        build_workspace_oauth_state,
        complete_workspace_oauth_callback,
    )

    _engine, sessionmaker = oauth_runtime
    monkeypatch.setattr(settings, "JWT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "GOOGLE_WORKSPACE_CLIENT_ID", "workspace-client-id")
    monkeypatch.setattr(
        settings, "GOOGLE_WORKSPACE_REFRESH_TOKEN", "ambient-token-canary"
    )
    env_path = tmp_path / ".env"
    env_path.write_text("GOOGLE_WORKSPACE_REFRESH_TOKEN=old-file-token\n", encoding="utf-8")
    monkeypatch.setattr(workspace_service, "ENV_PATH", env_path)
    exchange = AsyncMock(
        return_value=_verified_identity(
            email="Brandon@Example.Test", refresh_token="database-new-token"
        )
    )
    monkeypatch.setattr(workspace_router, "run_workspace_oauth_exchange", exchange)
    state = build_workspace_oauth_state({"sub": "admin-1"})

    async with sessionmaker() as session:
        response = await complete_workspace_oauth_callback(
            code="opaque-code",
            state=state,
            error=None,
            db=session,
        )
        # The callback owns its transaction; a separate session can see the tuple
        # before the HTTP response is handed back to the caller.
        async with sessionmaker() as verifier_session:
            account = await verifier_session.scalar(sa.select(GmailSyncAccount))
            values = {
                row.key: row.value
                for row in (
                    await verifier_session.scalars(
                        sa.select(Setting).where(
                            Setting.key.in_(
                                [
                                    WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY,
                                    WORKSPACE_REFRESH_TOKEN_KEY,
                                ]
                            )
                        )
                    )
                ).all()
            }

    assert response.status_code == 200
    assert account.workspace_email == "brandon@example.test"
    assert values == {
        WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY: str(account.id),
        WORKSPACE_REFRESH_TOKEN_KEY: "database-new-token",
    }
    assert settings.GOOGLE_WORKSPACE_REFRESH_TOKEN == "ambient-token-canary"
    assert env_path.read_text(encoding="utf-8") == (
        "GOOGLE_WORKSPACE_REFRESH_TOKEN=old-file-token\n"
    )


async def test_callback_commit_failure_rolls_back_and_returns_fixed_non_success(
    oauth_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from routers import workspace as workspace_router
    from routers.workspace import (
        WORKSPACE_REFRESH_TOKEN_KEY,
        bind_workspace_gmail_identity,
        build_workspace_oauth_state,
        complete_workspace_oauth_callback,
    )

    engine, sessionmaker = oauth_runtime
    monkeypatch.setattr(settings, "JWT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "GOOGLE_WORKSPACE_CLIENT_ID", "workspace-client-id")
    async with sessionmaker() as session:
        old = await bind_workspace_gmail_identity(
            session,
            _verified_identity(email="brandon@example.test", refresh_token="old-token"),
        )
        await session.commit()

    monkeypatch.setattr(
        workspace_router,
        "run_workspace_oauth_exchange",
        AsyncMock(
            return_value=_verified_identity(
                email="brandon@example.test", refresh_token="new-token-canary"
            )
        ),
    )
    fail_next = True

    def fail_commit(_connection):
        nonlocal fail_next
        if fail_next:
            fail_next = False
            raise RuntimeError("database-private-detail")

    sa.event.listen(engine.sync_engine, "commit", fail_commit)
    try:
        async with sessionmaker() as session:
            response = await complete_workspace_oauth_callback(
                code="opaque-code",
                state=build_workspace_oauth_state({"sub": "admin-1"}),
                error=None,
                db=session,
            )
    finally:
        sa.event.remove(engine.sync_engine, "commit", fail_commit)

    assert response.status_code == 503
    body = response.body.decode("utf-8")
    assert "Workspace authorization could not be saved." in body
    assert "database-private-detail" not in body
    assert "new-token-canary" not in body
    async with sessionmaker() as session:
        accounts = list((await session.scalars(sa.select(GmailSyncAccount))).all())
        token = await session.scalar(
            sa.select(Setting.value).where(Setting.key == WORKSPACE_REFRESH_TOKEN_KEY)
        )
    assert [(row.id, row.workspace_email) for row in accounts] == [
        (old.id, "brandon@example.test")
    ]
    assert token == "old-token"


async def test_concurrent_complete_callbacks_commit_one_coherent_identity_tuple(
    oauth_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from routers.workspace import (
        WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY,
        WORKSPACE_REFRESH_TOKEN_KEY,
        build_workspace_oauth_state,
        complete_workspace_oauth_callback,
    )

    _engine, sessionmaker = oauth_runtime
    monkeypatch.setattr(settings, "JWT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "GOOGLE_WORKSPACE_CLIENT_ID", "workspace-client-id")
    ready = asyncio.Event()
    release = asyncio.Event()
    mutex = asyncio.Lock()
    arrived = 0

    async def exchange(*, code: str, **_kwargs):
        nonlocal arrived
        async with mutex:
            arrived += 1
            if arrived == 2:
                ready.set()
        await release.wait()
        return _verified_identity(
            email=f"{code}@example.test",
            refresh_token=f"token-{code}",
        )

    state = build_workspace_oauth_state({"sub": "admin-1"})

    async def callback(code: str):
        async with sessionmaker() as session:
            return await complete_workspace_oauth_callback(
                code=code,
                state=state,
                error=None,
                db=session,
                oauth_exchange=exchange,
            )

    tasks = [
        asyncio.create_task(callback("first")),
        asyncio.create_task(callback("second")),
    ]
    await asyncio.wait_for(ready.wait(), timeout=2)
    release.set()
    responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)

    assert sorted(response.status_code for response in responses) == [200, 409]
    async with sessionmaker() as session:
        account = await session.scalar(sa.select(GmailSyncAccount))
        values = {
            row.key: row.value
            for row in (
                await session.scalars(
                    sa.select(Setting).where(
                        Setting.key.in_(
                            [
                                WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY,
                                WORKSPACE_REFRESH_TOKEN_KEY,
                            ]
                        )
                    )
                )
            ).all()
        }
    winner = account.workspace_email.split("@", 1)[0]
    assert winner in {"first", "second"}
    assert values == {
        WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY: str(account.id),
        WORKSPACE_REFRESH_TOKEN_KEY: f"token-{winner}",
    }


async def test_invalid_callback_identity_uses_no_gmail_profile_and_writes_nothing(
    oauth_runtime,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from routers.workspace import build_workspace_oauth_state, complete_workspace_oauth_callback

    _engine, sessionmaker = oauth_runtime
    monkeypatch.setattr(settings, "JWT_SECRET", "test-secret")
    profile = Mock(side_effect=AssertionError("OAuth binding must not query Gmail profile"))
    monkeypatch.setattr(workspace_service, "build_workspace_service", profile)

    async def invalid_exchange(**_kwargs):
        raise RuntimeError("workspace_identity_invalid") from ValueError(
            "signed-id-token-private-canary"
        )

    async with sessionmaker() as session:
        response = await complete_workspace_oauth_callback(
            code="opaque-code",
            state=build_workspace_oauth_state({"sub": "admin-1"}),
            error=None,
            db=session,
            oauth_exchange=invalid_exchange,
        )

    assert response.status_code == 503
    body = response.body.decode("utf-8")
    assert body.count("workspace_identity_invalid") == 0
    assert "signed-id-token-private-canary" not in body
    assert "signed-id-token-private-canary" not in caplog.text
    profile.assert_not_called()
    async with sessionmaker() as session:
        assert await session.scalar(
            sa.select(sa.func.count()).select_from(GmailSyncAccount)
        ) == 0
        assert await session.scalar(sa.select(sa.func.count()).select_from(Setting)) == 0


async def test_concurrent_same_email_callbacks_serialize_safe_token_rotation(
    oauth_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from routers.workspace import (
        WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY,
        WORKSPACE_REFRESH_TOKEN_KEY,
        build_workspace_oauth_state,
        complete_workspace_oauth_callback,
    )

    _engine, sessionmaker = oauth_runtime
    monkeypatch.setattr(settings, "JWT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "GOOGLE_WORKSPACE_CLIENT_ID", "workspace-client-id")
    monkeypatch.setattr(
        settings, "GOOGLE_WORKSPACE_REFRESH_TOKEN", "ambient-unchanged"
    )
    ready = asyncio.Event()
    release = asyncio.Event()
    mutex = asyncio.Lock()
    arrived = 0

    async def exchange(*, code: str, **_kwargs):
        nonlocal arrived
        async with mutex:
            arrived += 1
            if arrived == 2:
                ready.set()
        await release.wait()
        return _verified_identity(
            email="Brandon@Example.Test",
            refresh_token=f"verified-{code}-token",
        )

    state = build_workspace_oauth_state({"sub": "admin-1"})

    async def callback(code: str):
        async with sessionmaker() as session:
            return await complete_workspace_oauth_callback(
                code=code,
                state=state,
                error=None,
                db=session,
                oauth_exchange=exchange,
            )

    tasks = [
        asyncio.create_task(callback("first")),
        asyncio.create_task(callback("second")),
    ]
    await asyncio.wait_for(ready.wait(), timeout=2)
    release.set()
    responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)

    assert [response.status_code for response in responses] == [200, 200]
    async with sessionmaker() as session:
        accounts = list((await session.scalars(sa.select(GmailSyncAccount))).all())
        values = {
            row.key: row.value
            for row in (
                await session.scalars(
                    sa.select(Setting).where(
                        Setting.key.in_(
                            [
                                WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY,
                                WORKSPACE_REFRESH_TOKEN_KEY,
                            ]
                        )
                    )
                )
            ).all()
        }
    assert [(row.workspace_email) for row in accounts] == [
        "brandon@example.test"
    ]
    assert values[WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY] == str(accounts[0].id)
    assert values[WORKSPACE_REFRESH_TOKEN_KEY] in {
        "verified-first-token",
        "verified-second-token",
    }
    assert settings.GOOGLE_WORKSPACE_REFRESH_TOKEN == "ambient-unchanged"


@pytest.mark.parametrize(
    ("blocked_reason", "expected_blocked_reason"),
    [
        ("oauth_revoked", None),
        ("history_cursor_expired", "history_cursor_expired"),
        ("session_affinity_lost", "session_affinity_lost"),
    ],
)
async def test_verified_same_mailbox_reconnect_clears_only_oauth_revoked_block(
    oauth_runtime,
    monkeypatch: pytest.MonkeyPatch,
    blocked_reason: str,
    expected_blocked_reason: str | None,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from routers.workspace import (
        WORKSPACE_REFRESH_TOKEN_KEY,
        bind_workspace_gmail_identity,
        build_workspace_oauth_state,
        complete_workspace_oauth_callback,
    )

    _engine, sessionmaker = oauth_runtime
    monkeypatch.setattr(settings, "JWT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "GOOGLE_WORKSPACE_CLIENT_ID", "workspace-client-id")
    async with sessionmaker() as session:
        account = await bind_workspace_gmail_identity(
            session,
            _verified_identity(
                email="brandon@example.test", refresh_token="old-token"
            ),
        )
        account.committed_history_id = "preserved-cursor-123"
        account.reseed_history_id = (
            "preserved-reseed-456"
            if blocked_reason == "history_cursor_expired"
            else None
        )
        account.blocked_reason = blocked_reason
        account.last_error_category = blocked_reason
        account.last_error_message = "Old bounded failure message."
        await session.commit()

    async def exchange(**_kwargs):
        return _verified_identity(
            email="brandon@example.test", refresh_token="rotated-token"
        )

    async with sessionmaker() as session:
        response = await complete_workspace_oauth_callback(
            code="opaque-code",
            state=build_workspace_oauth_state({"sub": "admin-1"}),
            error=None,
            db=session,
            oauth_exchange=exchange,
        )
    assert response.status_code == 200

    async with sessionmaker() as session:
        stored = await session.get(GmailSyncAccount, account.id)
        token = await session.scalar(
            sa.select(Setting.value).where(Setting.key == WORKSPACE_REFRESH_TOKEN_KEY)
        )
    assert stored.committed_history_id == "preserved-cursor-123"
    assert stored.reseed_history_id == (
        "preserved-reseed-456"
        if blocked_reason == "history_cursor_expired"
        else None
    )
    assert stored.blocked_reason == expected_blocked_reason
    if blocked_reason == "oauth_revoked":
        assert stored.last_error_category is None
        assert stored.last_error_message is None
    else:
        assert stored.last_error_category == blocked_reason
        assert stored.last_error_message == "Old bounded failure message."
    assert token == "rotated-token"


async def test_bound_database_token_overrides_stale_ambient_for_provider_clients(
    oauth_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from routers.workspace import (
        build_workspace_oauth_state,
        complete_workspace_oauth_callback,
        load_workspace_refresh_token_from_db,
    )

    _engine, sessionmaker = oauth_runtime
    monkeypatch.setattr(settings, "JWT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "GOOGLE_WORKSPACE_CLIENT_ID", "workspace-client-id")
    monkeypatch.setattr(
        settings,
        "GOOGLE_WORKSPACE_REFRESH_TOKEN",
        "stale-ambient-token",
    )

    async def exchange(**_kwargs):
        return _verified_identity(
            email="brandon@example.test",
            refresh_token="rotated-database-token",
        )

    async with sessionmaker() as session:
        response = await complete_workspace_oauth_callback(
            code="opaque-code",
            state=build_workspace_oauth_state({"sub": "admin-1"}),
            error=None,
            db=session,
            oauth_exchange=exchange,
        )
    assert response.status_code == 200

    client_tokens: list[str] = []

    def build_client(_api_name, _version, *, credentials, cache_discovery):
        assert cache_discovery is False
        client_tokens.append(credentials.refresh_token)
        return object()

    monkeypatch.setattr(workspace_service, "build", build_client)

    async def load_and_build_client():
        async with sessionmaker() as session:
            loaded_token = await load_workspace_refresh_token_from_db(session)
        client = workspace_service.build_workspace_service("gmail", "v1")
        return loaded_token, client

    first = await contextvars.Context().run(
        asyncio.create_task,
        load_and_build_client(),
    )
    restarted = await contextvars.Context().run(
        asyncio.create_task,
        load_and_build_client(),
    )

    assert first[0] == "rotated-database-token"
    assert restarted[0] == "rotated-database-token"
    assert client_tokens == ["rotated-database-token", "rotated-database-token"]
    assert settings.GOOGLE_WORKSPACE_REFRESH_TOKEN == "stale-ambient-token"


@pytest.mark.parametrize("binding_value", ["", "not-a-uuid", str(uuid4())])
async def test_present_invalid_gmail_binding_never_falls_back_to_ambient_token(
    oauth_runtime,
    monkeypatch: pytest.MonkeyPatch,
    binding_value: str,
) -> None:
    from models.setting import Setting
    from routers.workspace import (
        WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY,
        WORKSPACE_REFRESH_TOKEN_KEY,
        load_workspace_refresh_token_from_db,
    )
    from services.workspace_service import WorkspaceIntegrationError

    _engine, sessionmaker = oauth_runtime
    monkeypatch.setattr(
        settings,
        "GOOGLE_WORKSPACE_REFRESH_TOKEN",
        "stale-ambient-token-must-not-be-used",
    )
    async with sessionmaker() as session:
        session.add_all(
            [
                Setting(
                    key=WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY,
                    value=binding_value,
                ),
                Setting(
                    key=WORKSPACE_REFRESH_TOKEN_KEY,
                    value="database-token-must-not-be-used",
                ),
            ]
        )
        await session.commit()

    provider_calls = 0

    def forbidden_build(*_args, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("invalid binding must fail before provider setup")

    monkeypatch.setattr(workspace_service, "build", forbidden_build)

    async def load_and_attempt_client():
        async with sessionmaker() as session:
            token = await load_workspace_refresh_token_from_db(session)
        with pytest.raises(WorkspaceIntegrationError):
            workspace_service.build_workspace_service("gmail", "v1")
        return token

    loaded = await contextvars.Context().run(
        asyncio.create_task,
        load_and_attempt_client(),
    )

    assert loaded == ""
    assert provider_calls == 0
    assert (
        settings.GOOGLE_WORKSPACE_REFRESH_TOKEN
        == "stale-ambient-token-must-not-be-used"
    )
