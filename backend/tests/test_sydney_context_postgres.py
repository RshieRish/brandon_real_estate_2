from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from schemas.sydney_context import ContextEventBatchRequest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.gmail_task_postgres import async_test_url, migrated_test_database

REVISION = "86f9c8a0d2e1"


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
                "TRUNCATE agent_tool_invocations, agent_run_request_receipts, "
                "agent_run_jobs, "
                "agent_context_projection_claims, "
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
async def test_event_orm_insert_omits_generated_search_vector(context_sessions) -> None:
    from models.sydney_context import AgentConversationEvent
    from services.sydney_context_service import ingest_event_batch

    _engine, factory = context_sessions
    request = _request()
    event_id = uuid4()
    content = "Inserted through the ORM"
    async with factory() as session:
        ingested = await ingest_event_batch(session, request)
        session.add(
            AgentConversationEvent(
                id=event_id,
                identity_id=ingested.identity_id,
                session_id=ingested.session_id,
                source_event_key="session-1:orm-message",
                event_type="assistant",
                role="assistant",
                occurred_at=datetime(2026, 8, 25, 17, 1, tzinfo=UTC),
                content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                redaction_status="unchanged",
                search_text=content,
            )
        )
        await session.commit()

    async with factory() as session:
        indexed = await session.scalar(
            sa.text(
                "SELECT search_vector IS NOT NULL "
                "FROM agent_conversation_events WHERE id = :event_id"
            ),
            {"event_id": event_id},
        )
    assert indexed is True


@pytest.mark.asyncio
async def test_accepted_large_event_cannot_overflow_full_text_index(
    context_sessions,
) -> None:
    from services.sydney_context_service import ingest_event_batch

    _engine, factory = context_sessions
    content = " ".join(
        hashlib.md5(str(index).encode(), usedforsecurity=False).hexdigest()
        for index in range(30_000)
    )
    assert len(content) < 1_000_000
    async with factory() as session:
        ingested = await ingest_event_batch(
            session,
            _request(content=content),
            segment_chars=16_000,
        )
        await session.commit()

    async with factory() as session:
        indexed = await session.scalar(
            sa.text(
                "SELECT search_vector IS NOT NULL "
                "FROM agent_conversation_events WHERE id = :event_id"
            ),
            {"event_id": ingested.event_ids[0]},
        )
    assert indexed is True


@pytest.mark.asyncio
async def test_reconciliation_requires_exact_receipts_and_new_events_invalidate_it(
    context_sessions,
) -> None:
    from models.sydney_context import AgentConversationSession
    from services.sydney_context_service import (
        ingest_event_batch,
        ordered_reconciliation_hash,
        reconcile_session,
    )

    _engine, factory = context_sessions
    request = _request()
    async with factory() as session:
        ingested = await ingest_event_batch(session, request)
        receipt = ingested.event_receipts[0]
        expected = ordered_reconciliation_hash(
            [(receipt.event_id, receipt.event_type, receipt.content_sha256)]
        )
        matched = await reconcile_session(
            session,
            identity_id=ingested.identity_id,
            hermes_session_id=request.hermes_session_id,
            expected_event_count=expected.count,
            expected_ordered_hash=expected.digest,
        )
        await session.commit()

    assert matched.matched is True
    assert matched.ordered_hash == expected.digest

    async with factory() as session:
        stored = await session.get(AgentConversationSession, ingested.session_id)
        assert stored.reconciliation_hash == expected.digest

        second_request = request.model_copy(
            update={
                "events": [
                    request.events[0].model_copy(
                        update={
                            "source_event_key": "session-1:message-2",
                            "occurred_at": request.events[0].occurred_at
                            + timedelta(seconds=1),
                            "content": "A later visible event",
                        }
                    )
                ]
            }
        )
        await ingest_event_batch(session, second_request)
        await session.commit()

    async with factory() as session:
        stored = await session.get(AgentConversationSession, ingested.session_id)
        assert stored.reconciliation_hash is None
        mismatch = await reconcile_session(
            session,
            identity_id=ingested.identity_id,
            hermes_session_id=request.hermes_session_id,
            expected_event_count=1,
            expected_ordered_hash=expected.digest,
        )
        await session.commit()

    assert mismatch.matched is False
    assert mismatch.event_count == 2
    async with factory() as session:
        stored = await session.get(AgentConversationSession, ingested.session_id)
        assert stored.reconciliation_hash is None


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
async def test_parent_session_must_belong_to_the_requested_lineage(
    context_sessions,
) -> None:
    from services.sydney_context_service import (
        ContextSessionConflict,
        ingest_event_batch,
    )

    _engine, factory = context_sessions
    root = _request()
    async with factory() as session:
        await ingest_event_batch(session, root)
        await session.commit()

    foreign_child = _request(content="Do not cross-link this conversation.").model_copy(
        update={
            "external_user_id": "another-user",
            "external_chat_id": "another-chat",
            "hermes_session_id": "foreign-child-session",
            "logical_conversation_id": uuid4(),
            "parent_hermes_session_id": root.hermes_session_id,
            "continuation_reason": "continuation",
            "events": [
                root.events[0].model_copy(
                    update={
                        "source_event_key": "foreign-child-session:message-1",
                        "content": "Do not cross-link this conversation.",
                    }
                )
            ],
        }
    )
    async with factory() as session:
        with pytest.raises(
            ContextSessionConflict,
            match="^context_parent_session_missing$",
        ):
            await ingest_event_batch(session, foreign_child)


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
            base.events[0].model_copy(
                update={
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


@pytest.mark.asyncio
async def test_history_search_finds_middle_segments_and_returns_bounded_excerpt(
    context_sessions,
) -> None:
    from schemas.sydney_context import ContextHistorySearchRequest
    from services.sydney_context_service import ingest_event_batch, search_history

    _engine, factory = context_sessions
    middle_keyword = "midsegmentaurum"
    oversized = ("alpha " * 9_000) + middle_keyword + (" omega" * 9_000)
    request = _request(content=oversized)
    async with factory() as session:
        ingested = await ingest_event_batch(session, request)
        await session.commit()

    async with factory() as session:
        search = await search_history(
            session,
            ContextHistorySearchRequest(
                identity_id=ingested.identity_id,
                query=middle_keyword,
                limit=5,
            ),
        )

    assert [event.event_id for event in search.events] == [ingested.event_ids[0]]
    assert middle_keyword in search.events[0].content
    assert len(search.events[0].content) <= 2_000
    assert search.events[0].content_truncated is True


@pytest.mark.asyncio
async def test_recent_conversations_returns_one_latest_event_per_logical_conversation(
    context_sessions,
) -> None:
    from schemas.sydney_context import ContextHistorySearchRequest
    from services.sydney_context_service import ingest_event_batch, search_history

    _engine, factory = context_sessions
    first = _request()
    second_logical_id = uuid4()
    second = first.model_copy(
        update={
            "hermes_session_id": "session-recent-2",
            "logical_conversation_id": second_logical_id,
            "events": [
                first.events[0].model_copy(
                    update={
                        "source_event_key": "session-recent-2:message-1",
                        "occurred_at": first.events[0].occurred_at
                        + timedelta(minutes=10),
                        "content": "Second conversation latest event",
                    }
                )
            ],
        }
    )
    async with factory() as session:
        first_result = await ingest_event_batch(session, first)
        second_result = await ingest_event_batch(session, second)
        await session.commit()

    async with factory() as session:
        result = await search_history(
            session,
            ContextHistorySearchRequest(
                identity_id=first_result.identity_id,
                recent_conversations=True,
                limit=10,
            ),
        )

    assert [event.event_id for event in result.events] == [
        second_result.event_ids[-1],
        first_result.event_ids[-1],
    ]
    assert [event.logical_conversation_id for event in result.events] == [
        second_logical_id,
        first.logical_conversation_id,
    ]
    assert result.total == 2
    assert result.truncated is False


@pytest.mark.asyncio
async def test_around_event_window_reports_matching_rows_outside_the_window(
    context_sessions,
) -> None:
    from schemas.sydney_context import ContextHistorySearchRequest
    from services.sydney_context_service import ingest_event_batch, search_history

    _engine, factory = context_sessions
    base = _request()
    events = [
        base.events[0].model_copy(
            update={
                "source_event_key": f"session-window:message-{index}",
                "occurred_at": base.events[0].occurred_at + timedelta(minutes=index),
                "content": f"Window event {index}",
            }
        )
        for index in range(9)
    ]
    request = base.model_copy(
        update={"hermes_session_id": "session-window", "events": events}
    )
    async with factory() as session:
        ingested = await ingest_event_batch(session, request)
        await session.commit()

    async with factory() as session:
        result = await search_history(
            session,
            ContextHistorySearchRequest(
                identity_id=ingested.identity_id,
                around_event_id=ingested.event_ids[4],
                window_size=2,
                limit=10,
            ),
        )

    assert [event.event_id for event in result.events] == ingested.event_ids[2:7]
    assert result.total > len(result.events)
    assert result.truncated is True


@pytest.mark.asyncio
async def test_around_event_window_stays_in_the_target_logical_conversation(
    context_sessions,
) -> None:
    from schemas.sydney_context import ContextHistorySearchRequest
    from services.sydney_context_service import ingest_event_batch, search_history

    _engine, factory = context_sessions
    base = _request()
    first_logical_id = base.logical_conversation_id
    first_batch = base.model_copy(
        update={
            "hermes_session_id": "logical-window-first",
            "events": [
                base.events[0].model_copy(
                    update={
                        "source_event_key": f"logical-window-first:{index}",
                        "occurred_at": base.events[0].occurred_at
                        + timedelta(minutes=index * 2),
                        "content": f"First conversation {index}",
                    }
                )
                for index in range(3)
            ],
        }
    )
    second_batch = base.model_copy(
        update={
            "hermes_session_id": "logical-window-second",
            "logical_conversation_id": uuid4(),
            "events": [
                base.events[0].model_copy(
                    update={
                        "source_event_key": f"logical-window-second:{index}",
                        "occurred_at": base.events[0].occurred_at
                        + timedelta(minutes=(index * 2) + 1),
                        "content": f"Second conversation {index}",
                    }
                )
                for index in range(2)
            ],
        }
    )
    async with factory() as session:
        first = await ingest_event_batch(session, first_batch)
        await ingest_event_batch(session, second_batch)
        await session.commit()

    async with factory() as session:
        result = await search_history(
            session,
            ContextHistorySearchRequest(
                identity_id=first.identity_id,
                around_event_id=first.event_ids[1],
                window_size=1,
            ),
        )

    assert [event.event_id for event in result.events] == first.event_ids
    assert {event.logical_conversation_id for event in result.events} == {
        first_logical_id
    }


@pytest.mark.asyncio
async def test_distinct_caller_keys_do_not_collapse_on_a_redacted_argument_hash(
    context_sessions,
) -> None:
    from schemas.sydney_context import (
        ContextRunClaimRequest,
        ContextRunStartRequest,
        ContextToolInvocationRequest,
    )
    from services.sydney_context_service import (
        claim_runs,
        ingest_event_batch,
        start_run,
        start_tool_invocation,
    )

    _engine, factory = context_sessions
    now = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)
    batch = _request()
    async with factory() as session:
        ingested = await ingest_event_batch(session, batch)
        started = await start_run(
            session,
            ContextRunStartRequest(
                identity_id=ingested.identity_id,
                platform_message_id="distinct-caller-keys",
                inbound_event_id=ingested.event_ids[0],
                session_id=ingested.session_id,
                logical_conversation_id=batch.logical_conversation_id,
                terminal_deadline_at=now + timedelta(hours=24),
            ),
        )
        await session.commit()

    async with factory() as session:
        claimed = await claim_runs(
            session,
            ContextRunClaimRequest(
                lease_owner="atlas-distinct-keys",
                run_id=started.run.id,
            ),
            now=now,
        )
        assert [run.id for run in claimed.runs] == [started.run.id]
        common_arguments = {"description": "[REDACTED_SIGNED_FRAGMENT]"}
        first = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=started.run.id,
                lease_owner="atlas-distinct-keys",
                tool_call_id="caller-key-a",
                tool_name="calendar_event_create",
                arguments=common_arguments,
                side_effect_class="idempotent_write",
                caller_idempotency_key="caller-key-sha256:a",
            ),
            now=now + timedelta(seconds=1),
        )
        second = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=started.run.id,
                lease_owner="atlas-distinct-keys",
                tool_call_id="caller-key-b",
                tool_name="calendar_event_create",
                arguments=common_arguments,
                side_effect_class="idempotent_write",
                caller_idempotency_key="caller-key-sha256:b",
            ),
            now=now + timedelta(seconds=1),
        )
        await session.commit()

    assert first.replay_decision == "execute"
    assert second.replay_decision == "execute"
    assert second.invocation_id != first.invocation_id
    assert second.canonical_tool_call_id == "caller-key-b"


