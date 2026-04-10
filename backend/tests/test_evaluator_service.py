import unittest

from services import evaluator_service


class EvaluatorServiceTests(unittest.TestCase):
    def test_calculate_property_estimate_returns_ordered_nonzero_range(self):
        result = evaluator_service.calculate_property_estimate(
            data={
                "address": "50 Cheever Ave, Lowell, MA",
                "property_type": "single_family",
                "bedrooms": 3,
                "bathrooms": 2.0,
                "sqft": 1800,
                "year_built": 1998,
                "condition": "good",
                "upgrades": [],
            },
            geo={"display": "50 Cheever Ave, Lowell, MA 01852"},
        )

        self.assertGreater(result["range_low"], 0)
        self.assertGreater(result["range_high"], result["range_low"])
        self.assertIn(result["confidence"], {"High", "Medium", "Low"})
        self.assertGreaterEqual(len(result["key_factors"]), 3)

    def test_calculate_property_estimate_rewards_condition_and_upgrades(self):
        poor_result = evaluator_service.calculate_property_estimate(
            data={
                "address": "50 Cheever Ave, Lowell, MA",
                "property_type": "single_family",
                "bedrooms": 3,
                "bathrooms": 2.0,
                "sqft": 1800,
                "year_built": 1998,
                "condition": "needs_work",
                "upgrades": [],
            },
            geo={"display": "50 Cheever Ave, Lowell, MA 01852"},
        )

        improved_result = evaluator_service.calculate_property_estimate(
            data={
                "address": "50 Cheever Ave, Lowell, MA",
                "property_type": "single_family",
                "bedrooms": 3,
                "bathrooms": 2.0,
                "sqft": 1800,
                "year_built": 1998,
                "condition": "excellent",
                "upgrades": ["Kitchen remodel", "Bathrooms", "Roof"],
            },
            geo={"display": "50 Cheever Ave, Lowell, MA 01852"},
        )

        self.assertGreater(improved_result["range_low"], poor_result["range_low"])
        self.assertGreater(improved_result["range_high"], poor_result["range_high"])

    def test_lowell_single_family_estimate_stays_within_current_market_band(self):
        result = evaluator_service.calculate_property_estimate(
            data={
                "address": "50 Cheever Ave, Lowell, MA",
                "property_type": "single_family",
                "bedrooms": 3,
                "bathrooms": 2.0,
                "sqft": 1800,
                "year_built": 1998,
                "condition": "good",
                "upgrades": [],
            },
            geo={"display": "50 Cheever Ave, Lowell, MA 01852"},
        )

        self.assertGreaterEqual(result["range_low"], 480000)
        self.assertLessEqual(result["range_high"], 620000)


if __name__ == "__main__":
    unittest.main()
