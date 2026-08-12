from dataclasses import FrozenInstanceError, fields, replace
import hashlib
from types import MappingProxyType

import pytest

from models.command_provenance import CaptureQuality, EvidenceLevel
from services.command_provenance import (
    ArchiveArtifactInput,
    ArchiveIntegrityError,
    SourceDraftValidationError,
    SourceRecordDraft,
    bundle_fingerprint,
    verify_artifact_bytes,
)


def artifact_for(content: bytes = b"private archive bytes", **overrides):
    values = {
        "id": 1,
        "source_path": "kw_command_repaired/contacts/contact.json",
        "domain": "kw_command",
        "artifact_type": "json",
        "filename": "contact.json",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "content_bytes": content,
    }
    values.update(overrides)
    return ArchiveArtifactInput(**values)


def source_draft(**overrides):
    values = {
        "source_system": "kw_command",
        "module": "contacts",
        "record_kind": "contact",
        "source_key": "63ac84e09655a08ec4d5d3ef",
        "evidence_level": EvidenceLevel.OBSERVED_RECORD,
        "display_label": "José Rivera",
        "payload": {"name": "José Rivera"},
        "artifact_paths": (
            "kw_command_repaired/contacts/sections/0000001/timeline.json",
        ),
        "parser_version": "command-v1",
    }
    values.update(overrides)
    return SourceRecordDraft(**values)


def test_provenance_inputs_are_frozen_slotted_value_objects():
    artifact = artifact_for()
    draft = source_draft()

    with pytest.raises(FrozenInstanceError):
        artifact.filename = "changed.json"
    with pytest.raises(FrozenInstanceError):
        draft.module = "changed"

    assert not hasattr(artifact, "__dict__")
    assert not hasattr(draft, "__dict__")


def test_source_draft_uses_exact_five_part_identity():
    draft = source_draft()

    assert draft.identity == (
        "kw_command",
        "contacts",
        "contact",
        "63ac84e09655a08ec4d5d3ef",
        "command-v1",
    )


def test_source_draft_serializes_nested_payload_as_canonical_unicode_json():
    draft = source_draft(
        payload={
            "zeta": None,
            "name": "José Rivera",
            "nested": {"β": 2, "alpha": [None, {"ñ": "sí", "a": 1}]},
        }
    )

    assert draft.payload_json == (
        '{"name":"José Rivera","nested":{"alpha":[null,{"a":1,"ñ":"sí"}],'
        '"β":2},"zeta":null}'
    )


def test_source_draft_has_exactly_the_public_contract_fields():
    assert tuple(item.name for item in fields(SourceRecordDraft)) == (
        "source_system",
        "module",
        "record_kind",
        "source_key",
        "evidence_level",
        "display_label",
        "payload",
        "artifact_paths",
        "parser_version",
        "capture_quality",
        "captured_at",
    )


def test_source_draft_deep_snapshots_payload_during_construction():
    original_payload = {
        "contact": {"name": "José Rivera"},
        "tags": ["buyer"],
    }
    draft = source_draft(payload=original_payload)

    original_payload["contact"]["name"] = "Changed"
    original_payload["tags"].append("seller")
    original_payload["added_later"] = True

    assert draft.payload_json == (
        '{"contact":{"name":"José Rivera"},"tags":["buyer"]}'
    )
    assert draft.payload == {
        "contact": {"name": "José Rivera"},
        "tags": ("buyer",),
    }


def test_source_draft_accepts_and_freezes_nested_mapping_values():
    original_payload = MappingProxyType(
        {
            "contact": MappingProxyType({"name": "José Rivera"}),
            "tags": ["buyer"],
        }
    )
    draft = source_draft(payload=original_payload)

    assert draft.payload_json == (
        '{"contact":{"name":"José Rivera"},"tags":["buyer"]}'
    )


def test_source_draft_payload_rejects_top_level_mutation():
    draft = source_draft(payload={"name": "José Rivera"})

    with pytest.raises(TypeError):
        draft.payload["name"] = "Changed"


def test_source_draft_payload_uses_true_immutable_mapping_proxies():
    draft = source_draft(
        payload={"contact": {"name": "José Rivera"}, "tags": ["buyer"]}
    )

    assert isinstance(draft.payload, MappingProxyType)
    assert isinstance(draft.payload["contact"], MappingProxyType)
    assert not isinstance(draft.payload, dict)
    assert not isinstance(draft.payload["contact"], dict)


