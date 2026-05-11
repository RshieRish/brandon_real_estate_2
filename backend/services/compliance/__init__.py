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
