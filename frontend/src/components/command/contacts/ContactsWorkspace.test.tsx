import { StrictMode } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  ContactCreated,
  ContactDirectoryPage,
  ContactDirectoryRow,
  ContactsApi,
} from '@/lib/command/contacts';
import { CommandToastProvider } from '../ui/CommandToastProvider';
import { ContactsWorkspace } from '../ContactsWorkspace';

const navigation = vi.hoisted(() => ({
  pathname: '/admin/command/contacts',
  push: vi.fn(),
  replace: vi.fn(),
  search: new URLSearchParams(),
}));

const viewport = vi.hoisted(() => ({ width: 1800 }));

vi.mock('next/navigation', () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push, replace: navigation.replace }),
  useSearchParams: () => navigation.search,
}));

const ada: ContactDirectoryRow = {
  id: 7,
  first_name: 'Ada',
  last_name: 'Lovelace',
  display_name: 'Ada Lovelace',
  primary_email: 'ada@example.com',
  primary_phone: '555-0107',
  stage: 'client',
  lead_backed: true,
  origins: ['lead_backed'],
  sources: ['legacy_lead'],
  health_score: 84,
  last_contacted_at: '2026-08-01T12:00:00.000Z',
  last_interaction_at: '2026-08-12T12:00:00.000Z',
  owner: { role: 'owner', provider_actor_id: 'owner-1', display_name: 'Brandon Sweeney' },
  assignee: null,
  tags: [{ id: 3, name: 'VIP' }],
  birthday: null,
  anniversary: null,
  evidence_quality: null,
};

const grace: ContactDirectoryRow = {
  ...ada,
  id: 2,
  first_name: 'Grace',
  last_name: 'Hopper',
  display_name: 'Grace Hopper',
  primary_email: null,
  primary_phone: null,
  lead_backed: false,
  origins: ['recovered'],
  sources: ['kw_command'],
  health_score: null,
  owner: null,
  tags: [],
  evidence_quality: null,
};

function page(
  rows: readonly ContactDirectoryRow[] = [ada, grace],
  total = rows.length,
): ContactDirectoryPage {
  return {
    rows,
    total,
    page: 1,
    page_size: 50,
    page_count: total === 0 ? 0 : Math.ceil(total / 50),
    sort: 'name',
    direction: 'asc',
  };
}

function created(id = 19): ContactCreated {
  return {
    id,
    first_name: 'New',
    last_name: 'Contact',
    email: 'new@example.com',
    phone: null,
    lead_id: null,
    birthday: null,
    anniversary: null,
    stage: 'lead',
  };
}

