'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ArrowSquareOut, FunnelSimple, Globe, Megaphone } from '@phosphor-icons/react';
import { commandApi, type MarketingRecords } from '@/lib/command/api';

const metadata = {
  marketing: { title: 'Marketing', description: 'Live internal content and conversion paths.', links: [['Content studio', '/admin/content', Megaphone], ['Funnels', '/admin/funnels', FunnelSimple]] },
  websites: { title: 'Websites', description: 'Published page content managed through the internal content system.', links: [['Content studio', '/admin/content', Globe], ['Funnels', '/admin/funnels', FunnelSimple]] },
} as const;

export function ConnectedWorkspace({ kind }: { kind: keyof typeof metadata }) {
  const item = metadata[kind]; const [records, setRecords] = useState<MarketingRecords | { pages: MarketingRecords['content_blocks'] } | null>(null); const [error, setError] = useState('');
  useEffect(() => { const load = kind === 'marketing' ? commandApi.marketingRecords() : commandApi.websiteRecords(); void load.then(setRecords).catch((err) => setError(err.message)); }, [kind]);
  const blocks = records ? ('content_blocks' in records ? records.content_blocks : records.pages) : []; const funnels = records && 'funnels' in records ? records.funnels : [];
  return <div className="min-h-[100dvh] bg-[#080807] p-6 text-white"><main className="mx-auto max-w-5xl"><p className="text-xs uppercase tracking-[.25em] text-[#eac469]">Connected internal workspace</p><h1 className="mt-1 text-3xl font-black">{item.title}</h1><p className="mt-3 max-w-xl text-white/55">{item.description}</p>{error && <p role="alert" className="mt-4 text-sm text-red-300">{error}</p>}<div className="mt-7 grid gap-4 lg:grid-cols-2"><section className="rounded-2xl border border-white/10 bg-white/[.035] p-5"><h2 className="font-bold">Content records</h2>{records ? blocks.length ? blocks.map((block) => <p className="mt-3 text-sm text-white/60" key={block.id}><b className="text-white">{block.block_id}</b> · {block.page ?? 'unassigned'} · {block.content_type}</p>) : <p className="mt-3 text-sm text-white/40">No internal content records.</p> : <div className="mt-4 h-24 animate-pulse rounded-xl bg-white/5" />}</section>{kind === 'marketing' && <section className="rounded-2xl border border-white/10 bg-white/[.035] p-5"><h2 className="font-bold">Funnels</h2>{records ? funnels.length ? funnels.map((funnel) => <p className="mt-3 text-sm text-white/60" key={funnel.id}><b className="text-white">{funnel.title}</b> · {funnel.status} · {funnel.registrations} registrations</p>) : <p className="mt-3 text-sm text-white/40">No funnel records.</p> : <div className="mt-4 h-24 animate-pulse rounded-xl bg-white/5" />}</section>}</div><div className="mt-8 grid gap-4 sm:grid-cols-2">{item.links.map(([label, href, Icon]) => <Link key={href} href={href} className="group rounded-2xl border border-white/10 bg-white/[.035] p-6 hover:border-[#eac469]/50"><Icon className="text-[#eac469]" size={24} /><div className="mt-8 flex items-center justify-between font-bold">{label}<ArrowSquareOut className="text-white/40 group-hover:text-[#eac469]" size={19} /></div></Link>)}</div></main></div>;
}
