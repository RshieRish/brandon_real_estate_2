import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Task } from '@/lib/command/api';
import type {
  ContactDirectoryPage,
  ContactDirectoryRow,
  ContactsApi,
} from '@/lib/command/contacts';
import { ContactsWorkspace } from './ContactsWorkspace';
import { TasksWorkspace } from './TasksWorkspace';
import { CommandToastProvider } from './ui/CommandToastProvider';
import { applyTaskWorkspaceView, parseLegacyContactWorkspaceQuery, parseTaskWorkspaceQuery } from './workspaceFilters';

const apiMocks = vi.hoisted(() => ({
  contacts: vi.fn(),
  tasks: vi.fn(),
}));
const navigation = vi.hoisted(() => ({
  pathname: '/admin/command/contacts',
  push: vi.fn(),
  replace: vi.fn(),
  search: new URLSearchParams(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push, replace: navigation.replace }),
  useSearchParams: () => navigation.search,
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

const contact: ContactDirectoryRow = {
  id: 1,
  first_name: 'Never',
  last_name: 'Lead',
  display_name: 'Never Lead',
  primary_email: null,
  primary_phone: null,
  stage: 'lead',
  lead_backed: false,
  origins: ['internal_only'],
  sources: ['internal_crm'],
  health_score: null,
  last_contacted_at: null,
  last_interaction_at: null,
  owner: null,
  assignee: null,
  tags: [],
  birthday: null,
  anniversary: null,
  evidence_quality: null,
};

function contactPage(): ContactDirectoryPage {
  return { rows: [contact], total: 1, page: 1, page_size: 50, page_count: 1, sort: 'name', direction: 'asc' };
}

function contactApi(): ContactsApi {
  return {
    directory: vi.fn().mockResolvedValue(contactPage()),
    detail: vi.fn(), neighbors: vi.fn(), workspace: vi.fn(), internalWorkspace: vi.fn(), timeline: vi.fn(),
    section: vi.fn(), evidence: vi.fn(), celebrations: vi.fn(), create: vi.fn(),
    update: vi.fn(), bulk: vi.fn(), createNote: vi.fn(), deleteNote: vi.fn(),
    createSavedSearch: vi.fn(), createTag: vi.fn(), assignTag: vi.fn(),
    removeTag: vi.fn(), createTask: vi.fn(), artifactBlob: vi.fn(),
  };
}

describe('Command workspace deep links', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date('2026-08-12T13:00:00.000Z'));
    apiMocks.contacts.mockReset().mockResolvedValue([]);
    apiMocks.tasks.mockReset().mockResolvedValue(tasks);
    navigation.search = new URLSearchParams();
    navigation.push.mockReset();
    navigation.replace.mockReset();
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

  it('parses canonical SmartViews before all exact legacy aliases', () => {
    expect(parseLegacyContactWorkspaceQuery({ smart_view: 'recently_active', filter: 'birthdays' })).toEqual({ smart_view: 'recently_active' });
    expect(parseLegacyContactWorkspaceQuery({ filter: 'never_contacted' })).toEqual({ smart_view: 'never_contacted' });
    expect(parseLegacyContactWorkspaceQuery({ filter: 'birthdays' })).toEqual({ smart_view: 'birthdays_this_month' });
    expect(parseLegacyContactWorkspaceQuery({ filter: 'anniversaries' })).toEqual({ smart_view: 'anniversaries_this_month' });
    expect(parseLegacyContactWorkspaceQuery({ sort: 'recent_activity' })).toEqual({ smart_view: 'recently_active' });
    expect(parseLegacyContactWorkspaceQuery({ filter: 'unknown', sort: 'unknown' })).toEqual({ smart_view: 'all' });
  });

  it.each([
    ['filter=never_contacted', 'never_contacted'],
    ['filter=birthdays', 'birthdays_this_month'],
    ['filter=anniversaries', 'anniversaries_this_month'],
    ['sort=recent_activity', 'recently_active'],
  ] as const)('requests and canonicalizes the legacy Contacts deep link %s', async (search, smartView) => {
    navigation.search = new URLSearchParams(search);
    navigation.replace.mockReset();
    const api = contactApi();
    const view = parseLegacyContactWorkspaceQuery(Object.fromEntries(navigation.search));
    render(
      <CommandToastProvider>
        <ContactsWorkspace initialView={view.smart_view} api={api} />
      </CommandToastProvider>,
    );

    await waitFor(() => expect(api.directory).toHaveBeenCalledWith(
      expect.objectContaining({ smart_view: smartView }),
      { signal: expect.any(AbortSignal) },
    ));
    const active = screen.getByRole('tab', { selected: true });
    await userEvent.click(active);
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toContain(`smart_view=${smartView}`);
    expect(navigation.replace.mock.calls.at(-1)?.[0]).not.toMatch(/filter=|sort=recent_activity/);
  });
});
