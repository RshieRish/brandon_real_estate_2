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
- House blast frames: Need ffmpeg extraction (Task 22)
- Bio/reviews: In BRANDON_RE_SPEC.md Section 14

## Known Issues
- None

## Last Session Context
- Task 1 complete: project initialized
- Next: Next.js frontend scaffold (Task 2)
