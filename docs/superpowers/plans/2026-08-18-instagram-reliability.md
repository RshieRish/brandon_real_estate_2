# Instagram Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the browser-side Instagram token path with a backend-owned, observable, cache-backed feed that fails safely, reports credential/API-version risk, and can be verified against production without exposing credentials.

**Architecture:** The backend calls Meta Graph with a bearer header, normalizes approved public fields, and atomically publishes a persisted feed snapshot. The public API reads that projection and reports `live`, `stale_cache`, or `unavailable`; the Next.js homepage never receives a token. The integration worker performs refresh and daily health/version checks, with deduplicated alerts and explicit feature flags.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, PostgreSQL, Alembic, HTTPX, Meta Graph API, Next.js/React/TypeScript, Vitest, Testing Library, Playwright, GitHub Actions, Railway, Vercel.

---

## File Structure

Create:

- `backend/models/instagram.py`, `backend/schemas/instagram.py`
- `backend/services/instagram_service.py`, `backend/routers/instagram.py`
- `backend/workers/jobs/instagram_health.py`
- `backend/alembic/versions/85e8b6a0c3d4_add_instagram_feed_cache.py`
- `backend/scripts/validate_instagram_graph_version.py`
- `backend/scripts/verify_instagram_production.py`
- `backend/scripts/verify_instagram_failover.py`
- `backend/tests/test_instagram_config.py`, `backend/tests/test_instagram_secret_redaction.py`
- `backend/tests/test_instagram_models.py`, `backend/tests/test_instagram_migration.py`
- `backend/tests/test_instagram_service.py`, `backend/tests/test_instagram_router.py`
- `backend/tests/test_instagram_health_job.py`, `backend/tests/test_instagram_verification_scripts.py`
- `frontend/src/types/instagram.ts`, `frontend/src/lib/instagram.ts`, `frontend/src/lib/instagram.test.ts`
- `frontend/src/lib/instagram-image-config.test.ts`
- `frontend/src/components/home/InstagramFeed.test.tsx`, `frontend/src/lib/analytics.test.ts`
- `frontend/src/app/admin/settings/page.test.tsx`
- `frontend/e2e/instagram-production.spec.ts`, `frontend/playwright.production.config.ts`
- `.github/workflows/instagram-reliability.yml`
- `docs/deployment/instagram-reliability.md`

Modify:

- `backend/config.py`, `backend/.env.example`, `backend/main.py`
- `backend/models/__init__.py`, `backend/alembic/env.py`
- worker registry and notification dedupe service from the Gmail/Sydney plan
- `frontend/src/app/(main)/page.tsx`
- `frontend/src/components/home/InstagramFeed.tsx` and its test
- `frontend/src/lib/analytics.ts` and its test
- `frontend/src/app/admin/settings/page.tsx` and its test
- `frontend/next.config.ts`
- `tdtn.md`, `memory.md`

## Prerequisite and Ownership Boundary

Do not start the Instagram migration or worker job until the Gmail/Sydney plan has landed the single chain through `84d7a5f9b2c3` and created the shared integration worker/runtime:

```text
81a4d2c6e9f0 CRM task foundation
  -> 82b5e3d7f0a1 integration runtime health + worker + alert dedupe
  -> 83c6f4e8a1b2 Gmail intake
  -> 84d7a5f9b2c3 Sydney review
  -> 85e8b6a0c3d4 Instagram feed cache
```

`85e8b6a0c3d4_add_instagram_feed_cache.py` must declare `down_revision = "84d7a5f9b2c3"`. Reuse `IntegrationHealthState`, `IntegrationWorkerHeartbeat`, notification provider/dedupe keys, the worker job registry, `/health`, and `/ready`; do not create a second health table, notification queue, worker app, or FastAPI startup loop.

Use the same isolated PostgreSQL database from the Gmail/Sydney plan after it reaches head `84d7a5f9b2c3`, exported as `INSTAGRAM_TEST_DATABASE_URL`. The database name must end in `_test` and must not match any development, staging, or production URL. Migration, advisory-lock, refresh, and worker tests require real PostgreSQL rather than SQLite or a parse-only URL.

## Locked Public API and Cache Contract

The public response is exactly:

