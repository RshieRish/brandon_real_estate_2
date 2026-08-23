from __future__ import annotations

import asyncio
import base64
import threading
import time
import traceback
from dataclasses import is_dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient


class _Response:
    def __init__(self, payload: dict[str, Any] | None = None, *, error: Exception | None = None):
        self.payload = payload or {}
        self.error = error
        self.retry_values: list[int] = []

    def execute(self, *, num_retries: int = -1) -> dict[str, Any]:
        self.retry_values.append(num_retries)
        if self.error is not None:
            raise self.error
        return self.payload


class _Users:
    def __init__(self, responses: dict[str, _Response]):
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def getProfile(self, **kwargs: Any) -> _Response:
        self.calls.append(("profile", kwargs))
        return self.responses["profile"]

    def history(self) -> "_Users":
        return self

    def list(self, **kwargs: Any) -> _Response:
        if "startHistoryId" in kwargs:
            self.calls.append(("history", kwargs))
            return self.responses["history"]
        self.calls.append(("messages_list", kwargs))
        return self.responses["messages_list"]

    def messages(self) -> "_Users":
        return self

    def get(self, **kwargs: Any) -> _Response:
        self.calls.append(("message", kwargs))
        key = "message_full" if kwargs.get("format") == "full" else "message_metadata"
        return self.responses[key]


class _Gmail:
    def __init__(self, responses: dict[str, _Response]):
        self.users_api = _Users(responses)
        self._http = type("HTTP", (), {"timeout": None})()

    def users(self) -> _Users:
        return self.users_api


class _ProviderError(RuntimeError):
    def __init__(self, status: int, text: str, *, content: bytes | None = None):
        super().__init__(text)
        self.resp = type("Resp", (), {"status": status})()
        self.content = content


def _responses() -> dict[str, _Response]:
    return {
        "profile": _Response(
            {"emailAddress": "Brandon@SoldWithSweeney.com", "historyId": "900"}
        ),
        "history": _Response(
            {
                "historyId": "903",
                "nextPageToken": "next-token",
                "history": [
                    {
                        "id": "901",
                        "messagesAdded": [
                            {"message": {"id": "message-1", "threadId": "thread-1"}}
                        ],
                    },
                    {
                        "id": "902",
                        "messages": [
                            {"id": "message-1", "threadId": "thread-1"},
                            {"id": "message-2", "threadId": "thread-2"},
                        ],
                    },
                ],
            }
        ),
        "message_metadata": _Response(
            {
                "id": "message-1",
                "threadId": "thread-1",
                "labelIds": ["INBOX"],
                "internalDate": "1787328000000",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Showing follow-up"},
                        {"name": "From", "value": "Jane <jane@example.test>"},
                        {"name": "To", "value": "Brandon <brandon@soldwithsweeney.com>"},
                    ]
                },
            }
        ),
        "message_full": _Response(
            {
                "id": "message-1",
                "threadId": "thread-1",
                "labelIds": ["INBOX"],
                "internalDate": "1787328000000",
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "Subject", "value": "Showing follow-up"},
                        {"name": "From", "value": "Jane <jane@example.test>"},
                        {"name": "To", "value": "Brandon <brandon@soldwithsweeney.com>"},
                    ],
                    "body": {"data": "UGxlYXNlIGNhbGwgbWUgdG9tb3Jyb3cu"},
                },
            }
        ),
    }


