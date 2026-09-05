"""Real PostgreSQL snapshots must not hide a newly committed manual address."""

from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.command_contacts import CRMContactAddress, CRMContactAuditEvent
from models.command_provenance import CRMSourceRecord
from scripts import repair_captured_contact_addresses as repair_cli
from services.command_contact_address_repair import (
    AddressRepairPlan,
    recover_captured_mailing_addresses,
)
from tests.test_command_contact_address_repair import seed
from tests.test_crm_task_service import owned_task_database


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("isolation", "error"),
    [
        ("SERIALIZABLE", "requires READ COMMITTED"),
        ("READ COMMITTED", "plan changed"),
    ],
    ids=["reject-stale-snapshot", "detect-committed-manual-address"],
)
async def test_apply_preserves_manual_address_committed_after_first_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolation: str,
    error: str,
) -> None:
    async with owned_task_database() as (_engine, sessions):
        async with sessions() as db, db.begin():
            source = await seed(db)
            original_source = source.payload_json
            reviewed = await recover_captured_mailing_addresses(db)
        assert len(reviewed.items) == 1

        calls: list[str | None] = []

        async def commit_manual_address_after_plan(
            db: AsyncSession,
            *,
            expected_fingerprint: str | None = None,
        ) -> AddressRepairPlan:
            calls.append(expected_fingerprint)
            plan = await recover_captured_mailing_addresses(
                db, expected_fingerprint=expected_fingerprint
            )
            if len(calls) == 1:
                # A separate connection commits after the first plan's read,
                # before the repair acquires contact locks and checks it again.
                async with sessions() as writer, writer.begin():
                    writer.add(
                        CRMContactAddress(
                            contact_id=1,
                            source_key="manual-user-edit",
                            formatted="34 New Example Street\nBoston, MA, 02110",
                            line1="34 New Example Street",
                            city="Boston",
                            state="MA",
                            postal_code="02110",
                            is_primary=True,
                        )
                    )
            return plan

        monkeypatch.setattr(
            repair_cli,
            "recover_captured_mailing_addresses",
            commit_manual_address_after_plan,
        )
        backup_path = tmp_path / "address-backup.json"
        with pytest.raises(ValueError, match=error):
            async with sessions() as db, db.begin():
                await db.execute(text(f"SET TRANSACTION ISOLATION LEVEL {isolation}"))
                await repair_cli.run_repair(
                    db,
                    apply=True,
                    expected_plan=reviewed.fingerprint,
                    backup_path=backup_path,
                )

        assert calls == [None, reviewed.fingerprint]
        assert backup_path.is_file()
        async with sessions() as db:
            addresses = (await db.scalars(select(CRMContactAddress))).all()
            assert [
                (
                    row.contact_id,
                    row.source_key,
                    row.source_record_id,
                    row.formatted,
                    row.line1,
                    row.city,
                    row.state,
                    row.postal_code,
                    row.is_primary,
                )
                for row in addresses
            ] == [
                (
                    1,
                    "manual-user-edit",
                    None,
                    "34 New Example Street\nBoston, MA, 02110",
                    "34 New Example Street",
                    "Boston",
                    "MA",
                    "02110",
                    True,
                )
            ]
            assert not (await db.scalars(select(CRMContactAuditEvent))).all()
            stored_source = await db.get(CRMSourceRecord, 1)
            assert stored_source is not None
            assert stored_source.payload_json == original_source
