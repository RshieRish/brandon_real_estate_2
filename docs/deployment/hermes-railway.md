# Hermes Railway Deployment Runbook

This runbook is for the private Brandon AI / Atlas assistant foundation.

## Verified Railway Context

- Railway project: `enchanting-perception`
- Project ID: `aa6c9f9c-46d4-4f5d-b529-86b073de4972`
- Existing FastAPI backend service: `extraordinary-prosperity`
- Existing backend service ID: `85541f63-2aa1-4679-8114-98895f4bf215`
- Hermes service: `atlas-agent`
- Hermes service ID: `6dc65984-89c1-400c-9d17-d5412befd031`
- Hermes URL: `https://atlas-agent-production-99dc.up.railway.app`
- Environment: `production`

Use the local wrapper for Railway commands:

```bash
scripts/railway-sweeney service status --all
```

Do not run `railway login` for `soldwithsweeneyfordeployment@gmail.com`; that would replace the global CLI login.

## Backend Bridge Variables

Set these on the existing FastAPI service only when ready:

```bash
scripts/railway-sweeney variable set --service extraordinary-prosperity --environment production AGENT_CONTROL_ENABLED=true
scripts/railway-sweeney variable set --service extraordinary-prosperity --environment production AGENT_CONTROL_TOKEN="$AGENT_CONTROL_TOKEN_VALUE"
scripts/railway-sweeney variable set --service extraordinary-prosperity --environment production AGENT_CONTROL_RECENT_LIMIT=10
```

Generate `AGENT_CONTROL_TOKEN` with a password manager or:

```bash
openssl rand -hex 32
```

Never commit the token.

## Hermes Service

Current status as of 2026-06-01:

- The FastAPI bridge is live and verified.
- `atlas-agent` is live in the same Railway project.
- Deployment `dc2db0c4-10ca-447a-8d7a-c500dec1aa89` is `SUCCESS`.
- The public dashboard URL is `https://atlas-agent-production-99dc.up.railway.app`.
- The health check returns `{"status":"ok","gateway":"running"}` after Gemini provider setup.
- Admin credentials are stored only in local ignored `.env.hermes-admin.local` and Railway variables.
- The current `.env.railway-sweeney.local` uses a project-scoped `RAILWAY_TOKEN`, which works for existing service operations but was rejected by Railway when attempting to create a new GitHub-backed service from `praveen-ks-2001/hermes-agent-template`.
- The deployed fallback path was: create an empty `atlas-agent` service, attach `/data`, set admin vars, then upload the checked-out template with `railway up --path-as-root`.
- The Railway template URL checked on 2026-06-01 is `https://railway.com/deploy/hermes-agent-nous-research`; it requires `ADMIN_USERNAME` and `ADMIN_PASSWORD`, persists config under `/data`, and stores LLM/channel keys through the Hermes dashboard.
- Template commit deployed: `7224d7c1a4dcffe9304f49bc843f55716f5561b4`.
- Persistent volume: `atlas-agent-volume`, ID `594c4970-ba61-4888-8372-57d0c235db65`, mounted at `/data`, size `5000 MB`.
- `BRANDON_BACKEND_URL` and masked `BRANDON_AGENT_CONTROL_TOKEN` are set on `atlas-agent` for future backend-control skills.
- Gemini provider is configured in Hermes persistent config with `LLM_MODEL=gemini-3.5-flash`.
- Telegram is configured for `soldwithsweeney_bot` with Brandon's Telegram user ID in the allowlist.
- Telegram home channel is Brandon's private DM chat ID, so future default Hermes deliveries can target Brandon without repeating a chat ID.
- Atlas backend MCP bridge is included in the custom Hermes image and writes `mcp_servers.atlas_backend` at boot when `BRANDON_BACKEND_URL` and `BRANDON_AGENT_CONTROL_TOKEN` exist.
- Latest custom Hermes deployment after Telegram config: `0636f515-da58-4b94-a6ca-bb27ef2ed8f5` reached `SUCCESS`.
- Railway SSH currently returns `Insufficient permissions: Railway SSH requires the MEMBER role`; use image redeploys and the Hermes setup API unless Railway project role is upgraded.

Preferred deployment path:

1. Open Railway dashboard for `enchanting-perception`.
2. Add the Hermes Agent template as a new service: `https://railway.com/deploy/hermes-agent-nous-research`.
3. Name the service `atlas-agent`.
4. Mount a persistent volume at `/data`.
5. Configure Hermes admin credentials in Railway variables.
6. Configure the LLM provider in the Hermes dashboard.
7. Configure Telegram in the Hermes dashboard.
8. Pair Brandon's Telegram user before any real usage.

If the dashboard template is unavailable, use the CLI/repo fallback from the design spec rather than modifying `extraordinary-prosperity`.

The CLI/repo fallback used successfully on 2026-06-01:

```bash
git clone --depth 1 https://github.com/praveen-ks-2001/hermes-agent-template.git /tmp/hermes-agent-template-inspect
npx -y @railway/cli@latest add --service atlas-agent --json
npx -y @railway/cli@latest volume add --mount-path /data --json
npx -y @railway/cli@latest up /tmp/hermes-agent-template-inspect \
  --service atlas-agent \
  --environment production \
  --path-as-root \
  --detach \
  --message "Deploy atlas-agent Hermes template 7224d7c" \
  --json
```

