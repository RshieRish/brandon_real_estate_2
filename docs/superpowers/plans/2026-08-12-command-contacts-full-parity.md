# Command Contacts Full-Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconstruct every recoverable Command contact and all eight captured contact views as a truthful, usable Sold With Sweeney CRM workspace while preserving 317 capture positions and 317 unique upstream provider identities, retaining all 51 lead-backed contacts and every `lead_id`, recognizing the two strong verified overlaps, preserving 49 legacy-only contacts, repairing rather than blindly deleting stale normalized rows, and never inventing birthday or anniversary data.

**Architecture:** A pure `ContactsParser` converts the immutable, checksum-verified archive into provenance records for provider contact rows, capture positions, the eight-view matrix, and exposed child occurrences. A transactional contact materializer resolves strong source identities into additive contact/profile tables and source links; focused FastAPI services then aggregate recovered evidence with internal CRM, lead, booking, task, SmartPlan, opportunity, note, and saved-search records without text-based duplication. The Next.js contact directory and split detail workspace consume typed paginated APIs, show materialized rows and source-only occurrences distinctly, and expose capture quality and original artifacts through the shared Command evidence components.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 async, Alembic, PostgreSQL/SQLite test runtime, Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4, Phosphor icons, Vitest/jsdom/Testing Library, Playwright/axe.

---

## Scope and non-negotiable truth gates

The operator supplies the authorized archive root without committing a user-specific local path:

```text
COMMAND_ARCHIVE_ROOT=<absolute-path-to-authorized-account-archive>
PROJECT_PYTHON=<absolute-path-to-project-venv-python>
# PLANNED TASK 4 ONLY — NOT ACCEPTED BY THE CURRENT CLI:
CONTACT_OVERLAP_MANIFEST=<absolute-path-to-private-reviewed-overlap-manifest>
```

These are operator inputs, not application runtime dependencies or frontend assets. Tests use synthetic fixtures; the real-archive gate receives `COMMAND_ARCHIVE_ROOT` explicitly, while Contacts reconciliation receives the private manifest explicitly only when selected.

The contacts import is accepted only when one apply run records all of these values:

```json
{
  "capture_positions": 317,
  "provider_contact_rows": 317,
  "unique_upstream_provider_ids": 317,
  "distinct_recovered_identities": 317,
  "normalized_recovered_contacts": 317,
  "identity_aliases_coalesced": 0,
  "preexisting_contact_rows": 362,
  "stale_source_normalized_rows": 313,
  "stale_source_normalized_leadless_rows": 311,
  "lead_backed_contacts": 51,
  "strong_verified_overlaps": 2,
  "legacy_only_contacts": 49,
  "legacy_lead_ids_preserved": 51,
  "recovered_contacts_created": 4,
  "reviewed_overlap_links_staged": 2,
  "source_entity_links_created_by_materializer": 315,
  "source_entity_links_final": 317,
  "expected_combined_contact_total": 366,
  "section_artifacts": 2536,
  "section_counts": {
    "timeline": 317,
    "opportunities": 317,
    "smart_plans": 317,
    "notes": 317,
    "saved_searches": 317,
    "tasks_to_do": 317,
    "tasks_completed": 317,
    "tasks_archived": 317
  },
  "ambiguous_identities": 0,
  "unmatched_provider_rows": 0,
  "fabricated_celebrations": 0
}
```

`expected_combined_contact_total == 366` is specific to the recovered production dataset: `317 recovered identities + 49 legacy-only`, with the two strong verified overlaps contained in both the 317 recovered and 51 lead-backed populations and therefore counted once in the combined directory. The service computes the union from source mappings and verified overlap links; it never deletes, rewrites, or invents a contact merely to force that number.

The existing database history is deliberately not an acceptance target: its 362 unique rows comprise 313 source-normalized rows and 51 lead-backed rows with two rows shared by both populations; 311 of the source-normalized rows are leadless. Those stale 313/311 rows remain auditable repair inputs. A repair run must map, adopt, split, or supersede them transactionally from immutable provenance; it must never delete them blindly. Every one of the 51 nonnull `lead_id` values and its contact row remains unchanged.

### Redacted identity-audit provenance

The production identity audit may be recorded only through counts, capture ordinals, and one-way hashes. It must not store raw names, emails, phone numbers, provider IDs, addresses, or timeline text in documentation or test fixtures.

- Archive truth: 317 capture positions, 317 unique upstream provider IDs, 317 resolved identities, zero aliases coalesced, and 2,536 canonical section captures.
- Internal overlap truth: 51 lead-backed contacts; exactly two recovered identities have separately verified strong email overlaps with that population; 49 lead-backed contacts are legacy-only.
- The five-placeholder evidence group is represented only as five capture ordinals or hashed provider/evidence-bundle references plus per-record field-presence categories. It is evidence for repairing the stale normalized history, never a reason to collapse five upstream IDs.
- The two verified overlaps are represented only as counts and salted/one-way evidence hashes. No private matching value appears in source control.
- Any acceptance artifact containing private values fails review and must be regenerated in redacted form.

A permissible production evidence shape is:

```json
{
  "placeholder_group": {
    "count": 5,
    "references": [
      {"capture_ordinal": "<redacted-ordinal-1>", "evidence_hash": "<sha256-1>", "present_fields": ["email"]},
      {"capture_ordinal": "<redacted-ordinal-2>", "evidence_hash": "<sha256-2>", "present_fields": []},
      {"capture_ordinal": "<redacted-ordinal-3>", "evidence_hash": "<sha256-3>", "present_fields": ["legal_name"]},
      {"capture_ordinal": "<redacted-ordinal-4>", "evidence_hash": "<sha256-4>", "present_fields": ["legal_name"]},
      {"capture_ordinal": "<redacted-ordinal-5>", "evidence_hash": "<sha256-5>", "present_fields": ["email"]}
    ]
  },
  "verified_overlaps": {
    "count": 2,
    "match_type": "strong_email",
    "evidence_hashes": ["<sha256-a>", "<sha256-b>"]
  }
}
```

The literal angle-bracket values above are documentation placeholders, not production evidence. The acceptance run substitutes only capture ordinals and nonreversible hashes generated from the immutable bundle; private identity values never enter the file.

### Private reviewed-overlap manifest contract

> **PLANNED TASK 4 CONTRACT — NOT AVAILABLE IN THE CURRENT CLI.** `--contact-overlap-manifest`, its loader/validator, reviewed-link staging, and the Contacts materializer do not exist yet. Until Task 4 lands and its gates pass, this section is a design contract only and every Contacts apply is blocked.

The two cross-system overlaps will be supplied at operation time through `--contact-overlap-manifest`; they are not fixtures, environment variables containing JSON, or values committed to the repository. The manifest is a private, access-controlled JSON file outside the checkout and outside any frontend/static path. The loader never emits its path or contents. Its canonical v1 schema is:

```json
{
  "schema_version": "command-contact-overlaps-v1",
  "bundle_fingerprint": "<64-lowercase-hex>",
  "parser_version": "contacts-v1",
  "rows": [
    {
      "source_provider_identity_hash": "<64-lowercase-hex-a>",
      "target_contact_id": "<positive-existing-crm-contact-id>",
      "target_contact_row_fingerprint": "<64-lowercase-hex-target-a>",
      "strong_evidence_hash": "<64-lowercase-hex-evidence-a>"
    },
    {
      "source_provider_identity_hash": "<64-lowercase-hex-b>",
      "target_contact_id": "<positive-existing-crm-contact-id>",
      "target_contact_row_fingerprint": "<64-lowercase-hex-target-b>",
      "strong_evidence_hash": "<64-lowercase-hex-evidence-b>"
    }
  ]
}
```

Production validation requires exactly two rows, two unique source hashes, and two unique positive `target_contact_id` values that already exist in `crm_contacts`. V1 has no alternate target key or implicit target-resolution path. Each target must have `lead_id IS NOT NULL`. Its row fingerprint is a domain-separated SHA-256 over non-PII concurrency fields (`contact_id`, `lead_id`, and the stored row version/timestamps) and must match again immediately before link creation, preventing target substitution or time-of-check/time-of-use drift without placing contact fields in the manifest. The source hash must resolve to exactly one of the 317 parsed provider identities. The service independently compares the source record and target contact using the approved strong-email rule and recomputes the domain-separated evidence hash; the manifest cannot authorize a name-only, weak, ambiguous, or conflicting match. The top-level fingerprint and parser version must exactly equal the current verified bundle and parser. Raw names, emails, phones, provider IDs, addresses, source payloads, and tokens are forbidden in the manifest schema, repository, CLI output, logs, exceptions, and acceptance evidence.

Preflight and dry-run load, canonicalize, fingerprint, and fully validate the private manifest against parsed source drafts plus the live 51 lead-backed contacts without writing source/entity links. Apply revalidates the approved manifest after the 317 source records have been persisted inside the Contacts module transaction. It then creates the two reviewed `CRMEntitySource` links and append-only contact audit events before invoking the materializer. The materializer adopts those two mappings, creates the remaining 315 source/entity links, and produces 317 final recovered mappings and 366 total contacts. A missing/malformed manifest, changed fingerprint/version, wrong row count, unresolved/non-lead-backed target, missing/ambiguous source, weak/conflicting evidence, or link conflict aborts and rolls back the whole Contacts module transaction. A resumed Contacts run must receive the same approved private file and repeat validation against the run fingerprint/version and exact source/target/evidence sets; only the canonical digest, row count, validation state, and audit/run IDs may be recorded on success.

The second apply of the same fingerprint/parser version must add zero rows to every contact-domain table, zero `crm_entity_sources` rows, zero source-artifact links, and must produce the identical reconciliation detail object.

### Eight-view ownership boundary

Contacts owns the source captures and the contact-facing presentation of:

1. Timeline
2. Opportunities
3. SmartPlans
4. Notes
5. Saved Searches
6. Tasks — To Do
7. Tasks — Completed
8. Tasks — Archived

Contacts materializes profiles, addresses, methods, ownership, neighborhoods, relationships, preferences, timeline events, notes, and saved-search observations. Standalone Tasks, SmartPlans, and Opportunities remain authoritative for their domain entities. Until those domain plans link a captured occurrence to a normalized record, the contact tab renders the parsed occurrence as `source_only`; it is visible and downloadable but cannot be mutated as if it were a normalized internal record. Later domain materializers attach the same source record through `crm_entity_sources` without changing the contact API or creating another occurrence.

### Birthday and anniversary rule

- Existing SWS-native `crm_contacts.birthday` and `crm_contacts.anniversary` values remain untouched by archive import.
- Recovered month, day, year, raw source value, and year quality live in `crm_contact_profiles`.
- A source year of `1900` is stored as raw evidence with `year_quality="sentinel"`; it is never displayed or returned as a verified birth year.
- Month/day may be normalized only when both were explicitly exposed. Missing month/day remains `null`.
- Anniversary year is returned only when explicitly exposed and calendar-valid.
- The import never defaults a year, uses the current year, derives a date from a task name, or parses a tag such as `August Birthday` as a birth date.

## Deterministic identity rules

Provider record identity and normalized business identity are separate:

- `source_contact_id` is the 24-character lowercase ID extracted from the captured contact URL. Every one of the 317 provider rows gets its own `contact_profile` source record.
- `capture_ordinal` is the seven-digit directory position (`0000001` through `0000317`). Every position gets its own `contact_capture_position` rendered occurrence, and the audited production bundle has a one-to-one position/provider-ID relationship.
- A normalized `CRMContact` may have multiple provider rows only after deterministic strong-identifier resolution, but the audited production source has zero such coalesced aliases. Cross-system overlap with a lead-backed internal contact is recorded as a source link, not as a provider-row alias.

`resolve_identity_clusters()` applies this order:

1. Reuse an existing `crm_entity_sources` mapping for the same provider source record.
2. Reuse a previously stored `CRMContactCapturePosition.contact_id` for the same source contact ID and bundle lineage.
3. Cluster recovered rows by the same normalized primary email only when their nonblank legal/preferred names are compatible and their nonblank E.164 phones do not conflict.
4. If no email is present, cluster by the same explicit E.164 phone only when their nonblank legal/preferred names are compatible.
5. Otherwise use the provider contact ID as a one-member identity cluster.

Names are confirmation signals, never merge keys. Local/national phone numbers that cannot be normalized without assuming a country are not merge keys. Placeholder emails, blank strings, `--`, and vendor overlay text are null. A conflicting strong identifier produces an `IdentityConflict`, increments `ambiguous_identities`, and blocks apply; it is never resolved by taking the first row.

To attach to pre-existing rows without duplication:

- a current, unambiguous source/entity mapping wins;
- after the source records exist inside the Contacts apply transaction, the reviewed-overlap service may stage exactly one source/entity link for each identity backed by the private strong-evidence manifest; the audited production manifest contains exactly two such links to lead-backed contacts;
- otherwise one `lead_id IS NULL` contact with the exact recovered identity hash and compatible fields may be adopted;
- zero matches creates a recovered contact;
- multiple matches block apply;
- an unreviewed or unmapped `lead_id IS NOT NULL` contact is never auto-merged from raw email, phone, or name. Only an explicit reviewed link staged from the validated private manifest may attach a recovered source to a lead-backed contact; adoption does not change `lead_id` or any legacy contact field. The other 49 lead-backed contacts remain legacy-only and may be shown as probable duplicates for manual review.

The identity hash is SHA-256 over a versioned canonical tuple such as `contacts-v1\0email\0avery@example.com`; raw email/phone values remain only in private contact tables and provenance payloads.

## Archive parsing precedence

For each position, the parser uses these sources in order and links all contributing artifacts:

1. `kw_command_repaired/contacts/nested/<ordinal>/contact.json` for structured profile fields when present.
2. `kw_command_repaired/contacts/details/<ordinal>.html` for embedded/visible profile fields.
3. The canonical section JSON path from the table below, using `visible_text` when present and `accessibility_snapshot` otherwise.
4. Matching `.html`, `.txt`, and `.snapshot.txt` files are supporting evidence, not duplicate business records.

The eight canonical section JSON files are mandatory for all 317 positions. The 316 `comprehensive-capture.json` files are audit manifests, not the completeness source. Vendor help, notification, AI disclaimer, messaging-limit, and modal boilerplate is stripped before any field/row parser runs.

