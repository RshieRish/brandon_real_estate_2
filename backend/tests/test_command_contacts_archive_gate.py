"""Opt-in integrity and cardinality gate against the recovered contact archive."""

from __future__ import annotations

from collections import Counter
import hashlib
import os
from pathlib import Path

import pytest

from models.command_provenance import CaptureQuality
from services.command_contact_identity import canonical_email
from services.command_parsers.contact_extractors import CONTACT_SECTIONS
from services.command_parsers.contacts import ContactsParser
from services.command_provenance import ArchiveArtifactInput


async def _verified_archive_artifacts(
    root: Path,
) -> tuple[ArchiveArtifactInput, ...]:
    """Verify local bytes against the immutable database artifact inventory."""
    from sqlalchemy import select

    from database import AsyncSessionLocal
    from models.command import CRMArchiveArtifact

    async with AsyncSessionLocal() as db:
        inventory = (
            await db.execute(
                select(
                    CRMArchiveArtifact.id,
                    CRMArchiveArtifact.source_path,
                    CRMArchiveArtifact.domain,
                    CRMArchiveArtifact.artifact_type,
                    CRMArchiveArtifact.filename,
                    CRMArchiveArtifact.sha256,
                    CRMArchiveArtifact.size_bytes,
                ).order_by(CRMArchiveArtifact.source_path)
            )
        ).all()

    assert len(inventory) == 12_580
    assert sum(row.size_bytes for row in inventory) == 745_060_261
    assert Counter(row.domain for row in inventory) == {
        "kw_command": 12_411,
        "docusign": 169,
    }

    expected_paths = {row.source_path for row in inventory}
    actual_paths = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    missing = sorted(expected_paths - actual_paths)
    unexpected = sorted(actual_paths - expected_paths)
    assert not missing, f"archive inventory is missing paths: {missing[:5]}"
    assert not unexpected, f"archive inventory has unexpected paths: {unexpected[:5]}"

    contacts: list[ArchiveArtifactInput] = []
    contact_bytes = 0
    for row in inventory:
        path = root / row.source_path
        content = path.read_bytes()
        assert len(content) == row.size_bytes, f"size drift: {row.source_path}"
        assert (
            hashlib.sha256(content).hexdigest() == row.sha256
        ), f"checksum drift: {row.source_path}"
        if not row.source_path.startswith("kw_command_repaired/contacts/"):
            continue
        contact_bytes += row.size_bytes
        contacts.append(
            ArchiveArtifactInput(
                id=row.id,
                source_path=row.source_path,
                domain=row.domain,
                artifact_type=row.artifact_type,
                filename=row.filename,
                sha256=row.sha256,
                size_bytes=row.size_bytes,
                content_bytes=content,
            )
        )

    assert len(contacts) == 6_709
    assert contact_bytes == 190_917_228
    return tuple(contacts)


def _redacted_overlap_hash(email: str) -> str:
    canonical = f"contacts-v1\0verified-overlap\0{email}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _redacted_provider_hash(source_contact_id: str) -> str:
    canonical = f"contacts-v1\0provider-evidence\0{source_contact_id}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _lead_backed_emails() -> tuple[str, ...]:
    from sqlalchemy import select

    from database import AsyncSessionLocal
    from models.command import CRMContact

    async with AsyncSessionLocal() as db:
        values = (
            await db.execute(
                select(CRMContact.email).where(CRMContact.lead_id.is_not(None))
            )
        ).scalars().all()

    assert len(values) == 51
    return tuple(
        canonical
        for value in values
        if (canonical := canonical_email(value)) is not None
    )


