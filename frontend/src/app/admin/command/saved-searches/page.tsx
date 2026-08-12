'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { MagnifyingGlass, Trash } from '@phosphor-icons/react';
import { commandApi, type SavedSearch } from '@/lib/command/api';

function criteriaLabel(criteria: string) {
  try {
    const parsed = JSON.parse(criteria) as Record<string, unknown>;
    return Object.entries(parsed).map(([key, value]) => `${key}: ${String(value)}`).join(' · ') || 'No criteria recorded';
  } catch { return 'Stored criteria unavailable'; }
}

export default function SavedSearchesPage() {
  const [searches, setSearches] = useState<SavedSearch[]>([]);
  const [error, setError] = useState('');
  const [removing, setRemoving] = useState<number | null>(null);
  useEffect(() => { void commandApi.savedSearches().then(setSearches).catch((err) => setError(err instanceof Error ? err.message : 'Unable to load saved searches')); }, []);
  async function remove(search: SavedSearch) {
    if (!window.confirm(`Remove saved search “${search.name}”?`)) return;
    setRemoving(search.id);
    try { await commandApi.deleteSavedSearch(search.id); setSearches((items) => items.filter((item) => item.id !== search.id)); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to remove saved search'); }
    finally { setRemoving(null); }
  }
  return <div className="min-h-[100dvh] bg-[#080807] p-6 text-white"><main className="mx-auto max-w-5xl"><p className="text-xs uppercase tracking-[.25em] text-[#eac469]">Contact intelligence</p><h1 className="mt-1 text-3xl font-black">Saved Searches</h1><p className="mt-3 text-sm text-white/50">Reusable contact-workspace contexts saved from the internal CRM.</p>{error && <p role="alert" className="mt-4 text-sm text-red-300">{error}</p>}<div className="mt-7 space-y-3">{searches.map((search) => <article key={search.id} className="flex flex-wrap items-center gap-4 rounded-2xl border border-white/10 bg-white/[.035] p-5"><MagnifyingGlass size={22} className="text-[#eac469]"/><div className="min-w-0 flex-1"><h2 className="font-bold">{search.name}</h2><p className="mt-1 truncate text-sm text-white/55">{criteriaLabel(search.criteria)}</p><p className="mt-2 text-xs text-white/40">{search.contact_id ? <Link className="hover:text-[#eac469]" href={`/admin/command/contacts/${search.contact_id}`}>{search.contact_name ?? `Contact #${search.contact_id}`}</Link> : 'Workspace-wide'} · Updated {new Date(search.updated_at).toLocaleDateString()}</p></div><button disabled={removing === search.id} onClick={() => remove(search)} className="rounded-lg border border-red-300/25 p-2 text-red-200 hover:bg-red-300/10 disabled:opacity-50" aria-label={`Remove ${search.name}`}><Trash size={18}/></button></article>)}{!searches.length && <div className="rounded-2xl border border-dashed border-white/15 p-12 text-center text-white/45"><MagnifyingGlass size={30} className="mx-auto text-[#eac469]"/><p className="mt-3">No saved searches yet.</p><p className="mt-1 text-sm">Save one from a contact workspace to keep its context here.</p></div>}</div></main></div>;
}
