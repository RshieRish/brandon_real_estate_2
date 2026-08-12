# Project Memory

## Architecture Decisions
- 2026-08-12: `/admin/command` implementation lives on isolated branch `feat/command-workspace`. Its first committed slice (`a7ccf66`) adds internal CRM SQLAlchemy models rather than replacing legacy lead data. Contacts link to `leads.id`; agreements are internal lifecycle records, not legal DocuSign execution.
- 2026-08-12: Command now has live internal API-backed workspaces for contacts, tasks, Smart Plans, opportunities, agreements, and listings, plus connected entrypoints into existing Content/Funnels/Analytics. Sweeney AI is a deterministic, review-required internal briefing endpoint; it does not take actions or send CRM data to an external platform.
- 2026-08-12: The configured PostgreSQL database was migrated through Command revision `f3a91c2d7e10`; all new Command tables now exist without altering legacy records.
- Next.js App Router: SSR + static pages, no API routes (UI only)
- FastAPI backend: all AI, DB, business logic
- Gemini flash for chatbot speed; Gemini pro for complex analysis
- Neon PostgreSQL for launch
- 2026-04-10: Approved direction for Brandon internal notifications is a DB-backed `notification_jobs` queue with save-first semantics and retry-until-delivered email behavior instead of inline route-level SMTP sends.
- 2026-04-10: Implemented `notification_jobs` with DB-backed retry state plus a background retry loop in `backend/main.py`, so failed Brandon-notification emails can continue retrying independently of new traffic.
- 2026-05-12: Auto-blog posting runs as a second in-process asyncio loop in `backend/main.py` (`_blog_auto_post_loop`), gated by `BLOG_AUTO_POST_ENABLED` and paced by `BLOG_AUTO_POST_INTERVAL_HOURS` (default 72h). Restart-safe via a `MAX(created_at) WHERE is_posted` check before every post. Existing HTTP `/api/v1/blog/cron` endpoint still works for ad-hoc admin triggering.
- 2026-05-12: Blog Gemini stages use `gemini-3-flash-preview` (research), `gemini-3-pro-preview` (writing), `gemini-3-pro-image-preview` (cover image). All three are valid against the prod API key — confirmed via direct `models?key=…` listing and live `generateContent` calls. Do **not** "fix" these to `gemini-3.1-*` to match `services/gemini.py`; they are intentionally distinct models.
- 2026-05-14: Cover-image upload requires the six `R2_*` env vars (`R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_PUBLIC_URL`, `R2_REGION`) on **both** local AND Railway. Local had them; Railway didn't until 2026-05-14 — that's why every Railway-generated post landed without a cover image until the fix. Diagnostic surfaces kept in place: `POST /api/v1/blog/admin/test-image` (admin JWT) returns `{image_url, error, took_ms, r2_configured, r2_endpoint_set, r2_public_url_set}`; `blogs.image_gen_error TEXT` column captures the failure reason of every auto-post that has `image_url IS NULL`. Use these first whenever a blog ships without a hero.

