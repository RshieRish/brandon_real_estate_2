"""Reviewed, additive restoration of source-backed captured mailing addresses."""

import hashlib
import json
from dataclasses import asdict, dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.command import CRMContact
from models.command_contacts import (
    CRMContactAddress,
    CRMContactCapturePosition,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
)
from models.command_provenance import CRMSourceRecord
from services.command_contact_capture_content import (
    CapturedMailingAddress,
    capture_coordinates_match,
    read_mailing_address,
    source_raw_lines,
)


@dataclass(frozen=True)
class AddressRepairItem:
    contact_id: int
    source_record_id: int
    source_sha256: str
    address: CapturedMailingAddress


@dataclass(frozen=True)
class AddressRepairPlan:
    items: tuple[AddressRepairItem, ...] = ()
    fingerprint: str = ""
    applied: int = 0
    needs_review: tuple[int, ...] = ()


async def recover_captured_mailing_addresses(
    db: AsyncSession,
    *,
    expected_fingerprint: str | None = None,
) -> AddressRepairPlan:
    """Dry-run by default; apply only the exact reviewed plan, inside caller's transaction.

    The operational caller must create and verify a protected backup first.
    Existing addresses (including later edits) always win. No source rows change.
    """
    if expected_fingerprint is not None:
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            isolation = await db.scalar(text("SHOW transaction_isolation"))
            if isolation != "read committed":
                raise ValueError(
                    "Address apply requires READ COMMITTED for a fresh locked plan"
                )
        # Serialize approved repair runs on contact rows; the deterministic unique
        # source key additionally prevents duplicate inserts on concurrent retries.
        await db.execute(
            select(CRMContact.id).order_by(CRMContact.id).with_for_update()
        )
    with db.no_autoflush:
        existing = set((await db.scalars(select(CRMContactAddress.contact_id))).all())
        candidates: dict[int, list[AddressRepairItem]] = {}
        after = 0
        while True:
            rows = (
                await db.execute(
                    select(
                        CRMSourceRecord,
                        CRMContactSourceOccurrence,
                        CRMContactSectionCapture,
                        CRMContactCapturePosition,
                    )
                    .join(
                        CRMContactSourceOccurrence,
                        CRMContactSourceOccurrence.source_record_id
                        == CRMSourceRecord.id,
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
                        CRMSourceRecord.id > after,
                        CRMSourceRecord.source_system == "kw_command",
                        CRMSourceRecord.module == "contacts",
                        CRMSourceRecord.record_kind == "contact_timeline_event",
                        CRMSourceRecord.parser_version == "contacts-v1",
                    )
                    .order_by(CRMSourceRecord.id)
                    .limit(1_000)
                )
            ).all()
            for source, occurrence, section, position in rows:
                if (
                    section is None
                    or position is None
                    or section.section_name != "timeline"
                    or occurrence.contact_id != position.contact_id
                    or not capture_coordinates_match(
                        source.payload_json,
                        source_contact_id=position.source_contact_id,
                        capture_ordinal=position.capture_ordinal,
                        occurrence_ordinal=occurrence.occurrence_ordinal,
                    )
                ):
                    raise ValueError("Captured address source ownership is invalid")
                raw = source_raw_lines(source.payload_json)
                address = read_mailing_address(raw) if raw else None
                if address is None or occurrence.contact_id in existing:
                    continue
                item = AddressRepairItem(
                    occurrence.contact_id,
                    source.id,
                    hashlib.sha256(source.payload_json.encode()).hexdigest(),
                    address,
                )
                candidates.setdefault(occurrence.contact_id, []).append(item)
            if len(rows) < 1_000:
                break
            after = rows[-1][0].id
    items: list[AddressRepairItem] = []
    review: list[int] = []
    for contact_id, sources in sorted(candidates.items()):
        # Multiple conflicting captures require review, not arbitrary first/last wins.
        if len({item.address for item in sources}) != 1:
            review.append(contact_id)
            continue
        item = sources[0]
        address = item.address
        if (
            len(address.formatted) > 500
            or len(address.line1 or "") > 255
            or len(address.line2 or "") > 255
            or len(address.city or "") > 120
        ):
            review.append(contact_id)
            continue
        items.append(item)
        if address.line1 is None:
            review.append(contact_id)
    serialized = json.dumps(
        {
            "version": 1,
            "items": [asdict(item) for item in items],
            "needs_review": review,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
    if expected_fingerprint is not None:
        if fingerprint != expected_fingerprint:
            raise ValueError("Address recovery plan changed; review a fresh dry run")
        for item in items:
            db.add(
                CRMContactAddress(
                    contact_id=item.contact_id,
                    source_record_id=item.source_record_id,
                    source_key=f"captured-mailing-v1:{item.source_record_id}",
                    address_type="mailing",
                    is_primary=True,
                    country="US" if item.address.state is not None else None,
                    **asdict(item.address),
                )
            )
        await db.flush()
    return AddressRepairPlan(
        tuple(items),
        fingerprint,
        len(items) if expected_fingerprint is not None else 0,
        tuple(review),
    )
