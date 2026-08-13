import { commandJson, CommandDecodeError, type Decoder } from './http';

export type ContactCaptureQuality = 'complete' | 'partial' | 'shell' | 'error';
export type ContactEvidenceQuality = 'complete' | 'partial' | 'limitation';
export type ContactSectionName =
  | 'timeline'
  | 'opportunities'
  | 'smart_plans'
  | 'notes'
  | 'saved_searches'
  | 'tasks_to_do'
  | 'tasks_completed'
  | 'tasks_archived';
export type ContactOrigin = 'recovered' | 'lead_backed' | 'legacy_only' | 'internal_only';
export type ContactSource = 'kw_command' | 'internal_crm' | 'legacy_lead';
export type ContactSmartView =
  | 'all'
  | 'never_contacted'
  | 'recently_active'
  | 'birthdays_this_month'
  | 'anniversaries_this_month';
export type ContactSortKey =
  | 'name'
  | 'stage'
  | 'health_score'
  | 'last_contacted_at'
  | 'last_interaction_at'
  | 'created_at'
  | 'updated_at';
export type SortDirection = 'asc' | 'desc';

export type ContactActor = Readonly<{
  role: 'owner' | 'assignee' | 'collaborator';
  provider_actor_id: string | null;
  display_name: string | null;
}>;

export type ContactTag = Readonly<{ id: number; name: string }>;

export type ContactCelebrationValue = Readonly<{
  month: number;
  day: number;
  year: number | null;
  year_quality: 'verified' | 'yearless' | 'sentinel' | 'unknown';
  origin: 'internal_crm' | 'recovered';
}>;

export type ContactAddress = Readonly<{
  id: number;
  address_type: string | null;
  formatted: string | null;
  latitude: string | null;
  longitude: string | null;
  source_record_id: number | null;
}>;

export type ContactDirectoryRow = Readonly<{
  id: number;
  first_name: string;
  last_name: string;
  display_name: string;
  primary_email: string | null;
  primary_phone: string | null;
  stage: string;
  lead_backed: boolean;
  origins: readonly ContactOrigin[];
  sources: readonly ContactSource[];
  health_score: number | null;
  last_contacted_at: string | null;
  last_interaction_at: string | null;
  owner: ContactActor | null;
  assignee: ContactActor | null;
  tags: readonly ContactTag[];
  birthday: ContactCelebrationValue | null;
  anniversary: ContactCelebrationValue | null;
  evidence_quality: ContactEvidenceQuality | null;
}>;

export type ContactDirectoryPage = Readonly<{
  rows: readonly ContactDirectoryRow[];
  total: number;
  page: number;
  page_size: number;
  page_count: number;
  sort: ContactSortKey;
  direction: SortDirection;
}>;

export type ContactRecoveredProfile = Readonly<{
  legal_name: string | null;
  preferred_name: string | null;
  description: string | null;
  company: string | null;
  title: string | null;
  lead_source: string | null;
  account_name: string | null;
  birthday: ContactCelebrationValue | null;
  anniversary: ContactCelebrationValue | null;
}>;

export type ContactDetail = Readonly<{
  contact: ContactDirectoryRow;
  lead_id: number | null;
  recovered_profile: ContactRecoveredProfile | null;
  addresses: readonly ContactAddress[];
  ownership: readonly ContactActor[];
  tags: readonly ContactTag[];
}>;

export type ContactNeighbors = Readonly<{
  previous_contact_id: number | null;
  next_contact_id: number | null;
}>;

export type ContactWorkspaceSummary = Readonly<{
  open_tasks: number;
  completed_tasks: number;
  archived_tasks: number;
  active_smart_plans: number;
  opportunities: number;
  notes: number;
  saved_searches: number;
  bookings: number;
}>;

export type ContactOccurrence =
  | Readonly<{ kind: 'opportunity'; title: string; stage: string | null; value_cents: number | null }>
  | Readonly<{ kind: 'smart_plan'; title: string; status: string | null }>
  | Readonly<{
      kind: 'task';
      title: string;
      description: string | null;
      state: 'to_do' | 'completed' | 'archived';
      due_at: string | null;
    }>
  | Readonly<{ kind: 'note'; title: string; body: string | null }>
  | Readonly<{ kind: 'saved_search'; title: string; criteria_summary: readonly string[] }>;

type ContactMaterializationCommon = Readonly<{
  source_record_id: number;
  source_key_hash: string;
  section: ContactSectionName;
  occurrence_ordinal: number;
  capture_quality: ContactCaptureQuality;
  captured_at: string | null;
  value: ContactOccurrence;
}>;

export type ContactMaterialization =
  | (ContactMaterializationCommon & Readonly<{ status: 'source_only' }>)
  | (ContactMaterializationCommon & Readonly<{
      status: 'materialized';
      entity_type: 'note' | 'saved_search' | 'task' | 'smart_plan' | 'opportunity';
      entity_id: number;
    }>);

export type ContactSectionPage = Readonly<{
  rows: readonly ContactMaterialization[];
  total: number;
  page: number;
  page_size: number;
  page_count: number;
}>;

export type ContactTimelineEntry = Readonly<{
  key: string;
  origin: 'recovered' | 'internal_crm' | 'legacy_lead' | 'booking';
  kind: string;
  title: string;
  body: string | null;
  outcome: string | null;
  occurred_at: string | null;
  source_record_id: number | null;
  entity_type: string;
  entity_id: number;
}>;

export type ContactTimelinePage = Readonly<{
  rows: readonly ContactTimelineEntry[];
  next_cursor: string | null;
  has_more: boolean;
}>;

export type ContactArtifactMetadata = Readonly<{
  artifact_id: number;
  artifact_type: string;
  sha256: string;
  size_bytes: number;
  content_href: string;
}>;

export type ContactSourceMetadata = Readonly<{
  source_record_id: number;
  record_kind: string;
  evidence_level: 'observed_record' | 'rendered_occurrence' | 'displayed_aggregate';
  capture_quality: ContactCaptureQuality;
  captured_at: string | null;
  artifacts: readonly ContactArtifactMetadata[];
}>;

export type ContactSectionEvidence = Readonly<{
  capture_position_id: number;
  section: ContactSectionName;
  source_record_id: number;
  capture_quality: ContactCaptureQuality;
  row_count: number;
  is_empty: boolean;
  limitation_codes: readonly string[];
}>;

export type ContactCapturePosition = Readonly<{
  capture_position_id: number;
  capture_ordinal: number;
  source_record_id: number;
  capture_quality: ContactCaptureQuality;
  sections: readonly ContactSectionEvidence[];
}>;

export type ContactEvidence = Readonly<{
  contact_id: number;
  provider_contact_rows: number;
  resolved_provider_identities: number;
  coalesced_aliases: 0;
  lead_backed_contacts: number;
  reviewed_overlaps: number;
  legacy_only_contacts: number;
  capture_positions: readonly ContactCapturePosition[];
  section_matrix: readonly ContactSectionEvidence[];
  sources: readonly ContactSourceMetadata[];
  capture_quality: ContactEvidenceQuality;
}>;

