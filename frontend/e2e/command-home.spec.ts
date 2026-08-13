import { commandHomeFixture, expect, test } from './fixtures/command';

test('Home prioritizes verified follow-up work and exactly four KPIs @critical', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');

  await expect(commandPage.getByRole('heading', { name: 'Follow-Up Readiness' })).toBeVisible();
  await expect(commandPage.getByRole('status', { name: 'Loading Command Home' })).toBeHidden();
  await expect(commandPage.getByText('3 overdue tasks need attention first')).toBeVisible();
  await expect(commandPage.getByRole('link', { name: 'Review overdue tasks' })).toHaveAttribute(
    'href',
    '/admin/command/tasks?tab=todo&due=past',
  );
  await expect(commandPage.getByTestId('home-kpi')).toHaveCount(4);
});

test('task scope tabs expose ownership limitations without inventing assignments', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  await expect(commandPage.getByRole('heading', { name: 'Tasks that need attention' })).toBeVisible();

  const all = commandPage.getByRole('tab', { name: 'All' });
  await expect(all).toHaveAttribute('aria-selected', 'true');
  await all.focus();
  await commandPage.keyboard.press('Home');
  await commandPage.keyboard.press('Enter');

  await expect(commandPage.getByRole('tab', { name: 'Personal' })).toHaveAttribute('aria-selected', 'true');
  await expect(commandPage.getByText('Personal task ownership is unavailable')).toBeVisible();
  await commandPage.getByRole('tab', { name: 'Team' }).click();
  await expect(commandPage.getByText('Team task ownership is unavailable')).toBeVisible();
});

test('utility Create task opens one dialog, clears the query, and restores trigger focus @critical', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  await expect(commandPage.getByRole('heading', { name: 'Follow-Up Readiness' })).toBeVisible();
  const headerAction = commandPage.getByRole('banner').getByRole('link', { name: 'Create task' });

  await headerAction.click();
  await expect(commandPage).toHaveURL('/admin/command?create=task');
  await expect(commandPage.getByRole('dialog', { name: 'Create task' })).toBeVisible();
  await commandPage.keyboard.press('Escape');

  await expect(commandPage).toHaveURL('/admin/command');
  await expect(commandPage.getByRole('dialog', { name: 'Create task' })).toBeHidden();
  await expect(headerAction).toBeFocused();
});

test('celebration shortcuts keep their observed counts and destinations', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  const shortcuts = commandPage.getByRole('region', { name: 'Home shortcuts' });

  await expect(shortcuts.getByRole('link', { name: /Birthdays\s+1/ })).toHaveAttribute(
    'href',
    '/admin/command/contacts?filter=birthdays',
  );
  await expect(shortcuts.getByRole('link', { name: /Anniversaries\s+1/ })).toHaveAttribute(
    'href',
    '/admin/command/contacts?filter=anniversaries',
  );
});

test('missing last-contact fields produce a partial score, not a favorable default', async ({
  commandPage,
  mockCommandEndpoint,
}) => {
  const withoutLastContact = commandHomeFixture.contacts.map(({ last_contacted_at: _omitted, ...contact }) => contact);
  await mockCommandEndpoint('/contacts?limit=100&offset=0', withoutLastContact);

  await commandPage.goto('/admin/command');

  await expect(commandPage.getByText(/3 of 4 inputs verified/)).toBeVisible();
  await commandPage.getByText('Readiness source coverage').click();
  await expect(commandPage.getByText('Last-contact history is unavailable.')).toBeVisible();
  await expect(commandPage.getByText('100% ready')).toHaveCount(0);
});

test('an unavailable region can be retried without erasing successful Home data', async ({
  commandPage,
  mockCommandEndpoint,
}) => {
  await mockCommandEndpoint('/overview', { detail: 'Overview temporarily unavailable' }, 503);
  await commandPage.goto('/admin/command');

  await expect(commandPage.getByRole('heading', { name: 'Follow-Up Readiness' })).toBeVisible();
  await expect(commandPage.getByRole('alert').filter({ hasText: 'Some Home data is unavailable' })).toBeVisible();
  await mockCommandEndpoint('/overview', commandHomeFixture.overview);
  await commandPage.getByRole('button', { name: 'Retry unavailable regions' }).click();

  await expect(commandPage.getByRole('alert').filter({ hasText: 'Some Home data is unavailable' })).toBeHidden();
  await expect(commandPage.getByText('3 overdue tasks need attention first')).toBeVisible();
});
