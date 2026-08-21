import AxeBuilder from '@axe-core/playwright';
import type { Locator, Page, Request, Route } from '@playwright/test';
import { expect, test as commandTest } from './fixtures/command';
import type { CommandFixtureTask } from './fixtures/command-contacts';

const TASK_ROUTE = '**/api/v1/command/tasks**';
const TASK_PATH = '/api/v1/command/tasks';
const ARCHIVED_AT = '2026-08-12T13:00:00.000Z';
const DATABASE_INTEGER_MAX = 2_147_483_647;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

type LifecycleAction = 'archive' | 'restore';
type LifecycleOutcome = 'ack' | 'conflict' | 'uncertain-applied' | 'uncertain-unchanged';
type TaskWorkflowStatus = 'open' | 'in_progress' | 'completed' | 'cancelled';
type LifecycleRequestBody = Readonly<{
  request_id: string;
  expected_version: number;
  reason?: string;
}>;
type LifecycleRequestRecord = Readonly<{
  action: LifecycleAction;
  taskId: number;
  body: LifecycleRequestBody;
  outcome: LifecycleOutcome | 'replay' | 'request-mismatch' | 'version-conflict';
}>;
type ReplaySnapshot = Readonly<{
  fingerprint: string;
  task: CommandFixtureTask;
}>;
type TaskLifecycleApi = Readonly<{
  setNextOutcome: (outcome: LifecycleOutcome) => void;
  setTaskStatus: (taskId: number, status: TaskWorkflowStatus) => void;
  requestsFor: (action: LifecycleAction, taskId: number) => readonly LifecycleRequestRecord[];
}>;

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (typeof value === 'object' && value !== null) {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => `${JSON.stringify(key)}:${canonicalJson(child)}`)
      .join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

function decodeLifecycleBody(request: Request): LifecycleRequestBody | null {
  let input: unknown;
  try {
    input = request.postDataJSON();
  } catch {
    return null;
  }
  if (typeof input !== 'object' || input === null || Array.isArray(input)) return null;
  const body = input as Record<string, unknown>;
  const keys = Object.keys(body);
  if (
    keys.some((key) => !['request_id', 'expected_version', 'reason'].includes(key))
    || !keys.includes('request_id')
    || !keys.includes('expected_version')
    || typeof body.request_id !== 'string'
    || !UUID_PATTERN.test(body.request_id)
    || typeof body.expected_version !== 'number'
    || !Number.isInteger(body.expected_version)
    || body.expected_version < 1
    || body.expected_version > DATABASE_INTEGER_MAX
    || ('reason' in body && (typeof body.reason !== 'string' || Array.from(body.reason).length > 500))
  ) return null;
  const decoded: { request_id: string; expected_version: number; reason?: string } = {
    request_id: body.request_id,
    expected_version: body.expected_version,
  };
  if (typeof body.reason === 'string') decoded.reason = body.reason;
  return decoded;
}

function taskConflict(code: 'task_version_conflict' | 'task_archived' | 'task_request_mismatch', task: CommandFixtureTask) {
  return {
    detail: {
      code,
      current_version: task.version,
      current_task: structuredClone(task),
    },
  };
}

function lifecycleTask(
  task: CommandFixtureTask,
  action: LifecycleAction,
  body: LifecycleRequestBody,
): CommandFixtureTask {
  return action === 'archive'
    ? {
        ...task,
        archived_at: ARCHIVED_AT,
        archive_reason: body.reason ?? null,
        version: task.version + 1,
      }
    : {
        ...task,
        archived_at: null,
        archive_reason: null,
        version: task.version + 1,
      };
}

async function fulfillJson(route: Route, status: number, body: unknown): Promise<void> {
  await route.fulfill({ status, json: structuredClone(body) });
}

