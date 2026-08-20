import { expect, test as base, type Page, type Route } from '@playwright/test';
import home from './command-home.json';
import {
  createCommandContactsFixtureState,
  handleCommandContactsRequest,
  type CommandContactsFixtureState,
} from './command-contacts';

const FIXED_TIME = new Date('2026-08-12T13:00:00.000Z');
const COMMAND_PREFIX = '/api/v1/command';

type MockResponse = Readonly<{
  status: number;
  body?: unknown;
  binaryBody?: Buffer;
  headers?: Readonly<Record<string, string>>;
}>;

type FailureResponse = MockResponse & {
  remaining: number;
};

type BuiltInCommandMock = Readonly<{
  method: string;
  path: string | RegExp;
  query?: string;
  respond: (url: URL) => MockResponse;
}>;

type RouteState = {
  responses: Map<string, Map<string, MockResponse>>;
  failures: Map<string, Map<string, FailureResponse>>;
  expectedHttpFailures: ExpectedHttpFailures;
  contacts: CommandContactsFixtureState;
};

class ExpectedHttpFailures {
  private readonly declared = new Map<string, number>();
  private readonly awaitingConsole = new Map<string, number>();

  add(path: string, method = 'GET', count = 1): void {
    const normalized = normalizeCommandPath(path);
    const identity = `${method.toUpperCase()} ${normalized}`;
    this.declared.set(identity, (this.declared.get(identity) ?? 0) + count);
  }

  registerResponse(path: string, method: string): void {
    const identity = `${method.toUpperCase()} ${path}`;
    const remaining = this.declared.get(identity) ?? 0;
    if (remaining < 1) return;
    if (remaining === 1) this.declared.delete(identity);
    else this.declared.set(identity, remaining - 1);
    this.awaitingConsole.set(path, (this.awaitingConsole.get(path) ?? 0) + 1);
  }

  consumeConsole(path: string): boolean {
    const remaining = this.awaitingConsole.get(path) ?? 0;
    if (remaining < 1) return false;
    if (remaining === 1) this.awaitingConsole.delete(path);
    else this.awaitingConsole.set(path, remaining - 1);
    return true;
  }
}

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

function safeRequestIdentity(method: string, url: URL, path = url.pathname): string {
  const queryKeys = [...new Set(url.searchParams.keys())];
  const query = queryKeys.length > 0 ? `?${queryKeys.map((key) => `${key}=<redacted>`).join('&')}` : '';
  return `${method} ${path}${query}`;
}

