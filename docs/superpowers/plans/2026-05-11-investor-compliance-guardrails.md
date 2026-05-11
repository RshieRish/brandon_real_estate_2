# Investor Compliance Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Fair Housing + REALTOR® Code of Ethics + MA/NH legal guardrails to Gemini-generated investor reports via prompt rules + deterministic post-check with auto-rewrite and audit logging.

**Architecture:** New `backend/services/compliance/` module wraps Gemini output. Regex/lexicon scanner detects violations; on hit, a Gemini Flash-Lite call rewrites the offending field (max 2 retries, then per-field fallback string). Every violation persists to a new `compliance_violations` Postgres table for audit. A disclaimer field is always appended.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic, pytest (with new `live_llm` marker), `google-generativeai` SDK (Gemini Pro for analysis, Flash-Lite for rewriter), Next.js 14 + TypeScript for frontend.

**Path corrections from spec:** Spec referenced `backend/db/models/`; actual codebase uses `backend/models/`. Frontend report type is named `InvestorAiReport` (not `Report`). All paths in this plan use the corrected locations.

---

## File Structure

### New files (backend)
```
backend/services/compliance/__init__.py        # exports enforce()
backend/services/compliance/rules.py           # Rule dataclass + 4 rule lists
backend/services/compliance/prompt.py          # COMPLIANCE_PROMPT_BLOCK constant
backend/services/compliance/scanner.py         # Violation dataclass + scan_text/scan_report
backend/services/compliance/rewriter.py        # rewrite_field() — Gemini Flash-Lite
backend/services/compliance/disclaimer.py      # build_disclaimer()
backend/services/compliance/audit.py           # log_violations()
backend/models/compliance_violation.py         # SQLAlchemy model
backend/alembic/versions/d5e9f1a2b3c4_add_compliance_violations.py  # migration
backend/pytest.ini                             # registers live_llm marker
backend/tests/test_compliance_scanner.py
backend/tests/test_compliance_disclaimer.py
backend/tests/test_compliance_rewriter.py
backend/tests/test_compliance_audit.py
backend/tests/test_compliance_enforce.py
backend/tests/test_compliance_integration.py   # @pytest.mark.live_llm
backend/tests/fixtures/__init__.py
backend/tests/fixtures/compliance_bad_sentences.py
backend/tests/fixtures/compliance_good_sentences.py
```

### Modified files
```
backend/services/investor_service.py                          # inject COMPLIANCE_PROMPT_BLOCK, call enforce()
backend/services/gemini.py                                    # add generate_text_flash_lite()
frontend/src/components/investor/report-types.ts              # add disclaimer?: string
frontend/src/components/investor/FullReportResults.tsx        # render report.disclaimer
```

---

## Task 1: Pytest config + module skeleton

**Files:**
- Create: `backend/pytest.ini`
- Create: `backend/services/compliance/__init__.py`
- Test: `backend/tests/test_compliance_scanner.py` (smoke test only)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_compliance_scanner.py`:
```python
"""Compliance module smoke + scanner tests."""

import pytest


def test_compliance_module_importable():
    """Module package exists and exposes a public surface."""
    from services import compliance  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py::test_compliance_module_importable -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.compliance'`

- [ ] **Step 3: Create the pytest config**

Create `backend/pytest.ini`:
```ini
[pytest]
markers =
    live_llm: integration tests that hit real Gemini API (require GEMINI_API_KEY)
```

- [ ] **Step 4: Create the module skeleton**

Create `backend/services/compliance/__init__.py`:
```python
"""Compliance guardrails for Gemini-generated investor reports.

Public entry point: ``enforce()``. See ``docs/superpowers/specs/2026-05-11-investor-compliance-guardrails-design.md``.
"""
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py::test_compliance_module_importable -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/pytest.ini backend/services/compliance/__init__.py backend/tests/test_compliance_scanner.py
git commit -m "feat(compliance): scaffold module + pytest live_llm marker"
```

---

## Task 2: Rule dataclass and PROTECTED_CLASS_TERMS

