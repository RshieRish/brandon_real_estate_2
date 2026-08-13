"""Transactional repair gates for recovered Command contacts."""

from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base
from models.command import CRMArchiveArtifact, CRMContact, CRMNote, CRMSavedSearch
from models.command_contacts import (
    CONTACT_SECTIONS,
    CRMContactAddress,
    CRMContactAuditEvent,
    CRMContactCapturePosition,
    CRMContactMethod,
    CRMContactNeighborhood,
    CRMContactOwnership,
    CRMContactPreference,
    CRMContactProfile,
    CRMContactRelationship,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
    CRMContactTimelineEvent,
)
from models.command_provenance import (
    CaptureQuality,
    CRMEntitySource,
    CRMReconciliationResult,
    CRMReconciliationRun,
    CRMSourceRecord,
    CRMSourceRecordArtifact,
    EvidenceLevel,
)
from models.lead import Lead
from services.command_contact_identity import (
    ContactIdentityCandidate,
    resolve_identity_clusters,
)
from services.command_contact_overlap_manifest import (
    ContactOverlapManifest,
    ContactOverlapManifestRow,
    strong_email_evidence_hash,
    target_contact_row_fingerprint,
)
from services.command_materializers import (
    ContactMaterializer,
    DuplicateMaterializerError,
    MaterializerRegistry,
    ModuleMaterializationResult,
    UnknownMaterializerModuleError,
)
from services.command_parsers import ModuleMetrics, ModuleParseResult, ParserRegistry
from services.command_provenance import ArchiveArtifactInput, SourceRecordDraft
from services.command_reconciliation import RunRequest, execute_reconciliation

ARTIFACT_PATH = "synthetic/contacts/source.json"
CAPTURED_AT = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
CONTACT_TABLES = (
    Lead.__table__,
    CRMContact.__table__,
    CRMNote.__table__,
    CRMSavedSearch.__table__,
    CRMArchiveArtifact.__table__,
    CRMSourceRecord.__table__,
    CRMSourceRecordArtifact.__table__,
    CRMEntitySource.__table__,
    CRMReconciliationRun.__table__,
    CRMReconciliationResult.__table__,
    CRMContactProfile.__table__,
    CRMContactMethod.__table__,
    CRMContactAddress.__table__,
    CRMContactNeighborhood.__table__,
    CRMContactOwnership.__table__,
    CRMContactRelationship.__table__,
    CRMContactPreference.__table__,
    CRMContactCapturePosition.__table__,
    CRMContactSectionCapture.__table__,
    CRMContactSourceOccurrence.__table__,
    CRMContactTimelineEvent.__table__,
    CRMContactAuditEvent.__table__,
)


class _Parser:
    module = "contacts"

    def __init__(self, result: ModuleParseResult) -> None:
        self.result = result

    def parse(self, artifacts, parser_version):
        return self.result


class _Materializer:
    def __init__(self, module: str) -> None:
        self.module = module

    async def materialize(self, db, records, *, bundle_fingerprint):
        return ModuleMaterializationResult(
            module=self.module,
            normalized_count=0,
            created_count=0,
            updated_count=0,
            unchanged_count=0,
            links_created=0,
            details={},
        )


class _FailingContactMaterializer:
    module = "contacts"

    async def materialize(self, db, records, *, bundle_fingerprint):
        raise RuntimeError(
            "synthetic failure private-selector@example.test after reviewed-link staging"
        )


class _ForgedCompleteContactMaterializer:
    module = "contacts"

    async def materialize(self, db, records, *, bundle_fingerprint):
        return ModuleMaterializationResult(
            module="contacts",
            normalized_count=317,
            created_count=4,
            updated_count=311,
            unchanged_count=2,
            links_created=315,
            details={
                "source_entity_links_final": 317,
                "total_contacts": 366,
                "legacy_only_contacts": 49,
            },
        )


