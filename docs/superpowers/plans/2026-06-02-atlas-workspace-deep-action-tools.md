# Atlas Workspace Deep Action Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the protected Atlas/Hermes backend bridge with deeper Google Workspace read tools plus confirmed calendar-event creation.

**Architecture:** Keep all Google API access in `backend/services/workspace_service.py`, expose only audited FastAPI routes in `backend/routers/agent_control.py`, and model requests/responses in `backend/schemas/agent_control.py`. Read actions are allowed silently through the existing bearer token, while creating a calendar event requires `confirmed_by_brandon=true` and audit metadata that excludes message bodies, file contents, row values, and recipient addresses.

**Tech Stack:** FastAPI, Pydantic, Google API Python Client, SQLAlchemy async audit logging, unittest.

---

### Task 1: Workspace Service Deep Helpers

**Files:**
- Modify: `backend/services/workspace_service.py`
- Test: `backend/tests/test_workspace_actions.py`

- [x] **Step 1: Write failing service tests**

Add tests for these helper behaviors:
- `search_gmail_messages(query, page_size=10)` lists matching messages, fetches compact metadata for each message, caps `page_size` at 25, and returns message id, thread id, snippet, subject, from, to, and date.
- `get_gmail_thread(thread_id, max_body_chars=4000)` reads a Gmail thread and extracts text from message payloads while respecting the body limit.
- `read_drive_file(file_id, max_chars=4000)` fetches metadata and exports Google Docs as `text/plain`, returning text plus a `truncated` flag.
- `list_calendar_events(time_min, time_max, page_size=10, calendar_id="primary")` lists Calendar events from Brandon's Workspace token.
- `create_workspace_calendar_event(...)` inserts a Calendar event with attendees and `sendUpdates="all"`.
- `search_contacts(query, page_size=10)` uses the People API to search Brandon's contacts and return compact names, emails, phones, and resource names.

- [x] **Step 2: Run service tests and confirm RED**

Run:
`./.venv/bin/python -m unittest tests.test_workspace_actions -v`

Expected: failures for missing helper functions.

- [x] **Step 3: Implement service helpers**

Add the helper functions listed above, plus small private helpers for Gmail header extraction, Gmail body text extraction, text truncation, and ISO datetime formatting.

- [x] **Step 4: Run service tests and confirm GREEN**

Run:
`./.venv/bin/python -m unittest tests.test_workspace_actions -v`

Expected: all Workspace service helper tests pass.

### Task 2: Agent-Control Deep Routes

**Files:**
- Modify: `backend/schemas/agent_control.py`
- Modify: `backend/routers/agent_control.py`
- Test: `backend/tests/test_agent_control_workspace_actions.py`
- Test: `backend/tests/test_agent_control_router.py`

- [x] **Step 1: Write failing route and catalog tests**

Add route tests that call handlers directly with fake DB/request/agent and patched service helpers:
- Gmail search route returns compact messages and audits `workspace.gmail.search`.
- Gmail thread route returns message body text while audit metadata only stores counts/lengths.
- Drive file route returns file text and audits `workspace.drive.file.read`.
- Calendar events route returns event summaries and audits `workspace.calendar.events.read`.
- Calendar event create route rejects without `confirmed_by_brandon=true`, then creates and audits when confirmed.
- Contacts search route returns contacts and audits `workspace.contacts.search`.
- Action catalog/status includes all six new action ids and marks calendar create as `human_confirm`.

- [x] **Step 2: Run route tests and confirm RED**

Run:
`./.venv/bin/python -m unittest tests.test_agent_control_workspace_actions tests.test_agent_control_router -v`

Expected: failures for missing schemas/routes/action ids.

- [x] **Step 3: Implement schemas and routes**

Add request/response models and routes under:
- `POST /api/v1/agent-control/workspace/gmail/search`
- `POST /api/v1/agent-control/workspace/gmail/thread`
- `POST /api/v1/agent-control/workspace/drive/file`
- `POST /api/v1/agent-control/workspace/calendar/events`
- `POST /api/v1/agent-control/workspace/calendar/event/create`
- `POST /api/v1/agent-control/workspace/contacts/search`

Each route must call `load_workspace_refresh_token_from_db(db)`, use the service helper, and write audit metadata without raw email bodies, Drive text, or contact addresses.

- [x] **Step 4: Run focused backend tests**

Run:
`./.venv/bin/python -m unittest tests.test_workspace_actions tests.test_agent_control_workspace_actions tests.test_agent_control_router tests.test_workspace_oauth tests.test_workspace_token_persistence tests.test_agent_control_auth -v`

Expected: all tests pass.

### Task 3: Documentation, Deployment, And Verification

**Files:**
- Modify: `docs/deployment/hermes-railway.md`
- Modify: `tdtn.md`
- Modify: `memory.md`

- [x] **Step 1: Verify locally**

Run focused backend tests and `git diff --check`.

- [x] **Step 2: Commit and push**

Commit implementation and docs on the current branch, then push.

- [x] **Step 3: Verify Railway**

Wait for Railway backend auto-deploy to reach `SUCCESS`, then smoke test:
- `/api/v1/agent-control/status` includes the new Workspace deep action capabilities.
- `/api/v1/agent-control/actions` lists the new action ids.
- `/api/v1/agent-control/workspace/status` remains connected.

- [x] **Step 4: Update remaining-work notes**

Record that Telegram channel setup and Hermes-side tool invocation wiring remain, while the backend Workspace command surface now includes Gmail, Drive, Calendar, Contacts, Docs, and Sheets.
