# Sydney Command Recovery Skill Design

**Date:** 2026-08-26

**Status:** Approved for implementation planning

**Scope:** Focused follow-up to the Sydney durable-context rollout

## Problem

Sydney's durable context, retry queue, and Command contact tools are healthy in
production, but Brandon's last pre-cutover business request did not complete.
The request was preserved by history backfill, yet it has no durable run because
it predates live run admission. In addition, the live
`atlas-backend-operations` skill contains stale guidance that treats "Command
contacts" as the old `KW Success Agent Roster 2025` Drive sheet. That guidance
contradicts the deployed `command_contacts_search` and
`command_contact_audience_preview` tools and led Sydney to inspect the admin UI
instead of querying the canonical Command directory.

The result is two distinct gaps:

1. future and resumed turns can still choose the wrong source because the live
   skill is not repository-owned or updated by the Hermes overlay; and
2. the exact unfinished pre-cutover turn cannot enter the automatic retry path
   without a bounded, explicit recovery admission.

## Approved Outcome

Sydney must use the canonical Command tools whenever Brandon refers to Command,
the Command contacts page, or its URL. An interrupted request may automatically
recover the current audience and prepare a reviewable email draft, but recovery
must never send email or perform another external mutation. Any actual send
requires a new, explicit Brandon approval after he sees the current audience and
draft.

Brandon must not need `/new`, `/reset`, `/compact`, or a restatement of the old
request.

## Selected Approach

Use a source-controlled Hermes skill plus a narrow legacy-recovery admission.
Do not build a generic historical replay scanner.

- The skill fixes tool selection for all future and resumed work.
- Existing durable run admission and retry continue to handle every post-cutover
  Telegram message automatically.
- A one-time operator-admitted recovery converts an exact, hash-verified
  pre-cutover user event into the existing durable run path.
- The recovered run carries a local `review_only` execution policy enforced by
  the Hermes tool boundary, not merely by model instructions.

This is safer than replaying every historical user event and more complete than
a skill-only change, which would leave Brandon's saved request unfinished.

## Repository-Owned Skill

Add the authoritative skill at:

`hermes/skills/atlas-backend-operations/SKILL.md`

The corrected Command section must state all of the following:

- `command_contacts_search` is the authoritative current-state source for
  individual Command contacts and paginated Command results.
- `command_contact_audience_preview` is the authoritative bounded source for a
  whole-audience count, checksum, opaque audience reference, and masked sample.
- `/admin/command` and `/admin/command/contacts` URLs are navigation locators,
  not data endpoints. Sydney must never scrape their HTML or inspect
  `__NEXT_DATA__` to obtain contacts.
- `contacts_search` means Google Contacts only and may never substitute for
  Command.
- `KW Success Agent Roster 2025` is a historical Drive roster. Sydney may use it
  only when Brandon explicitly asks for that former-office roster; it is never
  a fallback for Command.
- Current Command results outrank remembered contact data and historical
  excerpts.
- A whole-audience request starts with an audience preview. Sydney must not put
  hundreds of contact records into the model prompt.
- A recovered request is review-only: Sydney prepares the audience summary,
  proposed subject, and proposed body, then stops for fresh approval.
- Historical wording such as "send this" is not fresh send approval after a
  restart or legacy recovery.

The skill must not teach Sydney to inspect process environments, retrieve admin
passwords, bypass the protected agent-control API, or use anonymous webpage
requests for private CRM data. Existing unrelated skill guidance remains intact
unless it conflicts with these boundaries.

## Idempotent Hermes Installation

Extend the existing overlay rather than editing `/data/.hermes` manually.

1. The overlay manifest records the managed skill source path, destination, and
   SHA-256.
2. The image build copies the skill beside the other repository-owned overlay
   assets.
3. Atlas bootstrap atomically installs the exact file at
   `/data/.hermes/skills/productivity/atlas-backend-operations/SKILL.md` before
   Hermes starts accepting messages.
4. Reapplying the same version is an exact no-op.
5. A missing source, unexpected source hash, write failure, or post-write hash
   mismatch fails startup rather than leaving stale instructions active.
6. Only this explicitly managed skill path is replaced; other user or upstream
   skills remain untouched.

The deployed skill version and content hash are emitted as content-free startup
evidence.

## Legacy Recovery Admission

Add a repository-owned utility alongside the Sydney overlay modules. It admits
one exact historical event into the existing spool and run queue; it does not
scan or infer which old tasks should execute.

### Required selectors

The operator supplies:

- the exact Hermes session ID;
- the exact state message ID;
- the expected SHA-256 of the visible, redacted user content; and
- the fixed policy `review_only`.

The utility defaults to dry-run. Enqueueing requires an explicit `--enqueue`
flag. It validates that the selected row:

- belongs to the configured private Brandon Telegram identity and mapped
  logical conversation;
- is a visible user message, not a system continuation, compaction handoff,
  canary, tool event, or assistant event;
- matches the supplied content hash;
- already has a reconciled canonical backfill receipt; and
- has no existing recovery spool record or run for its stable recovery key.

The stable recovery key is derived from the platform, chat, Hermes session, and
state message ID. Repeating the command returns the existing admission and never
creates a second run.

### Existing-run integration

The recovery utility writes an ordinary inbound spool bundle whose event uses
the original backfill source key. Backend ingestion therefore deduplicates to
the existing canonical user event instead of creating a second user message.
The bundle starts a normal durable run with a synthetic, deterministic platform
message ID and `recovery_policy=review_only` in its local run metadata. The
existing gateway watcher then claims and resumes it automatically.