async def test_adapter_returns_typed_profile_history_metadata_and_content() -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter
    from services.integration_health_service import BoundedProviderExecutor

    responses = _responses()
    gmail = _Gmail(responses)
    executor = BoundedProviderExecutor(max_workers=2)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: gmail,
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        profile = await adapter.get_profile(account_key="account-1")
        page = await adapter.list_history(
            account_key="account-1",
            start_history_id="900",
            page_token=None,
        )
        metadata = await adapter.get_message_metadata(
            account_key="account-1",
            message_id="message-1",
        )
        content = await adapter.get_message_content(
            account_key="account-1",
            message_id="message-1",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert is_dataclass(profile)
    assert profile.email_address == "brandon@soldwithsweeney.com"
    assert profile.history_id == "900"
    assert page.history_id == "903"
    assert page.next_page_token == "next-token"
    assert page.discovered_history_id_min == "901"
    assert page.discovered_history_id_max == "902"
    assert [(item.message_id, item.thread_id) for item in page.messages] == [
        ("message-1", "thread-1"),
        ("message-2", "thread-2"),
    ]
    assert metadata.message_id == "message-1"
    assert metadata.headers["subject"] == "Showing follow-up"
    assert metadata.label_ids == ("INBOX",)
    assert content.body_text == "Please call me tomorrow."
    assert content.body_transport_compatible is True
    assert "Please call me tomorrow." not in repr(content)
    assert content.headers == metadata.headers
    assert gmail._http.timeout == 0.25
    assert all(
        response.retry_values == [0]
        for response in responses.values()
    )

    assert gmail.users_api.calls == [
        ("profile", {"userId": "me"}),
        (
            "history",
            {
                "userId": "me",
                "startHistoryId": "900",
                "pageToken": None,
                "historyTypes": ["messageAdded"],
                "maxResults": 500,
            },
        ),
        (
            "message",
            {
                "userId": "me",
                "id": "message-1",
                "format": "metadata",
                "metadataHeaders": [
                    "Subject",
                    "From",
                    "To",
                    "Cc",
                    "Bcc",
                    "Date",
                    "Auto-Submitted",
                    "Precedence",
                    "List-Id",
                ],
            },
        ),
        (
            "message",
            {"userId": "me", "id": "message-1", "format": "full"},
        ),
    ]


async def test_adapter_accepts_terminal_no_change_page_and_prefers_nested_plain_text() -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter
    from services.integration_health_service import BoundedProviderExecutor

    responses = _responses()
    responses["history"] = _Response({"historyId": "904"})
    responses["message_full"] = _Response(
        {
            "id": "message-nested",
            "threadId": "thread-nested",
            "labelIds": ["INBOX"],
            "internalDate": "1787328000000",
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [
                    {"name": "Subject", "value": "Nested"},
                    {"name": "From", "value": "client@example.test"},
                    {"name": "To", "value": "brandon@example.test"},
                ],
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "parts": [
                            {
                                "mimeType": "text/html",
                                "body": {
                                    "data": "PHA-SFRNTCBvbmx5PC9wPg"
                                },
                            },
                            {
                                "mimeType": "text/plain",
                                # Gmail base64url data commonly omits padding.
                                "body": {"data": "UGxhaW4gYm9keQ"},
                            },
                        ],
                    },
                    {
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "attachment-not-fetched"},
                    },
                ],
            },
        }
    )
    gmail = _Gmail(responses)
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: gmail,
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        page = await adapter.list_history(
            account_key="account-nested",
            start_history_id="903",
            page_token=None,
        )
        content = await adapter.get_message_content(
            account_key="account-nested",
            message_id="message-nested",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert page.history_id == "904"
    assert page.next_page_token is None
    assert page.messages == ()
    assert page.discovered_history_id_min is None
    assert page.discovered_history_id_max is None
    assert content.body_text == "Plain body"
    assert "HTML only" not in content.body_text


@pytest.mark.parametrize("attachment_first", [True, False])
async def test_full_message_skips_text_attachments_before_body_selection(
    attachment_first: bool,
) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter
    from services.integration_health_service import BoundedProviderExecutor

    attachment = {
        "mimeType": "text/plain",
        "filename": "private-notes.txt",
        "headers": [
            {"name": "Content-Disposition", "value": "attachment; filename=notes.txt"}
        ],
        # Deliberately malformed: skipped attachments must never be decoded.
        "body": {"data": "attachment-private-canary $$$"},
    }
    body = {
        "mimeType": "text/plain",
        "filename": "",
        "headers": [{"name": "Content-Disposition", "value": "inline"}],
        "body": {"data": "QWN0dWFsIG1lc3NhZ2UgYm9keQ"},
    }
    parts = [attachment, body] if attachment_first else [body, attachment]
    responses = _responses()
    responses["message_full"] = _Response(
        {
            "id": "message-with-text-attachment",
            "threadId": "thread-with-text-attachment",
            "labelIds": ["INBOX"],
            "internalDate": "1787328000000",
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [],
                "parts": parts,
            },
        }
    )
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        content = await adapter.get_message_content(
            account_key="account-text-attachment",
            message_id="message-with-text-attachment",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert content.body_text == "Actual message body"
    assert "attachment-private-canary" not in repr(content)


@pytest.mark.parametrize(
    ("parts", "expected_body"),
    [
        (
            (
                ("text/plain", "   \n\t"),
                ("text/html", "<p>Actionable HTML body</p>"),
            ),
            "<p>Actionable HTML body</p>",
        ),
        (
            (
                ("text/plain", "\n \t"),
                ("text/plain", "Substantive later plain"),
            ),
            "Substantive later plain",
        ),
    ],
)
async def test_full_message_ignores_blank_plain_before_substantive_body(
    parts: tuple[tuple[str, str], ...],
    expected_body: str,
) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter
    from services.integration_health_service import BoundedProviderExecutor

    def encoded(value: str) -> str:
        return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")

    responses = _responses()
    responses["message_full"] = _Response(
        {
            "id": "message-blank-plain-fallback",
            "threadId": "thread-blank-plain-fallback",
            "labelIds": ["INBOX"],
            "internalDate": "1787328000000",
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [],
                "parts": [
                    {
                        "mimeType": mime_type,
                        "body": {"data": encoded(value)},
                    }
                    for mime_type, value in parts
                ],
            },
        }
    )
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        content = await adapter.get_message_content(
            account_key="account-blank-plain-fallback",
            message_id="message-blank-plain-fallback",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert content.body_text == expected_body
    assert content.body_transport_compatible is False


async def test_adapter_preserves_recipient_occurrences_and_all_automation_signals() -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter
    from services.integration_health_service import BoundedProviderExecutor

    responses = _responses()
    responses["message_metadata"] = _Response(
        {
            "id": "message-duplicate-recipients",
            "threadId": "thread-duplicate-recipients",
            "labelIds": ["SENT"],
            "internalDate": "1787328000000",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Exact envelope"},
                    {"name": "From", "value": "brandon@example.test"},
                    {"name": "To", "value": "client@example.test"},
                    {"name": "To", "value": "extra@example.test"},
                    {"name": "Cc", "value": "assistant@example.test"},
                    {"name": "Auto-Submitted", "value": "no"},
                    {"name": "Auto-Submitted", "value": "auto-replied"},
                    {"name": "Precedence", "value": "normal"},
                    {"name": "Precedence", "value": "bulk"},
                    {"name": "List-Id", "value": ""},
                    {"name": "List-Id", "value": "list.example.test"},
                ]
            },
        }
    )
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        metadata = await adapter.get_message_metadata(
            account_key="duplicate-header-account",
            message_id="message-duplicate-recipients",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert metadata.headers["to"] == "client@example.test, extra@example.test"
    assert metadata.headers["cc"] == "assistant@example.test"
    assert metadata.headers["auto-submitted"] == "auto-replied"
    assert metadata.headers["precedence"] == "bulk"
    assert metadata.headers["list-id"] == "list.example.test"


@pytest.mark.parametrize("singleton", ["From", "Subject"])
async def test_adapter_rejects_duplicate_singleton_envelope_headers(
    singleton: str,
) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    responses = _responses()
    headers = list(responses["message_metadata"].payload["payload"]["headers"])
    headers.append({"name": singleton, "value": "masked-extra-value"})
    responses["message_metadata"].payload["payload"]["headers"] = headers
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        with pytest.raises(GmailProviderFailure) as raised:
            await adapter.get_message_metadata(
                account_key="duplicate-singleton-account",
                message_id="message-1",
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert raised.value.category == "malformed_provider"
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    "parts",
    [
        (
            ("text/plain", "Exact intended body"),
            ("text/plain", "Extra recipient-visible body"),
        ),
        (
            ("text/plain", "Exact intended body"),
            ("text/html", "<p>Divergent recipient-visible body</p>"),
        ),
    ],
)
async def test_adapter_marks_ambiguous_multipart_body_ineligible_for_send_proof(
    parts: tuple[tuple[str, str], ...],
) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter
    from services.integration_health_service import BoundedProviderExecutor

    def encoded(value: str) -> str:
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    responses = _responses()
    responses["message_full"] = _Response(
        {
            "id": "ambiguous-message",
            "threadId": "ambiguous-thread",
            "labelIds": ["SENT"],
            "internalDate": "1787328000000",
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [
                    {"name": "Subject", "value": "Ambiguous"},
                    {"name": "From", "value": "brandon@example.test"},
                    {"name": "To", "value": "client@example.test"},
                ],
                "parts": [
                    {"mimeType": mime_type, "body": {"data": encoded(value)}}
                    for mime_type, value in parts
                ],
            },
        }
    )
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        content = await adapter.get_message_content(
            account_key="ambiguous-body-account",
            message_id="ambiguous-message",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert content.body_text == "Exact intended body"
    assert content.body_transport_compatible is False


@pytest.mark.parametrize(
    ("mime_type", "body", "expected"),
    [
        (
            "text/plain",
            "Call <Jane> tomorrow at <client@example.com>.",
            "Call <Jane> tomorrow at <client@example.com>.",
        ),
        (
            "text/html",
            "<p>Call <b>Jane</b> at &lt;client@example.com&gt;.</p>",
            "Call Jane at <client@example.com>.",
        ),
    ],
)
async def test_adapter_to_sanitizer_preserves_plain_angles_and_strips_html_once(
    mime_type: str,
    body: str,
    expected: str,
) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter
    from services.gmail_message_sanitizer import sanitize_gmail_message
    from services.integration_health_service import BoundedProviderExecutor

    encoded = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    responses = _responses()
    responses["message_full"] = _Response(
        {
            "id": "body-media-type-message",
            "threadId": "body-media-type-thread",
            "labelIds": ["INBOX"],
            "internalDate": "1787328000000",
            "payload": {
                "mimeType": mime_type,
                "headers": [
                    {"name": "Subject", "value": "Body fidelity"},
                    {"name": "From", "value": "client@example.test"},
                    {"name": "To", "value": "brandon@example.test"},
                ],
                "body": {"data": encoded},
            },
        }
    )
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        content = await adapter.get_message_content(
            account_key="body-media-type-account",
            message_id="body-media-type-message",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert content.body_media_type == mime_type
    sanitized = sanitize_gmail_message(
        content,
        mailbox_email="brandon@example.test",
        participant_hash_key=b"0123456789abcdef0123456789abcdef",
    )
    assert sanitized.transient_body_text == expected


async def test_adapter_to_sanitizer_does_not_choose_one_of_multiple_from_addresses(
) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter
    from services.gmail_message_sanitizer import sanitize_gmail_message
    from services.integration_health_service import BoundedProviderExecutor

    body = "Please schedule the inspection."
    encoded = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    responses = _responses()
    responses["message_full"] = _Response(
        {
            "id": "multiple-from-message",
            "threadId": "multiple-from-thread",
            "labelIds": ["INBOX"],
            "internalDate": "1787328000000",
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "Subject", "value": "Inspection request"},
                    {
                        "name": "From",
                        "value": (
                            "Alice <alice@example.test>, "
                            "Bob <bob@example.test>"
                        ),
                    },
                    {"name": "To", "value": "brandon@example.test"},
                ],
                "body": {"data": encoded},
            },
        }
    )
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        content = await adapter.get_message_content(
            account_key="multiple-from-account",
            message_id="multiple-from-message",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    sanitized = sanitize_gmail_message(
        content,
        mailbox_email="brandon@example.test",
        participant_hash_key=b"0123456789abcdef0123456789abcdef",
    )

    assert sanitized.sender_hmac is None
    assert "alice@example.test" not in repr(sanitized)
    assert "bob@example.test" not in repr(sanitized)


@pytest.mark.parametrize(
    "invalid_history_id",
    [
        "",
        "0",
        " 900",
        "+900",
        "0900",
        "٩٠٠",
        str(2**64),
        "not-numeric",
    ],
)
async def test_adapter_rejects_noncanonical_profile_history_ids(
    invalid_history_id: str,
) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    responses = _responses()
    responses["profile"] = _Response(
        {
            "emailAddress": "brandon@example.test",
            "historyId": invalid_history_id,
        }
    )
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        with pytest.raises(GmailProviderFailure) as raised:
            await adapter.get_profile(account_key="invalid-profile-history-id")
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert raised.value.category == "malformed_provider"
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    "history_payload",
    [
        {"historyId": "899", "history": []},
        {"historyId": "901", "history": [{"id": "900"}]},
        {"historyId": "901", "history": [{"id": "902"}]},
        {"historyId": str(2**64), "history": []},
        {"historyId": "901", "history": [{"id": "01"}]},
    ],
)
async def test_adapter_rejects_nonmonotone_or_invalid_history_pages(
    history_payload: dict[str, Any],
) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    responses = _responses()
    responses["history"] = _Response(history_payload)
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        with pytest.raises(GmailProviderFailure) as raised:
            await adapter.list_history(
                account_key="invalid-history-page",
                start_history_id="900",
                page_token=None,
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert raised.value.category == "malformed_provider"
    assert raised.value.__cause__ is None


async def test_adapter_lists_bounded_backfill_window_with_typed_refs_and_zero_retries() -> None:
    from datetime import datetime, timezone

    from services.gmail_history_adapter import GmailHistoryAdapter
    from services.integration_health_service import BoundedProviderExecutor

    responses = _responses()
    responses["messages_list"] = _Response(
        {
            "messages": [
                {"id": "backfill-message-1", "threadId": "backfill-thread-1"},
                {"id": "backfill-message-2", "threadId": "backfill-thread-2"},
            ],
            "nextPageToken": "backfill-page-2",
            "resultSizeEstimate": 2,
        }
    )
    gmail = _Gmail(responses)
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: gmail,
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    start = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 21, 12, 0, 0, 100_000, tzinfo=timezone.utc)
    try:
        page = await adapter.list_messages_for_backfill(
            account_key="account-backfill",
            window_start=start,
            window_end=end,
            page_token=None,
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert [(item.message_id, item.thread_id) for item in page.messages] == [
        ("backfill-message-1", "backfill-thread-1"),
        ("backfill-message-2", "backfill-thread-2"),
    ]
    assert page.next_page_token == "backfill-page-2"
    assert gmail.users_api.calls == [
        (
            "messages_list",
            {
                "userId": "me",
                # Gmail's epoch bounds are strict. Query one second before an
                # aligned start for safe overfetch and ceil the exclusive end;
                # the service filters hydrated metadata back to [start, end).
                "q": "after:1786708799 before:1787313601",
                "pageToken": None,
                "includeSpamTrash": True,
                "maxResults": 500,
            },
        )
    ]
    assert responses["messages_list"].retry_values == [0]


def test_default_gmail_service_uses_explicit_socket_timeout_and_zero_retry_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.gmail_history_adapter as adapter_module
    from services.gmail_history_adapter import build_gmail_service

    calls: dict[str, Any] = {}
    credentials = object()
    raw_http = object()
    authorized_http = object()
    built_service = object()

    def credentials_factory(**kwargs):
        calls["credentials"] = kwargs
        return credentials

    def http_factory(*, timeout):
        calls["http_timeout"] = timeout
        return raw_http

    def authorized_factory(received_credentials, *, http, max_refresh_attempts):
        calls["authorized"] = (
            received_credentials,
            http,
            max_refresh_attempts,
        )
        return authorized_http

    def discovery_build(api, version, **kwargs):
        calls["build"] = (api, version, kwargs)
        return built_service

    monkeypatch.setattr(adapter_module, "Credentials", credentials_factory)
    monkeypatch.setattr(adapter_module, "_SingleAttemptHttp", http_factory)
    monkeypatch.setattr(
        adapter_module.google_auth_httplib2,
        "AuthorizedHttp",
        authorized_factory,
    )
    monkeypatch.setattr(adapter_module, "build", discovery_build)
    monkeypatch.setattr(
        adapter_module.socket,
        "setdefaulttimeout",
        lambda *_args: pytest.fail("global socket defaults must never be mutated"),
    )

    result = build_gmail_service(
        refresh_token="database-refresh-token-canary",
        client_id="workspace-client-id",
        client_secret="workspace-client-secret",
        socket_timeout_seconds=0.25,
    )

    assert result is built_service
    assert calls["credentials"] == {
        "token": None,
        "refresh_token": "database-refresh-token-canary",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "workspace-client-id",
        "client_secret": "workspace-client-secret",
    }
    assert calls["http_timeout"] == 0.25
    assert calls["authorized"] == (credentials, raw_http, 0)
    assert calls["build"] == (
        "gmail",
        "v1",
        {
            "http": authorized_http,
            "cache_discovery": False,
            "num_retries": 0,
        },
    )


@pytest.mark.parametrize(
    ("method", "failure_stage"),
    [
        ("POST", "request"),
        ("POST", "bad_status"),
        ("GET", "response_not_ready"),
    ],
)
def test_single_attempt_http_never_replays_an_ambiguous_post(
    method: str,
    failure_stage: str,
) -> None:
    import http.client

    from services.gmail_history_adapter import _SingleAttemptHttp

    class _Connection:
        sock = object()
        host = "gmail.googleapis.test"

        def __init__(self) -> None:
            self.request_calls = 0
            self.connect_calls = 0
            self.close_calls = 0

        def connect(self) -> None:
            self.connect_calls += 1
            self.sock = object()

        def close(self) -> None:
            self.close_calls += 1
            self.sock = None

        def request(self, *_args, **_kwargs) -> None:
            self.request_calls += 1
            if failure_stage == "request":
                raise http.client.CannotSendRequest("accepted-but-unknown")

        def getresponse(self):
            if failure_stage == "response_not_ready":
                raise http.client.ResponseNotReady("accepted-but-not-ready")
            raise http.client.BadStatusLine("accepted-but-no-status")

    connection = _Connection()
    transport = _SingleAttemptHttp(timeout=0.25)
    with pytest.raises(http.client.HTTPException):
        transport._conn_request(
            connection,
            "/gmail/v1/users/me/messages/send",
            method,
            b"private-wire-body",
            {"content-type": "application/json"},
        )

    assert connection.request_calls == 1
    assert connection.connect_calls == 0
    assert connection.close_calls == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401])
