"""Read-only adapter from Sydney agent contracts to Command Contacts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid5

from models.command_contacts import CRMContactAddress
from models.command_provenance import CRMReconciliationResult, CRMReconciliationRun
from schemas.agent_control_command import (
    CommandContactAudiencePreviewRequest,
    CommandContactAudiencePreviewResponse,
    CommandContactAudienceSample,
    CommandContactCelebrationOccurrence,
    CommandContactCelebrationSample,
    CommandContactCelebrationsPreviewRequest,
    CommandContactCelebrationsPreviewResponse,
    CommandContactFilters,
    CommandContactResult,
    CommandContactsSearchRequest,
    CommandContactsSearchResponse,
)
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.command_contact_contracts import (
    ContactCelebrationRow,
    ContactDirectoryFilters,
    ContactDirectoryRow,
)
from services.command_contacts import (
    ContactDirectoryError,
    list_contact_celebrations,
    list_contacts,
    list_contacts_cursor,
)

_AUDIENCE_DOMAIN = b"sydney-command-audience-v1\x00"
_AUDIENCE_NAMESPACE = UUID("571651d5-3832-4f60-82fb-20d0a5ce7f1b")
_AUDIENCE_PAGE_SIZE = 100
_SEARCH_CURSOR_VERSION = 1
_CELEBRATION_DOMAIN = b"sydney-command-celebrations-v1\x00"
_CELEBRATION_NAMESPACE = UUID("8be84ee1-57fa-4e65-a33d-c9c3f3b96016")


class CommandContactsUnavailable(RuntimeError):
    """The authoritative Command directory could not be read safely."""


class CommandContactAudienceChanged(RuntimeError):
    """The directory changed while an exact audience was materialized."""


class CommandContactsCursorInvalid(ValueError):
    """The opaque Command search cursor is malformed or filter-mismatched."""


def _filters(
    request: CommandContactFilters,
    *,
    page: int,
    page_size: int,
) -> ContactDirectoryFilters:
    return ContactDirectoryFilters(
        query=request.query,
        stage=request.stage,
        tag_ids=tuple(request.tag_ids),
        sources=tuple(request.sources),
        origins=tuple(request.origins),
        page=page,
        page_size=page_size,
    )


def _result(row: ContactDirectoryRow) -> CommandContactResult:
    return CommandContactResult(
        contact_id=row.id,
        display_name=row.display_name,
        primary_email=row.primary_email,
        primary_phone=row.primary_phone,
        stage=row.stage,
        sources=list(row.sources),
        origins=list(row.origins),
        tag_names=[tag.name for tag in row.tags],
    )


def _mask_name(value: str) -> str:
    return " ".join(f"{part[0]}***" for part in value.split() if part)


def _mask_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return None
    return f"***@{value.rsplit('@', 1)[1]}"


def _mask_phone(value: str | None) -> str | None:
    digits = "".join(character for character in (value or "") if character.isdigit())
    return f"***-***-{digits[-4:]}" if len(digits) >= 4 else None


def _sample(row: ContactDirectoryRow) -> CommandContactAudienceSample:
    return CommandContactAudienceSample(
        display_name=_mask_name(row.display_name),
        primary_email=_mask_email(row.primary_email),
        primary_phone=_mask_phone(row.primary_phone),
    )


def _audience_checksum(contact_ids: list[int]) -> str:
    digest = hashlib.sha256()
    digest.update(_AUDIENCE_DOMAIN)
    for contact_id in contact_ids:
        digest.update(str(contact_id).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _present(value: str | None) -> bool:
    return bool(value and value.strip())


def _mailing_address_ready(row: CRMContactAddress) -> bool:
    """Require explicit structured mailing fields; never infer from a label."""
    return all(
        _present(value) for value in (row.line1, row.city, row.state, row.postal_code)
    )


async def _address_ready_contact_ids(
    db: AsyncSession,
    contact_ids: set[int],
) -> set[int]:
    if not contact_ids:
        return set()
    with db.no_autoflush:
        rows = (
            await db.scalars(
                select(CRMContactAddress)
                .where(CRMContactAddress.contact_id.in_(contact_ids))
                .order_by(
                    CRMContactAddress.contact_id,
                    CRMContactAddress.is_primary.desc(),
                    CRMContactAddress.id,
                )
            )
        ).all()
    return {row.contact_id for row in rows if _mailing_address_ready(row)}


async def _contact_reconciliation_status(
    db: AsyncSession,
) -> str:
    """Summarize the latest authoritative contacts apply evidence."""
    row = (
        await db.execute(
            select(
                CRMReconciliationRun.status,
                CRMReconciliationResult.error_count,
            )
            .join(
                CRMReconciliationResult,
                CRMReconciliationResult.run_id == CRMReconciliationRun.id,
            )
            .where(
                CRMReconciliationRun.mode == "apply",
                CRMReconciliationResult.module == "contacts",
            )
            .order_by(
                CRMReconciliationRun.started_at.desc(),
                CRMReconciliationRun.id.desc(),
            )
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return "not_reconciled"
    if row.status == "completed" and row.error_count == 0:
        return "reconciled"
    return "incomplete"


def _selected_celebrations(
    rows: tuple[ContactCelebrationRow, ...],
    *,
    kind: str,
) -> tuple[tuple[int, str, str, int, int | None, str, str], ...]:
    public_kind = "home_anniversary" if kind == "anniversary" else "birthday"
    return tuple(
        (
            row.contact_id,
            row.display_name,
            public_kind,
            row.day,
            row.year,
            row.year_quality,
            row.origin,
        )
        for row in rows
    )


def _celebration_checksum(
    *,
    month: int,
    include_birthdays: bool,
    include_home_anniversaries: bool,
    selected: tuple[tuple[int, str, str, int, int | None, str, str], ...],
    address_ready_ids: set[int],
) -> str:
    material = {
        "address_ready_contact_ids": sorted(address_ready_ids),
        "include_birthdays": include_birthdays,
        "include_home_anniversaries": include_home_anniversaries,
        "month": month,
        "occurrences": [
            {
                "contact_id": contact_id,
                "day": day,
                "kind": kind,
                "origin": origin,
                "year": year,
                "year_quality": year_quality,
            }
            for (
                contact_id,
                _display_name,
                kind,
                day,
                year,
                year_quality,
                origin,
            ) in sorted(selected, key=lambda item: (item[0], item[2], item[3]))
        ],
    }
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(_CELEBRATION_DOMAIN + canonical.encode("utf-8")).hexdigest()


def _search_filter_hash(request: CommandContactFilters) -> str:
    payload = {
        "query": request.query,
        "stage": request.stage,
        "tag_ids": list(request.tag_ids),
        "sources": [value.value for value in request.sources],
        "origins": [value.value for value in request.origins],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(
        b"sydney-command-search-filter-v1\x00" + canonical.encode("utf-8")
    ).hexdigest()


def _encode_search_cursor(
    *,
    after_id: int,
    upper_bound_id: int,
    filter_hash: str,
) -> str:
    payload = json.dumps(
        {
            "a": after_id,
            "f": filter_hash,
            "u": upper_bound_id,
            "v": _SEARCH_CURSOR_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_search_cursor(
    encoded: str,
    *,
    filter_hash: str,
) -> tuple[int, int]:
    error = CommandContactsCursorInvalid("command_contacts_cursor_invalid")
    if not isinstance(encoded, str) or not encoded or len(encoded) > 512:
        raise error
    try:
        padding = "=" * (-len(encoded) % 4)
        decoded = base64.b64decode(
            encoded + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise error from None
    if not isinstance(payload, dict) or set(payload) != {"a", "f", "u", "v"}:
        raise error
    after_id = payload.get("a")
    upper_bound_id = payload.get("u")
    if (
        payload.get("v") != _SEARCH_CURSOR_VERSION
        or type(after_id) is not int
        or after_id <= 0
        or type(upper_bound_id) is not int
        or upper_bound_id < after_id
        or payload.get("f") != filter_hash
    ):
        raise error
    if (
        _encode_search_cursor(
            after_id=after_id,
            upper_bound_id=upper_bound_id,
            filter_hash=filter_hash,
        )
        != encoded
    ):
        raise error
    return after_id, upper_bound_id


async def search_command_contacts(
    db: AsyncSession,
    request: CommandContactsSearchRequest,
    *,
    now: datetime | None = None,
) -> CommandContactsSearchResponse:
    current = now or datetime.now(UTC)
    filter_hash = _search_filter_hash(request)
    after_id: int | None = None
    upper_bound_id: int | None = None
    if request.cursor is not None:
        after_id, upper_bound_id = _decode_search_cursor(
            request.cursor,
            filter_hash=filter_hash,
        )
    try:
        page = await list_contacts_cursor(
            db,
            _filters(request, page=1, page_size=request.page_size),
            after_id=after_id,
            upper_bound_id=upper_bound_id,
            now=current,
        )
    except (ContactDirectoryError, SQLAlchemyError):
        raise CommandContactsUnavailable("command_contacts_unavailable") from None
    return CommandContactsSearchResponse(
        contacts=[_result(row) for row in page.rows],
        total=page.total,
        page_size=request.page_size,
        next_cursor=(
            _encode_search_cursor(
                after_id=page.next_after_id,
                upper_bound_id=page.upper_bound_id,
                filter_hash=filter_hash,
            )
            if page.next_after_id is not None
            else None
        ),
        has_more=page.has_more,
    )


async def preview_command_contact_audience(
    db: AsyncSession,
    request: CommandContactAudiencePreviewRequest,
    *,
    now: datetime | None = None,
) -> CommandContactAudiencePreviewResponse:
    current = now or datetime.now(UTC)
    contact_ids: list[int] = []
    samples: list[CommandContactAudienceSample] = []
    expected_total: int | None = None
    page_number = 1
    try:
        # Every page must be read from one PostgreSQL snapshot; otherwise rows
        # inserted or removed between OFFSET pages can silently change the
        # supposedly exact audience while preserving the reported total.
        # Keep every page and the content-free audit write in one stable
        # snapshot. The request-scoped dependency commits the audit after this
        # function returns, so the transaction cannot be READ ONLY.
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        while True:
            page = await list_contacts(
                db,
                _filters(
                    request,
                    page=page_number,
                    page_size=_AUDIENCE_PAGE_SIZE,
                ),
                now=current,
            )
            if expected_total is None:
                expected_total = page.total
            if page.total != expected_total or page.page != page_number:
                raise CommandContactAudienceChanged(
                    "command_contacts_changed_during_preview"
                )
            for row in page.rows:
                contact_ids.append(row.id)
                if len(samples) < 5:
                    samples.append(_sample(row))
            if page_number >= page.page_count:
                break
            page_number += 1
    except CommandContactAudienceChanged:
        raise
    except (ContactDirectoryError, SQLAlchemyError):
        raise CommandContactsUnavailable("command_contacts_unavailable") from None

    if expected_total is None:
        expected_total = 0
    if len(contact_ids) != expected_total or len(set(contact_ids)) != len(contact_ids):
        raise CommandContactAudienceChanged("command_contacts_changed_during_preview")
    checksum = _audience_checksum(contact_ids)
    return CommandContactAudiencePreviewResponse(
        audience_ref=uuid5(_AUDIENCE_NAMESPACE, checksum),
        audience_checksum=checksum,
        exact_count=expected_total,
        samples=samples,
    )


async def preview_command_contact_celebrations(
    db: AsyncSession,
    request: CommandContactCelebrationsPreviewRequest,
) -> CommandContactCelebrationsPreviewResponse:
    try:
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        celebrations = await list_contact_celebrations(db, month=request.month)
        selected: tuple[tuple[int, str, str, int, int | None, str, str], ...] = ()
        birthdays = celebrations.birthdays if request.include_birthdays else ()
        anniversaries = (
            celebrations.anniversaries if request.include_home_anniversaries else ()
        )
        if birthdays:
            selected += _selected_celebrations(birthdays, kind="birthday")
        if anniversaries:
            selected += _selected_celebrations(
                anniversaries,
                kind="anniversary",
            )

        audience: dict[
            int,
            dict[str, object],
        ] = {}
        for contact_id, display_name, kind, day, *_private in selected:
            current = audience.setdefault(
                contact_id,
                {"display_name": display_name, "celebrations": []},
            )
            if current["display_name"] != display_name:
                raise CommandContactAudienceChanged(
                    "command_contacts_changed_during_preview"
                )
            current["celebrations"].append((kind, day))  # type: ignore[union-attr]

        audience_ids = set(audience)
        address_ready_ids = await _address_ready_contact_ids(db, audience_ids)
        reconciliation_status = await _contact_reconciliation_status(db)
    except CommandContactAudienceChanged:
        raise
    except (ContactDirectoryError, SQLAlchemyError):
        raise CommandContactsUnavailable("command_contacts_unavailable") from None

    checksum = _celebration_checksum(
        month=request.month,
        include_birthdays=request.include_birthdays,
        include_home_anniversaries=request.include_home_anniversaries,
        selected=selected,
        address_ready_ids=address_ready_ids,
    )

    def sample_order(item: tuple[int, dict[str, object]]) -> tuple[int, str, int]:
        contact_id, value = item
        occurrences = value["celebrations"]
        assert isinstance(occurrences, list)
        first_day = min(day for _kind, day in occurrences)
        return first_day, str(value["display_name"]).casefold(), contact_id

    samples: list[CommandContactCelebrationSample] = []
    for contact_id, value in sorted(audience.items(), key=sample_order)[:5]:
        occurrences = value["celebrations"]
        assert isinstance(occurrences, list)
        samples.append(
            CommandContactCelebrationSample(
                display_name=str(value["display_name"]),
                celebrations=[
                    CommandContactCelebrationOccurrence(kind=kind, day=day)
                    for kind, day in sorted(
                        occurrences,
                        key=lambda item: (
                            0 if item[0] == "birthday" else 1,
                            item[1],
                        ),
                    )
                ],
                address_ready=contact_id in address_ready_ids,
            )
        )
    ready_count = len(audience_ids.intersection(address_ready_ids))
    return CommandContactCelebrationsPreviewResponse(
        month=request.month,
        include_birthdays=request.include_birthdays,
        include_home_anniversaries=request.include_home_anniversaries,
        audience_ref=uuid5(_CELEBRATION_NAMESPACE, checksum),
        audience_checksum=checksum,
        birthday_count=len(birthdays),
        home_anniversary_count=len(anniversaries),
        union_count=len(audience_ids),
        address_ready_count=ready_count,
        missing_address_count=len(audience_ids) - ready_count,
        reconciliation_status=reconciliation_status,  # type: ignore[arg-type]
        samples=samples,
    )


__all__ = [
    "CommandContactAudienceChanged",
    "CommandContactsCursorInvalid",
    "CommandContactsUnavailable",
    "preview_command_contact_audience",
    "preview_command_contact_celebrations",
    "search_command_contacts",
]
