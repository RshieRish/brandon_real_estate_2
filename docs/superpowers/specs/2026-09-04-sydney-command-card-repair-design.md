# Sydney, Command Contacts, and Card Fulfillment Repair Design

**Date:** 2026-09-04  
**Status:** Approved  
**Scope:** Sydney Telegram runtime, Command contact reconciliation/detail UI,
and a compliant Send Out Cards fulfillment boundary.

## Outcome

Brandon can ask Sydney in ordinary language for a month of contact birthdays
and home anniversaries. Sydney responds promptly, uses authoritative Command
data, prepares a truthful card campaign, and continues across internal session
rotation without `/reset`, `/new`, or `/compact`.

Command contact pages render structured recovered and SWS-owned records, never
a raw accessibility dump. Empty states distinguish verified empty, partial
capture, unreconciled source data, unavailable data, and a genuine empty SWS
workspace.

A physical-card send is a separate authenticated administrator action. The
backend may call Send Out Cards only after contracted API credentials are
configured and Brandon approves the exact recipients, messages, designs, and
cost.

## Confirmed production failures

1. Hermes passes nullable provider usage metadata to
   `reconcile_input_usage`; `int(None)` crashes the turn.
2. Durable Telegram delivery disables interim output. A slow first model call
   appears silent, encouraging a manual reset and duplicate submissions.
3. Equivalent messages with different platform IDs become separate durable
   runs; a reset does not cancel the existing run.
4. Normal Sydney turns can invoke native shell, filesystem, and code tools. The
   failed request wandered through those tools, Google Contacts, Drive, and a
   historical roster instead of one authoritative Command capability.
5. Command Agent Control does not expose celebration-month semantics even
   though the protected Command application API supports them.
6. Production has the immutable archive bytes but no reconciliation runs,
   recovered profiles, capture positions, section captures, source
   occurrences, or recovered timeline events. The old import created flattened
   contacts and raw archive-text activities.
7. The timeline maps each legacy activity summary directly into a heading, so
   a roughly 10,000-character capture becomes an enormous timeline title.
8. No Send Out Cards connector exists. Its terms prohibit scraping/macros and
   permit third-party API use only under a separate agreement.

## Architecture

```text
Telegram request
  -> durable acknowledgement + in-flight dedupe
  -> bounded Sydney business-tool runtime
  -> Command celebration preview
  -> internal card campaign draft
  -> authenticated Command review and approval
  -> contracted Send Out Cards API adapter
  -> immutable per-recipient receipt + contact timeline event

Immutable Command archive
  -> verify-only
  -> manifest-aware contacts dry run
  -> guarded contacts apply
  -> structured profiles, sections, and evidence
  -> truthful contact detail UI
```

Provider and CRM logic stays in FastAPI. Next.js renders typed state and
submits authenticated intent; it never calls Send Out Cards directly.

## Sydney runtime

### Nullable usage metadata

`reconcile_input_usage` accepts `int | None`. Missing or invalid usage metadata
keeps the preflight reservation and does not fail the turn. A nonnegative
integer still reconciles any positive difference.

### Prompt acknowledgement and dedupe

The first accepted Telegram message receives a short receipt-guarded
acknowledgement before the model call. It is separate from final-response
delivery and replays reuse its receipt.

For one authenticated identity, normalized request text is hashed and bound to
the active run. An equivalent message arriving while the run is queued,
running, or waiting retry reuses that run and reports that work is in progress.
Terminal work is not permanently deduplicated.

### Continuation and tool policy

The logical conversation remains stable across local sessions. Compression,
terminal model failure, and bounded no-progress stops rotate internally while
preserving source-linked durable context. Manual reset is not a recovery
requirement; an equivalent resubmission after a manual reset is coalesced.

Normal private Sydney turns allow the repository-owned skill and registered
Atlas business tools. Native `terminal`, `execute_code`, `read_file`,
`write_file`, `search_files`, and process-control tools are blocked before
execution and recorded as policy denials. Review-only recovery remains stricter.

An aggregate per-run tool budget and no-progress ceiling survive continuation.
Reaching either produces a truthful bounded response and terminalizes the run
instead of starting another loop.

## Command celebration capability

Add a read-only Agent Control/MCP tool named
`command_contact_celebrations_preview`.

