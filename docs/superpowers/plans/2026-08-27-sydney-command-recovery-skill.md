# Sydney Command Recovery Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Atlas operations skill repository-owned and permanently route Command contact requests through the canonical Command tools, then recover Brandon's exact unfinished pre-cutover request once under an enforced review-only policy.

**Architecture:** The existing Hermes overlay will ship and atomically install one managed skill before gateway startup. A new exact-selector recovery utility will reuse the existing backfilled canonical user event by staging a deterministic inbound spool bundle with local `review_only` metadata. The gateway and tool interceptor will preserve that policy across restart, allow read-only tools, deny every mutation durably, and return one review packet without sending email.

**Tech Stack:** Python 3.12+, Hermes overlay/bootstrap, SQLite Sydney spool and Hermes state database, Atlas JSON-RPC MCP, `unittest`/`pytest`, Railway.

---

## File Structure

- Create `hermes/skills/atlas-backend-operations/SKILL.md`: authoritative, focused Atlas/Command routing instructions.
- Create `hermes/overlay/sydney_recovery.py`: exact, dry-run-first legacy recovery admission and CLI.
- Create `backend/tests/test_sydney_recovery.py`: exact-selector, rejection, idempotency, and spool admission coverage.
- Modify `hermes/overlay/manifest.json`: managed-skill source, deployed asset name, destination, and SHA-256.
- Modify `hermes/overlay/apply_overlay.py`: copy the managed skill and recovery utility into the pinned template build context/image.
- Modify `hermes/overlay/atlas_backend_bootstrap.py`: verify and atomically install the managed skill before Hermes starts.
- Modify `hermes/overlay/install_sydney_overlay.py`: install `sydney_recovery.py` into the pinned Hermes package.
- Modify `hermes/overlay/sydney_spool.py`: allow an inbound bundle to carry bounded local-only metadata that is never sent to the backend run contract.
- Modify `hermes/overlay/sydney_gateway.py`: add the review-only continuation context and propagate local policy into claimed-run metadata.
- Modify `hermes/overlay/sydney_memory_provider.py`: expose the active run's local recovery policy and persist policy-denial tool evidence.
- Modify `hermes/overlay/sydney_runtime.py`: block all non-read-only tools while a `review_only` recovery run is active.
- Modify `backend/tests/test_hermes_overlay.py`: managed-skill manifest, image copy, install/no-op/fail-closed, and package-copy tests.
- Modify `backend/tests/test_sydney_spool.py`: local metadata round-trip and idempotency tests.
- Modify `backend/tests/test_sydney_memory_provider.py`: review-only read allowance, mutation denial, denial ledger, normal-run behavior, and restart preservation tests.
- Modify `hermes/README.md`, `docs/deployment/hermes-railway.md`, `tdtn.md`, and `memory.md`: source ownership, runbook, rollback, and final evidence.

### Task 1: Repository-owned Atlas skill and atomic installation

**Files:**
- Create: `hermes/skills/atlas-backend-operations/SKILL.md`
- Modify: `hermes/overlay/manifest.json`
- Modify: `hermes/overlay/apply_overlay.py`
- Modify: `hermes/overlay/atlas_backend_bootstrap.py`
- Modify: `backend/tests/test_hermes_overlay.py`

- [x] **Step 1: Write failing managed-skill and overlay tests**

Add tests that require the source skill, exact Command language, absence of the stale fallback and credential-bypass guidance, a manifest hash matching the source bytes, image copies, atomic installation, idempotent no-op, unrelated-skill preservation, and fail-closed hash mismatch.

