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
        pattern=_ci(r"\bwalk(?:ing)?\s+distance\s+to\s+(?:\w+\s+){0,3}?(?:churches?|temples?|mosques?|synagogues?)\b"),
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
