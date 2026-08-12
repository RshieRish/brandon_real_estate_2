const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export type Overview = { contacts: number; open_tasks: number; opportunities: number; active_smart_plans: number };
export type Contact = { id: number; first_name: string; last_name: string; email: string | null; phone: string | null; stage: string; birthday?: string | null; anniversary?: string | null };
export type Celebrations = { birthdays: Contact[]; anniversaries: Contact[] };
export type ContactWorkspace = { contact: Contact; timeline: { id: number; kind: string; summary: string; created_at: string }[]; tasks: Task[]; notes: { id: number; body: string }[]; smart_plans: { id: number; plan_id: number; status: string }[]; opportunities: Opportunity[]; saved_searches: { id: number; name: string; criteria: string }[]; bookings: { id: number; meeting_type: string; context: string; scheduled_at: string; location: string | null; notes: string }[]; tags: { id: number; name: string }[] };
export type ReportDetails = { metric: string; rows: { id: number; title: string; detail: string; occurred_at: string | null }[] };
export type Goal = { id: number; name: string; target_value: number; current_value: number; period: 'weekly' | 'monthly' | 'quarterly' | 'annual' };
export type AiBriefing = { summary: string; source: string; requires_review: boolean };
export type Task = { id: number; title: string; contact_id: number | null; description: string; priority: string; due_at: string | null; status: string };
export type NamedRecord = { id:number; name:string; description:string; status:string };
export type SmartPlanEnrollment = { id: number; contact_id: number; contact_name: string; status: 'active' | 'paused' | 'completed' };
export type TaskLink = { id: number; task_id: number; entity_type: string; entity_id: number; display_name: string };
export type ContactImportRow = Pick<Contact, 'first_name' | 'last_name' | 'email' | 'phone' | 'birthday' | 'anniversary'> & { stage?: string };
export type ContactImportResult = { created: number; skipped_duplicates: number };
export type Opportunity = { id:number; name:string; stage:string; value_cents:number|null };
export type Agreement = { id:number; title:string; contact_id:number|null; template_id?:number|null; status:string };
export type AgreementWorkspace = { agreement: Agreement; recipients: Relationship[]; events: { id: number; event_type: string; created_at: string }[]; files: { id: number; filename: string; storage_key: string; content_type: string; agreement_id: number | null }[] };
export type AgreementTemplate = { id: number; name: string; body: string };
export type MarketingRecords = { content_blocks: { id: number; block_id: string; page: string | null; content_type: string; updated_at: string }[]; funnels: { id: number; title: string; slug: string; audience: string; status: string; registrations: number; updated_at: string }[] };
export type Listing = { id:number; address:string; latitude:string|null; longitude:string|null; status:string };
export type Referral = { id: number; name: string; source: string; contact_id: number | null; status: string };
export type Relationship = { id:number; contact_id?:number; name?:string; email?:string; role:string; amount_cents?:number|null; status?:string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_URL}/api/v1/command${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...init?.headers } });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? 'Unable to load Command workspace');
  return response.json() as Promise<T>;
}