| Internal section name | Exact archive-relative path below `sections/<ordinal>/` |
|---|---|
| `timeline` | `timeline.json` |
| `opportunities` | `opportunities.json` |
| `smart_plans` | `smartplans.json` |
| `notes` | `notes.json` |
| `saved_searches` | `saved_searches.json` |
| `tasks_to_do` | `tasks/to_do.json` |
| `tasks_completed` | `tasks/completed.json` |
| `tasks_archived` | `tasks/archived.json` |

The parser normalizes only the internal section name; it never guesses the physical filename. Inventory validation must find each exact path 317 times before parsing.

Source keys are stable and version-independent:

```text
contact:<source_contact_id>
position:<capture_ordinal>
position:<capture_ordinal>:section:<section_name>
contact:<source_contact_id>:timeline:<event_key>
contact:<source_contact_id>:note:<note_id_or_occurrence_hash>
contact:<source_contact_id>:saved-search:<search_id_or_occurrence_hash>
contact:<source_contact_id>:task:<state>:<task_id_or_occurrence_hash>
contact:<source_contact_id>:smart-plan:<plan_id_or_occurrence_hash>
contact:<source_contact_id>:opportunity:<opportunity_id_or_occurrence_hash>
```

An occurrence hash is SHA-256 over canonical parsed values plus the ordinal-within-section, never over the entire HTML body and never over display title alone.

## File responsibility map

### Backend domain and migration

- Create `backend/models/command_contacts.py`: focused profile, method, address, neighborhood, ownership, relationship, preference, capture-position, section-capture, recovered timeline-event, and contact-audit models.
- Modify `backend/models/__init__.py`: export contact-domain models.
- Modify `backend/alembic/env.py`: register the contact model module.
- Create `backend/alembic/versions/4a8c0d1e2f3b_add_command_contact_parity.py`: additive schema whose parent is the then-current `2e7f9a0b1c2d`; after this migration lands, `4a8c0d1e2f3b` is the sole head and operators must upgrade through it.
- Create `backend/tests/test_command_contacts_models.py`: constraints and model defaults.
- Create `backend/tests/test_command_contacts_migration.py`: real SQLite upgrade/downgrade plus PostgreSQL SQL compilation.

### Parser, materializer, and reconciliation

- Create `backend/services/command_parsers/contact_extractors.py`: canonical URL, snapshot, profile, date, and section-row extraction.
- Create `backend/services/command_parsers/contacts.py`: pure `ContactsParser` and exact metrics/details.
- Modify `backend/services/command_parsers/__init__.py`: register/export Contacts.
- Create `backend/services/command_contact_identity.py`: canonical identifiers, cluster resolution, and conflicts.
- Create `backend/services/command_contact_overlap_manifest.py`: private manifest schema/loader, canonical digest, strong-evidence validation, and audited two-link staging.
- Create `backend/services/command_contact_materializer.py`: idempotent normalized writes and entity-source links.
- Create `backend/services/command_materializers/base.py`: small generic materializer protocol/registry used by later domains.
- Create `backend/services/command_materializers/__init__.py`: default registry with Contacts.
- Modify `backend/services/command_reconciliation.py`: validate the Contacts manifest during dry-run; during apply persist source records, stage reviewed links, invoke the materializer, and commit or roll back as one module transaction.
- Modify `backend/scripts/reconcile_command_archive.py`: add `--contact-overlap-manifest`, Contacts apply requirement, private preflight, and redacted JSON output.
- Create `backend/tests/fixtures/command_contacts/`: synthetic, non-production structured/visible/accessibility captures covering duplicates, yearless celebrations, empty tabs, and partial captures.
- Create `backend/tests/test_command_contacts_parser.py`: parser/source-record/matrix/date tests.
- Create `backend/tests/test_command_contact_identity.py`: strong-identity and conflict tests.
- Create `backend/tests/test_command_contact_overlap_manifest.py`: private schema, exact-two, fingerprint/version, strong-evidence, redaction, staging, and rollback tests.
- Create `backend/tests/test_command_contact_materializer.py`: real async SQLite import/idempotency/legacy-preservation tests.
- Create `backend/tests/test_command_contacts_archive_gate.py`: opt-in real-archive gate for 317 positions, 317 unique provider IDs, 317 resolved identities, zero coalesced aliases, and 2,536 sections.
- Modify `backend/tests/test_command_reconciliation.py`: materializer transaction, failure, resume, and no-materializer regression cases.
- Modify `backend/tests/test_reconcile_command_archive_cli.py`: Contacts manifest requirement, preflight/dry-run/resume, digest, and no-private-output tests.

### Backend query/API boundary

- Modify `backend/models/command.py`: add nullable, uniquely indexed provenance from `CRMActivity` to a recovered source record.
- Modify `backend/models/command_contacts.py`: add contact/source-occurrence ownership and permit recovered timeline rows with no exposed timestamp.
- Create `backend/alembic/versions/5b9d1e2f3a4c_add_contact_occurrence_context.py`: additive occurrence/activity/timeline migration whose parent is `4a8c0d1e2f3b`.
- Create `backend/services/command_contact_contracts.py`: framework-neutral directory, detail, section, evidence, timeline, celebration, bulk, audit, filter, and sort contracts shared by query services.
- Create `backend/services/command_contact_occurrences.py`: validate and idempotently persist child-occurrence ownership from parser payload context.
- Create `backend/services/command_contact_timeline.py`: typed merge of recovered timeline events, `CRMActivity`, leads, and bookings with source-key dedupe.
- Create `backend/services/command_contacts.py`: directory/detail/tab queries, stable pagination, mutations, and audits.
- Create `backend/schemas/command_contacts.py`: request/response/page/evidence contracts.
- Create `backend/routers/command_contacts.py`: admin-only focused contact routes.
- Modify `backend/routers/command.py`: remove moved contact, contact-note, tag-assignment, contact-saved-search, and celebration handlers; retain unrelated routes.
- Modify `backend/routers/command_provenance.py`: allow contact extension entity types.
- Modify `backend/main.py`: mount `command_contacts.router` under `/api/v1/command`.
- Create `backend/tests/test_command_contact_contracts.py`: exact filters, sorts, SmartViews, cursors, bulk variants, and redaction contracts.
- Create `backend/tests/test_command_contact_occurrences.py`: occurrence ownership, backfill, idempotency, and ambiguity gates.
- Create `backend/tests/test_command_contact_timeline.py`: deterministic aggregation and non-duplication.
- Create `backend/tests/test_command_contacts_service.py`: directory/detail/section/evidence/celebration/mutation query tests.
- Create `backend/tests/test_command_contacts_router.py`: authenticated page/detail/tab/mutation/evidence integration tests.
- Modify `backend/tests/test_command_models.py`: retain compatibility coverage for legacy Command entities.

### Frontend typed client and directory

- Create `frontend/src/lib/command/http.ts`: shared authenticated JSON/blob transport, typed HTTP errors, response decoding, and `AbortSignal` support.
- Create `frontend/src/lib/command/http.test.ts`: authentication, error, malformed-response, blob, and abort tests.
- Create `frontend/src/lib/command/contacts.ts`: contact types, page/filter/sort state, route builders, and contact API methods.
- Create `frontend/src/lib/command/contacts.test.ts`: encoding and response-contract tests.
- Modify `frontend/src/lib/command/api.ts`: re-export contact types and keep the `commandApi.contacts(limit, offset, filters)` array contract for Home/Tasks while exposing `contactDirectory()` for full metadata.
- Modify `frontend/src/lib/command/api.test.ts`: compatibility adapter and new endpoint assertions.
- Replace `frontend/src/components/command/ContactsWorkspace.tsx`: dense directory composition using shared module/table/state/evidence primitives.
- Create `frontend/src/components/command/contacts/ContactsToolbar.tsx`: search, SmartViews, filters, column controls, and add/bulk actions.
- Create `frontend/src/components/command/contacts/ContactsTable.tsx`: stable columns, evidence badges, selection, activation, and pagination.
- Create `frontend/src/components/command/contacts/ContactCreateDrawer.tsx`: internal-contact creation in the shared overlay.
- Create `frontend/src/components/command/contacts/ContactsWorkspace.test.tsx`: component states, filters, keyboard, and bulk behavior.
- Modify `frontend/src/components/command/shell/CommandShell.tsx`: mount the shared toast provider around every Command route.
- Modify `frontend/src/components/command/shell/CommandShell.test.tsx`: prove workspace toasts render without a missing-provider error.
- Modify `frontend/src/app/admin/command/command-shell.css`: add scoped directory/toolbar/table/drawer/responsive styles.
- Modify `frontend/src/app/admin/command/contacts/page.tsx`: route-only wrapper.

### Frontend contact detail

- Create `frontend/src/components/command/contacts/ContactDetailWorkspace.tsx`: split canvas, navigation, tab routing, and state orchestration.
- Create `frontend/src/components/command/contacts/ContactProfilePanel.tsx`: identity, health, owner/assignee, methods, tags, profile fields, and observed map.
- Create `frontend/src/components/command/contacts/ContactObservedMap.tsx`: coordinate/address display using existing server-mediated map/static-map behavior; no client key.
- Create `frontend/src/components/command/contacts/ContactDetailTabs.tsx`: ARIA tabs for the eight captured views plus SWS-native Bookings.
- Create `frontend/src/components/command/contacts/ContactTimelineTab.tsx`.
- Create `frontend/src/components/command/contacts/ContactOpportunitiesTab.tsx`.
- Create `frontend/src/components/command/contacts/ContactSmartPlansTab.tsx`.
- Create `frontend/src/components/command/contacts/ContactTasksTab.tsx`.
- Create `frontend/src/components/command/contacts/ContactNotesTab.tsx`.
- Create `frontend/src/components/command/contacts/ContactSavedSearchesTab.tsx`.
- Create `frontend/src/components/command/contacts/ContactCaptureEvidence.tsx`: capture positions, upstream provider identities, internal verified-overlap evidence, zero-alias status, section matrix, limitations, and authenticated artifact links.
- Modify `frontend/src/components/command/ContactActions.tsx`: render in the shared light workspace and refresh only the affected tab.
- Modify `frontend/src/components/command/ContactProfileEditor.tsx`: edit SWS-owned fields without overwriting recovered observations.
- Replace `frontend/src/app/admin/command/contacts/[contactId]/page.tsx`: route-only detail wrapper.
- Create `frontend/src/components/command/contacts/ContactDetailWorkspace.test.tsx`: eight-view, evidence, celebration, source-only, and navigation coverage.

### Browser, visual, and production gates

- Create `frontend/e2e/command-contacts.spec.ts`: desktop directory/detail journeys and eight-view coverage.
- Create `frontend/e2e/command-contacts-mobile.spec.ts`: responsive split/detail navigation and touch/focus checks.
- Create `frontend/e2e/command-contacts-accessibility.spec.ts`: axe, keyboard, tab, drawer, grid, and status announcements.
- Create `frontend/e2e/command-contacts-visual.spec.ts`: deterministic 1800×982, 1793×1166, and 390×844 snapshots.
- Modify `frontend/e2e/visual/command-reference-manifest.ts`: add only valid contact references and mark shell/error images as limitations.
- Modify `frontend/design-qa.md`: same-viewport contact comparison and brand-mask results.
- Modify `docs/command-reconciliation-runbook.md`: Contacts-specific dry-run/apply/resume/count/rollback commands.
- Create `docs/command-contacts-production-acceptance.md`: fingerprint, run IDs, SQL totals, authenticated smoke results, and screenshot evidence template populated during deployment.

## Dependency and commit order

1. Base contact schema and migration.
2. Pure parser/extractors.
3. Identity resolver and materializer protocol.
4. Contact materializer and reconciliation integration.
5. Additive query schema plus framework-neutral Contacts contracts.
6. Timeline aggregation.
7. Directory/detail/section/evidence query services.
8. Focused Contacts router with an explicit legacy-route inventory.
9. Shared typed frontend transport, Contacts client, and Home compatibility adapter.
10. Dense directory UI after the toast provider and shell styles are available.
11. Contact detail and eight views.
12. Browser/visual/production gates.

The Tasks, SmartPlans, and Opportunities domain imports depend on tasks 1–5 because they link their normalized entities to contact section source records. Contacts does not depend on those later materializers: it renders source-only occurrences truthfully until links exist.

---

### Task 1: Add the additive contact parity schema

**Files:**
- Create: `backend/models/command_contacts.py`
- Modify: `backend/models/__init__.py`
- Modify: `backend/alembic/env.py`
- Create: `backend/alembic/versions/4a8c0d1e2f3b_add_command_contact_parity.py`
- Create: `backend/tests/test_command_contacts_models.py`
- Create: `backend/tests/test_command_contacts_migration.py`

- [ ] **Step 1: Write failing model and migration tests**

Define tests that assert the exact public tables and constraints:

```python
CONTACT_TABLES = {
    "crm_contact_profiles",
    "crm_contact_methods",
    "crm_contact_addresses",
    "crm_contact_neighborhoods",
    "crm_contact_ownerships",
    "crm_contact_relationships",
    "crm_contact_preferences",
    "crm_contact_capture_positions",
    "crm_contact_section_captures",
    "crm_contact_timeline_events",
    "crm_contact_audit_events",
}

def test_contact_parity_models_register_every_additive_table():
    assert CONTACT_TABLES <= set(Base.metadata.tables)

def test_capture_position_keeps_position_and_business_identity_separate():
    table = Base.metadata.tables["crm_contact_capture_positions"]
    assert {"capture_ordinal", "source_contact_id", "contact_id", "source_record_id"} <= set(table.c)
    assert "uq_crm_contact_capture_bundle_ordinal" in {c.name for c in table.constraints}

def test_contact_section_enum_is_database_constrained():
    checks = {c.name: str(c.sqltext) for c in Base.metadata.tables["crm_contact_section_captures"].constraints if c.name}
    assert "ck_crm_contact_section_name" in checks
    for value in ("timeline", "opportunities", "smart_plans", "notes", "saved_searches", "tasks_to_do", "tasks_completed", "tasks_archived"):
        assert value in checks["ck_crm_contact_section_name"]
```

