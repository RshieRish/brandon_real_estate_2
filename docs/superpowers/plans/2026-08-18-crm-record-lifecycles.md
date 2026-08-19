# CRM Record Lifecycles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Command users explicit, reversible lifecycle controls for every mutable CRM record while preserving financial, communication, execution, imported-source, and compliance evidence.

**Architecture:** Extend the task-foundation `crm_record_lifecycle_events` replay contract through one serial migration and one typed service/router boundary per CRM domain. Reversible records use archive/restore, workflow records use validated domain transitions, scoped children use unlink/clear/remove rules, and immutable evidence has no mutation route. Every enabled mutation requires an authenticated actor, UUID request ID, expected version, bounded reason where required, transactional audit, and a server-acknowledged UI state.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, PostgreSQL, Alembic, Pydantic 2, Next.js 14, React, TypeScript, Vitest, Testing Library, Playwright, Railway, Vercel.

---

## Locked Migration Chain

These revisions are serial. Do not create parallel heads.

| Revision | Down revision | Responsibility |
|---|---|---|
| `86f9c7b1d4e5` | `85e8b6a0c3d4` | Contact archive/restore and contact version. |
| `870ad8c2e5f6` | `86f9c7b1d4e5` | Smart Plan, step, enrollment, and append-only step-run evidence. |
| `881be9d3f607` | `870ad8c2e5f6` | Opportunity transitions plus contact/vendor unlink/relink. |
| `892cf0e4a718` | `881be9d3f607` | Listing, offer, agreement, and referral transitions. |
| `8a3d01f5b829` | `892cf0e4a718` | Goal and agreement-template archive/restore. |
| `8b4e12a6c93a` | `8a3d01f5b829` | Scoped child removal, task-link lifecycle, contact field overrides, tags, recipients, and files. |

Every migration registers its models in `backend/models/__init__.py` and `backend/alembic/env.py`, has upgrade/downgrade tests, and leaves imported/source evidence tables untouched.

## Feature Flags

Add these booleans to `backend/config.py` and `backend/.env.example`, all defaulting to `false`:

- `CRM_CONTACT_LIFECYCLE_ENABLED`
- `CRM_SMART_PLAN_LIFECYCLE_ENABLED`
- `CRM_PIPELINE_LIFECYCLE_ENABLED`
- `CRM_DEAL_LIFECYCLE_ENABLED`
- `CRM_GOAL_TEMPLATE_LIFECYCLE_ENABLED`
- `CRM_CHILD_LIFECYCLE_ENABLED`

Reads remain backward compatible while flags are off. Each mutation router returns `404` while its flag is off so disabled capabilities are not advertised as usable.

## File Structure

Create common boundaries:

- `backend/schemas/crm_lifecycle.py` — strict UUID/version/reason request and conflict/replay response types.
- `backend/services/crm_lifecycle_service.py` — row lock, request-hash replay, optimistic version update, redacted audit, and result snapshot helper.
- `backend/scripts/verify_isolated_postgres.py` — refuses SQLite, shared databases, and non-test database names before migration tests.
- `frontend/src/lib/command/lifecycle.ts` and `lifecycle.test.ts` — typed lifecycle request/client and conflict/uncertain-write decoding.
- `frontend/src/components/command/ui/RecordLifecycleDialog.tsx` and `.test.tsx` — accessible named confirmation with reason, loading, error, conflict, and focus return.
- `frontend/src/components/command/ui/LifecycleBadge.tsx` — domain state label.

Create domain files named in Tasks 2-7. Modify:

- `backend/models/command.py`, `backend/models/command_contacts.py`, `backend/models/__init__.py`
- `backend/alembic/env.py`, `backend/config.py`, `backend/.env.example`, `backend/main.py`
- `backend/routers/command.py`, `backend/routers/command_contacts.py`
- `backend/services/command_contacts.py`, `backend/services/command_contact_contracts.py`
- `backend/services/command_contact_materializer.py`, `backend/services/command_reconciliation.py`
- `frontend/src/lib/command/api.ts`, `frontend/src/lib/command/api.test.ts`
- the exact Command pages/components listed in each domain task
- `frontend/playwright.config.ts`, `tdtn.md`, `memory.md`

## Task 1: Establish the isolated PostgreSQL and common transaction contract

**Files:**

