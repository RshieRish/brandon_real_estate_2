import AxeBuilder from '@axe-core/playwright';
import type { Locator, Page } from '@playwright/test';
import { commandHomeFixture, expect, test } from './fixtures/command';

const wcagTags = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

async function expectNoAxeViolations(page: Page) {
  await expect(page).toHaveTitle(/\S+/);
  const results = await new AxeBuilder({ page }).withTags(wcagTags).analyze();
  expect(results.violations, results.violations.map((violation) => (
    `${violation.id}: ${violation.help}\n${violation.nodes.map((node) => node.target.join(' ')).join('\n')}`
  )).join('\n\n')).toEqual([]);
}

async function expectBidirectionalFocusLoop(
  page: Page,
  dialog: Locator,
  first: Locator,
  last: Locator,
) {
  await expect(first).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(last).toBeFocused();
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press('Tab');
  await expect(first).toBeFocused();
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
}

test('Home has no WCAG 2.0/2.1 A or AA axe violations', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  await expect(commandPage.getByRole('heading', { name: 'Follow-Up Readiness' })).toBeVisible();

  await expectNoAxeViolations(commandPage);
});

test('global search remains accessible while modal focus is contained', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  const trigger = commandPage.getByRole('button', { name: 'Search Command' });
  await trigger.click();
  const dialog = commandPage.getByRole('dialog', { name: 'Search Command' });
  await expect(dialog).toBeVisible();
  const input = commandPage.getByRole('combobox', { name: 'Search Command' });
  const lastOption = dialog.getByRole('option', { name: 'Saved Searches' });

  await expectNoAxeViolations(commandPage);
  await expectBidirectionalFocusLoop(commandPage, dialog, input, lastOption);
  await commandPage.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});

test('mobile drawer has no axe violations and keeps focus inside', async ({ commandPage }) => {
  await commandPage.setViewportSize({ width: 390, height: 844 });
  await commandPage.goto('/admin/command');
  const trigger = commandPage.getByRole('button', { name: 'Open Command navigation' });
  await trigger.click();
  const drawer = commandPage.getByRole('dialog', { name: 'Command navigation' });
  await expect(drawer).toBeVisible();
  const close = drawer.getByRole('button', { name: 'Close Command navigation' });
  const lastLink = drawer.getByRole('link', { name: 'Saved Searches' });

  await expectNoAxeViolations(commandPage);
  await expectBidirectionalFocusLoop(commandPage, drawer, close, lastLink);
  await commandPage.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});

test('quick task dialog passes axe and contains focus in both directions', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  const trigger = commandPage.getByRole('banner').getByRole('link', { name: 'Create task' });
  await trigger.click();
  const dialog = commandPage.getByRole('dialog', { name: 'Create task' });
  await expect(dialog).toBeVisible();

  await expectNoAxeViolations(commandPage);
  await expectBidirectionalFocusLoop(
    commandPage,
    dialog,
    dialog.getByRole('button', { name: 'Close detail' }),
    dialog.getByRole('button', { name: 'Save task' }),
  );
  await commandPage.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});

test('Tasks uses one main landmark and its archive dialog passes axe with contained focus', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/tasks');
  await expect(commandPage.getByRole('heading', { name: 'Tasks', level: 1 })).toBeVisible();
  await expect(commandPage.getByRole('main')).toHaveCount(1);
  await expect(commandPage.getByRole('region', { name: 'Tasks' })).toBeVisible();

  const trigger = commandPage.getByRole('button', { name: 'Task actions for Call Avery' });
  await trigger.click();
  await commandPage.getByRole('menuitem', { name: 'Archive task' }).click();
  const dialog = commandPage.getByRole('dialog', { name: 'Archive Call Avery' });
  await expect(dialog).toBeVisible();

  await expectNoAxeViolations(commandPage);
  await expectBidirectionalFocusLoop(
    commandPage,
    dialog,
    dialog.getByRole('textbox', { name: 'Archive reason (optional)' }),
    dialog.getByRole('button', { name: 'Archive', exact: true }),
  );
  await commandPage.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});

