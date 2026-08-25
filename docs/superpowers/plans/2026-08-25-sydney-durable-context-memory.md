# Sydney Durable Context and Automatic Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Brandon one durable Sydney conversation across Hermes sessions and restarts, with automatic bounded recall, explicit full-history and Command contact tools, and crash-safe continuation after transient Gemini failures.

**Architecture:** PostgreSQL becomes the canonical cross-session event, checkpoint, run, and tool ledger while Hermes keeps its existing `state.db` transcript and adds a small SQLite write-ahead spool on `/data`. A custom Hermes memory provider mirrors every visible turn, automatically retrieves a source-linked context packet, and exposes full-history search; a narrow gateway patch records tool execution and persists retryable runs without replaying completed or uncertain side effects. Every behavior is independently gated so rollout can progress from write-only shadow mode through retrieval, projection, and retry canaries.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2 async, PostgreSQL 16 full-text search, Alembic, SQLite WAL, Hermes Agent 0.15.2, Gemini 3.5 Flash, MCP JSON-RPC, Railway, pytest.

---

## File Structure

Create:

- `backend/models/sydney_context.py` — the eight canonical durable-context tables.
- `backend/schemas/sydney_context.py` — strict ingest, retrieval, history, run, tool-ledger, and health wire contracts.
- `backend/schemas/agent_control_command.py` — bounded Command search and audience-preview contracts.
- `backend/services/sydney_context_redaction.py` — deterministic irreversible secret redaction and hashes.
- `backend/services/sydney_context_service.py` — identity/session resolution, append-only ingest, retrieval, search, run leases, and tool outcomes.
- `backend/services/sydney_context_projection.py` — source-linked checkpoint/fact validation and projection application.
- `backend/services/agent_control_command.py` — Command-only search and stateless audience materialization.
- `backend/routers/agent_control_context.py` — protected context and continuation endpoints.
- `backend/routers/agent_control_command.py` — protected Command read endpoints.
- `backend/workers/jobs/sydney_context_projection.py` — disabled-by-default checkpoint projection job.
- `backend/alembic/versions/85e8b7c9d4f1_add_sydney_durable_context.py` — serial revision after `84d7a5f9b2c3`.
- `backend/tests/test_sydney_context_redaction.py`
- `backend/tests/test_sydney_context_models.py`
- `backend/tests/test_sydney_context_migration.py`
- `backend/tests/test_sydney_context_service.py`
- `backend/tests/test_sydney_context_retrieval.py`
- `backend/tests/test_sydney_context_runs.py`
- `backend/tests/test_sydney_context_router.py`
- `backend/tests/test_sydney_context_projection.py`
- `backend/tests/test_agent_control_command.py`
- `backend/tests/test_sydney_context_postgres.py`
- `backend/tests/test_sydney_context_e2e.py`
- `hermes/overlay/sydney_spool.py` — local SQLite WAL queue and reconciliation cursor.
- `hermes/overlay/sydney_memory_provider.py` — Hermes `MemoryProvider` implementation.
- `hermes/overlay/sydney_retry.py` — retry-delay parser, classifier, prompt budget, and continuation state.
- `hermes/overlay/sydney_backfill.py` — idempotent `state.db` history backfill/reconciliation utility.
- `hermes/overlay/install_sydney_overlay.py` — exact-source, hash-checked Hermes core patch installer.
- `backend/tests/test_sydney_spool.py`
- `backend/tests/test_sydney_memory_provider.py`
- `backend/tests/test_sydney_retry.py`
- `backend/tests/test_sydney_backfill.py`

Modify:

- `backend/config.py`, `backend/.env.example`, `backend/main.py`, `backend/models/__init__.py`
- `backend/routers/agent_control.py`, `backend/workers/integration_worker.py`
- `backend/tests/test_integration_worker.py`, `backend/tests/test_integration_worker_deployment.py`
- `hermes/atlas_backend_mcp.py`, `hermes/verify_atlas_tools.py`
- `hermes/overlay/manifest.json`, `hermes/overlay/apply_overlay.py`, `hermes/overlay/atlas_backend_bootstrap.py`
- `backend/tests/test_atlas_backend_mcp.py`, `backend/tests/test_verify_atlas_tools.py`, `backend/tests/test_hermes_overlay.py`
- `.github/workflows/gmail-sydney-task-intake.yml`
- `hermes/README.md`, `docs/deployment/hermes-railway.md`, `tdtn.md`, `memory.md`

