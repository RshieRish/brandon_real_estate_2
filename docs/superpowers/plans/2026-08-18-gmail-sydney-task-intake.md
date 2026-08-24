# Gmail and Sydney Task Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn received and sent Gmail messages into reviewable CRM task suggestions, let Sydney ask one concise clarification question when required, and require an authenticated Command approval before a task becomes real.

**Architecture:** A dedicated integration worker polls Gmail History under a per-account PostgreSQL advisory lock, writes durable source receipts, and extracts zero or more obligations without retaining raw message bodies. Per-account/thread serialization creates versioned task suggestions and a durable clarification outbox. Sydney delivers one Telegram question at a time through a repo-owned dispatcher; untrusted Hermes answers may update only the draft, while final approval uses a handoff nonce followed by a distinct authenticated-Command approval nonce. All confirmed creation routes use the shared `crm_task_service` from the task-foundation plan.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, PostgreSQL, Alembic, Google Gmail API, Gemini structured output, Telegram Bot API, Next.js/React/TypeScript, Vitest, Testing Library, Playwright, Railway.

---

## File Structure

Create:

- `backend/models/integration_health.py`, `backend/models/gmail_task_intake.py`, `backend/models/sydney_tasks.py`
- `backend/schemas/gmail_task_intake.py`, `backend/schemas/agent_control_crm.py`
- `backend/services/integration_health_service.py`
- `backend/services/integration_advisory_locks.py`
- `backend/services/gmail_history_adapter.py`, `backend/services/gmail_history_service.py`
- `backend/services/gmail_message_sanitizer.py`, `backend/services/gmail_task_extractor.py`
- `backend/services/gmail_obligation_reconciliation.py`, `backend/services/crm_task_suggestion_service.py`
- `backend/services/sydney_clarification_service.py`, `backend/services/sydney_telegram_dispatcher.py`
- `backend/services/task_suggestion_approval_service.py`, `backend/services/gmail_task_intake_health.py`
- `backend/routers/admin_integrations.py`, `backend/routers/command_task_suggestions.py`, `backend/routers/agent_control_crm.py`
- `backend/workers/__init__.py`, `backend/workers/health_app.py`, `backend/workers/integration_worker.py`
- `backend/workers/jobs/gmail_history.py`, `backend/workers/jobs/gmail_receipts.py`, `backend/workers/jobs/sydney_questions.py`, `backend/workers/jobs/integration_alerts.py`
- `backend/Dockerfile.worker`, `backend/railway.integration-worker.json`
- `backend/scripts/check_integration_worker.py`
- `backend/alembic/versions/82b5e3d7f0a1_add_integration_runtime_health.py`
- `backend/alembic/versions/83c6f4e8a1b2_add_gmail_task_intake.py`
- `backend/alembic/versions/84d7a5f9b2c3_add_sydney_task_review.py`
- `hermes/overlay/manifest.json`, `hermes/overlay/apply_overlay.py`, `hermes/overlay/atlas_backend_bootstrap.py`
- `frontend/src/app/admin/command/task-suggestions/page.tsx`
- `frontend/src/components/command/TaskSuggestionsWorkspace.tsx` and its test
- `frontend/src/lib/command/task-suggestions.ts` and its test
- `backend/tests/test_integration_runtime_migration.py`, `backend/tests/test_integration_health_service.py`
- `backend/tests/test_notification_claims.py`, `backend/tests/test_integration_worker.py`, `backend/tests/test_integration_worker_deployment.py`
- `backend/tests/test_gmail_task_intake_migration.py`, `backend/tests/test_gmail_history_adapter.py`
- `backend/tests/test_gmail_history_service.py`, `backend/tests/test_gmail_history_cursor_recovery.py`
- `backend/tests/test_gmail_message_processing.py`, `backend/tests/test_gmail_agent_control_origins.py`
- `backend/tests/test_gmail_task_extractor.py`, `backend/tests/test_crm_task_suggestions.py`
- `backend/tests/test_sydney_task_review_migration.py`, `backend/tests/test_sydney_clarifications.py`
- `backend/tests/test_sydney_telegram_dispatcher.py`, `backend/tests/test_task_suggestion_approval.py`
- `backend/tests/test_gmail_task_intake_admin.py`, `backend/tests/test_agent_control_crm.py`
- `backend/tests/test_gmail_task_router_registration.py`
- `backend/tests/test_agent_control_transactional_audit.py`, `backend/tests/test_hermes_overlay.py`
- `backend/tests/test_gmail_task_intake_e2e.py`
- `backend/tests/gmail_task_postgres.py`, `backend/tests/test_gmail_task_postgres_contract.py`
- `.github/workflows/gmail-sydney-task-intake.yml`

Modify:

- `backend/config.py`, `backend/.env.example`, `backend/main.py`
- `backend/models/__init__.py`, `backend/alembic/env.py`
- `backend/models/notification_job.py`, `backend/services/notification_service.py`
- `backend/services/workspace_service.py`
- `backend/routers/agent_control.py`, `backend/schemas/agent_control.py`
- `backend/tests/test_crm_task_lifecycle_migration.py`
- `.github/workflows/crm-task-lifecycle-migration.yml`
- `hermes/atlas_backend_mcp.py`, `backend/tests/test_atlas_backend_mcp.py`
- `frontend/package.json`, `frontend/package-lock.json`
- `frontend/src/components/command/shell/commandNavigation.ts`
- `frontend/src/components/command/shell/commandNavigation.test.ts`
- `frontend/src/components/command/shell/CommandShell.test.tsx`
- `docs/deployment/hermes-railway.md`, `tdtn.md`, `memory.md`

## Locked Persistence Contract

Migration `82b5e3d7f0a1` owns the shared runtime tables and notification claim columns:

| Model | Table | Required invariant |
|---|---|---|
| `IntegrationHealthState` | `integration_health_states` | One row per provider; sanitized state/error, last check/success, consecutive failures, transition epoch, alert/reminder/recovery timestamps. |
| `IntegrationWorkerHeartbeat` | `integration_worker_heartbeats` | One row per worker ID with boot time, last heartbeat, current job, and last completed job; no provider content. |
| `NotificationJob` changes | `notification_jobs` | Add `provider_key`, `dedupe_key`, `lease_owner`, and `lease_expires_at`; unique non-null `(provider_key, dedupe_key)` and leased `FOR UPDATE SKIP LOCKED` claims. |

Migration `83c6f4e8a1b2` owns the Gmail discovery, evidence, and review tables:

| Model | Table | Required invariant |
|---|---|---|
| `GmailSyncAccount` | `gmail_sync_accounts` | Unique Workspace account; committed cursor, reseed candidate, mode, and blocked reason. The committed cursor is never a page checkpoint. |
| `GmailSyncRun` | `gmail_sync_runs` | One durable poll/backfill run with start cursor, terminal History ID, run kind, state, lease, and bounded sanitized failure. |
| `GmailSyncPageCheckpoint` | `gmail_sync_page_checkpoints` | Unique `(run_id, page_number)`; request/next page token, discovered History range, receipt count, and committed timestamp for restart. |
| `GmailMessageReceipt` | `gmail_message_receipts` | Unique `(account_id, gmail_message_id)`; direction, nonunique indexed thread ID, timestamps, participant HMACs, bounded subject preview, body hash, and processing state; no raw body. Multiple receipts in one thread are expected. |
| `GmailMessageOrigin` | `gmail_message_origins` | The durable pre-send intent and later sent-message origin. Agent/API sends require unique `(account_id, request_id)` with PostgreSQL UUID `request_id`, a canonical send hash excluding request/retry UUIDs, a separately stored canonical envelope/body hash, nullable self-FK `retry_of_origin_id`, positive row version, `origin_kind` of `sydney_client_send` or `system_automation`, and exact delivery state `sending`, `succeeded`, or `delivery_uncertain`. Only `(account_id, gmail_message_id)` is unique when the message ID is non-null; `gmail_thread_id` is deliberately nonunique and indexed. The partial unique unresolved-send index on `(account_id, canonical_send_hash)` uses the exact PostgreSQL predicate `delivery_state IN ('sending', 'delivery_uncertain') AND reconciled_outcome IS DISTINCT FROM 'not_delivered'`; `!=`/`<>` alone is forbidden because a NULL outcome would bypass it. `retry_of_origin_id` is unique when non-null. A nullable operator `reconciled_outcome` is only `delivered` or `not_delivered`; rejected delivered candidates record bounded quarantine evidence and remain uncertain. History-inferred `human_send` rows are created already `succeeded`, have provider IDs, and have no caller request ID. |
| `GmailExtractionAttempt` | `gmail_extraction_attempts` | Unique bounded attempt number per receipt/schema version with state and sanitized error category. |
| `GmailExtractedObligation` | `gmail_extracted_obligations` | Unique `(receipt_id, action_key, schema_version)`; structured fields, obligation fingerprint, confidence, and evaluator result. |
| `CRMTaskSuggestion` | `crm_task_suggestions` | Versioned top-level state exactly `needs_clarification`, `possible_duplicate`, `pending_review`, `approved`, `dismissed`, `applied`, or `failed`; editable Brandon-owned task payload, payload hash, clarification state, bounded blocker-code set, application idempotency key, and applied task ID. `manual_review_required` is a clarification state, not a top-level suggestion state; unsupported ownership/linking use `pending_review` plus blockers. |
| `CRMTaskSuggestionSource` | `crm_task_suggestion_sources` | Unique many-source link `(suggestion_id, obligation_id)` so a reconciled obligation retains every received/sent source. |
| `CRMTaskSuggestionSuppression` | `crm_task_suggestion_suppressions` | Command-authored dismissal ledger with unique `(source_type, source_scope_key, source_action_key, obligation_fingerprint)`. The source/action columns are version-independent; for Gmail the scope includes account UUID plus thread ID. A matching semantic fingerprint in an unrelated thread/source never suppresses. Stores dismissal reason/actor/audit and optional authenticated reprocess override. |
| `GmailBackfillRequest` | `gmail_backfill_requests` | Explicit administrator, reason, bounded start/end, expired cursor, reseed cursor, audit ID, and run/result state. |

