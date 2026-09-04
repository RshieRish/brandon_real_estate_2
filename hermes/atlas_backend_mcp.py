#!/usr/bin/env python3
"""StdIO MCP bridge from Hermes to Brandon's protected backend actions.

The script intentionally uses only the Python standard library so it can run in
the Hermes container without changing FastAPI/backend dependencies.
"""

from __future__ import annotations

import json
import math
import os
import socket
import signal
import sys
import threading
from typing import Any
from urllib import error, parse, request


SERVER_NAME = "atlas-backend"
SERVER_VERSION = "1.0.0"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 30.0


class BackendRequestError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.payload = payload or {}


class _RequestDeadlineExceeded(Exception):
    pass


class _RequestDeadlineUnavailable(Exception):
    pass


class _HardRequestDeadline:
    """Interrupt one synchronous request at its end-to-end deadline on Linux."""

    def __init__(self, timeout_seconds: float | None) -> None:
        self.timeout_seconds = timeout_seconds
        self._previous_handler: Any = None
        self._handler_installed = False
        self._timer_armed = False

    def __enter__(self) -> None:
        try:
            valid_timeout = (
                self.timeout_seconds is not None
                and math.isfinite(float(self.timeout_seconds))
                and float(self.timeout_seconds) > 0
            )
        except (TypeError, ValueError):
            valid_timeout = False
        if not valid_timeout:
            raise _RequestDeadlineUnavailable("invalid request deadline")
        if threading.current_thread() is not threading.main_thread():
            raise _RequestDeadlineUnavailable("request is not on the main thread")
        self._previous_handler = signal.getsignal(signal.SIGALRM)
        previous_delay, previous_interval = signal.getitimer(signal.ITIMER_REAL)
        if previous_delay or previous_interval:
            raise _RequestDeadlineUnavailable("ITIMER_REAL is already active")
        try:
            signal.signal(signal.SIGALRM, self._raise_deadline)
            self._handler_installed = True
            signal.setitimer(signal.ITIMER_REAL, self.timeout_seconds)
            self._timer_armed = True
        except Exception:
            self._restore()
            raise

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        self._restore()
        return False

    def _restore(self) -> None:
        try:
            if self._timer_armed:
                signal.setitimer(signal.ITIMER_REAL, 0)
        finally:
            self._timer_armed = False
            if self._handler_installed:
                signal.signal(signal.SIGALRM, self._previous_handler)
                self._handler_installed = False

    @staticmethod
    def _raise_deadline(signum: int, frame: Any) -> None:
        raise _RequestDeadlineExceeded()


def _object_schema(
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


def _array_of_strings(description: str, *, min_items: int = 0) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "array",
        "items": {"type": "string"},
        "description": description,
        "maxItems": 20,
    }
    if min_items:
        schema["minItems"] = min_items
    return schema


