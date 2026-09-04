from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from database import get_db
from middleware.auth import require_admin, require_admin_subject
from schemas.card_campaign import CardCampaignDetail, CardCampaignPage

CAMPAIGN_ID = UUID("8ea082cb-c9f5-4ddb-95bf-717ca36cb483")
REQUEST_ID = UUID("68fca6be-1e02-47e6-bf93-242a4a74a620")
NOW = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)


def _detail(*, status: str = "needs_connection", version: int = 1):
    return CardCampaignDetail(
        id=CAMPAIGN_ID,
        request_id=REQUEST_ID,
        title="September celebration cards",
        month=9,
        status=status,
        total_recipients=2,
        sendable_recipients=1,
        missing_address_count=1,
        estimated_cost_cents=0,
        currency="USD",
        version=version,
        created_at=NOW,
        updated_at=NOW,
        include_birthdays=True,
        include_home_anniversaries=True,
        audience_ref=uuid4(),
        audience_checksum="a" * 64,
        birthday_recipients=1,
        home_anniversary_recipients=1,
        excluded_recipients=0,
        provider_connected=False,
        provider_connection_reason="contract_required",
        approved_by_actor=None,
        approved_at=None,
        send_request_id=None,
        recipients=[],
    )


def _app(*, authenticated: bool) -> FastAPI:
    from routers import command_cards

    app = FastAPI()
    app.include_router(command_cards.router, prefix="/api/v1/command")
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    if authenticated:
        app.dependency_overrides[require_admin] = lambda: {"sub": "17"}
        app.dependency_overrides[require_admin_subject] = lambda: "17"
    return app


def test_card_routes_have_exact_admin_only_inventory_and_bounded_contracts() -> None:
    from routers import command_cards

    inventory = [
        (method, route.path)
        for route in command_cards.router.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods or ())
        if method != "HEAD"
    ]
    assert inventory == [
        ("GET", "/cards/campaigns"),
        ("POST", "/cards/campaigns/drafts"),
        ("GET", "/cards/campaigns/{campaign_id}"),
        ("PATCH", "/cards/campaigns/{campaign_id}"),
        ("POST", "/cards/campaigns/{campaign_id}/approve-and-send"),
    ]
    assert require_admin in {
        dependency.dependency for dependency in command_cards.router.dependencies
    }

    schema = _app(authenticated=True).openapi()
    listing = schema["paths"]["/api/v1/command/cards/campaigns"]["get"]
    parameters = {item["name"]: item for item in listing["parameters"]}
    assert parameters["limit"]["schema"]["maximum"] == 50
    assert parameters["offset"]["schema"]["minimum"] == 0
    approval_schema = schema["components"]["schemas"]["CardCampaignApproveRequest"]
    assert "confirmed_by_brandon" in approval_schema["required"]
    assert approval_schema["properties"]["confirmed_by_brandon"]["const"] is True


def test_card_routes_reject_missing_admin_auth_before_service_execution() -> None:
    from routers import command_cards

    with (
        patch.object(command_cards, "card_campaign_service") as service_factory,
        TestClient(_app(authenticated=False), raise_server_exceptions=False) as client,
    ):
        response = client.get("/api/v1/command/cards/campaigns")

    assert response.status_code == 401
    service_factory.assert_not_called()


def test_admin_card_routes_correlate_requests_versions_actor_and_responses() -> None:
    from routers import command_cards

    created = _detail()
    updated = _detail(version=2)
    service = SimpleNamespace(
        list_campaigns=AsyncMock(
            return_value=CardCampaignPage(campaigns=[created], total=1)
        ),
        create_or_get_draft=AsyncMock(return_value=created),
        get_campaign=AsyncMock(return_value=created),
        update_campaign=AsyncMock(return_value=updated),
        approve_and_send=AsyncMock(return_value=updated),
    )
    with (
        patch.object(command_cards, "card_campaign_service", return_value=service),
        patch.object(
            command_cards, "write_agent_audit_transactional", new_callable=AsyncMock
        ),
        TestClient(_app(authenticated=True), raise_server_exceptions=False) as client,
    ):
        listed = client.get("/api/v1/command/cards/campaigns?limit=25&offset=0")
        draft = client.post(
            "/api/v1/command/cards/campaigns/drafts",
            json={"request_id": str(REQUEST_ID), "month": 9},
        )
        detail = client.get(f"/api/v1/command/cards/campaigns/{CAMPAIGN_ID}")
        changed = client.patch(
            f"/api/v1/command/cards/campaigns/{CAMPAIGN_ID}",
            json={"expected_version": 1, "title": "September client cards"},
        )
        sent = client.post(
            f"/api/v1/command/cards/campaigns/{CAMPAIGN_ID}/approve-and-send",
            json={
                "request_id": str(uuid4()),
                "expected_version": 2,
                "confirmed_recipient_count": 1,
                "confirmed_cost_cents": 0,
                "confirmed_by_brandon": True,
            },
        )

    assert [
        response.status_code for response in (listed, draft, detail, changed, sent)
    ] == [
        200,
        201,
        200,
        200,
        200,
    ]
    assert listed.json()["total"] == 1
    assert draft.json()["provider_connected"] is False
    assert changed.json()["version"] == 2
    service.list_campaigns.assert_awaited_once_with(ANY, limit=25, offset=0)
    assert service.create_or_get_draft.await_args.args[1].request_id == REQUEST_ID
    assert service.update_campaign.await_args.kwargs["actor"] == "admin:17"
    assert service.approve_and_send.await_args.kwargs["actor"] == "admin:17"


def test_approve_maps_missing_provider_to_connection_required_without_io() -> None:
    from routers import command_cards
    from services.card_campaign_service import CardCampaignNotReady

    service = SimpleNamespace(
        approve_and_send=AsyncMock(
            side_effect=CardCampaignNotReady("provider_not_connected")
        )
    )
    with (
        patch.object(command_cards, "card_campaign_service", return_value=service),
        TestClient(_app(authenticated=True), raise_server_exceptions=False) as client,
    ):
        response = client.post(
            f"/api/v1/command/cards/campaigns/{CAMPAIGN_ID}/approve-and-send",
            json={
                "request_id": str(uuid4()),
                "expected_version": 1,
                "confirmed_recipient_count": 1,
                "confirmed_cost_cents": 0,
                "confirmed_by_brandon": True,
            },
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "provider_not_connected"}
