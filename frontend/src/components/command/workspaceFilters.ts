import type { Contact, Task } from '@/lib/command/api';

type QueryValue = string | readonly string[] | undefined;
type QueryRecord = Readonly<Record<string, QueryValue>>;

export type TaskWorkspaceView = Readonly<{
  tab: 'all' | 'todo' | 'completed' | 'cancelled';
  due: 'all' | 'past';
}>;

export type ContactWorkspaceView = Readonly<{
  kind: 'all' | 'never_contacted' | 'birthdays' | 'anniversaries' | 'recent_activity';
}>;

export type ContactWorkspaceViewResult =
  | Readonly<{ state: 'available'; rows: readonly Contact[] }>
  | Readonly<{ state: 'unavailable'; rows: readonly []; message: string }>;

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

export function parseContactWorkspaceQuery(query: QueryRecord): ContactWorkspaceView {
  const filter = first(query.filter);
  const sort = first(query.sort);
  if (filter === 'never_contacted' || filter === 'birthdays' || filter === 'anniversaries') {
    return { kind: filter };
  }
  if (sort === 'recent_activity') return { kind: 'recent_activity' };
  return { kind: 'all' };
}

function hasExplicitOptionalValue(value: string | null | undefined): value is string | null {
  return value === null || typeof value === 'string';
}

function monthOf(value: string): number | null {
  const match = /^\d{4}-(\d{2})-\d{2}/.exec(value);
  if (!match) return null;
  const month = Number(match[1]);
  return month >= 1 && month <= 12 ? month : null;
}

export function applyContactWorkspaceView(
  contacts: readonly Contact[],
  view: ContactWorkspaceView,
  now: Date,
): ContactWorkspaceViewResult {
  if (view.kind === 'all') return { state: 'available', rows: [...contacts] };

  if (view.kind === 'never_contacted') {
    const leads = contacts.filter((contact) => contact.stage.toLowerCase() === 'lead');
    if (!leads.every((contact) => hasExplicitOptionalValue(contact.last_contacted_at))) {
      return { state: 'unavailable', rows: [], message: 'Last-contact history is unavailable for this lead filter.' };
    }
    return {
      state: 'available',
      rows: leads.filter((contact) => contact.last_contacted_at === null),
    };
  }

  const field = view.kind === 'birthdays' ? 'birthday'
    : view.kind === 'anniversaries' ? 'anniversary'
      : 'recently_active_at';
  if (!contacts.every((contact) => hasExplicitOptionalValue(contact[field]))) {
    return {
      state: 'unavailable',
      rows: [],
      message: `${view.kind === 'recent_activity' ? 'Recent-activity' : 'Celebration'} evidence is unavailable for this view.`,
    };
  }

  if (view.kind === 'recent_activity') {
    return {
      state: 'available',
      rows: [...contacts].sort((left, right) => {
        const leftTime = left.recently_active_at ? Date.parse(left.recently_active_at) : Number.NEGATIVE_INFINITY;
        const rightTime = right.recently_active_at ? Date.parse(right.recently_active_at) : Number.NEGATIVE_INFINITY;
        return rightTime - leftTime || left.id - right.id;
      }),
    };
  }

  const month = now.getMonth() + 1;
  return {
    state: 'available',
    rows: contacts.filter((contact) => {
      const value = contact[field];
      return typeof value === 'string' && monthOf(value) === month;
    }),
  };
}
