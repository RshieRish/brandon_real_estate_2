"""Tests for the rental analyzer service.

These tests use stubbed RentCast responses so they're deterministic.
The real-world calibration runs happen in Task 14 (separate spreadsheet).
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from services.rental_analyzer_service import (
    EstimateRentRequest,
    estimate_rent,
    _weighted_baseline,
    _normalize_rentcast_type,
    _property_type_adjustment,
    _amenity_total_pct,
    _bath_premium,
    _year_built_adj,
    _sqft_adj,
    AMENITY_BUMPS,
    AMENITY_CAP,
    BATH_PREMIUM_CAP,
    SQFT_ADJ_CAP,
)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class RentalAnalyzerTests(unittest.TestCase):

    def test_excellent_condition_uplifts_rentcast_baseline(self):
        rc = {"rent": 2400, "rentRangeLow": 2200, "rentRangeHigh": 2600, "comparables": []}
        req = EstimateRentRequest(
            address="50 Cheever Ave, Dracut, MA 01826",
            property_type="condo",
            condition="excellent",
            upgrades=["Kitchen"],
            mode="ltr",
        )
        with patch("services.rental_analyzer_service.get_rent_estimate", new=MagicMock(return_value=_async(rc))):
            result = run(estimate_rent(req))

        # Baseline 2400 + 4% (excellent) + 2% (kitchen) = 2544
        self.assertEqual(result["mode"], "ltr")
        self.assertGreaterEqual(result["monthly_median"], 2540)
        self.assertLessEqual(result["monthly_median"], 2560)
        # v2 confidence: no same-type comps → Medium (not High)
        self.assertEqual(result["confidence"], "Medium")

    def test_needs_work_drops_rent_below_baseline(self):
        rc = {"rent": 2400, "rentRangeLow": 2300, "rentRangeHigh": 2500, "comparables": []}
        req = EstimateRentRequest(
            address="XXXX", property_type="condo", condition="needs_work", upgrades=[], mode="ltr",
        )
        with patch("services.rental_analyzer_service.get_rent_estimate", new=MagicMock(return_value=_async(rc))):
            result = run(estimate_rent(req))
        # Baseline 2400 − 12% = 2112
        self.assertLess(result["monthly_median"], 2200)

    def test_upgrades_capped_at_eight_pct(self):
        rc = {"rent": 2000, "rentRangeLow": None, "rentRangeHigh": None, "comparables": []}
        req = EstimateRentRequest(
            address="XXXX",
            property_type="condo",
            condition="good",
            upgrades=["Kitchen", "Baths", "HVAC", "Flooring", "Roof", "Windows"],
            mode="ltr",
        )
        with patch("services.rental_analyzer_service.get_rent_estimate", new=MagicMock(return_value=_async(rc))):
            result = run(estimate_rent(req))
        # Sum of bumps = 6.0%; well within +8% cap. Should equal 2000 × 1.06 = 2120.
        self.assertEqual(result["monthly_median"], 2120)

    def test_falls_back_when_rentcast_returns_none(self):
        req = EstimateRentRequest(
            address="XXXX", property_type="single_family", condition="good", upgrades=[], mode="ltr",
            bedrooms=2, purchase_price=400000,
        )
        with patch("services.rental_analyzer_service.get_rent_estimate", new=MagicMock(return_value=_async(None))):
            result = run(estimate_rent(req))
        self.assertEqual(result["confidence"], "Low")
        self.assertGreater(result["monthly_median"], 0)

    def test_str_mode_returns_nightly_rate(self):
        rc = {"rent": 3000, "rentRangeLow": None, "rentRangeHigh": None, "comparables": []}
        req = EstimateRentRequest(
            address="XXXX", property_type="condo", condition="good", upgrades=[], mode="str", market_type="urban",
        )
        with patch("services.rental_analyzer_service.get_rent_estimate", new=MagicMock(return_value=_async(rc))):
            result = run(estimate_rent(req))
        self.assertEqual(result["mode"], "str")
        # urban multiplier 1.3, occupancy 55% → nightly = (3000 × 1.3) / (30.4 × 0.55) ≈ 233
        # (calibrated 2026-05-10 against AirDNA / AirROI Boston-metro data)
        self.assertGreater(result["nightly_median"], 210)
        self.assertLess(result["nightly_median"], 260)
        self.assertEqual(result["suggested_occupancy_pct"], 55)


async def _async(value):
    return value


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


class AdjusterHelperTests(unittest.TestCase):
    def test_property_type_adjustments(self):
        self.assertAlmostEqual(_property_type_adjustment("single_family"), 0.08)
        self.assertAlmostEqual(_property_type_adjustment("duplex"), 0.06)
        self.assertAlmostEqual(_property_type_adjustment("multi_5plus_unit"), -0.05)
        self.assertEqual(_property_type_adjustment("unknown_type"), 0.0)

    def test_amenity_total_stacks_then_caps(self):
        # All 7 amenities = 3 + 2.5 + 4 + 2 + 3 + 1 + 1.5 = 17%, but capped at 12%.
        # Note: garage supersedes off_street_parking, so total = 17 - 2.5 = 14.5%,
        # still capped at 12%.
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


if __name__ == "__main__":
    unittest.main()
