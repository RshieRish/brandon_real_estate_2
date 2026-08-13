from __future__ import annotations

import base64
import json
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import get_args, get_type_hints

import pytest

from services.command_contact_contracts import (
    UNSET,
    CaptureQualityValue,
    ContactBulkAddTag,
    ContactBulkCommand,
    ContactBulkSetStage,
    ContactCreateCommand,
    ContactDirectoryFilters,
    ContactImportCommand,
    ContactImportRowCommand,
    ContactMaterialized,
    ContactNoteCreateCommand,
    ContactOriginFilter,
    ContactSavedSearchCreateCommand,
    ContactSection,
    ContactSmartView,
    ContactSortKey,
    ContactSourceFilter,
    ContactUpdateCommand,
    MaterializationStatus,
    SortDirection,
    TimelineCursorV1,
    TimelineOrigin,
    canonical_contact_audit_json,
    decode_timeline_cursor,
    encode_timeline_cursor,
    redact_contact_audit_value,
    timeline_position_is_after,
)


def test_materialized_section_entity_types_exclude_timeline():
    entity_type = get_type_hints(ContactMaterialized)["entity_type"]
    assert get_args(entity_type) == (
        "note",
        "saved_search",
        "task",
        "smart_plan",
        "opportunity",
    )


def test_exact_enum_values_are_stable():
    assert tuple(ContactSection) == tuple(
        ContactSection(value)
        for value in (
            "timeline", "opportunities", "smart_plans", "notes",
            "saved_searches", "tasks_to_do", "tasks_completed", "tasks_archived",
        )
    )
    assert {item.value for item in CaptureQualityValue} == {
        "complete", "partial", "shell", "error",
    }
    assert {item.value for item in MaterializationStatus} == {
        "source_only", "materialized",
    }
    assert {item.value for item in TimelineOrigin} == {
        "recovered", "internal_crm", "legacy_lead", "booking",
    }


def test_timeline_cursor_is_byte_exact_unpadded_and_round_trips():
    cursor = TimelineCursorV1(
        null_rank=0,
        occurred_at=datetime(2026, 7, 27, 20, 1, 2, 3456, tzinfo=UTC),
        origin_rank=2,
        entity_id=17,
    )
    expected_json = b'{"v":1,"n":0,"t":"2026-07-27T20:01:02.003456Z","o":2,"i":17}'
    expected = base64.urlsafe_b64encode(expected_json).decode().rstrip("=")
    assert encode_timeline_cursor(cursor) == expected
    assert "=" not in expected
    assert decode_timeline_cursor(expected) == cursor


@pytest.mark.parametrize(
    "raw",
    [
        '{"v":1,"n":0,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":1}=',
        '{"n":0,"v":1,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":1}',
        '{"v":1,"n":0,"t":"2026-07-27T20:01:02Z","o":0,"i":1}',
        '{"v":1,"n":0,"t":"2026-07-27T20:01:02.000000+00:00","o":0,"i":1}',
        '{"v":1,"n":1,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":1}',
        '{"v":1,"n":0,"t":null,"o":0,"i":1}',
        '{"v":1,"n":false,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":1}',
        '{"v":1,"n":0,"t":"2026-07-27T20:01:02.000000Z","o":true,"i":1}',
        '{"v":1,"n":0,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":0}',
        '{"v":2,"n":0,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":1}',
        '{"v":1,"n":0,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":1,"x":2}',
        "a",
    ],
)
def test_timeline_cursor_rejects_every_noncanonical_form_without_echo(raw):
    encoded = raw if raw.endswith("=") else base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    with pytest.raises(ValueError) as error:
        decode_timeline_cursor(encoded)
    assert encoded not in str(error.value)


def test_null_cursor_and_after_semantics_match_total_order():
    cursor = TimelineCursorV1(1, None, 1, 50)
    assert decode_timeline_cursor(encode_timeline_cursor(cursor)) == cursor
    assert timeline_position_is_after(cursor, null_rank=1, occurred_at=None, origin_rank=2, entity_id=999)
    assert timeline_position_is_after(cursor, null_rank=1, occurred_at=None, origin_rank=1, entity_id=49)
    assert not timeline_position_is_after(cursor, null_rank=0, occurred_at=datetime.now(UTC), origin_rank=3, entity_id=1)


