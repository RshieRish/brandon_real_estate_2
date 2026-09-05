# Command data and Sydney presentation repair

This continues the completed Task 8/9 rollout and the September 5 audit. It does not replace or restart that plan.

**Goal:** expose source-backed addresses, real timeline events and dates, truthful contact-section fields/counts, imported DocuSign files/folders, and concise Sydney replies with genuinely active task reads.

**Boundaries:** preserve original capture bytes, source records, contact ownership, later CRM edits, and Telegram history. Do not send cards/messages, sign documents, reconnect providers, reimport the entire archive, or substitute candidate tests for deployed evidence. Production data changes require a reviewed dry run and validated backup. Existing unrelated checkout edits remain untouched.

## 1. Captured addresses and timeline (main agent)

- [x] Inspect representative source records and capture structure, including date-header ordering and address labels, using read-only production queries.
- [x] Add failing cases for source-backed address extraction and conservative timeline cleanup/date interpretation in `backend/tests/test_command_contact_capture_content.py`.
- [x] Implement pure readers in `backend/services/command_contact_capture_content.py`: only proven navigation/profile/footer structures are hidden, legitimate unknown content remains, dates retain source precision and original timezone uncertainty.
- [x] Wire address projection into the contact/card read paths and timeline presentation into `backend/services/command_contact_timeline.py`, with ownership checks and deterministic pagination. Add regression coverage in contact/timeline/card tests.
- [x] Update only corresponding address/timeline contracts, schemas, frontend decoding, `ContactProfilePanel.tsx` and `ContactTimelineTab.tsx`; test readable content, literal captured dates, missing-source states, responsive overflow, and preserved source evidence.

## 2. Contact sections and counts (independent scoped agent)

- [x] Write failing backend/frontend tests for task date-only fields, opportunity budget, internal-versus-recovered counts, SmartPlan names and saved-search labels.
- [x] Update scoped projections in `backend/services/command_contacts.py`, occurrence contracts/schemas, matching `frontend/src/lib/command/contacts.ts` decoding and section components.
- [x] Keep imported and live counts distinct when identity is unproven; never deduplicate by title alone or fabricate currency/date precision.

## 3. DocuSign archive visibility (independent scoped agent)

- [x] Inventory every imported DocuSign file and source folder. Distinguish preserved captures from downloaded documents.
- [x] Add failing tests for authenticated metadata-only archive listings, safe folder/search filters, accurate counts/pagination and downloads.
- [x] Implement archive service/router projection and a responsive folder/search browser at `frontend/src/app/admin/command/archive/page.tsx`; preserve exact bytes and prevent stale filter responses.

## 4. Sydney replies and active tasks (independent scoped agent)

- [x] Add failing regressions for birthday-only technical identifier leakage and active task queries including completed/test tasks.
- [x] Narrow business instructions and exact celebration-result response presentation; retain internal evidence and honor explicit requests for identifiers.
- [x] Filter default active task reads conservatively, with explicit historical reads available. Preserve continuity and business-tool boundaries.

## 5. Verification and handoff

- [x] Run focused RED/GREEN tests, then combined backend/frontend suites against disposable local databases and existing pinned runtimes.
- [x] Review each changed domain independently for correctness, provenance, privacy, pagination, and regressions. Validate UI with real local screens at desktop/mobile sizes.
- [x] Run read-only production-shaped comparisons of every affected record; distinguish local candidate output from installed production behavior.
- [ ] Record exact tests, record counts, limitations and release state in `tdtn.md` and project `memory.md`. Report any uncompleted production rollout explicitly.

## Production follow-through

- [x] Validate a protected full PostgreSQL backup outside the repository before applying recovered addresses.
- [x] Finish the all-317-contact read-only comparison and independent review, with no unproven control cleanup.
- [ ] Merge only reviewed source with complete green CI, then verify installed backend, worker, frontend and Atlas revisions/assets/27-tool registry.
- [ ] Apply only the reviewed additive address fingerprint with its separate verified JSON backup, then prove an idempotent zero-row dry run.
- [ ] Verify the authenticated live contact/archive UI and installed isolated Sydney reads. Preserve Telegram history and distinguish probes from actual delivery.
- [ ] Record final release evidence and remaining genuine source/provider limitations.
