import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  CardCampaignDetail,
  CardCampaignPage,
  CardsApi,
} from '@/lib/command/cards';
import { CommandHttpError } from '@/lib/command/http';
import { CardCampaignReview } from './CardCampaignReview';
import { CardCampaignsWorkspace } from './CardCampaignsWorkspace';

const routerPush = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: routerPush }),
}));

const CAMPAIGN_ID = '8ea082cb-c9f5-4ddb-95bf-717ca36cb483';
const RECIPIENT_ONE = '87ad6ee2-86fd-4af1-90cf-4fdd4df7f82e';
const RECIPIENT_TWO = '358bf99f-5b4a-46bb-b700-048acc6f200c';

const readyCampaign: CardCampaignDetail = {
  id: CAMPAIGN_ID,
  request_id: '68fca6be-1e02-47e6-bf93-242a4a74a620',
  title: 'September celebration cards',
  month: 9,
  status: 'ready_for_review',
  total_recipients: 2,
  sendable_recipients: 2,
  missing_address_count: 0,
  estimated_cost_cents: 450,
  currency: 'USD',
  version: 3,
  created_at: '2026-09-04T10:00:00Z',
  updated_at: '2026-09-04T10:05:00Z',
  include_birthdays: true,
  include_home_anniversaries: true,
  audience_ref: 'd593a93a-4b73-4a0d-8890-cff2d57fe344',
  audience_checksum: 'a'.repeat(64),
  birthday_recipients: 1,
  home_anniversary_recipients: 1,
  excluded_recipients: 0,
  provider_connected: true,
  provider_connection_reason: null,
  approved_by_actor: null,
  approved_at: null,
  send_request_id: null,
  recipients: [
    {
      id: RECIPIENT_ONE,
      contact_id: 17,
      display_name: 'Avery Stone',
      celebration_kind: 'birthday',
      celebration_month: 9,
      celebration_day: 14,
      celebration_year: null,
      celebration_year_quality: 'yearless',
      celebration_origin: 'recovered',
      message: 'Happy birthday, Avery!',
      design_key: 'birthday-classic',
      address_status: 'ready',
      address_summary: 'Boston, MA',
      excluded: false,
      exclusion_reason: null,
      delivery_outcome: null,
    },
    {
      id: RECIPIENT_TWO,
      contact_id: 18,
      display_name: 'Jordan Lee',
      celebration_kind: 'home_anniversary',
      celebration_month: 9,
      celebration_day: 22,
      celebration_year: 2021,
      celebration_year_quality: 'verified',
      celebration_origin: 'internal_crm',
      message: 'Happy home anniversary, Jordan!',
      design_key: 'home-anniversary-classic',
      address_status: 'ready',
      address_summary: 'Cambridge, MA',
      excluded: false,
      exclusion_reason: null,
      delivery_outcome: null,
    },
  ],
};

function campaignPage(campaigns: CardCampaignPage['campaigns'] = []): CardCampaignPage {
  return { campaigns, total: campaigns.length };
}

function fakeApi(overrides: Partial<CardsApi> = {}): CardsApi {
  return {
    list: vi.fn().mockResolvedValue(campaignPage([readyCampaign])),
    createDraft: vi.fn().mockResolvedValue(readyCampaign),
    get: vi.fn().mockResolvedValue(readyCampaign),
    update: vi.fn().mockResolvedValue({ ...readyCampaign, version: 4 }),
    approveAndSend: vi.fn().mockResolvedValue({
      ...readyCampaign,
      status: 'sent',
      version: 4,
      approved_by_actor: 'admin:17',
      approved_at: '2026-09-04T10:07:00Z',
      send_request_id: '716af075-2155-4eb7-86cc-6449db26763f',
      recipients: readyCampaign.recipients.map((recipient) => ({
        ...recipient,
        delivery_outcome: 'confirmed' as const,
      })),
    }),
    ...overrides,
  };
}