@pytest.mark.asyncio
async def test_tool_invocation_limit_survives_new_sessions_and_preserves_replays(
    context_sessions,
) -> None:
    from schemas.sydney_context import (
        ContextRunClaimRequest,
        ContextRunStartRequest,
        ContextToolInvocationRequest,
    )
    from services.sydney_context_service import (
        claim_runs,
        ingest_event_batch,
        start_run,
        start_tool_invocation,
    )

    _engine, factory = context_sessions
    now = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)
    batch = _request()
    async with factory() as session:
        ingested = await ingest_event_batch(session, batch)
        started = await start_run(
            session,
            ContextRunStartRequest(
                identity_id=ingested.identity_id,
                platform_message_id="aggregate-tool-limit",
                inbound_event_id=ingested.event_ids[0],
                session_id=ingested.session_id,
                logical_conversation_id=batch.logical_conversation_id,
                terminal_deadline_at=now + timedelta(hours=24),
            ),
        )
        await session.commit()

    async with factory() as session:
        await claim_runs(
            session,
            ContextRunClaimRequest(
                lease_owner="atlas-tool-limit",
                run_id=started.run.id,
            ),
            now=now,
        )
        first = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=started.run.id,
                lease_owner="atlas-tool-limit",
                tool_call_id="within-limit",
                tool_name="command_contacts_search",
                arguments={"query": "September"},
                side_effect_class="read_only",
            ),
            now=now + timedelta(seconds=1),
            invocation_limit=1,
        )
        await session.commit()

    async with factory() as continuation_session:
        blocked = await start_tool_invocation(
            continuation_session,
            ContextToolInvocationRequest(
                run_id=started.run.id,
                lease_owner="atlas-tool-limit",
                tool_call_id="continued-over-limit",
                tool_name="command_contacts_search",
                arguments={"query": "October"},
                side_effect_class="read_only",
            ),
            now=now + timedelta(seconds=2),
            invocation_limit=1,
        )
        await continuation_session.commit()

    async with factory() as later_continuation:
        still_blocked = await start_tool_invocation(
            later_continuation,
            ContextToolInvocationRequest(
                run_id=started.run.id,
                lease_owner="atlas-tool-limit",
                tool_call_id="another-continuation-over-limit",
                tool_name="status_read",
                arguments={},
                side_effect_class="read_only",
            ),
            now=now + timedelta(seconds=3),
            invocation_limit=1,
        )
        replay = await start_tool_invocation(
            later_continuation,
            ContextToolInvocationRequest(
                run_id=started.run.id,
                lease_owner="atlas-tool-limit",
                tool_call_id="within-limit",
                tool_name="command_contacts_search",
                arguments={"query": "September"},
                side_effect_class="read_only",
            ),
            now=now + timedelta(seconds=3),
            invocation_limit=1,
        )
        stored_count = await later_continuation.scalar(
            sa.text(
                "SELECT count(*) FROM agent_tool_invocations WHERE run_id = :run_id"
            ),
            {"run_id": started.run.id},
        )

    assert first.replay_decision == "execute"
    assert first.invocation_count == first.invocation_limit == 1
    assert first.limit_reached is True
    for receipt in (blocked, still_blocked):
        assert receipt.invocation_id is None
        assert receipt.replay_decision == "block_limit"
        assert receipt.invocation_count == receipt.invocation_limit == 1
        assert receipt.limit_reached is True
    assert replay.invocation_id == first.invocation_id
    assert replay.replay_decision == "repeat_read"
    assert replay.invocation_count == replay.invocation_limit == 1
    assert stored_count == 1


