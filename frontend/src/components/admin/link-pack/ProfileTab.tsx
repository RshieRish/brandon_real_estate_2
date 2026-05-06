'use client';
import { useState } from 'react';
import { CircleNotch, UploadSimple } from '@phosphor-icons/react';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface Props {
  initial: {
    name: string;
    bio: string;
    photo_url: string | null;
    is_verified: boolean;
  };
  onSaved: () => void;
}

export default function ProfileTab({ initial, onSaved }: Props) {
  const [name, setName] = useState(initial.name);
  const [bio, setBio] = useState(initial.bio);
  const [verified, setVerified] = useState(initial.is_verified);
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(
    initial.photo_url ? `${API_URL}${initial.photo_url}?t=${Date.now()}` : null
  );
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const onPhoto = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) { setMsg('Image too large (max 5MB)'); return; }
    setPhotoFile(f);
    setPhotoPreview(URL.createObjectURL(f));
  };

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const token = localStorage.getItem('admin_token');
      const res = await fetch(`${API_URL}/api/v1/link-pack/profile`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ profile_name: name, profile_bio: bio, is_verified: verified }),
      });
      if (!res.ok) throw new Error('Save failed');
      if (photoFile) {
        const form = new FormData();
        form.append('file', photoFile);
        const photoRes = await fetch(`${API_URL}/api/v1/link-pack/profile-photo`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: form,
        });
        if (!photoRes.ok) throw new Error('Photo upload failed');
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
    <div className="space-y-4 max-w-2xl">
      <div>
        <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">Photo</label>
        <div className="flex items-center gap-4">
          <div className="w-20 h-20 rounded-full bg-dark-surface border border-dark-border overflow-hidden grid place-items-center">
            {photoPreview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={photoPreview} alt="profile" className="w-full h-full object-cover" />
            ) : (
              <UploadSimple size={20} className="text-white/30" />
            )}
          </div>
          <label className="text-xs text-white/60 border border-dashed border-dark-border hover:border-gold/40 px-4 py-2 cursor-pointer">
            Upload new
            <input type="file" accept="image/*" className="hidden" onChange={onPhoto} />
          </label>
        </div>
      </div>

      <div>
        <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">Name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 focus:outline-none focus:border-gold"
        />
      </div>

      <div>
        <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">Bio</label>
        <textarea
          rows={3}
          value={bio}
          onChange={(e) => setBio(e.target.value)}
          className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 resize-none focus:outline-none focus:border-gold"
        />
      </div>

      <label className="flex items-center gap-2 text-white/70 text-sm cursor-pointer">
        <input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} />
        Show verified badge
      </label>

      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-2 text-xs bg-gold text-dark-surface font-bold uppercase tracking-widest px-4 py-2 hover:bg-gold-hover transition-colors disabled:opacity-60 cursor-pointer"
        >
          {saving ? <CircleNotch size={12} className="animate-spin" /> : null}
          Save profile
        </button>
        {msg && <span className="text-xs text-white/60">{msg}</span>}
      </div>
    </div>
  );
}
