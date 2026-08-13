"""Typed HTTP boundary for the focused Command Contacts workspace."""

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
    ContactBulkRequest,
    ContactBulkResultOut,
    ContactCelebrationsOut,
    ContactCreateIn,
    ContactDeletedOut,
    ContactDetailOut,
    ContactDirectoryPageOut,
    ContactDirectoryQueryIn,
    ContactEvidenceOut,
    ContactImportIn,
    ContactImportResultOut,
    ContactLegacySyncResultOut,
    ContactNeighborsOut,
    ContactNoteCreatedOut,
    ContactNoteCreateIn,
    ContactSavedSearchCreatedOut,
    ContactSavedSearchCreateIn,
    ContactSectionPageOut,
    ContactTagAssignmentOut,
    ContactTagRemovalOut,
    ContactTimelinePageOut,
    ContactUpdateIn,
    ContactWorkspaceSummaryOut,
    LegacyContactOut,
    LegacyContactWorkspaceOut,
    canonical_saved_search_criteria,
)
from services import command_contacts as contact_service
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
_SYNC_RESULT_ADAPTER = TypeAdapter(ContactLegacySyncResultOut)
_IMPORT_RESULT_ADAPTER = TypeAdapter(ContactImportResultOut)
_BULK_RESULT_ADAPTER = TypeAdapter(ContactBulkResultOut)
_LEGACY_CONTACT_ADAPTER = TypeAdapter(LegacyContactOut)
_NOTE_CREATED_ADAPTER = TypeAdapter(ContactNoteCreatedOut)
_DELETED_ADAPTER = TypeAdapter(ContactDeletedOut)
_SEARCH_CREATED_ADAPTER = TypeAdapter(ContactSavedSearchCreatedOut)
_TAG_ASSIGNMENT_ADAPTER = TypeAdapter(ContactTagAssignmentOut)
_TAG_REMOVAL_ADAPTER = TypeAdapter(ContactTagRemovalOut)


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


def _request_command(factory: Callable[[], _Result]) -> _Result:
    try:
        return factory()
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Contact request is invalid",
        ) from None
    # Command construction is still part of the HTTP boundary. Unexpected
    # adapter failures must never escape with request or exception values.
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update contact data",
        ) from None


async def _run_mutation(
    operation: Callable[[], Awaitable[_Result]],
    adapter: TypeAdapter,
) -> object:
    try:
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
    # The outer HTTP boundary intentionally redacts service programming errors
    # and response-validation failures without exposing exception values.
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update contact data",
        ) from None


def _require_mutation_identity(
    *,
    actual_contact_id: int,
    expected_contact_id: int,
    actual_record_id: int | None = None,
    expected_record_id: int | None = None,
) -> None:
    if actual_contact_id != expected_contact_id or (
        expected_record_id is not None and actual_record_id != expected_record_id
    ):
        raise ContactDataIntegrityError("contact mutation identity is invalid")


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


