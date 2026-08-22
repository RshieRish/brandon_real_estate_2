from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import HTTPException, Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "84d7a5f9b2c3"
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def test_command_summary_exposes_bounded_review_provenance() -> None:
    from routers.command_task_suggestions import _summary

    suggestion_id = uuid4()
    row = SimpleNamespace(
        id=suggestion_id,
        source_type="gmail_message",
        title="Send Jane the disclosure package",
        description="Jane requested the signed disclosure package.",
        priority="high",
        due_at=NOW,
        contact_id=41,
        task_status="open",
        state="pending_review",
        clarification_state="not_required",
        blocker_codes=["missing_required_field"],
        owner_clarification_pending=True,
        task_details_clarification_pending=False,
        confidence=0.94,
        rationale="The message explicitly requests a disclosure follow-up.",
        model_schema_version="gmail-task-v1",
        payload_hash="a" * 64,
        version=7,
        applied_task_id=None,
        created_at=NOW,
        updated_at=NOW,
    )
    source = SimpleNamespace(
        direction="received",
        source_label=f"gmail:received:{'1' * 32}",
        created_at=NOW,
    )
    event = SimpleNamespace(
        suggestion_version=7,
        event_type="edit",
        actor_type="command_admin",
        action_audit_id=91,
        created_at=NOW,
    )

    result = _summary(row, sources=(source,), audit_trail=(event,))

    assert result.confidence == 0.94
    assert result.rationale.startswith("The message explicitly")
    assert result.model_schema_version == "gmail-task-v1"
    assert result.resolution_requirements == ["resolve_owner_as_brandon"]
    assert result.sources[0].model_dump() == {
        "direction": "received",
        "source_label": f"gmail:received:{'1' * 32}",
        "created_at": NOW,
    }
    assert result.audit_trail[0].model_dump() == {
        "suggestion_version": 7,
        "event_type": "edit",
        "actor_type": "command_admin",
        "action_audited": True,
        "created_at": NOW,
    }


def _request(path: str, *, method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": [],
            "scheme": "https",
            "server": ("testserver", 443),
        }
    )


