import type { Task } from '@/lib/command/api';
import type { ContactSmartView } from '@/lib/command/contacts';

type QueryValue = string | readonly string[] | undefined;
type QueryRecord = Readonly<Record<string, QueryValue>>;

export type TaskWorkspaceView = Readonly<{
  tab: 'all' | 'todo' | 'completed' | 'cancelled';
  due: 'all' | 'past';
}>;

export type LegacyContactWorkspaceView = Readonly<{
  smart_view: ContactSmartView;
}>;

function first(value: QueryValue): string | undefined {
  return typeof value === 'string' ? value : value?.[0];
}

export function parseTaskWorkspaceQuery(query: QueryRecord): TaskWorkspaceView {
  const tab = first(query.tab);
  const due = first(query.due);
  return {
    tab: tab === 'todo' || tab === 'completed' || tab === 'cancelled' ? tab : 'all',
    due: due === 'past' ? 'past' : 'all',
  };
}

export function applyTaskWorkspaceView(
  tasks: readonly Task[],
  view: TaskWorkspaceView,
  now: Date,
): Task[] {
  return tasks.filter((task) => {
    const status = task.status.toLowerCase();
    const statusMatches = view.tab === 'all'
      || (view.tab === 'todo' && (status === 'open' || status === 'in_progress'))
      || status === view.tab;
    if (!statusMatches) return false;
    if (view.due !== 'past') return true;
    if (!task.due_at) return false;
    const dueTime = Date.parse(task.due_at);
    return Number.isFinite(dueTime) && dueTime < now.getTime();
  });
}

function isContactSmartView(value: string | undefined): value is ContactSmartView {
  return value === 'all'
    || value === 'never_contacted'
    || value === 'recently_active'
    || value === 'birthdays_this_month'
    || value === 'anniversaries_this_month';
}

export function parseLegacyContactWorkspaceQuery(query: QueryRecord): LegacyContactWorkspaceView {
  const smartView = first(query.smart_view);
  if (isContactSmartView(smartView)) return { smart_view: smartView };
  const filter = first(query.filter);
  const sort = first(query.sort);
  if (filter === 'never_contacted') return { smart_view: 'never_contacted' };
  if (filter === 'birthdays') return { smart_view: 'birthdays_this_month' };
  if (filter === 'anniversaries') return { smart_view: 'anniversaries_this_month' };
  if (sort === 'recent_activity') return { smart_view: 'recently_active' };
  return { smart_view: 'all' };
}