The migration test must upgrade a real SQLite database from `2e7f9a0b1c2d`, assert all tables/indexes/checks, downgrade one revision, and assert only the new tables disappear. It must also compile PostgreSQL offline SQL and assert `ON DELETE RESTRICT` for provenance evidence and `ON DELETE CASCADE` only for owned contact children.

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contacts_models.py \
  tests/test_command_contacts_migration.py
```

Expected: FAIL because the contact extension models and revision do not exist.

- [ ] **Step 3: Implement focused models**

Use these model contracts; every JSON column is canonical text to match current project conventions:

```python
class CRMContactProfile(Timestamped, Base):
    __tablename__ = "crm_contact_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id", ondelete="CASCADE"), unique=True)
    recovered_identity_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    preferred_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    lead_source: Mapped[str | None] = mapped_column(String(255))
    account_name: Mapped[str | None] = mapped_column(String(255))
    health_score: Mapped[int | None] = mapped_column(Integer)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    birth_month: Mapped[int | None] = mapped_column(Integer)
    birth_day: Mapped[int | None] = mapped_column(Integer)
    birth_year: Mapped[int | None] = mapped_column(Integer)
    birth_year_quality: Mapped[str] = mapped_column(String(24), default="unknown")
    birth_raw: Mapped[str | None] = mapped_column(String(64))
    anniversary_month: Mapped[int | None] = mapped_column(Integer)
    anniversary_day: Mapped[int | None] = mapped_column(Integer)
    anniversary_year: Mapped[int | None] = mapped_column(Integer)
    anniversary_year_quality: Mapped[str] = mapped_column(String(24), default="unknown")
    anniversary_raw: Mapped[str | None] = mapped_column(String(64))
```

Implement the other ten tables with these exact owned fields in addition to `id`, `created_at`, and `updated_at` where `Timestamped` supplies them:

- `CRMContactMethod`: `contact_id`, nullable provenance `source_record_id`, `source_key`, `kind`, `label`, `raw_value`, `normalized_value`, and `is_primary`; constrain `kind` to `email | phone` and index `(kind, normalized_value)`.
- `CRMContactAddress`: `contact_id`, nullable provenance `source_record_id`, `source_key`, `address_type`, `line1`, `line2`, `city`, `state`, `postal_code`, `country`, `formatted`, `latitude`, `longitude`, and `is_primary`; use `Numeric(10, 7)`/`Numeric(10, 7)` coordinates and enforce latitude `-90..90` and longitude `-180..180` when present.
- `CRMContactNeighborhood`: `contact_id`, nullable provenance `source_record_id`, `source_key`, `name`, `latitude`, and `longitude`, with the same coordinate types/checks.
- `CRMContactOwnership`: `contact_id`, nullable provenance `source_record_id`, `source_key`, `role`, `provider_actor_id`, `display_name`, and `is_primary`; constrain `role` to `owner | assignee | collaborator`.
- `CRMContactRelationship`: `contact_id`, nullable provenance `source_record_id`, `source_key`, `relationship_type`, `display_name`, `related_source_contact_id`, and nullable `related_contact_id`; use `SET NULL` only for `related_contact_id` so deleting the related party does not delete the observation.
- `CRMContactPreference`: `contact_id`, nullable provenance `source_record_id`, `source_key`, `preference_key`, and canonical `value_json` text.
- `CRMContactCapturePosition`: `contact_id`, required provenance `source_record_id`, `bundle_fingerprint`, integer `capture_ordinal`, `source_contact_id`, `captured_at`, `capture_quality`, and canonical `limitations_json`; constrain ordinal positive, provider ID to 24 lowercase hexadecimal characters, and quality to `complete | partial | shell | error`.
- `CRMContactSectionCapture`: `capture_position_id`, required provenance `source_record_id`, `section_name`, `captured_at`, `capture_quality`, `is_empty`, `row_count`, and canonical `limitations_json`; constrain row count nonnegative and quality to the same four values.
- `CRMContactTimelineEvent`: `contact_id`, required provenance `source_record_id`, `source_system`, `source_event_key`, `kind`, `outcome`, `title`, `body`, `actor_label`, `channel`, `occurred_at`, and canonical `attributes_json`.
- `CRMContactAuditEvent`: `contact_id`, `actor_subject`, `action`, canonical `before_json`, canonical `after_json`, and `created_at`; this is append-only and has no `updated_at`.

Every recovered observation FK to the existing `crm_source_records.id` provenance table uses `ON DELETE RESTRICT`. Every owned child `contact_id` FK uses `ON DELETE CASCADE`; `capture_position_id` cascades only to its eight owned section rows. Add checks for score `0..100`, month `1..12`, day `1..31`, and year quality `verified | yearless | sentinel | unknown`. Method/address/neighborhood/ownership/relationship/preference tables use `(contact_id, source_key)` unique constraints. Capture tables use:

```python
UniqueConstraint("bundle_fingerprint", "capture_ordinal", name="uq_crm_contact_capture_bundle_ordinal")
UniqueConstraint("bundle_fingerprint", "source_contact_id", name="uq_crm_contact_capture_bundle_source")
UniqueConstraint("source_record_id", name="uq_crm_contact_capture_source_record")
UniqueConstraint("capture_position_id", "section_name", name="uq_crm_contact_position_section")
UniqueConstraint("source_record_id", name="uq_crm_contact_section_source_record")
```

`CRMContactTimelineEvent` has unique `(source_system, source_event_key)` and unique `source_record_id`. Add indexes for capture lookup `(contact_id, bundle_fingerprint)`, section lookup `(capture_position_id, section_name)`, timeline order `(contact_id, occurred_at, id)`, and audit order `(contact_id, created_at, id)`. Model tests must instantiate every table, prove check/unique/FK failures against SQLite with foreign keys enabled, and prove canonical JSON serialization is stable.

- [ ] **Step 4: Write the additive Alembic revision**

Use revision `4a8c0d1e2f3b`, `down_revision = "2e7f9a0b1c2d"`, create the eleven tables in parent-before-child order, and drop them in exact reverse order. Do not rename, rewrite, or populate `crm_contacts`, `leads`, or any provenance table in this migration.

- [ ] **Step 5: Run migration/model regressions**

Run:

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contacts_models.py \
  tests/test_command_contacts_migration.py \
  tests/test_command_provenance_models.py \
  tests/test_command_provenance_migration.py
"$PROJECT_PYTHON" -m alembic heads
```

Expected: PASS; Alembic prints only `4a8c0d1e2f3b (head)`.

- [ ] **Step 6: Commit**

```bash
git add backend/models/command_contacts.py backend/models/__init__.py backend/alembic/env.py \
  backend/alembic/versions/4a8c0d1e2f3b_add_command_contact_parity.py \
  backend/tests/test_command_contacts_models.py backend/tests/test_command_contacts_migration.py
git commit -m "feat: add Command contact parity schema"
```

### Task 2: Parse the provider rows and complete eight-view matrix

**Files:**
- Create: `backend/services/command_parsers/contact_extractors.py`
- Create: `backend/services/command_parsers/contacts.py`
- Modify: `backend/services/command_parsers/__init__.py`
- Create: `backend/tests/fixtures/command_contacts/`
- Create: `backend/tests/test_command_contacts_parser.py`
- Create: `backend/tests/test_command_contacts_archive_gate.py`

- [ ] **Step 1: Create synthetic fixtures with no production PII**

Build three positions under `backend/tests/fixtures/command_contacts/kw_command_repaired/contacts/sections/`, using the exact physical paths in the archive mapping table (`smartplans.json` and nested `tasks/{to_do,completed,archived}.json`, not normalized filenames):

- position 1: structured profile, explicit email/phone, `1900-08-30` birth sentinel, verified anniversary, nonempty timeline/note/tasks;
- position 2: same strong email as position 1 and compatible name, accessibility-snapshot fallback, empty notes/searches;
- position 3: no email/normalizable phone, yearless birthday, partial Opportunities capture.

Each position must have exactly the eight canonical JSON paths. Supporting HTML/text artifacts may repeat the same content and must not create additional section records.

- [ ] **Step 2: Write failing extractor/parser tests**

Pin these public contracts:

```python
CONTACT_SECTIONS = (
    "timeline", "opportunities", "smart_plans", "notes", "saved_searches",
    "tasks_to_do", "tasks_completed", "tasks_archived",
)

def test_extract_source_contact_id_requires_canonical_contact_url():
    assert extract_source_contact_id("https://console.command.kw.com/command/contacts/deadbeefdeadbeefdeadbeef?page=2") == "deadbeefdeadbeefdeadbeef"
    with pytest.raises(ContactParseError):
        extract_source_contact_id("https://example.com/contacts/not-an-id")

def test_parser_emits_one_profile_one_position_and_eight_sections_per_position(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    kinds = Counter(record.record_kind for record in result.records)
    assert kinds["contact_profile"] == 3
    assert kinds["contact_capture_position"] == 3
    assert kinds["contact_section_capture"] == 24

def test_parser_marks_1900_birth_year_as_sentinel_without_inventing_a_date(bundle):
    profile = source_record(result, "contact:deadbeefdeadbeefdeadbeef")
    assert profile.payload["birthday"] == {
        "month": 8, "day": 30, "year": None,
        "year_quality": "sentinel", "raw": "1900-08-30",
    }

def test_parser_does_not_treat_supporting_html_and_text_as_extra_occurrences(bundle):
    assert Counter(r.record_kind for r in result.records)["contact_section_capture"] == 24
```

Also assert boilerplate stripping, visible-text/accessibility extraction, deterministic occurrence hashes, empty-state payloads, partial/error capture quality, canonical artifact links, parser-version propagation, stable ordering, and duplicate-ordinal/missing-section hard failures.

- [ ] **Step 3: Run focused tests and confirm RED**

Run:

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q tests/test_command_contacts_parser.py
```

Expected: FAIL because the Contacts parser modules do not exist.

- [ ] **Step 4: Implement pure extractors**

Expose this typed value:

```python
@dataclass(frozen=True, slots=True)
class ParsedCelebration:
    month: int | None
    day: int | None
    year: int | None
    year_quality: Literal["verified", "yearless", "sentinel", "unknown"]
    raw: str | None

```

Implement these exact function contracts: `extract_source_contact_id(url: str) -> str`, `strip_application_boilerplate(text: str) -> str`, `parse_contact_profile(ordinal: int, artifacts: Mapping[str, ArchiveArtifactInput]) -> ParsedContactProfile`, `parse_section_capture(profile: ParsedContactProfile, section: str, artifact: ArchiveArtifactInput) -> ParsedSection`, and `canonical_occurrence_key(values: Mapping[str, object], ordinal: int) -> str`.

`parse_contact_profile()` uses structured JSON first and fallbacks second. It must distinguish absent values from displayed `--`, preserve raw values, and never parse application overlays after the stripped boundary.

- [ ] **Step 5: Implement `ContactsParser` and pre-resolution metrics**

Register `module = "contacts"`. Emit one provider profile, one capture position, eight section records, and child source records actually exposed by each section. Use observed-record evidence only for stable provider/note IDs; visible rows without stable IDs are rendered occurrences.

Return:

```python
ModuleMetrics(
    source_system="kw_command",
    module="contacts",
    expected_count=317,
    observed_count=provider_row_count,
    rendered_count=position_count,
    normalized_count=0,
    evidence_only_count=0,
    unmatched_count=0,
    duplicate_content_count=duplicate_supporting_body_count,
    error_count=0,
    details={
        "provider_contact_rows": provider_row_count,
        "capture_positions": position_count,
        "section_artifacts": section_count,
        "section_counts": section_counts,
        "fabricated_celebrations": 0,
    },
)
```

The parser emits deterministic identity-candidate payloads but performs no clustering or database writes in this task. Task 3 integrates the resolver and replaces `observed_count` with the resolved identity count before materialization can run.

- [ ] **Step 6: Add the opt-in real-archive gate**

The test must skip only when `COMMAND_ARCHIVE_ROOT` is absent. When present, load the immutable artifact inventory, run checksum verification, parse Contacts, and assert 317 provider rows, 317 unique provider IDs, 317 capture positions, 2,536 section records, 317 records for every section, zero unmatched rows, zero coalesced aliases, and zero fabricated celebrations. Task 3 adds the deterministic 317-identity assertion after the identity resolver exists.

Run:

```bash
cd backend
COMMAND_ARCHIVE_ROOT="$COMMAND_ARCHIVE_ROOT" \
  "$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contacts_archive_gate.py
```

Expected: PASS with 317 provider rows/positions, 2,536 section records, and 317 for every section.

- [ ] **Step 7: Run parser/provenance regressions and commit**

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contacts_parser.py \
  tests/test_command_parser_registry.py \
  tests/test_command_provenance_service.py
git add services/command_parsers tests/fixtures/command_contacts \
  tests/test_command_contacts_parser.py tests/test_command_contacts_archive_gate.py
git commit -m "feat: parse recovered Command contacts"
```

### Task 3: Resolve identities without name-only merges

**Files:**
- Create: `backend/services/command_contact_identity.py`
- Create: `backend/tests/test_command_contact_identity.py`
- Modify: `backend/services/command_parsers/contacts.py`
- Modify: `backend/tests/test_command_contacts_parser.py`
- Modify: `backend/tests/test_command_contacts_archive_gate.py`

- [ ] **Step 1: Write failing resolver tests**

Cover the rules directly:

```python
def test_same_email_and_compatible_names_form_one_cluster():
    clusters = resolve_identity_clusters((profile("a", email="Avery@Example.com", name="Avery Lake"), profile("b", email="avery@example.com", name="Avery Lake")))
    assert [cluster.source_contact_ids for cluster in clusters] == [("a", "b")]

def test_same_name_without_strong_identifier_never_merges():
    clusters = resolve_identity_clusters((profile("a", name="Jordan Lee"), profile("b", name="Jordan Lee")))
    assert len(clusters) == 2

def test_shared_email_with_conflicting_phone_blocks_apply():
    with pytest.raises(IdentityConflict, match="conflicting phone"):
        resolve_identity_clusters((profile("a", email="a@example.com", phone="+19785550101"), profile("b", email="a@example.com", phone="+19785550102")))

def test_non_e164_phone_is_preserved_but_not_used_as_merge_key():
    assert canonical_phone("978-555-0101") is None
```

