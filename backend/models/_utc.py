"""Shared persistence-time UTC normalization for database timestamps."""

from datetime import UTC, datetime


def normalize_database_datetime(value: datetime | None) -> datetime | None:
    """Treat naive database values as UTC and normalize aware writes to UTC."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC)


__all__ = ["normalize_database_datetime"]
