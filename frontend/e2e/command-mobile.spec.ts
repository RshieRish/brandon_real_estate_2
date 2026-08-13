import { expect, test } from './fixtures/command';

test('mobile drawer traps focus, closes with Escape, and restores its trigger @critical', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  const trigger = commandPage.getByRole('button', { name: 'Open Command navigation' });

  await trigger.click();
  const drawer = commandPage.getByRole('dialog', { name: 'Command navigation' });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('button', { name: 'Close Command navigation' })).toBeFocused();

  await commandPage.keyboard.press('Shift+Tab');
  await expect(drawer).toContainText('Saved Searches');
  expect(await drawer.evaluate((element) => element.contains(document.activeElement))).toBe(true);

  await commandPage.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  await expect(trigger).toBeFocused();
});

test('mobile drawer closes after module navigation', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  await commandPage.getByRole('button', { name: 'Open Command navigation' }).click();
  const drawer = commandPage.getByRole('dialog', { name: 'Command navigation' });

  await drawer.getByRole('link', { name: 'Tasks' }).click();

  await expect(commandPage).toHaveURL('/admin/command/tasks');
  await expect(drawer).toBeHidden();
});

test('mobile navigation controls meet the 44px target minimum', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  const trigger = commandPage.getByRole('button', { name: 'Open Command navigation' });
  await trigger.click();

  const targets = [
    trigger,
    commandPage.getByRole('button', { name: 'Close Command navigation' }),
    commandPage.getByRole('navigation', { name: 'Mobile Command modules' }).getByRole('link', { name: 'Home' }),
  ];
  for (const target of targets) {
    const box = await target.boundingBox();
    expect(box, 'target must be visible and measurable').not.toBeNull();
    expect(box?.width).toBeGreaterThanOrEqual(44);
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
});

test('the mobile page contains horizontal scrolling inside intended strips', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  await expect(commandPage.getByRole('heading', { name: 'Follow-Up Readiness' })).toBeVisible();

  const dimensions = await commandPage.evaluate(() => ({
    viewport: window.innerWidth,
    page: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
    shortcutsClient: document.querySelector<HTMLElement>('.command-home-shortcuts')?.clientWidth ?? 0,
    shortcutsScroll: document.querySelector<HTMLElement>('.command-home-shortcuts')?.scrollWidth ?? 0,
  }));

  expect(dimensions.page).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.body).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.shortcutsScroll).toBeGreaterThan(dimensions.shortcutsClient);
});

test('mobile shell reaches the current paged Contacts directory', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  await commandPage.getByRole('button', { name: 'Open Command navigation' }).click();
  await commandPage.getByRole('navigation', { name: 'Mobile Command modules' }).getByRole('link', { name: 'Contacts', exact: true }).click();
  await expect(commandPage.getByText('366 contacts')).toBeVisible();
  await expect(commandPage.getByRole('table', { name: 'Contacts directory' })).toBeVisible();
});
