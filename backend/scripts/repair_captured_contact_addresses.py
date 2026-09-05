"""Dry-run by default; additive address recovery with a protected source backup.

Run from backend: python -m scripts.repair_captured_contact_addresses
After review: add --apply --expected-plan SHA --backup-path /private/path/new.json
No messages, campaign updates, provider calls, deletes, or source rewrites occur.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import stat
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.command_contacts import CRMContactAddress, CRMContactAuditEvent
from models.command_provenance import CRMSourceRecord
from services.command_contact_address_repair import recover_captured_mailing_addresses


def _write_verified_backup(path: Path, payload: dict) -> str:
    destination = path.expanduser().absolute()
    repository = Path(__file__).resolve().parents[2]
    if destination.resolve().is_relative_to(repository):
        raise ValueError("Backup must be outside the repository")
    if not destination.parent.is_dir():
        raise ValueError("Create a private backup directory before applying")
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, default=str
    ).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    descriptor = os.open(
        destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    if stat.S_IMODE(destination.stat().st_mode) != 0o600:
        raise ValueError("Backup permissions are not private")
    restored = destination.read_bytes()
    if hashlib.sha256(restored).hexdigest() != digest or json.loads(
        restored
    ) != json.loads(encoded):
        raise ValueError("Backup verification failed; no addresses were changed")
    return digest


async def run_repair(
    db: AsyncSession,
    *,
    apply: bool = False,
    expected_plan: str | None = None,
    backup_path: Path | None = None,
) -> dict:
    if apply and (not expected_plan or backup_path is None):
        raise ValueError(
            "Apply requires the reviewed fingerprint and a new private backup path"
        )
    if apply and db.bind is not None and db.bind.dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(843205091)"))
    plan = await recover_captured_mailing_addresses(db)
    report = {
        "mode": "apply" if apply else "dry_run",
        "fingerprint": plan.fingerprint,
        "planned_addresses": len(plan.items),
        "structured_addresses": sum(
            item.address.line1 is not None for item in plan.items
        ),
        "needs_review_contact_ids": list(plan.needs_review),
        "applied_addresses": 0,
    }
    if not apply:
        return report
    if expected_plan != plan.fingerprint:
        raise ValueError("Address recovery plan changed; review a fresh dry run")
    ids = [item.contact_id for item in plan.items]
    source_ids = [item.source_record_id for item in plan.items]
    existing = (
        (
            await db.execute(
                select(CRMContactAddress.__table__).where(
                    CRMContactAddress.contact_id.in_(ids)
                )
            )
        )
        .mappings()
        .all()
    )
    sources = (
        (
            await db.execute(
                select(CRMSourceRecord.__table__).where(
                    CRMSourceRecord.id.in_(source_ids)
                )
            )
        )
        .mappings()
        .all()
    )
    payload = {
        "repair": "captured-mailing-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "fingerprint": plan.fingerprint,
        "existing_addresses": [dict(row) for row in existing],
        "source_records": [dict(row) for row in sources],
        "planned_addresses": [asdict(item) for item in plan.items],
    }
    assert backup_path is not None
    digest = _write_verified_backup(backup_path, payload)
    applied = await recover_captured_mailing_addresses(
        db, expected_fingerprint=plan.fingerprint
    )
    for item in applied.items:
        db.add(
            CRMContactAuditEvent(
                contact_id=item.contact_id,
                actor_subject="operator:captured-mailing-v1",
                action="captured_mailing_address_recovered",
                before_json="{}",
                after_json=json.dumps(
                    {
                        "source_record_id": item.source_record_id,
                        "source_sha256": item.source_sha256,
                        "backup_sha256": digest,
                        "structured": item.address.line1 is not None,
                    },
                    sort_keys=True,
                ),
            )
        )
    await db.flush()
    return {
        **report,
        "applied_addresses": applied.applied,
        "backup_path": str(backup_path),
        "backup_sha256": digest,
    }


async def _main(args) -> None:
    from database import AsyncSessionLocal, engine

    try:
        async with AsyncSessionLocal() as db, db.begin():
            await db.execute(
                text(
                    "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
                    if args.apply
                    else "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
            )
            report = await run_repair(
                db,
                apply=args.apply,
                expected_plan=args.expected_plan,
                backup_path=args.backup_path,
            )
        print(json.dumps(report, sort_keys=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan")
    parser.add_argument("--backup-path", type=Path)
    asyncio.run(_main(parser.parse_args()))
