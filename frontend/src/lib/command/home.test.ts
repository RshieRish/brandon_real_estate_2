import { describe, expect, it, vi } from 'vitest';
import {
  buildCommandHomeModel,
  loadCommandHome,
  type CommandHomeApi,
} from './home';
import {
  completeHomeInput,
  emptyButAvailableInput,
  emptyButUnavailableInput,
  inputWithoutLastContactFields,
  inputWithoutRecentActivityFields,
} from '@/test/fixtures/commandHome';

const now = new Date('2026-08-12T13:00:00.000Z');

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

  it('marks readiness partial when last-contact coverage is unavailable', () => {
    const model = buildCommandHomeModel(inputWithoutLastContactFields, now);

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

  it('keeps celebrations and recent activity unavailable when their source regions or fields are absent', () => {
    const withoutRecentActivity = buildCommandHomeModel(inputWithoutRecentActivityFields, now);
    const unavailable = buildCommandHomeModel(emptyButUnavailableInput, now);

    expect(withoutRecentActivity.shortcuts.find((shortcut) => shortcut.key === 'recently_active')).toMatchObject({
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

    expect(model.tasks.map((task) => task.id)).toEqual([1, 2, 3, 4]);
    expect(model.recentContacts.map((contact) => contact.id)).toEqual([3, 4]);
  });
});

function makeApi(overrides: Partial<CommandHomeApi> = {}): CommandHomeApi {
  return {
    overview: vi.fn().mockResolvedValue(completeHomeInput.overview),
    contacts: vi.fn().mockImplementation(async (_limit: number, offset: number) => {
      if (offset === 0) return Array.from({ length: 100 }, (_, index) => ({
        id: index + 1,
        first_name: `Contact ${index + 1}`,
        last_name: 'Synthetic',
        email: null,
        phone: null,
        stage: 'lead',
      }));
      return [{ id: 101, first_name: 'Last', last_name: 'Page', email: null, phone: null, stage: 'lead' }];
    }),
    tasks: vi.fn().mockResolvedValue(completeHomeInput.tasks),
    opportunities: vi.fn().mockResolvedValue(completeHomeInput.opportunities),
    celebrations: vi.fn().mockResolvedValue(completeHomeInput.celebrations),
    goals: vi.fn().mockResolvedValue(completeHomeInput.goals),
    aiBriefing: vi.fn().mockResolvedValue(completeHomeInput.briefing),
    ...overrides,
  };
}

describe('loadCommandHome', () => {
  it('loads current regions independently and exhausts all 100-row contact pages', async () => {
    const api = makeApi();
    const model = await loadCommandHome(api, now);

    expect(api.contacts).toHaveBeenNthCalledWith(1, 100, 0);
    expect(api.contacts).toHaveBeenNthCalledWith(2, 100, 100);
    expect(model.readiness.status).toBe('partial');
    expect(model.readiness.coverage).toEqual({ available: 3, total: 4 });
    expect(model.regionErrors).toEqual({});
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

  it('records a typed per-region error map when every request fails', async () => {
    const failed = vi.fn().mockRejectedValue(new Error('Offline'));
    const model = await loadCommandHome({
      overview: failed,
      contacts: failed,
      tasks: failed,
      opportunities: failed,
      celebrations: failed,
      goals: failed,
      aiBriefing: failed,
    }, now);

    expect(model.readiness.score).toBeNull();
    expect(model.regionErrors).toEqual({
      overview: 'Offline',
      contacts: 'Offline',
      tasks: 'Offline',
      opportunities: 'Offline',
      celebrations: 'Offline',
      goals: 'Offline',
      briefing: 'Offline',
    });
  });
});