@pytest.fixture()
async def contact_db(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'contacts.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=CONTACT_TABLES,
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _artifact() -> ArchiveArtifactInput:
    content = b"synthetic contact evidence"
    return ArchiveArtifactInput(
        id=1,
        source_path=ARTIFACT_PATH,
        domain="kw_command",
        artifact_type="json",
        filename="source.json",
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        content_bytes=content,
    )


def _source_id(index: int) -> str:
    return f"{index:024x}"


def _email(index: int) -> str:
    return f"recovered-{index:04d}@example.test"


def _identity_hashes(count: int) -> dict[str, str]:
    clusters = resolve_identity_clusters(
        tuple(
            ContactIdentityCandidate(
                source_contact_id=_source_id(index),
                primary_email=_email(index),
                e164_phone=None,
                legal_name=f"Recovered Person {index}",
                preferred_name=None,
            )
            for index in range(1, count + 1)
        )
    )
    return {
        cluster.source_contact_ids[0]: cluster.identity_hash for cluster in clusters
    }


def _drafts(count: int) -> tuple[SourceRecordDraft, ...]:
    records: list[SourceRecordDraft] = []
    for index in range(1, count + 1):
        source_id = _source_id(index)
        ordinal = f"{index:07d}"
        records.append(
            SourceRecordDraft(
                source_system="kw_command",
                module="contacts",
                record_kind="contact_profile",
                source_key=f"contact:{source_id}",
                evidence_level=EvidenceLevel.OBSERVED_RECORD,
                display_label=f"Recovered Person {index}",
                payload={
                    "source_contact_id": source_id,
                    "capture_ordinal": ordinal,
                    "display_name": f"Recovered Person {index}",
                    "legal_name": f"Recovered Person {index}",
                    "preferred_name": None,
                    "primary_email": _email(index),
                    "primary_phone": None,
                    "birthday": {
                        "month": None,
                        "day": None,
                        "year": None,
                        "year_quality": "unknown",
                        "raw": None,
                    },
                    "anniversary": {
                        "month": None,
                        "day": None,
                        "year": None,
                        "year_quality": "unknown",
                        "raw": None,
                    },
                    "identity_candidate": {
                        "source_contact_id": source_id,
                        "primary_email": _email(index),
                        "e164_phone": None,
                        "legal_name": f"Recovered Person {index}",
                        "preferred_name": None,
                    },
                    "raw_fields": {"structured": None},
                },
                artifact_paths=(ARTIFACT_PATH,),
                parser_version="contacts-v1",
                capture_quality=CaptureQuality.COMPLETE,
                captured_at=CAPTURED_AT,
            )
        )
        records.append(
            SourceRecordDraft(
                source_system="kw_command",
                module="contacts",
                record_kind="contact_capture_position",
                source_key=f"position:{ordinal}",
                evidence_level=EvidenceLevel.RENDERED_OCCURRENCE,
                display_label=f"position {ordinal}",
                payload={
                    "capture_ordinal": ordinal,
                    "source_contact_id": source_id,
                    "section_names": CONTACT_SECTIONS,
                },
                artifact_paths=(ARTIFACT_PATH,),
                parser_version="contacts-v1",
                capture_quality=CaptureQuality.COMPLETE,
                captured_at=CAPTURED_AT,
            )
        )
        for section in CONTACT_SECTIONS:
            records.append(
                SourceRecordDraft(
                    source_system="kw_command",
                    module="contacts",
                    record_kind="contact_section_capture",
                    source_key=f"position:{ordinal}:section:{section}",
                    evidence_level=EvidenceLevel.RENDERED_OCCURRENCE,
                    display_label=f"{ordinal} {section}",
                    payload={
                        "capture_ordinal": ordinal,
                        "source_contact_id": source_id,
                        "section_name": section,
                        "is_empty": True,
                        "row_count": 0,
                        "limitations": (),
                    },
                    artifact_paths=(ARTIFACT_PATH,),
                    parser_version="contacts-v1",
                    capture_quality=CaptureQuality.COMPLETE,
                    captured_at=CAPTURED_AT,
                )
            )
    return tuple(records)


def _parse_result(records: tuple[SourceRecordDraft, ...], count: int):
    return ModuleParseResult(
        records=records,
        metrics=ModuleMetrics(
            source_system="kw_command",
            module="contacts",
            expected_count=count,
            observed_count=count,
            rendered_count=count,
            details={
                "provider_contact_rows": count,
                "capture_positions": count,
                "section_artifacts": count * 8,
                "section_counts": {section: count for section in CONTACT_SECTIONS},
                "identity_clusters": count,
                "identity_aliases_coalesced": 0,
                "ambiguous_identities": 0,
                "unmatched_provider_rows": 0,
                "fabricated_celebrations": 0,
            },
        ),
    )


async def _seed_artifact(db: AsyncSession) -> None:
    artifact = _artifact()
    db.add(
        CRMArchiveArtifact(
            id=artifact.id,
            source_path=artifact.source_path,
            domain=artifact.domain,
            artifact_type=artifact.artifact_type,
            filename=artifact.filename,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            text_preview="",
            content_bytes=artifact.content_bytes,
        )
    )
    await db.commit()


async def _seed_repair_boundary(
    db: AsyncSession,
    identity_hashes: dict[str, str],
) -> tuple[CRMContact, CRMContact]:
    db.add_all(
        Lead(id=index, name=f"Legacy Lead {index}") for index in range(1, 52)
    )
    for index in range(1, 312):
        contact = CRMContact(
            id=index,
            first_name="Preserved",
            last_name=f"Leadless {index}",
            email=_email(index),
            phone=None,
            stage="preserved",
        )
        db.add(contact)
        db.add(
            CRMContactProfile(
                id=index,
                contact_id=index,
                recovered_identity_hash=identity_hashes[_source_id(index)],
                legal_name=f"Recovered Person {index}",
                birth_year_quality="unknown",
                anniversary_year_quality="unknown",
            )
        )
    for index in (312, 313):
        db.add(
            CRMContact(
                id=index,
                lead_id=index - 311,
                first_name="Recovered",
                last_name=f"Person {index}",
                email=_email(index),
                phone=None,
                stage="preserved",
            )
        )
        db.add(
            CRMContactProfile(
                id=index,
                contact_id=index,
                recovered_identity_hash=identity_hashes[_source_id(index)],
                legal_name=f"Recovered Person {index}",
                birth_year_quality="unknown",
                anniversary_year_quality="unknown",
            )
        )
    for offset, contact_id in enumerate(range(314, 363), start=3):
        db.add(
            CRMContact(
                id=contact_id,
                lead_id=offset,
                first_name="Legacy",
                last_name=f"Only {offset}",
                email=f"legacy-{offset:02d}@example.test",
                phone=None,
                stage="preserved",
            )
        )
    await db.commit()
    first = await db.get(CRMContact, 312)
    second = await db.get(CRMContact, 313)
    assert first is not None and second is not None
    return first, second


def _manifest(
    *,
    fingerprint: str,
    identity_hashes: dict[str, str],
    targets: tuple[CRMContact, CRMContact],
) -> ContactOverlapManifest:
    return _manifest_for_indexes(
        fingerprint=fingerprint,
        identity_hashes=identity_hashes,
        targets=targets,
        source_indexes=(312, 313),
    )


def _manifest_for_indexes(
    *,
    fingerprint: str,
    identity_hashes: dict[str, str],
    targets: tuple[CRMContact, CRMContact],
    source_indexes: tuple[int, int],
) -> ContactOverlapManifest:
    rows = []
    for index, target in zip(source_indexes, targets, strict=True):
        source_hash = identity_hashes[_source_id(index)]
        target_fingerprint = target_contact_row_fingerprint(target)
        rows.append(
            ContactOverlapManifestRow(
                source_provider_identity_hash=source_hash,
                target_contact_id=target.id,
                target_contact_row_fingerprint=target_fingerprint,
                strong_evidence_hash=strong_email_evidence_hash(
                    source_hash,
                    _email(index),
                    target_fingerprint,
                ),
            )
        )
    return ContactOverlapManifest(
        schema_version="command-contact-overlaps-v1",
        bundle_fingerprint=fingerprint,
        parser_version="contacts-v1",
        rows=tuple(rows),
    )


def _base_snapshot(contact: CRMContact) -> tuple[object, ...]:
    return tuple(getattr(contact, column.name) for column in CRMContact.__table__.c)


def test_materializer_registry_is_deterministic_and_rejects_duplicate_modules():
    first = _Materializer("zeta")
    second = _Materializer("alpha")
    registry = MaterializerRegistry()
    registry.register(first)
    registry.register(second)

    assert registry.registered_modules() == frozenset({"alpha", "zeta"})
    assert registry.select(frozenset({"zeta", "alpha"})) == (second, first)
    with pytest.raises(DuplicateMaterializerError):
        registry.register(_Materializer("alpha"))
    with pytest.raises(UnknownMaterializerModuleError):
        registry.select(frozenset({"missing"}))

    result = ModuleMaterializationResult(
        module="contacts",
        normalized_count=1,
        created_count=1,
        updated_count=0,
        unchanged_count=0,
        links_created=1,
        details={"safe": [1, 2]},
    )
    assert result.details == {"safe": (1, 2)}
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.created_count = 2


def test_manifest_target_selection_refreshes_and_locks_postgresql_rows():
    from services.command_contact_overlap_manifest import _contact_targets_statement

    statement = _contact_targets_statement((11, 12), lock_for_update=True)
    rendered = str(statement.compile(dialect=postgresql.dialect()))

    assert statement.get_execution_options()["populate_existing"] is True
    assert "FOR UPDATE" in rendered


async def test_overlap_staging_revalidates_after_concurrent_target_change(
    tmp_path: Path,
):
    from services.command_contact_overlap_manifest import (
        ContactOverlapManifestError,
        stage_reviewed_contact_overlap_links,
        validate_contact_overlap_manifest,
    )
    from services.command_provenance import bundle_fingerprint, persist_source_records

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'overlap-concurrency.sqlite'}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=CONTACT_TABLES,
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as validator, factory() as concurrent:
            await _seed_artifact(validator)
            validator.add_all(
                Lead(id=index, name=f"Synthetic Lead {index}") for index in (1, 2)
            )
            targets = []
            for index in (1, 2):
                target = CRMContact(
                    id=index,
                    lead_id=index,
                    first_name="Recovered",
                    last_name=f"Person {index}",
                    email=_email(index),
                    stage="preserved",
                )
                validator.add(target)
                targets.append(target)
            await validator.commit()
            records = _drafts(2)
            artifact = _artifact()
            fingerprint = bundle_fingerprint((artifact,))
            manifest = _manifest_for_indexes(
                fingerprint=fingerprint,
                identity_hashes=_identity_hashes(2),
                targets=(targets[0], targets[1]),
                source_indexes=(1, 2),
            )

            await validate_contact_overlap_manifest(
                validator,
                manifest,
                records,
                bundle_fingerprint=fingerprint,
                parser_version="contacts-v1",
            )
            await validator.commit()

            await concurrent.execute(
                update(CRMContact)
                .where(CRMContact.id == targets[0].id)
                .values(updated_at=datetime(2026, 8, 13, 12, 0, tzinfo=UTC))
            )
            await concurrent.commit()

            validator.add(
                CRMReconciliationRun(
                    id=99,
                    bundle_fingerprint=fingerprint,
                    parser_version="contacts-v1",
                    mode="apply",
                    status="running",
                    requested_modules_json='["contacts"]',
                )
            )
            await validator.flush()
            await persist_source_records(validator, records)
            await validator.flush()
            with pytest.raises(ContactOverlapManifestError, match="target row changed"):
                await stage_reviewed_contact_overlap_links(
                    validator,
                    manifest,
                    records,
                    bundle_fingerprint=fingerprint,
                    parser_version="contacts-v1",
                    run_id=99,
                )
            await validator.rollback()

        async with factory() as verifier:
            assert (
                await verifier.scalar(select(func.count()).select_from(CRMSourceRecord))
                == 0
            )
            assert (
                await verifier.scalar(select(func.count()).select_from(CRMEntitySource))
                == 0
            )
            assert (
                await verifier.scalar(
                    select(func.count()).select_from(CRMContactAuditEvent)
                )
                == 0
            )
    finally:
        await engine.dispose()


