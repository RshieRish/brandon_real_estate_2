# Brandon Hermes Agent Foundation - Design

**Date:** 2026-06-01
**Author:** Brainstormed with Codex
**Scope:** Railway Hermes service plus FastAPI agent-control bridge
**Status:** Approved for implementation planning

---

## Problem

The attached "Brandon AI / Atlas" PRD describes a private executive assistant for Brandon Sweeney. That assistant is not another public website widget. It is an always-on private agent that needs messaging access, persistent memory, scheduled jobs, Google Workspace access, voice/persona context, and a controlled path into the existing Brandon Real Estate backend.

The existing production backend already runs in Railway as service `extraordinary-prosperity` inside project `enchanting-perception`. We want Hermes to live close enough to that backend to control selected backend functions, but not close enough that an agent deployment can overwrite or destabilize the production FastAPI service.

## Goal

Create the foundation for a private Hermes-based executive assistant by deploying Hermes as a separate Railway service in the same Railway project, then exposing a narrow, token-authenticated FastAPI control API that Hermes can call for safe read-only operational context.

## Non-goals for this slice

- No Gmail, Calendar, Drive, Sheets, Docs, People, or CRM OAuth wiring yet.
- No auto-sending email, SMS, Telegram client replies, booking invites, or client-facing messages.
- No deep Drive indexing or RAG layer.
- No replacement of the current public website chatbot.
- No direct database access from Hermes.
- No direct shell or internal backend mutation by Hermes.
- No merger of Hermes into the existing FastAPI process.

This slice gives Hermes a safe place to run and a safe first bridge into the current backend.

## Decisions locked during brainstorming

| Decision | Choice |
|---|---|
| Railway organization | Use the existing project `enchanting-perception`. |
| Service topology | Keep FastAPI and Hermes as separate Railway services. |
| Existing backend service | Leave `extraordinary-prosperity` untouched except for explicit agent-control endpoints. |
| New agent service | Create a separate service named `atlas-agent` unless Railway name availability forces `brandon-hermes`. |
| Hermes persistence | Mount a Railway volume at `/data`, matching the active Railway Hermes template guidance. |
| Hermes setup | Use Hermes dashboard/admin setup for LLM keys and channel tokens, not committed env files. |
| Backend control path | Add `/api/v1/agent-control/*` endpoints to FastAPI. |
| First backend bridge behavior | Read-only status, recent leads, recent bookings, and action registry. |
| Auth | Require `Authorization: Bearer ${AGENT_CONTROL_TOKEN}`. |
| Audit | Persist an audit row for every successful and rejected agent-control request. |
| Autonomy | Foundation only. Risk-tiered outbound behavior is a later phase. |

## Architecture

```
Railway project: enchanting-perception

  service: extraordinary-prosperity
    FastAPI backend
    Postgres via existing DATABASE_URL
    /api/v1/agent-control/*
      - token auth
      - read-only operational endpoints
      - audit logging

  service: atlas-agent
    Hermes Agent
    dashboard + messaging gateway
    persistent volume at /data
    Telegram channel configured from dashboard
    calls FastAPI only through agent-control endpoints
```

Hermes and FastAPI communicate through explicit HTTP APIs. If Railway private networking is available for both services, the internal/private URL should be used. If private networking is not available or not stable for this template, Hermes can call the public Railway backend URL with the same bearer token. In either case, FastAPI must treat every request as untrusted until the agent token dependency passes.

## Railway deployment design

The existing wrapper `scripts/railway-sweeney` must be used for Railway CLI operations so the global CLI login for `rishabnandibusiness@gmail.com` remains untouched.

Current verified Railway state:

- Project: `enchanting-perception`
- Project ID: `aa6c9f9c-46d4-4f5d-b529-86b073de4972`
- Existing backend service: `extraordinary-prosperity`
- Existing backend service ID: `85541f63-2aa1-4679-8114-98895f4bf215`
- Environment: `production`

Hermes service options:

1. **Preferred for first deployment:** use the Railway Hermes template from the dashboard, selecting the existing project `enchanting-perception`, then name the service `atlas-agent`.
2. **CLI fallback:** create a new service with `scripts/railway-sweeney add --service atlas-agent --repo praveen-ks-2001/hermes-agent-template` if the public Railway template repository can be deployed cleanly from CLI.
3. **Repo fallback:** add a local `hermes/` service directory with a Dockerfile that installs Hermes from the official `NousResearch/hermes-agent` source, then deploy it as another Railway service from this repository.

