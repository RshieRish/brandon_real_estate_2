import {
  commandJson,
  CommandDecodeError,
  CommandHttpError,
  type Decoder,
} from './http';

const COMMAND_API_URL = `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}/api/v1/command`;
const DATABASE_INTEGER_MAX = 2_147_483_647;
const HTTP_DETAIL_MAX_LENGTH = 512;
const OUTCOME_UNCERTAIN_MESSAGE = 'The server may have applied the task change; refresh before retrying.';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const RFC3339_PATTERN = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:[Zz]|[+-](\d{2}):(\d{2}))$/;

export type TaskVisibility = 'active' | 'archived' | 'all';
export type TaskPriority = 'low' | 'normal' | 'high';
export type TaskStatus = 'open' | 'in_progress' | 'completed' | 'cancelled';

export type Task = Readonly<{
  id: number;
  title: string;
  contact_id: number | null;
  description: string;
  priority: TaskPriority;
  due_at: string | null;
  status: TaskStatus;
  archived_at: string | null;
  archive_reason: string | null;
  version: number;
}>;

export type TaskLink = Readonly<{
  id: number;
  task_id: number;
  entity_type: string;
  entity_id: number;
  display_name: string;
  task_version: number;
}>;

export type TaskFilters = Readonly<{
  visibility?: TaskVisibility;
  status?: TaskStatus;
  due_before?: string;
  due_after?: string;
}>;

export type TaskCreateInput = Pick<
  Task,
  'title' | 'description' | 'priority' | 'contact_id' | 'due_at'
>;

export type TaskUpdateRequest = Readonly<{
  expected_version: number;
  title?: string;
  description?: string;
  priority?: TaskPriority;
  status?: TaskStatus;
  due_at?: string | null;
  contact_id?: number | null;
}>;

export type TaskLinkRequest = Readonly<{
  expected_version: number;
  entity_type: string;
  entity_id: number;
}>;

export type TaskLifecycleRequest = Readonly<{
  request_id: string;
  expected_version: number;
  reason?: string;
}>;

export type TaskConflict = Readonly<{
  code: 'task_version_conflict' | 'task_archived' | 'task_request_mismatch';
  current_version: number;
  current_task: Task;
}>;

export type TaskRequestOptions = Readonly<{ signal?: AbortSignal }>;

export class CommandConflictError extends Error {
  readonly name = 'CommandConflictError';

  constructor(readonly conflict: TaskConflict) {
    super('The task changed on the server; refresh before retrying.');
  }
}

export class CommandOutcomeUncertainError extends Error {
  readonly name = 'CommandOutcomeUncertainError';
  readonly cause: unknown;

  constructor(cause: unknown) {
    super(OUTCOME_UNCERTAIN_MESSAGE);
    this.cause = cause;
  }
}

type Reader = (key: string) => unknown;

function invalid(path: string, expected: string): never {
  throw new CommandDecodeError(path, expected);
}

function exactObject(input: unknown, keys: readonly string[], path: string): Reader {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) {
    return invalid(path, 'object');
  }
  const actual = Object.keys(input);
  if (actual.length !== keys.length || actual.some((key) => !keys.includes(key))) {
    return invalid(path, `object with exactly ${keys.join(', ')}`);
  }
  return (key: string): unknown => Reflect.get(input, key);
}

function inputObject(
  input: unknown,
  allowed: readonly string[],
  required: readonly string[],
  path: string,
): Reader {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) {
    return invalid(path, 'object');
  }
  const actual = Object.keys(input);
  if (actual.some((key) => !allowed.includes(key)) || required.some((key) => !actual.includes(key))) {
    return invalid(path, `object with allowed fields ${allowed.join(', ')}`);
  }
  return (key: string): unknown => Reflect.get(input, key);
}

function stringValue(input: unknown, path: string, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): string {
  if (typeof input !== 'string') return invalid(path, `string length ${minimum}..${maximum}`);
  const length = Array.from(input).length;
  if (length < minimum || length > maximum) {
    return invalid(path, `string length ${minimum}..${maximum}`);
  }
  return input;
}

