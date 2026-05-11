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


def _make_db(add_side_effect=None):
    """Build a mock AsyncSession that supports ``async with db.begin_nested():``."""
    db = MagicMock()
    db.add = MagicMock(side_effect=add_side_effect)
    savepoint_ctx = AsyncMock()
    savepoint_ctx.__aenter__ = AsyncMock(return_value=savepoint_ctx)
    savepoint_ctx.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=savepoint_ctx)
    return db


@pytest.mark.asyncio
async def test_log_violations_writes_one_row_per_violation():
    from services.compliance.audit import log_violations

    db = _make_db()
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
    db.begin_nested.assert_called_once()  # savepoint was used
    first_row = db.add.call_args_list[0].args[0]
    assert first_row.lead_id == 42
    assert first_row.rule_id == "FH-001"
    assert first_row.original_text == "Original txt with families with children."
    assert first_row.final_text == "Clean text."
    assert first_row.rewrite_attempts == 1
    assert first_row.resolution == "rewritten_clean"


@pytest.mark.asyncio
async def test_log_violations_swallows_db_errors(caplog):
    """When db.add raises mid-savepoint, the savepoint context rolls back and
    log_violations swallows the error rather than propagating it."""
    from services.compliance.audit import log_violations

    db = _make_db(add_side_effect=RuntimeError("DB down"))

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


@pytest.mark.asyncio
async def test_log_violations_warns_when_outcome_missing(caplog):
    """A violation with no matching field_outcome should log a warning, not silently drop."""
    import logging
    from services.compliance.audit import log_violations

    db = _make_db()
    with caplog.at_level(logging.WARNING, logger="services.compliance.audit"):
        await log_violations(
            db,
            lead_id=7,
            violations_by_field={"ai_explanation": [_violation()]},
            field_outcomes={},  # no outcome for ai_explanation
        )
    assert db.add.call_count == 0
    assert any("rewriter produced no outcome" in r.message for r in caplog.records)