const test = commandTest.extend<{ taskLifecycleApi: TaskLifecycleApi }>({
  taskLifecycleApi: async ({ commandPage, routeState }, provideFixture) => {
    let nextOutcome: LifecycleOutcome = 'ack';
    const requests: LifecycleRequestRecord[] = [];
    const replaySnapshots = new Map<string, ReplaySnapshot>();

    const record = (
      action: LifecycleAction,
      taskId: number,
      body: LifecycleRequestBody,
      outcome: LifecycleRequestRecord['outcome'],
    ) => {
      requests.push({ action, taskId, body: structuredClone(body), outcome });
    };
    const replaceTask = (replacement: CommandFixtureTask) => {
      const index = routeState.tasks.findIndex((task) => task.id === replacement.id);
      if (index >= 0) routeState.tasks[index] = structuredClone(replacement);
    };
    const expectHttpFailure = (url: URL, method: string) => {
      const path = `${url.pathname.slice('/api/v1/command'.length)}${url.search}`;
      routeState.expectedHttpFailures.add(path, method);
      routeState.expectedHttpFailures.registerResponse(path, method);
    };

    const handler = async (route: Route) => {
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();
      if (url.pathname !== TASK_PATH && !/^\/api\/v1\/command\/tasks\/[1-9]\d*\/(?:archive|restore)$/.test(url.pathname)) {
        await route.fallback();
        return;
      }
      if (request.headers().authorization !== 'Bearer test-admin-token') {
        expectHttpFailure(url, method);
        await fulfillJson(route, 401, { detail: 'Missing deterministic test authorization' });
        return;
      }

      if (url.pathname === TASK_PATH) {
        if (
          method !== 'GET'
          || [...url.searchParams.keys()].length !== 1
          || url.searchParams.getAll('visibility').length !== 1
        ) {
          await route.fallback();
          return;
        }
        const visibility = url.searchParams.get('visibility');
        if (visibility !== 'active' && visibility !== 'archived' && visibility !== 'all') {
          await route.fallback();
          return;
        }
        const tasks = routeState.tasks.filter((task) => (
          visibility === 'all'
          || (visibility === 'active' ? task.archived_at === null : task.archived_at !== null)
        ));
        await fulfillJson(route, 200, tasks);
        return;
      }

      const match = /^\/api\/v1\/command\/tasks\/([1-9]\d*)\/(archive|restore)$/.exec(url.pathname);
      if (match === null || method !== 'POST' || url.search.length > 0) {
        await route.fallback();
        return;
      }
      const taskId = Number(match[1]);
      const action = match[2] as LifecycleAction;
      const body = decodeLifecycleBody(request);
      if (body === null) {
        expectHttpFailure(url, method);
        await fulfillJson(route, 422, { detail: 'Invalid deterministic task lifecycle request' });
        return;
      }
      const task = routeState.tasks.find((candidate) => candidate.id === taskId);
      if (task === undefined) {
        expectHttpFailure(url, method);
        await fulfillJson(route, 404, { detail: 'Task not found' });
        return;
      }

      const replayKey = `${action}:${taskId}:${body.request_id}`;
      const fingerprint = canonicalJson(body);
      const replay = replaySnapshots.get(replayKey);
      if (replay !== undefined) {
        if (replay.fingerprint !== fingerprint) {
          record(action, taskId, body, 'request-mismatch');
          expectHttpFailure(url, method);
          await fulfillJson(route, 409, taskConflict('task_request_mismatch', task));
          return;
        }
        record(action, taskId, body, 'replay');
        await fulfillJson(route, 200, replay.task);
        return;
      }

      if (body.expected_version !== task.version) {
        record(action, taskId, body, 'version-conflict');
        expectHttpFailure(url, method);
        await fulfillJson(route, 409, taskConflict('task_version_conflict', task));
        return;
      }
      if (action === 'archive' && task.archived_at !== null) {
        record(action, taskId, body, 'version-conflict');
        expectHttpFailure(url, method);
        await fulfillJson(route, 409, taskConflict('task_archived', task));
        return;
      }
      if (action === 'restore' && task.archived_at === null) {
        record(action, taskId, body, 'version-conflict');
        expectHttpFailure(url, method);
        await fulfillJson(route, 409, taskConflict('task_version_conflict', task));
        return;
      }

      const outcome = nextOutcome;
      nextOutcome = 'ack';
      if (outcome === 'conflict') {
        const authoritative = {
          ...task,
          description: 'Changed by another administrator',
          version: task.version + 1,
        };
        replaceTask(authoritative);
        record(action, taskId, body, outcome);
        expectHttpFailure(url, method);
        await fulfillJson(route, 409, taskConflict('task_version_conflict', authoritative));
        return;
      }
      if (outcome === 'uncertain-unchanged') {
        record(action, taskId, body, outcome);
        expectHttpFailure(url, method);
        await fulfillJson(route, 503, { detail: 'Synthetic outcome uncertainty' });
        return;
      }

      const changed = lifecycleTask(task, action, body);
      replaceTask(changed);
      replaySnapshots.set(replayKey, { fingerprint, task: structuredClone(changed) });
      record(action, taskId, body, outcome);
      if (outcome === 'uncertain-applied') {
        expectHttpFailure(url, method);
        await fulfillJson(route, 503, { detail: 'Synthetic response lost after commit' });
        return;
      }
      await fulfillJson(route, 200, changed);
    };

    await commandPage.route(TASK_ROUTE, handler);
    await provideFixture({
      setNextOutcome: (outcome) => { nextOutcome = outcome; },
      setTaskStatus: (taskId, status) => {
        const task = routeState.tasks.find((candidate) => candidate.id === taskId);
        if (task === undefined) throw new Error(`Unknown deterministic task ${taskId}`);
        replaceTask({ ...task, status });
      },
      requestsFor: (action, taskId) => requests
        .filter((entry) => entry.action === action && entry.taskId === taskId)
        .map((entry) => structuredClone(entry)),
    });
    await commandPage.unroute(TASK_ROUTE, handler);
  },
});

