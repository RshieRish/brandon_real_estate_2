# Rental Analyzer v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the rental analyzer property-type aware. A side-by-side duplex no longer returns the same estimate as a 5+ unit apartment building unit at the same address.

**Architecture:** Two coordinated changes in `backend/services/rental_analyzer_service.py`: (1) when RentCast returns comparable listings, re-weight them by property-type similarity × RentCast's correlation score and recompute the baseline from the weighted comps; (2) layer five new heuristic adjusters on top (property type, amenities, bath premium, year built, sqft refinement). Frontend modal grows two new chip groups (Property Type, Amenities) — property type becomes required, amenities optional.

**Tech Stack:** FastAPI + Pydantic v2 (backend), Next.js 16 + React 19 + Framer Motion + TypeScript (frontend), Vitest + pytest (tests).

**Spec:** [docs/superpowers/specs/2026-05-11-rental-analyzer-property-type-and-comp-reweighting-design.md](docs/superpowers/specs/2026-05-11-rental-analyzer-property-type-and-comp-reweighting-design.md)

---

## File Structure

**Modified:**
- `backend/services/rental_analyzer_service.py` — add heuristic v2 tables, similarity matrix, RentCast type normalizer, weighted-baseline function, expanded adjuster pipeline, updated confidence rules
- `backend/tests/test_rental_analyzer_service.py` — update existing 5 tests to pass `property_type` explicitly + add 6 new tests
- `frontend/src/lib/rental-analyzer-types.ts` — narrow `property_type` to a 7-value literal union, add `Amenity` type, add `PROPERTY_TYPE_OPTIONS` and `AMENITY_OPTIONS` constant arrays, add `amenities` to the request payload
- `frontend/src/components/investor/RentalAnalyzerModal.tsx` — new Property Type chip group (single-select, required), new Amenities chip group (multi-select), updated submit gate, garage/parking helper line

**Not modified:** No DB migration. No new files. The existing `EstimateRentRequest` model gets new fields and a tighter literal type — no other backend or frontend file touches it.

---

## Phase 1 — Backend heuristic tables and helpers

### Task 1: Add the heuristic tables + similarity matrix

This task lands the new constants in `rental_analyzer_service.py` without yet using them. Pure additive change — existing tests stay green.

**Files:**
- Modify: `backend/services/rental_analyzer_service.py`

- [ ] **Step 1: Add the new constants below the existing heuristic tables**

Open `backend/services/rental_analyzer_service.py`. Find the line `NIGHTS_PER_MONTH = 30.4` (around line 76). Insert the following block immediately after it:

```python

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
```

- [ ] **Step 2: Update the total clamp constants**

Find these two lines (currently around lines 39-40):

```python
TOTAL_ADJ_CEILING = 0.10
TOTAL_ADJ_FLOOR = -0.20
```

Replace them with:

```python
# Heuristic v2 allows broader combos; clamp widened so property-type + amenities
# + condition + upgrades can stack without saturating prematurely.
TOTAL_ADJ_CEILING = 0.25
TOTAL_ADJ_FLOOR = -0.25
```

- [ ] **Step 3: Verify existing tests still pass**

Run from `/Users/rishabnandi/brandon-real-estate/backend`:

```bash
python -m pytest tests/test_rental_analyzer_service.py tests/test_estimate_rent_router.py -v
```

Expected: All 8 pre-existing tests still pass (none of them depend on the new constants).

- [ ] **Step 4: Commit**

```bash
git add backend/services/rental_analyzer_service.py
git commit -m "feat(rental): add v2 heuristic tables + property-type similarity matrix"
```

---

### Task 2: Add the comp re-weighting helper (TDD)

**Files:**
- Modify: `backend/services/rental_analyzer_service.py`
- Modify: `backend/tests/test_rental_analyzer_service.py`

- [ ] **Step 1: Write failing tests for `_weighted_baseline`**

Open `backend/tests/test_rental_analyzer_service.py`. Add these imports at the top (alongside the existing imports):

```python
from services.rental_analyzer_service import (
    _weighted_baseline,
    _normalize_rentcast_type,
)
```

Then append these tests after the existing `RentalAnalyzerTests` class (still inside the file, as a new class):

```python
class WeightedBaselineTests(unittest.TestCase):
    def test_same_type_comps_dominate(self):
        # 3 apartment-building comps at $2200, 2 duplex comps at $2700.
        # Looking up a duplex → weighted baseline should land closer to $2700.
        comps = [
            {"price": 2200, "propertyType": "Apartment", "correlation": 0.9},
            {"price": 2200, "propertyType": "Apartment", "correlation": 0.9},
            {"price": 2200, "propertyType": "Apartment", "correlation": 0.9},
            {"price": 2700, "propertyType": "Multi Family", "correlation": 0.9},
            {"price": 2700, "propertyType": "Multi Family", "correlation": 0.9},
        ]
        baseline, same_type = _weighted_baseline(comps, "duplex")
        # multi_2_4_unit similarity 0.65 to duplex; apartment 0.45 to duplex
        # weighted = (2200×0.45×3 + 2700×0.65×2) / (0.45×3 + 0.65×2)
        #         = (2970 + 3510) / (1.35 + 1.30) = 6480 / 2.65 ≈ 2445
        self.assertGreater(baseline, 2350)
        self.assertLess(baseline, 2550)

    def test_returns_zero_count_when_no_same_type_match(self):
        comps = [
            {"price": 2200, "propertyType": "Apartment", "correlation": 0.9},
        ]
        baseline, same_type = _weighted_baseline(comps, "single_family")
        self.assertEqual(same_type, 0)
        self.assertGreater(baseline, 0)

    def test_counts_same_type_matches(self):
        comps = [
            {"price": 2700, "propertyType": "Single Family", "correlation": 0.9},
            {"price": 2700, "propertyType": "Single Family", "correlation": 0.9},
            {"price": 2200, "propertyType": "Apartment", "correlation": 0.9},
        ]
        baseline, same_type = _weighted_baseline(comps, "single_family")
        self.assertEqual(same_type, 2)

    def test_returns_none_when_no_comps(self):
        baseline, same_type = _weighted_baseline([], "duplex")
        self.assertIsNone(baseline)
        self.assertEqual(same_type, 0)

    def test_unknown_comp_type_uses_neutral_similarity(self):
        comps = [
            {"price": 2500, "propertyType": "Mystery Type", "correlation": 0.8},
        ]
        baseline, same_type = _weighted_baseline(comps, "duplex")
        # With one comp at 0.5 similarity, baseline = 2500 (weighted-mean of one).
        self.assertEqual(baseline, 2500.0)
        self.assertEqual(same_type, 0)


class NormalizeRentcastTypeTests(unittest.TestCase):
    def test_known_mappings(self):
        self.assertEqual(_normalize_rentcast_type("Single Family"), "single_family")
        self.assertEqual(_normalize_rentcast_type("Multi Family"), "multi_2_4_unit")
        self.assertEqual(_normalize_rentcast_type("Condo"), "condo")
        self.assertEqual(_normalize_rentcast_type("Townhouse"), "townhouse")
        self.assertEqual(_normalize_rentcast_type("Apartment"), "multi_5plus_unit")

    def test_unknown_returns_none(self):
        self.assertIsNone(_normalize_rentcast_type("Mystery Type"))
        self.assertIsNone(_normalize_rentcast_type(None))
        self.assertIsNone(_normalize_rentcast_type(""))
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `/Users/rishabnandi/brandon-real-estate/backend`:

```bash
python -m pytest tests/test_rental_analyzer_service.py -v
```

Expected: 7 new tests fail with `ImportError` on `_weighted_baseline` and `_normalize_rentcast_type`.

- [ ] **Step 3: Implement `_normalize_rentcast_type` and `_weighted_baseline`**

Open `backend/services/rental_analyzer_service.py`. Find the `_confidence` helper (currently around line 123). Insert the following two helpers immediately BEFORE `_confidence`:

```python
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
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_rental_analyzer_service.py::WeightedBaselineTests tests/test_rental_analyzer_service.py::NormalizeRentcastTypeTests -v
```

Expected: All 7 new tests pass.

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
python -m pytest tests/test_rental_analyzer_service.py tests/test_estimate_rent_router.py -v
```

