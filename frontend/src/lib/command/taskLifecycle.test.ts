import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  commandApi,
  type CommandConflictError,
  type CommandOutcomeUncertainError,
  type Task,
  type TaskConflict,
  type TaskLifecycleRequest,
  type TaskLink,
  type TaskVisibility,
} from './api';
import { CommandDecodeError, CommandHttpError } from './http';

const COMMAND_BASE_URL = 'http://localhost:8000/api/v1/command';
const REQUEST_ID = '550e8400-e29b-41d4-a716-446655440000';
const SECOND_REQUEST_ID = '123e4567-e89b-42d3-a456-426614174000';

const task = {
  id: 7,
  title: 'Call buyer',
  contact_id: 11,
  description: 'Confirm inspection timing',
  priority: 'high',
  due_at: '2026-08-21T14:30:00Z',
  status: 'in_progress',
  archived_at: null,
  archive_reason: null,
  version: 3,
} satisfies Task;

const link = {
  id: 5,
  task_id: 7,
  entity_type: 'agreement',
  entity_id: 19,
  display_name: 'Buyer representation agreement',
  task_version: 4,
} satisfies TaskLink;

type Equal<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends
  (<Value>() => Value extends Right ? 1 : 2)
    ? (<Value>() => Value extends Right ? 1 : 2) extends
      (<Value>() => Value extends Left ? 1 : 2)
      ? true
      : false
    : false;
type Expect<Condition extends true> = Condition;

const CONTRACT_ASSERTIONS: readonly [
  Expect<Equal<TaskVisibility, 'active' | 'archived' | 'all'>>,
  Expect<Equal<Task['status'], 'open' | 'in_progress' | 'completed' | 'cancelled'>>,
  Expect<Equal<Task['priority'], 'low' | 'normal' | 'high'>>,
  Expect<Equal<keyof TaskLifecycleRequest, 'request_id' | 'expected_version' | 'reason'>>,
  Expect<Equal<
    TaskConflict['code'],
    'task_version_conflict' | 'task_archived' | 'task_request_mismatch'
  >>,
  Expect<CommandConflictError extends Error ? true : false>,
  Expect<CommandOutcomeUncertainError extends Error ? true : false>,
] = [true, true, true, true, true, true, true];

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function malformedJsonResponse(status = 200): Response {
  return new Response('{"private":"truncated"', {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function withoutKey(value: Record<string, unknown>, key: string): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).filter(([candidate]) => candidate !== key));
}