## Locked Runtime Contract

Use these disabled-by-default flags and limits:

```python
SYDNEY_DURABLE_CONTEXT_ENABLED: bool = False
SYDNEY_DURABLE_CONTEXT_RETRIEVAL_ENABLED: bool = False
SYDNEY_DURABLE_CONTEXT_PROJECTION_ENABLED: bool = False
SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED: bool = False
SYDNEY_CONTEXT_RECALL_TOKEN_BUDGET: int = 16_000
SYDNEY_CONTEXT_PROMPT_COMPRESS_TOKENS: int = 96_000
SYDNEY_CONTEXT_INTERACTIVE_TPM_BUDGET: int = 500_000
SYDNEY_CONTEXT_MAX_TURNS: int = 16
SYDNEY_CONTEXT_EVENT_BATCH_LIMIT: int = 100
SYDNEY_CONTEXT_SEGMENT_CHARS: int = 16_000
SYDNEY_CONTEXT_RUN_LEASE_SECONDS: int = 120
```

`SYDNEY_DURABLE_CONTEXT_ENABLED` gates all new routes. Retrieval, projection, and retry require the master flag plus their own flag. The production sequence is therefore write-only, then reconciled retrieval, then projection, then retry.

The stable identity is the unique tuple `(platform, external_user_id, external_chat_id)`. Hermes session IDs are segments of one backend `logical_conversation_id`. There is no retention TTL and no reset-based deletion.

Visible user/assistant content, tool calls/results, approvals, errors, continuation markers, and attachment references are retained. Hidden reasoning, thought signatures, raw binary bytes, passwords, tokens, cookies, signed handoff fragments, and authorization values are never retained.

## Locked Persistence Contract

Migration `85e8b7c9d4f1` creates exactly these tables and PostgreSQL invariants:

| Table | Required invariant |
|---|---|
| `agent_conversation_identities` | UUID PK; unique `(platform, external_user_id, external_chat_id)`; `retention_mode='indefinite'`; enabled and timestamps. |
| `agent_conversation_sessions` | UUID PK; identity FK; unique `hermes_session_id`; stable logical conversation; nullable parent session FK; bounded continuation reason; reconciliation count/hash. |
| `agent_conversation_events` | UUID PK; identity/session FKs; unique `(identity_id, source_event_key)`; exact event-type check; content hash; JSONB metadata; generated `tsvector` and GIN index; append-only trigger. |
| `agent_conversation_event_segments` | Event FK; nonnegative ordinal; complete redacted text; SHA-256; unique `(event_id, ordinal)`; append-only trigger. |
| `agent_context_checkpoints` | Immutable identity/logical-conversation boundary; versioned structured JSON; mandatory source event UUID array and covered-range hash. |
| `agent_memory_facts` | Versioned canonical key/kind/value/status; nonempty source event UUID array; supersession without raw-event mutation. |
| `agent_run_jobs` | Unique `(identity_id, platform_message_id)`; exact state check; attempts/lease/next attempt; inbound/final event FKs; FIFO claim index. |
| `agent_tool_invocations` | Unique `(run_id, tool_call_id)`; canonical argument hash; exact side-effect/state checks; idempotency/result linkage; no raw arguments. |

Create a shared PostgreSQL function/trigger that rejects `UPDATE` and `DELETE` on events, segments, and checkpoints. Feature rollback leaves the migration and retained evidence in place. A downgrade refuses while any owned table is nonempty; an empty owned schema may downgrade to `84d7a5f9b2c3`.

## Task 1: Add redaction, hashing, and strict wire contracts

**Files:** Create `backend/services/sydney_context_redaction.py`, `backend/schemas/sydney_context.py`, `backend/tests/test_sydney_context_redaction.py`; modify `backend/config.py` and `backend/.env.example`.

- [x] **Step 1: Write failing redaction tests** with nested URLs, JSON strings, bearer headers, OAuth values, API-key/password assignments, signed `#handoff=` fragments, configured-secret values, normal email/phone/address PII, repeated input, and UTF-8 segment boundaries. Assert secrets never appear in output or exception text; normal business PII remains; repeated input has identical redacted text and SHA-256.
- [x] **Step 2: Run the red test:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:5432/test \
  GEMINI_API_KEY=test-only-key PYTHONPATH=. ../backend/.venv/bin/pytest -q \
  tests/test_sydney_context_redaction.py
