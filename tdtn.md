# Things Done Till Now

## Project: Brandon Real Estate AI Platform
Last Updated: 2026-08-26

### 2026-08-26 - Sydney Durable Context Task 14 Production Completion
- Completed Task 14 in production. The feature release and every test-first rollout correction merged through PRs `#14`-`#23`; the final production source is merge `28a5764214da02efaf6e0613717b33dc1726f85c`, which contains the reviewed projection fix `04081eea7dc2b5e6c16f49d20867fe8345829aab`. PR `#23` passed the exact Hermes/25-tool, Command frontend, Vercel, and real PostgreSQL 16/TLS persistence/concurrency/E2E gates before the SHA-pinned merge.
- Preserved the protected pre-migration backup at `/Users/rishabnandi/brandon-real-estate-production-backups/sydney-task14-pre-migration-20260826T180513Z.dump`: mode `0600`, `516102115` bytes, SHA-256 `8a200bba3ca51af9eba43e028a838b90eaaf4ef51553a33e77c8c7b7a2252847`, and a PostgreSQL 17 `pg_restore --list` catalog of `732` entries. Production `alembic current` and `alembic heads` both report sole head `85e8b7c9d4f1`.
- Final Railway deployments reached `SUCCESS` from exact main: backend `aa4a1ae3-36a5-4524-9e96-5d0d91223836`, worker `957d12c3-dfbe-4470-877d-d2e26e5b929c`, and Atlas `34932fbf-e916-4032-97fa-50b9d477a815`. Backend and worker health, worker readiness, Atlas health, and the single gateway process pass. Live JSON-RPC `tools/list` returns exactly 25 ordered unique tools, preserves the original 22, requires UUID `gmail_send.request_id`, and exposes no forbidden write tool.
- The exact backfill proof remains compacted and matched: `8` sessions, `918` messages, `947` events, roles `assistant=442`, `tool=455`, `user=21`, `455` tool calls/results, zero unacknowledged rows, and identical source/acknowledged ordered hash `9c7c960a59b959e13faa317fda987193d60b8416367212da249c4281a73be689`. After live continuation, content-free health reports `14/14` reconciled sessions, `1092` canonical events, zero unreconciled sessions, no eligible run, and status `ready`.
- Retrieval and read-only acceptance passed without reset commands: the latest automatic packet has five source-linked sections, `37` unique source references, and `15979` estimated tokens; bounded history search returned five event-ID-linked excerpts. Command-only contact search and audience preview returned an exact `20`-record audience, a valid checksum/reference, five fully masked samples, and only Command sources. No Google Contacts fallback, UI scraping, email, calendar, CRM mutation, or write tool was used.
- The controlled synthetic `429` proof persisted attempt `1` and an exact `45`-second delay, delivered one acknowledgement, survived the Atlas container restart, then succeeded once on attempt `2`. PostgreSQL proves one exact final assistant event/reference/hash, one acknowledgement event/hash, zero tool invocations, a released lease, cleared provider/error fields, and no unresolved state. The private spool is clean: zero pending, active, claimed, or final-delivery records; the synthetic marker and exact temporary recovery/verifier files were removed.
- Final health inspection found a real projection compatibility gap: Gemini deterministically returned a valid `32/33` ordered source echo with one interior omission. PR `#23` now binds only that exact safe case to the server-owned committed range while still rejecting endpoint/multiple omissions, reordering, duplicates, foreign IDs, and inconsistent fact citations. Local verification passed `112` wider context/runtime tests with one expected database-only skip; production then advanced checkpoints `16 -> 17`, facts `14 -> 15`, cleared `23` prior failures to zero, released the range claim, and changed protected context health from `degraded` to `ready`. The bounded backlog continues asynchronously while raw source-linked retrieval remains available.
- All feature gates are fully promoted in their owning services: backend has master/retrieval/projection/retry enabled; worker has master/projection enabled with retrieval/retry disabled; Atlas has master/retrieval/retry enabled with projection disabled. The backup and canonical context evidence are intentionally retained. Task 14 is complete.

### 2026-08-26 - Sydney Durable Context Task 14 Development Gate
- Completed the pre-release Task 14 review and verification gate on `codex/sydney-durable-context`. The final review fixes preserve the newest recent events at whole-event boundaries, pass trusted structured boundaries directly from retrieval instead of reparsing source-marker text, declare the event full-text vector as server-generated for ORM writes, suppress ambiguous final-delivery replay, and reuse a cutover-bound backfill source report without rescanning lifetime history after restart.
- Independent review reproduced the generated-column failure against a migrated PostgreSQL schema and found the long-history newest-event loss. Both were fixed test-first. A focused follow-up review then found that quoted older source markers could confuse text-based boundary recovery; that parser was removed, regressions now cover quoted markers and predecessor-fragment exclusion, and the final focused re-review reported no actionable correctness, provenance, or token-budget issue.
- Final development evidence on the exact reviewed state: the 24-file changed-test matrix passed `757` with `5` expected exact-checkout skips; the separate Atlas bridge suite passed `16/16`; the exact template/Hermes gate passed `227/227` at template `7224d7c1a4dcffe9304f49bc843f55716f5561b4` and Hermes `77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5`; the real JSON-RPC verifier returned exactly 25 ordered unique tools with the original 22 unchanged and UUID `gmail_send.request_id` required. PostgreSQL 17/TLS, focused Ruff, compileall, `git diff --check`, the credential scan, and sole Alembic head `85e8b7c9d4f1` are green.
- This entry is pre-release evidence only. At this point no Task 14 commit, push, PR, merge, production backup, migration, deployment, flag change, backfill, canary, Telegram message, or external write had occurred. Production evidence is recorded separately only after each live gate succeeds.

### 2026-08-25 - Sydney Durable Context Development Through Task 13
- Completed the approved durable-context implementation through Task 13 on isolated branch `codex/sydney-durable-context`. PostgreSQL is the canonical cross-session history; Hermes keeps its existing `state.db`; a private mode-0600 SQLite WAL spool saves redacted inbound events before any backend/model call and retains pending acknowledgements, cached context, run state, and tool receipts across restart.
- Added strict authenticated context ingest, retrieval/history, projection, run/lease, tool-ledger, content-free health, and exact session-reconciliation contracts at sole Alembic head `85e8b7c9d4f1`. Authoritative ingest receipts carry event ID/type/time/content hash; reconciliation succeeds only when the caller's exact count and timestamp/UUID-ordered hash match PostgreSQL. Any later event clears the old marker until Atlas acknowledges and re-reconciles the complete receipt set.
- The exact Hermes template commit `7224d7c1a4dcffe9304f49bc843f55716f5561b4` installs against official Hermes tag `v2026.5.29.2`, commit `77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5`. The overlay is atomic, hash-pinned, dirty-tree rejecting, rollback-safe, and byte-stable on a second application. Runtime policy keeps one logical Brandon conversation across compression/session switches, automatic 16,000-token recall, 16 turns, bounded compression/rolling input, hard tool-loop stops, and saved automatic continuation without asking Brandon to use `/new`, `/reset`, or `/compact`.
- Existing history backfill is bounded, idempotent, identity-filtered, hidden-reasoning-free, and credential-redacted. Its `--reconcile` gate drains only owned `backfill:` rows, exits nonzero unless unacknowledged rows are zero, compares session/message/event/role/tool-call/tool-result totals and the ordered global hash, and proves every opaque session hash against canonical PostgreSQL. Retrieval remains disabled on any mismatch.
- Added a deterministic no-network E2E covering local-before-backend inbound durability, source-linked recall, Command-only read, tool ledger, assistant completion, session continuation, restart-persisted `429` wait, one due claim/final response, and zero Gmail/Calendar/CRM writes. CI keeps the prior Gmail/Sydney/PostgreSQL 16 TLS and frontend jobs, adds all context contracts, enforces sole head `85e8b7c9d4f1`, verifies fresh exact template/Hermes sources, and runs live-format JSON-RPC against the exact ordered 25-tool registry.
- Independent Task 14 review found and development fixed seven pre-release gaps: recursively redacting secrets in encoded redirects, classifying transport exception types for retry, excluding backfilled history from later full-transcript sync, deduplicating mutating intent across regenerated model call IDs, fencing tool transitions with the exact live run lease, retaining redacted failed-tool results, and hiding the prefixed MCP history variant from the model. Canonical call-ID aliasing keeps a proven `not_delivered` retry on the original ledger row.
- Fresh post-review development evidence: the combined 17-file Task 9 gate passes `227/227` against PostgreSQL 17 with TLS plus fresh exact pinned Hermes and template checkouts; the PostgreSQL durability/concurrency file passes `11/11`; exact overlay behavior passes `16/16`; focused Ruff and `git diff --check` pass. This is still pre-release evidence: no PR, merge, production migration, deployment, flag enablement, backfill, Telegram message, or external write has occurred from these fixes.
- Fresh development evidence: the complete Sydney-focused gate passed `148` with `10` expected local PostgreSQL skips; reconciliation/spool/provider/backfill/E2E checks passed `35/35`; scoped Ruff passed; workflow YAML parsed; full frontend passed `661/661` and TypeScript; the full backend returned exactly the recorded unrelated baseline, `2472 passed, 689 skipped, 3 deselected, 17 failed`. The PostgreSQL/TLS context cases are fail-closed in CI and cannot skip there. No PR, merge, migration, production deployment, flag enablement, backfill, Telegram message, or external write occurred in Task 13. Task 14 owns review, PR/merge, protected backup, production migration/deploy, controlled rollout, live backfill/reconciliation, and acceptance proof.

### 2026-08-24 - Command Task Bulk Selection and Archive
- Added 25-task pagination to the Command Tasks workspace plus accessible individual selection, current-page selection, and an explicit second step to select every task matching the active filters across all pages. Selection persists between pages, resets when visibility or filters change, and successful bulk removal clamps the current page.
- Added one authenticated, feature-flagged `POST /api/v1/command/tasks/bulk-archive` contract. It accepts at most 500 unique task/request identities, processes tasks in stable ID order through the existing `crm_task_service.archive`, preserves each optimistic version and UUID lifecycle identity, trims one shared reason, and returns a distinct archived/conflict/not-found/invalid result for every task.
- Bulk confirmation is reversible and server-authoritative. Successful tasks move to Archived; conflicted or rejected tasks remain selected with named failure details. A transport-uncertain result performs exactly one authoritative all-task refresh and never automatically resends the archive command.
- Fresh verification: focused bulk backend route/schema checks passed `9`, with the real PostgreSQL replay check safely skipped because this shell has no isolated `_test` database; the complete task API file passed `21` with `92` database-backed skips. The focused frontend bulk/API/workspace checks passed `97/97`, the full frontend passed `661/661`, TypeScript and touched-file ESLint passed, and the 36-page production build completed. No deployment, production API call, database write, migration, or feature-flag change occurred.

### 2026-08-24 - Task 9 Gmail/Sydney Controlled Production Rollout
- Completed the three Brandon-approved controlled production paths without using a client conversation. The received Gmail fixture became exactly Task `454`; the caller-UUID Agent Control sent commitment became exactly Task `455`; the direct Sydney draft asked one Telegram clarification, resumed after one answer, and became exactly Task `456` only after Brandon opened Command and clicked **Approve task**. Every input replay kept one suggestion, one creation request, one task source, and one task; final production totals were 456 tasks, 16 suggestions, three creation requests, and three task sources.
- The controlled received receipt is `eb82b845-c616-421f-b5d1-dba955e99b4f`, suggestion `f9a333f6-0b3e-4e05-bb96-f8494adfd282`, final hash `80309124002cb9752b75845b82b73c246489250da914a02a5289caba2ea207cc`, and edit/approve audits `215`/`216`. The controlled sent receipt is `4db4edae-e040-4d6b-ab25-4611428948f3`, suggestion `f592e23a-4692-4c24-b9fc-ed2c24a0fea6`, final hash `fea579ba02be818178b2d6d7fbf12e95d2124a893bd1e419580091dae643736f`, send/edit/approve audits `187`/`217`/`218`, and the same UUID replay returned the same Gmail message/thread. Direct Sydney suggestion `7e10f85b-fe97-416d-ac4b-d1386a2c38a9` used clarification `420aaf01-6663-4439-8aac-404f8166f799`, outbox `36ad52c7-9346-4b54-90b1-18673ea3566d`, Telegram message `88`, final hash `712501a991739de609fd651243950344b2c64ec9eb2754234a9a931941dcf3b7`, and draft/answer/link/approve audits `219`/`220`/`235`/`236`.
- Fixed the production handoff-link defect so Agent Control now returns an absolute `https://www.soldwithsweeney.com/admin/command/task-suggestions...#handoff=...` URL while keeping the one-time value only in the fragment. Fix `68d4db2` merged through PR #11 as exact main `ca544e6dc9e99c08b3cd9b2c498eefd0774d1cf5`; all CI passed and backend/worker deployments reached `SUCCESS` on that merge.
- Performed the required rollback after evidence collection. Backend deployment `c46df9ff-d4c1-48a5-8b3b-adb29e3b43af` and worker deployment `e4efa174-0d7b-4623-8f05-afbb8246d980` are healthy on `ca544e6`; both services explicitly set `GMAIL_TASK_INTAKE_ENABLED=false`, `SYDNEY_TASK_QUESTIONS_ENABLED=false`, and `INSTAGRAM_INTEGRATION_ENABLED=false`; backend also explicitly sets `COMMAND_PUBLIC_BASE_URL=https://www.soldwithsweeney.com`. Worker `/health` and the exact repository-owned `/ready` probe pass, and its current job is null.
- One unrelated Gmail provider-deletion incident arose after all controlled fixtures. It remains pending and alerted, its account/run retain `message_not_found` recovery state, and it was deliberately not acknowledged from database evidence alone. Gmail intake stays disabled until an authorized operator verifies the exact provider message returns `404` and completes same-run recovery. The complete worker configuration, probes, rollout/rollback, final-page cursor and reseed/backfill process, Telegram uncertain-delivery process, live Atlas gate, controlled IDs, and blocker are in `docs/deployment/gmail-sydney-task-intake.md`.

### 2026-08-23 - Task 8 Hermes Review-Tool Production Rollout
- Completed Gmail/Sydney plan Task 8. Task 8 source commit `a53ff04421c395be54012398cc1dccecddf08f97` shipped through PR #5 at merge commit `f3ed543359cac39c3caa66dd3d25592319f1b921`; the exact main workflow run was green. Railway backend deployment `e29cfc64-5b2d-4265-ad9d-0e0d7d00a226` and Atlas deployment `51f50a75-32ed-4ed7-bd88-5dc5bfde0988` both reached `SUCCESS`, and their public health endpoints returned HTTP 200.
- Cleared the rollout dependency first with authenticated production Task 7 evidence. The fragment-only handoff was removed before exchange network activity, exchange returned 200, the separate Approve button remained required and was not clicked, query-carried secrets were rejected and stripped, and both controlled suggestions were dismissed through the real UI. The production CRM task total remained 453, pending review count returned to zero, both fixture rows have `applied_task_id=null`, and the smoke produced zero HTTP 5xx, runtime exceptions, console errors, or related production log errors.
- Built the Atlas image from pinned upstream Hermes commit `7224d7c1a4dcffe9304f49bc843f55716f5561b4` with the repo overlay applied reproducibly. Overlay hashes were stable across a second application, `git diff --check` passed, and the focused local MCP/overlay/live-verifier suite passed `26/26`. The merged GitHub Task 8 workflow also passed its exact PostgreSQL/TLS job; the separate local full PostgreSQL attempt remained environment-blocked because the Homebrew server rejected mandatory TLS and was not reported as green.
- Fresh Member-level Railway SSH connected to the deployed `atlas-agent`. `hermes mcp test atlas_backend` discovered 22 tools. The checked-in `hermes/verify_atlas_tools.py` raw JSON-RPC probe returned exactly 22 ordered unique names, preserved all original 16 names unchanged, appended the exact six CRM review tools once, required UUID `gmail_send.request_id`, and exposed none of `crm_task_suggestions_dismiss`, `crm_task_suggestions_approve`, `crm_tasks_create_confirmed`, `crm_tasks_archive`, or `crm_tasks_restore`.
- Historical Task 8 authentication note: the then-saved Railway token was unauthorized, so that rollout used the directly authenticated Member CLI with both token variables unset. On 2026-08-26 the ignored `.env.railway-sweeney.local` account/workspace token was replaced and verified with Member SSH/deployment access; `scripts/railway-sweeney` is valid again when live project/service checks pass. The backend service ID is `37afead7-c55b-4ef2-8071-ca4da1c88992`.
- Safety boundary: `GMAIL_TASK_INTAKE_ENABLED=false`, `SYDNEY_TASK_QUESTIONS_ENABLED=false`, and `CRM_TASK_ARCHIVE_ENABLED=false` remain unchanged. No real suggestion was approved, no confirmed task was created, and actual approve/dismiss/create-confirmed/archive/restore tools remain absent. Next: Task 9, the only remaining numbered task in this plan.

### 2026-08-22 - Command Task-Suggestion Review Workspace
- Completed Gmail/Sydney plan Task 7 locally. Command now has one authenticated `/admin/command/task-suggestions` destination and a dark SWS review workspace with loading, empty, error, clarification, timed-out/manual, blocker, stale-write, dismissal, terminal, keyboard/focus, preview, handoff, and approval states. It uses the existing shared navigation registry and exposes no native `prompt()` or `confirm()` flow.
- Strict frontend decoders and Command summaries expose bounded confidence/rationale/schema provenance, at most 20 source summaries, at most 20 audit summaries, and a unique five-value `resolution_requirements` contract. Owner ambiguity, taxonomy fallback, unsupported links, multi-action evidence, and live duplicates now render only their applicable explicit decisions. Duplicate requirements use the same current-version audited validator as approval, and Prepare stays disabled while any authoritative requirement remains.
- Sydney handoff secrets are captured into closure memory by the pre-hydration bootstrap, removed from the fragment before application network activity, and never accepted in query parameters. Query secrets are stripped by Proxy with a safe error; missing or expired admin sessions preserve an unused-link reopen notice without exchanging the secret. Handoff exchange and ordinary Command prepare still produce only an in-memory stage-two nonce and require a later explicit Approve click.
- A successful Approve response is correlated to suggestion, next version, and request UUID. Command then refetches the authoritative applied summary so the new version and `approve`/`apply` audit evidence are visible; a failed post-ACK read keeps a locked terminal fallback at the returned version and removes stale audit display. Lost-response retries reuse the same request UUID.
- Verification: the exact four-file Task 7 gate passed `47/47`; the full frontend passed `647/647`; TypeScript, touched-file ESLint, Next production build, workflow YAML, Ruff format/check, and diff checks passed. Focused real PostgreSQL 16/TLS backend plus workflow contract passed `28/28` with 11 existing Pydantic deprecation warnings. Production-build browser checks proved fragment clearing before API calls, one exchange, no approval before the explicit click, one approval plus authoritative refetch, safe query rejection with zero Command requests, expired-token reopen with zero Command requests, correct owner/duplicate controls, and no tested secret in the DOM, local storage, or session storage. Independent final review found no remaining Critical or Important findings. The exact PostgreSQL 14 and 16 fixtures were stopped, ports `55463`/`55464` were verified closed, and both fixture directories were moved recoverably to Trash.
- Repository baseline: the one required full frontend lint capture remains known-red at `20 errors, 20 warnings` outside the Task 7 scope; it was not treated as a green gate. Rollout boundary: no Vercel/Railway deployment, production API call, migration, CRM task creation, Gmail/Telegram action, or feature enablement occurred. Next: Task 8 Hermes overlay and 22-tool MCP contract; production advertising/deployment remains gated on a separately verified Task 7 rollout.

### 2026-08-22 - Authenticated Sydney CRM Task Review
- Completed Gmail/Sydney plan Task 6 locally. The backend registers 24 protected Task 6 routes exactly once and exposes exactly six bounded Agent Control CRM actions: task and suggestion reads, clarification answers, draft creation, approval-link handoff, and dismissal proposals. Confirmed task creation and actual dismissal remain authenticated Command-only operations.
- Command review now requires explicit resolution of owner, unsupported-link, task-detail, action-scope, and duplicate blockers. Edits and dismissals supersede locked clarifications; approval locks Gmail thread before suggestion, revalidates current contact authority, and creates through `crm_task_service` in the same transaction only after a separate stage-two approval nonce.
- Handoff and approval secrets use `secrets.token_urlsafe(32)`, persist only hashes, rotate to one live handoff, reject malformed values without echo, and use no-store/no-referrer responses. Exact replay remains durable after expiry or later edits, draft insert races converge, and Agent writes are transactionally audited without granting trusted create/dismiss authority.
- Dismissal creates instance-exact suppression evidence. Admin reprocessing consumes an exact receipt-bound suppression override once and emits the reconciler-required audit. Applying legitimate same-thread siblings requires a current-version Command edit plus its exact linked audit containing `confirm_not_duplicate`; unrelated later edits require renewed confirmation.
- Verification: the exact Task 1-through-Task 6 PostgreSQL 16/TLS workflow passed `1192 passed, 35 warnings` in `169.66s`; focused Task 6 passed `37/37`, worker/deployment passed `40/40`, and compatibility passed `252/252`. Ruff format/check, compileall, YAML parse, diff checks, and sole Alembic head `84d7a5f9b2c3` passed. Independent final review found no remaining Critical or Important findings.
- Rollout boundary: no production migration, Railway deployment, live Gmail/Telegram call, confirmed production CRM task, or feature enablement occurred. `GMAIL_TASK_INTAKE_ENABLED=false`, `SYDNEY_TASK_QUESTIONS_ENABLED=false`, and `INSTAGRAM_INTEGRATION_ENABLED=false` remain unchanged. Next: Task 7 authenticated Command task-suggestion workspace.

### 2026-08-22 - Sydney Task Clarification Persistence and One-Question Flow
- Completed Gmail/Sydney plan Task 5 locally. Alembic revision `84d7a5f9b2c3` is the sole head after revision `83` and adds hash-only clarification, Telegram outbox, approval-nonce, and immutable suggestion-event persistence. Downgrade remains evidence-guarded; revision-83 rolling writers use omitted-column sentinels, while explicit invalid authority shapes and duplicate/stale contact changes fail closed.
- Sydney now asks one highest-value consequential question at a time, applies only strict structured answers to the same locked suggestion/version, supersedes old questions after independent source edits, releases the chat slot on terminal states, and enters manual review after five rounds without creating a sixth row. Clarification codes and 32-byte handoff secrets are restart-stable/hash-only in storage; handoff URLs keep the secret in the fragment and create no confirmed CRM task.
- Telegram delivery persists `sending` before the bounded provider call, records immutable sent/failed/uncertain attempts, permits one 24-hour reminder, uses a fixed 48-hour deadline, and allows an explicit retry only after audited `not_delivered` reconciliation. Unknown delivery is never automatically retried, and reminder/retry attempts cannot extend the clarification deadline.
- Contact authority now uses one database-enforced transaction advisory protocol shared by every contact identity insert/update/delete and every inference, clarification, preserved-contact, compatibility, and approval-time reader. Suggestion rows lock before contacts; a real two-session contact-answer/source-update race completes without deadlock; duplicate-email phantoms and rolling-writer contact changes fail with full rollback.
- Verification: the exact Task 1-through-Task 5 PostgreSQL 16/TLS workflow passed `1155 passed, 19 warnings` in `134.67s`; the warnings are unchanged `python-jose` `datetime.utcnow` deprecations. Focused touched suites passed `445/445`; final Ruff, compileall, sole Alembic head `84d7a5f9b2c3`, and diff checks passed. Independent final review found no remaining Critical or Important findings.
- Rollout boundary: no production migration, Railway deployment, live Telegram/Gmail call, confirmed CRM task write, or feature enablement occurred. `GMAIL_TASK_INTAKE_ENABLED=false`, `SYDNEY_TASK_QUESTIONS_ENABLED=false`, and `INSTAGRAM_INTEGRATION_ENABLED=false` remain unchanged. Next: Task 6 authenticated approval and Agent Control CRM tools.

