# Brandon Real Estate AI Platform — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-stack AI-powered real estate conversion platform for Brandon Sweeney (SoldWithSweeney.com) with a Next.js frontend, Python FastAPI backend, Gemini-powered chatbot, seller evaluator, investor analysis tool, and admin dashboard.

**Architecture:** Next.js 14 App Router frontend (Vercel) calls a FastAPI Python backend (Railway) via REST. PostgreSQL on Neon stores leads, funnels, content, analytics, and bookings. All AI logic (Gemini chatbot, property evaluator, investor analysis, funnel generation) runs server-side in Python.

**Tech Stack:** Next.js 14, TypeScript, Tailwind CSS, Framer Motion, GSAP ScrollTrigger, FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic, Pydantic v2, Google Gemini API, Google Calendar API, Google OAuth2, python-jose JWT, PostgreSQL (Neon)

---

## Assets Already Available

Located in `/Users/rishabnandi/brandon-real-estate/public/`:
- `assets/` — aerial_drone_shot.mp4, black_gold.mp4, house_blast.mp4, reverse_house.mp4
- `headshots/` — Brandon Sweeney Headshot.jpg, Brandon Sweeney Headshot Zoomed In.png, SWS TEAM Headshot.png
- `logos/` — SWS primary logo, KW white logo, MORE Good Days
- `logos/Designations-Associations/` — Green.jpg, MAR logo, NAR logo, NEAR.png, C2EX logo
- `testimonial/` — 46D52606...MP4

## Environment Variables

**Frontend `.env.local`:**
```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
NEXT_PUBLIC_GOOGLE_MAPS_KEY=<pending>
```

**Backend `.env`:**
```
DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>/<db>?sslmode=require
GEMINI_API_KEY=<REDACTED_GEMINI_KEY>
GOOGLE_CLIENT_ID=<REDACTED_GOOGLE_CLIENT_ID>
GOOGLE_CLIENT_SECRET=<REDACTED_GOOGLE_CLIENT_SECRET>
GOOGLE_CALENDAR_CLIENT_ID=<REDACTED_GOOGLE_CLIENT_ID>
GOOGLE_CALENDAR_CLIENT_SECRET=<REDACTED_GOOGLE_CLIENT_SECRET>
JWT_SECRET=<generate: python -c "import secrets; print(secrets.token_hex(32))">
CORS_ORIGINS=http://localhost:3000,https://soldwithsweeney.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=info@soldwithsweeney.com
SMTP_PASS=<pending>
KW_CRM_API_KEY=<pending>
```

---

## File Map

### Root
```
brandon-real-estate/
├── claude.md
├── tdtn.md
├── memory.md
├── .gitignore
├── frontend/
└── backend/
```

### Frontend (`frontend/`)
```
frontend/
├── .env.local
├── package.json
├── next.config.js
├── tailwind.config.js
├── tsconfig.json
├── public/
│   ├── assets/          ← copy from ../public/assets/
│   ├── headshots/       ← copy from ../public/headshots/
│   ├── logos/           ← copy from ../public/logos/
│   ├── testimonial/     ← copy from ../public/testimonial/
│   └── frames/house-blast/  ← extracted via ffmpeg
└── src/
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx              ← Home
    │   ├── buy/page.tsx
    │   ├── sell/page.tsx
    │   ├── invest/page.tsx
    │   ├── about/page.tsx
    │   ├── f/[slug]/page.tsx     ← Funnel pages
    │   └── admin/
    │       ├── layout.tsx
    │       ├── page.tsx          ← Dashboard home
    │       ├── leads/page.tsx
    │       ├── leads/[id]/page.tsx
    │       ├── content/page.tsx
    │       ├── funnels/page.tsx
    │       ├── funnels/new/page.tsx
    │       ├── funnels/[id]/page.tsx
    │       ├── analytics/page.tsx
    │       └── settings/page.tsx
    ├── components/
    │   ├── layout/Navbar.tsx
    │   ├── layout/Footer.tsx
    │   ├── layout/AdminSidebar.tsx
    │   ├── home/Hero.tsx
    │   ├── home/ExplodingHouseScroll.tsx
    │   ├── home/TrustSection.tsx
    │   ├── home/AudienceCards.tsx
    │   ├── home/GivingBack.tsx
    │   ├── buyer/MonopolyJourney.tsx
    │   ├── buyer/BuyerTeam.tsx
    │   ├── buyer/BuyerMistakes.tsx
    │   ├── seller/SellerSteps.tsx
    │   ├── seller/StagingChecklist.tsx
    │   ├── seller/PropertyEvaluator.tsx
    │   ├── investor/InvestorCalculator.tsx
    │   ├── investor/AnalysisResults.tsx
    │   ├── investor/MeetingGate.tsx
    │   ├── investor/FlipCaseStudy.tsx
    │   ├── chat/ChatWidget.tsx
    │   ├── chat/ChatPanel.tsx
    │   ├── chat/BookingInChat.tsx
    │   ├── shared/CTAButton.tsx
    │   ├── shared/ReviewCard.tsx
    │   ├── shared/CalendarPicker.tsx
    │   ├── shared/LeadCaptureForm.tsx
    │   ├── shared/HalftoneOverlay.tsx
    │   └── admin/
    │       ├── LeadTable.tsx
    │       ├── ContentEditor.tsx
    │       ├── FunnelBuilder.tsx
    │       ├── AnalyticsCharts.tsx
    │       └── SettingsForm.tsx
    ├── lib/
    │   ├── api.ts
    │   ├── investor-calc.ts
    │   └── analytics.ts
    ├── hooks/
    │   ├── useScrollAnimation.ts
    │   ├── useChat.ts
    │   └── useAnalytics.ts
    └── styles/
        ├── globals.css
        └── animations.css
```

### Backend (`backend/`)
```
backend/
├── .env
├── requirements.txt
├── Dockerfile
├── main.py
├── config.py
├── database.py
├── seed.py
├── alembic.ini
├── alembic/env.py
├── alembic/versions/
├── models/
│   ├── __init__.py
│   ├── base.py
│   ├── lead.py
│   ├── funnel.py
│   ├── content_block.py
│   ├── analytics_event.py
│   ├── booking.py
│   ├── admin_user.py
│   └── setting.py
├── schemas/
│   ├── __init__.py
│   ├── lead.py
│   ├── funnel.py
│   ├── booking.py
│   ├── content.py
│   ├── analytics.py
│   └── auth.py
├── routers/
│   ├── __init__.py
│   ├── chat.py
│   ├── leads.py
│   ├── funnels.py
│   ├── evaluator.py
│   ├── investor.py
│   ├── booking.py
│   ├── analytics.py
│   ├── content.py
│   ├── crm.py
│   └── auth.py
├── services/
│   ├── __init__.py
│   ├── gemini.py
│   ├── calendar_service.py
│   ├── crm_service.py
│   ├── evaluator_service.py
│   ├── investor_service.py
│   ├── funnel_service.py
│   └── email_service.py
└── middleware/
    ├── __init__.py
    └── auth.py
```

---

## Phase 1: Project Foundation

### Task 1: Scaffold project structure + git init

**Files:**
- Create: `brandon-real-estate/.gitignore`
- Create: `brandon-real-estate/claude.md`
- Create: `brandon-real-estate/tdtn.md`
- Create: `brandon-real-estate/memory.md`

- [ ] Run in `/Users/rishabnandi/brandon-real-estate`:
```bash
git init
```

- [ ] Create `.gitignore`:
```gitignore
# Dependencies
node_modules/
__pycache__/
*.pyc
.venv/
venv/

# Env
.env
.env.local
.env.*.local

# Build
.next/
dist/
build/

# Misc
.DS_Store
*.log
```

- [ ] Create `claude.md`:
```markdown
# Brandon Real Estate — AI Conversion Platform

## Project
Premium real estate conversion platform for Brandon Sweeney (Sold With Sweeney & Co.)
Client site: SoldWithSweeney.com

## Objective
Convert visitors into qualified meetings: Buy → strategy call, Sell → valuation meeting, Invest → investor review call.

## Brand Rules
- Colors: Black (#000000), Gold (#eac469), White (#ffffff), Gray (#818285), Bronze (#c08235)
- Font: Montserrat (weights 300–900)
- REALTOR® must ALWAYS be capitalized with ® mark
- Dark-dominant, premium, cinematic aesthetic
- Gold halftone dot patterns as texture overlays
- KW legal disclaimers in every footer

## Tech Stack
- Frontend: Next.js 14 App Router → Vercel
- Backend: FastAPI + Uvicorn → Railway
- DB: PostgreSQL (Neon free tier) via SQLAlchemy 2.0 async + asyncpg
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
```

- [ ] Create `tdtn.md` (initial):
```markdown
# Things Done Till Now

## Project: Brandon Real Estate AI Platform
Last Updated: 2026-03-18

### 2026-03-18 — Project Initialized
- Git repo initialized
- Created claude.md, tdtn.md, memory.md, .gitignore
- Status: Complete
```

- [ ] Create `memory.md` (initial):
```markdown
# Project Memory

## Architecture Decisions
- Next.js App Router: SSR + static pages, no API routes (UI only)
- FastAPI backend: all AI, DB, business logic
- Gemini flash for chatbot speed; Gemini pro for complex analysis
- Neon PostgreSQL free tier for launch

## Integration Status
- Gemini API: Key in .env ✓
- Google OAuth: Client ID + Secret in .env ✓
- Google Calendar: Same OAuth credentials (pending calendar scope setup)
- Google Maps: Pending key
- KW CRM: Pending access path
- SMTP: Pending configuration

## Content Status
- Videos: Available in public/assets/
- Headshots: Available in public/headshots/
- Logos: Available in public/logos/
- House blast frames: Need ffmpeg extraction
- Bio/reviews: Available in BRANDON_RE_SPEC.md Section 14

## Known Issues
- None yet

## Last Session Context
- Project initialized, moving to Next.js scaffold
```

- [ ] Commit:
```bash
git add .
git commit -m "chore: initialize project with claude.md, tdtn.md, memory.md"
```

---

### Task 2: Scaffold Next.js frontend

**Files:** Create `frontend/` directory with Next.js 14 App Router + TypeScript + Tailwind

- [ ] Scaffold Next.js:
```bash
cd /Users/rishabnandi/brandon-real-estate
npx create-next-app@latest frontend \
  --typescript \
  --tailwind \
  --eslint \
  --app \
  --src-dir \
  --import-alias "@/*" \
  --no-git
```

- [ ] Install frontend dependencies:
```bash
cd frontend
npm install framer-motion gsap @gsap/react axios
npm install -D @types/node
```

- [ ] Copy assets from project public to frontend public:
```bash
cp -r /Users/rishabnandi/brandon-real-estate/public/assets frontend/public/assets
cp -r /Users/rishabnandi/brandon-real-estate/public/headshots frontend/public/headshots
cp -r /Users/rishabnandi/brandon-real-estate/public/logos frontend/public/logos
cp -r /Users/rishabnandi/brandon-real-estate/public/testimonial frontend/public/testimonial
mkdir -p frontend/public/frames/house-blast
```

- [ ] Create `frontend/.env.local`:
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

- [ ] Replace `frontend/next.config.js` (or `next.config.ts`):
```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [],
  },
  async headers() {
    return [
      {
        source: '/assets/:path*',
        headers: [{ key: 'Cache-Control', value: 'public, max-age=31536000, immutable' }],
      },
    ];
  },
};

module.exports = nextConfig;
```

- [ ] Update `frontend/tailwind.config.ts`:
```ts
import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        gold: '#eac469',
        'gold-hover': '#d4af5a',
        bronze: '#c08235',
        'dark-surface': '#0a0a0a',
        'dark-card': '#111111',
        'dark-border': '#1a1a1a',
      },
      fontFamily: {
        sans: ['Montserrat', 'sans-serif'],
      },
    },
  },
  plugins: [],
};

export default config;
```

- [ ] Create `frontend/src/styles/globals.css`:
```css
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700;800;900&display=swap');
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --color-black: #000000;
  --color-gold: #eac469;
  --color-white: #ffffff;
  --color-gray: #818285;
  --color-bronze: #c08235;
  --color-gold-hover: #d4af5a;
  --color-gold-light: rgba(234, 196, 105, 0.1);
  --color-gold-glow: rgba(234, 196, 105, 0.3);
  --color-dark-surface: #0a0a0a;
  --color-dark-card: #111111;
  --color-dark-border: #1a1a1a;
}

* { box-sizing: border-box; }

html { scroll-behavior: smooth; }

body {
  background-color: #000000;
  color: #ffffff;
  font-family: 'Montserrat', sans-serif;
}
```

- [ ] Create `frontend/src/styles/animations.css`:
```css
@keyframes pulse-gold {
  0%, 100% { box-shadow: 0 0 0 0 rgba(234, 196, 105, 0.4); }
  50% { box-shadow: 0 0 0 12px rgba(234, 196, 105, 0); }
}

@keyframes fade-up {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.animate-pulse-gold { animation: pulse-gold 2s infinite; }
.animate-fade-up { animation: fade-up 0.6s ease forwards; }
```

- [ ] Create `frontend/src/lib/api.ts`:
```ts
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${API_URL}${path}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
}

export async function apiPostAuth<T>(path: string, body: unknown, token: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
```

- [ ] Create `frontend/src/lib/analytics.ts`:
```ts
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export function trackEvent(event_type: string, metadata: Record<string, unknown> = {}) {
  if (typeof window === 'undefined') return;
  fetch(`${API_URL}/api/v1/analytics/event`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      event_type,
      page: window.location.pathname,
      referrer: document.referrer,
      user_agent: navigator.userAgent,
      metadata,
    }),
    keepalive: true,
  }).catch(() => {}); // fire and forget
}
```

- [ ] Verify frontend starts:
```bash
cd frontend && npm run dev
```
Expected: Runs on http://localhost:3000

- [ ] Commit:
```bash
cd /Users/rishabnandi/brandon-real-estate
git add frontend/
git commit -m "feat: scaffold Next.js frontend with brand system and config"
```

---

### Task 3: Scaffold FastAPI backend

**Files:** Create `backend/` with all Python structure

- [ ] Create `backend/` with virtualenv + requirements:
```bash
cd /Users/rishabnandi/brandon-real-estate
mkdir -p backend/models backend/schemas backend/routers backend/services backend/middleware backend/alembic/versions
python3 -m venv backend/.venv
```

- [ ] Create `backend/requirements.txt`:
```
fastapi==0.111.0
uvicorn[standard]==0.29.0
sqlalchemy[asyncio]==2.0.29
asyncpg==0.29.0
alembic==1.13.1
pydantic==2.7.1
pydantic-settings==2.2.1
google-generativeai==0.7.2
google-auth-oauthlib==1.2.0
google-api-python-client==2.128.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9
aiosmtplib==3.0.1
httpx==0.27.0
weasyprint==62.3
python-dotenv==1.0.1
```

- [ ] Install:
```bash
cd backend && .venv/bin/pip install -r requirements.txt
```

- [ ] Create `backend/config.py`:
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = ""
    GEMINI_API_KEY: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_CALENDAR_CLIENT_ID: str = ""
    GOOGLE_CALENDAR_CLIENT_SECRET: str = ""
    JWT_SECRET: str = "changeme"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    CORS_ORIGINS: str = "http://localhost:3000"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    KW_CRM_API_KEY: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
```

- [ ] Create `backend/database.py`:
```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

- [ ] Create `backend/models/__init__.py` (empty)
- [ ] Create `backend/models/base.py`:
```python
from database import Base
```

- [ ] Create `backend/models/lead.py`:
```python
from sqlalchemy import Column, Integer, String, DateTime, Text, func
from database import Base

class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    email = Column(String(255))
    phone = Column(String(50))
    source = Column(String(100))  # page or funnel slug
    lead_type = Column(String(50))  # buyer, seller, investor, general
    routing_status = Column(String(50), default="new")  # new, in_review, sent_to_crm, booked, converted, archived
    notes = Column(Text, default="")
    metadata_ = Column("metadata", Text, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] Create `backend/models/funnel.py`:
```python
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, func
from database import Base

class Funnel(Base):
    __tablename__ = "funnels"
    id = Column(Integer, primary_key=True)
    title = Column(String(255))
    slug = Column(String(255), unique=True)
    audience = Column(String(50))
    event_date = Column(DateTime(timezone=True), nullable=True)
    description = Column(Text, default="")
    cta_text = Column(String(255), default="Register Now")
    video_url = Column(String(500), nullable=True)
    lead_routing = Column(String(50), default="dashboard")
    status = Column(String(50), default="draft")
    generated_content = Column(Text, default="{}")  # JSON
    registrations = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] Create `backend/models/content_block.py`:
```python
from sqlalchemy import Column, Integer, String, DateTime, Text, func
from database import Base

class ContentBlock(Base):
    __tablename__ = "content_blocks"
    id = Column(Integer, primary_key=True)
    block_id = Column(String(100), unique=True)
    content = Column(Text)
    content_type = Column(String(50), default="text")  # text, html, image_url
    page = Column(String(100))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] Create `backend/models/analytics_event.py`:
```python
from sqlalchemy import Column, Integer, String, DateTime, Text, func
from database import Base

class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    id = Column(Integer, primary_key=True)
    event_type = Column(String(100))
    page = Column(String(255))
    referrer = Column(String(500), nullable=True)
    user_agent = Column(String(500), nullable=True)
    device_type = Column(String(50), nullable=True)
    metadata_ = Column("metadata", Text, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] Create `backend/models/booking.py`:
```python
from sqlalchemy import Column, Integer, String, DateTime, Text, func
from database import Base

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, nullable=True)
    name = Column(String(255))
    email = Column(String(255))
    phone = Column(String(50))
    meeting_type = Column(String(50))  # phone, video, in_person
    context = Column(String(50))  # buyer, seller, investor
    scheduled_at = Column(DateTime(timezone=True))
    google_event_id = Column(String(255), nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] Create `backend/models/admin_user.py`:
```python
from sqlalchemy import Column, Integer, String, DateTime, func
from database import Base

class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True)
    hashed_password = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] Create `backend/models/setting.py`:
```python
from sqlalchemy import Column, Integer, String, Text, DateTime, func
from database import Base

class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True)
    value = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] Create `backend/.env` (substitute real DB URL once Neon is set up):
```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost/brandon_re
GEMINI_API_KEY=<REDACTED_GEMINI_KEY>
GOOGLE_CLIENT_ID=<REDACTED_GOOGLE_CLIENT_ID>
GOOGLE_CLIENT_SECRET=<REDACTED_GOOGLE_CLIENT_SECRET>
GOOGLE_CALENDAR_CLIENT_ID=<REDACTED_GOOGLE_CLIENT_ID>
GOOGLE_CALENDAR_CLIENT_SECRET=<REDACTED_GOOGLE_CLIENT_SECRET>
JWT_SECRET=super-secret-change-this
CORS_ORIGINS=http://localhost:3000
```

- [ ] Set up Alembic. Create `backend/alembic.ini` — run:
```bash
cd backend && .venv/bin/alembic init alembic
```

- [ ] Update `backend/alembic/env.py` — replace target_metadata section:
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import settings
from database import Base

# import all models so Base picks them up
import models.lead
import models.funnel
import models.content_block
import models.analytics_event
import models.booking
import models.admin_user
import models.setting

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("+asyncpg", ""))
target_metadata = Base.metadata
```

