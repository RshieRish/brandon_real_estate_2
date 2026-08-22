from __future__ import annotations

import base64
import gc
import inspect
import json
import math
import weakref
from importlib import import_module
from uuid import UUID

import pytest


CLARIFICATION_ID = UUID("00000000-0000-4000-8000-000000000001")
SUGGESTION_ID = UUID("00000000-0000-4000-8000-000000000002")
CODE_KEY = b"k" * 32
BOT_TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd"
QUESTION_CONTEXT = {
    "question": "Should this be one task or separate tasks?",
    "party_label": "From Jane Miller",
    "subject_preview": "Inspection follow-up",
    "task_title": "Schedule repairs and send the report",
}


def _dispatcher_module():
    try:
        return import_module("services.sydney_telegram_dispatcher")
    except ModuleNotFoundError as exc:
        pytest.fail(
            "Sydney's Telegram dispatcher has not been implemented",
            pytrace=False,
        )
        raise AssertionError("unreachable") from exc


def _http_response(module, payload: object, *, status_code: int = 200):
    return module.TelegramHTTPResponse(
        status_code=status_code,
        payload=payload,
    )


def _derive_code(module, **overrides: object) -> str:
    values: dict[str, object] = {
        "key": CODE_KEY,
        "key_version": 7,
        "clarification_id": CLARIFICATION_ID,
        "suggestion_id": SUGGESTION_ID,
        "suggestion_version": 3,
        "field_name": "due_at",
        "round_number": 2,
    }
    values.update(overrides)
    return module.derive_clarification_code(**values)


def test_clarification_code_has_a_pinned_restart_stable_derivation() -> None:
    module = _dispatcher_module()

    first = _derive_code(module)
    after_restart = _derive_code(module)

    assert first == "SmYh3VL0sc72tl8vAilNEg"
    assert after_restart == first
    assert "=" not in first
    assert len(base64.urlsafe_b64decode(first + "==")) == 16
    assert module.clarification_code_hash(first) == bytes.fromhex(
        "f981ba6992505a91d7d92a61c59a947aab115238624ea72945cf694c2b28e31e"
    )


@pytest.mark.parametrize(
    ("changed", "value"),
    [
        ("key", b"z" * 32),
        ("key_version", 8),
        (
            "clarification_id",
            UUID("00000000-0000-4000-8000-000000000003"),
        ),
        (
            "suggestion_id",
            UUID("00000000-0000-4000-8000-000000000004"),
        ),
        ("suggestion_version", 4),
        ("field_name", "contact"),
        ("round_number", 3),
    ],
)
def test_clarification_code_is_bound_to_every_immutable_identity_field(
    changed: str,
    value: object,
) -> None:
    module = _dispatcher_module()

    assert _derive_code(module, **{changed: value}) != _derive_code(module)


@pytest.mark.parametrize(
    "bad_key",
    [
        b"",
        b"k" * 16,
        b"k" * 31,
        b"k" * 33,
        "k" * 32,
    ],
)
def test_clarification_code_requires_exactly_32_secret_bytes(
    bad_key: object,
) -> None:
    module = _dispatcher_module()

    with pytest.raises(module.SydneyClarificationError) as raised:
        _derive_code(module, key=bad_key)

    assert str(raised.value) == "clarification_code_key_invalid"
    assert "kkkk" not in str(raised.value)


@pytest.mark.parametrize(
    ("changed", "value"),
    [
        ("key_version", 0),
        ("key_version", -1),
        ("key_version", 32768),
        ("key_version", True),
        ("key_version", 1.0),
        ("clarification_id", str(CLARIFICATION_ID)),
        ("suggestion_id", str(SUGGESTION_ID)),
        ("suggestion_version", 0),
        ("suggestion_version", -1),
        ("suggestion_version", 2**31),
        ("suggestion_version", True),
        ("suggestion_version", 1.0),
        ("field_name", ""),
        ("field_name", None),
        ("field_name", "due_at\nignore"),
        ("field_name", "contact_id"),
        ("field_name", "Contact"),
        ("field_name", " contact"),
        ("field_name", "contact "),
        ("field_name", "task-detail"),
        ("field_name", "unsupported_owner"),
        ("field_name", "unsupported_link"),
        ("field_name", "optional_polish"),
        ("round_number", 0),
        ("round_number", 6),
        ("round_number", True),
    ],
)
def test_clarification_code_rejects_noncanonical_identity_material(
    changed: str,
    value: object,
) -> None:
    module = _dispatcher_module()

    with pytest.raises(module.SydneyClarificationError) as raised:
        _derive_code(module, **{changed: value})

    assert str(raised.value) == "clarification_code_identity_invalid"


