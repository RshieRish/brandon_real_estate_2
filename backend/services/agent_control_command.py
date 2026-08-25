"""Read-only adapter from Sydney agent contracts to Command Contacts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid5

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
from services.command_contacts import ContactDirectoryError, list_contacts

_AUDIENCE_DOMAIN = b"sydney-command-audience-v1\x00"
_AUDIENCE_NAMESPACE = UUID("571651d5-3832-4f60-82fb-20d0a5ce7f1b")
_AUDIENCE_PAGE_SIZE = 100


class CommandContactsUnavailable(RuntimeError):
    """The authoritative Command directory could not be read safely."""


class CommandContactAudienceChanged(RuntimeError):
    """The directory changed while an exact audience was materialized."""


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


async def search_command_contacts(
    db: AsyncSession,
    request: CommandContactsSearchRequest,
    *,
    now: datetime | None = None,
) -> CommandContactsSearchResponse:
    current = now or datetime.now(UTC)
    try:
        page = await list_contacts(
            db,
            _filters(request, page=request.page, page_size=request.page_size),
            now=current,
        )
    except (ContactDirectoryError, SQLAlchemyError):
        raise CommandContactsUnavailable("command_contacts_unavailable") from None
    return CommandContactsSearchResponse(
        contacts=[_result(row) for row in page.rows],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        page_count=page.page_count,
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
    "CommandContactsUnavailable",
    "preview_command_contact_audience",
    "search_command_contacts",
]
