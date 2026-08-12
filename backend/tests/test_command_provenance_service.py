from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime
import asyncio
import hashlib
from types import MappingProxyType

import pytest
from sqlalchemy import func, select

from command_db import (
    archive_artifact_row,
    command_db as command_db_session,
    command_file_session_factory,
)
from models.command_provenance import (
    CRMSourceRecord,
    CRMSourceRecordArtifact,
    CaptureQuality,
    EvidenceLevel,
)
from services.command_provenance import (
    ArchiveArtifactInput,
    ArchiveIntegrityError,
    SourceDraftValidationError,
    SourceRecordDraft,
    bundle_fingerprint,
    verify_artifact_bytes,
)


command_db = pytest.fixture(name="command_db")(command_db_session)


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


async def test_persistence_creates_records_and_links_then_is_idempotent(command_db):
    from services.command_provenance import PersistenceCounts, persist_source_records

    first_path = "kw_command_repaired/contacts/contact.json"
    second_path = "kw_command_repaired/contacts/timeline.json"
    command_db.add_all(
        [
            archive_artifact_row(source_path=first_path),
            archive_artifact_row(source_path=second_path, content=b"timeline"),
        ]
    )
    await command_db.flush()
    first = source_draft(artifact_paths=(first_path, second_path))
    second = source_draft(
        source_key="contact-2",
        display_label="Ada Lovelace",
        payload={"name": "Ada Lovelace"},
        artifact_paths=(first_path,),
    )

    assert await persist_source_records(command_db, (first, second)) == (
        PersistenceCounts(created=2, links_created=3)
    )
    assert (
        await command_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 2
    )
    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMSourceRecordArtifact)
        )
        == 3
    )

    assert await persist_source_records(command_db, (first, second)) == (
        PersistenceCounts(unchanged=2)
    )
    assert (
        await command_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 2
    )
    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMSourceRecordArtifact)
        )
        == 3
    )


async def test_persistence_updates_semantics_when_artifact_set_is_unchanged(
    command_db,
):
    from services.command_provenance import PersistenceCounts, persist_source_records

    path = "kw_command_repaired/contacts/contact.json"
    command_db.add(archive_artifact_row(source_path=path))
    await command_db.flush()
    captured_at = datetime(2026, 8, 12, 14, 30)
    original = source_draft(artifact_paths=(path,))
    changed = source_draft(
        artifact_paths=(path,),
        display_label="José Rivera — updated",
        payload={"name": "José Rivera", "stage": "lead"},
        capture_quality=CaptureQuality.PARTIAL,
        captured_at=captured_at,
    )

    assert await persist_source_records(command_db, (original,)) == PersistenceCounts(
        created=1,
        links_created=1,
    )
    assert await persist_source_records(command_db, (changed,)) == PersistenceCounts(
        updated=1
    )

    row = await command_db.scalar(select(CRMSourceRecord))
    assert row is not None
    assert row.evidence_level == EvidenceLevel.OBSERVED_RECORD.value
    assert row.display_label == "José Rivera — updated"
    assert row.payload_json == '{"name":"José Rivera","stage":"lead"}'
    assert row.capture_quality == CaptureQuality.PARTIAL.value
    assert row.captured_at == captured_at


async def test_persistence_requires_new_parser_version_for_evidence_level_change(
    command_db,
):
    from services.command_provenance import (
        ParserVersionConflict,
        persist_source_records,
    )

    path = "kw_command_repaired/contacts/contact.json"
    command_db.add(archive_artifact_row(source_path=path))
    await command_db.flush()
    await persist_source_records(
        command_db,
        (source_draft(artifact_paths=(path,)),),
    )

    with pytest.raises(ParserVersionConflict, match="evidence level"):
        await persist_source_records(
            command_db,
            (
                source_draft(
                    artifact_paths=(path,),
                    evidence_level=EvidenceLevel.RENDERED_OCCURRENCE,
                ),
            ),
        )

    row = await command_db.scalar(select(CRMSourceRecord))
    assert row is not None
    assert row.evidence_level == EvidenceLevel.OBSERVED_RECORD.value


async def test_persistence_rejects_parser_identity_with_changed_artifact_set(
    command_db,
):
    from services.command_provenance import (
        ParserVersionConflict,
        persist_source_records,
    )

    first_path = "kw_command_repaired/contacts/contact.json"
    second_path = "kw_command_repaired/contacts/other.json"
    command_db.add_all(
        [
            archive_artifact_row(source_path=first_path),
            archive_artifact_row(source_path=second_path, content=b"other"),
        ]
    )
    await command_db.flush()
    await persist_source_records(
        command_db, (source_draft(artifact_paths=(first_path,)),)
    )

    with pytest.raises(ParserVersionConflict, match="parser version"):
        await persist_source_records(
            command_db,
            (source_draft(artifact_paths=(first_path, second_path)),),
        )