Also test placeholder stripping, Unicode/case normalization, compatible missing fields, stable SHA-256 identity hashes, source-order independence, and one source ID appearing in only one cluster.

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd backend && "$PROJECT_PYTHON" -m pytest -q tests/test_command_contact_identity.py`

Expected: FAIL because the resolver is missing.

- [ ] **Step 3: Implement immutable identity contracts**

```python
@dataclass(frozen=True, slots=True)
class ContactIdentityCandidate:
    source_contact_id: str
    primary_email: str | None
    e164_phone: str | None
    legal_name: str | None
    preferred_name: str | None

@dataclass(frozen=True, slots=True)
class ContactIdentityCluster:
    identity_hash: str
    resolution_method: Literal["email", "phone", "provider_id"]
    source_contact_ids: Sequence[str]

class IdentityConflict(ValueError):
    """Raised when strong identity evidence conflicts across source contacts."""
```

Implement `resolve_identity_clusters(candidates: Sequence[ContactIdentityCandidate]) -> Sequence[ContactIdentityCluster]`. Sort inputs and outputs canonically, validate that a provider ID is unique before grouping, and return tuples through both `Sequence`-typed boundaries so no mutable collections escape.

- [ ] **Step 4: Integrate the resolver into parser metrics**

Resolve the emitted candidates after all provider rows have parsed. Set `observed_count=distinct_identity_count`, add `identity_clusters` and `identity_aliases_coalesced` to `details`, and preserve `rendered_count=317`. Treat every `IdentityConflict` as a parser error with `ambiguous_identities > 0`; it must make verification/apply ineligible rather than silently falling back to provider IDs.

- [ ] **Step 5: Extend the real-archive gate to identity truth**

With `COMMAND_ARCHIVE_ROOT` set, assert exactly 317 identity clusters, zero aliases coalesced across the 317 unique provider IDs, zero ambiguous identities, and deterministic cluster hashes after reversing the artifact inventory. Record the five-placeholder evidence group only through capture ordinals or one-way evidence hashes and field-presence categories; record the two cross-system verified email overlaps only through counts/hashes. This converts the Task 2 archive test into the complete parser-side truth gate without checking private values into source control.

- [ ] **Step 6: Run tests and commit**

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contact_identity.py \
  tests/test_command_contacts_parser.py \
  tests/test_command_contacts_archive_gate.py
git add services/command_contact_identity.py services/command_parsers/contacts.py \
  tests/test_command_contact_identity.py tests/test_command_contacts_parser.py \
  tests/test_command_contacts_archive_gate.py
git commit -m "feat: resolve Command contact identities"
```

### Task 4: Materialize contacts transactionally and preserve all legacy links

**Files:**
- Create: `backend/services/command_materializers/base.py`
- Create: `backend/services/command_materializers/__init__.py`
- Create: `backend/services/command_contact_overlap_manifest.py`
- Create: `backend/services/command_contact_materializer.py`
- Modify: `backend/services/command_reconciliation.py`
- Modify: `backend/scripts/reconcile_command_archive.py`
- Create: `backend/tests/test_command_contact_overlap_manifest.py`
- Create: `backend/tests/test_command_contact_materializer.py`
- Modify: `backend/tests/test_command_reconciliation.py`
- Modify: `backend/tests/test_reconcile_command_archive_cli.py`

- [ ] **Step 1: Write failing materializer tests against real async SQLite**

Preseed the full stale repair boundary as exactly 362 unique `CRMContact` rows:

- 313 stale source-normalized rows, consisting of 311 `lead_id IS NULL` rows plus the same two lead-backed overlap rows below;
- 51 lead-backed rows with 51 distinct `lead_id` values, consisting of two rows already included in the 313 stale source-normalized population plus 49 legacy-only rows; and
- therefore `313 + 51 - 2 == 362` unique rows before apply, not 364.

Begin with zero recovered source records and zero `CRMEntitySource` links: those links cannot exist before their source records. Give 311 stale leadless rows exact recoverable identity hashes, leave four recovered identities absent from the database, and leave the other 49 lead-backed contacts unmapped and legacy-only. Supply a private synthetic manifest with exactly two redacted source-hash/lead-backed-target/evidence-hash rows, the exact synthetic bundle fingerprint, and `parser_version="contacts-v1"`. Apply a synthetic 317-identity/317-position source set through reconciliation. The apply transaction must persist the source records first, validate and stage the two reviewed links plus audit events, then invoke the materializer. The materializer must adopt those two links, adopt the 311 compatible leadless rows without mutating their base contact fields, create exactly four missing recovered contacts, create the remaining 315 mappings, and never derive another lead-backed adoption from raw identity fields. Assert:

```python
assert result.normalized_count == 317
assert result.created_count == 4
assert await count(CRMContact) == 366
assert await count(CRMContact, CRMContact.lead_id.is_not(None)) == 51
assert set(await scalar_list(select(CRMContact.lead_id).where(CRMContact.lead_id.is_not(None)))) == set(range(1, 52))
assert await count(CRMContactCapturePosition) == 317
assert await count(CRMContactSectionCapture) == 2536
assert await count(CRMEntitySource, CRMEntitySource.entity_type == "contact") == 317
```

Snapshot all 362 pre-existing CRM rows before apply and assert every base-column value is byte-for-byte equal after apply; recovered child/provenance rows are additive and do not count as base-row mutation. Assert four and only four new `CRMContact` IDs, the two manifest-linked contacts each owning exactly one recovered mapping, 311 adopted leadless rows each owning one recovered mapping, the other 49 lead-backed rows owning none, and all 317 recovered source records mapping exactly once. Assert two links were staged by the reviewed-overlap service, 315 were created by the materializer, 317 mappings exist at commit, and the combined directory contains 366 contacts. Apply the same drafts and manifest again and assert all create/link/audit counts are zero. Add conflict tests for two adoptable leadless contacts, a provider source mapped to two normalized contacts, an attempted raw-identifier auto-merge into an unlinked lead-backed contact, an invalid/unreviewed overlap manifest entry, and a missing source record.

- [ ] **Step 2: Write failing private-manifest and CLI tests**

Test `command_contact_overlap_manifest.py` with synthetic values only. Require the exact schema/version, a 64-hex bundle fingerprint, exact parser version, exactly two unique rows, a 64-hex source provider identity hash, one positive existing `target_contact_id`, its 64-hex non-PII row fingerprint, a 64-hex strong-evidence hash, and a canonical order-independent manifest digest. Reject alternate target keys, raw identity fields, and unknown fields. Validate each source hash against exactly one parsed draft in dry-run and exactly one persisted Contacts source record in apply; require each target ID to resolve to exactly one existing `lead_id IS NOT NULL` contact and its row fingerprint to remain unchanged at staging; recompute and compare the approved strong-email evidence; reject cross-links, weak/name-only matches, and existing conflicting mappings.

CLI tests require `--contact-overlap-manifest` whenever `--apply` selects Contacts, before database writes. Dry-run and resume accept and fully validate the file. Fingerprint/parser-version drift or any changed source/target/evidence set fails preflight; no log, JSON result, exception, or captured output may contain the manifest path, contact selector, raw source/target values, or evidence input. Output may contain only schema version, canonical digest, row count `2`, validation state, staged/materializer/final mapping counts, and audit/run IDs. A failure after source persistence but before materialization must prove that source records, both staged links, their audit events, all materialized rows, and the module result roll back together.

- [ ] **Step 3: Run tests and confirm RED**

Run:

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contact_materializer.py \
  tests/test_command_contact_overlap_manifest.py \
  tests/test_command_reconciliation.py \
  tests/test_reconcile_command_archive_cli.py
```

Expected: FAIL because the materializer protocol and Contacts materializer do not exist.

- [ ] **Step 4: Implement the generic materializer registry**

```python
@dataclass(frozen=True, slots=True)
class ModuleMaterializationResult:
    module: str
    normalized_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    links_created: int
    details: Mapping[str, object]

@runtime_checkable
class CommandDomainMaterializer(Protocol):
    module: str
```

Give the protocol one exact async method contract: `materialize(self, db: AsyncSession, records: Sequence[SourceRecordDraft], *, bundle_fingerprint: str) -> ModuleMaterializationResult`.

The registry enforces one materializer per module and deterministic selection, matching parser-registry validation behavior.

- [ ] **Step 5: Implement the private manifest loader and reviewed-link service**

Load the path once without logging it, reject non-regular files and schema drift, canonicalize rows by source hash, and return an immutable typed manifest plus canonical SHA-256 digest. Preflight binds it to the computed archive fingerprint and selected parser version. Dry-run validates it against parsed drafts and live target contacts without writes. During Contacts apply, after `persist_source_records()` has flushed the exact source rows, `stage_reviewed_contact_overlap_links()` repeats the source/target/strong-evidence checks, inserts exactly two idempotent `CRMEntitySource` rows, and appends `CRMContactAuditEvent` rows attributed to the reconciliation run/service actor and containing only run ID, manifest digest, source/evidence hashes, and reviewed-link action. Existing identical links/audits are unchanged; any difference is a conflict.

- [ ] **Step 6: Implement `ContactMaterializer`**

Materialize in this order inside the caller transaction:

1. Load persisted contact source rows and identity clusters.
2. Resolve existing source/entity mappings, including the two links already staged from the validated private manifest in the caller transaction. Reject ambiguous, missing, or unreviewed lead-backed links.
3. For every unmapped identity, adopt exactly one compatible `lead_id IS NULL` contact or create one; never auto-adopt a `lead_id IS NOT NULL` contact from raw identity fields.
4. Upsert profile and child values by `(contact_id, source_key)`.
5. Insert all 317 capture positions and 2,536 section captures.
6. Materialize timeline/note/saved-search records only from their stable/occurrence source keys.
7. Insert `CRMEntitySource` links for contacts and materialized child entities.
8. Return counts without committing.

Never change a lead-backed contact field (including `CRMContact.lead_id`), delete a contact, write `CRMContact.birthday/anniversary`, or create Tasks/SmartPlans/Opportunities here. A manifest-reviewed overlap adds provenance/source links and recovered child observations only; it does not copy recovered profile values onto the lead-backed row.

- [ ] **Step 7: Integrate manifest staging and materializers into reconciliation**

Add keyword-only overlap-manifest and `materializers: MaterializerRegistry | None = None` inputs to `execute_reconciliation`. Contacts preflight/dry-run validates the manifest against parser output and the target database without semantic writes. In Contacts apply, use one module transaction in this exact order: persist and flush source records; validate the manifest against those exact persisted records, the existing lead-backed contacts, and recomputed strong evidence; stage two reviewed links and audit events; invoke the materializer, which creates the remaining 315 links and four contacts; add the module result; commit. Record only the canonical manifest digest/count/state plus the `2` staged, `315` materializer-created, `317` final mapping, and `366` total-contact counts in `details_json`. Any failure rolls back every write in that sequence before the failed run is recorded. Verify-only never loads the manifest; dry-run never calls a materializer. Resume receives the same approved file and repeats all validation under the existing claim/fingerprint/version/module rules.

In `reconcile_command_archive.py`, add `--contact-overlap-manifest PATH`. `--apply --module contacts` (and unbounded apply when Contacts is registered) fails before opening the database if the flag is absent. Load/canonicalize it for Contacts preflight, validate its embedded fingerprint and parser version against the computed request, and pass the typed value to reconciliation. Never include the path or field values in output or errors.

- [ ] **Step 8: Run idempotency/reconciliation regressions and commit**

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contact_materializer.py \
  tests/test_command_contact_overlap_manifest.py \
  tests/test_command_reconciliation.py \
  tests/test_reconcile_command_archive_cli.py \
  tests/test_command_provenance_service.py
git add services/command_materializers services/command_contact_materializer.py \
  services/command_contact_overlap_manifest.py services/command_reconciliation.py \
  scripts/reconcile_command_archive.py tests/test_command_contact_materializer.py \
  tests/test_command_contact_overlap_manifest.py tests/test_command_reconciliation.py \
  tests/test_reconcile_command_archive_cli.py
git commit -m "feat: materialize recovered Command contacts"
```

### Task 5A: Add lossless occurrence ownership and timeline provenance

**Files:**
- Modify: `backend/models/command.py`
- Modify: `backend/models/command_contacts.py`
- Modify: `backend/models/__init__.py`
- Modify: `backend/alembic/env.py`
- Create: `backend/alembic/versions/5b9d1e2f3a4c_add_contact_occurrence_context.py`
- Create: `backend/services/command_contact_contracts.py`
- Create: `backend/services/command_contact_occurrences.py`
- Modify: `backend/services/command_contact_materializer.py`
- Create: `backend/tests/test_command_contact_contracts.py`
- Create: `backend/tests/test_command_contact_occurrences.py`
- Modify: `backend/tests/test_command_contacts_models.py`
- Modify: `backend/tests/test_command_contacts_migration.py`
- Modify: `backend/tests/test_command_contact_materializer.py`

- [ ] **Step 1: Write failing schema, cursor, and occurrence-ownership tests**

Add these exact additive model contracts:

```python
class CRMActivity(Base):
    # Existing columns remain unchanged.
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_source_records.id", ondelete="RESTRICT"),
        nullable=True,
    )

class CRMContactSourceOccurrence(Timestamped, Base):
    __tablename__ = "crm_contact_source_occurrences"

    id: Mapped[int]
    contact_id: Mapped[int]                 # FK crm_contacts.id, CASCADE
    section_capture_id: Mapped[int]         # FK crm_contact_section_captures.id, CASCADE
    source_record_id: Mapped[int]           # FK crm_source_records.id, RESTRICT, UNIQUE
    occurrence_ordinal: Mapped[int]         # > 0
```

`CRMActivity.source_record_id` has the named unique index `uq_crm_activities_source_record_id`; multiple legacy `NULL` values remain legal, while one recovered source record can mirror at most one internal activity. `CRMContactSourceOccurrence` has unique constraints `uq_crm_contact_source_occurrence_source` on `source_record_id` and `uq_crm_contact_source_occurrence_section_ordinal` on `(section_capture_id, occurrence_ordinal)`, plus index `ix_crm_contact_source_occurrence_contact_section` on `(contact_id, section_capture_id, id)`. `CRMContactTimelineEvent.occurred_at` becomes nullable; a recovered event without an exposed timestamp must remain visible instead of being discarded or assigned capture time.

