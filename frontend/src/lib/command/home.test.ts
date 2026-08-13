import { describe, expect, it, vi } from 'vitest';
import {
  adaptHomeCelebrations,
  buildCommandHomeModel,
  loadAllContacts,
  loadCommandHome,
  loadHomeSmartViewCounts,
  type CommandHomeApi,
} from './home';
import { CommandDecodeError } from './http';
import type { ContactDirectoryRow } from './contacts';
import {
  completeHomeInput,
  emptyButAvailableInput,
  emptyButUnavailableInput,
} from '@/test/fixtures/commandHome';

const now = new Date('2026-08-12T13:00:00.000Z');

function directoryRow(id: number, stage = 'lead'): ContactDirectoryRow {
  return {
    id,
    first_name: `Contact ${id}`,
    last_name: 'Synthetic',
    display_name: `Contact ${id} Synthetic`,
    primary_email: null,
    primary_phone: null,
    stage,
    lead_backed: false,
    origins: ['recovered'],
    sources: ['kw_command'],
    health_score: null,
    last_contacted_at: null,
    last_interaction_at: null,
    owner: null,
    assignee: null,
    tags: [],
    birthday: null,
    anniversary: null,
    evidence_quality: 'complete' as const,
  };
}

function directoryPage(page: number, rows: readonly ContactDirectoryRow[], total = 366) {
  return {
    rows,
    total,
    page,
    page_size: 100,
    page_count: total === 0 ? 0 : Math.ceil(total / 100),
    sort: 'name' as const,
    direction: 'asc' as const,
  };
}

