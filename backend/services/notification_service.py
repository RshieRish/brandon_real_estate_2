import html
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models.notification_job import NotificationJob
from services.email_service import BRANDON_EMAIL, send_internal_email

logger = logging.getLogger(__name__)
NOTIFICATION_RETRY_INTERVAL_SECONDS = 60


def _titleize(value: str | None) -> str:
    return (value or "").replace("_", " ").strip().title() or "General"


def _humanize_key(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _render_table(payload: dict) -> str:
    return "".join(
        f"<tr><td style=\"color: #818285; padding: 8px 0; vertical-align: top;\">{html.escape(_humanize_key(key))}</td><td style=\"padding: 8px 0;\">{html.escape(str(value if value not in (None, '') else 'Not provided'))}</td></tr>"
        for key, value in payload.items()
    )


def render_notification_email(
    event_type: str,
    payload: dict,
    *,
    subject_override: str | None = None,
) -> tuple[str, str]:
    if event_type == "lead_captured":
        lead_type = _titleize(payload.get("lead_type")) if payload.get("lead_type") else "Lead"
        subject = subject_override or f"New Lead Captured — {lead_type}"
        name = html.escape(str(payload.get("name") or "Not provided"))
        email = html.escape(str(payload.get("email") or "Not provided"))
        phone = html.escape(str(payload.get("phone") or "Not provided"))
        source = html.escape(str(payload.get("source") or "website"))
        lead_type_value = html.escape(lead_type)
        body = f"""
        <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
            <h2 style="color: #eac469; margin-top: 0;">New Lead Captured</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="color: #818285; padding: 8px 0;">Name</td><td style="padding: 8px 0;">{name}</td></tr>
                <tr><td style="color: #818285; padding: 8px 0;">Email</td><td style="padding: 8px 0;">{email}</td></tr>
                <tr><td style="color: #818285; padding: 8px 0;">Phone</td><td style="padding: 8px 0;">{phone}</td></tr>
                <tr><td style="color: #818285; padding: 8px 0;">Source</td><td style="padding: 8px 0;">{source}</td></tr>
                <tr><td style="color: #818285; padding: 8px 0;">Type</td><td style="padding: 8px 0;">{lead_type_value}</td></tr>
            </table>
        </div>
        """
        return subject, body

    if event_type == "chat_lead_captured":
        lead_type = _titleize(payload.get("lead_type")) if payload.get("lead_type") else "General"
        subject = subject_override or f"New Chat Lead — {lead_type}"
        body = f"""
        <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
            <h2 style="color: #eac469; margin-top: 0;">New Chat Lead</h2>
            <table style="width: 100%; border-collapse: collapse;">{_render_table(payload)}</table>
        </div>
        """
        return subject, body

    if event_type == "funnel_registration":
        subject = subject_override or f"New Funnel Registration — {payload.get('funnel_title') or 'Funnel'}"
        body = f"""
        <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
            <h2 style="color: #eac469; margin-top: 0;">New Funnel Registration</h2>
            <table style="width: 100%; border-collapse: collapse;">{_render_table(payload)}</table>
        </div>
        """
        return subject, body

    if event_type == "booking_attempted":
        subject = subject_override or f"Booking Attempted — {_titleize(payload.get('meeting_type'))}"
        body = f"""
        <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
            <h2 style="color: #eac469; margin-top: 0;">Booking Attempted</h2>
            <table style="width: 100%; border-collapse: collapse;">{_render_table(payload)}</table>
        </div>
        """
        return subject, body

    if event_type == "booking_confirmed":
        subject = subject_override or f"Booking Confirmed — {_titleize(payload.get('meeting_type'))}"
        body = f"""
        <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
            <h2 style="color: #eac469; margin-top: 0;">Booking Confirmed</h2>
            <table style="width: 100%; border-collapse: collapse;">{_render_table(payload)}</table>
        </div>
        """
        return subject, body

    if event_type == "seller_evaluator_calculated":
        subject = subject_override or "Seller Calculator Used"
        body = f"""
        <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
            <h2 style="color: #eac469; margin-top: 0;">Seller Calculator Used</h2>
            <table style="width: 100%; border-collapse: collapse;">{_render_table(payload)}</table>
        </div>
        """
        return subject, body

    if event_type == "seller_evaluator_rated":
        subject = subject_override or "Seller Calculator Rating Received"
        body = f"""
        <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
            <h2 style="color: #eac469; margin-top: 0;">Seller Calculator Rating Received</h2>
            <table style="width: 100%; border-collapse: collapse;">{_render_table(payload)}</table>
        </div>
        """
        return subject, body

    if event_type == "investor_report_requested":
        subject = subject_override or "Investor Report Requested"
        body = f"""
        <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
            <h2 style="color: #eac469; margin-top: 0;">Investor Report Requested</h2>
            <table style="width: 100%; border-collapse: collapse;">{_render_table(payload)}</table>
        </div>
        """
        return subject, body

    if event_type == "investor_calculator_engaged":
        subject = subject_override or "Investor Calculator Engaged"
        body = f"""
        <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
            <h2 style="color: #eac469; margin-top: 0;">Investor Calculator Engaged</h2>
            <table style="width: 100%; border-collapse: collapse;">{_render_table(payload)}</table>
        </div>
        """
        return subject, body

    subject = subject_override or f"Internal Notification — {_titleize(event_type)}"
    body = f"""
    <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
        <h2 style="color: #eac469; margin-top: 0;">{_titleize(event_type)}</h2>
        <table style="width: 100%; border-collapse: collapse;">{_render_table(payload)}</table>
    </div>
    """
    return subject, body


def calculate_next_attempt_at(attempt_count: int) -> datetime:
    if attempt_count <= 1:
        delay_minutes = 1
    elif attempt_count == 2:
        delay_minutes = 5
    elif attempt_count == 3:
        delay_minutes = 15
    else:
        delay_minutes = 60
    return datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)