Migration `84d7a5f9b2c3` owns clarification and approval state:

| Model | Table | Required invariant |
|---|---|---|
| `CRMTaskClarification` | `crm_task_clarifications` | Suggestion/version-bound opaque code hash, exact consequential field, round number, one unresolved clarification per Telegram chat, one reminder at 24 hours, release at 48 hours, and resolution. Unique `(suggestion_id, suggestion_version, field_name)` prevents a repeated question for the same field/version; one suggestion may have at most five consequential rounds. |
| `SydneyQuestionOutbox` | `sydney_question_outbox` | One immutable-payload attempt per row with `attempt_kind=initial|initial_retry|reminder`, nullable parent initial attempt, deterministic unique dedupe key, exact `pending/sending/sent/failed/delivery_uncertain` state, Telegram chat/message IDs, and attempt timestamps. A reminder is its own row; an uncertain attempt is never retried automatically. |
| `TaskSuggestionApprovalNonce` | `crm_task_suggestion_approval_nonces` | Both kinds use Python `secrets.token_urlsafe(32)` (32 random bytes/256 bits; never below 128 bits) and persist only a unique SHA-256 hash, never plaintext. `kind=handoff` is suggestion/version/payload-bound, administrator-null, parent-null, single-use, and expires after 15 minutes. `kind=approval` is administrator-bound, single-use, and expires after 5 minutes; `issuance_path=handoff_exchange` requires a consumed parent handoff, while `issuance_path=command_prepare` requires a null parent. Preparing, opening, or exchanging never approves. |
| `CRMTaskSuggestionEvent` | `crm_task_suggestion_events` | Immutable state transition/audit reference for edit, clarify, dismiss, preview, approve, apply, and reprocess. |

Every migration test must assert the exact table/constraint inventory, upgrade without dropping existing CRM rows, and `alembic heads` returning one head. Feature/code rollback keeps migrations `82` through `84` in place. A direct downgrade of `83` or `84` must fail closed while any Gmail/Sydney durable, evidence, outbox, nonce, or audit table is nonempty. Destructive downgrade is allowed only through a separate explicit runbook that records an audited export and operator approval, verifies the export, deliberately empties the owned tables, and then runs Alembic. Tests seed pre-existing CRM rows plus intake evidence, prove the refusal preserves both, and separately prove the empty-database downgrade path.

These are the canonical names for implementation. They supersede the design draft's early shorthand `gmail_sync_states`, `gmail_history_runs`, `crm_task_email_sources`, `gmail_obligation_suppressions`, and `sydney_clarification_threads`; implementation must not create compatibility tables or aliases with those names. The only origin values are `sydney_client_send`, `human_send`, and `system_automation`; the earlier `client_facing_agent_send` and `internal_operational_automation` labels are not persisted.

## Isolated PostgreSQL test prerequisite

Use a dedicated disposable PostgreSQL 16 database and export both `GMAIL_TASK_TEST_DATABASE_NAME` and `GMAIL_TASK_TEST_DATABASE_URL`. The shared helper `backend/tests/gmail_task_postgres.py` must parse the URL with SQLAlchemy and enforce all of the following before any migration or concurrency test opens a connection:

```python
def fail_closed(message: str):
    if os.getenv("CI", "").strip().lower() == "true":
        pytest.fail(message)
    raise RuntimeError(message)

if not raw_url or not expected_database:
    if os.getenv("CI", "").strip().lower() == "true":
        pytest.fail(
            "CI requires GMAIL_TASK_TEST_DATABASE_NAME and "
            "GMAIL_TASK_TEST_DATABASE_URL"
        )
    pytest.skip("GMAIL_TASK_TEST_DATABASE_URL is not provisioned")
url = make_url(raw_url)
if not expected_database.endswith("_test"):
    fail_closed("GMAIL_TASK_TEST_DATABASE_NAME must end in _test")
if url.database != expected_database:
    fail_closed("GMAIL_TASK_TEST_DATABASE_URL must target the exact configured database")
if not (url.database or "").endswith("_test"):
    fail_closed("GMAIL_TASK_TEST_DATABASE_URL must target a _test database")
if not url.drivername.startswith("postgresql"):
    fail_closed("Gmail/Sydney persistence tests require PostgreSQL")
```

No destructive guard uses Python `assert`, because `python -O` removes assertions. The helper claims only an initially empty database by creating `_gmail_sydney_test_ownership` with one cryptographically random run marker. Before any cleanup, downgrade, schema drop, or reuse it queries the marker table and requires the exact tuple `(total_rows, matching_run_rows) == (1, 1)` through `fail_closed`; missing, extra, or foreign ownership leaves every table untouched. `backend/tests/test_gmail_task_postgres_contract.py` launches the helper under `python -O` against wrong-name, wrong-driver, populated-schema, missing-marker, duplicate-marker, and foreign-marker fixtures, requires nonzero failure, and then proves a sentinel row/table remains. Tests upgrade the full real chain through `81a4d2c6e9f0`, then `82b5e3d7f0a1`, `83c6f4e8a1b2`, and `84d7a5f9b2c3`; they never point at a shared development, staging, or production database. Every advisory-lock, lease, cursor, migration, and end-to-end test uses at least two independent real PostgreSQL connections where concurrency matters. SQLite and parse-only DDL tests do not satisfy this gate.

Create `.github/workflows/gmail-sydney-task-intake.yml` with a disposable TLS-enabled `postgres:16-alpine` container named `gmail-sydney-postgres`, database `brandon_gmail_sydney_ci_test`, matching `GMAIL_TASK_TEST_DATABASE_NAME`/URL, `CI=true`, and an always-run cleanup of that exact container and certificate files. Its pull-request and `main` push filters include every backend path in this plan plus `hermes/**`, `docs/deployment/hermes-railway.md`, `backend/tests/test_atlas_backend_mcp.py`, `backend/tests/test_hermes_overlay.py`, `frontend/package.json`, `frontend/package-lock.json`, and the exact Task 7 page, library, workspace, navigation, and test paths listed below. The backend set includes `.github/workflows/gmail-sydney-task-intake.yml`, `backend/.env.example`, `backend/main.py`, worker Docker/Railway/probe files, `backend/alembic/**`, config/database/models, the three new routers and schemas, agent-control/audit/CRM/Gmail/integration/notification/Sydney/approval/workspace services, `backend/workers/**`, every named Gmail/Sydney/integration/approval/Agent Control/router-registration test, the PostgreSQL helper/contract test, and `backend/requirements.txt`.

A repository contract test reads the workflow and asserts these triggers, the TLS check, exact `_test` name, cleanup, and incrementally valid jobs. Task 1 starts with only its six persistence/runtime tests. Tasks 2 through 6 extend the explicit PostgreSQL pytest list as their files land. Task 7 adds a Node job running the exact four Vitest files `src/lib/command/task-suggestions.test.ts`, `src/components/command/TaskSuggestionsWorkspace.test.tsx`, `src/components/command/shell/commandNavigation.test.ts`, and `src/components/command/shell/CommandShell.test.tsx`, then `npm run typecheck` and scoped ESLint over only the eight touched Task 7 TypeScript/TSX files. Task 8 must expand CI with `tests/test_atlas_backend_mcp.py`, `tests/test_agent_control_crm.py`, and `tests/test_hermes_overlay.py`, plus an exact 22-tool registry assertion. Task 9 pins the full PostgreSQL/E2E list. No intermediate commit references a test or job before its file lands.

The existing `.github/workflows/crm-task-lifecycle-migration.yml` also triggers on `backend/alembic/**`. Before adding migration `82`, update `backend/tests/test_crm_task_lifecycle_migration.py` test-first: keep `81a4d2c6e9f0`'s own metadata/DDL/upgrade/downgrade assertions exact, but replace the assumption that revision `81` is forever the repository head with a single-head assertion plus proof that `81` is the revision under test and an ancestor of that head. Its real-database `alembic heads` assertion compares against `ScriptDirectory.get_current_head()`, not the literal `81`. Add a repository test that fails with a parallel head. Keep that existing workflow green at each serial migration commit: sole head `82b5e3d7f0a1` in Task 1, `83c6f4e8a1b2` in Task 2, and `84d7a5f9b2c3` in Task 5.

## Locked advisory serialization

Use advisory-key contract version `v1` and exact domain-separated bytes, never Python's randomized `hash()`. `GmailSyncAccount.id` is PostgreSQL UUID. Account material is `b"sws:gmail-task-intake:advisory:v1:account\x00" + account_id.bytes`. Thread material is `b"sws:gmail-task-intake:advisory:v1:thread\x00" + account_id.bytes + len(thread_bytes).to_bytes(2, "big") + thread_bytes`, where the validated Gmail thread ID is encoded as exact ASCII bytes. Hash with SHA-256, take the first eight bytes big-endian unsigned, then convert to PostgreSQL signed bigint by subtracting `2**64` when the high bit is set. Fixed vectors for account `00000000-0000-0000-0000-000000000001` are `848794804012879307` for the account key and `-7678506188538908948` for thread `thread-123`.

Gmail History discovery acquires a session-level `pg_try_advisory_lock(account_key(account_id))` on a dedicated PostgreSQL connection before reading the committed cursor and holds it through all provider pages and the final cursor compare-and-set; failure to acquire skips that account without blocking. It releases the lock in `finally` on the same connection.

Receipt extraction may run concurrently across threads, but every reconciliation transaction first takes `pg_advisory_xact_lock(thread_key(account_id, gmail_thread_id))` before reading or writing obligations, suggestions, suppressions, or source links. All receipts for one account/thread therefore serialize, while different threads remain parallel. Two-session PostgreSQL tests must prove same-account History exclusion, same-thread suggestion serialization, and non-blocking progress for distinct threads.

