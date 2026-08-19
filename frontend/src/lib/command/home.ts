import {
  commandApi,
  type AiBriefing,
  type CommandRequestOptions,
  type Contact,
  type Goal,
  type Opportunity,
  type Overview,
  type Task,
  type TaskFilters,
} from './api';
import {
  type ContactCelebrations,
  type ContactDirectoryPage,
  type ContactDirectoryRequest,
  type ContactDirectoryRow,
} from './contacts';
import { CommandDecodeError } from './http';

export type CommandHomeRegion =
  | 'overview'
  | 'contacts'
  | 'tasks'
  | 'opportunities'
  | 'celebrations'
  | 'goals'
  | 'briefing';

export type CommandHomeInput = Readonly<{
  overview: Overview | null;
  contacts: readonly Contact[] | null;
  smartViewCounts: HomeSmartViewCounts | null;
  tasks: readonly Task[] | null;
  opportunities: readonly Opportunity[] | null;
  celebrations: HomeCelebrations | null;
  goals: readonly Goal[] | null;
  briefing: AiBriefing | null;
  errors: Readonly<Partial<Record<CommandHomeRegion, string>>>;
}>;

export type HomeSmartViewCounts = Readonly<{
  never_contacted: number;
  recently_active: number;
  birthdays_this_month: number;
  anniversaries_this_month: number;
}>;

export type HomeCelebrationRow = Readonly<{
  contactId: number;
  displayName: string;
  kind: 'birthday' | 'anniversary';
  month: number;
  day: number;
  year: number | null;
  yearQuality: 'verified' | 'yearless' | 'sentinel' | 'unknown';
  origin: 'internal_crm' | 'recovered';
}>;

export type HomeCelebrations = Readonly<{
  birthdays: readonly HomeCelebrationRow[];
  anniversaries: readonly HomeCelebrationRow[];
}>;

export type ReadinessFactorKey =
  | 'overdue_tasks'
  | 'uncontacted_leads'
  | 'contact_health'
  | 'active_opportunities';

export type ReadinessFactor = Readonly<{
  key: ReadinessFactorKey;
  label: string;
  available: boolean;
  score: number | null;
  affected: number | null;
  total: number | null;
  weight: number;
  href: string;
  insight: string;
}>;

export type FollowUpReadiness = Readonly<{
  score: number | null;
  status: 'ready' | 'watch' | 'at_risk' | 'partial';
  label: string;
  coverage: Readonly<{ available: number; total: 4 }>;
  factors: readonly ReadinessFactor[];
}>;

export type HomeShortcut = Readonly<{
  key: 'never_contacted' | 'recently_active' | 'birthdays' | 'anniversaries';
  label: string;
  count: number | null;
  evidenceState: 'observed_record' | 'partial_capture';
  href: string;
}>;

export type HomeKpi = Readonly<{
  key: 'never_contacted' | 'open_tasks' | 'active_opportunities' | 'contactable_profiles';
  label: string;
  value: string;
  insight: string;
  href: string;
}>;

export type HomeNextAction = Readonly<{
  kind: ReadinessFactorKey;
  title: string;
  affected: number;
  urgency: number;
  href: string;
}>;

export type CommandHomeModel = Readonly<{
  readiness: FollowUpReadiness;
  shortcuts: readonly HomeShortcut[];
  kpis: readonly HomeKpi[];
  nextActions: readonly HomeNextAction[];
  tasks: readonly Task[] | null;
  recentContacts: readonly Contact[];
  celebrations: HomeCelebrations | null;
  goals: readonly Goal[] | null;
  briefing: AiBriefing | null;
  bookingsState: 'partial_capture';
  regionErrors: Readonly<Partial<Record<CommandHomeRegion, string>>>;
}>;

export type CommandHomeApi = Readonly<{
  overview: (options?: CommandRequestOptions) => Promise<Overview>;
  contactDirectory: (
    request: ContactDirectoryRequest,
    options?: CommandRequestOptions,
  ) => Promise<ContactDirectoryPage>;
  tasks: (
    filters?: TaskFilters,
    options?: CommandRequestOptions,
  ) => Promise<readonly Task[]>;
  opportunities: (options?: CommandRequestOptions) => Promise<readonly Opportunity[]>;
  celebrations: (
    month: number,
    options?: CommandRequestOptions,
  ) => Promise<ContactCelebrations>;
  goals: (options?: CommandRequestOptions) => Promise<readonly Goal[]>;
  aiBriefing: (options?: CommandRequestOptions) => Promise<AiBriefing>;
}>;

