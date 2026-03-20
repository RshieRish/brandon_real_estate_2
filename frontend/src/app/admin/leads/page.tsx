'use client';

import { useEffect, useState } from 'react';
import { Users, WarningCircle, X } from '@phosphor-icons/react';

interface Lead {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  lead_type: string;
  source: string;
  status: string;
  notes: string | null;
  created_at: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const STATUS_FILTERS = ['all', 'new', 'contacted', 'qualified', 'closed'] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

function statusBadge(status: string) {
  switch (status) {
    case 'new':
      return 'bg-blue-500/20 text-blue-400';
    case 'contacted':
      return 'bg-gold/20 text-gold';
    case 'qualified':
      return 'bg-green-500/20 text-green-400';
    case 'closed':
      return 'bg-white/10 text-white/40';
    default:
      return 'bg-white/10 text-white/40';
  }
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [notesDraft, setNotesDraft] = useState('');

  useEffect(() => {
    const fetchLeads = async () => {
      const token = localStorage.getItem('admin_token');
      if (!token) {
        setError('Not authenticated. Please log in.');
        setIsLoading(false);
        return;
      }
      try {
        const res = await fetch(`${API_URL}/api/v1/leads/?limit=100`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error('Failed to load leads');
        const data = await res.json();
        setLeads(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        setIsLoading(false);
      }
    };
    fetchLeads();
  }, []);

  const filteredLeads =
    statusFilter === 'all' ? leads : leads.filter((l) => l.status === statusFilter);

  const handleSelectLead = (lead: Lead) => {
    setSelectedLead(lead);
    setNotesDraft(lead.notes ?? '');
  };

  const handleStatusChange = async (newStatus: string) => {
    if (!selectedLead) return;
    const token = localStorage.getItem('admin_token');
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/api/v1/leads/${selectedLead.id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ status: newStatus }),
      });
      if (!res.ok) return;
      const updated = { ...selectedLead, status: newStatus };
      setSelectedLead(updated);
      setLeads((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
    } catch (err) {
      console.error('Failed to save status:', err);
    }
  };

  const handleNotesBlur = async () => {
    if (!selectedLead) return;
    if (notesDraft === (selectedLead?.notes ?? '')) return;
    const token = localStorage.getItem('admin_token');
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/api/v1/leads/${selectedLead.id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ notes: notesDraft }),
      });
      if (!res.ok) return;
      const updated = { ...selectedLead, notes: notesDraft };
      setSelectedLead(updated);
      setLeads((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
    } catch (err) {
      console.error('Failed to save:', err);
    }
  };

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-white font-black text-2xl">Leads</h1>
        {!isLoading && !error && (
          <span className="bg-gold/20 text-gold text-xs font-bold px-2.5 py-1 rounded-full uppercase tracking-widest">
            {leads.length}
          </span>
        )}
      </div>

      {/* Filter pills */}
      <div className="flex gap-2 mb-6 flex-wrap">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setStatusFilter(f)}
            className={`px-4 py-1.5 rounded-full text-xs font-semibold uppercase tracking-widest border transition-colors cursor-pointer ${
              statusFilter === f
                ? 'border-gold text-gold bg-gold/10'
                : 'border-dark-border text-white/40 hover:text-white/70'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Error state */}
      {error && (
        <div className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/20 rounded mb-6">
          <WarningCircle weight="fill" className="w-5 h-5 text-red-400 flex-shrink-0" />
          <div>
            <p className="text-red-400 text-sm font-medium">Failed to load leads</p>
            <p className="text-white/40 text-xs mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Table */}
      {!error && (
        <div className="overflow-x-auto">
          <table className="w-full border border-dark-border text-sm">
            <thead>
              <tr className="border-b border-dark-border">
                {['Name', 'Email', 'Type', 'Source', 'Status', 'Date', 'Actions'].map((col) => (
                  <th
                    key={col}
                    className="text-white/40 text-xs tracking-widest uppercase font-semibold px-4 py-3 text-left"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="border-b border-dark-border">
                    {Array.from({ length: 7 }).map((__, j) => (
                      <td key={j} className="px-4 py-4">
                        <div className="h-4 bg-dark-border rounded animate-pulse" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : filteredLeads.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-16 text-center">
                    <div className="flex flex-col items-center gap-3">
                      <Users size={36} className="text-white/20" />
                      <p className="text-white/40 text-sm">No leads yet</p>
                    </div>
                  </td>
                </tr>
              ) : (
                filteredLeads.map((lead) => (
                  <tr
                    key={lead.id}
                    className="border-b border-dark-border hover:bg-dark-surface/50 transition-colors"
                  >
                    <td className="px-4 py-3 text-white font-medium">{lead.name}</td>
                    <td className="px-4 py-3 text-white/70">{lead.email}</td>
                    <td className="px-4 py-3 text-white/70 capitalize">{lead.lead_type}</td>
                    <td className="px-4 py-3 text-white/70 capitalize">{lead.source}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block px-2.5 py-1 rounded-full text-xs font-semibold uppercase tracking-wider ${statusBadge(lead.status)}`}
                      >
                        {lead.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-white/40 text-xs">
                      {new Date(lead.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => handleSelectLead(lead)}
                        className="text-xs text-gold border border-gold/30 hover:bg-gold/10 px-3 py-1.5 rounded transition-colors cursor-pointer"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail panel */}
      {selectedLead && (
        <div className="fixed top-0 right-0 w-80 h-full bg-dark-card border-l border-dark-border p-6 z-50 overflow-y-auto">
          <div className="flex items-start justify-between mb-6">
            <h2 className="text-white font-bold text-base leading-snug">{selectedLead.name}</h2>
            <button
              onClick={() => setSelectedLead(null)}
              aria-label="Close lead detail"
              className="text-white/40 hover:text-white transition-colors cursor-pointer ml-3 flex-shrink-0"
            >
              <X size={18} />
            </button>
          </div>

          <div className="space-y-4 mb-6">
            {[
              { label: 'Email', value: selectedLead.email },
              { label: 'Phone', value: selectedLead.phone ?? '—' },
              { label: 'Type', value: selectedLead.lead_type },
              { label: 'Source', value: selectedLead.source },
            ].map(({ label, value }) => (
              <div key={label}>
                <p className="text-white/40 text-xs uppercase tracking-widest mb-1">{label}</p>
                <p className="text-white/80 text-sm capitalize">{value}</p>
              </div>
            ))}
          </div>

          {/* Status select */}
          <div className="mb-4">
            <label className="text-white/40 text-xs uppercase tracking-widest block mb-2">
              Status
            </label>
            <select
              value={selectedLead.status}
              onChange={(e) => handleStatusChange(e.target.value)}
              className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 rounded focus:outline-none focus:border-gold cursor-pointer"
            >
              {['new', 'contacted', 'qualified', 'closed'].map((s) => (
                <option key={s} value={s} className="bg-dark-surface">
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </option>
              ))}
            </select>
          </div>

          {/* Notes textarea */}
          <div>
            <label className="text-white/40 text-xs uppercase tracking-widest block mb-2">
              Notes
            </label>
            <textarea
              value={notesDraft}
              onChange={(e) => setNotesDraft(e.target.value)}
              onBlur={handleNotesBlur}
              rows={5}
              placeholder="Add notes..."
              className="w-full bg-dark-surface border border-dark-border text-white/80 text-sm px-3 py-2 rounded resize-none focus:outline-none focus:border-gold placeholder:text-white/20"
            />
          </div>
        </div>
      )}
    </div>
  );
}
