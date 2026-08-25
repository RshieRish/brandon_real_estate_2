# Sydney Durable Context and Automatic Continuation Design

**Date:** 2026-08-25  
**Author:** Brainstormed with Codex  
**Scope:** Sydney/Hermes, Telegram, FastAPI agent control, PostgreSQL, the integration worker, Command contacts, and Railway  
**Status:** Approved in conversation; written specification awaiting review

---

## Problem

Sydney currently treats one long-running Hermes session as both the durable record and the active model prompt. Those are different jobs and must be separated.

The production incident on 2026-08-25 demonstrated the failure mode:

- Brandon's Telegram messages reached the healthy `atlas-agent` service.
- Sydney did not have a Command contacts tool, so it searched Google Contacts and Drive and attempted to interpret the authenticated Command web page instead of using the Command backend.
- The affected session had grown to hundreds of messages and more than one hundred tool calls.
- One response ran for roughly 33 minutes and sent approximately 281,000 input tokens before Gemini returned `429 RESOURCE_EXHAUSTED` for the paid-tier input-token quota.
- Hermes did preserve the transcript, but its configured compression threshold was about half of Gemini 3.5 Flash's one-million-token window. That protects against the model's context ceiling, not the much lower operational token-per-minute limit.
- Hermes did not recognize Gemini's `retry in ...` wording, so it used a one-hour fallback cooldown instead of the provider's approximately 47-second delay.
- Daily and idle session resets can rotate the active session, while historical recall still depends on the model deciding to call `session_search`.
- Brandon received instructions such as `/new` or `/reset`. Those are implementation details and are not an acceptable operating requirement for a nontechnical user.

The permanent solution must preserve complete useful operational history while keeping each model request small, relevant, restart-safe, and automatically recoverable.

## Goals

- Retain Brandon's complete useful Sydney history indefinitely in the private production data plane.
- Store each inbound message durably before an AI request begins.
- Preserve visible user messages, assistant responses, tool calls, tool results, approvals, errors, and internal continuation markers.
- Recall relevant history automatically before every turn without waiting for Brandon or the model to request it.
- Let Sydney search the full historical record when the bounded automatic context is not enough.
- Make session compression and rotation invisible to Brandon; `/new`, `/reset`, and `/compact` must not be part of the normal user experience.
- Recover automatically from transient Gemini rate limits, timeouts, and provider failures without losing or duplicating work.
- Prevent retries from repeating external side effects.
- Add explicit, bounded Command contact tools so Sydney cannot confuse Command with Google Contacts or scrape the admin UI.
- Keep outbound email, calendar, CRM, and other consequential actions behind their existing confirmation and authority boundaries.
- Backfill existing Hermes history and prove reconciliation with counts and hashes.
- Expose enough metrics and health state to prove that storage, retrieval, compaction, and retry are working in production without logging conversation content.

## Non-goals

- Do not put the full lifetime transcript into every Gemini request.
- Do not replace Command or Google Workspace as the source of truth for current contact, calendar, or email state. Conversation memory records what happened; current-state tools answer what is true now.
- Do not add an unrestricted database connection, Command admin session, or browser scraper to Hermes.
- Do not add an unreviewed mass-email sending capability. This design adds Command search and audience preview; sending remains a separately confirmed action.
- Do not store passwords, bearer tokens, OAuth tokens, API keys, session cookies, signed handoff fragments, or other credentials as memory.
- Do not mirror hidden model reasoning, encrypted thought signatures, or raw binary attachment bytes into PostgreSQL. Visible content, tool activity, extracted attachment text, immutable asset identifiers, and hashes are retained.
- Do not introduce a third-party memory vendor. The canonical store remains the existing PostgreSQL deployment, with Hermes's Railway volume as a local write-ahead and recovery copy.
- Do not promise that storage is physically indestructible. "Indefinite" means no automatic expiry or retention TTL, protected by the existing database backup and recovery process until an explicitly authorized deletion policy is introduced.

