import type { CommandHomeInput } from '@/lib/command/home';

export const completeHomeInput: CommandHomeInput = {
  overview: { contacts: 4, open_tasks: 4, opportunities: 5, active_smart_plans: 2 },
  contacts: [
    {
      id: 1,
      first_name: 'Avery',
      last_name: 'Lake',
      email: 'avery@example.test',
      phone: null,
      stage: 'lead',
      birthday: '1991-08-21',
      last_contacted_at: null,
      recently_active_at: null,
    },
    {
      id: 2,
      first_name: 'Morgan',
      last_name: 'Hill',
      email: null,
      phone: null,
      stage: 'lead',
      anniversary: '2018-08-12',
      last_contacted_at: null,
      recently_active_at: null,
    },
    {
      id: 3,
      first_name: 'Casey',
      last_name: 'Pine',
      email: null,
      phone: '+1 555 0103',
      stage: 'lead',
      last_contacted_at: '2026-08-10T15:00:00.000Z',
      recently_active_at: '2026-08-11T12:00:00.000Z',
    },
    {
      id: 4,
      first_name: 'Riley',
      last_name: 'Stone',
      email: 'riley@example.test',
      phone: '+1 555 0104',
      stage: 'client',
      last_contacted_at: '2026-08-09T15:00:00.000Z',
      recently_active_at: '2026-08-10T12:00:00.000Z',
    },
  ],
  tasks: [
    { id: 1, title: 'Call Avery', contact_id: 1, description: '', priority: 'high', due_at: '2026-08-09T13:00:00.000Z', status: 'open' },
    { id: 2, title: 'Review offer', contact_id: 4, description: '', priority: 'high', due_at: '2026-08-10T13:00:00.000Z', status: 'open' },
    { id: 3, title: 'Send market update', contact_id: 3, description: '', priority: 'normal', due_at: '2026-08-11T13:00:00.000Z', status: 'in_progress' },
    { id: 4, title: 'Plan next touch', contact_id: 2, description: '', priority: 'normal', due_at: null, status: 'open' },
    { id: 5, title: 'Completed consult', contact_id: 4, description: '', priority: 'normal', due_at: '2026-08-08T13:00:00.000Z', status: 'completed' },
    { id: 6, title: 'Archived reminder', contact_id: 1, description: '', priority: 'low', due_at: null, status: 'archived' },
  ],
  opportunities: [
    { id: 1, name: 'Lake purchase', stage: 'active', value_cents: 52_500_000 },
    { id: 2, name: 'Stone listing', stage: 'under_contract', value_cents: 71_000_000 },
    { id: 3, name: 'Pine search', stage: 'cultivate', value_cents: null },
    { id: 4, name: 'Hill pause', stage: 'lost', value_cents: 22_000_000 },
    { id: 5, name: 'Closed consult', stage: 'closed', value_cents: 18_000_000 },
  ],
  celebrations: {
    birthdays: [
      {
        id: 1,
        first_name: 'Avery',
        last_name: 'Lake',
        email: 'avery@example.test',
        phone: null,
        stage: 'lead',
        birthday: '1991-08-21',
      },
    ],
    anniversaries: [
      {
        id: 2,
        first_name: 'Morgan',
        last_name: 'Hill',
        email: null,
        phone: null,
        stage: 'lead',
        anniversary: '2018-08-12',
      },
    ],
  },
  goals: [
    { id: 1, name: 'Appointments', target_value: 12, current_value: 5, period: 'monthly' },
    { id: 2, name: 'Closings', target_value: 4, current_value: 1, period: 'quarterly' },
  ],
  briefing: {
    summary: 'Clear overdue tasks, then contact new leads.',
    source: 'internal-crm',
    requires_review: true,
  },
  errors: {},
};

export const inputWithoutLastContactFields: CommandHomeInput = {
  ...completeHomeInput,
  contacts: completeHomeInput.contacts === null
    ? null
    : completeHomeInput.contacts.map((contact) => ({
        id: contact.id,
        first_name: contact.first_name,
        last_name: contact.last_name,
        email: contact.email,
        phone: contact.phone,
        stage: contact.stage,
        birthday: contact.birthday,
        anniversary: contact.anniversary,
        recently_active_at: contact.recently_active_at,
        health_score: contact.health_score,
      })),
};

export const inputWithoutRecentActivityFields: CommandHomeInput = {
  ...completeHomeInput,
  contacts: completeHomeInput.contacts === null
    ? null
    : completeHomeInput.contacts.map((contact) => ({
        id: contact.id,
        first_name: contact.first_name,
        last_name: contact.last_name,
        email: contact.email,
        phone: contact.phone,
        stage: contact.stage,
        birthday: contact.birthday,
        anniversary: contact.anniversary,
        last_contacted_at: contact.last_contacted_at,
        health_score: contact.health_score,
      })),
};

export const emptyButAvailableInput: CommandHomeInput = {
  overview: { contacts: 0, open_tasks: 0, opportunities: 0, active_smart_plans: 0 },
  contacts: [],
  tasks: [],
  opportunities: [],
  celebrations: { birthdays: [], anniversaries: [] },
  goals: [],
  briefing: null,
  errors: {},
};

export const emptyButUnavailableInput: CommandHomeInput = {
  overview: null,
  contacts: null,
  tasks: null,
  opportunities: null,
  celebrations: null,
  goals: null,
  briefing: null,
  errors: {
    overview: 'Unavailable',
    contacts: 'Unavailable',
    tasks: 'Unavailable',
    opportunities: 'Unavailable',
    celebrations: 'Unavailable',
    goals: 'Unavailable',
    briefing: 'Unavailable',
  },
};
