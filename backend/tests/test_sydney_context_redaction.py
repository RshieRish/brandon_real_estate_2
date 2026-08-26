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


@pytest.mark.parametrize(
    "payload",
    (
        {"authorization": "opaque-session-secret-123456789"},
        {"sessionToken": "opaque-session-secret-123456789"},
        {
            "credential": {
                "value": "opaque-session-secret-123456789",
                "copies": ["opaque-session-secret-123456789"],
            }
        },
    ),
)
def test_redaction_covers_structured_secret_key_subtrees(
    payload: dict[str, object],
) -> None:
    from services.sydney_context_redaction import redact_content

    secret = "opaque-session-secret-123456789"
    result = redact_content(json.dumps(payload))

    assert result.changed is True
    assert secret not in result.text
    assert "[REDACTED_" in result.text


def test_redaction_recurses_into_encoded_login_redirects_without_losing_selectors() -> (
    None
):
    from services.sydney_context_redaction import redact_content

    direct_code = "direct-oauth-code"
    nested_code = "nested-oauth-code"
    nested_state = "nested-oauth-state"
    nested_signature = "nested-signature"
    source = json.dumps(
        {
            "direct": (
                "https://auth.example.test/callback?proposal_id=proposal-7"
                f"&code={direct_code}"
            ),
            "encoded": (
                "https://www.soldwithsweeney.com/login?proposal_id=proposal-8&"
                "return_to=https%3A%2F%2Fauth.example.test%2Fcallback%3F"
                f"code%3D{nested_code}%26state%3D{nested_state}"
            ),
            "json_wrapped": (
                "https://www.soldwithsweeney.com/login?payload=%7B%22redirect%22%3A"
                "%22https%3A%2F%2Fauth.example.test%2Fcallback%3Fsignature%3D"
                f"{nested_signature}%22%7D"
            ),
        }
    )

    result = redact_content(source)

    for secret in (direct_code, nested_code, nested_state, nested_signature):
        assert secret not in result.text
    assert "proposal_id=proposal-7" in result.text
    assert "proposal_id=proposal-8" in result.text
    assert result.text.count("REDACTED") >= 4


def test_redaction_covers_context_labeled_uuid_tokens_and_database_uri_passwords() -> (
    None
):
    from services.sydney_context_redaction import redact_content

    first_token = "11111111-2222-4333-8444-555555555555"
    second_token = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    database_password = "database-password-value"
    source = (
        f"{first_token}\n\nhere is the token, use it for deployment. "
        f"The API token is {second_token}. "
        "DATABASE_URL=postgresql+asyncpg://dbuser:"
        f"{database_password}@database.example.test/app"
    )

    result = redact_content(source)

    assert first_token not in result.text
    assert second_token not in result.text
    assert database_password not in result.text
    assert result.text.count("[REDACTED_CONTEXT_TOKEN]") == 2
    assert "[REDACTED_URI_PASSWORD]" in result.text


def test_redaction_covers_unlabeled_well_known_provider_key_formats() -> None:
    from services.sydney_context_redaction import redact_content

    google_key = "AIza" + "A" * 35
    github_key = "ghp_" + "b" * 36
    openai_key = "sk-" + "c" * 32

    result = redact_content(
        f"Copied values: {google_key}, {github_key}, and {openai_key}."
    )

    assert google_key not in result.text
    assert github_key not in result.text
    assert openai_key not in result.text
    assert result.text.count("[REDACTED_PROVIDER_TOKEN]") == 3


@pytest.mark.parametrize(
    ("source", "secret"),
    [
        ("my password is hunter2plus", "hunter2plus"),
        ("client secret is supersecretvalue", "supersecretvalue"),
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("authorization: Token opaque-credential-value", "opaque-credential-value"),
    ],
)
def test_redaction_covers_natural_language_assignments_and_auth_headers(
    source: str,
    secret: str,
) -> None:
    from services.sydney_context_redaction import redact_content

    result = redact_content(source)

    assert result.changed is True
    assert secret not in result.text
    assert "[REDACTED_" in result.text


@pytest.mark.parametrize(
    ("source", "secret_tail"),
    [
        ('password="correct horse battery staple"; note=keep', "horse battery staple"),
        ("client secret='alpha beta gamma delta'; note=keep", "beta gamma delta"),
    ],
)
def test_redaction_consumes_complete_multiword_quoted_assignments(
    source: str,
    secret_tail: str,
) -> None:
    from services.sydney_context_redaction import redact_content

    result = redact_content(source)

    assert result.changed is True
    assert secret_tail not in result.text
    assert "[REDACTED_PASSWORD]" in result.text
    assert "note=keep" in result.text


@pytest.mark.parametrize(
    ("source", "secret"),
    [
        ("session_token=opaque-session-value", "opaque-session-value"),
        ("session-token: opaque-session-value", "opaque-session-value"),
        ("handoff=short-handoff-secret", "short-handoff-secret"),
        ("token=shortsecret123", "shortsecret123"),
    ],
)
def test_redaction_covers_plain_token_session_and_handoff_assignments(
    source: str,
    secret: str,
) -> None:
    from services.sydney_context_redaction import redact_content

    result = redact_content(source)

    assert result.changed is True
    assert secret not in result.text
    assert "[REDACTED_" in result.text


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


def test_redaction_removes_encoded_configured_values_at_every_supported_depth() -> None:
    from urllib.parse import quote

    from services.sydney_context_redaction import redact_content

    secret = "runtime/secret?with=value and space"
    encoded_once = quote(secret, safe="")
    encoded_twice = quote(encoded_once, safe="")
    source = (
        f"https://example.test/callback?opaque={encoded_once}&nested={encoded_twice}"
    )

    result = redact_content(source, configured_secrets=(secret,))

    assert secret not in result.text
    assert encoded_once not in result.text
    assert encoded_twice not in result.text
    assert "REDACTED_CONFIGURED_SECRET" in result.text


@pytest.mark.parametrize(
    "source",
    (
        "https://example.test/callback?note=hello%20world",
        (
            "https://example.test/login?return_to="
            "https%3A%2F%2Fother.test%2Fpath%3Fnote%3Dhello%2520world"
        ),
        "https://example.test/path#section=review%20queue",
    ),
)
def test_redaction_preserves_harmless_encoded_urls_byte_for_byte(source: str) -> None:
    from services.sydney_context_redaction import redact_content

    result = redact_content(source)

    assert result.text == source
    assert result.changed is False


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
