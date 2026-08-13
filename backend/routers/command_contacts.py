"""Read-only HTTP boundary for the focused Command Contacts workspace."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal, TypeVar

from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from middleware.auth import AdminSubject
from models.booking import Booking
from models.command import (
    CRMActivity,
    CRMContact,
    CRMContactTag,
    CRMNote,
    CRMOpportunity,
    CRMOpportunityContact,
    CRMSavedSearch,
    CRMSmartPlanEnrollment,
    CRMTag,
    CRMTask,
)
from models.lead import Lead
from pydantic import BeforeValidator, TypeAdapter
from schemas.command_contacts import (
    ContactCelebrationsOut,
    ContactDetailOut,
    ContactDirectoryPageOut,
    ContactDirectoryQueryIn,
    ContactEvidenceOut,
    ContactNeighborsOut,
    ContactSectionPageOut,
    ContactTimelinePageOut,
    ContactWorkspaceSummaryOut,
    LegacyContactOut,
    LegacyContactWorkspaceOut,
)
from services.command_contact_contracts import (
    ContactDirectoryFilters,
    ContactSection,
    decode_timeline_cursor,
)
from services.command_contact_identity import canonical_email
from services.command_contact_timeline import (
    ContactNotFound as TimelineContactNotFound,
)
from services.command_contact_timeline import (
    ContactTimelineIntegrityError,
    count_contact_bookings,
    list_contact_timeline,
)
from services.command_contacts import (
    ContactDataIntegrityError,
    ContactLinkConflict,
    ContactNotFound,
    ContactNotInDirectory,
    ContactSectionUnsupported,
    get_contact_detail,
    get_contact_evidence,
    get_contact_neighbors,
    get_contact_workspace_summary,
    list_contact_celebrations,
    list_contact_section,
    list_contacts,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

DatabaseDependency = Annotated[AsyncSession, Depends(get_db)]
_Result = TypeVar("_Result")
TaskState = Literal["to_do", "completed", "archived"]


def _canonical_http_integer(value: object) -> int:
    if type(value) is int:
        return value
    if (
        type(value) is str
        and value.isascii()
        and value.isdigit()
        and (value == "0" or not value.startswith("0"))
    ):
        return int(value)
    raise ValueError("integer input must be a canonical unsigned decimal")


ContactId = Annotated[
    int,
    Path(gt=0),
    BeforeValidator(_canonical_http_integer),
]
Page = Annotated[
    int,
    Query(ge=1),
    BeforeValidator(_canonical_http_integer),
]
PageSize = Annotated[
    int,
    Query(ge=1, le=100),
    BeforeValidator(_canonical_http_integer),
]
LegacyLimit = Annotated[
    int,
    Query(ge=1, le=100),
    BeforeValidator(_canonical_http_integer),
]
LegacyOffset = Annotated[
    int,
    Query(ge=0),
    BeforeValidator(_canonical_http_integer),
]
CelebrationMonth = Annotated[
    int,
    Query(ge=1, le=12),
    BeforeValidator(_canonical_http_integer),
]

_DIRECTORY_PAGE_ADAPTER = TypeAdapter(ContactDirectoryPageOut)
_LEGACY_CONTACTS_ADAPTER = TypeAdapter(list[LegacyContactOut])
_CELEBRATIONS_ADAPTER = TypeAdapter(ContactCelebrationsOut)
_DETAIL_ADAPTER = TypeAdapter(ContactDetailOut)
_NEIGHBORS_ADAPTER = TypeAdapter(ContactNeighborsOut)
_WORKSPACE_SUMMARY_ADAPTER = TypeAdapter(ContactWorkspaceSummaryOut)
_LEGACY_WORKSPACE_ADAPTER = TypeAdapter(LegacyContactWorkspaceOut)
_TIMELINE_ADAPTER = TypeAdapter(ContactTimelinePageOut)
_SECTION_PAGE_ADAPTER = TypeAdapter(ContactSectionPageOut)
_EVIDENCE_ADAPTER = TypeAdapter(ContactEvidenceOut)


async def _run_read(
    db: AsyncSession,
    operation: Callable[[], Awaitable[_Result]],
    adapter: TypeAdapter,
) -> object:
    try:
        with db.no_autoflush:
            value = await operation()
            return adapter.validate_python(value)
    except (ContactNotFound, TimelineContactNotFound):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found",
        ) from None
    except (
        ContactNotInDirectory,
        ContactDataIntegrityError,
        ContactLinkConflict,
        ContactTimelineIntegrityError,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Contact data is unavailable",
        ) from None
    except ContactSectionUnsupported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Contact section is unsupported",
        ) from None
    except HTTPException:
        raise
    # The HTTP boundary must redact all unexpected service and response-validation
    # failures; callers never receive exception text or values.
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load contact data",
        ) from None


def _now() -> datetime:
    return datetime.now(UTC)


def _request_filters(filters: ContactDirectoryQueryIn) -> ContactDirectoryFilters:
    try:
        return filters.to_filters()
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Contact filters are invalid",
        ) from None


async def _list_legacy_contacts(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    query: str | None,
    stage: str | None,
) -> list[CRMContact]:
    statement = select(CRMContact)
    if query and (term := query.strip()):
        needle = f"%{term}%"
        statement = statement.where(
            or_(
                CRMContact.first_name.ilike(needle),
                CRMContact.last_name.ilike(needle),
                CRMContact.email.ilike(needle),
                CRMContact.phone.ilike(needle),
            )
        )
    if stage is not None:
        statement = statement.where(CRMContact.stage == stage)
    statement = (
        statement.order_by(CRMContact.created_at.desc(), CRMContact.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(await db.scalars(statement))


@dataclass(frozen=True, slots=True)
class _WorkspaceBookingOwner:
    lead_id: int | None
    normalized_email: str | None


async def _workspace_booking_owner_snapshot(
    db: AsyncSession,
    *,
    contact_id: int,
) -> _WorkspaceBookingOwner | None:
    contact_row = (
        await db.execute(
            select(
                CRMContact.id.label("contact_id"),
                CRMContact.lead_id,
                CRMContact.email,
                CRMContact.normalized_email,
                Lead.id.label("resolved_lead_id"),
            )
            .outerjoin(Lead, Lead.id == CRMContact.lead_id)
            .where(CRMContact.id == contact_id)
            .limit(1)
        )
    ).one_or_none()
    if contact_row is None:
        raise TimelineContactNotFound("contact does not exist")
    if canonical_email(contact_row.email) != contact_row.normalized_email:
        raise ContactTimelineIntegrityError("contact email normalization is invalid")
    if contact_row.lead_id is not None:
        if contact_row.resolved_lead_id is None:
            raise ContactTimelineIntegrityError("linked lead is unavailable")
        return _WorkspaceBookingOwner(
            lead_id=contact_row.lead_id,
            normalized_email=None,
        )

    normalized_email = canonical_email(contact_row.email)
    if normalized_email is None:
        return None
    owner_rows = (
        await db.execute(
            select(
                CRMContact.id,
                CRMContact.email,
                CRMContact.normalized_email,
            )
            .where(CRMContact.normalized_email == normalized_email)
            .order_by(CRMContact.id)
            .limit(2)
        )
    ).all()
    if any(
        canonical_email(owner.email) != owner.normalized_email for owner in owner_rows
    ):
        raise ContactTimelineIntegrityError("contact email normalization is invalid")
    if len(owner_rows) != 1 or owner_rows[0].id != contact_id:
        return None
    return _WorkspaceBookingOwner(
        lead_id=None,
        normalized_email=normalized_email,
    )


async def _legacy_contact_workspace(
    db: AsyncSession,
    *,
    contact_id: int,
) -> dict[str, object]:
    contact = await db.get(CRMContact, contact_id)
    if contact is None:
        raise ContactNotFound("contact does not exist")

    tasks = list(
        await db.scalars(
            select(CRMTask)
            .where(CRMTask.contact_id == contact_id)
            .order_by(CRMTask.created_at.desc())
        )
    )
    notes = list(
        await db.scalars(
            select(CRMNote)
            .where(CRMNote.contact_id == contact_id)
            .order_by(CRMNote.created_at.desc())
        )
    )
    activities = list(
        await db.scalars(
            select(CRMActivity)
            .where(CRMActivity.contact_id == contact_id)
            .order_by(CRMActivity.created_at.desc())
        )
    )
    enrollments = list(
        await db.scalars(
            select(CRMSmartPlanEnrollment).where(
                CRMSmartPlanEnrollment.contact_id == contact_id
            )
        )
    )
    opportunity_rows = (
        await db.execute(
            select(CRMOpportunity, CRMOpportunityContact.role)
            .join(
                CRMOpportunityContact,
                CRMOpportunity.id == CRMOpportunityContact.opportunity_id,
            )
            .where(CRMOpportunityContact.contact_id == contact_id)
            .order_by(CRMOpportunity.created_at.desc())
        )
    ).all()
    searches = list(
        await db.scalars(
            select(CRMSavedSearch).where(CRMSavedSearch.contact_id == contact_id)
        )
    )
    tags = list(
        await db.scalars(
            select(CRMTag)
            .join(CRMContactTag, CRMTag.id == CRMContactTag.tag_id)
            .where(CRMContactTag.contact_id == contact_id)
        )
    )
    booking_owner = await _workspace_booking_owner_snapshot(
        db,
        contact_id=contact_id,
    )
    booking_count = await count_contact_bookings(db, contact_id)
    if booking_owner != await _workspace_booking_owner_snapshot(
        db,
        contact_id=contact_id,
    ):
        raise ContactTimelineIntegrityError("booking ownership changed during read")
    if booking_owner is None:
        if booking_count != 0:
            raise ContactTimelineIntegrityError("booking ownership changed during read")
        bookings = []
    elif booking_owner.lead_id is not None:
        bookings = list(
            await db.scalars(
                select(Booking)
                .where(Booking.lead_id == booking_owner.lead_id)
                .order_by(Booking.scheduled_at.desc())
                .execution_options(populate_existing=True)
            )
        )
    else:
        assert booking_owner.normalized_email is not None
        bookings = list(
            await db.scalars(
                select(Booking)
                .where(
                    Booking.lead_id.is_(None),
                    Booking.normalized_email == booking_owner.normalized_email,
                )
                .order_by(Booking.scheduled_at.desc())
                .execution_options(populate_existing=True)
            )
        )
    if any(canonical_email(item.email) != item.normalized_email for item in bookings):
        raise ContactTimelineIntegrityError("booking email normalization is invalid")
    if booking_owner is not None and any(
        (
            item.lead_id != booking_owner.lead_id
            if booking_owner.lead_id is not None
            else item.lead_id is not None
            or item.normalized_email != booking_owner.normalized_email
        )
        for item in bookings
    ):
        raise ContactTimelineIntegrityError("booking ownership changed during read")
    if len(bookings) != booking_count:
        raise ContactTimelineIntegrityError("booking ownership changed during read")
    if booking_owner != await _workspace_booking_owner_snapshot(
        db,
        contact_id=contact_id,
    ):
        raise ContactTimelineIntegrityError("booking ownership changed during read")
    return {
        "contact": contact,
        "timeline": [
            {
                "id": item.id,
                "kind": item.kind,
                "summary": item.summary,
                "created_at": item.created_at,
            }
            for item in activities
        ],
        "tasks": tasks,
        "notes": notes,
        "smart_plans": [
            {
                "id": item.id,
                "plan_id": item.smart_plan_id,
                "status": item.status,
            }
            for item in enrollments
        ],
        "opportunities": [
            {
                "id": item.id,
                "name": item.name,
                "stage": item.stage,
                "value_cents": item.value_cents,
                "role": role,
            }
            for item, role in opportunity_rows
        ],
        "saved_searches": [
            {"id": item.id, "name": item.name, "criteria": item.criteria_json}
            for item in searches
        ],
        "bookings": [
            {
                "id": item.id,
                "meeting_type": item.meeting_type,
                "context": item.context,
                "scheduled_at": item.scheduled_at,
                "location": item.location,
                "notes": item.notes,
            }
            for item in bookings
        ],
        "tags": [{"id": item.id, "name": item.name} for item in tags],
    }


# Static reads are declared before every dynamic contact path. Slice C inserts
# the three static mutations between directory and the legacy compatibility read.
@router.get("/contacts/directory", response_model=ContactDirectoryPageOut)
async def contact_directory(
    filters: Annotated[ContactDirectoryQueryIn, Query()],
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    _actor_subject = actor_subject
    request_filters = _request_filters(filters)
    return await _run_read(
        db,
        lambda: list_contacts(db, request_filters, now=_now()),
        _DIRECTORY_PAGE_ADAPTER,
    )


# Slice C inserts POST /contacts after this compatibility read.
@router.get("/contacts", response_model=list[LegacyContactOut])
async def legacy_contacts(
    actor_subject: AdminSubject,
    db: DatabaseDependency,
    limit: LegacyLimit = 50,
    offset: LegacyOffset = 0,
    query: str | None = None,
    stage: str | None = None,
) -> object:
    _actor_subject = actor_subject
    return await _run_read(
        db,
        lambda: _list_legacy_contacts(
            db,
            limit=limit,
            offset=offset,
            query=query,
            stage=stage,
        ),
        _LEGACY_CONTACTS_ADAPTER,
    )


@router.get("/celebrations", response_model=ContactCelebrationsOut)
async def celebrations(
    actor_subject: AdminSubject,
    db: DatabaseDependency,
    month: CelebrationMonth,
) -> object:
    _actor_subject = actor_subject
    return await _run_read(
        db,
        lambda: list_contact_celebrations(db, month=month),
        _CELEBRATIONS_ADAPTER,
    )


# Slice C inserts PATCH /contacts/{contact_id} immediately after this detail read.
@router.get("/contacts/{contact_id}", response_model=ContactDetailOut)
async def contact_detail(
    contact_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    _actor_subject = actor_subject
    return await _run_read(
        db,
        lambda: get_contact_detail(db, contact_id),
        _DETAIL_ADAPTER,
    )


@router.get("/contacts/{contact_id}/neighbors", response_model=ContactNeighborsOut)
async def contact_neighbors(
    contact_id: ContactId,
    filters: Annotated[ContactDirectoryQueryIn, Query()],
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    _actor_subject = actor_subject
    request_filters = _request_filters(filters)
    return await _run_read(
        db,
        lambda: get_contact_neighbors(
            db,
            contact_id,
            request_filters,
            now=_now(),
        ),
        _NEIGHBORS_ADAPTER,
    )


@router.get(
    "/contacts/{contact_id}/workspace/summary",
    response_model=ContactWorkspaceSummaryOut,
)
async def contact_workspace_summary(
    contact_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    _actor_subject = actor_subject
    return await _run_read(
        db,
        lambda: get_contact_workspace_summary(db, contact_id),
        _WORKSPACE_SUMMARY_ADAPTER,
    )


@router.get(
    "/contacts/{contact_id}/workspace",
    response_model=LegacyContactWorkspaceOut,
)
async def contact_workspace(
    contact_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    _actor_subject = actor_subject
    return await _run_read(
        db,
        lambda: _legacy_contact_workspace(db, contact_id=contact_id),
        _LEGACY_WORKSPACE_ADAPTER,
    )


@router.get("/contacts/{contact_id}/timeline", response_model=ContactTimelinePageOut)
async def contact_timeline(
    contact_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
    cursor: str | None = None,
    page_size: PageSize = 50,
) -> object:
    _actor_subject = actor_subject
    if cursor is not None:
        try:
            decode_timeline_cursor(cursor)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Timeline cursor is invalid",
            ) from None
    return await _run_read(
        db,
        lambda: list_contact_timeline(
            db,
            contact_id,
            cursor=cursor,
            page_size=page_size,
        ),
        _TIMELINE_ADAPTER,
    )


async def _section_page(
    *,
    db: AsyncSession,
    contact_id: int,
    section: ContactSection,
    page: int,
    page_size: int,
) -> object:
    return await _run_read(
        db,
        lambda: list_contact_section(
            db,
            contact_id,
            section,
            page=page,
            page_size=page_size,
        ),
        _SECTION_PAGE_ADAPTER,
    )


@router.get(
    "/contacts/{contact_id}/opportunities",
    response_model=ContactSectionPageOut,
)
async def contact_opportunities(
    contact_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
    page: Page = 1,
    page_size: PageSize = 50,
) -> object:
    _actor_subject = actor_subject
    return await _section_page(
        db=db,
        contact_id=contact_id,
        section=ContactSection.OPPORTUNITIES,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/contacts/{contact_id}/smart-plans",
    response_model=ContactSectionPageOut,
)
async def contact_smart_plans(
    contact_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
    page: Page = 1,
    page_size: PageSize = 50,
) -> object:
    _actor_subject = actor_subject
    return await _section_page(
        db=db,
        contact_id=contact_id,
        section=ContactSection.SMART_PLANS,
        page=page,
        page_size=page_size,
    )


@router.get("/contacts/{contact_id}/tasks", response_model=ContactSectionPageOut)
async def contact_tasks(
    contact_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
    state_values: Annotated[list[TaskState], Query(alias="state")],
    page: Page = 1,
    page_size: PageSize = 50,
) -> object:
    _actor_subject = actor_subject
    if len(state_values) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Exactly one task state is required",
        )
    sections = {
        "to_do": ContactSection.TASKS_TO_DO,
        "completed": ContactSection.TASKS_COMPLETED,
        "archived": ContactSection.TASKS_ARCHIVED,
    }
    section = sections.get(state_values[0])
    if section is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Task state is invalid",
        )
    return await _section_page(
        db=db,
        contact_id=contact_id,
        section=section,
        page=page,
        page_size=page_size,
    )


@router.get("/contacts/{contact_id}/notes", response_model=ContactSectionPageOut)
async def contact_notes(
    contact_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
    page: Page = 1,
    page_size: PageSize = 50,
) -> object:
    _actor_subject = actor_subject
    return await _section_page(
        db=db,
        contact_id=contact_id,
        section=ContactSection.NOTES,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/contacts/{contact_id}/saved-searches",
    response_model=ContactSectionPageOut,
)
async def contact_saved_searches(
    contact_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
    page: Page = 1,
    page_size: PageSize = 50,
) -> object:
    _actor_subject = actor_subject
    return await _section_page(
        db=db,
        contact_id=contact_id,
        section=ContactSection.SAVED_SEARCHES,
        page=page,
        page_size=page_size,
    )


@router.get("/contacts/{contact_id}/evidence", response_model=ContactEvidenceOut)
async def contact_evidence(
    contact_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    _actor_subject = actor_subject
    return await _run_read(
        db,
        lambda: get_contact_evidence(db, contact_id),
        _EVIDENCE_ADAPTER,
    )


__all__ = ["router"]