async def test_recovered_contacts_have_complete_eight_view_matrix():
    configured_root = os.environ.get("COMMAND_ARCHIVE_ROOT")
    if not configured_root:
        pytest.skip("COMMAND_ARCHIVE_ROOT is not configured")

    artifacts = await _verified_archive_artifacts(Path(configured_root))
    result = ContactsParser().parse(artifacts, "contacts-v1")
    kinds = Counter(record.record_kind for record in result.records)
    assert kinds == {
        "contact_profile": 317,
        "contact_capture_position": 317,
        "contact_section_capture": 2_536,
        "contact_timeline_event": 6_557,
        "contact_opportunity": 127,
        "contact_smart_plan": 291,
        "contact_note": 178,
        "contact_saved_search": 5,
        "contact_task": 2_052,
    }
    task_states = Counter(
        record.payload["state"]
        for record in result.records
        if record.record_kind == "contact_task"
    )
    assert task_states == {"to_do": 1_463, "completed": 32, "archived": 557}
    position_three_completed = [
        record
        for record in result.records
        if record.record_kind == "contact_task"
        and record.payload["capture_ordinal"] == "0000003"
        and record.payload["state"] == "completed"
    ]
    assert [record.display_label for record in position_three_completed] == [
        "Birthday card for Aimee Levesque"
    ]
    assert result.metrics.observed_count == 317
    assert result.metrics.rendered_count == 317
    assert result.metrics.unmatched_count == 0
    assert result.metrics.details["identity_clusters"] == 317
    assert result.metrics.details["identity_aliases_coalesced"] == 0
    assert result.metrics.details["ambiguous_identities"] == 0
    assert result.metrics.details["unmatched_provider_rows"] == 0
    identity_hashes = result.metrics.details["identity_cluster_hashes"]
    membership_hashes = result.metrics.details["identity_cluster_membership_hashes"]
    assert len(identity_hashes) == 317
    assert len(set(identity_hashes)) == 317
    assert len(membership_hashes) == 317
    assert len(set(membership_hashes)) == 317
    assert (
        hashlib.sha256("\n".join(membership_hashes).encode("utf-8")).hexdigest()
        == "a42a7bc6efbf6133951b9534188c455d0728d2cc5a33adebb15b6d4a2c3de7de"
    )
    assert (
        hashlib.sha256("\n".join(identity_hashes).encode("utf-8")).hexdigest()
        == "3bb6bc7754da2bb17d58162ef0af72b602316230f9c3b2e3fac4c73341eb6474"
    )
    reversed_result = ContactsParser().parse(
        tuple(reversed(artifacts)),
        "contacts-v1",
    )
    assert reversed_result.metrics == result.metrics
    assert reversed_result.records == result.records
    profile_source_ids = {
        record.payload["source_contact_id"]
        for record in result.records
        if record.record_kind == "contact_profile"
    }
    position_source_ids = [
        record.payload["source_contact_id"]
        for record in result.records
        if record.record_kind == "contact_capture_position"
    ]
    assert len(profile_source_ids) == 317
    assert Counter(position_source_ids) == Counter(
        {source_contact_id: 1 for source_contact_id in profile_source_ids}
    )
    source_id_by_ordinal = {
        record.payload["capture_ordinal"]: record.payload["source_contact_id"]
        for record in result.records
        if record.record_kind == "contact_capture_position"
    }
    scoped_records = [
        record
        for record in result.records
        if "capture_ordinal" in record.payload
        and "source_contact_id" in record.payload
    ]
    assert len(scoped_records) == len(result.records)
    assert all(
        record.payload["source_contact_id"]
        == source_id_by_ordinal[record.payload["capture_ordinal"]]
        for record in scoped_records
    )

    profiles_by_ordinal = {
        record.payload["capture_ordinal"]: record
        for record in result.records
        if record.record_kind == "contact_profile"
    }
    placeholder_evidence = tuple(
        (
            ordinal,
            tuple(
                field_label
                for payload_key, field_label in (
                    ("primary_email", "email"),
                    ("primary_phone", "phone"),
                    ("legal_name", "legal_name"),
                    ("preferred_name", "preferred_name"),
                )
                if profiles_by_ordinal[ordinal].payload[payload_key]
            ),
        )
        for ordinal in ("0000102", "0000103", "0000104", "0000105", "0000106")
    )
    assert placeholder_evidence == (
        ("0000102", ("email",)),
        ("0000103", ()),
        ("0000104", ("legal_name",)),
        ("0000105", ("legal_name",)),
        ("0000106", ("email",)),
    )

    recovered_emails = {
        canonical
        for record in result.records
        if record.record_kind == "contact_profile"
        if (canonical := canonical_email(record.payload["primary_email"])) is not None
    }
    overlap_hashes = tuple(
        sorted(
            _redacted_overlap_hash(email)
            for email in recovered_emails.intersection(await _lead_backed_emails())
        )
    )
    assert overlap_hashes == (
        "77b6ade5b93b9781ebcd48d8e36068d8faf6f5d5b2f7a185f061a3d6a98ca1fe",
        "babca90f14f8f7fd69a09f80c5ca4ef586551e36562edb7bab6af0690ca7371d",
    )
    assert result.metrics.details["section_artifacts"] == 2_536
    assert result.metrics.details["section_counts"] == {
        section: 317 for section in CONTACT_SECTIONS
    }
    assert result.metrics.details["fabricated_celebrations"] == 0

    section_records = [
        record
        for record in result.records
        if record.record_kind == "contact_section_capture"
    ]
    assert Counter(record.capture_quality for record in section_records) == {
        CaptureQuality.COMPLETE: 2_535,
        CaptureQuality.PARTIAL: 1,
    }
    assert Counter(
        (
            record.payload["section_name"],
            record.payload["is_empty"],
            record.capture_quality,
        )
        for record in section_records
    ) == {
        ("timeline", False, CaptureQuality.COMPLETE): 317,
        ("opportunities", False, CaptureQuality.COMPLETE): 100,
        ("opportunities", True, CaptureQuality.COMPLETE): 217,
        ("smart_plans", False, CaptureQuality.COMPLETE): 197,
        ("smart_plans", False, CaptureQuality.PARTIAL): 1,
        ("smart_plans", True, CaptureQuality.COMPLETE): 119,
        ("notes", False, CaptureQuality.COMPLETE): 154,
        ("notes", True, CaptureQuality.COMPLETE): 163,
        ("saved_searches", False, CaptureQuality.COMPLETE): 3,
        ("saved_searches", True, CaptureQuality.COMPLETE): 314,
        ("tasks_to_do", False, CaptureQuality.COMPLETE): 190,
        ("tasks_to_do", True, CaptureQuality.COMPLETE): 127,
        ("tasks_completed", False, CaptureQuality.COMPLETE): 22,
        ("tasks_completed", True, CaptureQuality.COMPLETE): 295,
        ("tasks_archived", False, CaptureQuality.COMPLETE): 138,
        ("tasks_archived", True, CaptureQuality.COMPLETE): 179,
    }

    partial_sections = [
        record
        for record in section_records
        if record.capture_quality is not CaptureQuality.COMPLETE
    ]
    assert len(partial_sections) == 1
    partial = partial_sections[0]
    assert partial.source_key == "position:0000246:section:smart_plans"
    assert partial.payload["capture_ordinal"] == "0000246"
    assert (
        _redacted_provider_hash(partial.payload["source_contact_id"])
        == "654e2b1f539f8df01fcd6c24c2fdaacff5cc1651db633e95e632514c46448bb3"
    )
    assert partial.payload["section_name"] == "smart_plans"
    assert partial.payload["is_empty"] is False
    assert partial.payload["row_count"] == 0
    assert partial.payload["limitations"] == (
        "rendered rows were not structurally distinguishable",
    )
    assert partial.artifact_paths == (
        "kw_command_repaired/contacts/sections/0000246/smartplans.json",
        "kw_command_repaired/contacts/sections/0000246/smartplans.snapshot.txt",
    )
