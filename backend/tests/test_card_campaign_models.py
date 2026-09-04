from __future__ import annotations

from uuid import uuid4

import pytest
from database import Base
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, UniqueConstraint


def _checks(model) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }


def _uniques(model) -> dict[str, tuple[str, ...]]:
    return {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name
    }


def test_card_models_register_exact_additive_tables_and_safe_defaults() -> None:
    from models.card_campaign import (
        CardCampaign,
        CardCampaignRecipient,
        CardDeliveryAttempt,
        CardProviderConnection,
        CardProviderReceipt,
    )

    models = (
        CardProviderConnection,
        CardCampaign,
        CardCampaignRecipient,
        CardDeliveryAttempt,
        CardProviderReceipt,
    )
    assert {model.__table__.name for model in models} <= set(Base.metadata.tables)
    assert CardProviderConnection.__table__.c.state.default.arg == "disconnected"
    assert CardCampaign.__table__.c.provider.default.arg == "send_out_cards"
    assert CardCampaign.__table__.c.version.default.arg == 1
    assert CardCampaignRecipient.__table__.c.excluded.default.arg is False
    assert CardDeliveryAttempt.__table__.c.attempt_number.default.arg == 1
    assert CardProviderReceipt.__table__.c.details_json.default.arg == "{}"


def test_card_models_enforce_idempotency_ownership_and_lifecycle_contracts() -> None:
    from models.card_campaign import (
        CardCampaign,
        CardCampaignRecipient,
        CardDeliveryAttempt,
        CardProviderReceipt,
    )

    assert {
        "uq_card_campaigns_request_id": ("request_id",),
        "uq_card_campaigns_send_request_id": ("send_request_id",),
    }.items() <= _uniques(CardCampaign).items()
    assert {
        "uq_card_campaign_recipients_contact_kind": (
            "campaign_id",
            "contact_id",
            "celebration_kind",
        ),
        "uq_card_campaign_recipients_id_campaign": ("id", "campaign_id"),
    }.items() <= _uniques(CardCampaignRecipient).items()
    assert {
        "uq_card_delivery_attempts_recipient_request": (
            "recipient_id",
            "request_id",
        ),
        "uq_card_delivery_attempts_provider_key": ("provider_idempotency_key",),
        "uq_card_delivery_attempts_identity": (
            "id",
            "campaign_id",
            "recipient_id",
        ),
    }.items() <= _uniques(CardDeliveryAttempt).items()
    assert {
        "uq_card_provider_receipts_attempt": ("attempt_id",),
    }.items() <= _uniques(CardProviderReceipt).items()
    assert {
        "ck_card_campaigns_status",
        "ck_card_campaigns_selection",
        "ck_card_campaigns_approval_shape",
        "ck_card_campaigns_checksum",
    } <= _checks(CardCampaign)
    assert {
        "ck_card_campaign_recipients_celebration",
        "ck_card_campaign_recipients_address_shape",
        "ck_card_campaign_recipients_exclusion_shape",
        "ck_card_campaign_recipients_content_hash",
    } <= _checks(CardCampaignRecipient)
    assert {
        "ck_card_delivery_attempts_number",
        "ck_card_delivery_attempts_content_hash",
    } <= _checks(CardDeliveryAttempt)
    assert {
        "ck_card_provider_receipts_outcome",
        "ck_card_provider_receipts_provider_reference",
        "ck_card_provider_receipts_details_json",
    } <= _checks(CardProviderReceipt)


def test_card_dtos_are_strict_bounded_and_require_deliberate_confirmation() -> None:
    from schemas.card_campaign import (
        CardCampaignApproveRequest,
        CardCampaignDraftRequest,
        CardCampaignUpdateRequest,
        CardRecipientUpdate,
    )

    draft = CardCampaignDraftRequest(request_id=uuid4(), month=9)
    assert draft.include_birthdays is True
    assert draft.include_home_anniversaries is True
    assert "{first_name}" in draft.birthday_message_template
    for invalid in (0, 13, True, "9"):
        with pytest.raises(ValidationError):
            CardCampaignDraftRequest.model_validate(
                {"request_id": str(uuid4()), "month": invalid}
            )
    with pytest.raises(ValidationError):
        CardCampaignDraftRequest(
            request_id=uuid4(),
            month=9,
            include_birthdays=False,
            include_home_anniversaries=False,
        )
    with pytest.raises(ValidationError):
        CardCampaignDraftRequest(
            request_id=uuid4(),
            month=9,
            birthday_message_template="No personalization token",
        )

    recipient_id = uuid4()
    update = CardCampaignUpdateRequest(
        expected_version=2,
        recipient_updates=[
            CardRecipientUpdate(
                recipient_id=recipient_id,
                excluded=True,
                exclusion_reason="Client requested no physical mail.",
            )
        ],
    )
    assert update.recipient_updates[0].recipient_id == recipient_id
    with pytest.raises(ValidationError):
        CardCampaignUpdateRequest(expected_version=2)
    with pytest.raises(ValidationError):
        CardRecipientUpdate(recipient_id=recipient_id)

    approval = CardCampaignApproveRequest(
        request_id=uuid4(),
        expected_version=3,
        confirmed_recipient_count=12,
        confirmed_cost_cents=2400,
        confirmed_by_brandon=True,
    )
    assert approval.confirmed_by_brandon is True
    with pytest.raises(ValidationError):
        CardCampaignApproveRequest(
            request_id=uuid4(),
            expected_version=3,
            confirmed_recipient_count=12,
            confirmed_cost_cents=2400,
            confirmed_by_brandon=False,
        )


def test_provider_boundary_hides_private_payloads_and_stays_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.card_provider import CardSendRequest, configured_card_provider

    private_name = "Private Recipient"
    private_message = "Private card message"
    private_street = "1 Private Street"
    request = CardSendRequest(
        idempotency_key=uuid4(),
        recipient_id=uuid4(),
        recipient_name=private_name,
        address={"line1": private_street},
        message=private_message,
        design_key="birthday-classic",
    )
    rendered = repr(request)
    assert private_name not in rendered
    assert private_message not in rendered
    assert private_street not in rendered

    monkeypatch.setenv("CARD_PROVIDER_MODE", "send_out_cards")
    monkeypatch.setenv("SEND_OUT_CARDS_API_BASE_URL", "https://provider.invalid")
    monkeypatch.setenv("SEND_OUT_CARDS_API_TOKEN", "never-log-this-token")
    monkeypatch.setenv("SEND_OUT_CARDS_ACCOUNT_ID", "private-account")
    provider = configured_card_provider()
    assert provider.connected is False
    assert provider.connection_reason == "contract_adapter_pending"
    assert "never-log-this-token" not in repr(provider)