const CONTACT_SMART_VIEW_URLS = {
  never_contacted: '/admin/command/contacts?smart_view=never_contacted',
  recently_active: '/admin/command/contacts?smart_view=recently_active',
  birthdays_this_month: '/admin/command/contacts?smart_view=birthdays_this_month',
  anniversaries_this_month: '/admin/command/contacts?smart_view=anniversaries_this_month',
} as const;

const ACTIVE_OPPORTUNITY_STAGES = new Set(['active', 'offer', 'under_contract']);

function roundedPercentage(numerator: number, denominator: number): number {
  return Math.round(100 * (numerator / Math.max(denominator, 1)));
}

function unavailableFactor(
  key: ReadinessFactorKey,
  label: string,
  weight: number,
  href: string,
  insight: string,
): ReadinessFactor {
  return { key, label, available: false, score: null, affected: null, total: null, weight, href, insight };
}

function availableFactor(
  key: ReadinessFactorKey,
  label: string,
  weight: number,
  href: string,
  affected: number,
  total: number,
  score: number,
  insight: string,
): ReadinessFactor {
  return { key, label, available: true, score, affected, total, weight, href, insight };
}

function activeTasks(tasks: readonly Task[]): Task[] {
  return tasks.filter((task) => {
    if (task.status === 'open' || task.status === 'in_progress') return true;
    if (
      task.status === 'completed'
      || task.status === 'cancelled'
      || task.status === 'archived'
    ) return false;
    throw new CommandDecodeError('tasks.status', 'known task workflow status');
  });
}

function buildFactors(input: CommandHomeInput, now: Date): readonly ReadinessFactor[] {
  const taskHref = '/admin/command/tasks?tab=todo&due=past';
  const overdueTasks = input.tasks === null
    ? unavailableFactor('overdue_tasks', 'Overdue tasks', 35, taskHref, 'Task due dates are unavailable.')
    : (() => {
        const open = activeTasks(input.tasks);
        if (open.length === 0) {
          return availableFactor('overdue_tasks', 'Overdue tasks', 35, taskHref, 0, 0, 100, 'No records in scope.');
        }
        const overdue = open.filter((task) => {
          if (!task.due_at) return false;
          const dueTime = Date.parse(task.due_at);
          return Number.isFinite(dueTime) && dueTime < now.getTime();
        }).length;
        return availableFactor(
          'overdue_tasks',
          'Overdue tasks',
          35,
          taskHref,
          overdue,
          open.length,
          roundedPercentage(open.length - overdue, open.length),
          overdue === 0 ? 'No open tasks are overdue.' : `${overdue} overdue ${overdue === 1 ? 'task needs' : 'tasks need'} attention.`,
        );
      })();

  const leadHref = CONTACT_SMART_VIEW_URLS.never_contacted;
  const leadContacts = input.contacts?.filter((contact) => contact.stage.trim().toLowerCase() === 'lead') ?? null;
  const uncontactedLeads = leadContacts === null || input.smartViewCounts === null
    ? unavailableFactor(
        'uncontacted_leads',
        'Never-contacted leads',
        30,
        leadHref,
        'Last-contact history is unavailable.',
      )
    : leadContacts.length === 0
      ? availableFactor('uncontacted_leads', 'Never-contacted leads', 30, leadHref, 0, 0, 100, 'No records in scope.')
      : (() => {
          const neverContacted = input.smartViewCounts?.never_contacted ?? 0;
          return availableFactor(
            'uncontacted_leads',
            'Never-contacted leads',
            30,
            leadHref,
            neverContacted,
            leadContacts.length,
            roundedPercentage(leadContacts.length - neverContacted, leadContacts.length),
            neverContacted === 0
              ? 'Every lead has contact history.'
              : `${neverContacted} ${neverContacted === 1 ? 'lead has' : 'leads have'} no contact history.`,
          );
        })();

  const contactHref = '/admin/command/contacts';
  const contactHealth = input.contacts === null
    ? unavailableFactor('contact_health', 'Contact health', 20, contactHref, 'Contact profile coverage is unavailable.')
    : input.contacts.length === 0
      ? availableFactor('contact_health', 'Contact health', 20, contactHref, 0, 0, 100, 'No records in scope.')
      : (() => {
          const contactable = input.contacts.filter((contact) => Boolean(contact.email?.trim() || contact.phone?.trim())).length;
          const missing = input.contacts.length - contactable;
          return availableFactor(
            'contact_health',
            'Contact health',
            20,
            contactHref,
            missing,
            input.contacts.length,
            roundedPercentage(contactable, input.contacts.length),
            missing === 0
              ? 'Every profile has an email or phone.'
              : `${missing} ${missing === 1 ? 'profile needs' : 'profiles need'} an email or phone.`,
          );
        })();

  const opportunityHref = '/admin/command/opportunities';
  const activeOpportunities = input.opportunities === null
    ? unavailableFactor(
        'active_opportunities',
        'Active opportunities',
        15,
        opportunityHref,
        'Opportunity stages are unavailable.',
      )
    : (() => {
        const nonLost = input.opportunities.filter((opportunity) => opportunity.stage.toLowerCase() !== 'lost');
        if (nonLost.length === 0) {
          return availableFactor('active_opportunities', 'Active opportunities', 15, opportunityHref, 0, 0, 100, 'No records in scope.');
        }
        const active = nonLost.filter((opportunity) => ACTIVE_OPPORTUNITY_STAGES.has(opportunity.stage.toLowerCase())).length;
        const inactive = nonLost.length - active;
        return availableFactor(
          'active_opportunities',
          'Active opportunities',
          15,
          opportunityHref,
          inactive,
          nonLost.length,
          roundedPercentage(active, nonLost.length),
          inactive === 0
            ? 'Every non-lost opportunity is active.'
            : `${inactive} ${inactive === 1 ? 'opportunity is' : 'opportunities are'} outside an active stage.`,
        );
      })();

  return [overdueTasks, uncontactedLeads, contactHealth, activeOpportunities];
}

