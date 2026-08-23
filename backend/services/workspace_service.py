"""Google Workspace OAuth and service clients for Brandon's agent access."""

import asyncio
import base64
import itertools
import logging
import math
from contextvars import ContextVar
from dataclasses import dataclass, field
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from config import (
    WorkspaceOAuthClientSettings,
    resolve_workspace_oauth_client_settings,
    settings,
)
from services.integration_health_service import (
    BoundedProviderExecutor,
    ProviderCallTimedOut,
    ProviderExecutorSaturated,
    ProviderJobStillRunning,
)

logger = logging.getLogger(__name__)

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

WORKSPACE_FULL_ACCESS_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/directory.readonly",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/chat.spaces",
    "https://www.googleapis.com/auth/chat.memberships",
    "https://www.googleapis.com/auth/meetings.space.settings",
    "https://www.googleapis.com/auth/admin.directory.customer",
    "https://www.googleapis.com/auth/admin.directory.group",
    "https://www.googleapis.com/auth/admin.directory.orgunit",
    "https://www.googleapis.com/auth/admin.directory.resource.calendar",
    "https://www.googleapis.com/auth/admin.directory.rolemanagement",
    "https://www.googleapis.com/auth/admin.directory.user",
]

_GOOGLE_IDENTITY_ISSUERS = frozenset(
    {"accounts.google.com", "https://accounts.google.com"}
)
_workspace_oauth_executor: BoundedProviderExecutor | None = None
_workspace_oauth_call_ids = itertools.count(1)
_bound_workspace_refresh_token: ContextVar[str | None] = ContextVar(
    "bound_workspace_refresh_token",
    default=None,
)


class WorkspaceIntegrationError(RuntimeError):
    """Raised when Google Workspace cannot be authorized or queried."""


@dataclass(frozen=True)
class WorkspaceOAuthCredentials:
    """Side-effect-free raw OAuth exchange result."""

    refresh_token: str = field(repr=False)
    id_token: str = field(repr=False)


@dataclass(frozen=True)
class WorkspaceOAuthIdentity:
    """Verified Google identity bound to one durable Workspace token."""

    refresh_token: str = field(repr=False)
    email: str
    email_verified: bool
    issuer: str
    audience: str
    subject: str = ""


def workspace_oauth_client_settings() -> WorkspaceOAuthClientSettings:
    """Return the one OAuth tuple shared by connect, status, and transports."""

    resolved = resolve_workspace_oauth_client_settings(settings)
    if resolved is None:
        raise WorkspaceIntegrationError(
            "Google Workspace OAuth client credentials are not configured."
        )
    return resolved


def _workspace_client_id() -> str:
    resolved = resolve_workspace_oauth_client_settings(settings)
    return resolved.client_id if resolved is not None else ""


def workspace_oauth_client_id() -> str:
    """Return the exact configured audience used for Workspace ID tokens."""

    return _workspace_client_id()


def _workspace_client_secret() -> str:
    resolved = resolve_workspace_oauth_client_settings(settings)
    return resolved.client_secret if resolved is not None else ""


def _workspace_redirect_uri() -> str:
    resolved = resolve_workspace_oauth_client_settings(settings)
    return resolved.redirect_uri if resolved is not None else ""


def workspace_integration_configured() -> bool:
    return resolve_workspace_oauth_client_settings(settings) is not None


def workspace_integration_ready() -> bool:
    return bool(
        workspace_integration_configured()
        and _active_workspace_refresh_token()
    )


def bind_workspace_refresh_token_for_request(
    refresh_token: str | None,
) -> None:
    """Bind database credentials to the current request without global writes."""

    if refresh_token is not None and not isinstance(refresh_token, str):
        raise WorkspaceIntegrationError(
            "Workspace refresh token binding is invalid."
        )
    _bound_workspace_refresh_token.set(refresh_token)