The first implementation plan should try the least invasive deployment path first, but it must not modify or redeploy `extraordinary-prosperity` until the FastAPI bridge has tests.

## Hermes configuration

Hermes itself stores runtime configuration, channel tokens, provider keys, learned skills, and memory in its own data volume and dashboard-managed config. Those secrets must not be committed to this repository.

Minimum first-run Hermes configuration:

- Admin username and password configured in Railway variables.
- Persistent Railway volume mounted at `/data`.
- LLM provider configured in Hermes dashboard.
- Telegram bot token configured in Hermes dashboard.
- Brandon's Telegram user paired and approved in Hermes dashboard before real use.

Recommended model posture:

- Use a capable paid model for anything that touches client context.
- Free or small models are acceptable only for smoke tests and dashboard bring-up.
- Do not enable automatic client-facing sends in this slice.

## FastAPI agent-control API

All new endpoints live under a new router:

```
backend/routers/agent_control.py
```

Mounted in `backend/main.py`:

```python
app.include_router(agent_control.router, prefix="/api/v1/agent-control", tags=["agent-control"])
```

### Authentication dependency

Add a dependency in:

```
backend/middleware/agent_control.py
```

Behavior:

- Read `settings.AGENT_CONTROL_TOKEN`.
- If missing or blank, all agent-control endpoints return `503` with `"Agent control is not configured."`.
- Require an `Authorization` header shaped as `Bearer ${AGENT_CONTROL_TOKEN}`.
- Use `secrets.compare_digest()` for token comparison.
- Return `401` for missing or wrong token.
- Return a small context object with `actor="hermes"` when valid.

### Settings

Add to `backend/config.py`:

```python
AGENT_CONTROL_TOKEN: str = ""
AGENT_CONTROL_ENABLED: bool = False
AGENT_CONTROL_RECENT_LIMIT: int = 10
```

Endpoint access is enabled only when both `AGENT_CONTROL_ENABLED` is true and `AGENT_CONTROL_TOKEN` is non-empty.

### Endpoint: `GET /api/v1/agent-control/status`

Purpose: give Hermes a quick health and capability snapshot.

Response shape:

```json
{
  "status": "ok",
  "service": "brandon-re-api",
  "environment": "production",
  "capabilities": [
    "status.read",
    "leads.recent.read",
    "bookings.recent.read"
  ],
  "risk_tier": "read_only_foundation"
}
```

No secrets, no database URLs, no provider keys, and no raw env values are returned.

### Endpoint: `GET /api/v1/agent-control/actions`

Purpose: expose the allowlisted action registry so Hermes can reason about what it is allowed to do.

Response shape:

```json
{
  "actions": [
    {
      "id": "status.read",
      "method": "GET",
      "path": "/api/v1/agent-control/status",
      "risk_tier": "auto_silent",
      "side_effects": false,
      "description": "Read backend health and capability metadata."
    },
    {
      "id": "leads.recent.read",
      "method": "GET",
      "path": "/api/v1/agent-control/leads/recent",
      "risk_tier": "auto_silent",
      "side_effects": false,
      "description": "Read recent lead summaries for operational context."
    },
    {
      "id": "bookings.recent.read",
      "method": "GET",
      "path": "/api/v1/agent-control/bookings/recent",
      "risk_tier": "auto_silent",
      "side_effects": false,
      "description": "Read recent booking summaries for operational context."
    }
  ]
}
```

This registry becomes the contract for later write-capable actions. Later actions must specify risk tier, confirmation policy, and audit behavior before implementation.

### Endpoint: `GET /api/v1/agent-control/leads/recent`

Purpose: let Hermes answer "what came in recently?" without admin dashboard access.

Query params:

- `limit`: optional integer, default from `AGENT_CONTROL_RECENT_LIMIT`, max `25`.
- `lead_type`: optional existing lead type filter.
- `routing_status`: optional existing routing status filter.

Response item shape:

