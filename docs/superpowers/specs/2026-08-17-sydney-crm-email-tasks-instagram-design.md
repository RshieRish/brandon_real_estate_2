# Sydney CRM, Email Task Intake, and Instagram Reliability Design

**Date:** 2026-08-17
**Author:** Brainstormed with Codex
**Scope:** FastAPI, Command CRM, Sydney/Hermes, Gmail, Telegram, Instagram, Railway, and the public Next.js homepage
**Status:** Approved for implementation planning

---

## Problem

Four related operational gaps are visible today:

1. The homepage Instagram connection silently falls back to authored images when the Graph API request fails. The replacement token supplied on 2026-08-17 was already expired, and the existing token is invalid. A token cannot truthfully be made impossible to revoke, but the integration can use the most durable supported token type, detect failures, retain the last known-good feed, and alert before visitors see a silent failure.
2. Command tasks and most other CRM records cannot be removed from active workspaces. The few existing delete endpoints permanently delete child records, while top-level records have no consistent reversible lifecycle or actor audit.
3. Sydney is healthy and can use Google Workspace through the controlled backend bridge, but the bridge exposes no CRM task tools. Sydney therefore cannot read, suggest, create, archive, or restore CRM tasks.
4. Gmail can be searched manually, but received and sent messages are not processed into durable task suggestions. There is no restart-safe cursor, deduplication, review queue, source provenance, or clarification conversation.

These gaps should be solved as one controlled workflow: email creates a reviewable suggestion, Sydney asks Brandon for only genuinely required missing information, Brandon approves or edits it, and the shared CRM service creates one auditable task. Instagram reliability is delivered alongside that work but remains an independent integration boundary.

## Goals

- Restore the real Instagram feed using a fresh valid long-lived Page access token without placing that token in browser code, URLs, logs, source control, or Vercel.
- Detect Instagram authentication and data failures, serve the last known-good media during transient outages, and expose operational health to administrators.
- Give Command tasks a reversible, auditable Archive and Restore lifecycle.
- Add safe, entity-specific removal actions across the CRM instead of applying a generic hard delete.
- Give Sydney narrow CRM task capabilities through the existing agent-control boundary rather than database credentials or an admin session.
- Process both received and sent Gmail messages automatically and idempotently into task suggestions.
- Require review before a suggestion becomes a CRM task.
- Make Sydney ask a concise follow-up whenever a task cannot be created correctly without missing or ambiguous information.
- Preserve enough source evidence to explain every suggestion and task without retaining full email bodies unnecessarily.

## Non-goals

- No promise that a Meta credential can literally never expire or be revoked.
- No automatic email replies, client messages, calendar invites, contact creation, or other external side effects.
- No automatic task creation from model output without Brandon's approval during the initial rollout.
- No full-mailbox historical import on first enablement.
- No generic hard-delete endpoint for contacts, tasks, opportunities, agreements, listings, referrals, Smart Plans, or goals.
- No direct Hermes database access, Command admin JWT, Railway database URL, or unrestricted backend action endpoint.
- No attempt to treat email text as authoritative CRM identity data when contact matching is ambiguous.

## Verified Current State

The design starts from the production-aligned `origin/main` snapshot verified on 2026-08-17.

- The public Next.js page reads `INSTAGRAM_ACCOUNT_ID` and `INSTAGRAM_ACCESS_TOKEN`, calls Graph API `v19.0` with the token in the query string, catches every failure, and passes an empty list to a component that silently renders five local frames.
- The existing and replacement Instagram tokens both fail live Graph validation. The replacement token reports OAuth subcode `463`, meaning it is expired. It must not be deployed.
- Command exposes task list, create, and update routes. Task workflow status is `open`, `in_progress`, `completed`, or `cancelled`; there is no archive field or task deletion route.
- Existing permanent-delete routes are limited to scoped child records such as notes, saved searches, and tag assignments.
- Sydney is the active Telegram identity for the `atlas-agent` Hermes service. Hermes and the production FastAPI service are healthy.
- The agent-control API exposes fifteen allowlisted Workspace and operational actions. Gmail inbox and sent searches work, but there are no CRM actions and no continuous Gmail intake.
- The backend already owns Google Workspace OAuth tokens, Gmail reads, Gemini configuration, CRM models, authentication, and audit primitives. Those boundaries should be reused.

## Decisions Locked During Brainstorming

| Decision | Choice |
|---|---|
| Email behavior | Automatically generate reviewable suggestions from both received and sent mail. |
| Creation authority | A human approval is required before creating a task in the initial rollout. |
| Clarification | Sydney asks the minimum necessary question when required information is missing or ambiguous. |
| Conversation continuity | Sydney retains a durable pending clarification and resumes the same suggestion after Brandon answers. |
| Unanswered questions | Send one reminder at 24 hours, time out/release the chat slot at 48 hours, and keep the suggestion in Command. |
| Task removal | Archive and Restore, not hard delete. |
| Other CRM removal | Use entity-specific lifecycle actions with immutable audit. |
| Agent access | Extend the narrow agent-control API and MCP bridge; never share an admin JWT or database credentials. |
| Gmail ingestion | Start with a dedicated, restart-safe Gmail History worker. Pub/Sub may later wake the same processor but is not required for the first reliable release. |
| Instagram fetch | Move it into FastAPI, use an authorization header, cache the last good response, and let the frontend call the backend. |
| Token storage | Railway secret variables only. The browser, rendered HTML, frontend build logs, database, and source code never contain the token. |
| Initial task ownership | Every applied task is implicitly Brandon-owned; no owner field or alternate assignee is introduced in this slice. |
| Approval handoff | A Telegram/agent link uses a one-time handoff nonce; authenticated Command exchange issues a separate one-time approval nonce, and opening the link never approves. |

## System Architecture

```text
Gmail API
  users.history.list
          |
          v
integration-worker on Railway
  receipt + dedupe -> structured Gemini extraction
          |
          v
crm_task_suggestions ----> Command review queue
          |
          +---- needs clarification ----> Sydney outbox
                                              |
                                              v
                                 integration-worker dispatcher
                                              |
                                              v
                                   Sydney bot -> Brandon on Telegram
                                              |
                                              v
                                  Hermes receives Brandon's answer
                                              |
                                              v
                               agent-control clarification answer
                                              |
                                              v
                                   same suggestion is resumed

approved suggestion or approved Sydney draft
          |
          v
shared CRM task service -> crm_tasks + source link + lifecycle audit

Instagram Graph API
          |
          v
FastAPI Instagram service -> persisted last-good cache + health state
          |
          v
public feed endpoint -> Next.js InstagramFeed
```

The FastAPI backend remains the owner of API credentials, validation, persistence, deduplication, task writes, and audit. Hermes remains a conversation and orchestration client. Next.js remains UI only.

## Shared CRM Task Service

Task creation currently happens directly in the Command router. Introduce a shared service so Command, approved email suggestions, and confirmed Sydney requests use the same rules.

Suggested module:

```text
backend/services/crm_task_service.py
```

The service accepts a typed command containing:

- `title`
- optional `description`, `priority`, `due_at`, and `contact_id`
- `actor_type`: `admin`, `sydney`, or `system`
- `actor_id`
- `source_type`: `command_ui`, `gmail_message`, or `sydney_chat`
- `source_id`
- `idempotency_key`
- no owner or linked-record fields; Brandon is the implicit owner and only an optional uniquely resolved `contact_id` is applied

It must:

1. Validate the optional contact. The initial create command does not atomically add opportunity, listing, or agreement links.
2. Normalize timestamps to UTC while preserving the user's timezone interpretation in audit metadata.
3. Enforce uniqueness on the idempotency key before inserting.
4. Create the task, contact activity when applicable, provenance link, and lifecycle event in one database transaction.
5. Return the existing task for an exact idempotent replay.
6. Reject a reused idempotency key whose normalized payload differs.

Persist this contract in `crm_task_creation_requests`, not only in application memory. Each row contains an idempotency scope/key, normalized payload hash, actor/source, state, resulting task ID, failure category, and timestamps. `(scope, idempotency_key)` is unique. The creation request, task, provenance, contact activity, lifecycle event, and write audit commit together; a payload mismatch or audit failure rolls the transaction back.

