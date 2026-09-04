from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from database import get_db
from middleware.agent_control import require_agent_control

NEW_ACTIONS = {
    "context.events.ingest",
    "context.sessions.reconcile",
    "context.retrieve",
    "context.history.search",
    "context.runs.start",
    "context.runs.update",
    "context.runs.claim",
    "context.runs.renew",
    "context.tools.start",
    "context.tools.update",
    "context.health.read",
}


def _app(*, event_batch_max_bytes: int | None = None) -> FastAPI:
    from routers import agent_control_context

    app = FastAPI()
    if event_batch_max_bytes is not None:
        from middleware.context_event_batch_limit import (
            ContextEventBatchLimitMiddleware,
        )

        app.add_middleware(
            ContextEventBatchLimitMiddleware,
            max_bytes=event_batch_max_bytes,
        )
    app.include_router(
        agent_control_context.router,
        prefix="/api/v1/agent-control",
    )
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    return app


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer context-secret"}


def _batch_payload() -> dict[str, object]:
    return {
        "platform": "telegram",
        "external_user_id": "brandon-user",
        "external_chat_id": "brandon-chat",
        "display_label": "Brandon",
        "hermes_session_id": "session-1",
        "logical_conversation_id": str(uuid4()),
        "model": "gemini-3.5-flash",
        "source_version": "hermes-0.15.2",
        "events": [
            {
                "source_event_key": "session-1:message-1",
                "event_type": "user",
                "role": "user",
                "occurred_at": "2026-08-25T17:00:00Z",
                "content": "private message body",
                "metadata": {},
            }
        ],
    }


def test_event_batch_contract_rejects_an_oversized_aggregate_payload() -> None:
    from schemas.sydney_context import ContextEventBatchRequest

    payload = _batch_payload()
    event = dict(payload["events"][0])
    payload["events"] = [
        {
            **event,
            "source_event_key": f"session-1:message-{index}",
            "content": "x" * 1_000_000,
        }
        for index in range(9)
    ]

    with pytest.raises(ValidationError, match="context_event_batch_too_large"):
        ContextEventBatchRequest.model_validate(payload)


def test_event_batch_limit_rejects_the_wire_body_before_route_handling() -> None:
    app = _app(event_batch_max_bytes=512)
    client = TestClient(app)
    payload = _batch_payload()
    payload["events"][0]["content"] = "x" * 1_000

    with patch(
        "routers.agent_control_context.ingest_event_batch",
        new_callable=AsyncMock,
    ) as ingest:
        response = client.post(
            "/api/v1/agent-control/context/events/batch",
            headers=_headers(),
            json=payload,
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "sydney_context_event_batch_too_large"}
    ingest.assert_not_awaited()


def test_registry_appends_exact_context_actions_without_write_capability_drift() -> (
    None
):
    from routers.agent_control import AGENT_ACTIONS

    ids = [action.id for action in AGENT_ACTIONS]
    assert NEW_ACTIONS.issubset(ids)
    assert len(ids) == len(set(ids))
    assert "context.events.delete" not in ids
    assert "context.history.delete" not in ids
    assert "context.tools.execute" not in ids


def test_context_redaction_inventory_includes_all_secret_bearing_settings() -> None:
    from routers.agent_control_context import _configured_secrets

    fixtures = {
        "DATABASE_URL": "postgresql+asyncpg://fixture:database-secret@db/app",
        "GMAIL_HISTORY_DATABASE_URL": (
            "postgresql+asyncpg://fixture:history-secret@direct-db/app"
        ),
        "GMAIL_PARTICIPANT_HASH_KEY": "participant-hash-secret-value",
        "SYDNEY_CLARIFICATION_CODE_KEYS_JSON": '{"1":"clarification-secret"}',
    }
    patches = [
        patch(f"routers.agent_control_context.settings.{name}", value)
        for name, value in fixtures.items()
    ]
    for active_patch in patches:
        active_patch.start()
    try:
        configured = set(_configured_secrets())
    finally:
        for active_patch in reversed(patches):
            active_patch.stop()

    assert set(fixtures.values()).issubset(configured)


