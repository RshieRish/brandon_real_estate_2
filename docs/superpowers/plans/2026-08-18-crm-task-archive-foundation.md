# CRM Task Archive Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one transactional CRM task creation path plus reversible, versioned, audited Task Archive and Restore across Command, contact summaries, reports, and the task UI.

**Architecture:** Add the first serial migration after `7d1f3a5b6c8e`, keeping archive visibility separate from workflow status. Route every task producer through `crm_task_service`, centralize task projections, and make lifecycle requests idempotent with a required UUID and optimistic version. The frontend changes state only after server acknowledgement and reconciles uncertain writes by refetching.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, PostgreSQL, Alembic, Pydantic 2, Next.js/React/TypeScript, Vitest, Testing Library, Playwright.

---

## File Structure

Create:

- `backend/alembic/versions/81a4d2c6e9f0_add_crm_task_lifecycle.py` — serial schema migration and legacy archive normalization.
- `backend/models/crm_task_lifecycle.py` — creation request, source, and immutable lifecycle event models.
- `backend/services/crm_task_projection.py` — one active/completed/cancelled/archived grouping contract.
- `backend/services/crm_task_service.py` — transactional create, update guard, archive, restore, and replay logic.
- `backend/tests/test_crm_task_lifecycle_migration.py` — migration shape and data reconciliation.
- `backend/tests/test_crm_task_service.py` — service idempotency, versioning, and transaction behavior.
- `backend/tests/test_command_task_api.py` — authenticated route contract.
- `backend/tests/test_command_task_projections.py` — overview/report/contact consistency.
- `frontend/src/components/command/TasksWorkspace.test.tsx` — task lifecycle UI contract.
- `frontend/e2e/command-tasks.spec.ts` — authenticated desktop/accessibility archive flow.

Modify:

- `backend/models/command.py`
- `backend/models/__init__.py`
- `backend/alembic/env.py`
- `backend/schemas/command.py`
- `backend/schemas/command_contacts.py`
- `backend/services/command_tasks.py`
- `backend/services/command_contacts.py`
- `backend/services/command_contact_contracts.py`
- `backend/routers/command.py`
- `backend/config.py`
- `backend/.env.example`
- focused existing backend tests listed below
- `frontend/src/lib/command/api.ts`
- `frontend/src/lib/command/api.test.ts`
- `frontend/src/lib/command/home.ts`
- `frontend/src/lib/command/home.test.ts`
- `frontend/src/lib/command/contacts.ts`
- `frontend/src/lib/command/contacts.test.ts`
- `frontend/src/components/command/TasksWorkspace.tsx`
- `frontend/src/components/command/TaskEditor.tsx`
- `frontend/src/components/command/workspaceFilters.ts`
- `frontend/src/components/command/contacts/ContactDetailWorkspace.tsx`
- `frontend/src/components/command/contacts/ContactDetailWorkspace.test.tsx`
- `frontend/src/components/command/contacts/ContactSectionSurface.tsx`
- `frontend/playwright.config.ts`
- `tdtn.md`
- `memory.md`

## Isolated PostgreSQL test prerequisite

All backend commands in this plan run against a disposable PostgreSQL database created only for this branch. Provision a fresh database (an ephemeral Neon branch/database or an isolated local PostgreSQL database), record its unique name, and export both URLs before Task 1. Never substitute the parse-only `postgresql+asyncpg://user:pass@localhost/test` value and never point these commands at development, staging, or production.

```bash
export CRM_TASK_TEST_DATABASE_NAME='brandon_crm_task_archive_<unique-suffix>'
export CRM_TASK_TEST_DATABASE_URL='postgresql+asyncpg://<test-user>:<test-password>@<isolated-host>/brandon_crm_task_archive_<unique-suffix>?ssl=require'
: "${CRM_TASK_TEST_DATABASE_NAME:?set the isolated database name}"
: "${CRM_TASK_TEST_DATABASE_URL:?set the isolated async PostgreSQL URL}"
case "$CRM_TASK_TEST_DATABASE_URL" in
  *user:pass@localhost/test*) echo 'Refusing the fake parse-only DATABASE_URL'; exit 1 ;;
esac
export CRM_TASK_TEST_SYNC_URL="${CRM_TASK_TEST_DATABASE_URL/postgresql+asyncpg:/postgresql:}"
test "$(psql "$CRM_TASK_TEST_SYNC_URL" -v ON_ERROR_STOP=1 -Atc 'select current_database()')" = "$CRM_TASK_TEST_DATABASE_NAME"
test "$(psql "$CRM_TASK_TEST_SYNC_URL" -v ON_ERROR_STOP=1 -Atc "select count(*) from pg_catalog.pg_tables where schemaname = 'public'")" = '0'
```

The last assertion is the isolation gate: start with another newly provisioned database if it is not empty. Keep these exports in the same shell for every backend and Alembic command below. Tests that exercise concurrency must use separate real connections to this database; SQLite and mocked sessions do not satisfy those tests.

## Task 1: Add the task lifecycle persistence contract

**Files:**

- Create: `backend/models/crm_task_lifecycle.py`
- Create: `backend/alembic/versions/81a4d2c6e9f0_add_crm_task_lifecycle.py`
- Create: `backend/tests/test_crm_task_lifecycle_migration.py`
- Modify: `backend/models/command.py:109`
- Modify: `backend/models/__init__.py:1`
- Modify: `backend/alembic/env.py:17`