def test_single_attempt_http_does_not_follow_redirect_or_auth_challenge(
    status: int,
) -> None:
    from services.gmail_history_adapter import _SingleAttemptHttp

    calls = 0

    def one_response(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return (
            {"status": status, "location": "https://other.example.test/replay"},
            b"",
        )

    transport = _SingleAttemptHttp(timeout=0.25)
    transport._conn_request = one_response
    response, content = transport._request(
        object(),
        "gmail.googleapis.test",
        "https://gmail.googleapis.test/send",
        "/send",
        "POST",
        b"private-wire-body",
        {},
        5,
        None,
    )

    assert calls == 1
    assert response["status"] == status
    assert content == b""


@pytest.mark.parametrize(
    ("operation", "status", "category"),
    [
        ("profile", 401, "oauth_revoked"),
        ("history", 404, "history_cursor_expired"),
        ("message_metadata", 404, "message_not_found"),
        ("history", 429, "rate_limited"),
        ("history", 503, "transient_provider"),
    ],
)
async def test_adapter_classifies_provider_failures_without_exposing_raw_errors(
    operation: str,
    status: int,
    category: str,
) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    secret = "private-bearer-and-client@example.test"
    responses = _responses()
    responses[operation] = _Response(error=_ProviderError(status, secret))
    gmail = _Gmail(responses)
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: gmail,
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        with pytest.raises(GmailProviderFailure) as raised:
            if operation == "profile":
                await adapter.get_profile(account_key="account-1")
            elif operation == "history":
                await adapter.list_history(
                    account_key="account-1",
                    start_history_id="900",
                    page_token=None,
                )
            else:
                await adapter.get_message_metadata(
                    account_key="account-1",
                    message_id="message-1",
                )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert raised.value.category == category
    assert str(raised.value) == category
    assert secret not in repr(raised.value)
    assert secret not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__suppress_context__ is True


@pytest.mark.parametrize(
    "reason",
    ["rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded"],
)
async def test_adapter_distinguishes_rate_limited_403_from_revoked_auth(
    reason: str,
) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    secret = "private-provider-payload@example.test"
    responses = _responses()
    responses["history"] = _Response(
        error=_ProviderError(
            403,
            secret,
            content=(
                b'{"error":{"errors":[{"reason":"'
                + reason.encode("ascii")
                + b'"}],"message":"'
                + secret.encode()
                + b'"}}'
            ),
        )
    )
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        with pytest.raises(GmailProviderFailure) as raised:
            await adapter.list_history(
                account_key="account-rate-limited",
                start_history_id="900",
                page_token=None,
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert raised.value.category == "rate_limited"
    assert secret not in repr(raised.value)


@pytest.mark.parametrize(
    ("reason", "category"),
    [
        ("insufficientPermissions", "oauth_revoked"),
        ("forbidden", "transient_provider"),
        ("domainPolicy", "transient_provider"),
    ],
)
async def test_adapter_only_treats_explicit_permission_403_as_revoked(
    reason: str,
    category: str,
) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    secret = "private-403-detail@example.test"
    responses = _responses()
    responses["profile"] = _Response(
        error=_ProviderError(
            403,
            secret,
            content=(
                b'{"error":{"errors":[{"reason":"'
                + reason.encode("ascii")
                + b'"}],"message":"'
                + secret.encode("ascii")
                + b'"}}'
            ),
        )
    )
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        with pytest.raises(GmailProviderFailure) as raised:
            await adapter.get_profile(account_key="account-forbidden")
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert raised.value.category == category
    assert secret not in repr(raised.value)


async def test_adapter_classifies_credential_refresh_failure_as_oauth_revoked() -> None:
    from google.auth.exceptions import RefreshError

    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    secret = "refresh-token-private-value"
    responses = _responses()
    responses["profile"] = _Response(error=RefreshError(secret))
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        with pytest.raises(GmailProviderFailure) as raised:
            await adapter.get_profile(account_key="account-refresh-failed")
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert raised.value.category == "oauth_revoked"
    assert secret not in repr(raised.value)


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("profile", {"emailAddress": "", "historyId": "900"}),
        ("profile", {"emailAddress": "valid@example.test", "historyId": ""}),
        ("history", {"history": "not-a-list", "historyId": "901"}),
        ("history", {"history": [], "historyId": ""}),
        ("message_metadata", {"id": "message-1", "threadId": ""}),
        ("message_full", {"id": "message-1", "threadId": "thread-1"}),
    ],
)
async def test_adapter_rejects_malformed_provider_payloads(
    operation: str,
    payload: dict[str, Any],
) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    responses = _responses()
    responses[operation] = _Response(payload)
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        with pytest.raises(GmailProviderFailure, match="malformed_provider"):
            if operation == "profile":
                await adapter.get_profile(account_key="account-1")
            elif operation == "history":
                await adapter.list_history(
                    account_key="account-1",
                    start_history_id="900",
                    page_token=None,
                )
            elif operation == "message_metadata":
                await adapter.get_message_metadata(
                    account_key="account-1",
                    message_id="message-1",
                )
            else:
                await adapter.get_message_content(
                    account_key="account-1",
                    message_id="message-1",
                )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        (
            "history",
            {
                "historyId": "901",
                "history": [
                    {
                        "id": "901",
                        "messagesAdded": [
                            {"message": {"id": "valid", "threadId": "thread"}},
                            {"message": {"id": "", "threadId": "bad-thread"}},
                        ],
                    }
                ],
            },
        ),
        (
            "history",
            {
                "historyId": "901",
                "history": [
                    {
                        "id": "901",
                        "messagesAdded": [
                            {
                                "message": {
                                    "id": "x" * 256,
                                    "threadId": "thread",
                                }
                            }
                        ],
                    }
                ],
            },
        ),
        (
            "history",
            {
                "historyId": "901",
                "history": [
                    {
                        "id": "901",
                        "messagesAdded": [
                            {
                                "message": {
                                    "id": "message with space",
                                    "threadId": "thread",
                                }
                            }
                        ],
                    }
                ],
            },
        ),
        (
            "history",
            {
                "historyId": "901",
                "history": [],
                "nextPageToken": "x" * 1025,
            },
        ),
        (
            "history",
            {
                "historyId": "901",
                "history": [
                    {
                        "id": "901",
                        "messagesAdded": [
                            {"message": {"threadId": "missing-message-id"}}
                        ],
                    }
                ],
            },
        ),
        (
            "history",
            {
                "historyId": "901",
                "history": [
                    {
                        "id": None,
                        "messagesAdded": [
                            {"message": {"id": "valid", "threadId": "thread"}}
                        ],
                    }
                ],
            },
        ),
        (
            "history",
            {
                "historyId": "901",
                "history": [
                    {
                        "messagesAdded": [
                            {"message": {"id": "message", "threadId": "thread"}}
                        ]
                    }
                ],
            },
        ),
        (
            "history",
            {
                "historyId": "901",
                "history": [
                    {
                        "id": "",
                        "messagesAdded": [
                            {"message": {"id": "message", "threadId": "thread"}}
                        ],
                    }
                ],
            },
        ),
        (
            "history",
            {
                "historyId": "901",
                "history": ["not-a-history-record"],
            },
        ),
        (
            "history",
            {
                "historyId": "901",
                "history": [
                    {
                        "id": "901",
                        "messagesAdded": [
                            {"message": {"id": 123, "threadId": "thread"}}
                        ],
                    }
                ],
            },
        ),
        (
            "history",
            {
                "historyId": "901",
                "history": [
                    {
                        "id": "901",
                        "messagesAdded": [
                            {"message": {"id": "message", "threadId": ""}}
                        ],
                    }
                ],
            },
        ),
        (
            "history",
            {
                "historyId": "901",
                "history": [
                    {
                        "id": "901",
                        "messagesAdded": [{"message": {"id": "message"}}],
                    }
                ],
            },
        ),
        (
            "history",
            {
                "historyId": "901",
                "history": [
                    {
                        "id": "901",
                        "messagesAdded": [
                            {"message": {"id": "message", "threadId": []}}
                        ],
                    }
                ],
            },
        ),
        (
            "messages_list",
            {
                "messages": [
                    {"id": "valid", "threadId": "thread"},
                    {"id": "", "threadId": "bad-thread"},
                ]
            },
        ),
        (
            "messages_list",
            {"messages": [{"id": "message", "threadId": None}]},
        ),
        (
            "messages_list",
            {"messages": [{"id": "message", "threadId": ""}]},
        ),
        (
            "messages_list",
            {"messages": [{"threadId": "missing-message-id"}]},
        ),
        (
            "messages_list",
            {"messages": [{"id": "message"}]},
        ),
        (
            "messages_list",
            {"messages": [{"id": {"not": "string"}, "threadId": "thread"}]},
        ),
        (
            "messages_list",
            {"messages": [{"id": "message", "threadId": "bad\nthread"}]},
        ),
        (
            "messages_list",
            {
                "messages": [{"id": "message", "threadId": "thread"}],
                "nextPageToken": "token with space",
            },
        ),
    ],
)
async def test_adapter_rejects_entire_page_for_malformed_message_reference(
    operation: str,
    payload: dict[str, Any],
) -> None:
    from datetime import datetime, timezone

    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    secret = "malformed-reference-provider-canary"
    payload = {**payload, "rawProviderDetail": secret}
    responses = _responses()
    responses[operation] = _Response(payload)
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        with pytest.raises(GmailProviderFailure) as raised:
            if operation == "history":
                await adapter.list_history(
                    account_key="malformed-ref-account",
                    start_history_id="900",
                    page_token=None,
                )
            else:
                await adapter.list_messages_for_backfill(
                    account_key="malformed-ref-account",
                    window_start=datetime(2026, 8, 20, tzinfo=timezone.utc),
                    window_end=datetime(2026, 8, 21, tzinfo=timezone.utc),
                    page_token=None,
                )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert raised.value.category == "malformed_provider"
    assert str(raised.value) == "malformed_provider"
    assert secret not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__suppress_context__ is True


