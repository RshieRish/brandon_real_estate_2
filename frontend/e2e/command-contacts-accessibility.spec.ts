import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { expect, test } from './fixtures/command';

const wcagTags = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];
async function axe(page: Page) {
  await expect(page).not.toHaveTitle('');
  const results = await new AxeBuilder({ page }).withTags(wcagTags).analyze();
  expect(results.violations, results.violations.map((item) => `${item.id}: ${item.nodes.map((node) => node.target.join(' ')).join(', ')}`).join('\n')).toEqual([]);
}

test('exactly four meaningful Contacts states pass axe', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts');
  await expect(commandPage.getByText('366 contacts')).toBeVisible();
  await axe(commandPage);

  await commandPage.goto('/admin/command/contacts/1');
  await expect(commandPage.getByRole('heading', { name: 'Avery Lake' })).toBeVisible();
  const expand = commandPage.getByRole('button', { name: 'Show full activity' });
  await expand.click();
  await expect(commandPage.getByRole('button', { name: 'Collapse activity' })).toHaveAttribute('aria-expanded', 'true');
  await axe(commandPage);

  await commandPage.getByRole('tab', { name: 'Tasks' }).click();
  await expect(commandPage.getByRole('region', { name: 'Captured source to-do tasks' })).toBeVisible();
  await axe(commandPage);

  await commandPage.getByRole('tab', { name: 'Source Evidence' }).click();
  await expect(commandPage.getByRole('region', { name: 'Contact capture evidence' })).toBeVisible();
  await axe(commandPage);
});

test('directory table has a caption, accessible region, and stateful aria-sort', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts');
  const region = commandPage.getByRole('region', { name: 'Contacts directory table' });
  const table = region.getByRole('table', { name: 'Contacts directory' });
  await expect(table.locator('caption')).toHaveText('Contacts directory');
  const name = table.getByRole('columnheader', { name: 'Name' });
  await expect(name).toHaveAttribute('aria-sort', 'ascending');
  await name.getByRole('button').click();
  await expect(name).toHaveAttribute('aria-sort', 'descending');
});

test('all eight plus three tabs have exact persistent tab-to-panel relationships and roving keyboard behavior', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts/1');
  const detail = commandPage.getByRole('tablist', { name: 'Contact detail views' });
  for (const { value, label } of [
    { value: 'timeline', label: 'Timeline' }, { value: 'opportunities', label: 'Opportunities' },
    { value: 'smart_plans', label: 'SmartPlans' }, { value: 'tasks', label: 'Tasks' },
    { value: 'notes', label: 'Notes' }, { value: 'saved_searches', label: 'Saved Searches' },
    { value: 'evidence', label: 'Source Evidence' }, { value: 'bookings', label: 'Bookings · SWS internal' },
  ]) {
    const tab = detail.getByRole('tab', { name: label, exact: true });
    const panel = commandPage.getByRole('tabpanel', { name: label, exact: true, includeHidden: true });
    await expect(tab).toHaveAttribute('aria-controls', `contact-detail-view-panel-${value}`);
    await expect(panel).toHaveAttribute('aria-labelledby', `contact-detail-view-tab-${value}`);
  }
  const timeline = detail.getByRole('tab', { name: 'Timeline' });
  await timeline.focus();
  await commandPage.keyboard.press('ArrowRight');
  await expect(detail.getByRole('tab', { name: 'Opportunities' })).toBeFocused();
  await commandPage.keyboard.press('End');
  await expect(detail.getByRole('tab', { name: 'Bookings · SWS internal' })).toBeFocused();
  await detail.getByRole('tab', { name: 'Tasks' }).click();
  const tasks = commandPage.getByRole('tablist', { name: 'Task states' });
  for (const { value, label } of [{ value: 'to_do', label: 'To Do' }, { value: 'completed', label: 'Completed' }, { value: 'archived', label: 'Archived' }]) {
    const tab = tasks.getByRole('tab', { name: label, exact: true });
    const panel = commandPage.getByRole('tabpanel', { name: label, exact: true, includeHidden: true });
    await expect(tab).toHaveAttribute('aria-controls', `contact-task-state-panel-${value}`);
    await expect(panel).toHaveAttribute('aria-labelledby', `contact-task-state-tab-${value}`);
  }
  const toDo = tasks.getByRole('tab', { name: 'To Do', exact: true });
  await toDo.focus();
  await commandPage.keyboard.press('ArrowRight');
  await expect(tasks.getByRole('tab', { name: 'Completed', exact: true })).toBeFocused();
  await commandPage.keyboard.press('End');
  await expect(tasks.getByRole('tab', { name: 'Archived', exact: true })).toBeFocused();
});

