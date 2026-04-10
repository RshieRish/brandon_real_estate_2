import unittest
from unittest.mock import AsyncMock, patch

from models.analytics_event import AnalyticsEvent
from routers.investor import InvestorInputs, full_analysis, track_engagement


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    def __init__(self, execute_results=None):
        self.added = []
        self.commit = AsyncMock()
        self.next_id = 1
        self.execute = AsyncMock(side_effect=execute_results or [])
        self.flush = AsyncMock(side_effect=self._assign_ids)

    def add(self, item):
        self.added.append(item)

    async def _assign_ids(self):
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = self.next_id
                self.next_id += 1


class InvestorNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_analysis_enqueues_report_requested_notification(self):
        db = _FakeDB()
        payload = InvestorInputs(
            address="50 Cheever Ave, Dracut, MA 01826",
            property_type="single_family",
            units=1,
            purchase_price=415000,
            down_payment_pct=15,
            interest_rate=7,
            loan_term_years=30,
            monthly_rent_total=0,
            rehab_costs=48769.63,
            annual_taxes=4800,
            annual_insurance=1800,
            monthly_maintenance=0,
            vacancy_rate_pct=8,
            mgmt_fee_pct=0,
            hold_years=1,
            appreciation_rate_pct=3,
            name="Investor Lead",
            email="investor@example.com",
            phone="555-0103",
        )

        with patch(
            "routers.investor.generate_investor_analysis",
            AsyncMock(return_value={"summary": "Looks solid"}),
        ), patch(
            "routers.investor.enqueue_notification",
            AsyncMock(),
        ) as enqueue_mock, patch(
            "routers.investor.run_notification_retry_pass",
            AsyncMock(return_value=1),
        ) as retry_mock:
            response = await full_analysis(payload, db)

        self.assertEqual(response["report"]["summary"], "Looks solid")
        enqueue_mock.assert_awaited_once()
        db.commit.assert_awaited_once()
        retry_mock.assert_awaited_once_with(limit=5)

    async def test_track_engagement_enqueues_once_per_session_key(self):
        existing_event = AnalyticsEvent(
            event_type="investor_calculator_engaged",
            page="/invest",
            referrer=None,
            user_agent=None,
            device_type=None,
            metadata_json='{"session_key":"session-123"}',
        )
        db = _FakeDB(
            execute_results=[
                _FakeResult(None),
                _FakeResult(existing_event),
            ]
        )

        with patch("routers.investor.enqueue_notification", AsyncMock()) as enqueue_mock, patch(
            "routers.investor.run_notification_retry_pass",
            AsyncMock(return_value=1),
        ):
            first = await track_engagement(
                session_key="session-123",
                purchase_price=415000,
                rehab_costs=48769.63,
                arv=570000,
                hold_months=6,
                db=db,
            )
            second = await track_engagement(
                session_key="session-123",
                purchase_price=415000,
                rehab_costs=48769.63,
                arv=570000,
                hold_months=6,
                db=db,
            )

        self.assertEqual(first, {"queued": True})
        self.assertEqual(second, {"queued": False})
        enqueue_mock.assert_awaited_once()
        db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
