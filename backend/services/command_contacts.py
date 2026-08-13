"""Framework-neutral query and mutation services for Command Contacts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import NoReturn

from sqlalchemy import (
    Select,
    and_,
    case,
    exists,
    extract,
    false,
    func,
    literal,
    not_,
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from models.command import (
    CRMActivity,
    CRMArchiveArtifact,
    CRMContact,
    CRMContactTag,
    CRMNote,
    CRMOpportunity,
    CRMOpportunityContact,
    CRMSavedSearch,
    CRMSmartPlan,
    CRMSmartPlanEnrollment,
    CRMTag,
    CRMTask,
)
from models.command_contacts import (
    CRMContactAddress,
    CRMContactAuditEvent,
    CRMContactCapturePosition,
    CRMContactMethod,
    CRMContactOwnership,
    CRMContactProfile,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
    CRMContactTimelineEvent,
)
from models.command_provenance import (
    CRMEntitySource,
    CRMSourceRecord,
    CRMSourceRecordArtifact,
)
from models.lead import Lead
from services.command_contact_contracts import (
    CONTACT_TOUCH_ACTIVITY_KINDS,
    UNSET,
    CaptureQualityValue,
    ContactActorValue,
    ContactAddressValue,
    ContactArtifactMetadata,
    ContactBulkAddTag,
    ContactBulkCommand,
    ContactBulkRemoveTag,
    ContactBulkResult,
    ContactBulkSetStage,
    ContactCaptureEvidence,
    ContactCelebrationRow,
    ContactCelebrations,
    ContactCelebrationValue,
    ContactCreateCommand,
    ContactDetail,
    ContactDirectoryFilters,
    ContactDirectoryPage,
    ContactDirectoryRow,
    ContactEvidence,
    ContactLegacySyncResult,
    ContactMaterialized,
    ContactMutationResult,
    ContactNeighbors,
    ContactNoteCreateCommand,
    ContactNoteOccurrence,
    ContactOpportunityOccurrence,
    ContactOriginFilter,
    ContactRecoveredProfile,
    ContactSavedSearchCreateCommand,
    ContactSavedSearchOccurrence,
    ContactSavedSearchValue,
    ContactSection,
    ContactSectionEvidence,
    ContactSectionPage,
    ContactSmartPlanOccurrence,
    ContactSmartView,
    ContactSortKey,
    ContactSourceFilter,
    ContactSourceMetadata,
    ContactSourceOnly,
    ContactTagValue,
    ContactTaskOccurrence,
    ContactUpdateCommand,
    ContactWorkspaceSummary,
    SavedSearchDeletionResult,
    SortDirection,
    WorkspaceMutationResult,
    canonical_contact_audit_json,
    canonical_workspace_saved_search_activity_json,
)
from services.command_contact_timeline import (
    ContactNotFound as TimelineContactNotFound,
)
from services.command_contact_timeline import (
    ContactTimelineIntegrityError,
    count_contact_bookings,
)


class ContactDirectoryError(Exception):
    """Base class for safe, framework-neutral Contacts service failures."""


class ContactNotFound(ContactDirectoryError, LookupError):
    """The requested internal contact does not exist."""


class ContactNotInDirectory(ContactDirectoryError):
    """The contact is outside the requested filtered directory universe."""


class ContactDataIntegrityError(ContactDirectoryError, RuntimeError):
    """Stored Contacts evidence is internally contradictory."""


class ContactLinkConflict(ContactDataIntegrityError):
    """A source link does not resolve to one compatible internal entity."""


class ContactSectionUnsupported(ValueError):
    """The requested section has a dedicated service instead."""


_CONTACT_MUTATION_FIELDS = (
    "first_name",
    "last_name",
    "email",
    "phone",
    "stage",
    "birthday",
    "anniversary",
)


def _validated_actor_subject(actor_subject: object) -> str:
    if (
        type(actor_subject) is not str
        or not 1 <= len(actor_subject) <= 255
        or not actor_subject.isascii()
        or not actor_subject.isdigit()
        or int(actor_subject) <= 0
        or actor_subject != str(int(actor_subject))
    ):
        raise ValueError("administrator subject is invalid")
    return actor_subject


def _contact_audit_fields(contact: CRMContact) -> dict[str, object]:
    return {
        field_name: getattr(contact, field_name)
        for field_name in _CONTACT_MUTATION_FIELDS
    }


def _compatibility_activity(
    *, contact_id: int, kind: str, summary: str
) -> CRMActivity:
    return CRMActivity(
        contact_id=contact_id,
        kind=kind,
        summary=summary,
        source_record_id=None,
        metadata_json="{}",
    )


def _contact_audit_event(
    *,
    contact_id: int,
    actor_subject: str,
    action: str,
    before_json: str,
    after_json: str,
) -> CRMContactAuditEvent:
    return CRMContactAuditEvent(
        contact_id=contact_id,
        actor_subject=actor_subject,
        action=action,
        before_json=before_json,
        after_json=after_json,
    )


def _safe_not_found() -> NoReturn:
    raise ContactNotFound("contact does not exist")


def _recovered_contact_exists() -> ColumnElement[bool]:
    return exists(
        select(literal(1))
        .select_from(CRMEntitySource)
        .join(
            CRMSourceRecord,
            CRMSourceRecord.id == CRMEntitySource.source_record_id,
        )
        .where(
            CRMEntitySource.entity_type == "contact",
            CRMEntitySource.entity_id == CRMContact.id,
            CRMSourceRecord.source_system == "kw_command",
            CRMSourceRecord.module == "contacts",
            CRMSourceRecord.record_kind == "contact_profile",
        )
    )


def _literal_like_pattern(value: str) -> str:
    escaped = value.casefold().replace("\\", "\\\\")
    escaped = escaped.replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _explicit_month_predicate(
    *,
    internal_column,
    recovered_month_column,
    recovered_day_column,
    recovered_year_column,
    recovered_year_quality_column,
    month: int,
) -> ColumnElement[bool]:
    return or_(
        extract("month", internal_column) == month,
        and_(
            internal_column.is_(None),
            recovered_month_column == month,
            _valid_recovered_celebration_predicate(
                month_column=recovered_month_column,
                day_column=recovered_day_column,
                year_column=recovered_year_column,
                quality_column=recovered_year_quality_column,
            ),
        ),
    )


def _valid_recovered_celebration_predicate(
    *,
    month_column,
    day_column,
    year_column,
    quality_column,
) -> ColumnElement[bool]:
    max_day = case(
        (month_column.in_((1, 3, 5, 7, 8, 10, 12)), 31),
        (month_column.in_((4, 6, 9, 11)), 30),
        (month_column == 2, 29),
        else_=0,
    )
    leap_year = or_(
        year_column % 400 == 0,
        and_(year_column % 4 == 0, year_column % 100 != 0),
    )
    common = and_(
        month_column.between(1, 12),
        day_column >= 1,
        day_column <= max_day,
    )
    verified = and_(
        quality_column == "verified",
        year_column.between(1, 9999),
        or_(month_column != 2, day_column != 29, leap_year),
    )
    yearless = quality_column.in_(("yearless", "sentinel"))
    return and_(common, or_(verified, yearless))


def _never_contacted_predicate() -> ColumnElement[bool]:
    latest_position_id = (
        select(CRMContactCapturePosition.id)
        .where(CRMContactCapturePosition.contact_id == CRMContact.id)
        .order_by(
            CRMContactCapturePosition.captured_at.is_(None).asc(),
            CRMContactCapturePosition.captured_at.desc(),
            CRMContactCapturePosition.id.desc(),
        )
        .limit(1)
        .correlate(CRMContact)
        .scalar_subquery()
    )
    authoritative_empty_timeline = exists(
        select(literal(1))
        .select_from(CRMContactSectionCapture)
        .where(
            CRMContactSectionCapture.capture_position_id == latest_position_id,
            CRMContactSectionCapture.section_name == "timeline",
            CRMContactSectionCapture.capture_quality
            == CaptureQualityValue.COMPLETE.value,
            CRMContactSectionCapture.is_empty.is_(True),
            CRMContactSectionCapture.row_count == 0,
            CRMContactSectionCapture.limitations_json == "[]",
        )
    )
    recovered_event = exists(
        select(literal(1))
        .select_from(CRMContactTimelineEvent)
        .where(CRMContactTimelineEvent.contact_id == CRMContact.id)
    )
    mirrored_activity = exists(
        select(literal(1))
        .select_from(CRMContactTimelineEvent)
        .where(
            CRMContactTimelineEvent.contact_id == CRMActivity.contact_id,
            CRMContactTimelineEvent.source_record_id == CRMActivity.source_record_id,
        )
        .correlate(CRMActivity)
    )
    non_mirrored_touch = exists(
        select(literal(1))
        .select_from(CRMActivity)
        .where(
            CRMActivity.contact_id == CRMContact.id,
            CRMActivity.kind.in_(tuple(sorted(CONTACT_TOUCH_ACTIVITY_KINDS))),
            or_(
                CRMActivity.source_record_id.is_(None),
                not_(mirrored_activity),
            ),
        )
    )
    return and_(
        func.lower(func.trim(CRMContact.stage)) == "lead",
        authoritative_empty_timeline,
        CRMContactProfile.last_contacted_at.is_(None),
        not_(recovered_event),
        not_(non_mirrored_touch),
    )


def _directory_predicates(
    filters: ContactDirectoryFilters,
    *,
    now: datetime,
) -> tuple[ColumnElement[bool], ...]:
    recovered = _recovered_contact_exists()
    lead_backed = CRMContact.lead_id.is_not(None)
    internal_only = and_(not_(recovered), CRMContact.lead_id.is_(None))
    predicates: list[ColumnElement[bool]] = []

    if filters.query is not None:
        pattern = _literal_like_pattern(filters.query)
        method_match = exists(
            select(literal(1))
            .select_from(CRMContactMethod)
            .where(
                CRMContactMethod.contact_id == CRMContact.id,
                func.lower(CRMContactMethod.normalized_value).like(
                    pattern, escape="\\"
                ),
            )
        )
        predicates.append(
            or_(
                func.lower(CRMContact.first_name).like(pattern, escape="\\"),
                func.lower(CRMContact.last_name).like(pattern, escape="\\"),
                func.lower(CRMContact.normalized_email).like(pattern, escape="\\"),
                func.lower(CRMContactProfile.legal_name).like(pattern, escape="\\"),
                func.lower(CRMContactProfile.preferred_name).like(pattern, escape="\\"),
                func.lower(CRMContactProfile.company).like(pattern, escape="\\"),
                func.lower(CRMContactProfile.title).like(pattern, escape="\\"),
                method_match,
            )
        )
    if filters.stage is not None:
        predicates.append(CRMContact.stage == filters.stage)
    if filters.owner_actor_id is not None:
        predicates.append(
            exists(
                select(literal(1))
                .select_from(CRMContactOwnership)
                .where(
                    CRMContactOwnership.contact_id == CRMContact.id,
                    CRMContactOwnership.role == "owner",
                    CRMContactOwnership.provider_actor_id == filters.owner_actor_id,
                )
            )
        )
    if filters.assignee_actor_id is not None:
        predicates.append(
            exists(
                select(literal(1))
                .select_from(CRMContactOwnership)
                .where(
                    CRMContactOwnership.contact_id == CRMContact.id,
                    CRMContactOwnership.role == "assignee",
                    CRMContactOwnership.provider_actor_id == filters.assignee_actor_id,
                )
            )
        )
    predicates.extend(
        exists(
            select(literal(1))
            .select_from(CRMContactTag)
            .where(
                CRMContactTag.contact_id == CRMContact.id,
                CRMContactTag.tag_id == tag_id,
            )
        )
        for tag_id in filters.tag_ids
    )

    if filters.sources:
        source_options: list[ColumnElement[bool]] = []
        if ContactSourceFilter.KW_COMMAND in filters.sources:
            source_options.append(recovered)
        if ContactSourceFilter.LEGACY_LEAD in filters.sources:
            source_options.append(lead_backed)
        if ContactSourceFilter.INTERNAL_CRM in filters.sources:
            source_options.append(internal_only)
        predicates.append(or_(*source_options))
    if filters.origins:
        origin_options: list[ColumnElement[bool]] = []
        if ContactOriginFilter.RECOVERED in filters.origins:
            origin_options.append(recovered)
        if ContactOriginFilter.LEAD_BACKED in filters.origins:
            origin_options.append(lead_backed)
        if ContactOriginFilter.LEGACY_ONLY in filters.origins:
            origin_options.append(and_(lead_backed, not_(recovered)))
        if ContactOriginFilter.INTERNAL_ONLY in filters.origins:
            origin_options.append(internal_only)
        predicates.append(or_(*origin_options))

    if filters.health_min is not None:
        predicates.append(CRMContactProfile.health_score >= filters.health_min)
    if filters.health_max is not None:
        predicates.append(CRMContactProfile.health_score <= filters.health_max)
    if filters.birthday_month is not None:
        predicates.append(
            _explicit_month_predicate(
                internal_column=CRMContact.birthday,
                recovered_month_column=CRMContactProfile.birth_month,
                recovered_day_column=CRMContactProfile.birth_day,
                recovered_year_column=CRMContactProfile.birth_year,
                recovered_year_quality_column=(CRMContactProfile.birth_year_quality),
                month=filters.birthday_month,
            )
        )
    if filters.anniversary_month is not None:
        predicates.append(
            _explicit_month_predicate(
                internal_column=CRMContact.anniversary,
                recovered_month_column=CRMContactProfile.anniversary_month,
                recovered_day_column=CRMContactProfile.anniversary_day,
                recovered_year_column=CRMContactProfile.anniversary_year,
                recovered_year_quality_column=(
                    CRMContactProfile.anniversary_year_quality
                ),
                month=filters.anniversary_month,
            )
        )

    if filters.smart_view is ContactSmartView.NEVER_CONTACTED:
        predicates.append(_never_contacted_predicate())
    elif filters.smart_view is ContactSmartView.RECENTLY_ACTIVE:
        predicates.extend(
            (
                CRMContactProfile.last_interaction_at >= now - timedelta(days=30),
                CRMContactProfile.last_interaction_at <= now,
            )
        )
    elif filters.smart_view is ContactSmartView.BIRTHDAYS_THIS_MONTH:
        predicates.append(
            _explicit_month_predicate(
                internal_column=CRMContact.birthday,
                recovered_month_column=CRMContactProfile.birth_month,
                recovered_day_column=CRMContactProfile.birth_day,
                recovered_year_column=CRMContactProfile.birth_year,
                recovered_year_quality_column=(CRMContactProfile.birth_year_quality),
                month=now.month,
            )
        )
    elif filters.smart_view is ContactSmartView.ANNIVERSARIES_THIS_MONTH:
        predicates.append(
            _explicit_month_predicate(
                internal_column=CRMContact.anniversary,
                recovered_month_column=CRMContactProfile.anniversary_month,
                recovered_day_column=CRMContactProfile.anniversary_day,
                recovered_year_column=CRMContactProfile.anniversary_year,
                recovered_year_quality_column=(
                    CRMContactProfile.anniversary_year_quality
                ),
                month=now.month,
            )
        )
    return tuple(predicates)


def _direction(expression, direction: SortDirection):
    return expression.asc() if direction is SortDirection.ASC else expression.desc()


def _directory_order(filters: ContactDirectoryFilters) -> tuple:
    last_name = func.lower(CRMContact.last_name)
    first_name = func.lower(CRMContact.first_name)
    direction = filters.direction
    if filters.sort is ContactSortKey.NAME:
        return (
            _direction(last_name, direction),
            _direction(first_name, direction),
            _direction(CRMContact.id, direction),
        )
    primary = {
        ContactSortKey.STAGE: func.lower(CRMContact.stage),
        ContactSortKey.HEALTH_SCORE: CRMContactProfile.health_score,
        ContactSortKey.LAST_CONTACTED_AT: CRMContactProfile.last_contacted_at,
        ContactSortKey.LAST_INTERACTION_AT: CRMContactProfile.last_interaction_at,
        ContactSortKey.CREATED_AT: CRMContact.created_at,
        ContactSortKey.UPDATED_AT: CRMContact.updated_at,
    }[filters.sort]
    return (
        case((primary.is_(None), 1), else_=0).asc(),
        _direction(primary, direction),
        _direction(last_name, direction),
        _direction(first_name, direction),
        _direction(CRMContact.id, direction),
    )


def _normalize_now(now: datetime) -> datetime:
    if not isinstance(now, datetime):
        raise TypeError("now must be a datetime")
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _base_directory_select(
    filters: ContactDirectoryFilters,
    *,
    now: datetime,
) -> Select:
    return (
        select(CRMContact)
        .outerjoin(
            CRMContactProfile,
            CRMContactProfile.contact_id == CRMContact.id,
        )
        .where(*_directory_predicates(filters, now=now))
    )


def _celebration(
    contact: CRMContact,
    profile: CRMContactProfile | None,
    *,
    kind: str,
) -> ContactCelebrationValue | None:
    internal = contact.birthday if kind == "birthday" else contact.anniversary
    if internal is not None:
        return ContactCelebrationValue(
            month=internal.month,
            day=internal.day,
            year=internal.year,
            year_quality="verified",
            origin="internal_crm",
        )
    if profile is None:
        return None
    return _recovered_celebration(profile, kind=kind)


def _recovered_celebration(
    profile: CRMContactProfile,
    *,
    kind: str,
) -> ContactCelebrationValue | None:
    if kind == "birthday":
        month = profile.birth_month
        day = profile.birth_day
        year = profile.birth_year
        quality = profile.birth_year_quality
    else:
        month = profile.anniversary_month
        day = profile.anniversary_day
        year = profile.anniversary_year
        quality = profile.anniversary_year_quality
    if quality not in {"verified", "yearless", "sentinel"}:
        return None
    validation_year = year if quality == "verified" else 2000
    if validation_year is None:
        return None
    try:
        date(validation_year, month, day)
    except (TypeError, ValueError):
        return None
    if quality in {"yearless", "sentinel"}:
        year = None
    return ContactCelebrationValue(
        month=month,
        day=day,
        year=year,
        year_quality=quality,  # type: ignore[arg-type]
        origin="recovered",
    )


def _origin_values(*, recovered: bool, lead_backed: bool):
    values: list[ContactOriginFilter] = []
    if recovered:
        values.append(ContactOriginFilter.RECOVERED)
    if lead_backed:
        values.append(ContactOriginFilter.LEAD_BACKED)
    if lead_backed and not recovered:
        values.append(ContactOriginFilter.LEGACY_ONLY)
    if not lead_backed and not recovered:
        values.append(ContactOriginFilter.INTERNAL_ONLY)
    return tuple(sorted(values, key=lambda value: value.value))


def _source_values(*, recovered: bool, lead_backed: bool):
    values: list[ContactSourceFilter] = []
    if recovered:
        values.append(ContactSourceFilter.KW_COMMAND)
    if lead_backed:
        values.append(ContactSourceFilter.LEGACY_LEAD)
    if not lead_backed and not recovered:
        values.append(ContactSourceFilter.INTERNAL_CRM)
    return tuple(sorted(values, key=lambda value: value.value))


async def _page_associations(
    db: AsyncSession,
    contact_ids: Sequence[int],
):
    if not contact_ids:
        return {}, {}, {}, {}
    profiles = {
        row.contact_id: row
        for row in (
            await db.scalars(
                select(CRMContactProfile).where(
                    CRMContactProfile.contact_id.in_(contact_ids)
                )
            )
        ).all()
    }
    methods: dict[int, list[CRMContactMethod]] = defaultdict(list)
    for row in (
        await db.scalars(
            select(CRMContactMethod)
            .where(CRMContactMethod.contact_id.in_(contact_ids))
            .order_by(
                CRMContactMethod.contact_id,
                CRMContactMethod.is_primary.desc(),
                CRMContactMethod.id,
            )
        )
    ).all():
        methods[row.contact_id].append(row)
    ownerships: dict[int, list[CRMContactOwnership]] = defaultdict(list)
    for row in (
        await db.scalars(
            select(CRMContactOwnership)
            .where(CRMContactOwnership.contact_id.in_(contact_ids))
            .order_by(
                CRMContactOwnership.contact_id,
                CRMContactOwnership.role,
                CRMContactOwnership.is_primary.desc(),
                CRMContactOwnership.id,
            )
        )
    ).all():
        ownerships[row.contact_id].append(row)
    tags: dict[int, list[CRMTag]] = defaultdict(list)
    for contact_id, tag in (
        await db.execute(
            select(CRMContactTag.contact_id, CRMTag)
            .join(CRMTag, CRMTag.id == CRMContactTag.tag_id)
            .where(CRMContactTag.contact_id.in_(contact_ids))
            .order_by(
                CRMContactTag.contact_id,
                func.lower(CRMTag.name),
                CRMTag.id,
            )
        )
    ).all():
        tags[contact_id].append(tag)
    return profiles, methods, ownerships, tags


def _method_value(methods: Sequence[CRMContactMethod], kind: str) -> str | None:
    for method in methods:
        if method.kind == kind:
            return method.raw_value or method.normalized_value
    return None


def _actor_value(
    ownerships: Sequence[CRMContactOwnership], role: str
) -> ContactActorValue | None:
    for row in ownerships:
        if row.role == role:
            return ContactActorValue(
                role=role,  # type: ignore[arg-type]
                provider_actor_id=row.provider_actor_id,
                display_name=row.display_name,
            )
    return None


def _directory_row(
    contact: CRMContact,
    *,
    profile: CRMContactProfile | None,
    methods: Sequence[CRMContactMethod],
    ownerships: Sequence[CRMContactOwnership],
    tags: Sequence[CRMTag],
    recovered: bool,
) -> ContactDirectoryRow:
    lead_backed = contact.lead_id is not None
    return ContactDirectoryRow(
        id=contact.id,
        first_name=contact.first_name,
        last_name=contact.last_name,
        display_name=f"{contact.first_name} {contact.last_name}".strip(),
        primary_email=contact.email or _method_value(methods, "email"),
        primary_phone=contact.phone or _method_value(methods, "phone"),
        stage=contact.stage,
        lead_backed=lead_backed,
        origins=_origin_values(recovered=recovered, lead_backed=lead_backed),
        sources=_source_values(recovered=recovered, lead_backed=lead_backed),
        health_score=profile.health_score if profile else None,
        last_contacted_at=profile.last_contacted_at if profile else None,
        last_interaction_at=profile.last_interaction_at if profile else None,
        owner=_actor_value(ownerships, "owner"),
        assignee=_actor_value(ownerships, "assignee"),
        tags=tuple(ContactTagValue(id=tag.id, name=tag.name) for tag in tags),
        birthday=_celebration(contact, profile, kind="birthday"),
        anniversary=_celebration(contact, profile, kind="anniversary"),
        evidence_quality=None,
    )


async def list_contacts(
    db: AsyncSession,
    filters: ContactDirectoryFilters,
    *,
    now: datetime,
) -> ContactDirectoryPage:
    """Return one deterministic page from the combined internal directory."""
    if not isinstance(filters, ContactDirectoryFilters):
        raise TypeError("filters must be ContactDirectoryFilters")
    normalized_now = _normalize_now(now)
    predicates = _directory_predicates(filters, now=normalized_now)
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(CRMContact)
            .outerjoin(
                CRMContactProfile,
                CRMContactProfile.contact_id == CRMContact.id,
            )
            .where(*predicates)
        )
        or 0
    )
    contacts = (
        await db.scalars(
            _base_directory_select(filters, now=normalized_now)
            .order_by(*_directory_order(filters))
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )
    ).all()
    contact_ids = tuple(contact.id for contact in contacts)
    profiles, methods, ownerships, tags = await _page_associations(db, contact_ids)
    recovered_ids = set(
        await db.scalars(
            select(CRMEntitySource.entity_id)
            .join(
                CRMSourceRecord,
                CRMSourceRecord.id == CRMEntitySource.source_record_id,
            )
            .where(
                CRMEntitySource.entity_type == "contact",
                CRMEntitySource.entity_id.in_(contact_ids),
                CRMSourceRecord.source_system == "kw_command",
                CRMSourceRecord.module == "contacts",
                CRMSourceRecord.record_kind == "contact_profile",
            )
        )
        if contact_ids
        else ()
    )
    rows: list[ContactDirectoryRow] = []
    for contact in contacts:
        profile = profiles.get(contact.id)
        recovered = contact.id in recovered_ids
        contact_methods = methods.get(contact.id, ())
        contact_ownerships = ownerships.get(contact.id, ())
        rows.append(
            _directory_row(
                contact,
                profile=profile,
                methods=contact_methods,
                ownerships=contact_ownerships,
                tags=tags.get(contact.id, ()),
                recovered=recovered,
            )
        )
    page_count = (total + filters.page_size - 1) // filters.page_size
    return ContactDirectoryPage(
        rows=tuple(rows),
        total=total,
        page=filters.page,
        page_size=filters.page_size,
        page_count=page_count,
        sort=filters.sort,
        direction=filters.direction,
    )


async def get_contact_detail(
    db: AsyncSession,
    contact_id: int,
) -> ContactDetail:
    """Hydrate one contact detail from internal and recovered normalized rows."""
    if type(contact_id) is not int or contact_id <= 0:
        _safe_not_found()
    with db.no_autoflush:
        contact = await db.get(CRMContact, contact_id)
        if contact is None:
            _safe_not_found()
        profiles, methods, ownerships, tags = await _page_associations(
            db, (contact.id,)
        )
        profile = profiles.get(contact.id)
        requested_link = aliased(CRMEntitySource)
        contributing_link = aliased(CRMEntitySource)
        profile_link_rows = (
            await db.execute(
                select(requested_link, CRMSourceRecord, contributing_link)
                .select_from(requested_link)
                .outerjoin(
                    CRMSourceRecord,
                    CRMSourceRecord.id == requested_link.source_record_id,
                )
                .outerjoin(
                    contributing_link,
                    contributing_link.source_record_id
                    == requested_link.source_record_id,
                )
                .where(
                    requested_link.entity_type == "contact",
                    requested_link.entity_id == contact.id,
                )
                .order_by(requested_link.id, contributing_link.id)
            )
        ).all()
        exact_source_links: dict[int, set[int]] = defaultdict(set)
        invalid_candidate = False
        for link, source, contributing in profile_link_rows:
            exact_domain = (
                source is not None
                and source.source_system == "kw_command"
                and source.module == "contacts"
                and source.record_kind == "contact_profile"
            )
            if exact_domain:
                exact_source_links[link.id].add(contributing.id)
            else:
                invalid_candidate = True
        recovered = bool(exact_source_links)
        if (
            invalid_candidate
            or (profile is not None) != recovered
            or any(
                contributing_ids != {link_id}
                for link_id, contributing_ids in exact_source_links.items()
            )
        ):
            raise ContactDataIntegrityError("recovered profile ownership is invalid")
        addresses = (
            await db.scalars(
                select(CRMContactAddress)
                .where(CRMContactAddress.contact_id == contact.id)
                .order_by(
                    CRMContactAddress.is_primary.desc(),
                    CRMContactAddress.id,
                )
            )
        ).all()
    contact_ownerships = ownerships.get(contact.id, ())
    role_rank = {"owner": 0, "assignee": 1, "collaborator": 2}
    ordered_ownerships = sorted(
        contact_ownerships,
        key=lambda row: (
            role_rank[row.role],
            not row.is_primary,
            row.id,
        ),
    )
    recovered_profile = None
    if profile is not None:
        recovered_profile = ContactRecoveredProfile(
            legal_name=profile.legal_name,
            preferred_name=profile.preferred_name,
            description=profile.description,
            company=profile.company,
            title=profile.title,
            lead_source=profile.lead_source,
            account_name=profile.account_name,
            birthday=_recovered_celebration(profile, kind="birthday"),
            anniversary=_recovered_celebration(profile, kind="anniversary"),
        )
    return ContactDetail(
        contact=_directory_row(
            contact,
            profile=profile,
            methods=methods.get(contact.id, ()),
            ownerships=contact_ownerships,
            tags=tags.get(contact.id, ()),
            recovered=recovered,
        ),
        lead_id=contact.lead_id,
        recovered_profile=recovered_profile,
        addresses=tuple(
            ContactAddressValue(
                id=row.id,
                address_type=row.address_type,
                formatted=row.formatted,
                latitude=row.latitude,
                longitude=row.longitude,
                source_record_id=row.source_record_id,
            )
            for row in addresses
        ),
        ownership=tuple(
            ContactActorValue(
                role=row.role,  # type: ignore[arg-type]
                provider_actor_id=row.provider_actor_id,
                display_name=row.display_name,
            )
            for row in ordered_ownerships
        ),
        tags=tuple(
            ContactTagValue(id=tag.id, name=tag.name)
            for tag in tags.get(contact.id, ())
        ),
    )


_SECTION_RECORD_KINDS = {
    "opportunities": "contact_opportunity",
    "smart_plans": "contact_smart_plan",
    "notes": "contact_note",
    "saved_searches": "contact_saved_search",
    "tasks_to_do": "contact_task",
    "tasks_completed": "contact_task",
    "tasks_archived": "contact_task",
}
_SECTION_ENTITY_TYPES = {
    "opportunities": "opportunity",
    "smart_plans": "smart_plan",
    "notes": "note",
    "saved_searches": "saved_search",
    "tasks_to_do": "task",
    "tasks_completed": "task",
    "tasks_archived": "task",
}
_SECTION_SOURCE_KEY_DOMAIN = b"command.contact.section-source-key.v1\0"
_RFC3339_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
_TASK_SECTION_STATES = {
    ContactSection.TASKS_TO_DO: "to_do",
    ContactSection.TASKS_COMPLETED: "completed",
    ContactSection.TASKS_ARCHIVED: "archived",
}
_CONTACT_PROVIDER_ID_RE = re.compile(r"[0-9a-f]{24}")
_ARTIFACT_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_EVIDENCE_LEVELS = {
    "observed_record",
    "rendered_occurrence",
    "displayed_aggregate",
}


async def _contact_occurrence_rows(
    db: AsyncSession,
    *,
    contact_id: int,
    task_ids: set[int],
    note_ids: set[int],
    saved_search_ids: set[int],
    smart_plan_ids: set[int],
    opportunity_ids: set[int],
):
    rows = (
        await db.execute(
            select(
                CRMContactSourceOccurrence,
                CRMContactSectionCapture,
                CRMContactCapturePosition,
                CRMSourceRecord,
                CRMEntitySource,
            )
            .select_from(CRMContactSourceOccurrence)
            .outerjoin(
                CRMContactSectionCapture,
                CRMContactSectionCapture.id
                == CRMContactSourceOccurrence.section_capture_id,
            )
            .outerjoin(
                CRMContactCapturePosition,
                CRMContactCapturePosition.id
                == CRMContactSectionCapture.capture_position_id,
            )
            .outerjoin(
                CRMSourceRecord,
                CRMSourceRecord.id == CRMContactSourceOccurrence.source_record_id,
            )
            .outerjoin(
                CRMEntitySource,
                CRMEntitySource.source_record_id
                == CRMContactSourceOccurrence.source_record_id,
            )
            .where(
                or_(
                    and_(
                        or_(
                            CRMContactSourceOccurrence.contact_id == contact_id,
                            CRMContactCapturePosition.contact_id == contact_id,
                        ),
                        or_(
                            CRMContactSectionCapture.section_name.is_(None),
                            CRMContactSectionCapture.section_name != "timeline",
                        ),
                    ),
                    and_(
                        CRMEntitySource.entity_type == "task",
                        CRMEntitySource.entity_id.in_(task_ids),
                    ),
                    and_(
                        CRMEntitySource.entity_type == "note",
                        CRMEntitySource.entity_id.in_(note_ids),
                    ),
                    and_(
                        CRMEntitySource.entity_type == "saved_search",
                        CRMEntitySource.entity_id.in_(saved_search_ids),
                    ),
                    and_(
                        CRMEntitySource.entity_type == "smart_plan",
                        CRMEntitySource.entity_id.in_(smart_plan_ids),
                    ),
                    and_(
                        CRMEntitySource.entity_type == "opportunity",
                        CRMEntitySource.entity_id.in_(opportunity_ids),
                    ),
                )
            )
            .order_by(CRMContactSourceOccurrence.id, CRMEntitySource.id)
        )
    ).all()
    grouped: dict[int, list] = defaultdict(list)
    for row in rows:
        grouped[row[0].id].append(row)
    return grouped


async def _require_internal_links_have_occurrences(
    db: AsyncSession,
    *,
    task_ids: set[int],
    note_ids: set[int],
    saved_search_ids: set[int],
    smart_plan_ids: set[int],
    opportunity_ids: set[int],
) -> None:
    owns_requested_entity = or_(
        and_(
            CRMEntitySource.entity_type == "task",
            CRMEntitySource.entity_id.in_(task_ids),
        ),
        and_(
            CRMEntitySource.entity_type == "note",
            CRMEntitySource.entity_id.in_(note_ids),
        ),
        and_(
            CRMEntitySource.entity_type == "saved_search",
            CRMEntitySource.entity_id.in_(saved_search_ids),
        ),
        and_(
            CRMEntitySource.entity_type == "smart_plan",
            CRMEntitySource.entity_id.in_(smart_plan_ids),
        ),
        and_(
            CRMEntitySource.entity_type == "opportunity",
            CRMEntitySource.entity_id.in_(opportunity_ids),
        ),
    )
    missing_occurrence = await db.scalar(
        select(CRMEntitySource.id)
        .outerjoin(
            CRMContactSourceOccurrence,
            CRMContactSourceOccurrence.source_record_id
            == CRMEntitySource.source_record_id,
        )
        .where(
            owns_requested_entity,
            CRMContactSourceOccurrence.id.is_(None),
        )
        .limit(1)
    )
    if missing_occurrence is not None:
        raise ContactDataIntegrityError("contact occurrence ownership is invalid")


def _require_occurrence_context(
    rows: Sequence,
    *,
    contact_id: int,
) -> tuple[
    CRMContactSourceOccurrence,
    CRMContactSectionCapture,
    CRMSourceRecord,
    CRMEntitySource | None,
]:
    occurrence, section, position, source, _link = rows[0]
    if (
        section is None
        or position is None
        or source is None
        or occurrence.contact_id != contact_id
        or position.contact_id != contact_id
        or section.section_name not in _SECTION_RECORD_KINDS
        or source.source_system != "kw_command"
        or source.module != "contacts"
        or source.record_kind != _SECTION_RECORD_KINDS[section.section_name]
    ):
        raise ContactDataIntegrityError("contact occurrence ownership is invalid")
    links = [row[4] for row in rows if row[4] is not None]
    if len(links) > 1:
        raise ContactDataIntegrityError("contact source link is invalid")
    link = links[0] if links else None
    if (
        link is not None
        and link.entity_type != _SECTION_ENTITY_TYPES[section.section_name]
    ):
        raise ContactDataIntegrityError("contact source link is invalid")
    return occurrence, section, source, link


def _occurrence_values(source: CRMSourceRecord) -> dict[str, object]:
    def reject_nonfinite(_value: str) -> NoReturn:
        raise ValueError("non-finite JSON value")

    try:
        payload = json.loads(source.payload_json, parse_constant=reject_nonfinite)
    except (TypeError, ValueError):
        raise ContactDataIntegrityError(
            "contact occurrence payload is invalid"
        ) from None
    if not isinstance(payload, dict):
        raise ContactDataIntegrityError("contact occurrence payload is invalid")
    values = payload.get("values")
    if not isinstance(values, dict):
        raise ContactDataIntegrityError("contact occurrence payload is invalid")
    return values


def _bounded_occurrence_text(
    values: dict[str, object],
    key: str,
    *,
    max_length: int,
) -> str | None:
    value = values.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ContactDataIntegrityError("contact occurrence payload is invalid")
    return normalized


def _required_occurrence_title(
    source: CRMSourceRecord,
    values: dict[str, object],
    key: str,
) -> str:
    raw = values.get(key)
    if isinstance(raw, str):
        normalized = raw.strip()
        if len(normalized) > 500:
            raise ContactDataIntegrityError("contact occurrence payload is invalid")
        if normalized:
            return normalized
    fallback = source.display_label
    if isinstance(fallback, str):
        normalized = fallback.strip()
        if len(normalized) > 500:
            raise ContactDataIntegrityError("contact occurrence payload is invalid")
        if normalized:
            return normalized
    raise ContactDataIntegrityError("contact occurrence payload is invalid")


def _explicit_due_at(value: object) -> datetime | None:
    if not isinstance(value, str) or _RFC3339_DATETIME.fullmatch(value) is None:
        return None
    normalized = value[:-1] + "+00:00" if value[-1] in "Zz" else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    try:
        return parsed.astimezone(UTC)
    except (OverflowError, ValueError):
        return None


def _saved_search_criterion(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized if 1 <= len(normalized) <= 120 else None
    if type(value) is int and value >= 0:
        return str(value)
    return None


def _project_section_occurrence(
    source: CRMSourceRecord,
    section: ContactSection,
):
    values = _occurrence_values(source)
    if section is ContactSection.OPPORTUNITIES:
        value_cents = values.get("value_cents")
        return ContactOpportunityOccurrence(
            kind="opportunity",
            title=_required_occurrence_title(source, values, "title"),
            stage=_bounded_occurrence_text(values, "stage", max_length=120),
            value_cents=(
                value_cents if type(value_cents) is int and value_cents >= 0 else None
            ),
        )
    if section is ContactSection.SMART_PLANS:
        return ContactSmartPlanOccurrence(
            kind="smart_plan",
            title=_required_occurrence_title(source, values, "name"),
            status=_bounded_occurrence_text(values, "status", max_length=120),
        )
    if section is ContactSection.NOTES:
        return ContactNoteOccurrence(
            kind="note",
            title=_required_occurrence_title(source, values, "title"),
            body=_bounded_occurrence_text(values, "body", max_length=20_000),
        )
    if section is ContactSection.SAVED_SEARCHES:
        criteria: list[str] = []
        for key, label in (
            ("price", "Price"),
            ("beds", "Beds"),
            ("baths", "Baths"),
        ):
            projected = _saved_search_criterion(values.get(key))
            if projected is not None:
                criteria.append(f"{label}: {projected}")
        return ContactSavedSearchOccurrence(
            kind="saved_search",
            title=_required_occurrence_title(source, values, "name"),
            criteria_summary=tuple(criteria),
        )
    state = _TASK_SECTION_STATES.get(section)
    if state is None:
        raise ContactDataIntegrityError("contact occurrence payload is invalid")
    return ContactTaskOccurrence(
        kind="task",
        title=_required_occurrence_title(source, values, "title"),
        description=_bounded_occurrence_text(values, "description", max_length=20_000),
        state=state,  # type: ignore[arg-type]
        due_at=_explicit_due_at(values.get("due_at")),
    )


def _section_source_key_hash(source_key: str) -> str:
    return hashlib.sha256(
        _SECTION_SOURCE_KEY_DOMAIN + source_key.encode("utf-8")
    ).hexdigest()


def _section_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _section_target_owned_predicate(
    entity_id,
    *,
    contact_id: int,
    section: ContactSection,
) -> ColumnElement[bool]:
    if section in _TASK_SECTION_STATES:
        target = exists(
            select(literal(1))
            .select_from(CRMTask)
            .where(
                CRMTask.id == entity_id,
                CRMTask.contact_id == contact_id,
            )
        )
    elif section is ContactSection.NOTES:
        target = exists(
            select(literal(1))
            .select_from(CRMNote)
            .where(
                CRMNote.id == entity_id,
                CRMNote.contact_id == contact_id,
            )
        )
    elif section is ContactSection.SAVED_SEARCHES:
        target = exists(
            select(literal(1))
            .select_from(CRMSavedSearch)
            .where(
                CRMSavedSearch.id == entity_id,
                CRMSavedSearch.contact_id == contact_id,
            )
        )
    elif section is ContactSection.SMART_PLANS:
        target = exists(
            select(literal(1))
            .select_from(CRMSmartPlanEnrollment)
            .where(
                CRMSmartPlanEnrollment.id == entity_id,
                CRMSmartPlanEnrollment.contact_id == contact_id,
            )
        )
    elif section is ContactSection.OPPORTUNITIES:
        target = exists(
            select(literal(1))
            .select_from(CRMOpportunity)
            .join(
                CRMOpportunityContact,
                CRMOpportunityContact.opportunity_id == CRMOpportunity.id,
            )
            .where(
                CRMOpportunity.id == entity_id,
                CRMOpportunityContact.contact_id == contact_id,
            )
        )
    else:
        raise ContactSectionUnsupported("timeline uses a dedicated service")
    return target


def _section_owned_target_statement(
    *,
    contact_id: int,
    section: ContactSection,
    entity_ids: Sequence[int],
) -> Select[tuple[int]]:
    if section in _TASK_SECTION_STATES:
        return select(CRMTask.id).where(
            CRMTask.id.in_(entity_ids),
            CRMTask.contact_id == contact_id,
        )
    if section is ContactSection.NOTES:
        return select(CRMNote.id).where(
            CRMNote.id.in_(entity_ids),
            CRMNote.contact_id == contact_id,
        )
    if section is ContactSection.SAVED_SEARCHES:
        return select(CRMSavedSearch.id).where(
            CRMSavedSearch.id.in_(entity_ids),
            CRMSavedSearch.contact_id == contact_id,
        )
    if section is ContactSection.SMART_PLANS:
        return select(CRMSmartPlanEnrollment.id).where(
            CRMSmartPlanEnrollment.id.in_(entity_ids),
            CRMSmartPlanEnrollment.contact_id == contact_id,
        )
    if section is ContactSection.OPPORTUNITIES:
        return (
            select(CRMOpportunity.id)
            .join(
                CRMOpportunityContact,
                CRMOpportunityContact.opportunity_id == CRMOpportunity.id,
            )
            .where(
                CRMOpportunity.id.in_(entity_ids),
                CRMOpportunityContact.contact_id == contact_id,
            )
            .distinct()
        )
    raise ContactSectionUnsupported("timeline uses a dedicated service")


async def list_contact_section(
    db: AsyncSession,
    contact_id: int,
    section: ContactSection,
    *,
    page: int,
    page_size: int,
) -> ContactSectionPage:
    """Return one validated, deterministic non-timeline contact section page."""
    if not isinstance(section, ContactSection):
        raise TypeError("section must be ContactSection")
    if section is ContactSection.TIMELINE:
        raise ContactSectionUnsupported("timeline uses a dedicated service")
    if type(page) is not int or page < 1:
        raise ValueError("page must be an integer >= 1")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("page_size must be an integer between 1 and 100")
    if type(contact_id) is not int or contact_id <= 0:
        _safe_not_found()

    with db.no_autoflush:
        existing_contact_id = await db.scalar(
            select(CRMContact.id).where(CRMContact.id == contact_id).limit(1)
        )
        if existing_contact_id is None:
            _safe_not_found()

        expected_entity_type = _SECTION_ENTITY_TYPES[section.value]
        expected_record_kind = _SECTION_RECORD_KINDS[section.value]
        candidate_link = aliased(CRMEntitySource)
        candidate_target_owned = _section_target_owned_predicate(
            candidate_link.entity_id,
            contact_id=contact_id,
            section=section,
        )
        compatible_link_exists = exists(
            select(literal(1))
            .select_from(candidate_link)
            .where(
                candidate_link.source_record_id
                == CRMContactSourceOccurrence.source_record_id,
                candidate_link.entity_type == expected_entity_type,
                candidate_target_owned,
            )
            .correlate(CRMContactSourceOccurrence)
        )
        link_count = (
            select(func.count(CRMEntitySource.id))
            .where(
                CRMEntitySource.source_record_id
                == CRMContactSourceOccurrence.source_record_id
            )
            .correlate(CRMContactSourceOccurrence)
            .scalar_subquery()
        )
        kind_identifies_requested_section = and_(
            CRMSourceRecord.record_kind == expected_record_kind,
            (
                CRMContactSectionCapture.id.is_(None)
                if expected_record_kind == "contact_task"
                else literal(True)
            ),
        )
        link_identifies_requested_section = and_(
            compatible_link_exists,
            (
                or_(
                    CRMContactSectionCapture.section_name.is_(None),
                    CRMContactSectionCapture.section_name.not_in(
                        tuple(value.value for value in _TASK_SECTION_STATES)
                    ),
                )
                if expected_record_kind == "contact_task"
                else literal(True)
            ),
        )
        candidate_section = or_(
            CRMContactSectionCapture.section_name == section.value,
            kind_identifies_requested_section,
            link_identifies_requested_section,
        )
        candidate_owner = or_(
            CRMContactSourceOccurrence.contact_id == contact_id,
            CRMContactCapturePosition.contact_id == contact_id,
            compatible_link_exists,
        )
        invalid_context = or_(
            CRMContactSourceOccurrence.id <= 0,
            CRMContactSourceOccurrence.contact_id != contact_id,
            CRMContactSourceOccurrence.occurrence_ordinal <= 0,
            CRMContactSectionCapture.id.is_(None),
            CRMContactSectionCapture.section_name != section.value,
            or_(
                CRMContactSectionCapture.capture_quality.is_(None),
                CRMContactSectionCapture.capture_quality.not_in(
                    tuple(value.value for value in CaptureQualityValue)
                ),
            ),
            CRMContactCapturePosition.id.is_(None),
            CRMContactCapturePosition.contact_id != contact_id,
            CRMContactCapturePosition.capture_ordinal <= 0,
            CRMSourceRecord.id.is_(None),
            CRMSourceRecord.source_system != "kw_command",
            CRMSourceRecord.module != "contacts",
            CRMSourceRecord.record_kind != expected_record_kind,
            link_count > 1,
            and_(link_count == 1, not_(compatible_link_exists)),
        )
        context_from = (
            CRMContactSourceOccurrence.__table__.outerjoin(
                CRMContactSectionCapture,
                CRMContactSectionCapture.id
                == CRMContactSourceOccurrence.section_capture_id,
            )
            .outerjoin(
                CRMContactCapturePosition,
                CRMContactCapturePosition.id
                == CRMContactSectionCapture.capture_position_id,
            )
            .outerjoin(
                CRMSourceRecord,
                CRMSourceRecord.id == CRMContactSourceOccurrence.source_record_id,
            )
        )
        invalid_occurrence_id = await db.scalar(
            select(CRMContactSourceOccurrence.id)
            .select_from(context_from)
            .where(candidate_section, candidate_owner, invalid_context)
            .limit(1)
        )
        if invalid_occurrence_id is not None:
            raise ContactDataIntegrityError("contact occurrence ownership is invalid")

        valid_ownership = and_(
            CRMContactSourceOccurrence.contact_id == contact_id,
            CRMContactSectionCapture.section_name == section.value,
            CRMContactCapturePosition.contact_id == contact_id,
            CRMSourceRecord.source_system == "kw_command",
            CRMSourceRecord.module == "contacts",
            CRMSourceRecord.record_kind == expected_record_kind,
        )
        valid_from = (
            CRMContactSourceOccurrence.__table__.join(
                CRMContactSectionCapture,
                CRMContactSectionCapture.id
                == CRMContactSourceOccurrence.section_capture_id,
            )
            .join(
                CRMContactCapturePosition,
                CRMContactCapturePosition.id
                == CRMContactSectionCapture.capture_position_id,
            )
            .join(
                CRMSourceRecord,
                CRMSourceRecord.id == CRMContactSourceOccurrence.source_record_id,
            )
        )
        total = int(
            await db.scalar(
                select(func.count(CRMContactSourceOccurrence.id))
                .select_from(valid_from)
                .where(valid_ownership)
            )
            or 0
        )
        page_rows = (
            await db.execute(
                select(
                    CRMContactSourceOccurrence.id,
                    CRMContactSourceOccurrence.source_record_id,
                    CRMContactSourceOccurrence.occurrence_ordinal,
                    CRMContactSectionCapture.capture_quality,
                    CRMContactSectionCapture.captured_at,
                    CRMContactCapturePosition.capture_ordinal,
                    CRMSourceRecord.source_key,
                    CRMSourceRecord.display_label,
                    CRMSourceRecord.payload_json,
                )
                .select_from(valid_from)
                .where(
                    valid_ownership,
                )
                .order_by(
                    CRMContactSectionCapture.captured_at.is_(None).asc(),
                    CRMContactSectionCapture.captured_at.desc(),
                    CRMContactCapturePosition.capture_ordinal.asc(),
                    CRMContactSourceOccurrence.occurrence_ordinal.asc(),
                    CRMContactSourceOccurrence.id,
                )
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).all()

        page_source_ids = tuple(row.source_record_id for row in page_rows)
        page_links = (
            await db.execute(
                select(
                    CRMEntitySource.source_record_id,
                    CRMEntitySource.entity_type,
                    CRMEntitySource.entity_id,
                )
                .where(CRMEntitySource.source_record_id.in_(page_source_ids))
                .order_by(CRMEntitySource.source_record_id, CRMEntitySource.id)
            )
        ).all()
        links_by_source: dict[int, list] = defaultdict(list)
        for link in page_links:
            links_by_source[link.source_record_id].append(link)
        linked_entity_ids = tuple(link.entity_id for link in page_links)
        target_ids = set(
            await db.scalars(
                _section_owned_target_statement(
                    contact_id=contact_id,
                    section=section,
                    entity_ids=linked_entity_ids,
                )
            )
        )

    projected_rows: list[object] = []
    for page_row in page_rows:
        links = links_by_source.get(page_row.source_record_id, [])
        if len(links) > 1:
            raise ContactDataIntegrityError("contact source link is invalid")
        link = links[0] if links else None
        if link is not None and (
            link.entity_type != expected_entity_type or link.entity_id not in target_ids
        ):
            raise ContactDataIntegrityError("contact source link is invalid")
        source = CRMSourceRecord(
            id=page_row.source_record_id,
            source_system="kw_command",
            module="contacts",
            record_kind=expected_record_kind,
            source_key=page_row.source_key,
            evidence_level="rendered_occurrence",
            display_label=page_row.display_label,
            payload_json=page_row.payload_json,
            capture_quality=page_row.capture_quality,
            parser_version="section-projection",
        )
        try:
            quality = CaptureQualityValue(page_row.capture_quality)
            source_key_hash = _section_source_key_hash(source.source_key)
        except (AttributeError, TypeError, UnicodeError, ValueError):
            raise ContactDataIntegrityError(
                "contact occurrence ownership is invalid"
            ) from None
        captured_at = _section_datetime(page_row.captured_at)
        value = _project_section_occurrence(source, section)
        if link is None:
            row = ContactSourceOnly(
                status="source_only",
                source_record_id=source.id,
                source_key_hash=source_key_hash,
                section=section,
                occurrence_ordinal=page_row.occurrence_ordinal,
                capture_quality=quality,
                captured_at=captured_at,
                value=value,
            )
        else:
            row = ContactMaterialized(
                status="materialized",
                source_record_id=source.id,
                source_key_hash=source_key_hash,
                section=section,
                occurrence_ordinal=page_row.occurrence_ordinal,
                capture_quality=quality,
                captured_at=captured_at,
                value=value,
                entity_type=expected_entity_type,  # type: ignore[arg-type]
                entity_id=link.entity_id,
            )
        projected_rows.append(row)
    return ContactSectionPage(
        rows=tuple(projected_rows),  # type: ignore[arg-type]
        total=total,
        page=page,
        page_size=page_size,
        page_count=(total + page_size - 1) // page_size,
    )


async def get_contact_workspace_summary(
    db: AsyncSession,
    contact_id: int,
) -> ContactWorkspaceSummary:
    """Count internal and recovered workspace rows without double-counting."""
    if type(contact_id) is not int or contact_id <= 0:
        _safe_not_found()
    with db.no_autoflush:
        if await db.get(CRMContact, contact_id) is None:
            _safe_not_found()
        tasks = {
            row.id: row.status
            for row in (
                await db.execute(
                    select(CRMTask.id, CRMTask.status).where(
                        CRMTask.contact_id == contact_id
                    )
                )
            ).all()
        }
        notes = set(
            await db.scalars(select(CRMNote.id).where(CRMNote.contact_id == contact_id))
        )
        searches = set(
            await db.scalars(
                select(CRMSavedSearch.id).where(CRMSavedSearch.contact_id == contact_id)
            )
        )
        enrollments = {
            row.id: row.status
            for row in (
                await db.execute(
                    select(
                        CRMSmartPlanEnrollment.id,
                        CRMSmartPlanEnrollment.status,
                    )
                    .join(
                        CRMSmartPlan,
                        CRMSmartPlan.id == CRMSmartPlanEnrollment.smart_plan_id,
                    )
                    .where(CRMSmartPlanEnrollment.contact_id == contact_id)
                )
            ).all()
        }
        opportunities = set(
            await db.scalars(
                select(CRMOpportunityContact.opportunity_id)
                .join(
                    CRMOpportunity,
                    CRMOpportunity.id == CRMOpportunityContact.opportunity_id,
                )
                .where(CRMOpportunityContact.contact_id == contact_id)
            )
        )
        await _require_internal_links_have_occurrences(
            db,
            task_ids=set(tasks),
            note_ids=notes,
            saved_search_ids=searches,
            smart_plan_ids=set(enrollments),
            opportunity_ids=opportunities,
        )
        occurrence_groups = await _contact_occurrence_rows(
            db,
            contact_id=contact_id,
            task_ids=set(tasks),
            note_ids=notes,
            saved_search_ids=searches,
            smart_plan_ids=set(enrollments),
            opportunity_ids=opportunities,
        )

        counts = {
            "tasks_to_do": 0,
            "tasks_completed": 0,
            "tasks_archived": 0,
            "smart_plans": 0,
            "opportunities": 0,
            "notes": 0,
            "saved_searches": 0,
        }
        for rows in occurrence_groups.values():
            _occurrence, section, source, link = _require_occurrence_context(
                rows, contact_id=contact_id
            )
            if link is not None:
                owned = {
                    "task": link.entity_id in tasks,
                    "note": link.entity_id in notes,
                    "saved_search": link.entity_id in searches,
                    "smart_plan": link.entity_id in enrollments,
                    "opportunity": link.entity_id in opportunities,
                }[link.entity_type]
                if not owned:
                    raise ContactDataIntegrityError("contact source link is invalid")
                continue
            values = _occurrence_values(source)
            if section.section_name == "smart_plans":
                status = _bounded_occurrence_text(values, "status", max_length=120)
                if status is None or status.casefold() != "active":
                    continue
            counts[section.section_name] += 1

        task_counts = {"open": 0, "completed": 0, "archived": 0}
        for status in tasks.values():
            if status not in task_counts:
                raise ContactDataIntegrityError("contact task status is invalid")
            task_counts[status] += 1
        active_enrollments = sum(
            1
            for status in enrollments.values()
            if isinstance(status, str) and status.strip().casefold() == "active"
        )
        try:
            bookings = await count_contact_bookings(db, contact_id)
        except TimelineContactNotFound:
            _safe_not_found()
        except ContactTimelineIntegrityError as error:
            raise ContactDataIntegrityError(
                "contact booking ownership is invalid"
            ) from error

    return ContactWorkspaceSummary(
        open_tasks=task_counts["open"] + counts["tasks_to_do"],
        completed_tasks=(task_counts["completed"] + counts["tasks_completed"]),
        archived_tasks=(task_counts["archived"] + counts["tasks_archived"]),
        active_smart_plans=active_enrollments + counts["smart_plans"],
        opportunities=len(opportunities) + counts["opportunities"],
        notes=len(notes) + counts["notes"],
        saved_searches=len(searches) + counts["saved_searches"],
        bookings=bookings,
    )


def _evidence_error(message: str = "contact evidence graph is invalid") -> NoReturn:
    raise ContactDataIntegrityError(message)


def _require_evidence_source(
    source: CRMSourceRecord | None,
    *,
    record_kind: str,
) -> CRMSourceRecord:
    if (
        source is None
        or type(source.id) is not int
        or source.id <= 0
        or source.source_system != "kw_command"
        or source.module != "contacts"
        or source.record_kind != record_kind
        or source.evidence_level not in _EVIDENCE_LEVELS
        or source.capture_quality
        not in {quality.value for quality in CaptureQualityValue}
    ):
        _evidence_error()
    return source


def _strict_json(value: str) -> object:
    def reject_nonfinite(_value: str) -> NoReturn:
        raise ValueError("non-finite JSON value")

    try:
        return json.loads(value, parse_constant=reject_nonfinite)
    except (TypeError, ValueError):
        _evidence_error()


def _profile_provider_id(source: CRMSourceRecord) -> str:
    payload = _strict_json(source.payload_json)
    if not isinstance(payload, dict):
        _evidence_error()
    provider_id = payload.get("source_contact_id")
    if (
        not isinstance(provider_id, str)
        or _CONTACT_PROVIDER_ID_RE.fullmatch(provider_id) is None
    ):
        _evidence_error()
    return provider_id


def _limitation_codes(value: str) -> tuple[str, ...]:
    payload = _strict_json(value)
    if not isinstance(payload, list):
        _evidence_error()
    codes: list[str] = []
    for item in payload:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or item in codes
        ):
            _evidence_error()
        codes.append(item)
    if json.dumps(codes, ensure_ascii=False, separators=(",", ":")) != value:
        _evidence_error()
    return tuple(codes)


def _source_metadata(
    source: CRMSourceRecord,
    artifacts: tuple[ContactArtifactMetadata, ...],
) -> ContactSourceMetadata:
    try:
        quality = CaptureQualityValue(source.capture_quality)
    except ValueError:
        _evidence_error()
    return ContactSourceMetadata(
        source_record_id=source.id,
        record_kind=source.record_kind,
        evidence_level=source.evidence_level,  # type: ignore[arg-type]
        capture_quality=quality,
        captured_at=_section_datetime(source.captured_at),
        artifacts=artifacts,
    )


async def get_contact_evidence(
    db: AsyncSession,
    contact_id: int,
) -> ContactEvidence:
    """Return the lossless, validated evidence graph for one contact."""
    if type(contact_id) is not int or contact_id <= 0:
        _safe_not_found()

    position_source = aliased(CRMSourceRecord)
    profile_source = aliased(CRMSourceRecord)
    profile_link = aliased(CRMEntitySource)
    profile_target = aliased(CRMContact)
    section_source = aliased(CRMSourceRecord)
    occurrence_source = aliased(CRMSourceRecord)
    occurrence_link = aliased(CRMEntitySource)
    section_context = aliased(CRMContactSectionCapture)
    position_context = aliased(CRMContactCapturePosition)

    with db.no_autoflush:
        existing_contact_id = await db.scalar(
            select(CRMContact.id).where(CRMContact.id == contact_id).limit(1)
        )
        if existing_contact_id is None:
            _safe_not_found()

        position_rows = (
            await db.execute(
                select(
                    CRMContactCapturePosition,
                    position_source,
                    CRMContact.id.label("target_contact_id"),
                )
                .select_from(CRMContactCapturePosition)
                .outerjoin(
                    position_source,
                    position_source.id == CRMContactCapturePosition.source_record_id,
                )
                .outerjoin(
                    CRMContact,
                    CRMContact.id == CRMContactCapturePosition.contact_id,
                )
                .order_by(CRMContactCapturePosition.id)
            )
        ).all()

        profile_rows = (
            await db.execute(
                select(
                    profile_source,
                    profile_link.id.label("link_id"),
                    profile_link.entity_id.label("link_contact_id"),
                    profile_target.id.label("target_contact_id"),
                )
                .select_from(profile_source)
                .outerjoin(
                    profile_link,
                    and_(
                        profile_link.source_record_id == profile_source.id,
                        profile_link.entity_type == "contact",
                    ),
                )
                .outerjoin(
                    profile_target,
                    profile_target.id == profile_link.entity_id,
                )
                .where(
                    profile_source.source_system == "kw_command",
                    profile_source.module == "contacts",
                    profile_source.record_kind == "contact_profile",
                )
                .order_by(profile_source.id, profile_link.id)
            )
        ).all()

        contact_rows = (
            await db.execute(
                select(
                    CRMContact.id,
                    CRMContact.lead_id,
                    exists(
                        select(literal(1)).where(
                            CRMContactAuditEvent.contact_id == CRMContact.id,
                            CRMContactAuditEvent.action
                            == "command_contact_overlap_reviewed",
                        )
                    ).label("reviewed"),
                ).order_by(CRMContact.id)
            )
        ).all()

        requested_position_ids = tuple(
            position.id
            for position, _source, _target_id in position_rows
            if position.contact_id == contact_id
        )
        section_rows = (
            await db.execute(
                select(CRMContactSectionCapture, section_source)
                .select_from(CRMContactSectionCapture)
                .outerjoin(
                    section_source,
                    section_source.id == CRMContactSectionCapture.source_record_id,
                )
                .where(
                    CRMContactSectionCapture.capture_position_id.in_(
                        requested_position_ids
                    )
                    if requested_position_ids
                    else false()
                )
                .order_by(
                    CRMContactSectionCapture.capture_position_id,
                    CRMContactSectionCapture.id,
                )
            )
        ).all()

        requested_section_ids = tuple(section.id for section, _source in section_rows)
        occurrence_target_owned = {
            "task": exists(
                select(literal(1))
                .select_from(CRMTask)
                .where(
                    CRMTask.id == occurrence_link.entity_id,
                    CRMTask.contact_id == contact_id,
                )
                .correlate(occurrence_link)
            ),
            "note": exists(
                select(literal(1))
                .select_from(CRMNote)
                .where(
                    CRMNote.id == occurrence_link.entity_id,
                    CRMNote.contact_id == contact_id,
                )
                .correlate(occurrence_link)
            ),
            "saved_search": exists(
                select(literal(1))
                .select_from(CRMSavedSearch)
                .where(
                    CRMSavedSearch.id == occurrence_link.entity_id,
                    CRMSavedSearch.contact_id == contact_id,
                )
                .correlate(occurrence_link)
            ),
            "smart_plan": exists(
                select(literal(1))
                .select_from(CRMSmartPlanEnrollment)
                .where(
                    CRMSmartPlanEnrollment.id == occurrence_link.entity_id,
                    CRMSmartPlanEnrollment.contact_id == contact_id,
                )
                .correlate(occurrence_link)
            ),
            "opportunity": exists(
                select(literal(1))
                .select_from(CRMOpportunity)
                .join(
                    CRMOpportunityContact,
                    CRMOpportunityContact.opportunity_id == CRMOpportunity.id,
                )
                .where(
                    CRMOpportunity.id == occurrence_link.entity_id,
                    CRMOpportunityContact.contact_id == contact_id,
                )
                .correlate(occurrence_link)
            ),
            "contact_timeline_event": exists(
                select(literal(1))
                .select_from(CRMContactTimelineEvent)
                .where(
                    CRMContactTimelineEvent.id == occurrence_link.entity_id,
                    CRMContactTimelineEvent.contact_id == contact_id,
                    CRMContactTimelineEvent.source_system == "kw_command",
                    CRMContactTimelineEvent.source_record_id
                    == CRMContactSourceOccurrence.source_record_id,
                )
                .correlate(occurrence_link, CRMContactSourceOccurrence)
            ),
        }
        occurrence_rows = (
            await db.execute(
                select(
                    CRMContactSourceOccurrence,
                    section_context,
                    position_context,
                    occurrence_source,
                    occurrence_link.id.label("link_id"),
                    occurrence_link.entity_type.label("link_entity_type"),
                    occurrence_link.entity_id.label("link_entity_id"),
                    *(
                        predicate.label(f"owns_{entity_type}")
                        for entity_type, predicate in occurrence_target_owned.items()
                    ),
                )
                .select_from(CRMContactSourceOccurrence)
                .outerjoin(
                    section_context,
                    section_context.id == CRMContactSourceOccurrence.section_capture_id,
                )
                .outerjoin(
                    position_context,
                    position_context.id == section_context.capture_position_id,
                )
                .outerjoin(
                    occurrence_source,
                    occurrence_source.id == CRMContactSourceOccurrence.source_record_id,
                )
                .outerjoin(
                    occurrence_link,
                    occurrence_link.source_record_id
                    == CRMContactSourceOccurrence.source_record_id,
                )
                .where(
                    or_(
                        CRMContactSourceOccurrence.contact_id == contact_id,
                        position_context.id.in_(requested_position_ids)
                        if requested_position_ids
                        else false(),
                    )
                )
                .order_by(
                    CRMContactSourceOccurrence.section_capture_id,
                    CRMContactSourceOccurrence.occurrence_ordinal,
                    CRMContactSourceOccurrence.id,
                )
            )
        ).all()

        profiles_by_provider: dict[str, list[tuple[CRMSourceRecord, list]]] = {}
        grouped_profiles: dict[int, list] = defaultdict(list)
        for row in profile_rows:
            source = _require_evidence_source(row[0], record_kind="contact_profile")
            grouped_profiles[source.id].append(row)
        for rows in grouped_profiles.values():
            source = rows[0][0]
            provider_id = _profile_provider_id(source)
            profiles_by_provider.setdefault(provider_id, []).append((source, rows))

        resolved_contacts: set[int] = set()
        profile_for_position: dict[int, CRMSourceRecord] = {}
        position_source_for_id: dict[int, CRMSourceRecord] = {}
        provider_sources: set[int] = set()
        for position, source, target_contact_id in position_rows:
            source = _require_evidence_source(
                source, record_kind="contact_capture_position"
            )
            if (
                type(position.id) is not int
                or position.id <= 0
                or type(position.source_record_id) is not int
                or position.source_record_id <= 0
                or type(position.contact_id) is not int
                or position.contact_id <= 0
                or target_contact_id != position.contact_id
                or type(position.capture_ordinal) is not int
                or position.capture_ordinal <= 0
                or _CONTACT_PROVIDER_ID_RE.fullmatch(position.source_contact_id) is None
                or position.capture_quality
                not in {quality.value for quality in CaptureQualityValue}
            ):
                _evidence_error()
            _limitation_codes(position.limitations_json)
            if position.source_record_id in provider_sources:
                _evidence_error()
            provider_sources.add(position.source_record_id)
            candidates = profiles_by_provider.get(position.source_contact_id, [])
            if len(candidates) != 1:
                _evidence_error()
            profile, linked_rows = candidates[0]
            linked = [row for row in linked_rows if row.link_id is not None]
            if (
                len(linked) != 1
                or linked[0].target_contact_id != position.contact_id
                or linked[0].link_contact_id != position.contact_id
            ):
                _evidence_error()
            resolved_contacts.add(position.contact_id)
            profile_for_position[position.id] = profile
            position_source_for_id[position.id] = source

        provider_count = len(provider_sources)
        resolved_count = len(resolved_contacts)
        aliases = provider_count - resolved_count
        if aliases != 0:
            _evidence_error()
        lead_ids = {row.id for row in contact_rows if row.lead_id is not None}
        reviewed_ids = {row.id for row in contact_rows if row.reviewed}
        reviewed_overlaps = len(lead_ids & resolved_contacts & reviewed_ids)

        sections_by_position: dict[int, dict[ContactSection, tuple]] = defaultdict(dict)
        requested_sources: dict[int, CRMSourceRecord] = {}
        for position_id in requested_position_ids:
            requested_sources[profile_for_position[position_id].id] = (
                profile_for_position[position_id]
            )
            requested_sources[position_source_for_id[position_id].id] = (
                position_source_for_id[position_id]
            )
        for section, source in section_rows:
            source = _require_evidence_source(
                source, record_kind="contact_section_capture"
            )
            if (
                type(section.id) is not int
                or section.id <= 0
                or section.capture_position_id not in requested_position_ids
                or type(section.row_count) is not int
                or section.row_count < 0
                or type(section.is_empty) is not bool
                or section.capture_quality
                not in {quality.value for quality in CaptureQualityValue}
            ):
                _evidence_error()
            try:
                section_name = ContactSection(section.section_name)
            except ValueError:
                _evidence_error()
            if section_name in sections_by_position[section.capture_position_id]:
                _evidence_error()
            limitations = _limitation_codes(section.limitations_json)
            if section.is_empty != (section.row_count == 0):
                if section.capture_quality == CaptureQualityValue.COMPLETE.value:
                    _evidence_error()
                if section.is_empty or section.row_count > 0:
                    _evidence_error()
            sections_by_position[section.capture_position_id][section_name] = (
                section,
                source,
                limitations,
            )
            requested_sources[source.id] = source

        occurrence_groups: dict[int, list] = defaultdict(list)
        for row in occurrence_rows:
            occurrence_groups[row[0].id].append(row)
        occurrences_by_section: dict[int, list] = defaultdict(list)
        for rows in occurrence_groups.values():
            occurrence, section, position, source = rows[0][:4]
            if (
                section is None
                or position is None
                or occurrence.contact_id != contact_id
                or position.contact_id != contact_id
                or section.id not in requested_section_ids
                or section.capture_position_id != position.id
                or type(occurrence.id) is not int
                or occurrence.id <= 0
                or type(occurrence.occurrence_ordinal) is not int
                or occurrence.occurrence_ordinal <= 0
            ):
                _evidence_error()
            try:
                section_name = ContactSection(section.section_name)
            except ValueError:
                _evidence_error()
            expected_kind = (
                "contact_timeline_event"
                if section_name is ContactSection.TIMELINE
                else _SECTION_RECORD_KINDS[section_name.value]
            )
            source = _require_evidence_source(source, record_kind=expected_kind)
            links = [row for row in rows if row.link_id is not None]
            expected_entity_type = (
                "contact_timeline_event"
                if section_name is ContactSection.TIMELINE
                else _SECTION_ENTITY_TYPES[section_name.value]
            )
            if len(links) > 1 or (
                links
                and (
                    links[0].link_entity_type != expected_entity_type
                    or type(links[0].link_entity_id) is not int
                    or links[0].link_entity_id <= 0
                    or not getattr(links[0], f"owns_{expected_entity_type}")
                )
            ):
                _evidence_error()
            if section_name is not ContactSection.TIMELINE:
                _project_section_occurrence(source, section_name)
            occurrences_by_section[section.id].append(occurrence)
            requested_sources[source.id] = source

        capture_positions: list[ContactCaptureEvidence] = []
        section_matrix: list[ContactSectionEvidence] = []
        requested_qualities: list[CaptureQualityValue] = []
        positions_by_id = {
            position.id: position
            for position, _source, _target_id in position_rows
            if position.contact_id == contact_id
        }
        for position in sorted(
            positions_by_id.values(), key=lambda row: (row.capture_ordinal, row.id)
        ):
            cells = sections_by_position.get(position.id, {})
            if set(cells) != set(ContactSection):
                _evidence_error()
            projected_cells: list[ContactSectionEvidence] = []
            for section_name in ContactSection:
                section, source, limitations = cells[section_name]
                if len(occurrences_by_section.get(section.id, ())) != section.row_count:
                    _evidence_error()
                try:
                    quality = CaptureQualityValue(section.capture_quality)
                except ValueError:
                    _evidence_error()
                projected = ContactSectionEvidence(
                    capture_position_id=position.id,
                    section=section_name,
                    source_record_id=source.id,
                    capture_quality=quality,
                    row_count=section.row_count,
                    is_empty=section.is_empty,
                    limitation_codes=limitations,
                )
                projected_cells.append(projected)
                section_matrix.append(projected)
                requested_qualities.append(quality)
            try:
                position_quality = CaptureQualityValue(position.capture_quality)
            except ValueError:
                _evidence_error()
            capture_positions.append(
                ContactCaptureEvidence(
                    capture_position_id=position.id,
                    capture_ordinal=position.capture_ordinal,
                    source_record_id=position.source_record_id,
                    capture_quality=position_quality,
                    sections=tuple(projected_cells),
                )
            )

        source_ids = tuple(sorted(requested_sources))
        artifact_rows = (
            await db.execute(
                select(
                    CRMSourceRecordArtifact.id.label("link_id"),
                    CRMSourceRecordArtifact.source_record_id,
                    CRMSourceRecordArtifact.artifact_id,
                    CRMSourceRecordArtifact.relation,
                    CRMArchiveArtifact.id.label("catalog_artifact_id"),
                    CRMArchiveArtifact.artifact_type,
                    CRMArchiveArtifact.sha256,
                    CRMArchiveArtifact.size_bytes,
                    func.length(CRMArchiveArtifact.content_bytes).label(
                        "content_length"
                    ),
                )
                .select_from(CRMSourceRecordArtifact)
                .outerjoin(
                    CRMArchiveArtifact,
                    CRMArchiveArtifact.id == CRMSourceRecordArtifact.artifact_id,
                )
                .where(
                    CRMSourceRecordArtifact.source_record_id.in_(source_ids)
                    if source_ids
                    else false()
                )
                .order_by(
                    CRMSourceRecordArtifact.source_record_id,
                    CRMSourceRecordArtifact.artifact_id,
                    CRMSourceRecordArtifact.id,
                )
            )
        ).all()

    artifacts_by_source: dict[int, list[ContactArtifactMetadata]] = defaultdict(list)
    artifact_links: set[tuple[int, int]] = set()
    for row in artifact_rows:
        key = (row.source_record_id, row.artifact_id)
        artifact_type = row.artifact_type
        if (
            type(row.link_id) is not int
            or row.link_id <= 0
            or row.source_record_id not in requested_sources
            or type(row.artifact_id) is not int
            or row.artifact_id <= 0
            or row.catalog_artifact_id != row.artifact_id
            or row.relation != "evidence"
            or key in artifact_links
            or not isinstance(artifact_type, str)
            or artifact_type.strip() != artifact_type
            or not 1 <= len(artifact_type) <= 64
            or not isinstance(row.sha256, str)
            or _ARTIFACT_SHA256_RE.fullmatch(row.sha256) is None
            or type(row.size_bytes) is not int
            or row.size_bytes < 0
            or (row.content_length is not None and row.content_length != row.size_bytes)
        ):
            _evidence_error("contact evidence artifact is invalid")
        artifact_links.add(key)
        artifacts_by_source[row.source_record_id].append(
            ContactArtifactMetadata(
                artifact_id=row.artifact_id,
                artifact_type=artifact_type,
                sha256=row.sha256,
                size_bytes=row.size_bytes,
                content_href=(
                    f"/api/v1/command/archive/artifacts/{row.artifact_id}/content"
                ),
            )
        )

    if not capture_positions or any(
        quality in {CaptureQualityValue.SHELL, CaptureQualityValue.ERROR}
        for quality in requested_qualities
    ):
        aggregate_quality = "limitation"
    elif any(quality is CaptureQualityValue.PARTIAL for quality in requested_qualities):
        aggregate_quality = "partial"
    else:
        aggregate_quality = "complete"

    return ContactEvidence(
        contact_id=contact_id,
        provider_contact_rows=provider_count,
        resolved_provider_identities=resolved_count,
        coalesced_aliases=0,
        lead_backed_contacts=len(lead_ids),
        reviewed_overlaps=reviewed_overlaps,
        legacy_only_contacts=len(lead_ids) - reviewed_overlaps,
        capture_positions=tuple(capture_positions),
        section_matrix=tuple(section_matrix),
        sources=tuple(
            _source_metadata(source, tuple(artifacts_by_source[source_id]))
            for source_id, source in sorted(requested_sources.items())
        ),
        capture_quality=aggregate_quality,  # type: ignore[arg-type]
    )


async def get_contact_neighbors(
    db: AsyncSession,
    contact_id: int,
    filters: ContactDirectoryFilters,
    *,
    now: datetime,
) -> ContactNeighbors:
    """Return adjacent contacts in the exact directory filter/sort universe."""
    if type(contact_id) is not int or contact_id <= 0:
        _safe_not_found()
    if await db.get(CRMContact, contact_id) is None:
        _safe_not_found()
    normalized_now = _normalize_now(now)
    order = _directory_order(filters)
    ranked = (
        select(
            CRMContact.id.label("contact_id"),
            func.lag(CRMContact.id).over(order_by=order).label("previous_id"),
            func.lead(CRMContact.id).over(order_by=order).label("next_id"),
        )
        .outerjoin(
            CRMContactProfile,
            CRMContactProfile.contact_id == CRMContact.id,
        )
        .where(*_directory_predicates(filters, now=normalized_now))
        .subquery()
    )
    row = (
        await db.execute(
            select(ranked.c.previous_id, ranked.c.next_id).where(
                ranked.c.contact_id == contact_id
            )
        )
    ).one_or_none()
    if row is None:
        raise ContactNotInDirectory("contact is outside the requested directory")
    return ContactNeighbors(
        previous_contact_id=row.previous_id,
        next_contact_id=row.next_id,
    )


def _celebration_row(
    contact: CRMContact,
    profile: CRMContactProfile | None,
    *,
    kind: str,
) -> ContactCelebrationRow | None:
    value = _celebration(contact, profile, kind=kind)
    if value is None:
        return None
    return ContactCelebrationRow(
        contact_id=contact.id,
        display_name=f"{contact.first_name} {contact.last_name}".strip(),
        kind=kind,  # type: ignore[arg-type]
        month=value.month,
        day=value.day,
        year=value.year,
        year_quality=value.year_quality,
        origin=value.origin,
    )


async def list_contact_celebrations(
    db: AsyncSession,
    *,
    month: int,
) -> ContactCelebrations:
    """Return explicit internal/recovered celebrations without inferring dates."""
    if type(month) is not int:
        raise TypeError("month must be an integer")
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")
    recovered_birthday = and_(
        CRMContact.birthday.is_(None),
        CRMContactProfile.birth_month == month,
        _valid_recovered_celebration_predicate(
            month_column=CRMContactProfile.birth_month,
            day_column=CRMContactProfile.birth_day,
            year_column=CRMContactProfile.birth_year,
            quality_column=CRMContactProfile.birth_year_quality,
        ),
    )
    recovered_anniversary = and_(
        CRMContact.anniversary.is_(None),
        CRMContactProfile.anniversary_month == month,
        _valid_recovered_celebration_predicate(
            month_column=CRMContactProfile.anniversary_month,
            day_column=CRMContactProfile.anniversary_day,
            year_column=CRMContactProfile.anniversary_year,
            quality_column=CRMContactProfile.anniversary_year_quality,
        ),
    )
    with db.no_autoflush:
        rows = (
            await db.execute(
                select(CRMContact, CRMContactProfile)
                .outerjoin(
                    CRMContactProfile,
                    CRMContactProfile.contact_id == CRMContact.id,
                )
                .where(
                    or_(
                        extract("month", CRMContact.birthday) == month,
                        extract("month", CRMContact.anniversary) == month,
                        recovered_birthday,
                        recovered_anniversary,
                    )
                )
            )
        ).all()
    birthdays: list[ContactCelebrationRow] = []
    anniversaries: list[ContactCelebrationRow] = []
    for contact, profile in rows:
        birthday = _celebration_row(contact, profile, kind="birthday")
        if birthday is not None and birthday.month == month:
            birthdays.append(birthday)
        anniversary = _celebration_row(contact, profile, kind="anniversary")
        if anniversary is not None and anniversary.month == month:
            anniversaries.append(anniversary)

    def order_key(row: ContactCelebrationRow) -> tuple[int, str, int]:
        return row.day, row.display_name.casefold(), row.contact_id

    birthdays.sort(key=order_key)
    anniversaries.sort(key=order_key)
    return ContactCelebrations(
        birthdays=tuple(birthdays),
        anniversaries=tuple(anniversaries),
    )


async def _lock_contact(db: AsyncSession, contact_id: int) -> CRMContact:
    contact = (
        await db.scalars(
            select(CRMContact)
            .where(CRMContact.id == contact_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if contact is None:
        _safe_not_found()
    return contact


def _canonical_audit(
    *, action: str, phase: str, payload: Mapping[str, object]
) -> str:
    try:
        return canonical_contact_audit_json(
            action=action,  # type: ignore[arg-type]
            phase=phase,  # type: ignore[arg-type]
            payload=payload,
        )
    except (TypeError, ValueError):
        raise ContactDataIntegrityError(
            "contact audit state is invalid"
        ) from None


def _canonical_workspace_saved_search_audit(
    *, actor_subject: str, search_id: int, name: str
) -> str:
    try:
        return canonical_workspace_saved_search_activity_json(
            actor_subject=actor_subject,
            search_id=search_id,
            name=name,
        )
    except (TypeError, ValueError):
        raise ContactDataIntegrityError(
            "saved search audit state is invalid"
        ) from None


def _thaw_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    return value


def _canonical_criteria(value: Mapping[str, object]) -> str:
    try:
        return json.dumps(
            _thaw_json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise ContactDataIntegrityError(
            "saved search criteria is invalid"
        ) from None


def _parse_canonical_criteria(value: str) -> Mapping[str, object]:
    def reject_nonfinite(_value: str) -> NoReturn:
        raise ValueError("nonfinite JSON value")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            value,
            parse_constant=reject_nonfinite,
            object_pairs_hook=reject_duplicates,
        )
        if not isinstance(parsed, dict):
            raise TypeError("criteria must be an object")
        canonical = json.dumps(
            parsed,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if len(canonical.encode("utf-8")) > 65_536:
            raise ValueError("canonical criteria is too large")
        return parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ContactDataIntegrityError(
            "saved search criteria is invalid"
        ) from None


async def _remove_materialized_child_link(
    db: AsyncSession,
    *,
    contact_id: int,
    entity_type: str,
    entity_id: int,
    record_kind: str,
    section_name: str,
) -> None:
    rows = (
        await db.execute(
            select(
                CRMEntitySource,
                CRMSourceRecord,
                CRMContactSourceOccurrence,
                CRMContactSectionCapture,
                CRMContactCapturePosition,
            )
            .outerjoin(
                CRMSourceRecord,
                CRMSourceRecord.id == CRMEntitySource.source_record_id,
            )
            .outerjoin(
                CRMContactSourceOccurrence,
                CRMContactSourceOccurrence.source_record_id
                == CRMEntitySource.source_record_id,
            )
            .outerjoin(
                CRMContactSectionCapture,
                CRMContactSectionCapture.id
                == CRMContactSourceOccurrence.section_capture_id,
            )
            .outerjoin(
                CRMContactCapturePosition,
                CRMContactCapturePosition.id
                == CRMContactSectionCapture.capture_position_id,
            )
            .where(
                CRMEntitySource.entity_type == entity_type,
                CRMEntitySource.entity_id == entity_id,
            )
            .with_for_update(of=CRMEntitySource)
        )
    ).all()
    if not rows:
        return
    if len(rows) != 1:
        raise ContactDataIntegrityError("contact source link is invalid")
    link, source, occurrence, section, position = rows[0]
    if (
        source is None
        or occurrence is None
        or section is None
        or position is None
        or source.source_system != "kw_command"
        or source.module != "contacts"
        or source.record_kind != record_kind
        or occurrence.contact_id != contact_id
        or occurrence.source_record_id != source.id
        or section.section_name != section_name
        or section.id != occurrence.section_capture_id
        or position.id != section.capture_position_id
        or position.contact_id != contact_id
    ):
        raise ContactDataIntegrityError("contact source link is invalid")
    await db.delete(link)
    await db.flush()


def _is_contact_tag_uniqueness_error(error: IntegrityError) -> bool:
    diagnostic = getattr(error.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == "uq_crm_contact_tag":
        return True
    driver_origin = getattr(error.orig, "__cause__", None)
    if getattr(driver_origin, "constraint_name", None) == "uq_crm_contact_tag":
        return True
    return (
        "UNIQUE constraint failed: crm_contact_tags.contact_id, crm_contact_tags.tag_id"
    ) in str(error.orig)


async def create_contact(
    db: AsyncSession,
    payload: ContactCreateCommand,
    *,
    actor_subject: str,
) -> ContactDetail:
    """Create one internal contact with its compatibility activity and audit."""
    actor = _validated_actor_subject(actor_subject)
    if not isinstance(payload, ContactCreateCommand):
        raise TypeError("payload must be ContactCreateCommand")
    before_json = canonical_contact_audit_json(
        action="contact.created",
        phase="before",
        payload={},
    )
    try:
        async with db.begin_nested():
            contact = CRMContact(
                first_name=payload.first_name,
                last_name=payload.last_name,
                email=payload.email,
                phone=payload.phone,
                stage=payload.stage,
                birthday=payload.birthday,
                anniversary=payload.anniversary,
            )
            db.add(contact)
            await db.flush()
            try:
                after_json = canonical_contact_audit_json(
                    action="contact.created",
                    phase="after",
                    payload=_contact_audit_fields(contact),
                )
            except (TypeError, ValueError):
                raise ContactDataIntegrityError(
                    "contact audit state is invalid"
                ) from None
            db.add_all(
                [
                    _compatibility_activity(
                        contact_id=contact.id,
                        kind="contact_created",
                        summary="Contact created in Command workspace",
                    ),
                    _contact_audit_event(
                        contact_id=contact.id,
                        actor_subject=actor,
                        action="contact.created",
                        before_json=before_json,
                        after_json=after_json,
                    ),
                ]
            )
            await db.flush()
            detail = await get_contact_detail(db, contact.id)
        return detail
    except ContactDirectoryError:
        raise
    except SQLAlchemyError:
        raise ContactDataIntegrityError(
            "contact mutation could not be completed"
        ) from None


async def update_contact(
    db: AsyncSession,
    contact_id: int,
    payload: ContactUpdateCommand,
    *,
    actor_subject: str,
) -> ContactDetail:
    """Apply one effective internal contact update and its exact audit."""
    actor = _validated_actor_subject(actor_subject)
    if not isinstance(payload, ContactUpdateCommand):
        raise TypeError("payload must be ContactUpdateCommand")
    if type(contact_id) is not int or contact_id <= 0:
        _safe_not_found()
    try:
        async with db.begin_nested():
            contact = (
                await db.scalars(
                    select(CRMContact)
                    .where(CRMContact.id == contact_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
            if contact is None:
                _safe_not_found()
            changed_fields: list[str] = []
            old_values: dict[str, object] = {}
            new_values: dict[str, object] = {}
            for field_name in _CONTACT_MUTATION_FIELDS:
                requested = getattr(payload, field_name)
                if requested is UNSET:
                    continue
                current = getattr(contact, field_name)
                if requested == current:
                    continue
                changed_fields.append(field_name)
                old_values[field_name] = current
                new_values[field_name] = requested

            for field_name in changed_fields:
                setattr(contact, field_name, new_values[field_name])

            if changed_fields:
                ordered_fields = tuple(sorted(changed_fields))
                try:
                    before_json = canonical_contact_audit_json(
                        action="contact.updated",
                        phase="before",
                        payload={
                            "changed_fields": ordered_fields,
                            **old_values,
                        },
                    )
                    after_json = canonical_contact_audit_json(
                        action="contact.updated",
                        phase="after",
                        payload={
                            "changed_fields": ordered_fields,
                            **new_values,
                        },
                    )
                except (TypeError, ValueError):
                    raise ContactDataIntegrityError(
                        "contact audit state is invalid"
                    ) from None
                stage_only = ordered_fields == ("stage",)
                db.add_all(
                    [
                        _compatibility_activity(
                            contact_id=contact.id,
                            kind=(
                                "stage_changed"
                                if stage_only
                                else "contact_updated"
                            ),
                            summary=(
                                "Contact stage changed"
                                if stage_only
                                else "Updated contact profile"
                            ),
                        ),
                        _contact_audit_event(
                            contact_id=contact.id,
                            actor_subject=actor,
                            action="contact.updated",
                            before_json=before_json,
                            after_json=after_json,
                        ),
                    ]
                )
            await db.flush()
            detail = await get_contact_detail(db, contact.id)
        return detail
    except ContactDirectoryError:
        raise
    except SQLAlchemyError:
        raise ContactDataIntegrityError(
            "contact mutation could not be completed"
        ) from None


async def apply_contact_bulk_action(
    db: AsyncSession,
    payload: ContactBulkCommand,
    *,
    actor_subject: str,
) -> ContactBulkResult:
    """Apply one audited action to a sorted, fully validated contact set."""
    actor = _validated_actor_subject(actor_subject)
    if not isinstance(payload, ContactBulkCommand):
        raise TypeError("payload must be ContactBulkCommand")
    requested_ids = tuple(sorted(payload.contact_ids))
    actioned_ids: list[int] = []
    audits: list[CRMContactAuditEvent] = []
    try:
        async with db.begin_nested():
            contacts = (
                await db.scalars(
                    select(CRMContact)
                    .where(CRMContact.id.in_(requested_ids))
                    .order_by(CRMContact.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
            if tuple(contact.id for contact in contacts) != requested_ids:
                _safe_not_found()

            if isinstance(payload.action, ContactBulkSetStage):
                result_action = "set_stage"
                for contact in contacts:
                    old_stage = contact.stage
                    if old_stage == payload.action.stage:
                        continue
                    contact.stage = payload.action.stage
                    actioned_ids.append(contact.id)
                    audits.append(
                        _contact_audit_event(
                            contact_id=contact.id,
                            actor_subject=actor,
                            action="contact.bulk_stage_set",
                            before_json=_canonical_audit(
                                action="contact.bulk_stage_set",
                                phase="before",
                                payload={"stage": old_stage},
                            ),
                            after_json=_canonical_audit(
                                action="contact.bulk_stage_set",
                                phase="after",
                                payload={"stage": contact.stage},
                            ),
                        )
                    )
            else:
                result_action = payload.action.action
                tag = (
                    await db.scalars(
                        select(CRMTag)
                        .where(CRMTag.id == payload.action.tag_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).one_or_none()
                if tag is None:
                    _safe_not_found()
                assignments = (
                    await db.scalars(
                        select(CRMContactTag)
                        .where(
                            CRMContactTag.contact_id.in_(requested_ids),
                            CRMContactTag.tag_id == tag.id,
                        )
                        .order_by(CRMContactTag.contact_id)
                        .with_for_update()
                    )
                ).all()
                assignments_by_contact = {
                    assignment.contact_id: assignment for assignment in assignments
                }

                if isinstance(payload.action, ContactBulkAddTag):
                    raced_contact_ids: list[int] = []
                    for contact in contacts:
                        if contact.id in assignments_by_contact:
                            continue
                        assignment = CRMContactTag(contact_id=contact.id, tag_id=tag.id)
                        try:
                            async with db.begin_nested():
                                db.add(assignment)
                                await db.flush()
                        except IntegrityError as error:
                            if not _is_contact_tag_uniqueness_error(error):
                                raise
                            raced_contact_ids.append(contact.id)
                            continue
                        actioned_ids.append(contact.id)
                        audits.append(
                            _contact_audit_event(
                                contact_id=contact.id,
                                actor_subject=actor,
                                action="contact.bulk_tag_added",
                                before_json=_canonical_audit(
                                    action="contact.bulk_tag_added",
                                    phase="before",
                                    payload={
                                        "present": False,
                                        "tag_id": tag.id,
                                    },
                                ),
                                after_json=_canonical_audit(
                                    action="contact.bulk_tag_added",
                                    phase="after",
                                    payload={
                                        "present": True,
                                        "tag_id": tag.id,
                                    },
                                ),
                            )
                        )
                    if raced_contact_ids:
                        raced_assignments = (
                            await db.scalars(
                                select(CRMContactTag)
                                .where(
                                    CRMContactTag.contact_id.in_(raced_contact_ids),
                                    CRMContactTag.tag_id == tag.id,
                                )
                                .order_by(CRMContactTag.contact_id)
                                .with_for_update()
                            )
                        ).all()
                        if tuple(
                            assignment.contact_id for assignment in raced_assignments
                        ) != tuple(raced_contact_ids):
                            raise ContactDataIntegrityError(
                                "contact tag race could not be reconciled"
                            )
                elif isinstance(payload.action, ContactBulkRemoveTag):
                    for contact in contacts:
                        assignment = assignments_by_contact.get(contact.id)
                        if assignment is None:
                            continue
                        await db.delete(assignment)
                        await db.flush()
                        actioned_ids.append(contact.id)
                        audits.append(
                            _contact_audit_event(
                                contact_id=contact.id,
                                actor_subject=actor,
                                action="contact.bulk_tag_removed",
                                before_json=_canonical_audit(
                                    action="contact.bulk_tag_removed",
                                    phase="before",
                                    payload={
                                        "present": True,
                                        "tag_id": tag.id,
                                    },
                                ),
                                after_json=_canonical_audit(
                                    action="contact.bulk_tag_removed",
                                    phase="after",
                                    payload={
                                        "present": False,
                                        "tag_id": tag.id,
                                    },
                                ),
                            )
                        )
                else:  # pragma: no cover - ContactBulkCommand rejects this.
                    raise TypeError("bulk action is invalid")

            db.add_all(audits)
            await db.flush()
            return ContactBulkResult(
                requested_contact_ids=requested_ids,
                actioned_contact_ids=tuple(actioned_ids),
                action=result_action,
            )
    except ContactDirectoryError:
        raise
    except IntegrityError as error:
        if "crm_contact_tags" in str(error.statement).casefold():
            raise
        raise ContactDataIntegrityError(
            "contact mutation could not be completed"
        ) from None
    except SQLAlchemyError:
        raise ContactDataIntegrityError(
            "contact mutation could not be completed"
        ) from None


async def sync_legacy_leads(
    db: AsyncSession,
    *,
    actor_subject: str,
) -> ContactLegacySyncResult:
    """Project legacy leads into contacts without mutating linked rows."""
    actor = _validated_actor_subject(actor_subject)
    created_count = 0
    backfilled_count = 0
    scanned_count = 0
    last_lead_id = 0
    try:
        async with db.begin_nested():
            while True:
                leads = (
                    await db.scalars(
                        select(Lead)
                        .where(Lead.id > last_lead_id)
                        .order_by(Lead.id)
                        .limit(500)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).all()
                if not leads:
                    break
                last_lead_id = leads[-1].id
                scanned_count += len(leads)
                lead_ids = tuple(lead.id for lead in leads)
                linked_contacts = (
                    await db.scalars(
                        select(CRMContact)
                        .where(CRMContact.lead_id.in_(lead_ids))
                        .order_by(CRMContact.id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).all()
                contacts_by_lead_id = {
                    contact.lead_id: contact for contact in linked_contacts
                }
                linked_contact_ids = tuple(contact.id for contact in linked_contacts)
                exact_markers = (
                    await db.scalars(
                        select(CRMActivity)
                        .where(
                            CRMActivity.contact_id.in_(linked_contact_ids),
                            CRMActivity.kind == "lead_imported",
                            CRMActivity.summary == "Imported from internal lead source",
                            CRMActivity.source_record_id.is_(None),
                            CRMActivity.metadata_json == "{}",
                        )
                        .order_by(CRMActivity.contact_id, CRMActivity.id)
                        .with_for_update()
                    )
                ).all()
                marker_contact_ids = {marker.contact_id for marker in exact_markers}

                pending_new: list[tuple[Lead, ContactCreateCommand, CRMContact]] = []
                for lead in leads:
                    if lead.id in contacts_by_lead_id:
                        continue
                    parts = (lead.name or "Unnamed contact").strip().split(maxsplit=1)
                    if not parts:
                        raise ContactDataIntegrityError(
                            "legacy lead cannot be synchronized"
                        )
                    try:
                        command = ContactCreateCommand(
                            first_name=parts[0],
                            last_name=parts[1] if len(parts) > 1 else "",
                            email=lead.email,
                            phone=lead.phone,
                            stage=lead.routing_status or "lead",
                        )
                    except (TypeError, ValueError):
                        raise ContactDataIntegrityError(
                            "legacy lead cannot be synchronized"
                        ) from None
                    contact = CRMContact(
                        lead_id=lead.id,
                        first_name=command.first_name,
                        last_name=command.last_name,
                        email=command.email,
                        phone=command.phone,
                        stage=command.stage,
                        birthday=None,
                        anniversary=None,
                    )
                    pending_new.append((lead, command, contact))
                    contacts_by_lead_id[lead.id] = contact
                db.add_all([row[2] for row in pending_new])
                await db.flush()

                pending_markers: list[tuple[Lead, CRMContact, CRMActivity, bool]] = []
                new_lead_ids = {lead.id for lead, _command, _contact in pending_new}
                for lead in leads:
                    contact = contacts_by_lead_id[lead.id]
                    is_new = lead.id in new_lead_ids
                    if not is_new and contact.id in marker_contact_ids:
                        continue
                    marker = _compatibility_activity(
                        contact_id=contact.id,
                        kind="lead_imported",
                        summary="Imported from internal lead source",
                    )
                    pending_markers.append((lead, contact, marker, is_new))
                db.add_all([row[2] for row in pending_markers])
                await db.flush()

                audits: list[CRMContactAuditEvent] = []
                for lead, contact, marker, is_new in pending_markers:
                    if is_new:
                        before_json = canonical_contact_audit_json(
                            action="contact.legacy_sync_applied",
                            phase="before",
                            payload={},
                        )
                        after_json = canonical_contact_audit_json(
                            action="contact.legacy_sync_applied",
                            phase="after",
                            payload={
                                "email": contact.email,
                                "first_name": contact.first_name,
                                "last_name": contact.last_name,
                                "phone": contact.phone,
                                "stage": contact.stage,
                                "lead_id": lead.id,
                            },
                        )
                        created_count += 1
                    else:
                        before_json = canonical_contact_audit_json(
                            action="contact.legacy_sync_applied",
                            phase="before",
                            payload={
                                "activity_present": False,
                                "lead_id": lead.id,
                            },
                        )
                        after_json = canonical_contact_audit_json(
                            action="contact.legacy_sync_applied",
                            phase="after",
                            payload={
                                "activity_present": True,
                                "activity_id": marker.id,
                                "lead_id": lead.id,
                            },
                        )
                        backfilled_count += 1
                    audits.append(
                        _contact_audit_event(
                            contact_id=contact.id,
                            actor_subject=actor,
                            action="contact.legacy_sync_applied",
                            before_json=before_json,
                            after_json=after_json,
                        )
                    )
                db.add_all(audits)
                await db.flush()
        return ContactLegacySyncResult(
            created=created_count,
            timeline_backfilled=backfilled_count,
            total_legacy_leads=scanned_count,
        )
    except ContactDirectoryError:
        raise
    except (TypeError, ValueError):
        raise ContactDataIntegrityError("legacy lead cannot be synchronized") from None
    except SQLAlchemyError:
        raise ContactDataIntegrityError(
            "contact mutation could not be completed"
        ) from None


async def assign_contact_tag(
    db: AsyncSession,
    contact_id: int,
    tag_id: int,
    *,
    actor_subject: str,
) -> ContactMutationResult:
    """Assign one tag, recovering only the exact assignment uniqueness race."""
    actor = _validated_actor_subject(actor_subject)
    if type(contact_id) is not int or contact_id <= 0:
        _safe_not_found()
    if type(tag_id) is not int or tag_id <= 0:
        _safe_not_found()
    try:
        async with db.begin_nested():
            contact = await _lock_contact(db, contact_id)
            tag = (
                await db.scalars(
                    select(CRMTag)
                    .where(CRMTag.id == tag_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
            if tag is None:
                _safe_not_found()
            existing = (
                await db.scalars(
                    select(CRMContactTag)
                    .where(
                        CRMContactTag.contact_id == contact.id,
                        CRMContactTag.tag_id == tag.id,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if existing is not None:
                return ContactMutationResult(
                    contact_id=contact.id,
                    record_id=existing.id,
                    changed=False,
                    audit_entity_type=None,
                    audit_event_id=None,
                )
            link = CRMContactTag(contact_id=contact.id, tag_id=tag.id)
            try:
                async with db.begin_nested():
                    db.add(link)
                    await db.flush()
            except IntegrityError as error:
                if not _is_contact_tag_uniqueness_error(error):
                    raise
                existing = (
                    await db.scalars(
                        select(CRMContactTag).where(
                            CRMContactTag.contact_id == contact.id,
                            CRMContactTag.tag_id == tag.id,
                        )
                    )
                ).one_or_none()
                if existing is None:
                    raise
                return ContactMutationResult(
                    contact_id=contact.id,
                    record_id=existing.id,
                    changed=False,
                    audit_entity_type=None,
                    audit_event_id=None,
                )
            audit = _contact_audit_event(
                contact_id=contact.id,
                actor_subject=actor,
                action="contact.tag_added",
                before_json=_canonical_audit(
                    action="contact.tag_added",
                    phase="before",
                    payload={"present": False, "tag_id": tag.id},
                ),
                after_json=_canonical_audit(
                    action="contact.tag_added",
                    phase="after",
                    payload={"present": True, "tag_id": tag.id},
                ),
            )
            db.add(audit)
            await db.flush()
            return ContactMutationResult(
                contact_id=contact.id,
                record_id=link.id,
                changed=True,
                audit_entity_type="contact_audit",
                audit_event_id=audit.id,
            )
    except ContactDirectoryError:
        raise
    except IntegrityError as error:
        if "crm_contact_tags" in str(error.statement).casefold():
            raise
        raise ContactDataIntegrityError(
            "contact mutation could not be completed"
        ) from None
    except SQLAlchemyError:
        raise ContactDataIntegrityError(
            "contact mutation could not be completed"
        ) from None


async def remove_contact_tag(
    db: AsyncSession,
    contact_id: int,
    tag_id: int,
    *,
    actor_subject: str,
) -> ContactMutationResult:
    """Remove one assignment, treating an absent assignment as a no-op."""
    actor = _validated_actor_subject(actor_subject)
    if type(contact_id) is not int or contact_id <= 0:
        _safe_not_found()
    if type(tag_id) is not int or tag_id <= 0:
        _safe_not_found()
    try:
        async with db.begin_nested():
            contact = await _lock_contact(db, contact_id)
            tag = (
                await db.scalars(
                    select(CRMTag)
                    .where(CRMTag.id == tag_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
            if tag is None:
                _safe_not_found()
            link = (
                await db.scalars(
                    select(CRMContactTag)
                    .where(
                        CRMContactTag.contact_id == contact.id,
                        CRMContactTag.tag_id == tag.id,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if link is None:
                return ContactMutationResult(
                    contact_id=contact.id,
                    record_id=None,
                    changed=False,
                    audit_entity_type=None,
                    audit_event_id=None,
                )
            record_id = link.id
            await db.delete(link)
            audit = _contact_audit_event(
                contact_id=contact.id,
                actor_subject=actor,
                action="contact.tag_removed",
                before_json=_canonical_audit(
                    action="contact.tag_removed",
                    phase="before",
                    payload={"present": True, "tag_id": tag.id},
                ),
                after_json=_canonical_audit(
                    action="contact.tag_removed",
                    phase="after",
                    payload={"present": False, "tag_id": tag.id},
                ),
            )
            db.add_all(
                [
                    _compatibility_activity(
                        contact_id=contact.id,
                        kind="tag_removed",
                        summary="Removed a contact tag",
                    ),
                    audit,
                ]
            )
            await db.flush()
            return ContactMutationResult(
                contact_id=contact.id,
                record_id=record_id,
                changed=True,
                audit_entity_type="contact_audit",
                audit_event_id=audit.id,
            )
    except ContactDirectoryError:
        raise
    except SQLAlchemyError:
        raise ContactDataIntegrityError(
            "contact mutation could not be completed"
        ) from None


async def create_contact_note(
    db: AsyncSession,
    contact_id: int,
    payload: ContactNoteCreateCommand,
    *,
    actor_subject: str,
) -> ContactMutationResult:
    """Create one internal contact note with activity and audit."""
    actor = _validated_actor_subject(actor_subject)
    if not isinstance(payload, ContactNoteCreateCommand):
        raise TypeError("payload must be ContactNoteCreateCommand")
    if type(contact_id) is not int or contact_id <= 0:
        _safe_not_found()
    try:
        async with db.begin_nested():
            contact = await _lock_contact(db, contact_id)
            note = CRMNote(contact_id=contact.id, body=payload.body)
            db.add(note)
            await db.flush()
            audit = _contact_audit_event(
                contact_id=contact.id,
                actor_subject=actor,
                action="contact.note_created",
                before_json=_canonical_audit(
                    action="contact.note_created",
                    phase="before",
                    payload={
                        "body": note.body,
                        "note_id": note.id,
                        "present": False,
                    },
                ),
                after_json=_canonical_audit(
                    action="contact.note_created",
                    phase="after",
                    payload={
                        "body": note.body,
                        "note_id": note.id,
                        "present": True,
                    },
                ),
            )
            db.add_all(
                [
                    _compatibility_activity(
                        contact_id=contact.id,
                        kind="note",
                        summary="Added a contact note",
                    ),
                    audit,
                ]
            )
            await db.flush()
            return ContactMutationResult(
                contact_id=contact.id,
                record_id=note.id,
                changed=True,
                audit_entity_type="contact_audit",
                audit_event_id=audit.id,
            )
    except ContactDirectoryError:
        raise
    except SQLAlchemyError:
        raise ContactDataIntegrityError(
            "contact mutation could not be completed"
        ) from None


async def delete_contact_note(
    db: AsyncSession,
    contact_id: int,
    note_id: int,
    *,
    actor_subject: str,
) -> ContactMutationResult:
    """Delete one same-contact note without dangling its source evidence."""
    actor = _validated_actor_subject(actor_subject)
    if (
        type(contact_id) is not int
        or contact_id <= 0
        or type(note_id) is not int
        or note_id <= 0
    ):
        _safe_not_found()
    try:
        async with db.begin_nested():
            contact = await _lock_contact(db, contact_id)
            note = (
                await db.scalars(
                    select(CRMNote)
                    .where(
                        CRMNote.id == note_id,
                        CRMNote.contact_id == contact.id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
            if note is None:
                _safe_not_found()
            await _remove_materialized_child_link(
                db,
                contact_id=contact.id,
                entity_type="note",
                entity_id=note.id,
                record_kind="contact_note",
                section_name="notes",
            )
            audit = _contact_audit_event(
                contact_id=contact.id,
                actor_subject=actor,
                action="contact.note_deleted",
                before_json=_canonical_audit(
                    action="contact.note_deleted",
                    phase="before",
                    payload={
                        "body": note.body,
                        "note_id": note.id,
                        "present": True,
                    },
                ),
                after_json=_canonical_audit(
                    action="contact.note_deleted",
                    phase="after",
                    payload={
                        "body": note.body,
                        "note_id": note.id,
                        "present": False,
                    },
                ),
            )
            record_id = note.id
            await db.delete(note)
            db.add_all(
                [
                    _compatibility_activity(
                        contact_id=contact.id,
                        kind="note_removed",
                        summary="Removed a contact note",
                    ),
                    audit,
                ]
            )
            await db.flush()
            return ContactMutationResult(
                contact_id=contact.id,
                record_id=record_id,
                changed=True,
                audit_entity_type="contact_audit",
                audit_event_id=audit.id,
            )
    except ContactDirectoryError:
        raise
    except SQLAlchemyError:
        raise ContactDataIntegrityError(
            "contact mutation could not be completed"
        ) from None


async def create_contact_saved_search(
    db: AsyncSession,
    contact_id: int,
    payload: ContactSavedSearchCreateCommand,
    *,
    actor_subject: str,
) -> ContactMutationResult:
    """Create one contact-owned saved search and its redacted audit."""
    actor = _validated_actor_subject(actor_subject)
    if not isinstance(payload, ContactSavedSearchCreateCommand):
        raise TypeError("payload must be ContactSavedSearchCreateCommand")
    if type(contact_id) is not int or contact_id <= 0:
        _safe_not_found()
    criteria_json = _canonical_criteria(payload.criteria)
    try:
        async with db.begin_nested():
            contact = await _lock_contact(db, contact_id)
            search = CRMSavedSearch(
                contact_id=contact.id,
                name=payload.name,
                criteria_json=criteria_json,
            )
            db.add(search)
            await db.flush()
            audit = _contact_audit_event(
                contact_id=contact.id,
                actor_subject=actor,
                action="contact.saved_search_created",
                before_json=_canonical_audit(
                    action="contact.saved_search_created",
                    phase="before",
                    payload={
                        "criteria": criteria_json,
                        "name": search.name,
                        "present": False,
                        "search_id": search.id,
                    },
                ),
                after_json=_canonical_audit(
                    action="contact.saved_search_created",
                    phase="after",
                    payload={
                        "criteria": criteria_json,
                        "name": search.name,
                        "present": True,
                        "search_id": search.id,
                    },
                ),
            )
            db.add(audit)
            await db.flush()
            return ContactMutationResult(
                contact_id=contact.id,
                record_id=search.id,
                changed=True,
                audit_entity_type="contact_audit",
                audit_event_id=audit.id,
            )
    except ContactDirectoryError:
        raise
    except SQLAlchemyError:
        raise ContactDataIntegrityError(
            "contact mutation could not be completed"
        ) from None


async def list_saved_searches(
    db: AsyncSession,
) -> tuple[ContactSavedSearchValue, ...]:
    """List global and contact-owned searches without flushing caller state."""
    with db.no_autoflush:
        rows = (
            await db.execute(
                select(
                    CRMSavedSearch,
                    CRMContact.id,
                    CRMContact.first_name,
                    CRMContact.last_name,
                )
                .outerjoin(
                    CRMContact, CRMContact.id == CRMSavedSearch.contact_id
                )
                .order_by(
                    CRMSavedSearch.updated_at.desc(),
                    CRMSavedSearch.id.desc(),
                )
            )
        ).all()
    result: list[ContactSavedSearchValue] = []
    for search, owner_id, first_name, last_name in rows:
        if search.contact_id is not None and owner_id != search.contact_id:
            raise ContactDataIntegrityError("saved search ownership is invalid")
        criteria = _parse_canonical_criteria(search.criteria_json)
        updated_at = _section_datetime(search.updated_at)
        if updated_at is None:
            raise ContactDataIntegrityError("saved search timestamp is invalid")
        contact_name = None
        if owner_id is not None:
            contact_name = f"{first_name} {last_name}".strip()
        result.append(
            ContactSavedSearchValue(
                id=search.id,
                contact_id=search.contact_id,
                contact_name=contact_name,
                name=search.name,
                criteria=criteria,
                updated_at=updated_at,
            )
        )
    return tuple(result)


async def delete_saved_search(
    db: AsyncSession,
    search_id: int,
    *,
    actor_subject: str,
) -> SavedSearchDeletionResult:
    """Delete one contact-owned or global saved search under exact locking."""
    actor = _validated_actor_subject(actor_subject)
    if type(search_id) is not int or search_id <= 0:
        _safe_not_found()
    try:
        async with db.begin_nested():
            candidate = (
                await db.execute(
                    select(CRMSavedSearch.id, CRMSavedSearch.contact_id).where(
                        CRMSavedSearch.id == search_id
                    )
                )
            ).one_or_none()
            if candidate is None:
                _safe_not_found()
            candidate_contact_id = candidate.contact_id
            if candidate_contact_id is not None:
                contact = await _lock_contact(db, candidate_contact_id)
                search = (
                    await db.scalars(
                        select(CRMSavedSearch)
                        .where(
                            CRMSavedSearch.id == search_id,
                            CRMSavedSearch.contact_id == contact.id,
                        )
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).one_or_none()
                if search is None:
                    raise ContactDataIntegrityError(
                        "saved search ownership changed"
                    )
                criteria_json = _canonical_criteria(
                    _parse_canonical_criteria(search.criteria_json)
                )
                await _remove_materialized_child_link(
                    db,
                    contact_id=contact.id,
                    entity_type="saved_search",
                    entity_id=search.id,
                    record_kind="contact_saved_search",
                    section_name="saved_searches",
                )
                audit = _contact_audit_event(
                    contact_id=contact.id,
                    actor_subject=actor,
                    action="contact.saved_search_deleted",
                    before_json=_canonical_audit(
                        action="contact.saved_search_deleted",
                        phase="before",
                        payload={
                            "criteria": criteria_json,
                            "name": search.name,
                            "present": True,
                            "search_id": search.id,
                        },
                    ),
                    after_json=_canonical_audit(
                        action="contact.saved_search_deleted",
                        phase="after",
                        payload={
                            "criteria": criteria_json,
                            "name": search.name,
                            "present": False,
                            "search_id": search.id,
                        },
                    ),
                )
                record_id = search.id
                await db.delete(search)
                db.add(audit)
                await db.flush()
                return ContactMutationResult(
                    contact_id=contact.id,
                    record_id=record_id,
                    changed=True,
                    audit_entity_type="contact_audit",
                    audit_event_id=audit.id,
                )

            search = (
                await db.scalars(
                    select(CRMSavedSearch)
                    .where(
                        CRMSavedSearch.id == search_id,
                        CRMSavedSearch.contact_id.is_(None),
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
            if search is None:
                raise ContactDataIntegrityError(
                    "saved search ownership changed"
                )
            links = (
                await db.scalars(
                    select(CRMEntitySource).where(
                        CRMEntitySource.entity_type == "saved_search",
                        CRMEntitySource.entity_id == search.id,
                    )
                )
            ).all()
            if links:
                raise ContactDataIntegrityError("contact source link is invalid")
            metadata = _canonical_workspace_saved_search_audit(
                actor_subject=actor,
                search_id=search.id,
                name=search.name,
            )
            activity = CRMActivity(
                contact_id=None,
                kind="workspace.saved_search_deleted",
                summary="Saved search deleted",
                source_record_id=None,
                metadata_json=metadata,
            )
            record_id = search.id
            await db.delete(search)
            db.add(activity)
            await db.flush()
            return WorkspaceMutationResult(
                record_id=record_id,
                changed=True,
                audit_entity_type="workspace_activity",
                audit_event_id=activity.id,
            )
    except ContactDirectoryError:
        raise
    except SQLAlchemyError:
        raise ContactDataIntegrityError(
            "contact mutation could not be completed"
        ) from None


__all__ = [
    "ContactDataIntegrityError",
    "ContactDirectoryError",
    "ContactLinkConflict",
    "ContactNotFound",
    "ContactNotInDirectory",
    "ContactSectionUnsupported",
    "apply_contact_bulk_action",
    "assign_contact_tag",
    "create_contact",
    "create_contact_note",
    "create_contact_saved_search",
    "delete_contact_note",
    "delete_saved_search",
    "get_contact_detail",
    "get_contact_evidence",
    "get_contact_neighbors",
    "get_contact_workspace_summary",
    "list_contact_celebrations",
    "list_contacts",
    "list_saved_searches",
    "remove_contact_tag",
    "sync_legacy_leads",
    "update_contact",
]