- [ ] Create initial migration:
```bash
cd backend && .venv/bin/alembic revision --autogenerate -m "initial schema"
```

- [ ] Create `backend/main.py`:
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings

from routers import auth, leads, chat, funnels, evaluator, investor, booking, analytics, content, crm

app = FastAPI(title="Brandon RE API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(leads.router, prefix="/api/v1/leads", tags=["leads"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["chat"])
app.include_router(funnels.router, prefix="/api/v1/funnels", tags=["funnels"])
app.include_router(evaluator.router, prefix="/api/v1/evaluator", tags=["evaluator"])
app.include_router(investor.router, prefix="/api/v1/investor", tags=["investor"])
app.include_router(booking.router, prefix="/api/v1/booking", tags=["booking"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(content.router, prefix="/api/v1/content", tags=["content"])
app.include_router(crm.router, prefix="/api/v1/crm", tags=["crm"])

@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] Create stub routers (each file gets a minimal APIRouter for now):

`backend/routers/__init__.py` — empty

`backend/routers/auth.py`:
```python
from fastapi import APIRouter
router = APIRouter()
```
(repeat minimal stubs for: leads.py, chat.py, funnels.py, evaluator.py, investor.py, booking.py, analytics.py, content.py, crm.py)

- [ ] Create `backend/schemas/__init__.py` — empty
- [ ] Create `backend/services/__init__.py` — empty
- [ ] Create `backend/middleware/__init__.py` — empty

- [ ] Test backend starts:
```bash
cd backend && .venv/bin/uvicorn main:app --reload --port 8000
```
Expected: "Application startup complete"

- [ ] Commit:
```bash
cd /Users/rishabnandi/brandon-real-estate
git add backend/
git commit -m "feat: scaffold FastAPI backend with models, config, and stub routers"
```

---

## Phase 2: Backend Auth & Core Routes

### Task 4: Admin auth (JWT login)

**Files:**
- Implement: `backend/routers/auth.py`
- Implement: `backend/middleware/auth.py`
- Implement: `backend/schemas/auth.py`
- Implement: `backend/seed.py`

- [ ] Create `backend/schemas/auth.py`:
```python
from pydantic import BaseModel

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
```

- [ ] Create `backend/middleware/auth.py`:
```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from config import settings

bearer = HTTPBearer()

def require_admin(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    try:
        payload = jwt.decode(credentials.credentials, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
```

- [ ] Implement `backend/routers/auth.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta
from database import get_db
from models.admin_user import AdminUser
from schemas.auth import LoginRequest, TokenResponse
from config import settings

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AdminUser).where(AdminUser.email == req.email))
    user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    token = jwt.encode({"sub": str(user.id), "exp": expire}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return TokenResponse(access_token=token)

@router.get("/me")
async def me(payload: dict = Depends(require_admin := __import__('middleware.auth', fromlist=['require_admin']).require_admin)):
    return {"user_id": payload["sub"]}
```

- [ ] Create `backend/seed.py`:
```python
import asyncio
from passlib.context import CryptContext
from database import AsyncSessionLocal, engine, Base
import models.lead, models.funnel, models.content_block, models.analytics_event, models.booking, models.admin_user, models.setting
from models.admin_user import AdminUser
from models.content_block import ContentBlock
from sqlalchemy import select

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEFAULT_CONTENT = [
    {"block_id": "home_hero_headline", "content": "NOT your AVERAGE, award winning, philanthropic REALTOR® OF THE YEAR '25", "page": "home"},
    {"block_id": "home_hero_subtext", "content": "Serving MA & NH | Keller Williams Realty Success", "page": "home"},
    {"block_id": "home_cta_buy", "content": "Find Your Home", "page": "home"},
    {"block_id": "home_cta_sell", "content": "Sell With Confidence", "page": "home"},
    {"block_id": "home_cta_invest", "content": "Analyze a Deal", "page": "home"},
    {"block_id": "market_update", "content": "Current market conditions in the Merrimack Valley remain competitive. Inventory is limited and well-priced homes move quickly. Contact Brandon for a personalized market analysis.", "page": "buyer"},
]

async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Admin user
        result = await db.execute(select(AdminUser).where(AdminUser.email == "brandon@soldwithsweeney.com"))
        if not result.scalar_one_or_none():
            db.add(AdminUser(email="brandon@soldwithsweeney.com", hashed_password=pwd_context.hash("changeme123!")))

        # Content blocks
        for item in DEFAULT_CONTENT:
            result = await db.execute(select(ContentBlock).where(ContentBlock.block_id == item["block_id"]))
            if not result.scalar_one_or_none():
                db.add(ContentBlock(**item, content_type="text"))

        await db.commit()
    print("Seed complete. Admin: brandon@soldwithsweeney.com / changeme123!")

if __name__ == "__main__":
    asyncio.run(seed())
```

- [ ] Run migrations (once DB is available) then seed:
```bash
cd backend
.venv/bin/alembic upgrade head
.venv/bin/python seed.py
```

- [ ] Commit:
```bash
git add backend/routers/auth.py backend/middleware/ backend/schemas/auth.py backend/seed.py
git commit -m "feat: admin JWT auth + seed script"
```

---

### Task 5: Leads API

**Files:**
- Implement: `backend/schemas/lead.py`
- Implement: `backend/routers/leads.py`

- [ ] Create `backend/schemas/lead.py`:
```python
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class LeadCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    source: Optional[str] = "website"
    lead_type: Optional[str] = "general"
    metadata_: Optional[dict] = {}

class LeadUpdate(BaseModel):
    routing_status: Optional[str] = None
    notes: Optional[str] = None

class LeadOut(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str]
    source: Optional[str]
    lead_type: Optional[str]
    routing_status: str
    notes: str
    created_at: datetime
    class Config:
        from_attributes = True
```

- [ ] Implement `backend/routers/leads.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional
import json
from database import get_db
from models.lead import Lead
from schemas.lead import LeadCreate, LeadUpdate, LeadOut
from middleware.auth import require_admin

router = APIRouter()

@router.post("/", response_model=LeadOut)
async def create_lead(data: LeadCreate, db: AsyncSession = Depends(get_db)):
    lead = Lead(
        name=data.name, email=data.email, phone=data.phone,
        source=data.source, lead_type=data.lead_type,
        metadata_=json.dumps(data.metadata_ or {})
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead

@router.get("/", response_model=List[LeadOut])
async def list_leads(
    lead_type: Optional[str] = None,
    routing_status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    q = select(Lead).order_by(desc(Lead.created_at))
    if lead_type: q = q.where(Lead.lead_type == lead_type)
    if routing_status: q = q.where(Lead.routing_status == routing_status)
    result = await db.execute(q)
    return result.scalars().all()

@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(lead_id: int, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead: raise HTTPException(404, "Lead not found")
    return lead

@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(lead_id: int, data: LeadUpdate, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead: raise HTTPException(404, "Lead not found")
    if data.routing_status: lead.routing_status = data.routing_status
    if data.notes is not None: lead.notes = data.notes
    await db.flush()
    await db.refresh(lead)
    return lead
```

- [ ] Commit:
```bash
git add backend/routers/leads.py backend/schemas/lead.py
git commit -m "feat: leads CRUD API"
```

---

### Task 6: Content blocks API

**Files:**
- Implement: `backend/schemas/content.py`
- Implement: `backend/routers/content.py`

- [ ] Create `backend/schemas/content.py`:
```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ContentBlockUpdate(BaseModel):
    content: str

class ContentBlockOut(BaseModel):
    id: int
    block_id: str
    content: str
    content_type: str
    page: Optional[str]
    updated_at: datetime
    class Config:
        from_attributes = True
```

- [ ] Implement `backend/routers/content.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from database import get_db
from models.content_block import ContentBlock
from schemas.content import ContentBlockUpdate, ContentBlockOut
from middleware.auth import require_admin

router = APIRouter()

@router.get("/", response_model=List[ContentBlockOut])
async def list_content(page: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(ContentBlock)
    if page: q = q.where(ContentBlock.page == page)
    result = await db.execute(q)
    return result.scalars().all()

@router.get("/{block_id}", response_model=ContentBlockOut)
async def get_block(block_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ContentBlock).where(ContentBlock.block_id == block_id))
    block = result.scalar_one_or_none()
    if not block: raise HTTPException(404, "Block not found")
    return block

@router.put("/{block_id}", response_model=ContentBlockOut)
async def update_block(block_id: str, data: ContentBlockUpdate, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    result = await db.execute(select(ContentBlock).where(ContentBlock.block_id == block_id))
    block = result.scalar_one_or_none()
    if not block: raise HTTPException(404, "Block not found")
    block.content = data.content
    await db.flush()
    await db.refresh(block)
    return block
```

- [ ] Commit:
```bash
git add backend/routers/content.py backend/schemas/content.py
git commit -m "feat: content blocks API"
```

---

### Task 7: Analytics API

**Files:**
- Implement: `backend/schemas/analytics.py`
- Implement: `backend/routers/analytics.py`

- [ ] Create `backend/schemas/analytics.py`:
```python
from pydantic import BaseModel
from typing import Optional

class EventCreate(BaseModel):
    event_type: str
    page: Optional[str] = None
    referrer: Optional[str] = None
    user_agent: Optional[str] = None
    metadata: Optional[dict] = {}
```

- [ ] Implement `backend/routers/analytics.py`:
```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from datetime import datetime, timedelta
import json
from database import get_db
from models.analytics_event import AnalyticsEvent
from schemas.analytics import EventCreate
from middleware.auth import require_admin

router = APIRouter()

def detect_device(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "mobile" in ua or "android" in ua: return "mobile"
    if "tablet" in ua or "ipad" in ua: return "tablet"
    return "desktop"

@router.post("/event")
async def track_event(data: EventCreate, db: AsyncSession = Depends(get_db)):
    event = AnalyticsEvent(
        event_type=data.event_type,
        page=data.page,
        referrer=data.referrer,
        user_agent=data.user_agent,
        device_type=detect_device(data.user_agent or ""),
        metadata_=json.dumps(data.metadata or {}),
    )
    db.add(event)
    return {"ok": True}

@router.get("/dashboard")
async def dashboard_stats(days: int = 30, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    since = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(func.count()).where(AnalyticsEvent.created_at >= since, AnalyticsEvent.event_type == "page_view")
    )
    page_views = result.scalar() or 0
    result2 = await db.execute(
        select(AnalyticsEvent.page, func.count().label("count"))
        .where(AnalyticsEvent.created_at >= since, AnalyticsEvent.event_type == "page_view")
        .group_by(AnalyticsEvent.page)
        .order_by(desc("count"))
        .limit(10)
    )
    top_pages = [{"page": row[0], "count": row[1]} for row in result2]
    return {"page_views": page_views, "top_pages": top_pages}
```

- [ ] Commit:
```bash
git add backend/routers/analytics.py backend/schemas/analytics.py
git commit -m "feat: analytics event tracking API"
```

---

## Phase 3: Gemini AI Services

### Task 8: Gemini service + chatbot API

**Files:**
- Create: `backend/services/gemini.py`
- Implement: `backend/routers/chat.py`

- [ ] Create `backend/services/gemini.py`:
```python
import google.generativeai as genai
from config import settings

genai.configure(api_key=settings.GEMINI_API_KEY)

CHATBOT_SYSTEM_PROMPT = """You are Brandon Sweeney's AI assistant on his real estate website, SoldWithSweeney.com.

Brandon is a licensed REALTOR® in MA and NH, CEO of Sold With Sweeney & Co., powered by Keller Williams Realty Success. He is the 2025 NEAR President and REALTOR® Of The Year. Licensed since 2017. Specializes in residential real estate in the Merrimack Valley and surrounding areas. Also works with investors.

PRIMARY GOAL: Help the visitor book a meeting with Brandon by:
1. Understanding their need (buying, selling, investing, general)
2. Providing helpful info about Brandon's services
3. Collecting lead details (name, email, phone, need)
4. Offering to book a call when context is sufficient
5. Redirecting to relevant site sections

SCOPE: Only discuss Brandon's real estate business. Never act as general assistant or coder. Never give specific legal or financial advice.

PERSONALITY: Friendly, professional, warm, concise, proactive about booking.

CONTACT: Phone (978) 987-2806 | Email info@SoldWithSweeney.com | 101 Broadway Rd #21, Dracut, MA"""

async def chat_response(messages: list[dict], use_pro: bool = False) -> str:
    model_name = "gemini-1.5-pro" if use_pro else "gemini-1.5-flash"
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=CHATBOT_SYSTEM_PROMPT,
    )
    history = []
    for msg in messages[:-1]:
        history.append({"role": msg["role"], "parts": [msg["content"]]})
    chat = model.start_chat(history=history)
    response = await chat.send_message_async(messages[-1]["content"])
    return response.text

async def generate_text(prompt: str, use_pro: bool = True) -> str:
    model_name = "gemini-1.5-pro" if use_pro else "gemini-1.5-flash"
    model = genai.GenerativeModel(model_name)
    response = await model.generate_content_async(prompt)
    return response.text
```

- [ ] Implement `backend/routers/chat.py`:
```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models.lead import Lead
from services.gemini import chat_response
import json

router = APIRouter()

class Message(BaseModel):
    role: str  # "user" or "model"
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    lead_context: dict = {}

class ChatResponse(BaseModel):
    reply: str

@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    msgs = [{"role": m.role, "content": m.content} for m in req.messages]
    reply = await chat_response(msgs)
    return ChatResponse(reply=reply)

@router.post("/lead")
async def capture_lead_from_chat(
    name: str, email: str, phone: str = None, lead_type: str = "general",
    db: AsyncSession = Depends(get_db)
):
    lead = Lead(name=name, email=email, phone=phone, source="chatbot", lead_type=lead_type, metadata_="{}")
    db.add(lead)
    await db.flush()
    return {"id": lead.id, "message": "Lead captured"}
```

- [ ] Commit:
```bash
git add backend/services/gemini.py backend/routers/chat.py
git commit -m "feat: Gemini chatbot service and chat API"
```

---

### Task 9: Seller property evaluator service

**Files:**
- Create: `backend/services/evaluator_service.py`
- Implement: `backend/routers/evaluator.py`

- [ ] Create `backend/services/evaluator_service.py`:
```python
from services.gemini import generate_text
import httpx

async def geocode_address(address: str) -> dict:
    """Basic geocode using nominatim (free) — replace with Google Maps if key available."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "SoldWithSweeney/1.0"}
        )
        results = resp.json()
        if results:
            return {"lat": results[0]["lat"], "lon": results[0]["lon"], "display": results[0]["display_name"]}
    return {}

async def evaluate_property(data: dict) -> dict:
    prompt = f"""You are a real estate valuation assistant for Brandon Sweeney, REALTOR® in MA/NH.

A seller has provided the following property details:
- Address: {data.get('address', 'Unknown')}
- Property type: {data.get('property_type', 'Unknown')}
- Bedrooms: {data.get('bedrooms', 'Unknown')}
- Bathrooms: {data.get('bathrooms', 'Unknown')}
- Square footage: {data.get('sqft', 'Unknown')}
- Year built: {data.get('year_built', 'Unknown')}
- Condition: {data.get('condition', 'Unknown')}
- Recent upgrades: {data.get('upgrades', 'None')}

Based on general MA/NH market knowledge for the Merrimack Valley region, provide:
1. An estimated value range (e.g. "$450,000 – $490,000")
2. Confidence level: Low, Medium, or High
3. A 2-3 sentence plain-English explanation of what's driving the estimate
4. 3-4 key factors affecting value

Respond in this exact JSON format:
{{
  "range_low": 450000,
  "range_high": 490000,
  "confidence": "Medium",
  "explanation": "...",
  "key_factors": ["...", "...", "..."]
}}

Important: This is an AI estimate, not a formal appraisal. Be conservative and honest about uncertainty."""

    text = await generate_text(prompt, use_pro=True)
    # Extract JSON from response
    import re, json
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        return json.loads(match.group())
    return {"range_low": 0, "range_high": 0, "confidence": "Low", "explanation": "Unable to generate estimate.", "key_factors": []}
```

- [ ] Implement `backend/routers/evaluator.py`:
```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models.lead import Lead
from services.evaluator_service import evaluate_property, geocode_address

router = APIRouter()

class EvaluatorRequest(BaseModel):
    address: Optional[str] = None
    property_type: str
    bedrooms: int
    bathrooms: float
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    condition: str
    upgrades: Optional[List[str]] = []
    # Lead capture
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

@router.post("/")
async def evaluate(req: EvaluatorRequest, db: AsyncSession = Depends(get_db)):
    data = req.model_dump()

    # Capture lead if contact info provided
    if req.email:
        lead = Lead(name=req.name or "", email=req.email, phone=req.phone, source="evaluator", lead_type="seller", metadata_="{}")
        db.add(lead)

    geo = {}
    if req.address:
        geo = await geocode_address(req.address)

    result = await evaluate_property(data)
    result["address_display"] = geo.get("display", req.address)
    result["coordinates"] = {"lat": geo.get("lat"), "lon": geo.get("lon")}
    result["disclaimer"] = "This is an AI-assisted estimate, not a formal appraisal. For an accurate valuation, book a meeting with Brandon."
    return result
```

- [ ] Commit:
```bash
git add backend/services/evaluator_service.py backend/routers/evaluator.py
git commit -m "feat: seller property evaluator API with Gemini AI"
```

---

### Task 10: Investor analysis service

**Files:**
- Create: `backend/services/investor_service.py`
- Implement: `backend/routers/investor.py`

- [ ] Create `backend/services/investor_service.py`:
```python
from services.gemini import generate_text
import json, re

async def generate_investor_analysis(inputs: dict, metrics: dict) -> dict:
    prompt = f"""You are a real estate investment analyst assistant for Brandon Sweeney, REALTOR® and investor in MA/NH.

A user has submitted an investment property analysis with these inputs:
{json.dumps(inputs, indent=2)}

The calculated basic metrics are:
{json.dumps(metrics, indent=2)}

Generate a comprehensive investor report including:
1. Plain-English AI explanation (3-4 paragraphs) of the deal quality, key risks, and strengths
2. Hold period scenarios for 3, 5, 7, and 10 years showing: equity built, cumulative cash flow, projected exit value (assume 3% annual appreciation if not specified)
3. Exit scenario comparison: Sell at end of hold / Refinance and hold / 1031 exchange consideration
4. Expense sensitivity: What happens to monthly cash flow if taxes +10%, vacancy goes to 10%, rents drop 5%
5. Deal verdict: STRONG / MODERATE / WEAK with brief reasoning

Respond in JSON format:
{{
  "ai_explanation": "...",
  "hold_scenarios": [
    {{"years": 3, "equity": 0, "cumulative_cash_flow": 0, "exit_value": 0}},
    ...
  ],
  "exit_comparison": {{
    "sell": "...",
    "refinance": "...",
    "exchange_1031": "..."
  }},
  "sensitivity": {{
    "tax_increase_10pct": 0,
    "vacancy_10pct": 0,
    "rent_drop_5pct": 0
  }},
  "verdict": "MODERATE",
  "verdict_reason": "..."
}}"""

    text = await generate_text(prompt, use_pro=True)
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        return json.loads(match.group())
    return {"ai_explanation": "Analysis unavailable.", "verdict": "UNKNOWN"}
```

- [ ] Implement `backend/routers/investor.py`:
```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models.lead import Lead
from services.investor_service import generate_investor_analysis

router = APIRouter()

class InvestorInputs(BaseModel):
    # Property
    address: Optional[str] = None
    property_type: str = "single_family"
    units: int = 1
    # Financials
    purchase_price: float
    down_payment_pct: float = 20.0
    interest_rate: float = 7.0
    loan_term_years: int = 30
    monthly_rent_total: float
    rehab_costs: float = 0
    annual_taxes: float = 0
    annual_insurance: float = 0
    monthly_maintenance: float = 0
    vacancy_rate_pct: float = 5.0
    mgmt_fee_pct: float = 0.0
    hold_years: int = 5
    appreciation_rate_pct: float = 3.0
    # Lead
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

def calculate_metrics(inp: InvestorInputs) -> dict:
    loan_amount = inp.purchase_price * (1 - inp.down_payment_pct / 100)
    down_payment = inp.purchase_price * (inp.down_payment_pct / 100)
    monthly_rate = inp.interest_rate / 100 / 12
    n = inp.loan_term_years * 12
    if monthly_rate > 0:
        mortgage = loan_amount * (monthly_rate * (1 + monthly_rate)**n) / ((1 + monthly_rate)**n - 1)
    else:
        mortgage = loan_amount / n

    gross_rent = inp.monthly_rent_total
    vacancy_loss = gross_rent * (inp.vacancy_rate_pct / 100)
    effective_rent = gross_rent - vacancy_loss
    mgmt_fee = effective_rent * (inp.mgmt_fee_pct / 100)
    monthly_tax = inp.annual_taxes / 12
    monthly_insurance = inp.annual_insurance / 12
    total_expenses = mgmt_fee + monthly_tax + monthly_insurance + inp.monthly_maintenance
    noi = effective_rent - total_expenses
    cash_flow = noi - mortgage
    total_cash_required = down_payment + inp.rehab_costs + (inp.purchase_price * 0.03)  # approx closing
    cap_rate = (noi * 12) / inp.purchase_price * 100 if inp.purchase_price > 0 else 0
    coc = (cash_flow * 12) / total_cash_required * 100 if total_cash_required > 0 else 0

    return {
        "monthly_gross_rent": round(gross_rent, 2),
        "monthly_mortgage": round(mortgage, 2),
        "monthly_noi": round(noi, 2),
        "monthly_cash_flow": round(cash_flow, 2),
        "cap_rate_pct": round(cap_rate, 2),
        "cash_on_cash_pct": round(coc, 2),
        "total_cash_required": round(total_cash_required, 2),
        "down_payment": round(down_payment, 2),
        "loan_amount": round(loan_amount, 2),
    }

@router.post("/calculate")
async def calculate(inp: InvestorInputs, db: AsyncSession = Depends(get_db)):
    metrics = calculate_metrics(inp)
    return {"metrics": metrics}

@router.post("/analyze")
async def full_analysis(inp: InvestorInputs, db: AsyncSession = Depends(get_db)):
    """Gated: full AI analysis — called after meeting booked."""
    metrics = calculate_metrics(inp)
    if inp.email:
        lead = Lead(name=inp.name or "", email=inp.email, phone=inp.phone, source="investor_tool", lead_type="investor", metadata_="{}")
        db.add(lead)
    ai_report = await generate_investor_analysis(inp.model_dump(), metrics)
    return {"metrics": metrics, "report": ai_report}
```

- [ ] Commit:
```bash
git add backend/services/investor_service.py backend/routers/investor.py
git commit -m "feat: investor analysis API with Gemini AI report generation"
```

---

### Task 11: Booking + Funnels APIs

**Files:**
- Implement: `backend/routers/booking.py`
- Implement: `backend/routers/funnels.py`
- Create: `backend/services/funnel_service.py`
- Create: `backend/schemas/booking.py`
- Create: `backend/schemas/funnel.py`

- [ ] Create `backend/schemas/booking.py`:
```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class BookingCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    meeting_type: str = "phone"
    context: str = "general"
    scheduled_at: datetime
    notes: Optional[str] = ""

class BookingOut(BaseModel):
    id: int
    name: str
    email: str
    meeting_type: str
    context: str
    scheduled_at: datetime
    class Config:
        from_attributes = True
```

- [ ] Implement `backend/routers/booking.py`:
```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models.booking import Booking
from models.lead import Lead
from schemas.booking import BookingCreate, BookingOut

router = APIRouter()

@router.post("/", response_model=BookingOut)
async def create_booking(data: BookingCreate, db: AsyncSession = Depends(get_db)):
    # Upsert lead
    result = await db.execute(select(Lead).where(Lead.email == data.email))
    lead = result.scalar_one_or_none()
    if not lead:
        lead = Lead(name=data.name, email=data.email, phone=data.phone, source="booking", lead_type=data.context, metadata_="{}")
        db.add(lead)
        await db.flush()
    else:
        lead.routing_status = "booked"

    booking = Booking(
        lead_id=lead.id,
        name=data.name, email=data.email, phone=data.phone,
        meeting_type=data.meeting_type, context=data.context,
        scheduled_at=data.scheduled_at, notes=data.notes,
    )
    db.add(booking)
    await db.flush()
    await db.refresh(booking)
    return booking

@router.get("/available-slots")
async def available_slots():
    """Placeholder — integrate with Google Calendar in Phase 6."""
    from datetime import datetime, timedelta
    slots = []
    base = datetime.utcnow().replace(hour=9, minute=0, second=0, microsecond=0)
    for i in range(14):
        day = base + timedelta(days=i+1)
        if day.weekday() < 5:  # Mon-Fri
            for h in [9, 10, 11, 14, 15, 16]:
                slots.append((day + timedelta(hours=h - 9)).isoformat())
    return {"slots": slots[:20]}
```

- [ ] Create `backend/services/funnel_service.py`:
```python
from services.gemini import generate_text
import json, re

async def generate_funnel_content(title: str, audience: str, description: str, cta_text: str) -> dict:
    prompt = f"""Generate a landing page for Brandon Sweeney's real estate business.

Details:
- Title: {title}
- Audience: {audience}
- Description: {description}
- CTA: {cta_text}

Brandon Sweeney is the 2025 NEAR REALTOR® Of The Year, CEO of Sold With Sweeney & Co., Keller Williams Realty Success.

Generate structured content sections in JSON:
{{
  "hero_headline": "...",
  "hero_subtext": "...",
  "details_heading": "...",
  "details_body": "...",
  "value_props": ["...", "...", "..."],
  "testimonial": "...",
  "cta_headline": "...",
  "cta_subtext": "..."
}}"""
    text = await generate_text(prompt, use_pro=True)
    match = re.search(r'\{{[\s\S]*\}}', text)
    if match:
        return json.loads(match.group())
    return {"hero_headline": title, "hero_subtext": description, "value_props": [], "cta_headline": cta_text, "cta_subtext": ""}
```

- [ ] Create `backend/schemas/funnel.py`:
```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class FunnelCreate(BaseModel):
    title: str
    audience: str = "general"
    event_date: Optional[datetime] = None
    description: str = ""
    cta_text: str = "Register Now"
    video_url: Optional[str] = None
    lead_routing: str = "dashboard"

class FunnelOut(BaseModel):
    id: int
    title: str
    slug: str
    audience: str
    status: str
    registrations: int
    generated_content: str
    created_at: datetime
    class Config:
        from_attributes = True
```

- [ ] Implement `backend/routers/funnels.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import re, json
from database import get_db
from models.funnel import Funnel
from models.lead import Lead
from schemas.funnel import FunnelCreate, FunnelOut
from services.funnel_service import generate_funnel_content
from middleware.auth import require_admin

router = APIRouter()

def slugify(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

@router.post("/", response_model=FunnelOut)
async def create_funnel(data: FunnelCreate, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    slug = slugify(data.title)
    content = await generate_funnel_content(data.title, data.audience, data.description, data.cta_text)
    funnel = Funnel(
        title=data.title, slug=slug, audience=data.audience,
        description=data.description, cta_text=data.cta_text,
        video_url=data.video_url, lead_routing=data.lead_routing,
        generated_content=json.dumps(content),
    )
    db.add(funnel)
    await db.flush()
    await db.refresh(funnel)
    return funnel

@router.get("/", response_model=List[FunnelOut])
async def list_funnels(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    result = await db.execute(select(Funnel))
    return result.scalars().all()

@router.get("/public/{slug}")
async def get_funnel_public(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Funnel).where(Funnel.slug == slug, Funnel.status == "published"))
    funnel = result.scalar_one_or_none()
    if not funnel: raise HTTPException(404, "Funnel not found")
    content = json.loads(funnel.generated_content)
    return {"funnel": {"id": funnel.id, "title": funnel.title, "audience": funnel.audience, "cta_text": funnel.cta_text}, "content": content}

@router.patch("/{funnel_id}/publish")
async def publish_funnel(funnel_id: int, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    result = await db.execute(select(Funnel).where(Funnel.id == funnel_id))
    funnel = result.scalar_one_or_none()
    if not funnel: raise HTTPException(404)
    funnel.status = "published" if funnel.status != "published" else "unpublished"
    return {"status": funnel.status}

@router.post("/{slug}/register")
async def register_funnel(slug: str, name: str, email: str, phone: str = None, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Funnel).where(Funnel.slug == slug))
    funnel = result.scalar_one_or_none()
    if not funnel: raise HTTPException(404)
    lead = Lead(name=name, email=email, phone=phone, source=f"funnel:{slug}", lead_type=funnel.audience, metadata_="{}")
    db.add(lead)
    funnel.registrations = (funnel.registrations or 0) + 1
    return {"success": True}
```

- [ ] Commit:
```bash
git add backend/routers/booking.py backend/routers/funnels.py backend/services/funnel_service.py backend/schemas/
git commit -m "feat: booking, funnels, and funnel AI generation APIs"
```

---

## Phase 4: Frontend Layout & Shared Components

### Task 12: Root layout, Navbar, Footer

**Files:**
- Create: `frontend/src/app/layout.tsx`
- Create: `frontend/src/components/layout/Navbar.tsx`
- Create: `frontend/src/components/layout/Footer.tsx`

- [ ] Create `frontend/src/components/layout/Navbar.tsx`:
```tsx
'use client';
import Link from 'next/link';
import Image from 'next/image';
import { useState } from 'react';

const links = [
  { href: '/buy', label: 'Buy' },
  { href: '/sell', label: 'Sell' },
  { href: '/invest', label: 'Invest' },
  { href: '/about', label: 'About' },
];

export default function Navbar() {
  const [open, setOpen] = useState(false);
  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-black/80 backdrop-blur-md border-b border-dark-border">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 flex items-center justify-between h-16">
        <Link href="/" className="flex items-center gap-3">
          <Image src="/logos/Sold With Sweeney Primary Logo Transparent Color.p.png" alt="Sold With Sweeney" width={120} height={40} className="h-10 w-auto object-contain" />
        </Link>
        <div className="hidden md:flex items-center gap-8">
          {links.map(l => (
            <Link key={l.href} href={l.href} className="text-sm font-500 text-white hover:text-gold transition-colors">{l.label}</Link>
          ))}
          <Link href="/sell#evaluator" className="bg-gold text-black px-4 py-2 rounded text-sm font-semibold hover:bg-gold-hover transition-colors">
            Book Brandon
          </Link>
        </div>
        <button className="md:hidden text-white" onClick={() => setOpen(!open)}>
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={open ? "M6 18L18 6M6 6l12 12" : "M4 6h16M4 12h16M4 18h16"} />
          </svg>
        </button>
      </div>
      {open && (
        <div className="md:hidden bg-dark-card border-t border-dark-border px-4 py-4 flex flex-col gap-4">
          {links.map(l => (
            <Link key={l.href} href={l.href} className="text-white text-sm font-medium" onClick={() => setOpen(false)}>{l.label}</Link>
          ))}
          <Link href="/sell#evaluator" className="bg-gold text-black px-4 py-2 rounded text-sm font-semibold text-center" onClick={() => setOpen(false)}>Book Brandon</Link>
        </div>
      )}
    </nav>
  );
}
```

- [ ] Create `frontend/src/components/layout/Footer.tsx`:
```tsx
import Link from 'next/link';
import Image from 'next/image';

const socials = [
  { label: 'Facebook', href: 'https://www.facebook.com/SoldWithSweeneyCo', icon: 'fb' },
  { label: 'Instagram', href: 'https://www.instagram.com/soldwithsweeneyco', icon: 'ig' },
  { label: 'YouTube', href: 'https://www.youtube.com/@soldwithsweeneyco', icon: 'yt' },
  { label: 'TikTok', href: 'https://www.tiktok.com/@soldwithsweeneyco', icon: 'tt' },
  { label: 'LinkedIn', href: 'https://www.linkedin.com/in/soldwithsweeneyco/', icon: 'li' },
];

const legal = [
  { label: 'Terms of Use', href: 'https://legal.kw.com/termsofuse' },
  { label: 'Privacy Policy', href: 'https://legal.kw.com/privacy-policy' },
  { label: 'Cookie Policy', href: 'https://legal.kw.com/cookie-policy' },
  { label: 'DMCA', href: 'https://legal.kw.com/dmca' },
  { label: 'Fair Housing', href: 'https://legal.kw.com/fairhousing' },
  { label: 'Accessibility', href: 'https://legal.kw.com/accessibility' },
];

export default function Footer() {
  return (
    <footer className="bg-dark-surface border-t border-dark-border mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-12">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-8">
          {/* Brand */}
          <div>
            <Image src="/logos/Sold With Sweeney Primary Logo Transparent Color.p.png" alt="SWS" width={140} height={50} className="h-12 w-auto object-contain mb-4" />
            <p className="text-gray-400 text-sm">Sold With Sweeney & Co.<br />Powered by Keller Williams Realty Success</p>
          </div>
          {/* Contact */}
          <div>
            <h4 className="text-gold font-semibold mb-3 text-sm uppercase tracking-wider">Contact</h4>
            <p className="text-gray-400 text-sm space-y-1">
              <span className="block">Brandon Sweeney, REALTOR®</span>
              <span className="block">101 Broadway Rd. #21, Dracut, MA 01826</span>
              <span className="block">(978) 987-2806</span>
              <span className="block">info@SoldWithSweeney.com</span>
            </p>
          </div>
          {/* Socials + Logos */}
          <div>
            <h4 className="text-gold font-semibold mb-3 text-sm uppercase tracking-wider">Connect</h4>
            <div className="flex gap-3 mb-4 flex-wrap">
              {socials.map(s => (
                <a key={s.icon} href={s.href} target="_blank" rel="noopener noreferrer"
                  className="w-9 h-9 rounded-full border border-dark-border flex items-center justify-center text-gray-400 hover:text-gold hover:border-gold transition-colors text-xs font-bold">
                  {s.icon.toUpperCase()}
                </a>
              ))}
            </div>
            <div className="flex gap-3 items-center">
              <Image src="/logos/KWRS White.png" alt="KW" width={60} height={30} className="h-7 w-auto object-contain opacity-70" />
              <Image src="/logos/Designations-Associations/NEAR.png" alt="NEAR" width={40} height={40} className="h-8 w-auto object-contain opacity-70" />
            </div>
          </div>
        </div>
        {/* Legal */}
        <div className="border-t border-dark-border pt-6">
          <div className="flex flex-wrap gap-x-4 gap-y-2 mb-3">
            {legal.map(l => (
              <a key={l.href} href={l.href} target="_blank" rel="noopener noreferrer" className="text-xs text-gray-500 hover:text-gold transition-colors">{l.label}</a>
            ))}
          </div>
          <p className="text-xs text-gray-600">
            MA Associate Broker #9589032 | NH Salesperson #072734 | © {new Date().getFullYear()} Sold With Sweeney & Co. All rights reserved.
            REALTOR® is a registered trademark of the National Association of REALTORS®.
          </p>
        </div>
      </div>
    </footer>
  );
}
```

- [ ] Update `frontend/src/app/layout.tsx`:
```tsx
import type { Metadata } from 'next';
import '../styles/globals.css';
import '../styles/animations.css';
import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';

export const metadata: Metadata = {
  title: 'Sold With Sweeney & Co. | Brandon Sweeney, REALTOR®',
  description: 'NOT your AVERAGE, award winning, philanthropic REALTOR® OF THE YEAR \'25. Serving MA & NH buyers, sellers, and investors.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-black text-white font-sans">
        <Navbar />
        <main className="pt-16">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
```

- [ ] Create `frontend/src/components/shared/CTAButton.tsx`:
```tsx
import Link from 'next/link';

interface Props {
  href?: string;
  onClick?: () => void;
  children: React.ReactNode;
  variant?: 'gold' | 'outline';
  className?: string;
}

export default function CTAButton({ href, onClick, children, variant = 'gold', className = '' }: Props) {
  const base = 'inline-flex items-center justify-center px-6 py-3 rounded font-semibold text-sm transition-all duration-200';
  const styles = variant === 'gold'
    ? 'bg-gold text-black hover:bg-gold-hover shadow-lg hover:shadow-gold/20'
    : 'border border-gold text-gold hover:bg-gold hover:text-black';
  const cls = `${base} ${styles} ${className}`;
  if (href) return <Link href={href} className={cls}>{children}</Link>;
  return <button onClick={onClick} className={cls}>{children}</button>;
}
```

- [ ] Create `frontend/src/components/shared/HalftoneOverlay.tsx`:
```tsx
export default function HalftoneOverlay({ opacity = 0.05 }: { opacity?: number }) {
  return (
    <div
      className="absolute inset-0 pointer-events-none"
      style={{
        backgroundImage: `radial-gradient(circle, #eac469 1px, transparent 1px)`,
        backgroundSize: '20px 20px',
        opacity,
      }}
    />
  );
}
```

- [ ] Create `frontend/src/components/shared/ReviewCard.tsx`:
```tsx
interface Props {
  quote: string;
  author: string;
  location: string;
}