export type ContactCelebrationRow = Readonly<{
  contact_id: number;
  display_name: string;
  kind: 'birthday' | 'anniversary';
  month: number;
  day: number;
  year: number | null;
  year_quality: 'verified' | 'yearless' | 'sentinel' | 'unknown';
  origin: 'internal_crm' | 'recovered';
}>;

export type ContactCelebrations = Readonly<{
  birthdays: readonly ContactCelebrationRow[];
  anniversaries: readonly ContactCelebrationRow[];
}>;

export type LegacyContact = Readonly<{
  id: number;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  lead_id: number | null;
  birthday: string | null;
  anniversary: string | null;
  stage: string;
}>;

export type ContactCreated = LegacyContact;

export type ContactCreateInput = Readonly<{
  first_name: string;
  last_name?: string;
  email?: string | null;
  phone?: string | null;
  stage?: string;
  birthday?: string | null;
  anniversary?: string | null;
}>;

export type ContactUpdateInput = Readonly<{
  first_name?: string;
  last_name?: string;
  email?: string | null;
  phone?: string | null;
  stage?: string;
  birthday?: string | null;
  anniversary?: string | null;
}>;

export type ContactBulkInput = Readonly<{
  contact_ids: readonly number[];
  action:
    | Readonly<{ action: 'set_stage'; stage: string }>
    | Readonly<{ action: 'add_tag'; tag_id: number }>
    | Readonly<{ action: 'remove_tag'; tag_id: number }>;
}>;

export type ContactBulkResult = Readonly<{
  requested_contact_ids: readonly number[];
  actioned_contact_ids: readonly number[];
  action: 'set_stage' | 'add_tag' | 'remove_tag';
}>;

export type ContactDirectoryRequest = Readonly<{
  query?: string;
  stage?: string;
  owner_actor_id?: string;
  assignee_actor_id?: string;
  tag?: readonly number[];
  source?: readonly ContactSource[];
  origin?: readonly ContactOrigin[];
  health_min?: number;
  health_max?: number;
  birthday_month?: number;
  anniversary_month?: number;
  smart_view?: ContactSmartView;
  sort?: ContactSortKey;
  direction?: SortDirection;
  page?: number;
  page_size?: number;
}>;

type Reader = (key: string) => unknown;

function invalid(path: string, expected: string): never {
  throw new CommandDecodeError(path, expected);
}

function objectReader(input: unknown, keys: readonly string[], path: string): Reader {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) {
    return invalid(path, 'object');
  }
  const actual = Object.keys(input);
  if (actual.length !== keys.length || actual.some((key) => !keys.includes(key))) {
    return invalid(path, `object with exactly ${keys.join(', ')}`);
  }
  return (key: string): unknown => Reflect.get(input, key);
}

function stringValue(input: unknown, path: string, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): string {
  if (typeof input !== 'string') {
    return invalid(path, `string length ${minimum}..${maximum}`);
  }
  let length = 0;
  for (const character of input) length += character.length > 0 ? 1 : 0;
  if (length < minimum || length > maximum) {
    return invalid(path, `string length ${minimum}..${maximum}`);
  }
  return input;
}

function nullableString(input: unknown, path: string): string | null {
  return input === null ? null : stringValue(input, path);
}

function booleanValue(input: unknown, path: string): boolean {
  if (typeof input !== 'boolean') return invalid(path, 'boolean');
  return input;
}

function integer(input: unknown, path: string, minimum: number, maximum = Number.MAX_SAFE_INTEGER): number {
  if (
    typeof input !== 'number'
    || !Number.isSafeInteger(input)
    || input < minimum
    || input > maximum
  ) {
    return invalid(path, `safe integer ${minimum}..${maximum}`);
  }
  return input;
}

function positiveInteger(input: unknown, path: string): number {
  return integer(input, path, 1);
}

function nonnegativeInteger(input: unknown, path: string): number {
  return integer(input, path, 0);
}

function nullablePositiveInteger(input: unknown, path: string): number | null {
  return input === null ? null : positiveInteger(input, path);
}

function enumValue<T extends string>(
  input: unknown,
  values: readonly T[],
  path: string,
): T {
  if (typeof input !== 'string') return invalid(path, values.join('|'));
  const match = values.find((value) => value === input);
  if (match === undefined) return invalid(path, values.join('|'));
  return match;
}

function arrayValue<T>(input: unknown, path: string, decoder: (value: unknown, path: string) => T): readonly T[] {
  if (!Array.isArray(input)) return invalid(path, 'array');
  const decoded: T[] = [];
  for (let index = 0; index < input.length; index += 1) {
    if (!Object.prototype.hasOwnProperty.call(input, index)) {
      return invalid(`${path}[${index}]`, 'present array element');
    }
    decoded.push(decoder(input[index], `${path}[${index}]`));
  }
  return decoded;
}

const CAPTURE_QUALITIES: readonly ContactCaptureQuality[] = ['complete', 'partial', 'shell', 'error'];
const EVIDENCE_QUALITIES: readonly ContactEvidenceQuality[] = ['complete', 'partial', 'limitation'];
const SECTION_NAMES: readonly ContactSectionName[] = [
  'timeline', 'opportunities', 'smart_plans', 'notes', 'saved_searches',
  'tasks_to_do', 'tasks_completed', 'tasks_archived',
];
const ORIGINS: readonly ContactOrigin[] = ['recovered', 'lead_backed', 'legacy_only', 'internal_only'];
const SOURCES: readonly ContactSource[] = ['kw_command', 'internal_crm', 'legacy_lead'];
const SMART_VIEWS: readonly ContactSmartView[] = [
  'all', 'never_contacted', 'recently_active', 'birthdays_this_month', 'anniversaries_this_month',
];
const SORT_KEYS: readonly ContactSortKey[] = [
  'name', 'stage', 'health_score', 'last_contacted_at', 'last_interaction_at', 'created_at', 'updated_at',
];
const DIRECTIONS: readonly SortDirection[] = ['asc', 'desc'];

function daysInMonth(year: number, month: number): number {
  if (month === 2) {
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    return leap ? 29 : 28;
  }
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

function exactDate(input: unknown, path: string): string {
  if (typeof input !== 'string') return invalid(path, 'YYYY-MM-DD');
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(input);
  if (match === null) return invalid(path, 'YYYY-MM-DD');
  const year = parseInt(match[1] ?? '', 10);
  const month = parseInt(match[2] ?? '', 10);
  const day = parseInt(match[3] ?? '', 10);
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) {
    return invalid(path, 'valid calendar date');
  }
  return input;
}

function nullableDate(input: unknown, path: string): string | null {
  return input === null ? null : exactDate(input, path);
}

