import secrets

from fastapi import Header, HTTPException

from config import settings


def require_agent_control(authorization: str | None = Header(default=None)) -> dict:
    if not settings.AGENT_CONTROL_ENABLED or not settings.AGENT_CONTROL_TOKEN:
        raise HTTPException(status_code=503, detail="Agent control is not configured.")

    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Invalid agent control credentials.")

    supplied_token = authorization[len(prefix):]
    if not secrets.compare_digest(supplied_token, settings.AGENT_CONTROL_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid agent control credentials.")

    return {"actor": "hermes"}
