import base64
import unittest
from datetime import datetime, timezone
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
        gmail.users.return_value.messages.return_value.send.return_value.execute.assert_called_once_with(
            num_retries=0
        )
        self.assertEqual(result["id"], "sent-123")
        self.assertEqual(result["thread_id"], "thread-123")

    @patch("services.workspace_service.build_workspace_service")
    def test_send_gmail_message_uses_caller_supplied_bound_client_without_global_token(
        self,
        mock_build,
    ):
        bound_gmail = Mock()
        bound_gmail.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "bound-sent-123",
            "threadId": "bound-thread-123",
        }

        result = workspace_service.send_gmail_message(
            to=["client@example.com"],
            subject="Bound account",
            body_text="Use the database-bound credential.",
            gmail_client=bound_gmail,
        )

        mock_build.assert_not_called()
        bound_gmail.users.return_value.messages.return_value.send.assert_called_once()
        bound_gmail.users.return_value.messages.return_value.send.return_value.execute.assert_called_once_with(
            num_retries=0
        )
        self.assertEqual(
            result,
            {"id": "bound-sent-123", "thread_id": "bound-thread-123"},
        )

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

    @patch("services.workspace_service.build_workspace_service")
    def test_search_gmail_messages_returns_compact_metadata(self, mock_build):
        gmail = Mock()
        gmail.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg-1", "threadId": "thread-1"}]
        }
        gmail.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg-1",
            "threadId": "thread-1",
            "snippet": "Thanks for the showing.",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Showing follow-up"},
                    {"name": "From", "value": "Jane Client <jane@example.com>"},
                    {"name": "To", "value": "brandon@soldwithsweeney.com"},
                    {"name": "Date", "value": "Tue, 02 Jun 2026 14:00:00 -0400"},
                ]
            },
        }
        mock_build.return_value = gmail

        result = workspace_service.search_gmail_messages("from:jane@example.com", page_size=99)

        mock_build.assert_called_once_with("gmail", "v1")
        list_kwargs = gmail.users.return_value.messages.return_value.list.call_args.kwargs
        self.assertEqual(list_kwargs["userId"], "me")
        self.assertEqual(list_kwargs["q"], "from:jane@example.com")
        self.assertEqual(list_kwargs["maxResults"], 25)
        get_kwargs = gmail.users.return_value.messages.return_value.get.call_args.kwargs
        self.assertEqual(get_kwargs["format"], "metadata")
        self.assertEqual(result[0]["id"], "msg-1")
        self.assertEqual(result[0]["thread_id"], "thread-1")
        self.assertEqual(result[0]["subject"], "Showing follow-up")
        self.assertEqual(result[0]["from_email"], "Jane Client <jane@example.com>")

    @patch("services.workspace_service.build_workspace_service")
    def test_get_gmail_thread_extracts_plain_text_body(self, mock_build):
        gmail = Mock()
        encoded_body = base64.urlsafe_b64encode(b"Detailed client message body.").decode("utf-8")
        gmail.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "thread-1",
            "messages": [
                {
                    "id": "msg-1",
                    "threadId": "thread-1",
                    "snippet": "Detailed client",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Buyer needs"},
                            {"name": "From", "value": "Jane Client <jane@example.com>"},
                            {"name": "To", "value": "brandon@soldwithsweeney.com"},
                            {"name": "Date", "value": "Tue, 02 Jun 2026 14:00:00 -0400"},
                        ],
                        "parts": [
                            {
                                "mimeType": "text/plain",
                                "body": {"data": encoded_body},
                            }
                        ],
                    },
                }
            ],
        }
        mock_build.return_value = gmail

        result = workspace_service.get_gmail_thread("thread-1", max_body_chars=4000)

        mock_build.assert_called_once_with("gmail", "v1")
        get_kwargs = gmail.users.return_value.threads.return_value.get.call_args.kwargs
        self.assertEqual(get_kwargs["userId"], "me")
        self.assertEqual(get_kwargs["id"], "thread-1")
        self.assertEqual(get_kwargs["format"], "full")
        self.assertEqual(result["thread_id"], "thread-1")
        self.assertEqual(result["messages"][0]["body_text"], "Detailed client message body.")

    @patch("services.workspace_service.build_workspace_service")
    def test_read_drive_file_exports_google_doc_text(self, mock_build):
        drive = Mock()
        drive.files.return_value.get.return_value.execute.return_value = {
            "id": "doc-1",
            "name": "Buyer Consultation",
            "mimeType": "application/vnd.google-apps.document",
            "webViewLink": "https://docs.google.com/document/d/doc-1/edit",
            "modifiedTime": "2026-06-02T12:00:00Z",
        }
        drive.files.return_value.export.return_value.execute.return_value = b"Buyer notes text."
        mock_build.return_value = drive

        result = workspace_service.read_drive_file("doc-1", max_chars=4000)

        mock_build.assert_called_once_with("drive", "v3")
        drive.files.return_value.get.assert_called_once()
        export_kwargs = drive.files.return_value.export.call_args.kwargs
        self.assertEqual(export_kwargs["fileId"], "doc-1")
        self.assertEqual(export_kwargs["mimeType"], "text/plain")
        self.assertEqual(result["id"], "doc-1")
        self.assertEqual(result["content_text"], "Buyer notes text.")
        self.assertFalse(result["truncated"])

    @patch("services.workspace_service.build_workspace_service")
    def test_list_calendar_events_returns_event_summaries(self, mock_build):
        calendar = Mock()
        calendar.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "event-1",
                    "summary": "Buyer strategy call",
                    "location": "Google Meet",
                    "htmlLink": "https://calendar.google.com/event?eid=event-1",
                    "start": {"dateTime": "2026-06-03T10:00:00-04:00"},
                    "end": {"dateTime": "2026-06-03T11:00:00-04:00"},
                    "attendees": [{"email": "jane@example.com"}],
                }
            ]
        }
        mock_build.return_value = calendar
        start = datetime(2026, 6, 3, 13, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 3, 21, 0, tzinfo=timezone.utc)

        result = workspace_service.list_calendar_events(start, end, page_size=99)

        mock_build.assert_called_once_with("calendar", "v3")
        list_kwargs = calendar.events.return_value.list.call_args.kwargs
        self.assertEqual(list_kwargs["calendarId"], "primary")
        self.assertEqual(list_kwargs["maxResults"], 25)
        self.assertEqual(list_kwargs["timeMin"], start.isoformat())
        self.assertEqual(result[0]["id"], "event-1")
        self.assertEqual(result[0]["attendee_count"], 1)

    @patch("services.workspace_service.build_workspace_service")
    def test_create_workspace_calendar_event_inserts_with_attendees(self, mock_build):
        calendar = Mock()
        calendar.events.return_value.insert.return_value.execute.return_value = {
            "id": "event-123",
            "htmlLink": "https://calendar.google.com/event?eid=event-123",
        }
        mock_build.return_value = calendar
        start = datetime(2026, 6, 3, 14, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 3, 15, 0, tzinfo=timezone.utc)

        result = workspace_service.create_workspace_calendar_event(
            summary="Buyer strategy call",
            start=start,
            end=end,
            attendees=["jane@example.com"],
            location="Google Meet",
            description="Intro call.",
        )

        mock_build.assert_called_once_with("calendar", "v3")
        insert_kwargs = calendar.events.return_value.insert.call_args.kwargs
        self.assertEqual(insert_kwargs["calendarId"], "primary")
        self.assertEqual(insert_kwargs["sendUpdates"], "all")
        self.assertEqual(insert_kwargs["body"]["attendees"], [{"email": "jane@example.com"}])
        self.assertEqual(insert_kwargs["body"]["start"]["dateTime"], start.isoformat())
        self.assertEqual(result["event_id"], "event-123")

    @patch("services.workspace_service.build_workspace_service")
    def test_search_contacts_returns_compact_contact_summaries(self, mock_build):
        people = Mock()
        people.people.return_value.searchContacts.return_value.execute.return_value = {
            "results": [
                {
                    "person": {
                        "resourceName": "people/contact-1",
                        "names": [{"displayName": "Jane Client"}],
                        "emailAddresses": [{"value": "jane@example.com"}],
                        "phoneNumbers": [{"value": "978-555-0100"}],
                    }
                }
            ]
        }
        mock_build.return_value = people

        result = workspace_service.search_contacts("Jane", page_size=99)

        mock_build.assert_called_once_with("people", "v1")
        search_kwargs = people.people.return_value.searchContacts.call_args.kwargs
        self.assertEqual(search_kwargs["query"], "Jane")
        self.assertEqual(search_kwargs["pageSize"], 25)
        self.assertEqual(result[0]["resource_name"], "people/contact-1")
        self.assertEqual(result[0]["display_name"], "Jane Client")
        self.assertEqual(result[0]["email_addresses"], ["jane@example.com"])


if __name__ == "__main__":
    unittest.main()