### 2026-08-21 - Gmail Obligation Extraction and Review Suggestions
- Completed Gmail/Sydney plan Task 4 locally. Added a strict bounded `gmail-task-v1` Gemini envelope, separately framed untrusted subject/body evidence, trusted message-time anchoring, finite real-estate semantic taxonomy with explicit review fallback, backend-derived identity/material hashes, and fixed body-free provider/parser errors. Model output never supplies action keys, CRM IDs, contact authority, owner authority, or apply authority.
- Added receipt-lease-fenced, account/thread-locked reconciliation for multiple received requests and sent commitments. Exact semantic evidence attaches idempotently; materially distinct fingerprints become immutable `possible_duplicate` siblings; same-fingerprint text instances remain a `multiple_actions` manual-review container; terminal rows stay immutable. Only an exact unique CRM contact may confer contact identity; unmatched, fuzzy, duplicate, or drifted hints remain transient and fall back to participant HMAC identity.
- Hardened revision `83` before release with append-only obligation/source evidence, exact suggestion-or-suppression dispositions, instance-scoped suppressions, one-use receipt-bound audited reprocess, source/disposition and duplicate-scope composite foreign keys, no-self duplicates, and generic-plan-safe indexes for thread candidates, instance/material membership, taxonomy/contact authority, and succeeded-attempt replay. Candidate and authority reads are bounded and do not rescan unbounded source history.
- Task 4 never creates a confirmed CRM task, task creation request, activity, task link, or lifecycle event. Its `task_payload` helper is an atomic preparation gate only inside the same open transaction after DB-authoritative scope locking and fresh hash/version/state/blocker/contact validation; Task 6 will own authenticated creation in that transaction.
- Verification: PostgreSQL 16.13 with TLS passed migration `40/40`, reconciliation `159/159`, extractor `136/136`, and the touched extractor/History-adapter/executor compatibility slice `236/236`. The exact prior Task 1-through-Task 3 workflow passed `577/577` with 19 existing `python-jose` deprecation warnings. Independent review reran Task 4 `335/335` and returned **QUALITY APPROVED** with zero open Critical/Important findings. Sole Alembic head, py_compile, Ruff, and diff checks passed; the dedicated workflow now includes both Task 4 suites and its contract passed `2/2`.
- Cleanup and rollout boundary: the exact disposable PostgreSQL cluster was stopped, port `55439` closed, and its directory removed. No production migration, Railway deployment, live Gemini/Gmail call, confirmed CRM write, or feature enablement occurred. Task 9 must bind sanitized receipt evidence to the active processing lease, catch fixed invalid-output failures, call `fail_attempt(category="invalid_model_output")`, and prove failed/no-partial-write/bounded-retry behavior. Do not start Task 5 until separately requested.

### 2026-08-21 - Safe Gmail History Intake and Durable Send Origins
- Completed Gmail/Sydney plan Task 3 in implementation commit `a864955` (`feat: ingest Gmail history safely`). Added the typed Gmail History adapter, direct retained-session PostgreSQL lock layer, metadata-first sanitizer and receipt processor, bounded cursor recovery/backfill, durable send-origin protocol, Workspace OAuth binding primitives, and the real Gmail worker job. Revision `83` now includes a twelfth body-free missing-message incident table plus authenticated admin detail/acknowledgement recovery.
- Provider calls are synchronous only inside one bounded shared executor, use socket plus outer deadlines, and are single-attempt at the Google request, token-refresh, HTTP reconnect, and redirect layers. Runtime config and internal claim reprs suppress database/refresh-token secrets; participant identities are HMACed; raw message content and sanitized body text are discarded before consumer-finalization database work or exception/log retention.
- Per-account History runs retain one direct `NullPool` connection and session advisory lock across page commits, prove backend PID/lock ownership before work and release, commit receipt evidence plus checkpoints before final cursor CAS, resume retryable pages, and durably block/alert fatal, malformed, affinity, pagination, cursor, and missing-message states. Bounded seven-day backfill uses exact time filtering and promotes only a completed matching snapshot.
- Durable Gmail sends require a caller UUID and same-transaction intent audit before the sole provider attempt. Canonical unresolved-send uniqueness, predecessor-bound retries, immutable provider message/thread identity, atomic provider-versus-History quarantine, exact candidate verification, one-way quarantine until independent History proof, and origin-to-receipt lock order prevent automatic duplicate sends and stale receipt lifecycle regression.
- Workspace OAuth is DB-authoritative for a bound Gmail account, validates account identity and ID-token audience/issuer/email, rotates token plus binding atomically, and generation-checks provider failures under the same advisory-lock transaction so stale credentials cannot re-block a fresh connection. The worker wires the direct History engine, origin observer, durable notification queue, current-time heartbeat, bounded whole-job cancellation, and deterministic peer cleanup.
- Exact 36-file implementation scope spans the dedicated workflow/env/config, revision `83` and Gmail models/schemas, Workspace and Agent Control boundaries, eight Gmail/shared services, fourteen Task 3 and compatibility test files, worker runtime/job package, and Hermes MCP compatibility. The exact existing 16 Hermes tools remain registered; Gmail send now passes required UUIDs through unchanged.
- Verification: initial real PostgreSQL 16/TLS RED collected `297` tests with `233` intended missing-production failures and zero fixture errors. Final History/origin `154 passed`; final identity/lifecycle race slice `9 passed`; exact Task 1-through-Task 3 workflow `567 passed, 19 warnings` in both implementation and independent review runs; Ruff, compileall/py_compile, diff, and sole-head checks clean. Independent verdicts: **SPEC PASS** and **QUALITY APPROVED**, zero remaining Critical/Important findings.
- Cleanup and rollout boundary: both final disposable PostgreSQL 16/TLS clusters were stopped and removed and disk headroom restored. No live Google call, production migration, Railway deploy, or feature enablement occurred. `GMAIL_TASK_INTAKE_ENABLED=false`, `SYDNEY_TASK_QUESTIONS_ENABLED=false`, and `INSTAGRAM_INTEGRATION_ENABLED=false` remain the rollout boundary. Next: Task 4 structured obligation extraction and suggestion reconciliation.

### 2026-08-21 - Gmail Task Intake Persistence
- Completed Gmail/Sydney plan Task 2 in implementation commit `1a691157` (`feat: persist Gmail task intake`). Alembic revision `83c6f4e8a1b2` is the sole head with direct parent `82b5e3d7f0a1` and adds the eleven locked account, run, checkpoint, receipt, origin, extraction, obligation, suggestion, source, suppression, and backfill tables. ORM metadata remains compatible with both PostgreSQL and the legacy SQLite bootstrap, and no raw email body, OAuth token, or credential column was added.
- Final integrity rules bind Gmail suggestion evidence to the same account and thread through composite keys, keep Gmail reconciliation indexes nonunique and queryable, require canonical lowercase/trimmed workspace email identities, restrict suggestion and suppression sources to `gmail_message|sydney_chat`, globally deduplicate Sydney draft request UUIDs, and bind a backfill request's optional run to the same account. History-inferred human sends are born succeeded; unresolved sends use the exact NULL-safe partial uniqueness predicate; application, obligation, receipt, and direction provenance fail closed when cross-wired.
- Downgrade acquires one deterministic all-table `ACCESS EXCLUSIVE` lock before inspecting evidence, refuses any nonempty owned table without losing intake or existing CRM rows, and permits the empty downgrade. The disposable PostgreSQL helper requires the exact TLS PostgreSQL 16 `_test` database and ownership marker, including optimized-Python cleanup regressions.
- Exact nine-file implementation scope: `.github/workflows/gmail-sydney-task-intake.yml`, `backend/alembic/env.py`, `backend/alembic/versions/83c6f4e8a1b2_add_gmail_task_intake.py`, `backend/models/__init__.py`, `backend/models/gmail_task_intake.py`, `backend/schemas/gmail_task_intake.py`, `backend/tests/test_gmail_task_intake_migration.py`, `backend/tests/test_integration_runtime_migration.py`, and `backend/tests/test_integration_worker_deployment.py`.
- Verification: real PostgreSQL 16/TLS Task 2 `29 passed`; exact dedicated Task 1+Task 2 workflow command `95 passed`; real PostgreSQL CRM lifecycle suite `13 passed`; Ruff, Python compilation, cached diff, and diff checks clean; sole Alembic head `83c6f4e8a1b2`. Independent reviews returned **SPEC PASS** and **QUALITY APPROVED**; quality independently reran `29 passed` and verified zero public relations.
- Cleanup and rollout boundary: the exact disposable database was verified as `brandon_gmail_sydney_task2_test` with zero public relations, its PostgreSQL cluster was stopped, port `55434` closed, and the validated cluster directory was moved recoverably out of `/tmp`. `GMAIL_TASK_INTAKE_ENABLED=false`, `SYDNEY_TASK_QUESTIONS_ENABLED=false`, and `INSTAGRAM_INTEGRATION_ENABLED=false`; no Task 3 adapter/routes, worker registration, production migration, deployment, provider call, or live enablement occurred.

### 2026-08-20 - Shared Integration Worker Runtime
- Completed Gmail/Sydney plan Task 1 in implementation commit `4ffed4c`. Alembic now has sole head `82b5e3d7f0a1` with direct parent `81a4d2c6e9f0`; the generalized revision-81 migration contract remains exact and passes at the later repository head.
- Added a separate integration worker with deterministic `FIRST_COMPLETED` supervision, peer cancellation/awaiting, and exception preference. The scheduler owns boot and heartbeat writes, advances heartbeats independently, and honors each job's `interval_seconds` instead of running every enabled job on every heartbeat.
- `/health` is dependency-free liveness. `/ready` performs bounded, sanitized, read-only checks of PostgreSQL, the sole migration head, fresh scheduler-owned heartbeat, and the initialized registry; SQL-capture coverage rejects readiness DML and stalled providers do not block liveness.
- Notification delivery now claims and commits one row at a time, revalidates ownership/state and renews the lease immediately before provider I/O, and uses a 30-second outer provider timeout strictly below the default 120-second lease. Later rows are not preclaimed; the queue retains explicit at-least-once crash semantics.
- The real PostgreSQL helper fails closed on an exact `_test` database, TLS, PostgreSQL version, empty schema, and cryptographic ownership marker. Destructive cleanup and downgrade require the exact `(1, 1)` ownership tuple even under optimized Python; wrong, missing, duplicate, foreign, or populated ownership states preserve sentinel data.
- Verification: PostgreSQL 16.13 TLS Task 1 suite `66 passed`; developer/no-PostgreSQL mode `33 passed, 33 skipped`; existing CRM lifecycle workflow suite `165 passed`; legacy notification suite `5 passed`; compile and diff checks clean. Independent final reviews: **SPEC PASS** and **QUALITY APPROVED**, with no remaining Critical or Important findings.
- `.github/workflows/crm-task-lifecycle-migration.yml` and `backend/.env.example` remained unchanged because their existing behavior already satisfied Task 1. `GMAIL_TASK_INTAKE_ENABLED=false`, `SYDNEY_TASK_QUESTIONS_ENABLED=false`, and `INSTAGRAM_INTEGRATION_ENABLED=false`; `backend/main.py` remains untouched, no integration loop was added to the web process, and no deployment or production enablement occurred.

### 2026-08-20 - Gmail and Sydney Intake Contract Hardening
- Hardened the approved Gmail/Sydney plan before implementation after repository preflight and adversarial review exposed concurrency, delivery-uncertainty, trust-boundary, migration, and rollout ambiguities. Documentation commit: `0a4c1fa`.
- Gmail sends now require durable pre-send intent, zero transport retries, per-account canonical unresolved-send uniqueness, and predecessor-bound retry only after authenticated `not_delivered`; per-account History and per-account/thread reconciliation use versioned PostgreSQL advisory locks. Delivered reconciliation must verify the configured Gmail account, `SENT` label, thread, and canonical envelope/body before an intent becomes eligible.
- Sydney clarification is one-at-a-time, with immutable delivery attempts, one reminder at 24 hours, fixed release at 48 hours, no repeated field/version, and at most five consequential rounds. Hermes input remains untrusted draft evidence: actual dismissal/suppression and final task creation remain authenticated Command-only.
- Approval uses separate handoff-exchange and ordinary Command-prepare paths. Handoff secrets live only in a cleared URL fragment; both handoff and approval nonces use `secrets.token_urlsafe(32)`, hash-only persistence, strict pre-lookup validation, and a separate explicit Approve click. Hermes preserves the exact existing 16 MCP tools and adds exactly six bounded CRM review/proposal tools.
- Implementation gates require a fail-closed disposable real PostgreSQL 16 CI database, serial Alembic heads, two-session race coverage, bounded/offloaded synchronous provider calls, a `FIRST_COMPLETED` worker supervisor, read-only readiness, exact route registration, Task 7/8 frontend/Hermes CI, and live rollout evidence. Independent review result: **SPEC PASS** and **QUALITY APPROVED**.
- This was documentation hardening only. `GMAIL_TASK_INTAKE_ENABLED=false`, `SYDNEY_TASK_QUESTIONS_ENABLED=false`, and `CRM_TASK_ARCHIVE_ENABLED=false` remain unchanged; no migration, provider call, live deployment, or production enablement occurred.

### 2026-08-18 - Sydney CRM, Gmail, Instagram, and CRM Lifecycle Implementation Plans
- Converted the approved design into four dependency-ordered, test-first plans under `docs/superpowers/plans/`: CRM task foundation, Gmail/Sydney task intake, Instagram reliability, and remaining CRM record lifecycles.
- Reserved one serial Alembic chain from current head `7d1f3a5b6c8e`: task lifecycle `81a4d2c6e9f0`, shared integration runtime `82b5e3d7f0a1`, Gmail intake `83c6f4e8a1b2`, Sydney review `84d7a5f9b2c3`, and Instagram cache `85e8b6a0c3d4`; later CRM migrations follow that head.
- Sydney's delivery plan asks one concise question only for consequential missing information, preserves one durable pending clarification, permits one reminder, and keeps initial task approval in authenticated Command.
- The Instagram plan explicitly rejects the exposed/expired pasted token and requires a fresh long-lived Page credential, backend bearer authentication, persisted last-good feed, health/version alerts, and production media verification before enablement.
- Next: execute the task foundation first through red/green tests, then the shared worker and Gmail suggestion engine, Sydney review bridge, Instagram cutover, and remaining entity-specific lifecycle controls.

### 2026-08-18 - CRM Task Lifecycle Persistence Foundation
- Added serial Alembic revision `81a4d2c6e9f0` after `7d1f3a5b6c8e`, with task archive metadata, optimistic `version`, durable creation idempotency, source provenance, and immutable lifecycle-event tables. Legacy normalized `status=archived` tasks convert to archived visibility with `status=open`; recovered source-only evidence is counted and preserved separately.
- Hardened the migration with transaction-local lock/statement timeouts, write locks before preservation counts, a deterministic fallback when both legacy timestamps are null, and downgrade refusal whenever durable lifecycle history exists.
- Added ownership-gated disposable PostgreSQL cleanup and a required TLS PostgreSQL GitHub Actions migration job. A populated `_test` database is preserved when the emptiness gate fails.
- TDD/review evidence: expected missing-model RED; real empty database -> Alembic `7d1f3a5b6c8e` -> `81a4d2c6e9f0` -> downgrade -> re-upgrade GREEN; final PostgreSQL contract `11 passed`; adjacent CRMTask sweep `301 passed, 1 skipped`; sole head `81a4d2c6e9f0`; independent spec review PASS and code-quality review APPROVED. Commits: `9c03491`, `0b54d16`, `72c62f6`.
- Next: centralize task projection semantics before enabling any lifecycle mutation.

### 2026-08-18 - Unified CRM Task Projections
- Added one shared task projection contract: non-archived `open`/`in_progress` are active, non-archived `completed` and `cancelled` are separate, and any row with `archived_at` is archived regardless of preserved workflow status. Unknown workflow states fail closed.
- Replaced divergent open-task logic in Command overview, AI briefing, reports/details, default/due task reads, and contact summaries. Cancelled/archived/completed tasks no longer inflate open counts; `in_progress` is accepted consistently.
- Contact summaries now return mutable archived tasks separately from immutable recovered archive evidence while preserving the combined `archived_tasks` total. The new frontend accepts both the legacy 8-field and expanded 12-field summary during rollout and explicitly keeps the current eight-key summary strip until the lifecycle UI slice.
- TDD/review evidence: expected missing-module and five frontend RED failures; final focused backend `317 passed`, frontend `136 passed`, TypeScript and focused ESLint pass; independent spec review PASS and code-quality review APPROVED. Commit: `e863320`.
- Deployment order is locked: deploy the compatible frontend before the additive backend response. Next: build the shared transactional task creation service.

### 2026-08-18 - Shared Transactional CRM Task Creation
- Added `services/crm_task_service.py` as the single production authority for mutable task creation. Command, permitted archive intake, future Gmail intake, and future Sydney review now share typed actor/source validation, canonical UTC payload hashing, durable idempotency claims, source provenance, contact activity, and immutable lifecycle audit in one savepoint owned by the request transaction.
- `POST /api/v1/command/tasks` now requires an authenticated administrator plus a UUID `X-Idempotency-Key`. Exact retries return the same task; changed payload or authority returns structured `409`; missing contacts and invalid timestamps/timezones fail without partial rows. Production `CRMTask(...)` construction remains only in the shared service.
- Archive task intake now requires stable `source_id` and `source_row_id` values, preserves workflow status, retains same-title rows from distinct sources, and sorts derived source keys before writes so simultaneous reversed-order imports cannot deadlock. Reorder retries replay; edited rows and cross-admin retries fail closed; unrelated archive sources remain distinct. The black-and-gold import UI validates identities before submission and renders structured conflict messages.
- The TLS PostgreSQL CI contract now runs migrations plus service/API concurrency tests, pins its async pytest dependencies, and triggers on database/auth/config changes. The disposable test instructions use an accepted `_test` database name and translate async `ssl=require` to libpq `sslmode=require` for `psql` safety checks.
- TDD/review evidence: intentional service/API/import/CI/frontend REDs; final disposable TLS PostgreSQL matrix `156 passed`; frontend import/API `60 passed`; TypeScript, touched-file ESLint, YAML, constructor audit, and diff checks passed; independent specification review PASS and adversarial quality review APPROVED with no remaining findings. Commits: `771f9ca`, `8cfae68`, `fae1be7`, `aa59f7b`.
- Deployment order remains locked: do not deploy the required task idempotency header until the planned typed frontend task clients, including the contact-task producer, send it. Next: add versioned task Archive and Restore APIs.

### 2026-08-20 - Versioned CRM Task Archive and Restore APIs
- Added an off-by-default feature flag, strict versioned `TaskUpdate`, `TaskLink`, and lifecycle schemas, reversible Archive/Restore that preserves workflow status and links, and active-by-default plus strict archived/all visibility modes.
- Centralized lifecycle semantics in the shared service: one optimistic version spans atomic PATCH compare-and-swap, row-locked new links, and durable actor/source-bound archive/restore replay and same-state no-op events, with exact stable conflicts and no outer transaction ownership.
- Hardened link reads to use a coherent snapshot, bounded task integers to PostgreSQL `int32`, mapped maximum-version mutations to `task_version_conflict`, and made the exact ownership cleanup guard safe under optimized Python.
- Evidence: real TLS PostgreSQL final focused suite `113 passed`; related service/lifecycle/model/contact suite `457 passed`; SPEC PASS and QUALITY APPROVED with no findings. Commits: `0d91ca2`, `5f6aa0f`, `f99544c`.
- Deployment gate: do not deploy the backend until Task 5's typed frontend sends create idempotency and PATCH/link `expected_version`. Next: Task 5 client.

### 2026-08-20 - Atomic Typed CRM Task Client
- Added one strict frontend task boundary for reads and single-attempt mutations. All three production task-create callers now generate and retain one UUID, canonical payload, and client timezone for the same logical attempt; PATCH and link writes send the current `expected_version`, and no task mutation retries automatically.
- Added PostgreSQL-`int32` and RFC3339 response validation, operation-specific conflict decoding, task/link identity and version correlation, exact due-instant preservation, and authoritative reconciliation locks. Stale task/link reads cannot overwrite newer state, stale editors close after conflicts, and Home does not unlock creation when only a partial aggregate response is available without authoritative Tasks data.
- Made the stateful browser fixtures match production task semantics: HTTP 200 create/replay, timezone-bound idempotency fingerprints, one shared task ledger, structured mismatches, and read-after-create across central and contact surfaces.
- TDD/review evidence: initial `33` focused unit and `3` browser failures plus targeted follow-up REDs; final Task 5 suite `430 passed`; desktop browser `33 passed`, accessibility browser `8 passed`, focused fixture `2 passed`, and Home `6 passed`; TypeScript, touched-file ESLint, and diff checks pass. Exact specification review PASS and final code-quality review APPROVED. Commits: `9966421`, `f39c482`, `0475b602`, `05cd99c`, `31a44de`.
- Deployment gate: the versioned backend and typed callers are compatible, but Archive/Restore stays disabled until Task 6 exposes the accessible lifecycle UI and the target environment explicitly enables `CRM_TASK_ARCHIVE_ENABLED`. Next: Task 6 archive/restore controls.

### 2026-08-20 - Accessible Task Archive and Restore Controls
- Added Active and Archived task views, a keyboard-operated named action menu, a portaled confirmation dialog with optional reason, ACK-only archive/restore transitions, and a real server-backed Undo. Archived rows expose Restore only and cannot be edited, completed, reassigned, or linked.
- Lifecycle uncertainty never retries automatically. Exact manual Retry retains the original UUID/version/reason, compares its ACK with a fresh authoritative row before confirmation, and refuses to expose Undo when a later administrator changed the task. Failed reconciliation closes stale editors, locks writes, and focuses the reachable refresh action.
- Hardened accessibility and mobile recovery: disappearing Retry/Undo controls retain an announced focus target while pending, recovery-control replacements preserve focus, the dialog scrolls within `100dvh` at keyboard/landscape sizes, all controls meet the 44px contract, and the Tasks route has one main landmark with zero Axe WCAG A/AA findings.
- TDD/review evidence: initial `16` component failures, focused menu and version-correlation REDs, final quality RED `8` component plus `2` browser failures; final frontend suite `605 passed`; Task compatibility `64 passed`; full Command mobile/accessibility projects `28 passed`; TypeScript, scoped ESLint, diff, native-dialog, emoji, and landmark scans pass. Independent contract PASS, specification PASS, and code-quality APPROVED. Commits: `f6a1a5a`, `2ac1412`, `83b75b6`.
- Deployment gate: keep `CRM_TASK_ARCHIVE_ENABLED=false` until the reviewed frontend and backend are released together and Task 8 completes the full stateful Archive/Restore browser journey. Next: reconcile contact archive presentation.

