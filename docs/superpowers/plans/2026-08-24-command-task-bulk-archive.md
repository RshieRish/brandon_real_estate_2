# Command Task Bulk Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 25-task pagination, individual/current-page/all-matching selection, and safe bulk archive to the authenticated Command Tasks workspace.

**Architecture:** Keep the existing all-task authoritative read and derive pages locally. Add one bounded FastAPI bulk endpoint that routes every item through the existing idempotent, versioned task lifecycle service and returns one result per task. Keep selection and reconciliation in focused frontend helpers so the large workspace component only coordinates UI state.

**Tech Stack:** FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL, Next.js 14, React, TypeScript, Vitest, Testing Library.

---

## File Structure

Create:

- `frontend/src/components/command/taskBulkSelection.ts` — pure page, selection, and uncertain-response reconciliation helpers.
- `frontend/src/components/command/taskBulkSelection.test.ts` — focused helper tests.

Modify:

- `backend/schemas/command.py` — strict bounded bulk request and discriminated response schemas.
- `backend/routers/command.py` — authenticated bulk archive route that reuses `crm_task_service.archive`.
- `backend/tests/test_command_task_api.py` — route validation, mixed outcomes, stable ordering, audit, and replay coverage.
- `frontend/src/lib/command/tasks.ts` — strict bulk request/response types, decoders, and mutation function.
- `frontend/src/lib/command/api.ts` — public Command API export.
- `frontend/src/lib/command/api.test.ts` — request serialization, response validation, and uncertain outcome tests.
- `frontend/src/components/command/TasksWorkspace.tsx` — pagination, selection toolbar, confirmation, outcomes, and focus.
- `frontend/src/components/command/TasksWorkspace.test.tsx` — accessible behavior and lifecycle reconciliation coverage.
- `tdtn.md` — completion status and verification evidence.
- `memory.md` — durable implementation decisions and rollout boundary.

### Task 1: Add the protected backend bulk archive contract

- [ ] **Step 1: Write failing schema and route tests**

Add tests that submit two active tasks and assert one `POST /api/v1/command/tasks/bulk-archive` returns results ordered by task ID, increments both versions, applies one trimmed reason, records distinct lifecycle request IDs, and exact replay adds no events. Add a mixed test with one stale version and one missing ID that expects `archived`, `conflict`, and `not_found` results without rolling back the archived item. Add validation cases for empty items, 501 items, duplicate task IDs, duplicate request IDs, overflow IDs/versions, extra fields, disabled flag, and missing/non-admin authentication.