def _active_workspace_refresh_token() -> str:
    bound_token = _bound_workspace_refresh_token.get()
    if bound_token is not None:
        return bound_token
    return settings.GOOGLE_WORKSPACE_REFRESH_TOKEN


def _workspace_client_config() -> dict:
    oauth_client = workspace_oauth_client_settings()

    return {
        "web": {
            "client_id": oauth_client.client_id,
            "client_secret": oauth_client.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _build_oauth_flow(state: str | None = None) -> Flow:
    oauth_client = workspace_oauth_client_settings()
    flow = Flow.from_client_config(
        _workspace_client_config(),
        scopes=WORKSPACE_FULL_ACCESS_SCOPES,
        state=state,
    )
    flow.redirect_uri = oauth_client.redirect_uri
    return flow


def get_auth_url(state: str) -> tuple[str, str]:
    """Return the Google OAuth consent URL for full Workspace access."""
    flow = _build_oauth_flow(state=state)
    return flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )


def persist_refresh_token(refresh_token: str, env_path: Path | None = None) -> None:
    """Persist the Workspace refresh token in the backend .env file."""
    target_path = env_path or ENV_PATH
    if target_path.exists():
        lines = target_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    persisted = False
    for index, line in enumerate(lines):
        if line.startswith("GOOGLE_WORKSPACE_REFRESH_TOKEN="):
            lines[index] = f"GOOGLE_WORKSPACE_REFRESH_TOKEN={refresh_token}"
            persisted = True
            break

    if not persisted:
        lines.append(f"GOOGLE_WORKSPACE_REFRESH_TOKEN={refresh_token}")

    target_path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


def exchange_code(
    code: str,
    state: str,
    *,
    socket_timeout_seconds: float | None = None,
) -> WorkspaceOAuthCredentials:
    """Exchange a code without writing files, settings, or process state."""

    flow = _build_oauth_flow(state=state)
    if socket_timeout_seconds is None:
        flow.fetch_token(code=code)
    else:
        flow.fetch_token(code=code, timeout=socket_timeout_seconds)
    refresh_token = flow.credentials.refresh_token
    raw_id_token = flow.credentials.id_token
    if not refresh_token or not raw_id_token:
        raise WorkspaceIntegrationError(
            "Google did not return the required Workspace credentials."
        )

    return WorkspaceOAuthCredentials(
        refresh_token=refresh_token,
        id_token=raw_id_token,
    )


def _get_workspace_oauth_executor() -> BoundedProviderExecutor:
    global _workspace_oauth_executor
    if _workspace_oauth_executor is None:
        configured_workers = settings.INTEGRATION_PROVIDER_MAX_WORKERS
        max_workers = configured_workers if configured_workers > 0 else 1
        _workspace_oauth_executor = BoundedProviderExecutor(
            max_workers=max_workers,
        )
    return _workspace_oauth_executor


def _google_request_with_timeout(socket_timeout_seconds: float):
    transport = GoogleAuthRequest()

    def bounded_request(*args, **kwargs):
        kwargs.setdefault("timeout", socket_timeout_seconds)
        return transport(*args, **kwargs)

    return bounded_request


def _canonical_workspace_email(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError("workspace_identity_invalid")
    canonical = value.strip().lower()
    if (
        len(canonical) > 320
        or canonical.count("@") != 1
        or any(character.isspace() or ord(character) < 33 for character in canonical)
    ):
        raise RuntimeError("workspace_identity_invalid")
    local_part, domain = canonical.split("@", 1)
    if not local_part or not domain:
        raise RuntimeError("workspace_identity_invalid")
    return canonical


def validate_workspace_oauth_identity(identity: object) -> str:
    """Return the canonical email for a verified, configured identity."""

    if not isinstance(identity, WorkspaceOAuthIdentity):
        raise RuntimeError("workspace_identity_invalid")
    if (
        not isinstance(identity.refresh_token, str)
        or not identity.refresh_token.strip()
        or identity.email_verified is not True
        or identity.issuer not in _GOOGLE_IDENTITY_ISSUERS
        or not workspace_oauth_client_id()
        or identity.audience != workspace_oauth_client_id()
    ):
        raise RuntimeError("workspace_identity_invalid")
    return _canonical_workspace_email(identity.email)


def _verified_identity_from_claims(
    credentials: WorkspaceOAuthCredentials,
    claims: object,
    client_id: str,
) -> WorkspaceOAuthIdentity:
    if not isinstance(claims, dict):
        raise RuntimeError("workspace_identity_invalid")
    subject = claims.get("sub")
    audience = claims.get("aud")
    issuer = claims.get("iss")
    email = claims.get("email")
    email_verified = claims.get("email_verified")
    if (
        not isinstance(subject, str)
        or not subject.strip()
        or audience != client_id
        or issuer not in _GOOGLE_IDENTITY_ISSUERS
        or email_verified is not True
    ):
        raise RuntimeError("workspace_identity_invalid")
    canonical_email = _canonical_workspace_email(email)
    identity = WorkspaceOAuthIdentity(
        refresh_token=credentials.refresh_token,
        email=canonical_email,
        email_verified=True,
        issuer=issuer,
        audience=audience,
        subject=subject.strip(),
    )
    return identity


async def _run_bounded_oauth_call(
    *,
    executor: BoundedProviderExecutor,
    phase: str,
    function,
    deadline_seconds: float,
    failure_category: str,
):
    if deadline_seconds <= 0:
        raise RuntimeError("workspace_oauth_provider_timeout")
    key = f"workspace-oauth:{phase}:{next(_workspace_oauth_call_ids)}"
    try:
        return await executor.run(
            key=key,
            function=function,
            deadline_seconds=deadline_seconds,
        )
    except ProviderCallTimedOut:
        raise RuntimeError("workspace_oauth_provider_timeout") from None
    except (ProviderExecutorSaturated, ProviderJobStillRunning):
        raise RuntimeError("workspace_oauth_provider_unavailable") from None
    except Exception:
        raise RuntimeError(failure_category) from None


async def run_workspace_oauth_exchange(
    *,
    code: str,
    state: str,
    client_id: str | None = None,
    deadline_seconds: float,
    socket_timeout_seconds: float,
    executor: BoundedProviderExecutor | None = None,
    exchange=None,
    verifier=None,
    oauth_request_factory=None,
) -> WorkspaceOAuthIdentity:
    """Exchange and cryptographically verify Google identity off-loop."""

    if (
        not isinstance(code, str)
        or not code
        or not isinstance(state, str)
        or not state
        or not math.isfinite(deadline_seconds)
        or deadline_seconds <= 0
        or not math.isfinite(socket_timeout_seconds)
        or socket_timeout_seconds <= 0
        or socket_timeout_seconds > deadline_seconds
    ):
        raise RuntimeError("workspace_oauth_configuration_invalid")

    expected_audience = client_id or workspace_oauth_client_id()
    if not expected_audience:
        raise RuntimeError("workspace_identity_invalid")
    bounded_executor = executor or _get_workspace_oauth_executor()
    exchange_function = exchange or exchange_code
    verifier_function = verifier or google_id_token.verify_oauth2_token
    request_factory = oauth_request_factory or _google_request_with_timeout
    loop = asyncio.get_running_loop()
    expires_at = loop.time() + deadline_seconds

    def exchange_call():
        if exchange is None:
            return exchange_function(
                code,
                state,
                socket_timeout_seconds=socket_timeout_seconds,
            )
        return exchange_function(code, state)

    credentials = await _run_bounded_oauth_call(
        executor=bounded_executor,
        phase="exchange",
        function=exchange_call,
        deadline_seconds=expires_at - loop.time(),
        failure_category="workspace_oauth_provider_failed",
    )
    if (
        not isinstance(credentials, WorkspaceOAuthCredentials)
        or not isinstance(credentials.refresh_token, str)
        or not credentials.refresh_token.strip()
        or not isinstance(credentials.id_token, str)
        or not credentials.id_token
    ):
        raise RuntimeError("workspace_identity_invalid") from None

    request_object = request_factory(socket_timeout_seconds)

    def verify_call():
        return verifier_function(
            credentials.id_token,
            request_object,
            expected_audience,
        )

    claims = await _run_bounded_oauth_call(
        executor=bounded_executor,
        phase="verify",
        function=verify_call,
        deadline_seconds=expires_at - loop.time(),
        failure_category="workspace_identity_invalid",
    )
    try:
        return _verified_identity_from_claims(
            credentials,
            claims,
            expected_audience,
        )
    except RuntimeError:
        raise RuntimeError("workspace_identity_invalid") from None


def _workspace_credentials(
    *,
    refresh_token: str | None = None,
    oauth_client: WorkspaceOAuthClientSettings | None = None,
) -> Credentials:
    oauth_client = oauth_client or workspace_oauth_client_settings()

    active_refresh_token = (
        refresh_token
        if refresh_token is not None
        else _active_workspace_refresh_token()
    )
    if not active_refresh_token:
        raise WorkspaceIntegrationError(
            "Google Workspace needs one-time authorization before Hermes can access Brandon's Workspace."
        )

    return Credentials(
        token=None,
        refresh_token=active_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth_client.client_id,
        client_secret=oauth_client.client_secret,
    )


def build_workspace_service(
    api_name: str,
    version: str,
    *,
    refresh_token: str | None = None,
    oauth_client: WorkspaceOAuthClientSettings | None = None,
    socket_timeout_seconds: float | None = None,
):
    """Build a Google API client using Brandon's Workspace OAuth token."""

    credentials = _workspace_credentials(
        refresh_token=refresh_token,
        oauth_client=oauth_client,
    )
    if socket_timeout_seconds is None:
        return build(
            api_name,
            version,
            credentials=credentials,
            cache_discovery=False,
        )
    if (
        not math.isfinite(socket_timeout_seconds)
        or socket_timeout_seconds <= 0
    ):
        raise WorkspaceIntegrationError(
            "Google Workspace provider timeout is invalid."
        )
    import google_auth_httplib2

    from services.gmail_history_adapter import _SingleAttemptHttp

    authorized_http = google_auth_httplib2.AuthorizedHttp(
        credentials,
        http=_SingleAttemptHttp(timeout=socket_timeout_seconds),
        max_refresh_attempts=0,
    )
    return build(
        api_name,
        version,
        http=authorized_http,
        cache_discovery=False,
        num_retries=0,
    )


def _coerce_recipients(value: list[str] | None) -> list[str]:
    return [item.strip() for item in (value or []) if item and item.strip()]


def _safe_page_size(page_size: int, cap: int = 25) -> int:
    return min(max(page_size, 1), cap)


def _truncate_with_flag(value: str, max_chars: int) -> tuple[str, bool]:
    safe_max = min(max(max_chars, 1), 20000)
    if len(value) <= safe_max:
        return value, False
    return value[:safe_max], True


def _coerce_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _coerce_iso_datetime(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _build_raw_email(
    *,
    to: list[str],
    subject: str,
    body_text: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> str:
    message = EmailMessage()
    message["To"] = ", ".join(_coerce_recipients(to))
    message["Subject"] = subject
    cc_values = _coerce_recipients(cc)
    bcc_values = _coerce_recipients(bcc)
    if cc_values:
        message["Cc"] = ", ".join(cc_values)
    if bcc_values:
        message["Bcc"] = ", ".join(bcc_values)
    message.set_content(body_text)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


def _gmail_headers(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers") or []
    return {
        str(header.get("name", "")).lower(): str(header.get("value", ""))
        for header in headers
        if header.get("name")
    }


def _decode_gmail_body_data(value: str | None) -> str:
    if not value:
        return ""
    padded = value + ("=" * (-len(value) % 4))
    try:
        return base64.urlsafe_b64decode(padded.encode("utf-8")).decode(
            "utf-8",
            errors="replace",
        )
    except (ValueError, TypeError):
        return ""


def _extract_gmail_payload_text(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""

    mime_type = str(payload.get("mimeType", ""))
    body_text = _decode_gmail_body_data((payload.get("body") or {}).get("data"))
    if body_text and mime_type.startswith("text/plain"):
        return body_text

    plain_parts = []
    fallback_parts = []
    for part in payload.get("parts") or []:
        part_text = _extract_gmail_payload_text(part)
        if not part_text:
            continue
        part_mime = str(part.get("mimeType", ""))
        if part_mime.startswith("text/plain"):
            plain_parts.append(part_text)
        else:
            fallback_parts.append(part_text)

    if plain_parts:
        return "\n".join(plain_parts)
    if fallback_parts:
        return "\n".join(fallback_parts)
    return body_text


def _gmail_message_summary(
    message: dict[str, Any],
    *,
    include_body: bool = False,
    max_body_chars: int = 4000,
) -> dict[str, str | bool]:
    payload = message.get("payload") or {}
    headers = _gmail_headers(payload)
    summary: dict[str, str | bool] = {
        "id": message.get("id", ""),
        "thread_id": message.get("threadId", ""),
        "snippet": message.get("snippet", ""),
        "subject": headers.get("subject", ""),
        "from_email": headers.get("from", ""),
        "to_email": headers.get("to", ""),
        "date": headers.get("date", ""),
    }
    if include_body:
        body_text, truncated = _truncate_with_flag(
            _extract_gmail_payload_text(payload),
            max_body_chars,
        )
        summary["body_text"] = body_text
        summary["body_truncated"] = truncated
    return summary


def create_gmail_draft(
    *,
    to: list[str],
    subject: str,
    body_text: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> dict[str, str]:
    """Create a Gmail draft in Brandon's mailbox."""
    gmail = build_workspace_service("gmail", "v1")
    raw = _build_raw_email(to=to, subject=subject, body_text=body_text, cc=cc, bcc=bcc)
    result = (
        gmail.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw}})
        .execute()
    )
    return {
        "id": result.get("id", ""),
        "message_id": (result.get("message") or {}).get("id", ""),
    }


def send_gmail_message(
    *,
    to: list[str],
    subject: str,
    body_text: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    gmail_client: Any | None = None,
) -> dict[str, str]:
    """Send a Gmail message from Brandon's mailbox."""
    gmail = gmail_client or build_workspace_service("gmail", "v1")
    raw = _build_raw_email(to=to, subject=subject, body_text=body_text, cc=cc, bcc=bcc)
    result = (
        gmail.users()
        .messages()
        .send(userId="me", body={"raw": raw})
        .execute(num_retries=0)
    )
    return {
        "id": result.get("id", ""),
        "thread_id": result.get("threadId", ""),
    }


def search_gmail_messages(query: str, page_size: int = 10) -> list[dict[str, str | bool]]:
    """Search Brandon's Gmail and return compact message metadata."""
    gmail = build_workspace_service("gmail", "v1")
    safe_page_size = _safe_page_size(page_size)
    result = (
        gmail.users()
        .messages()
        .list(userId="me", q=query, maxResults=safe_page_size)
        .execute()
    )
    messages = []
    for item in result.get("messages", []):
        message_id = item.get("id")
        if not message_id:
            continue
        message = (
            gmail.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"],
            )
            .execute()
        )
        if not message.get("threadId") and item.get("threadId"):
            message["threadId"] = item.get("threadId")
        messages.append(_gmail_message_summary(message))
    return messages


def get_gmail_thread(thread_id: str, max_body_chars: int = 4000) -> dict[str, Any]:
    """Read a Gmail thread and extract text bodies for Hermes context."""
    gmail = build_workspace_service("gmail", "v1")
    result = (
        gmail.users()
        .threads()
        .get(userId="me", id=thread_id, format="full")
        .execute()
    )
    return {
        "thread_id": result.get("id", thread_id),
        "messages": [
            _gmail_message_summary(
                message,
                include_body=True,
                max_body_chars=max_body_chars,
            )
            for message in result.get("messages", [])
        ],
    }


def search_drive_files(query: str, page_size: int = 10) -> list[dict[str, str]]:
    """Search Brandon's Google Drive and return compact file summaries."""
    drive = build_workspace_service("drive", "v3")
    safe_page_size = _safe_page_size(page_size)
    result = (
        drive.files()
        .list(
            q=query,
            pageSize=safe_page_size,
            fields="files(id,name,mimeType,webViewLink,modifiedTime)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    return [
        {
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "mime_type": item.get("mimeType", ""),
            "web_view_link": item.get("webViewLink", ""),
            "modified_time": item.get("modifiedTime", ""),
        }
        for item in result.get("files", [])
    ]


def read_drive_file(file_id: str, max_chars: int = 4000) -> dict[str, str | bool]:
    """Read text content from a supported Drive file."""
    drive = build_workspace_service("drive", "v3")
    metadata = (
        drive.files()
        .get(
            fileId=file_id,
            fields="id,name,mimeType,webViewLink,modifiedTime",
            supportsAllDrives=True,
        )
        .execute()
    )
    mime_type = metadata.get("mimeType", "")
    export_mime_type = ""
    if mime_type == "application/vnd.google-apps.document":
        export_mime_type = "text/plain"
    elif mime_type == "application/vnd.google-apps.spreadsheet":
        export_mime_type = "text/csv"

    if export_mime_type:
        raw_content = (
            drive.files()
            .export(fileId=file_id, mimeType=export_mime_type)
            .execute()
        )
    elif mime_type.startswith("text/") or mime_type in {
        "application/json",
        "application/xml",
        "text/csv",
    }:
        raw_content = drive.files().get_media(fileId=file_id).execute()
    else:
        raw_content = ""

    content_text, truncated = _truncate_with_flag(_coerce_text(raw_content), max_chars)
    return {
        "id": metadata.get("id", file_id),
        "name": metadata.get("name", ""),
        "mime_type": mime_type,
        "web_view_link": metadata.get("webViewLink", ""),
        "modified_time": metadata.get("modifiedTime", ""),
        "content_text": content_text,
        "truncated": truncated,
    }


def create_google_doc(title: str, body_text: str) -> dict[str, str]:
    """Create a Google Doc and insert body text."""
    docs = build_workspace_service("docs", "v1")
    created = docs.documents().create(body={"title": title}).execute()
    document_id = created.get("documentId", "")
    if body_text:
        docs.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": 1},
                            "text": body_text,
                        }
                    }
                ]
            },
        ).execute()
    return {
        "document_id": document_id,
        "title": created.get("title", title),
        "url": f"https://docs.google.com/document/d/{document_id}/edit" if document_id else "",
    }


