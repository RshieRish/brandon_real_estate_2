import { commandBlob, commandJson, CommandDecodeError, type Decoder } from './http';
import {
  createTask as createLifecycleTask,
  restoreTask as restoreLifecycleTask,
  type Task,
  type TaskLifecycleRequest,
  type TaskRequestOptions,
} from './tasks';

export type ContactCaptureQuality = 'complete' | 'partial' | 'shell' | 'error';
export type ContactEvidenceQuality = 'complete' | 'partial' | 'limitation';
export type ContactEvidenceStatus = 'loading' | 'available' | 'unavailable';
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

type ContactWorkspaceSummaryBase = Readonly<{
  open_tasks: number;
  completed_tasks: number;
  archived_tasks: number;
  active_smart_plans: number;
  opportunities: number;
  notes: number;
  saved_searches: number;
  bookings: number;
}>;

type LegacyContactWorkspaceTaskSummary = Readonly<{
  active_tasks?: never;
  cancelled_tasks?: never;
  archived_mutable_tasks?: never;
  archived_recovered_evidence?: never;
}>;

type ExpandedContactWorkspaceTaskSummary = Readonly<{
  active_tasks: number;
  cancelled_tasks: number;
  archived_mutable_tasks: number;
  archived_recovered_evidence: number;
}>;

/** The legacy variant exists only for a rolling frontend-before-backend deploy. */
export type ContactWorkspaceSummary = ContactWorkspaceSummaryBase & (
  | LegacyContactWorkspaceTaskSummary
  | ExpandedContactWorkspaceTaskSummary
);

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

export type ContactSectionCoverageState =
  | 'unreconciled'
  | 'not_linked'
  | 'partial'
  | 'verified_empty'
  | 'captured';

export type ContactSectionCoverage = Readonly<{
  state: ContactSectionCoverageState;
  recovered_count: number;
  capture_positions: number;
  complete_positions: number;
}>;

export type ContactPresentationText = Readonly<{
  preview: string;
  full: string;
  truncated: boolean;
}>;

/**
 * Bounds archive-derived values by Unicode code point for safe presentation.
 * The full value remains available only through a deliberate UI expansion.
 */
export function contactPresentationText(value: string, limit: number): ContactPresentationText {
  if (!Number.isSafeInteger(limit) || limit < 1) {
    throw new RangeError('Contact presentation limit must be a positive safe integer');
  }
  const characters = Array.from(value);
  if (characters.length <= limit) return { preview: value, full: value, truncated: false };
  return {
    preview: `${characters.slice(0, limit).join('')}…`,
    full: value,
    truncated: true,
  };
}

const TECHNICAL_CONTACT_TIMELINE_KINDS = new Set([
  'archive_contact_imported',
  'archive_timeline_capture',
]);

export function isTechnicalContactTimelineEntry(entry: ContactTimelineEntry): boolean {
  return entry.origin === 'internal_crm' && TECHNICAL_CONTACT_TIMELINE_KINDS.has(entry.kind);
}

/**
 * Describes only evidence attached to this contact. Global archive totals are
 * useful migration context, but never prove that an individual section is empty.
 */
export function contactSectionCoverage(
  evidence: ContactEvidence,
  section: ContactSectionName,
): ContactSectionCoverage {
  const capturePositions = evidence.capture_positions.length;
  if (capturePositions === 0) {
    return {
      state: evidence.provider_contact_rows === 0 && evidence.resolved_provider_identities === 0
        ? 'unreconciled'
        : 'not_linked',
      recovered_count: 0,
      capture_positions: 0,
      complete_positions: 0,
    };
  }

  const positionIds = new Set(evidence.capture_positions.map((position) => position.capture_position_id));
  const cells = evidence.section_matrix.filter((cell) => (
    cell.section === section && positionIds.has(cell.capture_position_id)
  ));
  const completePositions = new Set(cells.filter((cell) => (
    cell.capture_quality === 'complete'
  )).map((cell) => cell.capture_position_id)).size;
  const recoveredCount = cells.reduce((total, cell) => total + cell.row_count, 0);
  const everyPositionRepresented = cells.length === capturePositions
    && evidence.capture_positions.every((position) => cells.filter((cell) => (
      cell.capture_position_id === position.capture_position_id
    )).length === 1);

  if (recoveredCount > 0) {
    return {
      state: 'captured',
      recovered_count: recoveredCount,
      capture_positions: capturePositions,
      complete_positions: completePositions,
    };
  }
  const verifiedEmpty = everyPositionRepresented && cells.every((cell) => (
    cell.capture_quality === 'complete' && cell.is_empty && cell.row_count === 0
  ));
  return {
    state: verifiedEmpty ? 'verified_empty' : 'partial',
    recovered_count: 0,
    capture_positions: capturePositions,
    complete_positions: completePositions,
  };
}

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

export type ContactInternalTimelineEntry = Readonly<{
  id: number;
  kind: string;
  summary: string;
  created_at: string;
}>;

type ContactInternalTaskBase = Readonly<{
  id: number;
  title: string;
  contact_id: number;
  description: string;
  priority: string;
  due_at: string | null;
}>;