TOOL_SPECS: dict[str, dict[str, Any]] = {
    "status_read": {
        "name": "status_read",
        "description": "Read backend health and capability metadata.",
        "method": "GET",
        "path": "/api/v1/agent-control/status",
        "query_params": (),
        "inputSchema": _object_schema(),
    },
    "actions_list": {
        "name": "actions_list",
        "description": "List the backend action catalog and risk tiers.",
        "method": "GET",
        "path": "/api/v1/agent-control/actions",
        "query_params": (),
        "inputSchema": _object_schema(),
    },
    "leads_recent": {
        "name": "leads_recent",
        "description": "Read recent lead summaries with masked contact data.",
        "method": "GET",
        "path": "/api/v1/agent-control/leads/recent",
        "query_params": ("limit", "lead_type", "routing_status"),
        "inputSchema": _object_schema(
            {
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                "lead_type": {"type": "string"},
                "routing_status": {"type": "string"},
            }
        ),
    },
    "bookings_recent": {
        "name": "bookings_recent",
        "description": "Read recent booking summaries with masked contact data.",
        "method": "GET",
        "path": "/api/v1/agent-control/bookings/recent",
        "query_params": ("limit", "meeting_type", "context"),
        "inputSchema": _object_schema(
            {
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                "meeting_type": {"type": "string"},
                "context": {"type": "string"},
            }
        ),
    },
    "workspace_status": {
        "name": "workspace_status",
        "description": "Read Google Workspace connection state.",
        "method": "GET",
        "path": "/api/v1/agent-control/workspace/status",
        "query_params": (),
        "inputSchema": _object_schema(),
    },
    "drive_search": {
        "name": "drive_search",
        "description": "Search Brandon's Google Drive and return compact file summaries.",
        "method": "POST",
        "path": "/api/v1/agent-control/workspace/drive/search",
        "inputSchema": _object_schema(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 1000},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            ["query"],
        ),
    },
    "drive_file_read": {
        "name": "drive_file_read",
        "description": "Read bounded text content from a supported Google Drive file.",
        "method": "POST",
        "path": "/api/v1/agent-control/workspace/drive/file",
        "inputSchema": _object_schema(
            {
                "file_id": {"type": "string", "minLength": 1, "maxLength": 300},
                "max_chars": {"type": "integer", "minimum": 500, "maximum": 20000},
            },
            ["file_id"],
        ),
    },
    "gmail_search": {
        "name": "gmail_search",
        "description": "Search Brandon's Gmail and return compact message summaries.",
        "method": "POST",
        "path": "/api/v1/agent-control/workspace/gmail/search",
        "inputSchema": _object_schema(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 1000},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            ["query"],
        ),
    },
    "gmail_thread_read": {
        "name": "gmail_thread_read",
        "description": "Read bounded body text from a Gmail thread for approved context.",
        "method": "POST",
        "path": "/api/v1/agent-control/workspace/gmail/thread",
        "inputSchema": _object_schema(
            {
                "thread_id": {"type": "string", "minLength": 1, "maxLength": 300},
                "max_body_chars": {"type": "integer", "minimum": 500, "maximum": 20000},
            },
            ["thread_id"],
        ),
    },
    "gmail_draft_create": {
        "name": "gmail_draft_create",
        "description": "Create a Gmail draft in Brandon's mailbox without sending it.",
        "method": "POST",
        "path": "/api/v1/agent-control/workspace/gmail/draft",
        "inputSchema": _object_schema(
            {
                "to": _array_of_strings("Recipient email addresses.", min_items=1),
                "subject": {"type": "string", "minLength": 1, "maxLength": 300},
                "body_text": {"type": "string", "minLength": 1, "maxLength": 20000},
                "cc": _array_of_strings("CC email addresses."),
                "bcc": _array_of_strings("BCC email addresses."),
            },
            ["to", "subject", "body_text"],
        ),
    },
    "gmail_send": {
        "name": "gmail_send",
        "description": (
            "Send email from Brandon's mailbox only after explicit Brandon "
            "approval. Requires confirmed_by_brandon=true."
        ),
        "method": "POST",
        "path": "/api/v1/agent-control/workspace/gmail/send",
        "inputSchema": _object_schema(
            {
                "request_id": {
                    "type": "string",
                    "format": "uuid",
                    "description": (
                        "Caller-supplied idempotency UUID; the bridge never "
                        "creates or replaces it."
                    ),
                },
                "retry_of_request_id": {
                    "type": "string",
                    "format": "uuid",
                    "description": (
                        "Optional caller-supplied UUID of a prior intent "
                        "authenticated as not-delivered."
                    ),
                },
                "to": _array_of_strings("Recipient email addresses.", min_items=1),
                "subject": {"type": "string", "minLength": 1, "maxLength": 300},
                "body_text": {"type": "string", "minLength": 1, "maxLength": 20000},
                "cc": _array_of_strings("CC email addresses."),
                "bcc": _array_of_strings("BCC email addresses."),
                "confirmed_by_brandon": {"type": "boolean"},
                "confirmation_note": {"type": "string", "maxLength": 500},
            },
            ["request_id", "to", "subject", "body_text", "confirmed_by_brandon"],
        ),
    },
    "docs_create": {
        "name": "docs_create",
        "description": "Create a Google Doc and insert supplied text.",
        "method": "POST",
        "path": "/api/v1/agent-control/workspace/docs/create",
        "inputSchema": _object_schema(
            {
                "title": {"type": "string", "minLength": 1, "maxLength": 300},
                "body_text": {"type": "string", "maxLength": 50000},
            },
            ["title"],
        ),
    },
    "sheets_append": {
        "name": "sheets_append",
        "description": "Append rows to a Google Sheet.",
        "method": "POST",
        "path": "/api/v1/agent-control/workspace/sheets/append",
        "inputSchema": _object_schema(
            {
                "spreadsheet_id": {"type": "string", "minLength": 1, "maxLength": 300},
                "range_name": {"type": "string", "minLength": 1, "maxLength": 300},
                "values": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 100,
                    "items": {
                        "type": "array",
                        "maxItems": 50,
                        "items": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "integer"},
                                {"type": "number"},
                                {"type": "boolean"},
                                {"type": "null"},
                            ]
                        },
                    },
                },
            },
            ["spreadsheet_id", "range_name", "values"],
        ),
    },
    "calendar_events_read": {
        "name": "calendar_events_read",
        "description": "Read Brandon's Google Calendar events in a bounded time window.",
        "method": "POST",
        "path": "/api/v1/agent-control/workspace/calendar/events",
        "inputSchema": _object_schema(
            {
                "time_min": {"type": "string", "format": "date-time"},
                "time_max": {"type": "string", "format": "date-time"},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 25},
                "calendar_id": {"type": "string", "minLength": 1, "maxLength": 300},
            },
            ["time_min", "time_max"],
        ),
    },
    "calendar_event_create": {
        "name": "calendar_event_create",
        "description": (
            "Create a Google Calendar event only after explicit Brandon approval. "
            "Requires confirmed_by_brandon=true."
        ),
        "method": "POST",
        "path": "/api/v1/agent-control/workspace/calendar/event/create",
        "inputSchema": _object_schema(
            {
                "summary": {"type": "string", "minLength": 1, "maxLength": 300},
                "start": {"type": "string", "format": "date-time"},
                "end": {"type": "string", "format": "date-time"},
                "attendees": _array_of_strings(
                    "Attendee email addresses.", min_items=1
                ),
                "location": {"type": "string", "maxLength": 1000},
                "description": {"type": "string", "maxLength": 10000},
                "calendar_id": {"type": "string", "minLength": 1, "maxLength": 300},
                "confirmed_by_brandon": {"type": "boolean"},
                "confirmation_note": {"type": "string", "maxLength": 500},
            },
            ["summary", "start", "end", "attendees", "confirmed_by_brandon"],
        ),
    },
    "contacts_search": {
        "name": "contacts_search",
        "description": "Search Google Contacts only; never Command.",
        "method": "POST",
        "path": "/api/v1/agent-control/workspace/contacts/search",
        "inputSchema": _object_schema(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 300},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            ["query"],
        ),
    },
    "crm_tasks_read": {
        "name": "crm_tasks_read",
        "description": "Read active CRM task summaries for review.",
        "method": "GET",
        "path": "/api/v1/agent-control/crm/tasks",
        "query_params": ("limit",),
        "inputSchema": _object_schema(
            {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}
        ),
    },
    "crm_task_suggestions_read": {
        "name": "crm_task_suggestions_read",
        "description": "Read CRM task suggestions awaiting Brandon review.",
        "method": "GET",
        "path": "/api/v1/agent-control/crm/task-suggestions",
        "query_params": ("limit",),
        "inputSchema": _object_schema(
            {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}
        ),
    },
    "crm_task_clarifications_answer": {
        "name": "crm_task_clarifications_answer",
        "description": (
            "Answer an opaque Sydney clarification with the required suggestion version "
            "using untrusted Hermes draft evidence; this cannot approve or create a task."
        ),
        "method": "POST",
        "path": "/api/v1/agent-control/crm/task-clarifications/answer",
        "inputSchema": _object_schema(
            {
                "code": {},
                "expected_version": {"type": "integer", "minimum": 1},
                "answer": {"type": "object", "maxProperties": 12},
            },
            ["code", "expected_version", "answer"],
        ),
    },
    "crm_task_drafts_create": {
        "name": "crm_task_drafts_create",
        "description": (
            "Create a non-authoritative Brandon-owned review draft from untrusted "
            "Hermes draft evidence; it cannot create a confirmed task."
        ),
        "method": "POST",
        "path": "/api/v1/agent-control/crm/task-drafts",
        "inputSchema": _object_schema(
            {
                "request_id": {"type": "string", "format": "uuid"},
                "title": {"type": "string", "minLength": 1, "maxLength": 255},
                "description": {"type": "string", "maxLength": 5000},
                "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                "due_at": {"type": "string", "format": "date-time"},
                "contact_id": {"type": "integer", "minimum": 1},
            },
            ["request_id", "title"],
        ),
    },
    "crm_task_suggestions_approval_link": {
        "name": "crm_task_suggestions_approval_link",
        "description": (
            "Create a fragment-only handoff link with the required suggestion version "
            "and payload hash for Brandon's authenticated review; actual approval remains "
            "authenticated Command-only."
        ),
        "method": "POST",
        "path": "/api/v1/agent-control/crm/task-suggestions/{suggestion_id}/approval-link",
        "path_params": ("suggestion_id",),
        "inputSchema": _object_schema(
            {
                "suggestion_id": {"type": "string", "format": "uuid"},
                "expected_version": {"type": "integer", "minimum": 1},
                "expected_payload_hash": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
            },
            ["suggestion_id", "expected_version", "expected_payload_hash"],
        ),
    },
    "crm_task_suggestions_dismiss_proposal": {
        "name": "crm_task_suggestions_dismiss_proposal",
        "description": (
            "Record a non-authoritative review proposal with the required suggestion "
            "version only; it cannot dismiss, suppress, or release anything."
        ),
        "method": "POST",
        "path": "/api/v1/agent-control/crm/task-suggestions/{suggestion_id}/dismiss-proposal",
        "path_params": ("suggestion_id",),
        "inputSchema": _object_schema(
            {
                "suggestion_id": {"type": "string", "format": "uuid"},
                "request_id": {"type": "string", "format": "uuid"},
                "expected_version": {"type": "integer", "minimum": 1},
                "reason": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            ["suggestion_id", "request_id", "expected_version", "reason"],
        ),
    },
    "context_history_search": {
        "name": "context_history_search",
        "description": (
            "Search Sydney's durable conversation history by text, date, type, "
            "event window, or recent conversation."
        ),
        "method": "POST",
        "path": "/api/v1/agent-control/context/history/search",
        "inputSchema": {
            **_object_schema(
                {
                    "identity_id": {"type": "string", "format": "uuid"},
                    "query": {"type": "string", "minLength": 1, "maxLength": 500},
                    "event_types": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {
                            "type": "string",
                            "enum": [
                                "user",
                                "assistant",
                                "tool_call",
                                "tool_result",
                                "approval",
                                "error",
                                "continuation",
                                "attachment_reference",
                            ],
                        },
                    },
                    "started_at": {"type": "string", "format": "date-time"},
                    "ended_at": {"type": "string", "format": "date-time"},
                    "around_event_id": {"type": "string", "format": "uuid"},
                    "recent_conversations": {"type": "boolean"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                    "window_size": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
                ["identity_id"],
            ),
            "anyOf": [
                {"required": ["query"]},
                {"required": ["around_event_id"]},
                {
                    "properties": {"recent_conversations": {"const": True}},
                    "required": ["recent_conversations"],
                },
            ],
        },
    },
    "command_contacts_search": {
        "name": "command_contacts_search",
        "description": "Search Command only; never Google Contacts or the admin UI.",
        "method": "POST",
        "path": "/api/v1/agent-control/crm/command-contacts/search",
        "inputSchema": _object_schema(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "stage": {"type": "string", "minLength": 1, "maxLength": 50},
                "tag_ids": {
                    "type": "array",
                    "maxItems": 50,
                    "items": {"type": "integer", "minimum": 1},
                },
                "sources": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "string",
                        "enum": ["internal_crm", "kw_command", "legacy_lead"],
                    },
                },
                "origins": {
                    "type": "array",
                    "maxItems": 4,
                    "items": {
                        "type": "string",
                        "enum": [
                            "internal_only",
                            "lead_backed",
                            "legacy_only",
                            "recovered",
                        ],
                    },
                },
                "cursor": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 512,
                    "pattern": "^[A-Za-z0-9_-]+$",
                },
                "page_size": {"type": "integer", "minimum": 1, "maximum": 25},
            }
        ),
    },
    "command_contact_audience_preview": {
        "name": "command_contact_audience_preview",
        "description": (
            "Preview an exact masked Command-only audience; never send, draft, "
            "or scrape the admin UI."
        ),
        "method": "POST",
        "path": "/api/v1/agent-control/crm/command-contact-audiences/preview",
        "inputSchema": _object_schema(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "stage": {"type": "string", "minLength": 1, "maxLength": 50},
                "tag_ids": {
                    "type": "array",
                    "maxItems": 50,
                    "items": {"type": "integer", "minimum": 1},
                },
                "sources": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "string",
                        "enum": ["internal_crm", "kw_command", "legacy_lead"],
                    },
                },
                "origins": {
                    "type": "array",
                    "maxItems": 4,
                    "items": {
                        "type": "string",
                        "enum": [
                            "internal_only",
                            "lead_backed",
                            "legacy_only",
                            "recovered",
                        ],
                    },
                },
            }
        ),
    },
    "command_contact_celebrations_preview": {
        "name": "command_contact_celebrations_preview",
        "description": (
            "Preview exact Command birthdays and home anniversaries for one "
            "month with masked examples and mailing-address readiness. Never "
            "substitute Google, Drive, a roster, or an admin-page scrape, and "
            "never send cards."
        ),
        "method": "POST",
        "path": "/api/v1/agent-control/crm/command-contact-celebrations/preview",
        "inputSchema": _object_schema(
            {
                "month": {"type": "integer", "minimum": 1, "maximum": 12},
                "include_birthdays": {"type": "boolean", "default": True},
                "include_home_anniversaries": {
                    "type": "boolean",
                    "default": True,
                },
            },
            ["month"],
        ),
    },
    "command_card_campaign_draft_create": {
        "name": "command_card_campaign_draft_create",
        "description": (
            "Create or retrieve a review-only Command card campaign draft. "
            "Returns an absolute Command review URL; never approves, sends, "
            "simulates delivery, or automates a provider website."
        ),
        "method": "POST",
        "path": "/api/v1/agent-control/crm/card-campaign-drafts",
        "inputSchema": _object_schema(
            {
                "request_id": {
                    "type": "string",
                    "format": "uuid",
                    "description": (
                        "Caller-supplied idempotency UUID; preserve it for an "
                        "exact retry of the same draft request."
                    ),
                },
                "month": {"type": "integer", "minimum": 1, "maximum": 12},
                "include_birthdays": {"type": "boolean", "default": True},
                "include_home_anniversaries": {
                    "type": "boolean",
                    "default": True,
                },
            },
            ["request_id", "month"],
        ),
    },
}


class BackendClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("BRANDON_BACKEND_URL") or "").rstrip("/")
        self.token = (
            token
            or os.getenv("BRANDON_AGENT_CONTROL_TOKEN")
            or os.getenv("AGENT_CONTROL_TOKEN")
        )
        configured_timeout: object = (
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("BRANDON_MCP_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        )
        try:
            requested_timeout = float(configured_timeout)
        except (TypeError, ValueError):
            self.timeout_seconds = None
        else:
            self.timeout_seconds = (
                min(max(requested_timeout, 1.0), MAX_TIMEOUT_SECONDS)
                if math.isfinite(requested_timeout) and requested_timeout > 0
                else None
            )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        if not self.base_url:
            raise BackendRequestError(
                status_code=500,
                message="BRANDON_BACKEND_URL is not configured.",
            )
        if not self.token:
            raise BackendRequestError(
                status_code=500,
                message="BRANDON_AGENT_CONTROL_TOKEN is not configured.",
            )
        if self.timeout_seconds is None:
            raise BackendRequestError(
                status_code=500,
                message="Backend request timeout configuration is invalid.",
            )

        try:
            with _HardRequestDeadline(self.timeout_seconds):
                url = f"{self.base_url}{path}"
                clean_params = _drop_none(params or {})
                if clean_params:
                    url = f"{url}?{parse.urlencode(clean_params, doseq=True)}"

                encoded_body = None
                headers = {
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json",
                }
                if body is not None:
                    encoded_body = json.dumps(_drop_none(body)).encode("utf-8")
                    headers["Content-Type"] = "application/json"

                backend_request = request.Request(
                    url,
                    data=encoded_body,
                    headers=headers,
                    method=method.upper(),
                )
                try:
                    with request.urlopen(
                        backend_request, timeout=self.timeout_seconds
                    ) as response:
                        response_text = response.read().decode("utf-8")
                        return _parse_json_response(response_text)
                except error.HTTPError as exc:
                    payload = _parse_json_response(exc.read().decode("utf-8"))
                    raise BackendRequestError(
                        status_code=exc.code,
                        message=_error_message_from_payload(payload)
                        or exc.reason
                        or "Backend request failed.",
                        payload=payload
                        if isinstance(payload, dict)
                        else {"response": payload},
                    ) from exc
        except _RequestDeadlineExceeded as exc:
            raise BackendRequestError(
                status_code=504,
                message="Backend request timed out.",
            ) from exc
        except _RequestDeadlineUnavailable as exc:
            raise BackendRequestError(
                status_code=503,
                message="Backend request deadline is unavailable.",
            ) from exc
        except (error.URLError, socket.timeout, TimeoutError) as exc:
            raise BackendRequestError(
                status_code=504 if _is_timeout_error(exc) else 502,
                message=(
                    "Backend request timed out."
                    if _is_timeout_error(exc)
                    else "Could not reach Brandon backend."
                ),
            ) from exc


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": spec["name"],
            "description": spec["description"],
            "inputSchema": spec["inputSchema"],
        }
        for spec in TOOL_SPECS.values()
    ]


