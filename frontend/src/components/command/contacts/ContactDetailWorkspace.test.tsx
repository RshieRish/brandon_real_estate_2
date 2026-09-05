import { StrictMode } from 'react';
import { readFileSync } from 'node:fs';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  ContactDetail,
  ContactDirectoryPage,
  ContactDirectoryRequest,
  ContactDirectoryRow,
  ContactEvidence,
  ContactInternalWorkspace,
  ContactLifecycleInternalTask,
  ContactMaterialization,
  ContactSectionName,
  ContactSectionPage,
  ContactTimelinePage,
  ContactWorkspaceSummary,
  ContactsApi,
} from '@/lib/command/contacts';
import { CommandToastProvider } from '../ui/CommandToastProvider';
import { ContactDetailWorkspace } from './ContactDetailWorkspace';
import { canonicalContactId } from '@/app/admin/command/contacts/[contactId]/page';
import { CommandHttpError } from '@/lib/command/http';
import {
  CommandConflictError,
  CommandOutcomeUncertainError,
  type Task,
} from '@/lib/command/tasks';

const navigation = vi.hoisted(() => ({
  pathname: '/admin/command/contacts/7',
  push: vi.fn(),
  replace: vi.fn(),
  search: new URLSearchParams(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push, replace: navigation.replace }),
  useSearchParams: () => navigation.search,
}));

const hash = 'a'.repeat(64);
const artifactHash = 'b'.repeat(64);
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const contact: ContactDirectoryRow = {
  id: 7,
  first_name: 'Ada',
  last_name: 'Lovelace',
  display_name: 'Ada Lovelace',
  primary_email: 'ada@example.test',
  primary_phone: '555-0107',
  stage: 'past client',
  lead_backed: true,
  origins: ['recovered', 'lead_backed'],
  sources: ['kw_command', 'legacy_lead'],
  health_score: 84,
  last_contacted_at: '2026-08-10T15:00:00Z',
  last_interaction_at: '2026-08-11T16:30:00Z',
  owner: { role: 'owner', provider_actor_id: 'owner-1', display_name: 'Brandon Sweeney' },
  assignee: { role: 'assignee', provider_actor_id: 'assignee-2', display_name: 'Sam Agent' },
  tags: [{ id: 3, name: 'VIP' }, { id: 8, name: 'Investor' }],
  birthday: {
    month: 8,
    day: 30,
    year: null,
    year_quality: 'yearless',
    origin: 'recovered',
  },
  anniversary: {
    month: 9,
    day: 23,
    year: 2022,
    year_quality: 'verified',
    origin: 'recovered',
  },
  evidence_quality: 'partial',
};

const detail: ContactDetail = {
  contact,
  lead_id: 44,
  recovered_profile: {
    legal_name: 'Augusta Ada King',
    preferred_name: 'Ada',
    description: 'Analytical engine correspondent',
    company: 'Babbage & Co.',
    title: 'Mathematician',
    lead_source: 'Archive import',
    account_name: 'Lovelace household',
    birthday: contact.birthday,
    anniversary: contact.anniversary,
  },
  addresses: [{
    id: 91,
    address_type: 'home',
    formatted: '12 St. James Square, London',
    latitude: null,
    longitude: null,
    source_record_id: 501,
  }],
  ownership: [
    contact.owner!,
    contact.assignee!,
    { role: 'collaborator', provider_actor_id: 'collab-3', display_name: 'Tess Partner' },
  ],
  tags: contact.tags,
};

const summary: ContactWorkspaceSummary = {
  open_tasks: 3,
  completed_tasks: 2,
  archived_tasks: 2,
  active_smart_plans: 2,
  opportunities: 2,
  notes: 1,
  saved_searches: 1,
  bookings: 2,
};

const expandedSummary: ContactWorkspaceSummary = {
  ...summary,
  active_tasks: 3,
  cancelled_tasks: 1,
  archived_mutable_tasks: 1,
  archived_recovered_evidence: 1,
};

const internalWorkspace: ContactInternalWorkspace = {
  contact: {
    id: 7,
    first_name: 'Ada',
    last_name: 'Lovelace',
    email: null,
    phone: null,
    lead_id: 44,
    birthday: null,
    anniversary: null,
    stage: 'past client',
  },
  timeline: [{
    id: 301,
    kind: 'internal_legacy_shadow',
    summary: 'This decoded duplicate timeline is not rendered',
    created_at: '2026-08-01T12:00:00Z',
  }],
  tasks: [
    {
      id: 102,
      title: 'Second tied task',
      contact_id: 7,
      description: '',
      priority: 'normal',
      due_at: '2026-08-21T14:00:00Z',
      status: 'open',
      archived_at: null,
      archive_reason: null,
      version: 1,
    },
    {
      id: 101,
      title: 'Internal valuation follow-up',
      contact_id: 7,
      description: 'Owned only by SWS.',
      priority: 'high',
      due_at: '2026-08-21T14:00:00Z',
      status: 'open',
      archived_at: null,
      archive_reason: null,
      version: 1,
    },
    {
      id: 103,
      title: 'Internal completed task',
      contact_id: 7,
      description: '',
      priority: 'low',
      due_at: null,
      status: 'completed',
      archived_at: null,
      archive_reason: null,
      version: 2,
    },
    {
      id: 104,
      title: 'Internal archived task',
      contact_id: 7,
      description: '',
      priority: 'normal',
      due_at: null,
      status: 'completed',
      archived_at: '2026-08-19T15:30:00Z',
      archive_reason: 'Superseded reminder',
      version: 4,
    },
  ],
  notes: [{
    id: 111,
    contact_id: 7,
    body: 'Internal follow-up note that has no capture occurrence.',
    created_at: '2026-08-12T12:00:00Z',
    updated_at: '2026-08-12T12:00:00Z',
  }],
  smart_plans: [{ id: 121, plan_id: 22, status: 'active' }],
  opportunities: [{
    id: 73,
    name: 'Internal listing opportunity',
    stage: 'active',
    value_cents: 51000000,
    role: 'seller',
  }],
  saved_searches: [{ id: 131, name: 'Internal downsizer search', criteria: '{"beds":2}' }],
  bookings: [
    {
      id: 142,
      meeting_type: 'consultation',
      context: 'Listing strategy',
      scheduled_at: '2026-09-02T14:00:00Z',
      location: 'SWS office',
      notes: 'Bring tax records.',
    },
    {
      id: 141,
      meeting_type: 'valuation',
      context: 'Walkthrough',
      scheduled_at: '2026-09-02T14:00:00Z',
      location: null,
      notes: '',
    },
  ],
  tags: [{ id: 999, name: 'Decoded duplicate tag is not rendered' }],
};

const archivedInternalTask = internalWorkspace.tasks.find(
  (task): task is ContactLifecycleInternalTask => task.id === 104 && 'archived_at' in task,
)!;
const restoredInternalTask: ContactLifecycleInternalTask = {
  ...archivedInternalTask,
  archived_at: null,
  archive_reason: null,
  version: 5,
};
const restoredInternalWorkspace: ContactInternalWorkspace = {
  ...internalWorkspace,
  tasks: internalWorkspace.tasks.map((task) => task.id === 104 ? restoredInternalTask : task),
};
const restoredSummary: ContactWorkspaceSummary = {
  ...expandedSummary,
  completed_tasks: 3,
  archived_tasks: 1,
  archived_mutable_tasks: 0,
};

const timeline: ContactTimelinePage = {
  rows: [
    {
      key: 'activity:30',
      origin: 'internal_crm',
      kind: 'call',
      title: 'Discovery call completed',
      body: 'Discussed a possible September listing.',
      outcome: 'Follow up next Tuesday',
      occurred_at: '2026-08-10T15:00:00Z',
      source_record_id: null,
      entity_type: 'activity',
      entity_id: 30,
    },
    {
      key: 'booking:31',
      origin: 'booking',
      kind: 'booking',
      title: 'Consultation booked',
      body: 'SWS consultation at the office.',
      outcome: null,
      occurred_at: '2026-08-12T14:00:00Z',
      source_record_id: null,
      entity_type: 'booking',
      entity_id: 31,
    },
  ],
  next_cursor: null,
  has_more: false,
};

type OccurrenceOverrides = Readonly<{
  status?: 'source_only' | 'materialized';
  source_record_id?: number;
  source_key_hash?: string;
  section: ContactSectionName;
  occurrence_ordinal?: number;
  capture_quality?: 'complete' | 'partial' | 'shell' | 'error';
  captured_at?: string | null;
  value: ContactMaterialization['value'];
  entity_type?: 'note' | 'saved_search' | 'task' | 'smart_plan' | 'opportunity';
  entity_id?: number;
}>;

function occurrence(overrides: OccurrenceOverrides): ContactMaterialization {
  return {
    status: 'source_only',
    source_record_id: 501,
    source_key_hash: hash,
    occurrence_ordinal: 1,
    capture_quality: 'partial',
    captured_at: '2026-08-01T12:00:00Z',
    ...overrides,
  } as ContactMaterialization;
}

const pages: Readonly<Record<Exclude<ContactSectionName, 'timeline'>, ContactSectionPage>> = {
  opportunities: sectionPage([
    occurrence({
      section: 'opportunities',
      value: { kind: 'opportunity', title: 'Archive seller opportunity', stage: 'consultation', value_cents: 42500000 },
    }),
    occurrence({
      status: 'materialized',
      section: 'opportunities',
      occurrence_ordinal: 2,
      value: { kind: 'opportunity', title: 'Internal listing opportunity', stage: 'active', value_cents: 51000000 },
      entity_type: 'opportunity',
      entity_id: 73,
    }),
  ]),
  smart_plans: sectionPage([
    occurrence({
      section: 'smart_plans',
      value: { kind: 'smart_plan', title: 'Recovered quarterly touch', status: 'active' },
    }),
    occurrence({
      status: 'materialized',
      section: 'smart_plans',
      occurrence_ordinal: 2,
      value: { kind: 'smart_plan', title: 'Missing materialized plan', status: 'paused' },
      entity_type: 'smart_plan',
      entity_id: 999,
    }),
  ]),
  tasks_to_do: sectionPage([
    occurrence({
      section: 'tasks_to_do',
      value: { kind: 'task', title: 'Call about valuation', description: 'Review comparable sales.', state: 'to_do', due_at: '2026-08-20T14:00:00Z' },
    }),
  ]),
  tasks_completed: sectionPage([
    occurrence({
      section: 'tasks_completed',
      value: { kind: 'task', title: 'Send market report', description: null, state: 'completed', due_at: null },
    }),
  ]),
  tasks_archived: sectionPage([
    occurrence({
      section: 'tasks_archived',
      value: { kind: 'task', title: 'Old reminder', description: null, state: 'archived', due_at: null },
    }),
  ]),
  notes: sectionPage([]),
  saved_searches: sectionPage([]),
};

function sectionPage(rows: readonly ContactMaterialization[]): ContactSectionPage {
  return {
    rows,
    total: rows.length,
    page: 1,
    page_size: 50,
    page_count: rows.length > 0 ? 1 : 0,
  };
}

const evidenceMatrix: ContactEvidence['section_matrix'] = [
  {
    capture_position_id: 901,
    section: 'timeline',
    source_record_id: 501,
    capture_quality: 'complete',
    row_count: 2,
    is_empty: false,
    limitation_codes: [],
  },
  {
    capture_position_id: 901,
    section: 'opportunities',
    source_record_id: 501,
    capture_quality: 'partial',
    row_count: 2,
    is_empty: false,
    limitation_codes: ['redacted_placeholder_evidence'],
  },
  {
    capture_position_id: 901,
    section: 'smart_plans',
    source_record_id: 501,
    capture_quality: 'partial',
    row_count: 2,
    is_empty: false,
    limitation_codes: [],
  },
  {
    capture_position_id: 901,
    section: 'notes',
    source_record_id: 501,
    capture_quality: 'complete',
    row_count: 0,
    is_empty: true,
    limitation_codes: [],
  },
  {
    capture_position_id: 901,
    section: 'saved_searches',
    source_record_id: 501,
    capture_quality: 'shell',
    row_count: 0,
    is_empty: true,
    limitation_codes: ['shell_only'],
  },
  ...(['tasks_to_do', 'tasks_completed', 'tasks_archived'] as const).map((section) => ({
    capture_position_id: 901,
    section,
    source_record_id: 501,
    capture_quality: 'partial' as const,
    row_count: 1,
    is_empty: false,
    limitation_codes: [],
  })),
];

const evidence: ContactEvidence = {
  contact_id: 7,
  provider_contact_rows: 317,
  resolved_provider_identities: 317,
  coalesced_aliases: 0,
  lead_backed_contacts: 51,
  reviewed_overlaps: 2,
  legacy_only_contacts: 49,
  capture_positions: [{
    capture_position_id: 901,
    capture_ordinal: 1,
    source_record_id: 501,
    capture_quality: 'partial',
    sections: evidenceMatrix,
  }],
  section_matrix: evidenceMatrix,
  sources: [{
    source_record_id: 501,
    record_kind: 'provider_contact_detail',
    evidence_level: 'observed_record',
    capture_quality: 'partial',
    captured_at: '2026-08-01T12:00:00Z',
    artifacts: [{
      artifact_id: 55,
      artifact_type: 'html',
      sha256: artifactHash,
      size_bytes: 4096,
      content_href: '/api/v1/command/archive/artifacts/55/content',
    }],
  }],
  capture_quality: 'partial',
};

