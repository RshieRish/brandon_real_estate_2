"""Stable PostgreSQL advisory keys for Gmail task-intake serialization."""

import hashlib
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


_ACCOUNT_DOMAIN = b"sws:gmail-task-intake:advisory:v1:account\x00"
_THREAD_DOMAIN = b"sws:gmail-task-intake:advisory:v1:thread\x00"
_CONTACT_IDENTITY_DOMAIN = b"sws:crm-contact-identity:advisory:v1"


def _signed_postgresql_bigint(material: bytes) -> int:
    unsigned = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
    return unsigned - 2**64 if unsigned >= 2**63 else unsigned


def account_advisory_key(account_id: UUID) -> int:
    return _signed_postgresql_bigint(_ACCOUNT_DOMAIN + account_id.bytes)


def thread_advisory_key(account_id: UUID, gmail_thread_id: str) -> int:
    try:
        thread_bytes = gmail_thread_id.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("gmail_thread_id must contain exact ASCII bytes") from exc
    if len(thread_bytes) > 65535:
        raise ValueError("gmail_thread_id must be at most 65535 ASCII bytes")
    material = (
        _THREAD_DOMAIN
        + account_id.bytes
        + len(thread_bytes).to_bytes(2, "big")
        + thread_bytes
    )
    return _signed_postgresql_bigint(material)


def contact_identity_advisory_key() -> int:
    """Serialize contact identity mutations with uniqueness decisions."""
    return _signed_postgresql_bigint(_CONTACT_IDENTITY_DOMAIN)


async def try_session_advisory_lock(
    connection: AsyncConnection,
    account_id: UUID,
) -> bool:
    return bool(
        await connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": account_advisory_key(account_id)},
        )
    )


async def release_session_advisory_lock(
    connection: AsyncConnection,
    account_id: UUID,
) -> bool:
    return bool(
        await connection.scalar(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": account_advisory_key(account_id)},
        )
    )


async def transaction_advisory_lock(
    connection: AsyncConnection,
    account_id: UUID,
    gmail_thread_id: str,
) -> None:
    await connection.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": thread_advisory_key(account_id, gmail_thread_id)},
    )


async def contact_identity_transaction_lock(
    connection: AsyncConnection,
) -> None:
    await connection.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": contact_identity_advisory_key()},
    )


__all__ = [
    "account_advisory_key",
    "contact_identity_advisory_key",
    "contact_identity_transaction_lock",
    "release_session_advisory_lock",
    "thread_advisory_key",
    "transaction_advisory_lock",
    "try_session_advisory_lock",
]