Expected: 8 existing + 7 new = 15 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/rental_analyzer_service.py backend/tests/test_rental_analyzer_service.py
git commit -m "feat(rental): add weighted-baseline + RentCast type normalizer helpers"
```

---

### Task 3: Add the property-type and amenity adjuster helpers (TDD)

**Files:**
- Modify: `backend/services/rental_analyzer_service.py`
- Modify: `backend/tests/test_rental_analyzer_service.py`

- [ ] **Step 1: Write failing tests for the new adjuster helpers**

Open `backend/tests/test_rental_analyzer_service.py`. Add to the imports block:

```python
from services.rental_analyzer_service import (
    _property_type_adjustment,
    _amenity_total_pct,
    _bath_premium,
    _year_built_adj,
    _sqft_adj,
)
```

Append this new test class at the end of the file (BEFORE `if __name__ == "__main__":`):

```python
class AdjusterHelperTests(unittest.TestCase):
    def test_property_type_adjustments(self):
        self.assertAlmostEqual(_property_type_adjustment("single_family"), 0.08)
        self.assertAlmostEqual(_property_type_adjustment("duplex"), 0.06)
        self.assertAlmostEqual(_property_type_adjustment("multi_5plus_unit"), -0.05)
        self.assertEqual(_property_type_adjustment("unknown_type"), 0.0)

    def test_amenity_total_stacks_then_caps(self):
        # All 7 amenities = 3 + 2.5 + 4 + 2 + 3 + 1 + 1.5 = 17%, but capped at 12%.
        all_amenities = list(AMENITY_BUMPS.keys())
        total = _amenity_total_pct(all_amenities)
        self.assertAlmostEqual(total, AMENITY_CAP)

    def test_garage_supersedes_off_street_parking(self):
        # Both selected: garage 4% should apply, off_street_parking 2.5% should be removed.
        total = _amenity_total_pct(["garage", "off_street_parking"])
        self.assertAlmostEqual(total, 0.04)

    def test_garage_alone_unaffected(self):
        total = _amenity_total_pct(["garage"])
        self.assertAlmostEqual(total, 0.04)

    def test_off_street_parking_alone_unaffected(self):
        total = _amenity_total_pct(["off_street_parking"])
        self.assertAlmostEqual(total, 0.025)

    def test_unknown_amenity_skipped(self):
        total = _amenity_total_pct(["in_unit_laundry", "moon_view"])
        self.assertAlmostEqual(total, 0.030)

    def test_bath_premium_scales_then_caps(self):
        self.assertAlmostEqual(_bath_premium(1.0), 0.0)
        self.assertAlmostEqual(_bath_premium(2.0), 0.025)
        self.assertAlmostEqual(_bath_premium(3.0), 0.05)
        # 5 baths = 4 extra × 2.5% = 10%, capped at 7.5%.
        self.assertAlmostEqual(_bath_premium(5.0), BATH_PREMIUM_CAP)

    def test_bath_premium_handles_half_baths(self):
        # 2.5 baths = 1.5 extra × 2.5% = 3.75%.
        self.assertAlmostEqual(_bath_premium(2.5), 0.0375)

    def test_year_built_tiers(self):
        self.assertAlmostEqual(_year_built_adj(1900), -0.02)
        self.assertAlmostEqual(_year_built_adj(1949), -0.02)
        self.assertAlmostEqual(_year_built_adj(1950), 0.0)
        self.assertAlmostEqual(_year_built_adj(1989), 0.0)
        self.assertAlmostEqual(_year_built_adj(1990), 0.02)
        self.assertAlmostEqual(_year_built_adj(2009), 0.02)
        self.assertAlmostEqual(_year_built_adj(2010), 0.05)
        self.assertAlmostEqual(_year_built_adj(2025), 0.05)

    def test_sqft_adj_above_typical(self):
        # 2bd unit, typical 950 sqft. 1450 sqft = +500 above = +5%.
        self.assertAlmostEqual(_sqft_adj(1450, 2), 0.05)

    def test_sqft_adj_below_typical(self):
        # 2bd, 750 sqft = −200 below = −2%.
        self.assertAlmostEqual(_sqft_adj(750, 2), -0.02)

    def test_sqft_adj_caps_at_six_percent(self):
        # 2bd, 2000 sqft = +1050 above = would be +10.5%, capped at +6%.
        self.assertAlmostEqual(_sqft_adj(2000, 2), SQFT_ADJ_CAP)

    def test_sqft_adj_unknown_bed_count_returns_zero(self):
        self.assertEqual(_sqft_adj(1450, 99), 0.0)


# Bring constants into scope for the new tests
from services.rental_analyzer_service import (
    AMENITY_BUMPS,
    AMENITY_CAP,
    BATH_PREMIUM_CAP,
    SQFT_ADJ_CAP,
)
```

NOTE: The `from services.rental_analyzer_service import AMENITY_BUMPS, ...` line goes near the OTHER imports at the top of the file (alongside the existing `from services.rental_analyzer_service import (...)`); the redundant copy at the bottom of the snippet above is just for clarity — don't actually duplicate it. Put one import block at the top.

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_rental_analyzer_service.py::AdjusterHelperTests -v
```

Expected: All 13 new tests fail with `ImportError` on the missing helpers.

- [ ] **Step 3: Implement the five adjuster helpers**

Open `backend/services/rental_analyzer_service.py`. Find the existing `_condition_adjustment` helper (currently around line 100). Replace the entire helpers section (lines ~100-135) with:

```python
# ─── Helpers ────────────────────────────────────────────────────────────────


def _condition_adjustment(condition: str) -> float:
    return CONDITION_ADJUSTMENTS.get(condition, 0.0)


def _upgrade_total_pct(upgrades: list[str]) -> float:
    total = sum(UPGRADE_BUMPS.get(u, 0.0) for u in upgrades)
    return min(total, UPGRADE_CAP)


def _property_type_adjustment(property_type: str) -> float:
    return PROPERTY_TYPE_ADJUSTMENTS.get(property_type, 0.0)


def _amenity_total_pct(amenities: list[str]) -> float:
    total = sum(AMENITY_BUMPS.get(a, 0.0) for a in amenities)
    # Garage supersedes off_street_parking when both are present.
    if "garage" in amenities and "off_street_parking" in amenities:
        total -= AMENITY_BUMPS["off_street_parking"]
    return min(total, AMENITY_CAP)


def _bath_premium(bathrooms: float) -> float:
    extra = max(0.0, bathrooms - 1.0)
    return min(extra * BATH_PREMIUM_PER_EXTRA, BATH_PREMIUM_CAP)


def _year_built_adj(year_built: int) -> float:
    for cutoff_exclusive, adj in YEAR_BUILT_TIERS:
        if year_built < cutoff_exclusive:
            return adj
    return YEAR_BUILT_TIERS[-1][1]


def _sqft_adj(sqft: int, bedrooms: int) -> float:
    typical = SQFT_TYPICAL_PER_BED.get(bedrooms)
    if typical is None:
        return 0.0
    delta = sqft - typical
    raw = (delta / 100.0) * SQFT_ADJ_PER_100SQFT
    return max(-SQFT_ADJ_CAP, min(SQFT_ADJ_CAP, raw))


def _clamp_total(total: float) -> float:
    return max(TOTAL_ADJ_FLOOR, min(TOTAL_ADJ_CEILING, total))


def _fallback_baseline(req: "EstimateRentRequest") -> int:
    bd_baseline = BEDROOM_BASELINE.get(req.bedrooms or 3, 2300)
    price_baseline = (
        int(req.purchase_price * FALLBACK_PERCENT_OF_PRICE)
        if req.purchase_price
        else 0
    )
    return max(bd_baseline, price_baseline)
```

Note: the `_normalize_rentcast_type` and `_weighted_baseline` from Task 2 stay where they are (above `_confidence`). The block above replaces only `_condition_adjustment` through `_fallback_baseline`. Keep `_confidence` untouched in this task — Task 5 updates it.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_rental_analyzer_service.py::AdjusterHelperTests -v
```

Expected: All 13 new tests pass.

- [ ] **Step 5: Confirm no regressions**

```bash
python -m pytest tests/test_rental_analyzer_service.py tests/test_estimate_rent_router.py -v
```

Expected: 8 pre-existing + 7 weighted-baseline + 13 adjuster = 28 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/rental_analyzer_service.py backend/tests/test_rental_analyzer_service.py
git commit -m "feat(rental): add property-type, amenity, bath, year-built, sqft adjusters"
```

---

## Phase 2 — Wire it all into `estimate_rent`

### Task 4: Update `EstimateRentRequest` schema and call site

**Files:**
- Modify: `backend/services/rental_analyzer_service.py`
- Modify: `backend/tests/test_rental_analyzer_service.py`

- [ ] **Step 1: Update `EstimateRentRequest`**

Open `backend/services/rental_analyzer_service.py`. Find the `EstimateRentRequest` class (currently around lines 82-94). Replace the entire class with:

```python
class EstimateRentRequest(BaseModel):
    address: str = Field(..., min_length=4)
    property_type: Literal[
        "single_family",
        "duplex",
        "townhouse",
        "condo",
        "multi_2_4_unit",
        "multi_5plus_unit",
        "adu",
    ]
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    condition: Literal["excellent", "good", "fair", "needs_work"]
    upgrades: list[str] = []
    amenities: list[str] = []
    mode: Literal["ltr", "str"] = "ltr"
    market_type: Optional[Literal["tourist", "urban", "suburban"]] = None
    # Optional context for fallbacks
    purchase_price: Optional[float] = None
```

NOTE: `property_type` was previously `Optional[str] = "single_family"`. It is now required with no default — clients must always pass one of the 7 canonical values. The frontend modal (Task 7) is updated to enforce this.

- [ ] **Step 2: Update the 5 existing tests to pass `property_type` explicitly**

In `backend/tests/test_rental_analyzer_service.py`, find each of the 5 existing tests in `RentalAnalyzerTests`. They construct `EstimateRentRequest(...)`. Add `property_type="single_family"` to each call. Here's the exact diff for each:

Test 1 (`test_excellent_condition_uplifts_rentcast_baseline`):
```python
req = EstimateRentRequest(
    address="50 Cheever Ave, Dracut, MA 01826",
    property_type="single_family",   # NEW
    condition="excellent",
    upgrades=["Kitchen"],
    mode="ltr",
)
```

Test 2 (`test_needs_work_drops_rent_below_baseline`):
```python
req = EstimateRentRequest(
    address="XXXX", property_type="single_family", condition="needs_work", upgrades=[], mode="ltr",
)
```

Test 3 (`test_upgrades_capped_at_eight_pct`):
```python
req = EstimateRentRequest(
    address="XXXX",
    property_type="single_family",   # NEW
    condition="good",
    upgrades=["Kitchen", "Baths", "HVAC", "Flooring", "Roof", "Windows"],
    mode="ltr",
)
```

Test 4 (`test_falls_back_when_rentcast_returns_none`):
```python
req = EstimateRentRequest(
    address="XXXX", property_type="single_family", condition="good", upgrades=[], mode="ltr",
    bedrooms=2, purchase_price=400000,
)
```

Test 5 (`test_str_mode_returns_nightly_rate`):
```python
req = EstimateRentRequest(
    address="XXXX", property_type="single_family", condition="good", upgrades=[], mode="str", market_type="urban",
)
```

Update the 3 router tests in `backend/tests/test_estimate_rent_router.py` too. The bodies currently look like:

```python
json={
    "address": "50 Cheever Ave, Dracut, MA 01826",
    "condition": "good",
    "upgrades": [],
    "mode": "ltr",
}
```

Update each of the 3 to include `"property_type": "single_family"` (and for `test_short_address_rejected`, the test asserts 422 on a 1-char address — keep `property_type` out of that one body so it still fails validation, OR include it; both produce 422 since address fails first).

Specifically:
- `test_ltr_happy_path`: add `"property_type": "single_family"` to the JSON body
- `test_str_requires_market_type`: add `"property_type": "single_family"` to the JSON body (this still fails because market_type is missing for STR)
- `test_short_address_rejected`: leave as-is (1-char address fails validation first)

- [ ] **Step 3: Run the existing-now-updated tests to confirm they still pass**

```bash
python -m pytest tests/test_rental_analyzer_service.py::RentalAnalyzerTests tests/test_estimate_rent_router.py -v
```

Expected: 8 tests still pass. (We haven't yet wired property_type into `estimate_rent`, so the numbers won't have changed — Task 5 does that.)

- [ ] **Step 4: Run the helper tests to confirm they still pass**

```bash
python -m pytest tests/test_rental_analyzer_service.py::WeightedBaselineTests tests/test_rental_analyzer_service.py::NormalizeRentcastTypeTests tests/test_rental_analyzer_service.py::AdjusterHelperTests -v
```