function rfc3339(input: unknown, path: string): string {
  if (typeof input !== 'string') return invalid(path, 'RFC3339 datetime');
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(input);
  if (match === null) return invalid(path, 'RFC3339 datetime');
  const year = parseInt(match[1] ?? '', 10);
  const month = parseInt(match[2] ?? '', 10);
  const day = parseInt(match[3] ?? '', 10);
  const hour = parseInt(match[4] ?? '', 10);
  const minute = parseInt(match[5] ?? '', 10);
  const second = parseInt(match[6] ?? '', 10);
  const offsetHour = match[8] === undefined ? 0 : parseInt(match[8], 10);
  const offsetMinute = match[9] === undefined ? 0 : parseInt(match[9], 10);
  if (
    year < 1 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)
    || hour > 23 || minute > 59 || second > 59 || offsetHour > 23 || offsetMinute > 59
  ) {
    return invalid(path, 'valid RFC3339 datetime');
  }
  return input;
}

function nullableRfc3339(input: unknown, path: string): string | null {
  return input === null ? null : rfc3339(input, path);
}

function parseBoundedExponent(text: string): number | null {
  let index = 0;
  let sign = 1;
  if (text.startsWith('+')) index = 1;
  else if (text.startsWith('-')) { index = 1; sign = -1; }
  const rawDigits = text.slice(index);
  if (rawDigits.length === 0) return null;
  const digits = rawDigits.replace(/^0+/, '') || '0';
  if (digits.length > 6) return null;
  let value = 0;
  for (const character of digits) {
    const code = character.charCodeAt(0) - 48;
    if (code < 0 || code > 9) return null;
    value = value * 10 + code;
  }
  return sign * value;
}

function coordinate(input: unknown, path: string, maximum: number): string | null {
  if (input === null) return null;
  if (typeof input !== 'string' || input.length === 0 || input.trim() !== input || input.length > 100_000) {
    return invalid(path, 'exact decimal string');
  }
  const match = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(input);
  if (match === null) return invalid(path, 'exact decimal string');
  const sign = match[1] === '-' ? -1 : 1;
  const whole = match[2] ?? '0';
  const fraction = match[3] ?? match[4] ?? '';
  const digits = `${whole}${fraction}`;
  const zero = /^0+$/.test(digits);
  const exponentText = match[5] ?? '0';
  const exponent = parseBoundedExponent(exponentText);
  if (exponent === null) {
    if (zero) return input;
    return invalid(path, 'bounded exact decimal exponent');
  }
  let scale = exponent - fraction.length + 7;
  let scaledDigits = digits.replace(/^0+/, '');
  if (scaledDigits.length === 0) return input;
  if (scale >= 0) {
    if (scale > 12 || scaledDigits.length + scale > 11) {
      return invalid(path, 'Numeric(10,7) coordinate');
    }
    scaledDigits += '0'.repeat(scale);
  } else {
    const remove = -scale;
    if (remove > scaledDigits.length) return invalid(path, 'scale no greater than seven');
    const discarded = scaledDigits.slice(scaledDigits.length - remove);
    if (!/^0+$/.test(discarded)) return invalid(path, 'scale no greater than seven');
    scaledDigits = scaledDigits.slice(0, scaledDigits.length - remove);
    if (scaledDigits.length === 0) scaledDigits = '0';
    scale = 0;
  }
  const scaled = BigInt(scaledDigits) * BigInt(sign);
  const bound = BigInt(maximum) * BigInt(10_000_000);
  if (scaled < -bound || scaled > bound) return invalid(path, `coordinate within ${maximum}`);
  return input;
}

function actorValue(input: unknown, path: string): ContactActor {
  const read = objectReader(input, ['role', 'provider_actor_id', 'display_name'], path);
  return {
    role: enumValue(read('role'), ['owner', 'assignee', 'collaborator'], `${path}.role`),
    provider_actor_id: nullableString(read('provider_actor_id'), `${path}.provider_actor_id`),
    display_name: nullableString(read('display_name'), `${path}.display_name`),
  };
}

function nullableActor(input: unknown, path: string): ContactActor | null {
  return input === null ? null : actorValue(input, path);
}

function tagValue(input: unknown, path: string): ContactTag {
  const read = objectReader(input, ['id', 'name'], path);
  return { id: positiveInteger(read('id'), `${path}.id`), name: stringValue(read('name'), `${path}.name`) };
}

function celebrationValue(input: unknown, path: string): ContactCelebrationValue {
  const read = objectReader(input, ['month', 'day', 'year', 'year_quality', 'origin'], path);
  const month = integer(read('month'), `${path}.month`, 1, 12);
  const day = integer(read('day'), `${path}.day`, 1, 31);
  const rawYear = read('year');
  const year = rawYear === null
    ? null
    : integer(rawYear, `${path}.year`, Number.MIN_SAFE_INTEGER, Number.MAX_SAFE_INTEGER);
  return {
    month,
    day,
    year,
    year_quality: enumValue(read('year_quality'), ['verified', 'yearless', 'sentinel', 'unknown'], `${path}.year_quality`),
    origin: enumValue(read('origin'), ['internal_crm', 'recovered'], `${path}.origin`),
  };
}

function nullableCelebration(input: unknown, path: string): ContactCelebrationValue | null {
  return input === null ? null : celebrationValue(input, path);
}

function directoryRowValue(input: unknown, path: string): ContactDirectoryRow {
  const keys = [
    'id', 'first_name', 'last_name', 'display_name', 'primary_email', 'primary_phone', 'stage',
    'lead_backed', 'origins', 'sources', 'health_score', 'last_contacted_at', 'last_interaction_at',
    'owner', 'assignee', 'tags', 'birthday', 'anniversary', 'evidence_quality',
  ];
  const read = objectReader(input, keys, path);
  const rawHealth = read('health_score');
  const rawQuality = read('evidence_quality');
  return {
    id: positiveInteger(read('id'), `${path}.id`),
    first_name: stringValue(read('first_name'), `${path}.first_name`),
    last_name: stringValue(read('last_name'), `${path}.last_name`),
    display_name: stringValue(read('display_name'), `${path}.display_name`),
    primary_email: nullableString(read('primary_email'), `${path}.primary_email`),
    primary_phone: nullableString(read('primary_phone'), `${path}.primary_phone`),
    stage: stringValue(read('stage'), `${path}.stage`),
    lead_backed: booleanValue(read('lead_backed'), `${path}.lead_backed`),
    origins: arrayValue(read('origins'), `${path}.origins`, (value, itemPath) => enumValue(value, ORIGINS, itemPath)),
    sources: arrayValue(read('sources'), `${path}.sources`, (value, itemPath) => enumValue(value, SOURCES, itemPath)),
    health_score: rawHealth === null ? null : integer(rawHealth, `${path}.health_score`, 0, 100),
    last_contacted_at: nullableRfc3339(read('last_contacted_at'), `${path}.last_contacted_at`),
    last_interaction_at: nullableRfc3339(read('last_interaction_at'), `${path}.last_interaction_at`),
    owner: nullableActor(read('owner'), `${path}.owner`),
    assignee: nullableActor(read('assignee'), `${path}.assignee`),
    tags: arrayValue(read('tags'), `${path}.tags`, tagValue),
    birthday: nullableCelebration(read('birthday'), `${path}.birthday`),
    anniversary: nullableCelebration(read('anniversary'), `${path}.anniversary`),
    evidence_quality: rawQuality === null ? null : enumValue(rawQuality, EVIDENCE_QUALITIES, `${path}.evidence_quality`),
  };
}

