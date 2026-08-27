# Hermes Railway Deployment Runbook

This runbook is for the private Brandon AI / Atlas assistant foundation.

For the separate Gmail/Sydney integration worker, provider switches, cursor and
Telegram recovery, rollback, and Task 9 production evidence, see
[`gmail-sydney-task-intake.md`](gmail-sydney-task-intake.md).

## Verified Railway Context

- Railway project: `enchanting-perception`
- Project ID: `aa6c9f9c-46d4-4f5d-b529-86b073de4972`
- Existing FastAPI backend service: `extraordinary-prosperity`
- Existing backend service ID: `37afead7-c55b-4ef2-8071-ca4da1c88992`
- Hermes service: `atlas-agent`
- Hermes service ID: `6dc65984-89c1-400c-9d17-d5412befd031`
- Hermes URL: `https://atlas-agent-production-99dc.up.railway.app`
- Environment: `production`

Task 14 production used an account/workspace token verified with Member access
to `enchanting-perception` on 2026-08-26. That verified credential was supplied
outside Git and must not be inferred from the contents of the gitignored
`.env.railway-sweeney.local`; the file may still hold an older credential. Use
the repository wrapper only after its live access checks pass, so the value is
loaded without printing it:

```bash
scripts/railway-sweeney whoami
scripts/railway-sweeney status --json
```

Alternatively, use a directly authenticated Railway CLI session. Unset token
environment variables so they cannot override that interactive session:

```bash
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway whoami
```

Before any production operation, require `whoami`, `railway list --json` to
include `enchanting-perception`, project status, Member-level SSH, and the intended
project/environment/service to succeed through the same authentication path. A
successful login to some other workspace is not sufficient. Never print, commit,
or copy the token into command output.

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

Current status as of 2026-08-26:

- The FastAPI bridge is live and verified.
- `atlas-agent` is live in the same Railway project.
- Backend deployment `e29cfc64-5b2d-4265-ad9d-0e0d7d00a226` is `SUCCESS`.
- Atlas deployment `51f50a75-32ed-4ed7-bd88-5dc5bfde0988` is `SUCCESS`.
- The public dashboard URL is `https://atlas-agent-production-99dc.up.railway.app`.
- The health check returns `{"status":"ok","gateway":"running"}` after Gemini provider setup.
- Admin credentials are stored only in local ignored `.env.hermes-admin.local` and Railway variables.
- The Task 14 account/workspace token was verified with Member-level SSH and
  deployment access, but it was not persisted over the older credential in the
  ignored `.env.railway-sweeney.local`. The wrapper or directly authenticated CLI
  is acceptable only when that exact authentication path can list and access
  `enchanting-perception` without displaying a credential.
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
        - context_history_search
        - command_contacts_search
        - command_contact_audience_preview
      resources: false
      prompts: false
