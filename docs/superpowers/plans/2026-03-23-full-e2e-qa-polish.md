# Full E2E QA, Polish & Deployment-Ready Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test every feature end-to-end (backend + frontend), fix all issues, redesign funnel pages to Apple-quality using taste-skill, show example outputs from funnels/calculators, and make the application deployment-ready for Vercel (frontend) + Railway (backend).

**Architecture:** FastAPI backend (Python) on Railway talking to Neon PostgreSQL. Next.js 16 frontend on Vercel. Gemini 3.1 Pro/Flash Lite for AI features. Google Calendar OAuth2 for booking. All communication via REST `/api/v1/*` endpoints.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Next.js 16 App Router, Tailwind CSS 4, Framer Motion, Google Gemini (`gemini-3.1-pro-preview` / `gemini-3.1-flash-lite-preview`), Google Calendar API, Neon PostgreSQL.

---

## Phase 1: Backend Startup & E2E Verification

### Task 1: Start Backend, Run Migrations, Seed Database

**Files:**
- Verify: `backend/.env` (credentials present)
- Run: `backend/alembic/versions/8fa950e372a8_initial_schema.py`
- Run: `backend/seed.py`

- [ ] **Step 1: Install backend dependencies**

```bash
cd /Users/rishabnandi/brandon-real-estate/backend
pip install -r requirements.txt
```

- [ ] **Step 2: Run Alembic migrations against Neon DB**

```bash
cd /Users/rishabnandi/brandon-real-estate/backend
alembic upgrade head
```
Expected: "Running upgrade -> 8fa950e372a8, initial schema" (or already at head)

- [ ] **Step 3: Seed default admin user + content blocks**

```bash
cd /Users/rishabnandi/brandon-real-estate/backend
python seed.py
```
Expected: Creates admin user `info@soldwithsweeney.com` + 9 content blocks (or skips if already exist)

- [ ] **Step 4: Start FastAPI server on port 8001**

```bash
cd /Users/rishabnandi/brandon-real-estate/backend
uvicorn main:app --host 0.0.0.0 --port 8001 --reload &
```

- [ ] **Step 5: Verify health endpoint**

```bash
curl http://localhost:8001/health
```
Expected: `{"status":"ok"}` or similar 200 response

---

### Task 2: Test Auth Endpoints

**Files:**
- Test: `backend/routers/auth.py`

- [ ] **Step 1: Test login with seeded admin credentials**

```bash
curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"info@soldwithsweeney.com","password":"changeme123!"}' | python3 -m json.tool
```
Expected: `{"access_token":"<jwt>","token_type":"bearer"}`
Save the token for subsequent auth requests.

- [ ] **Step 2: Test /me endpoint with token**

```bash
TOKEN="<from step 1>"
curl -s http://localhost:8001/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
Expected: `{"id":1,"email":"info@soldwithsweeney.com"}`

- [ ] **Step 3: Test /me without token (should 401)**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/v1/auth/me
```
Expected: `401` or `403`

---

### Task 3: Test Leads CRUD

**Files:**
- Test: `backend/routers/leads.py`

- [ ] **Step 1: Create a test lead (public endpoint)**

```bash
curl -s -X POST http://localhost:8001/api/v1/leads/ \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Buyer","email":"test@example.com","phone":"5551234567","source":"manual_test","lead_type":"buyer"}' | python3 -m json.tool
```
Expected: 200/201 with lead object including `id`

- [ ] **Step 2: List leads (admin auth required)**

