"""Sentences that must NOT trigger any compliance rule.

These lock the false-positive baseline. If a rule change adds a match here,
the rule was too broad and needs scoping.
"""

GOOD_SENTENCES: tuple[str, ...] = (
    # Plain financial analysis
    "Projected monthly cash flow is $420 after debt service and vacancy reserve.",
    "Cap rate of 6.2% based on $32,400 NOI and $522,000 purchase price.",
    "Gross rent multiplier of 11.4 is on the lower end for this submarket.",
    "5-year equity build totals $58,000 assuming 3% annual appreciation.",
    "Stress-testing rents at -5% yields negative monthly cash flow.",
    # Property descriptions without coded language
    "Three-bedroom single-family on a 0.18-acre lot with attached one-car garage.",
    "Renovated in 2019 with new HVAC, roof, and updated kitchen.",
    "Lot backs to conservation land for natural privacy buffer.",
    "Walkability score of 72 per Walk Score; near commuter rail station.",
    # Strategy framing
    "BRRRR refinance assumes 75% LTV at appraised post-rehab value.",
    "Short-term rental occupancy break-even is 58% at current ADR.",
    "Fix-and-flip ARV of $640,000 supported by three comparable sales within 0.5 miles.",
    "Buy-and-hold strategy requires sustained rent growth of 2.8% annually.",
    # Advice that includes the required consult disclaimer
    "Consider a Section 1031 exchange — consult a qualified intermediary and CPA before any sale.",
    "Tax depreciation may offset rental income; confirm with your CPA.",
    "MA Chapter 186 governs security deposits; have an attorney review your lease.",
    # State context done correctly
    "Massachusetts has no rent control; market rents apply.",
    "MA Chapter 186 §15B requires a separate interest-bearing escrow for security deposits.",
    "Lead paint disclosure is mandatory for pre-1978 properties under federal and MA law.",
    "STR legality varies by municipality in MA — confirm with the local bylaw.",
)
