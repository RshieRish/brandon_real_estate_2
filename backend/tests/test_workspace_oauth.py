import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from config import settings
from services import workspace_service


class WorkspaceOAuthTests(unittest.TestCase):
    def test_full_access_scopes_include_core_workspace_apps(self):
        scopes = set(workspace_service.WORKSPACE_FULL_ACCESS_SCOPES)

        self.assertIn("https://mail.google.com/", scopes)
        self.assertIn("https://www.googleapis.com/auth/calendar", scopes)
        self.assertIn("https://www.googleapis.com/auth/drive", scopes)
        self.assertIn("https://www.googleapis.com/auth/documents", scopes)
        self.assertIn("https://www.googleapis.com/auth/spreadsheets", scopes)
        self.assertIn("https://www.googleapis.com/auth/presentations", scopes)
        self.assertIn("https://www.googleapis.com/auth/contacts", scopes)
        self.assertIn("https://www.googleapis.com/auth/tasks", scopes)

    @patch("services.workspace_service.Flow")
    def test_get_auth_url_requests_offline_access_with_full_consent_prompt(self, mock_flow_cls):
        mock_flow = Mock()
        mock_flow.authorization_url.return_value = ("https://example.com/workspace-auth", "oauth-state")
        mock_flow_cls.from_client_config.return_value = mock_flow

        auth_url, returned_state = workspace_service.get_auth_url("signed-state")

        self.assertEqual(auth_url, "https://example.com/workspace-auth")
        self.assertEqual(returned_state, "oauth-state")
        mock_flow.authorization_url.assert_called_once_with(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state="signed-state",
        )

    @patch("services.workspace_service.persist_refresh_token")
    @patch("services.workspace_service.Flow")
    def test_exchange_code_persists_refresh_token_and_updates_runtime_settings(
        self,
        mock_flow_cls,
        mock_persist_refresh_token,
    ):
        original_token = settings.GOOGLE_WORKSPACE_REFRESH_TOKEN
        mock_flow = Mock()
        mock_flow.credentials = Mock(refresh_token="fresh-workspace-token")
        mock_flow_cls.from_client_config.return_value = mock_flow

        try:
            refresh_token = workspace_service.exchange_code("sample-code", "signed-state")
        finally:
            settings.GOOGLE_WORKSPACE_REFRESH_TOKEN = original_token

        self.assertEqual(refresh_token, "fresh-workspace-token")
        mock_flow.fetch_token.assert_called_once_with(code="sample-code")
        mock_persist_refresh_token.assert_called_once_with("fresh-workspace-token")

    def test_persist_refresh_token_replaces_existing_env_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "GOOGLE_WORKSPACE_CLIENT_ID=test-client\n"
                "GOOGLE_WORKSPACE_REFRESH_TOKEN=old-token\n",
                encoding="utf-8",
            )

            workspace_service.persist_refresh_token("new-token", env_path=env_path)

            self.assertIn(
                "GOOGLE_WORKSPACE_REFRESH_TOKEN=new-token\n",
                env_path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
