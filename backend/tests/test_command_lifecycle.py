import pytest

from services.command_lifecycle import ensure_agreement_transition


def test_agreement_lifecycle_allows_normal_forward_progression():
    ensure_agreement_transition("draft", "in_review")
    ensure_agreement_transition("ready", "shared")
    ensure_agreement_transition("viewed", "completed")


def test_agreement_lifecycle_rejects_terminal_or_backward_transition():
    with pytest.raises(ValueError, match="not allowed"):
        ensure_agreement_transition("completed", "shared")
    with pytest.raises(ValueError, match="not allowed"):
        ensure_agreement_transition("shared", "draft")
