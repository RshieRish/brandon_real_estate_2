# Command and Agreement Full-Parity Reconstruction Design

**Date:** 2026-08-12  
**Status:** Approved  
**Supersedes for parity scope:** `2026-08-12-command-workspace-design.md`

## Goal

Turn `/admin/command` into a complete Sold With Sweeney operational workspace that reconstructs every usable Command and DocuSign surface and every distinct recoverable business record in the authorized local archive. The result must preserve the captured information architecture, density, navigation, list/detail behavior, tabs, boards, filters, drawers, and workflow states while using Sold With Sweeney branding and the application's FastAPI/PostgreSQL/object-storage stack.

This is not a screenshot viewer and not a cosmetic reskin. Recovered records must be searchable and usable inside their native CRM modules, and every reconstructed record must be traceable to immutable source artifacts.

## Acceptance Definition: “One to One”

Parity is measured at three separate evidence levels. They must never be conflated:

1. **Observed record** — a stable source ID or uniquely identifiable row/detail was captured. Create exactly one source record and, when the domain supports it, exactly one normalized CRM record.
2. **Rendered occurrence** — a row/card appeared in a captured range, page, or workspace but may repeat another observed identity. Preserve the occurrence and its source location without inventing another person or business entity.
3. **Displayed aggregate** — the source UI displayed a badge, total, or range count without exposing the underlying unique records. Preserve the exact aggregate with an `evidence_only` state and an explanation; do not fabricate underlying records.

A feature is complete only when:

- every distinct recoverable record is available in its correct native module;
- all source artifacts used for that record are linked and downloadable;
- all captured fields and relationships are retained, including null/empty states;
- source duplicates are not silently collapsed and repeated renderings are not inflated into fake entities;
- module counts reconcile to observed records, rendered occurrences, and evidence-only aggregates separately;
- the relevant reconstructed screens satisfy functional, responsive, accessibility, and visual-comparison checks; and
- production migrations, data import, authenticated reads, and file downloads are verified against live production.

## Immutable Source Baseline

The current production archive contains **12,580 checksum-valid artifacts** totaling **745,060,261 bytes**:

- Command: 12,411 artifacts.
- DocuSign: 169 artifacts.
- Every artifact has stored bytes, matching declared length, and a matching SHA-256 checksum.

`crm_archive_artifacts` remains immutable. Reconstruction creates semantic source records and normalized CRM entities beside it; it never rewrites or discards original bytes.

### Recoverable Command baseline

- **Contacts:** 317 captured contact positions with the required eight-view matrix: Timeline, Opportunities, SmartPlans, Notes, Saved Searches, and Tasks in To Do/Completed/Archived states. The archive resolves 313 distinct names/identities; capture positions and business identities remain separate concepts.
- **Tasks:** 2,173 stable task IDs with expanded panels: 1,506 To Do, 44 Completed, and 623 Archived.
- **SmartPlans:** 25 rendered plan rows, 14 unique expanded plan names, zero Published rows, and a displayed badge of 31. The difference is evidence-only, not six invented plans.
- **Opportunities:** 23 exposed opportunity IDs with four captured secondary tabs each (92 tab captures): Documents, Notes, Timeline, and Offers & Commissions. Vendors has representative UI coverage, not bulk vendor coverage.
- **Listings:** 37 concrete list rows. One listing has a clearly complete detail set; other detail/tab evidence varies in quality and remains explicitly qualified.
- **Marketing:** eight email-campaign IDs, 34 design cards with 33 unique editor bodies, and 20 Direct Mail records. Campaign aggregate metrics and visible recipient samples remain distinct; recipient totals do not authorize fabricated recipient rows. Social Posts is a captured calendar state. Paid Ads is a shell/progress state only.
- **Referrals:** four concrete referral cards, five distinct observed network names across repeated range output, two expanded profiles, two pending invites, and a displayed directory/range total through 2,318. The 2,318 display is an evidence-only aggregate because the captured range output repeats a handful of names.
- **Reports:** eight categories with displayed counts totaling 34; category pages expose no individual report cards. Favorites is an observed empty state.
- **Websites:** landing/settings and manager-shell states; no recoverable page inventory or underlying site-content records were exposed.
- **Visual reference:** 99 exact-file-unique screenshots currently exist. Valid rendered states are reference targets; blank shells, retries, redirects, and errors are limitation evidence, not successful page targets.

### Recoverable DocuSign baseline

