import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Contact, Task } from '@/lib/command/api';
import { ContactsWorkspace } from './ContactsWorkspace';
import { TasksWorkspace } from './TasksWorkspace';
import {
  applyContactWorkspaceView,
  applyTaskWorkspaceView,
  parseContactWorkspaceQuery,
  parseTaskWorkspaceQuery,
} from './workspaceFilters';

const apiMocks = vi.hoisted(() => ({
  contacts: vi.fn(),
  tasks: vi.fn(),
}));

vi.mock('@/lib/command/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/command/api')>();
  return {
    ...actual,
    commandApi: {
      ...actual.commandApi,
      contacts: apiMocks.contacts,
      tasks: apiMocks.tasks,
    },
  };
});

const tasks: Task[] = [
  { id: 1, title: 'Past open', contact_id: null, description: '', priority: 'high', due_at: '2026-08-10T12:00:00.000Z', status: 'open' },
  { id: 2, title: 'Past in progress', contact_id: null, description: '', priority: 'normal', due_at: '2026-08-11T12:00:00.000Z', status: 'in_progress' },
  { id: 3, title: 'Future open', contact_id: null, description: '', priority: 'normal', due_at: '2026-08-14T12:00:00.000Z', status: 'open' },
  { id: 4, title: 'Past completed', contact_id: null, description: '', priority: 'low', due_at: '2026-08-09T12:00:00.000Z', status: 'completed' },
  { id: 5, title: 'Undated open', contact_id: null, description: '', priority: 'low', due_at: null, status: 'open' },
];

const contacts: Contact[] = [
  { id: 1, first_name: 'Never', last_name: 'Lead', email: null, phone: null, stage: 'lead', birthday: null, anniversary: null, last_contacted_at: null, recently_active_at: null },
  { id: 2, first_name: 'Contacted', last_name: 'Lead', email: null, phone: null, stage: 'lead', birthday: '1990-08-20', anniversary: null, last_contacted_at: '2026-08-01T12:00:00.000Z', recently_active_at: '2026-08-11T12:00:00.000Z' },
  { id: 3, first_name: 'Recent', last_name: 'Client', email: null, phone: null, stage: 'client', birthday: null, anniversary: '2019-08-12', last_contacted_at: '2026-07-01T12:00:00.000Z', recently_active_at: '2026-08-12T12:00:00.000Z' },
];

describe('Command workspace deep links', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date('2026-08-12T13:00:00.000Z'));
    apiMocks.contacts.mockReset().mockResolvedValue(contacts);
    apiMocks.tasks.mockReset().mockResolvedValue(tasks);
  });

  it('parses and applies the exact overdue to-do task queue', () => {
    const view = parseTaskWorkspaceQuery({ tab: 'todo', due: 'past' });
    expect(view).toEqual({ tab: 'todo', due: 'past' });
    expect(applyTaskWorkspaceView(tasks, view, new Date())).toEqual([tasks[0], tasks[1]]);
  });

  it('renders the Tasks destination with the deep-linked controls and exact rows active', async () => {
    render(<TasksWorkspace initialView={{ tab: 'todo', due: 'past' }} />);

    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalled());
    expect(screen.getByRole('combobox', { name: 'Task status' })).toHaveValue('todo');
    expect(screen.getByRole('combobox', { name: 'Task due scope' })).toHaveValue('past');
    expect(screen.getByText('Past open')).toBeInTheDocument();
    expect(screen.getByText('Past in progress')).toBeInTheDocument();
    expect(screen.queryByText('Future open')).not.toBeInTheDocument();
    expect(screen.queryByText('Past completed')).not.toBeInTheDocument();
    expect(screen.queryByText('Undated open')).not.toBeInTheDocument();
  });

  it('parses and applies every supported Contacts shortcut without inventing missing evidence', () => {
    expect(parseContactWorkspaceQuery({ filter: 'never_contacted' })).toEqual({ kind: 'never_contacted' });
    expect(parseContactWorkspaceQuery({ filter: 'birthdays' })).toEqual({ kind: 'birthdays' });
    expect(parseContactWorkspaceQuery({ filter: 'anniversaries' })).toEqual({ kind: 'anniversaries' });
    expect(parseContactWorkspaceQuery({ sort: 'recent_activity' })).toEqual({ kind: 'recent_activity' });

    expect(applyContactWorkspaceView(contacts, { kind: 'never_contacted' }, new Date())).toMatchObject({
      state: 'available',
      rows: [contacts[0]],
    });
    expect(applyContactWorkspaceView(contacts, { kind: 'birthdays' }, new Date())).toMatchObject({
      state: 'available',
      rows: [contacts[1]],
    });
    expect(applyContactWorkspaceView(contacts, { kind: 'anniversaries' }, new Date())).toMatchObject({
      state: 'available',
      rows: [contacts[2]],
    });
    expect(applyContactWorkspaceView(contacts, { kind: 'recent_activity' }, new Date())).toMatchObject({
      state: 'available',
      rows: [contacts[2], contacts[1], contacts[0]],
    });
    expect(applyContactWorkspaceView(
      [{ ...contacts[0], last_contacted_at: undefined }, contacts[1]],
      { kind: 'never_contacted' },
      new Date(),
    )).toMatchObject({ state: 'unavailable' });
  });

  it('renders the Contacts destination with the never-contacted filter active', async () => {
    render(<ContactsWorkspace initialView={{ kind: 'never_contacted' }} />);

    const table = await screen.findByRole('table');
    await waitFor(() => expect(within(table).getByText('Never Lead')).toBeInTheDocument());
    expect(screen.getByRole('combobox', { name: 'Contact view' })).toHaveValue('never_contacted');
    expect(within(table).queryByText('Contacted Lead')).not.toBeInTheDocument();
    expect(within(table).queryByText('Recent Client')).not.toBeInTheDocument();
  });
});