@pytest.mark.asyncio
async def test_equivalent_active_requests_coalesce_across_manual_session_reset(
    context_sessions,
) -> None:
    from schemas.sydney_context import ContextRunStartRequest
    from services.sydney_context_service import ingest_event_batch, start_run

    _engine, factory = context_sessions
    base = _request(
        content="  Source ALL September birthdays\n and home anniversaries  "
    )
    reset_batch = base.model_copy(
        update={
            "hermes_session_id": "session-after-manual-reset",
            "parent_hermes_session_id": base.hermes_session_id,
            "continuation_reason": "manual_reset",
            "events": [
                base.events[0].model_copy(
                    update={
                        "source_event_key": "session-after-manual-reset:message-1",
                        "content": (
                            "source all september birthdays and home anniversaries"
                        ),
                        "metadata": {"telegram_message_id": "12"},
                    }
                )
            ],
        }
    )
    async with factory() as session:
        first_ingest = await ingest_event_batch(session, base)
        reset_ingest = await ingest_event_batch(session, reset_batch)
        await session.commit()

    now = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

    async def start(
        *, platform_message_id: str, inbound_event_id: UUID, session_id: UUID
    ):
        async with factory() as session:
            result = await start_run(
                session,
                ContextRunStartRequest(
                    identity_id=first_ingest.identity_id,
                    platform_message_id=platform_message_id,
                    inbound_event_id=inbound_event_id,
                    session_id=session_id,
                    logical_conversation_id=base.logical_conversation_id,
                    terminal_deadline_at=now + timedelta(hours=24),
                ),
            )
            await session.commit()
            return result

    first, reset = await asyncio.gather(
        start(
            platform_message_id="telegram-11",
            inbound_event_id=first_ingest.event_ids[0],
            session_id=first_ingest.session_id,
        ),
        start(
            platform_message_id="telegram-12",
            inbound_event_id=reset_ingest.event_ids[0],
            session_id=reset_ingest.session_id,
        ),
    )

    assert first.run.id == reset.run.id
    assert {first.coalesced, reset.coalesced} == {False, True}
    assert first.replayed is False
    assert reset.replayed is False

    async with factory() as session:
        run_count = await session.scalar(sa.text("SELECT count(*) FROM agent_run_jobs"))
        receipts = (
            await session.execute(
                sa.text(
                    "SELECT platform_message_id, disposition, run_id "
                    "FROM agent_run_request_receipts ORDER BY platform_message_id"
                )
            )
        ).all()
    assert run_count == 1
    assert [(row.platform_message_id, row.disposition) for row in receipts] == [
        ("telegram-11", "primary"),
        ("telegram-12", "coalesced"),
    ]
    assert {row.run_id for row in receipts} == {first.run.id}

    replay = await start(
        platform_message_id="telegram-12",
        inbound_event_id=reset_ingest.event_ids[0],
        session_id=reset_ingest.session_id,
    )
    assert replay.replayed is True
    assert replay.coalesced is True
    assert replay.run.id == first.run.id


@pytest.mark.asyncio
async def test_terminal_request_fingerprint_can_start_fresh_work(
    context_sessions,
) -> None:
    from schemas.sydney_context import ContextRunStartRequest
    from services.sydney_context_service import ingest_event_batch, start_run

    _engine, factory = context_sessions
    base = _request(content="September birthdays")
    later = base.model_copy(
        update={
            "hermes_session_id": "terminal-repeat-session",
            "events": [
                base.events[0].model_copy(
                    update={
                        "source_event_key": "terminal-repeat-session:message-2",
                        "metadata": {"telegram_message_id": "22"},
                    }
                )
            ],
        }
    )
    now = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    async with factory() as session:
        first_ingest = await ingest_event_batch(session, base)
        first = await start_run(
            session,
            ContextRunStartRequest(
                identity_id=first_ingest.identity_id,
                platform_message_id="telegram-21",
                inbound_event_id=first_ingest.event_ids[0],
                session_id=first_ingest.session_id,
                logical_conversation_id=base.logical_conversation_id,
                terminal_deadline_at=now + timedelta(hours=24),
            ),
        )
        await session.execute(
            sa.text(
                "UPDATE agent_run_jobs SET state = 'terminal_failure' WHERE id = :id"
            ),
            {"id": first.run.id},
        )
        second_ingest = await ingest_event_batch(session, later)
        second = await start_run(
            session,
            ContextRunStartRequest(
                identity_id=first_ingest.identity_id,
                platform_message_id="telegram-22",
                inbound_event_id=second_ingest.event_ids[0],
                session_id=second_ingest.session_id,
                logical_conversation_id=base.logical_conversation_id,
                terminal_deadline_at=now + timedelta(hours=24),
            ),
        )
        await session.commit()

    assert second.coalesced is False
    assert second.run.id != first.run.id