No route or agent tool may bypass this service after cutover.

The first Gmail/Sydney slice applies only the existing `CreateTaskCommand` shape: title, description, priority, due time, optional uniquely resolved `contact_id`, and `status=open`. If evidence clearly assigns the work to someone other than Brandon, the suggestion stays `pending_review` with blocker `unsupported_owner`. If ownership is ambiguous, Sydney may ask once whether this should be Brandon's follow-up; a non-Brandon answer returns it to that blocker. A requested non-contact task link stays `pending_review` with blocker `unsupported_link`. Command may resolve either blocker only through a versioned, audited choice to make it Brandon-owned or create without the unsupported link, or dismiss it. Approval is disabled while either blocker remains; the system never fabricates an owner or link.

## CRM Removal and Lifecycle Design

### Task archive model

Archiving is visibility state, not workflow status. Keep the current task status values and add:

- `archived_at: datetime | null`
- `archived_by_type: string | null`
- `archived_by_id: string | null`
- `archive_reason: string | null`
- `version: integer`, non-null and incremented by every task mutation

This avoids converting a completed, cancelled, or in-progress task into a misleading workflow state. Restore clears the archive fields and reveals the task with its prior status unchanged.

The migration must reconcile the current split vocabulary before enforcing queries. Normalized rows whose legacy `status` is already `archived` become archived rows with `archived_at` derived from the best available timestamp, a migration actor/reason, and workflow `status=open` as the documented restore fallback because no earlier workflow status exists. Source-only recovered task occurrences remain immutable evidence and continue to contribute to recovered-data counts; they are not silently converted into mutable tasks. Preflight and post-migration counts must prove that no normalized or source-only row disappeared.

All task projections use one grouping contract after migration:

- active: non-archived `open` and `in_progress` tasks;
- completed: non-archived `completed` tasks;
- cancelled: non-archived `cancelled` tasks, never counted as open;
- archived: every normalized task with `archived_at`, regardless of preserved workflow status;
- recovered archive evidence: immutable source-only occurrences, counted and labeled separately from mutable archived tasks.

The contact workspace may show a combined archived total only if it also returns the mutable and recovered subtotals. Recovered entries render a `Recovered evidence` label and no Restore control. Task, contact, overview, and report services must all use this contract before the archive feature flag is enabled.

Every archive and restore writes an immutable generic lifecycle event:

```text
crm_record_lifecycle_events
  id
  entity_type
  entity_id
  action
  actor_type
  actor_id
  source_type
  source_id
  request_id
  metadata_json
  created_at
```

`request_id` is a required UUID, never null. `(entity_type, entity_id, action, request_id)` is unique so a retried request cannot duplicate an event.

### Lifecycle matrix

| CRM record | Active-workspace removal | Recovery | Permanent delete |
|---|---|---|---|
| Task | Archive | Restore with prior status | Never through normal UI |
| Contact | Archive in a later slice; hide from default directory but retain relationships | Restore | Never while any provenance or relationship exists |
| Smart Plan | Existing `archived` lifecycle | Reactivate | No |
| Opportunity | Mark `lost` or `closed` with reason | Reopen to an allowed pipeline stage | No |
| Listing | Mark `withdrawn` | Restore to an allowed nonterminal status | No |
| Agreement | Void or expire according to the existing forward-only state machine | No state rollback; create a new agreement if needed | No |
| Referral | Mark closed/lost through its validated lifecycle | Reopen where allowed | No |
| Goal | Archive in a later slice | Restore | No |
| Note | Existing scoped permanent removal may remain, with confirmation and immutable removal activity | No | Yes, only within contact scope |
| Saved search | Existing scoped permanent removal may remain, with confirmation | No | Yes |
| Contact tag assignment | Existing scoped removal may remain; the tag definition is retained | Reassign | Assignment only |
| Imported/archive evidence | Never removed from application workflows | Not applicable | No |

The first implementation slice completes Task Archive and Restore. Follow-up slices add the listed lifecycle action to each top-level workspace; they must not expose one generic `DELETE /records/{type}/{id}` route.

### Child and relationship inventory

The phrase “other CRM things” includes every record visibly manageable from Command, not only the top-level matrix. These actions are part of the delivery program and must be completed entity by entity:

| Visible record | Removal action | Recovery and evidence rule |
|---|---|---|
| Task link | Unlink with confirmation | Relink; write lifecycle audit |
| Contact address/method/profile value | Clear through validated edit | Previous value remains in bounded audit, not active profile |
| Tag definition | Archive and hide from picker | Restore; existing assignments remain traceable |
| Contact tag assignment | Unassign | Reassign; immutable removal activity |
| Smart Plan step | Disable; a never-run draft step may be permanently removed after confirmation | Re-enable; executed-step evidence is never deleted |
| Smart Plan enrollment | Pause, complete, or cancel | Resume only where lifecycle permits; never delete history |
| Opportunity contact/vendor relation | Unlink | Relink; immutable relationship event |
| Opportunity offer | Withdraw | No destructive delete after capture; preserve financial evidence |
| Agreement template | Archive | Restore |
| Agreement recipient | Remove only while the agreement is an unshared draft | Preserve recipient/event evidence after sharing |
| Agreement file | Supersede or mark withdrawn | Keep private bytes and audit; no normal hard delete |
| Agreement event | No removal | Immutable |
| Note | Existing scoped delete with explicit confirmation | Preserve removal activity, not note body |
| Saved search | Existing scoped delete with explicit confirmation | No recovery; audit the action |
| Imported source record/archive artifact | No removal | Immutable provenance |

Every listed UI action needs its own typed route, permission check, confirmation copy, success/error/uncertain state, audit rule, and recovery behavior. Phase 5 is complete only when this inventory and the top-level matrix have been reconciled against the actual Command navigation and API surface.

### Task API

Admin Command routes:

- `GET /api/v1/command/tasks?visibility=active|archived|all`
- `POST /api/v1/command/tasks/{task_id}/archive`
- `POST /api/v1/command/tasks/{task_id}/restore`

Archive and Restore accept a strict body containing required `request_id: UUID`, required `expected_version: int`, and optional bounded reason. Every task response includes `version`. The mutation uses an atomic `WHERE id=:id AND version=:expected_version` update and increments the version. An exact replay of the same request ID/action/payload returns the recorded result without another event. Reusing a request ID with a different payload returns `409`; a stale expected version also returns `409` with the current version/state. Archiving an already archived task or restoring an active task is otherwise an idempotent no-op with an explicit result.

Overview, report, contact-summary, due-date, and open-task queries must default to `archived_at IS NULL`. Archived counts are reported separately where a workspace needs them. An archived task cannot be edited, completed, or linked until restored.

### Task UI

The Tasks workspace adds:

- an accessible row/card action menu with Archive or Restore;
- a confirmation dialog that names the task and explains that archive is reversible;
- Active and Archived filters;
- loading, success, error, and uncertain-write reconciliation states;
- a short Undo action after a confirmed archive response;
- no browser-native prompt or confirm call.

An archive response updates UI state only after the server acknowledges it. If the response is uncertain, the client refetches the record before enabling a retry.

## Gmail Intake and Task Suggestions

### Worker topology

Run one dedicated `integration-worker` Railway service from the backend image, for example:

```text
python -m workers.integration_worker
```

Do not run the polling loop inside every Uvicorn process. The worker hosts independently feature-flagged Gmail intake and Instagram health jobs. Gmail polls at a configurable interval, initially two minutes. Advisory contract `v1` hashes exact account bytes `b"sws:gmail-task-intake:advisory:v1:account\x00" + account_uuid.bytes`; thread bytes are `b"sws:gmail-task-intake:advisory:v1:thread\x00" + account_uuid.bytes + len(thread_ascii).to_bytes(2, "big") + thread_ascii`. Take SHA-256's first eight bytes big-endian unsigned and subtract `2**64` when the high bit is set for PostgreSQL signed bigint. Fixed vectors for account `00000000-0000-0000-0000-000000000001` are `848794804012879307` for the account and `-7678506188538908948` for thread `thread-123`. Tests pin domain/version, UUID byte order, ASCII length framing, signed conversion, vectors, and `PYTHONHASHSEED` independence. All rolling workers stay on `v1`; a future version acquires old/new keys in sorted numeric order during an explicit dual-lock drain rollout. The session account lock is held on one dedicated PostgreSQL connection across every provider page and final cursor compare-and-set and released in `finally`; failure to acquire skips that account. Only one lease-holder advances a mailbox cursor.