@pytest.fixture(scope="module")
def approval_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def approval_runtime(approval_database):
    from models.lead import Lead

    assert Lead.__table__.name == "leads"
    url, sync_engine = approval_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE crm_task_suggestion_approval_nonces, "
                "crm_task_suggestion_events, crm_task_suggestions, crm_tasks, "
                "crm_task_creation_requests, crm_task_sources, "
                "crm_record_lifecycle_events, crm_activities, crm_task_links, "
                "admin_users, crm_contacts CASCADE"
            )
        )
    engine = create_async_engine(async_test_url(url), poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessions
    finally:
        await engine.dispose()


async def _seed(sessions, *, blocked: bool = False):
    from models.admin_user import AdminUser
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import canonical_task_payload_hash

    request_id = uuid4()
    suggestion = CRMTaskSuggestion(
        source_type="sydney_chat",
        source_scope_key=f"sydney:{request_id}",
        source_action_key=f"sydney-action:{request_id.hex}",
        source_request_id=request_id,
        contact_resolution_state="not_provided",
        title="Call the listing agent",
        description="Confirm showing availability.",
        priority="high",
        task_status="open",
        state="needs_clarification" if blocked else "pending_review",
        clarification_state="pending" if blocked else "not_required",
        blocker_codes=["ambiguous_due_at"] if blocked else [],
        payload_hash=canonical_task_payload_hash(
            title="Call the listing agent",
            description="Confirm showing availability.",
            priority="high",
            due_at=None,
            contact_id=None,
            status="open",
        ),
        model_schema_version="sydney-task-v1",
        obligation_fingerprint="a" * 64,
        confidence=1,
        rationale="",
        version=1,
    )
    admin = AdminUser(email=f"admin-{uuid4()}@example.test", hashed_password="test")
    async with sessions() as session:
        session.add_all([admin, suggestion])
        await session.commit()
        await session.refresh(admin)
        await session.refresh(suggestion)
    return admin, suggestion


@pytest.mark.asyncio
async def test_prepare_uses_exact_32_byte_secret_persists_only_hash_and_creates_no_task(
    approval_runtime, monkeypatch
):
    from models.sydney_tasks import TaskSuggestionApprovalNonce
    from services.task_suggestion_approval_service import (
        TaskSuggestionApprovalService,
        approval_token_hash,
    )

    _, sessions = approval_runtime
    admin, suggestion = await _seed(sessions)
    raw = bytes(range(32))
    canonical = __import__("base64").urlsafe_b64encode(raw).decode().rstrip("=")
    monkeypatch.setattr(
        "services.task_suggestion_approval_service.secrets.token_urlsafe",
        lambda n: canonical if n == 32 else "",
    )

    async with sessions() as session, session.begin():
        row, issued = await TaskSuggestionApprovalService().prepare(
            session,
            suggestion_id=suggestion.id,
            administrator_id=admin.id,
            expected_version=suggestion.version,
            expected_payload_hash=suggestion.payload_hash,
            now=NOW,
        )
        assert row.id == suggestion.id
        assert issued.token == canonical

    async with sessions() as session:
        nonce = await session.scalar(sa.select(TaskSuggestionApprovalNonce))
        assert nonce is not None
        assert nonce.token_hash == approval_token_hash(canonical)
        assert nonce.token_hash == hashlib.sha256(canonical.encode("ascii")).digest()
        assert nonce.kind == "approval"
        assert nonce.issuance_path == "command_prepare"
        assert nonce.administrator_id == admin.id
        assert nonce.parent_nonce_id is None
        assert nonce.expires_at == NOW + timedelta(minutes=5)
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 0
        persisted = str(nonce.__dict__)
        assert canonical not in persisted


@pytest.mark.asyncio
async def test_handoff_exchange_is_parent_bound_one_time_and_has_zero_task_side_effects(
    approval_runtime,
):
    from models.sydney_tasks import TaskSuggestionApprovalNonce
    from services.task_suggestion_approval_service import (
        TaskSuggestionApprovalError,
        TaskSuggestionApprovalService,
    )

    _, sessions = approval_runtime
    admin, suggestion = await _seed(sessions)
    service = TaskSuggestionApprovalService()
    async with sessions() as session, session.begin():
        _, handoff = await service.issue_handoff(
            session,
            suggestion_id=suggestion.id,
            expected_version=1,
            expected_payload_hash=suggestion.payload_hash,
            now=NOW,
        )
    async with sessions() as session, session.begin():
        _, approval = await service.exchange_handoff(
            session,
            suggestion_id=suggestion.id,
            administrator_id=admin.id,
            handoff=handoff.token,
            expected_version=1,
            expected_payload_hash=suggestion.payload_hash,
            now=NOW + timedelta(seconds=1),
        )
    assert approval.nonce.parent_nonce_id == handoff.nonce.id
    assert approval.nonce.issuance_path == "handoff_exchange"
    assert approval.nonce.administrator_id == admin.id

    async with sessions() as session, session.begin():
        with pytest.raises(TaskSuggestionApprovalError, match="handoff_invalid"):
            await service.exchange_handoff(
                session,
                suggestion_id=suggestion.id,
                administrator_id=admin.id,
                handoff=handoff.token,
                expected_version=1,
                expected_payload_hash=suggestion.payload_hash,
                now=NOW + timedelta(seconds=2),
            )
    async with sessions() as session:
        parent = await session.get(TaskSuggestionApprovalNonce, handoff.nonce.id)
        assert parent is not None and parent.consumed_at is not None
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 0


@pytest.mark.asyncio
async def test_only_stage_two_approval_applies_once_through_crm_task_service(
    approval_runtime,
):
    from services.task_suggestion_approval_service import TaskSuggestionApprovalService

    _, sessions = approval_runtime
    admin, suggestion = await _seed(sessions)
    service = TaskSuggestionApprovalService()
    async with sessions() as session, session.begin():
        _, issued = await service.prepare(
            session,
            suggestion_id=suggestion.id,
            administrator_id=admin.id,
            expected_version=1,
            expected_payload_hash=suggestion.payload_hash,
            now=NOW,
        )
    request_id = uuid4()
    async with sessions() as session, session.begin():
        first = await service.approve(
            session,
            suggestion_id=suggestion.id,
            administrator_id=admin.id,
            approval=issued.token,
            expected_version=1,
            expected_payload_hash=suggestion.payload_hash,
            request_id=request_id,
            client_timezone="America/New_York",
            now=NOW + timedelta(seconds=1),
        )
        assert not first.replayed
    async with sessions() as session, session.begin():
        replay = await service.approve(
            session,
            suggestion_id=suggestion.id,
            administrator_id=admin.id,
            approval=issued.token,
            expected_version=1,
            expected_payload_hash=suggestion.payload_hash,
            request_id=request_id,
            client_timezone="America/New_York",
            now=NOW + timedelta(minutes=6),
        )
        assert replay.replayed
        assert replay.task.id == first.task.id
    async with sessions() as session:
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 1
        assert (
            await session.scalar(
                sa.text("SELECT count(*) FROM crm_task_creation_requests")
            )
            == 1
        )
        assert (
            await session.scalar(sa.text("SELECT count(*) FROM crm_task_sources")) == 1
        )


@pytest.mark.asyncio
async def test_wrong_admin_expiry_and_blockers_fail_closed_without_tasks(
    approval_runtime,
):
    from services.task_suggestion_approval_service import (
        TaskSuggestionApprovalError,
        TaskSuggestionApprovalService,
    )

    _, sessions = approval_runtime
    admin, suggestion = await _seed(sessions)
    service = TaskSuggestionApprovalService()
    async with sessions() as session, session.begin():
        _, issued = await service.prepare(
            session,
            suggestion_id=suggestion.id,
            administrator_id=admin.id,
            expected_version=1,
            expected_payload_hash=suggestion.payload_hash,
            now=NOW,
        )
    for administrator_id, when in (
        (admin.id + 1, NOW + timedelta(seconds=1)),
        (admin.id, NOW + timedelta(minutes=5)),
    ):
        async with sessions() as session, session.begin():
            with pytest.raises(TaskSuggestionApprovalError, match="approval_invalid"):
                await service.approve(
                    session,
                    suggestion_id=suggestion.id,
                    administrator_id=administrator_id,
                    approval=issued.token,
                    expected_version=1,
                    expected_payload_hash=suggestion.payload_hash,
                    request_id=uuid4(),
                    client_timezone="UTC",
                    now=when,
                )
    _, blocked = await _seed(sessions, blocked=True)
    async with sessions() as session, session.begin():
        with pytest.raises(TaskSuggestionApprovalError, match="suggestion_blocked"):
            await service.prepare(
                session,
                suggestion_id=blocked.id,
                administrator_id=admin.id,
                expected_version=1,
                expected_payload_hash=blocked.payload_hash,
                now=NOW,
            )
    async with sessions() as session:
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 0


def test_malformed_or_noncanonical_tokens_fail_before_lookup():
    from services.task_suggestion_approval_service import (
        TaskSuggestionApprovalError,
        approval_token_hash,
    )

    for token in ("short", "a" * 42, "a" * 44, "=" * 43, "A" * 42 + "="):
        with pytest.raises(TaskSuggestionApprovalError, match="approval_token_invalid"):
            approval_token_hash(token)


@pytest.mark.asyncio
async def test_malformed_handoff_reaches_bounded_route_error_without_database_lookup():
    from routers.command_task_suggestions import exchange_task_suggestion_handoff
    from schemas.agent_control_crm import HandoffExchangeRequest

    class NoDatabase:
        def begin(self):
            class Transaction:
                async def __aenter__(self):
                    return None

                async def __aexit__(self, exc_type, exc, traceback):
                    return None

            return Transaction()

        def __getattr__(self, name):
            raise AssertionError(f"database lookup attempted: {name}")

    malformed = "malformed-secret-that-must-not-be-echoed"
    with pytest.raises(HTTPException) as raised:
        await exchange_task_suggestion_handoff(
            uuid4(),
            HandoffExchangeRequest(
                handoff=malformed,
                expected_version=1,
                expected_payload_hash="a" * 64,
            ),
            _request("/api/v1/command/task-suggestions/example/handoff/exchange"),
            Response(),
            "1",
            NoDatabase(),  # type: ignore[arg-type]
        )
    assert raised.value.status_code == 422
    assert raised.value.detail == "approval_token_invalid"
    assert raised.value.headers == {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
    }
    assert malformed not in str(raised.value)


@pytest.mark.asyncio
async def test_gmail_approval_locks_thread_before_suggestion_row(
    approval_runtime,
):
    from models.admin_user import AdminUser
    from models.gmail_task_intake import CRMTaskSuggestion, GmailSyncAccount
    from services.crm_task_suggestion_service import canonical_task_payload_hash
    from services.task_suggestion_approval_service import TaskSuggestionApprovalService

    engine, sessions = approval_runtime
    account = GmailSyncAccount(
        workspace_email=f"gmail-lock-{uuid4()}@example.test",
        committed_history_id="100",
        mode="shadow",
    )
    admin = AdminUser(email=f"admin-{uuid4()}@example.test", hashed_password="test")
    async with sessions() as session:
        session.add_all([account, admin])
        await session.flush()
        suggestion = CRMTaskSuggestion(
            gmail_account_id=account.id,
            gmail_thread_id="thread-lock-order",
            source_type="gmail_message",
            source_scope_key=f"gmail:{account.id}:thread-lock-order",
            source_action_key="action-v1:" + "1" * 64,
            source_request_id=None,
            contact_resolution_state="not_provided",
            title="Confirm the inspection",
            description="Call the inspector.",
            priority="normal",
            task_status="open",
            state="pending_review",
            clarification_state="not_required",
            blocker_codes=[],
            payload_hash=canonical_task_payload_hash(
                title="Confirm the inspection",
                description="Call the inspector.",
                priority="normal",
                due_at=None,
                contact_id=None,
                status="open",
            ),
            model_schema_version="gmail-task-v1",
            obligation_fingerprint="e" * 64,
            primary_instance_digest="f" * 64,
            confidence=1,
            rationale="",
            version=1,
        )
        session.add(suggestion)
        await session.commit()
        await session.refresh(suggestion)
        await session.refresh(admin)

    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.split()).casefold())

    sa.event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        async with sessions() as session, session.begin():
            await TaskSuggestionApprovalService().prepare(
                session,
                suggestion_id=suggestion.id,
                administrator_id=admin.id,
                expected_version=1,
                expected_payload_hash=suggestion.payload_hash,
                now=NOW,
            )
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", record)
    advisory_index = next(
        index
        for index, statement in enumerate(statements)
        if "pg_advisory_xact_lock" in statement
    )
    suggestion_lock_index = next(
        index
        for index, statement in enumerate(statements)
        if "from crm_task_suggestions" in statement and "for update" in statement
    )
    assert advisory_index < suggestion_lock_index


