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
  it('copies updated contact addresses only after an explicit review action and never sends', async () => {
    const missing: CardCampaignDetail = {
      ...readyCampaign, status: 'needs_addresses', missing_address_count: 1,
      sendable_recipients: 1, recipients: [
        { ...readyCampaign.recipients[0], address_status: 'missing', address_summary: null },
        readyCampaign.recipients[1],
      ],
    };
    const api = fakeApi({ get: vi.fn().mockResolvedValue(missing) });
    const user = userEvent.setup();
    render(<CardCampaignReview campaignId={CAMPAIGN_ID} api={api} />);
    const refresh = await screen.findByRole('button', { name: 'Check updated addresses' });
    expect(api.update).not.toHaveBeenCalled();
    await user.click(refresh);
    expect(api.update).toHaveBeenCalledWith(CAMPAIGN_ID, {
      expected_version: 3, refresh_missing_addresses: true,
    });
    expect(await screen.findByText('Mailing addresses checked. Review the draft before approving.')).toBeInTheDocument();
    expect(api.approveAndSend).not.toHaveBeenCalled();
  });

  it('preserves unsaved card edits when only address snapshots are refreshed', async () => {
    const missing: CardCampaignDetail = {
      ...readyCampaign, status: 'needs_addresses', missing_address_count: 1,
      sendable_recipients: 1, recipients: [
        { ...readyCampaign.recipients[0], address_status: 'missing', address_summary: null },
        readyCampaign.recipients[1],
      ],
    };
    const api = fakeApi({ get: vi.fn().mockResolvedValue(missing) });
    const user = userEvent.setup();
    render(<CardCampaignReview campaignId={CAMPAIGN_ID} api={api} />);
    const card = await screen.findByRole('article', { name: 'Card for Avery Stone' });
    const message = within(card).getByRole('textbox', { name: 'Message for Avery Stone' });
    await user.clear(message);
    await user.type(message, 'Looking forward to celebrating with you.');
    await user.click(within(card).getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Check updated addresses' }));
    await screen.findByText('Mailing addresses checked. Review the draft before approving.');
    expect(message).toHaveValue('Looking forward to celebrating with you.');
    expect(within(card).getByRole('checkbox')).toBeChecked();
    expect(within(card).getByRole('textbox', { name: 'Reason for excluding Avery Stone' }))
      .toHaveValue('Mailing address unavailable.');
    expect(api.approveAndSend).not.toHaveBeenCalled();
  });

  it('recovers an address refresh version conflict without automatically retrying the update', async () => {
    const missing = {
      ...readyCampaign, status: 'needs_addresses' as const, missing_address_count: 1,
      recipients: [{ ...readyCampaign.recipients[0], address_status: 'missing' as const, address_summary: null }],
    };
    const api = fakeApi({
      get: vi.fn().mockResolvedValueOnce(missing).mockResolvedValueOnce({ ...missing, version: 4 }),
      update: vi.fn().mockRejectedValue(new CommandHttpError(409, 'campaign_stale')),
    });
    const user = userEvent.setup();
    render(<CardCampaignReview campaignId={CAMPAIGN_ID} api={api} />);
    await user.click(await screen.findByRole('button', { name: 'Check updated addresses' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Campaign changed while addresses were being checked');
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(api.update).toHaveBeenCalledTimes(1);
    expect(api.approveAndSend).not.toHaveBeenCalled();
  });

  it('keeps dirty fields while merging untouched server fields after an address refresh conflict', async () => {
    const missing: CardCampaignDetail = {
      ...readyCampaign, status: 'needs_addresses', missing_address_count: 1,
      recipients: [
        { ...readyCampaign.recipients[0], address_status: 'missing', address_summary: null },
        readyCampaign.recipients[1],
      ],
    };
    const authoritative: CardCampaignDetail = {
      ...missing, version: 4,
      recipients: [
        { ...missing.recipients[0], message: 'Updated in another tab.', design_key: 'birthday-gold' },
        { ...missing.recipients[1], message: 'A newer anniversary note.' },
      ],
    };
    const api = fakeApi({
      get: vi.fn().mockResolvedValueOnce(missing).mockResolvedValueOnce(authoritative),
      update: vi.fn().mockRejectedValue(new CommandHttpError(409, 'campaign_stale')),
    });
    const user = userEvent.setup();
    render(<CardCampaignReview campaignId={CAMPAIGN_ID} api={api} />);
    const card = await screen.findByRole('article', { name: 'Card for Avery Stone' });
    const message = within(card).getByRole('textbox', { name: 'Message for Avery Stone' });
    await user.clear(message);
    await user.type(message, 'Keep my personal note.');
    await user.click(within(card).getByRole('checkbox'));
    const reason = within(card).getByRole('textbox', { name: 'Reason for excluding Avery Stone' });
    await user.clear(reason);
    await user.type(reason, 'Confirm with Avery first.');
    await user.click(screen.getByRole('button', { name: 'Check updated addresses' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Campaign changed while addresses were being checked');
    expect(message).toHaveValue('Keep my personal note.');
    expect(within(card).getByRole('textbox', { name: 'Design key' })).toHaveValue('birthday-gold');
    expect(within(card).getByRole('checkbox')).toBeChecked();
    expect(reason).toHaveValue('Confirm with Avery first.');
    expect(screen.getByRole('textbox', { name: 'Message for Jordan Lee' })).toHaveValue('A newer anniversary note.');
    expect(screen.getByRole('alert')).toHaveTextContent('Unsaved edits are kept');
    expect(api.update).toHaveBeenCalledTimes(1);
    expect(api.approveAndSend).not.toHaveBeenCalled();
  });

  it('keeps an unsaved design after a conflicting server design and message update', async () => {
    const missing: CardCampaignDetail = {
      ...readyCampaign, status: 'needs_addresses', missing_address_count: 1,
      recipients: [{ ...readyCampaign.recipients[0], address_status: 'missing', address_summary: null }],
    };
    const api = fakeApi({
      get: vi.fn().mockResolvedValueOnce(missing).mockResolvedValueOnce({
        ...missing, version: 4,
        recipients: [{ ...missing.recipients[0], message: 'Updated server note.', design_key: 'server-design' }],
      }),
      update: vi.fn().mockRejectedValue(new CommandHttpError(409, 'campaign_stale')),
    });
    const user = userEvent.setup();
    render(<CardCampaignReview campaignId={CAMPAIGN_ID} api={api} />);
    const card = await screen.findByRole('article', { name: 'Card for Avery Stone' });
    const design = within(card).getByRole('textbox', { name: 'Design key' });
    await user.clear(design);
    await user.type(design, 'my-personal-design');
    await user.click(screen.getByRole('button', { name: 'Check updated addresses' }));

    await screen.findByRole('alert');
    expect(design).toHaveValue('my-personal-design');
    expect(within(card).getByRole('textbox', { name: 'Message for Avery Stone' })).toHaveValue('Updated server note.');
    expect(api.update).toHaveBeenCalledTimes(1);
    expect(api.approveAndSend).not.toHaveBeenCalled();
  });

  it('locks other actions during address refresh and reports a failed check without sending', async () => {
    const missing: CardCampaignDetail = {
      ...readyCampaign, excluded_recipients: 1, sendable_recipients: 1,
      recipients: [
        {
          ...readyCampaign.recipients[0], address_status: 'missing', address_summary: null,
          excluded: true, exclusion_reason: 'Review with client first.',
        },
        readyCampaign.recipients[1],
      ],
    };
    let reject!: (reason: Error) => void;
    const pending = new Promise<CardCampaignDetail>((_resolve, fail) => { reject = fail; });
    const api = fakeApi({ get: vi.fn().mockResolvedValue(missing), update: vi.fn().mockReturnValue(pending) });
    const user = userEvent.setup();
    render(<CardCampaignReview campaignId={CAMPAIGN_ID} api={api} />);
    await user.click(await screen.findByRole('button', { name: 'Check updated addresses' }));
    expect(screen.getByRole('button', { name: 'Checking addresses…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Review and send' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save Jordan Lee card' })).toBeDisabled();
    reject(new CommandHttpError(503, 'unavailable'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Mailing addresses could not be checked. Nothing was sent.');
    expect(screen.getByRole('button', { name: 'Check updated addresses' })).toBeEnabled();
    expect(api.update).toHaveBeenCalledTimes(1);
    expect(api.approveAndSend).not.toHaveBeenCalled();
  });

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
    expect(screen.queryByRole('button', { name: 'Check updated addresses' })).not.toBeInTheDocument();
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
