from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "84d7a5f9b2c3"
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


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
def admin_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def admin_runtime(admin_database):
    from models.lead import Lead

    assert Lead.__table__.name == "leads"
    url, sync_engine = admin_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE gmail_backfill_requests, gmail_message_origins, "
                "gmail_message_receipts, gmail_sync_runs, gmail_sync_accounts, "
                "notification_jobs, integration_health_states, "
                "integration_worker_heartbeats, agent_action_audits, admin_users CASCADE"
            )
        )
    engine = create_async_engine(async_test_url(url), poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessions
    finally:
        await engine.dispose()


def test_all_admin_integration_routes_require_admin_auth():
    from middleware.auth import require_admin
    from routers import admin_integrations

    routes = [
        route
        for route in admin_integrations.router.routes
        if isinstance(route, APIRoute)
    ]
    assert len(routes) == 9
    for route in routes:
        assert require_admin in {
            dependency.call for dependency in route.dependant.dependencies
        }

    app = FastAPI()
    app.include_router(admin_integrations.router, prefix="/api/v1/admin/integrations")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/admin/integrations/gmail-task-intake/status")
    assert response.status_code == 401


def test_send_reconcile_schema_is_strict_and_provider_ids_are_delivery_only():
    from schemas.agent_control_crm import GmailSendIntentReconcileRequest

    base = {
        "account_id": str(uuid4()),
        "expected_state": "delivery_uncertain",
        "expected_version": 2,
        "reason": "Verified by the administrator.",
    }
    delivered = GmailSendIntentReconcileRequest.model_validate(
        {
            **base,
            "outcome": "delivered",
            "candidate_message_id": "message-1",
            "candidate_thread_id": "thread-1",
        }
    )
    assert delivered.outcome == "delivered"
    not_delivered = GmailSendIntentReconcileRequest.model_validate(
        {**base, "outcome": "not_delivered"}
    )
    assert not_delivered.candidate_message_id is None
    for invalid in (
        {**base, "outcome": "delivered"},
        {**base, "outcome": "not_delivered", "candidate_message_id": "message-1"},
        {**base, "outcome": "unknown"},
        {**base, "outcome": "not_delivered", "reason": " "},
        {**base, "outcome": "not_delivered", "extra": True},
    ):
        with pytest.raises(ValidationError):
            GmailSendIntentReconcileRequest.model_validate(invalid)


def test_backfill_schema_rejects_more_than_seven_days_and_naive_bounds():
    from schemas.agent_control_crm import GmailTaskBackfillRequest

    base = {"account_id": str(uuid4()), "reason": "Recover expired cursor history."}
    GmailTaskBackfillRequest.model_validate(
        {**base, "window_start": NOW, "window_end": NOW + timedelta(days=7)}
    )
    for start, end in (
        (NOW, NOW + timedelta(days=7, seconds=1)),
        (NOW, NOW),
        (NOW.replace(tzinfo=None), NOW + timedelta(days=1)),
    ):
        with pytest.raises(ValidationError):
            GmailTaskBackfillRequest.model_validate(
                {**base, "window_start": start, "window_end": end}
            )


@pytest.mark.asyncio
async def test_status_is_body_free_and_backfill_persists_admin_audit(
    admin_runtime, monkeypatch
):
    from models.admin_user import AdminUser
    from models.gmail_task_intake import GmailBackfillRequest, GmailSyncAccount
    from routers.admin_integrations import (
        create_gmail_task_backfill,
        gmail_task_intake_status,
    )
    from schemas.agent_control_crm import GmailTaskBackfillRequest

    _, sessions = admin_runtime
    account = GmailSyncAccount(
        workspace_email="brandon@example.test",
        committed_history_id="100",
        reseed_history_id="200",
        blocked_reason="history_cursor_expired",
        mode="shadow",
    )
    admin = AdminUser(email="admin@example.test", hashed_password="test")
    async with sessions() as session:
        session.add_all([account, admin])
        await session.commit()
        await session.refresh(account)
        await session.refresh(admin)
    monkeypatch.setattr(
        "routers.admin_integrations.settings.GMAIL_TASK_INTAKE_ENABLED", True
    )
    async with sessions() as session:
        status = await gmail_task_intake_status(str(admin.id), session)
        assert status["enabled"] is True
        assert status["account_count"] == 1
    async with sessions() as session:
        response = await create_gmail_task_backfill(
            GmailTaskBackfillRequest(
                account_id=account.id,
                reason="Recover the exact missing interval.",
                window_start=NOW,
                window_end=NOW + timedelta(days=2),
            ),
            str(admin.id),
            _request("/api/v1/admin/integrations/gmail-task-intake/backfill"),
            session,
        )
    async with sessions() as session:
        row = await session.get(GmailBackfillRequest, response["request_id"])
        assert row is not None
        assert row.administrator_id == admin.id
        assert row.state == "requested"
        assert (
            await session.scalar(sa.text("SELECT count(*) FROM agent_action_audits"))
            == 1
        )


@pytest.mark.asyncio
async def test_not_delivered_reconciliation_never_invokes_transport(
    admin_runtime, monkeypatch
):
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import GmailMessageOrigin, GmailSyncAccount
    from routers.admin_integrations import reconcile_gmail_send_intent
    from schemas.agent_control_crm import GmailSendIntentReconcileRequest

    engine, sessions = admin_runtime
    account = GmailSyncAccount(
        workspace_email="delivery@example.test",
        committed_history_id="300",
        mode="shadow",
    )
    initial_audit = AgentActionAudit(
        actor="hermes",
        action_id="workspace.gmail.send",
        method="POST",
        path="/api/v1/agent-control/workspace/gmail/send",
        status_code=503,
        allowed=True,
    )
    request_id = uuid4()
    async with sessions() as session:
        session.add_all([account, initial_audit])
        await session.flush()
        origin = GmailMessageOrigin(
            account_id=account.id,
            request_id=request_id,
            canonical_send_hash="a" * 64,
            canonical_envelope_hash="b" * 64,
            canonical_body_hash="c" * 64,
            origin_kind="sydney_client_send",
            delivery_state="delivery_uncertain",
            action_audit_id=initial_audit.id,
            failure_category="provider_timeout",
            failure_message="Gmail delivery could not be verified.",
            version=2,
        )
        session.add(origin)
        await session.commit()
    assert engine
    monkeypatch.setattr(
        "routers.admin_integrations.settings.GMAIL_TASK_INTAKE_ENABLED", True
    )
    async with sessions() as session:
        result = await reconcile_gmail_send_intent(
            request_id,
            GmailSendIntentReconcileRequest(
                account_id=account.id,
                expected_state="delivery_uncertain",
                expected_version=2,
                outcome="not_delivered",
                reason="Confirmed absent from Sent mail.",
            ),
            "1",
            _request(
                f"/api/v1/admin/integrations/gmail-task-intake/send-intents/{request_id}/reconcile"
            ),
            session,
        )
    assert result["reconciled_outcome"] == "not_delivered"
    assert result["message_id"] is None and result["thread_id"] is None
    async with sessions() as session:
        stored = await session.scalar(
            sa.select(GmailMessageOrigin).where(
                GmailMessageOrigin.request_id == request_id
            )
        )
        assert stored is not None and stored.reconciled_outcome == "not_delivered"


@pytest.mark.asyncio
async def test_reprocess_authorizes_exact_one_use_suppression_override(
    admin_runtime,
    monkeypatch,
):
    from models.admin_user import AdminUser
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import (
        CRMTaskSuggestionSuppression,
        GmailMessageReceipt,
        GmailSyncAccount,
    )
    from routers.admin_integrations import reprocess_gmail_task_receipt
    from schemas.agent_control_crm import GmailTaskReprocessRequest
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _, sessions = admin_runtime
    admin = AdminUser(email=f"admin-{uuid4()}@example.test", hashed_password="test")
    account = GmailSyncAccount(
        workspace_email=f"reprocess-{uuid4()}@example.test",
        committed_history_id="100",
        mode="shadow",
    )
    dismissed_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    async with sessions() as session:
        dismissal_audit = AgentActionAudit(
            actor="admin",
            action_id="command.task_suggestions.dismiss",
            method="POST",
            path="/api/v1/command/task-suggestions/example/dismiss",
            status_code=200,
            allowed=True,
        )
        session.add_all([admin, account, dismissal_audit])
        await session.flush()
        receipt = GmailMessageReceipt(
            account_id=account.id,
            gmail_message_id=f"message-{uuid4()}",
            gmail_thread_id="thread-reprocess-override",
            direction="received",
            message_at=NOW,
            sender_hmac="a" * 64,
            recipient_hmacs_json=json.dumps(["b" * 64]),
            subject_preview="Please follow up",
            body_hash="c" * 64,
            labels_json=json.dumps(["INBOX"]),
            processing_state="ignored",
            classification="ignored_manual_reprocess",
            processed_at=NOW,
        )
        session.add(receipt)
        await session.flush()
        suppression = CRMTaskSuggestionSuppression(
            source_type="gmail_message",
            source_scope_key=gmail_source_scope_key(
                account.id,
                receipt.gmail_thread_id,
            ),
            source_action_key="action-v1:" + "1" * 64,
            obligation_fingerprint="2" * 64,
            identity_instance_digest="3" * 64,
            dismissal_reason="Handled outside the system.",
            dismissed_by_admin_id=admin.id,
            dismissal_audit_id=dismissal_audit.id,
            dismissed_at=dismissed_at,
        )
        session.add(suppression)
        await session.commit()
        await session.refresh(receipt)
        await session.refresh(suppression)
        receipt_id = receipt.id
        suppression_id = suppression.id
        admin_id = admin.id

    monkeypatch.setattr(
        "routers.admin_integrations.settings.GMAIL_TASK_INTAKE_ENABLED", True
    )
    path = f"/api/v1/admin/integrations/gmail-task-intake/reprocess/{receipt_id}"
    async with sessions() as session:
        result = await reprocess_gmail_task_receipt(
            receipt_id,
            GmailTaskReprocessRequest(
                reason="Retry this exact receipt once.",
                suppression_id=suppression_id,
            ),
            str(admin_id),
            _request(path),
            session,
        )
    assert result["processing_state"] == "pending"
    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestionSuppression, suppression_id)
        assert stored is not None
        audit = await session.get(AgentActionAudit, stored.reprocess_override_audit_id)
        assert stored.reprocess_override_at is not None
        assert stored.reprocess_override_consumed_at is None
        assert stored.reprocess_override_by_admin_id == admin_id
        assert audit is not None
        assert audit.actor == "admin"
        assert audit.action_id == "gmail_task_intake.reprocess"
        assert audit.path == path
        assert json.loads(audit.request_meta_json) == {
            "admin_user_id": admin_id,
            "suppression_id": str(suppression_id),
        }
        assert await GmailObligationReconciliationService._override_is_valid(
            session=session,
            suppression=stored,
            receipt_id=receipt_id,
        )