function nonblankString(input: unknown, path: string, maximum: number): string {
  const value = stringValue(input, path, 1, maximum);
  if (value.trim().length === 0) return invalid(path, 'nonblank string');
  return value;
}

function nullableString(input: unknown, path: string): string | null {
  return input === null ? null : stringValue(input, path);
}

function positiveSafeInteger(input: unknown, path: string): number {
  if (typeof input !== 'number' || !Number.isSafeInteger(input) || input < 1) {
    return invalid(path, 'positive safe integer');
  }
  return input;
}

function databaseInteger(input: unknown, path: string): number {
  const value = positiveSafeInteger(input, path);
  if (value > DATABASE_INTEGER_MAX) {
    return invalid(path, `integer 1..${DATABASE_INTEGER_MAX}`);
  }
  return value;
}

function nullablePositiveSafeInteger(input: unknown, path: string): number | null {
  return input === null ? null : positiveSafeInteger(input, path);
}

function enumValue<Value extends string>(
  input: unknown,
  values: readonly Value[],
  path: string,
): Value {
  if (typeof input !== 'string') return invalid(path, values.join('|'));
  const match = values.find((value) => value === input);
  return match ?? invalid(path, values.join('|'));
}

function nullableRfc3339(input: unknown, path: string): string | null {
  if (input === null) return null;
  const value = stringValue(input, path);
  const match = RFC3339_PATTERN.exec(value);
  if (match === null) {
    return invalid(path, 'RFC 3339 datetime with UTC offset or null');
  }
  const [, rawYear, rawMonth, rawDay, rawHour, rawMinute, rawSecond, rawOffsetHour, rawOffsetMinute] = match;
  const year = Number(rawYear);
  const month = Number(rawMonth);
  const day = Number(rawDay);
  const hour = Number(rawHour);
  const minute = Number(rawMinute);
  const second = Number(rawSecond);
  const offsetHour = rawOffsetHour === undefined ? 0 : Number(rawOffsetHour);
  const offsetMinute = rawOffsetMinute === undefined ? 0 : Number(rawOffsetMinute);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [
    31,
    leapYear ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ];
  if (
    year < 1
    || month < 1
    || month > 12
    || day < 1
    || day > (daysInMonth[month - 1] ?? 0)
    || hour > 23
    || minute > 59
    || second > 59
    || offsetHour > 23
    || offsetMinute > 59
  ) {
    return invalid(path, 'calendar-valid RFC 3339 datetime with UTC offset or null');
  }
  return value;
}

function uuidValue(input: unknown, path: string): string {
  const value = stringValue(input, path);
  if (!UUID_PATTERN.test(value)) return invalid(path, 'UUID');
  return value;
}

function decodeArray<Value>(
  input: unknown,
  path: string,
  decode: (value: unknown, childPath: string) => Value,
): readonly Value[] {
  if (!Array.isArray(input)) return invalid(path, 'array');
  return input.map((value, index) => decode(value, `${path}[${index}]`));
}

const TASK_FIELDS = [
  'id',
  'title',
  'contact_id',
  'description',
  'priority',
  'due_at',
  'status',
  'archived_at',
  'archive_reason',
  'version',
] as const;

export const decodeTask: Decoder<Task> = (input, path = 'response') => {
  const read = exactObject(input, TASK_FIELDS, path);
  return {
    id: positiveSafeInteger(read('id'), `${path}.id`),
    title: stringValue(read('title'), `${path}.title`),
    contact_id: nullablePositiveSafeInteger(read('contact_id'), `${path}.contact_id`),
    description: stringValue(read('description'), `${path}.description`),
    priority: enumValue(read('priority'), ['low', 'normal', 'high'], `${path}.priority`),
    due_at: nullableString(read('due_at'), `${path}.due_at`),
    status: enumValue(
      read('status'),
      ['open', 'in_progress', 'completed', 'cancelled'],
      `${path}.status`,
    ),
    archived_at: nullableString(read('archived_at'), `${path}.archived_at`),
    archive_reason: nullableString(read('archive_reason'), `${path}.archive_reason`),
    version: positiveSafeInteger(read('version'), `${path}.version`),
  };
};

