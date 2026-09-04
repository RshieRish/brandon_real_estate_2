"""Strict contracts for approval-gated physical-card campaigns."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
CampaignStatus = Literal[
    "draft",
    "needs_addresses",
    "needs_connection",
    "ready_for_review",
    "approved",
    "sending",
    "sent",
    "partially_sent",
    "failed",
    "delivery_uncertain",
]
DeliveryOutcome = Literal["confirmed", "rejected", "ambiguous"]
CelebrationKind = Literal["birthday", "home_anniversary"]

DEFAULT_BIRTHDAY_MESSAGE = (
    "Happy birthday, {first_name}! Wishing you a wonderful day and a great "
    "year ahead. — Brandon"
)
DEFAULT_ANNIVERSARY_MESSAGE = (
    "Happy home anniversary, {first_name}! I hope your home continues to be a "
    "place you love. — Brandon"
)


class CardModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        from_attributes=True,
    )


class CardCampaignDraftRequest(CardModel):
    request_id: UUID
    month: Annotated[StrictInt, Field(ge=1, le=12)]
    include_birthdays: StrictBool = True
    include_home_anniversaries: StrictBool = True
    title: str | None = Field(default=None, min_length=1, max_length=255)
    birthday_message_template: str = Field(
        default=DEFAULT_BIRTHDAY_MESSAGE,
        min_length=1,
        max_length=2000,
    )
    home_anniversary_message_template: str = Field(
        default=DEFAULT_ANNIVERSARY_MESSAGE,
        min_length=1,
        max_length=2000,
    )
    birthday_design_key: str = Field(
        default="birthday-classic",
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    home_anniversary_design_key: str = Field(
        default="home-anniversary-classic",
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )

    @model_validator(mode="after")
    def validate_selection_and_templates(self) -> Self:
        if not self.include_birthdays and not self.include_home_anniversaries:
            raise ValueError("at least one celebration kind must be selected")
        if (
            self.include_birthdays
            and "{first_name}" not in self.birthday_message_template
        ):
            raise ValueError("birthday message must include {first_name}")
        if (
            self.include_home_anniversaries
            and "{first_name}" not in self.home_anniversary_message_template
        ):
            raise ValueError("home anniversary message must include {first_name}")
        return self


class CardRecipientUpdate(CardModel):
    recipient_id: UUID
    message: str | None = Field(default=None, min_length=1, max_length=2000)
    design_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    excluded: StrictBool | None = None
    exclusion_reason: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
    )

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        if all(
            value is None
            for value in (
                self.message,
                self.design_key,
                self.excluded,
                self.exclusion_reason,
            )
        ):
            raise ValueError("recipient update must change at least one field")
        if self.excluded is True and self.exclusion_reason is None:
            raise ValueError("excluded recipients require a reason")
        if self.excluded is not True and self.exclusion_reason is not None:
            raise ValueError("exclusion reason requires excluded=true")
        return self


class CardCampaignUpdateRequest(CardModel):
    expected_version: PositiveInt
    title: str | None = Field(default=None, min_length=1, max_length=255)
    birthday_message_template: str | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
    )
    home_anniversary_message_template: str | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
    )
    birthday_design_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    home_anniversary_design_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    recipient_updates: list[CardRecipientUpdate] = Field(
        default_factory=list,
        max_length=500,
    )

    @field_validator("recipient_updates")
    @classmethod
    def unique_recipients(
        cls, values: list[CardRecipientUpdate]
    ) -> list[CardRecipientUpdate]:
        ids = [value.recipient_id for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError("recipient updates must be unique")
        return values

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if (
            self.title is None
            and self.birthday_message_template is None
            and self.home_anniversary_message_template is None
            and self.birthday_design_key is None
            and self.home_anniversary_design_key is None
            and not self.recipient_updates
        ):
            raise ValueError("campaign update must change at least one field")
        return self


class CardCampaignApproveRequest(CardModel):
    request_id: UUID
    expected_version: PositiveInt
    confirmed_recipient_count: NonNegativeInt
    confirmed_cost_cents: NonNegativeInt
    confirmed_by_brandon: Literal[True]


class CardProviderConnectionOut(CardModel):
    provider: str
    state: Literal["disconnected", "connected", "error"]
    display_label: str | None
    reason: str | None
    last_verified_at: datetime | None


class CardRecipientOut(CardModel):
    id: UUID
    contact_id: PositiveInt
    display_name: str
    celebration_kind: CelebrationKind
    celebration_month: Annotated[StrictInt, Field(ge=1, le=12)]
    celebration_day: Annotated[StrictInt, Field(ge=1, le=31)]
    celebration_year: StrictInt | None
    celebration_year_quality: Literal["verified", "yearless", "sentinel", "unknown"]
    celebration_origin: Literal["internal_crm", "recovered"]
    message: str
    design_key: str
    address_status: Literal["ready", "missing"]
    address_summary: str | None
    excluded: StrictBool
    exclusion_reason: str | None
    delivery_outcome: DeliveryOutcome | None


class CardCampaignListItem(CardModel):
    id: UUID
    title: str
    month: Annotated[StrictInt, Field(ge=1, le=12)]
    status: CampaignStatus
    total_recipients: NonNegativeInt
    sendable_recipients: NonNegativeInt
    missing_address_count: NonNegativeInt
    estimated_cost_cents: NonNegativeInt
    currency: Literal["USD"]
    version: PositiveInt
    created_at: datetime
    updated_at: datetime


class CardCampaignDetail(CardCampaignListItem):
    request_id: UUID
    include_birthdays: StrictBool
    include_home_anniversaries: StrictBool
    audience_ref: UUID
    audience_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    birthday_recipients: NonNegativeInt
    home_anniversary_recipients: NonNegativeInt
    excluded_recipients: NonNegativeInt
    provider_connected: StrictBool
    provider_connection_reason: str | None
    approved_by_actor: str | None
    approved_at: datetime | None
    send_request_id: UUID | None
    recipients: list[CardRecipientOut] = Field(max_length=500)


class CardCampaignPage(CardModel):
    campaigns: list[CardCampaignListItem] = Field(max_length=50)
    total: NonNegativeInt


__all__ = [name for name in globals() if name.startswith("Card")]
