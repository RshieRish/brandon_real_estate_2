"""Read-only adapter from Sydney agent contracts to Command Contacts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.agent_control_command import (
    CommandContactAudiencePreviewRequest,
    CommandContactAudiencePreviewResponse,
    CommandContactAudienceSample,
    CommandContactFilters,
    CommandContactResult,
    CommandContactsSearchRequest,
    CommandContactsSearchResponse,
)
from services.command_contact_contracts import (
    ContactDirectoryFilters,
    ContactDirectoryRow,
)
from services.command_contacts import (
    ContactDirectoryError,
    list_contacts,
    list_contacts_cursor,
)

_AUDIENCE_DOMAIN = b"sydney-command-audience-v1\x00"
_AUDIENCE_NAMESPACE = UUID("571651d5-3832-4f60-82fb-20d0a5ce7f1b")
_AUDIENCE_PAGE_SIZE = 100
_SEARCH_CURSOR_VERSION = 1


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


__all__ = [
    "CommandContactAudienceChanged",
    "CommandContactsCursorInvalid",
    "CommandContactsUnavailable",
    "preview_command_contact_audience",
    "search_command_contacts",
]
