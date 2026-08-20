import type { Page } from '@playwright/test';
import { expect, test } from './fixtures/command';

const defaultDirectory = '/contacts/directory?smart_view=all&sort=name&direction=asc&page=1&page_size=50';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function api(page: Page, path: string, method = 'GET', body?: unknown) {
  return page.evaluate(async ({ requestPath, requestMethod, requestBody }) => {
    const response = await fetch(`/api/v1/command${requestPath}`, {
      method: requestMethod,
      headers: { Authorization: 'Bearer test-admin-token', 'content-type': 'application/json' },
      body: requestBody === undefined ? undefined : JSON.stringify(requestBody),
    });
    const contentType = response.headers.get('content-type') ?? '';
    return { status: response.status, body: contentType.includes('json') ? await response.json() : await response.text() };
  }, { requestPath: path, requestMethod: method, requestBody: body });
}

async function rawApi(page: Page, path: string, method: string, body: string) {
  return page.evaluate(async ({ requestPath, requestMethod, requestBody }) => {
    const response = await fetch(`/api/v1/command${requestPath}`, {
      method: requestMethod,
      headers: { Authorization: 'Bearer test-admin-token', 'content-type': 'application/json' },
      body: requestBody,
    });
    return { status: response.status, body: await response.json() };
  }, { requestPath: path, requestMethod: method, requestBody: body });
}

test('Contacts loads the deterministic 366-row directory and accessible table @critical', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts');
  await expect(commandPage.getByRole('heading', { name: 'Contacts', exact: true })).toBeVisible();
  await expect(commandPage.getByText('366 contacts')).toBeVisible();
  const table = commandPage.getByRole('table', { name: 'Contacts directory' });
  await expect(table).toBeVisible();
  await expect(table.locator('caption')).toHaveText('Contacts directory');
  await expect(table.getByRole('columnheader', { name: 'Name' })).toHaveAttribute('aria-sort', 'ascending');
  await expect(commandPage.getByText('Page 1 of 8')).toBeVisible();
});

test('directory search, arbitrary stage, filters, sorting, pagination, and selection stay URL-backed', async ({ commandPage, routeState }) => {
  await commandPage.goto('/admin/command/contacts');
  await expect(commandPage.getByText('366 contacts')).toBeVisible();
  const search = commandPage.getByRole('searchbox', { name: 'Search contacts' });
  await search.fill('Avery Lake');
  await commandPage.clock.runFor(350);
  await expect(commandPage).toHaveURL(/query=Avery\+Lake/);
  await expect(commandPage.getByText('Avery Lake')).toBeVisible();

  await commandPage.getByRole('button', { name: 'Filter contacts' }).click();
  const filters = commandPage.getByRole('dialog', { name: 'Contact filters' });
  await filters.getByLabel('Stage').fill('bespoke advisory');
  await commandPage.keyboard.press('Escape');
  await expect(commandPage).toHaveURL(/stage=bespoke\+advisory/);
  await expect(commandPage.getByText('No contacts match these filters')).toBeVisible();
  await commandPage.getByRole('button', { name: 'Clear filters' }).click();

  await commandPage.getByRole('button', { name: 'Filter contacts' }).click();
  await commandPage.getByRole('dialog', { name: 'Contact filters' }).getByLabel('Stage').fill('bespoke advisory');
  await commandPage.keyboard.press('Escape');
  await expect(commandPage.getByText('Synthetic 009 Contact')).toBeVisible();
  await commandPage.goto('/admin/command/contacts');
  await expect(commandPage.getByText('366 contacts')).toBeVisible();

  await commandPage.getByRole('button', { name: 'Sort by Stage' }).click();
  await expect(commandPage.getByRole('columnheader', { name: 'Stage' })).toHaveAttribute('aria-sort', 'ascending');
  const orderedNames = async () => commandPage.getByRole('table', { name: 'Contacts directory' }).getByRole('button', { name: /^Open / }).evaluateAll((buttons) => buttons.slice(0, 5).map((button) => button.getAttribute('aria-label')));
  const expectedStage = (direction: 'asc' | 'desc') => [...routeState.contacts.rows].sort((left, right) => {
    const stage = left.stage.localeCompare(right.stage);
    const tie = left.last_name.localeCompare(right.last_name) || left.first_name.localeCompare(right.first_name) || left.id - right.id;
    return direction === 'asc' ? stage || tie : -stage || -tie;
  }).slice(0, 5).map((row) => `Open ${row.display_name}`);
  await expect.poll(orderedNames).toEqual(expectedStage('asc'));
  await commandPage.getByRole('button', { name: 'Sort by Stage' }).click();
  await expect(commandPage.getByRole('columnheader', { name: 'Stage' })).toHaveAttribute('aria-sort', 'descending');
  await expect.poll(orderedNames).toEqual(expectedStage('desc'));
  const stageRows = commandPage.getByRole('table', { name: 'Contacts directory' }).getByRole('row').filter({ has: commandPage.getByRole('button', { name: /^Open / }) });
  await expect(stageRows.nth(0)).toContainText('nurture');
  await commandPage.getByRole('combobox', { name: 'Rows per page' }).selectOption('25');
  await expect(commandPage.getByText('Page 1 of 15')).toBeVisible();
  await commandPage.getByRole('button', { name: 'Next page' }).click();
  await expect(commandPage.getByText('Page 2 of 15')).toBeVisible();
  await commandPage.getByRole('checkbox', { name: 'Select all contacts on this page' }).check();
  await expect(commandPage.getByText('25 selected')).toBeVisible();
  await commandPage.getByRole('tab', { name: 'Recently active' }).click();
  await expect(commandPage.getByText(/selected/)).toHaveCount(0);
});

