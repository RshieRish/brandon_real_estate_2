from __future__ import annotations

import asyncio
import hashlib
import json
import unicodedata
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "84d7a5f9b2c3"
UTC = timezone.utc


def _identity_instance_digest(title: str, description: str) -> str:
    payload = {
        "description": " ".join(
            unicodedata.normalize("NFKC", description).casefold().split()
        ),
        "title": " ".join(
            unicodedata.normalize("NFKC", title).casefold().split()
        ),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


@pytest.fixture(scope="module")
def suggestion_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def suggestion_runtime(suggestion_database):
    from models.lead import Lead

    # CRMContact's optional lead FK must be present in the shared SQLAlchemy
    # metadata before ORM flushes exercise contact authority.
    assert Lead.__table__.name == "leads"
    url, sync_engine = suggestion_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE gmail_sync_accounts, admin_users, "
                "agent_action_audits, crm_contacts CASCADE"
            )
        )
    engine = create_async_engine(
        async_test_url(url),
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessions
    finally:
        await engine.dispose()


async def _seed_account(sessions, *, email: str | None = None):
    from models.gmail_task_intake import GmailSyncAccount

    row = GmailSyncAccount(
        workspace_email=email or f"brandon-{uuid4()}@example.test",
        committed_history_id="100",
        mode="shadow",
    )
    async with sessions() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def _seed_receipt(
    sessions,
    *,
    account_id: UUID,
    thread_id: str,
    direction: str = "received",
    message_id: str | None = None,
    subject: str = "Showing follow-up",
    sender_hmac: str | None = "a" * 64,
    recipient_hmacs: tuple[str, ...] = ("b" * 64,),
):
    from models.gmail_task_intake import GmailMessageReceipt

    row = GmailMessageReceipt(
        account_id=account_id,
        gmail_message_id=message_id or f"message-{uuid4()}",
        gmail_thread_id=thread_id,
        direction=direction,
        message_at=datetime(2026, 8, 21, 14, 0, tzinfo=UTC),
        sender_hmac=sender_hmac,
        recipient_hmacs_json=json.dumps(list(recipient_hmacs)),
        subject_preview=subject,
        body_hash="c" * 64,
        labels_json=json.dumps(["INBOX"] if direction == "received" else ["SENT"]),
        processing_state="processing",
        classification="eligible",
        processing_started_at=datetime(2026, 8, 21, 14, 1, tzinfo=UTC),
    )
    async with sessions() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


def _obligation(**overrides: object):
    from services.gmail_task_extractor import ExtractedGmailObligation

    values: dict[str, object] = {
        "kind": "incoming_request",
        "action_key": "action-v1:" + "1" * 64,
        "title": "Call Alice about the showing",
        "description": "Discuss Alice's feedback from the property showing.",
        "priority": "normal",
        "due_at": datetime(2026, 8, 22, 19, 0, tzinfo=UTC),
        "timezone_basis": "America/New_York",
        "due_at_ambiguous": False,
        "requested_owner": None,
        "owner_ambiguous": False,
        "requested_link_type": None,
        "requested_link_id": None,
        "contact_hint": None,
        "obligation_fingerprint": "2" * 64,
        "confidence": 0.94,
        "rationale": "The message explicitly requests a follow-up call.",
        "evidence_preview": "Please call Alice tomorrow at 3 PM Eastern.",
    }
    values.update(overrides)
    if "identity_instance_digest" not in overrides:
        values["identity_instance_digest"] = _identity_instance_digest(
            str(values["title"]),
            str(values["description"]),
        )
    if "participant_reconciliation_action_key" not in overrides:
        values["participant_reconciliation_action_key"] = (
            values.get("reconciliation_action_key") or values["action_key"]
        )
    if "participant_obligation_fingerprint" not in overrides:
        values["participant_obligation_fingerprint"] = values[
            "obligation_fingerprint"
        ]
    return ExtractedGmailObligation(**values)


def _extraction(receipt, *obligations, schema_version: str = "gmail-task-v1"):
    from services.gmail_task_extractor import (
        GmailExtractionResult,
        gmail_participant_evidence_hash,
    )

    return GmailExtractionResult(
        account_id=receipt.account_id,
        message_id=receipt.gmail_message_id,
        thread_id=receipt.gmail_thread_id,
        direction=receipt.direction,
        body_hash=receipt.body_hash,
        subject_evidence_hash=hashlib.sha256(
            (receipt.subject_preview or "").encode("utf-8")
        ).hexdigest(),
        reference_message_at=receipt.message_at,
        participant_evidence_hash=gmail_participant_evidence_hash(
            direction=receipt.direction,
            sender_hmac=receipt.sender_hmac,
            recipient_hmacs=tuple(json.loads(receipt.recipient_hmacs_json)),
        ),
        schema_version=schema_version,
        obligations=tuple(obligations),
    )


async def _claim_and_reconcile(service, receipt, extraction):
    claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )
    return await service.reconcile_attempt(claim=claim, extraction=extraction)


def _model_action(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "incoming_request",
        "semantic_action": "call",
        "semantic_object": "showing_feedback",
        "title": "Call Alice about the showing",
        "description": "Discuss Alice's feedback from the property showing.",
        "priority": "normal",
        "due_at": "2026-08-22T19:00:00Z",
        "timezone_basis": "America/New_York",
        "due_at_ambiguous": False,
        "requested_owner": None,
        "owner_ambiguous": False,
        "requested_link_type": None,
        "requested_link_id": None,
        "contact_hint": None,
        "confidence": 0.94,
        "rationale": "The message explicitly requests a follow-up call.",
    }
    payload.update(overrides)
    return payload


async def _extract_model_actions(
    receipt,
    *actions: dict[str, object],
    schema_version: str = "gmail-task-v1",
):
    from services.gmail_message_sanitizer import SanitizedGmailMessage
    from services.gmail_task_extractor import GmailTaskExtractor
    from services.integration_health_service import BoundedProviderExecutor

    response = {
        "schema_version": schema_version,
        "actions": list(actions),
    }
    transient = SanitizedGmailMessage(
        message_id=receipt.gmail_message_id,
        thread_id=receipt.gmail_thread_id,
        direction=receipt.direction,
        message_at=receipt.message_at,
        sender_hmac=receipt.sender_hmac,
        recipient_hmacs=tuple(json.loads(receipt.recipient_hmacs_json)),
        subject_preview=receipt.subject_preview,
        body_hash=receipt.body_hash,
        labels=("INBOX",) if receipt.direction == "received" else ("SENT",),
        processing_state="processing",
        classification="eligible",
        transient_body_text="\n".join(str(action["title"]) for action in actions),
        body_truncated=False,
    )
    executor = BoundedProviderExecutor(max_workers=1)
    try:
        return await GmailTaskExtractor(
            executor=executor,
            model_call=lambda _request: response,
            deadline_seconds=1,
            schema_version=schema_version,
        ).extract(account_id=receipt.account_id, message=transient)
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()


async def test_attempt_claim_failure_restart_and_success_are_numbered_idempotently(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import GmailExtractionAttempt
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-attempt-lifecycle",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)

    first = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version="gmail-task-v1",
    )
    replay = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version="gmail-task-v1",
    )
    assert first.attempt_number == 1
    assert replay.id == first.id
    assert replay.replayed is True

    failed = await service.fail_attempt(
        claim=first,
        category="invalid_model_output",
    )
    assert failed.state == "failed"
    assert failed.error_category == "invalid_model_output"
    assert "PRIVATE" not in (failed.error_message or "")

    second = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version="gmail-task-v1",
    )
    assert second.attempt_number == 2
    completed = await service.reconcile_attempt(
        claim=second,
        extraction=_extraction(receipt),
    )
    assert completed.replayed is False
    assert completed.suggestion_ids == ()

    completed_replay = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version="gmail-task-v1",
    )
    assert completed_replay.id == second.id
    assert completed_replay.state == "succeeded"
    assert completed_replay.replayed is True

    async with sessions() as session:
        rows = list(
            (
                await session.scalars(
                    sa.select(GmailExtractionAttempt)
                    .where(GmailExtractionAttempt.receipt_id == receipt.id)
                    .order_by(GmailExtractionAttempt.attempt_number)
                )
            ).all()
        )
    assert [(row.attempt_number, row.state) for row in rows] == [
        (1, "failed"),
        (2, "succeeded"),
    ]


@pytest.mark.parametrize(
    ("classification", "processing_state"),
    [
        ("ignored", "processing"),
        ("eligible", "processed"),
        ("eligible", "failed"),
    ],
)
async def test_new_attempt_requires_an_eligible_processing_receipt(
    suggestion_runtime,
    classification: str,
    processing_state: str,
) -> None:
    from models.gmail_task_intake import GmailExtractionAttempt, GmailMessageReceipt
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationError,
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=f"thread-ineligible-claim-{uuid4()}",
    )
    async with sessions() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
        stored.classification = classification
        stored.processing_state = processing_state
        await session.commit()

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    with pytest.raises(
        GmailObligationReconciliationError,
        match="gmail_extraction_receipt_ineligible",
    ):
        await service.claim_attempt(
            receipt_id=receipt.id,
            schema_version="gmail-task-v1",
        )

    async with sessions() as session:
        count = await session.scalar(sa.select(sa.func.count(GmailExtractionAttempt.id)))
    assert count == 0


@pytest.mark.parametrize(
    ("classification", "processing_state"),
    [
        ("ignored", "processing"),
        ("eligible", "processed"),
        ("eligible", "failed"),
    ],
)
async def test_running_attempt_rechecks_receipt_lifecycle_before_writes(
    suggestion_runtime,
    classification: str,
    processing_state: str,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
        GmailMessageReceipt,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationError,
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=f"thread-ineligible-reconcile-{uuid4()}",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    extraction = _extraction(receipt, _obligation())
    claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )
    async with sessions() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
        stored.classification = classification
        stored.processing_state = processing_state
        await session.commit()

    with pytest.raises(
        GmailObligationReconciliationError,
        match="gmail_extraction_receipt_ineligible",
    ):
        await service.reconcile_attempt(claim=claim, extraction=extraction)

    async with sessions() as session:
        counts = (
            await session.scalar(sa.select(sa.func.count(GmailExtractedObligation.id))),
            await session.scalar(sa.select(sa.func.count(CRMTaskSuggestion.id))),
            await session.scalar(sa.select(sa.func.count(CRMTaskSuggestionSource.id))),
        )
    assert counts == (0, 0, 0)


async def test_stale_receipt_lease_cannot_reconcile_after_reclaim(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
        GmailExtractionAttempt,
        GmailMessageReceipt,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationError,
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-reclaimed-reconcile-lease",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    extraction = _extraction(receipt, _obligation())
    stale_claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )
    replacement_started_at = datetime(2026, 8, 21, 14, 2, tzinfo=UTC)
    async with sessions() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
        stored.processing_started_at = replacement_started_at
        await session.commit()
    current_claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )

    assert stale_claim.id == current_claim.id
    assert stale_claim.receipt_processing_started_at != replacement_started_at
    assert current_claim.receipt_processing_started_at == replacement_started_at
    with pytest.raises(
        GmailObligationReconciliationError,
        match="gmail_extraction_receipt_lease_lost",
    ):
        await service.reconcile_attempt(
            claim=stale_claim,
            extraction=extraction,
        )

    async with sessions() as session:
        attempt = await session.get(GmailExtractionAttempt, stale_claim.id)
        counts = (
            await session.scalar(sa.select(sa.func.count(GmailExtractedObligation.id))),
            await session.scalar(sa.select(sa.func.count(CRMTaskSuggestion.id))),
            await session.scalar(sa.select(sa.func.count(CRMTaskSuggestionSource.id))),
        )
    assert attempt.state == "running"
    assert counts == (0, 0, 0)
    finished = await service.reconcile_attempt(
        claim=current_claim,
        extraction=extraction,
    )
    assert len(finished.suggestion_ids) == 1


async def test_stale_receipt_lease_cannot_fail_current_attempt_after_reclaim(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import GmailExtractionAttempt, GmailMessageReceipt
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationError,
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-reclaimed-fail-lease",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    extraction = _extraction(receipt, _obligation())
    stale_claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )
    replacement_started_at = datetime(2026, 8, 21, 14, 3, tzinfo=UTC)
    async with sessions() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
        stored.processing_started_at = replacement_started_at
        await session.commit()
    current_claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )

    with pytest.raises(
        GmailObligationReconciliationError,
        match="gmail_extraction_receipt_lease_lost",
    ):
        await service.fail_attempt(
            claim=stale_claim,
            category="provider_failed",
        )
    async with sessions() as session:
        attempt = await session.get(GmailExtractionAttempt, stale_claim.id)
    assert attempt.state == "running"
    finished = await service.reconcile_attempt(
        claim=current_claim,
        extraction=extraction,
    )
    assert len(finished.suggestion_ids) == 1


async def test_succeeded_attempt_replays_without_writes_after_receipt_finishes(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
        GmailMessageReceipt,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-succeeded-after-receipt",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    extraction = _extraction(receipt, _obligation())
    first_claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )
    first = await service.reconcile_attempt(
        claim=first_claim,
        extraction=extraction,
    )
    async with sessions() as session:
        stored = await session.get(GmailMessageReceipt, receipt.id)
        stored.processing_state = "processed"
        await session.commit()

    replay_claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )
    replay = await service.reconcile_attempt(
        claim=replay_claim,
        extraction=extraction,
    )

    assert replay.replayed is True
    assert replay.suggestion_ids == first.suggestion_ids
    async with sessions() as session:
        counts = (
            await session.scalar(sa.select(sa.func.count(GmailExtractedObligation.id))),
            await session.scalar(sa.select(sa.func.count(CRMTaskSuggestion.id))),
            await session.scalar(sa.select(sa.func.count(CRMTaskSuggestionSource.id))),
        )
    assert counts == (1, 1, 1)


@pytest.mark.parametrize(
    "category",
    [
        "provider_timeout",
        "provider_failed",
        "invalid_model_output",
        "body_truncated",
    ],
)
async def test_failed_extraction_attempts_persist_only_bounded_categories(
    suggestion_runtime,
    category: str,
) -> None:
    from models.gmail_task_intake import GmailExtractionAttempt
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=f"thread-failed-{category}",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version="gmail-task-v1",
    )
    await service.fail_attempt(claim=claim, category=category)

    async with sessions() as session:
        stored = await session.get(GmailExtractionAttempt, claim.id)
    assert stored is not None
    assert stored.state == "failed"
    assert stored.error_category == category
    assert len(stored.error_message or "") <= 500


async def test_persistent_invalid_output_reaches_a_bounded_attempt_limit(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import GmailExtractionAttempt
    from services.gmail_obligation_reconciliation import (
        GmailExtractionAttemptLimitReached,
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-attempt-limit",
    )
    service = GmailObligationReconciliationService(
        sessionmaker=sessions,
        max_attempts_per_schema=3,
    )
    for expected_number in range(1, 4):
        claim = await service.claim_attempt(
            receipt_id=receipt.id,
            schema_version="gmail-task-v1",
        )
        assert claim.attempt_number == expected_number
        await service.fail_attempt(
            claim=claim,
            category="invalid_model_output",
        )

    with pytest.raises(GmailExtractionAttemptLimitReached) as raised:
        await service.claim_attempt(
            receipt_id=receipt.id,
            schema_version="gmail-task-v1",
        )
    assert str(raised.value) == "gmail_extraction_attempt_limit"
    async with sessions() as session:
        count = await session.scalar(
            sa.select(sa.func.count(GmailExtractionAttempt.id)).where(
                GmailExtractionAttempt.receipt_id == receipt.id
            )
        )
    assert count == 3


async def test_received_request_and_sent_commitment_merge_with_two_sources(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    received = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-two-directions",
        direction="received",
        message_id="received-request",
    )
    sent = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-two-directions",
        direction="sent",
        message_id="sent-commitment",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)

    incoming = _obligation(kind="incoming_request")
    outgoing = _obligation(kind="outgoing_commitment")
    first = await _claim_and_reconcile(
        service,
        received,
        _extraction(received, incoming),
    )
    second = await _claim_and_reconcile(
        service,
        sent,
        _extraction(sent, outgoing),
    )

    assert first.suggestion_ids == second.suggestion_ids
    assert len(first.suggestion_ids) == 1
    async with sessions() as session:
        suggestions = list((await session.scalars(sa.select(CRMTaskSuggestion))).all())
        obligations = list(
            (await session.scalars(sa.select(GmailExtractedObligation))).all()
        )
        sources = list(
            (
                await session.scalars(
                    sa.select(CRMTaskSuggestionSource).order_by(
                        CRMTaskSuggestionSource.direction
                    )
                )
            ).all()
        )
    assert len(suggestions) == 1
    assert len(obligations) == 2
    assert len(sources) == 2
    assert {source.direction for source in sources} == {"received", "sent"}
    assert {source.receipt_id for source in sources} == {received.id, sent.id}
    assert suggestions[0].version == 1


async def test_backend_participant_identity_prevents_cross_sender_auto_merge(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipts = (
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id="thread-two-senders",
            message_id="sender-alice",
            sender_hmac="a" * 64,
        ),
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id="thread-two-senders",
            message_id="sender-bob",
            sender_hmac="d" * 64,
        ),
    )
    extractions = tuple(
        [
            await _extract_model_actions(
                receipt,
                _model_action(contact_hint=None),
            )
            for receipt in receipts
        ]
    )
    assert extractions[0].obligations[0].action_key != (
        extractions[1].obligations[0].action_key
    )

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    for receipt, extraction in zip(receipts, extractions, strict=True):
        await _claim_and_reconcile(service, receipt, extraction)

    async with sessions() as session:
        suggestions = list(
            (await session.scalars(sa.select(CRMTaskSuggestion))).all()
        )
        sources = list(
            (await session.scalars(sa.select(CRMTaskSuggestionSource))).all()
        )
    assert len(suggestions) == 2
    assert len(sources) == 2
    assert len({source.suggestion_id for source in sources}) == 2


async def test_backend_participant_identity_merges_received_and_sent_counterpart(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestionSource
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    received = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-participant-counterpart",
        message_id="counterpart-received",
        direction="received",
        sender_hmac="a" * 64,
        recipient_hmacs=("c" * 64,),
    )
    sent = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-participant-counterpart",
        message_id="counterpart-sent",
        direction="sent",
        sender_hmac="c" * 64,
        recipient_hmacs=("a" * 64,),
    )
    incoming = await _extract_model_actions(
        received,
        _model_action(contact_hint=None),
    )
    outgoing = await _extract_model_actions(
        sent,
        _model_action(kind="outgoing_commitment", contact_hint=None),
    )
    assert incoming.obligations[0].action_key == outgoing.obligations[0].action_key
    assert incoming.obligations[0].obligation_fingerprint == (
        outgoing.obligations[0].obligation_fingerprint
    )

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(service, received, incoming)
    second = await _claim_and_reconcile(service, sent, outgoing)
    assert first.suggestion_ids == second.suggestion_ids
    async with sessions() as session:
        source_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestionSource.id))
        )
    assert source_count == 2


async def test_multi_recipient_participant_identity_is_message_scoped_but_reviewable(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-multi-recipient",
        message_id="multi-recipient-sent",
        direction="sent",
        sender_hmac="c" * 64,
        recipient_hmacs=("a" * 64, "d" * 64),
    )
    extraction = await _extract_model_actions(
        receipt,
        _model_action(kind="outgoing_commitment", contact_hint=None),
    )
    assert extraction.obligations[0].participant_ambiguous is True
    result = await _claim_and_reconcile(
        GmailObligationReconciliationService(sessionmaker=sessions),
        receipt,
        extraction,
    )

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        obligation = await session.scalar(sa.select(GmailExtractedObligation))
    assert suggestion.state == "pending_review"
    assert suggestion.blocker_codes == []
    assert json.loads(obligation.evaluator_result_json)[
        "participant_ambiguous"
    ] is True


async def test_self_copy_participant_identity_is_message_scoped_but_reviewable(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipts = (
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id="thread-self-copy",
            message_id="self-copy-one",
            direction="self_copy",
            sender_hmac="c" * 64,
            recipient_hmacs=("c" * 64,),
        ),
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id="thread-self-copy",
            message_id="self-copy-two",
            direction="self_copy",
            sender_hmac="c" * 64,
            recipient_hmacs=("c" * 64,),
        ),
    )
    extractions = tuple(
        [
            await _extract_model_actions(
                receipt,
                _model_action(
                    kind="outgoing_commitment",
                    contact_hint=None,
                ),
            )
            for receipt in receipts
        ]
    )
    assert all(
        extraction.obligations[0].participant_ambiguous
        for extraction in extractions
    )
    assert extractions[0].obligations[0].action_key != (
        extractions[1].obligations[0].action_key
    )

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    for receipt, extraction in zip(receipts, extractions, strict=True):
        await _claim_and_reconcile(service, receipt, extraction)

    async with sessions() as session:
        suggestions = list(
            (
                await session.scalars(
                    sa.select(CRMTaskSuggestion).order_by(
                        CRMTaskSuggestion.created_at,
                        CRMTaskSuggestion.id,
                    )
                )
            ).all()
        )
    assert len(suggestions) == 2
    assert all(row.state == "pending_review" for row in suggestions)
    assert all(row.blocker_codes == [] for row in suggestions)


