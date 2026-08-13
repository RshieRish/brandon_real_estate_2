export type CommandReferenceQuality = 'valid' | 'limitation';

export type SourceBrandMask = Readonly<{
  x: number;
  y: number;
  width: number;
  height: number;
  reason: 'source vendor mark' | 'source vendor utilities' | 'source account identity';
}>;

export type CommandSourceReference = Readonly<{
  filename: string;
  route: string;
  width: number;
  height: number;
  quality: CommandReferenceQuality;
  observedState: string;
  brandMasks: readonly SourceBrandMask[];
}>;

const shellBrandMasks: readonly SourceBrandMask[] = Object.freeze([
  { x: 0, y: 0, width: 80, height: 64, reason: 'source vendor mark' },
  { x: 1180, y: 0, width: 180, height: 64, reason: 'source vendor utilities' },
  { x: 1430, y: 0, width: 290, height: 64, reason: 'source account identity' },
]);

function rendered(
  filename: string,
  route: string,
  width = 1800,
  height = 982,
  observedState = 'authenticated rendered module view',
): CommandSourceReference {
  return { filename, route, width, height, quality: 'valid', observedState, brandMasks: shellBrandMasks };
}

function limitation(
  filename: string,
  route: string,
  width = 1800,
  height = 982,
  observedState = 'blank, incomplete, retry, or error capture; never a visual target',
): CommandSourceReference {
  return { filename, route, width, height, quality: 'limitation', observedState, brandMasks: shellBrandMasks };
}

export const commandSourceReferences: readonly CommandSourceReference[] = Object.freeze([
  rendered('command-home-live.png', '/admin/command', 1800, 2249, 'authenticated full Home with persistent shell'),
  rendered('contacts-live-current.png', '/admin/command/contacts', 1800, 982, 'contacts list with toolbar, rows, and pagination'),
  rendered('tasks-to-do-live.png', '/admin/command/tasks?tab=todo', 1800, 982, 'To Do tasks with filters and dense rows'),
  rendered('smartplans-live-current.png', '/admin/command/smart-plans', 1800, 982, 'Smart Plans list with notice, tabs, and evidence count'),
  rendered('opportunities-live-current.png', '/admin/command/opportunities', 1800, 982, 'opportunity phase board and module tabs'),
  rendered('marketing-dashboard-live.png', '/admin/command/marketing', 1800, 982, 'marketing dashboard with nested module tabs'),
  rendered('referrals-dashboard-live.png', '/admin/command/referrals', 1800, 982, 'referrals dashboard with rendered network state'),
  rendered('contact-adam-pappastergion-live-details.png', '/admin/command/contacts/:id', 1793, 1166, 'split contact detail canvas with sticky navigation'),
  limitation('top-home.png', '/admin/command', 1800, 982, 'top-only shell capture without valid Home content'),
  limitation('contacts-list.png', '/admin/command/contacts', 1800, 982, 'incomplete contacts capture'),
  limitation('opportunities-board.png', '/admin/command/opportunities', 1800, 982, 'incomplete opportunity board capture'),
  limitation('smartplans-my.png', '/admin/command/smart-plans', 1800, 982, 'incomplete Smart Plans capture'),
  limitation('referrals-dashboard-error-state.png', '/admin/command/referrals', 1800, 982, 'rendered referral error state'),
  limitation('contacts-live-list-retry.png', '/admin/command/contacts', 1793, 1063, 'retry capture'),
  limitation('listings-live-retry.png', '/admin/command/listings', 1800, 982, 'retry capture'),
  limitation('websites-live-retry.png', '/admin/command/websites', 1800, 982, 'retry capture'),
]);
