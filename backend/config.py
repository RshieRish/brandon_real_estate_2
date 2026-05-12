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
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    CORS_ORIGINS: str = "http://localhost:3000"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    KW_CRM_API_KEY: str = ""
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
    BLOG_AUTO_POST_ENABLED: bool = True
    BLOG_AUTO_POST_INTERVAL_HOURS: int = 72


settings = Settings()