## Decisions Locked During Brainstorming

| Decision | Choice |
|---|---|
| Retention | Full private useful history indefinitely, with no automatic TTL. |
| User interaction | Brandon never needs `/new`, `/reset`, or another context-management command. |
| Canonical history | PostgreSQL owned by the Brandon backend. |
| Local safety copy | Hermes `state.db` remains intact and a new local SQLite spool records unacknowledged writes and pending runs on `/data`. |
| Retrieval | Automatic bounded context on every turn plus an explicit full-history search tool. |
| Context strategy | Store everything; inject only recent, active, and relevant evidence under a hard token budget. |
| Memory extraction | Structured, source-linked projections produced asynchronously; raw events remain authoritative. |
| Session policy | No daily or idle reset; internal compression and continuation rotation only. |
| Command contacts | Add explicit read-only Command search and server-side audience preview tools. |
| Side effects | Existing confirmations remain; automatic retries require a completed-result record or an idempotency contract. |
| Gemini recovery | Parse provider retry metadata, use bounded exponential backoff with jitter, and persist longer waits instead of blocking Telegram. |
| Rollout | Write-only shadow mode, reconciled backfill, retrieval canary, retry canary, then full Brandon enablement. |

## Architecture

```text
Brandon on Telegram
        |
        v
Hermes gateway in atlas-agent
  1. append inbound event to local SQLite spool
  2. mirror event + run record through agent-control API
  3. retrieve bounded durable context
  4. run Gemini with strict prompt/tool budgets
  5. persist tool events and final response
  6. acknowledge the local spool only after backend commit
        |
        +-----------------------------+
        |                             |
        v                             v
Hermes state.db                 FastAPI agent-control
full local transcript           authenticated context endpoints
session_search fallback                |
local pending-run spool                v
                                 PostgreSQL
                                 append-only events
                                 session lineage
                                 context checkpoints
                                 durable facts
                                 run/retry ledger
                                 tool invocation ledger
                                        |
                                        v
                                 integration-worker
                                 structured projections
                                 retry readiness/health

Command database ----------------> bounded Command contact tools
Google Workspace ---------------> existing separate Workspace tools
```

PostgreSQL is the canonical cross-restart, cross-session history. Hermes's existing `state.db` is not removed: it remains the immediate full transcript and local search fallback. A small separate SQLite spool under the persistent `/data` volume makes pre-call writes and pending retries crash-safe when the backend is temporarily unavailable. The spool is a queue, not a second long-term memory API; acknowledged rows can be compacted after PostgreSQL reconciliation.

## Stable Identity and Session Lineage

The durable identity key is not a Hermes session ID. It is a backend-issued UUID mapped to the allowlisted Telegram platform, Brandon's stable Telegram user ID, and Brandon's private chat ID. Raw identifiers remain private and are never emitted in logs or model context.

Every Hermes session is recorded as a continuation segment under that identity:

- `hermes_session_id` identifies the local transcript segment.
- `parent_session_id` records compression or continuation lineage.
- `logical_conversation_id` remains stable across internal rotation.
- `reset_reason` distinguishes compression, deployment restart, explicit administrator recovery, and legacy user commands.

Compression may create a new Hermes session ID, but it does not create a new Brandon conversation. The provider reloads the same durable identity, active commitments, and relevant history automatically.

## Durable Data Model

The migration follows the current sole Alembic head and uses PostgreSQL-specific contract tests for constraints, search indexes, and concurrent claims.

### `agent_conversation_identities`

- UUID primary key.
- Platform and private external user/chat identifiers.
- Display label and enabled state.
- Retention mode fixed to `indefinite` for Brandon's identity.
- Unique active mapping for `(platform, external_user_id, external_chat_id)`.
- Created, updated, and last-seen timestamps.

### `agent_conversation_sessions`

