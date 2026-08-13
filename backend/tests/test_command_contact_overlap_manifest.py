"""Privacy-safe private manifest validation and staging tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.command_contact_overlap_manifest import (
    ContactOverlapManifestError,
    load_contact_overlap_manifest,
)


def _payload() -> dict[str, object]:
    return {
        "schema_version": "command-contact-overlaps-v1",
        "bundle_fingerprint": "a" * 64,
        "parser_version": "contacts-v1",
        "rows": [
            {
                "source_provider_identity_hash": "b" * 64,
                "target_contact_id": 11,
                "target_contact_row_fingerprint": "c" * 64,
                "strong_evidence_hash": "d" * 64,
            },
            {
                "source_provider_identity_hash": "e" * 64,
                "target_contact_id": 12,
                "target_contact_row_fingerprint": "f" * 64,
                "strong_evidence_hash": "0" * 64,
            },
        ],
    }


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_manifest_loader_is_order_independent_and_returns_only_redacted_metadata(
    tmp_path: Path,
):
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first = _payload()
    second = _payload()
    second["rows"] = list(reversed(second["rows"]))
    _write_manifest(first_path, first)
    _write_manifest(second_path, second)

    first_manifest = load_contact_overlap_manifest(first_path)
    second_manifest = load_contact_overlap_manifest(second_path)

    assert first_manifest.rows == second_manifest.rows
    assert first_manifest.canonical_digest == second_manifest.canonical_digest
    assert first_manifest.redacted_metadata == {
        "schema_version": "command-contact-overlaps-v1",
        "canonical_digest": first_manifest.canonical_digest,
        "row_count": 2,
        "validation_state": "loaded",
    }
    assert not hasattr(first_manifest, "path")


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.update(schema_version="wrong"),
        lambda payload: payload.update(parser_version="contacts-v2"),
        lambda payload: payload.update(extra="forbidden"),
        lambda payload: payload.update(rows=payload["rows"][:1]),
        lambda payload: payload["rows"][0].update(target_contact_id=0),
        lambda payload: payload["rows"][0].update(email="private@example.test"),
        lambda payload: payload["rows"][1].update(
            source_provider_identity_hash="b" * 64
        ),
        lambda payload: payload["rows"][1].update(target_contact_id=11),
    ),
)
def test_manifest_loader_rejects_schema_drift_without_echoing_private_input(
    tmp_path: Path,
    mutation,
):
    path = tmp_path / "private-selector-do-not-echo.json"
    payload = _payload()
    mutation(payload)
    _write_manifest(path, payload)

    with pytest.raises(ContactOverlapManifestError) as captured:
        load_contact_overlap_manifest(path)

    rendered = f"{captured.value!r} {captured.value} {captured.value.args}"
    assert str(path) not in rendered
    assert "private@example.test" not in rendered
    assert "b" * 64 not in rendered
    assert "target_contact_id=11" not in rendered


def test_manifest_loader_rejects_symlink_and_repository_local_file(tmp_path: Path):
    external = tmp_path / "external.json"
    link = tmp_path / "linked.json"
    _write_manifest(external, _payload())
    link.symlink_to(external)

    with pytest.raises(ContactOverlapManifestError):
        load_contact_overlap_manifest(link)
    with pytest.raises(ContactOverlapManifestError):
        load_contact_overlap_manifest(external, repository_root=tmp_path)


def test_manifest_loader_error_does_not_retain_the_private_path(tmp_path: Path):
    path = tmp_path / "private-selector-that-must-not-survive.json"

    with pytest.raises(ContactOverlapManifestError) as captured:
        load_contact_overlap_manifest(path)

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert str(path) not in repr(captured.value.args)
