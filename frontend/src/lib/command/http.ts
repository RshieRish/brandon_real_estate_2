const COMMAND_API_URL = `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}/api/v1/command`;

export type Decoder<T> = (input: unknown, path?: string) => T;

export class CommandHttpError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
  }
}

export class CommandDecodeError extends Error {
  constructor(
    readonly path: string,
    readonly expected: string,
  ) {
    super(`Invalid Command response at ${path}: expected ${expected}`);
  }
}

export const COMMAND_HTTP_ERROR_DETAIL_MAX_LENGTH = 512;

export type CommandJsonRequest<T> = Readonly<{
  path: string;
  decode: Decoder<T>;
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
}>;

export type CommandBlobRequest = Readonly<{
  path: string;
  signal?: AbortSignal;
}>;

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function fallbackDetail(status: number): string {
  return `Command request failed (${status})`;
}

async function responseError(response: Response): Promise<CommandHttpError> {
  let value: unknown;
  try {
    value = await response.json();
  } catch (error) {
    if (isAbortError(error)) throw error;
    return new CommandHttpError(response.status, fallbackDetail(response.status));
  }

  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    const candidate = Reflect.get(value, 'detail');
    if (typeof candidate === 'string') {
      const detail = candidate.trim();
      if (detail.length >= 1 && detail.length <= COMMAND_HTTP_ERROR_DETAIL_MAX_LENGTH) {
        return new CommandHttpError(response.status, detail);
      }
    }
  }

  return new CommandHttpError(response.status, fallbackDetail(response.status));
}

async function authenticatedFetch(path: string, init: RequestInit): Promise<Response> {
  const token = localStorage.getItem('admin_token');
  if (token === null || token.trim().length === 0) {
    throw new CommandHttpError(401, 'Administrator session required');
  }

  const headers = init.headers
    ? Object.assign({ Authorization: `Bearer ${token}` }, init.headers)
    : { Authorization: `Bearer ${token}` };
  const response = await fetch(`${COMMAND_API_URL}${path}`, { ...init, headers });
  if (!response.ok) throw await responseError(response);
  return response;
}

export async function commandJson<T>(request: CommandJsonRequest<T>): Promise<T> {
  const init: RequestInit = {
    method: request.method ?? 'GET',
    headers: { 'Content-Type': 'application/json' },
    signal: request.signal,
  };
  if (request.body !== undefined) {
    const body = JSON.stringify(request.body);
    if (body !== undefined) init.body = body;
  }

  const response = await authenticatedFetch(request.path, init);
  if (response.status === 204) return request.decode(null);

  let value: unknown;
  try {
    value = await response.json();
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new CommandDecodeError('response', 'valid JSON');
  }
  return request.decode(value);
}

export async function commandBlob(request: CommandBlobRequest): Promise<Blob> {
  const response = await authenticatedFetch(request.path, { signal: request.signal });
  return response.blob();
}
