# Brandon Hermes Agent Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved read-only Hermes foundation bridge: a separate Railway Hermes service plan plus token-authenticated FastAPI `/api/v1/agent-control/*` endpoints with audit logging.

**Architecture:** The existing FastAPI backend remains the only owner of app data. Hermes will run as a separate Railway service and call only allowlisted FastAPI agent-control endpoints protected by `AGENT_CONTROL_TOKEN`; the first implementation slice is read-only and audited.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, Railway CLI via `scripts/railway-sweeney`, pytest/unittest.

---

## File Structure

- Create `backend/middleware/agent_control.py`: bearer-token dependency using `settings.AGENT_CONTROL_ENABLED` and `settings.AGENT_CONTROL_TOKEN`.
- Create `backend/models/agent_action_audit.py`: SQLAlchemy model for audited Hermes/backend bridge requests.
- Create `backend/schemas/agent_control.py`: Pydantic response models plus action registry data.
- Create `backend/services/agent_control_audit.py`: best-effort audit writer that avoids logging tokens or full PII response bodies.
- Create `backend/routers/agent_control.py`: `status`, `actions`, `leads/recent`, and `bookings/recent` endpoints.
- Create Alembic migration `backend/alembic/versions/e2f4a6b8c901_add_agent_action_audits.py`.
- Modify `backend/config.py`: add agent-control settings.
- Modify `backend/main.py`: include the new router.
- Modify `backend/models/__init__.py`: import the audit model for migration/model discovery.
- Modify `backend/.env.example`: document agent-control env vars without secrets.
- Create tests `backend/tests/test_agent_control_auth.py` and `backend/tests/test_agent_control_router.py`.
- Create `docs/deployment/hermes-railway.md`: runbook for deploying `atlas-agent` safely in the existing Railway project.
- Update `tdtn.md` and `memory.md`.

## Shared Test Environment

Use these env vars for local tests from `backend/`:

```bash
JWT_SECRET=test-secret DATABASE_URL=postgresql+asyncpg://user:pass@localhost/test
```

The dummy `DATABASE_URL` is parseable for SQLAlchemy import-time engine creation; tests use fake sessions and do not connect to it.

---

### Task 1: Agent-Control Auth Dependency

**Files:**
- Modify: `backend/config.py`
- Create: `backend/middleware/agent_control.py`
- Test: `backend/tests/test_agent_control_auth.py`

- [ ] **Step 1: Write the failing auth tests**

Create `backend/tests/test_agent_control_auth.py`:

```python
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from middleware.agent_control import require_agent_control


class AgentControlAuthTests(unittest.TestCase):
    def test_disabled_returns_503(self):
        with patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", False), patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "secret"
        ):
            with self.assertRaises(HTTPException) as ctx:
                require_agent_control("Bearer secret")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_missing_token_config_returns_503(self):
        with patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True), patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", ""
        ):
            with self.assertRaises(HTTPException) as ctx:
                require_agent_control("Bearer secret")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_missing_authorization_returns_401(self):
        with patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True), patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "secret"
        ):
            with self.assertRaises(HTTPException) as ctx:
                require_agent_control(None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_wrong_authorization_returns_401(self):
        with patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True), patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "secret"
        ):
            with self.assertRaises(HTTPException) as ctx:
                require_agent_control("Bearer wrong")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_correct_authorization_returns_actor_context(self):
        with patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True), patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "secret"
        ):
            context = require_agent_control("Bearer secret")
        self.assertEqual(context, {"actor": "hermes"})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL=postgresql+asyncpg://user:pass@localhost/test /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/python -m pytest tests/test_agent_control_auth.py -v
```

Expected: fail with `ModuleNotFoundError` for `middleware.agent_control`.

- [ ] **Step 3: Implement minimal auth dependency**

Add settings in `backend/config.py`:

```python
AGENT_CONTROL_TOKEN: str = ""
AGENT_CONTROL_ENABLED: bool = False
AGENT_CONTROL_RECENT_LIMIT: int = 10
```