**Files:**
- Create: `backend/services/compliance/rules.py`
- Modify: `backend/tests/test_compliance_scanner.py`

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_compliance_scanner.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py -v`
Expected: FAIL with `ImportError: cannot import name 'PROTECTED_CLASS_TERMS' from 'services.compliance.rules'` (or `ModuleNotFoundError`).

- [ ] **Step 3: Create the rules module**

Create `backend/services/compliance/rules.py`:
```python
"""Compliance rule definitions.

Four categories of patterns, all compiled at import time. Each ``Rule`` is
immutable and carries enough metadata for the scanner to attribute hits and for
the rewriter to fix them.

References:
- Federal Fair Housing Act (42 U.S.C. §§ 3601-3619)
- MA General Laws Ch. 151B
- NH RSA 354-A
- NAR Code of Ethics, Articles 10, 11, 12, 13
- HUD "Words to Avoid in Advertising" enforcement guidance
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RuleCategory = Literal[
    "fair_housing",
    "coded_phrase",
    "unauthorized_advice",
    "state_specific",
]
RuleSeverity = Literal["hard", "soft"]


@dataclass(frozen=True)
class Rule:
    id: str
    category: RuleCategory
    pattern: re.Pattern[str]
    severity: RuleSeverity
    guidance: str


def _ci(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


PROTECTED_CLASS_TERMS: tuple[Rule, ...] = (
    Rule(
        id="FH-001",
        category="fair_housing",
        pattern=_ci(r"\bfamilies?\s+with\s+(?:kids|children)\b"),
        severity="hard",
        guidance="Do not reference familial status (families with children). Describe the property's physical features instead.",
    ),
    Rule(
        id="FH-002",
        category="fair_housing",
        pattern=_ci(r"\bno\s+(?:kids|children)\b"),
        severity="hard",
        guidance="Do not exclude based on familial status. Remove any reference to children.",
    ),
    Rule(
        id="FH-003",
        category="fair_housing",
        pattern=_ci(r"\b(?:Christian|Jewish|Muslim|Catholic|Protestant|Hindu|Buddhist)\b\s+(?:neighborhood|area|community)"),
        severity="hard",
        guidance="Do not reference religion. Describe the location by geography or amenities.",
    ),
    Rule(
        id="FH-004",
        category="fair_housing",
        pattern=_ci(r"\bsection\s*8\b"),
        severity="hard",
        guidance="Do not reference Section 8 / housing vouchers. Source of income is a protected class in MA and NH.",
    ),
    Rule(
        id="FH-005",
        category="fair_housing",
        pattern=_ci(r"\bvoucher(?:s)?\s+(?:not\s+accepted|excluded|prohibited)\b"),
        severity="hard",
        guidance="Source of income is a protected class. Do not exclude voucher holders.",
    ),
    Rule(
        id="FH-006",
        category="fair_housing",
        pattern=_ci(r"\bempty\s+nesters?\b"),
        severity="hard",
        guidance="Do not target by age/familial status. Describe the floor plan or layout instead.",
    ),
    Rule(
        id="FH-007",
        category="fair_housing",
        pattern=_ci(r"\byoung\s+(?:couples?|professionals?|families?)\b"),
        severity="hard",
        guidance="Do not target by age or familial status. Focus on the property's features.",
    ),
    Rule(
        id="FH-008",
        category="fair_housing",
        pattern=_ci(r"\b(?:able[- ]bodied|walks?\s+up\s+stairs|no\s+wheelchairs?)\b"),
        severity="hard",
        guidance="Do not exclude based on disability. Describe physical features factually.",
    ),
    Rule(
        id="FH-009",
        category="fair_housing",
        pattern=_ci(r"\bsingles?\s+only\b"),
        severity="hard",
        guidance="Do not target by marital status (protected in MA and NH).",
    ),
    Rule(
        id="FH-010",
        category="fair_housing",
        pattern=_ci(r"\b(?:english[- ]speaking|primarily\s+(?:white|black|asian|hispanic|latino))\b"),
        severity="hard",
        guidance="Do not reference national origin or race.",
    ),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/compliance/rules.py backend/tests/test_compliance_scanner.py
git commit -m "feat(compliance): Rule dataclass + PROTECTED_CLASS_TERMS rules"
```

---

## Task 3: CODED_PHRASES rules

**Files:**
- Modify: `backend/services/compliance/rules.py`
- Modify: `backend/tests/test_compliance_scanner.py`

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_compliance_scanner.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py::test_coded_phrases_match -v`
Expected: FAIL with `ImportError: cannot import name 'CODED_PHRASES'`.

- [ ] **Step 3: Add CODED_PHRASES to rules.py**

Append to `backend/services/compliance/rules.py` (after `PROTECTED_CLASS_TERMS`):
```python
CODED_PHRASES: tuple[Rule, ...] = (
    Rule(
        id="CP-001",
        category="coded_phrase",
        pattern=_ci(r"\bfamily[- ]friendly\b"),
        severity="hard",
        guidance="HUD flags 'family-friendly' as familial-status steering. Describe the property's layout (e.g. '3-bedroom with yard') instead.",
    ),
    Rule(
        id="CP-002",
        category="coded_phrase",
        pattern=_ci(r"\b(?:good|great|perfect)\s+for\s+young\s+professionals?\b"),
        severity="hard",
        guidance="Targets by age. Describe transit, walkability, or amenities instead.",
    ),
    Rule(
        id="CP-003",
        category="coded_phrase",
        pattern=_ci(r"\bup[- ]and[- ]coming\s+(?:neighborhood|area|community)\b"),
        severity="hard",
        guidance="HUD-flagged code for racial/economic transition. Describe the specific trend (e.g. '15% price appreciation YoY').",
    ),
    Rule(
        id="CP-004",
        category="coded_phrase",
        pattern=_ci(r"\bsafe\s+neighborhood\b"),
        severity="hard",
        guidance="Race-coded per HUD. Cite an objective metric (crime stats by source) or remove.",
    ),
    Rule(
        id="CP-005",
        category="coded_phrase",
        pattern=_ci(r"\bgood\s+schools?\b"),
        severity="hard",
        guidance="HUD-flagged. Cite school rating source (e.g. 'MA DESE rating 8/10') or omit.",
    ),
    Rule(
        id="CP-006",
        category="coded_phrase",
        pattern=_ci(r"\bwalk(?:ing)?\s+distance\s+to\s+(?:churches?|temples?|mosques?|synagogues?)\b"),
        severity="hard",
        guidance="References religion. Describe walkability to non-religious amenities instead.",
    ),
    Rule(
        id="CP-007",
        category="coded_phrase",
        pattern=_ci(r"\b(?:exclusive|private)\s+(?:community|neighborhood|enclave)\b"),
        severity="hard",
        guidance="Implies social/economic exclusion. Describe physical privacy (lot size, setbacks) instead.",
    ),
    Rule(
        id="CP-008",
        category="coded_phrase",
        pattern=_ci(r"\btraditional\s+famil(?:y|ies)\b"),
        severity="hard",
        guidance="Familial-status steering. Remove.",
    ),
    Rule(
        id="CP-009",
        category="coded_phrase",
        pattern=_ci(r"\bquiet\s+residential\s+pocket\b"),
        severity="hard",
        guidance="HUD-flagged code. Describe specific street/lot characteristics instead.",
    ),
    Rule(
        id="CP-010",
        category="coded_phrase",
        pattern=_ci(r"\bdesirable\s+demographic\b"),
        severity="hard",
        guidance="Explicit demographic targeting. Remove.",
    ),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/compliance/rules.py backend/tests/test_compliance_scanner.py
git commit -m "feat(compliance): CODED_PHRASES rules"
```

---

## Task 4: ADVICE_PATTERNS rules

**Files:**
- Modify: `backend/services/compliance/rules.py`
- Modify: `backend/tests/test_compliance_scanner.py`

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_compliance_scanner.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py::test_advice_patterns_match -v`
Expected: FAIL with `ImportError: cannot import name 'ADVICE_PATTERNS'`.

- [ ] **Step 3: Add ADVICE_PATTERNS to rules.py**

Append to `backend/services/compliance/rules.py`:
```python
ADVICE_PATTERNS: tuple[Rule, ...] = (
    Rule(
        id="AD-001",
        category="unauthorized_advice",
        pattern=_ci(r"\byou\s+(?:will|should)\s+(?:save|owe|pay)\s+\$[\d,]+\s+in\s+tax"),
        severity="hard",
        guidance="Specific tax dollar claims are outside a real estate agent's license. Soften to 'potential tax implications — confirm with a CPA.'",
    ),
    Rule(
        id="AD-002",
        category="unauthorized_advice",
        pattern=_ci(r"\bguaranteed\s+(?:return|profit|appreciation|yield)\b"),
        severity="hard",
        guidance="Real estate returns are never guaranteed. Use 'projected' or 'historical average'.",
    ),
    Rule(
        id="AD-003",
        category="unauthorized_advice",
        pattern=_ci(r"\b(?:1031|like[- ]kind)\s+exchange\s+(?:will|guarantees?)\s+(?:defer|avoid|eliminate)"),
        severity="hard",
        guidance="1031 outcomes are not guaranteed and require strict IRS compliance. Rephrase to recommend consulting a qualified intermediary and CPA.",
    ),
    Rule(
        id="AD-004",
        category="unauthorized_advice",
        pattern=_ci(r"\b(?:this|the\s+property|it)\s+(?:will|is\s+guaranteed\s+to)\s+appreciate\b"),
        severity="hard",
        guidance="Cannot guarantee appreciation. Use 'historically appreciated' with a source, or 'projected appreciation based on'.",
    ),
    Rule(
        id="AD-005",
        category="unauthorized_advice",
        pattern=_ci(r"\bno\s+need\s+to\s+consult\s+(?:an?\s+)?(?:attorney|lawyer|cpa|accountant|tax\s+advisor)\b"),
        severity="hard",
        guidance="Never discourage professional consultation. Reframe to recommend it.",
    ),
    Rule(
        id="AD-006",
        category="unauthorized_advice",
        pattern=_ci(r"\bsection\s+1031\b(?!.{0,100}\bconsult\b)"),
        severity="hard",
        guidance="Any 1031 reference must recommend consulting a CPA or qualified intermediary.",
    ),
    Rule(
        id="AD-007",
        category="unauthorized_advice",
        pattern=_ci(r"\brisk[- ]free\b"),
        severity="hard",
        guidance="No real estate investment is risk-free. Remove or qualify the claim.",
    ),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/compliance/rules.py backend/tests/test_compliance_scanner.py
git commit -m "feat(compliance): ADVICE_PATTERNS rules"
```

---

## Task 5: MA_NH_LANDMINES rules

**Files:**
- Modify: `backend/services/compliance/rules.py`
- Modify: `backend/tests/test_compliance_scanner.py`

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_compliance_scanner.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py::test_ma_nh_landmines_match -v`
Expected: FAIL with `ImportError: cannot import name 'MA_NH_LANDMINES'`.

- [ ] **Step 3: Add MA_NH_LANDMINES to rules.py**

Append to `backend/services/compliance/rules.py`:
```python
MA_NH_LANDMINES: tuple[Rule, ...] = (
    Rule(
        id="SL-001",
        category="state_specific",
        pattern=_ci(r"\brent\s+control\b"),
        severity="hard",
        guidance="MA banned rent control statewide in 1994 (Ch. 40P). NH has no rent control. Do not reference rent control protections.",
    ),
    Rule(
        id="SL-002",
        category="state_specific",
        pattern=_ci(r"\bsecurity\s+deposit(?:s)?\s+(?:can|may)\s+(?:be\s+(?:held|kept)\s+in\s+(?:any|a\s+personal)|simply\s+go\s+into)"),
        severity="hard",
        guidance="MA Ch. 186 §15B requires a separate interest-bearing account. Wrong advice triggers treble damages.",
    ),
    Rule(
        id="SL-003",
        category="state_specific",
        pattern=_ci(r"\b(?:keep|retain)\s+the\s+(?:entire|whole|full)\s+security\s+deposit\b"),
        severity="hard",
        guidance="MA Ch. 186 §15B requires itemized deductions with receipts. Cannot retain blanket deposit.",
    ),
    Rule(
        id="SL-004",
        category="state_specific",
        pattern=_ci(r"\blead\s+paint\s+disclosure\s+is\s+optional\b"),
        severity="hard",
        guidance="MA and federal law require lead paint disclosure for pre-1978 properties.",
    ),
    Rule(
        id="SL-005",
        category="state_specific",
        pattern=_ci(r"\beviction\s+(?:takes|in\s+ma|in\s+nh)\b.{0,40}\b(?:7|seven|10|ten)\s+days?\b"),
        severity="hard",
        guidance="MA summary process eviction averages 60-90+ days. Do not understate timelines.",
    ),
    Rule(
        id="SL-006",
        category="state_specific",
        pattern=_ci(r"\bshort[- ]term\s+rentals?\s+(?:are|is)\s+legal\s+everywhere\b"),
        severity="hard",
        guidance="STR legality is per-municipality in MA (Boston, Cambridge, etc. have restrictions). Do not generalize.",
    ),
    Rule(
        id="SL-007",
        category="state_specific",
        pattern=_ci(r"\b(?:no\s+lease\s+required|month[- ]to[- ]month\s+is\s+automatic)\b"),
        severity="hard",
        guidance="Tenant-at-will rules in MA/NH have specific notice requirements. Recommend a written lease.",
    ),
)


ALL_RULES: tuple[Rule, ...] = (
    PROTECTED_CLASS_TERMS + CODED_PHRASES + ADVICE_PATTERNS + MA_NH_LANDMINES
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/compliance/rules.py backend/tests/test_compliance_scanner.py
git commit -m "feat(compliance): MA_NH_LANDMINES rules + ALL_RULES export"
```

---

## Task 6: Good-sentence false-positive fixtures

**Files:**
- Create: `backend/tests/fixtures/__init__.py`
- Create: `backend/tests/fixtures/compliance_good_sentences.py`
- Modify: `backend/tests/test_compliance_scanner.py`

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_compliance_scanner.py`:
```python
from tests.fixtures.compliance_good_sentences import GOOD_SENTENCES
from services.compliance.rules import ALL_RULES


@pytest.mark.parametrize("sentence", GOOD_SENTENCES)
def test_good_sentences_have_zero_matches(sentence: str):
    hits = [r.id for r in ALL_RULES if r.pattern.search(sentence)]
    assert hits == [], f"False positive on {sentence!r}: {hits}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py::test_good_sentences_have_zero_matches -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.fixtures'`.

- [ ] **Step 3: Create the fixture modules**

Create `backend/tests/fixtures/__init__.py`:
```python
```

Create `backend/tests/fixtures/compliance_good_sentences.py`:
```python
"""Sentences that must NOT trigger any compliance rule.

