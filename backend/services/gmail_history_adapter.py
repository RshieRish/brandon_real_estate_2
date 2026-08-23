"""Typed, zero-retry Gmail provider adapter for durable task intake."""

from __future__ import annotations

import base64
import json
import math
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable

import google_auth_httplib2
import httplib2
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from services.integration_health_service import (
    BoundedProviderExecutor,
    ProviderCallTimedOut,
    ProviderExecutorSaturated,
    ProviderJobStillRunning,
)


_METADATA_HEADERS = [
    "Subject",
    "From",
    "To",
    "Cc",
    "Bcc",
    "Date",
    "Auto-Submitted",
    "Precedence",
    "List-Id",
]
_RATE_LIMIT_REASONS = {
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "dailyLimitExceeded",
    "quotaExceeded",
}
_OAUTH_REVOKED_REASONS = {
    "authError",
    "insufficientPermissions",
    "invalidCredentials",
}
_MAX_GMAIL_HISTORY_ID = (1 << 64) - 1
_SINGLETON_ENVELOPE_HEADERS = frozenset({"from", "subject"})
_RECIPIENT_HEADERS = frozenset({"to", "cc", "bcc"})


class GmailProviderFailure(RuntimeError):
    """A fixed provider failure category with no raw provider detail."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class _SingleAttemptHttp(httplib2.Http):
    """httplib2 transport with no method replay at any HTTP layer."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.follow_redirects = False
        self.follow_all_redirects = False

    def _conn_request(self, conn, request_uri, method, body, headers):
        try:
            if conn.sock is None:
                conn.connect()
            conn.request(method, request_uri, body, headers)
            response = conn.getresponse()
            content = b""
            if method == "HEAD":
                conn.close()
            else:
                content = response.read()
            response = httplib2.Response(response)
            if method != "HEAD":
                content = httplib2._decompressContent(response, content)
            return response, content
        except BaseException:
            conn.close()
            raise

    def _request(
        self,
        conn,
        host,
        absolute_uri,
        request_uri,
        method,
        body,
        headers,
        redirections,
        cachekey,
    ):
        del host, absolute_uri, redirections, cachekey
        return self._conn_request(conn, request_uri, method, body, headers)


@dataclass
class GmailProfile:
    email_address: str
    history_id: str


@dataclass
class GmailHistoryMessageRef:
    message_id: str
    thread_id: str


@dataclass
class GmailHistoryPage:
    history_id: str
    messages: tuple[GmailHistoryMessageRef, ...]
    next_page_token: str | None
    discovered_history_id_min: str | None
    discovered_history_id_max: str | None


@dataclass
class GmailMessageListPage:
    messages: tuple[GmailHistoryMessageRef, ...]
    next_page_token: str | None


@dataclass
class GmailMessageMetadata:
    message_id: str
    thread_id: str
    label_ids: tuple[str, ...]
    message_at: datetime
    headers: dict[str, str]


@dataclass
class GmailMessageContent(GmailMessageMetadata):
    body_text: str = field(repr=False)
    body_truncated: bool = False
    body_transport_compatible: bool = True
    body_media_type: str = "text/plain"


def build_gmail_service(
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    socket_timeout_seconds: float,
):
    """Build a Gmail client with an explicit socket timeout and no retries."""

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    raw_http = _SingleAttemptHttp(timeout=socket_timeout_seconds)
    authorized_http = google_auth_httplib2.AuthorizedHttp(
        credentials,
        http=raw_http,
        max_refresh_attempts=0,
    )
    return build(
        "gmail",
        "v1",
        http=authorized_http,
        cache_discovery=False,
        num_retries=0,
    )


def _nonblank_string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid provider string")
    return value.strip()


def parse_gmail_provider_id(value: object) -> str:
    """Return one durable-safe Gmail message or thread identifier."""

    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 255
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
    ):
        raise ValueError("invalid Gmail provider identifier")
    return value


def parse_gmail_page_token(value: object) -> str | None:
    """Return one durable-safe opaque Gmail page token."""

    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 1024
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
    ):
        raise ValueError("invalid Gmail page token")
    return value


def _optional_token(value: object) -> str | None:
    return parse_gmail_page_token(value)


