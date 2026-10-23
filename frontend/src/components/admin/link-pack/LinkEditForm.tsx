'use client';
import { useEffect, useId, useState } from 'react';
import { CircleNotch } from '@phosphor-icons/react';
import { imageUrl } from '@/lib/link-pack/api';
import type { LinkPackItem, LinkKind, Animation } from '@/lib/link-pack/types';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const KINDS: { value: LinkKind; label: string }[] = [
  { value: 'classic', label: 'Classic button' },
  { value: 'thumbnail', label: 'Thumbnail card (for properties)' },
  { value: 'group', label: 'Group (expandable)' },
  { value: 'email_gate', label: 'Email-gated download' },
];
const ANIMATIONS: Animation[] = ['none', 'pulse', 'wobble', 'shake', 'breathe', 'bounce'];

async function checkResponse(response: Response, fallback: string) {
  if (response.ok) return;
  const error = await response.json().catch(() => null);
  throw new Error(typeof error?.detail === 'string' ? error.detail : fallback);
}

interface Props {
  existing?: LinkPackItem;
  parentId?: number | null;
  onCancel: () => void;
  onSaved: () => void;
}

export default function LinkEditForm({ existing, parentId, onCancel, onSaved }: Props) {
  const [itemId, setItemId] = useState(existing?.id);
  const [kind, setKind] = useState<LinkKind>(existing?.kind ?? (parentId ? 'classic' : 'classic'));
  const [title, setTitle] = useState(existing?.title ?? '');
  const [url, setUrl] = useState(existing?.url ?? '');
  const [animation, setAnimation] = useState<Animation>(existing?.animation ?? 'none');
  const [active, setActive] = useState(existing?.is_active ?? true);
  const [headline, setHeadline] = useState(existing?.gate_modal_headline ?? '');
  const [subtext, setSubtext] = useState(existing?.gate_modal_subtext ?? '');
  const [thumbFile, setThumbFile] = useState<File | null>(null);
  const [thumbPreview, setThumbPreview] = useState<string | null>(null);
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const thumbnailId = useId();
  const preview = thumbPreview ?? imageUrl(existing?.thumbnail_url ?? null);
  useEffect(() => {
    if (thumbPreview) return () => URL.revokeObjectURL(thumbPreview);
  }, [thumbPreview]);

  const isEdit = itemId != null;
  const inGroup = parentId != null;
  const usableKinds = inGroup ? KINDS.filter(k => k.value !== 'group') : KINDS;

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      const token = localStorage.getItem('admin_token');
      if (!token) throw new Error('Please sign in again before saving.');
      let savedItemId = itemId;

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
        await checkResponse(res, 'Create failed');
        const created = await res.json();
        savedItemId = created.id;
        setItemId(created.id);
      } else {
        const body = {
          title, url: url || null, animation, is_active: active,
          gate_modal_headline: kind === 'email_gate' ? (headline || null) : null,
          gate_modal_subtext: kind === 'email_gate' ? (subtext || null) : null,
        };
        const res = await fetch(`${API_URL}/api/v1/link-pack/items/${savedItemId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(body),
        });
        await checkResponse(res, 'Update failed');
      }

      if (thumbFile && savedItemId) {
        const form = new FormData();
        form.append('file', thumbFile);
        const res = await fetch(`${API_URL}/api/v1/link-pack/items/${savedItemId}/thumbnail`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: form,
        });
        await checkResponse(res, 'Photo upload failed. Please try again.');
      }
      if (pdfFile && savedItemId) {
        const form = new FormData();
        form.append('file', pdfFile);
        const res = await fetch(`${API_URL}/api/v1/link-pack/items/${savedItemId}/gated-file`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: form,
        });
        await checkResponse(res, 'PDF upload failed. Please try again.');
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
        <div className="space-y-2">
          <label htmlFor={thumbnailId} className="text-white/40 text-xs block mb-1">Thumbnail image</label>
          {preview && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={preview} alt={`${title || 'Listing'} thumbnail`} className="w-full max-w-sm aspect-video object-cover rounded-lg border border-dark-border" />
          )}
          <p className="text-white/50 text-xs">
            {thumbFile ? `Selected photo: ${thumbFile.name}` : existing?.thumbnail_url
              ? 'Saved photo. Choose a file to replace it.' : 'No photo saved yet.'}
          </p>
          <input
            id={thumbnailId}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            disabled={saving}
            onChange={(e) => {
              const file = e.target.files?.[0] ?? null;
              setThumbFile(file);
              setThumbPreview(file ? URL.createObjectURL(file) : null);
            }}
            className="max-w-full text-white/70 text-xs"
          />
          <p className="text-white/40 text-xs">JPG, PNG, WebP or GIF. Photos up to 20 MB; animations up to 5 MB. Large photos are resized automatically.</p>
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

      {err && <p role="alert" className="text-red-400 text-xs">{err}</p>}

      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} disabled={saving} className="text-xs text-white/40 border border-dark-border px-4 py-2 disabled:opacity-60 cursor-pointer">
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