@pytest.mark.asyncio
async def test_run_fifo_claim_and_tool_ledger_prevent_duplicate_side_effects(
    context_sessions,
) -> None:
    from schemas.sydney_context import (
        ContextRunClaimRequest,
        ContextRunStartRequest,
        ContextRunUpdateRequest,
        ContextToolInvocationRequest,
        ContextToolInvocationUpdateRequest,
    )
    from services.sydney_context_service import (
        ContextToolConflict,
        claim_runs,
        ingest_event_batch,
        start_run,
        start_tool_invocation,
        update_run_state,
        update_tool_invocation,
    )

    _engine, factory = context_sessions
    base = _request()
    batch = base.model_copy(
        update={
            "events": [
                base.events[0],
                base.events[0].model_copy(
                    update={
                        "source_event_key": "session-1:message-2",
                        "event_type": "tool_result",
                        "role": "tool",
                        "tool_name": "gmail_send",
                        "tool_call_id": "call-1",
                        "occurred_at": base.events[0].occurred_at
                        + timedelta(seconds=1),
                        "content": "Saved response",
                    }
                ),
                base.events[0].model_copy(
                    update={
                        "source_event_key": "session-1:message-3",
                        "event_type": "tool_result",
                        "role": "tool",
                        "tool_name": "gmail_send",
                        "tool_call_id": "call-1",
                        "occurred_at": base.events[0].occurred_at
                        + timedelta(seconds=2),
                        "content": "Conflicting response",
                    }
                ),
                base.events[0].model_copy(
                    update={
                        "source_event_key": "session-1:message-4",
                        "event_type": "tool_result",
                        "role": "tool",
                        "tool_name": "command_contacts_search",
                        "tool_call_id": "read-call-1",
                        "occurred_at": base.events[0].occurred_at
                        + timedelta(seconds=3),
                        "content": "Read response",
                    }
                ),
                base.events[0].model_copy(
                    update={
                        "source_event_key": "session-1:message-5",
                        "event_type": "tool_result",
                        "role": "tool",
                        "tool_name": "gmail_send",
                        "tool_call_id": "retry-call-1",
                        "occurred_at": base.events[0].occurred_at
                        + timedelta(seconds=4),
                        "content": "Retry response",
                    }
                ),
                base.events[0].model_copy(
                    update={
                        "source_event_key": "session-1:message-6",
                        "event_type": "assistant",
                        "role": "assistant",
                        "occurred_at": base.events[0].occurred_at
                        + timedelta(seconds=5),
                        "content": "Completed response",
                    }
                ),
            ]
        }
    )
    now = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)
    async with factory() as session:
        ingested = await ingest_event_batch(session, batch)
        first = await start_run(
            session,
            ContextRunStartRequest(
                identity_id=ingested.identity_id,
                platform_message_id="telegram-11",
                inbound_event_id=ingested.event_ids[0],
                session_id=ingested.session_id,
                logical_conversation_id=batch.logical_conversation_id,
                terminal_deadline_at=now + timedelta(hours=24),
            ),
        )
        replay = await start_run(
            session,
            ContextRunStartRequest(
                identity_id=ingested.identity_id,
                platform_message_id="telegram-11",
                inbound_event_id=ingested.event_ids[0],
                session_id=ingested.session_id,
                logical_conversation_id=batch.logical_conversation_id,
                terminal_deadline_at=now + timedelta(hours=24),
            ),
        )
        await session.commit()
    assert replay.replayed is True
    assert replay.coalesced is False
    assert replay.run.id == first.run.id

    async with factory() as session:
        claimed = await claim_runs(
            session,
            ContextRunClaimRequest(lease_owner="atlas-one"),
            now=now,
            lease_seconds=120,
        )
        await session.commit()
    assert [run.id for run in claimed.runs] == [first.run.id]
    assert claimed.runs[0].attempt_count == 1

    async with factory() as session:
        with pytest.raises(
            ContextToolConflict,
            match="^context_run_lease_expired$",
        ):
            await start_tool_invocation(
                session,
                ContextToolInvocationRequest(
                    run_id=first.run.id,
                    lease_owner="atlas-one",
                    tool_call_id="call-expired",
                    tool_name="gmail_send",
                    arguments={"request_id": "expired", "subject": "Hello"},
                    side_effect_class="idempotent_write",
                    caller_idempotency_key="expired",
                ),
                now=now + timedelta(seconds=121),
            )
        with pytest.raises(
            ContextToolConflict,
            match="^context_run_lease_owner_invalid$",
        ):
            await start_tool_invocation(
                session,
                ContextToolInvocationRequest(
                    run_id=first.run.id,
                    lease_owner="atlas-stale",
                    tool_call_id="call-stale",
                    tool_name="gmail_send",
                    arguments={"request_id": "stale", "subject": "Hello"},
                    side_effect_class="idempotent_write",
                    caller_idempotency_key="stale",
                ),
                now=now + timedelta(seconds=1),
            )
        tool = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="call-1",
                tool_name="gmail_send",
                arguments={"request_id": "stable-id", "subject": "Hello"},
                side_effect_class="idempotent_write",
                caller_idempotency_key="stable-id",
            ),
            now=now + timedelta(seconds=1),
        )
        with pytest.raises(
            ContextToolConflict,
            match="^context_run_lease_owner_invalid$",
        ):
            await update_tool_invocation(
                session,
                ContextToolInvocationUpdateRequest(
                    run_id=first.run.id,
                    lease_owner="atlas-stale",
                    tool_call_id="call-1",
                    state="succeeded",
                    result_event_id=ingested.event_ids[1],
                ),
                now=now + timedelta(seconds=1),
            )
        finished = await update_tool_invocation(
            session,
            ContextToolInvocationUpdateRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="call-1",
                state="succeeded",
                result_event_id=ingested.event_ids[1],
            ),
            now=now + timedelta(seconds=1),
        )
        with pytest.raises(
            ContextToolConflict,
            match="^context_tool_update_replay_conflict$",
        ):
            await update_tool_invocation(
                session,
                ContextToolInvocationUpdateRequest(
                    run_id=first.run.id,
                    lease_owner="atlas-one",
                    tool_call_id="call-1",
                    state="succeeded",
                    result_event_id=ingested.event_ids[2],
                ),
                now=now + timedelta(seconds=2),
            )
        replayed_tool = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="call-1",
                tool_name="gmail_send",
                arguments={"subject": "Hello", "request_id": "stable-id"},
                side_effect_class="idempotent_write",
                caller_idempotency_key="stable-id",
            ),
            now=now + timedelta(seconds=1),
        )
        regenerated_tool = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="regenerated-call-id",
                tool_name="gmail_send",
                arguments={"subject": "Hello", "request_id": "stable-id"},
                side_effect_class="idempotent_write",
                caller_idempotency_key="stable-id",
            ),
            now=now + timedelta(seconds=1),
        )
        arguments_only_replay = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="arguments-only-call-id",
                tool_name="gmail_send",
                arguments={"subject": "Hello", "request_id": "stable-id"},
                side_effect_class="idempotent_write",
            ),
            now=now + timedelta(seconds=1),
        )
        with pytest.raises(
            ContextToolConflict,
            match="^context_tool_replay_conflict$",
        ):
            await start_tool_invocation(
                session,
                ContextToolInvocationRequest(
                    run_id=first.run.id,
                    lease_owner="atlas-one",
                    tool_call_id="conflicting-intent-call-id",
                    tool_name="gmail_send",
                    arguments={"subject": "Different", "request_id": "stable-id"},
                    side_effect_class="idempotent_write",
                    caller_idempotency_key="stable-id",
                ),
                now=now + timedelta(seconds=1),
            )
        read_tool = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="read-call-1",
                tool_name="command_contacts_search",
                arguments={"query": "Brandon"},
                side_effect_class="read_only",
            ),
            now=now + timedelta(seconds=1),
        )
        await update_tool_invocation(
            session,
            ContextToolInvocationUpdateRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="read-call-1",
                state="failed",
                result_event_id=ingested.event_ids[3],
            ),
            now=now + timedelta(seconds=1),
        )
        read_replay = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="read-call-1",
                tool_name="command_contacts_search",
                arguments={"query": "Brandon"},
                side_effect_class="read_only",
            ),
            now=now + timedelta(seconds=1),
        )
        read_finished = await update_tool_invocation(
            session,
            ContextToolInvocationUpdateRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="read-call-1",
                state="succeeded",
                result_event_id=ingested.event_ids[3],
            ),
            now=now + timedelta(seconds=1),
        )
        retryable_tool = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="retry-call-1",
                tool_name="gmail_send",
                arguments={"request_id": "retryable-id", "subject": "Retry"},
                side_effect_class="idempotent_write",
                caller_idempotency_key="retryable-id",
            ),
            now=now + timedelta(seconds=1),
        )
        await update_tool_invocation(
            session,
            ContextToolInvocationUpdateRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="retry-call-1",
                state="not_delivered",
            ),
            now=now + timedelta(seconds=1),
        )
        write_replay = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="retry-call-2",
                tool_name="gmail_send",
                arguments={"request_id": "retryable-id", "subject": "Retry"},
                side_effect_class="idempotent_write",
                caller_idempotency_key="retryable-id",
            ),
            now=now + timedelta(seconds=1),
        )
        write_finished = await update_tool_invocation(
            session,
            ContextToolInvocationUpdateRequest(
                run_id=first.run.id,
                lease_owner="atlas-one",
                tool_call_id="retry-call-1",
                state="succeeded",
                result_event_id=ingested.event_ids[4],
            ),
            now=now + timedelta(seconds=1),
        )
        completed = await update_run_state(
            session,
            ContextRunUpdateRequest(
                run_id=first.run.id,
                state="succeeded",
                lease_owner="atlas-one",
                final_response_event_id=ingested.event_ids[5],
            ),
            now=now + timedelta(seconds=1),
        )
        await session.commit()
    assert tool.replay_decision == "execute"
    assert finished.replay_decision == "restore_result"
    assert finished.result_content == "Saved response"
    assert replayed_tool.replay_decision == "restore_result"
    assert replayed_tool.result_content == "Saved response"
    assert regenerated_tool.invocation_id == tool.invocation_id
    assert regenerated_tool.replay_decision == "restore_result"
    assert regenerated_tool.result_content == "Saved response"
    assert arguments_only_replay.invocation_id == tool.invocation_id
    assert arguments_only_replay.replay_decision == "restore_result"
    assert read_tool.replay_decision == "execute"
    assert read_replay.replay_decision == "repeat_read"
    assert read_finished.replay_decision == "restore_result"
    assert retryable_tool.replay_decision == "execute"
    assert write_replay.replay_decision == "retry_not_delivered"
    assert write_finished.replay_decision == "restore_result"
    assert completed.state == "succeeded"