```python
class InstagramMediaItem(BaseModel):
    id: str
    caption_preview: str | None
    media_type: Literal["IMAGE", "VIDEO", "CAROUSEL_ALBUM"]
    display_url: AnyHttpUrl
    permalink: AnyHttpUrl
    published_at: datetime | None

class InstagramFeedResponse(BaseModel):
    items: list[InstagramMediaItem]
    source: Literal["live", "stale_cache", "unavailable"]
    fetched_at: datetime | None
    degraded: bool
```

`GET /api/v1/instagram/feed` always returns HTTP 200 with no provider error details:

| Condition | Exact response behavior |
|---|---|
| Healthy last-success snapshot within `INSTAGRAM_CACHE_MAX_STALE_SECONDS` | `source="live"`, persisted items, snapshot `fetched_at`, `degraded=false`. |
| Latest check failed but last-good snapshot age is within `INSTAGRAM_CACHE_MAX_STALE_SECONDS` | `source="stale_cache"`, persisted items, original `fetched_at`, `degraded=true`. |
| No snapshot or snapshot age exceeds `INSTAGRAM_CACHE_MAX_STALE_SECONDS` | HTTP 200 with `items=[]`, `source="unavailable"`, `fetched_at=null`, `degraded=true`. |

Protected `GET /api/v1/admin/integrations/instagram/status` returns HTTP 200 for healthy or unhealthy state. Protected `POST /api/v1/admin/integrations/instagram/check` returns HTTP 200 only for a successful explicit Graph check; authentication/permission/provider failure returns non-2xx (503) with the typed sanitized health state and `reauthorization_required`, never raw Meta payloads, request URLs, account IDs, or credentials.

`InstagramFeedCache` uses a singleton `cache_key="homepage"` row containing normalized `items_json`, `fetched_at`, SHA-256 `content_hash`, and `expires_at = fetched_at + INSTAGRAM_CACHE_MAX_STALE_SECONDS`. The token is never a model field. `IntegrationHealthState(provider="instagram")` determines whether an unexpired snapshot is `live` or `stale_cache`.

## Task 1: Define and validate the backend-only Instagram configuration

**Files:** Modify `backend/config.py` and `backend/.env.example`; create `backend/tests/test_instagram_config.py`, `backend/tests/test_instagram_secret_redaction.py`, and `backend/scripts/validate_instagram_graph_version.py`.

- [ ] **Step 1: Before coding, browse only official Meta documentation** to confirm the currently supported Graph API version and published sunset date. Record the source/date in the deployment doc; do not guess a future sunset.
- [ ] **Step 2: Write failing config tests** for these exact server-only settings:

```text
INSTAGRAM_GRAPH_ACCESS_TOKEN                 SecretStr; required only when enabled
INSTAGRAM_BUSINESS_ACCOUNT_ID               SecretStr; required only when enabled
INSTAGRAM_GRAPH_API_VERSION                 ^v[0-9]+\.[0-9]+$
INSTAGRAM_GRAPH_API_VERSION_SUNSET_AT       timezone-aware UTC datetime
INSTAGRAM_REFRESH_INTERVAL_SECONDS          integer >= 300
INSTAGRAM_CACHE_MAX_STALE_SECONDS           integer >= refresh interval
INSTAGRAM_INTEGRATION_ENABLED               boolean, default false
```

`INSTAGRAM_INTEGRATION_ENABLED` is the rollout gate; the first six values are the integration contract. Assert both secrets are redacted from validation errors, settings reprs, HTTP errors, and logs. Do not introduce any `NEXT_PUBLIC_INSTAGRAM_*` variable.
- [ ] **Step 3: Run:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$INSTAGRAM_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_instagram_config.py tests/test_instagram_secret_redaction.py
```

- [ ] **Step 4: Implement config and validator.** Fixtures use obvious non-secret sentinels and assert those sentinels never reappear in captured output. Never add the previously supplied credential to a file, command, fixture, deployment variable, or log; production authorization must create a replacement directly in the Railway secret store.
- [ ] **Step 5: Re-run tests and commit:** `feat: add safe Instagram configuration`.

## Task 2: Add persisted feed snapshots and health state

**Files:** Create `backend/models/instagram.py` and `backend/alembic/versions/85e8b6a0c3d4_add_instagram_feed_cache.py`; modify `backend/models/__init__.py` and `backend/alembic/env.py`; create `backend/tests/test_instagram_models.py` and `backend/tests/test_instagram_migration.py`.

- [ ] **Step 1: Write failing model tests** for one `InstagramFeedCache` row keyed by `cache_key="homepage"`. Its only persisted fields are `cache_key`, normalized `items_json`, `fetched_at`, `expires_at`, `content_hash`, `created_at`, and `updated_at`; the model has no token, account ID, provider payload, or error columns. Validate each JSON item against `InstagramMediaItem` before persistence.
- [ ] **Step 2: Write migration-chain tests** requiring `revision = "85e8b6a0c3d4"`, `down_revision = "84d7a5f9b2c3"`, one Alembic head, a unique/primary constraint on `cache_key`, non-null timestamp/hash constraints, and a database check restricting `cache_key` to `homepage`. Error state and alert dedupe remain in the shared runtime tables from revision `82b5e3d7f0a1`.
- [ ] **Step 3: Run the focused tests** and confirm the expected missing-model failure:

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$INSTAGRAM_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_instagram_models.py tests/test_instagram_migration.py
```

