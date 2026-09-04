"""Protected Sydney route for review-only physical-card drafts."""

from __future__ import annotations

from typing import Annotated

from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Request, status
from middleware.agent_control import require_agent_control
from schemas.agent_control_cards import (
    AgentCardCampaignDraftRequest,
    AgentCardCampaignDraftResponse,
)
from services.agent_control_audit import write_agent_audit_transactional
from services.agent_control_cards import create_agent_card_campaign_draft
from services.card_campaign_service import (
    CardAudienceNotReconciled,
    CardCampaignError,
    CardCampaignIdempotencyConflict,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(dependencies=[Depends(require_agent_control)])
Database = Annotated[AsyncSession, Depends(get_db)]
Agent = Annotated[dict, Depends(require_agent_control)]


@router.post(
    "/crm/card-campaign-drafts",
    response_model=AgentCardCampaignDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_card_campaign_draft(
    payload: AgentCardCampaignDraftRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> AgentCardCampaignDraftResponse:
    try:
        result = await create_agent_card_campaign_draft(db, payload)
    except CardCampaignIdempotencyConflict:
        raise HTTPException(409, "card_campaign_request_id_conflict") from None
    except CardAudienceNotReconciled as exc:
        raise HTTPException(503, str(exc)) from None
    except CardCampaignError as exc:
        raise HTTPException(422, str(exc)) from None
    await write_agent_audit_transactional(
        db,
        request=request,
        actor=agent["actor"],
        action_id="crm.card_campaign_drafts.create",
        status_code=status.HTTP_201_CREATED,
        allowed=True,
        request_meta={
            "include_birthdays": payload.include_birthdays,
            "include_home_anniversaries": payload.include_home_anniversaries,
            "month": payload.month,
        },
        response_meta={
            "campaign_id": str(result.campaign_id),
            "missing_address_count": result.missing_address_count,
            "provider_connected": result.provider_connected,
            "sendable_recipients": result.sendable_recipients,
            "status": result.status,
            "total_recipients": result.total_recipients,
        },
    )
    return result


__all__ = ["router"]