@pytest.mark.parametrize(
    ("operation", "invalid_value"),
    [
        ("history", "token with space"),
        ("backfill", "x" * 1025),
        ("metadata", "bad\nmessage"),
        ("content", "x" * 256),
    ],
)
async def test_adapter_rejects_undurable_identifiers_before_provider_call(
    operation: str,
    invalid_value: str,
) -> None:
    from datetime import datetime, timezone

    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    provider_calls = 0

    def service_factory():
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("malformed durable identifiers must fail pre-provider")

    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=service_factory,
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        with pytest.raises(GmailProviderFailure, match="^malformed_provider$"):
            if operation == "history":
                await adapter.list_history(
                    account_key="invalid-input-account",
                    start_history_id="900",
                    page_token=invalid_value,
                )
            elif operation == "backfill":
                await adapter.list_messages_for_backfill(
                    account_key="invalid-input-account",
                    window_start=datetime(2026, 8, 20, tzinfo=timezone.utc),
                    window_end=datetime(2026, 8, 21, tzinfo=timezone.utc),
                    page_token=invalid_value,
                )
            elif operation == "metadata":
                await adapter.get_message_metadata(
                    account_key="invalid-input-account",
                    message_id=invalid_value,
                )
            else:
                await adapter.get_message_content(
                    account_key="invalid-input-account",
                    message_id=invalid_value,
                )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert provider_calls == 0


