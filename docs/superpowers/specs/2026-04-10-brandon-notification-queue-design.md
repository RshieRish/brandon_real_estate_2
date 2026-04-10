# Brandon Notification Queue Design

**Goal:** Ensure Brandon receives internal email notifications for every important conversion event, with durable retry-until-delivered behavior even when SMTP or transient infrastructure fails.

**Problem Statement:** The current backend sends some emails inline and misses many event types entirely. Booking notifications only run after a full successful booking, most lead capture routes never notify Brandon at all, and SMTP failures are effectively silent. This makes notifications incomplete and unreliable.

## Scope

This design covers internal Brandon notifications for:

- Standard lead form submissions through `/api/v1/leads/`
- Funnel registrations through `/api/v1/funnels/{slug}/register`
- Chatbot lead capture through `/api/v1/chat/lead`
- Booking attempts through `/api/v1/booking/`
- Successful bookings through `/api/v1/booking/`
- Seller calculator submissions through `/api/v1/evaluator/`
- Seller calculator feedback submissions through `/api/v1/evaluator/{calculation_id}/rating`
- Investor full-report requests through `/api/v1/investor/analyze`
- Investor calculator engagement before lead capture through a new lightweight event endpoint

This design does not cover:

- Customer-facing email confirmations
- SMS or push notifications
- Admin UI for managing notification jobs

## Current State

The current backend behavior is fragmented:

- `backend/services/email_service.py` can send SMTP mail successfully, but only exposes direct helper functions.
- `backend/routers/booking.py` attempts a booking email only after calendar and database success.
- `backend/routers/leads.py`, `backend/routers/chat.py`, `backend/routers/funnels.py`, `backend/routers/evaluator.py`, and `backend/routers/investor.py` save important events without a reliable Brandon notification path.
- Email failures are masked because `_send_email()` returns `False` instead of raising, and callers mostly ignore that return value.

## Recommended Architecture

Use a database-backed notification job queue with best-effort immediate delivery and durable retry semantics.

### Core Principles

- User actions must be saved even if email sending fails.
- Notifications must be stored durably before send attempts begin.
- Failed sends must remain queued until delivered.
- Notification generation must be centralized so route coverage is easy to audit.
- Retry behavior must survive process restarts and Railway instance churn.

## Data Model

Add a new table: `notification_jobs`

Required fields:

- `id`
- `event_type`
- `status`
- `recipient`
- `subject`
- `payload_json`
- `attempt_count`
- `last_error`
- `next_attempt_at`
- `delivered_at`
- `created_at`
- `updated_at`

### Status Values

- `pending`: saved, not yet attempted
- `sending`: currently being attempted by the worker path
- `failed`: last send failed, but still retryable
- `delivered`: email was accepted by SMTP

### Event Types

- `lead_captured`
- `funnel_registration`
- `chat_lead_captured`
- `booking_attempted`
- `booking_confirmed`
- `seller_evaluator_calculated`
- `seller_evaluator_rated`
- `investor_report_requested`
- `investor_calculator_engaged`

## Notification Service

Create a dedicated notification queue service in the backend.

Responsibilities:

- Build the correct subject/body for each event type
- Create notification jobs from route payloads
- Attempt immediate delivery after the originating DB write succeeds
- Retry failed jobs with backoff
- Mark successful jobs as delivered
- Preserve the last failure reason for debugging

### Retry Policy

Use escalating backoff:

- Attempt 1: immediate
- Attempt 2: 1 minute later
- Attempt 3: 5 minutes later
- Attempt 4: 15 minutes later
- Attempt 5+: 60 minutes later

There is no hard stop. Jobs remain retryable until delivered.

## Delivery Flow

### For a synchronous route

1. Save the user action first.
2. Create one or more `notification_jobs` in the same DB transaction.
3. Commit the transaction.
4. Try to send newly created jobs immediately.
5. If send succeeds, mark as `delivered`.
6. If send fails, mark as `failed`, increment attempts, set `next_attempt_at`, and return success to the user anyway.

### For retry processing

Add a backend process path that can re-attempt due notification jobs by selecting jobs where:

- `status` is `pending` or `failed`
- `next_attempt_at` is null or in the past

The initial implementation can expose a reusable async function and call it opportunistically from request paths. A scheduled job can be added later if needed, but the data model must already support durable retries.

## Route Coverage Plan

### `/api/v1/leads/`

Queue `lead_captured` after lead creation.

Payload should include:

