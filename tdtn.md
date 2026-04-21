# Things Done Till Now

## Project: Brandon Real Estate AI Platform
Last Updated: 2026-04-20

### 2026-04-20 — Chat Booking Options + Same-Day Past Slot Filtering
- What was fixed: Restored all three booking format options in the chatbot booking flow and removed already-started same-day appointment times from availability.
- Files modified:
  - `frontend/src/components/chat/CalendarPickerCard.tsx`
  - `frontend/src/components/chat/ChatPanel.tsx`
  - `frontend/src/hooks/useChat.ts`
  - `backend/services/calendar_service.py`
  - `backend/tests/test_booking_calendar.py`
- Key decisions:
  - `Book Brandon` chat entry now opens the booking chooser in guided mode instead of forcing a phone-only next-available shortcut.
  - Renamed the video option to `Google Meet` so the three visible choices are `Phone Call`, `Google Meet`, and `In Person`.
  - Added a backend `_current_eastern_time()` helper so same-day slot generation can skip any slot whose start time is already at or before the current Eastern time.
  - Hardened booking validation so already-started appointment times are rejected even if a stale client somehow submits one.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest tests.test_booking_calendar -v` passed.
  - `frontend`: `npm run typecheck` passed.
  - Browser smoke test passed: homepage `Book Brandon` opened chat with `Phone Call`, `Google Meet`, and `In Person` buttons visible.
  - Backend slot-filter smoke check passed: with the clock pinned to `2:16 PM ET`, available phone slots started at `3:00 PM`.
- Status: Complete locally

### 2026-04-18 — Book Brandon CTA Opens Chatbot Booking Slots
- What was built: Updated booking CTAs so visitors are sent directly into the chatbot booking flow with Brandon's next available calendar slots.
- Files created:
  - `frontend/src/lib/booking-chat.ts`
  - `frontend/src/components/shared/BookBrandonCTA.tsx`
- Files modified:
  - `frontend/src/components/layout/Navbar.tsx`
  - `frontend/src/components/chat/ChatWidget.tsx`
  - `frontend/src/components/chat/ChatPanel.tsx`
  - `frontend/src/components/chat/CalendarPickerCard.tsx`
  - `frontend/src/hooks/useChat.ts`
  - `frontend/src/app/(main)/buy/page.tsx`
  - `frontend/src/app/(main)/about/page.tsx`
  - `frontend/src/components/seller/PropertyEvaluator.tsx`
  - `frontend/src/components/investor/MeetingGate.tsx`
- Key decisions:
  - Added a global `sws:open-booking-chat` client event so any CTA can open the persistent chat widget without prop-drilling through the layout.
  - Added a reusable `BookBrandonCTA` client wrapper for server-rendered pages that need to open chatbot booking.
  - Calendar picker now supports `next_available` mode, which searches from today forward and shows the first available phone-call slots immediately.
  - Left explicit `Call Direct` and `Call Brandon` phone links as phone links; only booking/strategy/valuation CTAs now launch the chatbot booking path.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - `frontend`: `npm run build` passed.
  - Browser smoke test passed: homepage `Book Brandon` opened the chatbot, showed the direct booking message, called `/api/v1/booking/available-slots`, and displayed next available slot buttons.
- Status: Complete locally

### 2026-04-18 — Frontend Vercel Typecheck Fix
- What was fixed: Resolved the deployment-blocking TypeScript errors from the About page and buyer journey component.
- Files modified:
  - `frontend/src/app/(main)/about/page.tsx`
  - `frontend/src/components/buyer/MonopolyJourney.tsx`
- Key decisions:
  - Kept the REALTOR® JSX formatting, but stopped using rendered JSX labels as React keys.
  - Added stable string ids for About-page bio chips and award cards.
  - Updated the buyer journey step type to allow rendered text and gave each step a stable string key.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - `frontend`: `npm run build` passed.
  - Build still logs non-fatal fallback warnings when the local backend content API is unavailable and the Instagram token is invalid.
- Status: Complete

### 2026-04-18 — Chatbot Booking Next Available Times
- What was built: Updated the chatbot calendar picker so an empty selected date no longer dead-ends the booking flow.
- Files modified:
  - `frontend/src/components/chat/CalendarPickerCard.tsx`
- Key decisions:
  - Reused the existing `/api/v1/booking/available-slots` endpoint so Google Calendar remains the source of truth.
  - When a selected date has no slots, the widget now scans the next 10 business days and shows up to 6 next available time options.
  - Suggested time buttons include both the date and time, and selecting one updates the booking confirmation date automatically.
  - In-person suggestions preserve the entered location and remain filtered by travel-time checks.
- Verification:
  - `frontend`: No `CalendarPickerCard.tsx` type errors were reported in the typecheck output.
  - `frontend`: The unrelated About-page and buyer journey type errors were fixed later on 2026-04-18.
- Status: Complete

### 2026-04-13 — Investor Calculator 80% Rule + Blank Inputs
- What was built: Updated the investor calculator's max-offer metric to an 80% rule and removed prefilled deal values so instant pricing only appears after visitors enter their own numbers.
- Files modified:
  - `frontend/src/lib/investor-calc.ts`
  - `frontend/src/components/investor/InvestorCalculator.tsx`
  - `frontend/src/components/investor/AnalysisResults.tsx`
- Key decisions:
  - Changed the offer cap formula from `ARV x 70% - rehab` to `ARV x 80% - rehab`.
  - Renamed the metric label to `80% Rule Offer Cap`.
  - Added helper copy explaining that the cap is a conservative max purchase offer, calculated as `ARV x 80% minus rehab`.
  - Confirmed the user's example now returns `$570,000 x 80% - $50,000 = $406,000`.
  - Converted the calculator inputs from prefilled numeric state to blank string state, with parsing only after all fields have valid values.
  - The instant snapshot and full-report gate now stay hidden until a complete set of deal inputs is entered.
- Verification:
  - `frontend`: direct calculator smoke check confirmed the offer cap is `$406,000` for the user's sample.
  - `frontend`: `npm run typecheck` passed.
- Status: Complete locally

### 2026-04-11 — Investor Calculator Short-Term Loan Fix
- What was built: Updated the investment calculator so one-year fix-and-flip style loans use interest-only debt service instead of being fully amortized over 12 months.
- Files created:
  - `backend/tests/test_investor_metrics.py`
- Files modified:
  - `backend/routers/investor.py`
  - `frontend/src/lib/investor-calc.ts`
  - `frontend/src/components/investor/AnalysisResults.tsx`
  - `frontend/src/components/investor/FlipCaseStudy.tsx`
- Key decisions:
  - Loan terms of 1-2 years are modeled as interest-only bridge / fix-and-flip debt.
  - Loan terms of 3+ years stay on the standard amortized payment formula.
  - The frontend now carries a `loanStructure` metric and explains the assumption under the flip-analysis cards.
  - Corrected the case-study percentage inputs from decimal-style values to the calculator's current percent-style inputs.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest tests.test_investor_metrics -v` first failed against the old one-year math (`$30,522.31/mo` vs expected `$2,057.71/mo`).
  - `backend`: `./.venv/bin/python -m unittest discover -s tests -v` passed with 32 tests.
  - `frontend`: `npm run typecheck` passed.
  - `frontend`: direct calculator smoke checks passed for both one-year interest-only and 30-year amortized scenarios.
