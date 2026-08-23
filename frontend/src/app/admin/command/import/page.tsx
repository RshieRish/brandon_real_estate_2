'use client';

import { ChangeEvent, useMemo, useState } from 'react';
import { DownloadSimple, FileArrowUp, UploadSimple, WarningCircle } from '@phosphor-icons/react';
import { commandApi, type ArchiveBundle, type ContactImportRow } from '@/lib/command/api';

const acceptedHeaders = new Set(['first_name', 'last_name', 'email', 'phone', 'stage', 'birthday', 'anniversary']);
export const archiveTemplate: ArchiveBundle = {
  source_id: '',
  contacts: [{ first_name: 'Avery', last_name: 'Lake', email: 'avery@example.com', phone: '+15550100', stage: 'lead', birthday: '1990-08-12', anniversary: null }],
  tasks: [{ source_row_id: '', title: 'Call Avery', contact_email: 'avery@example.com', description: 'Review next steps', status: 'open', priority: 'high', due_at: null }],
  notes: [{ contact_email: 'avery@example.com', body: 'Imported timeline context.' }],
  opportunities: [{ name: '10 Main Street purchase', stage: 'active', value_cents: 75000000, contact_emails: ['avery@example.com'] }],
  referrals: [{ name: 'Avery referral', source: 'Partner', status: 'new', contact_email: 'avery@example.com' }],
  listings: [{ address: '10 Main Street', latitude: null, longitude: null, status: 'active' }],
  templates: [{ name: 'Buyer agreement', body: 'Internal agreement template content.' }],
  agreements: [{ title: 'Avery buyer agreement', contact_email: 'avery@example.com', template_name: 'Buyer agreement', status: 'draft' }],
};

const supportedArchiveCollections = ['contacts', 'tasks', 'notes', 'opportunities', 'referrals', 'listings', 'templates', 'agreements'] as const;

function requiredIdentity(value: unknown, label: string, maximum: number): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${label} must be a non-empty string.`);
  if (value.length > maximum) throw new Error(`${label} must be ${maximum} characters or fewer.`);
  return value;
}

export function validateArchiveBundle(value: unknown): ArchiveBundle {
  if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('JSON archive must be an object.');
  const archive = value as Record<string, unknown>;
  if (!supportedArchiveCollections.some((key) => key in archive)) throw new Error('JSON archive must contain at least one supported collection.');
  if ('tasks' in archive && !Array.isArray(archive.tasks)) throw new Error('Archive tasks must be an array.');
  const tasks = (archive.tasks ?? []) as unknown[];
  if (tasks.length) {
    requiredIdentity(archive.source_id, 'Task archive source_id', 255);
    tasks.forEach((task, index) => {
      if (!task || Array.isArray(task) || typeof task !== 'object') throw new Error(`Task ${index + 1} must be an object.`);
      requiredIdentity((task as Record<string, unknown>).source_row_id, `Task ${index + 1} source_row_id`, 128);
    });
  }
  return value as ArchiveBundle;
}

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

  function downloadTemplate() {
    const blob = new Blob([JSON.stringify(archiveTemplate, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob); const link = document.createElement('a');
    link.href = url; link.download = 'command-archive-template.json'; link.click(); URL.revokeObjectURL(url);
  }

  async function loadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const source = await file.text();
      const json = file.name.toLowerCase().endsWith('.json') ? JSON.parse(source) : null;
      if (json && !Array.isArray(json) && typeof json === 'object') {
        const archive = validateArchiveBundle(json);
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

  return <div className="min-h-[100dvh] bg-[#080807] p-6 text-white"><main className="mx-auto max-w-4xl"><p className="text-xs uppercase tracking-[.25em] text-[#eac469]">Permitted internal intake</p><div className="mt-1 flex flex-wrap items-center justify-between gap-4"><h1 className="text-3xl font-black">Import archive</h1><button onClick={downloadTemplate} className="inline-flex items-center gap-2 rounded-lg border border-white/15 px-3 py-2 text-xs text-white/70 hover:border-[#eac469]"><DownloadSimple size={16}/>Download JSON template</button></div><p className="mt-3 max-w-2xl text-sm leading-6 text-white/55">Import a contacts CSV/JSON or one JSON archive bundle. Bundle collections may include <code>contacts, tasks, notes, opportunities, referrals, listings, templates, agreements</code>. Task bundles retain immutable <code>source_id</code> and <code>source_row_id</code> values. Email-based contact relationships are reconciled into the internal CRM; no external API is used.</p><label className="mt-8 flex min-h-44 cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-[#eac469]/50 bg-[#eac469]/[.04] p-8 text-center transition hover:bg-[#eac469]/[.08]"><input className="sr-only" type="file" accept=".csv,application/json,.json,text/csv" onChange={loadFile}/><FileArrowUp size={32} className="text-[#eac469]"/><b className="mt-4">Choose a CSV or JSON archive</b><span className="mt-2 text-sm text-white/45">Use one stable, unique source_id for each immutable archive source; use a different value for unrelated bundles. Keep every source_row_id unchanged across retries.</span></label>{error && <p role="alert" className="mt-5 flex gap-2 rounded-xl border border-red-300/20 bg-red-300/10 p-4 text-sm text-red-200"><WarningCircle size={18}/>{error}</p>}{(rows.length > 0 || bundle) && <section className="mt-6 rounded-2xl border border-white/10 bg-white/[.035] p-5"><div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="font-bold">{bundle ? 'Archive bundle ready' : `${rows.length.toLocaleString()} contacts ready`}</h2><p className="mt-1 text-sm text-white/45">{bundle ? Object.entries(bundle).filter(([, value]) => Array.isArray(value) && value.length).map(([key, value]) => `${key}: ${(value as unknown[]).length}`).join(' · ') : `Previewing the first ${preview.length} rows. Existing emails are skipped case-insensitively.`}</p></div><button disabled={running} onClick={importRows} className="inline-flex items-center gap-2 rounded-xl bg-[#eac469] px-4 py-3 text-sm font-bold text-black disabled:opacity-50"><UploadSimple size={18}/>{running ? 'Importing…' : 'Import archive'}</button></div>{!bundle && <div className="mt-5 overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><thead className="text-xs uppercase tracking-widest text-white/40"><tr><th className="pb-3">Name</th><th className="pb-3">Email</th><th className="pb-3">Phone</th><th className="pb-3">Stage</th></tr></thead><tbody>{preview.map((row, index) => <tr key={`${row.email}-${index}`} className="border-t border-white/10"><td className="py-3">{row.first_name} {row.last_name}</td><td className="py-3 text-white/60">{row.email ?? '—'}</td><td className="py-3 text-white/60">{row.phone ?? '—'}</td><td className="py-3 text-white/60">{row.stage}</td></tr>)}</tbody></table></div>}</section>}{result && <p className="mt-5 rounded-xl border border-[#eac469]/25 bg-[#eac469]/10 p-4 text-sm text-[#f5d98f]">{result}</p>}</main></div>;
}