async function readTasks(page: Page, visibility: 'active' | 'archived' | 'all') {
  return page.evaluate(async (requestedVisibility) => {
    const response = await fetch(`/api/v1/command/tasks?visibility=${requestedVisibility}`, {
      headers: { Authorization: 'Bearer test-admin-token' },
    });
    return {
      status: response.status,
      body: await response.json() as CommandFixtureTask[],
    };
  }, visibility);
}

async function postLifecycleRequest(
  page: Page,
  taskId: number,
  action: LifecycleAction,
  body: LifecycleRequestBody,
) {
  return page.evaluate(async ({ requestedTaskId, requestedAction, requestedBody }) => {
    const response = await fetch(`/api/v1/command/tasks/${requestedTaskId}/${requestedAction}`, {
      method: 'POST',
      headers: {
        Authorization: 'Bearer test-admin-token',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(requestedBody),
    });
    return {
      status: response.status,
      body: await response.json() as CommandFixtureTask,
    };
  }, {
    requestedTaskId: taskId,
    requestedAction: action,
    requestedBody: body,
  });
}

async function openArchiveDialog(page: Page, title = 'Call Avery') {
  const trigger = page.getByRole('button', { name: `Task actions for ${title}` });
  await trigger.click();
  const item = page.getByRole('menuitem', { name: 'Archive task' });
  await expect(item).toBeFocused();
  await item.click();
  const dialog = page.getByRole('dialog', { name: `Archive ${title}` });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('textbox', { name: 'Archive reason (optional)' })).toBeFocused();
  return { dialog, trigger };
}

async function archiveFromDialog(dialog: Locator, reason?: string) {
  if (reason !== undefined) {
    await dialog.getByRole('textbox', { name: 'Archive reason (optional)' }).fill(reason);
  }
  await dialog.getByRole('button', { name: 'Archive', exact: true }).click();
}

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  expect(
    results.violations,
    results.violations.map((violation) => (
      `${violation.id}: ${violation.help}\n${violation.nodes.map((node) => node.target.join(' ')).join('\n')}`
    )).join('\n\n'),
  ).toEqual([]);
}

function desktopOnly() {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'command-desktop', 'Desktop task lifecycle coverage');
  });
}

function mobileOnly() {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'command-mobile', 'Mobile task lifecycle coverage');
  });
}

function a11yOnly() {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'command-a11y', 'Task lifecycle accessibility coverage');
  });
}

