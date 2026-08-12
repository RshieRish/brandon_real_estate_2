from schemas.command import ContactWorkspaceOpportunityOut
from models.command import AgreementStatus, CRMActivity, CRMContact, CRMTask


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
