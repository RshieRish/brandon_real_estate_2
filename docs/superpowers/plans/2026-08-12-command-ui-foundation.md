# Command UI Foundation and Home Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current dark, card-based `/admin/command` wrapper with a Sold With Sweeney branded, persistent Command-parity shell and a truthful operational Home that answers “What needs Brandon’s attention next?” across desktop and mobile.

**Architecture:** A single client-side `CommandShell` owns the fixed rail, utility header, global search, contextual actions, mobile navigation, focus management, and dense white work canvas for every `/admin/command/*` route. Reusable typed primitives own module headers, tabs, tables, overlays, evidence states, and toasts; Home composes existing authenticated Command endpoints through a pure model builder so missing archive fields become explicit partial states rather than inferred records.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4, scoped CSS, Phosphor icons, Vitest 4, jsdom, Testing Library, Playwright, axe-core.

---

## Scope boundary

This plan implements only the shared frontend foundation and Home. It does not change backend models, migrations, parsers, reconciliation code, or domain-specific record interiors. Contacts, Tasks, SmartPlans, Opportunities, Listings, Marketing, Referrals, Reports, Websites, Agreements, Archive, Import, Saved Searches, and AI keep their existing business behavior while they inherit the new shell; their full list/detail parity is delivered by their later domain plans.

The implementation must remain deployable against the current API. Home may calculate only from fields returned today. When a readiness factor requires a field that is absent from every returned record, the factor is marked unavailable, the overall metric is labeled partial, and the interface states how many inputs were verified. No default value may convert an unavailable factor into a favorable score.

No source screenshot, Keller Williams asset, DocuSign asset, vendor logo, or vendor copy is copied into the application bundle. The authorized screenshots remain local QA references only.

## Visual contract

Use these valid local references during implementation:

- `kw_command_ui_screenshots/command-home-live.png` — valid shell and full Home density reference, 1800×2249; compare its first 982px at the standard desktop viewport and its full-page structure separately.
- `kw_command_ui_screenshots/contacts-live-current.png` — valid rail, header, module toolbar, dense table, and pagination reference, 1800×982.
- `kw_command_ui_screenshots/tasks-to-do-live.png` — valid tabs, filters, table rows, date chips, and pagination reference, 1800×982.
- `kw_command_ui_screenshots/smartplans-live-current.png` — valid module header, notice, top tabs, dense table, and evidence-count reference, 1800×982.
- `kw_command_ui_screenshots/opportunities-live-current.png` — valid module tabs and phase geometry reference, 1800×982.
- `kw_command_ui_screenshots/marketing-dashboard-live.png` and `referrals-dashboard-live.png` — valid nested module tabs and dense dashboard references, 1800×982.
- `kw_command_ui_screenshots/contact-adam-pappastergion-live-details.png` — valid split-detail canvas and sticky navigation reference, 1793×1166.

Do not use `top-home.png`, `contacts-list.png`, `opportunities-board.png`, `smartplans-my.png`, any `*-retry.png`, or a blank/error/shell image as a successful target. They are limitation evidence.

Exact shell geometry at desktop:

- fixed icon rail: 80px wide, full viewport height, black `#0a0a0a`;
- fixed utility header: 64px high, begins at x=80px, black/graphite;
- rail expansion: 248px overlay on demand, without shifting the work canvas;
- work canvas: starts at x=80px and y=64px, fills the remaining viewport, warm white `#f6f5f2` with white surfaces;
- module content: no centered `max-w-*` island; content uses the full available width with 24px desktop gutters and 16px mobile gutters;
- default table rows: 48–56px, with column headings and toolbars remaining visually denser than marketing pages;
- desktop breakpoint: 1024px; below it the rail is removed and a 56px mobile header opens an off-canvas drawer.

SWS substitutions are intentional: black/gold replaces the source accent palette, the SWS smiley replaces the vendor logo, Montserrat remains the product face, and account/vendor-specific header content is replaced by Brandon’s internal workspace controls.

## Home dashboard gates

- **One job:** answer “What needs Brandon’s attention next?”
- **Signature metric:** `Follow-Up Readiness`.
- **Distinctive hero:** one horizontal readiness rail with four labeled factors and a ranked next-action queue; do not use a generic donut.
- **Insight:** the hero states the highest-risk factor and links to the exact filtered queue that addresses it.
- **Subtraction:** reduce the source Home’s ten-plus co-equal widgets to one hero plus four KPI tiles above the fold. Goals, task queue, celebrations, recent leads, bookings, briefing, source placeholders, and data health appear below or behind “View all.”
- **Pitch test:** one desktop screenshot must communicate what the workspace is, current readiness, and the first action Brandon should take.
- **Screenshot reason:** the screen is worth capturing because the readiness rail turns scattered CRM obligations into one auditable priority decision.

## File responsibility map

### Testing foundation

- Modify `frontend/package.json`: add component/E2E test commands and test dependencies.
- Modify `frontend/package-lock.json`: lock resolved test dependencies.
- Modify `frontend/vitest.config.ts`: run `.test.ts` and `.test.tsx` in jsdom with a setup file.
- Create `frontend/src/test/setup.ts`: install jest-dom matchers and cleanup.
- Create `frontend/src/test/testing-library.test.tsx`: prove the component harness works.
- Create `frontend/playwright.config.ts`: desktop/mobile/a11y/visual projects and managed Next server.
- Create `frontend/e2e/fixtures/command.ts`: deterministic auth, API routes, fixed time, and console-error gate.
- Create `frontend/e2e/fixtures/command-home.json`: realistic, non-production test data.
- Modify `.gitignore`: ignore Playwright reports, traces, test results, local captures, and auth state.

### Shell and shared UI

- Create `frontend/src/components/command/shell/commandNavigation.ts`: the sole route/navigation/action registry.
- Create `frontend/src/components/command/shell/CommandShell.tsx`: shell state and composition.
- Create `frontend/src/components/command/shell/CommandRail.tsx`: desktop icon rail and expanded-label overlay.
- Create `frontend/src/components/command/shell/CommandUtilityHeader.tsx`: search, contextual create, notifications, help, and account controls.
- Create `frontend/src/components/command/shell/CommandMobileNavigation.tsx`: modal off-canvas navigation.
- Create `frontend/src/components/command/shell/CommandGlobalSearch.tsx`: Command/Ctrl+K navigation search.
- Create `frontend/src/components/command/shell/useFocusContainment.ts`: focus trap, Escape close, scroll lock, and focus restoration.
- Create `frontend/src/app/admin/command/command-shell.css`: scoped SWS tokens, fixed geometry, dense light canvas, responsive behavior, and reduced motion.
- Modify `frontend/src/app/admin/command/layout.tsx`: render the shell for Home and every nested route.
- Create `frontend/src/components/command/ui/CommandModuleHeader.tsx`: breadcrumbs, title, tabs, action slot, and toolbar slot.
- Create `frontend/src/components/command/ui/CommandTabs.tsx`: ARIA tabs with roving keyboard focus.
- Create `frontend/src/components/command/ui/CommandDataTable.tsx`: typed table, sort state, row selection, bulk-action slot, and contained horizontal overflow.
- Create `frontend/src/components/command/ui/CommandOverlay.tsx`: shared dialog/drawer semantics and focus behavior.
- Create `frontend/src/components/command/ui/CommandStatePanel.tsx`: loading, first-run, empty, evidence-only, partial-capture, error, and retry states.
- Create `frontend/src/components/command/ui/CommandEvidencePanel.tsx`: observed/rendered/aggregate evidence and source-artifact links.
- Create `frontend/src/components/command/ui/CommandToastProvider.tsx`: polite confirmation and assertive error regions.

### Home