test('directory error retries without leaking to live network', async ({ commandPage, failCommandEndpointOnce }) => {
  await failCommandEndpointOnce(defaultDirectory, 503, 'Synthetic directory interruption');
  await commandPage.goto('/admin/command/contacts');
  await expect(commandPage.getByRole('table', { name: 'Contacts directory' }).getByRole('alert')).toContainText('Unable to load contacts');
  await commandPage.getByRole('button', { name: 'Retry' }).click();
  await expect(commandPage.getByText('366 contacts')).toBeVisible();
});

test('bulk request is exact, stateful, and preserves selection on 409', async ({ commandPage, routeState, failCommandEndpointOnce }) => {
  await commandPage.goto('/admin/command/contacts');
  await expect(commandPage.getByText('366 contacts')).toBeVisible();
  const boxes = commandPage.getByRole('checkbox', { name: /^Select Synthetic/ });
  await boxes.nth(1).check();
  await boxes.nth(0).check();
  await commandPage.getByRole('combobox', { name: 'Bulk stage' }).fill('active review');
  const requestPromise = commandPage.waitForRequest((request) => request.url().endsWith('/contacts/bulk'));
  const selectedIds = [...routeState.contacts.rows.slice().sort((a, b) => a.last_name.localeCompare(b.last_name) || a.first_name.localeCompare(b.first_name) || a.id - b.id).slice(0, 2).map((row) => row.id)].sort((a, b) => a - b);
  const timelinesBeforeSuccess = await Promise.all(selectedIds.map((id) => api(commandPage, `/contacts/${id}/timeline?page_size=50`)));
  await commandPage.getByRole('button', { name: 'Apply bulk action' }).click();
  expect((await requestPromise).postDataJSON()).toEqual({ contact_ids: selectedIds, action: { action: 'set_stage', stage: 'active review' } });
  await expect(commandPage.getByRole('status')).toContainText('2 contacts updated');
  for (const [index, id] of selectedIds.entries()) {
    expect(((await api(commandPage, `/contacts/${id}/workspace`)).body as { contact: { stage: string } }).contact.stage).toBe('active review');
    expect(await api(commandPage, `/contacts/${id}/timeline?page_size=50`)).toEqual(timelinesBeforeSuccess[index]);
  }
  const noOp = await api(commandPage, '/contacts/bulk', 'POST', { contact_ids: selectedIds, action: { action: 'set_stage', stage: 'active review' } });
  expect(noOp).toEqual({ status: 200, body: { requested_contact_ids: selectedIds, actioned_contact_ids: [], action: 'set_stage' } });
  for (const [index, id] of selectedIds.entries()) expect(await api(commandPage, `/contacts/${id}/timeline?page_size=50`)).toEqual(timelinesBeforeSuccess[index]);

  await boxes.nth(0).check();
  await failCommandEndpointOnce('/contacts/bulk', 409, 'Stale selection', 'POST');
  await commandPage.getByRole('button', { name: 'Apply bulk action' }).click();
  await expect(commandPage.getByRole('alert').filter({ hasText: 'Contacts were not updated' })).toBeVisible();
  await expect(boxes.nth(0)).toBeChecked();
  for (const [index, id] of selectedIds.entries()) expect(await api(commandPage, `/contacts/${id}/timeline?page_size=50`)).toEqual(timelinesBeforeSuccess[index]);
});

test('Add Contact validates, persists exact dates, succeeds, and restores focus on Escape', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts');
  const trigger = commandPage.getByRole('button', { name: 'Add Contact' });
  await trigger.click();
  const dialog = commandPage.getByRole('dialog', { name: 'Add contact' });
  await dialog.getByRole('button', { name: 'Create contact' }).click();
  await expect(dialog.getByRole('alert')).toContainText('First name is required');
  await dialog.getByLabel('First name').fill('New');
  await dialog.getByLabel('Last name').fill('Contact');
  await dialog.getByLabel('Birthday').fill('1990-08-13');
  await dialog.getByLabel('Anniversary').fill('2020-08-13');
  const requestPromise = commandPage.waitForRequest((request) => request.url().endsWith('/contacts') && request.method() === 'POST');
  await dialog.getByRole('button', { name: 'Create contact' }).click();
  expect((await requestPromise).postDataJSON()).toEqual({ first_name: 'New', last_name: 'Contact', stage: 'lead', birthday: '1990-08-13', anniversary: '2020-08-13' });
  await expect(commandPage.getByRole('status')).toContainText('New Contact created');
  await expect(commandPage).toHaveURL(/\/contacts\/367$/);
  const createdWorkspace = (await api(commandPage, '/contacts/367/workspace')).body as { contact: { birthday: string; anniversary: string } };
  expect(createdWorkspace.contact).toMatchObject({ birthday: '1990-08-13', anniversary: '2020-08-13' });
  const createdTimeline = (await api(commandPage, '/contacts/367/timeline?page_size=50')).body as { rows: { kind: string; title: string }[] };
  expect(createdTimeline.rows).toEqual([expect.objectContaining({ kind: 'contact_created', title: 'Contact created in Command workspace' })]);
  expect(((await api(commandPage, '/contacts/1/workspace')).body as { contact: { birthday: null; anniversary: null } }).contact).toMatchObject({ birthday: null, anniversary: null });
  await commandPage.goBack();
  await trigger.click();
  await commandPage.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});