describe('Home contact loading contracts', () => {
  it('loads all 366 contacts across exact stable 100/100/100/66 pages with one signal', async () => {
    const pages = [
      Array.from({ length: 100 }, (_value, index) => directoryRow(index + 1)),
      Array.from({ length: 100 }, (_value, index) => directoryRow(index + 101)),
      Array.from({ length: 100 }, (_value, index) => directoryRow(index + 201)),
      Array.from({ length: 66 }, (_value, index) => directoryRow(index + 301)),
    ];
    const contactDirectory = vi.fn().mockImplementation(
      async (request: { page?: number }) => directoryPage(request.page ?? 1, pages[(request.page ?? 1) - 1] ?? []),
    );
    const controller = new AbortController();

    await expect(loadAllContacts({ contactDirectory }, controller.signal)).resolves.toHaveLength(366);
    expect(contactDirectory).toHaveBeenCalledTimes(4);
    pages.forEach((_rows, index) => {
      expect(contactDirectory).toHaveBeenNthCalledWith(index + 1, {
        smart_view: 'all',
        sort: 'name',
        direction: 'asc',
        page: index + 1,
        page_size: 100,
      }, { signal: controller.signal });
    });
  });

  it.each([
    ['duplicate ids', [directoryPage(1, [directoryRow(1), directoryRow(1)], 2)]],
    ['total drift', [
      directoryPage(1, Array.from({ length: 100 }, (_value, index) => directoryRow(index + 1)), 101),
      directoryPage(2, [directoryRow(101)], 102),
    ]],
    ['early empty page', [
      directoryPage(1, Array.from({ length: 100 }, (_value, index) => directoryRow(index + 1)), 101),
      directoryPage(2, [], 101),
    ]],
    ['final count mismatch', [
      directoryPage(1, Array.from({ length: 100 }, (_value, index) => directoryRow(index + 1)), 102),
      directoryPage(2, [directoryRow(101)], 102),
    ]],
  ])('rejects %s as unstable contact pagination', async (_name, pages) => {
    const contactDirectory = vi.fn().mockImplementation(
      async (request: { page?: number }) => pages[(request.page ?? 1) - 1] ?? pages[pages.length - 1],
    );
    await expect(loadAllContacts({ contactDirectory })).rejects.toMatchObject({
      constructor: CommandDecodeError,
      path: 'contacts',
      expected: 'stable complete pagination',
    });
  });

  it('returns an exact empty collection for the zero-page server contract', async () => {
    const contactDirectory = vi.fn().mockResolvedValue(directoryPage(1, [], 0));
    await expect(loadAllContacts({ contactDirectory })).resolves.toEqual([]);
    expect(contactDirectory).toHaveBeenCalledTimes(1);
  });

  it('propagates a native abort rejection unchanged', async () => {
    const abort = new DOMException('Stopped', 'AbortError');
    const contactDirectory = vi.fn().mockRejectedValue(abort);
    await expect(loadAllContacts({ contactDirectory })).rejects.toBe(abort);
  });

  it('issues exactly four page-size-one SmartView count probes with one signal', async () => {
    const totals = [12, 23, 4, 5];
    const contactDirectory = vi.fn().mockImplementation(async (request: { page?: number }) => ({
      ...directoryPage(request.page ?? 1, [directoryRow(1)], totals.shift() ?? 0),
      page_size: 1,
    }));
    const controller = new AbortController();

    await expect(loadHomeSmartViewCounts({ contactDirectory }, controller.signal)).resolves.toEqual({
      never_contacted: 12,
      recently_active: 23,
      birthdays_this_month: 4,
      anniversaries_this_month: 5,
    });
    expect(contactDirectory).toHaveBeenCalledTimes(4);
    expect(contactDirectory.mock.calls.map(([request]) => request)).toEqual([
      { smart_view: 'never_contacted', sort: 'name', direction: 'asc', page: 1, page_size: 1 },
      { smart_view: 'recently_active', sort: 'name', direction: 'asc', page: 1, page_size: 1 },
      { smart_view: 'birthdays_this_month', sort: 'name', direction: 'asc', page: 1, page_size: 1 },
      { smart_view: 'anniversaries_this_month', sort: 'name', direction: 'asc', page: 1, page_size: 1 },
    ]);
    expect(contactDirectory.mock.calls.every((call) => call[1]?.signal === controller.signal)).toBe(true);
  });

  it('adapts and preserves all four valid celebration year qualities', () => {
    const adapted = adaptHomeCelebrations({
      birthdays: [
        {
          contact_id: 6,
          display_name: 'Verified Year',
          kind: 'birthday',
          month: 8,
          day: 12,
          year: 1984,
          year_quality: 'verified',
          origin: 'internal_crm',
        },
        {
          contact_id: 7,
          display_name: 'Yearless',
          kind: 'birthday',
          month: 8,
          day: 13,
          year: null,
          year_quality: 'yearless',
          origin: 'recovered',
        },
        {
          contact_id: 8,
          display_name: 'Sentinel',
          kind: 'birthday',
          month: 8,
          day: 14,
          year: null,
          year_quality: 'sentinel',
          origin: 'recovered',
        },
        {
          contact_id: 9,
          display_name: 'Unknown',
          kind: 'birthday',
          month: 8,
          day: 15,
          year: null,
          year_quality: 'unknown',
          origin: 'recovered',
        },
      ],
      anniversaries: [],
    });

    expect(adapted.birthdays.map((row) => ({
      contactId: row.contactId,
      year: row.year,
      yearQuality: row.yearQuality,
      origin: row.origin,
    }))).toEqual([
      { contactId: 6, year: 1984, yearQuality: 'verified', origin: 'internal_crm' },
      { contactId: 7, year: null, yearQuality: 'yearless', origin: 'recovered' },
      { contactId: 8, year: null, yearQuality: 'sentinel', origin: 'recovered' },
      { contactId: 9, year: null, yearQuality: 'unknown', origin: 'recovered' },
    ]);
  });

  it('rejects fabricated or mismatched celebration semantics without exposing row values', () => {

    for (const value of [
      { kind: 'anniversary', year: null, year_quality: 'yearless' },
      { kind: 'birthday', year: 1900, year_quality: 'sentinel' },
      { kind: 'birthday', year: null, year_quality: 'verified' },
      { kind: 'birthday', year: 2020, year_quality: 'unknown' },
    ] as const) {
      expect(() => adaptHomeCelebrations({
        birthdays: [{
          contact_id: 7,
          display_name: 'Private',
          month: 8,
          day: 13,
          origin: 'recovered',
          ...value,
        }],
        anniversaries: [],
      })).toThrow(CommandDecodeError);
    }

    expect(() => adaptHomeCelebrations({
      birthdays: [{
        contact_id: 7,
        display_name: 'Private',
        kind: 'anniversary',
        month: 8,
        day: 13,
        year: null,
        year_quality: 'yearless',
        origin: 'recovered',
      }],
      anniversaries: [],
    })).toThrowError(expect.not.stringContaining('Private'));
  });
});

