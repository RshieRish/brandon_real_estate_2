import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CommandDecodeError, CommandHttpError } from './http';
import {
  contactsApi,
  decodeContactBulkInput,
  decodeContactBulkResult,
  decodeContactCelebrations,
  decodeContactCreateInput,
  decodeContactDetail,
  decodeContactDirectoryPage,
  decodeContactEvidence,
  decodeContactNeighbors,
  decodeContactSectionPage,
  decodeContactTimelinePage,
  decodeContactUpdateInput,
  decodeContactWorkspaceSummary,
  decodeLegacyContact,
  serializeDirectoryRequest,
} from './contacts';

const COMMAND_BASE_URL = 'http://localhost:8000/api/v1/command';
const SHA = 'a'.repeat(64);

const actor = {
  role: 'owner',
  provider_actor_id: 'provider-17',
  display_name: 'Owner',
};

const celebrationValue = {
  month: 8,
  day: 13,
  year: null,
  year_quality: 'yearless',
  origin: 'recovered',
};

const directoryRow = {
  id: 7,
  first_name: 'Avery',
  last_name: 'Stone',
  display_name: 'Avery Stone',
  primary_email: null,
  primary_phone: null,
  stage: 'lead',
  lead_backed: false,
  origins: ['recovered'],
  sources: ['kw_command'],
  health_score: 88,
  last_contacted_at: '2026-08-13T14:30:00Z',
  last_interaction_at: null,
  owner: actor,
  assignee: null,
  tags: [{ id: 3, name: 'Buyer' }],
  birthday: celebrationValue,
  anniversary: null,
  evidence_quality: 'complete',
};

const directoryPage = {
  rows: [directoryRow],
  total: 1,
  page: 1,
  page_size: 25,
  page_count: 1,
  sort: 'name',
  direction: 'asc',
};

const detail = {
  contact: directoryRow,
  lead_id: null,
  recovered_profile: {
    legal_name: 'Avery Stone',
    preferred_name: 'Avery',
    description: null,
    company: null,
    title: null,
    lead_source: null,
    account_name: null,
    birthday: celebrationValue,
    anniversary: null,
  },
  addresses: [{
    id: 5,
    address_type: 'home',
    formatted: 'Private address',
    latitude: '4.21E+1',
    longitude: '-71.0000000',
    source_record_id: 19,
  }],
  ownership: [actor],
  tags: [{ id: 3, name: 'Buyer' }],
};

const sourceOnlyRow = {
  status: 'source_only',
  source_record_id: 31,
  source_key_hash: SHA,
  section: 'tasks_to_do',
  occurrence_ordinal: 1,
  capture_quality: 'complete',
  captured_at: '2026-08-13T14:30:00+00:00',
  value: {
    kind: 'task',
    title: 'Call client',
    description: null,
    state: 'to_do',
    due_at: '2026-08-14T09:00:00-04:00',
  },
};

const materializedRow = {
  status: 'materialized',
  source_record_id: 32,
  source_key_hash: SHA,
  section: 'opportunities',
  occurrence_ordinal: 2,
  capture_quality: 'partial',
  captured_at: null,
  value: {
    kind: 'opportunity',
    title: 'Listing',
    stage: null,
    value_cents: 250_000,
  },
  entity_type: 'opportunity',
  entity_id: 12,
};

const sectionPage = {
  rows: [sourceOnlyRow, materializedRow],
  total: 2,
  page: 1,
  page_size: 50,
  page_count: 1,
};

const timelinePage = {
  rows: [{
    key: 'booking:4',
    origin: 'booking',
    kind: 'meeting',
    title: 'Consultation',
    body: null,
    outcome: null,
    occurred_at: null,
    source_record_id: null,
    entity_type: 'booking',
    entity_id: 4,
  }],
  next_cursor: null,
  has_more: false,
};