async def test_same_title_messages_remain_distinct_durable_evidence(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id="thread-same-title",
            message_id=f"same-title-{index}",
        )
        for index in range(2)
    ]
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    for receipt in receipts:
        await _claim_and_reconcile(
            service,
            receipt,
            _extraction(receipt, _obligation()),
        )

    async with sessions() as session:
        obligations = list(
            (await session.scalars(sa.select(GmailExtractedObligation))).all()
        )
        sources = list(
            (await session.scalars(sa.select(CRMTaskSuggestionSource))).all()
        )
        source_counts = {
            obligation_id: count
            for obligation_id, count in (
                await session.execute(
                    sa.select(
                        CRMTaskSuggestionSource.obligation_id,
                        sa.func.count(CRMTaskSuggestionSource.id),
                    ).group_by(CRMTaskSuggestionSource.obligation_id)
                )
            ).all()
        }
    assert len(obligations) == 2
    assert {row.receipt_id for row in obligations} == {item.id for item in receipts}
    assert len(sources) == 2
    assert {row.obligation_id for row in sources} == {row.id for row in obligations}
    assert source_counts == {row.id: 1 for row in obligations}


async def test_one_message_with_two_distinct_actions_creates_two_suggestions_and_sources(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-two-actions-one-message",
    )
    first_action = _obligation()
    second_action = _obligation(
        action_key="action-v1:" + "8" * 64,
        title=first_action.title,
        description="Email the listing packet to Alice.",
        due_at=None,
        timezone_basis=None,
        obligation_fingerprint="9" * 64,
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)

    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, first_action, second_action),
    )

    assert len(result.suggestion_ids) == 2
    async with sessions() as session:
        suggestions = list(
            (await session.scalars(sa.select(CRMTaskSuggestion))).all()
        )
        obligations = list(
            (await session.scalars(sa.select(GmailExtractedObligation))).all()
        )
        sources = list(
            (await session.scalars(sa.select(CRMTaskSuggestionSource))).all()
        )
        source_counts = {
            obligation_id: count
            for obligation_id, count in (
                await session.execute(
                    sa.select(
                        CRMTaskSuggestionSource.obligation_id,
                        sa.func.count(CRMTaskSuggestionSource.id),
                    ).group_by(CRMTaskSuggestionSource.obligation_id)
                )
            ).all()
        }
    assert len(suggestions) == len(obligations) == len(sources) == 2
    assert {row.source_action_key for row in suggestions} == {
        first_action.action_key,
        second_action.action_key,
    }
    possible_duplicates = [row for row in suggestions if row.state == "possible_duplicate"]
    assert len(possible_duplicates) == 1
    assert possible_duplicates[0].duplicate_of_suggestion_id is not None
    assert source_counts == {row.id: 1 for row in obligations}


async def test_same_semantic_collision_creates_two_and_continuation_selects_by_fingerprint(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_message_sanitizer import SanitizedGmailMessage
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )
    from services.gmail_task_extractor import GmailTaskExtractor
    from services.integration_health_service import BoundedProviderExecutor

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-semantic-collision",
        message_id="semantic-collision-one",
    )
    continuation_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-semantic-collision",
        message_id="semantic-collision-two",
    )

    def action(*, title: str, due_at: str) -> dict[str, object]:
        return {
            "kind": "incoming_request",
            "semantic_action": "send",
            "semantic_object": "seller_disclosure",
            "title": title,
            "description": "Send the requested disclosure package.",
            "priority": "normal",
            "due_at": due_at,
            "timezone_basis": "America/New_York",
            "due_at_ambiguous": False,
            "requested_owner": None,
            "owner_ambiguous": False,
            "requested_link_type": None,
            "requested_link_id": None,
            "contact_hint": "alice@example.test",
            "confidence": 0.9,
            "rationale": "The client requests a disclosure package.",
        }

    first_response = {
        "schema_version": "gmail-task-v1",
        "actions": [
            action(
                title="Send the first disclosure package",
                due_at="2026-08-24T19:00:00Z",
            ),
            action(
                title="Send the final disclosure package",
                due_at="2026-08-28T19:00:00Z",
            ),
        ],
    }
    continuation_response = {
        "schema_version": "gmail-task-v1",
        "actions": [
            action(
                title="Send the final disclosure package",
                due_at="2026-08-28T19:00:00Z",
            )
        ],
    }

    def transient(receipt) -> SanitizedGmailMessage:
        return SanitizedGmailMessage(
            message_id=receipt.gmail_message_id,
            thread_id=receipt.gmail_thread_id,
            direction=receipt.direction,
            message_at=receipt.message_at,
            sender_hmac=receipt.sender_hmac,
            recipient_hmacs=("b" * 64,),
            subject_preview=receipt.subject_preview,
            body_hash=receipt.body_hash,
            labels=("INBOX",),
            processing_state="processing",
            classification="eligible",
            transient_body_text="Please send both disclosure packages.",
            body_truncated=False,
        )

    executor = BoundedProviderExecutor(max_workers=1)
    try:
        first_extraction = await GmailTaskExtractor(
            executor=executor,
            model_call=lambda _request: first_response,
            deadline_seconds=1,
        ).extract(account_id=account.id, message=transient(first_receipt))
        continuation = await GmailTaskExtractor(
            executor=executor,
            model_call=lambda _request: continuation_response,
            deadline_seconds=1,
        ).extract(
            account_id=account.id,
            message=transient(continuation_receipt),
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(service, first_receipt, first_extraction)
    continued = await _claim_and_reconcile(
        service,
        continuation_receipt,
        continuation,
    )

    assert len(first.suggestion_ids) == 2
    async with sessions() as session:
        suggestions = list((await session.scalars(sa.select(CRMTaskSuggestion))).all())
        obligations = list(
            (await session.scalars(sa.select(GmailExtractedObligation))).all()
        )
        sources = list(
            (await session.scalars(sa.select(CRMTaskSuggestionSource))).all()
        )
    assert len(suggestions) == 2
    assert len(obligations) == len(sources) == 3
    selected = next(row for row in suggestions if row.id == continued.suggestion_ids[0])
    assert selected.due_at == datetime(2026, 8, 28, 19, 0, tzinfo=UTC)
    assert sum(source.suggestion_id == selected.id for source in sources) == 2
    assert len({row.source_action_key for row in suggestions}) == 1
    possible_duplicates = [row for row in suggestions if row.state == "possible_duplicate"]
    assert len(possible_duplicates) == 2
    roots = [row for row in possible_duplicates if row.duplicate_of_suggestion_id is None]
    successors = [
        row for row in possible_duplicates if row.duplicate_of_suggestion_id is not None
    ]
    assert len(roots) == len(successors) == 1
    assert successors[0].duplicate_of_suggestion_id == roots[0].id
    assert {
        source.obligation_id for source in sources
    } == {obligation.id for obligation in obligations}


async def test_same_fingerprint_collision_keeps_two_obligations_on_one_manual_suggestion(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-same-fingerprint-collision",
        message_id="same-fingerprint-collision",
    )
    base_key = "action-v1:" + "a" * 64
    fingerprint = "b" * 64
    first_title = "Call Alice about 123 Main"
    first_description = "Discuss showing feedback for 123 Main."
    first = _obligation(
        action_key=f"{base_key}:" + "1" * 32,
        reconciliation_action_key=base_key,
        obligation_fingerprint=fingerprint,
        title=first_title,
        description=first_description,
        identity_collision=True,
        identity_collision_requires_review=True,
        identity_instance_digest=_identity_instance_digest(
            first_title,
            first_description,
        ),
    )
    second_title = "Call Alice about 456 Oak"
    second_description = "Discuss showing feedback for 456 Oak."
    second = _obligation(
        action_key=f"{base_key}:" + "2" * 32,
        reconciliation_action_key=base_key,
        obligation_fingerprint=fingerprint,
        title=second_title,
        description=second_description,
        identity_collision=True,
        identity_collision_requires_review=True,
        identity_instance_digest=_identity_instance_digest(
            second_title,
            second_description,
        ),
    )
    result = await _claim_and_reconcile(
        GmailObligationReconciliationService(sessionmaker=sessions),
        receipt,
        _extraction(receipt, first, second),
    )

    assert len(set(result.suggestion_ids)) == 1
    async with sessions() as session:
        suggestion = await session.scalar(sa.select(CRMTaskSuggestion))
        obligations = list(
            (await session.scalars(sa.select(GmailExtractedObligation))).all()
        )
        sources = list(
            (await session.scalars(sa.select(CRMTaskSuggestionSource))).all()
        )
    assert len(obligations) == len(sources) == 2
    assert {source.suggestion_id for source in sources} == {suggestion.id}
    assert {source.obligation_id for source in sources} == {
        obligation.id for obligation in obligations
    }
    assert suggestion.source_action_key == base_key
    assert suggestion.state == "needs_clarification"
    assert suggestion.clarification_state == "manual_review_required"
    assert suggestion.blocker_codes == ["multiple_actions"]
    assert all(
        json.loads(row.evaluator_result_json)[
            "identity_collision_requires_review"
        ]
        is True
        for row in obligations
    )


async def test_cross_message_same_fingerprint_distinct_instances_never_overwrite(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id="thread-cross-message-instances",
            message_id=f"cross-instance-{index}",
        )
        for index in range(3)
    ]
    actions = (
        _model_action(
            title="Call Alice about 123 Main",
            description="Discuss showing feedback for 123 Main.",
        ),
        _model_action(
            title="Call Alice about 456 Oak",
            description="Discuss showing feedback for 456 Oak.",
        ),
        _model_action(
            title="Call Alice about 123 Main",
            description="Discuss showing feedback for 123 Main.",
        ),
    )
    extractions = tuple(
        [
            await _extract_model_actions(receipt, action)
            for receipt, action in zip(receipts, actions, strict=True)
        ]
    )
    obligations = tuple(extraction.obligations[0] for extraction in extractions)
    assert len({row.action_key for row in obligations}) == 1
    assert len({row.obligation_fingerprint for row in obligations}) == 1
    assert obligations[0].identity_instance_digest == (
        obligations[2].identity_instance_digest
    )
    assert obligations[0].identity_instance_digest != (
        obligations[1].identity_instance_digest
    )

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    results = []
    for receipt, extraction in zip(receipts, extractions, strict=True):
        results.append(await _claim_and_reconcile(service, receipt, extraction))

    assert len({result.suggestion_ids[0] for result in results}) == 1
    async with sessions() as session:
        suggestion = await session.scalar(sa.select(CRMTaskSuggestion))
        stored_obligations = list(
            (
                await session.scalars(
                    sa.select(GmailExtractedObligation).order_by(
                        GmailExtractedObligation.created_at,
                        GmailExtractedObligation.id,
                    )
                )
            ).all()
        )
        sources = list(
            (await session.scalars(sa.select(CRMTaskSuggestionSource))).all()
        )
    assert suggestion.title == "Call Alice about 123 Main"
    assert suggestion.description == "Discuss showing feedback for 123 Main."
    assert suggestion.primary_instance_digest == (
        obligations[0].identity_instance_digest
    )
    assert suggestion.state == "needs_clarification"
    assert suggestion.clarification_state == "manual_review_required"
    assert suggestion.blocker_codes == ["multiple_actions"]
    assert len(stored_obligations) == len(sources) == 3
    assert {
        row.identity_instance_digest for row in stored_obligations
    } == {
        obligations[0].identity_instance_digest,
        obligations[1].identity_instance_digest,
    }
    assert all(
        row.reconciled_suggestion_id == suggestion.id
        and row.reconciled_suppression_id is None
        for row in stored_obligations
    )


async def test_sequential_distinct_fingerprints_create_stable_possible_duplicates(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id="thread-three-property-variants",
            message_id=f"property-variant-{number}",
        )
        for number in range(1, 4)
    ]
    actions = [
        _model_action(
            title="Call Alice about 123 Main",
            description="Discuss showing feedback for 123 Main.",
            due_at="2026-08-22T19:00:00Z",
        ),
        _model_action(
            title="Call Alice about 456 Oak",
            description="Discuss showing feedback for 456 Oak.",
            due_at="2026-08-24T19:00:00Z",
        ),
        _model_action(
            title="Call Alice about 789 Pine",
            description="Discuss showing feedback for 789 Pine.",
            due_at="2026-08-26T19:00:00Z",
        ),
    ]
    extractions = [
        await _extract_model_actions(receipt, action)
        for receipt, action in zip(receipts, actions, strict=True)
    ]
    assert len({row.obligations[0].action_key for row in extractions}) == 1
    assert len(
        {row.obligations[0].obligation_fingerprint for row in extractions}
    ) == 3

    results = [
        await _claim_and_reconcile(service, receipt, extraction)
        for receipt, extraction in zip(receipts, extractions, strict=True)
    ]

    async with sessions() as session:
        suggestions = list(
            (
                await session.scalars(
                    sa.select(CRMTaskSuggestion).order_by(
                        CRMTaskSuggestion.created_at,
                        CRMTaskSuggestion.id,
                    )
                )
            ).all()
        )
        sources = list(
            (await session.scalars(sa.select(CRMTaskSuggestionSource))).all()
        )
    assert len({result.suggestion_ids[0] for result in results}) == 3
    assert len(suggestions) == len(sources) == 3
    root = suggestions[0]
    assert [row.state for row in suggestions] == ["possible_duplicate"] * 3
    assert [row.version for row in suggestions] == [3, 2, 1]
    assert root.duplicate_of_suggestion_id is None
    assert all(
        row.duplicate_of_suggestion_id == root.id for row in suggestions[1:]
    )
    assert {row.title for row in suggestions} == {
        "Call Alice about 123 Main",
        "Call Alice about 456 Oak",
        "Call Alice about 789 Pine",
    }


async def test_taxonomy_fallback_is_durable_and_requires_clarification(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-taxonomy-fallback",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)

    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(
            receipt,
            _obligation(
                title="Arrange the uncommon municipal filing",
                description="Complete the uncommon filing before the hearing.",
                taxonomy_fallback=True,
            ),
        ),
    )

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        obligation = await session.scalar(
            sa.select(GmailExtractedObligation).where(
                GmailExtractedObligation.receipt_id == receipt.id
            )
        )
    assert suggestion.state == "needs_clarification"
    assert suggestion.clarification_state == "pending"
    assert suggestion.blocker_codes == ["missing_required_field"]
    assert suggestion.owner_clarification_pending is False
    assert suggestion.task_details_clarification_pending is True
    assert obligation.taxonomy_fallback is True
    assert obligation.owner_ambiguous is False
    assert json.loads(obligation.evaluator_result_json) == {
        "contact_hint_supplied": False,
        "due_at_ambiguous": False,
        "due_at_state": "resolved",
        "link_state": "not_provided",
        "owner_ambiguous": False,
        "owner_state": "implicit_brandon",
        "participant_ambiguous": False,
        "participant_state": "backend_unique",
        "taxonomy_fallback": True,
    }


async def test_distinct_cross_message_fallbacks_never_merge_or_overwrite(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-distinct-fallbacks",
        message_id="fallback-survey",
    )
    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-distinct-fallbacks",
        message_id="fallback-hoa",
    )
    common = {
        "taxonomy_fallback": True,
        "action_key": "action-v1:" + "f" * 64,
        "obligation_fingerprint": "e" * 64,
    }
    first = await _claim_and_reconcile(
        service,
        first_receipt,
        _extraction(
            first_receipt,
            _obligation(
                **common,
                title="Order the boundary survey",
                description="Arrange a new boundary survey.",
            ),
        ),
    )
    second = await _claim_and_reconcile(
        service,
        second_receipt,
        _extraction(
            second_receipt,
            _obligation(
                **common,
                title="Notify the homeowners association",
                description="Notify the HOA before exterior work begins.",
            ),
        ),
    )

    async with sessions() as session:
        suggestions = list(
            (
                await session.scalars(
                    sa.select(CRMTaskSuggestion).order_by(
                        CRMTaskSuggestion.created_at,
                        CRMTaskSuggestion.id,
                    )
                )
            ).all()
        )
        obligations = list(
            (await session.scalars(sa.select(GmailExtractedObligation))).all()
        )
        sources = list(
            (await session.scalars(sa.select(CRMTaskSuggestionSource))).all()
        )
    assert len(suggestions) == len(obligations) == len(sources) == 2
    assert first.suggestion_ids != second.suggestion_ids
    original = next(row for row in suggestions if row.id == first.suggestion_ids[0])
    later = next(row for row in suggestions if row.id == second.suggestion_ids[0])
    assert original.title == "Order the boundary survey"
    assert later.title == "Notify the homeowners association"
    assert later.state == "possible_duplicate"
    assert later.duplicate_of_suggestion_id == original.id
    assert later.blocker_codes == [
        "missing_required_field",
        "multiple_actions",
    ]
    assert {source.obligation_id for source in sources} == {
        obligation.id for obligation in obligations
    }


async def test_suppressed_fallback_never_suppresses_a_different_fallback_message(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )
    from services.gmail_task_extractor import GmailTaskExtractor
    from services.integration_health_service import BoundedProviderExecutor

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-fallback-suppression",
        message_id="fallback-dismissed-one",
    )
    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-fallback-suppression",
        message_id="fallback-reviewable-two",
    )

    def response(title: str) -> dict[str, object]:
        return {
            "schema_version": "gmail-task-v1",
            "actions": [
                {
                    "kind": "incoming_request",
                    "semantic_action": "other_action",
                    "semantic_object": "other_object",
                    "title": title,
                    "description": "An uncommon obligation needs review.",
                    "priority": "normal",
                    "due_at": "2026-08-22T19:00:00Z",
                    "timezone_basis": "America/New_York",
                    "due_at_ambiguous": False,
                    "requested_owner": None,
                    "owner_ambiguous": False,
                    "requested_link_type": None,
                    "requested_link_id": None,
                    "contact_hint": None,
                    "confidence": 0.8,
                    "rationale": "The message contains an explicit obligation.",
                }
            ],
        }

    from services.gmail_message_sanitizer import SanitizedGmailMessage

    def transient(receipt, body: str) -> SanitizedGmailMessage:
        return SanitizedGmailMessage(
            message_id=receipt.gmail_message_id,
            thread_id=receipt.gmail_thread_id,
            direction=receipt.direction,
            message_at=receipt.message_at,
            sender_hmac=receipt.sender_hmac,
            recipient_hmacs=("b" * 64,),
            subject_preview=receipt.subject_preview,
            body_hash=receipt.body_hash,
            labels=("INBOX",),
            processing_state="processing",
            classification="eligible",
            transient_body_text=body,
            body_truncated=False,
        )

    executor = BoundedProviderExecutor(max_workers=1)
    try:
        first_extractor = GmailTaskExtractor(
            executor=executor,
            model_call=lambda _request: response("Order the boundary survey"),
            deadline_seconds=1,
        )
        first = await first_extractor.extract(
            account_id=account.id,
            message=transient(first_receipt, "Order the boundary survey."),
        )
        second_extractor = GmailTaskExtractor(
            executor=executor,
            model_call=lambda _request: response(
                "Notify the homeowners association"
            ),
            deadline_seconds=1,
        )
        second = await second_extractor.extract(
            account_id=account.id,
            message=transient(second_receipt, "Notify the HOA."),
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert first.obligations[0].action_key != second.obligations[0].action_key
    await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, first_receipt.gmail_thread_id),
        action_key=first.obligations[0].action_key,
        fingerprint=first.obligations[0].obligation_fingerprint,
        instance_digest=first.obligations[0].identity_instance_digest,
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    suppressed = await _claim_and_reconcile(service, first_receipt, first)
    assert suppressed.suggestion_ids == ()
    assert suppressed.suppressed_action_keys == (
        first.obligations[0].action_key,
    )
    result = await _claim_and_reconcile(service, second_receipt, second)

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
    assert result.suppressed_action_keys == ()
    assert suggestion.state in {"needs_clarification", "possible_duplicate"}
    assert suggestion.blocker_codes == ["missing_required_field"]


async def test_extractor_preview_is_pg_safe_before_reconciliation_persists_it(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        GmailExtractedObligation,
    )
    from services.crm_task_suggestion_service import CRMTaskSuggestionService
    from services.gmail_message_sanitizer import SanitizedGmailMessage
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )
    from services.gmail_task_extractor import GmailTaskExtractor
    from services.integration_health_service import BoundedProviderExecutor

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-control-preview",
        message_id="message-control-preview",
        subject="Showing\r\n\u202eAPPROVED\u2066fake\u2069",
    )
    response = {
        "schema_version": "gmail-task-v1",
        "actions": [
            {
                "kind": "incoming_request",
                "semantic_action": "call",
                "semantic_object": "showing_feedback",
                "title": "Call José about the showing 例",
                "description": (
                    "Discuss the showing feedback.\r\nEnvoyer le résumé."
                ),
                "priority": "normal",
                "due_at": None,
                "timezone_basis": None,
                "due_at_ambiguous": False,
                "requested_owner": None,
                "owner_ambiguous": False,
                "requested_link_type": None,
                "requested_link_id": None,
                "contact_hint": None,
                "confidence": 0.9,
                "rationale": "Une demande directe est présente.",
            }
        ],
    }
    transient = SanitizedGmailMessage(
        message_id=receipt.gmail_message_id,
        thread_id=receipt.gmail_thread_id,
        direction=receipt.direction,
        message_at=receipt.message_at,
        sender_hmac=receipt.sender_hmac,
        recipient_hmacs=("b" * 64,),
        subject_preview=receipt.subject_preview,
        body_hash=receipt.body_hash,
        labels=("INBOX",),
        processing_state="processing",
        classification="eligible",
        transient_body_text=(
            "\x00Please\tcall about the showing.\u202eAPPROVED\u2066fake\u2069"
            "\r\nThank you.\x7f"
        ),
        body_truncated=False,
    )
    executor = BoundedProviderExecutor(max_workers=1)
    try:
        extraction = await GmailTaskExtractor(
            executor=executor,
            model_call=lambda _request: response,
            deadline_seconds=1,
        ).extract(account_id=account.id, message=transient)
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    await _claim_and_reconcile(service, receipt, extraction)

    async with sessions() as session:
        stored = await session.scalar(sa.select(GmailExtractedObligation))
        suggestion = await session.scalar(sa.select(CRMTaskSuggestion))
    assert stored.evidence_preview == (
        "Please call about the showing. APPROVED fake Thank you."
    )
    assert all(
        unicodedata.category(character)
        not in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for character in stored.evidence_preview
    )
    preview = CRMTaskSuggestionService.preview_payload(suggestion)
    assert stored.title == preview.title == "Call José about the showing 例"
    assert stored.description == preview.description == (
        "Discuss the showing feedback.\nEnvoyer le résumé."
    )