describe('Follow-Up Readiness', () => {
  it('penalizes overdue work and never-contacted leads using observed values', () => {
    const model = buildCommandHomeModel(completeHomeInput, now);

    expect(model.readiness.coverage).toEqual({ available: 4, total: 4 });
    expect(model.readiness.status).toBe('at_risk');
    expect(model.readiness.factors.map((factor) => factor.key)).toEqual([
      'overdue_tasks',
      'uncontacted_leads',
      'contact_health',
      'active_opportunities',
    ]);
    expect(model.readiness.factors).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: 'overdue_tasks', score: 25, affected: 3, total: 4, weight: 35 }),
        expect.objectContaining({ key: 'uncontacted_leads', score: 33, affected: 2, total: 3, weight: 30 }),
        expect.objectContaining({ key: 'contact_health', score: 75, affected: 1, total: 4, weight: 20 }),
        expect.objectContaining({ key: 'active_opportunities', score: 50, affected: 2, total: 4, weight: 15 }),
      ]),
    );
    expect(model.nextActions[0]).toMatchObject({
      kind: 'overdue_tasks',
      affected: 3,
      href: '/admin/command/tasks?tab=todo&due=past',
    });
  });

  it('marks readiness partial when the server-owned SmartView totals are unavailable', () => {
    const model = buildCommandHomeModel({
      ...completeHomeInput,
      smartViewCounts: null,
    }, now);

    expect(model.readiness.status).toBe('partial');
    expect(model.readiness.coverage).toEqual({ available: 3, total: 4 });
    expect(model.readiness.factors.find((factor) => factor.key === 'uncontacted_leads')).toMatchObject({
      available: false,
      score: null,
      affected: null,
      total: null,
      insight: 'Last-contact history is unavailable.',
    });
    expect(model.readiness.label).toContain('3 of 4 inputs verified');
    expect(model.nextActions.some((action) => action.kind === 'uncontacted_leads')).toBe(false);
  });

  it('uses only divergent server totals for all four SmartView counts and normalizes lead stages', () => {
    const model = buildCommandHomeModel({
      ...completeHomeInput,
      contacts: (completeHomeInput.contacts ?? []).map((contact, index) => ({
        ...contact,
        stage: index < 3 ? ' Lead ' : contact.stage,
      })),
      smartViewCounts: {
        never_contacted: 1,
        recently_active: 41,
        birthdays_this_month: 42,
        anniversaries_this_month: 43,
      },
    }, now);

    expect(model.readiness.factors.find((factor) => factor.key === 'uncontacted_leads')).toMatchObject({
      available: true,
      score: 67,
      affected: 1,
      total: 3,
      href: '/admin/command/contacts?smart_view=never_contacted',
    });
    expect(model.shortcuts.map(({ key, count, href }) => ({ key, count, href }))).toEqual([
      { key: 'never_contacted', count: 1, href: '/admin/command/contacts?smart_view=never_contacted' },
      { key: 'recently_active', count: 41, href: '/admin/command/contacts?smart_view=recently_active' },
      { key: 'birthdays', count: 42, href: '/admin/command/contacts?smart_view=birthdays_this_month' },
      { key: 'anniversaries', count: 43, href: '/admin/command/contacts?smart_view=anniversaries_this_month' },
    ]);
    expect(model.kpis.find((kpi) => kpi.key === 'never_contacted')).toMatchObject({
      value: '1',
      href: '/admin/command/contacts?smart_view=never_contacted',
    });
    expect(model.nextActions.find((action) => action.kind === 'uncontacted_leads')).toMatchObject({
      affected: 1,
      href: '/admin/command/contacts?smart_view=never_contacted',
    });
  });

  it('never converts unavailable data into a zero count or perfect score', () => {
    const model = buildCommandHomeModel(emptyButUnavailableInput, now);

    expect(model.readiness.score).toBeNull();
    expect(model.readiness.status).toBe('partial');
    expect(model.shortcuts.find((shortcut) => shortcut.key === 'never_contacted')?.count).toBeNull();
    expect(model.shortcuts.find((shortcut) => shortcut.key === 'never_contacted')?.evidenceState).toBe('partial_capture');
    expect(model.kpis.map((kpi) => kpi.value)).toEqual(['Unavailable', 'Unavailable', 'Unavailable', 'Unavailable']);
    expect(model.nextActions).toEqual([]);
  });

  it('returns neutral scores with explicit no-record insights for available empty regions', () => {
    const model = buildCommandHomeModel(emptyButAvailableInput, now);

    expect(model.readiness.score).toBe(100);
    expect(model.readiness.status).toBe('ready');
    expect(model.readiness.factors.every((factor) => factor.insight === 'No records in scope.')).toBe(true);
    expect(model.shortcuts.find((shortcut) => shortcut.key === 'never_contacted')).toMatchObject({
      count: 0,
      evidenceState: 'observed_record',
    });
  });

  it('keeps the secondary metric strip at exactly four fixed tiles', () => {
    const model = buildCommandHomeModel(completeHomeInput, now);

    expect(model.kpis).toHaveLength(4);
    expect(model.kpis.map((kpi) => kpi.key)).toEqual([
      'never_contacted',
      'open_tasks',
      'active_opportunities',
      'contactable_profiles',
    ]);
    expect(model.kpis.find((kpi) => kpi.key === 'active_opportunities')).toMatchObject({
      value: '2',
      insight: expect.stringContaining('$1,235,000'),
    });
  });

  it('keeps celebrations and SmartView shortcuts unavailable when their source regions are absent', () => {
    const withoutSmartViews = buildCommandHomeModel({
      ...completeHomeInput,
      smartViewCounts: null,
    }, now);
    const unavailable = buildCommandHomeModel(emptyButUnavailableInput, now);

    expect(withoutSmartViews.shortcuts.find((shortcut) => shortcut.key === 'recently_active')).toMatchObject({
      count: null,
      evidenceState: 'partial_capture',
    });
    expect(unavailable.shortcuts.find((shortcut) => shortcut.key === 'birthdays')?.count).toBeNull();
    expect(unavailable.shortcuts.find((shortcut) => shortcut.key === 'anniversaries')?.count).toBeNull();
    expect(unavailable.celebrations).toBeNull();
    expect(unavailable.bookingsState).toBe('partial_capture');
  });

  it('sorts tasks and recent contacts only from supplied factual timestamps', () => {
    const model = buildCommandHomeModel(completeHomeInput, now);

    expect(model.tasks?.map((task) => task.id)).toEqual([1, 2, 3, 4]);
    expect(model.recentContacts.map((contact) => contact.id)).toEqual([3, 4]);
  });
});

