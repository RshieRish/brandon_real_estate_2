from datetime import date

import pytest
from pydantic import ValidationError

from schemas.command import ContactCreate, ContactWorkspaceOpportunityOut, TaskUpdate
from models.command import AgreementStatus, CRMActivity, CRMAgreementEvent, CRMContact, CRMFileAsset, CRMReferral, CRMTask, CRMTaskLink


def test_command_models_expose_safe_defaults_and_links():
    contact = CRMContact(first_name="Brandon", last_name="Sweeney")
    task = CRMTask(title="Call Brandon")
    activity = CRMActivity(kind="note", summary="Created contact")

    assert contact.lead_id is None
    assert task.status == "open"
    assert activity.kind == "note"


def test_agreement_statuses_only_include_internal_lifecycle():
    assert {status.value for status in AgreementStatus} == {
        "draft", "in_review", "ready", "shared", "viewed", "completed", "voided", "expired"
    }


def test_contact_workspace_opportunity_serializes_linked_record_context():
    item = ContactWorkspaceOpportunityOut(
        id=12,
        name="15 Oak Street purchase",
        stage="offer",
        value_cents=75000000,
        role="buyer",
    )

    assert item.model_dump() == {
        "id": 12,
        "name": "15 Oak Street purchase",
        "stage": "offer",
        "value_cents": 75000000,
        "role": "buyer",
    }


def test_agreement_files_and_events_are_scoped_to_an_internal_agreement():
    asset = CRMFileAsset(
        filename="buyer-agreement.pdf",
        storage_key="command-files/buyer-agreement.pdf",
        agreement_id=4,
    )
    event = CRMAgreementEvent(agreement_id=4, event_type="in_review")

    assert asset.agreement_id == 4
    assert event.agreement_id == 4


def test_task_link_connects_a_task_to_an_internal_record_without_copying_data():
    link = CRMTaskLink(task_id=3, entity_type="opportunity", entity_id=8)
    assert (link.task_id, link.entity_type, link.entity_id) == (3, "opportunity", 8)


def test_referral_is_an_internal_record_with_a_lifecycle():
    referral = CRMReferral(name="Buyer introduction", status="new")
    assert referral.status == "new"


def test_contact_can_store_private_birthday_and_anniversary_dates():
    contact = CRMContact(first_name="Avery", birthday=date(1990, 8, 12), anniversary=date(2020, 6, 1))
    payload = ContactCreate(first_name="Avery", birthday=date(1990, 8, 12), anniversary=date(2020, 6, 1))

    assert contact.birthday == date(1990, 8, 12)
    assert payload.anniversary == date(2020, 6, 1)


def test_task_updates_only_allow_internal_task_lifecycle_and_priorities():
    assert TaskUpdate(status="in_progress", priority="high", description="Call before noon").priority == "high"
    with pytest.raises(ValidationError):
        TaskUpdate(status="deleted")
    with pytest.raises(ValidationError):
        TaskUpdate(priority="urgentish")