- Create: `backend/scripts/verify_isolated_postgres.py`
- Create: `backend/schemas/crm_lifecycle.py`
- Create: `backend/services/crm_lifecycle_service.py`
- Create: `backend/tests/test_crm_lifecycle_postgres_gate.py`
- Create: `backend/tests/test_crm_lifecycle_feature_flags.py`
- Create: `backend/tests/test_crm_lifecycle_replay.py`
- Create: `backend/tests/test_crm_lifecycle_audit.py`
- Create: `backend/tests/test_crm_lifecycle_authorization.py`
- Modify: `backend/models/crm_task_lifecycle.py`
- Modify: `backend/config.py`
- Modify: `backend/.env.example`

- [ ] **Step 1: Write failing contract tests.** Require PostgreSQL, a database name ending `_test`, and a target URL different from `CRM_LIFECYCLE_PROTECTED_DATABASE_URL`. Test exact replay, changed-payload `409`, stale-version `409`, `SELECT ... FOR UPDATE` serialization, one version increment, actor capture, timezone-aware timestamps, sanitized result snapshots, and rollback when lifecycle-event persistence fails.

```python
request = LifecycleRequest(request_id=uuid4(), expected_version=3, reason="Duplicate record")
first = await lifecycle.apply(db, target=record, action="archive", request=request, actor=admin)
replay = await lifecycle.apply(db, target=record, action="archive", request=request, actor=admin)
assert replay.replayed is True
assert replay.version == first.version == 4
```

- [ ] **Step 2: Run the red suite.**

```bash
cd backend
test -n "$CRM_LIFECYCLE_TEST_DATABASE_URL"
test -n "$CRM_LIFECYCLE_PROTECTED_DATABASE_URL"
JWT_SECRET=test-secret DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" \
CRM_LIFECYCLE_TEST_DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" \
CRM_LIFECYCLE_PROTECTED_DATABASE_URL="$CRM_LIFECYCLE_PROTECTED_DATABASE_URL" \
PYTHONPATH=. /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_crm_lifecycle_postgres_gate.py tests/test_crm_lifecycle_replay.py \
  tests/test_crm_lifecycle_audit.py tests/test_crm_lifecycle_authorization.py \
  tests/test_crm_lifecycle_feature_flags.py
```

Expected: fail because the gate, schema, and service do not exist. Do not run any lifecycle migration until `verify_isolated_postgres.py` prints `ISOLATED_POSTGRES_OK`.

- [ ] **Step 3: Implement the common contract.** Use PostgreSQL UUID for `request_id`, canonical sorted JSON plus SHA-256 for `request_hash`, `SELECT ... FOR UPDATE`, an atomic expected-version predicate, the existing unique lifecycle-event identity, and a redacted `result_json`. Add all six named feature flags with `false` defaults and strict boolean parsing. Never put note bodies, email bodies, agreement bodies, file bytes/storage keys, tokens, or imported artifact previews in audit JSON.
- [ ] **Step 4: Run the green suite** with the command above; expected all pass and `ISOLATED_POSTGRES_OK`.
- [ ] **Step 5: Commit.**

```bash
git add backend/scripts/verify_isolated_postgres.py backend/schemas/crm_lifecycle.py \
  backend/services/crm_lifecycle_service.py backend/models/crm_task_lifecycle.py \
  backend/tests/test_crm_lifecycle_*.py backend/config.py backend/.env.example
git commit -m "feat: harden CRM lifecycle transactions"
```

## Task 2: Add contact Archive and Restore everywhere

**Files:**

