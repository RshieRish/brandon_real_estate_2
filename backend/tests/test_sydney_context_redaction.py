from __future__ import annotations

import json

import pytest


def test_redaction_is_deterministic_and_preserves_ordinary_business_pii() -> None:
    from services.sydney_context_redaction import redact_content

    source = (
        "Contact Jane Agent at jane@example.com or +1 (404) 555-0123 about "
        "18 Gold Street. Authorization: Bearer abc.def.ghi and password=hunter42"
    )

    first = redact_content(source)
    second = redact_content(source)

    assert first == second
    assert first.changed is True
    assert "jane@example.com" in first.text
    assert "+1 (404) 555-0123" in first.text
    assert "18 Gold Street" in first.text
    assert "abc.def.ghi" not in first.text
    assert "hunter42" not in first.text
    assert "[REDACTED_BEARER_TOKEN]" in first.text
    assert "[REDACTED_PASSWORD]" in first.text
    assert len(first.sha256) == 64


def test_redaction_covers_nested_urls_json_oauth_and_signed_fragments() -> None:
    from services.sydney_context_redaction import redact_content

    nested = json.dumps(
        {
            "url": (
                "https://www.soldwithsweeney.com/admin/command?access_token=oauth-value"
                "#handoff=signed-fragment-value"
            ),
            "refresh_token": "refresh-value",
            "api_key": "api-key-value",
            "cookie": "session=private-cookie-value",
        }
    )

    result = redact_content(nested)

    for secret in (
        "oauth-value",
        "signed-fragment-value",
        "refresh-value",
        "api-key-value",
        "private-cookie-value",
    ):
        assert secret not in result.text
    assert "[REDACTED_SIGNED_FRAGMENT]" in result.text
    assert "[REDACTED_OAUTH_TOKEN]" in result.text
    assert "[REDACTED_API_KEY]" in result.text
    assert "[REDACTED_COOKIE]" in result.text


def test_redaction_removes_runtime_configured_values_without_echoing_them() -> None:
    from services.sydney_context_redaction import redact_content

    secret = "runtime-secret-value-that-must-never-persist"
    result = redact_content(
        f"opaque={secret}; again={secret}; label=short",
        configured_secrets=("", secret, "short"),
    )

    assert secret not in result.text
    assert "[REDACTED_CONFIGURED_SECRET]" in result.text
    assert "short" in result.text


@pytest.mark.parametrize("max_chars", [0, -1])
def test_split_utf8_text_rejects_nonpositive_limits(max_chars: int) -> None:
    from services.sydney_context_redaction import split_utf8_text

    with pytest.raises(ValueError, match="^max_chars must be positive$"):
        split_utf8_text("hello", max_chars=max_chars)


def test_split_utf8_text_is_lossless_and_character_safe() -> None:
    from services.sydney_context_redaction import split_utf8_text

    value = "Sydney remembers café listings and 🏠 details."
    segments = split_utf8_text(value, max_chars=7)

    assert "".join(segments) == value
    assert all(len(segment) <= 7 for segment in segments)
    assert split_utf8_text("", max_chars=7) == ("",)
