"""
Zapier Catch Hook integration.

When a lead is created, this service fires a background POST to the existing
Zapier webhook. The downstream destination is a legacy CRM workflow managed
outside this application; this module does not claim a brokerage CRM API.

Env var required:
    ZAPIER_WEBHOOK_URL  — the "Catch Hook" URL from your Zap trigger step.
                          Leave blank / unset to disable silently.
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

ZAPIER_WEBHOOK_URL = os.getenv("ZAPIER_WEBHOOK_URL", "")


async def push_lead_to_zapier(
    *,
    name: str,
    email: str,
    phone: str | None,
    source: str | None,
    lead_type: str | None,
    notes: str = "",
) -> None:
    """
    Fire-and-forget: POST lead data to the Zapier Catch Hook.
    Failures are logged but never surfaced to the caller — we never want
    a Zapier outage to block lead capture.
    """
    if not ZAPIER_WEBHOOK_URL:
        logger.debug("ZAPIER_WEBHOOK_URL not set — skipping Zapier push")
        return

    # Preserve the legacy webhook's separate first/last-name contract.
    parts = name.strip().split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""

    # Map lead_type to the webhook's human-readable source tag.
    source_tag_map = {
        "buyer": "Website – Buyer",
        "seller": "Website – Seller",
        "investor": "Website – Investor",
    }
    crm_source = source_tag_map.get(lead_type or "", "Website – General")

    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone or "",
        "lead_source": crm_source,
        "lead_type": lead_type or "general",
        "source_page": source or "website",
        "tags": "soldwithsweeney-website",
        "notes": notes or "",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(ZAPIER_WEBHOOK_URL, json=payload)
            resp.raise_for_status()
            logger.info("Zapier push OK — lead: %s (%s)", email, lead_type)
    except httpx.HTTPStatusError as exc:
        logger.error("Zapier HTTP error %s for lead %s: %s", exc.response.status_code, email, exc)
    except Exception as exc:
        logger.error("Zapier push failed for lead %s: %s", email, exc)