- Create: `backend/alembic/versions/86f9c7b1d4e5_add_crm_contact_lifecycle.py`
- Create: `backend/schemas/crm_contact_lifecycle.py`
- Create: `backend/services/crm_contact_lifecycle.py`
- Create: `backend/routers/command_contact_lifecycle.py`
- Create: `backend/tests/test_crm_contact_lifecycle_migration.py`
- Create: `backend/tests/test_crm_contact_lifecycle.py`
- Create: `backend/tests/test_crm_contact_lifecycle_router.py`
- Create: `frontend/src/components/command/contacts/ContactLifecycleControls.tsx`
- Create: `frontend/src/components/command/contacts/ContactLifecycleControls.test.tsx`
- Create: `frontend/src/lib/command/lifecycle.ts`
- Create: `frontend/src/lib/command/lifecycle.test.ts`
- Create: `frontend/src/components/command/ui/RecordLifecycleDialog.tsx`
- Create: `frontend/src/components/command/ui/RecordLifecycleDialog.test.tsx`
- Create: `frontend/src/components/command/ui/LifecycleBadge.tsx`
- Modify: `backend/models/command.py`, `backend/main.py`, `backend/config.py`, `backend/.env.example`
- Modify: `backend/models/__init__.py`, `backend/alembic/env.py`
- Modify: `backend/services/command_contacts.py`, `backend/routers/command_contacts.py`, `backend/routers/command.py`
- Modify: `frontend/src/components/command/ContactsWorkspace.tsx`
- Modify: `frontend/src/components/command/contacts/ContactDetailWorkspace.tsx`

- [ ] **Step 1: Write red migration/service/router tests.** Add `version`, `archived_at`, `archived_by_type`, `archived_by_id`, and `archive_reason`; require `down_revision = "85e8b6a0c3d4"`. Test default-active directory/search/report counts, `visibility=archived|all`, archive/restore replay, stale version, preserved relationships, and imports matching an archived contact without silently restoring it.
- [ ] **Step 2: Run red tests.**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" \
CRM_LIFECYCLE_TEST_DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_crm_contact_lifecycle_migration.py tests/test_crm_contact_lifecycle.py \
  tests/test_crm_contact_lifecycle_router.py
```

Expected: missing revision and lifecycle route failures.

- [ ] **Step 3: Implement typed routes.** Add `POST /api/v1/command/contacts/{contact_id}/archive` and `/restore`; require UUID, expected version, and archive reason. Retain tasks, opportunities, notes, communications, and provenance. Add active filters to contact directory, overview, reports, and global search.
- [ ] **Step 4: Write and run frontend red tests** for the archived filter, named dialog, reason validation, conflict refetch, restore, keyboard focus return, and no native prompt/confirm.

```bash
cd frontend
npm exec vitest run -- src/components/command/contacts/ContactLifecycleControls.test.tsx \
  src/components/command/contacts/ContactsWorkspace.test.tsx \
  src/components/command/ui/RecordLifecycleDialog.test.tsx src/lib/command/lifecycle.test.ts
```

- [ ] **Step 5: Implement the UI, rerun both backend/frontend commands, and confirm `alembic heads` prints only `86f9c7b1d4e5`.**
- [ ] **Step 6: Commit.**

```bash
git add backend frontend/src/components/command/contacts frontend/src/lib/command/lifecycle.ts
git commit -m "feat: archive and restore CRM contacts"
```

## Task 3: Add Smart Plan, step, and enrollment lifecycles

**Files:**

- Create: `backend/alembic/versions/870ad8c2e5f6_add_smart_plan_lifecycle.py`
- Create: `backend/models/crm_smart_plan_execution.py`
- Create: `backend/schemas/crm_smart_plan_lifecycle.py`
- Create: `backend/services/crm_smart_plan_lifecycle.py`
- Create: `backend/routers/command_smart_plan_lifecycle.py`
- Create: `backend/tests/test_crm_smart_plan_lifecycle_migration.py`
- Create: `backend/tests/test_crm_smart_plan_lifecycle.py`
- Create: `backend/tests/test_crm_smart_plan_lifecycle_router.py`
- Create: `frontend/src/components/command/SmartPlanLifecycleControls.tsx`
- Create: `frontend/src/components/command/SmartPlanLifecycleControls.test.tsx`
- Modify: `backend/models/command.py`, `backend/models/__init__.py`, `backend/alembic/env.py`
- Modify: `backend/main.py`, `backend/routers/command.py`
- Modify: `frontend/src/app/admin/command/smart-plans/page.tsx`, `frontend/src/lib/command/lifecycle.ts`

- [ ] **Step 1: Write red tests for the exact schema.** Require `down_revision = "86f9c7b1d4e5"`; add versions to plans, steps, and enrollments. Add step state `draft|enabled|disabled`, migrating current steps to `enabled`, and add append-only `crm_smart_plan_step_runs(id, step_id, enrollment_id, execution_key, state, started_at, finished_at)` with restrictive foreign keys and unique `execution_key`.
- [ ] **Step 2: Test the transition matrix.** Plan archive/reactivate; step draft -> enabled -> disabled -> enabled; delete only a `draft` step with `NOT EXISTS crm_smart_plan_step_runs`; enrollment active -> paused -> active, active/paused -> completed, and active/paused -> cancelled. Reject resume from completed/cancelled. `record_step_run()` writes immutable evidence before any execution side effect.
- [ ] **Step 3: Run red tests.**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" \
CRM_LIFECYCLE_TEST_DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_crm_smart_plan_lifecycle_migration.py tests/test_crm_smart_plan_lifecycle.py \
  tests/test_crm_smart_plan_lifecycle_router.py
```