@pytest.mark.asyncio
async def test_tool_result_event_must_match_the_exact_run_and_call(
    context_sessions,
) -> None:
    from schemas.sydney_context import (
        ContextRunClaimRequest,
        ContextRunStartRequest,
        ContextToolInvocationRequest,
        ContextToolInvocationUpdateRequest,
    )
    from services.sydney_context_service import (
        ContextToolConflict,
        claim_runs,
        ingest_event_batch,
        start_run,
        start_tool_invocation,
        update_tool_invocation,
    )

    _engine, factory = context_sessions
    base = _request()

    def result_event(
        source_key: str,
        *,
        event_type: str = "tool_result",
        tool_name: str = "gmail_send",
        tool_call_id: str = "call-1",
    ):
        return base.events[0].model_copy(
            update={
                "source_event_key": source_key,
                "event_type": event_type,
                "role": "tool" if event_type == "tool_result" else "assistant",
                "occurred_at": base.events[0].occurred_at + timedelta(seconds=1),
                "content": f"Result for {source_key}",
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
            }
        )

    local = base.model_copy(
        update={
            "events": [
                base.events[0],
                result_event("session-1:correct-result"),
                result_event("session-1:wrong-type", event_type="assistant"),
                result_event("session-1:wrong-tool", tool_name="calendar_event_create"),
                result_event("session-1:wrong-call", tool_call_id="other-call"),
            ]
        }
    )
    foreign = base.model_copy(
        update={
            "external_user_id": "other-user",
            "external_chat_id": "other-chat",
            "hermes_session_id": "foreign-session",
            "logical_conversation_id": uuid4(),
            "events": [result_event("foreign-session:matching-result")],
        }
    )
    now = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)
    async with factory() as session:
        local_ingest = await ingest_event_batch(session, local)
        foreign_ingest = await ingest_event_batch(session, foreign)
        run = await start_run(
            session,
            ContextRunStartRequest(
                identity_id=local_ingest.identity_id,
                platform_message_id="tool-result-provenance",
                inbound_event_id=local_ingest.event_ids[0],
                session_id=local_ingest.session_id,
                logical_conversation_id=local.logical_conversation_id,
                terminal_deadline_at=now + timedelta(hours=1),
            ),
        )
        await session.commit()
    async with factory() as session:
        await claim_runs(
            session,
            ContextRunClaimRequest(lease_owner="atlas-one"),
            now=now,
            lease_seconds=120,
        )
        await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=run.run.id,
                lease_owner="atlas-one",
                tool_call_id="call-1",
                tool_name="gmail_send",
                arguments={"request_id": "provenance-test"},
                side_effect_class="idempotent_write",
                caller_idempotency_key="provenance-test",
            ),
            now=now + timedelta(seconds=1),
        )
        await session.commit()

    invalid_event_ids = [
        *local_ingest.event_ids[2:],
        foreign_ingest.event_ids[0],
    ]
    for invalid_event_id in invalid_event_ids:
        async with factory() as session:
            with pytest.raises(
                ContextToolConflict,
                match="^context_tool_result_event_invalid$",
            ):
                await update_tool_invocation(
                    session,
                    ContextToolInvocationUpdateRequest(
                        run_id=run.run.id,
                        lease_owner="atlas-one",
                        tool_call_id="call-1",
                        state="succeeded",
                        result_event_id=invalid_event_id,
                    ),
                    now=now + timedelta(seconds=2),
                )
            await session.rollback()

    async with factory() as session:
        finished = await update_tool_invocation(
            session,
            ContextToolInvocationUpdateRequest(
                run_id=run.run.id,
                lease_owner="atlas-one",
                tool_call_id="call-1",
                state="succeeded",
                result_event_id=local_ingest.event_ids[1],
            ),
            now=now + timedelta(seconds=2),
        )
        await session.commit()

    assert finished.replay_decision == "restore_result"
    assert finished.result_content == "Result for session-1:correct-result"


@pytest.mark.asyncio
async def test_run_events_must_match_the_exact_conversation_and_role(
    context_sessions,
) -> None:
    from schemas.sydney_context import (
        ContextRunClaimRequest,
        ContextRunStartRequest,
        ContextRunUpdateRequest,
    )
    from services.sydney_context_service import (
        ContextRunConflict,
        claim_runs,
        ingest_event_batch,
        start_run,
        update_run_state,
    )

    _engine, factory = context_sessions
    base = _request()

    def assistant_event(source_key: str):
        return base.events[0].model_copy(
            update={
                "source_event_key": source_key,
                "event_type": "assistant",
                "role": "assistant",
                "occurred_at": base.events[0].occurred_at + timedelta(seconds=1),
                "content": f"Response for {source_key}",
            }
        )

    local = base.model_copy(
        update={
            "events": [
                base.events[0],
                assistant_event("session-1:assistant-response"),
            ]
        }
    )
    foreign = base.model_copy(
        update={
            "external_user_id": "other-run-user",
            "external_chat_id": "other-run-chat",
            "hermes_session_id": "foreign-run-session",
            "logical_conversation_id": uuid4(),
            "events": [
                base.events[0].model_copy(
                    update={"source_event_key": "foreign-run-session:user"}
                ),
                assistant_event("foreign-run-session:assistant"),
            ],
        }
    )
    now = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)
    async with factory() as session:
        local_ingest = await ingest_event_batch(session, local)
        foreign_ingest = await ingest_event_batch(session, foreign)
        await session.commit()

    for platform_message_id, inbound_event_id in (
        ("wrong-inbound-role", local_ingest.event_ids[1]),
        ("foreign-inbound", foreign_ingest.event_ids[0]),
    ):
        async with factory() as session:
            with pytest.raises(
                ContextRunConflict,
                match="^context_run_inbound_event_invalid$",
            ):
                await start_run(
                    session,
                    ContextRunStartRequest(
                        identity_id=local_ingest.identity_id,
                        platform_message_id=platform_message_id,
                        inbound_event_id=inbound_event_id,
                        session_id=local_ingest.session_id,
                        logical_conversation_id=local.logical_conversation_id,
                        terminal_deadline_at=now + timedelta(hours=1),
                    ),
                )
            await session.rollback()

    async with factory() as session:
        run = await start_run(
            session,
            ContextRunStartRequest(
                identity_id=local_ingest.identity_id,
                platform_message_id="valid-run-provenance",
                inbound_event_id=local_ingest.event_ids[0],
                session_id=local_ingest.session_id,
                logical_conversation_id=local.logical_conversation_id,
                terminal_deadline_at=now + timedelta(hours=1),
            ),
        )
        await session.commit()
    async with factory() as session:
        await claim_runs(
            session,
            ContextRunClaimRequest(lease_owner="atlas-one", run_id=run.run.id),
            now=now,
            lease_seconds=120,
        )
        await session.commit()

    for final_event_id in (
        local_ingest.event_ids[0],
        foreign_ingest.event_ids[1],
    ):
        async with factory() as session:
            with pytest.raises(
                ContextRunConflict,
                match="^context_run_final_event_invalid$",
            ):
                await update_run_state(
                    session,
                    ContextRunUpdateRequest(
                        run_id=run.run.id,
                        state="succeeded",
                        lease_owner="atlas-one",
                        final_response_event_id=final_event_id,
                    ),
                    now=now + timedelta(seconds=1),
                )
            await session.rollback()

    async with factory() as session:
        completed = await update_run_state(
            session,
            ContextRunUpdateRequest(
                run_id=run.run.id,
                state="succeeded",
                lease_owner="atlas-one",
                final_response_event_id=local_ingest.event_ids[1],
            ),
            now=now + timedelta(seconds=1),
        )
        await session.commit()

    assert completed.state == "succeeded"
    assert completed.final_response_event_id == local_ingest.event_ids[1]