```json
{
  "id": 123,
  "name": "Jane Client",
  "email": "j***@example.com",
  "phone": "***-***-2806",
  "source": "sell_page",
  "lead_type": "seller",
  "routing_status": "new",
  "notes": "Interested in valuation meeting.",
  "metadata": {
    "intent": "valuation"
  },
  "created_at": "2026-06-01T12:34:56Z",
  "updated_at": "2026-06-01T12:34:56Z"
}
```

PII handling for v1:

- Mask email local-part by default.
- Mask phone except last four digits.
- Include name because Brandon-facing operational context needs it.
- Include notes and metadata, but cap long string fields so prompt context cannot balloon.

Later phases can add a `pii_scope` model and stronger role-based controls if needed.

### Endpoint: `GET /api/v1/agent-control/bookings/recent`

Purpose: let Hermes see recent scheduled meetings and understand booking flow state.

Query params:

- `limit`: optional integer, default from `AGENT_CONTROL_RECENT_LIMIT`, max `25`.
- `meeting_type`: optional existing meeting type filter.
- `context`: optional existing context filter.

Response item shape:

```json
{
  "id": 456,
  "lead_id": 123,
  "name": "Jane Client",
  "email": "j***@example.com",
  "phone": "***-***-2806",
  "meeting_type": "phone",
  "context": "seller",
  "location": "",
  "scheduled_at": "2026-06-02T15:00:00-04:00",
  "has_google_event": true,
  "notes": "Valuation call.",
  "created_at": "2026-06-01T12:40:00Z"
}
```

`google_event_id` is never returned directly. Only `has_google_event` is exposed.

## Audit logging

Add a dedicated model and migration instead of overloading public analytics:

```
backend/models/agent_action_audit.py
backend/alembic/versions/generated_add_agent_action_audits_revision.py
```

Table shape:

```python
class AgentActionAudit(Base):
    __tablename__ = "agent_action_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor: Mapped[str] = mapped_column(String(80), default="hermes")
    action_id: Mapped[str] = mapped_column(String(120), index=True)
    method: Mapped[str] = mapped_column(String(12))
    path: Mapped[str] = mapped_column(String(255))
    status_code: Mapped[int] = mapped_column(Integer)
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    request_meta_json: Mapped[str] = mapped_column("request_meta", Text, default="{}")
    response_meta_json: Mapped[str] = mapped_column("response_meta", Text, default="{}")
```

Audit rules:

- Log every authenticated request.
- Log rejected authenticated requests if the action registry rejects them.
- Do not log raw bearer tokens.
- Do not log full PII response bodies.
- Log counts and ids, not full lead or booking payloads.
- If audit logging fails, endpoint should still return its safe read-only response, but the failure must be logged through Python logging.

Unauthenticated requests are not inserted into the audit table because the actor is unknown and repeated attacks could fill the database. They are rejected with HTTP status only.

## Security and compliance guardrails

### Token handling

- `AGENT_CONTROL_TOKEN` is generated once and stored only in Railway variables for both services.
- The token is not committed to this repository.
- Local development may use `.env`, which is ignored.
- Token comparison uses constant-time comparison.

### Network handling

- Prefer Railway private service URL when possible.
- Public URL fallback is acceptable because bearer token auth is still required.
- CORS is irrelevant for Hermes server-to-server calls; do not loosen CORS for agent-control endpoints.

### Prompt-injection boundary

Hermes can read untrusted email and web content in later phases. The backend must never treat Hermes instructions as privileged merely because they arrived from Hermes. The agent-control bridge is action-registry-driven, token-authenticated, and narrow. Later write endpoints must apply their own confirmations and validation.

### Real-estate compliance

No outbound client-facing content is sent from this slice. Later phases must keep Fair Housing and professional-license guardrails above persona/voice matching. In this slice, the main compliance posture is least privilege and read-only context.

## Repository changes for the first implementation slice

Backend files:

```
backend/config.py
backend/main.py
backend/middleware/agent_control.py
backend/models/__init__.py
backend/models/agent_action_audit.py
backend/routers/__init__.py
backend/routers/agent_control.py
backend/schemas/agent_control.py
backend/services/agent_control_audit.py
backend/alembic/versions/generated_add_agent_action_audits_revision.py
backend/tests/test_agent_control_auth.py
backend/tests/test_agent_control_router.py
backend/.env.example
```