@pytest.mark.asyncio
async def test_explicit_duplicate_resolution_allows_both_legitimate_gmail_tasks(
    approval_runtime,
):
    from models.admin_user import AdminUser
    from models.gmail_task_intake import CRMTaskSuggestion, GmailSyncAccount
    from routers.command_task_suggestions import (
        edit_task_suggestion,
        get_task_suggestion,
    )
    from schemas.agent_control_crm import TaskSuggestionEditRequest
    from services.crm_task_suggestion_service import canonical_task_payload_hash
    from services.task_suggestion_approval_service import TaskSuggestionApprovalService

    _, sessions = approval_runtime
    account = GmailSyncAccount(
        workspace_email=f"duplicates-{uuid4()}@example.test",
        committed_history_id="100",
        mode="shadow",
    )
    admin = AdminUser(email=f"admin-{uuid4()}@example.test", hashed_password="test")
    titles = ("Call the buyer", "Call the listing agent")
    suggestions = []
    async with sessions() as session:
        session.add_all([account, admin])
        await session.flush()
        for index, title in enumerate(titles):
            row = CRMTaskSuggestion(
                gmail_account_id=account.id,
                gmail_thread_id="thread-legitimate-duplicates",
                source_type="gmail_message",
                source_scope_key=(f"gmail:{account.id}:thread-legitimate-duplicates"),
                source_action_key="action-v1:" + "1" * 64,
                contact_resolution_state="not_provided",
                title=title,
                description=f"Distinct obligation {index + 1}.",
                priority="normal",
                task_status="open",
                state="possible_duplicate",
                clarification_state="not_required",
                blocker_codes=[],
                payload_hash=canonical_task_payload_hash(
                    title=title,
                    description=f"Distinct obligation {index + 1}.",
                    priority="normal",
                    due_at=None,
                    contact_id=None,
                    status="open",
                ),
                model_schema_version="gmail-task-v1",
                obligation_fingerprint=("a" if index == 0 else "b") * 64,
                primary_instance_digest=("c" if index == 0 else "d") * 64,
                confidence=1,
                rationale="",
                version=1,
            )
            session.add(row)
            suggestions.append(row)
        await session.commit()
        for row in suggestions:
            await session.refresh(row)
        await session.refresh(admin)

    service = TaskSuggestionApprovalService()
    task_ids = []
    for index, suggestion in enumerate(suggestions):
        async with sessions() as session:
            summary = await get_task_suggestion(suggestion.id, session)
        assert "confirm_not_duplicate" in summary.resolution_requirements
        async with sessions() as session:
            edited = await edit_task_suggestion(
                suggestion.id,
                TaskSuggestionEditRequest(
                    expected_version=1,
                    expected_payload_hash=suggestion.payload_hash,
                    confirm_not_duplicate=True,
                ),
                _request(
                    f"/api/v1/command/task-suggestions/{suggestion.id}",
                    method="PATCH",
                ),
                str(admin.id),
                session,
            )
        assert edited.state == "pending_review"
        assert "confirm_not_duplicate" not in edited.resolution_requirements
        async with sessions() as session:
            refreshed = await get_task_suggestion(suggestion.id, session)
        assert "confirm_not_duplicate" not in refreshed.resolution_requirements
        if index == 0:
            async with sessions() as session:
                unresolved_sibling = await get_task_suggestion(
                    suggestions[1].id,
                    session,
                )
            assert "confirm_not_duplicate" in unresolved_sibling.resolution_requirements
        async with sessions() as session, session.begin():
            _, issued = await service.prepare(
                session,
                suggestion_id=suggestion.id,
                administrator_id=admin.id,
                expected_version=edited.version,
                expected_payload_hash=edited.payload_hash,
                now=NOW,
            )
        async with sessions() as session, session.begin():
            applied = await service.approve(
                session,
                suggestion_id=suggestion.id,
                administrator_id=admin.id,
                approval=issued.token,
                expected_version=edited.version,
                expected_payload_hash=edited.payload_hash,
                request_id=uuid4(),
                client_timezone="UTC",
                now=NOW + timedelta(seconds=1),
            )
            task_ids.append(applied.task.id)
    assert len(set(task_ids)) == 2
    async with sessions() as session:
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 2


