import {
  commandJson,
  CommandDecodeError,
  CommandHttpError,
  type Decoder,
} from './http';
export {
  consumeTaskSuggestionHandoffBootstrap,
  installTaskSuggestionHandoffBootstrap,
} from './task-suggestion-handoff';
export type {
  CapturedTaskSuggestionHandoff,
  TaskSuggestionHandoffBootstrapMetadata,
} from './task-suggestion-handoff';

const DATABASE_INTEGER_MAX = 2_147_483_647;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const HASH_PATTERN = /^[0-9a-f]{64}$/;
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$/;
const RFC3339_PATTERN = /^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$/;

export type TaskSuggestionSource = 'gmail_message' | 'sydney_chat';
export type TaskSuggestionPriority = 'low' | 'normal' | 'high';
export type TaskSuggestionState =
  | 'needs_clarification'
  | 'possible_duplicate'
  | 'pending_review'
  | 'approved'
  | 'dismissed'
  | 'applied'
  | 'failed';
export type TaskSuggestionClarificationState =
  | 'not_required'
  | 'pending'
  | 'answered'
  | 'timed_out'
  | 'manual_review_required';
export type TaskSuggestionBlocker =
  | 'missing_required_field'
  | 'ambiguous_due_at'
  | 'ambiguous_contact'
  | 'multiple_actions'
  | 'unsupported_owner'
  | 'unsupported_link';
export type TaskSuggestionResolutionRequirement =
  | 'resolve_owner_as_brandon'
  | 'create_without_unsupported_link'
  | 'accept_current_task_details'
  | 'treat_as_single_action'
  | 'confirm_not_duplicate';
export type TaskSuggestionSourceDirection = 'received' | 'sent' | 'self_copy';
export type TaskSuggestionEventType =
  | 'edit'
  | 'clarification_asked'
  | 'clarification_answered'
  | 'clarification_timed_out'
  | 'clarification_superseded'
  | 'clarification_delivery_retry'
  | 'dismiss'
  | 'preview'
  | 'approve'
  | 'apply'
  | 'reprocess'
  | 'dismiss_proposed';

export type TaskSuggestionSourceEvidence = Readonly<{
  direction: TaskSuggestionSourceDirection;
  source_label: string;
  created_at: string;
}>;

export type TaskSuggestionAuditEvent = Readonly<{
  suggestion_version: number;
  event_type: TaskSuggestionEventType;
  actor_type: 'system' | 'sydney' | 'command_admin' | 'untrusted_hermes_input';
  action_audited: boolean;
  created_at: string;
}>;

export type TaskSuggestion = Readonly<{
  id: string;
  source_type: TaskSuggestionSource;
  title: string;
  description: string;
  priority: TaskSuggestionPriority;
  due_at: string | null;
  contact_id: number | null;
  status: 'open';
  state: TaskSuggestionState;
  clarification_state: TaskSuggestionClarificationState;
  blocker_codes: readonly TaskSuggestionBlocker[];
  resolution_requirements: readonly TaskSuggestionResolutionRequirement[];
  confidence: number;
  rationale: string;
  model_schema_version: string;
  sources: readonly TaskSuggestionSourceEvidence[];
  audit_trail: readonly TaskSuggestionAuditEvent[];
  payload_hash: string;
  version: number;
  applied_task_id: number | null;
  created_at: string;
  updated_at: string;
}>;

export type TaskSuggestionList = Readonly<{
  suggestions: readonly TaskSuggestion[];
}>;

export type TaskSuggestionPayload = Readonly<{
  title: string;
  description: string;
  priority: TaskSuggestionPriority;
  due_at: string | null;
  contact_id: number | null;
  status: 'open';
}>;

export type TaskSuggestionPreview = Readonly<{
  suggestion_id: string;
  suggestion_version: number;
  payload_hash: string;
  task: TaskSuggestionPayload;
}>;

export type ApprovalPrepare = TaskSuggestionPreview & Readonly<{
  approval: string;
  expires_at: string;
}>;

export type ApprovalResult = Readonly<{
  suggestion_id: string;
  suggestion_version: number;
  task_id: number;
  request_id: string;
  replayed: boolean;
}>;

export type SuggestionVersionRequest = Readonly<{
  expected_version: number;
  expected_payload_hash: string;
}>;

