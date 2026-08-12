"""Read-only API coverage for recovered Command provenance evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import Base, get_db
from main import app
from middleware.auth import require_admin
from models.command import CRMArchiveArtifact
from models.command_provenance import (
    CRMEntitySource,
    CRMReconciliationResult,
    CRMReconciliationRun,
    CRMSourceRecord,
    CRMSourceRecordArtifact,
)


PROVENANCE_TABLES = (
    CRMArchiveArtifact.__table__,
    CRMSourceRecord.__table__,
    CRMSourceRecordArtifact.__table__,
    CRMEntitySource.__table__,
    CRMReconciliationRun.__table__,
    CRMReconciliationResult.__table__,
)


@pytest.fixture
async def provenance_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=PROVENANCE_TABLES,
            )
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def seeded_provenance(provenance_db):
    private_bytes = b"private recovered contact contents"
    artifact = CRMArchiveArtifact(
        source_path="kw_command_repaired/contacts/alice.json",
        domain="kw_command",
        artifact_type="json",
        filename="alice.json",
        sha256=hashlib.sha256(private_bytes).hexdigest(),
        size_bytes=len(private_bytes),
        text_preview="Alice Adams",
        content_bytes=private_bytes,
    )
    provenance_db.add(artifact)
    await provenance_db.flush()

    records = [
        CRMSourceRecord(
            source_system="kw_command",
            module="contacts",
            record_kind="contact",
            source_key="contact-z",
            evidence_level="observed_record",
            display_label="Zed Contact",
            payload_json='{"email":"zed@example.com"}',
            capture_quality="complete",
            captured_at=datetime(2026, 7, 27, 20, 1, tzinfo=UTC),
            parser_version="command-v1",
        ),
        CRMSourceRecord(
            source_system="kw_command",
            module="contacts",
            record_kind="contact",
            source_key="contact-a",
            evidence_level="observed_record",
            display_label="Alice Adams",
            payload_json='{"email":"alice@example.com","tags":["buyer"]}',
            capture_quality="complete",
            captured_at=datetime(2026, 7, 27, 20, 0, tzinfo=UTC),
            parser_version="command-v1",
        ),
        CRMSourceRecord(
            source_system="kw_command",
            module="tasks",
            record_kind="task",
            source_key="task-1",
            evidence_level="rendered_occurrence",
            display_label="Call Alice",
            payload_json='{"status":"to_do"}',
            capture_quality="partial",
            captured_at=datetime(2026, 7, 27, 20, 2, tzinfo=UTC),
            parser_version="command-v1",
        ),
        CRMSourceRecord(
            source_system="docusign",
            module="agreements",
            record_kind="envelope",
            source_key="envelope-1",
            evidence_level="displayed_aggregate",
            display_label="Completed agreements",
            payload_json='{"count":68}',
            capture_quality="complete",
            captured_at=datetime(2026, 7, 27, 20, 3, tzinfo=UTC),
            parser_version="command-v1",
        ),
    ]
    provenance_db.add_all(records)
    await provenance_db.flush()

    alice = records[1]
    provenance_db.add_all(
        [
            CRMSourceRecordArtifact(
                source_record_id=alice.id,
                artifact_id=artifact.id,
                relation="evidence",
            ),
            CRMEntitySource(
                entity_type="contact",
                entity_id=12,
                source_record_id=alice.id,
            ),
        ]
    )

    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    older_run = CRMReconciliationRun(
        bundle_fingerprint="a" * 64,
        parser_version="command-v1",
        mode="verify_only",
        status="completed",
        requested_modules_json='["archive_integrity"]',
        error_text="",
        started_at=now - timedelta(days=1),
        completed_at=now - timedelta(days=1, minutes=-2),
    )
    newer_run = CRMReconciliationRun(
        bundle_fingerprint="b" * 64,
        parser_version="command-v1",
        mode="dry_run",
        status="completed",
        requested_modules_json='["contacts","tasks"]',
        error_text="",
        started_at=now,
        completed_at=now + timedelta(minutes=3),
    )
    provenance_db.add_all([older_run, newer_run])
    await provenance_db.flush()
    provenance_db.add(
        CRMReconciliationResult(
            run_id=newer_run.id,
            source_system="kw_command",
            module="contacts",
            expected_count=317,
            observed_count=313,
            rendered_count=317,
            normalized_count=313,
            evidence_only_count=4,
            unmatched_count=0,
            duplicate_content_count=4,
            error_count=0,
            details_json='{"coverage":"captured positions"}',
        )
    )
    await provenance_db.commit()

    return {
        "artifact_id": artifact.id,
        "alice_record_id": alice.id,
        "older_run_id": older_run.id,
        "newer_run_id": newer_run.id,
    }


@pytest.fixture
async def authenticated_client(provenance_db):
    async def override_db():
        yield provenance_db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: {"sub": "test-admin"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": "Bearer test-admin-token"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def unauthenticated_client(provenance_db):
    async def override_db():
        yield provenance_db

    app.dependency_overrides[get_db] = override_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/command/source-records",
        "/api/v1/command/source-records/1",
        "/api/v1/command/entities/contact/12/sources",
        "/api/v1/command/reconciliation/runs",
        "/api/v1/command/reconciliation/runs/latest",
        "/api/v1/command/reconciliation/runs/1",
    ],
)
async def test_all_provenance_routes_require_admin(unauthenticated_client, path):
    response = await unauthenticated_client.get(path)

    assert response.status_code == 401


async def test_provenance_routes_reject_an_invalid_bearer_token(provenance_db):
    async def override_db():
        yield provenance_db

    app.dependency_overrides[get_db] = override_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": "Bearer not-a-valid-admin-token"},
    ) as client:
        response = await client.get("/api/v1/command/source-records")
    app.dependency_overrides.clear()

    assert response.status_code == 401


async def test_source_records_page_filters_reports_total_and_has_stable_order(
    authenticated_client,
    seeded_provenance,
):
    response = await authenticated_client.get(
        "/api/v1/command/source-records",
        params={
            "source_system": "kw_command",
            "module": "contacts",
            "record_kind": "contact",
            "evidence_level": "observed_record",
            "capture_quality": "complete",
            "page": 1,
            "page_size": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["page"] == 1
    assert response.json()["page_size"] == 1
    assert response.json()["total"] == 2
    assert [row["source_key"] for row in response.json()["rows"]] == ["contact-a"]

    second_page = await authenticated_client.get(
        "/api/v1/command/source-records",
        params={
            "source_system": "kw_command",
            "module": "contacts",
            "page": 2,
            "page_size": 1,
        },
    )
    assert [row["source_key"] for row in second_page.json()["rows"]] == [
        "contact-z"
    ]

    queried = await authenticated_client.get(
        "/api/v1/command/source-records",
        params={"query": "ALICE@EXAMPLE.COM"},
    )
    assert queried.status_code == 200
    assert queried.json()["total"] == 1
    assert queried.json()["rows"][0]["display_label"] == "Alice Adams"


@pytest.mark.parametrize(
    ("params", "expected_status"),
    [
        ({"page": 0}, 422),
        ({"page_size": 0}, 422),
        ({"page_size": 201}, 422),
        ({"evidence_level": "fabricated"}, 422),
        ({"capture_quality": "unknown"}, 422),
        ({"source_system": "x" * 65}, 422),
        ({"query": "x" * 501}, 422),
    ],
)
async def test_source_record_filters_and_pagination_are_bounded(
    authenticated_client,
    params,
    expected_status,
):
    response = await authenticated_client.get(
        "/api/v1/command/source-records",
        params=params,
    )

    assert response.status_code == expected_status


async def test_source_record_detail_contains_typed_payload_and_safe_artifact_metadata(
    authenticated_client,
    seeded_provenance,
):
    record_id = seeded_provenance["alice_record_id"]
    response = await authenticated_client.get(
        f"/api/v1/command/source-records/{record_id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["payload"] == {
        "email": "alice@example.com",
        "tags": ["buyer"],
    }
    assert payload["artifacts"] == [
        {
            "id": seeded_provenance["artifact_id"],
            "domain": "kw_command",
            "artifact_type": "json",
            "filename": "alice.json",
            "source_path": "kw_command_repaired/contacts/alice.json",
            "sha256": hashlib.sha256(
                b"private recovered contact contents"
            ).hexdigest(),
            "size_bytes": len(b"private recovered contact contents"),
            "text_preview": "Alice Adams",
            "relation": "evidence",
        }
    ]
    assert "content_bytes" not in payload["artifacts"][0]

    missing = await authenticated_client.get(
        "/api/v1/command/source-records/999999"
    )
    assert missing.status_code == 404


async def test_entity_sources_are_typed_safe_and_reject_unknown_entity_types(
    authenticated_client,
    seeded_provenance,
):
    response = await authenticated_client.get(
        "/api/v1/command/entities/contact/12/sources"
    )

    assert response.status_code == 200
    assert response.json()["entity_type"] == "contact"
    assert response.json()["entity_id"] == 12
    assert [source["source_key"] for source in response.json()["sources"]] == [
        "contact-a"
    ]
    assert "content_bytes" not in response.json()["sources"][0]["artifacts"][0]

    unsupported = await authenticated_client.get(
        "/api/v1/command/entities/not_a_real_entity/12/sources"
    )
    assert unsupported.status_code == 422

    invalid_id = await authenticated_client.get(
        "/api/v1/command/entities/contact/0/sources"
    )
    assert invalid_id.status_code == 422


async def test_reconciliation_runs_are_newest_first_paginated_and_typed(
    authenticated_client,
    seeded_provenance,
):
    response = await authenticated_client.get(
        "/api/v1/command/reconciliation/runs",
        params={"page": 1, "page_size": 1},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["page"] == 1
    assert response.json()["page_size"] == 1
    assert [row["id"] for row in response.json()["rows"]] == [
        seeded_provenance["newer_run_id"]
    ]
    assert response.json()["rows"][0]["requested_modules"] == [
        "contacts",
        "tasks",
    ]

    latest = await authenticated_client.get(
        "/api/v1/command/reconciliation/runs/latest"
    )
    assert latest.status_code == 200
    assert latest.json()["id"] == seeded_provenance["newer_run_id"]
    assert latest.json()["results"][0]["details"] == {
        "coverage": "captured positions"
    }
    assert latest.json()["results"][0]["expected_count"] == 317

    older = await authenticated_client.get(
        f"/api/v1/command/reconciliation/runs/{seeded_provenance['older_run_id']}"
    )
    assert older.status_code == 200
    assert older.json()["results"] == []


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 201}])
async def test_reconciliation_run_pagination_is_bounded(
    authenticated_client,
    params,
):
    response = await authenticated_client.get(
        "/api/v1/command/reconciliation/runs",
        params=params,
    )

    assert response.status_code == 422


async def test_missing_reconciliation_runs_return_404(
    authenticated_client,
    seeded_provenance,
):
    response = await authenticated_client.get(
        "/api/v1/command/reconciliation/runs/999999"
    )

    assert response.status_code == 404


async def test_latest_reconciliation_returns_404_when_no_runs_exist(
    authenticated_client,
):
    response = await authenticated_client.get(
        "/api/v1/command/reconciliation/runs/latest"
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/command/source-records",
        "/api/v1/command/reconciliation/runs",
    ],
)
async def test_provenance_collections_are_get_only(
    authenticated_client,
    path,
):
    response = await authenticated_client.post(path, json={})

    assert response.status_code == 405
