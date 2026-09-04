# Sydney, Command Contacts, and Card Fulfillment Repair Plan

> Execute test-first in the isolated `codex/sydney-command-card-repair`
> worktree. Do not replay the failed production prompt or perform an external
> card send as a deployment test.

**Goal:** Make Sydney responsive and self-continuing, expose authoritative
Command celebrations, restore structured recovered contact data and usable
detail pages, and add an authenticated, idempotent card-campaign workflow whose
Send Out Cards adapter remains disabled until contracted API access exists.

**Architecture:** Extend the durable Sydney ledger at its existing provider and
tool boundaries; extend Command through typed FastAPI services; persist card
campaign intent/approval/receipts in additive PostgreSQL tables; keep external
sending behind a provider-neutral interface; and render all state through typed
Next.js clients.

**Baseline:** `origin/main` at `2be775408f15f21e146b33fcd5eaa2d89f36c738`,
sole migration head `85e8b7c9d4f1`. Production archive bytes exist, while
Contacts reconciliation and semantic capture tables are empty.

## Task 1: Fix nullable usage accounting

**Files:**

- Modify `backend/tests/test_sydney_memory_provider.py`
- Modify `hermes/overlay/sydney_runtime.py`
- Modify `backend/tests/test_hermes_overlay.py` only if the installer contract
  needs an annotation change
- Update `tdtn.md` and `memory.md`

**Steps:**

1. Add a failing test proving `reconcile_input_usage(agent, None)` does not
   throw, retains the preflight reservation, and does not claim an actual token
   count.
2. Add strict tests for bool, negative, numeric, and invalid-string inputs.
3. Implement the smallest safe normalization: only a real nonnegative integer
   reconciles usage; missing/invalid values no-op.
4. Run the focused Sydney runtime tests, Ruff, and diff check.
5. Record and commit the task.

## Task 2: Enforce normal Sydney business-tool policy and run budgets

**Files:**

- Modify `backend/tests/test_sydney_memory_provider.py`
- Modify `backend/tests/test_sydney_context_runs.py`
- Modify `backend/schemas/sydney_context.py`
- Modify `backend/services/sydney_context_service.py`
- Modify `hermes/overlay/sydney_runtime.py`
- Modify `hermes/overlay/sydney_memory_provider.py`
- Modify `hermes/skills/atlas-backend-operations/SKILL.md`
- Modify `hermes/overlay/manifest.json`
- Update `tdtn.md` and `memory.md`

**Steps:**

1. Add failing tests showing normal private Sydney runs reject native shell,
   filesystem, code, search-files, and process tools before execution while
   allowing `skill_view` and registered Atlas tools.
2. Add a server-authoritative aggregate invocation count to tool-start receipts
   and failing tests for a configurable per-run ceiling.
3. Add a fixed terminal policy result when the ceiling is reached; prove no
   continuation can reset it.
4. Classify `skill_view` as read-only and keep review-only recovery behavior
   byte-for-behavior compatible.
5. Strengthen the repository-owned skill: Command celebration language routes
   only to the new tool; unsupported providers stop instead of invoking native
   tools.
6. Regenerate the managed-skill hash in the manifest through the repository
   helper, then run provider/runtime/manifest tests.
7. Record and commit the task.

## Task 3: Add immediate durable acknowledgement and equivalent in-flight dedupe

**Files:**

- Modify `backend/alembic/versions/85e8b7c9d4f1_add_sydney_durable_context.py`
  only for test understanding; do not rewrite the deployed revision
- Create `backend/alembic/versions/86f9c8a0d2e1_add_sydney_request_dedupe.py`
- Modify `backend/models/sydney_context.py`
- Modify `backend/schemas/sydney_context.py`
- Modify `backend/services/sydney_context_service.py`
- Modify `backend/tests/test_sydney_context_migration.py`
- Modify `backend/tests/test_sydney_context_models.py`
- Modify `backend/tests/test_sydney_context_runs.py`
- Modify `hermes/overlay/sydney_memory_provider.py`
- Modify `hermes/overlay/sydney_runtime.py`
- Modify `hermes/overlay/sydney_gateway.py`
- Modify `hermes/overlay/install_sydney_overlay.py`
- Modify `backend/tests/test_sydney_memory_provider.py`
- Modify `backend/tests/test_sydney_context_e2e.py`
- Modify `backend/tests/test_hermes_overlay.py`
- Update `tdtn.md` and `memory.md`

**Steps:**

1. Add migration/model tests for a server-computed normalized request hash and
   active-run lookup; raw content never enters a uniqueness key or logs.
2. Add concurrency tests: two different platform messages with equivalent text
   produce one executable run and one coalesced receipt; terminal work remains
   repeatable later.