```

Expected: collection fails because `services.sydney_context_redaction` is absent.

- [x] **Step 3: Implement the strict contracts and redactor.** The public primitive is:

```python
@dataclass(frozen=True, slots=True)
class RedactedContent:
    text: str
    sha256: str
    changed: bool

def redact_content(value: str, *, configured_secrets: Sequence[str] = ()) -> RedactedContent:
    normalized = unicodedata.normalize("NFC", value)
    redacted = _redact_known_values(_redact_structural_secrets(normalized), configured_secrets)
    return RedactedContent(redacted, hashlib.sha256(redacted.encode()).hexdigest(), redacted != normalized)

def split_utf8_text(value: str, *, max_chars: int) -> tuple[str, ...]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    return tuple(value[start : start + max_chars] for start in range(0, len(value), max_chars)) or ("",)
```

Use typed markers (`[REDACTED_BEARER_TOKEN]`, `[REDACTED_OAUTH_TOKEN]`, `[REDACTED_PASSWORD]`, `[REDACTED_SIGNED_FRAGMENT]`, `[REDACTED_CONFIGURED_SECRET]`) and a bounded regex set. Do not log input or matched values. Pydantic models must use `extra='forbid'`, bounded strings/lists, UTC timestamps, UUIDs, and exact `Literal` values.
- [x] **Step 4: Re-run the focused test and `ruff check` on the three touched Python files.** Expected: all pass.
- [x] **Step 5: Commit:** `feat: add Sydney context contracts and redaction`.

## Task 2: Add the serial PostgreSQL migration and SQLAlchemy models

**Files:** Create `backend/models/sydney_context.py`, `backend/alembic/versions/85e8b7c9d4f1_add_sydney_durable_context.py`, `backend/tests/test_sydney_context_models.py`, `backend/tests/test_sydney_context_migration.py`; modify `backend/models/__init__.py`, `backend/tests/test_integration_worker.py`, and every repository assertion that pins `84d7a5f9b2c3` as the forever head.

- [x] **Step 1: Write failing model and migration tests** for the exact table/column/constraint/index inventory, generated search vector, GIN index, append-only trigger, sole head, serial ancestry, non-destructive upgrade over seeded CRM data, guarded nonempty downgrade, empty downgrade, and upgrade/downgrade roundtrip on the owned PostgreSQL fixture.
- [x] **Step 2: Run:**

```bash
cd backend
PYTHONPATH=. ../backend/.venv/bin/pytest -q \
  tests/test_sydney_context_models.py tests/test_sydney_context_migration.py