async def _seed_suppression(
    sessions,
    *,
    scope: str,
    action_key: str,
    fingerprint: str,
    instance_digest: str = "3" * 64,
):
    from models.admin_user import AdminUser
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import CRMTaskSuggestionSuppression

    async with sessions() as session:
        admin = AdminUser(
            email=f"admin-{uuid4()}@example.test",
            hashed_password="test-only",
        )
        dismissal_audit = AgentActionAudit(
            actor="admin",
            action_id=f"dismiss-{uuid4()}",
            method="POST",
            path="/test/task-suggestions/dismiss",
            status_code=200,
            allowed=True,
            request_meta_json="{}",
            response_meta_json="{}",
        )
        session.add_all([admin, dismissal_audit])
        await session.flush()
        suppression = CRMTaskSuggestionSuppression(
            source_type="gmail_message",
            source_scope_key=scope,
            source_action_key=action_key,
            obligation_fingerprint=fingerprint,
            identity_instance_digest=instance_digest,
            dismissal_reason="Already handled outside the system.",
            dismissed_by_admin_id=admin.id,
            dismissal_audit_id=dismissal_audit.id,
        )
        session.add(suppression)
        await session.commit()
        await session.refresh(suppression)
        return suppression, admin, dismissal_audit


async def test_evaluator_json_preserves_ambiguity_through_suppression_and_replay(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import GmailExtractedObligation
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-suppressed-ambiguity-evidence",
        message_id="suppressed-ambiguity-evidence",
    )
    obligation = _obligation(
        due_at=None,
        timezone_basis=None,
        due_at_ambiguous=True,
        requested_owner=None,
        owner_ambiguous=True,
    )
    suppression, _admin, _audit = await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, receipt.gmail_thread_id),
        action_key=obligation.action_key,
        fingerprint=obligation.obligation_fingerprint,
        instance_digest=obligation.identity_instance_digest,
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, obligation),
    )
    replay = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, obligation),
    )

    assert first.suggestion_ids == ()
    assert replay.replayed is True
    assert replay.suppressed_action_keys == (obligation.action_key,)
    async with sessions() as session:
        stored = await session.scalar(sa.select(GmailExtractedObligation))
    assert json.loads(stored.evaluator_result_json) == {
        "contact_hint_supplied": False,
        "due_at_ambiguous": True,
        "due_at_state": "ambiguous",
        "link_state": "not_provided",
        "owner_ambiguous": True,
        "owner_state": "ambiguous",
        "participant_ambiguous": False,
        "participant_state": "backend_unique",
    }
    assert stored.reconciled_suggestion_id is None
    assert stored.reconciled_suppression_id == suppression.id


@pytest.mark.parametrize(
    ("ambiguous_fields", "first_title", "second_title", "expected_blocker"),
    [
        (
            {
                "due_at": None,
                "timezone_basis": None,
                "due_at_ambiguous": True,
            },
            "Call Alice this Friday",
            "Call Alice next Tuesday",
            "ambiguous_due_at",
        ),
        (
            {
                "requested_owner": None,
                "owner_ambiguous": True,
            },
            "Ask Pat or Brandon to call Alice",
            "Ask Morgan or Brandon to call Alice",
            "missing_required_field",
        ),
    ],
)
async def test_ambiguous_message_suppression_is_exact_to_one_provider_message(
    suggestion_runtime,
    ambiguous_fields: dict[str, object],
    first_title: str,
    second_title: str,
    expected_blocker: str,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-ambiguous-suppression",
        message_id="ambiguous-suppressed-one",
    )
    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-ambiguous-suppression",
        message_id="ambiguous-review-two",
    )
    first = await _extract_model_actions(
        first_receipt,
        _model_action(title=first_title, **ambiguous_fields),
    )
    retry = await _extract_model_actions(
        first_receipt,
        _model_action(title=first_title, **ambiguous_fields),
    )
    second = await _extract_model_actions(
        second_receipt,
        _model_action(title=second_title, **ambiguous_fields),
    )
    first_obligation = first.obligations[0]
    assert first_obligation.action_key == second.obligations[0].action_key
    assert first_obligation.obligation_fingerprint == (
        retry.obligations[0].obligation_fingerprint
    )
    assert first_obligation.obligation_fingerprint != (
        second.obligations[0].obligation_fingerprint
    )
    await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, first_receipt.gmail_thread_id),
        action_key=first_obligation.action_key,
        fingerprint=first_obligation.obligation_fingerprint,
        instance_digest=first_obligation.identity_instance_digest,
    )

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    suppressed = await _claim_and_reconcile(service, first_receipt, first)
    replay = await _claim_and_reconcile(service, first_receipt, retry)
    reviewable = await _claim_and_reconcile(service, second_receipt, second)

    assert suppressed.suggestion_ids == ()
    assert replay.replayed is True
    assert replay.suppressed_action_keys == (first_obligation.action_key,)
    assert len(reviewable.suggestion_ids) == 1
    async with sessions() as session:
        suggestion = await session.get(
            CRMTaskSuggestion,
            reviewable.suggestion_ids[0],
        )
    assert suggestion.state == "needs_clarification"
    assert expected_blocker in suggestion.blocker_codes


async def test_suppression_is_exact_to_semantic_instance_digest(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-instance-suppression",
        message_id="instance-suppressed-123-main",
    )
    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-instance-suppression",
        message_id="instance-review-456-oak",
    )
    first = await _extract_model_actions(
        first_receipt,
        _model_action(
            title="Call Alice about 123 Main",
            description="Discuss showing feedback for 123 Main.",
        ),
    )
    second = await _extract_model_actions(
        second_receipt,
        _model_action(
            title="Call Alice about 456 Oak",
            description="Discuss showing feedback for 456 Oak.",
        ),
    )
    first_obligation = first.obligations[0]
    second_obligation = second.obligations[0]
    assert first_obligation.action_key == second_obligation.action_key
    assert first_obligation.obligation_fingerprint == (
        second_obligation.obligation_fingerprint
    )
    assert first_obligation.identity_instance_digest != (
        second_obligation.identity_instance_digest
    )
    await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, first_receipt.gmail_thread_id),
        action_key=first_obligation.action_key,
        fingerprint=first_obligation.obligation_fingerprint,
        instance_digest=first_obligation.identity_instance_digest,
    )

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    suppressed = await _claim_and_reconcile(service, first_receipt, first)
    reviewable = await _claim_and_reconcile(service, second_receipt, second)

    assert suppressed.suggestion_ids == ()
    assert len(reviewable.suggestion_ids) == 1
    async with sessions() as session:
        suggestion = await session.get(
            CRMTaskSuggestion,
            reviewable.suggestion_ids[0],
        )
    assert suggestion.title == "Call Alice about 456 Oak"
    assert suggestion.state == "pending_review"


async def test_suppression_survives_schema_upgrade_until_distinct_audited_override(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt_v1 = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-suppressed",
        message_id="suppressed-v1",
    )
    obligation = _obligation()
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    original = await _claim_and_reconcile(
        service,
        receipt_v1,
        _extraction(receipt_v1, obligation),
    )
    receipt_v2 = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-suppressed",
        message_id="suppressed-v2",
    )
    scope = gmail_source_scope_key(account.id, receipt_v2.gmail_thread_id)
    suppression, admin, dismissal_audit = await _seed_suppression(
        sessions,
        scope=scope,
        action_key=obligation.action_key,
        fingerprint=obligation.obligation_fingerprint,
        instance_digest=obligation.identity_instance_digest,
    )
    async with sessions() as session:
        dismissed = await session.get(CRMTaskSuggestion, original.suggestion_ids[0])
        dismissed.state = "dismissed"
        await session.commit()

    suppressed = await _claim_and_reconcile(
        service,
        receipt_v2,
        _extraction(receipt_v2, obligation, schema_version="gmail-task-v2"),
    )
    assert suppressed.suggestion_ids == ()
    assert suppressed.suppressed_action_keys == (obligation.action_key,)

    receipt_v3 = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-suppressed",
        message_id="suppressed-v3",
    )

    async with sessions() as session:
        from models.agent_action_audit import AgentActionAudit

        assert await session.scalar(sa.select(sa.func.count(CRMTaskSuggestion.id))) == 1
        assert await session.scalar(sa.select(sa.func.count(CRMTaskSuggestionSource.id))) == 1
        assert await session.scalar(sa.select(sa.func.count(GmailExtractedObligation.id))) == 2
        reprocess_audit = AgentActionAudit(
            actor="admin",
            action_id="gmail_task_intake.reprocess",
            method="POST",
            path=(
                "/api/v1/admin/integrations/gmail-task-intake/reprocess/"
                f"{receipt_v3.id}"
            ),
            status_code=200,
            allowed=True,
            request_meta_json=json.dumps(
                {
                    "admin_user_id": admin.id,
                    "suppression_id": str(suppression.id),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            response_meta_json="{}",
        )
        session.add(reprocess_audit)
        await session.flush()
        stored = await session.get(type(suppression), suppression.id)
        stored.reprocess_override_at = datetime.now(UTC)
        stored.reprocess_override_by_admin_id = admin.id
        stored.reprocess_override_audit_id = reprocess_audit.id
        await session.commit()
        assert stored.reprocess_override_audit_id != dismissal_audit.id

    allowed = await _claim_and_reconcile(
        service,
        receipt_v3,
        _extraction(receipt_v3, obligation, schema_version="gmail-task-v3"),
    )
    assert len(allowed.suggestion_ids) == 1
    async with sessions() as session:
        stored = await session.get(type(suppression), suppression.id)
        original_row = await session.get(
            CRMTaskSuggestion,
            original.suggestion_ids[0],
        )
        successor = await session.get(CRMTaskSuggestion, allowed.suggestion_ids[0])
        assert stored.reprocess_override_consumed_at is not None
        assert successor.id != original_row.id
        assert original_row.state == "dismissed"
        assert successor.state == "pending_review"
        assert successor.duplicate_of_suggestion_id == original_row.id

    receipt_v4 = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-suppressed",
        message_id="suppressed-v4",
    )
    second_use = await _claim_and_reconcile(
        service,
        receipt_v4,
        _extraction(receipt_v4, obligation, schema_version="gmail-task-v4"),
    )
    assert second_use.suggestion_ids == ()
    assert second_use.suppressed_action_keys == (obligation.action_key,)


async def test_reprocess_override_preserves_live_same_base_duplicate_ambiguity(
    suggestion_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    thread_id = "thread-override-live-fingerprint-sibling"
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id=thread_id,
            message_id=f"override-live-sibling-{index}",
        )
        for index in range(3)
    ]
    action_a = _model_action(due_at="2026-08-22T19:00:00Z")
    action_b = _model_action(due_at="2026-08-24T19:00:00Z")
    extraction_a = await _extract_model_actions(receipts[0], action_a)
    extraction_b = await _extract_model_actions(receipts[1], action_b)
    reprocess_a = await _extract_model_actions(receipts[2], action_a)
    obligation_a = extraction_a.obligations[0]
    obligation_b = extraction_b.obligations[0]
    assert obligation_a.action_key == obligation_b.action_key
    assert obligation_a.obligation_fingerprint != (
        obligation_b.obligation_fingerprint
    )

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    original_result = await _claim_and_reconcile(
        service,
        receipts[0],
        extraction_a,
    )
    suppression, admin, _dismissal_audit = await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, thread_id),
        action_key=obligation_a.action_key,
        fingerprint=obligation_a.obligation_fingerprint,
        instance_digest=obligation_a.identity_instance_digest,
    )
    async with sessions() as session:
        original = await session.get(
            CRMTaskSuggestion,
            original_result.suggestion_ids[0],
        )
        original.state = "dismissed"
        await session.commit()

    sibling_result = await _claim_and_reconcile(
        service,
        receipts[1],
        extraction_b,
    )
    async with sessions() as session:
        original = await session.get(
            CRMTaskSuggestion,
            original_result.suggestion_ids[0],
        )
        sibling = await session.get(
            CRMTaskSuggestion,
            sibling_result.suggestion_ids[0],
        )
        original_snapshot = (
            original.state,
            original.version,
            original.payload_hash,
            original.obligation_fingerprint,
            original.duplicate_of_suggestion_id,
        )
        sibling_version = sibling.version
        assert sibling.state == "possible_duplicate"

        audit = AgentActionAudit(
            actor="admin",
            action_id="gmail_task_intake.reprocess",
            method="POST",
            path=(
                "/api/v1/admin/integrations/gmail-task-intake/reprocess/"
                f"{receipts[2].id}"
            ),
            status_code=200,
            allowed=True,
            request_meta_json=json.dumps(
                {
                    "admin_user_id": admin.id,
                    "suppression_id": str(suppression.id),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            response_meta_json="{}",
        )
        session.add(audit)
        await session.flush()
        stored_suppression = await session.get(type(suppression), suppression.id)
        stored_suppression.reprocess_override_at = datetime.now(UTC)
        stored_suppression.reprocess_override_by_admin_id = admin.id
        stored_suppression.reprocess_override_audit_id = audit.id
        await session.commit()

    override_result = await _claim_and_reconcile(
        service,
        receipts[2],
        reprocess_a,
    )

    async with sessions() as session:
        original = await session.get(
            CRMTaskSuggestion,
            original_result.suggestion_ids[0],
        )
        sibling = await session.get(
            CRMTaskSuggestion,
            sibling_result.suggestion_ids[0],
        )
        successor = await session.get(
            CRMTaskSuggestion,
            override_result.suggestion_ids[0],
        )
        suggestions = list(
            (await session.scalars(sa.select(CRMTaskSuggestion))).all()
        )
        consumed = await session.get(type(suppression), suppression.id)

    assert len(suggestions) == 3
    assert (
        original.state,
        original.version,
        original.payload_hash,
        original.obligation_fingerprint,
        original.duplicate_of_suggestion_id,
    ) == original_snapshot
    assert original.state == "dismissed"
    assert sibling.state == "possible_duplicate"
    assert sibling.version == sibling_version + 1
    assert successor.id not in {
        original.id,
        sibling.id,
    }
    assert successor.state == "possible_duplicate"
    assert successor.duplicate_of_suggestion_id == original.id
    assert consumed.reprocess_override_consumed_at is not None


async def test_terminal_material_successor_reblocks_resolved_live_sibling(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    thread_id = "thread-terminal-successor-live-sibling"
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id=thread_id,
            message_id=f"terminal-successor-sibling-{index}",
        )
        for index in range(3)
    ]
    action_a = _model_action(due_at="2026-08-22T19:00:00Z")
    action_b = _model_action(due_at="2026-08-24T19:00:00Z")
    changed_b = _model_action(
        due_at="2026-08-24T19:00:00Z",
        priority="high",
    )
    extractions = [
        await _extract_model_actions(receipts[0], action_a),
        await _extract_model_actions(receipts[1], action_b),
        await _extract_model_actions(receipts[2], changed_b),
    ]
    assert extractions[0].obligations[0].action_key == (
        extractions[1].obligations[0].action_key
    )
    assert extractions[0].obligations[0].obligation_fingerprint != (
        extractions[1].obligations[0].obligation_fingerprint
    )
    assert extractions[1].obligations[0].obligation_fingerprint == (
        extractions[2].obligations[0].obligation_fingerprint
    )

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(service, receipts[0], extractions[0])
    second = await _claim_and_reconcile(service, receipts[1], extractions[1])
    async with sessions() as session:
        root = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        terminal = await session.get(CRMTaskSuggestion, second.suggestion_ids[0])
        assert root.state == terminal.state == "possible_duplicate"
        root.state = "pending_review"
        root.clarification_state = "not_required"
        root.version += 1
        terminal.state = "approved"
        await session.commit()
        root_snapshot = (
            root.version,
            root.payload_hash,
            root.title,
            root.obligation_fingerprint,
        )
        terminal_snapshot = (
            terminal.state,
            terminal.version,
            terminal.payload_hash,
            terminal.title,
            terminal.priority,
            terminal.obligation_fingerprint,
            terminal.duplicate_of_suggestion_id,
        )

    successor_result = await _claim_and_reconcile(
        service,
        receipts[2],
        extractions[2],
    )

    async with sessions() as session:
        root = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        terminal = await session.get(CRMTaskSuggestion, second.suggestion_ids[0])
        successor = await session.get(
            CRMTaskSuggestion,
            successor_result.suggestion_ids[0],
        )
        suggestion_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestion.id))
        )

    assert suggestion_count == 3
    assert root.state == "possible_duplicate"
    assert root.version == root_snapshot[0] + 1
    assert (
        root.payload_hash,
        root.title,
        root.obligation_fingerprint,
    ) == root_snapshot[1:]
    assert (
        terminal.state,
        terminal.version,
        terminal.payload_hash,
        terminal.title,
        terminal.priority,
        terminal.obligation_fingerprint,
        terminal.duplicate_of_suggestion_id,
    ) == terminal_snapshot
    assert successor.state == "possible_duplicate"
    assert successor.priority == "high"
    assert successor.duplicate_of_suggestion_id == root.id


async def test_exact_continuation_reblocks_live_duplicate_set_without_version_churn(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    thread_id = "thread-exact-continuation-reblocks-siblings"
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id=thread_id,
            message_id=f"exact-reblock-{index}",
        )
        for index in range(4)
    ]
    action_a = _model_action(due_at="2026-08-22T19:00:00Z")
    action_b = _model_action(due_at="2026-08-24T19:00:00Z")
    extractions = [
        await _extract_model_actions(receipts[0], action_a),
        await _extract_model_actions(receipts[1], action_b),
        await _extract_model_actions(receipts[2], action_a),
        await _extract_model_actions(receipts[3], action_a),
    ]

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(service, receipts[0], extractions[0])
    second = await _claim_and_reconcile(service, receipts[1], extractions[1])
    async with sessions() as session:
        root = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        sibling = await session.get(CRMTaskSuggestion, second.suggestion_ids[0])
        assert root.state == sibling.state == "possible_duplicate"
        root.state = "pending_review"
        root.clarification_state = "not_required"
        root.version += 1
        await session.commit()
        root_version = root.version
        sibling_snapshot = (
            sibling.state,
            sibling.clarification_state,
            sibling.version,
            sibling.payload_hash,
        )

    continued = await _claim_and_reconcile(
        service,
        receipts[2],
        extractions[2],
    )
    assert continued.suggestion_ids == first.suggestion_ids
    async with sessions() as session:
        root = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        sibling = await session.get(CRMTaskSuggestion, second.suggestion_ids[0])
        assert root.state == "possible_duplicate"
        assert root.version == root_version + 1
        assert (
            sibling.state,
            sibling.clarification_state,
            sibling.version,
            sibling.payload_hash,
        ) == sibling_snapshot
        normalized_versions = (root.version, sibling.version)

    repeated = await _claim_and_reconcile(
        service,
        receipts[3],
        extractions[3],
    )
    assert repeated.suggestion_ids == first.suggestion_ids
    async with sessions() as session:
        root = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        sibling = await session.get(CRMTaskSuggestion, second.suggestion_ids[0])
        source_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestionSource.id)).where(
                CRMTaskSuggestionSource.suggestion_id == root.id
            )
        )
    assert (root.version, sibling.version) == normalized_versions
    assert source_count == 3


