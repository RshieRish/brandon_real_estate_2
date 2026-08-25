"""Transactional storage and retrieval primitives for Sydney durable context."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.sydney_context import (
    AgentConversationEvent,
    AgentConversationEventSegment,
    AgentConversationIdentity,
    AgentConversationSession,
)
from schemas.sydney_context import (
    ContextEventBatchRequest,
    ContextEventBatchResponse,
    ContextEventInput,
)
from services.sydney_context_redaction import redact_content, split_utf8_text


class ContextEventConflict(ValueError):
    """A source key was replayed with non-identical immutable evidence."""


class ContextSessionConflict(ValueError):
    """A Hermes session ID was rebound to a different durable lineage."""


@dataclass(frozen=True, slots=True)
class PreparedEvent:
    source: ContextEventInput
    content: str
    content_sha256: str
    redaction_status: str
    metadata: dict[str, Any]
    segments: tuple[str, ...]
    segment_sha256: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationHash:
    source_rows: tuple[tuple[UUID, str, str], ...]
    count: int
    digest: str


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        raise ValueError("value is not canonical JSON") from None


def canonical_json_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _redact_metadata(
    metadata: dict[str, Any],
    *,
    configured_secrets: Sequence[str],
) -> dict[str, Any]:
    serialized = canonical_json(metadata)
    redacted = redact_content(
        serialized,
        configured_secrets=configured_secrets,
    ).text
    loaded = json.loads(redacted)
    if not isinstance(loaded, dict):
        raise TypeError("event metadata must be an object")
    return loaded


def prepare_event(
    event: ContextEventInput,
    *,
    configured_secrets: Sequence[str] = (),
    segment_chars: int = 16_000,
) -> PreparedEvent:
    content = redact_content(
        event.content,
        configured_secrets=configured_secrets,
    )
    segments = split_utf8_text(content.text, max_chars=segment_chars)
    return PreparedEvent(
        source=event,
        content=content.text,
        content_sha256=content.sha256,
        redaction_status="redacted" if content.changed else "unchanged",
        metadata=_redact_metadata(
            event.metadata,
            configured_secrets=configured_secrets,
        ),
        segments=segments,
        segment_sha256=tuple(
            hashlib.sha256(segment.encode("utf-8")).hexdigest() for segment in segments
        ),
    )


def ordered_reconciliation_hash(
    rows: Sequence[tuple[UUID, str, str]],
) -> ReconciliationHash:
    source_rows = tuple(rows)
    digest = hashlib.sha256(b"sws:sydney-context:reconciliation:v1\0")
    for event_id, event_type, content_sha256 in source_rows:
        digest.update(event_id.bytes)
        digest.update(len(event_type.encode("utf-8")).to_bytes(2, "big"))
        digest.update(event_type.encode("utf-8"))
        digest.update(bytes.fromhex(content_sha256))
    return ReconciliationHash(
        source_rows=source_rows,
        count=len(source_rows),
        digest=digest.hexdigest(),
    )


async def _resolve_identity(
    db: AsyncSession,
    request: ContextEventBatchRequest,
) -> UUID:
    now = datetime.now(UTC)
    candidate_id = uuid4()
    statement = (
        insert(AgentConversationIdentity)
        .values(
            id=candidate_id,
            platform=request.platform,
            external_user_id=request.external_user_id,
            external_chat_id=request.external_chat_id,
            display_label=request.display_label,
            enabled=True,
            retention_mode="indefinite",
            last_seen_at=now,
        )
        .on_conflict_do_update(
            index_elements=[
                AgentConversationIdentity.platform,
                AgentConversationIdentity.external_user_id,
                AgentConversationIdentity.external_chat_id,
            ],
            set_={
                "display_label": request.display_label,
                "last_seen_at": now,
                "updated_at": now,
            },
        )
        .returning(AgentConversationIdentity.id)
    )
    return (await db.execute(statement)).scalar_one()


async def _resolve_session(
    db: AsyncSession,
    request: ContextEventBatchRequest,
    *,
    identity_id: UUID,
) -> UUID:
    parent_session_id: UUID | None = None
    if request.parent_hermes_session_id:
        parent_session_id = await db.scalar(
            select(AgentConversationSession.id).where(
                AgentConversationSession.hermes_session_id
                == request.parent_hermes_session_id
            )
        )
        if parent_session_id is None:
            raise ContextSessionConflict("context_parent_session_missing")

    candidate_id = uuid4()
    inserted_id = (
        await db.execute(
            insert(AgentConversationSession)
            .values(
                id=candidate_id,
                identity_id=identity_id,
                hermes_session_id=request.hermes_session_id,
                logical_conversation_id=request.logical_conversation_id,
                parent_session_id=parent_session_id,
                platform=request.platform,
                continuation_reason=request.continuation_reason,
                model=request.model,
                source_version=request.source_version,
            )
            .on_conflict_do_nothing(
                index_elements=[AgentConversationSession.hermes_session_id]
            )
            .returning(AgentConversationSession.id)
        )
    ).scalar_one_or_none()
    if inserted_id is not None:
        return inserted_id

    existing = (
        await db.scalars(
            select(AgentConversationSession).where(
                AgentConversationSession.hermes_session_id == request.hermes_session_id
            )
        )
    ).one_or_none()
    if existing is None or (
        existing.identity_id != identity_id
        or existing.logical_conversation_id != request.logical_conversation_id
        or existing.platform != request.platform
        or existing.parent_session_id != parent_session_id
    ):
        raise ContextSessionConflict("context_session_replay_conflict")
    return existing.id


def _event_matches(
    existing: AgentConversationEvent,
    prepared: PreparedEvent,
    *,
    session_id: UUID,
) -> bool:
    source = prepared.source
    return (
        existing.session_id == session_id
        and existing.event_type == source.event_type
        and existing.role == source.role
        and existing.tool_name == source.tool_name
        and existing.tool_call_id == source.tool_call_id
        and existing.provider_model == source.provider_model
        and existing.occurred_at == source.occurred_at
        and existing.token_metadata_json == source.token_metadata
        and existing.metadata_json == prepared.metadata
        and existing.content_sha256 == prepared.content_sha256
        and existing.redaction_status == prepared.redaction_status
        and existing.search_text == prepared.content
    )


async def _stored_segment_hashes(
    db: AsyncSession,
    *,
    event_id: UUID,
) -> tuple[str, ...]:
    return tuple(
        (
            await db.scalars(
                select(AgentConversationEventSegment.content_sha256)
                .where(AgentConversationEventSegment.event_id == event_id)
                .order_by(AgentConversationEventSegment.ordinal)
            )
        ).all()
    )


async def ingest_event_batch(
    db: AsyncSession,
    request: ContextEventBatchRequest,
    *,
    configured_secrets: Sequence[str] = (),
    segment_chars: int = 16_000,
) -> ContextEventBatchResponse:
    if len(request.events) > 100:
        raise ValueError("context_event_batch_too_large")
    identity_id = await _resolve_identity(db, request)
    session_id = await _resolve_session(db, request, identity_id=identity_id)
    inserted_count = 0
    replayed_count = 0
    event_ids: list[UUID] = []

    for event in request.events:
        prepared = prepare_event(
            event,
            configured_secrets=configured_secrets,
            segment_chars=segment_chars,
        )
        candidate_id = uuid4()
        inserted_id = (
            await db.execute(
                insert(AgentConversationEvent)
                .values(
                    id=candidate_id,
                    identity_id=identity_id,
                    session_id=session_id,
                    source_event_key=event.source_event_key,
                    event_type=event.event_type,
                    role=event.role,
                    tool_name=event.tool_name,
                    tool_call_id=event.tool_call_id,
                    provider_model=event.provider_model,
                    occurred_at=event.occurred_at,
                    token_metadata_json=event.token_metadata,
                    metadata_json=prepared.metadata,
                    content_sha256=prepared.content_sha256,
                    redaction_status=prepared.redaction_status,
                    search_text=prepared.content,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        AgentConversationEvent.identity_id,
                        AgentConversationEvent.source_event_key,
                    ]
                )
                .returning(AgentConversationEvent.id)
            )
        ).scalar_one_or_none()

        if inserted_id is not None:
            db.add_all(
                [
                    AgentConversationEventSegment(
                        event_id=inserted_id,
                        ordinal=ordinal,
                        content=content,
                        content_sha256=prepared.segment_sha256[ordinal],
                    )
                    for ordinal, content in enumerate(prepared.segments)
                ]
            )
            inserted_count += 1
            event_ids.append(inserted_id)
            continue

        existing = (
            await db.scalars(
                select(AgentConversationEvent).where(
                    AgentConversationEvent.identity_id == identity_id,
                    AgentConversationEvent.source_event_key == event.source_event_key,
                )
            )
        ).one()
        if not _event_matches(existing, prepared, session_id=session_id):
            raise ContextEventConflict("context_event_replay_conflict")
        if (
            await _stored_segment_hashes(db, event_id=existing.id)
            != prepared.segment_sha256
        ):
            raise ContextEventConflict("context_event_replay_conflict")
        replayed_count += 1
        event_ids.append(existing.id)

    if inserted_count:
        await db.execute(
            update(AgentConversationSession)
            .where(AgentConversationSession.id == session_id)
            .values(
                source_event_count=(
                    AgentConversationSession.source_event_count + inserted_count
                ),
                updated_at=datetime.now(UTC),
            )
        )
    await db.flush()
    return ContextEventBatchResponse(
        identity_id=identity_id,
        session_id=session_id,
        logical_conversation_id=request.logical_conversation_id,
        event_ids=event_ids,
        inserted_count=inserted_count,
        replayed_count=replayed_count,
    )


async def reconcile_session(
    db: AsyncSession,
    *,
    identity_id: UUID,
    hermes_session_id: str,
) -> ReconciliationHash:
    session = (
        await db.scalars(
            select(AgentConversationSession).where(
                AgentConversationSession.identity_id == identity_id,
                AgentConversationSession.hermes_session_id == hermes_session_id,
            )
        )
    ).one()
    rows = tuple(
        (
            await db.execute(
                select(
                    AgentConversationEvent.id,
                    AgentConversationEvent.event_type,
                    AgentConversationEvent.content_sha256,
                )
                .where(AgentConversationEvent.session_id == session.id)
                .order_by(
                    AgentConversationEvent.occurred_at,
                    AgentConversationEvent.id,
                )
            )
        ).all()
    )
    result = ordered_reconciliation_hash(rows)
    await db.execute(
        update(AgentConversationSession)
        .where(AgentConversationSession.id == session.id)
        .values(
            source_event_count=result.count,
            reconciliation_hash=result.digest,
            updated_at=datetime.now(UTC),
        )
    )
    await db.flush()
    return result


__all__ = [
    "ContextEventConflict",
    "ContextSessionConflict",
    "PreparedEvent",
    "ReconciliationHash",
    "canonical_json",
    "canonical_json_hash",
    "ingest_event_batch",
    "ordered_reconciliation_hash",
    "prepare_event",
    "reconcile_session",
]
