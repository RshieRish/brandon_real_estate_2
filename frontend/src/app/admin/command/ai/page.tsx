'use client';
import { useEffect, useState } from 'react';
import { CheckCircle, Sparkle, WarningCircle } from '@phosphor-icons/react';
import { commandApi, type AiBriefing } from '@/lib/command/api';

export default function Page() {
  const [briefing, setBriefing] = useState<AiBriefing | null>(null); const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  useEffect(() => { void commandApi.aiBriefing().then(setBriefing).catch((err) => setError(err.message)); }, []);
  async function generate() { setLoading(true); setError(''); try { setBriefing(await commandApi.generateAiBriefing()); } catch (err) { setError(err instanceof Error ? err.message : 'AI briefing unavailable'); } finally { setLoading(false); } }
  return <div className="min-h-[100dvh] bg-[#080807] p-6 text-white"><main className="mx-auto max-w-3xl"><p className="text-xs uppercase tracking-[.25em] text-[#eac469]">Auditable internal AI</p><h1 className="mt-1 text-3xl font-black">Sweeney AI Briefing</h1><section className="mt-8 rounded-2xl border border-[#eac469]/30 bg-[#eac469]/5 p-7"><Sparkle className="text-[#eac469]" size={28} />{error ? <div role="alert" className="mt-5 flex gap-3 text-red-200"><WarningCircle size={22} /><p>{error}</p></div> : !briefing ? <div className="mt-5 h-20 animate-pulse rounded-xl bg-white/5" /> : <><p className="mt-5 text-xl font-semibold">{briefing.summary}</p><div className="mt-5 flex flex-wrap gap-2"><span className="rounded-full bg-black/25 px-3 py-1 text-xs text-white/65">Source: {briefing.source}</span>{briefing.requires_review && <span className="inline-flex items-center gap-1 rounded-full bg-[#eac469]/15 px-3 py-1 text-xs text-[#eac469]"><CheckCircle size={13} />Review required</span>}</div></>}<button onClick={generate} disabled={loading} className="mt-6 rounded-xl bg-[#eac469] px-4 py-2 text-sm font-bold text-black disabled:opacity-50">{loading ? 'Generating…' : 'Generate fresh briefing'}</button><p className="mt-5 text-sm text-white/45">This is an internal, review-required summary. No action is taken automatically.</p></section></main></div>;
}
