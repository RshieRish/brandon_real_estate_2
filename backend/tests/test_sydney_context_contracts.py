from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError


def _event_payload(index: int = 1) -> dict[str, object]:
    return {
        "source_event_key": f"session-1:message-{index}",
        "event_type": "user",
        "role": "user",
        "occurred_at": datetime(2026, 8, 25, 16, 0, tzinfo=UTC)
        + timedelta(minutes=index),
        "content": f"message {index}",
        "metadata": {"telegram_message_id": str(index)},
    }


def test_durable_context_flags_default_off_and_limits_are_bounded() -> None:
    from config import Settings

    config = Settings(JWT_SECRET="test-secret")

    assert config.SYDNEY_DURABLE_CONTEXT_ENABLED is False
    assert config.SYDNEY_DURABLE_CONTEXT_RETRIEVAL_ENABLED is False
    assert config.SYDNEY_DURABLE_CONTEXT_PROJECTION_ENABLED is False
    assert config.SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED is False
    assert config.SYDNEY_CONTEXT_RECALL_TOKEN_BUDGET == 16_000
    assert config.SYDNEY_CONTEXT_PROMPT_COMPRESS_TOKENS == 96_000
    assert config.SYDNEY_CONTEXT_INTERACTIVE_TPM_BUDGET == 500_000
    assert config.SYDNEY_CONTEXT_MAX_TURNS == 16
    assert config.SYDNEY_CONTEXT_EVENT_BATCH_LIMIT == 100
    assert config.SYDNEY_CONTEXT_SEGMENT_CHARS == 16_000
    assert config.SYDNEY_CONTEXT_RUN_LEASE_SECONDS == 120


def test_event_batch_contract_is_strict_and_bounded() -> None:
    from schemas.sydney_context import ContextEventBatchRequest

    request = ContextEventBatchRequest(
        platform="telegram",
        external_user_id="brandon-user",
        external_chat_id="brandon-chat",
        display_label="Brandon",
        hermes_session_id="session-1",
        logical_conversation_id=uuid4(),
        model="gemini-3.5-flash",
        source_version="hermes-0.15.2",
        events=[_event_payload()],
    )
    assert request.events[0].event_type == "user"

    with pytest.raises(ValidationError):
        ContextEventBatchRequest.model_validate(
            {
                **request.model_dump(),
                "events": [_event_payload(index) for index in range(1, 102)],
            }
        )
    with pytest.raises(ValidationError):
        ContextEventBatchRequest.model_validate(
            {**request.model_dump(), "unexpected": "not accepted"}
        )
    with pytest.raises(ValidationError):
        ContextEventBatchRequest.model_validate(
            {
                **request.model_dump(),
                "events": [{**_event_payload(), "event_type": "reasoning"}],
            }
        )


def test_retrieval_and_history_contracts_clamp_at_the_boundary() -> None:
    from schemas.sydney_context import (
        ContextHistorySearchRequest,
        ContextRetrieveRequest,
    )

    identity_id = uuid4()
    logical_id = uuid4()
    request = ContextRetrieveRequest(
        identity_id=identity_id,
        logical_conversation_id=logical_id,
        hermes_session_id="session-1",
        current_user_text="What did we decide about the audience?",
        token_budget=16_000,
    )
    assert request.token_budget == 16_000

    with pytest.raises(ValidationError):
        ContextRetrieveRequest.model_validate(
            {**request.model_dump(), "token_budget": 16_001}
        )

    history = ContextHistorySearchRequest(
        identity_id=identity_id,
        query="audience decision",
        event_types=["user", "assistant", "tool_result"],
        limit=25,
    )
    assert history.limit == 25
    with pytest.raises(ValidationError):
        ContextHistorySearchRequest.model_validate(
            {**history.model_dump(), "limit": 26}
        )
