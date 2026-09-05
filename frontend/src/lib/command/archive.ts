import { commandBlob, CommandDecodeError, commandJson } from './http';

export type ArchiveContentKind = 'document_bundle' | 'document' | 'source_capture' | 'data_export' | 'supporting_file';
export type ArchiveFolderEntry = { entry_type: 'folder'; path: string; name: string; file_count: number };
type ArchiveFile = { path: string; filename: string; artifact_type: string; size_bytes: number; content_kind: ArchiveContentKind; download_available: boolean };
export type ArchiveArtifactEntry = ArchiveFile & { entry_type: 'artifact'; id: number; domain: string; source_path: string; sha256: string };
export type ArchiveMemberEntry = ArchiveFile & { entry_type: 'member'; member_index: number; unavailable_reason: string | null; unsafe_path: boolean };
export type ArchiveEntry = ArchiveFolderEntry | ArchiveArtifactEntry | ArchiveMemberEntry;
export type ArchiveSummary = { files: number; folders: number; document_bundles: number; documents: number; source_captures: number; data_exports: number; supporting_files: number; unavailable_files: number };
export type ArchivePage = {
  path: string; query: string; limit: number; offset: number; total: number;
  entries: ArchiveEntry[]; summary: ArchiveSummary;
  domains?: Record<string, number>; bundle?: ArchiveArtifactEntry;
};
export type ArchiveBrowseOptions = { domain?: string; path?: string; query?: string; offset?: number; limit?: number; signal?: AbortSignal };

function decodePage(value: unknown): ArchivePage {
  const record = (item: unknown): item is Record<string, unknown> => typeof item === 'object' && item !== null && !Array.isArray(item);
  const count = (item: unknown) => typeof item === 'number' && Number.isSafeInteger(item) && item >= 0;
  const summaryKeys = ['files', 'folders', 'documents', 'document_bundles', 'source_captures', 'data_exports', 'supporting_files', 'unavailable_files'];
  const kinds = ['document_bundle', 'document', 'source_capture', 'data_export', 'supporting_file'];
  const entry = (item: unknown): boolean => {
    if (!record(item) || typeof item.path !== 'string') return false;
    if (item.entry_type === 'folder') return typeof item.name === 'string' && count(item.file_count);
    if (typeof item.filename !== 'string' || typeof item.artifact_type !== 'string'
        || !count(item.size_bytes) || typeof item.download_available !== 'boolean'
        || typeof item.content_kind !== 'string' || !kinds.includes(item.content_kind)) return false;
    if (item.entry_type === 'artifact') return count(item.id) && Number(item.id) > 0 && typeof item.sha256 === 'string' && typeof item.domain === 'string' && typeof item.source_path === 'string';
    return item.entry_type === 'member' && count(item.member_index) && typeof item.unsafe_path === 'boolean' && (item.unavailable_reason === null || typeof item.unavailable_reason === 'string');
  };
  if (!record(value) || !Array.isArray(value.entries) || !value.entries.every(entry)
      || !record(value.summary) || !summaryKeys.every((key) => count((value.summary as Record<string, unknown>)[key]))
      || !count(value.total) || !count(value.offset) || !count(value.limit) || Number(value.limit) < 1 || Number(value.limit) > 200
      || typeof value.path !== 'string' || typeof value.query !== 'string'
      || (value.domains !== undefined && (!record(value.domains) || !Object.values(value.domains).every(count)))
      || (value.bundle !== undefined && (!entry(value.bundle) || !record(value.bundle) || value.bundle.entry_type !== 'artifact'))) {
    throw new CommandDecodeError('archive', 'an archive page');
  }
  return value as unknown as ArchivePage;
}

function browseParams(options: ArchiveBrowseOptions): URLSearchParams {
  const params = new URLSearchParams({ path: options.path ?? '', query: options.query ?? '', limit: String(options.limit ?? 100), offset: String(options.offset ?? 0) });
  if (options.domain) params.set('domain', options.domain);
  return params;
}

export const archiveApi = {
  browse: (options: ArchiveBrowseOptions) => commandJson({ path: `/archive/browse?${browseParams(options)}`, decode: decodePage, signal: options.signal }),
  members: (id: number, options: ArchiveBrowseOptions) => commandJson({ path: `/archive/artifacts/${id}/members?${browseParams(options)}`, decode: decodePage, signal: options.signal }),
  original: (id: number, signal?: AbortSignal) => commandBlob({ path: `/archive/artifacts/${id}/content`, signal }),
  member: (id: number, memberIndex: number, signal?: AbortSignal) => commandBlob({ path: `/archive/artifacts/${id}/members/${memberIndex}/content`, signal }),
};
