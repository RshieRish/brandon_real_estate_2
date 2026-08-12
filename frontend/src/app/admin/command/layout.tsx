'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Archive, ChartBar, CheckCircle, FileText, Handshake, House, List, MagnifyingGlass, MapPin, Megaphone, Sparkle, UploadSimple, Users, X } from '@phosphor-icons/react';
import { useState } from 'react';

const links = [['Contacts', '/admin/command/contacts', Users], ['Saved searches', '/admin/command/saved-searches', MagnifyingGlass], ['Tasks', '/admin/command/tasks', CheckCircle], ['Smart Plans', '/admin/command/smart-plans', Sparkle], ['Opportunities', '/admin/command/opportunities', ChartBar], ['Referrals', '/admin/command/referrals', Handshake], ['Marketing', '/admin/command/marketing', Megaphone], ['Agreements', '/admin/command/agreements', FileText], ['Reports', '/admin/command/reports', ChartBar], ['Listings & Map', '/admin/command/listings', MapPin], ['Websites', '/admin/command/websites', House], ['Recovered archive', '/admin/command/archive', Archive], ['Sweeney AI', '/admin/command/ai', Sparkle], ['Import contacts', '/admin/command/import', UploadSimple]] as const;

function Navigation({ path, close }: { path: string; close?: () => void }) { return <>{links.map(([label, href, Icon]) => <Link onClick={close} key={href} href={href} className={`mt-1 flex items-center gap-3 rounded-xl px-3 py-3 text-sm ${path === href ? 'bg-[#eac469] font-bold text-black' : 'text-white/60 hover:bg-white/5'}`}><Icon size={17} />{label}</Link>)}</>; }

export default function CommandLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname(); const [open, setOpen] = useState(false);
  if (path === '/admin/command') return <>{children}</>;
  return <div className="flex min-h-[100dvh] bg-[#080807] text-white"><aside className="hidden w-56 shrink-0 border-r border-white/10 bg-black/20 p-3 lg:block"><Link href="/admin/command" className="block px-3 py-4 text-xs font-bold uppercase tracking-[.22em] text-[#eac469]">Sold With Sweeney</Link><Navigation path={path} /></aside><div className="min-w-0 flex-1"><header className="flex items-center justify-between border-b border-white/10 px-4 py-3 lg:hidden"><Link href="/admin/command" className="text-xs font-bold uppercase tracking-[.22em] text-[#eac469]">Sold With Sweeney</Link><button onClick={() => setOpen(true)} aria-label="Open Command navigation" className="rounded-lg border border-white/10 p-2 text-white"><List size={20} /></button></header>{open && <div className="fixed inset-0 z-50 lg:hidden"><button onClick={() => setOpen(false)} aria-label="Close navigation" className="absolute inset-0 bg-black/70" /><aside className="relative h-full w-72 border-r border-white/10 bg-[#0d0c0a] p-3 shadow-2xl"><div className="flex items-center justify-between px-3 py-3"><Link onClick={() => setOpen(false)} href="/admin/command" className="text-xs font-bold uppercase tracking-[.22em] text-[#eac469]">Sold With Sweeney</Link><button onClick={() => setOpen(false)} aria-label="Close Command navigation" className="p-1 text-white/65"><X size={20} /></button></div><Navigation path={path} close={() => setOpen(false)} /></aside></div>}{children}</div></div>;
}