```python
def test_managed_atlas_skill_routes_command_without_stale_fallback(self):
    root = Path(__file__).resolve().parents[2]
    skill = root / "hermes/skills/atlas-backend-operations/SKILL.md"
    text = skill.read_text()
    lowered = text.lower()
    self.assertIn("command_contacts_search", text)
    self.assertIn("command_contact_audience_preview", text)
    self.assertIn("navigation locator", lowered)
    self.assertIn("google contacts only", lowered)
    self.assertNotIn("always pull and parse this sheet first", lowered)
    self.assertNotIn("/proc/{ppid}/environ", text)
    self.assertNotIn("admin_password", lowered)

def test_manifest_pins_managed_skill_hash(self):
    root = Path(__file__).resolve().parents[2]
    skill = root / "hermes/skills/atlas-backend-operations/SKILL.md"
    manifest = json.loads((root / "hermes/overlay/manifest.json").read_text())
    managed = manifest["managed_skills"]["atlas-backend-operations"]
    self.assertEqual(
        managed,
        {
            "source": "skills/atlas-backend-operations/SKILL.md",
            "deployed_source": "atlas_backend_operations_skill.md",
            "destination": "skills/productivity/atlas-backend-operations/SKILL.md",
            "sha256": hashlib.sha256(skill.read_bytes()).hexdigest(),
        },
    )

def test_bootstrap_installs_managed_skill_once_and_preserves_other_skills(self):
    bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        home = root / "home"
        asset = root / "atlas_backend_operations_skill.md"
        asset.write_text("managed skill\n")
        other = home / "skills/productivity/other/SKILL.md"
        other.parent.mkdir(parents=True)
        other.write_text("keep\n")
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        manifest = {
            "managed_skills": {
                "atlas-backend-operations": {
                    "source": "skills/atlas-backend-operations/SKILL.md",
                    "deployed_source": asset.name,
                    "destination": "skills/productivity/atlas-backend-operations/SKILL.md",
                    "sha256": digest,
                }
            }
        }
        first = bootstrap.install_managed_skills(home, manifest, asset_root=root)
        second = bootstrap.install_managed_skills(home, manifest, asset_root=root)
        installed = home / manifest["managed_skills"]["atlas-backend-operations"]["destination"]
        self.assertEqual(first[0]["changed"], True)
        self.assertEqual(second[0]["changed"], False)
        self.assertEqual(installed.read_bytes(), asset.read_bytes())
        self.assertEqual(other.read_text(), "keep\n")
```

- [x] **Step 2: Run the tests and verify RED**

Run:

```bash
cd backend
PYTHONPATH=. /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_hermes_overlay.py -k 'managed_atlas_skill or managed_skill_hash or installs_managed_skill'
```

Expected: failures because the source skill, manifest section, image copy, and installer function do not exist.

- [x] **Step 3: Add the focused source skill**

Create a concise skill with this complete behavioral core:

```markdown
---
name: atlas-backend-operations
description: Use Sold With Sweeney Atlas backend tools safely, including Command CRM and Google Workspace.
version: 2.0.0
---

# Atlas Backend Operations

## Command contacts

- `command_contacts_search` is the authoritative current-state source for Command contacts.
- `command_contact_audience_preview` is the authoritative whole-audience count, checksum, reference, and masked sample.
- A Command admin URL is a navigation locator, never a data endpoint. Never scrape its HTML or `__NEXT_DATA__`.
- `contacts_search` searches Google Contacts only; never substitute it for Command.
- `KW Success Agent Roster 2025` is historical and may be used only when Brandon explicitly asks for that former-office roster.
- Current Command results outrank remembered or historical contact data.
- For all-Command-contact work, preview the bounded audience rather than putting every contact into model context.

## Recovered work

- Recovery is review-only. Prepare the exact audience count/checksum/sample and proposed subject/body.
- State clearly that nothing was sent.
- Old wording such as "send this" is not fresh approval after restart or legacy recovery.
- Never call a send, draft, document, sheet, calendar, or CRM mutation during review-only recovery.

## Security

- Use only the protected Atlas tools provided to Hermes.
- Never inspect process environments, retrieve admin passwords, bypass agent-control authentication, or scrape private CRM pages.
```

Retain only safe, still-relevant Drive query, native Google Sheet reading, voice reconciliation, approval-link, and tool-reference guidance from the old skill. Remove duplicated headings, brokerage-source ambiguity, `/proc` credential extraction, admin-password access, and unrelated one-off property instructions.

- [x] **Step 4: Add manifest and overlay copies**

Compute the source SHA-256:

```bash
python3 -c 'from pathlib import Path; import hashlib; p=Path("hermes/skills/atlas-backend-operations/SKILL.md"); print(hashlib.sha256(p.read_bytes()).hexdigest())'
```

