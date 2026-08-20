import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  CommandConflictError,
  CommandOutcomeUncertainError,
  type Task,
} from '@/lib/command/api';
import { TasksWorkspace } from './TasksWorkspace';

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
  archiveTask: vi.fn(),
  restoreTask: vi.fn(),
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
      archiveTask: apiMocks.archiveTask,
      restoreTask: apiMocks.restoreTask,
    },
  };
});

const activeTask: Task = {
  id: 7,
  title: 'Call Jane',
  contact_id: null,
  description: 'Confirm the inspection window',
  priority: 'high',
  due_at: '2026-08-21T14:00:00.000Z',
  status: 'open',
  archived_at: null,
  archive_reason: null,
  version: 3,
};

const completedTask: Task = {
  ...activeTask,
  id: 8,
  title: 'Send market report',
  description: '',
  priority: 'normal',
  due_at: null,
  status: 'completed',
  version: 1,
};

const archivedTask: Task = {
  ...activeTask,
  archived_at: '2026-08-20T16:00:00.000Z',
  archive_reason: 'No longer actionable',
  version: 4,
};

const fixtureTasks: readonly Task[] = [activeTask, completedTask, {
  ...archivedTask,
  id: 9,
  title: 'Superseded follow-up',
  version: 2,
}];

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function deferred<Value>() {
  let resolve!: (value: Value) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<Value>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

async function renderWorkspace(rows: readonly Task[] = fixtureTasks) {
  apiMocks.tasks.mockResolvedValueOnce(rows);
  const user = userEvent.setup();
  render(<TasksWorkspace />);
  await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledWith({ visibility: 'all' }));
  const initiallyVisible = rows.find((task) => task.archived_at === null);
  if (initiallyVisible !== undefined) await screen.findByText(initiallyVisible.title);
  return user;
}

async function openArchiveDialog(user: ReturnType<typeof userEvent.setup>, title = activeTask.title) {
  const trigger = screen.getByRole('button', { name: `Task actions for ${title}` });
  await user.click(trigger);
  await user.click(screen.getByRole('menuitem', { name: 'Archive task' }));
  return {
    trigger,
    dialog: screen.getByRole('dialog', { name: `Archive ${title}` }),
  };
}