describe('CardCampaignsWorkspace', () => {
  beforeEach(() => {
    routerPush.mockReset();
  });

  it('shows a bounded loading state, then a premium campaign summary', async () => {
    let resolve!: (value: CardCampaignPage) => void;
    const pending = new Promise<CardCampaignPage>((done) => { resolve = done; });
    const api = fakeApi({ list: vi.fn().mockReturnValue(pending) });

    render(<CardCampaignsWorkspace api={api} />);

    expect(screen.getByRole('status', { name: 'Loading card campaigns' })).toBeInTheDocument();
    resolve(campaignPage([readyCampaign]));

    expect(await screen.findByRole('heading', { name: 'September celebration cards' }))
      .toBeInTheDocument();
    const counts = screen.getByLabelText('Campaign counts');
    expect(counts).toHaveTextContent('2 ready');
    expect(counts).toHaveTextContent('$4.50 estimated');
  });

  it('renders unavailable and first-run states with working recovery actions', async () => {
    const retrying = fakeApi({
      list: vi.fn()
        .mockRejectedValueOnce(new CommandHttpError(503, 'Campaign service unavailable'))
        .mockResolvedValueOnce(campaignPage()),
    });
    const user = userEvent.setup();

    render(<CardCampaignsWorkspace api={retrying} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Card campaigns are unavailable');
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('No card campaigns yet')).toBeInTheDocument();
    expect(retrying.list).toHaveBeenCalledTimes(2);
  });

  it('creates an idempotent September birthday and anniversary draft', async () => {
    const api = fakeApi({ list: vi.fn().mockResolvedValue(campaignPage()) });
    const user = userEvent.setup();
    vi.stubGlobal('crypto', { randomUUID: vi.fn().mockReturnValue(
      '716af075-2155-4eb7-86cc-6449db26763f',
    ) });

    render(<CardCampaignsWorkspace api={api} />);
    await screen.findByText('No card campaigns yet');
    await user.click(screen.getByRole('button', { name: 'Prepare a campaign' }));
    await user.selectOptions(screen.getByLabelText('Celebration month'), '9');
    await user.click(screen.getByRole('button', { name: 'Build review draft' }));

    expect(api.createDraft).toHaveBeenCalledWith({
      request_id: '716af075-2155-4eb7-86cc-6449db26763f',
      month: 9,
      include_birthdays: true,
      include_home_anniversaries: true,
    });
    expect(routerPush).toHaveBeenCalledWith(`/admin/command/cards/${CAMPAIGN_ID}`);
    vi.unstubAllGlobals();
  });
});