- [ ] **Step 4: Implement routes** `/archive`, `/reactivate`, `/steps/{id}/enable`, `/disable`, `/remove-draft`, and `/enrollments/{id}/pause|resume|complete|cancel`. Replace lifecycle writes in `backend/routers/command.py`; workspace reads exclude archived plans and disabled steps from runnable projections.
- [ ] **Step 5: Write/implement frontend controls, run the backend command plus** `npm exec vitest run -- src/components/command/SmartPlanLifecycleControls.test.tsx`, and confirm the sole head is `870ad8c2e5f6`.
- [ ] **Step 6: Commit.**

```bash
git add backend frontend/src/app/admin/command/smart-plans/page.tsx \
  frontend/src/components/command/SmartPlanLifecycleControls* frontend/src/lib/command/lifecycle.ts
git commit -m "feat: add Smart Plan lifecycle controls"
```

## Task 4: Add opportunity transitions and contact/vendor unlink/relink

**Files:**

- Create: `backend/alembic/versions/881be9d3f607_add_pipeline_lifecycle.py`
- Create: `backend/schemas/crm_pipeline_lifecycle.py`
- Create: `backend/services/crm_pipeline_lifecycle.py`
- Create: `backend/routers/command_pipeline_lifecycle.py`
- Create: `backend/tests/test_crm_pipeline_lifecycle_migration.py`
- Create: `backend/tests/test_crm_pipeline_lifecycle.py`
- Create: `backend/tests/test_crm_pipeline_lifecycle_router.py`
- Create: `frontend/src/components/command/OpportunityLifecycleControls.tsx`
- Create: `frontend/src/components/command/OpportunityLifecycleControls.test.tsx`
- Modify: `backend/models/command.py`, `backend/models/__init__.py`, `backend/alembic/env.py`
- Modify: `backend/main.py`, `backend/routers/command.py`
- Modify: `frontend/src/app/admin/command/opportunities/page.tsx`, `frontend/src/lib/command/lifecycle.ts`

- [ ] **Step 1: Write red tests.** Require `down_revision = "870ad8c2e5f6"`; add opportunity version/terminal reason and reversible unlink fields/version to `CRMOpportunityContact` and `CRMOpportunityVendor`. Test allowed nonterminal -> lost/closed, lost/closed -> selected allowed nonterminal stage with reason, invalid transitions, replay, stale version, and projection counts.
- [ ] **Step 2: Test only actual opportunity relations.** Add unlink/relink for opportunity contacts and vendors. Do not invent listing, referral, or task associations. Task links are implemented in Task 7.
- [ ] **Step 3: Run red tests.**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" \
CRM_LIFECYCLE_TEST_DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_crm_pipeline_lifecycle_migration.py tests/test_crm_pipeline_lifecycle.py \
  tests/test_crm_pipeline_lifecycle_router.py
```

- [ ] **Step 4: Implement** `/opportunities/{id}/mark-lost`, `/close`, `/reopen`, `/contacts/{relation_id}/unlink|relink`, and `/vendors/{relation_id}/unlink|relink`. Make the old stage PATCH reject terminal/reopen transitions and delegate permitted nonterminal updates through the versioned service.
- [ ] **Step 5: Implement and test domain dialogs/badges, rerun the red command plus** `npm exec vitest run -- src/components/command/OpportunityLifecycleControls.test.tsx`, and confirm the sole head is `881be9d3f607`.
- [ ] **Step 6: Commit.**

```bash
git add backend frontend/src/app/admin/command/opportunities/page.tsx \
  frontend/src/components/command/OpportunityLifecycleControls* frontend/src/lib/command/lifecycle.ts