@pytest.mark.asyncio
async def test_run_scoped_claim_never_leases_a_newer_run_ahead_of_fifo(
    context_sessions,
) -> None:
    from models.sydney_context import AgentRunJob
    from schemas.sydney_context import ContextRunClaimRequest, ContextRunStartRequest
    from services.sydney_context_service import (
        claim_runs,
        ingest_event_batch,
        start_run,
    )

    _engine, factory = context_sessions
    base = _request()
    batch = base.model_copy(
        update={
            "events": [
                base.events[0],
                base.events[0].model_copy(
                    update={
                        "source_event_key": "session-1:message-fifo-2",
                        "occurred_at": base.events[0].occurred_at
                        + timedelta(seconds=1),
                        "content": "A newer request",
                    }
                ),
            ]
        }
    )
    now = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)
    async with factory() as session:
        ingested = await ingest_event_batch(session, batch)
        older = await start_run(
            session,
            ContextRunStartRequest(
                identity_id=ingested.identity_id,
                platform_message_id="telegram-fifo-older",
                inbound_event_id=ingested.event_ids[0],
                session_id=ingested.session_id,
                logical_conversation_id=batch.logical_conversation_id,
                terminal_deadline_at=now + timedelta(hours=24),
            ),
        )
        newer = await start_run(
            session,
            ContextRunStartRequest(
                identity_id=ingested.identity_id,
                platform_message_id="telegram-fifo-newer",
                inbound_event_id=ingested.event_ids[1],
                session_id=ingested.session_id,
                logical_conversation_id=batch.logical_conversation_id,
                terminal_deadline_at=now + timedelta(hours=24),
            ),
        )
        await session.execute(
            sa.update(AgentRunJob)
            .where(AgentRunJob.id == older.run.id)
            .values(created_at=now)
        )
        await session.execute(
            sa.update(AgentRunJob)
            .where(AgentRunJob.id == newer.run.id)
            .values(created_at=now + timedelta(seconds=1))
        )
        await session.commit()

    async with factory() as session:
        blocked = await claim_runs(
            session,
            ContextRunClaimRequest(
                lease_owner="interactive-worker",
                identity_id=ingested.identity_id,
                run_id=newer.run.id,
            ),
            now=now,
        )
        await session.commit()
    assert blocked.runs == []

    async with factory() as session:
        claimed = await claim_runs(
            session,
            ContextRunClaimRequest(
                lease_owner="continuation-watcher",
                identity_id=ingested.identity_id,
            ),
            now=now,
        )
        await session.commit()
    assert [run.id for run in claimed.runs] == [older.run.id]


@pytest.mark.asyncio
async def test_projection_range_claim_allows_only_one_concurrent_worker(
    context_sessions,
) -> None:
    from models.sydney_context import AgentContextProjectionClaim
    from schemas.sydney_context import SydneyContextProjectionResult
    from services.sydney_context_projection import (
        SydneyContextProjectionError,
        apply_projection_result,
        claim_projection_candidate,
        release_projection_claim,
    )
    from services.sydney_context_service import ingest_event_batch

    _engine, factory = context_sessions
    async with factory() as session:
        await ingest_event_batch(session, _request())
        await session.commit()

    claimed_at = datetime.now(UTC)

    async def claim_once(owner: str):
        async with factory() as session:
            candidate = await claim_projection_candidate(
                session,
                lease_owner=owner,
                claimed_at=claimed_at,
                lease_seconds=90,
            )
            await session.commit()
            return candidate

    results = await asyncio.gather(
        claim_once("projection-a"), claim_once("projection-b")
    )
    winners = [candidate for candidate in results if candidate is not None]
    assert len(winners) == 1
    winner = winners[0]
    assert winner.projection_claim_id is not None
    assert winner.projection_claim_token is not None
    assert winner.projection_claim_range_hash is not None

    async with factory() as session:
        claims = list(
            (await session.scalars(sa.select(AgentContextProjectionClaim))).all()
        )
    assert len(claims) == 1
    assert claims[0].lease_token == winner.projection_claim_token

    async with factory() as session:
        assert await release_projection_claim(session, winner) is True
        await session.commit()
    async with factory() as session:
        reclaimed = await claim_projection_candidate(
            session,
            lease_owner="projection-c",
            claimed_at=claimed_at + timedelta(seconds=1),
            lease_seconds=90,
        )
        await session.commit()
    assert reclaimed is not None
    assert reclaimed.projection_claim_token != winner.projection_claim_token
    result = SydneyContextProjectionResult(
        schema_version="sydney-context-v1",
        rolling_summary="The claimed range was projected once.",
        source_event_ids=list(reclaimed.source_event_ids),
    )
    async with factory() as session:
        with pytest.raises(
            SydneyContextProjectionError,
            match="^sydney_projection_claim_lost$",
        ):
            await apply_projection_result(
                session, winner, result, produced_at=claimed_at
            )
        await session.rollback()
    async with factory() as session:
        await apply_projection_result(
            session,
            reclaimed,
            result,
            produced_at=claimed_at + timedelta(seconds=2),
        )
        await session.commit()
    async with factory() as session:
        remaining_claims = int(
            await session.scalar(
                sa.select(sa.func.count()).select_from(AgentContextProjectionClaim)
            )
            or 0
        )
    assert remaining_claims == 0


@pytest.mark.asyncio
async def test_projection_claim_skips_a_leased_conversation_for_other_work(
    context_sessions,
) -> None:
    from services.sydney_context_projection import claim_projection_candidate
    from services.sydney_context_service import ingest_event_batch

    _engine, factory = context_sessions
    first = _request()
    second_logical_id = uuid4()
    second = first.model_copy(
        update={
            "hermes_session_id": "session-2",
            "logical_conversation_id": second_logical_id,
            "events": [
                first.events[0].model_copy(
                    update={"source_event_key": "session-2:message-1"}
                )
            ],
        }
    )
    async with factory() as session:
        await ingest_event_batch(session, first)
        await ingest_event_batch(session, second)
        await session.commit()

    claimed_at = datetime.now(UTC)
    async with factory() as session:
        first_claim = await claim_projection_candidate(
            session,
            lease_owner="projection-a",
            claimed_at=claimed_at,
            lease_seconds=90,
        )
        await session.commit()
    async with factory() as session:
        second_claim = await claim_projection_candidate(
            session,
            lease_owner="projection-b",
            claimed_at=claimed_at,
            lease_seconds=90,
        )
        await session.commit()

    assert first_claim is not None
    assert second_claim is not None
    assert first_claim.logical_conversation_id != second_claim.logical_conversation_id
    assert {
        first_claim.logical_conversation_id,
        second_claim.logical_conversation_id,
    } == {first.logical_conversation_id, second_logical_id}


