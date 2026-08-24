# Hermes Railway Deployment Runbook

This runbook is for the private Brandon AI / Atlas assistant foundation.

## Verified Railway Context

- Railway project: `enchanting-perception`
- Project ID: `aa6c9f9c-46d4-4f5d-b529-86b073de4972`
- Existing FastAPI backend service: `extraordinary-prosperity`
- Existing backend service ID: `37afead7-c55b-4ef2-8071-ca4da1c88992`
- Hermes service: `atlas-agent`
- Hermes service ID: `6dc65984-89c1-400c-9d17-d5412befd031`
- Hermes URL: `https://atlas-agent-production-99dc.up.railway.app`
- Environment: `production`

Use the directly authenticated Railway CLI. Unset token environment variables so
an old saved token cannot override the active Member session:

```bash
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway whoami
```

The token currently stored in `.env.railway-sweeney.local` is stale or unauthorized
for this project and must not be used as production evidence. The direct CLI session
was verified against project `enchanting-perception` with Member-level SSH access on
2026-08-23.

## Backend Bridge Variables

Set these on the existing FastAPI service only when ready. Run them from a
temporary directory linked to project `aa6c9f9c-46d4-4f5d-b529-86b073de4972`,
production, and service `extraordinary-prosperity`; do not link or rewrite an
unrelated checkout:

```bash
: "${AGENT_CONTROL_TOKEN_VALUE:?set AGENT_CONTROL_TOKEN_VALUE first}"
task8_backend_link_dir="$(mktemp -d /tmp/sws-backend-link.XXXXXX)"
trap '/usr/bin/trash "$task8_backend_link_dir"' EXIT
cd "$task8_backend_link_dir"

env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway link \
  --project aa6c9f9c-46d4-4f5d-b529-86b073de4972 \
  --environment production --service extraordinary-prosperity --json
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway status --json

printf '%s' "$AGENT_CONTROL_TOKEN_VALUE" | \
  env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway variable set \
    --service extraordinary-prosperity --environment production \
    --skip-deploys --stdin AGENT_CONTROL_TOKEN
unset AGENT_CONTROL_TOKEN_VALUE
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway variable set \
  --service extraordinary-prosperity --environment production --skip-deploys \
  AGENT_CONTROL_RECENT_LIMIT=10
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway variable set \
  --service extraordinary-prosperity --environment production --skip-deploys \
  AGENT_CONTROL_ENABLED=true

env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway redeploy \
  --service extraordinary-prosperity --yes --json
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway deployment list \
  --service extraordinary-prosperity --environment production --limit 1 --json
```

Generate `AGENT_CONTROL_TOKEN` with a password manager or:

```bash
openssl rand -hex 32
```

Never commit the token.

## Hermes Service

Current status as of 2026-08-23:

- The FastAPI bridge is live and verified.
- `atlas-agent` is live in the same Railway project.
- Backend deployment `e29cfc64-5b2d-4265-ad9d-0e0d7d00a226` is `SUCCESS`.
- Atlas deployment `51f50a75-32ed-4ed7-bd88-5dc5bfde0988` is `SUCCESS`.
- The public dashboard URL is `https://atlas-agent-production-99dc.up.railway.app`.
- The health check returns `{"status":"ok","gateway":"running"}` after Gemini provider setup.
- Admin credentials are stored only in local ignored `.env.hermes-admin.local` and Railway variables.
- The saved token in `.env.railway-sweeney.local` is not authorized for current
  project operations. Production verification uses the direct Member-authenticated
  CLI session with both Railway token environment variables unset.
- The deployed fallback path was: create an empty `atlas-agent` service, attach `/data`, set admin vars, then upload the checked-out template with `railway up --path-as-root`.
- The Railway template URL checked on 2026-06-01 is `https://railway.com/deploy/hermes-agent-nous-research`; it requires `ADMIN_USERNAME` and `ADMIN_PASSWORD`, persists config under `/data`, and stores LLM/channel keys through the Hermes dashboard.
- Template commit deployed: `7224d7c1a4dcffe9304f49bc843f55716f5561b4`.
- Persistent volume: `atlas-agent-volume`, ID `594c4970-ba61-4888-8372-57d0c235db65`, mounted at `/data`, size `5000 MB`.
- `BRANDON_BACKEND_URL` and masked `BRANDON_AGENT_CONTROL_TOKEN` are set on `atlas-agent` for future backend-control skills.
- Gemini provider is configured in Hermes persistent config with `LLM_MODEL=gemini-3.5-flash`.
- Telegram is configured for `soldwithsweeney_bot` with Brandon's Telegram user ID in the allowlist.
- Telegram home channel is Brandon's private DM chat ID, so future default Hermes deliveries can target Brandon without repeating a chat ID.
- Atlas backend MCP bridge is included in the custom Hermes image and writes `mcp_servers.atlas_backend` at boot when `BRANDON_BACKEND_URL` and `BRANDON_AGENT_CONTROL_TOKEN` exist.
- Task 8 source commit: `a53ff04421c395be54012398cc1dccecddf08f97`.
- Task 8 was merged to `main` by PR #5 at `f3ed543359cac39c3caa66dd3d25592319f1b921`.
- Latest custom Hermes deployment: `51f50a75-32ed-4ed7-bd88-5dc5bfde0988` reached `SUCCESS`.
- Railway SSH works for the direct CLI session because that account has the Member role.

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