Expected: 20 helper tests still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/rental_analyzer_service.py backend/tests/test_rental_analyzer_service.py backend/tests/test_estimate_rent_router.py
git commit -m "feat(rental): make property_type required + tighten Literal type"
```

---

### Task 5: Rewire `estimate_rent` to use the v2 baseline + adjusters

This is the integration task. Add the new adjusters to the pipeline, switch the baseline to the weighted version, expand the breakdown, and update the confidence rules.

**Files:**
- Modify: `backend/services/rental_analyzer_service.py`
- Modify: `backend/tests/test_rental_analyzer_service.py`

- [ ] **Step 1: Write a failing integration test for property-type uplift**

Append this new test class to `backend/tests/test_rental_analyzer_service.py`:

```python
class V2IntegrationTests(unittest.TestCase):
    def test_duplex_outperforms_apartment_building_at_same_address(self):
        # Same RentCast stub, same baseline, same condition/beds/baths.
        # Only difference: property_type. Duplex should land ≥10% higher than 5+ unit apt.
        rc = {
            "rent": 2400,
            "rentRangeLow": 2300,
            "rentRangeHigh": 2500,
            "comparables": [],   # no comps → falls back to RentCast median baseline
        }
        duplex_req = EstimateRentRequest(
            address="50 Cheever Ave, Dracut, MA 01826",
            property_type="duplex",
            condition="good",
            upgrades=[],
            mode="ltr",
        )
        apt_req = EstimateRentRequest(
            address="50 Cheever Ave, Dracut, MA 01826",
            property_type="multi_5plus_unit",
            condition="good",
            upgrades=[],
            mode="ltr",
        )
        with patch(
            "services.rental_analyzer_service.get_rent_estimate",
            new=MagicMock(return_value=_async(rc)),
        ):
            duplex_result = run(estimate_rent(duplex_req))
        with patch(
            "services.rental_analyzer_service.get_rent_estimate",
            new=MagicMock(return_value=_async(rc)),
        ):
            apt_result = run(estimate_rent(apt_req))

        # duplex: 2400 × (1 + 0.06) = 2544
        # apt:    2400 × (1 + (-0.05)) = 2280
        # ratio:  2544 / 2280 ≈ 1.116 → ≥10% delta
        self.assertGreater(duplex_result["monthly_median"], apt_result["monthly_median"])
        ratio = duplex_result["monthly_median"] / apt_result["monthly_median"]
        self.assertGreater(ratio, 1.10)

    def test_comp_reweighting_pulls_baseline_toward_same_type(self):
        # RentCast median is 2400 (their blend), but the comp list is 3 apt comps at $2200
        # and 2 duplex comps at $2700. Looking up a duplex → weighted baseline ≈ $2445
        # (verified in WeightedBaselineTests), not $2400.
        rc = {
            "rent": 2400,
            "rentRangeLow": 2300,
            "rentRangeHigh": 2500,
            "comparables": [
                {"price": 2200, "propertyType": "Apartment", "correlation": 0.9,
                 "formattedAddress": "1 Apt St", "bedrooms": 2, "bathrooms": 1, "squareFootage": 800, "distance": 0.1},
                {"price": 2200, "propertyType": "Apartment", "correlation": 0.9,
                 "formattedAddress": "2 Apt St", "bedrooms": 2, "bathrooms": 1, "squareFootage": 800, "distance": 0.1},
                {"price": 2200, "propertyType": "Apartment", "correlation": 0.9,
                 "formattedAddress": "3 Apt St", "bedrooms": 2, "bathrooms": 1, "squareFootage": 800, "distance": 0.1},
                {"price": 2700, "propertyType": "Multi Family", "correlation": 0.9,
                 "formattedAddress": "4 Duplex St", "bedrooms": 2, "bathrooms": 1, "squareFootage": 1000, "distance": 0.2},
                {"price": 2700, "propertyType": "Multi Family", "correlation": 0.9,
                 "formattedAddress": "5 Duplex St", "bedrooms": 2, "bathrooms": 1, "squareFootage": 1000, "distance": 0.2},
            ],
        }
        req = EstimateRentRequest(
            address="50 Cheever Ave, Dracut, MA 01826",
            property_type="duplex",
            condition="good",
            upgrades=[],
            mode="ltr",
        )
        with patch(
            "services.rental_analyzer_service.get_rent_estimate",
            new=MagicMock(return_value=_async(rc)),
        ):
            result = run(estimate_rent(req))

        # weighted baseline ≈ 2445; with +6% duplex = 2592.
        # Plain RentCast median path would be 2400 × 1.06 = 2544.
        # So weighted result should land > 2544.
        self.assertGreater(result["monthly_median"], 2544)

    def test_bath_premium_appears_in_estimate(self):
        rc = {"rent": 2000, "rentRangeLow": None, "rentRangeHigh": None, "comparables": []}
        req = EstimateRentRequest(
            address="XXXX",
            property_type="condo",   # 0% prop-type adj
            bathrooms=3.0,
            condition="good",
            upgrades=[],
            mode="ltr",
        )
        with patch(
            "services.rental_analyzer_service.get_rent_estimate",
            new=MagicMock(return_value=_async(rc)),
        ):
            result = run(estimate_rent(req))
        # 2 extra baths × 2.5% = 5% → 2000 × 1.05 = 2100.
        self.assertEqual(result["monthly_median"], 2100)

    def test_amenity_total_lands_in_breakdown(self):
        rc = {"rent": 2000, "rentRangeLow": None, "rentRangeHigh": None, "comparables": []}
        req = EstimateRentRequest(
            address="XXXX",
            property_type="condo",
            condition="good",
            upgrades=[],
            amenities=["in_unit_laundry", "garage"],
            mode="ltr",
        )
        with patch(
            "services.rental_analyzer_service.get_rent_estimate",
            new=MagicMock(return_value=_async(rc)),
        ):
            result = run(estimate_rent(req))
        # in_unit_laundry 3% + garage 4% = 7% → 2000 × 1.07 = 2140.
        self.assertEqual(result["monthly_median"], 2140)
        # And the breakdown should include a single combined "Amenities" line.
        labels = [b["label"] for b in result["breakdown"]]
        amenity_rows = [l for l in labels if "Amenities" in l]
        self.assertEqual(len(amenity_rows), 1)

    def test_total_adjustment_clamps_at_25pct(self):
        # Stack everything to push past +25%: excellent (+4) + all upgrades capped (+8)
        # + SFH (+8) + amenities capped (+12) + bath premium (+7.5) + sqft (+6) + 2010+ (+5)
        # = ~50%, should clamp to +25%.
        rc = {"rent": 2000, "rentRangeLow": None, "rentRangeHigh": None, "comparables": []}
        req = EstimateRentRequest(
            address="XXXX",
            property_type="single_family",
            bedrooms=2,
            bathrooms=5.0,
            sqft=2000,
            year_built=2020,
            condition="excellent",
            upgrades=["Kitchen", "Baths", "HVAC", "Flooring", "Roof", "Windows"],
            amenities=list(AMENITY_BUMPS.keys()),
            mode="ltr",
        )
        with patch(
            "services.rental_analyzer_service.get_rent_estimate",
            new=MagicMock(return_value=_async(rc)),
        ):
            result = run(estimate_rent(req))
        # 2000 × 1.25 = 2500 (clamped).
        self.assertEqual(result["monthly_median"], 2500)


