# Project Memory

## Architecture Decisions
- Next.js App Router: SSR + static pages, no API routes (UI only)
- FastAPI backend: all AI, DB, business logic
- Gemini flash for chatbot speed; Gemini pro for complex analysis
- Neon PostgreSQL for launch

## Integration Status
- Gemini API: Key provided, not yet in .env file (Task 3)
- Google OAuth: Credentials provided, not yet in .env file (Task 3)
- Google Calendar: Same OAuth credentials (pending calendar scope)
- Google Maps: Pending key
- KW CRM: Pending access path
- SMTP: Pending

## Content Status
- Videos: Available in public/assets/
- Headshots: Available in public/headshots/
- Logos: Available in public/logos/
- House blast frames: DONE (Task 22) — 60 WebP at frames/frame_001.webp, 60 JPEG at frames/house-blast/frame_0001.jpg
- Bio/reviews: In BRANDON_RE_SPEC.md Section 14

## Known Issues
- None

## Buyer Components
- `MonopolyJourney`: 3-phase accordion — Phase 1 (DeviceMobile), Phase 2 (HeartStraight), Phase 3 (House); CaretDown toggle; AnimatePresence open/close
- `BuyerMistakes`: 4-card 2-col grid; XCircle (red-400) for mistake, CheckCircle (gold) for fix

## LeadCaptureForm Props
- Now accepts: `source?: string`, `leadType?: string`, `ctaText?: string`

## About Page Components
- All 7 sections are named function components in `frontend/src/app/about/page.tsx`
- HeroSection: split grid, AnimatePresence, Brandon Sweeney Headshot.jpg, floating glass name badge
- StatsStrip: 4-cell `grid-cols-4` glass cards with gold stat value + uppercase label
- BioSection: sticky left column (zoomed headshot), 3 glassmorphism panels right
- DesignationsSection: 5-logo grid (NEAR/MAR/NAR/GREEN/C2EX) + 2 award cards
- MSisBSSection: $300K stat, external link to MSisBSNewEngland.com, story glassmorphism panel
- TeamSection: SWS TEAM Headshot.png, asymmetric image-left text-right layout
- ContactSection: centered, 3-col contact grid (Phone/Email/Office), gold Book a Call CTA

## Admin Pages (Task 20)
- `frontend/src/app/admin/leads/page.tsx` — filter pills, table, right-panel detail with status PATCH + notes PATCH on blur
- `frontend/src/app/admin/content/page.tsx` — 2-col grid, inline edit mode per block, PUT on save
- `frontend/src/app/admin/funnels/page.tsx` — table with publish/copy-link, create form with AI loading spinner
- `frontend/src/app/admin/analytics/page.tsx` — stats strip, top pages + top events with gold bar, recent events table
- `frontend/src/app/admin/settings/page.tsx` — 3 integration cards (Gemini/Calendar/KW), password form (coming soon), site info

## Last Session Context
- Task 20 complete: Admin sub-pages (leads, content, funnels, analytics, settings)
- Next: Check BRANDON_RE_SPEC.md for Task 21+
