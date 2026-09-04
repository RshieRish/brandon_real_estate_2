import { expect, test } from './fixtures/command';
import {
  BROKEN_ARCHIVE_TIMELINE_VALUE,
  LONG_REAL_TIMELINE_VALUE,
} from './fixtures/command-contacts';

test('Contacts detail mobile profile disclosure opens, closes, and restores focus', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts/1');
  const disclosure = commandPage.getByRole('button', { name: 'Profile details' });
  await expect(disclosure).toHaveAttribute('aria-expanded', 'false');
  await disclosure.click();
  await expect(disclosure).toHaveAttribute('aria-expanded', 'true');
  await expect(commandPage.getByText('Synthetic recovered profile for deterministic browser acceptance.')).toBeVisible();
  await commandPage.keyboard.press('Escape');
  await expect(disclosure).toHaveAttribute('aria-expanded', 'false');
  await expect(disclosure).toBeFocused();
});

test('pending mobile profile save retains editor focus and nested Escape ownership', async ({ commandPage }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await commandPage.route('**/api/v1/command/contacts/1', async (route) => {
    if (route.request().method() !== 'PATCH') return route.fallback();
    await gate;
    await route.fallback();
  });
  await commandPage.goto('/admin/command/contacts/1');
  const disclosure = commandPage.getByRole('button', { name: 'Profile details' });
  await disclosure.click();
  await commandPage.getByRole('button', { name: 'Edit profile' }).click();
  await commandPage.getByLabel('Stage').fill('active review');
  await commandPage.getByRole('button', { name: 'Save profile' }).click();
  const editor = commandPage.getByRole('region', { name: 'Edit SWS profile' });
  await expect(editor).toBeFocused();
  await commandPage.keyboard.press('Escape');
  await expect(editor).toBeVisible();
  await expect(editor).toBeFocused();
  await expect(disclosure).toHaveAttribute('aria-expanded', 'true');
  release();
  const editProfile = commandPage.getByRole('button', { name: 'Edit profile' });
  await expect(editProfile).toBeFocused();
  await editProfile.click();
  await commandPage.keyboard.press('Escape');
  await expect(editProfile).toBeFocused();
  await expect(disclosure).toHaveAttribute('aria-expanded', 'true');
  await commandPage.keyboard.press('Escape');
  await expect(disclosure).toHaveAttribute('aria-expanded', 'false');
  await expect(disclosure).toBeFocused();
});

test('mobile detail reaches all eight views, all three task states, and adjacent contacts', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts/1?page_size=25');
  const top = commandPage.getByRole('tablist', { name: 'Contact detail views' });
  for (const { value, label } of [
    { value: 'timeline', label: 'Timeline' }, { value: 'opportunities', label: 'Opportunities' },
    { value: 'smart_plans', label: 'SmartPlans' }, { value: 'tasks', label: 'Tasks' },
    { value: 'notes', label: 'Notes' }, { value: 'saved_searches', label: 'Saved Searches' },
    { value: 'evidence', label: 'Source Evidence' }, { value: 'bookings', label: 'Bookings · SWS internal' },
  ]) {
    const tab = top.getByRole('tab', { name: label, exact: true });
    const panel = commandPage.getByRole('tabpanel', { name: label, exact: true, includeHidden: true });
    await tab.click();
    await expect(tab).toHaveAttribute('aria-selected', 'true');
    await expect(tab).toHaveAttribute('id', `contact-detail-view-tab-${value}`);
    await expect(tab).toHaveAttribute('aria-controls', `contact-detail-view-panel-${value}`);
    await expect(panel).toHaveAttribute('id', `contact-detail-view-panel-${value}`);
    await expect(panel).toHaveAttribute('aria-labelledby', `contact-detail-view-tab-${value}`);
    await expect(panel).toBeVisible();
  }
  await top.getByRole('tab', { name: 'Tasks' }).click();
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
  await commandPage.getByRole('button', { name: 'Next contact' }).click();
  await expect(commandPage).toHaveURL(/\/contacts\/3\?.*page_size=25/);
  await commandPage.getByRole('button', { name: 'Previous contact' }).click();
  await expect(commandPage).toHaveURL(/\/contacts\/1\?.*page_size=25/);
  const jump = commandPage.getByRole('searchbox', { name: 'Jump to contact' });
  const lookup = commandPage.waitForRequest((request) => request.url().includes('query=Morgan') && request.url().includes('page_size=10'));
  await jump.tap();
  await jump.fill('Morgan');
  await commandPage.clock.runFor(350);
  await lookup;
  await commandPage.getByRole('button', { name: 'Open Morgan Hill' }).tap();
  await expect(commandPage).toHaveURL(/\/contacts\/2\?.*page_size=25/);
});

