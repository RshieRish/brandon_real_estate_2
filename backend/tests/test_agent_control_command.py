from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from database import get_db
from services.command_contact_contracts import (
    ContactDirectoryFilters,
    ContactDirectoryPage,
    ContactDirectoryRow,
    ContactOriginFilter,
    ContactSourceFilter,
    ContactTagValue,
)

NOW = datetime(2026, 8, 25, 17, 0, tzinfo=UTC)


def _row(
    contact_id: int,
    *,
    name: str = "Brandon Sweeney",
    email: str | None = "brandon@example.com",
    phone: str | None = "+19785550123",
) -> ContactDirectoryRow:
    first_name, _, last_name = name.partition(" ")
    return ContactDirectoryRow(
        id=contact_id,
        first_name=first_name,
        last_name=last_name,
        display_name=name,
        primary_email=email,
        primary_phone=phone,
        stage="lead",
        lead_backed=False,
        origins=(ContactOriginFilter.RECOVERED,),
        sources=(ContactSourceFilter.KW_COMMAND,),
        health_score=90,
        last_contacted_at=None,
        last_interaction_at=None,
        owner=None,
        assignee=None,
        tags=(ContactTagValue(id=7, name="VIP"),),
        birthday=None,
        anniversary=None,
        evidence_quality="complete",
    )


def _page(
    rows: tuple[ContactDirectoryRow, ...],
    *,
    total: int | None = None,
    page: int = 1,
    page_size: int = 25,
) -> ContactDirectoryPage:
    resolved_total = len(rows) if total is None else total
    return ContactDirectoryPage(
        rows=rows,
        total=resolved_total,
        page=page,
        page_size=page_size,
        page_count=(resolved_total + page_size - 1) // page_size,
        sort="name",  # type: ignore[arg-type]
        direction="asc",  # type: ignore[arg-type]
    )


def _app() -> FastAPI:
    from routers import agent_control_command

    app = FastAPI()
    app.include_router(
        agent_control_command.router,
        prefix="/api/v1/agent-control",
    )
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    return app


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer command-secret"}


def test_command_contracts_are_strict_and_limit_agent_pages_to_25() -> None:
    from schemas.agent_control_command import CommandContactsSearchRequest

    request = CommandContactsSearchRequest(
        query="brandon@example.com",
        stage="lead",
        tag_ids=[9, 7, 9],
        sources=["kw_command"],
        origins=["recovered"],
        page=2,
        page_size=25,
    )
    assert request.tag_ids == [7, 9]
    with pytest.raises(ValidationError):
        CommandContactsSearchRequest(page_size=26)
    with pytest.raises(ValidationError):
        CommandContactsSearchRequest.model_validate(
            {"page_size": 10, "send_email": True}
        )


@pytest.mark.asyncio
async def test_search_adapts_existing_command_directory_without_google_fallback() -> None:
    from schemas.agent_control_command import CommandContactsSearchRequest
    from services.agent_control_command import search_command_contacts

    db = SimpleNamespace()
    request = CommandContactsSearchRequest(
        query="978-555-0123",
        stage="lead",
        tag_ids=[7],
        sources=["kw_command"],
        origins=["recovered"],
        page_size=25,
    )
    directory = AsyncMock(return_value=_page((_row(41),), page_size=25))
    with patch("services.agent_control_command.list_contacts", directory):
        result = await search_command_contacts(db, request, now=NOW)

    directory.assert_awaited_once_with(
        db,
        ContactDirectoryFilters(
            query="978-555-0123",
            stage="lead",
            tag_ids=(7,),
            sources=(ContactSourceFilter.KW_COMMAND,),
            origins=(ContactOriginFilter.RECOVERED,),
            page=1,
            page_size=25,
        ),
        now=NOW,
    )
    assert result.total == 1
    assert result.contacts[0].contact_id == 41
    assert result.contacts[0].primary_email == "brandon@example.com"
    assert result.contacts[0].tag_names == ["VIP"]