Create framework-neutral contracts in `command_contact_contracts.py` using `StrEnum`, frozen/slotted dataclasses, and tuples rather than mutable defaults:

```python
class ContactSection(StrEnum):
    TIMELINE = "timeline"
    OPPORTUNITIES = "opportunities"
    SMART_PLANS = "smart_plans"
    NOTES = "notes"
    SAVED_SEARCHES = "saved_searches"
    TASKS_TO_DO = "tasks_to_do"
    TASKS_COMPLETED = "tasks_completed"
    TASKS_ARCHIVED = "tasks_archived"

class CaptureQualityValue(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    SHELL = "shell"
    ERROR = "error"

class MaterializationStatus(StrEnum):
    SOURCE_ONLY = "source_only"
    MATERIALIZED = "materialized"

class TimelineOrigin(StrEnum):
    RECOVERED = "recovered"
    INTERNAL_CRM = "internal_crm"
    LEGACY_LEAD = "legacy_lead"
    BOOKING = "booking"

@dataclass(frozen=True, slots=True)
class TimelineCursorV1:
    null_rank: Literal[0, 1]
    occurred_at: datetime | None
    origin_rank: Literal[0, 1, 2, 3]
    entity_id: int
```

The timeline order is exactly `(occurred_at IS NULL) ASC, occurred_at DESC NULLS LAST, origin_rank ASC, entity_id DESC`, where recovered/internal/lead/booking ranks are `0/1/2/3`. The opaque cursor is unpadded base64url of canonical JSON `{"v":1,"n":0|1,"t":"<UTC-RFC3339-microseconds-Z>"|null,"o":0|1|2|3,"i":<positive-int>}`. `encode_timeline_cursor()` always emits that canonical form. `decode_timeline_cursor()` rejects padding, noncanonical base64url/JSON, unknown or missing keys, non-UTC/noncanonical timestamps, a timestamp inconsistent with `n`, booleans posing as integers, nonpositive IDs, and versions other than `1`. “After cursor” means a greater null rank, then an older timestamp, then a greater origin rank, then a smaller entity ID. Tests pin byte-for-byte cursor output, round-trip behavior, every rejection, and the null boundary.

Migration `5b9d1e2f3a4c` has parent `4a8c0d1e2f3b`. It adds the activity FK/index, creates the ownership table parent-first, and changes only `crm_contact_timeline_events.occurred_at` from non-null to nullable using Alembic batch operations where SQLite requires them. Downgrade reverses only these additions and restores non-nullability only after explicitly refusing when null recovered timestamps exist; it never fabricates timestamps. Migration tests perform real SQLite upgrade/downgrade, compile PostgreSQL SQL, and assert `5b9d1e2f3a4c (head)`.

- [ ] **Step 2: Implement exact occurrence ownership without text inference**

Expose:

```python
@dataclass(frozen=True, slots=True)
class ContactOccurrenceSyncResult:
    observed: int
    created: int
    unchanged: int

async def sync_contact_occurrence_ownership(
    db: AsyncSession,
    *,
    bundle_fingerprint: str,
    parser_version: str,
) -> ContactOccurrenceSyncResult: ...
```

The service selects persisted Contacts source records whose `record_kind` is exactly `contact_timeline_event`, `contact_note`, `contact_saved_search`, `contact_task`, `contact_smart_plan`, or `contact_opportunity`. It reads only the typed payload context emitted by the parser: `source_contact_id`, `capture_ordinal`, `section_name`, and positive `occurrence_ordinal`. It resolves the contact through the exact `contact_profile` source record's `CRMEntitySource(entity_type="contact")`, then resolves the position by `(bundle_fingerprint, source_contact_id, capture_ordinal)` and the section capture by `(position_id, section_name)`. All three contact IDs must agree. Missing, duplicate, malformed, cross-contact, cross-section, or parser-version-mismatched context raises `ContactOccurrenceOwnershipError` and rolls back; display label, text, name, timestamp, and row position are never fallback keys.

One ownership row is written for every child occurrence, including timeline rows with no timestamp and Tasks/SmartPlans/Opportunities that remain source-only. Re-running returns all rows as unchanged. An existing row is accepted only when all owner fields and ordinal match byte-for-byte; otherwise it is a conflict. Call the sync from `ContactMaterializer` after positions/sections exist and before selective note/search/timeline materialization so the same transaction owns both provenance and normalized writes. Existing internal `CRMActivity` rows retain `source_record_id=NULL`; only deliberate mirrors set it.

- [ ] **Step 3: Run focused schema/ownership gates and commit**

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contact_contracts.py \
  tests/test_command_contact_occurrences.py \
  tests/test_command_contacts_models.py \
  tests/test_command_contacts_migration.py \
  tests/test_command_contact_materializer.py
"$PROJECT_PYTHON" -m alembic heads
git add models/command.py models/command_contacts.py models/__init__.py alembic/env.py \
  alembic/versions/5b9d1e2f3a4c_add_contact_occurrence_context.py \
  services/command_contact_contracts.py services/command_contact_occurrences.py \
  services/command_contact_materializer.py tests/test_command_contact_contracts.py \
  tests/test_command_contact_occurrences.py tests/test_command_contacts_models.py \
  tests/test_command_contacts_migration.py tests/test_command_contact_materializer.py
git commit -m "feat: retain Command contact occurrence ownership"
```

### Task 5B: Build the non-duplicating timeline

**Files:**
- Create: `backend/services/command_contact_timeline.py`
- Create: `backend/tests/test_command_contact_timeline.py`

- [ ] **Step 1: Write failing aggregation and cursor tests**

Pin the output contract:

```python
@dataclass(frozen=True, slots=True)
class ContactTimelineEntry:
    key: str
    origin: TimelineOrigin
    kind: str
    title: str
    body: str | None
    outcome: str | None
    occurred_at: datetime | None
    source_record_id: int | None
    entity_type: str
    entity_id: int

@dataclass(frozen=True, slots=True)
class ContactTimelinePage:
    rows: tuple[ContactTimelineEntry, ...]
    next_cursor: str | None
    has_more: bool
```

Expose `list_contact_timeline(db, contact_id: int, *, cursor: str | None, page_size: int) -> ContactTimelinePage`, with `page_size` restricted to `1..100` and 404 expressed as `ContactNotFound`, not an HTTP exception.

Recovered rows come from `CRMContactTimelineEvent`, internal rows from `CRMActivity`, the single legacy-lead row from the exact `CRMContact.lead_id`, and booking rows from the linkage rule below. Keys are `recovered:<id>`, `activity:<id>`, `lead:<id>`, and `booking:<id>`; text/time similarity is never a dedupe key. When a recovered event and `CRMActivity` share the same non-null `source_record_id`, return only the recovered entry. A `CRMActivity.source_record_id` that points to a different contact or to a non-timeline source is an integrity error, not a silent drop.

Booking linkage uses `Booking.lead_id == contact.lead_id` exclusively whenever the contact has a lead. Email fallback is allowed only when the contact has no lead, its normalized email is nonblank and belongs to exactly one `CRMContact`, and the booking has `lead_id IS NULL` plus the exact same normalized email. Ambiguous/shared email, a booking tied to another lead, or a name/phone match never links. The legacy-lead entry uses the persisted lead creation timestamp and ID; no synthetic history rows are derived from current status.

Tests cover mirrored-source dedupe, same-text/same-time distinctness, all booking branches, nullable recovered times, exact ordering/cursors across page boundaries, cursor tampering, deleted cursor-bound entities, empty pages, `page_size` bounds, timezone normalization, and deterministic results after reversing fixture insertion order.

- [ ] **Step 2: Implement, run, and commit**

Fetch at most `page_size + 1` eligible rows per origin after the decoded cursor, merge by the exact Task 5A key, and return a cursor for the last emitted row only when another eligible row exists. Do not load an unbounded timeline into memory.

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contact_contracts.py tests/test_command_contact_timeline.py
git add services/command_contact_timeline.py tests/test_command_contact_timeline.py
git commit -m "feat: aggregate Command contact timelines"
```

### Task 5C: Build deterministic Contacts query and mutation services

**Files:**
- Create: `backend/services/command_contacts.py`
- Create: `backend/tests/test_command_contacts_service.py`

- [ ] **Step 1: Complete the framework-neutral query contracts**

Add these exact enums to `command_contact_contracts.py`:

```python
class ContactOriginFilter(StrEnum):
    RECOVERED = "recovered"          # has a recovered contact-profile source link
    LEAD_BACKED = "lead_backed"      # lead_id is non-null
    LEGACY_ONLY = "legacy_only"      # lead_id is non-null and no recovered link
    INTERNAL_ONLY = "internal_only"  # no lead_id and no recovered link

class ContactSourceFilter(StrEnum):
    KW_COMMAND = "kw_command"
    INTERNAL_CRM = "internal_crm"
    LEGACY_LEAD = "legacy_lead"

class ContactSmartView(StrEnum):
    ALL = "all"
    NEVER_CONTACTED = "never_contacted"
    RECENTLY_ACTIVE = "recently_active"
    BIRTHDAYS_THIS_MONTH = "birthdays_this_month"
    ANNIVERSARIES_THIS_MONTH = "anniversaries_this_month"

class ContactSortKey(StrEnum):
    NAME = "name"
    STAGE = "stage"
    HEALTH_SCORE = "health_score"
    LAST_CONTACTED_AT = "last_contacted_at"
    LAST_INTERACTION_AT = "last_interaction_at"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"

class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"
```

`ContactDirectoryFilters` is frozen/slotted and contains `page: int=1`, `page_size: int=50`, trimmed literal `query`, exact `stage`, `owner_actor_id`, `assignee_actor_id`, unique sorted `tag_ids`, unique sorted `sources`, unique sorted `origins`, `health_min`, `health_max`, `birthday_month`, `anniversary_month`, `smart_view`, `sort`, and `direction`. Validate page `>=1`, page size `1..100`, query `<=200`, actor IDs `<=255`, tag IDs positive, health `0..100` with min `<=` max, and months `1..12`. Repeated tag filters mean “has every requested tag.” All filters are ANDed after SmartView expansion.

SmartView semantics are fixed: `never_contacted` requires lead stage plus no explicit recovered/internal last-contact observation; unknown capture is excluded rather than called never contacted. `recently_active` means an explicit last-interaction timestamp in `[now-30 days, now]`. Birthday/anniversary views use explicit month/day from the internal date first, otherwise an exposed recovered profile month/day; sentinel/yearless years remain null. The two month views use the injected `now` month. No tag, task title, name, or current date supplies a missing celebration/contact timestamp.

Sort uses the requested primary expression, then case-folded last name, case-folded first name, then contact ID. Null values are always last in either direction; contact ID follows the requested direction. `name` sorts by case-folded last name, first name, then ID. Literal search escapes `%`, `_`, and `\\` and searches first name, last name, legal/preferred name, normalized methods, company, and title; it never interpolates SQL.

- [ ] **Step 2: Write failing directory/detail/section/evidence/mutation tests**

Expose these exact async functions; service exceptions are typed domain errors and contain no HTTP concerns:

```python
async def list_contacts(db, filters: ContactDirectoryFilters, *, now: datetime) -> ContactDirectoryPage: ...
async def get_contact_detail(db, contact_id: int) -> ContactDetail: ...
async def get_contact_neighbors(db, contact_id: int, filters: ContactDirectoryFilters, *, now: datetime) -> ContactNeighbors: ...
async def get_contact_workspace_summary(db, contact_id: int) -> ContactWorkspaceSummary: ...
async def list_contact_section(db, contact_id: int, section: ContactSection, *, page: int, page_size: int) -> ContactSectionPage: ...
async def get_contact_evidence(db, contact_id: int) -> ContactEvidence: ...
async def list_contact_celebrations(db, *, month: int) -> ContactCelebrations: ...
async def create_contact(db, payload: ContactCreateCommand, *, actor_subject: str) -> ContactDetail: ...
async def update_contact(db, contact_id: int, payload: ContactUpdateCommand, *, actor_subject: str) -> ContactDetail: ...
async def apply_contact_bulk_action(db, payload: ContactBulkCommand, *, actor_subject: str) -> ContactBulkResult: ...
```

`list_contact_section` accepts page `>=1` and page size `1..100`. It queries `CRMContactSourceOccurrence`, not text. Each row is a discriminated union: `source_only` includes `source_record_id`, source key, section, occurrence ordinal, capture quality, captured time, and redacted typed values; `materialized` additionally includes the one `CRMEntitySource` target. Allowed target types are timeline event, note, saved search, task, smart plan, or opportunity according to source record kind. Zero targets is source-only, one compatible target is materialized, and multiple/incompatible/cross-contact targets are integrity errors. All rows order by section capture time descending nulls last, capture ordinal ascending, occurrence ordinal ascending, then ownership ID ascending. Timeline uses Task 5B rather than this page API.

`get_contact_evidence` returns all provider rows/positions separately, eight section cells per position, source/artifact metadata only, the 317/317/zero-alias identity summary and redacted 51/2/49 overlap summary. It never loads artifact bytes or emits raw overlap evidence. Aggregate quality is complete only when all required cells are complete, partial when no cell is shell/error and at least one is partial, otherwise limitation.

Celebrations merge internal and recovered observations per `(contact_id, kind)`: an internal date wins; otherwise an explicitly exposed recovered month/day is returned with its year-quality. Rows order by day, case-folded name, and ID. Missing month/day, sentinel year, tags, or task text never create a date. Mutation tests snapshot canonical before/after JSON, prove JWT subjects are passed unchanged by the router later, preserve `lead_id`, reject recovered-field overwrite, and roll back the business write if its audit insert fails.

- [ ] **Step 3: Implement source/materialized joins, exact pagination, and commits**

Use count and page queries with the same predicates. Return page count `ceil(total/page_size)` with `0` when total is `0`; a page beyond the last returns an empty row tuple without changing the requested page. `get_contact_neighbors` locates the contact in exactly the same filter/sort universe and returns adjacent IDs or null; if the contact is outside that universe, raise `ContactNotInDirectory`.

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contact_contracts.py \
  tests/test_command_contacts_service.py \
  tests/test_command_contact_timeline.py \
  tests/test_command_contact_occurrences.py
