import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  commandApi,
  CommandOutcomeUncertainError,
  contactsApi,
} from './api';
import { CommandDecodeError } from './http';

const legacyContact = {
  id: 7,
  first_name: 'Avery',
  last_name: 'Stone',
  email: null,
  phone: '+1 555 0107',
  lead_id: null,
  birthday: null,
  anniversary: '2020-02-29',
  stage: 'lead',
};

const directoryPage = {
  rows: [],
  total: 0,
  page: 1,
  page_size: 25,
  page_count: 0,
  sort: 'name',
  direction: 'asc',
};

describe('commandApi', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('keeps the complete compatibility method inventory alongside the decoded contact adapters', () => {
    expect(Object.keys(commandApi)).toEqual([
      'overview',
      'contacts',
      'contactDirectory',
      'tasks',
      'celebrations',
      'createContactNote',
      'createContactSavedSearch',
      'savedSearches',
      'deleteSavedSearch',
      'createTag',
      'assignContactTag',
      'removeContactTag',
      'deleteContactNote',
      'goals',
      'createGoal',
      'updateGoalProgress',
      'aiBriefing',
      'generateAiBriefing',
      'createContact',
      'importContacts',
      'importArchiveBundle',
      'updateContactStage',
      'updateContact',
      'smartPlans',
      'createSmartPlan',
      'updateSmartPlanStatus',
      'smartPlanWorkspace',
      'addSmartPlanStep',
      'updateSmartPlanStep',
      'enrollSmartPlanContact',
      'updateSmartPlanEnrollment',
      'opportunities',
      'createOpportunity',
      'updateOpportunity',
      'opportunityWorkspace',
      'addOpportunityContact',
      'addOpportunityVendor',
      'addOpportunityOffer',
      'agreements',
      'createAgreement',
      'agreementWorkspace',
      'updateAgreementStatus',
      'addAgreementRecipient',
      'agreementTemplates',
      'createAgreementTemplate',
      'updateAgreementTemplate',
      'listings',
      'createListing',
      'updateListingStatus',
      'geocodeListing',
      'referrals',
      'createReferral',
      'updateReferralStatus',
      'marketingRecords',
      'websiteRecords',
      'eventBreakdown',
      'reportsSummary',
      'archiveArtifacts',
      'archiveArtifactBlob',
      'reportDetails',
      'createTask',
      'addTaskLink',
      'taskLinks',
      'updateTask',
      'archiveTask',
      'bulkArchiveTasks',
      'restoreTask',
    ]);
  });

  it('retains unchecked request transport and exact URLs for every unrelated read adapter', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-retained-reads' });
    const payload = { private_payload: 'retained-unchecked-result' };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => payload });
    vi.stubGlobal('fetch', fetchMock);
    const cases: readonly Readonly<{
      name: string;
      invoke: () => Promise<unknown>;
      path: string;
    }>[] = [
      { name: 'overview', invoke: () => commandApi.overview(), path: '/overview' },
      { name: 'savedSearches', invoke: () => commandApi.savedSearches(), path: '/saved-searches' },
      { name: 'goals', invoke: () => commandApi.goals(), path: '/goals' },
      { name: 'aiBriefing', invoke: () => commandApi.aiBriefing(), path: '/ai/briefing' },
      { name: 'smartPlans', invoke: () => commandApi.smartPlans(), path: '/smart-plans' },
      { name: 'smartPlanWorkspace', invoke: () => commandApi.smartPlanWorkspace(7), path: '/smart-plans/7/workspace' },
      { name: 'opportunities', invoke: () => commandApi.opportunities(), path: '/opportunities' },
      { name: 'opportunityWorkspace', invoke: () => commandApi.opportunityWorkspace(7), path: '/opportunities/7/workspace' },
      { name: 'agreements', invoke: () => commandApi.agreements(), path: '/agreements' },
      { name: 'agreementWorkspace', invoke: () => commandApi.agreementWorkspace(7), path: '/agreements/7/workspace' },
      { name: 'agreementTemplates', invoke: () => commandApi.agreementTemplates(), path: '/agreement-templates' },
      { name: 'listings', invoke: () => commandApi.listings({ query: 'Main', status: 'active' }), path: '/listings?query=Main&status=active' },
      { name: 'referrals', invoke: () => commandApi.referrals(), path: '/referrals' },
      { name: 'marketingRecords', invoke: () => commandApi.marketingRecords(), path: '/marketing/records' },
      { name: 'websiteRecords', invoke: () => commandApi.websiteRecords(), path: '/websites/records' },
      { name: 'eventBreakdown', invoke: () => commandApi.eventBreakdown(), path: '/reports/event-breakdown' },
      { name: 'reportsSummary', invoke: () => commandApi.reportsSummary(), path: '/reports/summary' },
      { name: 'archiveArtifacts', invoke: () => commandApi.archiveArtifacts('contacts', 3), path: '/archive/artifacts?limit=100&offset=3&domain=contacts' },
      { name: 'reportDetails', invoke: () => commandApi.reportDetails('contact health'), path: '/reports/details/contact%20health' },
    ];

    for (const item of cases) {
      fetchMock.mockClear();
      await expect(item.invoke()).resolves.toBe(payload);
      expect(fetchMock.mock.calls[0]?.[0], item.name).toBe(
        `http://localhost:8000/api/v1/command${item.path}`,
      );
    }
  });

  it('retains unchecked request transport and exact requests for every unrelated mutation adapter', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-retained-mutations' });
    const payload = { private_payload: 'retained-unchecked-result' };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => payload });
    vi.stubGlobal('fetch', fetchMock);
    const cases: readonly Readonly<{
      name: string;
      invoke: () => Promise<unknown>;
      path: string;
      method: 'POST' | 'PATCH' | 'DELETE';
      body?: string;
    }>[] = [
      { name: 'createContactNote', invoke: () => commandApi.createContactNote(7, 'Note'), path: '/contacts/7/notes', method: 'POST', body: JSON.stringify({ body: 'Note' }) },
      { name: 'createContactSavedSearch', invoke: () => commandApi.createContactSavedSearch(7, 'Search', { stage: 'lead' }), path: '/contacts/7/saved-searches', method: 'POST', body: JSON.stringify({ name: 'Search', criteria: { stage: 'lead' } }) },
      { name: 'deleteSavedSearch', invoke: () => commandApi.deleteSavedSearch(7), path: '/saved-searches/7', method: 'DELETE' },
      { name: 'createTag', invoke: () => commandApi.createTag('Buyer'), path: '/tags', method: 'POST', body: JSON.stringify({ name: 'Buyer' }) },
      { name: 'assignContactTag', invoke: () => commandApi.assignContactTag(7, 8), path: '/contacts/7/tags/8', method: 'POST' },
      { name: 'removeContactTag', invoke: () => commandApi.removeContactTag(7, 8), path: '/contacts/7/tags/8', method: 'DELETE' },
      { name: 'deleteContactNote', invoke: () => commandApi.deleteContactNote(7, 8), path: '/contacts/7/notes/8', method: 'DELETE' },
      { name: 'createGoal', invoke: () => commandApi.createGoal({ name: 'Closings', target_value: 2, current_value: 0, period: 'monthly' }), path: '/goals', method: 'POST', body: JSON.stringify({ name: 'Closings', target_value: 2, current_value: 0, period: 'monthly' }) },
      { name: 'updateGoalProgress', invoke: () => commandApi.updateGoalProgress(7, 2), path: '/goals/7', method: 'PATCH', body: JSON.stringify({ current_value: 2 }) },
      { name: 'generateAiBriefing', invoke: () => commandApi.generateAiBriefing(), path: '/ai/briefing/generate', method: 'POST' },
      { name: 'createContact', invoke: () => commandApi.createContact({ first_name: 'Avery', last_name: '', email: null, phone: null }), path: '/contacts', method: 'POST', body: JSON.stringify({ first_name: 'Avery', last_name: '', email: null, phone: null }) },
      { name: 'importContacts', invoke: () => commandApi.importContacts([{ first_name: 'Avery', last_name: '', email: null, phone: null }]), path: '/contacts/import', method: 'POST', body: JSON.stringify({ contacts: [{ first_name: 'Avery', last_name: '', email: null, phone: null }] }) },
      { name: 'importArchiveBundle', invoke: () => commandApi.importArchiveBundle({ contacts: [] }), path: '/archive/import', method: 'POST', body: JSON.stringify({ contacts: [] }) },
      { name: 'updateContactStage', invoke: () => commandApi.updateContactStage(7, 'client'), path: '/contacts/7', method: 'PATCH', body: JSON.stringify({ stage: 'client' }) },
      { name: 'updateContact', invoke: () => commandApi.updateContact(7, { phone: null }), path: '/contacts/7', method: 'PATCH', body: JSON.stringify({ phone: null }) },
      { name: 'createSmartPlan', invoke: () => commandApi.createSmartPlan({ name: 'Plan', description: '' }), path: '/smart-plans', method: 'POST', body: JSON.stringify({ name: 'Plan', description: '' }) },
      { name: 'updateSmartPlanStatus', invoke: () => commandApi.updateSmartPlanStatus(7, 'paused'), path: '/smart-plans/7', method: 'PATCH', body: JSON.stringify({ status: 'paused' }) },
      { name: 'addSmartPlanStep', invoke: () => commandApi.addSmartPlanStep(7, 1, 'call', { title: 'Call' }), path: '/smart-plans/7/steps', method: 'POST', body: JSON.stringify({ position: 1, action_type: 'call', payload: { title: 'Call' } }) },
      { name: 'updateSmartPlanStep', invoke: () => commandApi.updateSmartPlanStep(7, 8, 2, 'email', { subject: 'Hi' }), path: '/smart-plans/7/steps/8', method: 'PATCH', body: JSON.stringify({ position: 2, action_type: 'email', payload: { subject: 'Hi' } }) },
      { name: 'enrollSmartPlanContact', invoke: () => commandApi.enrollSmartPlanContact(7, 9), path: '/smart-plans/7/enrollments', method: 'POST', body: JSON.stringify({ contact_id: 9 }) },
      { name: 'updateSmartPlanEnrollment', invoke: () => commandApi.updateSmartPlanEnrollment(7, 8, 'paused'), path: '/smart-plans/7/enrollments/8', method: 'PATCH', body: JSON.stringify({ status: 'paused' }) },
      { name: 'createOpportunity', invoke: () => commandApi.createOpportunity({ name: 'Listing', stage: 'active', value_cents: null }), path: '/opportunities', method: 'POST', body: JSON.stringify({ name: 'Listing', stage: 'active', value_cents: null }) },
      { name: 'updateOpportunity', invoke: () => commandApi.updateOpportunity(7, 'offer'), path: '/opportunities/7', method: 'PATCH', body: JSON.stringify({ stage: 'offer' }) },
      { name: 'addOpportunityContact', invoke: () => commandApi.addOpportunityContact(7, 8, 'buyer'), path: '/opportunities/7/contacts', method: 'POST', body: JSON.stringify({ contact_id: 8, role: 'buyer' }) },
      { name: 'addOpportunityVendor', invoke: () => commandApi.addOpportunityVendor(7, 'Vendor', 'inspector'), path: '/opportunities/7/vendors', method: 'POST', body: JSON.stringify({ name: 'Vendor', role: 'inspector' }) },
      { name: 'addOpportunityOffer', invoke: () => commandApi.addOpportunityOffer(7, 100_000, 'draft'), path: '/opportunities/7/offers', method: 'POST', body: JSON.stringify({ amount_cents: 100_000, status: 'draft' }) },
      { name: 'createAgreement', invoke: () => commandApi.createAgreement({ title: 'Agreement', contact_id: null }), path: '/agreements', method: 'POST', body: JSON.stringify({ title: 'Agreement', contact_id: null }) },
      { name: 'updateAgreementStatus', invoke: () => commandApi.updateAgreementStatus(7, 'ready'), path: '/agreements/7/status', method: 'PATCH', body: JSON.stringify({ status: 'ready' }) },
      { name: 'addAgreementRecipient', invoke: () => commandApi.addAgreementRecipient(7, 'Avery', 'avery@example.test', 'signer'), path: '/agreements/7/recipients', method: 'POST', body: JSON.stringify({ name: 'Avery', email: 'avery@example.test', role: 'signer' }) },
      { name: 'createAgreementTemplate', invoke: () => commandApi.createAgreementTemplate('Buyer', 'Body'), path: '/agreement-templates', method: 'POST', body: JSON.stringify({ name: 'Buyer', body: 'Body' }) },
      { name: 'updateAgreementTemplate', invoke: () => commandApi.updateAgreementTemplate(7, 'Body'), path: '/agreement-templates/7', method: 'PATCH', body: JSON.stringify({ body: 'Body' }) },
      { name: 'createListing', invoke: () => commandApi.createListing({ address: '10 Main St', latitude: null, longitude: null }), path: '/listings', method: 'POST', body: JSON.stringify({ address: '10 Main St', latitude: null, longitude: null }) },
      { name: 'updateListingStatus', invoke: () => commandApi.updateListingStatus(7, 'pending'), path: '/listings/7', method: 'PATCH', body: JSON.stringify({ status: 'pending' }) },
      { name: 'geocodeListing', invoke: () => commandApi.geocodeListing(7), path: '/listings/7/geocode', method: 'POST' },
      { name: 'createReferral', invoke: () => commandApi.createReferral({ name: 'Referral', source: 'Partner', contact_id: null }), path: '/referrals', method: 'POST', body: JSON.stringify({ name: 'Referral', source: 'Partner', contact_id: null }) },
      { name: 'updateReferralStatus', invoke: () => commandApi.updateReferralStatus(7, 'contacted'), path: '/referrals/7', method: 'PATCH', body: JSON.stringify({ status: 'contacted' }) },
    ];

    for (const item of cases) {
      fetchMock.mockClear();
      await expect(item.invoke()).resolves.toBe(payload);
      const call = fetchMock.mock.calls[0];
      expect(call?.[0], item.name).toBe(
        `http://localhost:8000/api/v1/command${item.path}`,
      );
      expect(call?.[1], item.name).toEqual(expect.objectContaining({ method: item.method }));
      if (item.body === undefined) expect(call?.[1], item.name).not.toHaveProperty('body');
      else expect(call?.[1]?.body, item.name).toBe(item.body);
    }
  });

  it('sends the admin bearer token when loading the internal overview', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-123' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ contacts: 1, open_tasks: 2, opportunities: 3, active_smart_plans: 4 }) });
    vi.stubGlobal('fetch', fetchMock);
    await expect(commandApi.overview()).resolves.toMatchObject({ contacts: 1 });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/v1/command/overview'), expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer token-123' }) }));
  });

  it('surfaces an API detail on failed CRM writes', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: 'Contact already exists' }) }));
    await expect(commandApi.createContact({ first_name: 'A', last_name: '', email: null, phone: null })).rejects.toThrow('Contact already exists');
  });

  it('surfaces the message from a structured archive import conflict', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        detail: {
          code: 'task_idempotency_mismatch',
          message: 'Archive task identity was already used with different task data or authority',
        },
      }),
    }));
    await expect(commandApi.importArchiveBundle({
      source_id: 'archive-1',
      tasks: [{ source_row_id: 'row-1', title: 'Call' }],
    })).rejects.toThrow(
      'Archive task identity was already used with different task data or authority',
    );
  });

  it('creates an opportunity contact relationship through the authenticated API', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-relationship' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 8, contact_id: 12, role: 'buyer' }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.addOpportunityContact(4, 12, 'buyer')).resolves.toMatchObject({ contact_id: 12, role: 'buyer' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/opportunities/4/contacts'), expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ Authorization: 'Bearer token-relationship' }),
      body: JSON.stringify({ contact_id: 12, role: 'buyer' }),
    }));
  });

  it('adds a persisted action step to a Smart Plan', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-plan' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 2, position: 1, action_type: 'call' }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.addSmartPlanStep(7, 1, 'call', { title: 'Initial consult' })).resolves.toMatchObject({ action_type: 'call' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/smart-plans/7/steps'), expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ position: 1, action_type: 'call', payload: { title: 'Initial consult' } }),
    }));
  });

  it('updates an agreement lifecycle state through the internal API', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-agreement' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 5, status: 'in_review' }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.updateAgreementStatus(5, 'in_review')).resolves.toMatchObject({ status: 'in_review' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/agreements/5/status'), expect.objectContaining({
      method: 'PATCH', body: JSON.stringify({ status: 'in_review' }),
    }));
  });

  it('loads internal marketing records with the administrator credential', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-marketing' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ content_blocks: [], funnels: [] }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.marketingRecords()).resolves.toEqual({ content_blocks: [], funnels: [] });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/marketing/records'), expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer token-marketing' }) }));
  });

  it('requests a bounded contacts page using limit and offset', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-page' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal('fetch', fetchMock);

    await commandApi.contacts(50, 100);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/contacts?limit=50&offset=100'), expect.anything());
  });

  it('keeps the legacy contacts URL and decodes the exact raw array shape', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-legacy-contacts' });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [legacyContact],
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.contacts(100, 100, {
      query: '  Avery & Stone  ',
      stage: ' Client / Lead ',
    })).resolves.toEqual([legacyContact]);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(
        '/contacts?limit=100&offset=100&query=Avery+%26+Stone&stage=+Client+%2F+Lead+',
      ),
      expect.anything(),
    );
  });

  it('fails closed on malformed legacy contact rows', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-malformed-contact' });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        id: 7,
        first_name: 'Avery',
        last_name: 'Stone',
        email: null,
        phone: null,
        birthday: null,
        anniversary: null,
        stage: 'lead',
      }],
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.contacts()).rejects.toBeInstanceOf(CommandDecodeError);
  });

  it('fails closed on a sparse legacy contact array instead of skipping its hole', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-sparse-contact' });
    const sparse: unknown[] = [];
    sparse.length = 1;
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => sparse });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.contacts()).rejects.toBeInstanceOf(CommandDecodeError);
  });

  it.each([
    [0, 0],
    [101, 0],
    [1.5, 0],
    [Number.MAX_SAFE_INTEGER + 1, 0],
    [50, -1],
    [50, 1.5],
    [50, Number.MAX_SAFE_INTEGER + 1],
  ])('rejects invalid legacy paging (%s, %s) before fetch', async (limit, offset) => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-invalid-paging' });
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.contacts(limit, offset)).rejects.toBeInstanceOf(CommandDecodeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('delegates directory and celebrations to strict contact decoders with signal identity', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-contact-delegates' });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => directoryPage })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ birthdays: [], anniversaries: [] }),
      });
    const controller = new AbortController();
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.contactDirectory(
      { query: 'A & B', tag: [9, 3], page_size: 25 },
      { signal: controller.signal },
    )).resolves.toEqual(directoryPage);
    await expect(commandApi.celebrations(8, { signal: controller.signal })).resolves.toEqual({
      birthdays: [],
      anniversaries: [],
    });

    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      '/contacts/directory?query=A+%26+B&tag=3&tag=9&page_size=25',
    );
    expect(fetchMock.mock.calls[1]?.[0]).toContain('/celebrations?month=8');
    for (const [, init] of fetchMock.mock.calls) {
      expect(init).toEqual(expect.objectContaining({ signal: controller.signal }));
    }
  });

  it('fails closed on a malformed snake-case celebration response before Home adaptation', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-malformed-celebrations' });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        birthdays: [{
          contact_id: 7,
          display_name: 'Private',
          kind: 'birthday',
          month: 8,
          day: 13,
          year: null,
          year_quality: 'yearless',
          origin: 'recovered',
          unexpected: true,
        }],
        anniversaries: [],
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.celebrations(8)).rejects.toBeInstanceOf(CommandDecodeError);
  });

  it('pins decoded create and update results to required nullable legacy keys', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-contact-mutations' });
    const missingLeadId = {
      id: 7,
      first_name: 'Avery',
      last_name: 'Stone',
      email: null,
      phone: null,
      birthday: null,
      anniversary: null,
      stage: 'lead',
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => missingLeadId })
      .mockResolvedValueOnce({ ok: true, json: async () => missingLeadId });
    vi.stubGlobal('fetch', fetchMock);

    await expect(contactsApi.create({ first_name: 'Avery' }))
      .rejects.toBeInstanceOf(CommandDecodeError);
    await expect(contactsApi.update(7, { email: null }))
      .rejects.toBeInstanceOf(CommandDecodeError);
  });

  it('updates a Smart Plan enrollment state through the authenticated API', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-enrollment' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 9, status: 'paused' }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.updateSmartPlanEnrollment(7, 9, 'paused')).resolves.toMatchObject({ status: 'paused' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/smart-plans/7/enrollments/9'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ status: 'paused' }) }));
  });

  it('enrolls a selected internal contact into a Smart Plan through the typed API', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-enrollment-create' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 9, contact_id: 13, status: 'active' }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.enrollSmartPlanContact(7, 13)).resolves.toMatchObject({ contact_id: 13, status: 'active' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/smart-plans/7/enrollments'), expect.objectContaining({ method: 'POST', body: JSON.stringify({ contact_id: 13 }) }));
  });

  it('moves an opportunity to a new persisted pipeline stage', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-opportunity' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 3, name: 'Oak Street', stage: 'offer', value_cents: null }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.updateOpportunity(3, 'offer')).resolves.toMatchObject({ stage: 'offer' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/opportunities/3'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ stage: 'offer' }) }));
  });

  it('updates a contact stage through the internal CRM API', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-contact-stage' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 11, first_name: 'Taylor', last_name: '', email: null, phone: null, stage: 'client' }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.updateContactStage(11, 'client')).resolves.toMatchObject({ stage: 'client' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/contacts/11'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ stage: 'client' }) }));
  });

  it('edits a Smart Plan step through the authenticated API', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-step' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 4, position: 2, action_type: 'email' }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.updateSmartPlanStep(7, 4, 2, 'email', { subject: 'Welcome' })).resolves.toMatchObject({ action_type: 'email' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/smart-plans/7/steps/4'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ position: 2, action_type: 'email', payload: { subject: 'Welcome' } }) }));
  });

  it('creates an internal record link for a task', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-task-link' });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 2,
        task_id: 8,
        entity_type: 'agreement',
        entity_id: 15,
        display_name: 'Agreement 15',
        task_version: 4,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    await expect(commandApi.addTaskLink(8, {
      expected_version: 3,
      entity_type: 'agreement',
      entity_id: 15,
    })).resolves.toMatchObject({ entity_id: 15, task_version: 4 });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/tasks/8/links'), expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ expected_version: 3, entity_type: 'agreement', entity_id: 15 }),
    }));
  });

  it('bulk archives tasks in normalized task-ID order with strict results', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-bulk-archive' });
    const firstRequestId = '11111111-1111-4111-8111-111111111111';
    const secondRequestId = '22222222-2222-4222-8222-222222222222';
    const archived = (id: number, version: number) => ({
      id,
      title: `Task ${id}`,
      contact_id: null,
      description: '',
      priority: 'normal',
      due_at: null,
      status: 'open',
      archived_at: '2026-08-24T20:00:00Z',
      archive_reason: 'Cleanup',
      version,
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        results: [
          { task_id: 3, status: 'archived', code: null, task: archived(3, 3) },
          { task_id: 9, status: 'archived', code: null, task: archived(9, 5) },
        ],
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.bulkArchiveTasks({
      reason: '  Cleanup  ',
      items: [
        { task_id: 9, request_id: secondRequestId, expected_version: 4 },
        { task_id: 3, request_id: firstRequestId, expected_version: 2 },
      ],
    })).resolves.toEqual({
      results: [
        { task_id: 3, status: 'archived', code: null, task: archived(3, 3) },
        { task_id: 9, status: 'archived', code: null, task: archived(9, 5) },
      ],
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/tasks/bulk-archive'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          items: [
            { task_id: 3, request_id: firstRequestId, expected_version: 2 },
            { task_id: 9, request_id: secondRequestId, expected_version: 4 },
          ],
          reason: 'Cleanup',
        }),
      }),
    );
  });

  it('fails closed when a bulk archive response is reordered or malformed', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-bulk-malformed' });
    const request = {
      items: [
        {
          task_id: 3,
          request_id: '11111111-1111-4111-8111-111111111111',
          expected_version: 2,
        },
        {
          task_id: 9,
          request_id: '22222222-2222-4222-8222-222222222222',
          expected_version: 4,
        },
      ],
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        results: [
          { task_id: 9, status: 'not_found', code: 'task_not_found', task: null },
          { task_id: 3, status: 'not_found', code: 'task_not_found', task: null },
        ],
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.bulkArchiveTasks(request))
      .rejects.toBeInstanceOf(CommandOutcomeUncertainError);
  });

  it('classifies a bulk archive transport failure as outcome uncertain', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-bulk-network' });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network interrupted')));

    await expect(commandApi.bulkArchiveTasks({
      items: [{
        task_id: 3,
        request_id: '11111111-1111-4111-8111-111111111111',
        expected_version: 2,
      }],
    })).rejects.toBeInstanceOf(CommandOutcomeUncertainError);
  });

  it('updates an internal agreement template body', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-template' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 6, name: 'Buyer', body: 'Updated body' }) });
    vi.stubGlobal('fetch', fetchMock);
    await expect(commandApi.updateAgreementTemplate(6, 'Updated body')).resolves.toMatchObject({ body: 'Updated body' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/agreement-templates/6'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ body: 'Updated body' }) }));
  });

  it('requests a filtered task queue with status and due date bounds', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-task-filter' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal('fetch', fetchMock);
    await commandApi.tasks({ status: 'open', due_before: '2026-08-31T23:59:59Z' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/tasks?status=open&due_before=2026-08-31T23%3A59%3A59Z'), expect.anything());
  });

  it('forwards Home read signals without serializing the task signal as a filter', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-home-signals' });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ contacts: 0 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => [] })
      .mockResolvedValueOnce({ ok: true, json: async () => [] })
      .mockResolvedValueOnce({ ok: true, json: async () => [] })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ summary: 'Brief' }) });
    const controller = new AbortController();
    vi.stubGlobal('fetch', fetchMock);

    await commandApi.overview({ signal: controller.signal });
    await commandApi.tasks(
      { status: 'open', due_after: '2026-08-01T00:00:00Z' },
      { signal: controller.signal },
    );
    await commandApi.opportunities({ signal: controller.signal });
    await commandApi.goals({ signal: controller.signal });
    await commandApi.aiBriefing({ signal: controller.signal });

    expect(fetchMock.mock.calls[1]?.[0]).toContain(
      '/tasks?status=open&due_after=2026-08-01T00%3A00%3A00Z',
    );
    expect(fetchMock.mock.calls[1]?.[0]).not.toContain('signal');
    for (const [, init] of fetchMock.mock.calls) {
      expect(init).toEqual(expect.objectContaining({ signal: controller.signal }));
    }
  });

  it('updates a listing lifecycle status through the internal API', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-listing' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 9, address: '10 Main St', latitude: null, longitude: null, status: 'pending' }) });
    vi.stubGlobal('fetch', fetchMock);
    await expect(commandApi.updateListingStatus(9, 'pending')).resolves.toMatchObject({ status: 'pending' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/listings/9'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ status: 'pending' }) }));
  });

  it('loads birthday and anniversary queues for the requested month', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-celebrations' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ birthdays: [], anniversaries: [] }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.celebrations(8)).resolves.toEqual({ birthdays: [], anniversaries: [] });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/celebrations?month=8'), expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer token-celebrations' }) }));
  });

  it('persists private celebration dates on the contact profile', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-profile-dates' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 11, first_name: 'Avery', last_name: '', email: null, phone: null, stage: 'lead', birthday: '1990-08-12', anniversary: null }) });
    vi.stubGlobal('fetch', fetchMock);

    await commandApi.updateContact(11, { birthday: '1990-08-12', anniversary: null });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/contacts/11'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ birthday: '1990-08-12', anniversary: null }) }));
  });

  it('imports a bounded internal contact archive through the protected CRM endpoint', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-import' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ created: 1, skipped_duplicates: 0 }) });
    vi.stubGlobal('fetch', fetchMock);
    await expect(commandApi.importContacts([{ first_name: 'Avery', last_name: 'Lake', email: 'avery@example.com', phone: null, stage: 'lead', birthday: null, anniversary: null }])).resolves.toMatchObject({ created: 1 });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/contacts/import'), expect.objectContaining({ method: 'POST', body: JSON.stringify({ contacts: [{ first_name: 'Avery', last_name: 'Lake', email: 'avery@example.com', phone: null, stage: 'lead', birthday: null, anniversary: null }] }) }));
  });

  it('imports a permitted multi-record archive bundle through the protected CRM endpoint', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-archive-bundle' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ created: { contacts: 1 }, skipped_duplicates: {}, unresolved_contact_references: 0 }) });
    vi.stubGlobal('fetch', fetchMock);
    await expect(commandApi.importArchiveBundle({ contacts: [{ first_name: 'Avery', last_name: '', email: 'avery@example.com', phone: null }] })).resolves.toMatchObject({ unresolved_contact_references: 0 });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/archive/import'), expect.objectContaining({ method: 'POST' }));
  });

  it('downloads recovered artifact bytes through an authenticated non-JSON request', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-artifact-download' });
    const payload = new Blob(['recovered source']);
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, blob: async () => payload });
    const controller = new AbortController();
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.archiveArtifactBlob(42, { signal: controller.signal })).resolves.toBe(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/archive/artifacts/42/content'),
      expect.objectContaining({
        signal: controller.signal,
        headers: { Authorization: 'Bearer token-artifact-download' },
      }),
    );
    expect(fetchMock.mock.calls[0]?.[1]?.headers).not.toHaveProperty('Content-Type');
  });

  it('requests contacts with server-side search and stage filters', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-contact-filter' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal('fetch', fetchMock);

    await commandApi.contacts(100, 0, { query: 'avery lake', stage: 'client' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/contacts?limit=100&offset=0&query=avery+lake&stage=client'), expect.anything());
  });

  it('requests listings with server-side address and lifecycle filters', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-listing-filter' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal('fetch', fetchMock);

    await commandApi.listings({ query: 'Main', status: 'active' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/listings?query=Main&status=active'), expect.anything());
  });

  it('persists a complete task edit through the internal API', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-task-edit' });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 9,
        title: 'Call buyer',
        description: 'Discuss timeline',
        priority: 'high',
        status: 'in_progress',
        due_at: null,
        contact_id: null,
        archived_at: null,
        archive_reason: null,
        version: 4,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await commandApi.updateTask(9, {
      expected_version: 3,
      title: 'Call buyer',
      description: 'Discuss timeline',
      priority: 'high',
      status: 'in_progress',
      due_at: null,
    });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/tasks/9'), expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({
        expected_version: 3,
        title: 'Call buyer',
        description: 'Discuss timeline',
        priority: 'high',
        status: 'in_progress',
        due_at: null,
      }),
    }));
  });

  it('assigns a task to a selected internal contact', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-task-contact' });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 9,
        title: 'Call buyer',
        description: '',
        priority: 'normal',
        status: 'open',
        due_at: null,
        contact_id: 14,
        archived_at: null,
        archive_reason: null,
        version: 6,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    await commandApi.updateTask(9, { expected_version: 5, contact_id: 14 });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/tasks/9'), expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({ expected_version: 5, contact_id: 14 }),
    }));
  });

  it('loads a report-card drilldown through the authenticated Command API', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-report-detail' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ metric: 'contacts', rows: [] }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.reportDetails('contacts')).resolves.toMatchObject({ metric: 'contacts' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/reports/details/contacts'), expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer token-report-detail' }) }));
  });

  it('updates persisted goal progress through the Command API', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-goal' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 3, name: 'Appointments', target_value: 12, current_value: 5, period: 'monthly' }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.updateGoalProgress(3, 5)).resolves.toMatchObject({ current_value: 5 });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/goals/3'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ current_value: 5 }) }));
  });

  it('updates a Smart Plan lifecycle without changing its enrollments', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-plan-lifecycle' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 7, name: 'Buyer follow-up', description: '', status: 'paused' }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.updateSmartPlanStatus(7, 'paused')).resolves.toMatchObject({ status: 'paused' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/smart-plans/7'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ status: 'paused' }) }));
  });

  it('generates an auditable review-required AI briefing through the typed client', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-ai-briefing' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ summary: 'Prioritize follow-up.', source: 'gemini-aggregate-internal-metrics', requires_review: true }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.generateAiBriefing()).resolves.toMatchObject({ requires_review: true });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/ai/briefing/generate'), expect.objectContaining({ method: 'POST', headers: expect.objectContaining({ Authorization: 'Bearer token-ai-briefing' }) }));
  });

  it('persists self-describing saved-search criteria for a contact workspace', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-saved-search' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 2, name: 'Follow-up context' }) });
    vi.stubGlobal('fetch', fetchMock);

    await commandApi.createContactSavedSearch(14, 'Follow-up context', { contact_id: 14, scope: 'contact_workspace', saved_from: 'command' });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/contacts/14/saved-searches'), expect.objectContaining({ method: 'POST', body: JSON.stringify({ name: 'Follow-up context', criteria: { contact_id: 14, scope: 'contact_workspace', saved_from: 'command' } }) }));
  });

  it('removes scoped contact notes and tags through protected Command routes', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-contact-cleanup' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ deleted: true }) });
    vi.stubGlobal('fetch', fetchMock);
    await commandApi.deleteContactNote(14, 3);
    await commandApi.removeContactTag(14, 5);
    expect(fetchMock).toHaveBeenNthCalledWith(1, expect.stringContaining('/contacts/14/notes/3'), expect.objectContaining({ method: 'DELETE' }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, expect.stringContaining('/contacts/14/tags/5'), expect.objectContaining({ method: 'DELETE' }));
  });

  it('lists and deletes saved searches through the authenticated Command API', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-saved-search-list' });
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => [] }).mockResolvedValueOnce({ ok: true, json: async () => ({ deleted: true, id: 4 }) });
    vi.stubGlobal('fetch', fetchMock);
    await expect(commandApi.savedSearches()).resolves.toEqual([]);
    await expect(commandApi.deleteSavedSearch(4)).resolves.toMatchObject({ deleted: true });
    expect(fetchMock).toHaveBeenNthCalledWith(1, expect.stringContaining('/saved-searches'), expect.anything());
    expect(fetchMock).toHaveBeenNthCalledWith(2, expect.stringContaining('/saved-searches/4'), expect.objectContaining({ method: 'DELETE' }));
  });

  it('creates an internal agreement with a selected internal template', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-agreement-template' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 6, title: 'Buyer agreement', contact_id: null, template_id: 3, status: 'draft' }) });
    vi.stubGlobal('fetch', fetchMock);

    await commandApi.createAgreement({ title: 'Buyer agreement', contact_id: null, template_id: 3 });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/agreements'), expect.objectContaining({ method: 'POST', body: JSON.stringify({ title: 'Buyer agreement', contact_id: null, template_id: 3 }) }));
  });

  it('persists an agreement against its selected internal contact', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-agreement-contact' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 7, title: 'Seller agreement', contact_id: 11, template_id: null, status: 'draft' }) });
    vi.stubGlobal('fetch', fetchMock);

    await commandApi.createAgreement({ title: 'Seller agreement', contact_id: 11, template_id: null });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/agreements'), expect.objectContaining({ method: 'POST', body: JSON.stringify({ title: 'Seller agreement', contact_id: 11, template_id: null }) }));
  });

  it('rejects directory-only readiness fields on legacy contacts while unrelated reads stay unchecked', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-home-readiness' });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [{
          id: 4,
          first_name: 'Avery',
          last_name: 'Lake',
          email: null,
          phone: '+1 555 0104',
          stage: 'lead',
          birthday: null,
          anniversary: null,
          last_contacted_at: '2026-08-10T15:00:00.000Z',
          recently_active_at: '2026-08-11T12:00:00.000Z',
          health_score: 84,
        }],
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [{
          id: 8,
          name: 'Lake purchase',
          stage: 'active',
          value_cents: 52_500_000,
          updated_at: '2026-08-11T14:00:00.000Z',
        }],
      });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.contacts(100, 0)).rejects.toBeInstanceOf(CommandDecodeError);
    await expect(commandApi.opportunities()).resolves.toEqual([
      expect.objectContaining({ updated_at: '2026-08-11T14:00:00.000Z' }),
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [, init] of fetchMock.mock.calls) {
      expect(init).toEqual(expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer token-home-readiness' }),
      }));
    }
  });
});
