from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "84d7a5f9b2c3"
NEW_ACTIONS = {
    "crm.tasks.read",
    "crm.task_suggestions.read",
    "crm.task_clarifications.answer",
    "crm.task_drafts.create",
    "crm.task_suggestions.approval_link",
    "crm.task_suggestions.dismiss_proposal",
}
FORBIDDEN_ACTIONS = {
    "crm.task_suggestions.dismiss",
    "crm.task_suggestions.approve",
    "crm.tasks.create_confirmed",
    "crm.tasks.archive",
    "crm.tasks.restore",
}


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


@pytest.fixture(scope="module")
def agent_crm_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def agent_crm_runtime(agent_crm_database):
    from models.lead import Lead

    assert Lead.__table__.name == "leads"
    url, sync_engine = agent_crm_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE crm_task_suggestion_approval_nonces, "
                "crm_task_suggestion_events, crm_task_clarifications, "
                "crm_task_suggestion_suppressions, crm_task_suggestions, "
                "crm_tasks, crm_task_creation_requests, crm_task_sources, "
                "crm_record_lifecycle_events, crm_activities, crm_task_links, "
                "agent_action_audits, admin_users, crm_contacts CASCADE"
            )
        )
    engine = create_async_engine(async_test_url(url), poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield sessions
    finally:
        await engine.dispose()


def test_registry_advertises_exactly_six_review_only_crm_actions():
    from routers.agent_control import AGENT_ACTIONS

    action_ids = {action.id for action in AGENT_ACTIONS}
    assert action_ids.intersection(NEW_ACTIONS | FORBIDDEN_ACTIONS) == NEW_ACTIONS


def test_agent_approval_link_is_absolute_and_keeps_secret_in_fragment():
    from services.task_suggestion_approval_service import approval_link

    suggestion_id = uuid4()
    token = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"

    link = approval_link(suggestion_id=suggestion_id, token=token)

    before_fragment, fragment = link.split("#", 1)
    assert before_fragment == (
        "https://www.soldwithsweeney.com/admin/command/task-suggestions"
        f"?suggestion={suggestion_id}"
    )
    assert token not in before_fragment
    assert fragment == f"handoff={token}"


def test_clarification_schema_rejects_hermes_identity_claims():
    from pydantic import ValidationError

    from schemas.agent_control_crm import AgentClarificationAnswerRequest

    base = {"code": "a" * 22, "expected_version": 1, "answer": {"kind": "due_none"}}
    for extra in (
        {"telegram_chat_id": "1"},
        {"telegram_user_id": "2"},
        {"telegram_update_id": "3"},
        {"reply_to_message_id": "4"},
        {"suggestion_id": str(uuid4())},
    ):
        with pytest.raises(ValidationError):
            AgentClarificationAnswerRequest.model_validate({**base, **extra})


def test_malformed_clarification_code_is_not_echoed_by_schema_or_parser():
    from schemas.agent_control_crm import AgentClarificationAnswerRequest
    from services.sydney_clarification_service import (
        SydneyClarificationError,
        parse_clarification_code,
    )

    malformed = "malformed-private-clarification-code"
    payload = AgentClarificationAnswerRequest.model_validate(
        {
            "code": malformed,
            "expected_version": 1,
            "answer": {"kind": "due_at", "decision": "no_due_date"},
        }
    )
    with pytest.raises(SydneyClarificationError) as raised:
        parse_clarification_code(payload.code)
    assert str(raised.value) == "invalid_clarification_code"
    assert malformed not in str(raised.value)


def test_task_write_schemas_reject_naive_due_dates_and_explicit_nulls():
    from datetime import datetime

    from pydantic import ValidationError

    from schemas.agent_control_crm import (
        AgentTaskDraftRequest,
        TaskSuggestionEditRequest,
    )

    with pytest.raises(ValidationError):
        AgentTaskDraftRequest(
            request_id=uuid4(),
            title="Review the offer",
            due_at=datetime(2026, 8, 23, 9, 0),
        )
    version = {
        "expected_version": 1,
        "expected_payload_hash": "a" * 64,
    }
    for field in ("title", "description", "priority"):
        with pytest.raises(ValidationError):
            TaskSuggestionEditRequest.model_validate({**version, field: None})


def test_agent_crm_routes_require_agent_control_auth(monkeypatch):
    from routers import agent_control_crm

    app = FastAPI()
    app.include_router(agent_control_crm.router, prefix="/api/v1/agent-control")
    monkeypatch.setattr("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True)
    monkeypatch.setattr(
        "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "agent-secret"
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/agent-control/crm/tasks")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_task_draft_is_review_only_and_request_id_replays_without_second_audit(
    agent_crm_runtime,
):
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import CRMTaskSuggestion
    from routers.agent_control_crm import create_task_draft
    from schemas.agent_control_crm import AgentTaskDraftRequest

    sessions = agent_crm_runtime
    request_id = uuid4()
    payload = AgentTaskDraftRequest(
        request_id=request_id,
        title="Prepare the buyer consultation",
        description="Draft the agenda for Brandon to review.",
        priority="normal",
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
    async with sessions() as session:
        from services.crm_task_suggestion_service import canonical_task_payload_hash

        edited = await session.get(CRMTaskSuggestion, first.id)
        assert edited is not None
        edited.description = "Command revised this draft after intake."
        edited.version += 1
        edited.payload_hash = canonical_task_payload_hash(
            title=edited.title,
            description=edited.description,
            priority=edited.priority,
            due_at=edited.due_at,
            contact_id=edited.contact_id,
            status=edited.task_status,
        )
        await session.commit()
    async with sessions() as session:
        replay_after_edit = await create_task_draft(
            payload,
            _request("/api/v1/agent-control/crm/task-drafts"),
            session,
            {"actor": "hermes"},
        )
    assert first.id == replay.id
    assert replay_after_edit.id == first.id
    assert replay_after_edit.version == 2
    assert first.state == "pending_review"
    assert first.applied_task_id is None
    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, first.id)
        assert suggestion is not None
        assert suggestion.source_type == "sydney_chat"
        assert suggestion.state == "pending_review"
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 0
        audits = list((await session.scalars(sa.select(AgentActionAudit))).all())
        assert [audit.action_id for audit in audits] == ["crm.task_drafts.create"]


async def _seed_suggestion(sessions):
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import canonical_task_payload_hash

    request_id = uuid4()
    row = CRMTaskSuggestion(
        source_type="sydney_chat",
        source_scope_key=f"sydney:{request_id}",
        source_action_key=f"sydney-action:{request_id.hex}",
        source_request_id=request_id,
        contact_resolution_state="not_provided",
        title="Review the offer",
        description="Check financing terms.",
        priority="high",
        task_status="open",
        state="pending_review",
        clarification_state="not_required",
        blocker_codes=[],
        payload_hash=canonical_task_payload_hash(
            title="Review the offer",
            description="Check financing terms.",
            priority="high",
            due_at=None,
            contact_id=None,
            status="open",
        ),
        model_schema_version="sydney-task-v1",
        obligation_fingerprint="b" * 64,
        confidence=1,
        rationale="",
        version=1,
    )
    async with sessions() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


@pytest.mark.asyncio
async def test_dismiss_proposal_is_idempotent_event_only_and_never_changes_authority(
    agent_crm_runtime,
):
    from models.gmail_task_intake import CRMTaskSuggestion
    from routers.agent_control_crm import propose_task_suggestion_dismissal
    from schemas.agent_control_crm import AgentDismissProposalRequest

    sessions = agent_crm_runtime
    suggestion = await _seed_suggestion(sessions)
    request_id = uuid4()
    payload = AgentDismissProposalRequest(
        request_id=request_id,
        expected_version=1,
        reason="The client already completed this follow-up.",
    )
    async with sessions() as session:
        first = await propose_task_suggestion_dismissal(
            suggestion.id,
            payload,
            _request(
                f"/api/v1/agent-control/crm/task-suggestions/{suggestion.id}/dismiss-proposal"
            ),
            session,
            {"actor": "hermes"},
        )
    async with sessions() as session:
        from services.crm_task_suggestion_service import canonical_task_payload_hash

        edited = await session.get(CRMTaskSuggestion, suggestion.id)
        assert edited is not None
        edited.description = "Command edited the draft after this proposal."
        edited.version += 1
        edited.payload_hash = canonical_task_payload_hash(
            title=edited.title,
            description=edited.description,
            priority=edited.priority,
            due_at=edited.due_at,
            contact_id=edited.contact_id,
            status=edited.task_status,
        )
        await session.commit()
    async with sessions() as session:
        replay = await propose_task_suggestion_dismissal(
            suggestion.id,
            payload,
            _request(
                f"/api/v1/agent-control/crm/task-suggestions/{suggestion.id}/dismiss-proposal"
            ),
            session,
            {"actor": "hermes"},
        )
    assert not first.replayed and replay.replayed
    assert replay.suggestion_version == first.suggestion_version == 1
    async with sessions() as session:
        current = await session.get(CRMTaskSuggestion, suggestion.id)
        assert current is not None
        assert current.state == "pending_review"
        assert current.version == 2
        assert current.clarification_state == "not_required"
        assert (
            await session.scalar(
                sa.text("SELECT count(*) FROM crm_task_suggestion_events")
            )
            == 1
        )
        assert (
            await session.scalar(
                sa.text("SELECT count(*) FROM crm_task_suggestion_suppressions")
            )
            == 0
        )
        assert (
            await session.scalar(
                sa.text("SELECT count(*) FROM crm_task_clarifications")
            )
            == 0
        )
        event_json = await session.scalar(
            sa.text("SELECT event_data_json FROM crm_task_suggestion_events")
        )
        assert json.loads(event_json)["request_id"] == str(request_id)


@pytest.mark.asyncio
async def test_approval_link_contains_secret_only_in_fragment_and_creates_no_task(
    agent_crm_runtime,
):
    from routers.agent_control_crm import create_task_suggestion_approval_link
    from schemas.agent_control_crm import AgentApprovalLinkRequest

    sessions = agent_crm_runtime
    suggestion = await _seed_suggestion(sessions)
    async with sessions() as session:
        result = await create_task_suggestion_approval_link(
            suggestion.id,
            AgentApprovalLinkRequest(
                expected_version=1,
                expected_payload_hash=suggestion.payload_hash,
            ),
            _request(
                f"/api/v1/agent-control/crm/task-suggestions/{suggestion.id}/approval-link"
            ),
            Response(),
            session,
            {"actor": "hermes"},
        )
    before_fragment, fragment = result.approval_link.split("#", 1)
    assert (
        before_fragment
        == (
            "https://www.soldwithsweeney.com/admin/command/task-suggestions"
            f"?suggestion={suggestion.id}"
        )
    )
    assert (
        fragment.startswith("handoff=") and len(fragment.removeprefix("handoff=")) == 43
    )
    assert "handoff=" not in before_fragment
    async with sessions() as session:
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 0


@pytest.mark.asyncio
async def test_concurrent_task_draft_request_id_has_one_result_and_one_audit(
    agent_crm_runtime,
):
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import CRMTaskSuggestion
    from routers.agent_control_crm import create_task_draft
    from schemas.agent_control_crm import AgentTaskDraftRequest

    sessions = agent_crm_runtime
    payload = AgentTaskDraftRequest(
        request_id=uuid4(),
        title="Prepare the inspection agenda",
        description="Draft it for Brandon's review.",
    )

    async def create_once():
        async with sessions() as session:
            return await create_task_draft(
                payload,
                _request("/api/v1/agent-control/crm/task-drafts"),
                session,
                {"actor": "hermes"},
            )

    first, second = await asyncio.gather(create_once(), create_once())
    assert first.id == second.id
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count(CRMTaskSuggestion.id))) == 1
        assert await session.scalar(sa.select(sa.func.count(AgentActionAudit.id))) == 1