test('fixture is auth-bound, fail-closed, stateful, and returns exact binary bytes', async ({ commandPage, routeState }) => {
  await commandPage.goto('/admin/login');
  routeState.expectedHttpFailures.add('/contacts/directory');
  routeState.expectedHttpFailures.add('/contacts/1/evidence?extra=1');
  const missingAuth = await commandPage.evaluate(async () => (await fetch('/api/v1/command/contacts/directory')).status);
  expect(missingAuth).toBe(401);
  const wrongQuery = await api(commandPage, '/contacts/1/evidence?extra=1');
  expect(wrongQuery.status).toBe(500);
  expect(String((wrongQuery.body as { detail: string }).detail)).toContain('Unexpected Command fixture request');
  routeState.expectedHttpFailures.add('/contacts/1/evidence', 'POST');
  const wrongMethod = await api(commandPage, '/contacts/1/evidence', 'POST', {});
  expect(wrongMethod.status).toBe(500);
  const artifact = await api(commandPage, '/archive/artifacts/55/content');
  expect(artifact).toEqual({ status: 200, body: 'synthetic archive evidence\n' });
  const julyCelebrations = await api(commandPage, '/celebrations?month=7');
  expect(julyCelebrations).toEqual({ status: 200, body: { birthdays: [], anniversaries: [] } });
  const filteredLegacy = await api(commandPage, '/contacts?limit=2&offset=0&query=Avery&stage=lead');
  expect(filteredLegacy).toEqual({ status: 200, body: [expect.objectContaining({ id: 1, first_name: 'Avery', stage: 'lead' })] });
  for (const path of ['/celebrations?month=01', '/celebrations?month=13', '/contacts?limit=01&offset=0', '/contacts?limit=2&offset=0&query=%20Avery%20']) {
    routeState.expectedHttpFailures.add(path);
    expect((await api(commandPage, path)).status).toBe(500);
  }
  const privateSentinel = 'PLANTED_PRIVATE_QUERY_VALUE';
  const privatePath = `/contacts/1/evidence?search=${privateSentinel}`;
  routeState.expectedHttpFailures.add(privatePath);
  const privateFailure = await api(commandPage, privatePath);
  expect(privateFailure.status).toBe(500);
  expect(JSON.stringify(privateFailure.body)).not.toContain(privateSentinel);
  routeState.expectedHttpFailures.add('/private-sentinel');
  const externalFailure = await commandPage.evaluate(async () => {
    try {
      await fetch('https://fixture-network-guard.invalid/private-sentinel');
      return 'unexpected success';
    } catch (error) {
      return error instanceof Error ? error.name : 'unknown failure';
    }
  });
  expect(externalFailure).toBe('TypeError');
});

test('detail renders celebrations, all eight top-level panels, three task panels, and source ownership', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts/1');
  await expect(commandPage.getByRole('heading', { name: 'Avery Lake' })).toBeVisible();
  await expect(commandPage.getByText(/year not captured/i)).toBeVisible();
  const topTabs = commandPage.getByRole('tablist', { name: 'Contact detail views' });
  for (const { value, label } of [
    { value: 'timeline', label: 'Timeline' }, { value: 'opportunities', label: 'Opportunities' },
    { value: 'smart_plans', label: 'SmartPlans' }, { value: 'tasks', label: 'Tasks' },
    { value: 'notes', label: 'Notes' }, { value: 'saved_searches', label: 'Saved Searches' },
    { value: 'evidence', label: 'Source Evidence' }, { value: 'bookings', label: 'Bookings · SWS internal' },
  ]) {
    const tab = topTabs.getByRole('tab', { name: label, exact: true });
    const panel = commandPage.getByRole('tabpanel', { name: label, exact: true, includeHidden: true });
    await tab.click();
    await expect(tab).toHaveAttribute('aria-selected', 'true');
    await expect(tab).toHaveAttribute('id', `contact-detail-view-tab-${value}`);
    await expect(tab).toHaveAttribute('aria-controls', `contact-detail-view-panel-${value}`);
    await expect(panel).toHaveAttribute('id', `contact-detail-view-panel-${value}`);
    await expect(panel).toHaveAttribute('aria-labelledby', `contact-detail-view-tab-${value}`);
    await expect(panel).toBeVisible();
  }
  await topTabs.getByRole('tab', { name: 'Tasks' }).click();
  for (const { value, label } of [
    { value: 'to_do', label: 'To Do' }, { value: 'completed', label: 'Completed' }, { value: 'archived', label: 'Archived' },
  ]) {
    const tab = commandPage.getByRole('tablist', { name: 'Task states' }).getByRole('tab', { name: label, exact: true });
    const panel = commandPage.getByRole('tabpanel', { name: label, exact: true, includeHidden: true });
    await tab.click();
    await expect(tab).toHaveAttribute('aria-selected', 'true');
    await expect(tab).toHaveAttribute('id', `contact-task-state-tab-${value}`);
    await expect(tab).toHaveAttribute('aria-controls', `contact-task-state-panel-${value}`);
    await expect(panel).toHaveAttribute('id', `contact-task-state-panel-${value}`);
    await expect(panel).toHaveAttribute('aria-labelledby', `contact-task-state-tab-${value}`);
    await expect(panel).toBeVisible();
  }
  await topTabs.getByRole('tab', { name: 'Opportunities' }).click();
  await expect(commandPage.getByText('Materialized in SWS')).toBeVisible();
  await topTabs.getByRole('tab', { name: 'SmartPlans' }).click();
  await expect(commandPage.getByRole('region', { name: 'Captured source SmartPlans' }).getByText('Source evidence only')).toBeVisible();
  await topTabs.getByRole('tab', { name: 'Saved Searches' }).click();
  await expect(commandPage.getByRole('region', { name: 'Captured source saved searches' }).getByText('Partial capture', { exact: true }).first()).toBeVisible();
});