Note: `volume add` needed a temporary service link because the project token cannot create one interactively. That temporary `/tmp` link was removed from `~/.railway/config.json` after the volume was attached.

## Atlas Backend MCP Bridge

Hermes uses the repo bridge at `hermes/atlas_backend_mcp.py`. It is a stdlib-only stdio MCP server that calls the existing FastAPI `agent-control` routes with:

- `BRANDON_BACKEND_URL`
- `BRANDON_AGENT_CONTROL_TOKEN`

These variables are Railway service variables on `atlas-agent`; do not commit or print the token.

The custom Hermes image copies the bridge to:

```text
/app/atlas_backend_mcp.py
```

The currently deployed Hermes image writes this config entry at boot when both backend bridge vars exist:

```yaml
mcp_servers:
  atlas_backend:
    command: python
    args:
      - /app/atlas_backend_mcp.py
    env:
      BRANDON_BACKEND_URL: ${BRANDON_BACKEND_URL}
      BRANDON_AGENT_CONTROL_TOKEN: ${BRANDON_AGENT_CONTROL_TOKEN}
    enabled: true
    timeout: 120
    connect_timeout: 30
    supports_parallel_tool_calls: false
    tools:
      include:
        - status_read
        - actions_list
        - leads_recent
        - bookings_recent
        - workspace_status
        - drive_search
        - drive_file_read
        - gmail_search
        - gmail_thread_read
        - gmail_draft_create
        - gmail_send
        - docs_create
        - sheets_append
        - calendar_events_read
        - calendar_event_create
        - contacts_search
      resources: false
      prompts: false
```

Local stdio verification against production succeeded for `initialize` and `workspace_status`, returning `configured=True` and `connected=True`. The live Hermes service cannot show a full MCP tool invocation yet because no messaging platform is enabled and Railway SSH is not available for direct `hermes mcp list/test` inside the container.

### Local Task 8 overlay preparation — not deployed

`hermes/overlay/manifest.json` pins the Hermes template source to commit
`7224d7c1a4dcffe9304f49bc843f55716f5561b4`. The local overlay preserves the
16 current tool names above in their current order and prepares exactly these
six additional CRM review tools:

- `crm_tasks_read`
- `crm_task_suggestions_read`
- `crm_task_clarifications_answer`
- `crm_task_drafts_create`
- `crm_task_suggestions_approval_link`
- `crm_task_suggestions_dismiss_proposal`

This is deliberately a local-only contract. Do not deploy it or change the
production `tools.include` list until the authenticated Task 7 review route,
two-stage handoff exchange, blocker UI, and production deployment are all
verified. The answer and draft tools treat Hermes input as untrusted draft
evidence. The dismissal tool only records a non-authoritative review proposal;
it cannot dismiss, suppress, or release anything. Actual dismiss, approve,
create-confirmed, archive, and restore tools remain absent.

## Verification

Check both services:

```bash
scripts/railway-sweeney service status --all
```

Expected shape:

```text
Services in production:

extraordinary-prosperity | deployment UUID | SUCCESS
atlas-agent | deployment UUID | SUCCESS
```

Check the backend bridge:

```bash
curl -sS "$BACKEND_URL/api/v1/agent-control/status" \
  -H "Authorization: Bearer $AGENT_CONTROL_TOKEN"
```

Expected fields:

```json
{
  "status": "ok",
  "service": "brandon-re-api",
  "risk_tier": "workspace_action_foundation"
}
```

Check Hermes:

```bash
curl -sS https://atlas-agent-production-99dc.up.railway.app/health
```

Expected fields:

```json
{
  "status": "ok",
  "gateway": "running"
}
```

`gateway="running"` confirms Hermes is up. The native dashboard `/api/status` should show `gateway_platforms.telegram.state="connected"`.

Check Telegram through Hermes setup/native status:

```bash
# Use .env.hermes-admin.local locally for admin credentials and query:
#   https://atlas-agent-production-99dc.up.railway.app/setup/api/status
#   https://atlas-agent-production-99dc.up.railway.app/api/status
```

Expected fields:

```json
{
  "setup_telegram": true,
  "telegram_runtime": {
    "state": "connected",
    "error_code": null,
    "error_message": null
  }
}
```

## Safety Boundary

This foundation exposes operational context plus the protected Workspace action tools:

- backend status
- allowlisted actions
- recent lead summaries
- recent booking summaries
- Workspace connection status
- Google Drive search
- Google Drive file text read for supported Docs/text files
- Gmail search
- Gmail thread read
- Gmail draft creation
- Google Doc creation
- Google Sheets row append
- Gmail send with explicit Brandon confirmation
- Google Calendar event search
- Google Calendar event creation with explicit Brandon confirmation
- Google Contacts search

Do not enable SMS, Telegram client replies, CRM writes, or broader backend mutation endpoints until a later approved spec adds risk-tiered confirmations. Direct Gmail sending is available only through the `workspace.gmail.send` action and requires `confirmed_by_brandon=true`. Calendar event creation is available only through `workspace.calendar.event.create` and also requires `confirmed_by_brandon=true`.