export default function ReviewCard({ quote, author, location }: Props) {
  return (
    <div className="bg-dark-card border border-dark-border rounded-lg p-6 hover:border-gold/30 transition-colors">
      <div className="flex gap-1 mb-3">
        {[...Array(5)].map((_, i) => (
          <svg key={i} className="w-4 h-4 text-gold fill-gold" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/></svg>
        ))}
      </div>
      <p className="text-gray-300 text-sm leading-relaxed mb-4 italic">"{quote}"</p>
      <p className="text-gold text-sm font-semibold">— {author}, {location}</p>
    </div>
  );
}
```

- [ ] Create `frontend/src/components/shared/LeadCaptureForm.tsx`:
```tsx
'use client';
import { useState } from 'react';
import CTAButton from './CTAButton';
import { apiPost } from '@/lib/api';

interface Props {
  source: string;
  leadType: string;
  ctaText?: string;
  onSuccess?: () => void;
}

export default function LeadCaptureForm({ source, leadType, ctaText = 'Get In Touch', onSuccess }: Props) {
  const [form, setForm] = useState({ name: '', email: '', phone: '' });
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await apiPost('/api/v1/leads/', { ...form, source, lead_type: leadType });
      setDone(true);
      onSuccess?.();
    } catch {}
    setLoading(false);
  }

  if (done) return (
    <div className="text-center py-4">
      <p className="text-gold font-semibold">Thanks! Brandon will be in touch shortly.</p>
    </div>
  );

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <input required placeholder="Full Name" value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
        className="bg-dark-card border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
      <input required type="email" placeholder="Email Address" value={form.email} onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
        className="bg-dark-card border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
      <input type="tel" placeholder="Phone (optional)" value={form.phone} onChange={e => setForm(p => ({ ...p, phone: e.target.value }))}
        className="bg-dark-card border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
      <CTAButton className="w-full">{loading ? 'Submitting...' : ctaText}</CTAButton>
    </form>
  );
}
```

- [ ] Commit:
```bash
git add frontend/src/
git commit -m "feat: Navbar, Footer, shared components (CTAButton, ReviewCard, LeadCaptureForm, HalftoneOverlay)"
```

---

## Phase 5: Home Page

### Task 13: Hero section with video background

**Files:**
- Create: `frontend/src/components/home/Hero.tsx`
- Update: `frontend/src/app/page.tsx`

- [ ] Create `frontend/src/components/home/Hero.tsx`:
```tsx
'use client';
import { useEffect, useRef } from 'react';
import Link from 'next/link';
import CTAButton from '@/components/shared/CTAButton';