Documentation and progress files:

```
docs/superpowers/specs/2026-06-01-brandon-hermes-agent-foundation-design.md
docs/superpowers/plans/2026-06-01-brandon-hermes-agent-foundation.md
tdtn.md
memory.md
```

Optional deployment helper files, only if CLI/template deployment requires repo-owned instructions:

```
docs/deployment/hermes-railway.md
```

## Testing strategy

Use TDD for backend code.

Minimum tests:

1. Missing `AGENT_CONTROL_ENABLED` or missing token returns `503`.
2. Missing `Authorization` returns `401`.
3. Wrong bearer token returns `401`.
4. Correct bearer token allows `status`.
5. `actions` returns only read-only v1 actions.
6. Recent leads endpoint masks email and phone.
7. Recent leads endpoint enforces max limit of `25`.
8. Recent bookings endpoint does not expose `google_event_id`.
9. Recent bookings endpoint exposes `has_google_event`.
10. Authenticated successful requests create `AgentActionAudit` rows.

Verification commands:

```bash
cd backend
./.venv/bin/python -m pytest tests/test_agent_control_auth.py tests/test_agent_control_router.py -v
```

If the backend virtualenv is unavailable:

```bash
cd backend
python -m pytest tests/test_agent_control_auth.py tests/test_agent_control_router.py -v
```

Full backend confidence check after implementation:

```bash
cd backend
./.venv/bin/python -m pytest -v
```

## Deployment verification

Backend bridge verification:

```bash
curl -sS "$BACKEND_URL/api/v1/agent-control/status" \
  -H "Authorization: Bearer $AGENT_CONTROL_TOKEN"
```

Expected response:

```json
{
  "status": "ok",
  "service": "brandon-re-api",
  "risk_tier": "read_only_foundation"
}
```

Railway Hermes verification:

```bash
scripts/railway-sweeney service status --all
```

Expected after Hermes deployment:

```text
Services in production:

extraordinary-prosperity | 85541f63-2aa1-4679-8114-98895f4bf215 | SUCCESS
atlas-agent | Railway-assigned service UUID | SUCCESS
```

Hermes dashboard verification:

- Open the `atlas-agent` Railway domain.
- Log in with configured admin credentials.
- Confirm Hermes dashboard loads.
- Confirm persistent volume is mounted.
- Configure LLM provider.
- Configure Telegram.
- Message the Telegram bot.
- Approve Brandon's pairing request.
- Send a private test prompt asking it to call the backend status action.

## Rollout sequence

1. Commit this spec.
2. Write the implementation plan.
3. Implement the FastAPI bridge with tests.
4. Deploy or redeploy only the FastAPI backend when tests pass.
5. Add `AGENT_CONTROL_ENABLED=true` and `AGENT_CONTROL_TOKEN` to FastAPI Railway service.
6. Deploy Hermes as a separate `atlas-agent` service in the same Railway project.
7. Add the same `AGENT_CONTROL_TOKEN` and backend URL to Hermes configuration or Hermes custom skill/tool config.
8. Verify status/actions/recent read endpoints from Hermes.
9. Leave all outbound and write-capable actions disabled until the next approved spec.

## Later phases

Phase 1 after this foundation:

- Hermes custom skill/tool for the Brandon backend bridge.
- Persona/style profile and seed precedent corpus from Brandon's samples.
- Telegram command set for Brandon-only private control.
- Daily digest draft, but not auto-send.

Phase 2:

- Google Workspace read-only integration.
- Email triage summaries.
- Calendar read/write with confirmation tier.

Phase 3:

- Lead speed-to-response workflows.
- Follow-up cadences.
- Sheets transaction tracking.
- First limited auto-notify actions.

Phase 4:

- Drive indexing/RAG.
- SMS/iMessage or WhatsApp.
- Richer multi-channel autonomy.

## References used

- Railway Hermes template page: `https://railway.com/deploy/hermes-agent-nous-research`
- Hermes Agent install docs: `https://hermes-agent.nousresearch.com/docs/getting-started/installation`
- Hermes Agent GitHub repository: `https://github.com/NousResearch/hermes-agent`
- Attached PRD: `Product Requirements Document - "Brandon" AI Executive Assistant`
