'use client';
import { useState } from 'react';
import { CircleNotch } from '@phosphor-icons/react';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const FIELDS = [
  { key: 'social_phone', label: 'Phone', placeholder: '+1 555 123 4567' },
  { key: 'social_email', label: 'Email', placeholder: 'you@example.com' },
  { key: 'social_instagram', label: 'Instagram', placeholder: '@handle or full URL' },
  { key: 'social_facebook', label: 'Facebook', placeholder: 'page-name or full URL' },
  { key: 'social_youtube', label: 'YouTube', placeholder: '@channel or full URL' },
  { key: 'social_website', label: 'Website', placeholder: 'soldwithsweeney.com' },
  { key: 'social_tiktok', label: 'TikTok', placeholder: '@handle or full URL' },
  { key: 'social_x', label: 'X', placeholder: '@handle or full URL' },
] as const;

interface Props {
  initial: Record<string, string | null>;
  onSaved: () => void;
}

export default function SocialTab({ initial, onSaved }: Props) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(FIELDS.map(f => [f.key, initial[f.key.replace('social_', '')] ?? '']))
  );
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const token = localStorage.getItem('admin_token');
      const body = Object.fromEntries(
        Object.entries(values).map(([k, v]) => [k, v.trim() || null])
      );
      const res = await fetch(`${API_URL}/api/v1/link-pack/social`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error('Save failed');
      setMsg('Saved.');
      onSaved();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-3xl">
      {FIELDS.map(f => (
        <div key={f.key}>
          <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">{f.label}</label>
          <input
            value={values[f.key]}
            onChange={(e) => setValues(v => ({ ...v, [f.key]: e.target.value }))}
            placeholder={f.placeholder}
            className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 focus:outline-none focus:border-gold"
          />
        </div>
      ))}
      <div className="md:col-span-2 flex items-center gap-3 pt-2">
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-2 text-xs bg-gold text-dark-surface font-bold uppercase tracking-widest px-4 py-2 hover:bg-gold-hover disabled:opacity-60 cursor-pointer"
        >
          {saving ? <CircleNotch size={12} className="animate-spin" /> : null}
          Save social
        </button>
        {msg && <span className="text-xs text-white/60">{msg}</span>}
      </div>
    </div>
  );
}
