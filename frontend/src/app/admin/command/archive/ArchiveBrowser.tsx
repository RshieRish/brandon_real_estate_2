'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { Archive, ArrowLeft, ArrowUp, CaretLeft, CaretRight, DownloadSimple, FileText, FileZip, Folder, MagnifyingGlass, ShieldCheck, X } from '@phosphor-icons/react';
import { archiveApi, type ArchiveArtifactEntry, type ArchiveContentKind, type ArchiveEntry, type ArchivePage } from '@/lib/command/archive';

const PAGE_SIZE = 100;
const spring = { type: 'spring' as const, stiffness: 100, damping: 20 };
const button = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-white/15 px-3 py-2 text-sm text-white/80 transition-colors hover:border-[#eac469]/50 hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#eac469] active:scale-[.98] disabled:cursor-not-allowed disabled:opacity-40';
const labels: Record<ArchiveContentKind, string> = { document_bundle: 'Document bundle', document: 'Original document', source_capture: 'Source capture', data_export: 'Data export', supporting_file: 'Supporting file' };
type Location = { domain: string; path: string; query: string; offset: number; bundle: ArchiveArtifactEntry | null; sourcePath: string };
type Result = { key: string; data: ArchivePage; error?: never } | { key: string; error: string; data?: never };

function sizeLabel(bytes: number) {
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${(bytes / 1024).toFixed(1)} KB`;
}

function fileKey(entry: Exclude<ArchiveEntry, { entry_type: 'folder' }>) {
  return entry.entry_type === 'artifact' ? `artifact-${entry.id}` : `member-${entry.member_index}`;
}

export function ArchiveBrowser() {
  const [location, setLocation] = useState<Location>({ domain: '', path: '', query: '', offset: 0, bundle: null, sourcePath: '' });
  const [search, setSearch] = useState('');
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [domains, setDomains] = useState<Record<string, number>>({});
  const [download, setDownload] = useState<{ key: string; busy: boolean; error: string } | null>(null);
  const downloadController = useRef<AbortController | null>(null);
  const reducedMotion = useReducedMotion();
  const { domain, path, query, offset, bundle } = location;
  const bundleId = bundle?.id;
  const requestKey = JSON.stringify([domain, path, query, offset, bundleId, revision]);
  const current = result?.key === requestKey ? result : null;
  const data = current?.data;
  const loading = current === null;

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const options = { domain, path, query, offset, limit: PAGE_SIZE, signal: controller.signal };
    const request = bundleId === undefined ? archiveApi.browse(options) : archiveApi.members(bundleId, options);
    void request.then((next) => {
      if (active) {
        setResult({ key: requestKey, data: next });
        if (next.domains) setDomains(next.domains);
      }
    }).catch((error: unknown) => {
      if (active) setResult({ key: requestKey, error: error instanceof Error ? error.message : 'Unable to load the archive' });
    });
    return () => { active = false; controller.abort(); };
  }, [domain, path, query, offset, bundleId, requestKey]);

  useEffect(() => () => { downloadController.current?.abort(); }, []);

  function navigate(changes: Partial<Location>) {
    downloadController.current?.abort();
    setDownload(null);
    setSearch('');
    setLocation((previous) => ({ ...previous, query: '', offset: 0, ...changes }));
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setLocation((previous) => ({ ...previous, query: search.trim(), offset: 0 }));
  }

  async function downloadFile(entry: Exclude<ArchiveEntry, { entry_type: 'folder' }>) {
    downloadController.current?.abort();
    const controller = new AbortController();
    downloadController.current = controller;
    const key = fileKey(entry);
    setDownload({ key, busy: true, error: '' });
    try {
      const blob = entry.entry_type === 'artifact'
        ? await archiveApi.original(entry.id, controller.signal)
        : await archiveApi.member(bundleId!, entry.member_index, controller.signal);
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = entry.filename; document.body.appendChild(link); link.click(); link.remove();
      // Let the browser accept the download before releasing its object URL.
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setDownload({ key, busy: false, error: '' });
    } catch (error) {
      if (!controller.signal.aborted) setDownload({ key, busy: false, error: error instanceof Error ? error.message : 'Unable to download this file' });
    }
  }

  const breadcrumbs = path ? path.split('/').map((name, index, parts) => ({ name, path: parts.slice(0, index + 1).join('/') })) : [];
  const range = !data?.total || !data.entries.length ? `0 of ${data?.total ?? 0} entries` : `${offset + 1}–${offset + data.entries.length} of ${data.total.toLocaleString()} entries`;

  return (
    <div className="min-h-[100dvh] bg-[#0a0a0a] px-4 py-7 text-white sm:px-6 lg:px-8">
      <div className="mx-auto max-w-[1400px]">
        <header className="relative overflow-hidden border-b border-white/10 pb-7">
          <div aria-hidden className="pointer-events-none absolute right-0 top-0 h-32 w-56 opacity-15" style={{ backgroundImage: 'radial-gradient(#eac469 1px, transparent 1px)', backgroundSize: '8px 8px', maskImage: 'linear-gradient(to left, black, transparent)' }} />
          <p className="text-[11px] font-bold uppercase tracking-[.22em] text-[#eac469]">Private source preservation</p>
          <h1 className="mt-3 flex items-center gap-3 text-2xl font-extrabold tracking-tight sm:text-3xl"><Archive size={28} className="shrink-0 text-[#eac469]" />Recovered archive</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-white/65">Browse the folders and files saved from Command and DocuSign. Open a document bundle to find its original PDFs, or download the complete ZIP.</p>
        </header>

        <div className="mt-6 grid min-w-0 gap-6 lg:grid-cols-[220px_minmax(0,1fr)] lg:gap-8">
          <aside className="min-w-0">
            <h2 className="text-xs font-semibold uppercase tracking-[.16em] text-white/50">Sources</h2>
            <div className="mt-3 flex flex-wrap gap-2 lg:flex-col">
              {([['', 'All sources'], ['docusign', 'DocuSign'], ['kw_command', 'Command']] as const).map(([value, label]) => (
                <button key={label} aria-pressed={domain === value} onClick={() => navigate({ domain: value, path: '', bundle: null, sourcePath: '' })} className={`${button} justify-between ${domain === value ? 'border-[#eac469]/40 bg-[#eac469]/10 text-[#f2d38a]' : ''}`}>
                  <span>{label}</span>{' '}<span className="ml-3 text-xs tabular-nums opacity-70">{value ? domains[value]?.toLocaleString() : Object.keys(domains).length ? Object.values(domains).reduce((total, count) => total + count, 0).toLocaleString() : ''}</span>
                </button>
              ))}
            </div>
            {data && <div className="mt-6 border-t border-white/10 pt-5 text-sm leading-6">
              <p className="font-semibold text-white/90">{data.summary.files.toLocaleString()} {query ? 'matching' : 'preserved'} {data.summary.files === 1 ? 'file' : 'files'}</p>
              <p className="mt-1 text-white/55">{data.summary.folders.toLocaleString()} {data.summary.folders === 1 ? 'folder' : 'folders'} in this view</p>
              <dl className="mt-4 space-y-2 text-xs text-white/60">
                {([['document_bundles', 'Document bundles'], ['documents', 'Original documents'], ['source_captures', 'Source captures'], ['data_exports', 'Data exports'], ['supporting_files', 'Supporting files']] as const).map(([key, label]) => data.summary[key] > 0 && <div key={key} className="flex items-center justify-between gap-3"><dt>{label}</dt><dd className="tabular-nums text-white/85">{data.summary[key].toLocaleString()}</dd></div>)}
              </dl>
            </div>}
            <div className="mt-6 hidden gap-2 border-t border-white/10 pt-5 text-xs leading-5 text-white/55 lg:flex"><ShieldCheck size={18} className="mt-0.5 shrink-0 text-[#eac469]" /><p>Original bytes are checked before download. Captured pages and exported data keep their source format.</p></div>
          </aside>

          <section className="min-w-0" aria-label="Archive files">
            {bundle && <div className="mb-5 rounded-xl border border-[#eac469]/25 bg-[#eac469]/5 p-4">
              <button onClick={() => navigate({ path: location.sourcePath, bundle: null })} aria-label="Back to containing folder" className="inline-flex min-h-9 items-center gap-2 text-xs text-[#f2d38a] hover:underline focus-visible:outline-2 focus-visible:outline-[#eac469]"><ArrowLeft size={15} />Back to containing folder</button>
              <h2 className="mt-2 break-words text-lg font-bold">{bundle.filename}</h2>
              <p className="mt-1 text-xs leading-5 text-white/60">Original files inside this ZIP. Filenames are preserved exactly.</p>
              <button onClick={() => void downloadFile(bundle)} disabled={download?.busy} className={`${button} mt-3`}><DownloadSimple size={17} />Download complete ZIP</button>
              {download?.key === fileKey(bundle) && download.error && <p role="alert" className="mt-2 text-xs text-red-300">{download.error}</p>}
            </div>}

            <form role="search" onSubmit={submitSearch}>
              <label htmlFor="archive-search" className="block text-xs font-semibold text-white/80">Search files and folders</label>
              <div className="mt-2 flex gap-2">
                <div className="relative min-w-0 flex-1"><MagnifyingGlass aria-hidden size={18} className="pointer-events-none absolute left-3 top-3.5 text-white/45" /><input id="archive-search" type="search" maxLength={500} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={bundle ? 'Find a file inside this bundle' : 'Find a filename or folder path'} className="min-h-11 w-full rounded-lg border border-white/15 bg-white/[.035] py-2.5 pl-10 pr-3 text-sm placeholder:text-white/35 focus:border-[#eac469]/60 focus:outline-none focus:ring-1 focus:ring-[#eac469]/40" /></div>
                <button type="submit" className={`${button} border-[#eac469]/40 bg-[#eac469]/10 text-[#f2d38a]`}>Search</button>
              </div>
              <p className="mt-2 text-xs leading-5 text-white/50">{bundle ? 'Search includes every folder inside this bundle.' : 'Search includes all files below this folder. Open a ZIP to search the files inside it.'}</p>
            </form>

            <nav aria-label="Archive folders" className="mt-5 flex flex-wrap items-center gap-1 text-xs text-white/65">
              <button onClick={() => navigate({ path: '' })} className="min-h-10 rounded px-2 hover:bg-white/5 hover:text-[#eac469] focus-visible:outline-2 focus-visible:outline-[#eac469]">{bundle ? 'Bundle root' : 'Archive root'}</button>
              {breadcrumbs.map((crumb, index) => <span key={crumb.path} className="flex min-w-0 items-center gap-1"><CaretRight aria-hidden size={12} /><button onClick={() => navigate({ path: crumb.path })} aria-current={index === breadcrumbs.length - 1 ? 'page' : undefined} className="min-h-10 break-all rounded px-2 text-left hover:bg-white/5 hover:text-[#eac469] focus-visible:outline-2 focus-visible:outline-[#eac469]">{crumb.name}</button></span>)}
            </nav>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-white/60">
              <span aria-live="polite">{loading ? 'Loading entries…' : current?.error ? 'Archive unavailable' : range}</span>
              <div className="flex gap-2">{query && <button className={button} onClick={() => navigate({})}><X size={14} />Clear search</button>}{path && <button className={button} onClick={() => navigate({ path: path.split('/').slice(0, -1).join('/') })}><ArrowUp size={14} />Up one folder</button>}</div>
            </div>

            <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[.025] shadow-[inset_0_1px_0_rgba(255,255,255,0.07)] backdrop-blur-sm" aria-busy={loading}>
              {loading ? <div role="status" aria-label="Loading archive" className="space-y-6 p-5 motion-safe:animate-pulse">{[0, 1, 2, 3].map((index) => <div key={index} className="flex items-center gap-4"><div className="h-10 w-10 rounded-lg bg-white/5" /><div className="flex-1 space-y-2"><div className="h-3 w-2/3 rounded bg-white/10" /><div className="h-2 w-1/3 rounded bg-white/5" /></div></div>)}</div>
                : current?.error ? <div className="p-6"><p role="alert" className="text-sm leading-6 text-red-300">{current.error}</p><button onClick={() => setRevision((value) => value + 1)} className={`${button} mt-4`}>Try again</button></div>
                  : data?.entries.length === 0 ? <div className="px-5 py-12"><Folder size={28} className="text-[#eac469]/70" /><h2 className="mt-4 font-semibold">{query ? 'No matching files' : 'No imported files in this folder'}</h2><p className="mt-2 max-w-lg text-sm leading-6 text-white/55">{query ? 'Try part of a filename, or clear the search to browse the folders.' : 'Choose another folder or source to see its preserved files.'}</p></div>
                    : <ul aria-label="Archive entries" className="divide-y divide-white/10"><AnimatePresence initial={false}>
                      {data?.entries.map((entry, index) => <motion.li key={entry.entry_type === 'folder' ? entry.path : fileKey(entry)} layout initial={{ opacity: 0, y: reducedMotion ? 0 : 5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ ...spring, delay: reducedMotion ? 0 : Math.min(index, 7) * .025 }}>
                        {entry.entry_type === 'folder' ? <button aria-label={`Open folder ${entry.name}`} onClick={() => navigate({ path: entry.path })} className="flex min-h-20 w-full items-center gap-4 px-4 py-4 text-left transition-colors hover:bg-white/[.04] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[#eac469] active:bg-white/[.06] sm:px-5"><Folder size={25} className="shrink-0 text-[#eac469]" /><span className="min-w-0 flex-1"><span className="block break-words text-sm font-semibold">{entry.name}</span><span className="mt-1 block text-xs text-white/55">{entry.file_count.toLocaleString()} {entry.file_count === 1 ? 'file' : 'files'} in folder</span></span><CaretRight size={17} className="shrink-0 text-white/45" /></button>
                          : <div className="p-4 sm:p-5"><div className="flex items-start gap-3 sm:gap-4">{entry.content_kind === 'document_bundle' ? <FileZip size={24} className="mt-1 shrink-0 text-[#eac469]" /> : <FileText size={24} className="mt-1 shrink-0 text-white/60" />}<div className="min-w-0 flex-1"><p className="break-words text-sm font-semibold leading-6">{entry.filename}</p><div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-white/55"><span>{labels[entry.content_kind]}</span><span>{entry.artifact_type.toUpperCase()} · {sizeLabel(entry.size_bytes)}</span></div>{entry.path !== entry.filename && <p className="mt-2 break-all text-[11px] leading-5 text-white/45">{entry.path}</p>}</div></div>
                            <div className="mt-3 flex flex-wrap gap-2 sm:pl-10">{entry.entry_type === 'artifact' && entry.content_kind === 'document_bundle' && <button aria-label={`Open bundle ${entry.filename}`} disabled={!entry.download_available} onClick={() => navigate({ bundle: entry, sourcePath: entry.path.split('/').slice(0, -1).join('/'), path: '' })} className={`${button} border-[#eac469]/35 text-[#f2d38a]`}><Folder size={16} />Open bundle</button>}<button aria-label={`Download ${entry.filename}`} disabled={!entry.download_available || Boolean(download?.busy)} onClick={() => void downloadFile(entry)} className={button}><DownloadSimple size={16} />{download?.key === fileKey(entry) && download.busy ? 'Preparing download…' : 'Download original'}</button></div>
                            {!entry.download_available && <p className="mt-3 text-xs leading-5 text-amber-200/80 sm:pl-10">{entry.entry_type === 'member' ? entry.unavailable_reason : 'Original bytes are not available'}</p>}
                            {download?.key === fileKey(entry) && download.error && <p role="alert" className="mt-3 text-xs leading-5 text-red-300 sm:pl-10">{download.error}</p>}
                            {entry.entry_type === 'artifact' && <details className="mt-3 text-[11px] text-white/45 sm:pl-10"><summary className="w-fit cursor-pointer py-1 hover:text-white/70">File integrity</summary><p className="mt-1 break-all leading-5">SHA-256: {entry.sha256}</p></details>}
                          </div>}
                      </motion.li>)}
                    </AnimatePresence></ul>}
            </div>
            <div className="mt-4 flex items-center justify-between gap-3"><p className="text-xs text-white/45">{!loading && !current?.error ? 'Original folder names and file formats are preserved.' : ''}</p><div className="flex shrink-0 gap-2"><button aria-label="Previous page" disabled={loading || offset === 0} onClick={() => setLocation((previous) => ({ ...previous, offset: Math.max(0, offset - PAGE_SIZE) }))} className={button}><CaretLeft size={17} /></button><button aria-label="Next page" disabled={loading || !data || offset + PAGE_SIZE >= data.total} onClick={() => setLocation((previous) => ({ ...previous, offset: offset + PAGE_SIZE }))} className={button}><CaretRight size={17} /></button></div></div>
          </section>
        </div>
      </div>
    </div>
  );
}