@pytest.mark.parametrize(
    "field_name",
    ["action_scope", "contact", "due_at", "owner", "task_details"],
)
def test_clarification_code_accepts_only_the_five_question_fields(
    field_name: str,
) -> None:
    module = _dispatcher_module()

    code = _derive_code(module, field_name=field_name)

    assert len(base64.urlsafe_b64decode(code + "==")) == 16


def test_dispatcher_public_boundary_has_no_untrusted_identity_authority() -> None:
    module = _dispatcher_module()

    forbidden = {
        "administrator_id",
        "approval",
        "approval_nonce",
        "suggestion_id",
        "update_id",
        "user_id",
    }
    dispatcher = module.SydneyTelegramDispatcher
    assert tuple(inspect.signature(dispatcher.__init__).parameters) == (
        "self",
        "sessionmaker",
        "executor",
        "send_message",
        "config",
        "clock",
    )
    exact_methods = {
        dispatcher.dispatch_attempt: ("self", "attempt_id"),
        dispatcher.enqueue_due_reminder: ("self", "clarification_id"),
        dispatcher.release_expired_clarification: (
            "self",
            "clarification_id",
        ),
        dispatcher.recover_interrupted_attempt: ("self", "attempt_id"),
        dispatcher.reconcile_attempt: (
            "self",
            "attempt_id",
            "expected_state",
            "outcome",
            "reason",
            "audit_id",
            "observed_chat_id",
            "observed_message_id",
        ),
        dispatcher.create_initial_retry: (
            "self",
            "attempt_id",
            "reason",
            "audit_id",
        ),
    }

    for method, expected in exact_methods.items():
        parameters = inspect.signature(method).parameters
        assert tuple(parameters) == expected
        assert forbidden.isdisjoint(parameters)


@pytest.mark.parametrize(
    "overrides",
    [
        {"bot_token": ""},
        {"brandon_chat_id": ""},
        {"clarification_code_keys": {}},
        {"active_code_key_version": 0},
        {"provider_deadline_seconds": 0},
        {"provider_socket_timeout_seconds": 0},
        {
            "provider_deadline_seconds": 1,
            "provider_socket_timeout_seconds": 2,
        },
    ],
)
def test_enabled_dispatcher_configuration_fails_closed(
    overrides: dict[str, object],
) -> None:
    module = _dispatcher_module()
    values: dict[str, object] = {
        "enabled": True,
        "bot_token": BOT_TOKEN,
        "brandon_chat_id": "99887766",
        "clarification_code_keys": {7: CODE_KEY},
        "active_code_key_version": 7,
        "provider_deadline_seconds": 2,
        "provider_socket_timeout_seconds": 1,
    }
    values.update(overrides)

    with pytest.raises(
        module.TelegramConfigurationError,
        match="sydney_telegram_configuration_invalid",
    ) as raised:
        module.SydneyTelegramDispatcherConfig(**values)

    rendered = repr(raised.value)
    assert BOT_TOKEN not in rendered
    assert CODE_KEY.hex() not in rendered


@pytest.mark.parametrize(
    "brandon_chat_id",
    [
        "@brandon",
        " 99887766",
        "99887766 ",
        "+99887766",
        "099887766",
        "-099887766",
        "0",
        "9988\n7766",
        str(2**52),
        str(-(2**52)),
    ],
)
def test_enabled_configuration_requires_a_canonical_numeric_chat_id(
    brandon_chat_id: str,
) -> None:
    module = _dispatcher_module()

    with pytest.raises(
        module.TelegramConfigurationError,
        match="sydney_telegram_configuration_invalid",
    ):
        module.SydneyTelegramDispatcherConfig(
            enabled=True,
            bot_token=BOT_TOKEN,
            brandon_chat_id=brandon_chat_id,
            clarification_code_keys={7: CODE_KEY},
            active_code_key_version=7,
            provider_deadline_seconds=2,
            provider_socket_timeout_seconds=1,
        )