The current web Docker/Railway configuration cannot be reused unchanged because it hardcodes Uvicorn and an HTTP health check. Add a worker-specific target:

- `backend/Dockerfile.worker` shares the pinned backend dependencies but starts `python -m workers.integration_worker`;
- `backend/railway.integration-worker.json` selects that Dockerfile and `/health` as its Railway health path;
- the worker module runs a minimal internal ASGI health server on Railway's `$PORT` alongside the job loops;
- `/health` is liveness only and returns exactly `{"status":"ok","service":"integration-worker"}` without touching PostgreSQL, Alembic, providers, or job configuration;
- `/ready` returns exactly `{"status":"ready","service":"integration-worker","database":"ok","migration":"ok","heartbeat":"ok","job_registry":"ok"}` only when read-only checks find PostgreSQL reachable, the expected single Alembic head, a fresh scheduler-owned boot/heartbeat, and an already-initialized valid non-secret registry; it never inserts, updates, flushes, or refreshes heartbeat state; otherwise it returns 503 with bounded component names;
- health output contains no mailbox identity, token, subject, recipient, or provider credential.

Railway's only restart health path is `/health`; `/ready` is a post-deploy promotion check. `backend/Dockerfile.worker` has no Docker `HEALTHCHECK` and installs or calls neither curl nor wget. A repo-owned Python standard-library probe checks `/ready`, so health verification does not depend on a binary absent from the backend image.

The scheduler owns boot/heartbeat writes after registry initialization. The worker supervises exactly the scheduler and ASGI server with `asyncio.wait(..., return_when=FIRST_COMPLETED)`. Any error or unexpected normal return sets server shutdown, cancels and awaits the peer, and raises so Railway restarts; a `TaskGroup` is not treated as a run-forever supervisor.

The Google Workspace/Gmail, Gemini, and current Telegram clients are synchronous. Their calls run only in dedicated bounded executors with provider socket/request timeouts and outer hard job deadlines. A timed-out future is tracked, and the same account/thread/outbox job cannot overlap it. Executor saturation degrades protected provider status but cannot occupy the scheduler/ASGI event loop; a stalled-provider test must prove `/health` and the read-only `/ready` remain responsive.

The worker service has its own restart policy and deployment verification. A successful web backend deployment is not evidence that the worker is healthy.

On first enablement, store Gmail's current `historyId` and do not scan historical mail. An authenticated admin can request an explicit bounded backfill, initially capped at seven days. If Gmail reports that the cursor is too old, record a blocked health state, reseed from the current profile cursor, and require an explicit bounded backfill rather than silently replaying the mailbox.

History discovery and content extraction are separate durable stages. A `gmail_sync_runs` row records the committed start cursor, terminal History ID, next page token, and run state; `gmail_sync_page_checkpoints` persists each page. For every History page, one transaction upserts each discovered message ID as a pending receipt and checkpoints the next page token. Only the final-page transaction marks the run complete and advances `gmail_sync_accounts.committed_history_id`. A crash resumes the page or run; it cannot advance past an undiscovered message. A separate consumer claims pending receipts, refetches message content when needed, extracts suggestions, and records success/failure without moving the mailbox cursor.

Before any receipt mutates obligations, suggestions, suppressions, or source links, its transaction takes `pg_advisory_xact_lock` on a stable SHA-256-derived signed 64-bit key for `(account_id, gmail_thread_id)`. Same-thread receipts therefore serialize across workers while different threads remain parallel. Python's randomized `hash()` is forbidden for both advisory key families.

Migration, advisory-lock, cursor, lease, and end-to-end tests run against independent connections to a real disposable PostgreSQL 16 database. The guard requires both `GMAIL_TASK_TEST_DATABASE_NAME` and `GMAIL_TASK_TEST_DATABASE_URL`, requires the configured and parsed database names to be exactly equal and end in `_test`, requires a PostgreSQL driver, and fails rather than skips when `CI=true`. Destructive setup/cleanup uses explicit fail-closed checks, never Python assertions, and requires the exact owned marker tuple `(total_rows, matching_run_rows) == (1, 1)` even under `python -O`. A dedicated scoped GitHub workflow starts and removes an exact TLS-enabled PostgreSQL container; SQLite and parse-only DDL do not satisfy this contract. The existing CRM lifecycle migration workflow is updated before revision `82` so its exact revision-81 tests remain valid while `81` is an ancestor of the sole serial head `82`, then `83`, then `84`.

### Direction and eligibility

For each changed message:

1. Fetch label and header metadata.
2. Treat `SENT` as outbound and `INBOX` as inbound.
3. When labels are unusual or both are present, compare normalized From/To addresses with the authenticated mailbox identity.
4. Ignore drafts, spam, trash, automated delivery notices, list mail, calendar noise, and messages carrying durable origin metadata that classifies them as internal operational automation.
5. Fetch and temporarily decode the plain-text body only for eligible candidates.
6. Cap body input and strip quoted thread history, signatures, tracking URLs, and unsafe HTML.
7. Discard raw body text after structured extraction. Do not persist it in logs, receipts, model traces, or audit metadata.

Received messages are candidates when they request, promise, schedule, defer, or require an action. Sent messages are candidates when Brandon commits to a follow-up, requests a response by a time, promises a deliverable, or delegates an action. Informational messages produce a non-actionable receipt, not a suggestion.

Client-facing email sent through Sydney remains eligible. Every agent-control send requires a caller-generated UUID `request_id` and permits optional UUID `retry_of_request_id`; `confirmed_by_brandon` alone is never an idempotency key. Before any provider call, the route commits a `gmail_message_origins` pre-send intent keyed by `(account_id, request_id)` with a canonical send hash excluding both UUIDs, canonical envelope/body hash, optional unique predecessor FK, `origin_kind=sydney_client_send`, and `delivery_state=sending`, plus a same-transaction fail-closed action audit. The partial unique gate on `(account_id, canonical_send_hash)` uses exact PostgreSQL `delivery_state IN ('sending', 'delivery_uncertain') AND reconciled_outcome IS DISTINCT FROM 'not_delivered'`; bare `!=`/`<>` is forbidden because NULL would evade the predicate. The Gmail transport uses zero automatic retries. Known success fills provider IDs, succeeds, and enqueues. Timeout/crash/unknown/persistence failure becomes uncertain; neither unresolved state may call Gmail again.

A new UUID with the same canonical payload is rejected before Gmail while its predecessor is unresolved, whether or not it falsely names that predecessor. Only authenticated `not_delivered` reconciliation releases the gate, and exactly one successor must explicitly bind `retry_of_request_id` to that same-account/same-hash predecessor. Missing, mismatched, unresolved, delivered, or already-used predecessor fails closed. A real two-session barrier test simultaneously inserts first intents with distinct UUIDs, identical account/hash, and NULL outcomes and proves one commit/provider call. Further tests prove fresh-UUID rejection, acceptance only after `not_delivered`, and one provider call under racing successors.

The only persisted origin values are `sydney_client_send`, `human_send`, and `system_automation`. A sent message first observed through History without an app intent gets a `human_send` origin already in `succeeded`. `sydney_client_send` enters normal sent-mail extraction and thread reconciliation; only `system_automation` is suppressed. The later History event uses the same successful origin and receipt key.

### Durable data model

`gmail_sync_accounts`

- one row per Workspace account;
- mailbox identity, committed History cursor, reseed candidate, mode, blocked reason, last success, and bounded last error;
- never stores OAuth token material.

