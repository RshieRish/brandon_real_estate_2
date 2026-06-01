# Hermes Railway Deployment Runbook

This runbook is for the private Brandon AI / Atlas assistant foundation.

## Verified Railway Context

- Railway project: `enchanting-perception`
- Project ID: `aa6c9f9c-46d4-4f5d-b529-86b073de4972`
- Existing FastAPI backend service: `extraordinary-prosperity`
- Existing backend service ID: `85541f63-2aa1-4679-8114-98895f4bf215`
- New Hermes service name: `atlas-agent`
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
- `atlas-agent` has not been created yet.
- The current `.env.railway-sweeney.local` uses a project-scoped `RAILWAY_TOKEN`, which works for the existing backend service but was rejected by Railway when attempting to create a new GitHub-backed service from `praveen-ks-2001/hermes-agent-template`.
- Use the Railway dashboard or a dedicated account-wide `RAILWAY_API_TOKEN` for the actual service creation step.
- The Railway template URL checked on 2026-06-01 is `https://railway.com/deploy/hermes-agent-nous-research`; it requires `ADMIN_USERNAME` and `ADMIN_PASSWORD`, persists config under `/data`, and stores LLM/channel keys through the Hermes dashboard.

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

## Verification

Check both services:

```bash
scripts/railway-sweeney service status --all
```

Expected shape:

```text
Services in production:

extraordinary-prosperity | 85541f63-2aa1-4679-8114-98895f4bf215 | SUCCESS
atlas-agent | Railway-assigned service UUID | SUCCESS
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

## Safety Boundary

This foundation exposes read-only operational context only:

- backend status
- allowlisted actions
- recent lead summaries
- recent booking summaries

Do not enable outbound email, SMS, Telegram client replies, calendar invites, CRM writes, or backend mutation endpoints until a later approved spec adds risk-tiered confirmations.