- 159 agreement rows across four full-history inventory pages.
- 136 unique agreement rows with direct-download controls recorded in the ledger.
- 148 checksum-valid downloaded ZIP bundles.
- Two accessible templates.
- Two pending agreements with captured form-data CSVs and no available document download while pending.
- Drafts, Deleted, and Tasks were observed empty after the documented filter checks.

The 159 rows must not be collapsed to the current 117 title-deduplicated agreement records. A title is display data, not a source identity.

## Product and Legal Boundaries

- Keep Sold With Sweeney branding, colors, typography, icons, wording, and logos. Do not ship Keller Williams or DocuSign trademarks, logos, proprietary brand copy, or hidden vendor controls.
- Reconstruct captured layout geometry and interaction behavior using original SWS components and code.
- Preserve all existing `/admin/*` routes and current lead, booking, funnel, content, analytics, compliance, and Maps behavior.
- Do not claim or simulate legal electronic signatures. Recovered DocuSign material is an internal agreement/document archive. New signing or provider delivery requires a separately approved signing integration.
- Do not fabricate records or missing fields. Unknown, unavailable, repeated-rendering, and evidence-only states are first-class UI states.

## Experience Architecture

### Shared shell

All `/admin/command/*` routes use one shell:

- compact black/gold icon rail with expanded labels on demand;
- desktop utility header with global search, contextual create action, notification access, help, and account controls;
- full-width light work canvas with a dense module header, breadcrumbs, top tabs, filters, saved views, actions, and module-specific content;
- responsive mobile header and off-canvas navigation;
- consistent popover → drawer/modal → full-detail-page depth ladder;
- keyboard-operable tabs, grids, menus, dialogs, drawers, and boards;
- loading skeleton, first-run, true-empty, evidence-only, partial-capture, error, and retry states.

The shell uses SWS black `#0a0a0a`, gold `#eac469`, warm whites, graphite, bronze accents, Montserrat, and restrained texture/motion. It matches captured density and geometry without vendor branding.

### Home

Reconstruct the captured operational dashboard and shortcuts:

- Leads Never Contacted, Recently Active, Birthdays, and Anniversaries;
- personal/team/all task views and quick task creation;
- goals, recent leads, database health, activity, lead-pool, and profit-share/captured placeholder regions;
- upcoming bookings and internal pipeline health;
- an auditable Sweeney Briefing.

The dashboard's one job is to answer: **“What needs Brandon’s attention next?”** Its signature metric is **Follow-Up Readiness**, derived from overdue work, uncontacted leads, contact health, and active opportunities. It is presented as the single hero insight with a next-action queue. Secondary metrics are limited to four tiles; deeper widgets live behind module links.

### Contacts

- Dense sortable/paginated directory with selection, bulk actions, SmartViews, search, owner/assignee, tags, contact methods, activity dates, and configurable columns.
- Split contact detail canvas: identity/health/profile/map on the left; Timeline, Opportunities, SmartPlans, Tasks, Notes, and Saved Searches on the right.
- Previous/next contact navigation and searchable contact jump.
- Preserve source, account, owner, assignee, collaborators, neighborhoods, addresses, preferences, legal name, birthday/anniversary month/day, relationships, company/title, tags, and captured activity fields.
- Merge first-class CRM activity with linked legacy lead/booking/funnel activity without duplicating events.
- Show capture-position evidence separately when multiple captured positions resolve to one identity.

### Tasks

- To Do, Completed, and Archived tabs with totals that reconcile to 1,506/44/623 recovered source tasks plus clearly separated internal post-migration tasks.
- Dense paginated table, task-name search, date chips, My/Team scope, priority/assignee/source filters, bulk transitions, and expanded task panel.
- Preserve task ID, name, contact, owner/assignee, priority, due/completed/archived timestamps, creator/actor, type, description, hyperlink, contact summary, and source evidence.
- State transitions are audited and reversible where business rules permit.

### SmartPlans

- My SmartPlans, Library, and Published views; row expansion shows duration, touches, contacts, actions, and ordered typed steps.
- Reconstruct 25 observed rows and the 14 unique exposed step bodies. Mark row step details unavailable where the archive did not expose them. Preserve the displayed 31 badge as evidence-only.
- New internal plans support typed wait, task, email, note, tag, notification, and condition-ready steps; drafts, publish state, enrollment, scheduling, run history, pausing, and compliance review.
- A backend executor processes enabled internal plans idempotently. Imported historical plans never auto-send or auto-execute merely because they were recovered.

