from services.gemini import generate_text
import json, re


STRATEGY_LABELS: dict[str, str] = {
    "buy_hold": "Buy & Hold (long-term rental)",
    "str": "Short-Term Rental (Airbnb / VRBO)",
    "flip": "Fix & Flip",
    "brrrr": "BRRRR (Buy, Rehab, Rent, Refinance, Repeat)",
}


async def generate_investor_analysis(inputs: dict, metrics: dict) -> dict:
    strategy = inputs.get("strategy") or "buy_hold"
    strategy_label = STRATEGY_LABELS.get(strategy, "Buy & Hold (long-term rental)")

    prompt = f"""You are a real estate investment analyst assistant for Brandon Sweeney, REALTOR® and investor in MA/NH.

The user is analyzing this deal under the **{strategy_label}** strategy. Frame your analysis around what matters most for that strategy:
- **Buy & Hold**: emphasize cash flow, cap rate, GRM, 5-year equity build, vacancy risk
- **STR**: emphasize occupancy break-even, seasonal risk, STR-specific expenses, regulatory exposure
- **Flip**: emphasize profit, ROI vs annualized ROI, holding cost sensitivity, ARV defensibility
- **BRRRR**: emphasize cash-left-in-deal, refi LTV risk, post-refi cash flow, "infinite-ROI" framing only when warranted

A user has submitted an investment property analysis with these inputs:
{json.dumps(inputs, indent=2)}

The calculated basic metrics are:
{json.dumps(metrics, indent=2)}

Generate a comprehensive investor report including:
1. Plain-English AI explanation (3-4 paragraphs) of the deal quality, key risks, and strengths — framed for the {strategy_label} strategy
2. Hold period scenarios for 3, 5, 7, and 10 years showing: equity built, cumulative cash flow, projected exit value (assume 3% annual appreciation if not specified)
3. Exit scenario comparison: Sell at end of hold / Refinance and hold / 1031 exchange consideration
4. Expense sensitivity: What happens to monthly cash flow if taxes +10%, vacancy goes to 10%, rents drop 5%
5. Deal verdict: STRONG / MODERATE / WEAK with brief reasoning

Respond in JSON format:
{{
  "ai_explanation": "...",
  "hold_scenarios": [
    {{"years": 3, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0}},
    {{"years": 5, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0}},
    {{"years": 7, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0}},
    {{"years": 10, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0}}
  ],
  "exit_comparison": {{
    "sell": "...",
    "refinance": "...",
    "exchange_1031": "..."
  }},
  "sensitivity": {{
    "tax_increase_10pct": 0,
    "vacancy_10pct": 0,
    "rent_drop_5pct": 0
  }},
  "verdict": "MODERATE",
  "verdict_reason": "..."
}}"""

    text = await generate_text(prompt, use_pro=True)
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        return json.loads(match.group())
    return {"ai_explanation": "Analysis unavailable.", "verdict": "UNKNOWN"}