@pytest.mark.parametrize("brandon_chat_id", ["99887766", "-10099887766"])
def test_enabled_configuration_accepts_canonical_numeric_chat_ids(
    brandon_chat_id: str,
) -> None:
    module = _dispatcher_module()

    config = module.SydneyTelegramDispatcherConfig(
        enabled=True,
        bot_token=BOT_TOKEN,
        brandon_chat_id=brandon_chat_id,
        clarification_code_keys={7: CODE_KEY},
        active_code_key_version=7,
        provider_deadline_seconds=2,
        provider_socket_timeout_seconds=1,
    )

    assert config.brandon_chat_id == brandon_chat_id


@pytest.mark.parametrize(
    "bot_token",
    [
        "",
        "123456",
        "012345:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd",
        "+123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd",
        "123456:short",
        "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ/abcd",
        "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ?abcd",
        "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ:abcd",
        "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd\n",
        " 123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd",
        "https://api.telegram.org/bot123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd",
        "１２３４５６:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd",
        "123456:" + "a" * 129,
    ],
)
def test_enabled_configuration_requires_a_bounded_canonical_bot_token(
    bot_token: str,
) -> None:
    module = _dispatcher_module()

    with pytest.raises(
        module.TelegramConfigurationError,
        match="sydney_telegram_configuration_invalid",
    ) as raised:
        module.SydneyTelegramDispatcherConfig(
            enabled=True,
            bot_token=bot_token,
            brandon_chat_id="99887766",
            clarification_code_keys={7: CODE_KEY},
            active_code_key_version=7,
            provider_deadline_seconds=2,
            provider_socket_timeout_seconds=1,
        )

    assert bot_token not in repr(raised.value) or not bot_token


@pytest.mark.parametrize(
    "clarification_code_keys",
    [
        {True: CODE_KEY},
        {0: CODE_KEY},
        {-1: CODE_KEY},
        {32768: CODE_KEY},
        {7: b""},
        {7: b"k" * 31},
        {7: b"k" * 33},
        {7: "k" * 32},
        {7: CODE_KEY, 8: b"z" * 31},
    ],
)
def test_configuration_validates_every_retained_code_key(
    clarification_code_keys: dict[object, object],
) -> None:
    module = _dispatcher_module()

    with pytest.raises(
        module.TelegramConfigurationError,
        match="sydney_telegram_configuration_invalid",
    ) as raised:
        module.SydneyTelegramDispatcherConfig(
            enabled=True,
            bot_token=BOT_TOKEN,
            brandon_chat_id="99887766",
            clarification_code_keys=clarification_code_keys,
            active_code_key_version=7,
            provider_deadline_seconds=2,
            provider_socket_timeout_seconds=1,
        )

    assert CODE_KEY.hex() not in repr(raised.value)


@pytest.mark.parametrize(
    ("socket_timeout", "outer_deadline"),
    [
        (True, 2),
        (1, True),
        (0, 2),
        (-1, 2),
        (math.nan, 2),
        (math.inf, 2),
        (1, math.nan),
        (1, math.inf),
        (1, 1),
        (2, 1),
    ],
)
def test_configuration_requires_finite_socket_timeout_below_outer_deadline(
    socket_timeout: object,
    outer_deadline: object,
) -> None:
    module = _dispatcher_module()

    with pytest.raises(
        module.TelegramConfigurationError,
        match="sydney_telegram_configuration_invalid",
    ):
        module.SydneyTelegramDispatcherConfig(
            enabled=True,
            bot_token=BOT_TOKEN,
            brandon_chat_id="99887766",
            clarification_code_keys={7: CODE_KEY},
            active_code_key_version=7,
            provider_deadline_seconds=outer_deadline,
            provider_socket_timeout_seconds=socket_timeout,
        )


def test_disabled_dispatcher_configuration_does_not_require_secrets() -> None:
    module = _dispatcher_module()

    config = module.SydneyTelegramDispatcherConfig(
        enabled=False,
        bot_token="",
        brandon_chat_id="",
        clarification_code_keys={},
        active_code_key_version=0,
        provider_deadline_seconds=2,
        provider_socket_timeout_seconds=1,
    )

    assert config.enabled is False
    assert "bot_token" not in repr(config)
    assert "clarification_code_keys" not in repr(config)