async def test_stalled_adapter_call_is_deadline_bounded_and_health_stays_responsive() -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import (
        BoundedProviderExecutor,
        ProviderJobStillRunning,
    )
    from workers.health_app import create_health_app

    release = threading.Event()
    started = threading.Event()
    response = _Response()

    def stalled_execute(*, num_retries: int = -1) -> dict[str, Any]:
        response.retry_values.append(num_retries)
        started.set()
        release.wait(timeout=5)
        return {"emailAddress": "brandon@example.test", "historyId": "900"}

    response.execute = stalled_execute  # type: ignore[method-assign]
    responses = _responses()
    responses["profile"] = response
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=0.05,
        socket_timeout_seconds=0.01,
    )
    client = TestClient(create_health_app(lambda: ("database",)))
    try:
        pending = asyncio.create_task(adapter.get_profile(account_key="account-1"))
        assert await asyncio.to_thread(started.wait, 1)
        started_at = time.monotonic()
        health = await asyncio.to_thread(client.get, "/health")
        assert time.monotonic() - started_at < 0.5
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "service": "integration-worker"}
        with pytest.raises(GmailProviderFailure) as timed_out:
            await pending
        assert timed_out.value.category == "provider_timeout"
        with pytest.raises(ProviderJobStillRunning, match="already_running"):
            await adapter.get_profile(account_key="account-1")
    finally:
        release.set()
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert response.retry_values == [0]


