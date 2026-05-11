def test_compliance_prompt_block_contains_required_guidance():
    from services.compliance.prompt import COMPLIANCE_PROMPT_BLOCK

    text = COMPLIANCE_PROMPT_BLOCK.lower()
    # Fair Housing
    assert "fair housing" in text
    assert "protected class" in text or "protected classes" in text
    # NAR ethics
    assert "no legal" in text or "not legal" in text or "no specific legal" in text
    # Disclaimer reminder
    assert "consult" in text
    # State context
    assert "massachusetts" in text or "ma" in text
    assert "new hampshire" in text or "nh" in text
