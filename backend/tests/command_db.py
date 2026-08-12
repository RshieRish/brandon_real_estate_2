"""Focused async SQLite fixtures for Command provenance tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from database import Base
from models.command import CRMArchiveArtifact
from models.command_provenance import (
    CRMEntitySource,
    CRMReconciliationResult,
    CRMReconciliationRun,
    CRMSourceRecord,
    CRMSourceRecordArtifact,
)


COMMAND_PROVENANCE_TABLES = (
    CRMArchiveArtifact.__table__,
    CRMSourceRecord.__table__,
    CRMSourceRecordArtifact.__table__,
    CRMEntitySource.__table__,
    CRMReconciliationRun.__table__,
    CRMReconciliationResult.__table__,
)


async def command_db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=COMMAND_PROVENANCE_TABLES,
            )
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def archive_artifact_row(
    *,
    source_path: str,
    content: bytes = b"private archive bytes",
) -> CRMArchiveArtifact:
    import hashlib

    return CRMArchiveArtifact(
        source_path=source_path,
        domain="kw_command",
        artifact_type="json",
        filename=source_path.rsplit("/", 1)[-1],
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        text_preview="",
        content_bytes=content,
    )
