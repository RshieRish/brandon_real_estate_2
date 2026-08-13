import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { buildCommandHomeModel, type CommandHomeModel } from '@/lib/command/home';
import {
  completeHomeInput,
  emptyButAvailableInput,
  emptyButUnavailableInput,
  inputWithoutLastContactFields,
} from '@/test/fixtures/commandHome';
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
const completeHomeModel = buildCommandHomeModel(completeHomeInput, now);
const partialHomeModel = buildCommandHomeModel(inputWithoutLastContactFields, now);
const emptyHomeModel = buildCommandHomeModel(emptyButAvailableInput, now);
const unavailableHomeModel = buildCommandHomeModel(emptyButUnavailableInput, now);

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
    render(<CommandHome loadHome={resolved()} />);

    expect(await screen.findByRole('heading', { name: 'Follow-Up Readiness' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { name: 'Follow-Up Readiness' })).toHaveLength(1);
    expect(screen.getByText(/3 overdue tasks need attention first/i)).toBeInTheDocument();
    expect(screen.getAllByTestId('home-kpi')).toHaveLength(4);
    expect(screen.getByRole('link', { name: /Review overdue tasks/i })).toHaveAttribute(
      'href',
      '/admin/command/tasks?tab=todo&due=past',
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
  });

  it('changes task scope with keyboard-operable tabs and shows the current API limitation', async () => {
    const user = userEvent.setup();
    render(<CommandHome loadHome={resolved()} />);
    const myTasks = await screen.findByRole('tab', { name: 'My Tasks' });

    myTasks.focus();
    await user.keyboard('{ArrowRight}{Enter}');
    expect(screen.getByRole('tab', { name: 'Team Tasks' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText(/Team task ownership is unavailable/i)).toBeInTheDocument();
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
    }));
    expect(screen.queryByRole('dialog', { name: 'Create task' })).not.toBeInTheDocument();
    expect(navigationMocks.replace).toHaveBeenCalledWith('/admin/command', { scroll: false });
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