### Opportunities

- Captured phase-board/Kanban layout with pipeline/type selectors and sortable phases.
- Normalize all 23 observed opportunity IDs and their captured details.
- Detail tabs: Details, Documents, Notes, Timeline, Offers & Commissions, Vendors, and Tasks.
- Preserve prices, commission fields, dates, phase/stage, property/client, checklist requirements, upload counts, empty-note/activity states, and the two observed accepted-offer records.
- Drag/drop stage transitions and every mutation are audited.

### Listings, Search, and Map

- Dense 37-row listing inventory with captured property fields.
- List/map split search with server-mediated map/geocode data, filters, pagination, saved searches, and contact/opportunity links.
- Detail tabs for Details, Photos, Open Houses, Virtual Tours, and Links.
- Render complete data where observed and explicit partial-capture/evidence panels where a detail tab was only a shell.
- Collections remains a documented redirected/empty state unless internal users create new collections.

### Marketing

- Dashboard, Emails, Designs, Social Posts, Direct Mail, and Paid Ads navigation matching captured hierarchy.
- Normalize eight observed campaigns, their aggregate delivery metrics, and only the recipient rows actually exposed.
- Normalize 34 design-card occurrences linked to 33 unique editor bodies.
- Normalize 20 Direct Mail records and their captured status/date/lead/recipient/goal fields.
- Integrate existing internal content/funnels/analytics as explicitly labeled SWS-native records; never claim they came from Command.
- Social Posts and Paid Ads preserve captured calendar/shell states while allowing new SWS-native records through internal tables.

### Referrals

- Dashboard, My Referrals, Map, My Network, Track Referral, New Referral, Grow Network, activity log, and profile-panel flows.
- Normalize four concrete referral cards, five distinct observed network identities, and two expanded profiles.
- Preserve repeated range occurrences and the 2,318 displayed aggregate in provenance/evidence views without creating 2,318 people.
- Show two pending invites and all observed status/economic fields.

### Reports

- Reconstruct All Reports, Favorites, category navigation, search, pagination, and the eight observed category counts.
- Do not invent the 34 report cards. Category counts render with an “individual records were not exposed in the recovered session” evidence state.
- Add SWS-native reports for contacts, tasks, pipeline, agreements, marketing, bookings, and database health, clearly distinguished from recovered report categories.

### Websites

- Reconstruct landing/settings and manager navigation with Homepage, Home Valuation, Featured Properties, Create Page, Expert Mode, preview, and browser actions.
- Display the recovered manager state and link real editing to existing internal content/funnel management.
- Do not invent recovered website/page records that were never exposed.

### Agreements and recovered DocuSign material

- Agreements list preserves all 159 source rows using stable source row identity, page/order, status, title, parties, dates, and all captured fields.
- Document/file relationships connect 136 direct-download ledger rows, 148 ZIP bundles, two pending CSVs, and templates without title-based collapsing.
- Detail workspace provides overview, recipients/parties when observed, documents, form data, events, related contact/opportunity, archive evidence, preview where supported, and authenticated original download.
- Duplicate bundle content remains represented as distinct source files when source paths differ, with checksum-based duplicate-content badges.
- Drafts, Deleted, and Tasks show captured empty-state evidence.
- Internal agreement creation remains available but is visually and semantically separated from recovered provider records.

### AI

- Sweeney Briefing and contextual contact/opportunity assistance use only internal normalized data and explicit source evidence.
- Prompts and outputs are compliance-scanned, aggregate-only by default, auditable, and review-only unless a user explicitly invokes an allowed mutation.
- AI never fills unavailable archive fields or upgrades evidence-only records into observed records.

## Provenance and Data Architecture

Add these core tables:

- `crm_source_records` — one row per observed source record, rendered occurrence, or displayed aggregate. Fields include source system, module, record kind, source key, evidence level, display label, observed payload JSON, capture quality, captured timestamp, and parser version.
- `crm_source_record_artifacts` — many-to-many links from semantic source records to immutable `crm_archive_artifacts`.
- `crm_entity_sources` — maps normalized CRM entity type/ID to source records. Unique constraints prevent one observed source identity from silently mapping to multiple normalized entities.
- `crm_reconciliation_runs` and `crm_reconciliation_results` — immutable import/reconciliation reports with expected, observed, rendered, normalized, evidence-only, unmatched, duplicate-content, and error totals by module.