```

The production bridge was verified from inside `atlas-agent` on 2026-08-23 with
the prior 22-tool contract. The Sydney release gate supersedes that count: raw
JSON-RPC `tools/list` must return exactly 25 ordered unique names, preserve the
original 22 byte-for-byte and in order, and append only the three read tools
shown above. The deployed `gmail_send` schema still requires a caller-supplied
UUID `request_id`.

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

- exactly 25 ordered and unique names;
- the first 22 names exactly match the prior production registry;
- the three Sydney/Command read tools are appended once;
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
- bounded source-linked Sydney history search
- Command-only contact search
- server-side Command audience preview

Do not expose confirmed CRM task creation, actual suggestion approval/dismissal,
archive, restore, SMS, Telegram client replies, or broader backend mutation
endpoints until a later approved spec adds the required trust and confirmation
gates. Direct Gmail sending is available only through the `workspace.gmail.send`
action and requires `confirmed_by_brandon=true` plus a caller UUID. Calendar event
creation is available only through `workspace.calendar.event.create` and also
requires `confirmed_by_brandon=true`.

## Sydney Durable Context Controlled Rollout

This release keeps PostgreSQL canonical, `/data/.hermes/state.db` as the local
Hermes transcript, and `/data/.hermes/sydney_spool.db` as a private crash-safe
WAL outbox and last-good context cache. It does not delete or compact source
history. Visible user, assistant, tool-call, and tool-result text is redacted
before enqueue, including configured secret values, authorization headers, and
natural-language password/client-secret disclosures. URL redaction recursively
sanitizes direct, nested percent-encoded, and JSON-wrapped login/callback values
while retaining benign selectors such as `proposal_id`. Hidden reasoning,
credentials, and raw binary attachments are not copied into canonical history.
The event-batch endpoint rejects an aggregate body over 8 MiB before JSON
decoding. Atlas splits multi-event batches below that cap and fails closed if a
single event cannot fit.

Tool execution is fenced by the exact live run lease in PostgreSQL. Mutating
calls are matched across regenerated model call IDs by a canonical argument hash
or hashed caller idempotency key; a completed result is restored and an
uncertain result blocks replay. Visible failed tool results are redacted and
retained as history. Transport timeout/connection exception types are eligible
for bounded automatic retry even when the provider supplies no status code.
Inbound and final run references are also provenance checked: only the exact
conversation's user event can start a run, and only that session's assistant
event can complete it.
Hermes hides the prefixed MCP history-search variant from the model and exposes
only the provider-owned `context_history_search`, which injects the authenticated
identity server-side.

The four backend switches default to `false` and must be promoted separately:

- `SYDNEY_DURABLE_CONTEXT_ENABLED` allows redacted canonical writes and health.
- `SYDNEY_DURABLE_CONTEXT_RETRIEVAL_ENABLED` allows bounded automatic recall and
  history search.
- `SYDNEY_DURABLE_CONTEXT_PROJECTION_ENABLED` allows the worker to produce
  source-linked checkpoints and facts.
- `SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED` allows leased automatic continuation of
  eligible transient failures.

Atlas also requires the exact private Telegram user/chat mapping and the same
user in `SYDNEY_DURABLE_CONTEXT_ALLOWED_USER_IDS`. The provider fails closed for
every non-allowlisted identity. Never put those IDs or any bearer token in a
deployment message, log, report, or committed file.

### Pre-deployment gates

Development gate recorded 2026-08-26:

- The final changed-test matrix passed `757` with `5` expected exact-checkout
  skips; the separate Atlas suite passed `16/16`.
- Fresh detached template `7224d7c1a4dcffe9304f49bc843f55716f5561b4`
  and Hermes `77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5` sources passed
  the exact `227/227` gate.
- The real JSON-RPC verifier returned exactly 25 ordered unique tools, retained
  the original 22 unchanged, exposed no forbidden tool, and required caller
  UUID `gmail_send.request_id`.
- PostgreSQL 17/TLS regressions, sole Alembic head `85e8b7c9d4f1`, focused
  Ruff, compileall, `git diff --check`, credential scanning, and independent
  review passed. This is pre-release evidence only and must not be substituted
  for the live gates below.

1. Record the reviewed branch SHA and require a clean worktree.
2. Create a mode-0600 custom-format PostgreSQL backup outside the repository and
   prove `pg_restore --list` can read it.
3. Confirm all four switches are `false` on the backend and worker, and the
   master/retry switches are `false` on Atlas.
4. Deploy the backend and worker from the reviewed SHA, then run `alembic upgrade
   head` once against production. `alembic current` and `alembic heads` must both
   identify sole head `85e8b7c9d4f1`.
5. Apply `hermes/overlay/apply_overlay.py` to a fresh detached template checkout
   at `7224d7c1a4dcffe9304f49bc843f55716f5561b4`. The inner installer must verify
   official Hermes tag `v2026.5.29.2`, commit
   `77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5`, and every pinned upstream hash.
6. Deploy that exact generated template to `atlas-agent`, preserving the existing
   `/data` volume. Backend, worker, and Atlas deployments must each reach
   `SUCCESS`, and their health checks must pass before enablement.

### Shadow ingest, backfill, and reconciliation

Enable only the master switch on the backend, worker, and Atlas. Keep retrieval,
projection, and retry disabled. Run the backfill inside the Atlas container so
the transcript never leaves `/data`:

```bash
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway ssh \
  --project aa6c9f9c-46d4-4f5d-b529-86b073de4972 \
  --service atlas-agent --environment production -- \
  sh -lc 'cd /opt/hermes-agent && python -m plugins.memory.sydney.sydney_backfill \
    --state-db /data/.hermes/state.db \
    --spool /data/.hermes/sydney_spool.db \
    --platform telegram \
    --user-id "$SYDNEY_DURABLE_CONTEXT_EXTERNAL_USER_ID" \
    --chat-id "$SYDNEY_DURABLE_CONTEXT_EXTERNAL_CHAT_ID" \
    --display-label "${SYDNEY_DURABLE_CONTEXT_DISPLAY_LABEL:-Brandon}" \
    --reconcile --wait-seconds 60'
