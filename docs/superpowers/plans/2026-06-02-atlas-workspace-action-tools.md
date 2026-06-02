# Atlas Workspace Action Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first protected Google Workspace action tools that Hermes can call through the existing FastAPI agent-control bridge.

**Architecture:** Keep all API logic in the Python backend. Extend `services.workspace_service` with small Google API helpers, extend `schemas.agent_control` with request/response models, and mount audited `/api/v1/agent-control/workspace/*` routes protected by `AGENT_CONTROL_TOKEN`. Avoid autonomous irreversible actions by requiring explicit `confirmed_by_brandon=true` for direct Gmail send.

**Tech Stack:** FastAPI, Pydantic, Google API Python Client, SQLAlchemy async audit logging, unittest.

---

### Task 1: Workspace Service Helpers

**Files:**
- Modify: `backend/services/workspace_service.py`
- Test: `backend/tests/test_workspace_actions.py`

- [ ] **Step 1: Write failing tests**

Create tests that patch `build_workspace_service` and verify:
- `create_gmail_draft()` calls Gmail `users().drafts().create()`.
- `send_gmail_message()` calls Gmail `users().messages().send()`.
- `search_drive_files()` calls Drive `files().list()`.
- `create_google_doc()` calls Docs `documents().create()` and `documents().batchUpdate()`.
- `append_sheet_values()` calls Sheets `spreadsheets().values().append()`.

- [ ] **Step 2: Run tests and confirm they fail**

Run: `./.venv/bin/python -m unittest tests.test_workspace_actions -v`

Expected: import/name failures because the helpers do not exist.

- [ ] **Step 3: Implement helpers**

Add helper functions in `workspace_service.py`:
- `create_gmail_draft(to, subject, body_text, cc=None, bcc=None)`
- `send_gmail_message(to, subject, body_text, cc=None, bcc=None)`
- `search_drive_files(query, page_size=10)`
- `create_google_doc(title, body_text)`
- `append_sheet_values(spreadsheet_id, range_name, values)`

- [ ] **Step 4: Run tests and confirm green**

Run: `./.venv/bin/python -m unittest tests.test_workspace_actions -v`

Expected: all tests pass.

### Task 2: Agent-Control Routes

**Files:**
- Modify: `backend/schemas/agent_control.py`
- Modify: `backend/routers/agent_control.py`
- Test: `backend/tests/test_agent_control_workspace_actions.py`

- [ ] **Step 1: Write failing route tests**

Create tests that call the route functions directly with fake DB/request/agent and patched Workspace helpers:
- Gmail draft returns the draft id and audits `workspace.gmail.draft.create`.
- Gmail send rejects when `confirmed_by_brandon=false`.
- Drive search returns sanitized file summaries.
- Docs create returns document id/url.
- Sheets append returns updated range/row count.

- [ ] **Step 2: Run tests and confirm they fail**

Run: `./.venv/bin/python -m unittest tests.test_agent_control_workspace_actions -v`

Expected: route/schema import failures because the models and routes do not exist yet.

- [ ] **Step 3: Implement schemas and routes**

Add Pydantic models for each request/response and route handlers under:
- `GET /api/v1/agent-control/workspace/status`
- `POST /api/v1/agent-control/workspace/gmail/draft`
- `POST /api/v1/agent-control/workspace/gmail/send`
- `POST /api/v1/agent-control/workspace/drive/search`
- `POST /api/v1/agent-control/workspace/docs/create`
- `POST /api/v1/agent-control/workspace/sheets/append`

All routes must call `load_workspace_refresh_token_from_db(db)`, audit with metadata that excludes body content and row values, and return compact IDs/URLs/counts.

- [ ] **Step 4: Run focused backend tests**

Run:
`./.venv/bin/python -m unittest tests.test_workspace_actions tests.test_agent_control_workspace_actions tests.test_agent_control_router tests.test_workspace_oauth tests.test_workspace_token_persistence -v`

Expected: all tests pass.

### Task 3: Deploy And Verify

**Files:**
- Modify: `tdtn.md`
- Modify: `memory.md`

- [ ] **Step 1: Verify locally**

Run backend focused tests and `git diff --check`.

- [ ] **Step 2: Commit and push**

Commit implementation and docs.

- [ ] **Step 3: Deploy and smoke test**

Deploy backend to Railway or let the push-triggered backend deployment complete. Verify:
- `/api/v1/agent-control/status` includes the new Workspace capabilities.
- `/api/v1/agent-control/actions` lists the new Workspace actions.
- Workspace status route returns connected.

- [ ] **Step 4: Update notes**

Update `tdtn.md` and `memory.md` with exactly what is now live and what remains for Telegram/Hermes channel wiring.
