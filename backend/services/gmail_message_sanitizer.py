"""Bounded Gmail message sanitization and fail-closed runtime validation."""

from __future__ import annotations

import hashlib
import hmac
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import getaddresses
from html.parser import HTMLParser
from typing import Mapping, Protocol

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from config import resolve_workspace_oauth_client_settings


_PARTICIPANT_DOMAIN = b"sws:gmail-task-intake:participant:v1\x00"
_MIN_PARTICIPANT_KEY_BYTES = 32
_MIN_RECEIPT_FINALIZATION_MARGIN_SECONDS = 5.0
_MAX_BODY_CHARS = 12_000
_BODY_SCAN_MULTIPLIER = 4
_BODY_SCAN_PADDING = 4_096
_SAFE_TLS_MODES = frozenset({"require", "verify-ca", "verify-full"})
_LIKELY_POOLER_PORTS = frozenset({6432, 6543})
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_QUOTED_THREAD_START = re.compile(
    r"(?im)^(?:"
    r"on [^\n]{0,500} wrote:\s*|"
    r"from:\s*[^\n]{0,500}|"
    r"-{2,}\s*original message\s*-{2,}|"
    r"_{5,}\s*"
    r")$"
)
_SIGNATURE_START = re.compile(r"(?im)^(?:\s*--\s*|\s*sent from my(?:\s+[^\n]*)?)$")
_TRACKING_URL = re.compile(r"https?://[^\s<>\"']{1,2048}", re.IGNORECASE)
_TRACKING_MARKERS = (
    "tracking",
    "/pixel",
    "pixel.",
    "utm_",
    "mc_eid=",
    "gclid=",
)


class _GmailMessageLike(Protocol):
    message_id: str
    thread_id: str
    label_ids: tuple[str, ...]
    message_at: datetime
    headers: Mapping[str, str]
    body_text: str
    body_truncated: bool
    body_media_type: str


@dataclass(frozen=True)
class GmailRuntimeSettings:
    """Validated Gmail settings safe to hand to the integration worker."""

    enabled: bool
    history_database_url: str | None = field(repr=False)
    participant_hash_key: bytes | None = field(repr=False)
    max_workers: int
    socket_timeout_seconds: float
    deadline_seconds: float
    max_pages_per_run: int
    job_deadline_seconds: float
    receipt_processing_deadline_seconds: float
    receipt_processing_stale_after_seconds: float
    workspace_oauth_client_id: str | None
    workspace_oauth_client_secret: str | None = field(repr=False)
    workspace_oauth_redirect_uri: str | None

    @property
    def provider_max_workers(self) -> int:
        return self.max_workers

    @property
    def provider_deadline_seconds(self) -> float:
        return self.deadline_seconds

    @property
    def whole_job_deadline_seconds(self) -> float:
        return self.job_deadline_seconds


@dataclass(frozen=True)
class SanitizedGmailMessage:
    """Durable receipt fields plus the one transient, non-repr body value."""

    message_id: str
    thread_id: str
    direction: str
    message_at: datetime
    sender_hmac: str | None
    recipient_hmacs: tuple[str, ...]
    subject_preview: str | None = field(repr=False)
    body_hash: str
    labels: tuple[str, ...]
    processing_state: str
    classification: str
    transient_body_text: str = field(repr=False)
    body_truncated: bool

    @property
    def label_ids(self) -> tuple[str, ...]:
        return self.labels


class _PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.casefold() in _BLOCK_TAGS:
            self.fragments.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in _BLOCK_TAGS:
            self.fragments.append("\n")

    def handle_data(self, data: str) -> None:
        self.fragments.append(data)

    def text(self) -> str:
        return "".join(self.fragments)


def _setting(config: object, name: str):
    return getattr(config, name)


def _positive_finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _participant_key(value: object) -> bytes:
    if not isinstance(value, str):
        raise RuntimeError("participant_hash_key_invalid")
    normalized = value.strip()
    try:
        encoded = normalized.encode("ascii")
    except UnicodeEncodeError:
        raise RuntimeError("participant_hash_key_invalid") from None
    if len(encoded) < _MIN_PARTICIPANT_KEY_BYTES or any(
        byte < 33 or byte > 126 for byte in encoded
    ):
        raise RuntimeError("participant_hash_key_invalid")
    return encoded


def _query_values(url, key: str) -> tuple[str, ...]:
    value = url.query.get(key)
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(str(item).strip().casefold() for item in value)
    return (str(value).strip().casefold(),)


