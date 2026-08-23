from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "84d7a5f9b2c3"
UTC = timezone.utc
CHAT_ID = "-1001234567890"
CODE_KEY_VERSION = 7
CODE_KEY = b"k" * 32


def _contact_resolution_hash(contact_id: int, canonical_email: str) -> str:
    return hashlib.sha256(
        b"sws:crm-contact-resolution:v1\0"
        + str(contact_id).encode("ascii")
        + b"\0"
        + canonical_email.encode("utf-8")
    ).hexdigest()


def _service_module():
    spec = importlib.util.find_spec("services.sydney_clarification_service")
    assert spec is not None, "missing Sydney clarification service"
    return importlib.import_module("services.sydney_clarification_service")


@pytest.fixture(scope="module")
def clarification_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def clarification_runtime(clarification_database):
    from models.lead import Lead

    assert Lead.__table__.name == "leads"
    url, sync_engine = clarification_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE crm_task_clarifications, "
                "sydney_question_outbox, crm_task_suggestion_approval_nonces, "
                "crm_task_suggestion_events, crm_task_suggestions, "
                "crm_tasks, crm_activities, crm_task_links, "
                "crm_task_creation_requests, crm_task_sources, "
                "crm_record_lifecycle_events, "
                "gmail_sync_accounts, admin_users, agent_action_audits, "
                "crm_contacts CASCADE"
            )
        )
    engine = create_async_engine(
        async_test_url(url),
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessions
    finally:
        await engine.dispose()


def _service(sessions):
    module = _service_module()
    return module.SydneyClarificationService(
        sessionmaker=sessions,
        brandon_chat_id=CHAT_ID,
        clarification_code_keys={CODE_KEY_VERSION: CODE_KEY},
        active_code_key_version=CODE_KEY_VERSION,
    )


class _InlineExecutor:
    async def run(self, *, key, function, deadline_seconds):
        assert key.startswith("telegram:")
        assert deadline_seconds == 2
        return function()


class _ObservingExecutor:
    def __init__(self, sessions) -> None:
        self._sessions = sessions
        self.observed_states: list[str] = []

    async def run(self, *, key, function, deadline_seconds):
        from models.sydney_tasks import SydneyQuestionOutbox

        assert deadline_seconds == 2
        attempt_id = UUID(key.removeprefix("telegram:"))
        async with self._sessions() as session:
            attempt = await session.get(SydneyQuestionOutbox, attempt_id)
        assert attempt is not None
        assert attempt.attempted_at is not None
        self.observed_states.append(attempt.state)
        return function()


class _MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _dispatcher(
    sessions,
    *,
    clock: _MutableClock,
    send_message,
    executor=None,
):
    from services.sydney_telegram_dispatcher import (
        SydneyTelegramDispatcher,
        SydneyTelegramDispatcherConfig,
    )

    return SydneyTelegramDispatcher(
        sessionmaker=sessions,
        executor=executor or _InlineExecutor(),
        send_message=send_message,
        config=SydneyTelegramDispatcherConfig(
            enabled=True,
            bot_token="123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd",
            brandon_chat_id=CHAT_ID,
            clarification_code_keys={CODE_KEY_VERSION: CODE_KEY},
            active_code_key_version=CODE_KEY_VERSION,
            provider_deadline_seconds=2,
            provider_socket_timeout_seconds=1,
        ),
        clock=clock,
    )


async def _seed_suggestion(
    sessions,
    *,
    blocker_codes: list[str],
    owner_clarification_pending: bool = False,
    task_details_clarification_pending: bool = False,
    title: str = "Follow up with Alice",
    description: str = "Confirm the next step.",
    priority: str = "normal",
    due_at: datetime | None = None,
    contact_id: int | None = None,
    contact_resolution_state: str | None = None,
    contact_resolution_hash: str | None = None,
    version: int = 1,
    state: str | None = None,
    clarification_state: str | None = None,
    duplicate_of_suggestion_id: UUID | None = None,
):
    from models.gmail_task_intake import CRMTaskSuggestion
    from services.crm_task_suggestion_service import canonical_task_payload_hash

    request_id = uuid4()
    if contact_resolution_state is None:
        if contact_id is not None:
            raise AssertionError(
                "contact fixtures must provide an exact resolution state and hash"
            )
        contact_resolution_state = (
            "unresolved"
            if "ambiguous_contact" in blocker_codes
            else "not_provided"
        )
    row = CRMTaskSuggestion(
        source_type="sydney_chat",
        source_scope_key=f"sydney:{request_id}",
        source_action_key=f"sydney-action:{request_id.hex}",
        source_request_id=request_id,
        contact_id=contact_id,
        contact_resolution_state=contact_resolution_state,
        contact_resolution_hash=contact_resolution_hash,
        title=title,
        description=description,
        priority=priority,
        due_at=due_at,
        task_status="open",
        state=state or ("needs_clarification" if blocker_codes else "pending_review"),
        clarification_state=clarification_state
        or ("pending" if blocker_codes else "not_required"),
        blocker_codes=blocker_codes,
        owner_clarification_pending=owner_clarification_pending,
        task_details_clarification_pending=task_details_clarification_pending,
        payload_hash=canonical_task_payload_hash(
            title=title,
            description=description,
            priority=priority,
            due_at=due_at,
            contact_id=contact_id,
            status="open",
        ),
        model_schema_version="sydney-task-v1",
        obligation_fingerprint="a" * 64,
        duplicate_of_suggestion_id=duplicate_of_suggestion_id,
        confidence=1,
        rationale="",
        version=version,
    )
    async with sessions() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def _clarification_code(sessions, clarification_id: UUID) -> str:
    from models.sydney_tasks import CRMTaskClarification

    module = _service_module()
    async with sessions() as session:
        row = await session.get(CRMTaskClarification, clarification_id)
    assert row is not None
    return module.derive_clarification_code(
        key=CODE_KEY,
        key_version=row.code_key_version,
        clarification_id=row.id,
        suggestion_id=row.suggestion_id,
        suggestion_version=row.suggestion_version,
        field_name=row.field_name,
        round_number=row.round_number,
    )


async def _task_side_effect_counts(sessions) -> dict[str, int]:
    tables = (
        "crm_tasks",
        "crm_activities",
        "crm_task_links",
        "crm_task_creation_requests",
        "crm_task_sources",
        "crm_record_lifecycle_events",
        "crm_task_suggestion_sources",
    )
    async with sessions() as session:
        return {
            table: int(
                await session.scalar(sa.text(f"SELECT count(*) FROM {table}"))
                or 0
            )
            for table in tables
        }


async def _set_initial_delivery(
    sessions,
    *,
    clarification_id: UUID,
    state: str,
    now: datetime,
    chat_id: str = CHAT_ID,
) -> None:
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox

    async with sessions() as session:
        clarification = await session.get(CRMTaskClarification, clarification_id)
        attempt = await session.scalar(
            sa.select(SydneyQuestionOutbox).where(
                SydneyQuestionOutbox.clarification_id == clarification_id,
                SydneyQuestionOutbox.attempt_kind == "initial",
            )
        )
        assert clarification is not None and attempt is not None
        if state == "pending":
            await session.rollback()
            return
        terminal_state = state
        attempt.state = "sending"
        attempt.attempted_at = now
        attempt.telegram_chat_id = chat_id
        clarification.first_attempt_at = now
        clarification.deadline_anchor_kind = "first_attempt"
        clarification.deadline_anchored_at = now
        clarification.slot_deadline_at = now + timedelta(hours=48)
        await session.flush()
        attempt.state = terminal_state
        if terminal_state == "sent":
            attempt.sent_at = now + timedelta(seconds=1)
            attempt.telegram_message_id = "9001"
            clarification.deadline_anchor_kind = "initial_sent"
            clarification.deadline_anchored_at = attempt.sent_at
            clarification.slot_deadline_at = attempt.sent_at + timedelta(hours=48)
        elif terminal_state in {"failed", "delivery_uncertain"}:
            attempt.failure_category = (
                "provider_rejected"
                if terminal_state == "failed"
                else "provider_timeout"
            )
        else:
            raise AssertionError(
                f"unsupported test delivery state: {terminal_state}"
            )
        await session.commit()


def test_clarification_code_derivation_matches_locked_vector_and_is_canonical() -> None:
    module = _service_module()
    clarification_id = UUID("00000000-0000-4000-8000-000000000001")
    suggestion_id = UUID("00000000-0000-4000-8000-000000000002")
    code = module.derive_clarification_code(
        key=CODE_KEY,
        key_version=7,
        clarification_id=clarification_id,
        suggestion_id=suggestion_id,
        suggestion_version=3,
        field_name="due_at",
        round_number=2,
    )
    assert code == "SmYh3VL0sc72tl8vAilNEg"
    assert len(base64.urlsafe_b64decode(code + "==")) == 16
    assert module.clarification_code_hash(code).hex() == (
        "f981ba6992505a91d7d92a61c59a947aab115238624ea72945cf694c2b28e31e"
    )
    assert module.parse_clarification_code(code) == code


@pytest.mark.parametrize(
    "value",
    [
        "",
        "short",
        "SmYh3VL0sc72tl8vAilNEg=",
        "SmYh3VL0sc72tl8v+ilNEg",
        "SmYh3VL0sc72tl8vAilNE!",
        "ＳｍＹｈ３ＶＬ０ｓｃ７２ｔｌ８ｖＡｉｌＮＥｇ",
    ],
)
def test_clarification_code_parser_rejects_short_padded_or_noncanonical_input(
    value: str,
) -> None:
    module = _service_module()
    with pytest.raises(module.SydneyClarificationError) as raised:
        module.parse_clarification_code(value)
    assert str(raised.value) == "invalid_clarification_code"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.parametrize("bad_key", [b"", b"k" * 31, b"k" * 33, "k" * 32])
def test_clarification_code_requires_an_exact_32_byte_injected_key(
    bad_key: object,
) -> None:
    module = _service_module()
    with pytest.raises(module.SydneyClarificationError) as raised:
        module.derive_clarification_code(
            key=bad_key,
            key_version=1,
            clarification_id=uuid4(),
            suggestion_id=uuid4(),
            suggestion_version=1,
            field_name="due_at",
            round_number=1,
        )
    assert str(raised.value) == "clarification_code_key_invalid"


def test_approval_token_uses_exact_32_byte_source_and_hashes_only_ascii_token(
    monkeypatch,
) -> None:
    module = _service_module()
    token = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    calls: list[int] = []

    def fixed_token_urlsafe(nbytes: int) -> str:
        calls.append(nbytes)
        return token

    monkeypatch.setattr(module.secrets, "token_urlsafe", fixed_token_urlsafe)
    generated = module.generate_approval_token()
    assert generated == token
    assert calls == [32]
    assert module.parse_approval_token(generated) == token
    assert len(base64.urlsafe_b64decode(generated + "=")) == 32
    assert module.approval_token_hash(generated).hex() == (
        "ea866a757e4c38babfa8127cbe9a409d3e1f93a00ff1488ff735fcf917afffd0"
    )


@pytest.mark.parametrize(
    "token",
    [
        "",
        "short",
        "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
        "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh+",
        "ＡＡＥＣＡｗＱＦＢｇｃＩＣＱｏＬＤＡ０ＯＤｘＡＲＥｈＭＵＦＲＹＸＧＢｋａＧｘｗｄＨｈ８",
    ],
)
def test_approval_token_parser_rejects_malformed_short_or_noncanonical_before_lookup(
    token: str,
) -> None:
    module = _service_module()
    with pytest.raises(module.SydneyClarificationError) as raised:
        module.parse_approval_token(token)
    assert str(raised.value) == "invalid_approval_nonce"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_handoff_link_places_only_opaque_secret_in_fragment() -> None:
    module = _service_module()
    suggestion_id = UUID("00000000-0000-4000-8000-000000000010")
    token = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    link = module.build_handoff_link(suggestion_id=suggestion_id, token=token)
    assert link == (
        "/admin/command/task-suggestions?"
        "suggestion=00000000-0000-4000-8000-000000000010"
        "#handoff=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    )
    query, fragment = link.split("#", 1)
    assert token not in query
    assert "handoff=" not in query
    assert fragment == f"handoff={token}"


def test_contact_resolution_hash_is_domain_separated_and_canonical() -> None:
    module = _service_module()
    expected = "8e79aac905cc876c77477164842b7f6da9aefb4ebdc0b65226559079407333a8"
    assert module.contact_resolution_hash(
        contact_id=42,
        email="Alice@Example.Test",
    ) == expected
    assert module.contact_resolution_hash(
        contact_id=42,
        email="alice@example.test",
    ) == expected
    assert expected == _contact_resolution_hash(42, "alice@example.test")
    with pytest.raises(module.SydneyClarificationError):
        module.contact_resolution_hash(contact_id=0, email="alice@example.test")


def test_contact_option_code_is_restart_safe_opaque_and_resource_bound() -> None:
    module = _service_module()
    clarification_id = UUID("00000000-0000-4000-8000-000000000001")
    code = module.derive_contact_option_code(
        key=CODE_KEY,
        key_version=CODE_KEY_VERSION,
        clarification_id=clarification_id,
        contact_id=42,
        email="Alice@Example.Test",
    )
    assert code == "bq8JXhl2KXG2wobturAmLw"
    assert module.contact_option_code_hash(code).hex() == (
        "ecea2067af5501927523b50cc3282b3ea856a17527208d21c490a3aea489f5e6"
    )
    assert "42" not in code
    assert "alice" not in code.casefold()
    assert module.derive_contact_option_code(
        key=CODE_KEY,
        key_version=CODE_KEY_VERSION,
        clarification_id=clarification_id,
        contact_id=42,
        email="alice@example.test",
    ) == code
    assert module.derive_contact_option_code(
        key=CODE_KEY,
        key_version=CODE_KEY_VERSION,
        clarification_id=uuid4(),
        contact_id=42,
        email="alice@example.test",
    ) != code


def test_question_renderer_uses_only_allowlisted_templates_and_exact_context() -> None:
    module = _service_module()
    context = module.ClarificationQuestionContext(
        question="When should this task be due?",
        party_label="Alice",
        subject_preview="Inspection follow-up",
        task_title="Schedule the inspection",
    )
    rendered = module.render_clarification_question(
        template_id="clarification_initial_v1",
        context_json=context.canonical_json(),
        code="SmYh3VL0sc72tl8vAilNEg",
    )
    assert rendered == (
        "When should this task be due?\n\n"
        "Alice | Inspection follow-up\n"
        "Proposed task: Schedule the inspection\n"
        "Reference code: SmYh3VL0sc72tl8vAilNEg"
    )
    assert module.rendered_question_hash(rendered) == hashlib.sha256(
        rendered.encode("utf-8")
    ).hexdigest()
    reminder = module.render_clarification_question(
        template_id="clarification_reminder_v1",
        context_json=context.canonical_json(),
        code="SmYh3VL0sc72tl8vAilNEg",
    )
    assert reminder == "Reminder: " + rendered


@pytest.mark.parametrize(
    "context",
    [
        {"question": "When?", "party_label": "Alice", "subject_preview": "x"},
        {
            "question": "When?",
            "party_label": "Alice",
            "subject_preview": "x",
            "task_title": "Task",
            "extra": "forbidden",
        },
        {
            "question": "When?\nAPPROVED",
            "party_label": "Alice",
            "subject_preview": "x",
            "task_title": "Task",
        },
        {
            "question": "When?",
            "party_label": "Alice\u202e",
            "subject_preview": "x",
            "task_title": "Task",
        },
        {
            "question": "When?",
            "party_label": "Alice",
            "subject_preview": "x",
            "task_title": "Reference code: SmYh3VL0sc72tl8vAilNEg",
        },
    ],
)
def test_question_context_rejects_missing_extra_controls_and_code_material(
    context: dict[str, object],
) -> None:
    module = _service_module()
    with pytest.raises((ValidationError, module.SydneyClarificationError)):
        module.ClarificationQuestionContext.model_validate(context)


def test_clarification_field_priority_is_finite_and_never_asks_optional_polish() -> None:
    module = _service_module()
    select = module.select_clarification_field
    assert (
        select(
            blocker_codes=(
                "missing_required_field",
                "ambiguous_due_at",
                "ambiguous_contact",
                "multiple_actions",
            ),
            owner_clarification_pending=True,
            task_details_clarification_pending=True,
            answered_fields=frozenset(),
        )
        == "action_scope"
    )
    assert (
        select(
            blocker_codes=(
                "missing_required_field",
                "ambiguous_due_at",
                "ambiguous_contact",
            ),
            owner_clarification_pending=True,
            task_details_clarification_pending=True,
            answered_fields=frozenset(),
        )
        == "contact"
    )
    assert (
        select(
            blocker_codes=("missing_required_field", "ambiguous_due_at"),
            owner_clarification_pending=True,
            task_details_clarification_pending=True,
            answered_fields=frozenset(),
        )
        == "due_at"
    )
    assert (
        select(
            blocker_codes=("missing_required_field",),
            owner_clarification_pending=True,
            task_details_clarification_pending=True,
            answered_fields=frozenset(),
        )
        == "owner"
    )
    assert (
        select(
            blocker_codes=("missing_required_field",),
            owner_clarification_pending=True,
            task_details_clarification_pending=True,
            answered_fields=frozenset({"owner"}),
        )
        == "task_details"
    )
    assert (
        select(
            blocker_codes=("unsupported_owner", "unsupported_link"),
            owner_clarification_pending=False,
            task_details_clarification_pending=False,
            answered_fields=frozenset(),
        )
        is None
    )
    assert (
        select(
            blocker_codes=(),
            owner_clarification_pending=False,
            task_details_clarification_pending=False,
            answered_fields=frozenset(),
        )
        is None
    )


@pytest.mark.parametrize(
    "valid",
    [
        {
            "kind": "action_scope",
            "decision": "single_task",
            "title": "Send the 123 Main disclosure",
            "description": "Send only the disclosure for 123 Main.",
            "priority": "high",
        },
        {"kind": "action_scope", "decision": "separate_tasks"},
        {
            "kind": "contact",
            "decision": "select_option",
            "option_code": "wV9FQwyxXx9v7Qn82YZzNQ",
        },
        {
            "kind": "contact",
            "decision": "exact_email",
            "email": "alice@example.test",
        },
        {"kind": "contact", "decision": "no_contact"},
        {
            "kind": "due_at",
            "decision": "set_due",
            "due_at": "2026-08-22T15:00:00-04:00",
            "timezone_basis": "America/New_York",
        },
        {"kind": "due_at", "decision": "no_due_date"},
        {"kind": "owner", "decision": "brandon"},
        {"kind": "owner", "decision": "other"},
        {
            "kind": "task_details",
            "decision": "replace",
            "title": "Pay the photographer invoice",
            "description": "Pay the invoice for the listing photos.",
            "priority": "normal",
        },
        {"kind": "task_details", "decision": "confirm_current"},
    ],
)
def test_finite_structured_answer_union_accepts_only_representable_draft_edits(
    valid: dict[str, object],
) -> None:
    module = _service_module()
    parsed = module.parse_clarification_answer(valid)
    assert parsed.kind == valid["kind"]


@pytest.mark.parametrize(
    "invalid",
    [
        {
            "kind": "action_scope",
            "decision": "single_task",
            "title": "Only title is not a full replacement",
            "priority": "normal",
        },
        {
            "kind": "action_scope",
            "decision": "separate_tasks",
            "title": "must not split",
        },
        {"kind": "contact", "decision": "select_option", "contact_id": 42},
        {
            "kind": "contact",
            "decision": "select_option",
            "choice_email": "alice@example.test",
        },
        {
            "kind": "contact",
            "decision": "exact_email",
            "email": "Alice Client",
        },
        {
            "kind": "contact",
            "decision": "no_contact",
            "option_code": "wV9FQwyxXx9v7Qn82YZzNQ",
        },
        {
            "kind": "due_at",
            "decision": "set_due",
            "due_at": "tomorrow",
            "timezone_basis": "America/New_York",
        },
        {
            "kind": "due_at",
            "decision": "set_due",
            "due_at": "2026-08-22T15:00:00",
            "timezone_basis": "America/New_York",
        },
        {
            "kind": "due_at",
            "decision": "set_due",
            "due_at": "2026-08-22T15:00:00-07:00",
            "timezone_basis": "America/New_York",
        },
        {"kind": "owner", "decision": "Pat"},
        {
            "kind": "task_details",
            "decision": "replace",
            "title": "Task",
            "description": "Details",
            "priority": "urgent",
        },
        {"kind": "due_at", "decision": "no_due_date", "chat_id": CHAT_ID},
        {"kind": "owner", "decision": "brandon", "suggestion_id": str(uuid4())},
        {"kind": "task_details", "decision": "confirm_current", "apply": True},
        {
            "kind": "action_scope",
            "decision": "single_task",
            "title": "Task",
            "description": "Details",
            "priority": "normal",
            "due_at": "2026-08-22T15:00:00-04:00",
        },
        {"kind": "owner", "decision": True},
    ],
)
def test_finite_structured_answer_union_rejects_coercion_authority_and_extra_fields(
    invalid: dict[str, object],
) -> None:
    module = _service_module()
    with pytest.raises(module.SydneyClarificationError) as raised:
        module.parse_clarification_answer(invalid)
    assert str(raised.value) == "invalid_clarification_answer"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_answer_text_is_bounded_control_safe_and_nfkc_normalized() -> None:
    module = _service_module()
    parsed = module.parse_clarification_answer(
        {
            "kind": "task_details",
            "decision": "replace",
            "title": "  Ｐａｙ the invoice  ",
            "description": "Line one\r\nLine two\u2028Line three\u2029Line four",
            "priority": "normal",
        }
    )
    assert parsed.title == "Pay the invoice"
    assert parsed.description == "Line one\nLine two\nLine three\nLine four"

    unsafe_single_line = ("\n", "\t", "\u202e", "\u2066", "\ud800", "\u2028", "\u2029")
    for unsafe in unsafe_single_line:
        with pytest.raises(module.SydneyClarificationError):
            module.parse_clarification_answer(
                {
                    "kind": "task_details",
                    "decision": "replace",
                    "title": f"Pay{unsafe}invoice",
                    "description": "Safe",
                    "priority": "normal",
                }
            )
    for unsafe in ("\t", "\u202e", "\u2066", "\ud800"):
        with pytest.raises(module.SydneyClarificationError):
            module.parse_clarification_answer(
                {
                    "kind": "task_details",
                    "decision": "replace",
                    "title": "Pay invoice",
                    "description": f"Unsafe{unsafe}description",
                    "priority": "normal",
                }
            )
    for title, description in (
        ("", "Safe"),
        ("x" * 256, "Safe"),
        ("Safe", "x" * 5001),
    ):
        with pytest.raises(module.SydneyClarificationError):
            module.parse_clarification_answer(
                {
                    "kind": "action_scope",
                    "decision": "single_task",
                    "title": title,
                    "description": description,
                    "priority": "normal",
                }
            )


async def test_enqueue_persists_hash_only_code_and_immutable_initial_outbox(
    clarification_runtime,
) -> None:
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
    )
    now = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
    result = await _service(sessions).enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Inspection follow-up",
        now=now,
    )
    assert result.created is True
    assert result.field_name == "due_at"
    assert not hasattr(result, "code")

    async with sessions() as session:
        clarification = await session.get(CRMTaskClarification, result.clarification_id)
        attempt = await session.get(SydneyQuestionOutbox, result.outbox_id)
    assert clarification is not None
    assert clarification.code_key_version == CODE_KEY_VERSION
    assert len(clarification.code_hash) == 32
    assert clarification.slot_deadline_at == now + timedelta(hours=48)
    assert attempt is not None
    assert attempt.dedupe_key == (
        f"clarification:{clarification.id}:v1:initial:1"
    )
    assert attempt.template_id == "clarification_initial_v1"
    assert attempt.state == "pending"
    assert attempt.rendered_payload_hash
    canonical_code = _service_module().derive_clarification_code(
        key=CODE_KEY,
        key_version=CODE_KEY_VERSION,
        clarification_id=clarification.id,
        suggestion_id=suggestion.id,
        suggestion_version=1,
        field_name="due_at",
        round_number=1,
    )
    assert canonical_code not in attempt.question_context_json
    assert canonical_code not in attempt.template_id
    assert canonical_code not in repr(clarification)
    assert canonical_code not in repr(attempt)


