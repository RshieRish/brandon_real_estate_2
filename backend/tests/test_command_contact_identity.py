"""Pure deterministic identity-resolution tests for recovered contacts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib

import pytest

from services.command_contact_identity import (
    ContactIdentityCandidate,
    ContactIdentityCluster,
    IdentityConflict,
    canonical_email,
    canonical_phone,
    redacted_cluster_membership_hash,
    resolve_identity_clusters,
)


def profile(
    source_contact_id: str,
    *,
    email: str | None = None,
    phone: str | None = None,
    legal_name: str | None = None,
    preferred_name: str | None = None,
) -> ContactIdentityCandidate:
    return ContactIdentityCandidate(
        source_contact_id=source_contact_id,
        primary_email=email,
        e164_phone=phone,
        legal_name=legal_name,
        preferred_name=preferred_name,
    )


def test_same_email_and_compatible_names_form_one_cluster():
    clusters = resolve_identity_clusters(
        (
            profile("a", email="Avery@Example.com", legal_name="Avery Lake"),
            profile("b", email="avery@example.com", legal_name="Avery Lake"),
        )
    )

    assert [cluster.source_contact_ids for cluster in clusters] == [("a", "b")]
    assert clusters[0].resolution_method == "email"


def test_same_name_without_strong_identifier_never_merges():
    clusters = resolve_identity_clusters(
        (
            profile("a", legal_name="Jordan Lee"),
            profile("b", legal_name="Jordan Lee"),
        )
    )

    assert len(clusters) == 2
    assert {cluster.source_contact_ids for cluster in clusters} == {("a",), ("b",)}
    assert {cluster.resolution_method for cluster in clusters} == {"provider_id"}


def test_shared_email_with_conflicting_phone_blocks_apply():
    with pytest.raises(IdentityConflict, match="conflicting phone") as captured:
        resolve_identity_clusters(
            (
                profile(
                    "a",
                    email="a@example.com",
                    phone="+19785550101",
                    legal_name="Avery Lake",
                ),
                profile(
                    "b",
                    email="a@example.com",
                    phone="+19785550102",
                    legal_name="Avery Lake",
                ),
            )
        )

    assert captured.value.ambiguous_identities == 1
    assert len(captured.value.evidence_hashes) == 2
    assert not hasattr(captured.value, "source_contact_ids")


def test_identity_conflict_text_is_redacted_and_keeps_auditable_count():
    first_source_id = "aaaaaaaaaaaaaaaaaaaaaaaa"
    second_source_id = "bbbbbbbbbbbbbbbbbbbbbbbb"

    with pytest.raises(IdentityConflict) as captured:
        resolve_identity_clusters(
            (
                profile(
                    first_source_id,
                    email="shared@example.test",
                    phone="+19785550101",
                ),
                profile(
                    second_source_id,
                    email="shared@example.test",
                    phone="+19785550102",
                ),
            )
        )

    message = str(captured.value)
    assert captured.value.ambiguous_identities == 1
    assert captured.value.reason == "conflicting_phone"
    assert captured.value.resolution_method == "email"
    assert "ambiguous_identities=1" in message
    assert "evidence_hashes=" in message
    non_callable_attributes = {
        name: value
        for name in dir(captured.value)
        if not callable(value := getattr(captured.value, name))
    }
    retained_state = repr(
        (
            captured.value,
            captured.value.args,
            vars(captured.value),
            non_callable_attributes,
        )
    )
    assert first_source_id not in retained_state
    assert second_source_id not in retained_state
    assert not hasattr(captured.value, "source_contact_ids")


def test_non_e164_phone_is_preserved_but_not_used_as_merge_key():
    assert canonical_phone("978-555-0101") is None
    assert canonical_phone("+1 978 555 0101") is None
    clusters = resolve_identity_clusters(
        (
            profile("a", phone="978-555-0101", legal_name="Avery Lake"),
            profile("b", phone="978-555-0101", legal_name="Avery Lake"),
        )
    )
    assert {cluster.source_contact_ids for cluster in clusters} == {("a",), ("b",)}


@pytest.mark.parametrize("value", [None, "", "  ", "--", "—", "N/A", "None", "null"])
def test_placeholder_identifiers_are_null(value):
    assert canonical_email(value) is None
    assert canonical_phone(value) is None


def test_email_and_names_use_unicode_case_and_whitespace_normalization():
    assert (
        canonical_email("  ＡＶＥＲＹ＠Ｅｘａｍｐｌｅ．ＣＯＭ  ") == "avery@example.com"
    )
    clusters = resolve_identity_clusters(
        (
            profile(
                "a",
                email="ＡＶＥＲＹ＠Ｅｘａｍｐｌｅ．ＣＯＭ",
                legal_name="Jose\u0301   Nun\u0303ez",
            ),
            profile(
                "b",
                email="avery@example.com",
                preferred_name="JOSÉ NUÑEZ",
            ),
        )
    )
    assert clusters[0].source_contact_ids == ("a", "b")


def test_compatible_missing_names_and_phones_do_not_block_email_cluster():
    clusters = resolve_identity_clusters(
        (
            profile("a", email="avery@example.com", legal_name="Avery Lake"),
            profile("b", email="avery@example.com"),
        )
    )
    assert clusters[0].source_contact_ids == ("a", "b")


def test_incompatible_names_on_same_email_block_apply():
    with pytest.raises(IdentityConflict, match="conflicting name"):
        resolve_identity_clusters(
            (
                profile("a", email="shared@example.com", legal_name="Avery Lake"),
                profile("b", email="shared@example.com", legal_name="Jordan Reed"),
            )
        )


def test_emailless_candidates_cluster_only_on_explicit_e164_phone():
    clusters = resolve_identity_clusters(
        (
            profile("a", phone="+19785550101", legal_name="Avery Lake"),
            profile("b", phone="+19785550101", preferred_name="avery lake"),
        )
    )
    assert len(clusters) == 1
    assert clusters[0].resolution_method == "phone"
    assert clusters[0].source_contact_ids == ("a", "b")


def test_phone_does_not_attach_an_emailless_row_to_an_email_identity():
    clusters = resolve_identity_clusters(
        (
            profile(
                "a",
                email="avery@example.com",
                phone="+19785550101",
                legal_name="Avery Lake",
            ),
            profile("b", phone="+19785550101", preferred_name="Avery Lake"),
        )
    )
    assert len(clusters) == 2
    assert {cluster.resolution_method for cluster in clusters} == {"email", "phone"}
    assert {cluster.source_contact_ids for cluster in clusters} == {("a",), ("b",)}


def test_one_phone_cannot_bridge_conflicting_email_identities():
    with pytest.raises(IdentityConflict, match="conflicting email"):
        resolve_identity_clusters(
            (
                profile("a", email="a@example.com", phone="+19785550101"),
                profile("b", email="b@example.com", phone="+19785550101"),
            )
        )


def test_identity_hash_is_versioned_stable_sha256():
    clusters = resolve_identity_clusters(
        (profile("a", email="Avery@Example.com", legal_name="Avery Lake"),)
    )
    assert (
        clusters[0].identity_hash
        == hashlib.sha256(b"contacts-v1\0email\0avery@example.com").hexdigest()
    )


def test_cluster_membership_hash_is_redacted_and_source_order_stable():
    forward = resolve_identity_clusters(
        (
            profile("aaaaaaaaaaaaaaaaaaaaaaaa", email="same@example.test"),
            profile("bbbbbbbbbbbbbbbbbbbbbbbb", email="SAME@example.test"),
        )
    )[0]
    reverse = resolve_identity_clusters(
        (
            profile("bbbbbbbbbbbbbbbbbbbbbbbb", email="same@example.test"),
            profile("aaaaaaaaaaaaaaaaaaaaaaaa", email="SAME@example.test"),
        )
    )[0]

    membership_hash = redacted_cluster_membership_hash(forward)
    assert membership_hash == redacted_cluster_membership_hash(reverse)
    assert len(membership_hash) == 64
    assert "aaaaaaaaaaaaaaaaaaaaaaaa" not in membership_hash
    assert "bbbbbbbbbbbbbbbbbbbbbbbb" not in membership_hash


def test_source_order_does_not_change_clusters_or_hashes():
    candidates = (
        profile("c", legal_name="Jordan Reed"),
        profile("b", email="avery@example.com", legal_name="Avery Lake"),
        profile("a", email="AVERY@example.com", legal_name="Avery Lake"),
    )
    assert resolve_identity_clusters(candidates) == resolve_identity_clusters(
        tuple(reversed(candidates))
    )


def test_duplicate_provider_id_is_an_identity_conflict():
    with pytest.raises(IdentityConflict, match="duplicate provider"):
        resolve_identity_clusters((profile("a"), profile("a")))


def test_every_source_id_appears_in_exactly_one_immutable_cluster():
    candidates = (
        profile("a", email="one@example.com"),
        profile("b", email="ONE@example.com"),
        profile("c", phone="+19785550101"),
        profile("d"),
    )
    clusters = resolve_identity_clusters(candidates)
    flattened = tuple(
        source_contact_id
        for cluster in clusters
        for source_contact_id in cluster.source_contact_ids
    )
    assert sorted(flattened) == ["a", "b", "c", "d"]
    assert len(flattened) == len(set(flattened))
    assert isinstance(clusters, tuple)
    assert all(isinstance(cluster.source_contact_ids, tuple) for cluster in clusters)
    with pytest.raises(FrozenInstanceError):
        clusters[0].identity_hash = "mutable"
    assert not hasattr(
        ContactIdentityCluster("0" * 64, "provider_id", ("x",)), "__dict__"
    )