const BUILT_IN_COMMAND_MOCKS: readonly BuiltInCommandMock[] = [
  { method: 'GET', path: '/overview', query: '', respond: () => ({ status: 200, body: home.overview }) },
  {
    method: 'GET',
    path: '/contacts',
    query: '',
    respond: (url) => ({
      status: 200,
      body: Number(url.searchParams.get('offset') ?? '0') === 0 ? home.contacts : [],
    }),
  },
  {
    method: 'GET',
    path: '/tasks',
    query: '?visibility=active',
    respond: () => ({
      status: 200,
      body: home.tasks.filter((task) => (
        task.archived_at === null
        && (task.status === 'open' || task.status === 'in_progress')
      )),
    }),
  },
  {
    method: 'GET',
    path: '/tasks',
    query: '?visibility=all',
    respond: () => ({ status: 200, body: home.tasks }),
  },
  {
    method: 'POST',
    path: '/tasks',
    query: '',
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
        archived_at: null,
        archive_reason: null,
        version: 1,
      },
    }),
  },
  { method: 'GET', path: '/opportunities', query: '', respond: () => ({ status: 200, body: home.opportunities }) },
  { method: 'GET', path: '/goals', query: '', respond: () => ({ status: 200, body: home.goals }) },
  { method: 'PATCH', path: /^\/goals\/\d+$/, query: '', respond: () => ({ status: 200, body: home.goals[0] }) },
  { method: 'GET', path: '/ai/briefing', query: '', respond: () => ({ status: 200, body: home.briefing }) },
  { method: 'GET', path: '/agreements', query: '', respond: () => ({ status: 200, body: [] }) },
  { method: 'GET', path: '/agreement-templates', query: '', respond: () => ({ status: 200, body: [] }) },
  {
    method: 'GET',
    path: '/contacts/1/workspace',
    query: '',
    respond: () => ({
      status: 200,
      body: {
        contact: home.contacts[0],
        timeline: [],
        tasks: home.tasks
          .filter((task) => task.contact_id === 1)
          .map((task) => ({
            id: task.id,
            title: task.title,
            contact_id: task.contact_id,
            description: task.description,
            priority: task.priority,
            due_at: task.due_at,
            status: task.archived_at === null ? task.status : 'archived',
          })),
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
    && (candidate.query === undefined || candidate.query === url.search)
  ));
  if (builtIn) return builtIn.respond(url);

  const requestIdentity = safeRequestIdentity(method, url, path);
  return {
    status: 500,
    body: {
      detail: `Unexpected Command fixture request: ${requestIdentity}. Add an explicit deterministic response or mock the endpoint in this test.`,
    },
  };
}

function responseFor(state: RouteState, url: URL, method: string): MockResponse {
  const normalized = `${url.pathname.slice(COMMAND_PREFIX.length) || '/'}${url.search}`;
  const failure = state.failures.get(normalized)?.get(method);
  if (failure?.remaining) {
    failure.remaining -= 1;
    return failure;
  }
  return state.responses.get(normalized)
    ?.get(method)
    ?? defaultCommandResponse(url, method);
}

async function fulfillApiRoute(route: Route, state: RouteState): Promise<void> {
  const request = route.request();
  const url = new URL(request.url());
  const authorization = request.headers().authorization;
  if (authorization !== 'Bearer test-admin-token') {
    const normalized = url.pathname.startsWith(COMMAND_PREFIX)
      ? `${url.pathname.slice(COMMAND_PREFIX.length) || '/'}${url.search}`
      : `${url.pathname}${url.search}`;
    state.expectedHttpFailures.registerResponse(normalized, request.method());
    await route.fulfill({ status: 401, json: { detail: 'Missing deterministic test authorization' } });
    return;
  }

  if (url.pathname === '/api/v1/auth/me' && request.method() === 'GET' && url.search.length === 0) {
    await route.fulfill({ status: 200, json: home.authMe });
    return;
  }
  if (url.pathname === '/api/v1/auth/me') {
    state.expectedHttpFailures.registerResponse(`${url.pathname}${url.search}`, request.method());
    await route.fulfill({ status: 500, json: { detail: `Unexpected auth fixture request: ${safeRequestIdentity(request.method(), url)}` } });
    return;
  }
  if (!url.pathname.startsWith(COMMAND_PREFIX)) {
    state.expectedHttpFailures.registerResponse(`${url.pathname}${url.search}`, request.method());
    await route.fulfill({
      status: 500,
      json: { detail: `Unexpected API fixture request: ${safeRequestIdentity(request.method(), url)}` },
    });
    return;
  }

  const normalized = `${url.pathname.slice(COMMAND_PREFIX.length) || '/'}${url.search}`;
  const hasOverride = (state.failures.get(normalized)?.get(request.method())?.remaining ?? 0) > 0
    || state.responses.get(normalized)?.has(request.method());
  const response = hasOverride
    ? responseFor(state, url, request.method())
    : handleCommandContactsRequest(state.contacts, request, url) ?? responseFor(state, url, request.method());
  if (response.status >= 400) state.expectedHttpFailures.registerResponse(normalized, request.method());
  if (response.binaryBody !== undefined) {
    await route.fulfill({ status: response.status, body: response.binaryBody, headers: response.headers });
  } else {
    await route.fulfill({ status: response.status, json: response.body, headers: response.headers });
  }
}

export const test = base.extend<CommandFixtures>({
  routeState: async ({}, provideFixture) => {
    await provideFixture({
      responses: new Map(),
      failures: new Map(),
      expectedHttpFailures: new ExpectedHttpFailures(),
      contacts: createCommandContactsFixtureState(),
    });
  },

  mockCommandEndpoint: async ({ routeState }, provideFixture) => {
    await provideFixture(async (path, response, status = 200, method = 'GET') => {
      const normalized = normalizeCommandPath(path);
      const responsesByMethod = routeState.responses.get(normalized) ?? new Map<string, MockResponse>();
      responsesByMethod.set(method.toUpperCase(), { status, body: structuredClone(response) });
      routeState.responses.set(normalized, responsesByMethod);
      if (status >= 400) routeState.expectedHttpFailures.add(normalized, method);
    });
  },

  failCommandEndpointOnce: async ({ routeState }, provideFixture) => {
    await provideFixture(async (path, status, detail, method = 'GET') => {
      const normalized = normalizeCommandPath(path);
      const failuresByMethod = routeState.failures.get(normalized) ?? new Map<string, FailureResponse>();
      failuresByMethod.set(method.toUpperCase(), {
        status,
        body: { detail },
        remaining: 1,
      });
      routeState.failures.set(normalized, failuresByMethod);
      routeState.expectedHttpFailures.add(normalized, method);
    });
  },

  commandPage: async ({ page, routeState }, provideFixture, testInfo) => {
    const browserErrors: string[] = [];

    page.on('console', (message) => {
      if (message.type() === 'error') {
        const location = message.location();
        if (message.text().startsWith('Failed to load resource') && location.url) {
          const url = new URL(location.url);
          const normalized = url.pathname.startsWith(COMMAND_PREFIX)
            ? `${url.pathname.slice(COMMAND_PREFIX.length) || '/'}${url.search}`
            : `${url.pathname}${url.search}`;
          if (routeState.expectedHttpFailures.consumeConsole(normalized)) {
            return;
          }
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
    const appOrigin = new URL(String(testInfo.project.use.baseURL)).origin;
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (!['http:', 'https:'].includes(url.protocol) || url.origin === appOrigin) {
        await route.fallback();
        return;
      }
      routeState.expectedHttpFailures.registerResponse(`${url.pathname}${url.search}`, route.request().method());
      await route.abort('blockedbyclient');
    });
    await page.route('**/api/v1/**', (route) => fulfillApiRoute(route, routeState));

    await provideFixture(page);

    if (browserErrors.length > 0) {
      testInfo.annotations.push({ type: 'browser-errors', description: browserErrors.join('\n') });
      throw new Error(`Unexpected browser errors:\n${browserErrors.join('\n')}`);
    }
  },
});

export { expect };
export { home as commandHomeFixture };
