from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from database import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from services.command_contact_contracts import (
    ContactCelebrationRow,
    ContactCelebrations,
    ContactDirectoryCursorPage,
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


def _cursor_page(
    rows: tuple[ContactDirectoryRow, ...],
    *,
    total: int | None = None,
    next_after_id: int | None = None,
    upper_bound_id: int = 0,
) -> ContactDirectoryCursorPage:
    return ContactDirectoryCursorPage(
        rows=rows,
        total=len(rows) if total is None else total,
        next_after_id=next_after_id,
        upper_bound_id=upper_bound_id,
        has_more=next_after_id is not None,
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


def test_command_contracts_are_strict_and_limit_cursor_pages_to_25() -> None:
    from schemas.agent_control_command import CommandContactsSearchRequest

    request = CommandContactsSearchRequest(
        query="brandon@example.com",
        stage="lead",
        tag_ids=[9, 7, 9],
        sources=["kw_command"],
        origins=["recovered"],
        page_size=25,
    )
    assert request.tag_ids == [7, 9]
    with pytest.raises(ValidationError):
        CommandContactsSearchRequest(page_size=26)
    with pytest.raises(ValidationError):
        CommandContactsSearchRequest.model_validate(
            {"page_size": 10, "send_email": True}
        )
    with pytest.raises(ValidationError):
        CommandContactsSearchRequest.model_validate({"page": 2})


def test_celebration_preview_contract_requires_a_strict_month_and_kind() -> None:
    from schemas.agent_control_command import (
        CommandContactCelebrationsPreviewRequest,
        CommandContactCelebrationsPreviewResponse,
    )

    request = CommandContactCelebrationsPreviewRequest(month=9)
    assert request.include_birthdays is True
    assert request.include_home_anniversaries is True
    for invalid in (0, 13, True, "9"):
        with pytest.raises(ValidationError):
            CommandContactCelebrationsPreviewRequest.model_validate({"month": invalid})
    with pytest.raises(ValidationError):
        CommandContactCelebrationsPreviewRequest(
            month=9,
            include_birthdays=False,
            include_home_anniversaries=False,
        )
    with pytest.raises(ValidationError):
        CommandContactCelebrationsPreviewRequest.model_validate(
            {"month": 9, "kind": "birthday"}
        )
    with pytest.raises(ValidationError):
        CommandContactCelebrationsPreviewResponse(
            month=9,
            include_birthdays=True,
            include_home_anniversaries=True,
            audience_ref="9ad04f43-adaf-5ef6-a17d-8f6d09df2401",
            audience_checksum="a" * 64,
            birthday_count=2,
            home_anniversary_count=1,
            union_count=4,
            address_ready_count=2,
            missing_address_count=1,
            reconciliation_status="reconciled",
            samples=[],
        )


@pytest.mark.asyncio
async def test_search_adapts_existing_command_directory_without_google_fallback() -> (
    None
):
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
    directory = AsyncMock(return_value=_cursor_page((_row(41),), upper_bound_id=41))
    with patch("services.agent_control_command.list_contacts_cursor", directory):
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
        after_id=None,
        upper_bound_id=None,
        now=NOW,
    )
    assert result.total == 1
    assert result.contacts[0].contact_id == 41
    assert result.contacts[0].primary_email == "brandon@example.com"
    assert result.contacts[0].tag_names == ["VIP"]
    assert result.next_cursor is None
    assert result.has_more is False


@pytest.mark.asyncio
async def test_search_cursor_is_stable_and_bound_to_the_original_filters() -> None:
    from schemas.agent_control_command import CommandContactsSearchRequest
    from services.agent_control_command import search_command_contacts

    db = SimpleNamespace()
    directory = AsyncMock(
        side_effect=(
            _cursor_page(
                (_row(41),),
                total=3,
                next_after_id=41,
                upper_bound_id=99,
            ),
            _cursor_page((_row(72), _row(99)), total=3, upper_bound_id=99),
        )
    )
    with patch("services.agent_control_command.list_contacts_cursor", directory):
        first = await search_command_contacts(
            db,
            CommandContactsSearchRequest(stage="lead", page_size=1),
            now=NOW,
        )
        assert first.next_cursor is not None
        second = await search_command_contacts(
            db,
            CommandContactsSearchRequest(
                stage="lead",
                page_size=2,
                cursor=first.next_cursor,
            ),
            now=NOW,
        )

    assert [contact.contact_id for contact in second.contacts] == [72, 99]
    assert directory.await_args_list[1].kwargs["after_id"] == 41
    assert directory.await_args_list[1].kwargs["upper_bound_id"] == 99

    with pytest.raises(ValueError, match="command_contacts_cursor_invalid"):
        await search_command_contacts(
            db,
            CommandContactsSearchRequest(
                stage="client",
                cursor=first.next_cursor,
            ),
            now=NOW,
        )


@pytest.mark.asyncio
async def test_audience_preview_is_exact_stable_masked_and_never_persists() -> None:
    from schemas.agent_control_command import CommandContactAudiencePreviewRequest
    from services.agent_control_command import preview_command_contact_audience

    rows = tuple(_row(index, name=f"Person {index}") for index in range(1, 102))

    async def directory(_db, filters, *, now):
        assert now == NOW
        assert db.execute.await_count >= 1
        start = (filters.page - 1) * filters.page_size
        page_rows = rows[start : start + filters.page_size]
        return _page(
            page_rows,
            total=len(rows),
            page=filters.page,
            page_size=filters.page_size,
        )

    db = SimpleNamespace(
        execute=AsyncMock(),
        add=pytest.fail,
        flush=pytest.fail,
        commit=pytest.fail,
    )
    request = CommandContactAudiencePreviewRequest(stage="lead", tag_ids=[7])
    with patch("services.agent_control_command.list_contacts", directory):
        first = await preview_command_contact_audience(db, request, now=NOW)
        second = await preview_command_contact_audience(db, request, now=NOW)

    assert first == second
    assert db.execute.await_count == 2
    assert all(
        str(call.args[0]) == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
        for call in db.execute.await_args_list
    )
    assert first.exact_count == 101
    assert len(first.audience_checksum) == 64
    assert len(first.samples) == 5
    assert first.samples[0].display_name == "P*** 1***"
    assert first.samples[0].primary_email == "***@example.com"
    assert first.samples[0].primary_phone == "***-***-0123"
    assert "brandon@example.com" not in repr(first.samples)


@pytest.mark.asyncio
async def test_private_celebration_preview_preserves_names_and_counts() -> None:
    from schemas.agent_control_command import (
        CommandContactCelebrationsPreviewRequest,
    )
    from services.agent_control_command import preview_command_contact_celebrations

    celebrations = ContactCelebrations(
        birthdays=(
            ContactCelebrationRow(
                contact_id=41,
                display_name="Brandon Sweeney",
                kind="birthday",
                month=9,
                day=4,
                year=1989,
                year_quality="verified",
                origin="internal_crm",
            ),
            ContactCelebrationRow(
                contact_id=72,
                display_name="Avery Client",
                kind="birthday",
                month=9,
                day=14,
                year=None,
                year_quality="yearless",
                origin="recovered",
            ),
        ),
        anniversaries=(
            ContactCelebrationRow(
                contact_id=72,
                display_name="Avery Client",
                kind="anniversary",
                month=9,
                day=21,
                year=2017,
                year_quality="verified",
                origin="recovered",
            ),
            ContactCelebrationRow(
                contact_id=99,
                display_name="Casey Homeowner",
                kind="anniversary",
                month=9,
                day=27,
                year=None,
                year_quality="yearless",
                origin="recovered",
            ),
        ),
    )
    db = SimpleNamespace(
        execute=AsyncMock(),
        add=pytest.fail,
        flush=pytest.fail,
        commit=pytest.fail,
    )
    with (
        patch(
            "services.agent_control_command.list_contact_celebrations",
            AsyncMock(return_value=celebrations),
        ) as directory,
        patch(
            "services.agent_control_command._address_ready_contact_ids",
            AsyncMock(return_value={41, 99}),
        ),
        patch(
            "services.agent_control_command._contact_reconciliation_status",
            AsyncMock(return_value="reconciled"),
        ),
    ):
        both = await preview_command_contact_celebrations(
            db,
            CommandContactCelebrationsPreviewRequest(month=9),
        )
        repeated = await preview_command_contact_celebrations(
            db,
            CommandContactCelebrationsPreviewRequest(month=9),
        )
        birthdays = await preview_command_contact_celebrations(
            db,
            CommandContactCelebrationsPreviewRequest(
                month=9,
                include_home_anniversaries=False,
            ),
        )

    assert both == repeated
    assert directory.await_count == 3
    assert all(call.kwargs == {"month": 9} for call in directory.await_args_list)
    assert db.execute.await_count == 3
    assert all(
        str(call.args[0]) == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
        for call in db.execute.await_args_list
    )
    assert (both.birthday_count, both.home_anniversary_count, both.union_count) == (
        2,
        2,
        3,
    )
    assert (both.address_ready_count, both.missing_address_count) == (2, 1)
    assert both.reconciliation_status == "reconciled"
    assert len(both.audience_checksum) == 64
    assert len(both.samples) == 3
    assert both.samples[0].display_name == "Brandon Sweeney"
    assert both.samples[1].display_name == "Avery Client"
    assert [item.kind for item in both.samples[1].celebrations] == [
        "birthday",
        "home_anniversary",
    ]
    assert [item.day for item in both.samples[1].celebrations] == [14, 21]
    assert both.samples[1].address_ready is False
    assert both.samples[2].display_name == "Casey Homeowner"
    assert "1989" not in repr(both.samples)
    assert birthdays.home_anniversary_count == 0
    assert birthdays.union_count == 2
    assert birthdays.address_ready_count == 1
    assert birthdays.audience_checksum != both.audience_checksum


def test_protected_routes_are_read_only_and_write_content_free_audits() -> None:
    from schemas.agent_control_command import (
        CommandContactAudiencePreviewResponse,
        CommandContactAudienceSample,
        CommandContactCelebrationOccurrence,
        CommandContactCelebrationSample,
        CommandContactCelebrationsPreviewResponse,
        CommandContactResult,
        CommandContactsSearchResponse,
    )

    app = _app()
    paths = {route.path for route in app.routes}
    assert paths >= {
        "/api/v1/agent-control/crm/command-contacts/search",
        "/api/v1/agent-control/crm/command-contact-audiences/preview",
        "/api/v1/agent-control/crm/command-contact-celebrations/preview",
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
        page_size=25,
        next_cursor=None,
        has_more=False,
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
    celebration_result = CommandContactCelebrationsPreviewResponse(
        month=9,
        include_birthdays=True,
        include_home_anniversaries=True,
        audience_ref="9ad04f43-adaf-5ef6-a17d-8f6d09df2401",
        audience_checksum="b" * 64,
        birthday_count=1,
        home_anniversary_count=1,
        union_count=1,
        address_ready_count=1,
        missing_address_count=0,
        reconciliation_status="reconciled",
        samples=[
            CommandContactCelebrationSample(
                display_name="Brandon Sweeney",
                celebrations=[
                    CommandContactCelebrationOccurrence(kind="birthday", day=4),
                    CommandContactCelebrationOccurrence(
                        kind="home_anniversary", day=21
                    ),
                ],
                address_ready=True,
            )
        ],
    )
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "command-secret"
        ),
        patch(
            "routers.agent_control_command.search_command_contacts",
            AsyncMock(return_value=search_result),
        ),
        patch(
            "routers.agent_control_command.preview_command_contact_audience",
            AsyncMock(return_value=preview_result),
        ),
        patch(
            "routers.agent_control_command.preview_command_contact_celebrations",
            AsyncMock(return_value=celebration_result),
        ),
        patch(
            "routers.agent_control_command.write_agent_audit_transactional",
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
        celebration_response = client.post(
            "/api/v1/agent-control/crm/command-contact-celebrations/preview",
            headers=_headers(),
            json={"month": 9},
        )

    assert search_response.status_code == 200
    assert preview_response.status_code == 200
    assert celebration_response.status_code == 200
    assert celebration_response.json()["union_count"] == 1
    assert (
        celebration_response.json()["samples"][0]["display_name"] == "Brandon Sweeney"
    )
    assert audit.await_count == 3
    assert "private person" not in repr(audit.await_args_list)
    assert "brandon@example.com" not in repr(audit.await_args_list)
    assert "Brandon Sweeney" not in repr(audit.await_args_list)
    assert "b" * 64 not in repr(audit.await_args_list)
    celebration_audit = audit.await_args_list[2].kwargs
    assert celebration_audit["request_meta"] == {
        "month": 9,
        "include_birthdays": True,
        "include_home_anniversaries": True,
    }
    assert celebration_audit["response_meta"] == {
        "audience_ref": "9ad04f43-adaf-5ef6-a17d-8f6d09df2401",
        "birthday_count": 1,
        "home_anniversary_count": 1,
        "union_count": 1,
        "address_ready_count": 1,
        "missing_address_count": 0,
        "reconciliation_status": "reconciled",
        "sample_count": 1,
    }


def test_command_outage_is_sanitized_and_registry_has_only_read_actions() -> None:
    from routers.agent_control import AGENT_ACTIONS
    from services.agent_control_command import CommandContactsUnavailable

    ids = [action.id for action in AGENT_ACTIONS]
    assert "crm.command_contacts.search" in ids
    assert "crm.command_contact_audiences.preview" in ids
    assert "crm.command_contact_celebrations.preview" in ids
    assert not any(action.startswith("crm.command_contacts.send") for action in ids)

    app = _app()
    client = TestClient(app)
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "command-secret"
        ),
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


def test_malformed_search_cursor_is_rejected_without_echoing_it() -> None:
    app = _app()
    client = TestClient(app)
    opaque = "structurally-valid-but-not-a-cursor"
    with (
        patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
        patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "command-secret"
        ),
    ):
        response = client.post(
            "/api/v1/agent-control/crm/command-contacts/search",
            headers=_headers(),
            json={"cursor": opaque},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "command_contacts_cursor_invalid"}
    assert opaque not in response.text
