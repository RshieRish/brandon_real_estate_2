'use client';

import { ChangeEvent, useMemo, useState } from 'react';
import { FileArrowUp, UploadSimple, WarningCircle } from '@phosphor-icons/react';
import { commandApi, type ArchiveBundle, type ContactImportRow } from '@/lib/command/api';

const acceptedHeaders = new Set(['first_name', 'last_name', 'email', 'phone', 'stage', 'birthday', 'anniversary']);

function readCsvLine(line: string): string[] {
  const cells: string[] = [];
  let value = ''; let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"' && line[index + 1] === '"' && quoted) { value += '"'; index += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === ',' && !quoted) { cells.push(value.trim()); value = ''; }
    else value += char;
  }
  cells.push(value.trim());
  return cells;
}

function normalize(value: unknown): string | null { const text = typeof value === 'string' ? value.trim() : ''; return text || null; }

function validateRows(value: unknown): ContactImportRow[] {
  if (!Array.isArray(value)) throw new Error('JSON must contain an array of contact objects.');
  return value.map((row, index) => {
    if (!row || typeof row !== 'object') throw new Error(`Row ${index + 1} is not a contact object.`);
    const item = row as Record<string, unknown>;
    const firstName = normalize(item.first_name);
    if (!firstName) throw new Error(`Row ${index + 1} needs first_name.`);
    return { first_name: firstName, last_name: normalize(item.last_name) ?? '', email: normalize(item.email), phone: normalize(item.phone), stage: normalize(item.stage) ?? 'lead', birthday: normalize(item.birthday), anniversary: normalize(item.anniversary) };
  });
}

function parseCsv(source: string): ContactImportRow[] {
  const lines = source.split(/\r?\n/).filter((line) => line.trim());
  if (lines.length < 2) throw new Error('CSV needs a header row and at least one contact.');
  const headers = readCsvLine(lines[0]).map((header) => header.toLowerCase().trim());
  if (!headers.includes('first_name')) throw new Error('CSV must include a first_name column.');
  const unknown = headers.filter((header) => !acceptedHeaders.has(header));
  if (unknown.length) throw new Error(`Unsupported CSV column: ${unknown[0]}.`);
  return validateRows(lines.slice(1).map((line) => Object.fromEntries(readCsvLine(line).map((cell, index) => [headers[index], cell]))));
}

