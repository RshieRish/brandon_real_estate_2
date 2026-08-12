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
});