```bash
curl -s http://localhost:8001/api/v1/leads/ \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
Expected: Array containing the test lead

- [ ] **Step 3: Update lead status (admin auth required)**

```bash
curl -s -X PATCH http://localhost:8001/api/v1/leads/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"routing_status":"contacted","notes":"Test note from E2E"}' | python3 -m json.tool
```
Expected: Updated lead with new status and notes

---

### Task 4: Test Chat (Gemini AI)

**Files:**
- Test: `backend/routers/chat.py`
- Test: `backend/services/gemini.py`

- [ ] **Step 1: Send a chat message**

```bash
curl -s -X POST http://localhost:8001/api/v1/chat/ \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hi, I am looking to buy a home in Lowell MA. What should I know?"}]}' | python3 -m json.tool
```
Expected: AI response about buying in Lowell MA, mentioning Brandon Sweeney

- [ ] **Step 2: Test multi-turn conversation**

```bash
curl -s -X POST http://localhost:8001/api/v1/chat/ \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hi, I want to sell my home"},{"role":"model","content":"Great! I would love to help you explore selling your home..."},{"role":"user","content":"Its a 3 bed 2 bath in Tyngsboro MA"}]}' | python3 -m json.tool
```
Expected: Contextual response about selling in Tyngsboro

- [ ] **Step 3: Test chat lead capture**

```bash
curl -s -X POST http://localhost:8001/api/v1/chat/lead \
  -H "Content-Type: application/json" \
  -d '{"name":"Chat Lead","email":"chatlead@test.com","phone":"5559876543","lead_type":"seller","lead_context":{"conversation_topic":"selling 3bed in Tyngsboro"}}' | python3 -m json.tool
```
Expected: Lead created with source="chatbot"

- [ ] **Step 4: Fix any issues found** (model names, prompt quality, error handling)

---

### Task 5: Test Property Evaluator (Seller Tool)

**Files:**
- Test: `backend/routers/evaluator.py`
- Test: `backend/services/evaluator_service.py`

- [ ] **Step 1: Submit a property evaluation request**

```bash
curl -s -X POST http://localhost:8001/api/v1/evaluator/ \
  -H "Content-Type: application/json" \
  -d '{
    "address": "50 Cheever Ave, Lowell, MA 01851",
    "property_type": "single_family",
    "bedrooms": 3,
    "bathrooms": 2,
    "sqft": 1800,
    "year_built": 1960,
    "condition": "good",
    "upgrades": ["kitchen", "bathroom"],
    "name": "Eval Test",
    "email": "eval@test.com"
  }' | python3 -m json.tool
```
Expected: JSON with range_low, range_high, confidence, explanation, key_factors, coordinates

- [ ] **Step 2: Verify geocoding worked** (lat/lon should be near Lowell MA)

- [ ] **Step 3: Verify seller lead was captured in DB**

```bash
curl -s http://localhost:8001/api/v1/leads/ \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
Expected: Lead with source="evaluator" in the list

- [ ] **Step 4: Fix any issues** (Gemini response parsing, geocoding errors)

---

### Task 6: Test Investor Calculator & AI Analysis

**Files:**
- Test: `backend/routers/investor.py`
- Test: `backend/services/investor_service.py`

- [ ] **Step 1: Test pure calculator (no AI, no lead capture)**

```bash
curl -s -X POST http://localhost:8001/api/v1/investor/calculate \
  -H "Content-Type: application/json" \
  -d '{
    "purchase_price": 350000,
    "down_payment_pct": 20,
    "interest_rate": 7.0,
    "loan_term_years": 30,
    "monthly_rent_total": 2800,
    "rehab_costs": 45000,
    "annual_taxes": 4200,
    "annual_insurance": 1800,
    "monthly_maintenance": 200,
    "vacancy_rate_pct": 5,
    "mgmt_fee_pct": 8,
    "hold_years": 5,
    "appreciation_rate_pct": 3
  }' | python3 -m json.tool
```
Expected: JSON with mortgage_monthly, noi, cash_flow_monthly, cap_rate, cash_on_cash, etc.
**SAVE THIS OUTPUT** to show the user as a calculator example.

- [ ] **Step 2: Test AI analysis (requires email, creates lead)**