3. Add failing gateway tests for a receipt-guarded `accepted` control delivery
   before the first model call, including ambiguous/replay handling.
4. Implement server and provider contracts, then patch the pinned Hermes
   gateway at exact anchors.
5. Prove a manual session reset followed by equivalent text reuses the active
   durable run, while automatic session lineage remains under one logical
   conversation.
6. Run the Sydney PostgreSQL and exact-overlay suites, update migration-head
   assertions, record, and commit.

## Task 4: Add authoritative Command celebration preview

**Files:**

- Modify `backend/schemas/agent_control_command.py`
- Modify `backend/services/agent_control_command.py`
- Modify `backend/routers/agent_control_command.py`
- Modify `backend/tests/test_agent_control_command.py`
- Modify `backend/tests/test_agent_control_transactional_audit.py`
- Modify `hermes/atlas_backend_mcp.py`
- Modify `hermes/verify_atlas_tools.py`
- Modify `hermes/overlay/atlas_backend_bootstrap.py`
- Modify `hermes/overlay/manifest.json`
- Modify `backend/tests/test_atlas_backend_mcp.py`
- Modify `backend/tests/test_verify_atlas_tools.py`
- Modify `backend/tests/test_hermes_overlay.py`
- Update `tdtn.md` and `memory.md`

**Steps:**

1. Add strict schema tests for month, kind selection, exact per-kind/union
   counts, address readiness, masked examples, checksum/reference, and
   reconciliation status.
2. Implement one repeatable-read query path using existing Command celebration
   and address ownership services; do not infer dates or leak full addresses.
3. Add a read-only audited Agent Control route.
4. Append exactly one MCP tool while preserving order and every existing tool
   contract; update exact-count tests and live verifier expectations.
5. Run Command service/router/MCP/overlay tests, record, and commit.

## Task 5: Add card campaign persistence and provider interface

**Files:**

- Create `backend/alembic/versions/87a0d9b1e3f2_add_card_campaigns.py`
- Create `backend/models/card_campaign.py`
- Modify `backend/models/__init__.py`
- Create `backend/schemas/card_campaign.py`
- Create `backend/services/card_provider.py`
- Create `backend/services/card_campaign_service.py`
- Create `backend/tests/test_card_campaign_migration.py`
- Create `backend/tests/test_card_campaign_models.py`
- Create `backend/tests/test_card_campaign_service.py`
- Modify migration-head/workflow contract tests
- Modify `backend/.env.example`
- Update `tdtn.md` and `memory.md`

**Steps:**

1. Add failing PostgreSQL migration tests for campaign, recipient, attempt, and
   receipt invariants; preserve a single serial Alembic head.
2. Add strict lifecycle and DTO contracts.
3. Add service tests for idempotent draft creation, address exclusions,
   optimistic versioning, approval invalidation after edits, intent-before-I/O,
   ambiguous delivery, receipt immutability, and no automatic send retry.
4. Implement a provider-neutral adapter plus disabled and deterministic fake
   providers. Secrets come only from environment configuration.
5. Run PostgreSQL/TLS and unit suites, record, and commit.

## Task 6: Add authenticated card campaign API and Sydney draft tool

**Files:**

- Create `backend/routers/command_cards.py`
- Create `backend/routers/agent_control_cards.py`
- Modify `backend/main.py`
- Modify `backend/routers/agent_control.py`
- Create `backend/schemas/agent_control_cards.py`
- Create `backend/services/agent_control_cards.py`
- Create `backend/tests/test_command_cards_router.py`
- Create `backend/tests/test_agent_control_cards.py`
- Modify `backend/tests/test_agent_control_router.py`
- Modify `hermes/atlas_backend_mcp.py`
- Modify `hermes/verify_atlas_tools.py`
- Modify overlay/MCP exact registry tests and manifest
- Update `tdtn.md` and `memory.md`

**Steps:**

1. Test authenticated list/detail/create/update/approve-and-send routes,
   authorization, request UUID/version correlation, and response bounds.
2. Test one agent tool that creates or retrieves an internal draft and returns
   an absolute authenticated Command review URL. Expose no agent approve/send
   tool.
3. Implement routes/services and append the draft tool to the MCP registry.
4. Prove missing provider configuration returns connection-required state and
   performs zero external I/O.
5. Run API/MCP/audit tests, record, and commit.

## Task 7: Build the Command card review UI

**Files:**

- Create `frontend/src/lib/command/cards.ts`
- Create `frontend/src/lib/command/cards.test.ts`
- Create `frontend/src/app/admin/command/cards/page.tsx`
- Create `frontend/src/app/admin/command/cards/[campaignId]/page.tsx`
- Create `frontend/src/components/command/cards/CardCampaignsWorkspace.tsx`
- Create `frontend/src/components/command/cards/CardCampaignReview.tsx`
- Create focused component tests
- Modify `frontend/src/components/command/shell/commandNavigation.ts`
- Modify navigation tests
- Modify `frontend/src/app/admin/command/command-shell.css`
- Update `tdtn.md` and `memory.md`

