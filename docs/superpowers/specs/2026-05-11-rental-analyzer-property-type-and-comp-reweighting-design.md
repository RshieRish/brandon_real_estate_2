# Rental Analyzer v2: Property-Type Awareness + Comp Re-Weighting

**Date:** 2026-05-11
**Status:** Draft — pending review
**Owner:** Backend + Frontend

## Goal

The current rental analyzer treats a side-by-side duplex 2bd/2ba and a 5+ unit apartment-building 2bd/2ba as the same property — the `property_type` field is accepted by the API but never used in the math. This spec adds property-type-aware estimation through two coordinated changes:

1. **Comp re-weighting** — when RentCast returns comparable rental listings, weight each comp by property-type similarity × RentCast's own correlation score. Recompute the baseline from the weighted comps instead of trusting RentCast's blended median.
2. **Heuristic v2 multipliers** — apply property-type, amenity, bath-count, year-built, and sqft adjusters on top of the (now type-weighted) baseline. Each adjuster is skipped when the corresponding input is missing.

Net effect on the user's scenario: a 2bd/2ba duplex no longer returns the same estimate as a 2bd/2ba apartment-building unit at the same address.

## Non-goals

- No LLM cross-check (deferred — adds latency and cost for marginal gain over good comp data).
- No new database tables. Property type and amenities flow through the existing `EstimateRentRequest`.
- No changes to the STR-mode multipliers — those are independent of LTR estimation and were already calibrated in the prior spec.
- No changes to the confidence ranges' tightness factors — only the High/Medium thresholds shift to account for type-match coverage.

## User flow

1. User opens the Rental Analyzer modal from `/invest`.
2. Modal renders new sections **above** the existing Condition and Upgrades chip groups:
   - **Property Type** (REQUIRED, single-select chip group of 7 values)
   - **Amenities** (optional, multi-select chip group of 7 values)
3. The existing Address / Beds / Baths / Sqft / Year fields stay, and now actually drive the math.
4. Submit button stays disabled until both `address` and `property_type` are filled (`condition` already required).
5. The result panel's breakdown lists one line per active adjuster — so the user sees exactly how property type, baths, year built, sqft, condition, upgrades, and amenities each contributed.

## Property-type taxonomy

Canonical values (added to the existing `EstimateRentRequest.property_type` Literal):

| Value | Display label | Description |
|---|---|---|
| `single_family` | Single Family | Detached SFH |
| `duplex` | Duplex | Side-by-side or stacked 2-unit, owner-rented one side |
| `townhouse` | Townhouse | Attached, single-deeded |
| `condo` | Condo | Owned unit in a building |
| `multi_2_4_unit` | Small Multi (2-4 unit) | Unit in a triple-decker or quadplex |
| `multi_5plus_unit` | Apartment Building (5+ unit) | Unit in a midsize or large apartment building |
| `adu` | ADU | Accessory dwelling unit |

The existing PropertyEvaluator (seller side) uses `single_family | multi_family | condo | townhouse`. We are NOT changing the seller side — the rental analyzer gets its own richer taxonomy because the rent-vs-property-type relationship is more granular than the sale-vs-property-type relationship.

When RentCast returns comps, its `propertyType` strings are mapped to our 7 values via a `_normalize_rentcast_type()` helper:

| RentCast string | Our value |
|---|---|
| "Single Family" | `single_family` |
| "Multi Family" | `multi_2_4_unit` (default — RentCast doesn't expose unit count) |
| "Condo" / "Condominium" | `condo` |
| "Townhouse" / "Townhome" | `townhouse` |
| "Apartment" | `multi_5plus_unit` |
| (anything else / missing) | matches everything at 0.5 weight |

## Heuristic tables (in `rental_analyzer_service.py`)

```python
PROPERTY_TYPE_ADJUSTMENTS: dict[str, float] = {
    "single_family":     0.08,
    "duplex":            0.06,
    "townhouse":         0.03,
    "condo":             0.00,
    "multi_2_4_unit":   -0.02,
    "multi_5plus_unit": -0.05,
    "adu":              -0.08,
}

AMENITY_BUMPS: dict[str, float] = {
    "in_unit_laundry":     0.03,
    "off_street_parking":  0.025,
    "garage":              0.04,   # supersedes off_street_parking when both
    "central_ac":          0.02,
    "private_outdoor":     0.03,
    "dishwasher":          0.01,
    "pet_friendly":        0.015,
}
AMENITY_CAP = 0.12

BATH_PREMIUM_PER_EXTRA = 0.025
BATH_PREMIUM_CAP = 0.075   # max +7.5% for 3+ extra baths

YEAR_BUILT_TIERS: list[tuple[int, float]] = [
    (1950, -0.02),   # pre-1950
    (1990,  0.00),   # 1950-1990
    (2010,  0.02),   # 1990-2010
    (9999,  0.05),   # 2010+
]

SQFT_TYPICAL_PER_BED: dict[int, int] = {
    1: 700, 2: 950, 3: 1300, 4: 1800, 5: 2200,
}
SQFT_ADJ_PER_100SQFT = 0.01   # ±1% per 100 sqft of deviation
SQFT_ADJ_CAP = 0.06           # max ±6%

# Updated total clamp — broader range needed for combos.
TOTAL_ADJ_CEILING = 0.25      # was 0.10
TOTAL_ADJ_FLOOR  = -0.25      # was -0.20
```

### Property-type similarity matrix (for comp re-weighting)

A 7×7 symmetric table. Diagonal = 1.0. Off-diagonal values:

| | SFH | Duplex | TH | Condo | Multi2-4 | Multi5+ | ADU |
|---|---|---|---|---|---|---|---|
| **SFH**       | 1.00 | 0.85 | 0.70 | 0.55 | 0.50 | 0.40 | 0.50 |
| **Duplex**    | 0.85 | 1.00 | 0.70 | 0.55 | 0.65 | 0.45 | 0.55 |
| **Townhouse** | 0.70 | 0.70 | 1.00 | 0.70 | 0.55 | 0.50 | 0.55 |
| **Condo**     | 0.55 | 0.55 | 0.70 | 1.00 | 0.65 | 0.75 | 0.60 |
| **Multi2-4**  | 0.50 | 0.65 | 0.55 | 0.65 | 1.00 | 0.75 | 0.60 |
| **Multi5+**   | 0.40 | 0.45 | 0.50 | 0.75 | 0.75 | 1.00 | 0.55 |
| **ADU**       | 0.50 | 0.55 | 0.55 | 0.60 | 0.60 | 0.55 | 1.00 |

Unknown comp type → 0.50 (neutral).

## Algorithm

```python
async def estimate_rent(req):
    validate_str_market_type_if_needed(req)
    rentcast = await get_rent_estimate(req.address)

    # ── Step 1: Compute baseline (now property-type-aware) ──
    comps = (rentcast or {}).get("comparables") or []
    if comps and req.property_type:
        baseline, same_type_count = _weighted_baseline(comps, req.property_type)
    else:
        baseline = float(rentcast["rent"]) if rentcast else float(_fallback_baseline(req))
        same_type_count = 0

    # ── Step 2: Apply heuristic v2 adjusters ──
    adjusters = []
    add(adjusters, "Property type",  PROPERTY_TYPE_ADJUSTMENTS.get(req.property_type, 0))
    add(adjusters, "Condition",       CONDITION_ADJUSTMENTS.get(req.condition, 0))
    if req.bathrooms is not None:
        extra = max(0, req.bathrooms - 1)
        add(adjusters, "Bath count",  min(extra * BATH_PREMIUM_PER_EXTRA, BATH_PREMIUM_CAP))
    if req.year_built is not None:
        add(adjusters, "Year built",  _year_built_adj(req.year_built))
    if req.sqft is not None and req.bedrooms is not None:
        add(adjusters, "Sqft",        _sqft_adj(req.sqft, req.bedrooms))
    for upgrade in req.upgrades:
        add(adjusters, f"Upgrade: {upgrade}", UPGRADE_BUMPS.get(upgrade, 0))
    amenity_total = 0
    for amenity in req.amenities:
        amenity_total += AMENITY_BUMPS.get(amenity, 0)
    if "garage" in req.amenities and "off_street_parking" in req.amenities:
        amenity_total -= AMENITY_BUMPS["off_street_parking"]  # garage supersedes
    amenity_total = min(amenity_total, AMENITY_CAP)
    add_grouped(adjusters, "Amenities", amenity_total, req.amenities)

    total_adj = sum(a.pct for a in adjusters)
    total_adj = max(TOTAL_ADJ_FLOOR, min(TOTAL_ADJ_CEILING, total_adj))
    monthly_median = round(baseline * (1 + total_adj))

    # ── Step 3: Range + confidence ──
    monthly_low = round(monthly_median * 0.93)
    monthly_high = round(monthly_median * 1.07)
    confidence = _confidence_v2(rentcast, same_type_count, range_tightness)

    # (STR mode + breakdown emission unchanged)
```

### `_weighted_baseline`

```python
def _weighted_baseline(comps, target_type):
    weights, prices = [], []
    same_type_count = 0
    for comp in comps:
        comp_type = _normalize_rentcast_type(comp.get("propertyType"))
        type_sim = PROPERTY_TYPE_SIMILARITY[target_type][comp_type]
        if type_sim == 1.0:
            same_type_count += 1
        correlation = comp.get("correlation") or 0.5
        weight = type_sim * correlation
        if weight > 0:
            weights.append(weight)
            prices.append(comp.get("price") or 0)
    if not weights:
        return None, 0
    return sum(p * w for p, w in zip(prices, weights)) / sum(weights), same_type_count
```

## Confidence rules (v2)

| Tier | Condition |
|---|---|
| **High** | ≥2 same-property-type comps AND range tightness < 20% |
| **Medium** | Comps available but <2 same-type matches, OR range tightness 20–30% |
| **Low** | No comps AND no RentCast baseline (fallback), OR range tightness ≥ 30% |

## Breakdown panel (response shape)

Response `breakdown` field grows from up to ~7 items to up to ~12. Each item still has the existing `{ label, value_dollars, pct_delta }` shape. Amenities collapse into one row labeled like "Amenities (In-Unit Laundry, Parking) (+5.5%, +$152)" rather than one row per amenity, to keep the panel scannable. All other adjusters render one row each. The order:

1. Weighted baseline (with note: "weighted from N comps, M of same type")
2. Property type
3. Bath count premium (if present)
4. Year built (if present)
5. Sqft refinement (if present)
6. Condition
7. Upgrades (one row each, existing behavior)
8. Amenities (collapsed, one row)

## Request/response schema changes

### `EstimateRentRequest` (Pydantic, backend)

```python
class EstimateRentRequest(BaseModel):
    address: str = Field(..., min_length=4)
    property_type: Literal[
        "single_family", "duplex", "townhouse", "condo",
        "multi_2_4_unit", "multi_5plus_unit", "adu",
    ]  # now REQUIRED, no default
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    condition: Literal["excellent", "good", "fair", "needs_work"]
    upgrades: list[str] = []
    amenities: list[str] = []         # NEW
    mode: Literal["ltr", "str"] = "ltr"
    market_type: Optional[Literal["tourist", "urban", "suburban"]] = None
    purchase_price: Optional[float] = None
```

**Backward compatibility note:** `property_type` was previously `Optional[str] = "single_family"`. Making it required is a breaking change for any client that omitted it — but the only caller is the modal we control, and the modal currently always sends it. So this is safe.

### `EstimateRentPayload` (TS, frontend)

Add `amenities: string[]` and tighten `property_type` from `string` to a literal union of the 7 values.

## UI changes (`RentalAnalyzerModal.tsx`)

Add two new sections between the bed/bath/sqft/year block and the existing Condition section.

**Property Type chip group:**

```
PROPERTY TYPE *

[ Single Family ] [ Duplex ] [ Townhouse ] [ Condo ]
[ Small Multi (2-4 unit) ] [ Apartment Building (5+ unit) ] [ ADU ]
```

Single-select, gold-when-selected styling matches the existing Condition chips.

**Amenities chip group:**

```
AMENITIES (Optional)

[ In-Unit Laundry ] [ Off-Street Parking ] [ Garage ]
[ Central AC ] [ Private Outdoor Space ] [ Dishwasher ]
[ Pet-Friendly ]
```

Multi-select, gold/outlined when selected, matches the existing Upgrades chips. When both `Garage` and `Off-Street Parking` are selected, a tiny helper line below reads "Parking supersedes — garage applies."

Submit button gate becomes: `disabled until address && condition && property_type && (mode !== 'str' || market_type)`.

## Failure modes

- **RentCast returns no comps** — `_weighted_baseline` returns `None`; we fall back to RentCast's blended median if present, else `_fallback_baseline`. Confidence drops to Medium or Low accordingly.
- **All comps have unknown property types** — every comp gets a 0.50 similarity weight. Baseline becomes a flat-weighted average across all comps; no error.
- **`property_type` arrives as a value not in the Literal** — Pydantic returns 422.
- **Garage + off-street parking both selected** — subtract `AMENITY_BUMPS["off_street_parking"]` so garage's larger bump dominates (net: +4%, not +6.5%).
- **Total adjustment exceeds ±25%** — clamped to the floor/ceiling. Breakdown panel notes "(clamped)" on the line that pushed it over.

## Testing

### Backend unit tests (`test_rental_analyzer_service.py`)

Add 6 new tests on top of the existing 5:

1. **`test_duplex_outperforms_apartment_building_at_same_address`** — Same RentCast stub, same condition, same beds/baths. Just `property_type=duplex` vs `multi_5plus_unit`. Assert duplex estimate is ≥10% higher.
2. **`test_comp_reweighting_favors_same_type`** — Stub RentCast with 5 comps: 3 apartment-building units at $2200 and 2 duplex units at $2700. With `property_type=duplex`, assert baseline is closer to $2700 than $2200.
3. **`test_bath_premium_caps_at_7_5pct`** — Property with 5 bathrooms. Assert bath premium reaches but doesn't exceed +7.5%.
4. **`test_year_built_pre_1950_penalty`** — `year_built=1900`. Assert −2% adjuster appears in breakdown.
5. **`test_sqft_above_typical_adds_premium`** — 2bd unit with 1450 sqft (typical 950). Assert +5% sqft adjuster.
6. **`test_garage_supersedes_off_street_parking`** — Both selected. Assert amenity total = 4% (not 6.5%).

The existing 5 tests need light updates to pass `property_type` explicitly (was defaulted; now required).

### Frontend

The modal already has Vitest infrastructure. Add no new test file in this iteration — modal-level rendering is exercised in Task 15-equivalent manual verification. The `parse-inputs` test file from the prior feature stays as-is (it tests a different concern).

## Calibration plan

Run the 5 LTR calibration listings from the prior spec back through the upgraded analyzer once it's deployed. The expectation:

- Properties that were 5-9% off pre-fix (Quincy SFH, Uphams Corner duplex) tighten further because the SFH and duplex multipliers correctly nudge them upward
- The Cleveland Circle apartment outlier (was +23%) drops 5-7% because the apartment-building multiplier (-5%) plus apartment-comp re-weighting both pull it down

If the new median absolute error isn't ≤ 5% (down from current 5.5%), re-tune. Document results as a second calibration appendix.

## Architecture & file changes

### Modified files

- `backend/services/rental_analyzer_service.py` — heuristic tables, `_weighted_baseline`, `_normalize_rentcast_type`, `_property_type_similarity`, expanded `estimate_rent` body
- `backend/tests/test_rental_analyzer_service.py` — 6 new tests + tweak the existing 5 to pass `property_type` explicitly
- `frontend/src/lib/rental-analyzer-types.ts` — add `PropertyType`, `Amenity` types + `PROPERTY_TYPE_OPTIONS` and `AMENITY_OPTIONS` constant arrays
- `frontend/src/components/investor/RentalAnalyzerModal.tsx` — two new chip group sections, property-type required gate, garage/parking helper line

### No DB migration, no new files needed

Property type was already on the request shape. Amenities is a new optional list field — no schema impact.

## Open questions

None — design is ready for plan-writing.