```

Expected: FAIL because revision `85e8b7c9d4f1` and models do not exist.

- [x] **Step 3: Implement the eight SQLAlchemy 2 models** using typed `Mapped` columns, named checks/uniques/FKs/indexes, PostgreSQL UUID/JSONB/ARRAY/TSVECTOR types, and no cascade that can erase canonical events. Export every class from `models.__init__` so Alembic metadata sees them.
- [x] **Step 4: Implement revision `85e8b7c9d4f1`** with `down_revision='84d7a5f9b2c3'`, `gen_random_uuid()`, exact checks, generated FTS column, GIN index, append-only trigger, FIFO/lease indexes, and a downgrade guard that raises when owned evidence exists.
- [x] **Step 5: Run model/migration tests plus `alembic heads`.** Expected: all tests pass and output is exactly `85e8b7c9d4f1 (head)`.
- [x] **Step 6: Commit:** `feat: add Sydney durable context persistence`.

## Task 3: Implement idempotent ingest and reconciliation

**Files:** Create `backend/services/sydney_context_service.py`, `backend/tests/test_sydney_context_service.py`, `backend/tests/test_sydney_context_postgres.py`.

- [x] **Step 1: Write failing service tests** proving stable identity/session lineage, event batch limit 100, pre-persistence redaction, UTF-8 segment ordering, duplicate source-key replay returning the original event, conflicting replay rejection, content/aggregate hashes, append-only enforcement, and concurrent duplicate ingest through two PostgreSQL connections.
- [x] **Step 2: Run the focused unit and PostgreSQL tests.** Expected: FAIL because the context service is absent.
- [x] **Step 3: Implement the exact async transaction boundaries** `ingest_event_batch(db, request, configured_secrets=()) -> ContextEventBatchResponse` and `reconcile_session(db, identity_id, hermes_session_id, expected) -> ReconciliationResult`. Resolve identity and session inside the caller transaction. Lock an existing conflicting source key, compare event type/content hash/ordered segment hashes, and return the stored UUID only for an exact replay. Insert event and all segments atomically. Never accept precomputed caller hashes as authoritative.
- [x] **Step 4: Re-run focused tests.** Expected: all pass, including two-connection idempotency.
- [x] **Step 5: Commit:** `feat: ingest Sydney conversation events`.

## Task 4: Implement deterministic retrieval and canonical history search

**Files:** Modify `backend/services/sydney_context_service.py`; create `backend/tests/test_sydney_context_retrieval.py`.

- [x] **Step 1: Write failing tests** for exact packet section order, confirmed facts/checkpoint/recent/relevant excerpts, source IDs on every item, current lineage ordering, FTS ranking, date/type filters, event-centered windows, maximum eight older excerpts, deterministic ties, a 16,000-token hard cap, untrusted-evidence wrapping, and truncation that never mutates stored text.
- [x] **Step 2: Run the focused retrieval tests.** Expected: FAIL because `retrieve_context` and `search_history` are absent.
- [x] **Step 3: Implement** `retrieve_context(db, request) -> ContextPacket` and `search_history(db, request) -> ContextHistorySearchResponse`. Use a deterministic approximate token estimator of `ceil(len(utf8_bytes) / 4)` for local budgeting, clamp requested recall to the configured maximum, budget each ordered section, use `websearch_to_tsquery('simple', :query)` plus `ts_rank_cd`, and return actual redacted event text with timestamps and source IDs. Historical text is wrapped in a fixed `<durable-context untrusted="true">` block and cannot carry system authority.
- [x] **Step 4: Re-run focused retrieval and ingest suites.** Expected: all pass.
- [x] **Step 5: Commit:** `feat: retrieve bounded Sydney context`.

## Task 5: Implement run leases, retry state, and tool replay protection

**Files:** Modify `backend/services/sydney_context_service.py`; create `backend/tests/test_sydney_context_runs.py`.

- [x] **Step 1: Write failing tests** for unique platform-message runs, FIFO per identity, `FOR UPDATE SKIP LOCKED`, stale lease recovery, lease-owner validation, allowed state transitions, attempt/deadline bounds, exact `next_attempt_at`, tool invocation uniqueness, canonical argument hashing, and all side-effect replay decisions.
- [x] **Step 2: Run the focused tests.** Expected: FAIL because run/tool service methods are absent.
- [x] **Step 3: Implement start/update/claim and the replay classifier.** Use one database transaction per state transition. The classifier must return `repeat_read`, `restore_result`, `retry_not_delivered`, or `block_uncertain`; it must never return an executable decision for a succeeded or delivery-uncertain mutation.
- [x] **Step 4: Re-run focused tests, including a two-connection concurrent claim case.** Expected: exactly one claimant receives the oldest eligible run.
- [x] **Step 5: Commit:** `feat: persist Sydney continuation runs`.

## Task 6: Expose protected context endpoints and action audits

**Files:** Create `backend/routers/agent_control_context.py`, `backend/tests/test_sydney_context_router.py`; modify `backend/main.py`, `backend/routers/agent_control.py`, and `backend/tests/test_agent_control_auth.py`.

- [x] **Step 1: Write failing HTTP tests** for master-flag disabled, agent-control disabled, missing/wrong/correct bearer token, ingest replay, retrieve flag separation, history search, run start/update/claim, strict validation, sanitized failures, and one content-free action audit per completed request.
- [x] **Step 2: Run the router tests.** Expected: FAIL because routes/actions are absent.
- [x] **Step 3: Add exact routes:**

```text
POST /api/v1/agent-control/context/events/batch
POST /api/v1/agent-control/context/retrieve
POST /api/v1/agent-control/context/history/search
POST /api/v1/agent-control/context/runs/start
POST /api/v1/agent-control/context/runs/update
POST /api/v1/agent-control/context/runs/claim
GET  /api/v1/agent-control/context/health
```

Append exact action IDs `context.events.ingest`, `context.retrieve`, `context.history.search`, `context.runs.start`, `context.runs.update`, `context.runs.claim`, and `context.health.read`. The health route returns canonical counts, oldest eligible run age, retry-state counts, checkpoint lag, last reconciliation metadata, and feature-flag state without identifiers or content. Audit metadata may contain counts, UUIDs, latency, tokens, and result classes only—never text, external IDs, tool arguments, or errors.
- [x] **Step 4: Run context router, agent-control auth, transactional-audit, and OpenAPI registration tests.** Expected: all pass and every route is mounted once.
- [x] **Step 5: Commit:** `feat: expose Sydney context control API`.

## Task 7: Add explicit Command search and audience preview

**Files:** Create `backend/schemas/agent_control_command.py`, `backend/services/agent_control_command.py`, `backend/routers/agent_control_command.py`, `backend/tests/test_agent_control_command.py`; modify `backend/main.py` and `backend/routers/agent_control.py`.

- [x] **Step 1: Write failing tests** for name/email/phone general query, stage, tag IDs, source, origin, page size at most 25, deterministic pagination, current primary contact methods, exact result count, masked sample, stable audience checksum/reference, no draft/send/mutation, Command-only outage behavior, and content-free audits.
- [x] **Step 2: Run the focused tests.** Expected: FAIL because the protected Command routes are absent.
- [x] **Step 3: Implement the adapter over the existing `ContactDirectoryFilters` and `list_contacts`.** Return only contact ID, display name, current primary email/phone, stage, source/origin values, and tag names. Audience preview re-runs the same bounded server-side filters, computes the exact count plus a domain-separated SHA-256 checksum over ordered contact IDs, derives an opaque UUIDv5 audience reference from that checksum, and returns at most five masked sample rows. It does not persist recipient data or grant send authority.
- [x] **Step 4: Add routes and action IDs:**

```text
POST /api/v1/agent-control/crm/command-contacts/search
POST /api/v1/agent-control/crm/command-contact-audiences/preview
crm.command_contacts.search
crm.command_contact_audiences.preview
```

- [x] **Step 5: Re-run the focused tests and existing Command service/router tests touched by imports.** Expected: all pass.
- [x] **Step 6: Commit:** `feat: add Command contact tools for Sydney`.

## Task 8: Add checkpoint projection behind its own worker flag

**Files:** Create `backend/services/sydney_context_projection.py`, `backend/workers/jobs/sydney_context_projection.py`, `backend/tests/test_sydney_context_projection.py`; modify `backend/workers/integration_worker.py`, `backend/config.py`, and `backend/tests/test_integration_worker.py`.

- [x] **Step 1: Write failing tests** for disabled-by-default registration, bounded source range, strict Pydantic/JSON schema, mandatory source-event provenance, rejection of foreign/missing IDs, canonical fact supersession, immutable checkpoint insertion, low output limit, Gemini health pause, and raw-history operation when projection fails.
- [x] **Step 2: Run projection and worker tests.** Expected: FAIL because the job is absent.
- [x] **Step 3: Implement `SydneyContextProjectionResult` with exact structured fields and `extra='forbid'`.** Build a bounded transcript from committed events, call Gemini through the existing structured-output client pattern, validate every returned source ID against the claimed range, insert a checkpoint/fact operations in one transaction, and record only bounded health categories. Never call tools or mutate CRM data.
- [x] **Step 4: Register `sydney_context_projection` with a deterministic 60-second schedule only when both durable context and projection flags are enabled. Update `EXPECTED_MIGRATION` to `85e8b7c9d4f1`.**
- [x] **Step 5: Re-run projection, worker, deployment-contract, and integration-health tests.** Expected: all pass.
- [x] **Step 6: Commit:** `feat: project Sydney context checkpoints`.

## Task 9: Extend the MCP registry without changing the existing 22 tools

**Files:** Modify `hermes/atlas_backend_mcp.py`, `hermes/verify_atlas_tools.py`, `hermes/overlay/manifest.json`, `backend/tests/test_atlas_backend_mcp.py`, `backend/tests/test_verify_atlas_tools.py`, and `backend/tests/test_hermes_overlay.py`.

- [x] **Step 1: Change tests first** so the original 22 names remain byte-for-byte ordered and these three unique read tools are appended: `context_history_search`, `command_contacts_search`, `command_contact_audience_preview`. Assert the registry has exactly 25 unique tools and all trusted-write/actual-send additions remain absent.
- [x] **Step 2: Add schema/mapping tests** for history query/date/type/window modes, Command filters/pagination, audience preview, secret-free backend errors, and the exact descriptions. `contacts_search` must say “Google Contacts only; never Command.” `command_contacts_search` must say “Command only; never Google Contacts or the admin UI.”
- [x] **Step 3: Run the MCP/overlay/verifier tests.** Expected: FAIL because the registry still contains 22 tools.
- [x] **Step 4: Append the three tool specs and update the verifier/manifest exact-order contract.** Do not rename, reorder, or remove any current tool.
- [x] **Step 5: Re-run the focused suite.** Expected: all pass with `count=25`, `unique_count=25`, `original_22_unchanged=true`.
- [x] **Step 6: Commit:** `feat: expose Sydney context and Command reads`.

## Task 10: Add the Hermes local spool and durable memory provider

**Files:** Create `hermes/overlay/sydney_spool.py`, `hermes/overlay/sydney_memory_provider.py`, `backend/tests/test_sydney_spool.py`, `backend/tests/test_sydney_memory_provider.py`.

- [x] **Step 1: Write failing tests** for mode-0600 SQLite WAL creation, one-transaction inbound-event/run enqueue, backend acknowledgement, crash/reopen recovery, ordered drain, bounded batches, exact replay, tool-before/tool-after records, cached context fallback, session lineage rotation, and provider prefetch/sync behavior.
- [x] **Step 2: Run the focused tests.** Expected: FAIL because spool/provider modules are absent.
- [x] **Step 3: Implement a `SydneySpool` with explicit schema version and transactions.** Store redacted event JSON, run transitions, tool ledger rows, acknowledgement state, attempt timestamps, cached context packet, and reconciliation cursor under `${HERMES_HOME}/sydney_spool.db`. Never store backend bearer tokens or unredacted content. Use `PRAGMA journal_mode=WAL`, `synchronous=FULL`, busy timeout, foreign keys, and an exclusive migration transaction.
- [x] **Step 4: Implement `SydneyMemoryProvider(MemoryProvider)`.** `initialize` binds stable platform/user/chat/session identity and starts a bounded drain thread; `prefetch` synchronously returns the fresh or cached source-linked packet under 16,000 tokens; `sync_turn` extracts only new visible messages/tool records and queues idempotent batches; `on_session_switch` records continuation lineage; shutdown drains within a fixed deadline. Its history tool delegates to the backend MCP contract rather than querying raw PostgreSQL.
- [x] **Step 5: Re-run spool/provider tests, interrupt a subprocess after its local commit, reopen it, and prove the queued row drains exactly once.** Expected: all pass.
- [x] **Step 6: Commit:** `feat: add Sydney local context spool`.

## Task 11: Add bounded Gemini retry, prompt budgets, and tool-ledger hooks

**Files:** Create `hermes/overlay/sydney_retry.py`, `backend/tests/test_sydney_retry.py`; later copied/installed through `hermes/overlay/install_sydney_overlay.py`.

- [x] **Step 1: Write failing tests** for structured `RetryInfo`, `Retry-After`, absolute reset, `retry in 47s`, `retry after 47 seconds`, milliseconds, unknown delay, retryable/nonretryable status classes, two immediate retries maximum, jitter bounds, 24-hour deadline, rolling 500,000-token budget, 96,000-token compression threshold, 16-turn ceiling, and side-effect decisions from Task 5.
- [x] **Step 2: Run the retry tests.** Expected: FAIL because `sydney_retry` is absent.
- [x] **Step 3: Implement pure parsing/classification primitives** `parse_retry_delay(error, now) -> timedelta | None`, `classify_retry(error) -> Literal['retry', 'continue_context', 'terminal']`, `next_retry(attempt, provider_delay, rng) -> timedelta`, and a timestamped `RollingInputBudget`. Provider delay wins over fallback. Unknown transient delays use bounded exponential backoff plus jitter. Application-level immediate retries stop after two; longer waits become `waiting_retry`. Error copy says the request is saved and will continue automatically and never mentions `/new`, `/reset`, or `/compact`.
- [x] **Step 4: Re-run the focused suite.** Expected: all pass, including `retry in 47s` yielding exactly 47 seconds before jitter-free provider scheduling.
- [x] **Step 5: Commit:** `feat: add automatic Sydney continuation policy`.

## Task 12: Pin and patch exact Hermes 0.15.2 source reproducibly

**Files:** Create `hermes/overlay/install_sydney_overlay.py`, `hermes/overlay/sydney_backfill.py`, `backend/tests/test_sydney_backfill.py`; modify `hermes/overlay/manifest.json`, `hermes/overlay/apply_overlay.py`, `hermes/overlay/atlas_backend_bootstrap.py`, `backend/tests/test_hermes_overlay.py`.

- [x] **Step 1: Write failing overlay tests** that require template commit `7224d7c1a4dcffe9304f49bc843f55716f5561b4`, official Hermes tag `v2026.5.29.2`, official commit `77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5`, expected SHA-256 for every patched upstream file, atomic/idempotent application, unrelated-dirty rejection, and rollback on injected replace failure.
- [x] **Step 2: Write failing behavior tests against a detached exact upstream checkout** proving `retry in` parsing, inbound spool-before-model order, executor before/after hooks, durable prefetch registration, session-reset mode none, compression/turn/loop budgets, and absence of reset instructions in transient error copy.
- [x] **Step 3: Run overlay/backfill tests.** Expected: FAIL because the official source pin and installer are absent.
- [x] **Step 4: Extend the manifest with exact upstream repository/tag/commit and source-file hashes.** The installer accepts only that checkout, verifies all hashes before mutation, copies the three Sydney modules plus backfill utility, and applies small anchor-checked patches to `agent/credential_pool.py`, memory registration, gateway inbound handling, the continuation-claim poller, usage-metadata accounting, and the central tool executor. It validates every anchor before replacing any file and supports exact desired-state no-op. The continuation poller restores the original inbound event, completed tool results, and current durable context; it appends only a continuation marker and sends one final Telegram response.
- [x] **Step 5: Extend bootstrap config** while preserving unrelated values:

```yaml
session_reset:
  mode: none
