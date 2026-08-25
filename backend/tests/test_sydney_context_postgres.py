from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from schemas.sydney_context import ContextEventBatchRequest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
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
                        "event_type": "assistant",
                        "role": "assistant",
                        "occurred_at": base.events[0].occurred_at
                        + timedelta(seconds=1),
                        "content": "Saved response",
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
        tool = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=first.run.id,
                tool_call_id="call-1",
                tool_name="gmail_send",
                arguments={"request_id": "stable-id", "subject": "Hello"},
                side_effect_class="idempotent_write",
                caller_idempotency_key="stable-id",
            ),
        )
        finished = await update_tool_invocation(
            session,
            ContextToolInvocationUpdateRequest(
                run_id=first.run.id,
                tool_call_id="call-1",
                state="succeeded",
                result_event_id=ingested.event_ids[1],
            ),
        )
        replayed_tool = await start_tool_invocation(
            session,
            ContextToolInvocationRequest(
                run_id=first.run.id,
                tool_call_id="call-1",
                tool_name="gmail_send",
                arguments={"subject": "Hello", "request_id": "stable-id"},
                side_effect_class="idempotent_write",
                caller_idempotency_key="stable-id",
            ),
        )
        completed = await update_run_state(
            session,
            ContextRunUpdateRequest(
                run_id=first.run.id,
                state="succeeded",
                lease_owner="atlas-one",
                final_response_event_id=ingested.event_ids[1],
            ),
        )
        await session.commit()
    assert tool.replay_decision == "execute"
    assert finished.replay_decision == "restore_result"
    assert replayed_tool.replay_decision == "restore_result"
    assert completed.state == "succeeded"


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
    assert checkpoint_count == 2
    assert [fact.status for fact in facts] == ["superseded", "active"]
    assert facts[-1].value_json == {"name": "blue"}


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
