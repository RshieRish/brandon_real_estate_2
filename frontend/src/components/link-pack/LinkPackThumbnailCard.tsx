'use client';
import type { LinkPackItem } from '@/lib/link-pack/types';
import { imageUrl } from '@/lib/link-pack/api';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function trackClick(id: number) {
  try {
    fetch(`${API_URL}/api/v1/link-pack/items/${id}/track-click`, { method: 'POST', keepalive: true });
  } catch { /* noop */ }
}

/**
 * Property-listing card: full-width hero image + title row beneath.
 * Mirrors the "featured" link layout used on Linktree for property cards.
 */
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
        display: 'block',
        width: '100%',
        background: 'var(--lp-btn-bg)',
        color: 'var(--lp-btn-text)',
        borderRadius: 24,
        boxShadow: '0 6px 0 0 var(--lp-btn-shadow)',
        border: '2px solid var(--lp-btn-shadow)',
        overflow: 'hidden',
        textDecoration: 'none',
        transition: 'transform 60ms, box-shadow 60ms',
      }}
    >
      <div
        style={{
          width: '100%',
          aspectRatio: '16 / 11',
          background: '#eee',
          backgroundImage: thumb ? `url(${thumb})` : undefined,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
      />
      <div
        style={{
          padding: '14px 16px',
          fontSize: 14,
          fontWeight: 600,
          lineHeight: 1.3,
          textAlign: 'left',
        }}
      >
        {item.title}
      </div>
    </a>
  );
}
