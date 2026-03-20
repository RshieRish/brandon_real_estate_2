'use client';

import { useEffect, useState } from 'react';
import { Plus, WarningCircle, CircleNotch } from '@phosphor-icons/react';

interface Funnel {
  id: number;
  title: string;
  slug: string;
  audience: string;
  status: string;
  registrations: number | null;
  created_at: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const AUDIENCE_OPTIONS = ['buyer', 'seller', 'investor'] as const;

export default function FunnelsPage() {
  const [funnels, setFunnels] = useState<Funnel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [form, setForm] = useState({
    title: '',
    audience: 'buyer',
    description: '',
    cta_text: '',
  });

  useEffect(() => {
    const fetchFunnels = async () => {
      const token = localStorage.getItem('admin_token');
      if (!token) {
        setError('Not authenticated. Please log in.');
        setIsLoading(false);
        return;
      }
      try {
        const res = await fetch(`${API_URL}/api/v1/funnels/`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error('Failed to load funnels');
        const data = await res.json();
        setFunnels(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        setIsLoading(false);
      }
    };
    fetchFunnels();
  }, []);

  const handlePublish = async (id: number) => {
    const token = localStorage.getItem('admin_token');
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/api/v1/funnels/${id}/publish`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return;
      setFunnels((prev) =>
        prev.map((f) => (f.id === id ? { ...f, status: 'published' } : f))
      );
    } catch {
      // silently fail
    }
  };

  const handleCopyLink = (funnel: Funnel) => {
    navigator.clipboard.writeText(window.location.origin + '/f/' + funnel.slug);
    setCopiedId(funnel.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem('admin_token');
    if (!token) return;
    setIsCreating(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/funnels/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(form),
      });
      if (!res.ok) throw new Error('Failed to create funnel');
      const newFunnel: Funnel = await res.json();
      setFunnels((prev) => [newFunnel, ...prev]);
      setShowCreate(false);
      setForm({ title: '', audience: 'buyer', description: '', cta_text: '' });
    } catch {
      // silently fail
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-white font-black text-2xl">Funnels</h1>
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="flex items-center gap-2 bg-gold text-dark-surface text-xs font-bold uppercase tracking-widest px-4 py-2.5 rounded hover:bg-gold-hover transition-colors cursor-pointer"
        >
          <Plus size={14} weight="bold" />
          New Funnel
        </button>
      </div>

      {/* Error state */}
      {error && (
        <div className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/20 rounded mb-6">
          <WarningCircle weight="fill" className="w-5 h-5 text-red-400 flex-shrink-0" />
          <div>
            <p className="text-red-400 text-sm font-medium">Failed to load funnels</p>
            <p className="text-white/40 text-xs mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Table */}
      {!error && (
        <div className="overflow-x-auto mb-6">
          <table className="w-full border border-dark-border text-sm">
            <thead>
              <tr className="border-b border-dark-border">
                {['Title', 'Audience', 'Status', 'Registrations', 'Date', 'Actions'].map((col) => (
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
              {isLoading
                ? Array.from({ length: 4 }).map((_, i) => (
                    <tr key={i} className="border-b border-dark-border">
                      {Array.from({ length: 6 }).map((__, j) => (
                        <td key={j} className="px-4 py-4">
                          <div className="h-4 bg-dark-border rounded animate-pulse" />
                        </td>
                      ))}
                    </tr>
                  ))
                : funnels.map((funnel) => (
                    <tr
                      key={funnel.id}
                      className="border-b border-dark-border hover:bg-dark-surface/50 transition-colors"
                    >
                      <td className="px-4 py-3 text-white font-medium">{funnel.title}</td>
                      <td className="px-4 py-3 text-white/70 capitalize">{funnel.audience}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block px-2.5 py-1 rounded-full text-xs font-semibold uppercase tracking-wider ${
                            funnel.status === 'published'
                              ? 'bg-green-500/20 text-green-400'
                              : 'bg-white/10 text-white/40'
                          }`}
                        >
                          {funnel.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-white/70">
                        {funnel.registrations ?? 0}
                      </td>
                      <td className="px-4 py-3 text-white/40 text-xs">
                        {new Date(funnel.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3">
                        {funnel.status === 'draft' ? (
                          <button
                            onClick={() => handlePublish(funnel.id)}
                            className="text-xs text-green-400 border border-green-500/30 hover:bg-green-500/10 px-3 py-1.5 rounded transition-colors cursor-pointer"
                          >
                            Publish
                          </button>
                        ) : (
                          <button
                            onClick={() => handleCopyLink(funnel)}
                            className="text-xs text-gold border border-gold/30 hover:bg-gold/10 px-3 py-1.5 rounded transition-colors cursor-pointer"
                          >
                            {copiedId === funnel.id ? 'Copied!' : 'Copy Link'}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div className="bg-dark-card border border-dark-border p-6 rounded mt-4">
          <h2 className="text-white font-bold text-sm mb-4 uppercase tracking-widest">
            New Funnel
          </h2>
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                Title
              </label>
              <input
                type="text"
                required
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 rounded focus:outline-none focus:border-gold"
                placeholder="e.g. First-Time Buyer Guide"
              />
            </div>

            <div>
              <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                Audience
              </label>
              <select
                value={form.audience}
                onChange={(e) => setForm((f) => ({ ...f, audience: e.target.value }))}
                className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 rounded focus:outline-none focus:border-gold cursor-pointer"
              >
                {AUDIENCE_OPTIONS.map((a) => (
                  <option key={a} value={a} className="bg-dark-surface">
                    {a.charAt(0).toUpperCase() + a.slice(1)}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                Description
              </label>
              <textarea
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                rows={3}
                className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 rounded resize-none focus:outline-none focus:border-gold"
                placeholder="Describe the funnel..."
              />
            </div>

            <div>
              <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                CTA Text
              </label>
              <input
                type="text"
                value={form.cta_text}
                onChange={(e) => setForm((f) => ({ ...f, cta_text: e.target.value }))}
                className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 rounded focus:outline-none focus:border-gold"
                placeholder="e.g. Book My Free Strategy Call"
              />
            </div>

            <div className="flex gap-3 justify-end pt-2">
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="text-xs text-white/40 border border-dark-border hover:border-white/20 px-4 py-2 rounded transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isCreating}
                className="flex items-center gap-2 text-xs bg-gold text-dark-surface font-bold uppercase tracking-widest px-4 py-2 rounded hover:bg-gold-hover transition-colors disabled:opacity-60 cursor-pointer"
              >
                {isCreating ? (
                  <>
                    <CircleNotch size={14} className="animate-spin" />
                    Generating with AI...
                  </>
                ) : (
                  'Create Funnel'
                )}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
