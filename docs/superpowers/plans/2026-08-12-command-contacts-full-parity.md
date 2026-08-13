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

- Create `backend/email_normalization.py`: one application-level canonical email function shared by ORM write synchronization, identity resolution, and timeline linkage.
- Modify `backend/models/command.py`: add nullable, uniquely indexed provenance from `CRMActivity` to a recovered source record; add derived `CRMContact.normalized_email`, write synchronization, and timeline query indexes.
- Modify `backend/models/booking.py`: add derived `Booking.normalized_email`, write synchronization, and lead/email timeline indexes.
- Modify `backend/models/command_contacts.py`: add contact/source-occurrence ownership and permit recovered timeline rows with no exposed timestamp.
- Create `backend/alembic/versions/5b9d1e2f3a4c_add_contact_occurrence_context.py`: additive occurrence/activity/timeline migration whose parent is `4a8c0d1e2f3b`.
- Create `backend/alembic/versions/6c0e2f4a5b7d_add_timeline_query_support.py`: online canonical-email backfill plus additive timeline query indexes whose parent is `5b9d1e2f3a4c`.
- Create `backend/alembic/versions/7d1f3a5b6c8e_add_contact_workspace_summary_indexes.py`: index-only Contacts workspace-summary support whose parent is `6c0e2f4a5b7d`; it creates and owns only the five missing contact-first summary indexes.
- Create `backend/services/command_contact_contracts.py`: framework-neutral directory, detail, section, evidence, timeline, celebration, bulk, audit, filter, and sort contracts shared by query services.
- Create `backend/services/command_contact_occurrences.py`: validate and idempotently persist child-occurrence ownership from parser payload context.
- Create `backend/services/command_contact_timeline.py`: typed merge of recovered timeline events, `CRMActivity`, leads, and bookings with source-key dedupe.
- Modify `backend/services/command_contact_identity.py`: consume and re-export the shared canonical email function without changing its public identity API.
- Modify `backend/services/command_contact_materializer.py`: use synchronized contact email writes and persist explicit recovered timeline timestamps in UTC.
- Create `backend/services/command_contacts.py`: directory/detail/tab queries, stable pagination, mutations, and audits.
- Create `backend/schemas/command_contacts.py`: request/response/page/evidence contracts.
- Create `backend/routers/command_contacts.py`: admin-only focused contact routes.
- Modify `backend/routers/command.py`: first make every legacy contact create/update/sync/import/archive write and duplicate check honor canonical normalized email; later remove moved contact, contact-note, tag-assignment, contact-saved-search, and celebration handlers while retaining unrelated routes.
- Modify `backend/routers/booking.py`: persist the synchronized booking email and convert the database `scheduled_at` value to UTC while retaining Eastern calendar behavior.
- Modify `backend/routers/command_provenance.py`: allow contact extension entity types.
- Modify `backend/main.py`: mount `command_contacts.router` under `/api/v1/command`.
- Create `backend/tests/test_command_contact_contracts.py`: exact filters, sorts, SmartViews, cursors, bulk variants, and redaction contracts.
- Create `backend/tests/test_command_contact_occurrences.py`: occurrence ownership, backfill, idempotency, and ambiguity gates.
- Create `backend/tests/test_command_email_normalization.py`: canonicalization, ORM synchronization, raw/derived drift, and primary-email ownership boundaries.
- Create `backend/tests/test_command_contact_email_writes.py`: all current Command contact write and canonical duplicate-detection paths.
- Create `backend/tests/test_command_contact_timeline.py`: deterministic bounded aggregation, integrity preflight, non-duplication, exact ordering, and positional cursor behavior.
- Create `backend/tests/test_command_contact_timeline_migration.py`: online-only bounded canonical backfill, exact indexes, helper parity, and safe downgrade coverage for revision `6c0e2f4a5b7d`.
- Create `backend/tests/test_command_contact_summary_migration.py`: ORM/migration index parity, real SQLite upgrade/downgrade with row preservation, and PostgreSQL online/offline upgrade/downgrade SQL compilation for revision `7d1f3a5b6c8e`.
- Modify `backend/tests/test_booking_calendar.py`: synchronized booking email and UTC database timestamp regressions.
- Modify `backend/tests/test_command_contact_materializer.py`: normalized contact email and UTC recovered-event persistence regressions.
- Create `backend/tests/test_command_contacts_service.py`: directory/detail/section/evidence/celebration/mutation query tests.
- Create `backend/tests/test_command_contacts_router.py`: authenticated page/detail/tab/mutation/evidence integration tests.
- Modify `backend/tests/test_command_models.py`: retain compatibility coverage for legacy Command entities.

### Frontend typed client and directory

- Create `frontend/src/lib/command/http.ts`: shared authenticated JSON/blob transport, typed HTTP errors, response decoding, and `AbortSignal` support.
- Create `frontend/src/lib/command/http.test.ts`: authentication, error, malformed-response, blob, and abort tests.
- Create `frontend/src/lib/command/contacts.ts`: contact types, page/filter/sort state, route builders, and contact API methods.
- Create `frontend/src/lib/command/contacts.test.ts`: encoding and response-contract tests.
- Modify `frontend/src/lib/command/api.ts`: re-export contact types, keep the `commandApi.contacts(limit, offset, filters)` array contract for Tasks/legacy consumers, and expose `contactDirectory()` for Home/full metadata.
- Modify `frontend/src/lib/command/api.test.ts`: compatibility adapter and new endpoint assertions.
- Modify `frontend/src/lib/command/home.ts`: consume complete directory pages and emit canonical SmartView links.
- Modify `frontend/src/lib/command/home.test.ts`: 366-row pagination, drift, abort, and canonical-link coverage.
- Replace `frontend/src/components/command/ContactsWorkspace.tsx`: dense directory composition using shared module/table/state/evidence primitives.
- Create `frontend/src/components/command/contacts/ContactsToolbar.tsx`: search, SmartViews, filters, column controls, and add/bulk actions.
- Create `frontend/src/components/command/contacts/ContactsTable.tsx`: stable columns, evidence badges, selection, activation, and pagination.
- Create `frontend/src/components/command/contacts/ContactCreateDrawer.tsx`: internal-contact creation in the shared overlay.
- Create `frontend/src/components/command/contacts/ContactsWorkspace.test.tsx`: component states, filters, keyboard, and bulk behavior.
- Modify `frontend/src/components/command/shell/CommandShell.tsx`: mount the shared toast provider around every Command route.
- Modify `frontend/src/components/command/shell/CommandShell.test.tsx`: prove workspace toasts render without a missing-provider error.
- Modify `frontend/src/components/command/workspaceFilters.ts`: translate legacy contact shortcut parameters to canonical SmartViews without filtering client-side.
- Modify `frontend/src/components/command/CommandWorkspaceDeepLinks.test.tsx`: legacy alias precedence, canonicalization, and server-filter tests.
- Modify `frontend/src/app/admin/command/command-shell.css`: add scoped directory/toolbar/table/drawer/responsive styles.
- Modify `frontend/src/app/admin/command/contacts/page.tsx`: compatibility-only query adapter and route wrapper.

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
5. Additive occurrence/provenance schema plus framework-neutral Contacts contracts.
6. Persisted canonical email linkage, timeline query indexes, and timeline aggregation.
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

```text
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

```text
@dataclass(frozen=True, slots=True)
class ContactOccurrenceSyncResult:
    observed: int
    created: int
    unchanged: int

async sync_contact_occurrence_ownership(
    db: AsyncSession,
    *,
    records: Sequence[SourceRecordDraft],
    persisted_by_identity: Mapping[
        tuple[str, str, str, str, str],
        CRMSourceRecord,
    ],
    bundle_fingerprint: str,
    parser_version: str,
) -> ContactOccurrenceSyncResult
```

The service filters only the immutable `records` supplied to the current `ContactMaterializer.materialize()` call whose `record_kind` is exactly `contact_timeline_event`, `contact_note`, `contact_saved_search`, `contact_task`, `contact_smart_plan`, or `contact_opportunity`. For each filtered draft, it requires one exact entry in the caller's current `persisted_by_identity` snapshot and rejects a persisted row whose parser version differs from the explicit `parser_version`. It never scans every historical Contacts row sharing that parser version, so an older or different bundle cannot create a false missing-position conflict in the current run.

For each current child draft, the service reads only the typed payload context emitted by the parser: `source_contact_id`, `capture_ordinal`, `section_name`, and positive `occurrence_ordinal`. It resolves the contact through the exact current `contact_profile` draft and its `CRMEntitySource(entity_type="contact")`, then resolves the position by `(bundle_fingerprint, source_contact_id, capture_ordinal)` and the section capture by `(position_id, section_name)`. All three contact IDs must agree. A child draft outside the current profile-draft set, a missing/extra current persisted identity, duplicate source record, malformed context, cross-contact/cross-section context, or parser-version mismatch raises `ContactOccurrenceOwnershipError` and rolls back; display label, text, name, timestamp, historical row, and row position are never fallback keys.

One ownership row is written for every current child occurrence, including timeline rows with no timestamp and Tasks/SmartPlans/Opportunities that remain source-only. Re-running the same current record set returns all rows as unchanged. An existing row is accepted only when all owner fields and ordinal match byte-for-byte; otherwise it is a conflict. Call the sync with the materializer's exact `records` and `persisted_by_identity` values after positions/sections exist and before selective note/search/timeline materialization so the same transaction owns both provenance and normalized writes. Change `_event_datetime()` to return only a valid explicitly exposed timestamp, never `captured_at`; create `CRMContactTimelineEvent` even when that result is `None`. Existing internal `CRMActivity` rows retain `source_record_id=NULL`; only deliberate mirrors set it.

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
- Create: `backend/email_normalization.py`
- Modify: `backend/models/command.py`
- Modify: `backend/models/booking.py`
- Create: `backend/alembic/versions/6c0e2f4a5b7d_add_timeline_query_support.py`
- Modify: `backend/services/command_contact_identity.py`
- Modify: `backend/services/command_contact_materializer.py`
- Create: `backend/services/command_contact_timeline.py`
- Modify: `backend/routers/command.py`
- Modify: `backend/routers/booking.py`
- Create: `backend/tests/test_command_email_normalization.py`
- Create: `backend/tests/test_command_contact_email_writes.py`
- Create: `backend/tests/test_command_contact_timeline.py`
- Modify: `backend/tests/test_command_models.py`
- Create: `backend/tests/test_command_contact_timeline_migration.py`
- Modify: `backend/tests/test_command_contact_materializer.py`
- Modify: `backend/tests/test_booking_calendar.py`

- [ ] **Step 1: Write failing canonical-email, schema, migration, and write-path tests**

Create `backend/email_normalization.py` as the only application implementation of:

```python
def canonical_email(value: str | None) -> str | None:
    """Return a canonical explicit email or None for invalid/placeholders."""
```

The function accepts only `str | None`, applies Unicode NFKC, strips outer whitespace, case-folds, treats `""`, `"--"`, `"—"`, `"n/a"`, `"none"`, and `"null"` as missing, requires exactly one `@`, rejects all remaining whitespace, and requires non-empty local/domain parts with a domain that neither begins nor ends with `.`. `command_contact_identity.py` imports and re-exports this function so its existing public import path remains valid; it does not keep a second email implementation.

Add these exact derived columns and indexes:

```text
CRMContact.normalized_email: String(255), nullable
Booking.normalized_email: String(255), nullable

ix_crm_contacts_normalized_email_id
    (crm_contacts.normalized_email, crm_contacts.id)
ix_crm_activities_timeline_order
    (crm_activities.contact_id, crm_activities.created_at, crm_activities.id)
ix_bookings_timeline_lead_order
    (bookings.lead_id, bookings.scheduled_at, bookings.id)
ix_bookings_timeline_email_order
    (bookings.normalized_email, bookings.lead_id,
     bookings.scheduled_at, bookings.id)
