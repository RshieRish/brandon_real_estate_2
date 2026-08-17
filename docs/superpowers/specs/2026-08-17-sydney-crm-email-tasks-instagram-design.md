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
| Unanswered questions | Keep the suggestion in the review queue; send at most one reminder, then stop. |
| Task removal | Archive and Restore, not hard delete. |
| Other CRM removal | Use entity-specific lifecycle actions with immutable audit. |
| Agent access | Extend the narrow agent-control API and MCP bridge; never share an admin JWT or database credentials. |
| Gmail ingestion | Start with a dedicated, restart-safe Gmail History worker. Pub/Sub may later wake the same processor but is not required for the first reliable release. |
| Instagram fetch | Move it into FastAPI, use an authorization header, cache the last good response, and let the frontend call the backend. |
| Token storage | Railway secret variables only. The browser, rendered HTML, frontend build logs, database, and source code never contain the token. |

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
- optional linked internal records

It must:

1. Validate the contact and linked records.
2. Normalize timestamps to UTC while preserving the user's timezone interpretation in audit metadata.
3. Enforce uniqueness on the idempotency key before inserting.
4. Create the task, contact activity when applicable, provenance link, and lifecycle event in one database transaction.
5. Return the existing task for an exact idempotent replay.
6. Reject a reused idempotency key whose normalized payload differs.

Persist this contract in `crm_task_creation_requests`, not only in application memory. Each row contains an idempotency scope/key, normalized payload hash, actor/source, state, resulting task ID, failure category, and timestamps. `(scope, idempotency_key)` is unique. The creation request, task, provenance, contact activity, lifecycle event, and write audit commit together; a payload mismatch or audit failure rolls the transaction back.

No route or agent tool may bypass this service after cutover.

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

Do not run the polling loop inside every Uvicorn process. The worker hosts independently feature-flagged Gmail intake and Instagram health jobs. Gmail polls at a configurable interval, initially two minutes, and takes a PostgreSQL advisory lock per Workspace account. Only one lease-holder advances a mailbox cursor.

The current web Docker/Railway configuration cannot be reused unchanged because it hardcodes Uvicorn and an HTTP health check. Add a worker-specific target:

- `backend/Dockerfile.worker` shares the pinned backend dependencies but starts `python -m workers.integration_worker`;
- `backend/railway.integration-worker.json` selects that Dockerfile and `/health` as its Railway health path;
- the worker module runs a minimal internal ASGI health server on Railway's `$PORT` alongside the job loops;
- `/health` proves process liveness, while `/ready` verifies database reachability, a recent worker heartbeat, and that every enabled job has initialized;
- health output contains no mailbox identity, token, subject, recipient, or provider credential.

The worker service has its own restart policy and deployment verification. A successful web backend deployment is not evidence that the worker is healthy.

On first enablement, store Gmail's current `historyId` and do not scan historical mail. An authenticated admin can request an explicit bounded backfill, initially capped at seven days. If Gmail reports that the cursor is too old, record a blocked health state, reseed from the current profile cursor, and require an explicit bounded backfill rather than silently replaying the mailbox.

History discovery and content extraction are separate durable stages. A `gmail_history_runs` row records the committed start cursor, target history ID, next page token, and run state. For each History page, one transaction upserts every discovered message ID as a pending receipt and checkpoints the next page token. Only the final-page transaction marks the run complete and advances `gmail_sync_states.current_history_id`. A crash resumes the page or run; it cannot advance past an undiscovered message. A separate consumer claims pending receipts, refetches message content when needed, extracts suggestions, and records success/failure without moving the mailbox cursor.

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

Client-facing email sent through Sydney remains eligible. The agent-control Gmail send path records `gmail_message_origins` keyed by Workspace account and returned Gmail message ID, with origin type such as `client_facing_agent_send` or `internal_operational_automation`. The former enters normal sent-mail extraction and thread reconciliation; only the latter is suppressed. The later History event uses the same origin row and receipt key.

### Durable data model

`gmail_sync_states`

- one row per Workspace account;
- mailbox identity, current history cursor, lease metadata, last success, last error, and enabled state;
- never stores OAuth token material.

`gmail_message_origins`

