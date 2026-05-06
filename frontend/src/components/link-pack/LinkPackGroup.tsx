'use client';
import type { LinkPackItem } from '@/lib/link-pack/types';
import LinkPackButton from './LinkPackButton';
import LinkPackThumbnailCard from './LinkPackThumbnailCard';
import LinkPackEmailGate from './LinkPackEmailGate';

/**
 * Renders a section header with its children stacked inline beneath it.
 *
 * Mirrors Linktree's `layoutOption: "stack"` group style: the title is a
 * small uppercase header (not a clickable button), and the items in the
 * group are rendered directly underneath, no expand/collapse interaction.
 */
export default function LinkPackGroup({ item }: { item: LinkPackItem }) {
  const activeChildren = (item.children || []).filter(c => c.is_active);
  if (activeChildren.length === 0) {
    // Empty section — render the header alone, dimmed, so admins/users can
    // see the section is intentional but currently empty.
    return (
      <div style={{ width: '100%' }}>
        <h2
          style={{
            color: 'var(--lp-text-color)',
            fontSize: 13,
            fontWeight: 700,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            textAlign: 'center',
            margin: '8px 0 4px',
            opacity: 0.5,
          }}
        >
          {item.title}
        </h2>
      </div>
    );
  }

  return (
    <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <h2
        style={{
          color: 'var(--lp-text-color)',
          fontSize: 13,
          fontWeight: 700,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          textAlign: 'center',
          margin: '8px 0 0',
        }}
      >
        {item.title}
      </h2>
      {activeChildren.map(child => {
        if (child.kind === 'thumbnail') return <LinkPackThumbnailCard key={child.id} item={child} />;
        if (child.kind === 'email_gate') return <LinkPackEmailGate key={child.id} item={child} />;
        return <LinkPackButton key={child.id} item={child} />;
      })}
    </div>
  );
}