def test_configuration_rejects_an_unavailable_active_key_version() -> None:
    module = _dispatcher_module()

    with pytest.raises(
        module.TelegramConfigurationError,
        match="sydney_telegram_configuration_invalid",
    ):
        module.SydneyTelegramDispatcherConfig(
            enabled=True,
            bot_token=BOT_TOKEN,
            brandon_chat_id="99887766",
            clarification_code_keys={7: CODE_KEY},
            active_code_key_version=8,
            provider_deadline_seconds=2,
            provider_socket_timeout_seconds=1,
        )


def test_configuration_defensively_freezes_the_retained_keyring() -> None:
    module = _dispatcher_module()
    provided = {7: CODE_KEY, 8: b"z" * 32}
    config = module.SydneyTelegramDispatcherConfig(
        enabled=True,
        bot_token=BOT_TOKEN,
        brandon_chat_id="99887766",
        clarification_code_keys=provided,
        active_code_key_version=8,
        provider_deadline_seconds=2,
        provider_socket_timeout_seconds=1,
    )

    provided[7] = b"x" * 32

    assert config.clarification_code_keys[7] == CODE_KEY
    with pytest.raises(TypeError):
        config.clarification_code_keys[7] = b"y" * 32
    assert CODE_KEY.hex() not in repr(config)
    assert (b"z" * 32).hex() not in repr(config)


def test_clarification_code_hash_rejects_noncanonical_codes() -> None:
    module = _dispatcher_module()

    valid = _derive_code(module)
    invalid_codes = (
        "",
        "short",
        valid + "=",
        valid[:-1],
        valid + "A",
        valid[:16] + "+" + valid[17:],
        valid[:-1] + "!",
        "a" * 21 + "\n",
        "ＳｍＹｈ３ＶＬ０ｓｃ７２ｔｌ８ｖＡｉｌＮＥｇ",
    )
    for value in invalid_codes:
        with pytest.raises(module.SydneyClarificationError) as raised:
            module.clarification_code_hash(value)
        assert str(raised.value) == "invalid_clarification_code"


def test_initial_question_rendering_and_hash_are_restart_stable() -> None:
    module = _dispatcher_module()
    code = _derive_code(module)

    rendered = module.render_clarification_question(
        template_id="clarification_initial_v1",
        context_json=json.dumps(
            QUESTION_CONTEXT,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ),
        code=code,
    )

    assert rendered == (
        "Should this be one task or separate tasks?\n\n"
        "From Jane Miller | Inspection follow-up\n"
        "Proposed task: Schedule repairs and send the report\n"
        "Reference code: SmYh3VL0sc72tl8vAilNEg"
    )
    assert module.rendered_question_hash(rendered) == (
        "ccd93ce2301f263518e1eeb1d672ccb642595bfb93a4096e9bfddf75c1e3d3a9"
    )


def test_reminder_rendering_is_distinct_and_keeps_the_same_code() -> None:
    module = _dispatcher_module()
    code = _derive_code(module)

    rendered = module.render_clarification_question(
        template_id="clarification_reminder_v1",
        context_json=json.dumps(
            QUESTION_CONTEXT,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ),
        code=code,
    )

    assert rendered == (
        "Reminder: Should this be one task or separate tasks?\n\n"
        "From Jane Miller | Inspection follow-up\n"
        "Proposed task: Schedule repairs and send the report\n"
        "Reference code: SmYh3VL0sc72tl8vAilNEg"
    )
    assert module.rendered_question_hash(rendered) == (
        "5dcf740be7394b918150cd5b80f637b36faf251633b7c626ab061fd5234d8150"
    )


