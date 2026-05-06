'use client';
import { useState } from 'react';
import { Plus } from '@phosphor-icons/react';
import {
  DndContext, closestCenter, PointerSensor, useSensor, useSensors,
  DragEndEvent,
} from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy, arrayMove, useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { LinkPackItem } from '@/lib/link-pack/types';
import LinkRow from './LinkRow';
import LinkEditForm from './LinkEditForm';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function SortableRow({ item, onChanged }: { item: LinkPackItem; onChanged: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item.id });
  return (
    <div ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }}>
      <LinkRow
        item={item}
        onChanged={onChanged}
        dragHandleProps={{ ...attributes, ...listeners }}
        isDragging={isDragging}
      />
    </div>
  );
}

interface Props {
  items: LinkPackItem[];
  onChanged: () => void;
}

export default function LinksTab({ items, onChanged }: Props) {
  const [adding, setAdding] = useState(false);
  const [localItems, setLocalItems] = useState(items);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  // Keep local in sync if parent refreshes
  if (items !== localItems && items.length !== localItems.length) {
    setLocalItems(items);
  }

  const onDragEnd = async (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const oldIdx = localItems.findIndex(i => i.id === e.active.id);
    const newIdx = localItems.findIndex(i => i.id === e.over!.id);
    const next = arrayMove(localItems, oldIdx, newIdx);
    setLocalItems(next);
    const token = localStorage.getItem('admin_token');
    await fetch(`${API_URL}/api/v1/link-pack/items/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ parent_id: null, ordered_ids: next.map(i => i.id) }),
    });
    onChanged();
  };

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
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={localItems.map(i => i.id)} strategy={verticalListSortingStrategy}>
          <div className="space-y-2">
            {localItems.length === 0 ? (
              <p className="text-white/40 text-sm text-center py-8">No links yet. Click &quot;Add link&quot; to get started.</p>
            ) : (
              localItems.map(item => <SortableRow key={item.id} item={item} onChanged={onChanged} />)
            )}
          </div>
        </SortableContext>
      </DndContext>
    </div>
  );
}
