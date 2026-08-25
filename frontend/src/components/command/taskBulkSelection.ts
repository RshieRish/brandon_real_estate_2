import type { Task } from '@/lib/command/api';

export const TASKS_PER_PAGE = 25;

export type BulkArchiveAttemptItem = Readonly<{
  task_id: number;
  expected_version: number;
  originalTask: Task;
}>;

export type BulkArchiveReconciliation = Readonly<{
  applied: readonly Task[];
  unchangedIds: readonly number[];
  changedIds: readonly number[];
}>;

export function pageCount(totalRows: number): number {
  return Math.max(1, Math.ceil(Math.max(0, totalRows) / TASKS_PER_PAGE));
}

export function clampPage(page: number, totalRows: number): number {
  const normalized = Number.isSafeInteger(page) ? page : 1;
  return Math.min(Math.max(1, normalized), pageCount(totalRows));
}

export function tasksForPage<Row>(rows: readonly Row[], page: number): readonly Row[] {
  const current = clampPage(page, rows.length);
  const start = (current - 1) * TASKS_PER_PAGE;
  return rows.slice(start, start + TASKS_PER_PAGE);
}

export function toggleTaskSelection(selected: ReadonlySet<number>, taskId: number): Set<number> {
  const next = new Set(selected);
  if (next.has(taskId)) next.delete(taskId);
  else next.add(taskId);
  return next;
}

export function togglePageSelection(
  selected: ReadonlySet<number>,
  pageTaskIds: readonly number[],
): Set<number> {
  const next = new Set(selected);
  const pageIsSelected = pageTaskIds.length > 0
    && pageTaskIds.every((taskId) => next.has(taskId));
  for (const taskId of pageTaskIds) {
    if (pageIsSelected) next.delete(taskId);
    else next.add(taskId);
  }
  return next;
}

export function selectAllMatching(taskIds: readonly number[]): Set<number> {
  return new Set(taskIds);
}

export function retainEligibleSelection(
  selected: ReadonlySet<number>,
  eligibleTaskIds: readonly number[],
): Set<number> {
  const eligible = new Set(eligibleTaskIds);
  return new Set([...selected].filter((taskId) => eligible.has(taskId)));
}

function sameTask(left: Task | undefined, right: Task): boolean {
  return left !== undefined
    && left.id === right.id
    && left.title === right.title
    && left.contact_id === right.contact_id
    && left.description === right.description
    && left.priority === right.priority
    && left.due_at === right.due_at
    && left.status === right.status
    && left.archived_at === right.archived_at
    && left.archive_reason === right.archive_reason
    && left.version === right.version;
}

export function reconcileBulkArchiveAttempt(
  attempt: readonly BulkArchiveAttemptItem[],
  authoritativeRows: readonly Task[],
): BulkArchiveReconciliation {
  const authoritativeById = new Map(authoritativeRows.map((task) => [task.id, task]));
  const applied: Task[] = [];
  const unchangedIds: number[] = [];
  const changedIds: number[] = [];
  for (const item of attempt) {
    const authoritative = authoritativeById.get(item.task_id);
    if (
      authoritative !== undefined
      && authoritative.archived_at !== null
      && authoritative.version > item.expected_version
    ) {
      applied.push(authoritative);
    } else if (sameTask(authoritative, item.originalTask)) {
      unchangedIds.push(item.task_id);
    } else {
      changedIds.push(item.task_id);
    }
  }
  return { applied, unchangedIds, changedIds };
}