- UUID primary key and identity foreign key.
- Unique Hermes session ID.
- Logical conversation ID and optional parent session foreign key.
- Platform, start/end timestamps, continuation reason, model, and source version.
- Per-session source event count and reconciliation hash.

### `agent_conversation_events`

- UUID primary key, identity/session foreign keys, and immutable timestamp.
- Stable `source_event_key`, unique within the source. Hermes rows use the original session ID plus local message ID; Telegram inbound events additionally bind the platform message ID.
- Event type: `user`, `assistant`, `tool_call`, `tool_result`, `approval`, `error`, `continuation`, or `attachment_reference`.
- Role, tool name, tool-call ID, provider model, token metadata, redaction status, and content SHA-256.
- Small structured metadata in JSONB. Metadata never includes credentials or full content.
- Search text and a generated PostgreSQL full-text-search vector with a GIN index.
- Events are append-only. Corrections create new events or superseding facts; they do not rewrite history.

### `agent_conversation_event_segments`

- Event foreign key, zero-based ordinal, UTF-8 text segment, and segment SHA-256.
- Unique `(event_id, ordinal)`.
- Stores complete visible textual payloads without forcing huge values into one API object.
- Binary files are represented by immutable provider/file IDs, media type, size, extracted text when available, and content hash. Raw bytes stay in the system that owns the file.

### `agent_context_checkpoints`

- Identity, logical conversation, source event boundary, schema version, and production timestamp.
- Bounded rolling summary, active tasks, commitments, decisions, people/entities, and unresolved questions.
- Source event IDs and a hash of the covered event range.
- Checkpoints are immutable; the newest valid checkpoint is selected during retrieval.

### `agent_memory_facts`

- Canonical key, kind, value JSON, confidence, status, valid/superseded timestamps, and projection version.
- Kinds: `identity`, `preference`, `person`, `project`, `decision`, `commitment`, and `constraint`.
- One or more source event IDs are mandatory. A model-derived fact without provenance is rejected.
- New evidence supersedes a fact; it never erases the raw source history.

### `agent_run_jobs`

- One row per inbound Telegram message, unique by identity and platform message ID.
- States: `queued`, `running`, `waiting_retry`, `succeeded`, `blocked_side_effect`, or `terminal_failure`.
- Attempt count, lease owner/expiry, next attempt, provider category, bounded error code, session lineage, and final response event.
- A per-identity database lease preserves FIFO processing across gateway restarts.
- No raw prompt or credential is stored in run metadata; the inbound event is referenced by ID.

### `agent_tool_invocations`

- Run, Hermes call ID, tool name, canonical argument hash, side-effect class, caller idempotency key, state, and result event.
- Unique `(run_id, tool_call_id)`.
- States distinguish `started`, `succeeded`, `not_delivered`, `delivery_uncertain`, and `failed`.
- Raw arguments/results remain in redacted event segments. The ledger stores only hashes, IDs, and outcome metadata needed to prevent duplicate execution.

## Secret Redaction and Content Boundaries

Redaction occurs before PostgreSQL or the local spool accepts content. The same deterministic redactor covers:

- bearer and API-key header shapes;
- OAuth access and refresh tokens;
- signed session, handoff, and approval fragments;
- password/secret assignment patterns;
- known configured secret values supplied only at runtime and never persisted;
- nested URLs and JSON strings containing credential-like query values.

Redacted values become typed markers such as `[REDACTED_BEARER_TOKEN]`; the original secret and a reversible representation are never retained. Email addresses, phone numbers, contact names, property addresses, and ordinary business content are retained under the approved indefinite private-history policy.

Audit logs contain action IDs, counts, event IDs, hashes, timing, and result classes only. Application logs must not include transcript bodies, context packets, tool arguments, Telegram identifiers, or Gemini prompt payloads.

## Ingest and Reconciliation Flow

