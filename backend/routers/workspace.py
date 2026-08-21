"""Google Workspace OAuth routes for Brandon's full-access agent connector."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from html import escape
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from jose import JWTError, jwt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.auth import require_admin
from models.gmail_task_intake import GmailSyncAccount
from models.setting import Setting
from services.workspace_service import (
    WorkspaceOAuthIdentity,
    bind_workspace_refresh_token_for_request,
    get_auth_url,
    get_workspace_connection_status_bounded,
    run_workspace_oauth_exchange,
    validate_workspace_oauth_identity,
    workspace_oauth_client_id,
)

router = APIRouter()
WORKSPACE_OAUTH_STATE_TTL_MINUTES = 10
WORKSPACE_REFRESH_TOKEN_KEY = "google_workspace_refresh_token"
WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY = "google_workspace_gmail_account_id"
_WORKSPACE_GMAIL_BINDING_LOCK_KEY = 5_921_914_720_764_681_105


async def load_workspace_refresh_token_from_db(db: AsyncSession) -> str:
    result = await db.execute(select(Setting).where(Setting.key == WORKSPACE_REFRESH_TOKEN_KEY))
    token_setting = result.scalar_one_or_none()
    binding_result = await db.execute(
        select(Setting).where(
            Setting.key == WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY
        )
    )
    binding_setting = binding_result.scalar_one_or_none()
    if binding_setting is not None:
        try:
            bound_account_id = UUID(binding_setting.value)
        except (TypeError, ValueError, AttributeError):
            bind_workspace_refresh_token_for_request("")
            return ""
        bound_account = await db.get(GmailSyncAccount, bound_account_id)
        if (
            bound_account is None
            or not bound_account.workspace_email
            or bound_account.workspace_email
            != bound_account.workspace_email.strip().lower()
        ):
            bind_workspace_refresh_token_for_request("")
            return ""
        database_token = (
            token_setting.value
            if token_setting
            and token_setting.key == WORKSPACE_REFRESH_TOKEN_KEY
            and token_setting.value
            else ""
        )
        bind_workspace_refresh_token_for_request(database_token)
        return database_token

    if settings.GOOGLE_WORKSPACE_REFRESH_TOKEN:
        bind_workspace_refresh_token_for_request(
            settings.GOOGLE_WORKSPACE_REFRESH_TOKEN
        )
        return settings.GOOGLE_WORKSPACE_REFRESH_TOKEN

    if token_setting and token_setting.value:
        # Preserve the legacy unbound Workspace path until every caller passes
        # an explicit database credential. Bound Gmail accounts never enter it.
        settings.GOOGLE_WORKSPACE_REFRESH_TOKEN = token_setting.value
        bind_workspace_refresh_token_for_request(token_setting.value)
        return token_setting.value

    bind_workspace_refresh_token_for_request(None)
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
    safe_title = escape(title)
    safe_message = escape(message)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title}</title>
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
      <h1>{safe_title}</h1>
      <p>{safe_message}</p>
    </main>
  </body>
</html>"""


