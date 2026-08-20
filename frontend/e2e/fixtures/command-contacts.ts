import type { Request } from '@playwright/test';
import { createHash } from 'node:crypto';
import type {
  ContactCapturePosition,
  ContactCelebrations,
  ContactDetail,
  ContactDirectoryPage,
  ContactDirectoryRow,
  ContactEvidence,
  ContactInternalWorkspace,
  ContactMaterialization,
  ContactSectionName,
  ContactSectionPage,
  ContactTimelinePage,
  ContactWorkspaceSummary,
} from '../../src/lib/command/contacts';

const FIXED_AT = '2026-08-12T12:00:00.000Z';
const ACTIVITY_AT = '2026-08-12T13:00:00.000Z';
const CONTACT_COUNT = 366;
const RECOVERED_COUNT = 317;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SECTION_NAMES: readonly ContactSectionName[] = [
  'timeline', 'opportunities', 'smart_plans', 'notes', 'saved_searches',
  'tasks_to_do', 'tasks_completed', 'tasks_archived',
];

export type ContactsFixtureResponse = Readonly<{
  status: number;
  body?: unknown;
  binaryBody?: Buffer;
  headers?: Readonly<Record<string, string>>;
}>;

type MutableContactState = {
  rows: ContactDirectoryRow[];
  details: Map<number, ContactDetail>;
  workspaces: Map<number, ContactInternalWorkspace>;
  tags: { id: number; name: string }[];
  nextContactId: number;
  nextNoteId: number;
  nextSearchId: number;
  nextTagId: number;
  nextTaskId: number;
  nextActivityId: number;
  taskCreates: Map<string, Readonly<{ fingerprint: string; task: Record<string, unknown> }>>;
  createdAt: Map<number, string>;
  updatedAt: Map<number, string>;
};

export type CommandContactsFixtureState = MutableContactState;

function nameFor(id: number): readonly [string, string] {
  if (id === 1) return ['Avery', 'Lake'];
  if (id === 2) return ['Morgan', 'Hill'];
  if (id === 3) return ['Casey', 'Pine'];
  if (id === 4) return ['Riley', 'Stone'];
  return [`Synthetic ${String(id).padStart(3, '0')}`, 'Contact'];
}

function rowFor(id: number): ContactDirectoryRow {
  const [firstName, lastName] = nameFor(id);
  const recovered = id <= RECOVERED_COUNT;
  const reviewedOverlap = id <= 2;
  const leadBacked = reviewedOverlap || !recovered;
  const birthday = id === 1
    ? { month: 8, day: 18, year: null, year_quality: 'yearless' as const, origin: 'recovered' as const }
    : id === 2
      ? { month: 8, day: 20, year: null, year_quality: 'sentinel' as const, origin: 'recovered' as const }
      : null;
  const anniversary = id === 3
    ? { month: 8, day: 23, year: 2022, year_quality: 'verified' as const, origin: 'recovered' as const }
    : null;
  return {
    id,
    first_name: firstName,
    last_name: lastName,
    display_name: `${firstName} ${lastName}`,
    primary_email: id % 5 === 0 ? null : `contact-${id}@example.test`,
    primary_phone: id % 7 === 0 ? null : `+1555${String(id).padStart(7, '0')}`,
    stage: id === 9 ? 'bespoke advisory' : id % 4 === 0 ? 'client' : id % 3 === 0 ? 'nurture' : 'lead',
    lead_backed: leadBacked,
    origins: reviewedOverlap ? ['lead_backed', 'recovered'] : recovered ? ['recovered'] : ['lead_backed', 'legacy_only'],
    sources: reviewedOverlap
      ? ['kw_command', 'legacy_lead']
      : recovered ? ['kw_command'] : ['legacy_lead'],
    health_score: recovered ? 50 + (id % 51) : null,
    last_contacted_at: recovered && id % 3 === 0 ? FIXED_AT : null,
    last_interaction_at: recovered && id % 4 === 0 ? FIXED_AT : null,
    owner: { role: 'owner', provider_actor_id: 'owner-sws', display_name: 'Brandon Sweeney' },
    assignee: id % 2 === 0
      ? { role: 'assignee', provider_actor_id: 'agent-sws', display_name: 'SWS Team' }
      : null,
    tags: id <= 3 ? [{ id: 1, name: 'Priority' }] : [],
    birthday,
    anniversary,
    evidence_quality: null,
  };
}

function syntheticHash(id: number): string {
  return createHash('sha256').update(`synthetic-command-source:${id}`, 'utf8').digest('hex');
}

function detailFor(row: ContactDirectoryRow): ContactDetail {
  const recovered = row.id <= RECOVERED_COUNT;
  return {
    contact: row,
    lead_id: row.lead_backed ? 10_000 + row.id : null,
    recovered_profile: recovered ? {
      legal_name: row.display_name,
      preferred_name: row.first_name,
      description: row.id === 1 ? 'Synthetic recovered profile for deterministic browser acceptance.' : null,
      company: row.id === 1 ? 'Sold With Sweeney client' : null,
      title: null,
      lead_source: 'Command archive',
      account_name: null,
      birthday: row.birthday,
      anniversary: row.anniversary,
    } : null,
    addresses: recovered ? [{
      id: 20_000 + row.id,
      address_type: 'observed',
      formatted: `${row.id} Example Avenue, Synthetic City`,
      latitude: null,
      longitude: null,
      source_record_id: 30_000 + row.id,
    }] : [],
    ownership: [row.owner, row.assignee].filter((actor): actor is NonNullable<typeof actor> => actor !== null),
    tags: row.tags,
  };
}

function workspaceFor(row: ContactDirectoryRow): ContactInternalWorkspace {
  return {
    contact: {
      id: row.id,
      first_name: row.first_name,
      last_name: row.last_name,
      email: row.primary_email,
      phone: row.primary_phone,
      lead_id: row.lead_backed ? 10_000 + row.id : null,
      birthday: null,
      anniversary: null,
      stage: row.stage,
    },
    timeline: [],
    tasks: row.id === 1 ? [
      { id: 101, title: 'SWS valuation follow-up', contact_id: 1, description: 'Internal only.', priority: 'high', due_at: '2026-08-20T14:00:00.000Z', status: 'open' },
      { id: 102, title: 'Completed consultation', contact_id: 1, description: '', priority: 'normal', due_at: null, status: 'completed' },
      { id: 103, title: 'Archived reminder', contact_id: 1, description: '', priority: 'low', due_at: null, status: 'archived' },
    ] : [],
    notes: row.id === 1 ? [{ id: 111, contact_id: 1, body: 'Internal SWS note', created_at: FIXED_AT, updated_at: FIXED_AT }] : [],
    smart_plans: row.id === 1 ? [{ id: 121, plan_id: 22, status: 'active' }] : [],
    opportunities: row.id === 1 ? [{ id: 131, name: 'Internal listing review', stage: 'active', value_cents: 51000000, role: 'seller' }] : [],
    saved_searches: row.id === 1 ? [{ id: 141, name: 'Internal search', criteria: '{"beds":2}' }] : [],
    bookings: row.id === 1 ? [{ id: 151, meeting_type: 'consultation', context: 'Listing strategy', scheduled_at: '2026-09-02T14:00:00.000Z', location: 'SWS office', notes: '' }] : [],
    tags: row.tags,
  };
}