@pytest.mark.asyncio
async def test_sydney_approval_revalidates_unique_contact_authority(
    approval_runtime,
):
    from models.command import CRMContact
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import TaskSuggestionApprovalNonce
    from services.crm_task_suggestion_service import canonical_task_payload_hash
    from services.sydney_clarification_service import contact_resolution_hash
    from services.task_suggestion_approval_service import (
        TaskSuggestionApprovalError,
        TaskSuggestionApprovalService,
    )

    _, sessions = approval_runtime
    admin, suggestion = await _seed(sessions)
    async with sessions() as session:
        contact = CRMContact(
            first_name="Alice",
            last_name="Client",
            email="alice-approval@example.test",
            phone=None,
            stage="lead",
        )
        session.add(contact)
        await session.flush()
        row = await session.get(CRMTaskSuggestion, suggestion.id)
        assert row is not None
        row.contact_id = contact.id
        row.contact_resolution_state = "clarified_unique"
        row.contact_resolution_hash = contact_resolution_hash(
            contact_id=contact.id,
            email="alice-approval@example.test",
        )
        row.payload_hash = canonical_task_payload_hash(
            title=row.title,
            description=row.description,
            priority=row.priority,
            due_at=row.due_at,
            contact_id=contact.id,
            status=row.task_status,
        )
        await session.commit()
        await session.refresh(row)
        suggestion_hash = row.payload_hash
    service = TaskSuggestionApprovalService()
    async with sessions() as session, session.begin():
        _, issued = await service.prepare(
            session,
            suggestion_id=suggestion.id,
            administrator_id=admin.id,
            expected_version=1,
            expected_payload_hash=suggestion_hash,
            now=NOW,
        )
    async with sessions() as session:
        session.add(
            CRMContact(
                first_name="Duplicate",
                last_name="Identity",
                email="alice-approval@example.test",
                phone=None,
                stage="lead",
            )
        )
        await session.commit()
    async with sessions() as session, session.begin():
        with pytest.raises(TaskSuggestionApprovalError) as raised:
            await service.approve(
                session,
                suggestion_id=suggestion.id,
                administrator_id=admin.id,
                approval=issued.token,
                expected_version=1,
                expected_payload_hash=suggestion_hash,
                request_id=uuid4(),
                client_timezone="UTC",
                now=NOW + timedelta(seconds=1),
            )
    assert str(raised.value) == "contact_authority_changed"
    async with sessions() as session:
        nonce = await session.get(TaskSuggestionApprovalNonce, issued.nonce.id)
        assert nonce is not None and nonce.consumed_at is None
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 0


