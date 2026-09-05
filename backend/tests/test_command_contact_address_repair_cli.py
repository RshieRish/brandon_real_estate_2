"""Operational repair requires a private, verified backup before any insert."""

import json
import stat

import pytest
from sqlalchemy import select

from models.command_contacts import CRMContactAddress
from scripts.repair_captured_contact_addresses import run_repair
from tests.test_command_contact_address_repair import note_db as _note_db
from tests.test_command_contact_address_repair import seed

note_db = _note_db


@pytest.mark.asyncio
async def test_apply_requires_review_and_creates_verified_private_backup(
    note_db, tmp_path
):
    await seed(note_db)
    dry = await run_repair(note_db)
    assert dry["planned_addresses"] == 1 and dry["mode"] == "dry_run"
    with pytest.raises(ValueError):
        await run_repair(note_db, apply=True)
    target = tmp_path / "address-backup.json"
    applied = await run_repair(
        note_db, apply=True, expected_plan=dry["fingerprint"], backup_path=target
    )
    assert applied["applied_addresses"] == 1
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    content = json.loads(target.read_text())
    assert content["existing_addresses"] == []
    assert len(content["source_records"]) == 1
    assert len(content["planned_addresses"]) == 1


@pytest.mark.asyncio
async def test_backup_collision_or_failure_does_not_insert(note_db, tmp_path):
    await seed(note_db)
    dry = await run_repair(note_db)
    target = tmp_path / "occupied.json"
    target.write_text("existing")
    with pytest.raises(FileExistsError):
        await run_repair(
            note_db, apply=True, expected_plan=dry["fingerprint"], backup_path=target
        )
    assert not (await note_db.scalars(select(CRMContactAddress))).all()
