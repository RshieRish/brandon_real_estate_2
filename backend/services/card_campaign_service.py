"""Transactional card-campaign lifecycle with intent-before-provider-I/O."""

from __future__ import annotations

import calendar
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid5

from models.card_campaign import (
    CardCampaign,
    CardCampaignRecipient,
    CardDeliveryAttempt,
    CardProviderConnection,
    CardProviderReceipt,
)
from models.command import CRMContact
from models.command_contacts import CRMContactAddress
from schemas.card_campaign import (
    CardCampaignApproveRequest,
    CardCampaignDetail,
    CardCampaignDraftRequest,
    CardCampaignListItem,
    CardCampaignPage,
    CardCampaignUpdateRequest,
    CardRecipientOut,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent_control_command import (
    _CELEBRATION_NAMESPACE,
    _celebration_checksum,
    _contact_reconciliation_status,
    _mailing_address_ready,
    _selected_celebrations,
)
from services.card_provider import (
    CardProvider,
    CardProviderError,
    CardProviderNotConnected,
    CardSendRequest,
    CardSendResult,
)
from services.command_contact_contracts import ContactCelebrationRow
from services.command_contacts import list_contact_celebrations

_CONTENT_DOMAIN = b"command-card-recipient-v1\x00"
_DRAFT_DOMAIN = b"command-card-draft-v1\x00"
_PROVIDER_REFERENCE_DOMAIN = b"command-card-provider-receipt-v1\x00"
_PROVIDER_KEY_NAMESPACE = UUID("5642045f-93b7-42df-bcb8-b6bfa10d3239")


class CardCampaignError(RuntimeError):
    """Base class for safe card workflow conflicts."""


class CardCampaignNotFound(CardCampaignError):
    pass


class CardCampaignIdempotencyConflict(CardCampaignError):
    pass


class CardCampaignVersionConflict(CardCampaignError):
    pass


class CardCampaignNotReady(CardCampaignError):
    pass


class CardCampaignConfirmationMismatch(CardCampaignError):
    pass


class CardCampaignAlreadyAttempted(CardCampaignError):
    pass


class CardAudienceNotReconciled(CardCampaignError):
    pass


def _canonical_hash(domain: bytes, value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(domain + canonical.encode("utf-8")).hexdigest()


def _draft_payload_hash(request: CardCampaignDraftRequest) -> str:
    payload = request.model_dump(mode="json")
    payload.pop("request_id", None)
    return _canonical_hash(_DRAFT_DOMAIN, payload)


def _address_payload(row: CRMContactAddress) -> dict[str, str]:
    payload = {
        "line1": row.line1 or "",
        "line2": row.line2 or "",
        "city": row.city or "",
        "state": row.state or "",
        "postal_code": row.postal_code or "",
        "country": row.country or "",
        "formatted": row.formatted or "",
    }
    return payload


def _address_json(row: CRMContactAddress) -> str:
    return json.dumps(
        _address_payload(row),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _content_hash(recipient: CardCampaignRecipient) -> str:
    address = (
        json.loads(recipient.address_snapshot_json)
        if recipient.address_snapshot_json is not None
        else None
    )
    return _canonical_hash(
        _CONTENT_DOMAIN,
        {
            "address": address,
            "celebration_day": recipient.celebration_day,
            "celebration_kind": recipient.celebration_kind,
            "celebration_month": recipient.celebration_month,
            "celebration_origin": recipient.celebration_origin,
            "celebration_year": recipient.celebration_year,
            "celebration_year_quality": recipient.celebration_year_quality,
            "contact_id": recipient.contact_id,
            "design_key": recipient.design_key_snapshot,
            "display_name": recipient.display_name_snapshot,
            "message": recipient.message_snapshot,
        },
    )


def _render_message(template: str, first_name: str) -> str:
    return template.replace("{first_name}", first_name)


def _status(
    recipients: list[CardCampaignRecipient],
    *,
    connected: bool,
) -> str:
    included = [recipient for recipient in recipients if not recipient.excluded]
    if not included:
        return "draft"
    if any(recipient.address_status == "missing" for recipient in included):
        return "needs_addresses"
    if not connected:
        return "needs_connection"
    return "ready_for_review"


async def _campaign_recipients(
    db: AsyncSession,
    campaign_id: UUID,
    *,
    lock: bool = False,
) -> list[CardCampaignRecipient]:
    statement = (
        select(CardCampaignRecipient)
        .where(CardCampaignRecipient.campaign_id == campaign_id)
        .order_by(
            CardCampaignRecipient.celebration_day,
            CardCampaignRecipient.display_name_snapshot,
            CardCampaignRecipient.celebration_kind,
            CardCampaignRecipient.id,
        )
    )
    if lock:
        statement = statement.with_for_update()
    return list((await db.scalars(statement)).all())


async def _campaign_for_update(db: AsyncSession, campaign_id: UUID) -> CardCampaign:
    campaign = (
        await db.scalars(
            select(CardCampaign).where(CardCampaign.id == campaign_id).with_for_update()
        )
    ).one_or_none()
    if campaign is None:
        raise CardCampaignNotFound("card_campaign_not_found")
    return campaign


class CardCampaignService:
    def __init__(self, *, provider: CardProvider) -> None:
        self.provider = provider

    async def list_campaigns(
        self,
        db: AsyncSession,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> CardCampaignPage:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        if type(offset) is not int or not 0 <= offset <= 2_147_483_647:
            raise ValueError("offset is out of range")
        total = int(await db.scalar(select(func.count(CardCampaign.id))) or 0)
        rows = list(
            (
                await db.scalars(
                    select(CardCampaign)
                    .order_by(CardCampaign.updated_at.desc(), CardCampaign.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        campaigns = [
            CardCampaignListItem.model_validate(await self.get_campaign(db, row.id))
            for row in rows
        ]
        return CardCampaignPage(campaigns=campaigns, total=total)

    async def _sync_connection(
        self,
        db: AsyncSession,
        *,
        now: datetime,
    ) -> CardProviderConnection:
        row = await db.get(CardProviderConnection, self.provider.provider_name)
        desired_state = "connected" if self.provider.connected else "disconnected"
        if row is None:
            row = CardProviderConnection(
                provider=self.provider.provider_name,
                state=desired_state,
                display_label=self.provider.display_label,
                last_error_code=self.provider.connection_reason,
                last_verified_at=now,
                version=1,
            )
            db.add(row)
        else:
            changed = (
                row.state != desired_state
                or row.display_label != self.provider.display_label
                or row.last_error_code != self.provider.connection_reason
            )
            row.state = desired_state
            row.display_label = self.provider.display_label
            row.last_error_code = self.provider.connection_reason
            row.last_verified_at = now
            if changed:
                row.version += 1
        return row

    async def create_or_get_draft(
        self,
        db: AsyncSession,
        request: CardCampaignDraftRequest,
        *,
        now: datetime | None = None,
    ) -> CardCampaignDetail:
        current = now or datetime.now(UTC)
        payload_hash = _draft_payload_hash(request)
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        existing = await db.scalar(
            select(CardCampaign).where(CardCampaign.request_id == request.request_id)
        )
        if existing is not None:
            if existing.draft_payload_hash != payload_hash:
                raise CardCampaignIdempotencyConflict(
                    "card_campaign_request_id_conflict"
                )
            await self._sync_connection(db, now=current)
            attempts = int(
                await db.scalar(
                    select(func.count(CardDeliveryAttempt.id)).where(
                        CardDeliveryAttempt.campaign_id == existing.id
                    )
                )
                or 0
            )
            if not attempts and existing.status in {
                "draft",
                "needs_addresses",
                "needs_connection",
                "ready_for_review",
            }:
                recipients = await _campaign_recipients(db, existing.id)
                next_status = _status(
                    recipients,
                    connected=self.provider.connected,
                )
                next_cost = self.provider.estimate_cost_cents(
                    sum(
                        1
                        for recipient in recipients
                        if not recipient.excluded
                        and recipient.address_status == "ready"
                    )
                )
                if (
                    existing.status != next_status
                    or existing.estimated_cost_cents != next_cost
                ):
                    existing.status = next_status
                    existing.estimated_cost_cents = next_cost
                    existing.version += 1
            return await self.get_campaign(db, existing.id)

        reconciliation = await _contact_reconciliation_status(db)
        if reconciliation != "reconciled":
            raise CardAudienceNotReconciled(f"command_contacts_{reconciliation}")
        celebrations = await list_contact_celebrations(db, month=request.month)
        birthdays = celebrations.birthdays if request.include_birthdays else ()
        anniversaries = (
            celebrations.anniversaries if request.include_home_anniversaries else ()
        )
        selected = _selected_celebrations(birthdays, kind="birthday")
        selected += _selected_celebrations(anniversaries, kind="anniversary")
        contact_ids = {row[0] for row in selected}
        contacts = {
            row.id: row
            for row in (
                await db.scalars(
                    select(CRMContact).where(CRMContact.id.in_(contact_ids))
                )
            ).all()
        }
        address_rows = (
            (
                await db.scalars(
                    select(CRMContactAddress)
                    .where(CRMContactAddress.contact_id.in_(contact_ids))
                    .order_by(
                        CRMContactAddress.contact_id,
                        CRMContactAddress.is_primary.desc(),
                        CRMContactAddress.id,
                    )
                )
            ).all()
            if contact_ids
            else []
        )
        ready_addresses: dict[int, CRMContactAddress] = {}
        for address in address_rows:
            if _mailing_address_ready(address):
                ready_addresses.setdefault(address.contact_id, address)
        checksum = _celebration_checksum(
            month=request.month,
            include_birthdays=request.include_birthdays,
            include_home_anniversaries=request.include_home_anniversaries,
            selected=selected,
            address_ready_ids=set(ready_addresses),
        )
        await self._sync_connection(db, now=current)
        campaign = CardCampaign(
            request_id=request.request_id,
            draft_payload_hash=payload_hash,
            provider=self.provider.provider_name,
            title=(
                request.title
                or f"{calendar.month_name[request.month]} celebration cards"
            ),
            purpose="celebrations",
            month=request.month,
            include_birthdays=request.include_birthdays,
            include_home_anniversaries=request.include_home_anniversaries,
            audience_ref=uuid5(_CELEBRATION_NAMESPACE, checksum),
            audience_checksum=checksum,
            status="draft",
            default_birthday_message=request.birthday_message_template,
            default_anniversary_message=request.home_anniversary_message_template,
            birthday_design_key=request.birthday_design_key,
            anniversary_design_key=request.home_anniversary_design_key,
            estimated_cost_cents=0,
            currency="USD",
            version=1,
        )
        db.add(campaign)
        await db.flush()

        rows_by_key: dict[tuple[int, str], ContactCelebrationRow] = {
            (row.contact_id, "birthday"): row for row in birthdays
        }
        rows_by_key.update(
            {(row.contact_id, "home_anniversary"): row for row in anniversaries}
        )
        recipients: list[CardCampaignRecipient] = []
        for contact_id, _display_name, kind, *_rest in sorted(
            selected,
            key=lambda item: (item[3], item[1].casefold(), item[2], item[0]),
        ):
            contact = contacts.get(contact_id)
            row = rows_by_key.get((contact_id, kind))
            if contact is None or row is None:
                raise CardCampaignError("card_campaign_audience_changed")
            address = ready_addresses.get(contact_id)
            template = (
                request.birthday_message_template
                if kind == "birthday"
                else request.home_anniversary_message_template
            )
            design = (
                request.birthday_design_key
                if kind == "birthday"
                else request.home_anniversary_design_key
            )
            recipient = CardCampaignRecipient(
                campaign_id=campaign.id,
                contact_id=contact_id,
                celebration_kind=kind,
                celebration_month=row.month,
                celebration_day=row.day,
                celebration_year=row.year,
                celebration_year_quality=row.year_quality,
                celebration_origin=row.origin,
                display_name_snapshot=row.display_name,
                message_snapshot=_render_message(template, contact.first_name),
                design_key_snapshot=design,
                address_status="ready" if address is not None else "missing",
                address_id=address.id if address is not None else None,
                address_snapshot_json=(
                    _address_json(address) if address is not None else None
                ),
                content_hash="0" * 64,
                excluded=False,
                exclusion_reason=None,
            )
            recipient.content_hash = _content_hash(recipient)
            recipients.append(recipient)
        db.add_all(recipients)
        campaign.status = _status(recipients, connected=self.provider.connected)
        campaign.estimated_cost_cents = self.provider.estimate_cost_cents(
            sum(
                1
                for recipient in recipients
                if not recipient.excluded and recipient.address_status == "ready"
            )
        )
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            existing = await db.scalar(
                select(CardCampaign).where(
                    CardCampaign.request_id == request.request_id
                )
            )
            if existing is None or existing.draft_payload_hash != payload_hash:
                raise CardCampaignIdempotencyConflict(
                    "card_campaign_request_id_conflict"
                ) from None
            return await self.get_campaign(db, existing.id)
        return await self.get_campaign(db, campaign.id)

    async def update_campaign(
        self,
        db: AsyncSession,
        campaign_id: UUID,
        request: CardCampaignUpdateRequest,
        *,
        actor: str,
    ) -> CardCampaignDetail:
        if not actor.strip():
            raise ValueError("actor is required")
        campaign = await _campaign_for_update(db, campaign_id)
        attempts = int(
            await db.scalar(
                select(func.count(CardDeliveryAttempt.id)).where(
                    CardDeliveryAttempt.campaign_id == campaign.id
                )
            )
            or 0
        )
        if attempts:
            raise CardCampaignAlreadyAttempted("card_campaign_already_attempted")
        if campaign.version != request.expected_version:
            raise CardCampaignVersionConflict("card_campaign_version_conflict")
        if request.refresh_missing_addresses and campaign.status not in {
            "draft", "needs_addresses", "needs_connection", "ready_for_review", "approved",
        }:
            raise CardCampaignNotReady("card_campaign_address_refresh_not_allowed")
        recipients = await _campaign_recipients(db, campaign.id, lock=True)
        if request.title is not None:
            campaign.title = request.title
        if request.birthday_message_template is not None:
            if "{first_name}" not in request.birthday_message_template:
                raise CardCampaignError("birthday_message_missing_first_name")
            campaign.default_birthday_message = request.birthday_message_template
        if request.home_anniversary_message_template is not None:
            if "{first_name}" not in request.home_anniversary_message_template:
                raise CardCampaignError("anniversary_message_missing_first_name")
            campaign.default_anniversary_message = (
                request.home_anniversary_message_template
            )
        if request.birthday_design_key is not None:
            campaign.birthday_design_key = request.birthday_design_key
        if request.home_anniversary_design_key is not None:
            campaign.anniversary_design_key = request.home_anniversary_design_key

        contacts = {
            row.id: row
            for row in (
                await db.scalars(
                    select(CRMContact).where(
                        CRMContact.id.in_({row.contact_id for row in recipients})
                    )
                )
            ).all()
        }
        if request.birthday_message_template is not None:
            for recipient in recipients:
                if recipient.celebration_kind == "birthday":
                    recipient.message_snapshot = _render_message(
                        request.birthday_message_template,
                        contacts[recipient.contact_id].first_name,
                    )
        if request.home_anniversary_message_template is not None:
            for recipient in recipients:
                if recipient.celebration_kind == "home_anniversary":
                    recipient.message_snapshot = _render_message(
                        request.home_anniversary_message_template,
                        contacts[recipient.contact_id].first_name,
                    )
        if request.birthday_design_key is not None:
            for recipient in recipients:
                if recipient.celebration_kind == "birthday":
                    recipient.design_key_snapshot = request.birthday_design_key
        if request.home_anniversary_design_key is not None:
            for recipient in recipients:
                if recipient.celebration_kind == "home_anniversary":
                    recipient.design_key_snapshot = request.home_anniversary_design_key

        recipients_by_id = {recipient.id: recipient for recipient in recipients}
        for change in request.recipient_updates:
            recipient = recipients_by_id.get(change.recipient_id)
            if recipient is None:
                raise CardCampaignNotFound("card_campaign_recipient_not_found")
            if change.message is not None:
                recipient.message_snapshot = change.message
            if change.design_key is not None:
                recipient.design_key_snapshot = change.design_key
            if change.excluded is not None:
                recipient.excluded = change.excluded
                recipient.exclusion_reason = (
                    change.exclusion_reason if change.excluded else None
                )

        if request.refresh_missing_addresses:
            missing_contact_ids = {
                recipient.contact_id
                for recipient in recipients
                if recipient.address_status == "missing"
            }
            ready_addresses: dict[int, CRMContactAddress] = {}
            if missing_contact_ids:
                address_rows = (
                    await db.scalars(
                        select(CRMContactAddress)
                        .where(CRMContactAddress.contact_id.in_(missing_contact_ids))
                        .order_by(
                            CRMContactAddress.contact_id,
                            CRMContactAddress.is_primary.desc(),
                            CRMContactAddress.id,
                        )
                    )
                ).all()
                for address in address_rows:
                    if _mailing_address_ready(address):
                        ready_addresses.setdefault(address.contact_id, address)
            for recipient in recipients:
                address = ready_addresses.get(recipient.contact_id)
                if recipient.address_status == "missing" and address is not None:
                    recipient.address_id = address.id
                    recipient.address_snapshot_json = _address_json(address)
                    recipient.address_status = "ready"

            # Reuse the frozen occurrences; current CRM celebrations cannot add
            # recipients or change the occasion being reviewed.
            checksum = _celebration_checksum(
                month=campaign.month,
                include_birthdays=campaign.include_birthdays,
                include_home_anniversaries=campaign.include_home_anniversaries,
                selected=tuple(
                    (
                        recipient.contact_id,
                        recipient.display_name_snapshot,
                        recipient.celebration_kind,
                        recipient.celebration_day,
                        recipient.celebration_year,
                        recipient.celebration_year_quality,
                        recipient.celebration_origin,
                    )
                    for recipient in recipients
                ),
                address_ready_ids={
                    recipient.contact_id
                    for recipient in recipients
                    if recipient.address_status == "ready"
                },
            )
            campaign.audience_checksum = checksum
            campaign.audience_ref = uuid5(_CELEBRATION_NAMESPACE, checksum)

        for recipient in recipients:
            recipient.content_hash = _content_hash(recipient)
        campaign.approved_by_actor = None
        campaign.approved_at = None
        campaign.approved_version = None
        campaign.send_request_id = None
        campaign.status = _status(recipients, connected=self.provider.connected)
        campaign.estimated_cost_cents = self.provider.estimate_cost_cents(
            sum(
                1
                for recipient in recipients
                if not recipient.excluded and recipient.address_status == "ready"
            )
        )
        campaign.version += 1
        await self._sync_connection(db, now=datetime.now(UTC))
        await db.flush()
        return await self.get_campaign(db, campaign.id)

    async def approve_and_send(
        self,
        db: AsyncSession,
        campaign_id: UUID,
        request: CardCampaignApproveRequest,
        *,
        actor: str,
        now: datetime | None = None,
    ) -> CardCampaignDetail:
        current = now or datetime.now(UTC)
        if not actor.strip():
            raise ValueError("actor is required")
        campaign = await _campaign_for_update(db, campaign_id)
        if campaign.send_request_id == request.request_id:
            return await self.get_campaign(db, campaign.id)
        attempt_count = int(
            await db.scalar(
                select(func.count(CardDeliveryAttempt.id)).where(
                    CardDeliveryAttempt.campaign_id == campaign.id
                )
            )
            or 0
        )
        if campaign.send_request_id is not None or attempt_count:
            raise CardCampaignAlreadyAttempted("card_campaign_already_attempted")
        if campaign.version != request.expected_version:
            raise CardCampaignVersionConflict("card_campaign_version_conflict")
        recipients = await _campaign_recipients(db, campaign.id, lock=True)
        campaign.status = _status(recipients, connected=self.provider.connected)
        if not self.provider.connected:
            raise CardCampaignNotReady("provider_not_connected")
        if campaign.status != "ready_for_review":
            raise CardCampaignNotReady(f"campaign_{campaign.status}")
        sendable = [
            recipient
            for recipient in recipients
            if not recipient.excluded and recipient.address_status == "ready"
        ]
        if not sendable:
            raise CardCampaignNotReady("campaign_has_no_sendable_recipients")
        estimated_cost = self.provider.estimate_cost_cents(len(sendable))
        if (
            request.confirmed_recipient_count != len(sendable)
            or request.confirmed_cost_cents != estimated_cost
        ):
            raise CardCampaignConfirmationMismatch(
                "card_campaign_confirmation_mismatch"
            )

        campaign.approved_by_actor = actor
        campaign.approved_at = current
        campaign.approved_version = campaign.version
        campaign.send_request_id = request.request_id
        campaign.estimated_cost_cents = estimated_cost
        campaign.status = "sending"
        campaign.version += 1
        attempts: list[tuple[CardDeliveryAttempt, CardCampaignRecipient]] = []
        for recipient in sendable:
            provider_key = uuid5(
                _PROVIDER_KEY_NAMESPACE,
                f"{request.request_id}:{recipient.id}",
            )
            attempt = CardDeliveryAttempt(
                campaign_id=campaign.id,
                recipient_id=recipient.id,
                request_id=request.request_id,
                attempt_number=1,
                provider=self.provider.provider_name,
                provider_idempotency_key=provider_key,
                content_hash=recipient.content_hash,
                intended_by_actor=actor,
            )
            db.add(attempt)
            attempts.append((attempt, recipient))
        await self._sync_connection(db, now=current)
        await db.flush()
        await db.commit()

        for attempt, recipient in attempts:
            address = json.loads(recipient.address_snapshot_json or "{}")
            try:
                result = await self.provider.send_card(
                    CardSendRequest(
                        idempotency_key=attempt.provider_idempotency_key,
                        recipient_id=recipient.id,
                        recipient_name=recipient.display_name_snapshot,
                        address=address,
                        message=recipient.message_snapshot,
                        design_key=recipient.design_key_snapshot,
                    )
                )
            except CardProviderNotConnected:
                result = CardSendResult(
                    outcome="rejected",
                    provider_status="not_connected",
                    detail_code="provider_not_connected",
                )
            except CardProviderError:
                result = CardSendResult(
                    outcome="ambiguous",
                    provider_status="provider_error",
                    detail_code="provider_error",
                )
            except Exception:  # noqa: BLE001 - unknown provider outcome is ambiguous
                result = CardSendResult(
                    outcome="ambiguous",
                    provider_status="unexpected_error",
                    detail_code="unexpected_provider_error",
                )
            db.add(
                CardProviderReceipt(
                    attempt_id=attempt.id,
                    campaign_id=campaign.id,
                    recipient_id=recipient.id,
                    provider=self.provider.provider_name,
                    outcome=result.outcome,
                    provider_receipt_id=result.provider_receipt_id,
                    provider_receipt_hash=(
                        hashlib.sha256(
                            _PROVIDER_REFERENCE_DOMAIN
                            + result.provider_receipt_id.encode("utf-8")
                        ).hexdigest()
                        if result.provider_receipt_id is not None
                        else None
                    ),
                    provider_status=result.provider_status,
                    detail_code=result.detail_code,
                    details_json=json.dumps(
                        result.details,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )
            await db.commit()

        campaign = await _campaign_for_update(db, campaign_id)
        outcomes = list(
            (
                await db.scalars(
                    select(CardProviderReceipt.outcome)
                    .where(CardProviderReceipt.campaign_id == campaign.id)
                    .order_by(CardProviderReceipt.created_at, CardProviderReceipt.id)
                )
            ).all()
        )
        if len(outcomes) != len(sendable) or "ambiguous" in outcomes:
            campaign.status = "delivery_uncertain"
        elif all(outcome == "confirmed" for outcome in outcomes):
            campaign.status = "sent"
        elif all(outcome == "rejected" for outcome in outcomes):
            campaign.status = "failed"
        else:
            campaign.status = "partially_sent"
        campaign.version += 1
        await db.commit()
        return await self.get_campaign(db, campaign.id)

    async def get_campaign(
        self,
        db: AsyncSession,
        campaign_id: UUID,
    ) -> CardCampaignDetail:
        campaign = await db.scalar(
            select(CardCampaign)
            .where(CardCampaign.id == campaign_id)
            .execution_options(populate_existing=True)
        )
        if campaign is None:
            raise CardCampaignNotFound("card_campaign_not_found")
        recipients = await _campaign_recipients(db, campaign.id)
        receipt_rows = (
            await db.execute(
                select(CardDeliveryAttempt.recipient_id, CardProviderReceipt.outcome)
                .join(
                    CardProviderReceipt,
                    CardProviderReceipt.attempt_id == CardDeliveryAttempt.id,
                )
                .where(CardDeliveryAttempt.campaign_id == campaign.id)
                .order_by(CardProviderReceipt.created_at, CardProviderReceipt.id)
            )
        ).all()
        outcomes = {recipient_id: outcome for recipient_id, outcome in receipt_rows}
        recipient_outputs: list[CardRecipientOut] = []
        for recipient in recipients:
            address = (
                json.loads(recipient.address_snapshot_json)
                if recipient.address_snapshot_json is not None
                else None
            )
            address_summary = None
            if isinstance(address, dict):
                formatted = address.get("formatted")
                address_summary = (
                    formatted
                    if isinstance(formatted, str) and formatted.strip()
                    else ", ".join(
                        value
                        for value in (
                            str(address.get("line1") or ""),
                            str(address.get("city") or ""),
                            str(address.get("state") or ""),
                            str(address.get("postal_code") or ""),
                        )
                        if value
                    )
                )
            recipient_outputs.append(
                CardRecipientOut(
                    id=recipient.id,
                    contact_id=recipient.contact_id,
                    display_name=recipient.display_name_snapshot,
                    celebration_kind=recipient.celebration_kind,  # type: ignore[arg-type]
                    celebration_month=recipient.celebration_month,
                    celebration_day=recipient.celebration_day,
                    celebration_year=recipient.celebration_year,
                    celebration_year_quality=recipient.celebration_year_quality,  # type: ignore[arg-type]
                    celebration_origin=recipient.celebration_origin,  # type: ignore[arg-type]
                    message=recipient.message_snapshot,
                    design_key=recipient.design_key_snapshot,
                    address_status=recipient.address_status,  # type: ignore[arg-type]
                    address_summary=address_summary,
                    excluded=recipient.excluded,
                    exclusion_reason=recipient.exclusion_reason,
                    delivery_outcome=outcomes.get(recipient.id),  # type: ignore[arg-type]
                )
            )
        included = [recipient for recipient in recipients if not recipient.excluded]
        return CardCampaignDetail(
            id=campaign.id,
            request_id=campaign.request_id,
            title=campaign.title,
            month=campaign.month,
            status=campaign.status,  # type: ignore[arg-type]
            total_recipients=len(recipients),
            sendable_recipients=sum(
                1 for recipient in included if recipient.address_status == "ready"
            ),
            missing_address_count=sum(
                1 for recipient in included if recipient.address_status == "missing"
            ),
            estimated_cost_cents=campaign.estimated_cost_cents or 0,
            currency="USD",
            version=campaign.version,
            created_at=campaign.created_at,
            updated_at=campaign.updated_at,
            include_birthdays=campaign.include_birthdays,
            include_home_anniversaries=campaign.include_home_anniversaries,
            audience_ref=campaign.audience_ref,
            audience_checksum=campaign.audience_checksum,
            birthday_recipients=sum(
                1
                for recipient in recipients
                if recipient.celebration_kind == "birthday"
            ),
            home_anniversary_recipients=sum(
                1
                for recipient in recipients
                if recipient.celebration_kind == "home_anniversary"
            ),
            excluded_recipients=sum(
                1 for recipient in recipients if recipient.excluded
            ),
            provider_connected=self.provider.connected,
            provider_connection_reason=self.provider.connection_reason,
            approved_by_actor=campaign.approved_by_actor,
            approved_at=campaign.approved_at,
            send_request_id=campaign.send_request_id,
            recipients=recipient_outputs,
        )


__all__ = [
    "CardAudienceNotReconciled",
    "CardCampaignAlreadyAttempted",
    "CardCampaignConfirmationMismatch",
    "CardCampaignError",
    "CardCampaignIdempotencyConflict",
    "CardCampaignNotFound",
    "CardCampaignNotReady",
    "CardCampaignService",
    "CardCampaignVersionConflict",
]
