const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export type Overview = { contacts: number; open_tasks: number; opportunities: number; active_smart_plans: number };
export type Contact = { id: number; first_name: string; last_name: string; email: string | null; phone: string | null; stage: string };
export type Task = { id: number; title: string; contact_id: number | null; description: string; priority: string; due_at: string | null; status: string };
export type NamedRecord = { id:number; name:string; description:string; status:string };
export type Opportunity = { id:number; name:string; stage:string; value_cents:number|null };
export type Agreement = { id:number; title:string; contact_id:number|null; status:string };
export type AgreementWorkspace = { agreement: Agreement; recipients: Relationship[]; events: { id: number; event_type: string; created_at: string }[]; files: { id: number; filename: string; storage_key: string; content_type: string; agreement_id: number | null }[] };
export type MarketingRecords = { content_blocks: { id: number; block_id: string; page: string | null; content_type: string; updated_at: string }[]; funnels: { id: number; title: string; slug: string; audience: string; status: string; registrations: number; updated_at: string }[] };
export type Listing = { id:number; address:string; latitude:string|null; longitude:string|null; status:string };
export type Relationship = { id:number; contact_id?:number; name?:string; email?:string; role:string; amount_cents?:number|null; status?:string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_URL}/api/v1/command${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...init?.headers } });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? 'Unable to load Command workspace');
  return response.json() as Promise<T>;
}

export const commandApi = {
  overview: () => request<Overview>('/overview'), contacts: (limit = 50, offset = 0) => request<Contact[]>(`/contacts?limit=${Math.min(Math.max(limit, 1), 100)}&offset=${Math.max(offset, 0)}`), tasks: () => request<Task[]>('/tasks'),
  createContact: (contact: Omit<Contact, 'id' | 'stage'>) => request<Contact>('/contacts', { method: 'POST', body: JSON.stringify(contact) }),
  smartPlans: () => request<NamedRecord[]>('/smart-plans'), createSmartPlan: (payload: Pick<NamedRecord,'name'|'description'>) => request<NamedRecord>('/smart-plans',{method:'POST',body:JSON.stringify(payload)}),
  smartPlanWorkspace: (id: number) => request<{ plan: NamedRecord; steps: { id: number; position: number; action_type: string; payload: string }[]; enrollments: { id: number; contact_id: number; status: string }[] }>(`/smart-plans/${id}/workspace`),
  addSmartPlanStep: (planId: number, position: number, actionType: string, payload: Record<string, unknown>) => request<{ id: number; position: number; action_type: string }>(`/smart-plans/${planId}/steps`, { method: 'POST', body: JSON.stringify({ position, action_type: actionType, payload }) }),
  enrollSmartPlanContact: (planId: number, contactId: number) => request<{ id: number; status: string }>(`/smart-plans/${planId}/enrollments`, { method: 'POST', body: JSON.stringify({ contact_id: contactId }) }),
  updateSmartPlanEnrollment: (planId: number, enrollmentId: number, status: 'active' | 'paused' | 'completed') => request<{ id: number; status: string }>(`/smart-plans/${planId}/enrollments/${enrollmentId}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  opportunities: () => request<Opportunity[]>('/opportunities'), createOpportunity: (payload: Omit<Opportunity,'id'>) => request<Opportunity>('/opportunities',{method:'POST',body:JSON.stringify(payload)}),
  opportunityWorkspace: (id: number) => request<{opportunity: Opportunity; contacts: Relationship[]; vendors: Relationship[]; offers: Relationship[]}>(`/opportunities/${id}/workspace`),
  addOpportunityContact: (opportunityId: number, contactId: number, role = 'client') => request<Relationship>(`/opportunities/${opportunityId}/contacts`, { method: 'POST', body: JSON.stringify({ contact_id: contactId, role }) }),
  addOpportunityVendor: (opportunityId: number, name: string, role = 'vendor') => request<Relationship>(`/opportunities/${opportunityId}/vendors`, { method: 'POST', body: JSON.stringify({ name, role }) }),
  addOpportunityOffer: (opportunityId: number, amount_cents: number | null, status = 'draft') => request<Relationship>(`/opportunities/${opportunityId}/offers`, { method: 'POST', body: JSON.stringify({ amount_cents, status }) }),
  agreements: () => request<Agreement[]>('/agreements'), createAgreement: (payload: Omit<Agreement,'id'|'status'>) => request<Agreement>('/agreements',{method:'POST',body:JSON.stringify(payload)}),
  agreementWorkspace: (id: number) => request<AgreementWorkspace>(`/agreements/${id}/workspace`),
  updateAgreementStatus: (id: number, status: string) => request<{ id: number; status: string }>(`/agreements/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  addAgreementRecipient: (agreementId: number, name: string, email: string, role = 'recipient') => request<Relationship>(`/agreements/${agreementId}/recipients`, { method: 'POST', body: JSON.stringify({ name, email, role }) }),
  listings: () => request<Listing[]>('/listings'), createListing: (payload: Omit<Listing,'id'|'status'>) => request<Listing>('/listings',{method:'POST',body:JSON.stringify(payload)}),
  geocodeListing: (id: number) => request<Listing>(`/listings/${id}/geocode`, { method: 'POST' }),
  marketingRecords: () => request<MarketingRecords>('/marketing/records'),
  websiteRecords: () => request<{ pages: MarketingRecords['content_blocks'] }>('/websites/records'),
  eventBreakdown: () => request<{ events: { event_type: string; count: number }[] }>('/reports/event-breakdown'),
  createTask: (task: Pick<Task, 'title' | 'description' | 'priority' | 'contact_id' | 'due_at'>) => request<Task>('/tasks', { method: 'POST', body: JSON.stringify(task) }),
  updateTask: (id: number, payload: Partial<Pick<Task, 'title' | 'status' | 'due_at'>>) => request<Task>(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
};