export type ContactLegacyInternalTask = ContactInternalTaskBase & Readonly<{
  status: 'open' | 'in_progress' | 'completed' | 'cancelled' | 'archived';
  archived_at?: never;
  archive_reason?: never;
  version?: never;
}>;

export type ContactLifecycleInternalTask = ContactInternalTaskBase & Readonly<{
  status: 'open' | 'in_progress' | 'completed' | 'cancelled';
  archived_at: string | null;
  archive_reason: string | null;
  version: number;
}>;

export type ContactInternalTask = ContactLegacyInternalTask | ContactLifecycleInternalTask;

export type ContactInternalNote = Readonly<{
  id: number;
  contact_id: number;
  body: string;
  created_at: string;
  updated_at: string;
}>;

export type ContactInternalSmartPlan = Readonly<{
  id: number;
  plan_id: number;
  status: string;
}>;

export type ContactInternalOpportunity = Readonly<{
  id: number;
  name: string;
  stage: string;
  value_cents: number | null;
  role: string;
}>;

export type ContactInternalSavedSearch = Readonly<{
  id: number;
  name: string;
  criteria: string;
}>;

export type ContactInternalBooking = Readonly<{
  id: number;
  meeting_type: string;
  context: string;
  scheduled_at: string;
  location: string | null;
  notes: string;
}>;

export type ContactInternalWorkspace = Readonly<{
  contact: LegacyContact;
  timeline: readonly ContactInternalTimelineEntry[];
  tasks: readonly ContactInternalTask[];
  notes: readonly ContactInternalNote[];
  smart_plans: readonly ContactInternalSmartPlan[];
  opportunities: readonly ContactInternalOpportunity[];
  saved_searches: readonly ContactInternalSavedSearch[];
  bookings: readonly ContactInternalBooking[];
  tags: readonly ContactTag[];
}>;

export type ContactJsonValue = null | boolean | number | string
  | readonly ContactJsonValue[]
  | Readonly<{ [key: string]: ContactJsonValue }>;

