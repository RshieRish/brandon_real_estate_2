from services.gemini import generate_text
from services.compliance import enforce
from services.compliance.prompt import COMPLIANCE_PROMPT_BLOCK
from services.compliance.disclaimer import build_disclaimer
import json
import re

from sqlalchemy.ext.asyncio import AsyncSession


STRATEGY_LABELS: dict[str, str] = {
    "buy_hold": "Buy & Hold (long-term rental)",
    "str": "Short-Term Rental (Airbnb / VRBO)",
    "flip": "Fix & Flip",
    "brrrr": "BRRRR (Buy, Rehab, Rent, Refinance, Repeat)",
}


def _unparseable_fallback() -> dict:
    return {
        "ai_explanation": "Analysis unavailable.",
        "verdict": "UNKNOWN",
        "disclaimer": build_disclaimer(),
    }


async def generate_investor_analysis(
    inputs: dict,
    metrics: dict,
    *,
    db: AsyncSession,
    lead_id: int | None,
) -> dict:
    strategy = inputs.get("strategy") or "buy_hold"
    strategy_label = STRATEGY_LABELS.get(strategy, "Buy & Hold (long-term rental)")

    prompt = (
        "You are a real estate investment analyst assistant for Brandon Sweeney, "
        "REALTOR® and investor in MA/NH.\n\n"
        f"{COMPLIANCE_PROMPT_BLOCK}\n\n"
        f"The user is analyzing this deal under the **{strategy_label}** strategy. "
        "Frame your analysis around what matters most for that strategy:\n"
        "- **Buy & Hold**: emphasize cash flow, cap rate, GRM, 5-year equity build, vacancy risk\n"
        "- **STR**: emphasize occupancy break-even, seasonal risk, STR-specific expenses, regulatory exposure\n"
        "- **Flip**: emphasize profit, ROI vs annualized ROI, holding cost sensitivity, ARV defensibility\n"
        "- **BRRRR**: emphasize cash-left-in-deal, refi LTV risk, post-refi cash flow, \"infinite-ROI\" framing only when warranted\n\n"
        "A user has submitted an investment property analysis with these inputs:\n"
        f"{json.dumps(inputs, indent=2)}\n\n"
        "The calculated basic metrics are:\n"
        f"{json.dumps(metrics, indent=2)}\n\n"
        "Generate a comprehensive investor report including:\n"
        f"1. Plain-English AI explanation (3-4 paragraphs) of the deal quality, key risks, and strengths — framed for the {strategy_label} strategy\n"
        "2. Hold period scenarios for 3, 5, 7, and 10 years showing: equity built, cumulative cash flow, projected exit value (assume 3% annual appreciation if not specified)\n"
        "3. Exit scenario comparison: Sell at end of hold / Refinance and hold / 1031 exchange consideration\n"
        "4. Expense sensitivity: What happens to monthly cash flow if taxes +10%, vacancy goes to 10%, rents drop 5%\n"
        "5. Deal verdict: STRONG / MODERATE / WEAK with brief reasoning\n\n"
        "Respond in JSON format:\n"
        "{\n"
        '  "ai_explanation": "...",\n'
        '  "hold_scenarios": [\n'
        '    {"years": 3, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0},\n'
        '    {"years": 5, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0},\n'
        '    {"years": 7, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0},\n'
        '    {"years": 10, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0}\n'
        '  ],\n'
        '  "exit_comparison": {\n'
        '    "sell": "...",\n'
        '    "refinance": "...",\n'
        '    "exchange_1031": "..."\n'
        '  },\n'
        '  "sensitivity": {\n'
        '    "tax_increase_10pct": 0,\n'
        '    "vacancy_10pct": 0,\n'
        '    "rent_drop_5pct": 0\n'
        '  },\n'
        '  "verdict": "MODERATE",\n'
        '  "verdict_reason": "..."\n'
        "}"
    )

    text = await generate_text(prompt, use_pro=True)
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        return _unparseable_fallback()
    try:
        report = json.loads(match.group())
    except json.JSONDecodeError:
        return _unparseable_fallback()
    return await enforce(report, db=db, lead_id=lead_id)
