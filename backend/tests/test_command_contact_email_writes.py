"""Canonical primary-email handling for legacy Command contact writes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from database import Base, get_db
from middleware import auth as auth_middleware
from middleware.auth import require_admin
from models.command import (
    CRMActivity,
    CRMAgreement,
    CRMContact,
    CRMNote,
    CRMOpportunityContact,
    CRMReferral,
    CRMSavedSearch,
    CRMTask,
)
from models.command_contacts import CRMContactAuditEvent, CRMContactMethod
from routers import command as command_router
from routers.command import delete_saved_search, import_archive_bundle, saved_searches
from routers.command_contacts import import_contacts
from schemas.command import (
    ArchiveAgreementImportRow,
    ArchiveBundleImportRequest,
    ArchiveNoteImportRow,
    ArchiveOpportunityImportRow,
    ArchiveReferralImportRow,
    ArchiveTaskImportRow,
    ContactImportRow,
)
from schemas.command_contacts import ContactImportIn, ContactImportRowIn
from services.command_contact_contracts import (
    ContactImportRowCommand,
    ContactMutationResult,
    ContactSavedSearchValue,
    WorkspaceMutationResult,
)
from services.command_contacts import (
    ContactDataIntegrityError,
    ContactLinkConflict,
    ContactNotFound,
    ContactNotInDirectory,
    ContactSectionUnsupported,
    _ArchiveContactIngestResult,
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


def _focused_row(
    email: str | None, *, first_name: str = "Synthetic"
) -> ContactImportRowIn:
    return ContactImportRowIn(**_row(email, first_name=first_name).model_dump())


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
        ContactImportIn(
            contacts=[
                _focused_row("owner@example.test", first_name="Existing duplicate"),
                _focused_row("New@Example.Test", first_name="New one"),
                _focused_row(" ｎｅｗ@example.test ", first_name="New duplicate"),
                _focused_row("not-an-email", first_name="Invalid one"),
                _focused_row("not-an-email", first_name="Invalid two"),
            ]
        ),
        email_write_db,
        actor_subject="17",
    )

    assert result.model_dump() == {"created": 3, "skipped_duplicates": 2}
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
            actor_subject="17",
        )
    finally:
        event.remove(email_write_db.bind.sync_engine, "before_cursor_execute", capture)

    assert result.created["contacts"] == 1
    assert result.skipped_duplicates["contacts"] == 2
    assert result.unresolved_contact_references == 0
    tasks = (await email_write_db.scalars(select(CRMTask).order_by(CRMTask.id))).all()
    assert [task.contact_id for task in tasks] == [owner.id, owner.id + 1]
    contact_queries = [query for query in statements if "FROM crm_contacts" in query]
    assert contact_queries
    assert all("normalized_email" in query for query in contact_queries)
    assert all("lower(" not in query.casefold() for query in contact_queries)
    assert all("WHERE" in query for query in contact_queries)


@pytest.mark.asyncio
async def test_archive_import_never_attaches_children_to_an_ambiguous_email_owner(
    email_write_db: AsyncSession,
):
    owners = [
        CRMContact(
            first_name="First",
            last_name="Owner",
            email="duplicate@example.test",
            stage="lead",
        ),
        CRMContact(
            first_name="Second",
            last_name="Owner",
            email=" ＤＵＰＬＩＣＡＴＥ@Example.Test ",
            stage="lead",
        ),
    ]
    email_write_db.add_all(owners)
    await email_write_db.flush()

    result = await import_archive_bundle(
        ArchiveBundleImportRequest(
            contacts=[_row("DUPLICATE@example.test", first_name="Third owner")],
            tasks=[
                ArchiveTaskImportRow(
                    title="Ambiguous task",
                    contact_email="duplicate@example.test",
                )
            ],
            notes=[
                ArchiveNoteImportRow(
                    body="Ambiguous note",
                    contact_email="duplicate@example.test",
                )
            ],
            opportunities=[
                ArchiveOpportunityImportRow(
                    name="Ambiguous opportunity",
                    contact_emails=["duplicate@example.test"],
                )
            ],
            referrals=[
                ArchiveReferralImportRow(
                    name="Ambiguous referral",
                    contact_email="duplicate@example.test",
                )
            ],
            agreements=[
                ArchiveAgreementImportRow(
                    title="Ambiguous agreement",
                    contact_email="duplicate@example.test",
                )
            ],
        ),
        email_write_db,
        actor_subject="17",
    )

    assert result.created["contacts"] == 0
    assert result.skipped_duplicates["contacts"] == 1
    assert result.unresolved_contact_references == 5
    assert len((await email_write_db.scalars(select(CRMContact))).all()) == 2

    tasks = (await email_write_db.scalars(select(CRMTask))).all()
    referrals = (await email_write_db.scalars(select(CRMReferral))).all()
    agreements = (await email_write_db.scalars(select(CRMAgreement))).all()
    assert len(tasks) == len(referrals) == len(agreements) == 1
    assert tasks[0].contact_id is None
    assert referrals[0].contact_id is None
    assert agreements[0].contact_id is None
    assert (await email_write_db.scalars(select(CRMNote))).all() == []
    assert (await email_write_db.scalars(select(CRMOpportunityContact))).all() == []


@pytest.mark.asyncio
async def test_contact_import_skips_when_canonical_email_has_multiple_owners(
    email_write_db: AsyncSession,
):
    email_write_db.add_all(
        [
            CRMContact(
                first_name="First",
                last_name="Owner",
                email="duplicate@example.test",
                stage="lead",
            ),
            CRMContact(
                first_name="Second",
                last_name="Owner",
                email=" ＤＵＰＬＩＣＡＴＥ@Example.Test ",
                stage="lead",
            ),
        ]
    )
    await email_write_db.flush()

    result = await import_contacts(
        ContactImportIn(
            contacts=[_focused_row("DUPLICATE@example.test", first_name="Third owner")]
        ),
        email_write_db,
        actor_subject="17",
    )

    assert result.model_dump() == {"created": 0, "skipped_duplicates": 1}
    assert len((await email_write_db.scalars(select(CRMContact))).all()) == 2
    assert (await email_write_db.scalars(select(CRMActivity))).all() == []


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
        ContactImportIn(contacts=[_focused_row("fixture@example.test")]),
        email_write_db,
        actor_subject="17",
    )
    assert result.model_dump() == {"created": 1, "skipped_duplicates": 0}
    activities = (await email_write_db.scalars(select(CRMActivity))).all()
    assert len(activities) == 1
    assert "fixture@example.test" not in activities[0].summary


@pytest.mark.asyncio
async def test_global_saved_search_list_delegates_and_canonicalizes_response(
    monkeypatch,
):
    db = object()
    calls: list[object] = []

    async def list_values(actual_db):
        calls.append(actual_db)
        return (
            ContactSavedSearchValue(
                id=7,
                contact_id=3,
                contact_name="Synthetic Contact",
                name="Exact search",
                criteria={"z": (2, 1), "a": {"value": True}},
                updated_at=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
            ),
        )

    monkeypatch.setattr(
        command_router,
        "contact_service",
        SimpleNamespace(list_saved_searches=list_values),
        raising=False,
    )

    result = await saved_searches(db)  # type: ignore[arg-type]

    assert calls == [db]
    assert [item.model_dump(mode="json") for item in result] == [
        {
            "id": 7,
            "name": "Exact search",
            "criteria": '{"a":{"value":true},"z":[2,1]}',
            "contact_id": 3,
            "contact_name": "Synthetic Contact",
            "updated_at": "2026-08-13T12:00:00Z",
        }
    ]


@pytest.mark.asyncio
async def test_global_saved_search_delete_forwards_actor_and_validates_identity(
    monkeypatch,
):
    db = object()
    seen: list[tuple[object, int, str]] = []

    async def delete_value(actual_db, search_id, *, actor_subject):
        seen.append((actual_db, search_id, actor_subject))
        return ContactMutationResult(3, search_id, True, "contact_audit", 9)

    monkeypatch.setattr(
        command_router,
        "contact_service",
        SimpleNamespace(delete_saved_search=delete_value),
        raising=False,
    )

    result = await delete_saved_search(7, db, actor_subject="17")  # type: ignore[arg-type]

    assert seen == [(db, 7, "17")]
    assert result.model_dump() == {"deleted": True, "id": 7}

    async def wrong_value(*_args, **_kwargs):
        return ContactMutationResult(3, 8, True, "contact_audit", 10)

    monkeypatch.setattr(
        command_router.contact_service, "delete_saved_search", wrong_value
    )
    with pytest.raises(HTTPException) as error:
        await delete_saved_search(7, db, actor_subject="17")  # type: ignore[arg-type]
    assert error.value.status_code == 409
    assert "8" not in str(error.value.detail)


@pytest.mark.asyncio
async def test_archive_import_delegates_contacts_once_with_all_child_references(
    monkeypatch,
    email_write_db: AsyncSession,
):
    calls: list[tuple[tuple[object, ...], tuple[str | None, ...], str]] = []

    async def ingest(_db, contacts, references, *, actor_subject):
        calls.append((contacts, references, actor_subject))
        return command_router.contact_service._ArchiveContactIngestResult(
            created=1,
            skipped_duplicates=0,
            owner_contact_ids_by_normalized_email={
                "contact@example.test": None,
                "task@example.test": None,
                "note@example.test": None,
                "first@example.test": None,
                "second@example.test": None,
                "referral@example.test": None,
                "agreement@example.test": None,
            },
        )

    real_service = command_router.contact_service
    monkeypatch.setattr(real_service, "ingest_archive_contacts", ingest)
    payload = ArchiveBundleImportRequest(
        contacts=[_row("contact@example.test")],
        tasks=[ArchiveTaskImportRow(title="Task", contact_email="task@example.test")],
        notes=[ArchiveNoteImportRow(body="Note", contact_email="note@example.test")],
        opportunities=[
            ArchiveOpportunityImportRow(
                name="Opportunity",
                contact_emails=["first@example.test", "second@example.test"],
            )
        ],
        referrals=[
            ArchiveReferralImportRow(
                name="Referral", contact_email="referral@example.test"
            )
        ],
        agreements=[
            ArchiveAgreementImportRow(
                title="Agreement", contact_email="agreement@example.test"
            )
        ],
    )

    result = await import_archive_bundle(
        payload,
        email_write_db,
        actor_subject="17",
    )

    assert len(calls) == 1
    contacts, references, actor = calls[0]
    assert actor == "17"
    assert len(contacts) == 1
    assert isinstance(contacts[0], ContactImportRowCommand)
    assert contacts[0].email == "contact@example.test"
    assert references == (
        "task@example.test",
        "note@example.test",
        "first@example.test",
        "second@example.test",
        "referral@example.test",
        "agreement@example.test",
    )
    assert result.created["contacts"] == 1
    assert result.unresolved_contact_references == 6


@pytest.mark.asyncio
async def test_global_saved_search_list_preserves_service_order_without_autoflush(
    email_write_db: AsyncSession,
):
    older = CRMSavedSearch(
        contact_id=None,
        name="Older",
        criteria_json='{"z":2,"a":1}',
        updated_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
    )
    newer = CRMSavedSearch(
        contact_id=None,
        name="Newer",
        criteria_json='{"nested":{"ok":true}}',
        updated_at=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
    )
    email_write_db.add_all([older, newer])
    await email_write_db.flush()
    pending = CRMContact(first_name=None, last_name="", stage="lead")
    email_write_db.add(pending)
    flushes = 0

    def before_flush(*_args):
        nonlocal flushes
        flushes += 1

    event.listen(email_write_db.sync_session, "before_flush", before_flush)
    try:
        result = await saved_searches(email_write_db)
    finally:
        event.remove(email_write_db.sync_session, "before_flush", before_flush)
        email_write_db.expunge(pending)

    assert flushes == 0
    assert [item.id for item in result] == [newer.id, older.id]
    assert [item.criteria for item in result] == [
        '{"nested":{"ok":true}}',
        '{"a":1,"z":2}',
    ]


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (ContactNotFound("private-saved-search"), 404),
        (ContactNotInDirectory("private-saved-search"), 409),
        (ContactDataIntegrityError("private-saved-search"), 409),
        (ContactLinkConflict("private-saved-search"), 409),
        (ContactSectionUnsupported("private-saved-search"), 422),
        (RuntimeError("private-saved-search"), 500),
    ],
)
@pytest.mark.asyncio
async def test_global_saved_search_list_errors_are_exact_and_private(
    monkeypatch,
    caplog,
    error: Exception,
    status_code: int,
):
    async def fail(_db):
        raise error

    monkeypatch.setattr(command_router.contact_service, "list_saved_searches", fail)
    with pytest.raises(HTTPException) as caught:
        await saved_searches(object())  # type: ignore[arg-type]

    assert caught.value.status_code == status_code
    assert "private-saved-search" not in str(caught.value.detail)
    assert "private-saved-search" not in caplog.text


@pytest.mark.asyncio
async def test_global_saved_search_list_response_validation_is_private(
    monkeypatch,
    caplog,
):
    async def invalid(_db):
        return (SimpleNamespace(id=True, private="private-result"),)

    monkeypatch.setattr(command_router.contact_service, "list_saved_searches", invalid)
    with pytest.raises(HTTPException) as caught:
        await saved_searches(object())  # type: ignore[arg-type]

    assert caught.value.status_code == 500
    assert "private-result" not in str(caught.value.detail)
    assert "private-result" not in caplog.text


@pytest.mark.parametrize(
    "result",
    [
        ContactMutationResult(3, 7, True, "contact_audit", 9),
        WorkspaceMutationResult(7, True, "workspace_activity", 9),
    ],
)
@pytest.mark.asyncio
async def test_global_saved_search_delete_accepts_both_exact_result_variants(
    monkeypatch,
    result,
):
    async def delete_value(_db, search_id, *, actor_subject):
        assert (search_id, actor_subject) == (7, "17")
        return result

    monkeypatch.setattr(
        command_router.contact_service, "delete_saved_search", delete_value
    )

    response = await delete_saved_search(7, object(), actor_subject="17")  # type: ignore[arg-type]

    assert response.model_dump() == {"deleted": True, "id": 7}


@pytest.mark.parametrize(
    "result",
    [
        ContactMutationResult(3, 7, False, None, None),
        ContactMutationResult(3, 8, True, "contact_audit", 9),
        object(),
    ],
)
@pytest.mark.asyncio
async def test_global_saved_search_delete_rejects_noop_wrong_or_unknown_result(
    monkeypatch,
    result,
):
    async def delete_value(*_args, **_kwargs):
        return result

    monkeypatch.setattr(
        command_router.contact_service, "delete_saved_search", delete_value
    )
    with pytest.raises(HTTPException) as caught:
        await delete_saved_search(7, object(), actor_subject="17")  # type: ignore[arg-type]

    assert caught.value.status_code == 409


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (ContactNotFound("private-delete"), 404),
        (ContactNotInDirectory("private-delete"), 409),
        (ContactDataIntegrityError("private-delete"), 409),
        (ContactLinkConflict("private-delete"), 409),
        (ContactSectionUnsupported("private-delete"), 422),
        (HTTPException(418, detail="private-delete"), 500),
        (RuntimeError("private-delete"), 500),
    ],
)
@pytest.mark.asyncio
async def test_global_saved_search_delete_errors_are_exact_and_private(
    monkeypatch,
    caplog,
    error: Exception,
    status_code: int,
):
    async def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(command_router.contact_service, "delete_saved_search", fail)
    with pytest.raises(HTTPException) as caught:
        await delete_saved_search(7, object(), actor_subject="17")  # type: ignore[arg-type]

    assert caught.value.status_code == status_code
    assert "private-delete" not in str(caught.value.detail)
    assert "private-delete" not in caplog.text


def _retained_global_client(monkeypatch, db: object) -> TestClient:
    app = FastAPI()
    app.include_router(command_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_admin] = lambda: {"sub": "17"}
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "value",
    ["0", "-1", "+1", "01", "1.0", "true", " 1", "1 "],
)
def test_global_saved_search_delete_rejects_noncanonical_path_before_service(
    monkeypatch,
    value: str,
):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("service must not run")

    monkeypatch.setattr(
        command_router.contact_service, "delete_saved_search", forbidden
    )
    response = _retained_global_client(monkeypatch, object()).delete(
        f"/saved-searches/{value}"
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_retained_mutations_share_one_admin_decode_and_forward_subject(
    monkeypatch,
    email_write_db: AsyncSession,
):
    decode_calls = 0
    real_decode = auth_middleware.jwt.decode
    actors: list[str] = []

    def counted_decode(*args, **kwargs):
        nonlocal decode_calls
        decode_calls += 1
        return real_decode(*args, **kwargs)

    async def delete_value(_db, search_id, *, actor_subject):
        actors.append(actor_subject)
        return WorkspaceMutationResult(search_id, True, "workspace_activity", 9)

    async def ingest(_db, _contacts, _references, *, actor_subject):
        actors.append(actor_subject)
        return _ArchiveContactIngestResult(0, 0, {})

    monkeypatch.setattr(auth_middleware.jwt, "decode", counted_decode)
    monkeypatch.setattr(
        command_router.contact_service, "delete_saved_search", delete_value
    )
    monkeypatch.setattr(
        command_router.contact_service, "ingest_archive_contacts", ingest
    )
    token = jwt.encode(
        {
            "sub": "17",
            "token_type": "admin_session",
            "scope": "admin",
            "exp": int(datetime.now(UTC).timestamp()) + 300,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    app = FastAPI()
    app.include_router(command_router.router)

    async def override_db():
        yield email_write_db

    app.dependency_overrides[get_db] = override_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        deleted = await client.delete("/saved-searches/7")
        archived = await client.post("/archive/import", json={})

    assert deleted.status_code == archived.status_code == 200
    assert decode_calls == 2
    assert actors == ["17", "17"]


@pytest.mark.asyncio
async def test_archive_children_use_private_id_map_without_contact_refetch(
    monkeypatch,
    email_write_db: AsyncSession,
):
    owner = CRMContact(
        first_name="Existing",
        last_name="Owner",
        email="owner@example.test",
        stage="lead",
    )
    email_write_db.add(owner)
    await email_write_db.flush()

    async def ingest(_db, _contacts, _references, *, actor_subject):
        assert actor_subject == "17"
        return _ArchiveContactIngestResult(
            0,
            0,
            {"owner@example.test": owner.id},
        )

    monkeypatch.setattr(
        command_router.contact_service, "ingest_archive_contacts", ingest
    )
    assert not hasattr(command_router, "_contacts_by_normalized_emails")
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.split()))

    assert email_write_db.bind is not None
    event.listen(email_write_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        result = await import_archive_bundle(
            ArchiveBundleImportRequest(
                tasks=[
                    ArchiveTaskImportRow(
                        title="Mapped task",
                        contact_email=" ＯＷＮＥＲ@Example.Test ",
                    )
                ]
            ),
            email_write_db,
            actor_subject="17",
        )
    finally:
        event.remove(email_write_db.bind.sync_engine, "before_cursor_execute", capture)

    assert result.created["tasks"] == 1
    task = await email_write_db.scalar(select(CRMTask))
    assert task is not None and task.contact_id == owner.id
    assert not any("FROM crm_contacts" in statement for statement in statements)


@pytest.mark.asyncio
async def test_archive_missing_owner_key_fails_closed_without_private_value(
    monkeypatch,
    email_write_db: AsyncSession,
    caplog,
):
    private_email = "private-missing-owner@example.test"

    async def ingest(*_args, **_kwargs):
        return _ArchiveContactIngestResult(0, 0, {})

    monkeypatch.setattr(
        command_router.contact_service, "ingest_archive_contacts", ingest
    )
    with pytest.raises(HTTPException) as caught:
        await import_archive_bundle(
            ArchiveBundleImportRequest(
                tasks=[
                    ArchiveTaskImportRow(
                        title="Missing owner", contact_email=private_email
                    )
                ]
            ),
            email_write_db,
            actor_subject="17",
        )

    assert caught.value.status_code == 409
    assert private_email not in str(caught.value.detail)
    assert private_email not in caplog.text


@pytest.mark.asyncio
async def test_archive_service_http_exception_is_private_generic_500(
    monkeypatch,
    email_write_db: AsyncSession,
    caplog,
):
    async def fail(*_args, **_kwargs):
        raise HTTPException(418, detail="private-archive-service")

    monkeypatch.setattr(command_router.contact_service, "ingest_archive_contacts", fail)
    with pytest.raises(HTTPException) as caught:
        await import_archive_bundle(
            ArchiveBundleImportRequest(),
            email_write_db,
            actor_subject="17",
        )

    assert caught.value.status_code == 500
    assert caught.value.detail == "Unable to import archive data"
    assert "private-archive-service" not in caplog.text


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (ContactNotFound("private-archive-domain"), 404),
        (ContactNotInDirectory("private-archive-domain"), 409),
        (ContactDataIntegrityError("private-archive-domain"), 409),
        (ContactLinkConflict("private-archive-domain"), 409),
        (ContactSectionUnsupported("private-archive-domain"), 422),
    ],
)
@pytest.mark.asyncio
async def test_archive_domain_errors_map_exactly_without_private_values(
    monkeypatch,
    email_write_db: AsyncSession,
    caplog,
    error: Exception,
    status_code: int,
):
    async def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(command_router.contact_service, "ingest_archive_contacts", fail)
    with pytest.raises(HTTPException) as caught:
        await import_archive_bundle(
            ArchiveBundleImportRequest(),
            email_write_db,
            actor_subject="17",
        )

    assert caught.value.status_code == status_code
    assert "private-archive-domain" not in str(caught.value.detail)
    assert "private-archive-domain" not in caplog.text


@pytest.mark.asyncio
async def test_archive_contact_command_validation_is_narrow_422(
    monkeypatch,
    email_write_db: AsyncSession,
):
    class InvalidContactCommand:
        def __init__(self, **_kwargs):
            raise ValueError("private-contact-command")

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("service must not run")

    monkeypatch.setattr(
        command_router, "ContactImportRowCommand", InvalidContactCommand
    )
    monkeypatch.setattr(
        command_router.contact_service, "ingest_archive_contacts", forbidden
    )
    with pytest.raises(HTTPException) as caught:
        await import_archive_bundle(
            ArchiveBundleImportRequest(contacts=[_row("private@example.test")]),
            email_write_db,
            actor_subject="17",
        )

    assert caught.value.status_code == 422
    assert "private-contact-command" not in str(caught.value.detail)


@pytest.mark.asyncio
async def test_archive_empty_child_references_do_not_increment_unresolved(
    monkeypatch,
    email_write_db: AsyncSession,
):
    async def ingest(_db, _contacts, references, *, actor_subject):
        assert actor_subject == "17"
        assert references == ("", "", "", "", "")
        return _ArchiveContactIngestResult(0, 0, {})

    monkeypatch.setattr(
        command_router.contact_service, "ingest_archive_contacts", ingest
    )
    result = await import_archive_bundle(
        ArchiveBundleImportRequest(
            tasks=[ArchiveTaskImportRow(title="No owner", contact_email="")],
            notes=[ArchiveNoteImportRow(body="No owner", contact_email="")],
            opportunities=[
                ArchiveOpportunityImportRow(name="No owner", contact_emails=[""])
            ],
            referrals=[ArchiveReferralImportRow(name="No owner", contact_email="")],
            agreements=[ArchiveAgreementImportRow(title="No owner", contact_email="")],
        ),
        email_write_db,
        actor_subject="17",
    )

    assert result.unresolved_contact_references == 0
    assert result.created == {
        "contacts": 0,
        "tasks": 1,
        "notes": 0,
        "opportunities": 1,
        "referrals": 1,
        "listings": 0,
        "templates": 0,
        "agreements": 1,
    }
    assert await email_write_db.scalar(select(func.count()).select_from(CRMTask)) == 1
    assert await email_write_db.scalar(select(func.count()).select_from(CRMNote)) == 0
    assert (
        await email_write_db.scalar(
            select(func.count()).select_from(CRMOpportunityContact)
        )
        == 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_after_children", [False, True])
async def test_archive_real_request_finalizer_commits_or_rolls_back_atomically(
    monkeypatch,
    tmp_path: Path,
    fail_after_children: bool,
):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / f'archive-finalizer-{fail_after_children}.sqlite'}",
        connect_args={"autocommit": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(command_router.router)
    app.dependency_overrides[require_admin] = lambda: {"sub": "17"}

    async def request_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = request_db
    if fail_after_children:

        class RejectingAdapter:
            def validate_python(self, _value):
                raise RuntimeError("private-late-adapter")

        monkeypatch.setattr(
            command_router, "_ARCHIVE_IMPORT_ADAPTER", RejectingAdapter()
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/archive/import",
            json={
                "contacts": [
                    {
                        "first_name": "Atomic",
                        "last_name": "Owner",
                        "email": "atomic@example.test",
                        "stage": "lead",
                    }
                ],
                "tasks": [
                    {
                        "title": "Atomic task",
                        "contact_email": "atomic@example.test",
                    }
                ],
            },
        )

    assert response.status_code == (500 if fail_after_children else 200)
    assert "private-late-adapter" not in response.text
    async with factory() as verifier:
        expected = 0 if fail_after_children else 1
        assert (
            await verifier.scalar(select(func.count()).select_from(CRMContact))
            == expected
        )
        assert (
            await verifier.scalar(select(func.count()).select_from(CRMTask)) == expected
        )
        assert (
            await verifier.scalar(
                select(func.count()).select_from(CRMContactAuditEvent)
            )
            == expected
        )
        assert (
            await verifier.scalar(select(func.count()).select_from(CRMActivity))
            == expected * 2
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_global_exception_handler_redacts_dependency_finalizer_failure(
    caplog,
):
    from main import global_exception_handler

    app = FastAPI()
    app.add_exception_handler(Exception, global_exception_handler)

    async def failing_finalizer():
        try:
            yield object()
        finally:
            raise RuntimeError("private-finalizer-value")

    finalizer_dependency = Depends(failing_finalizer)

    @app.get("/finalizer")
    async def endpoint(_value=finalizer_dependency):
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/finalizer")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert "private-finalizer-value" not in response.text
    assert "private-finalizer-value" not in caplog.text


def test_retained_global_route_models_and_transaction_ownership_are_exact():
    archive_route = next(
        route
        for route in command_router.router.routes
        if isinstance(route, APIRoute)
        and route.path == "/archive/import"
        and route.methods == {"POST"}
    )
    assert archive_route.response_model is command_router.ArchiveBundleImportResult

    import inspect

    source = "\n".join(
        inspect.getsource(callable_)
        for callable_ in (
            command_router.saved_searches,
            command_router.delete_saved_search,
            command_router.import_archive_bundle,
            command_router._import_archive_bundle,
        )
    )
    for forbidden in (".commit(", ".rollback(", ".begin(", "CRMContactAuditEvent("):
        assert forbidden not in source