- [ ] **Step 1: Write the failing model and migration tests**

```python
from uuid import UUID

from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID


def test_task_lifecycle_columns_are_explicit() -> None:
    columns = CRMTask.__table__.columns
    assert columns["version"].nullable is False
    assert columns["version"].default.arg == 1
    assert columns["archived_at"].nullable is True
    assert columns["archived_by_type"].type.length == 32


def test_creation_request_scope_and_key_are_unique() -> None:
    names = {constraint.name for constraint in CRMTaskCreationRequest.__table__.constraints}
    assert "uq_crm_task_creation_request_scope_key" in names
    columns = CRMTaskCreationRequest.__table__.columns
    assert columns["failure_category"].nullable is True
    assert columns["metadata_json"].nullable is False


def test_lifecycle_event_request_identity_is_unique() -> None:
    names = {constraint.name for constraint in CRMRecordLifecycleEvent.__table__.constraints}
    assert "uq_crm_record_lifecycle_event_request" in names
    request_id = CRMRecordLifecycleEvent.__table__.columns["request_id"]
    assert isinstance(request_id.type, PostgreSQLUUID)
    assert request_id.type.as_uuid is True
    assert request_id.type.python_type is UUID


def test_task_visibility_indexes_are_named_and_partial() -> None:
    assert {
        "ix_crm_tasks_active_status_due_id",
        "ix_crm_tasks_active_contact_status_id",
        "ix_crm_tasks_archived_at_id",
    }.issubset({index.name for index in CRMTask.__table__.indexes})
```

Also add an isolated-PostgreSQL migration test that upgrades from `7d1f3a5b6c8e`, verifies a legacy `status='archived'` row becomes `status='open'` with archive metadata and `version=1`, downgrades it back to `status='archived'`, then upgrades again. Assert the three table names, every named unique constraint/index below, the PostgreSQL UUID type, and a single Alembic head.

- [ ] **Step 2: Run the tests and verify the red state**

Run:

```bash
cd backend
: "${CRM_TASK_TEST_DATABASE_URL:?complete the isolated PostgreSQL prerequisite first}"
JWT_SECRET=test-secret DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_crm_task_lifecycle_migration.py
```

Expected: collection fails because `models.crm_task_lifecycle` does not exist.

- [ ] **Step 3: Add the ORM models and task fields**

