'use client';

import { useState } from 'react';
import { FloppyDisk, NotePencil, Tag, X } from '@phosphor-icons/react';
import { commandApi } from '@/lib/command/api';

type Mode = 'note' | 'search' | 'tag' | null;

export function ContactActions({ contactId, onChanged }: { contactId: string; onChanged: () => void }) {
  const id = Number(contactId);
  const [mode, setMode] = useState<Mode>(null);
  const [value, setValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const label = mode === 'note' ? 'Add note' : mode === 'search' ? 'Save search' : 'Add tag';
  async function save() {
    const trimmed = value.trim();
    if (!mode || !trimmed) return;
    setSaving(true); setError('');
    try {
      if (mode === 'note') await commandApi.createContactNote(id, trimmed);
      if (mode === 'search') await commandApi.createContactSavedSearch(id, trimmed, { contact_id: id, scope: 'contact_workspace', saved_from: 'command' });
      if (mode === 'tag') { const tag = await commandApi.createTag(trimmed); await commandApi.assignContactTag(id, tag.id); }
      setMode(null); setValue(''); onChanged();
    } catch (err) { setError(err instanceof Error ? err.message : `Unable to ${label.toLowerCase()}`); }
    finally { setSaving(false); }
  }
  function open(next: Exclude<Mode, null>) { setMode(next); setValue(''); setError(''); }
  return <div className="mt-4"><div className="flex flex-wrap gap-2"><button onClick={() => open('note')} className="inline-flex items-center gap-2 rounded-lg border border-white/15 px-3 py-2 text-xs text-white/70 hover:border-[#eac469]"><NotePencil size={15}/>Add note</button><button onClick={() => open('search')} className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white/70 hover:border-[#eac469]">Save search</button><button onClick={() => open('tag')} className="inline-flex items-center gap-2 rounded-lg border border-white/15 px-3 py-2 text-xs text-white/70 hover:border-[#eac469]"><Tag size={15}/>Add tag</button></div>{mode && <section className="mt-3 max-w-xl rounded-xl border border-[#eac469]/25 bg-[#eac469]/[.06] p-4"><div className="flex items-center justify-between gap-3"><b className="text-sm">{label}</b><button onClick={() => setMode(null)} aria-label="Close contact action" className="text-white/55"><X size={17}/></button></div>{mode === 'note' ? <textarea autoFocus value={value} onChange={(event) => setValue(event.target.value)} placeholder="Write a private contact note" className="mt-3 min-h-24 w-full rounded-lg border border-white/10 bg-black/30 p-3 text-sm"/> : <input autoFocus value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && save()} placeholder={mode === 'search' ? 'Saved search name' : 'Tag name'} className="mt-3 w-full rounded-lg border border-white/10 bg-black/30 p-3 text-sm"/>}{error && <p role="alert" className="mt-2 text-xs text-red-200">{error}</p>}<div className="mt-3 flex justify-end"><button disabled={!value.trim() || saving} onClick={save} className="inline-flex items-center gap-2 rounded-lg bg-[#eac469] px-3 py-2 text-xs font-bold text-black disabled:opacity-50"><FloppyDisk size={15}/>{saving ? 'Saving…' : label}</button></div></section>}</div>;
}