def call_tool(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    client: BackendClient | Any | None = None,
) -> dict[str, Any]:
    if name not in TOOL_SPECS:
        return _tool_error(
            {
                "status_code": 400,
                "message": f"Unknown Atlas backend tool: {name}",
                "tool": name,
            }
        )
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _tool_error(
            {
                "status_code": 400,
                "message": "Tool arguments must be a JSON object.",
                "tool": name,
            }
        )

    spec = TOOL_SPECS[name]
    backend_client = client or BackendClient()
    try:
        if spec["method"] == "GET":
            params = {
                key: arguments.get(key)
                for key in spec.get("query_params", ())
                if arguments.get(key) is not None
            }
            payload = backend_client.request(
                spec["method"], spec["path"], params=params
            )
        else:
            path = spec["path"]
            path_params = spec.get("path_params", ())
            body = dict(arguments)
            for key in path_params:
                value = body.pop(key, None)
                if value is None:
                    return _tool_error(
                        {
                            "status_code": 400,
                            "message": "Tool path parameter is required.",
                            "tool": name,
                        }
                    )
                path = path.replace("{" + key + "}", str(value))
            payload = backend_client.request(spec["method"], path, body=body)
        return _tool_success(payload)
    except BackendRequestError as exc:
        return _tool_error(
            {
                "status_code": exc.status_code,
                "message": "Backend request failed.",
                "tool": name,
            }
        )