git add services/command_contact_contracts.py services/command_contacts.py \
  tests/test_command_contact_contracts.py tests/test_command_contacts_service.py
git commit -m "feat: query Command contact workspaces"
```

### Task 6: Split and type the Contacts API without losing existing behavior

**Files:**
- Create: `backend/schemas/command_contacts.py`
- Create: `backend/routers/command_contacts.py`
- Modify: `backend/routers/command.py`
- Modify: `backend/routers/command_provenance.py`
- Modify: `backend/main.py`
- Create: `backend/tests/test_command_contacts_router.py`
- Modify: `backend/tests/test_command_models.py`

- [ ] **Step 1: Freeze route ownership, declaration order, and administrator identity tests**

`command_contacts.py` owns every contact-scoped URL below. `command.py` must delete the moved handlers rather than retaining aliases. It keeps the unrelated global `POST /tags`, `GET /saved-searches`, and `DELETE /saved-searches/{search_id}` URLs; those two global saved-search handlers delegate to the same Task 5C service and audit helper. `main.py` includes each router once under `/api/v1/command`.

Declare focused routes in this exact order so no string is ever offered to `{contact_id}`:

```text
GET    /contacts/directory
POST   /contacts/sync-leads
POST   /contacts/import
POST   /contacts/bulk
GET    /contacts
POST   /contacts
GET    /celebrations
GET    /contacts/{contact_id}
PATCH  /contacts/{contact_id}
GET    /contacts/{contact_id}/neighbors
GET    /contacts/{contact_id}/workspace
GET    /contacts/{contact_id}/timeline
GET    /contacts/{contact_id}/opportunities
GET    /contacts/{contact_id}/smart-plans
GET    /contacts/{contact_id}/tasks
GET    /contacts/{contact_id}/notes
POST   /contacts/{contact_id}/notes
DELETE /contacts/{contact_id}/notes/{note_id}
GET    /contacts/{contact_id}/saved-searches
POST   /contacts/{contact_id}/saved-searches
GET    /contacts/{contact_id}/evidence
POST   /contacts/{contact_id}/tags/{tag_id}
DELETE /contacts/{contact_id}/tags/{tag_id}
```

The legacy `GET /contacts?limit=&offset=&query=&stage=` remains an array with `limit=1..100` and `offset>=0`; it delegates to the service but does not masquerade as the directory page. The task route requires exactly one `state=to_do|completed|archived`. Static-route tests specifically call `/contacts/directory`, `/contacts/import`, `/contacts/bulk`, and `/contacts/sync-leads` and prove none returns an integer-path 422.

Replace dependency-only authentication with a subject-bearing dependency:

```python
async def require_admin_subject(
    claims: dict[str, object] = Depends(require_admin),
) -> str:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.isascii() or not subject.isdigit() or int(subject) <= 0:
        raise HTTPException(status_code=401, detail="Invalid administrator subject")
    return subject

AdminSubject = Annotated[str, Depends(require_admin_subject)]
```

Every focused route receives `actor_subject: AdminSubject`; read handlers assign it to `_actor_subject`, while mutations pass the unchanged string to Task 5C. Tests exercise missing token `401`, a non-admin token `403`, malformed/missing `sub` `401`, and a valid admin subject. Do not derive an actor from email, display name, request IP, or a constant service value.

- [ ] **Step 2: Define the complete Pydantic boundary and RED tests**

All models use `ConfigDict(extra="forbid", from_attributes=True)` and strict enums matching Task 5C. Define `ContactDirectoryQueryIn` with `query`, `stage`, `owner_actor_id`, `assignee_actor_id`, repeated `tag`, repeated `source`, repeated `origin`, `health_min`, `health_max`, `birthday_month`, `anniversary_month`, `smart_view`, `sort`, `direction`, `page`, and `page_size`. Its `to_filters()` normalizes only as Task 5C permits; it never silently clamps invalid values.

Define these response/mutation boundaries, including every named nested type rather than `dict`:

```python
class ContactDirectoryPageOut(BaseModel):
    rows: list[ContactDirectoryRowOut]
    total: int
    page: int
    page_size: int
    page_count: int
    sort: ContactSortKey
    direction: SortDirection

class ContactSectionPageOut(BaseModel):
    rows: list[Annotated[ContactSourceOnlyOut | ContactMaterializedOut, Field(discriminator="status")]]
    total: int
    page: int
    page_size: int
    page_count: int

class ContactTimelinePageOut(BaseModel):
    rows: list[ContactTimelineEntryOut]
    next_cursor: str | None
    has_more: bool

class ContactEvidenceOut(BaseModel):
    contact_id: int
    provider_contact_rows: int
    resolved_provider_identities: int
    coalesced_aliases: Literal[0]
    capture_positions: list[ContactCapturePositionOut]
    section_matrix: list[ContactSectionEvidenceOut]
    sources: list[SourceRecordDetailOut]
    capture_quality: Literal["complete", "partial", "limitation"]

class ContactBulkSetStage(BaseModel):
    action: Literal["set_stage"]
    stage: str = Field(min_length=1, max_length=64)

class ContactBulkAddTag(BaseModel):
    action: Literal["add_tag"]
    tag_id: int = Field(gt=0)

class ContactBulkRemoveTag(BaseModel):
    action: Literal["remove_tag"]
    tag_id: int = Field(gt=0)

ContactBulkActionIn = Annotated[
    ContactBulkSetStage | ContactBulkAddTag | ContactBulkRemoveTag,
    Field(discriminator="action"),
]

class ContactBulkRequest(BaseModel):
    contact_ids: list[int] = Field(min_length=1, max_length=200)
    action: ContactBulkActionIn
```

Validate every contact ID as a positive integer and reject duplicate IDs rather than deduplicating them. Define concrete `ContactDetailOut`, `ContactNeighborsOut`, `ContactWorkspaceSummaryOut`, `ContactCelebrationsOut`, `ContactCreateIn`, `ContactUpdateIn`, `ContactNoteCreateIn`, and `ContactSavedSearchCreateIn` models with bounded strings and `Field(default_factory=list)`/`Field(default_factory=dict)` for collections. `ContactUpdateIn` must contain at least one set field and must not expose `lead_id`, provenance, recovered-profile fields, or audit fields. `ContactCreateIn` accepts internal first/last name, email, phone, stage, birthday, and anniversary only. Timeline times remain nullable. Evidence source rows exclude `payload_json` and artifact bytes.

Router tests cover every URL/method in Step 1, all filters and repeated values, exact response models, stable sort ties, `page>=1`, `page_size=1..100`, timeline cursor forwarding, task-state validation, 404 domain mapping, 409 integrity/conflict mapping, and 422 boundary errors. Evidence fixtures assert 317 upstream provider IDs, 317 resolved identities, zero aliases, 317 positions, 2,536 sections, plus aggregate-only 51 lead-backed/2 reviewed-overlap/49 legacy-only counts without private values.

Run:

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q tests/test_command_contacts_router.py
```

Expected: FAIL because the focused schema/router and new service-backed URLs do not exist.

- [ ] **Step 3: Implement one transaction and one audit for every mutation**

Map service `ContactNotFound` to 404, `ContactNotInDirectory`/integrity/link conflicts to 409, and validation to 422. Unexpected errors remain 500 and never expose payloads. Read routes never write audit rows.

Use these canonical audit actions:

```text
contact.created
contact.updated
contact.bulk_stage_set
contact.bulk_tag_added
contact.bulk_tag_removed
contact.tag_added
contact.tag_removed
contact.note_created
contact.note_deleted
contact.saved_search_created
contact.saved_search_deleted
contact.legacy_sync_applied
contact.legacy_import_applied
```

`before_json` and `after_json` are canonical JSON with sorted keys and compact separators. They include record IDs and changed business fields, never bearer tokens, overlap-manifest values, raw provenance payloads, or archive bytes. Create, edit, tag, note, search, sync/import, and each affected bulk contact write its audit inside the same database transaction as the business change. A bulk request locks contacts in sorted ID order, requires all requested contacts and the referenced tag to exist, applies all-or-nothing, writes one audit per contact with the same `actor_subject`, and returns requested/actioned IDs sorted ascending. An audit failure rolls back the business rows. Replays are ordinary explicit admin actions, not reconciliation idempotency.

`GET /celebrations` requires `month=1..12` and returns separate `birthdays` and `anniversaries` rows with `contact_id`, display name, `month`, `day`, nullable verified year, `year_quality=verified|sentinel|unknown`, and `origin=internal_crm|recovered`. It follows Task 5C precedence and never infers a celebration.

Add all contact provenance entity types to the allowlist: `contact_profile`, `contact_method`, `contact_address`, `contact_neighborhood`, `contact_ownership`, `contact_relationship`, `contact_preference`, `contact_capture_position`, `contact_section_capture`, `contact_timeline_event`, `contact_note`, and `contact_saved_search`. Artifact detail remains behind the existing authenticated provenance endpoint.

- [ ] **Step 4: Run API, auth, and ownership regressions and commit**

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contacts_router.py \
  tests/test_command_contacts_service.py \
  tests/test_command_contact_timeline.py \
  tests/test_command_provenance_router.py \
  tests/test_command_models.py
git add schemas/command_contacts.py routers/command_contacts.py routers/command.py \
  routers/command_provenance.py main.py tests/test_command_contacts_router.py \
  tests/test_command_models.py
git commit -m "feat: expose Command contact parity APIs"
```

### Task 7: Add the typed contact client and preserve Home compatibility

**Files:**
- Create: `frontend/src/lib/command/http.ts`
- Create: `frontend/src/lib/command/http.test.ts`
- Create: `frontend/src/lib/command/contacts.ts`
- Create: `frontend/src/lib/command/contacts.test.ts`
- Modify: `frontend/src/lib/command/api.ts`
- Modify: `frontend/src/lib/command/api.test.ts`
- Modify: `frontend/src/lib/command/home.ts`
- Modify: `frontend/src/lib/command/home.test.ts`

- [ ] **Step 1: Specify the shared abortable HTTP boundary and write RED tests**

Move authenticated JSON behavior from the untyped local `request<T>` cast in `api.ts` into `http.ts`:

```ts
export type Decoder<T> = (input: unknown, path?: string) => T;

export class CommandHttpError extends Error {
  constructor(readonly status: number, readonly detail: string) { super(detail); }
}

export class CommandDecodeError extends Error {
  constructor(readonly path: string, readonly expected: string) {
    super(`Invalid Command response at ${path}: expected ${expected}`);
  }
}

export type CommandJsonRequest<T> = Readonly<{
  path: string;
  decode: Decoder<T>;
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
}>;

export async function commandJson<T>(request: CommandJsonRequest<T>): Promise<T>;
```

`commandJson` reads `admin_token`, sends `Authorization: Bearer <token>` and `Content-Type: application/json`, serializes `body` exactly once, and forwards the identical `AbortSignal`. A missing/blank token throws `CommandHttpError(401, "Administrator session required")` before fetch. A non-2xx response reads only a string `detail` from a bounded JSON error body and otherwise uses `Command request failed (<status>)`; it does not decode the success schema. A 204 passes `null` to the decoder. A successful response parses JSON as `unknown`, then requires the supplied decoder. JSON parse/schema failures throw `CommandDecodeError`; they may identify a field path and expected type but never include response values. Native abort rejection is rethrown unchanged so callers can recognize `AbortError`.

Tests assert bearer/header/body behavior, missing token, 204, 401/404/409/422/500 messages, invalid JSON, nested decoder paths, signal identity, and an aborted fetch. Run:

```bash
cd frontend
npm test -- src/lib/command/http.test.ts
```

Expected: FAIL because `commandJson` and decoder errors do not exist.

- [ ] **Step 2: Define exact wire types, decoders, URL serialization, and client methods**

`contacts.ts` uses snake_case wire fields exactly as returned by Task 6 and exports no `any` or unchecked `as` cast. Build decoder combinators `object`, `array`, `string`, `number`, `nullable`, `literal`, and `optional` locally or from `http.ts`; every response below has a named decoder.

```ts
export type CaptureQuality = 'complete' | 'partial' | 'shell' | 'error';
export type ContactSectionName =
  | 'timeline' | 'opportunities' | 'smart_plans' | 'notes' | 'saved_searches'
  | 'tasks_to_do' | 'tasks_completed' | 'tasks_archived';
export type ContactSmartView =
  | 'all' | 'never_contacted' | 'recently_active'
  | 'birthdays_this_month' | 'anniversaries_this_month';
export type ContactSortKey =
  | 'name' | 'stage' | 'health_score' | 'last_contacted_at'
  | 'last_interaction_at' | 'created_at' | 'updated_at';
export type ContactMaterialization =
  | Readonly<{ status: 'materialized'; source_record_id: number; entity_type: string; entity_id: number }>
  | Readonly<{ status: 'source_only'; source_record_id: number; capture_quality: CaptureQuality }>;