describe('typed task lifecycle client', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function authenticate(token = 'task-admin-token') {
    vi.stubGlobal('localStorage', { getItem: vi.fn().mockReturnValue(token) });
  }

  it('keeps the public task lifecycle types exact', () => {
    expect(CONTRACT_ASSERTIONS).toEqual([true, true, true, true, true, true, true]);
  });

  describe('strict task reads', () => {
    it('sends visibility with workflow and due filters and decodes every exact task field', async () => {
      authenticate();
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse([task]));
      vi.stubGlobal('fetch', fetchMock);

      await expect(commandApi.tasks({
        visibility: 'all',
        status: 'in_progress',
        due_before: '2026-08-31T23:59:59Z',
        due_after: '2026-08-01T00:00:00Z',
      })).resolves.toEqual([task]);

      expect(fetchMock).toHaveBeenCalledOnce();
      expect(fetchMock.mock.calls[0]?.[0]).toBe(
        `${COMMAND_BASE_URL}/tasks?visibility=all&status=in_progress&due_before=2026-08-31T23%3A59%3A59Z&due_after=2026-08-01T00%3A00%3A00Z`,
      );
    });

    it.each([
      ['non-array response', task],
      ['wrong id', [{ ...task, id: 0 }]],
      ['wrong title', [{ ...task, title: 9 }]],
      ['wrong contact_id', [{ ...task, contact_id: 0 }]],
      ['wrong description', [{ ...task, description: null }]],
      ['wrong priority literal', [{ ...task, priority: 'urgent' }]],
      ['wrong due_at', [{ ...task, due_at: 1_724_073_300 }]],
      ['wrong status literal', [{ ...task, status: 'archived' }]],
      ['wrong archived_at', [{ ...task, archived_at: false }]],
      ['wrong archive_reason', [{ ...task, archive_reason: 42 }]],
      ['wrong version', [{ ...task, version: 0 }]],
      ['extra field', [{ ...task, private_value: 'must not cross boundary' }]],
    ])('rejects a %s', async (_label, payload) => {
      authenticate();
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(payload)));

      await expect(commandApi.tasks()).rejects.toBeInstanceOf(CommandDecodeError);
    });

    it.each(Object.keys(task))('rejects a task missing required %s', async (key) => {
      authenticate();
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([
        withoutKey(task as unknown as Record<string, unknown>, key),
      ])));

      await expect(commandApi.tasks()).rejects.toBeInstanceOf(CommandDecodeError);
    });

    it.each([
      ['low', 'open'],
      ['normal', 'in_progress'],
      ['high', 'completed'],
      ['normal', 'cancelled'],
    ] as const)('accepts priority %s and workflow status %s', async (priority, status) => {
      authenticate();
      const payload = [{ ...task, priority, status }];
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(payload)));

      await expect(commandApi.tasks()).resolves.toEqual(payload);
    });
  });

  describe('strict task links', () => {
    it('decodes the exact positive task_version on link reads', async () => {
      authenticate();
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([link])));

      await expect(commandApi.taskLinks(7)).resolves.toEqual([link]);
    });

    it.each([
      ['missing task_version', [withoutKey(link as unknown as Record<string, unknown>, 'task_version')]],
      ['zero task_version', [{ ...link, task_version: 0 }]],
      ['string task_version', [{ ...link, task_version: '4' }]],
      ['extra field', [{ ...link, secret: true }]],
    ])('rejects a link with %s', async (_label, payload) => {
      authenticate();
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(payload)));

      await expect(commandApi.taskLinks(7)).rejects.toBeInstanceOf(CommandDecodeError);
    });
  });

  describe('mutation requests', () => {
    it('creates with the caller UUID in the exact idempotency header and decodes TaskOut', async () => {
      authenticate('create-token');
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ...task, version: 1 }, 201));
      vi.stubGlobal('fetch', fetchMock);
      const payload = {
        title: 'Call buyer',
        contact_id: 11,
        description: 'Confirm inspection timing',
        priority: 'high' as const,
        due_at: '2026-08-21T14:30:00Z',
      };

      await expect(commandApi.createTask(payload, REQUEST_ID)).resolves.toEqual({ ...task, version: 1 });
      expect(fetchMock).toHaveBeenCalledWith(`${COMMAND_BASE_URL}/tasks`, {
        method: 'POST',
        headers: {
          Authorization: 'Bearer create-token',
          'Content-Type': 'application/json',
          'X-Idempotency-Key': REQUEST_ID,
        },
        body: JSON.stringify(payload),
      });
    });

    it.each(['', 'not-a-uuid', '550e8400-e29b-41d4-a716', `${REQUEST_ID}-extra`])(
      'rejects invalid create UUID %j before fetch',
      async (requestId) => {
        authenticate();
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);

        await expect(commandApi.createTask({
          title: 'Call', contact_id: null, description: '', priority: 'normal', due_at: null,
        }, requestId)).rejects.toBeInstanceOf(CommandDecodeError);
        expect(fetchMock).not.toHaveBeenCalled();
      },
    );

    it('sends expected_version with every update field and decodes the incremented task', async () => {
      authenticate();
      const updated = { ...task, title: 'Call seller', version: 4 };
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse(updated));
      vi.stubGlobal('fetch', fetchMock);

      await expect(commandApi.updateTask(7, {
        expected_version: 3,
        title: 'Call seller',
        description: '',
        priority: 'normal',
        status: 'open',
        due_at: null,
        contact_id: null,
      })).resolves.toEqual(updated);
      expect(fetchMock).toHaveBeenCalledWith(`${COMMAND_BASE_URL}/tasks/7`, expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          expected_version: 3,
          title: 'Call seller',
          description: '',
          priority: 'normal',
          status: 'open',
          due_at: null,
          contact_id: null,
        }),
      }));
    });

    it('sends expected_version in the task-link body and decodes its new task version', async () => {
      authenticate();
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse(link, 201));
      vi.stubGlobal('fetch', fetchMock);

      await expect(commandApi.addTaskLink(7, {
        expected_version: 3,
        entity_type: 'agreement',
        entity_id: 19,
      })).resolves.toEqual(link);
      expect(fetchMock).toHaveBeenCalledWith(`${COMMAND_BASE_URL}/tasks/7/links`, expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          expected_version: 3,
          entity_type: 'agreement',
          entity_id: 19,
        }),
      }));
    });

    it.each([
      ['archive', 'archiveTask', REQUEST_ID, 'No longer needed'],
      ['restore', 'restoreTask', SECOND_REQUEST_ID, undefined],
    ] as const)('posts a strict %s lifecycle request', async (action, method, requestId, reason) => {
      authenticate();
      const changed = action === 'archive'
        ? { ...task, archived_at: '2026-08-20T16:00:00Z', archive_reason: reason, version: 4 }
        : { ...task, archived_at: null, archive_reason: null, version: 4 };
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse(changed));
      vi.stubGlobal('fetch', fetchMock);
      const lifecycle = reason === undefined
        ? { request_id: requestId, expected_version: 3 }
        : { request_id: requestId, expected_version: 3, reason };

      await expect(commandApi[method](7, lifecycle)).resolves.toEqual(changed);
      expect(fetchMock).toHaveBeenCalledWith(`${COMMAND_BASE_URL}/tasks/7/${action}`, expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(lifecycle),
      }));
    });

    it.each([
      ['task id', () => commandApi.updateTask(2_147_483_648, { expected_version: 1, status: 'open' })],
      ['expected version', () => commandApi.updateTask(7, { expected_version: 2_147_483_648, status: 'open' })],
      ['contact id', () => commandApi.updateTask(7, { expected_version: 1, contact_id: 2_147_483_648 })],
      ['link entity id', () => commandApi.addTaskLink(7, { expected_version: 1, entity_type: 'contact', entity_id: 0 })],
      ['lifecycle UUID', () => commandApi.archiveTask(7, { request_id: 'invalid', expected_version: 1 })],
      ['lifecycle reason', () => commandApi.restoreTask(7, { request_id: REQUEST_ID, expected_version: 1, reason: 'x'.repeat(501) })],
    ])('rejects invalid %s before fetch', async (_label, invoke) => {
      authenticate();
      const fetchMock = vi.fn();
      vi.stubGlobal('fetch', fetchMock);

      await expect(invoke()).rejects.toBeInstanceOf(CommandDecodeError);
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });

  describe('uncertain mutation outcomes and conflicts', () => {
    it.each([
      'task_version_conflict',
      'task_archived',
      'task_request_mismatch',
    ] as const)('decodes a FastAPI %s detail into CommandConflictError', async (code) => {
      authenticate();
      const conflict = { code, current_version: task.version, current_task: task };
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: conflict }, 409));
      vi.stubGlobal('fetch', fetchMock);

      const promise = commandApi.updateTask(7, { expected_version: 2, priority: 'normal' });
      await expect(promise).rejects.toMatchObject({
        name: 'CommandConflictError',
        conflict,
      });
      expect(fetchMock).toHaveBeenCalledOnce();
    });

    it.each([
      ['malformed JSON', () => malformedJsonResponse(409)],
      ['missing detail', () => jsonResponse({ code: 'task_archived' }, 409)],
      ['unknown code', () => jsonResponse({ detail: { code: 'other', current_version: 3, current_task: task } }, 409)],
      ['invalid current version', () => jsonResponse({ detail: { code: 'task_archived', current_version: 0, current_task: task } }, 409)],
      ['malformed current task', () => jsonResponse({ detail: { code: 'task_archived', current_version: 3, current_task: { ...task, version: 0 } } }, 409)],
    ])('treats a 409 with %s as outcome-uncertain without retry', async (_label, response) => {
      authenticate();
      const fetchMock = vi.fn().mockResolvedValue(response());
      vi.stubGlobal('fetch', fetchMock);

      const promise = commandApi.updateTask(7, { expected_version: 2, priority: 'normal' });
      await expect(promise).rejects.toMatchObject({
        name: 'CommandOutcomeUncertainError',
        message: 'The server may have applied the task change; refresh before retrying.',
      });
      expect(fetchMock).toHaveBeenCalledOnce();
    });

    it('wraps a network rejection as outcome-uncertain and never retries', async () => {
      authenticate();
      const cause = new TypeError('Synthetic network failure');
      const fetchMock = vi.fn().mockRejectedValue(cause);
      vi.stubGlobal('fetch', fetchMock);

      const promise = commandApi.createTask({
        title: 'Call', contact_id: null, description: '', priority: 'normal', due_at: null,
      }, REQUEST_ID);
      await expect(promise).rejects.toMatchObject({
        name: 'CommandOutcomeUncertainError',
        message: 'The server may have applied the task change; refresh before retrying.',
        cause,
      });
      expect(fetchMock).toHaveBeenCalledOnce();
    });

    it('wraps a 5xx as outcome-uncertain and never retries', async () => {
      authenticate();
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'Private server failure' }, 503));
      vi.stubGlobal('fetch', fetchMock);

      const promise = commandApi.updateTask(7, { expected_version: 3, status: 'completed' });
      await expect(promise).rejects.toMatchObject({
        name: 'CommandOutcomeUncertainError',
        message: 'The server may have applied the task change; refresh before retrying.',
      });
      await expect(promise).rejects.not.toThrow(/Private server failure/);
      expect(fetchMock).toHaveBeenCalledOnce();
    });

    it.each([
      ['invalid JSON', malformedJsonResponse()],
      ['invalid TaskOut', jsonResponse({ ...task, version: 0 })],
    ])('wraps a successful mutation with %s as outcome-uncertain', async (_label, response) => {
      authenticate();
      const fetchMock = vi.fn().mockResolvedValue(response);
      vi.stubGlobal('fetch', fetchMock);

      await expect(commandApi.updateTask(7, { expected_version: 3, status: 'completed' })).rejects.toMatchObject({
        name: 'CommandOutcomeUncertainError',
        message: 'The server may have applied the task change; refresh before retrying.',
      });
      expect(fetchMock).toHaveBeenCalledOnce();
    });

    it('keeps a known non-conflict 4xx definite and never fabricates a conflict', async () => {
      authenticate();
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'Task contact not found' }, 404));
      vi.stubGlobal('fetch', fetchMock);

      const promise = commandApi.updateTask(7, { expected_version: 3, contact_id: 999_999 });
      await expect(promise).rejects.toBeInstanceOf(CommandHttpError);
      await expect(promise).rejects.toMatchObject({ status: 404, detail: 'Task contact not found' });
      await expect(promise).rejects.not.toMatchObject({ name: 'CommandConflictError' });
      expect(fetchMock).toHaveBeenCalledOnce();
    });
  });
});
