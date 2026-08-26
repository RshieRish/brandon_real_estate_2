from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest


def test_history_excerpt_schema_is_bounded_and_signals_truncation() -> None:
    from schemas.sydney_context import ContextSourceExcerpt

    excerpt = ContextSourceExcerpt(
        event_id=uuid4(),
        event_type="assistant",
        occurred_at=datetime(2026, 8, 25, 17, 0, tzinfo=UTC),
        content="bounded",
        content_truncated=True,
    )

    assert excerpt.content_truncated is True


def test_prepare_event_redacts_segments_and_hashes_canonical_content() -> None:
    from schemas.sydney_context import ContextEventInput
    from services.sydney_context_service import prepare_event

    event = ContextEventInput(
        source_event_key="session-1:message-1",
        event_type="user",
        role="user",
        occurred_at=datetime(2026, 8, 25, 17, 0, tzinfo=UTC),
        content="remember café password=hunter42 and the gold folder",
        metadata={"telegram_message_id": "11"},
    )

    prepared = prepare_event(event, segment_chars=12)

    assert (
        prepared.content
        == "remember café password=[REDACTED_PASSWORD] and the gold folder"
    )
    assert "hunter42" not in prepared.content
    assert "".join(prepared.segments) == prepared.content
    assert all(len(segment) <= 12 for segment in prepared.segments)
    assert len(prepared.content_sha256) == 64
    assert prepared.redaction_status == "redacted"


@pytest.mark.parametrize(
    "secret",
    (
        'configured-secret-with-a-"-quote',
        "configured-secret-with-a-\\-slash",
        "configured-secret-with-a-\n-newline",
    ),
)
def test_prepare_event_redacts_nested_metadata_before_json_escaping(
    secret: str,
) -> None:
    from schemas.sydney_context import ContextEventInput
    from services.sydney_context_service import prepare_event

    event = ContextEventInput(
        source_event_key="session-1:metadata-secret",
        event_type="user",
        role="user",
        occurred_at=datetime(2026, 8, 25, 17, 0, tzinfo=UTC),
        content="ordinary content",
        metadata={
            "nested": [{"opaque": f"before {secret} after"}],
            "credentials": {"client_secret": "unlabeled-sensitive-value"},
        },
    )

    prepared = prepare_event(event, configured_secrets=(secret,))

    assert prepared.metadata["nested"][0]["opaque"] == (
        "before [REDACTED_CONFIGURED_SECRET] after"
    )
    assert prepared.metadata["credentials"]["client_secret"] == ("[REDACTED_SECRET]")
    assert secret not in json.dumps(prepared.metadata, ensure_ascii=False)


@pytest.mark.parametrize("key", ("token", "secret", "credentials", "pwd"))
def test_prepare_event_redacts_generic_secret_bearing_metadata_fields(key: str) -> None:
    from schemas.sydney_context import ContextEventInput
    from services.sydney_context_service import prepare_event

    secret = "opaque-generic-metadata-secret"
    event = ContextEventInput(
        source_event_key=f"session-1:metadata-{key}",
        event_type="user",
        role="user",
        occurred_at=datetime(2026, 8, 25, 17, 0, tzinfo=UTC),
        content="ordinary content",
        metadata={"nested": [{key: secret}]},
    )

    prepared = prepare_event(event)

    assert prepared.metadata == {"nested": [{key: "[REDACTED_SECRET]"}]}
    assert secret not in json.dumps(prepared.metadata)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    (
        (
            "credentials",
            {"value": "nested-secret", "items": ["list-secret"]},
            {
                "value": "[REDACTED_SECRET]",
                "items": ["[REDACTED_SECRET]"],
            },
        ),
        (
            "authorization",
            ["Bearer nested-secret", {"value": "deeper-secret"}],
            ["[REDACTED_SECRET]", {"value": "[REDACTED_SECRET]"}],
        ),
    ),
)
def test_prepare_event_redacts_entire_secret_bearing_metadata_subtrees(
    key: str,
    value: object,
    expected: object,
) -> None:
    from schemas.sydney_context import ContextEventInput
    from services.sydney_context_service import prepare_event

    event = ContextEventInput(
        source_event_key=f"session-1:metadata-container:{key}",
        event_type="user",
        role="user",
        occurred_at=datetime(2026, 8, 25, 17, 0, tzinfo=UTC),
        content="ordinary content",
        metadata={key: value},
    )

    prepared = prepare_event(event)

    assert prepared.metadata == {key: expected}
    encoded = json.dumps(prepared.metadata)
    assert "nested-secret" not in encoded
    assert "deeper-secret" not in encoded