async def test_dispatcher_persists_success_and_enqueues_one_due_reminder(
    clarification_runtime,
) -> None:
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox
    from services.sydney_telegram_dispatcher import TelegramHTTPResponse

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
    )
    created_at = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
    queued = await _service(sessions).enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Inspection follow-up",
        now=created_at,
    )
    clock = _MutableClock(created_at + timedelta(minutes=1))
    sent_payloads: list[dict[str, object]] = []

    def send_message(**kwargs):
        sent_payloads.append(kwargs["payload"])
        return TelegramHTTPResponse(
            status_code=200,
            payload={
                "ok": True,
                "result": {
                    "message_id": 9001,
                    "chat": {"id": int(CHAT_ID)},
                },
            },
        )

    executor = _ObservingExecutor(sessions)
    dispatcher = _dispatcher(
        sessions,
        clock=clock,
        send_message=send_message,
        executor=executor,
    )
    correlation = await dispatcher.dispatch_attempt(queued.outbox_id)
    assert correlation.chat_id == CHAT_ID
    assert correlation.message_id == "9001"
    assert sent_payloads[0]["chat_id"] == CHAT_ID
    assert executor.observed_states == ["sending"]

    clock.now += timedelta(hours=24)
    reminder_id = await dispatcher.enqueue_due_reminder(
        queued.clarification_id
    )
    replay_id = await dispatcher.enqueue_due_reminder(
        queued.clarification_id
    )
    assert replay_id == reminder_id

    async with sessions() as session:
        clarification = await session.get(
            CRMTaskClarification, queued.clarification_id
        )
        attempts = list(
            (
                await session.scalars(
                    sa.select(SydneyQuestionOutbox)
                    .where(
                        SydneyQuestionOutbox.clarification_id
                        == queued.clarification_id
                    )
                    .order_by(SydneyQuestionOutbox.created_at)
                )
            ).all()
        )
    assert clarification.deadline_anchor_kind == "initial_sent"
    assert clarification.deadline_anchored_at == created_at + timedelta(minutes=1)
    assert clarification.slot_deadline_at == created_at + timedelta(
        hours=48, minutes=1
    )
    assert [attempt.attempt_kind for attempt in attempts] == [
        "initial",
        "reminder",
    ]
    assert [attempt.state for attempt in attempts] == ["sent", "pending"]


