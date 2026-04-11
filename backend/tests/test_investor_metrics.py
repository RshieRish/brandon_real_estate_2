import unittest

from routers.investor import InvestorInputs, calculate_metrics


class InvestorMetricsTests(unittest.TestCase):
    def test_one_year_investor_loan_uses_interest_only_debt_service(self):
        inputs = InvestorInputs(
            address="50 Cheever Ave, Dracut, MA 01826",
            purchase_price=415000,
            down_payment_pct=15,
            interest_rate=7,
            loan_term_years=1,
            monthly_rent_total=0,
            rehab_costs=48769.63,
            hold_years=1,
        )

        metrics = calculate_metrics(inputs)

        self.assertEqual(metrics["monthly_mortgage"], 2057.71)
        self.assertEqual(metrics.get("loan_structure"), "interest_only")

    def test_thirty_year_investor_loan_stays_amortized(self):
        inputs = InvestorInputs(
            purchase_price=415000,
            down_payment_pct=15,
            interest_rate=7,
            loan_term_years=30,
            monthly_rent_total=0,
            rehab_costs=48769.63,
            hold_years=1,
        )

        metrics = calculate_metrics(inputs)

        self.assertEqual(metrics["monthly_mortgage"], 2346.85)
        self.assertEqual(metrics.get("loan_structure"), "amortized")


if __name__ == "__main__":
    unittest.main()