test.describe('Tasks lifecycle desktop', () => {
  desktopOnly();

  test('archives and restores against active, archived, and all task reads', async ({ commandPage, taskLifecycleApi }) => {
    taskLifecycleApi.setTaskStatus(1, 'in_progress');
    await commandPage.goto('/admin/command/tasks');
    await expect(commandPage.getByRole('article', { name: 'Task Call Avery' })).toBeVisible();

    const initialActive = await readTasks(commandPage, 'active');
    const initialArchived = await readTasks(commandPage, 'archived');
    const initialAll = await readTasks(commandPage, 'all');
    expect(initialActive.status).toBe(200);
    expect(initialArchived.status).toBe(200);
    expect(initialAll.status).toBe(200);
    expect(initialActive.body.every((task) => task.archived_at === null)).toBe(true);
    expect(initialArchived.body.every((task) => task.archived_at !== null)).toBe(true);
    expect(initialAll.body).toHaveLength(initialActive.body.length + initialArchived.body.length);
    expect(initialAll.body.find((task) => task.id === 1)?.status).toBe('in_progress');

    const { dialog } = await openArchiveDialog(commandPage);
    await archiveFromDialog(dialog, '  Duplicate follow-up  ');
    const notice = commandPage.getByRole('status').filter({ hasText: 'Call Avery was archived.' });
    await expect(notice).toBeVisible();
    await expect(notice.getByRole('button', { name: 'Undo' })).toBeFocused();
    await expect(commandPage.getByRole('article', { name: 'Task Call Avery' })).toHaveCount(0);

    const archivedVisibility = commandPage.getByRole('button', { name: 'Archived', exact: true });
    await archivedVisibility.click();
    const archivedTask = commandPage.getByRole('article', { name: 'Task Call Avery' });
    await expect(archivedTask).toContainText('Duplicate follow-up');
    const archivedRead = await readTasks(commandPage, 'archived');
    const archivedAck = archivedRead.body.find((task) => task.id === 1)!;
    expect(archivedAck).toMatchObject({
      status: 'in_progress',
      archived_at: ARCHIVED_AT,
      archive_reason: 'Duplicate follow-up',
      version: 2,
    });
    await archivedTask.getByRole('button', { name: 'Restore Call Avery' }).click();
    await expect(commandPage.getByRole('status').filter({ hasText: 'Call Avery was restored.' })).toBeVisible();
    await expect(archivedVisibility).toBeFocused();
    await expect(archivedTask).toHaveCount(0);

    const activeVisibility = commandPage.getByRole('button', { name: 'Active', exact: true });
    await activeVisibility.click();
    await expect(commandPage.getByRole('article', { name: 'Task Call Avery' })).toBeVisible();
    const finalActive = await readTasks(commandPage, 'active');
    expect(finalActive.body.find((task) => task.id === 1)).toMatchObject({
      status: 'in_progress',
      archived_at: null,
      archive_reason: null,
      version: 3,
    });
    const archiveRequest = taskLifecycleApi.requestsFor('archive', 1)[0]!;
    const restoreRequest = taskLifecycleApi.requestsFor('restore', 1)[0]!;
    expect(archiveRequest.body).toStrictEqual({
      request_id: expect.stringMatching(UUID_PATTERN),
      expected_version: 1,
      reason: 'Duplicate follow-up',
    });
    expect(restoreRequest.body).toStrictEqual({
      request_id: expect.stringMatching(UUID_PATTERN),
      expected_version: 2,
    });
    expect(restoreRequest.body.request_id).not.toBe(archiveRequest.body.request_id);

    const replay = await postLifecycleRequest(commandPage, 1, 'archive', archiveRequest.body);
    expect(replay).toEqual({ status: 200, body: archivedAck });
    const authoritativeAfterReplay = await readTasks(commandPage, 'all');
    expect(authoritativeAfterReplay.body.find((task) => task.id === 1)).toMatchObject({
      status: 'in_progress',
      archived_at: null,
      archive_reason: null,
      version: 3,
    });
    const archiveCalls = taskLifecycleApi.requestsFor('archive', 1);
    expect(archiveCalls).toHaveLength(2);
    expect(archiveCalls[1]).toMatchObject({ body: archiveRequest.body, outcome: 'replay' });
    expect(taskLifecycleApi.requestsFor('restore', 1)).toHaveLength(1);
  });

  test('adopts a stale conflict and requires a fresh UUID and version', async ({ commandPage, taskLifecycleApi }) => {
    taskLifecycleApi.setNextOutcome('conflict');
    await commandPage.goto('/admin/command/tasks');
    const { dialog } = await openArchiveDialog(commandPage);
    await archiveFromDialog(dialog);

    await expect(commandPage.getByRole('alert').filter({
      hasText: 'Call Avery changed elsewhere. Review the authoritative task and start a fresh action.',
    })).toBeVisible();
    const activeVisibility = commandPage.getByRole('button', { name: 'Active', exact: true });
    await expect(activeVisibility).toBeFocused();
    await expect(commandPage.getByRole('article', { name: 'Task Call Avery' })).toContainText('Changed by another administrator');

    const first = taskLifecycleApi.requestsFor('archive', 1)[0]!;
    expect(first.body.expected_version).toBe(1);
    expect(first.body.request_id).toMatch(UUID_PATTERN);
    expect(first.outcome).toBe('conflict');

    const freshDialog = (await openArchiveDialog(commandPage)).dialog;
    await archiveFromDialog(freshDialog);
    await expect(commandPage.getByRole('status').filter({ hasText: 'Call Avery was archived.' })).toBeVisible();
    const calls = taskLifecycleApi.requestsFor('archive', 1);
    expect(calls).toHaveLength(2);
    expect(calls[1]?.body.expected_version).toBe(2);
    expect(calls[1]?.body.request_id).toMatch(UUID_PATTERN);
    expect(calls[1]?.body.request_id).not.toBe(first.body.request_id);
  });

  test('reconciles a committed archive after an uncertain response without retrying', async ({ commandPage, taskLifecycleApi }) => {
    taskLifecycleApi.setNextOutcome('uncertain-applied');
    await commandPage.goto('/admin/command/tasks');
    const { dialog } = await openArchiveDialog(commandPage);
    await archiveFromDialog(dialog, 'Committed before response loss');

    const notice = commandPage.getByRole('status').filter({ hasText: 'Archive confirmed after refreshing.' });
    await expect(notice).toBeVisible();
    await expect(notice.getByRole('button', { name: 'Undo' })).toBeFocused();
    await expect(commandPage.getByRole('button', { name: 'Retry' })).toHaveCount(0);
    expect(taskLifecycleApi.requestsFor('archive', 1)).toHaveLength(1);
    const archived = await readTasks(commandPage, 'archived');
    expect(archived.body.find((task) => task.id === 1)).toMatchObject({
      archive_reason: 'Committed before response loss',
      version: 2,
    });
  });

  test('reuses the exact protected request after an uncertain unchanged response', async ({ commandPage, taskLifecycleApi }) => {
    taskLifecycleApi.setNextOutcome('uncertain-unchanged');
    await commandPage.goto('/admin/command/tasks');
    const { dialog } = await openArchiveDialog(commandPage);
    await archiveFromDialog(dialog, 'Retry the same request');

    const alert = commandPage.getByRole('alert').filter({ hasText: 'Archive outcome is unknown.' });
    await expect(alert).toBeVisible();
    const retry = alert.getByRole('button', { name: 'Retry' });
    await expect(retry).toBeFocused();
    const original = taskLifecycleApi.requestsFor('archive', 1)[0]!;
    await retry.click();
    await expect(commandPage.getByRole('status').filter({ hasText: 'Archive confirmed after refreshing.' })).toBeVisible();

    const calls = taskLifecycleApi.requestsFor('archive', 1);
    expect(calls).toHaveLength(2);
    expect(calls[1]?.body).toStrictEqual(original.body);
    expect(calls[0]?.outcome).toBe('uncertain-unchanged');
    expect(calls[1]?.outcome).toBe('ack');
  });
});

