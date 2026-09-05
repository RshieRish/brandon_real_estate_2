import { afterEach, expect, it, vi } from 'vitest';
import { archiveApi } from './archive';
import { CommandDecodeError } from './http';

const summary = { files: 0, folders: 0, documents: 0, document_bundles: 0, source_captures: 0, data_exports: 0, supporting_files: 0, unavailable_files: 0 };
const page = { entries: [], total: 0, summary, path: '', query: '', offset: 0, limit: 100, domains: {} };

afterEach(() => vi.unstubAllGlobals());

it('encodes literal folder/search text and forwards cancellation through authenticated transport', async () => {
  vi.stubGlobal('localStorage', { getItem: () => 'archive-session' });
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(page)));
  vi.stubGlobal('fetch', fetcher);
  const controller = new AbortController();
  await archiveApi.browse({ domain: 'docusign', path: 'docusign_full/100%_done', query: 'A & B', offset: 100, signal: controller.signal });
  const url = new URL(fetcher.mock.calls[0][0]);
  expect(url.searchParams.get('path')).toBe('docusign_full/100%_done');
  expect(url.searchParams.get('query')).toBe('A & B');
  expect(url.searchParams.get('offset')).toBe('100');
  expect(fetcher.mock.calls[0][1]).toMatchObject({ signal: controller.signal, headers: { Authorization: 'Bearer archive-session' } });
});

it.each([
  { ...page, summary: {} },
  { ...page, summary: { ...summary, files: -1 } },
  { ...page, entries: [{ entry_type: 'folder', path: 'folder' }], total: 1 },
  { ...page, entries: [{ entry_type: 'member', member_index: -1, filename: 'File.pdf' }], total: 1 },
])('rejects malformed archive entries and counts before they reach the browser', async (payload) => {
  vi.stubGlobal('localStorage', { getItem: () => 'archive-session' });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))));
  await expect(archiveApi.browse({})).rejects.toBeInstanceOf(CommandDecodeError);
});