@pytest.mark.asyncio
async def test_audience_preview_is_exact_stable_masked_and_never_persists() -> None:
    from schemas.agent_control_command import CommandContactAudiencePreviewRequest
    from services.agent_control_command import preview_command_contact_audience

    rows = tuple(_row(index, name=f"Person {index}") for index in range(1, 102))

    async def directory(_db, filters, *, now):
        assert now == NOW
        start = (filters.page - 1) * filters.page_size
        page_rows = rows[start : start + filters.page_size]
        return _page(
            page_rows,
            total=len(rows),
            page=filters.page,
            page_size=filters.page_size,
        )

    db = SimpleNamespace(add=pytest.fail, flush=pytest.fail, commit=pytest.fail)
    request = CommandContactAudiencePreviewRequest(stage="lead", tag_ids=[7])
    with patch("services.agent_control_command.list_contacts", directory):
        first = await preview_command_contact_audience(db, request, now=NOW)
        second = await preview_command_contact_audience(db, request, now=NOW)

    assert first == second
    assert first.exact_count == 101
    assert len(first.audience_checksum) == 64
    assert len(first.samples) == 5
    assert first.samples[0].display_name == "P*** 1***"
    assert first.samples[0].primary_email == "***@example.com"
    assert first.samples[0].primary_phone == "***-***-0123"
    assert "brandon@example.com" not in repr(first.samples)


def test_protected_routes_are_read_only_and_write_content_free_audits() -> None:
    from schemas.agent_control_command import (
        CommandContactAudiencePreviewResponse,
        CommandContactAudienceSample,
        CommandContactResult,
        CommandContactsSearchResponse,
    )

    app = _app()
    paths = {route.path for route in app.routes}
    assert paths >= {
        "/api/v1/agent-control/crm/command-contacts/search",
        "/api/v1/agent-control/crm/command-contact-audiences/preview",
    }
    assert all("send" not in path and "draft" not in path for path in paths)

    client = TestClient(app)
    search_result = CommandContactsSearchResponse(
        contacts=[
            CommandContactResult(
                contact_id=41,
                display_name="Brandon Sweeney",
                primary_email="brandon@example.com",
                primary_phone="+19785550123",
                stage="lead",
                sources=["kw_command"],
                origins=["recovered"],
                tag_names=["VIP"],
            )
        ],
        total=1,
        page=1,
        page_size=25,
        page_count=1,
    )
    preview_result = CommandContactAudiencePreviewResponse(
        audience_ref="9ad04f43-adaf-5ef6-a17d-8f6d09df2401",
        audience_checksum="a" * 64,
        exact_count=1,
        samples=[
            CommandContactAudienceSample(
                display_name="B*** S***",
                primary_email="***@example.com",
                primary_phone="***-***-0123",
            )
        ],
    )
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch("middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "command-secret"),
        patch(
            "routers.agent_control_command.search_command_contacts",
            AsyncMock(return_value=search_result),
        ),
        patch(
            "routers.agent_control_command.preview_command_contact_audience",
            AsyncMock(return_value=preview_result),
        ),
        patch(
            "routers.agent_control_command.write_agent_audit",
            new_callable=AsyncMock,
        ) as audit,
    ):
        search_response = client.post(
            "/api/v1/agent-control/crm/command-contacts/search",
            headers=_headers(),
            json={"query": "private person", "page_size": 25},
        )
        preview_response = client.post(
            "/api/v1/agent-control/crm/command-contact-audiences/preview",
            headers=_headers(),
            json={"stage": "lead"},
        )

    assert search_response.status_code == 200
    assert preview_response.status_code == 200
    assert audit.await_count == 2
    assert "private person" not in repr(audit.await_args_list)
    assert "brandon@example.com" not in repr(audit.await_args_list)


def test_command_outage_is_sanitized_and_registry_has_only_read_actions() -> None:
    from routers.agent_control import AGENT_ACTIONS
    from services.agent_control_command import CommandContactsUnavailable

    ids = [action.id for action in AGENT_ACTIONS]
    assert "crm.command_contacts.search" in ids
    assert "crm.command_contact_audiences.preview" in ids
    assert not any(action.startswith("crm.command_contacts.send") for action in ids)

    app = _app()
    client = TestClient(app)
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch("middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "command-secret"),
        patch(
            "routers.agent_control_command.search_command_contacts",
            AsyncMock(
                side_effect=CommandContactsUnavailable("command_contacts_unavailable")
            ),
        ),
    ):
        response = client.post(
            "/api/v1/agent-control/crm/command-contacts/search",
            headers=_headers(),
            json={"query": "sensitive@example.com"},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "command_contacts_unavailable"}
    assert "sensitive@example.com" not in response.text