# Bring the constants used by V2IntegrationTests into scope.
# (Add to the top-of-file imports alongside the others if not already present.)
```

NOTE on the import comment: `AMENITY_BUMPS` is already imported via Task 3's update. If not, add it to the top-of-file imports.

- [ ] **Step 2: Run new tests to verify they fail**

```bash
python -m pytest tests/test_rental_analyzer_service.py::V2IntegrationTests -v
```

Expected: All 5 new tests fail because `estimate_rent` doesn't yet apply property-type adjustment, comp re-weighting, bath premium, amenities, or sqft refinement.

- [ ] **Step 3: Rewrite the body of `estimate_rent` to use the new pipeline**

Open `backend/services/rental_analyzer_service.py`. Find the existing `estimate_rent` function. Replace its entire body (everything from `async def estimate_rent(...)` to the `return response` at the end) with:

```python
async def estimate_rent(req: EstimateRentRequest) -> dict:
    # Validate STR requirements upfront, before any IO
    if req.mode == "str" and not req.market_type:
        raise ValueError("market_type is required when mode == 'str'")

    rentcast = await get_rent_estimate(req.address)
    comps = (rentcast or {}).get("comparables") or []

    # ── Baseline (property-type-aware when comps are available) ──
    same_type_count = 0
    weighted = None
    if comps:
        weighted, same_type_count = _weighted_baseline(comps, req.property_type)

    if weighted is not None:
        baseline = weighted
        baseline_label = (
            f"Weighted baseline ({len(comps)} comps, {same_type_count} same-type)"
        )
    elif rentcast and rentcast.get("rent"):
        baseline = float(rentcast["rent"])
        baseline_label = "RentCast baseline"
    else:
        baseline = float(_fallback_baseline(req))
        baseline_label = "Per-bedroom fallback"

    # Range-tightness still derived from RentCast's published range, when present.
    range_tightness = None
    if rentcast:
        rc_low = rentcast.get("rentRangeLow")
        rc_high = rentcast.get("rentRangeHigh")
        if rc_low is not None and rc_high is not None and baseline > 0:
            range_tightness = (rc_high - rc_low) / baseline

    # ── Adjusters ──
    prop_type_adj = _property_type_adjustment(req.property_type)
    cond_adj = _condition_adjustment(req.condition)
    upgrade_adj = _upgrade_total_pct(req.upgrades)
    amenity_adj = _amenity_total_pct(req.amenities)
    bath_adj = _bath_premium(req.bathrooms) if req.bathrooms is not None else 0.0
    year_adj = _year_built_adj(req.year_built) if req.year_built is not None else 0.0
    sqft_adj = (
        _sqft_adj(req.sqft, req.bedrooms)
        if req.sqft is not None and req.bedrooms is not None
        else 0.0
    )

    total_adj = (
        prop_type_adj + cond_adj + upgrade_adj + amenity_adj + bath_adj + year_adj + sqft_adj
    )
    total_adj_clamped = _clamp_total(total_adj)
    monthly_median = round(baseline * (1 + total_adj_clamped))
    monthly_low = round(monthly_median * 0.93)
    monthly_high = round(monthly_median * 1.07)

    # ── Breakdown ──
    breakdown: list[dict] = [
        {"label": baseline_label, "value_dollars": int(baseline), "pct_delta": None},
    ]

    def _push(label: str, pct: float) -> None:
        if pct == 0:
            return
        breakdown.append({
            "label": label,
            "value_dollars": int(round(baseline * pct)),
            "pct_delta": round(pct * 100, 1),
        })

    _push(
        f"Property type: {req.property_type.replace('_', ' ').title()}",
        prop_type_adj,
    )
    if req.bathrooms is not None and bath_adj > 0:
        _push(f"Bath count: {req.bathrooms}", bath_adj)
    if req.year_built is not None and year_adj != 0:
        _push(f"Year built: {req.year_built}", year_adj)
    if req.sqft is not None and req.bedrooms is not None and sqft_adj != 0:
        _push(f"Sqft: {req.sqft} vs typical {SQFT_TYPICAL_PER_BED.get(req.bedrooms, '?')}", sqft_adj)
    _push(f"Condition: {req.condition.replace('_', ' ').title()}", cond_adj)
    for upgrade in req.upgrades:
        bump = UPGRADE_BUMPS.get(upgrade)
        if bump:
            _push(f"Upgrade: {upgrade}", bump)
    if amenity_adj > 0:
        amenity_labels = ", ".join(
            a.replace("_", " ").title()
            for a in req.amenities
            if AMENITY_BUMPS.get(a, 0) > 0
        )
        _push(f"Amenities ({amenity_labels})", amenity_adj)
    if total_adj != total_adj_clamped:
        breakdown.append({
            "label": "(clamped to ±25% ceiling)",
            "value_dollars": 0,
            "pct_delta": round((total_adj_clamped - total_adj) * 100, 1),
        })

    # ── Comparables for the UI ──
    comparables = []
    for comp in comps[:3]:
        comparables.append({
            "address": comp.get("formattedAddress"),
            "rent": comp.get("price"),
            "bedrooms": comp.get("bedrooms"),
            "bathrooms": comp.get("bathrooms"),
            "sqft": comp.get("squareFootage"),
            "distance_miles": round(comp.get("distance", 0), 2),
            "correlation": round(comp.get("correlation", 0), 4),
            "property_type": _normalize_rentcast_type(comp.get("propertyType")),
        })

    confidence = _confidence_v2(rentcast, same_type_count, range_tightness)

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
```

- [ ] **Step 4: Replace `_confidence` with `_confidence_v2`**

Still in `backend/services/rental_analyzer_service.py`, find the existing `_confidence` function. Replace it with:

```python
def _confidence_v2(
    rentcast_data: Optional[dict],
    same_type_count: int,
    range_tightness: Optional[float],
) -> str:
    """Confidence label for the v2 rental analyzer.

    Rules:
        High   — ≥2 same-property-type comps AND range tightness < 20%
        Medium — comps available but <2 same-type matches, OR range tightness 20-30%
        Low    — no RentCast data, OR range tightness ≥ 30%
    """
    if not rentcast_data:
        return "Low"
    if range_tightness is not None and range_tightness >= 0.30:
        return "Low"
    if same_type_count >= 2 and (range_tightness is None or range_tightness < 0.20):
        return "High"
    return "Medium"
```

Keep the old name `_confidence` as a thin alias for backward compatibility if anything imports it (nothing does, but be safe):

```python
_confidence = _confidence_v2
```

Add that single line right after the `_confidence_v2` definition.

- [ ] **Step 5: Run all rental analyzer tests**

```bash
python -m pytest tests/test_rental_analyzer_service.py tests/test_estimate_rent_router.py -v
```

Expected: 28 (Tasks 1-4) + 5 (V2IntegrationTests) = 33 tests pass.

If any of the pre-existing 5 `RentalAnalyzerTests` fail now because the v2 pipeline produces different numbers (the property-type +0% for `single_family` should keep them unchanged, but check), update the assertions to the new expected values. Specifically:

- `test_excellent_condition_uplifts_rentcast_baseline`: baseline 2400 × (1 + 0.04 + 0.02 + 0.08 SFH) = 2736. Update the assertion ranges from `>= 2540, <= 2560` to `>= 2720, <= 2750`.

Wait — that's a meaningful behavior change. The single_family adjuster (+8%) now kicks in for the previously-defaulted property type. The test name doesn't promise a specific value, just that excellent + kitchen upgrade lifts the baseline. We have two options:

1. **Use a property type with 0% adjuster in the existing test** — change `property_type="single_family"` to `property_type="condo"` in this specific test so the existing assertion ranges still hold.
2. **Update the assertion ranges** to match the new SFH-inclusive math.

Pick option 1 — change `property_type="single_family"` to `property_type="condo"` ONLY in `test_excellent_condition_uplifts_rentcast_baseline` (Task 4 currently set it to single_family). This preserves the original test's intent (verifying condition+upgrade adjusters) without leaking property-type behavior into it.

Re-run:

```bash
python -m pytest tests/test_rental_analyzer_service.py::RentalAnalyzerTests::test_excellent_condition_uplifts_rentcast_baseline -v
```

Expected: passes again.

Also check `test_str_mode_returns_nightly_rate` — it uses RentCast baseline 3000 and asserts nightly_median in [320, 410]. With `single_family` adding +8%, monthly becomes 3000 × 1.08 = 3240, and STR nightly = (3240 × 1.3) / (30.4 × 0.55) ≈ 252. That would FAIL the existing assertion `> 320`.

Change `property_type="single_family"` → `property_type="condo"` in `test_str_mode_returns_nightly_rate` too.

Re-run the full suite:

```bash
python -m pytest tests/test_rental_analyzer_service.py tests/test_estimate_rent_router.py -v
```

Expected: 33 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/rental_analyzer_service.py backend/tests/test_rental_analyzer_service.py
git commit -m "feat(rental): wire v2 pipeline — weighted baseline + 7 adjusters in estimate_rent"
```