All rolling instances use `v1`; a future key-version change requires a separate rollout that acquires old and new keys in sorted numeric order until every old worker is drained. Unit tests pin both vectors, domain separation, UUID byte order, ASCII/length framing, signed conversion, and unchanged results under `PYTHONHASHSEED` variation.

## Locked provider-call and worker supervision contract

The Google Workspace, Gmail, Gemini, and current Telegram client calls are synchronous. Every such call runs in a dedicated bounded provider executor, never on the scheduler/ASGI event loop, with both a provider socket/request timeout and an outer `asyncio.wait_for` job deadline. A timed-out future is recorded and tracked until it exits; the scheduler does not start another job with the same account/thread/outbox key while that future remains alive. Executor saturation degrades the protected provider status but cannot block `/health`. Tests stall each sync adapter beyond its deadline and prove the job fails with a bounded category while `/health` responds on the event loop within its latency budget.

The worker creates exactly two long-lived peers—the scheduler and the internal ASGI server—and supervises them with `asyncio.wait(..., return_when=asyncio.FIRST_COMPLETED)`, not a `TaskGroup` assumed to run forever. On any peer error or normal return, set `server.should_exit`, cancel and await the other peer with `return_exceptions=True`, then re-raise the error or raise `RuntimeError` for unexpected normal return so Railway restarts the process. Tests cover both peers returning normally and raising and prove no orphan task remains.

The scheduler alone creates the worker boot/heartbeat row after job-registry validation and updates its periodic heartbeat. `/ready` performs read-only checks: `SELECT 1`, read/compare the single Alembic version, read the scheduler-owned boot/heartbeat, and inspect already-initialized in-memory registry state. It never inserts, updates, flushes, or refreshes the heartbeat. A SQL-capture test rejects DML from `/ready`; a stalled provider test proves both probes remain responsive.

## Locked Gmail Cursor and Origin Protocol

The committed Gmail cursor changes only after the terminal History page. Page commits make discovery restart-safe but are not cursor commits:

```python
run = await start_or_resume_run(account.committed_history_id)
while True:
    page = await gmail.history_list(run.start_history_id, run.next_page_token)
    async with db.begin():
        await insert_receipts_idempotently(page.message_ids)
        await save_page_checkpoint(run.id, page)
    if page.next_page_token:
        run.next_page_token = page.next_page_token
        continue
    async with db.begin():
        await mark_run_discovered(run, terminal_history_id=page.history_id)
        await compare_and_set_committed_cursor(
            account_id=account.id,
            expected=run.start_history_id,
            value=page.history_id,
        )
    break
```

On `history_cursor_expired`, stop discovery and keep the old committed cursor unchanged. Fetch the current profile History ID only into `reseed_history_id`, set the account/run to `blocked_expired_cursor`, and enqueue one deduplicated administrator alert. Resumption requires `POST /api/v1/admin/integrations/gmail-task-intake/backfill` with an authenticated administrator, reason, and explicit maximum-seven-day window. That request creates `GmailBackfillRequest`, runs the bounded recovery, records its audit, then promotes the reseed cursor only after the backfill run reaches its final page. There is no automatic unbounded mailbox scan.

Every Agent Control Gmail send requires `request_id: UUID` and optional `retry_of_request_id: UUID` in `WorkspaceGmailSendRequest`; `confirmed_by_brandon` remains required but is not an idempotency key. Before any Gmail API call, the route canonicalizes account, intended thread, From/To/Cc/Bcc, subject, and body into a send hash that excludes both UUIDs. In one transaction it claims the unresolved partial-unique hash gate, writes and commits a `GmailMessageOrigin` keyed by `(account_id, request_id)` with `delivery_state="sending"`, and writes the send-intent `AgentActionAudit`. Audit/claim failure means no provider call.

```python
async with db.begin():
    intent = await claim_send_intent(
        account_id=account.id,
        request_id=payload.request_id,
        request_hash=canonical_send_hash(payload),
        origin_kind="sydney_client_send",
        delivery_state="sending",
    )
    await write_transactional_agent_audit(db, intent)

provider_result = await send_gmail_message(..., num_retries=0)

async with db.begin():
    origin = await mark_send_succeeded(
        intent_id=intent.id,
        message_id=provider_result.message_id,
        thread_id=provider_result.thread_id,
    )
    await enqueue_receipt_from_origin(origin)
```

The send transport performs no automatic retry. Any non-success after the durable intent commits—including explicit provider rejection, timeout, worker crash, unknown response, or failure to persist returned IDs—leaves or transitions the intent to `delivery_uncertain` with a sanitized category; stale `sending` is treated as uncertain by reconciliation. Neither state may call Gmail again automatically. An exact replay with the same UUID and payload returns the stored result only when state is `succeeded`; a mismatched hash returns `409 gmail_send_idempotency_mismatch`.

A fresh UUID is not a bypass. While an older intent for the same account/canonical send hash is `sending` or `delivery_uncertain` without authenticated `not_delivered`, any second UUID fails before Gmail with `409 gmail_send_reconciliation_required`, even if it omits or falsely supplies `retry_of_request_id`. After an administrator records `not_delivered`, exactly one deliberate successor may be claimed only when its new request carries `retry_of_request_id=old.request_id`; the service verifies same account/hash, parent outcome/version, and no existing successor, then stores the unique self-FK. A missing, unrelated, delivered, unresolved, hash-mismatched, or already-used parent fails closed. The old row remains immutable evidence. Two independent PostgreSQL-request tests prove a fresh UUID cannot send while the first is unresolved and that only the correctly bound successor is accepted after `not_delivered`; a barrier race proves at most one successor reaches the provider. Local validation failures before durable intent commit make no provider call.

For `outcome=delivered`, operator-supplied provider IDs are candidates, never proof. With zero send retries, reconciliation uses the configured account to transiently fetch Gmail profile and message under the provider deadline, then verifies the profile/account identity, exact message ID, `SENT` label, returned thread ID against both the candidate and any thread bound by the intent, and canonical From/To/Cc/Bcc/subject/body bytes against the stored envelope/body hash. Only a full match may transition the origin to `succeeded` and enqueue an eligible receipt. A wrong account, missing/wrong message, wrong thread, missing `SENT`, or envelope/body mismatch writes a bounded immutable quarantine audit, leaves the origin `delivery_uncertain`, and creates no eligible receipt. It remains quarantined until independent Gmail History discovery observes and verifies the send; reconciliation tests cover each mismatch and prove arbitrary IDs cannot manufacture a sent obligation.

The later Gmail History observation upserts the same `(account_id, gmail_message_id)` receipt and attaches the existing succeeded origin instead of creating another suggestion. A sent message first seen in History without an app origin creates a `human_send` origin already in `succeeded`. `sydney_client_send` remains eligible as an outgoing commitment; `system_automation`, drafts, spam, trash, and internal loop notifications are ineligible by durable origin/label metadata rather than subject heuristics.

## Locked clarification, authority, and approval policy

Clarification delivery is globally one-at-a-time for the configured Brandon chat. A partial unique constraint covers every unresolved row that still owns the chat slot; a later suggestion cannot enqueue while that row is active. Each delivery is a separate outbox row whose identity/payload/dedupe key never changes: `clarification:{id}:v{version}:initial:1`, an explicit operator-created `initial_retry:{n}`, or the sole `reminder:1`. The dispatcher commits that row as `sending` before `sendMessage`, then records `sent`, `failed`, or `delivery_uncertain`; uncertain is never auto-retried. A known delivered initial/retry may create exactly one reminder row due at `sent_at + 24 hours` only if it precedes the fixed slot deadline. The reminder follows the same pre-call `sending` protocol and is never retried or replaced, whether sent, failed, or uncertain.

The 48-hour slot deadline never moves: known initial success uses its `sent_at + 48 hours`; failed or uncertain initial delivery uses `first_attempt_at + 48 hours`; an initial still pending uses `created_at + 48 hours`. An operator retry and reminder cannot extend it. At the deadline, atomically mark an unanswered clarification `timed_out`, release the chat slot, keep the suggestion visible as `needs_clarification`, and require Command review. Thus failed initial/retry/reminder attempts cannot hold the slot indefinitely.

The evaluator selects one highest-consequence unresolved field. It may ask at most five rounds per suggestion and may never persist the same `(suggestion_id, suggestion_version, field_name)` twice. Each accepted answer closes the current clarification, increments the suggestion version, reruns the evaluator, and only then may enqueue the next field. Any independent edit, reprocess, or material source update that changes the suggestion version first marks the active clarification `superseded` and releases its chat slot in the same transaction. If five rounds are exhausted with consequential ambiguity remaining, set `clarification_state=manual_review_required`; do not enqueue a sixth question. An answer to a timed-out/resolved/superseded row, a stale suggestion version, a replaced field, or an old opaque code returns `409 stale_clarification` and changes neither the suggestion nor the chat slot.

Hermes is not a trusted identity or transport-attestation boundary. The initial `crm.task_clarifications.answer` arguments contain only the opaque code, expected suggestion version, and bounded structured answer; they contain no accepted `chat_id`, `user_id`, `suggestion_id`, owner, or approval assertion. The backend verifies that the hashed code belongs to the one active clarification whose successful outbound row records the configured Brandon chat, but this is correlation, not proof of who typed the answer. Audit it as `untrusted_hermes_input` and allow it to edit only the review draft. Final task creation still requires authenticated Command approval. `SYDNEY_TELEGRAM_BRANDON_USER_ID` is reserved for a future signed inbound adapter and must not be treated as verified when repeated by a model or MCP argument.