- Status: Complete locally

### 2026-04-10 — Brandon Notification Queue Implemented
- What was built: Added a durable `notification_jobs` queue for Brandon-only internal email notifications, wired it into lead capture, chatbot lead capture, funnel registrations, booking attempts, booking confirmations, seller calculator activity, seller calculator ratings, investor full-report requests, and investor calculator engagement.
- Files created:
  - `backend/models/notification_job.py`
  - `backend/services/notification_service.py`
  - `backend/alembic/versions/7efdda0d6b65_add_notification_jobs.py`
  - `backend/tests/test_notification_service.py`
  - `backend/tests/test_leads_notifications.py`
  - `backend/tests/test_investor_notifications.py`
- Files modified:
  - `backend/alembic/env.py`
  - `backend/main.py`
  - `backend/routers/leads.py`
  - `backend/routers/chat.py`
  - `backend/routers/funnels.py`
  - `backend/routers/booking.py`
  - `backend/routers/evaluator.py`
  - `backend/routers/investor.py`
  - `backend/services/email_service.py`
  - `backend/tests/test_booking_calendar.py`
  - `backend/tests/test_evaluator_router.py`
  - `frontend/src/components/investor/InvestorCalculator.tsx`
- Key decisions:
  - Notifications now save to DB first as `notification_jobs` with status, attempts, next retry time, last error, and delivered timestamp.
  - Failed notification sends are kept and retried with escalating backoff instead of being silently dropped.
  - Added a background retry loop in `backend/main.py` so failed jobs continue retrying even without fresh user traffic.
  - Booking attempts are queued in a separate DB session before downstream booking work continues, so Brandon can still be notified of attempted bookings even if later calendar or booking persistence steps fail.
  - Booking confirmations now use the queue instead of direct inline SMTP calls.
  - Seller evaluator usage and ratings now both notify Brandon.
  - Investor report requests notify Brandon from the backend, and investor calculator engagement now sends a one-time event from the frontend per browser session with retry-on-failure.
  - Email rendering was centralized with explicit subjects for lead, funnel, chat, booking, seller calculator, and investor events.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest discover -s tests -v` passed (`30` tests).
  - `frontend`: `npm run typecheck` passed.
  - `backend`: `./.venv/bin/alembic upgrade head` succeeded, upgrading `0d8d9bce6f44 -> 7efdda0d6b65`.
- Deployment note:
  - The connected database now has the `notification_jobs` table, but the live Railway backend still needs these code changes deployed before production traffic will use the queue and retry loop.
- Status: Complete locally; ready to deploy

### 2026-04-10 — Brandon Notification Queue Spec + Plan Drafted
- What was written:
  - A notification-queue design spec for Brandon-only internal email alerts with durable retry-until-delivered behavior.
  - A detailed implementation plan covering the new `notification_jobs` model, queue service, route integrations, investor engagement endpoint, retry processing, and verification steps.
- Files created:
  - `docs/superpowers/specs/2026-04-10-brandon-notification-queue-design.md`
  - `docs/superpowers/plans/2026-04-10-brandon-notification-queue.md`
- Coverage included in the plan:
  - Standard leads
  - Funnel registrations
  - Chatbot lead capture
  - Booking attempts
  - Booking confirmations
  - Seller calculator usage
  - Seller calculator rating feedback
  - Investor full-report requests
  - Investor calculator engagement before contact capture
- Status: Planning complete; implementation not started yet in this plan phase

### 2026-04-10 — Booking Email Delivery Diagnosis
- What was analyzed: Investigated why Brandon did not receive a booking email even though SMTP is configured.
- Files reviewed:
  - `backend/routers/booking.py`
  - `backend/services/email_service.py`
  - `backend/config.py`
- Findings:
  - SMTP credentials themselves are not the primary blocker in the local environment; direct calls to `send_test_email()` and `notify_new_booking()` both returned `True`.
  - Booking notifications are only attempted at the very end of `create_booking(...)`, after:
    - calendar token load
    - slot validation
    - Google Calendar event creation
    - booking DB insert / refresh
  - Because the live booking flow had been failing before that point (`bookings.location` schema mismatch, then non-durable Google refresh-token persistence), Brandon would not get an email even if SMTP was perfectly configured.
  - The current code also hides email send failures:
    - `backend/services/email_service.py` catches SMTP exceptions and returns `False`
    - `backend/routers/booking.py` ignores that boolean return value and only logs exceptions
    - result: the API can appear successful even when Brandon never receives an email
  - The notification is sent from Brandon's own Gmail SMTP account to the same Brandon email address, which can make Gmail delivery less obvious in the inbox even when accepted by SMTP.
- Status: Diagnosed; no product-code change in this analysis pass

### 2026-04-10 — Live Chat Booking Verification + Booking Schema/Token Persistence Fix
- What was analyzed and fixed:
  - Ran a live production booking verification against the chatbot/booking endpoints after Google Calendar was reconnected.
  - Found that the live chatbot correctly returned the calendar widget, but the booking POST crashed because the production `bookings` table was missing the `location` column.
  - Added a new Alembic migration for `bookings.location`, applied it to the connected production database, and added cleanup logic so orphaned Google events are deleted if the DB save fails after calendar insertion.
  - Found a second production issue: the Google Calendar refresh token was only being written into the container-local `.env`, which is not durable on Railway across deploys / instance changes.
  - Added DB-backed refresh-token persistence helpers in the booking router so the OAuth callback also stores the token in the `settings` table, and booking/status/availability routes load the token from DB before calling Google Calendar.
- Files modified:
  - `backend/alembic/versions/0d8d9bce6f44_add_location_to_bookings.py`
  - `backend/routers/booking.py`
  - `backend/services/calendar_service.py`
  - `backend/tests/test_booking_calendar.py`
  - `backend/tests/test_booking_token_persistence.py`
- Live verification details:
  - `POST /api/v1/chat/` on the live Railway backend returned `widget: "calendar_picker"` for a booking request.
  - Before the schema fix, `POST /api/v1/booking/` failed with `UndefinedColumnError: column "location" of relation "bookings" does not exist`.
  - The first failed live booking attempt created a real Google Calendar event before the DB insert crashed, which removed the `2026-04-13 09:00 AM ET` slot from availability.
  - After applying the migration, the live database schema now includes `bookings.location`.
  - Repeated live availability / booking checks then showed `Google Calendar needs one-time authorization before Brandon can accept bookings.`, confirming the refresh token was not durably persisted in Railway.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest tests.test_booking_calendar -v` passed (`5` tests).
  - `backend`: `./.venv/bin/python -m unittest tests.test_booking_token_persistence -v` passed (`3` tests).
  - `backend`: `./.venv/bin/python -m unittest discover -s tests -v` passed (`16` tests) after the schema + cleanup changes.
  - `backend`: `./.venv/bin/alembic upgrade head` succeeded against the connected production database, upgrading `9c1fb48ea689 -> 0d8d9bce6f44`.
