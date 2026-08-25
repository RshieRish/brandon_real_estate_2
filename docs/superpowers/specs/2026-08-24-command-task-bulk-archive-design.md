# Command Task Bulk Archive Design

**Date:** 2026-08-24
**Author:** Codex, following the user's approved direction
**Scope:** Command Tasks workspace, FastAPI task lifecycle API, and focused automated coverage
**Status:** Approved for implementation planning

---

## Problem

The Command Tasks workspace loads the authoritative task ledger but renders every matching task in one unpaginated list. It supports only a single selected task and a single archive request. An administrator therefore cannot select several tasks, select one page, or select all tasks matching the current view before archiving.

## Goals

- Paginate the rendered task list at 25 tasks per page without changing the authoritative task source.
- Allow individual task selection in the active workspace.
- Allow selecting or clearing every task on the current page.
- After a page is selected, offer a separate action to select every task matching the active status and due-date filters across all pages.
- Keep selection while moving between pages.
- Archive the selected tasks with one confirmation and one optional shared reason.
- Preserve each task's optimistic version and unique lifecycle request identity.
- Return and display an outcome for every requested task so conflicts are never hidden.
- Keep failed or conflicted tasks selected for review and retry while clearing successful tasks from the selection.

## Non-goals

- No bulk Restore in this slice.
- No hard delete.
- No selection of archived tasks.
- No server-side search, cursor pagination, or saved selection sets.
- No automatic retry after an uncertain network outcome.
- No change to task workflow status, source evidence, or lifecycle audit semantics.

## User Experience

The active task list gains a selection checkbox on every task and a compact selection toolbar above the list. The toolbar shows the selected count and provides:

- `Select this page` or `Clear this page`, based on the current page state.
- `Select all N matching tasks` after the current page has been selected and more matching tasks exist.
- `Clear selection` whenever at least one task is selected.
- `Archive selected` whenever at least one task is selected.

The list shows 25 tasks per page with Previous and Next controls plus `Page X of Y`. Selection persists when the user moves between pages. Changing Active/Archived visibility, status, or due-date filters clears the selection and returns to page 1 so hidden tasks cannot be archived accidentally.

The existing overflow-menu archive remains available for a single task. Bulk archive opens a separate modal that states the exact number of tasks, explains that the action is reversible, and accepts one optional shared reason.

After the response:

- Successful tasks move to Archived and are removed from the active view.
- Successful task IDs are removed from the selection.
- Conflicted or rejected tasks remain selected and visible under the current filter when possible.
- A status message reports the success count.
- An error summary reports each unsuccessful task by title and reason.
- Page position is clamped if the current page becomes empty.

## API Contract

Add `POST /api/v1/command/tasks/bulk-archive` behind the existing authenticated Command boundary and `CRM_TASK_ARCHIVE_ENABLED` flag.

The request contains a bounded list of 1 to 500 items. Every item contains:

- `task_id`
- `request_id`, a UUID unique to that task archive intent
- `expected_version`

The request also contains one optional trimmed archive reason shared by the batch. Duplicate task IDs or request IDs are invalid.

The backend processes the items in stable task-ID order through `crm_task_service.archive`; it does not add a second lifecycle implementation. Each item returns exactly one discriminated result:

- `archived` with the authoritative task row
- `conflict` with the authoritative current task and conflict code
- `not_found`
- `invalid`

Logical per-task failures do not erase successful task results. Authentication failure, a disabled archive flag, malformed batch input, or an unexpected infrastructure failure rejects the whole HTTP request. Exact replay remains safe because each task uses its own existing lifecycle request ID and payload contract.

## Client Data Flow

The workspace continues to fetch `visibility=all` and derives the active filtered collection locally. Selection stores task IDs, not page indexes. Before opening confirmation, the client snapshots the selected tasks' IDs and versions and generates one request UUID per task. The same snapshot is reused only when reconciling an uncertain response; no automatic second write is sent.

On an uncertain response, the workspace performs one authoritative all-task refresh. Tasks that reached an archived state at a version newer than the submitted version are treated as applied. Exact unchanged tasks remain selected for a fresh user-initiated attempt. Any other state is reported as changed elsewhere. This keeps the existing server-authoritative, no-blind-retry lifecycle rule.

## Accessibility and Visual Rules

- Use native checkboxes with task-specific accessible names.
- The page-selection checkbox exposes checked, unchecked, and indeterminate states.
- All bulk actions meet the existing 44-pixel touch target rule.
- The confirmation dialog uses the existing focus-containment behavior and returns focus to `Archive selected` on cancel.
- Selection, progress, success, and error changes are announced through existing live-region patterns.
- The visual treatment stays within the existing dark black-and-gold Command system and uses Phosphor icons only.
- Archived-state contrast and explanatory text retain the existing accessible color requirements.

## Testing

Backend tests cover request validation, authentication, feature-flag enforcement, stable processing order, successful multi-archive, mixed conflict/not-found results, shared reason normalization, and exact replay.

Frontend API tests cover strict request/response encoding, malformed response rejection, and uncertain outcome classification. Workspace tests cover individual selection, current-page selection, all-matching selection, selection persistence across pages, filter reset, confirmation, mixed outcomes, uncertain-response reconciliation, page clamping, focus, keyboard use, touch targets, and live announcements. The final gate includes focused backend and frontend tests, TypeScript, scoped lint, and a production frontend build.

