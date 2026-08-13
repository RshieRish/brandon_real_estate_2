import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  COMMAND_HTTP_ERROR_DETAIL_MAX_LENGTH,
  CommandDecodeError,
  CommandHttpError,
  commandBlob,
  commandJson,
  type Decoder,
} from './http';

const COMMAND_BASE_URL = 'http://localhost:8000/api/v1/command';

type Transport = 'json' | 'blob';

function jsonResponse(value: unknown, status = 200) {
  const response = new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
  return {
    response,
    json: vi.spyOn(response, 'json'),
    blob: vi.spyOn(response, 'blob'),
  };
}

function textResponse(value: string, status: number) {
  const response = new Response(value, { status });
  return {
    response,
    json: vi.spyOn(response, 'json'),
    blob: vi.spyOn(response, 'blob'),
  };
}

function requestThrough(transport: Transport, signal?: AbortSignal): Promise<unknown> {
  if (transport === 'json') {
    return commandJson({
      path: '/contacts/directory',
      decode: (input) => input,
      signal,
    });
  }
  return commandBlob({ path: '/archive/artifacts/7/content', signal });
}

describe('Command HTTP boundary', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn().mockReturnValue('admin-token'),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe('error types', () => {
    it('exposes the exact bounded HTTP status and detail', () => {
      const error = new CommandHttpError(409, 'Contact state changed');

      expect(error).toBeInstanceOf(Error);
      expect(error).toMatchObject({
        status: 409,
        detail: 'Contact state changed',
        message: 'Contact state changed',
      });
    });

    it('formats decoder paths without response values', () => {
      const error = new CommandDecodeError('response.rows[0].email', 'string or null');

      expect(error).toBeInstanceOf(Error);
      expect(error).toMatchObject({
        path: 'response.rows[0].email',
        expected: 'string or null',
        message: 'Invalid Command response at response.rows[0].email: expected string or null',
      });
    });
  });

  describe('authenticated JSON requests', () => {
    it('sends the bearer token, identical signal, JSON headers, method, and body', async () => {
      const response = jsonResponse({ saved: true });
      const fetchMock = vi.fn().mockResolvedValue(response.response);
      const controller = new AbortController();
      const toJSON = vi.fn().mockReturnValue({ name: 'Avery' });
      const decode: Decoder<string> = vi.fn((input) => {
        if (typeof input === 'object' && input !== null && Reflect.get(input, 'saved') === true) {
          return 'decoded';
        }
        throw new CommandDecodeError('response.saved', 'true');
      });
      vi.stubGlobal('fetch', fetchMock);

      await expect(commandJson({
        path: '/contacts',
        method: 'POST',
        body: { toJSON },
        decode,
        signal: controller.signal,
      })).resolves.toBe('decoded');

      expect(fetchMock).toHaveBeenCalledOnce();
      expect(fetchMock).toHaveBeenCalledWith(`${COMMAND_BASE_URL}/contacts`, {
        method: 'POST',
        headers: {
          Authorization: 'Bearer admin-token',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ name: 'Avery' }),
        signal: controller.signal,
      });
      expect(toJSON).toHaveBeenCalledOnce();
      expect(response.json).toHaveBeenCalledOnce();
      expect(response.blob).not.toHaveBeenCalled();
      expect(decode).toHaveBeenCalledOnce();
    });

    it('defaults to GET and omits a missing body while retaining the JSON header', async () => {
      const response = jsonResponse({ rows: [] });
      const fetchMock = vi.fn().mockResolvedValue(response.response);
      vi.stubGlobal('fetch', fetchMock);

      await commandJson({ path: '/contacts/directory', decode: (input) => input });

      expect(fetchMock).toHaveBeenCalledWith(`${COMMAND_BASE_URL}/contacts/directory`, {
        method: 'GET',
        headers: {
          Authorization: 'Bearer admin-token',
          'Content-Type': 'application/json',
        },
        signal: undefined,
      });
    });

    it('passes null to the decoder for 204 without parsing a body', async () => {
      const response = new Response(null, { status: 204 });
      const json = vi.spyOn(response, 'json');
      const blob = vi.spyOn(response, 'blob');
      const decode: Decoder<string> = vi.fn((input) => {
        if (input === null) return 'no content';
        throw new CommandDecodeError('response', 'null');
      });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));

      await expect(commandJson({
        path: '/contacts/3',
        method: 'DELETE',
        decode,
      })).resolves.toBe('no content');

      expect(decode).toHaveBeenCalledWith(null);
      expect(json).not.toHaveBeenCalled();
      expect(blob).not.toHaveBeenCalled();
    });

    it('turns invalid success JSON into a private decoder error', async () => {
      const rawPrivateBody = '{"email":"private@example.test"';
      const response = textResponse(rawPrivateBody, 200);
      const decode = vi.fn((input: unknown) => input);
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response.response));

      const promise = commandJson({ path: '/contacts/9', decode });

      await expect(promise).rejects.toBeInstanceOf(CommandDecodeError);
      await expect(promise).rejects.toMatchObject({
        path: 'response',
        expected: 'valid JSON',
      });
      await expect(promise).rejects.not.toThrow(/private@example\.test/);
      expect(response.json).toHaveBeenCalledOnce();
      expect(response.blob).not.toHaveBeenCalled();
      expect(decode).not.toHaveBeenCalled();
    });

    it('preserves a nested private decoder failure exactly', async () => {
      const response = jsonResponse({ contact: { email: 17, secret: 'do-not-leak' } });
      const decoderError = new CommandDecodeError('response.contact.email', 'string or null');
      const decode: Decoder<never> = vi.fn(() => {
        throw decoderError;
      });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response.response));

      const promise = commandJson({ path: '/contacts/9', decode });

      await expect(promise).rejects.toBe(decoderError);
      await expect(promise).rejects.not.toThrow(/do-not-leak|17/);
      expect(response.json).toHaveBeenCalledOnce();
      expect(decode).toHaveBeenCalledOnce();
    });
  });

  describe('authenticated blob requests', () => {
    it('sends only bearer authentication and returns the exact bytes and media type', async () => {
      const source = new Blob([new Uint8Array([0, 7, 19, 255])], {
        type: 'application/octet-stream',
      });
      const json = vi.fn();
      const blob = vi.fn().mockResolvedValue(source);
      const response = { ok: true, status: 200, json, blob };
      const fetchMock = vi.fn().mockResolvedValue(response);
      const controller = new AbortController();
      vi.stubGlobal('fetch', fetchMock);

      const result = await commandBlob({
        path: '/archive/artifacts/11/content',
        signal: controller.signal,
      });

      expect(fetchMock).toHaveBeenCalledWith(
        `${COMMAND_BASE_URL}/archive/artifacts/11/content`,
        {
          headers: { Authorization: 'Bearer admin-token' },
          signal: controller.signal,
        },
      );
      expect(result).toBe(source);
      expect(result.size).toBe(4);
      expect(result.type).toBe('application/octet-stream');
      expect(json).not.toHaveBeenCalled();
      expect(blob).toHaveBeenCalledOnce();
      const init = fetchMock.mock.calls[0]?.[1];
      expect(init).not.toHaveProperty('body');
      expect(init?.headers).not.toHaveProperty('Content-Type');
    });
  });

  describe('administrator session validation', () => {
    it.each([
      ['missing', null],
      ['empty', ''],
      ['whitespace-only', ' \t\n '],
    ])('rejects a %s token before either transport fetches', async (_label, token) => {
      const fetchMock = vi.fn();
      vi.stubGlobal('localStorage', { getItem: vi.fn().mockReturnValue(token) });
      vi.stubGlobal('fetch', fetchMock);

      for (const transport of ['json', 'blob'] as const) {
        const promise = requestThrough(transport);
        await expect(promise).rejects.toBeInstanceOf(CommandHttpError);
        await expect(promise).rejects.toMatchObject({
          status: 401,
          detail: 'Administrator session required',
          message: 'Administrator session required',
        });
      }
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });

  describe('shared non-success status gate', () => {
    it.each(
      (['json', 'blob'] as const).flatMap((transport) =>
        [401, 404, 409, 422, 500].map((status) => [transport, status] as const)),
    )('surfaces bounded %s detail for status %i after one error parse', async (transport, status) => {
      const detail = `Safe detail for ${status}`;
      const response = jsonResponse({ detail }, status);
      const decode = vi.fn((input: unknown) => input);
      const fetchMock = vi.fn().mockResolvedValue(response.response);
      vi.stubGlobal('fetch', fetchMock);

      const promise = transport === 'json'
        ? commandJson({ path: '/contacts/5', decode })
        : commandBlob({ path: '/archive/artifacts/5/content' });

      await expect(promise).rejects.toBeInstanceOf(CommandHttpError);
      await expect(promise).rejects.toMatchObject({ status, detail, message: detail });
      expect(response.json).toHaveBeenCalledOnce();
      expect(response.blob).not.toHaveBeenCalled();
      expect(decode).not.toHaveBeenCalled();
      expect(fetchMock).toHaveBeenCalledOnce();
    });

    it.each(
      (['json', 'blob'] as const).flatMap((transport) => [
        [transport, 'one trimmed character', ' x ', 'x'],
        [
          transport,
          '512 trimmed characters',
          ` \n${'x'.repeat(COMMAND_HTTP_ERROR_DETAIL_MAX_LENGTH)}\t `,
          'x'.repeat(COMMAND_HTTP_ERROR_DETAIL_MAX_LENGTH),
        ],
      ] as const),
    )('accepts a %s %s detail', async (transport, _label, rawDetail, expectedDetail) => {
      const response = jsonResponse({ detail: rawDetail }, 422);
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response.response));

      const promise = requestThrough(transport);

      await expect(promise).rejects.toMatchObject({
        status: 422,
        detail: expectedDetail,
        message: expectedDetail,
      });
      expect(response.json).toHaveBeenCalledOnce();
      expect(response.blob).not.toHaveBeenCalled();
    });

    it.each(
      (['json', 'blob'] as const).flatMap((transport) => [
        [transport, 'blank detail', { detail: ' \t\n ' }],
        [
          transport,
          '513-character detail',
          { detail: 'private-'.padEnd(COMMAND_HTTP_ERROR_DETAIL_MAX_LENGTH + 1, 'x') },
        ],
        [transport, 'non-string detail', { detail: { private: 'do-not-stringify' } }],
        [transport, 'missing detail', { message: 'private-message' }],
        [transport, 'array body', [{ detail: 'private-array-detail' }]],
        [transport, 'null body', null],
        [transport, 'string body', 'private-string-body'],
      ] as const),
    )('uses the exact fallback for a %s response with %s', async (transport, _label, body) => {
      const response = jsonResponse(body, 500);
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response.response));

      const promise = requestThrough(transport);

      await expect(promise).rejects.toMatchObject({
        status: 500,
        detail: 'Command request failed (500)',
        message: 'Command request failed (500)',
      });
      await expect(promise).rejects.not.toThrow(/private|do-not-stringify/);
      expect(response.json).toHaveBeenCalledOnce();
      expect(response.blob).not.toHaveBeenCalled();
    });

    it.each(['json', 'blob'] as const)(
      'uses the exact fallback for invalid JSON on the %s transport',
      async (transport) => {
        const response = textResponse('{"detail":"private-error"', 500);
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response.response));

        const promise = requestThrough(transport);

        await expect(promise).rejects.toMatchObject({
          status: 500,
          detail: 'Command request failed (500)',
          message: 'Command request failed (500)',
        });
        await expect(promise).rejects.not.toThrow(/private-error/);
        expect(response.json).toHaveBeenCalledOnce();
        expect(response.blob).not.toHaveBeenCalled();
      },
    );

    it.each(['json', 'blob'] as const)(
      'rethrows an abort raised while parsing a %s error body unchanged',
      async (transport) => {
        const abortError = new DOMException('Body stream aborted', 'AbortError');
        const json = vi.fn().mockRejectedValue(abortError);
        const blob = vi.fn();
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
          ok: false,
          status: 499,
          json,
          blob,
        }));

        const promise = requestThrough(transport);

        await expect(promise).rejects.toBe(abortError);
        expect(json).toHaveBeenCalledOnce();
        expect(blob).not.toHaveBeenCalled();
      },
    );
  });

  describe('native cancellation', () => {
    it.each(['json', 'blob'] as const)(
      'returns the same already-aborted reason for %s requests',
      async (transport) => {
        const controller = new AbortController();
        const abortError = new DOMException('Already aborted', 'AbortError');
        controller.abort(abortError);
        const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
          const signal = init?.signal;
          return signal?.aborted
            ? Promise.reject(signal.reason)
            : Promise.reject(new Error('Expected an aborted signal'));
        });
        vi.stubGlobal('fetch', fetchMock);

        const promise = requestThrough(transport, controller.signal);

        await expect(promise).rejects.toBe(abortError);
        expect(fetchMock).toHaveBeenCalledOnce();
        expect(fetchMock.mock.calls[0]?.[1]?.signal).toBe(controller.signal);
      },
    );

    it.each(['json', 'blob'] as const)(
      'returns the same in-flight abort reason for %s requests',
      async (transport) => {
        const controller = new AbortController();
        const abortError = new DOMException('Cancelled in flight', 'AbortError');
        const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            const signal = init?.signal;
            if (signal?.aborted) {
              reject(signal.reason);
              return;
            }
            signal?.addEventListener('abort', () => reject(signal.reason), { once: true });
          }));
        vi.stubGlobal('fetch', fetchMock);

        const promise = requestThrough(transport, controller.signal);
        controller.abort(abortError);

        await expect(promise).rejects.toBe(abortError);
        expect(fetchMock).toHaveBeenCalledOnce();
        expect(fetchMock.mock.calls[0]?.[1]?.signal).toBe(controller.signal);
      },
    );
  });
});
