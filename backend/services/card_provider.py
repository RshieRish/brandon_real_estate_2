"""Provider-neutral physical-card boundary with no browser automation."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID


class CardProviderError(RuntimeError):
    """A provider boundary failed before returning a classified outcome."""


class CardProviderNotConnected(CardProviderError):
    """No contracted provider API is configured."""


@dataclass(frozen=True, slots=True, repr=False)
class CardSendRequest:
    idempotency_key: UUID
    recipient_id: UUID
    recipient_name: str = field(repr=False)
    address: dict[str, str] = field(repr=False)
    message: str = field(repr=False)
    design_key: str


@dataclass(frozen=True, slots=True)
class CardSendResult:
    outcome: Literal["confirmed", "rejected", "ambiguous"]
    provider_status: str
    provider_receipt_id: str | None = None
    detail_code: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.outcome == "confirmed" and not self.provider_receipt_id:
            raise ValueError("confirmed card send requires a provider receipt")
        if self.outcome not in {"confirmed", "rejected", "ambiguous"}:
            raise ValueError("card provider outcome is invalid")


class CardProvider(Protocol):
    provider_name: str
    connected: bool
    connection_reason: str | None
    display_label: str
    send_calls: list[CardSendRequest]

    def estimate_cost_cents(self, recipient_count: int) -> int: ...

    async def send_card(self, request: CardSendRequest) -> CardSendResult: ...


class DisabledCardProvider:
    """Fail-closed production default until a contracted API is available."""

    provider_name = "send_out_cards"
    connected = False
    display_label = "Send Out Cards"

    def __init__(self, *, reason: str = "contract_required") -> None:
        self.connection_reason = reason
        self.send_calls: list[CardSendRequest] = []

    def estimate_cost_cents(self, recipient_count: int) -> int:
        del recipient_count
        return 0

    async def send_card(self, request: CardSendRequest) -> CardSendResult:
        del request
        raise CardProviderNotConnected(self.connection_reason)


class DeterministicFakeCardProvider:
    """No-network provider used only through explicit test injection."""

    provider_name = "send_out_cards"
    connected = True
    connection_reason = None
    display_label = "Send Out Cards test provider"

    def __init__(
        self,
        *,
        outcomes: Sequence[Literal["confirmed", "rejected", "ambiguous"]] = (),
        cost_cents: int = 200,
        before_send: Callable[[CardSendRequest], Awaitable[None]] | None = None,
    ) -> None:
        if type(cost_cents) is not int or cost_cents < 0:
            raise ValueError("cost_cents must be a non-negative integer")
        self._outcomes = tuple(outcomes)
        self._cost_cents = cost_cents
        self._before_send = before_send
        self.send_calls: list[CardSendRequest] = []

    def estimate_cost_cents(self, recipient_count: int) -> int:
        if type(recipient_count) is not int or recipient_count < 0:
            raise ValueError("recipient_count must be a non-negative integer")
        return recipient_count * self._cost_cents

    async def send_card(self, request: CardSendRequest) -> CardSendResult:
        call_index = len(self.send_calls)
        self.send_calls.append(request)
        if self._before_send is not None:
            await self._before_send(request)
        outcome = (
            self._outcomes[call_index]
            if call_index < len(self._outcomes)
            else "confirmed"
        )
        if outcome == "confirmed":
            return CardSendResult(
                outcome="confirmed",
                provider_status="accepted",
                provider_receipt_id=f"fake-{request.idempotency_key}",
            )
        if outcome == "rejected":
            return CardSendResult(
                outcome="rejected",
                provider_status="rejected",
                detail_code="synthetic_rejection",
            )
        return CardSendResult(
            outcome="ambiguous",
            provider_status="timeout",
            detail_code="synthetic_ambiguous",
        )


def configured_card_provider() -> CardProvider:
    """Return only the disabled provider until the API contract is implemented."""
    mode = os.getenv("CARD_PROVIDER_MODE", "disabled").strip().lower()
    if mode == "disabled":
        return DisabledCardProvider(reason="contract_required")
    if mode == "send_out_cards":
        required = (
            os.getenv("SEND_OUT_CARDS_API_BASE_URL", "").strip(),
            os.getenv("SEND_OUT_CARDS_API_TOKEN", "").strip(),
            os.getenv("SEND_OUT_CARDS_ACCOUNT_ID", "").strip(),
        )
        return DisabledCardProvider(
            reason=(
                "contract_adapter_pending"
                if all(required)
                else "provider_configuration_incomplete"
            )
        )
    return DisabledCardProvider(reason="provider_mode_invalid")


__all__ = [
    "CardProvider",
    "CardProviderError",
    "CardProviderNotConnected",
    "CardSendRequest",
    "CardSendResult",
    "DeterministicFakeCardProvider",
    "DisabledCardProvider",
    "configured_card_provider",
]
