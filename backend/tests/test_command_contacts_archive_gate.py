"""Opt-in integrity and cardinality gate against the recovered contact archive."""

from __future__ import annotations

from collections import Counter
import hashlib
import os
from pathlib import Path

import pytest

from services.command_parsers.contact_extractors import CONTACT_SECTIONS
from services.command_parsers.contacts import ContactsParser
from services.command_provenance import ArchiveArtifactInput


def _archive_artifacts(root: Path) -> tuple[ArchiveArtifactInput, ...]:
    contacts_root = root / "kw_command_repaired" / "contacts"
    values = []
    for artifact_id, path in enumerate(
        sorted(item for item in contacts_root.rglob("*") if item.is_file()),
        start=1,
    ):
        content = path.read_bytes()
        values.append(
            ArchiveArtifactInput(
                id=artifact_id,
                source_path=path.relative_to(root).as_posix(),
                domain="kw_command",
                artifact_type=path.suffix.removeprefix(".") or "unknown",
                filename=path.name,
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                content_bytes=content,
            )
        )
    return tuple(values)


def test_recovered_contacts_have_complete_eight_view_matrix():
    configured_root = os.environ.get("COMMAND_ARCHIVE_ROOT")
    if not configured_root:
        pytest.skip("COMMAND_ARCHIVE_ROOT is not configured")

    result = ContactsParser().parse(
        _archive_artifacts(Path(configured_root)),
        "contacts-v1",
    )
    kinds = Counter(record.record_kind for record in result.records)
    assert kinds["contact_profile"] == 317
    assert kinds["contact_capture_position"] == 317
    assert kinds["contact_section_capture"] == 2_536
    assert result.metrics.observed_count == 317
    assert result.metrics.rendered_count == 317
    assert result.metrics.unmatched_count == 0
    assert result.metrics.details["section_artifacts"] == 2_536
    assert result.metrics.details["section_counts"] == {
        section: 317 for section in CONTACT_SECTIONS
    }
    assert result.metrics.details["fabricated_celebrations"] == 0