function makeApi(overrides: Partial<CommandHomeApi> = {}): CommandHomeApi {
  const rows = (completeHomeInput.contacts ?? []).map((contact) => ({
    ...directoryRow(contact.id, contact.stage),
    first_name: contact.first_name,
    last_name: contact.last_name,
    display_name: `${contact.first_name} ${contact.last_name}`,
    primary_email: contact.email,
    primary_phone: contact.phone,
    health_score: contact.health_score ?? null,
    last_contacted_at: contact.last_contacted_at ?? null,
    last_interaction_at: contact.recently_active_at ?? null,
  }));
  const totals = {
    never_contacted: 2,
    recently_active: 2,
    birthdays_this_month: 1,
    anniversaries_this_month: 1,
  } as const;
  return {
    overview: vi.fn().mockResolvedValue(completeHomeInput.overview),
    contactDirectory: vi.fn().mockImplementation(async (
      request: Parameters<CommandHomeApi['contactDirectory']>[0],
    ) => request.smart_view === 'all'
      ? directoryPage(request.page ?? 1, rows, rows.length)
      : {
          ...directoryPage(1, [rows[0]], totals[request.smart_view ?? 'never_contacted']),
          page_size: 1,
          page_count: totals[request.smart_view ?? 'never_contacted'],
        }),
    tasks: vi.fn().mockResolvedValue(completeHomeInput.tasks),
    opportunities: vi.fn().mockResolvedValue(completeHomeInput.opportunities),
    celebrations: vi.fn().mockResolvedValue({
      birthdays: [{
        contact_id: 1,
        display_name: 'Avery Lake',
        kind: 'birthday',
        month: 8,
        day: 21,
        year: 1991,
        year_quality: 'verified',
        origin: 'internal_crm',
      }],
      anniversaries: [{
        contact_id: 2,
        display_name: 'Morgan Hill',
        kind: 'anniversary',
        month: 8,
        day: 12,
        year: 2018,
        year_quality: 'verified',
        origin: 'internal_crm',
      }],
    }),
    goals: vi.fn().mockResolvedValue(completeHomeInput.goals),
    aiBriefing: vi.fn().mockResolvedValue(completeHomeInput.briefing),
    ...overrides,
  };
}

