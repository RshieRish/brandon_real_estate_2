"""Transactional additive materialization for recovered Command contacts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.command import CRMActivity, CRMContact, CRMNote, CRMSavedSearch
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
    CRMContactTimelineEvent,
    canonical_json_text,
)
from models.command_provenance import CRMEntitySource, CRMSourceRecord
from services.command_contact_identity import (
    ContactIdentityCandidate,
    ContactIdentityCluster,
    canonical_email,
    canonical_phone,
    resolve_identity_clusters,
)
from services.command_contact_occurrences import (
    ContactOccurrenceOwnershipError,
    sync_contact_occurrence_ownership,
)
from services.command_materializers.base import ModuleMaterializationResult
from services.command_provenance import SourceRecordDraft

_HEX64 = re.compile(r"[0-9a-f]{64}")


class ContactMaterializationError(ValueError):
    """Privacy-safe materialization conflict that blocks the module transaction."""


class ContactMaterializer:
    module = "contacts"

    async def materialize(
        self,
        db: AsyncSession,
        records: Sequence[SourceRecordDraft],
        *,
        bundle_fingerprint: str,
    ) -> ModuleMaterializationResult:
        if not isinstance(bundle_fingerprint, str) or not _HEX64.fullmatch(
            bundle_fingerprint
        ):
            raise ContactMaterializationError("bundle fingerprint is invalid")
        materialized = tuple(records)
        if any(
            not isinstance(record, SourceRecordDraft)
            or record.module != self.module
            for record in materialized
        ):
            raise ContactMaterializationError(
                "contact materializer received records outside its module"
            )
        profile_drafts = tuple(
            record
            for record in materialized
            if record.record_kind == "contact_profile"
        )
        profiles_by_source: dict[str, SourceRecordDraft] = {}
        candidates = []
        for draft in profile_drafts:
            candidate = _candidate(draft)
            if candidate.source_contact_id in profiles_by_source:
                raise ContactMaterializationError(
                    "recovered contact profile set is ambiguous"
                )
            profiles_by_source[candidate.source_contact_id] = draft
            candidates.append(candidate)
        clusters = resolve_identity_clusters(tuple(candidates))

        persisted_by_identity = await _persisted_records(db, materialized)
        profile_source_rows: dict[str, CRMSourceRecord] = {}
        for source_id, draft in profiles_by_source.items():
            source_record = persisted_by_identity.get(draft.identity)
            if source_record is None:
                raise ContactMaterializationError(
                    "a recovered contact source record is missing"
                )
            profile_source_rows[source_id] = source_record

        profile_source_ids = tuple(row.id for row in profile_source_rows.values())
        existing_links = (
            await db.scalars(
                select(CRMEntitySource).where(
                    CRMEntitySource.entity_type == "contact",
                    CRMEntitySource.source_record_id.in_(profile_source_ids),
                )
            )
        ).all()
        links_by_source_record: dict[int, list[CRMEntitySource]] = {}
        for link in existing_links:
            links_by_source_record.setdefault(link.source_record_id, []).append(link)

        contacts = (await db.scalars(select(CRMContact))).all()
        contacts_by_id = {contact.id: contact for contact in contacts}
        legacy_profiles_staged = await _stage_legacy_capture_profiles(
            db,
            profiles_by_source,
            clusters,
            contacts_by_id,
        )
        await db.flush()
        contact_profiles = (await db.scalars(select(CRMContactProfile))).all()
        preexisting_contact_rows = len(contacts)
        lead_backed_contacts = sum(
            contact.lead_id is not None for contact in contacts
        )
        legacy_lead_ids_preserved = len(
            {contact.lead_id for contact in contacts if contact.lead_id is not None}
        )
        stale_source_normalized_rows = sum(
            profile.recovered_identity_hash is not None
            for profile in contact_profiles
        )
        stale_source_normalized_leadless_rows = sum(
            profile.recovered_identity_hash is not None
            and contacts_by_id[profile.contact_id].lead_id is None
            for profile in contact_profiles
        )
        profiles_by_contact = {
            profile.contact_id: profile for profile in contact_profiles
        }
        profiles_by_hash: dict[str, list[CRMContactProfile]] = {}
        for profile in contact_profiles:
            if profile.recovered_identity_hash:
                profiles_by_hash.setdefault(
                    profile.recovered_identity_hash, []
                ).append(profile)

        created_count = 0
        adopted_count = 0
        unchanged_count = 0
        contact_links_created = 0
        reviewed_lead_backed_contact_ids: set[int] = set()
        source_to_contact: dict[str, CRMContact] = {}
        for cluster in clusters:
            cluster_source_rows = tuple(
                profile_source_rows[source_id]
                for source_id in cluster.source_contact_ids
            )
            mapped_ids = {
                link.entity_id
                for source_row in cluster_source_rows
                for link in links_by_source_record.get(source_row.id, ())
            }
            if len(mapped_ids) > 1:
                raise ContactMaterializationError(
                    "one recovered identity maps to multiple contacts"
                )
            contact: CRMContact
            if mapped_ids:
                mapped_id = next(iter(mapped_ids))
                contact = contacts_by_id.get(mapped_id)  # type: ignore[assignment]
                if contact is None:
                    raise ContactMaterializationError(
                        "a recovered contact mapping targets a missing contact"
                    )
                if contact.lead_id is not None and not await _has_reviewed_overlap(
                    db, contact.id, cluster.identity_hash
                ):
                    raise ContactMaterializationError(
                        "lead-backed recovery requires a reviewed overlap mapping"
                    )
                if contact.lead_id is not None:
                    reviewed_lead_backed_contact_ids.add(contact.id)
                unchanged_count += 1
            else:
                adoption_profiles = profiles_by_hash.get(cluster.identity_hash, [])
                if len(adoption_profiles) > 1:
                    raise ContactMaterializationError(
                        "multiple leadless contacts match one recovered identity"
                    )
                if adoption_profiles:
                    adoption = adoption_profiles[0]
                    contact = contacts_by_id[adoption.contact_id]
                    if contact.lead_id is not None:
                        raise ContactMaterializationError(
                            "lead-backed recovery requires a reviewed overlap mapping"
                        )
                    adopted_count += 1
                else:
                    primary_draft = profiles_by_source[cluster.source_contact_ids[0]]
                    contact = _new_contact(primary_draft)
                    db.add(contact)
                    await db.flush()
                    contacts_by_id[contact.id] = contact
                    created_count += 1

            existing_profile = profiles_by_contact.get(contact.id)
            if existing_profile is not None and (
                existing_profile.recovered_identity_hash
                and existing_profile.recovered_identity_hash != cluster.identity_hash
            ):
                raise ContactMaterializationError(
                    "normalized contact profile has a conflicting recovered identity"
                )
            if contact.lead_id is None:
                primary_draft = profiles_by_source[cluster.source_contact_ids[0]]
                profile = await _upsert_profile(
                    db,
                    contact,
                    existing_profile,
                    cluster.identity_hash,
                    primary_draft,
                )
                profiles_by_contact[contact.id] = profile
                profiles_by_hash.setdefault(cluster.identity_hash, [profile])
                await _upsert_profile_children(
                    db,
                    contact,
                    profile_source_rows[cluster.source_contact_ids[0]],
                    primary_draft,
                )

            for source_id in cluster.source_contact_ids:
                source_to_contact[source_id] = contact
                source_record = profile_source_rows[source_id]
                links = links_by_source_record.get(source_record.id, [])
                if links:
                    if any(link.entity_id != contact.id for link in links):
                        raise ContactMaterializationError(
                            "recovered provider source has a conflicting mapping"
                        )
                    continue
                link = CRMEntitySource(
                    entity_type="contact",
                    entity_id=contact.id,
                    source_record_id=source_record.id,
                )
                db.add(link)
                links_by_source_record[source_record.id] = [link]
                contact_links_created += 1

        await db.flush()
        positions_by_ordinal = await _upsert_positions(
            db,
            materialized,
            persisted_by_identity,
            source_to_contact,
            bundle_fingerprint,
        )
        await _upsert_sections(
            db,
            materialized,
            persisted_by_identity,
            positions_by_ordinal,
        )
        await db.flush()
        parser_versions = {record.parser_version for record in materialized}
        if len(parser_versions) != 1:
            raise ContactMaterializationError(
                "contact materializer received an inconsistent parser version"
            )
        try:
            occurrence_sync = await sync_contact_occurrence_ownership(
                db,
                records=materialized,
                persisted_by_identity=persisted_by_identity,
                bundle_fingerprint=bundle_fingerprint,
                parser_version=next(iter(parser_versions)),
            )
        except ContactOccurrenceOwnershipError as exc:
            raise ContactMaterializationError(str(exc)) from exc
        child_links_created = await _materialize_occurrences(
            db,
            materialized,
            persisted_by_identity,
            source_to_contact,
        )
        await db.flush()

        final_mapping_count = int(
            await db.scalar(
                select(func.count())
                .select_from(CRMEntitySource)
                .where(
                    CRMEntitySource.entity_type == "contact",
                    CRMEntitySource.source_record_id.in_(profile_source_ids),
                )
            )
            or 0
        )
        total_contacts = int(
            await db.scalar(select(func.count()).select_from(CRMContact)) or 0
        )
        return ModuleMaterializationResult(
            module=self.module,
            normalized_count=len(clusters),
            created_count=created_count,
            updated_count=adopted_count,
            unchanged_count=unchanged_count,
            links_created=contact_links_created,
            details={
                "adopted_leadless_contacts": adopted_count,
                "child_entity_links_created": child_links_created,
                "child_occurrences_observed": occurrence_sync.observed,
                "child_occurrences_created": occurrence_sync.created,
                "child_occurrences_unchanged": occurrence_sync.unchanged,
                "preexisting_contact_rows": preexisting_contact_rows,
                "stale_source_normalized_rows": stale_source_normalized_rows,
                "stale_source_normalized_leadless_rows": (
                    stale_source_normalized_leadless_rows
                ),
                "lead_backed_contacts": lead_backed_contacts,
                "strong_verified_overlaps": len(
                    reviewed_lead_backed_contact_ids
                ),
                "legacy_only_contacts": (
                    lead_backed_contacts - len(reviewed_lead_backed_contact_ids)
                ),
                "legacy_lead_ids_preserved": legacy_lead_ids_preserved,
                "legacy_capture_profiles_staged": legacy_profiles_staged,
                "source_entity_links_final": final_mapping_count,
                "total_contacts": total_contacts,
            },
        )


async def _persisted_records(
    db: AsyncSession,
    records: Sequence[SourceRecordDraft],
) -> dict[tuple[str, str, str, str, str], CRMSourceRecord]:
    if not records:
        return {}
    requested = {record.identity for record in records}
    source_rows = (
        await db.scalars(
            select(CRMSourceRecord).where(
                CRMSourceRecord.source_system == "kw_command",
                CRMSourceRecord.module == "contacts",
                CRMSourceRecord.source_key.in_(
                    {record.source_key for record in records}
                ),
                CRMSourceRecord.parser_version.in_(
                    {record.parser_version for record in records}
                ),
            )
        )
    ).all()
    return {
        identity: row
        for row in source_rows
        if (
            identity := (
            row.source_system,
            row.module,
            row.record_kind,
            row.source_key,
            row.parser_version,
            )
        ) in requested
    }


def _candidate(draft: SourceRecordDraft) -> ContactIdentityCandidate:
    payload = draft.payload.get("identity_candidate")
    if not isinstance(payload, Mapping):
        raise ContactMaterializationError(
            "recovered contact profile lacks identity evidence"
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
        raise ContactMaterializationError(
            "recovered contact identity evidence is invalid"
        ) from exc


async def _stage_legacy_capture_profiles(
    db: AsyncSession,
    profiles_by_source: Mapping[str, SourceRecordDraft],
    clusters: Sequence[ContactIdentityCluster],
    contacts_by_id: Mapping[int, CRMContact],
) -> int:
    """Bind the preserved legacy capture markers to recovered identities.

    The first Command import retained one technical timeline marker per
    source-normalized contact, including its canonical seven-digit capture
    ordinal, but it predates ``crm_contact_profiles``.  Contacts reconciliation
    needs that explicit historical edge in order to repair the existing rows
    instead of duplicating them.  This bridge is additive, idempotent, and
    refuses identifier drift.
    """
    markers = (
        await db.scalars(
            select(CRMActivity)
            .where(CRMActivity.kind == "archive_timeline_capture")
            .order_by(CRMActivity.id)
        )
    ).all()
    if not markers:
        return 0

    drafts_by_ordinal: dict[str, SourceRecordDraft] = {}
    for draft in profiles_by_source.values():
        ordinal = draft.payload.get("capture_ordinal")
        if not isinstance(ordinal, str) or re.fullmatch(r"[0-9]{7}", ordinal) is None:
            raise ContactMaterializationError(
                "recovered contact capture ordinal is invalid"
            )
        if ordinal in drafts_by_ordinal:
            raise ContactMaterializationError(
                "recovered contact capture ordinal is ambiguous"
            )
        drafts_by_ordinal[ordinal] = draft

    identity_by_source: dict[str, str] = {}
    for cluster in clusters:
        source_ids = cluster.source_contact_ids
        if len(source_ids) != 1:
            raise ContactMaterializationError(
                "legacy contact capture identity is ambiguous"
            )
        identity_by_source[source_ids[0]] = cluster.identity_hash

    existing_profiles = (await db.scalars(select(CRMContactProfile))).all()
    profiles_by_contact = {profile.contact_id: profile for profile in existing_profiles}
    profile_owner_by_hash = {
        profile.recovered_identity_hash: profile.contact_id
        for profile in existing_profiles
        if profile.recovered_identity_hash is not None
    }
    seen_contacts: set[int] = set()
    seen_ordinals: set[str] = set()
    marker_sources: set[str] = set()
    staged = 0
    for marker in markers:
        if marker.contact_id is None or marker.contact_id in seen_contacts:
            raise ContactMaterializationError(
                "legacy contact capture marker ownership is ambiguous"
            )
        try:
            metadata = json.loads(marker.metadata_json or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ContactMaterializationError(
                "legacy contact capture marker is invalid"
            ) from exc
        if not isinstance(metadata, dict) or set(metadata) != {"ordinal", "source"}:
            raise ContactMaterializationError(
                "legacy contact capture marker is invalid"
            )
        ordinal = metadata.get("ordinal")
        marker_source = metadata.get("source")
        if (
            not isinstance(ordinal, str)
            or re.fullmatch(r"[0-9]{7}", ordinal) is None
            or ordinal in seen_ordinals
            or not isinstance(marker_source, str)
            or not marker_source.strip()
        ):
            raise ContactMaterializationError(
                "legacy contact capture marker is invalid"
            )
        draft = drafts_by_ordinal.get(ordinal)
        contact = contacts_by_id.get(marker.contact_id)
        if draft is None or contact is None:
            raise ContactMaterializationError(
                "legacy contact capture marker is unresolved"
            )
        candidate = _candidate(draft)
        source_email = canonical_email(candidate.primary_email)
        target_email = canonical_email(contact.email)
        if source_email != target_email:
            raise ContactMaterializationError(
                "legacy contact capture email evidence changed"
            )
        source_phone = canonical_phone(candidate.e164_phone)
        target_phone = canonical_phone(contact.phone)
        if (
            source_phone is not None
            and target_phone is not None
            and source_phone != target_phone
        ):
            raise ContactMaterializationError(
                "legacy contact capture phone evidence changed"
            )
        identity_hash = identity_by_source.get(candidate.source_contact_id)
        if identity_hash is None:
            raise ContactMaterializationError(
                "legacy contact capture identity is unresolved"
            )
        current_owner = profile_owner_by_hash.get(identity_hash)
        if current_owner is not None and current_owner != contact.id:
            raise ContactMaterializationError(
                "legacy contact capture identity has conflicting ownership"
            )
        profile = profiles_by_contact.get(contact.id)
        if profile is None:
            profile = CRMContactProfile(
                contact_id=contact.id,
                recovered_identity_hash=identity_hash,
                birth_year_quality="unknown",
                anniversary_year_quality="unknown",
            )
            db.add(profile)
            profiles_by_contact[contact.id] = profile
            profile_owner_by_hash[identity_hash] = contact.id
            staged += 1
        elif profile.recovered_identity_hash is None:
            profile.recovered_identity_hash = identity_hash
            profile_owner_by_hash[identity_hash] = contact.id
            staged += 1
        elif profile.recovered_identity_hash != identity_hash:
            raise ContactMaterializationError(
                "legacy contact capture profile identity changed"
            )
        seen_contacts.add(contact.id)
        seen_ordinals.add(ordinal)
        marker_sources.add(marker_source.strip())

    if len(marker_sources) != 1:
        raise ContactMaterializationError(
            "legacy contact capture source is ambiguous"
        )
    return staged


def _new_contact(draft: SourceRecordDraft) -> CRMContact:
    payload = draft.payload
    name = _string(payload.get("preferred_name")) or _string(
        payload.get("legal_name")
    ) or _string(payload.get("display_name"))
    if not name:
        raise ContactMaterializationError("recovered contact name is unavailable")
    first_name, _, last_name = name.partition(" ")
    return CRMContact(
        first_name=first_name,
        last_name=last_name,
        email=canonical_email(_string(payload.get("primary_email"))),
        phone=canonical_phone(_string(payload.get("primary_phone"))),
        stage="lead",
        birthday=None,
        anniversary=None,
    )


async def _upsert_profile(
    db: AsyncSession,
    contact: CRMContact,
    existing: CRMContactProfile | None,
    identity_hash: str,
    draft: SourceRecordDraft,
) -> CRMContactProfile:
    birthday = _mapping(draft.payload.get("birthday"))
    anniversary = _mapping(draft.payload.get("anniversary"))
    values = {
        "recovered_identity_hash": identity_hash,
        "legal_name": _string(draft.payload.get("legal_name")),
        "preferred_name": _string(draft.payload.get("preferred_name")),
        "birth_month": _integer(birthday.get("month")),
        "birth_day": _integer(birthday.get("day")),
        "birth_year": _integer(birthday.get("year")),
        "birth_year_quality": _quality(birthday.get("year_quality")),
        "birth_raw": _string(birthday.get("raw")),
        "anniversary_month": _integer(anniversary.get("month")),
        "anniversary_day": _integer(anniversary.get("day")),
        "anniversary_year": _integer(anniversary.get("year")),
        "anniversary_year_quality": _quality(
            anniversary.get("year_quality")
        ),
        "anniversary_raw": _string(anniversary.get("raw")),
    }
    if existing is None:
        existing = CRMContactProfile(contact_id=contact.id, **values)
        db.add(existing)
    else:
        for field_name, value in values.items():
            setattr(existing, field_name, value)
    return existing


async def _upsert_profile_children(
    db: AsyncSession,
    contact: CRMContact,
    source_record: CRMSourceRecord,
    draft: SourceRecordDraft,
) -> None:
    for kind, raw_value in (
        ("email", _string(draft.payload.get("primary_email"))),
        ("phone", _string(draft.payload.get("primary_phone"))),
    ):
        if raw_value is None:
            continue
        source_key = f"{draft.source_key}:{kind}:primary"
        existing = await db.scalar(
            select(CRMContactMethod).where(
                CRMContactMethod.contact_id == contact.id,
                CRMContactMethod.source_key == source_key,
            )
        )
        normalized = (
            canonical_email(raw_value) if kind == "email" else canonical_phone(raw_value)
        )
        values = {
            "source_record_id": source_record.id,
            "kind": kind,
            "label": "primary",
            "raw_value": raw_value,
            "normalized_value": normalized,
            "is_primary": True,
        }
        if existing is None:
            db.add(CRMContactMethod(contact_id=contact.id, source_key=source_key, **values))
        else:
            for field_name, value in values.items():
                setattr(existing, field_name, value)

    raw_fields = _mapping(draft.payload.get("raw_fields"))
    structured = _mapping(raw_fields.get("structured"))
    owner = _mapping(structured.get("owner"))
    owner_id = _string(owner.get("id"))
    owner_name = _string(owner.get("name"))
    if owner_id or owner_name:
        source_key = f"{draft.source_key}:owner:primary"
        existing = await db.scalar(
            select(CRMContactOwnership).where(
                CRMContactOwnership.contact_id == contact.id,
                CRMContactOwnership.source_key == source_key,
            )
        )
        values = {
            "source_record_id": source_record.id,
            "role": "owner",
            "provider_actor_id": owner_id,
            "display_name": owner_name,
            "is_primary": True,
        }
        if existing is None:
            db.add(
                CRMContactOwnership(
                    contact_id=contact.id, source_key=source_key, **values
                )
            )
        else:
            for field_name, value in values.items():
                setattr(existing, field_name, value)

    for ordinal, relationship in enumerate(_mapping_sequence(structured.get("relationships")), 1):
        source_key = f"{draft.source_key}:relationship:{ordinal}"
        existing = await db.scalar(
            select(CRMContactRelationship).where(
                CRMContactRelationship.contact_id == contact.id,
                CRMContactRelationship.source_key == source_key,
            )
        )
        values = {
            "source_record_id": source_record.id,
            "relationship_type": _string(relationship.get("type")) or "other",
            "display_name": _string(relationship.get("name")),
            "related_source_contact_id": _provider_id(relationship.get("id")),
        }
        if existing is None:
            db.add(
                CRMContactRelationship(
                    contact_id=contact.id, source_key=source_key, **values
                )
            )
        else:
            for field_name, value in values.items():
                setattr(existing, field_name, value)

    for ordinal, custom_field in enumerate(_mapping_sequence(structured.get("customFields")), 1):
        key = _string(custom_field.get("name")) or _string(custom_field.get("id"))
        if key is None:
            continue
        source_key = f"{draft.source_key}:preference:{ordinal}"
        existing = await db.scalar(
            select(CRMContactPreference).where(
                CRMContactPreference.contact_id == contact.id,
                CRMContactPreference.source_key == source_key,
            )
        )
        values = {
            "source_record_id": source_record.id,
            "preference_key": key,
            "value_json": canonical_json_text(
                _json_value(custom_field.get("value"))
            ),
        }
        if existing is None:
            db.add(
                CRMContactPreference(
                    contact_id=contact.id, source_key=source_key, **values
                )
            )
        else:
            for field_name, value in values.items():
                setattr(existing, field_name, value)

    for ordinal, address in enumerate(_mapping_sequence(structured.get("addresses")), 1):
        source_key = f"{draft.source_key}:address:{ordinal}"
        existing = await db.scalar(
            select(CRMContactAddress).where(
                CRMContactAddress.contact_id == contact.id,
                CRMContactAddress.source_key == source_key,
            )
        )
        values = {
            "source_record_id": source_record.id,
            "address_type": _string(address.get("type")),
            "line1": _string(address.get("line1")) or _string(address.get("street")),
            "line2": _string(address.get("line2")),
            "city": _string(address.get("city")),
            "state": _string(address.get("state")),
            "postal_code": _string(address.get("postalCode")),
            "country": _string(address.get("country")),
            "formatted": _string(address.get("formatted")),
            "is_primary": ordinal == 1,
        }
        if existing is None:
            db.add(CRMContactAddress(contact_id=contact.id, source_key=source_key, **values))
        else:
            for field_name, value in values.items():
                setattr(existing, field_name, value)

    for ordinal, neighborhood in enumerate(_mapping_sequence(structured.get("neighborhoods")), 1):
        name = _string(neighborhood.get("name"))
        if name is None:
            continue
        source_key = f"{draft.source_key}:neighborhood:{ordinal}"
        existing = await db.scalar(
            select(CRMContactNeighborhood).where(
                CRMContactNeighborhood.contact_id == contact.id,
                CRMContactNeighborhood.source_key == source_key,
            )
        )
        values = {"source_record_id": source_record.id, "name": name}
        if existing is None:
            db.add(
                CRMContactNeighborhood(
                    contact_id=contact.id, source_key=source_key, **values
                )
            )
        else:
            for field_name, value in values.items():
                setattr(existing, field_name, value)


async def _upsert_positions(
    db: AsyncSession,
    records: Sequence[SourceRecordDraft],
    persisted: Mapping[tuple[str, str, str, str, str], CRMSourceRecord],
    source_to_contact: Mapping[str, CRMContact],
    bundle_fingerprint: str,
) -> dict[str, CRMContactCapturePosition]:
    existing_rows = (
        await db.scalars(
            select(CRMContactCapturePosition).where(
                CRMContactCapturePosition.bundle_fingerprint == bundle_fingerprint
            )
        )
    ).all()
    by_ordinal = {f"{row.capture_ordinal:07d}": row for row in existing_rows}
    for draft in records:
        if draft.record_kind != "contact_capture_position":
            continue
        ordinal = _ordinal(draft.payload.get("capture_ordinal"))
        source_id = _string(draft.payload.get("source_contact_id"))
        if source_id is None or source_id not in source_to_contact:
            raise ContactMaterializationError(
                "capture position references an unresolved recovered identity"
            )
        source_record = persisted.get(draft.identity)
        if source_record is None:
            raise ContactMaterializationError("capture position source is missing")
        contact = source_to_contact[source_id]
        existing = by_ordinal.get(f"{ordinal:07d}")
        values = {
            "contact_id": contact.id,
            "source_record_id": source_record.id,
            "source_contact_id": source_id,
            "captured_at": draft.captured_at,
            "capture_quality": draft.capture_quality.value,
            "limitations_json": "[]",
        }
        if existing is None:
            existing = CRMContactCapturePosition(
                bundle_fingerprint=bundle_fingerprint,
                capture_ordinal=ordinal,
                **values,
            )
            db.add(existing)
            by_ordinal[f"{ordinal:07d}"] = existing
        elif not _model_values_match(existing, values):
            raise ContactMaterializationError(
                "capture position changed for an existing bundle"
            )
    await db.flush()
    return by_ordinal


async def _upsert_sections(
    db: AsyncSession,
    records: Sequence[SourceRecordDraft],
    persisted: Mapping[tuple[str, str, str, str, str], CRMSourceRecord],
    positions: Mapping[str, CRMContactCapturePosition],
) -> None:
    position_ids = tuple(position.id for position in positions.values())
    existing_rows = (
        await db.scalars(
            select(CRMContactSectionCapture).where(
                CRMContactSectionCapture.capture_position_id.in_(position_ids)
            )
        )
    ).all()
    existing_by_key = {
        (row.capture_position_id, row.section_name): row for row in existing_rows
    }
    for draft in records:
        if draft.record_kind != "contact_section_capture":
            continue
        ordinal_string = f"{_ordinal(draft.payload.get('capture_ordinal')):07d}"
        section_name = _string(draft.payload.get("section_name"))
        if section_name not in CONTACT_SECTIONS or ordinal_string not in positions:
            raise ContactMaterializationError(
                "contact section references an invalid capture position"
            )
        source_record = persisted.get(draft.identity)
        if source_record is None:
            raise ContactMaterializationError("contact section source is missing")
        position = positions[ordinal_string]
        values = {
            "source_record_id": source_record.id,
            "captured_at": draft.captured_at,
            "capture_quality": draft.capture_quality.value,
            "is_empty": bool(draft.payload.get("is_empty", False)),
            "row_count": _nonnegative_integer(draft.payload.get("row_count")),
            "limitations_json": canonical_json_text(
                list(_string_sequence(draft.payload.get("limitations")))
            ),
        }
        existing = existing_by_key.get((position.id, section_name))
        if existing is None:
            existing = CRMContactSectionCapture(
                capture_position_id=position.id,
                section_name=section_name,
                **values,
            )
            db.add(existing)
            existing_by_key[(position.id, section_name)] = existing
        elif not _model_values_match(existing, values):
            raise ContactMaterializationError(
                "contact section changed for an existing capture"
            )


async def _materialize_occurrences(
    db: AsyncSession,
    records: Sequence[SourceRecordDraft],
    persisted: Mapping[tuple[str, str, str, str, str], CRMSourceRecord],
    source_to_contact: Mapping[str, CRMContact],
) -> int:
    links_created = 0
    for draft in records:
        if draft.record_kind not in {
            "contact_timeline_event",
            "contact_note",
            "contact_saved_search",
        }:
            continue
        source_id = _string(draft.payload.get("source_contact_id"))
        source_record = persisted.get(draft.identity)
        if source_id is None or source_id not in source_to_contact or source_record is None:
            raise ContactMaterializationError(
                "contact occurrence references a missing recovered source"
            )
        contact = source_to_contact[source_id]
        entity_type = {
            "contact_timeline_event": "contact_timeline_event",
            "contact_note": "note",
            "contact_saved_search": "saved_search",
        }[draft.record_kind]
        values = _mapping(draft.payload.get("values"))
        existing_links = (
            await db.scalars(
                select(CRMEntitySource)
                .where(CRMEntitySource.source_record_id == source_record.id)
                .execution_options(populate_existing=True)
            )
        ).all()
        if existing_links:
            if (
                len(existing_links) != 1
                or existing_links[0].entity_type != entity_type
            ):
                raise ContactMaterializationError(
                    "an existing contact child link has a conflicting entity type"
                )
            await _validate_existing_child_link(
                db,
                existing_links[0],
                draft,
                values,
                contact,
                source_record,
            )
            continue
        if draft.record_kind == "contact_note":
            raw_lines = _string_sequence(values.get("raw_lines"))
            body = _string(values.get("body")) or "\n".join(raw_lines)
            if not body:
                continue
            entity = CRMNote(contact_id=contact.id, body=body)
        elif draft.record_kind == "contact_saved_search":
            name = _string(values.get("name")) or draft.display_label
            entity = CRMSavedSearch(
                contact_id=contact.id,
                name=name,
                criteria_json=canonical_json_text(_json_value(values)),
            )
        else:
            occurred_at = _event_datetime(values)
            raw_lines = _string_sequence(values.get("raw_lines"))
            kind = _string(values.get("kind")) or "CONTACT"
            entity = CRMContactTimelineEvent(
                contact_id=contact.id,
                source_record_id=source_record.id,
                source_system="kw_command",
                source_event_key=draft.source_key,
                kind=kind.casefold(),
                outcome=_string(values.get("outcome")),
                title=draft.display_label,
                body="\n".join(raw_lines) or None,
                actor_label=_string(values.get("actor_label")),
                channel=_string(values.get("channel")),
                occurred_at=occurred_at,
                attributes_json=canonical_json_text(_json_value(values)),
            )
        db.add(entity)
        await db.flush()
        db.add(
            CRMEntitySource(
                entity_type=entity_type,
                entity_id=entity.id,
                source_record_id=source_record.id,
            )
        )
        links_created += 1
    return links_created


async def _validate_existing_child_link(
    db: AsyncSession,
    link: CRMEntitySource,
    draft: SourceRecordDraft,
    values: Mapping[str, object],
    contact: CRMContact,
    source_record: CRMSourceRecord,
) -> None:
    if draft.record_kind == "contact_note":
        entity = await db.get(CRMNote, link.entity_id, populate_existing=True)
        raw_lines = _string_sequence(values.get("raw_lines"))
        expected_body = _string(values.get("body")) or "\n".join(raw_lines)
        if (
            entity is None
            or not expected_body
            or entity.contact_id != contact.id
            or entity.body != expected_body
        ):
            raise ContactMaterializationError(
                "an existing contact child link conflicts with its note source"
            )
        return

    if draft.record_kind == "contact_saved_search":
        entity = await db.get(CRMSavedSearch, link.entity_id, populate_existing=True)
        expected_name = _string(values.get("name")) or draft.display_label
        expected_criteria = canonical_json_text(_json_value(values))
        if (
            entity is None
            or entity.contact_id != contact.id
            or entity.name != expected_name
            or entity.criteria_json != expected_criteria
        ):
            raise ContactMaterializationError(
                "an existing contact child link conflicts with its saved-search source"
            )
        return

    entity = await db.get(
        CRMContactTimelineEvent,
        link.entity_id,
        populate_existing=True,
    )
    occurred_at = _event_datetime(values)
    raw_lines = _string_sequence(values.get("raw_lines"))
    expected_kind = (_string(values.get("kind")) or "CONTACT").casefold()
    if (
        entity is None
        or entity.contact_id != contact.id
        or entity.source_record_id != source_record.id
        or entity.source_system != "kw_command"
        or entity.source_event_key != draft.source_key
        or entity.kind != expected_kind
        or entity.outcome != _string(values.get("outcome"))
        or entity.title != draft.display_label
        or entity.body != ("\n".join(raw_lines) or None)
        or entity.actor_label != _string(values.get("actor_label"))
        or entity.channel != _string(values.get("channel"))
        or not _same_datetime(entity.occurred_at, occurred_at)
        or entity.attributes_json
        != canonical_json_text(_json_value(values))
    ):
        raise ContactMaterializationError(
            "an existing contact child link conflicts with its timeline source"
        )


async def _has_reviewed_overlap(
    db: AsyncSession,
    contact_id: int,
    identity_hash: str,
) -> bool:
    audits = (
        await db.scalars(
            select(CRMContactAuditEvent).where(
                CRMContactAuditEvent.contact_id == contact_id,
                CRMContactAuditEvent.action == "command_contact_overlap_reviewed",
            )
        )
    ).all()
    for audit in audits:
        try:
            payload = json.loads(audit.after_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and (
            payload.get("source_provider_identity_hash") == identity_hash
        ):
            return True
    return False


def _event_datetime(
    values: Mapping[str, object],
) -> datetime | None:
    explicit = values.get("occurred_at")
    if isinstance(explicit, str):
        try:
            parsed = datetime.fromisoformat(explicit.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    return None


def _same_datetime(first: datetime | None, second: datetime | None) -> bool:
    if first is None or second is None:
        return first is second
    if first.tzinfo is None:
        first = first.replace(tzinfo=UTC)
    if second.tzinfo is None:
        second = second.replace(tzinfo=UTC)
    return first.astimezone(UTC) == second.astimezone(UTC)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _integer(value: object) -> int | None:
    return value if type(value) is int else None


def _nonnegative_integer(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


def _quality(value: object) -> str:
    return (
        value
        if isinstance(value, str)
        and value in {"verified", "yearless", "sentinel", "unknown"}
        else "unknown"
    )


def _ordinal(value: object) -> int:
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    raise ContactMaterializationError("capture ordinal is invalid")


def _provider_id(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{24}", value) else None


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def _model_values_match(model: object, values: Mapping[str, object]) -> bool:
    for field_name, expected in values.items():
        actual = getattr(model, field_name)
        if isinstance(actual, datetime) and isinstance(expected, datetime):
            actual_value = actual.replace(tzinfo=actual.tzinfo or UTC).astimezone(UTC)
            expected_value = expected.replace(
                tzinfo=expected.tzinfo or UTC
            ).astimezone(UTC)
            if actual_value != expected_value:
                return False
        elif actual != expected:
            return False
    return True


__all__ = ("ContactMaterializationError", "ContactMaterializer")
