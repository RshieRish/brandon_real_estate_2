# Gmail and Sydney Task Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn received and sent Gmail messages into reviewable CRM task suggestions, let Sydney ask one concise clarification question when required, and require an authenticated Command approval before a task becomes real.

**Architecture:** A dedicated integration worker polls Gmail History under a per-account PostgreSQL advisory lock, writes durable source receipts, and extracts zero or more obligations without retaining raw message bodies. Thread-level reconciliation creates versioned task suggestions and a durable clarification outbox. Sydney delivers one Telegram question at a time through a repo-owned dispatcher; answers update the draft, while final approval happens through a short-lived nonce in authenticated Command. All confirmed creation routes use the shared `crm_task_service` from the task-foundation plan.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, PostgreSQL, Alembic, Google Gmail API, Gemini structured output, Telegram Bot API, Next.js/React/TypeScript, Vitest, Testing Library, Playwright, Railway.

---

## File Structure

Create:

- `backend/models/integration_health.py`, `backend/models/gmail_task_intake.py`, `backend/models/sydney_tasks.py`
- `backend/schemas/gmail_task_intake.py`, `backend/schemas/agent_control_crm.py`
- `backend/services/integration_health_service.py`
- `backend/services/gmail_history_adapter.py`, `backend/services/gmail_history_service.py`
- `backend/services/gmail_message_sanitizer.py`, `backend/services/gmail_task_extractor.py`
- `backend/services/gmail_obligation_reconciliation.py`, `backend/services/crm_task_suggestion_service.py`
- `backend/services/sydney_clarification_service.py`, `backend/services/sydney_telegram_dispatcher.py`
- `backend/services/task_suggestion_approval_service.py`, `backend/services/gmail_task_intake_health.py`
- `backend/routers/admin_integrations.py`, `backend/routers/command_task_suggestions.py`, `backend/routers/agent_control_crm.py`
- `backend/workers/__init__.py`, `backend/workers/health_app.py`, `backend/workers/integration_worker.py`
- `backend/workers/jobs/gmail_history.py`, `backend/workers/jobs/gmail_receipts.py`, `backend/workers/jobs/sydney_questions.py`, `backend/workers/jobs/integration_alerts.py`
- `backend/Dockerfile.worker`, `backend/railway.integration-worker.json`
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
- `backend/tests/test_agent_control_transactional_audit.py`, `backend/tests/test_hermes_overlay.py`
- `backend/tests/test_gmail_task_intake_e2e.py`

Modify:

- `backend/config.py`, `backend/.env.example`, `backend/main.py`
- `backend/models/__init__.py`, `backend/alembic/env.py`
- `backend/models/notification_job.py`, `backend/services/notification_service.py`
- `backend/services/workspace_service.py`
- `backend/routers/agent_control.py`, `backend/schemas/agent_control.py`
- `hermes/atlas_backend_mcp.py`, `backend/tests/test_atlas_backend_mcp.py`
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
| `GmailMessageReceipt` | `gmail_message_receipts` | Unique `(account_id, gmail_message_id)`; direction, thread ID, timestamps, participant HMACs, bounded subject preview, body hash, and processing state; no raw body. |
| `GmailMessageOrigin` | `gmail_message_origins` | Unique provider message ID and unique Agent Control idempotency key; records `sydney_client_send`, `human_send`, or `system_automation` plus the originating action audit. |
| `GmailExtractionAttempt` | `gmail_extraction_attempts` | Unique bounded attempt number per receipt/schema version with state and sanitized error category. |
| `GmailExtractedObligation` | `gmail_extracted_obligations` | Unique `(receipt_id, action_key, schema_version)`; structured fields, obligation fingerprint, confidence, and evaluator result. |
| `CRMTaskSuggestion` | `crm_task_suggestions` | Versioned review state, editable task payload, payload hash, clarification state, application idempotency key, and applied task ID. |
| `CRMTaskSuggestionSource` | `crm_task_suggestion_sources` | Unique many-source link `(suggestion_id, obligation_id)` so a reconciled obligation retains every received/sent source. |
| `CRMTaskSuggestionSuppression` | `crm_task_suggestion_suppressions` | Unique stable obligation fingerprint; dismissal reason/actor/audit and optional authenticated reprocess override. |
| `GmailBackfillRequest` | `gmail_backfill_requests` | Explicit administrator, reason, bounded start/end, expired cursor, reseed cursor, audit ID, and run/result state. |