async def test_full_repair_materializes_317_and_preserves_all_362_base_rows(
    contact_db: AsyncSession,
):
    records = _drafts(317)
    identity_hashes = _identity_hashes(317)
    await _seed_artifact(contact_db)
    targets = await _seed_repair_boundary(contact_db, identity_hashes)
    before_rows = (
        await contact_db.scalars(select(CRMContact).order_by(CRMContact.id))
    ).all()
    before = {contact.id: _base_snapshot(contact) for contact in before_rows}
    artifact = _artifact()
    fingerprint = hashlib.sha256(
        f"{artifact.source_path}\0{artifact.sha256}\0{artifact.size_bytes}\n".encode()
    ).hexdigest()
    manifest = _manifest(
        fingerprint=fingerprint,
        identity_hashes=identity_hashes,
        targets=targets,
    )
    parsers = ParserRegistry()
    parsers.register(_Parser(_parse_result(records, 317)))
    materializers = MaterializerRegistry()
    materializers.register(ContactMaterializer())
    request = RunRequest(
        mode="apply",
        parser_version="contacts-v1",
        modules=frozenset({"contacts"}),
    )

    dry = await execute_reconciliation(
        contact_db,
        parsers,
        (artifact,),
        RunRequest(
            mode="dry_run",
            parser_version="contacts-v1",
            modules=frozenset({"contacts"}),
        ),
        materializers=materializers,
        contact_overlap_manifest=manifest,
    )
    assert dry.results[0].details["contact_overlap_manifest"] == {
        "schema_version": "command-contact-overlaps-v1",
        "canonical_digest": manifest.canonical_digest,
        "row_count": 2,
        "validation_state": "validated",
    }
    assert await contact_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 0

    first = await execute_reconciliation(
        contact_db,
        parsers,
        (artifact,),
        request,
        materializers=materializers,
        contact_overlap_manifest=manifest,
    )

    assert first.status == "completed"
    result = first.results[0]
    assert result.normalized_count == 317
    assert result.details["recovered_contacts_created"] == 4
    assert result.details["preexisting_contact_rows"] == 362
    assert result.details["stale_source_normalized_rows"] == 313
    assert result.details["stale_source_normalized_leadless_rows"] == 311
    assert result.details["lead_backed_contacts"] == 51
    assert result.details["strong_verified_overlaps"] == 2
    assert result.details["legacy_only_contacts"] == 49
    assert result.details["legacy_lead_ids_preserved"] == 51
    assert result.details["reviewed_overlap_links_staged"] == 2
    assert result.details["source_entity_links_created_by_materializer"] == 315
    assert result.details["source_entity_links_final"] == 317
    assert result.details["expected_combined_contact_total"] == 366
    assert await contact_db.scalar(select(func.count()).select_from(CRMContact)) == 366
    assert (
        await contact_db.scalar(
            select(func.count())
            .select_from(CRMContact)
            .where(CRMContact.lead_id.is_not(None))
        )
        == 51
    )
    assert set(
        await contact_db.scalars(
            select(CRMContact.lead_id).where(CRMContact.lead_id.is_not(None))
        )
    ) == set(range(1, 52))
    assert (
        await contact_db.scalar(
            select(func.count()).select_from(CRMContactCapturePosition)
        )
        == 317
    )
    assert (
        await contact_db.scalar(
            select(func.count()).select_from(CRMContactSectionCapture)
        )
        == 2536
    )
    assert (
        await contact_db.scalar(
            select(func.count())
            .select_from(CRMEntitySource)
            .where(CRMEntitySource.entity_type == "contact")
        )
        == 317
    )
    after_rows = (
        await contact_db.scalars(
            select(CRMContact).where(CRMContact.id <= 362).order_by(CRMContact.id)
        )
    ).all()
    assert {contact.id: _base_snapshot(contact) for contact in after_rows} == before
    mapped_lead_backed = set(
        await contact_db.scalars(
            select(CRMEntitySource.entity_id)
            .join(CRMContact, CRMContact.id == CRMEntitySource.entity_id)
            .where(
                CRMEntitySource.entity_type == "contact",
                CRMContact.lead_id.is_not(None),
            )
        )
    )
    assert mapped_lead_backed == {312, 313}
    from scripts.reconcile_command_archive import summary_json

    rendered_summary = summary_json(first)
    assert _email(312) not in rendered_summary
    assert _source_id(312) not in rendered_summary

    second = await execute_reconciliation(
        contact_db,
        parsers,
        (artifact,),
        request,
        materializers=materializers,
        contact_overlap_manifest=manifest,
    )
    second_result = second.results[0]
    assert second_result.normalized_count == 317
    assert second_result.details["recovered_contacts_created"] == 0
    assert second_result.details["reviewed_overlap_links_staged"] == 0
    assert second_result.details["source_entity_links_created_by_materializer"] == 0
    assert second_result.details["source_entity_links_final"] == 317
    assert await contact_db.scalar(select(func.count()).select_from(CRMContact)) == 366
    assert (
        await contact_db.scalar(
            select(func.count()).select_from(CRMContactAuditEvent)
        )
        == 2
    )