Extend domain models rather than forcing all data into generic JSON:

- contact profile, address, relationship, neighborhood, ownership, preference, and capture-position models;
- task ownership/source/archive fields;
- typed SmartPlan steps and execution/run events;
- opportunity pipeline/phase/property/document/checklist/timeline/offer/vendor relationships;
- listing facts/media/open-house/tour/link/collection relationships;
- marketing campaigns, recipient observations, designs, direct-mail, social, and paid-ad records;
- referral identities, profile observations, cards, invitations, range occurrences, and activity events;
- report category observations/favorites;
- website manager/page records for SWS-native content;
- recovered agreement inventory rows, bundles, ledger links, pending form data, and provider-state observations.

All imports are idempotent by `(source_system, module, record_kind, source_key, parser_version)`. Re-running import updates parser-derived payload only when the immutable source inputs match and produces a new reconciliation run; it never deletes user-created internal records.

## Import and Reconciliation Pipeline

1. Inventory and checksum the local source bundle against `crm_archive_artifacts`.
2. Parse each module into typed `crm_source_records`, retaining raw observed payloads and capture-quality flags.
3. Link every source record to all contributing artifacts.
4. Materialize or update normalized domain entities by stable source key, never display title alone.
5. Link normalized entities back to source records.
6. Compute expected-vs-observed-vs-normalized reconciliation totals and per-record errors.
7. Refuse the production write phase if immutable archive counts/checksums differ, a stable source ID maps ambiguously, or a module violates a hard expected total.
8. Emit machine-readable JSON and an admin reconciliation screen.

The importer supports `--dry-run`, `--apply`, `--resume`, `--module`, and `--verify-only`. Production import uses a single recorded source-bundle fingerprint and resumable module transactions.

## API and Ownership

- Split the current monolithic Command router into focused router/service modules without breaking existing URLs.
- All list APIs use cursor or page/size pagination, stable sorting, typed filters, and total metadata.
- All routes require existing admin authentication.
- Every user-created/mutated record carries owner/assignee/creator where applicable and uses the current admin as actor.
- Imported historical records use an explicit `source_actor` label when no internal actor identity exists.
- Mutations write actor-attributed audit events.
- Source-evidence endpoints expose metadata/previews and authenticated byte downloads only to admins.

## Visual Fidelity Contract

For each valid reference state:

- capture the rebuilt screen at the same viewport;
- compare shell width, rail/header geometry, content bounds, row height, typography scale, tabs, toolbar placement, grid/board structure, drawer dimensions, and responsive transitions;
- apply a documented color/brand mask so SWS branding differences do not count as visual failures;
- use screenshot regression thresholds plus human review for dynamic text, maps, and timestamps;
- keep error/shell source screenshots as limitation tests, not visual targets.

Representative browser journeys cover every module, each top-level tab, high-risk detail tab, filters/pagination, empty/evidence-only/error states, and mobile navigation.

## Testing and Verification

- Parser fixture tests for every source family and every documented limitation.
- Migration upgrade tests and database constraints for stable identities/provenance.
- Idempotency tests: a second import produces zero extra normalized entities and identical reconciliation totals.
- FastAPI authenticated integration tests for list/detail/filter/pagination/mutation/evidence/download flows.
- SmartPlan executor tests for timing, retries, pause, compliance blocking, and no execution of imported historical plans.
- Frontend unit/component tests for grids, tabs, boards, drawers, evidence states, keyboard behavior, and typed clients.
- Playwright journeys and screenshot comparisons across desktop/mobile.
- TypeScript, lint, production build, backend suite, migration dry run, reconciliation dry run, and production post-deploy smoke tests.
- Production acceptance checks exact archive byte/hash integrity, domain totals, normalized totals, source links, authenticated file downloads, and representative browser screens.

## Delivery Program

1. Provenance schema, parser registry, reconciliation engine, and read-only dry run.
2. Shared parity shell, data grid, tabs, drawers, evidence panel, and Home.
3. Contacts and Tasks full data/import/UI parity.
4. SmartPlans and Opportunities full data/import/UI parity.
5. Listings/Map, Marketing, Referrals, Reports, and Websites.
6. Recovered DocuSign/agreement inventory and document relationships.
7. AI context actions, audit hardening, accessibility, visual regression, production migration, deployment, and live reconciliation.

Each phase must be independently deployable and must leave the raw archive browseable if semantic parsing for a later module is incomplete.
