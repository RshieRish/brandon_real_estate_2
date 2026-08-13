"""Canonical primary-email handling for legacy Command contact writes."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base
from models.command import CRMActivity, CRMContact, CRMTask
from models.command_contacts import CRMContactMethod
from routers.command import import_archive_bundle, import_contacts
from schemas.command import (
    ArchiveBundleImportRequest,
    ArchiveTaskImportRow,
    ContactImportRequest,
    ContactImportRow,
)


@pytest_asyncio.fixture()
async def email_write_db(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'contact-email-writes.sqlite'}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _row(email: str | None, *, first_name: str = "Synthetic") -> ContactImportRow:
    return ContactImportRow(
        first_name=first_name,
        last_name="Contact",
        email=email,
        phone=None,
        stage="lead",
        birthday=None,
        anniversary=None,
    )


@pytest.mark.asyncio
async def test_contact_import_uses_canonical_email_and_dedupes_within_request(
    email_write_db: AsyncSession,
):
    email_write_db.add(
        CRMContact(
            first_name="Existing",
            last_name="Contact",
            email=" ＯＷＮＥＲ＠Ｅｘａｍｐｌｅ．ＴＥＳＴ ",
            stage="lead",
        )
    )
    await email_write_db.flush()

    result = await import_contacts(
        ContactImportRequest(
            contacts=[
                _row("owner@example.test", first_name="Existing duplicate"),
                _row("New@Example.Test", first_name="New one"),
                _row(" ｎｅｗ@example.test ", first_name="New duplicate"),
                _row("not-an-email", first_name="Invalid one"),
                _row("not-an-email", first_name="Invalid two"),
            ]
        ),
        email_write_db,
    )

    assert result == {"created": 3, "skipped_duplicates": 2}
    contacts = (
        await email_write_db.scalars(select(CRMContact).order_by(CRMContact.id))
    ).all()
    assert [contact.first_name for contact in contacts] == [
        "Existing",
        "New one",
        "Invalid one",
        "Invalid two",
    ]
    assert [contact.normalized_email for contact in contacts] == [
        "owner@example.test",
        "new@example.test",
        None,
        None,
    ]


@pytest.mark.asyncio
async def test_archive_import_queries_only_referenced_canonical_emails_and_links_them(
    email_write_db: AsyncSession,
):
    rows = [
        CRMContact(
            first_name="Noise",
            last_name=str(index),
            email=f"noise-{index}@example.test",
            stage="lead",
        )
        for index in range(1, 1_202)
    ]
    owner = CRMContact(
        first_name="Existing",
        last_name="Owner",
        email=" ＯＷＮＥＲ＠Ｅｘａｍｐｌｅ．ＴＥＳＴ ",
        stage="lead",
    )
    email_write_db.add_all([*rows, owner])
    await email_write_db.flush()

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.split()))

    assert email_write_db.bind is not None
    event.listen(email_write_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        result = await import_archive_bundle(
            ArchiveBundleImportRequest(
                contacts=[
                    _row("owner@example.test", first_name="Existing duplicate"),
                    _row("New@Example.Test", first_name="New owner"),
                    _row(" ｎｅｗ@example.test ", first_name="New duplicate"),
                ],
                tasks=[
                    ArchiveTaskImportRow(
                        title="Canonical reference",
                        contact_email="owner@example.test",
                    ),
                    ArchiveTaskImportRow(
                        title="New canonical reference",
                        contact_email="ＮＥＷ@example.test",
                    ),
                ],
            ),
            email_write_db,
        )
    finally:
        event.remove(
            email_write_db.bind.sync_engine, "before_cursor_execute", capture
        )

    assert result["created"]["contacts"] == 1
    assert result["skipped_duplicates"]["contacts"] == 2
    assert result["unresolved_contact_references"] == 0
    tasks = (
        await email_write_db.scalars(select(CRMTask).order_by(CRMTask.id))
    ).all()
    assert [task.contact_id for task in tasks] == [owner.id, owner.id + 1]
    contact_queries = [query for query in statements if "FROM crm_contacts" in query]
    assert contact_queries
    assert all("normalized_email" in query for query in contact_queries)
    assert all("lower(" not in query.casefold() for query in contact_queries)
    assert all("WHERE" in query for query in contact_queries)


@pytest.mark.asyncio
async def test_contact_import_does_not_consult_recovered_methods_or_echo_email(
    email_write_db: AsyncSession,
):
    evidence_only = CRMContact(
        first_name="Evidence",
        last_name="Only",
        email=None,
        stage="lead",
    )
    email_write_db.add(evidence_only)
    await email_write_db.flush()
    email_write_db.add(
        CRMContactMethod(
            contact_id=evidence_only.id,
            source_record_id=None,
            source_key="synthetic:method:email",
            kind="email",
            label="recovered",
            raw_value="fixture@example.test",
            normalized_value="fixture@example.test",
            is_primary=True,
        )
    )
    await email_write_db.flush()

    result = await import_contacts(
        ContactImportRequest(contacts=[_row("fixture@example.test")]),
        email_write_db,
    )
    assert result == {"created": 1, "skipped_duplicates": 0}
    activities = (await email_write_db.scalars(select(CRMActivity))).all()
    assert len(activities) == 1
    assert "fixture@example.test" not in activities[0].summary
