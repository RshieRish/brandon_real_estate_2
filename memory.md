# Project Memory

## Architecture Decisions
- Next.js App Router: SSR + static pages, no API routes (UI only)
- FastAPI backend: all AI, DB, business logic
- Gemini flash for chatbot speed; Gemini pro for complex analysis
- Neon PostgreSQL for launch

## Integration Status
## Integration Status
- Gemini API: Key provided; using `gemini-1.5-pro` (pro) and `gemini-1.5-flash` (standard).
- Google OAuth/Calendar: Credentials provided.
- Instagram: Access token prone to expiration; frontend handles fetching failure gracefully.
- Railway Backend: Docker builder forced via `railway.json`. Uses dynamic `$PORT` and root context.
- Vercel Frontend: Requires `NEXT_PUBLIC_API_URL` to match Railway domain.

## Content Status
- Videos: Available in public/assets/
- Headshots: Available in public/headshots/
- Logos: Available in public/logos/
- House blast frames: DONE (Task 22) — 60 WebP at frames/frame_001.webp, 60 JPEG at frames/house-blast/frame_0001.jpg
- Bio/reviews: In BRANDON_RE_SPEC.md Section 14

## Known Issues
- None

## Chatbot Architecture
- Chat widget is mounted globally from `frontend/src/components/layout/ClientWidgets.tsx`, so it appears across public pages.
- `backend/routers/chat.py` now returns structured chat payloads: `text`, `actions[]`, `widget`, plus backward-compatible `response`.
- `backend/services/gemini.py` instructs Gemini to return JSON and normalizes assistant actions into three allowed types: `send_message`, `navigate`, and `open_widget`.
- Legacy booking tags like `[BOOK_MEETING]` still work as a fallback and are normalized into `widget: 'calendar_picker'`.
- `frontend/src/hooks/useChat.ts` normalizes the structured API payload, preserves legacy booking fallback, and stores `actions` on assistant messages.
- `frontend/src/components/chat/ChatPanel.tsx` renders assistant messages as text bubbles with premium action buttons underneath and conditionally mounts `CalendarPickerCard` below a message when `widget === 'calendar_picker'`.
- `frontend/src/components/chat/CalendarPickerCard.tsx` remains the inline booking widget used by both direct widget replies and action-button triggered booking flows.
- `/api/v1/chat/lead` exists, but the current chat frontend does not submit lead capture there.
- Current allowed navigate destinations are `/buy`, `/sell`, `/invest`, and `/about`.
- Generative UI is still best treated as a later-stage extension for multiple rich widget types; the implemented server-driven structured actions are the safer current fit.

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
- 2026-03-23: Fixed Railway Railpack/Caddy detection bug by adding root `railway.json` and modifying `backend/Dockerfile` for root context. Fixed missing phase images by force-adding to git. Verified backend health success.
- 2026-03-27: Analyzed chatbot flow, then implemented structured assistant actions/buttons in the chatbot with browser-verified action rendering and booking-widget launch.
- Next: If requested, extend the action system with lead-capture prompts, richer analytics events, or additional widget types beyond booking.