agent:
  max_turns: 16
compression:
  enabled: true
  threshold: 0.08
  target: 0.02
  protect_last: 20
  abort_on_summary_failure: true
tool_guardrails:
  enabled: true
  exact_failure_limit: 5
  same_tool_failure_limit: 8
  no_progress_limit: 5
memory:
  provider: sydney
```

Only enable the provider when the master environment flag, backend URL/token, and allowlisted Brandon identity are all present.
- [x] **Step 6: Implement `sydney_backfill.py`** to read `state.db` in bounded ordered pages, omit hidden reasoning fields, redact before enqueue, preserve message/tool IDs, deduplicate by source key, persist its cursor, and emit content-free reconciliation JSON with session/role/tool counts and ordered hashes.
- [x] **Step 7: Apply twice to detached exact template and Hermes checkouts, run upstream-focused tests both times, and verify the second run changes no bytes.** Expected: all pass and unrelated files remain pristine.
- [x] **Step 8: Commit:** `feat: install Sydney durable context in Hermes`.

## Task 13: Add end-to-end contracts, CI, and operator documentation

**Files:** Create `backend/tests/test_sydney_context_e2e.py`; modify `.github/workflows/gmail-sydney-task-intake.yml`, `hermes/README.md`, `docs/deployment/hermes-railway.md`, `tdtn.md`, and `memory.md`.

- [ ] **Step 1: Write a deterministic no-network E2E** for inbound spool -> backend ingest -> retrieval -> read-only Command search -> tool ledger -> assistant event -> session continuation -> recall. Add synthetic `429 retry in 2s` -> persisted wait -> process restart -> one claim -> one final response, and prove zero Gmail/calendar/CRM writes.
- [ ] **Step 2: Add exact new test paths and migration `85e8b7c9d4f1` to the existing PostgreSQL/TLS workflow.** Keep previous Gmail/Sydney, MCP, frontend, and migration jobs intact. Add a detached exact-Hermes overlay job and verify 25-tool JSON-RPC output.
- [ ] **Step 3: Run all task-specific tests, then the recorded backend/frontend baseline commands.** Every new/modified task test must pass; backend failures must not exceed the recorded 17 unrelated failures; frontend remains 661 passed/typecheck green; touched-file checks pass.
- [ ] **Step 4: Document exact flags, data boundaries, backup/migration order, shadow/backfill/reconcile/retrieval/retry enablement, health queries, rollback, and content-free acceptance evidence.** Update `tdtn.md` and `memory.md` in the same commit as required by `AGENTS.md`.
- [ ] **Step 5: Commit:** `docs: document Sydney durable context rollout`.

## Task 14: Review, merge, deploy, backfill, and prove production behavior

**Files:** No source changes except review fixes and final evidence updates.

- [ ] **Step 1: Run `git diff --check`, secret scan, task-specific tests, migration sole-head check, exact overlay idempotence, and JSON-RPC `tools/list`. Use `superpowers:verification-before-completion` and request code review before opening the PR.**
- [ ] **Step 2: Push `codex/sydney-durable-context`, open a PR with design/plan/testing/rollout details, wait for required checks, address review test-first, and merge only with the reviewed head SHA.**
- [ ] **Step 3: Create a mode-0600 PostgreSQL custom-format backup outside the repository, validate its catalog, record only its path/size/hash, and verify production `alembic current` is `84d7a5f9b2c3` before applying sole head `85e8b7c9d4f1`.**
- [ ] **Step 4: Deploy backend and worker with all four new flags false.** Verify deployment `SUCCESS`, backend health, worker `/health` and `/ready`, sole migration head, and no active context jobs.
- [ ] **Step 5: Enable master write-only shadow mode for Brandon, deploy the exact-pinned Atlas image, and inspect the live runtime.** Live JSON-RPC `tools/list` must return exactly 25 ordered unique names with the original 22 unchanged. Verify local spool exists on `/data`, mode is private, session reset is none, turns are 16, compression/loop controls match the plan, and both services remain healthy.
- [ ] **Step 6: Run backfill inside `atlas-agent` and repeat until reconciliation reports no unacknowledged rows.** Compare session/message/role/tool counts, each session hash, and one ordered global hash. Keep retrieval disabled on any mismatch.
- [ ] **Step 7: Enable retrieval canary and run benign production checks:** unique private fact -> ordinary recall; internal continuation -> recall; `atlas-agent` restart -> recall; old-history search -> source-linked excerpt; known Command contact -> Command tool; audience preview -> count/checksum/masked sample. Verify no Google-Contacts substitution, UI scraping, email, calendar, or CRM mutation.
- [ ] **Step 8: Enable projection, wait for a valid source-linked checkpoint, and verify retrieval remains correct if projection is then temporarily disabled.**
- [ ] **Step 9: Enable retry canary and inject a safe synthetic short `429`.** Restart during the persisted wait; verify one acknowledgement, FIFO continuation, one eventual response, exact parsed delay, and no duplicate tool invocation or side effect.
- [ ] **Step 10: Enable full durable context for Brandon, monitor content-free health, add exact deployment/reconciliation/acceptance evidence to `tdtn.md`, `memory.md`, and the runbook, commit/push the documentation evidence if needed, and leave rollback switches documented.**

## Verification Commands

Focused backend/Hermes gate:

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:5432/test \
  GEMINI_API_KEY=test-only-key PYTHONPATH=. ../backend/.venv/bin/pytest -q \
  tests/test_sydney_context_redaction.py \
  tests/test_sydney_context_models.py \
  tests/test_sydney_context_service.py \
  tests/test_sydney_context_retrieval.py \
  tests/test_sydney_context_runs.py \
  tests/test_sydney_context_router.py \
  tests/test_sydney_context_projection.py \
  tests/test_agent_control_command.py \
  tests/test_sydney_spool.py \
  tests/test_sydney_memory_provider.py \
  tests/test_sydney_retry.py \
  tests/test_sydney_backfill.py \
  tests/test_sydney_context_e2e.py \
  tests/test_atlas_backend_mcp.py \
  tests/test_hermes_overlay.py \
  tests/test_verify_atlas_tools.py
```