1. The gateway receives a Telegram message and resolves Brandon's durable identity.
2. Before calling Gemini, it writes the inbound event and queued run to `sydney_spool.db` using one local transaction.
3. It calls `POST /api/v1/agent-control/context/events/batch` and `POST /api/v1/agent-control/context/runs/start` with idempotency keys.
4. A successful backend commit marks the local rows acknowledged. Backend unavailability does not discard the message; normal processing may continue from the local transcript while the spool retries replication.
5. Hermes persists tool-inclusive messages to its existing `state.db` as it does today.
6. The gateway records each tool invocation in the local spool immediately before execution and records its outcome immediately afterward. Retry safety therefore does not depend on reaching a final assistant response.
7. After each completed turn, the Sydney memory provider reads the source message IDs that have not been acknowledged and submits bounded batches. Duplicate batches return the already-created event IDs.
8. On startup and periodically, the provider drains the spool and scans for any `state.db` rows beyond its acknowledged cursor.
9. Reconciliation compares per-session event counts, role/tool counts, content hashes, and ordered aggregate hashes. It never deletes either copy to make counts match.

The backend endpoint accepts at most 100 events per request and a bounded transport payload. Large event bodies are split into ordered segments so the full useful text is retained without an unbounded request.

## Automatic Context Retrieval

Before every Gemini turn, the Sydney memory provider calls `POST /api/v1/agent-control/context/retrieve` with the durable identity, logical conversation, current user text, current session ID, and a requested token budget.

The response is a deterministic context packet, ordered as follows:

1. Confirmed identity and durable user preferences.
2. Active commitments, tasks, decisions, constraints, and unresolved questions.
3. The newest valid rolling checkpoint.
4. A bounded recent window across the current session lineage.
5. Up to eight older excerpts ranked by PostgreSQL full-text relevance, entity overlap, recency, and source confidence.
6. Source event IDs for every fact and excerpt.

The default recalled-memory budget is 16,000 tokens. The packet builder budgets sections independently, truncates only the injected copy, and never mutates stored events. Historical text is clearly wrapped as untrusted quoted evidence; it cannot override Sydney's system prompt, current user request, confirmation requirements, or tool policy.

Current-state data wins over memory. For example, a remembered contact email explains what Sydney used previously, while `command_contacts_search` supplies the authoritative current email.

If the backend is unavailable, the provider falls back to the most recent locally cached context packet and Hermes `session_search`. The user turn continues in degraded mode and the outage is recorded in health metadata.

## Full-History Search Tool

Automatic recall is intentionally bounded. A new read-only MCP tool, `context_history_search`, provides explicit deeper lookup through the backend when Sydney needs it.

Calling shapes:

- Search by natural-language terms, optional event types, and bounded date range.
- Browse recent logical conversations.
- Read a bounded window around a returned event ID.

The result returns actual stored messages/tool events with source IDs and timestamps, not an unsourced model summary. Limits are clamped, content is segmented, and every call is audited. The existing local `session_search` remains available as a fallback, but the system prompt directs Sydney to prefer the backend tool for cross-restart canonical recall.

## Structured Memory Projection

The integration worker claims completed event ranges that do not yet have a checkpoint. It sends a bounded transcript slice to Gemini using structured output with a small, versioned Pydantic schema. The allowed result contains:

- rolling summary;
- active tasks and commitments;
- decisions and constraints;
- people/entities;
- fact operations with canonical keys, confidence, and source event IDs;
- unresolved questions.

The application validates every field and provenance reference. Schema-valid but semantically invalid records are rejected and retried or quarantined. Projection never executes a tool, sends a message, or mutates CRM data. If Gemini is unavailable, raw history and full-text retrieval continue working; projection is an optimization, not the durability boundary.

Projection uses a small bounded input, low output ceiling, response usage metadata, and a separate concurrency/rate budget. It yields to interactive Sydney traffic and pauses while the Gemini integration health state is rate-limited.

## Prompt and Tool-Loop Budgets

Gemini 3.5 Flash supports a much larger model context than Sydney should normally send. The operational budget is therefore independent of the model's maximum:

- Estimate the complete request, including system prompt, function declarations, recalled context, recent messages, tool results, and requested output.
- Recheck that estimate before every provider call inside the tool loop, not only at the beginning of the user turn.
- Keep recalled durable context at or below 16,000 tokens.
- Force compression before the estimated complete input reaches 96,000 tokens.
- Configure Hermes compression near eight percent of the detected 1,048,576-token model context, with a small rolling target and a protected recent tail.
- Validate actual prompt, cached, tool-use, and output counts from Gemini usage metadata. Use the official `countTokens` endpoint for uncertain or unusually large requests rather than on every normal turn.
- Enforce a configurable rolling 60-second interactive input budget, initially 500,000 tokens, leaving headroom below the currently observed provider quota for compression, retries, and other production work. When the bucket is full, persist a short continuation wait instead of making another doomed call.
- Reduce the interactive tool-iteration ceiling from 60 to 16.
- Enable Hermes hard loop stops using the existing thresholds: five identical failures, eight failures from the same tool, or five idempotent calls with no progress.
- Keep warnings enabled and compact tool output before it enters the model.
- Large audiences and collections remain server-side and are represented by references, counts, filters, and small samples.

If ordinary compression cannot produce a safe summary, the gateway creates an internal continuation session from the latest durable checkpoint and context packet. It does not ask Brandon to run a slash command, and no stored history is deleted.

## Session Configuration

The boot overlay enforces the following production posture while preserving unrelated dashboard configuration:

- `session_reset.mode: none`;
- compression enabled at the approved lower threshold;
- `abort_on_summary_failure: true`, paired with the durable fallback rather than silent message loss;
- hard tool-loop stops enabled;
- interactive max turns set to 16;
- bounded tool output;
- the Sydney durable-memory provider enabled for Brandon's Telegram identity.

Legacy slash commands may remain as administrator recovery tools, but Sydney's normal error copy must never tell Brandon to use them.

## Automatic Retry and Continuation

The Hermes overlay adds a narrow gateway continuation controller rather than an unlimited generic retry loop.

### Retry classification

- Retryable: `408`, `429`, provider `5xx`, connection reset, and bounded timeout.
- Not retryable: authentication/authorization failure, invalid input, safety rejection, missing confirmation, or a deterministic tool-contract error.
- Context overflow invokes transparent durable continuation, not a repeat of the oversized request.

For Gemini `429`, the classifier reads, in order:

1. structured `google.rpc.RetryInfo.retryDelay` details;
2. HTTP `Retry-After`;
3. absolute reset metadata;
4. message forms including `retry in 47s` and `retry after 47 seconds`;
5. bounded fallback backoff only when no provider value exists.

Immediate application-level retries are limited to two with exponential backoff and jitter, following Google's conservative Vertex retry guidance. Longer provider waits are stored as `waiting_retry`; the Telegram handler does not sleep for the whole delay.

### User experience

On a deferred retry Sydney sends one concise message:

> I hit a temporary Google limit. Your request is saved, and I'll continue automatically.

The run remains in FIFO order for Brandon. Later messages are also saved and queued. The gateway continuation controller polls the protected claim endpoint on startup and at a bounded interval, then resumes a leased saved run after `next_attempt_at`, including the durable context and completed tool ledger. It restores the original user event from history and appends only an internal continuation marker, so the user's message is not duplicated. Success sends the final response and closes the job.

### Side-effect safety

- Read-only tools may be repeated after a transient failure.
- A successful mutating tool call is never repeated; its recorded result is restored to the resumed transcript.
- A mutating call with `delivery_uncertain` blocks automatic replay until its provider-specific reconciliation proves `not_delivered` or `succeeded`.
- Tools without an idempotency contract cannot be automatically replayed after an ambiguous boundary. The request remains saved and Sydney reports that the action outcome is being checked; it still does not ask Brandon to reset context.
- Gmail send keeps its existing caller UUID and authenticated origin ledger.
- New automatic-retry coverage for other write tools requires caller request IDs and provider-specific reconciliation before those tools are classified as replay-safe.

