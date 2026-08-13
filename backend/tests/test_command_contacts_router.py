"""Typed HTTP-boundary contracts for the focused Command Contacts router."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated

import pytest
import pytest_asyncio
from fastapi import FastAPI, Query
from fastapi.routing import APIRoute, Match
from fastapi.testclient import TestClient
from jose import jwt
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import settings
from database import Base, get_db
from main import app as main_app
from middleware import auth as auth_middleware
from middleware.auth import require_admin_subject
from models.booking import Booking
from models.command import CRMContact, CRMOpportunity, CRMOpportunityContact
from models.command_contacts import CRMContactMethod
from models.lead import Lead
from routers import command as command_router
from routers import command_contacts as contact_router
from routers import command_provenance as provenance_router
from schemas import command_contacts
from schemas.command_contacts import (
    ContactArtifactMetadataOut,
    ContactBoundaryModel,
    ContactBulkRequest,
    ContactCelebrationsOut,
    ContactCreateIn,
    ContactDetailOut,
    ContactDirectoryPageOut,
    ContactDirectoryQueryIn,
    ContactEvidenceOut,
    ContactImportIn,
    ContactImportRowIn,
    ContactMaterializedOut,
    ContactNoteCreateIn,
    ContactNoteOccurrenceOut,
    ContactOpportunityOccurrenceOut,
    ContactSavedSearchCreateIn,
    ContactSavedSearchOccurrenceOut,
    ContactSectionPageOut,
    ContactSmartPlanOccurrenceOut,
    ContactSourceMetadataOut,
    ContactSourceOnlyOut,
    ContactTaskOccurrenceOut,
    ContactTimelinePageOut,
    ContactUpdateIn,
    LegacyContactWorkspaceOut,
    canonical_saved_search_criteria,
)
from services.command_contact_contracts import (
    UNSET,
    CaptureQualityValue,
    ContactActorValue,
    ContactAddressValue,
    ContactArtifactMetadata,
    ContactBulkCommand,
    ContactBulkResult,
    ContactCaptureEvidence,
    ContactCelebrationRow,
    ContactCelebrations,
    ContactCelebrationValue,
    ContactCreateCommand,
    ContactDetail,
    ContactDirectoryFilters,
    ContactDirectoryPage,
    ContactDirectoryRow,
    ContactEvidence,
    ContactImportCommand,
    ContactImportResult,
    ContactImportRowCommand,
    ContactLegacySyncResult,
    ContactMutationResult,
    ContactNeighbors,
    ContactNoteCreateCommand,
    ContactOriginFilter,
    ContactRecoveredProfile,
    ContactSavedSearchCreateCommand,
    ContactSection,
    ContactSectionEvidence,
    ContactSectionPage,
    ContactSmartView,
    ContactSortKey,
    ContactSourceFilter,
    ContactSourceMetadata,
    ContactTagValue,
    ContactTimelineEntry,
    ContactTimelinePage,
    ContactUpdateCommand,
    ContactWorkspaceSummary,
    SortDirection,
    TimelineCursorV1,
    TimelineOrigin,
    encode_timeline_cursor,
)

NOW = datetime(2026, 8, 13, 14, 30, tzinfo=UTC)

READ_ROUTE_INVENTORY = (
    ("GET", "/contacts/directory"),
    ("GET", "/contacts"),
    ("GET", "/celebrations"),
    ("GET", "/contacts/{contact_id}"),
    ("GET", "/contacts/{contact_id}/neighbors"),
    ("GET", "/contacts/{contact_id}/workspace/summary"),
    ("GET", "/contacts/{contact_id}/workspace"),
    ("GET", "/contacts/{contact_id}/timeline"),
    ("GET", "/contacts/{contact_id}/opportunities"),
    ("GET", "/contacts/{contact_id}/smart-plans"),
    ("GET", "/contacts/{contact_id}/tasks"),
    ("GET", "/contacts/{contact_id}/notes"),
    ("GET", "/contacts/{contact_id}/saved-searches"),
    ("GET", "/contacts/{contact_id}/evidence"),
)

FULL_ROUTE_INVENTORY = (
    ("GET", "/contacts/directory"),
    ("POST", "/contacts/sync-leads"),
    ("POST", "/contacts/import"),
    ("POST", "/contacts/bulk"),
    ("GET", "/contacts"),
    ("POST", "/contacts"),
    ("GET", "/celebrations"),
    ("GET", "/contacts/{contact_id}"),
    ("PATCH", "/contacts/{contact_id}"),
    ("GET", "/contacts/{contact_id}/neighbors"),
    ("GET", "/contacts/{contact_id}/workspace/summary"),
    ("GET", "/contacts/{contact_id}/workspace"),
    ("GET", "/contacts/{contact_id}/timeline"),
    ("GET", "/contacts/{contact_id}/opportunities"),
    ("GET", "/contacts/{contact_id}/smart-plans"),
    ("GET", "/contacts/{contact_id}/tasks"),
    ("GET", "/contacts/{contact_id}/notes"),
    ("POST", "/contacts/{contact_id}/notes"),
    ("DELETE", "/contacts/{contact_id}/notes/{note_id}"),
    ("GET", "/contacts/{contact_id}/saved-searches"),
    ("POST", "/contacts/{contact_id}/saved-searches"),
    ("GET", "/contacts/{contact_id}/evidence"),
    ("POST", "/contacts/{contact_id}/tags/{tag_id}"),
    ("DELETE", "/contacts/{contact_id}/tags/{tag_id}"),
)

RETAINED_GLOBAL_ROUTE_INVENTORY = (
    ("POST", "/archive/import"),
    ("POST", "/tags"),
    ("GET", "/saved-searches"),
    ("DELETE", "/saved-searches/{search_id}"),
)

PROVENANCE_ROUTE_INVENTORY = (
    ("GET", "/source-records"),
    ("GET", "/source-records/{record_id}"),
    ("GET", "/entities/{entity_type}/{entity_id}/sources"),
    ("GET", "/reconciliation/runs"),
    ("GET", "/reconciliation/runs/latest"),
    ("GET", "/reconciliation/runs/{run_id}"),
)

MOVED_MONOLITH_NAMES = frozenset(
    {
        "contacts",
        "celebrations",
        "create_contact",
        "sync_legacy_leads",
        "import_contacts",
        "contact_detail",
        "update_contact",
        "contact_workspace",
        "assign_tag",
        "remove_tag",
        "create_contact_note",
        "delete_contact_note",
        "create_saved_search",
        "_contacts_by_normalized_emails",
    }
)


@pytest_asyncio.fixture
async def contact_router_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _query_test_client() -> TestClient:
    app = FastAPI()

    @app.get("/contacts")
    async def contacts(
        filters: Annotated[ContactDirectoryQueryIn, Query()],
    ) -> dict[str, object]:
        return filters.model_dump(mode="json")

    return TestClient(app)


def _directory_row() -> ContactDirectoryRow:
    return ContactDirectoryRow(
        id=7,
        first_name="Synthetic",
        last_name="Contact",
        display_name="Synthetic Contact",
        primary_email="synthetic@example.test",
        primary_phone=None,
        stage="lead",
        lead_backed=True,
        origins=(ContactOriginFilter.LEAD_BACKED,),
        sources=(ContactSourceFilter.INTERNAL_CRM, ContactSourceFilter.LEGACY_LEAD),
        health_score=81,
        last_contacted_at=None,
        last_interaction_at=NOW,
        owner=ContactActorValue(
            role="owner", provider_actor_id="actor-1", display_name="Owner"
        ),
        assignee=None,
        tags=(ContactTagValue(id=2, name="VIP"),),
        birthday=ContactCelebrationValue(
            month=8,
            day=13,
            year=1990,
            year_quality="verified",
            origin="internal_crm",
        ),
        anniversary=None,
        evidence_quality="complete",
    )


def test_directory_query_maps_every_repeated_filter_without_clamping():
    query = ContactDirectoryQueryIn(
        query=" Synthetic ",
        stage=" lead ",
        owner_actor_id=" owner-1 ",
        assignee_actor_id=" assignee-1 ",
        tag=[3, 1, 3],
        source=["legacy_lead", "kw_command"],
        origin=["legacy_only", "recovered"],
        health_min=10,
        health_max=90,
        birthday_month=8,
        anniversary_month=9,
        smart_view=ContactSmartView.RECENTLY_ACTIVE,
        sort=ContactSortKey.UPDATED_AT,
        direction="desc",
        page=3,
        page_size=100,
    )

    assert query.to_filters() == ContactDirectoryFilters(
        query="Synthetic",
        stage="lead",
        owner_actor_id="owner-1",
        assignee_actor_id="assignee-1",
        tag_ids=(1, 3),
        sources=(ContactSourceFilter.KW_COMMAND, ContactSourceFilter.LEGACY_LEAD),
        origins=(ContactOriginFilter.LEGACY_ONLY, ContactOriginFilter.RECOVERED),
        health_min=10,
        health_max=90,
        birthday_month=8,
        anniversary_month=9,
        smart_view=ContactSmartView.RECENTLY_ACTIVE,
        sort=ContactSortKey.UPDATED_AT,
        direction=SortDirection.DESC,
        page=3,
        page_size=100,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("page", 0),
        ("page", True),
        ("page_size", 0),
        ("page_size", 101),
        ("health_min", -1),
        ("health_max", 101),
        ("birthday_month", 13),
        ("anniversary_month", 0),
        ("tag", [1, True]),
    ],
)
def test_directory_query_rejects_invalid_integer_boundaries(field, value):
    with pytest.raises(ValidationError):
        ContactDirectoryQueryIn.model_validate({field: value})


def test_directory_query_accepts_canonical_numeric_url_values_and_repeated_tags():
    response = _query_test_client().get(
        "/contacts",
        params=[
            ("page", "2"),
            ("page_size", "100"),
            ("health_min", "10"),
            ("health_max", "90"),
            ("birthday_month", "8"),
            ("anniversary_month", "9"),
            ("tag", "3"),
            ("tag", "1"),
        ],
    )

    assert response.status_code == 200
    assert response.json() == {
        **ContactDirectoryQueryIn().model_dump(mode="json"),
        "page": 2,
        "page_size": 100,
        "health_min": 10,
        "health_max": 90,
        "birthday_month": 8,
        "anniversary_month": 9,
        "tag": [3, 1],
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("page", "+1"),
        ("page", "01"),
        ("page", "1.0"),
        ("page", "true"),
        ("page_size", " 50"),
        ("health_min", "-1"),
        ("birthday_month", "08"),
        ("tag", "+1"),
        ("tag", "01"),
        ("tag", "1.0"),
        ("tag", "true"),
    ],
)
def test_directory_query_rejects_noncanonical_numeric_url_values(field, value):
    response = _query_test_client().get("/contacts", params=[(field, value)])

    assert response.status_code == 422


def test_directory_page_and_detail_adapt_framework_neutral_dtos():
    row = _directory_row()
    page = ContactDirectoryPage(
        rows=(row,),
        total=1,
        page=1,
        page_size=50,
        page_count=1,
        sort="name",
        direction="asc",
    )
    detail = ContactDetail(
        contact=row,
        lead_id=9,
        recovered_profile=ContactRecoveredProfile(
            legal_name="Synthetic Contact",
            preferred_name=None,
            description=None,
            company="Example Brokerage",
            title=None,
            lead_source="internal",
            account_name=None,
            birthday=None,
            anniversary=None,
        ),
        addresses=(
            ContactAddressValue(
                id=4,
                address_type="home",
                formatted="1 Fixture Way",
                latitude=Decimal("42.1"),
                longitude=Decimal("-71.2"),
                source_record_id=18,
            ),
        ),
        ownership=row.owner and (row.owner,) or (),
        tags=row.tags,
    )

    page_out = ContactDirectoryPageOut.model_validate(page)
    detail_out = ContactDetailOut.model_validate(detail)

    assert page_out.model_dump(mode="json")["rows"][0]["id"] == 7
    assert page_out.model_dump(mode="json")["sort"] == "name"
    assert detail_out.lead_id == 9
    assert detail_out.addresses[0].latitude == Decimal("42.1")
    assert detail_out.model_dump(mode="json")["addresses"][0]["latitude"] == "42.1"
    assert detail_out.contact.primary_email == "synthetic@example.test"


def test_create_and_update_inputs_expose_only_editable_internal_fields():
    created = ContactCreateIn(
        first_name=" Synthetic ",
        last_name=" Contact ",
        email=" synthetic@example.test ",
        phone=None,
        stage=" lead ",
        birthday=date(1990, 8, 13),
        anniversary=None,
    ).to_command()
    updated = ContactUpdateIn(email=None, stage=" client ").to_command()

    assert (
        created.first_name,
        created.last_name,
        created.email,
        created.stage,
    ) == ("Synthetic", "Contact", "synthetic@example.test", "lead")
    assert updated.email is None
    assert updated.stage == "client"
    assert updated.first_name is UNSET

    for protected in (
        "lead_id",
        "recovered_profile",
        "source_record_id",
        "audit_event_id",
    ):
        with pytest.raises(ValidationError):
            ContactCreateIn.model_validate(
                {"first_name": "Synthetic", protected: "private"}
            )
        with pytest.raises(ValidationError):
            ContactUpdateIn.model_validate({protected: "private"})


@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        (ContactCreateIn, "birthday", datetime(2026, 8, 13, tzinfo=UTC)),
        (ContactCreateIn, "anniversary", "2026-08-13T00:00:00Z"),
        (ContactUpdateIn, "birthday", datetime(2026, 8, 13, tzinfo=UTC)),
        (ContactUpdateIn, "anniversary", "2026-08-13T00:00:00Z"),
    ],
)
def test_contact_inputs_reject_datetime_values_for_exact_date_fields(
    model, field, value
):
    payload = {"first_name": "Synthetic"} if model is ContactCreateIn else {}
    payload[field] = value

    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    "value",
    [
        0,
        86_400,
        -86_400,
        0.0,
        True,
        b"2026-08-13",
        datetime(2026, 8, 13, tzinfo=UTC),
        "2026-08-13T00:00:00Z",
    ],
)
@pytest.mark.parametrize("field", ["birthday", "anniversary"])
def test_all_contact_write_inputs_reject_non_exact_date_values(field, value):
    create_payload = {"first_name": "Synthetic", field: value}
    update_payload = {field: value}
    import_payload = {
        "contacts": [{"first_name": "Synthetic", field: value}],
    }

    for model, payload in (
        (ContactCreateIn, create_payload),
        (ContactUpdateIn, update_payload),
        (ContactImportIn, import_payload),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)


@pytest.mark.parametrize("value", [None, date(2026, 8, 13), "2026-08-13"])
def test_all_contact_write_inputs_accept_only_exact_date_values(value):
    assert ContactCreateIn(first_name="Synthetic", birthday=value).birthday == (
        date(2026, 8, 13) if value is not None else None
    )
    assert ContactUpdateIn(birthday=value).birthday == (
        date(2026, 8, 13) if value is not None else None
    )
    assert ContactImportIn(
        contacts=[{"first_name": "Synthetic", "birthday": value}]
    ).contacts[0].birthday == (date(2026, 8, 13) if value is not None else None)


def test_every_new_contact_boundary_forbids_extra_mapping_fields():
    assert ContactBoundaryModel.model_config["extra"] == "forbid"
    assert ContactBoundaryModel.model_config["from_attributes"] is True

    with pytest.raises(ValidationError):
        ContactDetailOut.model_validate(
            {
                "contact": {
                    **ContactDirectoryPageOut.model_validate(
                        ContactDirectoryPage(
                            rows=(_directory_row(),),
                            total=1,
                            page=1,
                            page_size=50,
                            page_count=1,
                            sort=ContactSortKey.NAME,
                            direction=SortDirection.ASC,
                        )
                    )
                    .rows[0]
                    .model_dump(),
                    "provider_contact_id": "private",
                },
                "lead_id": None,
                "recovered_profile": None,
                "addresses": [],
                "ownership": [],
                "tags": [],
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"first_name": None},
        {"last_name": None},
        {"stage": None},
        {"stage": "x" * 51},
    ],
)
def test_update_input_requires_an_effective_shaped_field(payload):
    with pytest.raises(ValidationError):
        ContactUpdateIn.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"contact_ids": [1, 1], "action": {"action": "set_stage", "stage": "lead"}},
        {"contact_ids": [True], "action": {"action": "set_stage", "stage": "lead"}},
        {"contact_ids": [0], "action": {"action": "set_stage", "stage": "lead"}},
        {"contact_ids": [1], "action": {"action": "set_stage", "stage": "x" * 51}},
        {"contact_ids": [1], "action": {"action": "add_tag", "tag_id": True}},
        {"contact_ids": [1], "action": {"action": "unknown", "tag_id": 2}},
    ],
)
def test_bulk_boundary_rejects_duplicates_nonintegers_and_unknown_actions(payload):
    with pytest.raises(ValidationError):
        ContactBulkRequest.model_validate(payload)


def test_bulk_boundary_builds_the_exact_discriminated_service_command():
    request = ContactBulkRequest.model_validate(
        {"contact_ids": [3, 1], "action": {"action": "add_tag", "tag_id": 7}}
    )

    command = request.to_command()

    assert command.contact_ids == (3, 1)
    assert command.action.action == "add_tag"
    assert command.action.tag_id == 7


def test_note_saved_search_and_import_inputs_build_strict_commands():
    note = ContactNoteCreateIn(body=" Follow up ").to_command()
    search_in = ContactSavedSearchCreateIn(
        name=" Priority ", criteria={"stage": "lead", "nested": {"b": 2, "a": 1}}
    )
    search = search_in.to_command()
    imported = ContactImportIn.model_validate(
        {
            "contacts": [
                {
                    "first_name": "Synthetic",
                    "last_name": "Contact",
                    "email": None,
                    "phone": None,
                    "stage": "lead",
                    "birthday": None,
                    "anniversary": None,
                }
            ]
        }
    ).to_command()

    assert note.body == "Follow up"
    assert search.name == "Priority"
    assert canonical_saved_search_criteria(search.criteria) == (
        '{"nested":{"a":1,"b":2},"stage":"lead"}'
    )
    assert len(imported.contacts) == 1


def test_import_row_builds_the_exact_import_row_command_type():
    row = ContactImportRowIn(first_name="Synthetic")

    command = row.to_command()
    imported = ContactImportIn(contacts=[row]).to_command()

    assert type(command) is ContactImportRowCommand
    assert type(imported.contacts[0]) is ContactImportRowCommand


def test_schema_exports_are_explicit_and_never_expose_service_commands():
    assert {
        "ContactDirectoryQueryIn",
        "ContactOccurrenceOut",
        "ContactSectionRowOut",
        "ContactBulkActionIn",
        "LegacyContactWorkspaceOut",
        "canonical_saved_search_criteria",
    } <= set(command_contacts.__all__)
    assert {
        "ContactCreateCommand",
        "ContactDirectoryFilters",
        "ContactBulkCommand",
    }.isdisjoint(command_contacts.__all__)


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Search", "criteria": {"score": float("nan")}},
        {"name": "Search", "criteria": {"score": float("inf")}},
        {"name": "Search", "criteria": []},
    ],
)
def test_saved_search_input_rejects_noncanonical_json(payload):
    with pytest.raises(ValidationError):
        ContactSavedSearchCreateIn.model_validate(payload)


def test_saved_search_input_rejects_non_string_mapping_keys():
    with pytest.raises(ValidationError):
        ContactSavedSearchCreateIn.model_validate(
            {"name": "Search", "criteria": {1: "private"}}
        )


def test_saved_search_input_pins_utf8_limit_and_frozen_command():
    boundary = ContactSavedSearchCreateIn(
        name="Search", criteria={"emoji": "😀", "nested": {"value": 1}}
    )
    command = boundary.to_command()

    assert canonical_saved_search_criteria(command.criteria) == (
        '{"emoji":"😀","nested":{"value":1}}'
    )
    with pytest.raises(TypeError):
        command.criteria["new"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        command.criteria["nested"]["value"] = 2  # type: ignore[index]

    exact_limit = ContactSavedSearchCreateIn(
        name="Search", criteria={"payload": "x" * 65_522}
    ).to_command()
    assert len(canonical_saved_search_criteria(exact_limit.criteria).encode()) == 65_536
    with pytest.raises(ValidationError):
        ContactSavedSearchCreateIn(name="Search", criteria={"payload": "x" * 65_523})


def test_import_input_enforces_nonempty_thousand_row_and_exact_row_boundaries():
    row = {
        "first_name": "Synthetic",
        "last_name": "",
        "email": None,
        "phone": None,
        "stage": "lead",
        "birthday": None,
        "anniversary": None,
    }
    assert len(ContactImportIn(contacts=[row] * 1_000).contacts) == 1_000
    with pytest.raises(ValidationError):
        ContactImportIn(contacts=[])
    with pytest.raises(ValidationError):
        ContactImportIn(contacts=[row] * 1_001)
    with pytest.raises(ValidationError):
        ContactImportIn.model_validate({"contacts": [{**row, "lead_id": 9}]})


@pytest.mark.parametrize("status", ["source_only", "materialized"])
@pytest.mark.parametrize(
    ("section", "value", "value_type", "entity_type"),
    [
        (
            "opportunities",
            {
                "kind": "opportunity",
                "title": "Synthetic opportunity",
                "stage": None,
                "value_cents": 0,
            },
            ContactOpportunityOccurrenceOut,
            "opportunity",
        ),
        (
            "smart_plans",
            {"kind": "smart_plan", "title": "Synthetic plan", "status": None},
            ContactSmartPlanOccurrenceOut,
            "smart_plan",
        ),
        (
            "tasks_to_do",
            {
                "kind": "task",
                "title": "Synthetic task",
                "description": None,
                "state": "to_do",
                "due_at": None,
            },
            ContactTaskOccurrenceOut,
            "task",
        ),
        (
            "notes",
            {"kind": "note", "title": "Visible note", "body": None},
            ContactNoteOccurrenceOut,
            "note",
        ),
        (
            "saved_searches",
            {
                "kind": "saved_search",
                "title": "Synthetic search",
                "criteria_summary": ["beds: 3"],
            },
            ContactSavedSearchOccurrenceOut,
            "saved_search",
        ),
    ],
)
def test_section_page_uses_both_nested_discriminators_for_every_value_kind(
    status, section, value, value_type, entity_type
):
    row = {
        "status": status,
        "source_record_id": 4,
        "source_key_hash": "a" * 64,
        "section": section,
        "occurrence_ordinal": 1,
        "capture_quality": "complete",
        "captured_at": NOW,
        "value": value,
    }
    if status == "materialized":
        row.update(entity_type=entity_type, entity_id=11)

    page = ContactSectionPageOut.model_validate(
        {"rows": [row], "total": 1, "page": 1, "page_size": 50, "page_count": 1}
    )

    expected_type = (
        ContactSourceOnlyOut if status == "source_only" else ContactMaterializedOut
    )
    assert isinstance(page.rows[0], expected_type)
    assert isinstance(page.rows[0].value, value_type)
    assert page.rows[0].value.kind == value["kind"]

    with pytest.raises(ValidationError):
        ContactSectionPageOut.model_validate(
            {
                "rows": [{**row, "status": "unknown"}],
                "total": 1,
                "page": 1,
                "page_size": 50,
                "page_count": 1,
            }
        )


def test_section_row_field_contracts_are_exact_and_nonduplicated():
    assert tuple(ContactSourceOnlyOut.model_fields) == (
        "status",
        "source_record_id",
        "source_key_hash",
        "section",
        "occurrence_ordinal",
        "capture_quality",
        "captured_at",
        "value",
    )
    assert tuple(ContactMaterializedOut.model_fields) == (
        *tuple(ContactSourceOnlyOut.model_fields),
        "entity_type",
        "entity_id",
    )


def test_timeline_page_keeps_recovered_timestamp_nullable():
    page = ContactTimelinePage(
        rows=(
            ContactTimelineEntry(
                key="recovered:1",
                origin=TimelineOrigin.RECOVERED,
                kind="timeline",
                title="Recovered event",
                body=None,
                outcome=None,
                occurred_at=None,
                source_record_id=8,
                entity_type="contact_timeline_event",
                entity_id=3,
            ),
        ),
        next_cursor=None,
        has_more=False,
    )

    output = ContactTimelinePageOut.model_validate(page)

    assert output.rows[0].occurred_at is None
    assert output.rows[0].origin == TimelineOrigin.RECOVERED


def test_evidence_output_is_exact_typed_and_artifact_href_is_id_derived():
    artifact = ContactArtifactMetadataOut(
        artifact_id=12,
        artifact_type="json",
        sha256="a" * 64,
        size_bytes=200,
        content_href="/api/v1/command/archive/artifacts/12/content",
    )
    source = ContactSourceMetadata(
        source_record_id=6,
        record_kind="contact_profile",
        evidence_level="observed_record",
        capture_quality=CaptureQualityValue.COMPLETE,
        captured_at=NOW,
        artifacts=(
            ContactArtifactMetadata(
                artifact_id=12,
                artifact_type="json",
                sha256="a" * 64,
                size_bytes=200,
                content_href="/api/v1/command/archive/artifacts/12/content",
            ),
        ),
    )
    cell = ContactSectionEvidence(
        capture_position_id=4,
        section=ContactSection.TIMELINE,
        source_record_id=7,
        capture_quality=CaptureQualityValue.COMPLETE,
        row_count=0,
        is_empty=True,
        limitation_codes=(),
    )
    capture = ContactCaptureEvidence(
        capture_position_id=4,
        capture_ordinal=1,
        source_record_id=5,
        capture_quality=CaptureQualityValue.COMPLETE,
        sections=(cell,),
    )
    evidence = ContactEvidence(
        contact_id=1,
        provider_contact_rows=317,
        resolved_provider_identities=317,
        coalesced_aliases=0,
        lead_backed_contacts=51,
        reviewed_overlaps=2,
        legacy_only_contacts=49,
        capture_positions=(capture,),
        section_matrix=(cell,),
        sources=(source,),
        capture_quality="complete",
    )

    output = ContactEvidenceOut.model_validate(evidence)

    assert output.provider_contact_rows == 317
    assert output.resolved_provider_identities == 317
    assert output.coalesced_aliases == 0
    assert (
        output.lead_backed_contacts,
        output.reviewed_overlaps,
        output.legacy_only_contacts,
    ) == (51, 2, 49)
    assert output.sources[0].artifacts == [artifact]

    with pytest.raises(ValidationError):
        ContactArtifactMetadataOut.model_validate(
            {**artifact.model_dump(), "content_href": "/private/archive/file"}
        )
    with pytest.raises(ValidationError):
        ContactArtifactMetadataOut.model_validate(
            {**artifact.model_dump(), "filename": "private.json"}
        )
    for invalid_zero in (False, 0.0, "0"):
        with pytest.raises(ValidationError):
            ContactEvidenceOut.model_validate(
                {**output.model_dump(), "coalesced_aliases": invalid_zero}
            )


def test_evidence_nested_sources_ignore_object_privates_but_reject_mapping_extras():
    artifact = SimpleNamespace(
        artifact_id=12,
        artifact_type="json",
        sha256="a" * 64,
        size_bytes=200,
        content_href="/api/v1/command/archive/artifacts/12/content",
        filename="private.json",
        content_bytes=b"private",
    )
    source = SimpleNamespace(
        source_record_id=6,
        record_kind="contact_profile",
        evidence_level="observed_record",
        capture_quality="complete",
        captured_at=NOW,
        artifacts=[artifact],
        source_key="private-source-key",
        payload_json='{"private":true}',
        source_path="/private/path",
        preview="private preview",
        provider_contact_id="private-provider-id",
    )

    output = ContactSourceMetadataOut.model_validate(source)
    serialized = output.model_dump_json()

    assert output.artifacts[0].content_href.endswith("/12/content")
    for secret in (
        "private.json",
        "private-source-key",
        "private-provider-id",
        "/private/path",
        "private preview",
        "payload_json",
        "content_bytes",
    ):
        assert secret not in serialized

    with pytest.raises(ValidationError):
        ContactSourceMetadataOut.model_validate(
            {**output.model_dump(), "payload_json": '{"private":true}'}
        )
    with pytest.raises(ValidationError):
        ContactArtifactMetadataOut.model_validate(
            {**output.artifacts[0].model_dump(), "content_bytes": b"private"}
        )


@pytest.mark.parametrize(
    ("model", "payload", "field"),
    [
        (
            ContactSectionPageOut,
            {"rows": [], "total": 0, "page": 1, "page_size": 50, "page_count": 0},
            "total",
        ),
        (
            ContactArtifactMetadataOut,
            {
                "artifact_id": 1,
                "artifact_type": "json",
                "sha256": "a" * 64,
                "size_bytes": 0,
                "content_href": "/api/v1/command/archive/artifacts/1/content",
            },
            "size_bytes",
        ),
    ],
)
def test_shared_id_and_count_aliases_reject_boolean_values(model, payload, field):
    with pytest.raises(ValidationError):
        model.model_validate({**payload, field: False})


def test_celebrations_output_adapts_both_kinds_without_fabrication():
    result = ContactCelebrations(
        birthdays=(
            ContactCelebrationRow(
                contact_id=1,
                display_name="Synthetic Contact",
                kind="birthday",
                month=8,
                day=13,
                year=None,
                year_quality="yearless",
                origin="recovered",
            ),
        ),
        anniversaries=(),
    )

    output = ContactCelebrationsOut.model_validate(result)

    assert output.birthdays[0].year is None
    assert output.birthdays[0].year_quality == "yearless"
    assert output.anniversaries == []


def test_legacy_workspace_boundary_has_only_the_existing_typed_wire_keys():
    output = LegacyContactWorkspaceOut.model_validate(
        {
            "contact": {
                "id": 1,
                "lead_id": 2,
                "first_name": "Synthetic",
                "last_name": "Contact",
                "email": None,
                "phone": None,
                "stage": "lead",
                "birthday": None,
                "anniversary": None,
            },
            "timeline": [],
            "tasks": [],
            "notes": [],
            "smart_plans": [],
            "opportunities": [],
            "saved_searches": [],
            "bookings": [],
            "tags": [],
        }
    )

    assert set(output.model_dump()) == {
        "contact",
        "timeline",
        "tasks",
        "notes",
        "smart_plans",
        "opportunities",
        "saved_searches",
        "bookings",
        "tags",
    }
    with pytest.raises(ValidationError):
        LegacyContactWorkspaceOut.model_validate(
            {**output.model_dump(), "private_payload": {"source_key": "hidden"}}
        )


def test_legacy_workspace_validates_every_populated_nested_wire_row():
    payload = {
        "contact": {
            "id": 1,
            "lead_id": 2,
            "first_name": "Synthetic",
            "last_name": "Contact",
            "email": None,
            "phone": None,
            "stage": "lead",
            "birthday": None,
            "anniversary": None,
        },
        "timeline": [{"id": 3, "kind": "call", "summary": "Called", "created_at": NOW}],
        "tasks": [
            {
                "id": 4,
                "title": "Follow up",
                "contact_id": 1,
                "description": "",
                "priority": "normal",
                "due_at": None,
                "status": "open",
            }
        ],
        "notes": [
            {
                "id": 5,
                "contact_id": 1,
                "body": "Visible note",
                "created_at": NOW,
                "updated_at": NOW,
            }
        ],
        "smart_plans": [{"id": 6, "plan_id": 7, "status": "active"}],
        "opportunities": [
            {
                "id": 8,
                "name": "Opportunity",
                "stage": "appointment",
                "value_cents": 100,
                "role": "buyer",
            }
        ],
        "saved_searches": [{"id": 9, "name": "Search", "criteria": '{"beds":3}'}],
        "bookings": [
            {
                "id": 10,
                "meeting_type": "consultation",
                "context": "buyer",
                "scheduled_at": NOW,
                "location": None,
                "notes": "",
            }
        ],
        "tags": [{"id": 11, "name": "VIP"}],
    }

    output = LegacyContactWorkspaceOut.model_validate(payload)

    assert output.timeline[0].id == 3
    assert output.tasks[0].contact_id == 1
    assert output.notes[0].body == "Visible note"
    assert output.smart_plans[0].plan_id == 7
    assert output.opportunities[0].value_cents == 100
    assert output.saved_searches[0].criteria == '{"beds":3}'
    assert output.bookings[0].scheduled_at == NOW
    assert output.tags[0].name == "VIP"

    for collection in (
        "timeline",
        "tasks",
        "notes",
        "smart_plans",
        "opportunities",
        "saved_searches",
        "bookings",
        "tags",
    ):
        invalid = {**payload, collection: [{**payload[collection][0], "private": True}]}
        with pytest.raises(ValidationError):
            LegacyContactWorkspaceOut.model_validate(invalid)


class _ReadOnlyBoundaryDB:
    no_autoflush = nullcontext()

    def add(self, _value):
        raise AssertionError("read route attempted DML")

    async def flush(self):
        raise AssertionError("read route attempted a flush")

    async def commit(self):
        raise AssertionError("read route attempted a commit")

    async def rollback(self):
        raise AssertionError("route attempted a rollback")

    def begin(self):
        raise AssertionError("route attempted a transaction")


def _focused_read_client() -> TestClient:
    app = FastAPI()
    app.include_router(contact_router.router)
    app.dependency_overrides[require_admin_subject] = lambda: "17"
    app.dependency_overrides[get_db] = lambda: _ReadOnlyBoundaryDB()
    return TestClient(app, raise_server_exceptions=False)


def _route_inventory(router) -> tuple[tuple[str, str], ...]:
    return tuple(
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods or ())
        if method != "HEAD"
    )


def _main_command_routes() -> tuple[APIRoute, ...]:
    return tuple(
        route
        for route in main_app.routes
        if isinstance(route, APIRoute)
        and route.path.startswith("/api/v1/command")
    )


def _mounted_inventory(routes: tuple[APIRoute, ...]) -> tuple[tuple[str, str], ...]:
    prefix = "/api/v1/command"
    return tuple(
        (method, route.path.removeprefix(prefix))
        for route in routes
        for method in sorted(route.methods or ())
        if method != "HEAD"
    )


def _first_main_endpoint(method: str, path: str):
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": (),
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    for route in main_app.routes:
        match, _ = route.matches(scope)
        if match is Match.FULL:
            return route.endpoint
    raise AssertionError(f"no route matched {method} {path}")


def test_main_mounts_cutover_routers_once_in_exact_order_and_ownership():
    routes = _main_command_routes()
    inventory = _mounted_inventory(routes)

    assert len(inventory) == 86
    assert inventory[:24] == FULL_ROUTE_INVENTORY
    assert inventory[-6:] == PROVENANCE_ROUTE_INVENTORY
    assert tuple(inventory.index(pair) for pair in RETAINED_GLOBAL_ROUTE_INVENTORY) == (
        38,
        39,
        40,
        41,
    )
    assert len(set(inventory)) == len(inventory)
    assert all(
        route.endpoint.__module__ == "routers.command_contacts"
        for route in routes[:24]
    )
    assert all(
        routes[index].endpoint.__module__ == "routers.command"
        for index in (38, 39, 40, 41)
    )
    assert all(
        route.endpoint.__module__ == "routers.command_provenance"
        for route in routes[-6:]
    )


def test_cutover_has_no_monolith_contact_aliases_or_legacy_owner_helper():
    assert MOVED_MONOLITH_NAMES.isdisjoint(vars(command_router))
    assert _route_inventory(command_router.router)[14:18] == (
        RETAINED_GLOBAL_ROUTE_INVENTORY
    )


def test_fresh_command_openapi_has_unique_routes_and_operation_ids():
    fresh = FastAPI()
    fresh.include_router(contact_router.router, prefix="/api/v1/command")
    fresh.include_router(command_router.router, prefix="/api/v1/command")
    fresh.include_router(provenance_router.router, prefix="/api/v1/command")

    routes = tuple(
        route for route in fresh.routes if isinstance(route, APIRoute)
    )
    inventory = tuple(
        (method, route.path)
        for route in routes
        for method in sorted(route.methods or ())
        if method != "HEAD"
    )
    assert len(inventory) == 86
    assert len(set(inventory)) == len(inventory)
    schema = fresh.openapi()
    operation_ids = [
        operation["operationId"]
        for path in schema["paths"].values()
        for method, operation in path.items()
        if method.lower() in {"get", "post", "patch", "delete", "put"}
    ]
    assert len(operation_ids) == 86
    assert len(set(operation_ids)) == len(operation_ids)
    expected_response_schemas = {
        ("/api/v1/command/contacts/directory", "get"): "ContactDirectoryPageOut",
        ("/api/v1/command/contacts/sync-leads", "post"): "ContactLegacySyncResultOut",
        ("/api/v1/command/contacts/import", "post"): "ContactImportResultOut",
        ("/api/v1/command/contacts/bulk", "post"): "ContactBulkResultOut",
        ("/api/v1/command/contacts/{contact_id}", "get"): "ContactDetailOut",
    }
    for (path, method), model_name in expected_response_schemas.items():
        response_schema = schema["paths"][path][method]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema["$ref"] == f"#/components/schemas/{model_name}"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/command/contacts/directory"),
        ("POST", "/api/v1/command/contacts/import"),
        ("POST", "/api/v1/command/contacts/sync-leads"),
        ("POST", "/api/v1/command/contacts/bulk"),
    ],
)
def test_main_static_contact_paths_dispatch_to_focused_router(method, path):
    endpoint = _first_main_endpoint(method, path)

    assert endpoint.__module__ == "routers.command_contacts"


def test_main_focused_route_decodes_admin_token_once(monkeypatch):
    decode_calls = 0
    real_decode = auth_middleware.jwt.decode

    def counted_decode(*args, **kwargs):
        nonlocal decode_calls
        decode_calls += 1
        return real_decode(*args, **kwargs)

    async def fake_list_contacts(_db, filters, *, now):
        assert now.tzinfo is UTC
        return ContactDirectoryPage(
            rows=(),
            total=0,
            page=filters.page,
            page_size=filters.page_size,
            page_count=0,
            sort=filters.sort,
            direction=filters.direction,
        )

    token = jwt.encode(
        {
            "sub": "17",
            "token_type": "admin_session",
            "scope": "admin",
            "exp": int(datetime.now(UTC).timestamp()) + 300,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    monkeypatch.setattr(auth_middleware.jwt, "decode", counted_decode)
    monkeypatch.setattr(contact_router, "list_contacts", fake_list_contacts)
    main_app.dependency_overrides[get_db] = lambda: _ReadOnlyBoundaryDB()
    try:
        response = TestClient(main_app, raise_server_exceptions=False).get(
            "/api/v1/command/contacts/directory",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        main_app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert decode_calls == 1


def test_focused_router_declares_exact_ordered_inventory_without_global_auth():
    assert contact_router.router.dependencies == []
    assert _route_inventory(contact_router.router) == FULL_ROUTE_INVENTORY
    for route in contact_router.router.routes:
        assert isinstance(route, APIRoute)
        assert require_admin_subject in {
            dependency.call for dependency in route.dependant.dependencies
        }


def test_focused_read_openapi_pins_required_parameters_and_numeric_bounds():
    app = FastAPI()
    app.include_router(contact_router.router)
    paths = app.openapi()["paths"]

    detail_params = {
        item["name"]: item
        for item in paths["/contacts/{contact_id}"]["get"]["parameters"]
    }
    assert detail_params["contact_id"] == {
        "name": "contact_id",
        "in": "path",
        "required": True,
        "schema": {
            "type": "integer",
            "exclusiveMinimum": 0,
            "title": "Contact Id",
        },
    }

    legacy_params = {
        item["name"]: item for item in paths["/contacts"]["get"]["parameters"]
    }
    assert legacy_params["limit"]["schema"] == {
        "type": "integer",
        "maximum": 100,
        "minimum": 1,
        "default": 50,
        "title": "Limit",
    }
    assert legacy_params["offset"]["schema"] == {
        "type": "integer",
        "minimum": 0,
        "default": 0,
        "title": "Offset",
    }

    task_params = {
        item["name"]: item
        for item in paths["/contacts/{contact_id}/tasks"]["get"]["parameters"]
    }
    assert task_params["state"]["required"] is True
    assert task_params["state"]["schema"] == {
        "type": "array",
        "items": {
            "enum": ["to_do", "completed", "archived"],
            "type": "string",
        },
        "title": "State",
    }
    assert task_params["page"]["schema"]["minimum"] == 1
    assert task_params["page_size"]["schema"]["minimum"] == 1
    assert task_params["page_size"]["schema"]["maximum"] == 100

    month = {
        item["name"]: item for item in paths["/celebrations"]["get"]["parameters"]
    }["month"]
    assert month["required"] is True
    assert month["schema"]["minimum"] == 1
    assert month["schema"]["maximum"] == 12


def test_directory_read_forwards_every_filter_and_never_writes(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_list_contacts(_db, filters, *, now):
        captured.update(filters=filters, now=now)
        return ContactDirectoryPage(
            rows=(),
            total=0,
            page=filters.page,
            page_size=filters.page_size,
            page_count=0,
            sort=filters.sort,
            direction=filters.direction,
        )

    monkeypatch.setattr(contact_router, "list_contacts", fake_list_contacts)
    response = _focused_read_client().get(
        "/contacts/directory",
        params=[
            ("query", "Synthetic"),
            ("stage", "lead"),
            ("owner_actor_id", "17"),
            ("assignee_actor_id", "18"),
            ("tag", "3"),
            ("tag", "1"),
            ("source", "kw_command"),
            ("origin", "recovered"),
            ("health_min", "10"),
            ("health_max", "90"),
            ("birthday_month", "8"),
            ("anniversary_month", "9"),
            ("smart_view", "recently_active"),
            ("sort", "updated_at"),
            ("direction", "desc"),
            ("page", "2"),
            ("page_size", "25"),
        ],
    )

    assert response.status_code == 200
    assert response.json()["rows"] == []
    filters = captured["filters"]
    assert filters == ContactDirectoryFilters(
        query="Synthetic",
        stage="lead",
        owner_actor_id="17",
        assignee_actor_id="18",
        tag_ids=(1, 3),
        sources=(ContactSourceFilter.KW_COMMAND,),
        origins=(ContactOriginFilter.RECOVERED,),
        health_min=10,
        health_max=90,
        birthday_month=8,
        anniversary_month=9,
        smart_view=ContactSmartView.RECENTLY_ACTIVE,
        sort=ContactSortKey.UPDATED_AT,
        direction=SortDirection.DESC,
        page=2,
        page_size=25,
    )
    assert captured["now"].tzinfo is UTC


def test_legacy_contact_read_forwards_exact_unclamped_window(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_legacy(_db, **values):
        captured.update(values)
        return [
            SimpleNamespace(
                id=7,
                first_name="Raw",
                last_name="Contact",
                email=" RAW@Example.Test ",
                phone=" raw phone ",
                lead_id=9,
                birthday=None,
                anniversary=None,
                stage=" lead ",
            )
        ]

    monkeypatch.setattr(contact_router, "_list_legacy_contacts", fake_legacy)
    response = _focused_read_client().get(
        "/contacts",
        params={
            "limit": "100",
            "offset": "99",
            "query": " Raw ",
            "stage": " lead ",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "limit": 100,
        "offset": 99,
        "query": " Raw ",
        "stage": " lead ",
    }
    assert response.json()[0] == {
        "id": 7,
        "first_name": "Raw",
        "last_name": "Contact",
        "email": " RAW@Example.Test ",
        "phone": " raw phone ",
        "lead_id": 9,
        "birthday": None,
        "anniversary": None,
        "stage": " lead ",
    }


@pytest.mark.parametrize(
    "params",
    [
        {"limit": "0"},
        {"limit": "101"},
        {"offset": "-1"},
        {"limit": "true"},
        {"offset": "1.5"},
    ],
)
def test_legacy_contact_read_rejects_invalid_windows_before_service(
    monkeypatch, params
):
    called = False

    async def fake_legacy(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(contact_router, "_list_legacy_contacts", fake_legacy)
    response = _focused_read_client().get("/contacts", params=params)

    assert response.status_code == 422
    assert called is False


def test_celebration_detail_neighbors_summary_and_evidence_delegate(monkeypatch):
    calls: list[tuple[str, object]] = []

    async def fake_celebrations(_db, *, month):
        calls.append(("celebrations", month))
        return ContactCelebrations(birthdays=(), anniversaries=())

    async def fake_detail(_db, contact_id):
        calls.append(("detail", contact_id))
        return ContactDetail(
            contact=_directory_row(),
            lead_id=9,
            recovered_profile=None,
            addresses=(),
            ownership=(),
            tags=(),
        )

    async def fake_neighbors(_db, contact_id, filters, *, now):
        calls.append(("neighbors", (contact_id, filters.page, now.tzinfo)))
        return ContactNeighbors(previous_contact_id=6, next_contact_id=8)

    async def fake_summary(_db, contact_id):
        calls.append(("summary", contact_id))
        return ContactWorkspaceSummary(1, 2, 3, 4, 5, 6, 7, 8)

    async def fake_evidence(_db, contact_id):
        calls.append(("evidence", contact_id))
        return ContactEvidence(
            contact_id=contact_id,
            provider_contact_rows=0,
            resolved_provider_identities=0,
            coalesced_aliases=0,
            lead_backed_contacts=0,
            reviewed_overlaps=0,
            legacy_only_contacts=0,
            capture_positions=(),
            section_matrix=(),
            sources=(),
            capture_quality="limitation",
        )

    monkeypatch.setattr(contact_router, "list_contact_celebrations", fake_celebrations)
    monkeypatch.setattr(contact_router, "get_contact_detail", fake_detail)
    monkeypatch.setattr(contact_router, "get_contact_neighbors", fake_neighbors)
    monkeypatch.setattr(contact_router, "get_contact_workspace_summary", fake_summary)
    monkeypatch.setattr(contact_router, "get_contact_evidence", fake_evidence)
    client = _focused_read_client()

    assert client.get("/celebrations", params={"month": "8"}).status_code == 200
    assert client.get("/contacts/7").json()["lead_id"] == 9
    assert client.get("/contacts/7/neighbors", params={"page": "2"}).json() == {
        "previous_contact_id": 6,
        "next_contact_id": 8,
    }
    assert client.get("/contacts/7/workspace/summary").json() == {
        "open_tasks": 1,
        "completed_tasks": 2,
        "archived_tasks": 3,
        "active_smart_plans": 4,
        "opportunities": 5,
        "notes": 6,
        "saved_searches": 7,
        "bookings": 8,
    }
    assert client.get("/contacts/7/evidence").json()["capture_quality"] == (
        "limitation"
    )
    assert calls == [
        ("celebrations", 8),
        ("detail", 7),
        ("neighbors", (7, 2, UTC)),
        ("summary", 7),
        ("evidence", 7),
    ]


def test_timeline_forwards_cursor_and_section_reads_map_exact_enums(monkeypatch):
    calls: list[tuple[object, ...]] = []

    async def fake_timeline(_db, contact_id, *, cursor, page_size):
        calls.append(("timeline", contact_id, cursor, page_size))
        return ContactTimelinePage(rows=(), next_cursor=None, has_more=False)

    async def fake_section(_db, contact_id, section, *, page, page_size):
        calls.append(("section", contact_id, section, page, page_size))
        return ContactSectionPage(
            rows=(), total=0, page=page, page_size=page_size, page_count=0
        )

    monkeypatch.setattr(contact_router, "list_contact_timeline", fake_timeline)
    monkeypatch.setattr(contact_router, "list_contact_section", fake_section)
    client = _focused_read_client()

    cursor = encode_timeline_cursor(TimelineCursorV1(0, NOW, 1, 999))
    assert (
        client.get(
            "/contacts/7/timeline",
            params={"cursor": cursor, "page_size": "25"},
        ).status_code
        == 200
    )
    section_paths = (
        ("opportunities", None, ContactSection.OPPORTUNITIES),
        ("smart-plans", None, ContactSection.SMART_PLANS),
        ("tasks", "to_do", ContactSection.TASKS_TO_DO),
        ("tasks", "completed", ContactSection.TASKS_COMPLETED),
        ("tasks", "archived", ContactSection.TASKS_ARCHIVED),
        ("notes", None, ContactSection.NOTES),
        ("saved-searches", None, ContactSection.SAVED_SEARCHES),
    )
    for path, state, _section in section_paths:
        params = {"page": "2", "page_size": "25"}
        if state is not None:
            params["state"] = state
        response = client.get(f"/contacts/7/{path}", params=params)
        assert response.status_code == 200

    assert calls == [
        ("timeline", 7, cursor, 25),
        *[("section", 7, section, 2, 25) for _path, _state, section in section_paths],
    ]


def test_malformed_timeline_cursor_is_rejected_before_service(monkeypatch):
    called = False

    async def fake_timeline(*_args, **_kwargs):
        nonlocal called
        called = True
        return ContactTimelinePage(rows=(), next_cursor=None, has_more=False)

    monkeypatch.setattr(contact_router, "list_contact_timeline", fake_timeline)
    response = _focused_read_client().get(
        "/contacts/7/timeline", params={"cursor": "not-a-valid-cursor"}
    )

    assert response.status_code == 422
    assert called is False


@pytest.mark.parametrize(
    "params",
    [
        [],
        [("state", "unknown")],
        [("state", "to_do"), ("state", "to_do")],
        [("state", "to_do"), ("state", "completed")],
    ],
)
def test_task_read_requires_exactly_one_known_state(monkeypatch, params):
    called = False

    async def fake_section(*_args, **_kwargs):
        nonlocal called
        called = True
        return ContactSectionPage(rows=(), total=0, page=1, page_size=50, page_count=0)

    monkeypatch.setattr(contact_router, "list_contact_section", fake_section)
    response = _focused_read_client().get("/contacts/7/tasks", params=params)

    assert response.status_code == 422
    assert called is False


@pytest.mark.parametrize(
    "path",
    [
        "/contacts/7/notes/01",
        "/contacts/7/notes/%2B1",
        "/contacts/7/notes/0",
        "/contacts/7/tags/01",
        "/contacts/7/tags/%2B1",
        "/contacts/7/tags/0",
    ],
)
def test_nested_mutation_path_ids_reject_noncanonical_values_before_service(
    monkeypatch, path
):
    called = False

    async def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        contact_router,
        "contact_service",
        SimpleNamespace(
            delete_contact_note=fail_if_called,
            assign_contact_tag=fail_if_called,
        ),
    )
    response = _focused_read_client().request(
        "DELETE" if "/notes/" in path else "POST", path
    )

    assert response.status_code == 422
    assert called is False


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (contact_router.ContactNotFound("private-provider-id"), 404),
        (contact_router.TimelineContactNotFound("private-provider-id"), 404),
        (contact_router.ContactNotInDirectory("private-provider-id"), 409),
        (contact_router.ContactDataIntegrityError("private-provider-id"), 409),
        (contact_router.ContactLinkConflict("private-provider-id"), 409),
        (contact_router.ContactTimelineIntegrityError("private-provider-id"), 409),
        (contact_router.ContactSectionUnsupported("private-provider-id"), 422),
        (
            contact_router.HTTPException(418, detail="private-provider-id"),
            500,
        ),
        (RuntimeError("private-provider-id"), 500),
    ],
)
def test_read_error_mapping_is_exact_and_privacy_safe(
    monkeypatch, error, expected_status
):
    async def fail(_db, _contact_id):
        raise error

    monkeypatch.setattr(contact_router, "get_contact_detail", fail)
    response = _focused_read_client().get("/contacts/7")

    assert response.status_code == expected_status
    assert "private-provider-id" not in response.text


def test_legacy_workspace_route_preserves_rich_arrays(monkeypatch):
    async def fake_workspace(_db, *, contact_id):
        assert contact_id == 7
        return {
            "contact": {
                "id": 7,
                "lead_id": 9,
                "first_name": "Raw",
                "last_name": "Contact",
                "email": None,
                "phone": None,
                "stage": "lead",
                "birthday": None,
                "anniversary": None,
            },
            "timeline": [],
            "tasks": [],
            "notes": [],
            "smart_plans": [],
            "opportunities": [],
            "saved_searches": [],
            "bookings": [],
            "tags": [],
        }

    monkeypatch.setattr(contact_router, "_legacy_contact_workspace", fake_workspace)
    response = _focused_read_client().get("/contacts/7/workspace")

    assert response.status_code == 200
    assert tuple(response.json()) == (
        "contact",
        "timeline",
        "tasks",
        "notes",
        "smart_plans",
        "opportunities",
        "saved_searches",
        "bookings",
        "tags",
    )


@pytest.mark.parametrize(
    "path",
    [
        "/contacts/01",
        "/contacts/1.0",
        "/contacts/true",
        "/contacts/%2B1",
        "/contacts/%201",
        "/contacts/0",
        "/contacts/-1",
    ],
)
def test_contact_path_ids_reject_every_noncanonical_value_before_service(
    monkeypatch, path
):
    called = False

    async def fake_detail(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(contact_router, "get_contact_detail", fake_detail)
    response = _focused_read_client().get(path)

    assert response.status_code == 422
    assert called is False


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/celebrations", {"month": "08"}),
        ("/celebrations", {"month": "+8"}),
        ("/contacts", {"limit": "01"}),
        ("/contacts", {"offset": "+1"}),
        ("/contacts/1/timeline", {"page_size": "01"}),
        ("/contacts/1/notes", {"page": "1.0"}),
        ("/contacts/1/notes", {"page_size": "true"}),
    ],
)
def test_all_read_query_integers_reject_noncanonical_values_before_service(
    monkeypatch, path, params
):
    called = False

    async def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True

    for name in (
        "list_contact_celebrations",
        "_list_legacy_contacts",
        "list_contact_timeline",
        "list_contact_section",
    ):
        monkeypatch.setattr(contact_router, name, fail_if_called)
    response = _focused_read_client().get(path, params=params)

    assert response.status_code == 422
    assert called is False


def test_response_validation_occurs_inside_the_safe_boundary(monkeypatch, caplog):
    secret = "private-provider-value"

    async def invalid_detail(_db, _contact_id):
        return {
            "contact": {"id": 7, "provider_contact_id": secret},
            "lead_id": None,
            "recovered_profile": None,
            "addresses": [],
            "ownership": [],
            "tags": [],
        }

    monkeypatch.setattr(contact_router, "get_contact_detail", invalid_detail)
    response = _focused_read_client().get("/contacts/7")

    assert response.status_code == 500
    assert response.json() == {"detail": "Unable to load contact data"}
    assert secret not in response.text
    assert secret not in caplog.text


def test_request_adapter_errors_are_422_but_service_type_errors_are_500(monkeypatch):
    def bad_adapter(_self):
        raise ValueError("private-request-value")

    monkeypatch.setattr(ContactDirectoryQueryIn, "to_filters", bad_adapter)
    adapter_response = _focused_read_client().get("/contacts/directory")

    async def bad_service(*_args, **_kwargs):
        raise ValueError("private-service-value")

    monkeypatch.undo()
    monkeypatch.setattr(contact_router, "list_contacts", bad_service)
    service_response = _focused_read_client().get("/contacts/directory")

    assert adapter_response.status_code == 422
    assert "private-request-value" not in adapter_response.text
    assert service_response.status_code == 500
    assert "private-service-value" not in service_response.text


async def test_legacy_raw_list_is_one_exact_select_with_stable_ties_and_no_fallback(
    contact_router_db,
):
    contacts = [
        CRMContact(
            id=index,
            first_name=f"Raw {index}",
            last_name="Contact",
            email=None if index == 2 else f"raw-{index}@example.test",
            phone=None,
            stage="" if index == 2 else "lead",
            created_at=NOW,
        )
        for index in (1, 2, 3)
    ]
    contact_router_db.add_all(contacts)
    await contact_router_db.flush()
    contact_router_db.add(
        CRMContactMethod(
            contact_id=2,
            source_key="synthetic-method",
            kind="email",
            label="Email",
            raw_value="recovered@example.test",
            normalized_value="recovered@example.test",
            is_primary=True,
        )
    )
    await contact_router_db.flush()
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.split()))

    event.listen(contact_router_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        rows = await contact_router._list_legacy_contacts(
            contact_router_db,
            limit=2,
            offset=1,
            query="   ",
            stage=None,
        )
        empty_stage = await contact_router._list_legacy_contacts(
            contact_router_db,
            limit=100,
            offset=0,
            query=None,
            stage="",
        )
    finally:
        event.remove(
            contact_router_db.bind.sync_engine, "before_cursor_execute", capture
        )

    assert [row.id for row in rows] == [2, 1]
    assert rows[0].email is None
    assert [row.id for row in empty_stage] == [2]
    assert len(statements) == 2
    assert all(
        "ORDER BY crm_contacts.created_at DESC, crm_contacts.id DESC" in sql
        for sql in statements
    )
    assert all(" LIMIT ? OFFSET ?" in sql for sql in statements)
    assert "crm_contacts.stage = ?" in statements[1]


async def test_legacy_workspace_uses_exact_booking_ownership_and_two_opportunities(
    contact_router_db,
):
    lead = Lead(id=40, name="Lead", routing_status="lead")
    lead_contact = CRMContact(
        id=1,
        lead_id=40,
        first_name="Lead",
        last_name="Contact",
        email="owner@example.test",
        stage="lead",
    )
    other_owner = CRMContact(
        id=2,
        first_name="Other",
        last_name="Owner",
        email="duplicate@example.test",
        stage="lead",
    )
    ambiguous_owner = CRMContact(
        id=3,
        first_name="Ambiguous",
        last_name="Owner",
        email=" ＤＵＰＬＩＣＡＴＥ@Example.Test ",
        stage="lead",
    )
    contact_router_db.add_all([lead, lead_contact, other_owner, ambiguous_owner])
    await contact_router_db.flush()
    contact_router_db.add_all(
        [
            Booking(
                id=1,
                lead_id=40,
                name="Lead booking",
                email="lead@example.test",
                scheduled_at=NOW,
                meeting_type="phone",
                context="general",
                notes="",
            ),
            Booking(
                id=2,
                lead_id=None,
                name="Same email but not lead-owned",
                email="owner@example.test",
                scheduled_at=NOW,
                meeting_type="phone",
                context="general",
                notes="",
            ),
            Booking(
                id=3,
                lead_id=None,
                name="Ambiguous booking",
                email="duplicate@example.test",
                scheduled_at=NOW,
                meeting_type="phone",
                context="general",
                notes="",
            ),
        ]
    )
    opportunities = [
        CRMOpportunity(id=10, name="First", stage="active"),
        CRMOpportunity(id=11, name="Second", stage="offer"),
    ]
    contact_router_db.add_all(opportunities)
    await contact_router_db.flush()
    contact_router_db.add_all(
        [
            CRMOpportunityContact(opportunity_id=item.id, contact_id=1, role="client")
            for item in opportunities
        ]
    )
    await contact_router_db.flush()

    lead_workspace = await contact_router._legacy_contact_workspace(
        contact_router_db, contact_id=1
    )
    ambiguous_workspace = await contact_router._legacy_contact_workspace(
        contact_router_db, contact_id=2
    )

    assert [row["id"] for row in lead_workspace["bookings"]] == [1]
    opportunity_ids = [row["id"] for row in lead_workspace["opportunities"]]
    assert len(opportunity_ids) == 2
    assert sorted(opportunity_ids) == [10, 11]
    assert ambiguous_workspace["bookings"] == []


async def test_legacy_workspace_missing_lead_and_booking_drift_fail_safe(
    contact_router_db,
):
    missing_lead = CRMContact(
        id=1,
        lead_id=999,
        first_name="Missing",
        last_name="Lead",
        stage="lead",
    )
    contact_router_db.add(missing_lead)
    await contact_router_db.flush()

    with pytest.raises(contact_router.ContactTimelineIntegrityError):
        await contact_router._legacy_contact_workspace(contact_router_db, contact_id=1)

    lead = Lead(id=999, name="Now present", routing_status="lead")
    contact_router_db.add(lead)
    await contact_router_db.flush()
    booking = Booking(
        lead_id=999,
        name="Private booking",
        email="private@example.test",
        scheduled_at=NOW,
        meeting_type="phone",
        context="general",
        notes="",
    )
    contact_router_db.add(booking)
    await contact_router_db.flush()
    await contact_router_db.execute(
        Booking.__table__.update()
        .where(Booking.id == booking.id)
        .values(normalized_email="drift@example.test")
    )
    contact_router_db.expire_all()

    with pytest.raises(contact_router.ContactTimelineIntegrityError) as error:
        await contact_router._legacy_contact_workspace(contact_router_db, contact_id=1)
    assert "private@example.test" not in str(error.value)


async def test_legacy_workspace_revalidates_same_count_booking_email_drift(
    contact_router_db, monkeypatch
):
    contact_router_db.add_all(
        [
            Lead(id=40, name="Lead", routing_status="lead"),
            CRMContact(
                id=1,
                lead_id=40,
                first_name="Lead",
                last_name="Contact",
                email="owner@example.test",
                stage="lead",
            ),
        ]
    )
    await contact_router_db.flush()
    booking = Booking(
        id=1,
        lead_id=40,
        name="Booking",
        email="booking@example.test",
        scheduled_at=NOW,
        meeting_type="phone",
        context="general",
        notes="",
    )
    contact_router_db.add(booking)
    await contact_router_db.flush()

    async def count_then_corrupt(_db, _contact_id):
        await _db.execute(
            Booking.__table__.update()
            .where(Booking.id == booking.id)
            .values(email="private-raw-drift@example.test")
        )
        return 1

    monkeypatch.setattr(contact_router, "count_contact_bookings", count_then_corrupt)

    with pytest.raises(contact_router.ContactTimelineIntegrityError) as error:
        await contact_router._legacy_contact_workspace(contact_router_db, contact_id=1)
    assert "private-raw-drift@example.test" not in str(error.value)


async def test_legacy_workspace_revalidates_unique_owner_after_same_count(
    contact_router_db, monkeypatch
):
    contact_router_db.add(
        CRMContact(
            id=1,
            first_name="Unique",
            last_name="Owner",
            email="owner@example.test",
            stage="lead",
        )
    )
    await contact_router_db.flush()
    contact_router_db.add(
        Booking(
            id=1,
            lead_id=None,
            name="Booking",
            email="owner@example.test",
            scheduled_at=NOW,
            meeting_type="phone",
            context="general",
            notes="",
        )
    )
    await contact_router_db.flush()

    async def count_then_make_ambiguous(_db, _contact_id):
        _db.add(
            CRMContact(
                id=2,
                first_name="Private",
                last_name="Duplicate",
                email=" ＯＷＮＥＲ@Example.Test ",
                stage="lead",
            )
        )
        await _db.flush()
        return 1

    monkeypatch.setattr(
        contact_router, "count_contact_bookings", count_then_make_ambiguous
    )

    with pytest.raises(contact_router.ContactTimelineIntegrityError) as error:
        await contact_router._legacy_contact_workspace(contact_router_db, contact_id=1)
    assert "Private" not in str(error.value)


def _mutation_detail(contact_id: int = 7) -> ContactDetail:
    return ContactDetail(
        contact=replace(_directory_row(), id=contact_id),
        lead_id=91,
        recovered_profile=None,
        addresses=(),
        ownership=(),
        tags=(),
    )


def _raw_contact(contact_id: int = 7) -> SimpleNamespace:
    return SimpleNamespace(
        id=contact_id,
        first_name="Raw",
        last_name="Contact",
        email=None,
        phone=" raw phone ",
        lead_id=91,
        birthday=date(1990, 8, 13),
        anniversary=None,
        stage=" internal ",
    )


def _install_successful_mutation_services(monkeypatch, calls):
    async def sync(_db, *, actor_subject):
        calls.append(("sync", actor_subject, None))
        return ContactLegacySyncResult(
            created=2,
            timeline_backfilled=1,
            total_legacy_leads=3,
        )

    async def import_rows(_db, payload, *, actor_subject):
        assert isinstance(payload, ContactImportCommand)
        calls.append(("import", actor_subject, payload))
        return ContactImportResult(created=1, skipped_duplicates=1)

    async def bulk(_db, payload, *, actor_subject):
        assert isinstance(payload, ContactBulkCommand)
        calls.append(("bulk", actor_subject, payload))
        return ContactBulkResult(
            requested_contact_ids=(7,),
            actioned_contact_ids=(7,),
            action="set_stage",
        )

    async def create(_db, payload, *, actor_subject):
        assert isinstance(payload, ContactCreateCommand)
        calls.append(("create", actor_subject, payload))
        return _mutation_detail()

    async def update(_db, contact_id, payload, *, actor_subject):
        assert contact_id == 7
        assert isinstance(payload, ContactUpdateCommand)
        calls.append(("update", actor_subject, payload))
        return _mutation_detail(contact_id)

    async def create_note(_db, contact_id, payload, *, actor_subject):
        assert contact_id == 7
        assert isinstance(payload, ContactNoteCreateCommand)
        calls.append(("note_create", actor_subject, payload))
        return ContactMutationResult(7, 31, True, "contact_audit", 101)

    async def delete_note(_db, contact_id, note_id, *, actor_subject):
        assert (contact_id, note_id) == (7, 31)
        calls.append(("note_delete", actor_subject, note_id))
        return ContactMutationResult(7, 31, True, "contact_audit", 102)

    async def create_search(_db, contact_id, payload, *, actor_subject):
        assert contact_id == 7
        assert isinstance(payload, ContactSavedSearchCreateCommand)
        calls.append(("search_create", actor_subject, payload))
        return ContactMutationResult(7, 41, True, "contact_audit", 103)

    async def assign_tag(_db, contact_id, tag_id, *, actor_subject):
        assert (contact_id, tag_id) == (7, 4)
        calls.append(("tag_assign", actor_subject, tag_id))
        return ContactMutationResult(7, 51, False, None, None)

    async def remove_tag(_db, contact_id, tag_id, *, actor_subject):
        assert (contact_id, tag_id) == (7, 4)
        calls.append(("tag_remove", actor_subject, tag_id))
        return ContactMutationResult(7, None, False, None, None)

    service = SimpleNamespace(
        sync_legacy_leads=sync,
        import_contacts=import_rows,
        apply_contact_bulk_action=bulk,
        create_contact=create,
        update_contact=update,
        create_contact_note=create_note,
        delete_contact_note=delete_note,
        create_contact_saved_search=create_search,
        assign_contact_tag=assign_tag,
        remove_contact_tag=remove_tag,
    )
    monkeypatch.setattr(contact_router, "contact_service", service, raising=False)

    async def load_raw(_db, contact_id):
        return _raw_contact(contact_id)

    monkeypatch.setattr(contact_router, "_load_legacy_contact", load_raw, raising=False)


def _valid_import_body() -> dict[str, object]:
    return {
        "contacts": [
            {
                "first_name": "Imported",
                "last_name": "Contact",
                "email": "imported@example.test",
                "stage": "lead",
            }
        ]
    }


def test_mutation_routes_are_interleaved_and_static_paths_never_hit_contact_id(
    monkeypatch,
):
    calls: list[tuple[str, str, object]] = []
    _install_successful_mutation_services(monkeypatch, calls)
    client = _focused_read_client()

    assert _route_inventory(contact_router.router) == FULL_ROUTE_INVENTORY
    responses = (
        client.post("/contacts/sync-leads"),
        client.post("/contacts/import", json=_valid_import_body()),
        client.post(
            "/contacts/bulk",
            json={
                "contact_ids": [7],
                "action": {"action": "set_stage", "stage": "active"},
            },
        ),
    )
    assert [response.status_code for response in responses] == [200, 200, 200]
    assert all(response.status_code != 422 for response in responses)


def test_all_ten_mutations_forward_actor_and_return_exact_compatibility_shapes(
    monkeypatch,
):
    calls: list[tuple[str, str, object]] = []
    _install_successful_mutation_services(monkeypatch, calls)
    client = _focused_read_client()

    responses = {
        "sync": client.post("/contacts/sync-leads"),
        "import": client.post("/contacts/import", json=_valid_import_body()),
        "bulk": client.post(
            "/contacts/bulk",
            json={
                "contact_ids": [7],
                "action": {"action": "set_stage", "stage": "active"},
            },
        ),
        "create": client.post(
            "/contacts",
            json={"first_name": "Created", "email": "created@example.test"},
        ),
        "update": client.patch("/contacts/7", json={"stage": "active"}),
        "note_create": client.post("/contacts/7/notes", json={"body": " Note body "}),
        "note_delete": client.delete("/contacts/7/notes/31"),
        "search_create": client.post(
            "/contacts/7/saved-searches",
            json={"name": " Search ", "criteria": {"z": 1, "a": {"b": 2}}},
        ),
        "tag_assign": client.post("/contacts/7/tags/4"),
        "tag_remove": client.delete("/contacts/7/tags/4"),
    }

    assert all(response.status_code == 200 for response in responses.values())
    assert responses["sync"].json() == {
        "created": 2,
        "timeline_backfilled": 1,
        "total_legacy_leads": 3,
    }
    assert responses["import"].json() == {
        "created": 1,
        "skipped_duplicates": 1,
    }
    assert responses["bulk"].json() == {
        "requested_contact_ids": [7],
        "actioned_contact_ids": [7],
        "action": "set_stage",
    }
    expected_raw = {
        "id": 7,
        "first_name": "Raw",
        "last_name": "Contact",
        "email": None,
        "phone": " raw phone ",
        "lead_id": 91,
        "birthday": "1990-08-13",
        "anniversary": None,
        "stage": " internal ",
    }
    assert responses["create"].json() == expected_raw
    assert responses["update"].json() == expected_raw
    assert responses["note_create"].json() == {"id": 31, "body": "Note body"}
    assert responses["note_delete"].json() == {"deleted": True, "id": 31}
    assert responses["search_create"].json() == {
        "id": 41,
        "name": "Search",
        "criteria": '{"a":{"b":2},"z":1}',
    }
    assert responses["tag_assign"].json() == {"contact_id": 7, "tag_id": 4}
    assert responses["tag_remove"].json() == {
        "removed": False,
        "contact_id": 7,
        "tag_id": 4,
    }
    assert [name for name, _actor, _payload in calls] == [
        "sync",
        "import",
        "bulk",
        "create",
        "update",
        "note_create",
        "note_delete",
        "search_create",
        "tag_assign",
        "tag_remove",
    ]
    assert all(actor == "17" for _name, actor, _payload in calls)
    assert all(
        "audit" not in key for response in responses.values() for key in response.json()
    )


@pytest.mark.parametrize(
    ("method", "path", "body", "schema_type"),
    [
        ("post", "/contacts/import", _valid_import_body(), ContactImportIn),
        (
            "post",
            "/contacts/bulk",
            {
                "contact_ids": [7],
                "action": {"action": "set_stage", "stage": "active"},
            },
            ContactBulkRequest,
        ),
        ("post", "/contacts", {"first_name": "Created"}, ContactCreateIn),
        ("patch", "/contacts/7", {"stage": "active"}, ContactUpdateIn),
        ("post", "/contacts/7/notes", {"body": "Body"}, ContactNoteCreateIn),
        (
            "post",
            "/contacts/7/saved-searches",
            {"name": "Search", "criteria": {}},
            ContactSavedSearchCreateIn,
        ),
    ],
)
@pytest.mark.parametrize("error_type", [TypeError, ValueError])
def test_every_mutation_command_adapter_error_is_safe_422_before_service(
    monkeypatch, method, path, body, schema_type, error_type
):
    called = False

    def invalid_command(_self):
        raise error_type("private-adapter-value")

    async def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(schema_type, "to_command", invalid_command)
    monkeypatch.setattr(
        contact_router,
        "contact_service",
        SimpleNamespace(
            import_contacts=fail_if_called,
            apply_contact_bulk_action=fail_if_called,
            create_contact=fail_if_called,
            update_contact=fail_if_called,
            create_contact_note=fail_if_called,
            create_contact_saved_search=fail_if_called,
        ),
        raising=False,
    )
    response = _focused_read_client().request(method, path, json=body)

    assert response.status_code == 422
    assert called is False
    assert "private-adapter-value" not in response.text


@pytest.mark.parametrize(
    ("method", "path", "body", "service_name"),
    [
        ("post", "/contacts/sync-leads", None, "sync_legacy_leads"),
        ("post", "/contacts/import", _valid_import_body(), "import_contacts"),
        (
            "post",
            "/contacts/bulk",
            {
                "contact_ids": [7],
                "action": {"action": "set_stage", "stage": "active"},
            },
            "apply_contact_bulk_action",
        ),
        ("post", "/contacts", {"first_name": "Created"}, "create_contact"),
        ("patch", "/contacts/7", {"stage": "active"}, "update_contact"),
        (
            "post",
            "/contacts/7/notes",
            {"body": "Body"},
            "create_contact_note",
        ),
        ("delete", "/contacts/7/notes/31", None, "delete_contact_note"),
        (
            "post",
            "/contacts/7/saved-searches",
            {"name": "Search", "criteria": {}},
            "create_contact_saved_search",
        ),
        ("post", "/contacts/7/tags/4", None, "assign_contact_tag"),
        ("delete", "/contacts/7/tags/4", None, "remove_contact_tag"),
    ],
)
@pytest.mark.parametrize("error_type", [TypeError, ValueError])
def test_every_mutation_service_type_error_is_private_generic_500(
    monkeypatch, method, path, body, service_name, error_type
):
    async def fail(*_args, **_kwargs):
        raise error_type("private-service-value")

    monkeypatch.setattr(
        contact_router,
        "contact_service",
        SimpleNamespace(**{service_name: fail}),
        raising=False,
    )
    response = _focused_read_client().request(method, path, json=body)

    assert response.status_code == 500
    assert response.json() == {"detail": "Unable to update contact data"}
    assert "private-service-value" not in response.text


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (contact_router.ContactNotFound("private-mutation-value"), 404),
        (contact_router.TimelineContactNotFound("private-mutation-value"), 404),
        (contact_router.ContactNotInDirectory("private-mutation-value"), 409),
        (contact_router.ContactDataIntegrityError("private-mutation-value"), 409),
        (contact_router.ContactLinkConflict("private-mutation-value"), 409),
        (
            contact_router.ContactTimelineIntegrityError("private-mutation-value"),
            409,
        ),
        (contact_router.ContactSectionUnsupported("private-mutation-value"), 422),
        (
            contact_router.HTTPException(418, detail="private-mutation-value"),
            500,
        ),
    ],
)
def test_mutation_domain_errors_map_exactly_without_private_values(
    monkeypatch, error, expected_status
):
    async def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(
        contact_router,
        "contact_service",
        SimpleNamespace(sync_legacy_leads=fail),
    )
    response = _focused_read_client().post("/contacts/sync-leads")

    assert response.status_code == expected_status
    assert "private-mutation-value" not in response.text


def test_mutation_response_validation_is_inside_private_boundary(monkeypatch, caplog):
    async def invalid_result(_db, *, actor_subject):
        assert actor_subject == "17"
        return {"created": True, "private": "private-result-value"}

    monkeypatch.setattr(
        contact_router,
        "contact_service",
        SimpleNamespace(sync_legacy_leads=invalid_result),
        raising=False,
    )
    response = _focused_read_client().post("/contacts/sync-leads")

    assert response.status_code == 500
    assert response.json() == {"detail": "Unable to update contact data"}
    assert "private-result-value" not in response.text
    assert "private-result-value" not in caplog.text


def test_unexpected_command_adapter_error_is_private_generic_500(monkeypatch, caplog):
    def unexpected_command(_self):
        raise RuntimeError("private-command-value")

    monkeypatch.setattr(ContactCreateIn, "to_command", unexpected_command)
    response = _focused_read_client().post("/contacts", json={"first_name": "Created"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Unable to update contact data"}
    assert "private-command-value" not in response.text
    assert "private-command-value" not in caplog.text


@pytest.mark.parametrize(
    ("method", "path", "body", "service_name", "result"),
    [
        (
            "patch",
            "/contacts/7",
            {"stage": "active"},
            "update_contact",
            _mutation_detail(8),
        ),
        (
            "post",
            "/contacts/7/notes",
            {"body": "Body"},
            "create_contact_note",
            ContactMutationResult(8, 31, True, "contact_audit", 101),
        ),
        (
            "delete",
            "/contacts/7/notes/31",
            None,
            "delete_contact_note",
            ContactMutationResult(7, 32, True, "contact_audit", 102),
        ),
        (
            "post",
            "/contacts/7/saved-searches",
            {"name": "Search", "criteria": {}},
            "create_contact_saved_search",
            ContactMutationResult(8, 41, True, "contact_audit", 103),
        ),
        (
            "post",
            "/contacts/7/tags/4",
            None,
            "assign_contact_tag",
            ContactMutationResult(8, 51, False, None, None),
        ),
        (
            "delete",
            "/contacts/7/tags/4",
            None,
            "remove_contact_tag",
            ContactMutationResult(8, None, False, None, None),
        ),
    ],
)
def test_mutation_result_identity_mismatch_is_safe_409(
    monkeypatch, method, path, body, service_name, result
):
    async def wrong_result(*_args, **_kwargs):
        return result

    monkeypatch.setattr(
        contact_router,
        "contact_service",
        SimpleNamespace(**{service_name: wrong_result}),
        raising=False,
    )
    response = _focused_read_client().request(method, path, json=body)

    assert response.status_code == 409
    assert response.json() == {"detail": "Contact data is unavailable"}


@pytest.mark.parametrize(
    ("method", "path", "body", "service_name", "result"),
    [
        (
            "post",
            "/contacts/7/notes",
            {"body": "Body"},
            "create_contact_note",
            ContactMutationResult(7, 31, False, None, None),
        ),
        (
            "delete",
            "/contacts/7/notes/31",
            None,
            "delete_contact_note",
            ContactMutationResult(7, 31, False, None, None),
        ),
        (
            "post",
            "/contacts/7/saved-searches",
            {"name": "Search", "criteria": {}},
            "create_contact_saved_search",
            ContactMutationResult(7, 41, False, None, None),
        ),
        (
            "post",
            "/contacts/bulk",
            {
                "contact_ids": [7],
                "action": {"action": "set_stage", "stage": "active"},
            },
            "apply_contact_bulk_action",
            ContactBulkResult((8,), (), "set_stage"),
        ),
        (
            "post",
            "/contacts/bulk",
            {
                "contact_ids": [7],
                "action": {"action": "set_stage", "stage": "active"},
            },
            "apply_contact_bulk_action",
            ContactBulkResult((7,), (), "add_tag"),
        ),
    ],
)
def test_mutation_result_semantic_mismatch_is_safe_409(
    monkeypatch, method, path, body, service_name, result
):
    async def wrong_result(*_args, **_kwargs):
        return result

    monkeypatch.setattr(
        contact_router,
        "contact_service",
        SimpleNamespace(**{service_name: wrong_result}),
        raising=False,
    )
    response = _focused_read_client().request(method, path, json=body)

    assert response.status_code == 409
    assert response.json() == {"detail": "Contact data is unavailable"}


def test_import_handler_keeps_direct_callable_signature():
    import inspect

    signature = inspect.signature(contact_router.import_contacts)
    assert tuple(signature.parameters) == ("payload", "db", "actor_subject")
    assert signature.parameters["actor_subject"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize("mode", ["missing", "create_mismatch", "update_mismatch"])
def test_create_update_raw_contact_missing_or_mismatched_is_safe_409(monkeypatch, mode):
    async def create(_db, _payload, *, actor_subject):
        assert actor_subject == "17"
        return _mutation_detail(7)

    async def update(_db, _contact_id, _payload, *, actor_subject):
        assert actor_subject == "17"
        return _mutation_detail(8 if mode == "update_mismatch" else 7)

    async def load(_db, contact_id):
        if mode == "missing":
            return None
        return _raw_contact(8 if mode == "create_mismatch" else contact_id)

    monkeypatch.setattr(
        contact_router,
        "contact_service",
        SimpleNamespace(create_contact=create, update_contact=update),
        raising=False,
    )
    monkeypatch.setattr(contact_router, "_load_legacy_contact", load, raising=False)
    client = _focused_read_client()
    response = (
        client.patch("/contacts/7", json={"stage": "active"})
        if mode == "update_mismatch"
        else client.post("/contacts", json={"first_name": "Created"})
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Contact data is unavailable"}


async def test_mutation_raw_contact_loader_is_one_exact_row_without_method_fallback(
    contact_router_db,
):
    contact_router_db.add(
        CRMContact(
            id=7,
            first_name="Raw",
            last_name="Contact",
            email=None,
            phone=None,
            stage="lead",
        )
    )
    await contact_router_db.flush()
    contact_router_db.add(
        CRMContactMethod(
            contact_id=7,
            source_record_id=None,
            source_key="synthetic-method",
            kind="email",
            label="Email",
            raw_value="recovered@example.test",
            normalized_value="recovered@example.test",
            is_primary=True,
        )
    )
    await contact_router_db.flush()
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(contact_router_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        raw = await contact_router._load_legacy_contact(contact_router_db, 7)
    finally:
        event.remove(
            contact_router_db.bind.sync_engine, "before_cursor_execute", capture
        )

    assert raw is not None
    assert raw.id == 7
    assert raw.email is None
    assert len(statements) == 1
    assert "crm_contact_methods" not in statements[0]