export function createCommandContactsFixtureState(): CommandContactsFixtureState {
  const rows = Array.from({ length: CONTACT_COUNT }, (_, index) => rowFor(index + 1));
  return {
    rows,
    details: new Map(rows.map((row) => [row.id, detailFor(row)])),
    workspaces: new Map(rows.map((row) => [row.id, workspaceFor(row)])),
    tags: [{ id: 1, name: 'Priority' }],
    nextContactId: 367,
    nextNoteId: 500,
    nextSearchId: 600,
    nextTagId: 2,
    nextTaskId: 700,
    nextActivityId: 800,
    taskCreates: new Map(),
    createdAt: new Map(rows.map((row) => [row.id, new Date(Date.parse(FIXED_AT) - row.id * 60_000).toISOString()])),
    updatedAt: new Map(rows.map((row) => [row.id, new Date(Date.parse(FIXED_AT) - row.id * 30_000).toISOString()])),
  };
}

function fail(detail: string, status = 500): ContactsFixtureResponse {
  const safeDetail = detail.replace(/([?&][^=&\s:]+)=([^&\s:]*)/g, '$1=<redacted>');
  return { status, body: { detail: `Unexpected Command fixture request: ${safeDetail}` } };
}

function isFixtureResponse(value: Record<string, unknown> | ContactsFixtureResponse): value is ContactsFixtureResponse {
  return typeof Reflect.get(value, 'status') === 'number';
}

function jsonBody(request: Request): Record<string, unknown> | ContactsFixtureResponse {
  let value: unknown;
  try {
    value = request.postDataJSON();
  } catch {
    return fail('malformed JSON body');
  }
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : fail('JSON body must be an object');
}

function exactKeys(body: Record<string, unknown>, allowed: readonly string[], required: readonly string[] = allowed): boolean {
  const keys = Object.keys(body).sort();
  return keys.every((key) => allowed.includes(key))
    && required.every((key) => keys.includes(key));
}

function optionalString(value: unknown, max: number, nullable = true): boolean {
  return value === undefined || (nullable && value === null) || (typeof value === 'string' && Array.from(value).length <= max);
}

function dateValue(value: unknown): boolean {
  if (value === undefined || value === null) return true;
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  if (Number(value.slice(0, 4)) < 1) return false;
  const date = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value;
}

