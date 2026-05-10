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
        # urban multiplier 2.4, occupancy 65% → nightly = (3000 × 2.4) / (30.4 × 0.65) ≈ 364
        self.assertGreater(result["nightly_median"], 320)
        self.assertLess(result["nightly_median"], 410)
        self.assertEqual(result["suggested_occupancy_pct"], 65)


async def _async(value):
    return value


if __name__ == "__main__":
    unittest.main()
