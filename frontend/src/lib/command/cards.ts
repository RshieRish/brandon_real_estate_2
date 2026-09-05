import { commandJson, CommandDecodeError, type Decoder } from './http';

const DATABASE_INTEGER_MAX = 2_147_483_647;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const DESIGN_KEY_PATTERN = /^[a-z0-9][a-z0-9_-]*$/;
const RFC3339_PATTERN = /^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$/;

export type CardCampaignStatus =
  | 'draft'
  | 'needs_addresses'
  | 'needs_connection'
  | 'ready_for_review'
  | 'approved'
  | 'sending'
  | 'sent'
  | 'partially_sent'
  | 'failed'
  | 'delivery_uncertain';

export type CardCelebrationKind = 'birthday' | 'home_anniversary';
export type CardDeliveryOutcome = 'confirmed' | 'rejected' | 'ambiguous';

export type CardCampaignListItem = Readonly<{
  id: string;
  title: string;
  month: number;
  status: CardCampaignStatus;
  total_recipients: number;
  sendable_recipients: number;
  missing_address_count: number;
  estimated_cost_cents: number;
  currency: 'USD';
  version: number;
  created_at: string;
  updated_at: string;
}>;

export type CardRecipient = Readonly<{
  id: string;
  contact_id: number;
  display_name: string;
  celebration_kind: CardCelebrationKind;
  celebration_month: number;
  celebration_day: number;
  celebration_year: number | null;
  celebration_year_quality: 'verified' | 'yearless' | 'sentinel' | 'unknown';
  celebration_origin: 'internal_crm' | 'recovered';
  message: string;
  design_key: string;
  address_status: 'ready' | 'missing';
  address_summary: string | null;
  excluded: boolean;
  exclusion_reason: string | null;
  delivery_outcome: CardDeliveryOutcome | null;
}>;

export type CardCampaignDetail = CardCampaignListItem & Readonly<{
  request_id: string;
  include_birthdays: boolean;
  include_home_anniversaries: boolean;
  audience_ref: string;
  audience_checksum: string;
  birthday_recipients: number;
  home_anniversary_recipients: number;
  excluded_recipients: number;
  provider_connected: boolean;
  provider_connection_reason: string | null;
  approved_by_actor: string | null;
  approved_at: string | null;
  send_request_id: string | null;
  recipients: readonly CardRecipient[];
}>;

export type CardCampaignPage = Readonly<{
  campaigns: readonly CardCampaignListItem[];
  total: number;
}>;

export type CardCampaignDraftRequest = Readonly<{
  request_id: string;
  month: number;
  include_birthdays: boolean;
  include_home_anniversaries: boolean;
  title?: string;
  birthday_message_template?: string;
  home_anniversary_message_template?: string;
  birthday_design_key?: string;
  home_anniversary_design_key?: string;
}>;

export type CardRecipientUpdate = Readonly<{
  recipient_id: string;
  message?: string;
  design_key?: string;
  excluded?: boolean;
  exclusion_reason?: string;
}>;

export type CardCampaignUpdateRequest = Readonly<{
  expected_version: number;
  refresh_missing_addresses?: boolean;
  title?: string;
  birthday_message_template?: string;
  home_anniversary_message_template?: string;
  birthday_design_key?: string;
  home_anniversary_design_key?: string;
  recipient_updates?: readonly CardRecipientUpdate[];
}>;