---

## Phase 3 — Frontend types and modal

### Task 6: Update shared types

**Files:**
- Modify: `frontend/src/lib/rental-analyzer-types.ts`

- [ ] **Step 1: Tighten `property_type` to a literal union and add `amenities`**

Open `frontend/src/lib/rental-analyzer-types.ts`. The existing `EstimateRentPayload` and `EstimateRentResponse` types declare `property_type?: string`. Replace the entire file with:

```ts
export type RentMode = 'ltr' | 'str';
export type RentCondition = 'excellent' | 'good' | 'fair' | 'needs_work';
export type StrMarketType = 'tourist' | 'urban' | 'suburban';

export type PropertyType =
  | 'single_family'
  | 'duplex'
  | 'townhouse'
  | 'condo'
  | 'multi_2_4_unit'
  | 'multi_5plus_unit'
  | 'adu';

export type Amenity =
  | 'in_unit_laundry'
  | 'off_street_parking'
  | 'garage'
  | 'central_ac'
  | 'private_outdoor'
  | 'dishwasher'
  | 'pet_friendly';

export interface EstimateRentPayload {
  address: string;
  property_type: PropertyType;
  bedrooms?: number;
  bathrooms?: number;
  sqft?: number;
  year_built?: number;
  condition: RentCondition;
  upgrades: string[];
  amenities: Amenity[];
  mode: RentMode;
  market_type?: StrMarketType;
  purchase_price?: number;
}

export interface RentBreakdownItem {
  label: string;
  value_dollars: number;
  pct_delta: number | null;
}

export interface EstimateRentComp {
  address: string;
  rent: number;
  bedrooms: number;
  bathrooms: number;
  sqft: number;
  distance_miles: number;
  correlation: number;
  property_type: PropertyType | null;
}

export interface EstimateRentResponse {
  mode: RentMode;
  monthly_low: number;
  monthly_median: number;
  monthly_high: number;
  confidence: 'High' | 'Medium' | 'Low';
  breakdown: RentBreakdownItem[];
  comparables: EstimateRentComp[];
  data_source: 'rentcast_avm' | 'fallback_heuristic';
  // STR-only
  nightly_low?: number;
  nightly_median?: number;
  nightly_high?: number;
  suggested_occupancy_pct?: number;
  market_multiplier?: number;
}

export const UPGRADE_OPTIONS = [
  'Kitchen',
  'Baths',
  'HVAC',
  'Flooring',
  'Roof',
  'Windows',
] as const;

export const CONDITION_OPTIONS: { value: RentCondition; label: string }[] = [
  { value: 'excellent', label: 'Excellent' },
  { value: 'good', label: 'Good' },
  { value: 'fair', label: 'Fair' },
  { value: 'needs_work', label: 'Needs Work' },
];

export const MARKET_OPTIONS: { value: StrMarketType; label: string; hint: string }[] = [
  { value: 'tourist', label: 'Tourist', hint: 'Cape Cod, Berkshires, Vermont resort' },
  { value: 'urban', label: 'Urban', hint: 'Boston, Cambridge, Somerville' },
  { value: 'suburban', label: 'Suburban', hint: 'Worcester, Lowell, Manchester NH' },
];

export const PROPERTY_TYPE_OPTIONS: { value: PropertyType; label: string }[] = [
  { value: 'single_family',    label: 'Single Family' },
  { value: 'duplex',           label: 'Duplex' },
  { value: 'townhouse',        label: 'Townhouse' },
  { value: 'condo',            label: 'Condo' },
  { value: 'multi_2_4_unit',   label: 'Small Multi (2-4 unit)' },
  { value: 'multi_5plus_unit', label: 'Apartment Building (5+ unit)' },
  { value: 'adu',              label: 'ADU' },
];

export const AMENITY_OPTIONS: { value: Amenity; label: string }[] = [
  { value: 'in_unit_laundry',    label: 'In-Unit Laundry' },
  { value: 'off_street_parking', label: 'Off-Street Parking' },
  { value: 'garage',             label: 'Garage' },
  { value: 'central_ac',         label: 'Central AC' },
  { value: 'private_outdoor',    label: 'Private Outdoor Space' },
  { value: 'dishwasher',         label: 'Dishwasher' },
  { value: 'pet_friendly',       label: 'Pet-Friendly' },
];
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: clean output. The modal file references `EstimateRentPayload` and will now error on `property_type` being string-typed in its component state — that's fixed in Task 7.

If `npm run typecheck` shows errors in `RentalAnalyzerModal.tsx` about property_type or amenities, that's expected and will be fixed in Task 7. To verify ONLY this file compiles:

```bash
cd frontend && npx tsc --noEmit src/lib/rental-analyzer-types.ts
```

(`tsc` won't accept a single file when there's a project tsconfig in effect — if the above complains, just trust that the full typecheck error will land on `RentalAnalyzerModal.tsx` and move on.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/rental-analyzer-types.ts
git commit -m "feat(rental): add PropertyType and Amenity types + option constants"
```

---

### Task 7: Update the modal with property-type and amenity chip groups

**Files:**
- Modify: `frontend/src/components/investor/RentalAnalyzerModal.tsx`

- [ ] **Step 1: Read the current modal to understand its structure**

```bash
cat /Users/rishabnandi/brandon-real-estate/frontend/src/components/investor/RentalAnalyzerModal.tsx | head -60
```

The component has `condition: RentCondition | ''` state and an `upgrades: string[]` state. We're adding equivalent property-type and amenity state.

- [ ] **Step 2: Update imports**

Find the existing import block (near the top of the file):

```tsx
import {
  CONDITION_OPTIONS,
  MARKET_OPTIONS,
  UPGRADE_OPTIONS,
  type EstimateRentPayload,
  type EstimateRentResponse,
  type RentCondition,
  type RentMode,
  type StrMarketType,
} from '@/lib/rental-analyzer-types';
```

Replace it with:

```tsx
import {
  AMENITY_OPTIONS,
  CONDITION_OPTIONS,
  MARKET_OPTIONS,
  PROPERTY_TYPE_OPTIONS,
  UPGRADE_OPTIONS,
  type Amenity,
  type EstimateRentPayload,
  type EstimateRentResponse,
  type PropertyType,
  type RentCondition,
  type RentMode,
  type StrMarketType,
} from '@/lib/rental-analyzer-types';
```

- [ ] **Step 3: Add new state declarations**

Find this block in the component:

```tsx
const [condition, setCondition] = useState<RentCondition | ''>('');
const [upgrades, setUpgrades] = useState<string[]>([]);
const [market, setMarket] = useState<StrMarketType | ''>('');
```

Replace it with:

```tsx
const [propertyType, setPropertyType] = useState<PropertyType | ''>('');
const [condition, setCondition] = useState<RentCondition | ''>('');
const [upgrades, setUpgrades] = useState<string[]>([]);
const [amenities, setAmenities] = useState<Amenity[]>([]);
const [market, setMarket] = useState<StrMarketType | ''>('');
```

- [ ] **Step 4: Update the reset effect to also reset the new fields**

Find the `useEffect` that resets state on modal open (it uses `prevOpenRef`). Inside the `if (open && !prevOpenRef.current)` block, add:

```tsx
setPropertyType('');
setAmenities([]);
```

Right after the existing `setCondition('')` or in the same block — match the existing style.

If the reset block currently looks like:

```tsx
if (open && !prevOpenRef.current) {
  setAddress(prefill?.address ?? '');
  setBedrooms(prefill?.bedrooms?.toString() ?? '');
  setBathrooms(prefill?.bathrooms?.toString() ?? '');
  setSqft(prefill?.sqft?.toString() ?? '');
  setYearBuilt(prefill?.year_built?.toString() ?? '');
  setResult(null);
  setError(null);
}
```

Add the two new lines:

```tsx
if (open && !prevOpenRef.current) {
  setAddress(prefill?.address ?? '');
  setBedrooms(prefill?.bedrooms?.toString() ?? '');
  setBathrooms(prefill?.bathrooms?.toString() ?? '');
  setSqft(prefill?.sqft?.toString() ?? '');
  setYearBuilt(prefill?.year_built?.toString() ?? '');
  setPropertyType('');
  setAmenities([]);
  setResult(null);
  setError(null);
}
```

Note: We deliberately do NOT reset `condition` or `upgrades` here either — the original modal preserves them across opens. Match that behavior for amenities. If the original DOES reset condition/upgrades, mirror that.

- [ ] **Step 5: Add a helper for toggling amenities (mirrors the existing `toggleUpgrade`)**

Find `function toggleUpgrade(u: string)`. Right after it, add:

```tsx
function toggleAmenity(a: Amenity) {
  setAmenities((prev) => (prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a]));
}
```

- [ ] **Step 6: Update `handleAnalyze` to include the new fields in the payload**

Find the `handleAnalyze` function. The early-return guard currently looks like:

```tsx
if (!address.trim() || !condition) return;
if (mode === 'str' && !market) return;
```

Update to:

```tsx
if (!address.trim() || !condition || !propertyType) return;
if (mode === 'str' && !market) return;
```

Then find the payload construction:

```tsx
const payload: EstimateRentPayload = {
  address: address.trim(),
  property_type: prefill?.property_type,
  ...
  condition,
  upgrades,
  mode,
  ...
};
```

Replace it with:

```tsx
const payload: EstimateRentPayload = {
  address: address.trim(),
  property_type: propertyType,
  bedrooms: bedrooms ? Number(bedrooms) : undefined,
  bathrooms: bathrooms ? Number(bathrooms) : undefined,
  sqft: sqft ? Number(sqft) : undefined,
  year_built: yearBuilt ? Number(yearBuilt) : undefined,
  condition,
  upgrades,
  amenities,
  mode,
  market_type: mode === 'str' ? (market as StrMarketType) : undefined,
  purchase_price: prefill?.purchase_price,
};
```

- [ ] **Step 7: Render the Property Type chip group**

Find this JSX block in the modal (the Beds/Baths/Sqft/Year row):

```tsx
<div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
  <input type="number" inputMode="numeric" min={0} placeholder="Beds" ... />
  <input type="number" inputMode="numeric" min={0} step={0.5} placeholder="Baths" ... />
  <input type="number" inputMode="numeric" min={0} placeholder="Sqft" ... />
  <input type="number" inputMode="numeric" min={1800} max={2030} placeholder="Year" ... />
</div>
```

Immediately AFTER that block (and BEFORE the existing Condition section), insert:

```tsx
<div>
  <p className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-2">
    Property Type <span className="text-gold">*</span>
  </p>
  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
    {PROPERTY_TYPE_OPTIONS.map((opt) => {
      const selected = propertyType === opt.value;
      return (
        <button
          key={opt.value}
          type="button"
          onClick={() => setPropertyType(opt.value)}
          className={`px-3 py-2.5 text-xs font-semibold tracking-wide border transition-colors ${
            selected
              ? 'bg-gold text-[#0a0a0a] border-gold'
              : 'bg-dark-surface border-dark-border text-white/60 hover:border-gold/40 hover:text-white'
          }`}
        >
          {opt.label}
        </button>
      );
    })}
  </div>
</div>
```

- [ ] **Step 8: Render the Amenities chip group**

Find the existing Upgrades chip group (it iterates `UPGRADE_OPTIONS`). Immediately AFTER its closing `</div>` (the outermost one for the Upgrades section), insert:

```tsx
<div>
  <p className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-2">
    Amenities
  </p>
  <div className="flex flex-wrap gap-2">
    {AMENITY_OPTIONS.map((opt) => {
      const selected = amenities.includes(opt.value);
      return (
        <button
          key={opt.value}
          type="button"
          onClick={() => toggleAmenity(opt.value)}
          className={`px-3 py-1.5 text-xs font-semibold tracking-widest uppercase border transition-colors ${
            selected
              ? 'bg-gold/15 border-gold text-gold'
              : 'bg-transparent border-dark-border text-white/50 hover:border-gold/40'
          }`}
        >
          {selected && <CheckCircle weight="fill" className="inline w-3 h-3 mr-1" />}
          {opt.label}
        </button>
      );
    })}
  </div>
  {amenities.includes('garage') && amenities.includes('off_street_parking') && (
    <p className="text-white/40 text-[10px] mt-2">
      Parking supersedes — only the Garage premium applies.
    </p>
  )}
</div>
```

- [ ] **Step 9: Update the Estimate button's disabled gate**

Find the Estimate button. Its `disabled` prop currently looks like:

```tsx
disabled={loading || !address.trim() || !condition || (mode === 'str' && !market)}
```

Replace with:

```tsx
disabled={loading || !address.trim() || !condition || !propertyType || (mode === 'str' && !market)}
```

- [ ] **Step 10: Update the validation hint to mention property type**

Find the validation hint paragraph (the one with `text-white/40 text-xs`). It currently lists the missing fields. Update its conditions:

```tsx
{!loading && (!address.trim() || !condition || !propertyType || (mode === 'str' && !market)) && (address || condition || propertyType || market) && (
  <p className="text-white/40 text-xs">
    {!address.trim() && 'Address required. '}
    {!propertyType && 'Pick a property type. '}
    {!condition && 'Pick a condition. '}
    {mode === 'str' && !market && 'Pick a market type.'}
  </p>
)}
```

- [ ] **Step 11: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: clean.

- [ ] **Step 12: Run frontend tests (no new tests, just regression)**

```bash
cd frontend && npm test
```

Expected: 31 existing tests still pass (none of them touch the modal directly).

- [ ] **Step 13: Commit**

```bash
git add frontend/src/components/investor/RentalAnalyzerModal.tsx
git commit -m "feat(rental): add property type + amenities chip groups to modal"
```

---

## Phase 4 — Verification

### Task 8: End-to-end verification

**Files:** None (verification only)

- [ ] **Step 1: Run all backend tests**