def test_context_routes_keep_agent_auth_and_strict_response_models() -> None:
    from routers import agent_control_context

    app = _app()
    routes = {route.path: route for route in app.routes if isinstance(route, APIRoute)}
    expected = {
        "/api/v1/agent-control/context/events/batch",
        "/api/v1/agent-control/context/sessions/reconcile",
        "/api/v1/agent-control/context/retrieve",
        "/api/v1/agent-control/context/history/search",
        "/api/v1/agent-control/context/runs/start",
        "/api/v1/agent-control/context/runs/update",
        "/api/v1/agent-control/context/runs/claim",
        "/api/v1/agent-control/context/runs/renew",
        "/api/v1/agent-control/context/tools/start",
        "/api/v1/agent-control/context/tools/update",
        "/api/v1/agent-control/context/health",
    }
    assert expected == set(routes)
    for route in routes.values():
        dependency_calls = {
            dependency.call for dependency in route.dependant.dependencies
        }
        assert require_agent_control in dependency_calls
    assert agent_control_context.router is not None


def test_master_and_retrieval_flags_fail_closed_before_service_calls() -> None:
    app = _app()
    client = TestClient(app)

    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "context-secret"
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_ENABLED",
            False,
        ),
        patch(
            "routers.agent_control_context.ingest_event_batch",
            new_callable=AsyncMock,
        ) as ingest,
    ):
        response = client.post(
            "/api/v1/agent-control/context/events/batch",
            headers=_headers(),
            json=_batch_payload(),
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "sydney_durable_context_disabled"}
    ingest.assert_not_awaited()

    retrieve_payload = {
        "identity_id": str(uuid4()),
        "logical_conversation_id": str(uuid4()),
        "hermes_session_id": "session-1",
        "current_user_text": "What did we decide?",
        "token_budget": 1_000,
    }
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "context-secret"
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_ENABLED",
            True,
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_RETRIEVAL_ENABLED",
            False,
        ),
        patch(
            "routers.agent_control_context.retrieve_context",
            new_callable=AsyncMock,
        ) as retrieve,
    ):
        response = client.post(
            "/api/v1/agent-control/context/retrieve",
            headers=_headers(),
            json=retrieve_payload,
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "sydney_context_retrieval_disabled"}
    retrieve.assert_not_awaited()


def test_authenticated_health_reports_disabled_state_before_master_enablement() -> None:
    from schemas.sydney_context import ContextHealthResponse

    app = _app()
    client = TestClient(app)
    result = ContextHealthResponse(
        status="disabled",
        flags={
            "durable_context": False,
            "retrieval": False,
            "projection": False,
            "retry": False,
        },
        identity_count=0,
        session_count=0,
        event_count=0,
        run_states={},
        checkpoint_lag_events=0,
    )
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "context-secret"
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_ENABLED",
            False,
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_RETRIEVAL_ENABLED",
            False,
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_PROJECTION_ENABLED",
            False,
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED",
            False,
        ),
        patch(
            "routers.agent_control_context.get_context_health",
            AsyncMock(return_value=result),
        ) as health,
        patch(
            "routers.agent_control_context.write_agent_audit",
            new_callable=AsyncMock,
        ),
    ):
        response = client.get(
            "/api/v1/agent-control/context/health",
            headers=_headers(),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    health.assert_awaited_once()


def test_ingest_uses_bearer_and_writes_content_free_audit_metadata() -> None:
    from schemas.sydney_context import ContextEventBatchResponse

    app = _app()
    client = TestClient(app)
    identity_id = uuid4()
    session_id = uuid4()
    logical_id = uuid4()
    event_id = uuid4()
    result = ContextEventBatchResponse(
        identity_id=identity_id,
        session_id=session_id,
        logical_conversation_id=logical_id,
        event_ids=[event_id],
        event_receipts=[
            {
                "event_id": event_id,
                "event_type": "user",
                "occurred_at": "2026-08-25T17:00:00Z",
                "content_sha256": "a" * 64,
            }
        ],
        inserted_count=1,
        replayed_count=0,
    )
    audit = AsyncMock()
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "context-secret"
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_ENABLED",
            True,
        ),
        patch(
            "routers.agent_control_context.ingest_event_batch",
            AsyncMock(return_value=result),
        ) as ingest,
        patch("routers.agent_control_context.write_agent_audit", audit),
    ):
        response = client.post(
            "/api/v1/agent-control/context/events/batch",
            headers=_headers(),
            json=_batch_payload(),
        )
    assert response.status_code == 200
    assert response.json()["event_ids"] == [str(event_id)]
    ingest.assert_awaited_once()
    audit.assert_awaited_once()
    audit_payload = audit.await_args.kwargs
    assert audit_payload["action_id"] == "context.events.ingest"
    assert audit_payload["response_meta"] == {
        "inserted_count": 1,
        "replayed_count": 0,
        "event_count": 1,
    }
    assert "private message body" not in repr(audit_payload)


