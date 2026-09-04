"""Sydney-facing card draft orchestration with no approval or send authority."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from config import settings
from schemas.agent_control_cards import (
    AgentCardCampaignDraftRequest,
    AgentCardCampaignDraftResponse,
)
from schemas.card_campaign import CardCampaignDraftRequest
from sqlalchemy.ext.asyncio import AsyncSession

from services.card_campaign_service import CardCampaignError, CardCampaignService
from services.card_provider import configured_card_provider


def _review_url(campaign_id: UUID) -> str:
    base = settings.COMMAND_PUBLIC_BASE_URL.strip().rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise CardCampaignError("command_public_base_url_invalid")
    clean_base = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
    )
    return f"{clean_base}/admin/command/cards/{campaign_id}"


async def create_agent_card_campaign_draft(
    db: AsyncSession,
    payload: AgentCardCampaignDraftRequest,
) -> AgentCardCampaignDraftResponse:
    service = CardCampaignService(provider=configured_card_provider())
    campaign = await service.create_or_get_draft(
        db,
        CardCampaignDraftRequest(
            request_id=payload.request_id,
            month=payload.month,
            include_birthdays=payload.include_birthdays,
            include_home_anniversaries=payload.include_home_anniversaries,
        ),
    )
    return AgentCardCampaignDraftResponse(
        campaign_id=campaign.id,
        status=campaign.status,
        review_url=_review_url(campaign.id),
        total_recipients=campaign.total_recipients,
        sendable_recipients=campaign.sendable_recipients,
        missing_address_count=campaign.missing_address_count,
        estimated_cost_cents=campaign.estimated_cost_cents,
        currency=campaign.currency,
        provider_connected=campaign.provider_connected,
        provider_connection_reason=campaign.provider_connection_reason,
        requires_brandon_review=True,
        nothing_sent=True,
    )


__all__ = ["create_agent_card_campaign_draft"]