export const decodeContactDirectoryPage: Decoder<ContactDirectoryPage> = (
  input,
  path = 'response',
) => {
  const read = objectReader(input, ['rows', 'total', 'page', 'page_size', 'page_count', 'sort', 'direction'], path);
  return {
    rows: arrayValue(read('rows'), `${path}.rows`, directoryRowValue),
    total: nonnegativeInteger(read('total'), `${path}.total`),
    page: positiveInteger(read('page'), `${path}.page`),
    page_size: integer(read('page_size'), `${path}.page_size`, 1, 100),
    page_count: nonnegativeInteger(read('page_count'), `${path}.page_count`),
    sort: enumValue(read('sort'), SORT_KEYS, `${path}.sort`),
    direction: enumValue(read('direction'), DIRECTIONS, `${path}.direction`),
  };
};

function recoveredProfileValue(input: unknown, path: string): ContactRecoveredProfile {
  const keys = [
    'legal_name', 'preferred_name', 'description', 'company', 'title', 'lead_source', 'account_name',
    'birthday', 'anniversary',
  ];
  const read = objectReader(input, keys, path);
  return {
    legal_name: nullableString(read('legal_name'), `${path}.legal_name`),
    preferred_name: nullableString(read('preferred_name'), `${path}.preferred_name`),
    description: nullableString(read('description'), `${path}.description`),
    company: nullableString(read('company'), `${path}.company`),
    title: nullableString(read('title'), `${path}.title`),
    lead_source: nullableString(read('lead_source'), `${path}.lead_source`),
    account_name: nullableString(read('account_name'), `${path}.account_name`),
    birthday: nullableCelebration(read('birthday'), `${path}.birthday`),
    anniversary: nullableCelebration(read('anniversary'), `${path}.anniversary`),
  };
}

function addressValue(input: unknown, path: string): ContactAddress {
  const read = objectReader(
    input,
    ['id', 'address_type', 'formatted', 'latitude', 'longitude', 'source_record_id'],
    path,
  );
  return {
    id: positiveInteger(read('id'), `${path}.id`),
    address_type: nullableString(read('address_type'), `${path}.address_type`),
    formatted: nullableString(read('formatted'), `${path}.formatted`),
    latitude: coordinate(read('latitude'), `${path}.latitude`, 90),
    longitude: coordinate(read('longitude'), `${path}.longitude`, 180),
    source_record_id: nullablePositiveInteger(read('source_record_id'), `${path}.source_record_id`),
  };
}

export const decodeContactDetail: Decoder<ContactDetail> = (input, path = 'response') => {
  const read = objectReader(input, ['contact', 'lead_id', 'recovered_profile', 'addresses', 'ownership', 'tags'], path);
  const rawProfile = read('recovered_profile');
  return {
    contact: directoryRowValue(read('contact'), `${path}.contact`),
    lead_id: nullablePositiveInteger(read('lead_id'), `${path}.lead_id`),
    recovered_profile: rawProfile === null ? null : recoveredProfileValue(rawProfile, `${path}.recovered_profile`),
    addresses: arrayValue(read('addresses'), `${path}.addresses`, addressValue),
    ownership: arrayValue(read('ownership'), `${path}.ownership`, actorValue),
    tags: arrayValue(read('tags'), `${path}.tags`, tagValue),
  };
};

export const decodeContactNeighbors: Decoder<ContactNeighbors> = (input, path = 'response') => {
  const read = objectReader(input, ['previous_contact_id', 'next_contact_id'], path);
  return {
    previous_contact_id: nullablePositiveInteger(read('previous_contact_id'), `${path}.previous_contact_id`),
    next_contact_id: nullablePositiveInteger(read('next_contact_id'), `${path}.next_contact_id`),
  };
};

export const decodeContactWorkspaceSummary: Decoder<ContactWorkspaceSummary> = (input, path = 'response') => {
  const keys = [
    'open_tasks', 'completed_tasks', 'archived_tasks', 'active_smart_plans',
    'opportunities', 'notes', 'saved_searches', 'bookings',
  ];
  const read = objectReader(input, keys, path);
  return {
    open_tasks: nonnegativeInteger(read('open_tasks'), `${path}.open_tasks`),
    completed_tasks: nonnegativeInteger(read('completed_tasks'), `${path}.completed_tasks`),
    archived_tasks: nonnegativeInteger(read('archived_tasks'), `${path}.archived_tasks`),
    active_smart_plans: nonnegativeInteger(read('active_smart_plans'), `${path}.active_smart_plans`),
    opportunities: nonnegativeInteger(read('opportunities'), `${path}.opportunities`),
    notes: nonnegativeInteger(read('notes'), `${path}.notes`),
    saved_searches: nonnegativeInteger(read('saved_searches'), `${path}.saved_searches`),
    bookings: nonnegativeInteger(read('bookings'), `${path}.bookings`),
  };
};

function occurrenceValue(input: unknown, path: string): ContactOccurrence {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) return invalid(path, 'occurrence object');
  const kind = enumValue(
    Reflect.get(input, 'kind'),
    ['opportunity', 'smart_plan', 'task', 'note', 'saved_search'],
    `${path}.kind`,
  );
  if (kind === 'opportunity') {
    const read = objectReader(input, ['kind', 'title', 'stage', 'value_cents'], path);
    const rawValue = read('value_cents');
    return {
      kind,
      title: stringValue(read('title'), `${path}.title`),
      stage: nullableString(read('stage'), `${path}.stage`),
      value_cents: rawValue === null ? null : nonnegativeInteger(rawValue, `${path}.value_cents`),
    };
  }
  if (kind === 'smart_plan') {
    const read = objectReader(input, ['kind', 'title', 'status'], path);
    return { kind, title: stringValue(read('title'), `${path}.title`), status: nullableString(read('status'), `${path}.status`) };
  }
  if (kind === 'task') {
    const read = objectReader(input, ['kind', 'title', 'description', 'state', 'due_at'], path);
    return {
      kind,
      title: stringValue(read('title'), `${path}.title`),
      description: nullableString(read('description'), `${path}.description`),
      state: enumValue(read('state'), ['to_do', 'completed', 'archived'], `${path}.state`),
      due_at: nullableRfc3339(read('due_at'), `${path}.due_at`),
    };
  }
  if (kind === 'note') {
    const read = objectReader(input, ['kind', 'title', 'body'], path);
    return { kind, title: stringValue(read('title'), `${path}.title`), body: nullableString(read('body'), `${path}.body`) };
  }
  const read = objectReader(input, ['kind', 'title', 'criteria_summary'], path);
  return {
    kind,
    title: stringValue(read('title'), `${path}.title`),
    criteria_summary: arrayValue(read('criteria_summary'), `${path}.criteria_summary`, (value, itemPath) => stringValue(value, itemPath)),
  };
}