async def test_one_override_authorizes_every_matching_collision_in_exact_receipt(
    suggestion_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
    )
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-collision-override",
        message_id="collision-override",
    )
    base_key = "action-v1:" + "a" * 64
    fingerprint = "b" * 64
    first_title = "Call Alice about 123 Main"
    first_description = "Discuss showing feedback for 123 Main."
    first_instance_digest = _identity_instance_digest(
        first_title,
        first_description,
    )
    suppression, admin, _dismissal_audit = await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, receipt.gmail_thread_id),
        action_key=base_key,
        fingerprint=fingerprint,
        instance_digest=first_instance_digest,
    )
    async with sessions() as session:
        audit = AgentActionAudit(
            actor="admin",
            action_id="gmail_task_intake.reprocess",
            method="POST",
            path=(
                "/api/v1/admin/integrations/gmail-task-intake/reprocess/"
                f"{receipt.id}"
            ),
            status_code=200,
            allowed=True,
            request_meta_json=json.dumps(
                {
                    "admin_user_id": admin.id,
                    "suppression_id": str(suppression.id),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            response_meta_json="{}",
        )
        session.add(audit)
        await session.flush()
        stored = await session.get(type(suppression), suppression.id)
        stored.reprocess_override_at = datetime.now(UTC)
        stored.reprocess_override_by_admin_id = admin.id
        stored.reprocess_override_audit_id = audit.id
        await session.commit()

    first = _obligation(
        action_key=f"{base_key}:" + "1" * 32,
        reconciliation_action_key=base_key,
        obligation_fingerprint=fingerprint,
        title=first_title,
        description=first_description,
        identity_collision=True,
        identity_collision_requires_review=True,
        identity_instance_digest=first_instance_digest,
    )
    second_title = "Call Alice about 456 Oak"
    second_description = "Discuss showing feedback for 456 Oak."
    second = _obligation(
        action_key=f"{base_key}:" + "2" * 32,
        reconciliation_action_key=base_key,
        obligation_fingerprint=fingerprint,
        title=second_title,
        description=second_description,
        identity_collision=True,
        identity_collision_requires_review=True,
        identity_instance_digest=_identity_instance_digest(
            second_title,
            second_description,
        ),
    )
    result = await _claim_and_reconcile(
        GmailObligationReconciliationService(sessionmaker=sessions),
        receipt,
        _extraction(receipt, first, second),
    )

    assert result.suppressed_action_keys == ()
    assert len(set(result.suggestion_ids)) == 1
    async with sessions() as session:
        stored = await session.get(type(suppression), suppression.id)
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        sources = list(
            (await session.scalars(sa.select(CRMTaskSuggestionSource))).all()
        )
    assert stored.reprocess_override_consumed_at is not None
    assert suggestion.blocker_codes == ["multiple_actions"]
    assert len(sources) == 2


async def test_same_fingerprint_in_unrelated_thread_is_not_suppressed(
    suggestion_runtime,
) -> None:
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    obligation = _obligation()
    await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, "thread-one"),
        action_key=obligation.action_key,
        fingerprint=obligation.obligation_fingerprint,
        instance_digest=obligation.identity_instance_digest,
    )
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-two",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)

    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, obligation),
    )
    assert len(result.suggestion_ids) == 1
    assert result.suppressed_action_keys == ()


async def test_suppression_cannot_be_overridden_by_reusing_its_dismissal_audit(
    suggestion_runtime,
) -> None:
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    obligation = _obligation()
    scope = gmail_source_scope_key(account.id, "thread-same-audit-override")
    suppression, admin, dismissal_audit = await _seed_suppression(
        sessions,
        scope=scope,
        action_key=obligation.action_key,
        fingerprint=obligation.obligation_fingerprint,
        instance_digest=obligation.identity_instance_digest,
    )
    async with sessions() as session:
        stored = await session.get(type(suppression), suppression.id)
        stored.reprocess_override_at = datetime.now(UTC)
        stored.reprocess_override_by_admin_id = admin.id
        stored.reprocess_override_audit_id = dismissal_audit.id
        await session.commit()
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-same-audit-override",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)

    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, obligation, schema_version="gmail-task-v2"),
    )
    assert result.suggestion_ids == ()
    assert result.suppressed_action_keys == (obligation.action_key,)


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_suppression",
        "wrong_admin",
        "wrong_action",
        "wrong_path",
        "wrong_receipt",
        "accepted_status",
        "no_content_status",
        "wrong_method",
        "denied",
    ],
)
async def test_reprocess_audit_is_bound_to_exact_suppression_admin_and_route(
    suggestion_runtime,
    fault: str,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    thread_id = f"thread-resource-bound-override-{uuid4()}"
    obligation = _obligation()
    suppression, admin, _dismissal_audit = await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, thread_id),
        action_key=obligation.action_key,
        fingerprint=obligation.obligation_fingerprint,
        instance_digest=obligation.identity_instance_digest,
    )
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=thread_id,
    )
    metadata = {
        "admin_user_id": admin.id,
        "suppression_id": str(suppression.id),
    }
    action_id = "gmail_task_intake.reprocess"
    method = "POST"
    status_code = 200
    allowed = True
    path = (
        "/api/v1/admin/integrations/gmail-task-intake/reprocess/"
        f"{receipt.id}"
    )
    if fault == "wrong_suppression":
        metadata["suppression_id"] = str(uuid4())
    elif fault == "wrong_admin":
        metadata["admin_user_id"] = admin.id + 1
    elif fault == "wrong_action":
        action_id = "gmail_task_intake.status"
    elif fault == "wrong_path":
        path = f"/api/v1/admin/integrations/gmail/suppressions/{suppression.id}/reprocess"
    elif fault == "wrong_receipt":
        path = (
            "/api/v1/admin/integrations/gmail-task-intake/reprocess/"
            f"{uuid4()}"
        )
    elif fault == "accepted_status":
        status_code = 202
    elif fault == "no_content_status":
        status_code = 204
    elif fault == "wrong_method":
        method = "PUT"
    else:
        allowed = False

    async with sessions() as session:
        audit = AgentActionAudit(
            actor="admin",
            action_id=action_id,
            method=method,
            path=path,
            status_code=status_code,
            allowed=allowed,
            request_meta_json=json.dumps(
                metadata,
                sort_keys=True,
                separators=(",", ":"),
            ),
            response_meta_json="{}",
        )
        session.add(audit)
        await session.flush()
        stored = await session.get(type(suppression), suppression.id)
        stored.reprocess_override_at = datetime.now(UTC)
        stored.reprocess_override_by_admin_id = admin.id
        stored.reprocess_override_audit_id = audit.id
        await session.commit()

    result = await _claim_and_reconcile(
        GmailObligationReconciliationService(sessionmaker=sessions),
        receipt,
        _extraction(receipt, obligation, schema_version="gmail-task-v2"),
    )
    assert result.suggestion_ids == ()
    assert result.suppressed_action_keys == (obligation.action_key,)


@pytest.mark.parametrize("temporal_fault", ["before_dismissal", "after_override"])
async def test_reprocess_override_requires_exact_temporal_authority(
    suggestion_runtime,
    temporal_fault: str,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    thread_id = f"thread-temporal-override-{uuid4()}"
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=thread_id,
    )
    obligation = _obligation()
    suppression, admin, _dismissal_audit = await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, thread_id),
        action_key=obligation.action_key,
        fingerprint=obligation.obligation_fingerprint,
        instance_digest=obligation.identity_instance_digest,
    )
    dismissed_at = datetime(2026, 8, 21, 14, 5, tzinfo=UTC)
    override_at = datetime(2026, 8, 21, 14, 6, tzinfo=UTC)
    audit_created_at = (
        datetime(2026, 8, 21, 14, 4, tzinfo=UTC)
        if temporal_fault == "before_dismissal"
        else datetime(2026, 8, 21, 14, 7, tzinfo=UTC)
    )
    async with sessions() as session:
        audit = AgentActionAudit(
            created_at=audit_created_at,
            actor="admin",
            action_id="gmail_task_intake.reprocess",
            method="POST",
            path=(
                "/api/v1/admin/integrations/gmail-task-intake/reprocess/"
                f"{receipt.id}"
            ),
            status_code=200,
            allowed=True,
            request_meta_json=json.dumps(
                {
                    "admin_user_id": admin.id,
                    "suppression_id": str(suppression.id),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            response_meta_json="{}",
        )
        session.add(audit)
        await session.flush()
        stored = await session.get(type(suppression), suppression.id)
        stored.dismissed_at = dismissed_at
        stored.reprocess_override_at = override_at
        stored.reprocess_override_by_admin_id = admin.id
        stored.reprocess_override_audit_id = audit.id
        await session.commit()

    result = await _claim_and_reconcile(
        GmailObligationReconciliationService(sessionmaker=sessions),
        receipt,
        _extraction(receipt, obligation, schema_version="gmail-task-v2"),
    )
    assert result.suggestion_ids == ()
    assert result.suppressed_action_keys == (obligation.action_key,)


async def test_real_extractor_priority_upgrade_keeps_suppression_effective(
    suggestion_runtime,
) -> None:
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_message_sanitizer import SanitizedGmailMessage
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )
    from services.gmail_task_extractor import GmailTaskExtractor
    from services.integration_health_service import BoundedProviderExecutor

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-priority-suppression",
        message_id="priority-v1",
    )
    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-priority-suppression",
        message_id="priority-v2",
    )

    def model_response(schema_version: str, priority: str) -> dict[str, object]:
        return {
            "schema_version": schema_version,
            "actions": [
                {
                    "kind": "incoming_request",
                    "semantic_action": "call",
                    "semantic_object": "showing_feedback",
                    "title": "Call Alice about the showing",
                    "description": "Discuss Alice's showing feedback.",
                    "priority": priority,
                    "due_at": "2026-08-22T19:00:00Z",
                    "timezone_basis": "America/New_York",
                    "due_at_ambiguous": False,
                    "requested_owner": None,
                    "owner_ambiguous": False,
                    "requested_link_type": None,
                    "requested_link_id": None,
                    "contact_hint": None,
                    "confidence": 0.9,
                    "rationale": "The client asks for a call.",
                }
            ],
        }

    def transient(receipt) -> SanitizedGmailMessage:
        return SanitizedGmailMessage(
            message_id=receipt.gmail_message_id,
            thread_id=receipt.gmail_thread_id,
            direction=receipt.direction,
            message_at=receipt.message_at,
            sender_hmac=receipt.sender_hmac,
            recipient_hmacs=("b" * 64,),
            subject_preview=receipt.subject_preview,
            body_hash=receipt.body_hash,
            labels=("INBOX",),
            processing_state="processing",
            classification="eligible",
            transient_body_text="Please call about the showing.",
            body_truncated=False,
        )

    executor = BoundedProviderExecutor(max_workers=1)
    try:
        first_extractor = GmailTaskExtractor(
            executor=executor,
            model_call=lambda _request: model_response("gmail-task-v1", "normal"),
            deadline_seconds=1,
            schema_version="gmail-task-v1",
        )
        first = await first_extractor.extract(
            account_id=account.id,
            message=transient(first_receipt),
        )
        second_extractor = GmailTaskExtractor(
            executor=executor,
            model_call=lambda _request: model_response("gmail-task-v2", "high"),
            deadline_seconds=1,
            schema_version="gmail-task-v2",
        )
        second = await second_extractor.extract(
            account_id=account.id,
            message=transient(second_receipt),
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    assert first.obligations[0].action_key == second.obligations[0].action_key
    assert (
        first.obligations[0].obligation_fingerprint
        == second.obligations[0].obligation_fingerprint
    )
    await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, first_receipt.gmail_thread_id),
        action_key=first.obligations[0].action_key,
        fingerprint=first.obligations[0].obligation_fingerprint,
        instance_digest=first.obligations[0].identity_instance_digest,
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)

    result = await _claim_and_reconcile(service, second_receipt, second)
    assert result.suggestion_ids == ()
    assert result.suppressed_action_keys == (second.obligations[0].action_key,)


async def test_material_change_increments_version_and_changes_payload_hash(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import CRMTaskSuggestionService
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-material-change",
        message_id="material-v1",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first_result = await _claim_and_reconcile(
        service,
        first_receipt,
        _extraction(first_receipt, _obligation()),
    )
    async with sessions() as session:
        initial = await session.get(CRMTaskSuggestion, first_result.suggestion_ids[0])
        old_version = initial.version
        old_hash = initial.payload_hash

    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-material-change",
        message_id="material-v2",
    )
    # Priority is presentation material but is intentionally excluded from
    # both the semantic fingerprint and the title/description instance digest.
    changed = _obligation(priority="high")
    second_result = await _claim_and_reconcile(
        service,
        second_receipt,
        _extraction(second_receipt, changed),
    )
    assert second_result.suggestion_ids == first_result.suggestion_ids

    async with sessions() as session:
        updated = await session.get(CRMTaskSuggestion, first_result.suggestion_ids[0])
        assert updated.version == old_version + 1
        assert updated.payload_hash != old_hash
        assert CRMTaskSuggestionService.is_current(
            updated,
            expected_version=updated.version,
            expected_payload_hash=updated.payload_hash,
        )
        assert not CRMTaskSuggestionService.is_current(
            updated,
            expected_version=old_version,
            expected_payload_hash=old_hash,
        )


async def test_material_source_change_supersedes_active_clarification(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )
    from services.sydney_clarification_service import SydneyClarificationService

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-material-supersedes-question",
        message_id="material-question-v1",
    )
    reconciliation = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(
        reconciliation,
        first_receipt,
        _extraction(first_receipt, _obligation(due_at_ambiguous=True)),
    )
    clarification_service = SydneyClarificationService(
        sessionmaker=sessions,
        brandon_chat_id="-1001234567890",
        clarification_code_keys={7: b"k" * 32},
        active_code_key_version=7,
    )
    queued = await clarification_service.enqueue_next(
        suggestion_id=first.suggestion_ids[0],
        party_label="Alice",
        subject_preview="Material source change",
        now=datetime(2026, 8, 21, 15, 0, tzinfo=UTC),
    )
    assert queued.created is True

    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=first_receipt.gmail_thread_id,
        message_id="material-question-v2",
    )
    second = await _claim_and_reconcile(
        reconciliation,
        second_receipt,
        _extraction(
            second_receipt,
            _obligation(due_at_ambiguous=True, priority="high"),
        ),
    )
    assert second.suggestion_ids == first.suggestion_ids
    async with sessions() as session:
        suggestion = await session.get(
            CRMTaskSuggestion, first.suggestion_ids[0]
        )
        clarification = await session.get(
            CRMTaskClarification, queued.clarification_id
        )
        outbox = await session.get(SydneyQuestionOutbox, queued.outbox_id)
    assert suggestion.version == 2
    assert clarification.state == "superseded"
    assert outbox.state == "failed"
    assert outbox.failure_category == "pre_send_superseded"


async def test_contact_answer_vs_source_update_serializes_without_deadlock(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )
    from services.sydney_clarification_service import (
        SydneyClarificationError,
        SydneyClarificationService,
        derive_clarification_code,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        session.add(
            CRMContact(
                first_name="Alice",
                last_name="Client",
                email="alice-source-race@example.test",
                phone=None,
                stage="lead",
            )
        )
        await session.commit()
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-contact-answer-source-race",
        message_id="contact-answer-source-v1",
    )
    base_reconciliation = GmailObligationReconciliationService(
        sessionmaker=sessions
    )
    first = await _claim_and_reconcile(
        base_reconciliation,
        first_receipt,
        _extraction(
            first_receipt,
            _obligation(contact_hint="unknown-source-race@example.test"),
        ),
    )
    clarification_service = SydneyClarificationService(
        sessionmaker=sessions,
        brandon_chat_id="-1001234567890",
        clarification_code_keys={7: b"k" * 32},
        active_code_key_version=7,
    )
    now = datetime(2026, 8, 21, 15, 30, tzinfo=UTC)
    queued = await clarification_service.enqueue_next(
        suggestion_id=first.suggestion_ids[0],
        party_label="Alice",
        subject_preview="Contact race",
        now=now,
    )
    async with sessions() as session:
        clarification = await session.get(
            CRMTaskClarification,
            queued.clarification_id,
        )
        outbox = await session.get(SydneyQuestionOutbox, queued.outbox_id)
        assert clarification is not None and outbox is not None
        outbox.state = "sending"
        outbox.attempted_at = now + timedelta(seconds=1)
        outbox.telegram_chat_id = "-1001234567890"
        clarification.first_attempt_at = outbox.attempted_at
        clarification.deadline_anchor_kind = "first_attempt"
        clarification.deadline_anchored_at = outbox.attempted_at
        clarification.slot_deadline_at = outbox.attempted_at + timedelta(
            hours=48
        )
        await session.flush()
        outbox.state = "sent"
        outbox.sent_at = now + timedelta(seconds=2)
        outbox.telegram_message_id = "9100"
        clarification.deadline_anchor_kind = "initial_sent"
        clarification.deadline_anchored_at = outbox.sent_at
        clarification.slot_deadline_at = outbox.sent_at + timedelta(hours=48)
        await session.commit()
        code = derive_clarification_code(
            key=b"k" * 32,
            key_version=clarification.code_key_version,
            clarification_id=clarification.id,
            suggestion_id=clarification.suggestion_id,
            suggestion_version=clarification.suggestion_version,
            field_name=clarification.field_name,
            round_number=clarification.round_number,
        )

    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=first_receipt.gmail_thread_id,
        message_id="contact-answer-source-v2",
    )
    contact_locked = asyncio.Event()
    release_reconciliation = asyncio.Event()

    class PausingReconciliation(GmailObligationReconciliationService):
        @staticmethod
        async def _resolve_contact(*, session, contact_hint):
            result = await GmailObligationReconciliationService._resolve_contact(
                session=session,
                contact_hint=contact_hint,
            )
            contact_locked.set()
            await release_reconciliation.wait()
            return result

    reconciliation = PausingReconciliation(sessionmaker=sessions)
    extraction = _extraction(
        second_receipt,
        _obligation(
            contact_hint="alice-source-race@example.test",
            priority="high",
        ),
    )
    claim = await reconciliation.claim_attempt(
        receipt_id=second_receipt.id,
        schema_version=extraction.schema_version,
    )

    reconcile_task = asyncio.create_task(
        reconciliation.reconcile_attempt(claim=claim, extraction=extraction)
    )
    await asyncio.wait_for(contact_locked.wait(), timeout=2)

    async def answer_late():
        try:
            return await clarification_service.answer(
                code=code,
                expected_suggestion_version=1,
                answer={
                    "kind": "contact",
                    "decision": "exact_email",
                    "email": "alice-source-race@example.test",
                },
                now=now + timedelta(minutes=1),
            )
        except SydneyClarificationError:
            return None

    answer_task = asyncio.create_task(answer_late())
    await asyncio.sleep(0.05)
    assert not answer_task.done()
    release_reconciliation.set()
    reconciled, answer = await asyncio.wait_for(
        asyncio.gather(reconcile_task, answer_task),
        timeout=5,
    )
    assert reconciled.suggestion_ids == first.suggestion_ids
    assert answer is None
    async with sessions() as session:
        clarification = await session.get(
            CRMTaskClarification,
            queued.clarification_id,
        )
    assert clarification.state == "superseded"


@pytest.mark.parametrize(
    ("change", "expected_field", "expected_value", "expected_blockers"),
    [
        ({"priority": "high"}, "priority", "high", []),
    ],
)
async def test_material_fields_are_compared_independently_of_model_fingerprint(
    suggestion_runtime,
    change: dict[str, object],
    expected_field: str,
    expected_value: str,
    expected_blockers: list[str],
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=f"thread-material-independent-{uuid4()}",
        message_id=f"material-base-{uuid4()}",
    )
    base = _obligation()
    first = await _claim_and_reconcile(
        service,
        first_receipt,
        _extraction(first_receipt, base),
    )
    async with sessions() as session:
        initial = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        initial_version = initial.version
        initial_hash = initial.payload_hash

    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=first_receipt.gmail_thread_id,
        message_id=f"material-change-{uuid4()}",
        direction="sent",
    )
    changed = _obligation(kind="outgoing_commitment", **change)
    assert changed.obligation_fingerprint == base.obligation_fingerprint
    second = await _claim_and_reconcile(
        service,
        second_receipt,
        _extraction(second_receipt, changed),
    )

    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        source_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestionSource.id)).where(
                CRMTaskSuggestionSource.suggestion_id == stored.id
            )
        )
    assert second.suggestion_ids == first.suggestion_ids
    assert stored.version == initial_version + 1
    assert getattr(stored, expected_field) == expected_value
    assert stored.blocker_codes == expected_blockers
    assert source_count == 2
    if expected_field in {"title", "description", "priority"} and not expected_blockers:
        assert stored.payload_hash != initial_hash


async def test_pure_source_attachment_does_not_increment_suggestion_version(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-source-only",
        message_id="source-only-one",
    )
    first = await _claim_and_reconcile(
        service,
        first_receipt,
        _extraction(first_receipt, _obligation()),
    )
    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-source-only",
        message_id="source-only-two",
        direction="sent",
    )
    await _claim_and_reconcile(
        service,
        second_receipt,
        _extraction(
            second_receipt,
            _obligation(kind="outgoing_commitment"),
            schema_version="gmail-task-v2",
        ),
    )

    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
    assert stored.version == 1


@pytest.mark.parametrize("terminal_state", ["approved", "dismissed", "applied", "failed"])
async def test_material_late_evidence_never_rewrites_terminal_suggestion_payload(
    suggestion_runtime,
    terminal_state: str,
) -> None:
    from models.command import CRMTask
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=f"thread-terminal-{terminal_state}",
        message_id=f"terminal-{terminal_state}-one",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(
        service,
        first_receipt,
        _extraction(first_receipt, _obligation()),
    )
    original_id = first.suggestion_ids[0]
    async with sessions() as session:
        original = await session.get(CRMTaskSuggestion, original_id)
        if terminal_state == "applied":
            task = CRMTask(
                title=original.title,
                description=original.description,
                status="open",
                priority=original.priority,
                due_at=original.due_at,
                contact_id=original.contact_id,
            )
            session.add(task)
            await session.flush()
        original.state = terminal_state
        if terminal_state == "applied":
            original.applied_task_id = task.id
            original.application_idempotency_key = uuid4()
        await session.commit()
        snapshot = (
            original.version,
            original.title,
            original.description,
            original.due_at,
            original.payload_hash,
            original.state,
            original.applied_task_id,
        )

    late_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=f"thread-terminal-{terminal_state}",
        message_id=f"terminal-{terminal_state}-two",
    )
    late = _obligation(
        description="Materially different follow-up and pricing analysis.",
        due_at=datetime(2026, 8, 24, 19, 0, tzinfo=UTC),
        obligation_fingerprint="7" * 64,
    )
    result = await _claim_and_reconcile(
        service,
        late_receipt,
        _extraction(late_receipt, late),
    )

    async with sessions() as session:
        original = await session.get(CRMTaskSuggestion, original_id)
        suggestions = list(
            (
                await session.scalars(
                    sa.select(CRMTaskSuggestion).order_by(CRMTaskSuggestion.created_at)
                )
            ).all()
        )
    assert (
        original.version,
        original.title,
        original.description,
        original.due_at,
        original.payload_hash,
        original.state,
        original.applied_task_id,
    ) == snapshot
    assert len(suggestions) == 2
    late_suggestion = next(row for row in suggestions if row.id != original_id)
    assert result.suggestion_ids == (late_suggestion.id,)
    assert late_suggestion.state == "possible_duplicate"
    assert late_suggestion.duplicate_of_suggestion_id == original_id