```

`normalized_email` is deliberately non-unique because ambiguity is evidence, not a migration failure. SQLAlchemy `before_insert` and `before_update` listeners on both models overwrite the derived column with `canonical_email(target.email)` on every ORM write, even when a caller supplied a conflicting derived value. The request schemas never expose `normalized_email`. Bulk SQL writers are outside the accepted application write contract and must populate both values explicitly.

Migration `6c0e2f4a5b7d` has parent `5b9d1e2f3a4c`. Its local canonicalizer is self-contained and byte-for-byte equivalent to the application helper; importing application code into the revision is forbidden. Upgrade performs this exact transaction sequence:

1. If `op.get_context().as_sql` is true, raise `RuntimeError("contact timeline query support requires an online canonical-email backfill")` before the first `op.*` call; the revision emits no partial offline SQL.
2. Add nullable `normalized_email` to `crm_contacts` and `bookings`.
3. Read `(id, email)` from each table with `WHERE id > :last_id ORDER BY id ASC LIMIT 1000`, compute the migration-local canonical value, and update by primary key. Advance `last_id` from the last returned row and repeat. Every result batch contains at most `1_000` rows; a single ordered result cursor without that keyset predicate and SQL limit is forbidden. Do not load either table unboundedly and do not log raw emails.
4. Re-read `(id, email, normalized_email)` through the same ascending-ID keyset loop and refuse if any stored derived value differs from the local canonicalizer. Verification is a distinct second pass, not an assertion over the in-memory values used to update. The migration transaction/DDL lock prevents concurrent application drift; any error rolls back columns, backfill, and indexes together.
5. Create the four named indexes above and advance the version to `6c0e2f4a5b7d`.

Downgrade drops only those four indexes and two derived columns and returns to `5b9d1e2f3a4c`; losing recomputable derived values is safe. Migration tests run real SQLite upgrade/backfill/downgrade, compare the migration helper to the application helper across ASCII, NFKC, placeholder, whitespace, and invalid inputs, assert every exact index/column, and assert PostgreSQL offline upgrade raises the exact `RuntimeError("contact timeline query support requires an online canonical-email backfill")` with an empty revision output buffer before any DDL. A 2,001-row fixture plus SQL capture proves both write and verification passes use the exact keyset predicate and `LIMIT 1000`, never retain more than one batch, and cross three nonempty pages. A direct post-backfill tamper followed by the revision-local verification helper must raise before index creation, proving the second pass detects observed drift rather than merely reusing computed values. After the implementation lands, `alembic heads` must print only `6c0e2f4a5b7d (head)`; until then, the committed source-tree head remains `5b9d1e2f3a4c`.

All current ORM write paths must preserve the invariant in the same commit:

- `POST /contacts`, `POST /contacts/sync-leads`, `POST /contacts/import`, `POST /archive/import`, and `PATCH /contacts/{contact_id}` in `command.py` rely on the model listener for every create/change. Import/archive duplicate maps and queries use the canonical non-null `CRMContact.normalized_email`; they never use `lower(email)`, raw equality, name, phone, or `CRMContactMethod`. Import/archive collect the finite set of canonical non-null emails present anywhere in the request, including child-record contact references, query existing contacts by `normalized_email` in sorted input-key batches of at most `500`, and build only request-scoped maps. Loading every emailed `CRMContact` to construct a Python lookup is forbidden.
- `_new_contact()` in `command_contact_materializer.py` writes the primary `CRMContact.email` through the same model invariant. `CRMContactMethod.normalized_value` remains recovered evidence and is explicitly excluded from timeline booking ownership and ambiguity counts.
- `create_booking()` in `booking.py` writes the raw booking email through the Booking listener and stores `Booking.scheduled_at=slot_start.astimezone(UTC)`. Google Calendar creation, office-hour validation, and notification payloads continue using the Eastern `slot_start`; only the database instant is normalized.
- `_event_datetime()` in `command_contact_materializer.py` converts every valid explicit recovered timestamp with `.astimezone(UTC)` and continues to preserve `None` when the source exposed no time.

`test_command_email_normalization.py` proves helper behavior, constructor/assignment synchronization, a deliberately conflicting caller-supplied derived value being overwritten at flush, and nullable invalid inputs. `test_command_contact_email_writes.py` exercises all five Command write endpoints above against real async SQLite, including update drift, NFKC-equivalent duplicate detection, invalid email non-linkage, and no `CRMContactMethod` participation. It seeds 1,200 unrelated contacts, captures SQL for both import endpoints, and asserts there is no `lower(crm_contacts.email)`, raw-email equality predicate, or unfiltered existing-contact preload; every existing-contact lookup is a `normalized_email IN (...)` request-key batch of at most `500`. `test_booking_calendar.py` proves the booking row stores the canonical email and UTC instant while the calendar call still receives Eastern time. Materializer tests prove normalized contact email and UTC/nullable recovered events. No failure or exception includes a raw email.

- [ ] **Step 2: Run the normalization/schema tests and confirm RED**

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_email_normalization.py \
  tests/test_command_contact_email_writes.py \
  tests/test_command_models.py \
  tests/test_command_contact_timeline_migration.py \
  tests/test_command_contact_materializer.py \
  tests/test_booking_calendar.py
```

Expected: FAIL because the shared helper, derived columns, revision, listeners, canonical duplicate queries, and UTC write normalization do not exist.

- [ ] **Step 3: Write failing aggregation, integrity, ordering, and cursor tests**

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

Recovered rows come from `CRMContactTimelineEvent`, internal rows from `CRMActivity`, the single legacy-lead row from the exact `CRMContact.lead_id`, and booking rows from the exact linkage rule below. Keys are `recovered:<id>`, `activity:<id>`, `lead:<id>`, and `booking:<id>`; text/time similarity is never a dedupe key.

Before applying a cursor or returning any row, run the integrity preflight for the requested contact. Source-domain, occurrence-ownership, contact-email, and linked-lead checks use a fixed number of aggregate/`EXISTS` or bounded point queries. The lead-backed booking drift scan defined below is intentionally different: it is a bounded multi-query keyset scan whose query count grows with that one lead's bookings. Do not describe the complete preflight as fixed-query-count. No preflight query loads an unbounded row set, and all checks finish before any partial page is returned.

1. Every recovered event for the contact independently resolves to a `CRMSourceRecord` with `source_system="kw_command"`, `module="contacts"`, and `record_kind="contact_timeline_event"`, and its event `source_system` agrees. This gate runs even when no `CRMActivity` references the source.
2. Inspect both directions of mirror ownership: every `CRMActivity` with non-null `source_record_id` whose `contact_id` is the requested contact, and every activity whose source points to a recovered event owned by the requested contact regardless of the activity's current `contact_id`. Each is one deliberate mirror: the activity contact is non-null and equals the requested contact, its source has the exact domain above, and exactly one same-contact recovered event owns that source through a timeline `CRMContactSourceOccurrence`, its `CRMContactSectionCapture`, and its same-contact `CRMContactCapturePosition`. A missing counterpart, missing occurrence, null activity owner, different activity/occurrence/position contact, non-timeline section, or wrong source system/module/kind is `ContactTimelineIntegrityError`.
3. If `CRMContact.lead_id` is non-null, exactly that `Lead` exists. A missing lead is an integrity error even when its creation row would fall before the cursor.
4. The requested contact's `normalized_email` equals `canonical_email(contact.email)`. Every primary-contact row returned by the at-most-two-owner email query satisfies the same raw/derived equality. Reads never repair drift; any observed mismatch is `ContactTimelineIntegrityError`.
5. If the contact has a linked lead, validate every `Booking` owned by that exact lead before fetching output. Use ascending primary-key keyset batches selecting only `(id, email, normalized_email)` with `Booking.lead_id == contact.lead_id`, `Booking.id > :last_id`, `ORDER BY Booking.id ASC`, and `LIMIT 1000`. Reject when any row has `normalized_email != canonical_email(email)`. Retain at most one 1,000-row batch. For `n` linked bookings this takes at most one count/terminal probe plus `ceil(n / 1_000)` nonempty batch queries—`O(ceil(n / 1_000))` work and bounded memory, not a fixed query count. The scan covers rows before the cursor and beyond the output page.

The source and lead-backed-booking checks cover corruption before the cursor and beyond the requested page. Email fallback remains fixed and indexed: it performs the at-most-two primary-owner lookup plus the single `page_size + 1` candidate query, validates raw/derived equality for each returned candidate, and never scans all leadless bookings. A leadless row whose persisted normalized value does not equal the uniquely owned canonical email is outside the linkage domain; a returned candidate whose raw value canonicalizes differently is an integrity error. Integrity errors contain only a stable generic reason code/message—never contact values, email values, source keys, payloads, or cursor contents—and the function returns no partial page.

After preflight, the internal activity query selects only `contact_id=<requested>` and `source_record_id IS NULL`; exact mirrors exist only as recovered entries. The merge layer defensively rejects any non-null activity source that reaches it and dedupes only the exact shared source identity. Same text and same timestamp without a shared non-null source remain distinct.

Booking ownership is exact:

- When `contact.lead_id` is non-null, complete the bounded all-linked-booking drift scan above, then fetch output only with `Booking.lead_id == contact.lead_id`. Email, name, and phone cannot add another booking.
- When the contact has no lead, fallback is allowed only if its non-null persisted `normalized_email` belongs to exactly one primary `CRMContact.email`. Query at most two owners through `ix_crm_contacts_normalized_email_id`; `CRMContactMethod` is never consulted.
- Email-linked bookings must have `Booking.lead_id IS NULL` and the same persisted `Booking.normalized_email`. Validate every returned candidate against `canonical_email(Booking.email)` before constructing entries. A shared contact email, blank/invalid canonical email, booking bound to any lead, raw/derived drift in a returned candidate, name-only match, or phone-only match never links.

Map every origin exactly:

| Origin | `kind` | `title` | `body` | `outcome` | `occurred_at` | `source_record_id` | `entity_type` |
|---|---|---|---|---|---|---|---|
| recovered | stored `kind` | stored `title` | stored `body` | stored `outcome` | stored event time | stored source ID | `contact_timeline_event` |
| internal CRM | stored activity `kind` | stored `summary` | `None` | `None` | `CRMActivity.created_at` | `None` | `activity` |
| legacy lead | `lead_created` | `Lead created` | `None` | `None` | `Lead.created_at` | `None` | `lead` |
| booking | `booking` | stored `meeting_type` | `notes or None` | `context or None` | `Booking.scheduled_at` | `None` | `booking` |

Lead `updated_at`, current routing status, source, type, name, and notes never synthesize timeline history. Booking `created_at` never replaces the scheduled instant.

The UTC invariant is exact. Application writers touched by this task persist explicit timestamps in UTC. PostgreSQL `timestamptz` values are treated as instants; SQLite/test values reloaded without `tzinfo` are interpreted as already-UTC compatibility values. Every non-null returned timestamp is converted to aware UTC before entry/cursor construction. Aware non-UTC values supplied directly to the conversion helper normalize to UTC. Tests must not treat SQLite storage of a non-UTC wall time as instant-preserving.

Order remains the Task 5A order `(occurred_at IS NULL) ASC, occurred_at DESC NULLS LAST, origin_rank ASC, entity_id DESC`. SQL uses native timestamp ordering. In-memory merge computes an exact signed integer microsecond offset from `datetime(1970, 1, 1, tzinfo=UTC)` using `timedelta.days`, `.seconds`, and `.microseconds`; it never calls `datetime.timestamp()` or converts time to `float`. Tests use year-2500 values one microsecond apart with opposing IDs to prove the timestamp wins without precision loss.

Cursors are positional, not entity handles. Continuation applies the decoded tuple directly to every origin query; it never fetches or validates that the entity encoded in the cursor still exists. Deleting the cursor-producing row, or supplying a canonical cursor for a never-existing bound, returns the same strictly later set with no 404, duplicate, or unrelated skip. Tests exhaust same-time transitions across all four origin ranks, descending IDs within an origin, timed-to-null transition, and the final null row. Cursor tampering remains a generic validation error.

- [ ] **Step 4: Implement bounded keyset queries and exact merge semantics**

Run the integrity preflight first. For a lead-backed contact, the preflight's full lead-booking drift scan uses the ascending-ID batches defined above; it is separate from and must not be reused as the output collection. After the preflight completes, fetch at most `page_size + 1` already-eligible output rows per origin after the decoded positional cursor:

- recovered uses `ix_crm_contact_timeline_order` and the exact contact/time/ID predicate;
- internal uses `ix_crm_activities_timeline_order`, exact contact, and `source_record_id IS NULL`;
- lead uses the exact primary key and returns zero or one eligible creation entry;
- lead-backed booking output uses `ix_bookings_timeline_lead_order` and still applies the exact scheduled-time/ID cursor plus `LIMIT page_size + 1`, regardless of how many integrity batches preceded it;
- email-backed booking uses `ix_bookings_timeline_email_order` with exact normalized email and `lead_id IS NULL`.

The email ownership query loads at most two contact IDs. No query scans all contacts or all leadless bookings in Python. The only row-count-dependent integrity work is the exact-lead booking scan, whose statements select three columns, use primary-key keyset progress, and limit every batch to `1_000`. Every output-origin statement includes its linkage predicate, cursor predicate when present, exact ordering, and SQL `LIMIT page_size + 1`. Merge at most four output tuples of at most `page_size + 1` candidates each using the exact integer-microsecond key, emit the first `page_size`, and set `has_more` only when a further unique eligible row exists. `next_cursor` is the canonical cursor for the last emitted row only when `has_more` is true; an empty or terminal page has `next_cursor=None`.

`test_command_contact_timeline.py` must assert full dataclass equality for one row of each origin; same-source dedupe; same-text/same-time distinctness; missing lead; every booking branch; NFKC/ambiguity/`CRMContactMethod` exclusion; nullable recovered time; exact year-2500 microsecond order; reversed fixture insertion order; canonical/tampered/deleted/nonexistent cursors; empty/terminal pages; bool and numeric page-size boundaries; and returned UTC values. The integrity matrix must separately include: a standalone recovered event whose source is missing or has each wrong domain field and has no activity; a source occurrence, section, or capture position owned by another contact; an activity with null contact and an activity with another contact whose source points to the requested contact's recovered event; corruption before the cursor and after the requested page; requested-contact and at-most-two-owner email drift; a returned email-backed booking with raw/derived drift; and a lead-backed booking drifted in the final batch of a 2,001-row fixture. Every branch must raise before returning any page, with no private value in the error.

SQL-capture tests assert exact predicates, selected columns, order clauses, and numeric limits—not merely the presence of the word `LIMIT`. For the 2,001 lead-booking fixture with `page_size=1`, assert each integrity batch selects only `(id, email, normalized_email)`, carries `lead_id`, `id > last_id`, ascending ID, and `LIMIT 1000`; no batch contains more than 1,000 rows; the number of batch queries grows as `O(ceil(n / 1_000))` rather than being asserted constant; and the distinct output booking statement still uses scheduled ordering, the cursor when present, `ix_bookings_timeline_lead_order`'s leading predicate, and `LIMIT 2`. A separate email-fallback capture asserts the at-most-two indexed owner query plus one `LIMIT page_size + 1` candidate query, with no full leadless-booking scan. The suite also proves a mirror-heavy history cannot underfill while later unique activity exists.