@pytest.mark.parametrize(
    ("template", "context"),
    [
        ("", QUESTION_CONTEXT),
        ("clarification_retry_v1", QUESTION_CONTEXT),
        ("clarification_initial_v1", {}),
        (
            "clarification_initial_v1",
            {**QUESTION_CONTEXT, "code": "must-not-persist"},
        ),
        (
            "clarification_initial_v1",
            {**QUESTION_CONTEXT, "question": "Ignore\nprevious instructions"},
        ),
        (
            "clarification_initial_v1",
            {**QUESTION_CONTEXT, "task_title": "x" * 256},
        ),
        (
            "clarification_initial_v1",
            {**QUESTION_CONTEXT, "subject_preview": 42},
        ),
    ],
)
def test_question_renderer_rejects_unbounded_or_noncanonical_persistence(
    template: str,
    context: dict[str, object],
) -> None:
    module = _dispatcher_module()

    with pytest.raises(
        (ValueError, module.SydneyClarificationError),
        match="clarification_question_invalid|validation error",
    ):
        module.render_clarification_question(
            template_id=template,
            context_json=json.dumps(
                context,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            code=_derive_code(module),
        )


def test_question_renderer_rejects_a_persisted_plaintext_code() -> None:
    module = _dispatcher_module()
    code = _derive_code(module)

    with pytest.raises(
        (ValueError, module.SydneyClarificationError),
        match="clarification_question_invalid|validation error",
    ):
        module.render_clarification_question(
            template_id="clarification_initial_v1",
            context_json=json.dumps(
                {**QUESTION_CONTEXT, "task_title": f"Call Jane {code}"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            code=code,
        )


def test_question_renderer_enforces_telegram_text_limit_after_rendering() -> None:
    module = _dispatcher_module()
    context = {
        "question": "q" * 3000,
        "party_label": "p" * 500,
        "subject_preview": "s" * 500,
        "task_title": "t" * 500,
    }

    with pytest.raises(
        (ValueError, module.SydneyClarificationError),
        match="clarification_question_invalid|validation error",
    ):
        module.render_clarification_question(
            template_id="clarification_initial_v1",
            context_json=json.dumps(
                context,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            code=_derive_code(module),
        )


def test_telegram_payload_targets_only_the_configured_chat() -> None:
    module = _dispatcher_module()
    text = "When should this be due?\nReference code: SmYh3VL0sc72tl8vAilNEg"

    initial = module.build_telegram_send_payload(
        configured_chat_id="99887766",
        text=text,
        reply_to_message_id=None,
    )
    reminder = module.build_telegram_send_payload(
        configured_chat_id="99887766",
        text="Reminder: " + text,
        reply_to_message_id=701,
    )

    assert initial == {"chat_id": "99887766", "text": text}
    assert reminder == {
        "chat_id": "99887766",
        "text": "Reminder: " + text,
        "reply_parameters": {"message_id": 701},
    }
    forbidden = {"user_id", "update_id", "suggestion_id", "approval"}
    assert forbidden.isdisjoint(initial)
    assert forbidden.isdisjoint(reminder)


@pytest.mark.parametrize(
    ("chat_id", "text", "reply_to_message_id"),
    [
        ("@brandon", "valid", None),
        ("099887766", "valid", None),
        ("99887766", "", None),
        ("99887766", "x" * 4097, None),
        ("99887766", "valid", True),
        ("99887766", "valid", 0),
        ("99887766", "valid", -1),
    ],
)
def test_telegram_payload_rejects_noncanonical_transport_material(
    chat_id: str,
    text: str,
    reply_to_message_id: object,
) -> None:
    module = _dispatcher_module()

    with pytest.raises(
        module.TelegramDispatchError,
        match="telegram_payload_invalid",
    ):
        module.build_telegram_send_payload(
            configured_chat_id=chat_id,
            text=text,
            reply_to_message_id=reply_to_message_id,
        )


def test_exact_telegram_success_correlation_returns_only_provider_ids() -> None:
    module = _dispatcher_module()

    result = module.parse_telegram_send_response(
        response=_http_response(
            module,
            {
                "ok": True,
                "result": {
                    "message_id": 701,
                    "date": 1787328000,
                    "chat": {
                        "id": 99887766,
                        "type": "private",
                        "first_name": "Brandon",
                    },
                    "text": "Question text",
                },
            },
        ),
        configured_chat_id="99887766",
    )

    assert result.chat_id == "99887766"
    assert result.message_id == "701"
    assert vars(result) == {
        "chat_id": "99887766",
        "message_id": "701",
    }


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"ok": True},
        {"ok": 1, "result": {}},
        {"ok": True, "result": {"message_id": 701}},
        {
            "ok": True,
            "result": {"message_id": 701, "chat": {"id": 99887767}},
        },
        {
            "ok": True,
            "result": {"message_id": True, "chat": {"id": 99887766}},
        },
        {
            "ok": True,
            "result": {"message_id": 0, "chat": {"id": 99887766}},
        },
        {
            "ok": True,
            "result": {"message_id": 701, "chat": {"id": True}},
        },
        {
            "ok": True,
            "result": {"message_id": 701, "chat": {"id": "99887766"}},
        },
    ],
)
def test_malformed_or_wrong_chat_success_is_delivery_uncertain(
    response: object,
) -> None:
    module = _dispatcher_module()

    with pytest.raises(
        module.TelegramDeliveryUncertain,
        match="telegram_delivery_uncertain",
    ) as raised:
        module.parse_telegram_send_response(
            response=_http_response(module, response),
            configured_chat_id="99887766",
        )

    assert "99887767" not in str(raised.value)
    assert repr(response) not in str(raised.value)


def test_explicit_telegram_rejection_is_definite_and_sanitized() -> None:
    module = _dispatcher_module()
    response = {
        "ok": False,
        "error_code": 400,
        "description": (
            f"Bad Request {BOT_TOKEN} "
            "SmYh3VL0sc72tl8vAilNEg"
        ),
    }

    with pytest.raises(
        module.TelegramProviderRejected,
        match="telegram_provider_rejected",
    ) as raised:
        module.parse_telegram_send_response(
            response=_http_response(module, response, status_code=400),
            configured_chat_id="99887766",
        )

    assert response["description"] not in str(raised.value)
    assert response["description"] not in repr(raised.value)


@pytest.mark.parametrize("error_code", [500, 502, 503, 599])
def test_telegram_server_error_is_delivery_uncertain(
    error_code: int,
) -> None:
    module = _dispatcher_module()
    response = {
        "ok": False,
        "error_code": error_code,
        "description": f"proxy retained {BOT_TOKEN}",
    }

    with pytest.raises(
        module.TelegramDeliveryUncertain,
        match="telegram_delivery_uncertain",
    ) as raised:
        module.parse_telegram_send_response(
            response=_http_response(
                module,
                response,
                status_code=error_code,
            ),
            configured_chat_id="99887766",
        )

    assert BOT_TOKEN not in repr(raised.value)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"ok": False, "error_code": 400, "description": "cached"},
        {
            "ok": True,
            "result": {
                "message_id": 701,
                "chat": {"id": 99887766},
            },
        },
    ],
)
def test_http_5xx_can_never_be_downgraded_to_a_definite_rejection(
    payload: object,
) -> None:
    module = _dispatcher_module()

    with pytest.raises(
        module.TelegramDeliveryUncertain,
        match="telegram_delivery_uncertain",
    ):
        module.parse_telegram_send_response(
            response=_http_response(module, payload, status_code=502),
            configured_chat_id="99887766",
        )