@pytest.mark.parametrize("terminal_state", ["approved", "applied"])
async def test_terminal_same_fingerprint_new_instance_gets_blocked_successor(
    suggestion_runtime,
    terminal_state: str,
) -> None:
    from models.command import CRMTask
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=f"thread-terminal-instance-{terminal_state}",
        message_id=f"terminal-instance-{terminal_state}-one",
    )
    first = await _claim_and_reconcile(
        service,
        first_receipt,
        _extraction(first_receipt, _obligation()),
    )
    original_id = first.suggestion_ids[0]
    async with sessions() as session:
        original = await session.get(CRMTaskSuggestion, original_id)
        if terminal_state == "applied":
            task = CRMTask(
                title=original.title,
                description=original.description,
                status="open",
                priority=original.priority,
                due_at=original.due_at,
                contact_id=original.contact_id,
            )
            session.add(task)
            await session.flush()
            original.applied_task_id = task.id
            original.application_idempotency_key = uuid4()
        original.state = terminal_state
        await session.commit()
        original_snapshot = (
            original.version,
            original.title,
            original.description,
            original.payload_hash,
            original.state,
            original.applied_task_id,
        )

    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=first_receipt.gmail_thread_id,
        message_id=f"terminal-instance-{terminal_state}-two",
    )
    different_instance = _obligation(
        title="Call Alice about 456 Oak",
        description="Discuss showing feedback for 456 Oak.",
    )
    assert different_instance.obligation_fingerprint == _obligation().obligation_fingerprint
    result = await _claim_and_reconcile(
        service,
        second_receipt,
        _extraction(second_receipt, different_instance),
    )

    async with sessions() as session:
        original = await session.get(CRMTaskSuggestion, original_id)
        suggestions = list(
            (await session.scalars(sa.select(CRMTaskSuggestion))).all()
        )
        sources = list(
            (await session.scalars(sa.select(CRMTaskSuggestionSource))).all()
        )
    assert (
        original.version,
        original.title,
        original.description,
        original.payload_hash,
        original.state,
        original.applied_task_id,
    ) == original_snapshot
    assert len(suggestions) == 2
    successor = next(row for row in suggestions if row.id != original_id)
    assert result.suggestion_ids == (successor.id,)
    assert successor.duplicate_of_suggestion_id == original_id
    assert successor.state in {"needs_clarification", "possible_duplicate"}
    assert not (
        successor.state == "pending_review"
        and successor.clarification_state == "not_required"
        and successor.blocker_codes == []
    )
    assert sum(row.suggestion_id == original_id for row in sources) == 1
    assert sum(row.suggestion_id == successor.id for row in sources) == 1


@pytest.mark.parametrize("terminal_state", ["approved", "applied"])
async def test_terminal_recognizes_every_previously_attached_instance_digest(
    suggestion_runtime,
    terminal_state: str,
) -> None:
    from models.command import CRMTask
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id=f"thread-terminal-membership-{terminal_state}",
            message_id=f"terminal-membership-{terminal_state}-{index}",
        )
        for index in range(3)
    ]
    action_a = _model_action(
        title="Call Alice about 123 Main",
        description="Discuss showing feedback for 123 Main.",
    )
    action_b = _model_action(
        title="Call Alice about 456 Oak",
        description="Discuss showing feedback for 456 Oak.",
    )
    first = await _claim_and_reconcile(
        service,
        receipts[0],
        await _extract_model_actions(receipts[0], action_a),
    )
    second = await _claim_and_reconcile(
        service,
        receipts[1],
        await _extract_model_actions(receipts[1], action_b),
    )
    assert first.suggestion_ids == second.suggestion_ids
    suggestion_id = first.suggestion_ids[0]
    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, suggestion_id)
        suggestion.blocker_codes = []
        suggestion.clarification_state = "not_required"
        if terminal_state == "applied":
            task = CRMTask(
                title=suggestion.title,
                description=suggestion.description,
                status="open",
                priority=suggestion.priority,
                due_at=suggestion.due_at,
                contact_id=suggestion.contact_id,
            )
            session.add(task)
            await session.flush()
            suggestion.applied_task_id = task.id
            suggestion.application_idempotency_key = uuid4()
        suggestion.state = terminal_state
        await session.commit()
        snapshot = (
            suggestion.version,
            suggestion.title,
            suggestion.description,
            suggestion.payload_hash,
            suggestion.primary_instance_digest,
            suggestion.state,
            suggestion.applied_task_id,
        )

    continuation = await _claim_and_reconcile(
        service,
        receipts[2],
        await _extract_model_actions(receipts[2], action_b),
    )

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, suggestion_id)
        suggestion_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestion.id))
        )
        source_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestionSource.id)).where(
                CRMTaskSuggestionSource.suggestion_id == suggestion_id
            )
        )
    assert continuation.suggestion_ids == (suggestion_id,)
    assert suggestion_count == 1
    assert source_count == 3
    assert (
        suggestion.version,
        suggestion.title,
        suggestion.description,
        suggestion.payload_hash,
        suggestion.primary_instance_digest,
        suggestion.state,
        suggestion.applied_task_id,
    ) == snapshot


async def test_nonprimary_instance_material_change_invalidates_review_preview(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id="thread-nonprimary-material-change",
            message_id=f"nonprimary-material-{index}",
        )
        for index in range(3)
    ]
    action_a = _model_action(
        title="Call Alice about 123 Main",
        description="Discuss showing feedback for 123 Main.",
    )
    action_b = _model_action(
        title="Call Alice about 456 Oak",
        description="Discuss showing feedback for 456 Oak.",
    )
    changed_b = _model_action(
        title="Call Alice about 456 Oak",
        description="Discuss showing feedback for 456 Oak.",
        priority="high",
    )
    first = await _claim_and_reconcile(
        service,
        receipts[0],
        await _extract_model_actions(receipts[0], action_a),
    )
    second = await _claim_and_reconcile(
        service,
        receipts[1],
        await _extract_model_actions(receipts[1], action_b),
    )
    assert first.suggestion_ids == second.suggestion_ids
    suggestion_id = first.suggestion_ids[0]
    async with sessions() as session:
        before = await session.get(CRMTaskSuggestion, suggestion_id)
        before_snapshot = (
            before.version,
            before.title,
            before.description,
            before.priority,
            before.payload_hash,
        )

    continuation = await _claim_and_reconcile(
        service,
        receipts[2],
        await _extract_model_actions(receipts[2], changed_b),
    )

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, suggestion_id)
        obligations = list(
            (
                await session.scalars(
                    sa.select(GmailExtractedObligation).order_by(
                        GmailExtractedObligation.created_at,
                        GmailExtractedObligation.id,
                    )
                )
            ).all()
        )
        source_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestionSource.id)).where(
                CRMTaskSuggestionSource.suggestion_id == suggestion_id
            )
        )
    assert continuation.suggestion_ids == (suggestion_id,)
    assert suggestion.version == before_snapshot[0] + 1
    assert (
        suggestion.title,
        suggestion.description,
        suggestion.priority,
        suggestion.payload_hash,
    ) == before_snapshot[1:]
    assert suggestion.state == "needs_clarification"
    assert suggestion.clarification_state == "manual_review_required"
    assert suggestion.blocker_codes == ["multiple_actions"]
    assert source_count == 3
    b_rows = [
        row
        for row in obligations
        if row.identity_instance_digest
        == obligations[1].identity_instance_digest
    ]
    assert len(b_rows) == 2
    assert len({row.reconciliation_material_hash for row in b_rows}) == 2


@pytest.mark.parametrize("terminal_state", ["approved", "applied"])
async def test_terminal_nonprimary_material_conflict_creates_blocked_successor(
    suggestion_runtime,
    terminal_state: str,
) -> None:
    from models.command import CRMTask
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id=f"thread-terminal-material-{terminal_state}",
            message_id=f"terminal-material-{terminal_state}-{index}",
        )
        for index in range(3)
    ]
    action_a = _model_action(
        title="Call Alice about 123 Main",
        description="Discuss showing feedback for 123 Main.",
    )
    action_b = _model_action(
        title="Call Alice about 456 Oak",
        description="Discuss showing feedback for 456 Oak.",
    )
    changed_b = _model_action(
        title="Call Alice about 456 Oak",
        description="Discuss showing feedback for 456 Oak.",
        priority="high",
    )
    first = await _claim_and_reconcile(
        service,
        receipts[0],
        await _extract_model_actions(receipts[0], action_a),
    )
    await _claim_and_reconcile(
        service,
        receipts[1],
        await _extract_model_actions(receipts[1], action_b),
    )
    original_id = first.suggestion_ids[0]
    async with sessions() as session:
        original = await session.get(CRMTaskSuggestion, original_id)
        original.blocker_codes = []
        original.clarification_state = "not_required"
        if terminal_state == "applied":
            task = CRMTask(
                title=original.title,
                description=original.description,
                status="open",
                priority=original.priority,
                due_at=original.due_at,
                contact_id=original.contact_id,
            )
            session.add(task)
            await session.flush()
            original.applied_task_id = task.id
            original.application_idempotency_key = uuid4()
        original.state = terminal_state
        await session.commit()
        original_snapshot = (
            original.version,
            original.title,
            original.description,
            original.priority,
            original.payload_hash,
            original.state,
            original.applied_task_id,
        )

    conflict = await _claim_and_reconcile(
        service,
        receipts[2],
        await _extract_model_actions(receipts[2], changed_b),
    )

    async with sessions() as session:
        original = await session.get(CRMTaskSuggestion, original_id)
        suggestions = list(
            (await session.scalars(sa.select(CRMTaskSuggestion))).all()
        )
        sources = list(
            (await session.scalars(sa.select(CRMTaskSuggestionSource))).all()
        )
    assert (
        original.version,
        original.title,
        original.description,
        original.priority,
        original.payload_hash,
        original.state,
        original.applied_task_id,
    ) == original_snapshot
    assert len(suggestions) == 2
    successor = next(row for row in suggestions if row.id != original_id)
    assert conflict.suggestion_ids == (successor.id,)
    assert successor.duplicate_of_suggestion_id == original_id
    assert successor.priority == "high"
    assert successor.state in {"needs_clarification", "possible_duplicate"}
    assert "multiple_actions" in successor.blocker_codes
    assert not (
        successor.state == "pending_review"
        and successor.clarification_state == "not_required"
        and successor.blocker_codes == []
    )
    assert sum(row.suggestion_id == original_id for row in sources) == 2
    assert sum(row.suggestion_id == successor.id for row in sources) == 1


@pytest.mark.parametrize("terminal_state", ["approved", "applied"])
async def test_exact_terminal_evidence_only_attaches_source_without_mutation(
    suggestion_runtime,
    terminal_state: str,
) -> None:
    from models.command import CRMTask
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=f"thread-terminal-exact-{terminal_state}",
        message_id=f"terminal-exact-{terminal_state}-one",
    )
    first = await _claim_and_reconcile(
        service,
        first_receipt,
        _extraction(first_receipt, _obligation()),
    )
    suggestion_id = first.suggestion_ids[0]
    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion_id)
        if terminal_state == "applied":
            task = CRMTask(
                title=stored.title,
                description=stored.description,
                status="open",
                priority=stored.priority,
                due_at=stored.due_at,
                contact_id=stored.contact_id,
            )
            session.add(task)
            await session.flush()
            stored.applied_task_id = task.id
            stored.application_idempotency_key = uuid4()
        stored.state = terminal_state
        await session.commit()
        snapshot = (
            stored.version,
            stored.payload_hash,
            stored.title,
            stored.description,
            stored.state,
            stored.applied_task_id,
        )

    continuation_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=first_receipt.gmail_thread_id,
        message_id=f"terminal-exact-{terminal_state}-two",
    )
    continuation = await _claim_and_reconcile(
        service,
        continuation_receipt,
        _extraction(continuation_receipt, _obligation()),
    )

    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion_id)
        suggestion_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestion.id))
        )
        source_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestionSource.id)).where(
                CRMTaskSuggestionSource.suggestion_id == suggestion_id
            )
        )
    assert continuation.suggestion_ids == (suggestion_id,)
    assert suggestion_count == 1
    assert source_count == 2
    assert (
        stored.version,
        stored.payload_hash,
        stored.title,
        stored.description,
        stored.state,
        stored.applied_task_id,
    ) == snapshot


async def test_reviewable_duplicate_is_the_authoritative_same_key_successor(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-duplicate-successor",
        message_id="duplicate-successor-a",
    )
    first = await _claim_and_reconcile(
        service,
        first_receipt,
        _extraction(first_receipt, _obligation()),
    )
    async with sessions() as session:
        original = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        original.state = "approved"
        await session.commit()

    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-duplicate-successor",
        message_id="duplicate-successor-b",
    )
    second = await _claim_and_reconcile(
        service,
        second_receipt,
        _extraction(
            second_receipt,
            _obligation(
                description="Updated follow-up evidence.",
                obligation_fingerprint="6" * 64,
            ),
        ),
    )
    successor_id = second.suggestion_ids[0]
    assert successor_id != first.suggestion_ids[0]

    continuation_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-duplicate-successor",
        message_id="duplicate-successor-b-continuation",
        direction="sent",
    )
    continuation = await _claim_and_reconcile(
        service,
        continuation_receipt,
        _extraction(
            continuation_receipt,
            _obligation(
                kind="outgoing_commitment",
                description="Final updated follow-up evidence.",
                obligation_fingerprint="6" * 64,
            ),
        ),
    )

    async with sessions() as session:
        suggestions = list(
            (await session.scalars(sa.select(CRMTaskSuggestion))).all()
        )
        successor = await session.get(CRMTaskSuggestion, successor_id)
        successor_source_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestionSource.id)).where(
                CRMTaskSuggestionSource.suggestion_id == successor_id
            )
        )
    assert continuation.suggestion_ids == (successor_id,)
    assert len(suggestions) == 2
    assert successor.state == "possible_duplicate"
    assert successor.duplicate_of_suggestion_id == first.suggestion_ids[0]
    assert successor.version == 2
    assert successor_source_count == 2


@pytest.mark.parametrize(
    ("obligation_overrides", "expected_state", "expected_blockers"),
    [
        (
            {"requested_owner": "Pat Agent", "owner_ambiguous": False},
            "pending_review",
            ["unsupported_owner"],
        ),
        (
            {"requested_owner": None, "owner_ambiguous": True},
            "needs_clarification",
            ["missing_required_field"],
        ),
        (
            {
                "requested_link_type": "opportunity",
                "requested_link_id": "opportunity-123",
            },
            "pending_review",
            ["unsupported_link"],
        ),
        (
            {
                "requested_link_type": "listing",
                "requested_link_id": "listing-123",
            },
            "pending_review",
            ["unsupported_link"],
        ),
        (
            {
                "requested_link_type": "agreement",
                "requested_link_id": "agreement-123",
            },
            "pending_review",
            ["unsupported_link"],
        ),
        (
            {
                "requested_owner": "Pat Agent",
                "owner_ambiguous": False,
                "requested_link_type": "listing",
                "requested_link_id": "listing-123",
            },
            "pending_review",
            ["unsupported_owner", "unsupported_link"],
        ),
        (
            {
                "due_at": None,
                "timezone_basis": None,
                "due_at_ambiguous": True,
            },
            "needs_clarification",
            ["ambiguous_due_at"],
        ),
    ],
)
async def test_owner_due_and_link_authority_shape_blocks_approval(
    suggestion_runtime,
    obligation_overrides: dict[str, object],
    expected_state: str,
    expected_blockers: list[str],
) -> None:
    from models.command import CRMTaskLink
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import (
        CRMTaskSuggestionAuthorityError,
        CRMTaskSuggestionService,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=f"thread-authority-{uuid4()}",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, _obligation(**obligation_overrides)),
    )

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        link_count = await session.scalar(sa.select(sa.func.count(CRMTaskLink.id)))
        assert suggestion.state == expected_state
        assert suggestion.blocker_codes == expected_blockers
        assert suggestion.task_status == "open"
        assert suggestion.contact_id is None
        assert suggestion.owner_clarification_pending is bool(
            obligation_overrides.get("owner_ambiguous", False)
        )
        assert suggestion.task_details_clarification_pending is False
        assert suggestion.contact_resolution_state == "not_provided"
        assert suggestion.contact_resolution_hash is None
        assert not hasattr(suggestion, "owner_id")
        assert CRMTaskSuggestionService.approval_eligible(suggestion) is False
        with pytest.raises(CRMTaskSuggestionAuthorityError, match="suggestion_blocked"):
            await CRMTaskSuggestionService.task_payload(
                session=session,
                suggestion=suggestion,
                expected_version=suggestion.version,
                expected_payload_hash=suggestion.payload_hash,
            )
    assert link_count == 0


async def test_implicit_brandon_owner_produces_exact_supported_task_payload(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from schemas.gmail_task_intake import GmailTaskPayload
    from services.crm_task_suggestion_service import CRMTaskSuggestionService
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-brandon-owned",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, _obligation(requested_owner=None, owner_ambiguous=False)),
    )

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
    payload = CRMTaskSuggestionService.preview_payload(suggestion)
    assert isinstance(payload, GmailTaskPayload)
    assert payload.model_dump() == {
        "title": "Call Alice about the showing",
        "description": "Discuss Alice's feedback from the property showing.",
        "priority": "normal",
        "due_at": datetime(2026, 8, 22, 19, 0, tzinfo=UTC),
        "contact_id": None,
        "status": "open",
    }
    assert CRMTaskSuggestionService.approval_eligible(suggestion) is True


async def test_explicit_brandon_owner_is_supported_but_other_owners_are_not(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    brandon_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-explicit-brandon",
    )
    other_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-explicit-other",
    )
    compatibility_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-explicit-brandon-compatibility",
    )
    brandon = await _claim_and_reconcile(
        service,
        brandon_receipt,
        _extraction(
            brandon_receipt,
            _obligation(requested_owner="Brandon", owner_ambiguous=False),
        ),
    )
    other = await _claim_and_reconcile(
        service,
        other_receipt,
        _extraction(
            other_receipt,
            _obligation(
                action_key="action-v1:" + "8" * 64,
                requested_owner="Pat Agent",
                owner_ambiguous=False,
            ),
        ),
    )
    compatibility = await _claim_and_reconcile(
        service,
        compatibility_receipt,
        _extraction(
            compatibility_receipt,
            _obligation(
                action_key="action-v1:" + "9" * 64,
                requested_owner="Ｂｒａｎｄｏｎ　Ｓｗｅｅｎｅｙ",
                owner_ambiguous=False,
            ),
        ),
    )

    async with sessions() as session:
        brandon_suggestion = await session.get(
            CRMTaskSuggestion, brandon.suggestion_ids[0]
        )
        other_suggestion = await session.get(
            CRMTaskSuggestion, other.suggestion_ids[0]
        )
        compatibility_suggestion = await session.get(
            CRMTaskSuggestion,
            compatibility.suggestion_ids[0],
        )
    assert brandon_suggestion.blocker_codes == []
    assert compatibility_suggestion.blocker_codes == []
    assert other_suggestion.blocker_codes == ["unsupported_owner"]


@pytest.mark.parametrize(
    ("ascii_authority", "compatibility_authority"),
    [
        (
            {"requested_owner": "Brandon Sweeney"},
            {"requested_owner": "Ｂｒａｎｄｏｎ　Ｓｗｅｅｎｅｙ"},
        ),
        (
            {
                "requested_link_type": "listing",
                "requested_link_id": "listing-123",
            },
            {
                "requested_link_type": "listing",
                "requested_link_id": "ｌｉｓｔｉｎｇ－１２３",
            },
        ),
    ],
)
async def test_nfkc_equivalent_authority_cannot_bypass_suppression(
    suggestion_runtime,
    ascii_authority: dict[str, object],
    compatibility_authority: dict[str, object],
) -> None:
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    thread_id = f"thread-nfkc-authority-{uuid4()}"
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=thread_id,
        message_id=f"nfkc-authority-ascii-{uuid4()}",
    )
    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=thread_id,
        message_id=f"nfkc-authority-compatibility-{uuid4()}",
    )
    first = await _extract_model_actions(
        first_receipt,
        _model_action(**ascii_authority),
    )
    second = await _extract_model_actions(
        second_receipt,
        _model_action(**compatibility_authority),
    )
    assert first.obligations[0].action_key == second.obligations[0].action_key
    assert first.obligations[0].obligation_fingerprint == (
        second.obligations[0].obligation_fingerprint
    )
    await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, thread_id),
        action_key=first.obligations[0].action_key,
        fingerprint=first.obligations[0].obligation_fingerprint,
        instance_digest=first.obligations[0].identity_instance_digest,
    )

    result = await _claim_and_reconcile(
        GmailObligationReconciliationService(sessionmaker=sessions),
        second_receipt,
        second,
    )
    assert result.suggestion_ids == ()
    assert result.suppressed_action_keys == (
        second.obligations[0].action_key,
    )