export type ContactNoteCreateInput = Readonly<{ body: string }>;
export type ContactNoteCreated = Readonly<{ id: number; body: string }>;
export type ContactDeleted = Readonly<{ deleted: true; id: number }>;
export type ContactSavedSearchCreateInput = Readonly<{
  name: string;
  criteria: Readonly<Record<string, ContactJsonValue>>;
}>;
export type ContactSavedSearchCreated = Readonly<{ id: number; name: string; criteria: string }>;
export type ContactTagCreateInput = Readonly<{ name: string }>;
export type ContactTagAssignment = Readonly<{ contact_id: number; tag_id: number }>;
export type ContactTagRemoval = ContactTagAssignment & Readonly<{ removed: boolean }>;
export type ContactTaskCreateInput = Readonly<{
  title: string;
  contact_id: number;
  description: string;
  priority: 'low' | 'normal' | 'high';
  due_at: string | null;
}>;

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
  const legacyKeys = [
    'open_tasks', 'completed_tasks', 'archived_tasks', 'active_smart_plans',
    'opportunities', 'notes', 'saved_searches', 'bookings',
  ] as const;
  const additiveKeys = [
    'active_tasks', 'cancelled_tasks',
    'archived_mutable_tasks', 'archived_recovered_evidence',
  ] as const;
  const hasAdditiveKey = typeof input === 'object'
    && input !== null
    && !Array.isArray(input)
    && additiveKeys.some((key) => Object.hasOwn(input, key));
  const keys = hasAdditiveKey ? [...legacyKeys, ...additiveKeys] : legacyKeys;
  const read = objectReader(input, keys, path);
  const legacy = {
    open_tasks: nonnegativeInteger(read('open_tasks'), `${path}.open_tasks`),
    completed_tasks: nonnegativeInteger(read('completed_tasks'), `${path}.completed_tasks`),
    archived_tasks: nonnegativeInteger(read('archived_tasks'), `${path}.archived_tasks`),
    active_smart_plans: nonnegativeInteger(read('active_smart_plans'), `${path}.active_smart_plans`),
    opportunities: nonnegativeInteger(read('opportunities'), `${path}.opportunities`),
    notes: nonnegativeInteger(read('notes'), `${path}.notes`),
    saved_searches: nonnegativeInteger(read('saved_searches'), `${path}.saved_searches`),
    bookings: nonnegativeInteger(read('bookings'), `${path}.bookings`),
  };
  if (!hasAdditiveKey) return legacy;
  const additive = {
    active_tasks: nonnegativeInteger(read('active_tasks'), `${path}.active_tasks`),
    cancelled_tasks: nonnegativeInteger(read('cancelled_tasks'), `${path}.cancelled_tasks`),
    archived_mutable_tasks: nonnegativeInteger(
      read('archived_mutable_tasks'), `${path}.archived_mutable_tasks`,
    ),
    archived_recovered_evidence: nonnegativeInteger(
      read('archived_recovered_evidence'), `${path}.archived_recovered_evidence`,
    ),
  };
  if (
    legacy.open_tasks !== additive.active_tasks
    || legacy.archived_tasks !== (
      additive.archived_mutable_tasks + additive.archived_recovered_evidence
    )
  ) return invalid(path, 'consistent task summary totals');
  return { ...legacy, ...additive };
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
  const result = {
    capture_position_id: positiveInteger(read('capture_position_id'), `${path}.capture_position_id`),
    section: enumValue(read('section'), SECTION_NAMES, `${path}.section`),
    source_record_id: positiveInteger(read('source_record_id'), `${path}.source_record_id`),
    capture_quality: enumValue(read('capture_quality'), CAPTURE_QUALITIES, `${path}.capture_quality`),
    row_count: nonnegativeInteger(read('row_count'), `${path}.row_count`),
    is_empty: booleanValue(read('is_empty'), `${path}.is_empty`),
    limitation_codes: arrayValue(read('limitation_codes'), `${path}.limitation_codes`, (value, itemPath) => stringValue(value, itemPath)),
  };
  if ((result.is_empty && result.row_count !== 0)
    || (result.row_count > 0 && result.is_empty)
    || (result.capture_quality === 'complete' && result.row_count === 0 && !result.is_empty)) {
    return invalid(path, 'empty flag consistent with row count');
  }
  if (new Set(result.limitation_codes).size !== result.limitation_codes.length) {
    return invalid(`${path}.limitation_codes`, 'unique limitation codes');
  }
  return result;
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
  const decoded: ContactEvidence = {
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
  const positionById = new Map<number, ContactCapturePosition>();
  const nestedCellByKey = new Map<string, ContactSectionEvidence>();
  decoded.capture_positions.forEach((position, positionIndex) => {
    if (positionById.has(position.capture_position_id)) {
      invalid(`${path}.capture_positions[${positionIndex}].capture_position_id`, 'unique capture position identity');
    }
    positionById.set(position.capture_position_id, position);
    if (position.sections.length !== SECTION_NAMES.length) {
      invalid(`${path}.capture_positions[${positionIndex}].sections`, 'one cell for every contact section');
    }
    position.sections.forEach((cell, cellIndex) => {
      if (cell.capture_position_id !== position.capture_position_id) {
        invalid(`${path}.capture_positions[${positionIndex}].sections[${cellIndex}]`, 'owning capture position identity');
      }
      if (cell.section !== SECTION_NAMES[cellIndex]) {
        invalid(`${path}.capture_positions[${positionIndex}].sections[${cellIndex}].section`, 'canonical contact section order');
      }
      const key = `${cell.capture_position_id}:${cell.section}`;
      if (nestedCellByKey.has(key)) invalid(`${path}.capture_positions[${positionIndex}].sections[${cellIndex}]`, 'unique section per capture position');
      nestedCellByKey.set(key, cell);
    });
  });
  if (decoded.section_matrix.length !== nestedCellByKey.size) {
    invalid(`${path}.section_matrix`, 'exact flattened capture-position sections');
  }
  const equalCell = (left: ContactSectionEvidence, right: ContactSectionEvidence) => (
    left.capture_position_id === right.capture_position_id
    && left.section === right.section
    && left.source_record_id === right.source_record_id
    && left.capture_quality === right.capture_quality
    && left.row_count === right.row_count
    && left.is_empty === right.is_empty
    && left.limitation_codes.length === right.limitation_codes.length
    && left.limitation_codes.every((value, index) => value === right.limitation_codes[index])
  );
  decoded.section_matrix.forEach((cell, index) => {
    const position = positionById.get(cell.capture_position_id);
    const nested = nestedCellByKey.get(`${cell.capture_position_id}:${cell.section}`);
    if (!position || !nested || !equalCell(cell, nested)) {
      invalid(`${path}.section_matrix[${index}]`, 'active capture position identity');
    }
  });
  const flattened = decoded.capture_positions.flatMap((position) => position.sections);
  decoded.section_matrix.forEach((cell, index) => {
    const expected = flattened[index];
    if (!expected || !equalCell(cell, expected)) {
      invalid(`${path}.section_matrix[${index}]`, 'canonical flattened capture-position order');
    }
  });
  const matrixKeys = new Set<string>();
  decoded.section_matrix.forEach((cell, index) => {
    const key = `${cell.capture_position_id}:${cell.section}`;
    if (matrixKeys.has(key)) invalid(`${path}.section_matrix[${index}]`, 'unique capture-position section identity');
    matrixKeys.add(key);
  });
  const sourceIds = new Set<number>();
  let previousSourceId = 0;
  decoded.sources.forEach((source, sourceIndex) => {
    if (source.source_record_id <= previousSourceId || sourceIds.has(source.source_record_id)) {
      invalid(`${path}.sources[${sourceIndex}].source_record_id`, 'unique ascending source identity');
    }
    previousSourceId = source.source_record_id;
    sourceIds.add(source.source_record_id);
    let previousArtifactId = 0;
    source.artifacts.forEach((artifact, artifactIndex) => {
      if (artifact.artifact_id <= previousArtifactId) {
        invalid(
          `${path}.sources[${sourceIndex}].artifacts[${artifactIndex}].artifact_id`,
          'unique ascending artifact identity',
        );
      }
      previousArtifactId = artifact.artifact_id;
    });
  });
  decoded.capture_positions.forEach((position, positionIndex) => {
    if (!sourceIds.has(position.source_record_id)) {
      invalid(
        `${path}.capture_positions[${positionIndex}].source_record_id`,
        'source identity present in source metadata',
      );
    }
  });
  decoded.section_matrix.forEach((cell, cellIndex) => {
    if (!sourceIds.has(cell.source_record_id)) {
      invalid(
        `${path}.section_matrix[${cellIndex}].source_record_id`,
        'source identity present in source metadata',
      );
    }
  });
  return decoded;
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

function internalTimelineValue(input: unknown, path: string): ContactInternalTimelineEntry {
  const read = objectReader(input, ['id', 'kind', 'summary', 'created_at'], path);
  return {
    id: positiveInteger(read('id'), `${path}.id`),
    kind: stringValue(read('kind'), `${path}.kind`),
    summary: stringValue(read('summary'), `${path}.summary`),
    created_at: rfc3339(read('created_at'), `${path}.created_at`),
  };
}

function internalTaskValue(input: unknown, path: string): ContactInternalTask {
  const lifecycleKeys = ['archived_at', 'archive_reason', 'version'] as const;
  const lifecycle = typeof input === 'object'
    && input !== null
    && !Array.isArray(input)
    && lifecycleKeys.some((key) => Object.hasOwn(input, key));
  const read = objectReader(
    input,
    lifecycle
      ? [
          'id', 'title', 'contact_id', 'description', 'priority', 'due_at', 'status',
          ...lifecycleKeys,
        ]
      : ['id', 'title', 'contact_id', 'description', 'priority', 'due_at', 'status'],
    path,
  );
  const common = {
    id: integer(read('id'), `${path}.id`, 1, 2_147_483_647),
    title: stringValue(read('title'), `${path}.title`, 1, 255),
    contact_id: integer(read('contact_id'), `${path}.contact_id`, 1, 2_147_483_647),
    description: stringValue(read('description'), `${path}.description`),
    priority: stringValue(read('priority'), `${path}.priority`),
    due_at: nullableRfc3339(read('due_at'), `${path}.due_at`),
  };
  if (!lifecycle) {
    return {
      ...common,
      status: enumValue(
        read('status'),
        ['open', 'in_progress', 'completed', 'cancelled', 'archived'],
        `${path}.status`,
      ),
    };
  }
  const archivedAt = nullableRfc3339(read('archived_at'), `${path}.archived_at`);
  const rawReason = read('archive_reason');
  const archiveReason = rawReason === null
    ? null
    : stringValue(rawReason, `${path}.archive_reason`, 0, 500);
  return {
    ...common,
    status: enumValue(
      read('status'),
      ['open', 'in_progress', 'completed', 'cancelled'],
      `${path}.status`,
    ),
    archived_at: archivedAt,
    archive_reason: archiveReason,
    version: integer(read('version'), `${path}.version`, 1, 2_147_483_647),
  };
}

function internalNoteValue(input: unknown, path: string): ContactInternalNote {
  const read = objectReader(
    input,
    ['id', 'contact_id', 'body', 'created_at', 'updated_at'],
    path,
  );
  return {
    id: positiveInteger(read('id'), `${path}.id`),
    contact_id: positiveInteger(read('contact_id'), `${path}.contact_id`),
    body: stringValue(read('body'), `${path}.body`),
    created_at: rfc3339(read('created_at'), `${path}.created_at`),
    updated_at: rfc3339(read('updated_at'), `${path}.updated_at`),
  };
}

function internalSmartPlanValue(input: unknown, path: string): ContactInternalSmartPlan {
  const read = objectReader(input, ['id', 'plan_id', 'status'], path);
  return {
    id: positiveInteger(read('id'), `${path}.id`),
    plan_id: positiveInteger(read('plan_id'), `${path}.plan_id`),
    status: stringValue(read('status'), `${path}.status`),
  };
}

function internalOpportunityValue(input: unknown, path: string): ContactInternalOpportunity {
  const read = objectReader(input, ['id', 'name', 'stage', 'value_cents', 'role'], path);
  const rawValue = read('value_cents');
  return {
    id: positiveInteger(read('id'), `${path}.id`),
    name: stringValue(read('name'), `${path}.name`),
    stage: stringValue(read('stage'), `${path}.stage`),
    value_cents: rawValue === null
      ? null
      : integer(rawValue, `${path}.value_cents`, Number.MIN_SAFE_INTEGER),
    role: stringValue(read('role'), `${path}.role`),
  };
}

function internalSavedSearchValue(input: unknown, path: string): ContactInternalSavedSearch {
  const read = objectReader(input, ['id', 'name', 'criteria'], path);
  return {
    id: positiveInteger(read('id'), `${path}.id`),
    name: stringValue(read('name'), `${path}.name`),
    criteria: stringValue(read('criteria'), `${path}.criteria`),
  };
}

function internalBookingValue(input: unknown, path: string): ContactInternalBooking {
  const read = objectReader(
    input,
    ['id', 'meeting_type', 'context', 'scheduled_at', 'location', 'notes'],
    path,
  );
  return {
    id: positiveInteger(read('id'), `${path}.id`),
    meeting_type: stringValue(read('meeting_type'), `${path}.meeting_type`),
    context: stringValue(read('context'), `${path}.context`),
    scheduled_at: rfc3339(read('scheduled_at'), `${path}.scheduled_at`),
    location: nullableString(read('location'), `${path}.location`),
    notes: stringValue(read('notes'), `${path}.notes`),
  };
}

export const decodeContactInternalWorkspace: Decoder<ContactInternalWorkspace> = (
  input,
  path = 'response',
) => {
  const read = objectReader(
    input,
    [
      'contact', 'timeline', 'tasks', 'notes', 'smart_plans', 'opportunities',
      'saved_searches', 'bookings', 'tags',
    ],
    path,
  );
  const workspace = {
    contact: decodeLegacyContact(read('contact'), `${path}.contact`),
    timeline: arrayValue(read('timeline'), `${path}.timeline`, internalTimelineValue),
    tasks: arrayValue(read('tasks'), `${path}.tasks`, internalTaskValue),
    notes: arrayValue(read('notes'), `${path}.notes`, internalNoteValue),
    smart_plans: arrayValue(read('smart_plans'), `${path}.smart_plans`, internalSmartPlanValue),
    opportunities: arrayValue(
      read('opportunities'),
      `${path}.opportunities`,
      internalOpportunityValue,
    ),
    saved_searches: arrayValue(
      read('saved_searches'),
      `${path}.saved_searches`,
      internalSavedSearchValue,
    ),
    bookings: arrayValue(read('bookings'), `${path}.bookings`, internalBookingValue),
    tags: arrayValue(read('tags'), `${path}.tags`, tagValue),
  };
  const descendingTimestampThenId = <T extends Readonly<{ created_at: string; id: number }>>(
    left: T,
    right: T,
  ) => Date.parse(right.created_at) - Date.parse(left.created_at) || right.id - left.id;
  const descendingScheduledThenId = <T extends Readonly<{ scheduled_at: string; id: number }>>(
    left: T,
    right: T,
  ) => Date.parse(right.scheduled_at) - Date.parse(left.scheduled_at) || right.id - left.id;
  const tagNameThenId = (left: ContactTag, right: ContactTag) => (
    left.name < right.name ? -1 : left.name > right.name ? 1 : left.id - right.id
  );
  return {
    ...workspace,
    timeline: [...workspace.timeline].sort(descendingTimestampThenId),
    tasks: [...workspace.tasks].sort((left, right) => right.id - left.id),
    notes: [...workspace.notes].sort(descendingTimestampThenId),
    smart_plans: [...workspace.smart_plans].sort((left, right) => left.id - right.id),
    opportunities: [...workspace.opportunities].sort((left, right) => right.id - left.id),
    saved_searches: [...workspace.saved_searches].sort((left, right) => left.id - right.id),
    bookings: [...workspace.bookings].sort(descendingScheduledThenId),
    tags: [...workspace.tags].sort(tagNameThenId),
  };
};

export function decodeContactInternalWorkspaceForContact(
  input: unknown,
  contactId: number,
  path = 'response',
): ContactInternalWorkspace {
  const expectedId = positiveInteger(contactId, 'request.id');
  const workspace = decodeContactInternalWorkspace(input, path);
  if (workspace.contact.id !== expectedId) {
    return invalid(`${path}.contact.id`, 'requested contact identity');
  }
  workspace.notes.forEach((note, index) => {
    if (note.contact_id !== expectedId) {
      return invalid(`${path}.notes[${index}].contact_id`, 'requested contact identity');
    }
  });
  workspace.tasks.forEach((task, index) => {
    if (task.contact_id !== expectedId) {
      return invalid(`${path}.tasks[${index}].contact_id`, 'requested contact identity');
    }
  });
  return workspace;
}

function jsonValue(
  input: unknown,
  path: string,
  ancestors: Set<object> = new Set<object>(),
): ContactJsonValue {
  if (input === null || typeof input === 'string' || typeof input === 'boolean') return input;
  if (typeof input === 'number') {
    if (!Number.isFinite(input)) return invalid(path, 'finite JSON number');
    return input;
  }
  if (Array.isArray(input)) {
    if (ancestors.has(input)) return invalid(path, 'acyclic JSON value');
    ancestors.add(input);
    const result: ContactJsonValue[] = [];
    for (let index = 0; index < input.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(input, index)) {
        ancestors.delete(input);
        return invalid(`${path}[${index}]`, 'present JSON array element');
      }
      result.push(jsonValue(input[index], `${path}[${index}]`, ancestors));
    }
    ancestors.delete(input);
    return result;
  }
  if (typeof input !== 'object') return invalid(path, 'JSON value');
  const prototype = Object.getPrototypeOf(input);
  if (prototype !== Object.prototype && prototype !== null) return invalid(path, 'plain JSON object');
  if (ancestors.has(input)) return invalid(path, 'acyclic JSON value');
  ancestors.add(input);
  const result: Record<string, ContactJsonValue> = {};
  Object.keys(input).sort().forEach((key) => {
    result[key] = jsonValue(Reflect.get(input, key), `${path}.${key}`, ancestors);
  });
  ancestors.delete(input);
  return result;
}

