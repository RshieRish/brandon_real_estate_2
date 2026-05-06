'use client';
import { useState } from 'react';
import { CircleNotch } from '@phosphor-icons/react';
import type { LinkPackItem, LinkKind, Animation } from '@/lib/link-pack/types';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const KINDS: { value: LinkKind; label: string }[] = [
  { value: 'classic', label: 'Classic button' },
  { value: 'thumbnail', label: 'Thumbnail card (for properties)' },
  { value: 'group', label: 'Group (expandable)' },
  { value: 'email_gate', label: 'Email-gated download' },
];
const ANIMATIONS: Animation[] = ['none', 'pulse', 'wobble', 'shake', 'breathe', 'bounce'];

interface Props {
  existing?: LinkPackItem;
  parentId?: number | null;
  onCancel: () => void;
  onSaved: () => void;
}

export default function LinkEditForm({ existing, parentId, onCancel, onSaved }: Props) {
  const [kind, setKind] = useState<LinkKind>(existing?.kind ?? (parentId ? 'classic' : 'classic'));
  const [title, setTitle] = useState(existing?.title ?? '');
  const [url, setUrl] = useState(existing?.url ?? '');
  const [animation, setAnimation] = useState<Animation>(existing?.animation ?? 'none');
  const [active, setActive] = useState(existing?.is_active ?? true);
  const [headline, setHeadline] = useState(existing?.gate_modal_headline ?? '');
  const [subtext, setSubtext] = useState(existing?.gate_modal_subtext ?? '');
  const [thumbFile, setThumbFile] = useState<File | null>(null);
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const isEdit = !!existing;
  const inGroup = parentId != null;
  const usableKinds = inGroup ? KINDS.filter(k => k.value !== 'group') : KINDS;

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      const token = localStorage.getItem('admin_token');
      let itemId = existing?.id;

      if (!isEdit) {
        const body = {
          kind, title, url: url || null, parent_id: parentId ?? null,
          animation, is_active: active,
          gate_modal_headline: kind === 'email_gate' ? (headline || null) : null,
          gate_modal_subtext: kind === 'email_gate' ? (subtext || null) : null,
        };
        const res = await fetch(`${API_URL}/api/v1/link-pack/items`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error((await res.json()).detail ?? 'Create failed');
        const created = await res.json();
        itemId = created.id;
      } else {
        const body = {
          title, url: url || null, animation, is_active: active,
          gate_modal_headline: kind === 'email_gate' ? (headline || null) : null,
          gate_modal_subtext: kind === 'email_gate' ? (subtext || null) : null,
        };
        const res = await fetch(`${API_URL}/api/v1/link-pack/items/${itemId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error('Update failed');
      }

      if (thumbFile && itemId) {
        const form = new FormData();
        form.append('file', thumbFile);
        await fetch(`${API_URL}/api/v1/link-pack/items/${itemId}/thumbnail`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: form,
        });
      }
      if (pdfFile && itemId) {
        const form = new FormData();
        form.append('file', pdfFile);
        await fetch(`${API_URL}/api/v1/link-pack/items/${itemId}/gated-file`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: form,
        });
      }

      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-dark-surface border border-dark-border p-4 space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="text-white/40 text-xs block mb-1">Title</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full bg-dark-card border border-dark-border text-white text-sm px-3 py-2"
          />
        </div>
        <div>
          <label className="text-white/40 text-xs block mb-1">Type</label>
          <select
            value={kind}
            disabled={isEdit}
            onChange={(e) => setKind(e.target.value as LinkKind)}
            className="w-full bg-dark-card border border-dark-border text-white text-sm px-3 py-2 disabled:opacity-60"
          >
            {usableKinds.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
        </div>
      </div>

      {kind !== 'group' && (
        <div>
          <label className="text-white/40 text-xs block mb-1">URL{kind === 'email_gate' ? ' (optional fallback)' : ''}</label>
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="w-full bg-dark-card border border-dark-border text-white text-sm px-3 py-2"
          />
        </div>
      )}

      {kind === 'thumbnail' && (
        <div>
          <label className="text-white/40 text-xs block mb-1">Thumbnail image</label>
          <input
            type="file"
            accept="image/*"
            onChange={(e) => setThumbFile(e.target.files?.[0] ?? null)}
            className="text-white/70 text-xs"
          />
        </div>
      )}

      {kind === 'email_gate' && (
        <>
          <div>
            <label className="text-white/40 text-xs block mb-1">Modal headline</label>
            <input
              value={headline}
              onChange={(e) => setHeadline(e.target.value)}
              className="w-full bg-dark-card border border-dark-border text-white text-sm px-3 py-2"
            />
          </div>
          <div>
            <label className="text-white/40 text-xs block mb-1">Modal subtext</label>
            <textarea
              rows={2}
              value={subtext}
              onChange={(e) => setSubtext(e.target.value)}
              className="w-full bg-dark-card border border-dark-border text-white text-sm px-3 py-2 resize-none"
            />
          </div>
          <div>
            <label className="text-white/40 text-xs block mb-1">Gated PDF (max 10MB)</label>
            <input
              type="file"
              accept="application/pdf"
              onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)}
              className="text-white/70 text-xs"
            />
          </div>
        </>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="text-white/40 text-xs block mb-1">Animation</label>
          <select
            value={animation}
            onChange={(e) => setAnimation(e.target.value as Animation)}
            className="w-full bg-dark-card border border-dark-border text-white text-sm px-3 py-2"
          >
            {ANIMATIONS.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <label className="flex items-center gap-2 text-white/70 text-sm cursor-pointer mt-6">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
          Active (visible on public page)
        </label>
      </div>

      {err && <p className="text-red-400 text-xs">{err}</p>}

      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} className="text-xs text-white/40 border border-dark-border px-4 py-2 cursor-pointer">
          Cancel
        </button>
        <button
          onClick={save}
          disabled={saving || !title}
          className="flex items-center gap-2 text-xs bg-gold text-dark-surface font-bold uppercase tracking-widest px-4 py-2 hover:bg-gold-hover disabled:opacity-60 cursor-pointer"
        >
          {saving ? <CircleNotch size={12} className="animate-spin" /> : null}
          {isEdit ? 'Save' : 'Add link'}
        </button>
      </div>
    </div>
  );
}
