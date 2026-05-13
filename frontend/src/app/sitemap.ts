import type { MetadataRoute } from 'next';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? 'https://soldwithsweeney.com').replace(/\/$/, '');

interface PublishedBlog {
  slug: string;
  created_at: string;
  updated_at?: string | null;
}

async function fetchBlogs(): Promise<PublishedBlog[]> {
  try {
    const res = await fetch(`${API_URL}/api/v1/blog/?limit=500`, {
      next: { revalidate: 600 },
    });
    if (!res.ok) return [];
    return (await res.json()) as PublishedBlog[];
  } catch {
    return [];
  }
}

const STATIC_ROUTES: { path: string; priority: number; changeFrequency: MetadataRoute.Sitemap[number]['changeFrequency'] }[] = [
  { path: '/', priority: 1.0, changeFrequency: 'weekly' },
  { path: '/buy', priority: 0.9, changeFrequency: 'monthly' },
  { path: '/sell', priority: 0.9, changeFrequency: 'monthly' },
  { path: '/invest', priority: 0.8, changeFrequency: 'monthly' },
  { path: '/about', priority: 0.8, changeFrequency: 'monthly' },
  { path: '/blog', priority: 0.9, changeFrequency: 'daily' },
];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();
  const entries: MetadataRoute.Sitemap = STATIC_ROUTES.map((r) => ({
    url: `${SITE_URL}${r.path}`,
    lastModified: now,
    changeFrequency: r.changeFrequency,
    priority: r.priority,
  }));

  const blogs = await fetchBlogs();
  for (const blog of blogs) {
    entries.push({
      url: `${SITE_URL}/blog/${blog.slug}`,
      lastModified: new Date(blog.updated_at || blog.created_at),
      changeFrequency: 'monthly',
      priority: 0.7,
    });
  }
  return entries;
}