Its input requires month `1..12` and may select birthdays and/or home
anniversaries. Its output contains exact per-kind and union counts, a stable
checksum and opaque audience reference, address-ready/missing-address counts,
bounded masked examples, and reconciliation evidence status.

It queries Command directly and never substitutes Google Contacts, Drive, an
admin page, or the former-office roster. Dates are never inferred or fabricated.
The Sydney skill routes phrases such as "my contacts", "birthdays", and "home
anniversaries" to this tool.

## Card campaign and provider boundary

Add additive storage for provider connection state, campaigns, recipients,
immutable attempts, and provider receipts. The campaign stores its month,
purpose, audience checksum/reference, lifecycle, cost snapshot, approval
identity, and optimistic version. Each recipient stores the source contact and
celebration type, personalized message/design snapshot, address readiness, and
canonical content hash.

```text
draft -> needs_addresses | needs_connection | ready_for_review
      -> approved -> sending -> sent | partially_sent | failed
```

Sydney may create or refresh an internal draft idempotently. It cannot approve
or send. Brandon reviews recipients, copy, designs, cost/credits, and exclusions
in Command. Any send-relevant edit invalidates approval.

`Approve and send` requires a request UUID and expected campaign version. The
backend commits intent before provider I/O, does not automatically retry an
ambiguous provider outcome, and stores one immutable receipt per recipient. A
retry is allowed only when authenticated provider evidence proves the prior
attempt was not delivered.

The provider-neutral adapter is configured through secret-managed environment
variables and disabled by default. Tests use a deterministic fake provider.
Production Send Out Cards calls require contracted API documentation and
credentials for Brandon's account. The system never scrapes the web app, shares
login cookies, or simulates browser clicks. Without credentials, Command shows
`Send Out Cards not connected` and preserves the campaign without sending.

## Command data repair

Use the existing reconciliation runbook:

1. Confirm the deployed revision and sole Alembic head.
2. Take and validate a protected provider-level database backup.
3. Run archive verify-only and retain the content-free fingerprint/metrics.
4. Build and review the private two-overlap manifest outside the repository
   from strong evidence only.
5. Run a manifest-aware Contacts dry run and compare every metric with the
   accepted 317-identity/2,536-section contract.
6. Apply only Contacts with the accepted fingerprint.
7. Verify idempotency, ownership, celebrations, and all eight views.

Every immutable artifact and lead-backed contact is preserved. Source-only
rows remain distinct from current SWS-owned records.

## Contact timeline and UI

Technical legacy activities `archive_timeline_capture` and
`archive_contact_imported` are excluded from the normal timeline. The rows stay
intact and available through Source Evidence/audit tooling. Canonical recovered
events render after reconciliation. A defensive bounded-title presentation
prevents future malformed records from destroying layout.

The detail UI keeps the premium Command system while fixing hierarchy:

- module content clears the fixed global header at every scroll position;
- the profile rail and content pane form an asymmetric responsive layout;
- sticky primary tabs scroll horizontally on small screens and show trustworthy
  counts/status;
- recovered Command and SWS-internal records remain visually distinct;
- empty states distinguish verified empty, partial, unreconciled, unavailable,
  and genuinely empty;
- Source Evidence summarizes capture coverage before artifact detail;
- long values wrap or clamp with explicit expansion;
- loading, retry, keyboard focus, 44px mobile targets, and reduced motion remain
  covered.

The UI uses Montserrat and the project black/gold/white/gray/bronze palette,
with no emoji.

## Verification and release

Development is test-first: null-usage regression; runtime denial/budget/dedupe/
acknowledgement/continuation tests; PostgreSQL campaign and celebration
contracts; MCP registry tests; reconciliation checks; frontend decoder,
component, accessibility, and Playwright visual tests; TypeScript, scoped lint,
build, Ruff, migration-head, and diff checks.

Release order:

1. Merge compatible frontend/backend/Atlas changes through one reviewed PR.
2. Deploy with card sending disabled.
3. Verify health, auth boundaries, live MCP tools, and Sydney configuration.
4. Run protected archive backup/verify/dry-run/apply gates and verify the UI.
5. Run one benign Sydney celebration-preview prompt with no external action.
6. When contracted Send Out Cards credentials exist, verify provider test mode
   and perform one separately approved controlled recipient before enabling
   general sends.

No historical failed prompt is rerun, and no card is sent merely to prove the
deployment.