@pytest.mark.asyncio
async def test_forced_token_hash_duplicate_fails_closed_without_extra_nonce_or_task(
    approval_runtime, monkeypatch
):
    from services.task_suggestion_approval_service import (
        TaskSuggestionApprovalError,
        TaskSuggestionApprovalService,
    )

    _, sessions = approval_runtime
    admin, suggestion = await _seed(sessions)
    raw = bytes(reversed(range(32)))
    token = __import__("base64").urlsafe_b64encode(raw).decode().rstrip("=")
    monkeypatch.setattr(
        "services.task_suggestion_approval_service.secrets.token_urlsafe",
        lambda size: token if size == 32 else "",
    )
    service = TaskSuggestionApprovalService()
    async with sessions() as session, session.begin():
        await service.prepare(
            session,
            suggestion_id=suggestion.id,
            administrator_id=admin.id,
            expected_version=1,
            expected_payload_hash=suggestion.payload_hash,
            now=NOW,
        )
    async with sessions() as session, session.begin():
        with pytest.raises(TaskSuggestionApprovalError) as raised:
            await service.prepare(
                session,
                suggestion_id=suggestion.id,
                administrator_id=admin.id,
                expected_version=1,
                expected_payload_hash=suggestion.payload_hash,
                now=NOW + timedelta(seconds=1),
            )
    assert str(raised.value) == "approval_nonce_persistence_invalid"
    async with sessions() as session:
        assert (
            await session.scalar(
                sa.text("SELECT count(*) FROM crm_task_suggestion_approval_nonces")
            )
            == 1
        )
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 0