@pytest.mark.asyncio
async def test_reissuing_approval_link_rotates_the_only_live_handoff(
    agent_crm_runtime,
):
    from models.sydney_tasks import TaskSuggestionApprovalNonce
    from routers.agent_control_crm import create_task_suggestion_approval_link
    from schemas.agent_control_crm import AgentApprovalLinkRequest

    sessions = agent_crm_runtime
    suggestion = await _seed_suggestion(sessions)
    payload = AgentApprovalLinkRequest(
        expected_version=1,
        expected_payload_hash=suggestion.payload_hash,
    )
    results = []
    for _ in range(2):
        response = Response()
        async with sessions() as session:
            results.append(
                await create_task_suggestion_approval_link(
                    suggestion.id,
                    payload,
                    _request(
                        f"/api/v1/agent-control/crm/task-suggestions/{suggestion.id}/approval-link"
                    ),
                    response,
                    session,
                    {"actor": "hermes"},
                )
            )
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
    assert results[0].approval_link != results[1].approval_link
    async with sessions() as session:
        rows = list(
            (
                await session.scalars(
                    sa.select(TaskSuggestionApprovalNonce).order_by(
                        TaskSuggestionApprovalNonce.issued_at,
                        TaskSuggestionApprovalNonce.id,
                    )
                )
            ).all()
        )
        assert len(rows) == 2
        assert sum(row.consumed_at is None for row in rows) == 1
