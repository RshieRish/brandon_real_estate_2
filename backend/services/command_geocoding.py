"""Server-side geocoding for internal listing map placement."""
import httpx

from config import settings

_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def extract_coordinates(data: dict) -> tuple[str, str]:
    results = data.get("results") or []
    if data.get("status") != "OK" or not results:
        raise ValueError("Address not found by geocoding service")
    location = results[0].get("geometry", {}).get("location", {})
    if "lat" not in location or "lng" not in location:
        raise ValueError("Geocoding response did not include coordinates")
    return str(location["lat"]), str(location["lng"])


async def geocode_listing_address(address: str) -> tuple[str, str]:
    if not settings.GOOGLE_MAPS_API_KEY:
        raise RuntimeError("Listing geocoding is not configured")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(_GEOCODE_URL, params={"address": address, "key": settings.GOOGLE_MAPS_API_KEY})
        response.raise_for_status()
    return extract_coordinates(response.json())