PostgreSQL contract gate:

```bash
cd backend
GMAIL_TASK_TEST_DATABASE_NAME=brandon_gmail_sydney_test \
GMAIL_TASK_TEST_DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL" \
PYTHONPATH=. ../backend/.venv/bin/pytest -q \
  tests/test_sydney_context_migration.py \
  tests/test_sydney_context_postgres.py \
  tests/test_sydney_context_e2e.py
```

Repository gates:

```bash
git diff --check
cd backend && alembic heads
cd ../frontend && npm test -- --reporter=dot && npm run typecheck
```

## Rollback Boundaries

- Disable `SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED` to stop automatic claims without losing queued runs.
- Disable `SYDNEY_DURABLE_CONTEXT_PROJECTION_ENABLED` to stop Gemini projection while raw ingest/search continue.
- Disable `SYDNEY_DURABLE_CONTEXT_RETRIEVAL_ENABLED` to return Hermes to local transcript/search while canonical writes continue.
- Disable `SYDNEY_DURABLE_CONTEXT_ENABLED` to stop all new backend context traffic; the local spool retains unacknowledged events.
- Roll back the Atlas image to the prior known-good deployment if the overlay is unhealthy. Do not delete `state.db`, `sydney_spool.db`, canonical events, backfill evidence, or migration tables during operational rollback.

## Completion Gate

Development is complete only after the Task 14 production evidence exists. A green local suite, merged PR, healthy deployment, unreconciled backfill, or configured-but-unused flag is not by itself completion.