Put the exact printed digest in `manifest.json` under `managed_skills`. Extend `OVERLAY_TARGETS`, `_desired_contents`, and Dockerfile insertions so the template contains `atlas_backend_operations_skill.md` and the image copies it to `/app/atlas_backend_operations_skill.md`.

- [x] **Step 5: Implement fail-closed atomic skill installation**

Add `install_managed_skills` before `configure_atlas_backend` runs:

```python
def install_managed_skills(
    hermes_home: Path,
    manifest: dict[str, Any],
    *,
    asset_root: Path = Path("/app"),
) -> list[dict[str, object]]:
    proofs: list[dict[str, object]] = []
    for name, raw in sorted((manifest.get("managed_skills") or {}).items()):
        if not isinstance(raw, dict):
            raise ValueError("managed skill manifest entry is invalid")
        expected = str(raw.get("sha256") or "")
        source = asset_root / str(raw.get("deployed_source") or "")
        destination = (hermes_home / str(raw.get("destination") or "")).resolve()
        destination.relative_to(hermes_home.resolve())
        contents = source.read_bytes()
        actual = hashlib.sha256(contents).hexdigest()
        if actual != expected:
            raise ValueError(f"managed skill hash mismatch: {name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        changed = _atomic_write(destination, contents)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
            raise ValueError(f"managed skill install verification failed: {name}")
        proofs.append({"name": name, "sha256": expected, "changed": changed})
    return proofs
```

Import `hashlib`, load the manifest once in `main`, install the skill before configuration/backfill, and print only the content-free proof JSON.

- [x] **Step 6: Run Task 1 tests and verify GREEN**

Run:

```bash
cd backend
PYTHONPATH=. /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_hermes_overlay.py
```

Expected: all `test_hermes_overlay.py` tests pass.

- [x] **Step 7: Commit Task 1**

```bash
git add hermes/skills/atlas-backend-operations/SKILL.md \
  hermes/overlay/manifest.json hermes/overlay/apply_overlay.py \
  hermes/overlay/atlas_backend_bootstrap.py backend/tests/test_hermes_overlay.py
git commit -m "fix(hermes): own Command routing skill"
```

### Task 2: Exact, idempotent legacy recovery admission

**Files:**
- Create: `hermes/overlay/sydney_recovery.py`
- Create: `backend/tests/test_sydney_recovery.py`
- Modify: `hermes/overlay/sydney_spool.py`
- Modify: `backend/tests/test_sydney_spool.py`
- Modify: `hermes/overlay/apply_overlay.py`
- Modify: `hermes/overlay/install_sydney_overlay.py`
- Modify: `backend/tests/test_hermes_overlay.py`

- [x] **Step 1: Write failing spool-local-metadata tests**

```python
def test_inbound_local_metadata_is_durable_and_idempotent(tmp_path):
    spool = SydneySpool(tmp_path / "spool.db")
    try:
        first = spool.enqueue_inbound(
            EVENT_BATCH,
            RUN_START,
            source_key="inbound:recovery:stable",
            local_metadata={"recovery_policy": "review_only"},
        )
        second = spool.enqueue_inbound(
            EVENT_BATCH,
            RUN_START,
            source_key="inbound:recovery:stable",
            local_metadata={"recovery_policy": "review_only"},
        )
        record = spool.get_record("inbound:recovery:stable")
        assert first == second
        assert record.payload["local_metadata"] == {"recovery_policy": "review_only"}
    finally:
        spool.close()
```

Also assert that changing the local policy for the same source key raises `SpoolConflict`.

- [x] **Step 2: Run the spool test and verify RED**

Run:

```bash
cd backend
PYTHONPATH=. /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_sydney_spool.py -k local_metadata
```

Expected: `enqueue_inbound()` rejects the unknown `local_metadata` argument.

- [x] **Step 3: Add bounded local metadata to inbound bundles**

Change only the spool contract; never pass local metadata to backend `runs/start`:

```python
def enqueue_inbound(
    self,
    event_batch: dict[str, Any],
    run_start: dict[str, Any],
    *,
    source_key: str,
    local_metadata: dict[str, Any] | None = None,
) -> int:
    payload = {"event_batch": event_batch, "run_start": run_start}
    if local_metadata:
        payload["local_metadata"] = redact_payload(local_metadata)
    return self.enqueue(kind="inbound_bundle", source_key=source_key, payload=payload)
```

