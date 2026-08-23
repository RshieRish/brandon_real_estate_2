"""Database-bound Gmail History job composition."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.gmail_task_intake import GmailSyncAccount
from models.setting import Setting


_ACCOUNT_BINDING_KEY = "google_workspace_gmail_account_id"
_REFRESH_TOKEN_KEY = "google_workspace_refresh_token"
_WORKSPACE_GMAIL_BINDING_LOCK_KEY = 5_921_914_720_764_681_105
_CREDENTIAL_GENERATION_DOMAIN = (
    b"sws:gmail-task-intake:credential-generation:v1\x00"
)
_PROGRESS_STATES = frozenset(
    {"started", "completed", "degraded", "failed", "timed_out"}
)


def _credential_generation(refresh_token: str) -> bytes:
    return hashlib.sha256(
        _CREDENTIAL_GENERATION_DOMAIN + refresh_token.encode("utf-8")
    ).digest()


def _history_observer_transport(**_kwargs: Any) -> None:
    """History observation never has authority to send a Gmail message."""

    raise RuntimeError("gmail_history_observer_send_forbidden")


def _build_gmail_history_service(
    *,
    history_engine,
    provider_executor,
    refresh_token: str,
    workspace_email: str,
    participant_hash_key: bytes,
    workspace_client_id: str,
    workspace_client_secret: str,
    socket_timeout_seconds: float,
    provider_deadline_seconds: float,
    max_pages_per_run: int,
    receipt_processing_deadline_seconds: float,
    receipt_processing_stale_after_seconds: float,
    alert_sink: Callable[..., Awaitable[None]] | None,
    credential_is_current: Callable[[AsyncSession], Awaitable[bool]],
):
    # Import the modules at composition time so tests can replace the provider
    # constructor without changing the production dependency graph.
    import services.gmail_history_adapter as adapter_module
    import services.gmail_history_service as history_service_module
    from services.gmail_origin_service import GmailOriginService

    def service_factory():
        return adapter_module.build_gmail_service(
            refresh_token=refresh_token,
            client_id=workspace_client_id,
            client_secret=workspace_client_secret,
            socket_timeout_seconds=socket_timeout_seconds,
        )

    adapter = adapter_module.GmailHistoryAdapter(
        executor=provider_executor,
        service_factory=service_factory,
        deadline_seconds=provider_deadline_seconds,
        socket_timeout_seconds=socket_timeout_seconds,
    )
    origin_observer = GmailOriginService(
        engine=history_engine,
        provider_executor=provider_executor,
        transport=_history_observer_transport,
        deadline_seconds=provider_deadline_seconds,
        participant_hash_key=participant_hash_key,
        sending_stale_after_seconds=receipt_processing_stale_after_seconds,
    )
    return history_service_module.GmailHistoryService(
        engine=history_engine,
        adapter=adapter,
        participant_hash_key=participant_hash_key,
        alert_sink=alert_sink,
        max_pages_per_run=max_pages_per_run,
        receipt_processing_deadline_seconds=(
            receipt_processing_deadline_seconds
        ),
        receipt_processing_stale_after_seconds=(
            receipt_processing_stale_after_seconds
        ),
        origin_observer=origin_observer,
        credential_is_current=credential_is_current,
    )


class GmailHistoryJob:
    """Run one Gmail account using its current database-bound credential."""

    def __init__(
        self,
        *,
        enabled: bool,
        sessionmaker,
        history_engine,
        provider_executor,
        participant_hash_key: bytes | None = None,
        workspace_client_id: str = "",
        workspace_client_secret: str = "",
        socket_timeout_seconds: float = 10.0,
        provider_deadline_seconds: float = 30.0,
        max_pages_per_run: int = 100,
        whole_job_deadline_seconds: float = 300.0,
        receipt_processing_deadline_seconds: float = 30.0,
        receipt_processing_stale_after_seconds: float = 120.0,
        max_accounts_per_run: int = 1,
        service_factory: Callable[..., Any] = _build_gmail_history_service,
        alert_sink: Callable[..., Awaitable[None]] | None = None,
        progress_heartbeat: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        if whole_job_deadline_seconds <= 0:
            raise ValueError("gmail_history_job_deadline_invalid")
        if max_accounts_per_run != 1:
            raise ValueError("gmail_history_single_binding_required")
        if service_factory is _build_gmail_history_service and (
            not isinstance(participant_hash_key, bytes)
            or len(participant_hash_key) < 32
        ):
            raise ValueError("participant_hash_key_required")
        self._enabled = enabled
        self._sessionmaker = sessionmaker
        self._history_engine = history_engine
        self._provider_executor = provider_executor
        self._participant_hash_key = participant_hash_key
        self._workspace_client_id = workspace_client_id
        self._workspace_client_secret = workspace_client_secret
        self._socket_timeout_seconds = socket_timeout_seconds
        self._provider_deadline_seconds = provider_deadline_seconds
        self._max_pages_per_run = max_pages_per_run
        self._whole_job_deadline_seconds = whole_job_deadline_seconds
        self._receipt_processing_deadline_seconds = (
            receipt_processing_deadline_seconds
        )
        self._receipt_processing_stale_after_seconds = (
            receipt_processing_stale_after_seconds
        )
        self._service_factory = service_factory
        self._alert_sink = alert_sink
        self._progress_heartbeat = progress_heartbeat

    async def _heartbeat(self, state: str) -> None:
        if state not in _PROGRESS_STATES:
            raise RuntimeError("gmail_history_progress_state_invalid")
        if self._progress_heartbeat is not None:
            await self._progress_heartbeat(state)

    @staticmethod
    async def _acquire_binding_lock(session) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _WORKSPACE_GMAIL_BINDING_LOCK_KEY},
        )

    async def _bound_account(self) -> tuple[UUID, str, str, bytes]:
        async with self._sessionmaker() as session:
            await self._acquire_binding_lock(session)
            binding = await session.scalar(
                select(Setting.value).where(Setting.key == _ACCOUNT_BINDING_KEY)
            )
            if not isinstance(binding, str) or not binding.strip():
                raise RuntimeError("gmail_account_binding_missing")
            try:
                account_id = UUID(binding.strip())
            except (TypeError, ValueError):
                raise RuntimeError("gmail_account_binding_missing") from None
            account = await session.get(GmailSyncAccount, account_id)
            if account is None or not account.workspace_email.strip():
                raise RuntimeError("gmail_account_binding_missing")
            refresh_token = await session.scalar(
                select(Setting.value).where(Setting.key == _REFRESH_TOKEN_KEY)
            )
            if not isinstance(refresh_token, str) or not refresh_token.strip():
                raise RuntimeError("gmail_database_token_missing")
            effective_refresh_token = refresh_token.strip()
            snapshot = (
                account_id,
                account.workspace_email.strip().lower(),
                effective_refresh_token,
                _credential_generation(effective_refresh_token),
            )
            # The callback/provider must never hold the OAuth binding lock.
            await session.rollback()
            return snapshot

    async def _credential_is_current(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        expected_generation: bytes,
    ) -> bool:
        binding = await session.scalar(
            select(Setting.value).where(Setting.key == _ACCOUNT_BINDING_KEY)
        )
        if not isinstance(binding, str) or not binding.strip():
            return False
        try:
            current_account_id = UUID(binding.strip())
        except (TypeError, ValueError):
            return False
        if current_account_id != account_id:
            return False
        refresh_token = await session.scalar(
            select(Setting.value).where(Setting.key == _REFRESH_TOKEN_KEY)
        )
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            return False
        current_generation = _credential_generation(refresh_token.strip())
        return hmac.compare_digest(
            expected_generation,
            current_generation,
        )

    async def _run_once(self) -> bool:
        from services.gmail_history_adapter import GmailProviderFailure
        from services.gmail_history_service import (
            GmailAccountBlocked,
            GmailCursorConflict,
            GmailPaginationGuard,
        )

        (
            account_id,
            workspace_email,
            refresh_token,
            credential_generation,
        ) = await self._bound_account()

        async def credential_is_current(session: AsyncSession) -> bool:
            return await self._credential_is_current(
                session,
                account_id=account_id,
                expected_generation=credential_generation,
            )

        service = self._service_factory(
            history_engine=self._history_engine,
            provider_executor=self._provider_executor,
            refresh_token=refresh_token,
            workspace_email=workspace_email,
            participant_hash_key=self._participant_hash_key,
            workspace_client_id=self._workspace_client_id,
            workspace_client_secret=self._workspace_client_secret,
            socket_timeout_seconds=self._socket_timeout_seconds,
            provider_deadline_seconds=self._provider_deadline_seconds,
            max_pages_per_run=self._max_pages_per_run,
            receipt_processing_deadline_seconds=(
                self._receipt_processing_deadline_seconds
            ),
            receipt_processing_stale_after_seconds=(
                self._receipt_processing_stale_after_seconds
            ),
            alert_sink=self._alert_sink,
            credential_is_current=credential_is_current,
        )
        try:
            await service.sync_account(account_id)
        except (
            GmailAccountBlocked,
            GmailCursorConflict,
            GmailPaginationGuard,
            GmailProviderFailure,
        ):
            # These outcomes are already reduced to bounded durable state by
            # GmailHistoryService. They must not starve later registry jobs
            # (especially notification delivery) by restarting the worker.
            return False
        return True

    async def run(self) -> None:
        if not self._enabled:
            return
        await self._heartbeat("started")
        try:
            succeeded = await asyncio.wait_for(
                self._run_once(),
                timeout=self._whole_job_deadline_seconds,
            )
        except TimeoutError:
            await self._heartbeat("timed_out")
            raise RuntimeError("gmail_history_job_timeout") from None
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._heartbeat("failed")
            raise
        await self._heartbeat("completed" if succeeded else "degraded")


def run_gmail_history_job(**kwargs: Any) -> Callable[[], Awaitable[None]]:
    """Build the callable registered by the dedicated worker."""

    return GmailHistoryJob(**kwargs).run


__all__ = ["GmailHistoryJob", "run_gmail_history_job"]
