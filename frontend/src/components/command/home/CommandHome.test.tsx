import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { buildCommandHomeModel, type CommandHomeModel } from '@/lib/command/home';
import {
  completeHomeInput,
  emptyButAvailableInput,
  emptyButUnavailableInput,
} from '@/test/fixtures/commandHome';
import * as commandApiModule from '@/lib/command/api';
import type { Task } from '@/lib/command/tasks';
import { CommandHome } from './CommandHome';

const navigationMocks = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
  search: '',
}));
const apiMocks = vi.hoisted(() => ({
  createTask: vi.fn(),
  updateGoalProgress: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/admin/command',
  useRouter: () => ({ replace: navigationMocks.replace, push: navigationMocks.push }),
  useSearchParams: () => new URLSearchParams(navigationMocks.search),
}));

vi.mock('@/lib/command/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/command/api')>();
  return {
    ...actual,
    commandApi: {
      ...actual.commandApi,
      createTask: apiMocks.createTask,
      updateGoalProgress: apiMocks.updateGoalProgress,
    },
  };
});

const now = new Date('2026-08-12T13:00:00.000Z');
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function outcomeUncertain(cause: unknown): Error {
  const Constructor = Reflect.get(commandApiModule, 'CommandOutcomeUncertainError');
  if (typeof Constructor === 'function') {
    return new (Constructor as new (cause: unknown) => Error)(cause);
  }
  return Object.assign(
    new Error('The server may have applied the task change; refresh before retrying.'),
    { name: 'CommandOutcomeUncertainError', cause },
  );
}

const completeHomeModel = buildCommandHomeModel(completeHomeInput, now);
const partialHomeModel = buildCommandHomeModel({
  ...completeHomeInput,
  smartViewCounts: null,
}, now);
const emptyHomeModel = buildCommandHomeModel(emptyButAvailableInput, now);
const unavailableHomeModel = buildCommandHomeModel(emptyButUnavailableInput, now);
const regionFailureHomeModel = buildCommandHomeModel({
  ...completeHomeInput,
  tasks: null,
  goals: null,
  celebrations: null,
  briefing: null,
  errors: {
    tasks: 'Tasks unavailable',
    goals: 'Goals unavailable',
    celebrations: 'Celebrations unavailable',
    briefing: 'Briefing unavailable',
  },
}, now);
const taskAuthoritativeRegionFailureHomeModel = buildCommandHomeModel({
  ...completeHomeInput,
  goals: null,
  errors: {
    goals: 'Goals unavailable',
  },
}, now);

function resolved(model: CommandHomeModel = completeHomeModel) {
  return vi.fn().mockResolvedValue(model);
}