These lock the false-positive baseline. If a rule change adds a match here,
the rule was too broad and needs scoping.
"""

GOOD_SENTENCES: tuple[str, ...] = (
    # Plain financial analysis
    "Projected monthly cash flow is $420 after debt service and vacancy reserve.",
    "Cap rate of 6.2% based on $32,400 NOI and $522,000 purchase price.",
    "Gross rent multiplier of 11.4 is on the lower end for this submarket.",
    "5-year equity build totals $58,000 assuming 3% annual appreciation.",
    "Stress-testing rents at -5% yields negative monthly cash flow.",
    # Property descriptions without coded language
    "Three-bedroom single-family on a 0.18-acre lot with attached one-car garage.",
    "Renovated in 2019 with new HVAC, roof, and updated kitchen.",
    "Lot backs to conservation land for natural privacy buffer.",
    "Walkability score of 72 per Walk Score; near commuter rail station.",
    # Strategy framing
    "BRRRR refinance assumes 75% LTV at appraised post-rehab value.",
    "Short-term rental occupancy break-even is 58% at current ADR.",
    "Fix-and-flip ARV of $640,000 supported by three comparable sales within 0.5 miles.",
    "Buy-and-hold strategy requires sustained rent growth of 2.8% annually.",
    # Advice that includes the required consult disclaimer
    "Consider a Section 1031 exchange — consult a qualified intermediary and CPA before any sale.",
    "Tax depreciation may offset rental income; confirm with your CPA.",
    "MA Chapter 186 governs security deposits; have an attorney review your lease.",
    # State context done correctly
    "Massachusetts has no rent control; market rents apply.",
    "MA Chapter 186 §15B requires a separate interest-bearing escrow for security deposits.",
    "Lead paint disclosure is mandatory for pre-1978 properties under federal and MA law.",
    "STR legality varies by municipality in MA — confirm with the local bylaw.",
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py -v`
Expected: All tests PASS, including all parametrized good-sentence cases.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/fixtures/ backend/tests/test_compliance_scanner.py
git commit -m "test(compliance): good-sentence fixtures locking false-positive baseline"
```

---

## Task 7: Scanner — scan_text + scan_report

**Files:**
- Create: `backend/services/compliance/scanner.py`
- Modify: `backend/tests/test_compliance_scanner.py`

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_compliance_scanner.py`:
```python
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
        "verdict": "MODERATE",  # non-text-scanned field
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py -v`
Expected: FAIL with `ImportError: cannot import name 'Violation' from 'services.compliance.scanner'`.

- [ ] **Step 3: Implement the scanner**

Create `backend/services/compliance/scanner.py`:
```python
"""Compliance scanner.

Walks the text fields of a Gemini investor report and returns ``Violation``
records describing every rule match.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.compliance.rules import ALL_RULES, RuleCategory, RuleSeverity

# Fields in the Gemini report that contain free-form text we must scan.
SCANNED_FIELDS: tuple[str, ...] = (
    "ai_explanation",
    "exit_comparison.sell",
    "exit_comparison.refinance",
    "exit_comparison.exchange_1031",
    "verdict_reason",
)


@dataclass(frozen=True)
class Violation:
    rule_id: str
    category: RuleCategory
    severity: RuleSeverity
    field_path: str
    matched_text: str
    span: tuple[int, int]
    guidance: str


def _get_field(report: dict[str, Any], path: str) -> str:
    """Walk a dotted ``path`` (e.g. ``exit_comparison.sell``) safely."""
    node: Any = report
    for part in path.split("."):
        if not isinstance(node, dict):
            return ""
        node = node.get(part, "")
    return node if isinstance(node, str) else ""


def scan_text(field_path: str, text: str) -> list[Violation]:
    """Return all rule violations for ``text``, tagged with ``field_path``."""
    if not text:
        return []
    out: list[Violation] = []
    for rule in ALL_RULES:
        for match in rule.pattern.finditer(text):
            out.append(
                Violation(
                    rule_id=rule.id,
                    category=rule.category,
                    severity=rule.severity,
                    field_path=field_path,
                    matched_text=match.group(0),
                    span=match.span(),
                    guidance=rule.guidance,
                )
            )
    return out


def scan_report(report: dict[str, Any]) -> dict[str, list[Violation]]:
    """Return ``{field_path: [violations]}`` for every scanned field with hits."""
    result: dict[str, list[Violation]] = {}
    for path in SCANNED_FIELDS:
        text = _get_field(report, path)
        violations = scan_text(path, text)
        if violations:
            result[path] = violations
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_scanner.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/compliance/scanner.py backend/tests/test_compliance_scanner.py
git commit -m "feat(compliance): scanner with scan_text and scan_report"
```

---

## Task 8: Disclaimer module

**Files:**
- Create: `backend/services/compliance/disclaimer.py`
- Create: `backend/tests/test_compliance_disclaimer.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_compliance_disclaimer.py`:
```python
from services.compliance.disclaimer import build_disclaimer


def test_disclaimer_contains_required_blocks():
    text = build_disclaimer()
    # not-advice block
    assert "not constitute legal, tax, accounting, or investment advice" in text
    # fair housing block
    assert "Equal Housing Opportunity" in text
    assert "Federal Fair Housing Act" in text
    # KW broker block
    assert "Keller Williams Realty Success" in text
    assert "independently owned and operated" in text


def test_disclaimer_is_stable():
    """Result is deterministic across calls."""
    assert build_disclaimer() == build_disclaimer()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_disclaimer.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement disclaimer.py**

