'use client';
import Link from 'next/link';
import { ArrowLeft, Wrench } from '@phosphor-icons/react';

export function WorkspacePlaceholder({ title, description }: { title: string; description: string }) {
  return <div className="min-h-[100dvh] bg-[#080807] p-8 text-white"><Link href="/admin/command" className="inline-flex items-center gap-2 text-sm text-[#eac469]"><ArrowLeft size={16}/>Command Home</Link><main className="mt-12 max-w-3xl rounded-2xl border border-white/10 bg-white/[.035] p-8"><Wrench size={28} className="text-[#eac469]"/><h1 className="mt-5 text-3xl font-black">{title}</h1><p className="mt-3 text-white/60">{description}</p><p className="mt-8 rounded-xl border border-[#eac469]/20 bg-[#eac469]/10 p-4 text-sm text-[#f4daa0]">This workspace is reserved for the internal CRM. It does not connect to Keller Williams or DocuSign.</p></main></div>;
}