@pytest.mark.parametrize(
    "requested_owner",
    [
        "Brandon and Pat",
        "Brandon's assistant Pat",
        "Brandon Sweeney / Pat Agent",
    ],
)
async def test_mixed_owner_text_never_inherits_brandon_authority(
    suggestion_runtime,
    requested_owner: str,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import CRMTaskSuggestionService
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=f"thread-mixed-owner-{uuid4()}",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(
            receipt,
            _obligation(
                requested_owner=requested_owner,
                owner_ambiguous=False,
            ),
        ),
    )

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
    assert suggestion.blocker_codes == ["unsupported_owner"]
    assert CRMTaskSuggestionService.approval_eligible(suggestion) is False


async def test_late_owner_and_link_authority_never_clear_without_audited_resolution(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import (
        CRMTaskSuggestionService,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-late-authority",
        message_id="late-authority-one",
    )
    first_extraction = await _extract_model_actions(
        first_receipt,
        _model_action(),
    )
    first = await _claim_and_reconcile(
        service,
        first_receipt,
        first_extraction,
    )
    async with sessions() as session:
        original = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        old_version = original.version
        old_hash = original.payload_hash

    authority_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-late-authority",
        message_id="late-authority-two",
        direction="sent",
        recipient_hmacs=("a" * 64,),
    )
    authority_extraction = await _extract_model_actions(
        authority_receipt,
        _model_action(
            kind="outgoing_commitment",
            requested_owner="Pat Agent",
            requested_link_type="agreement",
            requested_link_id="agreement-123",
        ),
    )
    assert (
        first_extraction.obligations[0].obligation_fingerprint
        != authority_extraction.obligations[0].obligation_fingerprint
    )
    authority = await _claim_and_reconcile(
        service,
        authority_receipt,
        authority_extraction,
    )
    later_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-late-authority",
        message_id="late-authority-three",
    )
    await _claim_and_reconcile(
        service,
        later_receipt,
        await _extract_model_actions(later_receipt, _model_action()),
    )

    async with sessions() as session:
        original = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        changed = await session.get(CRMTaskSuggestion, authority.suggestion_ids[0])
        suggestions = list(
            (await session.scalars(sa.select(CRMTaskSuggestion))).all()
        )
    assert len(suggestions) == 2
    assert original.version == old_version + 1
    assert original.payload_hash == old_hash
    assert original.blocker_codes == []
    assert original.state == "possible_duplicate"
    assert changed.state == "possible_duplicate"
    assert changed.blocker_codes == ["unsupported_owner", "unsupported_link"]
    assert changed.duplicate_of_suggestion_id == original.id
    assert not CRMTaskSuggestionService.is_current(
        original,
        expected_version=old_version,
        expected_payload_hash=old_hash,
    )


async def test_apply_payload_boundary_rejects_blocked_unapproved_and_stale_suggestions(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import (
        CRMTaskSuggestionAuthorityError,
        CRMTaskSuggestionService,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-apply-boundary",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, _obligation()),
    )
    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        with pytest.raises(CRMTaskSuggestionAuthorityError, match="suggestion_not_approved"):
            await CRMTaskSuggestionService.task_payload(
                session=session,
                suggestion=suggestion,
                expected_version=suggestion.version,
                expected_payload_hash=suggestion.payload_hash,
            )
        suggestion.state = "approved"
        await session.commit()
        payload = await CRMTaskSuggestionService.task_payload(
            session=session,
            suggestion=suggestion,
            expected_version=suggestion.version,
            expected_payload_hash=suggestion.payload_hash,
        )
        assert payload.status == "open"
        with pytest.raises(CRMTaskSuggestionAuthorityError, match="suggestion_stale"):
            await CRMTaskSuggestionService.task_payload(
                session=session,
                suggestion=suggestion,
                expected_version=suggestion.version - 1,
                expected_payload_hash=suggestion.payload_hash,
            )
        suggestion.blocker_codes = ["unsupported_link"]
        await session.commit()
        with pytest.raises(CRMTaskSuggestionAuthorityError, match="suggestion_blocked"):
            await CRMTaskSuggestionService.task_payload(
                session=session,
                suggestion=suggestion,
                expected_version=suggestion.version,
                expected_payload_hash=suggestion.payload_hash,
            )


async def test_task_payload_reloads_state_under_thread_lock(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import (
        CRMTaskSuggestionAuthorityError,
        CRMTaskSuggestionService,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-stale-apply-object",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, _obligation()),
    )
    async with sessions() as stale_session:
        stale = await stale_session.get(
            CRMTaskSuggestion,
            result.suggestion_ids[0],
        )
        async with sessions() as writer:
            current = await writer.get(CRMTaskSuggestion, stale.id)
            current.state = "dismissed"
            await writer.commit()

        with pytest.raises(
            CRMTaskSuggestionAuthorityError,
            match="suggestion_not_approved",
        ):
            await CRMTaskSuggestionService.task_payload(
                session=stale_session,
                suggestion=stale,
                expected_version=stale.version,
                expected_payload_hash=stale.payload_hash,
            )


async def test_task_payload_uses_authoritative_db_scope_not_detached_caller_scope(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import CRMTaskSuggestionService
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )
    from services.integration_advisory_locks import transaction_advisory_lock

    engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-authoritative-task-payload-scope",
    )
    result = await _claim_and_reconcile(
        GmailObligationReconciliationService(sessionmaker=sessions),
        receipt,
        _extraction(receipt, _obligation()),
    )
    async with sessions() as session:
        current = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        current.state = "approved"
        await session.commit()
        suggestion_id = current.id
        expected_version = current.version
        expected_hash = current.payload_hash

    detached = CRMTaskSuggestion(
        id=suggestion_id,
        gmail_account_id=uuid4(),
        gmail_thread_id="caller-controlled-wrong-thread",
    )
    blocker = await engine.connect()
    blocker_transaction = await blocker.begin()
    await transaction_advisory_lock(
        blocker,
        account.id,
        receipt.gmail_thread_id,
    )
    worker = sessions()
    payload_task = asyncio.create_task(
        CRMTaskSuggestionService.task_payload(
            session=worker,
            suggestion=detached,
            expected_version=expected_version,
            expected_payload_hash=expected_hash,
        )
    )
    try:
        await asyncio.sleep(0.05)
        assert not payload_task.done()
    finally:
        await blocker_transaction.rollback()
        await blocker.close()
    try:
        payload = await asyncio.wait_for(payload_task, timeout=2)
        assert payload.title == "Call Alice about the showing"
    finally:
        await worker.rollback()
        await worker.close()


async def test_task_payload_blocks_live_different_fingerprint_sibling_under_thread_lock(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import (
        CRMTaskSuggestionAuthorityError,
        CRMTaskSuggestionService,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )
    from services.integration_advisory_locks import transaction_advisory_lock

    engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    thread_id = "thread-task-payload-live-fingerprint-sibling"
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id=thread_id,
            message_id=f"task-payload-sibling-{index}",
        )
        for index in range(2)
    ]
    extractions = [
        await _extract_model_actions(
            receipts[0],
            _model_action(due_at="2026-08-22T19:00:00Z"),
        ),
        await _extract_model_actions(
            receipts[1],
            _model_action(due_at="2026-08-24T19:00:00Z"),
        ),
    ]
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(service, receipts[0], extractions[0])
    second = await _claim_and_reconcile(service, receipts[1], extractions[1])
    async with sessions() as session:
        approved = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        sibling = await session.get(CRMTaskSuggestion, second.suggestion_ids[0])
        assert sibling.state == "possible_duplicate"
        assert sibling.obligation_fingerprint != approved.obligation_fingerprint
        approved.state = "approved"
        await session.commit()
        expected_version = approved.version
        expected_hash = approved.payload_hash

    blocker = await engine.connect()
    blocker_transaction = await blocker.begin()
    await transaction_advisory_lock(blocker, account.id, thread_id)
    worker = sessions()
    payload_task = asyncio.create_task(
        CRMTaskSuggestionService.task_payload(
            session=worker,
            suggestion=approved,
            expected_version=expected_version,
            expected_payload_hash=expected_hash,
        )
    )
    try:
        await asyncio.sleep(0.05)
        assert not payload_task.done()
    finally:
        await blocker_transaction.rollback()
        await blocker.close()
    try:
        with pytest.raises(
            CRMTaskSuggestionAuthorityError,
            match="^suggestion_blocked$",
        ):
            await asyncio.wait_for(payload_task, timeout=2)
    finally:
        await worker.rollback()
        await worker.close()


@pytest.mark.parametrize(
    ("sibling_state", "same_fingerprint"),
    [
        ("dismissed", False),
        ("pending_review", True),
    ],
)
async def test_task_payload_does_not_false_block_terminal_or_same_fingerprint_sibling(
    suggestion_runtime,
    sibling_state: str,
    same_fingerprint: bool,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import CRMTaskSuggestionService
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    thread_id = f"thread-task-payload-nonblocking-sibling-{uuid4()}"
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id=thread_id,
            message_id=f"task-payload-nonblocking-{index}-{uuid4()}",
        )
        for index in range(2)
    ]
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(
        service,
        receipts[0],
        await _extract_model_actions(
            receipts[0],
            _model_action(due_at="2026-08-22T19:00:00Z"),
        ),
    )
    second = await _claim_and_reconcile(
        service,
        receipts[1],
        await _extract_model_actions(
            receipts[1],
            _model_action(due_at="2026-08-24T19:00:00Z"),
        ),
    )
    async with sessions() as session:
        approved = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        sibling = await session.get(CRMTaskSuggestion, second.suggestion_ids[0])
        approved.state = "approved"
        sibling.state = sibling_state
        if same_fingerprint:
            sibling.obligation_fingerprint = approved.obligation_fingerprint
        await session.commit()
        payload = await CRMTaskSuggestionService.task_payload(
            session=session,
            suggestion=approved,
            expected_version=approved.version,
            expected_payload_hash=approved.payload_hash,
        )

    assert payload.title == approved.title


async def test_task_payload_rejects_stored_payload_hash_corruption(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import (
        CRMTaskSuggestionAuthorityError,
        CRMTaskSuggestionService,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-payload-hash-corruption",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, _obligation()),
    )
    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        suggestion.state = "approved"
        await session.commit()
        expected_version = suggestion.version
        expected_hash = suggestion.payload_hash
        await session.execute(
            sa.text(
                "UPDATE crm_task_suggestions SET title = :title WHERE id = :id"
            ),
            {"title": "Tampered task title", "id": suggestion.id},
        )
        await session.commit()

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        with pytest.raises(
            CRMTaskSuggestionAuthorityError,
            match="suggestion_payload_corrupt",
        ):
            await CRMTaskSuggestionService.task_payload(
                session=session,
                suggestion=suggestion,
                expected_version=expected_version,
                expected_payload_hash=expected_hash,
            )


@pytest.mark.parametrize(
    ("state", "clarification_state", "blockers", "eligible"),
    [
        ("pending_review", "not_required", [], True),
        ("pending_review", "pending", [], False),
        ("pending_review", "answered", [], False),
        ("pending_review", "timed_out", [], False),
        ("pending_review", "manual_review_required", [], False),
        ("pending_review", "not_required", ["unsupported_owner"], False),
        ("needs_clarification", "pending", ["missing_required_field"], False),
        ("possible_duplicate", "not_required", [], False),
        ("dismissed", "not_required", [], False),
        ("approved", "not_required", [], False),
        ("applied", "not_required", [], False),
        ("failed", "not_required", [], False),
    ],
)
async def test_approval_eligibility_requires_one_clean_review_lifecycle_shape(
    suggestion_runtime,
    state: str,
    clarification_state: str,
    blockers: list[str],
    eligible: bool,
) -> None:
    from models.command import CRMTask
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import CRMTaskSuggestionService
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=f"thread-approval-shape-{uuid4()}",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, _obligation()),
    )
    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        suggestion.clarification_state = clarification_state
        suggestion.blocker_codes = blockers
        suggestion.task_details_clarification_pending = (
            "missing_required_field" in blockers
        )
        if state == "applied":
            task = CRMTask(
                title=suggestion.title,
                description=suggestion.description,
                status="open",
                priority=suggestion.priority,
                due_at=suggestion.due_at,
                contact_id=suggestion.contact_id,
            )
            session.add(task)
            await session.flush()
        suggestion.state = state
        if state == "applied":
            suggestion.applied_task_id = task.id
            suggestion.application_idempotency_key = uuid4()
        await session.flush()
        assert CRMTaskSuggestionService.approval_eligible(suggestion) is eligible


async def test_reconciliation_never_creates_confirmed_crm_tasks_or_side_effects(
    suggestion_runtime,
) -> None:
    from models.command import CRMActivity, CRMTask, CRMTaskLink
    from models.crm_task_lifecycle import (
        CRMRecordLifecycleEvent,
        CRMTaskCreationRequest,
        CRMTaskSource,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    eligible = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-zero-confirmed-eligible",
    )
    blocked = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-zero-confirmed-blocked",
    )
    await _claim_and_reconcile(
        service,
        eligible,
        _extraction(eligible, _obligation()),
    )
    await _claim_and_reconcile(
        service,
        blocked,
        _extraction(
            blocked,
            _obligation(requested_owner="Another Agent"),
        ),
    )

    async with sessions() as session:
        counts = {
            model.__tablename__: await session.scalar(
                sa.select(sa.func.count(model.id))
            )
            for model in (
                CRMTask,
                CRMTaskCreationRequest,
                CRMTaskSource,
                CRMRecordLifecycleEvent,
                CRMActivity,
                CRMTaskLink,
            )
        }
    assert counts == {
        "crm_tasks": 0,
        "crm_task_creation_requests": 0,
        "crm_task_sources": 0,
        "crm_record_lifecycle_events": 0,
        "crm_activities": 0,
        "crm_task_links": 0,
    }


async def test_contact_hint_binds_only_one_unique_backend_resolved_contact(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )
    from services.sydney_clarification_service import contact_resolution_hash

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        alice = CRMContact(
            first_name="Alice",
            last_name="Client",
            email="Alice@Example.Test",
            phone=None,
            stage="lead",
        )
        session.add(alice)
        await session.commit()
        await session.refresh(alice)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-unique-contact",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, _obligation(contact_hint="alice@example.test")),
    )

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
    assert suggestion.contact_id == alice.id
    assert suggestion.contact_resolution_state == "inferred_unique"
    assert suggestion.contact_resolution_hash == contact_resolution_hash(
        contact_id=alice.id,
        email="alice@example.test",
    )
    assert "ambiguous_contact" not in suggestion.blocker_codes


async def test_unique_contact_identity_merges_received_and_sent_despite_participant_difference(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        alice = CRMContact(
            first_name="Alice",
            last_name="Client",
            email="alice@example.test",
            phone=None,
            stage="lead",
        )
        session.add(alice)
        await session.commit()
        await session.refresh(alice)
    received = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-unique-contact-cross-direction",
        message_id="unique-contact-received",
        direction="received",
        sender_hmac="a" * 64,
        recipient_hmacs=("c" * 64,),
    )
    sent = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-unique-contact-cross-direction",
        message_id="unique-contact-sent",
        direction="sent",
        sender_hmac="c" * 64,
        recipient_hmacs=("d" * 64,),
    )
    incoming = await _extract_model_actions(
        received,
        _model_action(contact_hint="alice@example.test"),
    )
    outgoing = await _extract_model_actions(
        sent,
        _model_action(
            kind="outgoing_commitment",
            contact_hint="alice@example.test",
        ),
    )
    assert incoming.obligations[0].action_key == outgoing.obligations[0].action_key
    assert incoming.obligations[0].participant_reconciliation_action_key != (
        outgoing.obligations[0].participant_reconciliation_action_key
    )

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(service, received, incoming)
    second = await _claim_and_reconcile(service, sent, outgoing)

    assert first.suggestion_ids == second.suggestion_ids
    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        obligations = list(
            (await session.scalars(sa.select(GmailExtractedObligation))).all()
        )
        source_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestionSource.id))
        )
    assert suggestion.contact_id == alice.id
    assert suggestion.source_action_key == incoming.obligations[0].action_key
    assert source_count == 2
    assert {row.action_key for row in obligations} == {
        incoming.obligations[0].action_key
    }
    assert {row.contact_hint for row in obligations} == {"alice@example.test"}


@pytest.mark.parametrize(
    ("authority_mode", "contact_hint"),
    [
        ("no_match", "nobody@example.test"),
        ("fuzzy", "Alice Client"),
        ("malformed", "alice@@example.test"),
        ("duplicate", "alice@example.test"),
        ("stale_index", "alice@example.test"),
    ],
)
async def test_rejected_contact_hint_uses_receipt_participant_identity(
    suggestion_runtime,
    authority_mode: str,
    contact_hint: str,
) -> None:
    from models.command import CRMContact
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        if authority_mode == "duplicate":
            session.add_all(
                [
                    CRMContact(
                        first_name="Alice",
                        last_name="One",
                        email="alice@example.test",
                        phone=None,
                        stage="lead",
                    ),
                    CRMContact(
                        first_name="Alice",
                        last_name="Two",
                        email="ALICE@example.test",
                        phone=None,
                        stage="lead",
                    ),
                ]
            )
            await session.commit()
        elif authority_mode == "stale_index":
            drifted = CRMContact(
                first_name="Mallory",
                last_name="Client",
                email="mallory@example.test",
                phone=None,
                stage="lead",
            )
            session.add(drifted)
            await session.commit()
            await session.execute(
                sa.text(
                    "UPDATE crm_contacts SET normalized_email = "
                    "'alice@example.test' WHERE id = :contact_id"
                ),
                {"contact_id": drifted.id},
            )
            await session.commit()

    thread_id = f"thread-rejected-contact-identity-{authority_mode}"
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id=thread_id,
            message_id=f"rejected-contact-{authority_mode}-{index}",
            sender_hmac=sender_hmac,
            recipient_hmacs=("c" * 64,),
        )
        for index, sender_hmac in enumerate(("a" * 64, "d" * 64))
    ]
    extractions = [
        await _extract_model_actions(
            receipt,
            _model_action(contact_hint=contact_hint),
        )
        for receipt in receipts
    ]
    assert extractions[0].obligations[0].action_key == (
        extractions[1].obligations[0].action_key
    )

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    results = [
        await _claim_and_reconcile(service, receipt, extraction)
        for receipt, extraction in zip(receipts, extractions, strict=True)
    ]

    assert results[0].suggestion_ids != results[1].suggestion_ids
    async with sessions() as session:
        suggestions = list(
            (await session.scalars(sa.select(CRMTaskSuggestion))).all()
        )
        obligations = list(
            (await session.scalars(sa.select(GmailExtractedObligation))).all()
        )
    assert len(suggestions) == len(obligations) == 2
    assert all(row.contact_id is None for row in suggestions)
    assert all("ambiguous_contact" in row.blocker_codes for row in suggestions)
    assert all(row.contact_hint is None for row in obligations)
    assert len({row.action_key for row in obligations}) == 2
    assert len({row.obligation_fingerprint for row in obligations}) == 2
    by_receipt = {row.receipt_id: row for row in obligations}
    for receipt, extraction in zip(receipts, extractions, strict=True):
        stored = by_receipt[receipt.id]
        assert stored.action_key == (
            extraction.obligations[0].participant_reconciliation_action_key
        )
        assert stored.obligation_fingerprint == (
            extraction.obligations[0].participant_obligation_fingerprint
        )


async def test_rejected_contact_suppression_is_isolated_by_participant(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    thread_id = "thread-rejected-contact-suppression"
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id=thread_id,
            message_id=f"rejected-contact-suppression-{index}",
            sender_hmac=sender_hmac,
        )
        for index, sender_hmac in enumerate(("a" * 64, "d" * 64))
    ]
    extractions = [
        await _extract_model_actions(
            receipt,
            _model_action(contact_hint="Alice Client"),
        )
        for receipt in receipts
    ]
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(service, receipts[0], extractions[0])
    async with sessions() as session:
        dismissed = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        dismissal_identity = (
            dismissed.source_action_key,
            dismissed.obligation_fingerprint,
            dismissed.primary_instance_digest,
        )
        dismissed.state = "dismissed"
        await session.commit()
    await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, thread_id),
        action_key=dismissal_identity[0],
        fingerprint=dismissal_identity[1],
        instance_digest=dismissal_identity[2],
    )

    second = await _claim_and_reconcile(service, receipts[1], extractions[1])

    assert second.suppressed_action_keys == ()
    assert len(second.suggestion_ids) == 1
    assert second.suggestion_ids != first.suggestion_ids


