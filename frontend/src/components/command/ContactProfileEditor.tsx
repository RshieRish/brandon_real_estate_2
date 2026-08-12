'use client';

import { useState } from 'react';
import { FloppyDisk, PencilSimple, X } from '@phosphor-icons/react';
import { commandApi, type Contact } from '@/lib/command/api';

type Fields = Pick<Contact, 'first_name' | 'last_name' | 'email' | 'phone' | 'birthday' | 'anniversary'>;

export function ContactProfileEditor({ contact, onUpdated }: { contact: Contact; onUpdated: (contact: Contact) => void }) {
  const [open, setOpen] = useState(false);
  const [fields, setFields] = useState<Fields>({ first_name: contact.first_name, last_name: contact.last_name, email: contact.email, phone: contact.phone, birthday: contact.birthday ?? null, anniversary: contact.anniversary ?? null });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  function begin() { setFields({ first_name: contact.first_name, last_name: contact.last_name, email: contact.email, phone: contact.phone, birthday: contact.birthday ?? null, anniversary: contact.anniversary ?? null }); setError(''); setOpen(true); }
  function update(field: keyof Fields, value: string) { setFields((current) => ({ ...current, [field]: value || (field === 'first_name' || field === 'last_name' ? value : null) })); }
  async function save() {
    if (!fields.first_name.trim()) { setError('First name is required.'); return; }
    setSaving(true); setError('');
    try {
      const updated = await commandApi.updateContact(contact.id, { ...fields, first_name: fields.first_name.trim(), last_name: fields.last_name.trim(), email: fields.email || null, phone: fields.phone || null, birthday: fields.birthday || null, anniversary: fields.anniversary || null });
      onUpdated(updated); setOpen(false);
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to save profile'); }
    finally { setSaving(false); }
  }
  return <>{!open ? <button onClick={begin} className="inline-flex items-center gap-2 rounded-lg border border-white/15 px-3 py-2 text-xs text-white/70 hover:border-[#eac469]"><PencilSimple size={15}/>Edit profile</button> : <section className="mt-4 rounded-2xl border border-[#eac469]/25 bg-[#eac469]/[.05] p-5"><div className="flex items-center justify-between"><h2 className="font-bold">Edit profile</h2><button aria-label="Close profile editor" onClick={() => setOpen(false)} className="text-white/55"><X size={18}/></button></div><div className="mt-4 grid gap-3 sm:grid-cols-2"><input aria-label="First name" value={fields.first_name} onChange={(event) => update('first_name', event.target.value)} placeholder="First name" className="rounded-lg border border-white/10 bg-black/30 p-3 text-sm"/><input aria-label="Last name" value={fields.last_name} onChange={(event) => update('last_name', event.target.value)} placeholder="Last name" className="rounded-lg border border-white/10 bg-black/30 p-3 text-sm"/><input aria-label="Email" value={fields.email ?? ''} onChange={(event) => update('email', event.target.value)} placeholder="Email" className="rounded-lg border border-white/10 bg-black/30 p-3 text-sm"/><input aria-label="Phone" value={fields.phone ?? ''} onChange={(event) => update('phone', event.target.value)} placeholder="Phone" className="rounded-lg border border-white/10 bg-black/30 p-3 text-sm"/><label className="text-xs text-white/55">Birthday<input aria-label="Birthday" type="date" value={fields.birthday ?? ''} onChange={(event) => update('birthday', event.target.value)} className="mt-1 block w-full rounded-lg border border-white/10 bg-black/30 p-3 text-sm text-white"/></label><label className="text-xs text-white/55">Anniversary<input aria-label="Anniversary" type="date" value={fields.anniversary ?? ''} onChange={(event) => update('anniversary', event.target.value)} className="mt-1 block w-full rounded-lg border border-white/10 bg-black/30 p-3 text-sm text-white"/></label></div>{error && <p role="alert" className="mt-3 text-sm text-red-200">{error}</p>}<div className="mt-5 flex justify-end gap-3"><button onClick={() => setOpen(false)} className="text-sm text-white/60">Cancel</button><button disabled={saving} onClick={save} className="inline-flex items-center gap-2 rounded-lg bg-[#eac469] px-4 py-2 text-sm font-bold text-black disabled:opacity-50"><FloppyDisk size={16}/>{saving ? 'Saving…' : 'Save profile'}</button></div></section>}</>;
}
