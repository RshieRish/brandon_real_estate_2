"""Provider jobs owned by the dedicated integration worker."""

from workers.jobs.gmail_history import GmailHistoryJob, run_gmail_history_job

__all__ = ["GmailHistoryJob", "run_gmail_history_job"]
