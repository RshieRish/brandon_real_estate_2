import unittest
from unittest.mock import Mock, patch

from services import workspace_service


class WorkspaceActionServiceTests(unittest.TestCase):
    @patch("services.workspace_service.build_workspace_service")
    def test_create_gmail_draft_creates_raw_message_draft(self, mock_build):
        gmail = Mock()
        gmail.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
            "id": "draft-123",
            "message": {"id": "msg-123"},
        }
        mock_build.return_value = gmail

        result = workspace_service.create_gmail_draft(
            to=["client@example.com"],
            subject="Showing follow-up",
            body_text="Thanks for touring today.",
            cc=["assistant@example.com"],
        )

        mock_build.assert_called_once_with("gmail", "v1")
        gmail.users.return_value.drafts.return_value.create.assert_called_once()
        create_kwargs = gmail.users.return_value.drafts.return_value.create.call_args.kwargs
        self.assertEqual(create_kwargs["userId"], "me")
        self.assertIn("raw", create_kwargs["body"]["message"])
        self.assertEqual(result["id"], "draft-123")
        self.assertEqual(result["message_id"], "msg-123")

    @patch("services.workspace_service.build_workspace_service")
    def test_send_gmail_message_sends_raw_message(self, mock_build):
        gmail = Mock()
        gmail.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "sent-123",
            "threadId": "thread-123",
        }
        mock_build.return_value = gmail

        result = workspace_service.send_gmail_message(
            to=["client@example.com"],
            subject="Confirmed",
            body_text="We are confirmed.",
        )

        mock_build.assert_called_once_with("gmail", "v1")
        gmail.users.return_value.messages.return_value.send.assert_called_once()
        send_kwargs = gmail.users.return_value.messages.return_value.send.call_args.kwargs
        self.assertEqual(send_kwargs["userId"], "me")
        self.assertIn("raw", send_kwargs["body"])
        self.assertEqual(result["id"], "sent-123")
        self.assertEqual(result["thread_id"], "thread-123")

    @patch("services.workspace_service.build_workspace_service")
    def test_search_drive_files_returns_file_summaries(self, mock_build):
        drive = Mock()
        drive.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "file-1",
                    "name": "Listing Notes",
                    "mimeType": "application/vnd.google-apps.document",
                    "webViewLink": "https://docs.google.com/document/d/file-1/edit",
                    "modifiedTime": "2026-06-02T12:00:00Z",
                }
            ]
        }
        mock_build.return_value = drive

        result = workspace_service.search_drive_files("name contains 'Listing'", page_size=50)

        mock_build.assert_called_once_with("drive", "v3")
        list_kwargs = drive.files.return_value.list.call_args.kwargs
        self.assertEqual(list_kwargs["q"], "name contains 'Listing'")
        self.assertEqual(list_kwargs["pageSize"], 25)
        self.assertEqual(result[0]["id"], "file-1")
        self.assertEqual(result[0]["name"], "Listing Notes")

    @patch("services.workspace_service.build_workspace_service")
    def test_create_google_doc_creates_document_and_inserts_text(self, mock_build):
        docs = Mock()
        docs.documents.return_value.create.return_value.execute.return_value = {
            "documentId": "doc-123",
            "title": "Client Follow Up",
        }
        docs.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{}]
        }
        mock_build.return_value = docs

        result = workspace_service.create_google_doc(
            title="Client Follow Up",
            body_text="Next steps for the buyer consultation.",
        )

        mock_build.assert_called_once_with("docs", "v1")
        docs.documents.return_value.create.assert_called_once_with(body={"title": "Client Follow Up"})
        docs.documents.return_value.batchUpdate.assert_called_once()
        self.assertEqual(result["document_id"], "doc-123")
        self.assertEqual(result["title"], "Client Follow Up")
        self.assertEqual(result["url"], "https://docs.google.com/document/d/doc-123/edit")

    @patch("services.workspace_service.build_workspace_service")
    def test_append_sheet_values_appends_rows(self, mock_build):
        sheets = Mock()
        sheets.spreadsheets.return_value.values.return_value.append.return_value.execute.return_value = {
            "spreadsheetId": "sheet-123",
            "updates": {
                "updatedRange": "Sheet1!A2:B2",
                "updatedRows": 1,
                "updatedColumns": 2,
                "updatedCells": 2,
            },
        }
        mock_build.return_value = sheets

        result = workspace_service.append_sheet_values(
            spreadsheet_id="sheet-123",
            range_name="Sheet1!A:B",
            values=[["Name", "Status"]],
        )

        mock_build.assert_called_once_with("sheets", "v4")
        append_kwargs = sheets.spreadsheets.return_value.values.return_value.append.call_args.kwargs
        self.assertEqual(append_kwargs["spreadsheetId"], "sheet-123")
        self.assertEqual(append_kwargs["range"], "Sheet1!A:B")
        self.assertEqual(append_kwargs["body"], {"values": [["Name", "Status"]]})
        self.assertEqual(result["updated_range"], "Sheet1!A2:B2")
        self.assertEqual(result["updated_rows"], 1)


if __name__ == "__main__":
    unittest.main()