async def test_fresh_materializer_creates_every_identity_without_legacy_adoption(
    contact_db: AsyncSession,
):
    from services.command_provenance import persist_source_records

    await _seed_artifact(contact_db)
    records = _drafts(2)
    await persist_source_records(contact_db, records)
    await contact_db.flush()

    result = await ContactMaterializer().materialize(
        contact_db,
        records,
        bundle_fingerprint="f" * 64,
    )

    assert result.normalized_count == 2
    assert result.created_count == 2
    assert result.links_created == 2
    assert await contact_db.scalar(select(func.count()).select_from(CRMContact)) == 2
    assert (
        await contact_db.scalar(
            select(func.count()).select_from(CRMContactCapturePosition)
        )
        == 2
    )
    assert (
        await contact_db.scalar(
            select(func.count()).select_from(CRMContactSectionCapture)
        )
        == 16
    )


async def test_contacts_apply_rejects_partial_parser_truth_before_source_writes(
    contact_db: AsyncSession,
):
    from services.command_reconciliation import ReconciliationRunError

    await _seed_artifact(contact_db)
    contact_db.add_all(
        Lead(id=index, name=f"Synthetic Lead {index}") for index in (1, 2)
    )
    targets = []
    for index in (1, 2):
        target = CRMContact(
            id=index,
            lead_id=index,
            first_name="Recovered",
            last_name=f"Person {index}",
            email=_email(index),
            stage="preserved",
        )
        contact_db.add(target)
        targets.append(target)
    await contact_db.commit()

    records = _drafts(2)
    artifact = _artifact()
    identity_hashes = _identity_hashes(2)
    manifest = _manifest_for_indexes(
        fingerprint=hashlib.sha256(
            f"{artifact.source_path}\0{artifact.sha256}\0{artifact.size_bytes}\n".encode()
        ).hexdigest(),
        identity_hashes=identity_hashes,
        targets=(targets[0], targets[1]),
        source_indexes=(1, 2),
    )
    parsers = ParserRegistry()
    parsers.register(_Parser(_parse_result(records, 2)))
    materializers = MaterializerRegistry()
    materializers.register(ContactMaterializer())

    with pytest.raises(ReconciliationRunError, match="eligibility"):
        await execute_reconciliation(
            contact_db,
            parsers,
            (artifact,),
            RunRequest(
                mode="apply",
                parser_version="contacts-v1",
                modules=frozenset({"contacts"}),
            ),
            materializers=materializers,
            contact_overlap_manifest=manifest,
        )

    assert await contact_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 0
    assert await contact_db.scalar(select(func.count()).select_from(CRMEntitySource)) == 0