def test_directory_filters_trim_and_canonicalize_set_like_fields():
    value = ContactDirectoryFilters(
        query="  Lake  ",
        tag_ids=(9, 2, 9),
        sources=(ContactSourceFilter.LEGACY_LEAD, ContactSourceFilter.KW_COMMAND, ContactSourceFilter.KW_COMMAND),
        origins=(ContactOriginFilter.LEAD_BACKED, ContactOriginFilter.RECOVERED, ContactOriginFilter.LEAD_BACKED),
        smart_view=ContactSmartView.NEVER_CONTACTED,
        sort=ContactSortKey.UPDATED_AT,
        direction=SortDirection.DESC,
    )
    assert value.query == "Lake"
    assert value.tag_ids == (2, 9)
    assert value.sources == (ContactSourceFilter.KW_COMMAND, ContactSourceFilter.LEGACY_LEAD)
    assert value.origins == (
        ContactOriginFilter.LEAD_BACKED,
        ContactOriginFilter.RECOVERED,
    )
    with pytest.raises(FrozenInstanceError):
        value.page = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0}, {"page_size": 101}, {"query": "x" * 201},
        {"owner_actor_id": "x" * 256}, {"tag_ids": (True,)},
        {"health_min": -1}, {"health_max": 101},
        {"health_min": 80, "health_max": 20}, {"birthday_month": 0},
        {"anniversary_month": 13},
    ],
)
def test_directory_filters_reject_invalid_boundaries(kwargs):
    with pytest.raises(ValueError):
        ContactDirectoryFilters(**kwargs)


def test_mutation_commands_enforce_exact_bounds_and_deep_freeze_criteria():
    created = ContactCreateCommand("  Avery  ", last_name=" Lake ", stage=" lead ")
    assert (created.first_name, created.last_name, created.stage) == ("Avery", "Lake", "lead")
    criteria = {"nested": {"tags": ["one", "two"]}}
    search = ContactSavedSearchCreateCommand("  My search ", criteria)
    criteria["nested"] = {"changed": True}
    assert isinstance(search.criteria, MappingProxyType)
    assert search.criteria["nested"]["tags"] == ("one", "two")
    update = ContactUpdateCommand(email=None)
    assert update.email is None
    assert update.first_name is UNSET


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ContactCreateCommand(""),
        lambda: ContactCreateCommand("x" * 121),
        lambda: ContactCreateCommand("A", email="x" * 256),
        lambda: ContactCreateCommand("A", phone="x" * 51),
        lambda: ContactCreateCommand("A", stage=""),
        lambda: ContactUpdateCommand(),
        lambda: ContactUpdateCommand(first_name=None),
        lambda: ContactNoteCreateCommand(""),
        lambda: ContactNoteCreateCommand("x" * 20_001),
        lambda: ContactSavedSearchCreateCommand("x" * 256, {}),
        lambda: ContactSavedSearchCreateCommand("ok", {"bad": float("nan")}),
        lambda: ContactBulkCommand((), ContactBulkSetStage("set_stage", "lead")),
        lambda: ContactBulkCommand((1, 1), ContactBulkSetStage("set_stage", "lead")),
        lambda: ContactBulkCommand(tuple(range(1, 202)), ContactBulkSetStage("set_stage", "lead")),
        lambda: ContactBulkCommand((1,), ContactBulkAddTag("add_tag", 0)),
        lambda: ContactImportCommand(()),
    ],
)
def test_mutation_commands_reject_invalid_or_ambiguous_input(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_import_rows_are_immutable_validated_and_limited():
    row = ContactImportRowCommand("A", "", None, None, "lead", date(2000, 1, 2), None)
    command = ContactImportCommand((row,))
    assert command.contacts == (row,)
    assert {field.name for field in fields(ContactCreateCommand)}.isdisjoint(
        {"lead_id", "source_record_id", "audit_event_id", "recovered_profile"}
    )


def test_audit_redaction_is_canonical_domain_separated_and_never_raw():
    first = redact_contact_audit_value("Private Name", domain="contact.name")
    second = redact_contact_audit_value("Private Name", domain="contact.email")
    assert first == {
        "present": True,
        "length": 12,
        "sha256": first["sha256"],
    }
    assert first["sha256"] != second["sha256"]
    rendered = canonical_contact_audit_json(
        {"stage": "lead", "name": first, "changed": True, "record_id": 7}
    )
    assert rendered == json.dumps(json.loads(rendered), sort_keys=True, separators=(",", ":"))
    assert "Private Name" not in rendered
    with pytest.raises(ValueError):
        canonical_contact_audit_json({"bad": float("inf")})
    for forbidden in (
        {"email": "private@example.test"},
        {"source_record_id": 9},
        {"provider_id": "private"},
        {"token": "secret"},
        {"actor_subject": "admin:private"},
    ):
        with pytest.raises(ValueError):
            canonical_contact_audit_json(forbidden)
