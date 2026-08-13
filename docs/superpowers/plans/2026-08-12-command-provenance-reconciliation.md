# Command Provenance and Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the additive source-identity, artifact-linking, parser, reconciliation, and evidence API foundation required to reconstruct every recovered Command and DocuSign record without collapsing or fabricating records.

**Architecture:** Immutable `crm_archive_artifacts` remain the byte-level source of truth. New semantic source records distinguish observed records, rendered occurrences, and displayed aggregates; typed parsers produce deterministic drafts; an idempotent reconciliation service persists drafts, links their source artifacts, and records exact per-module outcomes. Read-only authenticated APIs expose provenance and reconciliation to the admin UI.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2 async, PostgreSQL/Alembic, Pydantic 2, pytest/pytest-asyncio, SQLite+aiosqlite for isolated persistence tests.

---

## File Structure

### New backend files

- `backend/models/command_provenance.py` — semantic source, artifact link, entity link, reconciliation run, and reconciliation result tables.
- `backend/schemas/command_provenance.py` — typed list/detail/run/result API contracts.
- `backend/alembic/versions/1d6e7f8a9b10_add_command_provenance.py` — additive tables, constraints, and indexes after `f0c8a6d9e431`.
- `backend/services/command_provenance.py` — immutable draft types, canonical JSON, bundle fingerprint, byte-integrity validation, and idempotent source-record persistence.
- `backend/services/command_parsers/__init__.py` — parser exports.
- `backend/services/command_parsers/base.py` — parser protocol, parse result, registry, and duplicate-module guard.
- `backend/services/command_parsers/archive_integrity.py` — initial parser that verifies raw archive integrity and reports the two source domains without creating fake business records.
- `backend/services/command_reconciliation.py` — run orchestration, module filtering, resumable status, result persistence, and failure handling.
- `backend/routers/command_provenance.py` — authenticated source-record, entity-source, and reconciliation endpoints.
- `backend/scripts/reconcile_command_archive.py` — `--dry-run`, `--apply`, `--verify-only`, `--resume`, and `--module` CLI.
- `backend/tests/fixtures/command/provenance/` — tiny deterministic Command/DocuSign artifact fixtures.
- `backend/tests/test_command_provenance_models.py` — schema constraints/defaults.
- `backend/tests/test_command_provenance_service.py` — fingerprints, integrity, canonical identities, and idempotent persistence.
- `backend/tests/test_command_parser_registry.py` — registry and module-result behavior.
- `backend/tests/test_command_reconciliation.py` — run/result/failure/resume behavior.
- `backend/tests/test_command_provenance_router.py` — auth, pagination, filters, detail, and evidence links.
- `backend/tests/test_reconcile_command_archive_cli.py` — mutually exclusive modes and safe refusal behavior.

### Modified backend files

- `backend/requirements.txt` — add `aiosqlite==0.21.0` for isolated async persistence tests.
- `backend/models/__init__.py` — import/export provenance models.
- `backend/alembic/env.py` — import Command and provenance models into migration metadata.
- `backend/main.py` — mount the focused provenance router at `/api/v1/command`.

## Task 1: Add Provenance Tables and Database Constraints

**Files:**
- Create: `backend/models/command_provenance.py`
- Create: `backend/alembic/versions/1d6e7f8a9b10_add_command_provenance.py`
- Create: `backend/tests/test_command_provenance_models.py`
- Modify: `backend/models/__init__.py`
- Modify: `backend/alembic/env.py`

- [ ] **Step 1: Write failing model-contract tests**

Create tests that assert the evidence enum, stable source identity, artifact-link uniqueness, one-normalized-entity-per-source/type rule, and reconciliation uniqueness:

```python
from models.command_provenance import (
    CRMEntitySource,
    CRMReconciliationResult,
    CRMSourceRecord,
    CRMSourceRecordArtifact,
    EvidenceLevel,
)


def constraint_columns(model):
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if getattr(constraint, "columns", None)
    }


def test_source_record_identity_is_parser_versioned():
    assert {item.value for item in EvidenceLevel} == {
        "observed_record", "rendered_occurrence", "displayed_aggregate"
    }
    assert (
        "source_system", "module", "record_kind", "source_key", "parser_version"
    ) in constraint_columns(CRMSourceRecord)


def test_provenance_links_cannot_duplicate_or_split_an_identity():
    assert ("source_record_id", "artifact_id") in constraint_columns(CRMSourceRecordArtifact)
    assert ("source_record_id", "entity_type") in constraint_columns(CRMEntitySource)
    assert ("entity_type", "entity_id", "source_record_id") in constraint_columns(CRMEntitySource)


def test_reconciliation_has_one_result_per_run_and_module():
    assert ("run_id", "source_system", "module") in constraint_columns(CRMReconciliationResult)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd backend
../backend/.venv/bin/python -m pytest -q tests/test_command_provenance_models.py
```

Expected: collection fails because `models.command_provenance` does not exist.

- [ ] **Step 3: Create the SQLAlchemy models**

Define `EvidenceLevel`, `CaptureQuality`, and these exact tables:

```python
class CRMSourceRecord(Timestamped, Base):
    __tablename__ = "crm_source_records"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "module", "record_kind", "source_key", "parser_version",
            name="uq_crm_source_record_identity",
        ),
        Index("ix_crm_source_records_module_level", "source_system", "module", "evidence_level"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_system: Mapped[str] = mapped_column(String(64))
    module: Mapped[str] = mapped_column(String(64))
    record_kind: Mapped[str] = mapped_column(String(64))
    source_key: Mapped[str] = mapped_column(String(500))
    evidence_level: Mapped[str] = mapped_column(String(32))
    display_label: Mapped[str] = mapped_column(String(500), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    capture_quality: Mapped[str] = mapped_column(String(32), default="complete")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parser_version: Mapped[str] = mapped_column(String(64))


class CRMSourceRecordArtifact(Base):
    __tablename__ = "crm_source_record_artifacts"
    __table_args__ = (
        UniqueConstraint("source_record_id", "artifact_id", name="uq_crm_source_record_artifact"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("crm_source_records.id", ondelete="CASCADE"))
    artifact_id: Mapped[int] = mapped_column(ForeignKey("crm_archive_artifacts.id", ondelete="RESTRICT"))
    relation: Mapped[str] = mapped_column(String(32), default="evidence")


class CRMEntitySource(Base):
    __tablename__ = "crm_entity_sources"
    __table_args__ = (
        UniqueConstraint("source_record_id", "entity_type", name="uq_crm_source_entity_type"),
        UniqueConstraint("entity_type", "entity_id", "source_record_id", name="uq_crm_entity_source"),
        Index("ix_crm_entity_sources_entity", "entity_type", "entity_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int] = mapped_column(Integer)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("crm_source_records.id", ondelete="CASCADE"))


class CRMReconciliationRun(Base):
    __tablename__ = "crm_reconciliation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="running")
    requested_modules_json: Mapped[str] = mapped_column(Text, default="[]")
    error_text: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CRMReconciliationResult(Base):
    __tablename__ = "crm_reconciliation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "source_system", "module", name="uq_crm_reconciliation_result"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("crm_reconciliation_runs.id", ondelete="CASCADE"))
    source_system: Mapped[str] = mapped_column(String(64))
    module: Mapped[str] = mapped_column(String(64))
    expected_count: Mapped[int | None] = mapped_column(Integer)
    observed_count: Mapped[int] = mapped_column(Integer, default=0)
    rendered_count: Mapped[int] = mapped_column(Integer, default=0)
    normalized_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_only_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_content_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
```

Use the existing `Timestamped` mixin from `models.command`; import provenance models from `models/__init__.py` and from `alembic/env.py` so metadata is complete.