def test_source_draft_payload_cannot_be_mutated_through_dict_base_class():
    draft = source_draft(payload={"contact": {"name": "José Rivera"}})

    with pytest.raises(TypeError):
        dict.__setitem__(draft.payload, "added", True)
    with pytest.raises(TypeError):
        dict.__setitem__(draft.payload["contact"], "name", "Changed")

    assert draft.payload_json == '{"contact":{"name":"José Rivera"}}'


def test_source_draft_payload_rejects_nested_mapping_mutation():
    draft = source_draft(payload={"contact": {"name": "José Rivera"}})

    with pytest.raises(TypeError):
        draft.payload["contact"]["name"] = "Changed"


def test_source_draft_payload_rejects_nested_array_mutation():
    draft = source_draft(payload={"tags": ["buyer"]})

    with pytest.raises(TypeError):
        draft.payload["tags"][0] = "seller"


def test_source_draft_equality_and_canonical_json_use_frozen_payload_values():
    first = source_draft(payload={"zeta": [1, {"b": 2, "a": 1}], "alpha": None})
    second = source_draft(payload={"alpha": None, "zeta": [1, {"a": 1, "b": 2}]})

    assert first == second
    assert first.payload_json == second.payload_json
    assert first.payload_json == (
        '{"alpha":null,"zeta":[1,{"a":1,"b":2}]}'
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"unsupported": {"set-value"}},
        {("unsupported", "key"): "value"},
    ],
    ids=["set-value", "nonstring-unsupported-key"],
)
def test_source_draft_rejects_payload_values_json_cannot_serialize(payload):
    with pytest.raises(SourceDraftValidationError, match="payload"):
        source_draft(payload=payload)


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_source_draft_rejects_non_finite_payload_numbers(non_finite):
    with pytest.raises(SourceDraftValidationError, match="payload"):
        source_draft(payload={"amount": non_finite})


def test_source_draft_rejects_circular_payload_as_a_validation_error():
    circular_payload = {}
    circular_payload["self"] = circular_payload

    with pytest.raises(SourceDraftValidationError, match="payload"):
        source_draft(payload=circular_payload)


@pytest.mark.parametrize(
    "field",
    ["source_system", "module", "record_kind", "source_key", "parser_version"],
)
@pytest.mark.parametrize("blank", ["", " \t\n"])
def test_source_draft_rejects_every_blank_identity_field(field, blank):
    with pytest.raises(SourceDraftValidationError, match=field):
        source_draft(**{field: blank})


def test_source_draft_normalizes_supported_evidence_and_capture_values():
    draft = source_draft(
        evidence_level=EvidenceLevel.RENDERED_OCCURRENCE.value,
        capture_quality=CaptureQuality.PARTIAL.value,
    )

    assert draft.evidence_level is EvidenceLevel.RENDERED_OCCURRENCE
    assert draft.capture_quality is CaptureQuality.PARTIAL


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("evidence_level", "inferred_record"),
        ("evidence_level", 1),
        ("capture_quality", "unknown"),
        ("capture_quality", 1),
    ],
)
def test_source_draft_rejects_invalid_evidence_and_capture_values(
    field, invalid_value
):
    with pytest.raises(SourceDraftValidationError, match=field):
        source_draft(**{field: invalid_value})


@pytest.mark.parametrize(
    "artifact_path",
    [
        "",
        "   ",
        "/private/contact.json",
        "../contact.json",
        "contacts/../contact.json",
        r"contacts\..\contact.json",
        r"C:\private\contact.json",
        r"\\server\share\contact.json",
    ],
)
def test_source_draft_rejects_blank_absolute_and_traversing_artifact_paths(
    artifact_path,
):
    with pytest.raises(SourceDraftValidationError, match="artifact_paths"):
        source_draft(artifact_paths=(artifact_path,))


def test_source_draft_rejects_duplicate_artifact_paths():
    path = "kw_command_repaired/contacts/contact.json"

    with pytest.raises(SourceDraftValidationError, match="duplicate"):
        source_draft(artifact_paths=(path, path))


@pytest.mark.parametrize(
    "artifact_path",
    ["a/./b", "a//b", "a/b/", r"a\b"],
)
def test_source_draft_rejects_noncanonical_posix_artifact_paths(artifact_path):
    with pytest.raises(SourceDraftValidationError, match="artifact_paths"):
        source_draft(artifact_paths=(artifact_path,))