- [ ] **Step 4: Implement atomic publication** by validating the complete normalized list, then upserting the singleton row and its SHA-256 `content_hash` in one database transaction. Any exception rolls the whole transaction back, leaving the previous row intact. Store classified failures only in sanitized `IntegrationHealthState`; never persist provider responses.
- [ ] **Step 5: Re-run tests, run `alembic heads`, and commit:** `feat: persist Instagram feed snapshots`.

## Task 3: Implement the Graph client, normalization, and safe refresh

**Files:** Create `backend/services/instagram_service.py` and `backend/tests/test_instagram_service.py`; extend `backend/tests/test_instagram_secret_redaction.py`.

- [ ] **Step 1: Write failing HTTP tests** proving the token is sent only as an `Authorization: Bearer` header, request URLs/logs contain no credential, requests ask only for the fields needed by `InstagramMediaItem`, pagination is capped at three pages and 24 normalized items, malformed items are skipped with a count, and Meta error codes 190/463 are classified as `credential_expired`.
- [ ] **Step 2: Add refresh tests** for successful atomic publication; a transient connect/timeout/429/5xx failure retaining the last-good row; invalid credentials or permissions retaining cache while marking health unhealthy; HTTPS media/permalink validation; and a shared PostgreSQL advisory lock preventing concurrent refreshes. Retry only connect/timeout/429/5xx at most three attempts with deterministic injected backoff; never retry 190/463 or other authentication/permission failures.
- [ ] **Step 3: Run:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$INSTAGRAM_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_instagram_service.py \
  tests/test_instagram_secret_redaction.py
```

- [ ] **Step 4: Implement** a typed HTTPX client, normalization, singleton-cache publisher, and health calculation. Use the configured version in the URL path, a bearer header, a finite connect/read timeout, and no automatic HTTPX request logging. Do not claim a credential can never expire; distinguish scheduled expiry, revoked authorization, password/security invalidation, permission loss, and API-version sunset.
- [ ] **Step 5: Re-run tests and commit:** `feat: refresh Instagram feed safely`.

## Task 4: Expose the public feed and authenticated health controls

**Files:** Create `backend/schemas/instagram.py`, `backend/routers/instagram.py`, and `backend/tests/test_instagram_router.py`; modify `backend/main.py`.

- [ ] **Step 1: Write failing route tests** for public `GET /api/v1/instagram/feed` and protected status/check endpoints. Assert the public JSON has exactly `items`, `source`, `fetched_at`, and `degraded` at the top level; items have exactly the six fields in `InstagramMediaItem`; and neither route exposes internal errors, credentials, account IDs, provider responses, or request URLs.
- [ ] **Step 2: Cover every projection/HTTP state:**

```python
healthy_and_unexpired = (200, {"source": "live", "degraded": False})
failed_but_unexpired  = (200, {"source": "stale_cache", "degraded": True})
missing_or_expired    = (200, {"items": [], "source": "unavailable", "fetched_at": None, "degraded": True})
admin_status_unhealthy = 200
admin_check_failed     = 503
```

- [ ] **Step 3: Implement only these routes:** `GET /api/v1/instagram/feed`, `GET /api/v1/admin/integrations/instagram/status`, and `POST /api/v1/admin/integrations/instagram/check`. The public route reads PostgreSQL only and uses `Cache-Control: public, max-age=60, stale-while-revalidate=300`; it never calls Graph in a request. The check route runs the same advisory-lock-protected refresh as the worker. Require the existing admin auth dependency on both admin routes, propagate the request ID, and return only typed redacted health fields.
- [ ] **Step 4: Run route/security tests and commit:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$INSTAGRAM_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_instagram_router.py tests/test_instagram_secret_redaction.py
```