async def test_stalled_service_factory_is_off_loop_and_deadline_bounded() -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor
    from workers.health_app import create_health_app

    release = threading.Event()
    started = threading.Event()

    def stalled_factory():
        started.set()
        release.wait(timeout=5)
        return _Gmail(_responses())

    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=stalled_factory,
        deadline_seconds=0.05,
        socket_timeout_seconds=0.01,
    )
    client = TestClient(create_health_app(lambda: ("database",)))
    try:
        pending = asyncio.create_task(adapter.get_profile(account_key="factory-account"))
        assert await asyncio.to_thread(started.wait, 1)
        started_at = time.monotonic()
        health = await asyncio.to_thread(client.get, "/health")
        assert time.monotonic() - started_at < 0.5
        assert health.status_code == 200
        with pytest.raises(GmailProviderFailure) as raised:
            await pending
        assert raised.value.category == "provider_timeout"
    finally:
        release.set()
        await executor.wait_for_tracked_calls()
        executor.shutdown()


async def test_timed_out_operation_blocks_other_operations_for_same_account_only() -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import (
        BoundedProviderExecutor,
        ProviderJobStillRunning,
    )

    release = threading.Event()
    started = threading.Event()
    stalled_profile = _Response()

    def stalled_execute(*, num_retries: int = -1) -> dict[str, Any]:
        stalled_profile.retry_values.append(num_retries)
        started.set()
        release.wait(timeout=5)
        return {"emailAddress": "brandon@example.test", "historyId": "900"}

    stalled_profile.execute = stalled_execute  # type: ignore[method-assign]
    responses = _responses()
    responses["profile"] = stalled_profile
    executor = BoundedProviderExecutor(max_workers=2)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=0.05,
        socket_timeout_seconds=0.01,
    )
    try:
        pending = asyncio.create_task(adapter.get_profile(account_key="account-1"))
        assert await asyncio.to_thread(started.wait, 1)
        with pytest.raises(GmailProviderFailure, match="provider_timeout"):
            await pending

        with pytest.raises(ProviderJobStillRunning, match="already_running"):
            await adapter.list_history(
                account_key="account-1",
                start_history_id="900",
                page_token=None,
            )

        other_page = await adapter.list_history(
            account_key="account-2",
            start_history_id="900",
            page_token=None,
        )
        assert other_page.history_id == "903"
        assert responses["history"].retry_values == [0]
    finally:
        release.set()
        await executor.wait_for_tracked_calls()
        executor.shutdown()


