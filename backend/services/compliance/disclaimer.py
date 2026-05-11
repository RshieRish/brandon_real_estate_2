"""Standard disclaimer block appended to every investor report.

Three concatenated paragraphs covering NAR Articles 11/13 (not-advice),
Federal + MA + NH Fair Housing, and KW broker disclosure (mirrors the
existing site footer per CLAUDE.md).
"""

_NOT_ADVICE = (
    "This analysis is generated as informational projection only and does not "
    "constitute legal, tax, accounting, or investment advice. Consult a licensed "
    "attorney, CPA, and your loan officer before acting on any figures."
)

_FAIR_HOUSING = (
    "Sold With Sweeney & Co. is an Equal Housing Opportunity provider. We comply "
    "with the Federal Fair Housing Act and applicable Massachusetts and New "
    "Hampshire fair housing laws."
)

_KW_BROKER = (
    "Brandon Sweeney is a licensed real estate agent in MA & NH. Sold With "
    "Sweeney & Co. is powered by Keller Williams Realty Success. Each office is "
    "independently owned and operated."
)


def build_disclaimer() -> str:
    """Return the three-paragraph disclaimer block."""
    return "\n\n".join((_NOT_ADVICE, _FAIR_HOUSING, _KW_BROKER))