def test_reconciliation_route_compares_only_content_free_expected_metadata() -> None:
    from schemas.sydney_context import ContextSessionReconciliationResponse

    app = _app()
    client = TestClient(app)
    identity_id = uuid4()
    session_id = uuid4()
    result = ContextSessionReconciliationResponse(
        identity_id=identity_id,
        session_id=session_id,
        hermes_session_id="session-1",
        event_count=3,
        ordered_hash="a" * 64,
        matched=True,
    )
    audit = AsyncMock()
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "context-secret"
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_ENABLED",
            True,
        ),
        patch(
            "routers.agent_control_context.reconcile_session",
            AsyncMock(return_value=result),
        ) as reconcile,
        patch("routers.agent_control_context.write_agent_audit", audit),
    ):
        response = client.post(
            "/api/v1/agent-control/context/sessions/reconcile",
            headers=_headers(),
            json={
                "identity_id": str(identity_id),
                "hermes_session_id": "session-1",
                "expected_event_count": 3,
                "expected_ordered_hash": "a" * 64,
            },
        )

    assert response.status_code == 200
    assert response.json()["matched"] is True
    reconcile.assert_awaited_once()
    assert audit.await_args.kwargs["action_id"] == "context.sessions.reconcile"
    assert audit.await_args.kwargs["request_meta"] == {"expected_event_count": 3}
    assert audit.await_args.kwargs["response_meta"] == {
        "event_count": 3,
        "matched": True,
    }
    assert "a" * 64 not in repr(audit.await_args.kwargs)


def test_retry_claim_flag_is_separate_and_wrong_bearer_never_reaches_handler() -> None:
    app = _app()
    client = TestClient(app)
    claim_payload = {"lease_owner": "atlas-one", "limit": 1}
    claim = AsyncMock()
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "context-secret"
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_ENABLED",
            True,
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED",
            True,
        ),
        patch("routers.agent_control_context.claim_runs", claim),
    ):
        response = client.post(
            "/api/v1/agent-control/context/runs/claim",
            headers={"Authorization": "Bearer wrong"},
            json=claim_payload,
        )
    assert response.status_code == 401
    claim.assert_not_awaited()


def test_run_start_contract_rejects_extra_prompt_content() -> None:
    app = _app()
    client = TestClient(app)
    payload = {
        "identity_id": str(uuid4()),
        "platform_message_id": "telegram-11",
        "inbound_event_id": str(uuid4()),
        "session_id": str(uuid4()),
        "logical_conversation_id": str(uuid4()),
        "terminal_deadline_at": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
        "raw_prompt": "must never persist here",
    }
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "context-secret"
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_ENABLED",
            True,
        ),
    ):
        response = client.post(
            "/api/v1/agent-control/context/runs/start",
            headers=_headers(),
            json=payload,
        )
    assert response.status_code == 422


