"""Real database/API checks for archive navigation and immutable downloads."""
from __future__ import annotations

import hashlib
import warnings
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest
from fastapi import FastAPI
from jose import jwt
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import settings
from database import Base, get_db
from middleware.auth import require_admin
from models.command import CRMArchiveArtifact
from routers.command import router

PREFIX = "/api/v1/command/archive"


def zip_bytes(*members: tuple[str, bytes]) -> bytes:
    output = BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            for name, content in members:
                archive.writestr(name, content)
    return output.getvalue()


@pytest.fixture
async def archive_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[CRMArchiveArtifact.__table__]))
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


@pytest.fixture
async def client(archive_db):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/command")

    async def database():
        yield archive_db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[require_admin] = lambda: {"sub": "1"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        yield client


async def seed(db, path, content=b"preserved bytes", *, domain="docusign", missing=False):
    row = CRMArchiveArtifact(
        source_path=path, domain=domain, artifact_type=path.rsplit(".", 1)[-1],
        filename=path.rsplit("/", 1)[-1], sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content), text_preview="", content_bytes=None if missing else content,
    )
    db.add(row)
    await db.flush()
    return row


async def test_source_hierarchy_counts_every_descendant_and_pages_folders_with_files(client, archive_db):
    await seed(archive_db, "docusign/pages/home.html")
    await seed(archive_db, "docusign_full/download_bundles/A.zip")
    await seed(archive_db, "docusign_full/download_bundles/B.zip")
    await seed(archive_db, "docusign_full/templates/export.json")
    await seed(archive_db, "docusign_full/README.md")
    await seed(archive_db, "kw_command/contact.json", domain="kw_command")
    first = await client.get(f"{PREFIX}/browse", params={"domain": "docusign", "limit": 1})
    assert first.status_code == 200
    page = first.json()
    assert page["total"] == 2
    assert page["summary"]["files"] == 5
    assert page["summary"]["folders"] == 5
    assert page["summary"]["document_bundles"] == 2
    assert page["entries"][0]["path"] == "docusign"
    assert page["entries"][0]["file_count"] == 1
    second = (await client.get(f"{PREFIX}/browse", params={"domain": "docusign", "limit": 1, "offset": 1})).json()
    assert second["entries"][0]["path"] == "docusign_full"
    assert second["entries"][0]["file_count"] == 4
    inside = (await client.get(f"{PREFIX}/browse", params={"domain": "docusign", "path": "docusign_full"})).json()
    assert [item["entry_type"] for item in inside["entries"]] == ["folder", "folder", "artifact"]
    assert inside["entries"][-1]["content_kind"] == "supporting_file"


async def test_folder_boundaries_and_literal_search_do_not_leak_sibling_prefixes(client, archive_db):
    wanted = await seed(archive_db, "docusign_full/100%_done/Lease_A.pdf")
    await seed(archive_db, "docusign_full/100x_done/Lease_A.pdf")
    await seed(archive_db, "docusign_full/100%_done_elsewhere/Lease_A.pdf")
    page = (await client.get(f"{PREFIX}/browse", params={"path": "docusign_full/100%_done", "query": "lease_A"})).json()
    assert page.get("total") == 1
    assert page["entries"][0]["id"] == wanted.id
    literal = (await client.get(f"{PREFIX}/browse", params={"query": "100%_done/"})).json()
    assert literal["total"] == 1


async def test_search_finds_artifacts_beyond_first_page_and_labels_captures(client, archive_db):
    for index in range(105):
        await seed(archive_db, f"docusign_full/download_bundles/{index:03}.zip")
    capture = await seed(archive_db, "docusign_full/agreements/pages/last.snapshot.txt", missing=True)
    page = (await client.get(f"{PREFIX}/browse", params={"query": "LAST.snapshot"})).json()
    assert page.get("total") == 1
    assert page["entries"][0]["id"] == capture.id
    assert page["entries"][0]["content_kind"] == "source_capture"
    assert page["entries"][0]["download_available"] is False


async def test_flat_catalog_and_folder_queries_never_select_blob_payloads(client, archive_db):
    await seed(archive_db, "docusign_full/A.zip", content=b"large private payload")
    statements = []
    event.listen(archive_db.bind.sync_engine, "before_cursor_execute", lambda _conn, _cursor, statement, *_args: statements.append(statement))
    for route in ("artifacts", "browse"):
        response = await client.get(f"{PREFIX}/{route}")
        assert response.status_code == 200
    selected = [statement for statement in statements if statement.startswith("SELECT")]
    assert selected
    assert all("crm_archive_artifacts.content_bytes," not in statement for statement in selected)
    assert all("crm_archive_artifacts.content_bytes \n" not in statement for statement in selected)
    assert all("large private payload" not in response.text for response in [response])


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"path": "../private"}, {"path": "/absolute"}, {"path": "a\\b"}, {"path": "a//b"}, {"query": "x" * 501}])
async def test_browse_rejects_unbounded_or_noncanonical_requests(client, params):
    assert (await client.get(f"{PREFIX}/browse", params=params)).status_code == 422