### 2026-08-20 - Contact Task Archive Reconciliation
- Contact workspace task rows now expose the authoritative ten-field lifecycle shape: `id`, `title`, `contact_id`, `description`, `priority`, `due_at`, preserved workflow `status`, `archived_at`, `archive_reason`, and optimistic `version`. The frontend boundary is an exact dual decoder: it accepts either the rolling legacy seven-field row or the complete ten-field row, rejects partial/mixed/private shapes, validates archive metadata, and bounds task/contact/version integers to PostgreSQL `int32`.
- `archived_at` is the sole archive authority for lifecycle rows. Mutable archived SWS tasks retain their workflow status and expose Restore; recovered source-only archive occurrences are labeled `Recovered evidence` with no action; legacy archived rows remain visible but read-only. The count strip shows one combined archived total with screen-reader-only mutable and recovered-evidence subtotals.
- Contact Restore is server-authoritative and single-attempt. It freezes one UUID plus expected version, refreshes both the internal workspace and summary before unlocking, offers exact same-request Retry only when the authoritative row still equals the original, and validates retry ACKs against the fresh authoritative row. Conflicts, changed/absent rows, refresh failures, contact changes, mutation locks, live announcements, and focus recovery fail closed without automatic write retries.
- TDD/review evidence: backend combined suites `411 passed`; affected frontend units `182 passed`; prior full frontend suite `614 passed`; TypeScript, scoped ESLint, and diff checks pass. The pending-refresh focus regression was reproduced RED, fixed with a persistent focused disabled `Refreshing…` control, and independently re-reviewed as resolved. Commit: `0a124a3`.
- Rollout remains frontend first, then the additive backend. Keep `CRM_TASK_ARCHIVE_ENABLED=false` until Task 8 completes the authenticated stateful browser journey and the target environment is explicitly verified.

### 2026-08-20 - CRM Task Archive Phase Browser Verification
- Added a stateful authenticated Playwright task API fixture for exact active/archived/all reads, archive/restore ACKs, stale-version conflict, uncertain-applied and uncertain-unchanged reconciliation, exact request validation, and immutable historical replay. The happy path proves a trimmed archive reason, preserved `in_progress` workflow status, versions `1 -> 2 -> 3`, a new Restore UUID, cleared archive metadata, and no double-apply when the historical Archive request is replayed after Restore.
- Added the task suite only to the Command desktop, mobile, and accessibility allowlists; the visual project is unchanged. Desktop covers the happy path, conflict, and both uncertainty outcomes. Mobile covers keyboard/Escape/focus restoration, touch Archive/Restore, 44px targets, and overflow. Axe scans Active, the confirmation dialog, Archived, and conflict states without exclusions or disabled rules.
- The Archived Axe RED found real contrast instability. The smallest black/gold-compatible production fix in `TasksWorkspace.tsx` raises the archived explanatory copy from `text-white/45` to `text-white/60` and removes the tab color transition so selected/unselected contrast is stable during the state change.
- Green scoped evidence: Playwright `7 passed` with `14` intentional project-mismatch skips; real TLS PostgreSQL task contract `164 passed`; sole Alembic head `81a4d2c6e9f0`; full frontend `614 passed`; TypeScript, Task-8-only ESLint, the `35`-page production build, and diff checks pass. Specification review passed and quality review approved the exact-body/version/UUID/status assertions plus immutable replay/no-double-apply coverage. Implementation commit: `011a183`.
- Repository-wide caveats remain explicit: full backend pytest reported `1822 passed, 1 skipped, 3 deselected, 11 failed` in unrelated legacy tests—seven immediate-await assertions against fire-and-forget notification tasks, two missing Calendar dummy-env failures, one empty-database `notification_jobs` expectation, and one brokerage-marker scan. With dummy `GOOGLE_CALENDAR_*` values, the Calendar file passed `3/3`. Full ESLint reported `20 errors and 20 warnings`; error paths were `frontend/.agents/skills/claude-d3js-skill/assets/interactive-template.jsx`, `frontend/src/app/admin/link-pack/page.tsx`, `frontend/src/components/admin/link-pack/LinkRow.tsx`, `frontend/src/components/buyer/MonopolyJourney.tsx`, `frontend/src/components/home/Hero.tsx`, `frontend/src/components/seller/StagingChecklist.tsx`, `frontend/src/components/shared/CookieConsent.tsx`, `frontend/src/components/shared/RotatingText.tsx`, and `frontend/src/lib/link-pack/theme-css.ts`. All are outside Task 8, and Task-8-only ESLint is green. These were diagnosed and not changed in this slice.
- This is local acceptance only: no live deployment or authenticated target-environment Archive/Restore check was performed. Keep `CRM_TASK_ARCHIVE_ENABLED=false` until the rollout gate, backup/count reconciliation, compatible release order, and controlled authenticated production exercise are complete.

### 2026-08-17 - Sydney CRM, Gmail Task Intake, and Instagram Reliability Design
- Approved design is documented in `docs/superpowers/specs/2026-08-17-sydney-crm-email-tasks-instagram-design.md`.
- The design uses review-required task suggestions from both received and sent Gmail, a restart-safe History worker, exact-once task application, and minimal persisted email data.
- Sydney must ask Brandon one concise question at a time whenever creating the right task would require a consequential guess, retain the pending suggestion, resume it after the answer, and send at most one reminder. A repo-owned worker delivers through the Sydney bot; initial final approval remains in authenticated Command UI.
- CRM tasks use reversible Archive and Restore with immutable actor audit; other top-level CRM records receive entity-specific lifecycle actions rather than generic hard delete.
- Instagram moves behind FastAPI with bearer-header authentication, a last-good cache, health state, and alerts. The token supplied on 2026-08-17 is expired and exposed, so a newly generated valid long-lived Page token is still required before production cutover.
- Next: review this design, create the implementation plan, then deliver the work in feature-flagged phases with live production verification.

### 2026-08-12 - Command Workspace Design
- Approved a new `/admin/command` workspace that remains separate from the existing admin panel and uses the current FastAPI/PostgreSQL stack as the source of truth.
- Defined a unified internal CRM design covering Contacts, Tasks, Smart Plans, Opportunities, Marketing, Agreements/Templates/files, Reports, Listings/Search/Map, Websites, and server-side auditable AI features.
- Internal agreements deliberately replace the initial DocuSign dependency: file bytes live in configured object storage and PostgreSQL stores metadata, recipients, lifecycle, and immutable audit events. Legally binding e-signature execution is deferred.
- Design document: `docs/superpowers/specs/2026-08-12-command-workspace-design.md`.
- Status: Design approved; implementation plan pending user review of the written spec.

### 2026-08-12 - Command Workspace Foundation
- Created the isolated `feat/command-workspace` branch and began the internal CRM persistence layer.
- Added SQLAlchemy Command models for contacts linked to existing leads, activities, notes, tasks, Smart Plans, opportunities, listings, internal agreements/events, and file metadata.
- Added a focused test-first model contract; `backend/tests/test_command_models.py` passes (2 tests) with an explicit non-production test configuration.
- Next: additive Alembic migration, Pydantic contracts, authenticated `/api/v1/command` router, then the `/admin/command` UI shell.
- Completed the additive migration, authenticated Command overview/contact/task/agreement API, dark Command dashboard, and route navigation shells. Frontend typecheck, 34 Vitest tests, and production build pass. Remaining work is the full feature views and resource endpoints for each workspace module.
- Added live internal Contacts, Tasks, Smart Plans, Opportunities, Agreements, Listings/Map, connected Marketing/Reports/Websites, and Sweeney AI briefing modules. Contact detail now covers Timeline, Opportunities, Smart Plans, Tasks, Notes, and Saved Searches through one authenticated API endpoint.
- Applied additive migration `f3a91c2d7e10` to the configured PostgreSQL database. Verified `alembic current` reports `f3a91c2d7e10 (head)`; no existing lead, booking, content, funnel, or analytics data was changed.
- Added and applied `f6b24e1c8a03` for Tags and Saved Searches; saved searches are returned in the per-contact workspace.

### 2026-08-02 - Production Header Logo Sizing Fix
- Root cause: the SWS-only PNG has a `9675x5084` canvas but its visible alpha content occupies only about 77% of the width and 57% of the height. The brokerage-swap navbar rendered that padded canvas at only `68x36px`, leaving a visible logo of roughly `52x21px` in production.
- Added a regression test first; it failed against the undersized `76x40` image contract and passed after the correction.
- Kept the existing 64px black-and-gold header and SWS-only branding. The logo now renders inside an overflow-hidden responsive frame: `112x64px` on mobile and `124x64px` from the small breakpoint, with the padded image enlarged to `72px`/`80px` tall so only transparent margins are cropped.
- Local browser verification at a 1200px viewport measured a `124x64px` logo frame and `152x80px` image box with zero horizontal overflow; the visible mark is approximately `117x46px` on desktop.
- Verification passed: 34/34 frontend tests, TypeScript, targeted Navbar lint, `git diff --check`, and the Next.js production build.
- Pushed commit `3358610` to GitHub `main`. Vercel Production deployment `5715079788` completed successfully, and Railway runtime deployment `3a9fee4a-a042-40c0-8e92-bf7a60196b83` reached `SUCCESS`.
- Live custom-domain verification returned HTTP 200 and confirmed the new frame/image classes and dimensions, absence of the old `76px` width, and no eXp logo in the header.
- The unrelated existing `docs/deployment/hermes-railway.md` edit remained excluded from the release.
- Status: Complete

### 2026-08-01 - eXp Production Release
- Pushed the completed brokerage swap to GitHub `main` at `857a752`, then pushed the migration idempotency follow-up at `b364124`.
- Railway production deployment `62b8335e-975f-4472-b069-045597141874` released the branding implementation. Follow-up deployment `0a580dbf-b570-4f2c-9500-c416531c3e53` released the corrected migration comparison and reached `SUCCESS`.
- Vercel Production deployment `5710309885` for `b364124` completed successfully at the custom domain.
- Applied the guarded production content migration once: 33 updates across 13 blogs, 16 funnels, 1 content block, 1 link pack, and 2 link items. The private recovery snapshot is `/Users/rishabnandi/.sws-backups/exp-branding/exp-branding-backup-20260802T024423Z.json`.
- A post-apply dry-run exposed a PostgreSQL-driver comparison false positive for the link-pack `BYTEA` background: the database `memoryview` and packaged `bytes` had identical length and SHA-256, but the raw types compared unequal. Added a reproducing regression test first, normalized both sides of the comparison, and passed all 26 migration tests.
- Final production dry-run reports exactly 0 planned updates and 0 old-brand remnants across every allowlisted table.
- Live verification: backend `/health` returns `status=ok`; Home, About, Buy, Sell, Invest, Blog, and Links all return HTTP 200 with zero `Keller Williams` text matches. The homepage header contains only the Sold With Sweeney logo, the footer contains the appropriate eXp Realty identification and legal links, and `/links` contains all six published top-level items with no eXp logo overlay.
- The unrelated existing `docs/deployment/hermes-railway.md` edit remained excluded from every release commit.
- Status: Complete

### 2026-08-01 - eXp Production Rollout Preflight
- Production rollout was explicitly authorized for the completed eXp brokerage swap.
- Confirmed `codex/exp-brokerage-swap` starts at the current `origin/main` tip and that pushes to `main` create both the Railway `enchanting-perception / production` deployment and the Vercel `Production` deployment.
- Fresh release gates passed: 33/33 frontend tests, TypeScript, production build, 39/39 branding-focused backend tests, Python compileall, and `git diff --check`.
- The full backend suite has the same eight non-release failures on both the release and an isolated `origin/main` snapshot: seven notification retry-task timing assertions plus one test that requires a running local PostgreSQL instance. The release adds passing coverage and introduces no new failure name.
- A fresh production-data dry-run rolled back without a backup or write and predicted exactly 33 changes with zero old-brokerage remnants.
- Release scope excludes the unrelated existing `docs/deployment/hermes-railway.md` edit. Production sequence is main push, Railway backend success, guarded migration apply and verification, then public Vercel/custom-domain verification.
- Status: Production release in progress; exact live deployment and migration evidence is reported in the deployment task handoff.

### 2026-08-01 - Local Frontend Review and Links Restoration
- Started the updated Next.js frontend at `http://localhost:3000` for local visual review.
- Removed the eXp logo from both the shared header and the `/links` background so the visible brand treatment stays Sold With Sweeney-only; eXp identification remains in the appropriate profile copy and footer disclosures.
- Added a navbar regression test that failed against the oversized dual-logo header and passed after the SWS-only correction.
- Replaced the temporary three-button `/links` mock with a read-only preview of the actual published link pack: the original profile, photo, social links, property, resource groups, valuation, contact, testimonials, thumbnails, active states, and all six top-level items are preserved.
- The preview API reads the published snapshot and its assets once inside an explicit read-only transaction, rolls the transaction back and closes it, and applies only the eXp copy, destination, and cleaned black-and-gold background substitutions in memory. It does not start production background loops or write to the database.
- Added a `/links` regression test that failed while the eXp image overlay was present and passed after only that overlay was removed.
- Verification: 33/33 frontend tests passed, TypeScript passed, targeted ESLint passed, the source/preview structure comparison matched all six top-level items with zero old-brokerage remnants, both local routes returned HTTP 200, and browser review found no console errors or horizontal overflow.
- Runtime status: The temporary frontend and read-only preview API were stopped cleanly before the production build; no deployment or production mutation occurred during local review.

### 2026-08-01 - eXp Realty Brokerage Swap
- What was changed: Replaced active Keller Williams/KW website branding with eXp Realty while preserving the existing Sold With Sweeney black-and-gold design, layouts, animation system, and lead flows.
- Frontend and assets:
  - Added the official white eXp Realty logo with source provenance for the footer; the shared navbar and `/links` background intentionally remain Sold With Sweeney-only.
  - Removed four Keller Williams-branded public logo/lockup files, including the prior composite navbar asset.
  - Replaced active brokerage copy and disclaimers on Home, About, Buy, Sell, Invest, Blog, blog articles, funnels, navigation, and footer.
  - Replaced KW legal destinations with the current eXp/AGNT terms, privacy, DMCA, and accessibility destinations.
  - Preserved the historical brokerage blog URL as an intentional permanent redirect to the new eXp Realty slug.
  - Cleaned only the old brokerage lockup from the black-and-gold `/links` background and left that background logo-free; the profile copy retains the appropriate eXp brokerage attribution.
- Backend and persisted content:
  - Updated blog, funnel, chatbot, investor-disclaimer, link-pack seed, email, and legacy CRM-handoff language so new content does not regenerate Keller Williams branding.
  - Added `backend/scripts/migrate_exp_branding.py`, which defaults to dry-run and uses an allowlist, audited-row guards, one transaction, advisory/row locks, a private outside-repo backup, and a post-update remnant check for apply mode.
  - Fresh live dry-run completed with no write or backup: 33 planned updates, covering 13 blogs, 16 funnels, 1 content block, 1 link pack, and 2 link items, with zero predicted old-brand remnants.
- Verification:
  - Frontend: 33/33 tests passed, TypeScript passed, and the production build completed successfully.
  - Backend branding suite: 39/39 tests passed; Python compileall and `git diff --check` passed.
  - Full backend suite under the explicit local test configuration: 222 passed, 8 failed, 3 deselected. The release and `origin/main` have the same eight failure names: seven pre-existing notification retry-task timing assertions plus one test that requires a running local PostgreSQL instance.
  - Independent frontend and backend quality reviews both passed after fixing the `/links` logo drift alignment.
  - Active-source scan found no unrelated company branding and no active Keller Williams/KW reference; the only active-source exception is the intentional legacy blog redirect slug.
- Production status: Rollout explicitly authorized. Safe release order is backend deployment, migration apply plus remnant verification, then frontend verification so the renamed blog destination exists before its redirect is public.
- Status: Implementation and release tooling complete; production rollout in progress.

### 2026-08-01 - Keller Williams Site-Wide Audit
- What was done: Completed a read-only Keller Williams inventory across the current production site, live public database content, frontend/backend source, public image assets, generated blog/funnel content, and non-served repository records.
- Current production findings:
  - The shared navigation logo contains an embedded `KW SUCCESS / KELLERWILLIAMS REALTY` lockup, and the shared footer contains the dedicated KW logo, three Keller Williams text blocks, and four `kw.com` legal links.
  - Page-specific Keller Williams copy remains on Home, About, Buy, Sell, Invest, Blog, blog articles, and funnel registration sections.
  - All 13 currently published blog articles and all 9 currently published funnels contain Keller Williams/KW copy in their article or generated funnel content.
  - `/links` has an eXp bio but still uses a background graphic containing the KW Success/Keller Williams lockup and a home-valuation link to `soldwithsweeney.kw.com`.
  - Investor full reports append the hardcoded Keller Williams broker disclaimer.
  - Blog, funnel, and chatbot prompts plus link-pack seed defaults can reintroduce Keller Williams after visible copy is changed.
- Asset verification:
  - Confirmed four Keller Williams-branded logo/lockup PNG files in `frontend/public/logos/`, including two duplicate white SWS/KW lockups.
  - OCR and visual checks found no Keller Williams branding in site videos, animation frames, current blog hero images, or published funnel hero images.
- Security follow-up: An initial failed read-only `psql` invocation echoed the production database connection URL in command output. Treat the database password as exposed and rotate it; no credential rotation or database mutation was performed during this audit.
- Scope: Inventory only; no public site, production data, or branding content was changed.
- Status: Complete

### 2026-06-05 - Hermes Assistant Rename To Sydney
- What was changed: Renamed the live Brandon Hermes/Atlas assistant identity to Sydney without redeploying or touching Railway global login state.
- Live configuration changed:
  - Telegram bot visible display/first name is now `Sydney`; the username remains `soldwithsweeney_bot`.
  - Hermes default profile `SOUL.md` now identifies the assistant as Sydney and instructs it not to introduce itself as Hermes Agent.
  - Restarted the Hermes gateway through the protected admin API so the updated persona is loaded for new turns.
- Files modified:
  - `docs/deployment/hermes-railway.md`
  - `tdtn.md`
  - `memory.md`
- Verification:
  - Hermes admin login succeeded and `/api/profiles/default/soul` returned the Sydney identity after the write.
  - Telegram Bot API `getMyName` returned `Sydney`, and `getMe` returned first name `Sydney` with username `soldwithsweeney_bot`.
  - Hermes `/health` returned `{"status":"ok","gateway":"running"}` after the restart.
  - Native Hermes `/api/status` reported Telegram `state=connected` with no error code or message.
- Notes:
  - Hermes stores the built system prompt per session. After the first rename, Brandon's existing Telegram session still had the old prompt and answered as Hermes Agent.
  - Added a persistent `agent.system_prompt` Sydney identity overlay and deleted Brandon's stale Telegram session so the next inbound message starts from the Sydney prompt.
  - `/start` is treated as a Telegram platform ping after a session exists, so Brandon should send a normal message such as `who are you?` or use `/reset` first to force a clean re-introduction.
- Status: Complete

### 2026-06-01 - Brandon Hermes Agent-Control Bridge
- What was changed: Implemented the first backend foundation slice for the private Brandon AI / Atlas assistant: a read-only, token-authenticated FastAPI agent-control bridge with dedicated audit logging.
- Files created:
  - `docs/superpowers/plans/2026-06-01-brandon-hermes-agent-foundation.md`
  - `docs/deployment/hermes-railway.md`
  - `backend/middleware/agent_control.py`
  - `backend/models/agent_action_audit.py`
  - `backend/schemas/agent_control.py`
  - `backend/services/agent_control_audit.py`
  - `backend/routers/agent_control.py`
  - `backend/alembic/versions/e2f4a6b8c901_add_agent_action_audits.py`
  - `backend/tests/test_agent_control_auth.py`
  - `backend/tests/test_agent_control_router.py`
- Files modified:
  - `backend/config.py`
  - `backend/main.py`
  - `backend/models/__init__.py`
  - `backend/.env.example`
  - `tdtn.md`
  - `memory.md`
- Key decisions:
  - Added `AGENT_CONTROL_ENABLED`, `AGENT_CONTROL_TOKEN`, and `AGENT_CONTROL_RECENT_LIMIT`; endpoints are unavailable unless explicitly enabled and tokenized.
  - Added `/api/v1/agent-control/status`, `/actions`, `/leads/recent`, and `/bookings/recent`.
  - Recent lead/booking responses mask email and phone and never expose `google_event_id`.
  - Audit rows go to `agent_action_audits` and record action ids/counts instead of raw tokens or full PII payloads.
  - Documented Hermes deployment as a separate `atlas-agent` Railway service, leaving `extraordinary-prosperity` as the existing FastAPI backend.
- Verification:
  - `JWT_SECRET=test-secret DATABASE_URL=postgresql+asyncpg://user:pass@localhost/test /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/python -m pytest tests/test_agent_control_auth.py tests/test_agent_control_router.py -v` passed: 10 tests.
  - `JWT_SECRET=test-secret DATABASE_URL=postgresql+asyncpg://user:pass@localhost/test /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/python -m pytest tests/test_link_pack_router.py -q` passed: 6 tests.
  - `JWT_SECRET=test-secret DATABASE_URL=postgresql+asyncpg://user:pass@localhost/test GEMINI_API_KEY=dummy-key /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/python -c "import main; print('main import ok')"` passed.
  - `JWT_SECRET=test-secret DATABASE_URL=postgresql+asyncpg://user:pass@localhost/test /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/alembic heads` returned `e2f4a6b8c901 (head)`.
  - `git diff --check` passed.
  - Neighboring `tests/test_leads_notifications.py` still fails on `main` and this branch because its three route tests expect `run_notification_retry_pass` to be awaited, while the current route code schedules it with `asyncio.create_task`; this is pre-existing and unrelated to the Hermes bridge.
- Status: Complete locally

### 2026-06-01 - Brandon Hermes Agent Foundation Design
- What was changed: Wrote the approved design spec for the first private Hermes/Atlas assistant slice: same Railway project, separate Hermes service, and a narrow FastAPI agent-control bridge.
- Files created:
  - `docs/superpowers/specs/2026-06-01-brandon-hermes-agent-foundation-design.md`
- Key decisions:
  - Keep Hermes under Railway project `enchanting-perception`, but deploy it as a separate `atlas-agent` service instead of merging it into the existing FastAPI backend service.
  - Leave `extraordinary-prosperity` untouched except for explicit, tested `/api/v1/agent-control/*` endpoints.
  - First bridge scope is read-only: backend status, allowlisted action registry, recent lead summaries, and recent booking summaries.
  - Protect the bridge with `AGENT_CONTROL_TOKEN`, `AGENT_CONTROL_ENABLED`, constant-time token comparison, and dedicated audit rows.
  - Defer Gmail, Calendar, Drive, Sheets, Docs, People, CRM, outbound messaging, and autonomy tiers to later specs.
- Verification:
  - Read the attached Brandon AI / Atlas PRD and cross-checked current repo architecture.
  - Checked current Railway CLI capabilities through `scripts/railway-sweeney`.
  - Reviewed Hermes/Railway current docs for deployment assumptions and persistent `/data` volume behavior.
  - Ran the spec self-review scan and removed placeholder-style deployment markers.