async def test_two_rejected_hints_regroup_into_one_manual_same_receipt_collision(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-rejected-contact-envelope-collision",
        message_id="rejected-contact-envelope-collision",
        sender_hmac="a" * 64,
    )
    actions = (
        _model_action(
            title="Call about 123 Main",
            description="Discuss showing feedback for 123 Main.",
            contact_hint="Alice Client",
        ),
        _model_action(
            title="Call about 456 Oak",
            description="Discuss showing feedback for 456 Oak.",
            contact_hint="Unknown Client",
        ),
    )
    extraction = await _extract_model_actions(receipt, *actions)
    assert len({row.action_key for row in extraction.obligations}) == 2

    result = await _claim_and_reconcile(
        GmailObligationReconciliationService(sessionmaker=sessions),
        receipt,
        extraction,
    )

    assert len(set(result.suggestion_ids)) == 1
    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        obligations = list(
            (await session.scalars(sa.select(GmailExtractedObligation))).all()
        )
        sources = list(
            (await session.scalars(sa.select(CRMTaskSuggestionSource))).all()
        )
    assert len(obligations) == len(sources) == 2
    assert len({row.action_key for row in obligations}) == 2
    assert len({row.obligation_fingerprint for row in obligations}) == 1
    assert all(row.contact_hint is None for row in obligations)
    assert suggestion.state == "needs_clarification"
    assert set(suggestion.blocker_codes) == {
        "ambiguous_contact",
        "multiple_actions",
    }
    assert all(
        json.loads(row.evaluator_result_json)["identity_collision"] is True
        for row in obligations
    )


async def test_exact_duplicate_after_rejected_contact_regroup_fails_atomically(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
        GmailExtractionAttempt,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationError,
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-rejected-contact-exact-duplicate",
        message_id="rejected-contact-exact-duplicate",
        sender_hmac="a" * 64,
    )
    extraction = await _extract_model_actions(
        receipt,
        _model_action(contact_hint="Alice Client"),
        _model_action(contact_hint="Unknown Client"),
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )

    with pytest.raises(
        GmailObligationReconciliationError,
        match="^gmail_extraction_effective_identity_invalid$",
    ):
        await service.reconcile_attempt(claim=claim, extraction=extraction)

    async with sessions() as session:
        counts = (
            await session.scalar(sa.select(sa.func.count(GmailExtractedObligation.id))),
            await session.scalar(sa.select(sa.func.count(CRMTaskSuggestion.id))),
            await session.scalar(sa.select(sa.func.count(CRMTaskSuggestionSource.id))),
        )
        attempt = await session.get(GmailExtractionAttempt, claim.id)
    assert counts == (0, 0, 0)
    assert attempt.state == "running"


async def test_duplicate_contact_hint_never_selects_the_first_match(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        session.add_all(
            [
                CRMContact(
                    first_name="Alice",
                    last_name="One",
                    email="alice@example.test",
                    phone=None,
                    stage="lead",
                ),
                CRMContact(
                    first_name="Alice",
                    last_name="Two",
                    email="ALICE@example.test",
                    phone=None,
                    stage="lead",
                ),
            ]
        )
        await session.commit()
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-duplicate-contact",
    )
    contact_queries: list[tuple[str, object]] = []

    def capture_contact_query(
        _conn,
        _cursor,
        statement,
        parameters,
        _context,
        _many,
    ) -> None:
        if "crm_contacts" in statement.casefold():
            contact_queries.append((statement.casefold(), parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", capture_contact_query)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    try:
        result = await _claim_and_reconcile(
            service,
            receipt,
            _extraction(receipt, _obligation(contact_hint="alice@example.test")),
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_contact_query)

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
    assert suggestion.contact_id is None
    assert suggestion.state == "needs_clarification"
    assert suggestion.blocker_codes == ["ambiguous_contact"]
    assert suggestion.contact_resolution_state == "unresolved"
    assert suggestion.contact_resolution_hash is None
    assert len(contact_queries) == 1
    statement, parameters = contact_queries[0]
    assert " limit " in " ".join(statement.split())
    flattened_parameters = (
        tuple(parameters)
        if isinstance(parameters, (list, tuple))
        else tuple(parameters.values())
    )
    assert 2 in flattened_parameters

    from models.gmail_task_intake import GmailExtractedObligation

    async with sessions() as session:
        stored_hint = await session.scalar(
            sa.select(GmailExtractedObligation.contact_hint)
        )
    assert stored_hint is None


async def test_contact_authority_drift_changes_immutable_material_hash(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        session.add(
            CRMContact(
                first_name="Alice",
                last_name="One",
                email="alice@example.test",
                phone=None,
                stage="lead",
            )
        )
        await session.commit()
    receipts = [
        await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id="thread-contact-material-drift",
            message_id=f"contact-material-drift-{index}",
        )
        for index in range(2)
    ]
    action = _model_action(contact_hint="alice@example.test")
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(
        service,
        receipts[0],
        await _extract_model_actions(receipts[0], action),
    )
    async with sessions() as session:
        session.add(
            CRMContact(
                first_name="Alice",
                last_name="Two",
                email="ALICE@example.test",
                phone=None,
                stage="lead",
            )
        )
        await session.commit()

    second = await _claim_and_reconcile(
        service,
        receipts[1],
        await _extract_model_actions(receipts[1], action),
    )

    async with sessions() as session:
        original = await session.get(
            CRMTaskSuggestion,
            first.suggestion_ids[0],
        )
        changed = await session.get(
            CRMTaskSuggestion,
            second.suggestion_ids[0],
        )
        stored = list(
            (
                await session.scalars(
                    sa.select(GmailExtractedObligation).order_by(
                        GmailExtractedObligation.created_at,
                        GmailExtractedObligation.id,
                    )
                )
            ).all()
        )
    assert second.suggestion_ids != first.suggestion_ids
    assert original.contact_id is not None
    assert "ambiguous_contact" not in original.blocker_codes
    assert changed.contact_id is None
    assert "ambiguous_contact" in changed.blocker_codes
    assert changed.duplicate_of_suggestion_id == original.id
    assert len(stored) == 2
    assert len({row.reconciliation_material_hash for row in stored}) == 2
    assert all(
        len(row.reconciliation_material_hash) == 64
        and row.reconciliation_material_hash.isascii()
        and row.reconciliation_material_hash.islower()
        for row in stored
    )


@pytest.mark.parametrize(
    "contact_hint",
    ["nobody@example.test", "Alice Client"],
)
async def test_zero_or_fuzzy_contact_hint_stays_ambiguous_without_plaintext_persistence(
    suggestion_runtime,
    contact_hint: str,
) -> None:
    from models.command import CRMContact
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=f"thread-unmatched-contact-{uuid4()}",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, _obligation(contact_hint=contact_hint)),
    )

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        stored_hint = await session.scalar(
            sa.select(GmailExtractedObligation.contact_hint)
        )
        contact_count = await session.scalar(sa.select(sa.func.count(CRMContact.id)))
    assert suggestion.contact_id is None
    assert suggestion.state == "needs_clarification"
    assert suggestion.blocker_codes == ["ambiguous_contact"]
    assert stored_hint is None
    assert contact_count == 0


async def test_contact_resolution_rechecks_actual_email_not_stale_normalized_email(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        drifted = CRMContact(
            first_name="Mallory",
            last_name="Client",
            email="mallory@example.test",
            phone=None,
            stage="lead",
        )
        session.add(drifted)
        await session.commit()
        await session.execute(
            sa.text(
                "UPDATE crm_contacts SET normalized_email = :wrong "
                "WHERE id = :contact_id"
            ),
            {"wrong": "alice@example.test", "contact_id": drifted.id},
        )
        await session.commit()
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-drifted-contact-index",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, _obligation(contact_hint="alice@example.test")),
    )

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        stored_hint = await session.scalar(
            sa.select(GmailExtractedObligation.contact_hint)
        )
    assert suggestion.contact_id is None
    assert suggestion.blocker_codes == ["ambiguous_contact"]
    assert stored_hint is None


async def test_task_payload_revalidates_unique_contact_at_application_time(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import (
        CRMTaskSuggestionAuthorityError,
        CRMTaskSuggestionService,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        session.add(
            CRMContact(
                first_name="Alice",
                last_name="One",
                email="alice@example.test",
                phone=None,
                stage="lead",
            )
        )
        await session.commit()
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-contact-drift-at-apply",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, _obligation(contact_hint="alice@example.test")),
    )
    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        assert suggestion.contact_id is not None
        suggestion.state = "approved"
        await session.commit()
        expected_version = suggestion.version
        expected_hash = suggestion.payload_hash

    async with sessions() as session:
        session.add(
            CRMContact(
                first_name="Alice",
                last_name="Two",
                email="ALICE@example.test",
                phone=None,
                stage="lead",
            )
        )
        await session.commit()

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        with pytest.raises(
            CRMTaskSuggestionAuthorityError,
            match="contact_authority_changed",
        ):
            await CRMTaskSuggestionService.task_payload(
                session=session,
                suggestion=suggestion,
                expected_version=expected_version,
                expected_payload_hash=expected_hash,
            )


async def test_task_payload_accepts_hash_bound_clarified_unique_contact(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import (
        CRMTaskSuggestionService,
        canonical_task_payload_hash,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-clarified-contact-authority",
    )
    reconciliation = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        reconciliation,
        receipt,
        _extraction(
            receipt,
            _obligation(contact_hint="alice@example.test"),
        ),
    )
    async with sessions() as session:
        contact = CRMContact(
            first_name="Alice",
            last_name="Client",
            email="alice@example.test",
            phone=None,
            stage="lead",
        )
        session.add(contact)
        await session.flush()
        suggestion = await session.get(
            CRMTaskSuggestion, result.suggestion_ids[0]
        )
        suggestion.contact_id = contact.id
        suggestion.contact_resolution_state = "clarified_unique"
        suggestion.contact_resolution_hash = hashlib.sha256(
            b"sws:crm-contact-resolution:v1\0"
            + str(contact.id).encode("ascii")
            + b"\0alice@example.test"
        ).hexdigest()
        suggestion.blocker_codes = []
        suggestion.state = "approved"
        suggestion.clarification_state = "not_required"
        suggestion.version += 1
        suggestion.payload_hash = canonical_task_payload_hash(
            title=suggestion.title,
            description=suggestion.description,
            priority=suggestion.priority,
            due_at=suggestion.due_at,
            contact_id=suggestion.contact_id,
            status=suggestion.task_status,
        )
        await session.commit()
        expected_version = suggestion.version
        expected_hash = suggestion.payload_hash

    async with sessions() as session:
        suggestion = await session.get(
            CRMTaskSuggestion, result.suggestion_ids[0]
        )
        payload = await CRMTaskSuggestionService.task_payload(
            session=session,
            suggestion=suggestion,
            expected_version=expected_version,
            expected_payload_hash=expected_hash,
        )
    assert payload.contact_id == contact.id


async def test_conflicting_unique_contacts_across_sources_never_last_write_wins(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        session.add_all(
            [
                CRMContact(
                    first_name="Alice",
                    last_name="Client",
                    email="alice@example.test",
                    phone=None,
                    stage="lead",
                ),
                CRMContact(
                    first_name="Bob",
                    last_name="Client",
                    email="bob@example.test",
                    phone=None,
                    stage="lead",
                ),
            ]
        )
        await session.commit()
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    alice_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-conflicting-contact",
        message_id="contact-alice",
    )
    first = await _claim_and_reconcile(
        service,
        alice_receipt,
        _extraction(alice_receipt, _obligation(contact_hint="alice@example.test")),
    )
    bob_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-conflicting-contact",
        message_id="contact-bob",
        direction="sent",
    )
    await _claim_and_reconcile(
        service,
        bob_receipt,
        _extraction(
            bob_receipt,
            _obligation(kind="outgoing_commitment", contact_hint="bob@example.test"),
        ),
    )

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
    assert suggestion.contact_id is None
    assert suggestion.state == "needs_clarification"
    assert suggestion.blocker_codes == ["ambiguous_contact"]


async def test_task_payload_rejects_selected_contact_actual_email_drift(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import (
        CRMTaskSuggestionAuthorityError,
        CRMTaskSuggestionService,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        contact = CRMContact(
            first_name="Alice",
            last_name="Client",
            email="alice@example.test",
            phone=None,
            stage="lead",
        )
        session.add(contact)
        await session.commit()
        await session.refresh(contact)
        contact_id = contact.id
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-contact-email-drift",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    result = await _claim_and_reconcile(
        service,
        receipt,
        _extraction(receipt, _obligation(contact_hint="alice@example.test")),
    )
    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        assert suggestion.contact_id == contact_id
        suggestion.state = "approved"
        await session.commit()
        expected_version = suggestion.version
        expected_hash = suggestion.payload_hash
        await session.execute(
            sa.text("UPDATE crm_contacts SET email = :email WHERE id = :contact_id"),
            {"email": "mallory@example.test", "contact_id": contact_id},
        )
        await session.commit()

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, result.suggestion_ids[0])
        with pytest.raises(
            CRMTaskSuggestionAuthorityError,
            match="contact_authority_changed",
        ):
            await CRMTaskSuggestionService.task_payload(
                session=session,
                suggestion=suggestion,
                expected_version=expected_version,
                expected_payload_hash=expected_hash,
            )


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("account_id", UUID("00000000-0000-4000-8000-000000009999")),
        ("message_id", "different-message"),
        ("thread_id", "different-thread"),
        ("direction", "sent"),
        ("body_hash", "f" * 64),
        ("subject_evidence_hash", "e" * 64),
        ("participant_evidence_hash", "d" * 64),
        (
            "reference_message_at",
            datetime(2026, 8, 20, 14, 0, tzinfo=UTC),
        ),
        ("schema_version", "gmail-task-v2"),
    ],
)
async def test_reconciliation_rejects_mismatched_body_free_source_identity_atomically(
    suggestion_runtime,
    field: str,
    wrong_value: object,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
        GmailExtractionAttempt,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationError,
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-identity",
    )
    extraction = _extraction(receipt, _obligation())
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )
    extraction = replace(extraction, **{field: wrong_value})

    with pytest.raises(GmailObligationReconciliationError) as raised:
        await service.reconcile_attempt(claim=claim, extraction=extraction)
    assert str(raised.value) == "gmail_extraction_source_mismatch"
    assert raised.value.__cause__ is None
    async with sessions() as session:
        attempt = await session.get(GmailExtractionAttempt, claim.id)
        counts = tuple(
            [
                await session.scalar(sa.select(sa.func.count(model.id)))
                for model in (
                    GmailExtractedObligation,
                    CRMTaskSuggestion,
                    CRMTaskSuggestionSource,
                )
            ]
        )
    assert attempt.state == "running"
    assert counts == (0, 0, 0)


async def test_reconciliation_recomputes_instance_digest_before_any_write(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
        GmailExtractionAttempt,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationError,
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-forged-instance-digest",
    )
    forged = _obligation(identity_instance_digest="f" * 64)
    extraction = _extraction(receipt, forged)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )

    with pytest.raises(
        GmailObligationReconciliationError,
        match="gmail_obligation_instance_digest_invalid",
    ) as raised:
        await service.reconcile_attempt(claim=claim, extraction=extraction)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None

    async with sessions() as session:
        attempt = await session.get(GmailExtractionAttempt, claim.id)
        counts = tuple(
            [
                await session.scalar(sa.select(sa.func.count(model.id)))
                for model in (
                    GmailExtractedObligation,
                    CRMTaskSuggestion,
                    CRMTaskSuggestionSource,
                )
            ]
        )
    assert attempt.state == "running"
    assert counts == (0, 0, 0)


async def test_foreign_claim_and_nonrunning_claim_cannot_write_partial_evidence(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationError,
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-claim-first",
    )
    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-claim-second",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first_claim = await service.claim_attempt(
        receipt_id=first_receipt.id,
        schema_version="gmail-task-v1",
    )
    with pytest.raises(GmailObligationReconciliationError, match="gmail_extraction_source_mismatch"):
        await service.reconcile_attempt(
            claim=first_claim,
            extraction=_extraction(second_receipt, _obligation()),
        )
    await service.fail_attempt(
        claim=first_claim,
        category="invalid_model_output",
    )
    with pytest.raises(GmailObligationReconciliationError, match="gmail_extraction_attempt_state_invalid"):
        await service.reconcile_attempt(
            claim=first_claim,
            extraction=_extraction(first_receipt, _obligation()),
        )

    async with sessions() as session:
        counts = tuple(
            [
                await session.scalar(sa.select(sa.func.count(model.id)))
                for model in (
                    GmailExtractedObligation,
                    CRMTaskSuggestion,
                    CRMTaskSuggestionSource,
                )
            ]
        )
    assert counts == (0, 0, 0)


async def test_reconcile_replay_is_idempotent_for_attempt_obligation_and_source(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-replay",
    )
    extraction = _extraction(receipt, _obligation())
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )
    first = await service.reconcile_attempt(claim=claim, extraction=extraction)
    second = await service.reconcile_attempt(claim=claim, extraction=extraction)

    assert second.replayed is True
    assert second.suggestion_ids == first.suggestion_ids
    async with sessions() as session:
        counts = tuple(
            [
                await session.scalar(sa.select(sa.func.count(model.id)))
                for model in (
                    CRMTaskSuggestion,
                    CRMTaskSuggestionSource,
                    GmailExtractedObligation,
                )
            ]
        )
    assert counts == (1, 1, 1)


async def test_linked_replay_remains_linked_after_later_exact_suppression(
    suggestion_runtime,
) -> None:
    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-linked-replay-after-dismissal",
    )
    obligation = _obligation()
    extraction = _extraction(receipt, obligation)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first = await _claim_and_reconcile(service, receipt, extraction)
    await _seed_suppression(
        sessions,
        scope=gmail_source_scope_key(account.id, receipt.gmail_thread_id),
        action_key=obligation.action_key,
        fingerprint=obligation.obligation_fingerprint,
        instance_digest=obligation.identity_instance_digest,
    )

    replay = await _claim_and_reconcile(service, receipt, extraction)

    assert replay.replayed is True
    assert replay.suggestion_ids == first.suggestion_ids
    assert replay.suppressed_action_keys == ()


async def test_replay_fails_closed_if_one_obligation_has_multiple_sources() -> None:
    from types import SimpleNamespace

    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationError,
        GmailObligationReconciliationService,
    )

    obligation_id = uuid4()

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _CorruptReplaySession:
        async def scalars(self, _statement):
            return _Rows(
                [
                    SimpleNamespace(
                        id=obligation_id,
                        action_key="action-v1:test",
                        reconciled_suggestion_id=uuid4(),
                        reconciled_suppression_id=None,
                    )
                ]
            )

        async def execute(self, _statement):
            return _Rows(
                [
                    SimpleNamespace(
                        obligation_id=obligation_id,
                        suggestion_id=uuid4(),
                    ),
                    SimpleNamespace(
                        obligation_id=obligation_id,
                        suggestion_id=uuid4(),
                    ),
                ]
            )

    with pytest.raises(
        GmailObligationReconciliationError,
        match="gmail_suggestion_source_multiplicity",
    ):
        await GmailObligationReconciliationService._replay_result(
            session=_CorruptReplaySession(),
            attempt=SimpleNamespace(id=uuid4()),
        )


async def test_replay_rejects_suggestion_disposition_without_exact_source() -> None:
    from types import SimpleNamespace

    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationError,
        GmailObligationReconciliationService,
    )

    obligation_id = uuid4()
    suggestion_id = uuid4()

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _MissingSourceSession:
        async def scalars(self, _statement):
            return _Rows(
                [
                    SimpleNamespace(
                        id=obligation_id,
                        action_key="action-v1:test",
                        reconciled_suggestion_id=suggestion_id,
                        reconciled_suppression_id=None,
                    )
                ]
            )

        async def execute(self, _statement):
            return _Rows([])

    with pytest.raises(
        GmailObligationReconciliationError,
        match="gmail_obligation_disposition_invalid",
    ):
        await GmailObligationReconciliationService._replay_result(
            session=_MissingSourceSession(),
            attempt=SimpleNamespace(id=uuid4()),
        )


async def test_replay_rejects_source_crosswired_to_a_different_suggestion() -> None:
    from types import SimpleNamespace

    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationError,
        GmailObligationReconciliationService,
    )

    obligation_id = uuid4()
    disposition_suggestion_id = uuid4()
    source_suggestion_id = uuid4()

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _CrosswiredSourceSession:
        async def scalars(self, _statement):
            return _Rows(
                [
                    SimpleNamespace(
                        id=obligation_id,
                        action_key="action-v1:test",
                        reconciled_suggestion_id=disposition_suggestion_id,
                        reconciled_suppression_id=None,
                    )
                ]
            )

        async def execute(self, _statement):
            return _Rows(
                [
                    SimpleNamespace(
                        obligation_id=obligation_id,
                        suggestion_id=source_suggestion_id,
                    )
                ]
            )

    with pytest.raises(
        GmailObligationReconciliationError,
        match="gmail_obligation_disposition_invalid",
    ):
        await GmailObligationReconciliationService._replay_result(
            session=_CrosswiredSourceSession(),
            attempt=SimpleNamespace(id=uuid4()),
        )


