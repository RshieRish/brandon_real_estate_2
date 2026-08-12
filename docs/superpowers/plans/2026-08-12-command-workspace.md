# Command Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver `/admin/command`, a Sold With Sweeney branded, data-backed internal CRM workspace with Command-style navigation and internal agreement management.

**Architecture:** FastAPI owns all business rules and PostgreSQL persistence. Existing `leads`, `bookings`, `funnels`, `content_blocks`, and analytics remain authoritative; CRM contacts link to them. The frontend is a typed authenticated client and dark premium workspace shell, never a local-data mock.

**Tech Stack:** Next.js App Router, TypeScript, Tailwind CSS, Framer Motion, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL, Vitest, pytest.

---

## File structure

- `backend/models/command.py`: focused SQLAlchemy models for contacts, activity, tasks, plans, opportunities, listings, agreements, files, and their relationships.
- `backend/schemas/command.py`: validated request/response contracts.
- `backend/services/command_service.py`: query, mutation, summary and audit helpers.
- `backend/routers/command.py`: authenticated `/api/v1/command` REST surface.
- `backend/alembic/versions/*_add_command_workspace.py`: additive schema migration.
- `frontend/src/lib/command/{types,api}.ts`: single typed client boundary.
- `frontend/src/components/command/*`: reusable shell, tables, state panels, detail drawer, map/list, and form primitives.
- `frontend/src/app/admin/command/**/page.tsx`: route-level screens only.
- `backend/tests/test_command_*.py`, `frontend/src/**/__tests__/command-*.test.tsx`: behavior-focused coverage.

### Task 1: Establish the Command data contract

**Files:** Create `backend/tests/test_command_models.py`, `backend/models/command.py`; modify `backend/models/__init__.py`.

- [ ] Write tests that import every Command model and assert contact-to-lead is nullable, task status defaults to `open`, activity rows are immutable by convention, and agreement status is constrained to the approved lifecycle.
- [ ] Run `PYTHONPATH=. pytest tests/test_command_models.py -q` and verify RED because the module does not exist.
- [ ] Implement typed SQLAlchemy 2 models and enums: `CRMContact`, `CRMTag`, `CRMContactTag`, `CRMActivity`, `CRMNote`, `CRMTask`, `CRMTaskLink`, `CRMSmartPlan`, `CRMSmartPlanStep`, `CRMSmartPlanEnrollment`, `CRMOpportunity`, contact/vendor/offer child rows, `CRMSavedSearch`, `CRMListingRecord`, `CRMAgreementTemplate`, `CRMAgreement`, recipient/event rows, and `CRMFileAsset`.
- [ ] Re-run the focused test and commit `feat: add command workspace data models`.

### Task 2: Add an additive migration and typed API schemas

**Files:** Create `backend/alembic/versions/*_add_command_workspace.py`, `backend/schemas/command.py`, `backend/tests/test_command_schemas.py`.

- [ ] Write failing schema tests for lifecycle validation, page cursor bounds, required contact identity, and task due-date serialization.
- [ ] Implement Pydantic request/response models and an additive Alembic upgrade/downgrade that declares every Task 1 table, foreign key, index, and status check.
- [ ] Run the focused test, `alembic upgrade head` against a disposable local database when configured, and commit `feat: add command workspace migration and contracts`.

### Task 3: Implement authenticated Command APIs

**Files:** Create `backend/services/command_service.py`, `backend/routers/command.py`, `backend/tests/test_command_router.py`; modify `backend/main.py`.

- [ ] Write failing router tests using an admin dependency override for `GET /overview`, paginated contacts, contact detail tabs, task CRUD, smart-plan enrollments, opportunity CRUD, listing search/map, agreement template/agreement lifecycle transitions, and audit events.
- [ ] Implement only validated, `require_admin`-protected endpoints under `/api/v1/command`; ensure mutations append `CRMActivity`/agreement event rows and never mutate existing lead records.
- [ ] Register the router, run tests, and commit `feat: add command workspace API`.

### Task 4: Build the authenticated Command shell and typed client

**Files:** Create `frontend/src/lib/command/types.ts`, `frontend/src/lib/command/api.ts`, `frontend/src/components/command/CommandShell.tsx`, `CommandNav.tsx`, `CommandState.tsx`, `frontend/src/app/admin/command/layout.tsx`, `frontend/src/app/admin/command/page.tsx`, `frontend/src/lib/command/__tests__/api.test.ts`.