@pytest.mark.parametrize(
    ("delivery_path", "attempt_state", "failure_category"),
    [
        ("pending", "failed", "pre_send_expired"),
        ("provider_rejected", "failed", "provider_rejected"),
        ("provider_uncertain", "delivery_uncertain", "provider_unknown"),
    ],
)
async def test_pending_failed_and_uncertain_initials_release_at_fixed_deadline(
    clarification_runtime,
    delivery_path: str,
    attempt_state: str,
    failure_category: str,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox
    from services.sydney_telegram_dispatcher import (
        TelegramDispatchError,
        TelegramHTTPResponse,
    )

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
    )
    created_at = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)
    queued = await _service(sessions).enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Delivery failure",
        now=created_at,
    )
    dispatch_at = created_at + timedelta(minutes=1)
    clock = _MutableClock(dispatch_at)
    calls = 0

    def send_message(**_kwargs):
        nonlocal calls
        calls += 1
        if delivery_path == "provider_rejected":
            return TelegramHTTPResponse(
                status_code=400,
                payload={"ok": False, "error_code": 400},
            )
        return TelegramHTTPResponse(
            status_code=200,
            payload={"ok": True, "result": {}},
        )

    dispatcher = _dispatcher(
        sessions,
        clock=clock,
        send_message=send_message,
        executor=_ObservingExecutor(sessions),
    )
    if delivery_path != "pending":
        with pytest.raises(TelegramDispatchError):
            await dispatcher.dispatch_attempt(queued.outbox_id)
        with pytest.raises(TelegramDispatchError):
            await dispatcher.dispatch_attempt(queued.outbox_id)
        assert calls == 1

    async with sessions() as session:
        clarification = await session.get(
            CRMTaskClarification, queued.clarification_id
        )
    expected_anchor = created_at if delivery_path == "pending" else dispatch_at
    assert clarification.deadline_anchored_at == expected_anchor
    assert clarification.slot_deadline_at == expected_anchor + timedelta(hours=48)

    clock.now = clarification.slot_deadline_at
    assert await dispatcher.release_expired_clarification(
        queued.clarification_id
    )
    assert not await dispatcher.release_expired_clarification(
        queued.clarification_id
    )

    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion.id)
        clarification = await session.get(
            CRMTaskClarification, queued.clarification_id
        )
        attempts = list(
            (
                await session.scalars(
                    sa.select(SydneyQuestionOutbox).where(
                        SydneyQuestionOutbox.clarification_id
                        == queued.clarification_id
                    )
                )
            ).all()
        )
    assert stored.state == "needs_clarification"
    assert stored.clarification_state == "timed_out"
    assert clarification.state == "timed_out"
    assert len(attempts) == 1
    assert attempts[0].state == attempt_state
    assert attempts[0].failure_category == failure_category


