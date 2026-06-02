"""Google Workspace OAuth routes for Brandon's full-access agent connector."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.auth import require_admin
from models.setting import Setting
from services.workspace_service import (
    WorkspaceIntegrationError,
    exchange_code,
    get_auth_url,
    get_workspace_connection_status,
)

router = APIRouter()
WORKSPACE_OAUTH_STATE_TTL_MINUTES = 10
WORKSPACE_REFRESH_TOKEN_KEY = "google_workspace_refresh_token"


async def load_workspace_refresh_token_from_db(db: AsyncSession) -> str:
    if settings.GOOGLE_WORKSPACE_REFRESH_TOKEN:
        return settings.GOOGLE_WORKSPACE_REFRESH_TOKEN

    result = await db.execute(select(Setting).where(Setting.key == WORKSPACE_REFRESH_TOKEN_KEY))
    token_setting = result.scalar_one_or_none()
    if token_setting and token_setting.value:
        settings.GOOGLE_WORKSPACE_REFRESH_TOKEN = token_setting.value
        return token_setting.value

    return ""


async def persist_workspace_refresh_token_to_db(db: AsyncSession, refresh_token: str) -> None:
    result = await db.execute(select(Setting).where(Setting.key == WORKSPACE_REFRESH_TOKEN_KEY))
    token_setting = result.scalar_one_or_none()
    if token_setting:
        token_setting.value = refresh_token
        return

    db.add(Setting(key=WORKSPACE_REFRESH_TOKEN_KEY, value=refresh_token))


def build_workspace_oauth_state(admin_payload: dict) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=WORKSPACE_OAUTH_STATE_TTL_MINUTES)
    return jwt.encode(
        {
            "sub": admin_payload.get("sub"),
            "purpose": "workspace_oauth",
            "exp": expires,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_workspace_oauth_state(state: str) -> dict:
    try:
        payload = jwt.decode(
            state,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid Workspace authorization state.") from exc

    if payload.get("purpose") != "workspace_oauth":
        raise HTTPException(status_code=401, detail="Invalid Workspace authorization state.")

    return payload


def is_workspace_oauth_state(state: str | None) -> bool:
    if not state:
        return False

    try:
        decode_workspace_oauth_state(state)
    except HTTPException:
        return False

    return True


def render_workspace_oauth_page(title: str, message: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <style>
      :root {{
        color-scheme: dark;
      }}
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #0a0a0a;
        color: #ffffff;
        font-family: Montserrat, Arial, sans-serif;
      }}
      main {{
        width: min(520px, calc(100vw - 32px));
        border: 1px solid rgba(234, 196, 105, 0.24);
        background: rgba(18, 18, 18, 0.92);
        padding: 32px;
        border-radius: 24px;
        box-shadow: 0 32px 80px rgba(0, 0, 0, 0.5);
      }}
      h1 {{
        margin: 0 0 12px;
        font-size: 28px;
        color: #eac469;
      }}
      p {{
        margin: 0;
        line-height: 1.6;
        color: rgba(255, 255, 255, 0.76);
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>{title}</h1>
      <p>{message}</p>
    </main>
  </body>
</html>"""


async def complete_workspace_oauth_callback(
    code: str | None,
    state: str | None,
    error: str | None,
    db: AsyncSession,
) -> HTMLResponse:
    if error:
        return HTMLResponse(
            render_workspace_oauth_page(
                "Workspace Not Connected",
                f"Google returned an error: {error}. Please close this tab and try again from Settings.",
            ),
            status_code=400,
        )

    if not code or not state:
        return HTMLResponse(
            render_workspace_oauth_page(
                "Workspace Not Connected",
                "Google did not return the authorization details we expected. Please close this tab and try again.",
            ),
            status_code=400,
        )

    try:
        decode_workspace_oauth_state(state)
        refresh_token = exchange_code(code, state)
        await persist_workspace_refresh_token_to_db(db, refresh_token)
    except HTTPException as exc:
        return HTMLResponse(
            render_workspace_oauth_page("Workspace Not Connected", exc.detail),
            status_code=exc.status_code,
        )
    except WorkspaceIntegrationError as exc:
        return HTMLResponse(
            render_workspace_oauth_page("Workspace Not Connected", str(exc)),
            status_code=503,
        )

    return HTMLResponse(
        render_workspace_oauth_page(
            "Workspace Connected",
            "Brandon's Google Workspace is now connected for approved Hermes workflows. You can close this tab and refresh the Settings page.",
        )
    )


@router.get("/status")
async def workspace_status(
    _: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await load_workspace_refresh_token_from_db(db)
    return get_workspace_connection_status()


@router.get("/auth-url")
async def workspace_auth_url(admin_payload: dict = Depends(require_admin)):
    auth_url, _ = get_auth_url(build_workspace_oauth_state(admin_payload))
    return {"auth_url": auth_url}


@router.get("/callback", response_class=HTMLResponse)
async def workspace_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await complete_workspace_oauth_callback(code=code, state=state, error=error, db=db)
