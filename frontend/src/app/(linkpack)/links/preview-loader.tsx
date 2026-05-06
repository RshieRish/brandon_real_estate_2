'use client';
import { useEffect, useState } from 'react';
import LinkPackPage from '@/components/link-pack/LinkPackPage';
import type { LinkPackSnapshot } from '@/lib/link-pack/types';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export default function PreviewLoader() {
  const [snap, setSnap] = useState<LinkPackSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = localStorage.getItem('admin_token');
    if (!token) {
      window.location.href = '/admin/login';
      return;
    }
    fetch(`${API_URL}/api/v1/link-pack/draft`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : Promise.reject('Auth required'))
      .then(data => setSnap(data.live))
      .catch(e => setError(typeof e === 'string' ? e : 'Failed to load preview'));
  }, []);

  if (error) return <div style={{ padding: 24, color: '#fff' }}>Preview error: {error}</div>;
  if (!snap) return <div style={{ padding: 24, color: '#fff' }}>Loading preview…</div>;
  return <LinkPackPage snapshot={snap} />;
}