function buildReadiness(factors: readonly ReadinessFactor[]): FollowUpReadiness {
  const available = factors.filter((factor) => factor.available && factor.score !== null);
  const coverage = { available: available.length, total: 4 as const };
  const totalWeight = available.reduce((total, factor) => total + factor.weight, 0);
  const score = totalWeight === 0
    ? null
    : Math.round(available.reduce((total, factor) => total + (factor.score ?? 0) * factor.weight, 0) / totalWeight);

  if (coverage.available < coverage.total) {
    return {
      score,
      status: 'partial',
      label: `${coverage.available} of ${coverage.total} inputs verified · Partial readiness`,
      coverage,
      factors,
    };
  }

  const status = score !== null && score >= 80 ? 'ready' : score !== null && score >= 60 ? 'watch' : 'at_risk';
  return {
    score,
    status,
    label: `${score}% ${status === 'ready' ? 'ready' : status === 'watch' ? 'readiness · Watch' : 'readiness · At risk'}`,
    coverage,
    factors,
  };
}

function shortcut(
  key: HomeShortcut['key'],
  label: string,
  count: number | null,
  href: string,
): HomeShortcut {
  return {
    key,
    label,
    count,
    evidenceState: count === null ? 'partial_capture' : 'observed_record',
    href,
  };
}

function buildShortcuts(input: CommandHomeInput): readonly HomeShortcut[] {
  const counts = input.smartViewCounts;

  return [
    shortcut('never_contacted', 'Leads Never Contacted', counts?.never_contacted ?? null, CONTACT_SMART_VIEW_URLS.never_contacted),
    shortcut('recently_active', 'Recently Active', counts?.recently_active ?? null, CONTACT_SMART_VIEW_URLS.recently_active),
    shortcut('birthdays', 'Birthdays', counts?.birthdays_this_month ?? null, CONTACT_SMART_VIEW_URLS.birthdays_this_month),
    shortcut('anniversaries', 'Anniversaries', counts?.anniversaries_this_month ?? null, CONTACT_SMART_VIEW_URLS.anniversaries_this_month),
  ];
}