git commit -m "feat: add opportunity lifecycle transitions"
```

## Task 5: Add listing, offer, agreement, and referral transitions

**Files:**

- Create: `backend/alembic/versions/892cf0e4a718_add_deal_record_lifecycles.py`
- Create: `backend/schemas/crm_deal_lifecycle.py`
- Create: `backend/services/crm_deal_lifecycle.py`
- Create: `backend/routers/command_deal_lifecycle.py`
- Create: `backend/tests/test_crm_deal_lifecycle_migration.py`
- Create: `backend/tests/test_crm_deal_lifecycle.py`
- Create: `backend/tests/test_crm_deal_lifecycle_router.py`
- Create: `frontend/src/components/command/DealLifecycleControls.tsx`
- Create: `frontend/src/components/command/DealLifecycleControls.test.tsx`
- Modify: `backend/models/command.py`, `backend/models/__init__.py`, `backend/alembic/env.py`
- Modify: `backend/services/command_lifecycle.py`, `backend/main.py`, `backend/routers/command.py`
- Modify: `frontend/src/app/admin/command/listings/page.tsx`
- Modify: `frontend/src/app/admin/command/opportunities/page.tsx`
- Modify: `frontend/src/app/admin/command/agreements/page.tsx`
- Modify: `frontend/src/app/admin/command/referrals/page.tsx`, `frontend/src/lib/command/lifecycle.ts`

- [ ] **Step 1: Write red migration/transition tests.** Require `down_revision = "881be9d3f607"`; add version/reason fields. Listings preserve `pre_withdraw_status` and restore only to `active|pending`; offers transition to `withdrawn`; agreements retain the current forward-only graph and expose only void/expire terminal actions; referrals close/lost and reopen to `new|contacted|nurture` with reason.
- [ ] **Step 2: Run red tests.**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" \
CRM_LIFECYCLE_TEST_DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_crm_deal_lifecycle_migration.py tests/test_crm_deal_lifecycle.py \
  tests/test_crm_deal_lifecycle_router.py tests/test_command_lifecycle.py
```

- [ ] **Step 3: Implement typed routes** for listing withdraw/restore, offer withdraw, agreement void/expire, and referral close/lost/reopen. Remove generic UI labels such as Delete; keep completed/voided/expired agreement state and financial evidence immutable.
- [ ] **Step 4: Implement frontend controls and test** with `npm exec vitest run -- src/components/command/DealLifecycleControls.test.tsx`; rerun backend tests and confirm the sole head is `892cf0e4a718`.
- [ ] **Step 5: Commit.**

```bash
git add backend frontend/src/app/admin/command/{listings,opportunities,agreements,referrals} \
  frontend/src/components/command/DealLifecycleControls* frontend/src/lib/command/lifecycle.ts
git commit -m "feat: add deal record lifecycle transitions"
```

## Task 6: Add goal and agreement-template Archive/Restore

**Files:**

- Create: `backend/alembic/versions/8a3d01f5b829_add_goal_template_lifecycle.py`
- Create: `backend/schemas/crm_goal_template_lifecycle.py`
- Create: `backend/services/crm_goal_template_lifecycle.py`
- Create: `backend/routers/command_goal_template_lifecycle.py`
- Create: `backend/tests/test_crm_goal_template_lifecycle_migration.py`
- Create: `backend/tests/test_crm_goal_template_lifecycle.py`
- Create: `backend/tests/test_crm_goal_template_lifecycle_router.py`
- Create: `frontend/src/components/command/GoalTemplateLifecycleControls.tsx`
- Create: `frontend/src/components/command/GoalTemplateLifecycleControls.test.tsx`
- Modify: `backend/models/command.py`, `backend/models/__init__.py`, `backend/alembic/env.py`
- Modify: `backend/main.py`, `backend/routers/command.py`
- Modify: `frontend/src/components/command/home/HomeGoals.tsx`
- Modify: `frontend/src/components/command/AgreementsWorkspace.tsx`, `frontend/src/lib/command/lifecycle.ts`

