# Things Done Till Now

## Project: Brandon Real Estate AI Platform
Last Updated: 2026-03-20

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

*Claude Code: Update this file after completing every task.*
