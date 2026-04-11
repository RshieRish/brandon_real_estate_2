# Project Memory

## Architecture Decisions
- Next.js App Router: SSR + static pages, no API routes (UI only)
- FastAPI backend: all AI, DB, business logic
- Gemini flash for chatbot speed; Gemini pro for complex analysis
- Neon PostgreSQL for launch
- 2026-04-10: Approved direction for Brandon internal notifications is a DB-backed `notification_jobs` queue with save-first semantics and retry-until-delivered email behavior instead of inline route-level SMTP sends.
- 2026-04-10: Implemented `notification_jobs` with DB-backed retry state plus a background retry loop in `backend/main.py`, so failed Brandon-notification emails can continue retrying independently of new traffic.

## Integration Status
## Integration Status
- Gemini API: Key provided; using `gemini-1.5-pro` (pro) and `gemini-1.5-flash` (standard).
- Google OAuth/Calendar: OAuth client credentials are present, but as of 2026-04-10 Brandon still needs to complete the one-time Google consent to generate `GOOGLE_CALENDAR_REFRESH_TOKEN`.
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
- Real Google Calendar event creation is still blocked until Brandon completes the one-time OAuth connect flow and the backend receives a refresh token.
- As of 2026-04-10, the immediate `Access blocked` error on the Google Calendar connect flow is specifically caused by `redirect_uri_mismatch`: the backend is still generating the OAuth URL with the localhost callback because `GOOGLE_CALENDAR_REDIRECT_URI` is unset and falls back to `http://localhost:8000/api/v1/booking/calendar/callback`.
- The next required setup step is to point `GOOGLE_CALENDAR_REDIRECT_URI` at the real public backend callback and register that exact URI in the Google Cloud OAuth client.
- As of the later 2026-04-10 live booking verification, the redirect mismatch was fixed, but a separate persistence issue remained: the OAuth callback currently writes the Google Calendar refresh token into the container-local backend `.env`, which is not durable on Railway across deploys / instance changes.
- Local code now also stores the refresh token in the `settings` table and reloads it from DB before live calendar reads/writes, but that backend code still needs deployment and then one more Google reconnect to repopulate the durable token store.
- A real test Google event was accidentally created on Brandon's calendar for Monday, April 13, 2026 at 9:00 AM ET during the failed pre-migration booking attempt; that slot disappeared from availability even though the DB write failed.
- Booking emails are only sent after the full booking flow succeeds. So when live bookings fail earlier in the pipeline, Brandon will not receive any SMTP notification even if Gmail SMTP is configured correctly.
- Current email behavior also masks delivery failures: `_send_email()` returns `False` on SMTP failure, but the booking route does not check that return value, so the app does not currently surface email-delivery failure to the UI or API response.
- As of the notification-queue implementation on 2026-04-10, Brandon notifications no longer depend on inline route-level SMTP helpers in the new code path; they are queued and retried from `notification_jobs`. This still needs a backend deploy before production uses it.

## Admin Auth Notes
- As of 2026-04-10, the Brandon admin login issue was traced to seed drift: the `admin_users` row already existed in the live database with an older hash that did not match `changeme123!`.
- `backend/seed.py` now uses `ensure_admin_user(...)` to create the Brandon admin account if missing and also refresh the stored hash if the existing row no longer matches the expected seeded password.
- The connected database was reseeded on 2026-04-10, and a direct `/api/v1/auth/login` smoke test succeeded for `brandon@soldwithsweeney.com` with the seeded password from `seed.py`.

## Chatbot Architecture
- Chat widget is mounted globally from `frontend/src/components/layout/ClientWidgets.tsx`, so it appears across public pages.
- `backend/routers/chat.py` now returns structured chat payloads: `text`, `actions[]`, `widget`, plus backward-compatible `response`.
- `backend/services/gemini.py` instructs Gemini to return JSON and normalizes assistant actions into three allowed types: `send_message`, `navigate`, and `open_widget`.
- Legacy booking tags like `[BOOK_MEETING]` still work as a fallback and are normalized into `widget: 'calendar_picker'`.
- `frontend/src/hooks/useChat.ts` normalizes the structured API payload, preserves legacy booking fallback, and stores `actions` on assistant messages.
- `frontend/src/components/chat/ChatPanel.tsx` renders assistant messages as text bubbles with premium action buttons underneath and conditionally mounts `CalendarPickerCard` below a message when `widget === 'calendar_picker'`.
- `frontend/src/components/chat/CalendarPickerCard.tsx` remains the inline booking widget used by both direct widget replies and action-button triggered booking flows.
- Booking availability now enforces Monday-Friday `9 AM-6 PM` Eastern only, revalidates the selected slot against Brandon's live calendar before saving, and truthfully surfaces when Google Calendar still needs authorization.
- For in-person meetings, booking checks the locations on Brandon's neighboring calendar events and uses route-time estimates to hide infeasible travel slots.
- `/api/v1/chat/lead` exists, but the current chat frontend does not submit lead capture there.
- Current allowed navigate destinations are `/buy`, `/sell`, `/invest`, and `/about`.
- Generative UI is still best treated as a later-stage extension for multiple rich widget types; the implemented server-driven structured actions are the safer current fit.