Commit: `feat: add Instagram feed API`.

## Task 5: Replace the frontend Graph call with the backend projection

**Files:** Create `frontend/src/types/instagram.ts`, `frontend/src/lib/instagram.ts`, `frontend/src/lib/instagram.test.ts`, and `frontend/src/lib/instagram-image-config.test.ts`; modify `frontend/src/app/(main)/page.tsx`, `frontend/src/components/home/InstagramFeed.tsx`, `frontend/src/components/home/InstagramFeed.test.tsx`, `frontend/src/lib/analytics.ts`, `frontend/src/lib/analytics.test.ts`, `frontend/src/app/admin/settings/page.tsx`, `frontend/src/app/admin/settings/page.test.tsx`, and `frontend/next.config.ts`.

- [ ] **Step 1: Read and apply `frontend-design` and `vercel-react-best-practices` before editing frontend code.**
- [ ] **Step 2: Write failing tests** proving no `NEXT_PUBLIC_INSTAGRAM_*` token/account dependency, the homepage fetches only `${NEXT_PUBLIC_API_URL}/api/v1/instagram/feed`, live/stale/unavailable render states are accessible, fallback content is explicitly labeled, and the feed root emits `data-instagram-source` and `data-instagram-fetched-at` for production verification. A `source="live"` card must render the API `id`, `permalink`, and `display_url`, never a local fallback asset.
- [ ] **Step 3: Add `frontend/src/lib/instagram-image-config.test.ts`** to import `frontend/next.config.ts` and require a narrow HTTPS `images.remotePatterns` entry for `**.cdninstagram.com` (plus an official hostname observed in the controlled Graph response if different). Reject a catch-all hostname, `http:`, and any URL containing a credential or account ID.
- [ ] **Step 4: Add a failing analytics regression test** for the existing endpoint/payload mismatch, then fix the client to call `/api/v1/analytics/event` with backend-compatible field names.
- [ ] **Step 5: Run:**

```bash
cd frontend
npm test -- src/lib/instagram.test.ts src/lib/instagram-image-config.test.ts \
  src/components/home/InstagramFeed.test.tsx \
  src/lib/analytics.test.ts src/app/admin/settings/page.test.tsx
```

- [ ] **Step 6: Implement** the typed server fetch and SWS-branded loading/empty/error states. Preserve mobile behavior, avoid native dialogs, and never treat branded fallback cards as live Instagram evidence. `next.config.ts` is the only Next configuration file to modify.
- [ ] **Step 7: Re-run focused tests, `npm run typecheck`, `npm run build`, and commit:** `fix: proxy Instagram through the backend`.

## Task 6: Add worker health checks, CI sunset guard, and deployment verification

**Files:** Create `backend/workers/jobs/instagram_health.py`, `backend/tests/test_instagram_health_job.py`, `backend/scripts/verify_instagram_production.py`, `backend/scripts/verify_instagram_failover.py`, `backend/tests/test_instagram_verification_scripts.py`, `.github/workflows/instagram-reliability.yml`, `frontend/e2e/instagram-production.spec.ts`, `frontend/playwright.production.config.ts`, and `docs/deployment/instagram-reliability.md`; modify the shared worker registry.

- [ ] **Step 1: Write failing worker tests** for interval refresh, one daily credential probe, one daily Graph-version check, the shared advisory lock, and exact alert transitions. Expiry warnings use dedupe keys `instagram:credential_expiry:90`, `:60`, `:30`, and `:7`; each fires once on entry into its UTC-day threshold. Provider unhealthy alerts use `instagram:health:{reason}:{failure_epoch}`. A transition from unhealthy to a successful live refresh emits exactly one `instagram:health:recovered:{failure_epoch}` notification, and subsequent successes emit none.
- [ ] **Step 2: Implement and register the job** in the shared integration worker only after revision `84d7a5f9b2c3` and the worker runtime are deployed. The CI validator fails inside each 90/60/30/7-day version-sunset threshold and directs maintainers to the dated official Meta source recorded in the deployment doc. Do not register a FastAPI startup scheduler.
- [ ] **Step 3: Run exact worker/script tests:**

