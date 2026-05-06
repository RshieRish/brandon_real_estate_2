'use client';
import type { LinkPackItem } from '@/lib/link-pack/types';
import { imageUrl } from '@/lib/link-pack/api';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function trackClick(id: number) {
  try {
    fetch(`${API_URL}/api/v1/link-pack/items/${id}/track-click`, { method: 'POST', keepalive: true });
  } catch { /* noop */ }
}

export default function LinkPackThumbnailCard({ item }: { item: LinkPackItem }) {
  const thumb = imageUrl(item.thumbnail_url);
  return (
    <a
      href={item.url ?? '#'}
      target="_blank"
      rel="noreferrer noopener"
      onClick={() => trackClick(item.id)}
      className={`lp-btn lp-anim-${item.animation}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        background: 'var(--lp-btn-bg)',
        color: 'var(--lp-btn-text)',
        borderRadius: 'var(--lp-btn-radius)',
        padding: 8,
        boxShadow: '0 6px 0 0 var(--lp-btn-shadow)',
        textDecoration: 'none',
        transition: 'transform 60ms, box-shadow 60ms',
      }}
    >
      <div
        style={{
          width: 56,
          height: 56,
          flexShrink: 0,
          background: '#eee',
          borderRadius: 'calc(var(--lp-btn-radius) - 4px)',
          overflow: 'hidden',
          backgroundImage: thumb ? `url(${thumb})` : undefined,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
      />
      <span style={{ flex: 1, fontSize: 15, fontWeight: 600, paddingRight: 12 }}>{item.title}</span>
    </a>
  );
}
