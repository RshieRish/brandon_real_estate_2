import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CommandDecodeError, CommandHttpError } from './http';
import {
  consumeTaskSuggestionHandoffBootstrap,
  decodeTaskSuggestionList,
  installTaskSuggestionHandoffBootstrap,
  taskSuggestionsApi,
  type TaskSuggestion,
} from './task-suggestions';
import { initializeTaskSuggestionHandoff } from '@/instrumentation-client';

const suggestionId = '11111111-1111-4111-8111-111111111111';
const payloadHash = 'a'.repeat(64);
const handoff = 'A'.repeat(43);
const approval = `${'B'.repeat(42)}A`;

const suggestion: TaskSuggestion = {
  id: suggestionId,
  source_type: 'gmail_message',
  title: 'Send Jane the disclosure package',
  description: 'Jane requested the signed disclosure package.',
  priority: 'high',
  due_at: '2026-08-25T14:00:00Z',
  contact_id: 41,
  status: 'open',
  state: 'pending_review',
  clarification_state: 'not_required',
  blocker_codes: [],
  resolution_requirements: [],
  confidence: 0.94,
  rationale: 'The message explicitly requests a disclosure follow-up.',
  model_schema_version: 'gmail-task-v1',
  sources: [{
    direction: 'received',
    source_label: `gmail:received:${'1'.repeat(32)}`,
    created_at: '2026-08-22T12:00:00Z',
  }],
  audit_trail: [{
    suggestion_version: 7,
    event_type: 'edit',
    actor_type: 'command_admin',
    action_audited: true,
    created_at: '2026-08-22T12:04:00Z',
  }],
  payload_hash: payloadHash,
  version: 7,
  applied_task_id: null,
  created_at: '2026-08-22T12:00:00Z',
  updated_at: '2026-08-22T12:05:00Z',
};

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('task suggestion client', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('admin_token', 'admin-test-token');
    vi.restoreAllMocks();
  });

  it('strictly decodes the bounded suggestion list', () => {
    expect(decodeTaskSuggestionList({ suggestions: [suggestion] })).toEqual({
      suggestions: [suggestion],
    });
    expect(() =>
      decodeTaskSuggestionList({ suggestions: [{ ...suggestion, raw_email_body: 'forbidden' }] }),
    ).toThrow(CommandDecodeError);
    expect(() =>
      decodeTaskSuggestionList({
        suggestions: [{ ...suggestion, payload_hash: 'not-a-hash' }],
      }),
    ).toThrow(CommandDecodeError);
    expect(() =>
      decodeTaskSuggestionList({ suggestions: [{ ...suggestion, due_at: 'tomorrow' }] }),
    ).toThrow(CommandDecodeError);
    expect(() =>
      decodeTaskSuggestionList({ suggestions: [{ ...suggestion, confidence: 1.1 }] }),
    ).toThrow(CommandDecodeError);
    expect(() =>
      decodeTaskSuggestionList({
        suggestions: [{
          ...suggestion,
          resolution_requirements: [
            'resolve_owner_as_brandon',
            'resolve_owner_as_brandon',
          ],
        }],
      }),
    ).toThrow(CommandDecodeError);
    expect(() =>
      decodeTaskSuggestionList({
        suggestions: [{
          ...suggestion,
          audit_trail: [{ ...suggestion.audit_trail[0], raw_event_data: 'forbidden' }],
        }],
      }),
    ).toThrow(CommandDecodeError);
  });

  it('uses typed Command routes and sends edit resolutions only in JSON bodies', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(response({ suggestions: [suggestion] }))
      .mockResolvedValueOnce(response({ ...suggestion, version: 8 }));

    await expect(taskSuggestionsApi.list()).resolves.toEqual({ suggestions: [suggestion] });
    await taskSuggestionsApi.edit(suggestionId, {
      expected_version: 7,
      expected_payload_hash: payloadHash,
      resolve_owner_as_brandon: true,
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      'http://localhost:8000/api/v1/command/task-suggestions?limit=50',
    );
    const editUrl = String(fetchMock.mock.calls[1]?.[0]);
    const editInit = fetchMock.mock.calls[1]?.[1];
    expect(editUrl).toBe(
      `http://localhost:8000/api/v1/command/task-suggestions/${suggestionId}`,
    );
    expect(editUrl).not.toContain('handoff');
    expect(editInit?.method).toBe('PATCH');
    expect(JSON.parse(String(editInit?.body))).toEqual({
      expected_version: 7,
      expected_payload_hash: payloadHash,
      resolve_owner_as_brandon: true,
    });
  });

  it('keeps handoff and approval secrets in POST bodies across two distinct stages', async () => {
    const preview = {
      suggestion_id: suggestionId,
      suggestion_version: 7,
      payload_hash: payloadHash,
      task: {
        title: suggestion.title,
        description: suggestion.description,
        priority: suggestion.priority,
        due_at: suggestion.due_at,
        contact_id: suggestion.contact_id,
        status: 'open',
      },
      approval,
      expires_at: '2026-08-22T12:10:00Z',
    };
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(response(preview))
      .mockResolvedValueOnce(
        response({
          suggestion_id: suggestionId,
          suggestion_version: 7,
          task_id: 91,
          request_id: '22222222-2222-4222-8222-222222222222',
          replayed: false,
        }),
      );

    await taskSuggestionsApi.exchangeHandoff(suggestionId, {
      expected_version: 7,
      expected_payload_hash: payloadHash,
      handoff,
    });
    await taskSuggestionsApi.approve(suggestionId, {
      expected_version: 7,
      expected_payload_hash: payloadHash,
      approval,
      request_id: '22222222-2222-4222-8222-222222222222',
      client_timezone: 'America/New_York',
    });

    const exchangeUrl = String(fetchMock.mock.calls[0]?.[0]);
    const approveUrl = String(fetchMock.mock.calls[1]?.[0]);
    expect(exchangeUrl.endsWith(`/task-suggestions/${suggestionId}/handoff/exchange`)).toBe(true);
    expect(approveUrl.endsWith(`/task-suggestions/${suggestionId}/approve`)).toBe(true);
    expect(exchangeUrl).not.toContain(handoff);
    expect(approveUrl).not.toContain(approval);
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      expected_version: 7,
      expected_payload_hash: payloadHash,
      handoff,
    });
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      expected_version: 7,
      expected_payload_hash: payloadHash,
      approval,
      request_id: '22222222-2222-4222-8222-222222222222',
      client_timezone: 'America/New_York',
    });
  });

  it('propagates bounded stale errors for authoritative refetch handling', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      response({ detail: 'suggestion_stale' }, 409),
    );

    await expect(
      taskSuggestionsApi.preview(suggestionId, {
        expected_version: 7,
        expected_payload_hash: payloadHash,
      }),
    ).rejects.toEqual(expect.objectContaining<Partial<CommandHttpError>>({
      status: 409,
      detail: 'suggestion_stale',
    }));
  });
});

