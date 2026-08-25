from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


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
