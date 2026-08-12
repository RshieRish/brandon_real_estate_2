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
});
