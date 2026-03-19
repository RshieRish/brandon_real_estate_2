# Brandon Real Estate — AI Conversion Platform

## Project
Premium real estate conversion platform for Brandon Sweeney (Sold With Sweeney & Co.)
Client site: SoldWithSweeney.com

## Objective
Convert visitors into qualified meetings: Buy → strategy call, Sell → valuation meeting, Invest → investor review call.

## Brand Rules
- Colors: Black (#0a0a0a), Gold (#eac469), White (#ffffff), Gray (#818285), Bronze (#c08235)
- Font: Montserrat (weights 300–900)
- REALTOR® must ALWAYS be capitalized with ® mark
- Dark-dominant, premium, cinematic aesthetic
- Gold halftone dot patterns as texture overlays
- KW legal disclaimers in every footer

## Design Skill (MANDATORY for all frontend)
taste-skill applied: DESIGN_VARIANCE:8, MOTION_INTENSITY:6, VISUAL_DENSITY:4
- NO emojis anywhere in code or UI — use @phosphor-icons/react
- min-h-[100dvh] for full-height sections (never h-screen)
- Asymmetric layouts (split-screen heroes, no 3-col equal card rows)
- Framer Motion spring physics: stiffness:100, damping:20
- Glassmorphism panels with inner refraction borders
- Staggered entrance animations with AnimatePresence
- Full interaction states: loading skeletons, empty states, error states

## Tech Stack
- Frontend: Next.js 14 App Router → Vercel
- Backend: FastAPI + Uvicorn → Railway
- DB: PostgreSQL (Neon) via SQLAlchemy 2.0 async + asyncpg
- AI: Google Gemini via google-generativeai SDK
- Calendar: Google Calendar API OAuth2
- CRM: KW Command CRM

## Key Rules
1. Update tdtn.md and memory.md after EVERY task
2. Never hardcode API keys — use .env files only
3. Mobile-first responsive design
4. Lighthouse > 80 performance target
5. All API logic in Python backend — Next.js is UI only

## Spec: ./BRANDON_RE_SPEC.md
## Progress: ./tdtn.md
## Memory: ./memory.md