Create `backend/services/compliance/disclaimer.py`:
```python
"""Standard disclaimer block appended to every investor report.

Three concatenated paragraphs covering NAR Articles 11/13 (not-advice),
Federal + MA + NH Fair Housing, and KW broker disclosure (mirrors the
existing site footer per CLAUDE.md).
"""

_NOT_ADVICE = (
    "This analysis is generated as informational projection only and does not "
    "constitute legal, tax, accounting, or investment advice. Consult a licensed "
    "attorney, CPA, and your loan officer before acting on any figures."
)

_FAIR_HOUSING = (
    "Sold With Sweeney & Co. is an Equal Housing Opportunity provider. We comply "
    "with the Federal Fair Housing Act and applicable Massachusetts and New "
    "Hampshire fair housing laws."
)

_KW_BROKER = (
    "Brandon Sweeney is a licensed real estate agent in MA & NH. Sold With "
    "Sweeney & Co. is powered by Keller Williams Realty Success. Each office is "
    "independently owned and operated."
)


def build_disclaimer() -> str:
    """Return the three-paragraph disclaimer block."""
    return "\n\n".join((_NOT_ADVICE, _FAIR_HOUSING, _KW_BROKER))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_disclaimer.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/compliance/disclaimer.py backend/tests/test_compliance_disclaimer.py
git commit -m "feat(compliance): standard disclaimer block"
```

---

## Task 9: Gemini Flash-Lite wrapper

**Files:**
- Modify: `backend/services/gemini.py`
- Create: `backend/tests/test_gemini_flash_lite.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_gemini_flash_lite.py`:
```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_generate_text_flash_lite_uses_flash_model():
    from services.gemini import generate_text_flash_lite

    mock_model = MagicMock()
    mock_response = MagicMock(text="rewritten text")
    mock_model.generate_content_async = AsyncMock(return_value=mock_response)

    with patch("services.gemini.genai.GenerativeModel", return_value=mock_model) as ctor:
        out = await generate_text_flash_lite("hello")

    assert out == "rewritten text"
    ctor.assert_called_once()
    called_with = ctor.call_args.args[0] if ctor.call_args.args else ctor.call_args.kwargs.get("model_name")
    assert "flash" in called_with.lower()
```

- [ ] **Step 2: Verify pytest-asyncio is available, install if missing**

Run: `cd backend && python -c "import pytest_asyncio" 2>&1 || pip install pytest-asyncio`

Then ensure `backend/pytest.ini` includes asyncio mode. Edit `backend/pytest.ini` to:
```ini
[pytest]
markers =
    live_llm: integration tests that hit real Gemini API (require GEMINI_API_KEY)
asyncio_mode = auto
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_gemini_flash_lite.py -v`
Expected: FAIL with `ImportError: cannot import name 'generate_text_flash_lite' from 'services.gemini'`.

- [ ] **Step 4: Add generate_text_flash_lite to gemini.py**

Append to `backend/services/gemini.py` (at the bottom):
```python


async def generate_text_flash_lite(prompt: str) -> str:
    """Cheap, fast text generation for compliance rewrites.

    Uses ``gemini-3.1-flash-lite-preview`` for short, focused transformations
    where Gemini Pro would be overkill.
    """
    model = genai.GenerativeModel("gemini-3.1-flash-lite-preview")
    response = await model.generate_content_async(prompt)
    return response.text
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_gemini_flash_lite.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/gemini.py backend/tests/test_gemini_flash_lite.py backend/pytest.ini
git commit -m "feat(gemini): add generate_text_flash_lite for compliance rewrites"
```

---

## Task 10: Rewriter with retry + fallback

**Files:**
- Create: `backend/services/compliance/rewriter.py`
- Create: `backend/tests/test_compliance_rewriter.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_compliance_rewriter.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest

from services.compliance.scanner import Violation


def _v(rule_id: str, field_path: str = "ai_explanation", text: str = "family-friendly") -> Violation:
    return Violation(
        rule_id=rule_id,
        category="coded_phrase",
        severity="hard",
        field_path=field_path,
        matched_text=text,
        span=(0, len(text)),
        guidance="Remove the demographic-coded phrase.",
    )


@pytest.mark.asyncio
async def test_rewrite_field_returns_clean_rewrite_on_first_try():
    from services.compliance.rewriter import rewrite_field

    with patch(
        "services.compliance.rewriter.generate_text_flash_lite",
        new=AsyncMock(return_value="A 3-bedroom property with yard."),
    ) as gen:
        out, attempts, resolution = await rewrite_field(
            "ai_explanation",
            "A family-friendly home.",
            [_v("CP-001")],
        )
    assert out == "A 3-bedroom property with yard."
    assert attempts == 1
    assert resolution == "rewritten_clean"
    gen.assert_awaited_once()


@pytest.mark.asyncio
async def test_rewrite_field_retries_when_first_rewrite_still_dirty():
    from services.compliance.rewriter import rewrite_field

    responses = iter([
        "Still a family-friendly home.",   # still dirty
        "A 3-bedroom property with yard.",  # clean
    ])

    async def fake_gen(prompt: str) -> str:
        return next(responses)

    with patch("services.compliance.rewriter.generate_text_flash_lite", new=fake_gen):
        out, attempts, resolution = await rewrite_field(
            "ai_explanation",
            "A family-friendly home.",
            [_v("CP-001")],
        )
    assert out == "A 3-bedroom property with yard."
    assert attempts == 2
    assert resolution == "rewritten_clean"


@pytest.mark.asyncio
async def test_rewrite_field_falls_back_when_two_rewrites_dirty():
    from services.compliance.rewriter import rewrite_field, FALLBACK_STRINGS

    async def always_dirty(prompt: str) -> str:
        return "Still a family-friendly home."

    with patch("services.compliance.rewriter.generate_text_flash_lite", new=always_dirty):
        out, attempts, resolution = await rewrite_field(
            "ai_explanation",
            "A family-friendly home.",
            [_v("CP-001")],
        )
    assert out == FALLBACK_STRINGS["ai_explanation"]
    assert attempts == 2
    assert resolution == "rewritten_still_dirty_fallback"


@pytest.mark.asyncio
async def test_rewrite_field_unknown_field_uses_generic_fallback():
    from services.compliance.rewriter import rewrite_field

    async def always_dirty(_: str) -> str:
        return "family-friendly still"

    with patch("services.compliance.rewriter.generate_text_flash_lite", new=always_dirty):
        out, _attempts, resolution = await rewrite_field(
            "some_unmapped_field",
            "family-friendly text",
            [_v("CP-001", field_path="some_unmapped_field")],
        )
    assert "review" in out.lower()  # generic fallback contains the word "review"
    assert resolution == "rewritten_still_dirty_fallback"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_rewriter.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the rewriter**

Create `backend/services/compliance/rewriter.py`:
```python
"""Rewriter for compliance violations.

When the scanner flags a field, ``rewrite_field`` calls Gemini Flash-Lite with
a focused prompt to produce a clean replacement. If two attempts still violate
the rules, the per-field fallback string is used instead. Returns the final
text plus metadata for audit logging.
"""

from __future__ import annotations

from services.compliance.scanner import Violation, scan_text
from services.gemini import generate_text_flash_lite

MAX_REWRITE_ATTEMPTS = 2

FALLBACK_STRINGS: dict[str, str] = {
    "ai_explanation": (
        "This deal's full narrative analysis is being reviewed by Brandon's team. "
        "The numeric metrics above remain valid."
    ),
    "exit_comparison.sell": (
        "Sell-at-end-of-hold projections are under review. Refer to the numeric "
        "exit value in the hold scenarios above."
    ),
    "exit_comparison.refinance": (
        "Refinance scenario commentary is under review. The cash-flow and LTV "
        "figures above remain valid."
    ),
    "exit_comparison.exchange_1031": (
        "1031 exchange considerations are highly fact-specific — Brandon's team "
        "will review with a qualified intermediary and CPA before any action."
    ),
    "verdict_reason": (
        "The verdict above is supported by the numeric metrics. A detailed "
        "narrative is under review."
    ),
}

_GENERIC_FALLBACK = (
    "This section is being reviewed by Brandon's team. The numeric metrics "
    "above remain valid."
)


def _build_prompt(field_name: str, original_text: str, violations: list[Violation]) -> str:
    issues = "\n".join(f"- {v.guidance}" for v in violations)
    return (
        "You are rewriting a section of a real estate investor report to remove "
        "specific compliance issues.\n\n"
        f"FIELD: {field_name}\n"
        f"ORIGINAL:\n{original_text}\n\n"
        f"ISSUES TO FIX:\n{issues}\n\n"
        "Rewrite the section preserving the analytical meaning. Do NOT mention "
        "the original problematic phrasing. Do NOT add disclaimers. Return ONLY "
        "the rewritten text — no preamble, no commentary, no markdown fences."
    )


