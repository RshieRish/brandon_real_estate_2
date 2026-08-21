import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_action_audit import AgentActionAudit

logger = logging.getLogger(__name__)


async def write_agent_audit_transactional(
    db: AsyncSession,
    *,
    request,
    actor: str,
    action_id: str,
    status_code: int,
    allowed: bool,
    request_meta: dict[str, Any] | None = None,
    response_meta: dict[str, Any] | None = None,
) -> AgentActionAudit:
    """Write a fail-closed audit row in the caller's transaction."""

    row = AgentActionAudit(
        actor=actor,
        action_id=action_id,
        method=request.method,
        path=request.url.path,
        status_code=status_code,
        allowed=allowed,
        request_meta_json=json.dumps(request_meta or {}),
        response_meta_json=json.dumps(response_meta or {}),
    )
    db.add(row)
    await db.flush()
    return row


async def write_agent_audit(
    db: AsyncSession,
    *,
    request,
    actor: str,
    action_id: str,
    status_code: int,
    allowed: bool,
    request_meta: dict[str, Any] | None = None,
    response_meta: dict[str, Any] | None = None,
) -> None:
    try:
        db.add(
            AgentActionAudit(
                actor=actor,
                action_id=action_id,
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                allowed=allowed,
                request_meta_json=json.dumps(request_meta or {}),
                response_meta_json=json.dumps(response_meta or {}),
            )
        )
        await db.flush()
    except Exception as exc:
        logger.error("[agent-control] Failed to write audit row: %s", exc)
