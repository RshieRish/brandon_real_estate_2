"""Deterministic source drafts and byte-level archive integrity checks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
from pathlib import PurePosixPath, PureWindowsPath
import re
from types import MappingProxyType
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.command import CRMArchiveArtifact
from models.command_provenance import (
    CRMSourceRecord,
    CRMSourceRecordArtifact,
    CaptureQuality,
    EvidenceLevel,
)


class ArchiveIntegrityError(ValueError):
    """Raised when a recovered archive artifact fails integrity validation."""


class SourceDraftValidationError(ValueError):
    """Raised when a semantic source-record draft is unsafe or incomplete."""


class ParserVersionConflict(ValueError):
    """Raised when one parser identity resolves to different source artifacts."""


class DuplicateSourceDraftError(ValueError):
    """Raised when a persistence batch repeats a five-part source identity."""


class MissingArchiveArtifactError(ValueError):
    """Raised when source evidence cannot resolve to the archive catalog."""


@dataclass(frozen=True, slots=True)
class PersistenceCounts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    links_created: int = 0

    def __post_init__(self) -> None:
        for field_name in ("created", "updated", "unchanged", "links_created"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ArchiveArtifactInput:
    id: int
    source_path: str
    domain: str
    artifact_type: str
    filename: str
    sha256: str
    size_bytes: int
    content_bytes: bytes | None


@dataclass(frozen=True, slots=True)
class SourceRecordDraft:
    source_system: str
    module: str
    record_kind: str
    source_key: str
    evidence_level: EvidenceLevel
    display_label: str
    payload: Mapping[str, object]
    artifact_paths: tuple[str, ...]
    parser_version: str
    capture_quality: CaptureQuality = CaptureQuality.COMPLETE
    captured_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "source_system",
            "module",
            "record_kind",
            "source_key",
            "parser_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise SourceDraftValidationError(f"{field_name} must be nonblank")

        evidence_level = _enum_value(
            self.evidence_level,
            EvidenceLevel,
            "evidence_level",
        )
        capture_quality = _enum_value(
            self.capture_quality,
            CaptureQuality,
            "capture_quality",
        )
        object.__setattr__(self, "evidence_level", evidence_level)
        object.__setattr__(self, "capture_quality", capture_quality)

        if not isinstance(self.payload, Mapping):
            raise SourceDraftValidationError("payload must be a mapping")
        try:
            frozen_payload = _freeze_json_value(self.payload)
            json.dumps(
                _thaw_json_value(frozen_payload),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise SourceDraftValidationError(
                "payload must contain canonical JSON-serializable values"
            ) from exc
        object.__setattr__(self, "payload", frozen_payload)

        if not isinstance(self.artifact_paths, tuple):
            raise SourceDraftValidationError("artifact_paths must be a tuple")

        seen_paths: set[str] = set()
        for artifact_path in self.artifact_paths:
            _validate_relative_path(
                artifact_path,
                field_name="artifact_paths",
                error_type=SourceDraftValidationError,
            )
            if artifact_path in seen_paths:
                raise SourceDraftValidationError(
                    f"artifact_paths contains duplicate path: {artifact_path}"
                )
            seen_paths.add(artifact_path)

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.source_system,
            self.module,
            self.record_kind,
            self.source_key,
            self.parser_version,
        )

    @property
    def payload_json(self) -> str:
        return json.dumps(
            _thaw_json_value(self.payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


async def persist_source_records(
    db: AsyncSession,
    drafts: Sequence[SourceRecordDraft],
) -> PersistenceCounts:
    """Flush semantic source records and evidence links without committing."""
    materialized = tuple(drafts)
    identities: set[tuple[str, str, str, str, str]] = set()
    artifact_paths: set[str] = set()
    for draft in materialized:
        if not isinstance(draft, SourceRecordDraft):
            raise SourceDraftValidationError(
                "drafts must contain only SourceRecordDraft values"
            )
        if draft.identity in identities:
            raise DuplicateSourceDraftError(
                f"duplicate source draft identity: {draft.identity}"
            )
        identities.add(draft.identity)
        if not draft.artifact_paths:
            if draft.evidence_level is not EvidenceLevel.DISPLAYED_AGGREGATE:
                raise MissingArchiveArtifactError(
                    "only a displayed aggregate may omit archive artifacts"
                )
        artifact_paths.update(draft.artifact_paths)

    artifacts_by_path: dict[str, CRMArchiveArtifact] = {}
    if artifact_paths:
        artifacts = await db.scalars(
            select(CRMArchiveArtifact).where(
                CRMArchiveArtifact.source_path.in_(artifact_paths)
            )
        )
        artifacts_by_path = {artifact.source_path: artifact for artifact in artifacts}
        missing_paths = artifact_paths.difference(artifacts_by_path)
        if missing_paths:
            raise MissingArchiveArtifactError(
                "archive artifacts not found: " + ", ".join(sorted(missing_paths))
            )

    created = 0
    updated = 0
    unchanged = 0
    links_created = 0
    for draft in materialized:
        source_record = await db.scalar(
            select(CRMSourceRecord).where(
                CRMSourceRecord.source_system == draft.source_system,
                CRMSourceRecord.module == draft.module,
                CRMSourceRecord.record_kind == draft.record_kind,
                CRMSourceRecord.source_key == draft.source_key,
                CRMSourceRecord.parser_version == draft.parser_version,
            )
        )
        if source_record is None:
            source_record = CRMSourceRecord(
                source_system=draft.source_system,
                module=draft.module,
                record_kind=draft.record_kind,
                source_key=draft.source_key,
                evidence_level=draft.evidence_level.value,
                display_label=draft.display_label,
                payload_json=draft.payload_json,
                capture_quality=draft.capture_quality.value,
                captured_at=draft.captured_at,
                parser_version=draft.parser_version,
            )
            db.add(source_record)
            await db.flush()
            for path in draft.artifact_paths:
                db.add(
                    CRMSourceRecordArtifact(
                        source_record_id=source_record.id,
                        artifact_id=artifacts_by_path[path].id,
                        relation="evidence",
                    )
                )
                links_created += 1
            created += 1
            continue

        existing_paths = set(
            await db.scalars(
                select(CRMArchiveArtifact.source_path)
                .join(
                    CRMSourceRecordArtifact,
                    CRMSourceRecordArtifact.artifact_id == CRMArchiveArtifact.id,
                )
                .where(CRMSourceRecordArtifact.source_record_id == source_record.id)
            )
        )
        requested_paths = set(draft.artifact_paths)
        if existing_paths != requested_paths:
            raise ParserVersionConflict(
                "source artifact set changed; a new parser version is required "
                f"for identity {draft.identity}"
            )

        semantic_values = {
            "evidence_level": draft.evidence_level.value,
            "display_label": draft.display_label,
            "payload_json": draft.payload_json,
            "capture_quality": draft.capture_quality.value,
            "captured_at": draft.captured_at,
        }
        if any(
            getattr(source_record, field_name) != value
            for field_name, value in semantic_values.items()
        ):
            for field_name, value in semantic_values.items():
                setattr(source_record, field_name, value)
            updated += 1
        else:
            unchanged += 1

    await db.flush()
    return PersistenceCounts(
        created=created,
        updated=updated,
        unchanged=unchanged,
        links_created=links_created,
    )


_EnumType = TypeVar("_EnumType", bound=Enum)
_LOWERCASE_SHA256 = re.compile(r"[0-9a-f]{64}")


def _freeze_json_value(
    value: object,
    ancestors: set[int] | None = None,
) -> object:
    if not isinstance(value, Mapping | list | tuple):
        return value

    if ancestors is None:
        ancestors = set()
    identity = id(value)
    if identity in ancestors:
        raise ValueError("payload cannot contain circular references")
    ancestors.add(identity)
    try:
        if isinstance(value, Mapping):
            return MappingProxyType(
                {
                    key: _freeze_json_value(item, ancestors)
                    for key, item in value.items()
                }
            )
        return tuple(_freeze_json_value(item, ancestors) for item in value)
    finally:
        ancestors.remove(identity)


def _thaw_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    return value


def _enum_value(
    value: object,
    enum_type: type[_EnumType],
    field_name: str,
) -> _EnumType:
    if isinstance(value, enum_type):
        return value
    if type(value) is str:
        try:
            return enum_type(value)
        except ValueError:
            pass
    raise SourceDraftValidationError(
        f"{field_name} must be a supported {enum_type.__name__} value"
    )


def _validate_relative_path(
    path: object,
    *,
    field_name: str,
    error_type: type[ValueError],
) -> None:
    if not isinstance(path, str) or not path.strip():
        raise error_type(f"{field_name} must contain a nonblank relative path")
    if "\x00" in path:
        raise error_type(f"{field_name} contains an unsafe NUL byte")
    if "\\" in path:
        raise error_type(f"{field_name} must use canonical POSIX separators: {path}")

    posix_path = PurePosixPath(path)
    windows_path = PureWindowsPath(path)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or bool(windows_path.root)
    ):
        raise error_type(f"{field_name} must be relative: {path}")

    path_segments = path.split("/")
    if ".." in path_segments:
        raise error_type(f"{field_name} cannot contain '..': {path}")
    if path != posix_path.as_posix() or any(
        segment in {"", "."} for segment in path_segments
    ):
        raise error_type(f"{field_name} must already be canonical POSIX: {path}")


def verify_artifact_bytes(artifact: ArchiveArtifactInput) -> None:
    """Verify an artifact's safe path, declared metadata, and private bytes."""
    if not isinstance(artifact, ArchiveArtifactInput):
        raise ArchiveIntegrityError("artifact must be an ArchiveArtifactInput")

    _validate_relative_path(
        artifact.source_path,
        field_name="source_path",
        error_type=ArchiveIntegrityError,
    )
    if type(artifact.size_bytes) is not int or artifact.size_bytes < 0:
        raise ArchiveIntegrityError("size_bytes must be a non-negative integer")
    if (
        not isinstance(artifact.sha256, str)
        or _LOWERCASE_SHA256.fullmatch(artifact.sha256) is None
    ):
        raise ArchiveIntegrityError(
            "sha256 must be exactly 64 lowercase hexadecimal characters"
        )
    if not isinstance(artifact.content_bytes, bytes):
        raise ArchiveIntegrityError("content_bytes must contain private source bytes")
    if len(artifact.content_bytes) != artifact.size_bytes:
        raise ArchiveIntegrityError(
            "content_bytes length does not match declared size_bytes"
        )

    actual_sha256 = hashlib.sha256(artifact.content_bytes).hexdigest()
    if artifact.sha256 != actual_sha256:
        raise ArchiveIntegrityError("artifact checksum does not match content_bytes")


def bundle_fingerprint(artifacts: Iterable[ArchiveArtifactInput]) -> str:
    """Hash canonical artifact rows; an empty bundle hashes as empty bytes."""
    materialized = tuple(artifacts)
    for artifact in materialized:
        verify_artifact_bytes(artifact)

    ordered = sorted(materialized, key=lambda artifact: artifact.source_path)
    fingerprint = hashlib.sha256()
    previous_path: str | None = None
    for artifact in ordered:
        if artifact.source_path == previous_path:
            raise ArchiveIntegrityError(
                f"bundle contains duplicate source_path: {artifact.source_path}"
            )
        previous_path = artifact.source_path
        fingerprint.update(
            (
                f"{artifact.source_path}\0{artifact.sha256.lower()}\0"
                f"{artifact.size_bytes}\n"
            ).encode("utf-8")
        )
    return fingerprint.hexdigest()