function buildKpis(input: CommandHomeInput, factors: readonly ReadinessFactor[]): readonly HomeKpi[] {
  const factorMap = new Map(factors.map((factor) => [factor.key, factor]));
  const uncontacted = factorMap.get('uncontacted_leads');
  const overdue = factorMap.get('overdue_tasks');
  const contactHealth = factorMap.get('contact_health');
  const openTasks = input.tasks === null ? null : activeTasks(input.tasks).length;
  const activeOpportunities = input.opportunities?.filter((opportunity) =>
    ACTIVE_OPPORTUNITY_STAGES.has(opportunity.stage.toLowerCase()),
  ) ?? null;
  const pipelineValue = activeOpportunities?.reduce(
    (total, opportunity) => total + (opportunity.value_cents ?? 0),
    0,
  ) ?? null;
  const currency = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  });

  return [
    {
      key: 'never_contacted',
      label: 'Never contacted',
      value: uncontacted?.affected === null || uncontacted?.affected === undefined ? 'Unavailable' : String(uncontacted.affected),
      insight: uncontacted?.insight ?? 'Last-contact history is unavailable.',
      href: CONTACT_SMART_VIEW_URLS.never_contacted,
    },
    {
      key: 'open_tasks',
      label: 'Open tasks',
      value: openTasks === null ? 'Unavailable' : String(openTasks),
      insight: overdue?.affected === null || overdue?.affected === undefined
        ? 'Task due dates are unavailable.'
        : `${overdue.affected} overdue`,
      href: '/admin/command/tasks?tab=todo',
    },
    {
      key: 'active_opportunities',
      label: 'Active opportunities',
      value: activeOpportunities === null ? 'Unavailable' : String(activeOpportunities.length),
      insight: activeOpportunities === null || pipelineValue === null
        ? 'Pipeline value is unavailable.'
        : activeOpportunities.length === 0
          ? 'No records in scope.'
          : `${currency.format(pipelineValue / 100)} active pipeline value`,
      href: '/admin/command/opportunities',
    },
    {
      key: 'contactable_profiles',
      label: 'Contactable profiles',
      value: contactHealth?.score === null || contactHealth?.score === undefined
        ? 'Unavailable'
        : input.contacts?.length === 0
          ? '0%'
          : `${contactHealth.score}%`,
      insight: contactHealth?.insight ?? 'Contact profile coverage is unavailable.',
      href: '/admin/command/contacts',
    },
  ];
}

const actionDetails: Record<ReadinessFactorKey, Readonly<{ title: (affected: number) => string; urgency: number }>> = {
  overdue_tasks: {
    title: (affected) => `${affected} overdue ${affected === 1 ? 'task needs' : 'tasks need'} attention first`,
    urgency: 4,
  },
  uncontacted_leads: {
    title: (affected) => `${affected} ${affected === 1 ? 'lead has' : 'leads have'} never been contacted`,
    urgency: 3,
  },
  contact_health: {
    title: (affected) => `${affected} contact ${affected === 1 ? 'profile needs' : 'profiles need'} an email or phone`,
    urgency: 2,
  },
  active_opportunities: {
    title: (affected) => `${affected} ${affected === 1 ? 'opportunity needs' : 'opportunities need'} an active stage`,
    urgency: 1,
  },
};

function buildNextActions(factors: readonly ReadinessFactor[]): readonly HomeNextAction[] {
  return factors
    .filter((factor): factor is ReadinessFactor & { affected: number } => factor.available && factor.affected !== null && factor.affected > 0)
    .map((factor) => ({
      kind: factor.key,
      title: actionDetails[factor.key].title(factor.affected),
      affected: factor.affected,
      urgency: actionDetails[factor.key].urgency,
      href: factor.href,
    }))
    .sort((left, right) =>
      right.affected - left.affected
      || right.urgency - left.urgency
      || left.kind.localeCompare(right.kind),
    );
}

function sortTasks(tasks: readonly Task[] | null): readonly Task[] | null {
  if (tasks === null) return null;
  return activeTasks(tasks).sort((left, right) => {
    if (left.due_at === null && right.due_at === null) return left.id - right.id;
    if (left.due_at === null) return 1;
    if (right.due_at === null) return -1;
    return Date.parse(left.due_at) - Date.parse(right.due_at) || left.id - right.id;
  });
}

