"""
Property image service — generates property thumbnail URLs.

Uses Google Street View Static API when GOOGLE_MAPS_API_KEY is available,
otherwise falls back to OpenStreetMap static map tiles (free, no key needed).
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

import httpx

from config import settings

logger = logging.getLogger(__name__)

_STREETVIEW_METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
_STREETVIEW_URL = "https://maps.googleapis.com/maps/api/streetview"

# ─── In-memory cache for Street View availability ──────────────────────────
_streetview_available_cache: dict[str, bool] = {}


async def _check_streetview_available(address: str) -> bool:
    """Check if Google Street View has imagery for this address."""
    key = settings.GOOGLE_MAPS_API_KEY
    if not key:
        return False

    cache_key = address.strip().lower()
    if cache_key in _streetview_available_cache:
        return _streetview_available_cache[cache_key]

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                _STREETVIEW_METADATA_URL,
                params={"location": address, "key": key},
            )
            data = resp.json()
            available = data.get("status") == "OK"
            _streetview_available_cache[cache_key] = available
            return available
    except Exception:
        return False


def get_streetview_url(address: str, width: int = 600, height: int = 400) -> str | None:
    """Build a Google Street View Static API URL (requires GOOGLE_MAPS_API_KEY)."""
    key = settings.GOOGLE_MAPS_API_KEY
    if not key:
        return None
    encoded = quote_plus(address)
    return f"{_STREETVIEW_URL}?size={width}x{height}&location={encoded}&key={key}&source=outdoor"


def get_map_thumbnail_url(
    lat: float,
    lng: float,
    zoom: int = 17,
    width: int = 600,
    height: int = 400,
) -> str:
    """
    Build a static map thumbnail URL using free OpenStreetMap tiles.
    This generates a URL for a static tile image centered on the property.
    """
    # Use the free OSM static map service
    return (
        f"https://staticmap.openstreetmap.de/staticmap.php"
        f"?center={lat},{lng}&zoom={zoom}&size={width}x{height}"
        f"&markers={lat},{lng},red-pushpin"
        f"&maptype=mapnik"
    )


async def get_property_image_url(
    address: str,
    lat: float | None = None,
    lng: float | None = None,
) -> dict:
    """
    Get the best available property image URL.

    Returns:
        {
            "image_url": "...",
            "image_type": "streetview" | "map" | "none"
        }
    """
    # Try Google Street View first
    key = settings.GOOGLE_MAPS_API_KEY
    if key:
        available = await _check_streetview_available(address)
        if available:
            url = get_streetview_url(address)
            if url:
                return {"image_url": url, "image_type": "streetview"}

    # Fallback to OpenStreetMap static map tile
    if lat is not None and lng is not None:
        url = get_map_thumbnail_url(lat, lng)
        return {"image_url": url, "image_type": "map"}

    return {"image_url": None, "image_type": "none"}