function materializationValue(input: unknown, path: string): ContactMaterialization {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) return invalid(path, 'materialization object');
  const status = enumValue(Reflect.get(input, 'status'), ['source_only', 'materialized'], `${path}.status`);
  const common = [
    'status', 'source_record_id', 'source_key_hash', 'section', 'occurrence_ordinal',
    'capture_quality', 'captured_at', 'value',
  ];
  const keys = status === 'materialized' ? [...common, 'entity_type', 'entity_id'] : common;
  const read = objectReader(input, keys, path);
  const sourceKeyHash = stringValue(read('source_key_hash'), `${path}.source_key_hash`);
  if (!/^[0-9a-f]{64}$/.test(sourceKeyHash)) return invalid(`${path}.source_key_hash`, '64 lowercase hexadecimal characters');
  const base = {
    source_record_id: positiveInteger(read('source_record_id'), `${path}.source_record_id`),
    source_key_hash: sourceKeyHash,
    section: enumValue(read('section'), SECTION_NAMES, `${path}.section`),
    occurrence_ordinal: positiveInteger(read('occurrence_ordinal'), `${path}.occurrence_ordinal`),
    capture_quality: enumValue(read('capture_quality'), CAPTURE_QUALITIES, `${path}.capture_quality`),
    captured_at: nullableRfc3339(read('captured_at'), `${path}.captured_at`),
    value: occurrenceValue(read('value'), `${path}.value`),
  };
  if (status === 'source_only') return { status, ...base };
  return {
    status,
    ...base,
    entity_type: enumValue(
      read('entity_type'),
      ['note', 'saved_search', 'task', 'smart_plan', 'opportunity'],
      `${path}.entity_type`,
    ),
    entity_id: positiveInteger(read('entity_id'), `${path}.entity_id`),
  };
}

export const decodeContactSectionPage: Decoder<ContactSectionPage> = (input, path = 'response') => {
  const read = objectReader(input, ['rows', 'total', 'page', 'page_size', 'page_count'], path);
  return {
    rows: arrayValue(read('rows'), `${path}.rows`, materializationValue),
    total: nonnegativeInteger(read('total'), `${path}.total`),
    page: positiveInteger(read('page'), `${path}.page`),
    page_size: integer(read('page_size'), `${path}.page_size`, 1, 100),
    page_count: nonnegativeInteger(read('page_count'), `${path}.page_count`),
  };
};

function timelineEntryValue(input: unknown, path: string): ContactTimelineEntry {
  const read = objectReader(
    input,
    ['key', 'origin', 'kind', 'title', 'body', 'outcome', 'occurred_at', 'source_record_id', 'entity_type', 'entity_id'],
    path,
  );
  return {
    key: stringValue(read('key'), `${path}.key`),
    origin: enumValue(read('origin'), ['recovered', 'internal_crm', 'legacy_lead', 'booking'], `${path}.origin`),
    kind: stringValue(read('kind'), `${path}.kind`),
    title: stringValue(read('title'), `${path}.title`),
    body: nullableString(read('body'), `${path}.body`),
    outcome: nullableString(read('outcome'), `${path}.outcome`),
    occurred_at: nullableRfc3339(read('occurred_at'), `${path}.occurred_at`),
    source_record_id: nullablePositiveInteger(read('source_record_id'), `${path}.source_record_id`),
    entity_type: stringValue(read('entity_type'), `${path}.entity_type`),
    entity_id: positiveInteger(read('entity_id'), `${path}.entity_id`),
  };
}

export const decodeContactTimelinePage: Decoder<ContactTimelinePage> = (input, path = 'response') => {
  const read = objectReader(input, ['rows', 'next_cursor', 'has_more'], path);
  return {
    rows: arrayValue(read('rows'), `${path}.rows`, timelineEntryValue),
    next_cursor: nullableString(read('next_cursor'), `${path}.next_cursor`),
    has_more: booleanValue(read('has_more'), `${path}.has_more`),
  };
};

function artifactValue(input: unknown, path: string): ContactArtifactMetadata {
  const read = objectReader(input, ['artifact_id', 'artifact_type', 'sha256', 'size_bytes', 'content_href'], path);
  const artifactId = positiveInteger(read('artifact_id'), `${path}.artifact_id`);
  const sha256 = stringValue(read('sha256'), `${path}.sha256`);
  if (!/^[0-9a-f]{64}$/.test(sha256)) return invalid(`${path}.sha256`, '64 lowercase hexadecimal characters');
  const contentHref = stringValue(read('content_href'), `${path}.content_href`);
  if (contentHref !== `/api/v1/command/archive/artifacts/${artifactId}/content`) {
    return invalid(`${path}.content_href`, 'artifact-derived content path');
  }
  return {
    artifact_id: artifactId,
    artifact_type: stringValue(read('artifact_type'), `${path}.artifact_type`, 1, 64),
    sha256,
    size_bytes: nonnegativeInteger(read('size_bytes'), `${path}.size_bytes`),
    content_href: contentHref,
  };
}

function sourceMetadataValue(input: unknown, path: string): ContactSourceMetadata {
  const read = objectReader(
    input,
    ['source_record_id', 'record_kind', 'evidence_level', 'capture_quality', 'captured_at', 'artifacts'],
    path,
  );
  return {
    source_record_id: positiveInteger(read('source_record_id'), `${path}.source_record_id`),
    record_kind: stringValue(read('record_kind'), `${path}.record_kind`, 1, 64),
    evidence_level: enumValue(
      read('evidence_level'),
      ['observed_record', 'rendered_occurrence', 'displayed_aggregate'],
      `${path}.evidence_level`,
    ),
    capture_quality: enumValue(read('capture_quality'), CAPTURE_QUALITIES, `${path}.capture_quality`),
    captured_at: nullableRfc3339(read('captured_at'), `${path}.captured_at`),
    artifacts: arrayValue(read('artifacts'), `${path}.artifacts`, artifactValue),
  };
}

function sectionEvidenceValue(input: unknown, path: string): ContactSectionEvidence {
  const read = objectReader(
    input,
    ['capture_position_id', 'section', 'source_record_id', 'capture_quality', 'row_count', 'is_empty', 'limitation_codes'],
    path,
  );
  return {
    capture_position_id: positiveInteger(read('capture_position_id'), `${path}.capture_position_id`),
    section: enumValue(read('section'), SECTION_NAMES, `${path}.section`),
    source_record_id: positiveInteger(read('source_record_id'), `${path}.source_record_id`),
    capture_quality: enumValue(read('capture_quality'), CAPTURE_QUALITIES, `${path}.capture_quality`),
    row_count: nonnegativeInteger(read('row_count'), `${path}.row_count`),
    is_empty: booleanValue(read('is_empty'), `${path}.is_empty`),
    limitation_codes: arrayValue(read('limitation_codes'), `${path}.limitation_codes`, (value, itemPath) => stringValue(value, itemPath)),
  };
}