Migration `84d7a5f9b2c3` owns clarification and approval state:

| Model | Table | Required invariant |
|---|---|---|
| `CRMTaskClarification` | `crm_task_clarifications` | Suggestion/version-bound opaque code, one unresolved clarification per Telegram chat, question/answer, 24-hour reminder count, and resolution. |
| `SydneyQuestionOutbox` | `sydney_question_outbox` | Durable `pending/sending/sent/failed/delivery_uncertain` delivery intent with Telegram chat/message IDs and no automatic retry from uncertain state. |
| `TaskSuggestionApprovalNonce` | `crm_task_suggestion_approval_nonces` | Store only nonce hash; bind to suggestion ID/version, payload hash, administrator, expiry, and one-time consumption. |
| `CRMTaskSuggestionEvent` | `crm_task_suggestion_events` | Immutable state transition/audit reference for edit, clarify, dismiss, preview, approve, apply, and reprocess. |

Every migration test must assert the exact table/constraint inventory, upgrade/downgrade without dropping existing CRM rows, and `alembic heads` returning one head.

## Isolated PostgreSQL test prerequisite

Continue from the disposable PostgreSQL database created by the task-foundation plan after it is at head `81a4d2c6e9f0`. Export that verified URL as `GMAIL_TASK_TEST_DATABASE_URL`, require its database name to end in `_test`, and refuse development, staging, or production URLs. Every concurrency, advisory-lock, lease, cursor, migration, and end-to-end test in this plan must use independent real PostgreSQL connections; SQLite and a parse-only URL do not satisfy the gate.

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

Known-success Agent Control sends participate in intake immediately and exactly once:

```python
provider_result = await send_gmail_message(...)
async with db.begin():
    origin = await record_origin(
        message_id=provider_result.message_id,
        thread_id=provider_result.thread_id,
        origin_kind="sydney_client_send",
        idempotency_key=request_id,
        action_audit_id=audit.id,
    )
    await enqueue_receipt_from_origin(origin)
```

The later Gmail History observation upserts the same `(account_id, gmail_message_id)` receipt and attaches the existing origin instead of creating another suggestion. `sydney_client_send` remains eligible as an outgoing commitment; `system_automation`, drafts, spam, trash, and internal loop notifications are ineligible by durable origin/label metadata rather than subject heuristics.

## Task 1: Add shared integration health and safe job claims

**Files:** Create `backend/alembic/versions/82b5e3d7f0a1_add_integration_runtime_health.py`, `backend/models/integration_health.py`, `backend/services/integration_health_service.py`, `backend/workers/health_app.py`, `backend/workers/integration_worker.py`, `backend/Dockerfile.worker`, `backend/railway.integration-worker.json`, `backend/tests/test_integration_runtime_migration.py`, `backend/tests/test_integration_health_service.py`, `backend/tests/test_notification_claims.py`, `backend/tests/test_integration_worker.py`, and `backend/tests/test_integration_worker_deployment.py`; modify `backend/models/notification_job.py`, `backend/services/notification_service.py`, `backend/config.py`, `backend/models/__init__.py`, and `backend/alembic/env.py`.

- [ ] **Step 1: Write failing tests** in the five exact test files above. Assert one Alembic head, atomic `FOR UPDATE SKIP LOCKED` claims, stale-lease recovery, deterministic dedupe keys, and no integration loops in the FastAPI web process. Pin separate worker probes:

```python
assert client.get("/health").json() == {
    "status": "ok",
    "service": "integration-worker",
}
ready = client.get("/ready")
assert ready.status_code == 200
assert ready.json()["database"] == "ok"
assert ready.json()["job_registry"] == "ok"
```

