import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from routers import agent_control
from schemas.agent_control import (
    WorkspaceCalendarCreateEventRequest,
    WorkspaceCalendarEventsRequest,
    WorkspaceContactsSearchRequest,
    WorkspaceDocsCreateRequest,
    WorkspaceDriveFileReadRequest,
    WorkspaceDriveSearchRequest,
    WorkspaceGmailDraftRequest,
    WorkspaceGmailSearchRequest,
    WorkspaceGmailSendRequest,
    WorkspaceGmailThreadRequest,
    WorkspaceSheetsAppendRequest,
)


class _FakeURL:
    def __init__(self, path="/api/v1/agent-control/workspace/status"):
        self.path = path


class _FakeRequest:
    method = "POST"

    def __init__(self, path="/api/v1/agent-control/workspace/status"):
        self.url = _FakeURL(path)


class _FakeDB:
    def __init__(self):
        self.added = []
        self.flush = AsyncMock()

    def add(self, item):
        self.added.append(item)


class AgentControlWorkspaceActionTests(unittest.IsolatedAsyncioTestCase):
    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.create_gmail_draft")
    async def test_gmail_draft_route_creates_draft_and_audits(self, mock_create, mock_load):
        mock_create.return_value = {"id": "draft-123", "message_id": "msg-123"}
        db = _FakeDB()

        result = await agent_control.workspace_gmail_draft(
            payload=WorkspaceGmailDraftRequest(
                to=["client@example.com"],
                subject="Follow up",
                body_text="Thanks for your time.",
            ),
            request=_FakeRequest("/api/v1/agent-control/workspace/gmail/draft"),
            db=db,
            agent={"actor": "hermes"},
        )

        mock_load.assert_awaited_once_with(db)
        mock_create.assert_called_once()
        self.assertEqual(result.draft_id, "draft-123")
        self.assertEqual(result.message_id, "msg-123")
        self.assertEqual(db.added[0].action_id, "workspace.gmail.draft.create")

    @patch("routers.agent_control._audit", new_callable=AsyncMock)
    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.send_gmail_message", create=True)
    @patch(
        "routers.agent_control.send_agent_gmail_with_origin",
        new_callable=AsyncMock,
        create=True,
    )
    async def test_gmail_send_route_requires_confirmation_before_any_send_path(
        self,
        durable_send,
        legacy_send,
        legacy_token_load,
        legacy_audit,
    ):
        db = _FakeDB()

        with self.assertRaises(HTTPException) as raised:
            await agent_control.workspace_gmail_send(
                payload=WorkspaceGmailSendRequest(
                    request_id=uuid4(),
                    to=["client@example.com"],
                    subject="Confirmed",
                    body_text="We are confirmed.",
                    confirmed_by_brandon=False,
                ),
                request=_FakeRequest("/api/v1/agent-control/workspace/gmail/send"),
                db=db,
                agent={"actor": "hermes"},
            )

        self.assertEqual(raised.exception.status_code, 422)
        durable_send.assert_not_awaited()
        legacy_token_load.assert_not_awaited()
        legacy_send.assert_not_called()
        legacy_audit.assert_not_awaited()
        self.assertEqual(db.added, [])

    @patch("routers.agent_control._audit", new_callable=AsyncMock)
    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.send_gmail_message", create=True)
    @patch(
        "routers.agent_control.send_agent_gmail_with_origin",
        new_callable=AsyncMock,
        create=True,
    )
    async def test_gmail_send_route_delegates_to_durable_origin_only(
        self,
        durable_send,
        legacy_send,
        legacy_token_load,
        legacy_audit,
    ):
        request_id = uuid4()
        durable_send.return_value = SimpleNamespace(
            request_id=request_id,
            message_id="sent-123",
            thread_id="thread-123",
            delivery_state="succeeded",
            replayed=False,
        )
        db = _FakeDB()
        request = _FakeRequest("/api/v1/agent-control/workspace/gmail/send")
        payload = WorkspaceGmailSendRequest(
            request_id=request_id,
            to=["client@example.com"],
            subject="Confirmed",
            body_text="We are confirmed.",
            confirmed_by_brandon=True,
            confirmation_note="Approved in Telegram by Brandon.",
        )

        result = await agent_control.workspace_gmail_send(
            payload=payload,
            request=request,
            db=db,
            agent={"actor": "hermes"},
        )

        durable_send.assert_awaited_once_with(
            db=db,
            payload=payload,
            request=request,
            actor="hermes",
        )
        legacy_token_load.assert_not_awaited()
        legacy_send.assert_not_called()
        legacy_audit.assert_not_awaited()
        self.assertEqual(result.request_id, request_id)
        self.assertEqual(result.message_id, "sent-123")
        self.assertEqual(result.thread_id, "thread-123")
        self.assertEqual(result.delivery_state, "succeeded")
        self.assertFalse(result.replayed)
        self.assertEqual(db.added, [])

    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.search_drive_files")
    async def test_drive_search_route_returns_files_and_audits(self, mock_search, mock_load):
        mock_search.return_value = [
            {
                "id": "file-1",
                "name": "Listing Notes",
                "mime_type": "application/vnd.google-apps.document",
                "web_view_link": "https://docs.google.com/document/d/file-1/edit",
                "modified_time": "2026-06-02T12:00:00Z",
            }
        ]
        db = _FakeDB()

        result = await agent_control.workspace_drive_search(
            payload=WorkspaceDriveSearchRequest(query="name contains 'Listing'", page_size=50),
            request=_FakeRequest("/api/v1/agent-control/workspace/drive/search"),
            db=db,
            agent={"actor": "hermes"},
        )

        mock_load.assert_awaited_once_with(db)
        mock_search.assert_called_once_with("name contains 'Listing'", page_size=25)
        self.assertEqual(result.files[0].id, "file-1")
        self.assertEqual(db.added[0].action_id, "workspace.drive.search")

    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.create_google_doc")
    async def test_docs_create_route_returns_document_and_audits(self, mock_create, mock_load):
        mock_create.return_value = {
            "document_id": "doc-123",
            "title": "Buyer Notes",
            "url": "https://docs.google.com/document/d/doc-123/edit",
        }
        db = _FakeDB()

        result = await agent_control.workspace_docs_create(
            payload=WorkspaceDocsCreateRequest(
                title="Buyer Notes",
                body_text="Buyer consultation notes.",
            ),
            request=_FakeRequest("/api/v1/agent-control/workspace/docs/create"),
            db=db,
            agent={"actor": "hermes"},
        )

        mock_load.assert_awaited_once_with(db)
        mock_create.assert_called_once_with("Buyer Notes", "Buyer consultation notes.")
        self.assertEqual(result.document_id, "doc-123")
        self.assertEqual(db.added[0].action_id, "workspace.docs.create")

    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.append_sheet_values")
    async def test_sheets_append_route_returns_update_counts_and_audits(self, mock_append, mock_load):
        mock_append.return_value = {
            "spreadsheet_id": "sheet-123",
            "updated_range": "Sheet1!A2:B2",
            "updated_rows": 1,
            "updated_columns": 2,
            "updated_cells": 2,
        }
        db = _FakeDB()

        result = await agent_control.workspace_sheets_append(
            payload=WorkspaceSheetsAppendRequest(
                spreadsheet_id="sheet-123",
                range_name="Sheet1!A:B",
                values=[["Name", "Status"]],
            ),
            request=_FakeRequest("/api/v1/agent-control/workspace/sheets/append"),
            db=db,
            agent={"actor": "hermes"},
        )

        mock_load.assert_awaited_once_with(db)
        mock_append.assert_called_once()
        self.assertEqual(result.updated_range, "Sheet1!A2:B2")
        self.assertEqual(result.updated_rows, 1)
        self.assertEqual(db.added[0].action_id, "workspace.sheets.append")

    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.search_gmail_messages")
    async def test_gmail_search_route_returns_messages_and_audits(self, mock_search, mock_load):
        mock_search.return_value = [
            {
                "id": "msg-1",
                "thread_id": "thread-1",
                "snippet": "Thanks for the showing.",
                "subject": "Showing follow-up",
                "from_email": "Jane Client <jane@example.com>",
                "to_email": "brandon@soldwithsweeney.com",
                "date": "Tue, 02 Jun 2026 14:00:00 -0400",
            }
        ]
        db = _FakeDB()

        result = await agent_control.workspace_gmail_search(
            payload=WorkspaceGmailSearchRequest(query="from:jane@example.com", page_size=50),
            request=_FakeRequest("/api/v1/agent-control/workspace/gmail/search"),
            db=db,
            agent={"actor": "hermes"},
        )

        mock_load.assert_awaited_once_with(db)
        mock_search.assert_called_once_with("from:jane@example.com", page_size=25)
        self.assertEqual(result.messages[0].id, "msg-1")
        self.assertEqual(result.messages[0].subject, "Showing follow-up")
        self.assertEqual(db.added[0].action_id, "workspace.gmail.search")

    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.get_gmail_thread")
    async def test_gmail_thread_route_returns_body_without_auditing_body_text(self, mock_thread, mock_load):
        mock_thread.return_value = {
            "thread_id": "thread-1",
            "messages": [
                {
                    "id": "msg-1",
                    "thread_id": "thread-1",
                    "snippet": "Detailed client",
                    "subject": "Buyer needs",
                    "from_email": "Jane Client <jane@example.com>",
                    "to_email": "brandon@soldwithsweeney.com",
                    "date": "Tue, 02 Jun 2026 14:00:00 -0400",
                    "body_text": "Detailed client message body.",
                    "body_truncated": False,
                }
            ],
        }
        db = _FakeDB()

        result = await agent_control.workspace_gmail_thread(
            payload=WorkspaceGmailThreadRequest(thread_id="thread-1", max_body_chars=4000),
            request=_FakeRequest("/api/v1/agent-control/workspace/gmail/thread"),
            db=db,
            agent={"actor": "hermes"},
        )

        mock_load.assert_awaited_once_with(db)
        mock_thread.assert_called_once_with("thread-1", max_body_chars=4000)
        self.assertEqual(result.messages[0].body_text, "Detailed client message body.")
        self.assertEqual(db.added[0].action_id, "workspace.gmail.thread.read")
        self.assertNotIn("Detailed client message body", db.added[0].request_meta_json)
        self.assertNotIn("Detailed client message body", db.added[0].response_meta_json)

    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.read_drive_file")
    async def test_drive_file_route_returns_text_and_audits_without_content(self, mock_read, mock_load):
        mock_read.return_value = {
            "id": "doc-1",
            "name": "Buyer Consultation",
            "mime_type": "application/vnd.google-apps.document",
            "web_view_link": "https://docs.google.com/document/d/doc-1/edit",
            "modified_time": "2026-06-02T12:00:00Z",
            "content_text": "Sensitive consultation notes.",
            "truncated": False,
        }
        db = _FakeDB()

        result = await agent_control.workspace_drive_file_read(
            payload=WorkspaceDriveFileReadRequest(file_id="doc-1", max_chars=4000),
            request=_FakeRequest("/api/v1/agent-control/workspace/drive/file"),
            db=db,
            agent={"actor": "hermes"},
        )

        mock_load.assert_awaited_once_with(db)
        mock_read.assert_called_once_with("doc-1", max_chars=4000)
        self.assertEqual(result.content_text, "Sensitive consultation notes.")
        self.assertEqual(db.added[0].action_id, "workspace.drive.file.read")
        self.assertNotIn("Sensitive consultation notes", db.added[0].response_meta_json)

    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.list_calendar_events")
    async def test_calendar_events_route_returns_events_and_audits(self, mock_events, mock_load):
        start = datetime(2026, 6, 3, 13, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 3, 21, 0, tzinfo=timezone.utc)
        mock_events.return_value = [
            {
                "id": "event-1",
                "summary": "Buyer strategy call",
                "start": "2026-06-03T10:00:00-04:00",
                "end": "2026-06-03T11:00:00-04:00",
                "location": "Google Meet",
                "html_link": "https://calendar.google.com/event?eid=event-1",
                "attendee_count": 1,
            }
        ]
        db = _FakeDB()

        result = await agent_control.workspace_calendar_events(
            payload=WorkspaceCalendarEventsRequest(
                time_min=start,
                time_max=end,
                page_size=50,
            ),
            request=_FakeRequest("/api/v1/agent-control/workspace/calendar/events"),
            db=db,
            agent={"actor": "hermes"},
        )

        mock_load.assert_awaited_once_with(db)
        mock_events.assert_called_once_with(start, end, page_size=25, calendar_id="primary")
        self.assertEqual(result.events[0].id, "event-1")
        self.assertEqual(db.added[0].action_id, "workspace.calendar.events.read")

    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.create_workspace_calendar_event")
    async def test_calendar_event_create_requires_confirmation(self, mock_create, mock_load):
        start = datetime(2026, 6, 3, 14, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 3, 15, 0, tzinfo=timezone.utc)
        db = _FakeDB()

        with self.assertRaises(HTTPException) as raised:
            await agent_control.workspace_calendar_event_create(
                payload=WorkspaceCalendarCreateEventRequest(
                    summary="Buyer strategy call",
                    start=start,
                    end=end,
                    attendees=["jane@example.com"],
                    confirmed_by_brandon=False,
                ),
                request=_FakeRequest("/api/v1/agent-control/workspace/calendar/event/create"),
                db=db,
                agent={"actor": "hermes"},
            )

        self.assertEqual(raised.exception.status_code, 422)
        mock_load.assert_not_awaited()
        mock_create.assert_not_called()
        self.assertEqual(db.added, [])

    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.create_workspace_calendar_event")
    async def test_calendar_event_create_when_confirmed_and_audits_without_attendees(
        self,
        mock_create,
        mock_load,
    ):
        start = datetime(2026, 6, 3, 14, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 3, 15, 0, tzinfo=timezone.utc)
        mock_create.return_value = {
            "event_id": "event-123",
            "html_link": "https://calendar.google.com/event?eid=event-123",
        }
        db = _FakeDB()

        result = await agent_control.workspace_calendar_event_create(
            payload=WorkspaceCalendarCreateEventRequest(
                summary="Buyer strategy call",
                start=start,
                end=end,
                attendees=["jane@example.com"],
                location="Google Meet",
                description="Intro call.",
                confirmed_by_brandon=True,
                confirmation_note="Approved in Telegram.",
            ),
            request=_FakeRequest("/api/v1/agent-control/workspace/calendar/event/create"),
            db=db,
            agent={"actor": "hermes"},
        )

        mock_load.assert_awaited_once_with(db)
        mock_create.assert_called_once()
        self.assertEqual(result.event_id, "event-123")
        self.assertEqual(result.attendee_count, 1)
        self.assertEqual(db.added[0].action_id, "workspace.calendar.event.create")
        request_meta = json.loads(db.added[0].request_meta_json)
        self.assertEqual(request_meta["attendee_count"], 1)
        self.assertNotIn("jane@example.com", db.added[0].request_meta_json)

    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.search_contacts")
    async def test_contacts_search_route_returns_contacts_and_audits_without_addresses(
        self,
        mock_contacts,
        mock_load,
    ):
        mock_contacts.return_value = [
            {
                "resource_name": "people/contact-1",
                "display_name": "Jane Client",
                "email_addresses": ["jane@example.com"],
                "phone_numbers": ["978-555-0100"],
            }
        ]
        db = _FakeDB()

        result = await agent_control.workspace_contacts_search(
            payload=WorkspaceContactsSearchRequest(query="Jane", page_size=50),
            request=_FakeRequest("/api/v1/agent-control/workspace/contacts/search"),
            db=db,
            agent={"actor": "hermes"},
        )

        mock_load.assert_awaited_once_with(db)
        mock_contacts.assert_called_once_with("Jane", page_size=25)
        self.assertEqual(result.contacts[0].display_name, "Jane Client")
        self.assertEqual(result.contacts[0].email_addresses, ["jane@example.com"])
        self.assertEqual(db.added[0].action_id, "workspace.contacts.search")
        self.assertNotIn("jane@example.com", db.added[0].response_meta_json)


if __name__ == "__main__":
    unittest.main()
