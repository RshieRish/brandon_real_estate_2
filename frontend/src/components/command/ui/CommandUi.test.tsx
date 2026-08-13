import { useCallback, useRef, useState } from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest';
import { CommandDataTable, type CommandColumn } from './CommandDataTable';
import { CommandEvidencePanel } from './CommandEvidencePanel';
import { CommandModuleHeader } from './CommandModuleHeader';
import { CommandOverlay } from './CommandOverlay';
import { CommandStatePanel, type CommandStatePanelProps } from './CommandStatePanel';
import { CommandTabs } from './CommandTabs';
import {
  CommandToastProvider,
  useCommandToast,
  type CommandToastInput,
} from './CommandToastProvider';

const taskTabs = [
  { value: 'todo', label: 'To Do' },
  { value: 'completed', label: 'Completed' },
  { value: 'paused', label: 'Paused', disabled: true },
  { value: 'archived', label: 'Archived' },
] as const;

const rows = [
  { id: '1', name: 'Avery Lake', stage: 'Lead' },
  { id: '2', name: 'Morgan Hill', stage: 'Client' },
];

const columns: readonly CommandColumn<(typeof rows)[number]>[] = [
  { key: 'name', header: 'Name', sortable: true, width: '18rem', render: (row) => row.name },
  { key: 'stage', header: 'Stage', sortable: true, render: (row) => row.stage },
];

function OverlayAndToastProbe() {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const { pushToast } = useCommandToast();
  const onOpenChange = useCallback((nextOpen: boolean) => setOpen(nextOpen), []);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => {
          setOpen(true);
          pushToast({ tone: 'error', message: 'Unable to save' });
        }}
      >
        Open detail
      </button>
      <CommandOverlay
        open={open}
        variant="drawer"
        labelledBy="detail-heading"
        triggerRef={triggerRef}
        onOpenChange={onOpenChange}
      >
        <h2 id="detail-heading">Detail</h2>
        <button type="button">Edit record</button>
      </CommandOverlay>
    </>
  );
}

function SuccessToastProbe() {
  const { pushToast } = useCommandToast();
  return (
    <button
      type="button"
      onClick={() => pushToast({ tone: 'success', message: 'Task saved' })}
    >
      Save task
    </button>
  );
}

function InvalidErrorUndoProbe() {
  const { pushToast } = useCommandToast();
  return (
    <button
      type="button"
      onClick={() => pushToast({
        tone: 'error',
        message: 'Save failed',
        onUndo: vi.fn(),
      } as never)}
    >
      Fail save
    </button>
  );
}

