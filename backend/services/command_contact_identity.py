"""Deterministic strong-identifier resolution for recovered Command contacts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import re
from typing import Literal
import unicodedata


_PLACEHOLDERS = frozenset({"", "--", "—", "n/a", "none", "null"})
_SOURCE_HASH_VERSION = "contacts-v1"
_E164_PATTERN = re.compile(r"\+[1-9][0-9]{7,14}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class IdentityConflict(ValueError):
    """Raised when strong identity evidence conflicts across source contacts."""

    def __init__(self, reason: str, source_contact_ids: Sequence[str]) -> None:
        self.source_contact_ids = tuple(sorted(source_contact_ids))
        self.ambiguous_identities = 1
        self.evidence_hashes = tuple(
            _provider_evidence_hash(source_contact_id)
            for source_contact_id in self.source_contact_ids
        )
        evidence_digest = hashlib.sha256(
            "\n".join(self.evidence_hashes).encode("utf-8")
        ).hexdigest()
        super().__init__(
            f"identity conflict: {reason}; ambiguous_identities=1; "
            f"evidence_count={len(self.evidence_hashes)}; "
            f"evidence_hashes={evidence_digest}"
        )


@dataclass(frozen=True, slots=True)
class ContactIdentityCandidate:
    source_contact_id: str
    primary_email: str | None
    e164_phone: str | None
    legal_name: str | None
    preferred_name: str | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_contact_id, str)
            or not self.source_contact_id.strip()
        ):
            raise ValueError("source_contact_id must be nonblank")
        for field_name in (
            "primary_email",
            "e164_phone",
            "legal_name",
            "preferred_name",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string or None")


@dataclass(frozen=True, slots=True)
class ContactIdentityCluster:
    identity_hash: str
    resolution_method: Literal["email", "phone", "provider_id"]
    source_contact_ids: Sequence[str]

    def __post_init__(self) -> None:
        if not isinstance(self.identity_hash, str) or not _SHA256_PATTERN.fullmatch(
            self.identity_hash
        ):
            raise ValueError("identity_hash must be a lowercase SHA-256 digest")
        if self.resolution_method not in {"email", "phone", "provider_id"}:
            raise ValueError("resolution_method is invalid")
        if isinstance(self.source_contact_ids, str | bytes):
            raise TypeError("source_contact_ids must be a sequence of IDs")
        source_contact_ids = tuple(sorted(self.source_contact_ids))
        if not source_contact_ids or any(
            not isinstance(value, str) or not value.strip()
            for value in source_contact_ids
        ):
            raise ValueError("source_contact_ids must contain nonblank IDs")
        if len(source_contact_ids) != len(set(source_contact_ids)):
            raise ValueError("source_contact_ids must be unique")
        object.__setattr__(self, "source_contact_ids", source_contact_ids)


@dataclass(frozen=True, slots=True)
class _CanonicalCandidate:
    source_contact_id: str
    email: str | None
    phone: str | None
    names: frozenset[str]


def canonical_email(value: str | None) -> str | None:
    """Return a case-folded explicit email or None for invalid/placeholders."""
    normalized = _normalized_text(value)
    if (
        normalized is None
        or normalized.count("@") != 1
        or any(character.isspace() for character in normalized)
    ):
        return None
    local, domain = normalized.split("@", 1)
    if not local or not domain or domain.startswith(".") or domain.endswith("."):
        return None
    return normalized


def canonical_phone(value: str | None) -> str | None:
    """Return only an explicitly supplied E.164 number; never assume a country."""
    normalized = _normalized_text(value)
    if normalized is None or _E164_PATTERN.fullmatch(normalized) is None:
        return None
    return normalized


def resolve_identity_clusters(
    candidates: Sequence[ContactIdentityCandidate],
) -> tuple[ContactIdentityCluster, ...]:
    """Resolve source rows through explicit email/phone edges, never names alone."""
    if isinstance(candidates, str | bytes) or not isinstance(candidates, Sequence):
        raise TypeError("candidates must be a sequence")
    materialized = tuple(candidates)
    if any(not isinstance(value, ContactIdentityCandidate) for value in materialized):
        raise TypeError("candidates must contain ContactIdentityCandidate values")

    by_source: dict[str, ContactIdentityCandidate] = {}
    for candidate in materialized:
        source_contact_id = candidate.source_contact_id.strip()
        if source_contact_id in by_source:
            raise IdentityConflict(
                "duplicate provider contact ID",
                (source_contact_id,),
            )
        by_source[source_contact_id] = candidate

    canonical = tuple(
        _canonical_candidate(source_contact_id, by_source[source_contact_id])
        for source_contact_id in sorted(by_source)
    )
    parents = list(range(len(canonical)))

    email_groups: dict[str, list[int]] = defaultdict(list)
    phone_groups: dict[str, list[int]] = defaultdict(list)
    for index, canonical_candidate in enumerate(canonical):
        if canonical_candidate.email is not None:
            email_groups[canonical_candidate.email].append(index)
        if canonical_candidate.phone is not None:
            phone_groups[canonical_candidate.phone].append(index)

    for indexes in email_groups.values():
        _require_compatible_names(canonical, indexes)
        phones = {canonical[index].phone for index in indexes} - {None}
        if len(phones) > 1:
            _raise_conflict("conflicting phone", canonical, indexes)
        _union_group(parents, indexes)

    for indexes in phone_groups.values():
        emails = {canonical[index].email for index in indexes} - {None}
        if len(emails) > 1:
            _raise_conflict("conflicting email", canonical, indexes)
        email_less_indexes = tuple(
            index for index in indexes if canonical[index].email is None
        )
        _require_compatible_names(canonical, email_less_indexes)
        _union_group(parents, email_less_indexes)

    resolved_groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(canonical)):
        resolved_groups[_find(parents, index)].append(index)

    sortable: list[tuple[int, str, ContactIdentityCluster]] = []
    method_order = {"email": 0, "phone": 1, "provider_id": 2}
    for indexes in resolved_groups.values():
        sources = tuple(canonical[index].source_contact_id for index in indexes)
        emails = {canonical[index].email for index in indexes} - {None}
        phones = {canonical[index].phone for index in indexes} - {None}
        if len(emails) > 1:
            _raise_conflict("conflicting email", canonical, indexes)
        if emails:
            method: Literal["email", "phone", "provider_id"] = "email"
            identity_value = next(iter(emails))
        elif phones:
            method = "phone"
            identity_value = next(iter(phones))
        else:
            method = "provider_id"
            identity_value = sources[0]
        assert identity_value is not None
        cluster = ContactIdentityCluster(
            identity_hash=_identity_hash(method, identity_value),
            resolution_method=method,
            source_contact_ids=sources,
        )
        sortable.append((method_order[method], identity_value, cluster))

    return tuple(cluster for _, _, cluster in sorted(sortable))


def redacted_cluster_membership_hash(cluster: ContactIdentityCluster) -> str:
    """Hash one identity partition without exposing its provider source IDs."""
    if not isinstance(cluster, ContactIdentityCluster):
        raise TypeError("cluster must be a ContactIdentityCluster")
    evidence_hashes = tuple(
        _provider_evidence_hash(source_contact_id)
        for source_contact_id in cluster.source_contact_ids
    )
    canonical = "\0".join(
        (
            _SOURCE_HASH_VERSION,
            "cluster-membership",
            cluster.identity_hash,
            *evidence_hashes,
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_candidate(
    source_contact_id: str,
    candidate: ContactIdentityCandidate,
) -> _CanonicalCandidate:
    names = frozenset(
        normalized
        for value in (candidate.legal_name, candidate.preferred_name)
        if (normalized := _canonical_name(value)) is not None
    )
    return _CanonicalCandidate(
        source_contact_id=source_contact_id,
        email=canonical_email(candidate.primary_email),
        phone=canonical_phone(candidate.e164_phone),
        names=names,
    )


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("identity values must be strings or None")
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return None if normalized in _PLACEHOLDERS else normalized


def _canonical_name(value: str | None) -> str | None:
    normalized = _normalized_text(value)
    return " ".join(normalized.split()) if normalized is not None else None


def _require_compatible_names(
    candidates: tuple[_CanonicalCandidate, ...],
    indexes: Sequence[int],
) -> None:
    for offset, left_index in enumerate(indexes):
        left_names = candidates[left_index].names
        if not left_names:
            continue
        for right_index in indexes[offset + 1 :]:
            right_names = candidates[right_index].names
            if right_names and left_names.isdisjoint(right_names):
                _raise_conflict(
                    "conflicting name",
                    candidates,
                    (left_index, right_index),
                )


def _raise_conflict(
    reason: str,
    candidates: tuple[_CanonicalCandidate, ...],
    indexes: Sequence[int],
) -> None:
    source_ids = tuple(candidates[index].source_contact_id for index in indexes)
    raise IdentityConflict(reason, source_ids)


def _provider_evidence_hash(source_contact_id: str) -> str:
    canonical = f"{_SOURCE_HASH_VERSION}\0provider-evidence\0{source_contact_id}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _find(parents: list[int], index: int) -> int:
    while parents[index] != index:
        parents[index] = parents[parents[index]]
        index = parents[index]
    return index


def _union_group(parents: list[int], indexes: Sequence[int]) -> None:
    if not indexes:
        return
    root = _find(parents, indexes[0])
    for index in indexes[1:]:
        other = _find(parents, index)
        if other != root:
            parents[other] = root


def _identity_hash(
    resolution_method: Literal["email", "phone", "provider_id"],
    identity_value: str,
) -> str:
    canonical = f"{_SOURCE_HASH_VERSION}\0{resolution_method}\0{identity_value}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = (
    "ContactIdentityCandidate",
    "ContactIdentityCluster",
    "IdentityConflict",
    "canonical_email",
    "canonical_phone",
    "redacted_cluster_membership_hash",
    "resolve_identity_clusters",
)
