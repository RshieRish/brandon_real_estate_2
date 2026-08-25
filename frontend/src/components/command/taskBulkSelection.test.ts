import { describe, expect, it } from 'vitest';
import type { Task } from '@/lib/command/api';
import {
  TASKS_PER_PAGE,
  clampPage,
  pageCount,
  reconcileBulkArchiveAttempt,
  retainEligibleSelection,
  selectAllMatching,
  tasksForPage,
  togglePageSelection,
  toggleTaskSelection,
} from './taskBulkSelection';

const task = (id: number, overrides: Partial<Task> = {}): Task => ({
  id,
  title: `Task ${id}`,
  contact_id: null,
  description: '',
  priority: 'normal',
  due_at: null,
  status: 'open',
  archived_at: null,
  archive_reason: null,
  version: 1,
  ...overrides,
});

describe('task bulk selection helpers', () => {
  it('uses 25-row pages and clamps page positions after removals', () => {
    const rows = Array.from({ length: 51 }, (_, index) => task(index + 1));
    expect(TASKS_PER_PAGE).toBe(25);
    expect(pageCount(rows.length)).toBe(3);
    expect(tasksForPage(rows, 2).map((row) => row.id)).toEqual(
      Array.from({ length: 25 }, (_, index) => index + 26),
    );
    expect(tasksForPage(rows, 3).map((row) => row.id)).toEqual([51]);
    expect(clampPage(3, 25)).toBe(1);
    expect(clampPage(0, 0)).toBe(1);
  });

  it('toggles one task without mutating the existing selection', () => {
    const original = new Set([2]);
    const added = toggleTaskSelection(original, 3);
    const removed = toggleTaskSelection(added, 2);
    expect([...original]).toEqual([2]);
    expect([...added].sort()).toEqual([2, 3]);
    expect([...removed]).toEqual([3]);
  });

  it('selects and clears only the current page while retaining other pages', () => {
    const original = new Set([40]);
    const selected = togglePageSelection(original, [1, 2, 3]);
    expect([...selected].sort((left, right) => left - right)).toEqual([1, 2, 3, 40]);
    const cleared = togglePageSelection(selected, [1, 2, 3]);
    expect([...cleared]).toEqual([40]);
  });

  it('selects all matching IDs and drops IDs that are no longer eligible', () => {
    const selected = selectAllMatching([1, 2, 3, 4]);
    expect([...selected]).toEqual([1, 2, 3, 4]);
    expect([...retainEligibleSelection(selected, [2, 4])]).toEqual([2, 4]);
  });

  it('classifies applied, unchanged, and changed tasks after uncertainty', () => {
    const original = [task(1), task(2), task(3)];
    const result = reconcileBulkArchiveAttempt(
      original.map((row) => ({
        task_id: row.id,
        expected_version: row.version,
        originalTask: row,
      })),
      [
        task(1, {
          version: 2,
          archived_at: '2026-08-24T20:00:00Z',
          archive_reason: 'Cleanup',
        }),
        task(2),
        task(3, { version: 2, description: 'Changed elsewhere' }),
      ],
    );
    expect(result.applied.map((row) => row.id)).toEqual([1]);
    expect(result.unchangedIds).toEqual([2]);
    expect(result.changedIds).toEqual([3]);
  });
});