async def test_contacts_apply_verifies_materialized_database_truth_before_commit(
    contact_db: AsyncSession,
):
    from services.command_reconciliation import ReconciliationRunError

    records = _drafts(317)
    identity_hashes = _identity_hashes(317)
    await _seed_artifact(contact_db)
    targets = await _seed_repair_boundary(contact_db, identity_hashes)
    artifact = _artifact()
    fingerprint = hashlib.sha256(
        f"{artifact.source_path}\0{artifact.sha256}\0{artifact.size_bytes}\n".encode()
    ).hexdigest()
    manifest = _manifest(
        fingerprint=fingerprint,
        identity_hashes=identity_hashes,
        targets=targets,
    )
    parsers = ParserRegistry()
    parsers.register(_Parser(_parse_result(records, 317)))
    materializers = MaterializerRegistry()
    materializers.register(_ForgedCompleteContactMaterializer())

    with pytest.raises(ReconciliationRunError, match="eligibility"):
        await execute_reconciliation(
            contact_db,
            parsers,
            (artifact,),
            RunRequest(
                mode="apply",
                parser_version="contacts-v1",
                modules=frozenset({"contacts"}),
            ),
            materializers=materializers,
            contact_overlap_manifest=manifest,
        )

    assert await contact_db.scalar(select(func.count()).select_from(CRMContact)) == 362
    assert await contact_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 0
    assert await contact_db.scalar(select(func.count()).select_from(CRMEntitySource)) == 0
    assert (
        await contact_db.scalar(
            select(func.count()).select_from(CRMContactCapturePosition)
        )
        == 0
    )
    assert (
        await contact_db.scalar(
            select(func.count()).select_from(CRMContactSectionCapture)
        )
        == 0
    )