- [ ] **Step 4: Add an additive Alembic migration**

Create revision `1d6e7f8a9b10`, `down_revision = "f0c8a6d9e431"`. Create the five tables, named unique constraints, foreign keys with the specified delete behavior, and indexes from the models. The downgrade drops results, runs, entity links, artifact links, then source records.

- [ ] **Step 5: Run model and migration-shape tests**

Run:

```bash
cd backend
../backend/.venv/bin/python -m pytest -q tests/test_command_provenance_models.py
../backend/.venv/bin/python -m alembic heads
```

Expected: tests pass and the sole head is `1d6e7f8a9b10`.

- [ ] **Step 6: Commit**

```bash
git add backend/models backend/alembic backend/tests/test_command_provenance_models.py
git commit -m "feat: add Command provenance schema"
```

## Task 2: Build Deterministic Source Drafts and Archive Integrity

**Files:**
- Create: `backend/services/command_provenance.py`
- Create: `backend/tests/test_command_provenance_service.py`
- Create: `backend/tests/fixtures/command/provenance/kw-contact.json`
- Create: `backend/tests/fixtures/command/provenance/docusign-row.json`

- [ ] **Step 1: Write failing pure-service tests**

Cover canonical JSON ordering, stable identity, path validation, deterministic fingerprints independent of input order, missing bytes, size mismatch, and checksum mismatch:

```python
def test_bundle_fingerprint_is_order_independent(sample_artifacts):
    assert bundle_fingerprint(sample_artifacts) == bundle_fingerprint(list(reversed(sample_artifacts)))


def test_source_draft_uses_a_five_part_identity():
    draft = SourceRecordDraft(
        source_system="kw_command", module="contacts", record_kind="contact",
        source_key="aaaaaaaaaaaaaaaaaaaaaaaa", evidence_level=EvidenceLevel.OBSERVED_RECORD,
        display_label="Synthetic Contact", payload={"phone": None, "name": "Synthetic Contact"},
        artifact_paths=("kw_command_repaired/contacts/sections/0000001/timeline.json",),
        parser_version="command-v1",
    )
    assert draft.identity == (
        "kw_command", "contacts", "contact", "aaaaaaaaaaaaaaaaaaaaaaaa", "command-v1"
    )
    assert draft.payload_json == '{"name":"Synthetic Contact","phone":null}'


@pytest.mark.parametrize("mutation", ["missing", "length", "checksum"])
def test_archive_integrity_rejects_invalid_private_bytes(sample_artifact, mutation):
    with pytest.raises(ArchiveIntegrityError):
        verify_artifact_bytes(mutate(sample_artifact, mutation))
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
cd backend
../backend/.venv/bin/python -m pytest -q tests/test_command_provenance_service.py
```

Expected: fails because `services.command_provenance` does not exist.

- [ ] **Step 3: Add immutable service types and validation**

Define:

```python
@dataclass(frozen=True, slots=True)
class ArchiveArtifactInput:
    id: int
    source_path: str
    domain: str
    artifact_type: str
    filename: str
    sha256: str
    size_bytes: int
    content_bytes: bytes | None


@dataclass(frozen=True, slots=True)
class SourceRecordDraft:
    source_system: str
    module: str
    record_kind: str
    source_key: str
    evidence_level: EvidenceLevel
    display_label: str
    payload: Mapping[str, object]
    artifact_paths: tuple[str, ...]
    parser_version: str
    capture_quality: CaptureQuality = CaptureQuality.COMPLETE
    captured_at: datetime | None = None

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.source_system,
            self.module,
            self.record_kind,
            self.source_key,
            self.parser_version,
        )

    @property
    def payload_json(self) -> str:
        return json.dumps(self.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

`verify_artifact_bytes()` requires bytes, exact length, and SHA-256 equality. `bundle_fingerprint()` sorts by `source_path`, rejects duplicate paths, validates every artifact, and hashes `path\0sha256\0size\n`. Source keys and artifact paths reject blanks, absolute paths, `..`, and duplicate artifact paths.

- [ ] **Step 4: Run tests and commit**

```bash
cd backend
../backend/.venv/bin/python -m pytest -q tests/test_command_provenance_service.py
cd ..
git add backend/services/command_provenance.py backend/tests
git commit -m "feat: verify recovered archive provenance"
```

Expected: service tests pass.

## Task 3: Add the Parser Registry and Archive-Integrity Parser

**Files:**
- Create: `backend/services/command_parsers/__init__.py`
- Create: `backend/services/command_parsers/base.py`
- Create: `backend/services/command_parsers/archive_integrity.py`
- Create: `backend/tests/test_command_parser_registry.py`

- [ ] **Step 1: Write failing registry tests**

```python
def test_registry_orders_selected_modules_and_rejects_duplicates():
    registry = ParserRegistry()
    registry.register(FakeParser(module="tasks"))
    registry.register(FakeParser(module="contacts"))
    assert [parser.module for parser in registry.select(None)] == ["contacts", "tasks"]
    assert [parser.module for parser in registry.select({"tasks"})] == ["tasks"]
    with pytest.raises(DuplicateParserError):
        registry.register(FakeParser(module="tasks"))


def test_archive_integrity_parser_reports_domains_without_business_records(sample_artifacts):
    result = ArchiveIntegrityParser().parse(sample_artifacts, parser_version="command-v1")
    assert result.records == ()
    assert result.metrics.observed_count == 2
    assert result.metrics.details == {
        "artifacts": 2,
        "bytes": sum(item.size_bytes for item in sample_artifacts),
        "domains": {"docusign": 1, "kw_command": 1},
    }
```

- [ ] **Step 2: Run and verify RED**

```bash
cd backend
../backend/.venv/bin/python -m pytest -q tests/test_command_parser_registry.py
```

Expected: fails because the parser package does not exist.

- [ ] **Step 3: Implement protocol, result, metrics, and registry**

Use these contracts:

```python
@dataclass(frozen=True, slots=True)
class ModuleMetrics:
    source_system: str
    module: str
    expected_count: int | None
    observed_count: int
    rendered_count: int = 0
    normalized_count: int = 0
    evidence_only_count: int = 0
    unmatched_count: int = 0
    duplicate_content_count: int = 0
    error_count: int = 0
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModuleParseResult:
    records: tuple[SourceRecordDraft, ...]
    metrics: ModuleMetrics


class CommandArchiveParser(Protocol):
    module: str
    def parse(
        self,
        artifacts: Sequence[ArchiveArtifactInput],
        parser_version: str,
    ) -> ModuleParseResult:
        raise NotImplementedError
```

The registry sorts modules, rejects duplicates/blanks, and raises `UnknownParserModuleError` when a selected name is unavailable. `ArchiveIntegrityParser` calls `verify_artifact_bytes` for every input, counts domains and bytes, and emits zero semantic records.

- [ ] **Step 4: Run tests and commit**

```bash
cd backend
../backend/.venv/bin/python -m pytest -q tests/test_command_parser_registry.py
cd ..
git add backend/services/command_parsers backend/tests/test_command_parser_registry.py
git commit -m "feat: add Command archive parser registry"
```

## Task 4: Persist Source Records Idempotently and Record Reconciliation Runs

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/services/command_provenance.py`
- Create: `backend/services/command_reconciliation.py`
- Create: `backend/tests/test_command_reconciliation.py`
- Modify: `backend/tests/test_command_provenance_service.py`

- [ ] **Step 1: Add isolated async test support**

Add exactly:

```text
aiosqlite==0.21.0
```

Install it in the existing project environment and build a fixture that creates only `crm_archive_artifacts` plus the five provenance tables in `sqlite+aiosqlite:///:memory:`.

- [ ] **Step 2: Write failing idempotency and run-state tests**