const evidence = {
  contact_id: 7,
  provider_contact_rows: 1,
  resolved_provider_identities: 1,
  coalesced_aliases: 0,
  lead_backed_contacts: 51,
  reviewed_overlaps: 2,
  legacy_only_contacts: 49,
  capture_positions: [{
    capture_position_id: 4,
    capture_ordinal: 1,
    source_record_id: 31,
    capture_quality: 'complete',
    sections: [{
      capture_position_id: 4,
      section: 'timeline',
      source_record_id: 32,
      capture_quality: 'complete',
      row_count: 0,
      is_empty: true,
      limitation_codes: [],
    }],
  }],
  section_matrix: [],
  sources: [{
    source_record_id: 31,
    record_kind: 'contact_profile',
    evidence_level: 'observed_record',
    capture_quality: 'complete',
    captured_at: null,
    artifacts: [{
      artifact_id: 9,
      artifact_type: 'json',
      sha256: SHA,
      size_bytes: 123,
      content_href: '/api/v1/command/archive/artifacts/9/content',
    }],
  }],
  capture_quality: 'complete',
};

const celebrations = {
  birthdays: [{
    contact_id: 7,
    display_name: 'Avery Stone',
    kind: 'birthday',
    month: 8,
    day: 13,
    year: null,
    year_quality: 'yearless',
    origin: 'recovered',
  }],
  anniversaries: [],
};

const legacyContact = {
  id: 7,
  first_name: 'Avery',
  last_name: 'Stone',
  email: null,
  phone: null,
  lead_id: null,
  birthday: null,
  anniversary: '2020-02-29',
  stage: 'lead',
};

const workspaceSummary = {
  open_tasks: 1,
  completed_tasks: 2,
  archived_tasks: 3,
  active_smart_plans: 4,
  opportunities: 5,
  notes: 6,
  saved_searches: 7,
  bookings: 8,
};

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function withoutKey(input: object, key: string): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(input).filter(([candidate]) => candidate !== key),
  );
}

function privateDecodeFailure(operation: () => unknown): void {
  let error: unknown;
  try {
    operation();
  } catch (caught) {
    error = caught;
  }
  expect(error).toBeInstanceOf(CommandDecodeError);
  expect(String(error)).not.toMatch(/private|secret|unsafe@example\.test/);
}