function jsonObject(input: unknown, path: string): Readonly<Record<string, ContactJsonValue>> {
  const value = jsonValue(input, path);
  if (!isJsonRecord(value)) {
    return invalid(path, 'JSON object');
  }
  return value;
}

function isJsonRecord(
  value: ContactJsonValue,
): value is Readonly<Record<string, ContactJsonValue>> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function canonicalCriteriaText(input: unknown, path: string): string {
  const value = stringValue(input, path, 1);
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    return invalid(path, 'canonical compact JSON object text');
  }
  const canonical = JSON.stringify(jsonObject(parsed, path));
  if (canonical !== value) return invalid(path, 'canonical compact sorted JSON object text');
  if (new TextEncoder().encode(canonical).length > 65_536) {
    return invalid(path, 'canonical JSON no greater than 65536 UTF-8 bytes');
  }
  return canonical;
}

export const decodeContactNoteCreateInput: Decoder<ContactNoteCreateInput> = (
  input,
  path = 'request',
) => {
  const read = objectReader(input, ['body'], path);
  return { body: stringValue(read('body'), `${path}.body`, 1, 20_000) };
};

export const decodeContactSavedSearchCreateInput: Decoder<ContactSavedSearchCreateInput> = (
  input,
  path = 'request',
) => {
  const read = objectReader(input, ['name', 'criteria'], path);
  const criteria = jsonObject(read('criteria'), `${path}.criteria`);
  if (new TextEncoder().encode(JSON.stringify(criteria)).length > 65_536) {
    return invalid(`${path}.criteria`, 'canonical JSON no greater than 65536 UTF-8 bytes');
  }
  return {
    name: stringValue(read('name'), `${path}.name`, 1, 255),
    criteria,
  };
};

