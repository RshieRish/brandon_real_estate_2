'use client';
import { useState } from 'react';
import { Plus } from '@phosphor-icons/react';
import type { LinkPackItem } from '@/lib/link-pack/types';
import LinkRow from './LinkRow';
import LinkEditForm from './LinkEditForm';

interface Props {
  items: LinkPackItem[];
  onChanged: () => void;
}

export default function LinksTab({ items, onChanged }: Props) {
  const [adding, setAdding] = useState(false);
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button
          onClick={() => setAdding(true)}
          className="flex items-center gap-2 bg-gold text-dark-surface text-xs font-bold uppercase tracking-widest px-4 py-2.5 hover:bg-gold-hover cursor-pointer"
        >
          <Plus size={14} weight="bold" /> Add link
        </button>
      </div>
      {adding && (
        <LinkEditForm onCancel={() => setAdding(false)} onSaved={() => { setAdding(false); onChanged(); }} />
      )}
      <div className="space-y-2">
        {items.length === 0 ? (
          <p className="text-white/40 text-sm text-center py-8">No links yet. Click &quot;Add link&quot; to get started.</p>
        ) : (
          items.map(item => <LinkRow key={item.id} item={item} onChanged={onChanged} />)
        )}
      </div>
    </div>
  );
}