```bash
cd backend && python -m pytest tests/test_rental_analyzer_service.py tests/test_estimate_rent_router.py tests/test_investor_metrics.py -v
```

Expected: 33 + 3 + 2 = 38 tests pass.

- [ ] **Step 2: Run all frontend tests + typecheck**

```bash
cd frontend && npm test && npm run typecheck
```

Expected: 31 tests pass, typecheck clean.

- [ ] **Step 3: Manual smoke test against the duplex-vs-apartment scenario**

Start the backend and frontend dev servers:

```bash
# Terminal 1
cd backend && uvicorn main:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev
```

Open `http://localhost:3000/invest`. Switch to Buy & Hold strategy. Click "Estimate this" next to Monthly Rental Income.

In the modal, fill in the same property fields TWICE — first time pick Property Type = **Duplex**, second time pick Property Type = **Apartment Building (5+ unit)**. Use the same condition, amenities, and beds/baths each time.

Expected: The Duplex estimate is materially higher than the Apartment Building estimate (≥10% delta).

If you can't run a dev server, exercise the route via `curl`:

```bash
curl -X POST http://localhost:8000/api/v1/investor/estimate-rent \
  -H "Content-Type: application/json" \
  -d '{
    "address": "123 Main St, Boston, MA",
    "property_type": "duplex",
    "bedrooms": 2,
    "bathrooms": 1,
    "condition": "good",
    "upgrades": [],
    "amenities": [],
    "mode": "ltr"
  }'

curl -X POST http://localhost:8000/api/v1/investor/estimate-rent \
  -H "Content-Type: application/json" \
  -d '{
    "address": "123 Main St, Boston, MA",
    "property_type": "multi_5plus_unit",
    "bedrooms": 2,
    "bathrooms": 1,
    "condition": "good",
    "upgrades": [],
    "amenities": [],
    "mode": "ltr"
  }'
```

Compare the `monthly_median` values. Duplex should be ≥10% higher than `multi_5plus_unit`.

- [ ] **Step 4: Update tdtn.md and memory.md**

Append to `/Users/rishabnandi/brandon-real-estate/tdtn.md`:

```markdown

### 2026-05-11 — Rental Analyzer v2: Property-Type Awareness + Comp Re-Weighting
- What was built: Made the rental analyzer property-type aware. Duplex 2bd/2ba no longer returns the same estimate as a 5+ unit apartment building 2bd/2ba at the same address.
- Files modified:
  - `backend/services/rental_analyzer_service.py` (heuristic v2 tables, weighted-baseline function, expanded adjuster pipeline, confidence v2)
  - `backend/tests/test_rental_analyzer_service.py` (5 existing tests updated + 25 new tests across 4 new test classes)
  - `frontend/src/lib/rental-analyzer-types.ts` (PropertyType + Amenity types + option constants)
  - `frontend/src/components/investor/RentalAnalyzerModal.tsx` (property-type required chip group + amenities multi-select)
- Key decisions:
  - Comp re-weighting: each RentCast comp weighted by (type_similarity × correlation). Same-type matches dominate; cross-type matches contribute less.
  - 7-value property-type taxonomy: SFH, duplex, townhouse, condo, small multi (2-4), apartment building (5+), ADU.
  - Heuristic adjusters layered on the weighted baseline: property type (+8% SFH to -8% ADU), amenities (capped at +12%), bath premium (+2.5%/extra, capped +7.5%), year built (-2% pre-1950 to +5% 2010+), sqft refinement (±1%/100sqft, capped ±6%).
  - Total adjustment clamped to ±25% (was ±10%) so combos can stack realistically.
  - Garage supersedes off-street parking when both are selected.
  - property_type is REQUIRED in the modal (breaking schema change; modal is the only caller).
- Tests: 33 backend tests pass (5 existing updated + 28 new across helper + integration test classes).
- Status: Complete
```

Append to `/Users/rishabnandi/brandon-real-estate/memory.md`:

```markdown
- 2026-05-11: Rental analyzer v2 — property-type aware. RentCast comps are now re-weighted by property-type similarity before computing the baseline, plus 5 new heuristic adjusters (property type, amenities, bath count, year built, sqft) layer on top. Modal grows two new chip groups; property_type is required.
```

Commit:

```bash
git add tdtn.md memory.md
git commit -m "docs: log rental analyzer v2 in tdtn/memory"
```

- [ ] **Step 5: Final summary**

Report:
- Backend tests: 33 passing (existing 5 + 25 new + 3 router)
- Frontend tests: 31 passing (unchanged)
- Typecheck: clean
- Manual smoke: duplex vs apartment building delta confirmed
- Last commit SHA

---

## Self-Review

**Spec coverage check:**
- ✅ Property-type taxonomy (7 values) → Task 1 (constants) + Task 4 (schema) + Task 6 (TS types)
- ✅ Comp re-weighting → Task 2 (`_weighted_baseline`) + Task 5 (used in `estimate_rent`)
- ✅ Property-type similarity matrix → Task 1 (constants)
- ✅ RentCast type normalizer → Task 2 (`_normalize_rentcast_type`)
- ✅ Heuristic v2 multipliers (property type, amenities, bath, year, sqft) → Task 1 (constants) + Task 3 (helpers) + Task 5 (integration)
- ✅ Updated total clamp ±25% → Task 1
- ✅ Garage supersedes off_street_parking → Task 3 (`_amenity_total_pct`)
- ✅ Confidence v2 rules → Task 5 (`_confidence_v2`)
- ✅ Expanded breakdown with one row per active adjuster → Task 5 (breakdown builder)
- ✅ Amenities collapsed into one row → Task 5 (`_push(f"Amenities ({labels})", amenity_adj)`)
- ✅ "clamped" annotation when total exceeds ±25% → Task 5
- ✅ Schema breaking change (`property_type` required) → Task 4
- ✅ TS types narrowed → Task 6
- ✅ Modal: property-type required chip group → Task 7 (Step 7)
- ✅ Modal: amenities multi-select chip group → Task 7 (Step 8)
- ✅ Modal: garage/parking helper line → Task 7 (Step 8)
- ✅ Modal: updated submit gate → Task 7 (Step 9)
- ✅ Modal: validation hint mentions property type → Task 7 (Step 10)
- ✅ 6 new backend tests → Task 5 (V2IntegrationTests, 5 tests) + Task 2/3 (helper tests) — actually I added MORE than 6, which is fine; spec said "Add 6 new tests" as a minimum baseline
- ✅ End-to-end verification → Task 8

**Placeholder scan:**
- No "TBD", "TODO", "implement later"
- No "Add appropriate error handling" — explicit failure modes are spelled out
- No "Similar to Task N" without re-stating code
- All test code is concrete with real assertions

**Type consistency:**
- `PROPERTY_TYPE_ADJUSTMENTS` keys match `EstimateRentRequest.property_type` Literal exactly (7 values, all spelled identically)
- `AMENITY_BUMPS` keys match the `Amenity` TS type values (7 values, snake_case)
- `_weighted_baseline` signature `(comps: list[dict], target_type: str) → tuple[Optional[float], int]` is used consistently in Task 2 (definition) and Task 5 (call site)
- `_confidence_v2(rentcast_data, same_type_count, range_tightness)` signature matches the call site in Task 5
- `PropertyType` TS union matches the Python Literal exactly
- `Amenity` TS union matches `AMENITY_BUMPS.keys()` exactly

Plan ready to execute.
