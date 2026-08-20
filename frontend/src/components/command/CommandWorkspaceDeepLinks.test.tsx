import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as commandApiModule from '@/lib/command/api';
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
  createTask: vi.fn(),
  updateTask: vi.fn(),
  addTaskLink: vi.fn(),
  taskLinks: vi.fn(),
  opportunities: vi.fn(),
  agreements: vi.fn(),
  listings: vi.fn(),
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
      createTask: apiMocks.createTask,
      updateTask: apiMocks.updateTask,
      addTaskLink: apiMocks.addTaskLink,
      taskLinks: apiMocks.taskLinks,
      opportunities: apiMocks.opportunities,
      agreements: apiMocks.agreements,
      listings: apiMocks.listings,
    },
  };
});

const tasks: Task[] = [
  { id: 1, title: 'Past open', contact_id: null, description: '', priority: 'high', due_at: '2026-08-10T12:00:00.000Z', status: 'open', archived_at: null, archive_reason: null, version: 1 },
  { id: 2, title: 'Past in progress', contact_id: null, description: '', priority: 'normal', due_at: '2026-08-11T12:00:00.000Z', status: 'in_progress', archived_at: null, archive_reason: null, version: 1 },
  { id: 3, title: 'Future open', contact_id: null, description: '', priority: 'normal', due_at: '2026-08-14T12:00:00.000Z', status: 'open', archived_at: null, archive_reason: null, version: 1 },
  { id: 4, title: 'Past completed', contact_id: null, description: '', priority: 'low', due_at: '2026-08-09T12:00:00.000Z', status: 'completed', archived_at: null, archive_reason: null, version: 1 },
  { id: 5, title: 'Undated open', contact_id: null, description: '', priority: 'low', due_at: null, status: 'open', archived_at: null, archive_reason: null, version: 1 },
  { id: 6, title: 'Archived open', contact_id: null, description: '', priority: 'high', due_at: '2026-08-08T12:00:00.000Z', status: 'open', archived_at: '2026-08-12T12:00:00.000Z', archive_reason: 'Superseded', version: 2 },
];

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function outcomeError(kind: 'uncertain' | 'conflict'): Error {
  const exportName = kind === 'uncertain' ? 'CommandOutcomeUncertainError' : 'CommandConflictError';
  const Constructor = Reflect.get(commandApiModule, exportName);
  if (typeof Constructor === 'function') {
    return kind === 'uncertain'
      ? new (Constructor as new (cause: unknown) => Error)(new TypeError('Synthetic disconnect'))
      : new (Constructor as new (conflict: unknown) => Error)({
          code: 'task_version_conflict',
          current_version: 2,
          current_task: { ...tasks[0], version: 2 },
        });
  }
  return Object.assign(new Error(kind), { name: kind === 'uncertain' ? 'CommandOutcomeUncertainError' : 'CommandConflictError' });
}

