# Gmail and Sydney Task Intake Railway Runbook

This runbook owns the production deployment and recovery procedure for the
Gmail-to-Command review loop, Sydney clarification delivery, and the dedicated
Railway integration worker. It does not grant autonomous task-creation authority:
an authenticated administrator must still review the final payload and click
**Approve task** in Command.

## Production status

As of 2026-08-24, Task 9's three controlled production paths passed and the
rollout was shut back down:

- backend service `extraordinary-prosperity` deployment
  `c46df9ff-d4c1-48a5-8b3b-adb29e3b43af` is `SUCCESS` on main commit
  `ca544e6dc9e99c08b3cd9b2c498eefd0774d1cf5`;
- worker service `integration-worker` deployment
  `e4efa174-0d7b-4623-8f05-afbb8246d980` is `SUCCESS` on the same commit;
- backend `/health` returns exactly
  `{"status":"ok","service":"brandon-re-api"}`;
- worker `/health` returns exactly
  `{"status":"ok","service":"integration-worker"}` and `/ready` returns the
  exact six-field ready object documented below;
- `GMAIL_TASK_INTAKE_ENABLED=false`,
  `SYDNEY_TASK_QUESTIONS_ENABLED=false`, and
  `INSTAGRAM_INTEGRATION_ENABLED=false` are explicitly set on both services;
- `COMMAND_PUBLIC_BASE_URL=https://www.soldwithsweeney.com` is explicitly set
  on the backend. Handoff links are absolute and retain their one-time secret
  only in the URL fragment.

Durable evidence is intentionally retained when the switches are disabled.
Disabling jobs is operational rollback; it is not permission to delete receipts,
origins, suggestions, clarifications, nonces, audits, or created tasks.

## Railway service contract

The worker is a separate Railway service in project `enchanting-perception`,
environment `production`:

- root directory: `/backend`
- service config: `/backend/railway.integration-worker.json`
- image: `/backend/Dockerfile.worker`
- start command: `python -m workers.integration_worker`
- Railway restart/liveness path: `/health`
- health timeout: 30 seconds
- restart policy: on failure, at most three retries

`/health` is dependency-free liveness. Railway must never use `/ready` as its
container restart path. `/ready` is the post-deploy promotion gate: it checks the
database, sole migration, current worker heartbeat, and initialized job registry.

Run the checked-in readiness probe from the repository root:

```bash
python backend/scripts/check_integration_worker.py \
  --base-url https://integration-worker-production.up.railway.app \
  --timeout 10
```

Expected output is `integration-worker ready`; the fetched object must equal:

```json
{
  "status": "ready",
  "service": "integration-worker",
  "database": "ok",
  "migration": "ok",
  "heartbeat": "ok",
  "job_registry": "ok"
}
```

The worker registry runs notification delivery every 60 seconds and integration
alerts every 60 seconds regardless of the provider gates. When enabled, Gmail
History runs every 120 seconds, receipt extraction every 30 seconds, and Sydney
questions every 30 seconds. Instagram health remains separately gated.

## Environment variables

Never commit or print variable values. Use Railway service references for shared
values and keep the Telegram bot token on the worker only.

Required shared runtime configuration:

| Variable | Contract |
| --- | --- |
| `DATABASE_URL` | Primary TLS PostgreSQL URL. |
| `GMAIL_HISTORY_DATABASE_URL` | Direct, non-pooler TLS URL to the same database; required for session-affine advisory locks. |
| `GOOGLE_WORKSPACE_CLIENT_ID` | Workspace OAuth client ID. A complete compatible Google client tuple may be used only through the existing resolver. |
| `GOOGLE_WORKSPACE_CLIENT_SECRET` | Workspace OAuth client secret. |
| `GOOGLE_WORKSPACE_REDIRECT_URI` | Exact registered Workspace OAuth callback. |
| `GEMINI_API_KEY` | Structured Gmail task extractor credential. |
| `GMAIL_PARTICIPANT_HASH_KEY` | Stable, whitespace-free ASCII secret of at least 32 characters. Never rotate without a digest migration. |
| `GMAIL_TASK_INTAKE_ENABLED` | Enables both History and receipt jobs. Default and rollback value: `false`. |
| `SYDNEY_TASK_QUESTIONS_ENABLED` | Enables Telegram clarification enqueue/delivery. Default and rollback value: `false`. |
| `INSTAGRAM_INTEGRATION_ENABLED` | Independent future provider gate. Default and rollback value: `false`. |