test.describe('Tasks lifecycle mobile', () => {
  mobileOnly();

  test('supports keyboard focus recovery and touch archive and restore', async ({ commandPage, taskLifecycleApi }) => {
    await commandPage.goto('/admin/command/tasks');
    const trigger = commandPage.getByRole('button', { name: 'Task actions for Call Avery' });
    await trigger.focus();
    await commandPage.keyboard.press('Enter');
    const menuItem = commandPage.getByRole('menuitem', { name: 'Archive task' });
    await expect(menuItem).toBeFocused();
    await commandPage.keyboard.press('Enter');
    let dialog = commandPage.getByRole('dialog', { name: 'Archive Call Avery' });
    const reason = dialog.getByRole('textbox', { name: 'Archive reason (optional)' });
    await expect(reason).toBeFocused();
    await commandPage.keyboard.press('Shift+Tab');
    await expect(dialog.getByRole('button', { name: 'Archive', exact: true })).toBeFocused();
    await commandPage.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();

    await trigger.tap();
    await menuItem.tap();
    dialog = commandPage.getByRole('dialog', { name: 'Archive Call Avery' });
    await dialog.getByRole('textbox', { name: 'Archive reason (optional)' }).fill('Mobile lifecycle');
    await dialog.getByRole('button', { name: 'Archive', exact: true }).tap();
    await expect(commandPage.getByRole('status').filter({ hasText: 'Call Avery was archived.' })).toBeVisible();
    await expect(commandPage.getByRole('button', { name: 'Undo' })).toBeFocused();

    await commandPage.getByRole('button', { name: 'Archived', exact: true }).tap();
    const restore = commandPage.getByRole('button', { name: 'Restore Call Avery' });
    await expect(restore).toBeVisible();
    await restore.tap();
    await expect(commandPage.getByRole('status').filter({ hasText: 'Call Avery was restored.' })).toBeVisible();
    expect(taskLifecycleApi.requestsFor('archive', 1)).toHaveLength(1);
    expect(taskLifecycleApi.requestsFor('restore', 1)).toHaveLength(1);
  });

  test('keeps lifecycle targets at least 44 pixels and contains horizontal overflow', async ({ commandPage }) => {
    await commandPage.goto('/admin/command/tasks');
    await expect(commandPage.getByRole('heading', { name: 'Tasks', level: 1 })).toBeVisible();

    const assertGeometry = async (targets: Locator) => {
      const undersized = await targets.evaluateAll((elements) => elements.map((element) => {
        const box = element.getBoundingClientRect();
        return {
          name: element.getAttribute('aria-label') ?? element.textContent?.trim().slice(0, 80) ?? '',
          width: box.width,
          height: box.height,
        };
      }).filter(({ width, height }) => width < 44 || height < 44));
      expect(undersized, JSON.stringify(undersized, null, 2)).toEqual([]);
      const width = await commandPage.evaluate(() => ({
        viewport: document.documentElement.clientWidth,
        document: document.documentElement.scrollWidth,
        body: document.body.scrollWidth,
      }));
      expect(width.document).toBeLessThanOrEqual(width.viewport + 1);
      expect(width.body).toBeLessThanOrEqual(width.viewport + 1);
    };

    await assertGeometry(commandPage.locator('main a:visible, main button:visible, main input:visible, main select:visible'));
    const { dialog } = await openArchiveDialog(commandPage);
    await assertGeometry(dialog.locator('button:visible, textarea:visible'));
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await commandPage.getByRole('button', { name: 'Archived', exact: true }).tap();
    await assertGeometry(commandPage.locator('main a:visible, main button:visible, main input:visible, main select:visible'));
  });
});