async def test_persistence_rejects_duplicate_draft_identity_before_db_writes(
    command_db,
):
    from services.command_provenance import (
        DuplicateSourceDraftError,
        persist_source_records,
    )

    path = "kw_command_repaired/contacts/contact.json"
    command_db.add(archive_artifact_row(source_path=path))
    await command_db.flush()
    first = source_draft(artifact_paths=(path,))
    duplicate = source_draft(artifact_paths=(path,), display_label="Changed")

    with pytest.raises(DuplicateSourceDraftError, match="duplicate"):
        await persist_source_records(command_db, (first, duplicate))

    assert (
        await command_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 0
    )


async def test_persistence_rejects_missing_artifacts_before_record_writes(command_db):
    from services.command_provenance import (
        MissingArchiveArtifactError,
        persist_source_records,
    )

    present_path = "kw_command_repaired/contacts/contact.json"
    command_db.add(archive_artifact_row(source_path=present_path))
    await command_db.flush()

    with pytest.raises(MissingArchiveArtifactError, match="missing.json"):
        await persist_source_records(
            command_db,
            (
                source_draft(artifact_paths=(present_path,)),
                source_draft(
                    source_key="missing",
                    artifact_paths=("kw_command_repaired/contacts/missing.json",),
                ),
            ),
        )

    assert (
        await command_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 0
    )


async def test_persistence_allows_only_aggregate_drafts_without_artifacts(command_db):
    from services.command_provenance import (
        MissingArchiveArtifactError,
        PersistenceCounts,
        persist_source_records,
    )

    nonaggregate = source_draft(artifact_paths=())
    with pytest.raises(MissingArchiveArtifactError, match="aggregate"):
        await persist_source_records(command_db, (nonaggregate,))

    aggregate = source_draft(
        source_key="displayed-total",
        record_kind="contact_total",
        evidence_level=EvidenceLevel.DISPLAYED_AGGREGATE,
        artifact_paths=(),
        payload={"count": 42},
    )
    assert await persist_source_records(command_db, (aggregate,)) == PersistenceCounts(
        created=1
    )


async def test_persistence_failure_is_atomic_after_caller_rollback(command_db):
    from services.command_provenance import (
        MissingArchiveArtifactError,
        persist_source_records,
    )

    present_path = "kw_command_repaired/contacts/contact.json"
    command_db.add(archive_artifact_row(source_path=present_path))
    await command_db.commit()

    await persist_source_records(
        command_db,
        (
            source_draft(
                source_key="kept-only-without-rollback", artifact_paths=(present_path,)
            ),
        ),
    )
    with pytest.raises(MissingArchiveArtifactError):
        await persist_source_records(
            command_db,
            (
                source_draft(
                    source_key="missing",
                    artifact_paths=("kw_command_repaired/contacts/missing.json",),
                ),
            ),
        )
    await command_db.rollback()

    assert (
        await command_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 0
    )


async def test_persistence_rejects_non_draft_values_before_db_writes(command_db):
    from services.command_provenance import (
        SourceDraftValidationError,
        persist_source_records,
    )

    with pytest.raises(SourceDraftValidationError, match="SourceRecordDraft"):
        await persist_source_records(command_db, (object(),))

    assert (
        await command_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 0
    )


async def test_concurrent_persistence_creates_one_identity_without_errors(tmp_path):
    from services.command_provenance import PersistenceCounts, persist_source_records

    engine, session_factory = await command_file_session_factory(
        tmp_path / "persistence-race.db"
    )
    path = "kw_command_repaired/contacts/contact.json"
    async with session_factory() as seed_session:
        seed_session.add(archive_artifact_row(source_path=path))
        await seed_session.commit()
    start = asyncio.Event()

    async def worker():
        async with session_factory() as session:
            await start.wait()
            counts = await persist_source_records(
                session,
                (source_draft(artifact_paths=(path,)),),
            )
            await session.commit()
            return counts

    tasks = [asyncio.create_task(worker()), asyncio.create_task(worker())]
    start.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    errors = [result for result in results if isinstance(result, Exception)]
    assert not errors, repr(errors)
    assert sorted(
        results,
        key=lambda counts: (counts.created, counts.unchanged),
    ) == [
        PersistenceCounts(unchanged=1),
        PersistenceCounts(created=1, links_created=1),
    ]
    async with session_factory() as verification_session:
        assert (
            await verification_session.scalar(
                select(func.count()).select_from(CRMSourceRecord)
            )
            == 1
        )
        assert (
            await verification_session.scalar(
                select(func.count()).select_from(CRMSourceRecordArtifact)
            )
            == 1
        )
    await engine.dispose()


def test_persistence_counts_are_frozen_slotted_and_nonnegative():
    from services.command_provenance import PersistenceCounts

    counts = PersistenceCounts()
    assert (
        counts.created
        == counts.updated
        == counts.unchanged
        == counts.links_created
        == 0
    )
    assert not hasattr(counts, "__dict__")
    with pytest.raises(FrozenInstanceError):
        counts.created = 1
    with pytest.raises(ValueError, match="non-negative"):
        PersistenceCounts(created=-1)