- [x] **Step 4: Write failing recovery utility tests**

Build a small Hermes `state.db`, exact session routing index, reconciled spool session, and selected user row. Cover:

```python
def test_review_only_recovery_dry_run_then_enqueues_once(recovery_fixture):
    recovery = recovery_fixture.recovery
    digest = recovery_fixture.selected_sha256
    dry_run = recovery.admit(
        session_id=recovery_fixture.session_id,
        message_id=recovery_fixture.message_id,
        expected_content_sha256=digest,
        enqueue=False,
    )
    assert dry_run["eligible"] is True
    assert dry_run["enqueued"] is False
    assert recovery_fixture.spool.find_inbound(dry_run["platform_message_id"]) is None

    admitted = recovery.admit(
        session_id=recovery_fixture.session_id,
        message_id=recovery_fixture.message_id,
        expected_content_sha256=digest,
        enqueue=True,
    )
    replay = recovery.admit(
        session_id=recovery_fixture.session_id,
        message_id=recovery_fixture.message_id,
        expected_content_sha256=digest,
        enqueue=True,
    )
    record = recovery_fixture.spool.find_inbound(admitted["platform_message_id"])
    assert admitted["record_id"] == replay["record_id"]
    assert record.payload["local_metadata"] == {"recovery_policy": "review_only"}
    assert record.payload["event_batch"]["events"][0]["source_event_key"].endswith(
        f":{recovery_fixture.message_id}:user"
    )
```

Add individual rejection tests for wrong hash, wrong identity/session, non-user role, observed row, canary/control/compaction content, missing reconciliation expectation, an existing terminal recovery, and a later final assistant response before the next user turn.

- [x] **Step 5: Run recovery tests and verify RED**

Run:

```bash
cd backend
PYTHONPATH=. /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_sydney_recovery.py
```

Expected: import failure because `sydney_recovery.py` does not exist.

- [x] **Step 6: Implement `SydneyLegacyRecovery` and CLI**

Implement a focused class that reuses `SydneyBackfill` to produce the exact original event and batch:

```python
class SydneyLegacyRecovery:
    def __init__(self, *, backfill: SydneyBackfill, spool: SydneySpool) -> None:
        self.backfill = backfill
        self.spool = spool

    def admit(
        self,
        *,
        session_id: str,
        message_id: int,
        expected_content_sha256: str,
        enqueue: bool = False,
    ) -> dict[str, Any]:
        row, session = self._validated_user_row(session_id, message_id)
        events = self.backfill._events_for_message(row)
        if len(events) != 1 or events[0]["event_type"] != "user":
            raise RecoveryRejected("selected message is not one visible user event")
        content_sha256 = hashlib.sha256(events[0]["content"].encode()).hexdigest()
        if not hmac.compare_digest(content_sha256, expected_content_sha256):
            raise RecoveryRejected("selected message hash does not match")
        if self.spool.reconciliation_expectation(session_id) is None:
            raise RecoveryRejected("selected session is not reconciled")
        stable = f"{self.backfill.platform}\x1f{self.backfill.external_chat_id}\x1f{session_id}\x1f{message_id}"
        digest = hashlib.sha256(stable.encode()).hexdigest()
        platform_message_id = f"legacy-recovery:{digest}"
        source_key = f"inbound:recovery:{digest}"
        batch = self.backfill._batch(
            session,
            events,
            known_session_ids=set(self.spool.reconciliation_expectations()),
        )
        run_start = {
            "platform_message_id": platform_message_id,
            "terminal_deadline_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        }
        record_id = None
        if enqueue:
            record_id = self.spool.enqueue_inbound(
                batch,
                run_start,
                source_key=source_key,
                local_metadata={"recovery_policy": "review_only"},
            )
        return self._content_free_result(
            content_sha256=content_sha256,
            platform_message_id=platform_message_id,
            record_id=record_id,
            enqueued=enqueue,
        )
```

`_content_free_result` returns only booleans, hashes, the stable platform ID, policy, and record ID; it never includes content. `_validated_user_row` performs an exact primary-key/session query, verifies the private mapped session, control-prefix rejection, `observed=0`, and no final assistant response before the next user turn.