test.describe('Tasks lifecycle accessibility', () => {
  a11yOnly();

  test('exactly four lifecycle states pass axe: Active, dialog, Archived, and conflict', async ({ commandPage, taskLifecycleApi }) => {
    await commandPage.goto('/admin/command/tasks');
    await expect(commandPage.getByRole('article', { name: 'Task Call Avery' })).toBeVisible();
    await expectNoAxeViolations(commandPage);

    const { dialog } = await openArchiveDialog(commandPage);
    await expectNoAxeViolations(commandPage);
    await archiveFromDialog(dialog, 'Accessibility state');
    await expect(commandPage.getByRole('status').filter({ hasText: 'Call Avery was archived.' })).toBeVisible();

    await commandPage.getByRole('button', { name: 'Archived', exact: true }).click();
    await expect(commandPage.getByRole('article', { name: 'Task Call Avery' })).toBeVisible();
    await expectNoAxeViolations(commandPage);

    await commandPage.getByRole('button', { name: 'Restore Call Avery' }).click();
    await expect(commandPage.getByRole('status').filter({ hasText: 'Call Avery was restored.' })).toBeVisible();
    await commandPage.getByRole('button', { name: 'Active', exact: true }).click();
    taskLifecycleApi.setNextOutcome('conflict');
    const conflictDialog = (await openArchiveDialog(commandPage)).dialog;
    await archiveFromDialog(conflictDialog);
    await expect(commandPage.getByRole('alert').filter({ hasText: 'Call Avery changed elsewhere.' })).toBeVisible();
    await expectNoAxeViolations(commandPage);
  });
});