export type ContactDirectoryPage = Readonly<{
  rows: readonly ContactDirectoryRow[];
  total: number;
  page: number;
  page_size: number;
  page_count: number;
  sort: ContactSortKey;
  direction: 'asc' | 'desc';
}>;
```

Define named readonly types/decoders for directory rows/pages, detail, neighbors, workspace summary, timeline entry/page, each section union/page, evidence matrix, celebrations, create/update requests, and bulk action/result. The section decoder dispatches on `status` and rejects unknown discriminants. The evidence decoder requires `coalesced_aliases === 0`; it never accepts raw source payloads as an alternative schema. Nullable recovered timeline timestamps remain nullable. Datetimes are validated RFC3339 strings, positive IDs are integral, and `health_score` is nullable `0..100`.

`serializeDirectoryRequest()` starts with a fresh `URLSearchParams`, emits keys in this canonical order, and sorts/deduplicates set-valued IDs/enums before repeating them:

```text
query, stage, owner_actor_id, assignee_actor_id, tag, source, origin,
health_min, health_max, birthday_month, anniversary_month, smart_view,
sort, direction, page, page_size
```

It omits blank/default-absent values, never appends `undefined`, and encodes through `URLSearchParams` only. Expose exactly:

```ts
export type ContactsApi = Readonly<{
  directory: (request: ContactDirectoryRequest, options?: { signal?: AbortSignal }) => Promise<ContactDirectoryPage>;
  detail: (id: number, options?: { signal?: AbortSignal }) => Promise<ContactDetail>;
  neighbors: (id: number, request: ContactDirectoryRequest, options?: { signal?: AbortSignal }) => Promise<ContactNeighbors>;
  workspace: (id: number, options?: { signal?: AbortSignal }) => Promise<ContactWorkspaceSummary>;
  timeline: (id: number, cursor: string | null, pageSize: number, options?: { signal?: AbortSignal }) => Promise<ContactTimelinePage>;
  section: (id: number, section: Exclude<ContactSectionName, 'timeline'>, page: number, pageSize: number, options?: { signal?: AbortSignal }) => Promise<ContactSectionPage>;
  evidence: (id: number, options?: { signal?: AbortSignal }) => Promise<ContactEvidence>;
  celebrations: (month: number, options?: { signal?: AbortSignal }) => Promise<ContactCelebrations>;
  create: (input: ContactCreateInput, options?: { signal?: AbortSignal }) => Promise<ContactDetail>;
  update: (id: number, input: ContactUpdateInput, options?: { signal?: AbortSignal }) => Promise<ContactDetail>;
  bulk: (input: ContactBulkInput, options?: { signal?: AbortSignal }) => Promise<ContactBulkResult>;
}>;
```

`section()` maps `opportunities`, `smart_plans`, `notes`, and `saved_searches` to their route segment; task sections map to `/tasks?state=to_do|completed|archived`. Timeline forwards the opaque cursor unchanged through `URLSearchParams`. Every method validates positive IDs and page bounds before fetch.

Tests pin the full canonical URL, repeated filters, reserved characters, stable sorting, omitted values, decoder rejection for every discriminated union, nullable timeline time, evidence constants, authenticated headers, 404/422 propagation, and signal forwarding.

- [ ] **Step 3: Preserve legacy consumers through a decoded adapter**

`api.ts` imports `commandJson` and named decoders. Replace its private unchecked JSON cast without changing unrelated public method signatures. `commandApi.contacts(limit, offset, filters)` continues calling `GET /contacts` and resolving the legacy array shape, now through `decodeLegacyContacts`. It remains available to Tasks and other legacy consumers; do not redirect it to `/directory` and do not synthesize a page.

Add a separate `commandApi.contactDirectory(request, options)` delegate to `contactsApi.directory` for gradual compatibility. Tests assert:

```ts
it('keeps the legacy contacts URL and decoded array shape', async () => {
  await expect(commandApi.contacts(100, 100)).resolves.toEqual(legacyRows);
  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining('/contacts?limit=100&offset=100'),
    expect.anything(),
  );
});
```

Malformed legacy rows now fail closed with `CommandDecodeError`; no caller receives partially decoded data.

- [ ] **Step 4: Make Home page-aware, abortable, and complete**

Change `CommandHomeApi` to expose `contactDirectory(request, options?)`, not the legacy offset method. Add:

```ts
export async function loadAllContacts(
  api: Pick<CommandHomeApi, 'contactDirectory'>,
  signal?: AbortSignal,
): Promise<readonly ContactDirectoryRow[]>;
```

It requests pages `1..page_count` at `page_size=100`, with `smart_view='all'`, `sort='name'`, and `direction='asc'`, forwards one signal to every request, and checks these invariants on every page: stable `total/page_count/page_size/sort/direction`, response page equals request, no duplicate contact ID, no page beyond the first is empty, collected length never exceeds total, and final length equals total. `total=0,page_count=0,rows=[]` returns immediately. Drift throws `CommandDecodeError("contacts", "stable complete pagination")`; abort propagates unchanged. Tests prove all 366 contacts are loaded across four pages, not truncated at 100, and cover zero, duplicate IDs, total drift, early empty page, final-count mismatch, and abort.

Home maps the decoded directory row into its existing `Contact` view explicitly and retains region-isolated error handling: a Contacts failure marks only `errors.contacts`; it does not erase tasks, opportunities, celebrations, goals, or briefing.

- [ ] **Step 5: Run frontend contracts and commit**

```bash
cd frontend
npm test -- \
  src/lib/command/http.test.ts \
  src/lib/command/contacts.test.ts \
  src/lib/command/api.test.ts \
  src/lib/command/home.test.ts
npm run typecheck
git add src/lib/command/http.ts src/lib/command/http.test.ts \
  src/lib/command/contacts.ts src/lib/command/contacts.test.ts \
  src/lib/command/api.ts src/lib/command/api.test.ts \
  src/lib/command/home.ts src/lib/command/home.test.ts
git commit -m "feat: add typed Command contacts client"
```

### Task 8: Rebuild the dense Contacts directory

**Files:**
- Replace: `frontend/src/components/command/ContactsWorkspace.tsx`
- Create: `frontend/src/components/command/contacts/ContactsToolbar.tsx`
- Create: `frontend/src/components/command/contacts/ContactsTable.tsx`
- Create: `frontend/src/components/command/contacts/ContactCreateDrawer.tsx`
- Create: `frontend/src/components/command/contacts/useContactDirectoryQuery.ts`
- Create: `frontend/src/components/command/contacts/useContactDirectoryQuery.test.tsx`
- Create: `frontend/src/components/command/contacts/ContactsWorkspace.test.tsx`
- Modify: `frontend/src/components/command/shell/CommandShell.tsx`
- Modify: `frontend/src/components/command/shell/CommandShell.test.tsx`
- Modify: `frontend/src/components/command/command-shell.css`
- Modify: `frontend/src/app/admin/command/contacts/page.tsx`

- [ ] **Step 1: Mount the existing toast system once at the authenticated shell**

Wrap the complete shell, including rail/header/mobile navigation/canvas, in `CommandToastProvider`; do not mount another provider inside Contacts. `CommandShell.test.tsx` renders a child that calls `useCommandToast`, clicks a trigger, and asserts one live-region toast, one dismiss action, and no provider error. It also proves route changes do not duplicate the viewport. Add `.command-toast-viewport` positioning above overlays, 16px edge spacing, pointer-event isolation, stacked 8px gaps, and the existing SWS tone variables to `command-shell.css`; toast buttons remain at least 44×44px and focus-visible.

Run:

```bash
cd frontend
npm test -- src/components/command/shell/CommandShell.test.tsx
```

Expected: FAIL because `CommandShell` does not mount `CommandToastProvider`.

- [ ] **Step 2: Implement and test the canonical URL-query adapter**

`useContactDirectoryQuery.ts` owns only these parameters:

```ts
export const CONTACT_QUERY_KEYS = [
  'query', 'stage', 'owner_actor_id', 'assignee_actor_id', 'tag', 'source', 'origin',
  'health_min', 'health_max', 'birthday_month', 'anniversary_month', 'smart_view',
  'sort', 'direction', 'page', 'page_size',
] as const;

export type ContactDirectoryQueryController = Readonly<{
  request: ContactDirectoryRequest;
  replace: (patch: Partial<ContactDirectoryRequest>) => void;
  reset: () => void;
}>;
```

The parser accepts only Task 5C enums and bounded integers. Invalid owned values resolve to defaults (`page=1`, `page_size=50`, `smart_view=all`, `sort=name`, `direction=asc`) and the next canonical replace removes them; repeated `tag/source/origin` values are parsed, deduplicated, and sorted. The serializer preserves unrelated query parameters, deletes all owned keys before writing canonical values in `CONTACT_QUERY_KEYS` order, and omits default/empty values except `page` and `page_size`. `replace()` resets page to 1 whenever any filter, SmartView, sort, direction, or page-size value changes; an explicit page-only patch preserves filters. It calls `router.replace(pathname + '?' + params, {scroll:false})` and never writes browser history per keystroke. `initialView` is used only when `smart_view` is absent, supporting the existing Home deep links; canonical Home links use `smart_view=never_contacted|recently_active|birthdays_this_month|anniversaries_this_month`.

Tests cover round trip, invalid enum/range cleanup, repeated-value ordering, reserved characters, unrelated-param preservation, initial-view precedence, reset-to-page-one, explicit pagination, and deterministic output after reordered input parameters.

- [ ] **Step 3: Write the full directory interaction contract and confirm RED**

`ContactsWorkspace.test.tsx` uses a typed fake `ContactsApi`, fake router/search params, and fake timers. It asserts:

- a full-width light canvas with module title, exact total, SmartView tabs, search, filter trigger, column menu, Add Contact, and server page controls;
- columns in default order: select, Name, Primary contact, Owner / Assignee, Tags, Stage, Health, Last activity, Origin / evidence, row action;
- 52px body rows, sticky 44px header, 44px minimum controls, visible keyboard focus, and no card-per-contact layout at desktop width;
- sort/filter/SmartView/page updates call the server with the canonical request and persist in the URL;
- search waits exactly 250ms, aborts the superseded request, and ignores a stale response even if the mock resolves it after the latest request;
- one initial fetch under React Strict Mode, retry creates one fresh request, and unmount aborts without an error toast;
- Enter/Space opens `/admin/command/contacts/{id}` unless focus is on checkbox/menu/action; pointer row click uses the same URL;
- page checkbox selects only visible IDs, indeterminate state is correct, navigation/filter changes clear selection, and bulk stage/tag operations send the explicit sorted IDs once;
- bulk success replaces/refetches the page, clears selection, and raises a success toast; 409/422 preserves selection and raises an error toast;
- loading skeleton, global true-empty, filtered no-results with Clear filters, evidence-only rows, partial/shell limitation, recoverable request error, and retry all have distinct text/actions;
- `recovered`, `lead_backed`, `legacy_only`, and `internal_only` badges are distinct; source-only evidence never uses the normalized/recovered-success badge;
- Add Contact opens the shared overlay, traps/restores focus, closes on Escape only when not submitting, validates fields, calls `contactsApi.create`, announces success, closes, and navigates to the returned internal contact.

Run:

```bash
cd frontend
npm test -- src/components/command/contacts/useContactDirectoryQuery.test.tsx \
  src/components/command/contacts/ContactsWorkspace.test.tsx
```

Expected: FAIL because the query adapter and dense server-backed workspace do not exist.

- [ ] **Step 4: Build the abortable directory controller and exact states**

`ContactsWorkspace` receives optional test injection only through this stable boundary:

```ts
export type ContactsWorkspaceProps = Readonly<{
  initialView?: ContactSmartView;
  api?: ContactsApi;
}>;
```

Production defaults to `contactsApi`. Keep `searchDraft` separate from the committed URL request. A 250ms timer commits trimmed search; all other controls commit immediately. For each request: abort the previous controller, increment a monotonically increasing request ID, set loading, call `api.directory(request,{signal})`, and apply success/error only when both ID and signal still match. `AbortError` is silent. Retain the prior page under a subtle refreshing state, but clear it when filters change to a universe that cannot describe those rows. Never fetch all 366 rows for client-side filtering or sort.

State rules are exact:

```text
loading + no page       -> table-shaped skeleton
success total=0 + no active filters -> "No contacts yet" and Add Contact
success rows=[] + active filters     -> "No contacts match these filters" and Clear filters
row with recovered source but no normalized children -> "Source evidence only"
row/evidence with partial|shell|error capture         -> "Recovered with limitations"
non-abort request failure                             -> error panel + Retry
refreshing prior page                                 -> aria-busy table, controls remain usable
```

The table renders only server rows, supplies an accessible caption, uses `aria-sort`, labels checkboxes with contact display labels, and uses a native table inside a horizontally scrollable region. Selection is a `Set<number>` limited to current row IDs. Bulk action menus expose only Task 6 actions. The create drawer fields exactly match `ContactCreateInput`; recovered/provider fields are read-only and absent.

- [ ] **Step 5: Apply Command geometry and responsive behavior in shared CSS**

Use existing SWS color/type/spacing tokens in `command-shell.css`; introduce only `command-contacts-*` structural classes. At the 1800×982 reference viewport the content fills the Command canvas, toolbar controls remain on one line, the table uses a 44px header and 52px rows, Name is sticky after selection, and page controls remain below the table. Do not reproduce source-brand colors or add another rail/header.

At `max-width: 1100px`, hide Owner/Assignee and evidence columns behind the column menu. At `max-width: 760px`, keep Name, Primary contact, Stage, and action visible, move filters into the shared overlay, and retain horizontal scroll rather than changing rows into cards. Print hides selection, actions, toolbar, bulk controls, pagination, and toast viewport. Icons are Phosphor with `aria-hidden`; icon-only buttons have explicit labels. Text and focus contrast use the existing accessible tokens.

- [ ] **Step 6: Wire the route, run focused/full checks, and commit**

`page.tsx` renders `<ContactsWorkspace />` without fetching or duplicating state. Home shortcut links use the canonical `smart_view` values. Preserve the current `/admin/command/contacts/[contactId]` navigation contract for Task 9.

```bash
cd frontend
npm test -- \
  src/components/command/contacts/useContactDirectoryQuery.test.tsx \
  src/components/command/contacts/ContactsWorkspace.test.tsx \
  src/components/command/ui/CommandUi.test.tsx \
  src/components/command/shell/CommandShell.test.tsx \
  src/lib/command/contacts.test.ts \
  src/lib/command/home.test.ts
npm run typecheck
git add src/components/command/ContactsWorkspace.tsx \
  src/components/command/contacts/ContactsToolbar.tsx \
  src/components/command/contacts/ContactsTable.tsx \
  src/components/command/contacts/ContactCreateDrawer.tsx \
  src/components/command/contacts/useContactDirectoryQuery.ts \
  src/components/command/contacts/useContactDirectoryQuery.test.tsx \
  src/components/command/contacts/ContactsWorkspace.test.tsx \
  src/components/command/shell/CommandShell.tsx \
  src/components/command/shell/CommandShell.test.tsx \
  src/components/command/command-shell.css \
  src/app/admin/command/contacts/page.tsx