```bash
curl -s -X POST http://localhost:8001/api/v1/investor/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "purchase_price": 350000,
    "down_payment_pct": 20,
    "interest_rate": 7.0,
    "loan_term_years": 30,
    "monthly_rent_total": 2800,
    "rehab_costs": 45000,
    "annual_taxes": 4200,
    "annual_insurance": 1800,
    "monthly_maintenance": 200,
    "vacancy_rate_pct": 5,
    "mgmt_fee_pct": 8,
    "hold_years": 5,
    "appreciation_rate_pct": 3,
    "email": "investor@test.com"
  }' | python3 -m json.tool
```
Expected: JSON with both `metrics` and `analysis` (AI report with hold scenarios, exit comparison, sensitivity, verdict)
**SAVE THIS OUTPUT** to show the user as an AI analysis example.

- [ ] **Step 3: Verify investor lead was captured**

- [ ] **Step 4: Fix any issues** (calculation accuracy, Gemini JSON parsing)

---

### Task 7: Test Funnel Generation & Registration

**Files:**
- Test: `backend/routers/funnels.py`
- Test: `backend/services/funnel_service.py`

- [ ] **Step 1: Create a funnel via admin API (AI-generates content)**

```bash
curl -s -X POST http://localhost:8001/api/v1/funnels/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "title": "First-Time Homebuyer Workshop",
    "audience": "buyer",
    "description": "Free virtual workshop for first-time homebuyers in Massachusetts. Learn about pre-approval, searching, offers, and closing. Hosted by Brandon Sweeney, REALTOR of the Year.",
    "cta_text": "Reserve Your Spot",
    "lead_routing": "dashboard"
  }' | python3 -m json.tool
```
Expected: Funnel object with `generated_content` JSON (hero_headline, hero_subtext, value_props, etc.)
**SAVE THIS OUTPUT** to show the user as a funnel generation example.

- [ ] **Step 2: Create a second funnel (investor audience)**

```bash
curl -s -X POST http://localhost:8001/api/v1/funnels/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "title": "Real Estate Investor Meetup Merrimack Valley",
    "audience": "investor",
    "description": "Monthly meetup for real estate investors in the Merrimack Valley. Network, share deals, and learn flipping strategies with Brandon Sweeney who has closed 100+ deals.",
    "cta_text": "Join the Meetup",
    "lead_routing": "dashboard"
  }' | python3 -m json.tool
```
**SAVE THIS OUTPUT** as second funnel example.

- [ ] **Step 3: Publish the first funnel**

```bash
curl -s -X PUT http://localhost:8001/api/v1/funnels/<funnel_id>/publish \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
Expected: Funnel with status="published"

- [ ] **Step 4: Fetch published funnel by slug (public)**

```bash
curl -s http://localhost:8001/api/v1/funnels/first-time-homebuyer-workshop | python3 -m json.tool
```
Expected: Full funnel data with generated_content

- [ ] **Step 5: Register for the funnel**

```bash
curl -s -X POST http://localhost:8001/api/v1/funnels/first-time-homebuyer-workshop/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Funnel Registrant","email":"funnel@test.com","phone":"5551112222"}' | python3 -m json.tool
```
Expected: Lead created with source="funnel:first-time-homebuyer-workshop"

- [ ] **Step 6: Fix any issues** (slug generation, AI JSON parsing, publish flow)

---

### Task 8: Test Booking, Analytics, Content Endpoints

**Files:**
- Test: `backend/routers/booking.py`
- Test: `backend/routers/analytics.py`
- Test: `backend/routers/content.py`

- [ ] **Step 1: Create a booking**

```bash
curl -s -X POST http://localhost:8001/api/v1/booking/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Booking Test",
    "email": "booking@test.com",
    "phone": "5553334444",
    "meeting_type": "video",
    "context": "buyer_strategy",
    "scheduled_at": "2026-03-28T14:00:00Z",
    "notes": "First-time buyer in Lowell area"
  }' | python3 -m json.tool
```
Expected: Booking object with id

- [ ] **Step 2: Get available slots**

```bash
curl -s http://localhost:8001/api/v1/booking/available-slots | python3 -m json.tool
```
Expected: Array of date/time slots (currently hardcoded Mon-Fri 9-4)

- [ ] **Step 3: Track an analytics event**

```bash
curl -s -X POST http://localhost:8001/api/v1/analytics/event \
  -H "Content-Type: application/json" \
  -d '{"event_type":"page_view","page":"/buy","referrer":"https://google.com","user_agent":"Mozilla/5.0","metadata":{}}' | python3 -m json.tool