`/health` is liveness only. `/ready` returns 503 until PostgreSQL is reachable, the single expected Alembic head is present, the worker heartbeat can be written, and enabled jobs have valid non-secret configuration. Provider OAuth health remains in the protected integration status route so Railway does not restart a healthy worker merely because Google revoked access.
- [ ] **Step 2: Run the red suite:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_integration_runtime_migration.py tests/test_integration_health_service.py \
  tests/test_notification_claims.py tests/test_integration_worker.py \
  tests/test_integration_worker_deployment.py
```

Expected: imports and worker deployment files are missing.

- [ ] **Step 3: Implement** shared health rows, leased notification claims, and the job registry. Keep detailed heartbeat/lag/error fields on authenticated admin status; public `/health` and `/ready` expose only the bounded probe contract above.
- [ ] **Step 4: Add deployment configuration** with the single start command `python -m workers.integration_worker`. That module owns an `asyncio.TaskGroup` containing the scheduler loop and `uvicorn.Server(Config("workers.health_app:app", host="0.0.0.0", port=int(os.environ["PORT"])))`; either task exiting cancels the other and makes the container fail. Set Railway health path `/health` and gate promotion on `/ready`. Keep the web app health check independent; never inherit `uvicorn main:app --workers 2` for the worker and never start scheduling from the web app lifespan.
- [ ] **Step 5: Re-run the suite**, then `alembic heads`; expected sole head `82b5e3d7f0a1` after the task-foundation migration.
- [ ] **Step 6: Commit:** `feat: add integration worker runtime`.

## Task 2: Persist Gmail cursors, receipts, obligations, and suggestions

**Files:** Create `backend/alembic/versions/83c6f4e8a1b2_add_gmail_task_intake.py`, `backend/models/gmail_task_intake.py`, `backend/schemas/gmail_task_intake.py`, and `backend/tests/test_gmail_task_intake_migration.py`; register every model in `backend/models/__init__.py` and `backend/alembic/env.py`.

- [ ] **Step 1: Write model tests** for all eleven migration-`83` models in the locked table above: account, sync run, page checkpoint, receipt, origin, extraction attempt, obligation, suggestion, many-source link, suppression, and backfill request. Require the named uniqueness constraints, suggestion `version`, explicit lifecycle states, bounded redacted errors, and the structural absence of raw body/token columns.
- [ ] **Step 2: Run:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q tests/test_gmail_task_intake_migration.py
```

Expected: missing model imports.

- [ ] **Step 3: Implement the exact schema** with `down_revision = "82b5e3d7f0a1"`. Use `CheckConstraint`s for states/directions/run kinds, a partial unique active-run constraint per account, and indexes for pending receipts, blocked accounts, suggestion review state, and source lookup. Do not add a raw-body column.
- [ ] **Step 4: Register the models**, run the test and confirm `alembic heads` is only `83c6f4e8a1b2`.
- [ ] **Step 5: Commit:** `feat: persist Gmail task intake`.

## Task 3: Build the typed Gmail History adapter and receipt pipeline

**Files:** Create `backend/services/gmail_history_adapter.py`, `backend/services/gmail_history_service.py`, `backend/services/gmail_message_sanitizer.py`, `backend/tests/test_gmail_history_adapter.py`, `backend/tests/test_gmail_history_service.py`, `backend/tests/test_gmail_history_cursor_recovery.py`, `backend/tests/test_gmail_message_processing.py`, and `backend/tests/test_gmail_agent_control_origins.py`; modify `backend/services/workspace_service.py` only for reusable credential/client primitives and known-success Agent Control origin recording.

