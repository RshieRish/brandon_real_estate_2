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

    db = _make_db()

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


@pytest.mark.asyncio
async def test_generate_investor_analysis_fallback_when_json_unparseable():
    """When Gemini returns non-JSON garbage, we return the safe fallback with disclaimer."""
    from services.investor_service import generate_investor_analysis

    async def fake_generate_text(prompt: str, use_pro: bool = True) -> str:
        return "not json at all"

    db = _make_db()

    with patch("services.investor_service.generate_text", new=fake_generate_text):
        out = await generate_investor_analysis(
            {"address": "test", "strategy": "buy_hold"},
            {"cap_rate": 6.2},
            db=db,
            lead_id=None,
        )

    assert out["verdict"] == "UNKNOWN"
    assert out["ai_explanation"] == "Analysis unavailable."
    assert "disclaimer" in out


@pytest.mark.asyncio
async def test_unparseable_fallback_uses_full_disclaimer():
    """Fallback must use the same disclaimer as the happy path (Fair Housing + KW required)."""
    from services.investor_service import generate_investor_analysis
    from services.compliance.disclaimer import build_disclaimer

    async def fake_generate_text(prompt: str, use_pro: bool = True) -> str:
        return "not json at all"

    db = _make_db()

    with patch("services.investor_service.generate_text", new=fake_generate_text):
        out = await generate_investor_analysis(
            {"address": "test", "strategy": "buy_hold"},
            {"cap_rate": 6.2},
            db=db,
            lead_id=None,
        )

    assert out["disclaimer"] == build_disclaimer()
    # spot-check both required blocks
    assert "Equal Housing Opportunity" in out["disclaimer"]
    assert "Keller Williams Realty Success" in out["disclaimer"]