- Status: Spec written; awaiting written-spec review before implementation plan

### 2026-05-31 - Railway Sweeney Token Verified
- What was changed: Replaced the rejected local Railway account/workspace token in the gitignored `.env.railway-sweeney.local` with a freshly generated account/workspace token for the Sold With Sweeney Railway workspace.
- Files modified:
  - `.env.railway-sweeney.local` - local-only token refreshed; added the verified Railway service metadata for `extraordinary-prosperity`.
  - `tdtn.md`
  - `memory.md`
- Key decisions:
  - Continued to use the wrapper instead of `railway login`, preserving the global CLI authentication for `rishabnandibusiness@gmail.com`.
  - Kept the account/workspace token local-only and out of git.
  - Because the current repo is not globally service-linked, service-scoped commands should pass `--service extraordinary-prosperity` when needed.
- Verification:
  - `scripts/railway-sweeney status` returned `Project: enchanting-perception`, `Environment: production`, `Service: None`.
  - `scripts/railway-sweeney service status --all` returned `extraordinary-prosperity | 85541f63-2aa1-4679-8114-98895f4bf215 | SUCCESS`.
  - `scripts/railway-sweeney run --service extraordinary-prosperity true` succeeded.
  - Plain `railway whoami` still reports `rishabnandibusiness@gmail.com`.
  - `~/.railway/config.json` hash stayed unchanged, confirming no global Railway login/config clobber.
- Status: Complete

### 2026-05-30 - Railway Sweeney Project Token Wrapper
- What was changed: Added a local token-scoped Railway helper so commands for the Sold With Sweeney deployment project can run without replacing the global Railway CLI login for `rishabnandibusiness@gmail.com`.
- Files created:
  - `scripts/railway-sweeney` - sources a repo-local env file, exports the Railway token only for that process, then runs `railway ...` or opens a token-scoped subshell.
  - `.env.railway-sweeney.local` - gitignored local env file holding the `soldwithsweeneyfordeployment@gmail.com` Railway account/workspace token and the `enchanting-perception` project metadata.
- Key decisions:
  - Used `RAILWAY_TOKEN` because the provided token is tied to the single Railway project `enchanting-perception` (`aa6c9f9c-46d4-4f5d-b529-86b073de4972`).
  - Did not run `railway login`, so `~/.railway/config.json` and the existing global CLI login remain untouched.
  - Kept the secret out of tracked files by relying on the existing `.env.*.local` ignore rule.