- [ ] **Step 1: Write adapter contract tests** for profile, paginated history, message metadata/content, and classified failures: `oauth_revoked`, `history_cursor_expired`, `rate_limited`, `transient_provider`, `malformed_provider`.
- [ ] **Step 2: Write ingestion tests** proving a PostgreSQL advisory lock serializes one account, each page checkpoint/receipt batch commits while `GmailSyncAccount.committed_history_id` stays unchanged, a crash resumes from the saved next-page token, and only the final page transaction advances the committed cursor. Cover received, sent, self-copy, draft, spam, and automation labels; replay; compare-and-set cursor races; and secret/body-free exceptions/logs.
- [ ] **Step 3: Write cursor-expiry tests** in `backend/tests/test_gmail_history_cursor_recovery.py`: a 404/expired cursor blocks the account, leaves the old committed cursor intact, records only a current reseed candidate, alerts once, rejects automatic/unbounded repair, and promotes the reseed cursor only after an authenticated, reasoned, maximum-seven-day `GmailBackfillRequest` finishes its final page.
- [ ] **Step 4: Write sent-origin tests** in `backend/tests/test_gmail_agent_control_origins.py`: known-success `workspace.gmail.send` persists `GmailMessageOrigin` and an eligible receipt in the same transaction as its write audit; a later History observation deduplicates it; `system_automation` remains ineligible; uncertain provider delivery does not invent a message ID or retry blindly.
- [ ] **Step 5: Run the red tests:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_gmail_history_adapter.py tests/test_gmail_history_service.py \
  tests/test_gmail_history_cursor_recovery.py tests/test_gmail_message_processing.py \
  tests/test_gmail_agent_control_origins.py
```

- [ ] **Step 6: Implement the adapter, final-page-only cursor protocol, blocked expiry/reseed flow, and sent-origin intake.** Use `GMAIL_PARTICIPANT_HASH_KEY` for participant HMACs. The only transient raw body object must be scoped to message processing and discarded before commit/logging/model traces.
- [ ] **Step 7: Re-run tests** and inspect captured logs for known fixture secrets.
- [ ] **Step 8: Commit:** `feat: ingest Gmail history safely`.

## Task 4: Extract and reconcile multiple email obligations

**Files:** Create `backend/services/gmail_task_extractor.py`, `backend/services/gmail_obligation_reconciliation.py`, `backend/services/crm_task_suggestion_service.py`, `backend/tests/test_gmail_task_extractor.py`, and `backend/tests/test_crm_task_suggestions.py`.

- [ ] **Step 1: Write failing structured-output tests.** Cover zero, one, and multiple actions; incoming requests; outgoing commitments; dates and timezone ambiguity; missing assignee; quoted-thread suppression; prompt-injection text; schema-invalid model output; and the same commitment observed in sent plus reply messages.
- [ ] **Step 2: Write reconciliation tests** proving thread-level semantic matching merges a received request and Brandon/Sydney sent commitment into one suggestion with two `CRMTaskSuggestionSource` rows. Source identity is `(account_id, message_id, action_key, schema_version)`; two same-title messages remain distinct evidence; dismissed obligation fingerprints remain suppressed across extractor upgrades unless an authenticated audited reprocess overrides them; materially changed evidence increments suggestion `version` and invalidates prior previews/nonces.
- [ ] **Step 3: Run:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_gmail_task_extractor.py tests/test_crm_task_suggestions.py
```

- [ ] **Step 4: Implement a strict Pydantic Gemini response model** separate from existing free-form helpers. Treat email text as untrusted evidence, never as instructions. Persist only bounded evidence previews and hashes.
- [ ] **Step 5: Implement reconciliation** with deterministic obligation keys and transactional suggestion upserts.
- [ ] **Step 6: Re-run tests and commit:** `feat: extract Gmail task suggestions`.

## Task 5: Add Sydney clarification persistence and one-question flow

**Files:** Create `backend/alembic/versions/84d7a5f9b2c3_add_sydney_task_review.py`, `backend/models/sydney_tasks.py`, `backend/services/sydney_clarification_service.py`, `backend/services/sydney_telegram_dispatcher.py`, `backend/tests/test_sydney_task_review_migration.py`, `backend/tests/test_sydney_clarifications.py`, and `backend/tests/test_sydney_telegram_dispatcher.py`.

