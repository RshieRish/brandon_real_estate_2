'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Plus, Users, WarningCircle } from '@phosphor-icons/react';
import {
  applyContactWorkspaceView,
  type ContactWorkspaceView,
} from '@/components/command/workspaceFilters';
import { commandApi, type Contact } from '@/lib/command/api';

const viewOptions: ReadonlyArray<Readonly<{ value: ContactWorkspaceView['kind']; label: string }>> = [
  { value: 'all', label: 'All contacts' },
  { value: 'never_contacted', label: 'Never contacted leads' },
  { value: 'recent_activity', label: 'Recently active' },
  { value: 'birthdays', label: 'Birthdays this month' },
  { value: 'anniversaries', label: 'Anniversaries this month' },
];

export function ContactsWorkspace({
  initialView = { kind: 'all' },
}: {
  initialView?: ContactWorkspaceView;
}) {
  const [items, setItems] = useState<Contact[]>([]);
  const [query, setQuery] = useState('');
  const [stage, setStage] = useState('');
  const [view, setView] = useState<ContactWorkspaceView['kind']>(initialView.kind);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState({ first_name: '', last_name: '', email: '', phone: '' });

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const pageSize = 100;
        const all: Contact[] = [];
        for (let offset = 0; ; offset += pageSize) {
          const page = await commandApi.contacts(pageSize, offset, { query, stage });
          all.push(...page);
          if (page.length < pageSize) break;
        }
        setItems(all);
        setError(null);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : 'Unable to load contacts');
      } finally {
        setLoading(false);
      }
    };
    const timeout = window.setTimeout(() => void load(), 200);
    return () => window.clearTimeout(timeout);
  }, [query, stage]);

  async function add() {
    try {
      const created = await commandApi.createContact(draft);
      setItems((current) => [created, ...current]);
      setOpen(false);
      setDraft({ first_name: '', last_name: '', email: '', phone: '' });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to create contact');
    }
  }

  const viewResult = applyContactWorkspaceView(items, { kind: view }, new Date());

  return (
    <div className="min-h-[100dvh] bg-[#080807] p-6 text-white">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[.25em] text-[#eac469]">Internal CRM</p>
            <h1 className="mt-1 text-3xl font-black">Contacts</h1>
          </div>
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-[#eac469] px-4 py-2 font-bold text-black"
          >
            <Plus size={17} />Add contact
          </button>
        </header>
        <div className="mt-6 grid gap-3 sm:grid-cols-[1fr_180px_220px]">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search name, email, or phone"
            className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 outline-none focus:border-[#eac469]"
          />
          <select
            aria-label="Filter by stage"
            value={stage}
            onChange={(event) => setStage(event.target.value)}
            className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white outline-none focus:border-[#eac469]"
          >
            <option value="">All stages</option>
            {['lead', 'nurture', 'appointment', 'client', 'past_client', 'lost'].map((value) => (
              <option key={value} value={value}>{value.replace('_', ' ')}</option>
            ))}
          </select>
          <select
            aria-label="Contact view"
            value={view}
            onChange={(event) => setView(event.target.value as ContactWorkspaceView['kind'])}
            className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white outline-none focus:border-[#eac469]"
          >
            {viewOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </div>
        {error ? <p className="mt-4 flex gap-2 text-red-300"><WarningCircle size={18} />{error}</p> : null}
        {viewResult.state === 'unavailable' ? (
          <p role="status" className="mt-4 rounded-xl border border-amber-300/30 bg-amber-300/10 p-4 text-amber-100">
            {viewResult.message}
          </p>
        ) : null}
        <div className="mt-5 overflow-hidden rounded-2xl border border-white/10 bg-white/[.035]">
          <table className="w-full text-left text-sm">
            <thead className="bg-white/5 text-xs uppercase tracking-widest text-white/45">
              <tr><th className="p-4">Contact</th><th className="p-4">Email</th><th className="p-4">Phone</th><th className="p-4">Stage</th></tr>
            </thead>
            <tbody>
              {viewResult.rows.map((contact) => (
                <tr key={contact.id} className="border-t border-white/10">
                  <td className="p-4 font-semibold">
                    <Link className="hover:text-[#eac469]" href={`/admin/command/contacts/${contact.id}`}>
                      {contact.first_name} {contact.last_name}
                    </Link>
                  </td>
                  <td className="p-4 text-white/60">{contact.email ?? '—'}</td>
                  <td className="p-4 text-white/60">{contact.phone ?? '—'}</td>
                  <td className="p-4"><span className="rounded-full bg-[#eac469]/15 px-2 py-1 text-xs text-[#eac469]">{contact.stage}</span></td>
                </tr>
              ))}
              {!loading && viewResult.state === 'available' && viewResult.rows.length === 0 ? (
                <tr>
                  <td className="p-12 text-center text-white/40" colSpan={4}>
                    <Users size={28} className="mx-auto mb-3" />No contacts found
                  </td>
                </tr>
              ) : null}
              {loading ? <tr><td className="p-12 text-center text-white/40" colSpan={4}>Loading contacts…</td></tr> : null}
            </tbody>
          </table>
        </div>
        {open ? (
          <div className="fixed inset-0 grid place-items-center bg-black/70 p-4">
            <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#12110f] p-6">
              <h2 className="text-xl font-bold">New contact</h2>
              {(['first_name', 'last_name', 'email', 'phone'] as const).map((key) => (
                <input
                  key={key}
                  value={draft[key]}
                  placeholder={key.replace('_', ' ')}
                  onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}
                  className="mt-3 w-full rounded-lg border border-white/10 bg-black/30 p-3 capitalize"
                />
              ))}
              <div className="mt-5 flex justify-end gap-3">
                <button type="button" onClick={() => setOpen(false)} className="text-white/60">Cancel</button>
                <button type="button" onClick={() => void add()} disabled={!draft.first_name} className="rounded-lg bg-[#eac469] px-4 py-2 font-bold text-black disabled:opacity-40">Save</button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