function capturePositionValue(input: unknown, path: string): ContactCapturePosition {
  const read = objectReader(
    input,
    ['capture_position_id', 'capture_ordinal', 'source_record_id', 'capture_quality', 'sections'],
    path,
  );
  return {
    capture_position_id: positiveInteger(read('capture_position_id'), `${path}.capture_position_id`),
    capture_ordinal: positiveInteger(read('capture_ordinal'), `${path}.capture_ordinal`),
    source_record_id: positiveInteger(read('source_record_id'), `${path}.source_record_id`),
    capture_quality: enumValue(read('capture_quality'), CAPTURE_QUALITIES, `${path}.capture_quality`),
    sections: arrayValue(read('sections'), `${path}.sections`, sectionEvidenceValue),
  };
}

export const decodeContactEvidence: Decoder<ContactEvidence> = (input, path = 'response') => {
  const keys = [
    'contact_id', 'provider_contact_rows', 'resolved_provider_identities', 'coalesced_aliases',
    'lead_backed_contacts', 'reviewed_overlaps', 'legacy_only_contacts', 'capture_positions',
    'section_matrix', 'sources', 'capture_quality',
  ];
  const read = objectReader(input, keys, path);
  const aliases = integer(read('coalesced_aliases'), `${path}.coalesced_aliases`, 0, 0);
  return {
    contact_id: positiveInteger(read('contact_id'), `${path}.contact_id`),
    provider_contact_rows: nonnegativeInteger(read('provider_contact_rows'), `${path}.provider_contact_rows`),
    resolved_provider_identities: nonnegativeInteger(read('resolved_provider_identities'), `${path}.resolved_provider_identities`),
    coalesced_aliases: aliases === 0 ? 0 : invalid(`${path}.coalesced_aliases`, 'exact integer zero'),
    lead_backed_contacts: nonnegativeInteger(read('lead_backed_contacts'), `${path}.lead_backed_contacts`),
    reviewed_overlaps: nonnegativeInteger(read('reviewed_overlaps'), `${path}.reviewed_overlaps`),
    legacy_only_contacts: nonnegativeInteger(read('legacy_only_contacts'), `${path}.legacy_only_contacts`),
    capture_positions: arrayValue(read('capture_positions'), `${path}.capture_positions`, capturePositionValue),
    section_matrix: arrayValue(read('section_matrix'), `${path}.section_matrix`, sectionEvidenceValue),
    sources: arrayValue(read('sources'), `${path}.sources`, sourceMetadataValue),
    capture_quality: enumValue(read('capture_quality'), EVIDENCE_QUALITIES, `${path}.capture_quality`),
  };
};

function celebrationRowValue(input: unknown, path: string): ContactCelebrationRow {
  const read = objectReader(input, ['contact_id', 'display_name', 'kind', 'month', 'day', 'year', 'year_quality', 'origin'], path);
  const month = integer(read('month'), `${path}.month`, 1, 12);
  const rawYear = read('year');
  const year = rawYear === null
    ? null
    : integer(rawYear, `${path}.year`, Number.MIN_SAFE_INTEGER, Number.MAX_SAFE_INTEGER);
  const day = integer(read('day'), `${path}.day`, 1, 31);
  return {
    contact_id: positiveInteger(read('contact_id'), `${path}.contact_id`),
    display_name: stringValue(read('display_name'), `${path}.display_name`),
    kind: enumValue(read('kind'), ['birthday', 'anniversary'], `${path}.kind`),
    month,
    day,
    year,
    year_quality: enumValue(read('year_quality'), ['verified', 'yearless', 'sentinel', 'unknown'], `${path}.year_quality`),
    origin: enumValue(read('origin'), ['internal_crm', 'recovered'], `${path}.origin`),
  };
}

export const decodeContactCelebrations: Decoder<ContactCelebrations> = (input, path = 'response') => {
  const read = objectReader(input, ['birthdays', 'anniversaries'], path);
  return {
    birthdays: arrayValue(read('birthdays'), `${path}.birthdays`, celebrationRowValue),
    anniversaries: arrayValue(read('anniversaries'), `${path}.anniversaries`, celebrationRowValue),
  };
};

export const decodeLegacyContact: Decoder<LegacyContact> = (input, path = 'response') => {
  const read = objectReader(
    input,
    ['id', 'first_name', 'last_name', 'email', 'phone', 'lead_id', 'birthday', 'anniversary', 'stage'],
    path,
  );
  return {
    id: positiveInteger(read('id'), `${path}.id`),
    first_name: stringValue(read('first_name'), `${path}.first_name`),
    last_name: stringValue(read('last_name'), `${path}.last_name`),
    email: nullableString(read('email'), `${path}.email`),
    phone: nullableString(read('phone'), `${path}.phone`),
    lead_id: nullablePositiveInteger(read('lead_id'), `${path}.lead_id`),
    birthday: nullableDate(read('birthday'), `${path}.birthday`),
    anniversary: nullableDate(read('anniversary'), `${path}.anniversary`),
    stage: stringValue(read('stage'), `${path}.stage`),
  };
};

function inputReader(input: unknown, allowed: readonly string[], path: string): Reader {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) return invalid(path, 'object');
  const actual = Object.keys(input);
  if (actual.some((key) => !allowed.includes(key))) return invalid(path, `object keys ${allowed.join(', ')}`);
  return (key: string): unknown => Reflect.get(input, key);
}

function optionalText(
  read: Reader,
  key: string,
  maximum: number,
  minimum = 0,
): string | undefined {
  const value = read(key);
  if (value === undefined) return undefined;
  return stringValue(value, key, minimum, maximum);
}

function optionalStage(read: Reader, key: string): string | undefined {
  const value = optionalText(read, key, 50, 1);
  if (value !== undefined && value.trim().length === 0) {
    return invalid(key, 'nonblank stage');
  }
  return value;
}

function optionalNullableText(read: Reader, key: string, maximum: number): string | null | undefined {
  const value = read(key);
  if (value === undefined) return undefined;
  if (value === null) return null;
  return stringValue(value, key, 0, maximum);
}

function optionalNullableDate(read: Reader, key: string): string | null | undefined {
  const value = read(key);
  if (value === undefined) return undefined;
  return nullableDate(value, key);
}