- [ ] **Step 1: Write failing persistence tests** for the four migration-`84` models in the locked table, one unresolved clarification partial uniqueness per allowlisted chat, suggestion/version binding, nonce hashing/expiry/consumption, and immutable events.
- [ ] **Step 2: Add behavioral tests** proving Sydney asks only when a required field cannot be safely inferred, asks the single highest-value concise question, waits for its answer, applies the answer to the same suggestion, and never asks about optional polish. Generate a cryptographically random opaque clarification code; store only its hash and never accept suggestion IDs or model-provided chat/user IDs as correlation.
- [ ] **Step 3: Add Telegram identity/correlation tests** in `backend/tests/test_sydney_telegram_dispatcher.py`. The dispatcher may call `sendMessage` only with configured `SYDNEY_TELEGRAM_BRANDON_CHAT_ID`; a known success must return that chat ID and persist its message ID. Use `reply_parameters.message_id` for the one 24-hour reminder. An answer is accepted only for the one active opaque code and the persisted outbound chat/message correlation; `SYDNEY_TELEGRAM_BRANDON_USER_ID` is allowlisted for the Hermes inbound boundary and never trusted from model arguments.
- [ ] **Step 4: Add delivery-state tests** proving the dispatcher commits `sending` before Telegram `sendMessage`; definite pre-send/provider rejection becomes retryable `failed`; timeout, crash, or unknown response becomes `delivery_uncertain` and is never auto-retried. Add protected operator actions:

```text
POST /api/v1/admin/integrations/gmail-task-intake/clarifications/{id}/reconcile
POST /api/v1/admin/integrations/gmail-task-intake/clarifications/{id}/retry
```

`reconcile` records the observed Telegram result. `retry` requires an administrator reason plus a reconciled `not_delivered` result; it creates a new outbox attempt rather than mutating history. Schedule exactly one reminder at `sent_at + 24 hours`; after that, leave the suggestion in Command indefinitely without another reminder.
- [ ] **Step 5: Add final-preview tests.** A valid answer increments the suggestion version, reruns the evaluator, and returns a bounded final task preview plus a short-lived Command link shaped as `/admin/command/task-suggestions?suggestion={id}&approval={opaque_nonce}`. The nonce is not an admin credential, is hash-stored, version/payload-bound, single-use, removed from the browser URL after exchange, and cannot approve without a valid Command admin session.
- [ ] **Step 6: Implement migration** with `down_revision = "83c6f4e8a1b2"`, then services and strict `SYDNEY_TELEGRAM_*` config validation.
- [ ] **Step 7: Run:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_sydney_task_review_migration.py tests/test_sydney_clarifications.py \
  tests/test_sydney_telegram_dispatcher.py
```

Expected: pass; `alembic heads` prints only `84d7a5f9b2c3`.

- [ ] **Step 8: Commit:** `feat: add Sydney task clarifications`.

## Task 6: Add authenticated approval and Agent Control CRM tools

**Files:** Create `backend/services/task_suggestion_approval_service.py`, `backend/routers/admin_integrations.py`, `backend/routers/command_task_suggestions.py`, `backend/routers/agent_control_crm.py`, `backend/schemas/agent_control_crm.py`, `backend/tests/test_task_suggestion_approval.py`, `backend/tests/test_gmail_task_intake_admin.py`, `backend/tests/test_agent_control_crm.py`, and `backend/tests/test_agent_control_transactional_audit.py`; modify `backend/routers/agent_control.py`, `backend/schemas/agent_control.py`, and `backend/services/agent_control_audit.py`.

- [ ] **Step 1: Write route tests** for authenticated list/detail/edit/preview/approve/dismiss, status/check/backfill (maximum seven days)/reprocess/alert-canary, clarification reconcile/retry, and Agent Control read/draft/answer/approval-link/dismiss actions. Pin these protected integration routes:

```text
GET  /api/v1/admin/integrations/gmail-task-intake/status
POST /api/v1/admin/integrations/gmail-task-intake/check
POST /api/v1/admin/integrations/gmail-task-intake/backfill
POST /api/v1/admin/integrations/gmail-task-intake/reprocess/{receipt_id}
POST /api/v1/admin/integrations/gmail-task-intake/alert-canary
```
- [ ] **Step 2: Assert authority boundaries:** Hermes-authenticated calls may not create confirmed tasks, approve, archive, or restore. Approval links contain no credentials. Nonces are hash-stored, short-lived, single-use, and bound to suggestion ID, version, administrator, and payload hash.
- [ ] **Step 3: Write fail-closed audit tests.** Every write-capable Agent Control handler must add its `AgentActionAudit` using the caller's `AsyncSession` inside the same `db.begin()` transaction as the suggestion/clarification/draft state change. If the audit flush fails, roll back the mutation and return non-2xx; do not call the existing best-effort new-session helper. Repeated idempotency keys return the existing result without a second mutation or success audit.
- [ ] **Step 4: Run the red route/audit suite:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_task_suggestion_approval.py tests/test_gmail_task_intake_admin.py \
  tests/test_agent_control_crm.py tests/test_agent_control_transactional_audit.py
```

