from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from threading import Event, Lock, Thread

import pytest

OVERLAY = Path(__file__).resolve().parents[2] / "hermes" / "overlay"
sys.path.insert(0, str(OVERLAY))

from sydney_spool import (
    SpoolConflict,
    SydneySpool,
    ordered_reconciliation_hash,
    redact_payload,
    redact_text,
)


@pytest.mark.parametrize(
    ("source", "secret"),
    (
        ('{"password":"quoted-password"}', "quoted-password"),
        ('{"clientSecret":"quoted-client-secret"}', "quoted-client-secret"),
        ('{"access-token":"quoted-access-token"}', "quoted-access-token"),
        ('{"apiKey":"quoted-api-key"}', "quoted-api-key"),
        ('{"cookie":"session=quoted-cookie"}', "session=quoted-cookie"),
        ('{"authorization":"Bearer quoted-bearer"}', "quoted-bearer"),
    ),
)
def test_json_credential_text_is_redacted_without_corrupting_json(
    source: str,
    secret: str,
) -> None:
    redacted = redact_text(source)

    assert secret not in redacted
    assert "REDACTED" in redacted
    assert isinstance(json.loads(redacted), dict)


@pytest.mark.parametrize("key", ("token", "secret", "credentials", "pwd"))
def test_generic_secret_bearing_payload_fields_are_redacted(key: str) -> None:
    secret = "opaque-generic-secret-value"

    redacted = redact_payload({"nested": {key: secret}})

    assert redacted == {"nested": {key: "[REDACTED_SECRET]"}}
    assert secret not in json.dumps(redacted)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    (
        (
            "credentials",
            {"value": "nested-secret", "details": ["list-secret"]},
            {
                "value": "[REDACTED_SECRET]",
                "details": ["[REDACTED_SECRET]"],
            },
        ),
        (
            "authorization",
            ["Bearer nested-secret", {"value": "deeper-secret"}],
            ["[REDACTED_SECRET]", {"value": "[REDACTED_SECRET]"}],
        ),
    ),
)
def test_secret_bearing_payload_containers_redact_the_entire_subtree(
    key: str,
    value: object,
    expected: object,
) -> None:
    redacted = redact_payload({key: value})

    assert redacted == {key: expected}
    assert "nested-secret" not in json.dumps(redacted)
    assert "deeper-secret" not in json.dumps(redacted)


@pytest.mark.parametrize(
    ("source", "secret"),
    (
        ("id_token=header.payload.signature", "header.payload.signature"),
        ("session_token=opaque-session-value", "opaque-session-value"),
        ("handoff=short-handoff-secret", "short-handoff-secret"),
        ("token=shortsecret123", "shortsecret123"),
        ("Set-Cookie: sid=opaque-cookie-value", "sid=opaque-cookie-value"),
    ),
)
def test_plain_oauth_session_handoff_and_cookie_values_never_reach_spool(
    source: str,
    secret: str,
) -> None:
    redacted = redact_text(source)

    assert secret not in redacted
    assert "REDACTED" in redacted


def _bundle(message_id: str = "telegram-1") -> tuple[dict, dict]:
    event_batch = {
        "platform": "telegram",
        "external_user_id": "brandon",
        "external_chat_id": "private-chat",
        "display_label": "Brandon",
        "hermes_session_id": "session-1",
        "logical_conversation_id": "11111111-1111-4111-8111-111111111111",
        "events": [
            {
                "source_event_key": f"telegram:{message_id}:user",
                "event_type": "user",
                "role": "user",
                "occurred_at": "2026-08-25T12:00:00+00:00",
                "content": "Keep this context",
                "metadata": {"message_id": message_id},
            }
        ],
    }
    run_start = {
        "platform_message_id": message_id,
        "terminal_deadline_at": "2026-08-26T12:00:00+00:00",
    }
    return event_batch, run_start


def test_creates_private_wal_database_with_explicit_schema(tmp_path: Path) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    try:
        assert spool.schema_version == 1
        assert spool.pragma("journal_mode").lower() == "wal"
        assert int(spool.pragma("synchronous")) == 2
        assert int(spool.pragma("foreign_keys")) == 1
        assert int(spool.pragma("busy_timeout")) >= 5_000
        assert (spool.path.stat().st_mode & 0o777) == 0o600
        tables = {
            str(row[0])
            for row in spool.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"reconciliation_state", "reconciliation_dirty"} <= tables
    finally:
        spool.close()


