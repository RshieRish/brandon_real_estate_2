"""Optional bounded Gemini projection job for Sydney durable context."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from models.integration_health import IntegrationHealthState
from pydantic import ValidationError
from schemas.sydney_context import SydneyContextProjectionResult
from services.integration_health_service import (
    ProviderCallTimedOut,
    ProviderExecutorSaturated,
    ProviderJobStillRunning,
    record_integration_failure,
    record_integration_success,
)
from services.sydney_context_projection import (
    ProjectionCandidate,
    ProjectionModelRequest,
    SydneyContextProjectionError,
    apply_projection_result,
    build_projection_request,
    claim_projection_candidate,
    release_projection_claim,
    validate_projection_result,
)
from sqlalchemy.exc import SQLAlchemyError

from workers.jobs.gmail_receipts import _gemini_json_response_schema

_PROVIDER = "sydney_context_projection"
_CLAIM_LEASE_MARGIN_SECONDS = 60
_MAX_CLAIM_LEASE_SECONDS = 900
_MAX_PROVIDER_DEADLINE_SECONDS = _MAX_CLAIM_LEASE_SECONDS - _CLAIM_LEASE_MARGIN_SECONDS


def build_sydney_projection_model_call(
    *,
    api_key: str,
    socket_timeout_seconds: float,
) -> Callable[[ProjectionModelRequest], object]:
    if not api_key:
        raise ValueError("sydney_projection_api_key_missing")
    if (
        isinstance(socket_timeout_seconds, bool)
        or not isinstance(socket_timeout_seconds, (int, float))
        or not math.isfinite(float(socket_timeout_seconds))
        or socket_timeout_seconds <= 0
    ):
        raise ValueError("sydney_projection_socket_timeout_invalid")
    timeout_ms = int(float(socket_timeout_seconds) * 1_000)
    if timeout_ms < 1:
        raise ValueError("sydney_projection_socket_timeout_invalid")

    def call(request: ProjectionModelRequest) -> object:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout_ms),
        )
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=request.prompt,
            config=types.GenerateContentConfig(
                system_instruction=request.system_instruction,
                response_mime_type="application/json",
                response_json_schema=_gemini_json_response_schema(
                    request.response_model
                ),
                temperature=0,
                max_output_tokens=request.max_output_tokens,
            ),
        )
        return response.parsed

    return call


def _pause_until(health: IntegrationHealthState) -> datetime | None:
    if (
        health.state == "healthy"
        or health.last_checked_at is None
        or health.consecutive_failures < 1
    ):
        return None
    seconds = min(600, 60 * (2 ** min(health.consecutive_failures - 1, 4)))
    return health.last_checked_at + timedelta(seconds=seconds)


class SydneyContextProjectionJob:
    def __init__(
        self,
        *,
        enabled: bool,
        sessionmaker,
        provider_executor,
        model_call: Callable[[ProjectionModelRequest], object],
        claim_candidate=claim_projection_candidate,
        release_claim=release_projection_claim,
        apply_result=apply_projection_result,
        clock: Callable[[], datetime] | None = None,
        provider_deadline_seconds: float = 30,
        lease_owner: str | None = None,
    ) -> None:
        if (
            isinstance(provider_deadline_seconds, bool)
            or not isinstance(provider_deadline_seconds, (int, float))
            or not math.isfinite(float(provider_deadline_seconds))
            or not 0
            < float(provider_deadline_seconds)
            <= _MAX_PROVIDER_DEADLINE_SECONDS
        ):
            raise ValueError("sydney_projection_provider_deadline_invalid")
        self._enabled = enabled
        self._sessionmaker = sessionmaker
        self._executor = provider_executor
        self._model_call = model_call
        self._claim_candidate = claim_candidate
        self._release_claim = release_claim
        self._apply_result = apply_result
        self._clock = clock or (lambda: datetime.now(UTC))
        self._provider_deadline_seconds = float(provider_deadline_seconds)
        self._claim_lease_seconds = (
            math.ceil(self._provider_deadline_seconds) + _CLAIM_LEASE_MARGIN_SECONDS
        )
        self._lease_owner = lease_owner or f"integration-worker:{uuid4()}"

    async def _record_failure(self, *, category: str, checked_at: datetime) -> None:
        async with self._sessionmaker() as db:
            await record_integration_failure(
                db,
                provider=_PROVIDER,
                state="degraded",
                checked_at=checked_at,
                error_category=category,
            )
            await db.commit()

    async def _release_candidate(self, candidate: ProjectionCandidate) -> None:
        try:
            async with self._sessionmaker() as db:
                released = await self._release_claim(db, candidate)
                if released:
                    await db.commit()
        except SQLAlchemyError:
            # A crashed or disconnected worker is recovered by the bounded lease.
            return

    async def run(self) -> None:
        if not self._enabled:
            return
        now = self._clock()
        async with self._sessionmaker() as db:
            health = await db.get(IntegrationHealthState, _PROVIDER)
            if health is not None:
                pause_until = _pause_until(health)
                if pause_until is not None and pause_until > now:
                    return
            try:
                candidate = await self._claim_candidate(
                    db,
                    lease_owner=self._lease_owner,
                    claimed_at=now,
                    lease_seconds=self._claim_lease_seconds,
                )
                if candidate is not None:
                    await db.commit()
            except (SQLAlchemyError, SydneyContextProjectionError):
                candidate = None
                selection_failed = True
            else:
                selection_failed = False
        if selection_failed:
            await self._record_failure(category="projection_failed", checked_at=now)
            return
        if candidate is None:
            return

        try:
            request = build_projection_request(candidate)
            raw_result = await self._executor.run(
                key=_PROVIDER,
                function=lambda: self._model_call(request),
                deadline_seconds=self._provider_deadline_seconds,
            )
            result = SydneyContextProjectionResult.model_validate(raw_result)
            validate_projection_result(candidate, result)
        except ProviderCallTimedOut:
            await self._release_candidate(candidate)
            await self._record_failure(category="provider_timeout", checked_at=now)
            return
        except (ProviderExecutorSaturated, ProviderJobStillRunning):
            await self._release_candidate(candidate)
            await self._record_failure(category="provider_timeout", checked_at=now)
            return
        except (ValidationError, SydneyContextProjectionError, ValueError, TypeError):
            await self._release_candidate(candidate)
            await self._record_failure(
                category="invalid_model_output",
                checked_at=now,
            )
            return
        except Exception:  # noqa: BLE001 - provider errors are categorized, never logged
            await self._release_candidate(candidate)
            await self._record_failure(category="provider_failed", checked_at=now)
            return

        try:
            async with self._sessionmaker() as db:
                await self._apply_result(db, candidate, result, produced_at=now)
                await record_integration_success(
                    db,
                    provider=_PROVIDER,
                    checked_at=now,
                )
                await db.commit()
        except (SydneyContextProjectionError, ValueError, TypeError):
            await self._release_candidate(candidate)
            await self._record_failure(
                category="invalid_model_output",
                checked_at=now,
            )
        except SQLAlchemyError:
            await self._release_candidate(candidate)
            await self._record_failure(category="projection_failed", checked_at=now)


__all__ = [
    "SydneyContextProjectionJob",
    "build_sydney_projection_model_call",
]