test('visible headings are unique and profile disclosure contains focus then restores its trigger', async ({ commandPage }) => {
  await commandPage.setViewportSize({ width: 390, height: 844 });
  await commandPage.goto('/admin/command/contacts/1');
  const headings = await commandPage.getByRole('heading').evaluateAll((elements) => elements.filter((element) => {
    const style = getComputedStyle(element);
    return style.visibility !== 'hidden' && style.display !== 'none';
  }).map((element) => element.textContent?.trim()).filter(Boolean));
  expect(new Set(headings).size, headings.join('\n')).toBe(headings.length);
  const trigger = commandPage.getByRole('button', { name: 'Profile details' });
  await trigger.click();
  await commandPage.getByRole('button', { name: 'Edit profile' }).focus();
  expect(await commandPage.locator('#command-contact-profile-region').evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await commandPage.keyboard.press('Escape');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await expect(trigger).toBeFocused();
});

test('visible Contacts controls meet the 44 CSS pixel target', async ({ commandPage }) => {
  await commandPage.setViewportSize({ width: 390, height: 844 });
  for (const route of ['/admin/command/contacts', '/admin/command/contacts/1']) {
    await commandPage.goto(route);
    if (route.endsWith('/contacts')) await expect(commandPage.getByText('366 contacts')).toBeVisible();
    else await expect(commandPage.getByRole('heading', { name: 'Avery Lake' })).toBeVisible();
    const undersized = await commandPage.locator('main a:visible, main button:visible, main input:visible, main select:visible').evaluateAll((elements) => elements.map((element) => {
      const target = element instanceof HTMLInputElement && element.type === 'checkbox' ? element.closest('label') ?? element : element;
      const box = target.getBoundingClientRect();
      return { name: element.getAttribute('aria-label') ?? element.textContent?.trim(), width: box.width, height: box.height };
    }).filter(({ width, height }) => width < 44 || height < 44));
    expect(undersized, `${route}: ${JSON.stringify(undersized)}`).toEqual([]);
  }
});

test('contact dialog contains focus, closes with Escape, and restores trigger', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts');
  const trigger = commandPage.getByRole('button', { name: 'Add Contact' });
  await trigger.click();
  const dialog = commandPage.getByRole('dialog', { name: 'Add contact' });
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  for (let index = 0; index < 12; index += 1) await commandPage.keyboard.press('Tab');
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  for (let index = 0; index < 12; index += 1) await commandPage.keyboard.press('Shift+Tab');
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await commandPage.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test('Contacts errors and success use assertive and polite live regions', async ({ commandPage, failCommandEndpointOnce }) => {
  await failCommandEndpointOnce('/contacts/directory?smart_view=all&sort=name&direction=asc&page=1&page_size=50', 503, 'Unavailable');
  await commandPage.goto('/admin/command/contacts');
  await expect(commandPage.getByRole('alert').filter({ hasText: 'Unable to load contacts' })).toBeVisible();
  await commandPage.getByRole('button', { name: 'Retry' }).click();
  await commandPage.getByRole('checkbox', { name: /^Select Synthetic/ }).first().check();
  await commandPage.getByRole('combobox', { name: 'Bulk stage' }).fill('review');
  await commandPage.getByRole('button', { name: 'Apply bulk action' }).click();
  await expect(commandPage.getByRole('status').filter({ hasText: 'contacts updated' })).toBeVisible();
});

test('forced colors remain visible and reduced motion is no more than 0.001 seconds', async ({ commandPage }) => {
  await commandPage.emulateMedia({ forcedColors: 'active' });
  await commandPage.goto('/admin/command/contacts/1');
  const tab = commandPage.getByRole('tab', { name: 'Timeline' });
  await tab.focus();
  const forced = await tab.evaluate((element) => ({ color: getComputedStyle(element).color, outline: getComputedStyle(element).outlineStyle }));
  expect(forced.color).not.toBe('rgba(0, 0, 0, 0)');
  expect(forced.outline).not.toBe('none');
  await commandPage.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'none' });
  const durations = await commandPage.locator('main *').evaluateAll((elements) => elements.flatMap((element) => getComputedStyle(element).transitionDuration.split(',')).map((value) => value.trim().endsWith('ms') ? Number.parseFloat(value) / 1000 : Number.parseFloat(value) || 0));
  expect(Math.max(...durations)).toBeLessThanOrEqual(0.001);
});