@pytest.mark.asyncio
async def test_projection_candidate_checkpoint_and_fact_supersession_are_source_linked(
    context_sessions,
) -> None:
    from models.sydney_context import AgentContextCheckpoint, AgentMemoryFact
    from schemas.sydney_context import SydneyContextProjectionResult
    from services.sydney_context_projection import (
        apply_projection_result,
        select_projection_candidate,
    )
    from services.sydney_context_service import ingest_event_batch

    _engine, factory = context_sessions
    base = _request()
    batch = base.model_copy(
        update={
            "events": [
                base.events[0],
                base.events[0].model_copy(
                    update={
                        "source_event_key": "session-1:message-2",
                        "event_type": "assistant",
                        "role": "assistant",
                        "occurred_at": base.events[0].occurred_at
                        + timedelta(seconds=1),
                        "content": "The gold folder is preferred.",
                    }
                ),
            ]
        }
    )
    async with factory() as session:
        ingested = await ingest_event_batch(session, batch)
        await session.commit()
    async with factory() as session:
        candidate = await select_projection_candidate(session)
        assert candidate is not None
        assert candidate.source_event_ids == tuple(ingested.event_ids)
        result = SydneyContextProjectionResult(
            schema_version="sydney-context-v1",
            rolling_summary="Brandon prefers the gold folder.",
            source_event_ids=list(candidate.source_event_ids),
            fact_operations=[
                {
                    "operation": "upsert",
                    "canonical_key": "preference.folder",
                    "kind": "preference",
                    "value": {"name": "gold"},
                    "confidence": 0.95,
                    "source_event_ids": [candidate.source_event_ids[-1]],
                }
            ],
        )
        first = await apply_projection_result(session, candidate, result)
        replay = await apply_projection_result(session, candidate, result)
        assert first.id == replay.id
        await session.commit()

    async with factory() as session:
        checkpoints = list(
            (await session.scalars(sa.select(AgentContextCheckpoint))).all()
        )
        facts = list((await session.scalars(sa.select(AgentMemoryFact))).all())
    assert len(checkpoints) == 1
    assert checkpoints[0].source_event_ids == ingested.event_ids
    assert len(facts) == 1
    assert facts[0].status == "active"
    assert facts[0].source_event_ids == [ingested.event_ids[-1]]

    other_logical_id = uuid4()
    async with factory() as session:
        other_fact = AgentMemoryFact(
            identity_id=ingested.identity_id,
            logical_conversation_id=other_logical_id,
            canonical_key="preference.folder",
            kind="preference",
            value_json={"name": "independent"},
            confidence=Decimal("0.9000"),
            status="active",
            valid_at=datetime(2026, 8, 25, 17, 30, tzinfo=UTC),
            projection_version="sydney-context-v1:independent:0",
            source_event_ids=[ingested.event_ids[0]],
        )
        session.add(other_fact)
        await session.commit()
        other_fact_id = other_fact.id

    continuation = batch.model_copy(
        update={
            "events": [
                base.events[0].model_copy(
                    update={
                        "source_event_key": "session-1:message-3",
                        "occurred_at": base.events[0].occurred_at
                        + timedelta(seconds=2),
                        "content": "The blue folder replaces that preference.",
                    }
                )
            ]
        }
    )
    async with factory() as session:
        continued = await ingest_event_batch(session, continuation)
        await session.commit()
    async with factory() as session:
        next_candidate = await select_projection_candidate(session)
        assert next_candidate is not None
        assert next_candidate.source_event_ids == tuple(continued.event_ids)
        next_result = SydneyContextProjectionResult(
            schema_version="sydney-context-v1",
            rolling_summary="Brandon now prefers the blue folder.",
            source_event_ids=list(next_candidate.source_event_ids),
            fact_operations=[
                {
                    "operation": "upsert",
                    "canonical_key": "preference.folder",
                    "kind": "preference",
                    "value": {"name": "blue"},
                    "confidence": 0.96,
                    "source_event_ids": list(next_candidate.source_event_ids),
                }
            ],
        )
        await apply_projection_result(session, next_candidate, next_result)
        await session.commit()
    async with factory() as session:
        facts = list(
            (
                await session.scalars(
                    sa.select(AgentMemoryFact).order_by(AgentMemoryFact.created_at)
                )
            ).all()
        )
        checkpoint_count = int(
            await session.scalar(
                sa.select(sa.func.count()).select_from(AgentContextCheckpoint)
            )
            or 0
        )
        checkpoints = list(
            (
                await session.scalars(
                    sa.select(AgentContextCheckpoint).order_by(
                        AgentContextCheckpoint.produced_at,
                        AgentContextCheckpoint.id,
                    )
                )
            ).all()
        )
    assert checkpoint_count == 2
    assert checkpoints[-1].parent_checkpoint_id == checkpoints[0].id
    assert checkpoints[0].source_event_ids == ingested.event_ids
    assert checkpoints[-1].source_event_ids == continued.event_ids
    assert checkpoints[-1].covered_range_hash != checkpoints[0].covered_range_hash
    conversation_facts = [
        fact
        for fact in facts
        if fact.logical_conversation_id == batch.logical_conversation_id
    ]
    independent_fact = next(fact for fact in facts if fact.id == other_fact_id)
    assert [fact.status for fact in conversation_facts] == ["superseded", "active"]
    assert conversation_facts[-1].value_json == {"name": "blue"}
    assert conversation_facts[-1].source_event_ids == continued.event_ids
    assert independent_fact.status == "active"
    assert independent_fact.superseded_at is None

    unprojected = continuation.model_copy(
        update={
            "events": [
                base.events[0].model_copy(
                    update={
                        "source_event_key": "session-1:message-4",
                        "occurred_at": base.events[0].occurred_at
                        + timedelta(seconds=3),
                        "content": "One newer event has not been projected yet.",
                    }
                )
            ]
        }
    )
    async with factory() as session:
        await ingest_event_batch(session, unprojected)
        await session.commit()
    async with factory() as session:
        from services.sydney_context_service import get_context_health

        health = await get_context_health(
            session,
            flags={"durable_context": True},
        )
    assert health.checkpoint_lag_events == 1


@pytest.mark.asyncio
async def test_health_ignores_superseded_and_recovered_terminal_history(
    context_sessions,
) -> None:
    from models.sydney_context import AgentRunJob
    from services.sydney_context_service import (
        get_context_health,
        ingest_event_batch,
        request_fingerprint_sha256,
    )

    _engine, factory = context_sessions
    now = datetime.now(UTC)
    request = _request()
    async with factory() as session:
        ingested = await ingest_event_batch(session, request)
        run = AgentRunJob(
            identity_id=ingested.identity_id,
            platform_message_id="health-superseded",
            inbound_event_id=ingested.event_ids[0],
            session_id=ingested.session_id,
            logical_conversation_id=request.logical_conversation_id,
            request_fingerprint_sha256=request_fingerprint_sha256(
                request.events[0].content
            ),
            state="terminal_failure",
            attempt_count=1,
            terminal_deadline_at=now + timedelta(hours=1),
            error_code="superseded_by_newer_inbound",
            updated_at=now,
        )
        session.add(run)
        await session.commit()

    async with factory() as session:
        healthy = await get_context_health(
            session,
            flags={"durable_context": True},
            now=now,
        )
        run = await session.get(AgentRunJob, run.id)
        run.error_code = "provider_terminal_failure"
        run.updated_at = now
        await session.commit()

    assert healthy.run_states["terminal_failure"] == 1
    assert healthy.status == "ready"

    async with factory() as session:
        degraded = await get_context_health(
            session,
            flags={"durable_context": True},
            now=now,
        )
        run = await session.get(AgentRunJob, run.id)
        run.updated_at = now - timedelta(minutes=16)
        await session.commit()

    assert degraded.status == "degraded"

    async with factory() as session:
        recovered = await get_context_health(
            session,
            flags={"durable_context": True},
            now=now,
        )

    assert recovered.status == "ready"


@pytest.mark.asyncio
async def test_health_degrades_when_enabled_projection_health_is_degraded(
    context_sessions,
) -> None:
    from models.integration_health import IntegrationHealthState
    from services.sydney_context_service import get_context_health

    _engine, factory = context_sessions
    now = datetime.now(UTC)
    async with factory() as session:
        session.add(
            IntegrationHealthState(
                provider="sydney_context_projection",
                state="degraded",
                last_checked_at=now,
                last_error_category="provider_timeout",
                last_error_message="Provider request timed out.",
                consecutive_failures=1,
                transition_epoch=1,
            )
        )
        await session.commit()

    async with factory() as session:
        health = await get_context_health(
            session,
            flags={"durable_context": True, "projection": True},
            now=now,
        )

    assert health.status == "degraded"


