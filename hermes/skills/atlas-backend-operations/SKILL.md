---
name: atlas-backend-operations
description: Use when Sydney needs Sold With Sweeney backend, Command CRM, Google Workspace, booking, lead, or task-suggestion data through Atlas.
version: 2.0.0
---

# Atlas Backend Operations

## Core rule

Use registered Atlas tools as truth. Route by owning system; never substitute
history, memory, or a web page.

## Source routing

| Request | Use |
| --- | --- |
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
  subject/body.
- State clearly that nothing was sent.
- Old wording such as "send this" is not fresh approval after recovery.
- Never call any mutation during review-only recovery.

## Security

- Use only protected Atlas tools. Never inspect process environments, retrieve
  admin passwords, bypass authentication, or scrape private CRM pages.
- If the authoritative tool is unavailable, name the gap and stop; never replace
  it silently.
