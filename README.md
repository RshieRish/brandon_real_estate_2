# Brandon Real Estate Platform

AI-powered real estate conversion platform for Brandon Sweeney (SoldWithSweeney.com).

## Tech Stack
- **Frontend**: Next.js 14 + Tailwind v4 → Vercel
- **Backend**: FastAPI + Uvicorn → Railway
- **DB**: PostgreSQL (Neon) via SQLAlchemy 2.0 async
- **AI**: Google Gemini

## Quick Start

### Backend
```bash
cd backend
cp .env.example .env  # fill in your values
pip install -r requirements.txt
alembic upgrade head
python seed.py        # creates default admin user
uvicorn main:app --reload
```

### Frontend
```bash
cd frontend
cp .env.example .env.local  # fill in NEXT_PUBLIC_API_URL
npm install
npm run dev
```

## Deployment

### Backend → Railway
1. Connect GitHub repo to Railway
2. Set root directory to `backend/`
3. Add environment variables from `.env.example`
4. Railway auto-detects `Dockerfile` and deploys

### Frontend → Vercel
1. Import GitHub repo in Vercel
2. Set root directory to `frontend/`
3. Add `NEXT_PUBLIC_API_URL` env var pointing to Railway URL
4. Deploy

## First-time Setup
After deploying backend, run migrations:
```bash
DATABASE_URL=your-neon-url alembic upgrade head
```
Then seed the admin user and **immediately change the password**.
