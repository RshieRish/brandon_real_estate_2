"""Additive address recovery never overwrites CRM data or source evidence."""

import json

import pytest
from sqlalchemy import select

from models.command import CRMContact
from models.command_contacts import CRMContactAddress
from services.command_contact_address_repair import recover_captured_mailing_addresses
from tests.test_command_contact_capture_content import profile
from tests.test_command_contact_notes import note_db as _note_db
from tests.test_command_contact_timeline import _source, _timeline_ownership

note_db = _note_db


async def seed(db):
    db.add(CRMContact(id=1, first_name="Example", last_name="Person", stage="lead"))
    source = _source(1)
    source.payload_json = json.dumps(
        {
            "source_contact_id": "000000000000000000000001",
            "capture_ordinal": "0000001",
            "section_name": "timeline",
            "occurrence_ordinal": 1,
            "values": {
                "raw_lines": profile(["12 Example Ln.", "Unit 7", "Dracut, MA, 01826"])
            },
        }
    )
    db.add(source)
    await db.flush()
    for row in _timeline_ownership(1, contact_id=1):
        db.add(row)
        await db.flush()
    return source


@pytest.mark.asyncio
async def test_dry_run_then_additive_idempotent_apply(note_db):
    source = await seed(note_db)
    original = source.payload_json
    plan = await recover_captured_mailing_addresses(note_db)
    assert len(plan.items) == 1
    assert not (await note_db.scalars(select(CRMContactAddress))).all()
    result = await recover_captured_mailing_addresses(
        note_db, expected_fingerprint=plan.fingerprint
    )
    assert result.applied == 1
    address = (await note_db.scalars(select(CRMContactAddress))).one()
    assert (address.line2, address.postal_code, address.source_record_id) == (
        "Unit 7",
        "01826",
        source.id,
    )
    assert source.payload_json == original
    rerun = await recover_captured_mailing_addresses(note_db)
    assert not rerun.items


@pytest.mark.asyncio
async def test_existing_address_and_drift_are_protected(note_db):
    await seed(note_db)
    plan = await recover_captured_mailing_addresses(note_db)
    note_db.add(
        CRMContactAddress(
            contact_id=1,
            source_key="manual",
            formatted="Later edited address",
            line1="Other road",
            is_primary=True,
        )
    )
    await note_db.flush()
    with pytest.raises(ValueError, match="changed"):
        await recover_captured_mailing_addresses(
            note_db, expected_fingerprint=plan.fingerprint
        )
    assert not (await recover_captured_mailing_addresses(note_db)).items


@pytest.mark.asyncio
async def test_foreign_position_cannot_supply_address(note_db):
    await seed(note_db)
    from models.command_contacts import CRMContactCapturePosition

    note_db.add(CRMContact(id=2, first_name="Other", last_name="Person", stage="lead"))
    await note_db.flush()
    position = await note_db.get(CRMContactCapturePosition, 200001)
    position.contact_id = 2
    await note_db.flush()
    with pytest.raises(ValueError, match="ownership"):
        await recover_captured_mailing_addresses(note_db)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("source_contact_id", "000000000000000000000002"),
        ("capture_ordinal", "0000002"),
        ("section_name", "notes"),
        ("occurrence_ordinal", 2),
        ("source_contact_id", None),
    ],
)
async def test_payload_coordinates_must_match_owned_capture(note_db, field, value):
    source = await seed(note_db)
    payload = json.loads(source.payload_json)
    payload[field] = value
    source.payload_json = json.dumps(payload)
    await note_db.flush()
    with pytest.raises(ValueError, match="ownership"):
        await recover_captured_mailing_addresses(note_db)
    assert not (await note_db.scalars(select(CRMContactAddress))).all()
