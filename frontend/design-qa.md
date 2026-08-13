# Command UI Foundation Design QA

## Sources and inspection method

- Reference: authorized local `kw_command_ui_screenshots/command-home-live.png`, 1800×2249, SHA-256 `14f67ec80e93b1144183761c3d9724a9bc09b014606b48ef97e7a159b42a7a83`.
- Current viewport: local `/admin/command` at 1800×982, SHA-256 `82def0cf2d9db8ed2f3ab02082853503292cf278d7f0b49e0da32f8e9d5d23ef`.
- Current full page: local `/admin/command` at 1800×1793, SHA-256 `4722d1ab8e45a6f6b435586cefbf3c18c30fcd79d1a31dc3827cb6b76a9f42f4`.
- Browser density: 1 CSS pixel per captured pixel at the named desktop, tablet, and mobile viewports.
- State: authenticated, deterministic synthetic CRM responses, browser time fixed to `2026-08-12T13:00:00.000Z` for Playwright captures.
- Comparison: the source's first 982 pixels and the current viewport capture were opened side by side at equal 1800px widths. The complete 2249px source and current full page were also opened side by side, with neutral padding below the shorter current page.
- Masks: only the manifest rectangles for the source vendor mark (`0,0 80×64`), source utility cluster (`1180,0 180×64`), and source account identity (`1430,0 290×64`) were covered. No current pixels or layout geometry were masked.
- Brand substitution: source vendor marks and accent colors are excluded; SWS black/gold, the source-controlled SWS smiley, and Brandon's internal controls are authoritative. No vendor screenshot or image was copied into the application.

## Measured shell contract

| Surface | Observed current geometry | Result |
|---|---:|---|
| Desktop viewport | 1800×982 | Exact comparison viewport |
| Fixed rail | x=0, y=0, 80×982 | Matches 80px shell contract |
| Fixed utility header | x=80, y=0, 1714×64 | Matches 64px header contract |
| Work canvas | x=80, y=0, width=1714; main starts at y=64 | Matches fixed shell bounds |
| Home content gutters | 24px left and right | Matches desktop gutter contract |
| Mobile header | 390×56 | Matches below-1024 mobile contract |
| Mobile drawer | x=0, y=0, 320×844 | Contained off-canvas navigation |
| Page overflow | 0px at desktop and mobile | No document-level horizontal scrolling |

## Comparison

| Priority | Surface | Finding | Resolution |
|---|---|---|---|
| P1 resolved | Home hierarchy | The source gives ten-plus panels similar visual weight, which obscures the first operational decision. | The approved subtraction gate is visible: one `Follow-Up Readiness` hero and exactly four KPI tiles above the fold. The first action, `Review overdue tasks`, is explicit in the 1800×982 capture. |
| P1 resolved | Evidence truth | Source shortcuts and dashboard regions can imply complete data even when the archive lacks record fields. | The partial-state capture visibly renders `Unavailable`, `Partial`, `3 of 4 inputs verified`, and an exact retry action; unavailable evidence is not converted to a favorable score. |
| P2 resolved | Shell and density | Source shell geometry and dense full-width canvas were the fidelity target, while source branding and accent color were not. | The measured 80px rail, 64px header, full-width canvas, 24px gutters, compact rows, and square-edged surfaces match the source intent. Only the documented SWS color/identity substitution differs. |
| P2 resolved | Full-page structure | The source is 2249px high; the current page is 1793px because source profit-share, lead-pool, and partner widgets are not equal operational priorities. | Preserved evidence is behind the collapsed `Recovered dashboard evidence` disclosure. The shorter page is intentional subtraction, not missing layout content. |
| P2 resolved | Responsive behavior | The archive provides no successful mobile Home reference. | Current captures at 1024×768 and 390×844 were inspected. Exactly 1024px keeps the fixed rail; 390px uses the 56px header, internally scrollable strips, stacked content, and a 320px drawer without document overflow. |
| P2 resolved | Overlays and focus | Expanded navigation and search must not move or escape the shell. | Expanded rail remains a 248px overlay over the unchanged canvas. Global search is centered and contained; the mobile drawer is viewport-height. Escape closes each overlay and restores focus in browser gates. |
| P3 | Development console | Next.js development mode reports its advisory for the site's existing global `scroll-behavior: smooth` declaration. | No page or console errors were observed. The advisory is non-rendering and production-independent; reduced-motion CSS and the dedicated browser gate still collapse transitions. |

## Dashboard quality gate

- One job: the page answers “What needs Brandon's attention next?”
- Named signature metric: `Follow-Up Readiness`.
- Distinctive decision surface: a weighted four-factor horizontal readiness rail with a ranked action queue, not a generic donut or decorative chart.
- Subtraction: one hero plus four KPIs above the fold replaces the source's ten-plus co-equal widgets.
- Screenshot pitch: the desktop viewport communicates an internal CRM workspace, 44% readiness, the three-overdue-task risk, and the first corrective action without scrolling.
- Capture reason: the interface is worth capturing because scattered CRM evidence is converted into one auditable priority decision.

## Interaction and accessibility

- In the Codex in-app Browser, global search returned Agreements for `agreement`; Personal, Team, and All task tabs each selected correctly; and the primary action navigated to `/admin/command/tasks?tab=todo&due=past`.
- At 390×844, the mobile drawer opened, measured 320×844, closed with Escape, and restored the undisturbed page.
- Global search, rail expansion, mobile drawer, quick-task dialog, retry, focus trapping/restoration, keyboard navigation, axe WCAG A/AA, forced colors, and reduced motion are covered by deterministic browser gates.
- Linux Playwright baseline candidates were generated in `mcr.microsoft.com/playwright:v1.62.1-noble`, inspected individually, and retained only after this comparison.

## Remaining P3 notes

- The Next.js development-only smooth-scroll advisory remains documented above; it does not change pixels, keyboard operation, reduced-motion behavior, or production output.

final result: passed
