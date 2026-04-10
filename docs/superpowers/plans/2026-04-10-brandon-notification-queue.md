# Brandon Notification Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable Brandon-only internal email notification queue that saves lead, booking, and calculator events first, then retries email delivery until successful.

**Architecture:** Add a new `notification_jobs` table plus a backend notification service that queues jobs, renders email content by event type, and attempts immediate delivery with durable retry state. Integrate that service into every relevant backend route and add one lightweight investor-engagement endpoint so non-contact calculator usage still alerts Brandon.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Gmail SMTP via `aiosmtplib`, Next.js client event ping, Python `unittest`

---

## File Structure

### New files

- `backend/models/notification_job.py`
  - SQLAlchemy model for durable notification jobs
- `backend/alembic/versions/<revision>_add_notification_jobs.py`
  - Migration to create the `notification_jobs` table
- `backend/services/notification_service.py`
  - Job enqueue, template rendering, immediate send, retry scheduling, due-job processing
- `backend/tests/test_notification_service.py`
  - Queue/service-level tests
- `backend/tests/test_leads_notifications.py`
  - Lead/chat/funnel route coverage
- `backend/tests/test_investor_notifications.py`
  - Investor route and engagement-event coverage

### Modified files

- `backend/alembic/env.py`
  - Import new model for migrations
- `backend/services/email_service.py`
  - Expose a lower-level send primitive that raises on failure for the queue service
- `backend/routers/leads.py`
  - Queue lead notifications after lead persistence
- `backend/routers/chat.py`
  - Queue chat lead notifications after lead persistence
- `backend/routers/funnels.py`
  - Queue funnel registration notifications after lead persistence
- `backend/routers/booking.py`
  - Queue booking attempt + booking confirmed notifications and process due jobs
- `backend/routers/evaluator.py`
  - Queue seller calculator + rating notifications
- `backend/routers/investor.py`
  - Queue investor report notifications and add investor engagement endpoint
- `frontend/src/components/investor/InvestorCalculator.tsx`
  - Send one investor engagement event per browser session
- `backend/tests/test_booking_calendar.py`
  - Update booking expectations for queued notifications
- `backend/tests/test_evaluator_router.py`
  - Extend evaluator expectations for queued notifications
- `tdtn.md`
  - Record the notification queue implementation work
- `memory.md`
  - Record the durable notification architecture decision

---

### Task 1: Add The Notification Job Model And Migration

**Files:**
- Create: `backend/models/notification_job.py`
- Modify: `backend/alembic/env.py`
- Create: `backend/alembic/versions/<revision>_add_notification_jobs.py`
- Test: `backend/tests/test_notification_service.py`

- [ ] **Step 1: Write the failing model/migration test**

```python
class NotificationQueueModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_notification_job_table_has_retry_fields(self):
        async with AsyncSessionLocal() as db:
            rows = await db.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'notification_jobs'
                ORDER BY ordinal_position
            """))
            columns = [row[0] for row in rows]

        self.assertIn('event_type', columns)
        self.assertIn('status', columns)
        self.assertIn('attempt_count', columns)
        self.assertIn('next_attempt_at', columns)
        self.assertIn('delivered_at', columns)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest tests.test_notification_service.NotificationQueueModelTests.test_notification_job_table_has_retry_fields -v`

Expected: FAIL because `notification_jobs` does not exist yet.

- [ ] **Step 3: Write the model and migration**