The bound Workspace refresh token is database-authoritative. Do not copy it into
logs or deployment documentation.

Sydney configuration, required only while questions are enabled:

| Variable | Contract |
| --- | --- |
| `SYDNEY_TELEGRAM_BOT_TOKEN` | Worker-only Telegram bot token. |
| `SYDNEY_TELEGRAM_BRANDON_CHAT_ID` | The one allowlisted outbound private chat. |
| `SYDNEY_TELEGRAM_BRANDON_USER_ID` | Future inbound configuration only; it grants no authority in this rollout. |
| `SYDNEY_CLARIFICATION_CODE_KEYS_JSON` | JSON keyring of positive versions to base64-encoded 32-byte keys. Keep old versions until their rows close. |
| `SYDNEY_CLARIFICATION_ACTIVE_KEY_VERSION` | Positive version used for new clarification codes. |

Worker timing and capacity configuration:

```text
INTEGRATION_WORKER_HEARTBEAT_SECONDS=30
INTEGRATION_WORKER_HEARTBEAT_MAX_AGE_SECONDS=120
INTEGRATION_PROVIDER_MAX_WORKERS=4
INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS=10
INTEGRATION_PROVIDER_DEADLINE_SECONDS=30
GMAIL_HISTORY_MAX_PAGES_PER_RUN=100
GMAIL_HISTORY_JOB_DEADLINE_SECONDS=300
GMAIL_RECEIPT_PROCESSING_DEADLINE_SECONDS=35
GMAIL_RECEIPT_PROCESSING_STALE_AFTER_SECONDS=120
```

The receipt deadline must remain at least five seconds longer than the provider
deadline so a timed-out extraction can be finalized durably before lease expiry.

Backend-only link configuration:

```text
COMMAND_PUBLIC_BASE_URL=https://www.soldwithsweeney.com
```

Both handoff generators must return a full URL on this origin. The handoff token
belongs only after `#handoff=`; it must never appear in a query parameter, log,
document, or database plaintext.

## Promotion and disable sequence

Before any enablement, require all of the following:

1. The backend, worker, frontend, and Atlas deployments identify the intended
   reviewed commits and report success.
2. Alembic `current` and `heads` both report sole head `84d7a5f9b2c3`.
3. Backend `/health`, worker `/health`, and the repository-owned `/ready` probe
   pass.
4. Workspace profile and current Gmail History access pass without exposing the
   mailbox or credential.
5. Telegram `getMe` passes and exactly one outbound chat is configured.
6. The authenticated Command handoff clears its fragment before any network
   activity, exchange only prepares approval, and a separate click remains
   necessary.
7. The live deployed Atlas check described in
   `docs/deployment/hermes-railway.md` returns exactly 25 ordered unique tools,
   retains the prior 22 unchanged, and exposes none of the five trusted write
   tools.
8. Pending unrelated suggestions and incidents are reviewed before enabling the
   global Sydney question job.

Enable Gmail in `shadow` mode first. Observe History and receipt processing before
enabling Sydney questions. Never enable autonomous creation; confirmed task
application remains Command-only.

To stop the rollout, set all three switches to `false` on both the backend and
worker. Use the directly authenticated Member CLI session with saved token
environment variables unset:

```bash
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway variables \
  --service extraordinary-prosperity \
  --set GMAIL_TASK_INTAKE_ENABLED=false \
  --set SYDNEY_TASK_QUESTIONS_ENABLED=false \
  --set INSTAGRAM_INTEGRATION_ENABLED=false

env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway variables \
  --service integration-worker \
  --set GMAIL_TASK_INTAKE_ENABLED=false \
  --set SYDNEY_TASK_QUESTIONS_ENABLED=false \
  --set INSTAGRAM_INTEGRATION_ENABLED=false
```

Wait for both deployments to reach `SUCCESS`, confirm both services are on the
intended commit, rerun the health/readiness probes, and verify the newest worker
heartbeat has `current_job=null`. Do not clear durable evidence during rollback.

## Gmail final-page cursor, reseed, and backfill

History progression is page-durable and fail-closed:

1. One account session advisory lock and backend connection remain bound across
   page commits.
2. Each page commits its body-free receipts, checkpoint, and next page token.
3. A retry resumes from the persisted page token. The account's committed History
   cursor is not promoted from an intermediate page.
4. Only the final page has `next_page_token=null`; final-page evidence must be
   durable before the cursor compare-and-set can advance.

If Gmail reports an expired History cursor, the account is blocked as
`history_cursor_expired`. After verifying the Workspace profile identity, the
current profile History ID is stored as the reseed target. An authenticated admin
may then request one bounded backfill through:

```text
POST /api/v1/admin/integrations/gmail-task-intake/backfill
```

The request must name the exact blocked account, a nonblank reason, timezone-aware
window bounds, and a window no longer than seven days. Only one active request is
allowed. Promotion is refused unless the backfill run, account, expired cursor,
reseed ID, terminal History ID, and final checkpoint agree and the final page has
no next token. Successful promotion moves the committed cursor to the reseed ID
and clears the reseed/block state.

A provider-deleted message uses a different recovery path. The worker stores one
body-free pending incident and blocks the exact run without skipping the message.
Read its protected detail route, independently verify the exact Gmail message now
returns provider `404`, then submit all returned identity/version fields plus a
reason to the acknowledgement route:

```text
GET  /api/v1/agent-control/gmail/missing-message/incidents/{incident_id}
POST /api/v1/agent-control/gmail/missing-message/acknowledge
```

Never acknowledge from a database row alone. Acknowledgement is authorized only
after provider confirmation and resumes the same durable run/page rather than
fabricating message content or advancing the cursor.

## Telegram uncertain-delivery reconciliation

Every initial, retry, and reminder attempt commits `sending` before Telegram I/O.
A timeout, crash, malformed success response, or unknown response becomes
`delivery_uncertain` and is never retried automatically.

For an uncertain attempt:

1. Check the exact configured private chat for the matching rendered question.
2. If it is visible, reconcile `delivered` with the observed chat and message IDs.
3. If it is definitely absent, reconcile `not_delivered` with no observed IDs.
4. Only after `not_delivered` may an authenticated admin create one explicit
   retry with a nonblank reason.

The protected routes are:

```text
POST /api/v1/admin/integrations/gmail-task-intake/clarifications/{attempt_id}/reconcile
POST /api/v1/admin/integrations/gmail-task-intake/clarifications/{attempt_id}/retry
```

Reconciliation and retry are version/state-bound and audited. Neither action
extends the original 48-hour clarification deadline. At most one reminder is due
24 hours after known delivery.

## Live Atlas registry evidence

The live production gate remains the Railway SSH procedure in
`docs/deployment/hermes-railway.md`. Source inspection, a local registry test, or
the backend `/actions` response is not a substitute. The verified deployed
registry after durable-context promotion contains exactly 25 ordered unique
tools: the original 16, six CRM review tools, and three read-only Sydney/Command
tools. `gmail_send` requires a caller UUID. Confirmed suggestion
approval/dismissal, confirmed task creation, archive, and restore remain absent.

## Task 9 controlled production evidence

Brandon explicitly approved the controlled production E2Es on 2026-08-24. No
client conversation was used.