def list_calendar_events(
    time_min: datetime | str,
    time_max: datetime | str,
    *,
    page_size: int = 10,
    calendar_id: str = "primary",
) -> list[dict[str, str | int]]:
    """List Brandon's Calendar events using the Workspace OAuth token."""
    calendar = build_workspace_service("calendar", "v3")
    safe_page_size = _safe_page_size(page_size)
    result = (
        calendar.events()
        .list(
            calendarId=calendar_id,
            timeMin=_coerce_iso_datetime(time_min),
            timeMax=_coerce_iso_datetime(time_max),
            singleEvents=True,
            orderBy="startTime",
            maxResults=safe_page_size,
        )
        .execute()
    )
    events = []
    for item in result.get("items", []):
        start = item.get("start") or {}
        end = item.get("end") or {}
        events.append(
            {
                "id": item.get("id", ""),
                "summary": item.get("summary", ""),
                "start": start.get("dateTime", start.get("date", "")),
                "end": end.get("dateTime", end.get("date", "")),
                "location": item.get("location", ""),
                "html_link": item.get("htmlLink", ""),
                "attendee_count": len(item.get("attendees") or []),
            }
        )
    return events


def create_workspace_calendar_event(
    *,
    summary: str,
    start: datetime | str,
    end: datetime | str,
    attendees: list[str],
    location: str = "",
    description: str = "",
    calendar_id: str = "primary",
) -> dict[str, str]:
    """Create a Calendar event from Brandon's Workspace account."""
    calendar = build_workspace_service("calendar", "v3")
    event_body = {
        "summary": summary,
        "location": location,
        "description": description,
        "start": {"dateTime": _coerce_iso_datetime(start)},
        "end": {"dateTime": _coerce_iso_datetime(end)},
        "attendees": [{"email": email} for email in _coerce_recipients(attendees)],
        "reminders": {"useDefault": True},
    }
    created = (
        calendar.events()
        .insert(
            calendarId=calendar_id,
            body=event_body,
            sendUpdates="all",
        )
        .execute()
    )
    return {
        "event_id": created.get("id", ""),
        "html_link": created.get("htmlLink", ""),
    }


