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
    """Write one ``ComplianceViolation`` row per violation. Never raises.

    Uses a SAVEPOINT so an audit write failure does NOT break the caller's
    surrounding transaction (e.g., the Lead row being inserted in the same
    router call). On failure, only the savepoint rolls back.
    """
    try:
        async with db.begin_nested():  # SAVEPOINT
            for field_path, violations in violations_by_field.items():
                outcome = field_outcomes.get(field_path)
                if outcome is None:
                    logger.warning(
                        "compliance.audit: scanner reported violations for field %r "
                        "but rewriter produced no outcome — %d violations not audited "
                        "for lead_id=%s",
                        field_path,
                        len(violations),
                        lead_id,
                    )
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
            # exit of begin_nested() context implicitly flushes the SAVEPOINT
    except Exception:
        logger.exception(
            "compliance.audit.log_violations failed for lead_id=%s — continuing",
            lead_id,
        )