```python
@pytest.mark.asyncio
async def test_same_parser_draft_is_idempotent(db, artifact_rows, contact_draft):
    first = await persist_source_records(db, [contact_draft])
    second = await persist_source_records(db, [contact_draft])
    assert first == PersistenceCounts(created=1, updated=0, unchanged=0, links_created=1)
    assert second == PersistenceCounts(created=0, updated=0, unchanged=1, links_created=0)
    assert await scalar_count(db, CRMSourceRecord) == 1
    assert await scalar_count(db, CRMSourceRecordArtifact) == 1


@pytest.mark.asyncio
async def test_same_identity_with_changed_evidence_requires_new_parser_version(db, artifact_rows, contact_draft):
    await persist_source_records(db, [contact_draft])
    changed = replace(contact_draft, artifact_paths=("other.json",))
    with pytest.raises(ParserVersionConflict):
        await persist_source_records(db, [changed])


@pytest.mark.asyncio
async def test_failed_module_marks_run_failed_and_preserves_error(db, registry, artifact_rows):
    registry.register(RaisingParser(module="contacts"))
    with pytest.raises(RuntimeError, match="broken fixture"):
        await execute_reconciliation(db, registry, artifact_rows, RunRequest(mode="dry_run", parser_version="v1"))
    run = (await db.execute(select(CRMReconciliationRun))).scalar_one()
    assert run.status == "failed"
    assert "broken fixture" in run.error_text
```

- [ ] **Step 3: Run and verify RED**

```bash
cd backend
../backend/.venv/bin/python -m pytest -q tests/test_command_provenance_service.py tests/test_command_reconciliation.py
```

Expected: fails because persistence and orchestration functions are absent.

- [ ] **Step 4: Implement idempotent persistence**

`persist_source_records()` must:

- reject duplicate draft identities in one parser result;
- fetch artifact IDs by every declared source path and fail if any are missing;
- create a source record only when its five-part identity is absent;
- treat identical payload/label/quality/timestamp/artifact-set as unchanged;
- update label/payload/quality/timestamp only when artifact-set is unchanged;
- require a new parser version if the artifact-set changes;
- add missing artifact links exactly once; and
- return `PersistenceCounts(created, updated, unchanged, links_created)`.

- [ ] **Step 5: Implement reconciliation orchestration**

Use:

```python
@dataclass(frozen=True, slots=True)
class RunRequest:
    mode: Literal["dry_run", "apply", "verify_only"]
    parser_version: str
    modules: frozenset[str] = frozenset()
    resume_run_id: int | None = None
```

`execute_reconciliation()` computes the fingerprint first, creates or validates a resumable run, selects parsers, persists only in `apply` mode, writes one result per module, commits successful module boundaries, and marks the run `completed`. `dry_run` parses and records metrics without semantic writes. `verify_only` runs only `archive_integrity`. Resume requires the same fingerprint/parser version and skips already successful module results. Any exception marks the run `failed`, stores a bounded error message, commits that state, and re-raises.

- [ ] **Step 6: Run focused and existing Command tests**

```bash
cd backend
../backend/.venv/bin/python -m pytest -q \
  tests/test_command_provenance_service.py \
  tests/test_command_parser_registry.py \
  tests/test_command_reconciliation.py \
  tests/test_command_models.py \
  tests/test_command_lifecycle.py \
  tests/test_command_geocoding.py \
  tests/test_command_file_storage.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/services backend/tests
git commit -m "feat: reconcile Command source records idempotently"
```

## Task 5: Add Safe Reconciliation CLI

**Files:**
- Create: `backend/scripts/reconcile_command_archive.py`
- Create: `backend/tests/test_reconcile_command_archive_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Test argument parsing as a pure function and patch the database runner only at the process boundary:

```python
def test_cli_requires_exactly_one_mode():
    with pytest.raises(SystemExit):
        parse_args([])
    with pytest.raises(SystemExit):
        parse_args(["--dry-run", "--apply"])


