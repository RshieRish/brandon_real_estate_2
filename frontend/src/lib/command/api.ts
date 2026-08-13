import {
  contactsApi,
  decodeLegacyContact,
  type ContactDirectoryPage,
  type ContactDirectoryRequest,
  type LegacyContact,
} from './contacts';
import {
  commandBlob,
  commandJson,
  CommandDecodeError,
  type Decoder,
} from './http';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export { contactsApi };

export type CommandRequestOptions = Readonly<{ signal?: AbortSignal }>;
export type TaskFilters = Readonly<{
  status?: string;
  due_before?: string;
  due_after?: string;
}>;

export type Overview = { contacts: number; open_tasks: number; opportunities: number; active_smart_plans: number };
export type Contact = { id: number; first_name: string; last_name: string; email: string | null; phone: string | null; stage: string; birthday?: string | null; anniversary?: string | null; last_contacted_at?: string | null; recently_active_at?: string | null; health_score?: number | null };
export type LegacyContactWorkspace = Readonly<{
  contact: LegacyContact;
  timeline: readonly Readonly<{
    id: number;
    kind: string;
    summary: string;
    created_at: string;
  }>[];
  tasks: readonly Readonly<{
    id: number;
    title: string;
    contact_id: number | null;
    description: string;
    priority: string;
    due_at: string | null;
    status: string;
  }>[];
  notes: readonly Readonly<{
    id: number;
    contact_id: number;
    body: string;
    created_at: string;
    updated_at: string;
  }>[];
  smart_plans: readonly Readonly<{
    id: number;
    plan_id: number;
    status: string;
  }>[];
  opportunities: readonly Readonly<{
    id: number;
    name: string;
    stage: string;
    value_cents: number | null;
    role: string;
  }>[];
  saved_searches: readonly Readonly<{
    id: number;
    name: string;
    criteria: string;
  }>[];
  bookings: readonly Readonly<{
    id: number;
    meeting_type: string;
    context: string;
    scheduled_at: string;
    location: string | null;
    notes: string;
  }>[];
  tags: readonly Readonly<{ id: number; name: string }>[];
}>;
export type ContactWorkspace = LegacyContactWorkspace;
export type ReportDetails = { metric: string; rows: { id: number; title: string; detail: string; occurred_at: string | null }[] };
export type Goal = { id: number; name: string; target_value: number; current_value: number; period: 'weekly' | 'monthly' | 'quarterly' | 'annual' };
export type AiBriefing = { summary: string; source: string; requires_review: boolean };
export type Task = { id: number; title: string; contact_id: number | null; description: string; priority: string; due_at: string | null; status: string };
export type NamedRecord = { id:number; name:string; description:string; status:string };
export type SmartPlanEnrollment = { id: number; contact_id: number; contact_name: string; status: 'active' | 'paused' | 'completed' };
export type TaskLink = { id: number; task_id: number; entity_type: string; entity_id: number; display_name: string };
export type ContactImportRow = Pick<Contact, 'first_name' | 'last_name' | 'email' | 'phone' | 'birthday' | 'anniversary'> & { stage?: string };
export type ContactImportResult = { created: number; skipped_duplicates: number };
export type ArchiveBundle = { contacts?: ContactImportRow[]; tasks?: { title: string; contact_email?: string | null; description?: string; status?: string; priority?: string; due_at?: string | null }[]; notes?: { contact_email: string; body: string }[]; opportunities?: { name: string; stage?: string; value_cents?: number | null; contact_emails?: string[] }[]; referrals?: { name: string; source?: string; status?: string; contact_email?: string | null }[]; listings?: { address: string; latitude?: string | null; longitude?: string | null; status?: string }[]; templates?: { name: string; body?: string }[]; agreements?: { title: string; contact_email?: string | null; template_name?: string | null; status?: string }[] };
export type ArchiveBundleImportResult = { created: Record<string, number>; skipped_duplicates: Record<string, number>; unresolved_contact_references: number };
export type SavedSearch = { id: number; name: string; criteria: string; contact_id: number | null; contact_name: string | null; updated_at: string };
export type Opportunity = { id:number; name:string; stage:string; value_cents:number|null; updated_at?:string|null };
export type Agreement = { id:number; title:string; contact_id:number|null; template_id?:number|null; status:string };
export type AgreementWorkspace = { agreement: Agreement; recipients: Relationship[]; events: { id: number; event_type: string; created_at: string }[]; files: { id: number; filename: string; storage_key: string; content_type: string; agreement_id: number | null }[] };
export type AgreementTemplate = { id: number; name: string; body: string };
export type MarketingRecords = { content_blocks: { id: number; block_id: string; page: string | null; content_type: string; updated_at: string }[]; funnels: { id: number; title: string; slug: string; audience: string; status: string; registrations: number; updated_at: string }[] };
export type Listing = { id:number; address:string; latitude:string|null; longitude:string|null; status:string };
export type Referral = { id: number; name: string; source: string; contact_id: number | null; status: string };
export type ArchiveArtifact = { id: number; domain: string; artifact_type: string; filename: string; source_path: string; sha256: string; size_bytes: number; text_preview: string };
export type Relationship = { id:number; contact_id?:number; name?:string; email?:string; role:string; amount_cents?:number|null; status?:string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_URL}/api/v1/command${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...init?.headers } });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? 'Unable to load Command workspace');
  return response.json() as Promise<T>;
}