function fakeApi(directoryResult: ContactDirectoryPage | Promise<ContactDirectoryPage> = page()): ContactsApi {
  return {
    directory: vi.fn().mockImplementation(() => Promise.resolve(directoryResult)),
    detail: vi.fn(),
    neighbors: vi.fn(),
    workspace: vi.fn(),
    timeline: vi.fn(),
    section: vi.fn(),
    evidence: vi.fn(),
    celebrations: vi.fn(),
    create: vi.fn().mockResolvedValue(created()),
    update: vi.fn(),
    bulk: vi.fn().mockResolvedValue({
      requested_contact_ids: [2, 7],
      actioned_contact_ids: [2, 7],
      action: 'set_stage',
    }),
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function renderWorkspace(
  api: ContactsApi,
  options: Readonly<{ strict?: boolean; initialView?: 'all' | 'never_contacted' }> = {},
) {
  const content = workspaceContent(api, options.initialView);
  return render(options.strict ? <StrictMode>{content}</StrictMode> : content);
}

function workspaceContent(
  api: ContactsApi,
  initialView: 'all' | 'never_contacted' | undefined = undefined,
) {
  return (
    <CommandToastProvider>
      <ContactsWorkspace api={api} initialView={initialView} />
    </CommandToastProvider>
  );
}

describe('ContactsWorkspace', () => {
  beforeEach(() => {
    navigation.pathname = '/admin/command/contacts';
    navigation.search = new URLSearchParams();
    navigation.push.mockReset();
    navigation.replace.mockReset();
    viewport.width = 1800;
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn((query: string) => ({
        matches: query.includes('767') ? viewport.width <= 767 : viewport.width <= 1100,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
    vi.useRealTimers();
  });

  it('renders a dense server-backed directory with exact total, controls, columns, and geometry hooks', async () => {
    const api = fakeApi(page([ada, grace], 318));
    renderWorkspace(api);

    expect(await screen.findByRole('heading', { name: 'Contacts' })).toBeInTheDocument();
    expect(screen.getByText('318 contacts')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'All contacts' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', 'contact-smart-view-tab-all');
    for (const tab of screen.getAllByRole('tab')) {
      const panelId = tab.getAttribute('aria-controls');
      expect(panelId).not.toBeNull();
      expect(document.getElementById(panelId as string)).not.toBeNull();
    }
    expect(screen.getByRole('searchbox', { name: 'Search contacts' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Filter contacts' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Choose columns' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add Contact' })).toHaveClass('command-print-hidden');
    expect(screen.getByRole('button', { name: 'Next page' })).toBeInTheDocument();

    const table = screen.getByRole('table', { name: 'Contacts directory' });
    expect(within(table).getByText('Contacts directory')).toHaveClass('command-visually-hidden');
    expect(within(table).getByRole('columnheader', { name: 'Name' })).toHaveClass('command-contacts-name-column');
    expect(within(table).getByRole('columnheader', { name: 'Name' }).parentElement).toHaveClass('command-contacts-table-head');
    expect(ada.display_name && within(table).getByRole('checkbox', { name: `Select ${ada.display_name}` })).toBeInTheDocument();
    for (const header of [
      'Name', 'Primary contact', 'Owner / Assignee', 'Tags', 'Stage', 'Health',
      'Last activity', 'Origin / source', 'Actions',
    ]) expect(within(table).getByRole('columnheader', { name: header })).toBeInTheDocument();
    expect(within(table).getByText('Ada Lovelace').closest('tr')).toHaveClass('command-contacts-row');
    expect(document.querySelector('.command-contact-card')).toBeNull();
    expect(api.directory).toHaveBeenCalledTimes(1);
    expect(api.directory).toHaveBeenCalledWith({
      smart_view: 'all', sort: 'name', direction: 'asc', page: 1, page_size: 50,
    }, { signal: expect.any(AbortSignal) });
  });

  it('makes responsive hidden-column defaults truthful and reveals an explicit picker choice', async () => {
    viewport.width = 1000;
    const user = userEvent.setup();
    renderWorkspace(fakeApi(page([ada], 1)));
    await screen.findByText('Ada Lovelace');

    expect(screen.queryByRole('columnheader', { name: 'Owner / Assignee' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Choose columns' }));
    const ownerChoice = screen.getByRole('checkbox', { name: 'Owner / Assignee' });
    expect(ownerChoice).not.toBeChecked();

    await user.click(ownerChoice);

    expect(ownerChoice).toBeChecked();
    expect(screen.getByRole('columnheader', { name: 'Owner / Assignee' })).toBeInTheDocument();
  });

  it('commits trimmed search at exactly 250ms, aborts the old request, and ignores stale success', async () => {
    vi.useFakeTimers();
    const initial = deferred<ContactDirectoryPage>();
    const latest = deferred<ContactDirectoryPage>();
    const api = fakeApi();
    vi.mocked(api.directory)
      .mockImplementationOnce((_request, options) => {
        options?.signal?.addEventListener('abort', () => undefined);
        return initial.promise;
      })
      .mockImplementationOnce(() => latest.promise);
    renderWorkspace(api);
    const initialSignal = vi.mocked(api.directory).mock.calls[0]?.[1]?.signal;

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search contacts' }), {
      target: { value: '  Grace  ' },
    });
    act(() => vi.advanceTimersByTime(249));
    expect(api.directory).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(1));
    expect(api.directory).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.directory).mock.calls[1]?.[0]).toMatchObject({ query: 'Grace', page: 1 });
    expect(initialSignal?.aborted).toBe(true);

    await act(async () => latest.resolve(page([grace], 1)));
    expect(screen.getByText('Grace Hopper')).toBeInTheDocument();
    await act(async () => initial.resolve(page([ada], 1)));
    expect(screen.queryByText('Ada Lovelace')).not.toBeInTheDocument();
  });

  it('does not restart the 250ms search timer when another filter changes', async () => {
    vi.useFakeTimers();
    const api = fakeApi(page());
    renderWorkspace(api);

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search contacts' }), {
      target: { value: 'Grace' },
    });
    act(() => vi.advanceTimersByTime(200));
    fireEvent.click(screen.getByRole('button', { name: 'Filter contacts' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Stage' }), {
      target: { value: 'zebra' },
    });
    act(() => vi.advanceTimersByTime(49));
    expect(api.directory).toHaveBeenCalledTimes(2);
    act(() => vi.advanceTimersByTime(1));
    expect(api.directory).toHaveBeenCalledTimes(3);
    expect(api.directory).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: 'Grace', stage: 'zebra' }),
      { signal: expect.any(AbortSignal) },
    );
  });

  it('accepts normalized Unicode bounds and refuses an over-bound search before fetch', () => {
    vi.useFakeTimers();
    const api = fakeApi(page());
    renderWorkspace(api);
    const search = screen.getByRole('searchbox', { name: 'Search contacts' });
    const maximum = '😀'.repeat(200);

    fireEvent.change(search, { target: { value: ` ${maximum} ` } });
    act(() => vi.advanceTimersByTime(250));
    expect(api.directory).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: maximum }),
      { signal: expect.any(AbortSignal) },
    );
    const acceptedCalls = vi.mocked(api.directory).mock.calls.length;

    fireEvent.change(search, { target: { value: ` ${'😀'.repeat(201)} ` } });
    act(() => vi.advanceTimersByTime(250));
    expect(api.directory).toHaveBeenCalledTimes(acceptedCalls);
  });

  it('does not refetch or become busy for a semantically identical selected SmartView', async () => {
    const user = userEvent.setup();
    const api = fakeApi(page([ada], 1));
    renderWorkspace(api);
    const table = await screen.findByRole('table', { name: 'Contacts directory' });

    await user.click(screen.getByRole('tab', { name: 'All contacts' }));

    expect(api.directory).toHaveBeenCalledTimes(1);
    expect(table).not.toHaveAttribute('aria-busy');
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
  });

  it('does not restart a settled request when the router commits its canonical URL', async () => {
    const api = fakeApi(page([ada], 1));
    const view = renderWorkspace(api);
    const table = await screen.findByRole('table', { name: 'Contacts directory' });

    navigation.search = new URLSearchParams('page=1&page_size=50');
    view.rerender(workspaceContent(api));

    expect(api.directory).toHaveBeenCalledTimes(1);
    expect(table).not.toHaveAttribute('aria-busy');
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
  });

  it('treats a nondefault optimistic request and canonical URL parse as one request', async () => {
    const user = userEvent.setup();
    const api = fakeApi(page([ada], 1));
    const view = renderWorkspace(api);
    await screen.findByText('Ada Lovelace');
    await user.click(screen.getByRole('button', { name: 'Filter contacts' }));
    const filters = screen.getByRole('dialog', { name: 'Contact filters' });

    fireEvent.change(within(filters).getByLabelText('Stage'), { target: { value: 'zebra' } });
    await waitFor(() => expect(api.directory).toHaveBeenCalledTimes(2));
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();

    navigation.search = new URLSearchParams('stage=zebra&page=1&page_size=50');
    view.rerender(workspaceContent(api));

    expect(api.directory).toHaveBeenCalledTimes(2);
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
  });

  it('removes old-universe rows synchronously when canonical filters change', async () => {
    const api = fakeApi(page([ada], 1));
    vi.mocked(api.directory).mockResolvedValueOnce(page([ada], 1)).mockImplementationOnce(
      () => new Promise(() => undefined),
    );
    const view = renderWorkspace(api);
    await screen.findByText('Ada Lovelace');

    navigation.search = new URLSearchParams('stage=zebra&page=1&page_size=50');
    view.rerender(workspaceContent(api));

    expect(screen.queryByText('Ada Lovelace')).not.toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Loading contacts' })).toBeInTheDocument();
  });

  it('uses the current pending request when toggling the same sort twice', async () => {
    const user = userEvent.setup();
    const firstSort = deferred<ContactDirectoryPage>();
    const secondSort = deferred<ContactDirectoryPage>();
    const api = fakeApi(page([ada], 1));
    vi.mocked(api.directory)
      .mockResolvedValueOnce(page([ada], 1))
      .mockReturnValueOnce(firstSort.promise)
      .mockReturnValueOnce(secondSort.promise);
    renderWorkspace(api);
    await screen.findByText('Ada Lovelace');

    await user.click(screen.getByRole('button', { name: 'Sort by Stage' }));
    await user.click(screen.getByRole('button', { name: 'Sort by Stage' }));

    expect(vi.mocked(api.directory).mock.calls[1]?.[0]).toMatchObject({
      sort: 'stage', direction: 'asc',
    });
    expect(vi.mocked(api.directory).mock.calls[2]?.[0]).toMatchObject({
      sort: 'stage', direction: 'desc',
    });
  });

  it('performs one initial request in Strict Mode and aborts silently after true unmount', async () => {
    const pending = deferred<ContactDirectoryPage>();
    const api = fakeApi(pending.promise);
    const view = renderWorkspace(api, { strict: true });

    expect(api.directory).toHaveBeenCalledTimes(1);
    const signal = vi.mocked(api.directory).mock.calls[0]?.[1]?.signal;
    view.unmount();
    await act(async () => Promise.resolve());
    expect(signal?.aborted).toBe(true);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('supports retry with a fresh request while retaining prior rows during page refresh', async () => {
    const api = fakeApi();
    vi.mocked(api.directory)
      .mockRejectedValueOnce(new Error('Directory offline'))
      .mockResolvedValueOnce(page([ada], 51))
      .mockImplementationOnce(() => new Promise(() => undefined));
    renderWorkspace(api);

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load contacts');
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getByRole('table', { name: 'Contacts directory' })).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
  });

  it('retains prior rows while a page-size refresh is pending', async () => {
    const user = userEvent.setup();
    const pending = deferred<ContactDirectoryPage>();
    const api = fakeApi();
    vi.mocked(api.directory)
      .mockResolvedValueOnce(page([ada], 120))
      .mockReturnValueOnce(pending.promise);
    renderWorkspace(api);
    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();

    await user.selectOptions(screen.getByRole('combobox', { name: 'Rows per page' }), '100');
    expect(screen.getByRole('table', { name: 'Contacts directory' })).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
  });

  it('derives pending pagination from retained total and the current page size', async () => {
    const user = userEvent.setup();
    const sizeRefresh = deferred<ContactDirectoryPage>();
    const secondPage = deferred<ContactDirectoryPage>();
    const api = fakeApi();
    vi.mocked(api.directory)
      .mockResolvedValueOnce(page([ada], 120))
      .mockReturnValueOnce(sizeRefresh.promise)
      .mockReturnValueOnce(secondPage.promise);
    renderWorkspace(api);
    await screen.findByText('Ada Lovelace');

    await user.selectOptions(screen.getByRole('combobox', { name: 'Rows per page' }), '100');
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled();
    expect(api.directory).toHaveBeenCalledTimes(3);
  });

  it('recovers an out-of-range server page without claiming the directory is empty', async () => {
    navigation.search = new URLSearchParams('page=999&page_size=50');
    const availablePage = deferred<ContactDirectoryPage>();
    const api = fakeApi();
    vi.mocked(api.directory)
      .mockResolvedValueOnce({ ...page([], 120), page: 999 })
      .mockReturnValueOnce(availablePage.promise);
    renderWorkspace(api);

    expect(await screen.findByText('Loading an available contact page')).toBeInTheDocument();
    expect(screen.queryByText('No contacts yet')).not.toBeInTheDocument();
    await waitFor(() => expect(api.directory).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 3, page_size: 50 }),
      { signal: expect.any(AbortSignal) },
    ));
    await act(async () => availablePage.resolve({ ...page([ada], 120), page: 3 }));
    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
  });

  it('clears aria-busy after a retained-page refresh fails', async () => {
    const user = userEvent.setup();
    const failed = deferred<ContactDirectoryPage>();
    const api = fakeApi();
    vi.mocked(api.directory)
      .mockResolvedValueOnce(page([ada], 51))
      .mockReturnValueOnce(failed.promise);
    renderWorkspace(api);
    const table = await screen.findByRole('table', { name: 'Contacts directory' });

    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(table).toHaveAttribute('aria-busy', 'true');
    await act(async () => failed.reject(new Error('PLANTED_PRIVATE_REFRESH_ERROR')));
    expect(await screen.findByRole('alert')).toHaveTextContent('Refresh failed');
    expect(table).not.toHaveAttribute('aria-busy');
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('PLANTED_PRIVATE_REFRESH_ERROR');
  });

  it('navigates a row by pointer, Enter, and Space without activating from nested controls', async () => {
    const user = userEvent.setup();
    renderWorkspace(fakeApi(page([ada], 1)));
    const row = (await screen.findByText('Ada Lovelace')).closest('tr');
    expect(row).not.toBeNull();

    await user.click(within(row as HTMLElement).getByRole('checkbox', { name: 'Select Ada Lovelace' }));
    expect(navigation.push).not.toHaveBeenCalled();
    fireEvent.keyDown(row as HTMLElement, { key: 'Enter' });
    expect(navigation.push).toHaveBeenLastCalledWith('/admin/command/contacts/7');
    fireEvent.keyDown(row as HTMLElement, { key: ' ' });
    expect(navigation.push).toHaveBeenLastCalledWith('/admin/command/contacts/7');
    await user.click(row as HTMLElement);
    expect(navigation.push).toHaveBeenLastCalledWith('/admin/command/contacts/7');
    await user.click(within(row as HTMLElement).getByRole('button', { name: 'Open Ada Lovelace' }));
    expect(navigation.push).toHaveBeenCalledTimes(4);
  });

  it('limits selection to visible IDs and sends sorted explicit bulk commands once', async () => {
    const user = userEvent.setup();
    const api = fakeApi(page([ada, grace], 2));
    renderWorkspace(api);
    const selectPage = await screen.findByRole('checkbox', { name: 'Select all contacts on this page' });
    await user.click(selectPage);
    expect(selectPage).toBeChecked();
    await user.click(screen.getByRole('checkbox', { name: 'Select Ada Lovelace' }));
    expect(selectPage).not.toBeChecked();
    expect((selectPage as HTMLInputElement).indeterminate).toBe(true);
    await user.click(screen.getByRole('checkbox', { name: 'Select Ada Lovelace' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Bulk action' }), 'set_stage');
    await user.clear(screen.getByRole('combobox', { name: 'Bulk stage' }));
    await user.type(screen.getByRole('combobox', { name: 'Bulk stage' }), 'zebra');
    await user.click(screen.getByRole('button', { name: 'Apply bulk action' }));

    await waitFor(() => expect(api.bulk).toHaveBeenCalledTimes(1));
    expect(api.bulk).toHaveBeenCalledWith({
      contact_ids: [2, 7], action: { action: 'set_stage', stage: 'zebra' },
    }, { signal: expect.any(AbortSignal) });
    expect(await screen.findByText('2 contacts updated')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Bulk contact actions' })).not.toBeInTheDocument();
    expect(api.directory).toHaveBeenCalledTimes(2);
  });

  it('preserves selection and announces a conflict for rejected bulk tag actions', async () => {
    const user = userEvent.setup();
    const api = fakeApi(page([ada], 1));
    vi.mocked(api.bulk).mockRejectedValueOnce(new Error('409 conflicting contact state'));
    renderWorkspace(api);
    await user.click(await screen.findByRole('checkbox', { name: 'Select Ada Lovelace' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Bulk action' }), 'add_tag');
    await user.clear(screen.getByRole('spinbutton', { name: 'Tag ID' }));
    await user.type(screen.getByRole('spinbutton', { name: 'Tag ID' }), '3');
    await user.click(screen.getByRole('button', { name: 'Apply bulk action' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Contacts were not updated');
    expect(screen.getByRole('checkbox', { name: 'Select Ada Lovelace' })).toBeChecked();
    expect(api.bulk).toHaveBeenCalledWith({
      contact_ids: [7], action: { action: 'add_tag', tag_id: 3 },
    }, { signal: expect.any(AbortSignal) });
  });

  it('renders distinct skeleton, true-empty, filtered-empty, and exact recovered provenance states', async () => {
    const pending = deferred<ContactDirectoryPage>();
    const skeleton = renderWorkspace(fakeApi(pending.promise));
    expect(screen.getByRole('status', { name: 'Loading contacts' })).toBeInTheDocument();
    skeleton.unmount();

    renderWorkspace(fakeApi(page([], 0)));
    expect(await screen.findByText('No contacts yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add your first contact' })).toBeInTheDocument();

    navigation.search = new URLSearchParams('query=missing');
    const filtered = renderWorkspace(fakeApi(page([], 0)));
    expect(await screen.findByText('No contacts match these filters')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeInTheDocument();
    filtered.unmount();

    navigation.search = new URLSearchParams();
    renderWorkspace(fakeApi(page([grace], 1)));
    expect(await screen.findByText('Recovered')).toBeInTheDocument();
    expect(screen.getByText('KW Command source')).toBeInTheDocument();
    expect(screen.queryByText('Legacy only')).not.toBeInTheDocument();
    expect(screen.queryByText('Lead backed')).not.toBeInTheDocument();
  });

  it('shows all four provenance badges distinctly', async () => {
    const rows: ContactDirectoryRow[] = [
      { ...ada, id: 1, display_name: 'Recovered One', origins: ['recovered'], sources: ['kw_command'], lead_backed: false },
      { ...ada, id: 2, display_name: 'Lead Two', origins: ['lead_backed', 'recovered'], sources: ['kw_command', 'legacy_lead'], lead_backed: true },
      { ...ada, id: 3, display_name: 'Legacy Three', origins: ['lead_backed', 'legacy_only'], sources: ['legacy_lead'], lead_backed: true },
      { ...ada, id: 4, display_name: 'Internal Four', origins: ['internal_only'], sources: ['internal_crm'], lead_backed: false },
    ];
    renderWorkspace(fakeApi(page(rows, 4)));

    expect(await screen.findAllByText('Recovered')).toHaveLength(2);
    expect(screen.getAllByText('Lead backed')).toHaveLength(2);
    expect(screen.getByText('Legacy only')).toBeInTheDocument();
    expect(screen.getByText('Internal only')).toBeInTheDocument();
    expect(screen.getAllByText('KW Command source')).toHaveLength(2);
    expect(screen.getAllByText('Legacy lead source')).toHaveLength(2);
    expect(screen.getByText('Internal CRM source')).toBeInTheDocument();
  });

  it('commits SmartViews, sorting, pagination, page size, filters, and columns while clearing selection', async () => {
    const user = userEvent.setup();
    const api = fakeApi(page([ada, grace], 120));
    renderWorkspace(api);
    await screen.findByText('Ada Lovelace');
    await user.click(screen.getByRole('checkbox', { name: 'Select Ada Lovelace' }));

    await user.click(screen.getByRole('tab', { name: 'Never contacted' }));
    await waitFor(() => expect(api.directory).toHaveBeenLastCalledWith(
      expect.objectContaining({ smart_view: 'never_contacted', page: 1 }),
      { signal: expect.any(AbortSignal) },
    ));
    expect(screen.getByRole('checkbox', { name: 'Select Ada Lovelace' })).not.toBeChecked();
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toContain('smart_view=never_contacted');

    await user.click(screen.getByRole('button', { name: 'Sort by Stage' }));
    await waitFor(() => expect(api.directory).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort: 'stage', direction: 'asc', page: 1 }),
      { signal: expect.any(AbortSignal) },
    ));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Rows per page' }), '100');
    await waitFor(() => expect(api.directory).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, page_size: 100 }),
      { signal: expect.any(AbortSignal) },
    ));
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(api.directory).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2, page_size: 100 }),
      { signal: expect.any(AbortSignal) },
    ));

    await user.click(screen.getByRole('button', { name: 'Choose columns' }));
    await user.click(screen.getByRole('checkbox', { name: 'Owner / Assignee' }));
    expect(screen.queryByRole('columnheader', { name: 'Owner / Assignee' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Filter contacts' }));
    const filters = screen.getByRole('dialog', { name: 'Contact filters' });
    await user.type(within(filters).getByLabelText('Stage'), 'past client');
    await waitFor(() => expect(api.directory).toHaveBeenLastCalledWith(
      expect.objectContaining({ stage: 'past client', page: 1 }),
      { signal: expect.any(AbortSignal) },
    ));
    await user.type(within(filters).getByLabelText('Tag IDs'), '3, 8');
    await user.click(within(filters).getByRole('checkbox', { name: 'KW Command source' }));
    await user.click(within(filters).getByRole('checkbox', { name: 'Recovered origin' }));
    await user.selectOptions(within(filters).getByLabelText('Birthday month'), '8');
    await user.selectOptions(within(filters).getByLabelText('Anniversary month'), '9');
    await waitFor(() => expect(api.directory).toHaveBeenLastCalledWith(
      expect.objectContaining({
        stage: 'past client',
        tag: [3, 8],
        source: ['kw_command'],
        origin: ['recovered'],
        birthday_month: 8,
        anniversary_month: 9,
        page: 1,
      }),
      { signal: expect.any(AbortSignal) },
    ));
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toContain('stage=past+client');
  });

  it('does not rewrite a valid filter when a tag draft contains invalid tokens', async () => {
    const user = userEvent.setup();
    const api = fakeApi(page());
    renderWorkspace(api);
    await screen.findByText('Ada Lovelace');
    await user.click(screen.getByRole('button', { name: 'Filter contacts' }));
    const tagInput = screen.getByLabelText('Tag IDs');
    const requests = vi.mocked(api.directory).mock.calls.length;

    fireEvent.change(tagInput, { target: { value: '-3, 03, 8x' } });

    expect(api.directory).toHaveBeenCalledTimes(requests);
    expect(navigation.replace.mock.calls.at(-1)?.[0] ?? '').not.toContain('tag=');
  });

  it('reconciles open filter drafts when browser navigation changes the URL', async () => {
    navigation.search = new URLSearchParams('stage=lead&tag=3&page=1&page_size=50');
    const api = fakeApi(page());
    const view = renderWorkspace(api);
    await screen.findByText('Ada Lovelace');
    await userEvent.click(screen.getByRole('button', { name: 'Filter contacts' }));
    const filters = screen.getByRole('dialog', { name: 'Contact filters' });
    expect(within(filters).getByLabelText('Stage')).toHaveValue('lead');
    expect(within(filters).getByLabelText('Tag IDs')).toHaveValue('3');

    navigation.search = new URLSearchParams('stage=past+client&tag=8&page=1&page_size=50');
    view.rerender(workspaceContent(api));

    await waitFor(() => expect(within(filters).getByLabelText('Stage')).toHaveValue('past client'));
    expect(within(filters).getByLabelText('Tag IDs')).toHaveValue('8');
  });

  it('restores the true-empty trigger after closing the create drawer', async () => {
    const user = userEvent.setup();
    renderWorkspace(fakeApi(page([], 0)));
    const trigger = await screen.findByRole('button', { name: 'Add your first contact' });

    await user.click(trigger);
    await user.keyboard('{Escape}');

    expect(trigger).toHaveFocus();
  });

  it.each(['409 contact conflict', '422 invalid stage'])(
    'preserves selection and announces server bulk rejection for %s',
    async (message) => {
      const user = userEvent.setup();
      const api = fakeApi(page([ada], 1));
      vi.mocked(api.bulk).mockRejectedValueOnce(new Error(message));
      renderWorkspace(api);
      await user.click(await screen.findByRole('checkbox', { name: 'Select Ada Lovelace' }));
      await user.selectOptions(screen.getByRole('combobox', { name: 'Bulk action' }), 'set_stage');
      await user.clear(screen.getByRole('combobox', { name: 'Bulk stage' }));
      await user.type(screen.getByRole('combobox', { name: 'Bulk stage' }), 'active');
      await user.click(screen.getByRole('button', { name: 'Apply bulk action' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('Contacts were not updated');
      expect(screen.getByRole('checkbox', { name: 'Select Ada Lovelace' })).toBeChecked();
    },
  );

  it('treats every nondefault server filter as an active-filter empty state', async () => {
    navigation.search = new URLSearchParams('origin=legacy_only&page=1&page_size=50');
    renderWorkspace(fakeApi(page([], 0)));
    expect(await screen.findByText('No contacts match these filters')).toBeInTheDocument();
  });

  it('validates and creates only writable fields in a focus-contained drawer, then navigates', async () => {
    const user = userEvent.setup();
    const api = fakeApi(page([], 0));
    renderWorkspace(api);
    const trigger = await screen.findByRole('button', { name: 'Add Contact' });
    trigger.focus();
    await user.click(trigger);
    const dialog = screen.getByRole('dialog', { name: 'Add contact' });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/provider/i)).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Create contact' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('First name is required');
    await user.type(within(dialog).getByLabelText('First name'), 'New');
    await user.type(within(dialog).getByLabelText('Last name'), 'Contact');
    await user.type(within(dialog).getByLabelText('Email'), 'new@example.com');
    await user.type(within(dialog).getByLabelText('Phone'), '555-0199');
    await user.clear(within(dialog).getByLabelText('Stage'));
    await user.type(within(dialog).getByLabelText('Stage'), 'active');
    fireEvent.change(within(dialog).getByLabelText('Birthday'), { target: { value: '1990-08-13' } });
    fireEvent.change(within(dialog).getByLabelText('Anniversary'), { target: { value: '2020-08-13' } });
    await user.click(within(dialog).getByRole('button', { name: 'Create contact' }));

    await waitFor(() => expect(api.create).toHaveBeenCalledWith({
      first_name: 'New',
      last_name: 'Contact',
      email: 'new@example.com',
      phone: '555-0199',
      stage: 'active',
      birthday: '1990-08-13',
      anniversary: '2020-08-13',
    }, { signal: expect.any(AbortSignal) }));
    expect(await screen.findByText('New Contact created')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Add contact' })).not.toBeInTheDocument();
    expect(navigation.push).toHaveBeenCalledWith('/admin/command/contacts/19');
  });

  it('restores trigger focus on Escape but ignores Escape while create is submitting', async () => {
    const user = userEvent.setup();
    const create = deferred<ContactCreated>();
    const api = fakeApi(page([], 0));
    vi.mocked(api.create).mockReturnValue(create.promise);
    renderWorkspace(api);
    const trigger = await screen.findByRole('button', { name: 'Add Contact' });
    await user.click(trigger);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Add contact' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    const dialog = screen.getByRole('dialog', { name: 'Add contact' });
    await user.type(within(dialog).getByLabelText('First name'), 'Waiting');
    await user.click(within(dialog).getByRole('button', { name: 'Create contact' }));
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog', { name: 'Add contact' })).toBeInTheDocument();
    await act(async () => create.resolve(created()));
  });

  it('keeps failed contact creation private and leaves the writable drawer open', async () => {
    const user = userEvent.setup();
    const api = fakeApi(page([], 0));
    vi.mocked(api.create).mockRejectedValueOnce(new Error('PLANTED_PRIVATE_CONTACT_VALUE'));
    renderWorkspace(api);
    await user.click(await screen.findByRole('button', { name: 'Add Contact' }));
    const dialog = screen.getByRole('dialog', { name: 'Add contact' });
    await user.type(within(dialog).getByLabelText('First name'), 'Safe');
    await user.click(within(dialog).getByRole('button', { name: 'Create contact' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'Unable to create contact. Review the fields and try again.',
    );
    expect(dialog).not.toHaveTextContent('PLANTED_PRIVATE_CONTACT_VALUE');
    expect(screen.getByRole('dialog', { name: 'Add contact' })).toBeInTheDocument();
  });

  it('does not publish bulk success or refetch after an aborted unmount', async () => {
    const user = userEvent.setup();
    const bulk = deferred<Awaited<ReturnType<ContactsApi['bulk']>>>();
    const api = fakeApi(page([ada], 1));
    vi.mocked(api.bulk).mockReturnValueOnce(bulk.promise);
    const view = renderWorkspace(api);
    await user.click(await screen.findByRole('checkbox', { name: 'Select Ada Lovelace' }));
    await user.click(screen.getByRole('button', { name: 'Apply bulk action' }));
    const signal = vi.mocked(api.bulk).mock.calls[0]?.[1]?.signal;

    view.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => bulk.resolve({
      requested_contact_ids: [7], actioned_contact_ids: [7], action: 'set_stage',
    }));
    expect(api.directory).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('1 contacts updated')).not.toBeInTheDocument();
  });
});