Approval always has a prepare stage and a distinct apply click. `crm.task_suggestions.approval_link` issues a 15-minute `handoff` bound to suggestion/version/payload hash but not an administrator. Its URL is exactly `/admin/command/task-suggestions?suggestion={id}#handoff={opaque}`: the secret is only in the fragment, never a query parameter. A no-store/no-referrer bootstrap synchronously reads and clears the fragment with `history.replaceState` before hydration, telemetry, analytics, `fetch`, `sendBeacon`, or any other referrer-capable application network call; it retains the token only in ephemeral memory, never DOM, logs, local/session storage, or persisted state. If the user is not already authenticated, it clears the fragment and requires sign-in followed by reopening the still-unused link.

Authenticated handoff exchange consumes that nonce and issues a 5-minute administrator-bound `approval` nonce with `issuance_path=handoff_exchange` and the handoff parent. Ordinary authenticated Command review does not invent a handoff: `POST /api/v1/command/task-suggestions/{id}/approval/prepare` revalidates expected version/hash, returns the exact preview, and issues a 5-minute administrator-bound `approval` nonce with `issuance_path=command_prepare` and no parent. Neither path creates a task. Both keep the approval nonce only in memory and require a later explicit Approve click; only that request may consume it in the same transaction as task creation and audit.

Both nonce issuers call `secrets.token_urlsafe(32)` directly. Before hashing or database lookup, consumers require canonical ASCII base64url encoding that decodes to exactly 32 bytes; malformed alphabet/padding, noncanonical encoding, or shorter input fails with the same bounded invalid-nonce response and performs no lookup. Persist `hashlib.sha256(token.encode("ascii")).digest()` under a unique constraint. Tests spy on the generator to require `nbytes=32`, decode fixture output to 32 bytes, prove no plaintext storage, reject malformed/short values before repository access, and force a repeated generator value to exercise hash uniqueness/bounded regeneration or fail-closed behavior. They do not claim statistical randomness from a sample.

The initial task shape is exactly the already-shipped `CreateTaskCommand`: Brandon is the implicit and only owner; the mutable payload is title, description, priority, due time, optional uniquely resolved `contact_id`, and `status=open`. There is no owner field and creation does not atomically add opportunity/listing/agreement links. A clear request assigned to someone other than Brandon stays in `pending_review` with blocker `unsupported_owner`; an ambiguous owner may ask once whether this should be Brandon's follow-up, but a non-Brandon answer returns it to that blocker. A requested non-contact task link stays in `pending_review` with blocker `unsupported_link`, not a fabricated link or repeated clarification. Command may resolve either blocker only by an explicit versioned, audited choice to make it Brandon-owned and/or create without the unsupported link, or may dismiss it; approval stays disabled while either blocker is unresolved.

## Task 1: Add shared integration health and safe job claims

**Files:** Create `backend/alembic/versions/82b5e3d7f0a1_add_integration_runtime_health.py`, `backend/models/integration_health.py`, `backend/services/integration_health_service.py`, `backend/services/integration_advisory_locks.py`, `backend/workers/health_app.py`, `backend/workers/integration_worker.py`, `backend/Dockerfile.worker`, `backend/railway.integration-worker.json`, `backend/scripts/check_integration_worker.py`, `backend/tests/gmail_task_postgres.py`, `backend/tests/test_gmail_task_postgres_contract.py`, `backend/tests/test_integration_runtime_migration.py`, `backend/tests/test_integration_health_service.py`, `backend/tests/test_notification_claims.py`, `backend/tests/test_integration_worker.py`, `backend/tests/test_integration_worker_deployment.py`, and `.github/workflows/gmail-sydney-task-intake.yml`; modify `backend/models/notification_job.py`, `backend/services/notification_service.py`, `backend/config.py`, `backend/models/__init__.py`, `backend/alembic/env.py`, `backend/tests/test_crm_task_lifecycle_migration.py`, and `.github/workflows/crm-task-lifecycle-migration.yml`.

**Actual file note (completed 2026-08-20):** The plan-wide file list overpredicted changes to `.github/workflows/crm-task-lifecycle-migration.yml` and `backend/.env.example`. Both remained unchanged: the existing CRM lifecycle workflow already triggers on `backend/alembic/**` and runs the generalized revision-81 ancestor contract, while Task 1 added no environment variables that required an example-file edit. No redundant or no-op change was made.

- [x] **Step 1: Generalize the existing revision-81 head test before adding revision 82.** Preserve every exact revision-81 metadata/DDL/round-trip assertion; assert one repository head, assert revision 81 is in that head's ancestor chain, and make the real `alembic heads` expectation use the discovered repository head. Run the existing CRM lifecycle workflow suite at current head 81 and require it to pass.
- [x] **Step 2: Write failing tests** in the six new test files above. Assert the next sole head is 82 with revision 81 as its direct ancestor, atomic `FOR UPDATE SKIP LOCKED` claims, stale-lease recovery, deterministic dedupe keys, and no integration loops in the FastAPI web process. Pin separate worker probes:

```python
assert client.get("/health").json() == {
    "status": "ok",
    "service": "integration-worker",
}
ready = client.get("/ready")
assert ready.status_code == 200
assert ready.json() == {
    "status": "ready",
    "service": "integration-worker",
    "database": "ok",
    "migration": "ok",
    "heartbeat": "ok",
    "job_registry": "ok",
}
```

`/health` is liveness only and must return that exact two-field body without touching PostgreSQL, Alembic, provider APIs, or job configuration. `/ready` returns the exact success body above only after its read-only checks find PostgreSQL reachable, the single expected Alembic head, a fresh scheduler-owned boot/heartbeat, and an already-initialized valid non-secret job registry. It never writes or refreshes heartbeat state. Failure returns 503 with only `status="not_ready"`, `service="integration-worker"`, and bounded failing component names; it includes no exception/provider/account text. Provider OAuth health remains in the protected integration status route so Railway does not restart a healthy worker merely because Google revoked access.
- [x] **Step 3: Run the red suite:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_gmail_task_postgres_contract.py tests/test_integration_runtime_migration.py \
  tests/test_integration_health_service.py \
  tests/test_notification_claims.py tests/test_integration_worker.py \
  tests/test_integration_worker_deployment.py
```

Expected: imports and worker deployment files are missing.

- [x] **Step 4: Implement** shared health rows, leased notification claims, bounded provider executors/deadlines, and the job registry. The scheduler owns boot/heartbeat writes; `/ready` is read-only. Keep detailed heartbeat/lag/error fields on authenticated admin status; public `/health` and `/ready` expose only the bounded probe contract above. Add stalled-sync-provider and SQL-capture tests proving probe responsiveness and no readiness DML.
- [x] **Step 5: Add deployment configuration** with the single start command `python -m workers.integration_worker` and the locked `FIRST_COMPLETED` supervisor contract above: any normal peer return or error cancels/awaits the other peer and raises. Set Railway's only container health path to `/health`; `backend/Dockerfile.worker` has no Docker `HEALTHCHECK` and installs/uses no `curl` or `wget`. The repo-owned `backend/scripts/check_integration_worker.py` uses Python's standard-library HTTP/JSON clients for the post-deploy `/ready` promotion gate. Tests reject `curl`, `wget`, a Dockerfile `HEALTHCHECK`, use of `/ready` as the Railway restart path, inheritance of `uvicorn main:app --workers 2`, scheduling from the web app lifespan, or a false run-forever `TaskGroup` contract.
- [x] **Step 6: Re-run the new suite and the existing CRM lifecycle workflow suite**, then `alembic heads`; expected sole head `82b5e3d7f0a1`, with `81a4d2c6e9f0` still verified as its ancestor/revision under test. Run the new CI contract test and inspect both workflows to confirm the exact `_test` database equality guard, TLS PostgreSQL job, scoped paths, six current tests, and cleanup.
- [x] **Step 7: Commit:** `feat: add integration worker runtime` (`4ffed4c`).

## Task 2: Persist Gmail cursors, receipts, obligations, and suggestions

**Files:** Create `backend/alembic/versions/83c6f4e8a1b2_add_gmail_task_intake.py`, `backend/models/gmail_task_intake.py`, `backend/schemas/gmail_task_intake.py`, and `backend/tests/test_gmail_task_intake_migration.py`; register every model in `backend/models/__init__.py` and `backend/alembic/env.py`.

**Actual file scope (completed 2026-08-21):** Exactly nine files changed: `.github/workflows/gmail-sydney-task-intake.yml`, `backend/alembic/env.py`, `backend/alembic/versions/83c6f4e8a1b2_add_gmail_task_intake.py`, `backend/models/__init__.py`, `backend/models/gmail_task_intake.py`, `backend/schemas/gmail_task_intake.py`, `backend/tests/test_gmail_task_intake_migration.py`, `backend/tests/test_integration_runtime_migration.py`, and `backend/tests/test_integration_worker_deployment.py`. The two existing integration-runtime tests were updated only to preserve their revision-82 direct-parent contract while accepting the later sole repository head; the dedicated workflow was expanded only through Task 2.

**Completion evidence:** Implementation commit `1a691157` (`feat: persist Gmail task intake`). PostgreSQL 16/TLS Task 2 passed `29/29`; the exact Task 1+Task 2 workflow command passed `95/95`; the real PostgreSQL CRM lifecycle migration suite passed `13/13`; Ruff, Python compilation, cached diff, and diff checks passed; Alembic reported sole head `83c6f4e8a1b2`. Independent reviews returned **SPEC PASS** and **QUALITY APPROVED**; quality independently reran `29/29` and left zero public relations. The exact disposable database was verified empty, its PostgreSQL cluster was stopped, port `55434` closed, and the validated cluster directory was moved recoverably out of `/tmp`. This is persistence only: `GMAIL_TASK_INTAKE_ENABLED=false`, `SYDNEY_TASK_QUESTIONS_ENABLED=false`, and `INSTAGRAM_INTEGRATION_ENABLED=false`; no Task 3 adapter/routes, deployment, production migration, provider call, or live enablement occurred.

**Final integrity decisions:** Workspace email identities must be lowercase, trimmed, and nonblank. Gmail suggestions and their source rows are bound to the same account/thread and to receipt direction through composite keys; suppression and suggestion source vocabularies are exactly `gmail_message|sydney_chat`; direct Sydney drafts use a globally unique request UUID without fabricated Gmail identity; linked backfill runs must belong to the same account. PostgreSQL keeps exact NULL-safe unresolved-send uniqueness and a nonunique Gmail reconciliation lookup index. ORM UUID/array metadata remains SQLite-safe, while downgrade locks all eleven tables before refusing any nonempty evidence.

- [x] **Step 1: Write model tests** for all eleven migration-`83` models in the locked table above: account, sync run, page checkpoint, receipt, origin, extraction attempt, obligation, suggestion, many-source link, suppression, and backfill request. Require the named uniqueness constraints, suggestion `version`, exact top-level lifecycle states, separate clarification state, bounded blocker codes, bounded redacted errors, and the structural absence of raw body/token columns. Pin `gmail_message_origins.request_id` as PostgreSQL UUID, unique `(account_id, request_id)`, partial uniqueness only for non-null `(account_id, gmail_message_id)`, nonunique indexes on origin/receipt thread IDs, canonical send plus envelope/body hashes, nullable unique `retry_of_origin_id`, and the unresolved canonical-hash index's exact compiled PostgreSQL predicate `delivery_state IN ('sending', 'delivery_uncertain') AND reconciled_outcome IS DISTINCT FROM 'not_delivered'` (never bare `!=`/`<>`). Also pin positive row version, exact `sending/succeeded/delivery_uncertain`, nullable provider IDs only before success, and the exact three origin values. Pin the four-column suppression uniqueness and prove the same fingerprint in two unrelated source scopes is allowed. Seed existing CRM plus intake evidence and prove downgrade refuses without losing either; test empty-database downgrade separately.
- [x] **Step 2: Run:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q tests/test_gmail_task_intake_migration.py
```

