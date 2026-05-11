from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_db():
    db = MagicMock()
    db.add = MagicMock()
    savepoint_ctx = AsyncMock()
    savepoint_ctx.__aenter__ = AsyncMock(return_value=savepoint_ctx)
    savepoint_ctx.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=savepoint_ctx)
    return db


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
    db = _make_db()

    out = await compliance.enforce(report, db=db, lead_id=1)
    assert out["ai_explanation"] == "Cap rate is 6.2% with stable comps."
    assert "Equal Housing Opportunity" in out["disclaimer"]
    assert db.add.call_count == 0  # no violations → no audit rows


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
    db = _make_db()

    async def fake_rewriter(field_name, original_text, violations):
        return ("Clean rewrite.", 1, "rewritten_clean")

    with patch("services.compliance.rewrite_field", new=fake_rewriter):
        out = await compliance.enforce(report, db=db, lead_id=1)

    assert out["ai_explanation"] == "Clean rewrite."
    assert "disclaimer" in out
    # ≥2 violations on ai_explanation (family-friendly + young professionals)
    assert db.add.call_count >= 2


@pytest.mark.asyncio
async def test_enforce_does_not_mutate_input_report():
    """Caller's report dict must NOT be mutated."""
    from services import compliance

    report = {"ai_explanation": "Cap rate is 6.2%.", "exit_comparison": {}, "verdict": "MODERATE", "verdict_reason": "Clean.", "hold_scenarios": []}
    original = {**report}
    db = _make_db()

    out = await compliance.enforce(report, db=db, lead_id=None)
    assert report == original  # input unchanged
    assert "disclaimer" in out
    assert "disclaimer" not in report