- [ ] **Step 5: Run focused timeline/schema/write gates and commit**

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contact_contracts.py \
  tests/test_command_email_normalization.py \
  tests/test_command_contact_email_writes.py \
  tests/test_command_contact_timeline.py \
  tests/test_command_models.py \
  tests/test_command_contact_timeline_migration.py \
  tests/test_command_contact_materializer.py \
  tests/test_booking_calendar.py
"$PROJECT_PYTHON" -m alembic heads
git add email_normalization.py models/command.py models/booking.py \
  alembic/versions/6c0e2f4a5b7d_add_timeline_query_support.py \
  services/command_contact_identity.py services/command_contact_materializer.py \
  services/command_contact_timeline.py routers/command.py routers/booking.py \
  tests/test_command_email_normalization.py \
  tests/test_command_contact_email_writes.py \
  tests/test_command_contact_timeline.py tests/test_command_models.py \
  tests/test_command_contact_timeline_migration.py \
  tests/test_command_contact_materializer.py \
  tests/test_booking_calendar.py
git commit -m "feat: aggregate Command contact timelines"
```

### Task 5C: Build deterministic Contacts query and mutation services

**Files:**
- Modify: `backend/models/command.py`
- Create: `backend/alembic/versions/7d1f3a5b6c8e_add_contact_workspace_summary_indexes.py`
- Modify: `backend/services/command_contact_contracts.py`
- Modify: `backend/services/command_contact_timeline.py`
- Create: `backend/services/command_contacts.py`
- Modify: `backend/tests/test_command_contacts_models.py`
- Modify: `backend/tests/test_command_contact_contracts.py`
- Create: `backend/tests/test_command_contact_summary_migration.py`
- Modify: `backend/tests/test_command_contact_timeline.py`
- Create: `backend/tests/test_command_contacts_service.py`
- Create: `backend/tests/test_command_contact_mutations.py`

Task 5C adds revision `7d1f3a5b6c8e`, with parent `6c0e2f4a5b7d`, and adds
only these indexes that are absent at its parent:

```text
ix_crm_tasks_contact_status_id
  ON crm_tasks(contact_id, status, id)
ix_crm_notes_contact_id
  ON crm_notes(contact_id, id)
ix_crm_saved_searches_contact_id
  ON crm_saved_searches(contact_id, id)
ix_crm_smart_plan_enrollments_contact_status_id
  ON crm_smart_plan_enrollments(contact_id, status, id)
ix_crm_opportunity_contacts_contact_opportunity
  ON crm_opportunity_contacts(contact_id, opportunity_id)
```

Declare the same exact names and column order in the five models'
`__table_args__`; do not add another index where the parent metadata/database
already supplies the same ordered columns. Upgrade creates only these five
indexes. Downgrade drops only these five indexes in reverse order, preserves
every table/row/constraint, and returns to `6c0e2f4a5b7d`. There is no data
backfill or application-code import, so online upgrade/downgrade and
PostgreSQL offline `--sql` upgrade/downgrade must all compile and must not
refuse offline mode. Migration tests assert the exact revision chain and
index name/table/column maps, run real SQLite upgrade then downgrade around
sentinel rows, compile both directions for PostgreSQL, and prove no column,
constraint, or row changes. After Task 5C lands, `alembic heads` prints only
`7d1f3a5b6c8e (head)`; until then the implemented source-tree head remains
`6c0e2f4a5b7d`.

Task 5C also adds the already-deployed
`UniqueConstraint("contact_id", "tag_id", name="uq_crm_contact_tag")` to
`CRMContactTag.__table_args__` so ORM metadata exactly matches revision
`fa4c19d2e3b7`; it must not attempt to create, rename, or replace that database
constraint. Model tests assert the exact metadata name/columns and SQLite
duplicate rejection with foreign keys enabled.

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

Define every service DTO in this task before any query implementation. These are the exact framework-neutral contracts consumed by Tasks 5B, 6, and 7; Pydantic models adapt them but never replace them:

```python
ContactEvidenceQuality = Literal["complete", "partial", "limitation"]
CelebrationYearQuality = Literal["verified", "yearless", "sentinel", "unknown"]
ContactAuditScalar = str | int | bool | None
type JsonValue = (
    None | bool | int | float | str
    | tuple["JsonValue", ...]
    | Mapping[str, "JsonValue"]
)

@dataclass(frozen=True, slots=True)
class ContactDirectoryFilters:
    page: int = 1
    page_size: int = 50
    query: str | None = None
    stage: str | None = None
    owner_actor_id: str | None = None
    assignee_actor_id: str | None = None
    tag_ids: tuple[int, ...] = ()
    sources: tuple[ContactSourceFilter, ...] = ()
    origins: tuple[ContactOriginFilter, ...] = ()
    health_min: int | None = None
    health_max: int | None = None
    birthday_month: int | None = None
    anniversary_month: int | None = None
    smart_view: ContactSmartView = ContactSmartView.ALL
    sort: ContactSortKey = ContactSortKey.NAME
    direction: SortDirection = SortDirection.ASC

@dataclass(frozen=True, slots=True)
class ContactTagValue:
    id: int
    name: str

@dataclass(frozen=True, slots=True)
class ContactActorValue:
    role: Literal["owner", "assignee", "collaborator"]
    provider_actor_id: str | None
    display_name: str | None

@dataclass(frozen=True, slots=True)
class ContactCelebrationValue:
    month: int
    day: int
    year: int | None
    year_quality: CelebrationYearQuality
    origin: Literal["internal_crm", "recovered"]

@dataclass(frozen=True, slots=True)
class ContactAddressValue:
    id: int
    address_type: str | None
    formatted: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    source_record_id: int | None

@dataclass(frozen=True, slots=True)
class ContactDirectoryRow:
    id: int
    first_name: str
    last_name: str
    display_name: str
    primary_email: str | None
    primary_phone: str | None
    stage: str
    lead_backed: bool
    origins: tuple[ContactOriginFilter, ...]
    sources: tuple[ContactSourceFilter, ...]
    health_score: int | None
    last_contacted_at: datetime | None
    last_interaction_at: datetime | None
    owner: ContactActorValue | None
    assignee: ContactActorValue | None
    tags: tuple[ContactTagValue, ...]
    birthday: ContactCelebrationValue | None
    anniversary: ContactCelebrationValue | None
    evidence_quality: ContactEvidenceQuality | None

@dataclass(frozen=True, slots=True)
class ContactDirectoryPage:
    rows: tuple[ContactDirectoryRow, ...]
    total: int
    page: int
    page_size: int
    page_count: int
    sort: ContactSortKey
    direction: SortDirection

@dataclass(frozen=True, slots=True)
class ContactRecoveredProfile:
    legal_name: str | None
    preferred_name: str | None
    description: str | None
    company: str | None
    title: str | None
    lead_source: str | None
    account_name: str | None
    birthday: ContactCelebrationValue | None
    anniversary: ContactCelebrationValue | None

@dataclass(frozen=True, slots=True)
class ContactDetail:
    contact: ContactDirectoryRow
    lead_id: int | None
    recovered_profile: ContactRecoveredProfile | None
    addresses: tuple[ContactAddressValue, ...]
    ownership: tuple[ContactActorValue, ...]
    tags: tuple[ContactTagValue, ...]

@dataclass(frozen=True, slots=True)
class ContactNeighbors:
    previous_contact_id: int | None
    next_contact_id: int | None

@dataclass(frozen=True, slots=True)
class ContactWorkspaceSummary:
    open_tasks: int
    completed_tasks: int
    archived_tasks: int
    active_smart_plans: int
    opportunities: int
    notes: int
    saved_searches: int
    bookings: int

@dataclass(frozen=True, slots=True)
class ContactOpportunityOccurrence:
    kind: Literal["opportunity"]
    title: str
    stage: str | None
    value_cents: int | None

@dataclass(frozen=True, slots=True)
class ContactSmartPlanOccurrence:
    kind: Literal["smart_plan"]
    title: str
    status: str | None

@dataclass(frozen=True, slots=True)
class ContactTaskOccurrence:
    kind: Literal["task"]
    title: str
    description: str | None
    state: Literal["to_do", "completed", "archived"]
    due_at: datetime | None

@dataclass(frozen=True, slots=True)
class ContactNoteOccurrence:
    kind: Literal["note"]
    title: str
    body: str | None

@dataclass(frozen=True, slots=True)
class ContactSavedSearchOccurrence:
    kind: Literal["saved_search"]
    title: str
    criteria_summary: tuple[str, ...]

ContactOccurrenceValue = (
    ContactOpportunityOccurrence
    | ContactSmartPlanOccurrence
    | ContactTaskOccurrence
    | ContactNoteOccurrence
    | ContactSavedSearchOccurrence
)

@dataclass(frozen=True, slots=True)
class ContactSourceOnly:
    status: Literal["source_only"]
    source_record_id: int
    source_key_hash: str
    section: ContactSection
    occurrence_ordinal: int
    capture_quality: CaptureQualityValue
    captured_at: datetime | None
    value: ContactOccurrenceValue

@dataclass(frozen=True, slots=True)
class ContactMaterialized:
    status: Literal["materialized"]
    source_record_id: int
    source_key_hash: str
    section: ContactSection
    occurrence_ordinal: int
    capture_quality: CaptureQualityValue
    captured_at: datetime | None
    value: ContactOccurrenceValue
    entity_type: Literal[
        "note", "saved_search", "task", "smart_plan", "opportunity",
    ]
    entity_id: int

ContactSectionRow = ContactSourceOnly | ContactMaterialized

@dataclass(frozen=True, slots=True)
class ContactSectionPage:
    rows: tuple[ContactSectionRow, ...]
    total: int
    page: int
    page_size: int
    page_count: int

@dataclass(frozen=True, slots=True)
class ContactArtifactMetadata:
    artifact_id: int
    artifact_type: str
    sha256: str
    size_bytes: int
    content_href: str

@dataclass(frozen=True, slots=True)
class ContactSourceMetadata:
    source_record_id: int
    record_kind: str
    evidence_level: Literal[
        "observed_record", "rendered_occurrence", "displayed_aggregate",
    ]
    capture_quality: CaptureQualityValue
    captured_at: datetime | None
    artifacts: tuple[ContactArtifactMetadata, ...]

@dataclass(frozen=True, slots=True)
class ContactSectionEvidence:
    capture_position_id: int
    section: ContactSection
    source_record_id: int
    capture_quality: CaptureQualityValue
    row_count: int
    is_empty: bool
    limitation_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ContactCaptureEvidence:
    capture_position_id: int
    capture_ordinal: int
    source_record_id: int
    capture_quality: CaptureQualityValue
    sections: tuple[ContactSectionEvidence, ...]

@dataclass(frozen=True, slots=True)
class ContactEvidence:
    contact_id: int
    provider_contact_rows: int
    resolved_provider_identities: int
    coalesced_aliases: Literal[0]
    lead_backed_contacts: int
    reviewed_overlaps: int
    legacy_only_contacts: int
    capture_positions: tuple[ContactCaptureEvidence, ...]
    section_matrix: tuple[ContactSectionEvidence, ...]
    sources: tuple[ContactSourceMetadata, ...]
    capture_quality: ContactEvidenceQuality

@dataclass(frozen=True, slots=True)
class ContactCelebrationRow:
    contact_id: int
    display_name: str
    kind: Literal["birthday", "anniversary"]
    month: int
    day: int
    year: int | None
    year_quality: CelebrationYearQuality
    origin: Literal["internal_crm", "recovered"]

@dataclass(frozen=True, slots=True)
class ContactCelebrations:
    birthdays: tuple[ContactCelebrationRow, ...]
    anniversaries: tuple[ContactCelebrationRow, ...]

class UnsetType(Enum):
    TOKEN = "unset"

UNSET = UnsetType.TOKEN

@dataclass(frozen=True, slots=True)
class ContactCreateCommand:
    first_name: str
    last_name: str = ""
    email: str | None = None
    phone: str | None = None
    stage: str = "lead"
    birthday: date | None = None
    anniversary: date | None = None

@dataclass(frozen=True, slots=True)
class ContactUpdateCommand:
    first_name: str | UnsetType = UNSET
    last_name: str | UnsetType = UNSET
    email: str | None | UnsetType = UNSET
    phone: str | None | UnsetType = UNSET
    stage: str | UnsetType = UNSET
    birthday: date | None | UnsetType = UNSET
    anniversary: date | None | UnsetType = UNSET

@dataclass(frozen=True, slots=True)
class ContactBulkSetStage:
    action: Literal["set_stage"]
    stage: str

@dataclass(frozen=True, slots=True)
class ContactBulkAddTag:
    action: Literal["add_tag"]
    tag_id: int

@dataclass(frozen=True, slots=True)
class ContactBulkRemoveTag:
    action: Literal["remove_tag"]
    tag_id: int

ContactBulkAction = ContactBulkSetStage | ContactBulkAddTag | ContactBulkRemoveTag

@dataclass(frozen=True, slots=True)
class ContactBulkCommand:
    contact_ids: tuple[int, ...]
    action: ContactBulkAction

@dataclass(frozen=True, slots=True)
class ContactBulkResult:
    requested_contact_ids: tuple[int, ...]
    actioned_contact_ids: tuple[int, ...]
    action: Literal["set_stage", "add_tag", "remove_tag"]