- [ ] **Step 1: Write red tests.** Require `down_revision = "892cf0e4a718"`; add archive fields/version to goals and agreement templates. Test default-active queries, archived views, restore, replay, stale version, goal reports, template-picker exclusion, and preservation of generated/sent agreements.
- [ ] **Step 2: Run red tests.**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" \
CRM_LIFECYCLE_TEST_DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_crm_goal_template_lifecycle_migration.py tests/test_crm_goal_template_lifecycle.py \
  tests/test_crm_goal_template_lifecycle_router.py
```

- [ ] **Step 3: Implement routes/UI**, run the backend command plus `npm exec vitest run -- src/components/command/GoalTemplateLifecycleControls.test.tsx`, and confirm the sole head is `8a3d01f5b829`.
- [ ] **Step 4: Commit.**

```bash
git add backend frontend/src/components/command/home/HomeGoals.tsx \
  frontend/src/components/command/AgreementsWorkspace.tsx \
  frontend/src/components/command/GoalTemplateLifecycleControls* frontend/src/lib/command/lifecycle.ts
git commit -m "feat: archive CRM goals and agreement templates"
```

## Task 7: Add scoped child removal, field clearing, and task-link lifecycle

**Files:**

- Create: `backend/alembic/versions/8b4e12a6c93a_add_crm_child_lifecycle.py`
- Create: `backend/models/crm_child_lifecycle.py`
- Create: `backend/schemas/crm_child_lifecycle.py`
- Create: `backend/services/crm_child_lifecycle.py`
- Create: `backend/routers/command_child_lifecycle.py`
- Create: `backend/tests/test_crm_child_lifecycle_migration.py`
- Create: `backend/tests/test_crm_child_lifecycle.py`
- Create: `backend/tests/test_crm_child_lifecycle_router.py`
- Create: `frontend/src/components/command/ChildLifecycleControls.tsx`
- Create: `frontend/src/components/command/ChildLifecycleControls.test.tsx`
- Modify: `backend/models/command.py`, `backend/models/command_contacts.py`
- Modify: `backend/models/__init__.py`, `backend/alembic/env.py`
- Modify: `backend/services/command_contact_materializer.py`, `backend/services/command_tasks.py`
- Modify: `backend/routers/command.py`, `backend/routers/command_contacts.py`, `backend/main.py`
- Modify: `frontend/src/components/command/contacts/ContactProfileEditor.tsx`
- Modify: `frontend/src/components/command/contacts/ContactNotesTab.tsx`
- Modify: `frontend/src/components/command/contacts/ContactSavedSearchesTab.tsx`
- Modify: `frontend/src/components/command/TaskEditor.tsx`
- Modify: `frontend/src/components/command/AgreementsWorkspace.tsx`, `frontend/src/lib/command/lifecycle.ts`

- [ ] **Step 1: Write red schema/ownership tests.** Require `down_revision = "8a3d01f5b829"`. Add version/removal fields to note, saved search, tag definition/assignment, task link, agreement recipient, and file asset. Add `crm_contact_field_overrides(contact_id, field_path, request_id, value_hash, cleared_at, actor_type, actor_id)` so an explicit clear survives later source reconciliation without deleting source evidence.
- [ ] **Step 2: Test exact allowed actions.** Scoped note and saved-search removal; tag unassign/reassign; tag definition archive/restore; task-link unlink/relink; address/method/profile field clear; recipient removal only while agreement status is `draft`; file supersede/withdraw while retaining private bytes. Cross-parent IDs return `404`; shared agreement recipients return `409`.
- [ ] **Step 3: Run red tests.**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" \
CRM_LIFECYCLE_TEST_DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_crm_child_lifecycle_migration.py tests/test_crm_child_lifecycle.py \
  tests/test_crm_child_lifecycle_router.py
```

- [ ] **Step 4: Implement scoped routes.** Use `/contacts/{contact_id}/notes/{id}/remove`, `/contacts/{contact_id}/saved-searches/{id}/remove`, `/contacts/{contact_id}/tags/{assignment_id}/unassign`, `/contacts/{contact_id}/fields/clear`, `/tasks/{task_id}/links/{id}/unlink|relink`, `/agreements/{id}/recipients/{recipient_id}/remove`, and `/files/{id}/supersede|withdraw`. Audit note ID, parent ID, body hash, and bounded metadata; never audit the body.
- [ ] **Step 5: Implement UI controls and test** with `npm exec vitest run -- src/components/command/ChildLifecycleControls.test.tsx`; rerun backend tests and confirm the sole head is `8b4e12a6c93a`.
- [ ] **Step 6: Commit.**