A run does not retry forever. Exact provider reset metadata controls normal quota waits. Unknown transient failures use a capped schedule and a 24-hour terminal deadline. Terminal failure preserves the request and emits one bounded operational alert without deleting history.

## Command Contacts Tools

Two explicit read-only tools are added to the existing MCP registry after the current 22 tools. The existing tool names and order remain unchanged.

### `command_contacts_search`

- Calls a new protected agent-control CRM endpoint; it never opens `/admin/command`.
- Searches the canonical Command contact directory by name, email, phone, tag, stage, source, or origin.
- Uses cursor pagination with a maximum page size of 25.
- Returns contact IDs, names, current primary email/phone, stage, source, tags, and a result count.
- Describes itself as Command-only. The existing `contacts_search` description is changed to say Google Contacts only and never Command.

### `command_contact_audience_preview`

- Creates or refreshes a server-side read-only audience definition from explicit filters.
- Returns an opaque audience reference, exact current count, filter summary, checksum, and a small masked sample.
- Does not place hundreds of contact records into the Gemini prompt.
- Does not draft or send email and confers no send approval.

Both routes require agent-control authentication and write content-free action audits. Query limits, filters, and response bounds are validated by the backend rather than trusted to the model.

## Hermes Overlay and Source Pinning

The current repository overlay pins the Railway template but does not pin or patch the Hermes core that is actually running. This design extends the manifest to pin both:

- the exact Railway template source; and
- official `NousResearch/hermes-agent` release `v2026.5.29.2`, commit `77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5`, matching deployed Hermes `0.15.2`.

The overlay adds only reviewable files:

- the Sydney memory provider and local spool;
- the gateway continuation/retry integration;
- exact config bootstrap changes;
- the existing Atlas MCP additions;
- an idempotent history backfill utility;
- upstream-focused tests.

Patch application verifies the exact upstream commit and expected file hashes, rejects unrelated or partial changes, and is idempotent on the exact desired result. Deployment never edits the live container by hand.

## Backend Agent-Control Contracts

All endpoints remain under `/api/v1/agent-control` and require the existing bearer dependency. New actions are added to the action registry with bounded risk tiers:

- `context.events.ingest` — append-only, idempotent internal write;
- `context.retrieve` — read-only bounded automatic context;
- `context.history.search` — read-only canonical history;
- `context.runs.start` and `context.runs.update` — idempotent internal run state;
- `context.runs.claim` — leased internal continuation claim;
- `crm.command_contacts.search` — read-only current Command lookup;
- `crm.command_contact_audiences.preview` — read-only audience materialization.

Memory endpoints are enabled only when both agent control and a dedicated `SYDNEY_DURABLE_CONTEXT_ENABLED` feature flag are true. Retrieval, projection, and automatic retry have separate rollout flags so write-only shadow mode is possible.

## Health and Observability

The backend and worker expose content-free metrics and health metadata:

- local spool unacknowledged count and oldest age;
- backend ingest success/failure and idempotent replay counts;
- canonical event, session, and identity counts;
- checkpoint lag in events and minutes;
- retrieval latency, packet tokens, section counts, and fallback use;
- total prompt, cached, tool-use, and completion tokens from provider metadata;
- compression count, continuation count, and summary failure count;
- run states, lease age, retry category, parsed provider delay, and duplicate prevention;
- Command search/audience call counts and response sizes;
- last successful backfill and reconciliation hash.

Integration health states use bounded error categories and messages. No metric label or log line contains contact details, conversation text, tool arguments, platform identifiers, or secrets.

## Existing-History Backfill

Backfill runs inside `atlas-agent` so the existing `/data/.hermes/state.db` never needs to be copied into the repository or printed to a terminal.

