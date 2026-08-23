"""Administrator controls for the Gmail-to-Sydney task intake pipeline."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from config import settings
from database import get_db
from middleware.auth import AdminSubject, require_admin
from models.gmail_task_intake import (
    CRMTaskSuggestion,
    CRMTaskSuggestionSuppression,
    GmailBackfillRequest,
    GmailMessageOrigin,
    GmailMessageReceipt,
    GmailSyncAccount,
    GmailSyncRun,
)
from models.integration_health import IntegrationHealthState, IntegrationWorkerHeartbeat
from models.sydney_tasks import SydneyQuestionOutbox
from models.sydney_tasks import CRMTaskSuggestionEvent
from routers.agent_control_crm import _BorrowedSessionFactory
from routers.workspace import load_workspace_refresh_token_from_db
from schemas.agent_control_crm import (
    GmailSendIntentReconcileRequest,
    GmailTaskBackfillRequest,
    GmailTaskReprocessRequest,
    TelegramReconcileRequest,
    TelegramRetryRequest,
)
from services.agent_control_audit import write_agent_audit_transactional
from services.gmail_history_adapter import (
    GmailHistoryAdapter,
    build_gmail_service,
    parse_gmail_history_id,
)
from services.gmail_origin_service import (
    GmailOriginService,
    GmailProviderFailure,
    GmailSendConflict,
    get_agent_gmail_provider_executor,
)
from services.notification_service import enqueue_notification
from services.integration_advisory_locks import account_advisory_key
from services.crm_task_suggestion_service import gmail_source_scope_key
from services.sydney_telegram_dispatcher import (
    SydneyTelegramDispatcher,
    SydneyTelegramDispatcherConfig,
    TelegramConfigurationError,
    TelegramDispatchError,
)
from services.workspace_service import (
    WorkspaceIntegrationError,
    workspace_oauth_client_settings,
)


router = APIRouter(dependencies=[Depends(require_admin)])


def _enabled() -> None:
    if not settings.GMAIL_TASK_INTAKE_ENABLED:
        raise HTTPException(503, "gmail_task_intake_disabled")


def _origin_response(origin: GmailMessageOrigin) -> dict[str, object]:
    return {
        "origin_id": str(origin.id),
        "account_id": str(origin.account_id),
        "request_id": str(origin.request_id) if origin.request_id else None,
        "delivery_state": origin.delivery_state,
        "reconciled_outcome": origin.reconciled_outcome,
        "version": origin.version,
        "message_id": origin.gmail_message_id,
        "thread_id": origin.gmail_thread_id,
        "failure_category": origin.failure_category,
        "quarantine_category": origin.quarantine_category,
    }


async def _exact_origin(db: AsyncSession, request_id: UUID, *, lock: bool = False):
    query = select(GmailMessageOrigin).where(
        GmailMessageOrigin.request_id == request_id
    )
    if lock:
        query = query.with_for_update()
    rows = list((await db.scalars(query.limit(2))).all())
    if not rows:
        raise HTTPException(404, "gmail_send_intent_not_found")
    if len(rows) != 1:
        raise HTTPException(409, "gmail_send_intent_ambiguous")
    return rows[0]


@router.get("/gmail-task-intake/status")
async def gmail_task_intake_status(
    _actor_subject: AdminSubject,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    account_count = int(
        await db.scalar(select(func.count()).select_from(GmailSyncAccount)) or 0
    )
    active_runs = int(
        await db.scalar(
            select(func.count())
            .select_from(GmailSyncRun)
            .where(GmailSyncRun.state.in_(("running", "discovered")))
        )
        or 0
    )
    pending_receipts = int(
        await db.scalar(
            select(func.count())
            .select_from(GmailMessageReceipt)
            .where(GmailMessageReceipt.processing_state.in_(("pending", "failed")))
        )
        or 0
    )
    health = await db.get(IntegrationHealthState, "gmail")
    heartbeat = await db.scalar(
        select(IntegrationWorkerHeartbeat)
        .order_by(IntegrationWorkerHeartbeat.heartbeat_at.desc())
        .limit(1)
    )
    return {
        "enabled": settings.GMAIL_TASK_INTAKE_ENABLED,
        "question_delivery_enabled": settings.SYDNEY_TASK_QUESTIONS_ENABLED,
        "account_count": account_count,
        "active_runs": active_runs,
        "pending_receipts": pending_receipts,
        "health": health.state if health else "unknown",
        "last_checked_at": health.last_checked_at if health else None,
        "worker_heartbeat_at": heartbeat.heartbeat_at if heartbeat else None,
    }


@router.post("/gmail-task-intake/check")
async def check_gmail_task_intake(
    actor_subject: AdminSubject,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    _enabled()
    async with db.begin():
        await write_agent_audit_transactional(
            db,
            request=request,
            actor=f"command_admin:{actor_subject}",
            action_id="gmail_task_intake.check.requested",
            status_code=202,
            allowed=True,
        )
    return {"accepted": True, "execution": "integration_worker"}


@router.post("/gmail-task-intake/backfill", status_code=201)
async def create_gmail_task_backfill(
    payload: GmailTaskBackfillRequest,
    actor_subject: AdminSubject,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    _enabled()
    async with db.begin():
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": account_advisory_key(payload.account_id)},
        )
        account = await db.scalar(
            select(GmailSyncAccount)
            .where(GmailSyncAccount.id == payload.account_id)
            .with_for_update()
        )
        if (
            account is None
            or account.blocked_reason != "history_cursor_expired"
            or account.committed_history_id is None
            or account.reseed_history_id is None
        ):
            raise HTTPException(409, "gmail_backfill_not_available")
        try:
            expired_history_id = parse_gmail_history_id(account.committed_history_id)
            reseed_history_id = parse_gmail_history_id(account.reseed_history_id)
            if int(reseed_history_id) < int(expired_history_id):
                raise ValueError
        except ValueError:
            raise HTTPException(409, "gmail_backfill_snapshot_invalid") from None
        active = await db.scalar(
            select(GmailBackfillRequest.id).where(
                GmailBackfillRequest.account_id == account.id,
                GmailBackfillRequest.state.in_(("requested", "running")),
            )
        )
        if active is not None:
            raise HTTPException(409, "active_backfill_exists")
        audit = await write_agent_audit_transactional(
            db,
            request=request,
            actor=f"command_admin:{actor_subject}",
            action_id="gmail_task_intake.backfill.requested",
            status_code=201,
            allowed=True,
            request_meta={
                "account_id": str(account.id),
                "reason_length": len(payload.reason),
            },
        )
        row = GmailBackfillRequest(
            id=uuid4(),
            account_id=account.id,
            administrator_id=int(actor_subject),
            reason=payload.reason.strip(),
            window_start=payload.window_start,
            window_end=payload.window_end,
            expired_history_id=expired_history_id,
            reseed_history_id=reseed_history_id,
            audit_id=audit.id,
            state="requested",
        )
        db.add(row)
        await db.flush()
    return {"request_id": str(row.id), "state": row.state}


@router.post("/gmail-task-intake/reprocess/{receipt_id}")
async def reprocess_gmail_task_receipt(
    receipt_id: UUID,
    payload: GmailTaskReprocessRequest,
    actor_subject: AdminSubject,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    _enabled()
    async with db.begin():
        receipt = await db.scalar(
            select(GmailMessageReceipt)
            .where(GmailMessageReceipt.id == receipt_id)
            .with_for_update()
        )
        if receipt is None:
            raise HTTPException(404, "gmail_receipt_not_found")
        if receipt.processing_state not in {"failed", "ignored"}:
            raise HTTPException(409, "gmail_receipt_not_reprocessable")
        suppression = None
        if payload.suppression_id is not None:
            suppression = await db.scalar(
                select(CRMTaskSuggestionSuppression)
                .where(CRMTaskSuggestionSuppression.id == payload.suppression_id)
                .with_for_update()
            )
            expected_scope = gmail_source_scope_key(
                receipt.account_id,
                receipt.gmail_thread_id,
            )
            if (
                suppression is None
                or suppression.source_type != "gmail_message"
                or suppression.source_scope_key != expected_scope
                or (
                    suppression.reprocess_override_at is not None
                    and suppression.reprocess_override_consumed_at is None
                )
            ):
                raise HTTPException(409, "gmail_suppression_override_invalid")
        receipt.processing_state = "pending"
        receipt.failure_category = None
        receipt.failure_message = None
        receipt.processing_started_at = None
        receipt.processed_at = None
        if suppression is None:
            await write_agent_audit_transactional(
                db,
                request=request,
                actor=f"command_admin:{actor_subject}",
                action_id="gmail_task_intake.receipt.reprocess",
                status_code=200,
                allowed=True,
                request_meta={
                    "receipt_id": str(receipt_id),
                    "reason_length": len(payload.reason),
                },
            )
        else:
            audit = await write_agent_audit_transactional(
                db,
                request=request,
                actor="admin",
                action_id="gmail_task_intake.reprocess",
                status_code=200,
                allowed=True,
                request_meta={
                    "admin_user_id": int(actor_subject),
                    "suppression_id": str(suppression.id),
                },
            )
            override_now = datetime.now(timezone.utc)
            override_at = max(
                override_now,
                audit.created_at or override_now,
            )
            suppression.reprocess_override_at = override_at
            suppression.reprocess_override_consumed_at = None
            suppression.reprocess_override_by_admin_id = int(actor_subject)
            suppression.reprocess_override_audit_id = audit.id
            suggestions = list(
                (
                    await db.scalars(
                        select(CRMTaskSuggestion)
                        .where(
                            CRMTaskSuggestion.source_type == "gmail_message",
                            CRMTaskSuggestion.source_scope_key
                            == suppression.source_scope_key,
                            CRMTaskSuggestion.source_action_key
                            == suppression.source_action_key,
                            CRMTaskSuggestion.obligation_fingerprint
                            == suppression.obligation_fingerprint,
                            CRMTaskSuggestion.primary_instance_digest
                            == suppression.identity_instance_digest,
                        )
                        .with_for_update()
                    )
                ).all()
            )
            for suggestion in suggestions:
                db.add(
                    CRMTaskSuggestionEvent(
                        suggestion_id=suggestion.id,
                        suggestion_version=suggestion.version,
                        event_type="reprocess",
                        actor_type="command_admin",
                        event_data_json=json.dumps(
                            {
                                "administrator_id": int(actor_subject),
                                "receipt_id": str(receipt_id),
                                "suppression_id": str(suppression.id),
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        action_audit_id=audit.id,
                        created_at=override_at,
                    )
                )
    return {"receipt_id": str(receipt.id), "processing_state": receipt.processing_state}


@router.post("/gmail-task-intake/alert-canary", status_code=202)
async def enqueue_gmail_alert_canary(
    actor_subject: AdminSubject,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    _enabled()
    canary_id = uuid4()
    async with db.begin():
        await enqueue_notification(
            db,
            event_type="integration_alert",
            payload={
                "provider": "gmail",
                "event": "canary",
                "canary_id": str(canary_id),
            },
            provider_key="gmail",
            dedupe_key=f"gmail:alert-canary:{canary_id}",
        )
        await write_agent_audit_transactional(
            db,
            request=request,
            actor=f"command_admin:{actor_subject}",
            action_id="gmail_task_intake.alert_canary",
            status_code=202,
            allowed=True,
            response_meta={"canary_id": str(canary_id)},
        )
    return {"canary_id": str(canary_id), "state": "pending"}


@router.get("/gmail-task-intake/send-intents/{request_id}")
async def get_gmail_send_intent(
    request_id: UUID,
    _actor_subject: AdminSubject,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return _origin_response(await _exact_origin(db, request_id))


async def _delivered_reconciliation(
    *,
    db: AsyncSession,
    origin: GmailMessageOrigin,
    payload: GmailSendIntentReconcileRequest,
    request: Request,
    actor_subject: str,
):
    engine = db.bind
    if not isinstance(engine, AsyncEngine):
        raise HTTPException(503, "gmail_reconciliation_database_binding_required")
    try:
        refresh_token = await load_workspace_refresh_token_from_db(db)
        oauth = workspace_oauth_client_settings()
        if not refresh_token:
            raise WorkspaceIntegrationError("missing refresh token")
    except WorkspaceIntegrationError:
        raise HTTPException(503, "gmail_workspace_oauth_config_required") from None
    executor = get_agent_gmail_provider_executor()
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: build_gmail_service(
            refresh_token=refresh_token,
            client_id=oauth.client_id,
            client_secret=oauth.client_secret,
            socket_timeout_seconds=settings.INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS,
        ),
        deadline_seconds=settings.INTEGRATION_PROVIDER_DEADLINE_SECONDS,
        socket_timeout_seconds=settings.INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS,
    )
    profile = await adapter.get_profile(account_key=str(origin.account_id))
    message = await adapter.get_message_content(
        account_key=str(origin.account_id),
        message_id=payload.candidate_message_id or "",
    )

    def fetcher(*, kind: str, message_id: str | None = None, num_retries: int = 0):
        del message_id, num_retries
        return profile if kind == "profile" else message

    service = GmailOriginService(
        engine=engine,
        provider_executor=executor,
        transport=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("reconciliation must never send")
        ),
        deadline_seconds=settings.INTEGRATION_PROVIDER_DEADLINE_SECONDS,
    )
    return await service.reconcile_delivered_candidate(
        account_id=payload.account_id,
        request_id=origin.request_id,
        expected_state=payload.expected_state,
        expected_version=payload.expected_version,
        reason=payload.reason,
        candidate_message_id=payload.candidate_message_id or "",
        candidate_thread_id=payload.candidate_thread_id or "",
        fetcher=fetcher,
        request=request,
        actor=f"command_admin:{actor_subject}",
    )


@router.post("/gmail-task-intake/send-intents/{request_id}/reconcile")
async def reconcile_gmail_send_intent(
    request_id: UUID,
    payload: GmailSendIntentReconcileRequest,
    actor_subject: AdminSubject,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    _enabled()
    origin = await _exact_origin(db, request_id)
    if origin.account_id != payload.account_id or origin.request_id is None:
        raise HTTPException(409, "gmail_reconciliation_state_conflict")
    engine = db.bind
    if not isinstance(engine, AsyncEngine):
        raise HTTPException(503, "gmail_reconciliation_database_binding_required")
    service = GmailOriginService(
        engine=engine,
        provider_executor=get_agent_gmail_provider_executor(),
        transport=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("reconciliation must never send")
        ),
        deadline_seconds=settings.INTEGRATION_PROVIDER_DEADLINE_SECONDS,
    )
    try:
        if payload.outcome == "delivered":
            result = await _delivered_reconciliation(
                db=db,
                origin=origin,
                payload=payload,
                request=request,
                actor_subject=actor_subject,
            )
        else:
            result = await service.mark_not_delivered(
                account_id=payload.account_id,
                request_id=request_id,
                expected_state=payload.expected_state,
                expected_version=payload.expected_version,
                reason=payload.reason,
                request=request,
                actor=f"command_admin:{actor_subject}",
            )
    except GmailSendConflict as error:
        raise HTTPException(error.status_code, error.category) from None
    except GmailProviderFailure as error:
        raise HTTPException(503, error.category) from None
    return {
        "request_id": str(result.request_id),
        "delivery_state": result.delivery_state,
        "reconciled_outcome": result.reconciled_outcome,
        "version": result.version,
        "message_id": result.message_id,
        "thread_id": result.thread_id,
        "quarantine_category": result.quarantine_category,
    }


def _telegram_dispatcher(db: AsyncSession) -> SydneyTelegramDispatcher:
    if not settings.SYDNEY_TASK_QUESTIONS_ENABLED:
        raise HTTPException(503, "sydney_task_questions_disabled")
    try:
        raw = json.loads(settings.SYDNEY_CLARIFICATION_CODE_KEYS_JSON)
        keys = {
            int(version): base64.b64decode(value, validate=True)
            for version, value in raw.items()
        }
        config = SydneyTelegramDispatcherConfig(
            enabled=settings.SYDNEY_TASK_QUESTIONS_ENABLED,
            bot_token=settings.SYDNEY_TELEGRAM_BOT_TOKEN,
            brandon_chat_id=settings.SYDNEY_TELEGRAM_BRANDON_CHAT_ID,
            clarification_code_keys=keys,
            active_code_key_version=settings.SYDNEY_CLARIFICATION_ACTIVE_KEY_VERSION,
            provider_deadline_seconds=settings.INTEGRATION_PROVIDER_DEADLINE_SECONDS,
            provider_socket_timeout_seconds=settings.INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS,
        )
    except (AttributeError, TypeError, ValueError, TelegramConfigurationError):
        raise HTTPException(503, "sydney_telegram_configuration_invalid") from None
    return SydneyTelegramDispatcher(
        sessionmaker=_BorrowedSessionFactory(db),
        executor=object(),
        send_message=lambda **_kwargs: None,
        config=config,
        clock=lambda: datetime.now(timezone.utc),
    )


@router.post("/gmail-task-intake/clarifications/{id}/reconcile")
async def reconcile_clarification_delivery(
    id: UUID,
    payload: TelegramReconcileRequest,
    actor_subject: AdminSubject,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    dispatcher = _telegram_dispatcher(db)
    try:
        async with db.begin():
            audit = await write_agent_audit_transactional(
                db,
                request=request,
                actor=f"command_admin:{actor_subject}",
                action_id="gmail_task_intake.clarification.reconcile",
                status_code=200,
                allowed=True,
                request_meta={"attempt_id": str(id), "outcome": payload.outcome},
            )
            await dispatcher.reconcile_attempt(
                id,
                payload.expected_state,
                payload.outcome,
                payload.reason,
                audit.id,
                payload.observed_chat_id,
                payload.observed_message_id,
            )
    except TelegramDispatchError as error:
        raise HTTPException(409, str(error)) from None
    attempt = await db.get(SydneyQuestionOutbox, id)
    return {
        "attempt_id": str(id),
        "state": attempt.state if attempt else None,
        "reconciled_outcome": attempt.reconciled_outcome if attempt else None,
    }


@router.post("/gmail-task-intake/clarifications/{id}/retry", status_code=201)
async def retry_clarification_delivery(
    id: UUID,
    payload: TelegramRetryRequest,
    actor_subject: AdminSubject,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    dispatcher = _telegram_dispatcher(db)
    try:
        async with db.begin():
            audit = await write_agent_audit_transactional(
                db,
                request=request,
                actor=f"command_admin:{actor_subject}",
                action_id="gmail_task_intake.clarification.retry",
                status_code=201,
                allowed=True,
                request_meta={
                    "attempt_id": str(id),
                    "reason_length": len(payload.reason),
                },
            )
            retry = await dispatcher.create_initial_retry(id, payload.reason, audit.id)
    except TelegramDispatchError as error:
        raise HTTPException(409, str(error)) from None
    return {"attempt_id": str(retry.id), "state": retry.state}


__all__ = ["router"]
