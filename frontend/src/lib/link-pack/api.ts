import type { LinkPackSnapshot } from './types';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export async function fetchPublicLinkPack(): Promise<LinkPackSnapshot | null> {
  const res = await fetch(`${API_URL}/api/v1/link-pack/`, { cache: 'no-store' });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to fetch link pack: ${res.status}`);
  return (await res.json()) as LinkPackSnapshot;
}

export function imageUrl(path: string | null): string | null {
  if (!path) return null;
  if (path.startsWith('http')) return path;
  return `${API_URL}${path}`;
}
