import {
  commandApi,
  type AiBriefing,
  type Celebrations,
  type Contact,
  type Goal,
  type Opportunity,
  type Overview,
  type Task,
} from './api';

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
  tasks: readonly Task[] | null;
  opportunities: readonly Opportunity[] | null;
  celebrations: Celebrations | null;
  goals: readonly Goal[] | null;
  briefing: AiBriefing | null;
  errors: Readonly<Partial<Record<CommandHomeRegion, string>>>;
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
  tasks: readonly Task[];
  recentContacts: readonly Contact[];
  celebrations: Celebrations | null;
  goals: readonly Goal[];
  briefing: AiBriefing | null;
  bookingsState: 'partial_capture';
  regionErrors: Readonly<Partial<Record<CommandHomeRegion, string>>>;
}>;

export type CommandHomeApi = Readonly<{
  overview: () => Promise<Overview>;
  contacts: (limit: number, offset: number) => Promise<Contact[]>;
  tasks: () => Promise<Task[]>;
  opportunities: () => Promise<Opportunity[]>;
  celebrations: (month: number) => Promise<Celebrations>;
  goals: () => Promise<Goal[]>;
  aiBriefing: () => Promise<AiBriefing>;
}>;

const ACTIVE_TASK_STATUSES = new Set(['open', 'in_progress']);
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
  return tasks.filter((task) => ACTIVE_TASK_STATUSES.has(task.status.toLowerCase()));
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

  const leadHref = '/admin/command/contacts?filter=never_contacted';
  const leadContacts = input.contacts?.filter((contact) => contact.stage.toLowerCase() === 'lead') ?? null;
  const hasLastContactCoverage = leadContacts !== null
    && leadContacts.every((contact) => Object.hasOwn(contact, 'last_contacted_at'));
  const uncontactedLeads = leadContacts === null || !hasLastContactCoverage
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
          const neverContacted = leadContacts.filter((contact) => contact.last_contacted_at === null).length;
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
  const leads = input.contacts?.filter((contact) => contact.stage.toLowerCase() === 'lead') ?? null;
  const neverContacted = leads !== null && leads.every((contact) => Object.hasOwn(contact, 'last_contacted_at'))
    ? leads.filter((contact) => contact.last_contacted_at === null).length
    : null;
  const recentlyActive = input.contacts !== null
    && input.contacts.every((contact) => Object.hasOwn(contact, 'recently_active_at'))
    ? input.contacts.filter((contact) => Boolean(contact.recently_active_at)).length
    : null;

  return [
    shortcut('never_contacted', 'Leads Never Contacted', neverContacted, '/admin/command/contacts?filter=never_contacted'),
    shortcut('recently_active', 'Recently Active', recentlyActive, '/admin/command/contacts?sort=recent_activity'),
    shortcut('birthdays', 'Birthdays', input.celebrations?.birthdays.length ?? null, '/admin/command/contacts?filter=birthdays'),
    shortcut('anniversaries', 'Anniversaries', input.celebrations?.anniversaries.length ?? null, '/admin/command/contacts?filter=anniversaries'),
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
      href: '/admin/command/contacts?filter=never_contacted',
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

function sortTasks(tasks: readonly Task[] | null): readonly Task[] {
  if (tasks === null) return [];
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
    goals: input.goals ?? [],
    briefing: input.briefing,
    bookingsState: 'partial_capture',
    regionErrors: input.errors,
  };
}

async function loadAllContacts(api: CommandHomeApi): Promise<Contact[]> {
  const contacts: Contact[] = [];
  for (let offset = 0; ; offset += 100) {
    const page = await api.contacts(100, offset);
    contacts.push(...page);
    if (page.length < 100) return contacts;
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unavailable';
}

export async function loadCommandHome(
  api: CommandHomeApi = commandApi,
  now = new Date(),
): Promise<CommandHomeModel> {
  const requests = {
    overview: api.overview(),
    contacts: loadAllContacts(api),
    tasks: api.tasks(),
    opportunities: api.opportunities(),
    celebrations: api.celebrations(now.getMonth() + 1),
    goals: api.goals(),
    briefing: api.aiBriefing(),
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

  return buildCommandHomeModel({
    overview: (values.overview as Overview | undefined) ?? null,
    contacts: (values.contacts as Contact[] | undefined) ?? null,
    tasks: (values.tasks as Task[] | undefined) ?? null,
    opportunities: (values.opportunities as Opportunity[] | undefined) ?? null,
    celebrations: (values.celebrations as Celebrations | undefined) ?? null,
    goals: (values.goals as Goal[] | undefined) ?? null,
    briefing: (values.briefing as AiBriefing | undefined) ?? null,
    errors,
  }, now);
}