- identifies known app/agent-created sent messages by account and Gmail message ID;
- records only origin class, source request ID, and timestamps;
- unique on `(workspace_account_id, gmail_message_id)` and contains no body.

`gmail_message_receipts`

- Workspace account ID, Gmail message ID, thread ID, direction, received/sent timestamp, normalized participant hashes, subject preview, content hash, classification, and processing timestamps;
- unique on `(workspace_account_id, gmail_message_id)`;
- stores no full raw body.

`crm_task_suggestions`

- structured title, description, priority, due time, matched contact, confidence, rationale, state, model/schema version, idempotency key, and resulting task ID;
- states: `needs_clarification`, `possible_duplicate`, `pending_review`, `approved`, `dismissed`, `applied`, or `failed`;
- zero, one, or many suggestions may belong to a receipt;
- unique source key based on mailbox, message ID, stable normalized action key, and model schema version, so one email can yield two distinct tasks while reprocessing cannot duplicate either one;
- an `obligation_fingerprint`, Gmail thread ID, and optional `duplicate_of_suggestion_id` support cross-message reconciliation.

`crm_task_email_sources`

- immutable link from suggestion and resulting task to the Gmail receipt;
- includes direction and a minimal user-visible source label;
- unique on `(workspace_account_id, gmail_message_id, suggestion_key)`;
- no raw body.

`sydney_clarification_threads`

- one active thread per suggestion;
- one outstanding clarification per Telegram chat, enforced by a partial unique constraint while state is `awaiting_answer`;
- state, opaque clarification code, current structured missing field, normalized options where useful, question version, ask count, Telegram chat/message IDs when available, last asked time, one reminder time, resolved fields, and completion time;
- does not store the original full email or unrelated chat history.

`sydney_question_outbox`

- durable delivery job with suggestion ID, dedupe key, claim time, sent time, and delivery status;
- unique dedupe key prevents duplicate questions after restarts.

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

This makes `crm_task_email_sources` many-to-one: multiple received and sent receipts can explain one suggestion and resulting task.

### When Sydney must ask

Sydney asks when proceeding would require a consequential guess. The backend, not the conversational model alone, determines that a clarification is required when any of these conditions applies:

- the intended action is ambiguous or more than one materially different task is plausible;
- a deadline is clearly required by the email but the time expression is incomplete, conflicting, or timezone-ambiguous;
- more than one CRM contact is a plausible match and the relationship matters to the task;
- the email delegates among multiple people and the owner of the CRM task is unclear;
- approval text conflicts with the stored structured suggestion;
- a requested linked opportunity, agreement, listing, or contact cannot be uniquely resolved.

Sydney does not ask merely because an optional field is absent. A clear task may have no contact or due date. Sydney also does not invent a contact, deadline, owner, or external action.

The same evaluator applies to `sydney_chat` drafts created from a direct request. A direct request is not allowed to bypass missing-field, duplicate, contact-match, or deadline checks merely because Brandon initiated it conversationally.

### Clarification conversation policy

1. Ask one short, specific question at a time in Brandon's allowlisted Telegram chat. Do not deliver a second suggestion's question until the current chat question is resolved or timed out back to the Command queue.
2. Include just enough context to identify the email, using sender/recipient, compact subject, and proposed task title. Never paste the full body unless Brandon explicitly asks Sydney to read the thread.
3. Offer two or three choices only when the backend has real candidates; otherwise ask a direct free-text question.
4. Store the pending field, opaque clarification code, and suggestion ID before delivery. Include the short opaque code in the question without exposing a database ID.
5. Correlate the answer to the one outstanding chat clarification, opaque code, and Telegram reply-to message ID when available.
6. Validate and persist the structured answer, then reevaluate the same suggestion.
7. Ask the next required question only if another consequential ambiguity remains.
8. When complete, show a compact final task preview and ask Brandon to Approve, Edit, or Dismiss.
9. If Brandon does not answer, send no more than one reminder after 24 hours. The suggestion remains in Command's review queue without further messages.
10. If an answer cannot be correlated safely, Sydney names the compact subject and opaque code and asks Brandon to choose; it does not apply the answer speculatively.

Examples:

- `Jane asked for the disclosure tomorrow. Should I set this for 9:00 AM or 5:00 PM Eastern?`
- `This could be linked to Jane Miller or Jane Miller-Smith. Which contact should I use?`
- `The email contains two requests. Should I make one task for both, or separate tasks?`