export const decodeTasks: Decoder<readonly Task[]> = (input, path = 'response') => (
  decodeArray(input, path, decodeTask)
);

const TASK_LINK_FIELDS = [
  'id',
  'task_id',
  'entity_type',
  'entity_id',
  'display_name',
  'task_version',
] as const;

export const decodeTaskLink: Decoder<TaskLink> = (input, path = 'response') => {
  const read = exactObject(input, TASK_LINK_FIELDS, path);
  return {
    id: positiveSafeInteger(read('id'), `${path}.id`),
    task_id: positiveSafeInteger(read('task_id'), `${path}.task_id`),
    entity_type: stringValue(read('entity_type'), `${path}.entity_type`),
    entity_id: positiveSafeInteger(read('entity_id'), `${path}.entity_id`),
    display_name: stringValue(read('display_name'), `${path}.display_name`),
    task_version: positiveSafeInteger(read('task_version'), `${path}.task_version`),
  };
};

export const decodeTaskLinks: Decoder<readonly TaskLink[]> = (input, path = 'response') => (
  decodeArray(input, path, decodeTaskLink)
);

const CONFLICT_CODES: readonly TaskConflict['code'][] = [
  'task_version_conflict',
  'task_archived',
  'task_request_mismatch',
];

export const decodeTaskConflict: Decoder<TaskConflict> = (input, path = 'response.detail') => {
  const read = exactObject(input, ['code', 'current_version', 'current_task'], path);
  const currentVersion = positiveSafeInteger(read('current_version'), `${path}.current_version`);
  const currentTask = decodeTask(read('current_task'), `${path}.current_task`);
  if (currentTask.version !== currentVersion) {
    return invalid(path, 'conflict version matching current task');
  }
  return {
    code: enumValue(read('code'), CONFLICT_CODES, `${path}.code`),
    current_version: currentVersion,
    current_task: currentTask,
  };
};

function decodeConflictResponse(input: unknown): TaskConflict {
  const read = exactObject(input, ['detail'], 'response');
  return decodeTaskConflict(read('detail'));
}

function serializeTaskFilters(filters: TaskFilters): string {
  const read = inputObject(
    filters,
    ['visibility', 'status', 'due_before', 'due_after'],
    [],
    'request.filters',
  );
  const params = new URLSearchParams();
  const visibility = read('visibility');
  if (visibility !== undefined) {
    params.set('visibility', enumValue(visibility, ['active', 'archived', 'all'], 'request.visibility'));
  }
  const status = read('status');
  if (status !== undefined) {
    params.set(
      'status',
      enumValue(status, ['open', 'in_progress', 'completed', 'cancelled'], 'request.status'),
    );
  }
  for (const key of ['due_before', 'due_after'] as const) {
    const raw = read(key);
    if (raw !== undefined) params.set(key, nullableRfc3339(raw, `request.${key}`) ?? invalid(`request.${key}`, 'RFC 3339 datetime'));
  }
  return params.toString();
}

function decodeTaskCreateInput(input: TaskCreateInput): TaskCreateInput {
  const read = exactObject(
    input,
    ['title', 'contact_id', 'description', 'priority', 'due_at'],
    'request',
  );
  const contactId = read('contact_id');
  return {
    title: nonblankString(read('title'), 'request.title', 255),
    contact_id: contactId === null ? null : databaseInteger(contactId, 'request.contact_id'),
    description: stringValue(read('description'), 'request.description', 0, 65_536),
    priority: enumValue(read('priority'), ['low', 'normal', 'high'], 'request.priority'),
    due_at: nullableRfc3339(read('due_at'), 'request.due_at'),
  };
}