export const decodeContactCreateInput: Decoder<ContactCreateInput> = (input, path = 'request') => {
  const keys = ['first_name', 'last_name', 'email', 'phone', 'stage', 'birthday', 'anniversary'];
  const read = inputReader(input, keys, path);
  const firstName = stringValue(read('first_name'), `${path}.first_name`, 1, 120);
  if (firstName.trim().length === 0) return invalid(`${path}.first_name`, 'nonblank name');
  const result: {
    first_name: string;
    last_name?: string;
    email?: string | null;
    phone?: string | null;
    stage?: string;
    birthday?: string | null;
    anniversary?: string | null;
  } = { first_name: firstName };
  const lastName = optionalText(read, 'last_name', 120);
  const email = optionalNullableText(read, 'email', 255);
  const phone = optionalNullableText(read, 'phone', 50);
  const stage = optionalStage(read, 'stage');
  const birthday = optionalNullableDate(read, 'birthday');
  const anniversary = optionalNullableDate(read, 'anniversary');
  if (lastName !== undefined) result.last_name = lastName;
  if (email !== undefined) result.email = email;
  if (phone !== undefined) result.phone = phone;
  if (stage !== undefined) result.stage = stage;
  if (birthday !== undefined) result.birthday = birthday;
  if (anniversary !== undefined) result.anniversary = anniversary;
  return result;
};

export const decodeContactUpdateInput: Decoder<ContactUpdateInput> = (input, path = 'request') => {
  const keys = ['first_name', 'last_name', 'email', 'phone', 'stage', 'birthday', 'anniversary'];
  const read = inputReader(input, keys, path);
  if (typeof input !== 'object' || input === null || Object.keys(input).length === 0) {
    return invalid(path, 'at least one update field');
  }
  const firstName = optionalText(read, 'first_name', 120, 1);
  if (firstName !== undefined && firstName.trim().length === 0) return invalid(`${path}.first_name`, 'nonblank name');
  const result: {
    first_name?: string;
    last_name?: string;
    email?: string | null;
    phone?: string | null;
    stage?: string;
    birthday?: string | null;
    anniversary?: string | null;
  } = {};
  const lastName = optionalText(read, 'last_name', 120);
  const email = optionalNullableText(read, 'email', 255);
  const phone = optionalNullableText(read, 'phone', 50);
  const stage = optionalStage(read, 'stage');
  const birthday = optionalNullableDate(read, 'birthday');
  const anniversary = optionalNullableDate(read, 'anniversary');
  if (firstName !== undefined) result.first_name = firstName;
  if (lastName !== undefined) result.last_name = lastName;
  if (email !== undefined) result.email = email;
  if (phone !== undefined) result.phone = phone;
  if (stage !== undefined) result.stage = stage;
  if (birthday !== undefined) result.birthday = birthday;
  if (anniversary !== undefined) result.anniversary = anniversary;
  if (Object.keys(result).length === 0) return invalid(path, 'at least one defined update field');
  return result;
};

function contactIds(input: unknown, path: string): readonly number[] {
  const values = arrayValue(input, path, (value, itemPath) => positiveInteger(value, itemPath));
  if (values.length < 1 || values.length > 200 || new Set(values).size !== values.length) {
    return invalid(path, '1..200 unique positive contact IDs');
  }
  return values;
}

export const decodeContactBulkInput: Decoder<ContactBulkInput> = (input, path = 'request') => {
  const read = objectReader(input, ['contact_ids', 'action'], path);
  const ids = contactIds(read('contact_ids'), `${path}.contact_ids`);
  const rawAction = read('action');
  if (typeof rawAction !== 'object' || rawAction === null || Array.isArray(rawAction)) {
    return invalid(`${path}.action`, 'bulk action object');
  }
  const kind = enumValue(Reflect.get(rawAction, 'action'), ['set_stage', 'add_tag', 'remove_tag'], `${path}.action.action`);
  if (kind === 'set_stage') {
    const action = objectReader(rawAction, ['action', 'stage'], `${path}.action`);
    const stage = stringValue(action('stage'), `${path}.action.stage`, 1, 50);
    if (stage.trim().length === 0) return invalid(`${path}.action.stage`, 'nonblank stage');
    return { contact_ids: ids, action: { action: kind, stage } };
  }
  const action = objectReader(rawAction, ['action', 'tag_id'], `${path}.action`);
  const tagId = positiveInteger(action('tag_id'), `${path}.action.tag_id`);
  return { contact_ids: ids, action: { action: kind, tag_id: tagId } };
};

function sortedUniquePositiveIds(input: unknown, path: string, allowEmpty: boolean): readonly number[] {
  const values = arrayValue(input, path, (value, itemPath) => positiveInteger(value, itemPath));
  if ((!allowEmpty && values.length === 0) || values.length > 200) return invalid(path, 'bounded ID array');
  for (let index = 0; index < values.length; index += 1) {
    if (index > 0 && (values[index - 1] ?? 0) >= (values[index] ?? 0)) {
      return invalid(path, 'strictly ascending unique IDs');
    }
  }
  return values;
}

export const decodeContactBulkResult: Decoder<ContactBulkResult> = (input, path = 'response') => {
  const read = objectReader(input, ['requested_contact_ids', 'actioned_contact_ids', 'action'], path);
  const requested = sortedUniquePositiveIds(read('requested_contact_ids'), `${path}.requested_contact_ids`, false);
  const actioned = sortedUniquePositiveIds(read('actioned_contact_ids'), `${path}.actioned_contact_ids`, true);
  const requestedSet = new Set(requested);
  if (actioned.some((id) => !requestedSet.has(id))) return invalid(`${path}.actioned_contact_ids`, 'subset of requested IDs');
  return {
    requested_contact_ids: requested,
    actioned_contact_ids: actioned,
    action: enumValue(read('action'), ['set_stage', 'add_tag', 'remove_tag'], `${path}.action`),
  };
};

function canonicalSet<T extends string>(values: unknown, allowed: readonly T[], path: string): readonly T[] {
  const decoded = arrayValue(values, path, (value, itemPath) => enumValue(value, allowed, itemPath));
  return [...new Set(decoded)].sort();
}

function exactRequestObject(input: ContactDirectoryRequest): Reader {
  const keys = [
    'query', 'stage', 'owner_actor_id', 'assignee_actor_id', 'tag', 'source', 'origin',
    'health_min', 'health_max', 'birthday_month', 'anniversary_month', 'smart_view',
    'sort', 'direction', 'page', 'page_size',
  ];
  return inputReader(input, keys, 'request');
}