Then implement transactional approval through `crm_task_service` with request-id replay. A consumed nonce, stale version, changed payload hash, wrong administrator, or failed same-transaction audit must create no CRM task.
- [ ] **Step 5: Add exactly these initially enabled actions:** `crm.tasks.read`, `crm.task_suggestions.read`, `crm.task_clarifications.answer`, `crm.task_drafts.create`, `crm.task_suggestions.approval_link`, and `crm.task_suggestions.dismiss`. Keep `crm.task_suggestions.approve`, `crm.tasks.create_confirmed`, `crm.tasks.archive`, and `crm.tasks.restore` absent from the advertised registry.
- [ ] **Step 6: Re-run the exact route/audit tests and commit:** `feat: connect Sydney to CRM task review`.

## Task 7: Build the Command task-suggestion workspace

**Files:** Create `frontend/src/app/admin/command/task-suggestions/page.tsx`, `frontend/src/lib/command/task-suggestions.ts`, `frontend/src/lib/command/task-suggestions.test.ts`, `frontend/src/components/command/TaskSuggestionsWorkspace.tsx`, and `frontend/src/components/command/TaskSuggestionsWorkspace.test.tsx`; modify `frontend/src/components/command/shell/commandNavigation.ts`, `frontend/src/components/command/shell/commandNavigation.test.ts`, and `frontend/src/components/command/shell/CommandShell.test.tsx`.

- [ ] **Step 1: Read and apply `frontend-design` and `vercel-react-best-practices` before editing frontend code.**
- [ ] **Step 2: Write failing Vitest/Testing Library tests** for loading, empty, error, review, clarification-needed, final preview, stale-version, approval-success, dismissal, one-time approval-link exchange/removal, and keyboard/focus behavior. Native `prompt()`/`confirm()` is forbidden.
- [ ] **Step 3: Extend the exact navigation registry.** Add one `commandNavigation` destination with `href: '/admin/command/task-suggestions'`, assert it in `frontend/src/components/command/shell/commandNavigation.test.ts`, and assert desktop rail, expanded rail, mobile drawer, global search, and utility-header active-state behavior through the existing registry consumers in `CommandShell.test.tsx`. Do not create a second navigation array.
- [ ] **Step 4: Run:**

```bash
cd frontend
npm test -- src/lib/command/task-suggestions.test.ts \
  src/components/command/TaskSuggestionsWorkspace.test.tsx
```

- [ ] **Step 5: Implement** a dark SWS Command surface with typed fetches, explicit reason input, server-acknowledged state changes, stale-write refetch, a clear badge for Sydney questions, and the final payload hash/preview before approval. On `?suggestion=&approval=`, exchange the opaque nonce only after admin auth, then immediately `router.replace('/admin/command/task-suggestions?suggestion={id}')` so it is not retained in the address bar.
- [ ] **Step 6: Re-run focused tests, `npm run typecheck`, `npm run lint`, and commit:** `feat: add task suggestion review UI`.

## Task 8: Package the Hermes overlay and MCP tool contract

**Files:** Create overlay files; modify MCP bridge and exact-tool test; create `backend/tests/test_hermes_overlay.py`.

- [ ] **Step 1: Write failing tests** that pin upstream Hermes commit `7224d7c1a4dcffe9304f49bc843f55716f5561b4`, apply the overlay reproducibly, and assert `tools.include` contains the exact enabled MCP names `crm_tasks_read`, `crm_task_suggestions_read`, `crm_task_clarifications_answer`, `crm_task_drafts_create`, `crm_task_suggestions_approval_link`, and `crm_task_suggestions_dismiss`, while excluding approve/create-confirmed/archive/restore tools.
- [ ] **Step 2: Add MCP tests** for typed request/response mapping, timeout behavior, and secret-free errors.
- [ ] **Step 3: Implement the overlay/bootstrap and MCP mappings**, update `docs/deployment/hermes-railway.md` with those exact names, then run:

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_atlas_backend_mcp.py tests/test_agent_control_crm.py tests/test_hermes_overlay.py
```

- [ ] **Step 4: After deploying the intended commit, inspect the live `atlas-agent` runtime rather than accepting a local registry test:**

```bash
RAILWAY_SWEENEY_ENV_FILE=/Users/rishabnandi/brandon-real-estate/.env.railway-sweeney.local \
  scripts/railway-sweeney ssh --service atlas-agent --environment production -- \
  hermes mcp tools list atlas_backend --json