```

The command exits nonzero unless its content-free JSON report has all of these:

- `matched=true` and `unacknowledged_count=0`;
- equal source/acknowledged session, message, event, role, tool-call, and
  tool-result counts;
- equal source/acknowledged ordered global hashes;
- one opaque session-key hash per useful session with matching source,
  acknowledgement, and canonical PostgreSQL hashes.

The backend accepts reconciliation only when the caller's exact event count and
timestamp/UUID-ordered hash match PostgreSQL. Every later inserted event clears
the prior reconciliation marker; Atlas restores it automatically only after all
local receipts for that session are acknowledged. The one-second provider loop
selects at most 25 dirty sessions and reads persisted per-session aggregates
instead of rebuilding hashes across lifetime history. Compacted inbound
tombstones retain a content-free terminal run state,
so a duplicate platform delivery is reported as already finalized rather than
as newly queued work. Do not enable retrieval while
any session or global comparison differs. Backfill resolves only the configured
Telegram chat's sessions and fails closed when history exists without that exact
chat mapping. Once shadow mode is live, ordinary turn synchronization copies
only assistant/tool rows after the current inbound user boundary, so rows already
covered by backfill cannot be inserted again under live source keys.

### Promotion and acceptance

1. Enable retrieval for Brandon only. Verify a fresh turn automatically recalls
   a known source-linked fact from an earlier Hermes session within the 16,000
   token packet cap. Verify `context_history_search` can find older exact
   evidence without `/new`, `/reset`, or `/compact`.
2. Enable projection on the worker. Require content-free health to show bounded
   checkpoint lag and no projection error; every checkpoint/fact must retain
   cumulative source event IDs. Oversized source events advance through explicit
   character offsets, so a checkpoint never claims an unprojected remainder.
   Immutable ingestion sequence, not the source timestamp, determines projection
   coverage, so delayed events remain eligible. The worker must commit one
   expiring range lease before Gemini; concurrent workers must produce one
   provider call for that range, skip the live lease to process other eligible
   conversations, and apply must consume the exact live lease token. A model echo
   may be bound to that server-owned committed range only when it retains both
   endpoints, preserves order, contains no duplicate or foreign ID, omits exactly
   one interior ID, and cites facts only from echoed IDs. Endpoint or multiple
   omissions, reordering, duplicates, foreign IDs, and inconsistent fact citations
   remain invalid and fail closed.
3. Run the controlled synthetic `429` continuation with no mutating external
   tool. Prove one saved run moves through `waiting_retry`, survives a provider
   restart, is leased once when due, sends one final answer, and produces zero
   Gmail, Calendar, CRM, or other external writes. The exact private Telegram
   retry path disables token/interim streaming, stages the final response hash
   in the private spool before Telegram delivery, and clears that marker only
   after canonical completion succeeds. Restart with a surviving delivery
   marker must block duplicate delivery for reconciliation. Then enable retry.
4. Repeat a real session transition/compression canary and a Command-only
   contact read. Confirm the same logical conversation continues, MCP remains
   exactly 25 backend tools, the model sees only one unprefixed
   `context_history_search`, and no Google Contacts fallback or write occurs.
5. Record deployment IDs, reviewed SHAs, migration head, content-free counts and
   hashes, canary event/run IDs, and timestamps in `tdtn.md` and `memory.md`.
   Never record transcript text, Telegram IDs, tool arguments, or secrets.

### Task 14 production evidence

Completed 2026-08-26:

- Feature PR `#14` and test-first rollout corrections through PR `#26` passed
  their required checks and were merged with reviewed-head pinning. The final
  application-code merge on `main` is
  `de986f5e9c3808fd1253c2532670bfd9f7ce9e65`; later evidence-only commits do not
  change the runtime behavior.
