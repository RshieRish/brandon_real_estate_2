"""Exact current-capture ownership for recovered contact child occurrences."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.command_contacts import (
    CRMContactCapturePosition,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
)
from models.command_provenance import CRMEntitySource, CRMSourceRecord
from services.command_provenance import SourceRecordDraft

SourceIdentity = tuple[str, str, str, str, str]

_CHILD_KINDS = frozenset(
    {
        "contact_timeline_event",
        "contact_note",
        "contact_saved_search",
        "contact_task",
        "contact_smart_plan",
        "contact_opportunity",
    }
)
_FIXED_SECTIONS = {
    "contact_timeline_event": "timeline",
    "contact_note": "notes",
    "contact_saved_search": "saved_searches",
    "contact_smart_plan": "smart_plans",
    "contact_opportunity": "opportunities",
}
_TASK_SECTIONS = {
    "to_do": "tasks_to_do",
    "completed": "tasks_completed",
    "archived": "tasks_archived",
}


class ContactOccurrenceOwnershipError(ValueError):
    """Privacy-safe conflict in immutable recovered occurrence ownership."""


@dataclass(frozen=True, slots=True)
class ContactOccurrenceSyncResult:
    observed: int
    created: int
    unchanged: int

    def __post_init__(self) -> None:
        for field_name in ("observed", "created", "unchanged"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.created + self.unchanged != self.observed:
            raise ValueError("occurrence sync counts do not reconcile")


async def sync_contact_occurrence_ownership(
    db: AsyncSession,
    *,
    records: Sequence[SourceRecordDraft],
    persisted_by_identity: Mapping[SourceIdentity, CRMSourceRecord],
    bundle_fingerprint: str,
    parser_version: str,
) -> ContactOccurrenceSyncResult:
    """Own each child by exact provider position/section context, without inference."""
    current = tuple(records)
    if any(not isinstance(record, SourceRecordDraft) for record in current):
        raise ContactOccurrenceOwnershipError("current record snapshot is invalid")
    identities = tuple(record.identity for record in current)
    if len(set(identities)) != len(identities):
        raise ContactOccurrenceOwnershipError("current record snapshot is ambiguous")
    if set(persisted_by_identity) != set(identities):
        raise ContactOccurrenceOwnershipError(
            "persisted current record snapshot does not match current drafts"
        )
    if not isinstance(bundle_fingerprint, str) or len(bundle_fingerprint) != 64:
        raise ContactOccurrenceOwnershipError("bundle fingerprint is invalid")
    if not isinstance(parser_version, str) or not parser_version.strip():
        raise ContactOccurrenceOwnershipError("parser version is invalid")

    persisted_ids: set[int] = set()
    for draft in current:
        row = persisted_by_identity[draft.identity]
        if not isinstance(row, CRMSourceRecord) or type(row.id) is not int:
            raise ContactOccurrenceOwnershipError(
                "persisted current record snapshot is invalid"
            )
        if row.id in persisted_ids:
            raise ContactOccurrenceOwnershipError(
                "persisted current record snapshot reuses a source"
            )
        persisted_ids.add(row.id)
        if row.parser_version != parser_version or draft.parser_version != parser_version:
            raise ContactOccurrenceOwnershipError(
                "persisted current record parser version is inconsistent"
            )
        row_identity = (
            row.source_system,
            row.module,
            row.record_kind,
            row.source_key,
            row.parser_version,
        )
        if row_identity != draft.identity:
            raise ContactOccurrenceOwnershipError(
                "persisted current record snapshot changed identity"
            )

    profile_drafts: dict[str, SourceRecordDraft] = {}
    for draft in current:
        if draft.record_kind != "contact_profile":
            continue
        source_contact_id = _source_contact_id(
            draft.payload.get("source_contact_id")
        )
        if source_contact_id in profile_drafts:
            raise ContactOccurrenceOwnershipError(
                "current contact profile set is ambiguous"
            )
        profile_drafts[source_contact_id] = draft

    children = tuple(record for record in current if record.record_kind in _CHILD_KINDS)
    contexts = tuple((draft, *_child_context(draft)) for draft in children)
    ownership_keys = tuple(
        (source_contact_id, capture_ordinal, section_name, occurrence_ordinal)
        for _, source_contact_id, capture_ordinal, section_name, occurrence_ordinal
        in contexts
    )
    if len(set(ownership_keys)) != len(ownership_keys):
        raise ContactOccurrenceOwnershipError(
            "current child occurrence ownership is ambiguous"
        )
    for _, source_contact_id, _, _, _ in contexts:
        if source_contact_id not in profile_drafts:
            raise ContactOccurrenceOwnershipError(
                "child occurrence is outside the current profile set"
            )

    profile_sources = {
        source_contact_id: persisted_by_identity[draft.identity]
        for source_contact_id, draft in profile_drafts.items()
    }
    profile_source_ids = tuple(row.id for row in profile_sources.values())
    profile_links = (
        await db.scalars(
            select(CRMEntitySource).where(
                CRMEntitySource.source_record_id.in_(profile_source_ids),
                CRMEntitySource.entity_type == "contact",
            )
        )
    ).all()
    links_by_source: dict[int, list[CRMEntitySource]] = {}
    for link in profile_links:
        links_by_source.setdefault(link.source_record_id, []).append(link)
    contact_by_source_id: dict[str, int] = {}
    for source_contact_id, source_record in profile_sources.items():
        links = links_by_source.get(source_record.id, [])
        if len(links) != 1 or type(links[0].entity_id) is not int or links[0].entity_id <= 0:
            raise ContactOccurrenceOwnershipError(
                "current profile has missing or ambiguous contact ownership"
            )
        contact_by_source_id[source_contact_id] = links[0].entity_id

    positions = (
        await db.scalars(
            select(CRMContactCapturePosition).where(
                CRMContactCapturePosition.bundle_fingerprint == bundle_fingerprint
            )
        )
    ).all()
    positions_by_key = {
        (row.source_contact_id, row.capture_ordinal): row for row in positions
    }
    if len(positions_by_key) != len(positions):
        raise ContactOccurrenceOwnershipError(
            "current capture position set is ambiguous"
        )
    required_positions: dict[tuple[str, int], CRMContactCapturePosition] = {}
    for _, source_contact_id, capture_ordinal, _, _ in contexts:
        key = (source_contact_id, capture_ordinal)
        position = positions_by_key.get(key)
        if position is None or position.contact_id != contact_by_source_id[source_contact_id]:
            raise ContactOccurrenceOwnershipError(
                "child occurrence capture position is missing or conflicts"
            )
        required_positions[key] = position

    position_ids = tuple(position.id for position in required_positions.values())
    sections = (
        await db.scalars(
            select(CRMContactSectionCapture).where(
                CRMContactSectionCapture.capture_position_id.in_(position_ids)
            )
        )
    ).all()
    sections_by_key = {
        (row.capture_position_id, row.section_name): row for row in sections
    }
    if len(sections_by_key) != len(sections):
        raise ContactOccurrenceOwnershipError(
            "current section ownership set is ambiguous"
        )

    child_source_ids = tuple(
        persisted_by_identity[draft.identity].id for draft in children
    )
    existing_rows = (
        await db.scalars(
            select(CRMContactSourceOccurrence).where(
                CRMContactSourceOccurrence.source_record_id.in_(child_source_ids)
            )
        )
    ).all()
    existing_by_source: dict[int, list[CRMContactSourceOccurrence]] = {}
    for row in existing_rows:
        existing_by_source.setdefault(row.source_record_id, []).append(row)

    created = 0
    unchanged = 0
    ordered_contexts = sorted(contexts, key=lambda item: item[0].identity)
    for (
        draft,
        source_contact_id,
        capture_ordinal,
        section_name,
        occurrence_ordinal,
    ) in ordered_contexts:
        contact_id = contact_by_source_id[source_contact_id]
        position = required_positions[(source_contact_id, capture_ordinal)]
        section = sections_by_key.get((position.id, section_name))
        if section is None:
            raise ContactOccurrenceOwnershipError(
                "child occurrence section ownership is missing or ambiguous"
            )
        source_record = persisted_by_identity[draft.identity]
        existing = existing_by_source.get(source_record.id, [])
        expected = (contact_id, section.id, source_record.id, occurrence_ordinal)
        if existing:
            actual = tuple(
                (
                    row.contact_id,
                    row.section_capture_id,
                    row.source_record_id,
                    row.occurrence_ordinal,
                )
                for row in existing
            )
            if actual != (expected,):
                raise ContactOccurrenceOwnershipError(
                    "existing child occurrence ownership conflicts"
                )
            unchanged += 1
            continue
        db.add(
            CRMContactSourceOccurrence(
                contact_id=contact_id,
                section_capture_id=section.id,
                source_record_id=source_record.id,
                occurrence_ordinal=occurrence_ordinal,
            )
        )
        created += 1
    await db.flush()
    return ContactOccurrenceSyncResult(
        observed=len(children), created=created, unchanged=unchanged
    )


def _child_context(draft: SourceRecordDraft) -> tuple[str, int, str, int]:
    source_contact_id = _source_contact_id(
        draft.payload.get("source_contact_id")
    )
    capture_ordinal = _capture_ordinal(draft.payload.get("capture_ordinal"))
    occurrence_ordinal = _positive_integer(
        draft.payload.get("occurrence_ordinal"), "occurrence ordinal"
    )
    section_name = draft.payload.get("section_name")
    if not isinstance(section_name, str):
        raise ContactOccurrenceOwnershipError(
            "child occurrence section context is invalid"
        )
    if draft.record_kind == "contact_task":
        state = draft.payload.get("state")
        expected_section = _TASK_SECTIONS.get(state) if isinstance(state, str) else None
    else:
        expected_section = _FIXED_SECTIONS.get(draft.record_kind)
    if expected_section is None or section_name != expected_section:
        raise ContactOccurrenceOwnershipError(
            "child occurrence section context conflicts with its kind"
        )
    return source_contact_id, capture_ordinal, section_name, occurrence_ordinal


def _source_contact_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 24
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ContactOccurrenceOwnershipError(
            "source contact context is invalid"
        )
    return value


def _positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ContactOccurrenceOwnershipError(f"{field_name} context is invalid")
    return value


def _capture_ordinal(value: object) -> int:
    if type(value) is int and value > 0:
        return value
    if (
        isinstance(value, str)
        and len(value) == 7
        and value.isdigit()
        and int(value) > 0
    ):
        return int(value)
    raise ContactOccurrenceOwnershipError("capture ordinal context is invalid")


__all__ = [
    "ContactOccurrenceOwnershipError",
    "ContactOccurrenceSyncResult",
    "sync_contact_occurrence_ownership",
]