Sydney must never ask the client or any email participant. All clarification goes only to Brandon's approved private channel.

### Review and application

A complete suggestion enters `pending_review`. Command shows the proposal, source direction, compact email identifier, confidence, extracted fields, missing-field state, and audit trail. Brandon can edit structured fields before approving.

Approval creates a short-lived server-issued nonce and payload hash bound to suggestion ID, current version, approver, and normalized task fields. The nonce has `expires_at` and `used_at`; it can be consumed only once. If the suggestion changes after preview, the old approval becomes invalid. The shared task service applies the approved version once and records the resulting task ID. Retries reconcile and return that same task.

For the initial rollout, final approval occurs in authenticated Command UI through a signed deep link Sydney may present. This is the only current path that proves the approver is an authenticated administrator rather than merely the holder of `AGENT_CONTROL_TOKEN`. Telegram-native approval stays disabled until the Hermes delivery gate below can provide a trusted, server-verifiable channel assertion bound to Brandon's allowlisted Telegram user/chat and inbound update ID.

Dismissal records a reason category and prevents repeated suggestions for the same semantic action unless the source message itself changes.

Dismissal suppression is independent of extractor/model version. Persist a `gmail_obligation_suppressions` row keyed by the version-independent source/action identity and obligation fingerprint, with dismissal reason, actor, and time. Model/schema version remains extraction metadata, not part of suppression identity. Reprocessing does not bypass this ledger; only an explicit authenticated admin Reprocess action can supersede a dismissal, and that override is audited.

When the existing agent-control Gmail send action succeeds, it should enqueue the returned Gmail message ID for the same receipt processor. The later Gmail History observation uses the receipt uniqueness key and becomes an idempotent reconciliation, not a second suggestion. History cursor advancement follows the durable scan-run contract: every discovered message is committed as a pending receipt before the final sync cursor advances, while extraction may safely continue afterward.

### Gmail intake health and alerts

Protected admin routes:

- `GET /api/v1/admin/integrations/gmail-task-intake/status`
- `POST /api/v1/admin/integrations/gmail-task-intake/check`
- `POST /api/v1/admin/integrations/gmail-task-intake/reprocess/{receipt_id}`

Status reports only bounded operational data: enabled/shadow/live mode, worker heartbeat age, last poll/success, current cursor state, current History run state, pending/failed receipt counts, oldest pending age, last applied suggestion time, and sanitized error category. It never returns subjects, participants, bodies, OAuth tokens, or raw provider errors.

Configurable thresholds cover maximum worker-heartbeat age, poll age, pending-receipt age, and repeated failed receipts. Revoked Workspace OAuth, expired History cursor, stalled scan, missed worker heartbeat, growing pending backlog, and repeated extraction failures transition a deduplicated health state and enqueue an administrator email through `notification_jobs`. Recovery sends one resolved notification. An authenticated, diagnostics-gated canary may enqueue a synthetic Gmail-intake alert under a separate provider key to prove production alert delivery without corrupting the real cursor or revoking live OAuth.

## Sydney and Hermes CRM Bridge

### Agent-control actions

Add typed actions under `/api/v1/agent-control/crm/*` and advertise them in the existing action registry:

| Action ID | Purpose | Risk tier |
|---|---|---|
| `crm.tasks.read` | Read active or archived task summaries | Read-only |
| `crm.task_suggestions.read` | Read suggestions awaiting clarification or review | Read-only |
| `crm.task_clarifications.answer` | Submit Brandon's structured answer | Human-originated write |
| `crm.task_drafts.create` | Create a reviewable draft from a direct Sydney request | Internal reversible write |
| `crm.task_suggestions.approval_link` | Issue a short-lived Command review link | Read/review handoff |
| `crm.task_suggestions.dismiss` | Dismiss a suggestion | Reversible workflow write |
| `crm.task_suggestions.approve` | Apply the exact previewed suggestion; disabled for Hermes initially | Trusted-channel confirmed write |
| `crm.tasks.create_confirmed` | Create an explicitly requested manual task; disabled for Hermes initially | Trusted-channel confirmed write |
| `crm.tasks.archive` | Archive a named task; disabled for Hermes initially | Trusted-channel confirmed reversible write |
| `crm.tasks.restore` | Restore an archived task; disabled for Hermes initially | Trusted-channel confirmed reversible write |