def search_contacts(query: str, page_size: int = 10) -> list[dict[str, str | list[str]]]:
    """Search Brandon's Google Contacts with compact contact summaries."""
    people = build_workspace_service("people", "v1")
    safe_page_size = _safe_page_size(page_size)
    result = (
        people.people()
        .searchContacts(
            query=query,
            pageSize=safe_page_size,
            readMask="names,emailAddresses,phoneNumbers",
        )
        .execute()
    )
    contacts = []
    for item in result.get("results", []):
        person = item.get("person") or {}
        names = person.get("names") or []
        emails = person.get("emailAddresses") or []
        phones = person.get("phoneNumbers") or []
        contacts.append(
            {
                "resource_name": person.get("resourceName", ""),
                "display_name": (names[0] or {}).get("displayName", "") if names else "",
                "email_addresses": [
                    email.get("value", "") for email in emails if email.get("value")
                ],
                "phone_numbers": [
                    phone.get("value", "") for phone in phones if phone.get("value")
                ],
            }
        )
    return contacts


def append_sheet_values(
    *,
    spreadsheet_id: str,
    range_name: str,
    values: list[list[str | int | float | bool | None]],
) -> dict[str, str | int]:
    """Append rows to a Google Sheet."""
    sheets = build_workspace_service("sheets", "v4")
    result = (
        sheets.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        )
        .execute()
    )
    updates = result.get("updates") or {}
    return {
        "spreadsheet_id": result.get("spreadsheetId", spreadsheet_id),
        "updated_range": updates.get("updatedRange", ""),
        "updated_rows": updates.get("updatedRows", 0),
        "updated_columns": updates.get("updatedColumns", 0),
        "updated_cells": updates.get("updatedCells", 0),
    }


