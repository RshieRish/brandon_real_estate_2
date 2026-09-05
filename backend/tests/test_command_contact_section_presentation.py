"""Captured date, budget, and internal/recovered section presentation regressions."""

import json
from dataclasses import asdict

import pytest

from models.command import (
    CRMContact,
    CRMSavedSearch,
    CRMSmartPlan,
    CRMSmartPlanEnrollment,
    CRMTask,
)
from routers.command_contacts import _legacy_contact_workspace
from schemas.command_contacts import LegacyContactWorkspaceOut
from services.command_contact_contracts import ContactSection
from services.command_contacts import (
    _project_section_occurrence,
    get_contact_workspace_summary,
    saved_search_criteria_summary,
)
from tests.test_command_contact_sections import _add_occurrence, _source
from tests.test_command_contact_sections import section_db as _section_db

section_db = _section_db


@pytest.mark.parametrize(
    "literal,canonical",
    [
        ("2026-08-30", "2026-08-30"),
        ("08/25/2024", "2024-08-25"),
        ("09/06/2026", None),
        ("Tomorrow", None),
        ("2026-02-30", None),
    ],
)
def test_captured_due_dates_retain_literal_without_inventing_a_timestamp(literal, canonical):
    source = _source(1, kind="contact_task", payload={"values": {
        "title": "Review comparable sales", "due_date": literal,
    }})

    task = asdict(_project_section_occurrence(source, ContactSection.TASKS_TO_DO))

    assert task.get("due_date_text") == literal
    assert task.get("due_date") == canonical
    assert task["due_at"] is None


def test_captured_budget_keeps_its_label_and_does_not_become_opportunity_value():
    source = _source(1, kind="contact_opportunity", payload={"values": {
        "title": "Condo search", "budget": "$440,000.00", "value_cents": 0,
    }})

    opportunity = asdict(_project_section_occurrence(source, ContactSection.OPPORTUNITIES))

    assert opportunity.get("budget") == "$440,000.00"
    assert opportunity["value_cents"] == 0


@pytest.mark.asyncio
async def test_summary_separates_same_title_internal_and_unlinked_recovered_tasks(section_db):
    contact = CRMContact(first_name="Rowan", last_name="Ellis")
    section_db.add(contact)
    await section_db.flush()
    task = CRMTask(contact_id=contact.id, title="Annual check-in", status="open")
    section_db.add(task)
    await section_db.flush()
    await _add_occurrence(section_db, contact, 1, section=ContactSection.TASKS_TO_DO,
                          values={"title": task.title, "due_date": "2026-08-30"})
    await _add_occurrence(section_db, contact, 2, section=ContactSection.TASKS_TO_DO,
                          values={"title": task.title}, linked_entity=("task", task.id))

    summary = asdict(await get_contact_workspace_summary(section_db, contact.id))

    assert summary["active_tasks"] == 2
    assert summary.get("internal_counts") == {
        "active_tasks": 1, "completed_tasks": 0, "cancelled_tasks": 0,
        "archived_tasks": 0, "active_smart_plans": 0, "opportunities": 0,
        "notes": 0, "saved_searches": 0, "bookings": 0,
    }
    assert summary.get("recovered_counts") == {
        **summary["internal_counts"], "active_tasks": 1,
    }


@pytest.mark.asyncio
async def test_internal_workspace_returns_plan_names_and_labeled_search_criteria(section_db):
    contact = CRMContact(first_name="Maren", last_name="Brooks")
    plan = CRMSmartPlan(name="Quarterly homeowner check-in")
    section_db.add_all([contact, plan])
    await section_db.flush()
    section_db.add_all([
        CRMSmartPlanEnrollment(contact_id=contact.id, smart_plan_id=plan.id),
        CRMSavedSearch(contact_id=contact.id, name="Lakeside condos", criteria_json=json.dumps({
            "beds": 2, "price": "$300,000 - $530,000", "baths": 1,
        })),
    ])
    await section_db.flush()

    raw = await _legacy_contact_workspace(section_db, contact_id=contact.id)
    workspace = LegacyContactWorkspaceOut.model_validate(raw).model_dump()

    assert workspace["smart_plans"][0].get("plan_name") == plan.name
    assert workspace["saved_searches"][0].get("criteria_summary") == [
        "Price: $300,000 - $530,000", "Beds: 2", "Baths: 1",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("criteria,expected", [
    (
        {"contact_id": 17, "scope": "contact_workspace", "saved_from": "command"},
        ["SWS contact workspace context", "Saved from Command"],
    ),
    (
        {"beds": 3, "baths": 2.5, "city": "Lowell"},
        ["Beds: 3", "Baths: 2.5", "City: Lowell"],
    ),
])
async def test_internal_saved_searches_describe_actual_stored_criteria(section_db, criteria, expected):
    contact = CRMContact(first_name="Maren", last_name="Brooks")
    section_db.add(contact)
    await section_db.flush()
    raw_criteria = json.dumps(criteria)
    section_db.add(CRMSavedSearch(
        contact_id=contact.id, name="Saved workspace", criteria_json=raw_criteria,
    ))
    await section_db.flush()

    raw = await _legacy_contact_workspace(section_db, contact_id=contact.id)
    workspace = LegacyContactWorkspaceOut.model_validate(raw).model_dump()

    assert workspace["saved_searches"][0]["criteria_summary"] == expected
    assert workspace["saved_searches"][0]["criteria"] == raw_criteria


@pytest.mark.parametrize("criteria,expected", [
    ({}, ("No search criteria recorded",)),
    ("not valid JSON", ("Stored criteria summary unavailable",)),
    (
        {"beds": 3, "custom_filter": {"private": "do not render"}, "created_by": "private actor"},
        ("Beds: 3", "Additional stored criteria are not summarized"),
    ),
    (
        {"beds": 3, "city": "x" * 121, "baths": True},
        ("Beds: 3", "Additional stored criteria are not summarized"),
    ),
])
def test_internal_saved_search_summary_has_bounded_explicit_fallbacks(criteria, expected):
    assert saved_search_criteria_summary(criteria) == expected


def test_internal_search_labels_do_not_expand_captured_source_whitelist():
    source = _source(1, kind="contact_saved_search", payload={"values": {
        "name": "Captured search", "beds": 3, "baths": 2.5, "city": "Lowell",
        "scope": "contact_workspace", "saved_from": "command",
    }})
    value = _project_section_occurrence(source, ContactSection.SAVED_SEARCHES)
    assert value.criteria_summary == ("Beds: 3",)