`gmail_sync_runs` and `gmail_sync_page_checkpoints`

- one resumable poll/backfill run plus unique ordered page checkpoints;
- page commits never advance `gmail_sync_accounts.committed_history_id`; only the terminal-page compare-and-set does.

`gmail_message_origins`

- represents app/agent pre-send intents and History-inferred human sent-message origins for one account;
- for agent/API sends, records required UUID request ID, canonical send hash excluding request/retry UUIDs, canonical envelope/body hash, optional unique self-FK predecessor, positive row version, originating audit, exact state `sending`, `succeeded`, or `delivery_uncertain`, and origin `sydney_client_send` or `system_automation` before the call;
- partial uniqueness on unresolved `(account_id, canonical_send_hash)` uses exact NULL-safe `delivery_state IN ('sending', 'delivery_uncertain') AND reconciled_outcome IS DISTINCT FROM 'not_delivered'`, blocks fresh-UUID bypass until authenticated `not_delivered`, and permits at most one predecessor-bound successor;
- provider message/thread IDs are nullable until known success; only `(account_id, gmail_message_id)` is unique when present, while `gmail_thread_id` is nonunique and indexed because a thread has many messages; History-inferred `human_send` rows are created already succeeded without a caller request ID;
- contains no body and no retry loop.

`gmail_message_receipts`

- Workspace account ID, Gmail message ID, thread ID, direction, received/sent timestamp, normalized participant hashes, subject preview, content hash, classification, and processing timestamps;
- unique on `(workspace_account_id, gmail_message_id)` with a separate nonunique `(workspace_account_id, gmail_thread_id)` lookup index;
- stores no full raw body.

`crm_task_suggestions`

- structured title, description, priority, due time, matched contact, confidence, rationale, state, model/schema version, idempotency key, and resulting task ID;
- states: `needs_clarification`, `possible_duplicate`, `pending_review`, `approved`, `dismissed`, `applied`, or `failed`; a separate clarification state and blocker-code set represent manual review without inventing another top-level state;
- zero, one, or many suggestions may belong to a receipt;
- unique source key based on mailbox, message ID, stable normalized action key, and model schema version, so one email can yield two distinct tasks while reprocessing cannot duplicate either one;
- an `obligation_fingerprint`, Gmail thread ID, and optional `duplicate_of_suggestion_id` support cross-message reconciliation.

`gmail_extraction_attempts` and `gmail_extracted_obligations`

- bounded versioned extraction attempts and structured obligations with deterministic action/source identity;
- contain only sanitized categories, structured task fields, hashes, and evidence previews, never raw bodies.

`crm_task_suggestion_sources`

- immutable link from suggestion and resulting task to the Gmail receipt;
- includes direction and a minimal user-visible source label;
- unique on `(suggestion_id, obligation_id)`;
- no raw body.

`crm_task_suggestion_suppressions`

- unique `(source_type, source_scope_key, source_action_key, obligation_fingerprint)`, where the source/action identity is version-independent and Gmail scope includes account plus thread;
- the same semantic fingerprint in an unrelated source scope remains eligible and is never globally suppressed;
- only an authenticated audited reprocess can supersede the suppression.

`gmail_backfill_requests`

- authenticated administrator, reason, maximum-seven-day bounds, expired/reseed cursors, audit, and terminal result.

`crm_task_clarifications`

- one active clarification per suggestion and one unresolved clarification per configured Telegram chat, enforced by partial unique constraints;
- stores only opaque code hash, current consequential field, suggestion version, normalized options, round 1 through 5, Telegram delivery correlation, last asked time, one 24-hour reminder time, 48-hour timeout/release, resolved fields, and completion state;
- unique `(suggestion_id, suggestion_version, field_name)` prevents repeating a field on one version;
- does not store the original full email or unrelated chat history.

`sydney_question_outbox`

- one immutable-payload row per `initial`, explicit `initial_retry`, or sole `reminder` attempt, with parent initial ID, deterministic unique dedupe key, claim/attempt/sent times, and exact `pending`, `sending`, `sent`, `failed`, or `delivery_uncertain` state;
- every attempt commits `sending` before `sendMessage`; uncertain is never automatically retried, and a reminder is never replaced or retried.

`crm_task_suggestion_approval_nonces` and `crm_task_suggestion_events`

- both nonce kinds come from Python `secrets.token_urlsafe(32)` (256-bit, never below 128-bit), persist only a unique SHA-256 digest, and reject malformed/short/noncanonical base64url before lookup;
- hash-only nonce rows and immutable suggestion transition events;
- a 15-minute administrator-null `handoff` is consumed by authenticated Command exchange to create a distinct 5-minute administrator-bound `approval` with `issuance_path=handoff_exchange` and a required parent; ordinary authenticated Command prepare instead creates a 5-minute `approval` with `issuance_path=command_prepare` and no parent.

These names supersede the early shorthand `gmail_sync_states`, `gmail_history_runs`, `crm_task_email_sources`, `gmail_obligation_suppressions`, and `sydney_clarification_threads`. No alias tables or legacy origin labels are created. Feature/code rollback leaves schema in place. Revisions `83`/`84` refuse downgrade while any owned durable/evidence/audit row exists; only a separate explicit audited export-and-destructive procedure may empty them first. Tests prove refusal preserves existing CRM and intake evidence and prove downgrade only on empty owned tables.

### Structured extraction

Gemini must return a versioned envelope of zero or more actions, not prose:

```json
{
  "schema_version": "gmail-task-v1",
  "actions": [{
    "action_key": "send-seller-disclosure-jane",
    "title": "Send the seller disclosure to Jane",
    "description": "Requested in the Aug 17 email thread.",
    "priority": "normal",
    "due_at": "2026-08-18T21:00:00Z",
    "timezone_basis": "America/New_York",
    "contact_candidates": [{"contact_id": 42, "confidence": 0.97}],
    "missing": [],
    "evidence": ["request", "explicit_due_date"],
    "confidence": 0.94
  }]
}
```

The backend validates this response and decides the state. Model output never directly writes a task or contact.

### Thread-level obligation reconciliation

Per-message deduplication is necessary but insufficient. A client may request a disclosure in an inbound message and Brandon may reply, `Yes, I will send it Friday`; those two messages are evidence for one obligation, not automatically two tasks.

For replies, the extractor may transiently fetch a bounded number of prior messages from the same Gmail thread to resolve pronouns and commitments. Those bodies follow the same no-persistence rule. The backend calculates a stable obligation fingerprint from normalized intent, object, relevant party/contact, and bounded due-time meaning; the fingerprint does not include the individual Gmail message ID.

Before creating a new suggestion, reconcile it against open suggestions and source-backed tasks in the same mailbox and Gmail thread:

- an exact/high-confidence continuation attaches the new receipt as another source to the existing suggestion or task and updates only still-reviewable evidence;
- a materially different action creates its own suggestion even when the title is similar;
- an uncertain match enters `possible_duplicate` review and is never auto-merged;
- messages in different Gmail threads are never auto-merged solely because their titles match.

This makes `crm_task_suggestion_sources` many-to-one: multiple received and sent obligations can explain one suggestion and resulting task.

### When Sydney must ask

Sydney asks when proceeding would require a consequential guess. The backend, not the conversational model alone, determines that a clarification is required when any of these conditions applies:

- the intended action is ambiguous or more than one materially different task is plausible;
- a deadline is clearly required by the email but the time expression is incomplete, conflicting, or timezone-ambiguous;
- more than one CRM contact is a plausible match and the relationship matters to the task;
- the email delegates among multiple people and it is unclear whether this should be Brandon's follow-up task;
- approval text conflicts with the stored structured suggestion;
- a requested contact cannot be uniquely resolved.

Sydney does not ask merely because an optional field is absent. A clear task may have no contact or due date. Sydney also does not invent a contact, deadline, owner, or external action.

The initial schema cannot represent a non-Brandon assignee or atomically create opportunity/listing/agreement links. An explicit non-Brandon assignment and any requested non-contact link stay `pending_review` with blocker `unsupported_owner` or `unsupported_link`; Sydney does not ask repeated questions that cannot make the payload representable.