- `lead_id`
- `name`
- `email`
- `phone`
- `source`
- `lead_type`
- `metadata`

### `/api/v1/funnels/{slug}/register`

Queue `funnel_registration` after lead creation and registration increment.

Payload should include:

- `funnel_id`
- `funnel_slug`
- `funnel_title`
- `audience`
- `name`
- `email`
- `phone`

### `/api/v1/chat/lead`

Queue `chat_lead_captured` after lead creation.

Payload should include:

- `lead_id`
- `name`
- `email`
- `phone`
- `lead_type`
- `lead_context`

### `/api/v1/booking/`

Queue `booking_attempted` as soon as a user submits booking details and the attempt is worth notifying Brandon about. For the first version, this should happen after slot validation passes but before calendar insertion.

Queue `booking_confirmed` only after:

- calendar event creation succeeds
- booking row is saved successfully

If booking confirmation fails after event creation, delete the orphaned Google event and leave only the attempted notification.

### `/api/v1/evaluator/`

Always queue `seller_evaluator_calculated`, even if the visitor does not provide contact info.

Payload should include:

- `address`
- `property_type`
- `bedrooms`
- `bathrooms`
- `sqft`
- `year_built`
- `condition`
- `upgrades`
- `price_low`
- `price_high`
- `confidence`
- optional `name`
- optional `email`
- optional `phone`

### `/api/v1/evaluator/{calculation_id}/rating`

Queue `seller_evaluator_rated`.

Payload should include:

- `calculation_id`
- `rating`

### `/api/v1/investor/analyze`

Queue `investor_report_requested` after lead creation and report generation request starts.

Payload should include:

- `address`
- `property_type`
- `purchase_price`
- `down_payment_pct`
- `interest_rate`
- `hold_years`
- `monthly_rent_total`
- `rehab_costs`
- `name`
- `email`
- `phone`

### Investor preview engagement

Add a lightweight endpoint for one-time calculator engagement events so Brandon gets notified when someone meaningfully uses the investor calculator before submitting contact details.

Behavior:

- Frontend sends one event per browser session after the visitor changes the calculator inputs from defaults or spends enough time engaging with the tool.
- Backend queues `investor_calculator_engaged`.
- Payload contains only non-PII calculator context unless the user later submits contact details.

## Email Templates

Keep using Gmail SMTP for now, but move all Brandon-notification email rendering behind the queue service.

Each event type gets:

- a deterministic subject line
- a structured HTML body
- consistent sections for contact info, source, event details, and timestamps

Subjects should be explicit and searchable, for example:

- `New Lead Captured — Seller`
- `Booking Attempted — Phone Call`
- `Booking Confirmed — Phone Call`
- `Seller Calculator Used`
- `Investor Report Requested`

## Error Handling

- SMTP failure must not delete or lose the job.
- Template rendering failure should mark the job failed with `last_error`.
- Immediate-send exceptions must never break the original user action after the action has been persisted.
- Notification retries must be idempotent. A delivered job must never be sent twice.

## Testing Strategy

Add test coverage for:

- queue job creation from each covered route
- immediate-send success path
- immediate-send failure path with retry scheduling
- repeated retry scheduling behavior
- booking attempt + booking confirmation dual-notification behavior
- investor engagement endpoint deduplication by session key
- no duplicate resend after `delivered`

## Files Expected To Change

Backend:

- `backend/models/notification_job.py`
- `backend/alembic/versions/<new_revision>_add_notification_jobs.py`
- `backend/services/email_service.py`
- `backend/services/notification_service.py`
- `backend/routers/leads.py`
- `backend/routers/chat.py`
- `backend/routers/funnels.py`
- `backend/routers/booking.py`
- `backend/routers/evaluator.py`
- `backend/routers/investor.py`
- `backend/alembic/env.py`

Frontend:

- `frontend/src/components/investor/InvestorCalculator.tsx`
- `frontend/src/lib/api.ts` only if a helper is needed for the new investor engagement endpoint

Tests:

- new tests for notification queue behavior
- updates to affected route tests

## Rollout Notes

After implementation:

1. Run migrations.
2. Deploy backend.
3. Trigger one lead, one seller calculator use, one investor report request, and one booking test.
4. Confirm notification jobs move to `delivered`.
5. Confirm Brandon receives all expected internal emails.

## Design Decision Summary

The notification queue is the smallest design that makes Brandon alerts reliable. It preserves conversions, survives SMTP failures, and closes the current route-coverage gaps without introducing an outside dependency.
