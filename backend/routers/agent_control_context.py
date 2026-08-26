"""Authenticated, bounded control-plane routes for Sydney durable context."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Annotated, NoReturn

from config import settings
from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from middleware.agent_control import require_agent_control
from schemas.sydney_context import (
    ContextEventBatchRequest,
    ContextEventBatchResponse,
    ContextHealthResponse,
    ContextHistorySearchRequest,
    ContextHistorySearchResponse,
    ContextPacket,
    ContextRetrieveRequest,
    ContextRunClaimRequest,
    ContextRunClaimResponse,
    ContextRunLeaseRenewRequest,
    ContextRunStartRequest,
    ContextRunStartResponse,
    ContextRunSummary,
    ContextRunUpdateRequest,
    ContextSessionReconciliationRequest,
    ContextSessionReconciliationResponse,
    ContextToolInvocationRequest,
    ContextToolInvocationResponse,
    ContextToolInvocationUpdateRequest,
)
from services.agent_control_audit import write_agent_audit
from services.sydney_context_service import (
    ContextEventConflict,
    ContextRunConflict,
    ContextSessionConflict,
    ContextToolConflict,
    claim_runs,
    get_context_health,
    ingest_event_batch,
    reconcile_session,
    renew_run_lease,
    retrieve_context,
    search_history,
    start_run,
    start_tool_invocation,
    update_run_state,
    update_tool_invocation,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import NoResultFound

router = APIRouter(dependencies=[Depends(require_agent_control)])

_CONFLICTS = (
    ContextEventConflict,
    ContextSessionConflict,
    ContextRunConflict,
    ContextToolConflict,
)
_CONTEXT_ERRORS = (*_CONFLICTS, NoResultFound)
Database = Annotated[AsyncSession, Depends(get_db)]
Agent = Annotated[dict, Depends(require_agent_control)]


def _require_master() -> None:
    if not settings.SYDNEY_DURABLE_CONTEXT_ENABLED:
        raise HTTPException(503, "sydney_durable_context_disabled")


def _require_retrieval() -> None:
    _require_master()
    if not settings.SYDNEY_DURABLE_CONTEXT_RETRIEVAL_ENABLED:
        raise HTTPException(503, "sydney_context_retrieval_disabled")


def _require_retry() -> None:
    _require_master()
    if not settings.SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED:
        raise HTTPException(503, "sydney_context_retry_disabled")


def _configured_secrets() -> Sequence[str]:
    secret_names = (
        "DATABASE_URL",
        "GMAIL_HISTORY_DATABASE_URL",
        "GMAIL_PARTICIPANT_HASH_KEY",
        "AGENT_CONTROL_TOKEN",
        "BRANDON_AGENT_CONTROL_TOKEN",
        "GEMINI_API_KEY",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_CALENDAR_CLIENT_SECRET",
        "GOOGLE_WORKSPACE_CLIENT_SECRET",
        "GOOGLE_WORKSPACE_REFRESH_TOKEN",
        "JWT_SECRET",
        "SMTP_PASS",
        "GOOGLE_MAPS_API_KEY",
        "GOOGLE_CALENDAR_REFRESH_TOKEN",
        "RENTCAST_API_KEY",
        "R2_SECRET_ACCESS_KEY",
        "TELEGRAM_BOT_TOKEN",
        "SYDNEY_TELEGRAM_BOT_TOKEN",
        "SYDNEY_CLARIFICATION_CODE_KEYS_JSON",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
    )
    values: list[str] = []
    for name in secret_names:
        for candidate in (getattr(settings, name, ""), os.environ.get(name, "")):
            if isinstance(candidate, str) and candidate and candidate not in values:
                values.append(candidate)
    return tuple(values)


async def _audit(
    db: AsyncSession,
    *,
    request: Request,
    agent: dict,
    action_id: str,
    request_meta: dict[str, object] | None = None,
    response_meta: dict[str, object] | None = None,
) -> None:
    await write_agent_audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id=action_id,
        status_code=200,
        allowed=True,
        request_meta=request_meta or {},
        response_meta=response_meta or {},
    )


def _raise_bounded(error: Exception) -> NoReturn:
    if isinstance(error, NoResultFound):
        raise HTTPException(404, "sydney_context_record_not_found") from None
    raise HTTPException(409, str(error)) from None


@router.post("/context/events/batch", response_model=ContextEventBatchResponse)
async def ingest_context_events(
    payload: ContextEventBatchRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> ContextEventBatchResponse:
    _require_master()
    try:
        result = await ingest_event_batch(
            db,
            payload,
            configured_secrets=_configured_secrets(),
            segment_chars=settings.SYDNEY_CONTEXT_SEGMENT_CHARS,
            batch_limit=settings.SYDNEY_CONTEXT_EVENT_BATCH_LIMIT,
        )
    except _CONTEXT_ERRORS as error:
        _raise_bounded(error)
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="context.events.ingest",
        response_meta={
            "inserted_count": result.inserted_count,
            "replayed_count": result.replayed_count,
            "event_count": len(result.event_ids),
        },
    )
    return result


@router.post(
    "/context/sessions/reconcile",
    response_model=ContextSessionReconciliationResponse,
)
async def reconcile_context_session(
    payload: ContextSessionReconciliationRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> ContextSessionReconciliationResponse:
    _require_master()
    try:
        result = await reconcile_session(
            db,
            identity_id=payload.identity_id,
            hermes_session_id=payload.hermes_session_id,
            expected_event_count=payload.expected_event_count,
            expected_ordered_hash=payload.expected_ordered_hash,
        )
    except _CONTEXT_ERRORS as error:
        _raise_bounded(error)
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="context.sessions.reconcile",
        request_meta={"expected_event_count": payload.expected_event_count},
        response_meta={
            "event_count": result.event_count,
            "matched": result.matched,
        },
    )
    return result


@router.post("/context/retrieve", response_model=ContextPacket)
async def retrieve_context_packet(
    payload: ContextRetrieveRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> ContextPacket:
    _require_retrieval()
    configured_budget = max(
        256,
        min(int(settings.SYDNEY_CONTEXT_RECALL_TOKEN_BUDGET), 16_000),
    )
    effective_payload = payload.model_copy(
        update={"token_budget": min(payload.token_budget, configured_budget)}
    )
    try:
        result = await retrieve_context(db, effective_payload)
    except _CONTEXT_ERRORS as error:
        _raise_bounded(error)
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="context.retrieve",
        request_meta={"token_budget": effective_payload.token_budget},
        response_meta={
            "estimated_tokens": result.estimated_tokens,
            "section_count": len(result.sections),
            "degraded": result.degraded,
        },
    )
    return result


@router.post("/context/history/search", response_model=ContextHistorySearchResponse)
async def search_context_history(
    payload: ContextHistorySearchRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> ContextHistorySearchResponse:
    _require_retrieval()
    try:
        result = await search_history(db, payload)
    except _CONTEXT_ERRORS as error:
        _raise_bounded(error)
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="context.history.search",
        request_meta={
            "event_type_count": len(payload.event_types),
            "has_query": payload.query is not None,
            "has_date_range": payload.started_at is not None
            or payload.ended_at is not None,
            "around_event": payload.around_event_id is not None,
            "recent_conversations": payload.recent_conversations,
            "limit": payload.limit,
        },
        response_meta={
            "count": len(result.events),
            "total": result.total,
            "truncated": result.truncated,
        },
    )
    return result


@router.post("/context/runs/start", response_model=ContextRunStartResponse)
async def start_context_run(
    payload: ContextRunStartRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> ContextRunStartResponse:
    _require_master()
    try:
        result = await start_run(db, payload)
    except _CONTEXT_ERRORS as error:
        _raise_bounded(error)
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="context.runs.start",
        response_meta={
            "run_id": str(result.run.id),
            "state": result.run.state,
            "replayed": result.replayed,
        },
    )
    return result


@router.post("/context/runs/update", response_model=ContextRunSummary)
async def update_context_run(
    payload: ContextRunUpdateRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> ContextRunSummary:
    _require_master()
    try:
        result = await update_run_state(db, payload)
    except _CONTEXT_ERRORS as error:
        _raise_bounded(error)
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="context.runs.update",
        response_meta={"run_id": str(result.id), "state": result.state},
    )
    return result


@router.post("/context/runs/claim", response_model=ContextRunClaimResponse)
async def claim_context_runs(
    payload: ContextRunClaimRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> ContextRunClaimResponse:
    _require_retry()
    try:
        result = await claim_runs(
            db,
            payload,
            lease_seconds=settings.SYDNEY_CONTEXT_RUN_LEASE_SECONDS,
        )
    except _CONTEXT_ERRORS as error:
        _raise_bounded(error)
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="context.runs.claim",
        request_meta={"limit": payload.limit},
        response_meta={"count": len(result.runs)},
    )
    return result


@router.post("/context/runs/renew", response_model=ContextRunSummary)
async def renew_context_run_lease(
    payload: ContextRunLeaseRenewRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> ContextRunSummary:
    _require_retry()
    try:
        result = await renew_run_lease(
            db,
            payload,
            lease_seconds=settings.SYDNEY_CONTEXT_RUN_LEASE_SECONDS,
        )
    except _CONTEXT_ERRORS as error:
        _raise_bounded(error)
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="context.runs.renew",
        response_meta={"run_id": str(result.id), "state": result.state},
    )
    return result


@router.post("/context/tools/start", response_model=ContextToolInvocationResponse)
async def start_context_tool(
    payload: ContextToolInvocationRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> ContextToolInvocationResponse:
    _require_master()
    try:
        result = await start_tool_invocation(db, payload)
    except _CONTEXT_ERRORS as error:
        _raise_bounded(error)
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="context.tools.start",
        response_meta={
            "invocation_id": str(result.invocation_id),
            "state": result.state,
            "replay_decision": result.replay_decision,
        },
    )
    return result


@router.post("/context/tools/update", response_model=ContextToolInvocationResponse)
async def update_context_tool(
    payload: ContextToolInvocationUpdateRequest,
    request: Request,
    db: Database,
    agent: Agent,
) -> ContextToolInvocationResponse:
    _require_master()
    try:
        result = await update_tool_invocation(db, payload)
    except _CONTEXT_ERRORS as error:
        _raise_bounded(error)
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="context.tools.update",
        response_meta={
            "invocation_id": str(result.invocation_id),
            "state": result.state,
            "replay_decision": result.replay_decision,
        },
    )
    return result


@router.get("/context/health", response_model=ContextHealthResponse)
async def context_health(
    request: Request,
    db: Database,
    agent: Agent,
) -> ContextHealthResponse:
    flags = {
        "durable_context": settings.SYDNEY_DURABLE_CONTEXT_ENABLED,
        "retrieval": settings.SYDNEY_DURABLE_CONTEXT_RETRIEVAL_ENABLED,
        "projection": settings.SYDNEY_DURABLE_CONTEXT_PROJECTION_ENABLED,
        "retry": settings.SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED,
    }
    result = await get_context_health(db, flags=flags)
    await _audit(
        db,
        request=request,
        agent=agent,
        action_id="context.health.read",
        response_meta={
            "status": result.status,
            "identity_count": result.identity_count,
            "session_count": result.session_count,
            "event_count": result.event_count,
            "checkpoint_lag_events": result.checkpoint_lag_events,
            "run_states": result.run_states,
        },
    )
    return result
