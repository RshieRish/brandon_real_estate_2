"""An explicit address refresh keeps unsent card drafts separate from delivery."""

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from models.card_campaign import (
    CardCampaign,
    CardCampaignRecipient,
    CardDeliveryAttempt,
)
from models.command import CRMContact
from models.command_contacts import CRMContactAddress
from schemas.card_campaign import (
    CardCampaignDraftRequest,
    CardCampaignUpdateRequest,
    CardRecipientUpdate,
)
from services.agent_control_command import _celebration_checksum
from services.card_campaign_service import (
    CardCampaignAlreadyAttempted,
    CardCampaignNotReady,
    CardCampaignService,
)
from services.card_provider import DeterministicFakeCardProvider
from tests import test_card_campaign_service as card_service_tests
from tests.test_card_campaign_service import _seed_contacts

card_database = card_service_tests.card_database
card_runtime = card_service_tests.card_runtime


def test_address_refresh_is_an_explicit_strict_boolean_update():
    request = CardCampaignUpdateRequest(
        expected_version=1, refresh_missing_addresses=True
    )
    assert request.refresh_missing_addresses is True
    for invalid in (False, "true", 1, None):
        with pytest.raises(ValidationError):
            CardCampaignUpdateRequest(
                expected_version=1, refresh_missing_addresses=invalid
            )


@pytest.mark.asyncio
async def test_refresh_fills_only_missing_snapshots_preserves_review_and_clears_approval(
    card_runtime,
):
    sessions = card_runtime
    first_id, second_id = await _seed_contacts(sessions)
    provider = DeterministicFakeCardProvider(cost_cents=225)
    service = CardCampaignService(provider=provider)
    request = CardCampaignDraftRequest(request_id=uuid4(), month=9)
    async with sessions() as db:
        draft = await service.create_or_get_draft(db, request)
        missing = next(row for row in draft.recipients if row.contact_id == second_id)
        customized = await service.update_campaign(
            db,
            draft.id,
            CardCampaignUpdateRequest(
                expected_version=draft.version,
                title="Personal September notes",
                recipient_updates=[
                    CardRecipientUpdate(
                        recipient_id=missing.id,
                        message="Your first year by the lake.",
                        design_key="lake-home",
                        excluded=True,
                        exclusion_reason="Review with client first.",
                    )
                ],
            ),
            actor="admin:brandon",
        )
        before = {
            row.id: (row.address_snapshot_json, row.content_hash)
            for row in (
                await db.scalars(
                    sa.select(CardCampaignRecipient).where(
                        CardCampaignRecipient.campaign_id == draft.id
                    )
                )
            ).all()
        }
        original = await db.get(CardCampaign, draft.id)
        original_hash = original.draft_payload_hash
        await db.commit()

    async with sessions() as db:
        first_address = await db.scalar(
            sa.select(CRMContactAddress).where(CRMContactAddress.contact_id == first_id)
        )
        first_address.line1 = "99 New Street"
        db.add(
            CRMContactAddress(
                contact_id=second_id,
                source_key="test:repaired-second",
                line1="2 Main Street",
                city="Lowell",
                state="MA",
                postal_code="01852",
                country="US",
                formatted="2 Main Street, Lowell, MA 01852",
                is_primary=True,
            )
        )
        db.add(
            CRMContact(first_name="New", last_name="Contact", birthday=date(1993, 9, 4))
        )
        await db.commit()

    async with sessions() as db:
        read = await service.get_campaign(db, draft.id)
        assert (
            next(row for row in read.recipients if row.id == missing.id).address_status
            == "missing"
        )
    async with sessions() as db:
        replay = await service.create_or_get_draft(db, request)
        assert (
            next(
                row for row in replay.recipients if row.id == missing.id
            ).address_status
            == "missing"
        )
        stored = await db.get(CardCampaign, draft.id)
        stored.status = "approved"
        stored.approved_by_actor = "admin:brandon"
        stored.approved_at = datetime.now(timezone.utc)
        stored.approved_version = stored.version
        stored.send_request_id = uuid4()
        await db.commit()

    async with sessions() as db:
        refreshed = await service.update_campaign(
            db,
            draft.id,
            CardCampaignUpdateRequest(
                expected_version=customized.version,
                refresh_missing_addresses=True,
            ),
            actor="admin:brandon",
        )
        await db.commit()
        stored = await db.get(CardCampaign, draft.id)
        recipients = (
            await db.scalars(
                sa.select(CardCampaignRecipient).where(
                    CardCampaignRecipient.campaign_id == draft.id
                )
            )
        ).all()
        assert stored.approved_version is None
        assert stored.draft_payload_hash == original_hash
        assert await db.scalar(sa.select(sa.func.count(CardDeliveryAttempt.id))) == 0

    assert refreshed.title == customized.title
    assert refreshed.version == customized.version + 1
    assert refreshed.status == "ready_for_review"
    assert refreshed.approved_at is None
    assert refreshed.approved_by_actor is None
    assert refreshed.send_request_id is None
    assert refreshed.audience_checksum != customized.audience_checksum
    assert refreshed.audience_ref != customized.audience_ref
    assert refreshed.audience_checksum == _celebration_checksum(
        month=draft.month,
        include_birthdays=draft.include_birthdays,
        include_home_anniversaries=draft.include_home_anniversaries,
        selected=tuple(
            (
                row.contact_id,
                row.display_name,
                row.celebration_kind,
                row.celebration_day,
                row.celebration_year,
                row.celebration_year_quality,
                row.celebration_origin,
            )
            for row in draft.recipients
        ),
        address_ready_ids={first_id, second_id},
    )
    assert {row.id for row in refreshed.recipients} == {
        row.id for row in customized.recipients
    }
    assert refreshed.sendable_recipients == 1
    assert refreshed.estimated_cost_cents == 225
    after_missing = next(row for row in refreshed.recipients if row.id == missing.id)
    assert after_missing.address_status == "ready"
    assert after_missing.message == "Your first year by the lake."
    assert after_missing.design_key == "lake-home"
    assert after_missing.excluded is True
    assert after_missing.exclusion_reason == "Review with client first."
    for recipient in recipients:
        old_address, old_hash = before[recipient.id]
        if recipient.id == missing.id:
            assert recipient.address_snapshot_json is not None
            assert recipient.content_hash != old_hash
        else:
            assert (recipient.address_snapshot_json, recipient.content_hash) == (
                old_address,
                old_hash,
            )
    assert provider.send_calls == []


