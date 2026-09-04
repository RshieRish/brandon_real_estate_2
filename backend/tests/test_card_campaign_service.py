from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from tests.gmail_task_postgres import async_test_url, migrated_test_database

REVISION = "87a0d9b1e3f2"


@pytest.fixture(scope="module")
def card_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def card_runtime(card_database):
    url, sync_engine = card_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE card_provider_receipts, card_delivery_attempts, "
                "card_campaign_recipients, card_campaigns, "
                "card_provider_connections, crm_reconciliation_results, "
                "crm_reconciliation_runs, crm_contacts CASCADE"
            )
        )
    engine = create_async_engine(async_test_url(url), poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield sessions
    finally:
        await engine.dispose()


async def _seed_contacts(sessions, *, missing_second: bool = True) -> tuple[int, int]:
    from models.command import CRMContact
    from models.command_contacts import CRMContactAddress, CRMContactProfile
    from models.command_provenance import (
        CRMReconciliationResult,
        CRMReconciliationRun,
    )

    async with sessions() as session:
        ready = CRMContact(
            first_name="Avery",
            last_name="Ready",
            stage="lead",
            birthday=date(1990, 9, 8),
        )
        second = CRMContact(
            first_name="Jordan",
            last_name="Second",
            stage="lead",
        )
        session.add_all([ready, second])
        await session.flush()
        session.add(
            CRMContactProfile(
                contact_id=second.id,
                birth_year_quality="unknown",
                anniversary_month=9,
                anniversary_day=21,
                anniversary_year=2018,
                anniversary_year_quality="verified",
            )
        )
        session.add(
            CRMContactAddress(
                contact_id=ready.id,
                source_key="test:ready",
                line1="1 Main Street",
                city="Boston",
                state="MA",
                postal_code="02108",
                country="US",
                formatted="1 Main Street, Boston, MA 02108",
                is_primary=True,
            )
        )
        if not missing_second:
            session.add(
                CRMContactAddress(
                    contact_id=second.id,
                    source_key="test:second",
                    line1="2 Main Street",
                    city="Lowell",
                    state="MA",
                    postal_code="01852",
                    country="US",
                    formatted="2 Main Street, Lowell, MA 01852",
                    is_primary=True,
                )
            )
        run = CRMReconciliationRun(
            bundle_fingerprint="e" * 64,
            parser_version="contacts-v1",
            mode="apply",
            status="completed",
            requested_modules_json='["contacts"]',
            error_text="",
            started_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
            completed_at=datetime(2026, 9, 4, 0, 5, tzinfo=timezone.utc),
        )
        session.add(run)
        await session.flush()
        session.add(
            CRMReconciliationResult(
                run_id=run.id,
                source_system="kw_command",
                module="contacts",
                expected_count=2,
                observed_count=2,
                rendered_count=2,
                normalized_count=2,
                evidence_only_count=0,
                unmatched_count=0,
                duplicate_content_count=0,
                error_count=0,
                details_json="{}",
            )
        )
        await session.commit()
        return ready.id, second.id


@pytest.mark.asyncio
async def test_draft_is_idempotent_tracks_missing_addresses_and_updates_optimistically(
    card_runtime,
):
    from schemas.card_campaign import (
        CardCampaignDraftRequest,
        CardCampaignUpdateRequest,
        CardRecipientUpdate,
    )
    from services.card_campaign_service import (
        CardCampaignIdempotencyConflict,
        CardCampaignService,
        CardCampaignVersionConflict,
    )
    from services.card_provider import DeterministicFakeCardProvider

    sessions = card_runtime
    await _seed_contacts(sessions)
    provider = DeterministicFakeCardProvider(cost_cents=225)
    service = CardCampaignService(provider=provider)
    request_id = uuid4()
    payload = CardCampaignDraftRequest(request_id=request_id, month=9)

    async with sessions() as session:
        first = await service.create_or_get_draft(session, payload)
        await session.commit()
    assert first.status == "needs_addresses"
    assert first.total_recipients == 2
    assert first.sendable_recipients == 1
    assert first.missing_address_count == 1
    assert first.estimated_cost_cents == 225
    assert {recipient.celebration_kind for recipient in first.recipients} == {
        "birthday",
        "home_anniversary",
    }
    assert all("{first_name}" not in row.message for row in first.recipients)

    async with sessions() as session:
        repeated = await service.create_or_get_draft(session, payload)
        await session.commit()
    assert repeated.id == first.id
    assert repeated.version == first.version
    async with sessions() as session:
        assert (
            await session.scalar(
                sa.text("SELECT count(*) FROM card_campaign_recipients")
            )
            == 2
        )

    with pytest.raises(CardCampaignIdempotencyConflict):
        async with sessions() as session:
            await service.create_or_get_draft(
                session,
                CardCampaignDraftRequest(
                    request_id=request_id,
                    month=10,
                ),
            )

    missing = next(row for row in first.recipients if row.address_status == "missing")
    with pytest.raises(CardCampaignVersionConflict):
        async with sessions() as session:
            await service.update_campaign(
                session,
                first.id,
                CardCampaignUpdateRequest(
                    expected_version=first.version + 1,
                    title="Wrong version",
                ),
                actor="admin:test",
            )

    async with sessions() as session:
        updated = await service.update_campaign(
            session,
            first.id,
            CardCampaignUpdateRequest(
                expected_version=first.version,
                recipient_updates=[
                    CardRecipientUpdate(
                        recipient_id=missing.id,
                        excluded=True,
                        exclusion_reason="Mailing address unavailable.",
                    )
                ],
            ),
            actor="admin:test",
        )
        await session.commit()
    assert updated.status == "ready_for_review"
    assert updated.excluded_recipients == 1
    assert updated.sendable_recipients == 1
    assert updated.version == first.version + 1


@pytest.mark.asyncio
async def test_disabled_provider_keeps_draft_and_performs_zero_external_io(
    card_runtime,
):
    from schemas.card_campaign import (
        CardCampaignApproveRequest,
        CardCampaignDraftRequest,
    )
    from services.card_campaign_service import (
        CardCampaignNotReady,
        CardCampaignService,
    )
    from services.card_provider import DisabledCardProvider

    sessions = card_runtime
    await _seed_contacts(sessions, missing_second=False)
    provider = DisabledCardProvider(reason="contract_required")
    service = CardCampaignService(provider=provider)
    async with sessions() as session:
        campaign = await service.create_or_get_draft(
            session,
            CardCampaignDraftRequest(request_id=uuid4(), month=9),
        )
        await session.commit()
    assert campaign.status == "needs_connection"
    assert campaign.provider_connected is False

    with pytest.raises(CardCampaignNotReady, match="provider_not_connected"):
        async with sessions() as session:
            await service.approve_and_send(
                session,
                campaign.id,
                CardCampaignApproveRequest(
                    request_id=uuid4(),
                    expected_version=campaign.version,
                    confirmed_recipient_count=2,
                    confirmed_cost_cents=0,
                    confirmed_by_brandon=True,
                ),
                actor="admin:brandon",
            )
    assert provider.send_calls == []

    from services.card_provider import DeterministicFakeCardProvider

    connected_service = CardCampaignService(
        provider=DeterministicFakeCardProvider(cost_cents=200)
    )
    async with sessions() as session:
        refreshed = await connected_service.create_or_get_draft(
            session,
            CardCampaignDraftRequest(
                request_id=campaign.request_id,
                month=9,
            ),
        )
        await session.commit()
    assert refreshed.status == "ready_for_review"
    assert refreshed.version == campaign.version + 1


@pytest.mark.asyncio
async def test_edit_invalidates_an_unsubmitted_approval(card_runtime):
    from models.card_campaign import CardCampaign
    from schemas.card_campaign import (
        CardCampaignDraftRequest,
        CardCampaignUpdateRequest,
    )
    from services.card_campaign_service import CardCampaignService
    from services.card_provider import DeterministicFakeCardProvider

    sessions = card_runtime
    await _seed_contacts(sessions, missing_second=False)
    service = CardCampaignService(provider=DeterministicFakeCardProvider())
    async with sessions() as session:
        campaign = await service.create_or_get_draft(
            session,
            CardCampaignDraftRequest(request_id=uuid4(), month=9),
        )
        stored = await session.get(CardCampaign, campaign.id)
        assert stored is not None
        stored.status = "approved"
        stored.approved_by_actor = "admin:brandon"
        stored.approved_at = datetime.now(timezone.utc)
        stored.approved_version = stored.version
        stored.send_request_id = uuid4()
        await session.commit()

    async with sessions() as session:
        updated = await service.update_campaign(
            session,
            campaign.id,
            CardCampaignUpdateRequest(
                expected_version=campaign.version,
                title="Revised September celebrations",
            ),
            actor="admin:brandon",
        )
        await session.commit()
    assert updated.status == "ready_for_review"
    assert updated.approved_by_actor is None
    assert updated.approved_at is None
    assert updated.send_request_id is None
    assert updated.version == campaign.version + 1


@pytest.mark.asyncio
async def test_send_commits_immutable_intent_before_io_and_replay_is_idempotent(
    card_runtime,
):
    from schemas.card_campaign import (
        CardCampaignApproveRequest,
        CardCampaignDraftRequest,
        CardCampaignUpdateRequest,
        CardRecipientUpdate,
    )
    from services.card_campaign_service import CardCampaignService
    from services.card_provider import DeterministicFakeCardProvider

    sessions = card_runtime
    await _seed_contacts(sessions)
    observed: list[tuple[int, str]] = []

    async def before_send(_request):
        async with sessions() as verification:
            count = await verification.scalar(
                sa.text("SELECT count(*) FROM card_delivery_attempts")
            )
            state = await verification.scalar(
                sa.text("SELECT status FROM card_campaigns")
            )
            observed.append((int(count or 0), str(state)))

    provider = DeterministicFakeCardProvider(
        outcomes=("confirmed",),
        cost_cents=250,
        before_send=before_send,
    )
    service = CardCampaignService(provider=provider)
    async with sessions() as session:
        draft = await service.create_or_get_draft(
            session,
            CardCampaignDraftRequest(request_id=uuid4(), month=9),
        )
        missing = next(
            row for row in draft.recipients if row.address_status == "missing"
        )
        ready = await service.update_campaign(
            session,
            draft.id,
            CardCampaignUpdateRequest(
                expected_version=draft.version,
                recipient_updates=[
                    CardRecipientUpdate(
                        recipient_id=missing.id,
                        excluded=True,
                        exclusion_reason="No verified mailing address.",
                    )
                ],
            ),
            actor="admin:brandon",
        )
        await session.commit()

    request = CardCampaignApproveRequest(
        request_id=uuid4(),
        expected_version=ready.version,
        confirmed_recipient_count=1,
        confirmed_cost_cents=250,
        confirmed_by_brandon=True,
    )
    async with sessions() as session:
        sent = await service.approve_and_send(
            session,
            draft.id,
            request,
            actor="admin:brandon",
        )
    assert sent.status == "sent"
    assert observed == [(1, "sending")]
    assert len(provider.send_calls) == 1
    async with sessions() as session:
        assert (
            await session.scalar(sa.text("SELECT count(*) FROM card_delivery_attempts"))
            == 1
        )
        assert (
            await session.scalar(sa.text("SELECT count(*) FROM card_provider_receipts"))
            == 1
        )

    async with sessions() as session:
        replayed = await service.approve_and_send(
            session,
            draft.id,
            request,
            actor="admin:brandon",
        )
    assert replayed.status == "sent"
    assert len(provider.send_calls) == 1


@pytest.mark.asyncio
async def test_ambiguous_delivery_is_preserved_and_never_automatically_retried(
    card_runtime,
):
    from schemas.card_campaign import (
        CardCampaignApproveRequest,
        CardCampaignDraftRequest,
    )
    from services.card_campaign_service import (
        CardCampaignAlreadyAttempted,
        CardCampaignService,
    )
    from services.card_provider import DeterministicFakeCardProvider

    sessions = card_runtime
    await _seed_contacts(sessions, missing_second=False)
    provider = DeterministicFakeCardProvider(outcomes=("ambiguous", "confirmed"))
    service = CardCampaignService(provider=provider)
    async with sessions() as session:
        campaign = await service.create_or_get_draft(
            session,
            CardCampaignDraftRequest(
                request_id=uuid4(),
                month=9,
                include_home_anniversaries=False,
            ),
        )
        await session.commit()
    request = CardCampaignApproveRequest(
        request_id=uuid4(),
        expected_version=campaign.version,
        confirmed_recipient_count=1,
        confirmed_cost_cents=200,
        confirmed_by_brandon=True,
    )
    async with sessions() as session:
        uncertain = await service.approve_and_send(
            session,
            campaign.id,
            request,
            actor="admin:brandon",
        )
    assert uncertain.status == "delivery_uncertain"
    assert len(provider.send_calls) == 1

    async with sessions() as session:
        replayed = await service.approve_and_send(
            session,
            campaign.id,
            request,
            actor="admin:brandon",
        )
    assert replayed.status == "delivery_uncertain"
    assert len(provider.send_calls) == 1

    with pytest.raises(CardCampaignAlreadyAttempted):
        async with sessions() as session:
            await service.approve_and_send(
                session,
                campaign.id,
                request.model_copy(update={"request_id": uuid4()}),
                actor="admin:brandon",
            )
    assert len(provider.send_calls) == 1


@pytest.mark.parametrize(
    ("outcomes", "expected_status"),
    [
        (("confirmed", "rejected"), "partially_sent"),
        (("rejected", "rejected"), "failed"),
    ],
)
@pytest.mark.asyncio
async def test_classified_provider_outcomes_set_truthful_terminal_status(
    card_runtime,
    outcomes,
    expected_status,
):
    from schemas.card_campaign import (
        CardCampaignApproveRequest,
        CardCampaignDraftRequest,
    )
    from services.card_campaign_service import CardCampaignService
    from services.card_provider import DeterministicFakeCardProvider

    sessions = card_runtime
    await _seed_contacts(sessions, missing_second=False)
    provider = DeterministicFakeCardProvider(outcomes=outcomes, cost_cents=200)
    service = CardCampaignService(provider=provider)
    async with sessions() as session:
        campaign = await service.create_or_get_draft(
            session,
            CardCampaignDraftRequest(request_id=uuid4(), month=9),
        )
        await session.commit()
    async with sessions() as session:
        result = await service.approve_and_send(
            session,
            campaign.id,
            CardCampaignApproveRequest(
                request_id=uuid4(),
                expected_version=campaign.version,
                confirmed_recipient_count=2,
                confirmed_cost_cents=400,
                confirmed_by_brandon=True,
            ),
            actor="admin:brandon",
        )

    assert result.status == expected_status
    assert [row.delivery_outcome for row in result.recipients] == list(outcomes)