- Remaining external step:
  - After deploying the new DB-backed token-persistence code, Brandon will need to reconnect Google Calendar one more time so the refresh token is stored durably in the database instead of only the Railway container filesystem.
- Status: Local code fix complete, production DB migrated, still needs backend deploy + one reconnect to make live chatbot bookings reliable again

### 2026-04-10 — Google Calendar OAuth Access Blocked Diagnosis
- What was analyzed: Investigated why the Google Calendar connect flow shows `Access blocked` during Brandon's admin Settings authorization attempt.
- Files reviewed:
  - `backend/config.py`
  - `backend/services/calendar_service.py`
  - `backend/routers/booking.py`
  - `frontend/src/app/admin/settings/page.tsx`
  - `backend/tests/test_calendar_oauth.py`
  - `backend/.env.example`
- Root cause found:
  - The generated Google OAuth URL is using `http://localhost:8000/api/v1/booking/calendar/callback` as the redirect URI because `GOOGLE_CALENDAR_REDIRECT_URI` is not set in the backend environment and the app falls back to the localhost default in `backend/config.py`.
  - A direct repro against Google's OAuth endpoint returned `redirect_uri_mismatch`, which surfaces in the browser as `Access blocked` / `This app's request is invalid`.
- Verification:
  - Generated the live auth URL from `services.calendar_service.get_auth_url(...)`.
  - Parsed the outgoing OAuth query and confirmed `redirect_uri=http://localhost:8000/api/v1/booking/calendar/callback`.
  - Direct fetch of the Google OAuth URL finished at `https://accounts.google.com/signin/oauth/error?...authError=...redirect_uri_mismatch...`.
