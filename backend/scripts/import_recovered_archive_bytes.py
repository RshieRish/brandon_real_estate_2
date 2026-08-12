"""Persist a locally recovered Command/DocuSign archive inside PostgreSQL.

Run with ARCHIVE_ROOT pointed to the trusted recovered archive. The importer is
resumable: rows whose checksum already matches are left untouched.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

from sqlalchemy import bindparam, select, update

from database import AsyncSessionLocal
from models.command import CRMArchiveArtifact


BATCH_SIZE = 25


async def main() -> None:
    root_value = os.environ.get("ARCHIVE_ROOT")
    if not root_value:
        raise RuntimeError("ARCHIVE_ROOT is required")
    root = Path(root_value).resolve()
    if not root.is_dir():
        raise RuntimeError("ARCHIVE_ROOT must be a readable directory")

    async with AsyncSessionLocal() as db:
        artifacts = (await db.execute(
            select(CRMArchiveArtifact.id, CRMArchiveArtifact.source_path, CRMArchiveArtifact.sha256)
            .where(CRMArchiveArtifact.content_bytes.is_(None))
            .order_by(CRMArchiveArtifact.id)
        )).all()
        pending = 0
        stored = 0
        batch: list[dict[str, object]] = []
        statement = update(CRMArchiveArtifact).values(content_bytes=bindparam("payload")).execution_options(synchronize_session=False)
        for artifact_id, source_path, expected_digest in artifacts:
            path = (root / source_path).resolve()
            if root not in path.parents or not path.is_file():
                raise RuntimeError(f"Archive artifact is missing: {source_path}")
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != expected_digest:
                raise RuntimeError(f"Checksum mismatch: {source_path}")
            pending += 1
            stored += len(data)
            batch.append({"id": artifact_id, "payload": data})
            if len(batch) == BATCH_SIZE:
                await db.execute(statement, batch)
                await db.commit()
                print(f"stored={pending} bytes={stored}", flush=True)
                batch = []
        if batch:
            await db.execute(statement, batch)
        await db.commit()
        remaining = (await db.execute(select(CRMArchiveArtifact).where(CRMArchiveArtifact.content_bytes.is_(None)))).scalars().all()
    print(f"complete stored={pending} bytes={stored} remaining={len(remaining)}")


if __name__ == "__main__":
    asyncio.run(main())
