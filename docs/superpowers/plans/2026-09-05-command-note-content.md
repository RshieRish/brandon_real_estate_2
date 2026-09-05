# Command Note Content and Sydney Names Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display the captured note text and correct titles, and return actual celebration names to Brandon's protected private assistant.

**Architecture:** Read the historical note format at the presentation boundary without rewriting immutable source records, importing duplicates, or overwriting user edits. Keep celebration audience limits, permissions, audit redaction, source routing, and external-action restrictions unchanged.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, the existing Atlas MCP tools and managed Hermes skill.

## Verified incident

- Live note #107 belongs to contact #149 and retains its original note text in both the source `values.raw_lines` and the linked note body.
- All 178 recovered notes use `raw_lines`; none has a structured `values.body`. 168 contain a separate body, 10 are title-only, and 19 use an Updated header that the historical parser mistakes for a title.
- The historical shape is time, Created/Updated, By author, title, optional body, Delete, Edit, sometimes followed by unrelated next-date or overlay text. All 178 live linked note bodies still exactly equal the original newline-joined capture.
- Celebration previews deliberately mask sample display names despite being protected by the same private bridge that already returns real names for contact searches.

## Note presentation repair

Files: `backend/services/command_contact_notes.py` (new focused reader), `backend/services/command_contacts.py` (source projection), `backend/routers/command_contacts.py` (internal workspace projection), `backend/tests/test_command_contact_notes.py` (new), existing contact section/router regression files.

- [x] Write failing tests for the production-shaped old-format note, Updated title, title-only note, multiline/Unicode body, overlay/date suffix, malformed capture, structured-field precedence, and nonmutating internal rendering.

```python
values = {"raw_lines": ["2:16 PM", "Updated", "By Example Agent", "Lake open house", "Requested a follow-up.", "Delete", "Edit"]}
assert projected_note.title == "Lake open house"
assert projected_note.body == "Requested a follow-up."
```

- [x] Run the focused tests with local-only test settings and confirm the expected missing-body/wrong-title failures.
- [x] Implement a strict pure legacy reader. Recognize the full header and Delete/Edit boundary; never promote arbitrary raw text or application overlays into a note. Return an empty body for a proven title-only note and no legacy projection for an incomplete/unrecognized shape. Enforce existing title/body bounds and preserve explicit structured fields.
- [x] Use that reader in recovered section projection. For internal notes, fetch contact-owned provenance in one batch and format title plus body only when the stored body exactly matches the original captured lines. Never mutate ORM note objects, source payloads, timestamps, links, archive bytes, or user-edited content. Conflicting/foreign provenance cannot supply another contact's text.
- [x] Run section/router/reader regressions and compare all 178 live notes read-only against the candidate reader. Verify original row counts and contents are unchanged.

## Sydney name presentation repair

Files: `backend/services/agent_control_command.py`, `backend/tests/test_agent_control_command.py`, `hermes/skills/atlas-backend-operations/SKILL.md`, its pinned manifest and existing overlay tests where required.

- [x] Change celebration regression assertions to require real sample names and confirm failure before implementation.

```python
assert both.samples[0].display_name == "Brandon Sweeney"
assert both.samples[1].display_name == "Avery Client"
```

- [x] Replace only the celebration sample's masking call with its authoritative display name. Retain the five-sample ceiling and general audience masking. Keep years, addresses and names out of content-free audit records.
- [x] Update the managed skill's celebration instructions to show returned names and dates; do not re-mask real returned names. Keep checksums/reference IDs as internal reconciliation metadata unless specifically requested. Include the complete authenticated campaign review link when a draft exists; keep fulfillment disconnection and explicit approval boundaries intact.
- [x] Validate the updated managed skill against the observed failing reply and an independent no-side-effect response scenario. Refresh its manifest hash using the repository's existing contract.
- [x] Run the Agent Control/MCP/overlay gates; independently review spec compliance and code quality before release.

## Verification and release

- [x] Update `tdtn.md` and project `memory.md` with exact local verification and remaining deployment state.
- [x] Run focused lint, whitespace, backend regressions, and read-only production-shaped projections. Do not re-run completed archive reconciliation or migrate the database for a read-path fix.
- [ ] Use the established PR-to-main production workflow from the user's prior authorization; require green CI and exact deployed revision evidence before claiming live repair. Verify note #107 through the authenticated production read path and verify real celebration names via the protected live tool. No card order, outreach draft, Telegram message, or other external business action is part of this repair.

### Live continuation follow-up

PR #37's note repair is deployed and verified across all 178 notes. The unchanged existing-conversation model check still reused the old masked preview without a current tool call, including when its normal durable-context instructions were preserved. Complete the remaining name-display gate without resetting or editing history:

- [ ] Add test-first, identity-scoped always-loaded instructions requiring a current-turn authoritative celebration read for current celebration/name requests. Distinguish historical explanation from a fresh check; never infer names from masks or claim a query that did not occur. Keep disabled/non-primary provider behavior, tool permissions, and mutation boundaries unchanged.
- [ ] Clarify the managed skill's current-turn evidence requirement and celebration-name exception to generic masked audience wording; refresh its version and manifest hash.
- [ ] Re-run the identical isolated existing-history model request against the candidate, require a real authorized read and returned names in the final response, then repeat against the deployed release. Verify visible history is unchanged and no business action was executed.