The same evaluator applies to `sydney_chat` drafts created from a direct request. A direct request is not allowed to bypass missing-field, duplicate, contact-match, or deadline checks merely because Brandon initiated it conversationally.

### Clarification conversation policy

1. Ask one short, specific question at a time in Brandon's configured Telegram chat. A partial unique constraint prevents a second suggestion's question from owning the chat slot until the current row resolves or times out at 48 hours.
2. Include just enough context to identify the email, using sender/recipient, compact subject, and proposed task title. Never paste the full body unless Brandon explicitly asks Sydney to read the thread.
3. Offer two or three choices only when the backend has real candidates; otherwise ask a direct free-text question.
4. Store the pending field, opaque clarification code, and suggestion ID before delivery. Include the short opaque code in the question without exposing a database ID.
5. The initial Hermes answer tool accepts only opaque code, expected suggestion version, and bounded structured answer. It accepts no caller-provided chat ID, user ID, suggestion ID, owner, or approval claim. The backend verifies the code hash and that the active row has a successful outbound delivery to the configured chat; this prevents cross-suggestion mistakes but is not proof of human identity.
6. Validate and persist the structured answer, close the clarification, increment the same suggestion's version, then reevaluate it. Any independent edit, reprocess, or material source update that changes the version first marks the active clarification `superseded` and releases the chat slot in the same transaction.
7. Ask the next highest-consequence field only if another consequential ambiguity remains. Never repeat `(suggestion_id, suggestion_version, field)` and stop after five rounds; unresolved ambiguity then becomes `manual_review_required` without a sixth question.
8. When complete, show a compact final task preview and ask Brandon to Approve, Edit, or Dismiss.
9. If Brandon does not answer after a known delivered initial/retry, create exactly one immutable reminder outbox attempt due at that attempt's `sent_at + 24 hours`, only when still before the fixed slot deadline. Commit the reminder as `sending` before its call and finish it as `sent`, `failed`, or `delivery_uncertain`; never retry or replace it. The slot deadline never moves: known initial success uses `sent_at + 48 hours`, failed/uncertain initial uses `first_attempt_at + 48 hours`, and never-attempted pending uses `created_at + 48 hours`. Retries/reminders do not extend it. At the deadline, mark the row `timed_out`, release the slot, and leave it in Command.
10. A timed-out/resolved/superseded row, stale suggestion version, replaced field, or old code is a stale late answer: return `409 stale_clarification` and change no draft or chat slot. If an answer cannot be correlated safely in conversation, Sydney names the compact subject and opaque code and asks Brandon to choose; it does not call the tool speculatively.

Examples:

- `Jane asked for the disclosure tomorrow. Should I set this for 9:00 AM or 5:00 PM Eastern?`
- `This could be linked to Jane Miller or Jane Miller-Smith. Which contact should I use?`
- `The email contains two requests. Should I make one task for both, or separate tasks?`

Sydney must never ask the client or any email participant. All clarification goes only to Brandon's approved private channel.

### Review and application

A complete suggestion enters `pending_review`. Command shows the proposal, source direction, compact email identifier, confidence, extracted fields, missing-field state, and audit trail. Brandon can edit structured fields before approving.

Sydney's approval-link action creates a 15-minute hash-only `handoff` bound to suggestion ID, current version, payload hash, and normalized task fields, with no administrator identity. The link is `/admin/command/task-suggestions?suggestion={id}#handoff={opaque}`; a handoff or approval secret is never accepted in the query. A no-store/no-referrer bootstrap synchronously captures and clears the fragment with `history.replaceState` before hydration, telemetry, analytics, fetch/beacon, or any other application network/referrer path, holds it only in ephemeral memory, and never puts it in DOM, logs, or local/session storage. An unauthenticated visitor must sign in and reopen the still-unused link.

Authenticated exchange revalidates/consumes the handoff and creates a distinct 5-minute administrator-bound `approval` with `issuance_path=handoff_exchange` and its parent. Ordinary authenticated Command review uses `POST /api/v1/command/task-suggestions/{suggestion_id}/approval/prepare`, which revalidates expected version/hash, returns the exact preview, and creates a 5-minute administrator-bound `approval` with `issuance_path=command_prepare` and no parent. Both paths require a separate Approve click; prepare/open/exchange never creates a task. Only Approve consumes the nonce in the same transaction as shared-service application/audit. Version/hash changes, wrong administrator, wrong kind/path/parent, expiry, or replay fail closed.

Handoff and approval issuers both use Python `secrets.token_urlsafe(32)`, yielding 32 random bytes (256 bits; never less than 128 bits), and store only unique SHA-256 digests. Consumers validate canonical ASCII base64url and exactly 32 decoded bytes before hashing or repository lookup; malformed, short, or noncanonical input gets the same bounded rejection. Tests pin the generator call/source and decoded length, prove plaintext absence, and force a duplicate generator output to test digest uniqueness/bounded regeneration or fail-closed behavior. They do not infer randomness statistically from generated samples.

The exact approval mutations are `POST /api/v1/command/task-suggestions/{suggestion_id}/approval/prepare`, `POST /api/v1/command/task-suggestions/{suggestion_id}/handoff/exchange`, and `POST /api/v1/command/task-suggestions/{suggestion_id}/approve`. Prepare and exchange issue different approval paths as above. Approve accepts either valid stage-two nonce, expected version/hash, and a required request UUID.

For the initial rollout, final approval occurs in authenticated Command UI through the two-stage handoff link Sydney may present. This is the only current path that proves the approver is an authenticated administrator rather than merely the holder of `AGENT_CONTROL_TOKEN`. Telegram-native approval stays disabled until the Hermes delivery gate below can provide a trusted, server-verifiable channel assertion bound to Brandon's configured Telegram user/chat and inbound update ID.

Authenticated Command dismissal records a reason category and suppresses only the same version-independent source/action identity and obligation fingerprint within its scoped source (for Gmail, account plus thread). It is not a global semantic veto; an unrelated message/thread remains eligible.

Dismissal suppression is independent of extractor/model version but never global by semantic fingerprint. Persist a `crm_task_suggestion_suppressions` row unique on `(source_type, source_scope_key, source_action_key, obligation_fingerprint)`, with dismissal reason, actor, and time. Gmail scope includes account UUID and thread ID; model/schema version and individual message ID are not part of the source/action identity. The same fingerprint in another thread/source remains eligible. Reprocessing does not bypass this ledger; only an explicit authenticated admin Reprocess action can supersede a dismissal, and that override is audited.

When the agent-control Gmail send state reaches `succeeded`, it enqueues the returned Gmail message ID for the same receipt processor. The later Gmail History observation uses the receipt uniqueness key and becomes an idempotent reconciliation, not a second suggestion. History cursor advancement follows the durable scan-run contract: every discovered message is committed as a pending receipt before the final sync cursor advances, while extraction may safely continue afterward.

### Gmail intake health and alerts

Protected admin routes:

- `GET /api/v1/admin/integrations/gmail-task-intake/status`
- `POST /api/v1/admin/integrations/gmail-task-intake/check`
- `POST /api/v1/admin/integrations/gmail-task-intake/reprocess/{receipt_id}`
- `GET /api/v1/admin/integrations/gmail-task-intake/send-intents/{request_id}`
- `POST /api/v1/admin/integrations/gmail-task-intake/send-intents/{request_id}/reconcile`

Status reports only bounded operational data: enabled/shadow/live mode, worker heartbeat age, last poll/success, current cursor state, current History run state, pending/failed receipt counts, oldest pending age, last applied suggestion time, and sanitized error category. It never returns subjects, participants, bodies, OAuth tokens, or raw provider errors.

Send-intent reconciliation is authenticated and never sends. Candidate delivered IDs trigger a transient deadline-bounded Gmail profile/message fetch through the configured account. Success requires matching account identity, exact message, `SENT`, candidate and intended thread, and canonical From/To/Cc/Bcc/subject/body hash. Only then may the origin succeed and enqueue. Wrong account/message/thread/label/envelope/body writes bounded quarantine evidence, remains uncertain, and is ineligible until independent History verification. `not_delivered` requires a bounded reason and expected state/version; only it releases the canonical-hash gate for one new UUID explicitly bound to that old intent.

