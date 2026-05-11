"""Prompt fragment injected into the investor-report Gemini prompt.

This is the *first* layer of compliance defense — the scanner is the second.
Keeps Gemini from generating the most common Fair Housing and unauthorized-
advice slip-ups in the first place, so the rewriter is rarely needed.
"""

COMPLIANCE_PROMPT_BLOCK = """
COMPLIANCE REQUIREMENTS — read carefully and follow strictly:

1. FAIR HOUSING. Do NOT reference, target, or exclude any protected class:
   race, color, national origin, religion, sex, familial status, disability,
   age, marital status, sexual orientation, gender identity, source of income
   (including Section 8 / housing vouchers), military/veteran status, genetic
   information, or ancestry. This applies to Federal FHA, MA Ch. 151B, and
   NH RSA 354-A.

2. NO CODED LANGUAGE. Do NOT use HUD-flagged steering phrases such as
   "family-friendly", "good for young professionals", "up-and-coming
   neighborhood", "safe neighborhood", "good schools", "exclusive community",
   "traditional family", "walking distance to churches/temples", or similar.
   Describe physical features, transit, walkability, or cite objective metrics
   with sources instead.

3. NO UNAUTHORIZED ADVICE. Provide no specific legal, tax, accounting, or
   investment advice. Do NOT claim guaranteed returns, guaranteed
   appreciation, or guaranteed tax outcomes. Any mention of a 1031 exchange,
   depreciation, or tax strategy must recommend consulting a CPA, attorney,
   or qualified intermediary. Use "projected", "historical average", or
   "potential" rather than "guaranteed" or "will".

4. STATE LAW. Do NOT claim rent control exists in Massachusetts (banned
   statewide since 1994) or New Hampshire (never existed). Do NOT
   understate security-deposit obligations (MA Ch. 186 §15B), lead-paint
   disclosure requirements, or eviction timelines. Do NOT generalize STR
   legality across MA/NH — it is per-municipality.

5. PROFESSIONAL TITLES. Refer to Brandon as a "licensed real estate agent",
   not a "licensed REALTOR®". REALTOR® is a trade-association membership
   mark, never a license.

Write the investor report assuming the reader will consult an attorney, CPA,
and lender before acting. Default to objective metrics and projections, not
promises.
""".strip()