def _workspace_status_unavailable() -> dict[str, str | bool]:
    return {
        "configured": True,
        "connected": False,
        "can_connect": True,
        "detail": (
            "Workspace credentials are present, but the connection check "
            "did not complete. Try again shortly."
        ),
    }


def get_workspace_connection_status(
    *,
    refresh_token: str | None = None,
    oauth_client: WorkspaceOAuthClientSettings | None = None,
    socket_timeout_seconds: float | None = None,
) -> dict[str, str | bool]:
    """Return current Workspace integration state for the admin UI."""
    resolved_oauth_client = oauth_client or resolve_workspace_oauth_client_settings(
        settings
    )
    if resolved_oauth_client is None:
        return {
            "configured": False,
            "connected": False,
            "can_connect": False,
            "detail": "Google Workspace OAuth client credentials are missing.",
        }

    active_refresh_token = (
        refresh_token
        if refresh_token is not None
        else _active_workspace_refresh_token()
    )
    if not active_refresh_token:
        return {
            "configured": True,
            "connected": False,
            "can_connect": True,
            "detail": "Google Workspace needs full-access authorization as Brandon.",
        }

    try:
        gmail = build_workspace_service(
            "gmail",
            "v1",
            refresh_token=active_refresh_token,
            oauth_client=resolved_oauth_client,
            socket_timeout_seconds=socket_timeout_seconds,
        )
        profile = gmail.users().getProfile(userId="me").execute(num_retries=0)
        drive = build_workspace_service(
            "drive",
            "v3",
            refresh_token=active_refresh_token,
            oauth_client=resolved_oauth_client,
            socket_timeout_seconds=socket_timeout_seconds,
        )
        drive.about().get(fields="user").execute(num_retries=0)
    except Exception:
        logger.error("Google Workspace connection check failed")
        return {
            "configured": True,
            "connected": False,
            "can_connect": True,
            "detail": "Workspace credentials are present, but Gmail or Drive connection checks failed. Reconnect Brandon's Workspace.",
        }

    email = profile.get("emailAddress") or "Brandon's Workspace"
    return {
        "configured": True,
        "connected": True,
        "can_connect": True,
        "detail": f"Google Workspace is connected as {email}. Full-access OAuth is available for approved agent workflows.",
    }