async def bind_workspace_gmail_identity(
    db: AsyncSession,
    identity: WorkspaceOAuthIdentity,
    *,
    before_binding_lock: Callable[[], Awaitable[None]] | None = None,
) -> GmailSyncAccount:
    """Bind one verified mailbox and token in the caller's transaction."""

    canonical_email = validate_workspace_oauth_identity(identity)
    if before_binding_lock is not None:
        await before_binding_lock()
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _WORKSPACE_GMAIL_BINDING_LOCK_KEY},
    )

    binding = await db.scalar(
        select(Setting)
        .where(Setting.key == WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY)
        .with_for_update()
    )
    account: GmailSyncAccount | None = None
    if binding is not None:
        try:
            account_id = UUID(binding.value)
        except (AttributeError, TypeError, ValueError):
            raise RuntimeError("workspace_binding_invalid") from None
        account = await db.scalar(
            select(GmailSyncAccount)
            .where(GmailSyncAccount.id == account_id)
            .with_for_update()
        )
        if account is None:
            raise RuntimeError("workspace_binding_invalid")
        if account.workspace_email != canonical_email:
            raise RuntimeError("workspace_account_rebind_forbidden")
    else:
        existing_accounts = list(
            (
                await db.scalars(
                    select(GmailSyncAccount)
                    .order_by(GmailSyncAccount.created_at, GmailSyncAccount.id)
                    .with_for_update()
                )
            ).all()
        )
        account = next(
            (
                row
                for row in existing_accounts
                if row.workspace_email == canonical_email
            ),
            None,
        )
        if account is None and existing_accounts:
            raise RuntimeError("workspace_account_rebind_forbidden")
        if account is None:
            account = GmailSyncAccount(
                workspace_email=canonical_email,
                committed_history_id=None,
                mode="shadow",
            )
            db.add(account)
            await db.flush()
        binding = Setting(
            key=WORKSPACE_GMAIL_ACCOUNT_BINDING_KEY,
            value=str(account.id),
        )
        db.add(binding)

    token_setting = await db.scalar(
        select(Setting)
        .where(Setting.key == WORKSPACE_REFRESH_TOKEN_KEY)
        .with_for_update()
    )
    if token_setting is None:
        db.add(
            Setting(
                key=WORKSPACE_REFRESH_TOKEN_KEY,
                value=identity.refresh_token,
            )
        )
    else:
        token_setting.value = identity.refresh_token

    if account.blocked_reason == "oauth_revoked":
        account.blocked_reason = None
        account.last_error_category = None
        account.last_error_message = None
    await db.flush()
    return account


async def _rollback_workspace_oauth(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        return


async def complete_workspace_oauth_callback(
    code: str | None,
    state: str | None,
    error: str | None,
    db: AsyncSession,
    *,
    oauth_exchange=None,
) -> HTMLResponse:
    if error:
        return HTMLResponse(
            render_workspace_oauth_page(
                "Workspace Not Connected",
                "Google authorization was not completed. Please close this tab "
                "and try again from Settings.",
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
    except HTTPException as exc:
        return HTMLResponse(
            render_workspace_oauth_page("Workspace Not Connected", exc.detail),
            status_code=exc.status_code,
        )

    try:
        if oauth_exchange is None:
            identity = await run_workspace_oauth_exchange(
                code=code,
                state=state,
                client_id=workspace_oauth_client_id(),
                deadline_seconds=settings.INTEGRATION_PROVIDER_DEADLINE_SECONDS,
                socket_timeout_seconds=(
                    settings.INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS
                ),
            )
        else:
            identity = await oauth_exchange(code=code, state=state)
    except Exception:
        await _rollback_workspace_oauth(db)
        return HTMLResponse(
            render_workspace_oauth_page(
                "Workspace Not Connected",
                "Workspace authorization could not be verified. Please close "
                "this tab and try again from Settings.",
            ),
            status_code=503,
        )

    try:
        await bind_workspace_gmail_identity(db, identity)
        await db.commit()
    except RuntimeError as exc:
        await _rollback_workspace_oauth(db)
        if str(exc) == "workspace_account_rebind_forbidden":
            return HTMLResponse(
                render_workspace_oauth_page(
                    "Workspace Not Connected",
                    "Workspace is already bound to a different Gmail mailbox.",
                ),
                status_code=409,
            )
        return HTMLResponse(
            render_workspace_oauth_page(
                "Workspace Not Connected",
                "Workspace authorization could not be saved. Please close this "
                "tab and try again from Settings.",
            ),
            status_code=503,
        )
    except Exception:
        await _rollback_workspace_oauth(db)
        return HTMLResponse(
            render_workspace_oauth_page(
                "Workspace Not Connected",
                "Workspace authorization could not be saved. Please close this "
                "tab and try again from Settings.",
            ),
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
    return await get_workspace_connection_status_bounded(
        deadline_seconds=settings.INTEGRATION_PROVIDER_DEADLINE_SECONDS,
        socket_timeout_seconds=(
            settings.INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS
        ),
    )


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
