import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CommandDecodeError } from './http';
import {
  cardsApi,
  decodeCardCampaignDetail,
  decodeCardCampaignPage,
} from './cards';

const COMMAND_BASE_URL = 'http://localhost:8000/api/v1/command';
const CAMPAIGN_ID = '8ea082cb-c9f5-4ddb-95bf-717ca36cb483';
const REQUEST_ID = '68fca6be-1e02-47e6-bf93-242a4a74a620';
const RECIPIENT_ID = '87ad6ee2-86fd-4af1-90cf-4fdd4df7f82e';

const listItem = {
  id: CAMPAIGN_ID,
  title: 'September celebration cards',
  month: 9,
  status: 'needs_addresses',
  total_recipients: 2,
  sendable_recipients: 1,
  missing_address_count: 1,
  estimated_cost_cents: 225,
  currency: 'USD',
  version: 1,
  created_at: '2026-09-04T10:00:00Z',
  updated_at: '2026-09-04T10:05:00+00:00',
};

const detail = {
  ...listItem,
  request_id: REQUEST_ID,
  include_birthdays: true,
  include_home_anniversaries: true,
  audience_ref: 'd593a93a-4b73-4a0d-8890-cff2d57fe344',
  audience_checksum: 'a'.repeat(64),
  birthday_recipients: 1,
  home_anniversary_recipients: 1,
  excluded_recipients: 0,
  provider_connected: false,
  provider_connection_reason: 'contract_required',
  approved_by_actor: null,
  approved_at: null,
  send_request_id: null,
  recipients: [{
    id: RECIPIENT_ID,
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
  }],
};

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('Command card campaign contract', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', { getItem: vi.fn().mockReturnValue('admin-token') });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('decodes an exact campaign page and full recipient evidence', () => {
    expect(decodeCardCampaignPage({ campaigns: [listItem], total: 1 })).toEqual({
      campaigns: [listItem],
      total: 1,
    });
    expect(decodeCardCampaignDetail(detail)).toEqual(detail);
  });

  it.each([
    ['an unknown campaign field', { ...detail, private_note: 'must not cross the boundary' }],
    ['a malformed campaign status', { ...detail, status: 'probably_sent' }],
    ['a negative cost', { ...detail, estimated_cost_cents: -1 }],
    ['a malformed nested recipient', {
      ...detail,
      recipients: [{ ...detail.recipients[0], delivery_outcome: 'maybe' }],
    }],
  ])('rejects %s without echoing response data', (_label, value) => {
    expect(() => decodeCardCampaignDetail(value)).toThrow(CommandDecodeError);
    expect(() => decodeCardCampaignDetail(value)).not.toThrow(/private_note|probably_sent|maybe/);
  });

  it('uses the exact authenticated routes and serialized review mutations', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ campaigns: [listItem], total: 1 }))
      .mockResolvedValueOnce(jsonResponse(detail, 201))
      .mockResolvedValueOnce(jsonResponse(detail))
      .mockResolvedValueOnce(jsonResponse({ ...detail, version: 2 }))
      .mockResolvedValueOnce(jsonResponse({ ...detail, status: 'sent', version: 3 }));
    vi.stubGlobal('fetch', fetchMock);

    await cardsApi.list({ limit: 25, offset: 0 });
    await cardsApi.createDraft({
      request_id: REQUEST_ID,
      month: 9,
      include_birthdays: true,
      include_home_anniversaries: true,
    });
    await cardsApi.get(CAMPAIGN_ID);
    await cardsApi.update(CAMPAIGN_ID, {
      expected_version: 1,
      recipient_updates: [{
        recipient_id: RECIPIENT_ID,
        excluded: true,
        exclusion_reason: 'Mailing address unavailable.',
      }],
    });
    await cardsApi.approveAndSend(CAMPAIGN_ID, {
      request_id: '716af075-2155-4eb7-86cc-6449db26763f',
      expected_version: 2,
      confirmed_recipient_count: 1,
      confirmed_cost_cents: 225,
      confirmed_by_brandon: true,
    });

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `${COMMAND_BASE_URL}/cards/campaigns?limit=25&offset=0`,
      `${COMMAND_BASE_URL}/cards/campaigns/drafts`,
      `${COMMAND_BASE_URL}/cards/campaigns/${CAMPAIGN_ID}`,
      `${COMMAND_BASE_URL}/cards/campaigns/${CAMPAIGN_ID}`,
      `${COMMAND_BASE_URL}/cards/campaigns/${CAMPAIGN_ID}/approve-and-send`,
    ]);
    expect(fetchMock.mock.calls.map(([, init]) => init.method)).toEqual([
      'GET', 'POST', 'GET', 'PATCH', 'POST',
    ]);
    expect(JSON.parse(fetchMock.mock.calls[4]?.[1].body as string)).toEqual({
      request_id: '716af075-2155-4eb7-86cc-6449db26763f',
      expected_version: 2,
      confirmed_recipient_count: 1,
      confirmed_cost_cents: 225,
      confirmed_by_brandon: true,
    });
  });

  it.each([
    ['bad UUID', () => cardsApi.get('not-an-id')],
    ['bad month', () => cardsApi.createDraft({
      request_id: REQUEST_ID,
      month: 13,
      include_birthdays: true,
      include_home_anniversaries: true,
    })],
    ['empty selection', () => cardsApi.createDraft({
      request_id: REQUEST_ID,
      month: 9,
      include_birthdays: false,
      include_home_anniversaries: false,
    })],
  ])('rejects %s before network I/O', (_label, invoke) => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    expect(invoke).toThrow(CommandDecodeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