The continuation uses the original logical conversation and current durable
context. Its internal instruction is limited to finishing the saved request as
a review packet; it does not pretend Brandon sent a new message.

## Enforced Review-Only Policy

The policy is enforced in the Hermes tool interceptor for the active recovered
run.

Allowed tools are read-only, including:

- `context_history_search`;
- `command_contact_audience_preview`;
- `command_contacts_search`; and
- bounded status/read tools needed to verify connected state.

Every mutating tool is blocked, including `gmail_draft_create`, `gmail_send`,
Docs or Sheets writes, calendar creation, and CRM writes. This avoids duplicate
historical side effects and makes recovery safe even if model instructions are
ignored.

"Prepare a draft" in recovery means returning a review packet to Brandon with:

- the exact current audience count;
- the opaque audience reference and checksum;
- the masked audience sample;
- the proposed subject and body; and
- an explicit statement that nothing was sent.

It does not create hundreds of Gmail drafts. After Brandon gives fresh approval
in a later normal turn, any supported draft or send action follows the existing
idempotency and confirmation contracts. Bulk-campaign delivery is not added by
this focused fix.

## Data Flow

1. Atlas bootstrap installs and verifies the repository-owned skill.
2. The operator runs the recovery utility in dry-run mode against the exact
   unfinished user event and checks the content-free validation result.
3. The operator explicitly enqueues the same validated event once.
4. The utility stages a deduplicating inbound bundle and stable `review_only`
   run admission in the Sydney spool.
5. The normal spool drain resolves the existing canonical event and starts the
   run.
6. The gateway watcher claims the run and restores Brandon's original request,
   logical conversation, completed history, and current durable context.
7. Sydney uses the Command audience and contact read tools, prepares the review
   packet, and sends one final Telegram response.
8. The backend records the assistant event and successful run completion.
9. No email, Gmail draft, document, calendar event, or CRM mutation occurs.

## Failure Handling

- A selector or content-hash mismatch fails before writing the spool.
- An unmapped or unreconciled historical row fails closed.
- A duplicate admission returns the existing stable record.
- A blocked mutating tool returns a durable, non-retryable policy-denial tool
  result while allowing Sydney to finish with a review-only explanation. The
  denied tool never starts, so the overall run may still complete successfully.
- A transient model/provider failure uses the existing persisted retry and
  continuation path.
- An uncertain final Telegram delivery uses the existing delivery ledger and is
  never repeated blindly.
- Disabling Sydney retry stops recovery execution without deleting the original
  history or recovery evidence.

## Test Strategy

Implementation follows red-green TDD.

### Skill and overlay tests

- The managed skill contains the required Command routing rules and excludes
  the stale Drive-roster fallback.
- Manifest hash, image copy, atomic bootstrap install, idempotent no-op, and
  fail-closed hash mismatch are covered.
- Unrelated skill paths remain untouched.

### Recovery utility tests

- Dry-run performs no writes.
- Exact valid admission creates one stable inbound bundle.
- Replay is idempotent.
- Wrong hash, identity, role, canary, compaction message, missing reconciliation,
  and existing terminal response are rejected.
- The original source event deduplicates to the existing canonical event.

### Runtime policy tests

- A recovered run can call both Command read tools.
- Every mutating tool, especially `gmail_send` and `gmail_draft_create`, is
  blocked even when the model requests it.
- A normal non-recovery run retains its existing tool behavior.
- Restart during a transient wait resumes once and preserves `review_only`.
- The final response is stored once and delivered once.

## Rollout and Production Proof

1. Run the focused backend and overlay test matrix, the full changed-area suite,
   exact overlay idempotence, secret scan, and `git diff --check`.
2. Open a focused PR, review it, merge it to `main`, and deploy Atlas. Deploy the
   backend only if implementation changes its code or contract.
3. Verify Railway health and live JSON-RPC `tools/list` still contains exactly
   the existing 25 ordered unique tools with no forbidden tools.
4. Verify the live managed skill hash and assert that its Command section names
   the two Command tools while excluding the stale fallback.
5. Run legacy recovery dry-run for Brandon's exact saved event and inspect only
   content-free evidence.
6. Enqueue it once under `review_only` and wait for terminal completion.
7. Confirm Sydney's final response is canonical, the run succeeded, context
   health remains ready, and the audience came from Command.
8. Confirm the Gmail draft/send endpoints, Docs/Sheets writes, calendar writes,
   and CRM mutation audits show no action from the recovery run.

## Acceptance Criteria

- The Atlas operations skill is repository-owned, hash-verified, and installed
  automatically on every Atlas boot.
- Sydney treats Command URLs as locators and uses only the explicit Command
  tools for Command contacts.
- The old Drive roster and Google Contacts are never silent Command fallbacks.
- Brandon's exact saved pre-cutover request enters the durable queue once without
  creating a duplicate user event or requiring a slash command.
- Recovery produces one review packet using the current Command audience.
- No external mutation or email send occurs during recovery.
- Any actual future send requires fresh Brandon approval.
- Live Atlas health, exact 25-tool registration, durable run completion, and
  zero-mutation evidence all pass in production.

## Non-Goals

- Automatically replaying arbitrary historical tasks.
- Treating old user wording as current send approval.
- Adding autonomous bulk-email delivery.
- Creating hundreds of Gmail drafts during recovery.
- Scraping the authenticated admin UI.
- Replacing the existing post-cutover durable retry architecture.