1. Take and validate the normal protected PostgreSQL backup before migration.
2. Enable backend context writes with retrieval and retry disabled.
3. Run the idempotent backfill utility against all Hermes sessions and messages.
4. Redact before transport and submit bounded batches.
5. Record a source event key for every source row.
6. Re-run until no rows remain unacknowledged.
7. Compare sessions, messages by role, tool-call/result counts, per-session hashes, and one ordered global aggregate hash.
8. Investigate differences; never delete or synthesize rows merely to make totals match.
9. Retain a reconciliation record with counts and hashes but no content.

Legacy JSONL transcripts are inventoried as a secondary recovery source. Rows already represented in `state.db` deduplicate by source key and content hash.

## Failure Behavior

- **Backend memory unavailable:** continue from the local transcript and cached context, queue replication, mark degraded health.
- **Local spool unavailable:** fail closed before the AI call because the inbound request is not yet durably recorded.
- **Projection unavailable:** raw storage and lexical retrieval continue; projection lag is visible.
- **Retrieval unavailable:** use last good packet and local `session_search`; never fabricate memory.
- **Compression summary fails:** preserve events and start a transparent continuation from the durable packet.
- **Gemini quota hit:** save the run, acknowledge once, honor provider delay, and continue automatically.
- **Tool loop detected:** hard stop the loop, preserve completed evidence, and return a concise progress/blocker response.
- **Ambiguous external write:** do not replay; reconcile or alert.
- **Command contact API unavailable:** report Command unavailable; never silently fall back to Google Contacts or UI scraping.
- **Backfill mismatch:** keep retrieval disabled until reconciled or explicitly accepted with documented evidence.

## Rollout Sequence

1. Implement in the isolated `codex/sydney-durable-context` worktree using tests first.
2. Add PostgreSQL models, migration, agent-control contracts, and worker projection behind disabled flags.
3. Add the exact-pinned Hermes provider, spool, retry parser, continuation controller, config bootstrap, and MCP tools.
4. Run repository tests and exact upstream Hermes overlay tests; task-specific suites must pass without increasing the recorded baseline failures.
5. Open a PR and complete code review.
6. Merge only after approval and current-head verification.
7. Create and validate a protected production PostgreSQL backup.
8. Deploy the backend with context flags disabled; verify health and the sole Alembic head.
9. Enable write-only shadow mode for Brandon and deploy `atlas-agent`.
10. Backfill and reconcile existing history.
11. Enable automatic retrieval for Brandon and verify recall before/after internal compression and service restart.
12. Verify read-only Command search and audience preview without drafting or sending email.
13. Enable retry canary and use an injected test failure to prove saved acknowledgement, provider-delay parsing, restart recovery, FIFO ordering, and no duplicate tool action.
14. Enable full durable context for Brandon, monitor health, and record production evidence in `tdtn.md`, `memory.md`, and the deployment runbook.

Rollback disables retrieval, projection, and automatic retry independently. It does not delete canonical events, backfill evidence, or the local Hermes transcript.

## Testing Strategy

### Backend unit and contract tests

- Identity and session-lineage uniqueness.
- Event/segment idempotency, ordering, redaction, and immutable hashes.
- PostgreSQL full-text ranking and bounded result windows.
- Context packet deterministic ordering and hard budget enforcement.
- Fact/checkpoint schema validation and mandatory provenance.
- Run FIFO leases, stale-lease recovery, exact retry timing, and concurrent claim exclusion.
- Tool invocation replay rules for success, failure, `not_delivered`, and `delivery_uncertain`.
- Agent-control disabled, missing-token, wrong-token, and correct-token boundaries.
- Command-versus-Google contact routing and bounded audience preview.
- Alembic upgrade/downgrade and sole-head verification on disposable PostgreSQL 16.

### Hermes and overlay tests