function decodeTaskUpdateRequest(input: TaskUpdateRequest): TaskUpdateRequest {
  const fields = [
    'expected_version', 'title', 'description', 'priority', 'status', 'due_at', 'contact_id',
  ] as const;
  const read = inputObject(input, fields, ['expected_version'], 'request');
  const actual = Object.keys(input);
  if (actual.length < 2) return invalid('request', 'expected_version and at least one task change');
  const decoded: {
    expected_version: number;
    title?: string;
    description?: string;
    priority?: TaskPriority;
    status?: TaskStatus;
    due_at?: string | null;
    contact_id?: number | null;
  } = { expected_version: databaseInteger(read('expected_version'), 'request.expected_version') };
  if (actual.includes('title')) decoded.title = nonblankString(read('title'), 'request.title', 255);
  if (actual.includes('description')) {
    decoded.description = stringValue(read('description'), 'request.description', 0, 65_536);
  }
  if (actual.includes('priority')) {
    decoded.priority = enumValue(
      read('priority'),
      ['low', 'normal', 'high'] as const,
      'request.priority',
    );
  }
  if (actual.includes('status')) {
    decoded.status = enumValue(
      read('status'),
      ['open', 'in_progress', 'completed', 'cancelled'] as const,
      'request.status',
    );
  }
  if (actual.includes('due_at')) decoded.due_at = nullableRfc3339(read('due_at'), 'request.due_at');
  if (actual.includes('contact_id')) {
    const contactId = read('contact_id');
    decoded.contact_id = contactId === null ? null : databaseInteger(contactId, 'request.contact_id');
  }
  return decoded;
}

function decodeTaskLinkRequest(input: TaskLinkRequest): TaskLinkRequest {
  const read = exactObject(input, ['expected_version', 'entity_type', 'entity_id'], 'request');
  return {
    expected_version: databaseInteger(read('expected_version'), 'request.expected_version'),
    entity_type: nonblankString(read('entity_type'), 'request.entity_type', 50),
    entity_id: databaseInteger(read('entity_id'), 'request.entity_id'),
  };
}

function decodeTaskLifecycleRequest(input: TaskLifecycleRequest): TaskLifecycleRequest {
  const fields = ['request_id', 'expected_version', 'reason'] as const;
  const read = inputObject(input, fields, ['request_id', 'expected_version'], 'request');
  const decoded: { request_id: string; expected_version: number; reason?: string } = {
    request_id: uuidValue(read('request_id'), 'request.request_id'),
    expected_version: databaseInteger(read('expected_version'), 'request.expected_version'),
  };
  if (Object.prototype.hasOwnProperty.call(input, 'reason')) {
    decoded.reason = stringValue(read('reason'), 'request.reason', 0, 500);
  }
  return decoded;
}

function fallbackDetail(status: number): string {
  return `Command request failed (${status})`;
}

async function definiteHttpError(response: Response): Promise<CommandHttpError> {
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    return new CommandHttpError(response.status, fallbackDetail(response.status));
  }
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    const raw = Reflect.get(value, 'detail');
    if (typeof raw === 'string') {
      const detail = raw.trim();
      if (detail.length >= 1 && detail.length <= HTTP_DETAIL_MAX_LENGTH) {
        return new CommandHttpError(response.status, detail);
      }
    }
  }
  return new CommandHttpError(response.status, fallbackDetail(response.status));
}

type TaskMutationRequest<Value> = Readonly<{
  path: string;
  method: 'POST' | 'PATCH';
  body: unknown;
  decode: Decoder<Value>;
  idempotencyKey?: string;
  signal?: AbortSignal;
}>;

