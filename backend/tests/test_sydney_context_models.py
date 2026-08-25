from __future__ import annotations

import importlib

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

TABLES = (
    "agent_conversation_identities",
    "agent_conversation_sessions",
    "agent_conversation_events",
    "agent_conversation_event_segments",
    "agent_context_checkpoints",
    "agent_memory_facts",
    "agent_run_jobs",
    "agent_tool_invocations",
)


def _tables() -> dict[str, sa.Table]:
    module = importlib.import_module("models.sydney_context")
    models = (
        module.AgentConversationIdentity,
        module.AgentConversationSession,
        module.AgentConversationEvent,
        module.AgentConversationEventSegment,
        module.AgentContextCheckpoint,
        module.AgentMemoryFact,
        module.AgentRunJob,
        module.AgentToolInvocation,
    )
    return {model.__table__.name: model.__table__ for model in models}


def test_sydney_context_models_own_exact_tables_and_uuid_primary_keys() -> None:
    tables = _tables()

    assert tuple(tables) == TABLES
    for table in tables.values():
        assert tuple(table.primary_key.columns.keys()) == ("id",)
        assert isinstance(table.c.id.type, postgresql.UUID)
        assert table.c.id.type.as_uuid is True


def test_identity_session_and_event_models_pin_durable_lineage() -> None:
    tables = _tables()
    identity = tables["agent_conversation_identities"]
    session = tables["agent_conversation_sessions"]
    event = tables["agent_conversation_events"]
    segment = tables["agent_conversation_event_segments"]

    assert {column.name for column in identity.columns} == {
        "id",
        "platform",
        "external_user_id",
        "external_chat_id",
        "display_label",
        "enabled",
        "retention_mode",
        "created_at",
        "updated_at",
        "last_seen_at",
    }
    assert any(
        isinstance(constraint, sa.UniqueConstraint)
        and tuple(column.name for column in constraint.columns)
        == ("platform", "external_user_id", "external_chat_id")
        for constraint in identity.constraints
    )
    assert session.c.hermes_session_id.unique is True
    assert session.c.parent_session_id.foreign_keys
    assert session.c.logical_conversation_id.nullable is False
    assert session.c.reconciliation_hash.type.length == 64

    assert isinstance(event.c.metadata_json.type, postgresql.JSONB)
    assert isinstance(event.c.token_metadata_json.type, postgresql.JSONB)
    assert isinstance(event.c.search_vector.type, postgresql.TSVECTOR)
    assert event.c.content_sha256.type.length == 64
    assert any(
        isinstance(constraint, sa.UniqueConstraint)
        and tuple(column.name for column in constraint.columns)
        == ("identity_id", "source_event_key")
        for constraint in event.constraints
    )
    assert any(
        index.name == "ix_agent_conversation_events_search" for index in event.indexes
    )
    assert any(
        isinstance(constraint, sa.UniqueConstraint)
        and tuple(column.name for column in constraint.columns)
        == ("event_id", "ordinal")
        for constraint in segment.constraints
    )


def test_checkpoint_fact_run_and_tool_models_pin_provenance_and_replay_state() -> None:
    tables = _tables()
    checkpoint = tables["agent_context_checkpoints"]
    fact = tables["agent_memory_facts"]
    run = tables["agent_run_jobs"]
    tool = tables["agent_tool_invocations"]

    assert isinstance(checkpoint.c.source_event_ids.type, postgresql.ARRAY)
    assert isinstance(checkpoint.c.active_state_json.type, postgresql.JSONB)
    assert isinstance(fact.c.value_json.type, postgresql.JSONB)
    assert isinstance(fact.c.source_event_ids.type, postgresql.ARRAY)
    assert any(
        isinstance(constraint, sa.UniqueConstraint)
        and tuple(column.name for column in constraint.columns)
        == ("identity_id", "canonical_key", "projection_version")
        for constraint in fact.constraints
    )
    assert any(
        isinstance(constraint, sa.UniqueConstraint)
        and tuple(column.name for column in constraint.columns)
        == ("identity_id", "platform_message_id")
        for constraint in run.constraints
    )
    assert run.c.attempt_count.nullable is False
    assert run.c.lease_expires_at.nullable is True
    assert any(index.name == "ix_agent_run_jobs_fifo_claim" for index in run.indexes)
    assert any(
        isinstance(constraint, sa.UniqueConstraint)
        and tuple(column.name for column in constraint.columns)
        == ("run_id", "tool_call_id")
        for constraint in tool.constraints
    )
    assert set(tool.columns.keys()).isdisjoint({"arguments", "result", "content"})