def test_command_rejects_query_secrets_and_marks_secret_responses_no_store():
    from routers.command_task_suggestions import (
        _no_secret_query,
        _protect_secret_response,
    )

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/command/task-suggestions/example/handoff/exchange",
            "query_string": b"handoff=secret",
            "headers": [],
            "scheme": "https",
            "server": ("testserver", 443),
        }
    )
    with pytest.raises(HTTPException) as raised:
        _no_secret_query(request)
    assert raised.value.status_code == 422
    response = Response()
    _protect_secret_response(response)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_command_edit_preserves_blockers_until_explicit_choices_and_supersedes_question(
    approval_runtime,
):
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification
    from routers.command_task_suggestions import edit_task_suggestion
    from schemas.agent_control_crm import TaskSuggestionEditRequest

    _, sessions = approval_runtime
    admin, suggestion = await _seed(sessions, blocked=True)
    async with sessions() as session:
        row = await session.get(CRMTaskSuggestion, suggestion.id)
        assert row is not None
        row.blocker_codes = [
            "ambiguous_due_at",
            "unsupported_owner",
            "unsupported_link",
        ]
        clarification = CRMTaskClarification(
            suggestion_id=row.id,
            suggestion_version=1,
            field_name="due_at",
            round_number=1,
            telegram_chat_id="123456",
            code_hash=b"c" * 32,
            code_key_version=1,
            options_json="{}",
            state="pending",
            deadline_anchor_kind="created",
            deadline_anchored_at=NOW,
            slot_deadline_at=NOW + timedelta(hours=48),
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(clarification)
        await session.commit()

    async with sessions() as session:
        first = await edit_task_suggestion(
            suggestion.id,
            TaskSuggestionEditRequest(
                expected_version=1,
                expected_payload_hash=suggestion.payload_hash,
                description="Keep the question open for Command review.",
            ),
            _request(
                f"/api/v1/command/task-suggestions/{suggestion.id}",
                method="PATCH",
            ),
            str(admin.id),
            session,
        )
    assert first.blocker_codes == [
        "ambiguous_due_at",
        "unsupported_owner",
        "unsupported_link",
    ]
    assert first.state == "needs_clarification"
    assert first.clarification_state == "manual_review_required"
    async with sessions() as session:
        stored_clarification = await session.scalar(sa.select(CRMTaskClarification))
        assert stored_clarification is not None
        assert stored_clarification.state == "superseded"

    async with sessions() as session:
        second = await edit_task_suggestion(
            suggestion.id,
            TaskSuggestionEditRequest(
                expected_version=first.version,
                expected_payload_hash=first.payload_hash,
                due_at=None,
                resolve_owner_as_brandon=True,
                create_without_unsupported_link=True,
            ),
            _request(
                f"/api/v1/command/task-suggestions/{suggestion.id}",
                method="PATCH",
            ),
            str(admin.id),
            session,
        )
    assert second.blocker_codes == []
    assert second.state == "pending_review"
    assert second.clarification_state == "not_required"


@pytest.mark.asyncio
async def test_command_owner_ambiguity_exposes_only_the_applicable_resolution(
    approval_runtime,
):
    from models.gmail_task_intake import CRMTaskSuggestion
    from routers.command_task_suggestions import (
        edit_task_suggestion,
        get_task_suggestion,
    )
    from schemas.agent_control_crm import TaskSuggestionEditRequest

    _, sessions = approval_runtime
    admin, suggestion = await _seed(sessions, blocked=True)
    async with sessions() as session:
        row = await session.get(CRMTaskSuggestion, suggestion.id)
        assert row is not None
        row.blocker_codes = ["missing_required_field"]
        row.owner_clarification_pending = True
        row.task_details_clarification_pending = False
        await session.commit()

    async with sessions() as session:
        summary = await get_task_suggestion(suggestion.id, session)
    assert summary.resolution_requirements == ["resolve_owner_as_brandon"]

    async with sessions() as session:
        resolved = await edit_task_suggestion(
            suggestion.id,
            TaskSuggestionEditRequest(
                expected_version=summary.version,
                expected_payload_hash=summary.payload_hash,
                resolve_owner_as_brandon=True,
            ),
            _request(
                f"/api/v1/command/task-suggestions/{suggestion.id}",
                method="PATCH",
            ),
            str(admin.id),
            session,
        )
    assert resolved.blocker_codes == []
    assert resolved.resolution_requirements == []
    assert resolved.state == "pending_review"


@pytest.mark.asyncio
async def test_command_contact_edit_recomputes_sydney_authority_hash(
    approval_runtime,
):
    from models.command import CRMContact
    from models.gmail_task_intake import CRMTaskSuggestion
    from routers.command_task_suggestions import edit_task_suggestion
    from schemas.agent_control_crm import TaskSuggestionEditRequest
    from services.sydney_clarification_service import contact_resolution_hash

    _, sessions = approval_runtime
    admin, suggestion = await _seed(sessions)
    async with sessions() as session:
        first = CRMContact(
            first_name="Alice",
            last_name="Client",
            email="alice@example.test",
            phone=None,
            stage="lead",
        )
        second = CRMContact(
            first_name="Bob",
            last_name="Client",
            email="bob@example.test",
            phone=None,
            stage="lead",
        )
        session.add_all([first, second])
        await session.flush()
        row = await session.get(CRMTaskSuggestion, suggestion.id)
        assert row is not None
        row.contact_id = first.id
        row.contact_resolution_state = "clarified_unique"
        row.contact_resolution_hash = contact_resolution_hash(
            contact_id=first.id,
            email="alice@example.test",
        )
        from services.crm_task_suggestion_service import canonical_task_payload_hash

        row.payload_hash = canonical_task_payload_hash(
            title=row.title,
            description=row.description,
            priority=row.priority,
            due_at=row.due_at,
            contact_id=first.id,
            status=row.task_status,
        )
        await session.commit()
        await session.refresh(row)
        expected_hash = row.payload_hash
        second_id = second.id

    async with sessions() as session:
        result = await edit_task_suggestion(
            suggestion.id,
            TaskSuggestionEditRequest(
                expected_version=1,
                expected_payload_hash=expected_hash,
                contact_id=second_id,
            ),
            _request(
                f"/api/v1/command/task-suggestions/{suggestion.id}",
                method="PATCH",
            ),
            str(admin.id),
            session,
        )
    assert result.contact_id == second_id
    async with sessions() as session:
        current = await session.get(CRMTaskSuggestion, suggestion.id)
        assert current is not None
        assert current.contact_resolution_hash == contact_resolution_hash(
            contact_id=second_id,
            email="bob@example.test",
        )


@pytest.mark.asyncio
async def test_command_dismiss_supersedes_question_and_writes_suppression_ledger(
    approval_runtime,
):
    from models.gmail_task_intake import CRMTaskSuggestionSuppression
    from models.sydney_tasks import CRMTaskClarification
    from routers.command_task_suggestions import dismiss_task_suggestion
    from schemas.agent_control_crm import DismissSuggestionRequest

    _, sessions = approval_runtime
    admin, suggestion = await _seed(sessions, blocked=True)
    async with sessions() as session:
        session.add(
            CRMTaskClarification(
                suggestion_id=suggestion.id,
                suggestion_version=1,
                field_name="due_at",
                round_number=1,
                telegram_chat_id="123456",
                code_hash=b"d" * 32,
                code_key_version=1,
                options_json="{}",
                state="pending",
                deadline_anchor_kind="created",
                deadline_anchored_at=NOW,
                slot_deadline_at=NOW + timedelta(hours=48),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.commit()
    async with sessions() as session:
        result = await dismiss_task_suggestion(
            suggestion.id,
            DismissSuggestionRequest(
                expected_version=1,
                expected_payload_hash=suggestion.payload_hash,
                reason="Handled outside Command.",
            ),
            _request(f"/api/v1/command/task-suggestions/{suggestion.id}/dismiss"),
            str(admin.id),
            session,
        )
    assert result.state == "dismissed"
    async with sessions() as session:
        clarification = await session.scalar(sa.select(CRMTaskClarification))
        suppression = await session.scalar(sa.select(CRMTaskSuggestionSuppression))
        assert clarification is not None and clarification.state == "superseded"
        assert suppression is not None
        assert suppression.dismissed_by_admin_id == admin.id
        assert suppression.dismissal_reason == "Handled outside Command."


@pytest.mark.asyncio
async def test_command_approval_audit_failure_rolls_back_task_and_nonce_consumption(
    approval_runtime, monkeypatch
):
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import TaskSuggestionApprovalNonce
    from routers.command_task_suggestions import approve_task_suggestion
    from schemas.agent_control_crm import ApprovalRequest
    from services.task_suggestion_approval_service import TaskSuggestionApprovalService

    _, sessions = approval_runtime
    admin, suggestion = await _seed(sessions)
    issued_at = datetime.now(timezone.utc)
    async with sessions() as session, session.begin():
        _, issued = await TaskSuggestionApprovalService().prepare(
            session,
            suggestion_id=suggestion.id,
            administrator_id=admin.id,
            expected_version=1,
            expected_payload_hash=suggestion.payload_hash,
            now=issued_at,
        )

    async def fail_audit(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("synthetic_approval_audit_failure")

    monkeypatch.setattr(
        "routers.command_task_suggestions.write_agent_audit_transactional",
        fail_audit,
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/v1/command/task-suggestions/{suggestion.id}/approve",
            "query_string": b"",
            "headers": [],
            "scheme": "https",
            "server": ("testserver", 443),
        }
    )
    async with sessions() as session:
        with pytest.raises(RuntimeError, match="synthetic_approval_audit_failure"):
            await approve_task_suggestion(
                suggestion.id,
                ApprovalRequest(
                    approval=issued.token,
                    request_id=uuid4(),
                    expected_version=1,
                    expected_payload_hash=suggestion.payload_hash,
                    client_timezone="UTC",
                ),
                request,
                Response(),
                str(admin.id),
                session,
            )
    async with sessions() as session:
        current = await session.get(CRMTaskSuggestion, suggestion.id)
        nonce = await session.get(TaskSuggestionApprovalNonce, issued.nonce.id)
        assert current is not None and current.state == "pending_review"
        assert current.version == 1 and current.applied_task_id is None
        assert nonce is not None and nonce.consumed_at is None
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 0
        assert (
            await session.scalar(
                sa.text("SELECT count(*) FROM crm_task_creation_requests")
            )
            == 0
        )
