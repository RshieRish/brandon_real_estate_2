"""Transactional Gmail obligation and CRM task-suggestion reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import bindparam, exists, func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent_action_audit import AgentActionAudit
from models.command import CRMContact
from models.gmail_task_intake import (
    CRMTaskSuggestion,
    CRMTaskSuggestionSource,
    CRMTaskSuggestionSuppression,
    GmailExtractedObligation,
    GmailExtractionAttempt,
    GmailMessageReceipt,
)
from services.command_contact_identity import canonical_email
from services.crm_task_suggestion_service import (
    canonical_task_payload_hash,
    gmail_source_scope_key,
)
from services.gmail_task_extractor import (
    ExtractedGmailObligation,
    GmailExtractionResult,
    gmail_identity_instance_digest,
    gmail_participant_evidence_hash,
    gmail_subject_evidence_hash,
)
from services.integration_advisory_locks import (
    contact_identity_transaction_lock,
    transaction_advisory_lock,
)
from services.sydney_clarification_service import (
    contact_resolution_hash,
    supersede_locked_clarification,
)


_SCHEMA_VERSION = re.compile(r"[a-z][a-z0-9-]{0,63}")
_INSTANCE_DIGEST = re.compile(r"[0-9a-f]{64}")
_BASE_ACTION_KEY = re.compile(r"action-v1:[0-9a-f]{64}")
_REPROCESS_PATH_PREFIX = (
    "/api/v1/admin/integrations/gmail-task-intake/reprocess/"
)
_FAILURE_MESSAGES = {
    "provider_timeout": "Gmail obligation extraction timed out.",
    "provider_failed": "Gmail obligation extraction failed.",
    "invalid_model_output": "Gmail obligation extraction returned invalid output.",
    "body_truncated": "Gmail evidence requires manual review.",
}
_CANDIDATE_LIMIT_CATEGORY = "suggestion_candidate_limit"
_CANDIDATE_LIMIT_MESSAGE = "Gmail suggestion history requires manual review."
_BLOCKER_ORDER = (
    "missing_required_field",
    "ambiguous_due_at",
    "ambiguous_contact",
    "multiple_actions",
    "unsupported_owner",
    "unsupported_link",
)
_TERMINAL_SUGGESTION_STATES = {
    "approved",
    "dismissed",
    "applied",
    "failed",
}


def _bounded_candidate_id_rows(
    candidate_ids: Sequence[UUID],
    *,
    bind_name: str,
):
    return (
        func.unnest(
            bindparam(
                bind_name,
                value=list(candidate_ids),
                type_=ARRAY(PostgreSQLUUID(as_uuid=True)),
            )
        )
        .table_valued("suggestion_id")
        .render_derived(name=f"{bind_name}_rows")
    )


class GmailObligationReconciliationError(RuntimeError):
    """Fixed, body-free reconciliation failure."""


class GmailExtractionAttemptLimitReached(GmailObligationReconciliationError):
    """No further extraction attempts may be created for this schema."""


class GmailReconciliationCandidateLimitReached(
    GmailObligationReconciliationError
):
    """The bounded thread suggestion set requires manual review."""


def _fixed_error(
    category: str,
    *,
    error_type: type[GmailObligationReconciliationError] = (
        GmailObligationReconciliationError
    ),
) -> GmailObligationReconciliationError:
    error = error_type(category)
    error.__cause__ = None
    error.__context__ = None
    return error


@dataclass(frozen=True, slots=True)
class GmailExtractionAttemptClaim:
    id: UUID
    receipt_id: UUID
    schema_version: str
    attempt_number: int
    state: str
    replayed: bool
    receipt_processing_started_at: datetime | None
    error_category: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class GmailObligationReconciliationResult:
    attempt_id: UUID
    replayed: bool
    suggestion_ids: tuple[UUID, ...]
    suppressed_action_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedContact:
    contact_id: int | None
    durable_hint: str | None
    ambiguous: bool
    supplied: bool


def _claim_from_row(
    row: GmailExtractionAttempt,
    *,
    replayed: bool,
    receipt_processing_started_at: datetime | None,
) -> GmailExtractionAttemptClaim:
    return GmailExtractionAttemptClaim(
        id=row.id,
        receipt_id=row.receipt_id,
        schema_version=row.schema_version,
        attempt_number=row.attempt_number,
        state=row.state,
        replayed=replayed,
        receipt_processing_started_at=receipt_processing_started_at,
        error_category=row.error_category,
        error_message=row.error_message,
    )


def _ordered_blockers(values: Sequence[str] | set[str]) -> list[str]:
    value_set = set(values)
    return [code for code in _BLOCKER_ORDER if code in value_set]


def _state_for_blockers(blockers: Sequence[str]) -> tuple[str, str]:
    if "multiple_actions" in blockers:
        return "needs_clarification", "manual_review_required"
    if any(
        code
        in {
            "missing_required_field",
            "ambiguous_due_at",
            "ambiguous_contact",
        }
        for code in blockers
    ):
        return "needs_clarification", "pending"
    return "pending_review", "not_required"


def _authority_blockers(
    obligation: ExtractedGmailObligation,
    *,
    contact_ambiguous: bool,
) -> list[str]:
    blockers: set[str] = set()
    if obligation.taxonomy_fallback or obligation.owner_ambiguous:
        blockers.add("missing_required_field")
    if obligation.due_at_ambiguous:
        blockers.add("ambiguous_due_at")
    if contact_ambiguous:
        blockers.add("ambiguous_contact")
    if obligation.identity_collision_requires_review:
        blockers.add("multiple_actions")
    if obligation.requested_owner is not None and (
        " ".join(
            unicodedata.normalize("NFKC", obligation.requested_owner)
            .casefold()
            .split()
        )
        not in {"brandon", "brandon sweeney"}
    ):
        blockers.add("unsupported_owner")
    if (
        obligation.requested_link_type is not None
        or obligation.requested_link_id is not None
    ):
        blockers.add("unsupported_link")
    return _ordered_blockers(blockers)


def _source_label(receipt: GmailMessageReceipt) -> str:
    digest = hashlib.sha256(
        receipt.gmail_message_id.encode("ascii")
    ).hexdigest()[:32]
    return f"gmail:{receipt.direction}:{digest}"


def _payload_hash(
    obligation: ExtractedGmailObligation,
    *,
    contact_id: int | None,
) -> str:
    return canonical_task_payload_hash(
        title=obligation.title,
        description=obligation.description,
        priority=obligation.priority,
        due_at=obligation.due_at,
        contact_id=contact_id,
        status="open",
    )


def _reconciliation_material_hash(
    obligation: ExtractedGmailObligation,
    *,
    contact_id: int | None,
    intrinsic_blockers: Sequence[str],
) -> str:
    """Bind immutable source evidence to its approval-relevant material."""
    payload = {
        "blockers": _ordered_blockers(
            set(intrinsic_blockers) - {"multiple_actions"}
        ),
        "task_payload_hash": _payload_hash(
            obligation,
            contact_id=contact_id,
        ),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reconciliation_action_key(
    obligation: ExtractedGmailObligation,
) -> str:
    return obligation.reconciliation_action_key or obligation.action_key


def _stored_reconciliation_action_key(
    obligation: GmailExtractedObligation,
) -> str:
    try:
        evaluator = json.loads(obligation.evaluator_result_json)
    except (TypeError, json.JSONDecodeError):
        raise _fixed_error("gmail_obligation_disposition_invalid") from None
    if type(evaluator) is not dict:
        raise _fixed_error("gmail_obligation_disposition_invalid")
    value = evaluator.get("reconciliation_action_key", obligation.action_key)
    if type(value) is not str or not value or len(value) > 128:
        raise _fixed_error("gmail_obligation_disposition_invalid")
    return value


def _require_instance_digest(obligation: ExtractedGmailObligation) -> None:
    supplied = obligation.identity_instance_digest
    expected = gmail_identity_instance_digest(
        title=obligation.title,
        description=obligation.description,
    )
    if (
        type(supplied) is not str
        or _INSTANCE_DIGEST.fullmatch(supplied) is None
        or supplied != expected
    ):
        raise _fixed_error("gmail_obligation_instance_digest_invalid")


def _evaluator_result_json(
    obligation: ExtractedGmailObligation,
    *,
    contact: _ResolvedContact,
) -> str:
    if obligation.due_at_ambiguous:
        due_at_state = "ambiguous"
    elif obligation.due_at is None:
        due_at_state = "not_provided"
    else:
        due_at_state = "resolved"
    if obligation.owner_ambiguous:
        owner_state = "ambiguous"
    elif obligation.requested_owner is None:
        owner_state = "implicit_brandon"
    else:
        owner_state = "explicit"
    result: dict[str, object] = {
        "contact_hint_supplied": contact.supplied,
        "due_at_ambiguous": obligation.due_at_ambiguous,
        "due_at_state": due_at_state,
        "link_state": (
            "provided"
            if obligation.requested_link_type is not None
            else "not_provided"
        ),
        "owner_ambiguous": obligation.owner_ambiguous,
        "owner_state": owner_state,
        "participant_ambiguous": obligation.participant_ambiguous,
        "participant_state": (
            "model_contact"
            if contact.contact_id is not None
            else (
                "ambiguous"
                if obligation.participant_ambiguous
                else "backend_unique"
            )
        ),
    }
    if obligation.taxonomy_fallback:
        result["taxonomy_fallback"] = True
    if obligation.identity_collision:
        result["identity_collision"] = True
        result["reconciliation_action_key"] = _reconciliation_action_key(
            obligation
        )
        if obligation.identity_collision_requires_review:
            result["identity_collision_requires_review"] = True
        if obligation.identity_instance_digest is not None:
            result["identity_instance_digest"] = (
                obligation.identity_instance_digest
            )
    return json.dumps(
        result,
        sort_keys=True,
        separators=(",", ":"),
    )


def _receipt_participant_evidence_hash(
    receipt: GmailMessageReceipt,
) -> str | None:
    try:
        recipients = json.loads(receipt.recipient_hmacs_json)
        if type(recipients) is not list:
            return None
        return gmail_participant_evidence_hash(
            direction=receipt.direction,
            sender_hmac=receipt.sender_hmac,
            recipient_hmacs=recipients,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


class GmailObligationReconciliationService:
    """Persists one extraction attempt and reconciles thread-scoped suggestions."""

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        max_attempts_per_schema: int = 3,
        max_thread_candidates: int = 500,
        after_suggestion_lookup: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if (
            isinstance(max_attempts_per_schema, bool)
            or not isinstance(max_attempts_per_schema, int)
            or max_attempts_per_schema < 1
            or max_attempts_per_schema > 100
        ):
            raise ValueError("max_attempts_per_schema is invalid")
        if (
            isinstance(max_thread_candidates, bool)
            or not isinstance(max_thread_candidates, int)
            or max_thread_candidates < 1
            or max_thread_candidates > 5_000
        ):
            raise ValueError("max_thread_candidates is invalid")
        self._sessionmaker = sessionmaker
        self._max_attempts_per_schema = max_attempts_per_schema
        self._max_thread_candidates = max_thread_candidates
        self._after_suggestion_lookup = after_suggestion_lookup

    async def claim_attempt(
        self,
        *,
        receipt_id: UUID,
        schema_version: str,
    ) -> GmailExtractionAttemptClaim:
        if (
            not isinstance(receipt_id, UUID)
            or type(schema_version) is not str
            or _SCHEMA_VERSION.fullmatch(schema_version) is None
        ):
            raise _fixed_error("gmail_extraction_claim_invalid")
        async with self._sessionmaker() as session:
            async with session.begin():
                receipt = await session.scalar(
                    select(GmailMessageReceipt)
                    .where(GmailMessageReceipt.id == receipt_id)
                    .with_for_update()
                )
                if receipt is None:
                    raise _fixed_error("gmail_extraction_receipt_missing")
                attempts = list(
                    (
                        await session.scalars(
                            select(GmailExtractionAttempt)
                            .where(
                                GmailExtractionAttempt.receipt_id == receipt_id,
                                GmailExtractionAttempt.schema_version
                                == schema_version,
                            )
                            .order_by(
                                GmailExtractionAttempt.attempt_number,
                                GmailExtractionAttempt.id,
                            )
                        )
                    ).all()
                )
                succeeded = next(
                    (row for row in reversed(attempts) if row.state == "succeeded"),
                    None,
                )
                if succeeded is not None:
                    return _claim_from_row(
                        succeeded,
                        replayed=True,
                        receipt_processing_started_at=None,
                    )
                candidate_limit_attempt = next(
                    (
                        row
                        for row in reversed(attempts)
                        if row.error_category == _CANDIDATE_LIMIT_CATEGORY
                    ),
                    None,
                )
                if candidate_limit_attempt is not None:
                    raise _fixed_error(
                        "gmail_suggestion_candidate_limit",
                        error_type=GmailReconciliationCandidateLimitReached,
                    )
                self._require_receipt_extractable(receipt)
                running = next(
                    (row for row in reversed(attempts) if row.state == "running"),
                    None,
                )
                if running is not None:
                    return _claim_from_row(
                        running,
                        replayed=True,
                        receipt_processing_started_at=(
                            receipt.processing_started_at
                        ),
                    )
                if len(attempts) >= self._max_attempts_per_schema:
                    raise _fixed_error(
                        "gmail_extraction_attempt_limit",
                        error_type=GmailExtractionAttemptLimitReached,
                    )
                row = GmailExtractionAttempt(
                    receipt_id=receipt_id,
                    schema_version=schema_version,
                    attempt_number=len(attempts) + 1,
                    state="running",
                )
                session.add(row)
                await session.flush()
                return _claim_from_row(
                    row,
                    replayed=False,
                    receipt_processing_started_at=(
                        receipt.processing_started_at
                    ),
                )

    async def fail_attempt(
        self,
        *,
        claim: GmailExtractionAttemptClaim,
        category: str,
    ) -> GmailExtractionAttemptClaim:
        if category not in _FAILURE_MESSAGES:
            raise _fixed_error("gmail_extraction_failure_category_invalid")
        async with self._sessionmaker() as session:
            async with session.begin():
                row = await session.scalar(
                    select(GmailExtractionAttempt)
                    .where(GmailExtractionAttempt.id == claim.id)
                    .with_for_update()
                )
                self._require_claim_identity(row=row, claim=claim)
                if row.state == "succeeded":
                    raise _fixed_error("gmail_extraction_attempt_state_invalid")
                if row.state == "running":
                    receipt = await session.scalar(
                        select(GmailMessageReceipt)
                        .where(GmailMessageReceipt.id == claim.receipt_id)
                        .with_for_update()
                    )
                    if receipt is None:
                        raise _fixed_error("gmail_extraction_receipt_missing")
                    self._require_receipt_extractable(receipt)
                    self._require_processing_lease(
                        receipt=receipt,
                        claim=claim,
                    )
                    row.state = "failed"
                    row.error_category = category
                    row.error_message = _FAILURE_MESSAGES[category]
                    row.completed_at = datetime.now(timezone.utc)
                    await session.flush()
                return _claim_from_row(
                    row,
                    replayed=row.state == "failed",
                    receipt_processing_started_at=(
                        claim.receipt_processing_started_at
                    ),
                )

    async def reconcile_attempt(
        self,
        *,
        claim: GmailExtractionAttemptClaim,
        extraction: GmailExtractionResult,
    ) -> GmailObligationReconciliationResult:
        terminal_error: GmailObligationReconciliationError | None = None
        result: GmailObligationReconciliationResult | None = None
        try:
            async with self._sessionmaker() as session:
                async with session.begin():
                    attempt = await session.scalar(
                        select(GmailExtractionAttempt)
                        .where(GmailExtractionAttempt.id == claim.id)
                        .with_for_update()
                    )
                    self._require_claim_identity(row=attempt, claim=claim)
                    receipt = await session.scalar(
                        select(GmailMessageReceipt)
                        .where(GmailMessageReceipt.id == claim.receipt_id)
                        .with_for_update()
                    )
                    if receipt is None:
                        raise _fixed_error("gmail_extraction_receipt_missing")
                    self._require_source_identity(
                        attempt=attempt,
                        receipt=receipt,
                        extraction=extraction,
                    )
                    if attempt.state == "succeeded":
                        await transaction_advisory_lock(
                            await session.connection(),
                            receipt.account_id,
                            receipt.gmail_thread_id,
                        )
                        return await self._replay_result(
                            session=session,
                            attempt=attempt,
                        )
                    if attempt.state != "running":
                        raise _fixed_error(
                            "gmail_extraction_attempt_state_invalid"
                        )
                    self._require_receipt_extractable(receipt)
                    self._require_processing_lease(
                        receipt=receipt,
                        claim=claim,
                    )
                    await transaction_advisory_lock(
                        await session.connection(),
                        receipt.account_id,
                        receipt.gmail_thread_id,
                    )
                    try:
                        result = await self._reconcile_running_attempt(
                            session=session,
                            attempt=attempt,
                            receipt=receipt,
                            extraction=extraction,
                        )
                    except GmailReconciliationCandidateLimitReached as error:
                        attempt.state = "failed"
                        attempt.error_category = _CANDIDATE_LIMIT_CATEGORY
                        attempt.error_message = _CANDIDATE_LIMIT_MESSAGE
                        attempt.completed_at = datetime.now(timezone.utc)
                        await session.flush()
                        terminal_error = error
                if terminal_error is not None:
                    raise terminal_error
                if result is None:
                    raise _fixed_error("gmail_obligation_reconciliation_failed")
                return result
        except asyncio.CancelledError:
            raise
        except GmailObligationReconciliationError:
            raise
        except BaseException:
            raise _fixed_error("gmail_obligation_reconciliation_failed") from None

    async def _reconcile_running_attempt(
        self,
        *,
        session: AsyncSession,
        attempt: GmailExtractionAttempt,
        receipt: GmailMessageReceipt,
        extraction: GmailExtractionResult,
    ) -> GmailObligationReconciliationResult:
        for obligation in extraction.obligations:
            _require_instance_digest(obligation)
        candidates, fallback_suggestion_ids = (
            await self._load_thread_candidates(
                session=session,
                receipt=receipt,
            )
        )
        prepared: list[
            tuple[
                ExtractedGmailObligation,
                _ResolvedContact,
                str,
                str,
            ]
        ] = []
        action_count_by_key: dict[str, int] = {}
        instance_digests_by_identity: dict[tuple[str, str], set[str]] = {}
        exact_effective_identities: set[tuple[str, str, str]] = set()
        for obligation in extraction.obligations:
            contact = await self._resolve_contact(
                session=session,
                contact_hint=obligation.contact_hint,
            )
            if contact.supplied and contact.contact_id is None:
                base_action_key = (
                    obligation.participant_reconciliation_action_key
                )
                fingerprint = obligation.participant_obligation_fingerprint
                if (
                    type(base_action_key) is not str
                    or _BASE_ACTION_KEY.fullmatch(base_action_key) is None
                    or type(fingerprint) is not str
                    or _INSTANCE_DIGEST.fullmatch(fingerprint) is None
                ):
                    raise _fixed_error(
                        "gmail_extraction_effective_identity_invalid"
                    )
            else:
                base_action_key = _reconciliation_action_key(obligation)
                fingerprint = obligation.obligation_fingerprint
            effective_identity = (
                base_action_key,
                fingerprint,
                obligation.identity_instance_digest,
            )
            if effective_identity in exact_effective_identities:
                raise _fixed_error(
                    "gmail_extraction_effective_identity_invalid"
                )
            exact_effective_identities.add(effective_identity)
            action_count_by_key[base_action_key] = (
                action_count_by_key.get(base_action_key, 0) + 1
            )
            instance_digests_by_identity.setdefault(
                (base_action_key, fingerprint),
                set(),
            ).add(obligation.identity_instance_digest)
            prepared.append(
                (obligation, contact, base_action_key, fingerprint)
            )

        effective_obligations: list[
            tuple[ExtractedGmailObligation, _ResolvedContact]
        ] = []
        effective_action_keys: set[str] = set()
        for obligation, contact, base_action_key, fingerprint in prepared:
            identity_collision = action_count_by_key[base_action_key] > 1
            collision_requires_review = (
                len(
                    instance_digests_by_identity[
                        (base_action_key, fingerprint)
                    ]
                )
                > 1
            )
            action_key = (
                f"{base_action_key}:"
                + hashlib.sha256(
                    (
                        f"{fingerprint}:"
                        f"{obligation.identity_instance_digest}"
                    ).encode("ascii")
                ).hexdigest()[:32]
                if identity_collision
                else base_action_key
            )
            if (
                len(action_key) > 128
                or action_key in effective_action_keys
            ):
                raise _fixed_error(
                    "gmail_extraction_effective_identity_invalid"
                )
            effective_action_keys.add(action_key)
            effective_obligations.append(
                (
                    replace(
                        obligation,
                        action_key=action_key,
                        reconciliation_action_key=base_action_key,
                        obligation_fingerprint=fingerprint,
                        identity_collision=identity_collision,
                        identity_collision_requires_review=(
                            collision_requires_review
                        ),
                    ),
                    contact,
                )
            )
        scope_key = gmail_source_scope_key(
            receipt.account_id,
            receipt.gmail_thread_id,
        )
        suggestion_ids: list[UUID] = []
        suppressed_action_keys: list[str] = []
        authorized_overrides: dict[UUID, CRMTaskSuggestionSuppression] = {}
        for obligation, contact in effective_obligations:
            initial_intrinsic_blockers = _ordered_blockers(
                set(
                    _authority_blockers(
                        obligation,
                        contact_ambiguous=contact.ambiguous,
                    )
                )
                - {"multiple_actions"}
            )
            stored_obligation = GmailExtractedObligation(
                receipt_id=receipt.id,
                extraction_attempt_id=attempt.id,
                action_key=obligation.action_key,
                schema_version=extraction.schema_version,
                title=obligation.title,
                description=obligation.description,
                priority=obligation.priority,
                due_at=obligation.due_at,
                timezone_basis=obligation.timezone_basis,
                requested_owner=obligation.requested_owner,
                requested_link_type=obligation.requested_link_type,
                requested_link_id=obligation.requested_link_id,
                contact_hint=contact.durable_hint,
                taxonomy_fallback=obligation.taxonomy_fallback,
                owner_ambiguous=obligation.owner_ambiguous,
                obligation_fingerprint=obligation.obligation_fingerprint,
                identity_instance_digest=obligation.identity_instance_digest,
                reconciliation_material_hash=_reconciliation_material_hash(
                    obligation,
                    contact_id=contact.contact_id,
                    intrinsic_blockers=initial_intrinsic_blockers,
                ),
                reconciled_suggestion_id=None,
                reconciled_suppression_id=None,
                confidence=obligation.confidence,
                evaluator_result_json=_evaluator_result_json(
                    obligation,
                    contact=contact,
                ),
                evidence_preview=obligation.evidence_preview,
            )
            suppression = await session.scalar(
                select(CRMTaskSuggestionSuppression)
                .where(
                    CRMTaskSuggestionSuppression.source_type
                    == "gmail_message",
                    CRMTaskSuggestionSuppression.source_scope_key == scope_key,
                    CRMTaskSuggestionSuppression.source_action_key
                    == _reconciliation_action_key(obligation),
                    CRMTaskSuggestionSuppression.obligation_fingerprint
                    == obligation.obligation_fingerprint,
                    CRMTaskSuggestionSuppression.identity_instance_digest
                    == obligation.identity_instance_digest,
                )
                .with_for_update()
            )
            override_used = False
            if suppression is not None:
                override_used = suppression.id in authorized_overrides
                if not override_used:
                    override_used = await self._override_is_valid(
                        session=session,
                        suppression=suppression,
                        receipt_id=receipt.id,
                    )
                    if override_used:
                        authorized_overrides[suppression.id] = suppression
                if not override_used:
                    stored_obligation.reconciled_suppression_id = (
                        suppression.id
                    )
                    session.add(stored_obligation)
                    await session.flush()
                    suppressed_action_keys.append(obligation.action_key)
                    continue

            suggestion = await self._reconcile_one_suggestion(
                session=session,
                receipt=receipt,
                extraction=extraction,
                obligation=obligation,
                stored_obligation=stored_obligation,
                contact=contact,
                scope_key=scope_key,
                override_used=override_used,
                candidates=candidates,
                fallback_suggestion_ids=fallback_suggestion_ids,
            )
            if all(candidate.id != suggestion.id for candidate in candidates):
                candidates.append(suggestion)
            if obligation.taxonomy_fallback:
                fallback_suggestion_ids.add(suggestion.id)
            suggestion_ids.append(suggestion.id)

        consumed_at = datetime.now(timezone.utc)
        for suppression in authorized_overrides.values():
            override_at = suppression.reprocess_override_at
            if override_at is None:
                raise _fixed_error("gmail_suppression_override_invalid")
            suppression.reprocess_override_consumed_at = max(
                consumed_at,
                override_at,
            )
        attempt.state = "succeeded"
        attempt.error_category = None
        attempt.error_message = None
        attempt.completed_at = datetime.now(timezone.utc)
        await session.flush()
        return GmailObligationReconciliationResult(
            attempt_id=attempt.id,
            replayed=False,
            suggestion_ids=tuple(suggestion_ids),
            suppressed_action_keys=tuple(suppressed_action_keys),
        )

    async def _load_thread_candidates(
        self,
        *,
        session: AsyncSession,
        receipt: GmailMessageReceipt,
    ) -> tuple[list[CRMTaskSuggestion], set[UUID]]:
        candidates = list(
            (
                await session.scalars(
                    select(CRMTaskSuggestion)
                    .where(
                        CRMTaskSuggestion.source_type == "gmail_message",
                        CRMTaskSuggestion.gmail_account_id == receipt.account_id,
                        CRMTaskSuggestion.gmail_thread_id
                        == receipt.gmail_thread_id,
                    )
                    .order_by(
                        CRMTaskSuggestion.created_at,
                        CRMTaskSuggestion.id,
                    )
                    .limit(self._max_thread_candidates + 1)
                    .with_for_update()
                )
            ).all()
        )
        if len(candidates) > self._max_thread_candidates:
            raise _fixed_error(
                "gmail_suggestion_candidate_limit",
                error_type=GmailReconciliationCandidateLimitReached,
            )
        if self._after_suggestion_lookup is not None:
            await self._after_suggestion_lookup()
        if not candidates:
            return candidates, set()
        candidate_id_rows = _bounded_candidate_id_rows(
            [candidate.id for candidate in candidates],
            bind_name="gmail_candidate_ids",
        )
        fallback_suggestion_ids = set(
            (
                await session.scalars(
                    select(candidate_id_rows.c.suggestion_id)
                    .where(
                        exists(
                            select(GmailExtractedObligation.id)
                            .where(
                                GmailExtractedObligation.reconciled_suggestion_id
                                == candidate_id_rows.c.suggestion_id,
                                GmailExtractedObligation.taxonomy_fallback.is_(
                                    True
                                ),
                            )
                        ),
                    )
                )
            ).all()
        )
        return candidates, fallback_suggestion_ids

    @staticmethod
    def _require_receipt_extractable(receipt: GmailMessageReceipt) -> None:
        if (
            receipt.classification != "eligible"
            or receipt.processing_state != "processing"
            or receipt.processing_started_at is None
        ):
            raise _fixed_error("gmail_extraction_receipt_ineligible")

    @staticmethod
    def _require_processing_lease(
        *,
        receipt: GmailMessageReceipt,
        claim: GmailExtractionAttemptClaim,
    ) -> None:
        if (
            claim.receipt_processing_started_at is None
            or receipt.processing_started_at
            != claim.receipt_processing_started_at
        ):
            raise _fixed_error("gmail_extraction_receipt_lease_lost")

    @staticmethod
    def _require_claim_identity(
        *,
        row: GmailExtractionAttempt | None,
        claim: GmailExtractionAttemptClaim,
    ) -> None:
        if row is None:
            raise _fixed_error("gmail_extraction_attempt_missing")
        if (
            row.receipt_id != claim.receipt_id
            or row.schema_version != claim.schema_version
            or row.attempt_number != claim.attempt_number
        ):
            raise _fixed_error("gmail_extraction_source_mismatch")

    @staticmethod
    def _require_source_identity(
        *,
        attempt: GmailExtractionAttempt,
        receipt: GmailMessageReceipt,
        extraction: GmailExtractionResult,
    ) -> None:
        if (
            extraction.account_id != receipt.account_id
            or extraction.message_id != receipt.gmail_message_id
            or extraction.thread_id != receipt.gmail_thread_id
            or extraction.direction != receipt.direction
            or extraction.body_hash != receipt.body_hash
            or extraction.subject_evidence_hash
            != gmail_subject_evidence_hash(receipt.subject_preview)
            or not isinstance(extraction.reference_message_at, datetime)
            or extraction.reference_message_at.tzinfo is None
            or extraction.reference_message_at.utcoffset() is None
            or not isinstance(receipt.message_at, datetime)
            or receipt.message_at.tzinfo is None
            or receipt.message_at.utcoffset() is None
            or extraction.reference_message_at != receipt.message_at
            or extraction.participant_evidence_hash
            != _receipt_participant_evidence_hash(receipt)
            or extraction.schema_version != attempt.schema_version
        ):
            raise _fixed_error("gmail_extraction_source_mismatch")

    @staticmethod
    async def _resolve_contact(
        *,
        session: AsyncSession,
        contact_hint: str | None,
    ) -> _ResolvedContact:
        if contact_hint is None:
            return _ResolvedContact(None, None, False, False)
        normalized = canonical_email(contact_hint)
        if normalized is None:
            return _ResolvedContact(None, None, True, True)
        await contact_identity_transaction_lock(await session.connection())
        rows = list(
            (
                await session.execute(
                    select(
                        CRMContact.id,
                        CRMContact.email,
                        CRMContact.normalized_email,
                    )
                    .where(CRMContact.normalized_email == normalized)
                    .order_by(CRMContact.id)
                    .limit(2)
                    .with_for_update()
                )
            ).all()
        )
        if (
            len(rows) == 1
            and rows[0].normalized_email == normalized
            and canonical_email(rows[0].email) == normalized
        ):
            return _ResolvedContact(rows[0].id, normalized, False, True)
        return _ResolvedContact(None, None, True, True)

    @staticmethod
    async def _override_is_valid(
        *,
        session: AsyncSession,
        suppression: CRMTaskSuggestionSuppression,
        receipt_id: UUID,
    ) -> bool:
        if (
            suppression.reprocess_override_at is None
            or suppression.reprocess_override_by_admin_id is None
            or suppression.reprocess_override_audit_id is None
            or suppression.reprocess_override_consumed_at is not None
            or suppression.reprocess_override_audit_id
            == suppression.dismissal_audit_id
        ):
            return False
        audit = await session.get(
            AgentActionAudit,
            suppression.reprocess_override_audit_id,
        )
        if (
            audit is None
            or not audit.allowed
            or audit.actor != "admin"
            or audit.action_id != "gmail_task_intake.reprocess"
            or audit.method != "POST"
            or audit.status_code != 200
            or not audit.path.startswith(_REPROCESS_PATH_PREFIX)
            or not (
                suppression.dismissed_at
                <= audit.created_at
                <= suppression.reprocess_override_at
            )
        ):
            return False
        receipt_id_text = audit.path.removeprefix(_REPROCESS_PATH_PREFIX)
        try:
            if (
                str(UUID(receipt_id_text)) != receipt_id_text
                or UUID(receipt_id_text) != receipt_id
            ):
                return False
            metadata = json.loads(audit.request_meta_json)
        except (TypeError, ValueError):
            return False
        return bool(
            type(metadata) is dict
            and set(metadata) == {"admin_user_id", "suppression_id"}
            and type(metadata["admin_user_id"]) is int
            and metadata["admin_user_id"]
            == suppression.reprocess_override_by_admin_id
            and metadata["suppression_id"] == str(suppression.id)
        )

    async def _reconcile_one_suggestion(
        self,
        *,
        session: AsyncSession,
        receipt: GmailMessageReceipt,
        extraction: GmailExtractionResult,
        obligation: ExtractedGmailObligation,
        stored_obligation: GmailExtractedObligation,
        contact: _ResolvedContact,
        scope_key: str,
        override_used: bool,
        candidates: list[CRMTaskSuggestion],
        fallback_suggestion_ids: set[UUID],
    ) -> CRMTaskSuggestion:
        reconciliation_key = _reconciliation_action_key(obligation)
        base_candidates = [
            candidate
            for candidate in candidates
            if candidate.source_action_key == reconciliation_key
        ]
        conflicting_base_candidates = [
            candidate
            for candidate in base_candidates
            if candidate.obligation_fingerprint
            != obligation.obligation_fingerprint
        ]
        fingerprint_candidates = [
            candidate
            for candidate in base_candidates
            if candidate.obligation_fingerprint
            == obligation.obligation_fingerprint
        ]
        attached_instance_ids: set[UUID] = set()
        if fingerprint_candidates:
            membership_candidate_rows = _bounded_candidate_id_rows(
                [row.id for row in fingerprint_candidates],
                bind_name="gmail_instance_candidate_ids",
            )
            candidate_membership = exists(
                select(GmailExtractedObligation.id)
                .where(
                    GmailExtractedObligation.reconciled_suggestion_id
                    == membership_candidate_rows.c.suggestion_id,
                    GmailExtractedObligation.identity_instance_digest
                    == obligation.identity_instance_digest,
                )
            )
            attached_rows = list(
                (
                    await session.scalars(
                        select(
                            membership_candidate_rows.c.suggestion_id
                        ).where(candidate_membership)
                    )
                ).all()
            )
            attached_instance_ids = {
                value for value in attached_rows if value is not None
            }
        instance_candidates = [
            candidate
            for candidate in fingerprint_candidates
            if (
                candidate.primary_instance_digest
                == obligation.identity_instance_digest
                or candidate.id in attached_instance_ids
            )
        ]
        reviewable_instance = [
            candidate
            for candidate in instance_candidates
            if candidate.state not in _TERMINAL_SUGGESTION_STATES
        ]
        if len(reviewable_instance) > 1:
            raise _fixed_error("gmail_suggestion_successor_ambiguous")
        reviewable_fingerprint = [
            candidate
            for candidate in fingerprint_candidates
            if candidate.state not in _TERMINAL_SUGGESTION_STATES
        ]
        if reviewable_instance:
            exact = reviewable_instance[0]
        elif len(reviewable_fingerprint) > 1:
            raise _fixed_error("gmail_suggestion_successor_ambiguous")
        elif reviewable_fingerprint:
            # One reviewable suggestion is the immutable container for all
            # same-fingerprint semantic instances. A distinct digest may add
            # evidence and force manual review, but it may never overwrite the
            # primary instance payload.
            exact = reviewable_fingerprint[0]
        elif instance_candidates:
            exact = instance_candidates[-1]
        elif fingerprint_candidates:
            exact = fingerprint_candidates[-1]
        else:
            exact = None
        incoming_blockers = _authority_blockers(
            obligation,
            contact_ambiguous=contact.ambiguous,
        )
        resolved_contact_id = contact.contact_id
        has_live_conflicting_sibling = any(
            candidate.state not in _TERMINAL_SUGGESTION_STATES
            for candidate in conflicting_base_candidates
        )
        if (
            exact is not None
            and exact.state not in _TERMINAL_SUGGESTION_STATES
            and has_live_conflicting_sibling
        ):
            for candidate in base_candidates:
                if candidate.state in _TERMINAL_SUGGESTION_STATES:
                    continue
                if "multiple_actions" in candidate.blocker_codes:
                    clarification_state = "manual_review_required"
                elif any(
                    blocker
                    in {
                        "missing_required_field",
                        "ambiguous_due_at",
                        "ambiguous_contact",
                    }
                    for blocker in candidate.blocker_codes
                ):
                    clarification_state = "pending"
                else:
                    clarification_state = "not_required"
                if (
                    candidate.state != "possible_duplicate"
                    or candidate.clarification_state != clarification_state
                ):
                    previous_version = candidate.version
                    candidate.state = "possible_duplicate"
                    candidate.clarification_state = clarification_state
                    candidate.version += 1
                    await supersede_locked_clarification(
                        session=session,
                        suggestion=candidate,
                        previous_version=previous_version,
                        now=datetime.now(timezone.utc),
                    )
        if exact is not None:
            primary_instance = (
                exact.primary_instance_digest
                == obligation.identity_instance_digest
            )
            attached_nonprimary_instance = (
                not primary_instance and exact.id in attached_instance_ids
            )
            same_instance = primary_instance or attached_nonprimary_instance
            if not same_instance:
                incoming_blockers = _ordered_blockers(
                    set(incoming_blockers) | {"multiple_actions"}
                )
            existing_blockers = set(exact.blocker_codes)
            if not contact.supplied:
                resolved_contact_id = exact.contact_id
            elif contact.ambiguous:
                resolved_contact_id = None
            elif exact.contact_id is not None and exact.contact_id != contact.contact_id:
                resolved_contact_id = None
                incoming_blockers = _ordered_blockers(
                    set(incoming_blockers) | {"ambiguous_contact"}
                )
            elif "ambiguous_contact" in existing_blockers:
                resolved_contact_id = None
            resolved_contact_email = (
                contact.durable_hint
                if resolved_contact_id == contact.contact_id
                else None
            )
            if resolved_contact_id is not None and resolved_contact_email is None:
                await contact_identity_transaction_lock(
                    await session.connection()
                )
                selected = await session.get(
                    CRMContact,
                    resolved_contact_id,
                    with_for_update=True,
                )
                selected_email = (
                    canonical_email(selected.email) if selected is not None else None
                )
                if (
                    selected is None
                    or selected_email is None
                    or selected.normalized_email != selected_email
                ):
                    resolved_contact_id = None
                else:
                    matches = list(
                        (
                            await session.scalars(
                                select(CRMContact.id)
                                .where(
                                    CRMContact.normalized_email == selected_email
                                )
                                .order_by(CRMContact.id)
                                .limit(2)
                                .with_for_update()
                            )
                        ).all()
                    )
                    if matches != [selected.id]:
                        resolved_contact_id = None
                    else:
                        resolved_contact_email = selected_email
                if resolved_contact_id is None:
                    incoming_blockers = _ordered_blockers(
                        set(incoming_blockers) | {"ambiguous_contact"}
                    )
            merged_blockers = _ordered_blockers(
                existing_blockers | set(incoming_blockers)
            )
            incoming_hash = _payload_hash(
                obligation,
                contact_id=resolved_contact_id,
            )
            intrinsic_blockers = _ordered_blockers(
                set(incoming_blockers) - {"multiple_actions"}
            )
            material_hash = _reconciliation_material_hash(
                obligation,
                contact_id=resolved_contact_id,
                intrinsic_blockers=intrinsic_blockers,
            )
            stored_obligation.reconciliation_material_hash = material_hash
            attached_nonprimary_same_material = False
            if attached_nonprimary_instance:
                attached_nonprimary_same_material = bool(
                    await session.scalar(
                        select(
                            exists(
                                select(GmailExtractedObligation.id)
                                .where(
                                    GmailExtractedObligation.reconciled_suggestion_id
                                    == exact.id,
                                    GmailExtractedObligation.identity_instance_digest
                                    == obligation.identity_instance_digest,
                                    GmailExtractedObligation.reconciliation_material_hash
                                    == material_hash,
                                )
                                .limit(1)
                            )
                        )
                    )
                )
                if not attached_nonprimary_same_material:
                    incoming_blockers = _ordered_blockers(
                        set(incoming_blockers) | {"multiple_actions"}
                    )
                    merged_blockers = _ordered_blockers(
                        existing_blockers | set(incoming_blockers)
                    )
            same_material = (
                same_instance
                and (
                    (
                        attached_nonprimary_same_material
                        and exact.blocker_codes == merged_blockers
                    )
                    or (
                        primary_instance
                        and
                        exact.payload_hash == incoming_hash
                        and exact.obligation_fingerprint
                        == obligation.obligation_fingerprint
                        and exact.blocker_codes == merged_blockers
                    )
                )
            )
            existing_fallback = exact.id in fallback_suggestion_ids
            shared_instance_container = not primary_instance
            if exact.state in _TERMINAL_SUGGESTION_STATES and (
                override_used or not same_material
            ):
                duplicate_of = exact.id
                force_reviewable_successor = override_used
                if conflicting_base_candidates:
                    root = next(
                        (
                            candidate
                            for candidate in base_candidates
                            if candidate.duplicate_of_suggestion_id is None
                        ),
                        base_candidates[0],
                    )
                    for candidate in base_candidates:
                        if candidate.state not in _TERMINAL_SUGGESTION_STATES:
                            previous_version = candidate.version
                            candidate.state = "possible_duplicate"
                            candidate.version += 1
                            await supersede_locked_clarification(
                                session=session,
                                suggestion=candidate,
                                previous_version=previous_version,
                                now=datetime.now(timezone.utc),
                            )
                    duplicate_of = root.id
                    force_reviewable_successor = False
                suggestion = self._new_suggestion(
                    receipt=receipt,
                    extraction=extraction,
                    obligation=obligation,
                    contact_id=resolved_contact_id,
                    contact_email=resolved_contact_email,
                    blockers=merged_blockers,
                    owner_clarification_pending=(
                        exact.owner_clarification_pending
                        or obligation.owner_ambiguous
                    ),
                    task_details_clarification_pending=(
                        exact.task_details_clarification_pending
                        or obligation.taxonomy_fallback
                    ),
                    scope_key=scope_key,
                    duplicate_of=duplicate_of,
                    force_reviewable_successor=force_reviewable_successor,
                )
                session.add(suggestion)
                await session.flush()
            elif (
                not same_material
                and (
                    exact.state in _TERMINAL_SUGGESTION_STATES
                    or (
                        exact.state != "possible_duplicate"
                        and (
                            obligation.taxonomy_fallback
                            or existing_fallback
                        )
                    )
                )
            ):
                suggestion = self._new_suggestion(
                    receipt=receipt,
                    extraction=extraction,
                    obligation=obligation,
                    contact_id=resolved_contact_id,
                    contact_email=resolved_contact_email,
                    blockers=merged_blockers,
                    owner_clarification_pending=(
                        exact.owner_clarification_pending
                        or obligation.owner_ambiguous
                    ),
                    task_details_clarification_pending=(
                        exact.task_details_clarification_pending
                        or obligation.taxonomy_fallback
                    ),
                    scope_key=scope_key,
                    duplicate_of=exact.id,
                )
                session.add(suggestion)
                await session.flush()
            else:
                suggestion = exact
                if not same_material:
                    if suggestion.state == "possible_duplicate":
                        state = "possible_duplicate"
                        if "multiple_actions" in merged_blockers:
                            clarification_state = "manual_review_required"
                        else:
                            clarification_state = (
                                "pending"
                                if any(
                                    blocker
                                    in {
                                        "missing_required_field",
                                        "ambiguous_due_at",
                                        "ambiguous_contact",
                                    }
                                    for blocker in merged_blockers
                                )
                                else "not_required"
                            )
                    else:
                        state, clarification_state = _state_for_blockers(
                            merged_blockers
                        )
                    if not shared_instance_container:
                        suggestion.contact_id = resolved_contact_id
                        suggestion.title = obligation.title
                        suggestion.description = obligation.description
                        suggestion.priority = obligation.priority
                        suggestion.due_at = obligation.due_at
                        suggestion.payload_hash = incoming_hash
                        suggestion.obligation_fingerprint = (
                            obligation.obligation_fingerprint
                        )
                        suggestion.confidence = obligation.confidence
                        suggestion.rationale = obligation.rationale
                    suggestion.state = state
                    suggestion.clarification_state = clarification_state
                    suggestion.blocker_codes = merged_blockers
                    suggestion.owner_clarification_pending = (
                        suggestion.owner_clarification_pending
                        or obligation.owner_ambiguous
                    )
                    suggestion.task_details_clarification_pending = (
                        suggestion.task_details_clarification_pending
                        or obligation.taxonomy_fallback
                    )
                    if resolved_contact_id is not None:
                        suggestion.contact_resolution_state = (
                            "clarified_unique"
                            if suggestion.contact_resolution_state
                            == "clarified_unique"
                            and suggestion.contact_id == resolved_contact_id
                            else "inferred_unique"
                        )
                        suggestion.contact_resolution_hash = (
                            contact_resolution_hash(
                                contact_id=resolved_contact_id,
                                email=resolved_contact_email,
                            )
                        )
                    elif "ambiguous_contact" in merged_blockers:
                        suggestion.contact_resolution_state = "unresolved"
                        suggestion.contact_resolution_hash = None
                    elif (
                        not contact.supplied
                        and suggestion.contact_resolution_state
                        == "explicit_none"
                    ):
                        suggestion.contact_resolution_hash = None
                    else:
                        suggestion.contact_resolution_state = "not_provided"
                        suggestion.contact_resolution_hash = None
                    suggestion.model_schema_version = extraction.schema_version
                    previous_version = suggestion.version
                    suggestion.version += 1
                    await supersede_locked_clarification(
                        session=session,
                        suggestion=suggestion,
                        previous_version=previous_version,
                        now=datetime.now(timezone.utc),
                    )
                    await session.flush()
        else:
            if base_candidates:
                root = next(
                    (
                        candidate
                        for candidate in base_candidates
                        if candidate.duplicate_of_suggestion_id is None
                    ),
                    base_candidates[0],
                )
                for candidate in base_candidates:
                    if candidate.state not in _TERMINAL_SUGGESTION_STATES:
                        previous_version = candidate.version
                        candidate.state = "possible_duplicate"
                        candidate.version += 1
                        await supersede_locked_clarification(
                            session=session,
                            suggestion=candidate,
                            previous_version=previous_version,
                            now=datetime.now(timezone.utc),
                        )
                duplicate_of = root.id
            else:
                duplicate_of = next(
                    (
                        candidate.id
                        for candidate in candidates
                        if (
                            obligation.taxonomy_fallback
                            and candidate.id in fallback_suggestion_ids
                        )
                        or (
                            not obligation.participant_ambiguous
                            and " ".join(
                                candidate.title.casefold().split()
                            )
                            == " ".join(obligation.title.casefold().split())
                        )
                    ),
                    None,
                )
            suggestion = self._new_suggestion(
                receipt=receipt,
                extraction=extraction,
                obligation=obligation,
                contact_id=resolved_contact_id,
                contact_email=(
                    contact.durable_hint
                    if resolved_contact_id == contact.contact_id
                    else None
                ),
                blockers=incoming_blockers,
                owner_clarification_pending=obligation.owner_ambiguous,
                task_details_clarification_pending=obligation.taxonomy_fallback,
                scope_key=scope_key,
                duplicate_of=duplicate_of,
            )
            session.add(suggestion)
            await session.flush()

        stored_obligation.reconciled_suggestion_id = suggestion.id
        session.add(stored_obligation)
        await session.flush()
        source = CRMTaskSuggestionSource(
            suggestion_id=suggestion.id,
            obligation_id=stored_obligation.id,
            receipt_id=receipt.id,
            gmail_account_id=receipt.account_id,
            gmail_thread_id=receipt.gmail_thread_id,
            direction=receipt.direction,
            source_label=_source_label(receipt),
        )
        session.add(source)
        await session.flush()
        return suggestion

    @staticmethod
    def _new_suggestion(
        *,
        receipt: GmailMessageReceipt,
        extraction: GmailExtractionResult,
        obligation: ExtractedGmailObligation,
        contact_id: int | None,
        contact_email: str | None,
        blockers: list[str],
        owner_clarification_pending: bool,
        task_details_clarification_pending: bool,
        scope_key: str,
        duplicate_of: UUID | None,
        force_reviewable_successor: bool = False,
    ) -> CRMTaskSuggestion:
        if duplicate_of is not None and not force_reviewable_successor:
            state = "possible_duplicate"
            if "multiple_actions" in blockers:
                clarification_state = "manual_review_required"
            else:
                clarification_state = (
                    "pending"
                    if any(
                        blocker
                        in {
                            "missing_required_field",
                            "ambiguous_due_at",
                            "ambiguous_contact",
                        }
                        for blocker in blockers
                    )
                    else "not_required"
                )
        else:
            state, clarification_state = _state_for_blockers(blockers)
        return CRMTaskSuggestion(
            gmail_account_id=receipt.account_id,
            gmail_thread_id=receipt.gmail_thread_id,
            source_type="gmail_message",
            source_scope_key=scope_key,
            source_action_key=_reconciliation_action_key(obligation),
            source_request_id=None,
            duplicate_of_suggestion_id=duplicate_of,
            contact_id=contact_id,
            title=obligation.title,
            description=obligation.description,
            priority=obligation.priority,
            due_at=obligation.due_at,
            task_status="open",
            state=state,
            clarification_state=clarification_state,
            blocker_codes=blockers,
            owner_clarification_pending=owner_clarification_pending,
            task_details_clarification_pending=(
                task_details_clarification_pending
            ),
            contact_resolution_state=(
                "inferred_unique"
                if contact_id is not None
                else (
                    "unresolved"
                    if "ambiguous_contact" in blockers
                    else "not_provided"
                )
            ),
            contact_resolution_hash=(
                contact_resolution_hash(
                    contact_id=contact_id,
                    email=contact_email,
                )
                if contact_id is not None and contact_email is not None
                else None
            ),
            payload_hash=_payload_hash(obligation, contact_id=contact_id),
            application_idempotency_key=None,
            applied_task_id=None,
            model_schema_version=extraction.schema_version,
            obligation_fingerprint=obligation.obligation_fingerprint,
            primary_instance_digest=obligation.identity_instance_digest,
            confidence=obligation.confidence,
            rationale=obligation.rationale,
            version=1,
        )

    @staticmethod
    async def _replay_result(
        *,
        session: AsyncSession,
        attempt: GmailExtractionAttempt,
    ) -> GmailObligationReconciliationResult:
        obligations = list(
            (
                await session.scalars(
                    select(GmailExtractedObligation)
                    .where(
                        GmailExtractedObligation.extraction_attempt_id
                        == attempt.id
                    )
                    .order_by(
                        GmailExtractedObligation.created_at,
                        GmailExtractedObligation.id,
                    )
                )
            ).all()
        )
        source_rows = list(
            (
                await session.execute(
                    select(
                        CRMTaskSuggestionSource.obligation_id,
                        CRMTaskSuggestionSource.suggestion_id,
                    ).where(
                        CRMTaskSuggestionSource.obligation_id.in_(
                            [row.id for row in obligations]
                        )
                    )
                )
            ).all()
        )
        source_by_obligation: dict[UUID, UUID] = {}
        for row in source_rows:
            if row.obligation_id in source_by_obligation:
                raise _fixed_error("gmail_suggestion_source_multiplicity")
            source_by_obligation[row.obligation_id] = row.suggestion_id
        suggestion_ids: list[UUID] = []
        suppressed_obligations: list[GmailExtractedObligation] = []
        for obligation in obligations:
            suggestion_id = obligation.reconciled_suggestion_id
            suppression_id = obligation.reconciled_suppression_id
            if (suggestion_id is None) == (suppression_id is None):
                raise _fixed_error("gmail_obligation_disposition_invalid")
            source_suggestion_id = source_by_obligation.get(obligation.id)
            if suggestion_id is not None:
                if source_suggestion_id != suggestion_id:
                    raise _fixed_error("gmail_obligation_disposition_invalid")
                suggestion_ids.append(suggestion_id)
            else:
                if source_suggestion_id is not None:
                    raise _fixed_error("gmail_obligation_disposition_invalid")
                suppressed_obligations.append(obligation)

        suppressed_action_keys: list[str] = []
        if suppressed_obligations:
            receipt = await session.scalar(
                select(GmailMessageReceipt).where(
                    GmailMessageReceipt.id == attempt.receipt_id
                )
            )
            if receipt is None:
                raise _fixed_error("gmail_obligation_disposition_invalid")
            suppression_ids = {
                row.reconciled_suppression_id
                for row in suppressed_obligations
                if row.reconciled_suppression_id is not None
            }
            suppressions = list(
                (
                    await session.scalars(
                        select(CRMTaskSuggestionSuppression).where(
                            CRMTaskSuggestionSuppression.id.in_(
                                suppression_ids
                            )
                        )
                    )
                ).all()
            )
            suppression_by_id = {row.id: row for row in suppressions}
            if len(suppression_by_id) != len(suppression_ids):
                raise _fixed_error("gmail_obligation_disposition_invalid")
            scope_key = gmail_source_scope_key(
                receipt.account_id,
                receipt.gmail_thread_id,
            )
            for obligation in suppressed_obligations:
                suppression = suppression_by_id.get(
                    obligation.reconciled_suppression_id
                )
                if (
                    suppression is None
                    or suppression.source_type != "gmail_message"
                    or suppression.source_scope_key != scope_key
                    or suppression.source_action_key
                    != _stored_reconciliation_action_key(obligation)
                    or suppression.obligation_fingerprint
                    != obligation.obligation_fingerprint
                    or suppression.identity_instance_digest
                    != obligation.identity_instance_digest
                ):
                    raise _fixed_error(
                        "gmail_obligation_disposition_invalid"
                    )
                suppressed_action_keys.append(obligation.action_key)
        return GmailObligationReconciliationResult(
            attempt_id=attempt.id,
            replayed=True,
            suggestion_ids=tuple(suggestion_ids),
            suppressed_action_keys=tuple(suppressed_action_keys),
        )


__all__ = [
    "GmailExtractionAttemptClaim",
    "GmailExtractionAttemptLimitReached",
    "GmailObligationReconciliationError",
    "GmailObligationReconciliationResult",
    "GmailObligationReconciliationService",
    "GmailReconciliationCandidateLimitReached",
]