export const decodeContactTagCreateInput: Decoder<ContactTagCreateInput> = (
  input,
  path = 'request',
) => {
  const read = objectReader(input, ['name'], path);
  return { name: stringValue(read('name'), `${path}.name`, 1, 80) };
};

export const decodeContactTaskCreateInput: Decoder<ContactTaskCreateInput> = (
  input,
  path = 'request',
) => {
  const read = objectReader(
    input,
    ['title', 'contact_id', 'description', 'priority', 'due_at'],
    path,
  );
  return {
    title: stringValue(read('title'), `${path}.title`, 1, 255),
    contact_id: positiveInteger(read('contact_id'), `${path}.contact_id`),
    description: stringValue(read('description'), `${path}.description`),
    priority: enumValue(read('priority'), ['low', 'normal', 'high'], `${path}.priority`),
    due_at: nullableRfc3339(read('due_at'), `${path}.due_at`),
  };
};

const decodeContactNoteCreated: Decoder<ContactNoteCreated> = (input, path = 'response') => {
  const read = objectReader(input, ['id', 'body'], path);
  return {
    id: positiveInteger(read('id'), `${path}.id`),
    body: stringValue(read('body'), `${path}.body`),
  };
};

const decodeContactDeleted: Decoder<ContactDeleted> = (input, path = 'response') => {
  const read = objectReader(input, ['deleted', 'id'], path);
  if (read('deleted') !== true) return invalid(`${path}.deleted`, 'literal true');
  return { deleted: true, id: positiveInteger(read('id'), `${path}.id`) };
};