@pytest.mark.parametrize(
    "key",
    (
        "accessToken",
        "refreshToken",
        "idToken",
        "bearerToken",
        "clientSecret",
        "apiKey",
        "APIKey",
        "setCookie",
        "client-secret",
    ),
)
def test_prepare_event_redacts_camelcase_and_hyphenated_metadata_keys(
    key: str,
) -> None:
    from schemas.sydney_context import ContextEventInput
    from services.sydney_context_service import prepare_event

    secret = "opaque-metadata-secret-that-must-not-persist"
    event = ContextEventInput(
        source_event_key=f"session-1:metadata:{key}",
        event_type="tool_call",
        role="assistant",
        occurred_at=datetime(2026, 8, 25, 17, 0, tzinfo=UTC),
        content="ordinary content",
        metadata={"nested": [{key: secret}]},
    )

    prepared = prepare_event(event)

    assert prepared.metadata == {"nested": [{key: "[REDACTED_SECRET]"}]}
    assert secret not in json.dumps(prepared.metadata, ensure_ascii=False)


def test_configured_secret_collection_reads_the_live_bridge_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from routers.agent_control_context import _configured_secrets

    secret = "opaque-bridge-secret-that-is-not-self-identifying"
    monkeypatch.setenv("BRANDON_AGENT_CONTROL_TOKEN", secret)

    assert secret in _configured_secrets()


def test_canonical_json_hash_ignores_mapping_order_and_rejects_nonfinite() -> None:
    import pytest
    from services.sydney_context_service import canonical_json_hash

    assert canonical_json_hash({"b": 2, "a": [1, 3]}) == canonical_json_hash(
        {"a": [1, 3], "b": 2}
    )
    with pytest.raises(ValueError, match="^value is not canonical JSON$"):
        canonical_json_hash({"unsafe": float("nan")})


def test_ordered_reconciliation_hash_is_order_sensitive_and_domain_separated() -> None:
    from services.sydney_context_service import ordered_reconciliation_hash

    first = ordered_reconciliation_hash(
        [(uuid4(), "user", "a" * 64), (uuid4(), "assistant", "b" * 64)]
    )
    same = ordered_reconciliation_hash(first.source_rows)
    reversed_result = ordered_reconciliation_hash(tuple(reversed(first.source_rows)))

    assert first.digest == same.digest
    assert first.count == 2
    assert first.digest != reversed_result.digest
    assert len(first.digest) == 64


@pytest.mark.asyncio
async def test_ingest_uses_the_configured_event_batch_limit() -> None:
    from schemas.sydney_context import ContextEventBatchRequest
    from services.sydney_context_service import ingest_event_batch

    request = ContextEventBatchRequest(
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
        hermes_session_id="session-1",
        logical_conversation_id=uuid4(),
        events=[
            {
                "source_event_key": f"message-{index}",
                "event_type": "user",
                "role": "user",
                "occurred_at": datetime(2026, 8, 25, 17, index, tzinfo=UTC),
                "content": f"message {index}",
            }
            for index in (1, 2)
        ],
    )

    with pytest.raises(ValueError, match="context_event_batch_too_large"):
        await ingest_event_batch(object(), request, batch_limit=1)  # type: ignore[arg-type]