test('failed note mutation refreshes authoritative state, preserves its editor, and retries exactly once', async ({ commandPage, failCommandEndpointOnce }) => {
  await failCommandEndpointOnce('/contacts/1/notes', 503, 'Synthetic note interruption', 'POST');
  await commandPage.goto('/admin/command/contacts/1');
  const addNote = commandPage.getByRole('button', { name: 'Add note' });
  await addNote.click();
  const editor = commandPage.getByRole('region', { name: 'Add note' });
  const body = editor.getByRole('textbox', { name: 'Note body' });
  await body.fill('Retry-safe browser note');
  await editor.getByRole('button', { name: 'Save note' }).click();

  const alert = editor.getByRole('alert');
  await expect(alert).toHaveText('Mutation status is unknown. Current contact data was refreshed.');
  await expect(editor).toBeVisible();
  await expect(body).toBeEnabled();
  await expect(body).toHaveValue('Retry-safe browser note');
  await expect(commandPage.getByRole('status').filter({ hasText: 'Note saved' })).toHaveCount(0);
  const failedWorkspace = (await api(commandPage, '/contacts/1/workspace')).body as { notes: { body: string }[] };
  expect(failedWorkspace.notes.filter((note) => note.body === 'Retry-safe browser note')).toHaveLength(0);
  const failedTimeline = (await api(commandPage, '/contacts/1/timeline?page_size=50')).body as { rows: { kind: string; title: string }[] };
  expect(failedTimeline.rows.filter((row) => row.kind === 'note' && row.title === 'Added a contact note')).toHaveLength(0);

  await body.focus();
  await expect(body).toBeFocused();
  await editor.getByRole('button', { name: 'Save note' }).click();
  await expect(addNote).toBeFocused();
  await expect(commandPage.getByRole('status').filter({ hasText: 'Note saved' })).toBeVisible();
  const recoveredWorkspace = (await api(commandPage, '/contacts/1/workspace')).body as { notes: { body: string }[] };
  expect(recoveredWorkspace.notes.filter((note) => note.body === 'Retry-safe browser note')).toHaveLength(1);
  const recoveredTimeline = (await api(commandPage, '/contacts/1/timeline?page_size=50')).body as { rows: { kind: string; title: string }[] };
  expect(recoveredTimeline.rows.filter((row) => row.kind === 'note' && row.title === 'Added a contact note')).toHaveLength(1);
});

test('Source Evidence is a tabpanel with global totals, contact scope, and downloadable artifact', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts/1');
  await commandPage.getByRole('tab', { name: 'Source Evidence' }).click();
  const panel = commandPage.getByRole('tabpanel', { name: 'Source Evidence' });
  await expect(panel).toBeVisible();
  for (const text of ['317 provider contact rows', '317 resolved provider identities', '0 coalesced aliases', '51 lead-backed contacts', '2 reviewed overlaps', '49 legacy-only contacts']) await expect(panel.getByText(text)).toBeVisible();
  await expect(panel.getByRole('heading', { name: 'Capture position 1', exact: true })).toBeVisible();
  const downloadButton = panel.getByRole('button', { name: /Download binary source artifact 55/i });
  const downloadPromise = commandPage.waitForEvent('download');
  await downloadButton.click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('command-contact-evidence-55.binary');
  const hashes = await Promise.all(['/opportunities', '/smart-plans', '/notes', '/saved-searches', '/tasks?state=to_do'].map(async (suffix) => {
    const separator = suffix.includes('?') ? '&' : '?';
    const section = (await api(commandPage, `/contacts/1${suffix}${separator}page=1&page_size=50`)).body as { rows: { source_key_hash: string }[] };
    return section.rows[0]!.source_key_hash;
  }));
  expect(hashes.every((hash) => /^[0-9a-f]{64}$/.test(hash))).toBe(true);
  expect(new Set(hashes).size).toBe(hashes.length);
  const otherEvidence = (await api(commandPage, '/contacts/2/evidence')).body as { sources: { artifacts: unknown[] }[] };
  expect(otherEvidence.sources.every((source) => source.artifacts.length === 0)).toBe(true);
});

