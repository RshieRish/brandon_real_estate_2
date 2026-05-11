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
        self.assertEqual(result["confidence"], "High")

    def test_needs_work_drops_rent_below_baseline(self):
        rc = {"rent": 2400, "rentRangeLow": 2300, "rentRangeHigh": 2500, "comparables": []}
        req = EstimateRentRequest(
            address="XXXX", condition="needs_work", upgrades=[], mode="ltr",
        )
        with patch("services.rental_analyzer_service.get_rent_estimate", new=MagicMock(return_value=_async(rc))):
            result = run(estimate_rent(req))
        # Baseline 2400 − 12% = 2112
        self.assertLess(result["monthly_median"], 2200)

    def test_upgrades_capped_at_eight_pct(self):
        rc = {"rent": 2000, "rentRangeLow": None, "rentRangeHigh": None, "comparables": []}
        req = EstimateRentRequest(
            address="XXXX",
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
            address="XXXX", condition="good", upgrades=[], mode="ltr",
            bedrooms=2, purchase_price=400000,
        )
        with patch("services.rental_analyzer_service.get_rent_estimate", new=MagicMock(return_value=_async(None))):
            result = run(estimate_rent(req))
        self.assertEqual(result["confidence"], "Low")
        self.assertGreater(result["monthly_median"], 0)

    def test_str_mode_returns_nightly_rate(self):
        rc = {"rent": 3000, "rentRangeLow": None, "rentRangeHigh": None, "comparables": []}
        req = EstimateRentRequest(
            address="XXXX", condition="good", upgrades=[], mode="str", market_type="urban",
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


if __name__ == "__main__":
    unittest.main()
