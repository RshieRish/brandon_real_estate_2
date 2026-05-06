'use client';

import { useEffect, useState, useCallback } from 'react';
import { CircleNotch, WarningCircle } from '@phosphor-icons/react';
import Tabs from '@/components/admin/link-pack/Tabs';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface DraftStatus {
  has_unpublished_changes: boolean;
  published_at: string | null;
  is_published: boolean;
}

interface DraftPayload {
  live: any;
  status: DraftStatus;
}

export default function LinkPackAdminPage() {
  const [tab, setTab] = useState('profile');
  const [draft, setDraft] = useState<DraftPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const token = localStorage.getItem('admin_token');
    if (!token) {
      setError('Not authenticated.');
      setLoading(false);
      return;
    }
    try {
      const res = await fetch(`${API_URL}/api/v1/link-pack/draft`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`Failed (${res.status})`);
      setDraft(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load draft');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  if (loading) {
    return (
      <div className="p-8">
        <CircleNotch className="animate-spin text-gold w-6 h-6" />
      </div>
    );
  }
  if (error || !draft) {
    return (
      <div className="p-8">
        <div className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/20">
          <WarningCircle weight="fill" className="w-5 h-5 text-red-400" />
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-white font-black text-2xl">Link Pack</h1>
        <a
          href="/links?preview=1"
          target="_blank"
          rel="noreferrer"
          className="text-xs text-white/60 border border-dark-border hover:border-white/30 px-4 py-2 cursor-pointer"
        >
          Preview
        </a>
      </div>

      <Tabs current={tab} onChange={setTab} />

      <div className="bg-dark-card border border-dark-border p-6">
        {tab === 'profile' && <p className="text-white/60 text-sm">Profile tab — Task 28</p>}
        {tab === 'social' && <p className="text-white/60 text-sm">Social tab — Task 29</p>}
        {tab === 'links' && <p className="text-white/60 text-sm">Links tab — Task 31</p>}
        {tab === 'theme' && <p className="text-white/60 text-sm">Theme tab — Task 30</p>}
      </div>
    </div>
  );
}
