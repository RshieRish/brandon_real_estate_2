'use client';

import { useEffect, useState, useCallback } from 'react';
import { CircleNotch, WarningCircle } from '@phosphor-icons/react';
import Tabs from '@/components/admin/link-pack/Tabs';
import StatusBar from '@/components/admin/link-pack/StatusBar';
import ProfileTab from '@/components/admin/link-pack/ProfileTab';
import SocialTab from '@/components/admin/link-pack/SocialTab';
import ThemeTab from '@/components/admin/link-pack/ThemeTab';

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
      <h1 className="text-white font-black text-2xl">Link Pack</h1>
      <StatusBar
        hasUnpublishedChanges={draft.status.has_unpublished_changes}
        publishedAt={draft.status.published_at}
        isPublished={draft.status.is_published}
        onPublished={refresh}
      />

      <Tabs current={tab} onChange={setTab} />

      <div className="bg-dark-card border border-dark-border p-6">
        {tab === 'profile' && (
          <ProfileTab
            initial={{
              name: draft.live.profile.name,
              bio: draft.live.profile.bio,
              photo_url: draft.live.profile.photo_url,
              is_verified: draft.live.profile.is_verified,
            }}
            onSaved={refresh}
          />
        )}
        {tab === 'social' && <SocialTab initial={draft.live.social} onSaved={refresh} />}
        {tab === 'links' && <p className="text-white/60 text-sm">Links tab — Task 31</p>}
        {tab === 'theme' && (
          <ThemeTab
            initial={draft.live.theme}
            backgroundImageUrl={draft.live.background_image_url}
            onSaved={refresh}
          />
        )}
      </div>
    </div>
  );
}
