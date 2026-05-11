"""Rental analyzer — combines RentCast's rent AVM with a condition/upgrade
heuristic to estimate monthly rent (LTR) or nightly rate (STR).

All multipliers live in this file so calibration tweaks are a single-place
change.  Calibration data lives in
docs/superpowers/specs/2026-05-10-investor-strategy-toggle-and-rental-analyzer-design.md
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from services.rentcast_service import get_rent_estimate


# ─── Heuristic tables (calibrate in Task 14) ────────────────────────────────

CONDITION_ADJUSTMENTS: dict[str, float] = {
    "excellent": 0.04,
    "good": 0.00,
    "fair": -0.06,
    "needs_work": -0.12,
}

UPGRADE_BUMPS: dict[str, float] = {
    "Kitchen": 0.020,
    "Baths": 0.015,
    "HVAC": 0.010,
    "Flooring": 0.005,
    "Roof": 0.005,
    "Windows": 0.005,
}

# Cap on additive upgrade bump (does NOT include the condition adjustment).
UPGRADE_CAP = 0.08
# Heuristic v2 allows broader combos; clamp widened so property-type + amenities
# + condition + upgrades can stack without saturating prematurely.
TOTAL_ADJ_CEILING = 0.25
TOTAL_ADJ_FLOOR = -0.25

# STR market multipliers (effective monthly STR revenue ≈ multiplier × LTR rent).
# Calibrated 2026-05-10 against AirDNA / AirROI / Rabbu Boston-metro market data:
#   - Tourist (Cape Cod): ~$272/night × ~50% annual occ ≈ $4,134/mo vs ~$2,300 LTR → 1.8×
#   - Urban (Boston):     ~$272/night × ~46.7% occ ≈ $3,861/mo vs ~$3,100 LTR → 1.25×
#   - Suburban (Worcester 2BR): ~$158/night × ~50% occ ≈ $2,400/mo vs ~$2,160 LTR → 1.1×
# Multipliers rounded slightly above measured values to leave room for well-run hosts.
STR_MARKET_MULTIPLIERS: dict[str, float] = {
    "tourist": 2.0,
    "urban": 1.3,
    "suburban": 1.2,
}

# Suggested occupancy reflects realistic annualized averages, not peak-season or
# top-quartile performers. AirDNA puts Boston at ~46.7%, Cape Cod ~50% annualized
# (peak-loaded, soft shoulder), Worcester ~50%. Rounded to clean values.
STR_SUGGESTED_OCCUPANCY: dict[str, int] = {
    "tourist": 55,
    "urban": 55,
    "suburban": 50,
}

# Per-bedroom fallback baseline (Boston-metro starting points).
BEDROOM_BASELINE: dict[int, int] = {
    1: 1400,
    2: 1800,
    3: 2300,
    4: 2800,
    5: 3300,
}

# When no RentCast and no purchase price, multiply per-bedroom baseline by 1.0.
# When purchase price is available, fallback = max(baseline, 0.7% × price).
FALLBACK_PERCENT_OF_PRICE = 0.007

NIGHTS_PER_MONTH = 30.4


# ─── Heuristic v2 tables (property-type-aware) ──────────────────────────────

# Property-type adjusters applied AFTER the (now type-weighted) baseline.
PROPERTY_TYPE_ADJUSTMENTS: dict[str, float] = {
    "single_family":     0.08,
    "duplex":            0.06,
    "townhouse":         0.03,
    "condo":             0.00,
    "multi_2_4_unit":   -0.02,
    "multi_5plus_unit": -0.05,
    "adu":              -0.08,
}

# Amenity bumps (additive, then capped at AMENITY_CAP).
# Garage supersedes off_street_parking when both are present.
AMENITY_BUMPS: dict[str, float] = {
    "in_unit_laundry":     0.030,
    "off_street_parking":  0.025,
    "garage":              0.040,
    "central_ac":          0.020,
    "private_outdoor":     0.030,
    "dishwasher":          0.010,
    "pet_friendly":        0.015,
}
AMENITY_CAP = 0.12

# Bath premium: each bath above 1 = +2.5%, capped at +7.5%.
BATH_PREMIUM_PER_EXTRA = 0.025
BATH_PREMIUM_CAP = 0.075

# Year-built tiers (cutoff_year_exclusive, adjustment).
YEAR_BUILT_TIERS: list[tuple[int, float]] = [
    (1950, -0.02),   # pre-1950
    (1990,  0.00),   # 1950-1990
    (2010,  0.02),   # 1990-2010
    (9999,  0.05),   # 2010+
]

# Sqft refinement: ±1% per 100sqft above/below typical for bed count, capped at ±6%.
SQFT_TYPICAL_PER_BED: dict[int, int] = {
    1: 700, 2: 950, 3: 1300, 4: 1800, 5: 2200,
}
SQFT_ADJ_PER_100SQFT = 0.01
SQFT_ADJ_CAP = 0.06

# 7×7 property-type similarity matrix for comp re-weighting.
# Diagonal = 1.0. Symmetric. Used to weight comps when computing the baseline.
PROPERTY_TYPE_SIMILARITY: dict[str, dict[str, float]] = {
    "single_family":    {"single_family": 1.00, "duplex": 0.85, "townhouse": 0.70, "condo": 0.55, "multi_2_4_unit": 0.50, "multi_5plus_unit": 0.40, "adu": 0.50},
    "duplex":           {"single_family": 0.85, "duplex": 1.00, "townhouse": 0.70, "condo": 0.55, "multi_2_4_unit": 0.65, "multi_5plus_unit": 0.45, "adu": 0.55},
    "townhouse":        {"single_family": 0.70, "duplex": 0.70, "townhouse": 1.00, "condo": 0.70, "multi_2_4_unit": 0.55, "multi_5plus_unit": 0.50, "adu": 0.55},
    "condo":            {"single_family": 0.55, "duplex": 0.55, "townhouse": 0.70, "condo": 1.00, "multi_2_4_unit": 0.65, "multi_5plus_unit": 0.75, "adu": 0.60},
    "multi_2_4_unit":   {"single_family": 0.50, "duplex": 0.65, "townhouse": 0.55, "condo": 0.65, "multi_2_4_unit": 1.00, "multi_5plus_unit": 0.75, "adu": 0.60},
    "multi_5plus_unit": {"single_family": 0.40, "duplex": 0.45, "townhouse": 0.50, "condo": 0.75, "multi_2_4_unit": 0.75, "multi_5plus_unit": 1.00, "adu": 0.55},
    "adu":              {"single_family": 0.50, "duplex": 0.55, "townhouse": 0.55, "condo": 0.60, "multi_2_4_unit": 0.60, "multi_5plus_unit": 0.55, "adu": 1.00},
}

# Neutral similarity used when a comp's type is unknown / not in the matrix.
UNKNOWN_TYPE_SIMILARITY = 0.50

# RentCast's propertyType strings → our canonical taxonomy.
RENTCAST_TYPE_MAP: dict[str, str] = {
    "Single Family":  "single_family",
    "Multi Family":   "multi_2_4_unit",   # RentCast doesn't expose unit count
    "Condo":          "condo",
    "Condominium":    "condo",
    "Townhouse":      "townhouse",
    "Townhome":       "townhouse",
    "Apartment":      "multi_5plus_unit",
}


# ─── Schemas ────────────────────────────────────────────────────────────────


class EstimateRentRequest(BaseModel):
    address: str = Field(..., min_length=4)
    property_type: Optional[str] = "single_family"
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    condition: Literal["excellent", "good", "fair", "needs_work"]
    upgrades: list[str] = []
    mode: Literal["ltr", "str"] = "ltr"
    market_type: Optional[Literal["tourist", "urban", "suburban"]] = None
    # Optional context for fallbacks
    purchase_price: Optional[float] = None


# ─── Helpers ────────────────────────────────────────────────────────────────


def _condition_adjustment(condition: str) -> float:
    return CONDITION_ADJUSTMENTS.get(condition, 0.0)


def _upgrade_total_pct(upgrades: list[str]) -> float:
    total = sum(UPGRADE_BUMPS.get(u, 0.0) for u in upgrades)
    return min(total, UPGRADE_CAP)


def _clamp_total(total: float) -> float:
    return max(TOTAL_ADJ_FLOOR, min(TOTAL_ADJ_CEILING, total))


def _fallback_baseline(req: EstimateRentRequest) -> int:
    bd_baseline = BEDROOM_BASELINE.get(req.bedrooms or 3, 2300)
    price_baseline = (
        int(req.purchase_price * FALLBACK_PERCENT_OF_PRICE)
        if req.purchase_price
        else 0
    )
    return max(bd_baseline, price_baseline)


def _normalize_rentcast_type(rentcast_type: Optional[str]) -> Optional[str]:
    """Map RentCast's propertyType string to our canonical taxonomy.

    Returns None when the type is missing or unrecognized — callers should
    treat unknown comp types as having neutral (0.5) similarity.
    """
    if not rentcast_type:
        return None
    return RENTCAST_TYPE_MAP.get(rentcast_type)


def _weighted_baseline(
    comps: list[dict],
    target_type: str,
) -> tuple[Optional[float], int]:
    """Compute a property-type-aware weighted baseline from RentCast comps.

    Each comp is weighted by (type_similarity × rentcast_correlation). Comps
    with no price or zero combined weight are skipped.

    Returns:
        (baseline_dollars, same_type_count) where baseline is None if no
        usable comps were available, and same_type_count is the number of
        comps whose normalized type matches target_type exactly.
    """
    weights: list[float] = []
    prices: list[float] = []
    same_type_count = 0

    target_row = PROPERTY_TYPE_SIMILARITY.get(target_type, {})

    for comp in comps:
        price = comp.get("price")
        if not price or price <= 0:
            continue

        comp_type = _normalize_rentcast_type(comp.get("propertyType"))
        if comp_type is None:
            type_sim = UNKNOWN_TYPE_SIMILARITY
        else:
            type_sim = target_row.get(comp_type, UNKNOWN_TYPE_SIMILARITY)
            if type_sim == 1.0:
                same_type_count += 1

        correlation = comp.get("correlation")
        if correlation is None:
            correlation = 0.5

        weight = type_sim * correlation
        if weight <= 0:
            continue

        weights.append(weight)
        prices.append(float(price))

    if not weights:
        return None, 0

    weighted_sum = sum(p * w for p, w in zip(prices, weights))
    total_weight = sum(weights)
    return weighted_sum / total_weight, same_type_count


def _confidence(rentcast_data: Optional[dict], range_tightness: Optional[float]) -> str:
    if not rentcast_data:
        return "Low"
    has_comps = bool(rentcast_data.get("comparables"))
    # Tight RentCast range (< 20%) → High confidence even without comps.
    if range_tightness is not None and range_tightness < 0.20:
        return "High"
    if has_comps:
        return "High"
    if range_tightness is not None and range_tightness >= 0.30:
        return "Low"
    return "Medium"


# ─── Public API ─────────────────────────────────────────────────────────────


async def estimate_rent(req: EstimateRentRequest) -> dict:
    # Validate STR requirements upfront, before any IO
    if req.mode == "str" and not req.market_type:
        raise ValueError("market_type is required when mode == 'str'")

    rentcast = await get_rent_estimate(req.address)
    if rentcast and "rent" in rentcast and rentcast["rent"]:
        baseline = float(rentcast["rent"])
        rc_low = rentcast.get("rentRangeLow")
        rc_high = rentcast.get("rentRangeHigh")
        range_tightness = (
            (rc_high - rc_low) / baseline
            if rc_low is not None and rc_high is not None and baseline > 0
            else None
        )
    else:
        baseline = float(_fallback_baseline(req))
        rentcast = None
        range_tightness = None

    cond_adj = _condition_adjustment(req.condition)
    upgrade_adj = _upgrade_total_pct(req.upgrades)
    total_adj = _clamp_total(cond_adj + upgrade_adj)
    monthly_median = round(baseline * (1 + total_adj))
    monthly_low = round(monthly_median * 0.93)
    monthly_high = round(monthly_median * 1.07)

    breakdown: list[dict] = [
        {
            "label": "RentCast baseline" if rentcast else "Per-bedroom fallback",
            "value_dollars": int(baseline),
            "pct_delta": None,
        }
    ]
    if cond_adj != 0:
        breakdown.append({
            "label": f"Condition: {req.condition.replace('_', ' ').title()}",
            "value_dollars": int(round(baseline * cond_adj)),
            "pct_delta": round(cond_adj * 100, 1),
        })
    for u in req.upgrades:
        bump = UPGRADE_BUMPS.get(u)
        if bump:
            breakdown.append({
                "label": f"Upgrade: {u}",
                "value_dollars": int(round(baseline * bump)),
                "pct_delta": round(bump * 100, 1),
            })

    comparables = []
    if rentcast:
        for comp in (rentcast.get("comparables") or [])[:3]:
            comparables.append({
                "address": comp.get("formattedAddress"),
                "rent": comp.get("price"),
                "bedrooms": comp.get("bedrooms"),
                "bathrooms": comp.get("bathrooms"),
                "sqft": comp.get("squareFootage"),
                "distance_miles": round(comp.get("distance", 0), 2),
                "correlation": round(comp.get("correlation", 0), 4),
            })

    confidence = _confidence(rentcast, range_tightness)

    response: dict = {
        "mode": req.mode,
        "monthly_low": monthly_low,
        "monthly_median": monthly_median,
        "monthly_high": monthly_high,
        "confidence": confidence,
        "breakdown": breakdown,
        "comparables": comparables,
        "data_source": "rentcast_avm" if rentcast else "fallback_heuristic",
    }

    if req.mode == "str":
        market_mult = STR_MARKET_MULTIPLIERS[req.market_type]
        suggested_occ = STR_SUGGESTED_OCCUPANCY[req.market_type]
        nightly_median = round(
            (monthly_median * market_mult) / (NIGHTS_PER_MONTH * (suggested_occ / 100))
        )
        response["nightly_median"] = nightly_median
        response["nightly_low"] = round(nightly_median * 0.85)
        response["nightly_high"] = round(nightly_median * 1.15)
        response["suggested_occupancy_pct"] = suggested_occ
        response["market_multiplier"] = market_mult

    return response
