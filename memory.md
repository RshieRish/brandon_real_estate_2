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

## Frontend Content Notes
- About page stats strip was updated to use Brandon-specific milestones instead of generic numbers.
- About page awards section now includes text-based recognition cards for MAR Good Neighbor, NEAR Good Neighbor, and Distinguished Young Professional.
- The requested `Brandon and Paige at Maine gala` image was added on 2026-04-02 at `frontend/public/headshots/brandon-and-paige-maine-gala.jpeg` and now replaces the lower About-page image in `TeamSection`.
- An awards-collage image is still not present in the repo as of 2026-04-02, so that swap remains blocked on asset delivery.
- Buy page common-mistakes section is now an interactive flashcard treatment rather than static cards.
- Buy lead-section gold headline text is now `THE ONE`.
- Seller lead-section headline is now `Stop Listing. Start Moving.`
- Home hero video no longer uses Brandon's headshot as a poster; it fades in only after the video loads to avoid the initial face flash.
- MS fundraising copy now uses `advocacy` instead of `research` on the relevant public sections.

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
- 2026-04-02: Applied About/Buy/Sell/home-page polish pass and removed the homepage hero headshot poster to fix the initial video flash.
- 2026-04-02: Added the provided Brandon and Paige gala image into `frontend/public/headshots/` and wired it into the About page.
- Next: If requested, extend the action system with lead-capture prompts, richer analytics events, or additional widget types beyond booking, or swap in an awards-collage image once that asset is added.

## 2026-03-31 - Home Videos
- Updated Invest and Sell pages with custom watermark-free hero videos saved in `frontend/public/videos`.

## 2026-03-31 - Home Video Cards
- Replaced static fallback images with video loops in the AudienceCards section (Buy, Sell, Invest). Used the corresponding videos from each respective page's hero section.

## 2026-03-31 - Marketing Dyson Sphere
- Built a 3D WebGL dyson sphere using Three.js inside `frontend/src/components/sell/MarketingSphere.tsx`.
- Maps custom PNG image logos onto 2D canvas sprites inside the 3D scene.
- Load `mini_house.gltf` into the center.
- Wrapped in Next.js `useRef` and `useEffect` with strict `cancelAnimationFrame` and unmounting logic for safely avoiding WebGL context leaks during client router navigation.
Added interactive videos to Seller Staging Checklist