def test_cli_apply_requires_explicit_bundle_fingerprint():
    args = parse_args(["--apply", "--parser-version", "command-v1"])
    with pytest.raises(ValueError, match="--expect-fingerprint"):
        validate_apply_args(args)


def test_cli_supports_bounded_module_and_resume():
    args = parse_args([
        "--dry-run", "--parser-version", "command-v1",
        "--module", "contacts", "--module", "tasks", "--resume", "7",
    ])
    assert args.modules == ["contacts", "tasks"]
    assert args.resume == 7
```

- [ ] **Step 2: Run and verify RED**

```bash
cd backend
../backend/.venv/bin/python -m pytest -q tests/test_reconcile_command_archive_cli.py
```

Expected: fails because the CLI module does not exist.

- [ ] **Step 3: Implement safe CLI modes**

The parser exposes mutually exclusive `--dry-run`, `--apply`, and `--verify-only`; required `--parser-version`; repeatable `--module`; optional `--resume`; and `--expect-fingerprint`. Apply refuses before any semantic write unless the expected fingerprint exactly equals the computed DB archive fingerprint. The command loads artifact metadata and bytes ordered by source path, registers `ArchiveIntegrityParser` plus all domain parsers exported by the registry, runs reconciliation, and prints one JSON object containing run ID/status/fingerprint/module metrics.

- [ ] **Step 4: Run tests, execute verify-only against configured archive DB, and commit**

```bash
cd backend
../backend/.venv/bin/python -m pytest -q tests/test_reconcile_command_archive_cli.py
../backend/.venv/bin/python -m scripts.reconcile_command_archive \
  --verify-only --parser-version command-v1
cd ..
git add backend/scripts/reconcile_command_archive.py backend/tests/test_reconcile_command_archive_cli.py
git commit -m "feat: add safe Command reconciliation CLI"
```

Expected live verification JSON: `status` is `completed`; artifact total is 12,580; byte total is 745,060,261; fingerprint is 64 hexadecimal characters. This command writes only the reconciliation run/result audit rows, not source or CRM business records.

## Task 6: Expose Authenticated Provenance and Reconciliation APIs

**Files:**
- Create: `backend/schemas/command_provenance.py`
- Create: `backend/routers/command_provenance.py`
- Create: `backend/tests/test_command_provenance_router.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write failing router tests**

Use dependency overrides for `require_admin` and `get_db`. Cover:

```python
def test_source_records_require_admin(unauthenticated_client):
    assert unauthenticated_client.get("/api/v1/command/source-records").status_code == 401


def test_source_records_page_filters_and_reports_total(authenticated_client, source_records):
    response = authenticated_client.get(
        "/api/v1/command/source-records?source_system=kw_command&module=contacts&evidence_level=observed_record&page=1&page_size=25"
    )
    assert response.status_code == 200
    assert response.json()["page"] == 1
    assert response.json()["page_size"] == 25
    assert response.json()["total"] == 1


def test_source_record_detail_contains_artifact_metadata_not_private_bytes(authenticated_client, source_record):
    payload = authenticated_client.get(f"/api/v1/command/source-records/{source_record.id}").json()
    assert payload["artifacts"][0]["sha256"]
    assert "content_bytes" not in payload["artifacts"][0]


def test_entity_sources_and_latest_reconciliation_are_read_only(authenticated_client):
    assert authenticated_client.get("/api/v1/command/entities/contact/12/sources").status_code == 200
    assert authenticated_client.get("/api/v1/command/reconciliation/runs/latest").status_code == 200
    assert authenticated_client.post("/api/v1/command/reconciliation/runs").status_code == 405
```

- [ ] **Step 2: Run and verify RED**

```bash
cd backend
../backend/.venv/bin/python -m pytest -q tests/test_command_provenance_router.py
```

Expected: fails because the provenance router is absent.