async def get_workspace_connection_status_bounded(
    *,
    deadline_seconds: float | None = None,
    socket_timeout_seconds: float | None = None,
    executor: BoundedProviderExecutor | None = None,
    status_check=None,
) -> dict[str, str | bool]:
    """Check Workspace off-loop with one stable overlap key and fixed errors."""

    oauth_client = resolve_workspace_oauth_client_settings(settings)
    if oauth_client is None:
        return {
            "configured": False,
            "connected": False,
            "can_connect": False,
            "detail": "Google Workspace OAuth client credentials are missing.",
        }
    refresh_token = _active_workspace_refresh_token()
    if not refresh_token:
        return {
            "configured": True,
            "connected": False,
            "can_connect": True,
            "detail": "Google Workspace needs full-access authorization as Brandon.",
        }
    deadline = (
        settings.INTEGRATION_PROVIDER_DEADLINE_SECONDS
        if deadline_seconds is None
        else deadline_seconds
    )
    socket_timeout = (
        settings.INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS
        if socket_timeout_seconds is None
        else socket_timeout_seconds
    )
    if (
        not math.isfinite(deadline)
        or deadline <= 0
        or not math.isfinite(socket_timeout)
        or socket_timeout <= 0
        or socket_timeout > deadline
    ):
        return _workspace_status_unavailable()
    bounded_executor = executor or _get_workspace_oauth_executor()

    def check():
        if status_check is not None:
            return status_check(
                refresh_token=refresh_token,
                oauth_client=oauth_client,
                socket_timeout_seconds=socket_timeout,
            )
        return get_workspace_connection_status(
            refresh_token=refresh_token,
            oauth_client=oauth_client,
            socket_timeout_seconds=socket_timeout,
        )

    try:
        result = await bounded_executor.run(
            key="workspace-status",
            function=check,
            deadline_seconds=deadline,
        )
    except (
        ProviderCallTimedOut,
        ProviderExecutorSaturated,
        ProviderJobStillRunning,
    ):
        logger.error("Google Workspace connection check unavailable")
        return _workspace_status_unavailable()
    except BaseException:
        logger.error("Google Workspace connection check failed")
        return _workspace_status_unavailable()
    if not isinstance(result, dict):
        return _workspace_status_unavailable()
    return result
