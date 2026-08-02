from services.compliance.disclaimer import build_disclaimer


def test_disclaimer_contains_required_blocks():
    text = build_disclaimer()
    # not-advice block
    assert "not constitute legal, tax, accounting, or investment advice" in text
    # fair housing block
    assert "Equal Housing Opportunity" in text
    assert "Federal Fair Housing Act" in text
    # eXp broker block
    assert "brokered by eXp Realty" in text
    assert "Keller Williams Realty Success" not in text
    assert "independently owned and operated" not in text


def test_disclaimer_is_stable():
    """Result is deterministic across calls."""
    assert build_disclaimer() == build_disclaimer()