test('detail navigation preserves page size; jump uses page_size 10 and outside-universe is explicit', async ({ commandPage, routeState }) => {
  await commandPage.goto('/admin/command/contacts/1?page=2&page_size=25');
  await expect(commandPage.getByRole('heading', { name: 'Avery Lake' })).toBeVisible();
  await commandPage.getByRole('button', { name: 'Next contact' }).click();
  await expect(commandPage).toHaveURL(/\/contacts\/3\?.*page_size=25/);
  await commandPage.getByRole('button', { name: 'Previous contact' }).click();
  await expect(commandPage).toHaveURL(/\/contacts\/1\?.*page_size=25/);
  const jump = commandPage.getByRole('searchbox', { name: 'Jump to contact' });
  const requestPromise = commandPage.waitForRequest((request) => request.url().includes('/contacts/directory?query=Morgan') && request.url().includes('page_size=10'));
  await jump.fill('Morgan');
  await commandPage.clock.runFor(350);
  await requestPromise;
  await commandPage.getByRole('button', { name: 'Open Morgan Hill' }).click();
  await expect(commandPage).toHaveURL(/\/contacts\/2\?.*page_size=25/);
  routeState.expectedHttpFailures.add('/contacts/1/neighbors?query=does-not-match&smart_view=all&sort=name&direction=asc&page=1&page_size=50');
  const outside = await api(commandPage, '/contacts/1/neighbors?query=does-not-match&smart_view=all&sort=name&direction=asc&page=1&page_size=50');
  expect(outside.status).toBe(409);
  routeState.expectedHttpFailures.add('/contacts/1/neighbors?query=does-not-match&smart_view=all&sort=name&direction=asc&page=1&page_size=50');
  await commandPage.goto('/admin/command/contacts/1?query=does-not-match');
  await expect(commandPage.getByRole('status').filter({ hasText: 'outside the current directory view' })).toBeVisible();
});

test('detail exposes recoverable base failure and explicit 404', async ({ commandPage, failCommandEndpointOnce, routeState }) => {
  let releaseDetail!: () => void;
  const detailGate = new Promise<void>((resolve) => { releaseDetail = resolve; });
  await commandPage.route('**/api/v1/command/contacts/1', async (route) => { await detailGate; await route.fallback(); });
  await commandPage.goto('/admin/command/contacts/1');
  await expect(commandPage.getByRole('status', { name: 'Loading contact workspace' })).toBeVisible();
  releaseDetail();
  await expect(commandPage.getByRole('heading', { name: 'Avery Lake' })).toBeVisible();
  await commandPage.unroute('**/api/v1/command/contacts/1');
  const before404 = structuredClone(routeState.contacts.rows.find((row) => row.id === 1));
  await failCommandEndpointOnce('/contacts/1', 404, 'Synthetic missing contact');
  await commandPage.goto('/admin/command/contacts/1');
  await expect(commandPage.getByRole('heading', { name: 'Contact not found' })).toBeVisible();
  expect(routeState.contacts.rows.find((row) => row.id === 1)).toEqual(before404);
  await commandPage.goto('/admin/command/contacts/1');
  await expect(commandPage.getByRole('heading', { name: 'Avery Lake' })).toBeVisible();
  await failCommandEndpointOnce('/contacts/1', 503, 'Synthetic detail interruption');
  await commandPage.goto('/admin/command/contacts/1');
  await expect(commandPage.getByRole('alert').filter({ hasText: 'Unable to load contact workspace' })).toBeVisible();
  await commandPage.getByRole('button', { name: 'Retry' }).click();
  await expect(commandPage.getByRole('heading', { name: 'Avery Lake' })).toBeVisible();
  for (const path of ['/contacts/9999', '/contacts/9999/workspace', '/contacts/9999/timeline?page_size=50', '/contacts/9999/evidence', '/contacts/9999/workspace/summary', '/contacts/9999/neighbors?smart_view=all&sort=name&direction=asc&page=2&page_size=25']) routeState.expectedHttpFailures.add(path);
  await commandPage.goto('/admin/command/contacts/9999?smart_view=all&sort=name&direction=asc&page=2&page_size=25');
  await expect(commandPage.getByRole('heading', { name: 'Contact not found' })).toBeVisible();
  await commandPage.getByRole('button', { name: 'Back to contacts' }).click();
  await expect(commandPage).toHaveURL(/\/contacts\?page=2&page_size=25$/);
  await expect(commandPage.getByRole('button', { name: 'Retry' })).toHaveCount(0);
});