async function taskMutation<Value>(request: TaskMutationRequest<Value>): Promise<Value> {
  const token = localStorage.getItem('admin_token');
  if (token === null || token.trim().length === 0) {
    throw new CommandHttpError(401, 'Administrator session required');
  }
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };
  if (request.idempotencyKey !== undefined) {
    headers['X-Idempotency-Key'] = request.idempotencyKey;
  }

  let response: Response;
  try {
    response = await fetch(`${COMMAND_API_URL}${request.path}`, {
      method: request.method,
      headers,
      body: JSON.stringify(request.body),
      signal: request.signal,
    });
  } catch (cause) {
    throw new CommandOutcomeUncertainError(cause);
  }

  if (response.status === 409) {
    try {
      throw new CommandConflictError(decodeConflictResponse(await response.json()));
    } catch (error) {
      if (error instanceof CommandConflictError) throw error;
      throw new CommandOutcomeUncertainError(error);
    }
  }
  if (response.status >= 500 || response.status < 400 && !response.ok) {
    throw new CommandOutcomeUncertainError(
      new CommandHttpError(response.status, fallbackDetail(response.status)),
    );
  }
  if (!response.ok) throw await definiteHttpError(response);

  try {
    return request.decode(await response.json());
  } catch (cause) {
    throw new CommandOutcomeUncertainError(cause);
  }
}

export function loadTasks(
  filters: TaskFilters = {},
  options?: TaskRequestOptions,
): Promise<readonly Task[]> {
  const query = serializeTaskFilters(filters);
  return commandJson({
    path: `/tasks${query ? `?${query}` : ''}`,
    decode: decodeTasks,
    signal: options?.signal,
  });
}

export function loadTaskLinks(taskId: number, options?: TaskRequestOptions): Promise<readonly TaskLink[]> {
  const id = databaseInteger(taskId, 'request.task_id');
  return commandJson({
    path: `/tasks/${id}/links`,
    decode: decodeTaskLinks,
    signal: options?.signal,
  });
}

export async function createTask(
  input: TaskCreateInput,
  idempotencyKey: string,
  options?: TaskRequestOptions,
): Promise<Task> {
  const body = decodeTaskCreateInput(input);
  const key = uuidValue(idempotencyKey, 'request.idempotency_key');
  return taskMutation({
    path: '/tasks',
    method: 'POST',
    body,
    decode: decodeTask,
    idempotencyKey: key,
    signal: options?.signal,
  });
}

export async function updateTask(
  taskId: number,
  input: TaskUpdateRequest,
  options?: TaskRequestOptions,
): Promise<Task> {
  const id = databaseInteger(taskId, 'request.task_id');
  const body = decodeTaskUpdateRequest(input);
  return taskMutation({
    path: `/tasks/${id}`,
    method: 'PATCH',
    body,
    decode: decodeTask,
    signal: options?.signal,
  });
}

export async function addTaskLink(
  taskId: number,
  input: TaskLinkRequest,
  options?: TaskRequestOptions,
): Promise<TaskLink> {
  const id = databaseInteger(taskId, 'request.task_id');
  const body = decodeTaskLinkRequest(input);
  return taskMutation({
    path: `/tasks/${id}/links`,
    method: 'POST',
    body,
    decode: decodeTaskLink,
    signal: options?.signal,
  });
}

function changeArchiveState(
  action: 'archive' | 'restore',
  taskId: number,
  input: TaskLifecycleRequest,
  options?: TaskRequestOptions,
): Promise<Task> {
  const id = databaseInteger(taskId, 'request.task_id');
  const body = decodeTaskLifecycleRequest(input);
  return taskMutation({
    path: `/tasks/${id}/${action}`,
    method: 'POST',
    body,
    decode: decodeTask,
    signal: options?.signal,
  });
}

export async function archiveTask(
  taskId: number,
  input: TaskLifecycleRequest,
  options?: TaskRequestOptions,
): Promise<Task> {
  return changeArchiveState('archive', taskId, input, options);
}

export async function restoreTask(
  taskId: number,
  input: TaskLifecycleRequest,
  options?: TaskRequestOptions,
): Promise<Task> {
  return changeArchiveState('restore', taskId, input, options);
}