def test_http_200_with_a_telegram_4xx_body_is_still_uncertain() -> None:
    module = _dispatcher_module()

    with pytest.raises(
        module.TelegramDeliveryUncertain,
        match="telegram_delivery_uncertain",
    ):
        module.parse_telegram_send_response(
            response=_http_response(
                module,
                {"ok": False, "error_code": 400, "description": "cached"},
            ),
            configured_chat_id="99887766",
        )


def test_http_redirect_is_uncertain_even_with_a_success_shaped_body() -> None:
    module = _dispatcher_module()

    with pytest.raises(
        module.TelegramDeliveryUncertain,
        match="telegram_delivery_uncertain",
    ):
        module.parse_telegram_send_response(
            response=_http_response(
                module,
                {
                    "ok": True,
                    "result": {
                        "message_id": 701,
                        "chat": {"id": 99887766},
                    },
                },
                status_code=302,
            ),
            configured_chat_id="99887766",
        )


class _StreamingResponse:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        content_length: str | None,
        status_code: int = 200,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._chunks = chunks
        self.headers = (
            {} if content_length is None else {"Content-Length": content_length}
        )
        self.headers.update(extra_headers or {})
        self.status_code = status_code
        self.closed = False
        self.iterated = False
        self.iterated_bytes = 0

    def iter_content(self, *, chunk_size: int) -> object:
        assert chunk_size > 0
        self.iterated = True
        for chunk in self._chunks:
            self.iterated_bytes += len(chunk)
            yield chunk

    def close(self) -> None:
        self.closed = True


