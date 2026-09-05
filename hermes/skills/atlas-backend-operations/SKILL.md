---
name: atlas-backend-operations
description: Use when Sydney needs Sold With Sweeney backend, Command CRM, Google Workspace, booking, lead, or task-suggestion data through Atlas.
version: 2.2.2
---

# Atlas Backend Operations

## Core rule

Use registered Atlas tools as truth. Route by owning system; never substitute
history, memory, or a web page.

## Source routing

| Request | Use |
| --- | --- |
| Command birthdays, home anniversaries, or monthly celebrations | `command_contact_celebrations_preview` only |
| Physical birthday or home-anniversary cards | `command_card_campaign_draft_create` after the celebration preview |
| Command contacts or an `/admin/command` contact audience | `command_contacts_search` or `command_contact_audience_preview` |
| Google Contacts | `contacts_search` |
| Drive files, including native Sheets | `drive_search`, then `drive_file_read` |
| Gmail | `gmail_search`, then `gmail_thread_read` |
| Calendar | `calendar_events_read` |
| Durable conversation history | `context_history_search` |
| CRM tasks or suggestions | matching `crm_*` read tool |
| Leads, bookings, or voice reconciliation | `leads_recent`, `bookings_recent`, `actions_list` |

## Command contacts

- `command_contacts_search` is authoritative for current Command contact lookup.
- `command_contact_audience_preview` is authoritative for a complete filtered
  count, checksum, opaque reference, and masked sample.
- `command_contact_celebrations_preview` is the only authoritative source for
  birthday and home-anniversary audiences. Treat "my contacts" as Command when
  Brandon asks for those celebrations; do not search Google Contacts or Drive.
- A Command admin URL is a navigation locator, never a data endpoint. Never
  fetch or parse its HTML, React payload, or `__NEXT_DATA__`.
- `contacts_search` searches Google Contacts only; never substitute it for
  Command.
- `KW Success Agent Roster 2025` is historical. Use it only when Brandon asks
  for that former-office roster.
- For large audiences, use the bounded preview; do not load every contact into
  model context.

### Command workflow

1. Translate the request into supported query, stage, tag, source, or origin
   filters.
2. Preview a complete audience; search only for lookup, paging, or diagnosis.
3. Report returned count, checksum, reference, filters, and masked sample.
4. Propose outreach subject and body in chat. Preview never sends or drafts.
5. Stop for fresh Brandon approval before any external action.

For a request to check, list, source, or refresh celebrations or their contact
names, call the celebration preview once in the current turn for the requested
month and kinds. Do not reuse an earlier preview as a current query, even when
the conversation already contains its counts and sample. Never infer full names
from masked history; obtain them from the current authorized tool result.
Historical explanations are not fresh queries: they may cite an earlier result
as historical, but must not claim a new lookup. If a fresh read is unavailable,
say the current data could not be checked.

In Brandon's private chat, show the returned contact names and
celebration dates as provided; do not replace them with initials or stars. State
the exact counts and address readiness, and identify examples as a sample, not
the full audience. Keep checksums and audience references internal unless Brandon
asks for them. Do not reconstruct dates from notes, files, historical rosters, or
general contact searches.

## Physical cards

- Sydney may create or retrieve an internal card-campaign draft only through
  `command_card_campaign_draft_create`.
- Sydney cannot approve, send, or simulate provider delivery. Return the
  complete authenticated Command review URL and stop for Brandon's explicit review.
- Command prepares and reviews drafts; it is not itself a physical-card delivery
  provider. Do not call fulfillment connected unless the tool confirms it.
- Send Out Cards is unsupported until the backend reports a contracted API
  connection. Never scrape its website, run a browser macro, use local shell or
  files to imitate an integration, or substitute another provider silently.

## Google Workspace

- Read native Sheets through `drive_file_read`, not a browser rendering.
- Draft, send, Docs, Sheets, calendar, and CRM writes are mutations.
- `gmail_send` and `calendar_event_create` require fresh explicit Brandon
  approval and confirmation fields. Preserve a request UUID unless the earlier
  outcome is authenticated as not delivered.

## Task suggestions and approval links

- Read current suggestion/version before clarification, dismissal proposal, or
  approval-link work.
- Return a complete absolute Command URL. Opening it is not approval; Brandon
  reviews and clicks the authenticated approval action himself.

## Recovered work

- A legacy or restart recovery marked review-only stays review-only regardless
  of historical wording.
- Use current read tools; prepare count, checksum, masked sample, and proposed
  subject/body for general audiences. For celebrations, apply the real-name rule
  above and keep technical audience metadata internal.
- State clearly that nothing was sent.
- Old wording such as "send this" is not fresh approval after recovery.
- Never call any mutation during review-only recovery.

## Security

- Use only protected Atlas tools. Never inspect process environments, retrieve
  admin passwords, bypass authentication, or scrape private CRM pages.
- Native shell, code execution, process, filesystem, browser, session-search,
  and local-memory tools are outside Sydney's business-tool lane. Do not invoke
  them; use `skill_view` for these instructions and registered Atlas tools for
  work.
- If the authoritative tool is unavailable, name the gap and stop; never replace
  it silently.