describe('loadCommandHome', () => {
  it('loads 366 contacts, four SmartView probes, and six regions with one identical signal', async () => {
    const pages = [
      Array.from({ length: 100 }, (_value, index) => directoryRow(index + 1)),
      Array.from({ length: 100 }, (_value, index) => directoryRow(index + 101)),
      Array.from({ length: 100 }, (_value, index) => directoryRow(index + 201)),
      Array.from({ length: 66 }, (_value, index) => directoryRow(index + 301)),
    ];
    const api = makeApi({
      contactDirectory: vi.fn().mockImplementation(async (
        request: Parameters<CommandHomeApi['contactDirectory']>[0],
      ) => request.smart_view === 'all'
        ? directoryPage(request.page ?? 1, pages[(request.page ?? 1) - 1] ?? [])
        : {
            ...directoryPage(1, [directoryRow(1)], request.smart_view === 'never_contacted' ? 1 : 7),
            page_size: 1,
            page_count: request.smart_view === 'never_contacted' ? 1 : 7,
          }),
    });
    const controller = new AbortController();
    const model = await loadCommandHome(api, now, controller.signal);

    expect(api.contactDirectory).toHaveBeenCalledTimes(8);
    expect(api.tasks).toHaveBeenCalledWith({}, { signal: controller.signal });
    expect(api.overview).toHaveBeenCalledWith({ signal: controller.signal });
    expect(api.opportunities).toHaveBeenCalledWith({ signal: controller.signal });
    expect(api.goals).toHaveBeenCalledWith({ signal: controller.signal });
    expect(api.aiBriefing).toHaveBeenCalledWith({ signal: controller.signal });
    expect(api.celebrations).toHaveBeenCalledWith(8, { signal: controller.signal });
    const directoryCalls = vi.mocked(api.contactDirectory).mock.calls;
    expect(directoryCalls.every((call) => call[1]?.signal === controller.signal)).toBe(true);
    expect(
      vi.mocked(api.contactDirectory).mock.calls.length
      + vi.mocked(api.overview).mock.calls.length
      + vi.mocked(api.tasks).mock.calls.length
      + vi.mocked(api.opportunities).mock.calls.length
      + vi.mocked(api.celebrations).mock.calls.length
      + vi.mocked(api.goals).mock.calls.length
      + vi.mocked(api.aiBriefing).mock.calls.length,
    ).toBe(14);
    expect(model.readiness.status).toBe('at_risk');
    expect(model.readiness.coverage).toEqual({ available: 4, total: 4 });
    expect(model.regionErrors).toEqual({});
  });

  it('maps decoded directory fields explicitly into Home contacts', async () => {
    const row = {
      ...directoryRow(91, ' Lead '),
      first_name: 'Wire',
      last_name: 'Person',
      primary_email: 'wire@example.test',
      primary_phone: '+1 555 0191',
      health_score: 87,
      last_contacted_at: null,
      last_interaction_at: '2026-08-11T10:00:00.000Z',
    };
    const api = makeApi({
      contactDirectory: vi.fn().mockImplementation(async (
        request: Parameters<CommandHomeApi['contactDirectory']>[0],
      ) => request.smart_view === 'all'
        ? directoryPage(1, [row], 1)
        : {
            ...directoryPage(1, request.smart_view === 'never_contacted' ? [] : [row], request.smart_view === 'never_contacted' ? 0 : 1),
            page_size: 1,
            page_count: request.smart_view === 'never_contacted' ? 0 : 1,
          }),
    });

    const model = await loadCommandHome(api, now);

    expect(model.recentContacts).toEqual([{
      id: 91,
      first_name: 'Wire',
      last_name: 'Person',
      email: 'wire@example.test',
      phone: '+1 555 0191',
      stage: ' Lead ',
      last_contacted_at: null,
      recently_active_at: '2026-08-11T10:00:00.000Z',
      health_score: 87,
    }]);
  });

  it('settles contact rows and SmartView counts as one region and rejects inconsistent lead totals', async () => {
    const api = makeApi({
      contactDirectory: vi.fn().mockImplementation(async (
        request: Parameters<CommandHomeApi['contactDirectory']>[0],
      ) => request.smart_view === 'all'
        ? directoryPage(1, [directoryRow(1, 'client')], 1)
        : {
            ...directoryPage(1, [directoryRow(1)], request.smart_view === 'never_contacted' ? 1 : 0),
            page_size: 1,
            page_count: request.smart_view === 'never_contacted' ? 1 : 0,
          }),
    });

    const model = await loadCommandHome(api, now);

    expect(model.recentContacts).toEqual([]);
    expect(model.readiness.factors.find((factor) => factor.key === 'uncontacted_leads')?.available).toBe(false);
    expect(model.shortcuts.every((shortcut) => shortcut.count === null)).toBe(true);
    expect(model.regionErrors.contacts).toContain('consistent SmartView totals');
  });

  it('fails the combined contacts region when any count probe rejects', async () => {
    const api = makeApi({
      contactDirectory: vi.fn().mockImplementation(async (
        request: Parameters<CommandHomeApi['contactDirectory']>[0],
      ) => {
        if (request.smart_view === 'birthdays_this_month') throw new Error('Count unavailable');
        return request.smart_view === 'all'
          ? directoryPage(1, [directoryRow(1)], 1)
          : { ...directoryPage(1, [], 0), page_size: 1 };
      }),
    });

    const model = await loadCommandHome(api, now);

    expect(model.recentContacts).toEqual([]);
    expect(model.shortcuts.every((shortcut) => shortcut.count === null)).toBe(true);
    expect(model.regionErrors.contacts).toBe('Count unavailable');
  });

  it('preserves successful hero/task regions when one optional dependency fails', async () => {
    const api = makeApi({
      celebrations: vi.fn().mockRejectedValue(new Error('Celebrations unavailable')),
    });
    const model = await loadCommandHome(api, now);

    expect(model.readiness.factors.find((factor) => factor.key === 'overdue_tasks')?.available).toBe(true);
    expect(model.tasks).toHaveLength(4);
    expect(model.celebrations).toBeNull();
    expect(model.regionErrors).toMatchObject({ celebrations: 'Celebrations unavailable' });
  });

  it('adapts celebrations before settlement so invalid year semantics fail only that region', async () => {
    const api = makeApi({
      celebrations: vi.fn().mockResolvedValue({
        birthdays: [{
          contact_id: 1,
          display_name: 'Private',
          kind: 'birthday',
          month: 8,
          day: 12,
          year: 1900,
          year_quality: 'sentinel',
          origin: 'recovered',
        }],
        anniversaries: [],
      }),
    });

    const model = await loadCommandHome(api, now);

    expect(model.celebrations).toBeNull();
    expect(model.tasks).toHaveLength(4);
    expect(model.regionErrors.celebrations).toContain('consistent celebration rows');
  });

  it('preserves failed task and goal regions as unavailable instead of verified empty arrays', async () => {
    const api = makeApi({
      tasks: vi.fn().mockRejectedValue(new Error('Tasks unavailable')),
      goals: vi.fn().mockRejectedValue(new Error('Goals unavailable')),
    });
    const model = await loadCommandHome(api, now);

    expect(model.tasks).toBeNull();
    expect(model.goals).toBeNull();
    expect(model.regionErrors).toMatchObject({
      tasks: 'Tasks unavailable',
      goals: 'Goals unavailable',
    });
  });

  it('rejects when every production region fails so the page can render a retryable error', async () => {
    const failed = vi.fn().mockRejectedValue(new Error('Offline'));
    await expect(loadCommandHome({
      overview: failed,
      contactDirectory: failed,
      tasks: failed,
      opportunities: failed,
      celebrations: failed,
      goals: failed,
      aiBriefing: failed,
    }, now)).rejects.toThrow('Command Home could not load any region');
  });

  it('fails before requests for a pre-aborted signal and preserves the exact reason', async () => {
    const api = makeApi();
    const reason = { kind: 'pre-abort' };
    const controller = new AbortController();
    controller.abort(reason);

    await expect(loadCommandHome(api, now, controller.signal)).rejects.toBe(reason);
    expect(api.overview).not.toHaveBeenCalled();
    expect(api.contactDirectory).not.toHaveBeenCalled();
    expect(api.tasks).not.toHaveBeenCalled();
    expect(api.opportunities).not.toHaveBeenCalled();
    expect(api.celebrations).not.toHaveBeenCalled();
    expect(api.goals).not.toHaveBeenCalled();
    expect(api.aiBriefing).not.toHaveBeenCalled();
  });

  it('preserves a mid-flight abort reason after all regions settle', async () => {
    let resolveOverview!: (value: NonNullable<typeof completeHomeInput.overview>) => void;
    const api = makeApi({
      overview: vi.fn().mockImplementation(() => new Promise((resolve) => {
        resolveOverview = resolve;
      })),
    });
    const reason = new Error('mid-flight stop');
    const controller = new AbortController();
    const promise = loadCommandHome(api, now, controller.signal);

    controller.abort(reason);
    resolveOverview(completeHomeInput.overview ?? { contacts: 0, open_tasks: 0, opportunities: 0, active_smart_plans: 0 });

    await expect(promise).rejects.toBe(reason);
  });
});