```python
class CRMTaskCreationRequest(Timestamped, Base):
    __tablename__ = "crm_task_creation_requests"
    __table_args__ = (
        UniqueConstraint("scope", "idempotency_key", name="uq_crm_task_creation_request_scope_key"),
        Index("ix_crm_task_creation_requests_task_id", "task_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(128))
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(32), default="applying")
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_tasks.id", ondelete="RESTRICT"), nullable=True
    )
    result_version: Mapped[int | None] = mapped_column(Integer)


class CRMTaskSource(Base):
    __tablename__ = "crm_task_sources"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "source_key", name="uq_crm_task_source_identity"),
        Index("ix_crm_task_sources_task_id", "task_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("crm_tasks.id", ondelete="RESTRICT"))
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(255))
    source_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CRMRecordLifecycleEvent(Base):
    __tablename__ = "crm_record_lifecycle_events"
    __table_args__ = (
        UniqueConstraint(
            "entity_type", "entity_id", "action", "request_id",
            name="uq_crm_record_lifecycle_event_request",
        ),
        Index(
            "ix_crm_record_lifecycle_events_entity_created_at",
            "entity_type", "entity_id", "created_at",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64))
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(128))
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(255))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Add to `CRMTask`:

```python
archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
archived_by_type: Mapped[str | None] = mapped_column(String(32))
archived_by_id: Mapped[str | None] = mapped_column(String(128))
archive_reason: Mapped[str | None] = mapped_column(String(500))
version: Mapped[int] = mapped_column(
    Integer, default=1, server_default="1", nullable=False
)
```

Extend `CRMTask.__table_args__` without removing `ix_crm_tasks_contact_status_id`:

```python
Index(
    "ix_crm_tasks_active_status_due_id",
    "status", "due_at", "id",
    postgresql_where=text("archived_at IS NULL"),
),
Index(
    "ix_crm_tasks_active_contact_status_id",
    "contact_id", "status", "id",
    postgresql_where=text("archived_at IS NULL"),
),
Index(
    "ix_crm_tasks_archived_at_id",
    "archived_at", "id",
    postgresql_where=text("archived_at IS NOT NULL"),
),
```

`metadata_json` contains canonical, sanitized metadata only (initially `client_timezone` for creation requests and bounded lifecycle context for events). `failure_category` is nullable and may contain only a bounded machine category such as `invalid_contact`, `source_conflict`, or `persistence_failure`; never store exception text, message bodies, tokens, or raw request payloads.

- [ ] **Step 4: Add the serial Alembic migration**

Use `revision = "81a4d2c6e9f0"` and `down_revision = "7d1f3a5b6c8e"`. Import `sqlalchemy as sa` and `from sqlalchemy.dialects import postgresql`. The upgrade must add and normalize task fields first:

```python
op.add_column("crm_tasks", sa.Column("archived_at", sa.DateTime(timezone=True)))
op.add_column("crm_tasks", sa.Column("archived_by_type", sa.String(32)))
op.add_column("crm_tasks", sa.Column("archived_by_id", sa.String(128)))
op.add_column("crm_tasks", sa.Column("archive_reason", sa.String(500)))
op.add_column(
    "crm_tasks",
    sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
)
op.execute("""
    UPDATE crm_tasks
    SET archived_at = COALESCE(updated_at, created_at),
        archived_by_type = 'migration',
        archived_by_id = '81a4d2c6e9f0',
        archive_reason = 'legacy_status_migration',
        status = 'open'
    WHERE status = 'archived'
""")
```

Create the three tables with all ORM columns, timestamps, foreign keys, and exact names:

```python
op.create_table(
    "crm_task_creation_requests",
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("scope", sa.String(64), nullable=False),
    sa.Column("idempotency_key", sa.String(128), nullable=False),
    sa.Column("payload_hash", sa.String(64), nullable=False),
    sa.Column("actor_type", sa.String(32), nullable=False),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("source_type", sa.String(64), nullable=False),
    sa.Column("source_id", sa.String(255), nullable=False),
    sa.Column("state", sa.String(32), nullable=False, server_default=sa.text("'applying'")),
    sa.Column("failure_category", sa.String(64), nullable=True),
    sa.Column("metadata_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
    sa.Column("task_id", sa.Integer(), nullable=True),
    sa.Column("result_version", sa.Integer(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.ForeignKeyConstraint(["task_id"], ["crm_tasks.id"], ondelete="RESTRICT"),
    sa.UniqueConstraint("scope", "idempotency_key", name="uq_crm_task_creation_request_scope_key"),
)
op.create_table(
    "crm_task_sources",
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("task_id", sa.Integer(), nullable=False),
    sa.Column("source_type", sa.String(64), nullable=False),
    sa.Column("source_id", sa.String(255), nullable=False),
    sa.Column("source_key", sa.String(128), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.ForeignKeyConstraint(["task_id"], ["crm_tasks.id"], ondelete="RESTRICT"),
    sa.UniqueConstraint("source_type", "source_id", "source_key", name="uq_crm_task_source_identity"),
)
op.create_table(
    "crm_record_lifecycle_events",
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("entity_type", sa.String(64), nullable=False),
    sa.Column("entity_id", sa.Integer(), nullable=False),
    sa.Column("action", sa.String(64), nullable=False),
    sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("request_hash", sa.String(64), nullable=False),
    sa.Column("actor_type", sa.String(32), nullable=False),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("source_type", sa.String(64), nullable=False),
    sa.Column("source_id", sa.String(255), nullable=False),
    sa.Column("metadata_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
    sa.Column("result_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.UniqueConstraint(
        "entity_type", "entity_id", "action", "request_id",
        name="uq_crm_record_lifecycle_event_request",
    ),
)
```

Create these exact indexes after the tables/columns exist:

```python
op.create_index("ix_crm_task_creation_requests_task_id", "crm_task_creation_requests", ["task_id"])
op.create_index("ix_crm_task_sources_task_id", "crm_task_sources", ["task_id"])
op.create_index(
    "ix_crm_record_lifecycle_events_entity_created_at",
    "crm_record_lifecycle_events", ["entity_type", "entity_id", "created_at"],
)
op.create_index(
    "ix_crm_tasks_active_status_due_id", "crm_tasks", ["status", "due_at", "id"],
    postgresql_where=sa.text("archived_at IS NULL"),
)
op.create_index(
    "ix_crm_tasks_active_contact_status_id", "crm_tasks", ["contact_id", "status", "id"],
    postgresql_where=sa.text("archived_at IS NULL"),
)
op.create_index(
    "ix_crm_tasks_archived_at_id", "crm_tasks", ["archived_at", "id"],
    postgresql_where=sa.text("archived_at IS NOT NULL"),
)
```

The compare-and-swap update always filters by primary key plus `version`, so a standalone version index is intentionally unnecessary. The downgrade docstring must state that the unknowable pre-archive workflow status cannot be reconstructed. Downgrade in this order: update every `archived_at IS NOT NULL` row to `status='archived'`; drop the six explicit indexes above; drop `crm_record_lifecycle_events`, `crm_task_sources`, then `crm_task_creation_requests`; drop `version`, `archive_reason`, `archived_by_id`, `archived_by_type`, then `archived_at`. Do not drop the pre-existing `ix_crm_tasks_contact_status_id`.

- [ ] **Step 5: Register models and prove upgrade/downgrade/upgrade on PostgreSQL**

Run the command from Step 2, then exercise the migration against the still-isolated database:

```bash
cd backend
: "${CRM_TASK_TEST_DATABASE_URL:?complete the isolated PostgreSQL prerequisite first}"
DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" ../backend/.venv/bin/alembic upgrade 7d1f3a5b6c8e
psql "$CRM_TASK_TEST_SYNC_URL" -v ON_ERROR_STOP=1 -c \
  "INSERT INTO crm_tasks (title, description, status, priority) VALUES ('Legacy archived', '', 'archived', 'normal')"
DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" ../backend/.venv/bin/alembic upgrade 81a4d2c6e9f0
test "$(psql "$CRM_TASK_TEST_SYNC_URL" -v ON_ERROR_STOP=1 -Atc "SELECT count(*) FROM crm_tasks WHERE title='Legacy archived' AND status='open' AND archived_at IS NOT NULL AND archived_by_type='migration' AND archived_by_id='81a4d2c6e9f0' AND version=1")" = '1'
DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" ../backend/.venv/bin/alembic downgrade 7d1f3a5b6c8e
test "$(psql "$CRM_TASK_TEST_SYNC_URL" -v ON_ERROR_STOP=1 -Atc "SELECT count(*) FROM crm_tasks WHERE title='Legacy archived' AND status='archived'")" = '1'
DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" ../backend/.venv/bin/alembic upgrade 81a4d2c6e9f0
test "$(DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" ../backend/.venv/bin/alembic heads | sed -n 's/ .*//p')" = '81a4d2c6e9f0'
```

Expected: all focused tests pass, the legacy row survives both directions with the documented lossy downgrade status, and Alembic prints only `81a4d2c6e9f0`.

- [ ] **Step 6: Commit the persistence slice**

```bash
git add backend/models backend/alembic backend/tests/test_crm_task_lifecycle_migration.py
git commit -m "feat: add CRM task lifecycle persistence"
```

## Task 2: Centralize task projection semantics

**Files:**

- Create: `backend/services/crm_task_projection.py`
- Create: `backend/tests/test_command_task_projections.py`
- Modify: `backend/routers/command.py:148-250`
- Modify: `backend/services/command_contacts.py:1931-2056`
- Modify: `backend/services/command_contact_contracts.py:875`
- Modify: `backend/schemas/command_contacts.py:245`
- Modify: focused contact and report tests

- [ ] **Step 1: Write red tests for all workflow/archive groups**

```python
@pytest.mark.parametrize(
    ("status", "archived", "group"),
    [
        ("open", False, "active"),
        ("in_progress", False, "active"),
        ("completed", False, "completed"),
        ("cancelled", False, "cancelled"),
        ("open", True, "archived"),
        ("completed", True, "archived"),
    ],
)
def test_task_group_contract(status: str, archived: bool, group: str) -> None:
    assert task_group(status=status, archived_at=NOW if archived else None) == group
```

Add service/router tests proving archived and cancelled tasks are absent from `open_tasks`, and recovered archived occurrences are reported separately.

- [ ] **Step 2: Run the projection tests and verify failure**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_command_task_projections.py tests/test_command_contacts_service.py
```

Expected: `task_group` is missing and `in_progress` still triggers the old integrity error.

- [ ] **Step 3: Implement the projection module**

```python
TaskGroup = Literal["active", "completed", "cancelled", "archived"]


def task_group(*, status: str, archived_at: datetime | None) -> TaskGroup:
    if archived_at is not None:
        return "archived"
    if status in {"open", "in_progress"}:
        return "active"
    if status == "completed":
        return "completed"
    if status == "cancelled":
        return "cancelled"
    raise TaskProjectionError("task status is invalid")


def active_task_clause():
    return and_(CRMTask.archived_at.is_(None), CRMTask.status.in_(("open", "in_progress")))
```

Use the shared clause in overview, AI briefing, reports, due lists, task list defaults, and contact summary. Extend contact summary with `active_tasks`, `cancelled_tasks`, `archived_mutable_tasks`, and `archived_recovered_evidence`, retaining the combined `archived_tasks` field.

- [ ] **Step 4: Run backend and frontend decoder tests**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_command_task_projections.py tests/test_command_contacts_service.py tests/test_command_contacts_router.py
cd ../frontend
npm exec vitest run -- src/lib/command/home.test.ts src/lib/command/contacts.test.ts
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the projection slice**

```bash
git add backend frontend/src/lib/command
git commit -m "fix: unify CRM task projections"
```

## Task 3: Build the shared transactional task service

**Files:**

- Create: `backend/services/crm_task_service.py`
- Create: `backend/tests/test_crm_task_service.py`
- Create: `backend/tests/test_command_task_api.py`
- Modify: `backend/services/command_tasks.py`
- Modify: `backend/routers/command.py:326,558`

- [ ] **Step 1: Write red service and Command API tests**

In `test_crm_task_service.py`, cover exact replay, key/payload mismatch, invalid contact, contactless task without contact activity, source linkage, client timezone metadata, concurrent uniqueness using two independent PostgreSQL sessions, and rollback when source/activity/lifecycle persistence fails. In `test_command_task_api.py`, prove `POST /tasks` requires an authenticated administrator and a valid `X-Idempotency-Key`, exact replay returns the original task, the same key with different JSON returns structured 409, and the real `get_db` finalizer commits all rows together or rolls all of them back.

```python
command = CreateTaskCommand(
    title="Call Jane",
    description="Discuss listing",
    priority="normal",
    due_at=NOW,
    contact_id=contact.id,
    actor=TaskActor(type="admin", id="admin-1"),
    source=TaskSource(type="command_ui", id="request-1", key="primary"),
    idempotency_scope="command_ui",
    idempotency_key="request-1",
    client_timezone="America/New_York",
)
first = await service.create(db, command)
second = await service.create(db, command)
assert second.task.id == first.task.id
assert second.replayed is True
```

- [ ] **Step 2: Run and verify failure**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_crm_task_service.py tests/test_command_task_api.py
```

Expected: import fails for `services.crm_task_service`.

- [ ] **Step 3: Implement typed commands and canonical hashing**

```python
@dataclass(frozen=True, slots=True)
class TaskActor:
    type: Literal["admin", "sydney", "system"]
    id: str


@dataclass(frozen=True, slots=True)
class TaskSource:
    type: Literal["command_ui", "archive_import", "gmail_message", "sydney_chat"]
    id: str
    key: str


@dataclass(frozen=True, slots=True)
class CreateTaskCommand:
    title: str
    description: str
    priority: Literal["low", "normal", "high"]
    due_at: datetime | None
    contact_id: int | None
    actor: TaskActor
    source: TaskSource
    idempotency_scope: str
    idempotency_key: str
    client_timezone: str
```

Canonicalize a JSON object with sorted keys, compact separators, UTC ISO datetimes, and hash it with SHA-256. Use PostgreSQL `INSERT .. ON CONFLICT DO NOTHING RETURNING` inside one service savepoint; do not catch a uniqueness error after a plain `flush()`, because that would leave the transaction unusable:

```python
async with db.begin_nested():
    claim_id = await db.scalar(
        pg_insert(CRMTaskCreationRequest)
        .values(
            scope=command.idempotency_scope,
            idempotency_key=command.idempotency_key,
            payload_hash=payload_hash,
            actor_type=command.actor.type,
            actor_id=command.actor.id,
            source_type=command.source.type,
            source_id=command.source.id,
            state="applying",
            metadata_json=canonical_json({"client_timezone": command.client_timezone}),
        )
        .on_conflict_do_nothing(
            constraint="uq_crm_task_creation_request_scope_key"
        )
        .returning(CRMTaskCreationRequest.id)
    )
    if claim_id is None:
        claim = await db.scalar(
            select(CRMTaskCreationRequest)
            .where(
                CRMTaskCreationRequest.scope == command.idempotency_scope,
                CRMTaskCreationRequest.idempotency_key == command.idempotency_key,
            )
            .with_for_update()
        )
        if claim is None or claim.payload_hash != payload_hash:
            raise TaskIdempotencyConflict()
        if claim.state != "applied" or claim.task_id is None:
            raise TaskCreationStateError()
        return CreateTaskResult(task=await require_task(db, claim.task_id), replayed=True)

    claim = await db.get(CRMTaskCreationRequest, claim_id)
    task = CRMTask(...)
    db.add(task)
    await db.flush()
    db.add(CRMTaskSource(task_id=task.id, ...))
    if task.contact_id is not None:
        db.add(CRMActivity(contact_id=task.contact_id, kind="task_created", ...))
    db.add(CRMRecordLifecycleEvent(entity_type="task", entity_id=task.id, action="create", ...))
    claim.state = "applied"
    claim.task_id = task.id
    claim.result_version = task.version
    await db.flush()
```

PostgreSQL waits on the unique index before the losing `ON CONFLICT` returns, so the loser can lock and read the committed winner without an `IntegrityError`. The savepoint contains the claim, task, source, optional contact activity, and lifecycle event; any failure rolls all five back. The service never calls `commit()` or `rollback()`—`get_db` owns the outer request transaction. A `uq_crm_task_source_identity` violation must escape the savepoint and roll back the new task rather than returning a partially linked task.

- [ ] **Step 4: Cut Command POST and archive import over to the service**

Command POST derives its idempotency key from required `X-Idempotency-Key`; archive import derives a deterministic key from archive source identity and row ordinal. Remove title/contact deduplication so distinct source messages with equal titles remain distinct.

- [ ] **Step 5: Run service/API/import tests and search for direct writes**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_crm_task_service.py tests/test_command_task_api.py tests/test_command_contact_email_writes.py
rg -n 'CRMTask\(' . --glob '*.py'
```

Expected: tests pass; production direct constructors remain only inside `crm_task_service.py`.

- [ ] **Step 6: Commit the service slice**

```bash
git add backend
git commit -m "feat: centralize CRM task creation"
```

## Task 4: Add versioned Archive and Restore APIs

**Files:**

- Modify: `backend/schemas/command.py:35-65`
- Modify: `backend/routers/command.py:549-606`
- Modify: `backend/services/crm_task_service.py`
- Modify: `backend/config.py`
- Modify: `backend/.env.example`
- Modify: `backend/tests/test_command_task_api.py`

- [ ] **Step 1: Write red route tests**

Test admin authentication, disabled flag, strict request body, exact replay, mismatched replay, stale version, same-state no-op, preserved status/links, and rejection of PATCH/link against archived tasks. Also prove every successful PATCH requires `expected_version` and increments `version` exactly once (including a write that repeats the stored value), and every newly persisted task link requires `expected_version` and increments the parent task version exactly once. A duplicate link is a non-mutation and returns the existing link/current task version without increment; stale `expected_version` still returns 409 before that replay check.

```python
payload = {"request_id": str(uuid4()), "expected_version": 1, "reason": "No longer needed"}
response = await client.post(f"/api/v1/command/tasks/{task.id}/archive", json=payload, headers=admin_headers)
assert response.status_code == 200
assert response.json()["archived_at"] is not None
assert response.json()["status"] == "in_progress"
assert response.json()["version"] == 2
```

- [ ] **Step 2: Run tests and confirm missing endpoints**

Run the focused API test command from Task 3. Expected: archive route returns 404.

- [ ] **Step 3: Add strict schemas and service methods**

```python
class TaskLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    status: Literal["open", "in_progress", "completed", "cancelled"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    priority: Literal["low", "normal", "high"] | None = None
    due_at: datetime | None = None
    contact_id: int | None = Field(default=None, ge=1)


class TaskLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: str = Field(min_length=1, max_length=50)
    entity_id: int = Field(gt=0)
    expected_version: int = Field(ge=1)


class TaskOut(TaskCreate):
    id: int
    status: str
    archived_at: datetime | None
    archive_reason: str | None
    version: int


class TaskLinkOut(BaseModel):
    id: int
    task_id: int
    entity_type: str
    entity_id: int
    display_name: str
    task_version: int
```

Reject an update body that contains no mutable field besides `expected_version`. PATCH performs one compare-and-swap and increments even when the submitted value equals the stored value:

```python
updated = await db.scalar(
    update(CRMTask)
    .where(
        CRMTask.id == task_id,
        CRMTask.version == payload.expected_version,
        CRMTask.archived_at.is_(None),
    )
    .values(**changes, version=CRMTask.version + 1)
    .returning(CRMTask)
)
```

If it returns no row, reload the task to distinguish 404, `task_archived`, and `task_version_conflict`. Task-link creation locks the task row with `SELECT ... FOR UPDATE`, checks archive state and `expected_version`, checks for the existing unique link, inserts a new link, then sets `task.version = task.version + 1` in the same savepoint. Return `TaskLinkOut.task_version`; a link insert failure rolls back the version increment. No router mutates a task or task link directly.

Archive/Restore first lock the task and query `(entity_type='task', entity_id, action, request_id)` for replay. An identical hash returns stored `result_json` without another increment; a different hash returns `task_request_mismatch`. For a new request, validate `expected_version`, mutate archive fields and `version + 1`, and persist the event/result in one savepoint. Return all conflicts as HTTP 409 with this stable body:

```json
{"detail":{"code":"task_version_conflict","current_version":4,"current_task":{"id":7,"title":"Call Jane","contact_id":null,"description":"","priority":"normal","due_at":null,"status":"open","archived_at":null,"archive_reason":null,"version":4}}}
```

- [ ] **Step 4: Add routes and archived mutation guards**

```python
@router.post("/tasks/{task_id}/archive", response_model=TaskOut)
async def archive_task(task_id: int, payload: TaskLifecycleRequest, admin=Depends(require_admin), db=Depends(get_db)):
    return (await task_service.archive(db, task_id=task_id, request=payload, actor_id=str(admin.id))).task
```

Add symmetric Restore. `GET /tasks` accepts strict `visibility=active|archived|all`, defaulting to active. PATCH and task-link creation use the service methods above and return 409 while archived. Creation returns version 1; each acknowledged PATCH, archive, restore, or new task-link mutation advances the one shared version exactly once.

- [ ] **Step 5: Run API/projection suites and commit**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_command_task_api.py tests/test_command_task_projections.py
git add backend
git commit -m "feat: add task archive and restore APIs"
```

## Task 5: Add the typed frontend task lifecycle client

**Files:**

- Modify: `frontend/src/lib/command/api.ts`
- Modify: `frontend/src/lib/command/api.test.ts`
- Modify: `frontend/src/components/command/workspaceFilters.ts`

- [ ] **Step 1: Write red decoder/request tests**

Test `visibility`, strict decoding of every new response field, create idempotency header, PATCH/link `expected_version`, request UUID/version/reason, structured 409, and an unknown network result that triggers refetch rather than optimistic retry.

```typescript
expect(commandApi.tasks({ visibility: 'archived' })).resolves.toEqual([archivedTask]);
await commandApi.archiveTask(7, { request_id: requestId, expected_version: 3, reason: 'Duplicate' });
expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/tasks/7/archive'), expect.objectContaining({ method: 'POST' }));
await expect(commandApi.updateTask(7, { expected_version: 3, status: 'completed' })).resolves.toMatchObject({ version: 4 });
await expect(commandApi.addTaskLink(7, { expected_version: 4, entity_type: 'agreement', entity_id: 9 })).resolves.toMatchObject({ task_version: 5 });
```

- [ ] **Step 2: Run the focused test and verify failure**

```bash
cd frontend
npm exec vitest run -- src/lib/command/api.test.ts
```

- [ ] **Step 3: Add strict types and API methods**

```typescript
export type TaskVisibility = 'active' | 'archived' | 'all';
export type Task = Readonly<{
  id: number;
  title: string;
  contact_id: number | null;
  description: string;
  priority: 'low' | 'normal' | 'high';
  due_at: string | null;
  status: 'open' | 'in_progress' | 'completed' | 'cancelled';
  archived_at: string | null;
  archive_reason: string | null;
  version: number;
}>;

export type TaskLifecycleRequest = Readonly<{
  request_id: string;
  expected_version: number;
  reason?: string;
}>;

export type TaskConflict = Readonly<{
  code: 'task_version_conflict' | 'task_archived' | 'task_request_mismatch';
  current_version: number;
  current_task: Task;
}>;

export class CommandConflictError extends Error {
  constructor(readonly conflict: TaskConflict) {
    super(conflict.code);
  }
}

export class CommandOutcomeUncertainError extends Error {
  constructor(readonly original: unknown) {
    super('The server may have applied the task change; refresh before retrying.');
  }
}
```

Replace unchecked task casts with a real decoder. The implementation may share primitive helpers, but it must enforce these same fields and literals:

```typescript
function objectAt(input: unknown, path: string): Record<string, unknown> {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) {
    throw new CommandDecodeError(path, 'object');
  }
  return input as Record<string, unknown>;
}

export function decodeTask(input: unknown, path = 'response'): Task {
  const row = objectAt(input, path);
  const integer = (key: string, minimum: number) => {
    const value = row[key];
    if (!Number.isSafeInteger(value) || (value as number) < minimum) {
      throw new CommandDecodeError(`${path}.${key}`, `integer >= ${minimum}`);
    }
    return value as number;
  };
  const string = (key: string) => {
    const value = row[key];
    if (typeof value !== 'string') throw new CommandDecodeError(`${path}.${key}`, 'string');
    return value;
  };
  const nullableString = (key: string) => row[key] === null ? null : string(key);
  const priority = string('priority');
  const status = string('status');
  if (!['low', 'normal', 'high'].includes(priority)) {
    throw new CommandDecodeError(`${path}.priority`, 'task priority');
  }
  if (!['open', 'in_progress', 'completed', 'cancelled'].includes(status)) {
    throw new CommandDecodeError(`${path}.status`, 'task status');
  }
  const contact = row.contact_id;
  if (contact !== null && (!Number.isSafeInteger(contact) || (contact as number) < 1)) {
    throw new CommandDecodeError(`${path}.contact_id`, 'null or positive integer');
  }
  return {
    id: integer('id', 1), title: string('title'),
    contact_id: contact as number | null, description: string('description'),
    priority: priority as Task['priority'], due_at: nullableString('due_at'),
    status: status as Task['status'], archived_at: nullableString('archived_at'),
    archive_reason: nullableString('archive_reason'), version: integer('version', 1),
  };
}
```

Use a dedicated mutation transport so the UI can distinguish a definite conflict from an unknown outcome:

```typescript
async function taskMutation<T>(
  path: string,
  method: 'POST' | 'PATCH',
  body: unknown,
  decode: Decoder<T>,
  headers: Record<string, string> = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/v1/command${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${localStorage.getItem('admin_token') ?? ''}`,
        'Content-Type': 'application/json',
        ...headers,
      },
      body: JSON.stringify(body),
    });
  } catch (error) {
    throw new CommandOutcomeUncertainError(error);
  }
  if (response.status === 409) {
    try {
      throw new CommandConflictError(decodeTaskConflict(await response.json()));
    } catch (error) {
      if (error instanceof CommandConflictError) throw error;
      throw new CommandOutcomeUncertainError(error);
    }
  }
  if (response.status >= 500) throw new CommandOutcomeUncertainError(response.status);
  if (!response.ok) throw new CommandHttpError(response.status, `Command request failed (${response.status})`);
  try {
    return decode(await response.json());
  } catch (error) {
    throw new CommandOutcomeUncertainError(error);
  }
}
```

`decodeTaskConflict` must decode the FastAPI `detail` object, its exact code, positive `current_version`, and `current_task` through `decodeTask`; malformed conflict JSON becomes `CommandOutcomeUncertainError`, not a fabricated conflict. Add `archiveTask` and `restoreTask` through this transport. Change `updateTask` to require `{expected_version, ...changes}`, change `addTaskLink` to require `{expected_version, entity_type, entity_id}` and decode `task_version`, and change `createTask` to accept a UUID idempotency key and send it as `X-Idempotency-Key`. Never automatically retry `CommandOutcomeUncertainError`.

- [ ] **Step 4: Run tests/typecheck and commit**

```bash
npm exec vitest run -- src/lib/command/api.test.ts
npm run typecheck
git add frontend/src/lib/command frontend/src/components/command/workspaceFilters.ts
git commit -m "feat: add typed task lifecycle client"
```

## Task 6: Build accessible Task Archive and Restore UI

**Files:**

- Modify: `frontend/src/components/command/TasksWorkspace.tsx`
- Modify: `frontend/src/components/command/TaskEditor.tsx`
- Create: `frontend/src/components/command/TasksWorkspace.test.tsx`

- [ ] **Step 1: Write red interaction tests**

Cover Active/Archived filters, action menu, named confirmation dialog, ACK-only removal, Undo, stale conflict, uncertain refetch, keyboard focus return, and no edit/link controls on archived tasks.

```tsx
await user.click(screen.getByRole('button', { name: /task actions for call jane/i }));
await user.click(screen.getByRole('menuitem', { name: /archive/i }));
expect(screen.getByRole('dialog', { name: /archive call jane/i })).toBeVisible();
await user.click(screen.getByRole('button', { name: /^archive$/i }));
expect(api.archiveTask).toHaveBeenCalledWith(task.id, expect.objectContaining({ expected_version: task.version }));
```

- [ ] **Step 2: Run the component test and verify failure**

```bash
cd frontend
npm exec vitest run -- src/components/command/TasksWorkspace.test.tsx
```

- [ ] **Step 3: Implement the UI using existing Command styling**

Use `@phosphor-icons/react` icons, a portal dialog with `role="dialog"`, focus trap/return, 44px targets, and the existing black/gold visual system. Generate one UUID before the write and retain it for reconciliation. Do not mutate the local collection until the response returns. Handle the two typed failures concretely:

```typescript
const request: TaskLifecycleRequest = {
  request_id: crypto.randomUUID(),
  expected_version: task.version,
  reason: reason.trim() || undefined,
};
try {
  replaceTask(await commandApi.archiveTask(task.id, request));
} catch (error) {
  if (error instanceof CommandConflictError) {
    replaceTask(error.conflict.current_task);
    setMutationError('This task changed elsewhere. Review the refreshed task.');
  } else if (error instanceof CommandOutcomeUncertainError) {
    const current = (await commandApi.tasks({ visibility: 'all' }))
      .find((candidate) => candidate.id === task.id);
    if (current?.archived_at !== null && current.version >= task.version + 1) {
      replaceTask(current);
      setMutationNotice('Archive confirmed after refreshing.');
    } else {
      setRetry(() => () => commandApi.archiveTask(task.id, request));
      setMutationError('Archive outcome is unknown. Refresh or retry the same request.');
    }
  } else {
    throw error;
  }
}
```

The retry closure must reuse the same `request_id`; a new UUID could apply the lifecycle mutation twice. PATCH/link uncertain outcomes refetch and require a fresh user action with the returned current version because those operations have no lifecycle request ID.

- [ ] **Step 4: Add Undo as a real Restore request**

The toast retains the archived task's returned version and sends a new Restore request UUID with that version. Do not implement client-only undo.

- [ ] **Step 5: Run component/typecheck/lint tests and commit**

```bash
npm exec vitest run -- src/components/command/TasksWorkspace.test.tsx
npm run typecheck
npm run lint -- src/components/command/TasksWorkspace.tsx src/components/command/TaskEditor.tsx
git add frontend/src/components/command
git commit -m "feat: add task archive controls"
```

## Task 7: Reconcile contact and recovered archive presentation

**Files:**

- Modify: `frontend/src/lib/command/contacts.ts`
- Modify: `frontend/src/lib/command/contacts.test.ts`
- Modify: `frontend/src/components/command/contacts/ContactDetailWorkspace.tsx`
- Modify: `frontend/src/components/command/contacts/ContactDetailWorkspace.test.tsx`
- Modify: `frontend/src/components/command/contacts/ContactSectionSurface.tsx`

- [ ] **Step 1: Write red decoder/render tests**

Assert mutable archived tasks expose Restore; recovered source-only archive evidence exposes a `Recovered evidence` label and no action. Assert all new summary keys decode exactly.

- [ ] **Step 2: Run focused tests and confirm failure**

```bash
cd frontend
npm exec vitest run -- src/lib/command/contacts.test.ts src/components/command/contacts/ContactDetailWorkspace.test.tsx
```

- [ ] **Step 3: Implement split counts and controls**

Use `archived_mutable_tasks` for task records and `archived_recovered_evidence` for source-only occurrences. Keep their combined number visible only as a total with both subtotals in accessible text.

- [ ] **Step 4: Run tests/typecheck and commit**

```bash
npm exec vitest run -- src/lib/command/contacts.test.ts src/components/command/contacts/ContactDetailWorkspace.test.tsx
npm run typecheck
git add frontend/src/lib/command/contacts* frontend/src/components/command/contacts
git commit -m "fix: distinguish archived tasks from recovered evidence"
```

## Task 8: Add browser coverage and verify the phase

**Files:**

- Create: `frontend/e2e/command-tasks.spec.ts`
- Modify: `frontend/playwright.config.ts`
- Modify: `tdtn.md`
- Modify: `memory.md`

- [ ] **Step 1: Add stateful authenticated Playwright coverage**

The fixture must model GET active/archived/all, archive ACK, restore ACK, stale version conflict, and uncertain response reconciliation. Test desktop and mobile keyboard/focus behavior and run axe on Active, confirmation dialog, Archived, and conflict states.

Modify the existing explicit project allowlists so the new file actually runs in all three requested projects; leave `command-visual` unchanged:

```typescript
{
  name: 'command-desktop',
  testMatch: [
    '**/command-shell.spec.ts',
    '**/command-home.spec.ts',
    '**/command-contacts.spec.ts',
    '**/command-tasks.spec.ts',
  ],
},
{
  name: 'command-mobile',
  testMatch: [
    '**/command-mobile.spec.ts',
    '**/command-contacts-mobile.spec.ts',
    '**/command-tasks.spec.ts',
  ],
},
{
  name: 'command-a11y',
  testMatch: [
    '**/command-accessibility.spec.ts',
    '**/command-contacts-accessibility.spec.ts',
    '**/command-tasks.spec.ts',
  ],
},
```

- [ ] **Step 2: Run the focused browser suite**

```bash
cd frontend
npm exec playwright test -- --project=command-desktop --project=command-mobile --project=command-a11y e2e/command-tasks.spec.ts
```

Expected: all selected projects pass with zero browser errors.

- [ ] **Step 3: Run the full phase verification**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" GOOGLE_WORKSPACE_CLIENT_ID=dummy GOOGLE_WORKSPACE_CLIENT_SECRET=dummy GEMINI_API_KEY=dummy-key PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q
JWT_SECRET=test-secret DATABASE_URL="$CRM_TASK_TEST_DATABASE_URL" \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/alembic heads
cd ../frontend
npm test
npm run typecheck
npm run lint
npm run build
git diff --check
```

Expected: backend/frontend tests, typecheck, lint, and build pass; Alembic reports exactly `81a4d2c6e9f0` before the next plan starts.

- [ ] **Step 4: Update project history and commit**

Record exact test counts and migration head in `tdtn.md` and the durable architecture choice in `memory.md`.

```bash
git add frontend/e2e frontend/playwright.config.ts tdtn.md memory.md
git commit -m "test: verify CRM task archive foundation"
```

## Rollout Gate

Keep `CRM_TASK_ARCHIVE_ENABLED=false` while migrating. Before enabling it in production: take a logical backup, record normalized task counts by status and recovered archive occurrence counts, apply the migration, prove one Alembic head, compare counts, verify active projections through authenticated API, then enable the flag and exercise archive/restore against a controlled task. Do not begin Gmail/Sydney task application until the shared task service and production idempotency constraints pass.