async def test_reconciled_initial_retry_and_reminder_never_extend_deadline(
    clarification_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.sydney_tasks import (
        CRMTaskClarification,
        CRMTaskSuggestionEvent,
        SydneyQuestionOutbox,
    )
    from services.sydney_telegram_dispatcher import (
        TelegramDeliveryUncertain,
        TelegramDispatchError,
        TelegramHTTPResponse,
    )

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
    )
    created_at = datetime(2026, 8, 21, 16, 0, tzinfo=UTC)
    queued = await _service(sessions).enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Retry lifecycle",
        now=created_at,
    )
    async with sessions() as session:
        audit = AgentActionAudit(
            actor="admin",
            action_id=f"telegram-reconcile-{uuid4()}",
            method="POST",
            path="/test/clarifications/reconcile",
            status_code=200,
            allowed=True,
            request_meta_json="{}",
            response_meta_json="{}",
        )
        session.add(audit)
        await session.commit()
        await session.refresh(audit)
    clock = _MutableClock(created_at + timedelta(minutes=1))
    sent_payloads: list[dict[str, object]] = []

    def send_message(**kwargs):
        sent_payloads.append(kwargs["payload"])
        if len(sent_payloads) == 1:
            return TelegramHTTPResponse(
                status_code=200,
                payload={"ok": True, "result": {}},
            )
        return TelegramHTTPResponse(
            status_code=200,
            payload={
                "ok": True,
                "result": {
                    "message_id": 9000 + len(sent_payloads),
                    "chat": {"id": int(CHAT_ID)},
                },
            },
        )

    dispatcher = _dispatcher(
        sessions,
        clock=clock,
        send_message=send_message,
        executor=_ObservingExecutor(sessions),
    )
    with pytest.raises(TelegramDeliveryUncertain):
        await dispatcher.dispatch_attempt(queued.outbox_id)
    fixed_deadline = clock.now + timedelta(hours=48)
    assert await dispatcher.reconcile_attempt(
        queued.outbox_id,
        "delivery_uncertain",
        "not_delivered",
        "Operator verified no message was created.",
        audit.id,
        None,
        None,
    )
    retry_id = await dispatcher.create_initial_retry(
        queued.outbox_id,
        "Retry approved after verification.",
        audit.id,
    )
    with pytest.raises(TelegramDispatchError) as raised:
        await dispatcher.create_initial_retry(
            queued.outbox_id,
            "A duplicate retry must not be created.",
            audit.id,
        )
    assert str(raised.value) == "telegram_retry_stale"

    clock.now += timedelta(hours=1)
    retry_correlation = await dispatcher.dispatch_attempt(retry_id)
    assert retry_correlation.message_id == "9002"
    clock.now += timedelta(hours=24)
    reminder_id = await dispatcher.enqueue_due_reminder(
        queued.clarification_id
    )
    reminder_correlation = await dispatcher.dispatch_attempt(reminder_id)
    assert reminder_correlation.message_id == "9003"
    assert sent_payloads[-1]["reply_parameters"] == {"message_id": 9002}

    async with sessions() as session:
        clarification = await session.get(
            CRMTaskClarification, queued.clarification_id
        )
        attempts = list(
            (
                await session.scalars(
                    sa.select(SydneyQuestionOutbox)
                    .where(
                        SydneyQuestionOutbox.clarification_id
                        == queued.clarification_id
                    )
                    .order_by(SydneyQuestionOutbox.created_at)
                )
            ).all()
        )
        retry_event = await session.scalar(
            sa.select(CRMTaskSuggestionEvent).where(
                CRMTaskSuggestionEvent.event_type
                == "clarification_delivery_retry"
            )
        )
    assert clarification.deadline_anchor_kind == "first_attempt"
    assert clarification.slot_deadline_at == fixed_deadline
    assert [attempt.attempt_kind for attempt in attempts] == [
        "initial",
        "initial_retry",
        "reminder",
    ]
    assert [attempt.state for attempt in attempts] == [
        "delivery_uncertain",
        "sent",
        "sent",
    ]
    assert attempts[1].parent_initial_attempt_id == queued.outbox_id
    assert attempts[2].reply_to_attempt_id == retry_id
    assert retry_event is not None
    assert retry_event.action_audit_id == audit.id
    retry_event_data = json.loads(retry_event.event_data_json)
    assert retry_event_data["attempt_id"] == str(retry_id)
    assert retry_event_data["parent_attempt_id"] == str(queued.outbox_id)
    assert retry_event_data["reason_sha256"] == hashlib.sha256(
        b"Retry approved after verification."
    ).hexdigest()