## Integration Status
## Integration Status
- Gemini API: Key provided; using `gemini-1.5-pro` (pro) and `gemini-1.5-flash` (standard).
- Google OAuth/Calendar: OAuth client credentials are present, but as of 2026-04-10 Brandon still needs to complete the one-time Google consent to generate `GOOGLE_CALENDAR_REFRESH_TOKEN`.
- Instagram: Access token prone to expiration; frontend handles fetching failure gracefully.
- Railway Backend: Docker builder forced via `railway.json`. Uses dynamic `$PORT` and root context.
- 2026-05-31: Local Railway work for the Sold With Sweeney deployment should use `scripts/railway-sweeney ...`, which sources the gitignored `.env.railway-sweeney.local` project token for `enchanting-perception` (`aa6c9f9c-46d4-4f5d-b529-86b073de4972`) without changing the global `railway login` for `rishabnandibusiness@gmail.com`. The verified production service is `extraordinary-prosperity` (`85541f63-2aa1-4679-8114-98895f4bf215`); use `--service extraordinary-prosperity` for service-scoped commands when the CLI says no service is linked. Do not run `railway login` for `soldwithsweeneyfordeployment@gmail.com` on this machine unless intentionally replacing the global login.
- 2026-06-01: Approved architecture for Brandon AI / Atlas assistant is same Railway project, separate Hermes service. Keep Hermes under `enchanting-perception` as `atlas-agent` (or `brandon-hermes` if name availability requires), and let it control the existing backend only through explicit `/api/v1/agent-control/*` endpoints protected by `AGENT_CONTROL_TOKEN` and audit logging. First slice is read-only status/actions/recent leads/recent bookings; no Gmail/Calendar/Drive/CRM/outbound autonomy until later specs.
- 2026-06-01 implementation note: FastAPI now has a read-only agent-control bridge guarded by `AGENT_CONTROL_ENABLED` and `AGENT_CONTROL_TOKEN`. Routes are `/api/v1/agent-control/status`, `/actions`, `/leads/recent`, and `/bookings/recent`; lead/booking responses mask email/phone and booking summaries expose `has_google_event` instead of `google_event_id`. Audit rows use `agent_action_audits`. Hermes deployment instructions live in `docs/deployment/hermes-railway.md`.
- Vercel Frontend: Requires `NEXT_PUBLIC_API_URL` to match Railway domain.

## Content Status
- Videos: Available in public/assets/
- Headshots: Available in public/headshots/
- Logos: Available in public/logos/
- House blast frames: DONE (Task 22) — 60 WebP at frames/frame_001.webp, 60 JPEG at frames/house-blast/frame_0001.jpg
- Bio/reviews: In BRANDON_RE_SPEC.md Section 14

