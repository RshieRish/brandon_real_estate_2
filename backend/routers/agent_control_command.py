"""Protected, read-only Command Contacts capabilities for Sydney."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.agent_control import require_agent_control
from schemas.agent_control_command import (
    CommandContactAudiencePreviewRequest,
    CommandContactAudiencePreviewResponse,
    CommandContactsSearchRequest,
    CommandContactsSearchResponse,
)
from services.agent_control_audit import write_agent_audit
from services.agent_control_command import (
    CommandContactAudienceChanged,
    CommandContactsUnavailable,
    preview_command_contact_audience,
    search_command_contacts,
)

router = APIRouter(dependencies=[Depends(require_agent_control)])
Database = Annotated[AsyncSession, Depends(get_db)]
Agent = Annotated[dict, Depends(require_agent_control)]


async def _audit(
    db: AsyncSession,
    *,
    request: Request,
    agent: dict,
    action_id: str,
    request_meta: dict[str, object],
    response_meta: dict[str, object],
) -> None:
    await write_agent_audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id=action_id,
        status_code=200,
        allowed=True,
        request_meta=request_meta,
        response_meta=response_meta,
    )


def _filter_meta(payload) -> dict[str, object]:
    return {
        "has_query": payload.query is not None,
        "has_stage": payload.stage is not None,
        "tag_count": len(payload.tag_ids),
        "source_count": len(payload.sources),
        "origin_count": len(payload.origins),
    }


@router.post(
    "/crm/command-contacts/search",
    response_model=CommandContactsSearchResponse,
)
async def command_contacts_search(
    payload: CommandContactsSearchRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> CommandContactsSearchResponse:
    try:
        result = await search_command_contacts(db, payload)
    except CommandContactsUnavailable:
        raise HTTPException(503, "command_contacts_unavailable") from None
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="crm.command_contacts.search",
        request_meta={
            **_filter_meta(payload),
            "page": payload.page,
            "page_size": payload.page_size,
        },
        response_meta={
            "count": len(result.contacts),
            "total": result.total,
            "page": result.page,
            "page_count": result.page_count,
        },
    )
    return result


@router.post(
    "/crm/command-contact-audiences/preview",
    response_model=CommandContactAudiencePreviewResponse,
)
async def command_contact_audience_preview(
    payload: CommandContactAudiencePreviewRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> CommandContactAudiencePreviewResponse:
    try:
        result = await preview_command_contact_audience(db, payload)
    except CommandContactAudienceChanged:
        raise HTTPException(409, "command_contacts_changed_during_preview") from None
    except CommandContactsUnavailable:
        raise HTTPException(503, "command_contacts_unavailable") from None
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="crm.command_contact_audiences.preview",
        request_meta=_filter_meta(payload),
        response_meta={
            "audience_ref": str(result.audience_ref),
            "exact_count": result.exact_count,
            "sample_count": len(result.samples),
        },
    )
    return result