test('directory exposes initial loading, retained-page refresh, true empty, combined filters, exact order, and row keyboard activation', async ({ commandPage }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await commandPage.route(`**/api/v1/command${defaultDirectory}`, async (route) => {
    await gate;
    await route.fulfill({ status: 200, json: { rows: [], total: 0, page: 1, page_size: 50, page_count: 0, sort: 'name', direction: 'asc' } });
  });
  await commandPage.goto('/admin/command/contacts');
  await expect(commandPage.getByRole('status', { name: 'Loading contacts' })).toBeVisible();
  release();
  await expect(commandPage.getByText('No contacts yet')).toBeVisible();
  await commandPage.unroute(`**/api/v1/command${defaultDirectory}`);

  await commandPage.goto('/admin/command/contacts');
  await expect(commandPage.getByText('366 contacts')).toBeVisible();
  let releaseRefresh!: () => void;
  const refreshGate = new Promise<void>((resolve) => { releaseRefresh = resolve; });
  await commandPage.route('**/api/v1/command/contacts/directory?smart_view=all&sort=name&direction=asc&page=1&page_size=25', async (route) => {
    await refreshGate;
    await route.fallback();
  });
  await commandPage.getByRole('combobox', { name: 'Rows per page' }).selectOption('25');
  const retainedTable = commandPage.getByRole('table', { name: 'Contacts directory' });
  await expect(retainedTable).toHaveAttribute('aria-busy', 'true');
  await expect(retainedTable.getByText('Synthetic 005 Contact')).toBeVisible();
  releaseRefresh();
  await expect(retainedTable).not.toHaveAttribute('aria-busy', 'true');
  await commandPage.unroute('**/api/v1/command/contacts/directory?smart_view=all&sort=name&direction=asc&page=1&page_size=25');

  await commandPage.goto('/admin/command/contacts?source=kw_command&origin=recovered&tag=1&smart_view=all&sort=name&direction=asc&page=1&page_size=50');
  await expect(commandPage.getByText('3 contacts')).toBeVisible();
  const rows = commandPage.getByRole('table', { name: 'Contacts directory' }).getByRole('row').filter({ has: commandPage.getByRole('button', { name: /^Open / }) });
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText('Morgan Hill');
  await expect(rows.nth(1)).toContainText('Avery Lake');
  await expect(rows.nth(2)).toContainText('Casey Pine');
  await rows.nth(0).focus();
  await rows.nth(0).press('Enter');
  await expect(commandPage).toHaveURL(/\/contacts\/2/);
});

test('detail celebrations distinguish yearless, sentinel, and verified evidence, including true-empty recovered sections', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts/1');
  await expect(commandPage.getByText(/year not captured/i)).toBeVisible();
  await commandPage.goto('/admin/command/contacts/2');
  await expect(commandPage.getByText(/source year treated as sentinel/i)).toBeVisible();
  await commandPage.goto('/admin/command/contacts/3');
  await expect(commandPage.getByText(/Home anniversary: August 23, 2022/i)).toBeVisible();
  await commandPage.getByRole('tab', { name: 'Notes' }).click();
  await expect(commandPage.getByRole('tabpanel', { name: 'Notes' }).getByText('No notes were captured')).toBeVisible();
});