def _is_pooler_url(url) -> bool:
    hostname = (url.host or "").casefold()
    if "pooler" in hostname or url.port in _LIKELY_POOLER_PORTS:
        return True

    pgbouncer_values = _query_values(url, "pgbouncer")
    if any(value not in {"", "0", "false", "no", "off"} for value in pgbouncer_values):
        return True
    return bool(_query_values(url, "pool_mode"))


def _validate_history_database_url(config: object) -> str:
    raw_history_url = _setting(config, "GMAIL_HISTORY_DATABASE_URL")
    if not isinstance(raw_history_url, str) or not raw_history_url.strip():
        raise RuntimeError("gmail_history_database_url_required")

    try:
        history_url = make_url(raw_history_url.strip())
    except (ArgumentError, TypeError, ValueError):
        raise RuntimeError("gmail_history_postgresql_required") from None
    if history_url.get_backend_name() != "postgresql":
        raise RuntimeError("gmail_history_postgresql_required")
    if _is_pooler_url(history_url):
        raise RuntimeError("gmail_history_direct_database_required")

    raw_primary_url = _setting(config, "DATABASE_URL")
    try:
        primary_url = make_url(raw_primary_url)
    except (ArgumentError, TypeError, ValueError):
        raise RuntimeError("gmail_primary_database_url_invalid") from None
    if not history_url.database or history_url.database != primary_url.database:
        raise RuntimeError("gmail_history_database_mismatch")

    tls_values = (
        *_query_values(history_url, "ssl"),
        *_query_values(history_url, "sslmode"),
    )
    if not tls_values or any(value not in _SAFE_TLS_MODES for value in tls_values):
        raise RuntimeError("gmail_history_tls_required")
    return raw_history_url.strip()


def validate_gmail_runtime_settings(config: object) -> GmailRuntimeSettings:
    """Validate Gmail-only settings when enabled, without exposing their values."""

    enabled = bool(_setting(config, "GMAIL_TASK_INTAKE_ENABLED"))
    max_workers = _setting(config, "INTEGRATION_PROVIDER_MAX_WORKERS")
    socket_timeout = _setting(config, "INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS")
    provider_deadline = _setting(config, "INTEGRATION_PROVIDER_DEADLINE_SECONDS")
    max_pages = _setting(config, "GMAIL_HISTORY_MAX_PAGES_PER_RUN")
    job_deadline = _setting(config, "GMAIL_HISTORY_JOB_DEADLINE_SECONDS")
    receipt_deadline = _setting(config, "GMAIL_RECEIPT_PROCESSING_DEADLINE_SECONDS")
    stale_after = _setting(config, "GMAIL_RECEIPT_PROCESSING_STALE_AFTER_SECONDS")

    if not enabled:
        return GmailRuntimeSettings(
            enabled=False,
            history_database_url=None,
            participant_hash_key=None,
            max_workers=max_workers,
            socket_timeout_seconds=socket_timeout,
            deadline_seconds=provider_deadline,
            max_pages_per_run=max_pages,
            job_deadline_seconds=job_deadline,
            receipt_processing_deadline_seconds=receipt_deadline,
            receipt_processing_stale_after_seconds=stale_after,
            workspace_oauth_client_id=None,
            workspace_oauth_client_secret=None,
            workspace_oauth_redirect_uri=None,
        )

    participant_key = _participant_key(_setting(config, "GMAIL_PARTICIPANT_HASH_KEY"))
    if (
        not isinstance(max_workers, int)
        or isinstance(max_workers, bool)
        or max_workers <= 0
    ):
        raise RuntimeError("provider_workers_invalid")
    if not _positive_finite(provider_deadline):
        raise RuntimeError("provider_deadline_invalid")
    if not _positive_finite(socket_timeout):
        raise RuntimeError("provider_socket_timeout_invalid")
    if float(socket_timeout) >= float(provider_deadline):
        raise RuntimeError("provider_socket_timeout_exceeds_deadline")
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages <= 0:
        raise RuntimeError("gmail_history_max_pages_invalid")
    if not _positive_finite(job_deadline):
        raise RuntimeError("gmail_history_job_deadline_invalid")
    if (
        not _positive_finite(receipt_deadline)
        or float(receipt_deadline) - float(provider_deadline)
        < _MIN_RECEIPT_FINALIZATION_MARGIN_SECONDS
    ):
        raise RuntimeError("gmail_receipt_processing_deadline_invalid")
    if not _positive_finite(stale_after) or float(stale_after) <= float(
        receipt_deadline
    ):
        raise RuntimeError("gmail_receipt_stale_threshold_invalid")

    oauth_client = resolve_workspace_oauth_client_settings(config)
    if oauth_client is None:
        raise RuntimeError("gmail_workspace_oauth_config_required")

    history_database_url = _validate_history_database_url(config)
    return GmailRuntimeSettings(
        enabled=True,
        history_database_url=history_database_url,
        participant_hash_key=participant_key,
        max_workers=max_workers,
        socket_timeout_seconds=float(socket_timeout),
        deadline_seconds=float(provider_deadline),
        max_pages_per_run=max_pages,
        job_deadline_seconds=float(job_deadline),
        receipt_processing_deadline_seconds=float(receipt_deadline),
        receipt_processing_stale_after_seconds=float(stale_after),
        workspace_oauth_client_id=oauth_client.client_id,
        workspace_oauth_client_secret=oauth_client.client_secret,
        workspace_oauth_redirect_uri=oauth_client.redirect_uri,
    )


