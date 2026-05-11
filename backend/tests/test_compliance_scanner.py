"""Compliance module smoke + scanner tests."""

import pytest


def test_compliance_module_importable():
    """Module package exists and exposes a public surface."""
    from services import compliance  # noqa: F401


import re

from services.compliance.rules import PROTECTED_CLASS_TERMS, Rule


def test_rule_dataclass_is_frozen_and_has_required_fields():
    rule = Rule(
        id="TEST-001",
        category="fair_housing",
        pattern=re.compile(r"\btest\b", re.IGNORECASE),
        severity="hard",
        guidance="Test guidance.",
    )
    assert rule.id == "TEST-001"
    with pytest.raises(Exception):  # FrozenInstanceError or dataclasses.FrozenInstanceError
        rule.id = "OTHER"  # type: ignore[misc]


@pytest.mark.parametrize(
    "sentence,expected_id_prefix",
    [
        ("Great for families with children!", "FH-"),
        ("No kids please.", "FH-"),
        ("Christian neighborhood with several churches.", "FH-"),
        ("Section 8 vouchers not accepted.", "FH-"),
        ("Perfect for empty nesters.", "FH-"),
        ("Ideal for a young couple.", "FH-"),
    ],
)
def test_protected_class_terms_match(sentence: str, expected_id_prefix: str):
    hits = [r for r in PROTECTED_CLASS_TERMS if r.pattern.search(sentence)]
    assert hits, f"Expected at least one PROTECTED_CLASS_TERMS hit on: {sentence!r}"
    assert all(r.id.startswith(expected_id_prefix) for r in hits)
    assert all(r.category == "fair_housing" for r in hits)


from services.compliance.rules import CODED_PHRASES


@pytest.mark.parametrize(
    "sentence",
    [
        "This is a family-friendly building.",
        "Good for young professionals.",
        "An up-and-coming neighborhood.",
        "It is a safe neighborhood.",
        "Walking distance to good schools.",
        "Walking distance to several churches and temples.",
        "An exclusive private community.",
        "Perfect for a traditional family.",
        "Located in a quiet residential pocket.",
    ],
)
def test_coded_phrases_match(sentence: str):
    hits = [r for r in CODED_PHRASES if r.pattern.search(sentence)]
    assert hits, f"Expected CODED_PHRASES hit on: {sentence!r}"
    assert all(r.id.startswith("CP-") for r in hits)
    assert all(r.category == "coded_phrase" for r in hits)