- Fix required:
  - Set `GOOGLE_CALENDAR_REDIRECT_URI` in the deployed backend environment to the real public backend callback URL.
  - Add that exact same callback URL to the OAuth client's Authorized redirect URIs in Google Cloud Console.
- Status: Diagnosed; no product code changed in this analysis pass

### 2026-04-10 — Admin Login Seed Resync Fix
- What was built: Fixed the admin seeding flow so Brandon's default admin account is not left with a stale password hash when the row already exists in the database.
- Files modified:
  - `backend/seed.py`
  - `backend/tests/test_seed_admin_user.py`
- Key decisions:
  - Added `DEFAULT_ADMIN_EMAIL` and `DEFAULT_ADMIN_PASSWORD` constants so the seed behavior is centralized.
  - Introduced `ensure_admin_user(...)` to handle both create and update cases for the admin account.
  - If the Brandon admin row already exists but its stored hash no longer matches the expected seeded password, the seed now rewrites the hash instead of silently leaving the stale credentials in place.
  - Ran the updated seed against the connected database so the live Brandon admin row was resynced immediately.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest tests.test_seed_admin_user -v` passed (`2` tests).
  - `backend`: direct database verification confirmed `pwd_context.verify("changeme123!", user.hashed_password) == True` for `brandon@soldwithsweeney.com`.
  - `backend`: direct ASGI smoke test to `POST /api/v1/auth/login` with Brandon's seeded credentials returned `200` and a bearer token.
- Root cause:
  - `seed.py` previously only created the admin user if it did not exist, so an older password hash in the live database could persist forever even though the seed file still advertised `changeme123!`.
- Status: Complete

### 2026-04-10 — Investor Preview Unlock Flow + Seller Expectation Ratings
- What was built: Reworked the investor calculator so live deal numbers are visible immediately and moved the contact gate to the deeper AI report only; also added a post-result expectation rating flow to the seller valuation tool and persisted every valuation calculation plus rating in the database.
- Files modified:
  - `backend/routers/evaluator.py`
  - `backend/tests/test_evaluator_router.py`
  - `frontend/src/components/investor/InvestorCalculator.tsx`
  - `frontend/src/components/investor/MeetingGate.tsx`
  - `frontend/src/components/investor/FullReportResults.tsx`
  - `frontend/src/components/investor/report-types.ts`
  - `frontend/src/components/seller/PropertyEvaluator.tsx`
- Key decisions:
  - Investor metrics now render live on the page with no blur/lock overlay.
  - The gated step is now specifically for the full AI report, which uses the existing `/api/v1/investor/analyze` backend endpoint and captures name/email/phone before requesting it.
  - Changing any investor input invalidates the unlocked full report so stale report copy is never shown against new deal numbers.
  - Fixed investor instant-math percentage handling so `Down Payment %` and `Interest Rate` now behave like real percentages (`15`, `7`) instead of requiring decimal fractions (`0.15`, `0.07`).
  - Updated investor flip math to include estimated closing costs and surfaced those assumptions directly in the UI.
  - Seller valuations now create a `seller_evaluator_calculation` analytics event on every run, regardless of whether the visitor leaves contact info.
  - Seller result view now asks one follow-up question with three responses:
    - `This is what I expected to get`
    - `This is under what I expected to get`
    - `This is more than what I expected to get`
  - Rating submissions are stored as linked `seller_evaluator_rating` analytics events keyed to the originating calculation id.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest discover -s tests -v` passed (`13` tests).
  - `frontend`: `npm run typecheck` passed.
  - `backend`: seller evaluator smoke test returned a live `calculation_id`.
  - `backend`: `POST /api/v1/evaluator/{calculation_id}/rating` returned `{"ok": true}`.
  - `backend`: `/api/v1/investor/analyze` logged `200 OK` during live smoke testing.
  - Browser test on `http://localhost:3000/invest` completed end-to-end with screenshots captured at:
    - `investor-instant-results-check.png`
    - `investor-full-report-check.png`
  - Using the user-provided flip scenario values, the instant snapshot produced:
    - `Estimated Profit`: `$78,799`
    - `Holding Costs`: `$14,081`
    - `Closing Costs`: `$13,350`
    - `Total Project Cost`: `$491,201`
- Known note:
  - The investor UI still does not take a property address as a direct input, so the user-provided `50 Cheever Ave, Dracut, MA 01826` address could not be entered into the calculator itself; the browser test used the provided financial inputs only.
- Status: Complete

### 2026-04-10 — Booking Hardening + Calendar OAuth Bootstrap + Seller Estimate Recalibration
- What was built: Hardened booking against Brandon's real calendar rules, added the missing one-time Google Calendar OAuth connect flow in admin settings, and recalibrated the seller estimate model to a more realistic local market band.
- Files modified:
  - `backend/.env.example`
  - `backend/config.py`
  - `backend/routers/booking.py`
  - `backend/routers/evaluator.py`
  - `backend/services/calendar_service.py`
  - `backend/services/evaluator_service.py`
  - `backend/services/maps_service.py`
  - `frontend/src/app/(main)/sell/page.tsx`
  - `frontend/src/app/admin/settings/page.tsx`
  - `frontend/src/components/chat/CalendarPickerCard.tsx`
  - `backend/tests/test_booking_calendar.py`
  - `backend/tests/test_calendar_oauth.py`
  - `backend/tests/test_evaluator_service.py`