function recentContacts(contacts: readonly Contact[] | null): readonly Contact[] {
  if (
    contacts === null
    || !contacts.every((contact) => Object.hasOwn(contact, 'recently_active_at'))
  ) return [];
  return contacts
    .filter((contact) => contact.recently_active_at && Number.isFinite(Date.parse(contact.recently_active_at)))
    .sort((left, right) => Date.parse(right.recently_active_at ?? '') - Date.parse(left.recently_active_at ?? ''));
}

export function buildCommandHomeModel(input: CommandHomeInput, now = new Date()): CommandHomeModel {
  const factors = buildFactors(input, now);
  return {
    readiness: buildReadiness(factors),
    shortcuts: buildShortcuts(input),
    kpis: buildKpis(input, factors),
    nextActions: buildNextActions(factors),
    tasks: sortTasks(input.tasks),
    recentContacts: recentContacts(input.contacts),
    celebrations: input.celebrations,
    goals: input.goals,
    briefing: input.briefing,
    bookingsState: 'partial_capture',
    regionErrors: input.errors,
  };
}

function paginationFailure(): never {
  throw new CommandDecodeError('contacts', 'stable complete pagination');
}

export async function loadAllContacts(
  api: Pick<CommandHomeApi, 'contactDirectory'>,
  signal?: AbortSignal,
): Promise<readonly ContactDirectoryRow[]> {
  const rows: ContactDirectoryRow[] = [];
  const ids = new Set<number>();
  let expected: Readonly<{
    total: number;
    page_count: number;
    page_size: number;
    sort: ContactDirectoryPage['sort'];
    direction: ContactDirectoryPage['direction'];
  }> | null = null;
  let requestedPage = 1;

  while (true) {
    const page = await api.contactDirectory({
      smart_view: 'all',
      sort: 'name',
      direction: 'asc',
      page: requestedPage,
      page_size: 100,
    }, { signal });
    if (page.page !== requestedPage) paginationFailure();
    if (expected === null) {
      expected = {
        total: page.total,
        page_count: page.page_count,
        page_size: page.page_size,
        sort: page.sort,
        direction: page.direction,
      };
      if (
        expected.page_size !== 100
        || expected.sort !== 'name'
        || expected.direction !== 'asc'
        || (expected.total === 0
          ? expected.page_count !== 0 || page.rows.length !== 0
          : expected.page_count < 1)
      ) paginationFailure();
    } else if (
      page.total !== expected.total
      || page.page_count !== expected.page_count
      || page.page_size !== expected.page_size
      || page.sort !== expected.sort
      || page.direction !== expected.direction
    ) {
      paginationFailure();
    }

    if (requestedPage > 1 && page.rows.length === 0) paginationFailure();
    for (const row of page.rows) {
      if (ids.has(row.id)) paginationFailure();
      ids.add(row.id);
      rows.push(row);
    }
    if (rows.length > expected.total) paginationFailure();
    if (requestedPage >= expected.page_count) break;
    requestedPage += 1;
  }

  if (expected === null || rows.length !== expected.total) paginationFailure();
  return rows;
}

const HOME_SMART_VIEWS = [
  'never_contacted',
  'recently_active',
  'birthdays_this_month',
  'anniversaries_this_month',
] as const;

export async function loadHomeSmartViewCounts(
  api: Pick<CommandHomeApi, 'contactDirectory'>,
  signal?: AbortSignal,
): Promise<HomeSmartViewCounts> {
  const pages = await Promise.all(HOME_SMART_VIEWS.map((smart_view) =>
    api.contactDirectory({
      smart_view,
      sort: 'name',
      direction: 'asc',
      page: 1,
      page_size: 1,
    }, { signal })));
  return {
    never_contacted: pages[0].total,
    recently_active: pages[1].total,
    birthdays_this_month: pages[2].total,
    anniversaries_this_month: pages[3].total,
  };
}