@dataclass(frozen=True, slots=True)
class ContactNoteCreateCommand:
    body: str

@dataclass(frozen=True, slots=True)
class ContactSavedSearchCreateCommand:
    name: str
    criteria: Mapping[str, JsonValue]

@dataclass(frozen=True, slots=True)
class ContactImportRowCommand:
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    stage: str
    birthday: date | None
    anniversary: date | None

@dataclass(frozen=True, slots=True)
class ContactImportCommand:
    contacts: tuple[ContactImportRowCommand, ...]

@dataclass(frozen=True, slots=True)
class ContactMutationResult:
    contact_id: int
    record_id: int | None
    changed: bool
    audit_entity_type: Literal["contact_audit"] | None
    audit_event_id: int | None

@dataclass(frozen=True, slots=True)
class WorkspaceMutationResult:
    record_id: int
    changed: bool
    audit_entity_type: Literal["workspace_activity"]
    audit_event_id: int | None

SavedSearchDeletionResult = ContactMutationResult | WorkspaceMutationResult

@dataclass(frozen=True, slots=True)
class ContactLegacySyncResult:
    created: int
    timeline_backfilled: int
    total_legacy_leads: int

@dataclass(frozen=True, slots=True)
class ContactImportResult:
    created: int
    skipped_duplicates: int

@dataclass(frozen=True, slots=True)
class ContactSavedSearchValue:
    id: int
    contact_id: int | None
    contact_name: str | None
    name: str
    criteria: Mapping[str, JsonValue]
    updated_at: datetime
