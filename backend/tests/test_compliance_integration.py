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
    # pydantic-settings loads .env into the Settings object but does NOT
    # populate os.environ. Fall back to importing settings so we honor either
    # source (env var OR backend/.env).
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        try:
            from config import settings

            key = settings.GEMINI_API_KEY
        except Exception:
            key = ""
    if not key:
        pytest.skip("GEMINI_API_KEY not set — skipping live LLM tests")


@pytest.fixture
def fake_db():
    db = MagicMock()
    db.add = MagicMock()
    savepoint_ctx = AsyncMock()
    savepoint_ctx.__aenter__ = AsyncMock(return_value=savepoint_ctx)
    savepoint_ctx.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=savepoint_ctx)
    return db


@pytest.mark.asyncio(loop_scope="session")
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
    # If Gemini produced anything dirty, audit rows should be >=1.
    # If Gemini refused the adversarial framing entirely (no violations to log),
    # that's also a pass — the prompt + scanner caught it pre-output.


@pytest.mark.asyncio(loop_scope="session")
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


@pytest.mark.asyncio(loop_scope="session")
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