Historical note: `volume add` needed a temporary service link because the
then-current saved account/workspace token was not authorized to create one
interactively. That temporary `/tmp` link was removed after the volume was
attached.

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
        - crm_tasks_read
        - crm_task_suggestions_read
        - crm_task_clarifications_answer
        - crm_task_drafts_create
        - crm_task_suggestions_approval_link
        - crm_task_suggestions_dismiss_proposal
      resources: false
      prompts: false
```

The production bridge was verified from inside `atlas-agent` on 2026-08-23.
`hermes mcp test atlas_backend` connected and discovered 22 tools. A separate raw
JSON-RPC `tools/list` request against `/app/atlas_backend_mcp.py` returned the exact
ordered registry above: 22 names, 22 unique names, the original 16 unchanged, and
the six review tools appended once. The deployed `gmail_send` schema requires a
caller-supplied UUID `request_id`.

### Deployed Task 8 overlay

`hermes/overlay/manifest.json` pins the Hermes template source to commit
`7224d7c1a4dcffe9304f49bc843f55716f5561b4`. The local overlay preserves the
16 prior tool names above in their existing order and adds exactly these
six additional CRM review tools:

- `crm_tasks_read`
- `crm_task_suggestions_read`
- `crm_task_clarifications_answer`
- `crm_task_drafts_create`
- `crm_task_suggestions_approval_link`
- `crm_task_suggestions_dismiss_proposal`

The overlay was applied reproducibly to the pinned upstream checkout and deployed
as Railway deployment `51f50a75-32ed-4ed7-bd88-5dc5bfde0988` only after the
authenticated Task 7 review route, two-stage handoff exchange, blocker UI, and
production deployment were verified. The answer and draft tools treat Hermes
input as untrusted draft evidence. The dismissal tool only records a
non-authoritative review proposal; it cannot dismiss, suppress, or release
anything. Actual `crm_task_suggestions_dismiss`,
`crm_task_suggestions_approve`, `crm_tasks_create_confirmed`,
`crm_tasks_archive`, and `crm_tasks_restore` tools remain absent.

## Verification

Check both services:

```bash
task8_status_link_dir="$(mktemp -d /tmp/sws-status-link.XXXXXX)"
trap '/usr/bin/trash "$task8_status_link_dir"' EXIT
cd "$task8_status_link_dir"

env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway link \
  --project aa6c9f9c-46d4-4f5d-b529-86b073de4972 \
  --environment production --service extraordinary-prosperity --json
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway status --json
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway deployment list \
  --service extraordinary-prosperity --environment production --limit 1 --json

env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway link \
  --project aa6c9f9c-46d4-4f5d-b529-86b073de4972 \
  --environment production --service atlas-agent --json
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway status --json
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway deployment list \
  --service atlas-agent --environment production --limit 1 --json
```

Expected shape:

```json
[
  {
    "id": "deployment UUID for the linked service",
    "status": "SUCCESS"
  }
]
```

Each `railway status --json` call must name the intended project, production
environment, and service before accepting its separate deployment list.

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

Check the live MCP registry from inside the deployed Atlas container:

```bash
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway ssh \
  --project aa6c9f9c-46d4-4f5d-b529-86b073de4972 \
  --service atlas-agent --environment production -- \
  hermes mcp test atlas_backend
```

The deployed Hermes CLI supports `hermes mcp test`, but does not support
`hermes mcp tools list ... --json`. Run the checked-in verifier through Railway
SSH for the machine-readable release gate:

```bash
task8_probe_path="$(git rev-parse --show-toplevel)/hermes/verify_atlas_tools.py"
task8_probe_b64="$(base64 < "$task8_probe_path" | tr -d '\n')"
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway ssh \
  --project aa6c9f9c-46d4-4f5d-b529-86b073de4972 \
  --service atlas-agent --environment production -- \
  "python -c 'import base64;exec(base64.b64decode(\"$task8_probe_b64\"))'"
unset task8_probe_b64
```

`hermes/verify_atlas_tools.py` starts `/app/atlas_backend_mcp.py`, sends
`initialize`, `notifications/initialized`, and `tools/list`, prints one JSON
proof object, and exits nonzero unless it confirms:

- exactly 22 ordered and unique names;
- the first 16 names exactly match the prior production registry;
- all six CRM review tools are appended once;
- the five actual approve/dismiss/create-confirmed/archive/restore tools are absent;
- `gmail_send.inputSchema.required` contains `request_id` and its format is `uuid`.

Source inspection or a local registry test does not replace this live gate.

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
- CRM task and review-suggestion reads
- clarification answers recorded as untrusted draft evidence
- non-authoritative CRM task review drafts
- fragment-only Command approval handoff links
- non-authoritative dismissal review proposals

Do not expose confirmed CRM task creation, actual suggestion approval/dismissal,
archive, restore, SMS, Telegram client replies, or broader backend mutation
endpoints until a later approved spec adds the required trust and confirmation
gates. Direct Gmail sending is available only through the `workspace.gmail.send`
action and requires `confirmed_by_brandon=true` plus a caller UUID. Calendar event
creation is available only through `workspace.calendar.event.create` and also
requires `confirmed_by_brandon=true`.