- Create `frontend/src/lib/command/home.ts`: typed Home loader, pure readiness calculation, queue ranking, and data-coverage rules.
- Create `frontend/src/lib/command/home.test.ts`: deterministic model tests.
- Create `frontend/src/test/fixtures/commandHome.ts`: shared synthetic Home inputs/models for unit and component tests.
- Modify `frontend/src/lib/command/api.ts`: add optional factual fields used by readiness without changing existing calls.
- Modify `frontend/src/lib/command/api.test.ts`: prove current authenticated calls remain intact.
- Create `frontend/src/components/command/home/CommandHome.tsx`: complete Home composition.
- Create `frontend/src/components/command/home/FollowUpReadinessHero.tsx`: signature metric and ranked action rail.
- Create `frontend/src/components/command/home/HomeShortcutStrip.tsx`: Leads Never Contacted, Recently Active, Birthdays, Anniversaries.
- Create `frontend/src/components/command/home/HomeKpiStrip.tsx`: exactly four secondary metrics.
- Create `frontend/src/components/command/home/HomeTaskQueue.tsx`: personal/team/all task tabs and quick-create entry.
- Create `frontend/src/components/command/home/HomeGoals.tsx`: concise goal progress and existing mutation affordance.
- Create `frontend/src/components/command/home/HomeContextPanels.tsx`: recent leads, celebrations, bookings, briefing, health, and captured-placeholder disclosure.
- Create `frontend/src/components/command/home/CommandHome.test.tsx`: rendering, state, accessibility, and interaction coverage.
- Replace `frontend/src/app/admin/command/page.tsx`: route-only Home wrapper.

### Browser and visual QA

- Create `frontend/e2e/command-shell.spec.ts`: persistent-shell and keyboard journeys.
- Create `frontend/e2e/command-home.spec.ts`: Home priority, error/retry, and mobile journeys.
- Create `frontend/e2e/command-mobile.spec.ts`: mobile drawer, focus, target-size, and overflow journeys.
- Create `frontend/e2e/command-accessibility.spec.ts`: axe, keyboard, focus, forced-colors, and reduced-motion gates.
- Create `frontend/e2e/command-visual.spec.ts`: stable local SWS snapshots at 1800×982, 1024×768, and 390×844.
- Create `frontend/e2e/visual/command-reference-manifest.ts`: valid/limitation source filenames, dimensions, and source-only brand-mask rectangles.
- Create `frontend/src/test/command-reference-manifest.test.ts`: prevent blank/error references from becoming targets.
- Create `frontend/design-qa.md`: same-viewport source/current comparison report, written only after inspection.

---

### Task 1: Install a real component-test runtime

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vitest.config.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/test/testing-library.test.tsx`

- [ ] **Step 1: Write the failing jsdom smoke test**

```tsx
import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

function Probe() {
  const [open, setOpen] = useState(false);
  return <button type="button" aria-expanded={open} onClick={() => setOpen(true)}>Open workspace</button>;
}

describe('Testing Library runtime', () => {
  it('renders and operates a React client component', async () => {
    const user = userEvent.setup();
    render(<Probe />);
    const button = screen.getByRole('button', { name: 'Open workspace' });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    await user.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
  });
});
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `cd frontend && npm test -- src/test/testing-library.test.tsx`

Expected: FAIL because `@testing-library/react`, `@testing-library/user-event`, jest-dom, and jsdom are not installed/configured.

- [ ] **Step 3: Install the component-test dependencies and add scripts**

Run:

```bash
cd frontend
npm install --save-dev @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom
```

Set the scripts block to retain existing commands and add the explicit component selector:

```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:components": "vitest run --environment jsdom"
  }
}
```

- [ ] **Step 4: Configure Vitest and global cleanup**

Replace `frontend/vitest.config.ts` with:

```ts
import path from 'node:path';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
    restoreMocks: true,
    clearMocks: true,
  },
});
```

Create `frontend/src/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});
```

- [ ] **Step 5: Run the smoke test and the entire pre-existing unit suite**

Run:

```bash
cd frontend
npm test -- src/test/testing-library.test.tsx
npm test
npm run typecheck
```

Expected: PASS with zero regressions in the existing source-inspection and API-client tests.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/src/test/setup.ts frontend/src/test/testing-library.test.tsx
git commit -m "test: add Command component test runtime"
```

### Task 2: Lock the route registry and SWS visual tokens

**Files:**
- Create: `frontend/src/components/command/shell/commandNavigation.ts`
- Create: `frontend/src/components/command/shell/commandNavigation.test.ts`
- Create: `frontend/src/app/admin/command/command-shell.css`

- [ ] **Step 1: Write failing registry tests**

```ts
import { describe, expect, it } from 'vitest';
import { commandNavigation, findCommandDestination, isCommandDestinationActive } from './commandNavigation';

describe('Command navigation registry', () => {
  it('contains every existing Command destination once', () => {
    expect(commandNavigation.map((item) => item.href)).toEqual([
      '/admin/command',
      '/admin/command/contacts',
      '/admin/command/tasks',
      '/admin/command/smart-plans',
      '/admin/command/opportunities',
      '/admin/command/referrals',
      '/admin/command/marketing',
      '/admin/command/agreements',
      '/admin/command/reports',
      '/admin/command/listings',
      '/admin/command/websites',
      '/admin/command/archive',
      '/admin/command/ai',
      '/admin/command/import',
      '/admin/command/saved-searches',
    ]);
  });

  it('matches Home exactly and nested module routes by prefix', () => {
    expect(isCommandDestinationActive('/admin/command', '/admin/command')).toBe(true);
    expect(isCommandDestinationActive('/admin/command/contacts', '/admin/command')).toBe(false);
    expect(isCommandDestinationActive('/admin/command/contacts/42', '/admin/command/contacts')).toBe(true);
    expect(findCommandDestination('/admin/command/tasks/9')?.label).toBe('Tasks');
  });
});
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `cd frontend && npm test -- src/components/command/shell/commandNavigation.test.ts`

Expected: FAIL because the registry module does not exist.

- [ ] **Step 3: Implement the immutable registry**

Define this public contract and populate it in the exact tested order:

```ts
import {
  Archive,
  ChartBar,
  CheckCircle,
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
  { label: 'Home', shortLabel: 'Home', href: '/admin/command', group: 'core', icon: House, createLabel: 'Create task', createHref: '/admin/command?create=task', searchTerms: ['dashboard', 'overview', 'briefing'] },
  { label: 'Contacts', shortLabel: 'Contacts', href: '/admin/command/contacts', group: 'core', icon: Users, searchTerms: ['people', 'leads', 'database'] },
  { label: 'Tasks', shortLabel: 'Tasks', href: '/admin/command/tasks', group: 'core', icon: CheckCircle, searchTerms: ['todo', 'completed', 'archived'] },
  { label: 'Smart Plans', shortLabel: 'Plans', href: '/admin/command/smart-plans', group: 'core', icon: Sparkle, searchTerms: ['automation', 'enrollments', 'steps'] },
  { label: 'Opportunities', shortLabel: 'Pipeline', href: '/admin/command/opportunities', group: 'core', icon: ChartBar, searchTerms: ['deals', 'pipeline', 'offers'] },
  { label: 'Referrals', shortLabel: 'Referrals', href: '/admin/command/referrals', group: 'growth', icon: Handshake, searchTerms: ['network', 'invites', 'agents'] },
  { label: 'Marketing', shortLabel: 'Marketing', href: '/admin/command/marketing', group: 'growth', icon: Megaphone, searchTerms: ['campaigns', 'designs', 'direct mail'] },
  { label: 'Agreements', shortLabel: 'Agreements', href: '/admin/command/agreements', group: 'records', icon: FileText, searchTerms: ['documents', 'templates', 'files'] },
  { label: 'Reports', shortLabel: 'Reports', href: '/admin/command/reports', group: 'growth', icon: ChartBar, searchTerms: ['analytics', 'favorites', 'metrics'] },
  { label: 'Listings & Map', shortLabel: 'Listings', href: '/admin/command/listings', group: 'growth', icon: MapPin, searchTerms: ['properties', 'search', 'map'] },
  { label: 'Websites', shortLabel: 'Websites', href: '/admin/command/websites', group: 'growth', icon: House, searchTerms: ['pages', 'content', 'funnels'] },
  { label: 'Recovered archive', shortLabel: 'Archive', href: '/admin/command/archive', group: 'records', icon: Archive, searchTerms: ['source', 'artifacts', 'evidence'] },
  { label: 'Sweeney AI', shortLabel: 'AI', href: '/admin/command/ai', group: 'tools', icon: Sparkle, searchTerms: ['briefing', 'assistant', 'insights'] },
  { label: 'Import contacts', shortLabel: 'Import', href: '/admin/command/import', group: 'tools', icon: UploadSimple, searchTerms: ['upload', 'csv', 'contacts'] },
  { label: 'Saved Searches', shortLabel: 'Searches', href: '/admin/command/saved-searches', group: 'tools', icon: MagnifyingGlass, searchTerms: ['filters', 'views', 'queries'] },
]);

export function isCommandDestinationActive(pathname: string, href: string): boolean {
  return href === '/admin/command' ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
}

export function findCommandDestination(pathname: string): CommandDestination | undefined {
  return commandNavigation.find((item) => isCommandDestinationActive(pathname, item.href));
}
```

