import {
  Archive,
  CardsThree,
  ChartBar,
  CheckCircle,
  ClipboardText,
  FileText,
  Handshake,
  House,
  MagnifyingGlass,
  MapPin,
  Megaphone,
  Sparkle,
  UploadSimple,
  Users,
} from '@phosphor-icons/react';
import type { Icon } from '@phosphor-icons/react';

export type CommandNavigationGroup = 'core' | 'growth' | 'records' | 'tools';

export type CommandDestination = Readonly<{
  label: string;
  shortLabel: string;
  href: string;
  group: CommandNavigationGroup;
  icon: Icon;
  createLabel?: string;
  createHref?: string;
  searchTerms: readonly string[];
}>;

export const commandNavigation: readonly CommandDestination[] = Object.freeze([
  {
    label: 'Home',
    shortLabel: 'Home',
    href: '/admin/command',
    group: 'core',
    icon: House,
    createLabel: 'Create task',
    createHref: '/admin/command?create=task',
    searchTerms: ['dashboard', 'overview', 'briefing'],
  },
  {
    label: 'Contacts',
    shortLabel: 'Contacts',
    href: '/admin/command/contacts',
    group: 'core',
    icon: Users,
    searchTerms: ['people', 'leads', 'database'],
  },
  {
    label: 'Tasks',
    shortLabel: 'Tasks',
    href: '/admin/command/tasks',
    group: 'core',
    icon: CheckCircle,
    searchTerms: ['todo', 'completed', 'archived'],
  },
  {
    label: 'Task review',
    shortLabel: 'Review',
    href: '/admin/command/task-suggestions',
    group: 'core',
    icon: ClipboardText,
    searchTerms: ['Sydney', 'Gmail', 'approval', 'suggestions'],
  },
  {
    label: 'Client cards',
    shortLabel: 'Cards',
    href: '/admin/command/cards',
    group: 'core',
    icon: CardsThree,
    createLabel: 'New card campaign',
    createHref: '/admin/command/cards?create=campaign',
    searchTerms: ['birthdays', 'anniversaries', 'mail', 'Send Out Cards', 'Sydney'],
  },
  {
    label: 'Smart Plans',
    shortLabel: 'Plans',
    href: '/admin/command/smart-plans',
    group: 'core',
    icon: Sparkle,
    searchTerms: ['automation', 'enrollments', 'steps'],
  },
  {
    label: 'Opportunities',
    shortLabel: 'Pipeline',
    href: '/admin/command/opportunities',
    group: 'core',
    icon: ChartBar,
    searchTerms: ['deals', 'pipeline', 'offers'],
  },
  {
    label: 'Referrals',
    shortLabel: 'Referrals',
    href: '/admin/command/referrals',
    group: 'growth',
    icon: Handshake,
    searchTerms: ['network', 'invites', 'agents'],
  },
  {
    label: 'Marketing',
    shortLabel: 'Marketing',
    href: '/admin/command/marketing',
    group: 'growth',
    icon: Megaphone,
    searchTerms: ['campaigns', 'designs', 'direct mail'],
  },
  {
    label: 'Agreements',
    shortLabel: 'Agreements',
    href: '/admin/command/agreements',
    group: 'records',
    icon: FileText,
    searchTerms: ['documents', 'templates', 'files'],
  },
  {
    label: 'Reports',
    shortLabel: 'Reports',
    href: '/admin/command/reports',
    group: 'growth',
    icon: ChartBar,
    searchTerms: ['analytics', 'favorites', 'metrics'],
  },
  {
    label: 'Listings & Map',
    shortLabel: 'Listings',
    href: '/admin/command/listings',
    group: 'growth',
    icon: MapPin,
    searchTerms: ['properties', 'search', 'map'],
  },
  {
    label: 'Websites',
    shortLabel: 'Websites',
    href: '/admin/command/websites',
    group: 'growth',
    icon: House,
    searchTerms: ['pages', 'content', 'funnels'],
  },
  {
    label: 'Recovered archive',
    shortLabel: 'Archive',
    href: '/admin/command/archive',
    group: 'records',
    icon: Archive,
    searchTerms: ['source', 'artifacts', 'evidence'],
  },
  {
    label: 'Sweeney AI',
    shortLabel: 'AI',
    href: '/admin/command/ai',
    group: 'tools',
    icon: Sparkle,
    searchTerms: ['briefing', 'assistant', 'insights'],
  },
  {
    label: 'Import contacts',
    shortLabel: 'Import',
    href: '/admin/command/import',
    group: 'tools',
    icon: UploadSimple,
    searchTerms: ['upload', 'csv', 'contacts'],
  },
  {
    label: 'Saved Searches',
    shortLabel: 'Searches',
    href: '/admin/command/saved-searches',
    group: 'tools',
    icon: MagnifyingGlass,
    searchTerms: ['filters', 'views', 'queries'],
  },
]);

export function isCommandDestinationActive(pathname: string, href: string): boolean {
  return href === '/admin/command'
    ? pathname === href
    : pathname === href || pathname.startsWith(`${href}/`);
}

export function findCommandDestination(pathname: string): CommandDestination | undefined {
  return commandNavigation.find((item) => isCommandDestinationActive(pathname, item.href));
}
