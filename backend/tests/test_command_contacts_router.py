"""Typed HTTP-boundary contracts for the focused Command Contacts router."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from pydantic import ValidationError

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
    ContactCaptureEvidence,
    ContactCelebrationRow,
    ContactCelebrations,
    ContactCelebrationValue,
    ContactDetail,
    ContactDirectoryFilters,
    ContactDirectoryPage,
    ContactDirectoryRow,
    ContactEvidence,
    ContactImportRowCommand,
    ContactOriginFilter,
    ContactRecoveredProfile,
    ContactSection,
    ContactSectionEvidence,
    ContactSmartView,
    ContactSortKey,
    ContactSourceFilter,
    ContactSourceMetadata,
    ContactTagValue,
    ContactTimelineEntry,
    ContactTimelinePage,
    SortDirection,
    TimelineOrigin,
)

NOW = datetime(2026, 8, 13, 14, 30, tzinfo=UTC)


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
