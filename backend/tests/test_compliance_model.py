def test_compliance_violation_model_fields():
    from models.compliance_violation import ComplianceViolation

    inst = ComplianceViolation(
        lead_id=1,
        source="investor_report",
        rule_id="FH-001",
        category="fair_housing",
        severity="hard",
        field_path="ai_explanation",
        matched_text="families with children",
        original_text="Great for families with children.",
        final_text="Great 3-bed layout.",
        rewrite_attempts=1,
        resolution="rewritten_clean",
    )
    assert inst.rule_id == "FH-001"
    assert inst.rewrite_attempts == 1
    assert inst.__tablename__ == "compliance_violations"
