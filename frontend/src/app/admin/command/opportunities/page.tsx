'use client';

import { useEffect, useState } from 'react';
import { Handshake, Plus, Receipt, Users } from '@phosphor-icons/react';
import { commandApi, type Opportunity, type Relationship } from '@/lib/command/api';

type Detail = { opportunity: Opportunity; contacts: Relationship[]; vendors: Relationship[]; offers: Relationship[] };

export default function Page() {
  const [items, setItems] = useState<Opportunity[]>([]);
  const [name, setName] = useState('');
  const [detail, setDetail] = useState<Detail | null>(null);
  const [contactId, setContactId] = useState('');
  const [vendorName, setVendorName] = useState('');
  const [offerAmount, setOfferAmount] = useState('');
  const [error, setError] = useState('');

  useEffect(() => { void commandApi.opportunities().then(setItems).catch((err) => setError(err.message)); }, []);

  async function add() {
    if (!name.trim()) return;
    try { const item = await commandApi.createOpportunity({ name, stage: 'cultivate', value_cents: null }); setItems((current) => [item, ...current]); setName(''); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to create opportunity'); }
  }

  async function open(id: number) {
    try { setDetail(await commandApi.opportunityWorkspace(id)); setError(''); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to load opportunity'); }
  }

  async function addContact() {
    if (!detail || !Number.isInteger(Number(contactId)) || Number(contactId) < 1) return;
    try { await commandApi.addOpportunityContact(detail.opportunity.id, Number(contactId), 'client'); setContactId(''); await open(detail.opportunity.id); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to add contact'); }
  }
  async function addVendor() {
    if (!detail || !vendorName.trim()) return;
    try { await commandApi.addOpportunityVendor(detail.opportunity.id, vendorName.trim()); setVendorName(''); await open(detail.opportunity.id); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to add vendor'); }
  }
  async function addOffer() {
    if (!detail || !offerAmount.trim() || Number.isNaN(Number(offerAmount))) return;
    try { await commandApi.addOpportunityOffer(detail.opportunity.id, Math.round(Number(offerAmount) * 100)); setOfferAmount(''); await open(detail.opportunity.id); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to add offer'); }
  }

  return <div className="min-h-[100dvh] bg-[#080807] p-6 text-white"><main className="mx-auto max-w-6xl">
    <p className="text-xs uppercase tracking-[.25em] text-[#eac469]">Internal pipeline</p><h1 className="mt-1 text-3xl font-black">Opportunities</h1>
    <div className="mt-6 flex gap-3"><input className="flex-1 rounded-xl border border-white/10 bg-white/5 p-3" placeholder="New opportunity" value={name} onChange={(event) => setName(event.target.value)} /><button onClick={add} className="rounded-xl bg-[#eac469] px-4 text-black" aria-label="Create opportunity"><Plus /></button></div>
    {error && <p role="alert" className="mt-3 text-sm text-red-300">{error}</p>}
    <div className="mt-6 grid gap-4 lg:grid-cols-[1fr_.9fr]"><section className="space-y-2">{items.map((item) => <button onClick={() => open(item.id)} key={item.id} className="w-full rounded-xl border border-white/10 bg-white/[.035] p-4 text-left hover:border-[#eac469]/40"><b>{item.name}</b><p className="mt-1 text-sm text-white/45">{item.stage} {item.value_cents ? `· $${(item.value_cents / 100).toLocaleString()}` : ''}</p></button>)}</section>
      <aside className="rounded-2xl border border-white/10 bg-white/[.035] p-5">{detail ? <><h2 className="text-xl font-bold">{detail.opportunity.name}</h2><p className="mt-1 text-sm text-[#eac469]">{detail.opportunity.stage}</p>
        <RelationshipSection icon={<Users size={17} className="text-[#eac469]" />} label="Contacts" rows={detail.contacts.map((item) => `Contact #${item.contact_id} · ${item.role}`)} input={<input value={contactId} onChange={(event) => setContactId(event.target.value)} inputMode="numeric" placeholder="Contact ID" className="min-w-0 flex-1 rounded-lg bg-black/30 p-2 text-sm" />} onAdd={addContact} />
        <RelationshipSection icon={<Handshake size={17} className="text-[#eac469]" />} label="Vendors" rows={detail.vendors.map((item) => `${item.name} · ${item.role}`)} input={<input value={vendorName} onChange={(event) => setVendorName(event.target.value)} placeholder="Vendor name" className="min-w-0 flex-1 rounded-lg bg-black/30 p-2 text-sm" />} onAdd={addVendor} />
        <RelationshipSection icon={<Receipt size={17} className="text-[#eac469]" />} label="Offers" rows={detail.offers.map((item) => `${item.amount_cents ? `$${(item.amount_cents / 100).toLocaleString()}` : 'Draft'} · ${item.status}`)} input={<input value={offerAmount} onChange={(event) => setOfferAmount(event.target.value)} inputMode="decimal" placeholder="Amount (USD)" className="min-w-0 flex-1 rounded-lg bg-black/30 p-2 text-sm" />} onAdd={addOffer} />
      </> : <p className="text-white/40">Choose an opportunity to manage contacts, vendors, and offers.</p>}</aside>
    </div>
  </main></div>;
}

function RelationshipSection({ icon, label, rows, input, onAdd }: { icon: React.ReactNode; label: string; rows: string[]; input: React.ReactNode; onAdd: () => void }) {
  return <div className="mt-6"><div className="flex items-center gap-2 text-sm font-bold">{icon}{label}</div>{rows.length ? rows.map((row, index) => <p className="mt-2 text-sm text-white/50" key={`${row}-${index}`}>{row}</p>) : <p className="mt-2 text-sm text-white/35">None added yet.</p>}<div className="mt-3 flex gap-2">{input}<button onClick={onAdd} className="rounded-lg bg-[#eac469] px-3 text-sm font-bold text-black">Add</button></div></div>;
}