function adaptCelebrationRows(
  rows: ContactCelebrations['birthdays'] | ContactCelebrations['anniversaries'],
  expectedKind: HomeCelebrationRow['kind'],
): readonly HomeCelebrationRow[] {
  return rows.map((row) => {
    const validYear = row.year_quality === 'verified'
      ? row.year !== null
      : row.year === null;
    if (row.kind !== expectedKind || !validYear) {
      throw new CommandDecodeError('celebrations', 'consistent celebration rows');
    }
    return {
      contactId: row.contact_id,
      displayName: row.display_name,
      kind: row.kind,
      month: row.month,
      day: row.day,
      year: row.year,
      yearQuality: row.year_quality,
      origin: row.origin,
    };
  });
}

export function adaptHomeCelebrations(value: ContactCelebrations): HomeCelebrations {
  return {
    birthdays: adaptCelebrationRows(value.birthdays, 'birthday'),
    anniversaries: adaptCelebrationRows(value.anniversaries, 'anniversary'),
  };
}

function directoryContact(row: ContactDirectoryRow): Contact {
  return {
    id: row.id,
    first_name: row.first_name,
    last_name: row.last_name,
    email: row.primary_email,
    phone: row.primary_phone,
    stage: row.stage,
    last_contacted_at: row.last_contacted_at,
    recently_active_at: row.last_interaction_at,
    health_score: row.health_score,
  };
}

async function loadHomeContacts(
  api: Pick<CommandHomeApi, 'contactDirectory'>,
  signal?: AbortSignal,
): Promise<Readonly<{
  contacts: readonly Contact[];
  smartViewCounts: HomeSmartViewCounts;
}>> {
  const [directoryRows, smartViewCounts] = await Promise.all([
    loadAllContacts(api, signal),
    loadHomeSmartViewCounts(api, signal),
  ]);
  const contacts = directoryRows.map(directoryContact);
  const leadCount = contacts.filter((contact) => contact.stage.trim().toLowerCase() === 'lead').length;
  if (smartViewCounts.never_contacted > leadCount) {
    throw new CommandDecodeError('contacts', 'consistent SmartView totals');
  }
  return { contacts, smartViewCounts };
}

function abortReason(signal: AbortSignal): unknown {
  return signal.reason === undefined
    ? new DOMException('The operation was aborted.', 'AbortError')
    : signal.reason;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unavailable';
}

export async function loadCommandHome(
  api: CommandHomeApi = commandApi,
  now = new Date(),
  signal?: AbortSignal,
): Promise<CommandHomeModel> {
  if (signal?.aborted) throw abortReason(signal);
  const requests = {
    overview: api.overview({ signal }),
    contacts: loadHomeContacts(api, signal),
    tasks: api.tasks({}, { signal }).then((tasks) => {
      activeTasks(tasks);
      return tasks;
    }),
    opportunities: api.opportunities({ signal }),
    celebrations: api
      .celebrations(now.getMonth() + 1, { signal })
      .then(adaptHomeCelebrations),
    goals: api.goals({ signal }),
    briefing: api.aiBriefing({ signal }),
  } satisfies Record<CommandHomeRegion, Promise<unknown>>;
  const regions = Object.keys(requests) as CommandHomeRegion[];
  const results = await Promise.allSettled(regions.map((region) => requests[region]));
  const values: Partial<Record<CommandHomeRegion, unknown>> = {};
  const errors: Partial<Record<CommandHomeRegion, string>> = {};

  results.forEach((result, index) => {
    const region = regions[index];
    if (result.status === 'fulfilled') values[region] = result.value;
    else errors[region] = errorMessage(result.reason);
  });

  if (signal?.aborted) throw abortReason(signal);

  if (Object.keys(errors).length === regions.length) {
    throw new Error('Command Home could not load any region.');
  }

  const contactValues = values.contacts as Awaited<ReturnType<typeof loadHomeContacts>> | undefined;
  return buildCommandHomeModel({
    overview: (values.overview as Overview | undefined) ?? null,
    contacts: contactValues?.contacts ?? null,
    smartViewCounts: contactValues?.smartViewCounts ?? null,
    tasks: (values.tasks as Task[] | undefined) ?? null,
    opportunities: (values.opportunities as Opportunity[] | undefined) ?? null,
    celebrations: (values.celebrations as HomeCelebrations | undefined) ?? null,
    goals: (values.goals as Goal[] | undefined) ?? null,
    briefing: (values.briefing as AiBriefing | undefined) ?? null,
    errors,
  }, now);
}