Tool descriptions must say exactly which actions require a suggestion version, payload hash, authenticated Command approval, or trusted Telegram channel assertion. A `confirmed_by_brandon` boolean alone is never sufficient. Disabled actions remain out of the advertised runtime action registry until their authentication gate is satisfied.

### MCP bridge and Hermes scheduling

Extend `hermes/atlas_backend_mcp.py` with one MCP tool per enabled allowlisted action. The bridge continues to hold only `AGENT_CONTROL_TOKEN` and the backend URL.

The deployed Hermes template also has a hardcoded `tools.include` allowlist in its boot overlay. Implementation must update the repo-owned overlay/bootstrap source and `docs/deployment/hermes-railway.md` with the exact enabled CRM tool names, redeploy `atlas-agent`, and then call live MCP `tools/list`. A code-level bridge test or backend action-registry response is not sufficient; production acceptance requires the expected CRM tools to appear in Hermes and every disabled trusted-write tool to remain absent.

Automatic question delivery uses a repo-owned dispatcher inside `integration-worker`, not an assumed Hermes cron callback. The worker holds `SYDNEY_TELEGRAM_BOT_TOKEN`, `SYDNEY_TELEGRAM_BRANDON_CHAT_ID`, and `SYDNEY_TELEGRAM_BRANDON_USER_ID` as Railway secrets and calls Telegram Bot API `sendMessage` only for that allowlisted chat. It never calls `getUpdates`, so Hermes remains the sole inbound long-polling consumer. A successful response supplies the real chat/message IDs, which the worker persists on the clarification row.

The dispatcher commits `sending` before the external call. A known pre-send failure is retryable. A timeout, worker crash, or unknown response after dispatch becomes `delivery_uncertain` and is not automatically resent; Command exposes Reconcile/Retry so an operator can avoid duplicate questions. A known Telegram success commits `sent`, and the partial unique chat constraint prevents the next question from leaving until the current one resolves or times out. This is at-least-once durable intent with fail-closed uncertain delivery, not a false exactly-once claim about Telegram.

Incoming Telegram answers remain ordinary Sydney conversations handled by Hermes. Sydney calls the clarification-answer tool only with the opaque code for the one correlated active thread. A direct request such as `add a task to call Jane Friday` first uses `crm.task_drafts.create`; that draft passes through the same missing-field evaluator, Sydney questions, final preview, and Command approval path as an email suggestion.

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
| Gemini invalid output | Record failed extraction safely; retry with bounded count; surface for review without creating a task. |
| Ambiguous task | Create one pending clarification; Sydney asks rather than guessing. |
| No answer from Brandon | One reminder after 24 hours, then leave in review queue. |
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

1. Add sync-run, receipt, multi-action suggestion, many-source, clarification, and outbox tables.
2. Add the worker-specific Docker/Railway target and health server, then build lossless paginated History discovery plus separate receipt extraction in `integration-worker`, with feature flag `GMAIL_TASK_INTAKE_ENABLED=false` by default.
3. Build bounded thread-context obligation reconciliation, structured extraction, and the Command suggestion review UI.
4. Add protected Gmail-intake health/check/reprocess routes, thresholds, and durable notification alerts.
5. Seed the current cursor, enable in shadow mode, and compare suggestions without notifying or creating tasks.
6. Enable review queue creation after shadow acceptance checks.

### Phase 3: Sydney CRM bridge and questions