const decodeContactSavedSearchCreated: Decoder<ContactSavedSearchCreated> = (
  input,
  path = 'response',
) => {
  const read = objectReader(input, ['id', 'name', 'criteria'], path);
  return {
    id: positiveInteger(read('id'), `${path}.id`),
    name: stringValue(read('name'), `${path}.name`),
    criteria: canonicalCriteriaText(read('criteria'), `${path}.criteria`),
  };
};

const decodeContactTag: Decoder<ContactTag> = (input, path = 'response') => tagValue(input, path);

const decodeContactTagAssignment: Decoder<ContactTagAssignment> = (
  input,
  path = 'response',
) => {
  const read = objectReader(input, ['contact_id', 'tag_id'], path);
  return {
    contact_id: positiveInteger(read('contact_id'), `${path}.contact_id`),
    tag_id: positiveInteger(read('tag_id'), `${path}.tag_id`),
  };
};

const decodeContactTagRemoval: Decoder<ContactTagRemoval> = (input, path = 'response') => {
  const read = objectReader(input, ['removed', 'contact_id', 'tag_id'], path);
  return {
    removed: booleanValue(read('removed'), `${path}.removed`),
    contact_id: positiveInteger(read('contact_id'), `${path}.contact_id`),
    tag_id: positiveInteger(read('tag_id'), `${path}.tag_id`),
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
  internalWorkspace: (id: number, options?: CommandRequestOptions) => Promise<ContactInternalWorkspace>;
  timeline: (id: number, cursor: string | null, pageSize: number, options?: CommandRequestOptions) => Promise<ContactTimelinePage>;
  section: (id: number, section: Exclude<ContactSectionName, 'timeline'>, page: number, pageSize: number, options?: CommandRequestOptions) => Promise<ContactSectionPage>;
  evidence: (id: number, options?: CommandRequestOptions) => Promise<ContactEvidence>;
  celebrations: (month: number, options?: CommandRequestOptions) => Promise<ContactCelebrations>;
  create: (input: ContactCreateInput, options?: CommandRequestOptions) => Promise<ContactCreated>;
  update: (id: number, input: ContactUpdateInput, options?: CommandRequestOptions) => Promise<ContactCreated>;
  bulk: (input: ContactBulkInput, options?: CommandRequestOptions) => Promise<ContactBulkResult>;
  createNote: (id: number, input: ContactNoteCreateInput, options?: CommandRequestOptions) => Promise<ContactNoteCreated>;
  deleteNote: (id: number, noteId: number, options?: CommandRequestOptions) => Promise<ContactDeleted>;
  createSavedSearch: (id: number, input: ContactSavedSearchCreateInput, options?: CommandRequestOptions) => Promise<ContactSavedSearchCreated>;
  createTag: (input: ContactTagCreateInput, options?: CommandRequestOptions) => Promise<ContactTag>;
  assignTag: (id: number, tagId: number, options?: CommandRequestOptions) => Promise<ContactTagAssignment>;
  removeTag: (id: number, tagId: number, options?: CommandRequestOptions) => Promise<ContactTagRemoval>;
  createTask: (
    input: ContactTaskCreateInput,
    idempotencyKey: string,
    options?: TaskRequestOptions,
  ) => Promise<Task>;
  restoreTask: (
    taskId: number,
    input: TaskLifecycleRequest,
    options?: TaskRequestOptions,
  ) => Promise<Task>;
  artifactBlob: (artifactId: number, options?: CommandRequestOptions) => Promise<Blob>;
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

function sectionPageForRequest(
  input: unknown,
  section: Exclude<ContactSectionName, 'timeline'>,
  expectedPage: number,
  expectedPageSize: number,
  path = 'response',
): ContactSectionPage {
  const decoded = decodeContactSectionPage(input, path);
  if (decoded.page !== expectedPage || decoded.page_size !== expectedPageSize) {
    return invalid(path, 'requested section page identity');
  }
  decoded.rows.forEach((row, index) => {
    const rowPath = `${path}.rows[${index}]`;
    if (row.section !== section) return invalid(`${rowPath}.section`, 'requested section identity');
    const expectedKind = section === 'opportunities' ? 'opportunity'
      : section === 'smart_plans' ? 'smart_plan'
        : section === 'notes' ? 'note'
          : section === 'saved_searches' ? 'saved_search'
            : 'task';
    if (row.value.kind !== expectedKind) {
      return invalid(`${rowPath}.value.kind`, 'requested section occurrence kind');
    }
    if (expectedKind === 'task' && row.value.kind === 'task') {
      const expectedState = section === 'tasks_to_do' ? 'to_do'
        : section === 'tasks_completed' ? 'completed'
          : 'archived';
      if (row.value.state !== expectedState) {
        return invalid(`${rowPath}.value.state`, 'requested task section state');
      }
    }
    if (row.status === 'materialized' && row.entity_type !== expectedKind) {
      return invalid(`${rowPath}.entity_type`, 'requested section materialization type');
    }
  });
  return decoded;
}

export const contactsApi: ContactsApi = {
  directory: async (request, options) => commandJson({
    path: queryPath('/contacts/directory', serializeDirectoryRequest(request)),
    decode: decodeContactDirectoryPage,
    signal: options?.signal,
  }),
  detail: async (id, options) => {
    const contactId = validId(id, 'request.id');
    return commandJson({
      path: `/contacts/${contactId}`,
      decode: (input, path) => {
        const responsePath = path ?? 'response';
        const decoded = decodeContactDetail(input, responsePath);
        if (decoded.contact.id !== contactId) {
          return invalid(`${responsePath}.contact.id`, 'requested contact identity');
        }
        return decoded;
      },
      signal: options?.signal,
    });
  },
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
  internalWorkspace: async (id, options) => {
    const contactId = validId(id, 'request.id');
    return commandJson({
      path: `/contacts/${contactId}/workspace`,
      decode: (input, path) => decodeContactInternalWorkspaceForContact(input, contactId, path),
      signal: options?.signal,
    });
  },
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
    const expectedPage = integer(page, 'request.page', 1);
    const expectedPageSize = integer(pageSize, 'request.page_size', 1, 100);
    const separator = route.includes('?') ? '&' : '?';
    const suffix = `page=${expectedPage}&page_size=${expectedPageSize}`;
    return commandJson({
      path: `/contacts/${validId(id, 'request.id')}/${route}${separator}${suffix}`,
      decode: (input, path) => sectionPageForRequest(
        input,
        section,
        expectedPage,
        expectedPageSize,
        path,
      ),
      signal: options?.signal,
    });
  },
  evidence: async (id, options) => {
    const contactId = validId(id, 'request.id');
    return commandJson({
      path: `/contacts/${contactId}/evidence`,
      decode: (input, path) => {
        const responsePath = path ?? 'response';
        const decoded = decodeContactEvidence(input, responsePath);
        if (decoded.contact_id !== contactId) {
          return invalid(`${responsePath}.contact_id`, 'requested contact identity');
        }
        return decoded;
      },
      signal: options?.signal,
    });
  },
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
  update: async (id, input, options) => {
    const contactId = validId(id, 'request.id');
    return commandJson({
      path: `/contacts/${contactId}`,
      method: 'PATCH',
      body: decodeContactUpdateInput(input),
      decode: (raw, path) => {
        const responsePath = path ?? 'response';
        const decoded = decodeLegacyContact(raw, responsePath);
        if (decoded.id !== contactId) {
          return invalid(`${responsePath}.id`, 'requested contact identity');
        }
        return decoded;
      },
      signal: options?.signal,
    });
  },
  bulk: async (input, options) => commandJson({
    path: '/contacts/bulk',
    method: 'POST',
    body: decodeContactBulkInput(input),
    decode: decodeContactBulkResult,
    signal: options?.signal,
  }),
  createNote: async (id, input, options) => {
    const body = decodeContactNoteCreateInput(input);
    return commandJson({
      path: `/contacts/${validId(id, 'request.id')}/notes`,
      method: 'POST',
      body,
      decode: (raw, path) => {
        const responsePath = path ?? 'response';
        const decoded = decodeContactNoteCreated(raw, responsePath);
        if (decoded.body !== body.body) {
          return invalid(`${responsePath}.body`, 'requested note body');
        }
        return decoded;
      },
      signal: options?.signal,
    });
  },
  deleteNote: async (id, noteId, options) => {
    const expectedNoteId = validId(noteId, 'request.note_id');
    return commandJson({
      path: `/contacts/${validId(id, 'request.id')}/notes/${expectedNoteId}`,
      method: 'DELETE',
      decode: (input, path) => {
        const decoded = decodeContactDeleted(input, path);
        if (decoded.id !== expectedNoteId) return invalid(`${path}.id`, 'requested note identity');
        return decoded;
      },
      signal: options?.signal,
    });
  },
  createSavedSearch: async (id, input, options) => {
    const body = decodeContactSavedSearchCreateInput(input);
    const expectedCriteria = JSON.stringify(body.criteria);
    return commandJson({
      path: `/contacts/${validId(id, 'request.id')}/saved-searches`,
      method: 'POST',
      body,
      decode: (raw, path) => {
        const responsePath = path ?? 'response';
        const decoded = decodeContactSavedSearchCreated(raw, responsePath);
        if (decoded.name !== body.name || decoded.criteria !== expectedCriteria) {
          return invalid(responsePath, 'requested saved search identity and criteria');
        }
        return decoded;
      },
      signal: options?.signal,
    });
  },
  createTag: async (input, options) => {
    const body = decodeContactTagCreateInput(input);
    return commandJson({
      path: '/tags',
      method: 'POST',
      body,
      decode: (raw, path) => {
        const responsePath = path ?? 'response';
        const decoded = decodeContactTag(raw, responsePath);
        if (decoded.name !== body.name) {
          return invalid(`${responsePath}.name`, 'requested tag identity');
        }
        return decoded;
      },
      signal: options?.signal,
    });
  },
  assignTag: async (id, tagId, options) => {
    const contactId = validId(id, 'request.id');
    const expectedTagId = validId(tagId, 'request.tag_id');
    return commandJson({
      path: `/contacts/${contactId}/tags/${expectedTagId}`,
      method: 'POST',
      decode: (input: unknown, path?: string) => {
        const responsePath = path ?? 'response';
        const decoded = decodeContactTagAssignment(input, responsePath);
        if (decoded.contact_id !== contactId || decoded.tag_id !== expectedTagId) {
          return invalid(responsePath, 'requested contact and tag identity');
        }
        return decoded;
      },
      signal: options?.signal,
    });
  },
  removeTag: async (id, tagId, options) => {
    const contactId = validId(id, 'request.id');
    const expectedTagId = validId(tagId, 'request.tag_id');
    return commandJson({
      path: `/contacts/${contactId}/tags/${expectedTagId}`,
      method: 'DELETE',
      decode: (input: unknown, path?: string) => {
        const responsePath = path ?? 'response';
        const decoded = decodeContactTagRemoval(input, responsePath);
        if (decoded.contact_id !== contactId || decoded.tag_id !== expectedTagId) {
          return invalid(responsePath, 'requested contact and tag identity');
        }
        return decoded;
      },
      signal: options?.signal,
    });
  },
  createTask: async (input, idempotencyKey, options) => {
    const body = decodeContactTaskCreateInput(input);
    return createLifecycleTask(body, idempotencyKey, options);
  },
  restoreTask: (taskId, input, options) => restoreLifecycleTask(taskId, input, options),
  artifactBlob: async (artifactId, options) => commandBlob({
    path: `/archive/artifacts/${validId(artifactId, 'request.artifact_id')}/content`,
    signal: options?.signal,
  }),
};
