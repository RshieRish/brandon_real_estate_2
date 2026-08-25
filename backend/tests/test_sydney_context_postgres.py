from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from schemas.sydney_context import ContextEventBatchRequest
from tests.gmail_task_postgres import async_test_url, migrated_test_database

REVISION = "85e8b7c9d4f1"


def _request(*, content: str = "Remember the gold folder") -> ContextEventBatchRequest:
    return ContextEventBatchRequest(
        platform="telegram",
        external_user_id="brandon-user",
        external_chat_id="brandon-chat",
        display_label="Brandon",
        hermes_session_id="session-1",
        logical_conversation_id=uuid4(),
        model="gemini-3.5-flash",
        source_version="hermes-0.15.2",
        events=[
            {
                "source_event_key": "session-1:message-1",
                "event_type": "user",
                "role": "user",
                "occurred_at": datetime(2026, 8, 25, 17, 0, tzinfo=UTC),
                "content": content,
                "metadata": {"telegram_message_id": "11"},
            }
        ],
    )


@pytest.fixture(scope="module")
def context_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def context_sessions(context_database):
    url, sync_engine = context_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE agent_tool_invocations, agent_run_jobs, "
                "agent_memory_facts, agent_context_checkpoints, "
                "agent_conversation_event_segments, agent_conversation_events, "
                "agent_conversation_sessions, agent_conversation_identities CASCADE"
            )
        )
    engine = create_async_engine(async_test_url(url), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_is_exactly_idempotent_and_redacts_before_commit(
    context_sessions,
) -> None:
    from services.sydney_context_service import ingest_event_batch

    _engine, factory = context_sessions
    request = _request(content="password=hunter42; remember the gold folder")
    async with factory() as session:
        first = await ingest_event_batch(session, request, segment_chars=12)
        await session.commit()
    async with factory() as session:
        replay = await ingest_event_batch(session, request, segment_chars=12)
        await session.commit()

    assert first.event_ids == replay.event_ids
    assert first.inserted_count == 1
    assert first.replayed_count == 0
    assert replay.inserted_count == 0
    assert replay.replayed_count == 1

    async with factory() as session:
        rows = (
            await session.execute(
                sa.text(
                    "SELECT e.search_text, s.ordinal, s.content "
                    "FROM agent_conversation_events e "
                    "JOIN agent_conversation_event_segments s ON s.event_id = e.id "
                    "ORDER BY s.ordinal"
                )
            )
        ).all()
    assert "hunter42" not in rows[0].search_text
    assert "".join(row.content for row in rows) == rows[0].search_text


@pytest.mark.asyncio
async def test_conflicting_source_key_replay_is_rejected(context_sessions) -> None:
    from services.sydney_context_service import ContextEventConflict, ingest_event_batch

    _engine, factory = context_sessions
    original = _request()
    async with factory() as session:
        await ingest_event_batch(session, original)
        await session.commit()
    conflicting = original.model_copy(
        update={
            "events": [
                original.events[0].model_copy(update={"content": "Different content"})
            ]
        }
    )
    with pytest.raises(ContextEventConflict, match="^context_event_replay_conflict$"):
        async with factory() as session:
            await ingest_event_batch(session, conflicting)


@pytest.mark.asyncio
async def test_two_connections_racing_same_event_create_one_row(
    context_sessions,
) -> None:
    from services.sydney_context_service import ingest_event_batch

    _engine, factory = context_sessions
    request = _request()

    async def ingest_once():
        async with factory() as session:
            result = await ingest_event_batch(session, request)
            await session.commit()
            return result

    results = await asyncio.gather(ingest_once(), ingest_once())

    assert sum(result.inserted_count for result in results) == 1
    assert sum(result.replayed_count for result in results) == 1
    assert results[0].event_ids == results[1].event_ids


@pytest.mark.asyncio
async def test_retrieval_and_history_search_return_bounded_source_linked_events(
    context_sessions,
) -> None:
    from schemas.sydney_context import (
        ContextHistorySearchRequest,
        ContextRetrieveRequest,
    )
    from services.sydney_context_service import (
        ingest_event_batch,
        retrieve_context,
        search_history,
    )

    _engine, factory = context_sessions
    base = _request()
    events = []
    for index in range(30):
        events.append(
            {
                "source_event_key": f"session-1:message-{index + 1}",
                "event_type": "user" if index % 2 == 0 else "assistant",
                "role": "user" if index % 2 == 0 else "assistant",
                "occurred_at": datetime(2026, 8, 25, 17, 0, tzinfo=UTC)
                + timedelta(minutes=index),
                "content": (
                    "The archival keyword is aurum-folder"
                    if index == 0
                    else f"Routine conversation event {index}"
                ),
                "metadata": {},
            }
        )
    request = base.model_copy(update={"events": events})
    async with factory() as session:
        ingested = await ingest_event_batch(session, request)
        await session.commit()

    async with factory() as session:
        packet = await retrieve_context(
            session,
            ContextRetrieveRequest(
                identity_id=ingested.identity_id,
                logical_conversation_id=request.logical_conversation_id,
                hermes_session_id=request.hermes_session_id,
                current_user_text="What was the archival aurum folder keyword?",
                token_budget=2_000,
            ),
        )
        search = await search_history(
            session,
            ContextHistorySearchRequest(
                identity_id=ingested.identity_id,
                query="aurum folder",
                limit=5,
            ),
        )
        window = await search_history(
            session,
            ContextHistorySearchRequest(
                identity_id=ingested.identity_id,
                around_event_id=ingested.event_ids[15],
                window_size=2,
                limit=5,
            ),
        )

    assert packet.estimated_tokens <= 2_000
    assert [section.kind for section in packet.sections] == [
        "recent_events",
        "relevant_events",
    ]
    assert "aurum-folder" in packet.sections[-1].text
    assert packet.sections[-1].source_event_ids == [ingested.event_ids[0]]
    assert [event.event_id for event in search.events] == [ingested.event_ids[0]]
    assert [event.event_id for event in window.events] == ingested.event_ids[13:18]