test('mobile directory and detail contain overflow in named strips only', async ({ commandPage }) => {
  await commandPage.goto('/admin/command/contacts');
  const tools = commandPage.getByRole('region', { name: 'Contacts tools' });
  await expect(tools).toBeVisible();
  const toolbar = tools.locator('.command-contacts-toolbar');
  const tableRegion = commandPage.getByRole('region', { name: 'Contacts directory table' });
  const smartViews = commandPage.getByRole('tablist', { name: 'Contact SmartViews' });
  for (const container of [tools, toolbar, tableRegion, smartViews]) {
    const box = await container.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390.5);
  }
  const tableOverflow = await tableRegion.evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth, overflow: getComputedStyle(element).overflowX }));
  expect(tableOverflow.scroll).toBeGreaterThan(tableOverflow.client);
  expect(tableOverflow.overflow).toMatch(/auto|scroll/);
  const smartViewOverflow = await smartViews.evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth, overflow: getComputedStyle(element).overflowX }));
  expect(smartViewOverflow.scroll).toBeGreaterThan(smartViewOverflow.client);
  expect(smartViewOverflow.overflow).toMatch(/auto|scroll/);

  for (const route of ['/admin/command/contacts', '/admin/command/contacts/1']) {
    await commandPage.goto(route);
    if (route.endsWith('/contacts')) await expect(commandPage.getByText('366 contacts')).toBeVisible();
    else await expect(commandPage.getByRole('heading', { name: 'Avery Lake' })).toBeVisible();
    await expect(commandPage.getByRole('main')).toBeVisible();
    const dimensions = await commandPage.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      document: document.documentElement.scrollWidth,
      offenders: Array.from(document.body.querySelectorAll<HTMLElement>('*')).map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName,
          className: element.className,
          left: Math.round(rect.left),
          right: Math.round(rect.right),
        };
      }).filter((item) => item.left < -1 || item.right > document.documentElement.clientWidth + 1).slice(0, 12),
    }));
    expect(dimensions.document, JSON.stringify(dimensions.offenders, null, 2)).toBeLessThanOrEqual(dimensions.viewport + 1);
  }
  await expect(commandPage.getByText(BROKEN_ARCHIVE_TIMELINE_VALUE, { exact: true })).toHaveCount(0);
  const expand = commandPage.getByRole('button', { name: 'Show full activity' });
  await expand.tap();
  await expect(commandPage.getByRole('heading', { name: LONG_REAL_TIMELINE_VALUE.trim() })).toBeVisible();
  const expandedDimensions = await commandPage.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    document: document.documentElement.scrollWidth,
  }));
  expect(expandedDimensions.document).toBeLessThanOrEqual(expandedDimensions.viewport + 1);
  const tabs = commandPage.getByRole('tablist', { name: 'Contact detail views' });
  const tabDimensions = await tabs.evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth, overflow: getComputedStyle(element).overflowX }));
  expect(tabDimensions.scroll).toBeGreaterThan(tabDimensions.client);
  expect(tabDimensions.overflow).toMatch(/auto|scroll/);
  const summary = commandPage.getByRole('complementary', { name: 'Contact workspace counts' });
  const summaryDimensions = await summary.evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth, overflow: getComputedStyle(element).overflowX }));
  expect(summaryDimensions.scroll).toBeGreaterThan(summaryDimensions.client);
  expect(summaryDimensions.overflow).toMatch(/auto|scroll/);
});

test('every visible Contacts directory and detail target is at least 44 CSS pixels', async ({ commandPage }) => {
  for (const route of ['/admin/command/contacts', '/admin/command/contacts/1']) {
    await commandPage.goto(route);
    if (route.endsWith('/contacts')) await expect(commandPage.getByText('366 contacts')).toBeVisible();
    else await expect(commandPage.getByRole('heading', { name: 'Avery Lake' })).toBeVisible();
    const targets = commandPage.locator('main a:visible, main button:visible, main input:visible, main select:visible');
    const count = await targets.count();
    expect(count).toBeGreaterThan(10);
    const undersized = await targets.evaluateAll((elements) => elements.map((element, index) => {
      const target = element instanceof HTMLInputElement && element.type === 'checkbox' ? element.closest('label') ?? element : element;
      const rect = target.getBoundingClientRect();
      return { index, label: element.getAttribute('aria-label') ?? element.textContent?.trim().slice(0, 80) ?? '', tag: element.tagName, width: rect.width, height: rect.height };
    }).filter((item) => item.width < 44 || item.height < 44));
    expect(undersized, `${route}\n${JSON.stringify(undersized, null, 2)}`).toEqual([]);
    const checkbox = commandPage.getByRole('checkbox').first();
    if (await checkbox.count()) {
      await checkbox.tap();
      await expect(checkbox).toBeChecked();
    }
  }
});
