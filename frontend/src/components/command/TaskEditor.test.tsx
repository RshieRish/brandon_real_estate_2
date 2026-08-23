import { useState } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Task } from '@/lib/command/api';
import { TaskEditor } from './TaskEditor';

const apiMocks = vi.hoisted(() => ({ updateTask: vi.fn() }));

vi.mock('@/lib/command/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/command/api')>();
  return {
    ...actual,
    commandApi: { ...actual.commandApi, updateTask: apiMocks.updateTask },
  };
});

const task: Task = {
  id: 7,
  title: 'Call buyer',
  contact_id: null,
  description: '',
  priority: 'normal',
  due_at: null,
  status: 'open',
  archived_at: null,
  archive_reason: null,
  version: 3,
};

describe('TaskEditor lifecycle compatibility', () => {
  const originalTimezone = process.env.TZ;

  beforeAll(() => {
    process.env.TZ = 'America/New_York';
  });

  afterAll(() => {
    process.env.TZ = originalTimezone;
  });

  beforeEach(() => {
    apiMocks.updateTask.mockReset().mockResolvedValue({
      ...task,
      title: 'Call buyer today',
      version: 4,
    });
  });

  it('sends the rendered task version and yields the authoritative replacement', async () => {
    const onUpdated = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<TaskEditor task={task} onUpdated={onUpdated} onClose={onClose} />);

    await user.clear(screen.getByRole('textbox', { name: 'Task title' }));
    await user.type(screen.getByRole('textbox', { name: 'Task title' }), 'Call buyer today');
    await user.click(screen.getByRole('button', { name: 'Save task' }));

    await waitFor(() => expect(apiMocks.updateTask).toHaveBeenCalledWith(7, {
      expected_version: 3,
      title: 'Call buyer today',
      description: '',
      priority: 'normal',
      due_at: null,
    }));
    expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ version: 4 }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it.each([
    ['UTC', '2026-08-20T14:30:00Z', '2026-08-20T10:30'],
    ['offset', '2026-08-20T14:30:00+02:00', '2026-08-20T08:30'],
    ['fractional seconds', '2026-08-20T14:30:45.123Z', '2026-08-20T10:30:45.123'],
    ['ambiguous DST instant', '2026-11-01T06:30:45.123Z', '2026-11-01T01:30:45.123'],
  ])('round-trips an untouched %s instant through browser-local datetime fields', async (
    _label,
    dueAt,
    localInput,
  ) => {
    const user = userEvent.setup();
    render(
      <TaskEditor
        task={{ ...task, due_at: dueAt }}
        onUpdated={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('Task due date')).toHaveValue(localInput);
    await user.click(screen.getByRole('button', { name: 'Save task' }));

    await waitFor(() => expect(apiMocks.updateTask).toHaveBeenCalledWith(7, expect.objectContaining({
      expected_version: 3,
      due_at: dueAt,
    })));
  });

  it.each([null, 'not-a-date'])('renders %s due input safely as empty', (dueAt) => {
    render(
      <TaskEditor
        task={{ ...task, due_at: dueAt }}
        onUpdated={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('Task due date')).toHaveValue('');
  });

  it('contains keyboard focus and restores its live trigger after Cancel, Escape, and save', async () => {
    function EditorHarness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Open task editor</button>
          {open ? (
            <TaskEditor
              task={task}
              onUpdated={vi.fn()}
              onClose={() => setOpen(false)}
            />
          ) : null}
        </>
      );
    }

    const user = userEvent.setup();
    render(<EditorHarness />);
    const trigger = screen.getByRole('button', { name: 'Open task editor' });
    await user.click(trigger);

    const dialog = screen.getByRole('dialog', { name: 'Edit task' });
    const close = within(dialog).getByRole('button', { name: 'Close task editor' });
    const save = within(dialog).getByRole('button', { name: 'Save task' });
    expect(close).toHaveFocus();
    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(save).toHaveFocus();
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog', { name: 'Edit task' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog', { name: 'Edit task' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: 'Save task' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Edit task' })).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it('gives every editor action a reusable 44px touch-target class', () => {
    render(<TaskEditor task={task} onUpdated={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByRole('button', { name: 'Close task editor' })).toHaveClass('command-touch-target');
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveClass('command-touch-target');
    expect(screen.getByRole('button', { name: 'Save task' })).toHaveClass('command-touch-target');
  });
});
