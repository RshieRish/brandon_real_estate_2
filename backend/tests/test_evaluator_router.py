import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from models.analytics_event import AnalyticsEvent
from routers.evaluator import EvaluatorRequest, RatingRequest, evaluate, submit_rating


class _FakeDB:
    def __init__(self):
        self.added = []
        self.next_id = 1
        self.get = AsyncMock(return_value=None)
        self.flush = AsyncMock(side_effect=self._assign_ids)

    def add(self, item):
        self.added.append(item)

    async def _assign_ids(self):
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = self.next_id
                self.next_id += 1


class EvaluatorRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_evaluate_returns_calculation_id_and_stores_event(self):
        db = _FakeDB()
        request = EvaluatorRequest(
            address="50 Cheever Ave, Lowell, MA",
            property_type="single_family",
            bedrooms=3,
            bathrooms=2.0,
            sqft=1800,
            year_built=1998,
            condition="good",
            upgrades=[],
            name="Taylor Seller",
            email="taylor@example.com",
            phone="9785550101",
        )

        with patch("routers.evaluator.geocode_address", AsyncMock(return_value={"display": "50 Cheever Ave, Lowell, MA 01852"})), patch(
            "routers.evaluator.evaluate_property",
            AsyncMock(
                return_value={
                    "range_low": 512000,
                    "range_high": 602000,
                    "confidence": "Medium",
                    "explanation": "Market-based range.",
                    "key_factors": ["Factor 1"],
                }
            ),
        ):
            response = await evaluate(request, db)

        self.assertGreater(response["calculation_id"], 0)
        stored_event = next(item for item in db.added if isinstance(item, AnalyticsEvent))
        self.assertEqual(stored_event.event_type, "seller_evaluator_calculation")
        metadata = json.loads(stored_event.metadata_json)
        self.assertEqual(metadata["inputs"]["address"], "50 Cheever Ave, Lowell, MA")
        self.assertEqual(metadata["result"]["price_low"], 512000)

    async def test_submit_rating_stores_linked_rating_event(self):
        db = _FakeDB()
        existing_event = AnalyticsEvent(
            event_type="seller_evaluator_calculation",
            page="/sell",
            referrer=None,
            user_agent=None,
            device_type=None,
            metadata_json="{}",
        )
        existing_event.id = 7
        db.get = AsyncMock(return_value=existing_event)

        response = await submit_rating(
            calculation_id=7,
            payload=RatingRequest(rating="expected"),
            db=db,
        )

        self.assertEqual(response, {"ok": True})
        stored_event = db.added[-1]
        self.assertEqual(stored_event.event_type, "seller_evaluator_rating")
        metadata = json.loads(stored_event.metadata_json)
        self.assertEqual(metadata["calculation_id"], 7)
        self.assertEqual(metadata["rating"], "expected")

    async def test_submit_rating_raises_for_missing_calculation(self):
        db = _FakeDB()
        db.get = AsyncMock(return_value=None)

        with self.assertRaises(HTTPException):
            await submit_rating(
                calculation_id=99,
                payload=RatingRequest(rating="above"),
                db=db,
            )


if __name__ == "__main__":
    unittest.main()
