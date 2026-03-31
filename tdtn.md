# Things Done Till Now

## Project: Brandon Real Estate AI Platform
Last Updated: 2026-03-27

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
