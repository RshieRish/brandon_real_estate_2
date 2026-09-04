"""Bounded Sydney contract for creating review-only card campaign drafts."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
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

from schemas.card_campaign import CampaignStatus, NonNegativeInt


class AgentCardModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentCardCampaignDraftRequest(AgentCardModel):
    request_id: UUID
    month: Annotated[StrictInt, Field(ge=1, le=12)]
    include_birthdays: StrictBool = True
    include_home_anniversaries: StrictBool = True

    @model_validator(mode="after")
    def require_a_celebration_kind(self) -> Self:
        if not self.include_birthdays and not self.include_home_anniversaries:
            raise ValueError("at least one celebration kind must be selected")
        return self


class AgentCardCampaignDraftResponse(AgentCardModel):
    campaign_id: UUID
    status: CampaignStatus
    review_url: str = Field(min_length=1, max_length=1000)
    total_recipients: NonNegativeInt
    sendable_recipients: NonNegativeInt
    missing_address_count: NonNegativeInt
    estimated_cost_cents: NonNegativeInt
    currency: Literal["USD"]
    provider_connected: StrictBool
    provider_connection_reason: str | None = Field(default=None, max_length=120)
    requires_brandon_review: Literal[True]
    nothing_sent: Literal[True]

    @field_validator("review_url")
    @classmethod
    def absolute_https_review_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("review_url must be an absolute credential-free HTTPS URL")
        return value


__all__ = ["AgentCardCampaignDraftRequest", "AgentCardCampaignDraftResponse"]
