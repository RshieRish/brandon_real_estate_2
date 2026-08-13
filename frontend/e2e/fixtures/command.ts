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

type BuiltInCommandMock = Readonly<{
  method: string;
  path: string | RegExp;
  respond: (url: URL) => MockResponse;
}>;

type RouteState = {
  responses: Map<string, Map<string, MockResponse>>;
  failures: Map<string, Map<string, FailureResponse>>;
  expectedHttpFailures: Set<string>;
};

type CommandFixtures = {
  commandPage: Page;
  mockCommandEndpoint: (path: string, response: unknown, status?: number, method?: string) => Promise<void>;
  failCommandEndpointOnce: (path: string, status: number, detail: string, method?: string) => Promise<void>;
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

const BUILT_IN_COMMAND_MOCKS: readonly BuiltInCommandMock[] = [
  { method: 'GET', path: '/overview', respond: () => ({ status: 200, body: home.overview }) },
  {
    method: 'GET',
    path: '/contacts',
    respond: (url) => ({
      status: 200,
      body: Number(url.searchParams.get('offset') ?? '0') === 0 ? home.contacts : [],
    }),
  },
  { method: 'GET', path: '/tasks', respond: () => ({ status: 200, body: home.tasks }) },
  {
    method: 'POST',
    path: '/tasks',
    respond: () => ({
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
    }),
  },
  { method: 'GET', path: '/opportunities', respond: () => ({ status: 200, body: home.opportunities }) },
  { method: 'GET', path: '/celebrations', respond: () => ({ status: 200, body: home.celebrations }) },
  { method: 'GET', path: '/goals', respond: () => ({ status: 200, body: home.goals }) },
  { method: 'PATCH', path: /^\/goals\/\d+$/, respond: () => ({ status: 200, body: home.goals[0] }) },
  { method: 'GET', path: '/ai/briefing', respond: () => ({ status: 200, body: home.briefing }) },
  { method: 'GET', path: '/agreements', respond: () => ({ status: 200, body: [] }) },
  { method: 'GET', path: '/agreement-templates', respond: () => ({ status: 200, body: [] }) },
  {
    method: 'GET',
    path: '/contacts/1/workspace',
    respond: () => ({
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
    }),
  },
];

function defaultCommandResponse(url: URL, method: string): MockResponse {
  const path = url.pathname.slice(COMMAND_PREFIX.length) || '/';
  const builtIn = BUILT_IN_COMMAND_MOCKS.find((candidate) => (
    candidate.method === method
    && (typeof candidate.path === 'string' ? candidate.path === path : candidate.path.test(path))
  ));
  if (builtIn) return builtIn.respond(url);

  const requestIdentity = `${method} ${path}${url.search}`;
  return {
    status: 500,
    body: {
      detail: `Unexpected Command fixture request: ${requestIdentity}. Add an explicit deterministic response or mock the endpoint in this test.`,
    },
  };
}

function responseFor(state: RouteState, url: URL, method: string): MockResponse {
  const normalized = `${url.pathname.slice(COMMAND_PREFIX.length) || '/'}${url.search}`;
  const pathOnly = url.pathname.slice(COMMAND_PREFIX.length) || '/';
  const failure = state.failures.get(normalized)?.get(method) ?? state.failures.get(pathOnly)?.get(method);
  if (failure?.remaining) {
    failure.remaining -= 1;
    return failure;
  }
  return state.responses.get(normalized)
    ?.get(method)
    ?? state.responses.get(pathOnly)?.get(method)
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
    await use(async (path, response, status = 200, method = 'GET') => {
      const normalized = normalizeCommandPath(path);
      const responsesByMethod = routeState.responses.get(normalized) ?? new Map<string, MockResponse>();
      responsesByMethod.set(method.toUpperCase(), { status, body: structuredClone(response) });
      routeState.responses.set(normalized, responsesByMethod);
      if (status >= 400) routeState.expectedHttpFailures.add(normalized.split('?')[0]);
    });
  },

  failCommandEndpointOnce: async ({ routeState }, use) => {
    await use(async (path, status, detail, method = 'GET') => {
      const normalized = normalizeCommandPath(path);
      const failuresByMethod = routeState.failures.get(normalized) ?? new Map<string, FailureResponse>();
      failuresByMethod.set(method.toUpperCase(), {
        status,
        body: { detail },
        remaining: 1,
      });
      routeState.failures.set(normalized, failuresByMethod);
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