```bash
cd backend
JWT_SECRET=test-secret DATABASE_URL="$INSTAGRAM_TEST_DATABASE_URL" PYTHONPATH=. \
  /Users/rishabnandi/brandon-real-estate/backend/.venv/bin/pytest -q \
  tests/test_instagram_health_job.py tests/test_instagram_verification_scripts.py
```

- [ ] **Step 4: Implement production verification** so the script accepts credentials only through the process environment, redacts subprocess/stdout failures, fetches controlled Graph media, and asserts at least three current IDs/permalinks match the public API. For each matched item, require the exact `display_url` to return HTTP 200 with `Content-Type: image/*` and non-zero bytes. Then require the production DOM to report `data-instagram-source="live"`, contain those same IDs/permalinks, and contain no fallback marker. The failover verifier uses an authenticated, explicitly enabled test hook and restores the original state in `finally`, including after an assertion failure.
- [ ] **Step 5: Add Playwright production checks** that fail on `stale_cache`, `unavailable`, local placeholder assets, generic fallback frames, missing media bytes, or a browser request to `graph.facebook.com`. Capture the API JSON, three media-response headers, DOM attributes, and screenshot as the release artifact.
- [ ] **Step 6: Deploy in dependency order:**

1. Confirm database head `84d7a5f9b2c3`, deploy the shared integration worker, and prove its `/health` and `/ready` endpoints.
2. Deploy backend revision `85e8b6a0c3d4`, run `alembic upgrade head`, and confirm exactly one head.
3. Add the seven named Instagram settings directly to Railway services `extraordinary-prosperity` and `integration-worker`. Verify the service names first with `scripts/railway-sweeney service status --all`, then verify secret-key names in the Railway dashboard without opening or copying their values.
4. Enable the integration, run the protected check once, and require a live singleton cache plus healthy shared state before frontend deployment.
5. Vercel is currently unlinked in this worktree. Run `npx vercel whoami`, `npx vercel project ls`, and `npx vercel domains inspect soldwithsweeney.com`; record the owning team, project ID, and production Git branch in the deployment doc. Link `frontend/` only to that verified project, inspect `frontend/.vercel/project.json`, and abort if its `orgId`/`projectId` differs. Deploy with `npx vercel deploy --prod --cwd frontend` only after the domain inspection proves the target serves `soldwithsweeney.com`.

- [ ] **Step 7: Run live verification without printing a credential:**

```bash
curl --fail --silent https://api.soldwithsweeney.com/health
curl --fail --silent https://api.soldwithsweeney.com/api/v1/instagram/feed | jq '{source,fetched_at,degraded,item_count:(.items|length),ids:[.items[0:3][].id]}'
cd frontend
PRODUCTION_BASE_URL=https://soldwithsweeney.com npm run test:e2e -- instagram-production.spec.ts
```

Also run the backend verifier in the Railway backend service so its secret remains server-side, scan the deployed HTML/JS and browser network log for `NEXT_PUBLIC_INSTAGRAM`, `graph.facebook.com`, and the configured secret fingerprint, and require zero matches. Store only redacted evidence.
- [ ] **Step 8: Run focused and full backend/frontend suites plus `git diff --check`.** Update `tdtn.md` and `memory.md` with exact command output, deployment IDs, API state, three matched media IDs, media response headers, DOM state, and artifact paths.
- [ ] **Step 9: Commit:** `chore: verify Instagram reliability`.

## Rollout Gate

Keep `INSTAGRAM_INTEGRATION_ENABLED=false` until a newly authorized long-lived Page credential and the correct Instagram Business account ID are supplied directly through Railway secrets, revision `85e8b6a0c3d4` and the shared worker are healthy, the first refresh publishes a valid singleton snapshot, and the verified production Vercel project renders `source="live"`. The previously supplied credential must not be copied or reused. “Never expires” is not a valid guarantee; the operational target is 90/60/30/7-day warnings, early rotation, cache continuity, deduplicated failure/recovery alerts, and clear handling of revocation or permission loss.

Production acceptance is not satisfied by a pretty grid, fallback cards, fixture IDs, a successful build, or a `200` feed alone. It requires one evidence bundle showing: healthy worker `/ready`; database head `85e8b6a0c3d4`; public `source="live"`, `degraded=false`, and a recent `fetched_at`; at least three IDs/permalinks equal to the controlled server-side Graph response; those exact media URLs returning image bytes; those same IDs/permalinks rendered on `soldwithsweeney.com` with no fallback marker; and zero credential/Graph requests in browser-delivered HTML, JavaScript, or network logs.