The CLI requires `--session-id`, `--message-id`, and `--expected-content-sha256`; defaults to dry-run; requires `--enqueue` to write; reads identity values only from existing Sydney environment variables; and prints sorted content-free JSON.

- [x] **Step 7: Wire the recovery module through both overlays**

Add `sydney_recovery.py` to `OVERLAY_TARGETS`, Docker image copies, `_desired_contents`, and the pinned Hermes package copy map:

```python
"plugins/memory/sydney/sydney_recovery.py": "sydney_recovery.py",
```

Extend overlay tests to require the file at every stage and verify the module imports through the installed package layout.

- [x] **Step 8: Run Task 2 tests and verify GREEN**

Run:

```bash
cd backend
PYTHONPATH=. /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_sydney_spool.py tests/test_sydney_recovery.py tests/test_hermes_overlay.py
```

Expected: all selected tests pass.

- [x] **Step 9: Commit Task 2**

```bash
git add hermes/overlay/sydney_recovery.py hermes/overlay/sydney_spool.py \
  hermes/overlay/apply_overlay.py hermes/overlay/install_sydney_overlay.py \
  backend/tests/test_sydney_recovery.py backend/tests/test_sydney_spool.py \
  backend/tests/test_hermes_overlay.py
git commit -m "feat(sydney): admit exact review-only recovery"
```

### Task 3: Enforced review-only runtime and restart continuation

**Files:**
- Modify: `hermes/overlay/sydney_gateway.py`
- Modify: `hermes/overlay/sydney_memory_provider.py`
- Modify: `hermes/overlay/sydney_runtime.py`
- Modify: `backend/tests/test_sydney_memory_provider.py`

- [x] **Step 1: Write failing review-only policy tests**

Add tests using a claimed inbound whose `local_metadata` contains `review_only`:

```python
@pytest.mark.parametrize(
    "tool_name",
    [
        "gmail_draft_create",
        "gmail_send",
        "docs_create",
        "sheets_append",
        "calendar_event_create",
        "crm_task_drafts_create",
    ],
)
def test_review_only_recovery_blocks_every_mutation(active_recovery_agent, tool_name):
    decision = tool_before(
        active_recovery_agent,
        "blocked-call",
        tool_name,
        {"subject": "review"},
    )
    assert decision is not None
    assert decision.block_message == REVIEW_ONLY_POLICY_MESSAGE
    assert active_recovery_agent.provider.backend.executed_tools == []
    assert active_recovery_agent.provider.spool.get_record(
        f"tool:{active_recovery_agent.provider.active_run_id}:blocked-call:before"
    ) is not None

@pytest.mark.parametrize(
    "tool_name",
    ["context_history_search", "command_contact_audience_preview", "command_contacts_search"],
)
def test_review_only_recovery_allows_read_tools(active_recovery_agent, tool_name):
    assert tool_before(active_recovery_agent, "read-call", tool_name, {}) is None

def test_normal_run_keeps_existing_mutation_behavior(active_normal_agent):
    assert tool_before(
        active_normal_agent,
        "normal-draft",
        "gmail_draft_create",
        {"to": ["safe@example.test"], "subject": "Draft", "body_text": "Body"},
    ) is None
```

Add gateway tests asserting a normal retry uses the old marker, a recovery uses the review-only marker, and local metadata never appears in the backend `start_run` request.

- [x] **Step 2: Run policy tests and verify RED**

Run:

```bash
cd backend
PYTHONPATH=. /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_sydney_memory_provider.py -k 'review_only or local_metadata_never'
```

Expected: failures because the provider exposes no active recovery policy and runtime does not block mutations.

- [x] **Step 3: Expose the active local recovery policy**

Add a provider method:

```python
def active_recovery_policy(self) -> str | None:
    if not self._active_run_id:
        return None
    inbound = self.spool.find_inbound_for_run(self._active_run_id)
    local = inbound.payload.get("local_metadata") if inbound is not None else None
    policy = local.get("recovery_policy") if isinstance(local, dict) else None
    return str(policy) if policy in {"review_only"} else None
```

