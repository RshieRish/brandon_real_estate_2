from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "84d7a5f9b2c3"
NOW = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)
CHAT_ID = "424242"
CODE_KEY = b"k" * 32


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
def audit_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def audit_runtime(audit_database):
    from models.lead import Lead

    assert Lead.__table__.name == "leads"
    url, sync_engine = audit_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE crm_task_suggestion_approval_nonces, "
                "crm_task_suggestion_events, sydney_question_outbox, "
                "crm_task_clarifications, crm_task_suggestions, crm_tasks, "
                "crm_task_creation_requests, crm_task_sources, "
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


async def _audit_failure(*args, **kwargs):
    del args, kwargs
    raise RuntimeError("synthetic_audit_failure")


async def _seed_suggestion(sessions, *, blocked: bool = False):
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import canonical_task_payload_hash

    request_id = uuid4()
    row = CRMTaskSuggestion(
        source_type="sydney_chat",
        source_scope_key=f"sydney:{request_id}",
        source_action_key=f"sydney-action:{request_id.hex}",
        source_request_id=request_id,
        contact_resolution_state="not_provided",
        title="Confirm the inspection",
        description="Ask whether Tuesday still works.",
        priority="normal",
        task_status="open",
        state="needs_clarification" if blocked else "pending_review",
        clarification_state="pending" if blocked else "not_required",
        blocker_codes=["ambiguous_due_at"] if blocked else [],
        payload_hash=canonical_task_payload_hash(
            title="Confirm the inspection",
            description="Ask whether Tuesday still works.",
            priority="normal",
            due_at=None,
            contact_id=None,
            status="open",
        ),
        model_schema_version="sydney-task-v1",
        obligation_fingerprint="c" * 64,
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
async def test_draft_audit_failure_rolls_back_suggestion(audit_runtime, monkeypatch):
    from routers.agent_control_crm import create_task_draft
    from schemas.agent_control_crm import AgentTaskDraftRequest

    sessions = audit_runtime
    monkeypatch.setattr(
        "routers.agent_control_crm.write_agent_audit_transactional", _audit_failure
    )
    async with sessions() as session:
        with pytest.raises(RuntimeError, match="synthetic_audit_failure"):
            await create_task_draft(
                AgentTaskDraftRequest(request_id=uuid4(), title="Review packet"),
                _request("/api/v1/agent-control/crm/task-drafts"),
                session,
                {"actor": "hermes"},
            )
    async with sessions() as session:
        assert (
            await session.scalar(sa.text("SELECT count(*) FROM crm_task_suggestions"))
            == 0
        )
        assert (
            await session.scalar(sa.text("SELECT count(*) FROM agent_action_audits"))
            == 0
        )


@pytest.mark.asyncio
async def test_approval_link_audit_failure_rolls_back_nonce(audit_runtime, monkeypatch):
    from routers.agent_control_crm import create_task_suggestion_approval_link
    from schemas.agent_control_crm import AgentApprovalLinkRequest

    sessions = audit_runtime
    suggestion = await _seed_suggestion(sessions)
    monkeypatch.setattr(
        "routers.agent_control_crm.write_agent_audit_transactional", _audit_failure
    )
    async with sessions() as session:
        with pytest.raises(RuntimeError, match="synthetic_audit_failure"):
            await create_task_suggestion_approval_link(
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
    async with sessions() as session:
        assert (
            await session.scalar(
                sa.text("SELECT count(*) FROM crm_task_suggestion_approval_nonces")
            )
            == 0
        )
        assert await session.scalar(sa.text("SELECT count(*) FROM crm_tasks")) == 0


@pytest.mark.asyncio
async def test_dismiss_proposal_audit_failure_rolls_back_event(
    audit_runtime, monkeypatch
):
    from models.gmail_task_intake import CRMTaskSuggestion
    from routers.agent_control_crm import propose_task_suggestion_dismissal
    from schemas.agent_control_crm import AgentDismissProposalRequest

    sessions = audit_runtime
    suggestion = await _seed_suggestion(sessions)
    monkeypatch.setattr(
        "routers.agent_control_crm.write_agent_audit_transactional", _audit_failure
    )
    async with sessions() as session:
        with pytest.raises(RuntimeError, match="synthetic_audit_failure"):
            await propose_task_suggestion_dismissal(
                suggestion.id,
                AgentDismissProposalRequest(
                    request_id=uuid4(),
                    expected_version=1,
                    reason="Already completed.",
                ),
                _request(
                    f"/api/v1/agent-control/crm/task-suggestions/{suggestion.id}/dismiss-proposal"
                ),
                session,
                {"actor": "hermes"},
            )
    async with sessions() as session:
        current = await session.get(CRMTaskSuggestion, suggestion.id)
        assert (
            current is not None
            and current.state == "pending_review"
            and current.version == 1
        )
        assert (
            await session.scalar(
                sa.text("SELECT count(*) FROM crm_task_suggestion_events")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_clarification_answer_audit_failure_rolls_back_answer_and_handoff(
    audit_runtime, monkeypatch
):
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox
    from routers.agent_control_crm import answer_task_clarification
    from schemas.agent_control_crm import AgentClarificationAnswerRequest
    from services.sydney_clarification_service import (
        SydneyClarificationService,
        derive_clarification_code,
    )

    sessions = audit_runtime
    suggestion = await _seed_suggestion(sessions, blocked=True)
    service = SydneyClarificationService(
        sessionmaker=sessions,
        brandon_chat_id=CHAT_ID,
        clarification_code_keys={7: CODE_KEY},
        active_code_key_version=7,
    )
    queued = await service.enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Client",
        subject_preview="Inspection",
        now=NOW,
    )
    assert queued.clarification_id is not None
    async with sessions() as session:
        clarification = await session.get(CRMTaskClarification, queued.clarification_id)
        attempt = await session.scalar(
            sa.select(SydneyQuestionOutbox).where(
                SydneyQuestionOutbox.clarification_id == queued.clarification_id
            )
        )
        assert clarification is not None and attempt is not None
        attempt.state = "sending"
        attempt.attempted_at = NOW
        attempt.telegram_chat_id = CHAT_ID
        clarification.first_attempt_at = NOW
        clarification.deadline_anchor_kind = "first_attempt"
        clarification.deadline_anchored_at = NOW
        clarification.slot_deadline_at = NOW + timedelta(hours=48)
        await session.flush()
        attempt.state = "sent"
        attempt.sent_at = NOW + timedelta(seconds=1)
        attempt.telegram_message_id = "9001"
        clarification.deadline_anchor_kind = "initial_sent"
        clarification.deadline_anchored_at = attempt.sent_at
        clarification.slot_deadline_at = attempt.sent_at + timedelta(hours=48)
        await session.commit()
        code = derive_clarification_code(
            key=CODE_KEY,
            key_version=7,
            clarification_id=clarification.id,
            suggestion_id=clarification.suggestion_id,
            suggestion_version=clarification.suggestion_version,
            field_name=clarification.field_name,
            round_number=clarification.round_number,
        )

    monkeypatch.setattr(
        "routers.agent_control_crm.settings.SYDNEY_CLARIFICATION_CODE_KEYS_JSON",
        json_text := __import__("json").dumps(
            {"7": base64.b64encode(CODE_KEY).decode("ascii")}
        ),
    )
    assert json_text
    monkeypatch.setattr(
        "routers.agent_control_crm.settings.SYDNEY_CLARIFICATION_ACTIVE_KEY_VERSION", 7
    )
    monkeypatch.setattr(
        "routers.agent_control_crm.settings.SYDNEY_TELEGRAM_BRANDON_CHAT_ID", CHAT_ID
    )
    monkeypatch.setattr(
        "routers.agent_control_crm.write_agent_audit_transactional", _audit_failure
    )
    async with sessions() as session:
        with pytest.raises(RuntimeError, match="synthetic_audit_failure"):
            await answer_task_clarification(
                AgentClarificationAnswerRequest(
                    code=code,
                    expected_version=1,
                    answer={"kind": "due_at", "decision": "no_due_date"},
                ),
                _request("/api/v1/agent-control/crm/task-clarifications/answer"),
                Response(),
                session,
                {"actor": "hermes"},
            )
    async with sessions() as session:
        clarification = await session.get(CRMTaskClarification, queued.clarification_id)
        current = await session.get(
            __import__(
                "models.gmail_task_intake", fromlist=["CRMTaskSuggestion"]
            ).CRMTaskSuggestion,
            suggestion.id,
        )
        assert clarification is not None and clarification.state == "pending"
        assert current is not None and current.version == 1
        assert current.state == "needs_clarification"
        assert (
            await session.scalar(
                sa.text("SELECT count(*) FROM crm_task_suggestion_approval_nonces")
            )
            == 0
        )