function directoryPage(rows: readonly ContactDirectoryRow[]): ContactDirectoryPage {
  return {
    rows,
    total: rows.length,
    page: 1,
    page_size: 10,
    page_count: rows.length > 0 ? 1 : 0,
    sort: 'name',
    direction: 'asc',
  };
}

function fakeApi(): ContactsApi {
  return {
    directory: vi.fn().mockResolvedValue(directoryPage([])),
    detail: vi.fn().mockResolvedValue(detail),
    neighbors: vi.fn().mockResolvedValue({ previous_contact_id: 5, next_contact_id: 9 }),
    workspace: vi.fn().mockResolvedValue(summary),
    internalWorkspace: vi.fn().mockResolvedValue(internalWorkspace),
    timeline: vi.fn().mockResolvedValue(timeline),
    section: vi.fn().mockImplementation((
      _id: number,
      section: Exclude<ContactSectionName, 'timeline'>,
    ) => Promise.resolve(pages[section])),
    evidence: vi.fn().mockResolvedValue(evidence),
    celebrations: vi.fn(),
    create: vi.fn(),
    update: vi.fn().mockResolvedValue({
      id: 7,
      first_name: 'Ada',
      last_name: 'Lovelace',
      email: 'ada@example.test',
      phone: '555-0107',
      lead_id: 44,
      birthday: null,
      anniversary: '2022-09-23',
      stage: 'past client',
    }),
    bulk: vi.fn(),
    createNote: vi.fn().mockResolvedValue({ id: 201, body: 'Internal note' }),
    deleteNote: vi.fn().mockResolvedValue({ deleted: true, id: 111 }),
    createSavedSearch: vi.fn().mockResolvedValue({ id: 202, name: 'Internal search', criteria: '{}' }),
    createTag: vi.fn().mockResolvedValue({ id: 203, name: 'Seller' }),
    assignTag: vi.fn().mockResolvedValue({ contact_id: 7, tag_id: 203 }),
    removeTag: vi.fn().mockResolvedValue({ removed: true, contact_id: 7, tag_id: 3 }),
    createTask: vi.fn().mockResolvedValue({
      id: 204,
      title: 'New task',
      contact_id: 7,
      description: '',
      priority: 'normal',
      due_at: null,
      status: 'open',
      archived_at: null,
      archive_reason: null,
      version: 1,
    }),
    restoreTask: vi.fn().mockResolvedValue({
      id: 104,
      title: 'Internal archived task',
      contact_id: 7,
      description: '',
      priority: 'normal',
      due_at: null,
      status: 'completed',
      archived_at: null,
      archive_reason: null,
      version: 5,
    }),
    artifactBlob: vi.fn().mockResolvedValue(new Blob(['archive evidence'], { type: 'text/html' })),
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function workspace(api: ContactsApi, contactId = 7) {
  return (
    <CommandToastProvider>
      <ContactDetailWorkspace contactId={contactId} api={api} />
    </CommandToastProvider>
  );
}

function renderWorkspace(api: ContactsApi, contactId = 7, strict = false) {
  const content = workspace(api, contactId);
  return render(strict ? <StrictMode>{content}</StrictMode> : content);
}

async function openArchivedInternalTask(api: ContactsApi) {
  renderWorkspace(api);
  await screen.findByRole('heading', { name: 'Ada Lovelace' });
  await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));
  await userEvent.click(screen.getByRole('tab', { name: 'Archived' }));
  return screen.findByRole('button', { name: 'Restore Internal archived task' });
}