async def test_reconciled_delivered_initial_can_receive_one_due_reminder(
    clarification_runtime,
) -> None:
    from models.agent_action_audit import AgentActionAudit
    from models.sydney_tasks import SydneyQuestionOutbox
    from services.sydney_telegram_dispatcher import (
        TelegramDeliveryUncertain,
        TelegramHTTPResponse,
    )

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
    )
    created_at = datetime(2026, 8, 21, 16, 0, tzinfo=UTC)
    queued = await _service(sessions).enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Reconciled delivery",
        now=created_at,
    )
    async with sessions() as session:
        audit = AgentActionAudit(
            actor="admin",
            action_id=f"telegram-reconcile-{uuid4()}",
            method="POST",
            path="/test/clarifications/reconcile-delivered",
            status_code=200,
            allowed=True,
            request_meta_json="{}",
            response_meta_json="{}",
        )
        session.add(audit)
        await session.commit()
        await session.refresh(audit)
    clock = _MutableClock(created_at + timedelta(minutes=1))

    def uncertain_send(**_kwargs):
        return TelegramHTTPResponse(
            status_code=200,
            payload={"ok": True, "result": {}},
        )

    dispatcher = _dispatcher(
        sessions,
        clock=clock,
        send_message=uncertain_send,
    )
    with pytest.raises(TelegramDeliveryUncertain):
        await dispatcher.dispatch_attempt(queued.outbox_id)
    assert await dispatcher.reconcile_attempt(
        queued.outbox_id,
        "delivery_uncertain",
        "delivered",
        "Operator verified the Telegram message.",
        audit.id,
        CHAT_ID,
        9010,
    )
    clock.now += timedelta(hours=24)
    reminder_id = await dispatcher.enqueue_due_reminder(
        queued.clarification_id
    )
    assert reminder_id is not None
    assert await dispatcher.enqueue_due_reminder(
        queued.clarification_id
    ) == reminder_id
    async with sessions() as session:
        reminder = await session.get(SydneyQuestionOutbox, reminder_id)
    assert reminder is not None
    assert reminder.reply_to_attempt_id == queued.outbox_id


async def test_one_pending_clarification_owns_the_chat_slot_without_repeating(
    clarification_runtime,
) -> None:
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox

    _engine, sessions = clarification_runtime
    first = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
        title="First task",
    )
    second = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_contact"],
        title="Second task",
    )
    now = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)
    service = _service(sessions)
    created = await service.enqueue_next(
        suggestion_id=first.id,
        party_label="Alice",
        subject_preview="First",
        now=now,
    )
    replay = await service.enqueue_next(
        suggestion_id=first.id,
        party_label="Alice",
        subject_preview="First",
        now=now,
    )
    busy = await service.enqueue_next(
        suggestion_id=second.id,
        party_label="Bob",
        subject_preview="Second",
        now=now,
    )
    assert replay.created is False
    assert replay.clarification_id == created.clarification_id
    assert busy.created is False
    assert busy.reason == "clarification_chat_busy"
    async with sessions() as session:
        counts = (
            await session.scalar(sa.select(sa.func.count(CRMTaskClarification.id))),
            await session.scalar(sa.select(sa.func.count(SydneyQuestionOutbox.id))),
        )
    assert counts == (1, 1)


async def test_five_distinct_causes_resolve_in_priority_order_across_restarts(
    clarification_runtime,
    monkeypatch,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import (
        CRMTaskClarification,
        CRMTaskSuggestionEvent,
        SydneyQuestionOutbox,
        TaskSuggestionApprovalNonce,
    )

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=[
            "missing_required_field",
            "ambiguous_due_at",
            "ambiguous_contact",
            "multiple_actions",
        ],
        owner_clarification_pending=True,
        task_details_clarification_pending=True,
        contact_resolution_state="unresolved",
        title="Two follow-ups",
        description="The scope is ambiguous.",
    )
    now = datetime(2026, 8, 21, 15, 30, tzinfo=UTC)
    token = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    monkeypatch.setattr(
        _service_module().secrets,
        "token_urlsafe",
        lambda nbytes: token if nbytes == 32 else "invalid",
    )
    first = await _service(sessions).enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Several details",
        now=now,
    )
    clarification_id = first.clarification_id
    answers = (
        {
            "kind": "action_scope",
            "decision": "single_task",
            "title": "Send one disclosure",
            "description": "Send the disclosure for 123 Main.",
            "priority": "high",
        },
        {"kind": "contact", "decision": "no_contact"},
        {"kind": "due_at", "decision": "no_due_date"},
        {"kind": "owner", "decision": "brandon"},
        {"kind": "task_details", "decision": "confirm_current"},
    )
    expected_fields = (
        "action_scope",
        "contact",
        "due_at",
        "owner",
        "task_details",
    )
    final_result = None
    for index, (expected_field, answer) in enumerate(
        zip(expected_fields, answers, strict=True),
        start=1,
    ):
        async with sessions() as session:
            row = await session.get(CRMTaskClarification, clarification_id)
        assert row is not None
        assert row.field_name == expected_field
        assert row.round_number == index
        assert row.suggestion_version == index
        await _set_initial_delivery(
            sessions,
            clarification_id=clarification_id,
            state="sent",
            now=now + timedelta(minutes=index),
        )
        restarted = _service(sessions)
        result = await restarted.answer(
            code=await _clarification_code(sessions, clarification_id),
            expected_suggestion_version=index,
            answer=answer,
            now=now + timedelta(minutes=index, seconds=30),
        )
        assert result.suggestion_version == index + 1
        if index < 5:
            assert result.handoff_link is None
            assert result.next_clarification_id is not None
            clarification_id = result.next_clarification_id
        else:
            final_result = result

    assert final_result is not None
    assert final_result.next_clarification_id is None
    assert final_result.handoff_link == (
        f"/admin/command/task-suggestions?suggestion={suggestion.id}"
        f"#handoff={token}"
    )
    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion.id)
        clarifications = list(
            (
                await session.scalars(
                    sa.select(CRMTaskClarification)
                    .where(CRMTaskClarification.suggestion_id == suggestion.id)
                    .order_by(CRMTaskClarification.round_number)
                )
            ).all()
        )
        outbox_count = await session.scalar(
            sa.select(sa.func.count(SydneyQuestionOutbox.id)).join(
                CRMTaskClarification,
                CRMTaskClarification.id == SydneyQuestionOutbox.clarification_id,
            ).where(CRMTaskClarification.suggestion_id == suggestion.id)
        )
        events = list(
            (
                await session.scalars(
                    sa.select(CRMTaskSuggestionEvent)
                    .where(CRMTaskSuggestionEvent.suggestion_id == suggestion.id)
                    .order_by(
                        CRMTaskSuggestionEvent.created_at,
                        CRMTaskSuggestionEvent.id,
                    )
                )
            ).all()
        )
        nonces = list(
            (
                await session.scalars(
                    sa.select(TaskSuggestionApprovalNonce).where(
                        TaskSuggestionApprovalNonce.suggestion_id == suggestion.id
                    )
                )
            ).all()
        )
    assert stored.version == 6
    assert stored.title == "Send one disclosure"
    assert stored.description == "Send the disclosure for 123 Main."
    assert stored.priority == "high"
    assert stored.due_at is None
    assert stored.contact_id is None
    assert stored.contact_resolution_state == "explicit_none"
    assert stored.contact_resolution_hash is None
    assert stored.owner_clarification_pending is False
    assert stored.task_details_clarification_pending is False
    assert stored.blocker_codes == []
    assert stored.state == "pending_review"
    assert stored.clarification_state == "not_required"
    assert [row.field_name for row in clarifications] == list(expected_fields)
    assert [row.state for row in clarifications] == ["answered"] * 5
    assert outbox_count == 5
    assert [event.event_type for event in events].count("clarification_asked") == 5
    assert [event.event_type for event in events].count("clarification_answered") == 5
    assert [event.event_type for event in events].count("preview") == 1
    assert len(nonces) == 1
    assert all(value == 0 for value in (await _task_side_effect_counts(sessions)).values())