export default function ImportContactsPage() {
  const [rows, setRows] = useState<ContactImportRow[]>([]);
  const [bundle, setBundle] = useState<ArchiveBundle | null>(null);
  const [error, setError] = useState('');
  const [result, setResult] = useState('');
  const [running, setRunning] = useState(false);
  const preview = useMemo(() => rows.slice(0, 5), [rows]);

  async function loadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const source = await file.text();
      const json = file.name.toLowerCase().endsWith('.json') ? JSON.parse(source) : null;
      if (json && !Array.isArray(json) && typeof json === 'object') {
        const archive = json as ArchiveBundle;
        const supported = ['contacts', 'tasks', 'notes', 'opportunities', 'referrals', 'listings', 'templates', 'agreements'];
        if (!supported.some((key) => key in archive)) throw new Error('JSON archive must contain at least one supported collection.');
        setBundle(archive); setRows(validateRows(archive.contacts ?? [])); setError(''); setResult(''); event.target.value = ''; return;
      }
      const parsed = json ? validateRows(json) : parseCsv(source);
      if (parsed.length > 10000) throw new Error('Imports are limited to 10,000 contacts per file.');
      setBundle(null); setRows(parsed); setError(''); setResult('');
    } catch (err) { setBundle(null); setRows([]); setError(err instanceof Error ? err.message : 'Unable to read that file.'); }
    event.target.value = '';
  }

  async function importRows() {
    if (!rows.length && !bundle) return;
    setRunning(true); setError('');
    try {
      if (bundle) {
        const response = await commandApi.importArchiveBundle(bundle);
        const created = Object.values(response.created).reduce((total, count) => total + count, 0);
        const skipped = Object.values(response.skipped_duplicates).reduce((total, count) => total + count, 0);
        setResult(`Imported ${created} internal records; skipped ${skipped} duplicates; ${response.unresolved_contact_references} contact references could not be resolved.`);
      } else {
        let created = 0; let skipped = 0;
        for (let index = 0; index < rows.length; index += 1000) {
          const response = await commandApi.importContacts(rows.slice(index, index + 1000));
          created += response.created; skipped += response.skipped_duplicates;
        }
        setResult(`Imported ${created} contact${created === 1 ? '' : 's'}; skipped ${skipped} duplicate${skipped === 1 ? '' : 's'}.`);
      }
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to import contacts.'); }
    finally { setRunning(false); }
  }

  return <div className="min-h-[100dvh] bg-[#080807] p-6 text-white"><main className="mx-auto max-w-4xl"><p className="text-xs uppercase tracking-[.25em] text-[#eac469]">Permitted internal intake</p><h1 className="mt-1 text-3xl font-black">Import archive</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-white/55">Import a contacts CSV/JSON or one JSON archive bundle. Bundle collections may include <code>contacts, tasks, notes, opportunities, referrals, listings, templates, agreements</code>. Email-based contact relationships are reconciled into the internal CRM; no external API is used.</p><label className="mt-8 flex min-h-44 cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-[#eac469]/50 bg-[#eac469]/[.04] p-8 text-center transition hover:bg-[#eac469]/[.08]"><input className="sr-only" type="file" accept=".csv,application/json,.json,text/csv" onChange={loadFile}/><FileArrowUp size={32} className="text-[#eac469]"/><b className="mt-4">Choose a CSV or JSON archive</b><span className="mt-2 text-sm text-white/45">Contact CSV imports use 1,000-record batches. JSON bundles preserve supported CRM relationships.</span></label>{error && <p role="alert" className="mt-5 flex gap-2 rounded-xl border border-red-300/20 bg-red-300/10 p-4 text-sm text-red-200"><WarningCircle size={18}/>{error}</p>}{(rows.length > 0 || bundle) && <section className="mt-6 rounded-2xl border border-white/10 bg-white/[.035] p-5"><div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="font-bold">{bundle ? 'Archive bundle ready' : `${rows.length.toLocaleString()} contacts ready`}</h2><p className="mt-1 text-sm text-white/45">{bundle ? Object.entries(bundle).filter(([, value]) => Array.isArray(value) && value.length).map(([key, value]) => `${key}: ${(value as unknown[]).length}`).join(' · ') : `Previewing the first ${preview.length} rows. Existing emails are skipped case-insensitively.`}</p></div><button disabled={running} onClick={importRows} className="inline-flex items-center gap-2 rounded-xl bg-[#eac469] px-4 py-3 text-sm font-bold text-black disabled:opacity-50"><UploadSimple size={18}/>{running ? 'Importing…' : 'Import archive'}</button></div>{!bundle && <div className="mt-5 overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><thead className="text-xs uppercase tracking-widest text-white/40"><tr><th className="pb-3">Name</th><th className="pb-3">Email</th><th className="pb-3">Phone</th><th className="pb-3">Stage</th></tr></thead><tbody>{preview.map((row, index) => <tr key={`${row.email}-${index}`} className="border-t border-white/10"><td className="py-3">{row.first_name} {row.last_name}</td><td className="py-3 text-white/60">{row.email ?? '—'}</td><td className="py-3 text-white/60">{row.phone ?? '—'}</td><td className="py-3 text-white/60">{row.stage}</td></tr>)}</tbody></table></div>}</section>}{result && <p className="mt-5 rounded-xl border border-[#eac469]/25 bg-[#eac469]/10 p-4 text-sm text-[#f5d98f]">{result}</p>}</main></div>;
}