test('keyboard-only journey reaches shell actions, live regions, and sortable records', async ({
  commandPage,
  mockCommandEndpoint,
}) => {
  await commandPage.goto('/admin/command');
  await expect(commandPage.getByRole('heading', { name: 'Follow-Up Readiness' })).toBeVisible();
  const skipLink = commandPage.getByRole('link', { name: 'Skip to workspace content' });
  await commandPage.keyboard.press('Tab');
  const firstTabLabel = await commandPage.evaluate(() => document.activeElement?.textContent?.trim() ?? '');
  expect(firstTabLabel).toBe('Skip to workspace content');
  await expect(skipLink).toBeFocused();
  await commandPage.keyboard.press('Tab');
  await expect(commandPage.getByRole('link', { name: 'Sold With Sweeney workspace' })).toBeFocused();
  await commandPage.keyboard.press('Tab');
  const railToggle = commandPage.getByRole('button', { name: 'Expand Command navigation' });
  await expect(railToggle).toBeFocused();
  await commandPage.keyboard.press('Enter');
  const expandedRail = commandPage.getByRole('dialog', { name: 'Expanded Command navigation' });
  await expect(expandedRail.getByRole('link', { name: /Sold With Sweeney\s+Workspace/i })).toBeFocused();
  await commandPage.keyboard.press('Escape');
  await expect(railToggle).toBeFocused();
  await expect(railToggle).toHaveAttribute('aria-expanded', 'false');
  await commandPage.keyboard.press('Tab');
  const current = commandPage.getByRole('navigation', { name: 'Command modules' }).getByRole('link', { name: 'Home' });
  await expect(current).toBeFocused();
  await expect(current).toHaveAttribute('aria-current', 'page');

  const searchTrigger = commandPage.getByRole('button', { name: 'Search Command' });
  for (let index = 0; index < 24 && !(await searchTrigger.evaluate((element) => element === document.activeElement)); index += 1) {
    await commandPage.keyboard.press('Tab');
  }
  await expect(searchTrigger).toBeFocused();
  await commandPage.keyboard.press('Enter');
  const searchInput = commandPage.getByRole('combobox', { name: 'Search Command' });
  await expect(searchInput).toBeFocused();
  await commandPage.keyboard.type('contacts');
  await expect(commandPage.getByRole('option', { name: 'Contacts', exact: true })).toBeVisible();
  await commandPage.keyboard.press('Escape');
  await expect(searchTrigger).toBeFocused();

  await mockCommandEndpoint('/tasks', { detail: 'Synthetic task rejection' }, 500, 'POST');
  await commandPage.keyboard.press('Tab');
  const createAction = commandPage.getByRole('banner').getByRole('link', { name: 'Create task' });
  await expect(createAction).toBeFocused();
  await commandPage.keyboard.press('Enter');
  const taskDialog = commandPage.getByRole('dialog', { name: 'Create task' });
  await expect(taskDialog).toBeVisible();
  await expect(taskDialog.getByRole('button', { name: 'Close detail' })).toBeFocused();
  const taskTitle = taskDialog.getByRole('textbox', { name: 'Task title' });
  await commandPage.keyboard.press('Tab');
  await expect(taskTitle).toBeFocused();
  await commandPage.keyboard.type('Keyboard follow-up');
  const saveTask = taskDialog.getByRole('button', { name: 'Save task' });
  for (let index = 0; index < 20 && !(await saveTask.evaluate((element) => element === document.activeElement)); index += 1) {
    await commandPage.keyboard.press('Tab');
  }
  await expect(saveTask).toBeFocused();
  await commandPage.keyboard.press('Enter');
  const error = commandPage.getByRole('alert').filter({
    hasText: 'The server may have applied the task change; refresh before retrying.',
  });
  await expect(error).toHaveAttribute('aria-live', 'assertive');
  await commandPage.keyboard.press('Escape');
  await expect(commandPage).toHaveURL('/admin/command');
  await expect(createAction).toBeFocused();
  await mockCommandEndpoint('/tasks', {
    id: 99,
    title: 'Successful keyboard task',
    contact_id: null,
    description: '',
    priority: 'normal',
    due_at: null,
    status: 'open',
    archived_at: null,
    archive_reason: null,
    version: 1,
  }, 201, 'POST');
  await commandPage.keyboard.press('Enter');
  await expect(commandPage).toHaveURL('/admin/command?create=task');
  const successDialog = commandPage.getByRole('dialog', { name: 'Create task' });
  await expect(successDialog.getByRole('button', { name: 'Close detail' })).toBeFocused();
  await commandPage.keyboard.press('Tab');
  const successTitle = successDialog.getByRole('textbox', { name: 'Task title' });
  await expect(successTitle).toBeFocused();
  await commandPage.keyboard.type('Successful keyboard task');
  const successSave = successDialog.getByRole('button', { name: 'Save task' });
  for (let index = 0; index < 20 && !(await successSave.evaluate((element) => element === document.activeElement)); index += 1) {
    await commandPage.keyboard.press('Tab');
  }
  await expect(successSave).toBeFocused();
  await commandPage.keyboard.press('Enter');
  const success = commandPage.getByRole('status').filter({ hasText: 'Task saved' });
  await expect(success).toHaveAttribute('aria-live', 'polite');
  await mockCommandEndpoint('/tasks', commandHomeFixture.tasks);

  await commandPage.keyboard.press('Shift+Tab');
  await expect(searchTrigger).toBeFocused();
  await commandPage.keyboard.press('Enter');
  await commandPage.keyboard.type('contacts');
  await commandPage.keyboard.press('Enter');
  await expect(commandPage).toHaveURL('/admin/command/contacts');
  await expect(commandPage.getByRole('heading', { name: 'Contacts' })).toBeVisible();

  const sortButton = commandPage.getByRole('button', { name: 'Sort by Name' });
  for (let index = 0; index < 32 && !(await sortButton.evaluate((element) => element === document.activeElement)); index += 1) {
    await commandPage.keyboard.press('Tab');
  }
  await expect(sortButton).toBeFocused();
  const sortableHeader = commandPage.getByRole('columnheader', { name: 'Name' });
  await expect(sortableHeader).toHaveAttribute('aria-sort', 'ascending');
  await commandPage.keyboard.press('Enter');
  await expect(sortableHeader).toHaveAttribute('aria-sort', 'descending');
});