describe('Command contacts wire decoders', () => {
  it('decodes the complete directory wire without renaming snake_case fields', () => {
    expect(decodeContactDirectoryPage(directoryPage)).toEqual(directoryPage);
  });

  it('requires every response array even when Task 6 constructs defaults internally', () => {
    const rowWithoutOrigins = withoutKey(directoryRow, 'origins');
    const rowWithoutSources = withoutKey(directoryRow, 'sources');
    const rowWithoutTags = withoutKey(directoryRow, 'tags');
    const pageWithoutRows = withoutKey(directoryPage, 'rows');

    privateDecodeFailure(() => decodeContactDirectoryPage({
      ...directoryPage,
      rows: [rowWithoutOrigins],
    }));
    privateDecodeFailure(() => decodeContactDirectoryPage({
      ...directoryPage,
      rows: [rowWithoutSources],
    }));
    privateDecodeFailure(() => decodeContactDirectoryPage({
      ...directoryPage,
      rows: [rowWithoutTags],
    }));
    privateDecodeFailure(() => decodeContactDirectoryPage(pageWithoutRows));

    privateDecodeFailure(() => decodeContactDetail(withoutKey(detail, 'addresses')));
    privateDecodeFailure(() => decodeContactDetail(withoutKey(detail, 'ownership')));
    privateDecodeFailure(() => decodeContactDetail(withoutKey(detail, 'tags')));

    privateDecodeFailure(() => decodeContactSectionPage({
      total: 0,
      page: 1,
      page_size: 50,
      page_count: 0,
    }));
    privateDecodeFailure(() => decodeContactTimelinePage({ next_cursor: null, has_more: false }));
    privateDecodeFailure(() => decodeContactCelebrations({}));
  });

  it('rejects missing required fields and extra fields recursively without leaking values', () => {
    privateDecodeFailure(() => decodeContactDirectoryPage({ rows: [], total: 0 }));
    privateDecodeFailure(() => decodeContactDetail({
      ...detail,
      contact: { ...directoryRow, private_payload: 'secret@example.test' },
    }));
    privateDecodeFailure(() => decodeContactEvidence({
      ...evidence,
      sources: [{ ...evidence.sources[0], payload_json: 'private-source-payload' }],
    }));
  });

  it('requires safe bounded integers instead of accepting booleans, floats, or unsafe JSON numbers', () => {
    for (const id of [true, 1.5, 0, -1, Number.MAX_SAFE_INTEGER + 1]) {
      privateDecodeFailure(() => decodeLegacyContact({ ...legacyContact, id }));
    }
    for (const total of [-1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
      privateDecodeFailure(() => decodeContactDirectoryPage({ ...directoryPage, total }));
    }
    privateDecodeFailure(() => decodeContactDirectoryPage({
      ...directoryPage,
      rows: [{ ...directoryRow, health_score: 101 }],
    }));
  });

  it('validates exact calendar dates and RFC3339 datetimes with offsets', () => {
    expect(decodeLegacyContact({ ...legacyContact, birthday: '2024-02-29' }).birthday)
      .toBe('2024-02-29');
    expect(decodeContactTimelinePage({
      ...timelinePage,
      rows: [{ ...timelinePage.rows[0], occurred_at: '2026-02-28T23:59:59.123+05:30' }],
    }).rows[0]?.occurred_at).toBe('2026-02-28T23:59:59.123+05:30');

    for (const birthday of ['2023-02-29', '2026-13-01', '2026-01-01T00:00:00Z']) {
      privateDecodeFailure(() => decodeLegacyContact({ ...legacyContact, birthday }));
    }
    for (const occurred_at of [
      '2026-02-30T12:00:00Z',
      '2026-01-01T12:00:00',
      '2026-01-01T24:00:00Z',
      '2026-01-01T12:00:00+24:00',
    ]) {
      privateDecodeFailure(() => decodeContactTimelinePage({
        ...timelinePage,
        rows: [{ ...timelinePage.rows[0], occurred_at }],
      }));
    }
  });

  it.each([
    ['1E-7', '1E-7'],
    ['0.0000001', '0.0000001'],
    ['.1', '.1'],
    ['1E-0000007', '1E-0000007'],
    ['1.23000000', '1.23000000'],
    ['00090.0000000', '00090.0000000'],
    ['-0E+999999', '-0E+999999'],
  ])('accepts exact Numeric(10,7) latitude text %s unchanged', (latitude, expected) => {
    const decoded = decodeContactDetail({
      ...detail,
      addresses: [{ ...detail.addresses[0], latitude }],
    });
    expect(decoded.addresses[0]?.latitude).toBe(expected);
  });

  it.each([
    [1e-7, 'numeric JSON'],
    ['', 'empty'],
    [' 1.0', 'whitespace'],
    ['NaN', 'NaN'],
    ['Infinity', 'infinity'],
    ['1E', 'malformed exponent'],
    ['90.0000001', 'latitude range'],
    ['1E-8', 'excess precision'],
    ['1E+999999999999999999999', 'huge positive exponent'],
    ['1E-999999999999999999999', 'huge negative exponent'],
  ])('rejects %s as %s latitude without floating-point coercion', (latitude, _description) => {
    void _description;
    privateDecodeFailure(() => decodeContactDetail({
      ...detail,
      addresses: [{ ...detail.addresses[0], latitude }],
    }));
  });

  it('enforces the separate longitude range', () => {
    expect(decodeContactDetail({
      ...detail,
      addresses: [{ ...detail.addresses[0], longitude: '180' }],
    }).addresses[0]?.longitude).toBe('180');
    privateDecodeFailure(() => decodeContactDetail({
      ...detail,
      addresses: [{ ...detail.addresses[0], longitude: '180.0000001' }],
    }));
  });

  it('discriminates occurrence kind before materialization status and rejects drift', () => {
    expect(decodeContactSectionPage(sectionPage)).toEqual(sectionPage);
    privateDecodeFailure(() => decodeContactSectionPage({
      ...sectionPage,
      rows: [{ ...sourceOnlyRow, status: 'unknown' }],
    }));
    privateDecodeFailure(() => decodeContactSectionPage({
      ...sectionPage,
      rows: [{ ...sourceOnlyRow, value: { kind: 'unknown', title: 'private' } }],
    }));
    privateDecodeFailure(() => decodeContactSectionPage({
      ...sectionPage,
      rows: [{ ...sourceOnlyRow, source_key_hash: SHA.toUpperCase() }],
    }));
    privateDecodeFailure(() => decodeContactSectionPage({
      ...sectionPage,
      rows: [{
        ...sourceOnlyRow,
        value: { ...sourceOnlyRow.value, due_at: '2026-02-30T00:00:00Z' },
      }],
    }));
  });

  it('decodes every occurrence variant and exact nullable fields', () => {
    const rows = [
      materializedRow,
      {
        ...sourceOnlyRow,
        section: 'smart_plans',
        value: { kind: 'smart_plan', title: 'Plan', status: null },
      },
      {
        ...sourceOnlyRow,
        section: 'notes',
        value: { kind: 'note', title: 'Note', body: null },
      },
      {
        ...sourceOnlyRow,
        section: 'saved_searches',
        value: { kind: 'saved_search', title: 'Search', criteria_summary: ['one'] },
      },
      sourceOnlyRow,
    ];
    expect(decodeContactSectionPage({ ...sectionPage, rows, total: rows.length }).rows)
      .toHaveLength(5);
  });

  it('preserves nullable recovered timeline timestamps', () => {
    expect(decodeContactTimelinePage(timelinePage)).toEqual(timelinePage);
  });

  it('enforces aggregate evidence constants, quality domains, and derived content links', () => {
    expect(decodeContactEvidence(evidence)).toEqual(evidence);
    privateDecodeFailure(() => decodeContactEvidence({
      contact_id: 7,
      provider_contact_rows: 0,
      resolved_provider_identities: 0,
      coalesced_aliases: 0,
      lead_backed_contacts: 0,
      reviewed_overlaps: 0,
      legacy_only_contacts: 0,
      capture_quality: 'limitation',
    }));

    expect(decodeContactEvidence({
      ...evidence,
      capture_quality: 'limitation',
      capture_positions: [{ ...evidence.capture_positions[0], capture_quality: 'shell' }],
      section_matrix: [{ ...evidence.capture_positions[0].sections[0], capture_quality: 'error' }],
      sources: [{ ...evidence.sources[0], capture_quality: 'partial' }],
    }).capture_quality).toBe('limitation');

    for (const coalesced_aliases of [1, false, '0']) {
      privateDecodeFailure(() => decodeContactEvidence({ ...evidence, coalesced_aliases }));
    }
    privateDecodeFailure(() => decodeContactEvidence({
      ...evidence,
      capture_quality: 'shell',
    }));
    privateDecodeFailure(() => decodeContactEvidence({
      ...evidence,
      sources: [{ ...evidence.sources[0], capture_quality: 'limitation' }],
    }));
    privateDecodeFailure(() => decodeContactEvidence({
      ...evidence,
      sources: [{
        ...evidence.sources[0],
        artifacts: [{
          ...evidence.sources[0].artifacts[0],
          content_href: '/private/archive/file',
        }],
      }],
    }));
  });

  it('validates artifact metadata and materialization provenance recursively', () => {
    for (const artifact of [
      { ...evidence.sources[0].artifacts[0], artifact_type: '' },
      { ...evidence.sources[0].artifacts[0], artifact_type: 'x'.repeat(65) },
      { ...evidence.sources[0].artifacts[0], sha256: 'A'.repeat(64) },
      { ...evidence.sources[0].artifacts[0], size_bytes: -1 },
      { ...evidence.sources[0].artifacts[0], content_href: '/api/v1/command/archive/artifacts/10/content' },
    ]) {
      privateDecodeFailure(() => decodeContactEvidence({
        ...evidence,
        sources: [{ ...evidence.sources[0], artifacts: [artifact] }],
      }));
    }

    for (const row of [
      { ...materializedRow, source_key_hash: '0'.repeat(63) },
      { ...materializedRow, captured_at: '2026-02-30T00:00:00Z' },
      { ...materializedRow, entity_type: 'private_entity' },
      { ...materializedRow, entity_id: 0 },
    ]) {
      privateDecodeFailure(() => decodeContactSectionPage({ ...sectionPage, rows: [row] }));
    }
  });

  it('requires legacy mutation nullable keys and rejects expanded-detail substitution', () => {
    expect(decodeLegacyContact(legacyContact)).toEqual(legacyContact);
    privateDecodeFailure(() => decodeLegacyContact(withoutKey(legacyContact, 'lead_id')));
    privateDecodeFailure(() => decodeLegacyContact(detail));
  });

  it('enforces sorted unique bounded bulk result IDs and the actioned subset', () => {
    const valid = {
      requested_contact_ids: [3, 7, 9],
      actioned_contact_ids: [3, 9],
      action: 'remove_tag',
    };
    expect(decodeContactBulkResult(valid)).toEqual(valid);

    for (const result of [
      { ...valid, requested_contact_ids: [] },
      { ...valid, requested_contact_ids: [7, 3, 9] },
      { ...valid, requested_contact_ids: [3, 3, 9] },
      { ...valid, requested_contact_ids: Array.from({ length: 201 }, (_value, index) => index + 1) },
      { ...valid, actioned_contact_ids: [9, 3] },
      { ...valid, actioned_contact_ids: [3, 3] },
      { ...valid, actioned_contact_ids: [3, 8] },
    ]) {
      privateDecodeFailure(() => decodeContactBulkResult(result));
    }
  });

  it('decodes every top-level response contract independently', () => {
    expect(decodeContactNeighbors({ previous_contact_id: null, next_contact_id: 8 }))
      .toEqual({ previous_contact_id: null, next_contact_id: 8 });
    expect(decodeContactWorkspaceSummary(workspaceSummary)).toEqual(workspaceSummary);
    expect(decodeContactCelebrations(celebrations)).toEqual(celebrations);
    expect(decodeContactBulkResult({
      requested_contact_ids: [7, 8],
      actioned_contact_ids: [7],
      action: 'add_tag',
    })).toEqual({
      requested_contact_ids: [7, 8],
      actioned_contact_ids: [7],
      action: 'add_tag',
    });
  });

  it('matches Task 6 celebration wire bounds without applying Home semantics', () => {
    expect(decodeContactDirectoryPage({
      ...directoryPage,
      rows: [{
        ...directoryRow,
        birthday: {
          ...celebrationValue,
          month: 2,
          day: 31,
          year: -5,
          year_quality: 'unknown',
        },
      }],
    }).rows[0]?.birthday).toMatchObject({ month: 2, day: 31, year: -5 });
    expect(decodeContactCelebrations({
      birthdays: [{
        ...celebrations.birthdays[0],
        month: 2,
        day: 31,
        year: -5,
        year_quality: 'unknown',
      }],
      anniversaries: [],
    }).birthdays[0]).toMatchObject({ month: 2, day: 31, year: -5 });
  });
});

describe('Command contacts request validation and serialization', () => {
  it('serializes every directory filter in canonical order with sorted unique repetitions', () => {
    expect(serializeDirectoryRequest({
      query: ' Avery & Co ',
      stage: ' buyer ',
      owner_actor_id: ' owner/7 ',
      assignee_actor_id: ' assigned?9 ',
      tag: [9, 3, 9],
      source: ['legacy_lead', 'kw_command', 'kw_command'],
      origin: ['legacy_only', 'recovered', 'legacy_only'],
      health_min: 10,
      health_max: 90,
      birthday_month: 8,
      anniversary_month: 9,
      smart_view: 'recently_active',
      sort: 'updated_at',
      direction: 'desc',
      page: 2,
      page_size: 25,
    })).toBe(
      'query=Avery+%26+Co&stage=buyer&owner_actor_id=owner%2F7&assignee_actor_id=assigned%3F9'
      + '&tag=3&tag=9&source=kw_command&source=legacy_lead&origin=legacy_only&origin=recovered'
      + '&health_min=10&health_max=90&birthday_month=8&anniversary_month=9'
      + '&smart_view=recently_active&sort=updated_at&direction=desc&page=2&page_size=25',
    );
  });

  it('omits blank and absent values without serializing undefined', () => {
    expect(serializeDirectoryRequest({
      query: '   ',
      stage: undefined,
      tag: [],
      source: [],
      origin: [],
    })).toBe('');
  });

  it('rejects invalid filters and unknown runtime keys before a URL exists', () => {
    for (const request of [
      { page: 0 },
      { page_size: 101 },
      { health_min: 80, health_max: 20 },
      { birthday_month: 13 },
      { tag: [0] },
      { page: Number.MAX_SAFE_INTEGER + 1 },
      { tag: [Number.MAX_SAFE_INTEGER + 1] },
      { query: 'q'.repeat(201) },
      { stage: 's'.repeat(51) },
      { owner_actor_id: 'o'.repeat(256) },
      { source: ['unknown'] },
      Object.assign({ page: 1 }, { private_filter: 'unsafe@example.test' }),
    ]) {
      privateDecodeFailure(() => Reflect.apply(serializeDirectoryRequest, undefined, [request]));
    }
  });

  it('validates create/update input shapes and exact dates', () => {
    expect(decodeContactCreateInput({ first_name: 'Avery' })).toEqual({ first_name: 'Avery' });
    expect(decodeContactCreateInput({
      first_name: 'Avery',
      last_name: '',
      email: null,
      phone: null,
      stage: 'lead',
      birthday: '2024-02-29',
      anniversary: null,
    })).toMatchObject({ birthday: '2024-02-29', anniversary: null });
    expect(decodeContactUpdateInput({ email: null })).toEqual({ email: null });

    privateDecodeFailure(() => decodeContactCreateInput({ first_name: '   ' }));
    privateDecodeFailure(() => decodeContactCreateInput({
      first_name: 'Avery',
      birthday: '2023-02-29',
    }));
    privateDecodeFailure(() => decodeContactUpdateInput({}));
    privateDecodeFailure(() => decodeContactUpdateInput({ stage: null }));
    privateDecodeFailure(() => decodeContactCreateInput({ first_name: 'A'.repeat(121) }));
    privateDecodeFailure(() => decodeContactCreateInput({ first_name: 'Avery', stage: 's'.repeat(51) }));
    privateDecodeFailure(() => decodeContactUpdateInput({ phone: 'p'.repeat(51) }));
    privateDecodeFailure(() => decodeContactUpdateInput({
      email: null,
      private_payload: 'unsafe@example.test',
    }));
  });

  it('validates each bulk discriminant and rejects duplicate or oversized contact sets', () => {
    expect(decodeContactBulkInput({
      contact_ids: [9, 3],
      action: { action: 'set_stage', stage: 'client' },
    })).toEqual({
      contact_ids: [9, 3],
      action: { action: 'set_stage', stage: 'client' },
    });
    expect(decodeContactBulkInput({
      contact_ids: [9],
      action: { action: 'add_tag', tag_id: 2 },
    }).action.action).toBe('add_tag');
    expect(decodeContactBulkInput({
      contact_ids: [9],
      action: { action: 'remove_tag', tag_id: 2 },
    }).action.action).toBe('remove_tag');

    privateDecodeFailure(() => decodeContactBulkInput({
      contact_ids: [9, 9],
      action: { action: 'add_tag', tag_id: 2 },
    }));
    privateDecodeFailure(() => decodeContactBulkInput({
      contact_ids: Array.from({ length: 201 }, (_value, index) => index + 1),
      action: { action: 'add_tag', tag_id: 2 },
    }));
    privateDecodeFailure(() => decodeContactBulkInput({
      contact_ids: [9],
      action: { action: 'unknown', tag_id: 2 },
    }));
  });

  it('rejects sparse arrays and undefined-only updates before serialization', async () => {
    const sparseTags = new Array<number>(1);
    const sparseContacts = new Array<number>(1);
    privateDecodeFailure(() => serializeDirectoryRequest({ tag: sparseTags }));
    privateDecodeFailure(() => serializeDirectoryRequest({
      source: new Array(1),
    }));
    privateDecodeFailure(() => serializeDirectoryRequest({
      origin: new Array(1),
    }));
    privateDecodeFailure(() => decodeContactBulkInput({
      contact_ids: sparseContacts,
      action: { action: 'add_tag', tag_id: 2 },
    }));
    privateDecodeFailure(() => decodeContactDirectoryPage({
      ...directoryPage,
      rows: new Array(1),
    }));

    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(contactsApi.update(7, { email: undefined })).rejects
      .toBeInstanceOf(CommandDecodeError);
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('counts Unicode code points and rejects whitespace-only stages before fetch', async () => {
    expect(serializeDirectoryRequest({ query: '😀'.repeat(101) }))
      .toBe(`query=${encodeURIComponent('😀'.repeat(101))}`);
    expect(decodeContactCreateInput({ first_name: '😀'.repeat(61) }).first_name)
      .toBe('😀'.repeat(61));
    expect(decodeContactBulkInput({
      contact_ids: [1],
      action: { action: 'set_stage', stage: '😀'.repeat(26) },
    }).action).toMatchObject({ stage: '😀'.repeat(26) });

    for (const input of [
      () => decodeContactCreateInput({ first_name: 'A', stage: '   ' }),
      () => decodeContactUpdateInput({ stage: '   ' }),
      () => decodeContactBulkInput({
        contact_ids: [1],
        action: { action: 'set_stage', stage: '   ' },
      }),
    ]) privateDecodeFailure(input);

    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(contactsApi.create({ first_name: 'A', stage: '   ' })).rejects
      .toBeInstanceOf(CommandDecodeError);
    await expect(contactsApi.update(1, { stage: '   ' })).rejects
      .toBeInstanceOf(CommandDecodeError);
    await expect(contactsApi.bulk({
      contact_ids: [1],
      action: { action: 'set_stage', stage: '   ' },
    })).rejects.toBeInstanceOf(CommandDecodeError);
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

describe('dedicated Contacts API transport map', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn().mockReturnValue('admin-token'),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('exposes exactly the eleven planned methods', () => {
    expect(Object.keys(contactsApi)).toEqual([
      'directory',
      'detail',
      'neighbors',
      'workspace',
      'timeline',
      'section',
      'evidence',
      'celebrations',
      'create',
      'update',
      'bulk',
    ]);
  });

  it('maps all eleven methods to exact URLs, methods, decoders, bodies, and signals', async () => {
    const responses = [
      directoryPage,
      detail,
      { previous_contact_id: null, next_contact_id: 8 },
      workspaceSummary,
      timelinePage,
      sectionPage,
      evidence,
      celebrations,
      legacyContact,
      legacyContact,
      { requested_contact_ids: [7], actioned_contact_ids: [7], action: 'add_tag' },
    ];
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse(responses.shift())));
    const controller = new AbortController();
    vi.stubGlobal('fetch', fetchMock);

    await contactsApi.directory({ query: 'A & B', page: 2 }, { signal: controller.signal });
    await contactsApi.detail(7, { signal: controller.signal });
    await contactsApi.neighbors(7, { tag: [9, 3] }, { signal: controller.signal });
    await contactsApi.workspace(7, { signal: controller.signal });
    await contactsApi.timeline(7, 'opaque+/=', 25, { signal: controller.signal });
    await contactsApi.section(7, 'opportunities', 2, 25, { signal: controller.signal });
    await contactsApi.evidence(7, { signal: controller.signal });
    await contactsApi.celebrations(8, { signal: controller.signal });
    await contactsApi.create({ first_name: 'Avery' }, { signal: controller.signal });
    await contactsApi.update(7, { email: null }, { signal: controller.signal });
    await contactsApi.bulk({
      contact_ids: [7],
      action: { action: 'add_tag', tag_id: 3 },
    }, { signal: controller.signal });

    const expected = [
      ['GET', '/contacts/directory?query=A+%26+B&page=2', undefined],
      ['GET', '/contacts/7', undefined],
      ['GET', '/contacts/7/neighbors?tag=3&tag=9', undefined],
      ['GET', '/contacts/7/workspace/summary', undefined],
      ['GET', '/contacts/7/timeline?cursor=opaque%2B%2F%3D&page_size=25', undefined],
      ['GET', '/contacts/7/opportunities?page=2&page_size=25', undefined],
      ['GET', '/contacts/7/evidence', undefined],
      ['GET', '/celebrations?month=8', undefined],
      ['POST', '/contacts', JSON.stringify({ first_name: 'Avery' })],
      ['PATCH', '/contacts/7', JSON.stringify({ email: null })],
      ['POST', '/contacts/bulk', JSON.stringify({
        contact_ids: [7],
        action: { action: 'add_tag', tag_id: 3 },
      })],
    ];

    expect(fetchMock).toHaveBeenCalledTimes(expected.length);
    expected.forEach(([method, path, body], index) => {
      const call = fetchMock.mock.calls[index];
      expect(call?.[0]).toBe(`${COMMAND_BASE_URL}${path}`);
      expect(call?.[1]).toMatchObject({
        method,
        signal: controller.signal,
        headers: {
          Authorization: 'Bearer admin-token',
          'Content-Type': 'application/json',
        },
      });
      if (body === undefined) expect(call?.[1]).not.toHaveProperty('body');
      else expect(call?.[1]?.body).toBe(body);
    });
  });

  it.each([
    ['opportunities', '/contacts/7/opportunities?page=1&page_size=50'],
    ['smart_plans', '/contacts/7/smart-plans?page=1&page_size=50'],
    ['notes', '/contacts/7/notes?page=1&page_size=50'],
    ['saved_searches', '/contacts/7/saved-searches?page=1&page_size=50'],
    ['tasks_to_do', '/contacts/7/tasks?state=to_do&page=1&page_size=50'],
    ['tasks_completed', '/contacts/7/tasks?state=completed&page=1&page_size=50'],
    ['tasks_archived', '/contacts/7/tasks?state=archived&page=1&page_size=50'],
  ] as const)('maps section %s to %s', async (section, path) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(sectionPage));
    vi.stubGlobal('fetch', fetchMock);

    await contactsApi.section(7, section, 1, 50);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(`${COMMAND_BASE_URL}${path}`);
  });

  it('omits a null timeline cursor and preserves URLSearchParams encoding for opaque cursors', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(timelinePage));
    vi.stubGlobal('fetch', fetchMock);

    await contactsApi.timeline(7, null, 50);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `${COMMAND_BASE_URL}/contacts/7/timeline?page_size=50`,
    );
  });

  it('rejects invalid input for every method before fetch', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const operations = [
      contactsApi.directory({ page: 0 }),
      contactsApi.detail(0),
      contactsApi.neighbors(0, {}),
      contactsApi.workspace(Number.MAX_SAFE_INTEGER + 1),
      contactsApi.timeline(7, null, 0),
      Promise.resolve(Reflect.apply(contactsApi.section, contactsApi, [7, 'timeline', 1, 50])),
      contactsApi.section(7, 'notes', 0, 50),
      contactsApi.evidence(-1),
      contactsApi.celebrations(13),
      contactsApi.create({ first_name: '   ' }),
      contactsApi.update(0, { email: null }),
      contactsApi.bulk({
        contact_ids: [7, 7],
        action: { action: 'add_tag', tag_id: 3 },
      }),
    ];

    for (const operation of operations) {
      await expect(operation).rejects.toBeInstanceOf(CommandDecodeError);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([404, 422])('propagates the shared bounded HTTP error for status %i', async (status) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'Safe failure' }, status));
    vi.stubGlobal('fetch', fetchMock);

    const promise = contactsApi.detail(7);

    await expect(promise).rejects.toBeInstanceOf(CommandHttpError);
    await expect(promise).rejects.toMatchObject({ status, detail: 'Safe failure' });
  });
});