async def enqueue_notification(
    db: AsyncSession,
    *,
    event_type: str,
    payload: dict,
) -> NotificationJob:
    subject, _ = render_notification_email(event_type, payload)
    job = NotificationJob(
        event_type=event_type,
        status="pending",
        recipient=BRANDON_EMAIL,
        subject=subject,
        payload_json=json.dumps(payload),
    )
    db.add(job)
    await db.flush()
    return job


async def attempt_notification_delivery(db: AsyncSession, job: NotificationJob) -> None:
    payload = json.loads(job.payload_json or "{}")
    _, body_html = render_notification_email(
        job.event_type,
        payload,
        subject_override=job.subject,
    )
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


async def process_due_notification_jobs(db: AsyncSession, *, limit: int = 10) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(NotificationJob)
        .where(NotificationJob.status.in_(["pending", "failed"]))
        .where(
            or_(
                NotificationJob.next_attempt_at.is_(None),
                NotificationJob.next_attempt_at <= now,
            )
        )
        .order_by(NotificationJob.created_at.asc())
        .limit(limit)
    )
    jobs = result.scalars().all()
    for job in jobs:
        await attempt_notification_delivery(db, job)
    return len(jobs)


async def enqueue_notification_in_new_session(
    *,
    event_type: str,
    payload: dict,
    process_now: bool = True,
) -> None:
    async with AsyncSessionLocal() as db:
        await enqueue_notification(db, event_type=event_type, payload=payload)
        await db.commit()
    if process_now:
        await run_notification_retry_pass(limit=5)


async def run_notification_retry_pass(*, limit: int = 20) -> int:
    async with AsyncSessionLocal() as db:
        try:
            processed = await process_due_notification_jobs(db, limit=limit)
            await db.commit()
            return processed
        except Exception:
            await db.rollback()
            logger.exception("Notification retry pass failed")
            return 0