describe('ContactDetailWorkspace', () => {
  beforeEach(() => {
    navigation.pathname = '/admin/command/contacts/7';
    navigation.search = new URLSearchParams();
    navigation.push.mockReset();
    navigation.replace.mockReset();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:command-evidence'),
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    });
  });

  it('loads decoded detail boundaries once and renders the split identity profile', async () => {
    const api = fakeApi();
    renderWorkspace(api, 7, true);

    expect(await screen.findByRole('heading', { name: 'Ada Lovelace' })).toBeInTheDocument();
    expect(api.detail).toHaveBeenCalledTimes(1);
    expect(api.workspace).toHaveBeenCalledTimes(1);
    expect(api.internalWorkspace).toHaveBeenCalledTimes(1);
    expect(api.neighbors).toHaveBeenCalledTimes(1);
    expect(api.timeline).toHaveBeenCalledTimes(1);
    expect(api.detail).toHaveBeenCalledWith(7, { signal: expect.any(AbortSignal) });
    expect(api.workspace).toHaveBeenCalledWith(7, { signal: expect.any(AbortSignal) });
    expect(api.internalWorkspace).toHaveBeenCalledWith(7, { signal: expect.any(AbortSignal) });
    expect(api.neighbors).toHaveBeenCalledWith(7, expect.any(Object), { signal: expect.any(AbortSignal) });
    expect(api.timeline).toHaveBeenCalledWith(7, null, 50, { signal: expect.any(AbortSignal) });
    expect(screen.getByText('84')).toBeInTheDocument();
    expect(screen.getByText('ada@example.test')).toBeInTheDocument();
    expect(screen.getByText('555-0107')).toBeInTheDocument();
    expect(screen.getByText('Brandon Sweeney')).toBeInTheDocument();
    expect(screen.getByText('Sam Agent')).toBeInTheDocument();
    expect(screen.getByText('Tess Partner')).toBeInTheDocument();
    expect(screen.getByText('VIP')).toBeInTheDocument();
    expect(screen.getByText('Investor')).toBeInTheDocument();
    expect(screen.getByText('Babbage & Co.')).toBeInTheDocument();
    expect(screen.getByText('Analytical engine correspondent')).toBeInTheDocument();
    expect(document.querySelector('.command-contact-detail-grid')).not.toBeNull();
    expect(document.querySelector('.command-contact-profile-column')).not.toBeNull();
  });

  it('shows date-only and literal recovered task due dates without a timezone shift', async () => {
    const api = fakeApi();
    vi.mocked(api.section).mockResolvedValue(sectionPage([
      occurrence({ section: 'tasks_to_do', source_record_id: 801, value: {
        kind: 'task', title: 'Date-only reminder', description: null, state: 'to_do',
        due_at: null, due_date: '2026-08-30', due_date_text: '08/30/2026',
      } }),
      occurrence({ section: 'tasks_to_do', source_record_id: 802, value: {
        kind: 'task', title: 'Ambiguous source date', description: null, state: 'to_do',
        due_at: null, due_date: null, due_date_text: '09/06/2026',
      } }),
    ]));
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));

    const captured = await screen.findByRole('region', { name: 'Captured source to-do tasks' });
    expect(await within(captured).findByText('Due Aug 30, 2026')).toBeInTheDocument();
    expect(within(captured).getByText('Due date as captured: 09/06/2026')).toBeInTheDocument();
    expect(within(captured).queryByText('Due date was not captured')).not.toBeInTheDocument();
  });

  it('shows an internal task due timestamp when SWS already has one', async () => {
    renderWorkspace(fakeApi());
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));

    const task = screen.getByRole('article', { name: 'SWS internal task 101' });
    const due = within(task).getByText(`Due ${new Date('2026-08-21T14:00:00Z').toLocaleString()}`);
    expect(due).toHaveAttribute('datetime', '2026-08-21T14:00:00Z');
  });

  it('labels captured opportunity budgets separately from opportunity value', async () => {
    const api = fakeApi();
    vi.mocked(api.section).mockResolvedValue(sectionPage([
      occurrence({ section: 'opportunities', source_record_id: 803, value: {
        kind: 'opportunity', title: 'Condo search', stage: 'active',
        value_cents: 0, budget: '$440,000.00',
      } }),
    ]));
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Opportunities' }));

    const captured = await screen.findByRole('region', { name: 'Captured source opportunities' });
    expect(await within(captured).findByText('Budget: $440,000.00')).toBeInTheDocument();
    expect(within(captured).getByText('Value: $0')).toBeInTheDocument();
    expect(within(captured).queryByText('Value: $440,000')).not.toBeInTheDocument();
  });

  it('shows separate current and recovered counts instead of describing their sum as SWS-owned', async () => {
    const api = fakeApi();
    const counts = {
      active_tasks: 10, completed_tasks: 0, cancelled_tasks: 0, archived_tasks: 0,
      active_smart_plans: 0, opportunities: 0, notes: 0, saved_searches: 0, bookings: 0,
    };
    vi.mocked(api.workspace).mockResolvedValue({
      ...expandedSummary, open_tasks: 20, active_tasks: 20,
      internal_counts: counts, recovered_counts: counts,
    });
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });

    const countStrip = screen.getByRole('complementary', { name: 'Contact workspace counts' });
    expect(within(countStrip).getByText('10 SWS')).toBeVisible();
    expect(within(countStrip).getByText('10 recovered')).toBeVisible();
    expect(within(countStrip).queryByText('20')).not.toBeInTheDocument();
    expect(within(countStrip).queryByText('SWS-owned records')).not.toBeInTheDocument();
  });

  it('uses stored SmartPlan names and readable saved-search criteria', async () => {
    const api = fakeApi();
    vi.mocked(api.internalWorkspace).mockResolvedValue({
      ...internalWorkspace,
      smart_plans: [{ id: 121, plan_id: 1, plan_name: 'Quarterly homeowner check-in', status: 'active' }],
      saved_searches: [{
        id: 131, name: 'Lakeside condos', criteria: '{"beds":2}', criteria_summary: ['Beds: 2'],
      }],
    });
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'SmartPlans' }));
    expect(await within(screen.getByRole('region', { name: 'SWS internal SmartPlans' })).findByRole(
      'heading', { name: 'Quarterly homeowner check-in' },
    )).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Saved Searches' }));
    const searches = screen.getByRole('region', { name: 'SWS internal saved searches' });
    expect(await within(searches).findByText('Beds: 2')).toBeInTheDocument();
    expect(within(searches).queryByText('{"beds":2}')).not.toBeInTheDocument();
  });

  it('reveals unsupported nested saved-search criteria without replacing the short summary', async () => {
    const neighborhoods = { include: ['Highlands', 'Belvidere'], exclude: ['Downtown'], strict: true };
    const requirements = `${'Keep this exact requirement. '.repeat(25)}Final stored detail.`;
    const api = fakeApi();
    vi.mocked(api.internalWorkspace).mockResolvedValue({
      ...internalWorkspace,
      saved_searches: [{
        id: 131, name: 'Lowell neighborhoods',
        criteria: JSON.stringify({ neighborhoods, custom_requirements: requirements }),
        criteria_summary: ['Additional stored criteria are not summarized'],
      }],
    });
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Saved Searches' }));
    const card = await screen.findByRole('article', { name: 'SWS internal saved search 131' });
    const disclosure = within(card).getByText('All stored search criteria');
    expect(disclosure.closest('details')).not.toHaveAttribute('open');
    expect(within(card).getByText('Additional stored criteria are not summarized')).toBeVisible();
    expect(within(card).queryByText('neighborhoods')).not.toBeInTheDocument();

    await userEvent.click(disclosure);
    expect(await within(card).findByText('neighborhoods')).toBeVisible();
    const nestedValue = within(card).getByText((_text, node) =>
      node?.tagName === 'P' && node.textContent === JSON.stringify(neighborhoods, null, 2));
    expect(nestedValue).toBeVisible();
    expect(within(card).queryByText(requirements)).not.toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: 'Show full custom requirements criterion' }));
    expect(within(card).getByText(requirements)).toBeVisible();
    expect(within(card).getByText('Additional stored criteria are not summarized')).toBeVisible();
  });

  it('progressively reveals every stored search field in a bounded list', async () => {
    const api = fakeApi();
    const criteria = Object.fromEntries(Array.from({ length: 13 }, (_, index) => [`field_${index + 1}`, `value ${index + 1}`]));
    vi.mocked(api.internalWorkspace).mockResolvedValue({
      ...internalWorkspace,
      saved_searches: [{ id: 132, name: 'Detailed search', criteria: JSON.stringify(criteria) }],
    });
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Saved Searches' }));
    const card = await screen.findByRole('article', { name: 'SWS internal saved search 132' });
    await userEvent.click(within(card).getByText('All stored search criteria'));
    expect(await within(card).findByText('field 12')).toBeVisible();
    expect(within(card).queryByText('field 13')).not.toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: 'Show more stored criteria' }));
    expect(within(card).getByText('field 13')).toBeVisible();
    expect(within(card).getByText('value 13')).toBeVisible();
  });

  it('preserves the original criteria when JavaScript cannot safely represent a stored number', async () => {
    const criteria = '{"neighborhoods":{"reference":9007199254740993}}';
    const api = fakeApi();
    vi.mocked(api.internalWorkspace).mockResolvedValue({
      ...internalWorkspace,
      saved_searches: [{ id: 133, name: 'Exact stored criteria', criteria }],
    });
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Saved Searches' }));
    const card = await screen.findByRole('article', { name: 'SWS internal saved search 133' });
    await userEvent.click(within(card).getByText('All stored search criteria'));
    expect(await within(card).findByText(criteria)).toBeVisible();
    expect(within(card).queryByText(/9007199254740992/)).not.toBeInTheDocument();
  });

  it('renders one visible archived total with accessible mutable and recovered subtotals', async () => {
    const api = fakeApi();
    vi.mocked(api.workspace).mockResolvedValue(expandedSummary);

    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });

    const countStrip = screen.getByRole('complementary', { name: 'Contact workspace counts' });
    expect(within(countStrip).getByText('active tasks')).toBeVisible();
    expect(within(countStrip).getByText('cancelled tasks')).toBeVisible();
    expect(within(countStrip).queryByText('open tasks')).not.toBeInTheDocument();
    const archived = within(countStrip).getByText('archived tasks').closest('span');
    expect(archived).not.toBeNull();
    expect(within(archived as HTMLElement).getByText('1 restorable SWS task')).toHaveClass(
      'command-visually-hidden',
    );
    expect(within(archived as HTMLElement).getByText('1 recovered evidence task')).toHaveClass(
      'command-visually-hidden',
    );
    expect(Array.from(countStrip.querySelectorAll(':scope > span')).filter((row) => (
      row.textContent?.includes('archived tasks')
    ))).toHaveLength(1);
  });

  it('does not fabricate archived subtotals for the rolling legacy summary', async () => {
    renderWorkspace(fakeApi());
    await screen.findByRole('heading', { name: 'Ada Lovelace' });

    const archived = within(screen.getByRole('complementary', {
      name: 'Contact workspace counts',
    })).getByText('archived tasks').closest('span');
    expect(within(archived as HTMLElement).getByText(
      'Archived task breakdown unavailable during update',
    )).toHaveClass('command-visually-hidden');
    expect(within(archived as HTMLElement).queryByText(/restorable SWS task/)).not.toBeInTheDocument();
  });

  it('exposes seven source views, nested task states, and an auxiliary SWS booking view as ARIA tabs', async () => {
    renderWorkspace(fakeApi());
    await screen.findByRole('heading', { name: 'Ada Lovelace' });

    const topTabs = screen.getByRole('tablist', { name: 'Contact detail views' });
    for (const name of [
      'Timeline', 'Opportunities', 'SmartPlans', 'Tasks', 'Notes', 'Saved Searches',
      'Source Evidence', 'Bookings · SWS internal',
    ]) {
      expect(within(topTabs).getByRole('tab', { name })).toBeInTheDocument();
    }
    expect(within(topTabs).getAllByRole('tab')).toHaveLength(8);
    expect(within(within(topTabs).getByRole('tab', { name: 'Timeline' })).getByText('2 events')).toBeInTheDocument();
    expect(within(within(topTabs).getByRole('tab', { name: 'Opportunities' })).getByText('2 captured · 1 SWS')).toBeInTheDocument();
    expect(within(within(topTabs).getByRole('tab', { name: 'SmartPlans' })).getByText('2 captured · 1 SWS')).toBeInTheDocument();
    expect(within(within(topTabs).getByRole('tab', { name: 'Tasks' })).getByText('3 captured · 4 SWS')).toBeInTheDocument();
    expect(within(within(topTabs).getByRole('tab', { name: 'Notes' })).getByText('0 verified · 1 SWS')).toBeInTheDocument();
    expect(within(within(topTabs).getByRole('tab', { name: 'Saved Searches' })).getByText('Source partial · 1 SWS')).toBeInTheDocument();
    expect(within(within(topTabs).getByRole('tab', { name: 'Source Evidence' })).getByText('1 capture')).toBeInTheDocument();
    expect(within(within(topTabs).getByRole('tab', { name: 'Bookings · SWS internal' })).getByText('2 SWS')).toBeInTheDocument();
    const topValues = ['timeline', 'opportunities', 'smart_plans', 'tasks', 'notes', 'saved_searches', 'evidence', 'bookings'];
    for (const value of topValues) {
      const tab = document.getElementById(`contact-detail-view-tab-${value}`);
      const panel = document.getElementById(`contact-detail-view-panel-${value}`);
      expect(tab).not.toBeNull();
      expect(panel).not.toBeNull();
      expect(tab).toHaveAttribute('aria-controls', panel?.id);
      expect(panel).toHaveAttribute('aria-labelledby', tab?.id);
      expect(panel).toHaveAttribute('role', 'tabpanel');
      expect(panel?.hidden).toBe(value !== 'timeline');
    }
    const timelineTab = within(topTabs).getByRole('tab', { name: 'Timeline' });
    timelineTab.focus();
    fireEvent.keyDown(timelineTab, { key: 'ArrowRight' });
    expect(within(topTabs).getByRole('tab', { name: 'Opportunities' })).toHaveFocus();
    expect(timelineTab).toHaveAttribute('aria-selected', 'true');

    await userEvent.click(within(topTabs).getByRole('tab', { name: 'Tasks' }));
    const taskTabs = screen.getByRole('tablist', { name: 'Task states' });
    for (const name of ['To Do', 'Completed', 'Archived']) {
      expect(within(taskTabs).getByRole('tab', { name })).toBeInTheDocument();
    }
    for (const value of ['to_do', 'completed', 'archived']) {
      const tab = document.getElementById(`contact-task-state-tab-${value}`);
      const panel = document.getElementById(`contact-task-state-panel-${value}`);
      expect(tab).toHaveAttribute('aria-controls', panel?.id);
      expect(panel).toHaveAttribute('aria-labelledby', tab?.id);
      expect(panel?.hidden).toBe(value !== 'to_do');
    }
    await userEvent.click(within(taskTabs).getByRole('tab', { name: 'Completed' }));
    expect(await screen.findByText('Send market report')).toBeInTheDocument();
  });

  it('renders the merged timeline and the complete decoded SWS internal bookings separately', async () => {
    const api = fakeApi();
    renderWorkspace(api);

    expect(await screen.findByText('Discovery call completed')).toBeInTheDocument();
    expect(screen.getByText('Discussed a possible September listing.')).toBeInTheDocument();
    expect(screen.getByText('Follow up next Tuesday')).toBeInTheDocument();
    expect(screen.getByText('Follow up next Tuesday').closest('article')?.querySelector('time')).toHaveAttribute('datetime');
    expect(screen.getByText('Consultation booked')).toBeInTheDocument();
    expect(screen.getByText('SWS consultation at the office.')).toBeInTheDocument();
    const timelineRegion = screen.getByRole('region', { name: 'Contact timeline' });
    const timelineEvidence = within(timelineRegion).getByRole('region', {
      name: 'Capture position 1 · timeline evidence',
    });
    expect(within(timelineEvidence).getByText('Complete capture')).toBeInTheDocument();
    expect(within(timelineEvidence).getByText('2')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Bookings · SWS internal' }));
    expect(screen.getByText('2 SWS internal bookings')).toBeInTheDocument();
    expect(screen.getByText('valuation')).toBeInTheDocument();
    expect(screen.getByText('consultation')).toBeInTheDocument();
    expect(screen.getByText('Walkthrough')).toBeInTheDocument();
    expect(screen.getByText('Listing strategy')).toBeInTheDocument();
    expect(screen.getAllByRole('article', { name: /SWS internal booking/i }).map((row) => row.textContent)).toEqual([
      expect.stringContaining('consultation'),
      expect.stringContaining('valuation'),
    ]);
    expect(api.timeline).toHaveBeenCalledTimes(1);
    expect(document.body).not.toHaveTextContent('/workspace');
  });

  it('explains a capture containing only profile and page controls without claiming missing events', async () => {
    const api = fakeApi();
    vi.mocked(api.timeline).mockResolvedValue({ rows: [], next_cursor: null, has_more: false, filtered_capture_count: 2 });
    renderWorkspace(api);
    expect(await screen.findByText('No activity entries in this capture')).toBeVisible();
    expect(screen.queryByText('Recovered timeline events are not available')).not.toBeInTheDocument();
  });

  it('defensively hides technical archive activities and bounds malformed long timeline values', async () => {
    const api = fakeApi();
    const rawArchiveValue = `- button command at header ${'raw accessibility node '.repeat(80)}`;
    vi.mocked(api.timeline).mockResolvedValue({
      rows: [
        {
          ...timeline.rows[0]!,
          key: 'activity:801',
          entity_id: 801,
          kind: 'archive_timeline_capture',
          title: 'INTERNAL_CRM · ARCHIVE_TIMELINE_CAPTURE',
          body: rawArchiveValue,
        },
        {
          ...timeline.rows[0]!,
          key: 'activity:802',
          entity_id: 802,
          kind: 'archive_contact_imported',
          title: 'INTERNAL_CRM · ARCHIVE_CONTACT_IMPORTED',
        },
        {
          ...timeline.rows[0]!,
          key: 'activity:803',
          entity_id: 803,
          kind: 'note_created',
          title: rawArchiveValue,
          body: 'A real event with a defensively bounded malformed title.',
        },
      ],
      next_cursor: null,
      has_more: false,
    });

    renderWorkspace(api);

    expect(await screen.findByText('A real event with a defensively bounded malformed title.')).toBeInTheDocument();
    expect(screen.queryByText('INTERNAL_CRM · ARCHIVE_TIMELINE_CAPTURE')).not.toBeInTheDocument();
    expect(screen.queryByText('INTERNAL_CRM · ARCHIVE_CONTACT_IMPORTED')).not.toBeInTheDocument();
    expect(screen.queryByText(rawArchiveValue)).not.toBeInTheDocument();
    const expand = screen.getByRole('button', { name: 'Show full activity' });
    expect(expand).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(expand);
    expect(screen.getByRole('heading', { name: rawArchiveValue.trim() })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Collapse activity' })).toHaveAttribute('aria-expanded', 'true');
  });

  it('shows yearless, sentinel, and verified celebrations without presenting 1900 as verified', async () => {
    const sentinelApi = fakeApi();
    vi.mocked(sentinelApi.detail).mockResolvedValue({
      ...detail,
      contact: {
        ...contact,
        birthday: {
          month: 8,
          day: 30,
          year: 1900,
          year_quality: 'sentinel',
          origin: 'recovered',
        },
      },
      recovered_profile: {
        ...detail.recovered_profile!,
        birthday: {
          month: 8,
          day: 30,
          year: null,
          year_quality: 'yearless',
          origin: 'recovered',
        },
      },
    });
    renderWorkspace(sentinelApi);

    expect(await screen.findByText('Birthday: August 30 — source year treated as sentinel')).toBeInTheDocument();
    expect(screen.getByText('Recovered birthday: August 30 — year not captured')).toBeInTheDocument();
    expect(screen.getByText('Home anniversary: September 23, 2022')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('August 30, 1900');
  });

  it('renders only observed address/coordinates and never fabricates a client-side map', async () => {
    const missingCoordinates = renderWorkspace(fakeApi());
    expect(await screen.findByText('12 St. James Square, London')).toBeInTheDocument();
    expect(screen.getByText('Map location was not captured')).toBeInTheDocument();
    expect(document.querySelector('iframe')).toBeNull();
    expect(document.querySelector('img[src*="maps"]')).toBeNull();
    missingCoordinates.unmount();

    const coordinatesApi = fakeApi();
    vi.mocked(coordinatesApi.detail).mockResolvedValue({
      ...detail,
      addresses: [{
        ...detail.addresses[0]!,
        latitude: '51.5074000',
        longitude: '-0.1278000',
      }],
    });
    renderWorkspace(coordinatesApi);
    expect(await screen.findByText('51.5074000, -0.1278000')).toBeInTheDocument();
    expect(screen.getByText('Static map preview is unavailable')).toBeInTheDocument();
    expect(document.querySelector('iframe')).toBeNull();
  });

  it('renders source-only and materialized occurrences distinctly and restricts source-only mutations', async () => {
    renderWorkspace(fakeApi());
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Opportunities' }));

    const sourceOnly = (await screen.findByText('Archive seller opportunity')).closest('article');
    const capturedRegion = screen.getByRole('region', { name: 'Captured source opportunities' });
    const materialized = within(capturedRegion).getByText('Internal listing opportunity').closest('article');
    expect(sourceOnly).not.toBeNull();
    expect(materialized).not.toBeNull();
    expect(within(sourceOnly as HTMLElement).getByText('Source evidence only')).toBeInTheDocument();
    expect(within(sourceOnly as HTMLElement).getByRole('button', { name: 'View source evidence' })).toBeInTheDocument();
    expect(within(sourceOnly as HTMLElement).queryByRole('button', { name: /complete|delete|edit/i })).not.toBeInTheDocument();
    expect(within(materialized as HTMLElement).queryByRole('link')).not.toBeInTheDocument();
    expect(within(materialized as HTMLElement).getByText('Linked opportunity #73')).toBeInTheDocument();
    expect(within(materialized as HTMLElement).getByText('Materialized in SWS')).toBeInTheDocument();
    expect(within(capturedRegion).getByText('Partial capture')).toBeInTheDocument();
  });

  it('keeps captured source and SWS internal rows in visibly separate regions without merging counts', async () => {
    renderWorkspace(fakeApi());
    await screen.findByRole('heading', { name: 'Ada Lovelace' });

    await userEvent.click(screen.getByRole('tab', { name: 'Opportunities' }));
    const captured = await screen.findByRole('region', { name: 'Captured source opportunities' });
    const internal = screen.getByRole('region', { name: 'SWS internal opportunities' });
    expect(within(captured).getByRole('heading', { name: 'Recovered source opportunities' })).toBeInTheDocument();
    expect(within(internal).getByRole('heading', { name: 'SWS internal opportunities' })).toBeInTheDocument();
    expect(within(captured).getAllByRole('article')).toHaveLength(2);
    expect(within(internal).getAllByRole('article')).toHaveLength(1);
    expect(within(captured).getByText('Internal listing opportunity')).toBeInTheDocument();
    expect(within(internal).getByText('Internal listing opportunity')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));
    expect(await within(screen.getByRole('region', { name: 'Captured source notes' })).findByText('No notes were captured')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'SWS internal notes' })).getByText(
      'Internal follow-up note that has no capture occurrence.',
    )).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Saved Searches' }));
    expect(await within(screen.getByRole('region', { name: 'Captured source saved searches' })).findByText(
      'Saved searches were not fully captured',
    )).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'SWS internal saved searches' })).getByText(
      'Internal downsizer search',
    )).toBeInTheDocument();
  });

  it('uses exact materialization identity and reports a missing target as unavailable', async () => {
    renderWorkspace(fakeApi());
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'SmartPlans' }));

    const missing = (await screen.findByText('Missing materialized plan')).closest('article');
    expect(missing).not.toBeNull();
    expect(within(missing as HTMLElement).getByText('Internal target unavailable')).toBeInTheDocument();
    expect(within(missing as HTMLElement).queryByRole('link')).not.toBeInTheDocument();
    expect(within(missing as HTMLElement).queryByText('Source evidence only')).not.toBeInTheDocument();
  });

  it('sorts complete internal collections deterministically with an ID tie-break', async () => {
    renderWorkspace(fakeApi());
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));

    expect(screen.getAllByRole('article', { name: /SWS internal task/i }).map((row) => row.textContent)).toEqual([
      expect.stringContaining('Second tied task'),
      expect.stringContaining('Internal valuation follow-up'),
    ]);
  });

  it('labels unavailable internal data distinctly from a truthful empty collection', async () => {
    const api = fakeApi();
    vi.mocked(api.internalWorkspace).mockRejectedValue(new Error('PLANTED_PRIVATE_INTERNAL_ERROR'));
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));

    const internal = screen.getByRole('region', { name: 'SWS internal notes' });
    expect(within(internal).getByText('SWS internal notes are unavailable')).toBeInTheDocument();
    expect(within(internal).queryByText('No SWS internal notes')).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('PLANTED_PRIVATE_INTERNAL_ERROR');
    expect(within(screen.getByRole('region', { name: 'Captured source notes' })).getByText(
      'No notes were captured',
    )).toBeInTheDocument();
  });

  it('renders truthful complete-empty and limited-empty states for notes and saved searches', async () => {
    renderWorkspace(fakeApi());
    await screen.findByRole('heading', { name: 'Ada Lovelace' });

    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));
    expect(await screen.findByText('No notes were captured')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Captured source notes' })).getByText('Complete capture')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Saved Searches' }));
    expect(await screen.findByText('Saved searches were not fully captured')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Captured source saved searches' })).getByText('Shell capture')).toBeInTheDocument();
  });

  it('renders 317/317/zero-alias evidence, overlap partition, positions, limitations, and authenticated artifacts', async () => {
    const api = fakeApi();
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Source Evidence' }));

    const evidencePanel = await screen.findByRole('region', { name: 'Contact capture evidence' });
    const recoverySummary = within(evidencePanel).getByRole('region', { name: 'Current contact recovery summary' });
    expect(within(recoverySummary).getByRole('heading', { name: '1 recovered Command capture linked' })).toBeInTheDocument();
    expect(within(recoverySummary).getByText('2 of 8 section checks are complete, with 9 captured records.')).toBeInTheDocument();
    expect(within(evidencePanel).getByText('317 provider contact rows')).toBeInTheDocument();
    expect(within(evidencePanel).getByText('317 resolved provider identities')).toBeInTheDocument();
    expect(within(evidencePanel).getByText('0 coalesced aliases')).toBeInTheDocument();
    expect(within(evidencePanel).getByText('51 lead-backed contacts')).toBeInTheDocument();
    expect(within(evidencePanel).getByText('2 reviewed overlaps')).toBeInTheDocument();
    expect(within(evidencePanel).getByText('49 legacy-only contacts')).toBeInTheDocument();
    expect(within(evidencePanel).getByText('Capture position 1')).toBeInTheDocument();
    expect(within(evidencePanel).getByText('redacted_placeholder_evidence')).toBeInTheDocument();
    expect(within(evidencePanel).getByText('shell_only')).toBeInTheDocument();

    const download = within(evidencePanel).getByRole('button', { name: 'Download html source artifact 55' });
    expect(within(evidencePanel).queryByRole('link', { name: /artifact 55/i })).not.toBeInTheDocument();
    await userEvent.click(download);

    expect(api.artifactBlob).toHaveBeenCalledWith(55, { signal: expect.any(AbortSignal) });
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:command-evidence');
  });

  it('preserves the sanitized directory universe through previous, next, back, and jump navigation', async () => {
    navigation.search = new URLSearchParams(
      'stage=past+client&source=kw_command&sort=health_score&direction=desc&page=3&page_size=25&campaign=sws-fall&health_min=bad',
    );
    const api = fakeApi();
    vi.mocked(api.directory).mockResolvedValue(directoryPage([{ ...contact, id: 21, display_name: 'Grace Hopper' }]));
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });

    const expectedRequest: ContactDirectoryRequest = {
      stage: 'past client',
      source: ['kw_command'],
      sort: 'health_score',
      direction: 'desc',
      page: 3,
      page_size: 25,
      smart_view: 'all',
    };
    expect(api.neighbors).toHaveBeenCalledWith(7, expectedRequest, { signal: expect.any(AbortSignal) });

    await userEvent.click(screen.getByRole('button', { name: 'Previous contact' }));
    expect(navigation.push).toHaveBeenLastCalledWith(
      '/admin/command/contacts/5?stage=past+client&source=kw_command&sort=health_score&direction=desc&page=3&page_size=25&campaign=sws-fall',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Next contact' }));
    expect(navigation.push).toHaveBeenLastCalledWith(
      '/admin/command/contacts/9?stage=past+client&source=kw_command&sort=health_score&direction=desc&page=3&page_size=25&campaign=sws-fall',
    );
    expect(screen.getByRole('link', { name: 'Back to contacts' })).toHaveAttribute(
      'href',
      '/admin/command/contacts?stage=past+client&source=kw_command&sort=health_score&direction=desc&page=3&page_size=25&campaign=sws-fall',
    );

    await userEvent.type(screen.getByRole('searchbox', { name: 'Jump to contact' }), 'Grace');
    await waitFor(() => expect(api.directory).toHaveBeenCalledWith(
      { ...expectedRequest, query: 'Grace', page: 1, page_size: 10 },
      { signal: expect.any(AbortSignal) },
    ));
    await userEvent.click(await screen.findByRole('button', { name: 'Open Grace Hopper' }));
    expect(navigation.push).toHaveBeenLastCalledWith(
      '/admin/command/contacts/21?query=Grace&stage=past+client&source=kw_command&sort=health_score&direction=desc&page=1&page_size=25&campaign=sws-fall',
    );
  });

  it('loads each section on demand, supports all task states, and refreshes only the active section', async () => {
    const api = fakeApi();
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    expect(api.section).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('tab', { name: 'SmartPlans' }));
    expect(await screen.findByText('Recovered quarterly touch')).toBeInTheDocument();
    expect(api.section).toHaveBeenCalledWith(7, 'smart_plans', 1, 50, { signal: expect.any(AbortSignal) });

    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));
    expect(await screen.findByText('Call about valuation')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Completed' }));
    expect(await screen.findByText('Send market report')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Archived' }));
    expect(await screen.findByText('Old reminder')).toBeInTheDocument();
    const recovered = screen.getByText('Old reminder').closest('article');
    expect(within(recovered as HTMLElement).getByText('Recovered evidence')).toBeInTheDocument();
    expect(within(recovered as HTMLElement).queryByRole('button')).not.toBeInTheDocument();
    const mutable = screen.getByText('Internal archived task').closest('article');
    expect(within(mutable as HTMLElement).getByText('Superseded reminder')).toBeInTheDocument();
    expect(within(mutable as HTMLElement).getByText('completed')).toBeInTheDocument();
    expect(within(mutable as HTMLElement).getByRole('button', {
      name: 'Restore Internal archived task',
    })).toBeInTheDocument();
    expect(within(mutable as HTMLElement).getAllByRole('button')).toHaveLength(1);

    expect(vi.mocked(api.section).mock.calls.map((call) => call[1])).toEqual([
      'smart_plans', 'tasks_to_do', 'tasks_completed', 'tasks_archived',
    ]);
  });

  it('keeps a rolling legacy archived row visible but read-only without inventing a version', async () => {
    const api = fakeApi();
    vi.mocked(api.internalWorkspace).mockResolvedValue({
      ...internalWorkspace,
      tasks: [{
        id: 901,
        title: 'Legacy archived row',
        contact_id: 7,
        description: '',
        priority: 'normal',
        due_at: null,
        status: 'archived',
      }],
    });
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));
    await userEvent.click(screen.getByRole('tab', { name: 'Archived' }));

    const row = (await screen.findByText('Legacy archived row')).closest('article');
    expect(within(row as HTMLElement).getByText(
      'Restore is unavailable until task lifecycle data is refreshed.',
    )).toBeInTheDocument();
    expect(within(row as HTMLElement).queryByRole('button', { name: /restore/i })).not.toBeInTheDocument();
    expect(api.restoreTask).not.toHaveBeenCalled();
  });

  it('restores a mutable archived task with one protected UUID and verifies internal plus summary state', async () => {
    const api = fakeApi();
    vi.mocked(api.workspace).mockResolvedValue(expandedSummary);
    const restore = await openArchivedInternalTask(api);
    vi.mocked(api.internalWorkspace).mockResolvedValueOnce(restoredInternalWorkspace);
    vi.mocked(api.workspace).mockResolvedValueOnce(restoredSummary);

    await userEvent.click(restore);

    await waitFor(() => expect(api.restoreTask).toHaveBeenCalledTimes(1));
    expect(api.restoreTask).toHaveBeenCalledWith(104, {
      request_id: expect.stringMatching(UUID_PATTERN),
      expected_version: 4,
    }, { signal: expect.any(AbortSignal) });
    expect(await screen.findByRole('status')).toHaveTextContent('Restore confirmed after refreshing.');
    expect(screen.queryByRole('button', { name: 'Restore Internal archived task' })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Archived' })).toHaveFocus();
    expect(api.internalWorkspace).toHaveBeenCalledTimes(2);
    expect(api.workspace).toHaveBeenCalledTimes(2);
  });

  it('does not reconcile a definite Restore rejection and returns focus to the surviving control', async () => {
    const api = fakeApi();
    const restore = await openArchivedInternalTask(api);
    vi.mocked(api.restoreTask).mockRejectedValueOnce(
      new CommandHttpError(422, 'Restore request was rejected'),
    );
    const internalReads = vi.mocked(api.internalWorkspace).mock.calls.length;
    const summaryReads = vi.mocked(api.workspace).mock.calls.length;

    await userEvent.click(restore);

    expect(await screen.findByRole('alert')).toHaveTextContent('Restore request was rejected');
    expect(api.internalWorkspace).toHaveBeenCalledTimes(internalReads);
    expect(api.workspace).toHaveBeenCalledTimes(summaryReads);
    expect(restore).toBeEnabled();
    expect(restore).toHaveFocus();
  });

  it('offers an exact same-request Restore retry only when uncertainty finds the original task unchanged', async () => {
    const api = fakeApi();
    vi.mocked(api.workspace).mockResolvedValue(expandedSummary);
    const retryAck = deferred<Task>();
    vi.mocked(api.restoreTask)
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockReturnValueOnce(retryAck.promise);
    const restore = await openArchivedInternalTask(api);
    vi.mocked(api.internalWorkspace).mockResolvedValueOnce(internalWorkspace);
    vi.mocked(api.workspace).mockResolvedValueOnce(expandedSummary);

    await userEvent.click(restore);

    const retry = await screen.findByRole('button', { name: 'Retry Restore' });
    expect(retry).toHaveFocus();
    expect(api.restoreTask).toHaveBeenCalledTimes(1);
    const originalRequest = { ...vi.mocked(api.restoreTask).mock.calls[0]?.[1] };
    vi.mocked(api.internalWorkspace).mockResolvedValueOnce(restoredInternalWorkspace);
    vi.mocked(api.workspace).mockResolvedValueOnce(restoredSummary);
    await userEvent.click(retry);

    const progress = screen.getByRole('status');
    expect(progress).toHaveTextContent('Retrying Restore for Internal archived task…');
    expect(progress).toHaveAttribute('aria-live', 'polite');
    expect(progress).toHaveAttribute('aria-atomic', 'true');
    expect(progress).toHaveAttribute('tabindex', '-1');
    expect(progress).toHaveFocus();
    await act(async () => retryAck.resolve(restoredInternalTask as Task));
    await waitFor(() => expect(api.restoreTask).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.restoreTask).mock.calls[1]?.[1]).toStrictEqual(originalRequest);
    expect(await screen.findByText('Restore confirmed after refreshing.')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Archived' })).toHaveFocus();
  });

  it('adopts a Restore conflict and requires a fresh UUID with the authoritative version', async () => {
    const api = fakeApi();
    vi.mocked(api.workspace).mockResolvedValue(expandedSummary);
    const changed = {
      ...archivedInternalTask,
      archive_reason: 'Reviewed by another administrator',
      version: 6,
    };
    const changedWorkspace = {
      ...internalWorkspace,
      tasks: internalWorkspace.tasks.map((task) => task.id === 104 ? changed : task),
    };
    vi.mocked(api.restoreTask)
      .mockRejectedValueOnce(new CommandConflictError({
        code: 'task_version_conflict',
        current_version: 6,
        current_task: changed as Task,
      }))
      .mockResolvedValueOnce({ ...restoredInternalTask, version: 7 } as Task);
    const restore = await openArchivedInternalTask(api);
    vi.mocked(api.internalWorkspace).mockResolvedValueOnce(changedWorkspace);
    vi.mocked(api.workspace).mockResolvedValueOnce(expandedSummary);

    await userEvent.click(restore);

    expect(await screen.findByRole('alert')).toHaveTextContent(/changed elsewhere.*fresh action/i);
    expect(screen.queryByRole('button', { name: 'Retry Restore' })).not.toBeInTheDocument();
    expect(screen.getByText('Reviewed by another administrator')).toBeInTheDocument();
    const firstRequest = vi.mocked(api.restoreTask).mock.calls[0]?.[1];
    vi.mocked(api.internalWorkspace).mockResolvedValueOnce({
      ...restoredInternalWorkspace,
      tasks: restoredInternalWorkspace.tasks.map((task) => task.id === 104
        ? { ...restoredInternalTask, version: 7 }
        : task),
    });
    vi.mocked(api.workspace).mockResolvedValueOnce(restoredSummary);
    await userEvent.click(screen.getByRole('button', { name: 'Restore Internal archived task' }));

    await waitFor(() => expect(api.restoreTask).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.restoreTask).mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      expected_version: 6,
      request_id: expect.stringMatching(UUID_PATTERN),
    }));
    expect(vi.mocked(api.restoreTask).mock.calls[1]?.[1].request_id).not.toBe(firstRequest?.request_id);
  });

  it('keeps every contact mutation locked when Restore uncertainty cannot be authoritatively refreshed', async () => {
    const api = fakeApi();
    vi.mocked(api.workspace).mockResolvedValue(expandedSummary);
    vi.mocked(api.restoreTask).mockRejectedValueOnce(
      new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')),
    );
    const restore = await openArchivedInternalTask(api);
    vi.mocked(api.internalWorkspace).mockRejectedValueOnce(new Error('Synthetic internal refresh failure'));
    vi.mocked(api.workspace).mockRejectedValueOnce(new Error('Synthetic summary refresh failure'));

    await userEvent.click(restore);

    const refresh = await screen.findByRole('button', { name: 'Retry contact refresh' });
    expect(refresh).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Edit profile' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Restore Internal archived task' })).toBeDisabled();
    const internalReadCount = vi.mocked(api.internalWorkspace).mock.calls.length;
    const pendingInternal = deferred<ContactInternalWorkspace>();
    const pendingSummary = deferred<ContactWorkspaceSummary>();
    vi.mocked(api.internalWorkspace).mockReturnValueOnce(pendingInternal.promise);
    vi.mocked(api.workspace).mockReturnValueOnce(pendingSummary.promise);
    fireEvent.click(refresh);
    fireEvent.click(refresh);

    await waitFor(() => expect(api.internalWorkspace).toHaveBeenCalledTimes(internalReadCount + 1));
    expect(refresh).toBeInTheDocument();
    expect(refresh).toHaveFocus();
    expect(refresh).toBeDisabled();
    expect(refresh).toHaveTextContent('Refreshing…');
    await act(async () => {
      pendingInternal.resolve(internalWorkspace);
      pendingSummary.resolve(expandedSummary);
      await Promise.all([pendingInternal.promise, pendingSummary.promise]);
    });
    expect(await screen.findByRole('button', { name: 'Retry Restore' })).toHaveFocus();
    expect(api.restoreTask).toHaveBeenCalledTimes(1);
  });

  it('rejects a historical Restore retry ACK when the authoritative task changed again', async () => {
    const api = fakeApi();
    vi.mocked(api.workspace).mockResolvedValue(expandedSummary);
    vi.mocked(api.restoreTask)
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockResolvedValueOnce(restoredInternalTask as Task);
    const restore = await openArchivedInternalTask(api);
    vi.mocked(api.internalWorkspace).mockResolvedValueOnce(internalWorkspace);
    vi.mocked(api.workspace).mockResolvedValueOnce(expandedSummary);
    await userEvent.click(restore);
    const retry = await screen.findByRole('button', { name: 'Retry Restore' });
    const newerArchive = {
      ...archivedInternalTask,
      description: 'Restored and then archived again',
      archive_reason: 'Newer archive decision',
      version: 6,
    };
    vi.mocked(api.internalWorkspace).mockResolvedValueOnce({
      ...internalWorkspace,
      tasks: internalWorkspace.tasks.map((task) => task.id === 104 ? newerArchive : task),
    });
    vi.mocked(api.workspace).mockResolvedValueOnce(expandedSummary);

    await userEvent.click(retry);

    expect(await screen.findByRole('alert')).toHaveTextContent(/changed again.*fresh action/i);
    expect(screen.queryByText('Restore confirmed after refreshing.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry Restore' })).not.toBeInTheDocument();
    expect(screen.getByText('Newer archive decision')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Archived' })).toHaveFocus();
  });

  it('persists SWS-only note mutations by refetching internal workspace, summary, and timeline', async () => {
    const api = fakeApi();
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));

    await userEvent.click(screen.getByRole('button', { name: 'Add note' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Note body' }), 'A new private SWS note');
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }));

    expect(api.createNote).toHaveBeenCalledWith(7, { body: 'A new private SWS note' }, { signal: expect.any(AbortSignal) });
    await waitFor(() => expect(api.internalWorkspace).toHaveBeenCalledTimes(2));
    expect(api.workspace).toHaveBeenCalledTimes(2);
    expect(api.timeline).toHaveBeenCalledTimes(2);
    expect(api.section).toHaveBeenCalledTimes(1);
  });

  it('exposes no globally addressed task mutation and allows contact-bound task creation only', async () => {
    const api = fakeApi();
    vi.mocked(api.createTask).mockResolvedValueOnce({
      id: 204,
      title: 'New task',
      contact_id: null,
      description: '',
      priority: 'normal',
      due_at: null,
      status: 'completed',
      archived_at: null,
      archive_reason: null,
      version: 4,
    });
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));
    const internalTask = screen.getByText('Internal valuation follow-up').closest('article');

    expect(within(internalTask as HTMLElement).queryByRole('button', { name: /edit|complete|reopen|delete|archive/i })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Add task' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Task title' }), 'New task');
    await userEvent.click(screen.getByRole('button', { name: 'Save task' }));
    expect(api.createTask).toHaveBeenCalledWith({
      title: 'New task',
      contact_id: 7,
      description: '',
      priority: 'normal',
      due_at: null,
    }, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i), {
      signal: expect.any(AbortSignal),
      clientTimezone: expect.any(String),
    });
    await waitFor(() => expect(api.internalWorkspace).toHaveBeenCalledTimes(2));
    expect(api.workspace).toHaveBeenCalledTimes(2);
    expect(api.timeline).toHaveBeenCalledTimes(2);
  });

  it('reuses one UUID and canonical payload for an unchanged contact-task retry after uncertainty', async () => {
    const api = fakeApi();
    vi.mocked(api.createTask)
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockResolvedValueOnce({
        id: 204, title: 'Uncertain contact task', contact_id: 7, description: '', priority: 'normal',
        due_at: null, status: 'open', archived_at: null, archive_reason: null, version: 1,
      });
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Add task' }));
    await userEvent.type(screen.getByLabelText('Task title'), 'Uncertain contact task');
    const save = screen.getByRole('button', { name: 'Save task' });

    await userEvent.click(save);
    await waitFor(() => expect(save).toBeEnabled());
    expect(api.createTask).toHaveBeenCalledTimes(1);
    const firstCall = vi.mocked(api.createTask).mock.calls[0];
    await userEvent.type(screen.getByLabelText('Task title'), ' ');
    await userEvent.click(save);

    await waitFor(() => expect(api.createTask).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.createTask).mock.calls[1]?.slice(0, 2)).toEqual(firstCall?.slice(0, 2));
    expect(vi.mocked(api.createTask).mock.calls[1]?.[2]).toEqual({
      signal: expect.any(AbortSignal),
      clientTimezone: vi.mocked(api.createTask).mock.calls[0]?.[2]?.clientTimezone,
    });
  });

  it('uses a new UUID when a contact-task draft changes after uncertainty', async () => {
    const api = fakeApi();
    vi.mocked(api.createTask)
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockResolvedValueOnce({
        id: 204, title: 'Changed contact task', contact_id: 7, description: '', priority: 'normal',
        due_at: null, status: 'open', archived_at: null, archive_reason: null, version: 1,
      });
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Add task' }));
    const title = screen.getByLabelText('Task title');
    await userEvent.type(title, 'Original contact task');
    await userEvent.click(screen.getByRole('button', { name: 'Save task' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save task' })).toBeEnabled());
    const firstKey = vi.mocked(api.createTask).mock.calls[0]?.[1];

    await userEvent.clear(title);
    await userEvent.type(title, 'Changed contact task');
    await userEvent.click(screen.getByRole('button', { name: 'Save task' }));
    await waitFor(() => expect(api.createTask).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.createTask).mock.calls[1]?.[1]).not.toBe(firstKey);
  });

  it.each([401, 404, 422])(
    'treats a definite task-create %i as direct, unlocks contact actions, and performs no reconciliation reads',
    async (status) => {
      const api = fakeApi();
      renderWorkspace(api);
      await screen.findByRole('heading', { name: 'Ada Lovelace' });
      await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));
      await userEvent.click(await screen.findByRole('button', { name: 'Add task' }));
      vi.mocked(api.createTask).mockRejectedValueOnce(new CommandHttpError(status, `Definite ${status} task failure`));

      await userEvent.type(screen.getByLabelText('Task title'), 'Rejected contact task');
      await userEvent.click(screen.getByRole('button', { name: 'Save task' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(`Definite ${status} task failure`);
      expect(api.internalWorkspace).toHaveBeenCalledTimes(1);
      expect(api.workspace).toHaveBeenCalledTimes(1);
      expect(api.timeline).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('button', { name: 'Save task' })).toBeEnabled();
      expect(screen.getByRole('button', { name: 'Edit profile' })).toBeEnabled();
    },
  );

  it('keeps a confirmed task create locked after its single authoritative refresh cycle fails', async () => {
    const api = fakeApi();
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Add task' }));
    vi.mocked(api.internalWorkspace)
      .mockRejectedValueOnce(new Error('Synthetic internal refresh failure'))
      .mockRejectedValueOnce(new Error('Synthetic internal retry failure'));
    vi.mocked(api.workspace)
      .mockRejectedValueOnce(new Error('Synthetic summary refresh failure'))
      .mockRejectedValueOnce(new Error('Synthetic summary retry failure'));
    vi.mocked(api.timeline)
      .mockRejectedValueOnce(new Error('Synthetic timeline refresh failure'))
      .mockRejectedValueOnce(new Error('Synthetic timeline retry failure'));

    await userEvent.type(screen.getByLabelText('Task title'), 'Confirmed but unverified task');
    await userEvent.click(screen.getByRole('button', { name: 'Save task' }));

    expect(await screen.findByRole('button', { name: 'Retry contact refresh' })).toBeInTheDocument();
    expect(api.createTask).toHaveBeenCalledTimes(1);
    expect(api.internalWorkspace).toHaveBeenCalledTimes(2);
    expect(api.workspace).toHaveBeenCalledTimes(2);
    expect(api.timeline).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Edit profile' })).toBeDisabled();

    await userEvent.click(screen.getByRole('button', { name: 'Retry contact refresh' }));
    await waitFor(() => expect(api.internalWorkspace).toHaveBeenCalledTimes(3));
    expect(screen.getByRole('button', { name: 'Retry contact refresh' })).toBeEnabled();
    expect(screen.getAllByText('Task was saved, but current contact data could not be verified.').length).toBeGreaterThan(0);
    expect(screen.queryByText('Task mutation status is unknown. Current contact data could not be verified.')).not.toBeInTheDocument();
    expect(api.createTask).toHaveBeenCalledTimes(1);
  });

  it('retains an uncertain contact-task attempt through failed verification and reuses it after explicit recovery', async () => {
    const api = fakeApi();
    vi.mocked(api.createTask)
      .mockRejectedValueOnce(new CommandOutcomeUncertainError(new TypeError('Synthetic disconnect')))
      .mockResolvedValueOnce({
        id: 204, title: 'Retry after verification', contact_id: 7, description: '', priority: 'normal',
        due_at: null, status: 'open', archived_at: null, archive_reason: null, version: 1,
      });
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Add task' }));
    vi.mocked(api.internalWorkspace).mockRejectedValueOnce(new Error('Synthetic internal refresh failure'));
    vi.mocked(api.workspace).mockRejectedValueOnce(new Error('Synthetic summary refresh failure'));
    vi.mocked(api.timeline).mockRejectedValueOnce(new Error('Synthetic timeline refresh failure'));
    await userEvent.type(screen.getByLabelText('Task title'), 'Retry after verification');
    await userEvent.click(screen.getByRole('button', { name: 'Save task' }));
    const firstCall = vi.mocked(api.createTask).mock.calls[0];

    await userEvent.click(await screen.findByRole('button', { name: 'Retry contact refresh' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save task' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Save task' }));

    await waitFor(() => expect(api.createTask).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.createTask).mock.calls[1]?.slice(0, 2)).toEqual(firstCall?.slice(0, 2));
    expect(vi.mocked(api.createTask).mock.calls[1]?.[2]).toEqual({
      signal: expect.any(AbortSignal),
      clientTimezone: vi.mocked(api.createTask).mock.calls[0]?.[2]?.clientTimezone,
    });
  });

  it('never prefills recovered-only dates into the SWS profile mutation', async () => {
    const api = fakeApi();
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('button', { name: 'Edit profile' }));

    expect(screen.getByLabelText('Birthday')).toHaveValue('');
    expect(screen.getByLabelText('Anniversary')).toHaveValue('');
    expect(screen.getByLabelText('Email')).toHaveValue('');
    expect(screen.getByLabelText('Phone')).toHaveValue('');
    await userEvent.clear(screen.getByLabelText('First name'));
    await userEvent.type(screen.getByLabelText('First name'), 'Augusta');
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }));

    expect(api.update).toHaveBeenCalledWith(
      7,
      { first_name: 'Augusta' },
      { signal: expect.any(AbortSignal) },
    );
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edit profile' })).toHaveFocus());
  });

  it('keeps a confirmed profile mutation authoritative when only neighbor navigation fails', async () => {
    const api = fakeApi();
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    vi.mocked(api.neighbors).mockRejectedValueOnce(new Error('PLANTED_PRIVATE_NEIGHBOR_REFRESH'));

    await userEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    await userEvent.clear(screen.getByLabelText('First name'));
    await userEvent.type(screen.getByLabelText('First name'), 'Augusta');
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }));

    expect(await screen.findByText(/Directory navigation is unavailable for the current view/)).toBeInTheDocument();
    expect(api.update).toHaveBeenCalledTimes(1);
    expect(api.neighbors).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/Mutation status is unknown/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edit profile' })).toHaveFocus());
    expect(document.body).not.toHaveTextContent('PLANTED_PRIVATE_NEIGHBOR_REFRESH');
  });

  it('renders distinct loading/error/retry states without leaking private errors', async () => {
    const pending = deferred<ContactDetail>();
    const api = fakeApi();
    vi.mocked(api.detail).mockReturnValueOnce(pending.promise);
    const view = renderWorkspace(api);
    expect(screen.getByRole('status', { name: 'Loading contact workspace' })).toBeInTheDocument();
    view.unmount();

    const failedApi = fakeApi();
    vi.mocked(failedApi.detail)
      .mockRejectedValueOnce(new Error('PLANTED_PRIVATE_DETAIL_ERROR'))
      .mockResolvedValueOnce(detail);
    renderWorkspace(failedApi);
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load contact workspace');
    expect(document.body).not.toHaveTextContent('PLANTED_PRIVATE_DETAIL_ERROR');
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('heading', { name: 'Ada Lovelace' })).toBeInTheDocument();
    expect(failedApi.detail).toHaveBeenCalledTimes(2);
  });

  it('renders a stable not-found state for a missing contact and does not offer retry', async () => {
    const api = fakeApi();
    const next = deferred<ContactDetail>();
    vi.mocked(api.detail).mockRejectedValueOnce(new CommandHttpError(404, 'private missing detail')).mockReturnValueOnce(next.promise);
    const view = renderWorkspace(api);
    expect(await screen.findByRole('heading', { name: 'Contact not found' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back to contacts' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('private missing detail');

    navigation.pathname = '/admin/command/contacts/9';
    view.rerender(workspace(api, 9));
    expect(screen.getByRole('status', { name: 'Loading contact workspace' })).toBeInTheDocument();
    expect(screen.queryByText('Contact not found')).not.toBeInTheDocument();
    await act(async () => next.resolve({ ...detail, contact: { ...contact, id: 9, display_name: 'Grace Hopper' } }));
    expect(await screen.findByRole('heading', { name: 'Grace Hopper' })).toBeInTheDocument();
  });

  it('invalidates a fulfilled section cache when the whole workspace retries', async () => {
    navigation.search = new URLSearchParams('contact_view=notes');
    const api = fakeApi();
    vi.mocked(api.detail).mockRejectedValueOnce(new Error('first detail failure')).mockResolvedValueOnce(detail);
    vi.mocked(api.section)
      .mockResolvedValueOnce(sectionPage([]))
      .mockResolvedValueOnce(sectionPage([occurrence({
        section: 'notes',
        value: { kind: 'note', title: 'Refetched captured note', body: 'Second attempt evidence' },
      })]));
    renderWorkspace(api);
    expect(await screen.findByText('Unable to load contact workspace')).toBeInTheDocument();
    await waitFor(() => expect(api.section).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('heading', { name: 'Ada Lovelace' })).toBeInTheDocument();
    expect(await screen.findByText('Refetched captured note')).toBeInTheDocument();
    expect(api.section).toHaveBeenCalledTimes(2);
  });

  it('aborts every in-flight base sibling when one base request fails', async () => {
    const pendingSummary = deferred<ContactWorkspaceSummary>();
    const api = fakeApi();
    vi.mocked(api.detail).mockRejectedValueOnce(new Error('base failure'));
    vi.mocked(api.workspace).mockReturnValueOnce(pendingSummary.promise);
    const view = renderWorkspace(api);
    expect(await screen.findByText('Unable to load contact workspace')).toBeInTheDocument();
    const summarySignal = vi.mocked(api.workspace).mock.calls[0]?.[1]?.signal;
    expect(summarySignal?.aborted).toBe(true);
    view.unmount();
    await act(async () => pendingSummary.resolve(summary));
    expect(screen.queryByRole('heading', { name: 'Ada Lovelace' })).not.toBeInTheDocument();
  });

  it('aborts old requests, ignores stale completion, and does not update after unmount', async () => {
    const first = deferred<ContactDetail>();
    const second = deferred<ContactDetail>();
    const pendingEvidence = deferred<ContactEvidence>();
    const api = fakeApi();
    vi.mocked(api.detail).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const view = renderWorkspace(api, 7);
    const firstSignal = vi.mocked(api.detail).mock.calls[0]?.[1]?.signal;

    vi.mocked(api.evidence).mockReturnValueOnce(pendingEvidence.promise);
    navigation.pathname = '/admin/command/contacts/9';
    view.rerender(workspace(api, 9));
    expect(firstSignal?.aborted).toBe(true);
    await act(async () => second.resolve({
      ...detail,
      contact: { ...contact, id: 9, first_name: 'Grace', last_name: 'Hopper', display_name: 'Grace Hopper' },
    }));
    expect(await screen.findByRole('heading', { name: 'Grace Hopper' })).toBeInTheDocument();
    await act(async () => first.resolve(detail));
    expect(screen.queryByRole('heading', { name: 'Ada Lovelace' })).not.toBeInTheDocument();

    const secondSignal = vi.mocked(api.evidence).mock.calls.at(-1)?.[1]?.signal;
    view.unmount();
    await act(async () => Promise.resolve());
    expect(secondSignal?.aborted).toBe(true);
  });

  it('deep-links the selected top tab and nested task state in the URL', async () => {
    navigation.search = new URLSearchParams('contact_view=tasks&task_state=completed&campaign=sws-fall');
    const api = fakeApi();
    renderWorkspace(api);

    expect(await screen.findByRole('tab', { name: 'Tasks' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Completed' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('Send market report')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));
    expect(navigation.replace).toHaveBeenLastCalledWith(
      '/admin/command/contacts/7?contact_view=notes&campaign=sws-fall',
      { scroll: false },
    );
  });

  it('rejects noncanonical route IDs before mounting any contact API surface', () => {
    for (const raw of ['', '0', '00', '07', '+7', ' 7', '7 ', '1e2', '-1', '9007199254740992']) {
      expect(canonicalContactId(raw)).toBeNull();
    }
    expect(canonicalContactId('7')).toBe(7);

    const api = fakeApi();
    renderWorkspace(api, Number.NaN);
    expect(screen.getByText('Invalid contact')).toBeInTheDocument();
    for (const method of ['detail', 'workspace', 'internalWorkspace', 'neighbors', 'timeline', 'evidence', 'section'] as const) {
      expect(api[method]).not.toHaveBeenCalled();
    }
  });

  it('treats the same-contact URL as source of truth and never reuses neighbors from an old universe', async () => {
    navigation.search = new URLSearchParams('stage=seller&page=2&page_size=25');
    const api = fakeApi();
    const nextNeighbors = deferred<{ previous_contact_id: number | null; next_contact_id: number | null }>();
    vi.mocked(api.neighbors)
      .mockResolvedValueOnce({ previous_contact_id: 5, next_contact_id: 9 })
      .mockReturnValueOnce(nextNeighbors.promise);
    const view = renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    expect(screen.getByRole('button', { name: 'Previous contact' })).toBeEnabled();

    navigation.search = new URLSearchParams('stage=buyer&page=1&page_size=25&contact_view=notes');
    view.rerender(workspace(api));
    await waitFor(() => expect(api.neighbors).toHaveBeenCalledTimes(2));
    expect(api.neighbors).toHaveBeenLastCalledWith(7, expect.objectContaining({ stage: 'buyer', page: 1, page_size: 25 }), { signal: expect.any(AbortSignal) });
    expect(screen.getByRole('button', { name: 'Previous contact' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next contact' })).toBeDisabled();
    expect(await screen.findByRole('tab', { name: 'Notes' })).toHaveAttribute('aria-selected', 'true');

    await act(async () => nextNeighbors.reject(new Error('PLANTED_PRIVATE_NEIGHBOR_ERROR')));
    expect(await screen.findByText(/Directory navigation is unavailable for the current view/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('PLANTED_PRIVATE_NEIGHBOR_ERROR');
  });

  it('aborts and discards a captured section when the contact changes', async () => {
    const oldNotes = deferred<ContactSectionPage>();
    const api = fakeApi();
    const detailNine: ContactDetail = {
      ...detail,
      contact: { ...contact, id: 9, first_name: 'Grace', last_name: 'Hopper', display_name: 'Grace Hopper' },
    };
    const internalNine: ContactInternalWorkspace = {
      ...internalWorkspace,
      contact: { ...internalWorkspace.contact, id: 9, first_name: 'Grace', last_name: 'Hopper' },
      tasks: [],
      notes: [],
    };
    vi.mocked(api.detail).mockImplementation((id) => Promise.resolve(id === 9 ? detailNine : detail));
    vi.mocked(api.internalWorkspace).mockImplementation((id) => Promise.resolve(id === 9 ? internalNine : internalWorkspace));
    vi.mocked(api.evidence).mockImplementation((id) => Promise.resolve({ ...evidence, contact_id: id }));
    vi.mocked(api.section).mockImplementation((id, section) => {
      if (id === 7 && section === 'notes') return oldNotes.promise;
      if (id === 9 && section === 'notes') {
        return Promise.resolve(sectionPage([occurrence({
          section: 'notes',
          value: { kind: 'note', title: 'Grace private note', body: 'Contact nine only' },
        })]));
      }
      return Promise.resolve(pages[section]);
    });
    const view = renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));
    await waitFor(() => expect(api.section).toHaveBeenCalledWith(7, 'notes', 1, 50, { signal: expect.any(AbortSignal) }));
    const oldSignal = vi.mocked(api.section).mock.calls[0]?.[4]?.signal;

    navigation.pathname = '/admin/command/contacts/9';
    navigation.search = new URLSearchParams();
    view.rerender(workspace(api, 9));
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => oldNotes.resolve(sectionPage([occurrence({
      section: 'notes',
      value: { kind: 'note', title: 'PRIVATE CONTACT SEVEN', body: 'Must never cross contacts' },
    })])));
    expect(await screen.findByRole('heading', { name: 'Grace Hopper' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));
    expect(await screen.findByText('Grace private note')).toBeInTheDocument();
    expect(screen.queryByText('PRIVATE CONTACT SEVEN')).not.toBeInTheDocument();
    expect(api.section).toHaveBeenCalledWith(9, 'notes', 1, 50, { signal: expect.any(AbortSignal) });
  });

  it('never turns global archive totals or orphan cells into a current-contact empty claim', async () => {
    const api = fakeApi();
    vi.mocked(api.timeline).mockResolvedValue({ rows: [], next_cursor: null, has_more: false });
    vi.mocked(api.evidence).mockResolvedValue({
      ...evidence,
      capture_positions: [],
      section_matrix: [],
    });
    renderWorkspace(api);
    const timelineRegion = await screen.findByRole('region', { name: 'Contact timeline' });
    expect(await within(timelineRegion).findByText('No recovered Command record is linked to this contact')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));
    expect(await within(screen.getByRole('region', { name: 'Captured source notes' })).findByText('No recovered Command record is linked to this contact')).toBeInTheDocument();
    expect(screen.queryByText('No notes were captured')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Source Evidence' }));
    expect(await screen.findByText('No contact capture positions')).toBeInTheDocument();
    expect(screen.getByText('317 provider contact rows')).toBeInTheDocument();
    expect(screen.getByText('Recovered archive (global)')).toBeInTheDocument();
  });

  it('labels unreconciled and unavailable recovered source coverage instead of showing empty tabs', async () => {
    const unreconciledApi = fakeApi();
    vi.mocked(unreconciledApi.timeline).mockResolvedValue({ rows: [], next_cursor: null, has_more: false });
    vi.mocked(unreconciledApi.evidence).mockResolvedValue({
      ...evidence,
      provider_contact_rows: 0,
      resolved_provider_identities: 0,
      capture_positions: [],
      section_matrix: [],
      sources: [],
      capture_quality: 'limitation',
    });
    const first = renderWorkspace(unreconciledApi);
    const unreconciledTimeline = await screen.findByRole('region', { name: 'Contact timeline' });
    expect(await within(unreconciledTimeline).findByText('Recovered Command timeline has not been restored')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));
    expect(await within(screen.getByRole('region', { name: 'Captured source notes' })).findByText('Recovered Command notes have not been restored')).toBeInTheDocument();
    first.unmount();

    const unavailableApi = fakeApi();
    vi.mocked(unavailableApi.timeline).mockResolvedValue({ rows: [], next_cursor: null, has_more: false });
    vi.mocked(unavailableApi.evidence).mockRejectedValue(new Error('PRIVATE_EVIDENCE_FAILURE'));
    renderWorkspace(unavailableApi);
    const unavailableTimeline = await screen.findByRole('region', { name: 'Contact timeline' });
    expect(await within(unavailableTimeline).findByText('Recovered source coverage is unavailable')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('PRIVATE_EVIDENCE_FAILURE');
    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));
    expect(await within(screen.getByRole('region', { name: 'Captured source notes' })).findByText('Recovered source coverage is unavailable')).toBeInTheDocument();
    expect(screen.queryByText('No notes were captured')).not.toBeInTheDocument();
  });

  it('renders matching evidence cells even when the timeline has no rows', async () => {
    const api = fakeApi();
    const partialTimelineSections = evidenceMatrix.map((cell) => cell.section === 'timeline'
      ? {
        ...cell,
        capture_quality: 'partial' as const,
        row_count: 0,
        is_empty: true,
        limitation_codes: ['timeline_partial'],
      }
      : cell);
    vi.mocked(api.timeline).mockResolvedValue({ rows: [], next_cursor: null, has_more: false });
    vi.mocked(api.evidence).mockResolvedValue({
      ...evidence,
      capture_positions: [{ ...evidence.capture_positions[0]!, sections: partialTimelineSections }],
      section_matrix: partialTimelineSections,
    });

    renderWorkspace(api);

    expect(await screen.findByText('Timeline was not fully captured')).toBeInTheDocument();
    const timeline = screen.getByRole('region', { name: 'Contact timeline' });
    const panel = within(timeline).getByRole('region', { name: 'Capture position 1 · timeline evidence' });
    expect(within(panel).getByText('Partial capture')).toBeInTheDocument();
    expect(within(panel).getByText('0')).toBeInTheDocument();
    expect(within(panel).getByText('timeline_partial')).toBeInTheDocument();
  });

  it('accepts section-specific source records while matching evidence by capture position', async () => {
    const api = fakeApi();
    const sectionSources = evidenceMatrix.map((cell, index) => ({ ...cell, source_record_id: 700 + index }));
    vi.mocked(api.evidence).mockResolvedValue({
      ...evidence,
      capture_positions: [{ ...evidence.capture_positions[0]!, source_record_id: 501, sections: sectionSources }],
      section_matrix: sectionSources,
    });
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));
    expect(await screen.findByText('No notes were captured')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Captured source notes' })).getByText('Complete capture')).toBeInTheDocument();
  });

  it('keeps loaded rows visible while independently paging captured sections and timeline cursors', async () => {
    const api = fakeApi();
    const secondSection = deferred<ContactSectionPage>();
    const secondTimeline = deferred<ContactTimelinePage>();
    const firstOpportunity = occurrence({
      section: 'opportunities', occurrence_ordinal: 1,
      value: { kind: 'opportunity', title: 'Captured row one', stage: null, value_cents: null },
    });
    const secondOpportunity = occurrence({
      section: 'opportunities', occurrence_ordinal: 51,
      value: { kind: 'opportunity', title: 'Captured row fifty-one', stage: null, value_cents: null },
    });
    vi.mocked(api.section).mockImplementation((_id, section, page) => {
      if (section !== 'opportunities') return Promise.resolve(pages[section]);
      if (page === 2) return secondSection.promise;
      return Promise.resolve({ rows: [firstOpportunity], total: 51, page: 1, page_size: 50, page_count: 2 });
    });
    vi.mocked(api.timeline).mockImplementation((_id, cursor) => {
      if (cursor === 'cursor-2') return secondTimeline.promise;
      return Promise.resolve({ rows: [timeline.rows[0]!], next_cursor: 'cursor-2', has_more: true });
    });
    renderWorkspace(api);
    expect(await screen.findByText('Discovery call completed')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Opportunities' }));
    expect(await screen.findByText('Captured row one')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Load more captured opportunities' }));
    expect(screen.getByText('Captured row one')).toBeInTheDocument();
    await act(async () => secondSection.resolve({ rows: [secondOpportunity], total: 51, page: 2, page_size: 50, page_count: 2 }));
    expect(await screen.findByText('Captured row fifty-one')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Timeline' }));
    await userEvent.click(screen.getByRole('button', { name: 'Load more timeline' }));
    expect(screen.getByText('Discovery call completed')).toBeInTheDocument();
    await act(async () => secondTimeline.resolve({ rows: [timeline.rows[1]!], next_cursor: null, has_more: false }));
    expect(await screen.findByText('Consultation booked')).toBeInTheDocument();
    expect(api.timeline).toHaveBeenLastCalledWith(7, 'cursor-2', 50, { signal: expect.any(AbortSignal) });
  });

  it('uses one contact-wide mutation lock and exposes a single-flight verification retry', async () => {
    const api = fakeApi();
    vi.mocked(api.createNote).mockRejectedValue(new Error('PLANTED_PRIVATE_WRITE_ERROR'));
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));

    vi.mocked(api.internalWorkspace).mockRejectedValueOnce(new Error('private refresh'));
    vi.mocked(api.workspace).mockRejectedValueOnce(new Error('private refresh'));
    vi.mocked(api.timeline).mockRejectedValueOnce(new Error('private refresh'));
    const verifyInternal = deferred<ContactInternalWorkspace>();
    const verifySummary = deferred<ContactWorkspaceSummary>();
    const verifyTimeline = deferred<ContactTimelinePage>();
    vi.mocked(api.internalWorkspace).mockReturnValueOnce(verifyInternal.promise);
    vi.mocked(api.workspace).mockReturnValueOnce(verifySummary.promise);
    vi.mocked(api.timeline).mockReturnValueOnce(verifyTimeline.promise);

    await userEvent.click(screen.getByRole('button', { name: 'Add note' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Note body' }), 'Uncertain private note');
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }));
    expect(await screen.findByText('Mutation status is unknown. Current contact data could not be verified.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close contact action' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'Note body' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Edit profile' })).toBeDisabled();

    const retry = screen.getByRole('button', { name: 'Retry contact refresh' });
    fireEvent.click(retry);
    fireEvent.click(retry);
    expect(screen.getByRole('button', { name: 'Refreshing…' })).toBeDisabled();
    expect(api.internalWorkspace).toHaveBeenCalledTimes(3);
    await act(async () => {
      verifyInternal.resolve(internalWorkspace);
      verifySummary.resolve(summary);
      verifyTimeline.resolve(timeline);
    });
    expect(await screen.findByText('Mutation status is unknown. Current contact data was refreshed.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save note' })).toBeEnabled();
    expect(document.body).not.toHaveTextContent('PLANTED_PRIVATE_WRITE_ERROR');
  });

  it('closes unlocked editors with Escape, restores focus, and blocks Escape while pending', async () => {
    const api = fakeApi();
    const pendingNote = deferred<{ id: number; body: string }>();
    vi.mocked(api.createNote).mockReturnValue(pendingNote.promise);
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });

    const editProfile = screen.getByRole('button', { name: 'Edit profile' });
    await userEvent.click(editProfile);
    fireEvent.keyDown(screen.getByRole('region', { name: 'Edit SWS profile' }), { key: 'Escape' });
    expect(screen.queryByRole('region', { name: 'Edit SWS profile' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Edit profile' })).toHaveFocus();
    await userEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    expect(screen.queryByRole('region', { name: 'Edit SWS profile' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Edit profile' })).toHaveFocus();

    const addNote = screen.getByRole('button', { name: 'Add note' });
    await userEvent.click(addNote);
    fireEvent.keyDown(screen.getByRole('region', { name: 'Add note' }), { key: 'Escape' });
    expect(screen.queryByRole('region', { name: 'Add note' })).not.toBeInTheDocument();
    expect(addNote).toHaveFocus();

    await userEvent.click(addNote);
    await userEvent.type(screen.getByLabelText('Note body'), 'Pending note');
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }));
    fireEvent.keyDown(screen.getByRole('region', { name: 'Add note' }), { key: 'Escape' });
    expect(screen.getByRole('region', { name: 'Add note' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close contact action' })).toBeDisabled();
    await act(async () => pendingNote.resolve({ id: 301, body: 'Pending note' }));
    await waitFor(() => expect(addNote).toHaveFocus());
  });

  it('provides an Escape/cancel path for a task draft and blocks it during save', async () => {
    const api = fakeApi();
    const pendingTask = deferred<Task>();
    vi.mocked(api.createTask).mockReturnValue(pendingTask.promise);
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));
    const addTask = await screen.findByRole('button', { name: 'Add task' });
    await userEvent.click(addTask);
    fireEvent.keyDown(screen.getByRole('region', { name: 'Add task' }), { key: 'Escape' });
    expect(screen.queryByRole('region', { name: 'Add task' })).not.toBeInTheDocument();
    expect(addTask).toHaveFocus();

    await userEvent.click(addTask);
    await userEvent.type(screen.getByLabelText('Task title'), 'Pending task');
    await userEvent.click(screen.getByRole('button', { name: 'Save task' }));
    fireEvent.keyDown(screen.getByRole('region', { name: 'Add task' }), { key: 'Escape' });
    expect(screen.getByRole('region', { name: 'Add task' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close task editor' })).toBeDisabled();
    await act(async () => pendingTask.resolve({
      ...internalWorkspace.tasks[0]!,
      id: 999,
      title: 'Pending task',
      priority: 'normal',
      status: 'open',
      archived_at: null,
      archive_reason: null,
      version: 1,
    }));
    await waitFor(() => expect(addTask).toHaveFocus());
  });

  it('aborts a pending contact-task create on navigation without surfacing uncertainty', async () => {
    const api = fakeApi();
    const pendingTask = deferred<Task>();
    vi.mocked(api.createTask).mockReturnValueOnce(pendingTask.promise);
    const view = renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Add task' }));
    await userEvent.type(screen.getByLabelText('Task title'), 'Navigation-safe task');
    await userEvent.click(screen.getByRole('button', { name: 'Save task' }));
    const signal = vi.mocked(api.createTask).mock.calls[0]?.[2]?.signal;

    navigation.pathname = '/admin/command/contacts/9';
    view.rerender(workspace(api, 9));
    expect(signal?.aborted).toBe(true);
    await act(async () => pendingTask.reject(new DOMException('Navigation aborted', 'AbortError')));

    expect(screen.queryByText(/Task mutation status is unknown/)).not.toBeInTheDocument();
    expect(screen.queryByText(/server may have applied/)).not.toBeInTheDocument();
  });

  it('validates code-point input bounds locally before any write or uncertainty refresh', async () => {
    const api = fakeApi();
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });

    await userEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    fireEvent.change(screen.getByLabelText('First name'), { target: { value: '😀'.repeat(121) } });
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    expect(screen.getByText('First name must be 120 characters or fewer.')).toBeInTheDocument();
    expect(api.update).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Add tag' }));
    fireEvent.change(screen.getByLabelText('Tag name'), { target: { value: '😀'.repeat(81) } });
    await userEvent.click(within(screen.getByRole('region', { name: 'Add tag' })).getByRole('button', { name: 'Add tag' }));
    expect(screen.getByText('Tag name must be 80 characters or fewer.')).toBeInTheDocument();
    expect(api.createTag).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Add task' }));
    fireEvent.change(screen.getByLabelText('Task title'), { target: { value: '😀'.repeat(256) } });
    await userEvent.click(screen.getByRole('button', { name: 'Save task' }));
    expect(screen.getByText('Task title must be 255 characters or fewer.')).toBeInTheDocument();
    expect(api.createTask).not.toHaveBeenCalled();
  });

  it('binds jump results to their exact request and clears stale or oversized drafts immediately', async () => {
    navigation.search = new URLSearchParams('page=3&page_size=25');
    const api = fakeApi();
    const adaRows = deferred<ContactDirectoryPage>();
    const graceRows = deferred<ContactDirectoryPage>();
    vi.mocked(api.directory).mockImplementation((request) => request.query === 'Ada' ? adaRows.promise : graceRows.promise);
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    const jump = screen.getByRole('searchbox', { name: 'Jump to contact' });
    fireEvent.change(jump, { target: { value: 'Ada' } });
    await waitFor(() => expect(api.directory).toHaveBeenCalledTimes(1));
    const adaSignal = vi.mocked(api.directory).mock.calls[0]?.[1]?.signal;
    fireEvent.change(jump, { target: { value: 'Grace' } });
    expect(adaSignal?.aborted).toBe(true);
    await waitFor(() => expect(api.directory).toHaveBeenCalledTimes(2));
    await act(async () => adaRows.resolve(directoryPage([{ ...contact, id: 20, display_name: 'Stale Ada' }])));
    expect(screen.queryByRole('button', { name: 'Open Stale Ada' })).not.toBeInTheDocument();
    await act(async () => graceRows.resolve(directoryPage([{ ...contact, id: 21, display_name: 'Grace Hopper' }])));
    const result = await screen.findByRole('button', { name: 'Open Grace Hopper' });
    await userEvent.click(result);
    expect(navigation.push).toHaveBeenLastCalledWith('/admin/command/contacts/21?query=Grace&page=1&page_size=25');

    fireEvent.change(jump, { target: { value: '😀'.repeat(201) } });
    expect(screen.queryByRole('button', { name: 'Open Grace Hopper' })).not.toBeInTheDocument();
    await new Promise((resolve) => window.setTimeout(resolve, 250));
    expect(api.directory).toHaveBeenCalledTimes(2);
  });

  it('refetches the captured Notes occurrence after deleting the exact SWS note', async () => {
    const api = fakeApi();
    const materialized = occurrence({
      status: 'materialized',
      section: 'notes',
      value: { kind: 'note', title: 'Captured linked note', body: 'Same immutable source value' },
      entity_type: 'note',
      entity_id: 111,
    });
    const sourceOnly = occurrence({
      section: 'notes',
      value: { kind: 'note', title: 'Captured linked note', body: 'Same immutable source value' },
    });
    vi.mocked(api.section)
      .mockResolvedValueOnce(sectionPage([materialized]))
      .mockResolvedValueOnce(sectionPage([sourceOnly]));
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Notes' }));
    expect(await screen.findByText('Materialized in SWS')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Delete SWS note 111' }));
    await waitFor(() => expect(api.section).toHaveBeenCalledTimes(2));
    const captured = screen.getByRole('region', { name: 'Captured source notes' });
    expect(await within(captured).findByText('Source evidence only')).toBeInTheDocument();
    expect(within(captured).getByText('Same immutable source value')).toBeInTheDocument();
    expect(api.deleteNote).toHaveBeenCalledWith(7, 111, { signal: expect.any(AbortSignal) });
  });

  it('treats an already-absent tag removal as a no-op without inventing timeline activity', async () => {
    const api = fakeApi();
    vi.mocked(api.removeTag).mockResolvedValue({ removed: false, contact_id: 7, tag_id: 3 });
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('button', { name: 'Remove VIP tag' }));
    await waitFor(() => expect(api.internalWorkspace).toHaveBeenCalledTimes(2));
    expect(api.removeTag).toHaveBeenCalledWith(7, 3, { signal: expect.any(AbortSignal) });
    expect(api.detail).toHaveBeenCalledTimes(2);
    expect(api.neighbors).toHaveBeenCalledTimes(2);
    expect(api.timeline).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Tag removed')).not.toBeInTheDocument();
  });

  it('reports uncertain tag assignment only after authoritative contact refresh', async () => {
    const api = fakeApi();
    vi.mocked(api.assignTag).mockRejectedValue(new Error('PLANTED_PRIVATE_ASSIGNMENT_ERROR'));
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('button', { name: 'Add tag' }));
    await userEvent.type(screen.getByLabelText('Tag name'), 'Seller');
    await userEvent.click(within(screen.getByRole('region', { name: 'Add tag' })).getByRole('button', { name: 'Add tag' }));
    expect(await screen.findByText('Tag assignment status is unknown. Current contact data was refreshed.')).toBeInTheDocument();
    expect(api.createTag).toHaveBeenCalledWith({ name: 'Seller' }, { signal: expect.any(AbortSignal) });
    expect(api.assignTag).toHaveBeenCalledWith(7, 203, { signal: expect.any(AbortSignal) });
    expect(api.internalWorkspace).toHaveBeenCalledTimes(2);
    expect(api.detail).toHaveBeenCalledTimes(2);
    expect(document.body).not.toHaveTextContent('PLANTED_PRIVATE_ASSIGNMENT_ERROR');
  });

  it('aborts pending mutations on contact change and never carries their draft or completion', async () => {
    const pendingNote = deferred<{ id: number; body: string }>();
    const api = fakeApi();
    const detailNine: ContactDetail = {
      ...detail,
      contact: { ...contact, id: 9, first_name: 'Grace', last_name: 'Hopper', display_name: 'Grace Hopper' },
    };
    const internalNine: ContactInternalWorkspace = {
      ...internalWorkspace,
      contact: { ...internalWorkspace.contact, id: 9, first_name: 'Grace', last_name: 'Hopper' },
      tasks: [],
      notes: [],
    };
    vi.mocked(api.createNote).mockReturnValue(pendingNote.promise);
    vi.mocked(api.detail).mockImplementation((id) => Promise.resolve(id === 9 ? detailNine : detail));
    vi.mocked(api.internalWorkspace).mockImplementation((id) => Promise.resolve(id === 9 ? internalNine : internalWorkspace));
    vi.mocked(api.evidence).mockImplementation((id) => Promise.resolve({ ...evidence, contact_id: id }));
    const view = renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('button', { name: 'Add note' }));
    await userEvent.type(screen.getByLabelText('Note body'), 'Contact seven private draft');
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }));
    const writeSignal = vi.mocked(api.createNote).mock.calls[0]?.[2]?.signal;
    expect(screen.getByRole('button', { name: 'Close contact action' })).toBeDisabled();

    navigation.pathname = '/admin/command/contacts/9';
    view.rerender(workspace(api, 9));
    expect(writeSignal?.aborted).toBe(true);
    await act(async () => pendingNote.resolve({ id: 999, body: 'Contact seven private draft' }));
    expect(await screen.findByRole('heading', { name: 'Grace Hopper' })).toBeInTheDocument();
    expect(screen.queryByText('Contact seven private draft')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add note' })).toBeEnabled();
  });

  it('aborts an authenticated artifact download on unmount and ignores its late blob', async () => {
    const pendingBlob = deferred<Blob>();
    const api = fakeApi();
    vi.mocked(api.artifactBlob).mockReturnValue(pendingBlob.promise);
    const view = renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    await userEvent.click(screen.getByRole('tab', { name: 'Source Evidence' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Download html source artifact 55' }));
    expect(screen.getByRole('status')).toHaveTextContent('Downloading source artifact 55');
    const signal = vi.mocked(api.artifactBlob).mock.calls[0]?.[1]?.signal;
    view.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => pendingBlob.resolve(new Blob(['late private bytes'])));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('contains no upstream vendor marks or imitation copy', async () => {
    renderWorkspace(fakeApi());
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    expect(document.body).not.toHaveTextContent(/Keller Williams|CommandMC|KWRI/i);
    expect(document.querySelector('[class*="kw-red"], [style*="#b40101"]')).toBeNull();
  });

  it('keeps pending profile saves inside the mobile disclosure and preserves nested Escape ownership', async () => {
    const api = fakeApi();
    const pendingUpdate = deferred<ContactInternalWorkspace['contact']>();
    vi.mocked(api.update).mockReturnValueOnce(pendingUpdate.promise);
    renderWorkspace(api);
    await screen.findByRole('heading', { name: 'Ada Lovelace' });
    const disclosure = screen.getByRole('button', { name: 'Profile details' });
    await userEvent.click(disclosure);
    expect(disclosure).toHaveAttribute('aria-expanded', 'true');
    let editProfile = screen.getByRole('button', { name: 'Edit profile' });
    await userEvent.click(editProfile);
    await userEvent.clear(screen.getByLabelText('Stage'));
    await userEvent.type(screen.getByLabelText('Stage'), 'active review');
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    const pendingEditor = screen.getByRole('region', { name: 'Edit SWS profile' });
    await waitFor(() => expect(pendingEditor).toHaveFocus());
    fireEvent.keyDown(pendingEditor, { key: 'Escape' });
    expect(screen.getByRole('region', { name: 'Edit SWS profile' })).toBeInTheDocument();
    expect(disclosure).toHaveAttribute('aria-expanded', 'true');
    expect(pendingEditor).toHaveFocus();

    await act(async () => pendingUpdate.resolve({ ...internalWorkspace.contact, stage: 'active review' }));
    editProfile = await screen.findByRole('button', { name: 'Edit profile' });
    await waitFor(() => expect(editProfile).toHaveFocus());
    await userEvent.click(editProfile);
    fireEvent.keyDown(screen.getByRole('region', { name: 'Edit SWS profile' }), { key: 'Escape' });
    expect(disclosure).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: 'Edit profile' })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('button', { name: 'Edit profile' }), { key: 'Escape' });
    expect(disclosure).toHaveAttribute('aria-expanded', 'false');
    expect(disclosure).toHaveFocus();
  });

  it('binds detail mobile targets, responsive disclosure, wrapping, and print controls in scoped CSS', () => {
    const css = readFileSync('src/app/admin/command/command-shell.css', 'utf8');
    expect(css).toMatch(/\.command-root \.command-contact-detail-grid\s*\{[^}]*grid-template-columns:\s*minmax\(320px, 352px\) minmax\(0, 1fr\)/);
    expect(css).toMatch(/@media \(max-width: 767px\)[\s\S]*?\.command-root \.command-contact-detail-grid\s*\{[^}]*display:\s*block/);
    expect(css).toMatch(/\.command-root \.command-contact-jump input\s*\{[^}]*min-height:\s*44px/);
    expect(css).toMatch(/\.command-root \.command-contact-jump-results button\s*\{[^}]*min-height:\s*44px/);
    expect(css).toMatch(/\.command-root \.command-contact-editor-fields input,[\s\S]*?\.command-root \.command-contact-action-form textarea\s*\{[^}]*min-height:\s*44px/);
    expect(css).toMatch(/\.command-root \.command-contact-record-card,[\s\S]*?\.command-root \.command-contact-bookings article > \*\s*\{[^}]*min-width:\s*0/);
    expect(css).toMatch(/\.command-root \.command-contact-record-card h4,[\s\S]*?\.command-root \.command-contact-bookings p\s*\{[^}]*overflow-wrap:\s*anywhere/);
    expect(css).toMatch(/@media print[\s\S]*?\.command-root \.command-contact-detail-workspace \.command-module-actions,[\s\S]*?\.command-root \.command-contact-detail-workspace \.command-tabs/);
  });
});