function deferred<Value>() {
  let resolve!: (value: Value) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<Value>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

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
    apiMocks.createTask.mockReset().mockResolvedValue({
      ...tasks[0], id: 99, title: 'New task', priority: 'normal', due_at: null, version: 1,
    });
    apiMocks.updateTask.mockReset().mockImplementation(async (_id, payload) => ({
      ...tasks[0], ...payload, version: tasks[0]!.version + 1,
    }));
    apiMocks.addTaskLink.mockReset().mockResolvedValue({
      id: 20, task_id: 1, entity_type: 'agreement', entity_id: 19,
      display_name: 'Buyer agreement', task_version: 2,
    });
    apiMocks.taskLinks.mockReset().mockResolvedValue([]);
    apiMocks.opportunities.mockReset().mockResolvedValue([]);
    apiMocks.agreements.mockReset().mockResolvedValue([
      { id: 19, title: 'Buyer agreement', contact_id: null, status: 'draft' },
    ]);
    apiMocks.listings.mockReset().mockResolvedValue([]);
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

    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledWith({ visibility: 'all' }));
    expect(screen.getByRole('combobox', { name: 'Task status' })).toHaveValue('todo');
    expect(screen.getByRole('combobox', { name: 'Task due scope' })).toHaveValue('past');
    expect(screen.getByText('Past open')).toBeInTheDocument();
    expect(screen.getByText('Past in progress')).toBeInTheDocument();
    expect(screen.queryByText('Future open')).not.toBeInTheDocument();
    expect(screen.queryByText('Past completed')).not.toBeInTheDocument();
    expect(screen.queryByText('Undated open')).not.toBeInTheDocument();
    expect(screen.queryByText('Archived open')).not.toBeInTheDocument();
  });

  it('creates with one caller-owned UUID per explicit task action', async () => {
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledWith({ visibility: 'all' }));

    await user.type(screen.getByPlaceholderText('Add a task'), 'New task');
    await user.click(screen.getByRole('button', { name: 'Add task' }));

    await waitFor(() => expect(apiMocks.createTask).toHaveBeenCalledWith({
      title: 'New task',
      description: '',
      priority: 'normal',
      contact_id: null,
      due_at: null,
    }, expect.stringMatching(UUID_PATTERN), {
      clientTimezone: expect.any(String),
    }));
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);
  });

  it('locks task creation until an uncertain outcome has been authoritatively refreshed', async () => {
    let resolveRefetch!: (value: readonly Task[]) => void;
    const refetch = new Promise<readonly Task[]>((resolve) => {
      resolveRefetch = resolve;
    });
    apiMocks.tasks.mockReset()
      .mockResolvedValueOnce(tasks)
      .mockReturnValueOnce(refetch);
    apiMocks.createTask.mockRejectedValueOnce(outcomeError('uncertain'));
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Past open');

    await user.type(screen.getByPlaceholderText('Add a task'), 'Uncertain task');
    const addTask = screen.getByRole('button', { name: 'Add task' });
    await user.click(addTask);
    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(2));

    expect(addTask).toBeDisabled();
    await user.click(addTask);
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);

    resolveRefetch(tasks);
    await waitFor(() => expect(addTask).toBeEnabled());
  });

  it('reuses the same UUID and canonical payload only for an unchanged explicit create retry', async () => {
    apiMocks.createTask
      .mockRejectedValueOnce(outcomeError('uncertain'))
      .mockResolvedValueOnce({
        ...tasks[0], id: 99, title: 'Uncertain task', priority: 'normal', due_at: null, version: 1,
      });
    apiMocks.tasks.mockReset()
      .mockResolvedValueOnce(tasks)
      .mockResolvedValueOnce(tasks);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Past open');

    await user.type(screen.getByPlaceholderText('Add a task'), 'Uncertain task');
    const addTask = screen.getByRole('button', { name: 'Add task' });
    await user.click(addTask);
    await waitFor(() => expect(addTask).toBeEnabled());
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);
    const [firstPayload, firstKey] = apiMocks.createTask.mock.calls[0]!;

    await user.type(screen.getByPlaceholderText('Add a task'), ' ');
    await user.click(addTask);
    await waitFor(() => expect(apiMocks.createTask).toHaveBeenCalledTimes(2));
    expect(apiMocks.createTask.mock.calls[1]).toEqual([
      firstPayload,
      firstKey,
      apiMocks.createTask.mock.calls[0]?.[2],
    ]);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('allocates a new UUID when any create payload field changes after uncertainty', async () => {
    apiMocks.createTask
      .mockRejectedValueOnce(outcomeError('uncertain'))
      .mockResolvedValueOnce({
        ...tasks[0], id: 100, title: 'Changed intent', priority: 'normal', due_at: null, version: 1,
      });
    apiMocks.tasks.mockReset()
      .mockResolvedValueOnce(tasks)
      .mockResolvedValueOnce(tasks);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Past open');

    const titleInput = screen.getByPlaceholderText('Add a task');
    await user.type(titleInput, 'Original intent');
    await user.click(screen.getByRole('button', { name: 'Add task' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add task' })).toBeEnabled());
    const firstKey = apiMocks.createTask.mock.calls[0]?.[1];

    await user.clear(titleInput);
    await user.type(titleInput, 'Changed intent');
    await user.click(screen.getByRole('button', { name: 'Add task' }));
    await waitFor(() => expect(apiMocks.createTask).toHaveBeenCalledTimes(2));
    expect(apiMocks.createTask.mock.calls[1]?.[1]).not.toBe(firstKey);
  });

  it('uses each authoritative mutation response version for the next update', async () => {
    apiMocks.updateTask
      .mockResolvedValueOnce({ ...tasks[0], status: 'completed', version: 2 })
      .mockResolvedValueOnce({ ...tasks[0], status: 'open', version: 3 });
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Past open');

    await user.click(screen.getByRole('button', { name: 'Toggle Past open' }));
    await waitFor(() => expect(apiMocks.updateTask).toHaveBeenNthCalledWith(1, 1, {
      expected_version: 1,
      status: 'completed',
    }));
    await user.click(screen.getByRole('button', { name: 'Toggle Past open' }));
    await waitFor(() => expect(apiMocks.updateTask).toHaveBeenNthCalledWith(2, 1, {
      expected_version: 2,
      status: 'open',
    }));
  });

  it('propagates task_version from linking into the next task mutation', async () => {
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Past open');

    await user.click(screen.getAllByRole('button', { name: 'Link record' })[0]!);
    await user.selectOptions(screen.getByRole('combobox', { name: 'Internal record type' }), 'agreement');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Internal record to link' }), '19');
    await user.click(screen.getByRole('button', { name: 'Link' }));

    await waitFor(() => expect(apiMocks.addTaskLink).toHaveBeenCalledWith(1, {
      expected_version: 1,
      entity_type: 'agreement',
      entity_id: 19,
    }));
    await user.click(screen.getByRole('button', { name: 'Toggle Past open' }));
    await waitFor(() => expect(apiMocks.updateTask).toHaveBeenCalledWith(1, {
      expected_version: 2,
      status: 'completed',
    }));
  });

  it.each(['uncertain', 'conflict'] as const)(
    'refetches all tasks after an %s mutation outcome without retrying it',
    async (kind) => {
      apiMocks.updateTask.mockRejectedValueOnce(outcomeError(kind));
      const user = userEvent.setup();
      render(<TasksWorkspace />);
      await screen.findByText('Past open');

      await user.click(screen.getByRole('button', { name: 'Toggle Past open' }));

      await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(2));
      expect(apiMocks.tasks).toHaveBeenLastCalledWith({ visibility: 'all' });
      expect(apiMocks.updateTask).toHaveBeenCalledTimes(1);
    },
  );

  it.each(['uncertain', 'conflict'] as const)(
    'locks every task write during %s editor reconciliation and closes the stale editor',
    async (kind) => {
      const refresh = deferred<readonly Task[]>();
      const authoritativeTask = {
        ...tasks[0]!,
        title: 'Server-owned concurrent title',
        description: 'Server-owned concurrent description',
        priority: 'low' as const,
        due_at: null,
        version: 8,
      };
      apiMocks.tasks.mockReset()
        .mockResolvedValueOnce(tasks)
        .mockReturnValueOnce(refresh.promise);
      apiMocks.updateTask.mockRejectedValueOnce(outcomeError(kind));
      const user = userEvent.setup();
      render(<TasksWorkspace />);
      await screen.findByText('Past open');

      await user.click(screen.getAllByRole('button', { name: 'Edit' })[0]!);
      const titleInput = screen.getByRole('textbox', { name: 'Task title' });
      await user.clear(titleInput);
      await user.type(titleInput, 'Fresh edit');
      const save = screen.getByRole('button', { name: 'Save task' });
      await user.click(save);

      await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(2));
      expect(save).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Add task' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Toggle Past open' })).toBeDisabled();
      expect(screen.getByRole('combobox', { name: 'Assign Past open contact' })).toBeDisabled();
      expect(screen.getAllByRole('button', { name: 'Edit' })[0]).toBeDisabled();
      expect(screen.getAllByRole('button', { name: 'Link record' })[0]).toBeDisabled();
      expect(apiMocks.updateTask).toHaveBeenCalledTimes(1);

      await act(async () => refresh.resolve([
        authoritativeTask,
        ...tasks.slice(1),
      ]));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Edit task' })).not.toBeInTheDocument());
      expect(apiMocks.updateTask).toHaveBeenCalledTimes(1);
    },
  );

  it.each(['uncertain', 'conflict'] as const)(
    'locks every task write while a %s link outcome is authoritatively reconciled without retry',
    async (kind) => {
      const refresh = deferred<readonly Task[]>();
      apiMocks.tasks.mockReset()
        .mockResolvedValueOnce(tasks)
        .mockReturnValueOnce(refresh.promise);
      apiMocks.addTaskLink.mockRejectedValueOnce(outcomeError(kind));
      const user = userEvent.setup();
      render(<TasksWorkspace />);
      await screen.findByText('Past open');

      await user.click(screen.getAllByRole('button', { name: 'Link record' })[0]!);
      await user.selectOptions(screen.getByRole('combobox', { name: 'Internal record type' }), 'agreement');
      await user.selectOptions(screen.getByRole('combobox', { name: 'Internal record to link' }), '19');
      const linkButton = screen.getByRole('button', { name: 'Link' });
      await user.click(linkButton);

      await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(2));
      expect(linkButton).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Add task' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Toggle Past open' })).toBeDisabled();
      expect(screen.getByRole('combobox', { name: 'Assign Past open contact' })).toBeDisabled();
      expect(screen.getAllByRole('button', { name: 'Edit' })[0]).toBeDisabled();
      expect(screen.getAllByRole('button', { name: 'Link record' })[0]).toBeDisabled();
      expect(apiMocks.addTaskLink).toHaveBeenCalledTimes(1);

      await act(async () => refresh.resolve([
        { ...tasks[0]!, version: 8 },
        ...tasks.slice(1),
      ]));
      await waitFor(() => expect(screen.queryByRole('heading', { name: 'Link internal record' })).not.toBeInTheDocument());
      expect(apiMocks.addTaskLink).toHaveBeenCalledTimes(1);
    },
  );

  it('keeps every task write locked when authoritative mutation reconciliation fails', async () => {
    apiMocks.tasks.mockReset()
      .mockResolvedValueOnce(tasks)
      .mockRejectedValueOnce(new Error('Synthetic authoritative refresh failure'));
    apiMocks.updateTask.mockRejectedValueOnce(outcomeError('uncertain'));
    apiMocks.taskLinks.mockRejectedValueOnce(new Error('Synthetic link read failure'));
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Past open');

    const toggle = screen.getByRole('button', { name: 'Toggle Past open' });
    await user.click(toggle);

    const refreshRequired = await screen.findByText(
      'Task state could not be refreshed. Refresh the page before making another task change.',
    );
    expect(refreshRequired.closest('[role="alert"]')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Add task' })).toBeDisabled();
    expect(toggle).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'Assign Past open contact' })).toBeDisabled();
    expect(screen.getAllByRole('button', { name: 'Edit' })[0]).toBeDisabled();
    expect(screen.getAllByRole('button', { name: 'Link record' })[0]).toBeDisabled();

    await user.click(toggle);
    await user.click(screen.getByRole('button', { name: 'Add task' }));
    await user.click(screen.getAllByRole('button', { name: 'Show links' })[0]!);
    expect(await screen.findByText(
      'Task state could not be refreshed. Refresh the page before making another task change.',
    )).toBeInTheDocument();
    expect(apiMocks.updateTask).toHaveBeenCalledTimes(1);
    expect(apiMocks.createTask).not.toHaveBeenCalled();
    expect(apiMocks.tasks).toHaveBeenCalledTimes(2);
  });

  it('ignores an initial task read that settles after a confirmed create mutation', async () => {
    const staleInitial = deferred<readonly Task[]>();
    apiMocks.tasks.mockReset().mockReturnValueOnce(staleInitial.promise);
    apiMocks.createTask.mockResolvedValueOnce({
      ...tasks[0], id: 99, title: 'Created while loading', priority: 'normal', due_at: null, version: 1,
    });
    const user = userEvent.setup();
    render(<TasksWorkspace />);

    await user.type(screen.getByPlaceholderText('Add a task'), 'Created while loading');
    await user.click(screen.getByRole('button', { name: 'Add task' }));
    expect(await screen.findByText('Created while loading')).toBeInTheDocument();

    await act(async () => staleInitial.resolve(tasks));
    expect(screen.getByText('Created while loading')).toBeInTheDocument();
  });

  it('ignores a stale initial task-read failure after a newer confirmed mutation', async () => {
    const staleInitial = deferred<readonly Task[]>();
    apiMocks.tasks.mockReset().mockReturnValueOnce(staleInitial.promise);
    apiMocks.createTask.mockResolvedValueOnce({
      ...tasks[0], id: 99, title: 'Newest task', priority: 'normal', due_at: null, version: 1,
    });
    const user = userEvent.setup();
    render(<TasksWorkspace />);

    await user.type(screen.getByPlaceholderText('Add a task'), 'Newest task');
    await user.click(screen.getByRole('button', { name: 'Add task' }));
    expect(await screen.findByText('Newest task')).toBeInTheDocument();

    await act(async () => staleInitial.reject(new Error('Stale tasks read failed')));
    expect(screen.queryByText('Stale tasks read failed')).not.toBeInTheDocument();
  });

  it('keeps the newest task-link read when an older request settles last', async () => {
    const oldLinks = deferred<readonly commandApiModule.TaskLink[]>();
    const freshLink = {
      id: 20, task_id: 1, entity_type: 'agreement', entity_id: 19,
      display_name: 'Fresh buyer agreement', task_version: 2,
    };
    apiMocks.taskLinks.mockReset()
      .mockReturnValueOnce(oldLinks.promise)
      .mockResolvedValueOnce([freshLink]);
    apiMocks.addTaskLink.mockResolvedValueOnce(freshLink);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Past open');

    await user.click(screen.getAllByRole('button', { name: 'Show links' })[0]!);
    await user.click(screen.getAllByRole('button', { name: 'Link record' })[0]!);
    await user.selectOptions(screen.getByRole('combobox', { name: 'Internal record type' }), 'agreement');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Internal record to link' }), '19');
    await user.click(screen.getByRole('button', { name: 'Link' }));

    expect(await screen.findByText(/Fresh buyer agreement/)).toBeInTheDocument();
    await act(async () => oldLinks.resolve([{ ...freshLink, id: 21, display_name: 'Stale agreement' }]));
    expect(screen.getByText(/Fresh buyer agreement/)).toBeInTheDocument();
    expect(screen.queryByText(/Stale agreement/)).not.toBeInTheDocument();
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