test('internal profile, note, search, tag, task, delete, and remove mutations send exact bodies and restore focus', async ({ commandPage }) => {
  const writes: string[] = [];
  commandPage.on('request', (request) => { if (request.method() !== 'GET') writes.push(request.url()); });
  await commandPage.goto('/admin/command/contacts/1');
  const editProfile = commandPage.getByRole('button', { name: 'Edit profile' });
  await editProfile.click();
  await commandPage.keyboard.press('Escape');
  await expect(editProfile).toBeFocused();
  expect(writes).toEqual([]);
  await editProfile.click();
  await commandPage.getByRole('region', { name: 'Edit SWS profile' }).getByLabel('Stage').fill('active review');
  const profile = commandPage.waitForRequest((request) => request.method() === 'PATCH' && request.url().endsWith('/contacts/1'));
  await commandPage.getByRole('button', { name: 'Save profile' }).click();
  expect((await profile).postDataJSON()).toEqual({ stage: 'active review' });
  await expect(commandPage.getByRole('button', { name: 'Edit profile' })).toBeFocused();

  const addNote = commandPage.getByRole('button', { name: 'Add note' });
  await addNote.click();
  await commandPage.keyboard.press('Escape');
  await expect(addNote).toBeFocused();
  expect(writes).toHaveLength(1);
  await addNote.click();
  await commandPage.getByLabel('Note body').fill('Browser-created internal note');
  const note = commandPage.waitForRequest((request) => request.method() === 'POST' && request.url().endsWith('/contacts/1/notes'));
  await commandPage.getByRole('button', { name: 'Save note' }).click();
  expect((await note).postDataJSON()).toEqual({ body: 'Browser-created internal note' });
  await expect(addNote).toBeFocused();

  const saveSearch = commandPage.getByRole('button', { name: 'Save search' }).first();
  await saveSearch.click();
  await commandPage.keyboard.press('Escape');
  await expect(saveSearch).toBeFocused();
  expect(writes).toHaveLength(2);
  await saveSearch.click();
  await commandPage.getByLabel('Saved search name').fill('Browser saved search');
  const search = commandPage.waitForRequest((request) => request.method() === 'POST' && request.url().endsWith('/contacts/1/saved-searches'));
  await commandPage.getByRole('region', { name: 'Save search' }).getByRole('button', { name: 'Save search' }).click();
  expect((await search).postDataJSON()).toEqual({ name: 'Browser saved search', criteria: { contact_id: 1, scope: 'contact_workspace', saved_from: 'command' } });
  await expect(saveSearch).toBeFocused();

  const addTag = commandPage.getByRole('button', { name: 'Add tag' });
  await addTag.click();
  await commandPage.keyboard.press('Escape');
  await expect(addTag).toBeFocused();
  expect(writes).toHaveLength(3);
  await addTag.click();
  await commandPage.getByLabel('Tag name').fill('Browser tag');
  const tagCreate = commandPage.waitForRequest((request) => request.method() === 'POST' && request.url().endsWith('/tags'));
  const tagAssign = commandPage.waitForRequest((request) => request.method() === 'POST' && /\/contacts\/1\/tags\/\d+$/.test(new URL(request.url()).pathname));
  await commandPage.getByRole('region', { name: 'Add tag' }).getByRole('button', { name: 'Add tag' }).click();
  expect((await tagCreate).postDataJSON()).toEqual({ name: 'Browser tag' });
  expect((await tagAssign).postData()).toBeNull();
  await expect(addTag).toBeFocused();
  await expect(commandPage.getByText('Browser tag')).toBeVisible();
  const remove = commandPage.getByRole('button', { name: 'Remove Browser tag tag' });
  await remove.click();
  await expect(remove).toBeHidden();

  await commandPage.getByRole('tab', { name: 'Tasks' }).click();
  const addTask = commandPage.getByRole('button', { name: 'Add task' });
  await addTask.click();
  await commandPage.keyboard.press('Escape');
  await expect(addTask).toBeFocused();
  expect(writes).toHaveLength(6);
  await addTask.click();
  await commandPage.getByLabel('Task title').fill('Browser task');
  const task = commandPage.waitForRequest((request) => request.method() === 'POST' && request.url().endsWith('/tasks'));
  await commandPage.getByRole('button', { name: 'Save task' }).click();
  const taskRequest = await task;
  expect(taskRequest.postDataJSON()).toEqual({ title: 'Browser task', contact_id: 1, description: '', priority: 'normal', due_at: null });
  expect(taskRequest.headers()['x-idempotency-key']).toMatch(UUID_PATTERN);
  await expect(commandPage.getByRole('button', { name: 'Add task' })).toBeFocused();

  await commandPage.getByRole('tab', { name: 'Notes' }).click();
  const deleteNote = commandPage.getByRole('button', { name: 'Delete SWS note 111' });
  await deleteNote.click();
  await expect(commandPage.getByRole('status').filter({ hasText: 'Note deleted' })).toBeVisible();
  const workspace = (await api(commandPage, '/contacts/1/workspace')).body as {
    contact: { stage: string }; notes: { id: number; body: string }[]; saved_searches: { name: string }[];
    tags: { name: string }[]; tasks: { title: string }[];
  };
  expect(workspace.contact.stage).toBe('active review');
  expect(workspace.notes).toEqual(expect.arrayContaining([expect.objectContaining({ body: 'Browser-created internal note' })]));
  expect(workspace.notes.some((noteRow) => noteRow.id === 111)).toBe(false);
  expect(workspace.saved_searches).toEqual(expect.arrayContaining([expect.objectContaining({ name: 'Browser saved search' })]));
  expect(workspace.tags.some((tagRow) => tagRow.name === 'Browser tag')).toBe(false);
  expect(workspace.tasks).toEqual(expect.arrayContaining([expect.objectContaining({ title: 'Browser task' })]));
  const mutationTimeline = (await api(commandPage, '/contacts/1/timeline?page_size=50')).body as { rows: { kind: string; title: string }[] };
  const expectedActivities = [
    ['stage_changed', 'Contact stage changed'],
    ['note', 'Added a contact note'],
    ['tag_removed', 'Removed a contact tag'],
    ['task_created', 'Browser task'],
    ['note_removed', 'Removed a contact note'],
  ] as const;
  for (const [kind, title] of expectedActivities) expect(mutationTimeline.rows.filter((row) => row.kind === kind && row.title === title)).toHaveLength(1);
  const repeatedRemoval = await api(commandPage, '/contacts/1/tags/2', 'DELETE');
  expect(repeatedRemoval).toEqual({ status: 200, body: { removed: false, contact_id: 1, tag_id: 2 } });
  expect(await api(commandPage, '/contacts/1/timeline?page_size=50')).toEqual({ status: 200, body: mutationTimeline });
});