Expected: missing model imports.

- [x] **Step 3: Implement the exact schema** with `down_revision = "82b5e3d7f0a1"`. Use `CheckConstraint`s for states/directions/run kinds, a partial unique active-run constraint per account, the origin constraints above, and indexes for pending receipts, blocked accounts, suggestion review state, and source lookup. Use only the canonical table and enum names locked above. Do not add a raw-body column.
- [x] **Step 4: Register the models**, add `tests/test_gmail_task_intake_migration.py` to the dedicated workflow command, run the test, and confirm `alembic heads` is only `83c6f4e8a1b2`.
- [x] **Step 5: Commit:** `feat: persist Gmail task intake` (`1a691157`).

## Task 3: Build the typed Gmail History adapter and receipt pipeline

**Files:** Create `backend/services/gmail_history_adapter.py`, `backend/services/gmail_history_service.py`, `backend/services/gmail_message_sanitizer.py`, `backend/tests/test_gmail_history_adapter.py`, `backend/tests/test_gmail_history_service.py`, `backend/tests/test_gmail_history_cursor_recovery.py`, `backend/tests/test_gmail_message_processing.py`, and `backend/tests/test_gmail_agent_control_origins.py`; modify `backend/services/workspace_service.py` only for reusable credential/client primitives and zero-retry transport, plus `backend/schemas/agent_control.py`, `backend/routers/agent_control.py`, and `backend/services/agent_control_audit.py` for required send UUID, durable intent claiming, and fail-closed transactional send-intent audit.

**Actual file scope (completed 2026-08-21):** The implementation commit changed 36 files. It added the five Gmail services, five core Task 3 suites, and the Gmail worker job package; updated the dedicated workflow, environment/config contract, revision `83`, Gmail models/schemas, Workspace and Agent Control routes/services/tests, worker runtime/tests, and Hermes MCP compatibility. Revision `83` now owns a twelfth body-free `gmail_missing_message_incidents` table because safe delete-between-list-and-fetch recovery could not be represented by the original eleven-table persistence contract.

**Completion evidence:** Implementation commit `a864955` (`feat: ingest Gmail history safely`). The fail-closed PostgreSQL 16/TLS RED run collected 297 tests and produced 233 intended missing-production failures with no fixture errors. Final focused History/origin verification passed `154/154`; the last identity, atomic-quarantine, and receipt-lock barrier slice passed `9/9`. The exact 17-file Task 1-through-Task 3 workflow command passed `567/567` with 19 warnings in both implementation and independent review runs. Ruff, compileall/py_compile, `git diff --check`, and the sole Alembic-head contract passed. Independent reviews returned **SPEC PASS** and **QUALITY APPROVED** with zero remaining Critical or Important findings.

**Final safety decisions:** Gmail uses one retained direct `NullPool` PostgreSQL session per account, proves backend/session affinity around advisory-lock commits, persists every receipt/checkpoint before final cursor CAS, resumes retryable pages and bounded backfills, and durably blocks plus alerts on fatal evidence. Metadata/content 404s create body-free, versioned incidents with authenticated detail and acknowledgement recovery. Provider calls are executor-offloaded, deadline/socket bounded, and truly single-attempt through both Google and HTTP layers. Raw bodies and participant data never cross the transient sanitizer boundary. Durable send intents, exact UUID replay, canonical unresolved-send uniqueness, provider/History identity quarantine, immutable message/thread identity, and origin-to-receipt lock order prevent duplicates and stale lifecycle overwrite. Workspace OAuth binding is DB-authoritative and generation-checked under the same transaction lock. The worker composes the direct History engine, origin observer, durable alert queue, current-time heartbeat, and cancellation-safe cleanup.

- [x] **Step 1: Write adapter contract tests** for profile, paginated history, message metadata/content, and classified failures: `oauth_revoked`, `history_cursor_expired`, `rate_limited`, `transient_provider`, `malformed_provider`. Prove the synchronous Google client runs only in the bounded executor with socket plus outer job deadlines and that a stalled call does not block worker health.
- [x] **Step 2: Write ingestion tests** proving the stable session advisory lock serializes one account on two independent PostgreSQL connections, each page checkpoint/receipt batch commits while `GmailSyncAccount.committed_history_id` stays unchanged, a crash resumes from the saved next-page token, and only the final page transaction advances the committed cursor. Cover received, sent, self-copy, draft, spam, and automation labels; replay; compare-and-set cursor races; and secret/body-free exceptions/logs. Prove a different account is not blocked.
- [x] **Step 3: Write cursor-expiry tests** in `backend/tests/test_gmail_history_cursor_recovery.py`: a 404/expired cursor blocks the account, leaves the old committed cursor intact, records only a current reseed candidate, alerts once, rejects automatic/unbounded repair, and promotes the reseed cursor only after an authenticated, reasoned, maximum-seven-day `GmailBackfillRequest` finishes its final page.
- [x] **Step 4: Write sent-origin tests** in `backend/tests/test_gmail_agent_control_origins.py`: `WorkspaceGmailSendRequest.request_id` is required UUID and `retry_of_request_id` is optional UUID; a valid request commits the `sending` intent, canonical hashes, and same-transaction audit before the mocked provider; audit failure makes zero provider calls. Pin exact replay, mismatched payload, known success, later History dedupe, History-inferred `human_send`, automation suppression, `num_retries=0`, timeout/crash/post-provider-persistence uncertainty, stale-`sending` reconciliation, and zero automatic provider recalls from unresolved states. With two independent PostgreSQL sessions released by one barrier, simultaneously insert first intents with different request UUIDs but the same account/hash and NULL `reconciled_outcome`; the exact partial index must allow one commit and one provider call only. Then prove a later fresh UUID is rejected while that intent is unresolved; after authenticated `not_delivered`, only a new UUID explicitly bound by `retry_of_request_id` succeeds, and two racing successors yield one provider call. A delivered reconciliation must transiently fetch Gmail and verify configured account, exact message, `SENT`, thread, and canonical envelope/body before success; wrong account/message/thread/label/envelope/body candidates remain quarantined and ineligible until independent History verification.
- [x] **Step 5: Run the red tests:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_gmail_history_adapter.py tests/test_gmail_history_service.py \
  tests/test_gmail_history_cursor_recovery.py tests/test_gmail_message_processing.py \
  tests/test_gmail_agent_control_origins.py