@pytest.mark.asyncio
async def test_health_pairs_latest_reconciliation_time_with_its_event_count(
    context_sessions,
) -> None:
    from models.sydney_context import AgentConversationSession
    from services.sydney_context_service import get_context_health, ingest_event_batch

    _engine, factory = context_sessions
    first_request = _request()
    second_request = first_request.model_copy(
        update={
            "hermes_session_id": "session-2",
            "logical_conversation_id": uuid4(),
            "events": [
                first_request.events[0].model_copy(
                    update={
                        "source_event_key": "session-2:message-1",
                        "occurred_at": first_request.events[0].occurred_at
                        + timedelta(seconds=1),
                    }
                )
            ],
        }
    )
    latest_at = datetime(2026, 8, 25, 20, 0, tzinfo=UTC)
    async with factory() as session:
        first = await ingest_event_batch(session, first_request)
        second = await ingest_event_batch(session, second_request)
        older_session = await session.get(AgentConversationSession, first.session_id)
        latest_session = await session.get(AgentConversationSession, second.session_id)
        older_session.reconciliation_hash = "a" * 64
        older_session.source_event_count = 100
        older_session.updated_at = latest_at - timedelta(minutes=10)
        latest_session.reconciliation_hash = "b" * 64
        latest_session.source_event_count = 2
        latest_session.updated_at = latest_at
        await session.commit()

    async with factory() as session:
        health = await get_context_health(
            session,
            flags={"durable_context": True},
            now=latest_at,
        )

    assert health.last_reconciled_at == latest_at
    assert health.last_reconciled_event_count == 2


@pytest.mark.asyncio
async def test_projection_resumes_every_chunk_of_an_oversized_event(
    context_sessions,
) -> None:
    from models.sydney_context import AgentContextCheckpoint
    from schemas.sydney_context import SydneyContextProjectionResult
    from services.sydney_context_projection import (
        apply_projection_result,
        build_projection_request,
        select_projection_candidate,
    )
    from services.sydney_context_service import get_context_health, ingest_event_batch

    _engine, factory = context_sessions
    source = ("A" * 1_000) + ("B" * 1_000) + ("C" * 400)
    base = _request()
    batch = base.model_copy(
        update={"events": [base.events[0].model_copy(update={"content": source})]}
    )
    async with factory() as session:
        ingested = await ingest_event_batch(session, batch)
        await session.commit()

    observed_chunks: list[str] = []
    observed_lag: list[int] = []
    for expected_offset in (1_000, 2_000, 2_400):
        async with factory() as session:
            candidate = await select_projection_candidate(
                session,
                transcript_chars=1_000,
            )
            assert candidate is not None
            assert candidate.source_event_ids == (ingested.event_ids[0],)
            assert candidate.boundary_char_offset == expected_offset
            observed_chunks.append(candidate.events[0].content)
            request = build_projection_request(candidate)
            assert candidate.events[0].content in request.prompt
            result = SydneyContextProjectionResult(
                schema_version="sydney-context-v1",
                rolling_summary=f"Projected through character {expected_offset}.",
                source_event_ids=list(candidate.source_event_ids),
            )
            await apply_projection_result(session, candidate, result)
            await session.commit()
        async with factory() as session:
            health = await get_context_health(
                session,
                flags={"durable_context": True},
            )
            observed_lag.append(health.checkpoint_lag_events)

    assert observed_chunks == ["A" * 1_000, "B" * 1_000, "C" * 400]
    assert observed_lag == [1, 1, 0]
    async with factory() as session:
        assert (
            await select_projection_candidate(session, transcript_chars=1_000) is None
        )
        checkpoints = list(
            (
                await session.scalars(
                    sa.select(AgentContextCheckpoint).order_by(
                        AgentContextCheckpoint.produced_at,
                        AgentContextCheckpoint.id,
                    )
                )
            ).all()
        )
    assert [checkpoint.source_boundary_char_offset for checkpoint in checkpoints] == [
        1_000,
        2_000,
        2_400,
    ]
    assert all(
        checkpoint.source_event_ids == [ingested.event_ids[0]]
        for checkpoint in checkpoints
    )
    assert len({checkpoint.covered_range_hash for checkpoint in checkpoints}) == 3


@pytest.mark.asyncio
async def test_projection_keeps_a_late_ingested_event_eligible(
    context_sessions,
) -> None:
    from schemas.sydney_context import SydneyContextProjectionResult
    from services.sydney_context_projection import (
        apply_projection_result,
        select_projection_candidate,
    )
    from services.sydney_context_service import ingest_event_batch

    _engine, factory = context_sessions
    first = _request()
    async with factory() as session:
        first_ingest = await ingest_event_batch(session, first)
        await session.commit()
    async with factory() as session:
        candidate = await select_projection_candidate(session)
        assert candidate is not None
        await apply_projection_result(
            session,
            candidate,
            SydneyContextProjectionResult(
                schema_version="sydney-context-v1",
                rolling_summary="The first event was projected.",
                source_event_ids=list(candidate.source_event_ids),
            ),
        )
        await session.commit()

    late = first.model_copy(
        update={
            "events": [
                first.events[0].model_copy(
                    update={
                        "source_event_key": "session-1:late-message",
                        "occurred_at": first.events[0].occurred_at - timedelta(days=1),
                        "content": "This arrived late but must still be projected.",
                    }
                )
            ]
        }
    )
    async with factory() as session:
        late_ingest = await ingest_event_batch(session, late)
        await session.commit()
    async with factory() as session:
        candidate = await select_projection_candidate(session)

    assert first_ingest.event_ids != late_ingest.event_ids
    assert candidate is not None
    assert candidate.source_event_ids == (late_ingest.event_ids[0],)


@pytest.mark.asyncio
async def test_projection_candidate_skips_one_hundred_completed_conversations(
    context_sessions,
) -> None:
    from models.sydney_context import AgentContextCheckpoint
    from services.sydney_context_projection import select_projection_candidate
    from services.sydney_context_service import ingest_event_batch

    _engine, factory = context_sessions
    base = _request()
    expected_logical_id = UUID(int=101)
    async with factory() as session:
        for index in range(101):
            logical_id = UUID(int=index + 1)
            content = f"Projection conversation {index + 1}"
            request = base.model_copy(
                update={
                    "hermes_session_id": f"projection-session-{index + 1:03d}",
                    "logical_conversation_id": logical_id,
                    "events": [
                        base.events[0].model_copy(
                            update={
                                "source_event_key": (
                                    f"projection-session-{index + 1:03d}:message-1"
                                ),
                                "occurred_at": base.events[0].occurred_at
                                + timedelta(seconds=index),
                                "content": content,
                            }
                        )
                    ],
                }
            )
            ingested = await ingest_event_batch(session, request)
            if index < 100:
                session.add(
                    AgentContextCheckpoint(
                        identity_id=ingested.identity_id,
                        logical_conversation_id=logical_id,
                        source_boundary_event_id=ingested.event_ids[0],
                        source_boundary_char_offset=len(content),
                        schema_version="sydney-context-v1",
                        rolling_summary=f"Completed conversation {index + 1}",
                        active_state_json={},
                        source_event_ids=[ingested.event_ids[0]],
                        covered_range_hash=f"{index + 1:064x}",
                    )
                )
        await session.commit()

    async with factory() as session:
        candidate = await select_projection_candidate(session)

    assert candidate is not None
    assert candidate.logical_conversation_id == expected_logical_id


@pytest.mark.asyncio
async def test_two_connections_claim_one_eligible_run_once(context_sessions) -> None:
    from schemas.sydney_context import ContextRunClaimRequest, ContextRunStartRequest
    from services.sydney_context_service import (
        claim_runs,
        ingest_event_batch,
        start_run,
    )

    _engine, factory = context_sessions
    request = _request()
    now = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)
    async with factory() as session:
        ingested = await ingest_event_batch(session, request)
        await start_run(
            session,
            ContextRunStartRequest(
                identity_id=ingested.identity_id,
                platform_message_id="telegram-claim-race",
                inbound_event_id=ingested.event_ids[0],
                session_id=ingested.session_id,
                logical_conversation_id=request.logical_conversation_id,
                terminal_deadline_at=now + timedelta(hours=24),
            ),
        )
        await session.commit()

    async def claim_once(owner: str):
        async with factory() as session:
            result = await claim_runs(
                session,
                ContextRunClaimRequest(lease_owner=owner),
                now=now,
            )
            await session.commit()
            return result

    results = await asyncio.gather(claim_once("atlas-a"), claim_once("atlas-b"))

    assert sum(len(result.runs) for result in results) == 1
    assert {run.lease_owner for result in results for run in result.runs} <= {
        "atlas-a",
        "atlas-b",
    }
