"""Authenticated Command card campaign review and approval routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import AdminSubject, require_admin
from schemas.card_campaign import (
    CardCampaignApproveRequest,
    CardCampaignDetail,
    CardCampaignDraftRequest,
    CardCampaignPage,
    CardCampaignUpdateRequest,
)
from services.agent_control_audit import write_agent_audit_transactional
from services.card_campaign_service import (
    CardAudienceNotReconciled,
    CardCampaignAlreadyAttempted,
    CardCampaignConfirmationMismatch,
    CardCampaignError,
    CardCampaignIdempotencyConflict,
    CardCampaignNotFound,
    CardCampaignNotReady,
    CardCampaignService,
    CardCampaignVersionConflict,
)
from services.card_provider import configured_card_provider

router = APIRouter(dependencies=[Depends(require_admin)])
Database = Annotated[AsyncSession, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=50)]
Offset = Annotated[int, Query(ge=0, le=2_147_483_647)]


def card_campaign_service() -> CardCampaignService:
    return CardCampaignService(provider=configured_card_provider())


def _raise_http(exc: CardCampaignError) -> None:
    if isinstance(exc, CardCampaignNotFound):
        raise HTTPException(404, str(exc)) from None
    if isinstance(exc, CardAudienceNotReconciled):
        raise HTTPException(503, str(exc)) from None
    if isinstance(
        exc,
        (
            CardCampaignAlreadyAttempted,
            CardCampaignConfirmationMismatch,
            CardCampaignIdempotencyConflict,
            CardCampaignNotReady,
            CardCampaignVersionConflict,
        ),
    ):
        raise HTTPException(409, str(exc)) from None
    raise HTTPException(422, str(exc)) from None


async def _audit(
    db: AsyncSession,
    *,
    request: Request,
    actor: str,
    action_id: str,
    result: CardCampaignDetail,
    status_code: int = status.HTTP_200_OK,
) -> None:
    await write_agent_audit_transactional(
        db,
        request=request,
        actor=actor,
        action_id=action_id,
        status_code=status_code,
        allowed=True,
        request_meta={},
        response_meta={
            "campaign_id": str(result.id),
            "missing_address_count": result.missing_address_count,
            "provider_connected": result.provider_connected,
            "sendable_recipients": result.sendable_recipients,
            "status": result.status,
            "version": result.version,
        },
    )


@router.get("/cards/campaigns", response_model=CardCampaignPage)
async def list_card_campaigns(
    db: Database,
    limit: Limit = 25,
    offset: Offset = 0,
) -> CardCampaignPage:
    return await card_campaign_service().list_campaigns(db, limit=limit, offset=offset)


@router.post(
    "/cards/campaigns/drafts",
    response_model=CardCampaignDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_card_campaign(
    payload: CardCampaignDraftRequest,
    request: Request,
    db: Database,
    admin: AdminSubject,
) -> CardCampaignDetail:
    try:
        result = await card_campaign_service().create_or_get_draft(db, payload)
    except CardCampaignError as exc:
        _raise_http(exc)
    await _audit(
        db,
        request=request,
        actor=f"admin:{admin}",
        action_id="command.card_campaigns.draft.create",
        result=result,
        status_code=status.HTTP_201_CREATED,
    )
    return result


@router.get("/cards/campaigns/{campaign_id}", response_model=CardCampaignDetail)
async def get_card_campaign(
    campaign_id: UUID,
    db: Database,
) -> CardCampaignDetail:
    try:
        return await card_campaign_service().get_campaign(db, campaign_id)
    except CardCampaignError as exc:
        _raise_http(exc)


@router.patch("/cards/campaigns/{campaign_id}", response_model=CardCampaignDetail)
async def update_card_campaign(
    campaign_id: UUID,
    payload: CardCampaignUpdateRequest,
    request: Request,
    db: Database,
    admin: AdminSubject,
) -> CardCampaignDetail:
    try:
        result = await card_campaign_service().update_campaign(
            db,
            campaign_id,
            payload,
            actor=f"admin:{admin}",
        )
    except CardCampaignError as exc:
        _raise_http(exc)
    await _audit(
        db,
        request=request,
        actor=f"admin:{admin}",
        action_id="command.card_campaigns.update",
        result=result,
    )
    return result


@router.post(
    "/cards/campaigns/{campaign_id}/approve-and-send",
    response_model=CardCampaignDetail,
)
async def approve_and_send_card_campaign(
    campaign_id: UUID,
    payload: CardCampaignApproveRequest,
    request: Request,
    db: Database,
    admin: AdminSubject,
) -> CardCampaignDetail:
    try:
        result = await card_campaign_service().approve_and_send(
            db,
            campaign_id,
            payload,
            actor=f"admin:{admin}",
        )
    except CardCampaignError as exc:
        _raise_http(exc)
    await _audit(
        db,
        request=request,
        actor=f"admin:{admin}",
        action_id="command.card_campaigns.approve_and_send",
        result=result,
    )
    return result


__all__ = ["card_campaign_service", "router"]