export const commandApi = {
  overview: () => request<Overview>('/overview'), contacts: (limit = 50, offset = 0, filters: { query?: string; stage?: string } = {}) => { const params = new URLSearchParams({ limit: String(Math.min(Math.max(limit, 1), 100)), offset: String(Math.max(offset, 0)) }); if (filters.query?.trim()) params.set('query', filters.query.trim()); if (filters.stage) params.set('stage', filters.stage); return request<Contact[]>(`/contacts?${params.toString()}`); }, tasks: (filters: { status?: string; due_before?: string; due_after?: string } = {}) => { const params = new URLSearchParams(); Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); }); return request<Task[]>(`/tasks${params.size ? `?${params.toString()}` : ''}`); },
  celebrations: (month: number) => request<Celebrations>(`/celebrations?month=${Math.min(Math.max(month, 1), 12)}`),
  contactWorkspace: (id: number) => request<ContactWorkspace>(`/contacts/${id}/workspace`),
  createContactNote: (id: number, body: string) => request<{ id: number; body: string }>(`/contacts/${id}/notes`, { method: 'POST', body: JSON.stringify({ body }) }),
  createContactSavedSearch: (id: number, name: string, criteria: Record<string, unknown>) => request<{ id: number; name: string; criteria: string }>(`/contacts/${id}/saved-searches`, { method: 'POST', body: JSON.stringify({ name, criteria }) }),
  createTag: (name: string) => request<{ id: number; name: string }>('/tags', { method: 'POST', body: JSON.stringify({ name }) }),
  assignContactTag: (contactId: number, tagId: number) => request<{ contact_id: number; tag_id: number }>(`/contacts/${contactId}/tags/${tagId}`, { method: 'POST' }),
  goals: () => request<Goal[]>('/goals'),
  createGoal: (payload: Omit<Goal, 'id'>) => request<Goal>('/goals', { method: 'POST', body: JSON.stringify(payload) }),
  updateGoalProgress: (id: number, current_value: number) => request<Goal>(`/goals/${id}`, { method: 'PATCH', body: JSON.stringify({ current_value }) }),
  aiBriefing: () => request<AiBriefing>('/ai/briefing'),
  generateAiBriefing: () => request<AiBriefing>('/ai/briefing/generate', { method: 'POST' }),
  createContact: (contact: Omit<Contact, 'id' | 'stage'>) => request<Contact>('/contacts', { method: 'POST', body: JSON.stringify(contact) }),
  importContacts: (contacts: ContactImportRow[]) => request<ContactImportResult>('/contacts/import', { method: 'POST', body: JSON.stringify({ contacts }) }),
  updateContactStage: (id: number, stage: string) => request<Contact>(`/contacts/${id}`, { method: 'PATCH', body: JSON.stringify({ stage }) }),
  updateContact: (id: number, payload: Partial<Pick<Contact, 'first_name' | 'last_name' | 'email' | 'phone' | 'stage' | 'birthday' | 'anniversary'>>) => request<Contact>(`/contacts/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  smartPlans: () => request<NamedRecord[]>('/smart-plans'), createSmartPlan: (payload: Pick<NamedRecord,'name'|'description'>) => request<NamedRecord>('/smart-plans',{method:'POST',body:JSON.stringify(payload)}),
  updateSmartPlanStatus: (id: number, status: 'active' | 'paused' | 'archived') => request<NamedRecord>(`/smart-plans/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  smartPlanWorkspace: (id: number) => request<{ plan: NamedRecord; steps: { id: number; position: number; action_type: string; payload: string }[]; enrollments: SmartPlanEnrollment[] }>(`/smart-plans/${id}/workspace`),
  addSmartPlanStep: (planId: number, position: number, actionType: string, payload: Record<string, unknown>) => request<{ id: number; position: number; action_type: string }>(`/smart-plans/${planId}/steps`, { method: 'POST', body: JSON.stringify({ position, action_type: actionType, payload }) }),
  updateSmartPlanStep: (planId: number, stepId: number, position: number, actionType: string, payload: Record<string, unknown>) => request<{ id: number; position: number; action_type: string }>(`/smart-plans/${planId}/steps/${stepId}`, { method: 'PATCH', body: JSON.stringify({ position, action_type: actionType, payload }) }),
  enrollSmartPlanContact: (planId: number, contactId: number) => request<{ id: number; contact_id: number; status: string }>(`/smart-plans/${planId}/enrollments`, { method: 'POST', body: JSON.stringify({ contact_id: contactId }) }),
  updateSmartPlanEnrollment: (planId: number, enrollmentId: number, status: 'active' | 'paused' | 'completed') => request<{ id: number; status: string }>(`/smart-plans/${planId}/enrollments/${enrollmentId}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  opportunities: () => request<Opportunity[]>('/opportunities'), createOpportunity: (payload: Omit<Opportunity,'id'>) => request<Opportunity>('/opportunities',{method:'POST',body:JSON.stringify(payload)}),
  updateOpportunity: (id: number, stage: string) => request<Opportunity>(`/opportunities/${id}`, { method: 'PATCH', body: JSON.stringify({ stage }) }),
  opportunityWorkspace: (id: number) => request<{opportunity: Opportunity; contacts: Relationship[]; vendors: Relationship[]; offers: Relationship[]}>(`/opportunities/${id}/workspace`),
  addOpportunityContact: (opportunityId: number, contactId: number, role = 'client') => request<Relationship>(`/opportunities/${opportunityId}/contacts`, { method: 'POST', body: JSON.stringify({ contact_id: contactId, role }) }),
  addOpportunityVendor: (opportunityId: number, name: string, role = 'vendor') => request<Relationship>(`/opportunities/${opportunityId}/vendors`, { method: 'POST', body: JSON.stringify({ name, role }) }),
  addOpportunityOffer: (opportunityId: number, amount_cents: number | null, status = 'draft') => request<Relationship>(`/opportunities/${opportunityId}/offers`, { method: 'POST', body: JSON.stringify({ amount_cents, status }) }),
  agreements: () => request<Agreement[]>('/agreements'), createAgreement: (payload: Omit<Agreement,'id'|'status'>) => request<Agreement>('/agreements',{method:'POST',body:JSON.stringify(payload)}),
  agreementWorkspace: (id: number) => request<AgreementWorkspace>(`/agreements/${id}/workspace`),
  updateAgreementStatus: (id: number, status: string) => request<{ id: number; status: string }>(`/agreements/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  addAgreementRecipient: (agreementId: number, name: string, email: string, role = 'recipient') => request<Relationship>(`/agreements/${agreementId}/recipients`, { method: 'POST', body: JSON.stringify({ name, email, role }) }),
  agreementTemplates: () => request<AgreementTemplate[]>('/agreement-templates'),
  createAgreementTemplate: (name: string, body = '') => request<AgreementTemplate>('/agreement-templates', { method: 'POST', body: JSON.stringify({ name, body }) }),
  updateAgreementTemplate: (id: number, body: string) => request<AgreementTemplate>(`/agreement-templates/${id}`, { method: 'PATCH', body: JSON.stringify({ body }) }),
  listings: (filters: { query?: string; status?: string } = {}) => { const params = new URLSearchParams(); if (filters.query?.trim()) params.set('query', filters.query.trim()); if (filters.status) params.set('status', filters.status); return request<Listing[]>(`/listings${params.size ? `?${params.toString()}` : ''}`); }, createListing: (payload: Omit<Listing,'id'|'status'>) => request<Listing>('/listings',{method:'POST',body:JSON.stringify(payload)}), updateListingStatus: (id: number, status: 'active' | 'pending' | 'sold' | 'withdrawn') => request<Listing>(`/listings/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  geocodeListing: (id: number) => request<Listing>(`/listings/${id}/geocode`, { method: 'POST' }),
  referrals: () => request<Referral[]>('/referrals'),
  createReferral: (payload: Omit<Referral, 'id' | 'status'>) => request<Referral>('/referrals', { method: 'POST', body: JSON.stringify(payload) }),
  updateReferralStatus: (id: number, status: string) => request<Referral>(`/referrals/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  marketingRecords: () => request<MarketingRecords>('/marketing/records'),
  websiteRecords: () => request<{ pages: MarketingRecords['content_blocks'] }>('/websites/records'),
  eventBreakdown: () => request<{ events: { event_type: string; count: number }[] }>('/reports/event-breakdown'),
  reportsSummary: () => request<Record<string, number>>('/reports/summary'),
  reportDetails: (metric: string) => request<ReportDetails>(`/reports/details/${encodeURIComponent(metric)}`),
  createTask: (task: Pick<Task, 'title' | 'description' | 'priority' | 'contact_id' | 'due_at'>) => request<Task>('/tasks', { method: 'POST', body: JSON.stringify(task) }),
  addTaskLink: (taskId: number, entityType: string, entityId: number) => request<TaskLink>(`/tasks/${taskId}/links`, { method: 'POST', body: JSON.stringify({ entity_type: entityType, entity_id: entityId }) }),
  taskLinks: (taskId: number) => request<TaskLink[]>(`/tasks/${taskId}/links`),
  updateTask: (id: number, payload: Partial<Pick<Task, 'title' | 'description' | 'priority' | 'status' | 'due_at' | 'contact_id'>>) => request<Task>(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
};