- Exact upstream commit/hash guard and idempotent overlay application.
- Local spool transaction survives process interruption.
- Existing `state.db` transcripts remain readable and searchable.
- Inbound event is spooled before the model adapter is called.
- Automatic prefetch injects a bounded source-linked context block.
- Backend failure uses local fallback and later reconciles.
- `retry in 47s`, `retry after 47 seconds`, `Retry-After`, structured `RetryInfo`, and unknown-delay cases.
- No one-hour fallback when a provider delay exists.
- Two immediate retries maximum, jitter bounds, persisted long wait, and restart resume.
- Successful and uncertain tool calls are not duplicated.
- Compression/session rotation retains logical identity and requires no slash command.
- Tool-loop hard stops prevent the previous unbounded pattern.
- `tools/list` preserves the existing 22 tools exactly once and appends the three new read tools exactly once.

### Production acceptance checks

- Send a unique benign fact, let Sydney reply, and verify the canonical event exists without content appearing in logs.
- Force internal compression/continuation, then ask for the fact in ordinary language; Sydney recalls it without `/new` or `/reset`.
- Restart `atlas-agent` and repeat the recall check.
- Search an older pre-backfill conversation and verify source-linked excerpts.
- Search for a known Command contact and confirm the Command tool—not Google Contacts or the admin UI—was used.
- Preview an audience and verify only count/filter/checksum/sample enter the prompt.
- Inject a safe synthetic `429` with a short delay, restart during the wait, and verify one acknowledgement plus one eventual response.
- Verify no Gmail send, calendar create, CRM mutation, or other external side effect occurred during read-only acceptance tests.
- Confirm both Railway services report `SUCCESS`, health/readiness pass, the database is on the intended sole migration head, and live metrics show bounded prompt size.

## Baseline Verification Rule

The isolated branch was created from `origin/main` at `214434d` on 2026-08-25.

- Backend baseline: 2,355 passed, 674 skipped, 17 pre-existing failures under safe test-only configuration.
- Frontend baseline: 661 passed.
- Frontend type-check: passed.
- Repository-wide frontend lint: 20 pre-existing errors and 19 warnings.

This task must not increase those unrelated failures. Every new or modified task-specific test must pass, and touched-file lint/type checks must pass even though unrelated repository-wide debt remains.

## External Engineering References

- Google documents that complete model inputs—including system instructions and tool declarations—count toward tokens, and provides `countTokens` plus response usage metadata: <https://ai.google.dev/gemini-api/docs/tokens>
- Google documents `429 RESOURCE_EXHAUSTED` for rate limits and recommends reducing expensive request size: <https://ai.google.dev/gemini-api/docs/rate-limits>
- Google's current troubleshooting guidance recommends retrying only transient errors with bounded exponential backoff and jitter: <https://ai.google.dev/gemini-api/docs/troubleshooting>
- Google's Vertex generative-AI error guidance recommends no more than two retries at the application layer: <https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/api-errors>
- Gemini structured output supports JSON Schema/Pydantic but still requires semantic application validation: <https://ai.google.dev/gemini-api/docs/structured-output>
- Gemini 3.5 Flash's model page reports a 1,048,576-token input limit; this design intentionally uses a much smaller operational prompt ceiling: <https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash>

## Acceptance Criteria

The work is complete only when all of the following are evidenced in production:

- Brandon can continue one logical conversation across compression and restart without any context-management command.
- Every new useful conversation event is present in the local transcript and canonical PostgreSQL store with reconciled IDs and hashes.
- Existing history has been backfilled and reconciled.
- Automatic retrieval supplies relevant older context under the configured budget.
- Full-history search returns source-linked actual events.
- Prompt size remains below the operational ceiling during the controlled long-context test.
- A controlled transient provider failure resumes automatically after restart.
- No completed or uncertain side-effecting tool call is duplicated.
- Sydney uses Command tools for Command contacts and never silently substitutes Google Contacts or UI scraping.
- No unapproved outbound email or mutation occurs.
- Health, migration, deployment, and live Telegram evidence are recorded without exposing private content or secrets.
