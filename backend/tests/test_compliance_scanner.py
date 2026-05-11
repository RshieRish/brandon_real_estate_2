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


from services.compliance.rules import ADVICE_PATTERNS


@pytest.mark.parametrize(
    "sentence",
    [
        "You will save $12,000 in tax this year.",
        "Guaranteed return of 8% annually.",
        "A 1031 exchange will defer all capital gains tax here.",
        "This will appreciate at least 5% per year.",
        "No need to consult an attorney on this transaction.",
        "Like-kind exchange guarantees you avoid the tax bill.",
        "This is guaranteed to appreciate.",
    ],
)
def test_advice_patterns_match(sentence: str):
    hits = [r for r in ADVICE_PATTERNS if r.pattern.search(sentence)]
    assert hits, f"Expected ADVICE_PATTERNS hit on: {sentence!r}"
    assert all(r.id.startswith("AD-") for r in hits)
    assert all(r.category == "unauthorized_advice" for r in hits)


from services.compliance.rules import MA_NH_LANDMINES


@pytest.mark.parametrize(
    "sentence",
    [
        "Rent control protects this Boston property from rent hikes.",
        "Massachusetts has rent control on most multi-family units.",
        "Security deposits can be held in any personal account.",
        "You can keep the entire security deposit on move-out.",
        "Lead paint disclosure is optional for pre-1978 buildings.",
        "Standard tenant eviction takes 7 days in MA.",
        "Short-term rentals are legal everywhere in NH and MA.",
    ],
)
def test_ma_nh_landmines_match(sentence: str):
    hits = [r for r in MA_NH_LANDMINES if r.pattern.search(sentence)]
    assert hits, f"Expected MA_NH_LANDMINES hit on: {sentence!r}"
    assert all(r.id.startswith("SL-") for r in hits)
    assert all(r.category == "state_specific" for r in hits)


def test_sl_001_excludes_no_rent_control_negation():
    """SL-001 must NOT fire on 'Massachusetts has no rent control'."""
    from services.compliance.rules import MA_NH_LANDMINES
    sl_001 = next(r for r in MA_NH_LANDMINES if r.id == "SL-001")
    assert sl_001.pattern.search("Rent control protects this property.") is not None
    assert sl_001.pattern.search("Massachusetts has rent control on multi-family.") is not None
    assert sl_001.pattern.search("Massachusetts has no rent control.") is None
    assert sl_001.pattern.search("Boston no rent control here.") is None


from tests.fixtures.compliance_good_sentences import GOOD_SENTENCES
from services.compliance.rules import ALL_RULES


@pytest.mark.parametrize("sentence", GOOD_SENTENCES)
def test_good_sentences_have_zero_matches(sentence: str):
    hits = [r.id for r in ALL_RULES if r.pattern.search(sentence)]
    assert hits == [], f"False positive on {sentence!r}: {hits}"


from services.compliance.scanner import Violation, scan_text, scan_report


def test_scan_text_returns_violations_for_field():
    violations = scan_text("ai_explanation", "This is a family-friendly area with good schools.")
    rule_ids = sorted(v.rule_id for v in violations)
    assert "CP-001" in rule_ids   # family-friendly
    assert "CP-005" in rule_ids   # good schools
    assert all(v.field_path == "ai_explanation" for v in violations)
    assert all(isinstance(v, Violation) for v in violations)


def test_scan_text_clean_returns_empty():
    assert scan_text("verdict_reason", "Cap rate of 6.2% with stable rent comps.") == []


def test_scan_report_walks_all_text_fields():
    report = {
        "ai_explanation": "A safe neighborhood for empty nesters.",
        "exit_comparison": {
            "sell": "Sell at end of hold for a guaranteed profit.",
            "refinance": "Refinance and hold; consult your CPA on tax impact.",
            "exchange_1031": "1031 exchange will defer all capital gains.",
        },
        "verdict": "MODERATE",
        "verdict_reason": "Cap rate supports the verdict.",
        "hold_scenarios": [],
    }
    violations_by_field = scan_report(report)
    assert "ai_explanation" in violations_by_field
    assert "exit_comparison.sell" in violations_by_field
    assert "exit_comparison.exchange_1031" in violations_by_field
    assert "exit_comparison.refinance" not in violations_by_field
    assert "verdict_reason" not in violations_by_field
    # spot-check some rule IDs
    all_ids = {v.rule_id for vs in violations_by_field.values() for v in vs}
    assert {"CP-004", "FH-006", "AD-002", "AD-003"}.issubset(all_ids)


def test_scan_report_missing_fields_are_safe():
    assert scan_report({}) == {}
    assert scan_report({"ai_explanation": ""}) == {}