def test_sync_transport_streams_one_bounded_send_message_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _dispatcher_module()
    assert module.TELEGRAM_RESPONSE_MAX_BYTES == 64 * 1024
    calls: list[tuple[str, dict[str, object], float, bool, bool]] = []
    response_payload = {
        "ok": True,
        "result": {
            "message_id": 701,
            "date": 1787328000,
            "chat": {"id": 99887766, "type": "private"},
            "text": "Question text",
        },
    }
    encoded = json.dumps(
        response_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    streamed = _StreamingResponse(
        [encoded[:17], encoded[17:]],
        content_length=str(len(encoded)),
    )

    def post(
        url: str,
        *,
        json: dict[str, object],
        timeout: float,
        stream: bool,
        allow_redirects: bool,
    ) -> _StreamingResponse:
        calls.append((url, json, timeout, stream, allow_redirects))
        return streamed

    monkeypatch.setattr(module.requests, "post", post)
    payload = {"chat_id": "99887766", "text": "Question text"}

    response = module.send_telegram_message(
        bot_token=BOT_TOKEN,
        payload=payload,
        socket_timeout_seconds=1.25,
    )

    assert response.status_code == 200
    assert response.payload == response_payload
    assert BOT_TOKEN not in repr(response)
    assert "Question text" not in repr(response)
    assert calls == [
        (
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            payload,
            1.25,
            True,
            False,
        )
    ]
    assert streamed.iterated is True
    assert streamed.iterated_bytes == len(encoded)
    assert streamed.closed is True


def test_sync_transport_never_follows_a_redirect_with_the_token_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _dispatcher_module()
    body = b'{"ok":false,"error_code":400}'
    streamed = _StreamingResponse(
        [body],
        content_length=str(len(body)),
        status_code=302,
        extra_headers={
            "Location": f"https://proxy.invalid/capture/{BOT_TOKEN}",
        },
    )
    calls = 0

    def post(*_args: object, **kwargs: object) -> _StreamingResponse:
        nonlocal calls
        calls += 1
        assert kwargs["allow_redirects"] is False
        return streamed

    monkeypatch.setattr(module.requests, "post", post)

    response = module.send_telegram_message(
        bot_token=BOT_TOKEN,
        payload={"chat_id": "99887766", "text": "question"},
        socket_timeout_seconds=1,
    )

    assert calls == 1
    assert response.status_code == 302
    assert BOT_TOKEN not in repr(response)
    with pytest.raises(module.TelegramDeliveryUncertain):
        module.parse_telegram_send_response(
            response=response,
            configured_chat_id="99887766",
        )


@pytest.mark.parametrize("content_length", [str(64 * 1024 + 1), "invalid", "-1"])
def test_sync_transport_rejects_invalid_or_oversize_content_length_without_reading(
    monkeypatch: pytest.MonkeyPatch,
    content_length: str,
) -> None:
    module = _dispatcher_module()
    streamed = _StreamingResponse(
        [b'raw proxy body containing "token"'],
        content_length=content_length,
        status_code=502,
    )
    monkeypatch.setattr(module.requests, "post", lambda *_args, **_kwargs: streamed)

    with pytest.raises(
        module.TelegramDeliveryUncertain,
        match="telegram_delivery_uncertain",
    ):
        module.send_telegram_message(
            bot_token=BOT_TOKEN,
            payload={"chat_id": "99887766", "text": "client question text"},
            socket_timeout_seconds=1,
        )

    assert streamed.iterated is False
    assert streamed.closed is True


def test_sync_transport_caps_chunked_response_without_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _dispatcher_module()
    cap = module.TELEGRAM_RESPONSE_MAX_BYTES
    streamed = _StreamingResponse(
        [b"x" * (cap // 2), b"y" * (cap // 2 + 1), b"never-read"],
        content_length=None,
        status_code=502,
    )
    monkeypatch.setattr(module.requests, "post", lambda *_args, **_kwargs: streamed)

    with pytest.raises(
        module.TelegramDeliveryUncertain,
        match="telegram_delivery_uncertain",
    ):
        module.send_telegram_message(
            bot_token=BOT_TOKEN,
            payload={"chat_id": "99887766", "text": "client question text"},
            socket_timeout_seconds=1,
        )

    assert streamed.iterated_bytes == cap + 1
    assert streamed.closed is True


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"\xff\xfe",
        b'{"ok":true,"ok":false}',
        b'{"ok":NaN}',
        b"[]",
    ],
)
def test_sync_transport_rejects_noncanonical_json_preflight(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    module = _dispatcher_module()
    streamed = _StreamingResponse(
        [body],
        content_length=str(len(body)),
        status_code=502,
    )
    monkeypatch.setattr(module.requests, "post", lambda *_args, **_kwargs: streamed)

    with pytest.raises(
        module.TelegramDeliveryUncertain,
        match="telegram_delivery_uncertain",
    ):
        module.send_telegram_message(
            bot_token=BOT_TOKEN,
            payload={"chat_id": "99887766", "text": "question"},
            socket_timeout_seconds=1,
        )

    assert streamed.closed is True


def test_sync_transport_accepts_an_exact_cap_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _dispatcher_module()
    prefix = b'{"ok":false,"error_code":400}'
    encoded = prefix + (b" " * (module.TELEGRAM_RESPONSE_MAX_BYTES - len(prefix)))
    streamed = _StreamingResponse(
        [encoded],
        content_length=str(len(encoded)),
        status_code=400,
    )
    monkeypatch.setattr(module.requests, "post", lambda *_args, **_kwargs: streamed)

    response = module.send_telegram_message(
        bot_token=BOT_TOKEN,
        payload={"chat_id": "99887766", "text": "client question text"},
        socket_timeout_seconds=1,
    )

    assert response.status_code == 400
    assert response.payload == {"ok": False, "error_code": 400}
    assert streamed.iterated_bytes == module.TELEGRAM_RESPONSE_MAX_BYTES
    assert streamed.closed is True


@pytest.mark.parametrize("failure_stage", ["request", "response_json"])
def test_sync_transport_sanitizes_network_and_json_errors(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    module = _dispatcher_module()
    secret = BOT_TOKEN

    def post(*_args: object, **_kwargs: object) -> object:
        if failure_stage == "request":
            raise RuntimeError(
                f"raw transport failure with {secret} and client question text"
            )
        return _StreamingResponse(
            [f'{{"secret":"{secret}"'.encode("utf-8")],
            content_length=None,
            status_code=502,
        )

    monkeypatch.setattr(module.requests, "post", post)

    with pytest.raises(
        module.TelegramDeliveryUncertain,
        match="telegram_delivery_uncertain",
    ) as raised:
        module.send_telegram_message(
            bot_token=secret,
            payload={"chat_id": "99887766", "text": "client question text"},
            socket_timeout_seconds=1,
        )

    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert secret not in repr(raised.value)
    assert "client question text" not in repr(raised.value)
    traceback = raised.value.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code.co_name == "send_telegram_message":
            retained = repr(traceback.tb_frame.f_locals)
            assert secret not in retained
            assert "client question text" not in retained
        traceback = traceback.tb_next


def test_sync_transport_does_not_retain_secret_or_raw_error_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _dispatcher_module()

    class _Secret(str):
        __slots__ = ("__weakref__",)

    class _Canary:
        pass

    class _RaisingPost:
        def __init__(self, error: BaseException) -> None:
            self.error: BaseException | None = error

        def __call__(self, *_args: object, **_kwargs: object) -> object:
            error = self.error
            self.error = None
            assert error is not None
            raise error

    secret = _Secret(BOT_TOKEN)
    canary = _Canary()
    raw_error = RuntimeError("raw provider error", canary)
    post = _RaisingPost(raw_error)
    secret_ref = weakref.ref(secret)
    canary_ref = weakref.ref(canary)
    monkeypatch.setattr(module.requests, "post", post)

    with pytest.raises(module.TelegramDeliveryUncertain) as raised:
        module.send_telegram_message(
            bot_token=secret,
            payload={"chat_id": "99887766", "text": "question"},
            socket_timeout_seconds=1,
        )

    sanitized = raised.value
    monkeypatch.undo()
    del raised, secret, canary, raw_error, post
    gc.collect()

    assert sanitized.__cause__ is None
    assert sanitized.__context__ is None
    assert secret_ref() is None
    assert canary_ref() is None


def test_dispatcher_never_implements_an_inbound_telegram_consumer() -> None:
    module = _dispatcher_module()
    source = inspect.getsource(module)

    assert "getUpdates" not in source
    assert "setWebhook" not in source