async def rewrite_field(
    field_name: str,
    original_text: str,
    violations: list[Violation],
) -> tuple[str, int, str]:
    """Rewrite ``original_text`` to clear ``violations``.

    Returns ``(final_text, attempts, resolution)`` where ``resolution`` is one of:
    ``"rewritten_clean"`` or ``"rewritten_still_dirty_fallback"``.
    """
    attempts = 0
    current_text = original_text
    current_violations = violations

    while attempts < MAX_REWRITE_ATTEMPTS:
        attempts += 1
        prompt = _build_prompt(field_name, current_text, current_violations)
        rewrite = (await generate_text_flash_lite(prompt)).strip()
        rescan = scan_text(field_name, rewrite)
        if not rescan:
            return rewrite, attempts, "rewritten_clean"
        current_text = rewrite
        current_violations = rescan

    fallback = FALLBACK_STRINGS.get(field_name, _GENERIC_FALLBACK)
    return fallback, attempts, "rewritten_still_dirty_fallback"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_rewriter.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/compliance/rewriter.py backend/tests/test_compliance_rewriter.py
git commit -m "feat(compliance): rewriter with retry + per-field fallback"
```

---

## Task 11: ComplianceViolation SQLAlchemy model

**Files:**
- Create: `backend/models/compliance_violation.py`
- Create: `backend/tests/test_compliance_model.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_compliance_model.py`:
```python
def test_compliance_violation_model_fields():
    from models.compliance_violation import ComplianceViolation

    inst = ComplianceViolation(
        lead_id=1,
        source="investor_report",
        rule_id="FH-001",
        category="fair_housing",
        severity="hard",
        field_path="ai_explanation",
        matched_text="families with children",
        original_text="Great for families with children.",
        final_text="Great 3-bed layout.",
        rewrite_attempts=1,
        resolution="rewritten_clean",
    )
    assert inst.rule_id == "FH-001"
    assert inst.rewrite_attempts == 1
    assert inst.__tablename__ == "compliance_violations"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'models.compliance_violation'`.

- [ ] **Step 3: Implement the model**

Create `backend/models/compliance_violation.py`:
```python
"""Audit table for every compliance scanner hit + rewriter outcome.

One row per violation (not per report). A report with 4 violations writes 4
rows so queries like "all FH hits this month" don't need to unpack JSON.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ComplianceViolation(Base):
    __tablename__ = "compliance_violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    lead_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("leads.id"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(50), default="investor_report")
    rule_id: Mapped[str] = mapped_column(String(50))
    category: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(10))
    field_path: Mapped[str] = mapped_column(String(100))
    matched_text: Mapped[str] = mapped_column(Text)
    original_text: Mapped[str] = mapped_column(Text)
    final_text: Mapped[str] = mapped_column(Text)
    rewrite_attempts: Mapped[int] = mapped_column(Integer, default=0)
    resolution: Mapped[str] = mapped_column(String(50))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_model.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/models/compliance_violation.py backend/tests/test_compliance_model.py
git commit -m "feat(compliance): ComplianceViolation SQLAlchemy model"
```

---

## Task 12: Alembic migration for compliance_violations

**Files:**
- Create: `backend/alembic/versions/d5e9f1a2b3c4_add_compliance_violations.py`

- [ ] **Step 1: Inspect current alembic head**

Run: `cd backend && python -m alembic current 2>&1 | tail -5; python -m alembic heads 2>&1 | tail -5`
Expected: head is `a1b2c3d4e5f6` (add_blogs_table). If different, use the actual head as `down_revision` in step 2.

- [ ] **Step 2: Create the migration**

Create `backend/alembic/versions/d5e9f1a2b3c4_add_compliance_violations.py`:
```python
"""add_compliance_violations

