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
- The health check returns `{"status":"ok","gateway":"stopped"}`.
- Admin credentials are stored only in local ignored `.env.hermes-admin.local` and Railway variables.
- The current `.env.railway-sweeney.local` uses a project-scoped `RAILWAY_TOKEN`, which works for existing service operations but was rejected by Railway when attempting to create a new GitHub-backed service from `praveen-ks-2001/hermes-agent-template`.
- The deployed fallback path was: create an empty `atlas-agent` service, attach `/data`, set admin vars, then upload the checked-out template with `railway up --path-as-root`.
- The Railway template URL checked on 2026-06-01 is `https://railway.com/deploy/hermes-agent-nous-research`; it requires `ADMIN_USERNAME` and `ADMIN_PASSWORD`, persists config under `/data`, and stores LLM/channel keys through the Hermes dashboard.
- Template commit deployed: `7224d7c1a4dcffe9304f49bc843f55716f5561b4`.
- Persistent volume: `atlas-agent-volume`, ID `594c4970-ba61-4888-8372-57d0c235db65`, mounted at `/data`, size `5000 MB`.
- `BRANDON_BACKEND_URL` and masked `BRANDON_AGENT_CONTROL_TOKEN` are set on `atlas-agent` for future backend-control skills.

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
  "risk_tier": "read_only_foundation"
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
  "gateway": "stopped"
}
```

`gateway="stopped"` is expected until the LLM provider and Telegram channel are configured in the Hermes dashboard.

## Safety Boundary

This foundation exposes read-only operational context only:

- backend status
- allowlisted actions
- recent lead summaries
- recent booking summaries

Do not enable outbound email, SMS, Telegram client replies, calendar invites, CRM writes, or backend mutation endpoints until a later approved spec adds risk-tiered confirmations.