async def test_failed_apply_rolls_back_the_whole_module_and_resume_requires_same_manifest(
    contact_db: AsyncSession,
):
    from services.command_reconciliation import (
        ContactApplyExpectedCounts,
        ReconciliationResumeError,
        ReconciliationRunError,
    )

    await _seed_artifact(contact_db)
    contact_db.add_all(
        Lead(id=index, name=f"Synthetic Lead {index}") for index in range(1, 5)
    )
    targets = []
    for contact_id, source_index in ((1, 1), (2, 2), (3, 1), (4, 2)):
        contact = CRMContact(
            id=contact_id,
            lead_id=contact_id,
            first_name="Recovered",
            last_name=f"Person {source_index}",
            email=_email(source_index),
            stage="preserved",
        )
        contact_db.add(contact)
        targets.append(contact)
    await contact_db.commit()
    records = _drafts(2)
    artifact = _artifact()
    fingerprint = hashlib.sha256(
        f"{artifact.source_path}\0{artifact.sha256}\0{artifact.size_bytes}\n".encode()
    ).hexdigest()
    hashes = _identity_hashes(2)

    def manifest_for(selected_targets) -> ContactOverlapManifest:
        rows = []
        for source_index, target in zip((1, 2), selected_targets, strict=True):
            source_hash = hashes[_source_id(source_index)]
            target_fingerprint = target_contact_row_fingerprint(target)
            rows.append(
                ContactOverlapManifestRow(
                    source_provider_identity_hash=source_hash,
                    target_contact_id=target.id,
                    target_contact_row_fingerprint=target_fingerprint,
                    strong_evidence_hash=strong_email_evidence_hash(
                        source_hash,
                        _email(source_index),
                        target_fingerprint,
                    ),
                )
            )
        return ContactOverlapManifest(
            schema_version="command-contact-overlaps-v1",
            bundle_fingerprint=fingerprint,
            parser_version="contacts-v1",
            rows=tuple(rows),
        )

    approved = manifest_for(targets[:2])
    changed_but_valid = manifest_for(targets[2:])
    parsers = ParserRegistry()
    parsers.register(_Parser(_parse_result(records, 2)))
    failing_materializers = MaterializerRegistry()
    failing_materializers.register(_FailingContactMaterializer())
    request = RunRequest(
        mode="apply",
        parser_version="contacts-v1",
        modules=frozenset({"contacts"}),
    )
    synthetic_counts = ContactApplyExpectedCounts.synthetic_for_tests(
        contacts=2,
        final_contacts=4,
        lead_backed_contacts=4,
        legacy_only_contacts=2,
    )

    with pytest.raises(ReconciliationRunError) as captured:
        await execute_reconciliation(
            contact_db,
            parsers,
            (artifact,),
            request,
            materializers=failing_materializers,
            contact_overlap_manifest=approved,
            contact_expected_counts=synthetic_counts,
        )
    assert "private-selector@example.test" not in str(captured.value)

    failed_run = await contact_db.scalar(select(CRMReconciliationRun))
    assert failed_run is not None and failed_run.status == "failed"
    assert await contact_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 0
    assert await contact_db.scalar(select(func.count()).select_from(CRMEntitySource)) == 0
    assert (
        await contact_db.scalar(
            select(func.count()).select_from(CRMContactAuditEvent)
        )
        == 0
    )
    assert (
        await contact_db.scalar(
            select(func.count()).select_from(CRMReconciliationResult)
        )
        == 0
    )
    assert _email(1) not in failed_run.error_text
    assert _source_id(1) not in failed_run.error_text

    succeeding = MaterializerRegistry()
    succeeding.register(ContactMaterializer())
    with pytest.raises(ReconciliationResumeError, match="manifest"):
        await execute_reconciliation(
            contact_db,
            parsers,
            (artifact,),
            RunRequest(
                mode="apply",
                parser_version="contacts-v1",
                modules=frozenset({"contacts"}),
                resume_run_id=failed_run.id,
            ),
            materializers=succeeding,
            contact_overlap_manifest=changed_but_valid,
            contact_expected_counts=synthetic_counts,
        )

    resumed = await execute_reconciliation(
        contact_db,
        parsers,
        (artifact,),
        RunRequest(
            mode="apply",
            parser_version="contacts-v1",
            modules=frozenset({"contacts"}),
            resume_run_id=failed_run.id,
        ),
        materializers=succeeding,
        contact_overlap_manifest=approved,
        contact_expected_counts=synthetic_counts,
    )
    assert resumed.run_id == failed_run.id
    assert resumed.status == "completed"
    assert resumed.results[0].normalized_count == 2
    assert await contact_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 20
    assert (
        await contact_db.scalar(
            select(func.count())
            .select_from(CRMEntitySource)
            .where(CRMEntitySource.entity_type == "contact")
        )
        == 2
    )


async def test_materializer_rejects_unreviewed_lead_backed_adoption(
    contact_db: AsyncSession,
):
    from services.command_contact_materializer import ContactMaterializationError
    from services.command_provenance import persist_source_records

    await _seed_artifact(contact_db)
    records = _drafts(1)
    identity_hash = _identity_hashes(1)[_source_id(1)]
    contact_db.add(Lead(id=1, name="Synthetic Lead"))
    contact_db.add(
        CRMContact(
            id=1,
            lead_id=1,
            first_name="Recovered",
            last_name="Person 1",
            email=_email(1),
            stage="preserved",
        )
    )
    contact_db.add(
        CRMContactProfile(
            contact_id=1,
            recovered_identity_hash=identity_hash,
            birth_year_quality="unknown",
            anniversary_year_quality="unknown",
        )
    )
    await contact_db.commit()
    await persist_source_records(contact_db, records)

    with pytest.raises(ContactMaterializationError, match="reviewed") as captured:
        await ContactMaterializer().materialize(
            contact_db,
            records,
            bundle_fingerprint="f" * 64,
        )
    assert _email(1) not in str(captured.value)
    assert _source_id(1) not in str(captured.value)


async def test_materializer_rejects_missing_source_and_split_identity_mapping(
    contact_db: AsyncSession,
):
    from services.command_contact_materializer import ContactMaterializationError
    from services.command_provenance import persist_source_records

    await _seed_artifact(contact_db)
    with pytest.raises(ContactMaterializationError, match="source record"):
        await ContactMaterializer().materialize(
            contact_db,
            _drafts(1),
            bundle_fingerprint="f" * 64,
        )

    first = next(
        draft for draft in _drafts(1) if draft.record_kind == "contact_profile"
    )
    second_payload = {
        **dict(first.payload),
        "source_contact_id": _source_id(2),
        "capture_ordinal": "0000002",
        "identity_candidate": {
            "source_contact_id": _source_id(2),
            "primary_email": _email(1),
            "e164_phone": None,
            "legal_name": "Recovered Person 1",
            "preferred_name": None,
        },
    }
    second = SourceRecordDraft(
        source_system="kw_command",
        module="contacts",
        record_kind="contact_profile",
        source_key=f"contact:{_source_id(2)}",
        evidence_level=EvidenceLevel.OBSERVED_RECORD,
        display_label="Recovered Person 1",
        payload=second_payload,
        artifact_paths=(ARTIFACT_PATH,),
        parser_version="contacts-v1",
        capture_quality=CaptureQuality.COMPLETE,
        captured_at=CAPTURED_AT,
    )
    records = (first, second)
    await persist_source_records(contact_db, records)
    contact_db.add_all(
        [
            CRMContact(
                id=1,
                first_name="First",
                last_name="Target",
                stage="preserved",
            ),
            CRMContact(
                id=2,
                first_name="Second",
                last_name="Target",
                stage="preserved",
            ),
        ]
    )
    await contact_db.flush()
    source_rows = (
        await contact_db.scalars(
            select(CRMSourceRecord).order_by(CRMSourceRecord.source_key)
        )
    ).all()
    contact_db.add_all(
        CRMEntitySource(
            entity_type="contact",
            entity_id=contact_id,
            source_record_id=source_row.id,
        )
        for contact_id, source_row in zip((1, 2), source_rows, strict=True)
    )
    await contact_db.flush()

    with pytest.raises(ContactMaterializationError, match="multiple contacts"):
        await ContactMaterializer().materialize(
            contact_db,
            records,
            bundle_fingerprint="f" * 64,
        )