```

`JsonValue` floats must be finite. Constructor validation pins first name `1..120`, last name `0..120`, email `<=255`, phone `<=50`, stage `1..50`, note body `1..20_000`, search name `1..255`, canonical criteria `<=64 KiB`, import rows `1..1,000`, contact IDs positive/unique with bulk size `1..200`, and tag IDs positive. Birthday and anniversary accept only `None` or an exact `date` instance for create/import, and only `UNSET`, `None`, or an exact `date` instance for update; `datetime` is rejected even though it subclasses `date`. `ContactUpdateCommand` rejects an all-`UNSET` command and `None` for required first/last/stage values. No command exposes `lead_id`, recovered observations, provenance IDs, or audit fields.

The source-occurrence projection is deliberately narrower than the parser
payload. Parse `CRMSourceRecord.payload_json` as an object and require its
`values` member to be an object; malformed JSON or a non-object envelope is a
`ContactDataIntegrityError`, never a best-effort string conversion. A projected
text value is accepted only when it is already a string, trims non-empty, and
fits the destination bound (`title <=500`, `stage/status <=120`,
`description/body <=20_000`); an absent or wrong-typed optional field becomes
`None`, while an over-bound value is an integrity error. Titles use, in order,
the section-specific whitelisted key (`title` for opportunity/task/note,
`name` for smart plan/saved search) and then the source record's bounded,
non-empty `display_label`; no title means integrity error. The exact remaining
projection rules are:

- opportunity `stage` reads only string `values.stage`; `value_cents` reads
  only an explicit JSON integer for which `type(value) is int` and `value >= 0`
  (therefore excluding booleans). Currency strings, budget/commission text,
  floats, negatives, and inferred values yield `None`;
- smart-plan `status` reads only string `values.status`;
- task state comes only from the owning section
  (`tasks_to_do -> to_do`, `tasks_completed -> completed`,
  `tasks_archived -> archived`), description reads only
  `values.description`, and `due_at` reads only string `values.due_at` when it
  is a complete RFC3339 timestamp with `Z` or an explicit numeric UTC offset.
  It is normalized to UTC; missing, date-only, naive, human `due_date`, or
  invalid text yields `None`;
- note body reads only string `values.body`; parser `raw_lines`, HTML, and all
  other keys are not projected;
- saved-search criteria inspect only `price`, `beds`, and `baths`, in that
  fixed order. A value is included only when it is a trimmed string of
  `1..120` characters or an exact nonnegative JSON integer (boolean and float
  excluded), producing exactly `Price: {value}`, `Beds: {value}`, or
  `Baths: {value}`. Nested values, unknown keys, `created_by`, and unsafe or
  empty scalars are omitted.

Every `source_key_hash` is exactly
`sha256(b"command.contact.section-source-key.v1\0" + source_key.encode("utf-8")).hexdigest()`.
Tests pin the byte domain and lowercase 64-hex output and prove neither the raw
key nor any unlisted payload field reaches a DTO, error, audit row, or log.

Source filter predicates are exact and may overlap: `kw_command` means a `contact_profile` source link from `source_system="kw_command"`; `legacy_lead` means `CRMContact.lead_id IS NOT NULL`; `internal_crm` means the row exists in `crm_contacts` and has neither of those two predicates. Repeated source values are ORed within the source group; repeated origin values are ORed within the origin group; the source and origin groups are ANDed with every other filter. Origins use the definitions in the enum comments, with `recovered` allowed to overlap `lead_backed`; `legacy_only` and `internal_only` are mutually exclusive terminal classifications.

SmartView semantics are fixed. `never_contacted` is the conjunction of all of these executable predicates:

1. `lower(trim(CRMContact.stage)) = 'lead'`.
2. The authoritative capture is the contact's latest `CRMContactCapturePosition` ordered by `(captured_at IS NULL) ASC, captured_at DESC, id DESC`; its one `timeline` section must have `capture_quality='complete'`, `is_empty=true`, `row_count=0`, and canonical `limitations_json='[]'`.
3. `CRMContactProfile.last_contacted_at IS NULL`.
4. No `CRMContactTimelineEvent` exists for the contact, and no non-mirrored `CRMActivity` exists for it with `kind` in the exact immutable `CONTACT_TOUCH_ACTIVITY_KINDS = frozenset({'call', 'email', 'sms', 'text', 'meeting', 'contacted'})`. A mirrored activity is already represented by its source-linked timeline event and does not alter the result.

No capture, a missing timeline cell, `partial|shell|error`, a non-empty/limited/contradictory complete cell, or any last-contact evidence makes the predicate false; unknown evidence is never labeled never contacted. A null capture timestamp does not erase a complete observation: the final `id DESC` tie-break still selects one authoritative capture deterministically. SQL uses correlated `EXISTS`/`NOT EXISTS` predicates against that selected capture and does not infer from `CRMContact.created_at`, lead creation, notes, tasks, tags, or current time. Service tests independently pin every clause, a complete null-time capture, two capture revisions with only the latest authoritative, a prior recovered event despite a later empty cell, every internal touch kind, non-touch administrative activities, mirrored activities, and reversed fixture insertion order. `recently_active` means an explicit last-interaction timestamp in `[now-30 days, now]`. Birthday/anniversary views use explicit month/day from the internal date first, otherwise an exposed recovered profile month/day; sentinel/yearless years remain null. The two month views use the injected `now` month. No tag, task title, name, or current date supplies a missing celebration/contact timestamp.

Sort uses the requested primary expression, then case-folded last name, case-folded first name, then contact ID. Null values are always last in either direction; contact ID follows the requested direction. `name` sorts by case-folded last name, first name, then ID. Literal search escapes `%`, `_`, and `\\` and searches first name, last name, legal/preferred name, normalized methods, company, and title; it never interpolates SQL.

- [ ] **Step 2: Write failing directory/detail/section/evidence/mutation tests**

Expose these exact async functions; service exceptions are typed domain errors and contain no HTTP concerns:

```text
async list_contacts(db, filters: ContactDirectoryFilters, *, now: datetime) -> ContactDirectoryPage
async get_contact_detail(db, contact_id: int) -> ContactDetail
async get_contact_neighbors(db, contact_id: int, filters: ContactDirectoryFilters, *, now: datetime) -> ContactNeighbors
async get_contact_workspace_summary(db, contact_id: int) -> ContactWorkspaceSummary
async list_contact_section(db, contact_id: int, section: ContactSection, *, page: int, page_size: int) -> ContactSectionPage
async get_contact_evidence(db, contact_id: int) -> ContactEvidence
async list_contact_celebrations(db, *, month: int) -> ContactCelebrations
async create_contact(db, payload: ContactCreateCommand, *, actor_subject: str) -> ContactDetail
async update_contact(db, contact_id: int, payload: ContactUpdateCommand, *, actor_subject: str) -> ContactDetail
async apply_contact_bulk_action(db, payload: ContactBulkCommand, *, actor_subject: str) -> ContactBulkResult
async sync_legacy_leads(db, *, actor_subject: str) -> ContactLegacySyncResult
async import_contacts(db, payload: ContactImportCommand, *, actor_subject: str) -> ContactImportResult
async assign_contact_tag(db, contact_id: int, tag_id: int, *, actor_subject: str) -> ContactMutationResult
async remove_contact_tag(db, contact_id: int, tag_id: int, *, actor_subject: str) -> ContactMutationResult
async create_contact_note(db, contact_id: int, payload: ContactNoteCreateCommand, *, actor_subject: str) -> ContactMutationResult
async delete_contact_note(db, contact_id: int, note_id: int, *, actor_subject: str) -> ContactMutationResult
async create_contact_saved_search(db, contact_id: int, payload: ContactSavedSearchCreateCommand, *, actor_subject: str) -> ContactMutationResult
async list_saved_searches(db) -> tuple[ContactSavedSearchValue, ...]
async delete_saved_search(db, search_id: int, *, actor_subject: str) -> SavedSearchDeletionResult
async ingest_archive_contacts(db, contacts: tuple[ContactImportRowCommand, ...], referenced_child_emails: tuple[str | None, ...], *, actor_subject: str) -> _ArchiveContactIngestResult
```

`_ArchiveContactIngestResult` is private to `command_contacts.py`, is excluded
from `__all__`, and is never a FastAPI response or JSON-serializable contract.
It contains only `created: int`, `skipped_duplicates: int`, and an immutable
`owner_contact_ids_by_normalized_email: Mapping[str, int | None]`. The keys are
canonical primary-email values from this request only; a positive value is the
sole owner contact ID and `None` means ambiguous or unresolved. Raw emails,
contact objects, names, and provider values never enter the map. The retained
archive router consumes the map only to assign child `contact_id` foreign keys
inside the same request transaction and discards it before constructing the
existing public `ArchiveBundleImportResult`.

Task 5C also exposes exactly
`async count_contact_bookings(db, contact_id: int) -> int` from
`command_contact_timeline.py`; it is the shared, framework-neutral Task 5B
booking ownership/count helper used by `get_contact_workspace_summary`. It
validates a positive exact integer contact ID, loads `CRMContact` and its
optional `Lead` together, applies `_require_contact_email_integrity`, raises
`ContactNotFound` for an absent contact, and raises
`ContactTimelineIntegrityError` for a non-null missing lead. For a lead-backed
contact it reuses the exact Task 5B linked-booking drift scan: PK keyset pages
of at most 1,000 for that single `lead_id`, ordered by ID, validating
`canonical_email(Booking.email) == Booking.normalized_email`; the helper
returns the number of validated rows rather than issuing an unvalidated
count. For a leadless contact, null canonical email or a canonical primary
email with zero/multiple `CRMContact` owners returns zero. Exactly one owner
must be this contact; then matching `lead_id IS NULL` bookings are scanned by
the indexed `(scheduled_at ASC, id ASC)` keyset in pages of at most 1,000,
each raw/derived email pair is validated, and the validated row count is
returned. `CRMContactMethod` never participates. Both scans are
`O(ceil(n/1000))`, retain at most one batch, use no float timestamp conversion,
and emit no raw email in errors/logs. The existing page-sized Task 5B timeline
fetch remains unchanged; only this whole-domain count helper may issue a
row-dependent number of integrity queries. Tests cover 0, 1, 1,001, and 2,001
rows, equal scheduled timestamps across a page boundary, lead/leadless paths,
ambiguous owners, raw/derived drift on the final page, missing lead, constant
1,000 batch size, and no `CRMContactMethod` fallback.

`get_contact_detail` accepts only a positive exact integer and otherwise uses
the same privacy-safe `ContactNotFound("contact does not exist")` as an absent
row. Under `db.no_autoflush`, it loads the contact directly (never by walking
directory pages) and batch-loads profile, methods, addresses, ownerships,
tags, and all candidate recovered contact-profile links. A recovered link is
valid only when its source exists with
`source_system="kw_command", module="contacts",
record_kind="contact_profile"` and targets this exact contact. Profile and at
least one valid recovered link must either both exist or both be absent;
missing/wrong-domain/dangling/other-contact or ambiguous target links fail as
`ContactDataIntegrityError`, with no partial DTO. `ContactDetail.contact` is
built by the same directory-row projector. Its merged celebrations retain
internal-date precedence, while `ContactRecoveredProfile.birthday` and
`.anniversary` independently expose only the recovered observation (verified,
yearless, or sentinel), even when the contact row has an internal date.
Addresses order `is_primary DESC, id ASC`; ownership orders role
`owner, assignee, collaborator`, then `is_primary DESC, id ASC`; tags order
case-folded name then ID. Only DTO fields are projected: never `source_key`,
raw celebration text, parser payload, provider contact ID, or archive path.
One-row and 100-child fixtures execute the same bounded number of SELECTs
(at most eight), and tests cover empty optional associations, internal-only,
valid recovered, profile/link mismatch in both directions, wrong-domain and
cross-contact links, deterministic ordering, internal/recovered celebration
separation, no autoflush/DML, and privacy-safe exceptions.

Task 5C-D is the bounded section/evidence slice. `list_contact_section`
accepts page `>=1` and page size `1..100`. It rejects
`ContactSection.TIMELINE` with `ContactSectionUnsupported` before issuing a
query because Task 5B is the sole timeline API. Its complete accepted tab
matrix is exactly the seven non-timeline enum values below; those seven tabs
project to exactly five DTO kinds:

```text
opportunities   -> ContactOpportunityOccurrence(kind="opportunity")
smart_plans     -> ContactSmartPlanOccurrence(kind="smart_plan")
notes           -> ContactNoteOccurrence(kind="note")
saved_searches  -> ContactSavedSearchOccurrence(kind="saved_search")
tasks_to_do     -> ContactTaskOccurrence(kind="task", state="to_do")
tasks_completed -> ContactTaskOccurrence(kind="task", state="completed")
tasks_archived  -> ContactTaskOccurrence(kind="task", state="archived")
```

Timeline plus these seven values remains the immutable eight-cell capture
matrix; the three task states are separate captured sections but share one
typed task DTO. No sixth occurrence DTO, generic row, unknown section, or
timeline alias is accepted. Every accepted section queries
`CRMContactSourceOccurrence`, never text, and first proves that occurrence,
section capture, capture position, and requested contact all share the same
contact ID and that the section name matches the occurrence record kind.
Each row is a discriminated union: `source_only` includes `source_record_id`,
the exact source-key hash above, section, occurrence ordinal, capture quality,
captured time, and the whitelisted typed value; `materialized` additionally
includes one validated `CRMEntitySource` target. The compatibility/ownership
matrix is exact: opportunity -> an opportunity joined to this contact by
`CRMOpportunityContact`; smart plan -> this contact's
`CRMSmartPlanEnrollment`; note -> this contact's `CRMNote`; saved search ->
this contact's `CRMSavedSearch`; every task section -> this contact's
`CRMTask`. Timeline-event links are not accepted by this function. Zero
compatible targets is source-only; exactly one is materialized. A missing
target row, incompatible entity type, target owned by another contact, or
multiple targets is `ContactDataIntegrityError`, not source-only. Raw source
keys, provider IDs, parser payloads, and archive paths are never response
fields. Rows order by section capture time descending nulls last, capture
ordinal ascending, occurrence ordinal ascending, then
`CRMContactSourceOccurrence.id ASC`.

The global integrity preflight over the requested section's full occurrence
universe is structural/link/ownership-only: it validates section/position/
contact agreement, source-link cardinality, compatible target existence and
same-contact ownership, but it does not parse every occurrence's payload JSON.
The single strict source-occurrence projector defined in Step 1 applies only
to rows emitted by the requested page after pagination. Every emitted row,
including a materialized row, passes through it before its DTO is built;
malformed/non-object payload or `values`, missing required title, over-bound
text, unsafe criteria, and invalid RFC3339 input follow that projector's exact
fail/nullable rules rather than ad hoc coercion. This split avoids an
unbounded full-payload scan while preserving fail-closed global ownership and
link integrity. A seven-section test matrix
asserts all five discriminants and the three task states, source-only and
materialized ownership for each compatible type, every strict payload rule,
and that no private payload value reaches a DTO or exception.

The section service uses a shared ownership predicate for count and page,
loads page occurrences, all source links, and all compatible targets in
set-based batches, and performs no per-row query. One occurrence and 101
occurrences must execute the same number of SELECTs and no DML/autoflush; each
call is capped at 10 SELECTs, excluding no operation because timeline and
invalid page arguments fail before querying. SQL-capture tests assert the
1-versus-101 invariant independently for each of the seven sections and prove
page `2` materialization does not consult page `1` rows.

`get_contact_workspace_summary` uses the same ownership validator rather than
adding persisted and recovered counts blindly. For each non-timeline section,
it counts the union of all contact-owned internal rows plus only source-only
occurrences; a compatible materialized occurrence contributes its internal
row once, and an invalid link fails closed. Task states map exactly from
`CRMTask.status`: `open` to `open_tasks`, `completed` to `completed_tasks`, and
`archived` to `archived_tasks`; an unknown status is integrity error. Active
Smart Plans are internal enrollments with case-folded status `active` plus
source-only occurrences whose projected status case-folds to `active` (null or
another status is not active). Opportunities, notes, and saved searches count
all contact-owned internal rows plus their source-only occurrences. Bookings
must call the shared Task 5B `count_contact_bookings(db, contact_id)` helper,
which applies the same lead-linked ownership, canonical-email fallback,
ambiguity/drift preflight, and missing-lead integrity rules as timeline
collection; this service must not repeat a raw/lower-email lookup. Tests cover
zero/one/many source-only rows, materialized de-duplication, cross-contact and
dangling links, unknown task state, inactive/null Smart Plans, and both Task
5B booking linkage paths.

The summary validator begins with all occurrences owned by the requested
contact and batch-joins each occurrence through its section capture, capture
position, and source record. Every joined row must share that contact ID; the
source must be `kw_command/contacts`, and the only accepted record-kind/section
pairs are `contact_opportunity/opportunities`,
`contact_smart_plan/smart_plans`, `contact_note/notes`,
`contact_saved_search/saved_searches`, and `contact_task` with exactly one of
`tasks_to_do|tasks_completed|tasks_archived`. Timeline occurrences are not in
the summary domain. Load *all* `CRMEntitySource` rows for those source IDs in
one batch, not just expected entity types. Zero links means source-only.
Exactly one compatible link is materialized only after its target exists and
is owned by this contact: `CRMTask.contact_id`, `CRMNote.contact_id`,
`CRMSavedSearch.contact_id`, `CRMSmartPlanEnrollment.contact_id`, or an
existing `CRMOpportunity` joined to this contact by
`CRMOpportunityContact`. Any extra/wrong-type link, missing target,
cross-contact target, source reused by two occurrences, or disagreement among
occurrence/section/position/source fails closed before constructing a result.

Internal task counts accept only exact statuses `open|completed|archived`;
source-only task state comes only from its owning section. Internal active
Smart Plans use `status.strip().casefold() == "active"`; source-only rows use
the safe projected status with the same comparison, and null/other status is
inactive. Opportunities count distinct contact-owned opportunity IDs (so two
roles do not double count); notes and contact-owned saved searches count rows.
Each compatible materialized target is already in the internal set and adds
zero; each source-only occurrence adds exactly one to its domain. Global saved
searches never count. Booking failures are translated to the Task 5C
privacy-safe not-found/integrity taxonomy without exposing an email or lead
value. Normalized counts, occurrence/link preflight, and target ownership use
set-based aggregate/`IN` queries with the five revision `7d1f3a5b6c8e`
indexes and never `db.get()` per occurrence. SQL-capture tests compare one
row with 101 rows and require the same non-booking SELECT count; only the
documented 1,000-row booking integrity scan may scale with data. The matrix
tests independently cover every internal-only, source-only, materialized, and
mixed union; duplicate opportunity roles; all task states; active casing;
global searches; every wrong/multiple/dangling/cross-contact link; source and
section mismatch; booking ambiguity/drift/missing lead; and prove an integrity
failure returns no partial summary.

`get_contact_evidence` computes every aggregate from live normalized rows; the
historical `317/317/0` and `51/2/49` values are acceptance expectations, never
constants. `provider_contact_rows` is the number of distinct capture-position
source records. `resolved_provider_identities` is the number of distinct
contacts reached by those positions after resolving each position to its
canonical profile source as follows. Parse only
`CRMSourceRecord(source_system="kw_command", module="contacts",
record_kind="contact_profile").payload_json` as an object, require its
top-level `source_contact_id` to be exactly 24 lowercase hexadecimal
characters, and match it exactly to
`CRMContactCapturePosition.source_contact_id`. That canonical profile source
must have exactly one `CRMEntitySource(entity_type="contact")`, its target
`CRMContact` must exist, and the target ID must equal the position's
`contact_id`. Missing/duplicate profile resolution, malformed payload,
zero/multiple contact targets, dangling target, or cross-contact target is a
privacy-safe `ContactDataIntegrityError`. Resolution never interprets
`CRMSourceRecord.source_key`, display label, URL, name, email, position, or
artifact path as an identity convention, and Task 5C-D adds no profile-source
foreign key. The provider ID is used only for this internal equality check and
never appears in a DTO, error, audit, or log. `coalesced_aliases` is
`provider_contact_rows - resolved_provider_identities`; any negative or
nonzero result is integrity error because the DTO permits only literal zero.
`lead_backed_contacts` is the distinct set of contacts with non-null `lead_id`.
A `reviewed_overlap` is a distinct lead-backed contact with both (a) that exact
validated profile-source mapping and (b) a same-contact
`CRMContactAuditEvent(action="command_contact_overlap_reviewed")`; neither an
audit without the mapping nor a mapping without the audit counts.
`legacy_only_contacts` is the lead-backed set minus the reviewed-overlap set,
after proving the overlap set is a subset. Tests remove/add mappings and audit
rows to prove the aggregates change or fail integrity; no fixture can pass by
returning literals.

The evidence detail returns every requested-contact capture position ordered
by `(capture_ordinal ASC, id ASC)`. Each position contains exactly eight
uniquely named cells in this immutable `ContactSection` enum order:
`timeline`, `opportunities`, `smart_plans`, `notes`, `saved_searches`,
`tasks_to_do`, `tasks_completed`, `tasks_archived`. The flattened
`section_matrix` uses the same position order and then that enum order; neither
database insertion order nor lexical section order is observable. It verifies
all position/profile/section/source IDs and contacts agree, every section
source is the declared Contacts record kind, `row_count >= 0`,
`is_empty=true` implies `row_count == 0`, `row_count > 0` implies
`is_empty=false`, a complete cell with zero rows is explicitly empty, and the
count of owned occurrences equals `row_count` for the same section capture.
`limitations_json` is a canonical JSON array of unique strings.
Missing/duplicate cells, malformed limitations, cross-contact links, or any
strict seven-non-timeline-tab occurrence projection failure is an integrity
error; timeline bodies remain owned by Task 5B and are never fabricated from
cell text.

`ContactEvidence.sources` is the distinct union for the requested contact of
exactly: (1) canonical `contact_profile` sources resolved by payload
`source_contact_id` and the same-contact entity link above, (2) every capture
position's `source_record_id`, (3) all eight section captures'
`source_record_id` values, and (4) all owned occurrence `source_record_id`
values. It excludes workspace-global/unrelated entity sources and contains
each source once, ordered by `CRMSourceRecord.id ASC`.
`ContactSourceMetadata` exposes only internal `source_record_id`,
`record_kind`, `evidence_level`, `capture_quality`, nullable `captured_at`, and
safe artifact entries. Each source's artifact entries are distinct and ordered
by `CRMArchiveArtifact.id ASC`; a duplicate source/artifact link, dangling
artifact, nonpositive ID, invalid/empty artifact type,
non-lowercase/non-64-hex SHA-256, or negative size is an integrity error.

Artifact queries select only artifact ID/type/SHA/catalog size and the
DB-computed `length(content_bytes)` scalar; they never select, defer-load, or
materialize `CRMArchiveArtifact.content_bytes`. When `content_bytes IS NOT
NULL`, its database-computed byte length must equal `size_bytes`. When the blob
is null, retain the nonnegative ingestion-verified size and SHA from the
immutable artifact catalog without pretending the bytes are present and
without reopening a source/archive path. Each DTO constructs only
`/api/v1/command/archive/artifacts/{artifact_id}/content`; filename, source
key, provider identifier, source/archive path, preview, payload, stored URL,
and bytes are excluded. Tests place a sentinel secret in every forbidden
column and in a non-null blob, prove only the DB-side length scalar is read,
prove nullable-blob metadata remains available, and prove no secret appears in
the DTO, exception, SQL parameter log, or serialized response.

Aggregate quality is `limitation` when the requested contact has zero capture
positions. Otherwise it is `complete` only when every required cell is
complete, `partial` only when at least one cell is partial and no cell is
shell/error, and `limitation` for any shell/error cell. This is not vacuous:
zero positions can never yield `complete`.

The evidence service uses set-based queries for positions, cells, occurrences,
profile resolution, source union, source/artifact links, artifact catalog
metadata/DB-side blob lengths, and aggregate sets; it performs no query per
position, cell, source, or artifact and runs under `db.no_autoflush`. One
position and 101 positions execute the same number of SELECTs and no DML; each
call is capped at 14 SELECTs. Tests reverse fixture insertion order, use 101
positions with all eight cells and artifacts, assert every deterministic order
above, and independently cover zero-position limitation, profile-payload
resolution without relying on source keys, all source-union categories,
missing/duplicate/cross-contact links, all cell/cardinality contradictions,
artifact mismatch/null-blob rules, query count, and privacy redaction.

Celebrations merge internal and recovered observations per
`(contact_id, kind)`. A non-null internal `CRMContact.birthday` or
`anniversary` wins and returns its real year with `year_quality="verified"` and
`origin="internal_crm"`. Otherwise an explicitly exposed recovered month/day
returns `origin="recovered"`; a verified recovered year may be returned, a
yearless observation returns `year=None,year_quality="yearless"`, and the
source sentinel `1900` returns `year=None,year_quality="sentinel"`. The service
never constructs or persists `date(1900, ...)`, never copies a recovered date
into either CRMContact date column, and does not substitute the current year.
Missing/invalid month/day, `unknown`, tags, or task text create no row. Rows
order by day, case-folded display name, and contact ID. Tests prove internal
precedence, leap-day behavior, sentinel/yearless rendering, unchanged null CRM
date columns, and no flush or mutation during this read.

Task 5C-E is the mutation/audit slice. Every public mutation service validates
`actor_subject` before its first query: it must be an exact `str`, contain
`1..255` characters, be ASCII decimal digits only, represent an integer greater
than zero, and equal `str(int(actor_subject))`. It is never trimmed; `"01"`,
Unicode digits, whitespace, signs, booleans, integers, and empty/over-bound
values fail validation. The FastAPI `get_db` dependency owns the request's
outer commit/rollback. A handler neither starts nor commits another outer
transaction. Each service call uses exactly one top-level service-owned
`db.begin_nested()` mutation savepoint, performs all of its locks, business
writes, compatibility activities, and audits inside it, calls `flush()`, and
never calls `commit()`. The only permitted nested savepoint inside that
mutation savepoint is the exact tag-assignment uniqueness-race handler below.
Domain, constraint, activity, or audit failure rolls that complete savepoint
back before re-raising; a later archive-child failure still causes `get_db` to
roll back the released contact-ingest savepoint with the rest of the outer
request transaction.

Lock order is binding. A mutation locks all requested `CRMContact` rows with
`FOR UPDATE` in ascending contact ID before locking its referenced tag, note,
or saved-search row. `update_contact` locks its one contact before reading the
old snapshot. Tag assignment/removal and note/search creation lock the contact
before checking the secondary row. Note deletion locks the requested contact,
then loads the note with `WHERE id=:note_id AND contact_id=:contact_id FOR
UPDATE`. `delete_saved_search` may first read only its candidate `contact_id`;
for a contact-owned row it then locks that contact followed by the search and
revalidates unchanged ownership, while a global row locks only the search.
Changed ownership is an integrity conflict, not a retry with a different
owner. A missing contact/tag/child raises the typed, privacy-safe not-found
error with no write; a child owned by another contact is indistinguishable
from missing.

`update_contact` with equal effective values, assigning an existing tag,
removing an absent tag, and a bulk per-contact row already in the requested
state are explicit no-ops: they write neither compatibility activity nor
audit. An existing assignment returns its link ID; absent removal returns
`record_id=None`; both return
`changed=False,audit_entity_type=None,audit_event_id=None`. This absent-removal
rule intentionally replaces the legacy route's 404. A replay means the service
re-evaluates these exact no-op rules; there is no idempotency token and a no-op
replay never creates another activity/audit.

Bulk locks every unique requested contact in ascending ID in one statement,
requires the returned ID set to equal the request, then locks the referenced
tag when the action uses one. It batch-loads existing assignments, changes and
audits only actioned contacts, and returns requested/actioned IDs sorted. One
and 200 contacts execute the same fixed number of SELECT statements; there is
no per-contact read. Any missing member, uniqueness error other than the exact
handled assignment race, or audit/activity failure rolls the whole bulk back.
For standalone and bulk tag add, the insert itself is wrapped in an inner
savepoint so an exact `uq_crm_contact_tag` conflict cannot poison the mutation
savepoint. The losing transaction rereads that exact `(contact_id, tag_id)`
assignment and returns the existing-link no-op with no audit; any different
constraint error is re-raised. Concurrent zero-owner contact creation by email
is not serialized because `normalized_email` is deliberately non-unique; that
cross-session deduplication is outside this contract.

Deleting a materialized `CRMNote` or `CRMSavedSearch` never leaves a dangling
provenance target. Under the same locks/savepoint, load every
`CRMEntitySource` targeting exactly `("note", note.id)` or
`("saved_search", search.id)`. Zero links is valid. Exactly one link is valid
only when its source is `kw_command/contacts` with record kind
`contact_note`/`contact_saved_search` respectively and its current
`CRMContactSourceOccurrence` belongs to this same contact and matching section.
Delete that one link before deleting the internal row, leaving the immutable
source/occurrence so the section renders it as `source_only`. Multiple target
links, a wrong-domain/kind/section owner, a dangling source/occurrence, or a
source linked to another contact is `ContactDataIntegrityError` and rolls back
the deletion. `list_saved_searches` parses criteria through the canonical JSON
contract and orders exactly `updated_at DESC, id DESC`.

Preserve these existing internal timeline compatibility activities, with
`source_record_id=NULL`, `metadata_json='{}'`, and the exact fixed, non-private
kind/summary below, inside the same savepoint as the business row and audit:

```text
create contact       contact_created          Contact created in Command workspace
stage-only update    stage_changed             Contact stage changed
other update         contact_updated           Updated contact profile
remove tag           tag_removed               Removed a contact tag
create note          note                      Added a contact note
delete note          note_removed              Removed a contact note
legacy sync marker   lead_imported             Imported from internal lead source
contact import       contact_imported          Imported through internal CRM import
archive import       archive_contact_imported  Imported from permitted archive bundle
```

An effective update writes exactly one of the two update activities. The sync
marker is itself the compatibility activity and is not duplicated. No activity
is invented for tag assignment, saved-search creation/deletion, bulk actions,
or any no-op because the existing routes define none; global saved-search
deletion's separate workspace activity remains its audit exception below.

`sync_legacy_leads` treats only the exact marker
`CRMActivity(contact_id=<contact>, kind='lead_imported',
source_record_id=NULL, summary='Imported from internal lead source',
metadata_json='{}')` as synchronized; every other activity is irrelevant.
Existing linked contacts retain every base column, including `lead_id`, names,
email/`normalized_email`, phone, stage, dates, and timestamps, byte-for-byte.
For a new unlinked lead, compute parts with the legacy expression
`(lead.name or "Unnamed contact").strip().split(maxsplit=1)`, require a nonempty
first part, use its first item as `first_name`, its optional second item as
`last_name` (otherwise `""`), use the raw lead email/phone, and use
`lead.routing_status or "lead"` as stage. Pass those exact values through
`ContactCreateCommand` and the canonical-email model invariant; never truncate,
repair, or copy recovered values. An empty-after-strip or over-bound legacy
value is a privacy-safe integrity error and rolls back the whole sync.

Scan `Lead` with `WHERE id>:last_id ORDER BY id ASC LIMIT 500 FOR UPDATE`.
For each nonempty batch, batch-load and lock linked contacts in ascending ID and
batch-load exact markers; never query per lead/contact and retain at most one
500-lead batch. The SELECT formula is exactly three per nonempty batch plus one
terminal Lead query: `3 * ceil(n / 500) + 1` for `n>0`, and one for `n=0`.
Create one contact+marker+`contact.legacy_sync_applied` audit for an unlinked
lead. Add one marker+backfill audit for an existing linked contact missing the
exact marker. A contact with at least one exact marker is unchanged. The result
counts created contacts, backfilled markers, and the leads actually scanned;
the second identical run is a zero-write no-op. Unit gates cover 51 existing
distinct lead-backed rows and 1, 501, and 1,001 leads without hard-coding 51 in
runtime logic.

Both contact import paths use one shared primary-email owner resolver. Collect
only non-null canonical keys from the request, sort them, and process batches
of at most 500. A window/aggregate query returns at most two owner IDs per key;
then a second bounded query locks only sole-owner rows and verifies
`canonical_email(contact.email) == contact.normalized_email`. Two returned
owners classify a key as ambiguous without loading the rest; sole-owner drift
is a privacy-safe integrity failure. No query loads all emailed contacts, and
`CRMContactMethod` never participates.

For `import_contacts`, a persisted sole or ambiguous key skips every input row
with that key. When no persisted owner exists, the first input-order row for a
non-null canonical key is created and later same-key rows are skipped. A null
canonical key never deduplicates, so every such input row is created. The
entire `1..1,000`-row request is one savepoint; every created contact receives
the exact `contact_imported` activity and one
`contact.legacy_import_applied` audit. An audit/activity failure rolls back the
whole request, including earlier rows. Existing contacts, especially all 51
lead-backed rows and their `lead_id`/base columns, are never changed.

`ingest_archive_contacts` applies the same resolver to the archive contact rows
plus every child-reference email before any archive child write. It processes
contact rows in input order with the same sole/ambiguous/first-wins/null rules,
creates the exact `archive_contact_imported` activity and one
`contact.archive_import_applied` audit per created contact, and returns only the
private request-scoped result defined above. The retained monolithic
`/archive/import` handler passes the unchanged validated admin subject,
consumes its owner-ID map for tasks/notes/opportunities/referrals/agreements,
then performs the remaining existing bundle writes. It preserves the existing
public counts/unresolved-reference response and the `10,000`-row archive schema
bounds. No owner map or canonical/raw email is serialized or logged. Any later
child failure rolls back contacts, activities, audits, and all archive children
through the request's outer transaction; all 51 lead-backed rows remain
unchanged.

Audit fingerprints use one exact helper
`redact_contact_audit_value(value: str | None, *, domain: ContactAuditDomain)`,
abbreviated `F(domain, value)`. `ContactAuditDomain` accepts only these seven
exact ASCII strings, with no trimming or aliases:

```text
command-contact-audit-v1:first_name
command-contact-audit-v1:last_name
command-contact-audit-v1:email
command-contact-audit-v1:phone
command-contact-audit-v1:note_body
command-contact-audit-v1:saved_search_name
command-contact-audit-v1:saved_search_criteria
```

For `None`, `raw_utf8=b""` and `present=false`; otherwise `type(value) is str`,
`raw_utf8=value.encode("utf-8")`, and `present=true`. Any bytes, mapping,
sequence, number, boolean, arbitrary object, non-ASCII/unlisted domain, or
trimmed domain is rejected. `F` returns exactly
`{"present":present,"length":len(raw_utf8),"sha256":sha256(domain.encode("ascii") + b"\0" + raw_utf8).hexdigest()}`;
length is UTF-8 bytes, not Unicode code points. Saved-search criteria enter `F`
only as canonical compact JSON text.

Replace the permissive generic audit validator with an action-aware builder:

```python
canonical_contact_audit_json(
    *, action: ContactAuditAction,
    phase: Literal["before", "after"],
    payload: Mapping[str, object],
) -> str

