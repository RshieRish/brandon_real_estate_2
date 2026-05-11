"""Route-level tests for POST /api/v1/investor/estimate-rent."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _async(value):
    async def _coro():
        return value
    return _coro()


class EstimateRentRouteTests(unittest.TestCase):

    def setUp(self):
        from main import app
        self.client = TestClient(app)

    def test_ltr_happy_path(self):
        rc = {"rent": 2400, "rentRangeLow": 2300, "rentRangeHigh": 2500, "comparables": []}
        with patch(
            "services.rental_analyzer_service.get_rent_estimate",
            new=MagicMock(return_value=_async(rc)),
        ):
            resp = self.client.post(
                "/api/v1/investor/estimate-rent",
                json={
                    "address": "50 Cheever Ave, Dracut, MA 01826",
                    "property_type": "single_family",
                    "condition": "good",
                    "upgrades": [],
                    "mode": "ltr",
                },
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["mode"], "ltr")
        self.assertGreater(body["monthly_median"], 0)

    def test_str_requires_market_type(self):
        resp = self.client.post(
            "/api/v1/investor/estimate-rent",
            json={
                "address": "50 Cheever Ave, Dracut, MA 01826",
                "property_type": "single_family",
                "condition": "good",
                "upgrades": [],
                "mode": "str",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_short_address_rejected(self):
        resp = self.client.post(
            "/api/v1/investor/estimate-rent",
            json={"address": "X", "condition": "good", "upgrades": [], "mode": "ltr"},
        )
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