- Key decisions:
  - Booking hours are now enforced as Monday-Friday, 9 AM-6 PM Eastern with slot revalidation at booking time.
  - In-person meetings continue to use neighboring calendar-event locations plus travel-time checks, with OSRM fallback when Google Maps is unavailable.
  - Added admin calendar endpoints for status, auth URL generation, and OAuth callback so Brandon can connect Google Calendar without hand-editing env vars.
  - OAuth callback persists `GOOGLE_CALENDAR_REFRESH_TOKEN` into `backend/.env` and updates runtime settings so the current server process can start using it immediately.
  - Settings page Google Calendar card is now dynamic and can start or refresh the connection flow instead of showing a static placeholder.
  - Seller pricing baselines were recalibrated so Lowell-area single-family estimates no longer overshoot the current local market band.
- Verification:
  - `backend`: `./.venv/bin/python -m unittest discover -s tests -v` passed (`10` tests).
  - `frontend`: `npm run typecheck` passed.
  - `backend`: `GET /api/v1/booking/calendar/status` returns `configured: true`, `connected: false`, `can_connect: true` when Brandon still needs OAuth.
  - `backend`: `GET /api/v1/booking/calendar/auth-url` returns a valid Google OAuth URL with offline access, consent prompt, and signed state.
  - `backend`: direct request to the Google OAuth URL returned `HTTP 302`, confirming handoff to Google.
  - `backend`: booking endpoints now return `Google Calendar needs one-time authorization before Brandon can accept bookings.` until the real Calendar consent is completed.
  - `backend`: seller evaluator smoke test for `50 Cheever Ave, Lowell, MA 01852` returned `$512,000-$602,000`.
- Blocker:
  - Live event creation in Brandon's actual Google Calendar still requires Brandon to complete the one-time Google consent so the app can receive a refresh token.
- Status: Complete in code; waiting on external Google authorization to finish true live booking

### 2026-03-19 — Project Initialized
- What was built: Git repo, project config files (claude.md, tdtn.md, memory.md, .gitignore, .env.example)
- Files created: .gitignore, claude.md, tdtn.md, memory.md, .env.example, BRANDON_RE_SPEC.md committed
- Key decisions: Using #0a0a0a near-black (taste-skill: NO pure #000000), Neon PostgreSQL for DB
- Status: Complete

