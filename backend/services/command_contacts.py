"""Framework-neutral query and mutation services for Command Contacts."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import NoReturn

from sqlalchemy import (
    Select,
    and_,
    case,
    exists,
    extract,
    func,
    literal,
    not_,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from models.command import (
    CRMActivity,
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
    CRMContactCapturePosition,
    CRMContactMethod,
    CRMContactOwnership,
    CRMContactProfile,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
    CRMContactTimelineEvent,
)
from models.command_provenance import CRMEntitySource, CRMSourceRecord
from services.command_contact_contracts import (
    CONTACT_TOUCH_ACTIVITY_KINDS,
    CaptureQualityValue,
    ContactActorValue,
    ContactAddressValue,
    ContactCelebrationRow,
    ContactCelebrations,
    ContactCelebrationValue,
    ContactDetail,
    ContactDirectoryFilters,
    ContactDirectoryPage,
    ContactDirectoryRow,
    ContactNeighbors,
    ContactOriginFilter,
    ContactRecoveredProfile,
    ContactSmartView,
    ContactSortKey,
    ContactSourceFilter,
    ContactTagValue,
    ContactWorkspaceSummary,
    SortDirection,
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
    try:
        payload = json.loads(source.payload_json)
    except (TypeError, ValueError):
        raise ContactDataIntegrityError(
            "contact occurrence payload is invalid"
        ) from None
    if not isinstance(payload, dict):
        raise ContactDataIntegrityError("contact occurrence payload is invalid")
    values = payload.get("values")
    if not isinstance(values, dict):
        return {}
    return values


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
            if section.section_name == "smart_plans":
                status = _occurrence_values(source).get("status")
                if not isinstance(status, str) or status.strip().casefold() != "active":
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


__all__ = [
    "ContactDataIntegrityError",
    "ContactDirectoryError",
    "ContactLinkConflict",
    "ContactNotFound",
    "ContactNotInDirectory",
    "ContactSectionUnsupported",
    "get_contact_detail",
    "get_contact_neighbors",
    "get_contact_workspace_summary",
    "list_contact_celebrations",
    "list_contacts",
]