- The protected pre-migration custom-format backup is
  `/Users/rishabnandi/brandon-real-estate-production-backups/sydney-task14-pre-migration-20260826T180513Z.dump`,
  mode `0600`, `516102115` bytes, SHA-256
  `8a200bba3ca51af9eba43e028a838b90eaaf4ef51553a33e77c8c7b7a2252847`.
  PostgreSQL 17 read its `732`-entry restore catalog. Production `alembic current`
  and `alembic heads` both report sole head `85e8b7c9d4f1`.
- Application-code rollout backend `4a761b35-04b6-4ab2-8774-7ef20c5f072f`, worker
  `0b3bf3b5-ca82-4d26-b585-0502965fd7df`, and Atlas
  `34932fbf-e916-4032-97fa-50b9d477a815` deployments reached `SUCCESS`.
  Backend/worker health, worker readiness, Atlas health, and the single gateway
  process pass. Live JSON-RPC returns exactly 25 ordered unique tools, preserves
  the original 22, and exposes no forbidden write tool. Treat these deployment
  IDs as code-rollout evidence; evidence-only merges may trigger later
  byte-equivalent backend/worker deployments.
- Backfill reconciliation matched `8` sessions, `918` messages, `947` events,
  roles `assistant=442`, `tool=455`, `user=21`, `455/455` tool calls/results,
  zero unacknowledged rows, and ordered hash
  `9c7c960a59b959e13faa317fda987193d60b8416367212da249c4281a73be689`.
  After live continuation, all `14` canonical sessions are reconciled.
- Retrieval remained automatically source-linked under `16000` estimated tokens;
  bounded history search retained event IDs. Command-only contact search and
  audience preview returned masked samples plus a valid server checksum/reference.
  No Google Contacts fallback, UI scraping, email, calendar, CRM mutation, or
  write tool occurred.
- The controlled retry proof saved one `45`-second wait and acknowledgement,
  survived an Atlas restart, and completed once on attempt `2`, with one final
  canonical assistant event/reference, zero tool invocations, no unresolved run,
  and a clean spool. Synthetic markers and temporary production probe files were
  removed.
- The first corrected projection cycle advanced checkpoints `16 -> 17` and facts
  `14 -> 15`, reset `23` accumulated failures to zero, released the range claim,
  and returned protected context health to `ready`. Raw source-linked retrieval
  remains available while the bounded backlog advances.
- A later 100-event range exposed a separate bounded-output failure: Gemini used
  `18911` prompt tokens, reached the strict `4096`-token response ceiling at
  `4081` output tokens, and returned no parsed object. The same server-owned range
  bounded to 50 events stopped normally at `3205` output tokens, echoed all source
  IDs, and passed strict provenance validation. PR `#26` changes only the default
  per-cycle event range from `100` to `50`; larger histories advance through more
  immutable checkpoints. Two consecutive deployed cycles advanced
  checkpoints/facts `41/35 -> 43/36`, reduced lag `155 -> 55`, reset failures
  `7 -> 0`, released every claim, and kept protected status `ready`.
- Feature gates are fully promoted only in their owning processes: backend has
  master/retrieval/projection/retry enabled; worker has master/projection enabled;
  Atlas has master/retrieval/retry enabled. The validated backup and canonical
  evidence remain preserved for evidence-safe rollback.

### Rollback

Disable retry, projection, and retrieval first, then the master switch on Atlas,
the worker, and the backend. Redeploy/wait for `SUCCESS`, confirm the gateway and
existing MCP bridge remain healthy, and leave PostgreSQL rows, `state.db`, and
the spool intact. Atlas keeps a mode-0600 snapshot of only the config fields
owned by Sydney and restores them when the master switch is disabled, even if
the backend bridge URL or token is simultaneously unavailable. A code rollback
may use the reviewed pre-release image; a
database restore is reserved for independently confirmed migration corruption
and uses the validated protected backup. Never delete history merely to clear a
health mismatch.