**Steps:**

1. Add strict client decoders and transport tests before UI code.
2. Add component tests for loading, unavailable, needs-connection,
   missing-address, ready, confirmation, sending, partial, sent, ambiguous, and
   conflict states.
3. Build the premium asymmetric campaign list/review surfaces with Phosphor
   icons, 44px targets, focus management, and reduced motion.
4. Require a deliberate confirmation dialog containing recipient count and
   cost before approve-and-send.
5. Run Vitest, TypeScript, scoped ESLint, and build; record and commit.

## Task 8: Repair contact timeline and detail presentation

**Files:**

- Modify `backend/services/command_contact_timeline.py`
- Modify `backend/tests/test_command_contact_timeline.py`
- Modify `frontend/src/lib/command/contacts.ts`
- Modify `frontend/src/lib/command/contacts.test.ts`
- Modify `frontend/src/components/command/contacts/ContactTimelineTab.tsx`
- Modify `frontend/src/components/command/contacts/ContactSectionSurface.tsx`
- Modify `frontend/src/components/command/contacts/ContactDetailTabs.tsx`
- Modify `frontend/src/components/command/contacts/ContactDetailWorkspace.tsx`
- Modify focused component tests
- Modify `frontend/src/app/admin/command/command-shell.css`
- Modify `frontend/e2e/fixtures/command-contacts.ts`
- Modify contact Playwright/accessibility/visual tests and snapshots only after
  reviewed rendering
- Update `tdtn.md` and `memory.md`

**Steps:**

1. Add a backend regression proving technical archive activities never appear
   in the normal timeline while canonical recovered and real internal events do.
2. Add frontend regressions for bounded long-title display and explicit
   recovery states/count indicators.
3. Implement timeline filtering, status summaries, sticky/scrollable tabs,
   fixed-header clearance, responsive containment, and long-value expansion.
4. Reproduce the supplied broken shape in a fixture and prove desktop/mobile
   containment plus accessibility.
5. Inspect new screenshots at exact visual dimensions before accepting them.
6. Run all focused UI/service gates, record, and commit.

## Task 9: Full development verification and documentation

**Files:**

- Modify CI workflows only where exact migration/tool/test lists require it
- Modify `docs/deployment/hermes-railway.md`
- Modify `docs/command-reconciliation-runbook.md` only for new head/verification
  commands
- Modify `backend/.env.example`
- Modify `tdtn.md` and `memory.md`

**Steps:**

1. Run all affected backend tests against real PostgreSQL/TLS and the complete
   Sydney/Command suites.
2. Run exact pinned Hermes overlay installation twice and prove byte stability.
3. Run the full frontend suite, TypeScript, scoped lint, production build,
   Playwright desktop/mobile/accessibility/visual gates, Ruff, compileall, and
   diff/credential checks.
4. Record unrelated pre-existing red baselines separately; never call them
   green.
5. Review the whole branch diff for PII, secrets, unintended external send
   capability, and migration safety; commit final development evidence.

## Task 10: PR, deployment, and guarded production data repair

1. Push the reviewed branch, open one PR, wait for required checks, merge the
   exact reviewed head to `main`, and verify the merge SHA.
2. Verify Vercel, backend, worker, and Atlas deployments correspond to that
   merge. Card sending stays disabled.
3. Verify health/auth boundaries and live JSON-RPC tool schemas.
4. Take and validate a protected database backup.
5. Run archive verify-only, create/review the access-controlled overlap
   manifest outside the repository, and run the manifest-aware Contacts dry
   run. Stop if any accepted metric differs.
6. Apply only Contacts with the accepted fingerprint, then rerun verify-only
   and a second idempotency check.
7. Verify production directory/detail/section/evidence/timeline/celebration
   endpoints and browser surfaces. Confirm no technical archive dump renders.
8. Run a benign controlled Sydney prompt proving prompt acknowledgement,
   Command celebration routing, bounded tools, durable completion, and no
   reset/external send.
9. Leave Send Out Cards connection explicitly pending until contracted API
   credentials/documentation are supplied. When supplied, require a separate
   controlled-send approval and provider receipt verification.

## Stop conditions

- Any migration head split, archive fingerprint/count mismatch, overlap
  ambiguity, reconciliation metric mismatch, unprotected provider secret,
  browser-scraping proposal, missing provider contract, unexpected external
  I/O, or uncertain prior delivery stops the corresponding rollout step.
- A Send Out Cards credential/contract blocker does not block deploying the
  disabled campaign workflow or completing Sydney/Command/UI repairs.
