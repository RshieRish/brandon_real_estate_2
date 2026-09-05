import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ArchivePage from './page';

const folder = (path: string, fileCount = 1) => ({ entry_type: 'folder', path, name: path.split('/').at(-1), file_count: fileCount });
const bundle = {
  entry_type: 'artifact', id: 21, domain: 'docusign', path: 'docusign_full/download_bundles/Lease.zip',
  source_path: 'docusign_full/download_bundles/Lease.zip', filename: 'Lease.zip', artifact_type: 'zip',
  sha256: 'a'.repeat(64), size_bytes: 476918, download_available: true, content_kind: 'document_bundle',
};
const pdf = {
  entry_type: 'member', member_index: 0, path: 'Original_Lease.pdf', filename: 'Original_Lease.pdf',
  artifact_type: 'pdf', size_bytes: 43105, content_kind: 'document', download_available: true,
  unavailable_reason: null, unsafe_path: false,
};
const summary = { files: 1, folders: 2, document_bundles: 1, documents: 0, source_captures: 0, data_exports: 0, supporting_files: 0, unavailable_files: 0 };
function page(entries: unknown[], overrides: Record<string, unknown> = {}) {
  return { entries, total: entries.length, summary, domains: { docusign: 1 }, path: '', query: '', limit: 100, offset: 0, rows: [], ...overrides };
}
function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('recovered archive browser', () => {
  beforeEach(() => {
    localStorage.setItem('admin_token', 'archive-admin-test');
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  });
  afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

  it('uses the existing Command main landmark instead of nesting another one', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(page([]))));
    render(<main aria-label="Command workspace"><ArchivePage /></main>);
    await screen.findByText('No imported files in this folder');
    expect(screen.getAllByRole('main')).toHaveLength(1);
  });

  it('opens preserved folders and bundles to show original PDF names with authenticated downloads', async () => {
    const fetcher = vi.fn(async (input: string) => {
      const url = new URL(input);
      if (url.pathname.endsWith('/members/0/content')) return new Response('original PDF bytes');
      if (url.pathname.endsWith('/members')) return response(page([pdf], { bundle, domains: undefined, summary: { ...summary, folders: 0, documents: 1, document_bundles: 0 } }));
      const path = url.searchParams.get('path');
      return response(page(path === 'docusign_full/download_bundles' ? [bundle] : path === 'docusign_full' ? [folder('docusign_full/download_bundles')] : [folder('docusign_full')], { path: path || '' }));
    });
    vi.stubGlobal('fetch', fetcher);
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:archive-pdf'), revokeObjectURL: vi.fn() }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const user = userEvent.setup();
    render(<ArchivePage />);
    await user.click(await screen.findByRole('button', { name: 'Open folder docusign_full' }));
    await user.click(await screen.findByRole('button', { name: 'Open folder download_bundles' }));
    await user.click(await screen.findByRole('button', { name: 'Open bundle Lease.zip' }));
    expect(await screen.findByText('Original_Lease.pdf')).toBeVisible();
    expect(screen.getByText('Original document')).toBeVisible();
    expect(screen.getByRole('button', { name: 'DocuSign 1' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Download Original_Lease.pdf' }));
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    const download = fetcher.mock.calls.find(([input]) => input.endsWith('/members/0/content'));
    expect(download).toBeDefined();
    expect(fetcher).toHaveBeenLastCalledWith(expect.stringContaining('/artifacts/21/members/0/content'), expect.objectContaining({ headers: { Authorization: 'Bearer archive-admin-test' } }));
    expect(screen.getByRole('button', { name: 'Back to containing folder' })).toBeVisible();
  });

  it('ignores an older source result after switching to DocuSign even if cancellation is ignored', async () => {
    const old = deferred<Response>();
    let initialSignal: AbortSignal | undefined;
    vi.stubGlobal('fetch', vi.fn((input: string, init?: RequestInit) => {
      if (new URL(input).searchParams.get('domain') === 'docusign') return Promise.resolve(response(page([folder('DocuSign only')])));
      initialSignal = init?.signal ?? undefined;
      return old.promise;
    }));
    const user = userEvent.setup();
    render(<ArchivePage />);
    await user.click(screen.getByRole('button', { name: /^DocuSign/ }));
    expect(await screen.findByRole('button', { name: 'Open folder DocuSign only' })).toBeVisible();
    await act(async () => { old.resolve(response(page([folder('Stale Command folder')]))); });
    expect(screen.queryByText('Stale Command folder')).not.toBeInTheDocument();
    expect(initialSignal?.aborted).toBe(true);
  });

  it('searches every descendant and resets pagination when the search changes', async () => {
    const requests: URL[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = new URL(input); requests.push(url);
      const offset = Number(url.searchParams.get('offset') || 0);
      const query = url.searchParams.get('query') || '';
      return response(page(query ? [] : [bundle], { total: query ? 0 : 101, offset, query, summary: query ? { ...summary, files: 0, folders: 0, document_bundles: 0 } : summary }));
    }));
    const user = userEvent.setup();
    render(<ArchivePage />);
    await screen.findByText('Lease.zip');
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(requests.at(-1)?.searchParams.get('offset')).toBe('100'));
    await user.type(screen.getByRole('searchbox', { name: 'Search files and folders' }), 'missing lease');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    expect(await screen.findByText('No matching files')).toBeVisible();
    expect(requests.at(-1)?.searchParams.get('offset')).toBe('0');
    expect(requests.at(-1)?.searchParams.get('query')).toBe('missing lease');
    expect(screen.getByText('0 of 0 entries')).toBeVisible();
  });

  it('shows a loading skeleton and a recoverable error without a false empty result', async () => {
    const pending = deferred<Response>();
    const fetcher = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(response(page([])));
    vi.stubGlobal('fetch', fetcher);
    const user = userEvent.setup();
    render(<ArchivePage />);
    expect(screen.getByRole('status', { name: 'Loading archive' })).toBeInTheDocument();
    await act(async () => { pending.resolve(response({ detail: 'Archive is temporarily unavailable' }, 503)); });
    expect(await screen.findByRole('alert')).toHaveTextContent('Archive is temporarily unavailable');
    expect(screen.queryByText('No imported files in this folder')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('No imported files in this folder')).toBeVisible();
  });

  it('labels source captures and keeps unavailable originals visible', async () => {
    const capture = { ...bundle, id: 22, filename: 'page.snapshot.txt', artifact_type: 'txt', content_kind: 'source_capture', download_available: false, path: 'docusign/pages/page.snapshot.txt' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(page([capture], { summary: { ...summary, source_captures: 1, document_bundles: 0, unavailable_files: 1 } }))));
    render(<ArchivePage />);
    expect(await screen.findByText('Source capture')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Download page.snapshot.txt' })).toBeDisabled();
    expect(screen.getByText('Original bytes are not available')).toBeVisible();
  });
});
