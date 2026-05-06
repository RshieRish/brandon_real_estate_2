'use client';
import { useState } from 'react';
import { CircleNotch } from '@phosphor-icons/react';
import type { LinkPackTheme } from '@/lib/link-pack/types';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const FONTS = ['Montserrat', 'Inter', 'Roboto', 'Poppins', 'Playfair Display'] as const;
const CORNERS = ['pill', 'rounded', 'square'] as const;

const DEFAULT_THEME: LinkPackTheme = {
  background: { type: 'image', color: '#c78829' },
  button: { bg: '#ffffff', text: '#1E2330', shadow: '#eac469', corner: 'pill' },
  social: { color: '#ffffff' },
  typography: { font: 'Montserrat', color: '#ffffff' },
};

interface Props {
  initial: LinkPackTheme;
  backgroundImageUrl: string | null;
  onSaved: () => void;
}

export default function ThemeTab({ initial, backgroundImageUrl, onSaved }: Props) {
  const [theme, setTheme] = useState<LinkPackTheme>(initial);
  const [bgFile, setBgFile] = useState<File | null>(null);
  const [bgPreview, setBgPreview] = useState<string | null>(
    backgroundImageUrl ? `${API_URL}${backgroundImageUrl}?t=${Date.now()}` : null
  );
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const onBg = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) { setMsg('Image too large (max 5MB)'); return; }
    setBgFile(f);
    setBgPreview(URL.createObjectURL(f));
  };

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const token = localStorage.getItem('admin_token');
      const res = await fetch(`${API_URL}/api/v1/link-pack/theme`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(theme),
      });
      if (!res.ok) throw new Error('Theme save failed');
      if (bgFile) {
        const form = new FormData();
        form.append('file', bgFile);
        const bgRes = await fetch(`${API_URL}/api/v1/link-pack/background-image`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: form,
        });
        if (!bgRes.ok) throw new Error('Background upload failed');
      }
      setMsg('Saved.');
      onSaved();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <section>
        <h3 className="text-white/80 text-xs font-bold uppercase tracking-widest mb-3">Background</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-white/40 text-xs block mb-1">Type</label>
            <select
              value={theme.background.type}
              onChange={(e) => setTheme(t => ({ ...t, background: { ...t.background, type: e.target.value as 'solid' | 'image' } }))}
              className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2"
            >
              <option value="solid">Solid color</option>
              <option value="image">Image (with color fallback)</option>
            </select>
          </div>
          <div>
            <label className="text-white/40 text-xs block mb-1">Color</label>
            <input
              type="color"
              value={theme.background.color}
              onChange={(e) => setTheme(t => ({ ...t, background: { ...t.background, color: e.target.value } }))}
              className="w-full h-10 bg-dark-surface border border-dark-border"
            />
          </div>
          {theme.background.type === 'image' && (
            <div className="md:col-span-2">
              <label className="text-white/40 text-xs block mb-1">Image (max 5MB)</label>
              <div className="flex items-center gap-4">
                {bgPreview && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={bgPreview} alt="" className="w-32 h-20 object-cover border border-dark-border" />
                )}
                <label className="text-xs text-white/60 border border-dashed border-dark-border hover:border-gold/40 px-4 py-2 cursor-pointer">
                  Upload new
                  <input type="file" accept="image/*" className="hidden" onChange={onBg} />
                </label>
              </div>
            </div>
          )}
        </div>
      </section>

      <section>
        <h3 className="text-white/80 text-xs font-bold uppercase tracking-widest mb-3">Button</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {(['bg', 'text', 'shadow'] as const).map(k => (
            <div key={k}>
              <label className="text-white/40 text-xs block mb-1 capitalize">{k} color</label>
              <input
                type="color"
                value={theme.button[k]}
                onChange={(e) => setTheme(t => ({ ...t, button: { ...t.button, [k]: e.target.value } }))}
                className="w-full h-10 bg-dark-surface border border-dark-border"
              />
            </div>
          ))}
          <div>
            <label className="text-white/40 text-xs block mb-1">Corner</label>
            <select
              value={theme.button.corner}
              onChange={(e) => setTheme(t => ({ ...t, button: { ...t.button, corner: e.target.value as typeof CORNERS[number] } }))}
              className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2"
            >
              {CORNERS.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-white/80 text-xs font-bold uppercase tracking-widest mb-3">Typography</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-white/40 text-xs block mb-1">Font</label>
            <select
              value={theme.typography.font}
              onChange={(e) => setTheme(t => ({ ...t, typography: { ...t.typography, font: e.target.value as typeof FONTS[number] } }))}
              className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2"
            >
              {FONTS.map(f => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div>
            <label className="text-white/40 text-xs block mb-1">Text color</label>
            <input
              type="color"
              value={theme.typography.color}
              onChange={(e) => setTheme(t => ({ ...t, typography: { ...t.typography, color: e.target.value } }))}
              className="w-full h-10 bg-dark-surface border border-dark-border"
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-white/80 text-xs font-bold uppercase tracking-widest mb-3">Social row</h3>
        <div>
          <label className="text-white/40 text-xs block mb-1">Icon color</label>
          <input
            type="color"
            value={theme.social.color}
            onChange={(e) => setTheme(t => ({ ...t, social: { color: e.target.value } }))}
            className="w-full md:w-1/2 h-10 bg-dark-surface border border-dark-border"
          />
        </div>
      </section>

      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-2 text-xs bg-gold text-dark-surface font-bold uppercase tracking-widest px-4 py-2 hover:bg-gold-hover disabled:opacity-60 cursor-pointer"
        >
          {saving ? <CircleNotch size={12} className="animate-spin" /> : null}
          Save theme
        </button>
        <button
          onClick={() => setTheme(DEFAULT_THEME)}
          className="text-xs text-white/40 border border-dark-border hover:border-white/20 px-4 py-2 cursor-pointer"
        >
          Reset to default
        </button>
        {msg && <span className="text-xs text-white/60">{msg}</span>}
      </div>
    </div>
  );
}
