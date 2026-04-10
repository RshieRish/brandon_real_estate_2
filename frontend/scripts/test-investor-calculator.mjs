import { chromium } from 'playwright';

const baseUrl = 'http://localhost:3000/invest';
const instantScreenshot = '/Users/rishabnandi/brandon-real-estate/investor-instant-results-check.png';
const fullReportScreenshot = '/Users/rishabnandi/brandon-real-estate/investor-full-report-check.png';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 2200 } });

async function fillNumber(label, value) {
  const input = page.getByLabel(label);
  await input.click();
  await input.fill(String(value));
}

try {
  console.log('STEP: goto');
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Purchase Price').waitFor({ timeout: 30000 });

  console.log('STEP: fill inputs');
  await fillNumber('Purchase Price', 415000);
  await fillNumber('Rehab / Renovation Cost', 48769.63);
  await fillNumber('After-Repair Value (ARV)', 570000);
  await fillNumber('Hold Period', 6);
  await fillNumber('Monthly Rental Income', 0);
  await fillNumber('Property Tax / Year', 0);
  await fillNumber('Annual Insurance', 0);
  await fillNumber('Down Payment %', 15);
  await fillNumber('Interest Rate', 7);
  await fillNumber('Loan Term', 30);

  console.log('STEP: capture instant');
  const instantCard = page.getByText('Instant Snapshot').first();
  await instantCard.scrollIntoViewIfNeeded();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: instantScreenshot, fullPage: true });

  const resultTexts = await page.locator('div.glass.border.border-dark-border.rounded-xl').allInnerTexts();
  console.log('VISIBLE_CARDS_START');
  console.log(resultTexts.join('\n---\n'));
  console.log('VISIBLE_CARDS_END');

  console.log('STEP: unlock full report');
  await page.getByLabel('Name').fill('Codex Test');
  await page.getByLabel('Email Address').fill('codex-test@example.com');
  await page.getByLabel('Phone Number').fill('9785550101');
  await page.getByRole('button', { name: /Unlock Full Report/i }).click();

  await page.getByText('Full AI Report Unlocked').waitFor({ timeout: 90000 });
  console.log('STEP: capture full report');
  await page.waitForTimeout(1000);
  await page.screenshot({ path: fullReportScreenshot, fullPage: true });

  console.log('FULL_REPORT_READY');
} finally {
  await browser.close();
}