### 2026-03-19 — Task 14: Buyers Experience Page
- What was built: Full `/buy` page route with hero, MonopolyJourney accordion, team section, BuyerMistakes grid, reviews 2x2, and lead capture form
- Files created: `frontend/src/app/buy/page.tsx`, `frontend/src/components/buyer/MonopolyJourney.tsx`, `frontend/src/components/buyer/BuyerMistakes.tsx`
- Files modified: `frontend/src/components/shared/LeadCaptureForm.tsx` — added `source`, `leadType`, `ctaText` props
- Key decisions: Used `DeviceMobile` Phosphor icon (not `Smartphone` which doesn't exist in this package version); Phosphor SSR import used in Server Component page; accordion opens Phase 1 by default
- Status: Complete — TypeScript clean, committed d6ae4f7

### 2026-03-19 — Task 17: About Brandon Page
- What was built: Full About page at /about with 7 sections
- File created: frontend/src/app/about/page.tsx (996 lines)
- Sections: Hero (split layout + headshot), Stats strip (4 glass cards), Bio deep-dive (sticky image + 3 glassmorphism panels), Designations & Memberships (5 logos + 2 award cards), MS is BS New England (story panel + $300K stat + external CTA), Team (SWS TEAM photo), Contact/CTA (Phone/EnvelopeSimple/MapPin icons, Book a Call button)
- Key decisions: 7 sub-section components composed in single page.tsx; useInView per-section stagger; external links use <a target="_blank">; REALTOR® with ® in all occurrences; no emojis anywhere
- TypeScript: 0 errors
- Status: Complete — committed 071a647

### 2026-03-20 — Task 20: Admin Sub-Pages
- What was built: 5 admin pages — leads, content, funnels, analytics, settings
- Files created:
  - `frontend/src/app/admin/leads/page.tsx` — leads table with filter pills, status badges, inline detail panel with PATCH status/notes
  - `frontend/src/app/admin/content/page.tsx` — content blocks grid, inline edit/save/cancel with PUT
  - `frontend/src/app/admin/funnels/page.tsx` — funnels table, publish action, copy link with 2s feedback, create form with AI loading state
  - `frontend/src/app/admin/analytics/page.tsx` — stats strip, top pages/events with bar visualization, recent events table
  - `frontend/src/app/admin/settings/page.tsx` — integrations status cards, admin password form (coming soon), site info card
- Key decisions: All pages use admin_token guard; loading skeletons via animate-pulse; empty + error states with Phosphor icons; no emojis
- TypeScript: 0 errors
- Status: Complete — committed 612de2e

### 2026-03-20 — Task 22: Frame Extraction Pipeline & Video Compression
- What was built: Frame extraction pipeline for ExplodingHouseScroll + aerial drone video compression
- Videos found at: `frontend/public/assets/` (not `videos/` — actual location differs from task spec)
- ffmpeg: Available at `/opt/homebrew/bin/ffmpeg` v8.0.1
- Frames extracted: 60 WebP frames at `frontend/public/frames/frame_001.webp`–`frame_060.webp` (12fps, 1920px wide, quality 85)
- Frames also extracted as JPEG: 60 frames at `frontend/public/frames/house-blast/frame_0001.jpg`–`frame_0060.jpg` (matches ExplodingHouseScroll.tsx component path)
- Video compressed: `aerial_drone_shot.mp4` compressed from 13MB → 3.2MB (75% reduction, H.264 CRF 28, faststart, no audio)
- Scripts created: `scripts/extract-frames.sh`, `scripts/compress-videos.sh` (both chmod +x)
- Gitignore: `frontend/public/frames/.gitignore`, `frontend/public/frames/house-blast/.gitignore`, root `.gitignore` updated
- Key decisions: house_blast.mp4 is 5s at 24fps (121 frames total); used fps=12 filter to get exactly 60 frames; JPG format used for component path compatibility (house-blast/)
- Status: Complete

### 2026-03-23 — Deployment Fixes & Model Updates
- What was built: Resolved Railway deployment issues, fixed Instagram build error, and updated Gemini models.
- Files modified:
  - `backend/services/gemini.py`: Updated models to `gemini-1.5-pro` (for pro tasks) and `gemini-1.5-flash` (standard).
  - `frontend/src/app/(main)/page.tsx`: Changed Instagram fetch error to `console.warn` to prevent build failures on expired tokens.
  - `backend/Dockerfile`: Updated to use dynamic `PORT` and root build context for Railway compatibility.
  - `railway.json`: Created at root to force Docker builder and bypass Railpack/Caddy detection.
- Force-added: `frontend/public/frames/phase-1-swiping.jpg`, `phase-2-touring.jpg`, `phase-3-keys.jpg` (previously gitignored).
- Key decisions: Using explicit `railway.json` to force Docker; switched to dynamic `$PORT` for Railway edge routing; enabled `PYTHONUNBUFFERED=1` for live logs.
- Status: Complete

### 2026-03-27 — Chatbot Architecture Analysis
- What was analyzed: End-to-end chatbot flow across frontend widget, React chat state, FastAPI chat router, Gemini service, and inline booking widget behavior.
- Files reviewed: `frontend/src/components/layout/ClientWidgets.tsx`, `frontend/src/components/chat/ChatWidget.tsx`, `frontend/src/components/chat/ChatPanel.tsx`, `frontend/src/components/chat/CalendarPickerCard.tsx`, `frontend/src/hooks/useChat.ts`, `backend/routers/chat.py`, `backend/services/gemini.py`, `backend/routers/booking.py`
- Key findings:
  - Chat is mounted site-wide via `ClientWidgets` and is entirely client-side on the frontend.
  - Backend chat API currently returns only `{ response: string }`; there is no structured UI payload.
  - Frontend only upgrades one special case today: booking tags like `[BOOK_MEETING]` are stripped from text and converted into the inline `CalendarPickerCard`.
  - Assistant message bubbles render plain text only; there is no support for per-message actions, chips, cards, or routed CTAs.
  - `/api/v1/chat/lead` exists for chatbot lead capture, but the current frontend does not call it.
  - `showBooking` state exists in `useChat` but is not used by the rendered UI beyond being toggled.
- Recommendation:
  - Best next step is a structured assistant response contract such as `text + actions + widget`, then render actions as buttons in the chat bubble.
  - Avoid heuristic parsing of plain prose into buttons.
  - Full free-form generative UI is not the best first move for the current buy/sell/invest/book flows; a bounded server-driven UI layer is lower risk and fits the current architecture better.
- Status: Complete — analysis only, no product code changed

### 2026-03-27 — Chatbot Structured Actions Upgrade
- What was built: Replaced the plain-text-only chatbot contract with a structured assistant payload supporting `text`, `actions[]`, and `widget`, then rendered those actions as premium in-chat buttons.
- Files modified:
  - `backend/services/gemini.py`: Updated chatbot instructions to return JSON, added structured response parsing, action normalization, widget normalization, legacy booking-tag fallback, and discovery-action fallback logic.
  - `backend/routers/chat.py`: Expanded chat API response model to include `text`, `actions`, `widget`, and backward-compatible `response`.
  - `frontend/src/hooks/useChat.ts`: Added frontend action/widget types, normalized structured API payloads, preserved legacy booking-tag fallback, and attached actions to assistant messages.
  - `frontend/src/components/chat/ChatPanel.tsx`: Rendered assistant actions as glassmorphism buttons, added action click handling for chat replies, page navigation, and booking widget launch.
- UX behavior now supported:
  - AI can return tappable `send_message` actions that continue the conversation.
  - AI can return `navigate` actions to `/buy`, `/sell`, `/invest`, and `/about`.
  - AI can return `open_widget` or top-level `widget` instructions for the inline booking calendar.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - `backend`: `python -m py_compile backend/routers/chat.py backend/services/gemini.py` passed.
  - API smoke test: `POST /api/v1/chat/` returned structured actions for “What can you help me with?”
  - Browser test: Opened chat on `http://localhost:3000`, sent “What can you help me with?”, confirmed four rendered action buttons, clicked `Buy a home`, confirmed follow-up response with new actions, clicked `Book a call`, confirmed inline calendar widget opened.
  - Screenshots captured: `chat-structured-actions.png`, `chat-action-booking-widget.png`
- Known verification note:
  - `npm run lint` still fails on a pre-existing unrelated error in `frontend/src/components/shared/RotatingText.tsx` (`no-explicit-any`) plus several unrelated warnings.
- Status: Complete

### 2026-04-02 — About / Buy / Sell / Home Polish Pass
- What was built: Implemented requested copy and UI refinements across the About, Buy, Sell, and home pages, including a buyer flashcard experience and a fix for the homepage hero video showing Brandon's face before playback.
- Files modified:
  - `frontend/src/app/(main)/about/page.tsx`
  - `frontend/src/app/(main)/buy/page.tsx`
  - `frontend/src/app/(main)/sell/page.tsx`
  - `frontend/src/components/buyer/BuyerMistakes.tsx`
  - `frontend/src/components/home/GivingBack.tsx`
  - `frontend/src/components/home/Hero.tsx`
- About page changes:
  - Changed the hero image badge separator so `|` renders in white.
  - Reworked the stats strip so the cards tie directly to Brandon-specific milestones instead of generic stats.
  - Expanded awards coverage with added recognition cards for MAR Good Neighbor, NEAR Good Neighbor, and Distinguished Young Professional.
  - Updated team/contact copy to use `the Sold With Sweeney & Co. team`.
  - Replaced `research` with `advocacy` in the MS fundraising copy.
- Buy / Sell changes:
  - Added a new Buy-page CTA: `Find "THE ONE"` with a downward scroll target.
  - Changed the buyer lead-section headline gold text from `Dream Home` to `THE ONE`.
  - Converted the buyer mistakes section into interactive flip-style flashcards for clearer reading.
  - Changed the seller lead-section headline to `Stop Listing. Start Moving.`
- Home page changes:
  - Removed the hero video poster image that used Brandon's headshot.
  - Added a dark fallback background and fade-in behavior until the video is loaded, preventing the initial headshot flash.
  - Updated Giving Back copy from `research` to `advocacy`.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - Route checks via `curl` confirmed the updated About, Buy, Sell, and home-page markup.
  - Home page hero markup no longer includes a `poster` attribute, and now renders a preload + fade-in fallback state.
- Blocker:
  - The repo does not currently include the requested `Brandon and Paige at Maine gala` image or an awards-collage image, so those two image swaps could not be completed from local assets.
- Known verification note:
  - `npm run lint` still fails on the pre-existing unrelated `frontend/src/components/shared/RotatingText.tsx` `no-explicit-any` error plus older warnings in unrelated files.
- Status: Complete with image-asset blocker noted

### 2026-04-09 — Buyer Mistakes Single-Card Revision
- What was built: Simplified the Buy-page `What Most Buyers Get Wrong` experience from a four-card deck into one rotating hero card.
- Files modified:
  - `frontend/src/components/buyer/BuyerMistakes.tsx`
- Implementation details:
  - Removed the `Rotating Buyer Playbook` explainer panel entirely.
  - Reworked the right column to render a single cinematic card that auto-advances to the next buyer mistake every 4.2 seconds.
  - Kept click-to-flip behavior so the active card still toggles between `Buyer Mistake` and `The Fix`.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - Browser automation confirmed the active card rotates from `Shopping before pre-approval` to `Using all your savings for the down payment`.
  - Browser automation confirmed clicking the rotated card flips it into `The Fix`.
  - Screenshots refreshed: `buy-mistakes-rotating-initial.png`, `buy-mistakes-rotating-flipped.png`
- Status: Complete

### 2026-04-09 — Home Reviews + Buyer Mistakes Motion Refresh
- What was built: Filled the blank space in the home-page reviews rail by stacking two reviews on the left and rebuilt the Buy-page `What Most Buyers Get Wrong` section into a rotating flip-card deck.
- Files modified:
  - `frontend/src/components/home/TrustSection.tsx`
  - `frontend/src/components/buyer/BuyerMistakes.tsx`
- Implementation details:
  - Added a new non-duplicate Google review from `reviews.html` by Madison Levanti and changed the home testimonials layout to a 2-left / 3-right composition.
  - Reworked the buyer mistakes module into a premium two-column section with a timed upward rotation, hover-to-pause behavior, and click-to-flip cards that switch between `Buyer Mistake` and `The Fix`.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - Browser automation confirmed the home reviews now render both left-rail testimonials including Madison Levanti.
  - Browser automation confirmed the buyer deck reorders over time:
    - Before: `Shopping before pre-approval` → `Using all your savings for the down payment` → `Buying with the listing agent` → `Picking a lender based on rate alone`
    - After rotation: `Using all your savings for the down payment` → `Buying with the listing agent` → `Picking a lender based on rate alone` → `Shopping before pre-approval`
  - Browser automation also confirmed clicking a card flips it to `The Fix`.
  - Screenshots captured: `home-reviews-two-left.png`, `buy-mistakes-rotating-initial.png`, `buy-mistakes-rotating-flipped.png`
- Status: Complete

### 2026-04-10 — Brandon Notification Queue Hardening
- What was built: Tightened the new Brandon notification queue so user actions commit before immediate email delivery is attempted.
- Files modified:
  - `backend/services/notification_service.py`
  - `backend/routers/leads.py`
  - `backend/routers/chat.py`
  - `backend/routers/funnels.py`
  - `backend/routers/booking.py`
  - `backend/routers/evaluator.py`
  - `backend/routers/investor.py`
  - `backend/tests/test_booking_calendar.py`
  - `backend/tests/test_evaluator_router.py`
  - `backend/tests/test_investor_notifications.py`
  - `backend/tests/test_leads_notifications.py`
- Implementation details:
  - Route integrations now commit the saved lead, booking, calculator event, or rating plus its pending notification job before any immediate send pass runs.
  - `enqueue_notification_in_new_session()` now persists the pending job first and only then triggers the retry worker path.
  - Notification email table rendering now HTML-escapes payload content before composing Brandon-facing emails.
- Verification:
  - `backend`: `./.venv/bin/alembic upgrade head` passed.
  - `backend`: `./.venv/bin/python -m unittest discover -s tests -v` passed with 30 tests.
  - `frontend`: `npm run typecheck` passed.
- Status: Complete

### 2026-04-02 — About Gala Image Swap
- What was built: Replaced the About page's lower team image with the provided Brandon and Paige at Maine gala photo.
- Files modified:
  - `frontend/src/app/(main)/about/page.tsx`
- Files added:
  - `frontend/public/headshots/brandon-and-paige-maine-gala.jpeg`
- Implementation details:
  - Updated the About page `TeamSection` image source to the new gala asset.
  - Changed the image framing to a portrait-friendly `4/5` aspect ratio for better crop behavior.
  - Updated the image alt text to `Brandon and Paige at the Maine gala`.
- Verification:
  - `frontend`: `npm run typecheck` passed.
  - Route check confirmed `/about` references the new image asset.
  - Screenshot captured: `about-gala-update-check.png`
- Status: Complete

*Claude Code: Update this file after completing every task.*

### 2026-03-31 — Invest & Sell Hero Videos
- What was built: Updated Invest and Sell pages to use new, watermark-free MP4 videos.
- Files modified: `frontend/src/app/(main)/invest/page.tsx`, `frontend/src/app/(main)/sell/page.tsx`
- Key decisions: Copied the downloaded MP4 files to `frontend/public/videos/invest_hero.mp4` and `sell_hero.mp4`. Fixed catastrophic parsing errors caused by curly quotes in the Invest page testimonial array.
- Status: Complete

### 2026-03-31 — Audience Cards Video Backgrounds
- What was built: Updated AudienceCards component on the home page to use looping video backgrounds.
- Files modified: `frontend/src/components/home/AudienceCards.tsx`
- Key decisions: Extracted `video` field into the `cards` data array (Buy: `black_gold.mp4`, Sell: `sell_hero.mp4`, Invest: `invest_hero.mp4`). Replaced the `<Image>` tags with `<video>` tags for the cards.
- Status: Complete

### 2026-03-31 — Marketing Dyson Sphere
- What was built: Developed a cinematic 3D interactive WebGL dyson sphere for the "Your Home, Everywhere" sell page section.
- Files created: `frontend/src/components/sell/MarketingSphere.tsx`
- Files modified: `frontend/src/app/(main)/sell/page.tsx`
- Key decisions: Ported raw vanilla Three.js into a React `useRef` based component inside Next.js rather than using R3F to precisely save the custom global canvas texture loop logic. Dynamically draws user's provided PNG logos (`/facebook_logo.png`, etc.) onto the WebGL nodes instead of just vectors. Added rigorous React unmout disposal to prevent memory leaks.
- Status: Complete
Completed Checklist Video Integration
  - Fixed BuyerMistakes animation to slide purely upwards (y axis) instead of using rotateX, addressing user complaint about sliding sideways.
  - Updated BuyerMistakes UI: moved the top horizontal pagination strip into a vertical alignment flush to the right edge with the index number stacked underneath.
  - Mapped the 'Style beds' staging checklist item on the /sell page to the newly added video.
  - Removed video file exclusions from .gitignore and pushed all previously ignored videos/frames to the repo origin.
  - Replaced the primary logo in the Footer with the new designated SWS Primary Logo White and Gold TRANSPARENT asset.
  - Added interactive hover states to the 'Built on Trust' section on the About page that dynamically swaps the side headshot based on the active bio panel.
  - Updated text split and display for the 'REALTOR Of The Year' statistic in the About section.
  - Added 'imageClassName' visibility filters to the designation logos on the Home page (TrustSection) to match the high-contrast look from the About page.
  - Converted the static team image in the About page Team Section into an interactive 4500ms cross-fading carousel.
  - Converted the marketing node network on the Sell page (MarketingSphere) entirely to true 3D extruded SVGs.
  - Fixed MarketingSphere Instagram and Homes.com node colors, swapped generic icons, and fixed text sprite rotations to always face downwards.
  - Swapped Instagram SVG to Phosphor to fix ExtrudeGeometry solid-blob bug.
