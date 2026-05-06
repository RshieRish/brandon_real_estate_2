'use client';
import { useState, useId } from 'react';
import { CaretDown } from '@phosphor-icons/react';
import type { LinkPackItem } from '@/lib/link-pack/types';
import LinkPackButton from './LinkPackButton';
import LinkPackThumbnailCard from './LinkPackThumbnailCard';

export default function LinkPackGroup({ item }: { item: LinkPackItem }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const activeChildren = (item.children || []).filter(c => c.is_active);
  const isEmpty = activeChildren.length === 0;

  return (
    <div style={{ width: '100%' }}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        disabled={isEmpty}
        onClick={() => !isEmpty && setOpen(o => !o)}
        className={`lp-btn lp-anim-${item.animation}`}
        style={{
          width: '100%',
          background: 'var(--lp-btn-bg)',
          color: 'var(--lp-btn-text)',
          borderRadius: 'var(--lp-btn-radius)',
          padding: '16px 24px',
          fontSize: 15,
          fontWeight: 600,
          boxShadow: isEmpty ? 'none' : '0 6px 0 0 var(--lp-btn-shadow)',
          opacity: isEmpty ? 0.6 : 1,
          cursor: isEmpty ? 'default' : 'pointer',
          border: 'none',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 8,
          position: 'relative',
        }}
      >
        <span>{item.title}</span>
        {!isEmpty && (
          <CaretDown
            size={16}
            weight="bold"
            style={{
              position: 'absolute',
              right: 24,
              transition: 'transform 200ms',
              transform: open ? 'rotate(180deg)' : 'rotate(0)',
            }}
          />
        )}
      </button>
      <div
        id={panelId}
        style={{
          display: 'grid',
          gridTemplateRows: open ? '1fr' : '0fr',
          transition: 'grid-template-rows 250ms ease',
        }}
      >
        <div style={{ overflow: 'hidden' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '12px 12px 0' }}>
            {activeChildren.map(child => {
              if (child.kind === 'thumbnail') return <LinkPackThumbnailCard key={child.id} item={child} />;
              return <LinkPackButton key={child.id} item={child} />;
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