export function serializeDirectoryRequest(input: ContactDirectoryRequest): string {
  const read = exactRequestObject(input);
  const params = new URLSearchParams();
  const addTrimmed = (key: string, maximum: number): void => {
    const raw = read(key);
    if (raw === undefined) return;
    const value = stringValue(raw, `request.${key}`, 0, maximum).trim();
    if (value.length > 0) params.append(key, value);
  };
  addTrimmed('query', 200);
  addTrimmed('stage', 50);
  addTrimmed('owner_actor_id', 255);
  addTrimmed('assignee_actor_id', 255);
  const rawTags = read('tag');
  if (rawTags !== undefined) {
    const tags = arrayValue(rawTags, 'request.tag', (value, path) => positiveInteger(value, path));
    [...new Set(tags)].sort((left, right) => left - right).forEach((tag) => params.append('tag', String(tag)));
  }
  const rawSources = read('source');
  if (rawSources !== undefined) {
    if (!Array.isArray(rawSources)) return invalid('request.source', 'array');
    canonicalSet(rawSources, SOURCES, 'request.source').forEach((value) => params.append('source', value));
  }
  const rawOrigins = read('origin');
  if (rawOrigins !== undefined) {
    if (!Array.isArray(rawOrigins)) return invalid('request.origin', 'array');
    canonicalSet(rawOrigins, ORIGINS, 'request.origin').forEach((value) => params.append('origin', value));
  }
  const appendInteger = (key: string, minimum: number, maximum: number): number | undefined => {
    const raw = read(key);
    if (raw === undefined) return undefined;
    const value = integer(raw, `request.${key}`, minimum, maximum);
    params.append(key, String(value));
    return value;
  };
  const healthMin = appendInteger('health_min', 0, 100);
  const healthMax = appendInteger('health_max', 0, 100);
  if (healthMin !== undefined && healthMax !== undefined && healthMin > healthMax) {
    return invalid('request.health', 'health_min no greater than health_max');
  }
  appendInteger('birthday_month', 1, 12);
  appendInteger('anniversary_month', 1, 12);
  const rawSmartView = read('smart_view');
  if (rawSmartView !== undefined) params.append('smart_view', enumValue(rawSmartView, SMART_VIEWS, 'request.smart_view'));
  const rawSort = read('sort');
  if (rawSort !== undefined) params.append('sort', enumValue(rawSort, SORT_KEYS, 'request.sort'));
  const rawDirection = read('direction');
  if (rawDirection !== undefined) params.append('direction', enumValue(rawDirection, DIRECTIONS, 'request.direction'));
  appendInteger('page', 1, Number.MAX_SAFE_INTEGER);
  appendInteger('page_size', 1, 100);
  return params.toString();
}

type CommandRequestOptions = Readonly<{ signal?: AbortSignal }>;

export type ContactsApi = Readonly<{
  directory: (request: ContactDirectoryRequest, options?: CommandRequestOptions) => Promise<ContactDirectoryPage>;
  detail: (id: number, options?: CommandRequestOptions) => Promise<ContactDetail>;
  neighbors: (id: number, request: ContactDirectoryRequest, options?: CommandRequestOptions) => Promise<ContactNeighbors>;
  workspace: (id: number, options?: CommandRequestOptions) => Promise<ContactWorkspaceSummary>;
  timeline: (id: number, cursor: string | null, pageSize: number, options?: CommandRequestOptions) => Promise<ContactTimelinePage>;
  section: (id: number, section: Exclude<ContactSectionName, 'timeline'>, page: number, pageSize: number, options?: CommandRequestOptions) => Promise<ContactSectionPage>;
  evidence: (id: number, options?: CommandRequestOptions) => Promise<ContactEvidence>;
  celebrations: (month: number, options?: CommandRequestOptions) => Promise<ContactCelebrations>;
  create: (input: ContactCreateInput, options?: CommandRequestOptions) => Promise<ContactCreated>;
  update: (id: number, input: ContactUpdateInput, options?: CommandRequestOptions) => Promise<ContactCreated>;
  bulk: (input: ContactBulkInput, options?: CommandRequestOptions) => Promise<ContactBulkResult>;
}>;

function queryPath(path: string, params: string): string {
  return params.length === 0 ? path : `${path}?${params}`;
}

function validId(id: number, path: string): number {
  return positiveInteger(id, path);
}

const SECTION_ROUTES: Readonly<Record<Exclude<ContactSectionName, 'timeline'>, string>> = {
  opportunities: 'opportunities',
  smart_plans: 'smart-plans',
  notes: 'notes',
  saved_searches: 'saved-searches',
  tasks_to_do: 'tasks?state=to_do',
  tasks_completed: 'tasks?state=completed',
  tasks_archived: 'tasks?state=archived',
};

function sectionRoute(section: unknown): string {
  const value = enumValue(
    section,
    ['opportunities', 'smart_plans', 'notes', 'saved_searches', 'tasks_to_do', 'tasks_completed', 'tasks_archived'],
    'request.section',
  );
  return SECTION_ROUTES[value];
}

export const contactsApi: ContactsApi = {
  directory: async (request, options) => commandJson({
    path: queryPath('/contacts/directory', serializeDirectoryRequest(request)),
    decode: decodeContactDirectoryPage,
    signal: options?.signal,
  }),
  detail: async (id, options) => commandJson({
    path: `/contacts/${validId(id, 'request.id')}`,
    decode: decodeContactDetail,
    signal: options?.signal,
  }),
  neighbors: async (id, request, options) => commandJson({
    path: queryPath(`/contacts/${validId(id, 'request.id')}/neighbors`, serializeDirectoryRequest(request)),
    decode: decodeContactNeighbors,
    signal: options?.signal,
  }),
  workspace: async (id, options) => commandJson({
    path: `/contacts/${validId(id, 'request.id')}/workspace/summary`,
    decode: decodeContactWorkspaceSummary,
    signal: options?.signal,
  }),
  timeline: async (id, cursor, pageSize, options) => {
    if (cursor !== null && typeof cursor !== 'string') return invalid('request.cursor', 'string or null');
    const params = new URLSearchParams();
    if (cursor !== null) params.append('cursor', cursor);
    params.append('page_size', String(integer(pageSize, 'request.page_size', 1, 100)));
    return commandJson({
      path: `/contacts/${validId(id, 'request.id')}/timeline?${params.toString()}`,
      decode: decodeContactTimelinePage,
      signal: options?.signal,
    });
  },
  section: async (id, section, page, pageSize, options) => {
    const route = sectionRoute(section);
    const separator = route.includes('?') ? '&' : '?';
    const suffix = `page=${integer(page, 'request.page', 1)}&page_size=${integer(pageSize, 'request.page_size', 1, 100)}`;
    return commandJson({
      path: `/contacts/${validId(id, 'request.id')}/${route}${separator}${suffix}`,
      decode: decodeContactSectionPage,
      signal: options?.signal,
    });
  },
  evidence: async (id, options) => commandJson({
    path: `/contacts/${validId(id, 'request.id')}/evidence`,
    decode: decodeContactEvidence,
    signal: options?.signal,
  }),
  celebrations: async (month, options) => commandJson({
    path: `/celebrations?month=${integer(month, 'request.month', 1, 12)}`,
    decode: decodeContactCelebrations,
    signal: options?.signal,
  }),
  create: async (input, options) => commandJson({
    path: '/contacts',
    method: 'POST',
    body: decodeContactCreateInput(input),
    decode: decodeLegacyContact,
    signal: options?.signal,
  }),
  update: async (id, input, options) => commandJson({
    path: `/contacts/${validId(id, 'request.id')}`,
    method: 'PATCH',
    body: decodeContactUpdateInput(input),
    decode: decodeLegacyContact,
    signal: options?.signal,
  }),
  bulk: async (input, options) => commandJson({
    path: '/contacts/bulk',
    method: 'POST',
    body: decodeContactBulkInput(input),
    decode: decodeContactBulkResult,
    signal: options?.signal,
  }),
};
