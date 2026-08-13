"""Private reviewed-overlap manifest validation and audited link staging."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import stat
from types import MappingProxyType

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.command import CRMContact
from models.command_contacts import CRMContactAuditEvent, canonical_json_text
from models.command_provenance import CRMEntitySource, CRMSourceRecord
from services.command_contact_identity import (
    ContactIdentityCandidate,
    canonical_email,
    canonical_phone,
    resolve_identity_clusters,
)
from services.command_provenance import SourceRecordDraft


SCHEMA_VERSION = "command-contact-overlaps-v1"
_HEX64 = re.compile(r"[0-9a-f]{64}")
_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "bundle_fingerprint", "parser_version", "rows"}
)
_ROW_KEYS = frozenset(
    {
        "source_provider_identity_hash",
        "target_contact_id",
        "target_contact_row_fingerprint",
        "strong_evidence_hash",
    }
)


class ContactOverlapManifestError(ValueError):
    """Safe failure for a private manifest; messages never echo its values/path."""


@dataclass(frozen=True, slots=True, order=True)
class ContactOverlapManifestRow:
    source_provider_identity_hash: str
    target_contact_id: int
    target_contact_row_fingerprint: str
    strong_evidence_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "source_provider_identity_hash",
            "target_contact_row_fingerprint",
            "strong_evidence_hash",
        ):
            if not isinstance((value := getattr(self, field_name)), str) or not (
                _HEX64.fullmatch(value)
            ):
                raise ContactOverlapManifestError(
                    "contact overlap manifest row contains an invalid digest"
                )
        if type(self.target_contact_id) is not int or self.target_contact_id <= 0:
            raise ContactOverlapManifestError(
                "contact overlap manifest target must be a positive contact ID"
            )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "source_provider_identity_hash": self.source_provider_identity_hash,
            "target_contact_id": self.target_contact_id,
            "target_contact_row_fingerprint": self.target_contact_row_fingerprint,
            "strong_evidence_hash": self.strong_evidence_hash,
        }


@dataclass(frozen=True, slots=True)
class ContactOverlapManifest:
    schema_version: str
    bundle_fingerprint: str
    parser_version: str
    rows: tuple[ContactOverlapManifestRow, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ContactOverlapManifestError(
                "contact overlap manifest schema version is unsupported"
            )
        if not isinstance(self.bundle_fingerprint, str) or not _HEX64.fullmatch(
            self.bundle_fingerprint
        ):
            raise ContactOverlapManifestError(
                "contact overlap manifest bundle fingerprint is invalid"
            )
        if self.parser_version != "contacts-v1":
            raise ContactOverlapManifestError(
                "contact overlap manifest parser version is invalid"
            )
        if not isinstance(self.rows, tuple) or any(
            not isinstance(row, ContactOverlapManifestRow) for row in self.rows
        ):
            raise ContactOverlapManifestError(
                "contact overlap manifest rows are invalid"
            )
        ordered = tuple(sorted(self.rows))
        if len(ordered) != 2:
            raise ContactOverlapManifestError(
                "contact overlap manifest must contain exactly two rows"
            )
        if len({row.source_provider_identity_hash for row in ordered}) != 2:
            raise ContactOverlapManifestError(
                "contact overlap manifest source hashes must be unique"
            )
        if len({row.target_contact_id for row in ordered}) != 2:
            raise ContactOverlapManifestError(
                "contact overlap manifest targets must be unique"
            )
        object.__setattr__(self, "rows", ordered)

    @property
    def canonical_digest(self) -> str:
        canonical = json.dumps(
            {
                "schema_version": self.schema_version,
                "bundle_fingerprint": self.bundle_fingerprint,
                "parser_version": self.parser_version,
                "rows": [row.canonical_payload() for row in self.rows],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def redacted_metadata(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "schema_version": self.schema_version,
                "canonical_digest": self.canonical_digest,
                "row_count": len(self.rows),
                "validation_state": "loaded",
            }
        )


@dataclass(frozen=True, slots=True)
class _ValidatedOverlap:
    source_provider_identity_hash: str
    source_record_id: int | None
    target_contact_id: int
    strong_evidence_hash: str


@dataclass(frozen=True, slots=True)
class ContactOverlapValidation:
    schema_version: str
    canonical_digest: str
    row_count: int
    validation_state: str
    overlaps: tuple[_ValidatedOverlap, ...]

    @property
    def redacted_metadata(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "schema_version": self.schema_version,
                "canonical_digest": self.canonical_digest,
                "row_count": self.row_count,
                "validation_state": self.validation_state,
            }
        )


@dataclass(frozen=True, slots=True)
class ReviewedOverlapStageResult:
    links_created: int
    audits_created: int
    final_mapping_count: int
    validation: ContactOverlapValidation


def load_contact_overlap_manifest(
    path: str | Path,
    *,
    repository_root: str | Path | None = None,
) -> ContactOverlapManifest:
    """Load one regular private file without retaining or echoing its path."""
    private_path = Path(path)
    info = None
    try:
        info = private_path.lstat()
    except OSError:
        pass
    if info is None:
        raise ContactOverlapManifestError(
            "contact overlap manifest file is unavailable"
        )
    if not stat.S_ISREG(info.st_mode) or private_path.is_symlink():
        raise ContactOverlapManifestError(
            "contact overlap manifest must be a regular non-symlink file"
        )
    if repository_root is not None:
        location_error = False
        try:
            private_path.resolve(strict=True).relative_to(
                Path(repository_root).resolve(strict=True)
            )
        except ValueError:
            pass
        except OSError:
            location_error = True
        else:
            raise ContactOverlapManifestError(
                "contact overlap manifest must be outside the repository"
            )
        if location_error:
            raise ContactOverlapManifestError(
                "contact overlap manifest location cannot be verified"
            )
    payload: object = None
    invalid_payload = False
    try:
        raw = private_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        invalid_payload = True
    if invalid_payload:
        raise ContactOverlapManifestError(
            "contact overlap manifest is not valid UTF-8 JSON"
        )
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_KEYS:
        raise ContactOverlapManifestError(
            "contact overlap manifest top-level schema is invalid"
        )
    rows_payload = payload.get("rows")
    if not isinstance(rows_payload, list):
        raise ContactOverlapManifestError(
            "contact overlap manifest rows are invalid"
        )
    rows = []
    for raw_row in rows_payload:
        if not isinstance(raw_row, dict) or set(raw_row) != _ROW_KEYS:
            raise ContactOverlapManifestError(
                "contact overlap manifest row schema is invalid"
            )
        rows.append(
            ContactOverlapManifestRow(
                source_provider_identity_hash=raw_row[
                    "source_provider_identity_hash"
                ],
                target_contact_id=raw_row["target_contact_id"],
                target_contact_row_fingerprint=raw_row[
                    "target_contact_row_fingerprint"
                ],
                strong_evidence_hash=raw_row["strong_evidence_hash"],
            )
        )
    return ContactOverlapManifest(
        schema_version=payload["schema_version"],
        bundle_fingerprint=payload["bundle_fingerprint"],
        parser_version=payload["parser_version"],
        rows=tuple(rows),
    )


def target_contact_row_fingerprint(contact: CRMContact) -> str:
    """Hash only non-PII target concurrency fields."""
    if not isinstance(contact, CRMContact) or type(contact.id) is not int:
        raise ContactOverlapManifestError(
            "target contact row is unavailable for fingerprinting"
        )
    canonical = "\0".join(
        (
            "command-contact-target-v1",
            str(contact.id),
            "" if contact.lead_id is None else str(contact.lead_id),
            _timestamp(contact.created_at),
            _timestamp(contact.updated_at),
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def strong_email_evidence_hash(
    source_provider_identity_hash: str,
    email: str,
    target_row_fingerprint: str,
) -> str:
    """Bind reviewed strong-email evidence without retaining its raw value."""
    if not _HEX64.fullmatch(source_provider_identity_hash) or not _HEX64.fullmatch(
        target_row_fingerprint
    ):
        raise ContactOverlapManifestError(
            "strong overlap evidence inputs are invalid"
        )
    normalized_email = canonical_email(email)
    if normalized_email is None:
        raise ContactOverlapManifestError(
            "strong overlap evidence requires a canonical email"
        )
    private_email_hash = hashlib.sha256(
        f"command-contact-email-v1\0{normalized_email}".encode("utf-8")
    ).hexdigest()
    canonical = "\0".join(
        (
            "command-contact-overlap-evidence-v1",
            source_provider_identity_hash,
            target_row_fingerprint,
            private_email_hash,
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _contact_targets_statement(
    target_contact_ids: Sequence[int],
    *,
    lock_for_update: bool,
):
    statement = (
        select(CRMContact)
        .where(CRMContact.id.in_(tuple(target_contact_ids)))
        .execution_options(populate_existing=True)
    )
    if lock_for_update:
        statement = statement.with_for_update()
    return statement


async def validate_contact_overlap_manifest(
    db: AsyncSession,
    manifest: ContactOverlapManifest,
    records: Sequence[SourceRecordDraft],
    *,
    bundle_fingerprint: str,
    parser_version: str,
    require_persisted_sources: bool = False,
) -> ContactOverlapValidation:
    """Fully validate source, target, evidence, and existing-link invariants."""
    if not isinstance(manifest, ContactOverlapManifest):
        raise ContactOverlapManifestError(
            "a typed contact overlap manifest is required"
        )
    if (
        manifest.bundle_fingerprint != bundle_fingerprint
        or manifest.parser_version != parser_version
    ):
        raise ContactOverlapManifestError(
            "contact overlap manifest fingerprint or parser version changed"
        )
    profiles, clusters = _resolved_profile_drafts(records)
    targets = (
        await db.scalars(
            _contact_targets_statement(
                tuple(row.target_contact_id for row in manifest.rows),
                lock_for_update=require_persisted_sources,
            )
        )
    ).all()
    targets_by_id = {target.id: target for target in targets}
    if len(targets_by_id) != 2:
        raise ContactOverlapManifestError(
            "contact overlap manifest target set is unresolved"
        )

    validated = []
    for row in manifest.rows:
        cluster = clusters.get(row.source_provider_identity_hash)
        if cluster is None or len(cluster.source_contact_ids) != 1:
            raise ContactOverlapManifestError(
                "contact overlap manifest source set is unresolved"
            )
        source_id = cluster.source_contact_ids[0]
        draft = profiles[source_id]
        candidate = _candidate_from_profile(draft)
        source_email = canonical_email(candidate.primary_email)
        target = targets_by_id[row.target_contact_id]
        if target.lead_id is None:
            raise ContactOverlapManifestError(
                "contact overlap manifest target is not lead-backed"
            )
        actual_target_fingerprint = target_contact_row_fingerprint(target)
        if actual_target_fingerprint != row.target_contact_row_fingerprint:
            raise ContactOverlapManifestError(
                "contact overlap manifest target row changed"
            )
        target_email = canonical_email(target.email)
        if source_email is None or source_email != target_email:
            raise ContactOverlapManifestError(
                "contact overlap manifest strong-email evidence does not match"
            )
        source_phone = canonical_phone(candidate.e164_phone)
        target_phone = canonical_phone(target.phone)
        if (
            source_phone is not None
            and target_phone is not None
            and source_phone != target_phone
        ):
            raise ContactOverlapManifestError(
                "contact overlap manifest contains conflicting phone evidence"
            )
        if not _names_compatible(candidate, target):
            raise ContactOverlapManifestError(
                "contact overlap manifest contains conflicting name evidence"
            )
        expected_evidence = strong_email_evidence_hash(
            row.source_provider_identity_hash,
            source_email,
            actual_target_fingerprint,
        )
        if expected_evidence != row.strong_evidence_hash:
            raise ContactOverlapManifestError(
                "contact overlap manifest strong evidence changed"
            )

        source_record = await db.scalar(
            select(CRMSourceRecord).where(
                CRMSourceRecord.source_system == "kw_command",
                CRMSourceRecord.module == "contacts",
                CRMSourceRecord.record_kind == "contact_profile",
                CRMSourceRecord.source_key == draft.source_key,
                CRMSourceRecord.parser_version == parser_version,
            )
        )
        if require_persisted_sources and source_record is None:
            raise ContactOverlapManifestError(
                "contact overlap source record has not been persisted"
            )
        if source_record is not None:
            links = (
                await db.scalars(
                    select(CRMEntitySource).where(
                        CRMEntitySource.source_record_id == source_record.id,
                        CRMEntitySource.entity_type == "contact",
                    )
                )
            ).all()
            if any(link.entity_id != target.id for link in links):
                raise ContactOverlapManifestError(
                    "contact overlap source already has a conflicting mapping"
                )
        validated.append(
            _ValidatedOverlap(
                source_provider_identity_hash=row.source_provider_identity_hash,
                source_record_id=(source_record.id if source_record is not None else None),
                target_contact_id=target.id,
                strong_evidence_hash=row.strong_evidence_hash,
            )
        )
    return ContactOverlapValidation(
        schema_version=manifest.schema_version,
        canonical_digest=manifest.canonical_digest,
        row_count=2,
        validation_state="validated",
        overlaps=tuple(validated),
    )


async def stage_reviewed_contact_overlap_links(
    db: AsyncSession,
    manifest: ContactOverlapManifest,
    records: Sequence[SourceRecordDraft],
    *,
    bundle_fingerprint: str,
    parser_version: str,
    run_id: int,
) -> ReviewedOverlapStageResult:
    """Revalidate and stage exactly two idempotent reviewed contact links."""
    validation = await validate_contact_overlap_manifest(
        db,
        manifest,
        records,
        bundle_fingerprint=bundle_fingerprint,
        parser_version=parser_version,
        require_persisted_sources=True,
    )
    links_created = 0
    audits_created = 0
    for overlap in validation.overlaps:
        assert overlap.source_record_id is not None
        existing = await db.scalar(
            select(CRMEntitySource).where(
                CRMEntitySource.source_record_id == overlap.source_record_id,
                CRMEntitySource.entity_type == "contact",
            )
        )
        if existing is None:
            db.add(
                CRMEntitySource(
                    entity_type="contact",
                    entity_id=overlap.target_contact_id,
                    source_record_id=overlap.source_record_id,
                )
            )
            links_created += 1
        elif existing.entity_id != overlap.target_contact_id:
            raise ContactOverlapManifestError(
                "contact overlap link changed during staging"
            )

        existing_audits = (
            await db.scalars(
                select(CRMContactAuditEvent).where(
                    CRMContactAuditEvent.contact_id == overlap.target_contact_id,
                    CRMContactAuditEvent.action == "command_contact_overlap_reviewed",
                )
            )
        ).all()
        already_audited = any(
            _matching_audit(
                audit,
                manifest_digest=validation.canonical_digest,
                source_hash=overlap.source_provider_identity_hash,
                evidence_hash=overlap.strong_evidence_hash,
            )
            for audit in existing_audits
        )
        if not already_audited:
            db.add(
                CRMContactAuditEvent(
                    contact_id=overlap.target_contact_id,
                    actor_subject="command-reconciliation-service",
                    action="command_contact_overlap_reviewed",
                    before_json="{}",
                    after_json=canonical_json_text(
                        {
                            "run_id": run_id,
                            "manifest_digest": validation.canonical_digest,
                            "source_provider_identity_hash": (
                                overlap.source_provider_identity_hash
                            ),
                            "strong_evidence_hash": overlap.strong_evidence_hash,
                        }
                    ),
                )
            )
            audits_created += 1
    await db.flush()
    final_mapping_count = int(
        await db.scalar(
            select(func.count())
            .select_from(CRMEntitySource)
            .where(CRMEntitySource.entity_type == "contact")
        )
        or 0
    )
    return ReviewedOverlapStageResult(
        links_created=links_created,
        audits_created=audits_created,
        final_mapping_count=final_mapping_count,
        validation=validation,
    )


def _resolved_profile_drafts(records: Sequence[SourceRecordDraft]):
    profile_records = tuple(
        record
        for record in records
        if record.module == "contacts" and record.record_kind == "contact_profile"
    )
    profiles: dict[str, SourceRecordDraft] = {}
    candidates = []
    for record in profile_records:
        candidate = _candidate_from_profile(record)
        if candidate.source_contact_id in profiles:
            raise ContactOverlapManifestError(
                "contact overlap source profiles are ambiguous"
            )
        profiles[candidate.source_contact_id] = record
        candidates.append(candidate)
    clusters = {
        cluster.identity_hash: cluster
        for cluster in resolve_identity_clusters(tuple(candidates))
    }
    if len(clusters) != len(candidates):
        raise ContactOverlapManifestError(
            "contact overlap manifest requires one provider row per identity"
        )
    return profiles, clusters


def _candidate_from_profile(record: SourceRecordDraft) -> ContactIdentityCandidate:
    payload = record.payload.get("identity_candidate")
    if not isinstance(payload, Mapping):
        raise ContactOverlapManifestError(
            "contact overlap source profile lacks identity evidence"
        )
    try:
        return ContactIdentityCandidate(
            source_contact_id=payload["source_contact_id"],
            primary_email=payload.get("primary_email"),
            e164_phone=payload.get("e164_phone"),
            legal_name=payload.get("legal_name"),
            preferred_name=payload.get("preferred_name"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContactOverlapManifestError(
            "contact overlap source profile identity evidence is invalid"
        ) from exc


def _names_compatible(
    source: ContactIdentityCandidate,
    target: CRMContact,
) -> bool:
    source_names = {
        _normalized_name(value)
        for value in (source.legal_name, source.preferred_name)
        if _normalized_name(value)
    }
    target_name = _normalized_name(f"{target.first_name} {target.last_name}")
    return not source_names or not target_name or target_name in source_names


def _normalized_name(value: str | None) -> str:
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""


def _timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _matching_audit(
    audit: CRMContactAuditEvent,
    *,
    manifest_digest: str,
    source_hash: str,
    evidence_hash: str,
) -> bool:
    try:
        payload = json.loads(audit.after_json)
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and (
        payload.get("manifest_digest") == manifest_digest
        and payload.get("source_provider_identity_hash") == source_hash
        and payload.get("strong_evidence_hash") == evidence_hash
    )


__all__ = (
    "ContactOverlapManifest",
    "ContactOverlapManifestError",
    "ContactOverlapManifestRow",
    "ContactOverlapValidation",
    "ReviewedOverlapStageResult",
    "SCHEMA_VERSION",
    "load_contact_overlap_manifest",
    "stage_reviewed_contact_overlap_links",
    "strong_email_evidence_hash",
    "target_contact_row_fingerprint",
    "validate_contact_overlap_manifest",
)