```

- [x] **Step 6: Implement the adapter, stable advisory-lock helpers, final-page-only cursor protocol, blocked expiry/reseed flow, and the locked pre-send origin state machine.** Use `GMAIL_PARTICIPANT_HASH_KEY` for participant HMACs. The only transient raw body object must be scoped to message processing and discarded before commit/logging/model traces.
- [x] **Step 7: Add the five Task 3 tests to the dedicated workflow command, re-run tests, and inspect captured logs for known fixture secrets.**
- [x] **Step 8: Commit:** `feat: ingest Gmail history safely` (`a864955`).

## Task 4: Extract and reconcile multiple email obligations

**Files:** Create `backend/services/gmail_task_extractor.py`, `backend/services/gmail_obligation_reconciliation.py`, `backend/services/crm_task_suggestion_service.py`, `backend/tests/test_gmail_task_extractor.py`, and `backend/tests/test_crm_task_suggestions.py`.

**Actual file scope (completed 2026-08-21):** The five planned service/test files landed, and accepted pre-release authority findings also hardened revision `83`, its ORM model and migration contract, the common bounded executor, Gmail sanitizer/adapter compatibility, the dedicated PostgreSQL workflow contract, and the workflow itself. No Task 5 schema, service, route, UI, worker composition, provider deployment, or live feature enablement was added.

**Final structured envelope:** The only accepted top-level model shape is strict `gmail-task-v1` with exactly `schema_version` plus `actions` (maximum 20). Each action contains only `kind`, finite backend-advertised `semantic_action`/`semantic_object`, bounded `title`/`description`, `priority`, resolved or explicitly ambiguous due-time fields, requested owner ambiguity, an all-or-none opportunity/listing/agreement link pair, optional contact hint, numeric confidence, and bounded rationale. The model cannot supply action keys, fingerprints, CRM IDs, owner authority, contact candidates, or application authority. Subject and body are separately encoded untrusted evidence; the provider message timestamp is trusted reference context outside those delimiters. Raw output and evidence are capped, control-safe, deadline-bounded, and released from retained exception/cancellation frames.

**Final reconciliation authority:** Backend identity uses canonical semantic intent/object and only a uniquely revalidated CRM contact; rejected hints fall back to receipt-bound participant HMAC identity, with uncertain participants, taxonomy fallbacks, and ambiguous due/owner meanings safely message-scoped. The backend derives and validates reconciliation keys, semantic fingerprints, every normalized text-instance digest, and post-contact material hashes. Exact identity/fingerprint/instance/material evidence attaches idempotently; differing fingerprints become immutable `possible_duplicate` siblings; same-fingerprint differing instances remain one `multiple_actions` manual-review container without overwriting the primary payload. Suppression is scope/fingerprint/instance exact, audited reprocess is exact-receipt, one-use, temporal, and cannot rewrite terminal rows. Reconciliation is fenced by receipt processing lease and account/thread transaction lock, persists immutable append-only evidence plus an exact suggestion-or-suppression disposition, uses bounded indexed candidate/authority/replay probes, and creates zero confirmed CRM tasks, activities, links, lifecycle events, or creation requests. `task_payload` is only an atomic preparation primitive inside the same open transaction after DB-derived scope locking, locked reload, hash/version/state/blocker/sibling/contact revalidation; Task 6 must create before that transaction is released.

**Completion evidence:** The final PostgreSQL 16.13/TLS Task 4 suites passed migration `40/40`, reconciliation `159/159`, and extractor `136/136`; the directly touched extractor/History-adapter/executor compatibility slice passed `236/236`. The exact prior 17-file Task 1-through-Task 3 workflow passed `577/577` with the same 19 `python-jose` `datetime.utcnow()` deprecation warnings (8 cursor-recovery and 11 Workspace OAuth), after which the dedicated workflow was expanded through Task 4 and its two repository contract tests passed `2/2`. Independent review reran the exact three-file Task 4 aggregate `335/335` in 54.84 seconds and returned **QUALITY APPROVED** with zero open Critical/Important findings. PostgreSQL reported TLS active, Alembic reported sole head `83c6f4e8a1b2`, and py_compile, Ruff, and `git diff --check` were clean. The owned cluster was stopped, port `55439` closed, and only its exact disposable directory was removed.

**Task 9 carry-forward:** Task 4 intentionally exposes fixed, body-free invalid-output/reconciliation errors and a bounded `fail_attempt(...)` API; it does not itself own worker orchestration. Task 9 must bind the sanitized body hash/classification to the current processing lease before claim/reconcile, catch fixed invalid-model-output failures, call `fail_attempt(category="invalid_model_output")`, and prove failed terminal state, zero partial obligation/suggestion/source rows, and bounded retry with no N+1 attempt. Do not weaken Task 4 source identity checks to accommodate orchestration order.

- [x] **Step 1: Write failing structured-output tests.** Cover zero, one, and multiple actions; incoming requests; outgoing commitments; dates and timezone ambiguity; missing assignee; quoted-thread suppression; prompt-injection text; schema-invalid model output; and the same commitment observed in sent plus reply messages.
- [x] **Step 2: Write reconciliation tests** proving thread-level semantic matching merges a received request and Brandon/Sydney sent commitment into one suggestion with two `CRMTaskSuggestionSource` rows. Source identity is `(account_id, message_id, action_key, schema_version)`; two same-title messages remain distinct evidence; dismissed obligation fingerprints remain suppressed across extractor upgrades unless an authenticated audited reprocess overrides them; materially changed evidence increments suggestion `version` and invalidates prior previews/nonces.
- [x] **Step 3: Add two-connection serialization tests** proving every same-account/same-thread reconciliation takes the stable transaction advisory lock before querying suggestions and produces one suggestion/source set under a race. Prove different Gmail threads can reconcile concurrently.
- [x] **Step 4: Write authority-shape tests.** Pin Brandon as the only implicit owner and the exact supported applied payload (`title`, `description`, `priority`, `due_at`, optional unique `contact_id`, `status=open`). A clearly non-Brandon owner stays `pending_review` with blocker `unsupported_owner`; ambiguity may ask once whether it is Brandon's follow-up. A requested opportunity/listing/agreement link stays `pending_review` with blocker `unsupported_link`; no `CRMTaskLink` is fabricated and approval stays disabled until a versioned audited create-without-link/Brandon-owned resolution or dismissal.
- [x] **Step 5: Run:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_gmail_task_extractor.py tests/test_crm_task_suggestions.py
```

- [x] **Step 6: Implement a strict Pydantic Gemini response model** separate from existing free-form helpers. Treat email text as untrusted evidence, never as instructions. Persist only bounded evidence previews and hashes.
- [x] **Step 7: Implement reconciliation** with deterministic obligation keys, the per-thread transaction lock, transactional suggestion upserts, and the exact owner/link blockers.
- [x] **Step 8: Add the two Task 4 tests to the dedicated workflow command, re-run tests, and commit:** `feat: extract Gmail task suggestions`.

## Task 5: Add Sydney clarification persistence and one-question flow

**Files:** Create `backend/alembic/versions/84d7a5f9b2c3_add_sydney_task_review.py`, `backend/models/sydney_tasks.py`, `backend/services/sydney_clarification_service.py`, `backend/services/sydney_telegram_dispatcher.py`, `backend/tests/test_sydney_task_review_migration.py`, `backend/tests/test_sydney_clarifications.py`, and `backend/tests/test_sydney_telegram_dispatcher.py`.

- [x] **Step 1: Write failing persistence tests** for the four migration-`84` models in the locked table. Pin one unresolved clarification partial uniqueness per configured chat, unique `(suggestion_id, suggestion_version, field_name)`, round range 1 through 5, immutable outbox attempt payloads and deterministic initial/retry/reminder dedupe keys, nonce kind/issuance-path/conditional-parent constraints, unique SHA-256 hash-only storage, exact 15-minute handoff and 5-minute approval expiry policy, one-time consumption, and immutable events. Seed CRM plus `83`/`84` evidence and prove downgrade refusal preserves all rows; prove the empty owned-table downgrade separately.
- [x] **Step 2: Add behavioral tests** proving Sydney asks only when a required field cannot be safely inferred, asks the single highest-value concise question, waits for its answer, applies the answer to the same suggestion, and never asks about optional polish. Prove there is no repeated field/version; a valid answer increments the suggestion version before reevaluation; an independent version-changing edit/reprocess/source update supersedes the old row and releases the chat slot; the fifth unresolved round becomes `manual_review_required`; and no sixth outbox row is created. Generate a cryptographically random opaque clarification code; store only its hash and never accept suggestion IDs or model-provided chat/user IDs as correlation. With two real PostgreSQL sessions and a barrier, test answer-versus-timeout and answer-versus-edit/source-update while locking suggestion then clarification in one order: exactly one transition wins, and the losing late answer or stale edit makes no mutation.
- [x] **Step 3: Add Telegram identity/correlation tests** in `backend/tests/test_sydney_telegram_dispatcher.py`. The dispatcher may call `sendMessage` only with configured `SYDNEY_TELEGRAM_BRANDON_CHAT_ID`; a known success must return that chat ID and persist its message ID. Use `reply_parameters.message_id` for exactly one reminder at `sent_at + 24 hours`; time out and release the chat slot at `sent_at + 48 hours`. The initial answer tool accepts only opaque code, expected suggestion version, and bounded answer. It verifies the persisted successful outbound correlation but treats Hermes as untrusted input, rejects chat/user/suggestion/approval arguments, and rejects late, timed-out, resolved, old-version, old-field, or old-code answers as `409 stale_clarification`. `SYDNEY_TELEGRAM_BRANDON_USER_ID` grants no backend authority without the future signed inbound adapter.
- [x] **Step 4: Add delivery-state tests** proving the dispatcher creates an immutable initial attempt and commits `sending` before the deadline-bounded, executor-offloaded Telegram `sendMessage`; definite pre-send/provider rejection becomes `failed`; timeout, crash, or unknown response becomes `delivery_uncertain` and is never auto-retried. The sole reminder is a separate immutable `reminder:1` attempt with the same state protocol. Prove failed/uncertain/pending initial attempts release at the fixed 48-hour rule, and neither an explicit retry nor reminder extends it. Add protected operator actions:

```text
POST /api/v1/admin/integrations/gmail-task-intake/clarifications/{id}/reconcile
POST /api/v1/admin/integrations/gmail-task-intake/clarifications/{id}/retry
```

`reconcile` records the observed Telegram result. `retry` requires an administrator reason plus a reconciled `not_delivered` result; it creates a new immutable `initial_retry:{n}` attempt rather than mutating history. No reminder attempt may be retried or replaced.
- [x] **Step 5: Add approval preparation, nonce-generation, and fragment-hygiene tests.** A valid answer returns a Command link shaped only as `/admin/command/task-suggestions?suggestion={id}#handoff={opaque}`. Reject handoff/approval secrets in query parameters. Prove the no-store/no-referrer bootstrap clears the fragment before auth/exchange/telemetry/network calls and never stores it. Authenticated exchange issues a parent-bound `handoff_exchange` approval nonce. The separate ordinary authenticated `/approval/prepare` route issues a parent-null `command_prepare` approval nonce and exact preview. For both kinds, spy that Python `secrets.token_urlsafe(32)` is the source, decoded entropy is exactly 32 bytes, only unique SHA-256 hashes persist, a forced duplicate is handled fail-closed, and malformed/short/noncanonical input is rejected before lookup; do not use a statistical randomness assertion. Prepare/open/exchange create no task; only a later explicit approve request can consume stage two.
- [x] **Step 6: Implement migration** with `down_revision = "83c6f4e8a1b2"`, then services and strict bot-token/outbound-chat configuration when questions are enabled. `SYDNEY_TELEGRAM_BRANDON_USER_ID` is optional future-adapter configuration and grants no initial authority.
- [x] **Step 7: Run:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_sydney_task_review_migration.py tests/test_sydney_clarifications.py \
  tests/test_sydney_telegram_dispatcher.py
