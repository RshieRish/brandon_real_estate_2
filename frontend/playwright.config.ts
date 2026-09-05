import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [['html', { open: 'never' }], ['github']]
    : [['list'], ['html', { open: 'never' }]],
  timeout: 30_000,
  expect: {
    timeout: 5_000,
    toHaveScreenshot: {
      animations: 'disabled',
      maxDiffPixelRatio: 0.01,
      threshold: 0.2,
    },
  },
  use: {
    baseURL: 'http://127.0.0.1:3100',
    locale: 'en-US',
    timezoneId: 'America/New_York',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'command-desktop',
      testMatch: [
        '**/command-shell.spec.ts',
        '**/command-home.spec.ts',
        '**/command-contacts.spec.ts',
        '**/command-tasks.spec.ts',
        '**/command-archive.spec.ts',
      ],
      use: { ...devices['Desktop Chrome'], viewport: { width: 1800, height: 982 } },
    },
    {
      name: 'command-mobile',
      testMatch: [
        '**/command-mobile.spec.ts',
        '**/command-contacts-mobile.spec.ts',
        '**/command-tasks.spec.ts',
        '**/command-archive.spec.ts',
      ],
      use: { ...devices['iPhone 14'], browserName: 'chromium', viewport: { width: 390, height: 844 } },
    },
    {
      name: 'command-a11y',
      testMatch: [
        '**/command-accessibility.spec.ts',
        '**/command-contacts-accessibility.spec.ts',
        '**/command-tasks.spec.ts',
      ],
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'command-visual',
      testMatch: ['**/command-visual.spec.ts', '**/command-contacts-visual.spec.ts'],
      use: { ...devices['Desktop Chrome'], viewport: { width: 1800, height: 982 } },
    },
  ],
  webServer: {
    command: process.env.CI
      ? 'npm run build && npm run start -- --hostname 127.0.0.1 --port 3100'
      : 'npm run dev -- --hostname 127.0.0.1 --port 3100',
    url: 'http://127.0.0.1:3100/admin/login',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