describe('TasksWorkspace archive lifecycle', () => {
  beforeEach(() => {
    apiMocks.contacts.mockReset().mockResolvedValue([]);
    apiMocks.tasks.mockReset();
    apiMocks.createTask.mockReset();
    apiMocks.updateTask.mockReset();
    apiMocks.addTaskLink.mockReset();
    apiMocks.taskLinks.mockReset().mockResolvedValue([]);
    apiMocks.opportunities.mockReset().mockResolvedValue([]);
    apiMocks.agreements.mockReset().mockResolvedValue([]);
    apiMocks.listings.mockReset().mockResolvedValue([]);
    apiMocks.archiveTask.mockReset().mockResolvedValue(archivedTask);
    apiMocks.restoreTask.mockReset().mockResolvedValue(activeTask);
  });

  it('switches between filtered active tasks and archived tasks without dropping either collection', async () => {
    const user = await renderWorkspace();

    expect(apiMocks.tasks).toHaveBeenCalledWith({ visibility: 'all' });
    expect(screen.getByRole('button', { name: 'Active' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Call Jane')).toBeInTheDocument();
    expect(screen.getByText('Send market report')).toBeInTheDocument();
    expect(screen.queryByText('Superseded follow-up')).not.toBeInTheDocument();

    await user.selectOptions(screen.getByRole('combobox', { name: 'Task status' }), 'completed');
    expect(screen.queryByText('Call Jane')).not.toBeInTheDocument();
    expect(screen.getByText('Send market report')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Archived' }));
    expect(screen.getByRole('button', { name: 'Archived' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Superseded follow-up')).toBeInTheDocument();
    expect(screen.getByText('No longer actionable')).toBeInTheDocument();
    const archivedRow = screen.getByRole('article', { name: 'Task Superseded follow-up' });
    expect(within(archivedRow).getByText(/^Archived /)).toHaveAttribute(
      'dateTime',
      '2026-08-20T16:00:00.000Z',
    );
    expect(screen.queryByText('Call Jane')).not.toBeInTheDocument();
    expect(screen.queryByText('Send market report')).not.toBeInTheDocument();
  });

  it('removes every mutation, assignment, edit, and link affordance from archived rows', async () => {
    const user = await renderWorkspace();
    await user.click(screen.getByRole('button', { name: 'Archived' }));

    const row = screen.getByRole('article', { name: 'Task Superseded follow-up' });
    const restore = within(row).getByRole('button', { name: 'Restore Superseded follow-up' });
    expect(restore).toHaveClass(
      'command-touch-target',
    );
    expect(within(row).queryByRole('button', { name: /toggle/i })).not.toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: /edit/i })).not.toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: /link record/i })).not.toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: /show links/i })).not.toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: /task actions/i })).not.toBeInTheDocument();
    expect(within(row).queryByRole('combobox', { name: /assign/i })).not.toBeInTheDocument();
    expect(within(row).queryByRole('textbox')).not.toBeInTheDocument();
    expect(Array.from(row.querySelectorAll('button,input,select,textarea,a[href]'))).toEqual([restore]);
  });

  it('implements a named menu with first-item focus, arrow navigation, Escape, and focus return', async () => {
    const user = await renderWorkspace();
    const trigger = screen.getByRole('button', { name: 'Task actions for Call Jane' });

    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    trigger.focus();
    await user.keyboard('{ArrowDown}');

    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const menu = screen.getByRole('menu', { name: 'Task actions for Call Jane' });
    const archive = within(menu).getByRole('menuitem', { name: 'Archive task' });
    expect(archive).toHaveFocus();
    expect(archive).toHaveClass('command-touch-target');

    await user.keyboard('{ArrowDown}');
    expect(archive).toHaveFocus();
    await user.keyboard('{ArrowUp}');
    expect(archive).toHaveFocus();
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveFocus();

    await user.keyboard('{Enter}');
    expect(archive).not.toBeInTheDocument();
    const keyboardArchive = screen.getByRole('menuitem', { name: 'Archive task' });
    expect(keyboardArchive).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('dialog', { name: 'Archive Call Jane' })).toBeInTheDocument();
  });

  it('opens a heading-named portal dialog, traps focus, and returns focus on Escape', async () => {
    const user = await renderWorkspace();
    const { trigger, dialog } = await openArchiveDialog(user);

    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(document.body.contains(dialog)).toBe(true);
    expect(screen.getByRole('main').contains(dialog)).toBe(false);
    expect(screen.getByRole('heading', { name: 'Archive Call Jane' })).toBeInTheDocument();
    const reason = screen.getByRole('textbox', { name: 'Archive reason (optional)' });
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    const archive = screen.getByRole('button', { name: 'Archive' });
    expect(reason).toHaveClass('focus-visible:outline');
    expect(cancel).toHaveClass('focus-visible:outline');
    expect(archive).toHaveClass('focus-visible:outline');
    expect(reason).toHaveFocus();

    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(archive).toHaveFocus();
    await user.tab();
    expect(reason).toHaveFocus();
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog', { name: 'Archive Call Jane' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('keeps an active task in place until archive ACK and guards rapid duplicate activation', async () => {
    const archive = deferred<Task>();
    apiMocks.archiveTask.mockReturnValueOnce(archive.promise);
    const user = await renderWorkspace([activeTask]);
    const { dialog } = await openArchiveDialog(user);
    await user.type(screen.getByRole('textbox', { name: 'Archive reason (optional)' }), '  Duplicate  ');
    const confirm = within(dialog).getByRole('button', { name: 'Archive' });

    await user.dblClick(confirm);
    await user.keyboard('{Enter}');

    expect(apiMocks.archiveTask).toHaveBeenCalledTimes(1);
    expect(apiMocks.archiveTask).toHaveBeenCalledWith(7, {
      request_id: expect.stringMatching(UUID_PATTERN),
      expected_version: 3,
      reason: 'Duplicate',
    });
    expect(screen.getByText('Call Jane')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();

    await act(async () => archive.resolve({ ...archivedTask, archive_reason: 'Duplicate' }));

    await waitFor(() => expect(screen.queryByText('Call Jane')).not.toBeInTheDocument());
    const undo = screen.getByRole('button', { name: 'Undo' });
    expect(undo).toHaveFocus();
    expect(undo).toHaveClass('command-touch-target');
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
    await user.click(screen.getByRole('button', { name: 'Archived' }));
    expect(screen.getByText('Call Jane')).toBeInTheDocument();
    expect(screen.getByText('Duplicate')).toBeInTheDocument();
  });

  it('keeps an archived task in place until direct restore ACK and then focuses a live visibility control', async () => {
    const restore = deferred<Task>();
    apiMocks.restoreTask.mockReturnValueOnce(restore.promise);
    const user = await renderWorkspace([archivedTask]);
    expect(screen.queryByText('Call Jane')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Archived' }));
    const restoreButton = screen.getByRole('button', { name: 'Restore Call Jane' });

    await user.dblClick(restoreButton);

    expect(apiMocks.restoreTask).toHaveBeenCalledTimes(1);
    expect(apiMocks.restoreTask).toHaveBeenCalledWith(7, {
      request_id: expect.stringMatching(UUID_PATTERN),
      expected_version: 4,
    });
    expect(screen.getByText('Call Jane')).toBeInTheDocument();

    await act(async () => restore.resolve({ ...activeTask, version: 5 }));

    await waitFor(() => expect(screen.queryByText('Call Jane')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Archived' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'Active' }));
    expect(screen.getByText('Call Jane')).toBeInTheDocument();
  });

  it('implements Undo as a new Restore request using the archived ACK version', async () => {
    const restore = deferred<Task>();
    apiMocks.restoreTask.mockReturnValueOnce(restore.promise);
    const user = await renderWorkspace([activeTask]);
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    const archiveRequest = apiMocks.archiveTask.mock.calls[0]?.[1];
    const undo = await screen.findByRole('button', { name: 'Undo' });
    await user.click(undo);

    expect(apiMocks.restoreTask).toHaveBeenCalledTimes(1);
    expect(apiMocks.restoreTask).toHaveBeenCalledWith(7, {
      request_id: expect.stringMatching(UUID_PATTERN),
      expected_version: 4,
    });
    expect(apiMocks.restoreTask.mock.calls[0]?.[1].request_id).not.toBe(archiveRequest.request_id);
    expect(screen.queryByText('Call Jane')).not.toBeInTheDocument();

    await act(async () => restore.resolve({ ...activeTask, version: 5 }));
    expect(await screen.findByText('Call Jane')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Active' })).toHaveFocus();
  });

  it('uses an exact same-version archive ACK for Undo and guards duplicate Undo activation', async () => {
    const sameVersionArchive = { ...archivedTask, version: activeTask.version };
    const restore = deferred<Task>();
    apiMocks.archiveTask.mockResolvedValueOnce(sameVersionArchive);
    apiMocks.restoreTask.mockReturnValueOnce(restore.promise);
    const user = await renderWorkspace([activeTask]);
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    const archiveRequest = apiMocks.archiveTask.mock.calls[0]?.[1];
    const undo = await screen.findByRole('button', { name: 'Undo' });
    await user.dblClick(undo);

    expect(apiMocks.restoreTask).toHaveBeenCalledTimes(1);
    expect(apiMocks.restoreTask).toHaveBeenCalledWith(7, {
      request_id: expect.stringMatching(UUID_PATTERN),
      expected_version: 3,
    });
    expect(apiMocks.restoreTask.mock.calls[0]?.[1].request_id).not.toBe(archiveRequest.request_id);

    await act(async () => restore.resolve({ ...activeTask, version: 4 }));
    expect(await screen.findByText('Call Jane')).toBeInTheDocument();
  });

  it('offers same-request retry only when uncertainty refetches the exact original task', async () => {
    apiMocks.archiveTask
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockResolvedValueOnce(archivedTask);
    apiMocks.tasks
      .mockResolvedValueOnce([activeTask])
      .mockResolvedValueOnce([activeTask])
      .mockResolvedValueOnce([archivedTask]);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Call Jane');
    await openArchiveDialog(user);
    await user.type(screen.getByRole('textbox', { name: 'Archive reason (optional)' }), 'Customer requested cleanup');
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    const retry = await screen.findByRole('button', { name: 'Retry' });
    expect(retry).toHaveClass('command-touch-target');
    const originalRequest = { ...apiMocks.archiveTask.mock.calls[0]?.[1] };
    expect(originalRequest.reason).toBe('Customer requested cleanup');
    expect(apiMocks.tasks).toHaveBeenCalledTimes(2);
    expect(apiMocks.archiveTask).toHaveBeenCalledTimes(1);
    await user.click(retry);

    await waitFor(() => expect(apiMocks.archiveTask).toHaveBeenCalledTimes(2));
    expect(apiMocks.archiveTask.mock.calls[1]?.[1]).toStrictEqual(originalRequest);
    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(3));
    expect(screen.getByRole('button', { name: 'Undo' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'Archived' }));
    expect(screen.getByText('Call Jane')).toBeInTheDocument();
  });

  it('guards rapid duplicate activation of an explicit lifecycle Retry', async () => {
    const retryAck = deferred<Task>();
    apiMocks.archiveTask
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockReturnValueOnce(retryAck.promise);
    apiMocks.tasks
      .mockResolvedValueOnce([activeTask])
      .mockResolvedValueOnce([activeTask])
      .mockResolvedValueOnce([archivedTask]);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Call Jane');
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));
    const retry = await screen.findByRole('button', { name: 'Retry' });

    await user.dblClick(retry);

    expect(apiMocks.archiveTask).toHaveBeenCalledTimes(2);
    await act(async () => retryAck.resolve(archivedTask));
    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(3));
  });

  it('adopts an already-applied archive after uncertainty without exposing Retry', async () => {
    apiMocks.archiveTask.mockRejectedValueOnce(
      new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')),
    );
    apiMocks.tasks
      .mockResolvedValueOnce([activeTask])
      .mockResolvedValueOnce([archivedTask]);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Call Jane');
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    expect(await screen.findByText(/Archive confirmed after refreshing/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.queryByText('Call Jane')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Undo' })).toHaveFocus();
    expect(apiMocks.archiveTask).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
  });

  it('rejects a same-version desired Archive state as non-authoritative after uncertainty', async () => {
    const impossibleSameVersionArchive = { ...archivedTask, version: activeTask.version };
    apiMocks.archiveTask.mockRejectedValueOnce(
      new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')),
    );
    apiMocks.tasks
      .mockResolvedValueOnce([activeTask])
      .mockResolvedValueOnce([impossibleSameVersionArchive]);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Call Jane');
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/start a fresh action/i);
    expect(screen.queryByText(/Archive confirmed after refreshing/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Active' })).toHaveFocus();
    expect(apiMocks.archiveTask).toHaveBeenCalledTimes(1);
  });

  it('reconciles uncertain Restore and reuses its exact request for explicit retry', async () => {
    apiMocks.restoreTask
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockResolvedValueOnce({ ...activeTask, version: 5 });
    apiMocks.tasks
      .mockResolvedValueOnce([archivedTask])
      .mockResolvedValueOnce([archivedTask])
      .mockResolvedValueOnce([{ ...activeTask, version: 5 }]);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledWith({ visibility: 'all' }));
    expect(screen.queryByText('Call Jane')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Archived' }));
    await user.click(screen.getByRole('button', { name: 'Restore Call Jane' }));

    const retry = await screen.findByRole('button', { name: 'Retry' });
    const originalRequest = { ...apiMocks.restoreTask.mock.calls[0]?.[1] };
    await user.click(retry);

    await waitFor(() => expect(apiMocks.restoreTask).toHaveBeenCalledTimes(2));
    expect(apiMocks.restoreTask.mock.calls[1]?.[1]).toStrictEqual(originalRequest);
    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(3));
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.queryByText('Call Jane')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Archived' })).toHaveFocus();
  });

  it('adopts an already-applied Restore after uncertainty without exposing Retry', async () => {
    const restored = { ...activeTask, version: 5 };
    apiMocks.restoreTask.mockRejectedValueOnce(
      new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')),
    );
    apiMocks.tasks
      .mockResolvedValueOnce([archivedTask])
      .mockResolvedValueOnce([restored]);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(1));
    expect(screen.queryByText('Call Jane')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Archived' }));
    await user.click(await screen.findByRole('button', { name: 'Restore Call Jane' }));

    expect(await screen.findByText(/Restore confirmed after refreshing/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.queryByText('Call Jane')).not.toBeInTheDocument();
    expect(apiMocks.restoreTask).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Archived' })).toHaveFocus();
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
  });

  it('rejects a same-version desired Restore state as non-authoritative after uncertainty', async () => {
    const impossibleSameVersionRestore = { ...activeTask, version: archivedTask.version };
    apiMocks.restoreTask.mockRejectedValueOnce(
      new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')),
    );
    apiMocks.tasks
      .mockResolvedValueOnce([archivedTask])
      .mockResolvedValueOnce([impossibleSameVersionRestore]);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: 'Archived' }));
    await user.click(await screen.findByRole('button', { name: 'Restore Call Jane' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/start a fresh action/i);
    expect(screen.queryByText(/Restore confirmed after refreshing/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Archived' })).toHaveFocus();
    expect(apiMocks.restoreTask).toHaveBeenCalledTimes(1);
  });

  it('discards uncertain Restore retry identity when the archived task changed differently', async () => {
    const changedArchive = {
      ...archivedTask,
      description: 'Changed while Restore was in flight',
      version: 5,
    };
    apiMocks.restoreTask
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockResolvedValueOnce({ ...activeTask, version: 6 });
    apiMocks.tasks
      .mockResolvedValueOnce([archivedTask])
      .mockResolvedValueOnce([changedArchive]);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: 'Archived' }));
    await user.click(await screen.findByRole('button', { name: 'Restore Call Jane' }));

    const firstRequest = { ...apiMocks.restoreTask.mock.calls[0]?.[1] };
    expect(await screen.findByText('Changed while Restore was in flight')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/changed.*review.*fresh action/i);
    await user.click(screen.getByRole('button', { name: 'Restore Call Jane' }));
    await waitFor(() => expect(apiMocks.restoreTask).toHaveBeenCalledTimes(2));
    expect(apiMocks.restoreTask.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      expected_version: 5,
      request_id: expect.stringMatching(UUID_PATTERN),
    }));
    expect(apiMocks.restoreTask.mock.calls[1]?.[1].request_id).not.toBe(firstRequest.request_id);
  });

  it('adopts a Restore conflict and requires a fresh Restore UUID with its authoritative version', async () => {
    const refreshedArchive = { ...archivedTask, archive_reason: 'Reviewed elsewhere', version: 8 };
    apiMocks.restoreTask
      .mockRejectedValueOnce(new CommandConflictError({
        code: 'task_version_conflict',
        current_version: 8,
        current_task: refreshedArchive,
      }))
      .mockResolvedValueOnce({ ...activeTask, version: 9 });
    const user = await renderWorkspace([archivedTask]);
    await user.click(screen.getByRole('button', { name: 'Archived' }));
    await user.click(screen.getByRole('button', { name: 'Restore Call Jane' }));

    expect(await screen.findByText('Reviewed elsewhere')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/changed elsewhere.*review.*fresh action/i);
    const firstRequest = apiMocks.restoreTask.mock.calls[0]?.[1];
    await user.click(screen.getByRole('button', { name: 'Restore Call Jane' }));

    await waitFor(() => expect(apiMocks.restoreTask).toHaveBeenCalledTimes(2));
    expect(apiMocks.restoreTask.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      request_id: expect.stringMatching(UUID_PATTERN),
      expected_version: 8,
    }));
    expect(apiMocks.restoreTask.mock.calls[1]?.[1].request_id).not.toBe(firstRequest.request_id);
  });

  it('keeps Restore and every active-row write locked when Restore reconciliation fails', async () => {
    apiMocks.restoreTask.mockRejectedValueOnce(
      new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')),
    );
    const activePeer = { ...activeTask, id: 10, title: 'Active peer' };
    apiMocks.tasks
      .mockResolvedValueOnce([activePeer, archivedTask])
      .mockRejectedValueOnce(new Error('Synthetic refresh failure'));
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Active peer');
    expect(screen.queryByText('Call Jane')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Archived' }));
    const restore = screen.getByRole('button', { name: 'Restore Call Jane' });
    await user.click(restore);

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be refreshed/i);
    expect(restore).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    const refresh = screen.getByRole('button', { name: 'Refresh tasks' });
    expect(refresh).toBeEnabled();
    expect(refresh).toHaveClass('command-touch-target');
    await user.click(screen.getByRole('button', { name: 'Active' }));
    expect(screen.getByRole('button', { name: 'Add task' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Toggle Active peer' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Edit' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Link record' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Task actions for Active peer' })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'Assign Active peer contact' })).toBeDisabled();
    expect(apiMocks.restoreTask).toHaveBeenCalledTimes(1);
  });

  it('discards a stale conflict, adopts its authoritative task, and requires a fresh UUID/version', async () => {
    const refreshed = { ...activeTask, title: 'Call Jane after review', version: 8 };
    apiMocks.archiveTask
      .mockRejectedValueOnce(new CommandConflictError({
        code: 'task_version_conflict',
        current_version: 8,
        current_task: refreshed,
      }))
      .mockResolvedValueOnce({ ...refreshed, archived_at: archivedTask.archived_at, version: 9 });
    const user = await renderWorkspace([activeTask]);
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    expect(await screen.findByText('Call Jane after review')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/changed elsewhere.*review.*fresh action/i);
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    const firstRequest = apiMocks.archiveTask.mock.calls[0]?.[1];

    await openArchiveDialog(user, 'Call Jane after review');
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    await waitFor(() => expect(apiMocks.archiveTask).toHaveBeenCalledTimes(2));
    expect(apiMocks.archiveTask.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      request_id: expect.stringMatching(UUID_PATTERN),
      expected_version: 8,
    }));
    expect(apiMocks.archiveTask.mock.calls[1]?.[1].request_id).not.toBe(firstRequest.request_id);
  });

  it('discards uncertain Archive retry identity after a different change and uses a fresh UUID/version', async () => {
    const changedActive = {
      ...activeTask,
      description: 'Changed while Archive was in flight',
      version: 5,
    };
    apiMocks.archiveTask
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockResolvedValueOnce({ ...archivedTask, description: changedActive.description, version: 6 });
    apiMocks.tasks
      .mockResolvedValueOnce([activeTask])
      .mockResolvedValueOnce([changedActive]);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Call Jane');
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    const firstRequest = { ...apiMocks.archiveTask.mock.calls[0]?.[1] };
    expect(await screen.findByText('Changed while Archive was in flight')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    await waitFor(() => expect(apiMocks.archiveTask).toHaveBeenCalledTimes(2));
    expect(apiMocks.archiveTask.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      expected_version: 5,
      request_id: expect.stringMatching(UUID_PATTERN),
    }));
    expect(apiMocks.archiveTask.mock.calls[1]?.[1].request_id).not.toBe(firstRequest.request_id);
  });

  it('keeps every task write locked and offers authoritative refresh when uncertainty reconciliation fails', async () => {
    apiMocks.archiveTask.mockRejectedValueOnce(
      new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')),
    );
    apiMocks.tasks
      .mockResolvedValueOnce([activeTask])
      .mockRejectedValueOnce(new Error('Synthetic refresh failure'));
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Call Jane');
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be refreshed/i);
    expect(screen.getByRole('button', { name: 'Add task' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Toggle Call Jane' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Task actions for Call Jane' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    const refresh = screen.getByRole('button', { name: 'Refresh tasks' });
    expect(refresh).toBeEnabled();
    expect(refresh).toHaveClass('command-touch-target');
    expect(refresh).toHaveFocus();
    expect(apiMocks.archiveTask).toHaveBeenCalledTimes(1);

    apiMocks.tasks.mockResolvedValueOnce([activeTask]);
    await user.click(refresh);

    const retry = await screen.findByRole('button', { name: 'Retry' });
    await waitFor(() => expect(retry).toHaveFocus());
    expect(apiMocks.archiveTask).toHaveBeenCalledTimes(1);
  });

  it('moves focus from Refresh tasks to Retry when authoritative refresh finds the unchanged task', async () => {
    apiMocks.archiveTask.mockRejectedValueOnce(
      new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')),
    );
    apiMocks.tasks
      .mockResolvedValueOnce([activeTask])
      .mockRejectedValueOnce(new Error('Synthetic refresh failure'))
      .mockResolvedValueOnce([activeTask]);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Call Jane');
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    const refresh = await screen.findByRole('button', { name: 'Refresh tasks' });
    refresh.focus();
    expect(refresh).toHaveFocus();
    await user.click(refresh);

    const retry = await screen.findByRole('button', { name: 'Retry' });
    expect(retry).toHaveFocus();
    expect(screen.queryByRole('button', { name: 'Refresh tasks' })).not.toBeInTheDocument();
    expect(apiMocks.archiveTask).toHaveBeenCalledTimes(1);
  });

  it('moves focus from Retry to Refresh tasks when retry reconciliation fails', async () => {
    apiMocks.archiveTask
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic retry disconnect')));
    apiMocks.tasks
      .mockResolvedValueOnce([activeTask])
      .mockResolvedValueOnce([activeTask])
      .mockRejectedValueOnce(new Error('Synthetic retry refresh failure'));
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Call Jane');
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    const retry = await screen.findByRole('button', { name: 'Retry' });
    retry.focus();
    expect(retry).toHaveFocus();
    await user.click(retry);

    const refresh = await screen.findByRole('button', { name: 'Refresh tasks' });
    expect(refresh).toHaveFocus();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(apiMocks.archiveTask).toHaveBeenCalledTimes(2);
  });

  it('focuses the visibility fallback when authoritative refresh finds a differently changed task', async () => {
    const changedActive = {
      ...activeTask,
      description: 'Changed during failed reconciliation',
      version: 5,
    };
    apiMocks.archiveTask.mockRejectedValueOnce(
      new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')),
    );
    apiMocks.tasks
      .mockResolvedValueOnce([activeTask])
      .mockRejectedValueOnce(new Error('Synthetic refresh failure'))
      .mockResolvedValueOnce([changedActive]);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Call Jane');
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    await user.click(await screen.findByRole('button', { name: 'Refresh tasks' }));

    expect(await screen.findByText('Changed during failed reconciliation')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Active' })).toHaveFocus();
  });

  it('focuses Undo when authoritative refresh confirms the archive was applied', async () => {
    apiMocks.archiveTask.mockRejectedValueOnce(
      new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')),
    );
    apiMocks.tasks
      .mockResolvedValueOnce([activeTask])
      .mockRejectedValueOnce(new Error('Synthetic refresh failure'))
      .mockResolvedValueOnce([archivedTask]);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Call Jane');
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));

    await user.click(await screen.findByRole('button', { name: 'Refresh tasks' }));

    expect(await screen.findByText(/Archive confirmed after refreshing/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Undo' })).toHaveFocus();
  });

  it('never briefly installs a historical Archive retry ACK while authoritative reconciliation is pending', async () => {
    const retryAck = deferred<Task>();
    const authoritativeRefresh = deferred<readonly Task[]>();
    const newerTask = {
      ...activeTask,
      title: 'Call Jane with revised terms',
      description: 'A later server-side change',
      version: 6,
    };
    apiMocks.archiveTask
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockReturnValueOnce(retryAck.promise);
    apiMocks.tasks
      .mockResolvedValueOnce([activeTask])
      .mockResolvedValueOnce([activeTask])
      .mockReturnValueOnce(authoritativeRefresh.promise);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await screen.findByText('Call Jane');
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));
    await user.click(await screen.findByRole('button', { name: 'Retry' }));

    expect(screen.getByText('Call Jane')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
    await act(async () => retryAck.resolve(archivedTask));
    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(3));
    expect(screen.getByText('Call Jane')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();

    await act(async () => authoritativeRefresh.resolve([newerTask]));
    expect(await screen.findByText('Call Jane with revised terms')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/changed again.*review/i);
    expect(screen.getByRole('button', { name: 'Active' })).toHaveFocus();
  });

  it('never briefly installs a historical Restore retry ACK over a newer archived task', async () => {
    const retryAck = deferred<Task>();
    const authoritativeRefresh = deferred<readonly Task[]>();
    const newerArchive = {
      ...archivedTask,
      archive_reason: 'Still archived after later review',
      version: 6,
    };
    apiMocks.restoreTask
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockReturnValueOnce(retryAck.promise);
    apiMocks.tasks
      .mockResolvedValueOnce([archivedTask])
      .mockResolvedValueOnce([archivedTask])
      .mockReturnValueOnce(authoritativeRefresh.promise);
    const user = userEvent.setup();
    render(<TasksWorkspace />);
    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: 'Archived' }));
    await user.click(await screen.findByRole('button', { name: 'Restore Call Jane' }));
    await user.click(await screen.findByRole('button', { name: 'Retry' }));

    expect(screen.getByText('Call Jane')).toBeInTheDocument();
    await act(async () => retryAck.resolve({ ...activeTask, version: 5 }));
    await waitFor(() => expect(apiMocks.tasks).toHaveBeenCalledTimes(3));
    expect(screen.getByText('Call Jane')).toBeInTheDocument();

    await act(async () => authoritativeRefresh.resolve([newerArchive]));
    expect(await screen.findByText('Still archived after later review')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/changed again.*review/i);
    expect(screen.getByRole('button', { name: 'Archived' })).toHaveFocus();
  });

  it('carries restored ACK and PATCH versions through the next existing link mutation', async () => {
    const highVersionArchive = { ...archivedTask, version: 10 };
    const highVersionRestore = { ...activeTask, version: 11 };
    apiMocks.archiveTask.mockResolvedValueOnce(highVersionArchive);
    apiMocks.restoreTask.mockResolvedValueOnce(highVersionRestore);
    apiMocks.updateTask.mockResolvedValueOnce({ ...highVersionRestore, status: 'completed', version: 12 });
    apiMocks.agreements.mockResolvedValueOnce([
      { id: 19, title: 'Buyer agreement', contact_id: null, status: 'draft' },
    ]);
    apiMocks.addTaskLink.mockResolvedValueOnce({
      id: 20,
      task_id: 7,
      entity_type: 'agreement',
      entity_id: 19,
      display_name: 'Buyer agreement',
      task_version: 13,
    });
    const user = await renderWorkspace([activeTask]);
    await openArchiveDialog(user);
    await user.click(screen.getByRole('button', { name: 'Archive' }));
    await user.click(await screen.findByRole('button', { name: 'Undo' }));

    expect(await screen.findByText('Call Jane')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Active' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'Toggle Call Jane' }));

    await waitFor(() => expect(apiMocks.updateTask).toHaveBeenCalledWith(7, {
      expected_version: 11,
      status: 'completed',
    }));
    await user.click(screen.getByRole('button', { name: 'Link record' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Internal record type' }), 'agreement');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Internal record to link' }), '19');
    await user.click(screen.getByRole('button', { name: 'Link' }));

    await waitFor(() => expect(apiMocks.addTaskLink).toHaveBeenCalledWith(7, {
      expected_version: 12,
      entity_type: 'agreement',
      entity_id: 19,
    }));
  });

  it('uses alert/live-region semantics, accessible names, 44px target classes, and no native dialogs or emoji', async () => {
    const confirm = vi.spyOn(window, 'confirm');
    const prompt = vi.spyOn(window, 'prompt');
    const user = await renderWorkspace([activeTask]);

    const active = screen.getByRole('button', { name: 'Active' });
    const archived = screen.getByRole('button', { name: 'Archived' });
    const actions = screen.getByRole('button', { name: 'Task actions for Call Jane' });
    expect(active).toHaveClass('command-touch-target');
    expect(archived).toHaveClass('command-touch-target');
    expect(actions).toHaveClass('command-touch-target');
    await openArchiveDialog(user);
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveClass('command-touch-target');
    expect(screen.getByRole('button', { name: 'Archive' })).toHaveClass('command-touch-target');
    expect(confirm).not.toHaveBeenCalled();
    expect(prompt).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toMatch(/[\u{1F300}-\u{1FAFF}]/u);
  });
});
