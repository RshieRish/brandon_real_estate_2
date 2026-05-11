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
        pattern=_ci(r"\b(?:1031|like[- ]kind)\s+exchange\s+(?:will|guarantees?)\s+(?:you\s+)?(?:defer|avoid|eliminate)"),
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


MA_NH_LANDMINES: tuple[Rule, ...] = (
    Rule(
        id="SL-001",
        category="state_specific",
        pattern=_ci(r"(?<!\bno )\brent\s+control\b"),
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