describe('Command workspace primitives', () => {
  beforeEach(() => {
    document.body.style.overflow = '';
  });

  it('requires an explicit retry action for error state props', () => {
    expectTypeOf<{
      kind: 'error';
      title: string;
      message: string;
    }>().not.toMatchTypeOf<CommandStatePanelProps>();
  });

  it('rejects reversible callbacks on non-success toast inputs', () => {
    expectTypeOf<{
      tone: 'error';
      message: string;
      onUndo: () => void;
    }>().not.toMatchTypeOf<CommandToastInput>();
  });

  it('moves tab focus with arrows, Home, and End without activating disabled tabs', async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <CommandTabs
        ariaLabel="Task states"
        tabs={taskTabs}
        value="todo"
        onValueChange={onValueChange}
      />,
    );

    const todo = screen.getByRole('tab', { name: 'To Do' });
    const completed = screen.getByRole('tab', { name: 'Completed' });
    const archived = screen.getByRole('tab', { name: 'Archived' });
    todo.focus();
    await user.keyboard('{ArrowRight}{Enter}');
    expect(completed).toHaveFocus();
    expect(onValueChange).toHaveBeenCalledWith('completed');
    await user.keyboard('{ArrowRight}');
    expect(archived).toHaveFocus();
    await user.keyboard('{Home}{Enter}');
    expect(todo).toHaveFocus();
    expect(onValueChange).toHaveBeenLastCalledWith('todo');
    await user.keyboard('{End}{Enter}');
    expect(archived).toHaveFocus();
    expect(onValueChange).toHaveBeenLastCalledWith('archived');
    expect(screen.getByRole('tab', { name: 'Paused' })).toBeDisabled();
  });

  it('links tabs to deterministic panels and supports click activation', async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <CommandTabs
        idBase="task-state"
        ariaLabel="Task states"
        tabs={taskTabs}
        value="todo"
        onValueChange={onValueChange}
      />,
    );

    const completed = screen.getByRole('tab', { name: 'Completed' });
    expect(screen.getByRole('tab', { name: 'To Do' })).toHaveAttribute(
      'aria-controls',
      'task-state-panel-todo',
    );
    expect(completed).toHaveAttribute('id', 'task-state-tab-completed');
    await user.click(completed);
    expect(onValueChange).toHaveBeenCalledWith('completed');
  });

  it('synchronizes the roving tab stop when the controlled value changes', () => {
    const onValueChange = vi.fn();
    const view = render(
      <CommandTabs
        idBase="task-state"
        ariaLabel="Task states"
        tabs={taskTabs}
        value="todo"
        onValueChange={onValueChange}
      />,
    );

    expect(screen.getByRole('tab', { name: 'To Do' })).toHaveAttribute('tabindex', '0');
    view.rerender(
      <CommandTabs
        idBase="task-state"
        ariaLabel="Task states"
        tabs={taskTabs}
        value="completed"
        onValueChange={onValueChange}
      />,
    );
    expect(screen.getByRole('tab', { name: 'To Do' })).toHaveAttribute('tabindex', '-1');
    expect(screen.getByRole('tab', { name: 'Completed' })).toHaveAttribute('tabindex', '0');
  });

  it('distinguishes aggregate evidence from observed records without fabricating imports', () => {
    render(
      <CommandEvidencePanel
        evidenceLevel="displayed_aggregate"
        captureQuality="partial"
        displayLabel="My Referral Network"
        observedCount={5}
        displayedCount={2318}
        artifactCount={2}
        explanation="The dashboard repeated a displayed range; expanded profiles were limited."
        artifactActions={[{ label: 'Open referral evidence', onAction: vi.fn() }]}
      />,
    );

    expect(screen.getByText('Displayed aggregate')).toBeInTheDocument();
    expect(screen.getByText('Partial capture')).toBeInTheDocument();
    expect(screen.getByText(/2,318 was displayed; 5 distinct identities were observed/i)).toBeInTheDocument();
    expect(screen.queryByText(/2,318 people imported/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open referral evidence' })).toBeInTheDocument();
  });

  it('labels a missing normalized count as not materialized rather than zero', () => {
    render(
      <CommandEvidencePanel
        evidenceLevel="rendered_occurrence"
        captureQuality="limitation"
        displayLabel="Recovered designs"
        normalizedCount={null}
        renderedCount={34}
        artifactCount={1}
      />,
    );

    expect(screen.getByText('Rendered occurrence')).toBeInTheDocument();
    expect(screen.getByText('34')).toBeInTheDocument();
    expect(screen.getByText('Not materialized')).toBeInTheDocument();
    expect(screen.queryByText('Observed records')).not.toBeInTheDocument();
  });

  it('renders only supplied evidence counts and never implies capture completeness', () => {
    render(
      <CommandEvidencePanel
        evidenceLevel="observed_record"
        captureQuality="partial"
        displayLabel="Recovered contact"
        observedCount={1}
      />,
    );

    expect(screen.getByText('Observed records')).toBeInTheDocument();
    expect(screen.queryByText('Normalized records')).not.toBeInTheDocument();
    expect(screen.queryByText('Rendered occurrences')).not.toBeInTheDocument();
    expect(screen.queryByText('Displayed count')).not.toBeInTheDocument();
    expect(screen.queryByText('Source artifacts')).not.toBeInTheDocument();
    expect(screen.getByText('Partial capture')).toBeInTheDocument();
  });

  it('keeps a wide semantic data table inside its own scroll container', () => {
    render(
      <CommandDataTable
        ariaLabel="Contacts"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.id}
      />,
    );

    expect(screen.getByRole('region', { name: 'Contacts table' })).toHaveClass(
      'command-table-scroll',
    );
    expect(screen.getByRole('table', { name: 'Contacts' })).toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(3);
  });

  it('exposes sortable headings and toggles the requested sort direction', async () => {
    const user = userEvent.setup();
    const onSortChange = vi.fn();
    render(
      <CommandDataTable
        ariaLabel="Contacts"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.id}
        sort={{ key: 'name', direction: 'ascending' }}
        onSortChange={onSortChange}
      />,
    );

    const nameHeading = screen.getByRole('columnheader', { name: /Name/ });
    expect(nameHeading).toHaveAttribute('aria-sort', 'ascending');
    const sortButton = within(nameHeading).getByRole('button', { name: 'Sort by Name' });
    expect(sortButton).toHaveClass('command-touch-target');
    await user.click(sortButton);
    expect(onSortChange).toHaveBeenCalledWith({ key: 'name', direction: 'descending' });
    expect(screen.getByRole('columnheader', { name: /Stage/ })).toHaveAttribute('aria-sort', 'none');
  });

  it('supports indeterminate select-all, complete selection, and the bulk-action region', async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();
    const view = render(
      <CommandDataTable
        ariaLabel="Contacts"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.id}
        selectedKeys={['1']}
        onSelectionChange={onSelectionChange}
        bulkActions={<button type="button">Archive selected</button>}
      />,
    );

    const selectAll = screen.getByRole('checkbox', { name: 'Select all Contacts rows' });
    expect(selectAll.closest('label')).toHaveClass(
      'command-checkbox-target',
      'command-touch-target',
    );
    expect(screen.getByRole('checkbox', { name: 'Select row 1' }).closest('label')).toHaveClass(
      'command-checkbox-target',
      'command-touch-target',
    );
    expect(selectAll).toBePartiallyChecked();
    expect(screen.getByRole('region', { name: 'Bulk actions' })).toHaveTextContent(
      '1 selected',
    );
    await user.click(selectAll);
    expect(onSelectionChange).toHaveBeenCalledWith(['1', '2']);

    view.rerender(
      <CommandDataTable
        ariaLabel="Contacts"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.id}
        selectedKeys={['1', '2']}
        onSelectionChange={onSelectionChange}
      />,
    );
    await user.click(screen.getByRole('checkbox', { name: 'Select all Contacts rows' }));
    expect(onSelectionChange).toHaveBeenLastCalledWith([]);
  });

  it('renders toolbar and empty content without losing table semantics', () => {
    render(
      <CommandDataTable
        ariaLabel="Contacts"
        columns={columns}
        rows={[]}
        rowKey={(row) => row.id}
        toolbar={<button type="button">Filter contacts</button>}
        emptyState={<p>No contacts match these filters.</p>}
      />,
    );

    expect(screen.getByRole('region', { name: 'Contacts tools' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Contacts' })).toBeInTheDocument();
    expect(screen.getByText('No contacts match these filters.')).toBeInTheDocument();
  });

  it('activates a row with click and Enter when row activation is supplied', async () => {
    const user = userEvent.setup();
    const onRowActivate = vi.fn();
    render(
      <CommandDataTable
        ariaLabel="Contacts"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.id}
        onRowActivate={onRowActivate}
        rowActionLabel={(row) => `Open ${row.name}`}
      />,
    );

    const row = screen.getByRole('row', { name: /Avery Lake/ });
    await user.click(row);
    expect(onRowActivate).toHaveBeenCalledWith(rows[0]);
    row.focus();
    await user.keyboard('{Enter}');
    expect(onRowActivate).toHaveBeenCalledTimes(2);
    const action = screen.getByRole('button', { name: 'Open Avery Lake' });
    expect(action).toHaveClass('command-touch-target');
    await user.click(action);
    expect(onRowActivate).toHaveBeenCalledTimes(3);
  });

  it('does not activate a row when an interactive cell descendant is used', async () => {
    const user = userEvent.setup();
    const onRowActivate = vi.fn();
    render(
      <CommandDataTable
        ariaLabel="Contacts"
        columns={[
          ...columns,
          {
            key: 'inline-action',
            header: 'Inline action',
            render: () => <button type="button">Send message</button>,
          },
        ]}
        rows={rows}
        rowKey={(row) => row.id}
        onRowActivate={onRowActivate}
        rowActionLabel={(row) => `Open ${row.name}`}
      />,
    );

    await user.click(screen.getAllByRole('button', { name: 'Send message' })[0]);
    expect(onRowActivate).not.toHaveBeenCalled();
  });

  it.each([
    ['loading', 'Loading contacts', 'Retrieving verified records', 'status'],
    ['first_run', 'Start your workspace', 'Import or create the first record', null],
    ['empty', 'No tasks', 'Nothing matches this view', null],
    ['evidence_only', 'Aggregate only', 'No distinct records were exposed', null],
    ['partial_capture', 'Partial history', 'Some source details were not exposed', null],
  ] as const)('renders the %s state with its truthful semantics', (kind, title, message, role) => {
    render(<CommandStatePanel kind={kind} title={title} message={message} />);
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
    if (role) expect(screen.getByRole(role, { name: title })).toBeInTheDocument();
  });

  it('renders loading placeholders as decorative skeletons without duplicating announcements', () => {
    const { container } = render(
      <CommandStatePanel
        kind="loading"
        title="Loading contacts"
        message="Retrieving verified records"
      />,
    );

    const skeleton = container.querySelector('.command-state-skeleton');
    expect(skeleton).toHaveAttribute('aria-hidden', 'true');
    expect(skeleton?.querySelectorAll('.command-state-skeleton-line')).toHaveLength(3);
    expect(screen.getAllByRole('status')).toHaveLength(1);
  });

  it('renders errors assertively and invokes the explicit Retry callback', async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(
      <CommandStatePanel
        kind="error"
        title="Contacts unavailable"
        message="The verified records could not be loaded."
        actionLabel="Retry"
        onAction={onAction}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Contacts unavailable');
    const retry = screen.getByRole('button', { name: 'Retry' });
    expect(retry).toHaveClass('command-touch-target');
    await user.click(retry);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it('restores focus after a drawer closes and announces an error toast assertively', async () => {
    const user = userEvent.setup();
    render(
      <CommandToastProvider>
        <OverlayAndToastProbe />
      </CommandToastProvider>,
    );

    const trigger = screen.getByRole('button', { name: 'Open detail' });
    await user.click(trigger);
    expect(screen.getByRole('dialog', { name: 'Detail' })).toHaveClass('command-overlay-drawer');
    expect(screen.getByRole('button', { name: 'Close detail' })).toHaveClass(
      'command-touch-target',
    );
    expect(document.body.style.overflow).toBe('hidden');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Detail' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(document.body.style.overflow).toBe('');
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to save');
    expect(screen.getByRole('button', { name: 'Dismiss Unable to save' })).toHaveClass(
      'command-touch-target',
    );
  });

  it('announces success politely without creating an assertive error region', async () => {
    const user = userEvent.setup();
    render(
      <CommandToastProvider>
        <SuccessToastProbe />
      </CommandToastProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'Save task' }));
    expect(screen.getByRole('status')).toHaveTextContent('Task saved');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('never exposes Undo for an error toast even if malformed runtime data supplies it', async () => {
    const user = userEvent.setup();
    render(
      <CommandToastProvider>
        <InvalidErrorUndoProbe />
      </CommandToastProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'Fail save' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Save failed');
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
  });

  it('renders a dense module header with breadcrumbs, actions, tabs, and tools', () => {
    render(
      <CommandModuleHeader
        breadcrumbs={[{ label: 'Command', href: '/admin/command' }, { label: 'Contacts' }]}
        title="Contacts"
        description="Recovered and internal CRM records"
        actions={<button type="button">Add contact</button>}
        tabs={<div role="tablist" aria-label="Contact views" />}
        toolbar={<button type="button">Filter</button>}
      />,
    );

    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Contacts' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Contacts actions' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Contacts tools' })).toBeInTheDocument();
  });
});