Configurable thresholds cover maximum worker-heartbeat age, poll age, pending-receipt age, and repeated failed receipts. Revoked Workspace OAuth, expired History cursor, stalled scan, missed worker heartbeat, growing pending backlog, and repeated extraction failures transition a deduplicated health state and enqueue an administrator email through `notification_jobs`. Recovery sends one resolved notification. An authenticated, diagnostics-gated canary may enqueue a synthetic Gmail-intake alert under a separate provider key to prove production alert delivery without corrupting the real cursor or revoking live OAuth.

## Sydney and Hermes CRM Bridge

`backend/main.py` must import and include exactly once `admin_integrations.router`, `command_task_suggestions.router`, and `agent_control_crm.router`. A real-app route-inventory test asserts every documented admin, Command, and `/api/v1/agent-control/crm/*` method/path appears once with unique operation IDs, and unauthenticated smoke requests reach the intended authentication boundary rather than `404`/`405`. Router unit tests without this registration proof do not satisfy delivery.

### Agent-control actions

Add typed actions under `/api/v1/agent-control/crm/*` and advertise them in the existing action registry:

| Action ID | Purpose | Risk tier |
|---|---|---|
| `crm.tasks.read` | Read active or archived task summaries | Read-only |
| `crm.task_suggestions.read` | Read suggestions awaiting clarification or review | Read-only |
| `crm.task_clarifications.answer` | Submit Brandon's structured answer | Human-originated write |
| `crm.task_drafts.create` | Create a reviewable draft from a direct Sydney request | Internal reversible write |
| `crm.task_suggestions.approval_link` | Issue a short-lived Command review link | Read/review handoff |
| `crm.task_suggestions.dismiss_proposal` | Record a bounded review proposal without changing suggestion/suppression state | Untrusted proposal-only write |
| `crm.task_suggestions.approve` | Apply the exact previewed suggestion; disabled for Hermes initially | Trusted-channel confirmed write |
| `crm.tasks.create_confirmed` | Create an explicitly requested manual task; disabled for Hermes initially | Trusted-channel confirmed write |
| `crm.tasks.archive` | Archive a named task; disabled for Hermes initially | Trusted-channel confirmed reversible write |
| `crm.tasks.restore` | Restore an archived task; disabled for Hermes initially | Trusted-channel confirmed reversible write |

Tool descriptions must say exactly which actions require a suggestion version, payload hash, authenticated Command approval, or trusted Telegram channel assertion. A `confirmed_by_brandon` boolean alone is never sufficient. Untrusted Hermes cannot dismiss, suppress, release a clarification, or change a suggestion version; dismiss-proposal only appends an idempotent bounded proposal/event for Command review. Actual dismissal and suppression are authenticated Command-only. Disabled actions remain out of the advertised runtime action registry until their authentication gate is satisfied.

### MCP bridge and Hermes scheduling

Extend `hermes/atlas_backend_mcp.py` without removing or renaming its exact existing 16 tools: `status_read`, `actions_list`, `leads_recent`, `bookings_recent`, `workspace_status`, `drive_search`, `drive_file_read`, `gmail_search`, `gmail_thread_read`, `gmail_draft_create`, `gmail_send`, `docs_create`, `sheets_append`, `calendar_events_read`, `calendar_event_create`, and `contacts_search`. Add exactly six: `crm_tasks_read`, `crm_task_suggestions_read`, `crm_task_clarifications_answer`, `crm_task_drafts_create`, `crm_task_suggestions_approval_link`, and `crm_task_suggestions_dismiss_proposal`. The final registry is exactly 22 unique names; `gmail_send` gains required UUID `request_id`. The bridge continues to hold only `AGENT_CONTROL_TOKEN` and the backend URL.

The deployed Hermes template also has a hardcoded `tools.include` allowlist in its boot overlay. Implementation must update the repo-owned overlay/bootstrap source and `docs/deployment/hermes-railway.md` with the exact enabled CRM tool names, redeploy `atlas-agent`, and then call live MCP `tools/list`. A code-level bridge test or backend action-registry response is not sufficient; production acceptance requires the expected CRM tools to appear in Hermes and every disabled trusted-write tool to remain absent.

Automatic question delivery uses a repo-owned dispatcher inside `integration-worker`, not an assumed Hermes cron callback. The worker holds `SYDNEY_TELEGRAM_BOT_TOKEN` and `SYDNEY_TELEGRAM_BRANDON_CHAT_ID` as Railway secrets and calls Telegram Bot API `sendMessage` only for that configured chat. `SYDNEY_TELEGRAM_BRANDON_USER_ID` may be retained only as future signed-adapter configuration; it grants no authority in the initial flow. The worker never calls `getUpdates`, so Hermes remains the sole inbound long-polling consumer. A successful response supplies the real chat/message IDs, which the worker persists on the clarification row.

Each dispatcher attempt is an immutable outbox row and commits `sending` before the executor-offloaded, deadline-bounded external call. A known initial failure may be retried only after authenticated reconciliation and as a new attempt. Timeout/crash/unknown becomes `delivery_uncertain` and is never auto-retried. The reminder is its own deterministic attempt and is never retried. The partial unique chat constraint holds until resolution or the fixed 48-hour deadline; failed attempts cannot extend it. This is durable intent with fail-closed uncertain delivery, not a false exactly-once claim.

Incoming Telegram answers remain ordinary Sydney conversations handled by Hermes. The model/tool layer cannot provide trustworthy inbound chat, user, update, or reply identity, so the backend treats every answer as `untrusted_hermes_input`. Sydney calls the clarification-answer tool only with the opaque code, expected suggestion version, and bounded answer for the one active row. This bounded write may update a review draft but can never approve or create a task. A direct request such as `add a task to call Jane Friday` first uses `crm.task_drafts.create`; that Brandon-owned draft passes through the same missing-field evaluator, Sydney questions, final preview, and authenticated Command approval path as an email suggestion.

Telegram-native final approval is a later gated enhancement. It may be enabled only if a verified Hermes channel hook exposes trustworthy inbound chat ID, user ID, and update/message ID outside model-supplied arguments. A repo-owned adapter must sign that context with a key distinct from `AGENT_CONTROL_TOKEN`; the backend verifies the signature, allowlist, one-time inbound update ID, suggestion version, nonce, and payload hash. If Hermes cannot provide that contract, Command remains the final approval surface permanently.

Every accepted and rejected agent-control call writes an audit row without secrets, email bodies, or task descriptions beyond a bounded sanitized summary. Existing best-effort audit behavior may remain for read-only calls. Every write-capable call must persist its audit in the same transaction as the state change and fail closed if that audit cannot be written.

## Instagram Reliability Design

### Credential lifecycle

The user-supplied replacement token is exposed and expired, so it is invalid deployment input. Before cutover, generate a fresh supported long-lived Page access token for the correct Facebook Page and connected Instagram professional account. Verify it against the exact media endpoint and account ID before storing it.

Store only these secret/config values in the production FastAPI Railway service:

- `INSTAGRAM_ACCOUNT_ID`
- `INSTAGRAM_ACCESS_TOKEN`
- `INSTAGRAM_GRAPH_API_VERSION`, set to a currently supported pinned version during implementation
- `INSTAGRAM_GRAPH_API_SUNSET_AT`, verified from Meta's official version schedule with the pinned version
- `INSTAGRAM_FEED_LIMIT`
- `INSTAGRAM_CACHE_MAX_STALE_SECONDS`

The implementation must verify the currently supported Graph version from Meta's official documentation at build time rather than copying the existing `v19.0` value. CI fails when the configured sunset is missing, in the past, or within the defined release safety window. The integration worker alerts at 90, 60, 30, and 7 days before sunset so a token-valid connection is not stranded by API-version retirement. Token rotation is an operational procedure, not a code change.