async def test_valid_due_answer_locks_suggestion_then_clarification_and_versions_draft(
    clarification_runtime,
    monkeypatch,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.command import CRMTask
    from models.sydney_tasks import (
        CRMTaskClarification,
        CRMTaskSuggestionEvent,
        SydneyQuestionOutbox,
        TaskSuggestionApprovalNonce,
    )
    from services.crm_task_suggestion_service import canonical_task_payload_hash

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
    )
    original_payload_hash = suggestion.payload_hash
    now = datetime(2026, 8, 21, 16, 0, tzinfo=UTC)
    service = _service(sessions)
    token = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    token_calls: list[int] = []

    def fixed_token_urlsafe(nbytes: int) -> str:
        token_calls.append(nbytes)
        return token

    monkeypatch.setattr(
        _service_module().secrets,
        "token_urlsafe",
        fixed_token_urlsafe,
    )
    queued = await service.enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Due date",
        now=now,
    )
    await _set_initial_delivery(
        sessions,
        clarification_id=queued.clarification_id,
        state="sent",
        now=now + timedelta(minutes=1),
    )
    code = await _clarification_code(sessions, queued.clarification_id)
    async with sessions() as session:
        initial = await session.scalar(
            sa.select(SydneyQuestionOutbox).where(
                SydneyQuestionOutbox.clarification_id == queued.clarification_id,
                SydneyQuestionOutbox.attempt_kind == "initial",
            )
        )
        assert initial is not None
        rendered = _service_module().render_clarification_question(
            template_id="clarification_reminder_v1",
            context_json=initial.question_context_json,
            code=code,
        )
        session.add(
            SydneyQuestionOutbox(
                clarification_id=queued.clarification_id,
                attempt_kind="reminder",
                attempt_number=1,
                reply_to_attempt_id=initial.id,
                dedupe_key=(
                    f"clarification:{queued.clarification_id}:v1:reminder:1"
                ),
                template_id="clarification_reminder_v1",
                question_context_json=initial.question_context_json,
                rendered_payload_hash=_service_module().rendered_question_hash(
                    rendered
                ),
            )
        )
        await session.commit()
    result = await service.answer(
        code=code,
        expected_suggestion_version=1,
        answer={
            "kind": "due_at",
            "decision": "set_due",
            "due_at": "2026-08-25T15:00:00-04:00",
            "timezone_basis": "America/New_York",
        },
        now=now + timedelta(hours=25),
    )
    assert result.suggestion_id == suggestion.id
    assert result.suggestion_version == 2
    assert result.handoff_link == (
        f"/admin/command/task-suggestions?suggestion={suggestion.id}"
        f"#handoff={token}"
    )
    assert token_calls == [32]

    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion.id)
        clarification = await session.get(
            CRMTaskClarification, queued.clarification_id
        )
        events = list(
            (
                await session.scalars(
                    sa.select(CRMTaskSuggestionEvent).order_by(
                        CRMTaskSuggestionEvent.created_at,
                        CRMTaskSuggestionEvent.id,
                    )
                )
            ).all()
        )
        nonce = await session.scalar(sa.select(TaskSuggestionApprovalNonce))
        reminder = await session.scalar(
            sa.select(SydneyQuestionOutbox).where(
                SydneyQuestionOutbox.clarification_id == queued.clarification_id,
                SydneyQuestionOutbox.attempt_kind == "reminder",
            )
        )
        task_count = await session.scalar(sa.select(sa.func.count(CRMTask.id)))
    assert stored.version == 2
    assert stored.due_at == datetime(2026, 8, 25, 19, 0, tzinfo=UTC)
    assert stored.blocker_codes == []
    assert stored.state == "pending_review"
    assert stored.clarification_state == "not_required"
    assert stored.payload_hash == canonical_task_payload_hash(
        title=stored.title,
        description=stored.description,
        priority=stored.priority,
        due_at=stored.due_at,
        contact_id=stored.contact_id,
        status=stored.task_status,
    )
    assert clarification.state == "answered"
    assert clarification.resolved_at == now + timedelta(hours=25)
    assert reminder.state == "failed"
    assert reminder.failure_category == "pre_send_resolved"
    assert reminder.attempted_at is None
    assert [event.event_type for event in events] == [
        "clarification_asked",
        "clarification_answered",
        "preview",
    ]
    assert events[1].actor_type == "untrusted_hermes_input"
    assert events[2].actor_type == "sydney"
    answered_event = json.loads(events[1].event_data_json)
    assert answered_event == {
        "clarification_id": str(queued.clarification_id),
        "field_name": "due_at",
        "new_blocker_codes": [],
        "new_payload_hash": stored.payload_hash,
        "new_version": 2,
        "old_blocker_codes": ["ambiguous_due_at"],
        "old_payload_hash": original_payload_hash,
        "old_version": 1,
    }
    preview_event = json.loads(events[2].event_data_json)
    assert preview_event == {
        "handoff_nonce_id": str(nonce.id),
        "payload_hash": stored.payload_hash,
        "suggestion_version": 2,
    }
    serialized_events = "\n".join(event.event_data_json for event in events)
    assert code not in serialized_events
    assert token not in serialized_events
    assert nonce.kind == "handoff"
    assert nonce.issuance_path == "approval_link"
    assert nonce.suggestion_id == suggestion.id
    assert nonce.suggestion_version == 2
    assert nonce.payload_hash == stored.payload_hash
    assert nonce.token_hash == hashlib.sha256(token.encode("ascii")).digest()
    assert nonce.administrator_id is None
    assert nonce.parent_nonce_id is None
    assert nonce.expires_at - nonce.issued_at == timedelta(minutes=15)
    assert nonce.consumed_at is None
    assert token not in repr(nonce)
    assert task_count == 0
    assert await _task_side_effect_counts(sessions) == {
        "crm_tasks": 0,
        "crm_activities": 0,
        "crm_task_links": 0,
        "crm_task_creation_requests": 0,
        "crm_task_sources": 0,
        "crm_record_lifecycle_events": 0,
        "crm_task_suggestion_sources": 0,
    }


async def test_action_scope_separate_tasks_stays_manual_and_never_creates_a_task(
    clarification_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskSuggestionEvent, TaskSuggestionApprovalNonce

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["multiple_actions"],
    )
    now = datetime(2026, 8, 21, 17, 0, tzinfo=UTC)
    service = _service(sessions)
    queued = await service.enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Two follow-ups",
        now=now,
    )
    await _set_initial_delivery(
        sessions,
        clarification_id=queued.clarification_id,
        state="sent",
        now=now + timedelta(seconds=10),
    )
    await service.answer(
        code=await _clarification_code(sessions, queued.clarification_id),
        expected_suggestion_version=1,
        answer={"kind": "action_scope", "decision": "separate_tasks"},
        now=now + timedelta(minutes=1),
    )
    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion.id)
        nonce_count = await session.scalar(
            sa.select(sa.func.count(TaskSuggestionApprovalNonce.id))
        )
        preview_count = await session.scalar(
            sa.select(sa.func.count(CRMTaskSuggestionEvent.id)).where(
                CRMTaskSuggestionEvent.event_type == "preview"
            )
        )
    assert stored.version == 2
    assert stored.blocker_codes == ["multiple_actions"]
    assert stored.state == "needs_clarification"
    assert stored.clarification_state == "manual_review_required"
    assert nonce_count == 0
    assert preview_count == 0
    assert all(value == 0 for value in (await _task_side_effect_counts(sessions)).values())


async def test_fifth_answer_with_remaining_ambiguity_creates_no_sixth_round(
    clarification_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at", "ambiguous_contact"],
        version=5,
    )
    now = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)
    async with sessions() as session:
        for round_number in range(1, 5):
            session.add(
                CRMTaskClarification(
                    suggestion_id=suggestion.id,
                    suggestion_version=round_number,
                    field_name="task_details" if round_number % 2 else "owner",
                    round_number=round_number,
                    telegram_chat_id=CHAT_ID,
                    code_hash=bytes([round_number]) * 32,
                    code_key_version=CODE_KEY_VERSION,
                    options_json="{}",
                    state="answered",
                    answer_json='{"kind":"task_details"}',
                    deadline_anchor_kind="created",
                    deadline_anchored_at=now - timedelta(days=round_number),
                    slot_deadline_at=(
                        now - timedelta(days=round_number) + timedelta(hours=48)
                    ),
                    resolved_at=now,
                    created_at=now - timedelta(days=round_number),
                    updated_at=now,
                )
            )
        await session.commit()
    service = _service(sessions)
    queued = await service.enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Round five",
        now=now,
    )
    assert queued.round_number == 5
    assert queued.field_name == "contact"
    await _set_initial_delivery(
        sessions,
        clarification_id=queued.clarification_id,
        state="sent",
        now=now + timedelta(seconds=10),
    )
    await service.answer(
        code=await _clarification_code(sessions, queued.clarification_id),
        expected_suggestion_version=5,
        answer={"kind": "contact", "decision": "no_contact"},
        now=now + timedelta(minutes=1),
    )
    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion.id)
        counts = (
            await session.scalar(
                sa.select(sa.func.count(CRMTaskClarification.id)).where(
                    CRMTaskClarification.suggestion_id == suggestion.id
                )
            ),
            await session.scalar(
                sa.select(sa.func.count(SydneyQuestionOutbox.id)).join(
                    CRMTaskClarification,
                    CRMTaskClarification.id == SydneyQuestionOutbox.clarification_id,
                ).where(CRMTaskClarification.suggestion_id == suggestion.id)
            ),
            await session.scalar(
                sa.text(
                    "SELECT count(*) FROM crm_task_suggestion_approval_nonces "
                    "WHERE suggestion_id = :suggestion_id"
                ),
                {"suggestion_id": suggestion.id},
            ),
        )
    assert stored.version == 6
    assert stored.clarification_state == "manual_review_required"
    assert stored.contact_resolution_state == "explicit_none"
    assert stored.blocker_codes == ["ambiguous_due_at"]
    assert counts == (5, 1, 0)
    assert all(value == 0 for value in (await _task_side_effect_counts(sessions)).values())