async def test_network_timeout_is_classified_without_raw_exception_text() -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    responses = _responses()
    responses["profile"] = _Response(
        error=TimeoutError("socket timeout bearer-private@example.test")
    )
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.1,
    )
    try:
        with pytest.raises(GmailProviderFailure) as raised:
            await adapter.get_profile(account_key="account-timeout")
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()
    assert raised.value.category == "transient_provider"
    assert "private" not in repr(raised.value)


async def test_full_message_decoder_bounds_bytes_depth_and_part_count() -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    responses = _responses()
    responses["message_full"] = _Response(
        {
            "id": "message-bounded",
            "threadId": "thread-bounded",
            "labelIds": ["INBOX"],
            "internalDate": "1787328000000",
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [
                    {"name": "Subject", "value": "Bounded"},
                    {"name": "From", "value": "client@example.test"},
                    {"name": "To", "value": "brandon@example.test"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": "YWJjZGVmZ2hpams="},
                    }
                ],
            },
        }
    )
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.1,
        max_body_bytes=5,
        max_mime_depth=4,
        max_mime_parts=8,
    )
    try:
        content = await adapter.get_message_content(
            account_key="bounded-account", message_id="message-bounded"
        )
        assert content.body_text == "abcde"
        assert content.body_truncated is True

        deep_payload: dict[str, Any] = {
            "mimeType": "text/plain",
            "body": {"data": "YQ=="},
        }
        for _ in range(6):
            deep_payload = {"mimeType": "multipart/mixed", "parts": [deep_payload]}
        responses["message_full"] = _Response(
            {
                "id": "message-bounded",
                "threadId": "thread-bounded",
                "labelIds": ["INBOX"],
                "internalDate": "1787328000000",
                "payload": deep_payload,
            }
        )
        with pytest.raises(GmailProviderFailure, match="malformed_provider"):
            await adapter.get_message_content(
                account_key="bounded-depth", message_id="message-bounded"
            )

        responses["message_full"] = _Response(
            {
                "id": "message-bounded",
                "threadId": "thread-bounded",
                "labelIds": ["INBOX"],
                "internalDate": "1787328000000",
                "payload": {
                    "mimeType": "multipart/mixed",
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": "YQ=="}}
                        for _ in range(9)
                    ],
                },
            }
        )
        with pytest.raises(GmailProviderFailure, match="malformed_provider"):
            await adapter.get_message_content(
                account_key="bounded-parts", message_id="message-bounded"
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()


async def test_oversized_encoded_body_is_bounded_before_base64_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.gmail_history_adapter as adapter_module
    from services.gmail_history_adapter import GmailHistoryAdapter
    from services.integration_health_service import BoundedProviderExecutor

    huge_encoded = "YWFh" * 100_000
    responses = _responses()
    responses["message_full"] = _Response(
        {
            "id": "message-encoded-bound",
            "threadId": "thread-encoded-bound",
            "labelIds": ["INBOX"],
            "internalDate": "1787328000000",
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "Subject", "value": "Encoded bound"},
                    {"name": "From", "value": "client@example.test"},
                    {"name": "To", "value": "brandon@example.test"},
                ],
                "body": {"data": huge_encoded},
            },
        }
    )
    original_decoder = adapter_module.base64.b64decode
    decoded_argument_lengths: list[int] = []

    def guarded_decoder(value, *args, **kwargs):
        decoded_argument_lengths.append(len(value))
        assert len(value) <= 16
        return original_decoder(value, *args, **kwargs)

    monkeypatch.setattr(adapter_module.base64, "b64decode", guarded_decoder)
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
        max_body_bytes=4,
    )
    try:
        content = await adapter.get_message_content(
            account_key="account-encoded-bound",
            message_id="message-encoded-bound",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert decoded_argument_lengths
    assert max(decoded_argument_lengths) <= 16
    assert len(content.body_text.encode("utf-8")) <= 4
    assert content.body_truncated is True


async def test_multipart_decoding_uses_one_cumulative_body_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.gmail_history_adapter as adapter_module
    from services.gmail_history_adapter import GmailHistoryAdapter
    from services.integration_health_service import BoundedProviderExecutor

    responses = _responses()
    responses["message_full"] = _Response(
        {
            "id": "message-aggregate-bound",
            "threadId": "thread-aggregate-bound",
            "labelIds": ["INBOX"],
            "internalDate": "1787328000000",
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [
                    {"name": "Subject", "value": "Aggregate bound"},
                    {"name": "From", "value": "client@example.test"},
                    {"name": "To", "value": "brandon@example.test"},
                ],
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": "YWJjZA=="}}
                    for _ in range(20)
                ],
            },
        }
    )
    original_decoder = adapter_module.base64.b64decode
    total_decoded_bytes = 0

    def counted_decoder(value, *args, **kwargs):
        nonlocal total_decoded_bytes
        result = original_decoder(value, *args, **kwargs)
        total_decoded_bytes += len(result)
        return result

    monkeypatch.setattr(adapter_module.base64, "b64decode", counted_decoder)
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
        max_body_bytes=8,
        max_mime_parts=25,
    )
    try:
        content = await adapter.get_message_content(
            account_key="account-aggregate-bound",
            message_id="message-aggregate-bound",
        )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert total_decoded_bytes <= 8
    assert len(content.body_text.encode("utf-8")) <= 8
    assert content.body_truncated is True