def parse_gmail_history_id(value: object) -> str:
    """Return one canonical positive Gmail uint64 history identifier."""

    if not isinstance(value, str):
        raise ValueError("invalid Gmail history identifier")
    if not value or not value.isascii() or not value.isdecimal():
        raise ValueError("invalid Gmail history identifier")
    if value[0] == "0" or len(value) > 20:
        raise ValueError("invalid Gmail history identifier")
    if int(value) > _MAX_GMAIL_HISTORY_ID:
        raise ValueError("invalid Gmail history identifier")
    return value


def _provider_reason(error: BaseException) -> str | None:
    content = getattr(error, "content", None)
    if not isinstance(content, (bytes, bytearray, str)):
        return None
    try:
        if isinstance(content, (bytes, bytearray)):
            decoded = bytes(content).decode("utf-8")
        else:
            decoded = content
        payload = json.loads(decoded)
        errors = payload.get("error", {}).get("errors", [])
        if not isinstance(errors, list):
            return None
        for item in errors:
            if isinstance(item, dict) and isinstance(item.get("reason"), str):
                return item["reason"]
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError):
        return None
    return None


def _classify_provider_error(error: BaseException, *, operation: str) -> str:
    if isinstance(error, GmailProviderFailure):
        return error.category
    if isinstance(error, RefreshError):
        return "oauth_revoked"
    if isinstance(error, (TimeoutError, socket.timeout, ConnectionError, OSError)):
        return "transient_provider"

    response = getattr(error, "resp", None)
    status = getattr(response, "status", None)
    if status == 401:
        return "oauth_revoked"
    if status == 403:
        reason = _provider_reason(error)
        if reason in _RATE_LIMIT_REASONS:
            return "rate_limited"
        if reason in _OAUTH_REVOKED_REASONS:
            return "oauth_revoked"
        return "transient_provider"
    if status == 404:
        if operation == "history":
            return "history_cursor_expired"
        if operation in {"message_metadata", "message_full"}:
            return "message_not_found"
        return "transient_provider"
    if status == 429:
        return "rate_limited"
    if isinstance(status, int) and status >= 500:
        return "transient_provider"
    return "malformed_provider"


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    raw_headers = payload.get("headers")
    if not isinstance(raw_headers, list):
        raise ValueError("invalid provider headers")
    values_by_name: dict[str, list[str]] = {}
    for item in raw_headers:
        if not isinstance(item, dict):
            raise ValueError("invalid provider header")
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("invalid provider header")
        normalized = name.strip().lower()
        if normalized:
            values_by_name.setdefault(normalized, []).append(value.strip())

    for name in _SINGLETON_ENVELOPE_HEADERS:
        if len(values_by_name.get(name, ())) > 1:
            raise ValueError("duplicate provider envelope header")

    result: dict[str, str] = {}
    for name, values in values_by_name.items():
        if name in _RECIPIENT_HEADERS:
            result[name] = ", ".join(value for value in values if value)
        elif name == "auto-submitted":
            result[name] = next(
                (
                    value
                    for value in values
                    if value.casefold() not in {"", "no"}
                ),
                values[0],
            )
        elif name == "precedence":
            result[name] = next(
                (
                    value
                    for value in values
                    if value.casefold() in {"bulk", "junk", "list"}
                ),
                values[0],
            )
        elif name == "list-id":
            result[name] = next((value for value in values if value), values[0])
        else:
            result[name] = values[0]
    return result