const decodeLegacyContacts: Decoder<readonly LegacyContact[]> = (
  input,
  path = 'response',
) => {
  if (!Array.isArray(input)) {
    throw new CommandDecodeError(path, 'array');
  }
  const rows: readonly unknown[] = input;
  return Array.from(rows, (row, index) => decodeLegacyContact(row, `${path}[${index}]`));
};

function requestInteger(
  value: number,
  path: string,
  minimum: number,
  maximum = Number.MAX_SAFE_INTEGER,
): number {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new CommandDecodeError(path, `safe integer from ${minimum} to ${maximum}`);
  }
  return value;
}

async function legacyContacts(
  limit = 50,
  offset = 0,
  filters: Readonly<{ query?: string; stage?: string }> = {},
): Promise<readonly LegacyContact[]> {
  const params = new URLSearchParams({
    limit: String(requestInteger(limit, 'request.limit', 1, 100)),
    offset: String(requestInteger(offset, 'request.offset', 0)),
  });
  if (filters.query !== undefined) {
    if (typeof filters.query !== 'string') {
      throw new CommandDecodeError('request.query', 'string');
    }
    const query = filters.query.trim();
    if (query.length > 0) params.set('query', query);
  }
  if (filters.stage !== undefined) {
    if (typeof filters.stage !== 'string') {
      throw new CommandDecodeError('request.stage', 'string');
    }
    params.set('stage', filters.stage);
  }
  return commandJson({
    path: `/contacts?${params.toString()}`,
    decode: decodeLegacyContacts,
  });
}