- Verification:
  - `scripts/railway-sweeney` is executable.
  - `.env.railway-sweeney.local` is ignored by git through the existing `.env.*.local` rule.
  - `railway whoami` still reports the global login as `rishabnandibusiness@gmail.com`.
  - The Railway config hash for `~/.railway/config.json` stayed unchanged before/after wrapper checks.
  - Railway rejected the first provided token as invalid/unauthorized for both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN`, so the helper needed a freshly generated token value before it could operate the `soldwithsweeneyfordeployment@gmail.com` project.
- Status: Superseded by 2026-05-31 token verification

### 2026-05-19 — Blog Production Outage Diagnosis
- What was found: Live `/blog` loads the frontend shell, but the deployed blog API returns HTTP 500. The Railway response reports Neon rejecting database connections because the account/project exceeded compute time quota; the error also notes the production DB connection is insecure and should use `sslmode=require`.
- Impact:
  - `/blog` can only show the client-side error/empty state because `GET /api/v1/blog/?limit=50` fails.
  - Individual `/blog/[slug]` pages return 404 because the server component treats a failed blog fetch as missing content.
  - `/sitemap.xml` still includes blog URLs from cached/generated output, but the live article fetch cannot reach the database.
- Required production fix: restore/upgrade Neon compute quota, ensure Railway `DATABASE_URL` includes SSL mode, then redeploy/restart the backend. After that, re-check the public blog list and one known post slug against the Railway API and `soldwithsweeney.com`.
- Neon identifier found locally: host `ep-tiny-firefly-ankqqw49-pooler.c-6.us-east-1.aws.neon.tech`, database `neondb`, user `neondb_owner`. Use the `ep-tiny-firefly-ankqqw49` endpoint/project marker to match this connection string inside the Neon dashboard or Railway variables; the local URL currently has no `sslmode=require` query.
- Neon account email check: no Neon owner/login email is stored in this repo. The Git author is `RshieRish <118158036+RshieRish@users.noreply.github.com>`, but that is only commit metadata and not evidence of the Neon account owner. Public app emails found (`info@soldwithsweeney.com`, `brandon@soldwithsweeney.com`) are contact/SMTP values, not Neon ownership evidence.
- Follow-up account trace: no Neon CLI is installed locally; Railway CLI is installed but currently unauthorized and this repo is not linked to a Railway project. A local Claude history search shows the `ep-tiny-firefly-ankqqw49` Neon URL was pasted into a prior project chat, but that pasted connection string does not include the Neon account/login email.
- 2026-05-19 re-check: the host still resolves publicly (`ep-tiny-firefly-ankqqw49-pooler.c-6.us-east-1.aws.neon.tech` → Neon IPs) and Railway still gets a Neon-origin error. This means the DB endpoint still exists/is routed in Neon; it has not "moved" to Railway or disappeared from DNS. The practical issue is account/org visibility plus Neon compute quota suspension.
- 2026-05-19 browser-forensics follow-up: strongest account candidate is `millergid9@gmail.com`. Evidence: Chrome `Profile 13` has Google account `millergid9@gmail.com`, signed up/logged into Neon on 2026-03-19 around 01:37 ET, landed in org `org-long-bread-73501543`, opened project `nameless-credit-95836299` with `database=neondb`, and the exact `ep-tiny-firefly-ankqqw49` DB URL was pasted into the Brandon project chat about one minute later. This is high-confidence local forensic evidence, but not server-side Neon ownership proof.
- Verification:
  - Confirmed the live blog chunk fetches the Railway backend.
  - Confirmed Railway `GET /api/v1/blog/?limit=50` returns 500 with Neon quota/SSL connection failure.
  - Confirmed a known live article URL on `soldwithsweeney.com` returns 404 while the backend blog fetch is failing.
- Status: Diagnosed; production infrastructure action required

### 2026-05-14 — Root Cause for Missing Hero Images: R2 Env Vars Missing on Railway
- What was changed: Today's auto-post landed with `image_url: null` again (same symptom as yesterday's two posts, which had landed with `placehold.co` URLs before that fallback was removed). Railway logs weren't directly accessible. Added two diagnostic surfaces, deployed, queried prod from outside, identified the actual failure: **R2 environment variables were never set on Railway**, so `boto3` couldn't construct the S3 client and every image upload silently dropped to `None`. Gemini image generation was working fine the entire time (Railway returned 975 KB JPEG bytes in 17s); the failure was the upload step. User added the six `R2_*` env vars to Railway via the dashboard; verified via the diagnostic endpoint immediately after restart — `r2_configured: true`, real R2 URL returned, image publicly readable.
- Files modified:
  - `backend/services/blog_service.py` — `generate_blog_image` now writes the human-readable failure reason (HTTP status + body, finishReason, safetyRatings, R2-vs-Gemini distinction, timeout, exception type) to `BlogService._LAST_IMAGE_ERROR`; `_save_blog` accepts an optional `image_error` and persists to a new `blogs.image_gen_error TEXT` column; `create_auto_blog` and `create_draft_blog` thread the error through.
  - `backend/routers/blog.py` — added `POST /api/v1/blog/admin/test-image` (admin JWT required). Runs only the image-generation step, returns `{image_url, error, took_ms, r2_configured, r2_endpoint_set, r2_public_url_set}`. No Gemini text call, no DB write — cheap to re-run during debugging.
- Schema change: `ALTER TABLE blogs ADD COLUMN IF NOT EXISTS image_gen_error TEXT` applied to prod DB out-of-band (no migration file — kept as a permanent diagnostic column per user decision to retain the diagnostic surface).
- Backfill: today's affected post (`Behind the Scenes: A Day in the Life…`) had its cover regenerated from local and `UPDATE`d so the live blog isn't broken.
- Key decision: kept `/admin/test-image` and `image_gen_error` column in place permanently — both are zero-cost when unused and would have saved hours of debugging today if they'd existed sooner.
- Verification:
  - Diagnostic endpoint pre-fix returned `r2_configured: false`, `error: "Gemini OK (975942 bytes) but R2/public upload returned None — check R2 env vars on Railway"`. Post-fix returned `r2_configured: true`, `image_url: pub-…r2.dev/blog-images/blog-1778795754-5620.jpg`, error null, took 16.5s.
  - Uploaded test image is publicly readable (HTTP 200, 987 KB JPEG).
- Status: Complete. Tomorrow's auto-post (~16:13 UTC) and every post after will have a real R2 cover.

### 2026-05-13 — Scheduler Worker-Race Fix + Removed Placeholder Fallback
- What was changed: Two daily posts landed in prod within 72 seconds, both with `placehold.co` cover images instead of real R2 images. Two root causes — Railway runs `uvicorn --workers 2`, so two Python processes each ran their own scheduler and fired simultaneously; AND image generation evidently failed on at least one of those concurrent calls so the placeholder fallback fired. Fix: postgres advisory lock around the scheduler so only one worker per cluster posts per cycle, and removed the placeholder fallback so a real failure surfaces the on-brand empty state instead of a generic gray rectangle.
- Files modified:
  - `backend/main.py` — added `_try_claim_post_lock` / `_release_post_lock` using `pg_try_advisory_lock(842913571)`. Loop now: jitter 0–30s on boot, then each iteration tries the lock; if got, re-check inside the lock (so a worker that just lost a race doesn't double-post), run pipeline, release; if not got, skip the cycle. Concurrency-safe across N uvicorn workers AND N Railway replicas.
  - `backend/services/blog_service.py` — `generate_blog_image` now returns `Optional[str]` and retries the Gemini call once (180s timeout, 2s backoff) before giving up; `_upload_image` returns `None` on failure; removed all three `placehold.co` return paths.
  - `frontend/next.config.ts` — dropped `placehold.co` from `remotePatterns` since no path emits it anymore.
- Backfill: ran a one-off script to regenerate covers for the 2 placehold posts (`Why More Boston Professionals…` and `Windham, Londonderry, Salem…`) and UPDATE'd their `image_url` to the real R2 URLs.
- Verification:
  - Lock test: Worker A claims → `got=True`. Worker B tries while A holds → `got=False`. A releases → B retries → `got=True`. Confirms the lock is non-blocking and properly released.
  - DB scan: all 3 blogs now have `pub-04769d4526f148fbbbeaac4f7a62b4c5.r2.dev` cover URLs (no placehold).
  - `next build` clean — 20/20 pages, sitemap + robots intact.
- Status: Complete locally

### 2026-05-12 — Daily Cadence + Topic Dedup + Full SEO Pass on Blog
- What was changed: Tightened the auto-blog system in three ways: (1) cadence dropped from 72h to 24h so a new post lands every day, (2) topic selection now filters out topics that match (post-Gemini rewrite) any existing blog title, so we cycle through all 50 topics across all 5 buckets before repeating, (3) blog detail pages went from `'use client'` with no SEO metadata to a server component shell exporting `generateMetadata` (full OG, Twitter, canonical, keywords, authors) plus an inline JSON-LD `BlogPosting` schema, with `sitemap.ts`, `robots.ts`, and `metadataBase` added at the app root.
- Files modified:
  - `backend/config.py`, `backend/.env.example` — default `BLOG_AUTO_POST_INTERVAL_HOURS` 72 → 24.
  - `backend/services/blog_service.py` — added `_norm_title`, `_topic_already_used` (state-name normalization + 4-word substring + difflib fuzzy backstop @ 0.72 ratio), `_get_existing_titles`, threaded `used_titles` through `_get_topic_and_category` and `generate_blog_content`, wired into `create_auto_blog`.
  - `frontend/src/app/(main)/blog/[slug]/page.tsx` — replaced 383-line client page with a server component: server-side `getBlog` memoized via React `cache`, `generateMetadata` with full OG + Twitter + canonical, inline `<script type="application/ld+json">` BlogPosting schema, delegates UI to client child.
  - `frontend/src/app/(main)/blog/[slug]/BlogArticleClient.tsx` — new file. All the original interactive UI (reading-progress bar, motion, react-markdown, sidebar) accepting `{ blog }` as a prop.
  - `frontend/src/app/sitemap.ts` — new. 6 static routes + every published blog slug (fetched from prod API, 10-min revalidate).
  - `frontend/src/app/robots.ts` — new. Allow `/`, disallow `/admin*` and `/api/*`, point at sitemap.
  - `frontend/src/app/layout.tsx` — added `metadataBase` so relative OG/Twitter image URLs resolve to the absolute site URL.
- Key decisions:
  - Server/client split matches Next 16's "metadata + generateMetadata only work in server components" rule. Used React `cache` to ensure the slug fetch happens once per request even though both `generateMetadata` and the page function call `getBlog`.
  - Dedup uses three signals — state-name normalization (MA↔Massachusetts, NH↔New Hampshire, REALTOR® variants), 4-word distinctive-phrase substring match, and difflib `SequenceMatcher.ratio() >= 0.72`. Tuned the threshold against real rewrites; lower would catch unrelated topics, higher would miss legit duplicates.
  - Dedup `OR`s against the existing-titles list so categories rotate AND titles never collide.
  - Sitemap revalidates every 10 minutes, blog detail every 5 minutes — fresh enough for daily posts, light enough on Railway.
- Verification:
  - `next build` succeeded; `/blog/[slug]` registered dynamic, `/robots.txt` static, `/sitemap.xml` with 10m revalidate.
  - Live-rendered the seed blog via dev server pointed at prod API: `<head>` contains correct title, description, canonical, `og:type=article`, `og:image=<R2 URL>`, `twitter:card=summary_large_image`. JSON-LD parses cleanly as `BlogPosting` with author bio, publisher, image, mainEntityOfPage, articleSection, wordCount.
  - `/robots.txt` and `/sitemap.xml` outputs verified against XML sitemap spec.
  - Dedup truth-table test: catches MA↔Massachusetts and NH↔New Hampshire rewrites and REALTOR®↔REALTOR variants; correctly does NOT match unrelated topics. 10-day simulation picks 10 distinct topics across all 5 buckets.
- Status: Complete locally

### 2026-05-12 — Blog Cover Images Whitelisted in next.config
- What was changed: Blog posts on the live site rendered with no cover image because Next.js `<Image>` was rejecting the R2 (`pub-*.r2.dev`) hostname — only `**.cdninstagram.com` was in `images.remotePatterns`. Whitelisted the three hosts the blog can actually emit (R2, picsum.photos, placehold.co) and changed the placehold.co fallback URL to use the `.jpg` extension since Next blocks remote SVG by default.
- Files modified:
  - `frontend/next.config.ts` — added `**.r2.dev`, `picsum.photos`, `placehold.co` to remotePatterns.
  - `backend/services/blog_service.py` — placeholder URL bumped from `…/eac469?text=…` to `…/eac469.jpg?text=…` so the safety-net image is served as JPEG (Next refuses remote SVG without `dangerouslyAllowSVG`).
- Verification:
  - Started Next dev server in worktree, hit `/_next/image?url=…` for each of the three hosts: R2 (200 / 125KB jpeg), picsum (200 / 901B jpeg), placehold .jpg (200 / 12KB jpeg). Unrelated host (example.com) correctly returned 400, confirming the whitelist is active.
- Status: Complete locally

### 2026-05-12 — Blog Auto-Post Scheduler Wired Up
- What was changed: The blog system was previously fully functional end-to-end (Gemini stages A/B/C all working, R2 upload working, DB save working) but had nothing triggering it. The `/api/v1/blog/cron` endpoint existed but no scheduler ever called it, and the Auto-Pilot button in `/admin/blog` had apparently never been clicked — DB had zero blog rows. Added an in-process asyncio loop that calls `BlogService.create_auto_blog()` on a configurable interval, mirroring the existing `_notification_retry_loop` pattern.
- Files modified:
  - `backend/main.py` — added `_blog_auto_post_loop`, `_seconds_since_last_posted_blog`, merged startup/shutdown hooks into `start_background_loops` / `stop_background_loops`.
  - `backend/config.py` — added `BLOG_AUTO_POST_ENABLED` (default `True`) and `BLOG_AUTO_POST_INTERVAL_HOURS` (default `72`).
  - `backend/.env.example` — documented the two new env vars.
- Key decisions:
  - In-process asyncio loop instead of APScheduler / external Railway cron — matches the existing notification-retry pattern, no new dependency, no need for a service-account JWT to call the HTTP endpoint.
  - Restart-safe: on every loop iteration we check `MAX(created_at) WHERE is_posted` against the interval, so a redeploy mid-window won't double-post.
  - Default interval 72h (every 3 days) so the 5 content buckets cycle every ~15 days; tunable via env.
  - Loop swallows Gemini/DB exceptions, logs them, and waits the full interval before retrying — avoids hammering the API on transient failures.
- Verification:
  - Hit Gemini directly via `curl` — `gemini-3-flash-preview`, `gemini-3-pro-preview`, and `gemini-3-pro-image-preview` all return 200. (Initial hypothesis that the model names were wrong was incorrect — they are valid against the prod API key.)
  - Ran `BlogService.create_auto_blog()` end-to-end against prod DB — produced one real blog `id=9531273e-5256-4de4-bc84-3606ccca477c`, slug `the-most-underrated-neighborhoods-in-northern-massachusetts-a-2025-buyers-guide`, with R2-hosted cover image, `is_posted=true`. (User can delete from `/admin/blog` if undesired.)
  - Imported `main` from worktree and called `start_background_loops()` — task spawned, logged `Last post was 131s ago — sleeping 259068s until next.`, did not crash, shut down cleanly via `stop_background_loops()`.
  - Verified `BLOG_AUTO_POST_ENABLED=false` short-circuits and never spawns the task.
- Status: Complete locally

### 2026-04-21 — Application Feature Inventory Review

### 2026-04-21 — Application Feature Inventory Review
- What was changed: Reviewed the current spec, project memory, public pages, backend routers, admin surfaces, chatbot flow, booking flow, and Zapier CRM wiring to prepare an accurate feature inventory for the application.
- Files modified:
  - `tdtn.md`
  - `memory.md`
- Key decisions:
  - Feature descriptions are based on implemented code paths and current project notes, not just the original specification.
  - CRM routing should be described as Zapier-based KW Command handoff rather than a direct Keller Williams API integration.
  - In-person booking availability should explicitly be described as Google Maps travel-time-aware, not just generic calendar availability.
- Verification:
  - Cross-checked the inventory against `BRANDON_RE_SPEC.md`, `memory.md`, frontend route/component files, and backend router/service files.
- Status: Complete locally

### 2026-04-21 — Homepage Hero Award Copy Update
- What was changed: Updated the homepage hero award badge copy to read `Northeast Association of REALTORS® Realtor Of The Year 2025`.
- Files modified:
  - `frontend/src/components/home/Hero.tsx`
  - `tdtn.md`
  - `memory.md`
- Key decisions:
  - Kept the existing layout and styling intact and changed only the requested wording in the hero eyebrow badge.
- Verification:
  - `frontend`: `npm run typecheck` passed.
- Status: Complete locally

### 2026-04-21 — Email Address Normalization
- What was changed: Updated hardcoded Sold With Sweeney email references across the app, backend services, seed defaults, tests, and supporting docs to `info@soldwithsweeney.com`.
- Files modified:
  - `frontend/src/app/(main)/about/page.tsx`
  - `frontend/src/app/(main)/buy/page.tsx`
  - `frontend/src/app/(main)/sell/page.tsx`
  - `frontend/src/app/(main)/invest/page.tsx`
  - `backend/services/email_service.py`
  - `backend/services/gemini.py`
  - `backend/seed.py`
  - `backend/tests/test_notification_service.py`
  - `BRANDON_RE_SPEC.md`
  - `docs/superpowers/plans/2026-03-18-brandon-re-platform.md`
  - `docs/superpowers/plans/2026-03-23-full-e2e-qa-polish.md`
  - `docs/superpowers/plans/2026-04-10-brandon-notification-queue.md`
  - `tdtn.md`
  - `memory.md`
- Key decisions:
  - Swapped public contact email copy and mailto links to `info@soldwithsweeney.com`.
  - Updated the internal notification recipient constant and the seeded default admin email to the same address for consistency.
  - Kept historical task notes accurate by removing specific old-email references where needed instead of pretending a new live verification already happened.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest tests.test_notification_service tests.test_seed_admin_user -v` passed.
  - `frontend`: `npm run typecheck` passed.
- Status: Complete locally

### 2026-04-20 — Chat Booking Label Copy Update
- What was changed: Renamed the chatbot's `Google Meet` booking label back to `Video Call`.
- Files modified:
  - `frontend/src/components/chat/CalendarPickerCard.tsx`
  - `frontend/src/components/chat/ChatPanel.tsx`
  - `frontend/src/hooks/useChat.ts`
- Key decisions:
  - Updated both the visible meeting-type button label and the guided booking prompt copy so the chatbot uses the same wording everywhere.
- Verification:
  - `frontend`: `npm run typecheck` passed.
- Status: Complete locally

### 2026-04-20 — Chat Booking Options + Same-Day Past Slot Filtering
- What was fixed: Restored all three booking format options in the chatbot booking flow and removed already-started same-day appointment times from availability.
- Files modified:
  - `frontend/src/components/chat/CalendarPickerCard.tsx`
  - `frontend/src/components/chat/ChatPanel.tsx`
  - `frontend/src/hooks/useChat.ts`
  - `backend/services/calendar_service.py`
  - `backend/tests/test_booking_calendar.py`
- Key decisions:
  - `Book Brandon` chat entry now opens the booking chooser in guided mode instead of forcing a phone-only next-available shortcut.
  - The three visible booking choices are `Phone Call`, `Video Call`, and `In Person`.
  - Added a backend `_current_eastern_time()` helper so same-day slot generation can skip any slot whose start time is already at or before the current Eastern time.
  - Hardened booking validation so already-started appointment times are rejected even if a stale client somehow submits one.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest tests.test_booking_calendar -v` passed.
  - `frontend`: `npm run typecheck` passed.
  - Browser smoke test passed: homepage `Book Brandon` opened chat with `Phone Call`, `Video Call`, and `In Person` buttons visible.
  - Backend slot-filter smoke check passed: with the clock pinned to `2:16 PM ET`, available phone slots started at `3:00 PM`.
- Status: Complete locally

### 2026-04-18 — Book Brandon CTA Opens Chatbot Booking Slots
- What was built: Updated booking CTAs so visitors are sent directly into the chatbot booking flow with Brandon's next available calendar slots.
- Files created:
  - `frontend/src/lib/booking-chat.ts`
  - `frontend/src/components/shared/BookBrandonCTA.tsx`
- Files modified:
  - `frontend/src/components/layout/Navbar.tsx`
  - `frontend/src/components/chat/ChatWidget.tsx`
  - `frontend/src/components/chat/ChatPanel.tsx`
  - `frontend/src/components/chat/CalendarPickerCard.tsx`
  - `frontend/src/hooks/useChat.ts`
  - `frontend/src/app/(main)/buy/page.tsx`
  - `frontend/src/app/(main)/about/page.tsx`
  - `frontend/src/components/seller/PropertyEvaluator.tsx`
  - `frontend/src/components/investor/MeetingGate.tsx`
- Key decisions:
  - Added a global `sws:open-booking-chat` client event so any CTA can open the persistent chat widget without prop-drilling through the layout.
  - Added a reusable `BookBrandonCTA` client wrapper for server-rendered pages that need to open chatbot booking.
  - Calendar picker now supports `next_available` mode, which searches from today forward and shows the first available phone-call slots immediately.
  - Left explicit `Call Direct` and `Call Brandon` phone links as phone links; only booking/strategy/valuation CTAs now launch the chatbot booking path.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - `frontend`: `npm run build` passed.
  - Browser smoke test passed: homepage `Book Brandon` opened the chatbot, showed the direct booking message, called `/api/v1/booking/available-slots`, and displayed next available slot buttons.
- Status: Complete locally

### 2026-04-18 — Frontend Vercel Typecheck Fix
- What was fixed: Resolved the deployment-blocking TypeScript errors from the About page and buyer journey component.
- Files modified:
  - `frontend/src/app/(main)/about/page.tsx`
  - `frontend/src/components/buyer/MonopolyJourney.tsx`
- Key decisions:
  - Kept the REALTOR® JSX formatting, but stopped using rendered JSX labels as React keys.
  - Added stable string ids for About-page bio chips and award cards.
  - Updated the buyer journey step type to allow rendered text and gave each step a stable string key.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - `frontend`: `npm run build` passed.
  - Build still logs non-fatal fallback warnings when the local backend content API is unavailable and the Instagram token is invalid.
- Status: Complete

### 2026-04-18 — Chatbot Booking Next Available Times
- What was built: Updated the chatbot calendar picker so an empty selected date no longer dead-ends the booking flow.
- Files modified:
  - `frontend/src/components/chat/CalendarPickerCard.tsx`
- Key decisions:
  - Reused the existing `/api/v1/booking/available-slots` endpoint so Google Calendar remains the source of truth.
  - When a selected date has no slots, the widget now scans the next 10 business days and shows up to 6 next available time options.
  - Suggested time buttons include both the date and time, and selecting one updates the booking confirmation date automatically.
  - In-person suggestions preserve the entered location and remain filtered by travel-time checks.
- Verification:
  - `frontend`: No `CalendarPickerCard.tsx` type errors were reported in the typecheck output.
  - `frontend`: The unrelated About-page and buyer journey type errors were fixed later on 2026-04-18.
- Status: Complete

### 2026-04-13 — Investor Calculator 80% Rule + Blank Inputs
- What was built: Updated the investor calculator's max-offer metric to an 80% rule and removed prefilled deal values so instant pricing only appears after visitors enter their own numbers.
- Files modified:
  - `frontend/src/lib/investor-calc.ts`
  - `frontend/src/components/investor/InvestorCalculator.tsx`
  - `frontend/src/components/investor/AnalysisResults.tsx`
- Key decisions:
  - Changed the offer cap formula from `ARV x 70% - rehab` to `ARV x 80% - rehab`.
  - Renamed the metric label to `80% Rule Offer Cap`.
  - Added helper copy explaining that the cap is a conservative max purchase offer, calculated as `ARV x 80% minus rehab`.
  - Confirmed the user's example now returns `$570,000 x 80% - $50,000 = $406,000`.
  - Converted the calculator inputs from prefilled numeric state to blank string state, with parsing only after all fields have valid values.
  - The instant snapshot and full-report gate now stay hidden until a complete set of deal inputs is entered.
- Verification:
  - `frontend`: direct calculator smoke check confirmed the offer cap is `$406,000` for the user's sample.
  - `frontend`: `npm run typecheck` passed.
- Status: Complete locally

### 2026-04-11 — Investor Calculator Short-Term Loan Fix
- What was built: Updated the investment calculator so one-year fix-and-flip style loans use interest-only debt service instead of being fully amortized over 12 months.
- Files created:
  - `backend/tests/test_investor_metrics.py`
- Files modified:
  - `backend/routers/investor.py`
  - `frontend/src/lib/investor-calc.ts`
  - `frontend/src/components/investor/AnalysisResults.tsx`
  - `frontend/src/components/investor/FlipCaseStudy.tsx`
- Key decisions:
  - Loan terms of 1-2 years are modeled as interest-only bridge / fix-and-flip debt.
  - Loan terms of 3+ years stay on the standard amortized payment formula.
  - The frontend now carries a `loanStructure` metric and explains the assumption under the flip-analysis cards.
  - Corrected the case-study percentage inputs from decimal-style values to the calculator's current percent-style inputs.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest tests.test_investor_metrics -v` first failed against the old one-year math (`$30,522.31/mo` vs expected `$2,057.71/mo`).
  - `backend`: `./.venv/bin/python -m unittest discover -s tests -v` passed with 32 tests.
  - `frontend`: `npm run typecheck` passed.
  - `frontend`: direct calculator smoke checks passed for both one-year interest-only and 30-year amortized scenarios.
- Status: Complete locally

### 2026-04-10 — Brandon Notification Queue Implemented
- What was built: Added a durable `notification_jobs` queue for Brandon-only internal email notifications, wired it into lead capture, chatbot lead capture, funnel registrations, booking attempts, booking confirmations, seller calculator activity, seller calculator ratings, investor full-report requests, and investor calculator engagement.
- Files created:
  - `backend/models/notification_job.py`
  - `backend/services/notification_service.py`
  - `backend/alembic/versions/7efdda0d6b65_add_notification_jobs.py`
  - `backend/tests/test_notification_service.py`
  - `backend/tests/test_leads_notifications.py`
  - `backend/tests/test_investor_notifications.py`
- Files modified:
  - `backend/alembic/env.py`
  - `backend/main.py`
  - `backend/routers/leads.py`
  - `backend/routers/chat.py`
  - `backend/routers/funnels.py`
  - `backend/routers/booking.py`
  - `backend/routers/evaluator.py`
  - `backend/routers/investor.py`
  - `backend/services/email_service.py`
  - `backend/tests/test_booking_calendar.py`
  - `backend/tests/test_evaluator_router.py`
  - `frontend/src/components/investor/InvestorCalculator.tsx`
- Key decisions:
  - Notifications now save to DB first as `notification_jobs` with status, attempts, next retry time, last error, and delivered timestamp.
  - Failed notification sends are kept and retried with escalating backoff instead of being silently dropped.
  - Added a background retry loop in `backend/main.py` so failed jobs continue retrying even without fresh user traffic.
  - Booking attempts are queued in a separate DB session before downstream booking work continues, so Brandon can still be notified of attempted bookings even if later calendar or booking persistence steps fail.
  - Booking confirmations now use the queue instead of direct inline SMTP calls.
  - Seller evaluator usage and ratings now both notify Brandon.
  - Investor report requests notify Brandon from the backend, and investor calculator engagement now sends a one-time event from the frontend per browser session with retry-on-failure.
  - Email rendering was centralized with explicit subjects for lead, funnel, chat, booking, seller calculator, and investor events.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest discover -s tests -v` passed (`30` tests).
  - `frontend`: `npm run typecheck` passed.
  - `backend`: `./.venv/bin/alembic upgrade head` succeeded, upgrading `0d8d9bce6f44 -> 7efdda0d6b65`.
- Deployment note:
  - The connected database now has the `notification_jobs` table, but the live Railway backend still needs these code changes deployed before production traffic will use the queue and retry loop.
- Status: Complete locally; ready to deploy

### 2026-04-10 — Brandon Notification Queue Spec + Plan Drafted
- What was written:
  - A notification-queue design spec for Brandon-only internal email alerts with durable retry-until-delivered behavior.
  - A detailed implementation plan covering the new `notification_jobs` model, queue service, route integrations, investor engagement endpoint, retry processing, and verification steps.
- Files created:
  - `docs/superpowers/specs/2026-04-10-brandon-notification-queue-design.md`
  - `docs/superpowers/plans/2026-04-10-brandon-notification-queue.md`
- Coverage included in the plan:
  - Standard leads
  - Funnel registrations
  - Chatbot lead capture
  - Booking attempts
  - Booking confirmations
  - Seller calculator usage
  - Seller calculator rating feedback
  - Investor full-report requests
  - Investor calculator engagement before contact capture
- Status: Planning complete; implementation not started yet in this plan phase

### 2026-04-10 — Booking Email Delivery Diagnosis
- What was analyzed: Investigated why Brandon did not receive a booking email even though SMTP is configured.
- Files reviewed:
  - `backend/routers/booking.py`
  - `backend/services/email_service.py`
  - `backend/config.py`
- Findings:
  - SMTP credentials themselves are not the primary blocker in the local environment; direct calls to `send_test_email()` and `notify_new_booking()` both returned `True`.
  - Booking notifications are only attempted at the very end of `create_booking(...)`, after:
    - calendar token load
    - slot validation
    - Google Calendar event creation
    - booking DB insert / refresh
  - Because the live booking flow had been failing before that point (`bookings.location` schema mismatch, then non-durable Google refresh-token persistence), Brandon would not get an email even if SMTP was perfectly configured.
  - The current code also hides email send failures:
    - `backend/services/email_service.py` catches SMTP exceptions and returns `False`
    - `backend/routers/booking.py` ignores that boolean return value and only logs exceptions
    - result: the API can appear successful even when Brandon never receives an email
  - The notification is sent from Brandon's own Gmail SMTP account to the same Brandon email address, which can make Gmail delivery less obvious in the inbox even when accepted by SMTP.
- Status: Diagnosed; no product-code change in this analysis pass

### 2026-04-10 — Live Chat Booking Verification + Booking Schema/Token Persistence Fix
- What was analyzed and fixed:
  - Ran a live production booking verification against the chatbot/booking endpoints after Google Calendar was reconnected.
  - Found that the live chatbot correctly returned the calendar widget, but the booking POST crashed because the production `bookings` table was missing the `location` column.
  - Added a new Alembic migration for `bookings.location`, applied it to the connected production database, and added cleanup logic so orphaned Google events are deleted if the DB save fails after calendar insertion.
  - Found a second production issue: the Google Calendar refresh token was only being written into the container-local `.env`, which is not durable on Railway across deploys / instance changes.
  - Added DB-backed refresh-token persistence helpers in the booking router so the OAuth callback also stores the token in the `settings` table, and booking/status/availability routes load the token from DB before calling Google Calendar.
- Files modified:
  - `backend/alembic/versions/0d8d9bce6f44_add_location_to_bookings.py`
  - `backend/routers/booking.py`
  - `backend/services/calendar_service.py`
  - `backend/tests/test_booking_calendar.py`
  - `backend/tests/test_booking_token_persistence.py`
- Live verification details:
  - `POST /api/v1/chat/` on the live Railway backend returned `widget: "calendar_picker"` for a booking request.
  - Before the schema fix, `POST /api/v1/booking/` failed with `UndefinedColumnError: column "location" of relation "bookings" does not exist`.
  - The first failed live booking attempt created a real Google Calendar event before the DB insert crashed, which removed the `2026-04-13 09:00 AM ET` slot from availability.
  - After applying the migration, the live database schema now includes `bookings.location`.
  - Repeated live availability / booking checks then showed `Google Calendar needs one-time authorization before Brandon can accept bookings.`, confirming the refresh token was not durably persisted in Railway.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest tests.test_booking_calendar -v` passed (`5` tests).
  - `backend`: `./.venv/bin/python -m unittest tests.test_booking_token_persistence -v` passed (`3` tests).
  - `backend`: `./.venv/bin/python -m unittest discover -s tests -v` passed (`16` tests) after the schema + cleanup changes.
  - `backend`: `./.venv/bin/alembic upgrade head` succeeded against the connected production database, upgrading `9c1fb48ea689 -> 0d8d9bce6f44`.
- Remaining external step:
  - After deploying the new DB-backed token-persistence code, Brandon will need to reconnect Google Calendar one more time so the refresh token is stored durably in the database instead of only the Railway container filesystem.
- Status: Local code fix complete, production DB migrated, still needs backend deploy + one reconnect to make live chatbot bookings reliable again

### 2026-04-10 — Google Calendar OAuth Access Blocked Diagnosis
- What was analyzed: Investigated why the Google Calendar connect flow shows `Access blocked` during Brandon's admin Settings authorization attempt.
- Files reviewed:
  - `backend/config.py`
  - `backend/services/calendar_service.py`
  - `backend/routers/booking.py`
  - `frontend/src/app/admin/settings/page.tsx`
  - `backend/tests/test_calendar_oauth.py`
  - `backend/.env.example`
- Root cause found:
  - The generated Google OAuth URL is using `http://localhost:8000/api/v1/booking/calendar/callback` as the redirect URI because `GOOGLE_CALENDAR_REDIRECT_URI` is not set in the backend environment and the app falls back to the localhost default in `backend/config.py`.
  - A direct repro against Google's OAuth endpoint returned `redirect_uri_mismatch`, which surfaces in the browser as `Access blocked` / `This app's request is invalid`.
- Verification:
  - Generated the live auth URL from `services.calendar_service.get_auth_url(...)`.
  - Parsed the outgoing OAuth query and confirmed `redirect_uri=http://localhost:8000/api/v1/booking/calendar/callback`.
  - Direct fetch of the Google OAuth URL finished at `https://accounts.google.com/signin/oauth/error?...authError=...redirect_uri_mismatch...`.
- Fix required:
  - Set `GOOGLE_CALENDAR_REDIRECT_URI` in the deployed backend environment to the real public backend callback URL.
  - Add that exact same callback URL to the OAuth client's Authorized redirect URIs in Google Cloud Console.
- Status: Diagnosed; no product code changed in this analysis pass

### 2026-04-10 — Admin Login Seed Resync Fix
- What was built: Fixed the admin seeding flow so Brandon's default admin account is not left with a stale password hash when the row already exists in the database.
- Files modified:
  - `backend/seed.py`
  - `backend/tests/test_seed_admin_user.py`
- Key decisions:
  - Added `DEFAULT_ADMIN_EMAIL` and `DEFAULT_ADMIN_PASSWORD` constants so the seed behavior is centralized.
  - Introduced `ensure_admin_user(...)` to handle both create and update cases for the admin account.
  - If the Brandon admin row already exists but its stored hash no longer matches the expected seeded password, the seed now rewrites the hash instead of silently leaving the stale credentials in place.
  - Ran the updated seed against the connected database so the live Brandon admin row was resynced immediately.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest tests.test_seed_admin_user -v` passed (`2` tests).
  - `backend`: direct database verification confirmed `pwd_context.verify("changeme123!", user.hashed_password) == True` for the seeded admin account.
  - `backend`: direct ASGI smoke test to `POST /api/v1/auth/login` with Brandon's seeded credentials returned `200` and a bearer token.
- Root cause:
  - `seed.py` previously only created the admin user if it did not exist, so an older password hash in the live database could persist forever even though the seed file still advertised `changeme123!`.
- Status: Complete

### 2026-04-10 — Investor Preview Unlock Flow + Seller Expectation Ratings
- What was built: Reworked the investor calculator so live deal numbers are visible immediately and moved the contact gate to the deeper AI report only; also added a post-result expectation rating flow to the seller valuation tool and persisted every valuation calculation plus rating in the database.
- Files modified:
  - `backend/routers/evaluator.py`
  - `backend/tests/test_evaluator_router.py`
  - `frontend/src/components/investor/InvestorCalculator.tsx`
  - `frontend/src/components/investor/MeetingGate.tsx`
  - `frontend/src/components/investor/FullReportResults.tsx`
  - `frontend/src/components/investor/report-types.ts`
  - `frontend/src/components/seller/PropertyEvaluator.tsx`
- Key decisions:
  - Investor metrics now render live on the page with no blur/lock overlay.
  - The gated step is now specifically for the full AI report, which uses the existing `/api/v1/investor/analyze` backend endpoint and captures name/email/phone before requesting it.
  - Changing any investor input invalidates the unlocked full report so stale report copy is never shown against new deal numbers.
  - Fixed investor instant-math percentage handling so `Down Payment %` and `Interest Rate` now behave like real percentages (`15`, `7`) instead of requiring decimal fractions (`0.15`, `0.07`).
  - Updated investor flip math to include estimated closing costs and surfaced those assumptions directly in the UI.
  - Seller valuations now create a `seller_evaluator_calculation` analytics event on every run, regardless of whether the visitor leaves contact info.
  - Seller result view now asks one follow-up question with three responses:
    - `This is what I expected to get`
    - `This is under what I expected to get`
    - `This is more than what I expected to get`
  - Rating submissions are stored as linked `seller_evaluator_rating` analytics events keyed to the originating calculation id.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest discover -s tests -v` passed (`13` tests).
  - `frontend`: `npm run typecheck` passed.
  - `backend`: seller evaluator smoke test returned a live `calculation_id`.
  - `backend`: `POST /api/v1/evaluator/{calculation_id}/rating` returned `{"ok": true}`.
  - `backend`: `/api/v1/investor/analyze` logged `200 OK` during live smoke testing.
  - Browser test on `http://localhost:3000/invest` completed end-to-end with screenshots captured at:
    - `investor-instant-results-check.png`
    - `investor-full-report-check.png`
  - Using the user-provided flip scenario values, the instant snapshot produced:
    - `Estimated Profit`: `$78,799`
    - `Holding Costs`: `$14,081`
    - `Closing Costs`: `$13,350`
    - `Total Project Cost`: `$491,201`
- Known note:
  - The investor UI still does not take a property address as a direct input, so the user-provided `50 Cheever Ave, Dracut, MA 01826` address could not be entered into the calculator itself; the browser test used the provided financial inputs only.
- Status: Complete

### 2026-04-10 — Booking Hardening + Calendar OAuth Bootstrap + Seller Estimate Recalibration
- What was built: Hardened booking against Brandon's real calendar rules, added the missing one-time Google Calendar OAuth connect flow in admin settings, and recalibrated the seller estimate model to a more realistic local market band.
- Files modified:
  - `backend/.env.example`
  - `backend/config.py`
  - `backend/routers/booking.py`
  - `backend/routers/evaluator.py`
  - `backend/services/calendar_service.py`
  - `backend/services/evaluator_service.py`
  - `backend/services/maps_service.py`
  - `frontend/src/app/(main)/sell/page.tsx`
  - `frontend/src/app/admin/settings/page.tsx`
  - `frontend/src/components/chat/CalendarPickerCard.tsx`
  - `backend/tests/test_booking_calendar.py`
  - `backend/tests/test_calendar_oauth.py`
  - `backend/tests/test_evaluator_service.py`
- Key decisions:
  - Booking hours are now enforced as Monday-Friday, 9 AM-6 PM Eastern with slot revalidation at booking time.
  - In-person meetings continue to use neighboring calendar-event locations plus travel-time checks, with OSRM fallback when Google Maps is unavailable.
  - Added admin calendar endpoints for status, auth URL generation, and OAuth callback so Brandon can connect Google Calendar without hand-editing env vars.
  - OAuth callback persists `GOOGLE_CALENDAR_REFRESH_TOKEN` into `backend/.env` and updates runtime settings so the current server process can start using it immediately.
  - Settings page Google Calendar card is now dynamic and can start or refresh the connection flow instead of showing a static placeholder.
  - Seller pricing baselines were recalibrated so Lowell-area single-family estimates no longer overshoot the current local market band.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest discover -s tests -v` passed (`10` tests).
  - `frontend`: `npm run typecheck` passed.
  - `backend`: `GET /api/v1/booking/calendar/status` returns `configured: true`, `connected: false`, `can_connect: true` when Brandon still needs OAuth.
  - `backend`: `GET /api/v1/booking/calendar/auth-url` returns a valid Google OAuth URL with offline access, consent prompt, and signed state.
  - `backend`: direct request to the Google OAuth URL returned `HTTP 302`, confirming handoff to Google.
  - `backend`: booking endpoints now return `Google Calendar needs one-time authorization before Brandon can accept bookings.` until the real Calendar consent is completed.
  - `backend`: seller evaluator smoke test for `50 Cheever Ave, Lowell, MA 01852` returned `$512,000-$602,000`.
- Blocker:
  - Live event creation in Brandon's actual Google Calendar still requires Brandon to complete the one-time Google consent so the app can receive a refresh token.
- Status: Complete in code; waiting on external Google authorization to finish true live booking

### 2026-03-19 — Project Initialized
- What was built: Git repo, project config files (claude.md, tdtn.md, memory.md, .gitignore, .env.example)
- Files created: .gitignore, claude.md, tdtn.md, memory.md, .env.example, BRANDON_RE_SPEC.md committed
- Key decisions: Using #0a0a0a near-black (taste-skill: NO pure #000000), Neon PostgreSQL for DB
- Status: Complete

### 2026-03-19 — Task 14: Buyers Experience Page
- What was built: Full `/buy` page route with hero, MonopolyJourney accordion, team section, BuyerMistakes grid, reviews 2x2, and lead capture form
- Files created: `frontend/src/app/buy/page.tsx`, `frontend/src/components/buyer/MonopolyJourney.tsx`, `frontend/src/components/buyer/BuyerMistakes.tsx`
- Files modified: `frontend/src/components/shared/LeadCaptureForm.tsx` — added `source`, `leadType`, `ctaText` props
- Key decisions: Used `DeviceMobile` Phosphor icon (not `Smartphone` which doesn't exist in this package version); Phosphor SSR import used in Server Component page; accordion opens Phase 1 by default
- Status: Complete — TypeScript clean, committed d6ae4f7

### 2026-03-19 — Task 17: About Brandon Page
- What was built: Full About page at /about with 7 sections
- File created: frontend/src/app/about/page.tsx (996 lines)
- Sections: Hero (split layout + headshot), Stats strip (4 glass cards), Bio deep-dive (sticky image + 3 glassmorphism panels), Designations & Memberships (5 logos + 2 award cards), MS is BS New England (story panel + $300K stat + external CTA), Team (SWS TEAM photo), Contact/CTA (Phone/EnvelopeSimple/MapPin icons, Book a Call button)
- Key decisions: 7 sub-section components composed in single page.tsx; useInView per-section stagger; external links use <a target="_blank">; REALTOR® with ® in all occurrences; no emojis anywhere
- TypeScript: 0 errors
- Status: Complete — committed 071a647

### 2026-03-20 — Task 20: Admin Sub-Pages
- What was built: 5 admin pages — leads, content, funnels, analytics, settings
- Files created:
  - `frontend/src/app/admin/leads/page.tsx` — leads table with filter pills, status badges, inline detail panel with PATCH status/notes
  - `frontend/src/app/admin/content/page.tsx` — content blocks grid, inline edit/save/cancel with PUT
  - `frontend/src/app/admin/funnels/page.tsx` — funnels table, publish action, copy link with 2s feedback, create form with AI loading state
  - `frontend/src/app/admin/analytics/page.tsx` — stats strip, top pages/events with bar visualization, recent events table
  - `frontend/src/app/admin/settings/page.tsx` — integrations status cards, admin password form (coming soon), site info card
- Key decisions: All pages use admin_token guard; loading skeletons via animate-pulse; empty + error states with Phosphor icons; no emojis
- TypeScript: 0 errors
- Status: Complete — committed 612de2e

### 2026-03-20 — Task 22: Frame Extraction Pipeline & Video Compression
- What was built: Frame extraction pipeline for ExplodingHouseScroll + aerial drone video compression
- Videos found at: `frontend/public/assets/` (not `videos/` — actual location differs from task spec)
- ffmpeg: Available at `/opt/homebrew/bin/ffmpeg` v8.0.1
- Frames extracted: 60 WebP frames at `frontend/public/frames/frame_001.webp`–`frame_060.webp` (12fps, 1920px wide, quality 85)
- Frames also extracted as JPEG: 60 frames at `frontend/public/frames/house-blast/frame_0001.jpg`–`frame_0060.jpg` (matches ExplodingHouseScroll.tsx component path)
- Video compressed: `aerial_drone_shot.mp4` compressed from 13MB → 3.2MB (75% reduction, H.264 CRF 28, faststart, no audio)
- Scripts created: `scripts/extract-frames.sh`, `scripts/compress-videos.sh` (both chmod +x)
- Gitignore: `frontend/public/frames/.gitignore`, `frontend/public/frames/house-blast/.gitignore`, root `.gitignore` updated
- Key decisions: house_blast.mp4 is 5s at 24fps (121 frames total); used fps=12 filter to get exactly 60 frames; JPG format used for component path compatibility (house-blast/)
- Status: Complete

### 2026-03-23 — Deployment Fixes & Model Updates
- What was built: Resolved Railway deployment issues, fixed Instagram build error, and updated Gemini models.
- Files modified:
  - `backend/services/gemini.py`: Updated models to `gemini-1.5-pro` (for pro tasks) and `gemini-1.5-flash` (standard).
  - `frontend/src/app/(main)/page.tsx`: Changed Instagram fetch error to `console.warn` to prevent build failures on expired tokens.
  - `backend/Dockerfile`: Updated to use dynamic `PORT` and root build context for Railway compatibility.
  - `railway.json`: Created at root to force Docker builder and bypass Railpack/Caddy detection.
- Force-added: `frontend/public/frames/phase-1-swiping.jpg`, `phase-2-touring.jpg`, `phase-3-keys.jpg` (previously gitignored).
- Key decisions: Using explicit `railway.json` to force Docker; switched to dynamic `$PORT` for Railway edge routing; enabled `PYTHONUNBUFFERED=1` for live logs.
- Status: Complete

### 2026-03-27 — Chatbot Architecture Analysis
- What was analyzed: End-to-end chatbot flow across frontend widget, React chat state, FastAPI chat router, Gemini service, and inline booking widget behavior.
- Files reviewed: `frontend/src/components/layout/ClientWidgets.tsx`, `frontend/src/components/chat/ChatWidget.tsx`, `frontend/src/components/chat/ChatPanel.tsx`, `frontend/src/components/chat/CalendarPickerCard.tsx`, `frontend/src/hooks/useChat.ts`, `backend/routers/chat.py`, `backend/services/gemini.py`, `backend/routers/booking.py`
- Key findings:
  - Chat is mounted site-wide via `ClientWidgets` and is entirely client-side on the frontend.
  - Backend chat API currently returns only `{ response: string }`; there is no structured UI payload.
  - Frontend only upgrades one special case today: booking tags like `[BOOK_MEETING]` are stripped from text and converted into the inline `CalendarPickerCard`.
  - Assistant message bubbles render plain text only; there is no support for per-message actions, chips, cards, or routed CTAs.
  - `/api/v1/chat/lead` exists for chatbot lead capture, but the current frontend does not call it.
  - `showBooking` state exists in `useChat` but is not used by the rendered UI beyond being toggled.
- Recommendation:
  - Best next step is a structured assistant response contract such as `text + actions + widget`, then render actions as buttons in the chat bubble.
  - Avoid heuristic parsing of plain prose into buttons.
  - Full free-form generative UI is not the best first move for the current buy/sell/invest/book flows; a bounded server-driven UI layer is lower risk and fits the current architecture better.
- Status: Complete — analysis only, no product code changed

### 2026-03-27 — Chatbot Structured Actions Upgrade
- What was built: Replaced the plain-text-only chatbot contract with a structured assistant payload supporting `text`, `actions[]`, and `widget`, then rendered those actions as premium in-chat buttons.
- Files modified:
  - `backend/services/gemini.py`: Updated chatbot instructions to return JSON, added structured response parsing, action normalization, widget normalization, legacy booking-tag fallback, and discovery-action fallback logic.
  - `backend/routers/chat.py`: Expanded chat API response model to include `text`, `actions`, `widget`, and backward-compatible `response`.
  - `frontend/src/hooks/useChat.ts`: Added frontend action/widget types, normalized structured API payloads, preserved legacy booking-tag fallback, and attached actions to assistant messages.
  - `frontend/src/components/chat/ChatPanel.tsx`: Rendered assistant actions as glassmorphism buttons, added action click handling for chat replies, page navigation, and booking widget launch.
- UX behavior now supported:
  - AI can return tappable `send_message` actions that continue the conversation.
  - AI can return `navigate` actions to `/buy`, `/sell`, `/invest`, and `/about`.
  - AI can return `open_widget` or top-level `widget` instructions for the inline booking calendar.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - `backend`: `python -m py_compile backend/routers/chat.py backend/services/gemini.py` passed.
  - API smoke test: `POST /api/v1/chat/` returned structured actions for “What can you help me with?”
  - Browser test: Opened chat on `http://localhost:3000`, sent “What can you help me with?”, confirmed four rendered action buttons, clicked `Buy a home`, confirmed follow-up response with new actions, clicked `Book a call`, confirmed inline calendar widget opened.
  - Screenshots captured: `chat-structured-actions.png`, `chat-action-booking-widget.png`
- Known verification note:
  - `npm run lint` still fails on a pre-existing unrelated error in `frontend/src/components/shared/RotatingText.tsx` (`no-explicit-any`) plus several unrelated warnings.
- Status: Complete

### 2026-04-02 — About / Buy / Sell / Home Polish Pass
- What was built: Implemented requested copy and UI refinements across the About, Buy, Sell, and home pages, including a buyer flashcard experience and a fix for the homepage hero video showing Brandon's face before playback.
- Files modified:
  - `frontend/src/app/(main)/about/page.tsx`
  - `frontend/src/app/(main)/buy/page.tsx`
  - `frontend/src/app/(main)/sell/page.tsx`
  - `frontend/src/components/buyer/BuyerMistakes.tsx`
  - `frontend/src/components/home/GivingBack.tsx`
  - `frontend/src/components/home/Hero.tsx`
- About page changes:
  - Changed the hero image badge separator so `|` renders in white.
  - Reworked the stats strip so the cards tie directly to Brandon-specific milestones instead of generic stats.
  - Expanded awards coverage with added recognition cards for MAR Good Neighbor, NEAR Good Neighbor, and Distinguished Young Professional.
  - Updated team/contact copy to use `the Sold With Sweeney & Co. team`.
  - Replaced `research` with `advocacy` in the MS fundraising copy.
- Buy / Sell changes:
  - Added a new Buy-page CTA: `Find "THE ONE"` with a downward scroll target.
  - Changed the buyer lead-section headline gold text from `Dream Home` to `THE ONE`.
  - Converted the buyer mistakes section into interactive flip-style flashcards for clearer reading.
  - Changed the seller lead-section headline to `Stop Listing. Start Moving.`
- Home page changes:
  - Removed the hero video poster image that used Brandon's headshot.
  - Added a dark fallback background and fade-in behavior until the video is loaded, preventing the initial headshot flash.
  - Updated Giving Back copy from `research` to `advocacy`.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - Route checks via `curl` confirmed the updated About, Buy, Sell, and home-page markup.
  - Home page hero markup no longer includes a `poster` attribute, and now renders a preload + fade-in fallback state.
- Blocker:
  - The repo does not currently include the requested `Brandon and Paige at Maine gala` image or an awards-collage image, so those two image swaps could not be completed from local assets.
- Known verification note:
  - `npm run lint` still fails on the pre-existing unrelated `frontend/src/components/shared/RotatingText.tsx` `no-explicit-any` error plus older warnings in unrelated files.
- Status: Complete with image-asset blocker noted

### 2026-04-09 — Buyer Mistakes Single-Card Revision
- What was built: Simplified the Buy-page `What Most Buyers Get Wrong` experience from a four-card deck into one rotating hero card.
- Files modified:
  - `frontend/src/components/buyer/BuyerMistakes.tsx`
- Implementation details:
  - Removed the `Rotating Buyer Playbook` explainer panel entirely.
  - Reworked the right column to render a single cinematic card that auto-advances to the next buyer mistake every 4.2 seconds.
  - Kept click-to-flip behavior so the active card still toggles between `Buyer Mistake` and `The Fix`.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - Browser automation confirmed the active card rotates from `Shopping before pre-approval` to `Using all your savings for the down payment`.
  - Browser automation confirmed clicking the rotated card flips it into `The Fix`.
  - Screenshots refreshed: `buy-mistakes-rotating-initial.png`, `buy-mistakes-rotating-flipped.png`
- Status: Complete

### 2026-04-09 — Home Reviews + Buyer Mistakes Motion Refresh
- What was built: Filled the blank space in the home-page reviews rail by stacking two reviews on the left and rebuilt the Buy-page `What Most Buyers Get Wrong` section into a rotating flip-card deck.
- Files modified:
  - `frontend/src/components/home/TrustSection.tsx`
  - `frontend/src/components/buyer/BuyerMistakes.tsx`
- Implementation details:
  - Added a new non-duplicate Google review from `reviews.html` by Madison Levanti and changed the home testimonials layout to a 2-left / 3-right composition.
  - Reworked the buyer mistakes module into a premium two-column section with a timed upward rotation, hover-to-pause behavior, and click-to-flip cards that switch between `Buyer Mistake` and `The Fix`.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - Browser automation confirmed the home reviews now render both left-rail testimonials including Madison Levanti.
  - Browser automation confirmed the buyer deck reorders over time:
    - Before: `Shopping before pre-approval` → `Using all your savings for the down payment` → `Buying with the listing agent` → `Picking a lender based on rate alone`
    - After rotation: `Using all your savings for the down payment` → `Buying with the listing agent` → `Picking a lender based on rate alone` → `Shopping before pre-approval`
  - Browser automation also confirmed clicking a card flips it to `The Fix`.
  - Screenshots captured: `home-reviews-two-left.png`, `buy-mistakes-rotating-initial.png`, `buy-mistakes-rotating-flipped.png`
- Status: Complete

### 2026-04-10 — Brandon Notification Queue Hardening
- What was built: Tightened the new Brandon notification queue so user actions commit before immediate email delivery is attempted.
- Files modified:
  - `backend/services/notification_service.py`
  - `backend/routers/leads.py`
  - `backend/routers/chat.py`
  - `backend/routers/funnels.py`
  - `backend/routers/booking.py`
  - `backend/routers/evaluator.py`
  - `backend/routers/investor.py`
  - `backend/tests/test_booking_calendar.py`
  - `backend/tests/test_evaluator_router.py`
  - `backend/tests/test_investor_notifications.py`
  - `backend/tests/test_leads_notifications.py`
- Implementation details:
  - Route integrations now commit the saved lead, booking, calculator event, or rating plus its pending notification job before any immediate send pass runs.
  - `enqueue_notification_in_new_session()` now persists the pending job first and only then triggers the retry worker path.
  - Notification email table rendering now HTML-escapes payload content before composing Brandon-facing emails.
- Verification:
  - `backend`: `./.venv/bin/alembic upgrade head` passed.
  - `backend`: `./.venv/bin/python -m unittest discover -s tests -v` passed with 30 tests.
  - `frontend`: `npm run typecheck` passed.
- Status: Complete

### 2026-04-02 — About Gala Image Swap
- What was built: Replaced the About page's lower team image with the provided Brandon and Paige at Maine gala photo.
- Files modified:
  - `frontend/src/app/(main)/about/page.tsx`
- Files added:
  - `frontend/public/headshots/brandon-and-paige-maine-gala.jpeg`
- Implementation details:
  - Updated the About page `TeamSection` image source to the new gala asset.
  - Changed the image framing to a portrait-friendly `4/5` aspect ratio for better crop behavior.
  - Updated the image alt text to `Brandon and Paige at the Maine gala`.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - Route check confirmed `/about` references the new image asset.
  - Screenshot captured: `about-gala-update-check.png`
- Status: Complete

*Claude Code: Update this file after completing every task.*

### 2026-03-31 — Invest & Sell Hero Videos
- What was built: Updated Invest and Sell pages to use new, watermark-free MP4 videos.
- Files modified: `frontend/src/app/(main)/invest/page.tsx`, `frontend/src/app/(main)/sell/page.tsx`
- Key decisions: Copied the downloaded MP4 files to `frontend/public/videos/invest_hero.mp4` and `sell_hero.mp4`. Fixed catastrophic parsing errors caused by curly quotes in the Invest page testimonial array.
- Status: Complete

### 2026-03-31 — Audience Cards Video Backgrounds
- What was built: Updated AudienceCards component on the home page to use looping video backgrounds.
- Files modified: `frontend/src/components/home/AudienceCards.tsx`
- Key decisions: Extracted `video` field into the `cards` data array (Buy: `black_gold.mp4`, Sell: `sell_hero.mp4`, Invest: `invest_hero.mp4`). Replaced the `<Image>` tags with `<video>` tags for the cards.
- Status: Complete

### 2026-03-31 — Marketing Dyson Sphere
- What was built: Developed a cinematic 3D interactive WebGL dyson sphere for the "Your Home, Everywhere" sell page section.
- Files created: `frontend/src/components/sell/MarketingSphere.tsx`
- Files modified: `frontend/src/app/(main)/sell/page.tsx`
- Key decisions: Ported raw vanilla Three.js into a React `useRef` based component inside Next.js rather than using R3F to precisely save the custom global canvas texture loop logic. Dynamically draws user's provided PNG logos (`/facebook_logo.png`, etc.) onto the WebGL nodes instead of just vectors. Added rigorous React unmout disposal to prevent memory leaks.
- Status: Complete
Completed Checklist Video Integration
  - Fixed BuyerMistakes animation to slide purely upwards (y axis) instead of using rotateX, addressing user complaint about sliding sideways.
  - Updated BuyerMistakes UI: moved the top horizontal pagination strip into a vertical alignment flush to the right edge with the index number stacked underneath.
  - Mapped the 'Style beds' staging checklist item on the /sell page to the newly added video.
  - Removed video file exclusions from .gitignore and pushed all previously ignored videos/frames to the repo origin.
  - Replaced the primary logo in the Footer with the new designated SWS Primary Logo White and Gold TRANSPARENT asset.
  - Added interactive hover states to the 'Built on Trust' section on the About page that dynamically swaps the side headshot based on the active bio panel.
  - Updated text split and display for the 'REALTOR Of The Year' statistic in the About section.
  - Added 'imageClassName' visibility filters to the designation logos on the Home page (TrustSection) to match the high-contrast look from the About page.
  - Converted the static team image in the About page Team Section into an interactive 4500ms cross-fading carousel.
  - Converted the marketing node network on the Sell page (MarketingSphere) entirely to true 3D extruded SVGs.
  - Fixed MarketingSphere Instagram and Homes.com node colors, swapped generic icons, and fixed text sprite rotations to always face downwards.
  - Swapped Instagram SVG to Phosphor to fix ExtrudeGeometry solid-blob bug.

### 2026-04-28 — Cookie Consent & Dynamic Location Hero Video
- What was built: Added a global Cookie Consent banner and updated the homepage Hero component to show a custom Dracut drone video if the user's IP is located in Dracut.
- Files modified:
  - `frontend/src/app/(main)/layout.tsx`
  - `frontend/src/components/home/Hero.tsx`
- Files created:
  - `frontend/src/components/shared/CookieConsent.tsx`
- Key decisions: 
  - Utilized `geojs.io` for a silent client-side IP-based location check to avoid intrusive permission prompts.
  - Saved consent choice to `localStorage`.
  - Added additional logic for users in Andover to see `Andover_drone.mp4`.
- Status: Complete

### 2026-05-10 — Investor Strategy Toggle + Rental Analyzer
- What was built: 4-strategy toggle (Buy & Hold / STR / Flip / BRRRR) at the top of `/invest`, plus a `RentalAnalyzerModal` that estimates monthly rent (LTR) or nightly rate (STR) from condition + upgrade heuristics on top of RentCast's AVM.
- Files created:
  - `frontend/src/components/investor/StrategyToggle.tsx`
  - `frontend/src/components/investor/strategy-defaults.ts`
  - `frontend/src/components/investor/RentalAnalyzerModal.tsx`
  - `frontend/src/components/investor/parse-inputs.test.ts`
  - `frontend/src/lib/rental-analyzer-types.ts`
  - `frontend/src/lib/investor-calc.test.ts`
  - `frontend/vitest.config.ts`
  - `backend/services/rental_analyzer_service.py`
  - `backend/tests/test_rental_analyzer_service.py`
  - `backend/tests/test_estimate_rent_router.py`
- Files modified:
  - `frontend/src/lib/investor-calc.ts` (discriminated-union refactor + 4 calc functions)
  - `frontend/src/components/investor/InvestorCalculator.tsx` (strategy state, URL sync, per-strategy fields, modal mount)
  - `frontend/src/components/investor/AnalysisResults.tsx` (strategy-aware metric grids)
  - `frontend/src/app/(main)/invest/page.tsx` (Suspense wrap for useSearchParams)
  - `frontend/package.json` (Vitest devDependencies)
  - `backend/routers/investor.py` (new /estimate-rent route, strategy field on InvestorInputs)
  - `backend/services/investor_service.py` (strategy-aware AI prompt)
  - `docs/superpowers/specs/2026-05-10-investor-strategy-toggle-and-rental-analyzer-design.md` (calibration appendix)
- Key decisions:
  - Discriminated-union types so the calc engine and dispatch wrapper are exhaustively type-checked.
  - URL sync via `?strategy=` so deals are shareable; invalid params fall back to Buy & Hold.
  - Heuristic adjuster on top of RentCast: condition (-12% to +4%) + upgrades (capped at +8%) clamped to [-20%, +10%].
  - STR multipliers calibrated against AirDNA / AirROI / Rabbu data — Tourist 2.0×, Urban 1.3×, Suburban 1.2× (down from initial 3.0/2.4/1.8 which proved too aggressive).
  - Cap rate calculated WITHOUT vacancy in NOI (industry convention); cash flow subtracts vacancy.
- Tests: 31 frontend Vitest cases + 8 backend pytest cases all passing.
- Status: Complete


### 2026-05-11 — Rental Analyzer v2: Property-Type Awareness + Comp Re-Weighting
- What was built: Made the rental analyzer property-type aware. A side-by-side duplex 2bd/2ba no longer returns the same estimate as a 5+ unit apartment building 2bd/2ba at the same address. Smoke test confirms +15.4% delta on identical inputs.
- Files modified:
  - `backend/services/rental_analyzer_service.py` (heuristic v2 tables, weighted-baseline function, expanded adjuster pipeline, confidence v2 rules)
  - `backend/tests/test_rental_analyzer_service.py` (5 existing tests updated to use `condo` instead of `single_family` + 25 new tests across 4 new test classes — 33 tests total)
  - `backend/tests/test_estimate_rent_router.py` (2 router tests updated with property_type)
  - `frontend/src/lib/rental-analyzer-types.ts` (PropertyType + Amenity literal unions + PROPERTY_TYPE_OPTIONS + AMENITY_OPTIONS constants)
  - `frontend/src/components/investor/RentalAnalyzerModal.tsx` (Property Type required chip group with radiogroup a11y + Amenities multi-select group + garage/parking helper line)
- Key decisions:
  - Comp re-weighting: each RentCast comp weighted by (type_similarity × correlation). Same-type matches dominate; cross-type matches contribute less.
  - 7-value property-type taxonomy: SFH, duplex, townhouse, condo, small multi (2-4), apartment building (5+), ADU.
  - Heuristic adjusters layered on the weighted baseline: property type (+8% SFH to -8% ADU), amenities (capped at +12%), bath premium (+2.5%/extra, capped +7.5%), year built (-2% pre-1950 to +5% 2010+), sqft refinement (±1%/100sqft, capped ±6%).
  - Total adjustment clamped to ±25% (was ±10%) so combos can stack realistically.
  - Garage supersedes off-street parking when both are selected.
  - property_type is REQUIRED in the modal (breaking schema change; modal is the only caller).
  - Range-tightness denominator is RentCast's published median (not our weighted baseline) so confidence thresholds remain semantically consistent.
- Tests: 33 backend tests + 31 frontend tests, all passing.
- Status: Complete

### 2026-06-01 - Hermes Agent Control Bridge Deployment
- What was built: Added and deployed the private read-only FastAPI bridge for the Atlas/Hermes backend controller.
- Files added:
  - `backend/middleware/agent_control.py`
  - `backend/models/agent_action_audit.py`
  - `backend/schemas/agent_control.py`
  - `backend/services/agent_control_audit.py`
  - `backend/routers/agent_control.py`
  - `backend/alembic/versions/e2f4a6b8c901_add_agent_action_audits.py`
  - `backend/tests/test_agent_control_auth.py`
  - `backend/tests/test_agent_control_router.py`
  - `scripts/railway-sweeney`
  - `docs/deployment/hermes-railway.md`
  - `docs/superpowers/specs/2026-06-01-brandon-hermes-agent-foundation-design.md`
  - `docs/superpowers/plans/2026-06-01-brandon-hermes-agent-foundation.md`
- Files modified:
  - `backend/config.py`
  - `backend/main.py`
  - `backend/models/__init__.py`
  - `backend/.env.example`
  - `.gitignore`
- Key decisions:
  - Kept the backend under the same Railway project and service family so Hermes can control the Brandon backend without splitting operational context.
  - Used a dedicated Railway account/workspace token via `scripts/railway-sweeney`, leaving the existing global Railway login untouched.
  - Shipped only read-only bridge actions for the first pass: status, action catalog, recent leads, and recent bookings.
  - Protected all bridge routes with `AGENT_CONTROL_ENABLED=true` plus a bearer token, and masked lead/booking email and phone values in responses.
  - Added `agent_action_audits` so every allowed agent-control request is persisted with metadata, IP, user agent, and action id.
- Deployment:
  - Pushed `main` to GitHub and Railway deployed commit `5b8c45a`.
  - Applied the production Alembic migration through Railway: `d5e9f1a2b3c4 -> e2f4a6b8c901`.
  - Set `AGENT_CONTROL_ENABLED`, `AGENT_CONTROL_RECENT_LIMIT`, and `AGENT_CONTROL_TOKEN` on Railway without printing secret values.
  - Redeployed Railway deployment `73deb46c-433f-4824-b87d-4f7fed63a154` so the new env snapshot was active.
- Verification:
  - `backend`: `pytest tests/test_agent_control_auth.py tests/test_agent_control_router.py -v` passed with 10 tests.
  - `backend`: `pytest tests/test_link_pack_router.py -q` passed with 6 tests after merging remote main.
  - `backend`: `pytest tests/test_compliance_scanner.py tests/test_compliance_disclaimer.py -q` passed with 58 tests after merging remote main.
  - Production `/api/v1/agent-control/status` returned `status=ok` with the expected read-only capabilities when called with the token.
  - Production `/api/v1/agent-control/status` returned `401` without credentials.
  - Production `/api/v1/agent-control/actions`, `/leads/recent?limit=1`, and `/bookings/recent?limit=1` returned successfully; data-route checks were summarized by count only.
- Notes:
  - `tests/test_leads_notifications.py` still has a pre-existing expectation mismatch around background notification retry scheduling and was not caused by this bridge.
  - Railway logs still show a pre-existing Gemini blog auto-generation model error for `gemini-3-pro-preview`; this should be handled as a separate follow-up.
  - `atlas-agent` is now live as a separate Railway service in the same project. The direct GitHub-backed service creation path was rejected by the then-current account/workspace token, so the successful fallback was: create empty service, attach `/data`, set admin variables, upload the Hermes template checkout with `railway up --path-as-root`, then redeploy after adding backend bridge vars.
- Hermes service:
  - Service ID: `6dc65984-89c1-400c-9d17-d5412befd031`
  - URL: `https://atlas-agent-production-99dc.up.railway.app`
  - Volume: `atlas-agent-volume` (`594c4970-ba61-4888-8372-57d0c235db65`) mounted at `/data`
  - Template commit: `7224d7c1a4dcffe9304f49bc843f55716f5561b4`
  - Deployment: `dc2db0c4-10ca-447a-8d7a-c500dec1aa89`
  - `BRANDON_BACKEND_URL` and masked `BRANDON_AGENT_CONTROL_TOKEN` are set on the service for future backend-control skills.
- Hermes verification:
  - `scripts/railway-sweeney service status --all` shows both `extraordinary-prosperity` and `atlas-agent` as `SUCCESS`.
  - `https://atlas-agent-production-99dc.up.railway.app/health` returns `status=ok` and `gateway=stopped`.
  - Admin login POST returns `302`, sets a session cookie, and redirects to `/setup`.
  - `gateway=stopped` is expected until LLM provider and Telegram channel are configured in the Hermes dashboard.
- Status: Complete

### 2026-06-02 - Hermes Gemini Provider Setup
- What was changed: Configured the live `atlas-agent` Hermes dashboard to use Google Gemini and updated current CRM assumptions.
- Key decisions:
  - Used official Gemini API docs to confirm the stable model string for Gemini 3.5 Flash is `gemini-3.5-flash`.
  - Reused the existing local `backend/.env` Gemini API key without printing it.
  - Tested `gemini-3.5-flash` through the Gemini API before updating Hermes; the API returned HTTP 200.
  - Set Hermes persistent `/data/.hermes/.env` values through the admin API: `LLM_MODEL=gemini-3.5-flash` and masked `GEMINI_API_KEY`.
  - Started the Hermes gateway after provider setup.
  - Updated CRM assumption: Brandon is moving to eXp; do not build new KW CRM work. Current KW/Zapier references should be treated as legacy/one-way Zapier context only unless replaced by an eXp integration spec.
- Verification:
  - Hermes `/setup/api/status` reports `Gemini` configured.
  - Hermes `/health` reports `status=ok` and `gateway=running`.
  - Hermes logs warn that no messaging platforms are enabled and all unauthorized users will be denied; this is expected until Telegram/email/Workspace channels and allowlists are configured.
- Still needed:
  - Telegram bot token and Brandon's Telegram user ID/approval.
  - Google Workspace connection plan and credentials/consent for Gmail, Drive, Docs, Sheets, and Calendar beyond the existing website booking flow.
  - eXp CRM requirements or API/Zapier handoff details if CRM automation is needed later.
- Status: Complete

### 2026-06-02 - Google Workspace Account Correction
- What was changed: Recorded that Brandon-side Google Workspace setup should use `brandon@soldwithsweeney.com`.
- Key decisions:
  - Treat `brandon@soldwithsweeney.com` as the Gmail / Drive / Docs / Sheets / Calendar authorization identity for Workspace automation.
  - Keep `soldwithsweeneyfordeployment@gmail.com` scoped to Railway deployment access unless Brandon explicitly reassigns ownership.
  - Keep `rishabnandibusiness@gmail.com` separate from Brandon's Workspace authorization; it can be invited to Google Cloud IAM for implementation access, but should not become the mailbox or document owner.
- Still needed:
  - Confirm access to the Google Cloud project that owns OAuth client `721277606944-...apps.googleusercontent.com`.
  - Enable the required Workspace APIs and update OAuth consent/scopes under the correct project.
  - Have `brandon@soldwithsweeney.com` complete any OAuth consent flow for Gmail, Drive, Docs, Sheets, and expanded Calendar access.
- Status: Complete

### 2026-06-02 - Google Cloud IAM Domain Restriction
- What was changed: Documented the failed IAM grant for `rishabnandibusiness@gmail.com`.
- Findings:
  - Google Cloud rejected the IAM grant because Domain Restricted Sharing is enforced through `constraints/iam.allowedPolicyMemberDomains`.
  - The policy only allows IAM principals from approved domains or organizations, so an external `@gmail.com` account cannot be added directly.
- Recommended path:
  - Use `brandon@soldwithsweeney.com` or another allowed `@soldwithsweeney.com` Workspace user for Google Cloud access.
  - If external implementation access is required, have the Workspace/Cloud organization admin temporarily modify the Domain Restricted Sharing policy to allow `rishabnandibusiness@gmail.com`, then remove it after setup.
- Status: Complete

### 2026-06-02 - Google Cloud API Enablement
- What was changed: Switched local `gcloud` to Brandon's Workspace account and enabled the required Google APIs on the website OAuth project.
- Project:
  - Account: `brandon@soldwithsweeney.com`
  - Project ID: `sold-with-sweeney-website-v1`
  - Project number: `721277606944`
- Enabled Workspace APIs:
  - `calendar-json.googleapis.com`
  - `gmail.googleapis.com`
  - `drive.googleapis.com`
  - `docs.googleapis.com`
  - `sheets.googleapis.com`
  - `people.googleapis.com`
  - `pubsub.googleapis.com`
  - `workspaceevents.googleapis.com`
  - `driveactivity.googleapis.com`
  - `tasks.googleapis.com`
  - `admin.googleapis.com`
  - `meet.googleapis.com`
  - `chat.googleapis.com`
  - `slides.googleapis.com`
  - `forms.googleapis.com`
- Enabled Maps/site APIs:
  - `maps-backend.googleapis.com`
  - `places-backend.googleapis.com`
  - `places.googleapis.com`
  - `geocoding-backend.googleapis.com`
  - `directions-backend.googleapis.com`
  - `distance-matrix-backend.googleapis.com`
  - `routes.googleapis.com`
  - `static-maps-backend.googleapis.com`
  - `street-view-image-backend.googleapis.com`
  - `timezone-backend.googleapis.com`
  - `addressvalidation.googleapis.com`
- Verification:
  - `gcloud services list --enabled --project=sold-with-sweeney-website-v1` confirmed all targeted APIs are enabled.
- Still needed:
  - Update OAuth consent/scopes and user authorization flows for Gmail, Drive, Docs, Sheets, People, and any Hermes channel access.
  - Re-check API key restrictions for the Maps key so browser and backend usage are constrained to the intended domains/services.
- Status: Complete

### 2026-06-02 - Full Workspace OAuth Connector
- What was changed: Added a full-access Google Workspace OAuth connector for Brandon/Hermes and an admin Settings control to connect or reconnect it.
- Files changed:
  - `backend/services/workspace_service.py` - full-scope Workspace OAuth flow, token persistence helper, Google API service builder, and Gmail/Drive connection status check.
  - `backend/routers/workspace.py` - admin-protected Workspace status/auth URL routes, OAuth callback, state validation, and durable DB token persistence under `google_workspace_refresh_token`.
  - `backend/routers/booking.py` - dispatches Workspace OAuth callback states through the existing Calendar callback URI when `GOOGLE_WORKSPACE_REDIRECT_URI` is unset.
  - `backend/config.py` - added optional `GOOGLE_WORKSPACE_CLIENT_ID`, `GOOGLE_WORKSPACE_CLIENT_SECRET`, `GOOGLE_WORKSPACE_REDIRECT_URI`, and `GOOGLE_WORKSPACE_REFRESH_TOKEN`.
  - `backend/main.py` - mounted `/api/v1/workspace`.
  - `frontend/src/app/admin/settings/page.tsx` - added the primary Google Workspace connection card and updated CRM status to eXp pending access path.
  - `backend/tests/test_workspace_oauth.py` and `backend/tests/test_workspace_token_persistence.py` - added focused tests for Workspace scopes, OAuth URL generation, token exchange, and DB persistence.
- Scope decision:
  - Brandon requested broad access. The connector requests Gmail full mail access, Calendar, Drive, Docs, Sheets, Slides, Forms, Contacts/Directory, Tasks, Chat, Meet, and Admin SDK scopes.
  - The connector can reuse the already registered production Calendar callback URI by falling back to `GOOGLE_CALENDAR_REDIRECT_URI`, so a new redirect URI is optional unless `GOOGLE_WORKSPACE_REDIRECT_URI` is explicitly set.
  - Broad OAuth access does not by itself enable autonomous send/delete/edit behavior; Hermes still needs explicit backend tools and confirmation policy before it acts on Workspace data.
- Verification:
  - Backend focused tests passed: `./.venv/bin/python -m unittest tests.test_workspace_oauth tests.test_workspace_token_persistence tests.test_calendar_oauth tests.test_booking_token_persistence -v`.
  - Backend import/route smoke passed and listed `/api/v1/workspace/auth-url`, `/api/v1/workspace/callback`, and `/api/v1/workspace/status`.
  - Frontend typecheck passed: `npm run typecheck`.
  - Targeted Settings lint passed: `npx eslint src/app/admin/settings/page.tsx`.
  - Git commit `0552e4b` was pushed to `origin/main`.
  - Railway backend deployment `3c8a2ace-cd34-4c1e-8a57-9fe27df6d453` succeeded after retrying with a small temporary build context; the first retry failed because uploading the repo root exceeded Railway/Cloudflare upload size.
  - Push-triggered Railway backend deployment `fc779bef-f978-4cee-92b2-4056765e4d8b` also succeeded and is the latest live backend deployment.
  - Live `/health` returned `{"status":"ok","service":"brandon-re-api"}`.
  - Live unauthenticated `/api/v1/workspace/status` returned `403`, confirming the route is protected.
  - Live authenticated `/api/v1/workspace/status` returned `configured=True`, `connected=False`, `can_connect=True`, meaning it is ready for Brandon's OAuth consent.
  - Final live authenticated `/api/v1/workspace/auth-url` on deployment `fc779bef-f978-4cee-92b2-4056765e4d8b` returned a Google OAuth URL using the existing production callback `https://extraordinary-prosperity-production.up.railway.app/api/v1/booking/calendar/callback` and 24 requested scopes.
  - Full frontend lint still fails on pre-existing unrelated files including `.agents/skills/claude-d3js-skill/assets/interactive-template.jsx`, `src/app/admin/link-pack/page.tsx`, `src/components/buyer/MonopolyJourney.tsx`, `src/components/home/Hero.tsx`, `src/components/seller/StagingChecklist.tsx`, `src/components/shared/CookieConsent.tsx`, `src/components/shared/RotatingText.tsx`, and `src/lib/link-pack/theme-css.ts`.
- Still needed:
  - Have Brandon open Settings and click Connect Workspace while signed in as `brandon@soldwithsweeney.com`.
  - If Google blocks restricted scopes, trust the OAuth app in Workspace Admin under Security -> Access and data control -> API controls -> App access control.
  - Add Telegram bot token and Brandon's Telegram user ID to Hermes once available.
- Status: Complete

### 2026-06-02 - Workspace Consent Completed
- What changed: Verified Brandon completed the Google Workspace OAuth consent flow.
- Verification:
  - Live authenticated `/api/v1/workspace/status` returned `configured=True`, `connected=True`, `can_connect=True`.
  - Status detail reports Workspace is connected as `brandon@soldwithsweeney.com`.
- Next step:
  - Configure Hermes Telegram channel with the BotFather token and Brandon's numeric Telegram user ID.
  - After Telegram is connected, add explicit Workspace action tools for Hermes so it can use Gmail, Drive, Docs, Sheets, Calendar, and related APIs through approved backend routes.
- Status: Complete

### 2026-06-02 - Atlas Setup Completeness Check
- What was checked: Verified whether the Atlas/Hermes system is fully set up aside from the Telegram bot token.
- Live status:
  - Railway services: `extraordinary-prosperity` and `atlas-agent` both report `SUCCESS`.
  - Backend `/health` is OK.
  - Hermes `/health` reports `status=ok` and `gateway=running`.
  - Workspace OAuth is connected as `brandon@soldwithsweeney.com`.
  - Agent-control bridge is live but still read-only, with capabilities `status.read`, `leads.recent.read`, and `bookings.recent.read`.
- Conclusion:
  - The infrastructure foundation is set up.
  - The PRD-level executive assistant is not fully set up yet because Telegram channel/allowlist and Workspace action tools still need implementation/configuration.
- Status: Complete

### 2026-06-02 - Atlas Workspace Action Tools
- What was changed: Added the first protected Workspace action-tool slice behind the existing `AGENT_CONTROL_TOKEN` bridge.
- Files changed:
  - `docs/superpowers/plans/2026-06-02-atlas-workspace-action-tools.md` - implementation plan for the first Workspace action-tool slice.
  - `backend/services/workspace_service.py` - added Gmail draft/send helpers, Drive search, Google Doc creation, and Sheets append helpers.
  - `backend/schemas/agent_control.py` - added request/response models for Workspace actions.
  - `backend/routers/agent_control.py` - added audited `/api/v1/agent-control/workspace/*` routes and updated the action catalog.
  - `backend/tests/test_workspace_actions.py` - service helper tests.
  - `backend/tests/test_agent_control_workspace_actions.py` - route/audit/confirmation tests.
  - `backend/tests/test_agent_control_router.py` - updated capability/action catalog expectations.
  - `docs/deployment/hermes-railway.md` - updated bridge verification and safety boundary docs.
- New protected actions:
  - `workspace.status.read`
  - `workspace.drive.search`
  - `workspace.gmail.draft.create`
  - `workspace.docs.create`
  - `workspace.sheets.append`
  - `workspace.gmail.send`
- Safety:
  - All routes require the existing agent-control bearer token.
  - Audit rows intentionally omit Gmail body text and Sheets row values.
  - Direct Gmail send requires `confirmed_by_brandon=true`; draft creation is available without sending.
- Verification:
  - Red tests failed first for missing helpers/schemas, then passed after implementation.
  - Focused backend suite passed: `./.venv/bin/python -m unittest tests.test_workspace_actions tests.test_agent_control_workspace_actions tests.test_agent_control_router tests.test_workspace_oauth tests.test_workspace_token_persistence tests.test_agent_control_auth -v`.
  - FastAPI import/route smoke listed all six `/api/v1/agent-control/workspace/*` routes.
  - Git commit `5cc1311` was pushed to `origin/main`.
  - Railway backend deployment `9e351dd9-fa15-45da-b7e9-8f4947a8f948` reached `SUCCESS`.
  - Live authenticated `/api/v1/agent-control/status` returned `risk_tier=workspace_action_foundation`, `capability_count=9`, and all six Workspace capabilities.
  - Live authenticated `/api/v1/agent-control/actions` listed all six Workspace actions.
  - Live authenticated `/api/v1/agent-control/workspace/status` returned `connected=True`.
- Still needed:
  - Configure Telegram channel and allowlist tomorrow when token/user ID are available.
  - Add deeper Calendar, Contacts, Gmail thread read/summarize, Drive file read, and action-confirmation workflow tooling after the first slice is live.
- Status: Complete

### 2026-06-02 - Atlas Workspace Deep Action Tools
- What was changed: Expanded the protected Atlas/Hermes Workspace command surface with deeper Gmail, Drive, Calendar, and Contacts tools.
- Files changed:
  - `docs/superpowers/plans/2026-06-02-atlas-workspace-deep-action-tools.md` - implementation plan and execution checklist for this slice.
  - `backend/services/workspace_service.py` - added Gmail search/thread read helpers, Drive file text read, Calendar event list/create helpers, and Contacts search.
  - `backend/schemas/agent_control.py` - added request/response models for Gmail search/thread, Drive file read, Calendar events/create, and Contacts search.
  - `backend/routers/agent_control.py` - added audited `/api/v1/agent-control/workspace/*` routes and action catalog entries.
  - `backend/tests/test_workspace_actions.py` - service helper tests.
  - `backend/tests/test_agent_control_workspace_actions.py` - route/audit/confirmation tests.
  - `backend/tests/test_agent_control_router.py` - action catalog/status expectations.
  - `docs/deployment/hermes-railway.md` - updated safety boundary and available Workspace tools.
- New protected actions:
  - `workspace.gmail.search`
  - `workspace.gmail.thread.read`
  - `workspace.drive.file.read`
  - `workspace.calendar.events.read`
  - `workspace.calendar.event.create`
  - `workspace.contacts.search`
- Safety:
  - All new routes require the existing agent-control bearer token.
  - Gmail thread bodies, Drive file contents, contact email addresses, contact phone numbers, calendar descriptions, and attendee addresses are intentionally excluded from audit metadata.
  - Calendar event creation requires `confirmed_by_brandon=true`, matching the human-confirm policy already used for direct Gmail send.
  - Read endpoints cap page sizes to 25 and content reads to bounded character counts.
- Verification:
  - Red tests failed first for missing helpers/schemas/routes/action IDs, then passed after implementation.
  - Focused backend suite passed: `./.venv/bin/python -m unittest tests.test_workspace_actions tests.test_agent_control_workspace_actions tests.test_agent_control_router tests.test_workspace_oauth tests.test_workspace_token_persistence tests.test_agent_control_auth -v`.
  - FastAPI import/route smoke listed all 12 `/api/v1/agent-control/workspace/*` routes.
  - `git diff --check` passed.
  - Git commit `bd7a738` was pushed to `origin/main`.
  - Railway backend deployment `047f12b5-2a3c-4488-90af-f8dde7d8f080` reached `SUCCESS`.
  - Live authenticated `/api/v1/agent-control/status` returned `risk_tier=workspace_action_foundation`, `capability_count=15`, and no missing new Workspace capabilities.
  - Live authenticated `/api/v1/agent-control/actions` returned `action_count=15` and no missing new Workspace action IDs.
  - Live authenticated `/api/v1/agent-control/workspace/status` returned `connected=True`.
  - Live unconfirmed calendar event creation returned `422` with `Calendar event creation requires confirmed_by_brandon=true.`, confirming the production confirmation guard.
- Still needed:
  - Configure Telegram channel and allowlist when Brandon's BotFather token and numeric Telegram user ID are available.
  - Wire Hermes-side tool invocation prompts/config so Atlas can call these backend routes from chat.
- Status: Complete

### 2026-06-02 - Atlas Hermes MCP Bridge
- What was changed: Added a stdlib-only MCP bridge so Hermes can expose the protected backend action catalog as callable tools once a messaging channel is connected.
- Files changed:
  - `docs/superpowers/plans/2026-06-02-atlas-hermes-mcp-bridge.md` - execution plan for the Hermes-to-backend bridge.
  - `hermes/atlas_backend_mcp.py` - stdio MCP server mapping Hermes tool calls to FastAPI `agent-control` routes.
  - `hermes/README.md` - deployment overlay notes for future custom Hermes redeploys.
  - `backend/tests/test_atlas_backend_mcp.py` - MCP tool catalog, request mapping, JSON-RPC, and backend-error tests.
  - `docs/deployment/hermes-railway.md` - runbook updates for the custom Hermes image and MCP config.
- Live deployment:
  - Patched the deployed Hermes template staging copy to include `/app/atlas_backend_mcp.py`.
  - Patched the template boot config writer to add `mcp_servers.atlas_backend` when `BRANDON_BACKEND_URL` and `BRANDON_AGENT_CONTROL_TOKEN` are present.
  - Deployed `atlas-agent` with Railway deployment `8dcd567b-0c27-4eda-a7ef-46104aff91fe`, which reached `SUCCESS`.
- Verification:
  - Red tests failed first because `hermes/atlas_backend_mcp.py` did not exist.
  - Focused MCP suite passed: `./.venv/bin/python -m unittest tests.test_atlas_backend_mcp -v`.
  - Local stdio MCP smoke against production initialized successfully and called `workspace_status`, returning `configured=True` and `connected=True`.
  - Template boot config smoke with fake env produced `mcp_servers.atlas_backend` with 16 allowlisted tools and token placeholders.
  - Railway variable-name check confirmed `BRANDON_BACKEND_URL` and `BRANDON_AGENT_CONTROL_TOKEN` exist on `atlas-agent` without printing values.
  - Hermes health returned `{"status":"ok","gateway":"running"}` after deployment, and setup status showed Gemini configured with no channels yet.
- Limit:
  - Railway SSH is blocked by project role (`MEMBER` required), so direct in-container `hermes mcp list/test` could not be run.
  - Since Telegram is not configured yet, there is no live messaging session to exercise the MCP tools from chat.
- Still needed:
  - Configure Telegram bot token and Brandon's numeric Telegram allowlist when available.
  - After Telegram is connected, send an approved test prompt that calls a read-only Atlas tool, then a draft-only Workspace action.
- Status: Complete

### 2026-06-05 - Hermes Telegram Channel Connected
- What was changed: Connected Brandon's Telegram bot to the live `atlas-agent` Hermes service.
- Runtime config:
  - Railway `atlas-agent` variables now include `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_HOME_CHANNEL`, `TELEGRAM_HOME_CHANNEL_NAME`, and `GATEWAY_ALLOW_ALL_USERS=false`.
  - Hermes persistent setup config was updated through the admin API so the setup dashboard also shows Telegram configured.
  - Brandon's Telegram allowlisted user ID is `8647590834`.
  - Telegram home channel is Brandon's private DM chat ID.
- Live deployment:
  - `atlas-agent` redeployment `0636f515-da58-4b94-a6ca-bb27ef2ed8f5` reached `SUCCESS`.
- Verification:
  - Telegram Bot API `getMe` returned username `soldwithsweeney_bot`.
  - Telegram Bot API `getWebhookInfo` returned no webhook URL and no pending updates, consistent with Hermes long polling.
  - Railway variable-name check confirmed Telegram, allowlist, home-channel, and backend bridge variables are present without printing secret values.
  - Hermes `/health` returned `{"status":"ok","gateway":"running"}`.
  - Hermes native dashboard status returned `gateway_platforms.telegram.state=connected` with no error code/message.
  - Hermes setup status returned `channels.Telegram.configured=True`.
- Security note:
  - The BotFather token was pasted into chat during setup. Rotate it in BotFather after live testing, then update Railway and Hermes config with the replacement token.
- Still needed:
  - Have Brandon send a normal non-`/start` message in Telegram and verify an agent response in the chat.
  - After token rotation, repeat the Telegram runtime status check.
- Status: Complete
# Command workspace continuation (2026-08-12)

## 2026-08-12 - Recovered Command and DocuSign archive catalog

- Recovered the permitted local account archive at `Documents/Codex/2026-07-27/realtime-voice-chat/outputs/authorized-account-archive` and applied additive migration `fe2a1c4b8d75`.
- The configured internal PostgreSQL database now contains a checksum-backed catalog of all 12,580 recovered source artifacts. The Command admin includes `/admin/command/archive`, which browses the preserved private captures by source system; normalized records remain in their respective CRM modules.
- Initial normalized import is present for recovered contacts, tasks, notes, SmartPlan enrollments, timelines, listings, and a captured opportunity. Referral/network and DocuSign evidence are preserved in the catalog; do not claim that a rendered count is equivalent to 2,318 individual structured referral records.
- DocuSign normalization now includes 2 captured templates, 117 unique agreement titles/events parsed from the four recovered list pages, and 151 private file metadata entries for recovered downloads/pending forms. The raw source evidence remains cataloged for reconciliation.
- Added migration `ff7d8e1a9234` and a resumable checksum-verifying importer that stores the original artifact bytes in PostgreSQL, so recovered evidence no longer depends on this Mac's filesystem or unavailable external object storage. The protected archive UI now downloads originals through the authenticated Command API. Bulk byte persistence is actively progressing and must be reconciled to 12,580 rows before completion.
- Completed the byte reconciliation: all 12,580 artifacts are non-null in PostgreSQL, totaling 745,060,261 bytes. Three spread source-to-database checksum/length probes passed, and an authenticated API retrieval of a 956,385-byte DocuSign artifact returned HTTP 200 with its exact cataloged length and attachment disposition. Focused backend tests (25), frontend Command API tests (35), TypeScript, and frontend production build pass.
- Integrated the Command workspace into local `main` at merge commit `dc9f258`. The merged checkout re-ran the 25 focused backend tests, 35 frontend Command API tests, and production build successfully. The previous `feat/command-workspace` worktree and branch were cleaned up after the merge.
- Resolved the discovered Alembic branch split with merge revision `f0c8a6d9e431`; the configured database upgraded successfully and now has one migration head. Post-merge live-database audit confirms 12,580/12,580 artifacts have stored bytes, checksum/length probes pass, and the protected archive list/download API returned HTTP 200 with the exact expected DocuSign artifact length.
- Production release verified after PR #1 merged to `origin/main` at `2fc88cf`: Vercel serves `/admin/command/archive` with HTTP 200; Railway serves both protected archive API routes. An authenticated production DocuSign archive list returned 169 artifacts, and a source-file download returned exactly 956,385 bytes as cataloged.

- Added an authenticated bulk-contact import endpoint for permitted internal source data. It accepts up to 1,000 contacts per request, skips duplicate email addresses, and writes a `contact_imported` activity for every created record.
- Contact workspace responses now resolve and return every opportunity linked through the internal opportunity-contact relation, including the opportunity’s name, stage, value, and the contact’s role. The former empty Opportunities tab payload is removed.
- Verification: command model and private storage tests pass (4 tests). The repository-wide test run still has seven pre-existing notification retry assertion failures, unrelated to the Command workspace.

- Opportunity workspace now supports actual authenticated additions for linked contacts, vendors, and offers. Additions reload the authoritative backend workspace state and show API errors in the UI.
- Verification: frontend typecheck and focused Command API tests pass.

- Smart Plan detail workspaces now persist action steps and contact enrollments through the authenticated backend rather than merely rendering their counts.
- Verification: frontend typecheck and focused Command API tests pass after the new Smart Plan API coverage.

- Agreement workspaces now provide recipient management, lifecycle state changes, event history, and agreement-scoped private-file metadata. The schema change is additive (`fb74d2c0a611_link_files_to_agreements`) and its generated PostgreSQL SQL was verified offline.
- Verification: focused Command backend tests pass (5), frontend Command API tests pass (5), and frontend typecheck passes.

- Marketing and Websites now show actual internal content/funnel records, and Reports includes a persisted analytics event-type breakdown. These views remain linked to the existing internal content/funnel editors as the single write path.
- Verification: focused Command backend tests pass (5), frontend Command API tests pass (6), and frontend typecheck passes.

- Listings now have a server-side Google geocoding action (configured-key only) and a coordinate-derived internal map layout. Geocoding failures are explicit and do not fabricate a location.
- Verification: focused Command model/geocoding tests pass (6) and frontend typecheck passes.

- Runtime migration verification: `fb74d2c0a611` is applied to the configured internal PostgreSQL database and `crm_file_assets.agreement_id` is present. Authenticated read checks returned HTTP 200 for Command overview, reports, marketing records, website records, event breakdown, listings, and agreements.
- Final frontend verification: 40 tests pass, TypeScript passes, and the production build completes. Static generation logs the pre-existing unavailable-local-API content-block fetch but does not fail the build.

- Contact loading now requests every paginated internal CRM page (100 rows per request) before applying client-side search, preventing the previous first-50-record truncation.
- Verification: Command API tests pass (7) and frontend typecheck passes.

- Smart Plan enrollments now support persisted `active`, `paused`, and `completed` lifecycle states; the UI provides pause/resume control from the plan workspace.
- Verification: Command API tests pass (8), frontend typecheck passes, and focused Command backend tests pass (6).

- Opportunities now support persisted pipeline stage movement from the detail workspace across cultivate, appointment, active, offer, under contract, closed, and lost.
- Verification: Command API tests pass (9), frontend typecheck passes, and focused Command model tests pass (4).

- Contacts now support persisted CRM stage movement from the contact workspace, with a `stage_changed` activity added to the contact timeline.
- Verification: Command API tests pass (10) and frontend typecheck passes.

- Smart Plan steps now support persisted editing of action type and position/payload contract through the internal API; the editor exposes an edit action per step.
- Verification: Command API tests pass (11) and frontend typecheck passes.

- Command nested routes now have a responsive mobile drawer with labelled open/close controls, an overlay dismiss action, and the same navigation destinations as the desktop rail.
- Verification: frontend typecheck passes and Command API tests remain passing (11).

- Added generic persisted task links (`crm_task_links`) and `POST /tasks/{task_id}/links` so tasks can reference an internal opportunity, agreement, listing, or other entity without copying its data. Migration `fc0e8a4b9422` was validated offline and applied to the configured internal database.
- Verification: Command model tests pass (5); Alembic current is `fc0e8a4b9422 (head)`.

- Tasks workspace now exposes the task-link workflow: choose a task, choose an internal record type, and persist the target record ID through the Task Links API.
- Verification: Command API tests pass (12) and frontend typecheck passes.

- Current-branch verification sweep: all frontend tests pass (46), TypeScript passes, production build completes, and all Command backend tests pass (8). The production build retains the known non-fatal local content-block API connection warning during static public-page generation.

- Agreement detail workspaces now support private file upload directly to the selected agreement using the existing server-side object-storage path and `agreement_id` relation.
- Verification: frontend typecheck passes.

- Agreement lifecycle integrity is now enforced server-side: draft → review → ready → shared → viewed → completed, with void/expiry exits and terminal-state protection. Invalid/backward transitions return 422 and do not append an event.
- Verification: Command lifecycle/model tests pass (7).

- Agreement templates now have a persisted body-update API (`PATCH /agreement-templates/{template_id}`) for internal template editing.
- Verification: all Command backend tests pass (10).

- Agreement workspace now includes a persistent template editor: create internal templates and edit their bodies through the authenticated template API.
- Verification: Command API tests pass (13) and frontend typecheck passes.

- Task links are now retrievable and visible from Tasks: `GET /tasks/{task_id}/links` returns persisted internal links, and the task card can load/display their entity type and ID.
- Verification: Command API tests pass (13), frontend typecheck passes, and all Command backend tests pass (10).

- Tasks now support server-side status and due-date bounds (`status`, `due_before`, `due_after`) with matching open/completed and due-by controls in the Tasks workspace.
- Verification: Command API tests pass (14), frontend typecheck passes, and all Command backend tests pass (10).

- Listings now support validated persisted lifecycle states (active, pending, sold, withdrawn) through the Listings workspace and API.
- Verification: Command API tests pass (15), frontend typecheck passes, and all Command backend tests pass (10).

- Sweeney AI briefing now visibly reports backend provenance and review-required state, with explicit error handling for unavailable/generation failures. It remains review-only and does not take automatic action.
- Verification: frontend typecheck passes and Command API tests remain passing (15).

- Tasks workspace now captures and persists priority and due date/time during creation, and displays each stored due date in the task queue.
- Verification: frontend typecheck passes and Command API tests remain passing (15).

- Contact profiles now support validated persisted edits to name, email, phone, and stage. Profile edits append `contact_updated` activity while stage-only edits retain `stage_changed` activity.
- Verification: Command API tests pass (15), frontend typecheck passes, and all Command backend tests pass (10).

- Contact workspace now creates/assigns tags directly through the internal CRM APIs; repeated tag names reuse the existing tag before assigning it.
- Verification: frontend typecheck passes.

- Added an internal Referrals workspace backed by persisted `crm_referrals` records. Referrals support source, optional linked contact, and a validated lifecycle (new, contacted, nurture, converted, closed, lost); the Command navigation and API now expose creation, retrieval, and status updates.
- Verification: migration `fd1c8e9a4703` is the configured database head; 11 focused Command backend tests, 15 Command frontend API tests, TypeScript, and the optimized frontend build pass. Authenticated runtime reads for overview, contacts, referrals, reports, marketing, and websites each returned HTTP 200.

- Data verification: the internal database currently contains 51 CRM contacts and 52 CRM activities, all from the existing internal lead projection. Tasks, Smart Plans, Opportunities, Listings, Referrals, Agreements, Templates, and private file assets are correctly provisioned but currently empty. No KW Command or DocuSign archive has been imported into this database.

- Command Home now has a real current-month birthday and anniversary queue. Contact profile records can persist optional private `birthday` and `anniversary` dates; `GET /celebrations?month=1..12` returns only matching internal contacts, ordered by calendar day.
- Verification: migration `a2d7e4b9c118` is applied to the configured database; authenticated celebrations runtime read returned HTTP 200; 12 focused Command backend tests, 16 Command frontend API tests, TypeScript, and production build pass.

- Contact profile editing now includes private birthday and anniversary dates, displays stored dates as contact metadata, and renders saved-search criteria alongside the saved-search record. Both use existing authenticated persisted APIs; date validation remains server-side through the contact schema.
- Verification: Command frontend API tests pass (17) and TypeScript passes.

- Contacts now have server-side search and lifecycle-stage filtering. The API accepts bounded pagination plus `query` (name/email/phone) and `stage`; the Contacts workspace debounces searches, keeps paging through matching records, and shows explicit loading/empty states.
- Verification: 12 focused Command backend tests, 18 Command frontend API tests, and TypeScript pass. Authenticated runtime searches for both a query and stage filter returned HTTP 200.

- Listings & Map now supports server-side address search and lifecycle filtering. The map/list workspace debounces the selected filters so mapped pins and cards remain scoped to the same persisted listing result set.
- Verification: 12 focused Command backend tests, 19 Command frontend API tests, and TypeScript pass. Authenticated listing query and status-filter runtime reads returned HTTP 200.

- Tasks now support a complete persisted edit path for title, details, priority, and due date. Server-side contracts constrain task states to `open`, `in_progress`, `completed`, or `cancelled`, and priorities to `low`, `normal`, or `high`; the workspace can filter the additional states and edit existing task records.
- Verification: 13 focused Command backend tests, 20 Command frontend API tests, and TypeScript pass. An authenticated invalid task-state mutation was rejected with HTTP 422.

- Every persisted task edit now appends an immutable `task_updated` CRM activity to the linked contact timeline. The audit summary names only the fields actually changed (for example, priority and due date), without duplicating task content in activity metadata.
- Verification: 14 focused Command backend tests pass.

- Referrals can now be linked to internal contacts from the referral workspace. The chooser loads every paginated contact record (rather than assuming a small contact set), passes the contact relationship through the existing validated referral API, and displays the resolved contact on the referral card.
- Verification: 14 focused Command backend tests, 20 Command frontend API tests, and TypeScript pass.

- Contact workspaces now include a Bookings tab built from the existing authoritative `bookings` table. The server links bookings by internal lead ID when available and otherwise by case-insensitive internal contact email; it does not duplicate or mutate booking records. The frontend now uses a typed contact-workspace API boundary rather than a route-local fetch.
- Verification: 14 focused Command backend tests, 21 Command frontend API tests, and TypeScript pass. Authenticated runtime contact-workspace read returned the contact and a `bookings` array. The reproducible frontend `.next` cache was removed to reclaim local temporary-disk space for the runtime check; no source or persisted data was deleted.

- Reports now has individual report-card drilldowns. Each aggregate card opens a bounded, read-only list of its current supporting contacts, leads, open tasks, opportunities, agreements, or analytics events. The report page also uses the typed authenticated client for its summary instead of a local fetch.
- Verification: 14 focused Command backend tests, 22 Command frontend API tests, and TypeScript pass. Authenticated runtime `reports/details/contacts` returned the expected metric with a result set capped at 25 rows.

- Command Home now includes persisted internal Goals with a measurable target, current progress, and period (weekly/monthly/quarterly/annual). The API supports creation, retrieval, and authenticated progress updates; the home workspace renders actual progress rather than a fixed dashboard widget.
- Verification: migration `b7e1f2d4a906` is applied to the configured database; 15 focused Command backend tests, 23 Command frontend API tests, and TypeScript pass. Authenticated `GET /goals` returned HTTP 200.

- Goal management is now complete in Command Home: admins can set a goal name, target, and cadence, then update a goal’s actual progress directly from its progress card. All writes use the persisted authenticated goals API and refresh local UI state only after the server response.
- Verification: Command frontend API tests pass (23), TypeScript passes, and `git diff --check` is clean.

- Smart Plans now have their own validated lifecycle (`active`, `paused`, `archived`), separate from contact enrollment state. The plan editor updates the stored plan status through a dedicated authenticated API without altering its steps or enrollments.
- Verification: 15 focused Command backend tests, 24 Command frontend API tests, and TypeScript pass. An authenticated invalid Smart Plan lifecycle mutation returned HTTP 422.

- Opportunities now enforce the internal pipeline vocabulary (`cultivate`, `appointment`, `active`, `offer`, `under_contract`, `closed`, `lost`) for creation and stage moves. A real stage move appends immutable `opportunity_stage_changed` activity evidence without duplicating opportunity data.
- Verification: 16 focused Command backend tests pass. An authenticated invalid opportunity-stage mutation returned HTTP 422.

- Sweeney AI Briefing now uses the shared typed authenticated Command client for both its deterministic internal preview and explicit fresh-generation action. The existing backend contract remains aggregate-only, review-required, audit-logged for generation, and non-autonomous.
- Verification: 16 focused Command backend tests, 25 Command frontend API tests, and TypeScript pass.

- Contact workspace actions now use the shared typed Command client for notes, saved searches, tags, and tag assignments. New saved searches persist self-describing criteria (`contact_id`, `scope`, and `saved_from`) rather than an empty object, making their context auditable and displayable.
- Verification: 16 focused Command backend tests, 26 Command frontend API tests, and TypeScript pass.

- Full current-branch regression sweep: all 60 frontend tests pass, all 16 focused Command backend tests pass, configured PostgreSQL is at `b7e1f2d4a906 (head)`, and the optimized frontend production build completes with every Command route present. Static generation retains the known non-fatal local `content blocks` connection-refused warning because no public API was running for that build.

- Internal agreement creation now supports selecting an existing internal template and persists `template_id` on the agreement record. The server validates optional contact/template references before creating the agreement and its initial audit event; this remains tracking/review only, not legal e-signature execution.
- Verification: 16 focused Command backend tests, 27 Command frontend API tests, TypeScript, and `git diff --check` pass.

- Opportunity contact relationships now use a complete paginated internal-contact chooser rather than requiring raw IDs. Existing relationship rows resolve to actual internal contact names when available, while writes still use the established validated persisted relationship API.
- Verification: Command frontend API tests pass (27), TypeScript passes, and `git diff --check` is clean.

- Opportunity-contact assignments are now idempotent by contact and role. Repeating the same relationship returns its existing record instead of creating a duplicate; a different role for the same contact remains a distinct valid relationship.
- Verification: 17 focused Command backend tests and `git diff --check` pass.

- Opportunity-contact deduplication is now enforced at the PostgreSQL layer with `uq_crm_opportunity_contact_role` across opportunity, contact, and role. This protects concurrent writes in addition to the API’s idempotent behavior.
- Verification: migration `c3a8b5e1d204` is applied to the configured database; 18 focused Command backend tests pass.

- Task links now validate both the supported internal entity type and the referenced record before persistence. Only contacts, opportunities, agreements, and listings can be linked; dangling or arbitrary entity links are rejected.
- Verification: 19 focused Command backend tests pass.

- Internal contact imports now accept optional birthday and anniversary dates, preserving them in the same persisted CRM contact fields used by Command Home celebrations.
- Verification: 20 focused Command backend tests pass.

- Smart Plan enrollment now uses a complete internal contact selector, returns the enrolled contact's display name, and prevents duplicate plan/contact enrollment records at both the API and PostgreSQL layers.
- Verification: migration `e8f2c4a6b901` is applied; 21 focused Command backend tests, 28 Command API tests, and TypeScript pass.

- Task-to-record links now use internal record selectors rather than raw IDs, display the persisted record name, are idempotent, and enforce unique task/entity links at the database layer.
- Verification: migration `ab4d9e2c7108` is applied; 22 focused Command backend tests, 62 frontend tests, and TypeScript pass.

- Agreement creation now includes a complete internal contact selector and persists that relationship with the selected template and agreement metadata.
- Verification: 63 frontend tests and TypeScript pass.

- Tasks can now be created and reassigned against canonical internal contacts through selectors in the task workspace. The backend validates contact existence on create/update while preserving explicit unassignment.
- Verification: 22 focused Command backend tests, 64 frontend tests, and TypeScript pass.

- Command now includes a permitted internal contact-archive intake workflow. Admins can preview validated CSV or JSON, import in bounded 1,000-contact batches, and receive canonical created/duplicate totals. Duplicate email checks are case-insensitive.
- Verification: 22 focused Command backend tests, 65 frontend tests, and TypeScript pass.

- Contact profile updates now persist explicit clears for optional email, phone, birthday, and anniversary values. This matches the profile UI and prevents stale private data from remaining after an admin clears it.
- Verification: 23 focused Command backend tests, 65 frontend tests, and TypeScript pass.

- Referral creation and genuine lifecycle changes now append immutable activity entries to their linked contact timeline, keeping relationship history visible from the canonical contact workspace.
- Verification: 24 focused Command backend tests pass.

- Public homepage static builds now deliberately use authored fallback content when no public API endpoint is configured, preventing build workers from attempting an unavailable localhost request.
- Verification: 65 frontend tests, TypeScript, and a clean 33-route production build pass with no content-block fetch failure. Reclaimed only a stale generated `.next` cache to complete the local build.

- Saved Searches now has its own internal Command registry with canonical contact context, readable persisted criteria, and explicit deletion. This completes management beyond the contact-profile creation entrypoint.
- Verification: 25 focused Command backend tests, 66 frontend tests, and TypeScript pass.

- Contact notes, tags, and saved searches now use native inline workspace controls with loading/error states and in-place refresh instead of browser prompts or a full-page reload.
- Verification: 66 frontend tests, TypeScript, and clean 34-route production build pass.

- Contact profile editing now uses an inline, validated form with real date controls and explicit optional-field clears, replacing the remaining prompt-driven workflow.
- Verification: 66 frontend tests, TypeScript, and clean 34-route production build pass.

- Opportunity stage changes and new contact/opportunity relationships now create contact-scoped immutable timeline activity, so the contact workspace retains the full pipeline history.
- Verification: 25 focused Command backend tests pass.

- Agreement creation/status changes and Smart Plan enrollment/status changes now emit contact-scoped immutable CRM activity. Each contact timeline now carries the agreement and automation events attached to that person.
- Verification: 25 focused Command backend tests, 66 frontend tests, and TypeScript pass.

- Contact notes and tags now have complete scoped removal workflows. Removals are protected by contact ownership, refresh in place, and append immutable contact-timeline activity.
- Verification: 26 focused Command backend tests, 67 frontend tests, TypeScript, and clean 34-route production build pass.

- Archive intake now supports a structured permitted JSON bundle for contacts, tasks, notes, opportunities, referrals, listings, templates, and agreements. It reconciles email-based contact relationships, reports unresolved references, and deduplicates against canonical internal records.
- Verification: 27 focused Command backend tests, 68 frontend tests, TypeScript, and clean 34-route production build pass.

- Task editing now uses a native modal form with validation, date controls, save state, and error feedback instead of browser prompts. The Link Pack layout no longer makes production builds depend on remote Next font downloads.
- Verification: 68 frontend tests, TypeScript, and clean 34-route production build pass.

- Archive intake now provides a downloadable JSON template covering every supported record collection and email relationship key, making the source-data handoff directly actionable.
- Verification: 68 frontend tests, TypeScript, and clean 34-route production build pass.

- 2026-08-13: Task 10 Command Contacts full-parity browser acceptance is implementation-complete in the isolated `command-full-parity` worktree. The deterministic, auth-bound, fail-closed fixture models 366 contact rows and authoritative detail/workspace/evidence/mutation state without a live backend, database, or private archive. Existing Home/shell/mobile/accessibility/visual coverage remains runnable; Contacts adds exact desktop, mobile, WCAG, mutation-reconciliation, privacy, manifest, and Darwin/Linux visual contracts. Two independent reviewers approved the frozen change set with no Critical or Important findings.
- Task 10 verification: independent isolated Playwright 70/70; scoped desktop 30/30, mobile 10/10, accessibility 16/16; final scoped Vitest 321/321; TypeScript, scoped ESLint, production build, and `git diff --check` pass. Darwin and pinned Playwright 1.62.1 Linux visual suites each pass 14/14; every Contacts screenshot uses a zero-differing-pixel budget. The operator-only private source comparison is explicitly **not run** because `COMMAND_VISUAL_SOURCE_MANIFEST` was unset; no private path, name, digest, pixels, or artifact entered the worktree. On 2026-08-13 the user explicitly waived that comparison for this release and authorized the verified branch for PR, merge, and production deployment.

### 2026-08-13 — Command Contacts Production Release

- PR #3 merged to `main` at `eca0b02a8b61dee464efcf22771b0b527196a0cd`. Vercel production and Railway deployment `4cb8083f-8d86-4da8-b504-f0fc25d62a4f` both reached `SUCCESS` for that exact commit.
- Before schema changes, a mode-0600 PostgreSQL 17 custom-format logical backup was created outside the repository and its restore catalog was validated. Production Alembic advanced in reviewed checkpoints from `f0c8a6d9e431` through `5b9d1e2f3a4c`, `6c0e2f4a5b7d`, and the sole head `7d1f3a5b6c8e`; all six required tables and all five workspace-summary indexes are present.
- Live production checks passed: backend health and the required OpenAPI routes are available; the authenticated directory returned HTTP 200 with 362 contacts; detail, summary, timeline, evidence, and neighbors each returned HTTP 200; missing and wrong-scope credentials returned 401 and 403. A real production browser rendered 50 directory rows, navigated to detail, opened Notes, and observed zero page, console, or HTTP 5xx errors. No Railway error-level log entries appeared after migration.
- Scope remains explicit: the private archive Contacts reconciliation/import was **not run**. Production capture-position and section-capture counts remain zero, so this release deploys the verified application and schema without claiming the separate private-data acceptance run. The waived private screenshot comparison also remains recorded as **not run**, not passed.