canonical_workspace_saved_search_activity_json(
    *, actor_subject: str,
    search_id: int,
    name: str,
) -> str
```

The contact builder accepts only the exact action/phase shape listed below,
validates every key and value, and then sorts keys with compact separators and
`allow_nan=False`. A fingerprint-shaped mapping under an unlisted key, an
arbitrary boolean/`*_id`, or an action valid under the wrong phase is rejected.
`lead_id` is a positive integer only in the two
`contact.legacy_sync_applied` shapes; `activity_id` is positive only in that
action's marker-backfill `after`. `actor_subject` is forbidden from every
contact JSON mapping and is stored only in `CRMContactAuditEvent.actor_subject`.
The workspace serializer is separate: it first applies the exact actor
validation above and permits the actor only in its one exact metadata mapping.
Task 4's independently specified `command_contact_overlap_reviewed` audit
continues to use its reconciliation serializer and is not accepted by these
Task 5C-E builders.

The exact contact-field encoder maps first/last/email/phone through their
corresponding `F`, stage to the raw validated string, birthday/anniversary to
ISO date or null, and the permitted IDs to positive integers. Raw values are
otherwise allowed only for the exact action, lexically sorted changed-field
names, dates, stage, and booleans. Names, email, phone, note bodies, search
names/criteria, import values, tokens, provider IDs, source keys/payload,
artifact/manifest data, and timeline text are forbidden from audit JSON,
exceptions, and logs.

Define `S(action, fields, row)` as exactly `action`, `changed_fields` as the
lexically sorted nonempty JSON list of `fields`, and one same-named encoded key
per field. No other key is permitted. The canonical action/phase contracts are:

- `contact.created`: before `{}`; after `S` over exactly
  `anniversary,birthday,email,first_name,last_name,phone,stage`;
- `contact.updated`: before/after `S` over exactly the effective changed fields
  from the old/new row;
- `contact.legacy_sync_applied` for a newly linked contact: before `{}`; after
  `S` over exactly `email,first_name,last_name,phone,stage,lead_id`;
- `contact.legacy_sync_applied` for marker backfill: before exactly
  `{"action":"contact.legacy_sync_applied","activity_present":false,
  "lead_id":lead_id}`; after the same keys with `activity_present=true` and
  positive `activity_id` added;
- `contact.legacy_import_applied`: before `{}`; after `S` over exactly
  `anniversary,birthday,email,first_name,last_name,phone,stage`;
- `contact.archive_import_applied`: before `{}`; after `S` over exactly
  `anniversary,birthday,email,first_name,last_name,phone,stage`;
- `contact.bulk_stage_set`: before/after exactly
  `{"action":"contact.bulk_stage_set","stage":old_or_new}`;
- `contact.bulk_tag_added`, `contact.bulk_tag_removed`, `contact.tag_added`, and
  `contact.tag_removed`: before/after exactly
  `{"action":exact_action,"present":old_or_new_bool,"tag_id":tag_id}`;
- `contact.note_created` and `contact.note_deleted`: before/after exactly
  `{"action":exact_action,"body":F("command-contact-audit-v1:note_body",body),
  "note_id":note_id,"present":old_or_new_bool}`;
- `contact.saved_search_created` and `contact.saved_search_deleted`:
  before/after exactly
  `{"action":exact_action,
  "criteria":F("command-contact-audit-v1:saved_search_criteria",canonical_criteria),
  "name":F("command-contact-audit-v1:saved_search_name",name),
  "present":old_or_new_bool,"search_id":search_id}`.

This is 14 canonical Task 5C-E contact action strings. Because
`contact.legacy_sync_applied` has distinct new-contact and marker-backfill
shapes, the snapshot matrix contains exactly 15 contact action/shape cases,
plus the one workspace action below. Create/import/archive/sync write one audit
per created/backfilled contact; bulk writes one per actioned contact; every
other changed contact mutation writes one. `create_contact` and
`update_contact` still return `ContactDetail`; their audit IDs are verified in
the database and are not added to that DTO. Only `ContactMutationResult` and
`WorkspaceMutationResult` expose `audit_entity_type`/`audit_event_id`; changed
contact mutation results use `contact_audit` and the flushed audit row ID.
No-op results expose neither and write no activity/audit.

For `delete_saved_search`, a contact-owned search follows the link/ownership
rules and contact audit above and returns `ContactMutationResult`. The sole
global exception is a locked legacy row with `contact_id IS NULL`: delete it,
create no contact audit, and write exactly
`CRMActivity(contact_id=NULL,kind="workspace.saved_search_deleted",
source_record_id=NULL,summary="Saved search deleted",metadata_json=<canonical>,
created_at=<server default>)`. The separate workspace serializer emits exactly
`{"action":"workspace.saved_search_deleted","actor_subject":actor_subject,
"saved_search":F("command-contact-audit-v1:saved_search_name",name),
"search_id":id}`. It returns
`WorkspaceMutationResult(record_id=id,changed=True,
audit_entity_type="workspace_activity",audit_event_id=activity.id)`. A missing
global/contact search raises not found; deletion is never a no-op. Tests prove
the workspace mapping contains no contact field, criteria, or raw name; every
other actor occurs only in `actor_subject`; and every activity/audit failure
rolls back its business row and provenance-link change.

- [ ] **Step 3: Implement source/materialized joins, exact pagination, and commits**

Use count and page queries with the same predicates. Return page count `ceil(total/page_size)` with `0` when total is `0`; a page beyond the last returns an empty row tuple without changing the requested page. `get_contact_neighbors` locates the contact in exactly the same filter/sort universe and returns adjacent IDs or null; if the contact is outside that universe, raise `ContactNotInDirectory`.

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contact_contracts.py \
  tests/test_command_contacts_models.py \
  tests/test_command_contact_summary_migration.py \
  tests/test_command_contacts_service.py \
  tests/test_command_contact_timeline.py \
  tests/test_command_contact_occurrences.py
"$PROJECT_PYTHON" -m alembic heads
git add models/command.py services/command_contact_contracts.py \
  alembic/versions/7d1f3a5b6c8e_add_contact_workspace_summary_indexes.py \
  services/command_contact_timeline.py services/command_contacts.py \
  tests/test_command_contact_contracts.py tests/test_command_contacts_models.py \
  tests/test_command_contact_summary_migration.py \
  tests/test_command_contact_timeline.py tests/test_command_contacts_service.py
git commit -m "feat: query Command contact workspaces"
```