describe('CardCampaignReview', () => {
  it('shows disconnected and missing-address gates without offering send', async () => {
    const campaign: CardCampaignDetail = {
      ...readyCampaign,
      status: 'needs_connection',
      provider_connected: false,
      provider_connection_reason: 'contract_required',
      sendable_recipients: 1,
      missing_address_count: 1,
      estimated_cost_cents: 0,
      recipients: [
        { ...readyCampaign.recipients[0], address_status: 'missing', address_summary: null },
        readyCampaign.recipients[1],
      ],
    };

    render(<CardCampaignReview campaignId={CAMPAIGN_ID} api={fakeApi({
      get: vi.fn().mockResolvedValue(campaign),
    })} />);

    expect(await screen.findByText('Send Out Cards is not connected')).toBeInTheDocument();
    expect(screen.getByText('1 mailing address needed')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Avery Stone contact' })).toHaveAttribute(
      'href',
      '/admin/command/contacts/17',
    );
    expect(screen.queryByRole('button', { name: 'Review and send' })).not.toBeInTheDocument();
  });

  it('edits and excludes a recipient with optimistic version protection', async () => {
    const api = fakeApi();
    const user = userEvent.setup();

    render(<CardCampaignReview campaignId={CAMPAIGN_ID} api={api} />);
    const card = await screen.findByRole('article', { name: 'Card for Avery Stone' });
    await user.clear(within(card).getByLabelText('Message for Avery Stone'));
    await user.type(within(card).getByLabelText('Message for Avery Stone'), 'A personal note.');
    await user.click(within(card).getByLabelText('Exclude Avery Stone from this campaign'));
    await user.type(within(card).getByLabelText('Reason for excluding Avery Stone'), 'Requested no mail.');
    await user.click(within(card).getByRole('button', { name: 'Save Avery Stone card' }));

    expect(api.update).toHaveBeenCalledWith(CAMPAIGN_ID, {
      expected_version: 3,
      recipient_updates: [{
        recipient_id: RECIPIENT_ONE,
        message: 'A personal note.',
        design_key: 'birthday-classic',
        excluded: true,
        exclusion_reason: 'Requested no mail.',
      }],
    });
    expect(await screen.findByText('Avery Stone card saved')).toBeInTheDocument();
  });

  it('requires a deliberate confirmation with the exact recipient count and cost', async () => {
    const api = fakeApi();
    const user = userEvent.setup();
    vi.stubGlobal('crypto', { randomUUID: vi.fn().mockReturnValue(
      '716af075-2155-4eb7-86cc-6449db26763f',
    ) });

    render(<CardCampaignReview campaignId={CAMPAIGN_ID} api={api} />);
    await user.click(await screen.findByRole('button', { name: 'Review and send' }));
    const dialog = screen.getByRole('dialog', { name: 'Confirm card order' });
    expect(dialog).toHaveTextContent('2 cards');
    expect(dialog).toHaveTextContent('$4.50');
    const submit = within(dialog).getByRole('button', { name: 'Confirm and send 2 cards' });
    expect(submit).toBeDisabled();
    await user.click(within(dialog).getByLabelText('I confirm 2 cards for $4.50'));
    expect(submit).toBeEnabled();
    await user.click(submit);

    expect(api.approveAndSend).toHaveBeenCalledWith(CAMPAIGN_ID, {
      request_id: '716af075-2155-4eb7-86cc-6449db26763f',
      expected_version: 3,
      confirmed_recipient_count: 2,
      confirmed_cost_cents: 450,
      confirmed_by_brandon: true,
    });
    expect(await screen.findByText('Card order confirmed')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Confirm card order' })).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it('refreshes a stale edit and clearly reports the review conflict', async () => {
    const changed = { ...readyCampaign, version: 4, title: 'Updated September cards' };
    const api = fakeApi({
      get: vi.fn()
        .mockResolvedValueOnce(readyCampaign)
        .mockResolvedValueOnce(changed),
      update: vi.fn().mockRejectedValue(new CommandHttpError(409, 'campaign_stale')),
    });
    const user = userEvent.setup();

    render(<CardCampaignReview campaignId={CAMPAIGN_ID} api={api} />);
    const card = await screen.findByRole('article', { name: 'Card for Avery Stone' });
    await user.click(within(card).getByRole('button', { name: 'Save Avery Stone card' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Campaign changed while you were reviewing it',
    );
    expect(await screen.findByRole('heading', { name: 'Updated September cards' }))
      .toBeInTheDocument();
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it.each([
    ['sending', 'Sending is in progress'],
    ['sent', 'Card order confirmed'],
    ['partially_sent', 'Some cards need attention'],
    ['failed', 'Card order was not completed'],
    ['delivery_uncertain', 'Delivery outcome needs review'],
  ] as const)('renders the %s outcome without an unsafe retry action', async (status, message) => {
    render(<CardCampaignReview campaignId={CAMPAIGN_ID} api={fakeApi({
      get: vi.fn().mockResolvedValue({ ...readyCampaign, status }),
    })} />);

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /retry send/i })).not.toBeInTheDocument();
  });

  it('renders a recoverable unavailable state when the campaign cannot load', async () => {
    const api = fakeApi({
      get: vi.fn()
        .mockRejectedValueOnce(new CommandHttpError(503, 'Unavailable'))
        .mockResolvedValueOnce(readyCampaign),
    });
    const user = userEvent.setup();

    render(<CardCampaignReview campaignId={CAMPAIGN_ID} api={api} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Campaign is unavailable');
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'September celebration cards' }))
      .toBeInTheDocument();
  });
});
