"""
RentCast API service — property records, value estimates, and rent estimates.

Uses an in-memory TTL cache (24 hours) so repeated lookups for the same
address don't burn API credits.  The free tier allows 50 calls/month at
$0.20 each overage, so every cache hit is literally saving money.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

# ─── In-Memory TTL Cache ────────────────────────────────────────────────────
_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours
_cache: dict[str, tuple[float, Any]] = {}


def _cache_key(endpoint: str, address: str) -> str:
    return f"{endpoint}::{address.strip().lower()}"


def _get_cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, data = entry
    if time.time() - ts > _CACHE_TTL_SECONDS:
        del _cache[key]
        return None
    return data


def _set_cached(key: str, data: Any) -> None:
    _cache[key] = (time.time(), data)


# ─── RentCast HTTP Helpers ──────────────────────────────────────────────────
_BASE = "https://api.rentcast.io/v1"


async def _rentcast_get(path: str, params: dict) -> dict | list | None:
    """Issue a GET request to the RentCast API with the configured key."""
    api_key = settings.RENTCAST_API_KEY
    if not api_key:
        logger.warning("RENTCAST_API_KEY is not configured — skipping lookup.")
        return None

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                f"{_BASE}{path}",
                params=params,
                headers={"X-Api-Key": api_key, "Accept": "application/json"},
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                logger.info("RentCast 404 for %s %s — address not found.", path, params)
                return None
            if resp.status_code == 429:
                logger.warning("RentCast rate limit reached (429).")
                return None
            logger.warning("RentCast %s returned status %d: %s", path, resp.status_code, resp.text[:200])
            return None
    except httpx.HTTPError as exc:
        logger.error("RentCast HTTP error for %s: %s", path, exc)
        return None


# ─── Public API ─────────────────────────────────────────────────────────────


async def get_property_record(address: str) -> dict | None:
    """Fetch property record data (beds, baths, sqft, tax history, etc.)."""
    key = _cache_key("property", address)
    cached = _get_cached(key)
    if cached is not None:
        logger.info("RentCast property cache HIT for %s", address)
        return cached

    result = await _rentcast_get("/properties", {"address": address, "limit": "1"})
    if result and isinstance(result, list) and len(result) > 0:
        data = result[0]
        _set_cached(key, data)
        return data
    return None


async def get_value_estimate(address: str) -> dict | None:
    """Fetch AVM value estimate + comparable sale listings."""
    key = _cache_key("value", address)
    cached = _get_cached(key)
    if cached is not None:
        logger.info("RentCast value cache HIT for %s", address)
        return cached

    result = await _rentcast_get("/avm/value", {"address": address})
    if result and isinstance(result, dict) and "price" in result:
        _set_cached(key, result)
        return result
    return None


async def get_rent_estimate(address: str) -> dict | None:
    """Fetch long-term rent estimate + comparable rental listings."""
    key = _cache_key("rent", address)
    cached = _get_cached(key)
    if cached is not None:
        logger.info("RentCast rent cache HIT for %s", address)
        return cached

    result = await _rentcast_get("/avm/rent/long-term", {"address": address})
    if result and isinstance(result, dict) and "rent" in result:
        _set_cached(key, result)
        return result
    return None


async def get_full_property_data(address: str) -> dict:
    """
    Orchestrates all three lookups and returns a combined result.

    Returns a dict with keys:
      - property_record: dict | None
      - value_estimate: dict | None
      - rent_estimate: dict | None
      - data_source: "rentcast" | "none"
    """
    prop = await get_property_record(address)
    value = await get_value_estimate(address)
    rent = await get_rent_estimate(address)

    has_data = any([prop, value, rent])

    return {
        "property_record": prop,
        "value_estimate": value,
        "rent_estimate": rent,
        "data_source": "rentcast" if has_data else "none",
    }