async def _load_legacy_contact(
    db: AsyncSession,
    contact_id: int,
) -> CRMContact | None:
    return (
        await db.scalars(
            select(CRMContact)
            .where(CRMContact.id == contact_id)
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()


async def _legacy_contact_after_detail(
    db: AsyncSession,
    *,
    detail: object,
    expected_contact_id: int | None,
) -> CRMContact:
    try:
        returned_contact_id = detail.contact.id  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        raise ContactDataIntegrityError(
            "contact mutation identity is invalid"
        ) from None
    if (
        type(returned_contact_id) is not int
        or returned_contact_id <= 0
        or (
            expected_contact_id is not None
            and returned_contact_id != expected_contact_id
        )
    ):
        raise ContactDataIntegrityError("contact mutation identity is invalid")
    contact = await _load_legacy_contact(db, returned_contact_id)
    if contact is None or contact.id != returned_contact_id:
        raise ContactDataIntegrityError("contact mutation identity is invalid")
    return contact


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


# Static routes are declared before every dynamic contact path.
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


@router.post(
    "/contacts/sync-leads",
    response_model=ContactLegacySyncResultOut,
)
async def sync_legacy_leads(
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    return await _run_mutation(
        lambda: contact_service.sync_legacy_leads(
            db,
            actor_subject=actor_subject,
        ),
        _SYNC_RESULT_ADAPTER,
    )


@router.post("/contacts/import", response_model=ContactImportResultOut)
async def import_contacts(
    payload: ContactImportIn,
    db: DatabaseDependency,
    *,
    actor_subject: AdminSubject,
) -> object:
    command = _request_command(payload.to_command)
    return await _run_mutation(
        lambda: contact_service.import_contacts(
            db,
            command,
            actor_subject=actor_subject,
        ),
        _IMPORT_RESULT_ADAPTER,
    )


@router.post("/contacts/bulk", response_model=ContactBulkResultOut)
async def bulk_contacts(
    payload: ContactBulkRequest,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    command = _request_command(payload.to_command)

    async def operation() -> object:
        result = await contact_service.apply_contact_bulk_action(
            db,
            command,
            actor_subject=actor_subject,
        )
        if (
            result.requested_contact_ids != tuple(sorted(command.contact_ids))
            or result.action != command.action.action
        ):
            raise ContactDataIntegrityError("contact mutation identity is invalid")
        return result

    return await _run_mutation(operation, _BULK_RESULT_ADAPTER)


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


@router.post("/contacts", response_model=LegacyContactOut)
async def create_contact(
    payload: ContactCreateIn,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    command = _request_command(payload.to_command)

    async def operation() -> CRMContact:
        detail = await contact_service.create_contact(
            db,
            command,
            actor_subject=actor_subject,
        )
        return await _legacy_contact_after_detail(
            db,
            detail=detail,
            expected_contact_id=None,
        )

    return await _run_mutation(operation, _LEGACY_CONTACT_ADAPTER)


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


@router.patch("/contacts/{contact_id}", response_model=LegacyContactOut)
async def update_contact(
    contact_id: ContactId,
    payload: ContactUpdateIn,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    command = _request_command(payload.to_command)

    async def operation() -> CRMContact:
        detail = await contact_service.update_contact(
            db,
            contact_id,
            command,
            actor_subject=actor_subject,
        )
        return await _legacy_contact_after_detail(
            db,
            detail=detail,
            expected_contact_id=contact_id,
        )

    return await _run_mutation(operation, _LEGACY_CONTACT_ADAPTER)


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


@router.post(
    "/contacts/{contact_id}/notes",
    response_model=ContactNoteCreatedOut,
)
async def create_contact_note(
    contact_id: ContactId,
    payload: ContactNoteCreateIn,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    command = _request_command(payload.to_command)

    async def operation() -> dict[str, object]:
        result = await contact_service.create_contact_note(
            db,
            contact_id,
            command,
            actor_subject=actor_subject,
        )
        _require_mutation_identity(
            actual_contact_id=result.contact_id,
            expected_contact_id=contact_id,
        )
        if result.changed is not True:
            raise ContactDataIntegrityError("contact mutation identity is invalid")
        return {"id": result.record_id, "body": command.body}

    return await _run_mutation(operation, _NOTE_CREATED_ADAPTER)


@router.delete(
    "/contacts/{contact_id}/notes/{note_id}",
    response_model=ContactDeletedOut,
)
async def delete_contact_note(
    contact_id: ContactId,
    note_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    async def operation() -> dict[str, object]:
        result = await contact_service.delete_contact_note(
            db,
            contact_id,
            note_id,
            actor_subject=actor_subject,
        )
        _require_mutation_identity(
            actual_contact_id=result.contact_id,
            expected_contact_id=contact_id,
            actual_record_id=result.record_id,
            expected_record_id=note_id,
        )
        if result.changed is not True:
            raise ContactDataIntegrityError("contact mutation identity is invalid")
        return {"deleted": True, "id": note_id}

    return await _run_mutation(operation, _DELETED_ADAPTER)


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


@router.post(
    "/contacts/{contact_id}/saved-searches",
    response_model=ContactSavedSearchCreatedOut,
)
async def create_saved_search(
    contact_id: ContactId,
    payload: ContactSavedSearchCreateIn,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    command = _request_command(payload.to_command)

    async def operation() -> dict[str, object]:
        result = await contact_service.create_contact_saved_search(
            db,
            contact_id,
            command,
            actor_subject=actor_subject,
        )
        _require_mutation_identity(
            actual_contact_id=result.contact_id,
            expected_contact_id=contact_id,
        )
        if result.changed is not True:
            raise ContactDataIntegrityError("contact mutation identity is invalid")
        return {
            "id": result.record_id,
            "name": command.name,
            "criteria": canonical_saved_search_criteria(command.criteria),
        }

    return await _run_mutation(operation, _SEARCH_CREATED_ADAPTER)


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


@router.post(
    "/contacts/{contact_id}/tags/{tag_id}",
    response_model=ContactTagAssignmentOut,
)
async def assign_tag(
    contact_id: ContactId,
    tag_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    async def operation() -> dict[str, int]:
        result = await contact_service.assign_contact_tag(
            db,
            contact_id,
            tag_id,
            actor_subject=actor_subject,
        )
        _require_mutation_identity(
            actual_contact_id=result.contact_id,
            expected_contact_id=contact_id,
        )
        return {"contact_id": contact_id, "tag_id": tag_id}

    return await _run_mutation(operation, _TAG_ASSIGNMENT_ADAPTER)


@router.delete(
    "/contacts/{contact_id}/tags/{tag_id}",
    response_model=ContactTagRemovalOut,
)
async def remove_tag(
    contact_id: ContactId,
    tag_id: ContactId,
    actor_subject: AdminSubject,
    db: DatabaseDependency,
) -> object:
    async def operation() -> dict[str, object]:
        result = await contact_service.remove_contact_tag(
            db,
            contact_id,
            tag_id,
            actor_subject=actor_subject,
        )
        _require_mutation_identity(
            actual_contact_id=result.contact_id,
            expected_contact_id=contact_id,
        )
        return {
            "removed": result.changed,
            "contact_id": contact_id,
            "tag_id": tag_id,
        }

    return await _run_mutation(operation, _TAG_REMOVAL_ADAPTER)


__all__ = ["import_contacts", "router"]
