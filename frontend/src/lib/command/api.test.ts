import { afterEach, describe, expect, it, vi } from 'vitest';
import { commandApi } from './api';

describe('commandApi', () => {
  afterEach(() => vi.unstubAllGlobals());

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
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 2, task_id: 8, entity_type: 'agreement', entity_id: 15 }) });
    vi.stubGlobal('fetch', fetchMock);
    await expect(commandApi.addTaskLink(8, 'agreement', 15)).resolves.toMatchObject({ entity_id: 15 });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/tasks/8/links'), expect.objectContaining({ method: 'POST', body: JSON.stringify({ entity_type: 'agreement', entity_id: 15 }) }));
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
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 9, title: 'Call buyer', description: 'Discuss timeline', priority: 'high', status: 'in_progress', due_at: null, contact_id: null }) });
    vi.stubGlobal('fetch', fetchMock);

    await commandApi.updateTask(9, { title: 'Call buyer', description: 'Discuss timeline', priority: 'high', status: 'in_progress', due_at: null });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/tasks/9'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ title: 'Call buyer', description: 'Discuss timeline', priority: 'high', status: 'in_progress', due_at: null }) }));
  });

  it('assigns a task to a selected internal contact', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-task-contact' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 9, contact_id: 14 }) });
    vi.stubGlobal('fetch', fetchMock);
    await commandApi.updateTask(9, { contact_id: 14 });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/tasks/9'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ contact_id: 14 }) }));
  });

  it('loads the complete contact workspace including internal booking history', async () => {
    vi.stubGlobal('localStorage', { getItem: () => 'token-contact-workspace' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ contact: {}, bookings: [] }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(commandApi.contactWorkspace(14)).resolves.toMatchObject({ bookings: [] });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/contacts/14/workspace'), expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer token-contact-workspace' }) }));
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
});
