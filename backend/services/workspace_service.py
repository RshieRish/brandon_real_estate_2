"""Google Workspace OAuth and service clients for Brandon's agent access."""

import base64
import logging
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime
from typing import Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from config import settings

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


class WorkspaceIntegrationError(RuntimeError):
    """Raised when Google Workspace cannot be authorized or queried."""


def _workspace_client_id() -> str:
    return (
        settings.GOOGLE_WORKSPACE_CLIENT_ID
        or settings.GOOGLE_CLIENT_ID
        or settings.GOOGLE_CALENDAR_CLIENT_ID
    )


def _workspace_client_secret() -> str:
    return (
        settings.GOOGLE_WORKSPACE_CLIENT_SECRET
        or settings.GOOGLE_CLIENT_SECRET
        or settings.GOOGLE_CALENDAR_CLIENT_SECRET
    )


def _workspace_redirect_uri() -> str:
    return settings.GOOGLE_WORKSPACE_REDIRECT_URI or settings.GOOGLE_CALENDAR_REDIRECT_URI


def workspace_integration_configured() -> bool:
    return bool(_workspace_client_id() and _workspace_client_secret() and _workspace_redirect_uri())


def workspace_integration_ready() -> bool:
    return bool(workspace_integration_configured() and settings.GOOGLE_WORKSPACE_REFRESH_TOKEN)


def _workspace_client_config() -> dict:
    client_id = _workspace_client_id()
    client_secret = _workspace_client_secret()
    if not client_id or not client_secret:
        raise WorkspaceIntegrationError(
            "Google Workspace OAuth client credentials are not configured."
        )

    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _build_oauth_flow(state: str | None = None) -> Flow:
    flow = Flow.from_client_config(
        _workspace_client_config(),
        scopes=WORKSPACE_FULL_ACCESS_SCOPES,
        state=state,
    )
    flow.redirect_uri = _workspace_redirect_uri()
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


def exchange_code(code: str, state: str) -> str:
    """Exchange a Google OAuth code for a refresh token and persist it."""
    flow = _build_oauth_flow(state=state)
    flow.fetch_token(code=code)
    refresh_token = flow.credentials.refresh_token
    if not refresh_token:
        raise WorkspaceIntegrationError(
            "Google did not return a Workspace refresh token. Disconnect the app in Google and try again."
        )

    persist_refresh_token(refresh_token)
    settings.GOOGLE_WORKSPACE_REFRESH_TOKEN = refresh_token
    return refresh_token


def _workspace_credentials() -> Credentials:
    if not _workspace_client_id() or not _workspace_client_secret():
        raise WorkspaceIntegrationError(
            "Google Workspace OAuth client credentials are not configured."
        )

    if not settings.GOOGLE_WORKSPACE_REFRESH_TOKEN:
        raise WorkspaceIntegrationError(
            "Google Workspace needs one-time authorization before Hermes can access Brandon's Workspace."
        )

    return Credentials(
        token=None,
        refresh_token=settings.GOOGLE_WORKSPACE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=_workspace_client_id(),
        client_secret=_workspace_client_secret(),
    )


def build_workspace_service(api_name: str, version: str):
    """Build a Google API client using Brandon's Workspace OAuth token."""
    return build(api_name, version, credentials=_workspace_credentials(), cache_discovery=False)


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
) -> dict[str, str]:
    """Send a Gmail message from Brandon's mailbox."""
    gmail = build_workspace_service("gmail", "v1")
    raw = _build_raw_email(to=to, subject=subject, body_text=body_text, cc=cc, bcc=bcc)
    result = gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
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


def get_workspace_connection_status() -> dict[str, str | bool]:
    """Return current Workspace integration state for the admin UI."""
    if not workspace_integration_configured():
        return {
            "configured": False,
            "connected": False,
            "can_connect": False,
            "detail": "Google Workspace OAuth client credentials are missing.",
        }

    if not settings.GOOGLE_WORKSPACE_REFRESH_TOKEN:
        return {
            "configured": True,
            "connected": False,
            "can_connect": True,
            "detail": "Google Workspace needs full-access authorization as Brandon.",
        }

    try:
        gmail = build_workspace_service("gmail", "v1")
        profile = gmail.users().getProfile(userId="me").execute()
        drive = build_workspace_service("drive", "v3")
        drive.about().get(fields="user").execute()
    except Exception:
        logger.exception("Google Workspace connection check failed")
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