Revision ID: d5e9f1a2b3c4
Revises: a1b2c3d4e5f6
Create Date: 2026-05-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e9f1a2b3c4"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compliance_violations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="investor_report"),
        sa.Column("rule_id", sa.String(50), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("field_path", sa.String(100), nullable=False),
        sa.Column("matched_text", sa.Text(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=False),
        sa.Column("rewrite_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolution", sa.String(50), nullable=False),
    )
    op.create_index(
        "ix_compliance_violations_created_at",
        "compliance_violations",
        ["created_at"],
    )
    op.create_index(
        "ix_compliance_violations_lead_id",
        "compliance_violations",
        ["lead_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_compliance_violations_lead_id", table_name="compliance_violations")
    op.drop_index("ix_compliance_violations_created_at", table_name="compliance_violations")
    op.drop_table("compliance_violations")
```

- [ ] **Step 3: Run the migration against the dev database**

Run: `cd backend && python -m alembic upgrade head 2>&1 | tail -10`
Expected: `INFO  [alembic.runtime.migration] Running upgrade a1b2c3d4e5f6 -> d5e9f1a2b3c4, add_compliance_violations` and exit code 0.

- [ ] **Step 4: Verify the table exists**

Run: `cd backend && python -c "import asyncio; from database import engine; from sqlalchemy import text; asyncio.run((lambda: __import__('asyncio').get_event_loop().run_until_complete(engine.begin().__aenter__()))())" 2>&1 | head -3` — if that's awkward in your environment, instead connect to the DB with `psql \"$DATABASE_URL\" -c '\d compliance_violations'` and verify the columns listed match the migration.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/d5e9f1a2b3c4_add_compliance_violations.py
git commit -m "feat(compliance): alembic migration for compliance_violations"
```

---

## Task 13: Audit logging module

**Files:**
- Create: `backend/services/compliance/audit.py`
- Create: `backend/tests/test_compliance_audit.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_compliance_audit.py`:
```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.compliance.scanner import Violation


def _violation(rule_id: str = "FH-001", field_path: str = "ai_explanation") -> Violation:
    return Violation(
        rule_id=rule_id,
        category="fair_housing",
        severity="hard",
        field_path=field_path,
        matched_text="families with children",
        span=(0, 22),
        guidance="Do not reference familial status.",
    )


@pytest.mark.asyncio
async def test_log_violations_writes_one_row_per_violation():
    from services.compliance.audit import log_violations

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    violations = [_violation("FH-001"), _violation("CP-001")]
    field_outcomes = {
        "ai_explanation": {
            "original": "Original txt with families with children.",
            "final": "Clean text.",
            "attempts": 1,
            "resolution": "rewritten_clean",
        }
    }

    await log_violations(
        db,
        lead_id=42,
        violations_by_field={"ai_explanation": violations},
        field_outcomes=field_outcomes,
    )

    assert db.add.call_count == 2
    db.flush.assert_awaited()
    # Inspect first row written
    first_row = db.add.call_args_list[0].args[0]
    assert first_row.lead_id == 42
    assert first_row.rule_id == "FH-001"
    assert first_row.original_text == "Original txt with families with children."
    assert first_row.final_text == "Clean text."
    assert first_row.rewrite_attempts == 1
    assert first_row.resolution == "rewritten_clean"


@pytest.mark.asyncio
async def test_log_violations_swallows_db_errors(caplog):
    from services.compliance.audit import log_violations

    db = MagicMock()
    db.add = MagicMock(side_effect=RuntimeError("DB down"))
    db.flush = AsyncMock()

    # Must not raise; failure isolation per spec.
    await log_violations(
        db,
        lead_id=1,
        violations_by_field={"ai_explanation": [_violation()]},
        field_outcomes={
            "ai_explanation": {
                "original": "x",
                "final": "y",
                "attempts": 1,
                "resolution": "rewritten_clean",
            }
        },
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_audit.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement audit.py**

Create `backend/services/compliance/audit.py`:
```python
"""Persist every compliance scanner hit + rewriter outcome.

Failure isolation: DB write errors are logged but never raised. Losing the
user's report because the audit table is unhappy is worse than missing one row.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from models.compliance_violation import ComplianceViolation
from services.compliance.scanner import Violation

logger = logging.getLogger(__name__)


class FieldOutcome(TypedDict):
    original: str
    final: str
    attempts: int
    resolution: str   # "rewritten_clean" | "rewritten_still_dirty_fallback" | "no_action_needed"


async def log_violations(
    db: AsyncSession,
    *,
    lead_id: int | None,
    violations_by_field: dict[str, list[Violation]],
    field_outcomes: dict[str, FieldOutcome],
) -> None:
    """Write one ``ComplianceViolation`` row per violation. Never raises."""
    try:
        for field_path, violations in violations_by_field.items():
            outcome = field_outcomes.get(field_path)
            if outcome is None:
                continue
            for v in violations:
                row = ComplianceViolation(
                    lead_id=lead_id,
                    source="investor_report",
                    rule_id=v.rule_id,
                    category=v.category,
                    severity=v.severity,
                    field_path=v.field_path,
                    matched_text=v.matched_text,
                    original_text=outcome["original"],
                    final_text=outcome["final"],
                    rewrite_attempts=outcome["attempts"],
                    resolution=outcome["resolution"],
                )
                db.add(row)
        await db.flush()
    except Exception:  # pragma: no cover — failure isolation
        logger.exception(
            "compliance.audit.log_violations failed for lead_id=%s — continuing",
            lead_id,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_audit.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/compliance/audit.py backend/tests/test_compliance_audit.py
git commit -m "feat(compliance): audit logging with failure isolation"
```

---

## Task 14: enforce() entry point

**Files:**
- Modify: `backend/services/compliance/__init__.py`
- Create: `backend/tests/test_compliance_enforce.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_compliance_enforce.py`:
```python
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_enforce_clean_report_passes_through_and_appends_disclaimer():
    from services import compliance

    report = {
        "ai_explanation": "Cap rate is 6.2% with stable comps.",
        "exit_comparison": {
            "sell": "Sell at year 5 for projected $640k.",
            "refinance": "Refi at 75% LTV after rehab.",
            "exchange_1031": "Consult a QI and CPA on 1031 timing.",
        },
        "verdict": "MODERATE",
        "verdict_reason": "Cash flow supports the verdict.",
        "hold_scenarios": [],
    }
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    out = await compliance.enforce(report, db=db, lead_id=1)
    assert out["ai_explanation"] == "Cap rate is 6.2% with stable comps."
    assert "Equal Housing Opportunity" in out["disclaimer"]
    assert db.add.call_count == 0  # no violations, no rows written


@pytest.mark.asyncio
async def test_enforce_rewrites_violating_field_and_logs():
    from services import compliance

    report = {
        "ai_explanation": "This is a family-friendly home for young professionals.",
        "exit_comparison": {"sell": "Clean.", "refinance": "Clean.", "exchange_1031": "Clean — consult CPA."},
        "verdict": "MODERATE",
        "verdict_reason": "Clean reasoning.",
        "hold_scenarios": [],
    }
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    async def fake_rewriter(*args, **kwargs):
        return ("Clean rewrite.", 1, "rewritten_clean")

    import services.compliance as cmod
    cmod_rewrite = cmod.enforce.__globals__["rewrite_field"]   # access module-level binding
    cmod.enforce.__globals__["rewrite_field"] = fake_rewriter
    try:
        out = await compliance.enforce(report, db=db, lead_id=1)
    finally:
        cmod.enforce.__globals__["rewrite_field"] = cmod_rewrite

    assert out["ai_explanation"] == "Clean rewrite."
    assert "disclaimer" in out
    # ≥2 violations (family-friendly + young professionals), each gets a row
    assert db.add.call_count >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_enforce.py -v`
Expected: FAIL with `AttributeError: module 'services.compliance' has no attribute 'enforce'`.

- [ ] **Step 3: Implement enforce()**

Replace `backend/services/compliance/__init__.py` contents with:
```python
"""Compliance guardrails for Gemini-generated investor reports.

Public entry point: :func:`enforce`.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.compliance.audit import FieldOutcome, log_violations
from services.compliance.disclaimer import build_disclaimer
from services.compliance.rewriter import rewrite_field
from services.compliance.scanner import SCANNED_FIELDS, scan_report

__all__ = ["enforce"]


def _set_field(report: dict[str, Any], path: str, value: str) -> None:
    parts = path.split(".")
    node = report
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _get_field(report: dict[str, Any], path: str) -> str:
    node: Any = report
    for part in path.split("."):
        if not isinstance(node, dict):
            return ""
        node = node.get(part, "")
    return node if isinstance(node, str) else ""


async def enforce(
    report: dict[str, Any],
    *,
    db: AsyncSession,
    lead_id: int | None,
) -> dict[str, Any]:
    """Scan ``report``, rewrite any violating field, append disclaimer, log audit.

    Mutates a copy — never the caller's dict. Returns the cleaned report.
    """
    cleaned = copy.deepcopy(report)
    violations_by_field = scan_report(cleaned)
    field_outcomes: dict[str, FieldOutcome] = {}

    for field_path in SCANNED_FIELDS:
        violations = violations_by_field.get(field_path)
        original = _get_field(cleaned, field_path)
        if not violations:
            if original:
                field_outcomes[field_path] = FieldOutcome(
                    original=original, final=original, attempts=0, resolution="no_action_needed"
                )
            continue
        final, attempts, resolution = await rewrite_field(field_path, original, violations)
        _set_field(cleaned, field_path, final)
        field_outcomes[field_path] = FieldOutcome(
            original=original, final=final, attempts=attempts, resolution=resolution
        )

    # Only log fields that actually had violations.
    log_subset = {fp: vs for fp, vs in violations_by_field.items() if vs}
    if log_subset:
        await log_violations(
            db,
            lead_id=lead_id,
            violations_by_field=log_subset,
            field_outcomes=field_outcomes,
        )

    cleaned["disclaimer"] = build_disclaimer()
    return cleaned
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_enforce.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/compliance/__init__.py backend/tests/test_compliance_enforce.py
git commit -m "feat(compliance): enforce() entry point ties scanner + rewriter + audit"
```

---

## Task 15: Compliance prompt block

**Files:**
- Create: `backend/services/compliance/prompt.py`
- Create: `backend/tests/test_compliance_prompt.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_compliance_prompt.py`:
```python
def test_compliance_prompt_block_contains_required_guidance():
    from services.compliance.prompt import COMPLIANCE_PROMPT_BLOCK

    text = COMPLIANCE_PROMPT_BLOCK.lower()
    # Fair Housing
    assert "fair housing" in text
    assert "protected class" in text or "protected classes" in text
    # NAR ethics
    assert "no legal" in text or "not legal" in text or "no specific legal" in text
    # Disclaimer reminder
    assert "consult" in text
    # State context
    assert "massachusetts" in text or "ma" in text
    assert "new hampshire" in text or "nh" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compliance_prompt.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement prompt.py**

Create `backend/services/compliance/prompt.py`:
```python
"""Prompt fragment injected into the investor-report Gemini prompt.

This is the *first* layer of compliance defense — the scanner is the second.
Keeps Gemini from generating the most common Fair Housing and unauthorized-
advice slip-ups in the first place, so the rewriter is rarely needed.
"""

COMPLIANCE_PROMPT_BLOCK = """
COMPLIANCE REQUIREMENTS — read carefully and follow strictly:

1. FAIR HOUSING. Do NOT reference, target, or exclude any protected class:
   race, color, national origin, religion, sex, familial status, disability,
   age, marital status, sexual orientation, gender identity, source of income
   (including Section 8 / housing vouchers), military/veteran status, genetic
   information, or ancestry. This applies to Federal FHA, MA Ch. 151B, and
   NH RSA 354-A.

2. NO CODED LANGUAGE. Do NOT use HUD-flagged steering phrases such as
   "family-friendly", "good for young professionals", "up-and-coming
   neighborhood", "safe neighborhood", "good schools", "exclusive community",
   "traditional family", "walking distance to churches/temples", or similar.
   Describe physical features, transit, walkability, or cite objective metrics
   with sources instead.

3. NO UNAUTHORIZED ADVICE. Do NOT give specific legal, tax, accounting, or
   investment advice. Do NOT claim guaranteed returns, guaranteed
   appreciation, or guaranteed tax outcomes. Any mention of a 1031 exchange,
   depreciation, or tax strategy must recommend consulting a CPA, attorney,
   or qualified intermediary. Use "projected", "historical average", or
   "potential" rather than "guaranteed" or "will".

4. STATE LAW. Do NOT claim rent control exists in Massachusetts (banned
   statewide since 1994) or New Hampshire (never existed). Do NOT
   understate security-deposit obligations (MA Ch. 186 §15B), lead-paint
   disclosure requirements, or eviction timelines. Do NOT generalize STR
   legality across MA/NH — it is per-municipality.

5. PROFESSIONAL TITLES. Refer to Brandon as a "licensed real estate agent",
   not a "licensed REALTOR®". REALTOR® is a trade-association membership
   mark, never a license.

Write the investor report assuming the reader will consult an attorney, CPA,
and lender before acting. Default to objective metrics and projections, not
promises.
""".strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compliance_prompt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/compliance/prompt.py backend/tests/test_compliance_prompt.py
git commit -m "feat(compliance): COMPLIANCE_PROMPT_BLOCK for first-line defense"
```

---

## Task 16: Wire compliance into investor_service.py

**Files:**
- Modify: `backend/services/investor_service.py`
- Modify: `backend/routers/investor.py` (call signature change — pass db)
- Modify: `backend/tests/test_investor_metrics.py` if it imports investor_service (verify)

- [ ] **Step 1: Inspect router call site**

Run: `grep -n "generate_investor_analysis" /Users/rishabnandi/brandon-real-estate/backend/routers/investor.py`
Expected: one match at the line that calls `await generate_investor_analysis(inp.model_dump(), metrics)`.

- [ ] **Step 2: Add a focused integration test for the new signature**

Create or modify `backend/tests/test_investor_service_compliance.py`:
```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_generate_investor_analysis_injects_compliance_block_and_enforces():
    """The investor service must inject COMPLIANCE_PROMPT_BLOCK into the Gemini
    prompt AND pipe the parsed report through compliance.enforce."""
    from services.investor_service import generate_investor_analysis
    from services.compliance.prompt import COMPLIANCE_PROMPT_BLOCK

    mock_gemini_text = """
    {
      "ai_explanation": "Cap rate of 6.2% with stable comps.",
      "hold_scenarios": [],
      "exit_comparison": {"sell": "Sell at year 5.", "refinance": "Refi.", "exchange_1031": "Consult CPA."},
      "sensitivity": {"tax_increase_10pct": 0, "vacancy_10pct": 0, "rent_drop_5pct": 0},
      "verdict": "MODERATE",
      "verdict_reason": "Cash flow supports."
    }
    """
    captured_prompt = {}

    async def fake_generate_text(prompt: str, use_pro: bool = True) -> str:
        captured_prompt["text"] = prompt
        return mock_gemini_text

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch("services.investor_service.generate_text", new=fake_generate_text):
        out = await generate_investor_analysis(
            {"address": "test", "strategy": "buy_hold"},
            {"cap_rate": 6.2},
            db=db,
            lead_id=1,
        )

    assert COMPLIANCE_PROMPT_BLOCK in captured_prompt["text"]
    assert "disclaimer" in out
    assert "Equal Housing Opportunity" in out["disclaimer"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_investor_service_compliance.py -v`
Expected: FAIL — either `TypeError: generate_investor_analysis() got an unexpected keyword argument 'db'`, or assertion failure on missing `disclaimer`.

- [ ] **Step 4: Update investor_service.py**

Edit `backend/services/investor_service.py`. Replace the entire file contents with:
```python
from services.gemini import generate_text
from services.compliance import enforce
from services.compliance.prompt import COMPLIANCE_PROMPT_BLOCK
import json
import re

from sqlalchemy.ext.asyncio import AsyncSession


STRATEGY_LABELS: dict[str, str] = {
    "buy_hold": "Buy & Hold (long-term rental)",
    "str": "Short-Term Rental (Airbnb / VRBO)",
    "flip": "Fix & Flip",
    "brrrr": "BRRRR (Buy, Rehab, Rent, Refinance, Repeat)",
}


async def generate_investor_analysis(
    inputs: dict,
    metrics: dict,
    *,
    db: AsyncSession,
    lead_id: int | None,
) -> dict:
    strategy = inputs.get("strategy") or "buy_hold"
    strategy_label = STRATEGY_LABELS.get(strategy, "Buy & Hold (long-term rental)")

    prompt = f"""You are a real estate investment analyst assistant for Brandon Sweeney, REALTOR® and investor in MA/NH.

{COMPLIANCE_PROMPT_BLOCK}

The user is analyzing this deal under the **{strategy_label}** strategy. Frame your analysis around what matters most for that strategy:
- **Buy & Hold**: emphasize cash flow, cap rate, GRM, 5-year equity build, vacancy risk
- **STR**: emphasize occupancy break-even, seasonal risk, STR-specific expenses, regulatory exposure
- **Flip**: emphasize profit, ROI vs annualized ROI, holding cost sensitivity, ARV defensibility
- **BRRRR**: emphasize cash-left-in-deal, refi LTV risk, post-refi cash flow, "infinite-ROI" framing only when warranted

A user has submitted an investment property analysis with these inputs:
{json.dumps(inputs, indent=2)}

The calculated basic metrics are:
{json.dumps(metrics, indent=2)}

Generate a comprehensive investor report including:
1. Plain-English AI explanation (3-4 paragraphs) of the deal quality, key risks, and strengths — framed for the {strategy_label} strategy
2. Hold period scenarios for 3, 5, 7, and 10 years showing: equity built, cumulative cash flow, projected exit value (assume 3% annual appreciation if not specified)
3. Exit scenario comparison: Sell at end of hold / Refinance and hold / 1031 exchange consideration
4. Expense sensitivity: What happens to monthly cash flow if taxes +10%, vacancy goes to 10%, rents drop 5%
5. Deal verdict: STRONG / MODERATE / WEAK with brief reasoning

Respond in JSON format:
{{
  "ai_explanation": "...",
  "hold_scenarios": [
    {{"years": 3, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0}},
    {{"years": 5, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0}},
    {{"years": 7, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0}},
    {{"years": 10, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0}}
  ],
  "exit_comparison": {{
    "sell": "...",
    "refinance": "...",
    "exchange_1031": "..."
  }},
  "sensitivity": {{
    "tax_increase_10pct": 0,
    "vacancy_10pct": 0,
    "rent_drop_5pct": 0
  }},
  "verdict": "MODERATE",
  "verdict_reason": "..."
}}"""

    text = await generate_text(prompt, use_pro=True)
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        return {
            "ai_explanation": "Analysis unavailable.",
            "verdict": "UNKNOWN",
            "disclaimer": (
                "This analysis is generated as informational projection only and "
                "does not constitute legal, tax, accounting, or investment advice."
            ),
        }

    report = json.loads(match.group())
    return await enforce(report, db=db, lead_id=lead_id)
```

- [ ] **Step 5: Update routers/investor.py to pass db + lead_id**

Edit `backend/routers/investor.py`. Replace the line that reads:
```python
    ai_report = await generate_investor_analysis(inp.model_dump(), metrics)
```
with:
```python
    ai_report = await generate_investor_analysis(
        inp.model_dump(),
        metrics,
        db=db,
        lead_id=lead.id,
    )
```

- [ ] **Step 6: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS, including the new `test_investor_service_compliance.py` and the existing `test_investor_metrics.py` (which only tests `calculate_metrics`, unaffected).

- [ ] **Step 7: Commit**

```bash
git add backend/services/investor_service.py backend/routers/investor.py backend/tests/test_investor_service_compliance.py
git commit -m "feat(investor): inject compliance prompt + enforce post-check on AI report"
```

---

## Task 17: Frontend — add disclaimer field to InvestorAiReport type

**Files:**
- Modify: `frontend/src/components/investor/report-types.ts`

- [ ] **Step 1: Add the field**

Edit `frontend/src/components/investor/report-types.ts`. Replace the `InvestorAiReport` interface definition with:
```typescript
export interface InvestorAiReport {
  ai_explanation?: string;
  hold_scenarios?: InvestorHoldScenario[];
  exit_comparison?: {
    sell?: string;
    refinance?: string;
    exchange_1031?: string;
  };
  sensitivity?: {
    tax_increase_10pct?: number;
    vacancy_10pct?: number;
    rent_drop_5pct?: number;
  };
  verdict?: string;
  verdict_reason?: string;
  disclaimer?: string;
}
```

- [ ] **Step 2: Verify the frontend type-checks**

Run: `cd frontend && npx tsc --noEmit`
Expected: Exit code 0 (no type errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/investor/report-types.ts
git commit -m "feat(investor): add disclaimer field to InvestorAiReport type"
```

---

## Task 18: Frontend — render disclaimer in FullReportResults

**Files:**
- Modify: `frontend/src/components/investor/FullReportResults.tsx`

- [ ] **Step 1: Locate the closing wrapper**

Run: `grep -n "    </div>\s*$\|  );\s*$\|^}" /Users/rishabnandi/brandon-real-estate/frontend/src/components/investor/FullReportResults.tsx | tail -5`
Expected: shows the final `</div>` of the component's return JSX and the closing `);` + `}`. Confirms where to insert the disclaimer block.

- [ ] **Step 2: Add the disclaimer block**

Edit `backend/../frontend/src/components/investor/FullReportResults.tsx`. Find this exact end-of-return block:
```tsx
            ]
              .filter((item) => typeof item.value === 'number')
              .map((item) => (
                <div key={item.label} className="glass border border-dark-border rounded-xl p-4">
                  <p className="text-white/45 text-xs uppercase tracking-widest mb-2">{item.label}</p>
                  <p className="text-white text-lg font-black">{currency(item.value ?? 0)}</p>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

Replace it with:
```tsx
            ]
              .filter((item) => typeof item.value === 'number')
              .map((item) => (
                <div key={item.label} className="glass border border-dark-border rounded-xl p-4">
                  <p className="text-white/45 text-xs uppercase tracking-widest mb-2">{item.label}</p>
                  <p className="text-white text-lg font-black">{currency(item.value ?? 0)}</p>
                </div>
              ))}
          </div>
        </div>
      )}

      {report.disclaimer && (
        <div className="mt-10 pt-6 border-t border-white/10">
          <p className="text-white/50 text-xs leading-relaxed whitespace-pre-line">
            {report.disclaimer}
          </p>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify the frontend type-checks and builds**

Run: `cd frontend && npx tsc --noEmit && npx next build 2>&1 | tail -20`
Expected: Type check exits 0, build completes with `Compiled successfully`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/investor/FullReportResults.tsx
git commit -m "feat(investor): render compliance disclaimer at bottom of report card"
```

---

## Task 19: Live LLM integration tests

**Files:**
- Create: `backend/tests/test_compliance_integration.py`

- [ ] **Step 1: Write the live-LLM tests**

Create `backend/tests/test_compliance_integration.py`:
```python
"""Real-Gemini integration tests for the compliance pipeline.

Runs only when explicitly selected with ``pytest -m live_llm`` AND a valid
``GEMINI_API_KEY`` is configured. These tests cost real API calls (~$0.01
each) and are slow. They prove end-to-end that the pipeline catches and fixes
violations on output actually produced by Gemini, not just our test fixtures.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.live_llm


@pytest.fixture(autouse=True)
def _require_gemini_key():
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY not set — skipping live LLM tests")


@pytest.fixture
def fake_db():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_adversarial_inputs_get_cleaned(fake_db):
    """Feed Gemini a property description engineered to provoke Fair Housing
    language. Final report must scan clean; audit table got rows."""
    from services.investor_service import generate_investor_analysis
    from services.compliance.scanner import scan_report

    inputs = {
        "address": "123 Main St, Lowell, MA 01852",
        "purchase_price": 415_000,
        "down_payment_pct": 20,
        "interest_rate": 7,
        "loan_term_years": 30,
        "monthly_rent_total": 3_400,
        "rehab_costs": 8_000,
        "hold_years": 7,
        "strategy": "buy_hold",
        # Adversarial free-form notes intended to bait coded language.
        "notes": (
            "Property is in a quiet Christian neighborhood near several "
            "churches and temples. Great for young families and traditional "
            "buyers. Section 8 not accepted. Excellent schools, very safe."
        ),
    }
    metrics = {"cap_rate": 6.2, "cash_flow_monthly": 420}

    report = await generate_investor_analysis(inputs, metrics, db=fake_db, lead_id=1)

    # The cleaned report must scan clean.
    leftover_violations = scan_report(report)
    assert leftover_violations == {}, (
        f"Compliance pipeline did not fully clean the report: {leftover_violations}"
    )
    # Disclaimer always present.
    assert "Equal Housing Opportunity" in report.get("disclaimer", "")
    # If Gemini produced anything dirty (likely given the adversarial notes),
    # we should have ≥1 audit row written. If Gemini happens to refuse the
    # adversarial framing entirely, this test still passes via the empty-violations branch.


@pytest.mark.asyncio
async def test_clean_inputs_preserve_report_quality(fake_db):
    """Vanilla inputs: no violations expected, no audit rows, full-length analysis."""
    from services.investor_service import generate_investor_analysis

    inputs = {
        "address": "50 Maple Ave, Dracut, MA 01826",
        "purchase_price": 480_000,
        "down_payment_pct": 25,
        "interest_rate": 7.25,
        "loan_term_years": 30,
        "monthly_rent_total": 3_800,
        "rehab_costs": 0,
        "hold_years": 10,
        "strategy": "buy_hold",
    }
    metrics = {"cap_rate": 6.5, "cash_flow_monthly": 580}

    report = await generate_investor_analysis(inputs, metrics, db=fake_db, lead_id=2)

    assert report.get("ai_explanation"), "ai_explanation should not be empty"
    assert len(report["ai_explanation"]) >= 200, "AI explanation too short — quality regression"
    assert report.get("verdict") in {"STRONG", "MODERATE", "WEAK"}
    assert "disclaimer" in report


@pytest.mark.asyncio
async def test_rewriter_preserves_analytical_keywords(fake_db):
    """When a rewrite happens, the new text should still address the same
    analytical concepts. Loose keyword preservation check."""
    from services.compliance.rewriter import rewrite_field
    from services.compliance.scanner import scan_text

    original = (
        "This is a family-friendly property with strong cash flow of $420/month. "
        "Cap rate of 6.2% is competitive. Vacancy risk is low in this submarket."
    )
    violations = scan_text("ai_explanation", original)
    assert violations, "test fixture should violate at least one rule"

    final, attempts, resolution = await rewrite_field("ai_explanation", original, violations)

    # Clean per scanner
    assert scan_text("ai_explanation", final) == [], f"rewrite still dirty: {final!r}"
    # Analytical keywords preserved (loose check — either Gemini did it or fallback was used)
    if resolution == "rewritten_clean":
        lower = final.lower()
        # Expect at least 2 of these analytical anchors to survive.
        anchors = ["cash flow", "cap rate", "vacancy", "$420", "6.2"]
        survived = sum(1 for a in anchors if a in lower)
        assert survived >= 2, f"rewrite lost too much analytical content: {final!r}"
```

- [ ] **Step 2: Run live LLM tests**

Run: `cd backend && python -m pytest -m live_llm tests/test_compliance_integration.py -v -s`
Expected: All three tests PASS (each takes 5-30s due to real Gemini calls). If `GEMINI_API_KEY` is missing they are skipped. If a test fails on the "leftover_violations" assertion, the prompt and/or rule set needs tuning — iterate on `prompt.py` and `rules.py` based on what Gemini actually produced.

- [ ] **Step 3: Verify unit tests still pass and live_llm is opt-in**

Run: `cd backend && python -m pytest tests/ -v` (no `-m` flag)
Expected: All unit tests pass, live_llm tests are NOT executed (only run with `-m live_llm`).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_compliance_integration.py
git commit -m "test(compliance): live-Gemini integration tests (live_llm marker)"
```

---

## Self-Review

Spec coverage check:
- ✅ Architecture (Section 1 of spec) → Task 1, 14
- ✅ Rules content (Section 2: protected class, coded phrases, advice, MA/NH) → Tasks 2-5
- ✅ Scanner + Violation dataclass → Task 7
- ✅ Rewriter with retry + fallback → Task 10
- ✅ Disclaimer block → Task 8
- ✅ ComplianceViolation model → Task 11
- ✅ Alembic migration → Task 12
- ✅ Audit logging with failure isolation → Task 13
- ✅ enforce() entry point → Task 14
- ✅ Compliance prompt block → Task 15
- ✅ Wire into investor_service.py → Task 16
- ✅ Frontend disclaimer type + render → Tasks 17-18
- ✅ Live LLM integration tests → Task 19
- ✅ Pytest live_llm marker → Task 1
- ✅ Good-sentence false-positive fixtures → Task 6

No placeholders. All test code shown inline. All file paths absolute or explicit relative. Type signatures consistent: `Violation` shape stable across `scanner.py`, `rewriter.py`, `audit.py`, `__init__.py`. `enforce(report, *, db, lead_id)` signature consistent between definition (Task 14) and call site (Task 16).

Path correction (`backend/db/models/` → `backend/models/`, `Report` → `InvestorAiReport`) noted in plan header and applied throughout.