```

Expected: pass; `alembic heads` prints only `84d7a5f9b2c3`. Add these three tests to the dedicated workflow command.

- [x] **Step 8: Commit:** `feat: add Sydney task clarifications`.

## Task 6: Add authenticated approval and Agent Control CRM tools

**Files:** Create `backend/services/task_suggestion_approval_service.py`, `backend/routers/admin_integrations.py`, `backend/routers/command_task_suggestions.py`, `backend/routers/agent_control_crm.py`, `backend/schemas/agent_control_crm.py`, `backend/tests/test_task_suggestion_approval.py`, `backend/tests/test_gmail_task_intake_admin.py`, `backend/tests/test_agent_control_crm.py`, `backend/tests/test_agent_control_transactional_audit.py`, and `backend/tests/test_gmail_task_router_registration.py`; modify `backend/main.py`, `backend/routers/agent_control.py`, `backend/schemas/agent_control.py`, and `backend/services/agent_control_audit.py`.

- [x] **Step 1: Write route and registration tests** for authenticated list/detail/edit/preview/approval-prepare/handoff-exchange/approve/dismiss, status/check/backfill (maximum seven days)/reprocess/alert-canary, clarification reconcile/retry, and Agent Control read/draft/answer/approval-link/dismiss-proposal actions. `test_gmail_task_router_registration.py` imports the real `backend/main.py` app, asserts the exact method/path inventory below appears once with unique operation IDs, and issues unauthenticated smoke requests that reach the intended auth boundary rather than returning `404`/`405`. It must fail until `main.py` imports and calls `app.include_router(...)` exactly once for `admin_integrations.router`, `command_task_suggestions.router`, and `agent_control_crm.router`. Pin these protected integration routes:

```text
GET  /api/v1/admin/integrations/gmail-task-intake/status
POST /api/v1/admin/integrations/gmail-task-intake/check
POST /api/v1/admin/integrations/gmail-task-intake/backfill
POST /api/v1/admin/integrations/gmail-task-intake/reprocess/{receipt_id}
POST /api/v1/admin/integrations/gmail-task-intake/alert-canary
GET  /api/v1/admin/integrations/gmail-task-intake/send-intents/{request_id}
POST /api/v1/admin/integrations/gmail-task-intake/send-intents/{request_id}/reconcile
POST /api/v1/admin/integrations/gmail-task-intake/clarifications/{id}/reconcile
POST /api/v1/admin/integrations/gmail-task-intake/clarifications/{id}/retry
GET  /api/v1/command/task-suggestions
GET  /api/v1/command/task-suggestions/{suggestion_id}
PATCH /api/v1/command/task-suggestions/{suggestion_id}
POST /api/v1/command/task-suggestions/{suggestion_id}/preview
POST /api/v1/command/task-suggestions/{suggestion_id}/approval/prepare
POST /api/v1/command/task-suggestions/{suggestion_id}/handoff/exchange
POST /api/v1/command/task-suggestions/{suggestion_id}/approve
POST /api/v1/command/task-suggestions/{suggestion_id}/dismiss
GET  /api/v1/agent-control/crm/tasks
GET  /api/v1/agent-control/crm/task-suggestions
POST /api/v1/agent-control/crm/task-clarifications/answer
POST /api/v1/agent-control/crm/task-drafts
POST /api/v1/agent-control/crm/task-suggestions/{suggestion_id}/approval-link
POST /api/v1/agent-control/crm/task-suggestions/{suggestion_id}/dismiss-proposal
```
- [x] **Step 2: Pin reconciliation and approval bodies.** Send-intent reconcile accepts strict `outcome=delivered|not_delivered`, required bounded reason, expected state/version, and candidate provider message/thread IDs only for `delivered`; it performs no send and applies the transient Gmail verification/quarantine contract above. Approval prepare accepts expected version/hash and returns exact preview plus a `command_prepare` nonce. Handoff exchange accepts only the opaque handoff and expected version/hash and returns a `handoff_exchange` nonce. Approve accepts either stage-two approval nonce, expected version/hash, and a required request UUID.
- [x] **Step 3: Assert authority boundaries:** Hermes-authenticated calls may not create confirmed tasks, approve, dismiss/suppress, archive, or restore. Its dismiss-proposal action appends only a bounded, idempotent, non-authoritative review proposal/event; it cannot change suggestion lifecycle/version, release clarification, or write suppression. Hermes-supplied chat/user/update/reply/suggestion IDs are not identity evidence and the clarification-answer action cannot accept them. Handoff links contain no credential except the fragment secret and query-secret forms are rejected. Pin both approval issuance paths: administrator-null 15-minute handoff; parent-bound `handoff_exchange` approval; parent-null `command_prepare` approval; prepare/open/exchange never applies; changed version/hash, wrong administrator, wrong kind/path/parent, expiry, or replay fails closed.
- [x] **Step 4: Write fail-closed audit tests.** Every write-capable Agent Control handler must add its `AgentActionAudit` using the caller's `AsyncSession` inside the same `db.begin()` transaction as the suggestion/clarification/draft state change. If the audit flush fails, roll back the mutation and return non-2xx; do not call the existing best-effort new-session helper. Repeated idempotency keys return the existing result without a second mutation or success audit.
- [x] **Step 5: Run the red route/registration/audit suite:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_task_suggestion_approval.py tests/test_gmail_task_intake_admin.py \
  tests/test_agent_control_crm.py tests/test_agent_control_transactional_audit.py \
  tests/test_gmail_task_router_registration.py
```

Then register all three routers in `backend/main.py` and implement transactional approval through `crm_task_service` with request-id replay. Only stage-two approval can enter the apply transaction. A consumed nonce, wrong nonce kind/parent, stale version, changed payload hash, wrong administrator, unresolved owner/link blocker, or failed same-transaction audit must create no CRM task.
- [x] **Step 6: Add exactly these initially enabled actions:** `crm.tasks.read`, `crm.task_suggestions.read`, `crm.task_clarifications.answer`, `crm.task_drafts.create`, `crm.task_suggestions.approval_link`, and `crm.task_suggestions.dismiss_proposal`. The answer schema is only opaque code, expected version, and bounded answer; the draft schema has no owner/link authority and creates Brandon-owned review state only; dismiss-proposal is non-authoritative and suppression remains Command-only. Keep `crm.task_suggestions.dismiss`, `crm.task_suggestions.approve`, `crm.tasks.create_confirmed`, `crm.tasks.archive`, and `crm.tasks.restore` absent from the advertised registry.
- [x] **Step 7: Add all five Task 6 tests to the dedicated workflow command, re-run the exact route/registration/audit tests, and commit:** `feat: connect Sydney to CRM task review`.

## Task 7: Build the Command task-suggestion workspace

**Files:** Create `frontend/src/app/admin/command/task-suggestions/page.tsx`, `frontend/src/lib/command/task-suggestions.ts`, `frontend/src/lib/command/task-suggestions.test.ts`, `frontend/src/components/command/TaskSuggestionsWorkspace.tsx`, and `frontend/src/components/command/TaskSuggestionsWorkspace.test.tsx`; modify `frontend/src/components/command/shell/commandNavigation.ts`, `frontend/src/components/command/shell/commandNavigation.test.ts`, and `frontend/src/components/command/shell/CommandShell.test.tsx`.

- [x] **Step 1: Read and apply `frontend-design` and `vercel-react-best-practices` before editing frontend code.**
- [x] **Step 2: Write failing Vitest/Testing Library tests** for loading, empty, error, review, clarification-needed, timed-out/manual-review, unsupported-owner, unsupported-link, explicit blocker resolution, final preview, stale-version, approval-success, dismissal, ordinary Command prepare, two-stage one-time handoff exchange/removal, and keyboard/focus behavior. Prove fragment clearing occurs before any application network/telemetry, query secrets are rejected, and prepare/open/exchange alone never calls approve. Native `prompt()`/`confirm()` is forbidden.
- [x] **Step 3: Extend the exact navigation registry.** Add one `commandNavigation` destination with `href: '/admin/command/task-suggestions'`, assert it in `frontend/src/components/command/shell/commandNavigation.test.ts`, and assert desktop rail, expanded rail, mobile drawer, global search, and utility-header active-state behavior through the existing registry consumers in `CommandShell.test.tsx`. Do not create a second navigation array.
- [x] **Step 4: Run:**

```bash
cd frontend
npm test -- src/lib/command/task-suggestions.test.ts \
  src/components/command/TaskSuggestionsWorkspace.test.tsx \
  src/components/command/shell/commandNavigation.test.ts \
  src/components/command/shell/CommandShell.test.tsx
```

- [x] **Step 5: Implement** a dark SWS Command surface with typed fetches, explicit reason input, server-acknowledged state changes, stale-write refetch, a clear badge for Sydney questions, explicit Brandon-owner/create-without-link resolution controls, and the final payload hash/preview before approval. The dedicated no-store/no-referrer bootstrap captures `#handoff=` into closure memory and clears the fragment before hydration/network; it never accepts a secret query parameter. An already-authenticated admin exchanges it, while an unauthenticated visitor is told to sign in and reopen the unused link. A normal Command review calls `/approval/prepare` instead. Hold either returned approval nonce only in memory and require a separate Approve click. Approval is disabled for unresolved clarification, `unsupported_owner`, or `unsupported_link`.
- [x] **Step 6: Re-run focused tests and `npm run typecheck`, then gate only the touched files with:**

