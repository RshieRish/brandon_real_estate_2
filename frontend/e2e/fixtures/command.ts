import { expect, test as base, type Page, type Route } from '@playwright/test';
import home from './command-home.json';

const FIXED_TIME = new Date('2026-08-12T13:00:00.000Z');
const COMMAND_PREFIX = '/api/v1/command';

type MockResponse = Readonly<{
  status: number;
  body: unknown;
}>;

type FailureResponse = MockResponse & {
  remaining: number;
};

type RouteState = {
  responses: Map<string, MockResponse>;
  failures: Map<string, FailureResponse>;
  expectedHttpFailures: Set<string>;
};

type CommandFixtures = {
  commandPage: Page;
  mockCommandEndpoint: (path: string, response: unknown, status?: number) => Promise<void>;
  failCommandEndpointOnce: (path: string, status: number, detail: string) => Promise<void>;
  routeState: RouteState;
};

function normalizeCommandPath(path: string): string {
  if (/^https?:\/\//.test(path)) {
    const url = new URL(path);
    return normalizeCommandPath(`${url.pathname}${url.search}`);
  }
  if (path.startsWith(COMMAND_PREFIX)) return path.slice(COMMAND_PREFIX.length) || '/';
  return path.startsWith('/') ? path : `/${path}`;
}

function defaultCommandResponse(url: URL, method: string): MockResponse {
  const path = url.pathname.slice(COMMAND_PREFIX.length) || '/';

  if (path === '/overview') return { status: 200, body: home.overview };
  if (path === '/contacts') {
    const offset = Number(url.searchParams.get('offset') ?? '0');
    return { status: 200, body: offset === 0 ? home.contacts : [] };
  }
  if (path === '/tasks' && method === 'GET') return { status: 200, body: home.tasks };
  if (path === '/tasks' && method === 'POST') {
    return {
      status: 201,
      body: {
        id: 99,
        title: 'Synthetic task',
        contact_id: null,
        description: '',
        priority: 'normal',
        due_at: null,
        status: 'open',
      },
    };
  }
  if (path === '/opportunities') return { status: 200, body: home.opportunities };
  if (path === '/celebrations') return { status: 200, body: home.celebrations };
  if (path === '/goals') return { status: 200, body: home.goals };
  if (/^\/goals\/\d+$/.test(path) && method === 'PATCH') return { status: 200, body: home.goals[0] };
  if (path === '/ai/briefing') return { status: 200, body: home.briefing };
  if (path === '/agreements' || path === '/agreement-templates') return { status: 200, body: [] };
  if (path === '/contacts/1/workspace') {
    return {
      status: 200,
      body: {
        contact: home.contacts[0],
        timeline: [],
        tasks: home.tasks.filter((task) => task.contact_id === 1),
        notes: [],
        smart_plans: [],
        opportunities: home.opportunities.slice(0, 1),
        saved_searches: [],
        bookings: [],
        tags: [],
      },
    };
  }
  return { status: 200, body: [] };
}

function responseFor(state: RouteState, url: URL, method: string): MockResponse {
  const normalized = `${url.pathname.slice(COMMAND_PREFIX.length) || '/'}${url.search}`;
  const pathOnly = url.pathname.slice(COMMAND_PREFIX.length) || '/';
  const failure = state.failures.get(normalized) ?? state.failures.get(pathOnly);
  if (failure?.remaining) {
    failure.remaining -= 1;
    return failure;
  }
  return state.responses.get(normalized)
    ?? state.responses.get(pathOnly)
    ?? defaultCommandResponse(url, method);
}

async function fulfillApiRoute(route: Route, state: RouteState): Promise<void> {
  const request = route.request();
  const url = new URL(request.url());
  const authorization = request.headers().authorization;
  if (authorization !== 'Bearer test-admin-token') {
    await route.fulfill({ status: 401, json: { detail: 'Missing deterministic test authorization' } });
    return;
  }

  if (url.pathname === '/api/v1/auth/me') {
    await route.fulfill({ status: 200, json: home.authMe });
    return;
  }
  if (!url.pathname.startsWith(COMMAND_PREFIX)) {
    await route.continue();
    return;
  }

  const response = responseFor(state, url, request.method());
  await route.fulfill({ status: response.status, json: response.body });
}

export const test = base.extend<CommandFixtures>({
  routeState: async ({}, use) => {
    await use({ responses: new Map(), failures: new Map(), expectedHttpFailures: new Set() });
  },

  mockCommandEndpoint: async ({ routeState }, use) => {
    await use(async (path, response, status = 200) => {
      const normalized = normalizeCommandPath(path);
      routeState.responses.set(normalized, { status, body: structuredClone(response) });
      if (status >= 400) routeState.expectedHttpFailures.add(normalized.split('?')[0]);
    });
  },

  failCommandEndpointOnce: async ({ routeState }, use) => {
    await use(async (path, status, detail) => {
      const normalized = normalizeCommandPath(path);
      routeState.failures.set(normalized, {
        status,
        body: { detail },
        remaining: 1,
      });
      routeState.expectedHttpFailures.add(normalized.split('?')[0]);
    });
  },

  commandPage: async ({ page, routeState }, use, testInfo) => {
    const browserErrors: string[] = [];

    page.on('console', (message) => {
      if (message.type() === 'error') {
        const location = message.location();
        if (message.text().startsWith('Failed to load resource') && location.url) {
          const url = new URL(location.url);
          if (
            url.pathname.startsWith(COMMAND_PREFIX)
            && routeState.expectedHttpFailures.has(url.pathname.slice(COMMAND_PREFIX.length) || '/')
          ) return;
        }
        browserErrors.push(`console: ${message.text()}${location.url ? ` (${location.url}:${location.lineNumber})` : ''}`);
      }
    });
    page.on('pageerror', (error) => {
      browserErrors.push(`pageerror: ${error.stack ?? error.message}`);
    });

    await page.addInitScript(() => {
      window.localStorage.setItem('admin_token', 'test-admin-token');
    });
    await page.clock.install({ time: FIXED_TIME });
    await page.route('**/api/v1/**', (route) => fulfillApiRoute(route, routeState));

    await use(page);

    if (browserErrors.length > 0) {
      testInfo.annotations.push({ type: 'browser-errors', description: browserErrors.join('\n') });
      throw new Error(`Unexpected browser errors:\n${browserErrors.join('\n')}`);
    }
  },
});

export { expect };
export { home as commandHomeFixture };