def test_source_draft_accepts_canonical_posix_artifact_path():
    assert source_draft(artifact_paths=("a/b",)).artifact_paths == ("a/b",)


def test_verify_artifact_bytes_accepts_exact_private_source_bytes():
    artifact = artifact_for(b"\x00private\xff")

    assert verify_artifact_bytes(artifact) is None


def test_verify_artifact_bytes_rejects_missing_private_source_bytes():
    with pytest.raises(ArchiveIntegrityError, match="content_bytes"):
        verify_artifact_bytes(replace(artifact_for(), content_bytes=None))


def test_verify_artifact_bytes_rejects_length_mismatch():
    artifact = artifact_for()

    with pytest.raises(ArchiveIntegrityError, match="size"):
        verify_artifact_bytes(replace(artifact, size_bytes=artifact.size_bytes + 1))


def test_verify_artifact_bytes_rejects_checksum_mismatch():
    with pytest.raises(ArchiveIntegrityError, match="checksum"):
        verify_artifact_bytes(replace(artifact_for(), sha256="0" * 64))


@pytest.mark.parametrize(
    "malformed_checksum",
    ["a" * 63, "g" * 64, hashlib.sha256(b"private archive bytes").hexdigest().upper()],
)
def test_verify_artifact_bytes_rejects_malformed_or_non_lowercase_checksum(
    malformed_checksum,
):
    with pytest.raises(ArchiveIntegrityError, match="sha256"):
        verify_artifact_bytes(
            replace(artifact_for(), sha256=malformed_checksum)
        )


def test_verify_artifact_bytes_rejects_negative_size():
    with pytest.raises(ArchiveIntegrityError, match="size_bytes"):
        verify_artifact_bytes(replace(artifact_for(), size_bytes=-1))


@pytest.mark.parametrize(
    "source_path",
    [
        "",
        "   ",
        "/private/contact.json",
        "../contact.json",
        "contacts/../contact.json",
        r"contacts\..\contact.json",
        r"C:\private\contact.json",
        r"\\server\share\contact.json",
    ],
)
def test_verify_artifact_bytes_rejects_unsafe_or_blank_source_path(source_path):
    with pytest.raises(ArchiveIntegrityError, match="source_path"):
        verify_artifact_bytes(artifact_for(source_path=source_path))


@pytest.mark.parametrize(
    "source_path",
    ["a/./b", "a//b", "a/b/", r"a\b"],
)
def test_verify_artifact_bytes_rejects_noncanonical_posix_source_paths(source_path):
    with pytest.raises(ArchiveIntegrityError, match="source_path"):
        verify_artifact_bytes(artifact_for(source_path=source_path))


def test_verify_artifact_bytes_accepts_canonical_posix_source_path():
    assert verify_artifact_bytes(artifact_for(source_path="a/b")) is None


def test_bundle_fingerprint_is_order_independent_and_uses_canonical_rows():
    first = artifact_for(b"alpha", id=1, source_path="z/alpha.json")
    second = artifact_for(b"beta", id=2, source_path="a/beta.json")
    canonical_bytes = (
        f"{second.source_path}\0{second.sha256}\0{second.size_bytes}\n"
        f"{first.source_path}\0{first.sha256}\0{first.size_bytes}\n"
    ).encode("utf-8")
    expected = hashlib.sha256(canonical_bytes).hexdigest()

    assert bundle_fingerprint([first, second]) == expected
    assert bundle_fingerprint([second, first]) == expected


def test_bundle_fingerprint_validates_every_artifact():
    invalid = replace(artifact_for(), content_bytes=None)

    with pytest.raises(ArchiveIntegrityError, match="content_bytes"):
        bundle_fingerprint([invalid])


def test_bundle_fingerprint_rejects_duplicate_source_paths():
    path = "kw_command_repaired/contacts/contact.json"
    first = artifact_for(b"alpha", id=1, source_path=path)
    second = artifact_for(b"beta", id=2, source_path=path)

    with pytest.raises(ArchiveIntegrityError, match="duplicate"):
        bundle_fingerprint([first, second])


def test_empty_bundle_fingerprint_is_sha256_of_empty_bytes():
    assert bundle_fingerprint([]) == hashlib.sha256(b"").hexdigest()