async def test_bundle_navigation_exposes_real_pdf_names_and_duplicate_names_by_index(client, archive_db):
    first_pdf, second_pdf = b"%PDF-first-original", b"%PDF-second-original"
    row = await seed(archive_db, "docusign_full/download_bundles/Lease.zip", zip_bytes(("Documents/Lease.pdf", first_pdf), ("Summary.pdf", second_pdf), ("Summary.pdf", first_pdf)))
    listing = await client.get(f"{PREFIX}/artifacts/{row.id}/members")
    assert listing.status_code == 200
    page = listing.json()
    assert page["summary"]["files"] == 3
    assert page["summary"]["documents"] == 3
    assert page["entries"][0]["entry_type"] == "folder"
    assert page["entries"][0]["path"] == "Documents"
    assert [entry["member_index"] for entry in page["entries"][1:]] == [1, 2]
    nested = (await client.get(f"{PREFIX}/artifacts/{row.id}/members", params={"path": "Documents"})).json()
    assert nested["entries"][0]["filename"] == "Lease.pdf"
    for index, expected in ((0, first_pdf), (1, second_pdf), (2, first_pdf)):
        downloaded = await client.get(f"{PREFIX}/artifacts/{row.id}/members/{index}/content")
        assert downloaded.status_code == 200
        assert downloaded.content == expected
        assert downloaded.headers["x-content-sha256"] == hashlib.sha256(expected).hexdigest()
        assert downloaded.headers["x-archive-sha256"] == row.sha256
        assert downloaded.headers["cache-control"] == "private, no-store"


async def test_bundle_members_are_searchable_and_paginated_without_renaming(client, archive_db):
    row = await seed(archive_db, "docusign_full/A.zip", zip_bytes(*[(f"forms/{index:03}.pdf", b"%PDF-preserved") for index in range(105)]))
    page = (await client.get(f"{PREFIX}/artifacts/{row.id}/members", params={"path": "forms", "offset": 100, "limit": 10})).json()
    assert page.get("total") == 105
    assert len(page["entries"]) == 5
    searched = (await client.get(f"{PREFIX}/artifacts/{row.id}/members", params={"query": "104.pdf"})).json()
    assert searched["total"] == 1
    assert searched["entries"][0]["filename"] == "104.pdf"


async def test_explicit_empty_zip_folders_are_browsable_and_counted(client, archive_db):
    row = await seed(archive_db, "docusign_full/with_empty_folders.zip", zip_bytes(("Empty/Nested/", b""), ("Documents/Lease.pdf", b"%PDF-original")))
    root = (await client.get(f"{PREFIX}/artifacts/{row.id}/members")).json()
    assert root["summary"]["folders"] == 3
    assert [entry["name"] for entry in root["entries"]] == ["Documents", "Empty"]
    assert root["entries"][1]["file_count"] == 0
    empty = (await client.get(f"{PREFIX}/artifacts/{row.id}/members", params={"path": "Empty"})).json()
    assert empty["entries"][0]["path"] == "Empty/Nested"


async def test_unsafe_and_high_ratio_members_remain_visible_but_cannot_be_downloaded(client, archive_db):
    row = await seed(archive_db, "docusign_full/unsafe.zip", zip_bytes(("../outside.pdf", b"%PDF-original"), ("bomb.pdf", b"a" * 1_000_000)))
    response = await client.get(f"{PREFIX}/artifacts/{row.id}/members")
    assert response.status_code == 200
    assert response.json()["summary"]["files"] == 2
    assert all(not entry["download_available"] for entry in response.json()["entries"])
    for index in (0, 1):
        assert (await client.get(f"{PREFIX}/artifacts/{row.id}/members/{index}/content")).status_code == 409


async def test_corrupt_or_changed_archives_are_not_presented_as_valid_documents(client, archive_db):
    invalid = await seed(archive_db, "docusign_full/invalid.zip", b"not a ZIP")
    mismatch = await seed(archive_db, "docusign_full/changed.zip", zip_bytes(("real.pdf", b"%PDF-original")))
    mismatch.sha256 = "0" * 64
    missing = await seed(archive_db, "docusign_full/missing.zip", missing=True)
    for row in (invalid, mismatch, missing):
        assert (await client.get(f"{PREFIX}/artifacts/{row.id}/members")).status_code == 409
    assert (await client.get(f"{PREFIX}/artifacts/{mismatch.id}/content")).status_code == 409


async def test_original_download_preserves_bytes_and_safely_encodes_unicode_filename(client, archive_db):
    original = b"original signed bytes"
    row = await seed(archive_db, 'docusign_full/R\u00e9sum\u00e9 "signed".pdf', original)
    response = await client.get(f"{PREFIX}/artifacts/{row.id}/content")
    assert response.status_code == 200
    assert response.content == original
    assert "filename*=UTF-8''R%C3%A9sum%C3%A9%20%22signed%22.pdf" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("suffix", ["browse", "artifacts", "artifacts/1/content", "artifacts/1/members", "artifacts/1/members/0/content"])
async def test_all_archive_routes_require_an_administrator(suffix):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/command")
    public = jwt.encode({"sub": "1", "exp": 4_000_000_000, "scope": "link_pack_gate"}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        assert (await client.get(f"{PREFIX}/{suffix}")).status_code == 401
        assert (await client.get(f"{PREFIX}/{suffix}", headers={"Authorization": f"Bearer {public}"})).status_code == 403
