"""Email notification service — internal notifications to Brandon.

Uses aiosmtplib to send async emails via Gmail SMTP.
This service is for INTERNAL NOTIFICATIONS ONLY:
- New lead submissions
- New meeting bookings
- New funnel registrations

Client-facing emails stay inside KW CRM workflows.
"""

import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

from config import settings

logger = logging.getLogger(__name__)

BRANDON_EMAIL = "brandon@soldwithsweeney.com"


async def _send_email(subject: str, body_html: str, to: str = BRANDON_EMAIL) -> bool:
    """Send an email via SMTP. Returns True on success."""
    if not settings.SMTP_HOST or not settings.SMTP_USER:
        logger.warning("SMTP not configured — skipping email: %s", subject)
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"SWS Platform <{settings.SMTP_USER}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            start_tls=True,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASS,
        )
        logger.info("Email sent: %s → %s", subject, to)
        return True
    except Exception:
        logger.exception("Failed to send email: %s", subject)
        return False


async def notify_new_lead(
    name: str, email: str, phone: str, lead_type: str, source: str
) -> bool:
    """Notify Brandon of a new lead submission."""
    subject = f"🏠 New {lead_type.title()} Lead: {name}"
    body = f"""
    <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 500px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
        <h2 style="color: #eac469; margin-top: 0;">New Lead Received</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <tr><td style="color: #818285; padding: 8px 0;">Name</td><td style="color: #fff; padding: 8px 0; font-weight: 600;">{name}</td></tr>
            <tr><td style="color: #818285; padding: 8px 0;">Email</td><td style="color: #fff; padding: 8px 0;"><a href="mailto:{email}" style="color: #eac469;">{email}</a></td></tr>
            <tr><td style="color: #818285; padding: 8px 0;">Phone</td><td style="color: #fff; padding: 8px 0;">{phone or 'Not provided'}</td></tr>
            <tr><td style="color: #818285; padding: 8px 0;">Type</td><td style="color: #fff; padding: 8px 0;">{lead_type.title()}</td></tr>
            <tr><td style="color: #818285; padding: 8px 0;">Source</td><td style="color: #fff; padding: 8px 0;">{source}</td></tr>
        </table>
        <hr style="border: none; border-top: 1px solid #1a1a1a; margin: 16px 0;">
        <p style="color: #818285; font-size: 12px;">Sold With Sweeney &amp; Co. — AI Platform Notification</p>
    </div>
    """
    return await _send_email(subject, body)


async def notify_new_booking(
    name: str, email: str, phone: str, meeting_type: str,
    scheduled_at: str, location: str = "", context: str = ""
) -> bool:
    """Notify Brandon of a new meeting booking."""
    subject = f"📅 New Booking: {name} — {meeting_type.replace('_', ' ').title()}"
    body = f"""
    <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 500px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
        <h2 style="color: #eac469; margin-top: 0;">New Meeting Booked</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <tr><td style="color: #818285; padding: 8px 0;">Client</td><td style="color: #fff; padding: 8px 0; font-weight: 600;">{name}</td></tr>
            <tr><td style="color: #818285; padding: 8px 0;">Email</td><td style="color: #fff; padding: 8px 0;"><a href="mailto:{email}" style="color: #eac469;">{email}</a></td></tr>
            <tr><td style="color: #818285; padding: 8px 0;">Phone</td><td style="color: #fff; padding: 8px 0;">{phone or 'Not provided'}</td></tr>
            <tr><td style="color: #818285; padding: 8px 0;">Type</td><td style="color: #fff; padding: 8px 0;">{meeting_type.replace('_', ' ').title()}</td></tr>
            <tr><td style="color: #818285; padding: 8px 0;">When</td><td style="color: #fff; padding: 8px 0; font-weight: 600;">{scheduled_at}</td></tr>
            {f'<tr><td style="color: #818285; padding: 8px 0;">Location</td><td style="color: #fff; padding: 8px 0;">{location}</td></tr>' if location else ''}
            {f'<tr><td style="color: #818285; padding: 8px 0;">Context</td><td style="color: #fff; padding: 8px 0;">{context}</td></tr>' if context else ''}
        </table>
        <hr style="border: none; border-top: 1px solid #1a1a1a; margin: 16px 0;">
        <p style="color: #818285; font-size: 12px;">Sold With Sweeney &amp; Co. — AI Platform Notification</p>
    </div>
    """
    return await _send_email(subject, body)


async def notify_funnel_registration(
    name: str, email: str, phone: str, funnel_title: str
) -> bool:
    """Notify Brandon of a new funnel registration."""
    subject = f"🎯 New Funnel Signup: {name} — {funnel_title}"
    body = f"""
    <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 500px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
        <h2 style="color: #eac469; margin-top: 0;">New Funnel Registration</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <tr><td style="color: #818285; padding: 8px 0;">Name</td><td style="color: #fff; padding: 8px 0; font-weight: 600;">{name}</td></tr>
            <tr><td style="color: #818285; padding: 8px 0;">Email</td><td style="color: #fff; padding: 8px 0;"><a href="mailto:{email}" style="color: #eac469;">{email}</a></td></tr>
            <tr><td style="color: #818285; padding: 8px 0;">Phone</td><td style="color: #fff; padding: 8px 0;">{phone or 'Not provided'}</td></tr>
            <tr><td style="color: #818285; padding: 8px 0;">Funnel</td><td style="color: #fff; padding: 8px 0;">{funnel_title}</td></tr>
        </table>
        <hr style="border: none; border-top: 1px solid #1a1a1a; margin: 16px 0;">
        <p style="color: #818285; font-size: 12px;">Sold With Sweeney &amp; Co. — AI Platform Notification</p>
    </div>
    """
    return await _send_email(subject, body)


async def send_test_email() -> bool:
    """Send a test email to verify SMTP configuration."""
    subject = "✅ SWS Platform — SMTP Test Successful"
    body = """
    <div style="font-family: 'Montserrat', Arial, sans-serif; max-width: 500px; margin: 0 auto; background: #0a0a0a; color: #fff; padding: 24px; border-radius: 12px;">
        <h2 style="color: #eac469; margin-top: 0;">SMTP Configuration Verified</h2>
        <p style="color: #fff;">Your email notification system is working correctly.</p>
        <p style="color: #818285;">You will receive notifications for:</p>
        <ul style="color: #fff; padding-left: 20px;">
            <li>New lead submissions</li>
            <li>New meeting bookings</li>
            <li>New funnel registrations</li>
        </ul>
        <hr style="border: none; border-top: 1px solid #1a1a1a; margin: 16px 0;">
        <p style="color: #818285; font-size: 12px;">Sold With Sweeney &amp; Co. — AI Platform Notification</p>
    </div>
    """
    return await _send_email(subject, body)
