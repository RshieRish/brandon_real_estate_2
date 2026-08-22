import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useCommandToast } from '../ui/CommandToastProvider';
import { CommandShell } from './CommandShell';

const mockRouterPush = vi.fn();
let mockPathname = '/admin/command';

vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ push: mockRouterPush, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

function ToastProbe() {
  const { pushToast } = useCommandToast();
  return (
    <button
      type="button"
      onClick={() => pushToast({ tone: 'success', message: 'Contact saved' })}
    >
      Show toast
    </button>
  );
}

describe('CommandShell', () => {
  beforeEach(() => {
    mockPathname = '/admin/command';
    mockRouterPush.mockReset();
    document.body.style.overflow = '';
  });

  it('renders the persistent rail, utility header, light canvas, and exact active Home route', () => {
    render(
      <CommandShell>
        <h1>Home body</h1>
      </CommandShell>,
    );

    expect(screen.getByRole('navigation', { name: 'Command modules' })).toBeInTheDocument();
    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveClass('command-main');
    expect(screen.getByText('Home body')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Create task' })).toHaveAttribute(
      'href',
      '/admin/command?create=task',
    );
    expect(screen.queryByRole('button', { name: 'Notifications' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Get Command help' })).toHaveAttribute(
      'href',
      'mailto:info@soldwithsweeney.com?subject=Command%20workspace%20help',
    );
    expect(screen.getByRole('link', { name: 'Brandon account settings' })).toHaveAttribute(
      'href',
      '/admin/settings',
    );
  });

  it('places the skip link first in the keyboard focus order', async () => {
    const user = userEvent.setup();
    render(
      <CommandShell>
        <p>Body</p>
      </CommandShell>,
    );

    await user.tab();

    expect(screen.getByRole('link', { name: 'Skip to workspace content' })).toHaveFocus();
  });

  it('matches nested module routes without leaving Home active', () => {
    mockPathname = '/admin/command/contacts/42';
    render(
      <CommandShell>
        <p>Contact detail</p>
      </CommandShell>,
    );

    expect(screen.getByRole('link', { name: 'Contacts' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('link', { name: 'Home' })).not.toHaveAttribute('aria-current');
    expect(screen.queryByRole('link', { name: 'Create task' })).not.toBeInTheDocument();
  });

  it('drives task review through the desktop rail, expanded rail, mobile drawer, search, and utility context', async () => {
    const user = userEvent.setup();
    mockPathname = '/admin/command/task-suggestions';
    render(
      <CommandShell>
        <p>Task review body</p>
      </CommandShell>,
    );

    const desktop = screen.getByRole('navigation', { name: 'Command modules' });
    expect(within(desktop).getByRole('link', { name: 'Task review' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('banner')).toHaveTextContent('Review');

    await user.click(screen.getByRole('button', { name: 'Expand Command navigation' }));
    const expanded = screen.getByRole('dialog', { name: 'Expanded Command navigation' });
    expect(within(expanded).getByRole('link', { name: 'Task review' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await user.click(screen.getByRole('button', { name: 'Collapse Command navigation' }));

    await user.click(screen.getByRole('button', { name: 'Open Command navigation' }));
    const mobile = screen.getByRole('dialog', { name: 'Command navigation' });
    expect(within(mobile).getByRole('link', { name: 'Task review' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await user.click(screen.getByRole('button', { name: 'Close Command navigation' }));

    await user.click(screen.getByRole('button', { name: 'Search Command' }));
    await user.type(screen.getByRole('combobox', { name: 'Search Command' }), 'Sydney');
    expect(screen.getByRole('option', { name: 'Task review' })).toBeInTheDocument();
  });

  it('opens global search with Control+K and navigates the filtered result by keyboard', async () => {
    const user = userEvent.setup();
    render(
      <CommandShell>
        <p>Body</p>
      </CommandShell>,
    );

    await user.keyboard('{Control>}k{/Control}');
    const search = screen.getByRole('combobox', { name: 'Search Command' });
    expect(search).toHaveFocus();
    expect(search).toHaveClass('command-search-input');
    expect(screen.getByRole('button', { name: 'Close search' })).toHaveClass(
      'command-touch-target',
    );
    await user.type(search, 'todo');
    expect(screen.getByRole('option', { name: 'Tasks' })).toBeInTheDocument();
    await user.keyboard('{ArrowDown}{Enter}');

    expect(mockRouterPush).toHaveBeenCalledWith('/admin/command/tasks');
    expect(screen.queryByRole('dialog', { name: 'Search Command' })).not.toBeInTheDocument();
  });

  it('supports Command+K, ArrowUp, and Escape while restoring search-trigger focus', async () => {
    const user = userEvent.setup();
    render(
      <CommandShell>
        <p>Body</p>
      </CommandShell>,
    );

    const trigger = screen.getByRole('button', { name: 'Search Command' });
    trigger.focus();
    await user.keyboard('{Meta>}k{/Meta}');
    await user.keyboard('{ArrowUp}');
    expect(screen.getByRole('option', { name: 'Saved Searches' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Search Command' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('expands and collapses the desktop navigation overlay without shifting the canvas', async () => {
    const user = userEvent.setup();
    render(
      <CommandShell>
        <p>Body</p>
      </CommandShell>,
    );

    const trigger = screen.getByRole('button', { name: 'Expand Command navigation' });
    const canvas = screen.getByRole('main').parentElement;
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await user.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('command-rail-overlay')).toHaveClass('command-rail-overlay');
    expect(canvas).toHaveClass('command-canvas');
    await user.click(screen.getByRole('button', { name: 'Collapse Command navigation' }));
    expect(screen.queryByTestId('command-rail-overlay')).not.toBeInTheDocument();
  });

  it('contains expanded-rail focus, closes with Escape, and restores its trigger and scrolling', async () => {
    const user = userEvent.setup();
    render(
      <CommandShell>
        <p>Body</p>
      </CommandShell>,
    );

    const trigger = screen.getByRole('button', { name: 'Expand Command navigation' });
    const baseRail = screen.getByRole('complementary');
    const canvas = screen.getByRole('main').parentElement;
    await user.click(trigger);
    const overlay = screen.getByRole('dialog', { name: 'Expanded Command navigation' });
    expect(overlay).toHaveAttribute('aria-modal', 'true');
    expect(canvas).toHaveAttribute('aria-hidden', 'true');
    expect(canvas).toHaveAttribute('inert');
    expect(baseRail).toHaveAttribute('aria-hidden', 'true');
    expect(baseRail).toHaveAttribute('inert');
    await waitFor(() => expect(overlay).toContainElement(document.activeElement as HTMLElement));
    expect(document.body.style.overflow).toBe('hidden');
    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(overlay).toContainElement(document.activeElement as HTMLElement);
    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('command-rail-overlay')).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe('');
    expect(canvas).not.toHaveAttribute('aria-hidden');
    expect(canvas).not.toHaveAttribute('inert');
    expect(baseRail).not.toHaveAttribute('aria-hidden');
    expect(baseRail).not.toHaveAttribute('inert');
    expect(trigger).toHaveFocus();
  });

  it('closes the mobile drawer with Escape, restores focus, and restores body scrolling', async () => {
    const user = userEvent.setup();
    render(
      <CommandShell>
        <p>Body</p>
      </CommandShell>,
    );

    const trigger = screen.getByRole('button', { name: 'Open Command navigation' });
    await user.click(trigger);
    expect(screen.getByRole('dialog', { name: 'Command navigation' })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe('hidden');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Command navigation' })).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe('');
    expect(trigger).toHaveFocus();
  });

  it('contains focus inside the mobile drawer and closes it after navigation', async () => {
    const user = userEvent.setup();
    render(
      <CommandShell>
        <p>Body</p>
      </CommandShell>,
    );

    await user.click(screen.getByRole('button', { name: 'Open Command navigation' }));
    const dialog = screen.getByRole('dialog', { name: 'Command navigation' });
    const close = screen.getByRole('button', { name: 'Close Command navigation' });
    await waitFor(() => expect(close).toHaveFocus());
    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    const taskLink = within(dialog).getByRole('link', { name: 'Tasks' });
    taskLink.addEventListener('click', (event) => event.preventDefault());
    await user.click(taskLink);
    expect(screen.queryByRole('dialog', { name: 'Command navigation' })).not.toBeInTheDocument();
  });

  it('closes open navigation overlays when the route changes', async () => {
    const user = userEvent.setup();
    const view = render(
      <CommandShell>
        <p>Body</p>
      </CommandShell>,
    );

    await user.click(screen.getByRole('button', { name: 'Open Command navigation' }));
    expect(screen.getByRole('dialog', { name: 'Command navigation' })).toBeInTheDocument();
    mockPathname = '/admin/command/tasks';
    view.rerender(
      <CommandShell>
        <p>Tasks body</p>
      </CommandShell>,
    );
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Command navigation' })).not.toBeInTheDocument(),
    );
  });

  it('owns one persistent toast provider across route changes', async () => {
    const user = userEvent.setup();
    const view = render(
      <CommandShell>
        <ToastProbe />
      </CommandShell>,
    );

    await user.click(screen.getByRole('button', { name: 'Show toast' }));
    const status = screen.getByRole('status');
    expect(within(status).getByText('Contact saved')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Dismiss Contact saved' })).toHaveLength(1);
    expect(view.container.querySelectorAll('.command-toast-viewport')).toHaveLength(1);
    expect(view.container.querySelector('.command-toast-viewport')?.closest('.command-root')).not.toBeNull();

    mockPathname = '/admin/command/contacts';
    view.rerender(
      <CommandShell>
        <ToastProbe />
      </CommandShell>,
    );

    expect(view.container.querySelectorAll('.command-toast-viewport')).toHaveLength(1);
    expect(screen.getAllByText('Contact saved')).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: 'Dismiss Contact saved' }));
    expect(screen.queryByText('Contact saved')).not.toBeInTheDocument();
  });

  it('ships only Sold With Sweeney shell branding', () => {
    const { container } = render(
      <CommandShell>
        <p>Body</p>
      </CommandShell>,
    );

    expect(screen.getByLabelText('Sold With Sweeney workspace')).toBeInTheDocument();
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