Use existing Phosphor icons; do not draw icons with CSS, text glyphs, or custom SVG. Provide contextual create actions only where a real internal action exists. Saved Searches remains reachable but is grouped under tools rather than presented as a co-equal primary module.

- [ ] **Step 4: Add scoped Command tokens and geometry**

Create `command-shell.css` with these tokens and layout invariants:

```css
.command-root {
  --command-rail: 80px;
  --command-rail-expanded: 248px;
  --command-header: 64px;
  --command-mobile-header: 56px;
  --command-black: #0a0a0a;
  --command-graphite: #24262b;
  --command-ink: #292b31;
  --command-muted: #6f737b;
  --command-gold: #eac469;
  --command-gold-strong: #c08235;
  --command-canvas: #f6f5f2;
  --command-surface: #ffffff;
  --command-border: #dedfdc;
  --command-danger: #b42318;
  --command-success: #26724a;
  min-height: 100dvh;
  background: var(--command-canvas);
  color: var(--command-ink);
}

.command-canvas {
  min-width: 0;
  min-height: calc(100dvh - var(--command-header));
  margin-left: var(--command-rail);
  padding-top: var(--command-header);
  background: var(--command-canvas);
}

.command-main {
  min-width: 0;
  min-height: calc(100dvh - var(--command-header));
  overflow-x: clip;
}

@media (max-width: 1023px) {
  .command-canvas {
    margin-left: 0;
    padding-top: var(--command-mobile-header);
    min-height: calc(100dvh - var(--command-mobile-header));
  }
}

@media (prefers-reduced-motion: reduce) {
  .command-root *,
  .command-root *::before,
  .command-root *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

Add component-specific classes in the same file for the fixed rail/header, 248px overlay expansion, 24px desktop gutters, 16px mobile gutters, 44px touch targets, high-contrast outlines, contained table overflow, and print hiding. Keep selectors under `.command-root` so public pages and the original admin shell do not change.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
cd frontend
npm test -- src/components/command/shell/commandNavigation.test.ts
npm run typecheck
```

Expected: PASS.

```bash
git add frontend/src/components/command/shell/commandNavigation.ts frontend/src/components/command/shell/commandNavigation.test.ts frontend/src/app/admin/command/command-shell.css
git commit -m "feat: define Command shell visual contract"
```

### Task 3: Build the persistent responsive shell

**Files:**
- Create: `frontend/src/components/command/shell/CommandShell.tsx`
- Create: `frontend/src/components/command/shell/CommandRail.tsx`
- Create: `frontend/src/components/command/shell/CommandUtilityHeader.tsx`
- Create: `frontend/src/components/command/shell/CommandMobileNavigation.tsx`
- Create: `frontend/src/components/command/shell/CommandGlobalSearch.tsx`
- Create: `frontend/src/components/command/shell/useFocusContainment.ts`
- Create: `frontend/src/components/command/shell/CommandShell.test.tsx`
- Modify: `frontend/src/app/admin/command/layout.tsx`

- [ ] **Step 1: Write failing shell behavior tests**

Mock `next/navigation` with a mutable pathname and assert all of the following in `CommandShell.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

const mockRouterPush = vi.fn();
let mockPathname = '/admin/command';

vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ push: mockRouterPush, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

it('renders the rail, utility header, light canvas, and active route on Home', () => {
  render(<CommandShell><h1>Home body</h1></CommandShell>);
  expect(screen.getByRole('navigation', { name: 'Command modules' })).toBeInTheDocument();
  expect(screen.getByRole('banner')).toBeInTheDocument();
  expect(screen.getByRole('main')).toHaveClass('command-main');
  expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('aria-current', 'page');
});

it('opens global search with Control+K and navigates by keyboard', async () => {
  const user = userEvent.setup();
  render(<CommandShell><p>Body</p></CommandShell>);
  await user.keyboard('{Control>}k{/Control}');
  const search = screen.getByRole('combobox', { name: 'Search Command' });
  await user.type(search, 'tasks');
  await user.keyboard('{ArrowDown}{Enter}');
  expect(mockRouterPush).toHaveBeenCalledWith('/admin/command/tasks');
});

it('closes the mobile drawer with Escape and restores focus to its trigger', async () => {
  const user = userEvent.setup();
  render(<CommandShell><p>Body</p></CommandShell>);
  const trigger = screen.getByRole('button', { name: 'Open Command navigation' });
  await user.click(trigger);
  expect(screen.getByRole('dialog', { name: 'Command navigation' })).toBeInTheDocument();
  await user.keyboard('{Escape}');
  expect(screen.queryByRole('dialog', { name: 'Command navigation' })).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it('ships only Sold With Sweeney shell branding', () => {
  const { container } = render(<CommandShell><p>Body</p></CommandShell>);
  expect(screen.getByLabelText('Sold With Sweeney workspace')).toBeInTheDocument();
  expect(container).not.toHaveTextContent(/Keller Williams|DocuSign|KWIQ/i);
  expect(container.querySelector('[src*="exp-realty"]')).toBeNull();
});
```

Also cover exact Home matching, nested-route active matching, rail expand/collapse, route-change overlay closure, focus containment, scroll lock, and contextual action lookup.

- [ ] **Step 2: Run the shell test and confirm RED**

Run: `cd frontend && npm test -- src/components/command/shell/CommandShell.test.tsx`

Expected: FAIL because the shell components do not exist.

- [ ] **Step 3: Implement focus containment first**

Expose this hook contract:

```ts
export type FocusContainmentOptions = Readonly<{
  active: boolean;
  containerRef: React.RefObject<HTMLElement | null>;
  onDismiss: () => void;
  restoreFocusRef?: React.RefObject<HTMLElement | null>;
}>;

export function useFocusContainment(options: FocusContainmentOptions): void;
```

When active, the hook must store the previously focused element, focus the first focusable child, cycle Tab/Shift+Tab, close on Escape, set `document.body.style.overflow = 'hidden'`, and restore both overflow and focus on cleanup. It must not intercept keys while inactive.

- [ ] **Step 4: Implement the visual shell pieces**

`CommandRail` must:

- remain fixed at 80px on desktop;
- use `/logos/Sold With Sweeney Smiley.png` as the real SWS mark with descriptive alt text;
- render every registry item as an icon button/link with a visible tooltip and accessible label;
- mark the active link with `aria-current="page"`, gold fill, and a non-color left-edge indicator;
- open the 248px labeled overlay from a button with `aria-expanded`; and
- keep rare tools grouped at the bottom.

`CommandUtilityHeader` must:

- remain fixed at 64px and begin after the rail;
- expose global search, one route-contextual create action, notifications, Help, and Brandon’s account menu;
- render a skip link to `#command-main` before utility actions;
- never display a fake notification count; omit the badge when the API has no count; and
- use icon-plus-text for the primary create action and accessible names for icon-only controls.

`CommandGlobalSearch` must implement a modal combobox/listbox over the registry. Command+K and Control+K open it. ArrowDown/ArrowUp change the active option, Enter routes, Escape closes, and the typed query matches label, short label, and search terms.

`CommandMobileNavigation` must use `role="dialog"`, `aria-modal="true"`, the focus hook, an 88vw width capped at 320px, a scrim, 44px targets, and close after navigation.

`CommandShell` must compose all pieces for every route:

```tsx
export function CommandShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="command-root">
      <CommandRail />
      <CommandUtilityHeader />
      <CommandMobileNavigation />
      <div className="command-canvas">
        <main id="command-main" className="command-main" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Replace the current route layout**

Remove the Home bypass and the inline navigation implementation from `frontend/src/app/admin/command/layout.tsx`. Import `./command-shell.css` and render `<CommandShell>{children}</CommandShell>` unconditionally. Do not change `frontend/src/app/admin/layout.tsx`; its existing Command bypass remains the authentication boundary.

- [ ] **Step 6: Run tests, typecheck, and commit**

Run:

```bash
cd frontend
npm test -- src/components/command/shell/CommandShell.test.tsx src/components/command/shell/commandNavigation.test.ts
npm run typecheck
```

Expected: PASS.

```bash
git add frontend/src/components/command/shell frontend/src/app/admin/command/layout.tsx frontend/src/app/admin/command/command-shell.css
git commit -m "feat: add persistent Command parity shell"
```

### Task 4: Add the shared work-canvas primitives and evidence states

**Files:**
- Create: `frontend/src/components/command/ui/CommandModuleHeader.tsx`
- Create: `frontend/src/components/command/ui/CommandTabs.tsx`
- Create: `frontend/src/components/command/ui/CommandDataTable.tsx`
- Create: `frontend/src/components/command/ui/CommandOverlay.tsx`
- Create: `frontend/src/components/command/ui/CommandStatePanel.tsx`
- Create: `frontend/src/components/command/ui/CommandEvidencePanel.tsx`
- Create: `frontend/src/components/command/ui/CommandToastProvider.tsx`
- Create: `frontend/src/components/command/ui/CommandUi.test.tsx`

- [ ] **Step 1: Write failing keyboard, table, and state tests**

The focused test must prove:

```tsx
import { useRef, useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

const taskTabs = [
  { value: 'todo', label: 'To Do' },
  { value: 'completed', label: 'Completed' },
  { value: 'paused', label: 'Paused', disabled: true },
  { value: 'archived', label: 'Archived' },
] as const;
const onValueChange = vi.fn();
const rows = [{ id: '1', name: 'Avery Lake' }];
const columns = [{ key: 'name', header: 'Name', render: (row: (typeof rows)[number]) => row.name }];

function OverlayAndToastProbe() {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const { pushToast } = useCommandToast();

  return (
    <>
      <button ref={triggerRef} onClick={() => { setOpen(true); pushToast({ tone: 'error', message: 'Unable to save' }); }}>
        Open detail
      </button>
      <CommandOverlay open={open} title="Detail" triggerRef={triggerRef} onClose={() => setOpen(false)} />
    </>
  );
}

it('moves tab focus with arrows, Home, and End without activating disabled tabs', async () => {
  const user = userEvent.setup();
  render(<CommandTabs ariaLabel="Task states" tabs={taskTabs} value="todo" onValueChange={onValueChange} />);
  const todo = screen.getByRole('tab', { name: 'To Do' });
  todo.focus();
  await user.keyboard('{ArrowRight}{Enter}');
  expect(onValueChange).toHaveBeenCalledWith('completed');
  await user.keyboard('{End}{Enter}');
  expect(onValueChange).toHaveBeenCalledWith('archived');
});

it('distinguishes aggregate evidence from observed records', () => {
  render(<CommandEvidencePanel evidenceLevel="displayed_aggregate" displayLabel="My Referral Network" observedCount={5} displayedCount={2318} artifactCount={2} />);
  expect(screen.getByText('Displayed aggregate')).toBeInTheDocument();
  expect(screen.getByText(/2,318 was displayed; 5 distinct identities were observed/i)).toBeInTheDocument();
  expect(screen.queryByText(/2,318 people imported/i)).not.toBeInTheDocument();
});

it('keeps a wide data table inside its own scroll container', () => {
  render(<CommandDataTable ariaLabel="Contacts" columns={columns} rows={rows} rowKey={(row) => row.id} />);
  expect(screen.getByRole('region', { name: 'Contacts table' })).toHaveClass('command-table-scroll');
  expect(screen.getByRole('table', { name: 'Contacts' })).toBeInTheDocument();
});

it('restores focus after a drawer closes and announces an error toast assertively', async () => {
  const user = userEvent.setup();
  render(<OverlayAndToastProbe />);
  const trigger = screen.getByRole('button', { name: 'Open detail' });
  await user.click(trigger);
  await user.keyboard('{Escape}');
  expect(trigger).toHaveFocus();
  expect(screen.getByRole('alert')).toHaveTextContent('Unable to save');
});
```

Also test loading skeleton semantics, first-run guidance, true empty, partial-capture explanation, error/retry callback, `aria-sort`, select-all indeterminate behavior, and the bulk-action region.

- [ ] **Step 2: Run the test and confirm RED**

Run: `cd frontend && npm test -- src/components/command/ui/CommandUi.test.tsx`

Expected: FAIL because the shared UI modules do not exist.

- [ ] **Step 3: Implement exact public contracts**

Use these evidence types everywhere:

```ts
export type EvidenceLevel = 'observed_record' | 'rendered_occurrence' | 'displayed_aggregate';
export type CaptureQuality = 'complete' | 'partial' | 'limitation';
export type CommandStateKind = 'loading' | 'first_run' | 'empty' | 'evidence_only' | 'partial_capture' | 'error';
```

`CommandEvidencePanel` accepts evidence level, capture quality, display label, observed/rendered/displayed counts, explanation, and artifact links. It must render only supplied counts. A missing normalized count is “Not materialized,” never zero.

`CommandStatePanel` accepts a state kind, title, message, optional action label/callback, and optional evidence child. Loading renders `role="status"` and an accessible label. Error renders `role="alert"` and an explicit Retry action.

`CommandTabs` implements the ARIA tabs pattern with roving `tabIndex`, linked `aria-controls`, ArrowLeft/ArrowRight/Home/End, and a click/tap path. It must not rely on color to show selection.

`CommandToastProvider` exposes `useCommandToast()`, whose `pushToast({ tone, message })` method renders success/info messages in a polite `role="status"` region and errors in an assertive `role="alert"` region.

`CommandDataTable<Row>` uses semantic table markup and this typed boundary:

```ts
export type CommandColumn<Row> = Readonly<{
  key: string;
  header: string;
  sortable?: boolean;
  width?: string;
  render: (row: Row) => React.ReactNode;
}>;

export type CommandSort = Readonly<{
  key: string;
  direction: 'ascending' | 'descending';
}>;
```

It receives `rows`, `columns`, `rowKey`, optional `sort`, `onSortChange`, selected keys, `onSelectionChange`, toolbar, bulk actions, empty state, and row activation. Page overflow is forbidden; only `.command-table-scroll` may scroll horizontally.

`CommandOverlay` exposes `variant="dialog" | "drawer"`, `open`, `onOpenChange`, `labelledBy`, `triggerRef`, and children. Desktop drawers enter from the right at 480px; below 768px drawers and dialogs become bottom sheets capped at 90dvh. All variants reuse `useFocusContainment`.

`CommandToastProvider` uses a polite `role="status"` region for success/info and an assertive `role="alert"` region for warning/error. Success toasts may offer Undo only when the caller supplies a real reversible callback.

- [ ] **Step 4: Style the primitives inside the scoped CSS file**

Add strict 12-column desktop grids, 48–56px table rows, 12–14px interface type, 24px desktop/16px mobile gutters, white surfaces, 1px graphite-tinted borders, small 4–8px radii, clear `:focus-visible` gold/black outlines, horizontal KPI snap scrolling on mobile, and no gradient-filled generic cards.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
cd frontend
npm test -- src/components/command/ui/CommandUi.test.tsx
npm run typecheck
```

Expected: PASS.

```bash
git add frontend/src/components/command/ui frontend/src/app/admin/command/command-shell.css
git commit -m "feat: add Command workspace primitives"
```

### Task 5: Build the truthful Home model and Follow-Up Readiness calculation

**Files:**
- Create: `frontend/src/lib/command/home.ts`
- Create: `frontend/src/lib/command/home.test.ts`
- Create: `frontend/src/test/fixtures/commandHome.ts`
- Modify: `frontend/src/lib/command/api.ts`
- Modify: `frontend/src/lib/command/api.test.ts`

- [ ] **Step 1: Write failing pure-model tests**

Use a fixed `2026-08-12T13:00:00.000Z` clock and prove the four-factor rules:

```ts
import { describe, expect, it } from 'vitest';
import { buildCommandHomeModel } from './home';
import { completeHomeInput, emptyButUnavailableInput, inputWithoutLastContactFields } from '@/test/fixtures/commandHome';

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
    expect(model.nextActions[0]).toMatchObject({ kind: 'overdue_tasks', href: '/admin/command/tasks?tab=todo&due=past' });
  });

  it('marks readiness partial when last-contact coverage is unavailable', () => {
    const model = buildCommandHomeModel(inputWithoutLastContactFields, now);
    expect(model.readiness.status).toBe('partial');
    expect(model.readiness.coverage).toEqual({ available: 3, total: 4 });
    expect(model.readiness.factors.find((factor) => factor.key === 'uncontacted_leads')).toMatchObject({ available: false, score: null });
    expect(model.readiness.label).toContain('3 of 4 inputs verified');
  });

  it('never converts unavailable data into a zero count or perfect score', () => {
    const model = buildCommandHomeModel(emptyButUnavailableInput, now);
    expect(model.readiness.score).toBeNull();
    expect(model.shortcuts.find((shortcut) => shortcut.key === 'never_contacted')?.count).toBeNull();
    expect(model.shortcuts.find((shortcut) => shortcut.key === 'never_contacted')?.evidenceState).toBe('partial_capture');
  });

  it('keeps the secondary metric strip at exactly four tiles', () => {
    expect(buildCommandHomeModel(completeInput, now).kpis).toHaveLength(4);
  });
});
```

Fixtures must include completed, open, overdue, undated, and archived tasks; lead and non-lead contacts; contactable and non-contactable profiles; active, closed, and lost opportunities; celebrations; goals; and an auditable briefing. No production names or private contact data belong in tests.

Create `frontend/src/test/fixtures/commandHome.ts` with one complete input and two explicit variants:

```ts
import type { CommandHomeInput } from '@/lib/command/home';

export const completeHomeInput: CommandHomeInput = {
  overview: { contacts: 4, open_tasks: 4, opportunities: 3, active_smart_plans: 2 },
  contacts: [
    { id: 1, first_name: 'Avery', last_name: 'Lake', email: 'avery@example.test', phone: null, stage: 'lead', last_contacted_at: null, recently_active_at: null },
    { id: 2, first_name: 'Morgan', last_name: 'Hill', email: null, phone: null, stage: 'lead', last_contacted_at: null, recently_active_at: null },
    { id: 3, first_name: 'Casey', last_name: 'Pine', email: null, phone: '+1 555 0103', stage: 'lead', last_contacted_at: '2026-08-10T15:00:00.000Z', recently_active_at: '2026-08-11T12:00:00.000Z' },
    { id: 4, first_name: 'Riley', last_name: 'Stone', email: 'riley@example.test', phone: '+1 555 0104', stage: 'client', last_contacted_at: '2026-08-09T15:00:00.000Z', recently_active_at: '2026-08-10T12:00:00.000Z' },
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
    { id: 1, name: 'Lake purchase', stage: 'active', value_cents: 52500000 },
    { id: 2, name: 'Stone listing', stage: 'under_contract', value_cents: 71000000 },
    { id: 3, name: 'Pine search', stage: 'cultivate', value_cents: null },
  ],
  celebrations: { birthdays: [], anniversaries: [] },
  goals: [
    { id: 1, name: 'Appointments', target_value: 12, current_value: 5, period: 'monthly' },
    { id: 2, name: 'Closings', target_value: 4, current_value: 1, period: 'quarterly' },
  ],
  briefing: { summary: 'Clear overdue tasks, then contact new leads.', source: 'internal-crm', requires_review: true },
  errors: {},
};

export const inputWithoutLastContactFields: CommandHomeInput = {
  ...completeHomeInput,
  contacts: completeHomeInput.contacts === null ? null : completeHomeInput.contacts.map((contact) => ({
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
```

Import `completeHomeInput`, `inputWithoutLastContactFields`, and `emptyButUnavailableInput` in `home.test.ts`; do not redefine divergent fixtures in the component tests.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `cd frontend && npm test -- src/lib/command/home.test.ts`

Expected: FAIL because the model builder does not exist.

- [ ] **Step 3: Extend current API types without inventing fields**

Add optional factual fields that later domain APIs may return while retaining compatibility with the current response:

```ts
export type Contact = {
  id: number;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  stage: string;
  birthday?: string | null;
  anniversary?: string | null;
  last_contacted_at?: string | null;
  recently_active_at?: string | null;
  health_score?: number | null;
};

export type Opportunity = {
  id: number;
  name: string;
  stage: string;
  value_cents: number | null;
  updated_at?: string | null;
};
```

Do not assign defaults to optional timestamps or health values during JSON parsing. Their absence is the coverage signal.

- [ ] **Step 4: Implement the loader and pure model**

Expose these contracts from `home.ts`:

```ts
import type { AiBriefing, Celebrations, Contact, Goal, Opportunity, Overview, Task } from './api';

export type CommandHomeRegion = 'overview' | 'contacts' | 'tasks' | 'opportunities' | 'celebrations' | 'goals' | 'briefing';

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

export type ReadinessFactorKey = 'overdue_tasks' | 'uncontacted_leads' | 'contact_health' | 'active_opportunities';

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
```

Use fixed weights: overdue tasks 35, uncontacted leads 30, contact health 20, active opportunities 15. Each factor returns a 0–100 readiness score:

- overdue tasks: `100 × (1 - overdueOpen / max(openTasks, 1))`;
- uncontacted leads: `100 × (1 - neverContacted / max(leadContacts, 1))`, available only when every lead record contains the `last_contacted_at` property;
- contact health: `100 × contactableContacts / max(allContacts, 1)`, where contactable means a non-empty email or phone; and
- active opportunities: `100 × activeOpportunities / max(nonLostOpportunities, 1)`, where active stages are `active`, `offer`, or `under_contract`.

If there are no records in an available factor, return a neutral operational score of 100 and explicitly state “No records in scope.” If a field is absent, return `available: false`, null counts, and an unavailable insight. The total score is the weighted mean of available factors only. It is null when no factor is available and its status is always `partial` whenever coverage is below four. Complete scores map to `ready` at 80–100, `watch` at 60–79, and `at_risk` below 60.

The loader receives an injectable API boundary and fetches the current overview, every contact page in 100-row increments, tasks, opportunities, celebrations, goals, and the saved briefing in parallel where possible. It returns either a `CommandHomeModel` or a typed per-region error map. One failed optional region must not erase successful hero/task data.

Rank `nextActions` by actionable affected count, then urgency, then a stable key. Never create an action for an unavailable factor.

- [ ] **Step 5: Add API regression tests**

Add assertions that optional source fields survive mocked responses unchanged and that every request keeps the admin bearer token. Keep the existing API behavior tests intact.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
cd frontend
npm test -- src/lib/command/home.test.ts src/lib/command/api.test.ts
npm run typecheck
```

Expected: PASS.

```bash
git add frontend/src/lib/command/home.ts frontend/src/lib/command/home.test.ts frontend/src/test/fixtures/commandHome.ts frontend/src/lib/command/api.ts frontend/src/lib/command/api.test.ts
git commit -m "feat: derive truthful Follow-Up Readiness"
```

### Task 6: Rebuild Home around the priority decision

**Files:**
- Create: `frontend/src/components/command/home/CommandHome.tsx`
- Create: `frontend/src/components/command/home/FollowUpReadinessHero.tsx`
- Create: `frontend/src/components/command/home/HomeShortcutStrip.tsx`
- Create: `frontend/src/components/command/home/HomeKpiStrip.tsx`
- Create: `frontend/src/components/command/home/HomeTaskQueue.tsx`
- Create: `frontend/src/components/command/home/HomeGoals.tsx`
- Create: `frontend/src/components/command/home/HomeContextPanels.tsx`
- Create: `frontend/src/components/command/home/CommandHome.test.tsx`
- Modify: `frontend/src/app/admin/command/page.tsx`
- Modify: `frontend/src/app/admin/command/command-shell.css`

- [ ] **Step 1: Write failing Home component tests**

Render `CommandHome` with injected `loadHome` and test these user-visible outcomes:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { buildCommandHomeModel } from '@/lib/command/home';
import { completeHomeInput, inputWithoutLastContactFields } from '@/test/fixtures/commandHome';
import { CommandHome } from './CommandHome';

const now = new Date('2026-08-12T13:00:00.000Z');
const completeHomeModel = buildCommandHomeModel(completeHomeInput, now);
const partialHomeModel = buildCommandHomeModel(inputWithoutLastContactFields, now);

it('answers what needs attention with one readiness hero and four KPIs', async () => {
  render(<CommandHome loadHome={async () => completeHomeModel} />);
  expect(await screen.findByRole('heading', { name: /Follow-Up Readiness/i })).toBeInTheDocument();
  expect(screen.getByText(/3 overdue tasks need attention first/i)).toBeInTheDocument();
  expect(screen.getAllByTestId('home-kpi')).toHaveLength(4);
  expect(screen.getByRole('link', { name: /Review overdue tasks/i })).toHaveAttribute('href', '/admin/command/tasks?tab=todo&due=past');
});

it('labels an incomplete readiness score and identifies the missing input', async () => {
  render(<CommandHome loadHome={async () => partialHomeModel} />);
  expect(await screen.findByText(/3 of 4 inputs verified/i)).toBeInTheDocument();
  expect(screen.getByText(/Last-contact history is unavailable/i)).toBeInTheDocument();
  expect(screen.queryByText('100% ready')).not.toBeInTheDocument();
});

it('changes task scope with keyboard-operable tabs', async () => {
  const user = userEvent.setup();
  render(<CommandHome loadHome={async () => completeHomeModel} />);
  await screen.findByRole('tab', { name: 'My Tasks' });
  const myTasks = screen.getByRole('tab', { name: 'My Tasks' });
  myTasks.focus();
  await user.keyboard('{ArrowRight}{Enter}');
  expect(screen.getByRole('tab', { name: 'Team Tasks' })).toHaveAttribute('aria-selected', 'true');
});

it('retries only after a failed load and announces the error', async () => {
  const loadHome = vi.fn().mockRejectedValueOnce(new Error('Home unavailable')).mockResolvedValueOnce(completeHomeModel);
  const user = userEvent.setup();
  render(<CommandHome loadHome={loadHome} />);
  await user.click(await screen.findByRole('button', { name: 'Retry Home' }));
  expect(await screen.findByRole('heading', { name: /Follow-Up Readiness/i })).toBeInTheDocument();
  expect(loadHome).toHaveBeenCalledTimes(2);
});
```

Also verify loading skeletons, true-empty positive state, shortcut null counts, goal mutation affordance, briefing review label, upcoming-booking partial state, captured-placeholder disclosure, and the absence of vendor names/assets.

Add a test with `useSearchParams()` returning `create=task`; the quick-create dialog must open, and closing it must call `router.replace('/admin/command', { scroll: false })` so the contextual header action is a real interaction rather than inert chrome.

- [ ] **Step 2: Run the component test and confirm RED**

Run: `cd frontend && npm test -- src/components/command/home/CommandHome.test.tsx`

Expected: FAIL because the Home components do not exist.

- [ ] **Step 3: Implement the dense module header and shortcut strip**

Keep the component testable through this dependency boundary:

```ts
export type CommandHomeProps = Readonly<{
  loadHome?: () => Promise<CommandHomeModel>;
}>;
```

The production default is `loadCommandHome`; tests inject resolved or rejected models. The injected function is called once per load attempt and again only from the explicit Retry action.

Home begins with `CommandModuleHeader`:

- breadcrumb label `Internal CRM`;
- heading `Welcome home, Brandon`;
- supporting line `Your next best actions across contacts, tasks, pipeline, and agreements.`;
- contextual `Create task` primary action; and
- `Customize` as a local display popover only when the control actually changes visible panel preferences.

The shortcut strip contains exactly four compact, horizontally scrollable buttons: Leads Never Contacted, Recently Active, Birthdays, Anniversaries. A null count renders `Unavailable` plus a partial-capture description, never `0`.

- [ ] **Step 4: Implement the signature hero**

`FollowUpReadinessHero` must contain:

- the named metric, score or `Partial`, and coverage label;
- one sentence explaining the highest-risk factor;
- one primary link to the first ranked action;
- a horizontal four-segment rail whose segment length follows factor weight and whose visual state follows factor score;
- a compact ranked queue of up to four next actions; and
- a source/evidence disclosure that lists unavailable factors.

Do not render a donut, radial gauge, decorative chart, or animation that obscures exact values. Use CSS transitions only for focus/hover feedback and honor reduced motion.

- [ ] **Step 5: Implement exactly four KPI tiles**

Use these fixed tiles in this order:

1. `Never contacted` — factual count or unavailable;
2. `Open tasks` — factual count and overdue insight;
3. `Active opportunities` — factual count and pipeline value when present;
4. `Contactable profiles` — factual percentage with email/phone coverage explanation.

Each tile includes a takeaway and a module link. Do not add Contacts, SmartPlans, or vanity totals as additional co-equal cards.

- [ ] **Step 6: Implement supporting operational regions**

Use a desktop 7/5 split that stacks in priority order on mobile:

- left: task queue first, then goals/data health;
- right: recent leads/celebrations, upcoming bookings, and Sweeney Briefing; and
- below: a collapsed `Recovered dashboard evidence` disclosure for source-only profit-share/lead-pool/other captured placeholders.

The task queue uses My Tasks, Team Tasks, and All Tasks tabs, date/source filters, five visible rows, and View all. Quick create opens `CommandOverlay` and persists only through the existing task API.

`CommandHome` reads the `create` search parameter. `create=task` opens the same quick-create overlay used by the queue. Closing or successfully creating removes the parameter through `router.replace('/admin/command', { scroll: false })`; direct navigation and the utility header therefore share one implementation.

The booking panel must display a partial-capture state until a global booking list is available. It may link to a contact workspace booking history; it must not enumerate guessed bookings.

The Sweeney Briefing shows the saved auditable briefing by default, marks it `Review only`, and links to the existing AI route for generation. Home does not auto-generate AI text on load.

- [ ] **Step 7: Replace the route page with a route-only wrapper**

`frontend/src/app/admin/command/page.tsx` becomes:

```tsx
import { CommandHome } from '@/components/command/home/CommandHome';

export default function CommandHomePage() {
  return <CommandHome />;
}
```

Remove the duplicate sidebar, dark root background, generic metric cards, direct prompt usage, and page-local navigation array.

- [ ] **Step 8: Run focused and full frontend checks**

Run:

```bash
cd frontend
npm test -- src/components/command/home/CommandHome.test.tsx src/lib/command/home.test.ts
npm test
npm run typecheck
npm run lint
```

Expected: PASS with zero warnings introduced by Command files.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/command/home frontend/src/app/admin/command/page.tsx frontend/src/app/admin/command/command-shell.css
git commit -m "feat: rebuild Command Home around follow-up readiness"
```

### Task 7: Add deterministic Playwright, responsive, and accessibility gates

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `.gitignore`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/fixtures/command.ts`
- Create: `frontend/e2e/fixtures/command-home.json`
- Create: `frontend/e2e/command-shell.spec.ts`
- Create: `frontend/e2e/command-home.spec.ts`
- Create: `frontend/e2e/command-mobile.spec.ts`
- Create: `frontend/e2e/command-accessibility.spec.ts`

- [ ] **Step 1: Install browser-test dependencies and commands**

Run:

```bash
cd frontend
npm install --save-dev @playwright/test @axe-core/playwright
npx playwright install chromium
```

Add scripts:

```json
{
  "scripts": {
    "test:e2e": "playwright test --project=command-desktop --project=command-mobile",
    "test:a11y": "playwright test --project=command-a11y",
    "test:visual": "playwright test --project=command-visual",
    "test:e2e:report": "playwright show-report"
  }
}
```

Add these ignores at repository root:

```gitignore
frontend/playwright-report/
frontend/test-results/
frontend/.auth/
frontend/artifacts/command-qa/current/
```

- [ ] **Step 2: Configure isolated projects**

Create `frontend/playwright.config.ts`:

```ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [['html', { open: 'never' }], ['github']] : [['list'], ['html', { open: 'never' }]],
  timeout: 30_000,
  expect: {
    timeout: 5_000,
    toHaveScreenshot: {
      animations: 'disabled',
      maxDiffPixelRatio: 0.01,
      threshold: 0.2,
    },
  },
  use: {
    baseURL: 'http://127.0.0.1:3100',
    locale: 'en-US',
    timezoneId: 'America/New_York',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'command-desktop',
      testMatch: ['**/command-shell.spec.ts', '**/command-home.spec.ts'],
      use: { ...devices['Desktop Chrome'], viewport: { width: 1800, height: 982 } },
    },
    {
      name: 'command-mobile',
      testMatch: '**/command-mobile.spec.ts',
      use: { ...devices['iPhone 14'], viewport: { width: 390, height: 844 } },
    },
    {
      name: 'command-a11y',
      testMatch: '**/command-accessibility.spec.ts',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'command-visual',
      testMatch: '**/command-visual.spec.ts',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1800, height: 982 } },
    },
  ],
  webServer: {
    command: process.env.CI
      ? 'npm run build && npm run start -- --hostname 127.0.0.1 --port 3100'
      : 'npm run dev -- --hostname 127.0.0.1 --port 3100',
    url: 'http://127.0.0.1:3100/admin/login',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
```

- [ ] **Step 3: Create a deterministic authenticated fixture**

`frontend/e2e/fixtures/command.ts` must:

- add `admin_token=test-admin-token` to localStorage before navigation;
- register API routes before `page.goto`;
- return a successful `/api/v1/auth/me` response;
- fulfill current Command endpoints from `command-home.json`;
- fix the browser time at `2026-08-12T13:00:00.000Z`;
- record console errors and page errors; and
- fail teardown when an unexpected console/page error occurred.

Expose `test`, `expect`, `mockCommandEndpoint(path, response)`, and `failCommandEndpointOnce(path, status, detail)`. Each test gets a fresh browser context and fresh route state; no mutable fixture state is shared across tests or workers.

The JSON fixture must use obviously synthetic names such as Avery Lake and Morgan Hill, exact ISO timestamps, all four readiness inputs, at least six tasks, four contacts, three opportunities, one birthday, one anniversary, two goals, and a review-only briefing.

- [ ] **Step 4: Write the persistent-shell journeys**

`command-shell.spec.ts` must use role/label locators and web-first assertions to cover:

```ts
test('shell persists across module navigation @critical', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  const navigation = commandPage.getByRole('navigation', { name: 'Command modules' });
  await navigation.getByRole('link', { name: 'Contacts' }).click();
  await expect(commandPage).toHaveURL('/admin/command/contacts');
  await expect(navigation).toBeVisible();
  await expect(navigation.getByRole('link', { name: 'Contacts' })).toHaveAttribute('aria-current', 'page');
});

test('global search is keyboard operable @critical', async ({ commandPage }) => {
  await commandPage.goto('/admin/command');
  await commandPage.keyboard.press(process.platform === 'darwin' ? 'Meta+K' : 'Control+K');
  const search = commandPage.getByRole('combobox', { name: 'Search Command' });
  await search.fill('agreement');
  await commandPage.keyboard.press('ArrowDown');
  await commandPage.keyboard.press('Enter');
  await expect(commandPage).toHaveURL('/admin/command/agreements');
});
```

Also test skip-link focus, rail expansion without canvas movement, and active nested-route matching.

Put the mobile-only drawer, focus-restoration, route-close, 44px target, and horizontal-overflow assertions in `command-mobile.spec.ts`; keep the fixed-rail geometry assertions in `command-shell.spec.ts` so each project tests only the shell it renders.

- [ ] **Step 5: Write Home journeys without arbitrary waits**

`command-home.spec.ts` must test the hero insight, primary action link, exact four KPI tiles, My/Team/All task tabs, quick-create dialog semantics, celebrations shortcuts, partial state after a response omits last-contact fields, and error/retry where the first Home dependency fails and the second succeeds. Use response/locator waiting; never use `waitForTimeout`.

Click the utility header’s `Create task` action from Home, assert navigation to `?create=task`, assert the dialog opens, close it with Escape, and assert focus returns to the header action after the query is cleared.

- [ ] **Step 6: Add axe and manual-keyboard gates**

`command-accessibility.spec.ts` must:

- run AxeBuilder with WCAG 2 A/AA and WCAG 2.1 A/AA tags against Home, an open global search, and an open mobile drawer;
- keyboard through skip link, rail, search, contextual action, tabs, and first table row;
- assert dialogs trap focus and return it to the trigger;
- assert `aria-current`, `aria-selected`, `aria-sort`, live regions, and evidence labels;
- emulate `forcedColors: 'active'` and prove core controls remain visible; and
- emulate `reducedMotion: 'reduce'` and prove animated transitions collapse to near-zero duration.

- [ ] **Step 7: Run browser tests repeatedly and commit**

Run:

```bash
cd frontend
npm run test:e2e
npm run test:a11y
npx playwright test --project=command-desktop --grep @critical --repeat-each=5
```

Expected: PASS with no retries required locally, no unexpected console/page errors, and no axe violations.

```bash
git add .gitignore frontend/package.json frontend/package-lock.json frontend/playwright.config.ts frontend/e2e/fixtures frontend/e2e/command-shell.spec.ts frontend/e2e/command-home.spec.ts frontend/e2e/command-mobile.spec.ts frontend/e2e/command-accessibility.spec.ts
git commit -m "test: gate Command shell across browser and accessibility"
```

### Task 8: Establish source-grounded visual regression and blocking design QA

**Files:**
- Create: `frontend/e2e/command-visual.spec.ts`
- Create: `frontend/e2e/visual/command-reference-manifest.ts`
- Create: `frontend/src/test/command-reference-manifest.test.ts`
- Create after comparison: `frontend/design-qa.md`

- [ ] **Step 1: Write the failing reference-manifest test**

```ts
import { describe, expect, it } from 'vitest';
import { commandSourceReferences } from '../../e2e/visual/command-reference-manifest';

describe('Command source visual manifest', () => {
  it('uses only known rendered targets for parity comparisons', () => {
    const valid = commandSourceReferences.filter((item) => item.quality === 'valid').map((item) => item.filename);
    expect(valid).toContain('command-home-live.png');
    expect(valid).toContain('contacts-live-current.png');
    expect(valid).toContain('tasks-to-do-live.png');
    expect(valid).not.toContain('top-home.png');
    expect(valid).not.toContain('contacts-list.png');
    expect(valid.some((filename) => filename.endsWith('-retry.png'))).toBe(false);
  });

  it('records source dimensions and brand-only mask rectangles', () => {
    const home = commandSourceReferences.find((item) => item.filename === 'command-home-live.png');
    expect(home).toMatchObject({ width: 1800, height: 2249, quality: 'valid' });
    expect(home?.brandMasks).toEqual(expect.arrayContaining([{ x: 0, y: 0, width: 80, height: 64, reason: 'source vendor mark' }]));
  });
});
```

- [ ] **Step 2: Run the manifest test and confirm RED**

Run: `cd frontend && npm test -- src/test/command-reference-manifest.test.ts`

Expected: FAIL because the manifest imported from `frontend/e2e/visual` does not exist.

- [ ] **Step 3: Implement the source-reference manifest**

Each entry contains filename, route, width, height, `valid | limitation`, observed interaction state, and source-only mask rectangles. Record at least the valid files listed in the Visual contract plus these limitations: `top-home.png`, `contacts-list.png`, `opportunities-board.png`, `smartplans-my.png`, every selected retry image, and `referrals-dashboard-error-state.png`.

Mask only vendor-specific source pixels during human source comparison:

- source rail mark: x=0, y=0, width=80, height=64;
- source KWIQ/store cluster: x=1180, y=0, width=180, height=64;
- source account/avatar text: x=1430, y=0, width=290, height=64.

Do not mask rail width, header height, module tabs, table rows, content gutters, cards, pagination, or drawer geometry. Accent-color differences are reviewed through the documented SWS color substitution, not hidden with broad masks.

- [ ] **Step 4: Add stable local SWS snapshots**

`command-visual.spec.ts` must capture:

- Home viewport at 1800×982;
- full Home at 1800px width;
- Home at 1024×768;
- Home at 390×844;
- expanded desktop rail;
- open global search;
- open mobile drawer; and
- partial/evidence-only Home state.

Before each screenshot, wait for the named heading and loading status to disappear, freeze time through the fixture, and use `animations: 'disabled'`. Create `frontend/artifacts/command-qa/current/` with `mkdir({ recursive: true })` from `node:fs/promises`; then, in addition to `toHaveScreenshot`, write the desktop and full-page captures to `frontend/artifacts/command-qa/current/home-desktop-1800x982.png` and `frontend/artifacts/command-qa/current/home-desktop-full.png` for source comparison. Mask only the synthetic avatar and fixed-date element if their pixels remain environment-dependent. Commit Linux-generated Playwright baselines; do not commit source vendor screenshots or the gitignored current-capture artifacts.

- [ ] **Step 5: Run exact same-viewport source comparison**

Run the local Next app, open `/admin/command` in the Codex in-app Browser, exercise global search, task tabs, the mobile drawer, and the primary action, and inspect browser console output. Use Playwright only for the exact viewport captures.

Open both:

- local source: `$COMMAND_REFERENCE_DIR/command-home-live.png` at 1800px wide; and
- current capture: `frontend/artifacts/command-qa/current/home-desktop-1800x982.png` at 1800×982 and `frontend/artifacts/command-qa/current/home-desktop-full.png` for the full-page comparison.

Compare shell width, header height, canvas bounds, content density, header/title baseline, shortcut strip, hero priority, row heights, gutters, responsive stacking, focus treatment, and drawer dimensions. Apply only the manifest’s brand masks and SWS accent substitution.

- [ ] **Step 6: Write and pass the design QA report**

Create `frontend/design-qa.md` with:

```md
# Command UI Foundation Design QA

## Sources

- Reference: authorized local `command-home-live.png`, 1800px desktop.
- Current: local `/admin/command` desktop, tablet, and mobile captures.
- Brand substitution: source vendor marks/colors excluded; SWS black/gold is authoritative.

## Comparison

| Priority | Surface | Finding | Resolution |
|---|---|---|---|
| P0-P3 | Shell or Home surface | Exact observed difference | Exact implemented correction |

## Interaction and accessibility

- Global search, rail expansion, mobile drawer, task tabs, dialog focus, retry, forced colors, and reduced motion: passed.

## Remaining P3 notes

- None.

final result: passed
```

Do not write `final result: passed` until the reference and current capture were both opened at the same viewport and every P0/P1/P2 finding was corrected and recaptured. A missing source/current capture produces `final result: blocked` instead.

- [ ] **Step 7: Run visual gates and commit**

Run:

```bash
cd frontend
npm test -- src/test/command-reference-manifest.test.ts
npm run test:visual
npm run test:e2e
npm run test:a11y
```

Expected: PASS and `frontend/design-qa.md` ends with `final result: passed`.

```bash
git add frontend/e2e/command-visual.spec.ts frontend/e2e/visual frontend/e2e/command-visual.spec.ts-snapshots frontend/src/test/command-reference-manifest.test.ts frontend/design-qa.md
git commit -m "test: verify Command shell visual parity"
```

### Task 9: Run the release-quality foundation verification

**Files:**
- Modify only if findings require correction: files created or modified in Tasks 1–8

- [ ] **Step 1: Prove shell route coverage**

Run a browser smoke loop for every registry route. Each route must authenticate, preserve one shell, show the correct active navigation item, expose one `main` landmark, and avoid page-level horizontal scrolling. A domain page may retain its current interior until its parity plan, but it may not render a second sidebar or escape the fixed work canvas.

- [ ] **Step 2: Prove forbidden brands are absent from the shipped shell/Home**

Run:

```bash
rg -n "Keller Williams|DocuSign|KWIQ|exp-realty" frontend/src/app/admin/command frontend/src/components/command/shell frontend/src/components/command/home
```

Expected: no matches. Evidence metadata may name a source system only in later provenance views; the shell and Home do not.

- [ ] **Step 3: Run all frontend quality gates**

Run:

```bash
cd frontend
npm test
npm run typecheck
npm run lint
npm run build
npm run test:e2e
npm run test:a11y
npm run test:visual
npx playwright test --project=command-desktop --grep @critical --repeat-each=5
```

Expected: every command exits 0; no critical journey needs a retry; visual baselines are unchanged after a second run.

- [ ] **Step 4: Run repository hygiene checks**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors, no source screenshots/auth tokens/reports/traces staged, and only intentional foundation files changed.

- [ ] **Step 5: Correct any finding and rerun the exact failed gate**

Use the failing assertion, trace, screenshot diff, or `design-qa.md` comparison to make the smallest correction. Do not raise visual thresholds, add broad masks, disable axe rules, or replace functional assertions to force green.

- [ ] **Step 6: Commit any final verified correction**

```bash
git add frontend
git commit -m "fix: finish Command UI foundation verification"
```

Skip this commit when Task 9 required no file changes.

---

## Acceptance checklist

- [ ] One persistent SWS shell wraps `/admin/command` and every nested route.
- [ ] Desktop geometry is 80px rail, 64px utility header, and full-width warm-white work canvas.
- [ ] The rail expands to labels without moving content; mobile uses a 56px header and accessible off-canvas drawer.
- [ ] Global search, contextual actions, notifications/help/account controls, skip link, active states, overlays, and focus restoration work by keyboard.
- [ ] Shared tabs, table, overlay, state, evidence, and toast primitives are component-tested.
- [ ] Evidence levels and missing capture fields remain visibly distinct; unavailable never silently becomes zero.
- [ ] Home’s single hero is Follow-Up Readiness with a ranked next action and explicit input coverage.
- [ ] Home has exactly four secondary KPI tiles and keeps less urgent regions below/progressively disclosed.
- [ ] Current API compatibility is preserved; Home works without a backend change and shows partial states where current fields are insufficient.
- [ ] No vendor trademarks/assets ship in the shell/Home.
- [ ] Unit/component, TypeScript, lint, production build, desktop/mobile E2E, axe, repeated critical journeys, and visual regression all pass.
- [ ] The local source and current app were compared at the same viewport; `frontend/design-qa.md` ends in `final result: passed`.

## Self-review

### Spec coverage

- Shared shell, persistent navigation, utility controls, dense light canvas, mobile drawer, depth ladder, keyboard operation, loading/empty/evidence/partial/error states: Tasks 2–4.
- Home shortcuts, tasks, goals, recent leads, celebrations, pipeline/data health, bookings limitation, captured placeholders, and Sweeney Briefing: Tasks 5–6.
- Follow-Up Readiness, four-KPI limit, next-action insight, distinctive hero, editorial subtraction, and screenshot pitch: Home dashboard gates plus Tasks 5–6.
- Functional, responsive, accessibility, and visual checks: Tasks 1, 3–4, and 7–9.
- Vendor-brand boundary and valid-reference selection: Visual contract plus Tasks 3, 8, and 9.

### Deliberate deferrals

- Full domain interiors and record-level parity are deferred to their domain plans; this foundation provides their shared shell and primitives.
- A global upcoming-bookings API and complete last-contact/source-health fields are not assumed. Their absence renders partial coverage.
- Legally binding signature execution and vendor integrations remain outside the product boundary.

### Placeholder scan

The plan contains no unspecified implementation step, generic error-handling request, or copied-task shorthand. Every new component has an explicit responsibility, public contract, test behavior, verification command, and commit boundary.

### Type consistency

`EvidenceLevel`, `CaptureQuality`, `CommandStateKind`, `CommandColumn<Row>`, `CommandSort`, `ReadinessFactorKey`, `ReadinessFactor`, and `FollowUpReadiness` are defined once and reused by later tasks with unchanged names. Navigation uses one immutable registry for rail, mobile drawer, global search, active matching, and contextual actions.
