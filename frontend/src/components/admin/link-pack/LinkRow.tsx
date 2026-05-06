'use client';
import { useState } from 'react';
import { Pencil, Trash, CaretDown, Plus, DotsSixVertical } from '@phosphor-icons/react';
import type { LinkPackItem } from '@/lib/link-pack/types';
import LinkEditForm from './LinkEditForm';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface Props {
  item: LinkPackItem;
  depth?: number;
  onChanged: () => void;
  dragHandleProps?: any;
  isDragging?: boolean;
}

export default function LinkRow({ item, depth = 0, onChanged, dragHandleProps, isDragging }: Props) {
  const [editing, setEditing] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [adding, setAdding] = useState(false);

  const remove = async () => {
    if (!confirm('Delete this link?')) return;
    const token = localStorage.getItem('admin_token');
    const res = await fetch(`${API_URL}/api/v1/link-pack/items/${item.id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) onChanged();
  };

  return (
    <div className={`border border-dark-border ${isDragging ? 'opacity-50' : ''}`} style={{ marginLeft: depth * 24 }}>
      <div className="flex items-center gap-3 p-3 bg-dark-card">
        {dragHandleProps && (
          <div {...dragHandleProps} className="cursor-grab text-white/30 hover:text-white/70">
            <DotsSixVertical size={16} />
          </div>
        )}
        <div className="flex-1">
          <p className="text-white text-sm font-medium">{item.title}</p>
          <div className="flex gap-2 mt-1">
            <span className="text-[10px] uppercase tracking-wider text-white/40 px-2 py-0.5 bg-white/5 border border-white/10">
              {item.kind}
            </span>
            {item.animation !== 'none' && (
              <span className="text-[10px] uppercase tracking-wider text-gold/70 px-2 py-0.5 bg-gold/10 border border-gold/20">
                {item.animation}
              </span>
            )}
            {!item.is_active && (
              <span className="text-[10px] uppercase tracking-wider text-red-400 px-2 py-0.5 bg-red-500/10 border border-red-500/20">
                hidden
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {item.kind === 'group' && (
            <button onClick={() => setExpanded(e => !e)} className="text-white/60 hover:text-white p-2">
              <CaretDown size={14} className={`transition-transform ${expanded ? 'rotate-180' : ''}`} />
            </button>
          )}
          <button onClick={() => setEditing(true)} className="text-white/60 hover:text-white p-2">
            <Pencil size={14} />
          </button>
          <button onClick={remove} className="text-red-400/70 hover:text-red-400 p-2">
            <Trash size={14} />
          </button>
        </div>
      </div>
      {editing && (
        <div className="p-3 bg-dark-surface border-t border-dark-border">
          <LinkEditForm
            existing={item}
            onCancel={() => setEditing(false)}
            onSaved={() => { setEditing(false); onChanged(); }}
          />
        </div>
      )}
      {item.kind === 'group' && expanded && (
        <div className="border-t border-dark-border p-3 bg-dark-surface space-y-2">
          {item.children.map(child => (
            <LinkRow key={child.id} item={child} depth={depth + 1} onChanged={onChanged} />
          ))}
          {adding ? (
            <LinkEditForm parentId={item.id} onCancel={() => setAdding(false)} onSaved={() => { setAdding(false); onChanged(); }} />
          ) : (
            <button
              onClick={() => setAdding(true)}
              className="flex items-center gap-2 text-xs text-white/60 border border-dashed border-dark-border hover:border-gold/40 px-4 py-2 cursor-pointer"
            >
              <Plus size={12} /> Add child
            </button>
          )}
        </div>
      )}
    </div>
  );
}