export default function Hero() {
  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => { videoRef.current?.play(); }, []);

  return (
    <section className="relative h-screen min-h-[600px] flex items-center justify-center overflow-hidden">
      {/* Video background */}
      <video
        ref={videoRef}
        className="absolute inset-0 w-full h-full object-cover"
        src="/assets/aerial_drone_shot.mp4"
        autoPlay muted loop playsInline
        poster="/headshots/Brandon Sweeney Headshot.jpg"
      />
      {/* Gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-b from-black/60 via-black/40 to-black/80" />
      {/* Radial vignette */}
      <div className="absolute inset-0" style={{background: 'radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,0.7) 100%)'}} />

      {/* Content */}
      <div className="relative z-10 text-center px-4 max-w-5xl mx-auto">
        <p className="text-gold text-sm font-semibold tracking-[0.2em] uppercase mb-4 animate-fade-up">
          NEAR REALTOR® Of The Year 2025 | Keller Williams Realty Success
        </p>
        <h1 className="text-4xl sm:text-5xl md:text-7xl font-black text-white mb-6 leading-tight animate-fade-up" style={{animationDelay: '0.1s'}}>
          NOT Your<br />
          <span className="text-gold">AVERAGE</span><br />
          REALTOR®
        </h1>
        <p className="text-gray-300 text-lg sm:text-xl mb-10 max-w-2xl mx-auto animate-fade-up" style={{animationDelay: '0.2s'}}>
          Award-winning, philanthropic, results-driven. Serving buyers, sellers, and investors across MA & NH.
        </p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center animate-fade-up" style={{animationDelay: '0.3s'}}>
          <CTAButton href="/buy">I Want to Buy</CTAButton>
          <CTAButton href="/sell" variant="outline">I Want to Sell</CTAButton>
          <CTAButton href="/invest" variant="outline">I'm an Investor</CTAButton>
        </div>
      </div>

      {/* Scroll indicator */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 text-gray-400 text-xs animate-bounce">
        <span>Scroll</span>
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </section>
  );
}
```

- [ ] Create `frontend/src/components/home/TrustSection.tsx`:
```tsx
import ReviewCard from '@/components/shared/ReviewCard';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';
import Image from 'next/image';

const reviews = [
  { quote: "Brandon went above and beyond throughout this process... He's a wonderful Realtor and an even better person.", author: "Adam P", location: "Lowell, MA" },
  { quote: "Working with Brandon was amazing! He made a generally stressful process feel much easier by being there for us every step of the way.", author: "Jacqui", location: "Westford, MA" },
  { quote: "Brandon was very responsive, very professional, presented a great marketing plan with a great price strategy.", author: "Valerie W", location: "Nashua, NH" },
  { quote: "Besides the outstanding assistance with valuing and marketing the property — the one that really stands out is patience.", author: "Jim R", location: "Dracut, MA" },
];

const stats = [
  { value: "4.9/5.0", label: "Satisfaction" },
  { value: "5.0/5.0", label: "Performance" },
  { value: "5.0/5.0", label: "Recommendation" },
];

export default function TrustSection() {
  return (
    <section className="relative py-20 bg-dark-surface">
      <HalftoneOverlay opacity={0.04} />
      <div className="max-w-7xl mx-auto px-4 sm:px-6">
        {/* Stats */}
        <div className="flex flex-col sm:flex-row justify-center gap-12 mb-16 text-center">
          {stats.map(s => (
            <div key={s.label}>
              <p className="text-4xl font-black text-gold">{s.value}</p>
              <p className="text-gray-400 text-sm mt-1">{s.label}</p>
            </div>
          ))}
        </div>

        {/* Heading */}
        <div className="text-center mb-12">
          <p className="text-gold text-xs uppercase tracking-widest mb-2 font-semibold">What Clients Say</p>
          <h2 className="text-3xl sm:text-4xl font-bold text-white">Real People. Real Results.</h2>
        </div>

        {/* Reviews grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
          {reviews.map(r => <ReviewCard key={r.author} {...r} />)}
        </div>

        {/* Badges */}
        <div className="flex flex-wrap justify-center items-center gap-6 mt-8">
          <Image src="/logos/Designations-Associations/NEAR.png" alt="NEAR" width={60} height={60} className="h-12 w-auto object-contain opacity-80" />
          <Image src="/logos/Designations-Associations/MAR-Logo-Color-VERT-300dpi.png" alt="MAR" width={60} height={60} className="h-12 w-auto object-contain opacity-80" />
          <Image src="/logos/Designations-Associations/National_Association_of_REALTORS_Logo.svg.png" alt="NAR" width={60} height={60} className="h-12 w-auto object-contain opacity-80" />
          <Image src="/logos/Designations-Associations/Green.jpg" alt="GREEN" width={60} height={60} className="h-12 w-auto object-contain opacity-80 rounded" />
          <Image src="/logos/KWRS White.png" alt="KW" width={80} height={40} className="h-10 w-auto object-contain opacity-80" />
          <span className="text-gold font-semibold text-sm border border-gold/30 px-3 py-1 rounded">REALTOR® Of The Year 2025</span>
        </div>
      </div>
    </section>
  );
}
```

- [ ] Create `frontend/src/components/home/AudienceCards.tsx`:
```tsx
import CTAButton from '@/components/shared/CTAButton';

const cards = [
  {
    icon: '🏡',
    title: 'Buying a Home',
    subtitle: 'For Buyers',
    description: "From pre-approval to closing day — Brandon guides first-time buyers and seasoned buyers alike through MA & NH's competitive market.",
    cta: 'Start Your Home Search',
    href: '/buy',
  },
  {
    icon: '💰',
    title: 'Selling Your Home',
    subtitle: 'For Sellers',
    description: "Professional photography, network marketing, and a proven strategy that sells your home quickly and above asking price.",
    cta: 'Get Your Free Estimate',
    href: '/sell',
  },
  {
    icon: '📊',
    title: 'Real Estate Investment',
    subtitle: 'For Investors',
    description: "Run the numbers on any deal. From fix & flip to buy & hold — Brandon has done it himself and can help you analyze your next investment.",
    cta: 'Analyze a Deal',
    href: '/invest',
  },
];