1. Add agent-control actions and MCP tools with tests, and update the Hermes `tools.include` boot overlay plus deployment documentation.
2. Deploy the bridge and `atlas-agent` with trusted write actions disabled.
3. Verify the exact enabled CRM tools through live Hermes `tools/list`, then exercise read-only task and suggestion tools from Sydney.
4. Configure the repo-owned Telegram dispatcher secrets only on `integration-worker`, verify one-chat serialization and uncertain-delivery handling, then enable the clarification outbox.
5. Verify ask, answer, resume, signed Command review link, authenticated approval, and idempotent create end to end.
6. Keep Telegram-native approval actions absent from the registry unless the separately verified signed channel-assertion contract exists.

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
- one message with two actions produces two stable suggestions, while two same-title messages remain two distinct source-backed tasks;
- an inbound request plus Brandon's sent commitment in the same thread reconciles to one obligation with two sources;
- History multi-page restart, crash before/after page checkpoint, duplicate receipt, cursor expiry, and worker lease cases;
- client-facing Sydney sends remain eligible, internal operational automation is suppressed by durable origin metadata, and later History delivery deduplicates both;
- extraction schema validation and raw-body non-persistence;
- ambiguous suggestions enter `needs_clarification`;
- optional missing fields do not trigger needless questions;
- one-outstanding-question constraint, Telegram success/failure/uncertain delivery, answer correlation, and one-reminder ceiling;
- direct Sydney drafts use the same evaluator; stale versions, approval nonce/hash, replay, dismissal, and exact-once task application fail closed;
- write mutations roll back when transactional audit persistence fails;
- dismissed obligations remain suppressed across extractor upgrades unless an authenticated audited reprocess overrides them;
- worker `/health` and `/ready`, OAuth failure, stale heartbeat/cursor, backlog thresholds, alert dedupe/recovery, and synthetic alert canary;
- every new agent action appears in the registry and enforces the correct risk tier;
- Instagram bearer-header use, token redaction, response normalization, cache freshness, stale fallback, auth failure, rate limit, and timeout behavior.

### Frontend tests

- task Active and Archived filters;
- accessible archive/restore confirmation and uncertain-write reconciliation;
- all task counts exclude archived records consistently;
- suggestion review loading, empty, error, clarification, edit, approve, dismiss, and applied states;
- Instagram live, stale-cache, empty, and authored-fallback rendering;
- no token, Graph URL, or provider error appears in generated client assets.

### End-to-end acceptance cases

1. A received email with a clear request becomes one reviewable suggestion and one task only after approval.
2. A sent email containing a commitment becomes one reviewable suggestion.
3. An ambiguous due time causes Sydney to ask one clear question; Brandon's reply updates the same suggestion and produces a final preview.
4. An unanswered question produces at most one reminder and remains visible in Command.
5. Replaying Gmail history, Telegram delivery, approval, or task creation produces no duplicates.
6. A direct Sydney request follows the same clarification flow, opens a signed Command review, and creates the same task shape after authenticated approval.
7. Archiving removes a task from active UI and every active count; restoring returns it with its prior status and relationships.
8. A valid Instagram credential returns real media through FastAPI and renders those exact permalinks in production.
9. Revoking the credential produces a visible admin health failure and alert while the public page uses the bounded last-good cache or explicit fallback.
10. Logs, database rows, rendered HTML, source maps, and frontend bundles contain no Instagram token or raw Gmail body.

## Production Acceptance Gate

The work is complete only when all of the following are demonstrated against production, not inferred from local code:

- Railway backend, `integration-worker`, and Hermes deployments are healthy at the intended commit.
- The worker's own `/health` and `/ready` pass, and live Hermes `tools/list` contains exactly the enabled CRM tools without disabled trusted-write tools.
- Database reports a single expected Alembic head and new uniqueness constraints are active.
- A controlled received-email fixture and sent-email fixture reach the review queue once.
- A controlled inbound request plus Sydney-sent client commitment in the same Gmail thread reconciles to one obligation with both source messages.
- A protected Gmail status check is healthy and the synthetic alert canary is delivered without changing the real mailbox cursor.
- Sydney asks a controlled ambiguity question in Brandon's Telegram chat, accepts the answer, resumes the same suggestion, hands off to authenticated Command approval, and creates exactly one task.
- The created task is visible in Command with source provenance and audit.
- Archive and Restore reconcile the task workspace, contact view, overview, and reports.
- The production homepage renders real Instagram media returned by the backend.
- A safe simulated integration failure proves last-good cache and health/alert behavior.
- Secret scans and log inspection show no pasted token, active token, bearer header, raw Graph URL with credentials, or raw Gmail body.

## Implementation Boundary

This document approves the architecture and behavior for implementation planning. It does not authorize deploying the expired pasted token, deleting CRM records permanently, sending client communications, or enabling unreviewed autonomous task creation. Any future move from review-required suggestions to automatic task creation requires a separate production evidence review and explicit approval.