export const commandApi = {
  overview: (options?: CommandRequestOptions) => request<Overview>('/overview', { signal: options?.signal }),
  contacts: legacyContacts,
  contactDirectory: (
    directoryRequest: ContactDirectoryRequest,
    options?: CommandRequestOptions,
  ): Promise<ContactDirectoryPage> => contactsApi.directory(directoryRequest, options),
  tasks: (filters: TaskFilters = {}, options?: CommandRequestOptions) => { const params = new URLSearchParams(); if (filters.status) params.set('status', filters.status); if (filters.due_before) params.set('due_before', filters.due_before); if (filters.due_after) params.set('due_after', filters.due_after); return request<Task[]>(`/tasks${params.size ? `?${params.toString()}` : ''}`, { signal: options?.signal }); },
  celebrations: (month: number, options?: CommandRequestOptions) => contactsApi.celebrations(month, options),
  contactWorkspace: (id: number) => request<LegacyContactWorkspace>(`/contacts/${id}/workspace`),
  createContactNote: (id: number, body: string) => request<{ id: number; body: string }>(`/contacts/${id}/notes`, { method: 'POST', body: JSON.stringify({ body }) }),
  createContactSavedSearch: (id: number, name: string, criteria: Record<string, unknown>) => request<{ id: number; name: string; criteria: string }>(`/contacts/${id}/saved-searches`, { method: 'POST', body: JSON.stringify({ name, criteria }) }),
  savedSearches: () => request<SavedSearch[]>('/saved-searches'),
  deleteSavedSearch: (id: number) => request<{ deleted: boolean; id: number }>(`/saved-searches/${id}`, { method: 'DELETE' }),
  createTag: (name: string) => request<{ id: number; name: string }>('/tags', { method: 'POST', body: JSON.stringify({ name }) }),
  assignContactTag: (contactId: number, tagId: number) => request<{ contact_id: number; tag_id: number }>(`/contacts/${contactId}/tags/${tagId}`, { method: 'POST' }),
  removeContactTag: (contactId: number, tagId: number) => request<{ removed: boolean; contact_id: number; tag_id: number }>(`/contacts/${contactId}/tags/${tagId}`, { method: 'DELETE' }),
  deleteContactNote: (contactId: number, noteId: number) => request<{ deleted: boolean; id: number }>(`/contacts/${contactId}/notes/${noteId}`, { method: 'DELETE' }),
  goals: (options?: CommandRequestOptions) => request<Goal[]>('/goals', { signal: options?.signal }),
  createGoal: (payload: Omit<Goal, 'id'>) => request<Goal>('/goals', { method: 'POST', body: JSON.stringify(payload) }),
  updateGoalProgress: (id: number, current_value: number) => request<Goal>(`/goals/${id}`, { method: 'PATCH', body: JSON.stringify({ current_value }) }),
  aiBriefing: (options?: CommandRequestOptions) => request<AiBriefing>('/ai/briefing', { signal: options?.signal }),
  generateAiBriefing: () => request<AiBriefing>('/ai/briefing/generate', { method: 'POST' }),
  createContact: (contact: Omit<Contact, 'id' | 'stage'>) => request<Contact>('/contacts', { method: 'POST', body: JSON.stringify(contact) }),
  importContacts: (contacts: ContactImportRow[]) => request<ContactImportResult>('/contacts/import', { method: 'POST', body: JSON.stringify({ contacts }) }),
  importArchiveBundle: (bundle: ArchiveBundle) => request<ArchiveBundleImportResult>('/archive/import', { method: 'POST', body: JSON.stringify(bundle) }),
  updateContactStage: (id: number, stage: string) => request<Contact>(`/contacts/${id}`, { method: 'PATCH', body: JSON.stringify({ stage }) }),
  updateContact: (id: number, payload: Partial<Pick<Contact, 'first_name' | 'last_name' | 'email' | 'phone' | 'stage' | 'birthday' | 'anniversary'>>) => request<Contact>(`/contacts/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  smartPlans: () => request<NamedRecord[]>('/smart-plans'), createSmartPlan: (payload: Pick<NamedRecord,'name'|'description'>) => request<NamedRecord>('/smart-plans',{method:'POST',body:JSON.stringify(payload)}),
  updateSmartPlanStatus: (id: number, status: 'active' | 'paused' | 'archived') => request<NamedRecord>(`/smart-plans/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  smartPlanWorkspace: (id: number) => request<{ plan: NamedRecord; steps: { id: number; position: number; action_type: string; payload: string }[]; enrollments: SmartPlanEnrollment[] }>(`/smart-plans/${id}/workspace`),
  addSmartPlanStep: (planId: number, position: number, actionType: string, payload: Record<string, unknown>) => request<{ id: number; position: number; action_type: string }>(`/smart-plans/${planId}/steps`, { method: 'POST', body: JSON.stringify({ position, action_type: actionType, payload }) }),
  updateSmartPlanStep: (planId: number, stepId: number, position: number, actionType: string, payload: Record<string, unknown>) => request<{ id: number; position: number; action_type: string }>(`/smart-plans/${planId}/steps/${stepId}`, { method: 'PATCH', body: JSON.stringify({ position, action_type: actionType, payload }) }),
  enrollSmartPlanContact: (planId: number, contactId: number) => request<{ id: number; contact_id: number; status: string }>(`/smart-plans/${planId}/enrollments`, { method: 'POST', body: JSON.stringify({ contact_id: contactId }) }),
  updateSmartPlanEnrollment: (planId: number, enrollmentId: number, status: 'active' | 'paused' | 'completed') => request<{ id: number; status: string }>(`/smart-plans/${planId}/enrollments/${enrollmentId}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  opportunities: (options?: CommandRequestOptions) => request<Opportunity[]>('/opportunities', { signal: options?.signal }), createOpportunity: (payload: Omit<Opportunity,'id'>) => request<Opportunity>('/opportunities',{method:'POST',body:JSON.stringify(payload)}),
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
  archiveArtifacts: (domain?: string, offset = 0) => { const params = new URLSearchParams({ limit: '100', offset: String(offset) }); if (domain) params.set('domain', domain); return request<{ total: number; rows: ArchiveArtifact[] }>(`/archive/artifacts?${params}`); },
  archiveArtifactBlob: (id: number, options?: CommandRequestOptions) => commandBlob({ path: `/archive/artifacts/${id}/content`, signal: options?.signal }),
  reportDetails: (metric: string) => request<ReportDetails>(`/reports/details/${encodeURIComponent(metric)}`),
  createTask: (task: Pick<Task, 'title' | 'description' | 'priority' | 'contact_id' | 'due_at'>) => request<Task>('/tasks', { method: 'POST', body: JSON.stringify(task) }),
  addTaskLink: (taskId: number, entityType: string, entityId: number) => request<TaskLink>(`/tasks/${taskId}/links`, { method: 'POST', body: JSON.stringify({ entity_type: entityType, entity_id: entityId }) }),
  taskLinks: (taskId: number) => request<TaskLink[]>(`/tasks/${taskId}/links`),
  updateTask: (id: number, payload: Partial<Pick<Task, 'title' | 'description' | 'priority' | 'status' | 'due_at' | 'contact_id'>>) => request<Task>(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
};
