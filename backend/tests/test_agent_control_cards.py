from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from database import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from middleware.agent_control import require_agent_control
from models.agent_action_audit import AgentActionAudit
from pydantic import ValidationError
from schemas.card_campaign import CardCampaignDetail

CAMPAIGN_ID = UUID("8ea082cb-c9f5-4ddb-95bf-717ca36cb483")
REQUEST_ID = UUID("68fca6be-1e02-47e6-bf93-242a4a74a620")
NOW = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)


def _detail() -> CardCampaignDetail:
    return CardCampaignDetail(
        id=CAMPAIGN_ID,
        request_id=REQUEST_ID,
        title="September celebration cards",
        month=9,
        status="needs_connection",
        total_recipients=12,
        sendable_recipients=9,
        missing_address_count=3,
        estimated_cost_cents=0,
        currency="USD",
        version=1,
        created_at=NOW,
        updated_at=NOW,
        include_birthdays=True,
        include_home_anniversaries=True,
        audience_ref=uuid4(),
        audience_checksum="b" * 64,
        birthday_recipients=7,
        home_anniversary_recipients=5,
        excluded_recipients=0,
        provider_connected=False,
        provider_connection_reason="contract_required",
        approved_by_actor=None,
        approved_at=None,
        send_request_id=None,
        recipients=[],
    )


class _FakeDB:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush = AsyncMock()

    def add(self, row: object) -> None:
        self.added.append(row)


def test_agent_card_schema_is_strict_and_exposes_no_approval_or_send_fields() -> None:
    from schemas.agent_control_cards import AgentCardCampaignDraftRequest

    payload = AgentCardCampaignDraftRequest(request_id=REQUEST_ID, month=9)
    assert payload.include_birthdays is True
    assert payload.include_home_anniversaries is True
    assert set(payload.model_fields) == {
        "request_id",
        "month",
        "include_birthdays",
        "include_home_anniversaries",
    }
    for invalid in (0, 13, True, "9"):
        with pytest.raises(ValidationError):
            AgentCardCampaignDraftRequest.model_validate(
                {"request_id": str(REQUEST_ID), "month": invalid}
            )
    with pytest.raises(ValidationError):
        AgentCardCampaignDraftRequest.model_validate(
            {
                "request_id": str(REQUEST_ID),
                "month": 9,
                "confirmed_by_brandon": True,
            }
        )


@pytest.mark.asyncio
async def test_agent_draft_returns_absolute_command_review_url_and_no_private_rows(
    monkeypatch,
) -> None:
    from schemas.agent_control_cards import AgentCardCampaignDraftRequest
    from services import agent_control_cards

    create = AsyncMock(return_value=_detail())
    monkeypatch.setattr(
        agent_control_cards.CardCampaignService,
        "create_or_get_draft",
        create,
    )
    monkeypatch.setattr(
        agent_control_cards.settings,
        "COMMAND_PUBLIC_BASE_URL",
        "https://www.soldwithsweeney.com/",
    )
    output = await agent_control_cards.create_agent_card_campaign_draft(
        SimpleNamespace(),
        AgentCardCampaignDraftRequest(request_id=REQUEST_ID, month=9),
    )

    assert output.review_url == (
        f"https://www.soldwithsweeney.com/admin/command/cards/{CAMPAIGN_ID}"
    )
    assert output.requires_brandon_review is True
    assert output.nothing_sent is True
    assert output.total_recipients == 12
    assert output.sendable_recipients == 9
    assert output.missing_address_count == 3
    assert "recipients" not in output.model_dump()
    assert "audience_checksum" not in output.model_dump()
    request = create.await_args.args[1]
    assert request.request_id == REQUEST_ID
    assert request.month == 9


def test_agent_draft_route_is_authenticated_and_audits_only_aggregate_metadata(
    monkeypatch,
) -> None:
    from routers import agent_control_cards
    from schemas.agent_control_cards import AgentCardCampaignDraftResponse

    db = _FakeDB()
    response_model = AgentCardCampaignDraftResponse(
        campaign_id=CAMPAIGN_ID,
        status="needs_connection",
        review_url=f"https://www.soldwithsweeney.com/admin/command/cards/{CAMPAIGN_ID}",
        total_recipients=12,
        sendable_recipients=9,
        missing_address_count=3,
        estimated_cost_cents=0,
        currency="USD",
        provider_connected=False,
        provider_connection_reason="contract_required",
        requires_brandon_review=True,
        nothing_sent=True,
    )
    app = FastAPI()
    app.include_router(agent_control_cards.router, prefix="/api/v1/agent-control")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_agent_control] = lambda: {"actor": "hermes"}
    monkeypatch.setattr(
        agent_control_cards,
        "create_agent_card_campaign_draft",
        AsyncMock(return_value=response_model),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/agent-control/crm/card-campaign-drafts",
            json={"request_id": str(REQUEST_ID), "month": 9},
        )

    assert response.status_code == 201, response.text
    audits = [row for row in db.added if isinstance(row, AgentActionAudit)]
    assert len(audits) == 1
    assert audits[0].action_id == "crm.card_campaign_drafts.create"
    assert json.loads(audits[0].request_meta_json) == {
        "include_birthdays": True,
        "include_home_anniversaries": True,
        "month": 9,
    }
    assert json.loads(audits[0].response_meta_json) == {
        "campaign_id": str(CAMPAIGN_ID),
        "missing_address_count": 3,
        "provider_connected": False,
        "sendable_recipients": 9,
        "status": "needs_connection",
        "total_recipients": 12,
    }


def test_agent_draft_route_rejects_missing_agent_credentials_before_handler(
    monkeypatch,
) -> None:
    from routers import agent_control_cards

    app = FastAPI()
    app.include_router(agent_control_cards.router, prefix="/api/v1/agent-control")
    app.dependency_overrides[get_db] = lambda: _FakeDB()
    monkeypatch.setattr(
        "middleware.agent_control.settings.AGENT_CONTROL_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "middleware.agent_control.settings.AGENT_CONTROL_TOKEN",
        "agent-secret",
    )
    create = AsyncMock()
    monkeypatch.setattr(
        agent_control_cards,
        "create_agent_card_campaign_draft",
        create,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/agent-control/crm/card-campaign-drafts",
            json={"request_id": str(REQUEST_ID), "month": 9},
        )

    assert response.status_code == 401
    create.assert_not_awaited()


def test_agent_registry_adds_draft_only_and_no_card_approve_or_send_action() -> None:
    from routers.agent_control import AGENT_ACTIONS

    card_actions = {
        action.id: action for action in AGENT_ACTIONS if "card" in action.id
    }
    assert set(card_actions) == {"crm.card_campaign_drafts.create"}
    action = card_actions["crm.card_campaign_drafts.create"]
    assert action.risk_tier == "operator_review"
    assert action.side_effects is True
    assert action.path == "/api/v1/agent-control/crm/card-campaign-drafts"