```python
class NotificationJob(Base):
    __tablename__ = "notification_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    recipient: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    payload_json: Mapped[str] = mapped_column("payload", Text, default="{}")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

```python
def upgrade() -> None:
    op.create_table(
        "notification_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
```

- [ ] **Step 4: Run the migration test and Alembic upgrade**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/alembic upgrade head && ./.venv/bin/python -m unittest tests.test_notification_service.NotificationQueueModelTests.test_notification_job_table_has_retry_fields -v`

Expected: migration succeeds, test passes.

- [ ] **Step 5: Commit**

```bash
git add backend/models/notification_job.py backend/alembic/env.py backend/alembic/versions/*.py backend/tests/test_notification_service.py
git commit -m "feat: add notification job queue model"
```

---

### Task 2: Build The Core Notification Queue Service

**Files:**
- Create: `backend/services/notification_service.py`
- Modify: `backend/services/email_service.py`
- Test: `backend/tests/test_notification_service.py`

- [ ] **Step 1: Write the failing queue service tests**

```python
class NotificationQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_notification_creates_pending_job(self):
        job = await enqueue_notification(
            db,
            event_type="lead_captured",
            payload={"name": "Jane Doe", "email": "jane@example.com"},
        )
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.recipient, "brandon@soldwithsweeney.com")

    async def test_send_job_marks_delivered_on_success(self):
        job = NotificationJob(...)
        with patch("services.notification_service.send_internal_email", AsyncMock()):
            await attempt_notification_delivery(db, job)
        self.assertEqual(job.status, "delivered")
        self.assertEqual(job.attempt_count, 1)

    async def test_send_job_schedules_retry_on_failure(self):
        job = NotificationJob(...)
        with patch("services.notification_service.send_internal_email", AsyncMock(side_effect=RuntimeError("smtp down"))):
            await attempt_notification_delivery(db, job)
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.attempt_count, 1)
        self.assertIsNotNone(job.next_attempt_at)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest tests.test_notification_service.NotificationQueueTests -v`

Expected: FAIL because the queue service functions do not exist yet.

- [ ] **Step 3: Add the queue service and low-level send function**

```python
BRANDON_NOTIFICATION_EMAIL = "brandon@soldwithsweeney.com"

async def send_internal_email(*, subject: str, body_html: str, to: str = BRANDON_NOTIFICATION_EMAIL) -> None:
    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        start_tls=True,
        username=settings.SMTP_USER,
        password=settings.SMTP_PASS,
    )
```

```python
async def enqueue_notification(db: AsyncSession, *, event_type: str, payload: dict) -> NotificationJob:
    subject, body_html = render_notification_email(event_type, payload)
    job = NotificationJob(
        event_type=event_type,
        status="pending",
        recipient=BRANDON_NOTIFICATION_EMAIL,
        subject=subject,
        payload_json=json.dumps(payload),
    )
    db.add(job)
    await db.flush()
    return job


async def attempt_notification_delivery(db: AsyncSession, job: NotificationJob) -> None:
    payload = json.loads(job.payload_json or "{}")
    _, body_html = render_notification_email(job.event_type, payload, subject_override=job.subject)
    try:
        job.status = "sending"
        await db.flush()
        await send_internal_email(subject=job.subject, body_html=body_html, to=job.recipient)
    except Exception as exc:
        job.status = "failed"
        job.attempt_count += 1
        job.last_error = str(exc)
        job.next_attempt_at = calculate_next_attempt_at(job.attempt_count)
        await db.flush()
        return

    job.status = "delivered"
    job.attempt_count += 1
    job.delivered_at = datetime.now(timezone.utc)
    job.next_attempt_at = None
    job.last_error = None
    await db.flush()
```

- [ ] **Step 4: Add retry scheduling and due-job processing**

```python
def calculate_next_attempt_at(attempt_count: int) -> datetime:
    delay_minutes = 1 if attempt_count == 1 else 5 if attempt_count == 2 else 15 if attempt_count == 3 else 60
    return datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)


async def process_due_notification_jobs(db: AsyncSession, *, limit: int = 10) -> int:
    result = await db.execute(
        select(NotificationJob)
        .where(NotificationJob.status.in_(["pending", "failed"]))
        .where(or_(NotificationJob.next_attempt_at.is_(None), NotificationJob.next_attempt_at <= datetime.now(timezone.utc)))
        .order_by(NotificationJob.created_at.asc())
        .limit(limit)
    )
    jobs = result.scalars().all()
    for job in jobs:
        await attempt_notification_delivery(db, job)
    return len(jobs)
```

- [ ] **Step 5: Run queue service tests**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest tests.test_notification_service.NotificationQueueTests -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/email_service.py backend/services/notification_service.py backend/tests/test_notification_service.py
git commit -m "feat: add notification queue service"
```

---

### Task 3: Integrate Lead, Chat, And Funnel Notifications

**Files:**
- Modify: `backend/routers/leads.py`
- Modify: `backend/routers/chat.py`
- Modify: `backend/routers/funnels.py`
- Create: `backend/tests/test_leads_notifications.py`

- [ ] **Step 1: Write failing route tests**

```python
class LeadNotificationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_lead_enqueues_lead_notification(self):
        with patch("routers.leads.enqueue_notification", AsyncMock()) as enqueue_mock, patch(
            "routers.leads.process_due_notification_jobs",
            AsyncMock(return_value=1),
        ):
            await create_lead(payload, background_tasks, db)
        enqueue_mock.assert_awaited_once()

    async def test_capture_chat_lead_enqueues_chat_notification(self):
        with patch("routers.chat.enqueue_notification", AsyncMock()) as enqueue_mock:
            await capture_lead_from_chat(payload, db)
        enqueue_mock.assert_awaited_once()

    async def test_funnel_register_enqueues_registration_notification(self):
        with patch("routers.funnels.enqueue_notification", AsyncMock()) as enqueue_mock:
            await register_for_funnel("buyer-funnel", payload, db)
        enqueue_mock.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest tests.test_leads_notifications -v`

Expected: FAIL because routes do not enqueue notification jobs yet.

- [ ] **Step 3: Integrate queueing into the routes**

```python
job = await enqueue_notification(
    db,
    event_type="lead_captured",
    payload={
        "lead_id": lead.id,
        "name": data.name,
        "email": data.email,
        "phone": data.phone,
        "source": data.source,
        "lead_type": data.lead_type,
        "metadata": data.metadata_ or {},
    },
)
```

```python
await process_due_notification_jobs(db, limit=5)
```

Use the same pattern in:

- `create_lead(...)`
- `capture_lead_from_chat(...)`
- `register_for_funnel(...)`

- [ ] **Step 4: Run route tests**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest tests.test_leads_notifications -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/leads.py backend/routers/chat.py backend/routers/funnels.py backend/tests/test_leads_notifications.py
git commit -m "feat: queue notifications for leads and funnel registrations"
```

---

### Task 4: Integrate Booking Attempt And Booking Confirmation Notifications

**Files:**
- Modify: `backend/routers/booking.py`
- Modify: `backend/tests/test_booking_calendar.py`

- [ ] **Step 1: Write the failing booking notification tests**

```python
async def test_create_booking_enqueues_attempt_and_confirmation_notifications(self):
    with patch("routers.booking.enqueue_notification", AsyncMock()) as enqueue_mock:
        await create_booking(payload, db)

    self.assertEqual(enqueue_mock.await_count, 2)
    enqueue_mock.assert_any_await(event_type="booking_attempted", payload=ANY, db=db)
    enqueue_mock.assert_any_await(event_type="booking_confirmed", payload=ANY, db=db)
```

```python
async def test_create_booking_only_keeps_attempt_notification_when_confirmation_fails(self):
    with patch("routers.booking.enqueue_notification", AsyncMock()) as enqueue_mock, patch(
        "routers.booking.create_event",
        AsyncMock(side_effect=CalendarIntegrationError("calendar unavailable")),
    ):
        with self.assertRaises(HTTPException):
            await create_booking(payload, db)

    self.assertEqual(enqueue_mock.await_count, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest tests.test_booking_calendar -v`

Expected: FAIL because booking route only sends inline SMTP today.

- [ ] **Step 3: Integrate attempt + confirmed queue logic**

```python
await enqueue_notification(
    db,
    event_type="booking_attempted",
    payload={
        "name": data.name,
        "email": data.email,
        "phone": data.phone,
        "meeting_type": data.meeting_type,
        "context": data.context,
        "requested_at": data.scheduled_at.isoformat(),
        "location": data.location or "",
    },
)
```

Place the attempted notification after slot validation passes.

```python
await enqueue_notification(
    db,
    event_type="booking_confirmed",
    payload={
        "booking_id": booking.id,
        "name": data.name,
        "email": data.email,
        "phone": data.phone,
        "meeting_type": data.meeting_type,
        "context": data.context,
        "scheduled_at": slot_start.isoformat(),
        "location": data.location or "",
        "google_event_id": google_event_id,
    },
)
await process_due_notification_jobs(db, limit=5)
```

Delete the old direct `notify_new_booking(...)` call entirely.

- [ ] **Step 4: Run booking tests**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest tests.test_booking_calendar -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/booking.py backend/tests/test_booking_calendar.py
git commit -m "feat: queue booking attempt and confirmation notifications"
```

---

### Task 5: Integrate Seller Calculator Notifications

**Files:**
- Modify: `backend/routers/evaluator.py`
- Modify: `backend/tests/test_evaluator_router.py`

- [ ] **Step 1: Write failing evaluator notification tests**

```python
async def test_evaluate_enqueues_seller_calculator_notification(self):
    with patch("routers.evaluator.enqueue_notification", AsyncMock()) as enqueue_mock:
        await evaluate(payload, db)
    enqueue_mock.assert_awaited_once()

async def test_submit_rating_enqueues_rating_notification(self):
    with patch("routers.evaluator.enqueue_notification", AsyncMock()) as enqueue_mock:
        await submit_rating(calculation_id, rating_payload, db)
    enqueue_mock.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest tests.test_evaluator_router -v`

Expected: FAIL because evaluator route does not queue Brandon notifications yet.

- [ ] **Step 3: Queue calculator and rating jobs**

```python
await enqueue_notification(
    db,
    event_type="seller_evaluator_calculated",
    payload={
        "address": result["address"],
        "property_type": req.property_type,
        "bedrooms": req.bedrooms,
        "bathrooms": req.bathrooms,
        "sqft": req.sqft,
        "year_built": req.year_built,
        "condition": req.condition,
        "upgrades": req.upgrades or [],
        "price_low": result["price_low"],
        "price_high": result["price_high"],
        "confidence": result["confidence"],
        "name": req.name,
        "email": req.email,
        "phone": req.phone,
    },
)
```

```python
await enqueue_notification(
    db,
    event_type="seller_evaluator_rated",
    payload={
        "calculation_id": calculation_id,
        "rating": payload.rating,
    },
)
```

- [ ] **Step 4: Run evaluator tests**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest tests.test_evaluator_router -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/evaluator.py backend/tests/test_evaluator_router.py
git commit -m "feat: queue seller calculator notifications"
```

---

### Task 6: Integrate Investor Report And Investor Engagement Notifications

**Files:**
- Modify: `backend/routers/investor.py`
- Create: `backend/tests/test_investor_notifications.py`
- Modify: `frontend/src/components/investor/InvestorCalculator.tsx`

- [ ] **Step 1: Write failing investor tests**

```python
class InvestorNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_analysis_enqueues_report_requested_notification(self):
        with patch("routers.investor.enqueue_notification", AsyncMock()) as enqueue_mock:
            await full_analysis(payload, db)
        enqueue_mock.assert_awaited_once()

    async def test_track_engagement_enqueues_once_per_session_key(self):
        first = await track_engagement(engagement_payload, db)
        second = await track_engagement(engagement_payload, db)
        self.assertTrue(first["queued"])
        self.assertFalse(second["queued"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest tests.test_investor_notifications -v`

Expected: FAIL because investor notifications and engagement tracking do not exist yet.

- [ ] **Step 3: Add investor backend notification coverage**

```python
class InvestorEngagementRequest(BaseModel):
    session_key: str
    property_type: str = "single_family"
    purchase_price: float
    rehab_costs: float
    arv: float
    hold_months: int
```

```python
@router.post("/engagement")
async def track_engagement(req: InvestorEngagementRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(AnalyticsEvent).where(
            AnalyticsEvent.event_type == "investor_calculator_engaged",
            AnalyticsEvent.metadata_json.contains(req.session_key),
        )
    )
    if existing.scalar_one_or_none():
        return {"queued": False}

    event = AnalyticsEvent(
        event_type="investor_calculator_engaged",
        page="/invest",
        referrer=None,
        user_agent=None,
        device_type=None,
        metadata_json=json.dumps(req.model_dump()),
    )
    db.add(event)
    await db.flush()

    await enqueue_notification(
        db,
        event_type="investor_calculator_engaged",
        payload=req.model_dump(),
    )
    await process_due_notification_jobs(db, limit=5)
    return {"queued": True}
```

Also add `investor_report_requested` queueing inside `full_analysis(...)`.

- [ ] **Step 4: Add frontend one-time engagement ping**

```tsx
useEffect(() => {
  const sessionKey = sessionStorage.getItem('investor_engagement_key') ?? crypto.randomUUID()
  sessionStorage.setItem('investor_engagement_key', sessionKey)

  const hasChanged = JSON.stringify(inputs) !== JSON.stringify(DEFAULT_INPUTS)
  const hasSent = sessionStorage.getItem('investor_engagement_sent') === '1'
  if (!hasChanged || hasSent) return

  const timer = window.setTimeout(async () => {
    await apiPost('/api/v1/investor/engagement', {
      session_key: sessionKey,
      property_type: 'single_family',
      purchase_price: inputs.purchasePrice,
      rehab_costs: inputs.rehabCost,
      arv: inputs.arv,
      hold_months: inputs.holdMonths,
    }).catch(() => {})
    sessionStorage.setItem('investor_engagement_sent', '1')
  }, 1200)

  return () => window.clearTimeout(timer)
}, [inputs])
```

- [ ] **Step 5: Run investor tests**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest tests.test_investor_notifications -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/routers/investor.py backend/tests/test_investor_notifications.py frontend/src/components/investor/InvestorCalculator.tsx
git commit -m "feat: queue investor report and engagement notifications"
```

---

### Task 7: Opportunistic Retry Processing And Final Regression Sweep

**Files:**
- Modify: `backend/services/notification_service.py`
- Modify: `backend/routers/leads.py`
- Modify: `backend/routers/chat.py`
- Modify: `backend/routers/funnels.py`
- Modify: `backend/routers/booking.py`
- Modify: `backend/routers/evaluator.py`
- Modify: `backend/routers/investor.py`
- Test: `backend/tests/test_notification_service.py`

- [ ] **Step 1: Write the failing retry processing test**

```python
async def test_process_due_jobs_only_attempts_pending_or_failed_due_records(self):
    pending_due = NotificationJob(status="pending", next_attempt_at=None, ...)
    failed_due = NotificationJob(status="failed", next_attempt_at=datetime.now(timezone.utc), ...)
    delivered = NotificationJob(status="delivered", ...)

    processed = await process_due_notification_jobs(db, limit=10)

    self.assertEqual(processed, 2)
```

- [ ] **Step 2: Run test to verify it fails if selector logic is wrong**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest tests.test_notification_service.NotificationQueueRetryTests -v`

Expected: FAIL until due-job selection is correct.

- [ ] **Step 3: Process due jobs opportunistically after each enqueue-heavy route**

```python
await process_due_notification_jobs(db, limit=5)
```

Call this after queueing in:

- `create_lead(...)`
- `capture_lead_from_chat(...)`
- `register_for_funnel(...)`
- `create_booking(...)`
- `evaluate(...)`
- `submit_rating(...)`
- `full_analysis(...)`
- `track_engagement(...)`

- [ ] **Step 4: Run the full backend test suite**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/python -m unittest discover -s tests -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/notification_service.py backend/routers/*.py backend/tests/*.py
git commit -m "feat: retry due notification jobs across conversion routes"
```

---

### Task 8: Documentation, Deployment Verification, And Smoke Tests

**Files:**
- Modify: `tdtn.md`
- Modify: `memory.md`

- [ ] **Step 1: Update project logs**

```markdown
### 2026-04-10 — Brandon Notification Queue
- Added `notification_jobs`
- Added durable retry-until-delivered email notifications
- Covered leads, chat leads, funnels, booking attempts, booking confirmations, seller calculator use, seller rating, investor report requests, and investor calculator engagement
```

- [ ] **Step 2: Run migration and backend verification locally**

Run: `cd /Users/rishabnandi/brandon-real-estate/backend && ./.venv/bin/alembic upgrade head && ./.venv/bin/python -m unittest discover -s tests -v`

Expected: migration succeeds, tests all pass.

- [ ] **Step 3: Run frontend typecheck**

Run: `cd /Users/rishabnandi/brandon-real-estate/frontend && npm run typecheck`

Expected: PASS

- [ ] **Step 4: Production smoke checklist after deploy**

Run these flows manually:

- submit a standard lead form
- submit a funnel registration
- submit chatbot lead capture
- request a booking
- complete a booking
- run seller calculator
- submit seller calculator rating
- unlock investor report
- engage investor calculator before contact capture

Verify:

- notification jobs are created
- failed jobs retry instead of disappearing
- delivered jobs stop retrying
- Brandon receives one internal email per event type

- [ ] **Step 5: Commit**

```bash
git add tdtn.md memory.md
git commit -m "docs: record notification queue rollout"
```