def test_tool_start_uses_the_server_configured_aggregate_limit() -> None:
    from schemas.sydney_context import ContextToolInvocationResponse

    app = _app()
    client = TestClient(app)
    start = AsyncMock(
        return_value=ContextToolInvocationResponse(
            invocation_id=uuid4(),
            canonical_tool_call_id="bounded-call",
            state="started",
            replay_decision="execute",
            invocation_count=1,
            invocation_limit=7,
        )
    )
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "context-secret"
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_ENABLED",
            True,
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_CONTEXT_MAX_TOOL_INVOCATIONS",
            7,
        ),
        patch("routers.agent_control_context.start_tool_invocation", start),
        patch(
            "routers.agent_control_context.write_agent_audit",
            AsyncMock(),
        ),
    ):
        response = client.post(
            "/api/v1/agent-control/context/tools/start",
            headers=_headers(),
            json={
                "run_id": str(uuid4()),
                "lease_owner": "atlas-one",
                "tool_call_id": "bounded-call",
                "tool_name": "status_read",
                "arguments": {},
                "side_effect_class": "read_only",
            },
        )

    assert response.status_code == 200
    assert start.await_args.kwargs["invocation_limit"] == 7


def test_all_context_operations_return_strict_models_and_content_free_audits() -> None:
    from schemas.sydney_context import (
        ContextHealthResponse,
        ContextHistorySearchResponse,
        ContextPacket,
        ContextRunClaimResponse,
        ContextRunStartResponse,
        ContextRunSummary,
        ContextToolInvocationResponse,
    )

    app = _app()
    client = TestClient(app)
    identity_id = uuid4()
    logical_id = uuid4()
    session_id = uuid4()
    inbound_event_id = uuid4()
    run_id = uuid4()
    deadline = datetime.now(UTC) + timedelta(hours=24)
    run = ContextRunSummary(
        id=run_id,
        identity_id=identity_id,
        platform_message_id="telegram-12",
        inbound_event_id=inbound_event_id,
        session_id=session_id,
        logical_conversation_id=logical_id,
        state="running",
        attempt_count=1,
        lease_owner="atlas-one",
        terminal_deadline_at=deadline,
    )
    cases = [
        (
            "/context/retrieve",
            "retrieve_context",
            {
                "identity_id": str(identity_id),
                "logical_conversation_id": str(logical_id),
                "hermes_session_id": "session-1",
                "current_user_text": "private context needle",
                "token_budget": 1_000,
            },
            ContextPacket(
                identity_id=identity_id,
                logical_conversation_id=logical_id,
                rendered_context="bounded packet",
                estimated_tokens=3,
                sections=[],
            ),
            "context.retrieve",
        ),
        (
            "/context/history/search",
            "search_history",
            {"identity_id": str(identity_id), "query": "private search needle"},
            ContextHistorySearchResponse(events=[], total=0, truncated=False),
            "context.history.search",
        ),
        (
            "/context/runs/start",
            "start_run",
            {
                "identity_id": str(identity_id),
                "platform_message_id": "telegram-12",
                "inbound_event_id": str(inbound_event_id),
                "session_id": str(session_id),
                "logical_conversation_id": str(logical_id),
                "terminal_deadline_at": deadline.isoformat(),
            },
            ContextRunStartResponse(run=run, replayed=False),
            "context.runs.start",
        ),
        (
            "/context/runs/update",
            "update_run_state",
            {
                "run_id": str(run_id),
                "state": "running",
                "lease_owner": "atlas-one",
            },
            run,
            "context.runs.update",
        ),
        (
            "/context/runs/claim",
            "claim_runs",
            {"lease_owner": "atlas-one", "limit": 1},
            ContextRunClaimResponse(runs=[run]),
            "context.runs.claim",
        ),
        (
            "/context/runs/renew",
            "renew_run_lease",
            {"run_id": str(run_id), "lease_owner": "atlas-one"},
            run,
            "context.runs.renew",
        ),
        (
            "/context/tools/start",
            "start_tool_invocation",
            {
                "run_id": str(run_id),
                "lease_owner": "atlas-one",
                "tool_call_id": "tool-call-1",
                "tool_name": "context_history_search",
                "arguments": {"query": "private tool argument"},
                "side_effect_class": "read_only",
            },
            ContextToolInvocationResponse(
                invocation_id=uuid4(),
                canonical_tool_call_id="tool-call-1",
                state="started",
                replay_decision="execute",
            ),
            "context.tools.start",
        ),
        (
            "/context/tools/update",
            "update_tool_invocation",
            {
                "run_id": str(run_id),
                "lease_owner": "atlas-one",
                "tool_call_id": "tool-call-1",
                "state": "not_delivered",
            },
            ContextToolInvocationResponse(
                invocation_id=uuid4(),
                canonical_tool_call_id="tool-call-1",
                state="not_delivered",
                replay_decision="retry_not_delivered",
            ),
            "context.tools.update",
        ),
    ]

    common_patches = (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "context-secret"
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_ENABLED",
            True,
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_RETRIEVAL_ENABLED",
            True,
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED",
            True,
        ),
    )
    with (
        common_patches[0],
        common_patches[1],
        common_patches[2],
        common_patches[3],
        common_patches[4],
    ):
        for path, service_name, payload, result, action_id in cases:
            audit = AsyncMock()
            with (
                patch(
                    f"routers.agent_control_context.{service_name}",
                    AsyncMock(return_value=result),
                ),
                patch("routers.agent_control_context.write_agent_audit", audit),
            ):
                response = client.post(
                    f"/api/v1/agent-control{path}",
                    headers=_headers(),
                    json=payload,
                )
            assert response.status_code == 200, (path, response.text)
            audit.assert_awaited_once()
            assert audit.await_args.kwargs["action_id"] == action_id
            audit_repr = repr(audit.await_args.kwargs)
            assert "private context needle" not in audit_repr
            assert "private search needle" not in audit_repr
            assert "private tool argument" not in audit_repr

        health = ContextHealthResponse(
            status="ready",
            flags={"durable_context": True},
            identity_count=1,
            session_count=2,
            event_count=3,
            run_states={"waiting_retry": 1},
            checkpoint_lag_events=2,
        )
        audit = AsyncMock()
        with (
            patch(
                "routers.agent_control_context.get_context_health",
                AsyncMock(return_value=health),
            ),
            patch("routers.agent_control_context.write_agent_audit", audit),
        ):
            response = client.get(
                "/api/v1/agent-control/context/health",
                headers=_headers(),
            )
        assert response.status_code == 200
        audit.assert_awaited_once()
        assert audit.await_args.kwargs["action_id"] == "context.health.read"


def test_known_context_conflicts_are_bounded_and_never_echo_payloads() -> None:
    from services.sydney_context_service import ContextRunConflict

    app = _app()
    client = TestClient(app)
    payload = {
        "identity_id": str(uuid4()),
        "platform_message_id": "private-platform-message",
        "inbound_event_id": str(uuid4()),
        "session_id": str(uuid4()),
        "logical_conversation_id": str(uuid4()),
        "terminal_deadline_at": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
    }
    audit = AsyncMock()
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "context-secret"
        ),
        patch(
            "routers.agent_control_context.settings.SYDNEY_DURABLE_CONTEXT_ENABLED",
            True,
        ),
        patch(
            "routers.agent_control_context.start_run",
            AsyncMock(side_effect=ContextRunConflict("context_run_replay_conflict")),
        ),
        patch("routers.agent_control_context.write_agent_audit", audit),
    ):
        response = client.post(
            "/api/v1/agent-control/context/runs/start",
            headers=_headers(),
            json=payload,
        )
    assert response.status_code == 409
    assert response.json() == {"detail": "context_run_replay_conflict"}
    assert "private-platform-message" not in response.text
    audit.assert_not_awaited()
