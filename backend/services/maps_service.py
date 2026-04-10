"""Google Maps Distance Matrix service for travel time calculations."""

import logging
from functools import lru_cache
from math import ceil

import httpx

from config import settings

logger = logging.getLogger(__name__)

_DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving"
_DEFAULT_TRAVEL_MINUTES = 30  # fallback when API is unavailable


@lru_cache(maxsize=256)
def _cached_key(origin: str, destination: str) -> str:
    """Create a hashable cache key."""
    return f"{origin}||{destination}"


# In-memory cache dict keyed by origin||destination
_travel_cache: dict[str, int] = {}
_geocode_cache: dict[str, tuple[str, str]] = {}


async def _geocode_address(address: str) -> tuple[str, str] | None:
    if address in _geocode_cache:
        return _geocode_cache[address]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _NOMINATIM_URL,
                params={"q": address, "format": "json", "limit": 1},
                headers={"User-Agent": "SoldWithSweeney/1.0"},
            )
            resp.raise_for_status()
            results = resp.json()
    except Exception:
        logger.exception("OSM geocoding error for %s", address)
        return None

    if not results:
        return None

    coords = (results[0]["lat"], results[0]["lon"])
    _geocode_cache[address] = coords
    return coords


async def _get_osrm_travel_time(origin: str, destination: str) -> int | None:
    origin_coords = await _geocode_address(origin)
    destination_coords = await _geocode_address(destination)
    if not origin_coords or not destination_coords:
        return None

    origin_lat, origin_lon = origin_coords
    destination_lat, destination_lon = destination_coords

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_OSRM_ROUTE_URL}/{origin_lon},{origin_lat};{destination_lon},{destination_lat}",
                params={"overview": "false"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("OSRM routing error for %s → %s", origin, destination)
        return None

    routes = data.get("routes") or []
    if not routes:
        return None

    minutes = ceil(routes[0]["duration"] / 60)
    logger.info("OSRM travel time %s → %s: %d min", origin, destination, minutes)
    return minutes


async def get_travel_time(origin: str, destination: str) -> int:
    """Return estimated driving time in minutes between two addresses.

    Uses the Google Maps Distance Matrix API. Results are cached in-memory
    to avoid redundant API calls for the same origin/destination pairs.

    Args:
        origin: Street address or place name of the starting point.
        destination: Street address or place name of the ending point.

    Returns:
        Estimated travel time in minutes (int). Falls back to
        _DEFAULT_TRAVEL_MINUTES if the API is unavailable.
    """
    if not origin or not destination:
        return _DEFAULT_TRAVEL_MINUTES

    cache_key = f"{origin}||{destination}"
    if cache_key in _travel_cache:
        return _travel_cache[cache_key]

    api_key = settings.GOOGLE_MAPS_API_KEY
    if not api_key:
        fallback = await _get_osrm_travel_time(origin, destination)
        if fallback is not None:
            _travel_cache[cache_key] = fallback
            return fallback

        logger.warning(
            "GOOGLE_MAPS_API_KEY not set and OSRM fallback unavailable — using default %d min",
            _DEFAULT_TRAVEL_MINUTES,
        )
        return _DEFAULT_TRAVEL_MINUTES

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _DISTANCE_MATRIX_URL,
                params={
                    "origins": origin,
                    "destinations": destination,
                    "mode": "driving",
                    "key": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        element = data["rows"][0]["elements"][0]
        if element["status"] != "OK":
            logger.warning("Distance Matrix status %s for %s → %s", element["status"], origin, destination)
            return _DEFAULT_TRAVEL_MINUTES

        minutes = element["duration"]["value"] // 60  # seconds → minutes
        _travel_cache[cache_key] = minutes
        logger.info("Travel time %s → %s: %d min", origin, destination, minutes)
        return minutes

    except Exception:
        logger.exception("Distance Matrix API error for %s → %s", origin, destination)
        fallback = await _get_osrm_travel_time(origin, destination)
        if fallback is not None:
            _travel_cache[cache_key] = fallback
            return fallback
        return _DEFAULT_TRAVEL_MINUTES