- [ ] **Step 3: Add typed schemas and endpoints**

Use `ConfigDict(from_attributes=True)` and bounded query fields. Add:

- `GET /source-records` — filters: source system, module, record kind, evidence level, capture quality, query, page 1+, page size 1–200; stable order by source system/module/source key/id.
- `GET /source-records/{id}` — source record plus artifact metadata.
- `GET /entities/{entity_type}/{entity_id}/sources` — source records plus artifacts for one normalized entity.
- `GET /reconciliation/runs` — newest-first paginated runs.
- `GET /reconciliation/runs/latest` — latest run plus module results.
- `GET /reconciliation/runs/{id}` — one run plus module results.

Return 404 for unknown records/runs and reject entity types outside an explicit allowlist. Do not expose `content_bytes`; original downloads continue through the existing authenticated archive endpoint.

- [ ] **Step 4: Mount the router and run tests**

In `backend/main.py`:

```python
from routers import command_provenance

app.include_router(
    command_provenance.router,
    prefix="/api/v1/command",
    tags=["command-provenance"],
)
```

Run:

```bash
cd backend
../backend/.venv/bin/python -m pytest -q tests/test_command_provenance_router.py
../backend/.venv/bin/python -m pytest -q tests/test_command_*.py
```

Expected: provenance router tests and all Command-focused backend tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/routers/command_provenance.py backend/schemas/command_provenance.py backend/tests/test_command_provenance_router.py
git commit -m "feat: expose Command provenance evidence APIs"
```

## Task 7: Verify the Foundation and Document Its Contract

**Files:**
- Modify: `docs/superpowers/specs/2026-08-12-command-full-parity-design.md`
- Create: `docs/command-reconciliation-runbook.md`

- [ ] **Step 1: Add operational runbook**

Document exact verify, dry-run, apply, resume, per-module, migration, rollback, and post-run queries. Include this production apply guard:

```bash
python -m scripts.reconcile_command_archive \
  --apply \
  --parser-version command-v1 \
  --expect-fingerprint "$VERIFIED_COMMAND_ARCHIVE_FINGERPRINT"
```

Document that apply is not authorized until every selected domain parser has a reviewed reconciliation expectation and dry run.

- [ ] **Step 2: Run plan self-review checks**

```bash
bad_patterns=("T""BD" "T""ODO" "implement ""later" "fill ""in" "similar ""to" "appropriate ""error")
for pattern in "${bad_patterns[@]}"; do
  rg -n "$pattern" docs/superpowers/plans/2026-08-12-command-provenance-reconciliation.md && exit 1
done
git diff --check
```

Expected: the placeholder scan returns no matches and `git diff --check` is clean.

- [ ] **Step 3: Run all verification gates**

```bash
cd backend
../backend/.venv/bin/python -m pytest -q tests/test_command_*.py tests/test_reconcile_command_archive_cli.py
../backend/.venv/bin/python -m alembic heads
../backend/.venv/bin/python -m scripts.reconcile_command_archive --verify-only --parser-version command-v1
cd ../frontend
npm test -- --run
npm run typecheck
```

Expected: all targeted backend tests pass; one Alembic head; verify-only returns the exact 12,580-artifact/745,060,261-byte archive; 69 existing frontend tests pass; TypeScript passes.

- [ ] **Step 4: Commit**

```bash
git add docs
git commit -m "docs: add Command reconciliation runbook"
```

## Completion Gate

This plan is complete only when:

- migration upgrade is additive and exposes a single Alembic head;
- source identities cannot collapse by display title/name;
- a second identical persistence run creates zero additional rows or links;
- changed evidence under the same parser version is rejected;
- raw archive bytes, lengths, and hashes verify exactly;
- dry-run does not create semantic source records;
- apply requires the exact expected bundle fingerprint;
- all provenance endpoints require admin authentication and never expose private bytes inline; and
- focused backend plus existing frontend baselines pass.
