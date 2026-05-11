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
