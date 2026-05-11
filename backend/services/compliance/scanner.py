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