```bash
git add backend frontend/src/components/command frontend/src/lib/command/lifecycle.ts
git commit -m "feat: add scoped CRM record removal controls"
```

## Task 8: Enforce immutable evidence and reconcile every projection/writer

**Files:**

- Create: `backend/services/crm_immutable_policy.py`
- Create: `backend/tests/test_crm_immutable_records.py`
- Create: `backend/tests/test_crm_lifecycle_projection_matrix.py`
- Create: `frontend/src/components/command/ImmutableRecordCapabilities.test.tsx`
- Modify: `backend/routers/command.py`, `backend/routers/command_contacts.py`, `backend/routers/command_provenance.py`
- Modify: `backend/services/command_contacts.py`, `backend/services/command_contact_contracts.py`
- Modify: `backend/services/command_contact_materializer.py`, `backend/services/command_reconciliation.py`
- Modify: `frontend/src/lib/command/api.ts`, `frontend/src/lib/command/api.test.ts`

- [ ] **Step 1: Write the immutable route-registry test.** Assert there is no update/delete/remove capability for `CRMActivity`, communications, `CRMAgreementEvent`, executed agreement artifacts, `CRMSmartPlanStepRun`, `CRMSourceRecord`, `CRMSourceRecordArtifact`, `CRMEntitySource`, `CRMArchiveArtifact`, `CRMContactCapturePosition`, `CRMContactSectionCapture`, `CRMContactSourceOccurrence`, `CRMContactTimelineEvent`, or `CRMContactAuditEvent`.
- [ ] **Step 2: Write a projection matrix test.** Seed every lifecycle state and compare overview, reports, directory, contact detail, search, exports, template picker, Smart Plan runnable rows, and imported-record reconciliation. Source evidence remains visible under provenance but never becomes mutable archive state.
- [ ] **Step 3: Run red tests.**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" \
CRM_LIFECYCLE_TEST_DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_crm_immutable_records.py tests/test_crm_lifecycle_projection_matrix.py \
  tests/test_command_contact_imports.py tests/test_command_reconciliation.py
```

- [ ] **Step 4: Implement the immutable policy and projection filters.** Make current raw lifecycle PATCH handlers call the domain services. Make contact materialization honor `crm_contact_field_overrides`. Keep all recovered artifacts and entity-source links append-only. Search for bypasses:

```bash
rg -n 'delete\(CRM(SourceRecord|SourceRecordArtifact|EntitySource|ArchiveArtifact)|session\.delete\(|\.status\s*=|\.stage\s*=' backend --glob '*.py'
```

Expected production lifecycle assignments occur only inside the six domain lifecycle services; immutable models have no delete call.

- [ ] **Step 5: Run the green command and frontend capability test.**

```bash
cd frontend
npm exec vitest run -- src/lib/command/api.test.ts \
  src/components/command/ImmutableRecordCapabilities.test.tsx
```

- [ ] **Step 6: Commit.**

```bash
git add backend frontend/src/lib/command/api* \
  frontend/src/components/command/ImmutableRecordCapabilities.test.tsx
git commit -m "fix: reconcile CRM lifecycle projections and evidence"
```

## Task 9: Add complete browser coverage and operational verification

**Files:**

- Create: `frontend/e2e/command-lifecycles.spec.ts`
- Create: `frontend/e2e/command-lifecycles-production.spec.ts`
- Create: `frontend/playwright.crm-production.config.ts`
- Create: `backend/scripts/verify_crm_lifecycle_production.py`
- Create: `backend/tests/test_verify_crm_lifecycle_production.py`
- Create: `docs/deployment/crm-lifecycles.md`
- Modify: `frontend/playwright.config.ts`, `tdtn.md`, `memory.md`

- [ ] **Step 1: Write browser tests** for contact/task Archive/Restore, Smart Plan/step/enrollment transitions including step re-enable and enrollment complete, opportunity contact/vendor unlink/relink, listing/offer/agreement/referral transitions, goal/template Archive/Restore, scoped child actions, stale versions, uncertain-write refetch, focus return, mobile layout, and axe scans.
- [ ] **Step 2: Run local browser tests.**

```bash
cd frontend
npm exec playwright test -- --project=command-desktop --project=command-mobile \
  --project=command-a11y e2e/command-lifecycles.spec.ts
