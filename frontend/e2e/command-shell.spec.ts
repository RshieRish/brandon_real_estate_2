import { test, expect } from './fixtures/command';

test('shell persists across module navigation @critical', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  const navigation = commandPage.getByRole('navigation', { name: 'Command modules' });

  await navigation.getByRole('link', { name: 'Contacts' }).click();

  await expect(commandPage).toHaveURL('/admin/command/contacts');
  await expect(navigation).toBeVisible();
  await expect(navigation.getByRole('link', { name: 'Contacts' })).toHaveAttribute('aria-current', 'page');
  await expect(commandPage.getByRole('main')).toHaveCount(1);
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
  routeState.expectedHttpFailures.add('/referrals');
  await commandPage.goto('/admin/command/referrals');

  await expect(commandPage.getByRole('alert').filter({ hasText: 'Unexpected Command fixture request' })).toContainText(
    'Unexpected Command fixture request: GET /referrals',
  );
});