- [ ] **Step 4: Implement and verify the Task 5C-E mutation/audit slice**

Write `test_command_contact_mutations.py` and extend the contract tests before
implementing the service methods. The acceptance matrix is binding:

1. Snapshot all 15 contact action/shape cases and the one workspace action as
   exact before/after canonical strings. Independently reject Unicode
   code-point length in place of UTF-8 byte length, wrong/null/type/domain
   variants, action/phase key smuggling, `lead_id` outside sync, and actor JSON
   outside the workspace serializer.
2. Parameterize every service over `None`, empty, whitespace, signed,
   zero/leading-zero, Unicode-digit, integer/bool, 255-character valid, and
   256-character actor subjects; invalid subjects issue zero SQL.
3. Inject a failure while flushing the audit/activity for create, update, each
   bulk family, sync create/backfill, normal import, archive ingest, tag
   add/remove, note create/delete, contact/global search deletion, and prove
   business row, compatibility activity, provenance-link change, and audit all
   roll back. Patch `AsyncSession.commit` to fail the test if a service calls it.
4. Run simultaneous same-contact tag assignments through two sessions. Assert
   one `CRMContactTag`, one `contact.tag_added` audit, and one existing-link
   no-op. For bulk, compare SQL capture for one versus 200 contacts: equal
   SELECT counts, sorted lock parameters/results, one audit per actioned row,
   and zero persisted changes when one contact/tag is missing.
5. Cover wrong-contact note deletion, absent tag removal, contact-owned/global
   saved-search deletion, zero/one/multiple/wrong-domain source links, exact
   source-link removal to `source_only`, and deterministic saved-search order.
6. Seed 51 distinct lead-backed contacts, snapshot every base column and
   `lead_id`, then sync 51 matching leads plus new/missing-marker cases. Assert
   byte-for-byte preservation, exact marker recognition, audit/activity counts,
   second-run no-op, and no recovered-field write. SQL capture for 1, 501, and
   1,001 leads must match `3 * ceil(n/500) + 1`, use `LIMIT 500`, and contain no
   per-lead/contact query.
7. For normal import and archive ingest, cover sole/ambiguous/drifted persisted
   owners, more than two owners for one key, NFKC equivalents, first-input-row
   within-request winner, null canonical non-deduplication, 1,000-row normal
   import, bounded 500-key owner statements, and archive child references.
   Assert exact activities/actions, private owner-map nonserialization, outer
   rollback after a later archive-child failure, and all 51 lead-backed rows
   unchanged.
8. Prove `birthday`/`anniversary` accept exact `date` values and their nullable/
   `UNSET` variants only, rejecting `datetime`; prove every no-op writes neither
   compatibility activity nor audit.

Run:

```bash
cd backend
"$PROJECT_PYTHON" -m pytest -q \
  tests/test_command_contact_contracts.py \
  tests/test_command_contact_mutations.py \
  tests/test_command_contact_email_writes.py \
  tests/test_command_contacts_service.py
"$PROJECT_PYTHON" -m ruff check \
  services/command_contact_contracts.py \
  services/command_contacts.py \
  tests/test_command_contact_contracts.py \
  tests/test_command_contact_mutations.py
git add services/command_contact_contracts.py services/command_contacts.py \
  tests/test_command_contact_contracts.py tests/test_command_contact_mutations.py \
  tests/test_command_contact_email_writes.py tests/test_command_contacts_service.py
git commit -m "feat(command): add audited contact mutations"
```

Expected: all focused tests and Ruff pass; `git diff --check` is empty. Task 6
then consumes these service contracts without rebuilding audit JSON in a router.

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

`command_contacts.py` owns every contact-scoped URL below. `command.py` must delete the moved handlers rather than retaining aliases. It keeps the unrelated global `POST /tags`, `GET /saved-searches`, `DELETE /saved-searches/{search_id}`, and `POST /archive/import` URLs. The two global saved-search handlers delegate to the exact Task 5C `list_saved_searches()`/`delete_saved_search()` contracts; deletion receives `AdminSubject` and follows the contact-owned/global audit split defined there. `/archive/import` remains exactly once in the monolithic router with its existing request/response contract, receives `AdminSubject`, and delegates contact creation plus request-scoped contact owner resolution to Task 5C-E `ingest_archive_contacts()` before writing the remaining archive children. The handler never serializes/logs the private owner-ID map, never constructs contact audit JSON, and relies on `get_db` for one outer atomic commit/rollback. It must neither be shadowed nor duplicated by the focused router. `main.py` includes each router once under `/api/v1/command`.

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

The legacy `GET /contacts?limit=&offset=&query=&stage=` remains an array with `limit=1..100` and `offset>=0`; it delegates to the service but does not masquerade as the directory page. The task route requires exactly one `state=to_do|completed|archived`. Static-route tests specifically call `/contacts/directory`, `/contacts/import`, `/contacts/bulk`, and `/contacts/sync-leads` and prove none returns an integer-path 422. A compatibility inventory test enumerates every method/path above plus `POST /tags`, `GET /saved-searches`, `DELETE /saved-searches/{search_id}`, and `POST /archive/import`; it asserts one registered route per method/path, the existing `/archive/import` response model, and no behavior-changing redirect or 404/405/422 collision.

Replace dependency-only authentication with a subject-bearing dependency:

```python
async def require_admin_subject(
    claims: dict[str, object] = Depends(require_admin),
) -> str:
    subject = claims.get("sub")
    if (
        not isinstance(subject, str)
        or not 1 <= len(subject) <= 255
        or not subject.isascii()
        or not subject.isdigit()
        or int(subject) <= 0
        or subject != str(int(subject))
    ):
        raise HTTPException(status_code=401, detail="Invalid administrator subject")
    return subject

AdminSubject = Annotated[str, Depends(require_admin_subject)]
```

Every focused route receives `actor_subject: AdminSubject`; read handlers assign it to `_actor_subject`, while mutations pass the unchanged string to Task 5C. The retained global `DELETE /saved-searches/{search_id}` and `POST /archive/import` handlers also receive `actor_subject: AdminSubject` and pass it unchanged to `delete_saved_search()`/`ingest_archive_contacts()`. Tests exercise missing token `401`, a non-admin token `403`, every malformed/missing/noncanonical `sub` case from Task 5C-E as `401`, and a valid unchanged admin subject on focused mutations, global saved-search deletion, and archive import. Do not derive or trim an actor from email, display name, request IP, or a constant service value.

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

class ContactArtifactMetadataOut(BaseModel):
    artifact_id: int = Field(gt=0)
    artifact_type: str = Field(min_length=1, max_length=64)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    content_href: str

class ContactSourceMetadataOut(BaseModel):
    source_record_id: int = Field(gt=0)
    record_kind: str = Field(min_length=1, max_length=64)
    evidence_level: Literal[
        "observed_record", "rendered_occurrence", "displayed_aggregate",
    ]
    capture_quality: Literal["complete", "partial", "shell", "error"]
    captured_at: datetime | None
    artifacts: list[ContactArtifactMetadataOut] = Field(default_factory=list)

class ContactEvidenceOut(BaseModel):
    contact_id: int
    provider_contact_rows: int
    resolved_provider_identities: int
    coalesced_aliases: Literal[0]
    lead_backed_contacts: int = Field(ge=0)
    reviewed_overlaps: int = Field(ge=0)
    legacy_only_contacts: int = Field(ge=0)
    capture_positions: list[ContactCapturePositionOut]
    section_matrix: list[ContactSectionEvidenceOut]
    sources: list[ContactSourceMetadataOut]
    capture_quality: Literal["complete", "partial", "limitation"]

class ContactBulkSetStage(BaseModel):
    action: Literal["set_stage"]
    stage: str = Field(min_length=1, max_length=50)

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

Validate every contact ID as a positive integer and reject duplicate IDs rather than deduplicating them. Define concrete `ContactDetailOut`, `ContactNeighborsOut`, `ContactWorkspaceSummaryOut`, `ContactCelebrationsOut`, `ContactCreateIn`, `ContactUpdateIn`, `ContactNoteCreateIn`, and `ContactSavedSearchCreateIn` models as one-to-one adapters over the Task 5C DTOs, with `Field(default_factory=list)`/`Field(default_factory=dict)` for collections. All stage inputs use `min_length=1,max_length=50`, matching `CRMContact.stage VARCHAR(50)`; there is no 51–64-character acceptance path. `ContactUpdateIn` must contain at least one set field and must not expose `lead_id`, provenance, recovered-profile fields, or audit fields. `ContactCreateIn` accepts internal first/last name, email, phone, stage, birthday, and anniversary only. Timeline times remain nullable. `ContactEvidenceOut` must use `ContactSourceMetadataOut` only; no import or adapter from `SourceRecordDetailOut` is permitted. Validate `content_href == f"/api/v1/command/archive/artifacts/{artifact_id}/content"` and reject filename, source key, provider ID, source/archive path, preview, payload, stored URL, and artifact bytes as extra fields. Router tests serialize a source fixture containing all those private database fields and prove none appears in the response while the ID-derived authenticated link does.

Preserve existing mutation response shapes while delegating writes to Task 5C: `POST /contacts` and `PATCH /contacts/{contact_id}` return legacy `ContactOut`; sync/import retain `ContactLegacySyncResult`/`ContactImportResult`; tag assignment/removal, note creation/deletion, and saved-search creation retain their current public JSON keys; `/archive/import` retains `ArchiveBundleImportResult` and merges the private helper's contact counts into its existing maps without exposing the owner map. The router maps service DTOs to those explicit compatibility models. `create_contact`/`update_contact` still return `ContactDetail` internally; no audit envelope is added. The new `contactsApi.create()`/`update()` clients decode a `ContactCreated` basic-contact result containing the positive `id` and editable internal fields, then detail consumers call `detail(id)` when the expanded DTO is needed. No endpoint silently changes a legacy response from a contact row into `ContactDetailOut`.

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
contact.archive_import_applied
workspace.saved_search_deleted
```

Apply the Task 5C-E action-aware audit builders, activity compatibility matrix, lock order, provenance-link deletion rules, and hashing rules exactly; a router never constructs ad hoc audit JSON. Contact-owned create, edit, tag, note, search, sync/import/archive import, and each affected bulk contact write `CRMContactAuditEvent` inside the service savepoint and request outer transaction. Global saved-search deletion writes the exact actor-attributed `workspace.saved_search_deleted` activity specified in Task 5C-E. Bulk uses the fixed-query sorted locks and all-or-none semantics there. Any activity/audit or later archive-child failure rolls back the relevant business rows. Replays reevaluate Task 5C-E's explicit no-op rules; they are ordinary admin actions without idempotency tokens, but a no-op creates no activity/audit. Router tests prove `/archive/import` passes the unchanged admin subject, preserves its response, uses the private owner-ID map only for child linkage, never serializes it, and rolls back contact ingest when a later child fails.

`GET /celebrations` requires `month=1..12` and returns separate `birthdays` and `anniversaries` rows with `contact_id`, display name, `month`, `day`, nullable verified year, `year_quality=verified|yearless|sentinel|unknown`, and `origin=internal_crm|recovered`. It follows Task 5C precedence and never infers a celebration. A recovered month/day with no exposed year returns `year=None,year_quality="yearless"`; sentinel `1900` returns `year=None,year_quality="sentinel"`.

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
- Modify: `frontend/src/components/command/home/HomeContextPanels.tsx`
- Create: `frontend/src/components/command/home/HomeContextPanels.test.tsx`

- [ ] **Step 1: Specify the shared abortable HTTP boundary and write RED tests**

Introduce the decoded, abortable boundary for the new Contacts client and archive blob retrieval in `http.ts`. This task does not attempt to decode every unrelated Command domain:

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

export type CommandBlobRequest = Readonly<{
  path: string;
  signal?: AbortSignal;
}>;

export async function commandBlob(request: CommandBlobRequest): Promise<Blob>;
```