def _labels(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("invalid provider labels")
    labels: list[str] = []
    for item in value:
        labels.append(_nonblank_string(item))
    return tuple(labels)


def _message_at(value: object) -> datetime:
    raw = _nonblank_string(value)
    try:
        milliseconds = int(raw)
        if milliseconds < 0:
            raise ValueError
        return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
    except (OverflowError, ValueError):
        raise ValueError("invalid provider timestamp") from None


def _parse_message_metadata(payload: object) -> GmailMessageMetadata:
    if not isinstance(payload, dict):
        raise ValueError("invalid provider message")
    body = payload.get("payload")
    if not isinstance(body, dict):
        raise ValueError("invalid provider message payload")
    return GmailMessageMetadata(
        message_id=parse_gmail_provider_id(payload.get("id")),
        thread_id=parse_gmail_provider_id(payload.get("threadId")),
        label_ids=_labels(payload.get("labelIds")),
        message_at=_message_at(payload.get("internalDate")),
        headers=_headers(body),
    )


def _parse_message_ref(payload: object) -> GmailHistoryMessageRef:
    if not isinstance(payload, dict):
        raise ValueError("invalid message reference")
    return GmailHistoryMessageRef(
        message_id=parse_gmail_provider_id(payload.get("id")),
        thread_id=parse_gmail_provider_id(payload.get("threadId")),
    )


class _TextOnlyHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []

    def handle_data(self, data: str) -> None:
        self.fragments.append(data)


def _html_to_text(value: str) -> str:
    parser = _TextOnlyHTMLParser()
    parser.feed(value)
    parser.close()
    return " ".join(" ".join(parser.fragments).split())


@dataclass
class _DecodedBody:
    plain: list[str]
    html: list[str]
    truncated: bool = False
    parts_seen: int = 0


_BASE64URL_ALPHABET = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def _validated_base64url(data: object) -> tuple[bytes, int]:
    if not isinstance(data, str):
        raise ValueError("invalid provider body")
    try:
        raw = data.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("invalid provider body") from None
    padding_count = len(raw) - len(raw.rstrip(b"="))
    core = raw[:-padding_count] if padding_count else raw
    if (
        padding_count > 2
        or b"=" in core
        or any(byte not in _BASE64URL_ALPHABET for byte in core)
    ):
        raise ValueError("invalid provider body")
    required_padding = (-len(core)) % 4
    if required_padding == 3 or (padding_count and padding_count != required_padding):
        raise ValueError("invalid provider body")
    return core, required_padding


def _decode_body_data(
    data: object,
    *,
    max_body_bytes: int,
) -> tuple[str, bool, int]:
    core, required_padding = _validated_base64url(data)
    encoded_limit = max(4, math.ceil(max_body_bytes / 3) * 4 + 4)
    bounded_core = core[:encoded_limit]
    truncated = len(core) > encoded_limit
    bounded_padding = (-len(bounded_core)) % 4
    if not truncated:
        bounded_padding = required_padding
    try:
        decoded = base64.b64decode(
            bounded_core + (b"=" * bounded_padding),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, base64.binascii.Error):
        raise ValueError("invalid provider body") from None
    if len(decoded) > max_body_bytes:
        decoded = decoded[:max_body_bytes]
        truncated = True
    return decoded.decode("utf-8", errors="replace"), truncated, len(decoded)


def _is_attachment(payload: dict[str, Any]) -> bool:
    filename = payload.get("filename", "")
    if not isinstance(filename, str):
        raise ValueError("invalid provider MIME filename")
    if filename.strip():
        return True
    raw_headers = payload.get("headers", [])
    if not isinstance(raw_headers, list):
        raise ValueError("invalid provider MIME headers")
    for item in raw_headers:
        if not isinstance(item, dict):
            raise ValueError("invalid provider MIME header")
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("invalid provider MIME header")
        if name.strip().lower() == "content-disposition":
            disposition = value.split(";", 1)[0].strip().lower()
            if disposition == "attachment":
                return True
    return False


def _walk_mime(
    payload: object,
    *,
    depth: int,
    max_depth: int,
    max_parts: int,
    max_body_bytes: int,
    decoded: _DecodedBody,
) -> None:
    if not isinstance(payload, dict) or depth > max_depth:
        raise ValueError("invalid provider MIME tree")
    mime_type = payload.get("mimeType", "")
    if not isinstance(mime_type, str):
        raise ValueError("invalid provider MIME type")
    if _is_attachment(payload):
        return
    parts = payload.get("parts")
    if parts is not None:
        if not isinstance(parts, list):
            raise ValueError("invalid provider MIME parts")
        for part in parts:
            decoded.parts_seen += 1
            if decoded.parts_seen > max_parts:
                raise ValueError("provider MIME part limit exceeded")
            _walk_mime(
                part,
                depth=depth + 1,
                max_depth=max_depth,
                max_parts=max_parts,
                max_body_bytes=max_body_bytes,
                decoded=decoded,
            )
        return

    normalized = mime_type.lower().split(";", 1)[0].strip()
    if normalized not in {"text/plain", "text/html"}:
        return
    body = payload.get("body")
    if not isinstance(body, dict):
        raise ValueError("invalid provider MIME body")
    if "data" not in body:
        return
    data = body.get("data")
    _validated_base64url(data)
    assert isinstance(data, str)
    if normalized == "text/plain":
        decoded.plain.append(data)
    else:
        decoded.html.append(data)


def _is_transport_compatible_body(payload: object) -> bool:
    """Sydney sends exactly one non-attachment text/plain MIME entity."""

    if not isinstance(payload, dict) or _is_attachment(payload):
        return False
    if payload.get("parts") is not None:
        return False
    mime_type = payload.get("mimeType", "")
    if not isinstance(mime_type, str):
        return False
    if mime_type.lower().split(";", 1)[0].strip() != "text/plain":
        return False
    body = payload.get("body")
    return isinstance(body, dict) and "data" in body


def _decode_first_substantive(
    candidates: list[str],
    *,
    max_body_bytes: int,
    transform: Callable[[str], str] | None = None,
    return_original: bool = False,
) -> tuple[str, bool, int]:
    remaining = max_body_bytes
    truncated = False
    decoded_total = 0
    for index, data in enumerate(candidates):
        if remaining == 0:
            truncated = True
            break
        value, was_truncated, decoded_size = _decode_body_data(
            data,
            max_body_bytes=remaining,
        )
        decoded_total += decoded_size
        remaining -= decoded_size
        truncated = truncated or was_truncated
        candidate = transform(value) if transform is not None else value
        if candidate.strip():
            # The selected transient body is bounded, but additional visible
            # MIME entities remain undisclosed. Mark the result truncated
            # without decoding or retaining those bodies.
            if index + 1 < len(candidates):
                truncated = True
            return (
                value if return_original else candidate,
                truncated,
                decoded_total,
            )
    return "", truncated, decoded_total


class GmailHistoryAdapter:
    def __init__(
        self,
        *,
        executor: BoundedProviderExecutor,
        service_factory: Callable[[], Any],
        deadline_seconds: float,
        socket_timeout_seconds: float,
        max_body_bytes: int = 1_000_000,
        max_mime_depth: int = 12,
        max_mime_parts: int = 200,
    ) -> None:
        if deadline_seconds <= 0 or socket_timeout_seconds <= 0:
            raise ValueError("provider deadlines must be positive")
        if max_body_bytes < 1 or max_mime_depth < 1 or max_mime_parts < 1:
            raise ValueError("provider MIME bounds must be positive")
        self._executor = executor
        self._service_factory = service_factory
        self._deadline_seconds = deadline_seconds
        self._socket_timeout_seconds = socket_timeout_seconds
        self._max_body_bytes = max_body_bytes
        self._max_mime_depth = max_mime_depth
        self._max_mime_parts = max_mime_parts

    def _service(self):
        service = self._service_factory()
        http = getattr(service, "_http", None)
        if http is not None and hasattr(http, "timeout"):
            http.timeout = self._socket_timeout_seconds
        return service

    async def _execute(
        self,
        *,
        account_key: str,
        operation: str,
        function: Callable[[Any], object],
    ) -> object:
        def invoke() -> object:
            try:
                return function(self._service())
            except GmailProviderFailure as error:
                raise GmailProviderFailure(error.category) from None
            except Exception as error:
                category = _classify_provider_error(error, operation=operation)
                raise GmailProviderFailure(category) from None

        try:
            return await self._executor.run(
                key=f"gmail:{account_key}",
                function=invoke,
                deadline_seconds=self._deadline_seconds,
            )
        except ProviderCallTimedOut:
            raise GmailProviderFailure("provider_timeout") from None
        except (ProviderExecutorSaturated, ProviderJobStillRunning):
            raise
        except GmailProviderFailure as error:
            raise GmailProviderFailure(error.category) from None
        except Exception as error:
            category = _classify_provider_error(error, operation=operation)
            raise GmailProviderFailure(category) from None

    async def get_profile(self, *, account_key: str) -> GmailProfile:
        raw = await self._execute(
            account_key=account_key,
            operation="profile",
            function=lambda gmail: gmail.users()
            .getProfile(userId="me")
            .execute(num_retries=0),
        )
        try:
            if not isinstance(raw, dict):
                raise ValueError
            return GmailProfile(
                email_address=_nonblank_string(raw.get("emailAddress")).lower(),
                history_id=parse_gmail_history_id(raw.get("historyId")),
            )
        except (AttributeError, TypeError, ValueError):
            raise GmailProviderFailure("malformed_provider") from None

    async def list_history(
        self,
        *,
        account_key: str,
        start_history_id: str,
        page_token: str | None,
    ) -> GmailHistoryPage:
        try:
            canonical_start = parse_gmail_history_id(start_history_id)
            canonical_page_token = parse_gmail_page_token(page_token)
        except ValueError:
            raise GmailProviderFailure("malformed_provider") from None
        raw = await self._execute(
            account_key=account_key,
            operation="history",
            function=lambda gmail: gmail.users()
            .history()
            .list(
                userId="me",
                startHistoryId=canonical_start,
                pageToken=canonical_page_token,
                historyTypes=["messageAdded"],
                maxResults=500,
            )
            .execute(num_retries=0),
        )
        try:
            if not isinstance(raw, dict):
                raise ValueError
            history_id = parse_gmail_history_id(raw.get("historyId"))
            start_value = int(canonical_start)
            terminal_value = int(history_id)
            if terminal_value < start_value:
                raise ValueError
            next_page_token = _optional_token(raw.get("nextPageToken"))
            raw_history = raw.get("history", [])
            if not isinstance(raw_history, list):
                raise ValueError
            refs: dict[str, GmailHistoryMessageRef] = {}
            discovered_ids: list[str] = []
            for record in raw_history:
                if not isinstance(record, dict):
                    raise ValueError
                record_id = parse_gmail_history_id(record.get("id"))
                record_value = int(record_id)
                if record_value <= start_value or record_value > terminal_value:
                    raise ValueError
                discovered_ids.append(record_id)
                for field_name, nested in (
                    ("messagesAdded", True),
                    ("messages", False),
                ):
                    values = record.get(field_name, [])
                    if not isinstance(values, list):
                        raise ValueError
                    for item in values:
                        if nested:
                            if not isinstance(item, dict):
                                raise ValueError
                            item = item.get("message")
                        ref = _parse_message_ref(item)
                        prior = refs.get(ref.message_id)
                        if prior is not None and prior.thread_id != ref.thread_id:
                            raise ValueError
                        refs.setdefault(ref.message_id, ref)
            if discovered_ids:
                discovered_min = min(discovered_ids, key=int)
                discovered_max = max(discovered_ids, key=int)
            else:
                discovered_min = None
                discovered_max = None
            return GmailHistoryPage(
                history_id=history_id,
                messages=tuple(refs.values()),
                next_page_token=next_page_token,
                discovered_history_id_min=discovered_min,
                discovered_history_id_max=discovered_max,
            )
        except (AttributeError, TypeError, ValueError):
            raise GmailProviderFailure("malformed_provider") from None

    async def list_messages_for_backfill(
        self,
        *,
        account_key: str,
        window_start: datetime,
        window_end: datetime,
        page_token: str | None,
    ) -> GmailMessageListPage:
        if (
            window_start.tzinfo is None
            or window_end.tzinfo is None
            or window_end <= window_start
        ):
            raise ValueError("invalid backfill window")
        try:
            canonical_page_token = parse_gmail_page_token(page_token)
        except ValueError:
            raise GmailProviderFailure("malformed_provider") from None
        # Gmail's epoch query operators are strict. Conservative rounding
        # intentionally overfetches at the start; durable receipt dedupe makes
        # that safe, while ceiling the exclusive end prevents fractional-second
        # mail inside the authorized window from being skipped permanently.
        after_epoch = math.floor(window_start.timestamp()) - 1
        before_epoch = math.ceil(window_end.timestamp())
        query = f"after:{after_epoch} before:{before_epoch}"
        raw = await self._execute(
            account_key=account_key,
            operation="messages_list",
            function=lambda gmail: gmail.users()
            .messages()
            .list(
                userId="me",
                q=query,
                pageToken=canonical_page_token,
                includeSpamTrash=True,
                maxResults=500,
            )
            .execute(num_retries=0),
        )
        try:
            if not isinstance(raw, dict):
                raise ValueError
            values = raw.get("messages", [])
            if not isinstance(values, list):
                raise ValueError
            refs: dict[str, GmailHistoryMessageRef] = {}
            for item in values:
                ref = _parse_message_ref(item)
                prior = refs.get(ref.message_id)
                if prior is not None and prior.thread_id != ref.thread_id:
                    raise ValueError
                refs.setdefault(ref.message_id, ref)
            return GmailMessageListPage(
                messages=tuple(refs.values()),
                next_page_token=_optional_token(raw.get("nextPageToken")),
            )
        except (AttributeError, TypeError, ValueError):
            raise GmailProviderFailure("malformed_provider") from None

    async def get_message_metadata(
        self,
        *,
        account_key: str,
        message_id: str,
    ) -> GmailMessageMetadata:
        try:
            canonical_message_id = parse_gmail_provider_id(message_id)
        except ValueError:
            raise GmailProviderFailure("malformed_provider") from None
        raw = await self._execute(
            account_key=account_key,
            operation="message_metadata",
            function=lambda gmail: gmail.users()
            .messages()
            .get(
                userId="me",
                id=canonical_message_id,
                format="metadata",
                metadataHeaders=list(_METADATA_HEADERS),
            )
            .execute(num_retries=0),
        )
        try:
            return _parse_message_metadata(raw)
        except (AttributeError, TypeError, ValueError):
            raise GmailProviderFailure("malformed_provider") from None

    async def get_message_content(
        self,
        *,
        account_key: str,
        message_id: str,
    ) -> GmailMessageContent:
        try:
            canonical_message_id = parse_gmail_provider_id(message_id)
        except ValueError:
            raise GmailProviderFailure("malformed_provider") from None
        raw = await self._execute(
            account_key=account_key,
            operation="message_full",
            function=lambda gmail: gmail.users()
            .messages()
            .get(userId="me", id=canonical_message_id, format="full")
            .execute(num_retries=0),
        )
        try:
            metadata = _parse_message_metadata(raw)
            assert isinstance(raw, dict)
            decoded = _DecodedBody(plain=[], html=[])
            _walk_mime(
                raw["payload"],
                depth=0,
                max_depth=self._max_mime_depth,
                max_parts=self._max_mime_parts,
                max_body_bytes=self._max_body_bytes,
                decoded=decoded,
            )
            body_text = ""
            body_media_type = "text/plain"
            decoded_bytes = 0
            if decoded.plain:
                body_text, was_truncated, decoded_bytes = _decode_first_substantive(
                    decoded.plain,
                    max_body_bytes=self._max_body_bytes,
                )
                decoded.truncated = decoded.truncated or was_truncated
            if not body_text and decoded.html:
                remaining = max(0, self._max_body_bytes - decoded_bytes)
                body_text, was_truncated, _html_decoded_bytes = (
                    _decode_first_substantive(
                    decoded.html,
                        max_body_bytes=remaining,
                        transform=_html_to_text,
                        return_original=True,
                    )
                )
                if body_text:
                    body_media_type = "text/html"
                decoded.truncated = decoded.truncated or was_truncated
            bounded_bytes = body_text.encode("utf-8")
            if len(bounded_bytes) > self._max_body_bytes:
                bounded_bytes = bounded_bytes[: self._max_body_bytes]
                body_text = bounded_bytes.decode("utf-8", errors="ignore")
                decoded.truncated = True
            return GmailMessageContent(
                message_id=metadata.message_id,
                thread_id=metadata.thread_id,
                label_ids=metadata.label_ids,
                message_at=metadata.message_at,
                headers=metadata.headers,
                body_text=body_text,
                body_truncated=decoded.truncated,
                body_transport_compatible=_is_transport_compatible_body(
                    raw["payload"]
                ),
                body_media_type=body_media_type,
            )
        except (AssertionError, AttributeError, KeyError, TypeError, ValueError):
            raise GmailProviderFailure("malformed_provider") from None


__all__ = [
    "GmailHistoryAdapter",
    "GmailHistoryMessageRef",
    "GmailHistoryPage",
    "GmailMessageContent",
    "GmailMessageListPage",
    "GmailMessageMetadata",
    "GmailProfile",
    "GmailProviderFailure",
    "build_gmail_service",
    "parse_gmail_history_id",
    "parse_gmail_page_token",
    "parse_gmail_provider_id",
]