test('error and evidence states are announced rather than encoded only by color', async ({
  commandPage,
  mockCommandEndpoint,
}) => {
  await mockCommandEndpoint('/overview', { detail: 'Overview temporarily unavailable' }, 503);
  await commandPage.goto('/admin/command');

  await expect(commandPage.getByRole('alert').filter({ hasText: 'Some Home data is unavailable' })).toBeVisible();
  await expect(commandPage.getByText('PARTIAL CAPTURE')).toBeVisible();
  await commandPage.getByText('Readiness source coverage').click();
  await expect(commandPage.getByText('All four readiness inputs are available from current internal records.')).toBeVisible();
});

test('forced colors preserve visible core controls', async ({ commandPage }) => {
  await commandPage.emulateMedia({ forcedColors: 'active' });
  await commandPage.goto('/admin/command');
  const search = commandPage.getByRole('button', { name: 'Search Command' });
  await search.focus();

  await expect(search).toBeVisible();
  const style = await search.evaluate((element) => {
    const computed = getComputedStyle(element);
    return { outlineStyle: computed.outlineStyle, color: computed.color };
  });
  expect(style.outlineStyle).not.toBe('none');
  expect(style.color).not.toBe('rgba(0, 0, 0, 0)');
});

test('reduced motion collapses shell transitions to near-zero duration', async ({ commandPage }) => {
  await commandPage.emulateMedia({ reducedMotion: 'reduce' });
  await commandPage.goto('/admin/command');
  const tooltip = commandPage.locator('.command-rail-tooltip').first();

  const duration = await tooltip.evaluate((element) => getComputedStyle(element).transitionDuration);
  const seconds = duration.split(',').map((value) => value.trim()).map((value) => (
    value.endsWith('ms') ? Number.parseFloat(value) / 1000 : Number.parseFloat(value)
  ));
  expect(Math.max(...seconds)).toBeLessThanOrEqual(0.001);
});
