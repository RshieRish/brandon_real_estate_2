import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import type { Page } from '@playwright/test';
import { expect, test } from './fixtures/command';

export function recordCommandFontRequests(page: Page): string[] {
  const requests: string[] = [];
  page.on('request', (request) => {
    if (request.resourceType() === 'font' || /\.(?:woff2?|ttf)(?:\?|$)/i.test(request.url())) requests.push(request.url());
  });
  return requests;
}

export async function assertCommandFonts(page: Page, requests: readonly string[]): Promise<void> {
  await page.evaluate(() => document.fonts.ready);
  const result = await page.evaluate(async () => {
    const weights = [400, 500, 600, 700, 800, 900];
    const loaded = await Promise.all(weights.map((weight) => document.fonts.load(`${weight} 16px "Montserrat Variable"`, 'Command')));
    return {
      loadedCounts: loaded.map((faces) => faces.length),
      family: getComputedStyle(document.body).fontFamily,
      loadedFaces: [...document.fonts].filter((face) => face.family.includes('Montserrat Variable') && face.status === 'loaded').length,
    };
  });
  expect(result.loadedCounts.every((count) => count > 0)).toBe(true);
  expect(result.loadedFaces).toBeGreaterThan(0);
  expect(result.family).toContain('Montserrat Variable');
  expect(requests.length).toBeGreaterThan(0);
  for (const request of requests) {
    const url = new URL(request);
    expect(url.origin).toBe(new URL(page.url()).origin);
    expect(url.hostname).not.toMatch(/googleapis|gstatic/);
  }
}

const currentDir = path.resolve(process.cwd(), 'artifacts/command-qa/current');

async function loadStableHome(commandPage: Page) {
  const fontRequests = recordCommandFontRequests(commandPage);
  await commandPage.goto('/admin/command');
  await expect(commandPage.getByRole('heading', { name: 'Follow-Up Readiness' })).toBeVisible();
  await expect(commandPage.getByRole('status', { name: 'Loading Command Home' })).toBeHidden();
  await assertCommandFonts(commandPage, fontRequests);
}

test.beforeAll(async () => {
  await mkdir(currentDir, { recursive: true });
});

test('Home desktop viewport and full page remain stable', async ({ commandPage }) => {
  await commandPage.setViewportSize({ width: 1800, height: 982 });
  await loadStableHome(commandPage);

  await expect(commandPage).toHaveScreenshot('home-desktop-1800x982.png', { animations: 'disabled' });
  await commandPage.screenshot({
    path: path.join(currentDir, 'home-desktop-1800x982.png'),
    animations: 'disabled',
  });
  await expect(commandPage).toHaveScreenshot('home-desktop-full.png', {
    animations: 'disabled',
    fullPage: true,
  });
  await commandPage.screenshot({
    path: path.join(currentDir, 'home-desktop-full.png'),
    animations: 'disabled',
    fullPage: true,
  });
});

test('Home tablet remains stable at the rail breakpoint', async ({ commandPage }) => {
  await commandPage.setViewportSize({ width: 1024, height: 768 });
  await loadStableHome(commandPage);

  await expect(commandPage).toHaveScreenshot('home-tablet-1024x768.png', { animations: 'disabled' });
});

test('Home mobile remains stable', async ({ commandPage }) => {
  await commandPage.setViewportSize({ width: 390, height: 844 });
  await loadStableHome(commandPage);

  await expect(commandPage).toHaveScreenshot('home-mobile-390x844.png', { animations: 'disabled' });
});

test('expanded desktop rail remains stable', async ({ commandPage }) => {
  await commandPage.setViewportSize({ width: 1800, height: 982 });
  await loadStableHome(commandPage);
  await commandPage.getByRole('button', { name: 'Expand Command navigation' }).click();
  await expect(commandPage.getByRole('dialog', { name: 'Expanded Command navigation' })).toBeVisible();

  await expect(commandPage).toHaveScreenshot('expanded-desktop-rail.png', { animations: 'disabled' });
});

test('open global search remains stable', async ({ commandPage }) => {
  await commandPage.setViewportSize({ width: 1800, height: 982 });
  await loadStableHome(commandPage);
  await commandPage.getByRole('button', { name: 'Search Command' }).click();
  await expect(commandPage.getByRole('dialog', { name: 'Search Command' })).toBeVisible();

  await expect(commandPage).toHaveScreenshot('open-global-search.png', { animations: 'disabled' });
});

test('open mobile drawer remains stable', async ({ commandPage }) => {
  await commandPage.setViewportSize({ width: 390, height: 844 });
  await loadStableHome(commandPage);
  await commandPage.getByRole('button', { name: 'Open Command navigation' }).click();
  await expect(commandPage.getByRole('dialog', { name: 'Command navigation' })).toBeVisible();

  await expect(commandPage).toHaveScreenshot('open-mobile-drawer.png', { animations: 'disabled' });
});

test('partial and evidence-only Home remains stable', async ({ commandPage, mockCommandEndpoint }) => {
  await mockCommandEndpoint('/contacts/directory?smart_view=all&sort=name&direction=asc&page=1&page_size=100', {
    rows: [], total: 0, page: 1, page_size: 100, page_count: 0, sort: 'name', direction: 'asc',
  });
  await mockCommandEndpoint('/celebrations?month=8', { detail: 'Celebrations unavailable' }, 503);
  await commandPage.setViewportSize({ width: 1800, height: 982 });
  await loadStableHome(commandPage);
  await expect(commandPage.getByText(/inputs verified · Partial readiness/)).toBeVisible();

  await expect(commandPage).toHaveScreenshot('partial-evidence-home.png', { animations: 'disabled' });
});