async def test_contact_answer_locks_identity_before_unique_lookup(
    clarification_runtime,
) -> None:
    from models.command import CRMContact

    engine, sessions = clarification_runtime
    async with sessions() as session:
        session.add(
            CRMContact(
                first_name="Alice",
                last_name="Client",
                email="alice-answer-lock@example.test",
                phone=None,
                stage="lead",
            )
        )
        await session.commit()
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_contact"],
    )
    now = datetime(2026, 8, 21, 18, 30, tzinfo=UTC)
    service = _service(sessions)
    queued = await service.enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Contact authority",
        now=now,
    )
    await _set_initial_delivery(
        sessions,
        clarification_id=queued.clarification_id,
        state="sent",
        now=now + timedelta(seconds=1),
    )
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.casefold().split()))

    sa.event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        await service.answer(
            code=await _clarification_code(sessions, queued.clarification_id),
            expected_suggestion_version=1,
            answer={
                "kind": "contact",
                "decision": "exact_email",
                "email": "alice-answer-lock@example.test",
            },
            now=now + timedelta(minutes=1),
        )
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", capture)
    identity_lock_positions = [
        index
        for index, statement in enumerate(statements)
        if "pg_advisory_xact_lock" in statement
    ]
    contact_lookup_positions = [
        index
        for index, statement in enumerate(statements)
        if "from crm_contacts" in statement and "for update" in statement
    ]
    assert identity_lock_positions
    assert contact_lookup_positions
    assert min(identity_lock_positions) < min(contact_lookup_positions)


async def test_enqueue_after_round_limit_marks_manual_review_without_sixth_row(
    clarification_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
        version=6,
    )
    now = datetime(2026, 8, 21, 18, 30, tzinfo=UTC)
    async with sessions() as session:
        for round_number in range(1, 6):
            session.add(
                CRMTaskClarification(
                    suggestion_id=suggestion.id,
                    suggestion_version=round_number,
                    field_name="due_at",
                    round_number=round_number,
                    telegram_chat_id=CHAT_ID,
                    code_hash=bytes([round_number]) * 32,
                    code_key_version=CODE_KEY_VERSION,
                    options_json="{}",
                    state="answered",
                    answer_json='{"decision":"no_due_date","kind":"due_at"}',
                    deadline_anchor_kind="created",
                    deadline_anchored_at=now - timedelta(days=round_number),
                    slot_deadline_at=(
                        now - timedelta(days=round_number) + timedelta(hours=48)
                    ),
                    resolved_at=now,
                    created_at=now - timedelta(days=round_number),
                    updated_at=now,
                )
            )
        await session.commit()
    queued = await _service(sessions).enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Reintroduced due ambiguity",
        now=now,
    )
    assert queued.created is False
    assert queued.reason == "clarification_round_limit"
    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion.id)
        count = await session.scalar(
            sa.select(sa.func.count(CRMTaskClarification.id)).where(
                CRMTaskClarification.suggestion_id == suggestion.id
            )
        )
    assert stored.clarification_state == "manual_review_required"
    assert count == 5


async def test_independent_version_change_supersedes_and_releases_chat_slot(
    clarification_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox
    from services.crm_task_suggestion_service import canonical_task_payload_hash

    _engine, sessions = clarification_runtime
    first = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
        title="First task",
    )
    second = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_contact"],
        title="Second task",
    )
    now = datetime(2026, 8, 21, 19, 0, tzinfo=UTC)
    service = _service(sessions)
    first_queue = await service.enqueue_next(
        suggestion_id=first.id,
        party_label="Alice",
        subject_preview="First",
        now=now,
    )
    async with sessions() as session:
        stored = await session.scalar(
            sa.select(CRMTaskSuggestion)
            .where(CRMTaskSuggestion.id == first.id)
            .with_for_update()
        )
        assert stored is not None
        previous_version = stored.version
        stored.priority = "high"
        stored.version += 1
        stored.payload_hash = canonical_task_payload_hash(
            title=stored.title,
            description=stored.description,
            priority=stored.priority,
            due_at=stored.due_at,
            contact_id=stored.contact_id,
            status=stored.task_status,
        )
        superseded = await service.supersede_for_locked_suggestion(
            session=session,
            suggestion=stored,
            previous_version=previous_version,
            now=now + timedelta(minutes=1),
        )
        await session.commit()
    assert superseded is True
    second_queue = await service.enqueue_next(
        suggestion_id=second.id,
        party_label="Bob",
        subject_preview="Second",
        now=now + timedelta(minutes=2),
    )
    assert second_queue.created is True
    async with sessions() as session:
        first_row = await session.get(
            CRMTaskClarification, first_queue.clarification_id
        )
        first_attempt = await session.scalar(
            sa.select(SydneyQuestionOutbox).where(
                SydneyQuestionOutbox.clarification_id == first_queue.clarification_id
            )
        )
    assert first_row.state == "superseded"
    assert first_row.resolved_at == now + timedelta(minutes=1)
    assert first_attempt.state == "failed"
    assert first_attempt.failure_category == "pre_send_superseded"
    assert first_attempt.attempted_at is None


async def test_dispatcher_rejects_pending_question_for_stale_suggestion_version(
    clarification_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import SydneyQuestionOutbox
    from services.crm_task_suggestion_service import canonical_task_payload_hash
    from services.sydney_telegram_dispatcher import TelegramDispatchError

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
    )
    now = datetime(2026, 8, 21, 19, 30, tzinfo=UTC)
    queued = await _service(sessions).enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Stale dispatch",
        now=now,
    )
    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion.id)
        stored.priority = "high"
        stored.version += 1
        stored.payload_hash = canonical_task_payload_hash(
            title=stored.title,
            description=stored.description,
            priority=stored.priority,
            due_at=stored.due_at,
            contact_id=stored.contact_id,
            status=stored.task_status,
        )
        await session.commit()
    send_calls = 0

    def send_message(**_kwargs):
        nonlocal send_calls
        send_calls += 1
        raise AssertionError("stale question crossed the provider boundary")

    dispatcher = _dispatcher(
        sessions,
        clock=_MutableClock(now + timedelta(minutes=1)),
        send_message=send_message,
    )
    with pytest.raises(TelegramDispatchError) as raised:
        await dispatcher.dispatch_attempt(queued.outbox_id)
    assert str(raised.value) == "telegram_attempt_stale"
    assert send_calls == 0
    async with sessions() as session:
        attempt = await session.get(SydneyQuestionOutbox, queued.outbox_id)
    assert attempt.state == "pending"
    assert attempt.attempted_at is None


async def test_old_code_version_field_or_resolved_answer_is_fixed_stale_without_mutation(
    clarification_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
    )
    now = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
    service = _service(sessions)
    queued = await service.enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Stale",
        now=now,
    )
    code = await _clarification_code(sessions, queued.clarification_id)
    with pytest.raises(_service_module().SydneyClarificationError) as pending:
        await service.answer(
            code=code,
            expected_suggestion_version=1,
            answer={"kind": "due_at", "decision": "no_due_date"},
            now=now + timedelta(seconds=30),
        )
    assert str(pending.value) == "stale_clarification"
    await _set_initial_delivery(
        sessions,
        clarification_id=queued.clarification_id,
        state="sent",
        now=now + timedelta(minutes=1),
    )
    before = (
        suggestion.version,
        suggestion.payload_hash,
        tuple(suggestion.blocker_codes),
    )
    for stale_code, stale_version, answer in (
        ("AAAAAAAAAAAAAAAAAAAAAA", 1, {"kind": "due_at", "decision": "no_due_date"}),
        (code, 2, {"kind": "due_at", "decision": "no_due_date"}),
        (code, 1, {"kind": "owner", "decision": "brandon"}),
    ):
        with pytest.raises(_service_module().SydneyClarificationError) as raised:
            await service.answer(
                code=stale_code,
                expected_suggestion_version=stale_version,
                answer=answer,
                now=now + timedelta(minutes=1),
            )
        assert str(raised.value) == "stale_clarification"
    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion.id)
        clarification = await session.get(
            CRMTaskClarification, queued.clarification_id
        )
    assert (stored.version, stored.payload_hash, tuple(stored.blocker_codes)) == before
    assert clarification.state == "pending"