Add a helper that records a tool call plus a `not_delivered` result using a stable `policy:<tool_call_id>` attempt key. It drains both records before returning so policy denial is canonical and repeatable without executing the tool.

- [x] **Step 4: Enforce policy before any non-read-only tool execution**

In `tool_before`, after establishing the active run/lease and calculating the side-effect class, add:

```python
if (
    provider.active_recovery_policy() == "review_only"
    and not _review_only_tool_is_allowed(tool_name)
):
    provider.record_policy_denial(
        run_id=run_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
    )
    return SydneyToolBeforeDecision(block_message=REVIEW_ONLY_POLICY_MESSAGE)
```

The reviewed allowlist is fail-closed. Every denial must be recorded as a
`non_idempotent_write` with a `not_delivered` result so it cannot become a
retryable mutation. The constant must state that recovery is review-only, the
action was not executed, and fresh Brandon approval is required.

- [x] **Step 5: Carry review-only context through restart**

Change the gateway context builder to accept the local policy:

```python
def _continuation_channel_context(
    original: str,
    *,
    recovery_policy: str | None = None,
) -> str:
    context = "[Recovered durable user request]\n" + original
    if recovery_policy == "review_only":
        context += (
            "\n\n[Recovery policy: REVIEW ONLY. Use current Command read tools, prepare "
            "the audience count/checksum/sample plus proposed subject and body, state that "
            "nothing was sent, and stop for fresh Brandon approval. Do not call any mutation.]"
        )
    return context
```

Read the policy from `inbound.payload["local_metadata"]` when creating the internal `MessageEvent`. Copy it into the content-free claimed-run spool metadata so a reused provider and restart both retain the same policy. Do not merge `local_metadata` into the backend `start_run` request.

- [x] **Step 6: Run Task 3 tests and verify GREEN**

Run:

```bash
cd backend
PYTHONPATH=. /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_sydney_memory_provider.py tests/test_sydney_spool.py \
  tests/test_sydney_recovery.py tests/test_hermes_overlay.py
```

Expected: all selected tests pass.

- [x] **Step 7: Commit Task 3**

```bash
git add hermes/overlay/sydney_gateway.py hermes/overlay/sydney_memory_provider.py \
  hermes/overlay/sydney_runtime.py backend/tests/test_sydney_memory_provider.py
git commit -m "fix(sydney): enforce review-only recovery"
```

### Task 4: Documentation, full verification, and review

**Files:**
- Modify: `hermes/README.md`
- Modify: `docs/deployment/hermes-railway.md`
- Modify: `tdtn.md`
- Modify: `memory.md`

- [x] **Step 1: Update operator and project documentation**

Document the managed skill source/destination/hash proof; the exact dry-run and `--enqueue` recovery commands with selectors supplied at action time and no prompt content; `review_only` allowed/blocked behavior; idempotent replay and rollback; no `/new` requirement; and the fact that historical wording does not approve sending.

- [x] **Step 2: Run static and secret checks**

Run:

```bash
git diff --check
if git grep -n -E '(RAILWAY_API_TOKEN|AGENT_CONTROL_TOKEN)=[^$[:space:]]+' -- \
  hermes backend docs tdtn.md memory.md; then exit 1; fi
python3 -m compileall -q hermes/overlay hermes/atlas_backend_mcp.py
```

Expected: `git diff --check` and compileall exit zero; the secret scan returns no matches.

- [x] **Step 3: Run the focused and changed-area test matrices**

Run:

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:5432/test \
  GEMINI_API_KEY=test-only-key PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_sydney_spool.py \
  tests/test_sydney_memory_provider.py \
  tests/test_sydney_backfill.py \
  tests/test_sydney_recovery.py \
  tests/test_sydney_context_e2e.py \
  tests/test_atlas_backend_mcp.py \
  tests/test_hermes_overlay.py \
  tests/test_verify_atlas_tools.py