function canonicalInteger(raw: string | null, minimum: number, maximum = Number.MAX_SAFE_INTEGER): boolean {
  if (raw === null || !/^(?:0|[1-9]\d*)$/.test(raw)) return false;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= minimum && value <= maximum && String(value) === raw;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (typeof value === 'object' && value !== null) {
    return `{${Object.entries(value as Record<string, unknown>).sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => `${JSON.stringify(key)}:${canonicalJson(child)}`).join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

function finiteJsonValue(value: unknown): boolean {
  if (typeof value === 'number') return Number.isFinite(value);
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (Array.isArray(value)) return value.every(finiteJsonValue);
  return typeof value === 'object'
    && Object.values(value as Record<string, unknown>).every(finiteJsonValue);
}

function rfc3339Value(value: unknown): boolean {
  if (value === null) return true;
  if (typeof value !== 'string') return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  if (!match) return false;
  return dateValue(`${match[1]}-${match[2]}-${match[3]}`)
    && Number(match[4]) <= 23 && Number(match[5]) <= 59 && Number(match[6]) <= 59
    && Number(match[7] ?? 0) <= 23 && Number(match[8] ?? 0) <= 59;
}

function timelineCursorValue(value: string): boolean {
  if (!/^[A-Za-z0-9_-]+$/.test(value) || value.includes('=')) return false;
  try {
    const raw = Buffer.from(value, 'base64url');
    if (raw.toString('base64url') !== value) return false;
    const text = raw.toString('utf8');
    const parsed = JSON.parse(text) as unknown;
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return false;
    const cursor = parsed as Record<string, unknown>;
    if (JSON.stringify(Object.keys(cursor)) !== JSON.stringify(['v', 'n', 't', 'o', 'i']) || JSON.stringify(cursor) !== text
      || cursor.v !== 1 || typeof cursor.n !== 'number' || !Number.isInteger(cursor.n) || ![0, 1].includes(cursor.n)
      || typeof cursor.o !== 'number' || !Number.isInteger(cursor.o) || ![0, 1, 2, 3].includes(cursor.o)
      || typeof cursor.i !== 'number' || !Number.isSafeInteger(cursor.i) || cursor.i < 1) return false;
    if (cursor.n === 1) return cursor.t === null;
    if (typeof cursor.t !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/.test(cursor.t)) return false;
    const parsedDate = new Date(cursor.t);
    return !Number.isNaN(parsedDate.valueOf()) && parsedDate.toISOString() === `${cursor.t.slice(0, 23)}Z`;
  } catch {
    return false;
  }
}

function validTimelineQuery(url: URL, method: string): boolean {
  const keys = [...url.searchParams.keys()];
  const cursor = url.searchParams.get('cursor');
  const pageSize = url.searchParams.get('page_size');
  return method === 'GET'
    && (keys.length === 1 || (keys.length === 2 && keys[0] === 'cursor'))
    && keys.at(-1) === 'page_size'
    && url.searchParams.getAll('cursor').length <= 1
    && url.searchParams.getAll('page_size').length === 1
    && (cursor === null || timelineCursorValue(cursor))
    && canonicalInteger(pageSize, 1, 100);
}

function validContactFields(body: Record<string, unknown>, create: boolean): boolean {
  return optionalString(body.first_name, 120, false)
    && (!create || (typeof body.first_name === 'string' && body.first_name.trim().length > 0))
    && optionalString(body.last_name, 120, false)
    && optionalString(body.email, 255)
    && optionalString(body.phone, 50)
    && optionalString(body.stage, 50, false)
    && (body.stage === undefined || (typeof body.stage === 'string' && body.stage.trim().length > 0))
    && dateValue(body.birthday)
    && dateValue(body.anniversary);
}

function updateContactState(
  state: CommandContactsFixtureState,
  id: number,
  update: (row: ContactDirectoryRow) => ContactDirectoryRow,
  touchUpdated = true,
): ContactDirectoryRow | null {
  const index = state.rows.findIndex((row) => row.id === id);
  if (index < 0) return null;
  const next = update(state.rows[index]!);
  state.rows[index] = next;
  if (touchUpdated) state.updatedAt.set(id, FIXED_AT);
  const detail = state.details.get(id);
  const workspace = state.workspaces.get(id);
  if (detail) state.details.set(id, { ...detail, contact: next, tags: next.tags, ownership: [next.owner, next.assignee].filter((actor): actor is NonNullable<typeof actor> => actor !== null) });
  if (workspace) {
    state.workspaces.set(id, {
      ...workspace,
      contact: {
        ...workspace.contact,
        first_name: next.first_name,
        last_name: next.last_name,
        email: next.primary_email,
        phone: next.primary_phone,
        stage: next.stage,
      },
      tags: next.tags,
    });
  }
  return next;
}

function canonicalDirectoryQuery(url: URL): string | null {
  const order = [
    'query', 'stage', 'owner_actor_id', 'assignee_actor_id', 'tag', 'source', 'origin',
    'health_min', 'health_max', 'birthday_month', 'anniversary_month', 'smart_view',
    'sort', 'direction', 'page', 'page_size',
  ] as const;
  let previousIndex = -1;
  for (const [key] of url.searchParams) {
    const index = order.indexOf(key as typeof order[number]);
    if (index < 0) return `unknown query key ${key}`;
    if (index < previousIndex) return 'query keys must use canonical order';
    previousIndex = index;
  }
  for (const key of order) {
    if (!['tag', 'source', 'origin'].includes(key) && url.searchParams.getAll(key).length > 1) return `duplicate query key ${key}`;
  }
  const tags = url.searchParams.getAll('tag');
  const tagNumbers = tags.map(Number);
  if (tags.some((tag) => !canonicalInteger(tag, 1))
    || tagNumbers.some((tag, index) => index > 0 && tagNumbers[index - 1]! >= tag)) {
    return 'tag must be sorted unique positive integers';
  }
  const allowedSources = ['internal_crm', 'kw_command', 'legacy_lead'];
  const sources = url.searchParams.getAll('source');
  if (sources.some((value) => !allowedSources.includes(value))
    || sources.some((value, index) => index > 0 && sources[index - 1]! >= value)) return 'source must be canonical';
  const allowedOrigins = ['internal_only', 'lead_backed', 'legacy_only', 'recovered'];
  const origins = url.searchParams.getAll('origin');
  if (origins.some((value) => !allowedOrigins.includes(value))
    || origins.some((value, index) => index > 0 && origins[index - 1]! >= value)) return 'origin must be canonical';
  const boundedText = (key: string, maximum: number) => {
    const value = url.searchParams.get(key);
    return value !== null && (value.trim() !== value || value.length < 1 || Array.from(value).length > maximum);
  };
  if (boundedText('query', 200) || boundedText('stage', 50)
    || boundedText('owner_actor_id', 255) || boundedText('assignee_actor_id', 255)) return 'invalid bounded text query';
  const integerInRange = (key: string, minimum: number, maximum: number) => {
    const raw = url.searchParams.get(key);
    if (raw === null) return true;
    const value = Number(raw);
    return canonicalInteger(raw, minimum, maximum) && Number.isSafeInteger(value);
  };
  if (!integerInRange('health_min', 0, 100) || !integerInRange('health_max', 0, 100)
    || !integerInRange('birthday_month', 1, 12) || !integerInRange('anniversary_month', 1, 12)
    || !integerInRange('page', 1, Number.MAX_SAFE_INTEGER) || !integerInRange('page_size', 1, 100)) return 'invalid integer query';
  const healthMin = Number(url.searchParams.get('health_min') ?? '0');
  const healthMax = Number(url.searchParams.get('health_max') ?? '100');
  if (healthMin > healthMax) return 'health_min must not exceed health_max';
  const smartView = url.searchParams.get('smart_view');
  if (smartView !== null && !['all', 'never_contacted', 'recently_active', 'birthdays_this_month', 'anniversaries_this_month'].includes(smartView)) return 'invalid smart_view';
  const sort = url.searchParams.get('sort');
  if (sort !== null && !['name', 'stage', 'health_score', 'last_contacted_at', 'last_interaction_at', 'created_at', 'updated_at'].includes(sort)) return 'invalid sort';
  const direction = url.searchParams.get('direction');
  if (direction !== null && !['asc', 'desc'].includes(direction)) return 'invalid direction';
  return null;
}

function directoryUniverse(state: CommandContactsFixtureState, url: URL): ContactDirectoryRow[] | ContactsFixtureResponse {
  const invalid = canonicalDirectoryQuery(url);
  if (invalid) return fail(`GET ${url.pathname}${url.search}: ${invalid}`);
  const sort = url.searchParams.get('sort') ?? 'name';
  const direction = url.searchParams.get('direction') ?? 'asc';
  let rows = [...state.rows];
  const query = url.searchParams.get('query')?.trim().toLowerCase();
  if (query) rows = rows.filter((row) => {
    const profile = state.details.get(row.id)?.recovered_profile;
    return [row.display_name, row.primary_email, row.primary_phone, profile?.legal_name, profile?.preferred_name, profile?.company, profile?.title]
      .some((value) => value?.toLowerCase().includes(query));
  });
  const stage = url.searchParams.get('stage');
  if (stage) rows = rows.filter((row) => row.stage === stage);
  const owner = url.searchParams.get('owner_actor_id');
  if (owner) rows = rows.filter((row) => row.owner?.provider_actor_id === owner);
  const assignee = url.searchParams.get('assignee_actor_id');
  if (assignee) rows = rows.filter((row) => row.assignee?.provider_actor_id === assignee);
  const origins = url.searchParams.getAll('origin');
  if (origins.length) rows = rows.filter((row) => origins.some((origin) => row.origins.includes(origin as never)));
  const sources = url.searchParams.getAll('source');
  if (sources.length) rows = rows.filter((row) => sources.some((source) => row.sources.includes(source as never)));
  const tags = url.searchParams.getAll('tag').map(Number);
  if (tags.length) rows = rows.filter((row) => tags.every((tag) => row.tags.some((candidate) => candidate.id === tag)));
  const healthMin = url.searchParams.has('health_min') ? Number(url.searchParams.get('health_min')) : null;
  const healthMax = url.searchParams.has('health_max') ? Number(url.searchParams.get('health_max')) : null;
  if (healthMin !== null || healthMax !== null) rows = rows.filter((row) => row.health_score !== null && (healthMin === null || row.health_score >= healthMin) && (healthMax === null || row.health_score <= healthMax));
  const birthdayMonth = url.searchParams.get('birthday_month');
  if (birthdayMonth) rows = rows.filter((row) => row.birthday?.month === Number(birthdayMonth));
  const anniversaryMonth = url.searchParams.get('anniversary_month');
  if (anniversaryMonth) rows = rows.filter((row) => row.anniversary?.month === Number(anniversaryMonth));
  const smartView = url.searchParams.get('smart_view');
  if (smartView === 'never_contacted') rows = rows.filter((row) => {
    const timelineEvidence = evidenceFor(row.id).section_matrix.find((entry) => entry.section === 'timeline');
    return row.stage === 'lead' && timelineEvidence?.capture_quality === 'complete' && timelineEvidence.is_empty
      && row.last_contacted_at === null && row.last_interaction_at === null;
  });
  if (smartView === 'recently_active') {
    const cutoff = Date.parse(FIXED_AT) - 30 * 24 * 60 * 60 * 1000;
    rows = rows.filter((row) => row.last_interaction_at !== null && Date.parse(row.last_interaction_at) >= cutoff && Date.parse(row.last_interaction_at) <= Date.parse(FIXED_AT));
  }
  if (smartView === 'birthdays_this_month') rows = rows.filter((row) => row.birthday?.month === 8);
  if (smartView === 'anniversaries_this_month') rows = rows.filter((row) => row.anniversary?.month === 8);
  const nullableCompare = (left: string | number | null, right: string | number | null): number => {
    if (left === null && right === null) return 0;
    if (left === null) return 1;
    if (right === null) return -1;
    const raw = typeof left === 'number' && typeof right === 'number'
      ? left - right
      : String(left).localeCompare(String(right));
    return direction === 'desc' ? -raw : raw;
  };
  const comparison = (left: ContactDirectoryRow, right: ContactDirectoryRow) => {
    if (sort === 'name') {
      const nameValue = left.last_name.localeCompare(right.last_name)
        || left.first_name.localeCompare(right.first_name);
      return (direction === 'desc' ? -nameValue : nameValue) || (direction === 'desc' ? right.id - left.id : left.id - right.id);
    }
    const value = sort === 'stage' ? nullableCompare(left.stage, right.stage)
      : sort === 'health_score' ? nullableCompare(left.health_score, right.health_score)
        : sort === 'last_contacted_at' ? nullableCompare(left.last_contacted_at, right.last_contacted_at)
          : sort === 'last_interaction_at' ? nullableCompare(left.last_interaction_at, right.last_interaction_at)
            : sort === 'created_at' ? nullableCompare(state.createdAt.get(left.id) ?? null, state.createdAt.get(right.id) ?? null)
              : nullableCompare(state.updatedAt.get(left.id) ?? null, state.updatedAt.get(right.id) ?? null);
    const tieName = left.last_name.localeCompare(right.last_name) || left.first_name.localeCompare(right.first_name) || left.id - right.id;
    return value || (direction === 'desc' ? -tieName : tieName);
  };
  rows.sort(comparison);
  return rows;
}

function directoryPage(state: CommandContactsFixtureState, url: URL): ContactDirectoryPage | ContactsFixtureResponse {
  const rowsOrFailure = directoryUniverse(state, url);
  if ('status' in rowsOrFailure) return rowsOrFailure;
  const page = Number(url.searchParams.get('page') ?? '1');
  const pageSize = Number(url.searchParams.get('page_size') ?? '50');
  if (pageSize < 1 || pageSize > 100) return fail(`GET ${url.pathname}${url.search}: unsupported fixture page_size`);
  const rows = rowsOrFailure;
  const total = rows.length;
  return {
    rows: rows.slice((page - 1) * pageSize, page * pageSize),
    total,
    page,
    page_size: pageSize,
    page_count: total === 0 ? 0 : Math.ceil(total / pageSize),
    sort: (url.searchParams.get('sort') ?? 'name') as ContactDirectoryPage['sort'],
    direction: (url.searchParams.get('direction') ?? 'asc') as ContactDirectoryPage['direction'],
  };
}

function sectionSourceId(contactId: number, section: ContactSectionName): number {
  return 100_000 + contactId * 10 + SECTION_NAMES.indexOf(section);
}

function materialization(contactId: number, section: Exclude<ContactSectionName, 'timeline'>): ContactMaterialization {
  const value = section === 'opportunities'
    ? { kind: 'opportunity' as const, title: 'Recovered seller opportunity', stage: 'consultation', value_cents: 42500000 }
    : section === 'smart_plans'
      ? { kind: 'smart_plan' as const, title: 'Recovered quarterly touch', status: 'active' }
      : section === 'notes'
        ? { kind: 'note' as const, title: 'Recovered note', body: 'Observed source-only note.' }
        : section === 'saved_searches'
          ? { kind: 'saved_search' as const, title: 'Recovered search', criteria_summary: ['2+ bedrooms'] }
          : { kind: 'task' as const, title: `Recovered ${section.replace('tasks_', '')} task`, description: 'Observed source-only task.', state: section.replace('tasks_', '') as 'to_do' | 'completed' | 'archived', due_at: null };
  return {
    status: section === 'opportunities' ? 'materialized' : 'source_only',
    source_record_id: sectionSourceId(contactId, section),
    source_key_hash: syntheticHash(sectionSourceId(contactId, section)),
    section,
    occurrence_ordinal: 1,
    capture_quality: section === 'saved_searches' ? 'partial' : 'complete',
    captured_at: FIXED_AT,
    value,
    ...(section === 'opportunities' ? { entity_type: 'opportunity' as const, entity_id: 131 } : {}),
  } as ContactMaterialization;
}

function sectionPage(section: Exclude<ContactSectionName, 'timeline'>, page: number, pageSize: number, contactId: number): ContactSectionPage {
  const rows = contactId === 1 && page === 1 ? [materialization(contactId, section)] : [];
  const total = contactId === 1 ? 1 : 0;
  return { rows, total, page, page_size: pageSize, page_count: total ? 1 : 0 };
}

function recordActivity(state: CommandContactsFixtureState, contactId: number, kind: string, summary: string): void {
  const workspace = state.workspaces.get(contactId);
  if (!workspace) return;
  const activity = { id: state.nextActivityId++, kind, summary, created_at: ACTIVITY_AT };
  state.workspaces.set(contactId, { ...workspace, timeline: [activity, ...workspace.timeline] });
}

function timeline(state: CommandContactsFixtureState, contactId: number): ContactTimelinePage {
  const internalRows = (state.workspaces.get(contactId)?.timeline ?? []).map((activity) => ({
    key: `activity:${activity.id}`,
    origin: 'internal_crm' as const,
    kind: activity.kind,
    title: activity.summary,
    body: null,
    outcome: null,
    occurred_at: activity.created_at,
    source_record_id: null,
    entity_type: 'activity',
    entity_id: activity.id,
  }));
  return {
    rows: [...internalRows, ...(contactId === 1 ? [{
      key: 'activity:1', origin: 'recovered', kind: 'call', title: 'Recovered discovery call',
      body: 'Synthetic observed timeline evidence.', outcome: 'Follow up', occurred_at: FIXED_AT,
      source_record_id: sectionSourceId(contactId, 'timeline'), entity_type: 'activity', entity_id: 1,
    } as const] : [])],
    next_cursor: null,
    has_more: false,
  };
}

function evidenceFor(contactId: number): ContactEvidence {
  const recovered = contactId <= RECOVERED_COUNT;
  const sectionMatrix = recovered ? SECTION_NAMES.map((section) => ({
    capture_position_id: 40_000 + contactId,
    section,
    source_record_id: sectionSourceId(contactId, section),
    capture_quality: contactId === 1 && section === 'saved_searches' ? 'partial' as const : 'complete' as const,
    row_count: contactId === 1 ? 1 : 0,
    is_empty: contactId !== 1,
    limitation_codes: contactId === 1 && section === 'saved_searches' ? ['partial_capture'] : [],
  })) : [];
  const sources = recovered ? [
    {
      source_record_id: 30_000 + contactId,
      record_kind: 'contact_profile',
      evidence_level: 'observed_record' as const,
      capture_quality: contactId === 1 ? 'partial' as const : 'complete' as const,
      captured_at: FIXED_AT,
      artifacts: contactId === 1 ? [{ artifact_id: 55, artifact_type: 'binary', sha256: 'f51404e9019f13676d2964666b2544b4372428775fec0798c6185293e6b657f5', size_bytes: 27, content_href: '/api/v1/command/archive/artifacts/55/content' }] : [],
    },
    ...SECTION_NAMES.map((section) => ({
      source_record_id: sectionSourceId(contactId, section),
      record_kind: section,
      evidence_level: 'rendered_occurrence' as const,
      capture_quality: contactId === 1 && section === 'saved_searches' ? 'partial' as const : 'complete' as const,
      captured_at: FIXED_AT,
      artifacts: [],
    })),
  ].sort((left, right) => left.source_record_id - right.source_record_id) : [];
  const positions: readonly ContactCapturePosition[] = recovered ? [{
    capture_position_id: 40_000 + contactId,
    capture_ordinal: contactId,
    source_record_id: 30_000 + contactId,
    capture_quality: contactId === 1 ? 'partial' : 'complete',
    sections: sectionMatrix,
  }] : [];
  return {
    contact_id: contactId,
    provider_contact_rows: 317,
    resolved_provider_identities: 317,
    coalesced_aliases: 0,
    lead_backed_contacts: 51,
    reviewed_overlaps: 2,
    legacy_only_contacts: 49,
    capture_positions: positions,
    section_matrix: sectionMatrix,
    sources,
    capture_quality: recovered ? (contactId === 1 ? 'partial' : 'complete') : 'limitation',
  };
}

function summaryFor(workspace: ContactInternalWorkspace): ContactWorkspaceSummary {
  return {
    open_tasks: workspace.tasks.filter((row) => row.status === 'open').length,
    completed_tasks: workspace.tasks.filter((row) => row.status === 'completed').length,
    archived_tasks: workspace.tasks.filter((row) => row.status === 'archived').length,
    active_smart_plans: workspace.smart_plans.length,
    opportunities: workspace.opportunities.length,
    notes: workspace.notes.length,
    saved_searches: workspace.saved_searches.length,
    bookings: workspace.bookings.length,
  };
}

function celebrations(state: CommandContactsFixtureState, month: number): ContactCelebrations {
  return {
    birthdays: state.rows.filter((row) => row.birthday?.month === month).map((row) => ({
      contact_id: row.id, display_name: row.display_name, kind: 'birthday' as const,
      month: row.birthday!.month, day: row.birthday!.day, year: row.birthday!.year,
      year_quality: row.birthday!.year_quality, origin: row.birthday!.origin,
    })),
    anniversaries: state.rows.filter((row) => row.anniversary?.month === month).map((row) => ({
      contact_id: row.id, display_name: row.display_name, kind: 'anniversary' as const,
      month: row.anniversary!.month, day: row.anniversary!.day, year: row.anniversary!.year,
      year_quality: row.anniversary!.year_quality, origin: row.anniversary!.origin,
    })),
  };
}

export function handleCommandContactsRequest(
  state: CommandContactsFixtureState,
  request: Request,
  url: URL,
): ContactsFixtureResponse | null {
  const method = request.method();
  const path = url.pathname.replace('/api/v1/command', '') || '/';
  if (path === '/contacts/directory') {
    if (method !== 'GET') return fail(`${method} ${path}`);
    const response = directoryPage(state, url);
    return 'status' in response ? response : { status: 200, body: response };
  }
  if (path === '/celebrations') {
    const month = url.searchParams.get('month');
    if (method !== 'GET' || url.searchParams.size !== 1 || url.searchParams.getAll('month').length !== 1 || !canonicalInteger(month, 1, 12)) return fail(`${method} ${path}${url.search}`);
    return { status: 200, body: celebrations(state, Number(month)) };
  }
  if (path === '/contacts/bulk') {
    if (method !== 'POST' || url.search.length > 0) return fail(`${method} ${path}${url.search}`);
    const body = jsonBody(request);
    if (isFixtureResponse(body) || !exactKeys(body, ['contact_ids', 'action'])) return isFixtureResponse(body) ? body : fail('invalid bulk body');
    const ids = body.contact_ids;
    const action = body.action;
    if (!Array.isArray(ids) || ids.length === 0 || ids.length > 200 || ids.some((id) => !Number.isInteger(id) || Number(id) < 1) || ids.some((id, index) => index > 0 && Number(ids[index - 1]) >= Number(id))) return fail('bulk contact_ids must be 1..200 sorted unique integers');
    if (typeof action !== 'object' || action === null || Array.isArray(action)) return fail('invalid bulk action');
    const actionObject = action as Record<string, unknown>;
    if (ids.some((id) => !state.rows.some((row) => row.id === id))) return { status: 409, body: { detail: 'Bulk selection is stale' } };
    if (actionObject.action === 'set_stage' && exactKeys(actionObject, ['action', 'stage']) && typeof actionObject.stage === 'string' && actionObject.stage.trim().length > 0 && Array.from(actionObject.stage).length <= 50) {
      const changed = ids.filter((id) => state.rows.find((row) => row.id === id)?.stage !== actionObject.stage);
      changed.forEach((id) => {
        updateContactState(state, id, (row) => ({ ...row, stage: actionObject.stage as string }));
      });
      return { status: 200, body: { requested_contact_ids: ids, actioned_contact_ids: changed, action: actionObject.action } };
    }
    if ((actionObject.action === 'add_tag' || actionObject.action === 'remove_tag') && exactKeys(actionObject, ['action', 'tag_id']) && Number.isSafeInteger(actionObject.tag_id) && Number(actionObject.tag_id) > 0) {
      const tag = state.tags.find((candidate) => candidate.id === actionObject.tag_id);
      if (!tag) return { status: 409, body: { detail: 'Bulk tag is stale' } };
      const changed = ids.filter((id) => {
        const assigned = state.rows.find((row) => row.id === id)?.tags.some((candidate) => candidate.id === tag.id) ?? false;
        return actionObject.action === 'add_tag' ? !assigned : assigned;
      });
      changed.forEach((id) => {
        updateContactState(state, id, (row) => ({
          ...row,
          tags: actionObject.action === 'add_tag'
            ? (row.tags.some((candidate) => candidate.id === tag.id) ? row.tags : [...row.tags, tag])
            : row.tags.filter((candidate) => candidate.id !== tag.id),
        }), false);
      });
      return { status: 200, body: { requested_contact_ids: ids, actioned_contact_ids: changed, action: actionObject.action } };
    }
    return fail('unsupported bulk action body');
  }
  if (path === '/contacts') {
    if (method === 'GET') {
      const keys = [...url.searchParams.keys()];
      const limit = Number(url.searchParams.get('limit'));
      const offset = Number(url.searchParams.get('offset'));
      const expectedKeys = ['limit', 'offset', ...(url.searchParams.has('query') ? ['query'] : []), ...(url.searchParams.has('stage') ? ['stage'] : [])];
      const query = url.searchParams.get('query');
      const stage = url.searchParams.get('stage');
      if (keys.length !== expectedKeys.length || keys.some((key, index) => key !== expectedKeys[index])
        || keys.some((key) => url.searchParams.getAll(key).length !== 1)
        || !canonicalInteger(url.searchParams.get('limit'), 1, 100) || !canonicalInteger(url.searchParams.get('offset'), 0)
        || (query !== null && (query.length === 0 || query !== query.trim()))
        || stage === '') return fail(`${method} ${path}${url.search}`);
      const needle = query?.toLowerCase() ?? null;
      const filtered = state.rows
        .filter((row) => (!needle || [row.first_name, row.last_name, row.primary_email, row.primary_phone].some((value) => value?.toLowerCase().includes(needle))) && (stage === null || row.stage === stage))
        .sort((left, right) => (state.createdAt.get(right.id) ?? '').localeCompare(state.createdAt.get(left.id) ?? '') || right.id - left.id);
      return { status: 200, body: filtered.slice(offset, offset + limit).map((row) => ({
        id: row.id,
        first_name: row.first_name,
        last_name: row.last_name,
        email: row.primary_email,
        phone: row.primary_phone,
        lead_id: row.lead_backed ? 10_000 + row.id : null,
        birthday: state.workspaces.get(row.id)?.contact.birthday ?? null,
        anniversary: state.workspaces.get(row.id)?.contact.anniversary ?? null,
        stage: row.stage,
      })) };
    }
    if (method !== 'POST' || url.search.length > 0) return null;
    if (request.postData() === null) return fail(`${method} ${path}`);
    const body = jsonBody(request);
    const allowed = ['first_name', 'last_name', 'email', 'phone', 'stage', 'birthday', 'anniversary'];
    if (isFixtureResponse(body) || !exactKeys(body, allowed, ['first_name']) || !validContactFields(body, true)) return isFixtureResponse(body) ? body : fail('invalid create contact body');
    const id = state.nextContactId++;
    const legacy = {
      id,
      first_name: String(body.first_name),
      last_name: typeof body.last_name === 'string' ? body.last_name : '',
      email: typeof body.email === 'string' ? body.email : null,
      phone: typeof body.phone === 'string' ? body.phone : null,
      lead_id: null,
      birthday: typeof body.birthday === 'string' ? body.birthday : null,
      anniversary: typeof body.anniversary === 'string' ? body.anniversary : null,
      stage: typeof body.stage === 'string' ? body.stage : 'lead',
    };
    const celebration = (raw: string | null) => raw ? { month: Number(raw.slice(5, 7)), day: Number(raw.slice(8, 10)), year: Number(raw.slice(0, 4)), year_quality: 'verified' as const, origin: 'internal_crm' as const } : null;
    const row = { ...rowFor(id), first_name: legacy.first_name, last_name: legacy.last_name, display_name: `${legacy.first_name} ${legacy.last_name}`.trim(), primary_email: legacy.email, primary_phone: legacy.phone, stage: legacy.stage, lead_backed: false, origins: ['internal_only'] as const, sources: ['internal_crm'] as const, birthday: celebration(legacy.birthday), anniversary: celebration(legacy.anniversary), evidence_quality: null };
    state.rows.push(row);
    state.createdAt.set(id, FIXED_AT);
    state.updatedAt.set(id, FIXED_AT);
    state.details.set(id, { ...detailFor(row), recovered_profile: null });
    const createdWorkspace = workspaceFor(row);
    state.workspaces.set(id, { ...createdWorkspace, contact: { ...createdWorkspace.contact, birthday: legacy.birthday, anniversary: legacy.anniversary } });
    recordActivity(state, id, 'contact_created', 'Contact created in Command workspace');
    return { status: 201, body: legacy };
  }
  if (path === '/tags') {
    if (method !== 'POST' || url.search.length > 0) return fail(`${method} ${path}${url.search}`);
    const body = jsonBody(request);
    if (isFixtureResponse(body) || !exactKeys(body, ['name']) || typeof body.name !== 'string' || body.name.trim().length === 0 || Array.from(body.name).length > 80) return isFixtureResponse(body) ? body : fail('invalid tag body');
    const tag = { id: state.nextTagId++, name: body.name };
    state.tags.push(tag);
    return { status: 201, body: tag };
  }
  if (path === '/tasks' && method === 'POST' && url.search.length === 0) {
    const body = jsonBody(request);
    const keys = ['title', 'contact_id', 'description', 'priority', 'due_at'];
    if (isFixtureResponse(body)) return body;
    if (body.contact_id === null) return null;
    const idempotencyKey = request.headers()['x-idempotency-key'];
    const clientTimezone = request.headers()['x-client-timezone'];
    const validContact = body.contact_id === null || (Number.isInteger(body.contact_id) && state.rows.some((row) => row.id === body.contact_id));
    if (!UUID_PATTERN.test(idempotencyKey ?? '') || typeof clientTimezone !== 'string' || clientTimezone.trim().length === 0 || clientTimezone.length > 100 || !exactKeys(body, keys) || !validContact || typeof body.title !== 'string' || body.title.trim().length === 0 || Array.from(body.title).length > 255 || typeof body.description !== 'string' || !['low', 'normal', 'high'].includes(String(body.priority)) || !rfc3339Value(body.due_at)) return fail('invalid contact task body');
    const canonicalPayload = {
      title: String(body.title),
      contact_id: Number(body.contact_id),
      description: String(body.description),
      priority: String(body.priority),
      due_at: body.due_at === null ? null : String(body.due_at),
    };
    const fingerprint = JSON.stringify(canonicalPayload);
    const existing = state.taskCreates.get(idempotencyKey!);
    if (existing !== undefined) {
      if (existing.fingerprint !== fingerprint) {
        return {
          status: 409,
          body: {
            detail: {
              code: 'task_idempotency_mismatch',
              message: 'Idempotency key was already used with a different task payload.',
            },
          },
        };
      }
      return { status: 201, body: structuredClone(existing.task) };
    }
    const createdTask = {
      id: state.nextTaskId++,
      ...canonicalPayload,
      status: 'open' as const,
      archived_at: null,
      archive_reason: null,
      version: 1,
    };
    state.taskCreates.set(idempotencyKey!, { fingerprint, task: createdTask });
    if (createdTask.contact_id !== null) {
      const taskWorkspace = state.workspaces.get(createdTask.contact_id)!;
      const legacyTask = {
        id: createdTask.id,
        title: createdTask.title,
        contact_id: createdTask.contact_id,
        description: createdTask.description,
        priority: createdTask.priority,
        due_at: createdTask.due_at,
        status: createdTask.status,
      };
      state.workspaces.set(createdTask.contact_id, { ...taskWorkspace, tasks: [legacyTask, ...taskWorkspace.tasks] });
      recordActivity(state, createdTask.contact_id, 'task_created', createdTask.title);
    }
    return { status: 201, body: createdTask };
  }
  const artifact = /^\/archive\/artifacts\/(\d+)\/content$/.exec(path);
  if (artifact) {
    if (method !== 'GET' || artifact[1] !== '55' || url.search.length > 0) return fail(`${method} ${path}${url.search}`);
    return { status: 200, binaryBody: Buffer.from('synthetic archive evidence\n'), headers: { 'content-type': 'application/octet-stream', 'content-disposition': 'attachment; filename="source-evidence-55.bin"' } };
  }
  const match = /^\/contacts\/(\d+)(.*)$/.exec(path);
  if (!match) return null;
  const id = Number(match[1]);
  if (!canonicalInteger(match[1], 1)) return fail(`${method} ${path}${url.search}`);
  const suffix = match[2] || '';
  const nestedId = /^\/(?:notes|tags)\/(\d+)$/.exec(suffix);
  if (nestedId && !canonicalInteger(nestedId[1], 1)) return fail(`${method} ${path}${url.search}`);
  const detail = state.details.get(id);
  const workspace = state.workspaces.get(id);
  if (!detail || !workspace) {
    const querylessMethods: Readonly<Record<string, readonly string[]>> = {
      '': ['GET', 'PATCH'],
      '/workspace/summary': ['GET'],
      '/workspace': ['GET'],
      '/evidence': ['GET'],
      '/notes': ['POST'],
      '/saved-searches': ['POST'],
    };
    const allowed = querylessMethods[suffix];
    const noteMutation = /^\/notes\/\d+$/.test(suffix) && method === 'DELETE';
    const tagMutation = /^\/tags\/\d+$/.test(suffix) && (method === 'POST' || method === 'DELETE');
    const queryBoundary = suffix === '/neighbors' || suffix === '/timeline'
      || ['/opportunities', '/smart-plans', '/notes', '/saved-searches', '/tasks'].includes(suffix);
    if ((!allowed || !allowed.includes(method)) && !noteMutation && !tagMutation && !(queryBoundary && method === 'GET')) return fail(`${method} ${path}${url.search}`);
    if (!queryBoundary && url.search.length > 0) return fail(`${method} ${path}${url.search}`);
    if (suffix === '/neighbors' && canonicalDirectoryQuery(url)) return fail(`${method} ${path}${url.search}`);
    if (suffix === '/timeline') {
      if (!validTimelineQuery(url, method)) return fail(`${method} ${path}${url.search}`);
    }
    if (['/opportunities', '/smart-plans', '/notes', '/saved-searches', '/tasks'].includes(suffix) && method === 'GET') {
      const expectedKeys = suffix === '/tasks' ? ['state', 'page', 'page_size'] : ['page', 'page_size'];
      const actualKeys = [...url.searchParams.keys()];
      const page = Number(url.searchParams.get('page'));
      const pageSize = Number(url.searchParams.get('page_size'));
      if (actualKeys.length !== expectedKeys.length || actualKeys.some((key, index) => key !== expectedKeys[index])
        || !canonicalInteger(url.searchParams.get('page'), 1) || !canonicalInteger(url.searchParams.get('page_size'), 1, 100)
        || !Number.isInteger(page) || page < 1 || !Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100
        || (suffix === '/tasks' && !['to_do', 'completed', 'archived'].includes(url.searchParams.get('state') ?? ''))) return fail(`${method} ${path}${url.search}`);
    }
    if (suffix === '' && method === 'PATCH') {
      const body = jsonBody(request);
      const allowedKeys = ['first_name', 'last_name', 'email', 'phone', 'stage', 'birthday', 'anniversary'];
      if (isFixtureResponse(body) || !exactKeys(body, allowedKeys, []) || Object.keys(body).length === 0 || !validContactFields(body, false)
        || (body.first_name !== undefined && String(body.first_name).trim().length === 0)) return isFixtureResponse(body) ? body : fail('invalid update contact body');
    }
    if (suffix === '/notes' && method === 'POST') {
      const body = jsonBody(request);
      if (isFixtureResponse(body) || !exactKeys(body, ['body']) || typeof body.body !== 'string' || body.body.trim().length === 0 || Array.from(body.body).length > 20_000) return isFixtureResponse(body) ? body : fail('invalid note body');
    }
    if (suffix === '/saved-searches' && method === 'POST') {
      const body = jsonBody(request);
      const criteria = !isFixtureResponse(body) && typeof body.criteria === 'object' && body.criteria !== null && !Array.isArray(body.criteria) ? body.criteria as Record<string, unknown> : null;
      if (isFixtureResponse(body) || !exactKeys(body, ['name', 'criteria']) || typeof body.name !== 'string' || body.name.trim().length === 0 || Array.from(body.name).length > 255
        || !criteria || !finiteJsonValue(criteria) || Buffer.byteLength(canonicalJson(criteria), 'utf8') > 65_536
        || (criteria.contact_id !== undefined && criteria.contact_id !== id)) return isFixtureResponse(body) ? body : fail('invalid saved search body');
    }
    if (tagMutation && (url.search.length > 0 || request.postData() !== null)) return fail(`${method} ${path}${url.search}`);
    return { status: 404, body: { detail: 'Contact not found' } };
  }
  if (suffix === '') {
    if (method === 'GET') return url.search.length === 0 ? { status: 200, body: detail } : fail(`${method} ${path}${url.search}`);
    if (method === 'PATCH') {
      const body = jsonBody(request);
      const allowed = ['first_name', 'last_name', 'email', 'phone', 'stage', 'birthday', 'anniversary'];
      if (url.search.length > 0 || isFixtureResponse(body) || !exactKeys(body, allowed, []) || Object.keys(body).length === 0 || !validContactFields(body, false) || (body.first_name !== undefined && String(body.first_name).trim().length === 0)) return isFixtureResponse(body) ? body : fail('invalid update contact body');
      const changed = Object.entries(body).some(([key, value]) => workspace.contact[key as keyof typeof workspace.contact] !== value);
      const updated = { ...workspace.contact, ...body, id };
      if (changed) {
        updateContactState(state, id, (row) => ({
          ...row,
          first_name: typeof body.first_name === 'string' ? body.first_name : row.first_name,
          last_name: typeof body.last_name === 'string' ? body.last_name : row.last_name,
          display_name: `${typeof body.first_name === 'string' ? body.first_name : row.first_name} ${typeof body.last_name === 'string' ? body.last_name : row.last_name}`.trim(),
          primary_email: body.email === undefined ? row.primary_email : body.email as string | null,
          primary_phone: body.phone === undefined ? row.primary_phone : body.phone as string | null,
          stage: typeof body.stage === 'string' ? body.stage : row.stage,
          birthday: typeof body.birthday === 'string'
            ? { month: Number(body.birthday.slice(5, 7)), day: Number(body.birthday.slice(8, 10)), year: Number(body.birthday.slice(0, 4)), year_quality: 'verified', origin: 'internal_crm' }
            : body.birthday === null ? null : row.birthday,
          anniversary: typeof body.anniversary === 'string'
            ? { month: Number(body.anniversary.slice(5, 7)), day: Number(body.anniversary.slice(8, 10)), year: Number(body.anniversary.slice(0, 4)), year_quality: 'verified', origin: 'internal_crm' }
            : body.anniversary === null ? null : row.anniversary,
        }));
        const persisted = state.workspaces.get(id)!;
        state.workspaces.set(id, {
          ...persisted,
          contact: {
            ...persisted.contact,
            birthday: body.birthday === undefined ? persisted.contact.birthday : body.birthday as string | null,
            anniversary: body.anniversary === undefined ? persisted.contact.anniversary : body.anniversary as string | null,
          },
        });
        const stageOnly = Object.keys(body).length === 1 && body.stage !== undefined;
        recordActivity(state, id, stageOnly ? 'stage_changed' : 'contact_updated', stageOnly ? 'Contact stage changed' : 'Updated contact profile');
      }
      return { status: 200, body: updated };
    }
    return fail(`${method} ${path}`);
  }
  if (suffix === '/neighbors') {
    if (method !== 'GET' || canonicalDirectoryQuery(url)) return fail(`${method} ${path}${url.search}`);
    const universe = directoryUniverse(state, url);
    if ('status' in universe) return universe;
    const index = universe.findIndex((row) => row.id === id);
    if (index < 0) return { status: 409, body: { detail: 'Contact is outside the current directory universe' } };
    return { status: 200, body: { previous_contact_id: index > 0 ? universe[index - 1]!.id : null, next_contact_id: index >= 0 && index < universe.length - 1 ? universe[index + 1]!.id : null } };
  }
  if (suffix === '/workspace/summary') return method === 'GET' && url.search.length === 0 ? { status: 200, body: summaryFor(workspace) } : fail(`${method} ${path}${url.search}`);
  if (suffix === '/workspace') return method === 'GET' && url.search.length === 0 ? { status: 200, body: workspace } : fail(`${method} ${path}${url.search}`);
  if (suffix === '/timeline') {
    return validTimelineQuery(url, method) ? { status: 200, body: timeline(state, id) } : fail(`${method} ${path}${url.search}`);
  }
  if (suffix === '/evidence') return method === 'GET' && url.search.length === 0 ? { status: 200, body: evidenceFor(id) } : fail(`${method} ${path}${url.search}`);
  const sectionBySuffix: Readonly<Record<string, Exclude<ContactSectionName, 'timeline'>>> = {
    '/opportunities': 'opportunities', '/smart-plans': 'smart_plans', '/notes': 'notes', '/saved-searches': 'saved_searches', '/tasks': (url.searchParams.get('state') ? `tasks_${url.searchParams.get('state')}` : '') as Exclude<ContactSectionName, 'timeline'>,
  };
  const section = sectionBySuffix[suffix];
  if (section && method === 'GET') {
    const page = Number(url.searchParams.get('page'));
    const pageSize = Number(url.searchParams.get('page_size'));
    const expectedKeys = suffix === '/tasks' ? ['state', 'page', 'page_size'] : ['page', 'page_size'];
    const actualKeys = [...url.searchParams.keys()];
    const taskState = url.searchParams.get('state');
    if (actualKeys.length !== expectedKeys.length || actualKeys.some((key, index) => key !== expectedKeys[index])
      || !canonicalInteger(url.searchParams.get('page'), 1) || !canonicalInteger(url.searchParams.get('page_size'), 1, 100)
      || !Number.isInteger(page) || page < 1 || !Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100
      || (suffix === '/tasks' && !['to_do', 'completed', 'archived'].includes(taskState ?? ''))) return fail(`invalid section query ${path}${url.search}`);
    return { status: 200, body: sectionPage(section, page, pageSize, id) };
  }
  if (suffix === '/notes' && method === 'POST') {
    const body = jsonBody(request);
    if (url.search.length > 0 || isFixtureResponse(body) || !exactKeys(body, ['body']) || typeof body.body !== 'string' || body.body.trim().length === 0 || Array.from(body.body).length > 20_000) return isFixtureResponse(body) ? body : fail('invalid note body');
    const note = { id: state.nextNoteId++, contact_id: id, body: body.body, created_at: FIXED_AT, updated_at: FIXED_AT };
    state.workspaces.set(id, { ...workspace, notes: [note, ...workspace.notes] });
    recordActivity(state, id, 'note', 'Added a contact note');
    return { status: 201, body: { id: note.id, body: note.body } };
  }
  const noteDelete = /^\/notes\/(\d+)$/.exec(suffix);
  if (noteDelete && method === 'DELETE') {
    const noteId = Number(noteDelete[1]);
    if (url.search.length > 0) return fail(`${method} ${path}${url.search}`);
    if (!workspace.notes.some((note) => note.id === noteId)) return { status: 404, body: { detail: 'Note not found for contact' } };
    state.workspaces.set(id, { ...workspace, notes: workspace.notes.filter((note) => note.id !== noteId) });
    recordActivity(state, id, 'note_removed', 'Removed a contact note');
    return { status: 200, body: { deleted: true, id: noteId } };
  }
  if (suffix === '/saved-searches' && method === 'POST') {
    const body = jsonBody(request);
    const criteria = !isFixtureResponse(body) && typeof body.criteria === 'object' && body.criteria !== null && !Array.isArray(body.criteria)
      ? body.criteria as Record<string, unknown>
      : null;
    if (url.search.length > 0 || isFixtureResponse(body) || !exactKeys(body, ['name', 'criteria']) || typeof body.name !== 'string' || body.name.trim().length === 0 || Array.from(body.name).length > 255 || !criteria || !finiteJsonValue(criteria) || Buffer.byteLength(canonicalJson(criteria), 'utf8') > 65_536 || (criteria.contact_id !== undefined && criteria.contact_id !== id)) return isFixtureResponse(body) ? body : fail('invalid saved search body');
    const saved = { id: state.nextSearchId++, name: body.name, criteria: canonicalJson(body.criteria) };
    state.workspaces.set(id, { ...workspace, saved_searches: [saved, ...workspace.saved_searches] });
    return { status: 201, body: saved };
  }
  const tagRoute = /^\/tags\/(\d+)$/.exec(suffix);
  if (tagRoute && (method === 'POST' || method === 'DELETE')) {
    const tagId = Number(tagRoute[1]);
    const tag = state.tags.find((candidate) => candidate.id === tagId);
    if (!tag) return { status: 404, body: { detail: 'Tag not found' } };
    if (url.search.length > 0 || request.postData() !== null) return fail(`${method} ${path}${url.search}`);
    const wasAssigned = workspace.tags.some((candidate) => candidate.id === tagId);
    const tags = method === 'POST'
      ? (workspace.tags.some((candidate) => candidate.id === tagId) ? workspace.tags : [...workspace.tags, tag])
      : workspace.tags.filter((candidate) => candidate.id !== tagId);
    updateContactState(state, id, (row) => ({ ...row, tags }), false);
    if (method === 'DELETE' && wasAssigned) recordActivity(state, id, 'tag_removed', 'Removed a contact tag');
    return { status: 200, body: method === 'POST' ? { contact_id: id, tag_id: tagId } : { removed: wasAssigned, contact_id: id, tag_id: tagId } };
  }
  return fail(`${method} ${path}${url.search}`);
}