@pytest.mark.parametrize(
    "encoded",
    [
        "YWJj$$$=",
        "YW JjZA==",
        "YWJjZA===",
        "!!!!",
    ],
)
async def test_full_message_rejects_noncanonical_base64url(encoded: str) -> None:
    from services.gmail_history_adapter import GmailHistoryAdapter, GmailProviderFailure
    from services.integration_health_service import BoundedProviderExecutor

    responses = _responses()
    responses["message_full"] = _Response(
        {
            "id": "message-invalid-base64",
            "threadId": "thread-invalid-base64",
            "labelIds": ["INBOX"],
            "internalDate": "1787328000000",
            "payload": {
                "mimeType": "text/plain",
                "headers": [],
                "body": {"data": encoded},
            },
        }
    )
    executor = BoundedProviderExecutor(max_workers=1)
    adapter = GmailHistoryAdapter(
        executor=executor,
        service_factory=lambda: _Gmail(responses),
        deadline_seconds=1,
        socket_timeout_seconds=0.25,
    )
    try:
        with pytest.raises(GmailProviderFailure) as raised:
            await adapter.get_message_content(
                account_key="account-invalid-base64",
                message_id="message-invalid-base64",
            )
    finally:
        await executor.wait_for_tracked_calls()
        executor.shutdown()

    assert raised.value.category == "malformed_provider"
    assert raised.value.__cause__ is None