async def test_materializer_adds_timeline_notes_and_saved_searches_once(
    contact_db: AsyncSession,
):
    from services.command_provenance import persist_source_records

    await _seed_artifact(contact_db)
    base_records = _drafts(1)

    def occurrence(
        *,
        record_kind: str,
        source_key: str,
        display_label: str,
        values: dict,
        section_name: str,
        occurrence_ordinal: int = 1,
        state: str | None = None,
    ) -> SourceRecordDraft:
        return SourceRecordDraft(
            source_system="kw_command",
            module="contacts",
            record_kind=record_kind,
            source_key=source_key,
            evidence_level=EvidenceLevel.RENDERED_OCCURRENCE,
            display_label=display_label,
            payload={
                "capture_ordinal": "0000001",
                "source_contact_id": _source_id(1),
                "section_name": section_name,
                "occurrence_ordinal": occurrence_ordinal,
                "state": state,
                "values": values,
            },
            artifact_paths=(ARTIFACT_PATH,),
            parser_version="contacts-v1",
            capture_quality=CaptureQuality.COMPLETE,
            captured_at=CAPTURED_AT,
        )

    records = (
        *base_records,
        occurrence(
            record_kind="contact_timeline_event",
            source_key=f"contact:{_source_id(1)}:timeline:event-1",
            display_label="Synthetic event",
            section_name="timeline",
            values={
                "kind": "EMAIL",
                "occurred_at": "2026-08-11T14:30:00Z",
                "raw_lines": ["EMAIL", "Synthetic event"],
            },
        ),
        occurrence(
            record_kind="contact_timeline_event",
            source_key=f"contact:{_source_id(1)}:timeline:event-2",
            display_label="Synthetic event without exposed time",
            section_name="timeline",
            occurrence_ordinal=2,
            values={
                "kind": "CONTACT",
                "raw_lines": ["CONTACT", "No exposed time"],
            },
        ),
        occurrence(
            record_kind="contact_note",
            source_key=f"contact:{_source_id(1)}:note:note-1",
            display_label="Synthetic note",
            section_name="notes",
            values={"body": "Synthetic note body"},
        ),
        occurrence(
            record_kind="contact_saved_search",
            source_key=f"contact:{_source_id(1)}:saved-search:search-1",
            display_label="Synthetic saved search",
            section_name="saved_searches",
            values={"name": "Synthetic saved search", "beds": "3"},
        ),
        occurrence(
            record_kind="contact_task",
            source_key=f"contact:{_source_id(1)}:task:to_do:task-1",
            display_label="Synthetic task",
            section_name="tasks_to_do",
            state="to_do",
            values={"title": "Synthetic task"},
        ),
        occurrence(
            record_kind="contact_smart_plan",
            source_key=f"contact:{_source_id(1)}:smart-plan:plan-1",
            display_label="Synthetic plan",
            section_name="smart_plans",
            values={"title": "Synthetic plan"},
        ),
        occurrence(
            record_kind="contact_opportunity",
            source_key=f"contact:{_source_id(1)}:opportunity:opportunity-1",
            display_label="Synthetic opportunity",
            section_name="opportunities",
            values={"title": "Synthetic opportunity"},
        ),
    )
    await persist_source_records(contact_db, records)
    historical = SourceRecordDraft(
        source_system="kw_command",
        module="contacts",
        record_kind="contact_note",
        source_key="contact:historical:note:outside-current-bundle",
        evidence_level=EvidenceLevel.RENDERED_OCCURRENCE,
        display_label="Historical row outside current materialization",
        payload={
            "source_contact_id": "f" * 24,
            "capture_ordinal": "9999999",
            "section_name": "notes",
            "occurrence_ordinal": 1,
            "values": {"body": "Historical"},
        },
        artifact_paths=(ARTIFACT_PATH,),
        parser_version="contacts-v1",
        capture_quality=CaptureQuality.COMPLETE,
        captured_at=CAPTURED_AT,
    )
    await persist_source_records(contact_db, (historical,))
    materializer = ContactMaterializer()

    first = await materializer.materialize(
        contact_db,
        records,
        bundle_fingerprint="f" * 64,
    )
    second = await materializer.materialize(
        contact_db,
        records,
        bundle_fingerprint="f" * 64,
    )

    assert first.details["child_entity_links_created"] == 4
    assert second.details["child_entity_links_created"] == 0
    assert first.details["child_occurrences_observed"] == 7
    assert first.details["child_occurrences_created"] == 7
    assert second.details["child_occurrences_unchanged"] == 7
    assert await contact_db.scalar(
        select(func.count()).select_from(CRMContactSourceOccurrence)
    ) == 7
    assert (
        await contact_db.scalar(
            select(func.count()).select_from(CRMContactTimelineEvent)
        )
        == 2
    )
    assert await contact_db.scalar(
        select(func.count())
        .select_from(CRMContactTimelineEvent)
        .where(CRMContactTimelineEvent.occurred_at.is_(None))
    ) == 1
    assert await contact_db.scalar(select(func.count()).select_from(CRMNote)) == 1
    assert (
        await contact_db.scalar(select(func.count()).select_from(CRMSavedSearch))
        == 1
    )
    assert (
        await contact_db.scalar(
            select(func.count())
            .select_from(CRMEntitySource)
            .where(
                CRMEntitySource.entity_type.in_(
                    {"contact_timeline_event", "note", "saved_search"}
                )
            )
        )
        == 4
    )
    contact = await contact_db.scalar(select(CRMContact))
    assert contact is not None
    assert contact.birthday is None
    assert contact.anniversary is None


