"""Provider jobs owned by the dedicated integration worker."""

from workers.jobs.gmail_history import GmailHistoryJob, run_gmail_history_job
from workers.jobs.gmail_receipts import GmailReceiptJob, run_gmail_receipts_job
from workers.jobs.integration_alerts import (
    IntegrationAlertsJob,
    run_integration_alerts_job,
)
from workers.jobs.sydney_questions import SydneyQuestionsJob, run_sydney_questions_job

__all__ = [
    "GmailHistoryJob",
    "GmailReceiptJob",
    "IntegrationAlertsJob",
    "SydneyQuestionsJob",
    "run_gmail_history_job",
    "run_gmail_receipts_job",
    "run_integration_alerts_job",
    "run_sydney_questions_job",
]