export default function AudienceCards() {
  return (
    <section className="py-20 px-4 max-w-7xl mx-auto">
      <div className="text-center mb-12">
        <p className="text-gold text-xs uppercase tracking-widest mb-2 font-semibold">How Can We Help?</p>
        <h2 className="text-3xl sm:text-4xl font-bold text-white">Your Real Estate Path Starts Here</h2>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
        {cards.map(card => (
          <div key={card.title} className="bg-dark-card border border-dark-border rounded-xl p-8 hover:border-gold/40 hover:shadow-lg hover:shadow-gold/5 transition-all group">
            <div className="text-4xl mb-4">{card.icon}</div>
            <p className="text-gold text-xs uppercase tracking-widest mb-1 font-semibold">{card.subtitle}</p>
            <h3 className="text-xl font-bold text-white mb-3">{card.title}</h3>
            <p className="text-gray-400 text-sm leading-relaxed mb-6">{card.description}</p>
            <CTAButton href={card.href} variant="outline" className="w-full group-hover:bg-gold group-hover:text-black">{card.cta}</CTAButton>
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] Create `frontend/src/components/home/GivingBack.tsx`:
```tsx
import CTAButton from '@/components/shared/CTAButton';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';

export default function GivingBack() {
  return (
    <section className="relative py-20 bg-dark-card border-y border-dark-border overflow-hidden">
      <HalftoneOverlay opacity={0.05} />
      <div className="relative z-10 max-w-4xl mx-auto px-4 text-center">
        <p className="text-gold text-xs uppercase tracking-widest mb-3 font-semibold">Giving Back</p>
        <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">MS is BS New England</h2>
        <p className="text-gray-300 text-lg mb-4">
          Founded in 2015, Brandon started MS is BS New England Inc. as a college assignment — it became a movement.
        </p>
        <p className="text-gold text-2xl font-bold mb-4">$300,000+ in grants to local MS warriors</p>
        <p className="text-gray-400 text-sm mb-8 max-w-2xl mx-auto">
          Brandon's father John, uncle Gary, and late grandmother Rose Sweeney all have or had MS. Every closing creates an opportunity to give back — $100 to your chosen charity or $200 to MS is BS when you close with Brandon.
        </p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <CTAButton href="https://www.MSisBSNewEngland.com" variant="gold">Learn About MS is BS</CTAButton>
          <CTAButton href="/about" variant="outline">Brandon's Story</CTAButton>
        </div>
      </div>
    </section>
  );
}
```

- [ ] Create `frontend/src/components/home/ExplodingHouseScroll.tsx`:
```tsx
'use client';
import { useEffect, useRef, useState } from 'react';

const TOTAL_FRAMES = 60; // adjust after ffmpeg extraction
const texts = [
  { progress: 0.1, headline: "Your Dream Home, Deconstructed", sub: "Every detail matters — from foundation to finish" },
  { progress: 0.5, headline: "Every Layer Has a Story", sub: "Brandon knows what to look for at every step of the process" },
  { progress: 0.85, headline: "Let Brandon Guide You Through", sub: "From inspection to closing — no surprises, just results" },
];

export default function ExplodingHouseScroll() {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [currentText, setCurrentText] = useState(0);
  const [frame, setFrame] = useState(0);
  const frames = useRef<HTMLImageElement[]>([]);
  const loaded = useRef(false);

  useEffect(() => {
    // Preload frames
    const imgs: HTMLImageElement[] = [];
    let loadedCount = 0;
    for (let i = 1; i <= TOTAL_FRAMES; i++) {
      const img = new Image();
      img.src = `/frames/house-blast/frame_${String(i).padStart(4, '0')}.jpg`;
      img.onload = () => {
        loadedCount++;
        if (loadedCount === TOTAL_FRAMES) loaded.current = true;
      };
      imgs.push(img);
    }
    frames.current = imgs;
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx || !frames.current[frame]) return;
    ctx.drawImage(frames.current[frame], 0, 0, canvas.width, canvas.height);
  }, [frame]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const onScroll = () => {
      const rect = container.getBoundingClientRect();
      const progress = Math.max(0, Math.min(1, -rect.top / (rect.height - window.innerHeight)));
      const frameIdx = Math.floor(progress * (TOTAL_FRAMES - 1));
      setFrame(frameIdx);
      const textIdx = texts.findLastIndex(t => progress >= t.progress);
      setCurrentText(Math.max(0, textIdx));
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <div ref={containerRef} className="relative" style={{ height: '300vh' }}>
      <div className="sticky top-0 h-screen flex items-center justify-center overflow-hidden bg-black">
        <canvas ref={canvasRef} width={1920} height={1080} className="w-full h-full object-contain" />
        <div className="absolute inset-0 bg-gradient-to-b from-black/40 via-transparent to-black/40 pointer-events-none" />
        <div className="absolute bottom-20 left-0 right-0 text-center px-4 transition-all duration-500">
          <h2 className="text-3xl sm:text-5xl font-black text-white mb-3">{texts[currentText]?.headline}</h2>
          <p className="text-gray-300 text-lg">{texts[currentText]?.sub}</p>
        </div>
      </div>
    </div>
  );
}
```

- [ ] Update `frontend/src/app/page.tsx`:
```tsx
import Hero from '@/components/home/Hero';
import ExplodingHouseScroll from '@/components/home/ExplodingHouseScroll';
import TrustSection from '@/components/home/TrustSection';
import AudienceCards from '@/components/home/AudienceCards';
import GivingBack from '@/components/home/GivingBack';

export default function Home() {
  return (
    <>
      <Hero />
      <ExplodingHouseScroll />
      <TrustSection />
      <AudienceCards />
      <GivingBack />
    </>
  );
}
```

- [ ] Commit:
```bash
git add frontend/src/app/page.tsx frontend/src/components/home/
git commit -m "feat: home page — hero video, exploding house scroll, trust section, audience cards, giving back"
```

---

## Phase 6: Experience Pages

### Task 14: Buyers Experience page

**Files:**
- Create: `frontend/src/app/buy/page.tsx`
- Create: `frontend/src/components/buyer/MonopolyJourney.tsx`
- Create: `frontend/src/components/buyer/BuyerTeam.tsx`
- Create: `frontend/src/components/buyer/BuyerMistakes.tsx`

- [ ] Create `frontend/src/components/buyer/MonopolyJourney.tsx`:
```tsx
'use client';
import { useState } from 'react';

const phases = [
  {
    name: "Phase 1: The Swiping Phase",
    emoji: "📱",
    color: "from-gold/20 to-gold/5",
    steps: [
      { title: "Pre-Approval for Budget", desc: "Get clear on your budget before falling in love with a home. Work with a lender to get pre-approved so you can move quickly when the right home appears." },
      { title: "Meet with Your REALTOR®", desc: "Brandon will guide you through the MA/NH market, explain the process, and set expectations so there are no surprises." },
      { title: "Utilize Your Pre-Approval", desc: "With your pre-approval letter in hand, you're ready to compete. In today's market, sellers take pre-approved buyers far more seriously." },
    ],
  },
  {
    name: "Phase 2: The Engagement Phase",
    emoji: "💍",
    color: "from-bronze/20 to-bronze/5",
    steps: [
      { title: "Showings & Open Houses", desc: "Tour properties that meet your criteria. Brandon will help you spot red flags, understand what's fixable, and what's a dealbreaker." },
      { title: "Finding the ONE", desc: "When the right home clicks, you'll feel it. Brandon's job is to make sure the numbers and the condition back up the feeling." },
      { title: "Edging Out the Competition", desc: "Brandon crafts competitive offers with strategic contingencies, escalation clauses, and seller-friendly terms that win without overpaying." },
    ],
  },
  {
    name: "Phase 3: The Happily Ever After Phase",
    emoji: "🏡",
    color: "from-green-800/20 to-green-800/5",
    steps: [
      { title: "Home Inspection", desc: "A critical step. Brandon attends every inspection and helps you navigate results — what to negotiate, what to accept, and when to walk away." },
      { title: "3rd Party Appraisal", desc: "Your lender orders an appraisal to confirm value. If it comes in low, Brandon negotiates on your behalf." },
      { title: "Commitment / Clear to Close", desc: "Your lender issues final approval. We're almost there." },
      { title: "Closing Time!", desc: "Sign the docs, get the keys, and welcome home. Brandon is there every step of the way — even after the sale." },
    ],
  },
];

export default function MonopolyJourney() {
  const [openPhase, setOpenPhase] = useState(0);
  return (
    <section className="py-20 px-4 max-w-5xl mx-auto">
      <div className="text-center mb-12">
        <p className="text-gold text-xs uppercase tracking-widest mb-2 font-semibold">Your Journey</p>
        <h2 className="text-3xl sm:text-4xl font-bold text-white">Home Buying in 3 Phases</h2>
        <p className="text-gray-400 mt-3">Think of it like dating — with a lot more paperwork.</p>
      </div>
      <div className="flex flex-col gap-4">
        {phases.map((phase, i) => (
          <div key={i} className={`rounded-xl border border-dark-border overflow-hidden bg-gradient-to-r ${openPhase === i ? phase.color : 'from-dark-card to-dark-card'} transition-all`}>
            <button
              className="w-full flex items-center justify-between p-6 text-left"
              onClick={() => setOpenPhase(openPhase === i ? -1 : i)}
            >
              <div className="flex items-center gap-4">
                <span className="text-3xl">{phase.emoji}</span>
                <h3 className="text-lg font-bold text-white">{phase.name}</h3>
              </div>
              <svg className={`w-5 h-5 text-gold transition-transform ${openPhase === i ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {openPhase === i && (
              <div className="px-6 pb-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
                {phase.steps.map((step, j) => (
                  <div key={j} className="bg-black/30 rounded-lg p-4 border border-dark-border">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="w-6 h-6 rounded-full bg-gold/20 text-gold text-xs flex items-center justify-center font-bold">{j + 1}</span>
                      <h4 className="text-white text-sm font-semibold">{step.title}</h4>
                    </div>
                    <p className="text-gray-400 text-xs leading-relaxed">{step.desc}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] Create `frontend/src/components/buyer/BuyerMistakes.tsx`:
```tsx
const mistakes = [
  { title: "Shopping before pre-approval", fix: "Always get pre-approved first — it defines your budget and signals to sellers you're serious." },
  { title: "Using all savings", fix: "Budget for closing costs (2-5%), moving costs, initial repairs, and an emergency fund AFTER your down payment." },
  { title: "Buying with the listing agent", fix: "The seller's agent works for the seller. You deserve dedicated representation — at no cost to you as a buyer." },
  { title: "Not comparing multiple lenders", fix: "Shop at least 3 lenders. A 0.5% rate difference on a $400K loan saves tens of thousands over 30 years." },
];

export default function BuyerMistakes() {
  return (
    <section className="py-16 px-4 max-w-5xl mx-auto">
      <div className="text-center mb-10">
        <p className="text-gold text-xs uppercase tracking-widest mb-2 font-semibold">Avoid These</p>
        <h2 className="text-2xl sm:text-3xl font-bold text-white">Common Buyer Mistakes</h2>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
        {mistakes.map(m => (
          <div key={m.title} className="bg-dark-card border border-red-900/30 rounded-xl p-6">
            <div className="flex items-start gap-3 mb-3">
              <span className="text-red-400 mt-0.5">✗</span>
              <h3 className="text-white font-semibold text-sm">{m.title}</h3>
            </div>
            <div className="flex items-start gap-3">
              <span className="text-gold mt-0.5">✓</span>
              <p className="text-gray-400 text-sm leading-relaxed">{m.fix}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] Create `frontend/src/app/buy/page.tsx`:
```tsx
import CTAButton from '@/components/shared/CTAButton';
import MonopolyJourney from '@/components/buyer/MonopolyJourney';
import BuyerMistakes from '@/components/buyer/BuyerMistakes';
import ReviewCard from '@/components/shared/ReviewCard';
import LeadCaptureForm from '@/components/shared/LeadCaptureForm';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';

const team = ["Your REALTOR® (Brandon)", "Lender/Loan Officer", "Real Estate Attorney", "Estate Planning Attorney", "Insurance Agent", "Financial Advisor", "Accountant"];

const buyerReviews = [
  { quote: "Brandon went above and beyond throughout this process. He's a wonderful Realtor and an even better person.", author: "Adam P", location: "Lowell, MA" },
  { quote: "He made a generally stressful process feel much easier by being there for us every step of the way as first time home buyers.", author: "Jacqui", location: "Westford, MA" },
  { quote: "Brandon was an invaluable source of information throughout the entire home buying process.", author: "Corey S", location: "Tyngsboro, MA" },
  { quote: "Brandon was able to get us our dream house at a price far less than we could have imagined.", author: "Erika R", location: "Sandown, NH" },
];

export default function BuyPage() {
  return (
    <div className="bg-black">
      {/* Hero */}
      <section className="relative py-24 px-4 text-center bg-dark-surface overflow-hidden">
        <HalftoneOverlay opacity={0.04} />
        <div className="relative z-10 max-w-3xl mx-auto">
          <p className="text-gold text-xs uppercase tracking-widest mb-3 font-semibold">For Buyers</p>
          <h1 className="text-4xl sm:text-6xl font-black text-white mb-5">Home Buying 101</h1>
          <p className="text-gray-300 text-lg mb-8">A comprehensive journey — from first search to closing day. Brandon has guided hundreds of buyers through MA & NH's most competitive markets.</p>
          <CTAButton href="tel:9789872806" className="text-lg px-8 py-4">Book a Strategy Call</CTAButton>
        </div>
      </section>

      {/* Journey */}
      <MonopolyJourney />

      {/* Winning team */}
      <section className="py-16 px-4 bg-dark-surface">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-10">
            <p className="text-gold text-xs uppercase tracking-widest mb-2 font-semibold">Your Support System</p>
            <h2 className="text-2xl sm:text-3xl font-bold text-white">The Winning Home Buying Team</h2>
          </div>
          <div className="flex flex-wrap justify-center gap-3">
            {team.map(t => (
              <span key={t} className="bg-dark-card border border-dark-border rounded-full px-5 py-2 text-sm text-white">{t}</span>
            ))}
          </div>
        </div>
      </section>

      {/* Mistakes */}
      <BuyerMistakes />

      {/* Reviews */}
      <section className="py-16 px-4 bg-dark-surface">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-10">
            <h2 className="text-2xl sm:text-3xl font-bold text-white">What Buyers Say</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {buyerReviews.map(r => <ReviewCard key={r.author} {...r} />)}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-20 px-4">
        <div className="max-w-lg mx-auto">
          <div className="text-center mb-8">
            <h2 className="text-2xl font-bold text-white mb-2">Ready to Find Your Home?</h2>
            <p className="text-gray-400">Let Brandon know where to start.</p>
          </div>
          <LeadCaptureForm source="buyer-page" leadType="buyer" ctaText="Book a Buyer Strategy Call" />
        </div>
      </section>
    </div>
  );
}
```

- [ ] Commit:
```bash
git add frontend/src/app/buy/ frontend/src/components/buyer/
git commit -m "feat: buyers experience page with journey, team, mistakes, reviews, lead capture"
```

---

### Task 15: Sellers page + Property Evaluator

**Files:**
- Create: `frontend/src/app/sell/page.tsx`
- Create: `frontend/src/components/seller/SellerSteps.tsx`
- Create: `frontend/src/components/seller/PropertyEvaluator.tsx`
- Create: `frontend/src/components/seller/StagingChecklist.tsx`

- [ ] Create `frontend/src/components/seller/SellerSteps.tsx`:
```tsx
const steps = [
  { n: 1, title: "Prepare", desc: "Home tour, listing appointment, and hiring Brandon. We'll discuss pricing strategy, timeline, and what needs to be done before listing." },
  { n: 2, title: "Pre-Listing", desc: "Confirm pricing, stage or virtually stage the home, and create all marketing materials — professional photos, video, flyers, social content." },
  { n: 3, title: "Listing Time", desc: "Your home goes live on the MLS, Zillow, Realtor.com, Trulia, and Brandon's full social media reach. Showings and open houses begin." },
  { n: 4, title: "Offer Process", desc: "Review offers together, navigate contingencies, and go under contract. Brandon handles all negotiation to get you the best terms." },
  { n: 5, title: "Closing Time", desc: "Final prep, closing disclosure review, packing, walkthrough, and closing day. Brandon is there from first call to key handoff." },
];

export default function SellerSteps() {
  return (
    <section className="py-20 px-4 max-w-5xl mx-auto">
      <div className="text-center mb-12">
        <p className="text-gold text-xs uppercase tracking-widest mb-2 font-semibold">The Process</p>
        <h2 className="text-3xl sm:text-4xl font-bold text-white">5 Easy Steps to Sell</h2>
      </div>
      <div className="relative">
        {/* Vertical line */}
        <div className="absolute left-6 top-0 bottom-0 w-px bg-gold/20 hidden sm:block" />
        <div className="flex flex-col gap-8">
          {steps.map(s => (
            <div key={s.n} className="flex gap-6">
              <div className="flex-shrink-0 w-12 h-12 rounded-full bg-gold text-black flex items-center justify-center font-black text-lg z-10">{s.n}</div>
              <div className="bg-dark-card border border-dark-border rounded-xl p-6 flex-1">
                <h3 className="text-white font-bold text-lg mb-2">{s.title}</h3>
                <p className="text-gray-400 text-sm leading-relaxed">{s.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
```

- [ ] Create `frontend/src/components/seller/PropertyEvaluator.tsx`:
```tsx
'use client';
import { useState } from 'react';
import CTAButton from '@/components/shared/CTAButton';
import { apiPost } from '@/lib/api';

type Step = 'form' | 'loading' | 'result';

interface Result {
  range_low: number;
  range_high: number;
  confidence: string;
  explanation: string;
  key_factors: string[];
  disclaimer: string;
  address_display: string;
}

export default function PropertyEvaluator() {
  const [step, setStep] = useState<Step>('form');
  const [result, setResult] = useState<Result | null>(null);
  const [form, setForm] = useState({
    address: '', property_type: 'single_family', bedrooms: 3, bathrooms: 2, sqft: '',
    year_built: '', condition: 'good', upgrades: [] as string[],
    name: '', email: '', phone: '',
  });

  const conditions = ['excellent', 'good', 'fair', 'needs_work'];
  const upgradeOptions = ['Kitchen remodel', 'Bathrooms', 'Roof', 'HVAC', 'Windows', 'Flooring', 'Addition'];

  function toggleUpgrade(u: string) {
    setForm(p => ({ ...p, upgrades: p.upgrades.includes(u) ? p.upgrades.filter(x => x !== u) : [...p.upgrades, u] }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setStep('loading');
    try {
      const res = await apiPost<Result>('/api/v1/evaluator/', { ...form, sqft: form.sqft ? parseInt(form.sqft) : null, year_built: form.year_built ? parseInt(form.year_built) : null });
      setResult(res);
      setStep('result');
    } catch {
      setStep('form');
      alert('Something went wrong. Please try again.');
    }
  }

  const fmt = (n: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);

  return (
    <div id="evaluator" className="bg-dark-card border border-dark-border rounded-2xl p-8 max-w-2xl mx-auto">
      <div className="text-center mb-8">
        <p className="text-gold text-xs uppercase tracking-widest mb-2 font-semibold">AI-Powered</p>
        <h2 className="text-2xl font-bold text-white">What's Your Home Worth?</h2>
        <p className="text-gray-400 text-sm mt-2">Get an instant AI estimate — then book Brandon for the real number.</p>
      </div>

      {step === 'form' && (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <input placeholder="Property Address" value={form.address} onChange={e => setForm(p => ({ ...p, address: e.target.value }))}
            className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
          <select value={form.property_type} onChange={e => setForm(p => ({ ...p, property_type: e.target.value }))}
            className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none">
            <option value="single_family">Single Family</option>
            <option value="multi_family">Multi-Family</option>
            <option value="condo">Condo</option>
            <option value="townhouse">Townhouse</option>
          </select>
          <div className="grid grid-cols-2 gap-4">
            <input type="number" placeholder="Bedrooms" min={1} max={10} value={form.bedrooms} onChange={e => setForm(p => ({ ...p, bedrooms: parseInt(e.target.value) }))}
              className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
            <input type="number" placeholder="Bathrooms" min={1} max={10} step={0.5} value={form.bathrooms} onChange={e => setForm(p => ({ ...p, bathrooms: parseFloat(e.target.value) }))}
              className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <input placeholder="Sq Footage (approx)" value={form.sqft} onChange={e => setForm(p => ({ ...p, sqft: e.target.value }))}
              className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
            <input placeholder="Year Built" value={form.year_built} onChange={e => setForm(p => ({ ...p, year_built: e.target.value }))}
              className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
          </div>
          <div>
            <p className="text-xs text-gray-400 mb-2">Condition</p>
            <div className="flex gap-2 flex-wrap">
              {conditions.map(c => (
                <button type="button" key={c} onClick={() => setForm(p => ({ ...p, condition: c }))}
                  className={`px-3 py-1.5 rounded text-xs font-medium border transition-colors ${form.condition === c ? 'bg-gold text-black border-gold' : 'border-dark-border text-gray-400 hover:border-gold/50'}`}>
                  {c.replace('_', ' ')}
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="text-xs text-gray-400 mb-2">Recent Upgrades</p>
            <div className="flex gap-2 flex-wrap">
              {upgradeOptions.map(u => (
                <button type="button" key={u} onClick={() => toggleUpgrade(u)}
                  className={`px-3 py-1.5 rounded text-xs font-medium border transition-colors ${form.upgrades.includes(u) ? 'bg-gold/20 border-gold text-gold' : 'border-dark-border text-gray-400'}`}>
                  {u}
                </button>
              ))}
            </div>
          </div>
          <div className="border-t border-dark-border pt-4">
            <p className="text-xs text-gray-400 mb-3">Your info (optional — to receive results by email)</p>
            <div className="flex flex-col gap-3">
              <input placeholder="Name" value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
              <input type="email" placeholder="Email" value={form.email} onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
                className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
              <input type="tel" placeholder="Phone" value={form.phone} onChange={e => setForm(p => ({ ...p, phone: e.target.value }))}
                className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
            </div>
          </div>
          <CTAButton className="w-full py-4 text-base">Get My AI Estimate</CTAButton>
        </form>
      )}

      {step === 'loading' && (
        <div className="text-center py-16">
          <div className="w-12 h-12 border-4 border-gold border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-white font-semibold">Analyzing your property...</p>
          <p className="text-gray-400 text-sm mt-1">Reviewing local market data</p>
        </div>
      )}

      {step === 'result' && result && (
        <div>
          <div className="text-center mb-6">
            <p className="text-gray-400 text-sm mb-1">{result.address_display}</p>
            <div className="text-4xl font-black text-gold mb-2">{fmt(result.range_low)} – {fmt(result.range_high)}</div>
            <span className={`text-xs font-semibold px-3 py-1 rounded-full ${result.confidence === 'High' ? 'bg-green-900/40 text-green-400' : result.confidence === 'Medium' ? 'bg-yellow-900/40 text-yellow-400' : 'bg-red-900/40 text-red-400'}`}>
              {result.confidence} Confidence
            </span>
          </div>
          <div className="bg-dark-surface rounded-lg p-4 mb-4">
            <p className="text-gray-300 text-sm leading-relaxed">{result.explanation}</p>
          </div>
          {result.key_factors.length > 0 && (
            <div className="mb-4">
              <p className="text-xs text-gray-400 uppercase tracking-wider mb-2">Key Factors</p>
              <ul className="flex flex-col gap-1">
                {result.key_factors.map(f => (
                  <li key={f} className="flex gap-2 text-sm text-gray-300"><span className="text-gold">→</span>{f}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-xs text-gray-500 italic mb-6">{result.disclaimer}</p>
          <CTAButton href="tel:9789872806" className="w-full py-4 text-base">Book Brandon for a Free Valuation</CTAButton>
          <button onClick={() => setStep('form')} className="w-full text-center text-gray-500 text-sm mt-3 hover:text-gold transition-colors">Run another estimate</button>
        </div>
      )}
    </div>
  );
}
```

- [ ] Create `frontend/src/components/seller/StagingChecklist.tsx`:
```tsx
'use client';
import { useState } from 'react';

const items = [
  "Remove personal photos and items",
  "Deep clean entire house (inside + out)",
  "Use neutral, warm colors",
  "Clear all countertops",
  "Declutter all rooms",
  "Manicure lawn and landscaping",
  "Style beds with fresh linens",
  "Organize closets (buyers will look)",
  "Hide cords and cables",
  "Fresh paint interior/exterior where needed",
  "Clean or replace light fixtures",
  "Add fresh flowers or plants",
];

export default function StagingChecklist() {
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const toggle = (i: number) => setChecked(p => { const n = new Set(p); n.has(i) ? n.delete(i) : n.add(i); return n; });
  return (
    <div className="bg-dark-card border border-dark-border rounded-xl p-6">
      <h3 className="text-white font-bold text-lg mb-4">Home Staging Checklist</h3>
      <p className="text-sm text-gray-400 mb-4">{checked.size}/{items.length} complete</p>
      <div className="w-full bg-dark-surface rounded-full h-2 mb-6">
        <div className="bg-gold h-2 rounded-full transition-all" style={{ width: `${(checked.size / items.length) * 100}%` }} />
      </div>
      <div className="flex flex-col gap-2">
        {items.map((item, i) => (
          <button key={i} onClick={() => toggle(i)} className="flex items-center gap-3 text-left group">
            <span className={`w-5 h-5 flex-shrink-0 rounded border flex items-center justify-center transition-colors ${checked.has(i) ? 'bg-gold border-gold' : 'border-dark-border group-hover:border-gold/50'}`}>
              {checked.has(i) && <svg className="w-3 h-3 text-black" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/></svg>}
            </span>
            <span className={`text-sm transition-colors ${checked.has(i) ? 'text-gray-500 line-through' : 'text-gray-300'}`}>{item}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] Create `frontend/src/app/sell/page.tsx`:
```tsx
import SellerSteps from '@/components/seller/SellerSteps';
import PropertyEvaluator from '@/components/seller/PropertyEvaluator';
import StagingChecklist from '@/components/seller/StagingChecklist';
import ReviewCard from '@/components/shared/ReviewCard';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';
import CTAButton from '@/components/shared/CTAButton';

const marketingChannels = ["MLS", "Zillow", "Realtor.com", "Trulia", "Facebook", "Instagram", "LinkedIn", "Local Groups & Forums", "Email Marketing", "Open Houses", "Video Marketing", "Adwerx Digital Ads", "Professional Flyers", "Signage", "Networking"];

const sellerReviews = [
  { quote: "Brandon's knowledge of the market and winning marketing strategies helped us sell our home in record time, well above what we had expected.", author: "Valerie W", location: "Nashua, NH" },
  { quote: "He is thorough, communicates very well, and is very responsive. He goes above and beyond to make sure everything is covered.", author: "Al & Elaine H", location: "Dracut, MA" },
  { quote: "Brandon was extremely supportive. He made this process so easy and I am extremely thankful.", author: "Michelle R", location: "Lowell, MA" },
  { quote: "Besides the outstanding assistance with valuing and marketing the property — the one that really stands out is patience.", author: "Jim R", location: "Dracut, MA" },
];

export default function SellPage() {
  return (
    <div className="bg-black">
      {/* Hero */}
      <section className="relative py-24 px-4 text-center bg-dark-surface overflow-hidden">
        <HalftoneOverlay opacity={0.04} />
        <div className="relative z-10 max-w-3xl mx-auto">
          <p className="text-gold text-xs uppercase tracking-widest mb-3 font-semibold">For Sellers</p>
          <h1 className="text-4xl sm:text-6xl font-black text-white mb-5">Sell With Peace of Mind</h1>
          <p className="text-gray-300 text-lg mb-8">Brandon's proven marketing strategy and hands-on approach ensures your home sells quickly, at the right price, with zero stress.</p>
          <CTAButton href="#evaluator" className="text-lg px-8 py-4">Get Your Free Home Estimate</CTAButton>
        </div>
      </section>

      {/* Evaluator */}
      <section className="py-20 px-4 max-w-4xl mx-auto">
        <PropertyEvaluator />
      </section>

      {/* Steps */}
      <div className="bg-dark-surface">
        <SellerSteps />
      </div>

      {/* Marketing */}
      <section className="py-16 px-4 max-w-5xl mx-auto">
        <div className="text-center mb-10">
          <p className="text-gold text-xs uppercase tracking-widest mb-2 font-semibold">Maximum Exposure</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white">Brandon's Marketing Strategy</h2>
          <p className="text-gray-400 mt-2 text-sm">Professional photography + full network exposure means more eyes, more offers, better price.</p>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          {marketingChannels.map(c => (
            <span key={c} className="bg-dark-card border border-gold/20 rounded-full px-4 py-2 text-sm text-gold">{c}</span>
          ))}
        </div>
      </section>

      {/* Staging checklist */}
      <section className="py-16 px-4 max-w-2xl mx-auto">
        <StagingChecklist />
      </section>

      {/* Reviews */}
      <section className="py-16 px-4 bg-dark-surface">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-10">
            <h2 className="text-2xl sm:text-3xl font-bold text-white">What Sellers Say</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {sellerReviews.map(r => <ReviewCard key={r.author} {...r} />)}
          </div>
        </div>
      </section>
    </div>
  );
}
```

- [ ] Commit:
```bash
git add frontend/src/app/sell/ frontend/src/components/seller/
git commit -m "feat: sellers page with property evaluator, steps, staging checklist, marketing channels"
```

---

### Task 16: Investor page + calculator

**Files:**
- Create: `frontend/src/app/invest/page.tsx`
- Create: `frontend/src/components/investor/InvestorCalculator.tsx`
- Create: `frontend/src/components/investor/AnalysisResults.tsx`
- Create: `frontend/src/components/investor/MeetingGate.tsx`
- Create: `frontend/src/components/investor/FlipCaseStudy.tsx`
- Create: `frontend/src/lib/investor-calc.ts`

- [ ] Create `frontend/src/lib/investor-calc.ts`:
```ts
export interface InvestorInputs {
  purchase_price: number;
  down_payment_pct: number;
  interest_rate: number;
  loan_term_years: number;
  monthly_rent_total: number;
  rehab_costs: number;
  annual_taxes: number;
  annual_insurance: number;
  monthly_maintenance: number;
  vacancy_rate_pct: number;
  mgmt_fee_pct: number;
}

export interface InvestorMetrics {
  monthly_gross_rent: number;
  monthly_mortgage: number;
  monthly_noi: number;
  monthly_cash_flow: number;
  cap_rate_pct: number;
  cash_on_cash_pct: number;
  total_cash_required: number;
  down_payment: number;
  loan_amount: number;
}

export function calculateMetrics(inp: InvestorInputs): InvestorMetrics {
  const loan_amount = inp.purchase_price * (1 - inp.down_payment_pct / 100);
  const down_payment = inp.purchase_price * (inp.down_payment_pct / 100);
  const monthly_rate = inp.interest_rate / 100 / 12;
  const n = inp.loan_term_years * 12;
  const mortgage = monthly_rate > 0
    ? loan_amount * (monthly_rate * Math.pow(1 + monthly_rate, n)) / (Math.pow(1 + monthly_rate, n) - 1)
    : loan_amount / n;

  const gross_rent = inp.monthly_rent_total;
  const vacancy_loss = gross_rent * (inp.vacancy_rate_pct / 100);
  const effective_rent = gross_rent - vacancy_loss;
  const mgmt_fee = effective_rent * (inp.mgmt_fee_pct / 100);
  const monthly_tax = inp.annual_taxes / 12;
  const monthly_insurance = inp.annual_insurance / 12;
  const total_expenses = mgmt_fee + monthly_tax + monthly_insurance + inp.monthly_maintenance;
  const noi = effective_rent - total_expenses;
  const cash_flow = noi - mortgage;
  const total_cash_required = down_payment + inp.rehab_costs + inp.purchase_price * 0.03;
  const cap_rate = inp.purchase_price > 0 ? (noi * 12) / inp.purchase_price * 100 : 0;
  const coc = total_cash_required > 0 ? (cash_flow * 12) / total_cash_required * 100 : 0;

  return {
    monthly_gross_rent: round2(gross_rent),
    monthly_mortgage: round2(mortgage),
    monthly_noi: round2(noi),
    monthly_cash_flow: round2(cash_flow),
    cap_rate_pct: round2(cap_rate),
    cash_on_cash_pct: round2(coc),
    total_cash_required: round2(total_cash_required),
    down_payment: round2(down_payment),
    loan_amount: round2(loan_amount),
  };
}

function round2(n: number) { return Math.round(n * 100) / 100; }
```

- [ ] Create `frontend/src/components/investor/FlipCaseStudy.tsx`:
```tsx
export default function FlipCaseStudy() {
  const items = [
    { label: "Purchase Price", value: "$415,000", color: "text-white" },
    { label: "Down Payment (15%)", value: "$62,250", color: "text-white" },
    { label: "Rehab Costs", value: "$48,769", color: "text-red-400" },
    { label: "Holding Costs", value: "$14,982", color: "text-red-400" },
    { label: "Closing Costs", value: "$13,372", color: "text-red-400" },
    { label: "Total All-In", value: "$492,124", color: "text-yellow-400" },
    { label: "ARV Sale Price", value: "$570,000", color: "text-green-400" },
    { label: "Total Profit", value: "$77,875", color: "text-gold" },
  ];
  return (
    <div className="bg-dark-card border border-gold/20 rounded-2xl p-8">
      <div className="text-center mb-6">
        <p className="text-gold text-xs uppercase tracking-widest mb-1 font-semibold">Real Numbers</p>
        <h3 className="text-xl font-bold text-white">50 Cheever Ave — Brandon's Fix & Flip</h3>
        <p className="text-gray-400 text-sm mt-1">Purchased Oct 31 → Sold Jan 21 — 3 months</p>
      </div>
      <div className="divide-y divide-dark-border">
        {items.map(item => (
          <div key={item.label} className="flex justify-between py-3">
            <span className="text-gray-400 text-sm">{item.label}</span>
            <span className={`font-semibold text-sm ${item.color}`}>{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] Create `frontend/src/components/investor/AnalysisResults.tsx`:
```tsx
import type { InvestorMetrics } from '@/lib/investor-calc';

const fmt = (n: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);

export default function AnalysisResults({ metrics }: { metrics: InvestorMetrics }) {
  const cashFlowColor = metrics.monthly_cash_flow >= 0 ? 'text-green-400' : 'text-red-400';
  const cards = [
    { label: "Monthly Gross Rent", value: fmt(metrics.monthly_gross_rent), color: "text-white" },
    { label: "Monthly Mortgage", value: fmt(metrics.monthly_mortgage), color: "text-red-400" },
    { label: "Monthly NOI", value: fmt(metrics.monthly_noi), color: "text-white" },
    { label: "Monthly Cash Flow", value: fmt(metrics.monthly_cash_flow), color: cashFlowColor },
    { label: "Cap Rate", value: `${metrics.cap_rate_pct.toFixed(2)}%`, color: "text-gold" },
    { label: "Cash-on-Cash", value: `${metrics.cash_on_cash_pct.toFixed(2)}%`, color: "text-gold" },
    { label: "Total Cash Required", value: fmt(metrics.total_cash_required), color: "text-yellow-400" },
    { label: "Loan Amount", value: fmt(metrics.loan_amount), color: "text-white" },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      {cards.map(c => (
        <div key={c.label} className="bg-dark-surface border border-dark-border rounded-xl p-4 text-center">
          <p className={`text-xl font-bold ${c.color} mb-1`}>{c.value}</p>
          <p className="text-gray-500 text-xs">{c.label}</p>
        </div>
      ))}
    </div>
  );
}
```

- [ ] Create `frontend/src/components/investor/MeetingGate.tsx`:
```tsx
'use client';
import { useState } from 'react';
import CTAButton from '@/components/shared/CTAButton';
import { apiPost } from '@/lib/api';
import type { InvestorInputs } from '@/lib/investor-calc';

interface Props { inputs: InvestorInputs; onUnlocked: (report: unknown) => void; }

export default function MeetingGate({ inputs, onUnlocked }: Props) {
  const [form, setForm] = useState({ name: '', email: '', phone: '' });
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await apiPost<{ metrics: unknown; report: unknown }>('/api/v1/investor/analyze', {
        ...inputs, ...form, property_type: 'single_family', units: 1, hold_years: 5, appreciation_rate_pct: 3,
      });
      onUnlocked(res.report);
    } catch { alert('Something went wrong.'); }
    setLoading(false);
  }

  return (
    <div className="border border-gold/30 rounded-2xl p-8 bg-dark-card text-center mt-6">
      <div className="text-3xl mb-3">🔒</div>
      <h3 className="text-xl font-bold text-white mb-2">Unlock Your Full Investor Report</h3>
      <p className="text-gray-400 text-sm mb-6 max-w-sm mx-auto">
        Book a 15-minute call with Brandon to review this deal together — and your full AI report unlocks instantly. Includes hold-period projections, exit scenarios, and sensitivity analysis.
      </p>
      <form onSubmit={submit} className="flex flex-col gap-3 max-w-sm mx-auto">
        <input required placeholder="Full Name" value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
          className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
        <input required type="email" placeholder="Email" value={form.email} onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
          className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
        <input type="tel" placeholder="Phone" value={form.phone} onChange={e => setForm(p => ({ ...p, phone: e.target.value }))}
          className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" />
        <CTAButton className="w-full py-4">{loading ? 'Generating Report...' : 'Book & Unlock Full Report'}</CTAButton>
      </form>
    </div>
  );
}
```

- [ ] Create `frontend/src/components/investor/InvestorCalculator.tsx`:
```tsx
'use client';
import { useState } from 'react';
import { calculateMetrics, type InvestorInputs } from '@/lib/investor-calc';
import AnalysisResults from './AnalysisResults';
import MeetingGate from './MeetingGate';
import CTAButton from '@/components/shared/CTAButton';

const defaultInputs: InvestorInputs = {
  purchase_price: 350000, down_payment_pct: 20, interest_rate: 7.25,
  loan_term_years: 30, monthly_rent_total: 2500, rehab_costs: 0,
  annual_taxes: 4000, annual_insurance: 1200, monthly_maintenance: 150,
  vacancy_rate_pct: 5, mgmt_fee_pct: 0,
};

type Step = 'form' | 'results' | 'unlocked';

export default function InvestorCalculator() {
  const [inputs, setInputs] = useState<InvestorInputs>(defaultInputs);
  const [step, setStep] = useState<Step>('form');
  const [report, setReport] = useState<unknown>(null);
  const metrics = calculateMetrics(inputs);

  function num(field: keyof InvestorInputs) {
    return (e: React.ChangeEvent<HTMLInputElement>) => setInputs(p => ({ ...p, [field]: parseFloat(e.target.value) || 0 }));
  }

  const fieldClass = "bg-dark-surface border border-dark-border rounded px-3 py-2.5 text-white text-sm focus:border-gold focus:outline-none w-full";
  const labelClass = "text-xs text-gray-400 mb-1 block";

  return (
    <div id="calculator" className="max-w-4xl mx-auto">
      {step === 'form' && (
        <div className="bg-dark-card border border-dark-border rounded-2xl p-8">
          <h2 className="text-2xl font-bold text-white mb-6">Investment Property Analyzer</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 mb-8">
            {[
              { label: "Purchase Price ($)", field: "purchase_price" as const },
              { label: "Down Payment (%)", field: "down_payment_pct" as const },
              { label: "Interest Rate (%)", field: "interest_rate" as const },
              { label: "Monthly Rent ($)", field: "monthly_rent_total" as const },
              { label: "Rehab Costs ($)", field: "rehab_costs" as const },
              { label: "Annual Taxes ($)", field: "annual_taxes" as const },
              { label: "Annual Insurance ($)", field: "annual_insurance" as const },
              { label: "Monthly Maintenance ($)", field: "monthly_maintenance" as const },
              { label: "Vacancy Rate (%)", field: "vacancy_rate_pct" as const },
            ].map(f => (
              <div key={f.field}>
                <label className={labelClass}>{f.label}</label>
                <input type="number" value={inputs[f.field]} onChange={num(f.field)} className={fieldClass} />
              </div>
            ))}
          </div>
          <CTAButton className="w-full py-4 text-base" onClick={() => setStep('results')}>Calculate Returns</CTAButton>
        </div>
      )}

      {(step === 'results' || step === 'unlocked') && (
        <div>
          <div className="bg-dark-card border border-dark-border rounded-2xl p-8 mb-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-white">Basic Analysis</h2>
              <button onClick={() => setStep('form')} className="text-gray-400 text-sm hover:text-gold transition-colors">Edit Inputs</button>
            </div>
            <AnalysisResults metrics={metrics} />
          </div>

          {step === 'results' && <MeetingGate inputs={inputs} onUnlocked={(r) => { setReport(r); setStep('unlocked'); }} />}

          {step === 'unlocked' && report && (
            <div className="bg-dark-card border border-gold/30 rounded-2xl p-8">
              <div className="flex items-center gap-2 mb-4">
                <span className="text-2xl">🔓</span>
                <h3 className="text-xl font-bold text-white">Full AI Analysis</h3>
              </div>
              <div className="bg-dark-surface rounded-lg p-4 mb-4">
                <p className="text-gray-300 text-sm leading-relaxed">{(report as any).ai_explanation}</p>
              </div>
              <div className="flex items-center gap-3">
                <span className={`px-4 py-2 rounded-full font-bold text-sm ${(report as any).verdict === 'STRONG' ? 'bg-green-900/40 text-green-400' : (report as any).verdict === 'MODERATE' ? 'bg-yellow-900/40 text-yellow-400' : 'bg-red-900/40 text-red-400'}`}>
                  {(report as any).verdict}
                </span>
                <p className="text-gray-400 text-sm">{(report as any).verdict_reason}</p>
              </div>
            </div>
          )}

          <p className="text-xs text-gray-600 text-center mt-4 italic">
            This tool provides estimates based on your inputs. Not intended to replace formal underwriting, appraisal, or financial advice.
          </p>
        </div>
      )}
    </div>
  );
}
```

- [ ] Create `frontend/src/app/invest/page.tsx`:
```tsx
import InvestorCalculator from '@/components/investor/InvestorCalculator';
import FlipCaseStudy from '@/components/investor/FlipCaseStudy';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';
import CTAButton from '@/components/shared/CTAButton';

const flippingSteps = [
  { n: 1, title: "Lead With Empathy", desc: "Every deal starts with understanding the seller's situation." },
  { n: 2, title: "Run the Numbers", desc: "Purchase, rehab, holding costs, ARV — no guessing." },
  { n: 3, title: "Find the Capital", desc: "Hard money lending, private lenders, or your own equity." },
  { n: 4, title: "Build Your Team", desc: "GC, electrician, plumber, landscaper — relationships matter." },
  { n: 5, title: "Execute & Exit", desc: "On-time, on-budget, profitable. That's the goal." },
];

export default function InvestPage() {
  return (
    <div className="bg-black">
      {/* Hero */}
      <section className="relative py-24 px-4 text-center overflow-hidden bg-dark-surface">
        <HalftoneOverlay opacity={0.04} />
        <div className="relative z-10 max-w-3xl mx-auto">
          <p className="text-gold text-xs uppercase tracking-widest mb-3 font-semibold">For Investors</p>
          <h1 className="text-4xl sm:text-6xl font-black text-white mb-5">Flipping 101 & Beyond</h1>
          <p className="text-gray-300 text-lg mb-8">Real numbers. Real strategy. Brandon has done it himself — from 1-2 family rentals to fix & flips. Now he helps other investors analyze and execute.</p>
          <CTAButton href="#calculator" className="text-lg px-8 py-4">Analyze a Deal</CTAButton>
        </div>
      </section>

      {/* Case study */}
      <section className="py-16 px-4 max-w-lg mx-auto">
        <div className="text-center mb-8">
          <p className="text-gold text-xs uppercase tracking-widest mb-2 font-semibold">Proof of Concept</p>
          <h2 className="text-2xl font-bold text-white">Brandon's Own Fix & Flip</h2>
        </div>
        <FlipCaseStudy />
      </section>

      {/* Strategy steps */}
      <section className="py-16 px-4 bg-dark-surface">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-10">
            <p className="text-gold text-xs uppercase tracking-widest mb-2 font-semibold">The Brandon Method</p>
            <h2 className="text-2xl font-bold text-white">How to Approach Every Deal</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-5 gap-4">
            {flippingSteps.map(s => (
              <div key={s.n} className="text-center">
                <div className="w-12 h-12 rounded-full bg-gold/10 border border-gold/30 flex items-center justify-center text-gold font-black text-lg mx-auto mb-3">{s.n}</div>
                <h3 className="text-white font-semibold text-sm mb-1">{s.title}</h3>
                <p className="text-gray-500 text-xs">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Calculator */}
      <section className="py-20 px-4">
        <InvestorCalculator />
      </section>

      {/* CTA */}
      <section className="py-16 px-4 text-center">
        <h2 className="text-2xl font-bold text-white mb-3">Ready to Talk Deals?</h2>
        <p className="text-gray-400 mb-6">Brandon brings real investor experience to every conversation.</p>
        <CTAButton href="tel:9789872806" className="px-8 py-4 text-base">Book an Investor Strategy Call</CTAButton>
      </section>
    </div>
  );
}
```

- [ ] Commit:
```bash
git add frontend/src/app/invest/ frontend/src/components/investor/ frontend/src/lib/investor-calc.ts
git commit -m "feat: investor page with calculator, freemium gate, flip case study"
```

---

### Task 17: About Brandon page

**Files:**
- Create: `frontend/src/app/about/page.tsx`

- [ ] Create `frontend/src/app/about/page.tsx`:
```tsx
import Image from 'next/image';
import CTAButton from '@/components/shared/CTAButton';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';

const awards = [
  "KW Heavy Hitter '22, '24",
  "KW Capper '19-'25",
  "Distinguished Young Professional (GLCC) '22",
  "NEAR Platinum '22, '24",
  "NEAR Gold '20-'21, '23",
  "MAR Good Neighbor '23",
  "NEAR Good Neighbor '20",
  "NEAR Silver '19",
  "NEAR Bronze '18",
];

const leadership = [
  "MAR BOD Member '26",
  "NEAR President & REALTOR® Of The Year '25",
  "President Elect '24",
  "1st Vice President '23",
  "DEI Member '23",
  "BOD Member '20-'22",
  "YPN Chair '20, Co-Chair '26",
  "YPN Member '18-'26",
];

export default function AboutPage() {
  return (
    <div className="bg-black">
      {/* Hero */}
      <section className="relative py-24 px-4 overflow-hidden bg-dark-surface">
        <HalftoneOverlay opacity={0.04} />
        <div className="relative z-10 max-w-5xl mx-auto flex flex-col md:flex-row gap-12 items-center">
          <div className="flex-shrink-0">
            <div className="relative w-64 h-80 rounded-2xl overflow-hidden border-2 border-gold/30 shadow-2xl shadow-gold/10">
              <Image src="/headshots/Brandon Sweeney Headshot.jpg" alt="Brandon Sweeney" fill className="object-cover object-top" />
            </div>
          </div>
          <div>
            <p className="text-gold text-xs uppercase tracking-widest mb-3 font-semibold">About</p>
            <h1 className="text-4xl sm:text-5xl font-black text-white mb-4">Brandon Sweeney, REALTOR®</h1>
            <p className="text-gray-300 text-lg mb-2">CEO, Sold With Sweeney & Co. | KW Realty Success</p>
            <p className="text-gray-400 mb-4">MA Associate Broker #9589032 | NH Salesperson #072734 | Licensed since April 17, 2017</p>
            <div className="flex flex-wrap gap-2">
              {["NEAR President 2025", "REALTOR® Of The Year '25", "GREEN", "C2EX"].map(b => (
                <span key={b} className="border border-gold/30 text-gold text-xs px-3 py-1 rounded-full">{b}</span>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Bio */}
      <section className="py-16 px-4 max-w-3xl mx-auto">
        <p className="text-gold text-xs uppercase tracking-widest mb-4 font-semibold">My Story</p>
        <div className="prose prose-invert max-w-none text-gray-300 text-base leading-relaxed space-y-4">
          <p>Born and raised in Dracut, MA — a townie and proud of it. I attended Plymouth State University where I graduated Magna Cum Laude with a Bachelor's in Business Management and minors in Sales & Marketing.</p>
          <p>My interest in real estate started with a childhood fascination with C.A.D. software. That detail-oriented, structural mindset carried into everything I do — from analyzing a property's bones during an inspection to crafting an offer strategy that wins.</p>
          <p>"Real estate is not only my profession, it's also my passion." Every client gets my full attention, my full expertise, and the kind of hand-holding approach that makes a stressful process feel manageable.</p>
          <p>My leadership journey at NEAR (Northeast Association of REALTORS®) took me from Director to VP to President Elect to President — and in 2025, I was named REALTOR® Of The Year. That recognition is a reflection of how I approach every transaction: with professionalism, market knowledge, and genuine care.</p>
          <p className="text-gold font-semibold italic">"NOT your AVERAGE, award winning, philanthropic REALTOR® OF THE YEAR '25 at KW Realty Success!"</p>
        </div>
      </section>

      {/* Achievements */}
      <section className="py-16 px-4 bg-dark-surface">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <p className="text-gold text-xs uppercase tracking-widest mb-2 font-semibold">Track Record</p>
            <h2 className="text-2xl sm:text-3xl font-bold text-white">Career Achievements</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div>
              <h3 className="text-gold font-semibold text-sm uppercase tracking-wider mb-4">Awards</h3>
              <ul className="flex flex-col gap-2">
                {awards.map(a => <li key={a} className="flex gap-2 text-sm text-gray-300"><span className="text-gold">★</span>{a}</li>)}
              </ul>
            </div>
            <div>
              <h3 className="text-gold font-semibold text-sm uppercase tracking-wider mb-4">Leadership</h3>
              <ul className="flex flex-col gap-2">
                {leadership.map(l => <li key={l} className="flex gap-2 text-sm text-gray-300"><span className="text-gold">→</span>{l}</li>)}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* MS is BS */}
      <section className="py-16 px-4">
        <div className="max-w-3xl mx-auto text-center">
          <p className="text-gold text-xs uppercase tracking-widest mb-3 font-semibold">Giving Back</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4">MS is BS New England Inc.</h2>
          <p className="text-gray-300 mb-4">Founded in 2015 as a college assignment — it became a movement. Brandon's father John, uncle Gary, and late grandmother Rose all have or had Multiple Sclerosis. That personal connection fuels everything.</p>
          <p className="text-4xl font-black text-gold mb-4">$300,000+</p>
          <p className="text-gray-400 mb-2">in grants to local MS warriors through an annual 5K, Gala, and Golf Tournament.</p>
          <p className="text-gray-300 italic mb-8">"When you close with Brandon, $100 goes to your chosen charity or $200 to MS is BS New England."</p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <CTAButton href="https://www.MSisBSNewEngland.com" variant="gold">Visit MS is BS</CTAButton>
            <CTAButton href="tel:9789872806" variant="outline">Book Time With Brandon</CTAButton>
          </div>
        </div>
      </section>

      {/* Why referral */}
      <section className="py-16 px-4 bg-dark-surface">
        <div className="max-w-3xl mx-auto text-center">
          <p className="text-gold text-xs uppercase tracking-widest mb-3 font-semibold">Philosophy</p>
          <h2 className="text-2xl font-bold text-white mb-8">Why I Work By Referral</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
            {[
              { q: "Relationships are more important than transactions.", e: "Every client is a long-term relationship, not a closing." },
              { q: "You control my business!", e: "Referrals from happy clients are the only marketing that truly matters." },
              { q: "Service that continues after the sale!", e: "Got a question 3 years later? Brandon still picks up the phone." },
            ].map(item => (
              <div key={item.q} className="bg-dark-card border border-dark-border rounded-xl p-5">
                <p className="text-gold font-semibold text-sm italic mb-2">"{item.q}"</p>
                <p className="text-gray-400 text-xs">{item.e}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
```

- [ ] Commit:
```bash
git add frontend/src/app/about/
git commit -m "feat: About Brandon page with bio, achievements, MS is BS, referral philosophy"
```

---

## Phase 7: Chatbot Widget

### Task 18: Floating chatbot with Gemini

**Files:**
- Create: `frontend/src/components/chat/ChatWidget.tsx`
- Create: `frontend/src/components/chat/ChatPanel.tsx`
- Update: `frontend/src/app/layout.tsx`
- Create: `frontend/src/hooks/useChat.ts`

- [ ] Create `frontend/src/hooks/useChat.ts`:
```ts
import { useState, useCallback } from 'react';
import { apiPost } from '@/lib/api';

export interface Message { role: 'user' | 'model'; content: string; }

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'model', content: "Hi! I'm Brandon's AI assistant. Are you looking to buy, sell, or invest in real estate? I'm here to help — and get you connected with Brandon." }
  ]);
  const [loading, setLoading] = useState(false);

  const send = useCallback(async (text: string) => {
    const updated = [...messages, { role: 'user' as const, content: text }];
    setMessages(updated);
    setLoading(true);
    try {
      const res = await apiPost<{ reply: string }>('/api/v1/chat/', { messages: updated });
      setMessages(p => [...p, { role: 'model', content: res.reply }]);
    } catch {
      setMessages(p => [...p, { role: 'model', content: "I'm having trouble connecting right now. Please call Brandon directly at (978) 987-2806." }]);
    }
    setLoading(false);
  }, [messages]);

  return { messages, loading, send };
}
```

- [ ] Create `frontend/src/components/chat/ChatPanel.tsx`:
```tsx
'use client';
import { useRef, useEffect, useState } from 'react';
import { useChat } from '@/hooks/useChat';

const quickReplies = ["I want to buy", "I want to sell", "I'm an investor", "Book a call"];

export default function ChatPanel({ onClose }: { onClose: () => void }) {
  const { messages, loading, send } = useChat();
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  async function handleSend(text?: string) {
    const msg = text || input.trim();
    if (!msg) return;
    setInput('');
    await send(msg);
  }

  return (
    <div className="fixed bottom-20 right-4 sm:right-6 z-50 w-[calc(100vw-2rem)] sm:w-96 bg-dark-card border border-dark-border rounded-2xl shadow-2xl flex flex-col" style={{ maxHeight: '75vh' }}>
      {/* Header */}
      <div className="flex items-center gap-3 p-4 border-b border-dark-border flex-shrink-0">
        <div className="w-8 h-8 rounded-full bg-gold flex items-center justify-center text-black font-bold text-sm">B</div>
        <div>
          <p className="text-white text-sm font-semibold">Brandon's AI Assistant</p>
          <p className="text-green-400 text-xs">● Online</p>
        </div>
        <button onClick={onClose} className="ml-auto text-gray-400 hover:text-white">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] rounded-xl px-4 py-3 text-sm leading-relaxed ${m.role === 'user' ? 'bg-gold text-black font-medium' : 'bg-dark-surface border border-dark-border text-gray-200'}`}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-dark-surface border border-dark-border rounded-xl px-4 py-3">
              <div className="flex gap-1">
                {[0, 1, 2].map(i => <span key={i} className="w-2 h-2 bg-gold rounded-full animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />)}
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Quick replies */}
      {messages.length <= 2 && (
        <div className="px-4 flex gap-2 flex-wrap flex-shrink-0">
          {quickReplies.map(q => (
            <button key={q} onClick={() => handleSend(q)}
              className="text-xs border border-gold/30 text-gold px-3 py-1.5 rounded-full hover:bg-gold/10 transition-colors">
              {q}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="p-4 border-t border-dark-border flex gap-2 flex-shrink-0">
        <input
          value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
          placeholder="Type a message..."
          className="flex-1 bg-dark-surface border border-dark-border rounded-lg px-3 py-2 text-white text-sm focus:border-gold focus:outline-none"
        />
        <button onClick={() => handleSend()}
          disabled={!input.trim() || loading}
          className="w-10 h-10 rounded-lg bg-gold text-black flex items-center justify-center disabled:opacity-40 hover:bg-gold-hover transition-colors">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" /></svg>
        </button>
      </div>
    </div>
  );
}
```

- [ ] Create `frontend/src/components/chat/ChatWidget.tsx`:
```tsx
'use client';
import { useState } from 'react';
import dynamic from 'next/dynamic';

const ChatPanel = dynamic(() => import('./ChatPanel'), { ssr: false });

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  return (
    <>
      {open && <ChatPanel onClose={() => setOpen(false)} />}
      <button
        onClick={() => setOpen(p => !p)}
        className="fixed bottom-4 right-4 sm:right-6 z-50 w-14 h-14 rounded-full bg-gold text-black flex items-center justify-center shadow-xl animate-pulse-gold hover:bg-gold-hover transition-all"
        aria-label="Chat with Brandon's assistant"
      >
        {open
          ? <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
          : <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 12H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z"/></svg>
        }
      </button>
    </>
  );
}
```

- [ ] Update `frontend/src/app/layout.tsx` to include ChatWidget:
```tsx
import type { Metadata } from 'next';
import '../styles/globals.css';
import '../styles/animations.css';
import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';
import ChatWidget from '@/components/chat/ChatWidget';

export const metadata: Metadata = {
  title: 'Sold With Sweeney & Co. | Brandon Sweeney, REALTOR®',
  description: "NOT your AVERAGE, award winning, philanthropic REALTOR® OF THE YEAR '25. Serving MA & NH buyers, sellers, and investors.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-black text-white font-sans">
        <Navbar />
        <main className="pt-16">{children}</main>
        <Footer />
        <ChatWidget />
      </body>
    </html>
  );
}
```

- [ ] Commit:
```bash
git add frontend/src/components/chat/ frontend/src/hooks/useChat.ts frontend/src/app/layout.tsx
git commit -m "feat: floating Gemini-powered chatbot with quick replies"
```

---

## Phase 8: Admin Dashboard

### Task 19: Admin layout + auth page

**Files:**
- Create: `frontend/src/app/admin/layout.tsx`
- Create: `frontend/src/app/admin/page.tsx`
- Create: `frontend/src/components/layout/AdminSidebar.tsx`
- Create: `frontend/src/app/admin/login/page.tsx`

- [ ] Create `frontend/src/components/layout/AdminSidebar.tsx`:
```tsx
'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

const navItems = [
  { href: '/admin', label: 'Dashboard', icon: '📊' },
  { href: '/admin/leads', label: 'Leads', icon: '👥' },
  { href: '/admin/content', label: 'Content', icon: '✏️' },
  { href: '/admin/funnels', label: 'Funnels', icon: '🎯' },
  { href: '/admin/analytics', label: 'Analytics', icon: '📈' },
  { href: '/admin/settings', label: 'Settings', icon: '⚙️' },
];

export default function AdminSidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-56 bg-dark-surface border-r border-dark-border min-h-screen flex flex-col">
      <div className="p-6 border-b border-dark-border">
        <p className="text-gold font-bold text-sm">SWS Admin</p>
        <p className="text-gray-500 text-xs">Sold With Sweeney & Co.</p>
      </div>
      <nav className="p-4 flex flex-col gap-1 flex-1">
        {navItems.map(item => (
          <Link key={item.href} href={item.href}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${pathname === item.href ? 'bg-gold/10 text-gold border border-gold/20' : 'text-gray-400 hover:text-white hover:bg-dark-card'}`}>
            <span>{item.icon}</span>{item.label}
          </Link>
        ))}
      </nav>
      <div className="p-4 border-t border-dark-border">
        <button onClick={() => { localStorage.removeItem('admin_token'); window.location.href = '/admin/login'; }}
          className="text-xs text-gray-500 hover:text-red-400 transition-colors w-full text-left">Sign Out</button>
      </div>
    </aside>
  );
}
```

- [ ] Create `frontend/src/app/admin/login/page.tsx`:
```tsx
'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiPost } from '@/lib/api';

export default function AdminLogin() {
  const [form, setForm] = useState({ email: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const res = await apiPost<{ access_token: string }>('/api/v1/auth/login', form);
      localStorage.setItem('admin_token', res.access_token);
      router.push('/admin');
    } catch { setError('Invalid credentials'); }
    setLoading(false);
  }

  return (
    <div className="min-h-screen bg-black flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-white mb-1">Admin Login</h1>
          <p className="text-gray-400 text-sm">Sold With Sweeney & Co.</p>
        </div>
        <form onSubmit={submit} className="bg-dark-card border border-dark-border rounded-2xl p-8 flex flex-col gap-4">
          {error && <p className="text-red-400 text-sm text-center">{error}</p>}
          <input type="email" placeholder="Email" value={form.email} onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
            className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" required />
          <input type="password" placeholder="Password" value={form.password} onChange={e => setForm(p => ({ ...p, password: e.target.value }))}
            className="bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none" required />
          <button type="submit" disabled={loading}
            className="bg-gold text-black rounded px-4 py-3 font-semibold text-sm hover:bg-gold-hover disabled:opacity-50 transition-colors">
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}
```

- [ ] Create `frontend/src/app/admin/layout.tsx`:
```tsx
'use client';
import { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import AdminSidebar from '@/components/layout/AdminSidebar';

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (pathname !== '/admin/login') {
      const token = localStorage.getItem('admin_token');
      if (!token) router.push('/admin/login');
    }
  }, [pathname, router]);

  if (pathname === '/admin/login') return <>{children}</>;

  return (
    <div className="flex min-h-screen bg-black">
      <AdminSidebar />
      <main className="flex-1 p-8 overflow-y-auto">{children}</main>
    </div>
  );
}
```

- [ ] Create `frontend/src/app/admin/page.tsx`:
```tsx
'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { apiGet } from '@/lib/api';

export default function AdminDashboard() {
  const [stats, setStats] = useState<{ page_views: number; top_pages: { page: string; count: number }[] } | null>(null);

  useEffect(() => {
    const token = localStorage.getItem('admin_token');
    if (!token) return;
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/analytics/dashboard?days=7`, {
      headers: { Authorization: `Bearer ${token}` }
    }).then(r => r.json()).then(setStats).catch(() => {});
  }, []);

  const quickActions = [
    { label: 'View All Leads', href: '/admin/leads', icon: '👥' },
    { label: 'Create Funnel', href: '/admin/funnels/new', icon: '🎯' },
    { label: 'Edit Content', href: '/admin/content', icon: '✏️' },
    { label: 'View Analytics', href: '/admin/analytics', icon: '📈' },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-2">Dashboard</h1>
      <p className="text-gray-400 text-sm mb-8">Welcome back, Brandon.</p>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        {quickActions.map(a => (
          <Link key={a.href} href={a.href}
            className="bg-dark-card border border-dark-border rounded-xl p-5 hover:border-gold/40 transition-colors text-center">
            <div className="text-2xl mb-2">{a.icon}</div>
            <p className="text-sm font-medium text-white">{a.label}</p>
          </Link>
        ))}
      </div>

      {stats && (
        <div className="bg-dark-card border border-dark-border rounded-xl p-6">
          <h2 className="text-white font-semibold mb-4">Last 7 Days</h2>
          <p className="text-3xl font-black text-gold mb-4">{stats.page_views} page views</p>
          <div>
            <p className="text-xs text-gray-400 uppercase tracking-wider mb-2">Top Pages</p>
            {stats.top_pages.slice(0, 5).map(p => (
              <div key={p.page} className="flex justify-between py-2 border-b border-dark-border">
                <span className="text-gray-300 text-sm">{p.page || '/'}</span>
                <span className="text-gold text-sm font-semibold">{p.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] Commit:
```bash
git add frontend/src/app/admin/
git commit -m "feat: admin layout, login page, dashboard home"
```

---

### Task 20: Admin leads, content, funnels pages

**Files:**
- Create: `frontend/src/app/admin/leads/page.tsx`
- Create: `frontend/src/app/admin/content/page.tsx`
- Create: `frontend/src/app/admin/funnels/page.tsx`
- Create: `frontend/src/app/admin/funnels/new/page.tsx`
- Create: `frontend/src/app/admin/analytics/page.tsx`

- [ ] Create `frontend/src/app/admin/leads/page.tsx`:
```tsx
'use client';
import { useEffect, useState } from 'react';

interface Lead { id: number; name: string; email: string; phone?: string; source?: string; lead_type?: string; routing_status: string; created_at: string; }

const statusColors: Record<string, string> = {
  new: 'bg-blue-900/40 text-blue-400',
  in_review: 'bg-yellow-900/40 text-yellow-400',
  sent_to_crm: 'bg-purple-900/40 text-purple-400',
  booked: 'bg-green-900/40 text-green-400',
  converted: 'bg-gold/20 text-gold',
  archived: 'bg-gray-900/40 text-gray-500',
};

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [filter, setFilter] = useState('');
  const token = typeof window !== 'undefined' ? localStorage.getItem('admin_token') : '';

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/leads/`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json()).then(setLeads).catch(() => {});
  }, [token]);

  async function updateStatus(id: number, status: string) {
    await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/leads/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ routing_status: status }),
    });
    setLeads(p => p.map(l => l.id === id ? { ...l, routing_status: status } : l));
  }

  const filtered = leads.filter(l => !filter || l.lead_type === filter || l.routing_status === filter);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Leads</h1>
        <select value={filter} onChange={e => setFilter(e.target.value)}
          className="bg-dark-card border border-dark-border rounded px-3 py-2 text-white text-sm focus:border-gold focus:outline-none">
          <option value="">All Leads</option>
          <option value="buyer">Buyers</option>
          <option value="seller">Sellers</option>
          <option value="investor">Investors</option>
          <option value="new">New</option>
          <option value="booked">Booked</option>
        </select>
      </div>
      <div className="bg-dark-card border border-dark-border rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-dark-border">
              {['Name', 'Contact', 'Type', 'Source', 'Status', 'Date', 'Actions'].map(h => (
                <th key={h} className="text-left text-xs text-gray-400 uppercase tracking-wider px-4 py-3">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(lead => (
              <tr key={lead.id} className="border-b border-dark-border hover:bg-dark-surface/50 transition-colors">
                <td className="px-4 py-3 text-white text-sm font-medium">{lead.name || '—'}</td>
                <td className="px-4 py-3">
                  <p className="text-sm text-gray-300">{lead.email}</p>
                  <p className="text-xs text-gray-500">{lead.phone || '—'}</p>
                </td>
                <td className="px-4 py-3"><span className="text-xs capitalize text-gray-400">{lead.lead_type || '—'}</span></td>
                <td className="px-4 py-3"><span className="text-xs text-gray-500">{lead.source || '—'}</span></td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-1 rounded-full font-medium ${statusColors[lead.routing_status] || 'text-gray-400'}`}>
                    {lead.routing_status.replace('_', ' ')}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-gray-500">{new Date(lead.created_at).toLocaleDateString()}</td>
                <td className="px-4 py-3">
                  <select onChange={e => updateStatus(lead.id, e.target.value)} defaultValue={lead.routing_status}
                    className="bg-dark-surface border border-dark-border rounded px-2 py-1 text-white text-xs focus:border-gold focus:outline-none">
                    <option value="new">New</option>
                    <option value="in_review">In Review</option>
                    <option value="sent_to_crm">Sent to CRM</option>
                    <option value="booked">Booked</option>
                    <option value="converted">Converted</option>
                    <option value="archived">Archive</option>
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && <p className="text-center text-gray-500 py-12">No leads yet.</p>}
      </div>
    </div>
  );
}
```

- [ ] Create `frontend/src/app/admin/content/page.tsx`:
```tsx
'use client';
import { useEffect, useState } from 'react';

interface Block { id: number; block_id: string; content: string; page?: string; }

export default function ContentPage() {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const token = typeof window !== 'undefined' ? localStorage.getItem('admin_token') : '';

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/content/`).then(r => r.json()).then(setBlocks);
  }, []);

  async function save(block_id: string, content: string) {
    await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/content/${block_id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ content }),
    });
    setSaved(p => new Set([...p, block_id]));
    setTimeout(() => setSaved(p => { const n = new Set(p); n.delete(block_id); return n; }), 2000);
  }

  const byPage = blocks.reduce((acc, b) => { const p = b.page || 'other'; acc[p] = [...(acc[p] || []), b]; return acc; }, {} as Record<string, Block[]>);

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Content Editor</h1>
      {Object.entries(byPage).map(([page, pageBlocks]) => (
        <div key={page} className="mb-8">
          <h2 className="text-gold font-semibold text-sm uppercase tracking-wider mb-4 capitalize">{page} page</h2>
          <div className="flex flex-col gap-4">
            {pageBlocks.map(block => (
              <div key={block.block_id} className="bg-dark-card border border-dark-border rounded-xl p-5">
                <div className="flex items-center justify-between mb-3">
                  <p className="text-xs text-gray-400 font-mono">{block.block_id}</p>
                  {saved.has(block.block_id) && <span className="text-xs text-green-400">✓ Saved</span>}
                </div>
                <textarea
                  defaultValue={block.content}
                  onChange={e => setEditing(p => ({ ...p, [block.block_id]: e.target.value }))}
                  rows={3}
                  className="w-full bg-dark-surface border border-dark-border rounded px-3 py-2 text-white text-sm focus:border-gold focus:outline-none resize-y"
                />
                <button onClick={() => save(block.block_id, editing[block.block_id] ?? block.content)}
                  className="mt-2 bg-gold text-black px-4 py-1.5 rounded text-sm font-semibold hover:bg-gold-hover transition-colors">
                  Save
                </button>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] Create `frontend/src/app/admin/funnels/new/page.tsx`:
```tsx
'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function NewFunnel() {
  const router = useRouter();
  const [form, setForm] = useState({ title: '', audience: 'general', description: '', cta_text: 'Register Now', lead_routing: 'dashboard' });
  const [loading, setLoading] = useState(false);
  const token = typeof window !== 'undefined' ? localStorage.getItem('admin_token') : '';

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/funnels/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(form),
    });
    if (res.ok) { const data = await res.json(); router.push(`/admin/funnels`); }
    setLoading(false);
  }

  const fieldClass = "bg-dark-surface border border-dark-border rounded px-4 py-3 text-white text-sm focus:border-gold focus:outline-none w-full";

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-white mb-6">Create New Funnel</h1>
      <form onSubmit={create} className="bg-dark-card border border-dark-border rounded-xl p-8 flex flex-col gap-5">
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Title</label>
          <input required value={form.title} onChange={e => setForm(p => ({ ...p, title: e.target.value }))} placeholder="e.g. First-Time Buyer Workshop" className={fieldClass} />
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Audience</label>
          <select value={form.audience} onChange={e => setForm(p => ({ ...p, audience: e.target.value }))} className={fieldClass}>
            <option value="general">General</option>
            <option value="buyer">Buyers</option>
            <option value="seller">Sellers</option>
            <option value="investor">Investors</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Description / Context for AI</label>
          <textarea required rows={4} value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))} placeholder="Describe what this event/funnel is about..." className={fieldClass} />
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1 block">CTA Button Text</label>
          <input value={form.cta_text} onChange={e => setForm(p => ({ ...p, cta_text: e.target.value }))} className={fieldClass} />
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Lead Routing</label>
          <select value={form.lead_routing} onChange={e => setForm(p => ({ ...p, lead_routing: e.target.value }))} className={fieldClass}>
            <option value="dashboard">Dashboard First</option>
            <option value="crm">Direct to KW CRM</option>
          </select>
        </div>
        <button type="submit" disabled={loading} className="bg-gold text-black px-6 py-3 rounded font-semibold hover:bg-gold-hover disabled:opacity-50 transition-colors">
          {loading ? 'Generating with AI...' : 'Create Funnel'}
        </button>
      </form>
    </div>
  );
}
```

- [ ] Create `frontend/src/app/admin/funnels/page.tsx`:
```tsx
'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';

interface Funnel { id: number; title: string; slug: string; audience: string; status: string; registrations: number; created_at: string; }

export default function FunnelsPage() {
  const [funnels, setFunnels] = useState<Funnel[]>([]);
  const token = typeof window !== 'undefined' ? localStorage.getItem('admin_token') : '';

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/funnels/`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json()).then(setFunnels).catch(() => {});
  }, [token]);

  async function togglePublish(id: number) {
    await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/funnels/${id}/publish`, { method: 'PATCH', headers: { Authorization: `Bearer ${token}` } });
    setFunnels(p => p.map(f => f.id === id ? { ...f, status: f.status === 'published' ? 'unpublished' : 'published' } : f));
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Funnels</h1>
        <Link href="/admin/funnels/new" className="bg-gold text-black px-4 py-2 rounded text-sm font-semibold hover:bg-gold-hover transition-colors">+ New Funnel</Link>
      </div>
      <div className="bg-dark-card border border-dark-border rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-dark-border">
              {['Title', 'Audience', 'Status', 'Registrations', 'Actions'].map(h => (
                <th key={h} className="text-left text-xs text-gray-400 uppercase tracking-wider px-4 py-3">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {funnels.map(f => (
              <tr key={f.id} className="border-b border-dark-border hover:bg-dark-surface/50">
                <td className="px-4 py-3">
                  <p className="text-white text-sm font-medium">{f.title}</p>
                  <p className="text-xs text-gray-500">/f/{f.slug}</p>
                </td>
                <td className="px-4 py-3 text-sm text-gray-400 capitalize">{f.audience}</td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-1 rounded-full ${f.status === 'published' ? 'bg-green-900/40 text-green-400' : 'bg-gray-900/40 text-gray-400'}`}>{f.status}</span>
                </td>
                <td className="px-4 py-3 text-gold font-semibold text-sm">{f.registrations}</td>
                <td className="px-4 py-3 flex gap-2">
                  <button onClick={() => togglePublish(f.id)} className="text-xs text-gray-400 hover:text-gold border border-dark-border px-3 py-1 rounded hover:border-gold/40 transition-colors">
                    {f.status === 'published' ? 'Unpublish' : 'Publish'}
                  </button>
                  <a href={`/f/${f.slug}`} target="_blank" className="text-xs text-gold hover:underline px-3 py-1">Preview</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {funnels.length === 0 && <p className="text-center text-gray-500 py-12">No funnels yet. Create your first one.</p>}
      </div>
    </div>
  );
}
```

- [ ] Create `frontend/src/app/admin/analytics/page.tsx`:
```tsx
'use client';
import { useEffect, useState } from 'react';

export default function AnalyticsPage() {
  const [stats, setStats] = useState<any>(null);
  const [days, setDays] = useState(30);
  const token = typeof window !== 'undefined' ? localStorage.getItem('admin_token') : '';

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/analytics/dashboard?days=${days}`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json()).then(setStats).catch(() => {});
  }, [days, token]);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Analytics</h1>
        <select value={days} onChange={e => setDays(Number(e.target.value))}
          className="bg-dark-card border border-dark-border rounded px-3 py-2 text-white text-sm focus:border-gold focus:outline-none">
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>
      {stats && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <div className="bg-dark-card border border-dark-border rounded-xl p-6">
            <p className="text-xs text-gray-400 uppercase tracking-wider mb-2">Page Views</p>
            <p className="text-4xl font-black text-gold">{stats.page_views}</p>
          </div>
          <div className="bg-dark-card border border-dark-border rounded-xl p-6">
            <p className="text-xs text-gray-400 uppercase tracking-wider mb-3">Top Pages</p>
            {stats.top_pages?.map((p: any) => (
              <div key={p.page} className="flex justify-between py-2 border-b border-dark-border">
                <span className="text-gray-300 text-sm">{p.page || '/'}</span>
                <span className="text-gold text-sm font-semibold">{p.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] Create `frontend/src/app/admin/settings/page.tsx`:
```tsx
export default function SettingsPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Settings</h1>
      <div className="bg-dark-card border border-dark-border rounded-xl p-8 max-w-2xl">
        <div className="flex flex-col gap-4">
          <div>
            <p className="text-xs text-gray-400 mb-1">Admin Email</p>
            <p className="text-white text-sm">brandon@soldwithsweeney.com</p>
          </div>
          <div className="border-t border-dark-border pt-4">
            <p className="text-xs text-gray-400 mb-1">Google Calendar</p>
            <p className="text-yellow-400 text-sm">⚠ Not connected — configure OAuth credentials</p>
          </div>
          <div className="border-t border-dark-border pt-4">
            <p className="text-xs text-gray-400 mb-1">KW CRM</p>
            <p className="text-yellow-400 text-sm">⚠ Not connected — API key pending</p>
          </div>
          <div className="border-t border-dark-border pt-4">
            <p className="text-xs text-gray-400 mb-1">Gemini AI</p>
            <p className="text-green-400 text-sm">✓ Connected</p>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] Commit:
```bash
git add frontend/src/app/admin/
git commit -m "feat: admin leads, content editor, funnels, analytics, settings pages"
```

---

## Phase 9: Dynamic Funnel Pages

### Task 21: Public funnel pages

**Files:**
- Create: `frontend/src/app/f/[slug]/page.tsx`

- [ ] Create `frontend/src/app/f/[slug]/page.tsx`:
```tsx
import { apiGet } from '@/lib/api';
import LeadCaptureForm from '@/components/shared/LeadCaptureForm';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';
import { notFound } from 'next/navigation';

interface FunnelData {
  funnel: { id: number; title: string; audience: string; cta_text: string; };
  content: { hero_headline: string; hero_subtext: string; details_heading?: string; details_body?: string; value_props?: string[]; testimonial?: string; cta_headline: string; cta_subtext: string; };
}

export default async function FunnelPage({ params }: { params: { slug: string } }) {
  let data: FunnelData;
  try {
    data = await apiGet<FunnelData>(`/api/v1/funnels/public/${params.slug}`);
  } catch {
    notFound();
  }
  const { funnel, content } = data;

  return (
    <div className="bg-black min-h-screen">
      {/* Hero */}
      <section className="relative py-24 px-4 text-center bg-dark-surface overflow-hidden">
        <HalftoneOverlay opacity={0.05} />
        <div className="relative z-10 max-w-3xl mx-auto">
          <p className="text-gold text-xs uppercase tracking-widest mb-3 font-semibold capitalize">{funnel.audience}</p>
          <h1 className="text-4xl sm:text-6xl font-black text-white mb-5">{content.hero_headline}</h1>
          <p className="text-gray-300 text-lg">{content.hero_subtext}</p>
        </div>
      </section>

      {/* Details */}
      {content.details_heading && (
        <section className="py-16 px-4 max-w-3xl mx-auto">
          <h2 className="text-2xl font-bold text-white mb-4">{content.details_heading}</h2>
          <p className="text-gray-300 leading-relaxed">{content.details_body}</p>
        </section>
      )}

      {/* Value props */}
      {content.value_props && content.value_props.length > 0 && (
        <section className="py-12 px-4 bg-dark-surface">
          <div className="max-w-3xl mx-auto">
            <div className="flex flex-col gap-4">
              {content.value_props.map((prop, i) => (
                <div key={i} className="flex gap-3">
                  <span className="text-gold font-bold flex-shrink-0">✓</span>
                  <p className="text-gray-300 text-sm">{prop}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* CTA + form */}
      <section className="py-20 px-4">
        <div className="max-w-lg mx-auto">
          <div className="text-center mb-8">
            <h2 className="text-2xl font-bold text-white mb-2">{content.cta_headline}</h2>
            <p className="text-gray-400 text-sm">{content.cta_subtext}</p>
          </div>
          <div className="bg-dark-card border border-dark-border rounded-2xl p-8">
            <LeadCaptureForm source={`funnel:${params.slug}`} leadType={funnel.audience} ctaText={funnel.cta_text} />
          </div>
        </div>
      </section>

      {/* Footer */}
      <div className="border-t border-dark-border py-8 px-4 text-center">
        <p className="text-xs text-gray-600">Sold With Sweeney & Co. | Brandon Sweeney, REALTOR® | (978) 987-2806 | info@SoldWithSweeney.com</p>
        <p className="text-xs text-gray-700 mt-1">MA #9589032 | NH #072734 | Powered by Keller Williams Realty Success</p>
      </div>
    </div>
  );
}
```

- [ ] Commit:
```bash
git add frontend/src/app/f/
git commit -m "feat: dynamic public funnel pages"
```

---

## Phase 10: Frame Extraction & Performance

### Task 22: Extract house blast frames via ffmpeg

**Files:**
- Create: `scripts/extract-frames.sh`

- [ ] Create `scripts/extract-frames.sh`:
```bash
#!/bin/bash
set -e

INPUT="frontend/public/assets/house_blast.mp4"
OUTPUT="frontend/public/frames/house-blast"

mkdir -p "$OUTPUT"

echo "Extracting frames from $INPUT..."
ffmpeg -i "$INPUT" \
  -vf "fps=24,scale=960:-2" \
  -q:v 5 \
  "$OUTPUT/frame_%04d.jpg"

FRAME_COUNT=$(ls "$OUTPUT"/*.jpg | wc -l)
echo "Extracted $FRAME_COUNT frames to $OUTPUT"
echo "Update TOTAL_FRAMES in ExplodingHouseScroll.tsx to: $FRAME_COUNT"
```

- [ ] Make executable and run:
```bash
chmod +x scripts/extract-frames.sh
cd /Users/rishabnandi/brandon-real-estate
bash scripts/extract-frames.sh
```

- [ ] Count frames and update `ExplodingHouseScroll.tsx` — find the line:
```ts
const TOTAL_FRAMES = 60;
```
Replace `60` with the actual count output by the script.

- [ ] Compress video for web:
```bash
ffmpeg -i frontend/public/assets/aerial_drone_shot.mp4 \
  -vf "scale=1920:-2" -c:v libx264 -crf 28 -preset slow \
  -an -movflags +faststart \
  frontend/public/assets/aerial_drone_shot_web.mp4
```

Update `Hero.tsx` `src` to use `aerial_drone_shot_web.mp4`.

- [ ] Commit:
```bash
git add scripts/ frontend/public/frames/ frontend/src/components/home/ExplodingHouseScroll.tsx
git commit -m "feat: extract house blast frames for scroll animation"
```

---

## Phase 11: Page-view Analytics + Final Wiring

### Task 23: Auto page-view tracking

**Files:**
- Create: `frontend/src/components/shared/PageViewTracker.tsx`
- Update: `frontend/src/app/layout.tsx`

- [ ] Create `frontend/src/components/shared/PageViewTracker.tsx`:
```tsx
'use client';
import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { trackEvent } from '@/lib/analytics';

export default function PageViewTracker() {
  const pathname = usePathname();
  useEffect(() => { trackEvent('page_view'); }, [pathname]);
  return null;
}
```

- [ ] Add `<PageViewTracker />` to `frontend/src/app/layout.tsx` inside the body, after `<Navbar />`.

- [ ] Commit:
```bash
git add frontend/src/components/shared/PageViewTracker.tsx frontend/src/app/layout.tsx
git commit -m "feat: automatic page view tracking on every route change"
```

---

### Task 24: Dockerfile + deployment prep

**Files:**
- Create: `backend/Dockerfile`
- Create: `frontend/vercel.json`

- [ ] Create `backend/Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] Create `frontend/vercel.json`:
```json
{
  "framework": "nextjs",
  "buildCommand": "npm run build",
  "devCommand": "npm run dev",
  "installCommand": "npm install"
}
```

- [ ] Update `tdtn.md` with all completed phases
- [ ] Update `memory.md` with integration status and final notes

- [ ] Final commit:
```bash
cd /Users/rishabnandi/brandon-real-estate
git add .
git commit -m "feat: complete Brandon RE platform build — all phases"
```

---

## Post-Build Checklist

- [ ] Set up Neon PostgreSQL → copy connection string → update `backend/.env` DATABASE_URL
- [ ] Run `alembic upgrade head` against Neon → run `seed.py`
- [ ] Deploy backend to Railway → set all env vars
- [ ] Deploy frontend to Vercel → set `NEXT_PUBLIC_API_URL` to Railway URL
- [ ] Test chatbot end-to-end with Gemini API
- [ ] Test property evaluator form
- [ ] Test investor calculator → meeting gate → full report
- [ ] Test admin login with seeded credentials
- [ ] Test lead creation → shows in admin → status update
- [ ] Test funnel creation → AI generation → publish → public page
- [ ] Update admin password from `changeme123!` to a strong password via seed or direct DB

---

## Environment Variables Summary

| Variable | Location | Value |
|----------|----------|-------|
| `NEXT_PUBLIC_API_URL` | Vercel | `https://api.soldwithsweeney.com` |
| `NEXT_PUBLIC_SITE_URL` | Vercel | `https://soldwithsweeney.com` |
| `DATABASE_URL` | Railway | Neon connection string |
| `GEMINI_API_KEY` | Railway | `<REDACTED_GEMINI_KEY>` |
| `GOOGLE_CLIENT_ID` | Railway | `<REDACTED_GOOGLE_CLIENT_ID>` |
| `GOOGLE_CLIENT_SECRET` | Railway | `<REDACTED_GOOGLE_CLIENT_SECRET>` |
| `JWT_SECRET` | Railway | Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `CORS_ORIGINS` | Railway | `https://soldwithsweeney.com,http://localhost:3000` |
