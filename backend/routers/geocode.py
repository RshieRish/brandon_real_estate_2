"""Geocode / address autocomplete router."""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter()

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_HEADERS = {"User-Agent": "SoldWithSweeney/1.0 (brandon@soldwithsweeney.com)"}

# In-memory cache for autocomplete results (query → suggestions)
_autocomplete_cache: dict[str, list[dict]] = {}


@router.get("/autocomplete")
async def address_autocomplete(
    q: str = Query(..., min_length=3, description="Partial address to autocomplete"),
    limit: int = Query(5, ge=1, le=10),
    country: Optional[str] = Query("us", description="ISO country code filter"),
) -> list[dict]:
    """
    Return address suggestions matching the partial query.

    Uses Nominatim (OpenStreetMap) geocoding — free, no API key required.
    Results are cached in-memory to reduce external calls.
    """
    cache_key = f"{q.strip().lower()}|{limit}|{country}"
    if cache_key in _autocomplete_cache:
        return _autocomplete_cache[cache_key]

    params: dict = {
        "q": q,
        "format": "json",
        "addressdetails": 1,
        "limit": limit,
        "dedupe": 1,
    }
    if country:
        params["countrycodes"] = country

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                _NOMINATIM_URL,
                params=params,
                headers=_NOMINATIM_HEADERS,
            )
            resp.raise_for_status()
            raw = resp.json()
    except Exception:
        logger.exception("Nominatim autocomplete error for q=%s", q)
        return []

    suggestions = []
    for item in raw:
        addr = item.get("address", {})

        # Build a clean formatted address
        parts = []
        house_number = addr.get("house_number", "")
        road = addr.get("road", "")
        if house_number and road:
            parts.append(f"{house_number} {road}")
        elif road:
            parts.append(road)
        elif item.get("display_name"):
            # Fallback: use the first part of display_name
            parts.append(item["display_name"].split(",")[0].strip())

        city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet") or ""
        state = addr.get("state", "")
        postcode = addr.get("postcode", "")

        if city:
            parts.append(city)
        if state:
            # Abbreviate common state names
            state_abbr = _abbreviate_state(state)
            parts.append(state_abbr)
        if postcode:
            parts.append(postcode)

        formatted = ", ".join(parts)
        if not formatted:
            formatted = item.get("display_name", "")

        suggestions.append({
            "formatted_address": formatted,
            "display_name": item.get("display_name", ""),
            "lat": float(item.get("lat", 0)),
            "lng": float(item.get("lon", 0)),
            "type": item.get("type", ""),
            "address_components": {
                "house_number": house_number,
                "road": road,
                "city": city,
                "state": state,
                "postcode": postcode,
                "county": addr.get("county", ""),
            },
        })

    _autocomplete_cache[cache_key] = suggestions
    return suggestions


# ─── State abbreviation helper ──────────────────────────────────────────────

_STATE_MAP = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
}


def _abbreviate_state(state: str) -> str:
    """Convert full state name to 2-letter abbreviation."""
    return _STATE_MAP.get(state, state)
