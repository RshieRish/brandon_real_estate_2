import { cache } from 'react';
import { notFound } from 'next/navigation';
import type { Metadata } from 'next';

import BlogArticleClient, { type Blog } from './BlogArticleClient';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? 'https://soldwithsweeney.com').replace(/\/$/, '');

// React.cache memoizes within a single request so generateMetadata + the page
// component share one fetch instead of doubling up.
const getBlog = cache(async (slug: string): Promise<Blog | null> => {
  try {
    const res = await fetch(`${API_URL}/api/v1/blog/${encodeURIComponent(slug)}`, {
      // Revalidate at most every 5 minutes — fresh enough for new posts,
      // cached enough that bot crawls don't hammer Railway.
      next: { revalidate: 300 },
    });
    if (res.status === 404) return null;
    if (!res.ok) return null;
    return (await res.json()) as Blog;
  } catch {
    return null;
  }
});

type Params = { slug: string };

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { slug } = await params;
  const blog = await getBlog(slug);

  if (!blog) {
    return {
      title: 'Article not found',
      robots: { index: false, follow: false },
    };
  }

  const description =
    blog.excerpt?.trim() ||
    `${blog.title} — insights from Brandon Sweeney's team at Sold With Sweeney & Co.`;
  const canonical = `${SITE_URL}/blog/${blog.slug}`;
  const ogImage = blog.image_url ?? `${SITE_URL}/logos/sws-primary-white-gold.png`;

  return {
    title: `${blog.title} | Sold With Sweeney & Co.`,
    description,
    keywords: [
      blog.category ?? 'Real Estate',
      'Massachusetts Real Estate',
      'New Hampshire Real Estate',
      'Brandon Sweeney',
      'REALTOR®',
      'Northern MA',
      'Southern NH',
    ],
    authors: [{ name: blog.author }],
    alternates: { canonical },
    openGraph: {
      type: 'article',
      url: canonical,
      title: blog.title,
      description,
      siteName: 'Sold With Sweeney & Co.',
      publishedTime: blog.created_at,
      authors: [blog.author],
      images: [{ url: ogImage, width: 1200, height: 630, alt: blog.title }],
    },
    twitter: {
      card: 'summary_large_image',
      title: blog.title,
      description,
      images: [ogImage],
    },
  };
}

export default async function BlogArticlePage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { slug } = await params;
  const blog = await getBlog(slug);
  if (!blog) notFound();

  const canonical = `${SITE_URL}/blog/${blog.slug}`;
  const ogImage = blog.image_url ?? `${SITE_URL}/logos/sws-primary-white-gold.png`;

  // BlogPosting schema for rich snippets in Google.
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'BlogPosting',
    headline: blog.title,
    description: blog.excerpt ?? undefined,
    image: ogImage,
    datePublished: blog.created_at,
    dateModified: blog.created_at,
    author: {
      '@type': 'Person',
      name: blog.author,
      ...(blog.author_role ? { jobTitle: blog.author_role } : {}),
      ...(blog.author_bio ? { description: blog.author_bio } : {}),
    },
    publisher: {
      '@type': 'Organization',
      name: 'Sold With Sweeney & Co.',
      logo: {
        '@type': 'ImageObject',
        url: `${SITE_URL}/logos/sws-primary-white-gold.png`,
      },
    },
    mainEntityOfPage: { '@type': 'WebPage', '@id': canonical },
    articleSection: blog.category ?? undefined,
    wordCount: blog.content?.split(/\s+/).length ?? undefined,
  };

  return (
    <>
      <script
        type="application/ld+json"
        // JSON.stringify here is safe — we're embedding a literal object we constructed.
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <BlogArticleClient blog={blog} />
    </>
  );
}