After backend cutover and verification, remove the Instagram token and account ID from the frontend Vercel project. Deployment must use the Sold With Sweeney Vercel team/project; the unrelated locally authenticated Vercel account must not be modified.

### Backend service and cache

Suggested modules:

```text
backend/services/instagram_service.py
backend/routers/instagram.py
```

The service calls Graph API with `Authorization: Bearer ...`, a strict timeout, bounded retry only for transient network/5xx/429 failures, and a supported pinned version. It normalizes only the fields the homepage needs:

- media ID;
- caption preview;
- media type;
- media or thumbnail URL;
- permalink;
- published timestamp when available.

Persist the normalized last-good response and operational state in dedicated rows. Never persist the credential.

`instagram_feed_cache` stores the normalized JSON, fetch time, content hash, and expiry time.

`integration_health_states` stores provider, state, last success, last check, last error category, bounded sanitized error message, consecutive failures, and alert timestamp.

Authentication failures are not retried in a loop. They set `reauthorization_required`. Rate limits honor server retry guidance. Transient failures return a still-valid or policy-bounded stale last-good cache. If no real cache exists, the API returns an explicit unavailable state; the authored fallback may render but must be labeled in admin health as fallback, never reported as a working Instagram connection.

### API and frontend

Public:

- `GET /api/v1/instagram/feed`

Protected admin:

- `GET /api/v1/admin/integrations/instagram/status`
- `POST /api/v1/admin/integrations/instagram/check`

The public response is always a typed content response and includes `items`, `source` (`live`, `stale_cache`, or `unavailable`), `fetched_at`, and `degraded`. When there is no usable cache, it returns HTTP 200 with `source="unavailable"`, `items=[]`, `fetched_at=null`, and `degraded=true` so the public page can render authored fallback without confusing content availability with integration health. It never includes provider errors or secrets. The protected admin status/check routes use non-2xx status for a failed explicit check and include the sanitized health state and whether reauthorization is required.

Next.js fetches the public backend route with timed revalidation and passes the normalized items to `InstagramFeed`. It no longer calls Graph API directly. If the backend is unavailable, the component may render the authored visual fallback, while instrumentation records that fallback state.

The `integration-worker` runs the daily Instagram check under a PostgreSQL advisory lock even when the homepage has low traffic. Authentication invalidation alerts once on the state transition and again only at the configured reminder interval. Version-sunset alerts follow the schedule above. All alerts use the existing durable `notification_jobs` queue to Brandon's configured administrator email; they do not depend on Sydney delivery and never include the token or raw Graph request URL.

## Security, Privacy, and Data Integrity

- Treat the pasted Instagram credential as compromised. Do not copy it into source, docs, shell history, logs, tests, Railway, or Vercel.
- OAuth and Page tokens remain server-side secrets. Redact bearer headers and query strings at logging boundaries.
- Gmail OAuth remains owned by the Workspace service. Hermes does not receive refresh tokens.
- Email bodies are transient processing input. Persist content hashes, bounded subject previews, structured task fields, and minimal source metadata only.
- Hash participant addresses in receipts; keep a plaintext address only where an existing CRM contact relationship already authorizes it.
- Ignore prompt-like instructions inside emails. Email is untrusted source content, not authority to call tools or change system rules.
- All suggestion state changes use optimistic concurrency through a version number.
- All creation, archive, restore, approval, dismissal, clarification, and delivery actions are idempotent and audited.
- Database migrations are additive and reversible before destructive cleanup. No existing records are dropped.
- Agent write actions fail closed when the agent-control token, approver binding, suggestion version, or payload hash is missing.

## Failure Handling

| Failure | Required behavior |
|---|---|
| Expired/revoked Instagram token | Mark reauthorization required, alert once, serve policy-bounded last-good cache, never claim live health. |
| Instagram timeout/5xx/429 | Bounded retry, retain last-good cache, record degraded health. |
| Gmail history cursor expired | Stop advancement, record blocked state, reseed current cursor, require bounded explicit backfill. |
| Workspace OAuth revoked or worker/backlog stalled | Mark Gmail intake unhealthy, stop unsafe advancement, and enqueue one deduplicated administrator alert. |
| Worker crash during History pagination | Resume the durable run/page checkpoint; the committed sync cursor never skips undiscovered messages. |
| Worker crash after receipt insert | Resume extraction from durable pending receipt state; unique constraints prevent duplicate suggestion. |
| Agent Gmail send timeout/crash/unknown result | Preserve `sending` or mark `delivery_uncertain`; never auto-resend, and require authenticated not-delivered reconciliation plus a new UUID. |
| Gemini invalid output | Record failed extraction safely; retry with bounded count; surface for review without creating a task. |
| Ambiguous task | Create one pending clarification; Sydney asks rather than guessing. |
| No answer from Brandon | One reminder at 24 hours; time out and release the one-chat slot at 48 hours, then leave in review queue. |
| Late or superseded clarification answer | Return `409 stale_clarification`; do not mutate the suggestion or claim a new chat slot. |
| More than five consequential questions | Stop delivery and mark manual review required. |
| Duplicate Telegram delivery | Dedupe key and asked state prevent a second question. |
| Telegram delivery result uncertain | Do not auto-resend; expose operator reconciliation so the question cannot be duplicated blindly. |
| Uncertain task-create response | Reconcile by idempotency key before retry. |
| Suggestion edited after approval preview | Reject old approval hash and require a new preview/confirmation. |
| Archive request repeated | Return current archived state without duplicate audit. |
| Agent-control unavailable | Keep suggestions/outbox durable; Command review remains usable. |

## Rollout Sequence

### Phase 0: credential and deployment readiness

1. Generate and live-verify a fresh long-lived Page access token outside source control.
2. Confirm the correct Instagram account ID and supported Graph version.
3. Confirm access to the correct Sold With Sweeney Vercel project before any frontend variable removal.
4. Capture current production deployment IDs and a database backup before migrations.

### Phase 1: shared task service and Task Archive/Restore

1. Add lifecycle/provenance fields, creation-request idempotency, and events through Alembic; reconcile normalized legacy `archived` rows and immutable source-only archive counts.
2. Extract task creation into the shared service.
3. Normalize task/contact/overview/report grouping, then add archive/restore routes and Command UI.
4. Deploy behind `CRM_TASK_ARCHIVE_ENABLED`, migrate, and verify authenticated production behavior.

### Phase 2: Gmail suggestion engine and Command review queue

Prerequisite: start only after Tasks 7 and 8 of `docs/superpowers/plans/2026-08-18-crm-task-archive-foundation.md` are complete and green, including contact-workspace reconciliation and lifecycle E2E evidence.

1. Add sync-run, receipt, multi-action suggestion, many-source, clarification, and outbox tables.
2. Add the worker-specific Docker/Railway target and health server, then build lossless paginated History discovery plus separate receipt extraction in `integration-worker`, with feature flag `GMAIL_TASK_INTAKE_ENABLED=false` by default.
3. Build bounded thread-context obligation reconciliation, structured extraction, and the Command suggestion review UI.
4. Add protected Gmail-intake health/check/reprocess routes, thresholds, and durable notification alerts.
5. Seed the current cursor, enable in shadow mode, and compare suggestions without notifying or creating tasks.
6. Enable review queue creation after shadow acceptance checks.

### Phase 3: Sydney CRM bridge and questions

1. Deploy and verify the authenticated Command task-suggestion workspace, including blocker review, handoff exchange, URL token removal, exact preview, and separate stage-two approval.
2. Add agent-control actions and MCP tools with tests, and update the Hermes `tools.include` boot overlay plus deployment documentation. Overlay code may be prepared earlier, but no write/review-handoff tool is advertised before step 1 is live.
3. Deploy the bridge and `atlas-agent` with trusted write actions disabled.
4. Verify the exact enabled CRM tools through live Hermes `tools/list`, then exercise read-only task and suggestion tools from Sydney.
5. Configure the repo-owned Telegram dispatcher secrets only on `integration-worker`, verify one-chat serialization, 24-hour reminder, 48-hour release, five-round ceiling, stale late-answer handling, and uncertain-delivery handling, then enable the clarification outbox.
6. Verify ask, answer, resume, two-stage Command handoff, authenticated explicit approval, and idempotent create end to end.
7. Keep Telegram-native approval actions absent from the registry unless the separately verified signed channel-assertion contract exists.

