import httpx


MARKET_BASE_PPSF = {
    "MA": {
        "single_family": 290,
        "multi_family": 235,
        "condo": 280,
        "townhouse": 275,
    },
    "NH": {
        "single_family": 265,
        "multi_family": 210,
        "condo": 250,
        "townhouse": 245,
    },
    "DEFAULT": {
        "single_family": 280,
        "multi_family": 220,
        "condo": 260,
        "townhouse": 255,
    },
}

CITY_PPSF_ADJUSTMENTS = {
    "andover": 105,
    "north andover": 95,
    "westford": 90,
    "chelmsford": 45,
    "tewksbury": 30,
    "dracut": 25,
    "lowell": 15,
    "nashua": 20,
    "windham": 55,
    "salem": 30,
    "hudson": 15,
    "manchester": 5,
}

DEFAULT_SQFT = {
    "single_family": 1800,
    "multi_family": 2600,
    "condo": 1200,
    "townhouse": 1500,
}

BASELINE_BEDROOMS = {
    "single_family": 3,
    "multi_family": 4,
    "condo": 2,
    "townhouse": 3,
}

BASELINE_BATHROOMS = {
    "single_family": 2.0,
    "multi_family": 2.0,
    "condo": 2.0,
    "townhouse": 2.5,
}

CONDITION_MULTIPLIERS = {
    "excellent": 1.08,
    "good": 1.0,
    "fair": 0.92,
    "needs_work": 0.82,
}

UPGRADE_VALUES = {
    "Kitchen remodel": 24000,
    "Bathrooms": 16000,
    "Roof": 12000,
    "HVAC": 9000,
    "Windows": 10000,
    "Flooring": 7000,
    "Addition": 30000,
}

PROPERTY_LABELS = {
    "single_family": "single-family home",
    "multi_family": "multi-family property",
    "condo": "condo",
    "townhouse": "townhouse",
}


async def geocode_address(address: str) -> dict:
    """Basic geocode using Nominatim (free)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "SoldWithSweeney/1.0"}
        )
        results = resp.json()
        if results:
            return {"lat": results[0]["lat"], "lon": results[0]["lon"], "display": results[0]["display_name"]}
    return {}


def _normalize_state(address: str) -> str:
    address_lower = address.lower()
    if ", ma" in address_lower or " massachusetts" in address_lower:
        return "MA"
    if ", nh" in address_lower or " new hampshire" in address_lower:
        return "NH"
    return "DEFAULT"


def _extract_city(address: str) -> str:
    parts = [part.strip().lower() for part in address.split(",") if part.strip()]
    if len(parts) >= 3:
        return parts[-2]
    if len(parts) == 2:
        return parts[-1]
    return ""


def _year_adjustment(year_built: int | None) -> int:
    if not year_built:
        return 0
    if year_built >= 2015:
        return 30000
    if year_built >= 2000:
        return 18000
    if year_built >= 1980:
        return 8000
    if year_built >= 1950:
        return -5000
    return -18000


def _confidence_level(data: dict, state: str, has_geocode: bool) -> str:
    completeness_points = 0
    if data.get("sqft"):
        completeness_points += 1
    if data.get("year_built"):
        completeness_points += 1
    if data.get("address"):
        completeness_points += 1
    if has_geocode:
        completeness_points += 1
    if state != "DEFAULT":
        completeness_points += 1

    if completeness_points >= 5:
        return "High"
    if completeness_points >= 3:
        return "Medium"
    return "Low"


def calculate_property_estimate(data: dict, geo: dict | None = None) -> dict:
    address = (geo or {}).get("display") or data.get("address") or ""
    state = _normalize_state(address)
    city = _extract_city(address)
    property_type = data.get("property_type") or "single_family"
    sqft = int(data.get("sqft") or DEFAULT_SQFT.get(property_type, 1600))
    bedrooms = int(data.get("bedrooms") or BASELINE_BEDROOMS.get(property_type, 3))
    bathrooms = float(data.get("bathrooms") or BASELINE_BATHROOMS.get(property_type, 2.0))
    condition = data.get("condition") or "good"
    upgrades = data.get("upgrades") or []
    year_built = data.get("year_built")

    state_profile = MARKET_BASE_PPSF.get(state, MARKET_BASE_PPSF["DEFAULT"])
    base_ppsf = state_profile.get(property_type, MARKET_BASE_PPSF["DEFAULT"]["single_family"])
    locality_adjustment = CITY_PPSF_ADJUSTMENTS.get(city, 0)
    effective_ppsf = base_ppsf + locality_adjustment

    base_value = sqft * effective_ppsf
    condition_multiplier = CONDITION_MULTIPLIERS.get(condition, 1.0)
    bedroom_adjustment = (bedrooms - BASELINE_BEDROOMS.get(property_type, 3)) * 12000
    bathroom_adjustment = (bathrooms - BASELINE_BATHROOMS.get(property_type, 2.0)) * 15000
    upgrade_adjustment = sum(UPGRADE_VALUES.get(upgrade, 0) for upgrade in upgrades)
    year_adjustment = _year_adjustment(year_built if isinstance(year_built, int) else None)

    midpoint = (
        (base_value * condition_multiplier)
        + bedroom_adjustment
        + bathroom_adjustment
        + upgrade_adjustment
        + year_adjustment
    )
    midpoint = max(midpoint, 50000)

    confidence = _confidence_level(data, state, bool(geo))
    margin = {"High": 0.05, "Medium": 0.08, "Low": 0.12}[confidence]
    range_low = round(midpoint * (1 - margin), -3)
    range_high = round(midpoint * (1 + margin), -3)

    factors = [
        f"Baseline pricing for a {PROPERTY_LABELS.get(property_type, 'home')} in {state} starts around ${effective_ppsf}/sq ft.",
        f"{condition.replace('_', ' ').title()} condition {'boosts' if condition_multiplier >= 1 else 'softens'} the estimate versus a market-average home.",
        f"{bedrooms} bedrooms and {bathrooms:g} bathrooms shift value against the local baseline for this property type.",
    ]

    if upgrades:
        factors.append(
            f"Recent upgrades add value, led by {', '.join(upgrades[:3])}."
        )
    else:
        factors.append("No major recent upgrade value was added to this estimate.")

    if year_built:
        factors.append(f"Year built ({year_built}) affects buyer demand and deferred-maintenance risk.")

    explanation = (
        f"This range uses a CMA-style pricing model built from local $/sq-ft baselines, "
        f"then adjusts for condition, bed/bath count, age, and upgrades. "
        f"It is most reliable as an initial listing conversation, not a formal appraisal."
    )

    return {
        "range_low": int(range_low),
        "range_high": int(max(range_high, range_low + 10000)),
        "confidence": confidence,
        "explanation": explanation,
        "key_factors": factors[:4],
    }


async def evaluate_property(data: dict, geo: dict | None = None) -> dict:
    return calculate_property_estimate(data, geo=geo)