## Calculator Notes
- Investor calculator now shows live numeric results before any lead gate. The gate is only for the deeper AI report generated from `/api/v1/investor/analyze`.
- Investor full-report gate now collects `name`, `email`, and `phone`, then renders AI explanation text, hold scenarios, exit-path commentary, and sensitivity cards once unlocked.
- Changing investor deal inputs after unlocking clears the prior full report so stale analysis is not shown.
- Investor calculator percentage inputs were corrected on 2026-04-10 to use human-entered percentages (`15`, `7`) instead of decimal fractions.
- Investor flip math now includes estimated closing costs in the instant snapshot and exposes `Holding Costs`, `Closing Costs`, and `Total Project Cost` cards. Current assumptions: `1.5%` buy-side closing costs and `1.25%` sell-side closing costs.
- Seller valuation tool now returns `calculation_id` from `backend/routers/evaluator.py`.
- Every seller valuation run is persisted as an analytics event with `event_type="seller_evaluator_calculation"` and includes the request inputs plus returned estimate in `metadata`.
- Seller feedback is now captured as a second analytics event with `event_type="seller_evaluator_rating"` linked back to the originating `calculation_id`.
- Current seller rating choices are:
  - `expected`
  - `under`
  - `above`

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
- Settings page Google Calendar card is dynamic as of 2026-04-10: it fetches live connection status, can open the Google Calendar OAuth flow, and supports status refresh after authorization.

## Last Session Context
- 2026-04-10: Wrote the durable notification queue design at `docs/superpowers/specs/2026-04-10-brandon-notification-queue-design.md`.
- 2026-04-10: Wrote the implementation plan at `docs/superpowers/plans/2026-04-10-brandon-notification-queue.md`.
- 2026-04-10: Implemented the notification queue itself, including route integrations for leads, chat leads, funnels, booking attempts, booking confirmations, seller evaluator usage, seller ratings, investor report requests, and investor calculator engagement.
- 2026-04-10: Hardened the notification queue so routes commit user actions and pending notification jobs before immediate delivery is attempted, which prevents Brandon from getting false-positive emails for rolled-back work.
- 2026-03-23: Fixed Railway Railpack/Caddy detection bug by adding root `railway.json` and modifying `backend/Dockerfile` for root context. Fixed missing phase images by force-adding to git. Verified backend health success.
- 2026-03-27: Analyzed chatbot flow, then implemented structured assistant actions/buttons in the chatbot with browser-verified action rendering and booking-widget launch.
- 2026-04-02: Applied About/Buy/Sell/home-page polish pass and removed the homepage hero headshot poster to fix the initial video flash.
- 2026-04-02: Added the provided Brandon and Paige gala image into `frontend/public/headshots/` and wired it into the About page.
- 2026-04-09: Home `TrustSection` now uses a two-card left review rail and includes a new Madison Levanti Google testimonial sourced from `reviews.html`.
- 2026-04-09: `frontend/src/components/buyer/BuyerMistakes.tsx` is now a rotating deck with auto-advance, hover-to-pause, and click-to-flip `Buyer Mistake` / `The Fix` states; browser automation verified both reorder and flip behavior.
- 2026-04-10: Added admin Google Calendar OAuth bootstrap endpoints and settings-page connect UI. Booking now truthfully blocks with a one-time authorization message until Brandon connects Calendar.
- 2026-04-10: Recalibrated seller valuation baselines so the Lowell smoke-test sample now returns roughly `$512k-$602k` instead of overshooting the local market band.
- 2026-04-10: Investor calculator now exposes its instant metrics up front and only gates the full AI report behind contact capture.
- 2026-04-10: Seller calculator now stores every calculation plus the follow-up expectation rating in the database through analytics events.
- 2026-04-10: Browser verification of the investor calculator was run against localhost with screenshots saved as `investor-instant-results-check.png` and `investor-full-report-check.png`.
- 2026-04-09: Revised `BuyerMistakes.tsx` again so the right side is now a single rotating hero card instead of four stacked cards, and removed the extra `Rotating Buyer Playbook` explainer panel.
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
- 2026-04-09: Fixed BuyerMistakes animation to slide purely upwards (y axis) instead of using rotateX.
- 2026-04-09: Refactored BuyerMistakes to move pagination dots to vertical alignment on the right edge of the card, moving from a top-horizontal layout.
- 2026-04-10: Mapped 'Style beds' staging checklist item to its respective interactive media.
- 2026-04-11: Updated the footer logo to use the new SWS Primary Logo White and Gold TRANSPARENT.
- 2026-04-11: Introduced interactive bio-panel hover images on the About page 'Built on Trust' section.