Create `backend/middleware/agent_control.py`:

```python
import secrets

from fastapi import Header, HTTPException

from config import settings


def require_agent_control(authorization: str | None = Header(default=None)) -> dict:
    if not settings.AGENT_CONTROL_ENABLED or not settings.AGENT_CONTROL_TOKEN:
        raise HTTPException(status_code=503, detail="Agent control is not configured.")

    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Invalid agent control credentials.")

    supplied = authorization[len(prefix):]
    if not secrets.compare_digest(supplied, settings.AGENT_CONTROL_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid agent control credentials.")

    return {"actor": "hermes"}
```

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command. Expected: all auth tests pass.

---

### Task 2: Audit Model And Service

**Files:**
- Create: `backend/models/agent_action_audit.py`
- Modify: `backend/models/__init__.py`
- Create: `backend/services/agent_control_audit.py`
- Create: `backend/alembic/versions/e2f4a6b8c901_add_agent_action_audits.py`
- Test: `backend/tests/test_agent_control_router.py`

- [ ] **Step 1: Write failing audit test**

In `backend/tests/test_agent_control_router.py`, start with:

```python
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from fastapi import Request

from models.agent_action_audit import AgentActionAudit
from services.agent_control_audit import write_agent_audit


class _FakeURL:
    path = "/api/v1/agent-control/status"


class _FakeRequest:
    method = "GET"
    url = _FakeURL()


class _FakeDB:
    def __init__(self):
        self.added = []
        self.flush = AsyncMock()

    def add(self, item):
        self.added.append(item)


class AgentControlAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_agent_audit_stores_metadata_without_pii_body(self):
        db = _FakeDB()
        await write_agent_audit(
            db,
            request=_FakeRequest(),
            actor="hermes",
            action_id="status.read",
            status_code=200,
            allowed=True,
            response_meta={"count": 2, "ids": [1, 2]},
        )

        self.assertEqual(len(db.added), 1)
        audit = db.added[0]
        self.assertIsInstance(audit, AgentActionAudit)
        self.assertEqual(audit.actor, "hermes")
        self.assertEqual(audit.action_id, "status.read")
        self.assertEqual(audit.status_code, 200)
        self.assertTrue(audit.allowed)
        self.assertEqual(json.loads(audit.response_meta_json), {"count": 2, "ids": [1, 2]})
        db.flush.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Expected: fail because `AgentActionAudit` and `write_agent_audit` do not exist.

- [ ] **Step 3: Implement model, migration, and audit service**

Create `backend/models/agent_action_audit.py` with the table from the spec. Add an import to `backend/models/__init__.py`.

Create `backend/services/agent_control_audit.py`:

```python
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_action_audit import AgentActionAudit

logger = logging.getLogger(__name__)


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
```

Create the Alembic migration with `agent_action_audits` columns and indexes on `created_at` and `action_id`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL=postgresql+asyncpg://user:pass@localhost/test /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/python -m pytest tests/test_agent_control_router.py::AgentControlAuditTests -v
```

Expected: pass.

---

### Task 3: Read-Only Agent-Control Router

**Files:**
- Create: `backend/schemas/agent_control.py`
- Create: `backend/routers/agent_control.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_agent_control_router.py`

- [ ] **Step 1: Write failing router tests**

Add tests with these assertions:

```python
class AgentControlRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_returns_read_only_capabilities_and_audits(self):
        # Call agent_status(request, db, agent={"actor": "hermes"}).
        # Assert status == "ok", risk_tier == "read_only_foundation",
        # "leads.recent.read" is present, and one audit row was added.

    async def test_actions_returns_only_read_only_actions(self):
        # Call list_agent_actions(request, db, agent={"actor": "hermes"}).
        # Assert every returned action has side_effects is False and the ids
        # equal status.read, leads.recent.read, and bookings.recent.read.

    async def test_recent_leads_masks_email_phone_and_caps_limit(self):
        # Fake one Lead row with email "jane@example.com" and phone
        # "978-987-2806"; call recent_leads with limit set to 99 and no filters.
        # Assert the query limit is capped at 25, email is "***@example.com",
        # phone is "***-***-2806", and metadata is parsed from metadata_json.

    async def test_recent_bookings_omits_google_event_id_and_exposes_boolean(self):
        # Fake one Booking row with google_event_id="evt_123".
        # Assert the response has has_google_event is True and no
        # google_event_id key or attribute in the returned item.
```

