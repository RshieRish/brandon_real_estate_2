'use client';
import type { LinkPackItem } from '@/lib/link-pack/types';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function trackClick(itemId: number) {
  try {
    fetch(`${API_URL}/api/v1/link-pack/items/${itemId}/track-click`, {
      method: 'POST',
      keepalive: true,
    });
  } catch {
    /* fire-and-forget */
  }
}

export default function LinkPackButton({ item }: { item: LinkPackItem }) {
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
        borderRadius: 'var(--lp-btn-radius)',
        padding: '14px 24px',
        fontSize: 14,
        fontWeight: 700,
        textAlign: 'center',
        boxShadow: '0 6px 0 0 var(--lp-btn-shadow)',
        border: '2px solid var(--lp-btn-shadow)',
        textDecoration: 'none',
        transition: 'transform 60ms, box-shadow 60ms',
      }}
    >
      {item.title}
    </a>
  );
}
