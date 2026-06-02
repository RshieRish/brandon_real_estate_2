import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from routers import agent_control
from schemas.agent_control import (
    WorkspaceDocsCreateRequest,
    WorkspaceDriveSearchRequest,
    WorkspaceGmailDraftRequest,
    WorkspaceGmailSendRequest,
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

    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.send_gmail_message")
    async def test_gmail_send_route_requires_confirmation(self, mock_send, mock_load):
        db = _FakeDB()

        with self.assertRaises(HTTPException) as raised:
            await agent_control.workspace_gmail_send(
                payload=WorkspaceGmailSendRequest(
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
        mock_load.assert_not_awaited()
        mock_send.assert_not_called()
        self.assertEqual(db.added, [])

    @patch("routers.agent_control.load_workspace_refresh_token_from_db", new_callable=AsyncMock)
    @patch("routers.agent_control.send_gmail_message")
    async def test_gmail_send_route_sends_when_confirmed_and_audits(self, mock_send, mock_load):
        mock_send.return_value = {"id": "sent-123", "thread_id": "thread-123"}
        db = _FakeDB()

        result = await agent_control.workspace_gmail_send(
            payload=WorkspaceGmailSendRequest(
                to=["client@example.com"],
                subject="Confirmed",
                body_text="We are confirmed.",
                confirmed_by_brandon=True,
                confirmation_note="Approved in Telegram by Brandon.",
            ),
            request=_FakeRequest("/api/v1/agent-control/workspace/gmail/send"),
            db=db,
            agent={"actor": "hermes"},
        )

        mock_load.assert_awaited_once_with(db)
        mock_send.assert_called_once()
        self.assertEqual(result.message_id, "sent-123")
        self.assertEqual(result.thread_id, "thread-123")
        self.assertEqual(db.added[0].action_id, "workspace.gmail.send")

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


if __name__ == "__main__":
    unittest.main()