def _key_bytes(participant_hash_key: bytes | str) -> bytes:
    if isinstance(participant_hash_key, bytes):
        key = participant_hash_key
    elif isinstance(participant_hash_key, str):
        try:
            key = participant_hash_key.encode("ascii")
        except UnicodeEncodeError:
            raise ValueError("participant_hash_key_invalid") from None
    else:
        raise ValueError("participant_hash_key_invalid")
    if len(key) < _MIN_PARTICIPANT_KEY_BYTES:
        raise ValueError("participant_hash_key_invalid")
    return key


def _canonical_address(address: str) -> str:
    if not isinstance(address, str):
        raise ValueError("participant_address_invalid")
    canonical = address.strip().lower()
    if (
        not canonical
        or "@" not in canonical
        or any(character.isspace() or ord(character) < 32 for character in canonical)
    ):
        raise ValueError("participant_address_invalid")
    return canonical


def participant_hmac(address: str, participant_hash_key: bytes | str) -> str:
    """Return a deterministic, versioned HMAC without retaining the address."""

    canonical = _canonical_address(address)
    key = _key_bytes(participant_hash_key)
    return hmac.new(
        key,
        _PARTICIPANT_DOMAIN + canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _normalized_headers(headers: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    try:
        items = headers.items()
    except AttributeError:
        raise ValueError("gmail_headers_invalid") from None
    for name, value in items:
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("gmail_headers_invalid")
        key = name.strip().casefold()
        if key and key not in normalized:
            normalized[key] = value
    return normalized


def _header_addresses(
    headers: Mapping[str, str], names: tuple[str, ...]
) -> tuple[str, ...]:
    values = [headers[name] for name in names if headers.get(name, "").strip()]
    try:
        parsed = getaddresses(values)
    except (IndexError, TypeError, ValueError):
        raise ValueError("gmail_participants_invalid") from None

    result: list[str] = []
    seen: set[str] = set()
    for _display_name, address in parsed:
        if not address.strip():
            continue
        try:
            canonical = _canonical_address(address)
        except ValueError:
            continue
        if canonical not in seen:
            result.append(canonical)
            seen.add(canonical)
    return tuple(result)


def _direction(
    labels: frozenset[str],
    _sender: str | None,
    recipients: tuple[str, ...],
    mailbox_email: str,
) -> str:
    # Gmail's provider-controlled SENT label, not the spoofable From header,
    # is the authority for outbound direction. This prevents an inbound
    # message claiming the mailbox address from becoming a Brandon obligation.
    if "SENT" not in labels:
        return "received"
    if mailbox_email in recipients:
        return "self_copy"
    return "sent"


def _is_automation(headers: Mapping[str, str]) -> bool:
    auto_submitted = headers.get("auto-submitted", "").strip().casefold()
    if auto_submitted and auto_submitted != "no":
        return True
    precedence = headers.get("precedence", "").strip().casefold()
    if precedence in {"bulk", "junk", "list"}:
        return True
    return bool(headers.get("list-id", "").strip())


def _classification(
    labels: frozenset[str],
    headers: Mapping[str, str],
    origin_kind: str | None,
) -> str:
    if "DRAFT" in labels:
        return "ignored_draft"
    if "SPAM" in labels:
        return "ignored_spam"
    if "TRASH" in labels:
        return "ignored_trash"
    if origin_kind == "system_automation":
        return "ignored_system_automation"
    if _is_automation(headers):
        return "ignored_automation"
    return "eligible"


def gmail_message_classification(
    content: _GmailMessageLike,
    *,
    origin_kind: str | None = None,
) -> str:
    """Return the shared metadata-only extraction eligibility category."""

    headers = _normalized_headers(content.headers)
    labels = frozenset(
        label.strip().upper()
        for label in content.label_ids
        if isinstance(label, str) and label.strip()
    )
    return _classification(labels, headers, origin_kind)


def _remove_tracking_url(match: re.Match[str]) -> str:
    value = match.group(0).casefold()
    if any(marker in value for marker in _TRACKING_MARKERS):
        return ""
    return match.group(0)


def _body_to_plain_text(
    raw_body: str,
    max_body_chars: int,
    *,
    body_media_type: str,
) -> tuple[str, bool]:
    if not isinstance(raw_body, str):
        raise ValueError("gmail_body_invalid")
    if (
        not isinstance(max_body_chars, int)
        or isinstance(max_body_chars, bool)
        or not 1 <= max_body_chars <= _MAX_BODY_CHARS
    ):
        raise ValueError("gmail_body_limit_invalid")

    scan_limit = max(
        max_body_chars * _BODY_SCAN_MULTIPLIER,
        max_body_chars + _BODY_SCAN_PADDING,
    )
    truncated = len(raw_body) > max_body_chars
    bounded_body = raw_body[:scan_limit]
    if len(raw_body) > scan_limit:
        truncated = True
    bounded_body = bounded_body.replace("\r\n", "\n").replace("\r", "\n")
    if body_media_type == "text/html":
        parser = _PlainTextHTMLParser()
        try:
            parser.feed(bounded_body)
            parser.close()
        except (AssertionError, UnicodeError, ValueError):
            raise ValueError("gmail_body_invalid") from None
        text = parser.text().replace("\xa0", " ")
    elif body_media_type == "text/plain":
        text = bounded_body
    else:
        raise ValueError("gmail_body_media_type_invalid")

    quote_match = _QUOTED_THREAD_START.search(text)
    if quote_match is not None:
        text = text[: quote_match.start()]
    signature_match = _SIGNATURE_START.search(text)
    if signature_match is not None:
        text = text[: signature_match.start()]

    text = _TRACKING_URL.sub(_remove_tracking_url, text)
    lines: list[str] = []
    for line in text.split("\n"):
        if line.lstrip().startswith(">"):
            continue
        cleaned = " ".join(line.replace("\t", " ").split())
        lines.append(cleaned)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) > max_body_chars:
        text = text[:max_body_chars].rstrip()
        truncated = True
    return text, truncated


def _subject_preview(headers: Mapping[str, str]) -> str | None:
    subject = headers.get("subject", "")
    cleaned = " ".join(subject.replace("\r", " ").replace("\n", " ").split())
    if not cleaned:
        return None
    return cleaned[:255]


def sanitize_gmail_message(
    content: _GmailMessageLike,
    *,
    mailbox_email: str,
    participant_hash_key: bytes | str,
    origin_kind: str | None = None,
    max_body_chars: int = _MAX_BODY_CHARS,
) -> SanitizedGmailMessage:
    """Create body-free durable fields and one bounded transient body value."""

    mailbox = _canonical_address(mailbox_email)
    headers = _normalized_headers(content.headers)
    senders = _header_addresses(headers, ("from",))
    recipients = _header_addresses(headers, ("to", "cc", "bcc"))
    sender = senders[0] if len(senders) == 1 else None

    normalized_labels = tuple(
        dict.fromkeys(
            label.strip().upper()
            for label in content.label_ids
            if isinstance(label, str) and label.strip()
        )
    )
    labels = frozenset(normalized_labels)
    direction = _direction(labels, sender, recipients, mailbox)
    classification = _classification(labels, headers, origin_kind)
    transient_body, locally_truncated = _body_to_plain_text(
        content.body_text,
        max_body_chars,
        body_media_type=getattr(content, "body_media_type", "text/plain"),
    )

    return SanitizedGmailMessage(
        message_id=content.message_id,
        thread_id=content.thread_id,
        direction=direction,
        message_at=content.message_at,
        sender_hmac=(
            participant_hmac(sender, participant_hash_key)
            if sender is not None
            else None
        ),
        recipient_hmacs=tuple(
            participant_hmac(address, participant_hash_key) for address in recipients
        ),
        subject_preview=_subject_preview(headers),
        body_hash=hashlib.sha256(transient_body.encode("utf-8")).hexdigest(),
        labels=normalized_labels,
        processing_state=("pending" if classification == "eligible" else "ignored"),
        classification=classification,
        transient_body_text=transient_body,
        body_truncated=bool(getattr(content, "body_truncated", False))
        or locally_truncated,
    )