```

- [ ] **Step 3: Implement the production verifier.** It accepts explicit `--domain`, `--base-url`, and controlled canary IDs. Reversible canaries are returned to their original state. Terminal agreement/offer/referral and permanent note/saved-search canaries require `--allow-terminal-canary` and IDs for synthetic records created solely for this check; the script refuses customer records and never deletes top-level records.
- [ ] **Step 4: Test the verifier fail-closed behavior.**

```bash
cd backend
PYTHONPATH=. /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_verify_crm_lifecycle_production.py
```

- [ ] **Step 5: Run full local verification against isolated PostgreSQL.**

```bash
cd backend
PYTHONPATH=. /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/python \
  scripts/verify_isolated_postgres.py "$CRM_LIFECYCLE_TEST_DATABASE_URL"
DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/alembic upgrade 85e8b6a0c3d4
DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/alembic upgrade head
DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/alembic heads
JWT_SECRET=test-secret DATABASE_URL="$CRM_LIFECYCLE_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q
cd ../frontend
npm test
npm run typecheck
npm run lint
npm run build
git diff --check
```

Expected: `ISOLATED_POSTGRES_OK`, one head `8b4e12a6c93a`, all tests/typecheck/lint/build pass, and no diff whitespace errors.

- [ ] **Step 6: Commit verified docs and tests.** Record exact counts and commands in `tdtn.md`; record migration/immutability decisions in `memory.md`.

```bash
git add frontend/e2e frontend/playwright.config.ts frontend/playwright.crm-production.config.ts \
  backend/scripts/verify_crm_lifecycle_production.py \
  backend/tests/test_verify_crm_lifecycle_production.py docs/deployment/crm-lifecycles.md \
  tdtn.md memory.md
git commit -m "test: verify CRM record lifecycles"
```

## Controlled Deployment and Production Verification

Execute only after the full local gate passes and a production database backup/Neon restore point is recorded in `docs/deployment/crm-lifecycles.md`.

- [ ] Confirm Railway project `enchanting-perception`, backend service `extraordinary-prosperity`, intended commit SHA, and all six feature flags `false`. Abort if any target differs.
- [ ] Apply migrations with the intended checkout and Railway production environment, then deploy the same SHA:

```bash
cd backend
railway status --json
railway run --service extraordinary-prosperity alembic upgrade head
railway up --service extraordinary-prosperity --detach
```

- [ ] Verify backend health, one production Alembic head `8b4e12a6c93a`, pre/post row counts, and immutable provenance counts before enabling mutations.
- [ ] Deploy frontend through the repository's configured Vercel integration to team `soldwithsweeneyfordeployment-2547s-projects`, project `brandon-real-estate-2`, at the same SHA. Do not use the unrelated locally authenticated Vercel account.
- [ ] Enable and verify one domain at a time in this order: Contact, Smart Plan, Pipeline, Deal, Goal/Template, Child. For each domain, set only its named flag, run the verifier with explicit synthetic canary IDs, inspect the lifecycle event and visible UI, then leave the flag enabled only if API, UI, audit, projections, and rollback behavior all pass.
- [ ] For reversible domains, prove both mutation and recovery. For terminal/scoped-delete domains, use only designated synthetic canaries and the explicit `--allow-terminal-canary` gate. Never use a real client record for destructive acceptance.
- [ ] Run production Playwright after every enabled domain:

```bash
cd frontend
COMMAND_PRODUCTION_BASE_URL=https://soldwithsweeney.com \
  npm exec playwright test -- --config=playwright.crm-production.config.ts \
  e2e/command-lifecycles-production.spec.ts
```

- [ ] If any domain fails, set that domain flag back to `false`, preserve its lifecycle events for diagnosis, and do not enable the next domain.

## Rollout Gate

No lifecycle domain is complete from local code evidence alone. Completion requires one production Alembic head, backend/frontend deployments at the same intended commit, controlled domain canary evidence, correct active/archived/terminal projections, transactional audit/replay proof, immutable imported/source/archive evidence counts, and a successful disable-flag rollback rehearsal. No generic hard-delete route may exist for contacts, tasks, opportunities, listings, agreements, referrals, Smart Plans, goals, or imported evidence.
