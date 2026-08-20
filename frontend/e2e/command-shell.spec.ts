import type { Page } from '@playwright/test';
import { test, expect } from './fixtures/command';

async function fetchCommand(
  commandPage: Page,
  path: string,
  method: string,
) {
  return commandPage.evaluate(async ({ requestPath, requestMethod }) => {
    const response = await fetch(`/api/v1/command${requestPath}`, {
      method: requestMethod,
      headers: { Authorization: 'Bearer test-admin-token' },
    });
    return { status: response.status, body: await response.json() as { detail?: string } };
  }, { requestPath: path, requestMethod: method });
}

async function createFixtureTask(
  commandPage: Page,
  idempotencyKey: string,
  title: string,
) {
  return commandPage.evaluate(async ({ key, taskTitle }) => {
    const response = await fetch('/api/v1/command/tasks', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer test-admin-token',
        'Content-Type': 'application/json',
        'X-Idempotency-Key': key,
        'X-Client-Timezone': 'America/New_York',
      },
      body: JSON.stringify({
        title: taskTitle,
        contact_id: null,
        description: '',
        priority: 'normal',
        due_at: null,
      }),
    });
    return { status: response.status, body: await response.json() as Record<string, unknown> };
  }, { key: idempotencyKey, taskTitle: title });
}

test('shell persists across module navigation @critical', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  const navigation = commandPage.getByRole('navigation', { name: 'Command modules' });

  await navigation.getByRole('link', { name: 'Contacts' }).click();

  await expect(commandPage).toHaveURL('/admin/command/contacts');
  await expect(navigation).toBeVisible();
  await expect(navigation.getByRole('link', { name: 'Contacts' })).toHaveAttribute('aria-current', 'page');
  await expect(commandPage.getByRole('main')).toHaveCount(1);
  await expect(commandPage.getByText('366 contacts')).toBeVisible();
});

test('global search is keyboard operable @critical', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  const trigger = commandPage.getByRole('button', { name: 'Search Command' });
  await expect(trigger).toBeVisible();
  await trigger.focus();
  await commandPage.keyboard.press(process.platform === 'darwin' ? 'Meta+K' : 'Control+K');
  const search = commandPage.getByRole('combobox', { name: 'Search Command' });

  await search.fill('agreement');
  await commandPage.keyboard.press('ArrowDown');
  await commandPage.keyboard.press('Enter');

  await expect(commandPage).toHaveURL('/admin/command/agreements');
});

test('skip link focuses the work canvas', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  await expect(commandPage.getByRole('heading', { name: 'Follow-Up Readiness' })).toBeVisible();
  const skipLink = commandPage.getByRole('link', { name: 'Skip to workspace content' });
  await skipLink.focus();
  await expect(skipLink).toBeFocused();
  await skipLink.press('Enter');
  await expect(commandPage.getByRole('main')).toBeFocused();
});

test('expanded rail overlays without moving the canvas', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  const canvas = commandPage.locator('.command-canvas');
  const before = await canvas.boundingBox();

  await commandPage.getByRole('button', { name: 'Expand Command navigation' }).click();
  await expect(commandPage.getByRole('dialog', { name: 'Expanded Command navigation' })).toBeVisible();
  const after = await canvas.boundingBox();

  expect(after?.x).toBe(before?.x);
  expect(after?.width).toBe(before?.width);
});

test('nested routes retain their module active state', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts/1');
  await expect(
    commandPage.getByRole('navigation', { name: 'Command modules' }).getByRole('link', { name: 'Contacts' }),
  ).toHaveAttribute('aria-current', 'page');
});

test('unexpected Command fixture endpoints fail closed with a diagnostic', async ({ commandPage, routeState }) => {
  routeState.expectedHttpFailures.add('/referrals', 'GET', 2);
  await commandPage.goto('/admin/command/referrals');

  await expect(commandPage.getByRole('alert').filter({ hasText: 'Unexpected Command fixture request' })).toContainText(
    'Unexpected Command fixture request: GET /referrals',
  );
});

test('known Command endpoints fail closed for methods that were not registered', async ({ commandPage, routeState }) => {
  routeState.expectedHttpFailures.add('/contacts', 'POST');
  routeState.expectedHttpFailures.add('/agreements', 'DELETE');
  await commandPage.goto('/admin/login');

  const postContacts = await fetchCommand(commandPage, '/contacts', 'POST');
  expect(postContacts).toEqual({
    status: 500,
    body: expect.objectContaining({ detail: expect.stringContaining('Unexpected Command fixture request: POST /contacts') }),
  });

  const deleteAgreements = await fetchCommand(commandPage, '/agreements', 'DELETE');
  expect(deleteAgreements).toEqual({
    status: 500,
    body: expect.objectContaining({ detail: expect.stringContaining('Unexpected Command fixture request: DELETE /agreements') }),
  });
});

test('a wrong method cannot consume a one-shot failure registered for another method', async ({
  commandPage,
  failCommandEndpointOnce,
  routeState,
}) => {
  await failCommandEndpointOnce('/overview', 503, 'Planned GET-only failure', 'GET');
  await commandPage.goto('/admin/login');

  // The deliberately wrong request has its own exact allowance and cannot consume the GET failure.
  routeState.expectedHttpFailures.add('/overview', 'POST');
  const wrongMethod = await fetchCommand(commandPage, '/overview', 'POST');
  expect(wrongMethod).toEqual({
    status: 500,
    body: expect.objectContaining({ detail: expect.stringContaining('Unexpected Command fixture request: POST /overview') }),
  });

  const intendedFailure = await fetchCommand(commandPage, '/overview', 'GET');
  expect(intendedFailure).toEqual({ status: 503, body: { detail: 'Planned GET-only failure' } });

  const recovered = await fetchCommand(commandPage, '/overview', 'GET');
  expect(recovered).toEqual({ status: 200, body: expect.any(Object) });
});

test('central task fixture replays one logical create and rejects same-key changed payload', async ({ commandPage, routeState }) => {
  await commandPage.goto('/admin/login');
  const key = '550e8400-e29b-41d4-a716-446655440000';
  const first = await createFixtureTask(commandPage, key, 'Replay-safe task');
  const replay = await createFixtureTask(commandPage, key, 'Replay-safe task');
  expect(first.status).toBe(201);
  expect(replay).toEqual(first);

  routeState.expectedHttpFailures.add('/tasks', 'POST');
  const mismatch = await createFixtureTask(commandPage, key, 'Changed payload');
  expect(mismatch).toEqual({
    status: 409,
    body: {
      detail: {
        code: 'task_idempotency_mismatch',
        message: 'Idempotency key was already used with a different task payload.',
      },
    },
  });

  const other = await createFixtureTask(
    commandPage,
    '123e4567-e89b-42d3-a456-426614174000',
    'Replay-safe task',
  );
  expect(other.status).toBe(201);
  expect(other.body.id).not.toBe(first.body.id);
});

test('central legacy contact workspace preserves raw workflow status for archived rows', async ({ commandPage, routeState }) => {
  routeState.useCentralLegacyWorkspace = true;
  await commandPage.goto('/admin/login');
  const workspace = await commandPage.evaluate(async () => {
    const response = await fetch('/api/v1/command/contacts/1/workspace', {
      headers: { Authorization: 'Bearer test-admin-token' },
    });
    return response.json() as Promise<{ tasks: { title: string; status: string }[] }>;
  });

  expect(workspace.tasks.find((task) => task.title === 'Archived reminder')?.status).toBe('open');
});