describe('Command Home', () => {
  beforeEach(() => {
    navigationMocks.search = '';
    navigationMocks.replace.mockReset();
    navigationMocks.push.mockReset();
    apiMocks.createTask.mockReset().mockResolvedValue({
      id: 20,
      title: 'Call new lead',
      contact_id: null,
      description: '',
      priority: 'normal',
      due_at: null,
      status: 'open',
      archived_at: null,
      archive_reason: null,
      version: 1,
    });
    apiMocks.updateGoalProgress.mockReset().mockResolvedValue({
      ...completeHomeInput.goals?.[0],
      id: 1,
      name: 'Appointments',
      target_value: 12,
      current_value: 7,
      period: 'monthly',
    });
  });

  it('answers what needs attention with one readiness hero and exactly four KPIs', async () => {
    const { container } = render(<CommandHome loadHome={resolved()} />);

    expect(await screen.findByRole('heading', { name: 'Follow-Up Readiness' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { name: 'Follow-Up Readiness' })).toHaveLength(1);
    expect(screen.getByText(/3 overdue tasks need attention first/i)).toBeInTheDocument();
    expect(screen.getAllByTestId('home-kpi')).toHaveLength(4);
    expect(screen.getByRole('link', { name: /Review overdue tasks/i })).toHaveAttribute(
      'href',
      '/admin/command/tasks?tab=todo&due=past',
    );
    expect(container.querySelectorAll('a[href="/admin/command/contacts?smart_view=never_contacted"]')).toHaveLength(3);
    expect(container.querySelectorAll('a[href="/admin/command/contacts?smart_view=recently_active"]')).toHaveLength(1);
    expect(container.querySelectorAll('a[href="/admin/command/contacts?smart_view=birthdays_this_month"]')).toHaveLength(1);
    expect(container.querySelectorAll('a[href="/admin/command/contacts?smart_view=anniversaries_this_month"]')).toHaveLength(1);
    expect(Array.from(container.querySelectorAll('a')).map((link) => link.getAttribute('href')).join(' ')).not.toMatch(
      /filter=never_contacted|filter=birthdays|filter=anniversaries|sort=recent_activity/,
    );
  });

  it('labels incomplete readiness and names the unavailable input without implying perfection', async () => {
    render(<CommandHome loadHome={resolved(partialHomeModel)} />);

    expect(await screen.findByText(/3 of 4 inputs verified/i)).toBeInTheDocument();
    expect(screen.getByText(/Last-contact history is unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText('100% ready')).not.toBeInTheDocument();
  });

  it('renders loading skeletons before a factual model resolves', async () => {
    let resolveModel!: (model: CommandHomeModel) => void;
    const loadHome = vi.fn(() => new Promise<CommandHomeModel>((resolve) => {
      resolveModel = resolve;
    }));
    render(<CommandHome loadHome={loadHome} />);

    expect(screen.getByRole('status', { name: 'Loading Command Home' })).toBeInTheDocument();
    expect(screen.getByTestId('home-loading-skeleton')).toBeInTheDocument();
    await act(async () => resolveModel(completeHomeModel));
    expect(await screen.findByRole('heading', { name: 'Follow-Up Readiness' })).toBeInTheDocument();
  });

  it('retries only after a failed load and announces the error', async () => {
    const loadHome = vi.fn()
      .mockRejectedValueOnce(new Error('Home unavailable'))
      .mockResolvedValueOnce(completeHomeModel);
    const user = userEvent.setup();
    render(<CommandHome loadHome={loadHome} />);

    const retry = await screen.findByRole('button', { name: 'Retry Home' });
    expect(screen.getByRole('alert')).toHaveTextContent('Home unavailable');
    expect(loadHome).toHaveBeenCalledTimes(1);
    await user.click(retry);
    expect(await screen.findByRole('heading', { name: 'Follow-Up Readiness' })).toBeInTheDocument();
    expect(loadHome).toHaveBeenCalledTimes(2);
  });

  it('creates one fresh controller per attempt and aborts retry and unmount cleanup', async () => {
    const signals: AbortSignal[] = [];
    const loadHome = vi.fn((signal?: AbortSignal) => {
      if (signal) signals.push(signal);
      if (signals.length === 1) return Promise.reject(new Error('Retryable'));
      return Promise.resolve(completeHomeModel);
    });
    const user = userEvent.setup();
    const view = render(<CommandHome loadHome={loadHome} />);

    await user.click(await screen.findByRole('button', { name: 'Retry Home' }));
    expect(await screen.findByRole('heading', { name: 'Follow-Up Readiness' })).toBeInTheDocument();
    expect(signals).toHaveLength(2);
    expect(signals[0]).not.toBe(signals[1]);
    expect(signals[0]?.aborted).toBe(true);
    expect(signals[1]?.aborted).toBe(false);

    view.unmount();
    expect(signals[1]?.aborted).toBe(true);
  });

  it('suppresses stale fulfillment from a test loader that ignores its aborted signal', async () => {
    let resolveFirst!: (model: CommandHomeModel) => void;
    let firstSignal: AbortSignal | undefined;
    const firstLoad = vi.fn((signal?: AbortSignal) => {
      firstSignal = signal;
      return new Promise<CommandHomeModel>((resolve) => {
        resolveFirst = resolve;
      });
    });
    const secondLoad = vi.fn().mockResolvedValue(emptyHomeModel);
    const view = render(<CommandHome loadHome={firstLoad} />);

    view.rerender(<CommandHome loadHome={secondLoad} />);
    expect(await screen.findByText('Your follow-up queue is clear.')).toBeInTheDocument();
    expect(firstSignal?.aborted).toBe(true);

    await act(async () => resolveFirst(completeHomeModel));
    expect(screen.getByText('Your follow-up queue is clear.')).toBeInTheDocument();
    expect(screen.queryByText('Call Avery')).not.toBeInTheDocument();
  });

  it('keeps AbortError rejection silent instead of rendering the global error panel', async () => {
    const abort = new DOMException('Synthetic stop', 'AbortError');
    const loadHome = vi.fn().mockRejectedValue(abort);

    render(<CommandHome loadHome={loadHome} />);

    await waitFor(() => expect(loadHome).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('status', { name: 'Loading Command Home' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText('Synthetic stop')).not.toBeInTheDocument();
  });

  it('renders an available empty workspace as a positive operational state', async () => {
    render(<CommandHome loadHome={resolved(emptyHomeModel)} />);

    expect(await screen.findByText('Your follow-up queue is clear.')).toBeInTheDocument();
    expect(screen.getByText('No open tasks in scope.')).toBeInTheDocument();
    expect(screen.getByText('No goals set yet.')).toBeInTheDocument();
  });

  it('shows unavailable shortcut counts and partial explanations instead of zeros', async () => {
    render(<CommandHome loadHome={resolved(unavailableHomeModel)} />);

    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });
    const shortcuts = screen.getByRole('region', { name: 'Home shortcuts' });
    expect(within(shortcuts).getAllByText('Unavailable')).toHaveLength(4);
    expect(within(shortcuts).getAllByText(/Source data is unavailable/i)).toHaveLength(4);
    expect(screen.queryByText('Your follow-up queue is clear.')).not.toBeInTheDocument();
    expect(screen.getByText(/Readiness inputs are unavailable/i)).toBeInTheDocument();
  });

  it('renders unowned task data only in All and marks personal and team scopes unavailable', async () => {
    const user = userEvent.setup();
    render(<CommandHome loadHome={resolved()} />);
    const allTasks = await screen.findByRole('tab', { name: 'All' });

    expect(allTasks).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Call Avery')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'My Tasks' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Personal' }));
    expect(screen.getByText(/Personal task ownership is unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText('Call Avery')).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Team' }));
    expect(screen.getByText(/Team task ownership is unavailable/i)).toBeInTheDocument();
  });

  it('renders semantic score tracks so factor scores are visually and accessibly encoded', async () => {
    render(<CommandHome loadHome={resolved()} />);

    expect(await screen.findByRole('progressbar', { name: 'Overdue tasks score' })).toHaveAttribute('value', '25');
    expect(screen.getByRole('progressbar', { name: 'Contact health score' })).toHaveAttribute('value', '75');

    render(<CommandHome loadHome={resolved(partialHomeModel)} />);
    await screen.findAllByRole('heading', { name: 'Follow-Up Readiness' });
    expect(screen.queryAllByRole('progressbar', { name: 'Never-contacted leads score' })).toHaveLength(1);
  });

  it('keeps failed task, goal, celebration, and briefing regions unavailable and retries the snapshot', async () => {
    const loadHome = vi.fn()
      .mockResolvedValueOnce(regionFailureHomeModel)
      .mockResolvedValueOnce(completeHomeModel);
    const user = userEvent.setup();
    render(<CommandHome loadHome={loadHome} />);

    expect(await screen.findByRole('heading', { name: 'Tasks unavailable' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Goals unavailable' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Celebrations unavailable' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Briefing unavailable' })).toBeInTheDocument();
    expect(screen.queryByText('No open tasks in scope.')).not.toBeInTheDocument();
    expect(screen.queryByText('No goals set yet.')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Retry unavailable regions' }));
    expect(await screen.findByText('Call Avery')).toBeInTheDocument();
    expect(loadHome).toHaveBeenCalledTimes(2);
  });

  it('persists goal progress through the current internal API', async () => {
    const user = userEvent.setup();
    render(<CommandHome loadHome={resolved()} />);
    await screen.findByRole('heading', { name: 'Goals' });

    await user.click(screen.getByRole('button', { name: 'Update Appointments' }));
    const progress = screen.getByRole('spinbutton', { name: 'Appointments progress' });
    await user.clear(progress);
    await user.type(progress, '7');
    await user.click(screen.getByRole('button', { name: 'Save Appointments progress' }));

    await waitFor(() => expect(apiMocks.updateGoalProgress).toHaveBeenCalledWith(1, 7));
    expect(await screen.findByText('7 / 12')).toBeInTheDocument();
  });

  it('marks briefing review, bookings, and recovered placeholders with truthful source states', async () => {
    const user = userEvent.setup();
    render(<CommandHome loadHome={resolved()} />);

    expect(await screen.findByText('Review only')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Upcoming bookings' })).toBeInTheDocument();
    expect(screen.getByText(/Global booking list is unavailable/i)).toBeInTheDocument();
    const disclosure = screen.getByText('Recovered dashboard evidence');
    await user.click(disclosure);
    expect(screen.getByText(/Captured placeholders are source evidence only/i)).toBeInTheDocument();
  });

  it('opens create=task as a real overlay and removes the parameter when closed', async () => {
    navigationMocks.search = 'create=task';
    const user = userEvent.setup();
    render(<CommandHome loadHome={resolved()} />);

    expect(await screen.findByRole('dialog', { name: 'Create task' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Close detail' }));
    expect(navigationMocks.replace).toHaveBeenCalledWith('/admin/command', { scroll: false });
  });

  it('persists quick-created tasks and closes the shared overlay', async () => {
    const user = userEvent.setup();
    render(<CommandHome loadHome={resolved()} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Call new lead');
    await user.click(screen.getByRole('button', { name: 'Save task' }));

    await waitFor(() => expect(apiMocks.createTask).toHaveBeenCalledWith({
      title: 'Call new lead',
      description: '',
      priority: 'normal',
      contact_id: null,
      due_at: null,
    }, expect.stringMatching(UUID_PATTERN), {
      clientTimezone: expect.any(String),
    }));
    expect(screen.queryByRole('dialog', { name: 'Create task' })).not.toBeInTheDocument();
    expect(navigationMocks.replace).toHaveBeenCalledWith('/admin/command', { scroll: false });
  });

  it('announces a quick-created task through a polite live region', async () => {
    const user = userEvent.setup();
    render(<CommandHome loadHome={resolved()} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Call new lead');
    await user.click(screen.getByRole('button', { name: 'Save task' }));

    const status = await screen.findByRole('status', { name: 'Task creation status' });
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toHaveTextContent('Task saved');
  });

  it('announces quick-task failures through an assertive live region', async () => {
    apiMocks.createTask.mockRejectedValueOnce(new Error('Synthetic task rejection'));
    const user = userEvent.setup();
    render(<CommandHome loadHome={resolved()} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Rejected task');
    await user.click(screen.getByRole('button', { name: 'Save task' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveAttribute('aria-live', 'assertive');
    expect(alert).toHaveTextContent('Synthetic task rejection');
  });

  it('authoritatively refreshes after an outcome-uncertain create without retrying it', async () => {
    apiMocks.createTask.mockRejectedValueOnce(outcomeUncertain(new TypeError('Synthetic network loss')));
    const loadHome = vi.fn()
      .mockResolvedValueOnce(completeHomeModel)
      .mockResolvedValueOnce(completeHomeModel);
    const user = userEvent.setup();
    render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Uncertain task');
    await user.click(screen.getByRole('button', { name: 'Save task' }));

    await waitFor(() => expect(loadHome).toHaveBeenCalledTimes(2));
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The server may have applied the task change; refresh before retrying.',
    );
  });

  it('reuses the same UUID and canonical payload for an unchanged explicit retry after reconciliation', async () => {
    apiMocks.createTask
      .mockRejectedValueOnce(outcomeUncertain(new TypeError('Synthetic network loss')))
      .mockResolvedValueOnce({
        id: 20, title: 'Uncertain task', contact_id: null, description: '', priority: 'normal',
        due_at: null, status: 'open', archived_at: null, archive_reason: null, version: 1,
      });
    const loadHome = vi.fn()
      .mockResolvedValueOnce(completeHomeModel)
      .mockResolvedValueOnce(completeHomeModel)
      .mockResolvedValueOnce(completeHomeModel);
    const user = userEvent.setup();
    render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Uncertain task');
    const save = screen.getByRole('button', { name: 'Save task' });
    await user.click(save);
    await waitFor(() => expect(save).toBeEnabled());
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);
    const firstCall = apiMocks.createTask.mock.calls[0];

    await user.type(screen.getByRole('textbox', { name: 'Task title' }), ' ');
    await user.type(screen.getByRole('textbox', { name: 'Task description' }), ' ');
    await user.click(save);
    await waitFor(() => expect(apiMocks.createTask).toHaveBeenCalledTimes(2));
    expect(apiMocks.createTask.mock.calls[1]).toEqual(firstCall);
  });

  it('allocates a new UUID when the Home create draft changes after uncertainty', async () => {
    apiMocks.createTask
      .mockRejectedValueOnce(outcomeUncertain(new TypeError('Synthetic network loss')))
      .mockResolvedValueOnce({
        id: 20, title: 'Changed task', contact_id: null, description: '', priority: 'normal',
        due_at: null, status: 'open', archived_at: null, archive_reason: null, version: 1,
      });
    const loadHome = vi.fn()
      .mockResolvedValueOnce(completeHomeModel)
      .mockResolvedValueOnce(completeHomeModel)
      .mockResolvedValueOnce(completeHomeModel);
    const user = userEvent.setup();
    render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    const title = screen.getByRole('textbox', { name: 'Task title' });
    await user.type(title, 'Original task');
    await user.click(screen.getByRole('button', { name: 'Save task' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save task' })).toBeEnabled());
    const firstKey = apiMocks.createTask.mock.calls[0]?.[1];

    await user.clear(title);
    await user.type(title, 'Changed task');
    await user.click(screen.getByRole('button', { name: 'Save task' }));
    await waitFor(() => expect(apiMocks.createTask).toHaveBeenCalledTimes(2));
    expect(apiMocks.createTask.mock.calls[1]?.[1]).not.toBe(firstKey);
  });

  it('keeps quick task creation locked when an uncertain outcome cannot be authoritatively refreshed', async () => {
    apiMocks.createTask.mockRejectedValueOnce(outcomeUncertain(new TypeError('Synthetic network loss')));
    const loadHome = vi.fn()
      .mockResolvedValueOnce(completeHomeModel)
      .mockRejectedValueOnce(new Error('Synthetic authoritative refresh failure'));
    const user = userEvent.setup();
    render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Uncertain task');
    const save = screen.getByRole('button', { name: 'Save task' });
    await user.click(save);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Task state could not be refreshed. Refresh the page before creating another task.',
    );
    expect(save).toBeDisabled();
    await user.click(save);
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);
    expect(loadHome).toHaveBeenCalledTimes(2);

    const firstRequestId = apiMocks.createTask.mock.calls[0]?.[1];
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await user.click(screen.getByRole('button', { name: 'Create task' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Task state could not be refreshed. Refresh the page before creating another task.',
    );
    const reopenedSave = screen.getByRole('button', { name: 'Save task' });
    expect(reopenedSave).toBeDisabled();
    await user.click(reopenedSave);
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);
    expect(apiMocks.createTask.mock.calls[0]?.[1]).toBe(firstRequestId);
  });

  it('keeps an uncertain create locked through resolved task-region failures until tasks are authoritative', async () => {
    apiMocks.createTask
      .mockRejectedValueOnce(outcomeUncertain(new TypeError('Synthetic network loss')))
      .mockResolvedValueOnce({
        id: 20, title: 'Task-region retry', contact_id: null, description: '', priority: 'normal',
        due_at: null, status: 'open', archived_at: null, archive_reason: null, version: 1,
      });
    let resolvePartialRetry!: (model: CommandHomeModel) => void;
    const loadHome = vi.fn()
      .mockResolvedValueOnce(completeHomeModel)
      .mockResolvedValueOnce(regionFailureHomeModel)
      .mockImplementationOnce(() => new Promise<CommandHomeModel>((resolve) => {
        resolvePartialRetry = resolve;
      }))
      .mockResolvedValueOnce(taskAuthoritativeRegionFailureHomeModel)
      .mockResolvedValueOnce(completeHomeModel);
    const user = userEvent.setup();
    render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Task-region retry');
    const save = screen.getByRole('button', { name: 'Save task' });
    await user.click(save);

    expect(await screen.findByText(
      'Task state could not be refreshed. Refresh the page before creating another task.',
    )).toBeInTheDocument();
    expect(save).toBeDisabled();
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);
    const firstCall = apiMocks.createTask.mock.calls[0];

    await user.click(screen.getByRole('button', { name: 'Retry Home refresh' }));
    await waitFor(() => expect(loadHome).toHaveBeenCalledTimes(3));
    await act(async () => resolvePartialRetry(regionFailureHomeModel));
    expect(save).toBeDisabled();
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Retry Home refresh' }));
    await screen.findByRole('heading', { name: 'Goals unavailable' });
    expect(save).toBeEnabled();
    await user.click(save);

    await waitFor(() => expect(apiMocks.createTask).toHaveBeenCalledTimes(2));
    expect(apiMocks.createTask.mock.calls[1]).toEqual(firstCall);
  });

  it('releases a refresh-required create lock only after an explicit authoritative Home retry succeeds', async () => {
    apiMocks.createTask
      .mockRejectedValueOnce(outcomeUncertain(new TypeError('Synthetic network loss')))
      .mockResolvedValueOnce({
        id: 20, title: 'Retry-safe task', contact_id: null, description: '', priority: 'normal',
        due_at: null, status: 'open', archived_at: null, archive_reason: null, version: 1,
      });
    const loadHome = vi.fn()
      .mockResolvedValueOnce(completeHomeModel)
      .mockRejectedValueOnce(new Error('Synthetic mutation refresh failure'))
      .mockResolvedValueOnce(completeHomeModel)
      .mockResolvedValueOnce(completeHomeModel);
    const user = userEvent.setup();
    render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Retry-safe task');
    await user.click(screen.getByRole('button', { name: 'Save task' }));
    await screen.findByText('Task state could not be refreshed. Refresh the page before creating another task.');
    const firstCall = apiMocks.createTask.mock.calls[0];

    await user.click(screen.getByRole('button', { name: 'Retry Home refresh' }));
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });
    const save = screen.getByRole('button', { name: 'Save task' });
    expect(save).toBeEnabled();
    await user.click(save);

    await waitFor(() => expect(apiMocks.createTask).toHaveBeenCalledTimes(2));
    expect(apiMocks.createTask.mock.calls[1]).toEqual(firstCall);
  });

  it('retains the create lock when an explicit authoritative Home retry also fails', async () => {
    apiMocks.createTask.mockRejectedValueOnce(outcomeUncertain(new TypeError('Synthetic network loss')));
    const loadHome = vi.fn()
      .mockResolvedValueOnce(completeHomeModel)
      .mockRejectedValueOnce(new Error('Synthetic mutation refresh failure'))
      .mockRejectedValueOnce(new Error('Synthetic explicit retry failure'));
    const user = userEvent.setup();
    render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Still locked task');
    await user.click(screen.getByRole('button', { name: 'Save task' }));
    await screen.findByText('Task state could not be refreshed. Refresh the page before creating another task.');
    await user.click(screen.getByRole('button', { name: 'Retry Home refresh' }));
    await screen.findByRole('heading', { name: 'Command Home unavailable' });
    expect(screen.getByRole('button', { name: 'Save task' })).toBeDisabled();
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);
  });

  it('closes a confirmed create only after an explicit authoritative Home recovery succeeds', async () => {
    const loadHome = vi.fn()
      .mockResolvedValueOnce(completeHomeModel)
      .mockRejectedValueOnce(new Error('Synthetic post-create refresh failure'))
      .mockResolvedValueOnce(completeHomeModel);
    const user = userEvent.setup();
    render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Confirmed task');
    await user.click(screen.getByRole('button', { name: 'Save task' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Task saved, but Home could not refresh. Synthetic post-create refresh failure Refresh the page before creating another task.',
    );
    expect(screen.getByRole('button', { name: 'Task saved' })).toBeDisabled();
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Retry Home refresh' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Create task' })).not.toBeInTheDocument());
    expect(loadHome).toHaveBeenCalledTimes(3);
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);
  });

  it('keeps a confirmed create locked when a resolved Home refresh has no authoritative tasks', async () => {
    let resolvePartialRetry!: (model: CommandHomeModel) => void;
    const loadHome = vi.fn()
      .mockResolvedValueOnce(completeHomeModel)
      .mockResolvedValueOnce(regionFailureHomeModel)
      .mockImplementationOnce(() => new Promise<CommandHomeModel>((resolve) => {
        resolvePartialRetry = resolve;
      }))
      .mockResolvedValueOnce(taskAuthoritativeRegionFailureHomeModel);
    const user = userEvent.setup();
    render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Confirmed partial task');
    await user.click(screen.getByRole('button', { name: 'Save task' }));

    expect(await screen.findByText(
      'Task saved, but Home could not refresh. Refresh the page before creating another task.',
    )).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Task saved' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Retry Home refresh' }));
    await waitFor(() => expect(loadHome).toHaveBeenCalledTimes(3));
    await act(async () => resolvePartialRetry(regionFailureHomeModel));
    expect(screen.getByRole('button', { name: 'Task saved' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Retry Home refresh' }));
    await screen.findByRole('heading', { name: 'Goals unavailable' });
    expect(screen.queryByRole('dialog', { name: 'Create task' })).not.toBeInTheDocument();
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);
  });

  it('does not let an older unrelated Home read release a newer mutation refresh lock', async () => {
    apiMocks.createTask.mockRejectedValueOnce(outcomeUncertain(new TypeError('Synthetic network loss')));
    let resolveOlderRead!: (model: CommandHomeModel) => void;
    const loadHome = vi.fn()
      .mockResolvedValueOnce(regionFailureHomeModel)
      .mockImplementationOnce(() => new Promise<CommandHomeModel>((resolve) => {
        resolveOlderRead = resolve;
      }))
      .mockRejectedValueOnce(new Error('Synthetic authoritative mutation refresh failure'));
    const user = userEvent.setup();
    render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('button', { name: 'Retry unavailable regions' });

    await user.click(screen.getByRole('button', { name: 'Retry unavailable regions' }));
    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Generation-owned task');
    await user.click(screen.getByRole('button', { name: 'Save task' }));
    await screen.findByText('Task state could not be refreshed. Refresh the page before creating another task.');

    await act(async () => resolveOlderRead(completeHomeModel));
    expect(screen.getByRole('button', { name: 'Save task' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Task state could not be refreshed. Refresh the page before creating another task.',
    );
    expect(apiMocks.createTask).toHaveBeenCalledTimes(1);
  });

  it('reloads and swaps the whole Home model atomically after quick task creation', async () => {
    const user = userEvent.setup();
    let resolveRefresh!: (model: CommandHomeModel) => void;
    const refreshedModel = buildCommandHomeModel({
      ...completeHomeInput,
      tasks: [
        ...(completeHomeInput.tasks ?? []),
        {
          id: 20,
          title: 'Call new lead',
          contact_id: null,
          description: '',
          priority: 'normal',
          due_at: '2026-08-08T13:00:00.000Z',
          status: 'open',
          archived_at: null,
          archive_reason: null,
          version: 1,
        },
      ],
    }, now);
    const loadHome = vi.fn()
      .mockResolvedValueOnce(completeHomeModel)
      .mockImplementationOnce(() => new Promise<CommandHomeModel>((resolve) => {
        resolveRefresh = resolve;
      }));
    render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    const metrics = screen.getByRole('region', { name: 'Operational metrics' });
    expect(within(within(metrics).getByRole('link', { name: /Open tasks/i })).getByText('4')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Call new lead');
    await user.click(screen.getByRole('button', { name: 'Save task' }));
    await waitFor(() => expect(loadHome).toHaveBeenCalledTimes(2));

    expect(within(within(metrics).getByRole('link', { name: /Open tasks/i })).getByText('4')).toBeInTheDocument();
    expect(screen.getByText(/3 overdue tasks need attention first/i)).toBeInTheDocument();

    await act(async () => resolveRefresh(refreshedModel));
    expect(await within(within(metrics).getByRole('link', { name: /Open tasks/i })).findByText('5')).toBeInTheDocument();
    expect(screen.getByText(/4 overdue tasks need attention first/i)).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Create task' })).not.toBeInTheDocument();
  });

  it('does not let generic Home retry abort a pending post-create authoritative refresh', async () => {
    const user = userEvent.setup();
    const signals: Array<AbortSignal | undefined> = [];
    let resolveQuickRefresh!: (model: CommandHomeModel) => void;
    const loadHome = vi.fn((signal?: AbortSignal) => {
      signals.push(signal);
      if (signals.length === 1) return Promise.resolve(regionFailureHomeModel);
      if (signals.length === 2) {
        return new Promise<CommandHomeModel>((resolve) => {
          resolveQuickRefresh = resolve;
        });
      }
      return Promise.resolve(emptyHomeModel);
    });
    render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('button', { name: 'Retry unavailable regions' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Race-safe task');
    await user.click(screen.getByRole('button', { name: 'Save task' }));
    await waitFor(() => expect(loadHome).toHaveBeenCalledTimes(2));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await user.click(screen.getByRole('button', { name: 'Retry unavailable regions' }));

    expect(signals[1]?.aborted).toBe(false);
    expect(loadHome).toHaveBeenCalledTimes(2);
    await act(async () => resolveQuickRefresh(completeHomeModel));
    expect(await screen.findByRole('heading', { name: 'Follow-Up Readiness' })).toBeInTheDocument();
  });

  it('aborts a pending quick-task refresh on unmount', async () => {
    const user = userEvent.setup();
    let refreshSignal: AbortSignal | undefined;
    const loadHome = vi.fn((signal?: AbortSignal) => {
      if (loadHome.mock.calls.length === 1) return Promise.resolve(completeHomeModel);
      refreshSignal = signal;
      return new Promise<CommandHomeModel>(() => undefined);
    });
    const view = render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Unmount-safe task');
    await user.click(screen.getByRole('button', { name: 'Save task' }));
    await waitFor(() => expect(loadHome).toHaveBeenCalledTimes(2));

    expect(refreshSignal?.aborted).toBe(false);
    view.unmount();
    expect(refreshSignal?.aborted).toBe(true);
  });

  it('does not start a Home refresh when unmounted during the task mutation', async () => {
    const user = userEvent.setup();
    let resolveCreateTask!: (value: Task) => void;
    apiMocks.createTask.mockImplementationOnce(() => new Promise((resolve) => {
      resolveCreateTask = resolve;
    }));
    const loadHome = resolved();
    const view = render(<CommandHome loadHome={loadHome} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    await user.click(screen.getByRole('button', { name: 'Create task' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Deferred task');
    await user.click(screen.getByRole('button', { name: 'Save task' }));
    await waitFor(() => expect(apiMocks.createTask).toHaveBeenCalledTimes(1));
    view.unmount();

    await act(async () => resolveCreateTask({
      id: 21,
      title: 'Deferred task',
      contact_id: null,
      description: '',
      priority: 'normal',
      due_at: null,
      status: 'open',
      archived_at: null,
      archive_reason: null,
      version: 1,
    }));

    expect(loadHome).toHaveBeenCalledTimes(1);
  });

  it('uses Customize only to change visible local Home panels', async () => {
    const user = userEvent.setup();
    render(<CommandHome loadHome={resolved()} />);
    await screen.findByRole('heading', { name: 'Goals' });

    await user.click(screen.getByRole('button', { name: 'Customize Home' }));
    await user.click(screen.getByRole('checkbox', { name: 'Show goals' }));
    expect(screen.queryByRole('heading', { name: 'Goals' })).not.toBeInTheDocument();
  });

  it('ships no legacy vendor branding or assets in the rebuilt Home', async () => {
    const { container } = render(<CommandHome loadHome={resolved()} />);
    await screen.findByRole('heading', { name: 'Follow-Up Readiness' });

    const forbiddenBrands = [
      ['Keller', 'Williams'].join(' '),
      ['Docu', 'Sign'].join(''),
      ['KW', 'IQ'].join(''),
    ];
    expect(forbiddenBrands.every((brand) => !container.textContent?.includes(brand))).toBe(true);
    const legacyBrokerageAsset = ['exp', 'realty'].join('-');
    expect(container.querySelector(`[src*="${legacyBrokerageAsset}"]`)).toBeNull();
  });
});