@pytest.mark.parametrize(
    "corruption",
    ("wrong_type", "missing_target", "wrong_owner", "wrong_value"),
)
async def test_materializer_rejects_stale_or_conflicting_existing_child_link(
    contact_db: AsyncSession,
    corruption: str,
):
    from services.command_contact_materializer import ContactMaterializationError
    from services.command_provenance import persist_source_records

    await _seed_artifact(contact_db)
    note = SourceRecordDraft(
        source_system="kw_command",
        module="contacts",
        record_kind="contact_note",
        source_key=f"contact:{_source_id(1)}:note:note-1",
        evidence_level=EvidenceLevel.RENDERED_OCCURRENCE,
        display_label="Synthetic note",
        payload={
            "capture_ordinal": "0000001",
            "source_contact_id": _source_id(1),
            "section_name": "notes",
            "occurrence_ordinal": 1,
            "values": {"body": "Synthetic note body"},
        },
        artifact_paths=(ARTIFACT_PATH,),
        parser_version="contacts-v1",
        capture_quality=CaptureQuality.COMPLETE,
        captured_at=CAPTURED_AT,
    )
    records = (*_drafts(1), note)
    await persist_source_records(contact_db, records)
    materializer = ContactMaterializer()
    await materializer.materialize(
        contact_db,
        records,
        bundle_fingerprint="f" * 64,
    )
    await contact_db.flush()

    note_source = await contact_db.scalar(
        select(CRMSourceRecord).where(CRMSourceRecord.record_kind == "contact_note")
    )
    assert note_source is not None
    link = await contact_db.scalar(
        select(CRMEntitySource).where(
            CRMEntitySource.source_record_id == note_source.id,
            CRMEntitySource.entity_type == "note",
        )
    )
    assert link is not None
    linked_note = await contact_db.get(CRMNote, link.entity_id)
    assert linked_note is not None

    if corruption == "wrong_type":
        link.entity_type = "saved_search"
    elif corruption == "missing_target":
        link.entity_id = 999_999
    elif corruption == "wrong_owner":
        other = CRMContact(
            first_name="Other",
            last_name="Owner",
            stage="preserved",
        )
        contact_db.add(other)
        await contact_db.flush()
        other_note = CRMNote(contact_id=other.id, body="Synthetic note body")
        contact_db.add(other_note)
        await contact_db.flush()
        link.entity_id = other_note.id
    else:
        linked_note.body = "Changed after materialization"
    await contact_db.flush()

    with pytest.raises(ContactMaterializationError, match="child link"):
        await materializer.materialize(
            contact_db,
            records,
            bundle_fingerprint="f" * 64,
        )


async def test_materializer_rejects_timeline_link_with_wrong_source_record(
    contact_db: AsyncSession,
):
    from services.command_contact_materializer import ContactMaterializationError
    from services.command_provenance import persist_source_records

    await _seed_artifact(contact_db)
    timeline = SourceRecordDraft(
        source_system="kw_command",
        module="contacts",
        record_kind="contact_timeline_event",
        source_key=f"contact:{_source_id(1)}:timeline:event-1",
        evidence_level=EvidenceLevel.RENDERED_OCCURRENCE,
        display_label="Synthetic event",
        payload={
            "capture_ordinal": "0000001",
            "source_contact_id": _source_id(1),
            "section_name": "timeline",
            "occurrence_ordinal": 1,
            "values": {
                "kind": "EMAIL",
                "occurred_at": "2026-08-11T14:30:00Z",
                "raw_lines": ["EMAIL", "Synthetic event"],
            },
        },
        artifact_paths=(ARTIFACT_PATH,),
        parser_version="contacts-v1",
        capture_quality=CaptureQuality.COMPLETE,
        captured_at=CAPTURED_AT,
    )
    records = (*_drafts(1), timeline)
    await persist_source_records(contact_db, records)
    materializer = ContactMaterializer()
    await materializer.materialize(
        contact_db,
        records,
        bundle_fingerprint="f" * 64,
    )
    await contact_db.flush()

    event = await contact_db.scalar(select(CRMContactTimelineEvent))
    profile_source = await contact_db.scalar(
        select(CRMSourceRecord).where(CRMSourceRecord.record_kind == "contact_profile")
    )
    assert event is not None and profile_source is not None
    event.source_record_id = profile_source.id
    await contact_db.flush()

    with pytest.raises(ContactMaterializationError, match="child link"):
        await materializer.materialize(
            contact_db,
            records,
            bundle_fingerprint="f" * 64,
        )
