from dataclasses import dataclass, field

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = ""
    GEMINI_API_KEY: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_CALENDAR_CLIENT_ID: str = ""
    GOOGLE_CALENDAR_CLIENT_SECRET: str = ""
    GOOGLE_CALENDAR_REDIRECT_URI: str = "http://localhost:8000/api/v1/booking/calendar/callback"
    GOOGLE_WORKSPACE_CLIENT_ID: str = ""
    GOOGLE_WORKSPACE_CLIENT_SECRET: str = ""
    GOOGLE_WORKSPACE_REDIRECT_URI: str = ""
    GOOGLE_WORKSPACE_REFRESH_TOKEN: str = ""
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    CORS_ORIGINS: str = "http://localhost:3000"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    GOOGLE_MAPS_API_KEY: str = ""
    GOOGLE_CALENDAR_REFRESH_TOKEN: str = ""
    BRANDON_DEFAULT_LOCATION: str = "101 Broadway Rd #21, Dracut, MA 01826"
    TRAVEL_BUFFER_MINUTES: int = 10
    RENTCAST_API_KEY: str = ""
    # Blog image storage (Cloudflare R2 — optional, falls back to public/ dir)
    R2_ENDPOINT: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "sweeney-public"
    R2_PUBLIC_URL: str = ""
    R2_REGION: str = "auto"
    # Auto-blog scheduler (in-process). Set BLOG_AUTO_POST_ENABLED=false in dev
    # to silence the loop, or tune the cadence with BLOG_AUTO_POST_INTERVAL_HOURS.
    # Daily posting (24h) is the production cadence so each day picks a fresh topic.
    BLOG_AUTO_POST_ENABLED: bool = True
    BLOG_AUTO_POST_INTERVAL_HOURS: int = 24
    # Private Hermes/Atlas agent bridge. Keep disabled unless Railway env vars
    # explicitly turn it on and provide a bearer token.
    AGENT_CONTROL_TOKEN: str = ""
    AGENT_CONTROL_ENABLED: bool = False
    AGENT_CONTROL_RECENT_LIMIT: int = 10
    CRM_TASK_ARCHIVE_ENABLED: bool = False
    # Dedicated integration-worker rollout gates. They remain disabled until
    # each provider-specific migration and live verification gate is complete.
    GMAIL_TASK_INTAKE_ENABLED: bool = False
    SYDNEY_TASK_QUESTIONS_ENABLED: bool = False
    INSTAGRAM_INTEGRATION_ENABLED: bool = False
    # Gmail History needs a direct, session-affine PostgreSQL connection so
    # session advisory locks remain held across page-level commits.
    GMAIL_HISTORY_DATABASE_URL: str = ""
    # Required only while Gmail task intake is enabled. There is deliberately
    # no fallback because changing the key changes every participant digest.
    GMAIL_PARTICIPANT_HASH_KEY: str = ""
    # Required only while Sydney task questions are enabled. The keyring is a
    # JSON object of positive integer versions to base64-encoded 32-byte keys;
    # old versions remain configured until every pending row using them closes.
    SYDNEY_TELEGRAM_BOT_TOKEN: str = ""
    SYDNEY_TELEGRAM_BRANDON_CHAT_ID: str = ""
    SYDNEY_TELEGRAM_BRANDON_USER_ID: str = ""
    SYDNEY_CLARIFICATION_CODE_KEYS_JSON: str = ""
    SYDNEY_CLARIFICATION_ACTIVE_KEY_VERSION: int = 0
    INTEGRATION_WORKER_HEARTBEAT_SECONDS: int = 30
    INTEGRATION_WORKER_HEARTBEAT_MAX_AGE_SECONDS: int = 120
    INTEGRATION_PROVIDER_MAX_WORKERS: int = 4
    INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS: float = 10.0
    INTEGRATION_PROVIDER_DEADLINE_SECONDS: float = 30.0
    GMAIL_HISTORY_MAX_PAGES_PER_RUN: int = 100
    GMAIL_HISTORY_JOB_DEADLINE_SECONDS: float = 300.0
    # The receipt boundary must outlive the provider deadline so the worker can
    # durably finalize a timed-out extraction attempt before its lease closes.
    GMAIL_RECEIPT_PROCESSING_DEADLINE_SECONDS: float = 35.0
    GMAIL_RECEIPT_PROCESSING_STALE_AFTER_SECONDS: float = 120.0


@dataclass(frozen=True)
class WorkspaceOAuthClientSettings:
    """One internally consistent OAuth client tuple with a redacted secret."""

    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str


def _nonblank_setting(config: object, name: str) -> str:
    value = getattr(config, name, "")
    return value.strip() if isinstance(value, str) else ""


def resolve_workspace_oauth_client_settings(
    config: object,
) -> WorkspaceOAuthClientSettings | None:
    """Resolve one complete client tuple without mixing configuration sources."""

    for client_id_name, client_secret_name, redirect_uri_name in (
        (
            "GOOGLE_WORKSPACE_CLIENT_ID",
            "GOOGLE_WORKSPACE_CLIENT_SECRET",
            "GOOGLE_WORKSPACE_REDIRECT_URI",
        ),
        (
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_CALENDAR_REDIRECT_URI",
        ),
        (
            "GOOGLE_CALENDAR_CLIENT_ID",
            "GOOGLE_CALENDAR_CLIENT_SECRET",
            "GOOGLE_CALENDAR_REDIRECT_URI",
        ),
    ):
        client_id = _nonblank_setting(config, client_id_name)
        client_secret = _nonblank_setting(config, client_secret_name)
        redirect_uri = _nonblank_setting(config, redirect_uri_name)
        if client_id and client_secret and redirect_uri:
            return WorkspaceOAuthClientSettings(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
            )
    return None


settings = Settings()