```

Capture the deployment ID/commit and machine-readable `tools/list` output. Assert the six enabled names are present exactly once and every disabled trusted-write name is absent. If Railway SSH still reports MEMBER permission required, stop the rollout and obtain project-member access; a local bridge call, backend `/actions`, or source inspection does not satisfy this gate.
- [ ] **Step 5: Commit:** `feat: expose CRM review tools to Hermes`.

## Task 9: Wire worker jobs and verify the end-to-end intake loop

**Files:** Complete `backend/workers/jobs/gmail_history.py`, `backend/workers/jobs/gmail_receipts.py`, `backend/workers/jobs/sydney_questions.py`, `backend/workers/jobs/integration_alerts.py`, `backend/tests/test_gmail_task_intake_e2e.py`, deployment docs, `tdtn.md`, and `memory.md`.

- [ ] **Step 1: Write deterministic end-to-end tests** covering three independent workflows:

```text
controlled received message -> one receipt -> one review suggestion -> authenticated approval -> one task
controlled sent commitment -> persisted Agent Control origin + one receipt -> one review suggestion -> one task
direct Sydney draft -> same evaluator -> one clarification -> answer -> final preview/Command link -> one task
```

Also cover one received request plus Sydney-sent commitment in the same Gmail thread reconciling to one suggestion/task with two source links. Replaying History, origin enqueue, Telegram delivery, answer, nonce, approval, or task creation must not add a duplicate.
- [ ] **Step 2: Wire job schedules** for history polling, receipt processing, Sydney questions, and integration alerts. Use deterministic job keys and leased claims.
- [ ] **Step 3: Run focused backend and frontend suites**, then the full backend/frontend suites.
- [ ] **Step 4: Run the deployment preflight:** intended backend/worker/Hermes commit and deployment IDs; backend `/health`; worker `/health` and `/ready`; single Alembic head `84d7a5f9b2c3`; OAuth profile/current History access; Telegram `getMe`; configured chat/user allowlists; protected Gmail status; and the live deployed `tools/list` gate from Task 8.
- [ ] **Step 5: Run controlled production E2Es with unique fixture IDs and Brandon's explicit approval.** Send one controlled received email into the mailbox, one controlled Agent Control sent commitment, and one direct Sydney draft. For each, record Gmail message/thread IDs, receipt/suggestion IDs, source counts, clarification/outbox/Telegram message IDs where applicable, final preview hash, nonce consumption, task ID, and audit ID. Query counts before/after and replay each input to prove exactly one task. Do not use a client conversation or enable autonomous creation.
- [ ] **Step 6: Update deployment docs, `tdtn.md`, and `memory.md`** with exact environment variables, Railway worker command and both probes, enable/disable switches, final-page cursor/reseed/backfill runbook, Telegram uncertain-delivery reconciliation, live `tools/list` evidence, rollback, and remaining blockers.
- [ ] **Step 7: Commit:** `docs: document Gmail Sydney task intake`.

## Rollout Gate

Keep `GMAIL_TASK_INTAKE_ENABLED=false`, `SYDNEY_TASK_QUESTIONS_ENABLED=false`, and confirmed Hermes writes absent until migrations, worker `/health` and `/ready`, live OAuth History access, Telegram chat/user allowlists, live deployed `tools/list`, review UI, final-page cursor recovery, transactional write-audit rollback, and all controlled received/sent/direct-draft idempotency evidence are green. Enable Gmail in shadow mode first, then review suggestions, then Sydney questions; final creation remains authenticated Command-approved.