async def test_rotated_active_key_keeps_pending_old_key_version_answerable(
    clarification_runtime,
) -> None:
    from models.sydney_tasks import CRMTaskClarification

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
    )
    now = datetime(2026, 8, 21, 20, 15, tzinfo=UTC)
    old_service = _service_module().SydneyClarificationService(
        sessionmaker=sessions,
        brandon_chat_id=CHAT_ID,
        clarification_code_keys={7: CODE_KEY, 8: b"z" * 32},
        active_code_key_version=7,
    )
    queued = await old_service.enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Key rotation",
        now=now,
    )
    await _set_initial_delivery(
        sessions,
        clarification_id=queued.clarification_id,
        state="sent",
        now=now + timedelta(seconds=1),
    )
    code = await _clarification_code(sessions, queued.clarification_id)
    rotated_service = _service_module().SydneyClarificationService(
        sessionmaker=sessions,
        brandon_chat_id=CHAT_ID,
        clarification_code_keys={7: CODE_KEY, 8: b"z" * 32},
        active_code_key_version=8,
    )
    result = await rotated_service.answer(
        code=code,
        expected_suggestion_version=1,
        answer={"kind": "due_at", "decision": "no_due_date"},
        now=now + timedelta(minutes=1),
    )
    async with sessions() as session:
        clarification = await session.get(
            CRMTaskClarification, queued.clarification_id
        )
    assert clarification.code_key_version == 7
    assert clarification.state == "answered"
    assert result.suggestion_version == 2


@pytest.mark.parametrize(
    ("delivery_state", "chat_id"),
    [
        ("pending", CHAT_ID),
        ("failed", CHAT_ID),
        ("delivery_uncertain", CHAT_ID),
        ("sent", "-1009876543210"),
    ],
)
async def test_answer_requires_successful_exact_configured_chat_outbound_correlation(
    clarification_runtime,
    delivery_state: str,
    chat_id: str,
) -> None:
    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
    )
    now = datetime(2026, 8, 21, 20, 30, tzinfo=UTC)
    service = _service(sessions)
    queued = await service.enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Correlation",
        now=now,
    )
    await _set_initial_delivery(
        sessions,
        clarification_id=queued.clarification_id,
        state=delivery_state,
        now=now + timedelta(seconds=1),
        chat_id=chat_id,
    )
    with pytest.raises(_service_module().SydneyClarificationError) as raised:
        await service.answer(
            code=await _clarification_code(sessions, queued.clarification_id),
            expected_suggestion_version=1,
            answer={"kind": "due_at", "decision": "no_due_date"},
            now=now + timedelta(minutes=1),
        )
    assert str(raised.value) == "stale_clarification"


async def test_answer_vs_timeout_serializes_to_exactly_one_transition(
    clarification_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
    )
    created_at = datetime(2026, 8, 21, 21, 0, tzinfo=UTC)
    service = _service(sessions)
    queued = await service.enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Deadline race",
        now=created_at,
    )
    await _set_initial_delivery(
        sessions,
        clarification_id=queued.clarification_id,
        state="sent",
        now=created_at + timedelta(seconds=1),
    )
    code = await _clarification_code(sessions, queued.clarification_id)
    async with sessions() as session:
        clarification = await session.get(
            CRMTaskClarification, queued.clarification_id
        )
    race_at = clarification.slot_deadline_at
    barrier = asyncio.Barrier(2)

    async def answer_at_deadline():
        await barrier.wait()
        try:
            return await service.answer(
                code=code,
                expected_suggestion_version=1,
                answer={"kind": "due_at", "decision": "no_due_date"},
                now=race_at,
            )
        except _service_module().SydneyClarificationError:
            return None

    async def time_out_at_deadline() -> bool:
        await barrier.wait()
        dispatcher = _dispatcher(
            sessions,
            clock=_MutableClock(race_at),
            send_message=lambda **_kwargs: None,
        )
        return await dispatcher.release_expired_clarification(
            queued.clarification_id
        )

    answer_result, timed_out = await asyncio.gather(
        answer_at_deadline(),
        time_out_at_deadline(),
    )
    assert answer_result is None
    assert timed_out is True

    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion.id)
        clarification = await session.get(
            CRMTaskClarification, queued.clarification_id
        )
    assert stored.version == 1
    assert stored.blocker_codes == ["ambiguous_due_at"]
    assert stored.clarification_state == "timed_out"
    assert clarification.state == "timed_out"


async def test_answer_vs_versioned_edit_serializes_without_loser_mutation(
    clarification_runtime,
) -> None:
    from models.gmail_task_intake import CRMTaskSuggestion
    from models.sydney_tasks import CRMTaskClarification
    from services.crm_task_suggestion_service import canonical_task_payload_hash

    _engine, sessions = clarification_runtime
    suggestion = await _seed_suggestion(
        sessions,
        blocker_codes=["ambiguous_due_at"],
    )
    now = datetime(2026, 8, 21, 22, 0, tzinfo=UTC)
    service = _service(sessions)
    queued = await service.enqueue_next(
        suggestion_id=suggestion.id,
        party_label="Alice",
        subject_preview="Edit race",
        now=now,
    )
    await _set_initial_delivery(
        sessions,
        clarification_id=queued.clarification_id,
        state="sent",
        now=now + timedelta(seconds=1),
    )
    code = await _clarification_code(sessions, queued.clarification_id)
    barrier = asyncio.Barrier(2)

    async def answer_pending():
        await barrier.wait()
        try:
            return await service.answer(
                code=code,
                expected_suggestion_version=1,
                answer={"kind": "due_at", "decision": "no_due_date"},
                now=now + timedelta(minutes=1),
            )
        except _service_module().SydneyClarificationError:
            return None

    async def versioned_edit() -> bool:
        await barrier.wait()
        async with sessions() as session:
            async with session.begin():
                stored = await session.scalar(
                    sa.select(CRMTaskSuggestion)
                    .where(CRMTaskSuggestion.id == suggestion.id)
                    .with_for_update()
                )
                assert stored is not None
                if stored.version != 1:
                    return False
                previous_version = stored.version
                stored.priority = "high"
                stored.version += 1
                stored.payload_hash = canonical_task_payload_hash(
                    title=stored.title,
                    description=stored.description,
                    priority=stored.priority,
                    due_at=stored.due_at,
                    contact_id=stored.contact_id,
                    status=stored.task_status,
                )
                return await service.supersede_for_locked_suggestion(
                    session=session,
                    suggestion=stored,
                    previous_version=previous_version,
                    now=now + timedelta(minutes=1),
                )

    answer_result, edited = await asyncio.gather(
        answer_pending(),
        versioned_edit(),
    )
    assert (answer_result is not None) is not edited

    async with sessions() as session:
        stored = await session.get(CRMTaskSuggestion, suggestion.id)
        clarification = await session.get(
            CRMTaskClarification, queued.clarification_id
        )
    assert stored.version == 2
    if answer_result is not None:
        assert stored.priority == "normal"
        assert stored.blocker_codes == []
        assert clarification.state == "answered"
    else:
        assert stored.priority == "high"
        assert stored.blocker_codes == ["ambiguous_due_at"]
        assert clarification.state == "superseded"


def test_service_configuration_is_secret_free_in_repr_and_rejects_missing_key() -> None:
    module = _service_module()
    with pytest.raises(module.SydneyClarificationError) as raised:
        module.SydneyClarificationService(
            sessionmaker=object(),
            brandon_chat_id=CHAT_ID,
            clarification_code_keys={},
            active_code_key_version=CODE_KEY_VERSION,
        )
    assert str(raised.value) == "clarification_code_key_missing"
    service = module.SydneyClarificationService(
        sessionmaker=object(),
        brandon_chat_id=CHAT_ID,
        clarification_code_keys={CODE_KEY_VERSION: CODE_KEY},
        active_code_key_version=CODE_KEY_VERSION,
    )
    assert CODE_KEY.decode("ascii") not in repr(service)
