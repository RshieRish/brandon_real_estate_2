"""Body-free authority helpers for reviewable CRM task suggestions."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import exists, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.command import CRMContact
from models.gmail_task_intake import (
    CRMTaskSuggestion,
    GmailExtractedObligation,
)
from schemas.gmail_task_intake import GmailTaskPayload
from services.command_contact_identity import canonical_email
from services.gmail_history_adapter import parse_gmail_provider_id
from services.integration_advisory_locks import (
    contact_identity_transaction_lock,
    transaction_advisory_lock,
)


class CRMTaskSuggestionAuthorityError(RuntimeError):
    """A fixed, body-free failure at the suggestion application boundary."""


def _fixed_authority_error(category: str) -> CRMTaskSuggestionAuthorityError:
    error = CRMTaskSuggestionAuthorityError(category)
    error.__cause__ = None
    error.__context__ = None
    return error


def _canonical_due_at(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("due_at must be timezone-aware")
    utc_value = value.astimezone(timezone.utc)
    return (
        utc_value.isoformat(
            timespec=("microseconds" if utc_value.microsecond else "seconds")
        )
        .replace("+00:00", "Z")
    )


def canonical_task_payload_hash(
    *,
    title: str,
    description: str,
    priority: str,
    due_at: datetime | None,
    contact_id: int | None,
    status: str,
) -> str:
    """Hash exactly the mutable CRM task payload, never source metadata."""
    payload = {
        "contact_id": contact_id,
        "description": description,
        "due_at": _canonical_due_at(due_at),
        "priority": priority,
        "status": status,
        "title": title,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def gmail_source_scope_key(account_id: UUID, gmail_thread_id: str) -> str:
    """Return the stable account/thread suppression and reconciliation scope."""
    if not isinstance(account_id, UUID):
        raise TypeError("account_id must be a UUID")
    try:
        canonical_thread_id = parse_gmail_provider_id(gmail_thread_id)
    except (TypeError, ValueError):
        raise ValueError("gmail_thread_id is invalid") from None
    scope = f"gmail:{account_id}:{canonical_thread_id}"
    if len(scope) > 512:
        raise ValueError("Gmail source scope is too long")
    return scope


def _contact_resolution_hash(*, contact_id: int, email: str) -> str:
    return hashlib.sha256(
        b"sws:crm-contact-resolution:v1\0"
        + str(contact_id).encode("ascii")
        + b"\0"
        + email.encode("utf-8")
    ).hexdigest()


class CRMTaskSuggestionService:
    """Validates suggestion authority without creating a confirmed CRM task."""

    @staticmethod
    def is_current(
        suggestion: CRMTaskSuggestion,
        *,
        expected_version: int,
        expected_payload_hash: str,
    ) -> bool:
        return (
            suggestion.version == expected_version
            and type(expected_payload_hash) is str
            and hmac.compare_digest(
                suggestion.payload_hash,
                expected_payload_hash,
            )
        )

    @staticmethod
    def approval_eligible(suggestion: CRMTaskSuggestion) -> bool:
        return (
            suggestion.state == "pending_review"
            and suggestion.clarification_state == "not_required"
            and not suggestion.blocker_codes
        )

    @staticmethod
    def preview_payload(suggestion: CRMTaskSuggestion) -> GmailTaskPayload:
        return GmailTaskPayload(
            title=suggestion.title,
            description=suggestion.description,
            priority=suggestion.priority,
            due_at=suggestion.due_at,
            contact_id=suggestion.contact_id,
            status=suggestion.task_status,
        )

    @classmethod
    async def task_payload(
        cls,
        *,
        session: AsyncSession,
        suggestion: CRMTaskSuggestion,
        expected_version: int,
        expected_payload_hash: str,
    ) -> GmailTaskPayload:
        authoritative_scope = (
            await session.execute(
                select(
                    CRMTaskSuggestion.gmail_account_id,
                    CRMTaskSuggestion.gmail_thread_id,
                    CRMTaskSuggestion.source_type,
                ).where(CRMTaskSuggestion.id == suggestion.id)
            )
        ).one_or_none()
        if (
            authoritative_scope is None
            or authoritative_scope.source_type != "gmail_message"
            or authoritative_scope.gmail_account_id is None
            or authoritative_scope.gmail_thread_id is None
        ):
            raise _fixed_authority_error("suggestion_authority_invalid")
        await transaction_advisory_lock(
            await session.connection(),
            authoritative_scope.gmail_account_id,
            authoritative_scope.gmail_thread_id,
        )
        current = await session.scalar(
            select(CRMTaskSuggestion)
            .where(
                CRMTaskSuggestion.id == suggestion.id,
                CRMTaskSuggestion.source_type == "gmail_message",
                CRMTaskSuggestion.gmail_account_id
                == authoritative_scope.gmail_account_id,
                CRMTaskSuggestion.gmail_thread_id
                == authoritative_scope.gmail_thread_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if current is None:
            raise _fixed_authority_error("suggestion_authority_invalid")
        recomputed_hash = canonical_task_payload_hash(
            title=current.title,
            description=current.description,
            priority=current.priority,
            due_at=current.due_at,
            contact_id=current.contact_id,
            status=current.task_status,
        )
        if not hmac.compare_digest(current.payload_hash, recomputed_hash):
            raise _fixed_authority_error("suggestion_payload_corrupt")
        if not cls.is_current(
            current,
            expected_version=expected_version,
            expected_payload_hash=expected_payload_hash,
        ):
            raise _fixed_authority_error("suggestion_stale")
        has_live_conflicting_sibling = bool(
            await session.scalar(
                select(
                    exists(
                        select(CRMTaskSuggestion.id)
                        .where(
                            CRMTaskSuggestion.id != current.id,
                            CRMTaskSuggestion.source_type
                            == literal("gmail_message"),
                            CRMTaskSuggestion.gmail_account_id
                            == current.gmail_account_id,
                            CRMTaskSuggestion.gmail_thread_id
                            == current.gmail_thread_id,
                            CRMTaskSuggestion.source_action_key
                            == current.source_action_key,
                            CRMTaskSuggestion.obligation_fingerprint
                            != current.obligation_fingerprint,
                            CRMTaskSuggestion.state.in_(
                                (
                                    "pending_review",
                                    "needs_clarification",
                                    "possible_duplicate",
                                )
                            ),
                        )
                        .limit(1)
                    )
                )
            )
        )
        if (
            current.blocker_codes
            or current.clarification_state != "not_required"
            or has_live_conflicting_sibling
        ):
            raise _fixed_authority_error("suggestion_blocked")
        if current.state != "approved":
            raise _fixed_authority_error("suggestion_not_approved")
        if current.contact_id is not None:
            await cls._require_current_contact_authority(
                session=session,
                suggestion=current,
            )
        return cls.preview_payload(current)

    @staticmethod
    async def _require_current_contact_authority(
        *,
        session: AsyncSession,
        suggestion: CRMTaskSuggestion,
    ) -> None:
        if (
            suggestion.gmail_account_id is None
            or suggestion.gmail_thread_id is None
            or suggestion.contact_id is None
        ):
            raise _fixed_authority_error("contact_authority_changed")
        await contact_identity_transaction_lock(await session.connection())
        selected = await session.scalar(
            select(CRMContact)
            .where(CRMContact.id == suggestion.contact_id)
            .with_for_update()
        )
        selected_email = (
            canonical_email(selected.email) if selected is not None else None
        )
        if (
            selected is None
            or selected_email is None
            or selected.normalized_email != selected_email
            or suggestion.contact_resolution_state
            not in {"inferred_unique", "clarified_unique"}
            or suggestion.contact_resolution_hash is None
            or not hmac.compare_digest(
                suggestion.contact_resolution_hash,
                _contact_resolution_hash(
                    contact_id=selected.id,
                    email=selected_email,
                ),
            )
        ):
            raise _fixed_authority_error("contact_authority_changed")
        if suggestion.contact_resolution_state == "clarified_unique":
            authorized_email = selected_email
        else:
            hint_query = select(GmailExtractedObligation.contact_hint).where(
                GmailExtractedObligation.reconciled_suggestion_id
                == suggestion.id,
                GmailExtractedObligation.contact_hint.is_not(None),
            )
            first_hint = await session.scalar(
                hint_query.order_by(
                    GmailExtractedObligation.contact_hint.asc(),
                    GmailExtractedObligation.id.asc(),
                ).limit(1)
            )
            last_hint = await session.scalar(
                hint_query.order_by(
                    GmailExtractedObligation.contact_hint.desc(),
                    GmailExtractedObligation.id.desc(),
                ).limit(1)
            )
            if (
                first_hint is None
                or last_hint is None
                or first_hint != last_hint
            ):
                raise _fixed_authority_error("contact_authority_changed")
            authorized_email = canonical_email(first_hint)
            if authorized_email is None or authorized_email != selected_email:
                raise _fixed_authority_error("contact_authority_changed")
        candidates = list(
            (
                await session.execute(
                    select(
                        CRMContact.id,
                        CRMContact.email,
                        CRMContact.normalized_email,
                    )
                    .where(CRMContact.normalized_email == authorized_email)
                    .order_by(CRMContact.id)
                    .limit(2)
                    .with_for_update()
                )
            ).all()
        )
        if (
            len(candidates) != 1
            or candidates[0].id != suggestion.contact_id
            or candidates[0].normalized_email != authorized_email
            or canonical_email(candidates[0].email) != authorized_email
        ):
            raise _fixed_authority_error("contact_authority_changed")


__all__ = [
    "CRMTaskSuggestionAuthorityError",
    "CRMTaskSuggestionService",
    "canonical_task_payload_hash",
    "gmail_source_scope_key",
]
