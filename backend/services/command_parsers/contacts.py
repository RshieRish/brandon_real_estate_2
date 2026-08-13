"""Deterministic parser for recovered Command contact profiles and views."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
import json
import re

from models.command_provenance import CaptureQuality, EvidenceLevel
from services.command_parsers.base import ModuleMetrics, ModuleParseResult
from services.command_parsers.contact_extractors import (
    CONTACT_SECTIONS,
    SECTION_RELATIVE_PATHS,
    ContactParseError,
    ParsedCelebration,
    ParsedContactProfile,
    ParsedOccurrence,
    ParsedSection,
    canonical_occurrence_key,
    parse_contact_profile,
    parse_section_capture,
)
from services.command_provenance import (
    ArchiveArtifactInput,
    SourceRecordDraft,
    verify_artifact_bytes,
)


_CONTACT_ROOT = "kw_command_repaired/contacts"
_ORDINAL_PATTERN = re.compile(
    rf"^{_CONTACT_ROOT}/sections/(\d{{7}})/(?:"
    + "|".join(re.escape(path) for path in SECTION_RELATIVE_PATHS.values())
    + r")$"
)


class ContactsParser:
    """Parse provider rows, positions, eight sections, and exposed child rows."""

    module = "contacts"

    def parse(
        self,
        artifacts: Sequence[ArchiveArtifactInput],
        parser_version: str,
    ) -> ModuleParseResult:
        if not isinstance(parser_version, str) or not parser_version.strip():
            raise ContactParseError("parser_version must be nonblank")
        artifacts_by_path: dict[str, ArchiveArtifactInput] = {}
        relevant: list[ArchiveArtifactInput] = []
        for artifact in artifacts:
            if not isinstance(artifact, ArchiveArtifactInput):
                raise ContactParseError(
                    "artifacts must contain only ArchiveArtifactInput values"
                )
            if not artifact.source_path.startswith(f"{_CONTACT_ROOT}/"):
                continue
            verify_artifact_bytes(artifact)
            if artifact.source_path in artifacts_by_path:
                raise ContactParseError(
                    f"duplicate artifact path: {artifact.source_path}"
                )
            artifacts_by_path[artifact.source_path] = artifact
            relevant.append(artifact)

        ordinal_strings = {
            match.group(1)
            for artifact in relevant
            if (match := _ORDINAL_PATTERN.fullmatch(artifact.source_path))
        }
        if not ordinal_strings:
            raise ContactParseError("contact archive contains no canonical sections")

        records: list[SourceRecordDraft] = []
        section_counts: Counter[str] = Counter()
        for ordinal_string in sorted(ordinal_strings):
            ordinal = int(ordinal_string)
            expected = {
                section: (
                    f"{_CONTACT_ROOT}/sections/{ordinal_string}/"
                    f"{SECTION_RELATIVE_PATHS[section]}"
                )
                for section in CONTACT_SECTIONS
            }
            for section, path in expected.items():
                if path not in artifacts_by_path:
                    raise ContactParseError(
                        f"missing canonical section for position {ordinal_string}: "
                        f"{section} ({path})"
                    )

            profile = parse_contact_profile(ordinal, artifacts_by_path)
            parsed_sections = tuple(
                parse_section_capture(
                    profile,
                    section,
                    artifacts_by_path[expected[section]],
                )
                for section in CONTACT_SECTIONS
            )
            parsed_sections = tuple(
                _associate_stable_note_evidence(profile, section, artifacts_by_path)
                for section in parsed_sections
            )
            records.append(_profile_draft(profile, parser_version))
            section_evidence = {
                section.section: _section_evidence_paths(
                    section.artifact_path, artifacts_by_path
                )
                for section in parsed_sections
            }
            records.append(
                _position_draft(
                    profile,
                    parsed_sections,
                    tuple(
                        sorted(
                            {
                                path
                                for paths in section_evidence.values()
                                for path in paths
                            }
                        )
                    ),
                    parser_version,
                )
            )
            for parsed_section in parsed_sections:
                section_counts[parsed_section.section] += 1
                artifact_paths = section_evidence[parsed_section.section]
                records.append(
                    _section_draft(
                        profile, parsed_section, artifact_paths, parser_version
                    )
                )
                records.extend(
                    _occurrence_drafts(
                        profile, parsed_section, artifact_paths, parser_version
                    )
                )

        supporting_hashes: set[str] = set()
        duplicate_supporting_body_count = 0
        for artifact in sorted(relevant, key=lambda value: value.source_path):
            if not _is_supporting_artifact(artifact.source_path):
                continue
            if artifact.sha256 in supporting_hashes:
                duplicate_supporting_body_count += 1
            else:
                supporting_hashes.add(artifact.sha256)

        position_count = len(ordinal_strings)
        section_count = sum(section_counts.values())
        return ModuleParseResult(
            records=tuple(records),
            metrics=ModuleMetrics(
                source_system="kw_command",
                module=self.module,
                expected_count=317,
                observed_count=position_count,
                rendered_count=position_count,
                normalized_count=0,
                evidence_only_count=0,
                unmatched_count=0,
                duplicate_content_count=duplicate_supporting_body_count,
                error_count=0,
                details={
                    "provider_contact_rows": position_count,
                    "capture_positions": position_count,
                    "section_artifacts": section_count,
                    "section_counts": {
                        section: section_counts[section] for section in CONTACT_SECTIONS
                    },
                    "fabricated_celebrations": 0,
                },
            ),
        )


def _profile_draft(
    profile: ParsedContactProfile,
    parser_version: str,
) -> SourceRecordDraft:
    return SourceRecordDraft(
        source_system="kw_command",
        module="contacts",
        record_kind="contact_profile",
        source_key=f"contact:{profile.source_contact_id}",
        evidence_level=EvidenceLevel.OBSERVED_RECORD,
        display_label=profile.display_name,
        payload={
            "source_contact_id": profile.source_contact_id,
            "capture_ordinal": profile.capture_ordinal,
            "source_url": profile.source_url,
            "display_name": profile.display_name,
            "legal_name": profile.legal_name,
            "preferred_name": profile.preferred_name,
            "primary_email": profile.primary_email,
            "primary_phone": profile.primary_phone,
            "birthday": _celebration_payload(profile.birthday),
            "anniversary": _celebration_payload(profile.anniversary),
            "identity_candidate": {
                "source_contact_id": profile.source_contact_id,
                "primary_email": profile.primary_email,
                "e164_phone": profile.primary_phone,
                "legal_name": profile.legal_name,
                "preferred_name": profile.preferred_name,
            },
            "profile_source": profile.profile_source,
            "raw_fields": profile.raw_fields,
        },
        artifact_paths=profile.artifact_paths,
        parser_version=parser_version,
        capture_quality=profile.capture_quality,
        captured_at=profile.captured_at,
    )


def _position_draft(
    profile: ParsedContactProfile,
    sections: tuple[ParsedSection, ...],
    artifact_paths: tuple[str, ...],
    parser_version: str,
) -> SourceRecordDraft:
    quality = _lowest_quality(section.capture_quality for section in sections)
    return SourceRecordDraft(
        source_system="kw_command",
        module="contacts",
        record_kind="contact_capture_position",
        source_key=f"position:{profile.capture_ordinal}",
        evidence_level=EvidenceLevel.RENDERED_OCCURRENCE,
        display_label=f"{profile.display_name} · position {profile.capture_ordinal}",
        payload={
            "capture_ordinal": profile.capture_ordinal,
            "source_contact_id": profile.source_contact_id,
            "source_url": profile.source_url,
            "section_names": CONTACT_SECTIONS,
        },
        artifact_paths=artifact_paths,
        parser_version=parser_version,
        capture_quality=quality,
        captured_at=profile.captured_at,
    )


def _section_draft(
    profile: ParsedContactProfile,
    section: ParsedSection,
    artifact_paths: tuple[str, ...],
    parser_version: str,
) -> SourceRecordDraft:
    return SourceRecordDraft(
        source_system="kw_command",
        module="contacts",
        record_kind="contact_section_capture",
        source_key=(f"position:{profile.capture_ordinal}:section:{section.section}"),
        evidence_level=EvidenceLevel.RENDERED_OCCURRENCE,
        display_label=(
            f"{profile.display_name} · {section.section.replace('_', ' ').title()}"
        ),
        payload={
            "capture_ordinal": profile.capture_ordinal,
            "source_contact_id": profile.source_contact_id,
            "section_name": section.section,
            "text_source": section.text_source,
            "exposed_text": section.exposed_text,
            "is_empty": section.is_empty,
            "row_count": len(section.occurrences),
            "limitations": section.limitations,
            "raw_fields": section.raw_fields,
        },
        artifact_paths=artifact_paths,
        parser_version=parser_version,
        capture_quality=section.capture_quality,
        captured_at=section.captured_at,
    )


def _occurrence_drafts(
    profile: ParsedContactProfile,
    section: ParsedSection,
    artifact_paths: tuple[str, ...],
    parser_version: str,
) -> tuple[SourceRecordDraft, ...]:
    values = []
    for ordinal, occurrence in enumerate(section.occurrences, start=1):
        suffix = occurrence.stable_id or canonical_occurrence_key(
            occurrence.values, ordinal
        )
        source_key, record_kind = _occurrence_identity(
            profile.source_contact_id,
            section.section,
            suffix,
        )
        evidence = (
            EvidenceLevel.OBSERVED_RECORD
            if section.section == "notes" and occurrence.stable_id is not None
            else EvidenceLevel.RENDERED_OCCURRENCE
        )
        values.append(
            SourceRecordDraft(
                source_system="kw_command",
                module="contacts",
                record_kind=record_kind,
                source_key=source_key,
                evidence_level=evidence,
                display_label=occurrence.display_label,
                payload={
                    "capture_ordinal": profile.capture_ordinal,
                    "source_contact_id": profile.source_contact_id,
                    "section_name": section.section,
                    "occurrence_ordinal": ordinal,
                    "stable_id": occurrence.stable_id,
                    "state": (
                        section.section.removeprefix("tasks_")
                        if section.section.startswith("tasks_")
                        else None
                    ),
                    "values": occurrence.values,
                },
                artifact_paths=artifact_paths,
                parser_version=parser_version,
                capture_quality=section.capture_quality,
                captured_at=section.captured_at,
            )
        )
    return tuple(values)


def _occurrence_identity(
    source_contact_id: str,
    section: str,
    suffix: str,
) -> tuple[str, str]:
    prefix = f"contact:{source_contact_id}"
    if section == "timeline":
        return f"{prefix}:timeline:{suffix}", "contact_timeline_event"
    if section == "notes":
        return f"{prefix}:note:{suffix}", "contact_note"
    if section == "saved_searches":
        return f"{prefix}:saved-search:{suffix}", "contact_saved_search"
    if section.startswith("tasks_"):
        state = section.removeprefix("tasks_")
        return f"{prefix}:task:{state}:{suffix}", "contact_task"
    if section == "smart_plans":
        return f"{prefix}:smart-plan:{suffix}", "contact_smart_plan"
    if section == "opportunities":
        return f"{prefix}:opportunity:{suffix}", "contact_opportunity"
    raise ContactParseError(f"unknown child occurrence section: {section}")


def _celebration_payload(value: ParsedCelebration) -> Mapping[str, object]:
    return {
        "month": value.month,
        "day": value.day,
        "year": value.year,
        "year_quality": value.year_quality,
        "raw": value.raw,
    }


def _lowest_quality(qualities: Iterable[CaptureQuality]) -> CaptureQuality:
    rank = {
        CaptureQuality.COMPLETE: 0,
        CaptureQuality.PARTIAL: 1,
        CaptureQuality.SHELL: 2,
        CaptureQuality.ERROR: 3,
    }
    return max(tuple(qualities), key=rank.__getitem__)


def _is_supporting_artifact(source_path: str) -> bool:
    if "/details/" in source_path and source_path.endswith(".html"):
        return True
    if "/sections/" not in source_path:
        return False
    return source_path.endswith((".html", ".txt", ".snapshot.txt"))


def _section_evidence_paths(
    canonical_path: str,
    artifacts: Mapping[str, ArchiveArtifactInput],
) -> tuple[str, ...]:
    if not canonical_path.endswith(".json"):
        raise ContactParseError(
            f"canonical section artifact must be JSON: {canonical_path}"
        )
    stem = canonical_path.removesuffix(".json")
    candidates = [
        f"{stem}.html",
        canonical_path,
        f"{stem}.snapshot.txt",
        f"{stem}.txt",
    ]
    section_match = re.fullmatch(
        rf"{_CONTACT_ROOT}/sections/(\d{{7}})/(notes|timeline)\.json",
        canonical_path,
    )
    if section_match:
        ordinal, nested_name = section_match.groups()
        candidates.append(f"{_CONTACT_ROOT}/nested/{ordinal}/{nested_name}.json")
    return tuple(sorted(path for path in candidates if path in artifacts))


def _associate_stable_note_evidence(
    profile: ParsedContactProfile,
    section: ParsedSection,
    artifacts: Mapping[str, ArchiveArtifactInput],
) -> ParsedSection:
    if section.section != "notes" or not section.occurrences:
        return section
    nested_path = f"{_CONTACT_ROOT}/nested/{profile.capture_ordinal}/notes.json"
    artifact = artifacts.get(nested_path)
    if artifact is None or artifact.content_bytes is None:
        return section
    try:
        payload = json.loads(artifact.content_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContactParseError(
            f"invalid structured note artifact: {nested_path}"
        ) from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise ContactParseError(f"invalid structured note payload: {nested_path}")
    raw_data = payload["data"]
    assert isinstance(raw_data, list)
    candidates: list[tuple[str, tuple[str, ...]]] = []
    for raw_note in raw_data:
        if not isinstance(raw_note, Mapping):
            raise ContactParseError(f"invalid structured note row: {nested_path}")
        stable_id = raw_note.get("id")
        if not isinstance(stable_id, str) or not stable_id.strip():
            continue
        matching_values = tuple(
            normalized
            for key in ("title", "note")
            if isinstance((value := raw_note.get(key)), str)
            and (normalized := _normalized_evidence_value(value))
        )
        if matching_values:
            candidates.append((stable_id.strip(), matching_values))

    unused = set(range(len(candidates)))
    associated: list[ParsedOccurrence] = []
    for occurrence in section.occurrences:
        if occurrence.stable_id is not None:
            associated.append(occurrence)
            continue
        raw_lines = occurrence.values.get("raw_lines", ())
        if not isinstance(raw_lines, Sequence) or isinstance(raw_lines, str | bytes):
            raw_lines = ()
        observed_values = {_normalized_evidence_value(occurrence.display_label)}
        observed_values.update(
            _normalized_evidence_value(value)
            for value in raw_lines
            if isinstance(value, str)
        )
        observed_values.discard("")
        matches = [
            index
            for index in sorted(unused)
            if any(value in observed_values for value in candidates[index][1])
        ]
        if len(matches) == 1:
            match = matches[0]
            unused.remove(match)
            associated.append(replace(occurrence, stable_id=candidates[match][0]))
        else:
            associated.append(occurrence)
    return replace(section, occurrences=tuple(associated))


def _normalized_evidence_value(value: str) -> str:
    return " ".join(value.casefold().split())