## Known Issues
- As of 2026-05-19, production blogs are down because the Railway blog API cannot connect to Neon: the live response says the Neon account/project exceeded compute time quota, and the DB connection should use `sslmode=require`. `/blog` depends on `GET /api/v1/blog/?limit=50`, while `/blog/[slug]` returns 404 when the server-side blog fetch fails. The local Neon host is `ep-tiny-firefly-ankqqw49-pooler.c-6.us-east-1.aws.neon.tech` (`neondb`, `neondb_owner`); use `ep-tiny-firefly-ankqqw49` to match the project/endpoint in Neon or Railway. That host still resolves and Railway gets a Neon-origin quota error, so the endpoint exists/routes in Neon rather than being moved elsewhere. Strongest local account candidate is `millergid9@gmail.com`: Chrome Profile 13 signed into Neon, opened org `org-long-bread-73501543` / project `nameless-credit-95836299?database=neondb`, and the exact `ep-tiny-firefly-ankqqw49` URL was pasted into the Brandon project chat about one minute later. This is high-confidence local forensic evidence, not server-side Neon ownership proof. Restore/upgrade Neon compute, add SSL mode to Railway `DATABASE_URL`, restart backend, then verify the blog list and a known slug.
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
- The connected database was reseeded on 2026-04-10, and a direct `/api/v1/auth/login` smoke test succeeded for the seeded admin account from `seed.py`.

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
- 2026-08-12: The approved next product surface is a new fully data-backed `/admin/command` route alongside the existing admin UI. It must use FastAPI/PostgreSQL as the source of truth and preserve existing lead, booking, funnel, content, and analytics records instead of duplicating them. The approved design is at `docs/superpowers/specs/2026-08-12-command-workspace-design.md`. It includes CRM Contacts, Tasks, Smart Plans, Opportunities, Marketing, internal Agreement/Templates/files, Reports, Listings/Search/Map, Websites, and server-side compliant/auditable AI actions. The interaction model uses the archived Command UI layouts, but branding must remain Sold With Sweeney & Co. and must not copy Keller Williams branding. Internal agreement lifecycle tracking is approved; real DocuSign API and legally binding in-house signatures are not in first release.
- 2026-04-21: Reviewed the live spec + implementation to produce a current feature inventory for the app, including chatbot, booking, funnels, analytics, admin tools, scroll/video experiences, and the Zapier-based KW Command CRM handoff.
- 2026-04-21: CRM integration should be described as a Zapier webhook flow rather than a direct Keller Williams API integration.
- 2026-04-21: The booking system description should explicitly mention Google Maps travel-time checks for in-person meetings so only feasible time slots are shown based on Brandon's surrounding calendar commitments and the requested location.
- 2026-04-21: The homepage hero eyebrow badge now reads `Northeast Association of REALTORS® Realtor Of The Year 2025` per the latest copy request.
- 2026-04-21: Hardcoded Sold With Sweeney email references now use `info@soldwithsweeney.com`, including public contact copy, internal notification recipient defaults, and the seeded default admin email.
- 2026-04-20: The chatbot booking chooser label was changed from `Google Meet` back to `Video Call`, and the guided booking prompt copy was updated to match.
- 2026-04-20: `Book Brandon` now opens the chatbot in guided booking mode again, with `Phone Call`, `Video Call`, and `In Person` visible before slot selection.
- 2026-04-20: Same-day booking availability now filters out any slot whose start time is already past in Eastern time, and booking validation rejects already-started times server-side too.
- 2026-04-18: Book Brandon CTAs now open the persistent chatbot directly into a `next_available` calendar picker mode; a browser smoke test confirmed the homepage CTA opened chat and displayed live next available slot buttons from `/api/v1/booking/available-slots`.
- 2026-04-18: Fixed the Vercel frontend typecheck blocker by replacing JSX-derived React keys in the About page with stable string ids and typing buyer journey steps as `ReactNode`; `npm run typecheck` and `npm run build` both pass locally.
- 2026-04-18: Updated the chatbot booking calendar card so if Brandon has no availability on the selected date, it scans the next 10 business days and displays up to 6 next available time options.
- 2026-04-13: Updated the investor calculator offer cap from 70% to 80%, renamed the card to `80% Rule Offer Cap`, and removed prefilled deal values so the instant snapshot and full-report gate only appear after users enter a complete deal.
- 2026-04-11: Fixed the investor calculator short-term loan bug. Terms of 1-2 years now model interest-only bridge / fix-and-flip debt, while 3+ year terms stay amortized; regression coverage lives in `backend/tests/test_investor_metrics.py`.
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
- 2026-04-11: Updated text split layout for 'REALTOR Of The Year' statistic on the About page.
- 2026-04-11: Aligned visibility styling for designation logos in the home page TrustSection with the About page.
- 2026-04-11: Updated the About page team image to an animated carousel featuring 3 team shots.
- 2026-04-11: Implemented SVGLoader and ExtrudeGeometry for all nodes on the MarketingSphere on the Sell page, making them true 3D.
- 2026-04-11: Fixed SVG colors in MarketingSphere and correctly aligned node text sprites to the global Y axis.
- 2026-04-28: Added Cookie Consent component to the main layout which persists consent state in localStorage.
- 2026-04-28: Added a silent client-side IP-based location check to the homepage Hero component (via geojs.io) that switches the background video to the high-res Dracut Drone video if the user's city is strictly 'Dracut', and 'Andover_drone.mp4' if the city is 'Andover'.
- 2026-05-10: Added 4-strategy investor toggle (Buy & Hold / STR / Flip / BRRRR) at top of /invest with URL sync via ?strategy=. Each strategy has its own input field set, default values, and result panel layout.
- 2026-05-10: Added RentalAnalyzerModal that estimates monthly rent (LTR) or nightly rate (STR) from condition + upgrade heuristics layered on top of RentCast's AVM. New backend route POST /api/v1/investor/estimate-rent.
- 2026-05-10: Refactored frontend/src/lib/investor-calc.ts into a discriminated union with 4 calc functions (calculateBuyHoldMetrics / calculateStrMetrics / calculateFlipMetrics / calculateBrrrrMetrics). All exhaustively type-checked.
- 2026-05-10: Added Vitest to frontend (no test framework existed before). 31 unit tests covering all 4 strategies + parseInputs gate.
- 2026-05-10: Calibrated STR market multipliers against AirDNA/AirROI/Rabbu — Tourist 2.0× (was 3.0×), Urban 1.3× (was 2.4×), Suburban 1.2× (was 1.8×). Initial multipliers were peak-season optimistic; new values match annualized data. Calibration appendix documented in docs/superpowers/specs/2026-05-10-investor-strategy-toggle-and-rental-analyzer-design.md.
- 2026-05-11: Rental analyzer v2 — property-type aware. RentCast comps are re-weighted by property-type similarity before computing the baseline, plus 5 new heuristic adjusters (property type, amenities, bath count, year built, sqft) layer on top. Modal grows two new chip groups (radiogroup-accessible). property_type is required. Smoke test: duplex vs apartment building at same address delta = +15.4%.
- 2026-06-01: Hermes/Atlas agent-control foundation is live on Railway. Use `scripts/railway-sweeney` for soldwithsweeney Railway commands so the global `rishabnandibusiness@gmail.com` Railway login stays untouched. The local token file is `.env.agent-control.local`, is gitignored by `.env.*.local`, and must not be printed.
- 2026-06-01: Agent bridge routes live under `/api/v1/agent-control/*` and are gated by `AGENT_CONTROL_ENABLED=true` plus bearer `AGENT_CONTROL_TOKEN`. Current production capabilities are `status.read`, `leads.recent.read`, and `bookings.recent.read`; responses mask emails/phones and audit allowed calls to `agent_action_audits`.
- 2026-06-01: Railway env changes made with `--skip-deploys` require `railway redeploy` for the running backend to pick up the new env snapshot. A plain `restart` left `/agent-control/status` returning 503 `Agent control is not configured`; redeployment `73deb46c-433f-4824-b87d-4f7fed63a154` fixed it.
- 2026-06-01: Production verification for agent control: authorized `/status` returns `status=ok` and the expected capabilities; unauthenticated `/status` returns 401; `/actions`, `/leads/recent?limit=1`, and `/bookings/recent?limit=1` all return successfully. Keep future checks from printing lead/booking details; summarize counts only.
- 2026-06-01: Known unrelated production issue remains in blog auto-generation: Railway logs show `gemini-3-pro-preview` is no longer available. Treat as separate Gemini model update work, not part of the Hermes bridge.
- 2026-06-01: `atlas-agent` is live in Railway project `enchanting-perception` as service ID `6dc65984-89c1-400c-9d17-d5412befd031` at `https://atlas-agent-production-99dc.up.railway.app`. Health returns `status=ok`, `gateway=stopped`; stopped is expected until provider and Telegram setup.
- 2026-06-01: Hermes deploy source was the external template repo `praveen-ks-2001/hermes-agent-template` at commit `7224d7c1a4dcffe9304f49bc843f55716f5561b4`, uploaded with `railway up --path-as-root` because GitHub-backed service creation was unauthorized with the project token.
- 2026-06-01: Hermes volume is `atlas-agent-volume` (`594c4970-ba61-4888-8372-57d0c235db65`) mounted at `/data`. Admin creds are in ignored `.env.hermes-admin.local` and Railway variables only. `BRANDON_BACKEND_URL` plus masked `BRANDON_AGENT_CONTROL_TOKEN` are set on `atlas-agent` for future backend-control skills.
- 2026-06-02: Hermes is now configured with `LLM_MODEL=gemini-3.5-flash` and the existing Gemini API key via the Hermes admin API. Official Gemini docs identify `gemini-3.5-flash` as the stable model string. Live Gemini API test returned HTTP 200, Hermes status reports Gemini configured, and `/health` reports gateway running.
- 2026-06-02: Hermes still has no messaging platforms configured. Logs warn that no messaging platforms are enabled and unauthorized users are denied. Need Telegram bot token + Brandon Telegram user ID/approval before Brandon can chat with Hermes.
- 2026-06-02: CRM assumption changed: Brandon does not use KW CRM for the future and is moving to eXp. Treat KW/Zapier as legacy one-way context only; do not build new KW CRM automation. Need eXp CRM/API/Zapier details before CRM work.
- 2026-06-02: Google Workspace / Gmail / Drive / Docs / Sheets setup should be authorized as `brandon@soldwithsweeney.com`. Do not assume `soldwithsweeneyfordeployment@gmail.com` or `rishabnandibusiness@gmail.com` is the Workspace identity for Brandon-side email and document automation.
- 2026-06-02: Adding `rishabnandibusiness@gmail.com` to Brandon's Google Cloud project IAM was blocked by Domain Restricted Sharing (`constraints/iam.allowedPolicyMemberDomains`). Next access path should use an allowed internal Workspace principal such as `brandon@soldwithsweeney.com` or a temporary org-policy exception created by a Workspace/Cloud organization admin.
- 2026-06-02: `gcloud` is authenticated as `brandon@soldwithsweeney.com` and configured to project `sold-with-sweeney-website-v1` (`721277606944`). Enabled Workspace APIs: Calendar, Gmail, Drive, Docs, Sheets, People, Pub/Sub, Workspace Events, Drive Activity, Tasks, Admin SDK, Meet, Chat, Slides, Forms. Enabled Maps/site APIs: Maps JavaScript, Places legacy/new, Geocoding, Directions, Distance Matrix, Routes, Static Maps, Street View Image, Time Zone, Address Validation.
- 2026-06-02: Brandon approved broad Workspace access for Hermes/Atlas. Implemented and deployed a full-access Workspace OAuth connector with routes under `/api/v1/workspace/*`, durable token key `google_workspace_refresh_token`, and Settings UI connect/reconnect controls. The connector requests Gmail full mail access, Calendar, Drive, Docs, Sheets, Slides, Forms, Contacts/Directory, Tasks, Chat, Meet, and Admin SDK scopes. Latest live backend deployment `fc779bef-f978-4cee-92b2-4056765e4d8b` succeeded; `/workspace/status` is configured but not connected until Brandon consents. This grants capability only after Brandon consents; autonomous send/delete/edit tools still need explicit backend agent-tool implementation and confirmation policy.
- 2026-06-02: Live Workspace OAuth is connected as `brandon@soldwithsweeney.com`; `/api/v1/workspace/status` returns `configured=True`, `connected=True`, `can_connect=True`. Next blocker for Brandon using Hermes is Telegram channel setup: need BotFather token and Brandon's numeric Telegram user ID, then wire Hermes channel allowlist and backend Workspace action tools.
- 2026-06-02: Current verified Hermes/Atlas state is not PRD-complete yet, but the first Workspace action-tool slice is live. Backend deployment `9e351dd9-fa15-45da-b7e9-8f4947a8f948` exposes `workspace.status.read`, `workspace.drive.search`, `workspace.gmail.draft.create`, `workspace.docs.create`, `workspace.sheets.append`, and `workspace.gmail.send` under `/api/v1/agent-control/workspace/*`; direct Gmail send requires explicit Brandon confirmation. Workspace OAuth remains connected as `brandon@soldwithsweeney.com`. Remaining work beyond Telegram token/user ID: configure Hermes channel/allowlist and expand action tools for Calendar/Contacts/deeper Gmail/Drive reads before claiming full executive-assistant automation.
- 2026-06-02: Atlas/Hermes backend deeper Workspace action-tool slice is live on Railway deployment `047f12b5-2a3c-4488-90af-f8dde7d8f080`: `workspace.gmail.search`, `workspace.gmail.thread.read`, `workspace.drive.file.read`, `workspace.calendar.events.read`, `workspace.calendar.event.create`, and `workspace.contacts.search`. Live authenticated status/actions smoke returned 15 capabilities/actions with no missing new IDs, Workspace remained connected, and unconfirmed calendar event creation returned 422. Calendar event creation requires `confirmed_by_brandon=true`; audit metadata excludes Gmail bodies, Drive file contents, contact addresses/phones, calendar descriptions, and attendee addresses. Still need Telegram channel/allowlist and Hermes-side tool invocation wiring.
- 2026-06-02: Hermes-side Atlas MCP bridge is now in repo at `hermes/atlas_backend_mcp.py` and deployed in the custom `atlas-agent` image as `/app/atlas_backend_mcp.py` on Railway deployment `8dcd567b-0c27-4eda-a7ef-46104aff91fe`. The patched Hermes template writes `mcp_servers.atlas_backend` with 16 allowlisted backend tools when `BRANDON_BACKEND_URL` and `BRANDON_AGENT_CONTROL_TOKEN` are present; Railway variable-name check confirmed both exist. Local stdio smoke against production returned Workspace `configured=True` and `connected=True`; Hermes health is running. Railway SSH remains blocked by project role (`MEMBER` required), and Telegram still needs BotFather token plus Brandon numeric Telegram user ID before chat-level MCP tool use can be tested.
- 2026-06-05: Telegram channel is configured for Hermes `atlas-agent` using bot username `soldwithsweeney_bot` and Brandon's allowlisted Telegram user ID `8647590834`. Railway deployment `0636f515-da58-4b94-a6ca-bb27ef2ed8f5` reached `SUCCESS`; Hermes `/health` reports gateway running; native dashboard status reports `gateway_platforms.telegram.state=connected` with no error; setup status reports Telegram configured after mirroring vars into Hermes persistent config. BotFather token was pasted in chat, so rotate it after final live Telegram chat testing and update Railway/Hermes with the replacement token.
- 2026-06-05: Hermes/Atlas assistant is now branded as Sydney. Telegram Bot API reports visible display/first name `Sydney` while username remains `soldwithsweeney_bot`; Hermes default profile `SOUL.md` was updated through the protected dashboard API to identify the assistant as Sydney, and the gateway restarted cleanly. `/start` is ignored as a platform ping once a session exists; use `/reset` or a normal message like `who are you?` to verify the new persona in Telegram.
- 2026-06-05: If Sydney still answers "Hermes Agent", the cause is Hermes session-level system prompt persistence, not Telegram bot metadata. The live fix was to set `agent.system_prompt` to a Sydney identity overlay in Hermes raw config, delete Brandon's stale Telegram session `20260605_135856_d86a6a6f`, and restart the gateway. After the restart, `/health` was running, native Telegram state was connected, and there were zero remaining Brandon Telegram sessions.
- 2026-08-01: A live Keller Williams audit found the old brokerage is still systemic despite the `/links` bio already saying eXp: global navigation/footer graphics and copy, Home/About/Buy/Sell/Invest/Blog copy, all 13 published blog articles, all 9 published funnels, the investor-report broker disclaimer, the `/links` background and KW valuation URL, and AI/seed prompts that can regenerate it. No production content was changed. Current videos, animation frames, blog hero images, and published funnel hero images were visually/OCR-checked and did not contain Keller Williams branding. A failed read-only `psql` command echoed the production database connection URL in tool output, so rotate the database password; no credential or database mutation was performed.
- 2026-08-01: The eXp Realty brokerage swap is implemented on `codex/exp-brokerage-swap` without changing the Sold With Sweeney black-and-gold design or introducing unrelated company branding. Active frontend copy/assets, footer legal destinations, backend prompts/defaults, link-pack seed, and legacy CRM wording now use eXp/provider-neutral language; four KW-branded logo composites were removed and the official white eXp logo was added with provenance. A guarded dry-run-first migration covers current persisted content and predicts 33 updates (13 blogs, 16 funnels, 1 content block, 1 link pack, 2 link items) with zero remnants. Release backend first, apply and verify the migration second, then verify the frontend so the permanent legacy-blog redirect cannot land before its renamed destination. Frontend tests/typecheck/build and 39 branding-focused backend tests pass; an isolated `origin/main` comparison confirms the release has the same eight non-release full-suite failures: seven notification timing assertions and one local-PostgreSQL dependency.
- 2026-08-01: Local review used the frontend at `http://localhost:3000` with a preview-only API at `127.0.0.1:8000`. Both the shared header and `/links` background are intentionally Sold With Sweeney-only; eXp identification remains in the appropriate profile copy and footer disclosures, with its logo used only in the footer. The preview read the actual published link-pack snapshot and assets once through an explicit read-only transaction, closed it without a write, and applied the eXp text/destination substitutions in memory while preserving all six top-level items, groups, profile/photo, socials, thumbnails, destinations, and active states. Navbar and `/links` regression tests plus the full 33-test frontend suite, TypeScript, targeted ESLint, structure comparison, HTTP checks, and browser/console review pass; both temporary local processes were stopped before the production build.
- 2026-08-01: Production rollout of the eXp swap was explicitly authorized. GitHub `main` is connected to both Railway project `enchanting-perception` production and Vercel Production. Fresh preflight passed, and the final read-only migration preview rolled back cleanly with 33 planned updates and zero remnants. Keep the unrelated `docs/deployment/hermes-railway.md` edit out of the release; exact live deployment/migration results belong in the deployment handoff.
- 2026-08-01: The eXp brokerage swap is live on production from GitHub `main` commit `b364124`. Railway deployment `0a580dbf-b570-4f2c-9500-c416531c3e53` and Vercel Production deployment `5710309885` succeeded. The guarded migration applied 33 updates and saved a private backup at `/Users/rishabnandi/.sws-backups/exp-branding/exp-branding-backup-20260802T024423Z.json`; the final production dry-run reports 0 planned updates and 0 old-brand remnants. A TDD follow-up fixed a false positive caused by PostgreSQL `BYTEA` values arriving as `memoryview(format='c')` while packaged assets are `bytes`. Live backend health is OK; Home/About/Buy/Sell/Invest/Blog/Links return 200 with no Keller Williams text; the header and `/links` are SWS-only, the footer retains eXp identification/legal links, and the real six-item published links page is intact.
- 2026-08-02: Fixed the production SWS header logo regression from commit `3358610`. The white/gold PNG contains large transparent margins, so the former `76x40` contract produced only about `52x21px` of visible artwork. The navbar now crops those margins inside a `112x64px` mobile / `124x64px` desktop frame while rendering the source at `72px` / `80px` tall, producing an approximately `117x46px` visible desktop mark without changing the 64px header or adding eXp branding. A red-green regression test, all 34 frontend tests, TypeScript, targeted lint, production build, local browser measurement, and live custom-domain HTML verification passed. Vercel Production deployment `5715079788` and Railway deployment `3a9fee4a-a042-40c0-8e92-bf7a60196b83` succeeded; the unrelated Hermes document edit stayed excluded.
# 2026-08-12: Internal Command workspace continuation
- Bulk permitted-data import is now available at `POST /api/v1/command/contacts/import` (maximum 1,000 rows per request). It deduplicates by email and records per-contact import activity.
- Contact workspaces now expose actual linked opportunity records rather than a blank opportunities array. This is internal CRM data only; no external brokerage or e-signature archive is present in this repository or database.
- Opportunity details support real contact, vendor, and offer relationship writes through the internal API; they are not mock UI state.
- Smart Plan workspaces now create steps and enroll contacts through the same internal database APIs.
- Agreement lifecycle is now audit-backed: creation/status changes/recipient additions create agreement events, detail workspaces show recipients/events/files, and a migration adds an optional agreement link to private file assets.
- Marketing, website, and report Command views now query live internal content, funnels, and aggregate analytics event-type records instead of rendering only counters.
- Listing map placement is now coordinate-based. The backend geocodes only when the configured Google Maps key is present and returns explicit errors otherwise.
- 2026-08-12: Command migration `fb74d2c0a611` is applied in the configured internal database; verified `crm_file_assets.agreement_id`. Authenticated runtime reads across overview/reports/marketing/websites/listings/agreements returned HTTP 200. Frontend full suite has 40 passing tests and production build completes; local static generation still logs an unrelated unavailable content-block API fetch.
- Contacts UI now fetches the entire paginated CRM dataset in 100-row batches rather than only the first 50 results.
- Smart Plan enrollment lifecycle now supports active/paused/completed status changes with a server-backed pause/resume UI.
- Opportunity workspace now persists pipeline stage changes and refreshes from the internal API after movement.
- Contact workspace now updates lead/client stages through the internal API and appends a stage-change timeline activity.
- Smart Plan steps can now be edited through a persisted API update from the plan workspace.
- Command shell now has a responsive mobile navigation drawer on nested module routes.
- Added and applied `fc0e8a4b9422` for generic task-to-internal-record links. API path: POST `/api/v1/command/tasks/{task_id}/links`.
- The Tasks workspace now exposes the persisted task-link workflow for contacts, opportunities, agreements, and listings.
- Latest Command branch verification: 46 frontend tests, frontend typecheck/build, and 8 focused Command backend tests pass. Build retains the unrelated non-fatal local content-block fetch warning.