@pytest.mark.parametrize(
    "mismatch",
    ["scope", "action_key", "fingerprint", "instance_digest"],
)
async def test_replay_rejects_crosswired_suppression_identity(
    mismatch: str,
) -> None:
    from types import SimpleNamespace

    from services.crm_task_suggestion_service import gmail_source_scope_key
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationError,
        GmailObligationReconciliationService,
    )

    account_id = uuid4()
    receipt_id = uuid4()
    suppression_id = uuid4()
    obligation_id = uuid4()
    expected_scope = gmail_source_scope_key(account_id, "thread-replay-suppression")
    expected = {
        "source_scope_key": expected_scope,
        "source_action_key": "action-v1:test",
        "obligation_fingerprint": "a" * 64,
        "identity_instance_digest": "b" * 64,
    }
    wrong_values = {
        "scope": "gmail:wrong:scope",
        "action_key": "action-v1:wrong",
        "fingerprint": "c" * 64,
        "instance_digest": "d" * 64,
    }
    suppression_values = dict(expected)
    field = {
        "scope": "source_scope_key",
        "action_key": "source_action_key",
        "fingerprint": "obligation_fingerprint",
        "instance_digest": "identity_instance_digest",
    }[mismatch]
    suppression_values[field] = wrong_values[mismatch]

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _CrosswiredSuppressionSession:
        def __init__(self):
            self.scalar_calls = 0

        async def scalars(self, _statement):
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                return _Rows(
                    [
                        SimpleNamespace(
                            id=obligation_id,
                            action_key=expected["source_action_key"],
                            obligation_fingerprint=expected[
                                "obligation_fingerprint"
                            ],
                            identity_instance_digest=expected[
                                "identity_instance_digest"
                            ],
                            evaluator_result_json="{}",
                            reconciled_suggestion_id=None,
                            reconciled_suppression_id=suppression_id,
                        )
                    ]
                )
            return _Rows(
                [
                    SimpleNamespace(
                        id=suppression_id,
                        source_type="gmail_message",
                        **suppression_values,
                    )
                ]
            )

        async def execute(self, _statement):
            return _Rows([])

        async def scalar(self, _statement):
            return SimpleNamespace(
                id=receipt_id,
                account_id=account_id,
                gmail_thread_id="thread-replay-suppression",
            )

    with pytest.raises(
        GmailObligationReconciliationError,
        match="gmail_obligation_disposition_invalid",
    ):
        await GmailObligationReconciliationService._replay_result(
            session=_CrosswiredSuppressionSession(),
            attempt=SimpleNamespace(id=uuid4(), receipt_id=receipt_id),
        )


async def test_succeeded_replay_with_changed_payload_never_rewrites_evidence(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
        GmailExtractedObligation,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-replay-payload-mismatch",
    )
    original = _obligation()
    extraction = _extraction(receipt, original)
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )
    first = await service.reconcile_attempt(claim=claim, extraction=extraction)
    async with sessions() as session:
        obligation = await session.scalar(sa.select(GmailExtractedObligation))
        suggestion = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        source = await session.scalar(sa.select(CRMTaskSuggestionSource))
        snapshot = (
            obligation.id,
            obligation.title,
            obligation.description,
            obligation.obligation_fingerprint,
            suggestion.id,
            suggestion.title,
            suggestion.payload_hash,
            suggestion.version,
            source.id,
            source.suggestion_id,
            source.obligation_id,
        )

    changed = replace(
        extraction,
        obligations=(
            replace(
                original,
                title="Changed replay title",
                obligation_fingerprint="d" * 64,
                requested_owner="Pat Agent",
                contact_hint="other@example.test",
            ),
        ),
    )
    replay = await service.reconcile_attempt(claim=claim, extraction=changed)
    assert replay.replayed is True
    assert replay.suggestion_ids == first.suggestion_ids

    async with sessions() as session:
        obligation = await session.scalar(sa.select(GmailExtractedObligation))
        suggestion = await session.get(CRMTaskSuggestion, first.suggestion_ids[0])
        source = await session.scalar(sa.select(CRMTaskSuggestionSource))
        assert (
            obligation.id,
            obligation.title,
            obligation.description,
            obligation.obligation_fingerprint,
            suggestion.id,
            suggestion.title,
            suggestion.payload_hash,
            suggestion.version,
            source.id,
            source.suggestion_id,
            source.obligation_id,
        ) == snapshot


async def test_thread_lock_precedes_all_protected_reconciliation_work(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        session.add(
            CRMContact(
                first_name="Alice",
                last_name="Client",
                email="alice-lock-order@example.test",
                phone=None,
                stage="lead",
            )
        )
        await session.commit()
    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-sql-order",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    extraction = _extraction(
        receipt,
        _obligation(contact_hint="alice-lock-order@example.test"),
    )
    claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.casefold().split()))

    def capture_commit(_conn) -> None:
        statements.append("<commit>")

    def capture_rollback(_conn) -> None:
        statements.append("<rollback>")

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    event.listen(engine.sync_engine, "commit", capture_commit)
    event.listen(engine.sync_engine, "rollback", capture_rollback)
    try:
        await service.reconcile_attempt(claim=claim, extraction=extraction)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        event.remove(engine.sync_engine, "commit", capture_commit)
        event.remove(engine.sync_engine, "rollback", capture_rollback)

    lock_positions = [
        index
        for index, statement in enumerate(statements)
        if "pg_advisory_xact_lock" in statement
    ]
    protected_positions = [
        index
        for index, statement in enumerate(statements)
        if statement.startswith(("select", "insert", "update", "delete"))
        and any(
            table in statement
            for table in (
                "gmail_extracted_obligations",
                "crm_task_suggestion_suppressions",
                "crm_task_suggestions",
                "crm_task_suggestion_sources",
            )
        )
    ]
    assert lock_positions
    assert len(lock_positions) >= 2
    assert protected_positions
    lock_position = min(lock_positions)
    assert lock_position < min(protected_positions)
    transaction_boundaries = [
        index
        for index, statement in enumerate(statements)
        if statement in {"<commit>", "<rollback>"}
    ]
    assert not any(
        lock_position < boundary < max(protected_positions)
        for boundary in transaction_boundaries
    )
    suggestion_lock_positions = [
        index
        for index, statement in enumerate(statements)
        if "from crm_task_suggestions" in statement
        and "for update" in statement
    ]
    contact_lock_positions = [
        index
        for index, statement in enumerate(statements)
        if "from crm_contacts" in statement and "for update" in statement
    ]
    assert suggestion_lock_positions
    assert contact_lock_positions
    assert min(suggestion_lock_positions) < min(contact_lock_positions)
    assert max(lock_positions) < min(contact_lock_positions)


async def test_preserved_contact_authority_joins_identity_lock_protocol(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        session.add(
            CRMContact(
                first_name="Alice",
                last_name="Client",
                email="alice-preserved-lock@example.test",
                phone=None,
                stage="lead",
            )
        )
        await session.commit()
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-preserved-contact-lock",
        message_id="preserved-contact-lock-v1",
    )
    await _claim_and_reconcile(
        service,
        first_receipt,
        _extraction(
            first_receipt,
            _obligation(contact_hint="alice-preserved-lock@example.test"),
        ),
    )
    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=first_receipt.gmail_thread_id,
        message_id="preserved-contact-lock-v2",
    )
    extraction = _extraction(
        second_receipt,
        _obligation(contact_hint=None, priority="high"),
    )
    claim = await service.claim_attempt(
        receipt_id=second_receipt.id,
        schema_version=extraction.schema_version,
    )
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.casefold().split()))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        await service.reconcile_attempt(claim=claim, extraction=extraction)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    identity_lock_positions = [
        index
        for index, statement in enumerate(statements)
        if "pg_advisory_xact_lock" in statement
    ]
    contact_lookup_positions = [
        index
        for index, statement in enumerate(statements)
        if "from crm_contacts" in statement and "for update" in statement
    ]
    assert len(identity_lock_positions) >= 2
    assert contact_lookup_positions
    assert max(identity_lock_positions) < min(contact_lookup_positions)


async def test_two_connections_same_thread_create_one_suggestion_and_two_sources(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        CRMTaskSuggestion,
        CRMTaskSuggestionSource,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-race",
        message_id="race-one",
    )
    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-race",
        message_id="race-two",
        direction="sent",
    )
    first_lookup_complete = asyncio.Event()
    release_first_insert = asyncio.Event()

    async def pause_after_lookup() -> None:
        first_lookup_complete.set()
        await release_first_insert.wait()

    first = GmailObligationReconciliationService(
        sessionmaker=sessions,
        after_suggestion_lookup=pause_after_lookup,
    )
    second = GmailObligationReconciliationService(sessionmaker=sessions)
    first_claim, second_claim = await asyncio.gather(
        first.claim_attempt(
            receipt_id=first_receipt.id,
            schema_version="gmail-task-v1",
        ),
        second.claim_attempt(
            receipt_id=second_receipt.id,
            schema_version="gmail-task-v1",
        ),
    )

    first_task = asyncio.create_task(
        first.reconcile_attempt(
            claim=first_claim,
            extraction=_extraction(first_receipt, _obligation()),
        )
    )
    await asyncio.wait_for(first_lookup_complete.wait(), timeout=2)
    second_task = asyncio.create_task(
        second.reconcile_attempt(
            claim=second_claim,
            extraction=_extraction(
                second_receipt,
                _obligation(kind="outgoing_commitment"),
            ),
        )
    )
    await asyncio.sleep(0.05)
    assert not second_task.done()
    release_first_insert.set()
    await asyncio.gather(first_task, second_task)

    async with sessions() as session:
        suggestion_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestion.id))
        )
        source_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestionSource.id))
        )
    assert suggestion_count == 1
    assert source_count == 2


async def test_reconciliation_loads_one_bounded_candidate_batch_per_receipt(
    suggestion_runtime,
) -> None:
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    thread_id = "thread-bounded-candidate-batch"
    seeder = GmailObligationReconciliationService(sessionmaker=sessions)
    for index in range(8):
        receipt = await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id=thread_id,
            message_id=f"bounded-candidate-seed-{index}",
        )
        await _claim_and_reconcile(
            seeder,
            receipt,
            _extraction(
                receipt,
                _obligation(
                    action_key=f"action-v1:{index + 10:064x}",
                    obligation_fingerprint=f"{index + 30:064x}",
                    title=f"Seed bounded candidate {index}",
                ),
            ),
        )

    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=thread_id,
        message_id="bounded-candidate-final",
    )
    obligations = tuple(
        _obligation(
            action_key=f"action-v1:{index + 100:064x}",
            obligation_fingerprint=f"{index + 200:064x}",
            title=f"New bounded action {index}",
        )
        for index in range(3)
    )
    statements: list[str] = []
    lookup_calls = 0

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.casefold().split()))

    async def after_lookup() -> None:
        nonlocal lookup_calls
        lookup_calls += 1

    service = GmailObligationReconciliationService(
        sessionmaker=sessions,
        max_thread_candidates=64,
        after_suggestion_lookup=after_lookup,
    )
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        await _claim_and_reconcile(
            service,
            receipt,
            _extraction(receipt, *obligations),
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    candidate_queries = [
        statement
        for statement in statements
        if statement.startswith("select")
        and "from crm_task_suggestions" in statement
        and "for update" in statement
    ]
    fallback_queries = [
        statement
        for statement in statements
        if statement.startswith("select")
        and "gmail_extracted_obligations" in statement
        and "taxonomy_fallback" in statement
    ]
    assert lookup_calls == 1
    assert len(candidate_queries) == 1
    assert " limit " in candidate_queries[0]
    assert len(fallback_queries) == 1
    assert "exists" in fallback_queries[0]
    assert "unnest" in fallback_queries[0]
    assert "from unnest" in fallback_queries[0]
    assert "from (select unnest" not in fallback_queries[0]
    assert "from crm_task_suggestions" not in fallback_queries[0]
    assert "crm_task_suggestion_sources" not in fallback_queries[0]
    assert "evaluator_result_json" not in fallback_queries[0]
    assert "taxonomy_fallback" in fallback_queries[0]


async def test_instance_membership_is_driven_by_bounded_candidate_values(
    suggestion_runtime,
) -> None:
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    thread_id = "thread-bounded-instance-membership"
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    first_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=thread_id,
        message_id="bounded-instance-first",
    )
    await _claim_and_reconcile(
        service,
        first_receipt,
        _extraction(first_receipt, _obligation()),
    )
    second_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=thread_id,
        message_id="bounded-instance-second",
    )
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.casefold().split()))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        await _claim_and_reconcile(
            service,
            second_receipt,
            _extraction(second_receipt, _obligation()),
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    membership_queries = [
        statement
        for statement in statements
        if statement.startswith("select")
        and "gmail_extracted_obligations" in statement
        and "identity_instance_digest" in statement
        and "reconciliation_material_hash" not in statement
    ]
    assert len(membership_queries) == 1
    statement = membership_queries[0]
    assert "exists" in statement
    assert "from unnest" in statement
    assert "from (select unnest" not in statement
    assert "from crm_task_suggestions" not in statement


async def test_candidate_batch_overflow_terminalizes_attempt_without_retry_churn(
    suggestion_runtime,
) -> None:
    from models.gmail_task_intake import (
        GmailExtractedObligation,
        GmailExtractionAttempt,
    )
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
        GmailReconciliationCandidateLimitReached,
    )

    _engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    thread_id = "thread-candidate-overflow"
    seeder = GmailObligationReconciliationService(sessionmaker=sessions)
    for index in range(3):
        receipt = await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id=thread_id,
            message_id=f"candidate-overflow-seed-{index}",
        )
        await _claim_and_reconcile(
            seeder,
            receipt,
            _extraction(
                receipt,
                _obligation(
                    action_key=f"action-v1:{index + 300:064x}",
                    obligation_fingerprint=f"{index + 400:064x}",
                    title=f"Candidate overflow seed {index}",
                ),
            ),
        )

    receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id=thread_id,
        message_id="candidate-overflow-final",
    )
    extraction = _extraction(receipt, _obligation())
    service = GmailObligationReconciliationService(
        sessionmaker=sessions,
        max_thread_candidates=2,
    )
    claim = await service.claim_attempt(
        receipt_id=receipt.id,
        schema_version=extraction.schema_version,
    )
    with pytest.raises(
        GmailReconciliationCandidateLimitReached,
        match="gmail_suggestion_candidate_limit",
    ):
        await service.reconcile_attempt(claim=claim, extraction=extraction)

    async with sessions() as session:
        attempt = await session.get(GmailExtractionAttempt, claim.id)
        obligation_count = await session.scalar(
            sa.select(sa.func.count(GmailExtractedObligation.id)).where(
                GmailExtractedObligation.receipt_id == receipt.id
            )
        )
        attempt_count = await session.scalar(
            sa.select(sa.func.count(GmailExtractionAttempt.id)).where(
                GmailExtractionAttempt.receipt_id == receipt.id
            )
        )
    assert attempt.state == "failed"
    assert attempt.error_category == "suggestion_candidate_limit"
    assert attempt.error_message == "Gmail suggestion history requires manual review."
    assert obligation_count == 0
    assert attempt_count == 1

    with pytest.raises(
        GmailReconciliationCandidateLimitReached,
        match="gmail_suggestion_candidate_limit",
    ):
        await service.claim_attempt(
            receipt_id=receipt.id,
            schema_version=extraction.schema_version,
        )
    async with sessions() as session:
        assert await session.scalar(
            sa.select(sa.func.count(GmailExtractionAttempt.id)).where(
                GmailExtractionAttempt.receipt_id == receipt.id
            )
        ) == 1


async def test_task_payload_uses_two_bounded_obligation_contact_hint_probes(
    suggestion_runtime,
) -> None:
    from models.command import CRMContact
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import CRMTaskSuggestionService
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )

    engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    async with sessions() as session:
        contact = CRMContact(
            first_name="Alice",
            last_name="Client",
            email="alice-bounded@example.test",
            phone=None,
            stage="lead",
        )
        session.add(contact)
        await session.commit()

    service = GmailObligationReconciliationService(sessionmaker=sessions)
    suggestion_id = None
    thread_id = "thread-bounded-apply-contact-hints"
    for index in range(5):
        receipt = await _seed_receipt(
            sessions,
            account_id=account.id,
            thread_id=thread_id,
            message_id=f"bounded-contact-source-{index}",
        )
        result = await _claim_and_reconcile(
            service,
            receipt,
            _extraction(
                receipt,
                _obligation(contact_hint="alice-bounded@example.test"),
            ),
        )
        suggestion_id = result.suggestion_ids[0]

    async with sessions() as session:
        suggestion = await session.get(CRMTaskSuggestion, suggestion_id)
        suggestion.state = "approved"
        await session.commit()
        expected_version = suggestion.version
        expected_hash = suggestion.payload_hash

    statements: list[tuple[str, object]] = []

    def capture(_conn, _cursor, statement, parameters, _context, _many):
        normalized = " ".join(statement.casefold().split())
        if (
            normalized.startswith("select")
            and "gmail_extracted_obligations" in normalized
            and "contact_hint" in normalized
        ):
            statements.append((normalized, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with sessions() as session:
            suggestion = await session.get(CRMTaskSuggestion, suggestion_id)
            payload = await CRMTaskSuggestionService.task_payload(
                session=session,
                suggestion=suggestion,
                expected_version=expected_version,
                expected_payload_hash=expected_hash,
            )
            assert payload.contact_id == contact.id
            await session.rollback()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    assert len(statements) == 2
    first_statement, first_parameters = statements[0]
    last_statement, last_parameters = statements[1]
    for statement, parameters in statements:
        assert "crm_task_suggestion_sources" not in statement
        assert " distinct " not in statement
        assert " limit " in statement
        flattened_parameters = (
            tuple(parameters)
            if isinstance(parameters, (list, tuple))
            else tuple(parameters.values())
        )
        assert 1 in flattened_parameters
    assert " order by gmail_extracted_obligations.contact_hint asc" in (
        first_statement
    )
    assert " order by gmail_extracted_obligations.contact_hint desc" in (
        last_statement
    )
    assert first_parameters is not None
    assert last_parameters is not None


async def test_different_threads_reconcile_while_one_thread_lock_is_held(
    suggestion_runtime,
) -> None:
    from services.gmail_obligation_reconciliation import (
        GmailObligationReconciliationService,
    )
    from services.integration_advisory_locks import thread_advisory_key

    engine, sessions = suggestion_runtime
    account = await _seed_account(sessions)
    blocked_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-blocked",
    )
    free_receipt = await _seed_receipt(
        sessions,
        account_id=account.id,
        thread_id="thread-free",
    )
    service = GmailObligationReconciliationService(sessionmaker=sessions)
    blocked_claim = await service.claim_attempt(
        receipt_id=blocked_receipt.id,
        schema_version="gmail-task-v1",
    )
    free_claim = await service.claim_attempt(
        receipt_id=free_receipt.id,
        schema_version="gmail-task-v1",
    )

    blocker = await engine.connect()
    transaction = await blocker.begin()
    await blocker.execute(
        sa.text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": thread_advisory_key(account.id, blocked_receipt.gmail_thread_id)},
    )
    blocked_task = asyncio.create_task(
        service.reconcile_attempt(
            claim=blocked_claim,
            extraction=_extraction(blocked_receipt, _obligation()),
        )
    )
    try:
        await asyncio.sleep(0.05)
        assert not blocked_task.done()
        free_result = await asyncio.wait_for(
            service.reconcile_attempt(
                claim=free_claim,
                extraction=_extraction(
                    free_receipt,
                    _obligation(
                        action_key="action-v1:" + "4" * 64,
                        obligation_fingerprint="5" * 64,
                    ),
                ),
            ),
            timeout=1,
        )
        assert len(free_result.suggestion_ids) == 1
    finally:
        await transaction.rollback()
        await blocker.close()
    blocked_result = await asyncio.wait_for(blocked_task, timeout=2)
    assert len(blocked_result.suggestion_ids) == 1


def test_payload_hash_is_canonical_and_excludes_source_schema_and_version() -> None:
    from services.crm_task_suggestion_service import canonical_task_payload_hash

    payload = {
        "title": "Call Alice",
        "description": "Discuss the showing.",
        "priority": "normal",
        "due_at": datetime(2026, 8, 22, 19, 0, tzinfo=UTC),
        "contact_id": None,
        "status": "open",
    }
    first = canonical_task_payload_hash(**payload)
    second = canonical_task_payload_hash(**dict(reversed(tuple(payload.items()))))
    assert first == second
    assert first == hashlib.sha256(
        (
            '{"contact_id":null,"description":"Discuss the showing.",'
            '"due_at":"2026-08-22T19:00:00Z","priority":"normal",'
            '"status":"open","title":"Call Alice"}'
        ).encode("utf-8")
    ).hexdigest()


def test_payload_hash_preserves_material_due_time_microseconds() -> None:
    from services.crm_task_suggestion_service import canonical_task_payload_hash

    base = {
        "title": "Call Alice",
        "description": "Discuss the showing.",
        "priority": "normal",
        "contact_id": None,
        "status": "open",
    }
    first = canonical_task_payload_hash(
        **base,
        due_at=datetime(2026, 8, 22, 19, 0, 0, 1, tzinfo=UTC),
    )
    second = canonical_task_payload_hash(
        **base,
        due_at=datetime(2026, 8, 22, 19, 0, 0, 2, tzinfo=UTC),
    )

    assert first != second


def test_source_scope_is_account_and_thread_bounded_without_schema_or_message() -> None:
    from services.crm_task_suggestion_service import gmail_source_scope_key

    account_id = UUID("00000000-0000-0000-0000-000000000001")
    scope = gmail_source_scope_key(account_id, "thread-123")
    assert scope == f"gmail:{account_id}:thread-123"
    assert "message" not in scope
    assert "schema" not in scope
    assert len(scope) <= 512


@pytest.mark.parametrize(
    "thread_id",
    ["thread\x00id", "thread\x07id", "thread\x7fid", "thread id", "\tthread"],
)
def test_source_scope_rejects_noncanonical_provider_thread_ids(thread_id: str) -> None:
    from services.crm_task_suggestion_service import gmail_source_scope_key

    with pytest.raises(ValueError):
        gmail_source_scope_key(
            UUID("00000000-0000-0000-0000-000000000001"),
            thread_id,
        )