def test_inbound_event_and_run_are_committed_as_one_exactly_replayable_unit(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, run_start = _bundle()
    first = spool.enqueue_inbound(event_batch, run_start, source_key="inbound:1")
    replay = spool.enqueue_inbound(event_batch, run_start, source_key="inbound:1")

    assert replay == first
    assert spool.pending_count == 1
    record = spool.pending(limit=10)[0]
    assert record.kind == "inbound_bundle"
    assert record.payload == {"event_batch": event_batch, "run_start": run_start}

    conflicting_event, conflicting_run = _bundle("different")
    with pytest.raises(SpoolConflict):
        spool.enqueue_inbound(
            conflicting_event,
            conflicting_run,
            source_key="inbound:1",
        )


def test_inbound_local_metadata_is_durable_and_idempotent(tmp_path: Path) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    try:
        event_batch, run_start = _bundle()
        first = spool.enqueue_inbound(
            event_batch,
            run_start,
            source_key="inbound:recovery:stable",
            local_metadata={"recovery_policy": "review_only"},
        )
        second = spool.enqueue_inbound(
            event_batch,
            run_start,
            source_key="inbound:recovery:stable",
            local_metadata={"recovery_policy": "review_only"},
        )

        record = spool.get_record("inbound:recovery:stable")
        assert first == second
        assert record is not None
        assert record.payload["local_metadata"] == {"recovery_policy": "review_only"}
    finally:
        spool.close()


def test_inbound_local_metadata_replay_conflict_and_unknown_policy_fail_closed(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    try:
        event_batch, run_start = _bundle()
        spool.enqueue_inbound(
            event_batch,
            run_start,
            source_key="inbound:recovery:stable",
            local_metadata={"recovery_policy": "review_only"},
        )

        with pytest.raises(SpoolConflict):
            spool.enqueue_inbound(
                event_batch,
                run_start,
                source_key="inbound:recovery:stable",
                local_metadata=None,
            )
        with pytest.raises(ValueError, match="local metadata"):
            spool.enqueue_inbound(
                event_batch,
                run_start,
                source_key="inbound:recovery:other",
                local_metadata={"recovery_policy": "send_allowed"},
            )
    finally:
        spool.close()


def test_secret_material_is_redacted_before_sqlite_persistence(tmp_path: Path) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, run_start = _bundle()
    secret = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
    event_batch["events"][0]["content"] = (
        f"Authorization: Bearer {secret} password=hunter2 "
        "https://example.test/path?access_token=oauth-secret#handoff=signed"
    )
    spool.enqueue_inbound(event_batch, run_start, source_key="inbound:redacted")
    spool.close()

    database_bytes = (tmp_path / "sydney_spool.db").read_bytes()
    wal_path = tmp_path / "sydney_spool.db-wal"
    if wal_path.exists():
        database_bytes += wal_path.read_bytes()
    assert secret.encode() not in database_bytes
    assert b"hunter2" not in database_bytes
    assert b"oauth-secret" not in database_bytes
    assert b"#handoff=signed" not in database_bytes


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
        "access-token",
    ),
)
def test_camelcase_and_hyphenated_credential_fields_are_redacted(
    key: str,
) -> None:
    secret = "opaque-secret-value-that-must-not-persist"

    redacted = redact_payload({"nested": [{key: secret}]})

    assert redacted == {"nested": [{key: "[REDACTED_SECRET]"}]}
    assert secret not in json.dumps(redacted)


@pytest.mark.parametrize(
    "parameter",
    (
        "approval",
        "approval_token",
        "session",
        "session_token",
        "nonce",
        "handoff",
        "code",
        "state",
        "signature",
        "sig",
    ),
)
def test_signed_url_parameters_are_redacted_before_sqlite_persistence(
    tmp_path: Path,
    parameter: str,
) -> None:
    spool = SydneySpool(tmp_path / f"sydney-{parameter}.db")
    event_batch, run_start = _bundle(parameter)
    secret = f"signed-{parameter}-value"
    event_batch["events"][0]["content"] = (
        f"https://example.test/callback?{parameter}={secret}"
        f"#section=review&{parameter}={secret}"
    )
    spool.enqueue_inbound(
        event_batch,
        run_start,
        source_key=f"inbound:signed-url:{parameter}",
    )
    spool.close()

    database_bytes = (tmp_path / f"sydney-{parameter}.db").read_bytes()
    wal_path = tmp_path / f"sydney-{parameter}.db-wal"
    if wal_path.exists():
        database_bytes += wal_path.read_bytes()
    assert secret.encode() not in database_bytes