```bash
npm exec eslint -- \
  src/app/admin/command/task-suggestions/page.tsx \
  src/lib/command/task-suggestions.ts \
  src/lib/command/task-suggestions.test.ts \
  src/components/command/TaskSuggestionsWorkspace.tsx \
  src/components/command/TaskSuggestionsWorkspace.test.tsx \
  src/components/command/shell/commandNavigation.ts \
  src/components/command/shell/commandNavigation.test.ts \
  src/components/command/shell/CommandShell.test.tsx
```

Run full `npm run lint` once only to capture the pre-existing known-red repository baseline separately in task evidence; its failures are not this task's gate and must never be reported as green. The focused tests, typecheck, and scoped touched-file ESLint must pass. Then commit: `feat: add task suggestion review UI`.

## Task 8: Package the Hermes overlay and MCP tool contract

**Files:** Create `hermes/overlay/manifest.json`, `hermes/overlay/apply_overlay.py`, `hermes/overlay/atlas_backend_bootstrap.py`, `hermes/verify_atlas_tools.py`, `backend/tests/test_hermes_overlay.py`, and `backend/tests/test_verify_atlas_tools.py`; modify `hermes/atlas_backend_mcp.py`, `backend/tests/test_atlas_backend_mcp.py`, `backend/tests/test_integration_worker_deployment.py`, `docs/deployment/hermes-railway.md`, and `.github/workflows/gmail-sydney-task-intake.yml`.

**Rollout dependency:** Task 7's authenticated review route, two-stage handoff exchange, blocker UI, and production deployment must be verified before Task 8 may deploy or advertise `crm_task_suggestions_approval_link`, `crm_task_clarifications_answer`, or `crm_task_drafts_create`. Overlay code/tests may be prepared earlier, but production `tools.include` remains unchanged until that gate passes. Independently, this whole plan starts only after Tasks 7 and 8 in `docs/superpowers/plans/2026-08-18-crm-task-archive-foundation.md` are complete and green, so the contact workspace and lifecycle E2E already prove the shared task read/write contract.

- [x] **Step 1: Write failing tests** that pin upstream Hermes commit `7224d7c1a4dcffe9304f49bc843f55716f5561b4`, apply the overlay reproducibly, and assert `tools.include` preserves these exact existing 16 names unchanged: `status_read`, `actions_list`, `leads_recent`, `bookings_recent`, `workspace_status`, `drive_search`, `drive_file_read`, `gmail_search`, `gmail_thread_read`, `gmail_draft_create`, `gmail_send`, `docs_create`, `sheets_append`, `calendar_events_read`, `calendar_event_create`, `contacts_search`. Add exactly six: `crm_tasks_read`, `crm_task_suggestions_read`, `crm_task_clarifications_answer`, `crm_task_drafts_create`, `crm_task_suggestions_approval_link`, `crm_task_suggestions_dismiss_proposal`. The final registry is exactly 22 unique tools; no existing name is removed or renamed, and `gmail_send` now exposes required UUID `request_id`.
- [x] **Step 2: Add MCP tests** for typed request/response mapping, hard timeout behavior, secret-free errors, and exact registry/risk descriptions. The answer tool exposes no chat/user/update/suggestion/approval fields and says Hermes input is untrusted draft evidence. The dismiss-proposal tool says it is non-authoritative, cannot dismiss/suppress/release anything, and only records a review proposal. Assert actual dismiss/approve/create-confirmed/archive/restore tools are absent.
- [x] **Step 3: Implement the overlay/bootstrap and MCP mappings**, update `docs/deployment/hermes-railway.md` with those exact names, then run:

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_atlas_backend_mcp.py tests/test_agent_control_crm.py \
  tests/test_hermes_overlay.py tests/test_verify_atlas_tools.py
```

- [x] **Step 4: After deploying the intended commit, inspect the live `atlas-agent` runtime rather than accepting a local registry test:**

```bash
env -u RAILWAY_API_TOKEN -u RAILWAY_TOKEN railway ssh \
  --project aa6c9f9c-46d4-4f5d-b529-86b073de4972 \
  --service atlas-agent --environment production -- \
  hermes mcp test atlas_backend
```

Capture the deployment ID/commit and machine-readable JSON-RPC `tools/list` output from `/app/atlas_backend_mcp.py`; the deployed Hermes CLI does not implement `mcp tools list ... --json`. Assert all exact 22 names are present once, the original 16 are unchanged, and every disabled trusted-write/actual-dismiss name is absent. If Railway SSH still reports MEMBER permission required, stop the rollout and obtain project-member access; a local bridge call, backend `/actions`, or source inspection does not satisfy this gate.
- [x] **Step 5: Commit:** `feat: expose CRM review tools to Hermes`.

Completion evidence (2026-08-23): source commit `a53ff04421c395be54012398cc1dccecddf08f97`, PR #5 merge `f3ed543359cac39c3caa66dd3d25592319f1b921`, backend deployment `e29cfc64-5b2d-4265-ad9d-0e0d7d00a226`, and Atlas deployment `51f50a75-32ed-4ed7-bd88-5dc5bfde0988` all reached the required green state. Both public health endpoints returned HTTP 200. Railway SSH connected with Member access; `hermes mcp test atlas_backend` discovered 22 tools. A live JSON-RPC `tools/list` returned exactly 22 ordered unique names, preserved the original 16 unchanged, appended the exact six review tools, exposed required UUID `gmail_send.request_id`, and contained none of the five forbidden trusted-write tools. Task 7's authenticated production handoff and separate approval gate were verified first; no approval was clicked and controlled fixtures were dismissed without creating a task. The three rollout flags remain disabled.

## Task 9: Wire worker jobs and verify the end-to-end intake loop

**Files:** Complete `backend/workers/jobs/gmail_history.py`, `backend/workers/jobs/gmail_receipts.py`, `backend/workers/jobs/sydney_questions.py`, `backend/workers/jobs/integration_alerts.py`, `backend/tests/test_gmail_task_intake_e2e.py`, deployment docs, `tdtn.md`, and `memory.md`.

- [ ] **Step 1: Write deterministic end-to-end tests** covering three independent workflows:

```text
controlled received message -> one receipt -> one review suggestion -> authenticated approval -> one task
controlled sent commitment -> persisted Agent Control origin + one receipt -> one review suggestion -> one task
direct Sydney draft -> same evaluator -> one clarification -> answer -> final preview/Command link -> one task
```

Also cover one received request plus Sydney-sent commitment in the same Gmail thread reconciling to one suggestion/task with two source links. Replaying History, the same Gmail send UUID, origin enqueue, any immutable initial/retry/reminder attempt, answer, either approval issuance path, approval, or task creation must not add a duplicate. Add clock-controlled cases for the one 24-hour reminder, fixed 48-hour release/stale late answer, five-round ceiling, and Task 7/8 rollout feature gates.
- [ ] **Step 2: Wire job schedules** for history polling, receipt processing, Sydney questions, and integration alerts. Use deterministic job keys and leased claims.
- [ ] **Step 3: Expand the dedicated workflow rather than replacing earlier jobs.** Pin its final PostgreSQL list to every backend persistence/concurrency/E2E test in Tasks 1–6 and 9; retain the Task 7 exact Vitest/typecheck/scoped-ESLint job and the Task 8 exact MCP/overlay/22-tool job. Keep `hermes/**`, both frontend package files, and every exact Task 7 source/test path in triggers. Run the focused backend/frontend suites and record the known-red full frontend lint baseline separately without treating it as a green gate.
- [ ] **Step 4: Run the deployment preflight:** prove the CRM task-foundation Tasks 7/8 evidence is green; capture intended backend/worker/frontend/Hermes commits and deployment IDs; check backend `/health`; check the worker's exact `/health` and `/ready` JSON with `backend/scripts/check_integration_worker.py` (not curl); verify sole Alembic head `84d7a5f9b2c3`; OAuth profile/current History access; Telegram `getMe`; configured outbound chat allowlist; protected Gmail status; deployed authenticated Task 7 handoff exchange/URL removal; and the live deployed `tools/list` gate from Task 8. A configured Telegram user ID is recorded only as future-gate configuration, not current trusted inbound proof.
- [ ] **Step 5: Run controlled production E2Es with unique UUID fixture IDs and Brandon's explicit approval.** Send one controlled received email into the mailbox, one controlled Agent Control sent commitment, and one direct Sydney draft. For each, record the redacted send-intent state transition, Gmail message/thread IDs, receipt/suggestion IDs, source counts, clarification/outbox/Telegram message IDs where applicable, handoff and approval nonce consumption timestamps (never nonce values), final preview hash, task ID, and audit ID. Query counts before/after and replay each input to prove exactly one task. Do not use a client conversation or enable autonomous creation.
- [ ] **Step 6: Update deployment docs, `tdtn.md`, and `memory.md`** with exact environment variables, Railway worker command and both probes, enable/disable switches, final-page cursor/reseed/backfill runbook, Telegram uncertain-delivery reconciliation, live `tools/list` evidence, rollback, and remaining blockers.
- [ ] **Step 7: Commit:** `docs: document Gmail Sydney task intake`.

## Rollout Gate

Do not begin implementation until Tasks 7 and 8 of `docs/superpowers/plans/2026-08-18-crm-task-archive-foundation.md` are green. Keep `GMAIL_TASK_INTAKE_ENABLED=false`, `SYDNEY_TASK_QUESTIONS_ENABLED=false`, and confirmed Hermes writes absent until migrations, exact worker `/health` and `/ready`, live OAuth History access, outbound Telegram chat configuration, live deployed exact-22 `tools/list`, the deployed Task 7 review/two-path-approval UI, final-page cursor recovery, per-account/per-thread PostgreSQL serialization, transactional write-audit rollback, and all controlled received/sent/direct-draft idempotency evidence are green. Task 8 may not advertise answer/draft/handoff tools before Task 7 is deployed and verified. Enable Gmail in shadow mode first, then review suggestions, then read/proposal-only tools, then Sydney questions/drafts/handoff; final creation and actual dismissal/suppression remain authenticated Command-only.