```

- [ ] **Step 4: Get analytics dashboard (admin)**

```bash
curl -s http://localhost:8001/api/v1/analytics/dashboard \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

- [ ] **Step 5: List content blocks**

```bash
curl -s http://localhost:8001/api/v1/content/ | python3 -m json.tool
```
Expected: 9 seeded content blocks

- [ ] **Step 6: Update a content block (admin)**

```bash
curl -s -X PUT http://localhost:8001/api/v1/content/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"content":"NOT your AVERAGE, award-winning, philanthropic REALTOR\u00ae OF THE YEAR 2025"}' | python3 -m json.tool
```

- [ ] **Step 7: Fix any issues found**

---

## Phase 2: Frontend Startup & E2E Verification

### Task 9: Start Frontend, Verify All Pages Render

**Files:**
- Verify: `frontend/.env.local` (NEXT_PUBLIC_API_URL=http://localhost:8001)
- Run: `frontend/package.json` scripts

- [ ] **Step 1: Install frontend dependencies**

```bash
cd /Users/rishabnandi/brandon-real-estate/frontend
npm install
```

- [ ] **Step 2: Start Next.js dev server**

```bash
cd /Users/rishabnandi/brandon-real-estate/frontend
npm run dev &
```

- [ ] **Step 3: Verify home page loads**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/
```
Expected: 200

- [ ] **Step 4: Verify all public routes return 200**

```bash
for route in / /buy /sell /invest /about; do
  echo "$route: $(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000$route)"
done
```
Expected: All 200

- [ ] **Step 5: Verify admin routes return 200**

```bash
for route in /admin /admin/login /admin/leads /admin/analytics /admin/content /admin/funnels /admin/settings; do
  echo "$route: $(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000$route)"
done
```
Expected: All 200 (client-side auth check, so HTML is always served)

- [ ] **Step 6: Run TypeScript type check**

```bash
cd /Users/rishabnandi/brandon-real-estate/frontend
npm run typecheck
```
Expected: No errors

- [ ] **Step 7: Run ESLint**

```bash
cd /Users/rishabnandi/brandon-real-estate/frontend
npm run lint
```
Expected: No errors (or only warnings)

- [ ] **Step 8: Run production build**

```bash
cd /Users/rishabnandi/brandon-real-estate/frontend
npm run build
```
Expected: Build succeeds with no errors

- [ ] **Step 9: Fix any build/type/lint errors found**

---

### Task 10: Test Frontend-Backend Integration (Live)

**Files:**
- Test: All components that call API endpoints

- [ ] **Step 1: Verify home page fetches content blocks from backend**

Open http://localhost:3000/ — hero text should show seeded content. Check browser devtools network tab for successful `/api/v1/content/` call.

- [ ] **Step 2: Test chatbot widget**

Open http://localhost:3000/ — click chat bubble. Send "I want to buy a house in Lowell". Verify AI response appears. Check network tab for `/api/v1/chat/` POST.

- [ ] **Step 3: Test property evaluator on /sell**

Open http://localhost:3000/sell — fill out PropertyEvaluator form with test address "50 Cheever Ave, Lowell, MA". Submit. Verify price range result appears. Check network tab for `/api/v1/evaluator/` POST.

- [ ] **Step 4: Test investor calculator on /invest**

Open http://localhost:3000/invest — fill in calculator inputs. Verify blurred preview shows metrics. Enter email in MeetingGate to unlock. Verify AnalysisResults display. Check network for `/api/v1/leads/` POST.

- [ ] **Step 5: Test lead capture form on /buy**

Open http://localhost:3000/buy — scroll to bottom lead form. Fill name/email/phone, submit. Verify success state. Check network for `/api/v1/leads/` POST.

- [ ] **Step 6: Test funnel page**

Open http://localhost:3000/f/first-time-homebuyer-workshop — verify funnel renders with AI-generated content. Fill registration form. Verify success. Check network for `/api/v1/funnels/first-time-homebuyer-workshop/register` POST.

- [ ] **Step 7: Test admin panel**

Open http://localhost:3000/admin/login — login with info@soldwithsweeney.com / changeme123!. Verify redirect to dashboard. Navigate to Leads — verify test leads appear. Navigate to Funnels — verify created funnels appear.

- [ ] **Step 8: Fix any integration issues** (CORS, endpoint mismatches, missing error handling)

---

## Phase 3: Funnel Page Redesign (Apple-Quality, Taste-Skill)

### Task 11: Redesign FunnelHero Component

**Files:**
- Rewrite: `frontend/src/components/funnel/FunnelHero.tsx`

Design principles (taste-skill DESIGN_VARIANCE:8, MOTION_INTENSITY:6, VISUAL_DENSITY:4):
- Full-viewport hero with cinematic gradient overlay on dark background
- Asymmetric layout: large headline left, event details card right
- Gold accent line on left edge (like buy page hero)
- Eyebrow tag with audience label (e.g., "FOR BUYERS")
- Headline with last word in gold with text-shadow glow
- Subtext in white/70 with font-light
- Bullet points with gold CheckCircle icons, staggered entrance animation
- Optional video embed in glassmorphic container with border glow
- Optional event date badge with gold border, pulsing glow
- HalftoneOverlay at opacity 0.04
- Framer Motion spring physics: stiffness:100, damping:20
- Bottom gradient fade to next section

- [ ] **Step 1: Read current FunnelHero.tsx**
- [ ] **Step 2: Rewrite with taste-skill design system**
- [ ] **Step 3: Verify renders correctly with test funnel data**
- [ ] **Step 4: Test responsive (mobile + desktop)**
- [ ] **Step 5: Commit**

---

### Task 12: Redesign FunnelRegistration Component

**Files:**
- Rewrite: `frontend/src/components/funnel/FunnelRegistration.tsx`

Design principles:
- Section with dark-card background + gold glow line at top
- Asymmetric 2-column: left has CTA copy + phone link, right has glassmorphic form card
- Form inputs: name, email, phone with gold focus borders
- Submit button: full-width gold bg with hover transition
- Loading state: shimmer animation on button
- Success state: animated CheckCircle with confetti-like gold particles, "You're In!" heading
- Error state: red-tinted glass card with warning icon
- HalftoneOverlay texture
- Staggered field entrance animations
- KW legal disclaimer at bottom

- [ ] **Step 1: Read current FunnelRegistration.tsx**
- [ ] **Step 2: Rewrite with taste-skill design system**
- [ ] **Step 3: Verify form submission works end-to-end**
- [ ] **Step 4: Test all states (idle, loading, success, error)**
- [ ] **Step 5: Commit**

---

### Task 13: Redesign Dynamic Funnel Page Layout

**Files:**
- Modify: `frontend/src/app/(main)/f/[slug]/page.tsx`

Design principles:
- Add social proof section between hero and registration (e.g., "100+ Deals Closed | 5-Star Rated | MA & NH")
- Add value proposition grid (3 cards from generated_content.value_props) with glassmorphic cards and spotlight hover effect
- Add testimonial section if generated_content.testimonial exists
- Ensure proper section spacing and gold accent dividers between sections
- Full mobile responsiveness

- [ ] **Step 1: Read current f/[slug]/page.tsx**
- [ ] **Step 2: Add social proof strip + value prop grid + testimonial section**
- [ ] **Step 3: Verify with test funnel**
- [ ] **Step 4: Test mobile responsive**
- [ ] **Step 5: Commit**

---

## Phase 4: Google Calendar Integration

### Task 14: Implement Google Calendar OAuth + Event Creation in Backend

**Files:**
- Create: `backend/services/calendar_service.py`
- Modify: `backend/routers/booking.py`
- Modify: `backend/config.py` (add GOOGLE_CALENDAR_ID, GOOGLE_REDIRECT_URI)

- [ ] **Step 1: Create calendar_service.py with OAuth2 flow**

Service should:
- Use google-auth-oauthlib + google-api-python-client (already in requirements.txt)
- Implement `get_auth_url()` -> returns OAuth consent URL
- Implement `exchange_code(code)` -> exchanges auth code for tokens, stores refresh token
- Implement `get_available_slots(days=14)` -> queries Brandon's calendar freebusy API
- Implement `create_event(booking)` -> creates calendar event with attendee info

- [ ] **Step 2: Add OAuth callback endpoint to booking router**

```python
@router.get("/calendar/auth-url")      # Admin only - returns OAuth URL
@router.get("/calendar/callback")       # OAuth callback - exchanges code
```

- [ ] **Step 3: Replace hardcoded available-slots with real Calendar API**

- [ ] **Step 4: Create calendar event when booking is created**

- [ ] **Step 5: Test OAuth flow end-to-end**

- [ ] **Step 6: Test event creation appears on calendar**

- [ ] **Step 7: Commit**

---

## Phase 5: Fix All Issues Found During Testing

### Task 15: Backend Bug Fixes

- [ ] **Step 1: Fix any Gemini model name issues** (ensure `gemini-3.1-pro-preview` and `gemini-3.1-flash-lite-preview` are correct)
- [ ] **Step 2: Fix any JSON parsing errors from Gemini responses**
- [ ] **Step 3: Fix any CORS issues** (ensure CORS_ORIGINS includes production domain)
- [ ] **Step 4: Fix any database query issues**
- [ ] **Step 5: Commit all fixes**

### Task 16: Frontend Bug Fixes

- [ ] **Step 1: Fix any TypeScript errors**
- [ ] **Step 2: Fix any missing error/loading states**
- [ ] **Step 3: Fix any responsive layout issues**
- [ ] **Step 4: Fix admin settings page** (currently stub)
- [ ] **Step 5: Commit all fixes**

---

## Phase 6: Show Example Outputs

### Task 17: Capture and Display Example Outputs

- [ ] **Step 1: Capture investor calculator output** (from Task 6 Step 1)
- [ ] **Step 2: Capture investor AI analysis output** (from Task 6 Step 2)
- [ ] **Step 3: Capture property evaluator output** (from Task 5 Step 1)
- [ ] **Step 4: Capture funnel generation output** (from Task 7 Step 1 & 2)
- [ ] **Step 5: Present all outputs to user with formatting**

---

## Phase 7: Deployment Readiness

### Task 18: Verify Deployment Configs

**Files:**
- Verify: `backend/Dockerfile`
- Verify: `backend/railway.json`
- Verify: `frontend/vercel.json`
- Modify: `backend/.env` (add CORS_ORIGINS for production domain)

- [ ] **Step 1: Verify Dockerfile builds**

```bash
cd /Users/rishabnandi/brandon-real-estate/backend
docker build -t brandon-re-backend .
```

- [ ] **Step 2: Verify Railway config is correct**
- [ ] **Step 3: Verify Vercel config is correct**
- [ ] **Step 4: Update CORS_ORIGINS for production**

```
CORS_ORIGINS=http://localhost:3000,https://soldwithsweeney.com,https://www.soldwithsweeney.com
```

- [ ] **Step 5: Verify frontend production build passes**

```bash
cd /Users/rishabnandi/brandon-real-estate/frontend
NEXT_PUBLIC_API_URL=https://api.soldwithsweeney.com npm run build
```

- [ ] **Step 6: Document deployment steps in README**
- [ ] **Step 7: Commit**

---

## Execution Order

1. Tasks 1-8 (Backend E2E) — sequential, each depends on server running
2. Tasks 9-10 (Frontend E2E) — after backend is verified
3. Tasks 11-13 (Funnel redesign) — can start after Task 10 confirms funnels work
4. Task 14 (Google Calendar) — independent, can run parallel with funnel redesign
5. Tasks 15-16 (Bug fixes) — after all testing is complete
6. Task 17 (Example outputs) — collected during Tasks 4-7
7. Task 18 (Deployment) — final step after everything is fixed