def test_context_labeled_uuid_and_database_uri_secrets_never_reach_spool(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, run_start = _bundle()
    contextual_token = "11111111-2222-4333-8444-555555555555"
    database_password = "database-password-value"
    event_batch["events"][0]["content"] = (
        f"{contextual_token}\n\nhere is the token. "
        "postgresql+asyncpg://dbuser:"
        f"{database_password}@database.example.test/app"
    )
    spool.enqueue_inbound(event_batch, run_start, source_key="inbound:uri-redacted")
    spool.close()

    database_bytes = (tmp_path / "sydney_spool.db").read_bytes()
    wal_path = tmp_path / "sydney_spool.db-wal"
    if wal_path.exists():
        database_bytes += wal_path.read_bytes()
    assert contextual_token.encode() not in database_bytes
    assert database_password.encode() not in database_bytes


def test_unlabeled_well_known_provider_keys_never_reach_spool(tmp_path: Path) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, run_start = _bundle()
    google_key = "AIza" + "A" * 35
    event_batch["events"][0]["content"] = f"Use {google_key} for this request"
    spool.enqueue_inbound(event_batch, run_start, source_key="inbound:provider-key")
    spool.close()

    database_bytes = (tmp_path / "sydney_spool.db").read_bytes()
    wal_path = tmp_path / "sydney_spool.db-wal"
    if wal_path.exists():
        database_bytes += wal_path.read_bytes()
    assert google_key.encode() not in database_bytes


def test_actual_hermes_telegram_token_never_reaches_spool(tmp_path: Path) -> None:
    token = "telegram-runtime-token-that-is-not-self-identifying"
    event_batch, run_start = _bundle("telegram-runtime-token")
    event_batch["events"][0]["content"] = f"Opaque copied value: {token}"

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
        spool = SydneySpool(tmp_path / "sydney_spool.db")
        spool.enqueue_inbound(
            event_batch,
            run_start,
            source_key="inbound:telegram-runtime-token",
        )
        spool.close()

    database_bytes = (tmp_path / "sydney_spool.db").read_bytes()
    wal_path = tmp_path / "sydney_spool.db-wal"
    if wal_path.exists():
        database_bytes += wal_path.read_bytes()
    assert token.encode() not in database_bytes


def test_encoded_runtime_secret_never_reaches_spool_and_harmless_urls_are_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from urllib.parse import quote

    secret = "telegram/runtime?token=value and space"
    encoded_once = quote(secret, safe="")
    encoded_twice = quote(encoded_once, safe="")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", secret)

    redacted = redact_text(
        f"https://example.test/callback?opaque={encoded_once}&nested={encoded_twice}"
    )

    assert secret not in redacted
    assert encoded_once not in redacted
    assert encoded_twice not in redacted
    harmless = "https://example.test/login?return_to=https%3A%2F%2Fother.test%2Fok"
    assert redact_text(harmless) == harmless


def test_rebind_pending_run_lease_changes_only_exact_pending_records(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    exact_pending = spool.enqueue_tool_before(
        run_id="run-exact",
        lease_owner="worker-old",
        tool_call_id="call-pending",
        tool_name="leads_recent",
        arguments={},
        side_effect_class="read_only",
    )
    exact_acknowledged = spool.enqueue_tool_after(
        run_id="run-exact",
        lease_owner="worker-old",
        tool_call_id="call-acknowledged",
        state="succeeded",
    )
    spool.acknowledge(exact_acknowledged, {"state": "succeeded"})
    other_pending = spool.enqueue_tool_after(
        run_id="run-other",
        lease_owner="worker-old",
        tool_call_id="call-other",
        state="failed",
    )

    assert spool.rebind_pending_run_lease("run-exact", "worker-new") == 1

    assert (
        spool.get_record("tool:run-exact:call-pending:before").payload["lease_owner"]
        == "worker-new"
    )
    assert (
        spool.get_record("tool:run-exact:call-acknowledged:after:succeeded").payload[
            "lease_owner"
        ]
        == "worker-old"
    )
    assert (
        spool.get_record("tool:run-other:call-other:after:failed").payload[
            "lease_owner"
        ]
        == "worker-old"
    )
    assert {record.id for record in spool.pending(limit=10)} == {
        exact_pending,
        other_pending,
    }


def test_rebind_pending_session_parent_changes_only_exact_pending_batches(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    exact_batch, exact_run = _bundle("exact-pending")
    exact_batch["parent_hermes_session_id"] = "missing-parent"
    exact_pending = spool.enqueue_inbound(
        exact_batch,
        exact_run,
        source_key="inbound:exact-pending",
    )

    acknowledged_batch, acknowledged_run = _bundle("exact-acknowledged")
    acknowledged_batch["parent_hermes_session_id"] = "missing-parent"
    exact_acknowledged = spool.enqueue_inbound(
        acknowledged_batch,
        acknowledged_run,
        source_key="inbound:exact-acknowledged",
    )
    spool.acknowledge(exact_acknowledged, {"accepted": True})

    other_batch, other_run = _bundle("other-pending")
    other_batch["hermes_session_id"] = "session-2"
    other_batch["parent_hermes_session_id"] = "other-parent"
    other_pending = spool.enqueue_inbound(
        other_batch,
        other_run,
        source_key="inbound:other-pending",
    )

    assert spool.rebind_pending_session_parent("session-1", None) == 1

    canonical = spool.get_record("inbound:exact-pending")
    assert canonical is not None
    assert canonical.payload["event_batch"]["parent_hermes_session_id"] is None
    assert (
        spool.get_record("inbound:exact-acknowledged").payload["event_batch"][
            "parent_hermes_session_id"
        ]
        == "missing-parent"
    )
    assert (
        spool.get_record("inbound:other-pending").payload["event_batch"][
            "parent_hermes_session_id"
        ]
        == "other-parent"
    )
    replay_batch = {**exact_batch, "parent_hermes_session_id": None}
    assert (
        spool.enqueue_inbound(
            replay_batch,
            exact_run,
            source_key="inbound:exact-pending",
        )
        == exact_pending
    )
    assert {record.id for record in spool.pending(limit=10)} == {
        exact_pending,
        other_pending,
    }


def test_rebind_pending_session_parent_normalizes_staged_control_delivery(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, _run_start = _bundle("staged-control")
    event_batch["parent_hermes_session_id"] = "missing-parent"
    response_sha256 = hashlib.sha256(b"wait").hexdigest()

    assert (
        spool.stage_control_delivery(
            platform="telegram",
            chat_id="private-chat",
            platform_message_id="staged-control",
            run_id="run-staged-control",
            lease_owner="worker-staged-control",
            response_sha256=response_sha256,
            delivery_kind="deferred",
            event_batch=event_batch,
            run_update=None,
        )
        == "staged"
    )

    assert spool.rebind_pending_session_parent("session-1", None) == 0

    staged = spool.get_final_delivery(
        platform="telegram",
        chat_id="private-chat",
        platform_message_id="staged-control",
    )
    assert staged is not None
    assert staged["event_batch"]["parent_hermes_session_id"] is None
    local_id = spool.confirm_control_delivery(
        platform="telegram",
        chat_id="private-chat",
        platform_message_id="staged-control",
        response_sha256=response_sha256,
        delivery_kind="deferred",
    )
    confirmed = spool.get_record("run:run-staged-control:control:deferred")
    assert confirmed is not None
    assert confirmed.id == local_id
    assert confirmed.payload["event_batch"]["parent_hermes_session_id"] is None


def test_rebind_pending_session_parent_keeps_confirmed_control_replay_exact(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, _run_start = _bundle("confirmed-control")
    event_batch["parent_hermes_session_id"] = "missing-parent"
    response_sha256 = hashlib.sha256(b"wait").hexdigest()
    spool.stage_control_delivery(
        platform="telegram",
        chat_id="private-chat",
        platform_message_id="confirmed-control",
        run_id="run-confirmed-control",
        lease_owner="worker-confirmed-control",
        response_sha256=response_sha256,
        delivery_kind="deferred",
        event_batch=event_batch,
        run_update=None,
    )
    first_id = spool.confirm_control_delivery(
        platform="telegram",
        chat_id="private-chat",
        platform_message_id="confirmed-control",
        response_sha256=response_sha256,
        delivery_kind="deferred",
    )

    assert spool.rebind_pending_session_parent("session-1", None) == 1

    replay_id = spool.confirm_control_delivery(
        platform="telegram",
        chat_id="private-chat",
        platform_message_id="confirmed-control",
        response_sha256=response_sha256,
        delivery_kind="deferred",
    )
    assert replay_id == first_id
    staged = spool.get_final_delivery(
        platform="telegram",
        chat_id="private-chat",
        platform_message_id="confirmed-control",
    )
    confirmed = spool.get_record("run:run-confirmed-control:control:deferred")
    assert staged is not None
    assert confirmed is not None
    assert staged["event_batch"]["parent_hermes_session_id"] is None
    assert confirmed.payload["event_batch"]["parent_hermes_session_id"] is None


def test_rebind_pending_session_parent_rolls_back_outbox_and_staged_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sydney_spool as spool_module

    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, _run_start = _bundle("rollback-control")
    event_batch["parent_hermes_session_id"] = "missing-parent"
    response_sha256 = hashlib.sha256(b"wait").hexdigest()
    spool.stage_control_delivery(
        platform="telegram",
        chat_id="private-chat",
        platform_message_id="rollback-control",
        run_id="run-rollback-control",
        lease_owner="worker-rollback-control",
        response_sha256=response_sha256,
        delivery_kind="deferred",
        event_batch=event_batch,
        run_update=None,
    )
    first_id = spool.confirm_control_delivery(
        platform="telegram",
        chat_id="private-chat",
        platform_message_id="rollback-control",
        response_sha256=response_sha256,
        delivery_kind="deferred",
    )
    original_canonical_json = spool_module._canonical_json
    canonical_count = 0

    def fail_between_outbox_and_metadata(value):
        nonlocal canonical_count
        canonical_count += 1
        if canonical_count == 2:
            raise RuntimeError("fault between canonical lineage copies")
        return original_canonical_json(value)

    monkeypatch.setattr(
        spool_module, "_canonical_json", fail_between_outbox_and_metadata
    )
    with pytest.raises(RuntimeError, match="^fault between canonical lineage copies$"):
        spool.rebind_pending_session_parent("session-1", None)
    monkeypatch.setattr(spool_module, "_canonical_json", original_canonical_json)

    staged = spool.get_final_delivery(
        platform="telegram",
        chat_id="private-chat",
        platform_message_id="rollback-control",
    )
    confirmed = spool.get_record("run:run-rollback-control:control:deferred")
    assert staged is not None
    assert confirmed is not None
    assert staged["event_batch"]["parent_hermes_session_id"] == "missing-parent"
    assert (
        confirmed.payload["event_batch"]["parent_hermes_session_id"] == "missing-parent"
    )
    assert (
        spool.confirm_control_delivery(
            platform="telegram",
            chat_id="private-chat",
            platform_message_id="rollback-control",
            response_sha256=response_sha256,
            delivery_kind="deferred",
        )
        == first_id
    )


@pytest.mark.parametrize(
    ("source", "secret"),
    [
        ("my password is hunter2plus", "hunter2plus"),
        ("client secret is supersecretvalue", "supersecretvalue"),
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("authorization: Token opaque-credential-value", "opaque-credential-value"),
    ],
)
def test_natural_language_credentials_never_reach_spool(
    tmp_path: Path,
    source: str,
    secret: str,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, run_start = _bundle()
    event_batch["events"][0]["content"] = source
    spool.enqueue_inbound(
        event_batch,
        run_start,
        source_key="inbound:natural",
    )
    spool.close()

    database_bytes = (tmp_path / "sydney_spool.db").read_bytes()
    wal_path = tmp_path / "sydney_spool.db-wal"
    if wal_path.exists():
        database_bytes += wal_path.read_bytes()
    assert secret.encode() not in database_bytes


@pytest.mark.parametrize(
    ("source", "secret_tail"),
    [
        ('password="correct horse battery staple"; note=keep', "horse battery staple"),
        ("client secret='alpha beta gamma delta'; note=keep", "beta gamma delta"),
    ],
)
def test_multiword_quoted_credentials_never_reach_spool_storage(
    tmp_path: Path,
    source: str,
    secret_tail: str,
) -> None:
    spool_path = tmp_path / "sydney_spool.db"
    spool = SydneySpool(spool_path)
    event_batch, run_start = _bundle()
    event_batch["events"][0]["content"] = source
    spool.enqueue_inbound(
        event_batch,
        run_start,
        source_key="inbound:quoted-multiword",
    )
    spool.close()

    database_bytes = spool_path.read_bytes()
    wal_path = spool_path.with_name(f"{spool_path.name}-wal")
    if wal_path.exists():
        database_bytes += wal_path.read_bytes()
    assert secret_tail.encode() not in database_bytes


def test_configured_runtime_secrets_never_reach_spool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_secret = "opaque-runtime-secret-that-has-no-structural-prefix"
    monkeypatch.setenv("GEMINI_API_KEY", configured_secret)
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, run_start = _bundle()
    event_batch["events"][0]["content"] = (
        f"The configured value is {configured_secret}; retain everything else."
    )
    spool.enqueue_inbound(
        event_batch, run_start, source_key="inbound:configured-secret"
    )
    spool.close()

    database_bytes = (tmp_path / "sydney_spool.db").read_bytes()
    wal_path = tmp_path / "sydney_spool.db-wal"
    if wal_path.exists():
        database_bytes += wal_path.read_bytes()
    assert configured_secret.encode() not in database_bytes


def test_nested_encoded_login_redirect_secrets_never_reach_spool() -> None:
    secrets = (
        "direct-code-value",
        "nested-code-value",
        "nested-state-value",
        "nested-signature-value",
    )
    source = (
        "https://www.soldwithsweeney.com/login?proposal_id=proposal-7&"
        f"code={secrets[0]}&return_to=https%3A%2F%2Fauth.example.test%2Fcallback%3F"
        f"code%3D{secrets[1]}%26state%3D{secrets[2]}&payload=%7B%22redirect%22%3A"
        "%22https%3A%2F%2Fauth.example.test%2Fcallback%3Fsignature%3D"
        f"{secrets[3]}%22%7D"
    )

    redacted = redact_text(source)

    assert all(secret not in redacted for secret in secrets)
    assert "proposal_id=proposal-7" in redacted
    assert redacted.count("REDACTED") >= 4


def test_ordered_bounded_drain_acknowledges_only_successful_delivery(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    for index in range(4):
        spool.enqueue(
            kind="event_batch",
            source_key=f"event:{index}",
            payload={"index": index},
        )

    delivered: list[int] = []

    def handler(record):
        delivered.append(record.payload["index"])
        if record.payload["index"] == 1:
            raise TimeoutError("backend unavailable")
        return {"receipt": record.payload["index"]}

    result = spool.drain(handler, limit=3)

    assert delivered == [0, 1]
    assert result.acknowledged == 1
    assert result.failed == 1
    assert [item.payload["index"] for item in spool.pending(limit=10)] == [1, 2, 3]
    assert spool.get_record("event:0").receipt == {"receipt": 0}
    assert spool.get_record("event:1").attempt_count == 1


def test_spool_record_tolerates_a_legacy_null_attempt_count(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    spool.enqueue(
        kind="event_batch",
        source_key="event:legacy-null-attempt",
        payload={"index": 1},
    )
    row = spool.connection.execute(
        """
        SELECT id, kind, source_key, payload_json, state,
               NULL AS attempt_count, created_at, last_attempt_at,
               acknowledged_at, receipt_json
        FROM outbox
        WHERE source_key='event:legacy-null-attempt'
        """
    ).fetchone()

    assert row is not None
    assert SydneySpool._record(row).attempt_count == 0


def test_concurrent_spool_instances_deliver_each_pending_record_once(
    tmp_path: Path,
) -> None:
    spool_path = tmp_path / "sydney_spool.db"
    first = SydneySpool(spool_path)
    second = SydneySpool(spool_path)
    first.enqueue(
        kind="tool_before_bundle",
        source_key="tool:run-1:call-1:before",
        payload={"tool_start": {"run_id": "run-1"}},
    )
    entered = Event()
    release = Event()
    calls: list[int] = []
    calls_lock = Lock()
    results = []

    def handler(record):
        with calls_lock:
            calls.append(record.id)
        entered.set()
        release.wait(timeout=2)
        return {"decision": "execute"}

    def drain(spool: SydneySpool) -> None:
        results.append(spool.drain(handler, limit=1))

    first_thread = Thread(target=drain, args=(first,))
    second_thread = Thread(target=drain, args=(second,))
    first_thread.start()
    assert entered.wait(timeout=1)
    second_thread.start()
    try:
        time.sleep(0.1)
        observed_while_first_delivery_was_open = len(calls)
    finally:
        release.set()
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)
        first.close()
        second.close()

    assert first_thread.is_alive() is False
    assert second_thread.is_alive() is False
    assert observed_while_first_delivery_was_open == 1
    assert calls == [calls[0]]
    assert sum(result.acknowledged for result in results) == 1


def test_crash_reopen_recovers_and_drains_once(tmp_path: Path) -> None:
    spool_path = tmp_path / "sydney_spool.db"
    script = textwrap.dedent(
        f"""
        import os, sys
        sys.path.insert(0, {str(OVERLAY)!r})
        from sydney_spool import SydneySpool
        spool = SydneySpool({str(spool_path)!r})
        spool.enqueue(kind='event_batch', source_key='crash:1', payload={{'value': 1}})
        os._exit(23)
        """
    )
    completed = subprocess.run([sys.executable, "-c", script], check=False)
    assert completed.returncode == 23

    reopened = SydneySpool(spool_path)
    calls: list[str] = []
    reopened.drain(lambda record: calls.append(record.source_key) or {"ok": True})
    reopened.drain(lambda record: calls.append(record.source_key) or {"ok": True})
    assert calls == ["crash:1"]
    assert reopened.pending_count == 0


def test_final_delivery_attempt_survives_reopen_until_explicit_resolution(
    tmp_path: Path,
) -> None:
    spool_path = tmp_path / "sydney_spool.db"
    spool = SydneySpool(spool_path)
    spool.stage_final_delivery(
        platform="telegram",
        chat_id="private-chat",
        platform_message_id="message-1",
        run_id="run-1",
        lease_owner="worker-1",
        response_sha256="a" * 64,
    )
    spool.close()

    reopened = SydneySpool(spool_path)
    attempt = reopened.get_final_delivery(
        platform="telegram",
        chat_id="private-chat",
        platform_message_id="message-1",
    )
    assert attempt == {
        "lease_owner": "worker-1",
        "response_sha256": "a" * 64,
        "run_id": "run-1",
        "staged_at": attempt["staged_at"],
    }
    reopened.clear_final_delivery(
        platform="telegram",
        chat_id="private-chat",
        platform_message_id="message-1",
    )
    assert (
        reopened.get_final_delivery(
            platform="telegram",
            chat_id="private-chat",
            platform_message_id="message-1",
        )
        is None
    )


def test_tool_records_cache_lineage_and_cursor_survive_reopen(tmp_path: Path) -> None:
    spool_path = tmp_path / "sydney_spool.db"
    spool = SydneySpool(spool_path)
    before_id = spool.enqueue_tool_before(
        run_id="run-1",
        lease_owner="atlas-one",
        tool_call_id="call-1",
        tool_name="command_contacts_search",
        arguments={"query": "Brandon"},
        side_effect_class="read_only",
    )
    after_id = spool.enqueue_tool_after(
        run_id="run-1",
        lease_owner="atlas-one",
        tool_call_id="call-1",
        state="succeeded",
        result_event_id="22222222-2222-4222-8222-222222222222",
    )
    spool.rotate_session(
        session_id="session-2",
        logical_conversation_id="11111111-1111-4111-8111-111111111111",
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        parent_session_id="session-1",
        continuation_reason="compression",
    )
    packet = {
        "rendered_context": "source-linked context",
        "estimated_tokens": 5,
        "sections": [{"source_event_ids": ["source-1"]}],
    }
    spool.cache_context("session-2", packet)
    spool.set_reconciliation_cursor("session-2", 8, "ordered-hash")
    spool.close()

    reopened = SydneySpool(spool_path)
    assert before_id != after_id
    assert [record.kind for record in reopened.pending(limit=10)] == [
        "tool_before",
        "tool_after",
    ]
    assert reopened.get_session("session-2")["parent_session_id"] == "session-1"
    assert reopened.get_cached_context("session-2") == packet
    assert reopened.get_reconciliation_cursor("session-2") == {
        "event_count": 8,
        "ordered_hash": "ordered-hash",
    }


def test_latest_cached_context_is_scoped_to_one_logical_conversation(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    for session_id, logical_id in (
        ("session-private", "11111111-1111-4111-8111-111111111111"),
        ("session-other", "22222222-2222-4222-8222-222222222222"),
    ):
        spool.rotate_session(
            session_id=session_id,
            logical_conversation_id=logical_id,
            platform="telegram",
            external_user_id="brandon",
            external_chat_id=f"chat-{session_id}",
        )
    private_packet = {"rendered_context": "private conversation"}
    other_packet = {"rendered_context": "other conversation"}
    spool.cache_context("session-private", private_packet)
    spool.cache_context("session-other", other_packet)

    assert (
        spool.get_latest_cached_context(
            logical_conversation_id="11111111-1111-4111-8111-111111111111"
        )
        == private_packet
    )
    assert (
        spool.get_latest_cached_context(
            logical_conversation_id="33333333-3333-4333-8333-333333333333"
        )
        is None
    )


def test_reconciled_session_compacts_payloads_to_fixed_tombstones(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, _run_start = _bundle()
    record_id = spool.enqueue(
        kind="event_batch",
        source_key="event:old-session:1",
        payload=event_batch,
    )
    event_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    receipt = {
        "identity_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "session_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "event_ids": [event_id],
        "event_receipts": [
            {
                "event_id": event_id,
                "event_type": "user",
                "occurred_at": event_batch["events"][0]["occurred_at"],
                "content_sha256": hashlib.sha256(
                    event_batch["events"][0]["content"].encode()
                ).hexdigest(),
            }
        ],
    }
    spool.acknowledge(record_id, receipt)
    expectation = spool.reconciliation_expectations()["session-1"]
    spool.set_reconciliation_cursor(
        "session-1",
        expectation["expected_event_count"],
        expectation["expected_ordered_hash"],
    )

    assert spool.compact_reconciled_session("session-1") == 1
    assert spool.connection.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
    tombstone = spool.get_record("event:old-session:1")
    assert tombstone is not None
    assert tombstone.payload == {}
    assert tombstone.receipt == {"compacted": True}
    assert (
        spool.enqueue(
            kind="event_batch",
            source_key="event:old-session:1",
            payload=event_batch,
        )
        == record_id
    )
    changed = json.loads(json.dumps(event_batch))
    changed["events"][0]["content"] = "different replay"
    with pytest.raises(SpoolConflict):
        spool.enqueue(
            kind="event_batch",
            source_key="event:old-session:1",
            payload=changed,
        )

    tables = {
        row[0]
        for row in spool.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "outbox_tombstones" in tables


def test_compaction_retains_each_unresolved_inbound_run_independently(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    run_ids = (
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    )
    message_ids = ("message-a", "message-b")

    for index, (run_id, message_id) in enumerate(zip(run_ids, message_ids)):
        event_batch, run_start = _bundle(message_id)
        event_batch["events"][0]["occurred_at"] = f"2026-08-25T12:0{index}:00+00:00"
        local_id = spool.enqueue_inbound(
            event_batch,
            run_start,
            source_key=f"inbound:telegram:private-chat:{message_id}",
        )
        event = event_batch["events"][0]
        event_id = f"{index + 1:08x}-1111-4111-8111-111111111111"
        spool.acknowledge(
            local_id,
            {
                "ingest": {
                    "identity_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                    "session_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                    "event_ids": [event_id],
                    "event_receipts": [
                        {
                            "event_id": event_id,
                            "event_type": event["event_type"],
                            "occurred_at": event["occurred_at"],
                            "content_sha256": hashlib.sha256(
                                event["content"].encode()
                            ).hexdigest(),
                        }
                    ],
                },
                "run": {"run": {"id": run_id, "state": "queued"}},
                "claim": {"runs": []},
            },
        )

    expectation = spool.reconciliation_expectations()["session-1"]
    spool.set_reconciliation_cursor(
        "session-1",
        expectation["expected_event_count"],
        expectation["expected_ordered_hash"],
    )

    spool.mark_run_terminal(run_ids[0], state="succeeded")
    assert spool.compact_reconciled_session("session-1") == 1
    assert (
        spool.get_record(f"inbound:telegram:private-chat:{message_ids[0]}").payload
        == {}
    )
    unresolved = spool.find_inbound(message_ids[1])
    assert unresolved is not None
    assert unresolved.payload["run_start"]["platform_message_id"] == message_ids[1]

    spool.mark_run_terminal(run_ids[1], state="terminal_failure")
    assert spool.compact_reconciled_session("session-1") == 1
    assert (
        spool.get_record(f"inbound:telegram:private-chat:{message_ids[1]}").payload
        == {}
    )


def test_compacted_reconciliation_proof_accepts_later_session_events(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, _run_start = _bundle()
    receipts: list[dict[str, str]] = []
    for index in range(2):
        batch = json.loads(json.dumps(event_batch))
        batch["events"][0]["source_event_key"] = f"session-1:event-{index}"
        batch["events"][0]["occurred_at"] = f"2026-08-25T12:0{index}:00+00:00"
        batch["events"][0]["content"] = f"Durable event {index}"
        event_receipt = {
            "event_id": f"{index + 1:08x}-1111-4111-8111-111111111111",
            "event_type": "user",
            "occurred_at": batch["events"][0]["occurred_at"],
            "content_sha256": hashlib.sha256(
                batch["events"][0]["content"].encode()
            ).hexdigest(),
        }
        receipts.append(event_receipt)
        record_id = spool.enqueue(
            kind="event_batch",
            source_key=f"event:session-1:{index}",
            payload=batch,
        )
        spool.acknowledge(
            record_id,
            {
                "identity_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "session_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                "event_ids": [event_receipt["event_id"]],
                "event_receipts": [event_receipt],
            },
        )
        expectation = spool.reconciliation_expectations()["session-1"]
        assert expectation["expected_event_count"] == index + 1
        assert expectation["expected_ordered_hash"] == ordered_reconciliation_hash(
            receipts
        )
        spool.set_reconciliation_cursor(
            "session-1",
            expectation["expected_event_count"],
            expectation["expected_ordered_hash"],
        )
        assert spool.compact_reconciled_session("session-1") == 1

    assert (
        spool.connection.execute(
            "SELECT count(*) FROM reconciliation_events WHERE session_id='session-1'"
        ).fetchone()[0]
        == 2
    )
    assert spool.connection.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0


def test_spool_never_creates_token_columns_or_persists_environment_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_CONTROL_TOKEN", "environment-only-token")
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    spool.enqueue(kind="event_batch", source_key="safe:1", payload={"ok": True})
    columns = {
        row[1]
        for table in ("spool_meta", "session_lineage", "outbox", "context_cache")
        for row in spool.connection.execute(f"PRAGMA table_info({table})")
    }
    spool.close()
    assert not any(
        "token" in column.lower() or "authorization" in column.lower()
        for column in columns
    )
    assert b"environment-only-token" not in (tmp_path / "sydney_spool.db").read_bytes()