### Phase 4: Instagram cutover

1. Deploy backend fetch/cache/health endpoints with the fresh token in Railway.
2. Verify real Instagram CDN media and permalinks from the production API.
3. Point the frontend to the backend route and deploy to the correct Vercel project.
4. Verify rendered production media, cache degradation, admin health, and token redaction.
5. Remove legacy frontend Instagram secrets only after the backend-backed production page is healthy.

### Phase 5: remaining CRM lifecycle actions

Deliver every top-level record and child/relationship action in the two inventories above, one entity at a time. Each slice includes typed API, UI, confirmation, immutable audit, summary/report reconciliation, restore/reopen behavior where legal, and production verification. Reconcile the completed checklist against the actual Command navigation and API before declaring “other CRM things” complete.

## Testing Strategy

### Backend unit and integration tests

- task creation uses the shared service from both Command and agent-control paths;
- archive/restore is authenticated, idempotent, audited, and preserves workflow status;
- legacy `status=archived` rows migrate without loss, recovered source-only items remain read-only, and open/in-progress/completed/cancelled/archived counts follow one contract everywhere;
- idempotency-key payload mismatch fails closed;
- Gmail direction detection covers inbox, sent, self-copy, draft, spam, and automation loops;
- agent Gmail send requires UUID, commits a pre-send `sending` intent/audit before the provider call, uses the exact NULL-safe unresolved partial-index predicate, permits only one of two simultaneous first intents with NULL outcomes to call the provider, rejects a later fresh-UUID same-hash bypass, permits only one predecessor-bound successor after authenticated `not_delivered`, never auto-retries uncertain delivery, and rejects/quarantines delivered IDs that fail account/message/SENT/thread/envelope/body verification;
- one message with two actions produces two stable suggestions, while two same-title messages remain two distinct source-backed tasks;
- an inbound request plus Brandon's sent commitment in the same thread reconciles to one obligation with two sources;
- real-PostgreSQL two-connection tests prove per-account History exclusion, per-thread reconciliation serialization, different-thread parallelism, multi-page restart, crash before/after page checkpoint, duplicate receipt, cursor expiry, and worker lease cases;
- client-facing Sydney sends remain eligible, internal operational automation is suppressed by durable origin metadata, and later History delivery deduplicates both;
- extraction schema validation and raw-body non-persistence;
- ambiguous suggestions enter `needs_clarification`;
- optional missing fields do not trigger needless questions;
- one-outstanding-question constraint, immutable initial/retry/reminder attempts, Telegram success/failure/uncertain delivery, one reminder at 24 hours, fixed release at 48 hours, stale late answer, no repeated field/version, and five-round ceiling;
- real two-session barriers prove answer-versus-timeout and answer-versus-edit/source-update have exactly one winner;
- direct Sydney drafts use the same evaluator; untrusted Hermes input cannot assert identity, approval, dismissal, or suppression; unsupported owner/link blockers, stale versions, fragment hygiene, both approval issuance paths, `secrets.token_urlsafe(32)` source/decoded length, unique hash-only storage, malformed-before-lookup rejection, nonce/hash/kind/path/parent, replay, Command dismissal, and exact-once task application fail closed;
- write mutations roll back when transactional audit persistence fails;
- dismissed obligations remain suppressed across extractor upgrades unless an authenticated audited reprocess overrides them;
- exact worker `/health` and read-only `/ready`, `FIRST_COMPLETED` peer failure, stalled synchronous provider responsiveness, no curl/wget/Dockerfile healthcheck dependency, OAuth failure, stale heartbeat/cursor, backlog thresholds, alert dedupe/recovery, and synthetic alert canary;
- the real `backend/main.py` route inventory proves all three new routers are registered exactly once before route behavior can be considered green;
- the exact existing 16 MCP tools remain unchanged, exactly six CRM tools are added, and the final 22-tool registry/risk tiers exclude actual dismiss and trusted writes;
- Instagram bearer-header use, token redaction, response normalization, cache freshness, stale fallback, auth failure, rate limit, and timeout behavior.

### Frontend tests

- task Active and Archived filters;
- accessible archive/restore confirmation and uncertain-write reconciliation;
- all task counts exclude archived records consistently;
- suggestion review loading, empty, error, clarification, edit, approve, dismiss, and applied states;
- Instagram live, stale-cache, empty, and authored-fallback rendering;
- no token, Graph URL, or provider error appears in generated client assets.

The Gmail/Sydney workflow triggers on all backend files above, `hermes/**`, the MCP/overlay tests and deployment doc, both frontend package/lock files, and every Task-suggestion page/library/workspace/navigation source and test. Task 7 adds exact focused Vitest, typecheck, and scoped ESLint for only those touched files. The repository-wide `npm run lint` is currently a known-red informational baseline, recorded separately and never called green; it is not the Task 7 gate. Task 8 expands, rather than replaces, CI with the exact MCP/overlay/22-tool tests, and Task 9 retains both frontend and Hermes jobs alongside the full PostgreSQL/E2E job.

### End-to-end acceptance cases

1. A received email with a clear request becomes one reviewable suggestion and one task only after approval.
2. A sent email containing a commitment becomes one reviewable suggestion.
3. An ambiguous due time causes Sydney to ask one clear question; Brandon's reply updates the same suggestion and produces a final preview.
4. An unanswered question produces one reminder at 24 hours, releases the chat slot at 48 hours, rejects a late answer, and remains visible in Command.
5. Replaying Gmail history, Telegram delivery, approval, or task creation produces no duplicates.
6. A direct Sydney request follows the same clarification flow, opens a two-stage Command handoff, and creates the same Brandon-owned task shape only after an authenticated explicit approval click.
7. Archiving removes a task from active UI and every active count; restoring returns it with its prior status and relationships.
8. A valid Instagram credential returns real media through FastAPI and renders those exact permalinks in production.
9. Revoking the credential produces a visible admin health failure and alert while the public page uses the bounded last-good cache or explicit fallback.
10. Logs, database rows, rendered HTML, source maps, and frontend bundles contain no Instagram token or raw Gmail body.

## Production Acceptance Gate

The work is complete only when all of the following are demonstrated against production, not inferred from local code:

- Railway backend, `integration-worker`, and Hermes deployments are healthy at the intended commit.
- CRM task-foundation Tasks 7 and 8 are green before Gmail/Sydney implementation begins, and the authenticated task-suggestion UI is deployed before Hermes advertises answer/draft/handoff tools.
- The worker's exact `/health` and `/ready` responses pass through the repo-owned non-curl probe, and live Hermes `tools/list` contains exactly the enabled CRM tools without disabled trusted-write tools.
- Database reports a single expected Alembic head and new uniqueness constraints are active.
- A controlled received-email fixture and sent-email fixture reach the review queue once.
- A controlled inbound request plus Sydney-sent client commitment in the same Gmail thread reconciles to one obligation with both source messages.
- A protected Gmail status check is healthy and the synthetic alert canary is delivered without changing the real mailbox cursor.
- Sydney asks a controlled ambiguity question in Brandon's Telegram chat, accepts the bounded untrusted answer, resumes the same suggestion, exchanges a handoff in authenticated Command, requires the separate approval click, and creates exactly one task.
- The created task is visible in Command with source provenance and audit.
- Archive and Restore reconcile the task workspace, contact view, overview, and reports.
- The production homepage renders real Instagram media returned by the backend.
- A safe simulated integration failure proves last-good cache and health/alert behavior.
- Secret scans and log inspection show no pasted token, active token, bearer header, raw Graph URL with credentials, or raw Gmail body.

## Implementation Boundary

This document approves the architecture and behavior for implementation planning. It does not authorize deploying the expired pasted token, deleting CRM records permanently, sending client communications, or enabling unreviewed autonomous task creation. Any future move from review-required suggestions to automatic task creation requires a separate production evidence review and explicit approval.