Use fake DB sessions with `execute()`, `add()`, and `flush()` methods. Call router functions directly and pass `agent={"actor": "hermes"}`.

- [ ] **Step 2: Run tests to verify they fail**

Expected: fail because router functions and schemas do not exist.

- [ ] **Step 3: Implement schemas and router**

Create action registry constants:

```python
AGENT_ACTIONS = [
    AgentAction(id="status.read", method="GET", path="/api/v1/agent-control/status", risk_tier="auto_silent", side_effects=False, description="Read backend health and capability metadata."),
    AgentAction(id="leads.recent.read", method="GET", path="/api/v1/agent-control/leads/recent", risk_tier="auto_silent", side_effects=False, description="Read recent lead summaries for operational context."),
    AgentAction(id="bookings.recent.read", method="GET", path="/api/v1/agent-control/bookings/recent", risk_tier="auto_silent", side_effects=False, description="Read recent booking summaries for operational context."),
]
```

Implement helpers:

```python
def _safe_limit(limit: int | None) -> int:
    default = settings.AGENT_CONTROL_RECENT_LIMIT
    return min(max(limit or default, 1), 25)

def _mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    _, domain = email.split("@", 1)
    return f"***@{domain}"

def _mask_phone(phone: str | None) -> str | None:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return phone
    return f"***-***-{digits[-4:]}"
```

Query `Lead` and `Booking` with existing SQLAlchemy patterns, order by descending `created_at`, and apply optional filters.

- [ ] **Step 4: Mount router**

Modify imports in `backend/main.py` to include `agent_control`, then mount:

```python
app.include_router(agent_control.router, prefix="/api/v1/agent-control", tags=["agent-control"])
```

- [ ] **Step 5: Run tests to verify they pass**

Run both new test files.

---

### Task 4: Environment And Deployment Documentation

**Files:**
- Modify: `backend/.env.example`
- Create: `docs/deployment/hermes-railway.md`
- Modify: `tdtn.md`
- Modify: `memory.md`

- [ ] **Step 1: Document backend env vars**

Add:

```dotenv
AGENT_CONTROL_ENABLED=false
AGENT_CONTROL_TOKEN=
AGENT_CONTROL_RECENT_LIMIT=10
```

- [ ] **Step 2: Add Railway deployment runbook**

Create `docs/deployment/hermes-railway.md` with:

- Verified project/service names.
- Use `scripts/railway-sweeney`, never `railway login`.
- Deploy Hermes as separate `atlas-agent`.
- Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `/data` volume, provider/channel setup.
- Set `AGENT_CONTROL_ENABLED=true` and `AGENT_CONTROL_TOKEN` only on the backend service when ready.
- Verification commands for `service status --all` and backend `curl`.
- Statement that outbound autonomy remains disabled.

- [ ] **Step 3: Update project progress and memory**

Add a `tdtn.md` entry for the implementation and a `memory.md` note for the new bridge endpoints and env vars.

---

### Task 5: Verification And Commit

**Files:**
- All implementation files.

- [ ] **Step 1: Run focused tests**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL=postgresql+asyncpg://user:pass@localhost/test /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/python -m pytest tests/test_agent_control_auth.py tests/test_agent_control_router.py -v
```

Expected: pass.

- [ ] **Step 2: Run baseline neighboring tests**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL=postgresql+asyncpg://user:pass@localhost/test /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/python -m pytest tests/test_link_pack_router.py tests/test_leads_notifications.py -q
```

Expected: pass.

- [ ] **Step 3: Run diff hygiene**

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend docs tdtn.md memory.md
git commit -m "feat: add hermes agent control bridge"
```