```

Expected: zero failures; record exact pass/skip counts.

- [x] **Step 4: Verify exact overlay idempotence against the pinned template**

Use the existing complete-clone workflow or local detached checkout, run `apply_overlay.py` twice, and assert the second run changes no bytes. Then execute `hermes/verify_atlas_tools.py` locally and require exactly 25 ordered unique tools with no forbidden tools.

- [x] **Step 5: Review the implementation against the design**

Check every acceptance criterion in `docs/superpowers/specs/2026-08-26-sydney-command-recovery-skill-design.md`, inspect the complete diff, and fix any uncovered issue test-first.

- [x] **Step 6: Commit documentation and verification evidence**

```bash
git add hermes/README.md docs/deployment/hermes-railway.md tdtn.md memory.md
git commit -m "docs: add Sydney recovery runbook"
```

### Task 5: PR, merge, Atlas deployment, and guarded production recovery

**Files:**
- No new source files unless production evidence reveals a tested defect.
- Update: `tdtn.md`, `memory.md`, and the implementation plan checkboxes with final evidence.

- [x] **Step 1: Re-run final verification immediately before PR**

Run the exact Task 4 static, focused-test, overlay-idempotence, and 25-tool commands again from the clean candidate commit. Confirm no uncommitted changes other than final evidence notes.

- [x] **Step 2: Push the branch and open a focused PR**

```bash
git push origin codex/sydney-durable-context
gh pr create \
  --base main \
  --head codex/sydney-durable-context \
  --title "Fix Sydney Command routing and guarded recovery" \
  --body-file /private/tmp/sydney-command-recovery-pr.md
```

The PR body must summarize the stale-skill root cause, managed installation, exact recovery admission, review-only enforcement, test evidence, and zero-send boundary without including Brandon's prompt or credentials.

- [x] **Step 3: Wait for required checks and merge SHA-safely**

Confirm all required checks pass, re-read the PR head SHA, then merge with head matching. Do not merge a stale or changed head.

- [x] **Step 4: Verify the Atlas deployment and live skill**

Wait for the `atlas-agent` Railway deployment from merged `main` to report success. Verify public health and run live in-container JSON-RPC `tools/list`; require the unchanged exact 25-tool contract. Hash the deployed skill and compare it with the manifest; inspect only the required/forbidden phrases, not private user data.

- [x] **Step 5: Run the exact production recovery dry-run**

Resolve Brandon's original unfinished state row by content hash and existing evidence without printing its text. Run:

```bash
python -m plugins.memory.sydney.sydney_recovery \
  --state-db /data/.hermes/state.db \
  --spool /data/.hermes/sydney_spool.db \
  --session-id "$RECOVERY_SESSION_ID" \
  --message-id "$RECOVERY_MESSAGE_ID" \
  --expected-content-sha256 "$RECOVERY_CONTENT_SHA256"
```

Expected content-free result: `eligible=true`, `enqueued=false`, `recovery_policy=review_only`, and no spool mutation.

- [ ] **Step 6: Enqueue once and wait for terminal completion**

Repeat the exact command with `--enqueue`. Poll durable run state without resending. Require one run, one final assistant event, and a successful terminal state. If a tool policy denial occurs, verify it is recorded and that Sydney still returns the review packet.

- [ ] **Step 7: Prove Command usage and zero mutation**

Verify the recovered run used `command_contact_audience_preview` and, if needed, `command_contacts_search`; verify the audience count/checksum/reference are current; verify no `contacts_search`, Drive roster read, admin-UI fetch, Gmail draft/send, Docs/Sheets write, calendar mutation, or CRM mutation occurred. Confirm context health is `ready`, reconciliation lag is zero, and Atlas remains healthy.

- [ ] **Step 8: Record exact production evidence and complete the work**

Update `tdtn.md`, `memory.md`, and this plan with merge commit, deployment ID, live skill hash, tools/list result, recovery run state, Command tool evidence, and zero-mutation evidence. Commit and merge that evidence-only documentation follow-up if needed. Preserve all durable history and spool evidence; remove only temporary local proof files.

---

## Rollback

1. Disable legacy recovery admission by not invoking the explicit CLI; no background scanner exists.
2. Disable Sydney retry if the recovered run must stop; do not delete its original event or spool record.
3. Roll Atlas back to the prior healthy image if skill installation or runtime hooks fail.
4. The previous skill is not restored automatically because it contains the confirmed stale routing rule; rollback must keep the managed skill fail-closed or disable Sydney until a corrected image is available.
5. Never delete `state.db`, `sydney_spool.db`, canonical context rows, or reconciliation proof during rollback.