test('artifact failure is announced then retries with authenticated exact bytes', async ({ commandPage, failCommandEndpointOnce }) => {
  await failCommandEndpointOnce('/archive/artifacts/55/content', 503, 'Synthetic artifact interruption');
  await commandPage.goto('/admin/command/contacts/1');
  await commandPage.getByRole('tab', { name: 'Source Evidence' }).click();
  const button = commandPage.getByRole('button', { name: /Download binary source artifact 55/i });
  await button.click();
  await expect(commandPage.getByRole('alert').filter({ hasText: 'Source artifact could not be downloaded' })).toBeVisible();
  const requestPromise = commandPage.waitForRequest((request) => request.url().endsWith('/archive/artifacts/55/content'));
  const downloadPromise = commandPage.waitForEvent('download');
  await button.click();
  const request = await requestPromise;
  expect(request.headers().authorization).toBe('Bearer test-admin-token');
  const download = await downloadPromise;
  expect(await download.createReadStream().then(async (stream) => {
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(Buffer.from(chunk));
    return Buffer.concat(chunks).toString('utf8');
  })).toBe('synthetic archive evidence\n');
});

test('fixture rejects malformed, extra-key, cross-contact, query, and unknown-route mutations without state changes', async ({ commandPage, routeState }) => {
  await commandPage.goto('/admin/login');
  routeState.expectedHttpFailures.add('/contacts', 'POST');
  expect((await rawApi(commandPage, '/contacts', 'POST', '{')).status).toBe(500);
  routeState.expectedHttpFailures.add('/contacts', 'POST');
  expect((await api(commandPage, '/contacts', 'POST', { first_name: 'Valid', extra: true })).status).toBe(500);
  routeState.expectedHttpFailures.add('/contacts/1/saved-searches', 'POST');
  expect((await api(commandPage, '/contacts/1/saved-searches', 'POST', { name: 'Bad', criteria: { contact_id: 2, scope: 'contact_workspace', saved_from: 'command' } })).status).toBe(500);
  routeState.expectedHttpFailures.add('/contacts/1/notes/111?extra=1', 'DELETE');
  expect((await api(commandPage, '/contacts/1/notes/111?extra=1', 'DELETE')).status).toBe(500);
  routeState.expectedHttpFailures.add('/contacts/9999/not-a-route');
  expect((await api(commandPage, '/contacts/9999/not-a-route')).status).toBe(500);
  for (const path of ['/contacts/9999/timeline?evil=1', '/contacts/9999/notes?page=0&page_size=101']) {
    routeState.expectedHttpFailures.add(path);
    expect((await api(commandPage, path)).status).toBe(500);
  }
  routeState.expectedHttpFailures.add('/contacts/9999', 'PATCH');
  expect((await api(commandPage, '/contacts/9999', 'PATCH', { extra: true })).status).toBe(500);
  routeState.expectedHttpFailures.add('/contacts/9999/notes', 'POST');
  expect((await rawApi(commandPage, '/contacts/9999/notes', 'POST', '{')).status).toBe(500);
  routeState.expectedHttpFailures.add('/contacts/9999/tags/1', 'POST');
  expect((await api(commandPage, '/contacts/9999/tags/1', 'POST', {})).status).toBe(500);
  for (const path of ['/contacts/directory?page=01', '/contacts/1/notes?page=01&page_size=50', '/contacts/0001']) {
    routeState.expectedHttpFailures.add(path);
    expect((await api(commandPage, path)).status).toBe(500);
  }
  routeState.expectedHttpFailures.add('/contacts', 'POST');
  expect((await api(commandPage, '/contacts', 'POST', { first_name: 'Year zero', birthday: '0000-01-01' })).status).toBe(500);
  const canonicalSearch = await api(commandPage, '/contacts/1/saved-searches', 'POST', { name: 'Canonical', criteria: { z: { y: 2, a: 1 }, a: 2 } });
  expect(canonicalSearch).toEqual({ status: 201, body: expect.objectContaining({ criteria: '{"a":2,"z":{"a":1,"y":2}}' }) });
  routeState.expectedHttpFailures.add('/contacts/1/saved-searches', 'POST');
  expect((await rawApi(commandPage, '/contacts/1/saved-searches', 'POST', '{"name":"Non-finite","criteria":{"nested":[1,1e400]}}')).status).toBe(500);
  const astral = 'x'.repeat(118) + '🌟';
  const validAstral = await api(commandPage, '/contacts', 'POST', { first_name: astral });
  expect(validAstral.status).toBe(201);
  expect(routeState.contacts.rows).toHaveLength(367);
  const legacyNewest = (await api(commandPage, '/contacts?limit=1&offset=0')).body as { id: number }[];
  expect(legacyNewest).toEqual([expect.objectContaining({ id: 367 })]);
  const beforeNoop = {
    updatedAt: routeState.contacts.updatedAt.get(1),
    row: structuredClone(routeState.contacts.rows.find((row) => row.id === 1)),
    detail: structuredClone(routeState.contacts.details.get(1)),
    workspace: structuredClone(routeState.contacts.workspaces.get(1)),
  };
  expect(await api(commandPage, '/contacts/1', 'PATCH', { stage: 'lead' })).toEqual({ status: 200, body: expect.objectContaining({ stage: 'lead' }) });
  expect(routeState.contacts.updatedAt.get(1)).toBe(beforeNoop.updatedAt);
  expect(routeState.contacts.rows.find((row) => row.id === 1)).toEqual(beforeNoop.row);
  expect(routeState.contacts.details.get(1)).toEqual(beforeNoop.detail);
  expect(routeState.contacts.workspaces.get(1)).toEqual(beforeNoop.workspace);
});