describe('fragment-first handoff bootstrap', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    Reflect.deleteProperty(window, '__swsTaskSuggestionHandoff');
    window.history.replaceState({}, '', '/admin/command/task-suggestions');
    vi.restoreAllMocks();
  });

  it('captures and clears the fragment synchronously before any application network call', async () => {
    const order: string[] = [];
    const originalReplaceState = window.history.replaceState.bind(window.history);
    vi.spyOn(window.history, 'replaceState').mockImplementation((data, unused, url) => {
      order.push('fragment-cleared');
      originalReplaceState(data, unused, url);
    });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      order.push('network');
      return response({ suggestions: [] });
    });
    window.history.replaceState(
      {},
      '',
      `/admin/command/task-suggestions?suggestion=${suggestionId}#handoff=${handoff}`,
    );
    order.length = 0;

    const metadata = installTaskSuggestionHandoffBootstrap(window);
    expect(window.location.hash).toBe('');
    const captured = consumeTaskSuggestionHandoffBootstrap(window);
    await fetch('/after-bootstrap');

    expect(captured).toEqual({
      handoff,
      invalid_query_secret: false,
      invalid_handoff: false,
    });
    expect(metadata).toEqual({
      has_handoff: true,
      invalid_query_secret: false,
      invalid_handoff: false,
    });
    expect(order).toEqual(['fragment-cleared', 'network']);
    expect(consumeTaskSuggestionHandoffBootstrap(window).handoff).toBeNull();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.body.textContent).not.toContain(handoff);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('rejects query-string secrets and reports malformed handoff fragments without echoing them', () => {
    window.history.replaceState(
      {},
      '',
      `/admin/command/task-suggestions?suggestion=${suggestionId}&handoff=${handoff}#handoff=short`,
    );

    installTaskSuggestionHandoffBootstrap(window);
    const captured = consumeTaskSuggestionHandoffBootstrap(window);

    expect(captured).toEqual({
      handoff: null,
      invalid_query_secret: true,
      invalid_handoff: true,
    });
    expect(window.location.hash).toBe('');
    expect(window.location.search).toBe(`?suggestion=${suggestionId}`);
  });

  it('clears an unauthenticated handoff before redirecting to a safe login notice', () => {
    const order: string[] = [];
    const originalReplaceState = window.history.replaceState.bind(window.history);
    vi.spyOn(window.history, 'replaceState').mockImplementation((data, unused, url) => {
      order.push('fragment-cleared');
      originalReplaceState(data, unused, url);
    });
    const redirect = vi.fn(() => order.push('redirect'));
    window.history.replaceState(
      {},
      '',
      `/admin/command/task-suggestions?suggestion=${suggestionId}#handoff=${handoff}`,
    );
    order.length = 0;

    const metadata = initializeTaskSuggestionHandoff(window, redirect);

    expect(metadata).toEqual({
      has_handoff: true,
      invalid_query_secret: false,
      invalid_handoff: false,
    });
    expect(order).toEqual(['fragment-cleared', 'redirect']);
    expect(window.location.hash).toBe('');
    expect(redirect).toHaveBeenCalledWith('/admin/login?approval_notice=reopen_task_handoff');
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.body.textContent).not.toContain(handoff);
  });
});