def handle_request(
    message: dict[str, Any],
    *,
    client: BackendClient | Any | None = None,
) -> dict[str, Any] | None:
    if "id" not in message:
        return None

    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if method == "initialize":
        protocol_version = params.get("protocolVersion") or "2024-11-05"
        return _rpc_success(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "ping":
        return _rpc_success(request_id, {})
    if method == "tools/list":
        return _rpc_success(request_id, {"tools": list_tools()})
    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(tool_name, str):
            return _rpc_error(request_id, -32602, "tools/call requires a string name.")
        return _rpc_success(request_id, call_tool(tool_name, arguments, client=client))

    return _rpc_error(request_id, -32601, f"Unsupported method: {method}")


def serve_stdio() -> None:
    client = BackendClient()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                response = _rpc_error(
                    None, -32600, "JSON-RPC message must be an object."
                )
            else:
                response = handle_request(message, client=client)
        except json.JSONDecodeError:
            response = _rpc_error(None, -32700, "Invalid JSON.")
        except Exception as exc:
            response = _rpc_error(None, -32603, f"Internal error: {type(exc).__name__}")

        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_none(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


def _is_timeout_error(exc: BaseException) -> bool:
    reason = exc.reason if isinstance(exc, error.URLError) else exc
    if isinstance(reason, TimeoutError):
        return True
    return isinstance(reason, str) and (
        "timeout" in reason.lower() or "timed out" in reason.lower()
    )


def _parse_json_response(response_text: str) -> Any:
    if not response_text:
        return {}
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {"text": response_text}


def _error_message_from_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        message = payload.get("message")
        if isinstance(message, str):
            return message
    return ""


def _tool_success(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": _json_text(payload)}]}


def _tool_error(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": _json_text(payload)}],
        "isError": True,
    }


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _rpc_success(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(
    request_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error_payload: dict[str, Any] = {"code": code, "message": message}
    if data:
        error_payload["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error_payload}


if __name__ == "__main__":
    serve_stdio()