### Controlled received Gmail

- fixture `982c69dd-b76b-4545-b0b8-1f30b255401c` produced Gmail message/thread
  `1a034d7ddfca2791` and receipt `eb82b845-c616-421f-b5d1-dba955e99b4f`;
- the receipt is `received`, `processed`, and exists once;
- suggestion `f9a333f6-0b3e-4e05-bb96-f8494adfd282` has one Gmail source,
  final payload hash
  `80309124002cb9752b75845b82b73c246489250da914a02a5289caba2ea207cc`,
  and Command edit/approve audits `215`/`216`;
- the ordinary Command approval stage was issued at
  `2026-08-24T18:05:00.294170Z` and consumed at
  `2026-08-24T18:06:18.050819Z`;
- it applied exactly once as Task `454`, with one creation request and one task
  source. Input replay left all three counts at one.

### Controlled Agent Control sent Gmail

- caller request `1100422e-4074-42c0-b7a3-08eb6268e0dd` produced message/thread
  `1a034d7e937e7ac2`; immediate replay returned the same provider IDs without a
  second send;
- origin `42573720-3b0c-4035-87e3-6e39eb25318d` reached `succeeded`; send-intent
  audit `187` records the redacted transition;
- receipt `4db4edae-e040-4d6b-ab25-4611428948f3` is `sent`, `processed`, and
  exists once;
- suggestion `f592e23a-4692-4c24-b9fc-ed2c24a0fea6` has one Gmail source,
  final payload hash
  `fea579ba02be818178b2d6d7fbf12e95d2124a893bd1e419580091dae643736f`,
  and Command edit/approve audits `217`/`218`;
- the ordinary Command approval stage was issued at
  `2026-08-24T18:08:13.903982Z` and consumed at
  `2026-08-24T18:08:23.987464Z`;
- it applied exactly once as Task `455`, with one creation request and one task
  source. Send and approval replay left all counts at one.

### Controlled direct Sydney draft

- caller request `30277959-206a-4929-b1d7-676820d323aa` replayed to the same
  suggestion `7e10f85b-fe97-416d-ac4b-d1386a2c38a9`;
- clarification `420aaf01-6663-4439-8aac-404f8166f799` asked `task_details`
  once; outbox attempt `36ad52c7-9346-4b54-90b1-18673ea3566d` sent Telegram
  message `88` once;
- draft and answer audits are `219` and `220`; the successful final approval-link
  and Command approval audits are `235` and `236`;
- the successful final handoff stage was issued at
  `2026-08-24T19:28:55.997543Z` and consumed at
  `2026-08-24T19:29:28.068269Z`; its separate approval stage was issued at that
  exchange time and consumed at `2026-08-24T19:29:35.457930Z`;
- final payload hash is
  `712501a991739de609fd651243950344b2c64ec9eb2754234a9a931941dcf3b7`;
- it applied exactly once as Task `456`, with one creation request and one task
  source. Draft, enqueue, answer, handoff, approval, and creation replay produced
  no second task.

The final production totals were 456 tasks, 16 suggestions, three creation
requests, three task sources, six Gmail origins, 34 receipts, 47 extraction
attempts, 13 obligations, one clarification, and one Sydney outbox row.

## Remaining blocker

After all controlled fixtures had completed, Gmail History encountered a
different provider-deleted message. Incident
`68d47eba-ecbb-4972-a504-82daa7d0704d` remains `pending` with its durable alert
sent. Account `0cd336f1-d3d8-47a2-8b37-597165d001cd` is blocked on
`message_not_found`; run `dfe63466-27d1-4822-822c-4205efdb1e58` retains the
exact recovery state. The worker is disabled and has no current job.

Do not acknowledge this incident until an authorized operator verifies the exact
provider message returns `404` and submits the protected exact-identity
acknowledgement. This blocker does not invalidate Tasks 454–456, but Gmail intake
must remain disabled until it is resolved and the same-run recovery is verified.