git commit -m "feat: rebuild Command contacts directory"
```

### Task 9: Build the split contact detail with all captured views

**Files:**
- Create: `frontend/src/components/command/contacts/ContactDetailWorkspace.tsx`
- Create: `frontend/src/components/command/contacts/ContactProfilePanel.tsx`
- Create: `frontend/src/components/command/contacts/ContactObservedMap.tsx`
- Create: `frontend/src/components/command/contacts/ContactDetailTabs.tsx`
- Create: `frontend/src/components/command/contacts/ContactTimelineTab.tsx`
- Create: `frontend/src/components/command/contacts/ContactOpportunitiesTab.tsx`
- Create: `frontend/src/components/command/contacts/ContactSmartPlansTab.tsx`
- Create: `frontend/src/components/command/contacts/ContactTasksTab.tsx`
- Create: `frontend/src/components/command/contacts/ContactNotesTab.tsx`
- Create: `frontend/src/components/command/contacts/ContactSavedSearchesTab.tsx`
- Create: `frontend/src/components/command/contacts/ContactCaptureEvidence.tsx`
- Modify: `frontend/src/components/command/ContactActions.tsx`
- Modify: `frontend/src/components/command/ContactProfileEditor.tsx`
- Replace: `frontend/src/app/admin/command/contacts/[contactId]/page.tsx`
- Create: `frontend/src/components/command/contacts/ContactDetailWorkspace.test.tsx`

- [ ] **Step 1: Write failing eight-view tests**

The tests must click and assert these exact contact-facing states:

```ts
const views = [
  'Timeline', 'Opportunities', 'SmartPlans', 'Tasks', 'Notes', 'Saved Searches', 'Source Evidence',
] as const;
const taskStates = ['To Do', 'Completed', 'Archived'] as const;
```

Tasks is one ARIA tab with three nested state tabs, producing the required eight captured source views. Bookings appears as an explicitly `SWS internal` auxiliary view and does not count toward the archive matrix.

Assert previous/next navigation preserves current filters; contact jump search; profile/map fields; owner/assignee/collaborators; tags; yearless and sentinel birthday display; explicit anniversary year; actual timeline event bodies; empty notes/searches; source-only opportunity/plan/task rows; materialized links; per-view evidence quality; 317 provider/317 identity/zero-alias evidence; the redacted 51/2/49 overlap partition; artifact downloads; loading/error/retry; and no vendor marks/copy.

- [ ] **Step 2: Run and confirm RED**

Run: `cd frontend && npm test -- src/components/command/contacts/ContactDetailWorkspace.test.tsx`

Expected: FAIL because the current page uses `any`, one generic list renderer, seven pill buttons, no position evidence, and dark centered geometry.

- [ ] **Step 3: Implement the split detail canvas**

At desktop, keep a 320–360px sticky profile column and a flexible tab workspace. At mobile, profile collapses into an accessible disclosure above tabs. Use `CommandTabs` for top/nested tabs, `CommandStatePanel` for all states, and `CommandEvidencePanel` inside each source-only/partial view.

`ContactObservedMap` receives only server-returned coordinates/static-map metadata. If coordinates are absent, show the observed formatted address and `Map location was not captured`; do not geocode in the browser or infer a pin.

Recovered celebration examples render as:

```text
Birthday: August 30 — year not captured
Birthday: August 30 — source year treated as sentinel
Home anniversary: September 23, 2022
```

They never render `1900` as a verified year.

- [ ] **Step 4: Keep mutations scoped to SWS-owned records**

Edit/add/remove controls operate on internal contact fields, notes, tags, searches, and tasks. A `source_only` occurrence offers `View source evidence`, not Complete/Delete/Edit. Profile editing does not prefill missing SWS-owned dates from recovered month/day values.

- [ ] **Step 5: Run contact/component/type checks and commit**

```bash
cd frontend
npm test -- src/components/command/contacts/ContactDetailWorkspace.test.tsx \
  src/components/command/contacts/ContactsWorkspace.test.tsx \
  src/components/command/ui/CommandUi.test.tsx
npm run typecheck
git add src/components/command/contacts src/components/command/ContactActions.tsx \
  src/components/command/ContactProfileEditor.tsx \
  src/app/admin/command/contacts/[contactId]/page.tsx
git commit -m "feat: add full Command contact detail workspace"
```

### Task 10: Verify browser behavior, accessibility, and visual parity

**Files:**
- Create: `frontend/e2e/command-contacts.spec.ts`
- Create: `frontend/e2e/command-contacts-mobile.spec.ts`
- Create: `frontend/e2e/command-contacts-accessibility.spec.ts`
- Create: `frontend/e2e/command-contacts-visual.spec.ts`
- Modify: `frontend/e2e/visual/command-reference-manifest.ts`
- Modify: `frontend/design-qa.md`

- [ ] **Step 1: Add deterministic browser fixtures/routes**

Use synthetic names/data and intercept every contact endpoint. Include 317 recovered identities/317 positions/zero aliases, 51 lead-backed contacts partitioned into two verified overlaps and 49 legacy-only contacts, five redacted placeholder-evidence fixtures identified only by fake ordinals/hashes and field categories, every view state, one materialized and one source-only cross-domain row, one sentinel birthday, one yearless birthday, and one verified anniversary.

- [ ] **Step 2: Write Playwright journeys**

Cover directory search/filter/sort/page, selection/bulk action, add drawer, contact activation, previous/next/jump, all eight views, nested task states, evidence download request, partial/error retry, mobile profile disclosure, keyboard-only operation, focus restoration, escape, no horizontal page overflow, and browser console error gate.

Run axe on directory, detail Timeline, source-only Tasks, and evidence drawer. Verify tab/tabpanel relationships, live announcements, headings, table names, target sizes, forced colors, and reduced motion.

- [ ] **Step 3: Add only valid visual references**

Use logical reference aliases resolved through the operator-only private QA manifest:

```text
kw_command_ui_screenshots/contacts-live-current.png              1800×982
contact-detail-live                                                1793×1166
contact-opportunities-live                                         observed detail tab
contact-notes-live                                                 observed detail tab
```

The private QA manifest maps those three logical aliases to the recovered files at runtime. Do not copy a contact name, provider ID, email, phone, or other private filename component into source-controlled test names, snapshots, or documentation.

Do not treat `contacts-list.png`, retry images, blank shells, redirects, or error captures as success targets. Brand-mask only vendor marks/colors and dynamic private text; do not mask geometry, row density, tabs, toolbar, split layout, or drawer bounds.

- [ ] **Step 4: Run browser and production-build gates**

```bash
cd frontend
npx playwright test e2e/command-contacts.spec.ts \
  e2e/command-contacts-mobile.spec.ts \
  e2e/command-contacts-accessibility.spec.ts \
  e2e/command-contacts-visual.spec.ts
npm test
npm run typecheck
npm run build
```

Expected: all journeys, a11y checks, snapshots, unit/component tests, TypeScript, and production build pass.

- [ ] **Step 5: Inspect with the in-app Browser and record QA**

At the same source/current viewports, inspect rail/header geometry, full-width work canvas, toolbars, row heights, split width, tabs, map bounds, evidence drawer, focus, and mobile transitions. Record each source/current pair, brand-mask rectangles, remaining differences, and final pass/fail in `frontend/design-qa.md`. Do not mark the visual gate passed from Playwright output alone.

- [ ] **Step 6: Commit**

```bash
git add frontend/e2e/command-contacts*.spec.ts \
  frontend/e2e/visual/command-reference-manifest.ts frontend/design-qa.md
git commit -m "test: verify Command contact parity"
```

### Task 11: Reconcile, migrate, deploy, and prove production Contacts

> **CURRENTLY BLOCKED / NOT AVAILABLE:** Task 11 cannot be executed until Task 4 implements and deploys `--contact-overlap-manifest`, the private loader/validator, reviewed-link staging, and the Contacts materializer. The current CLI rejects the manifest flag. The manifest-aware commands below are future acceptance commands, not current operator instructions.

**Files:**
- Modify: `docs/command-reconciliation-runbook.md`
- Create: `docs/command-contacts-production-acceptance.md`

- [ ] **Step 1: Add exact Contacts operating commands to the runbook**

Document the future sequence below, substituting only the fingerprint/run ID returned by the preceding command once Task 4 is deployed. Today, execute only the verify-only command; do not execute the two commands explicitly marked unavailable:

```bash
cd backend
python -m scripts.reconcile_command_archive --verify-only --parser-version contacts-v1 > /tmp/command-contacts-verify.json
# NOT AVAILABLE — planned Task 4 manifest validation command.
python -m scripts.reconcile_command_archive --dry-run --module contacts --parser-version contacts-v1 --contact-overlap-manifest "$CONTACT_OVERLAP_MANIFEST" > /tmp/command-contacts-dry-run.json
# NOT AVAILABLE — planned Task 4 Contacts apply; do not run today.
python -m scripts.reconcile_command_archive --apply --module contacts --parser-version contacts-v1 --contact-overlap-manifest "$CONTACT_OVERLAP_MANIFEST" --expect-fingerprint "$VERIFIED_FINGERPRINT" > /tmp/command-contacts-apply.json
```

After Task 4 is deployed, `CONTACT_OVERLAP_MANIFEST` will name a private file outside the checkout and acceptance-artifact directories. Until then, Contacts apply remains blocked because the current CLI cannot accept or validate it. The future flow additionally blocks apply unless the manifest has exactly two reviewed rows and verification plus reviewed dry-run used the exact production bundle fingerprint/parser version/manifest digest. A future failed Contacts run resumes with `--resume <run_id>` and the same mode/module/version/fingerprint/manifest; its command repeats `--contact-overlap-manifest "$CONTACT_OVERLAP_MANIFEST"`.

- [ ] **Step 2: After Task 4 is deployed, run the real archive and database preflight**

Before the future production apply, assert checksums, exact parser counts, current Alembic head, all 51 lead-backed rows and 51 distinct nonnull `lead_id` values, exactly two strong verified cross-system overlaps, 49 legacy-only rows, zero aliases coalesced, zero ambiguous identity candidates, and a complete manifest-aware dry-run result. Inventory the stale 313 source-normalized/311 leadless history for repair without deleting it. Verify that the private manifest is a regular access-controlled file outside the repository, embeds the verified bundle fingerprint and `contacts-v1`, resolves exactly two source hashes to exact parsed records and two unique positive existing lead-backed contact IDs, validates both non-PII target-row fingerprints, and passes independent strong-evidence recomputation. Store only totals, canonical manifest/evidence hashes, validation state, and run/audit IDs in the acceptance document—no manifest path, target ID, private names, emails, phones, provider IDs, addresses, timeline bodies, or tokens.

- [ ] **Step 3: After Task 4 is deployed, apply migration and Contacts module in a bounded rollout**

Run `alembic upgrade 4a8c0d1e2f3b`. Contacts apply remains blocked until Task 4 is deployed; only then run the planned bounded apply. Do not run other domain modules in the same transaction or deployment checkpoint. Preserve the pre-apply database backup/restore identifier in the acceptance document.

- [ ] **Step 4: Execute production SQL count and integrity gates**

Record queries/results proving:

```sql
SELECT count(*) FROM crm_contact_capture_positions;              -- 317
SELECT count(*) FROM crm_contact_section_captures;                -- 2536
SELECT section_name, count(*) FROM crm_contact_section_captures GROUP BY section_name ORDER BY section_name; -- each 317
SELECT count(DISTINCT source_contact_id) FROM crm_contact_capture_positions; -- 317
SELECT count(DISTINCT contact_id) FROM crm_contact_capture_positions; -- 317
SELECT count(*) FROM crm_contacts;                                -- 366
SELECT count(*), count(DISTINCT lead_id) FROM crm_contacts WHERE lead_id IS NOT NULL; -- 51, 51
-- Verified overlap query uses private canonical identifiers in the operator session but records only the aggregate: 2
-- Lead-backed contacts without a recovered source link: 49
SELECT count(*) FROM crm_entity_sources WHERE entity_type='contact'; -- 317
```

The Contacts reconciliation detail must also prove `reviewed_overlap_links_staged == 2`, `source_entity_links_created_by_materializer == 315`, `source_entity_links_final == 317`, and `expected_combined_contact_total == 366`. Also prove every capture position has eight section rows, every source record has at least one artifact unless it is an allowed aggregate, no source profile maps to two contact entities, no contact extension row is orphaned, no recovered profile overwrote an internal date, and a second apply with the same manifest adds zero rows, links, or audit events.

- [ ] **Step 5: Run authenticated production smoke tests**

Using an admin session, verify directory totals/pagination/search, one recovered contact linked to one capture position, one of the two verified recovered/lead-backed overlaps, one of the 49 legacy-only contacts retaining `lead_id`, all eight views, one empty section, one source-only occurrence, one materialized occurrence if the dependent domain is deployed, source artifact metadata/download, celebration sentinel/yearless rendering, map limitation, mobile navigation, and 401/403 behavior for non-admin tokens.

- [ ] **Step 6: Populate acceptance evidence, run full suites, and commit docs**

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q
cd ../frontend
npm test
npm run typecheck
npm run build
git add docs/command-reconciliation-runbook.md docs/command-contacts-production-acceptance.md
git commit -m "docs: record Command contacts acceptance"
```

Production is not declared complete until the acceptance document contains the deployed commit, migration head, bundle fingerprint, verification/dry-run/apply run IDs, exact count outputs, second-apply idempotency result, authenticated smoke timestamps, and visual QA result.

## Final implementation review checklist

- The raw archive remains immutable and downloadable only to authenticated admins.
- 317 provider rows and 317 capture positions remain individually traceable.
- Exactly 317 recovered identities are normalized from 317 unique upstream provider IDs; zero aliases are coalesced.
- All 2,536 section records exist, eight per position and 317 per section.
- All 51 lead-backed contacts and all 51 `lead_id` values are unchanged; the private manifest stages exactly two audited verified-overlap links after source persistence, the materializer creates the other 315 recovered links, all 317 mappings exist, and the other 49 lead-backed contacts remain legacy-only.
- The stale 313 source-normalized/311 leadless rows remain auditable throughout repair and are never deleted blindly.
- No name-only merge, title-only merge, first-row-wins conflict, or email/phone assumption exists.
- Birthday/anniversary month/day/year quality is explicit; sentinel/missing years are never presented as verified.
- Timeline aggregation uses typed source/entity keys, not text/time similarity.
- Source-only Tasks/SmartPlans/Opportunities are visible but not editable as normalized entities.
- Existing create/edit/tag/note/search/celebration behavior remains functional and audited.
- Directory and detail are paginated, keyboard operable, responsive, accessible, and visually compared at source viewports.
- Second import is a no-op for normalized rows and links.
- Production migration, import, authenticated reads, original download, and live UI are verified before completion is claimed.
