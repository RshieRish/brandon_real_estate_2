"""Google Workspace OAuth and service clients for Brandon's agent access."""

import logging
from pathlib import Path

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
