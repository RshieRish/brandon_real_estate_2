import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { expect, test } from './fixtures/command';

function recordCommandFontRequests(page: import('@playwright/test').Page): string[] {
  const requests: string[] = [];
  page.on('request', (request) => {
    if (request.resourceType() === 'font' || /\.(?:woff2?|ttf)(?:\?|$)/i.test(request.url())) requests.push(request.url());
  });
  return requests;
}

async function assertCommandFonts(page: import('@playwright/test').Page, requests: readonly string[]): Promise<void> {
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
const crossRunnerPixelNoiseBudget = 20;

test.beforeAll(async () => { await mkdir(currentDir, { recursive: true }); });

async function stable(page: import('@playwright/test').Page, route: string, width: number, height: number) {
  const fontRequests = recordCommandFontRequests(page);
  await page.setViewportSize({ width, height });
  await page.goto(route);
  await expect(page.getByRole('main')).toBeVisible();
  await assertCommandFonts(page, fontRequests);
}

test('Contacts directory desktop synthetic baseline', async ({ commandPage }) => {
  await stable(commandPage, '/admin/command/contacts', 1800, 982);
  await expect(commandPage.getByText('366 contacts')).toBeVisible();
  await expect(commandPage).toHaveScreenshot('contacts-directory-desktop-1800x982.png', { animations: 'disabled', maxDiffPixels: crossRunnerPixelNoiseBudget });
  await commandPage.screenshot({ path: path.join(currentDir, 'contacts-directory-desktop-1800x982.png'), animations: 'disabled' });
});

test('Contact detail Timeline desktop synthetic baseline', async ({ commandPage }) => {
  await stable(commandPage, '/admin/command/contacts/1', 1793, 1166);
  await expect(commandPage.getByRole('heading', { name: 'Avery Lake' })).toBeVisible();
  await expect(commandPage).toHaveScreenshot('contact-detail-timeline-desktop-1793x1166.png', { animations: 'disabled', maxDiffPixels: crossRunnerPixelNoiseBudget });
});

for (const [name, tab] of [['opportunities', 'Opportunities'], ['notes', 'Notes'], ['source-evidence', 'Source Evidence']] as const) {
  test(`Contact detail ${tab} desktop synthetic baseline`, async ({ commandPage }) => {
    await stable(commandPage, '/admin/command/contacts/1', 1793, 1166);
    await commandPage.getByRole('tab', { name: tab }).click();
    await expect(commandPage.getByRole('tabpanel', { name: tab })).toBeVisible();
    await expect(commandPage).toHaveScreenshot(`contact-detail-${name}-desktop-1793x1166.png`, { animations: 'disabled', maxDiffPixels: crossRunnerPixelNoiseBudget });
  });
}

test('Contacts directory mobile synthetic baseline', async ({ commandPage }) => {
  await stable(commandPage, '/admin/command/contacts', 390, 844);
  await expect(commandPage.getByText('366 contacts')).toBeVisible();
  await expect(commandPage).toHaveScreenshot('contacts-directory-mobile-390x844.png', { animations: 'disabled', maxDiffPixels: crossRunnerPixelNoiseBudget });
});

test('Contact detail mobile synthetic baseline', async ({ commandPage }) => {
  await stable(commandPage, '/admin/command/contacts/1', 390, 844);
  await expect(commandPage.getByRole('heading', { name: 'Avery Lake' })).toBeVisible();
  await expect(commandPage).toHaveScreenshot('contact-detail-mobile-390x844.png', { animations: 'disabled', maxDiffPixels: crossRunnerPixelNoiseBudget });
});