export type CardCampaignApproveRequest = Readonly<{
  request_id: string;
  expected_version: number;
  confirmed_recipient_count: number;
  confirmed_cost_cents: number;
  confirmed_by_brandon: true;
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

function nullableString(
  input: unknown,
  path: string,
  minimum: number,
  maximum: number,
): string | null {
  return input === null ? null : stringValue(input, path, minimum, maximum);
}

function enumValue<Value extends string>(
  input: unknown,
  values: readonly Value[],
  path: string,
): Value {
  if (typeof input !== 'string') return invalid(path, values.join('|'));
  return values.find((value) => value === input) ?? invalid(path, values.join('|'));
}

function safeInteger(input: unknown, path: string, minimum: number, maximum: number): number {
  if (
    typeof input !== 'number'
    || !Number.isSafeInteger(input)
    || input < minimum
    || input > maximum
  ) {
    return invalid(path, `integer ${minimum}..${maximum}`);
  }
  return input;
}

function positiveInteger(input: unknown, path: string): number {
  return safeInteger(input, path, 1, DATABASE_INTEGER_MAX);
}

function nonNegativeInteger(input: unknown, path: string): number {
  return safeInteger(input, path, 0, Number.MAX_SAFE_INTEGER);
}

function booleanValue(input: unknown, path: string): boolean {
  return typeof input === 'boolean' ? input : invalid(path, 'boolean');
}

function uuidValue(input: unknown, path: string): string {
  const value = stringValue(input, path, 36, 36);
  return UUID_PATTERN.test(value) ? value : invalid(path, 'UUID');
}

function nullableUuid(input: unknown, path: string): string | null {
  return input === null ? null : uuidValue(input, path);
}

function rfc3339Value(input: unknown, path: string): string {
  const value = stringValue(input, path, 20, 40);
  if (!RFC3339_PATTERN.test(value) || !Number.isFinite(Date.parse(value))) {
    return invalid(path, 'RFC 3339 datetime with UTC offset');
  }
  return value;
}

function nullableRfc3339(input: unknown, path: string): string | null {
  return input === null ? null : rfc3339Value(input, path);
}

function monthValue(input: unknown, path: string): number {
  return safeInteger(input, path, 1, 12);
}

function dayValue(input: unknown, path: string): number {
  return safeInteger(input, path, 1, 31);
}

function designKeyValue(input: unknown, path: string): string {
  const value = stringValue(input, path, 1, 120);
  return DESIGN_KEY_PATTERN.test(value) ? value : invalid(path, 'design key');
}

const campaignStatuses = [
  'draft',
  'needs_addresses',
  'needs_connection',
  'ready_for_review',
  'approved',
  'sending',
  'sent',
  'partially_sent',
  'failed',
  'delivery_uncertain',
] as const;

const listItemKeys = [
  'id',
  'title',
  'month',
  'status',
  'total_recipients',
  'sendable_recipients',
  'missing_address_count',
  'estimated_cost_cents',
  'currency',
  'version',
  'created_at',
  'updated_at',
] as const;

function decodeListItemReader(read: Reader, path: string): CardCampaignListItem {
  return {
    id: uuidValue(read('id'), `${path}.id`),
    title: stringValue(read('title'), `${path}.title`, 1, 255),
    month: monthValue(read('month'), `${path}.month`),
    status: enumValue(read('status'), campaignStatuses, `${path}.status`),
    total_recipients: nonNegativeInteger(read('total_recipients'), `${path}.total_recipients`),
    sendable_recipients: nonNegativeInteger(
      read('sendable_recipients'),
      `${path}.sendable_recipients`,
    ),
    missing_address_count: nonNegativeInteger(
      read('missing_address_count'),
      `${path}.missing_address_count`,
    ),
    estimated_cost_cents: nonNegativeInteger(
      read('estimated_cost_cents'),
      `${path}.estimated_cost_cents`,
    ),
    currency: enumValue(read('currency'), ['USD'], `${path}.currency`),
    version: positiveInteger(read('version'), `${path}.version`),
    created_at: rfc3339Value(read('created_at'), `${path}.created_at`),
    updated_at: rfc3339Value(read('updated_at'), `${path}.updated_at`),
  };
}

export const decodeCardCampaignListItem: Decoder<CardCampaignListItem> = (
  input,
  path = 'response',
) => decodeListItemReader(exactObject(input, listItemKeys, path), path);

function decodeRecipient(input: unknown, path: string): CardRecipient {
  const read = exactObject(input, [
    'id',
    'contact_id',
    'display_name',
    'celebration_kind',
    'celebration_month',
    'celebration_day',
    'celebration_year',
    'celebration_year_quality',
    'celebration_origin',
    'message',
    'design_key',
    'address_status',
    'address_summary',
    'excluded',
    'exclusion_reason',
    'delivery_outcome',
  ], path);
  const rawYear = read('celebration_year');
  return {
    id: uuidValue(read('id'), `${path}.id`),
    contact_id: positiveInteger(read('contact_id'), `${path}.contact_id`),
    display_name: stringValue(read('display_name'), `${path}.display_name`, 1, 255),
    celebration_kind: enumValue(
      read('celebration_kind'),
      ['birthday', 'home_anniversary'],
      `${path}.celebration_kind`,
    ),
    celebration_month: monthValue(read('celebration_month'), `${path}.celebration_month`),
    celebration_day: dayValue(read('celebration_day'), `${path}.celebration_day`),
    celebration_year: rawYear === null
      ? null
      : safeInteger(rawYear, `${path}.celebration_year`, -9999, 9999),
    celebration_year_quality: enumValue(
      read('celebration_year_quality'),
      ['verified', 'yearless', 'sentinel', 'unknown'],
      `${path}.celebration_year_quality`,
    ),
    celebration_origin: enumValue(
      read('celebration_origin'),
      ['internal_crm', 'recovered'],
      `${path}.celebration_origin`,
    ),
    message: stringValue(read('message'), `${path}.message`, 1, 2000),
    design_key: designKeyValue(read('design_key'), `${path}.design_key`),
    address_status: enumValue(
      read('address_status'),
      ['ready', 'missing'],
      `${path}.address_status`,
    ),
    address_summary: nullableString(read('address_summary'), `${path}.address_summary`, 1, 1000),
    excluded: booleanValue(read('excluded'), `${path}.excluded`),
    exclusion_reason: nullableString(
      read('exclusion_reason'),
      `${path}.exclusion_reason`,
      1,
      500,
    ),
    delivery_outcome: read('delivery_outcome') === null
      ? null
      : enumValue(
        read('delivery_outcome'),
        ['confirmed', 'rejected', 'ambiguous'] as const,
        `${path}.delivery_outcome`,
      ),
  };
}

const detailKeys = [
  ...listItemKeys,
  'request_id',
  'include_birthdays',
  'include_home_anniversaries',
  'audience_ref',
  'audience_checksum',
  'birthday_recipients',
  'home_anniversary_recipients',
  'excluded_recipients',
  'provider_connected',
  'provider_connection_reason',
  'approved_by_actor',
  'approved_at',
  'send_request_id',
  'recipients',
] as const;

export const decodeCardCampaignDetail: Decoder<CardCampaignDetail> = (
  input,
  path = 'response',
) => {
  const read = exactObject(input, detailKeys, path);
  const rawRecipients = read('recipients');
  if (!Array.isArray(rawRecipients) || rawRecipients.length > 500) {
    return invalid(`${path}.recipients`, 'array with at most 500 recipients');
  }
  const checksum = stringValue(read('audience_checksum'), `${path}.audience_checksum`, 64, 64);
  if (!SHA256_PATTERN.test(checksum)) {
    return invalid(`${path}.audience_checksum`, 'lowercase SHA-256 hash');
  }
  return {
    ...decodeListItemReader(read, path),
    request_id: uuidValue(read('request_id'), `${path}.request_id`),
    include_birthdays: booleanValue(read('include_birthdays'), `${path}.include_birthdays`),
    include_home_anniversaries: booleanValue(
      read('include_home_anniversaries'),
      `${path}.include_home_anniversaries`,
    ),
    audience_ref: uuidValue(read('audience_ref'), `${path}.audience_ref`),
    audience_checksum: checksum,
    birthday_recipients: nonNegativeInteger(
      read('birthday_recipients'),
      `${path}.birthday_recipients`,
    ),
    home_anniversary_recipients: nonNegativeInteger(
      read('home_anniversary_recipients'),
      `${path}.home_anniversary_recipients`,
    ),
    excluded_recipients: nonNegativeInteger(
      read('excluded_recipients'),
      `${path}.excluded_recipients`,
    ),
    provider_connected: booleanValue(read('provider_connected'), `${path}.provider_connected`),
    provider_connection_reason: nullableString(
      read('provider_connection_reason'),
      `${path}.provider_connection_reason`,
      1,
      255,
    ),
    approved_by_actor: nullableString(
      read('approved_by_actor'),
      `${path}.approved_by_actor`,
      1,
      255,
    ),
    approved_at: nullableRfc3339(read('approved_at'), `${path}.approved_at`),
    send_request_id: nullableUuid(read('send_request_id'), `${path}.send_request_id`),
    recipients: rawRecipients.map((recipient, index) =>
      decodeRecipient(recipient, `${path}.recipients[${index}]`)),
  };
};

export const decodeCardCampaignPage: Decoder<CardCampaignPage> = (
  input,
  path = 'response',
) => {
  const read = exactObject(input, ['campaigns', 'total'], path);
  const rawCampaigns = read('campaigns');
  if (!Array.isArray(rawCampaigns) || rawCampaigns.length > 50) {
    return invalid(`${path}.campaigns`, 'array with at most 50 campaigns');
  }
  return {
    campaigns: rawCampaigns.map((campaign, index) =>
      decodeCardCampaignListItem(campaign, `${path}.campaigns[${index}]`)),
    total: nonNegativeInteger(read('total'), `${path}.total`),
  };
};

function validateUuid(value: string, path: string): string {
  return uuidValue(value, path);
}

function validateDraft(payload: CardCampaignDraftRequest): CardCampaignDraftRequest {
  validateUuid(payload.request_id, 'request.request_id');
  monthValue(payload.month, 'request.month');
  booleanValue(payload.include_birthdays, 'request.include_birthdays');
  booleanValue(payload.include_home_anniversaries, 'request.include_home_anniversaries');
  if (!payload.include_birthdays && !payload.include_home_anniversaries) {
    return invalid('request', 'at least one celebration kind selected');
  }
  if (payload.title !== undefined) stringValue(payload.title, 'request.title', 1, 255);
  if (payload.birthday_message_template !== undefined) {
    const value = stringValue(
      payload.birthday_message_template,
      'request.birthday_message_template',
      1,
      2000,
    );
    if (payload.include_birthdays && !value.includes('{first_name}')) {
      return invalid('request.birthday_message_template', 'message containing {first_name}');
    }
  }
  if (payload.home_anniversary_message_template !== undefined) {
    const value = stringValue(
      payload.home_anniversary_message_template,
      'request.home_anniversary_message_template',
      1,
      2000,
    );
    if (payload.include_home_anniversaries && !value.includes('{first_name}')) {
      return invalid('request.home_anniversary_message_template', 'message containing {first_name}');
    }
  }
  if (payload.birthday_design_key !== undefined) {
    designKeyValue(payload.birthday_design_key, 'request.birthday_design_key');
  }
  if (payload.home_anniversary_design_key !== undefined) {
    designKeyValue(payload.home_anniversary_design_key, 'request.home_anniversary_design_key');
  }
  return payload;
}

function validateUpdate(payload: CardCampaignUpdateRequest): CardCampaignUpdateRequest {
  positiveInteger(payload.expected_version, 'request.expected_version');
  if (payload.refresh_missing_addresses !== undefined) {
    booleanValue(payload.refresh_missing_addresses, 'request.refresh_missing_addresses');
  }
  const updates = payload.recipient_updates ?? [];
  if (updates.length > 500) return invalid('request.recipient_updates', 'array at most 500');
  const hasTopLevelChange = [
    payload.title,
    payload.birthday_message_template,
    payload.home_anniversary_message_template,
    payload.birthday_design_key,
    payload.home_anniversary_design_key,
  ].some((value) => value !== undefined);
  if (!hasTopLevelChange && updates.length === 0 && payload.refresh_missing_addresses !== true) {
    return invalid('request', 'campaign change');
  }
  if (payload.title !== undefined) stringValue(payload.title, 'request.title', 1, 255);
  if (payload.birthday_message_template !== undefined) {
    stringValue(payload.birthday_message_template, 'request.birthday_message_template', 1, 2000);
  }
  if (payload.home_anniversary_message_template !== undefined) {
    stringValue(
      payload.home_anniversary_message_template,
      'request.home_anniversary_message_template',
      1,
      2000,
    );
  }
  if (payload.birthday_design_key !== undefined) {
    designKeyValue(payload.birthday_design_key, 'request.birthday_design_key');
  }
  if (payload.home_anniversary_design_key !== undefined) {
    designKeyValue(payload.home_anniversary_design_key, 'request.home_anniversary_design_key');
  }
  const ids = updates.map((update, index) => {
    const path = `request.recipient_updates[${index}]`;
    const id = validateUuid(update.recipient_id, `${path}.recipient_id`);
    const fields = [update.message, update.design_key, update.excluded, update.exclusion_reason];
    if (fields.every((value) => value === undefined)) return invalid(path, 'recipient change');
    if (update.message !== undefined) stringValue(update.message, `${path}.message`, 1, 2000);
    if (update.design_key !== undefined) designKeyValue(update.design_key, `${path}.design_key`);
    if (update.excluded !== undefined) booleanValue(update.excluded, `${path}.excluded`);
    if (update.exclusion_reason !== undefined) {
      stringValue(update.exclusion_reason, `${path}.exclusion_reason`, 1, 500);
      if (update.excluded !== true) {
        return invalid(`${path}.exclusion_reason`, 'reason with excluded=true');
      }
    }
    if (update.excluded === true && update.exclusion_reason === undefined) {
      return invalid(`${path}.exclusion_reason`, 'reason for excluded recipient');
    }
    return id;
  });
  if (new Set(ids).size !== ids.length) {
    return invalid('request.recipient_updates', 'unique recipient IDs');
  }
  return payload;
}

function validateApproval(payload: CardCampaignApproveRequest): CardCampaignApproveRequest {
  validateUuid(payload.request_id, 'request.request_id');
  positiveInteger(payload.expected_version, 'request.expected_version');
  nonNegativeInteger(payload.confirmed_recipient_count, 'request.confirmed_recipient_count');
  nonNegativeInteger(payload.confirmed_cost_cents, 'request.confirmed_cost_cents');
  if (payload.confirmed_by_brandon !== true) {
    return invalid('request.confirmed_by_brandon', 'true');
  }
  return payload;
}

function campaignPath(campaignId: string, suffix = ''): string {
  return `/cards/campaigns/${validateUuid(campaignId, 'request.campaign_id')}${suffix}`;
}

export const cardsApi = Object.freeze({
  list: (
    options: Readonly<{ limit?: number; offset?: number; signal?: AbortSignal }> = {},
  ): Promise<CardCampaignPage> => {
    const limit = safeInteger(options.limit ?? 25, 'request.limit', 1, 50);
    const offset = safeInteger(options.offset ?? 0, 'request.offset', 0, DATABASE_INTEGER_MAX);
    return commandJson({
      path: `/cards/campaigns?${new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      }).toString()}`,
      decode: decodeCardCampaignPage,
      signal: options.signal,
    });
  },
  createDraft: (payload: CardCampaignDraftRequest): Promise<CardCampaignDetail> =>
    commandJson({
      path: '/cards/campaigns/drafts',
      method: 'POST',
      body: validateDraft(payload),
      decode: decodeCardCampaignDetail,
    }),
  get: (campaignId: string, signal?: AbortSignal): Promise<CardCampaignDetail> =>
    commandJson({
      path: campaignPath(campaignId),
      decode: decodeCardCampaignDetail,
      signal,
    }),
  update: (
    campaignId: string,
    payload: CardCampaignUpdateRequest,
  ): Promise<CardCampaignDetail> =>
    commandJson({
      path: campaignPath(campaignId),
      method: 'PATCH',
      body: validateUpdate(payload),
      decode: decodeCardCampaignDetail,
    }),
  approveAndSend: (
    campaignId: string,
    payload: CardCampaignApproveRequest,
  ): Promise<CardCampaignDetail> =>
    commandJson({
      path: campaignPath(campaignId, '/approve-and-send'),
      method: 'POST',
      body: validateApproval(payload),
      decode: decodeCardCampaignDetail,
    }),
});

export type CardsApi = typeof cardsApi;

export function isCardCampaignConflict(error: unknown): boolean {
  return error instanceof Error
    && 'status' in error
    && Reflect.get(error, 'status') === 409;
}