- [ ] Write failing Vitest tests proving bearer headers are attached, non-OK responses surface errors, navigation labels resolve to the intended routes, and loading/empty/error states render.
- [ ] Implement the protected responsive shell: dense left rail, top command bar, keyboard-safe mobile drawer, glass panels, gold/bronze/black palette, motion springs `{ stiffness: 100, damping: 20 }`, and no Keller Williams brand assets or wording.
- [ ] Run `npm test -- command` and `npm run typecheck`; commit `feat: add command workspace shell`.

### Task 5: Deliver Home, Contacts, and contact detail tabs

**Files:** Create `frontend/src/app/admin/command/contacts/page.tsx`, `frontend/src/app/admin/command/contacts/[contactId]/page.tsx`, `frontend/src/components/command/{Overview,ContactsTable,ContactDetailTabs,Timeline,NotesPanel}.tsx` plus focused tests.

- [ ] Write failing tests for overview metrics, contact pagination/filtering, direct contact detail routing, and Timeline/Opportunities/SmartPlans/Tasks/Notes/Saved Searches tabs.
- [ ] Implement server-backed UI with skeletons, zero states and error recovery; use linked `Lead`/`Booking` data through the Command API without duplicate writes.
- [ ] Run test/typecheck and commit `feat: add command contacts workspace`.

### Task 6: Deliver Tasks and Smart Plans

**Files:** Create route pages and components under `frontend/src/app/admin/command/{tasks,smart-plans}` and `frontend/src/components/command/{TaskBoard,TaskForm,SmartPlanList,SmartPlanEditor}.tsx` plus tests.

- [ ] Write failing tests for create/complete/reopen task flows, due-date filtering, plan step editing, enrollment, pause, and completion.
- [ ] Connect every action to Task 3 API endpoints, optimistic only after successful server responses, then run tests and commit `feat: add command tasks and smart plans`.

### Task 7: Deliver Opportunities, Listings, Search, and Map

**Files:** Create pages under `frontend/src/app/admin/command/{opportunities,listings}` and components `{OpportunityBoard,OpportunityDetail,ListingsSearch,ListingsMap}.tsx` plus tests.

- [ ] Write failing tests for stage movement persistence, offer/vendor panels, saved-search application, map/list selection synchronization, and empty map results.
- [ ] Implement the boards, detail drawers, list/search/map split view and `geocode`-backed pins; run tests/typecheck and commit `feat: add command opportunities and listings`.

### Task 8: Deliver Internal Agreements, Templates, and Files

**Files:** Create pages under `frontend/src/app/admin/command/agreements`, components `{AgreementList,AgreementDetail,TemplateEditor,FilePicker}.tsx`, backend file service/tests if object storage adapter is needed.

- [ ] Write failing tests for template creation, recipient validation, allowed lifecycle transitions, immutable event history, and file metadata persistence.
- [ ] Implement the internal-only agreement experience, clearly labeling it as tracking/sharing rather than a legal e-signature system; run tests and commit `feat: add internal agreements workspace`.

### Task 9: Deliver Marketing, Reports, Websites, and AI briefing

**Files:** Create pages under `frontend/src/app/admin/command/{marketing,reports,websites,ai}`, components `{MarketingWorkspace,ReportsDashboard,WebsiteWorkspace,AIBriefing}.tsx`, and API/service tests.

- [ ] Write failing tests that data is read from existing content/funnel/analytics sources, AI requests require admin authorization, compliance failures are returned to the UI, and generated suggestions are audit logged.
- [ ] Implement connected dashboards and server-side AI actions with explicit provenance and compliance feedback; run tests and commit `feat: add command growth and ai tools`.

### Task 10: Verify, document, and release safely

**Files:** Modify `tdtn.md`, `memory.md`; add/update `docs/command-workspace.md`.

- [ ] Run frontend unit tests, typecheck, production build, focused backend tests, migration upgrade/downgrade test, and authenticated browser smoke tests for each route.
- [ ] Record tested endpoints, seeded/real-data behavior, agreement limitation, migration identifier, and any environment prerequisites.
- [ ] Update project progress/memory, review `git diff --check`, commit `docs: verify command workspace`, and hand off the isolated branch for review.

## Self-review

All approved modules map to Tasks 3–9. Every new persistent feature has a model, schema, API, test, and UI. The only deliberate exclusion is real DocuSign integration and legally binding signature execution; agreements are internal lifecycle tracking in this release.