Run:

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_command_task_api.py -k 'bulk_archive'
```

Expected: FAIL because the schema and route do not exist.

- [ ] **Step 2: Add strict Pydantic models**

Implement one item model with `task_id`, `request_id`, and `expected_version`; a 1..500 item request with optional 500-character reason and an after-validator rejecting duplicate task and request IDs; and a response item with `task_id`, `status`, optional `code`, and optional authoritative `task`.

- [ ] **Step 3: Add the route using the existing service**

Sort items by task ID. For each item call `crm_task_service.archive` with the authenticated admin actor and a `command_ui` source keyed `bulk_archive`. Map `TaskStateConflict`, `TaskNotFound`, and `TaskCommandValidationError` to per-item results. Keep unexpected exceptions as whole-request failures so the normal transaction finalizer rolls back.

- [ ] **Step 4: Run the focused backend tests**

Run the Step 1 command and require zero failures.

### Task 2: Add a strict frontend bulk archive client

- [ ] **Step 1: Write failing API tests**

Add tests that call `commandApi.bulkArchiveTasks` with two items, assert the exact URL/method/body in normalized task-ID order, decode all four result kinds, reject reordered or duplicate results, reject mismatched task IDs and invalid archived states/versions, and classify a network error, HTTP 5xx, or malformed success body as `CommandOutcomeUncertainError`.

Run:

```bash
cd frontend
npm test -- --run src/lib/command/api.test.ts
```

Expected: FAIL because `bulkArchiveTasks` is missing.

- [ ] **Step 2: Implement types, strict decoders, and mutation**

Add `TaskBulkArchiveRequest`, `TaskBulkArchiveResult`, and `TaskBulkArchiveResponse`. Validate 1..500 unique items, UUIDs, database integers, optional trimmed reason, normalize request items by task ID, require one response per requested task in that normalized order, and validate result-specific fields. Send the request through the existing `taskMutation` path so uncertain outcomes remain distinguishable.

- [ ] **Step 3: Export the client through `commandApi` and rerun tests**

Run the Step 1 command and require zero failures.

### Task 3: Add pure pagination, selection, and reconciliation helpers

- [ ] **Step 1: Write failing helper tests**

Cover a 25-row page size, page-count/page-clamp behavior, toggling one ID, selecting/clearing one page without dropping other-page IDs, selecting all matching IDs, retaining only IDs still eligible after a refresh, and classifying an uncertain bulk attempt as applied/unchanged/changed from authoritative rows.

Run:

```bash
cd frontend
npm test -- --run src/components/command/taskBulkSelection.test.ts
```

Expected: FAIL because the helper module does not exist.

- [ ] **Step 2: Implement the pure helper module**

Export `TASKS_PER_PAGE = 25`, `pageCount`, `clampPage`, `tasksForPage`, `toggleTaskSelection`, `togglePageSelection`, `selectAllMatching`, `retainEligibleSelection`, and `reconcileBulkArchiveAttempt`. Keep helpers immutable and independent of React.

- [ ] **Step 3: Rerun helper tests**

Run the Step 1 command and require zero failures.

### Task 4: Build the accessible bulk-selection workspace

- [ ] **Step 1: Write failing workspace tests**

Add tests proving:

- 26 tasks produce Page 1 of 2 with 25 rows and working Previous/Next controls.
- Individual checkbox selection persists across pages.
- The page checkbox selects and clears only the current page and exposes indeterminate state.
- Selecting a full page reveals `Select all 26 matching tasks`; activating it selects all filtered tasks.
- Filter or visibility changes clear selection and return to page 1.
- Bulk confirmation names the exact count, traps focus, accepts one optional reason, and submits one UUID/version per task.
- A mixed response clears successful IDs, retains conflicts, moves successful tasks to Archived, and announces both counts.
- An uncertain response performs one authoritative refresh, never automatically retries the write, and retains unchanged tasks for a fresh action.
- Removing the last row on the last page clamps the pager.
- Checkboxes, page controls, toolbar actions, and dialog controls have accessible names, keyboard behavior, and 44-pixel targets.

Run:

```bash
cd frontend
npm test -- --run src/components/command/TasksWorkspace.test.tsx
```

Expected: FAIL because pagination and bulk controls are absent.

- [ ] **Step 2: Implement state and data flow**

Add current page, selected-ID set, bulk candidate snapshot, shared reason, per-item failures, and bulk trigger focus state. Derive filtered tasks, clamp the current page, derive the 25-row slice, and clear selection on filter/visibility changes. Reuse `beginTaskMutation`, the authoritative refresh, and existing live-region/error patterns.

- [ ] **Step 3: Implement the task-row checkboxes, selection toolbar, pager, and modal**

Render native labelled checkboxes only for active tasks. Add page/all-matching actions, selected count, archive button, Previous/Next, and `Page X of Y`. Use the current black/gold glass treatment, Phosphor icons, `command-touch-target`, existing focus containment, and no emoji.

- [ ] **Step 4: Apply authoritative results and uncertain reconciliation**

Replace successful and conflict task rows with authoritative data, clear successful selection, retain failed selection, report exact counts, and clamp the page. On uncertainty, perform one `visibility=all` refresh and classify each submitted task without another write.

- [ ] **Step 5: Rerun workspace and combined frontend tests**

Run:

```bash
cd frontend
npm test -- --run \
  src/components/command/taskBulkSelection.test.ts \
  src/components/command/TasksWorkspace.test.tsx \
  src/lib/command/api.test.ts
```

Expected: all selected suites pass with zero failures.

### Task 5: Document and verify the completed feature

- [ ] **Step 1: Update project progress and memory**

Add one dated entry to `tdtn.md` with feature scope and fresh commands/counts. Add one concise dated entry to `memory.md` recording the 25-row selection semantics, bounded per-task lifecycle identities, mixed-result behavior, and whether deployment occurred.

- [ ] **Step 2: Run the final verification gate**

Run focused backend tests, focused frontend tests, TypeScript, scoped ESLint for changed frontend files, the production frontend build, `git diff --check`, and `git status --short`. Record the exact evidence; do not claim deployment without deployed evidence.