export type TaskSuggestionEditRequest = SuggestionVersionRequest & Readonly<{
  title?: string;
  description?: string;
  priority?: TaskSuggestionPriority;
  due_at?: string | null;
  contact_id?: number | null;
  resolve_owner_as_brandon?: boolean;
  create_without_unsupported_link?: boolean;
  accept_current_task_details?: boolean;
  treat_as_single_action?: boolean;
  confirm_not_duplicate?: boolean;
}>;

export type HandoffExchangeRequest = SuggestionVersionRequest & Readonly<{
  handoff: string;
}>;

export type TaskSuggestionApprovalRequest = SuggestionVersionRequest & Readonly<{
  approval: string;
  request_id: string;
  client_timezone: string;
}>;

export type TaskSuggestionDismissRequest = SuggestionVersionRequest & Readonly<{
  reason: string;
}>;

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
  return (key: string) => Reflect.get(input, key);
}

function stringValue(input: unknown, path: string, minimum: number, maximum: number): string {
  if (typeof input !== 'string') return invalid(path, `string length ${minimum}..${maximum}`);
  const length = Array.from(input).length;
  if (length < minimum || length > maximum) {
    return invalid(path, `string length ${minimum}..${maximum}`);
  }
  return input;
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

function databaseInteger(input: unknown, path: string): number {
  if (
    typeof input !== 'number'
    || !Number.isSafeInteger(input)
    || input < 1
    || input > DATABASE_INTEGER_MAX
  ) {
    return invalid(path, `integer 1..${DATABASE_INTEGER_MAX}`);
  }
  return input;
}

function nullableDatabaseInteger(input: unknown, path: string): number | null {
  return input === null ? null : databaseInteger(input, path);
}

function booleanValue(input: unknown, path: string): boolean {
  return typeof input === 'boolean' ? input : invalid(path, 'boolean');
}

function confidenceValue(input: unknown, path: string): number {
  if (typeof input !== 'number' || !Number.isFinite(input) || input < 0 || input > 1) {
    return invalid(path, 'finite number 0..1');
  }
  return input;
}

function uuidValue(input: unknown, path: string): string {
  const value = stringValue(input, path, 36, 36);
  return UUID_PATTERN.test(value) ? value : invalid(path, 'UUID');
}

function hashValue(input: unknown, path: string): string {
  const value = stringValue(input, path, 64, 64);
  return HASH_PATTERN.test(value) ? value : invalid(path, 'lowercase SHA-256 hash');
}

function tokenValue(input: unknown, path: string): string {
  const value = stringValue(input, path, 43, 43);
  return TOKEN_PATTERN.test(value) ? value : invalid(path, 'canonical 32-byte base64url token');
}

function rfc3339Value(input: unknown, path: string): string {
  const value = stringValue(input, path, 20, 40);
  if (!RFC3339_PATTERN.test(value) || !Number.isFinite(Date.parse(value))) {
    return invalid(path, 'RFC 3339 datetime with UTC offset');
  }
  return value;
}

function nullableRfc3339Value(input: unknown, path: string): string | null {
  return input === null ? null : rfc3339Value(input, path);
}

function decodeTaskPayload(input: unknown, path = 'response.task'): TaskSuggestionPayload {
  const read = exactObject(
    input,
    ['title', 'description', 'priority', 'due_at', 'contact_id', 'status'],
    path,
  );
  return {
    title: stringValue(read('title'), `${path}.title`, 1, 255),
    description: stringValue(read('description'), `${path}.description`, 0, 5000),
    priority: enumValue(read('priority'), ['low', 'normal', 'high'], `${path}.priority`),
    due_at: nullableRfc3339Value(read('due_at'), `${path}.due_at`),
    contact_id: nullableDatabaseInteger(read('contact_id'), `${path}.contact_id`),
    status: enumValue(read('status'), ['open'], `${path}.status`),
  };
}

export const decodeTaskSuggestion: Decoder<TaskSuggestion> = (
  input,
  path = 'response',
) => {
  const read = exactObject(
    input,
    [
      'id',
      'source_type',
      'title',
      'description',
      'priority',
      'due_at',
      'contact_id',
      'status',
      'state',
      'clarification_state',
      'blocker_codes',
      'resolution_requirements',
      'confidence',
      'rationale',
      'model_schema_version',
      'sources',
      'audit_trail',
      'payload_hash',
      'version',
      'applied_task_id',
      'created_at',
      'updated_at',
    ],
    path,
  );
  const rawBlockers = read('blocker_codes');
  if (!Array.isArray(rawBlockers) || rawBlockers.length > 6) {
    return invalid(`${path}.blocker_codes`, 'array with at most 6 blockers');
  }
  const blockers: TaskSuggestionBlocker[] = rawBlockers.map((blocker, index) =>
    enumValue(
      blocker,
      [
        'missing_required_field',
        'ambiguous_due_at',
        'ambiguous_contact',
        'multiple_actions',
        'unsupported_owner',
        'unsupported_link',
      ] as const,
      `${path}.blocker_codes[${index}]`,
    ),
  );
  if (new Set(blockers).size !== blockers.length) {
    return invalid(`${path}.blocker_codes`, 'unique blocker codes');
  }
  const rawResolutionRequirements = read('resolution_requirements');
  if (!Array.isArray(rawResolutionRequirements) || rawResolutionRequirements.length > 5) {
    return invalid(`${path}.resolution_requirements`, 'array with at most 5 requirements');
  }
  const resolutionRequirements: TaskSuggestionResolutionRequirement[] =
    rawResolutionRequirements.map((requirement, index) =>
      enumValue(
        requirement,
        [
          'resolve_owner_as_brandon',
          'create_without_unsupported_link',
          'accept_current_task_details',
          'treat_as_single_action',
          'confirm_not_duplicate',
        ] as const,
        `${path}.resolution_requirements[${index}]`,
      ),
    );
  if (new Set(resolutionRequirements).size !== resolutionRequirements.length) {
    return invalid(`${path}.resolution_requirements`, 'unique resolution requirements');
  }
  const rawSources = read('sources');
  if (!Array.isArray(rawSources) || rawSources.length > 20) {
    return invalid(`${path}.sources`, 'array with at most 20 sources');
  }
  const sources = rawSources.map((source, index): TaskSuggestionSourceEvidence => {
    const sourcePath = `${path}.sources[${index}]`;
    const sourceRead = exactObject(source, ['direction', 'source_label', 'created_at'], sourcePath);
    return {
      direction: enumValue(
        sourceRead('direction'),
        ['received', 'sent', 'self_copy'],
        `${sourcePath}.direction`,
      ),
      source_label: stringValue(sourceRead('source_label'), `${sourcePath}.source_label`, 1, 255),
      created_at: rfc3339Value(sourceRead('created_at'), `${sourcePath}.created_at`),
    };
  });
  const rawAuditTrail = read('audit_trail');
  if (!Array.isArray(rawAuditTrail) || rawAuditTrail.length > 20) {
    return invalid(`${path}.audit_trail`, 'array with at most 20 events');
  }
  const auditTrail = rawAuditTrail.map((event, index): TaskSuggestionAuditEvent => {
    const eventPath = `${path}.audit_trail[${index}]`;
    const eventRead = exactObject(
      event,
      ['suggestion_version', 'event_type', 'actor_type', 'action_audited', 'created_at'],
      eventPath,
    );
    return {
      suggestion_version: databaseInteger(
        eventRead('suggestion_version'),
        `${eventPath}.suggestion_version`,
      ),
      event_type: enumValue(
        eventRead('event_type'),
        [
          'edit',
          'clarification_asked',
          'clarification_answered',
          'clarification_timed_out',
          'clarification_superseded',
          'clarification_delivery_retry',
          'dismiss',
          'preview',
          'approve',
          'apply',
          'reprocess',
          'dismiss_proposed',
        ],
        `${eventPath}.event_type`,
      ),
      actor_type: enumValue(
        eventRead('actor_type'),
        ['system', 'sydney', 'command_admin', 'untrusted_hermes_input'],
        `${eventPath}.actor_type`,
      ),
      action_audited: booleanValue(eventRead('action_audited'), `${eventPath}.action_audited`),
      created_at: rfc3339Value(eventRead('created_at'), `${eventPath}.created_at`),
    };
  });
  return {
    id: uuidValue(read('id'), `${path}.id`),
    source_type: enumValue(
      read('source_type'),
      ['gmail_message', 'sydney_chat'],
      `${path}.source_type`,
    ),
    title: stringValue(read('title'), `${path}.title`, 1, 255),
    description: stringValue(read('description'), `${path}.description`, 0, 5000),
    priority: enumValue(read('priority'), ['low', 'normal', 'high'], `${path}.priority`),
    due_at: nullableRfc3339Value(read('due_at'), `${path}.due_at`),
    contact_id: nullableDatabaseInteger(read('contact_id'), `${path}.contact_id`),
    status: enumValue(read('status'), ['open'], `${path}.status`),
    state: enumValue(
      read('state'),
      [
        'needs_clarification',
        'possible_duplicate',
        'pending_review',
        'approved',
        'dismissed',
        'applied',
        'failed',
      ],
      `${path}.state`,
    ),
    clarification_state: enumValue(
      read('clarification_state'),
      ['not_required', 'pending', 'answered', 'timed_out', 'manual_review_required'],
      `${path}.clarification_state`,
    ),
    blocker_codes: blockers,
    resolution_requirements: resolutionRequirements,
    confidence: confidenceValue(read('confidence'), `${path}.confidence`),
    rationale: stringValue(read('rationale'), `${path}.rationale`, 0, 500),
    model_schema_version: stringValue(
      read('model_schema_version'),
      `${path}.model_schema_version`,
      1,
      64,
    ),
    sources,
    audit_trail: auditTrail,
    payload_hash: hashValue(read('payload_hash'), `${path}.payload_hash`),
    version: databaseInteger(read('version'), `${path}.version`),
    applied_task_id: nullableDatabaseInteger(read('applied_task_id'), `${path}.applied_task_id`),
    created_at: rfc3339Value(read('created_at'), `${path}.created_at`),
    updated_at: rfc3339Value(read('updated_at'), `${path}.updated_at`),
  };
};

export const decodeTaskSuggestionList: Decoder<TaskSuggestionList> = (
  input,
  path = 'response',
) => {
  const read = exactObject(input, ['suggestions'], path);
  const rawSuggestions = read('suggestions');
  if (!Array.isArray(rawSuggestions) || rawSuggestions.length > 100) {
    return invalid(`${path}.suggestions`, 'array with at most 100 suggestions');
  }
  return {
    suggestions: rawSuggestions.map((row, index) =>
      decodeTaskSuggestion(row, `${path}.suggestions[${index}]`),
    ),
  };
};

export const decodeTaskSuggestionPreview: Decoder<TaskSuggestionPreview> = (
  input,
  path = 'response',
) => {
  const read = exactObject(
    input,
    ['suggestion_id', 'suggestion_version', 'payload_hash', 'task'],
    path,
  );
  return {
    suggestion_id: uuidValue(read('suggestion_id'), `${path}.suggestion_id`),
    suggestion_version: databaseInteger(
      read('suggestion_version'),
      `${path}.suggestion_version`,
    ),
    payload_hash: hashValue(read('payload_hash'), `${path}.payload_hash`),
    task: decodeTaskPayload(read('task'), `${path}.task`),
  };
};

export const decodeApprovalPrepare: Decoder<ApprovalPrepare> = (
  input,
  path = 'response',
) => {
  const read = exactObject(
    input,
    [
      'suggestion_id',
      'suggestion_version',
      'payload_hash',
      'task',
      'approval',
      'expires_at',
    ],
    path,
  );
  return {
    suggestion_id: uuidValue(read('suggestion_id'), `${path}.suggestion_id`),
    suggestion_version: databaseInteger(
      read('suggestion_version'),
      `${path}.suggestion_version`,
    ),
    payload_hash: hashValue(read('payload_hash'), `${path}.payload_hash`),
    task: decodeTaskPayload(read('task'), `${path}.task`),
    approval: tokenValue(read('approval'), `${path}.approval`),
    expires_at: rfc3339Value(read('expires_at'), `${path}.expires_at`),
  };
};

export const decodeApprovalResult: Decoder<ApprovalResult> = (
  input,
  path = 'response',
) => {
  const read = exactObject(
    input,
    ['suggestion_id', 'suggestion_version', 'task_id', 'request_id', 'replayed'],
    path,
  );
  return {
    suggestion_id: uuidValue(read('suggestion_id'), `${path}.suggestion_id`),
    suggestion_version: databaseInteger(
      read('suggestion_version'),
      `${path}.suggestion_version`,
    ),
    task_id: databaseInteger(read('task_id'), `${path}.task_id`),
    request_id: uuidValue(read('request_id'), `${path}.request_id`),
    replayed: booleanValue(read('replayed'), `${path}.replayed`),
  };
};

function versionBody(payload: SuggestionVersionRequest): SuggestionVersionRequest {
  if (!Number.isSafeInteger(payload.expected_version) || payload.expected_version < 1) {
    return invalid('request.expected_version', 'positive safe integer');
  }
  if (!HASH_PATTERN.test(payload.expected_payload_hash)) {
    return invalid('request.expected_payload_hash', 'lowercase SHA-256 hash');
  }
  return payload;
}

function suggestionPath(suggestionId: string, suffix = ''): string {
  if (!UUID_PATTERN.test(suggestionId)) return invalid('request.suggestion_id', 'UUID');
  return `/task-suggestions/${suggestionId}${suffix}`;
}

export const taskSuggestionsApi = Object.freeze({
  list: (
    options: Readonly<{ state?: TaskSuggestionState; limit?: number; signal?: AbortSignal }> = {},
  ): Promise<TaskSuggestionList> => {
    const limit = options.limit ?? 50;
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
      return Promise.reject(new CommandDecodeError('request.limit', 'integer 1..100'));
    }
    const params = new URLSearchParams({ limit: String(limit) });
    if (options.state !== undefined) params.set('state', options.state);
    return commandJson({
      path: `/task-suggestions?${params.toString()}`,
      decode: decodeTaskSuggestionList,
      signal: options.signal,
    });
  },
  get: (suggestionId: string, signal?: AbortSignal): Promise<TaskSuggestion> =>
    commandJson({
      path: suggestionPath(suggestionId),
      decode: decodeTaskSuggestion,
      signal,
    }),
  edit: (
    suggestionId: string,
    payload: TaskSuggestionEditRequest,
  ): Promise<TaskSuggestion> =>
    commandJson({
      path: suggestionPath(suggestionId),
      method: 'PATCH',
      body: { ...versionBody(payload), ...payload },
      decode: decodeTaskSuggestion,
    }),
  preview: (
    suggestionId: string,
    payload: SuggestionVersionRequest,
  ): Promise<TaskSuggestionPreview> =>
    commandJson({
      path: suggestionPath(suggestionId, '/preview'),
      method: 'POST',
      body: versionBody(payload),
      decode: decodeTaskSuggestionPreview,
    }),
  prepareApproval: (
    suggestionId: string,
    payload: SuggestionVersionRequest,
  ): Promise<ApprovalPrepare> =>
    commandJson({
      path: suggestionPath(suggestionId, '/approval/prepare'),
      method: 'POST',
      body: versionBody(payload),
      decode: decodeApprovalPrepare,
    }),
  exchangeHandoff: (
    suggestionId: string,
    payload: HandoffExchangeRequest,
  ): Promise<ApprovalPrepare> =>
    commandJson({
      path: suggestionPath(suggestionId, '/handoff/exchange'),
      method: 'POST',
      body: { ...versionBody(payload), handoff: tokenValue(payload.handoff, 'request.handoff') },
      decode: decodeApprovalPrepare,
    }),
  approve: (
    suggestionId: string,
    payload: TaskSuggestionApprovalRequest,
  ): Promise<ApprovalResult> =>
    commandJson({
      path: suggestionPath(suggestionId, '/approve'),
      method: 'POST',
      body: {
        ...versionBody(payload),
        approval: tokenValue(payload.approval, 'request.approval'),
        request_id: uuidValue(payload.request_id, 'request.request_id'),
        client_timezone: stringValue(payload.client_timezone, 'request.client_timezone', 1, 64),
      },
      decode: decodeApprovalResult,
    }),
  dismiss: (
    suggestionId: string,
    payload: TaskSuggestionDismissRequest,
  ): Promise<TaskSuggestion> =>
    commandJson({
      path: suggestionPath(suggestionId, '/dismiss'),
      method: 'POST',
      body: { ...versionBody(payload), reason: payload.reason },
      decode: decodeTaskSuggestion,
    }),
});

export function isSuggestionStaleError(error: unknown): boolean {
  return error instanceof CommandHttpError
    && error.status === 409
    && error.detail === 'suggestion_stale';
}