Both functions use one private `authenticatedFetch(path, init)` that validates `admin_token`, prepends the Command API base, supplies the bearer header, forwards the identical signal, and applies the same bounded non-2xx detail parsing. `commandJson` additionally sends `Content-Type: application/json`, serializes `body` exactly once, passes `null` to the decoder for 204, parses success JSON as `unknown`, and requires the supplied decoder. `commandBlob` sends no JSON content-type/body and returns `response.blob()` only after the shared status gate. A missing/blank token throws `CommandHttpError(401, "Administrator session required")` before fetch. A non-2xx response uses only a bounded string `detail` or `Command request failed (<status>)`; success schema/blob parsing never runs. JSON parse/schema failures throw `CommandDecodeError`; they may identify a field path and expected type but never include response values. Native abort rejection is rethrown unchanged so callers can recognize `AbortError`.

Tests assert JSON and blob bearer behavior, JSON-only content type/body, exact blob bytes/type, missing token for both paths, 204, 401/404/409/422/500 messages for JSON and blob, invalid JSON, nested decoder paths, signal identity, and aborted JSON/blob fetches. Run:

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

export type ContactCreated = Readonly<{
  id: number;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  stage: string;
  birthday: string | null;
  anniversary: string | null;
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
  create: (input: ContactCreateInput, options?: { signal?: AbortSignal }) => Promise<ContactCreated>;
  update: (id: number, input: ContactUpdateInput, options?: { signal?: AbortSignal }) => Promise<ContactCreated>;
  bulk: (input: ContactBulkInput, options?: { signal?: AbortSignal }) => Promise<ContactBulkResult>;
}>;
```

`section()` maps `opportunities`, `smart_plans`, `notes`, and `saved_searches` to their route segment; task sections map to `/tasks?state=to_do|completed|archived`. Timeline forwards the opaque cursor unchanged through `URLSearchParams`. Every method validates positive IDs and page bounds before fetch.

Tests pin the full canonical URL, repeated filters, reserved characters, stable sorting, omitted values, decoder rejection for every discriminated union, nullable timeline time, evidence constants, authenticated headers, 404/422 propagation, and signal forwarding.

- [ ] **Step 3: Preserve legacy consumers through a decoded adapter**

`api.ts` imports `commandJson`, `commandBlob`, and the Contacts decoders. Delete only private `requestBlob`; retain the existing private `request<T>` unchanged for non-Contacts JSON methods until those domains receive named decoders in their own plans. The new `contactsApi`, `commandApi.contacts`, and `commandApi.celebrations` use `commandJson`; `archiveArtifactBlob(id, options?)` uses `commandBlob({path,signal:options?.signal})` without changing its default call shape. No overview, task, goal, SmartPlan, opportunity, agreement, listing, referral, marketing, website, report, archive-index, tag, or other legacy method is migrated or behaviorally changed in this task. An `api.test.ts` inventory snapshots those unrelated method URLs/results before and after this change and proves they still traverse the retained `request<T>`; the HTTP tests do not claim those responses are decoded.

`commandApi.contacts(limit, offset, filters)` continues calling `GET /contacts` and resolving the legacy array shape, now through `decodeLegacyContacts`. It remains available to Tasks and other legacy consumers; do not redirect it to `/directory` and do not synthesize a page. Legacy contact mutation/workspace helpers not replaced by an exact `contactsApi` method also remain on `request<T>` in this task; Task 8 rewires the new Contacts workspace only to the decoded client without silently changing those compatibility responses.

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

Replace the old `Celebrations = {birthdays: Contact[]; anniversaries: Contact[]}` assumption. `CommandHomeApi.celebrations(month, options?)` returns the decoded `ContactCelebrations` wire contract from `contacts.ts`; `CommandHomeInput` and `CommandHomeModel` hold the UI-only shape below after `adaptHomeCelebrations()` runs inside `loadCommandHome`:

```ts
export type HomeCelebrationRow = Readonly<{
  contactId: number;
  displayName: string;
  kind: 'birthday' | 'anniversary';
  month: number;
  day: number;
  year: number | null;
  yearQuality: 'verified' | 'yearless' | 'sentinel' | 'unknown';
  origin: 'internal_crm' | 'recovered';
}>;

export type HomeCelebrations = Readonly<{
  birthdays: readonly HomeCelebrationRow[];
  anniversaries: readonly HomeCelebrationRow[];
}>;

export function adaptHomeCelebrations(value: ContactCelebrations): HomeCelebrations;
```

The adapter copies `contact_id`/`display_name` to the camel-case UI fields, validates each row's `kind` agrees with its containing array, preserves month/day/origin and every year-quality value, and never converts `yearless` or `sentinel` into a fabricated year. `yearless` and `sentinel` must both retain `year=null`; a non-null year is accepted only with `year_quality='verified'`; `unknown` also requires null. A mismatch throws `CommandDecodeError` without including the row value. `HomeContextPanels` renders `displayName`, uses `contactId` for the canonical `/admin/command/contacts/{id}` link/key, labels birthday versus anniversary from `kind`, and may display month/day but never prints `1900` or substitutes the current year. Remove the obsolete `Celebrations` alias from `api.ts`; no celebration row is coerced into `Contact` or given fake first/last names.

`home.test.ts` pins `CommandHomeApi`, `CommandHomeInput`, and `CommandHomeModel` types/behavior, adapter mapping, array-kind mismatch rejection, verified/yearless/sentinel/unknown invariants, abort forwarding, and celebrations-only error isolation. `HomeContextPanels.test.tsx` renders verified, yearless, and sentinel rows, asserts their names and contact links, and proves neither `1900` nor the current year is fabricated. `api.test.ts` proves malformed snake_case celebration rows fail closed before the Home adapter runs.

Replace the four Home contact shortcut URLs with canonical server-view links in this task: `?smart_view=never_contacted`, `?smart_view=recently_active`, `?smart_view=birthdays_this_month`, and `?smart_view=anniversaries_this_month`. Remove the Home-emitted `filter=never_contacted|birthdays|anniversaries` and `sort=recent_activity` forms; Task 8 retains those forms only as inbound compatibility aliases. `home.test.ts` asserts all four exact canonical URLs.

- [ ] **Step 5: Run frontend contracts and commit**

```bash
cd frontend
npm test -- \
  src/lib/command/http.test.ts \
  src/lib/command/contacts.test.ts \
  src/lib/command/api.test.ts \
  src/lib/command/home.test.ts \
  src/components/command/home/HomeContextPanels.test.tsx
npm run typecheck
git add src/lib/command/http.ts src/lib/command/http.test.ts \
  src/lib/command/contacts.ts src/lib/command/contacts.test.ts \
  src/lib/command/api.ts src/lib/command/api.test.ts \
  src/lib/command/home.ts src/lib/command/home.test.ts \
  src/components/command/home/HomeContextPanels.tsx \
  src/components/command/home/HomeContextPanels.test.tsx
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
- Modify: `frontend/src/components/command/workspaceFilters.ts`
- Modify: `frontend/src/components/command/CommandWorkspaceDeepLinks.test.tsx`
- Modify: `frontend/src/app/admin/command/command-shell.css`
- Modify: `frontend/src/app/admin/command/contacts/page.tsx`

- [ ] **Step 1: Mount the existing toast system once at the authenticated shell**

Wrap the complete shell, including rail/header/mobile navigation/canvas, in `CommandToastProvider`; do not mount another provider inside Contacts. `CommandShell.test.tsx` renders a child that calls `useCommandToast`, clicks a trigger, and asserts one live-region toast, one dismiss action, and no provider error. It also proves route changes do not duplicate the viewport. Add `.command-toast-viewport` positioning above overlays, 16px edge spacing, pointer-event isolation, stacked 8px gaps, and the existing SWS tone variables to `frontend/src/app/admin/command/command-shell.css`; toast buttons remain at least 44×44px and focus-visible.

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

The parser accepts only Task 5C enums and bounded integers. Invalid owned values resolve to defaults (`page=1`, `page_size=50`, `smart_view=all`, `sort=name`, `direction=asc`) and the next canonical replace removes them; repeated `tag/source/origin` values are parsed, deduplicated, and sorted. The serializer preserves unrelated query parameters, deletes all owned keys before writing canonical values in `CONTACT_QUERY_KEYS` order, and omits default/empty values except `page` and `page_size`. `replace()` resets page to 1 whenever any filter, SmartView, sort, direction, or page-size value changes; an explicit page-only patch preserves filters. It calls `router.replace(pathname + '?' + params, {scroll:false})` and never writes browser history per keystroke.

Replace the client-filtering `ContactWorkspaceView` in `workspaceFilters.ts` with this one-way compatibility adapter; Tasks helpers in that file remain unchanged:

```ts
export type LegacyContactWorkspaceView = Readonly<{
  smart_view: ContactSmartView;
}>;

export function parseLegacyContactWorkspaceQuery(
  query: Readonly<Record<string, string | readonly string[] | undefined>>,
): LegacyContactWorkspaceView {
  const smartView = first(query.smart_view);
  if (isContactSmartView(smartView)) return { smart_view: smartView };
  if (first(query.filter) === 'never_contacted') return { smart_view: 'never_contacted' };
  if (first(query.filter) === 'birthdays') return { smart_view: 'birthdays_this_month' };
  if (first(query.filter) === 'anniversaries') return { smart_view: 'anniversaries_this_month' };
  if (first(query.sort) === 'recent_activity') return { smart_view: 'recently_active' };
  return { smart_view: 'all' };
}
```

Precedence is canonical `smart_view`, then exactly one recognized legacy alias, then `all`; unknown legacy values never become filters. Delete `applyContactWorkspaceView()` and its client-side date/activity filtering. `page.tsx` awaits `searchParams`, calls `parseLegacyContactWorkspaceQuery()`, and renders `<ContactsWorkspace initialView={view.smart_view} />`. `useContactDirectoryQuery` uses `initialView` only when canonical `smart_view` is absent. On the first canonical `router.replace`, it deletes owned legacy `filter` and `sort=recent_activity` aliases so URLs converge without double semantics. The canonical Home links were already changed and tested in Task 7; Task 8 only preserves old inbound bookmarks.

Tests cover round trip, invalid enum/range cleanup, repeated-value ordering, reserved characters, unrelated-param preservation, canonical-over-legacy precedence, all four exact legacy aliases, unknown aliases, initial-view precedence, alias cleanup, reset-to-page-one, explicit pagination, and deterministic output after reordered input parameters. `CommandWorkspaceDeepLinks.test.tsx` asserts that each legacy URL produces the correct server `smart_view` request and then canonicalizes; it no longer expects client-side filtered rows.

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

Use existing SWS color/type/spacing tokens in `frontend/src/app/admin/command/command-shell.css`; introduce only `command-contacts-*` structural classes. At the 1800×982 reference viewport the content fills the Command canvas, toolbar controls remain on one line, the table uses a 44px header and 52px rows, Name is sticky after selection, and page controls remain below the table. Do not reproduce source-brand colors or add another rail/header.

At `max-width: 1100px`, hide Owner/Assignee and evidence columns behind the column menu. At `max-width: 760px`, keep Name, Primary contact, Stage, and action visible, move filters into the shared overlay, and retain horizontal scroll rather than changing rows into cards. Print hides selection, actions, toolbar, bulk controls, pagination, and toast viewport. Icons are Phosphor with `aria-hidden`; icon-only buttons have explicit labels. Text and focus contrast use the existing accessible tokens.

- [ ] **Step 6: Wire the route, run focused/full checks, and commit**

`page.tsx` performs only the compatibility parse above and renders `<ContactsWorkspace initialView={view.smart_view} />`; it does not fetch or duplicate directory state. Home shortcut links use the canonical `smart_view` values. Preserve the current `/admin/command/contacts/[contactId]` navigation contract for Task 9.

```bash
cd frontend
npm test -- \
  src/components/command/contacts/useContactDirectoryQuery.test.tsx \
  src/components/command/contacts/ContactsWorkspace.test.tsx \
  src/components/command/CommandWorkspaceDeepLinks.test.tsx \
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
  src/components/command/workspaceFilters.ts \
  src/components/command/CommandWorkspaceDeepLinks.test.tsx \
  src/app/admin/command/command-shell.css \
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