@pytest.mark.asyncio
async def test_refresh_does_not_promote_incomplete_addresses(card_runtime):
    sessions = card_runtime
    _first_id, second_id = await _seed_contacts(sessions)
    provider = DeterministicFakeCardProvider()
    service = CardCampaignService(provider=provider)
    async with sessions() as db:
        draft = await service.create_or_get_draft(
            db, CardCampaignDraftRequest(request_id=uuid4(), month=9)
        )
        db.add(
            CRMContactAddress(
                contact_id=second_id,
                source_key="test:incomplete-address",
                line1="2 Main Street",
                city="Lowell",
                state="MA",
                postal_code=None,
                is_primary=True,
            )
        )
        await db.commit()
    async with sessions() as db:
        refreshed = await service.update_campaign(
            db,
            draft.id,
            CardCampaignUpdateRequest(
                expected_version=draft.version,
                refresh_missing_addresses=True,
            ),
            actor="admin:brandon",
        )
    assert refreshed.status == "needs_addresses"
    assert refreshed.missing_address_count == 1
    assert refreshed.audience_checksum == draft.audience_checksum
    assert refreshed.audience_ref == draft.audience_ref
    assert refreshed.version == draft.version + 1
    assert provider.send_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["sending", "sent", "partially_sent", "failed", "delivery_uncertain"]
)
async def test_refresh_requires_a_review_only_campaign_even_without_attempt_rows(
    card_runtime, status
):
    sessions = card_runtime
    await _seed_contacts(sessions)
    provider = DeterministicFakeCardProvider()
    service = CardCampaignService(provider=provider)
    async with sessions() as db:
        draft = await service.create_or_get_draft(
            db, CardCampaignDraftRequest(request_id=uuid4(), month=9)
        )
        stored = await db.get(CardCampaign, draft.id)
        stored.status = status
        stored.approved_by_actor = "admin:brandon"
        stored.approved_at = datetime.now(timezone.utc)
        stored.approved_version = stored.version
        stored.send_request_id = uuid4()
        await db.commit()
    async with sessions() as db:
        with pytest.raises(CardCampaignNotReady, match="address_refresh_not_allowed"):
            await service.update_campaign(
                db,
                draft.id,
                CardCampaignUpdateRequest(
                    expected_version=draft.version,
                    refresh_missing_addresses=True,
                ),
                actor="admin:brandon",
            )
    assert provider.send_calls == []


@pytest.mark.asyncio
async def test_refresh_cannot_change_a_campaign_after_any_delivery_attempt(
    card_runtime,
):
    sessions = card_runtime
    await _seed_contacts(sessions)
    provider = DeterministicFakeCardProvider()
    service = CardCampaignService(provider=provider)
    async with sessions() as db:
        draft = await service.create_or_get_draft(
            db, CardCampaignDraftRequest(request_id=uuid4(), month=9)
        )
        recipient = await db.get(CardCampaignRecipient, draft.recipients[0].id)
        request_id = uuid4()
        db.add(
            CardDeliveryAttempt(
                campaign_id=draft.id,
                recipient_id=recipient.id,
                request_id=request_id,
                attempt_number=1,
                provider="send_out_cards",
                provider_idempotency_key=uuid4(),
                content_hash=recipient.content_hash,
                intended_by_actor="admin:brandon",
            )
        )
        await db.commit()
    async with sessions() as db:
        with pytest.raises(CardCampaignAlreadyAttempted):
            await service.update_campaign(
                db,
                draft.id,
                CardCampaignUpdateRequest(
                    expected_version=draft.version,
                    refresh_missing_addresses=True,
                ),
                actor="admin:brandon",
            )
    assert provider.send_calls == []
