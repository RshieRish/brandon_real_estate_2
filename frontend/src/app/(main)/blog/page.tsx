'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowRight, Clock, BookOpen, MagnifyingGlass, WarningCircle } from '@phosphor-icons/react';

interface Blog {
  id: string;
  title: string;
  slug: string;
  excerpt: string | null;
  image_url: string | null;
  category: string | null;
  author: string;
  author_image_url: string | null;
  read_time_mins: number | null;
  created_at: string;
  featured: boolean;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const CATEGORIES = ['All', 'MA Real Estate', 'NH Real Estate', 'Brandon Sweeney', 'REALTOR® Insights', 'First-Time Buyers'];

const CATEGORY_COLORS: Record<string, string> = {
  'MA Real Estate': 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  'NH Real Estate': 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  'Brandon Sweeney': 'bg-gold/20 text-gold border-gold/30',
  'REALTOR® Insights': 'bg-purple-500/20 text-purple-300 border-purple-500/30',
  'First-Time Buyers': 'bg-orange-500/20 text-orange-300 border-orange-500/30',
};

function BlogCardSkeleton() {
  return (
    <div className="bg-dark-card border border-dark-border rounded-2xl overflow-hidden animate-pulse">
      <div className="aspect-[16/9] bg-dark-border" />
      <div className="p-6 space-y-3">
        <div className="h-3 w-24 bg-dark-border rounded" />
        <div className="h-5 w-full bg-dark-border rounded" />
        <div className="h-5 w-4/5 bg-dark-border rounded" />
        <div className="h-3 w-full bg-dark-border rounded mt-4" />
        <div className="h-3 w-3/4 bg-dark-border rounded" />
        <div className="flex items-center gap-3 mt-4">
          <div className="w-8 h-8 rounded-full bg-dark-border" />
          <div className="h-3 w-28 bg-dark-border rounded" />
        </div>
      </div>
    </div>
  );
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });
}

function CategoryBadge({ category }: { category: string | null }) {
  if (!category) return null;
  const cls = CATEGORY_COLORS[category] ?? 'bg-white/10 text-white/60 border-white/10';
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-widest border ${cls}`}>
      {category}
    </span>
  );
}

function HeroCard({ blog }: { blog: Blog }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 100, damping: 20 }}
      className="relative col-span-full rounded-2xl overflow-hidden group cursor-pointer"
    >
      <Link href={`/blog/${blog.slug}`} className="block">
        {/* Image */}
        <div className="relative w-full h-[480px] md:h-[560px]">
          {blog.image_url ? (
            <Image
              src={blog.image_url}
              alt={blog.title}
              fill
              className="object-cover group-hover:scale-[1.02] transition-transform duration-700"
              priority
            />
          ) : (
            <div className="absolute inset-0 bg-gradient-to-br from-dark-card to-dark-surface halftone opacity-40" />
          )}
          {/* Cinematic overlay */}
          <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent" />
        </div>

        {/* Content overlay */}
        <div className="absolute inset-0 flex flex-col justify-end p-8 md:p-12">
          <div className="max-w-3xl">
            <div className="mb-3">
              <CategoryBadge category={blog.category} />
            </div>
            <h2 className="text-white font-black text-2xl md:text-4xl leading-tight mb-4 group-hover:text-gold transition-colors duration-300">
              {blog.title}
            </h2>
            {blog.excerpt && (
              <p className="text-white/70 text-base md:text-lg leading-relaxed mb-6 max-w-2xl line-clamp-2">
                {blog.excerpt}
              </p>
            )}
            <div className="flex items-center gap-4">
              {blog.author_image_url && (
                <Image
                  src={blog.author_image_url}
                  alt={blog.author}
                  width={36}
                  height={36}
                  className="rounded-full border border-white/20 flex-shrink-0"
                />
              )}
              <div className="flex items-center gap-3 text-white/50 text-sm">
                <span className="text-white/80 font-medium">{blog.author}</span>
                {blog.read_time_mins && (
                  <>
                    <span>·</span>
                    <span className="flex items-center gap-1">
                      <Clock size={12} />
                      {blog.read_time_mins} min read
                    </span>
                  </>
                )}
                <span>·</span>
                <span>{formatDate(blog.created_at)}</span>
              </div>
              <span className="ml-auto flex items-center gap-1.5 text-gold text-sm font-semibold group-hover:gap-3 transition-all duration-300">
                Read article <ArrowRight size={14} />
              </span>
            </div>
          </div>
        </div>
      </Link>
    </motion.div>
  );
}

function BlogCard({ blog, index }: { blog: Blog; index: number }) {
  return (
    <motion.article
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 100, damping: 20, delay: index * 0.06 }}
      className="group bg-dark-card border border-dark-border rounded-2xl overflow-hidden hover:border-gold/30 transition-colors duration-300 spotlight-card flex flex-col"
    >
      <Link href={`/blog/${blog.slug}`} className="flex flex-col flex-1">
        {/* Cover image */}
        <div className="relative aspect-[16/9] overflow-hidden bg-dark-border flex-shrink-0">
          {blog.image_url ? (
            <Image
              src={blog.image_url}
              alt={blog.title}
              fill
              className="object-cover group-hover:scale-[1.03] transition-transform duration-500"
            />
          ) : (
            <div className="absolute inset-0 bg-gradient-to-br from-dark-card to-dark-surface flex items-center justify-center">
              <BookOpen size={32} className="text-gold/30" />
            </div>
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
        </div>

        {/* Body */}
        <div className="p-6 flex flex-col flex-1 gap-3">
          <CategoryBadge category={blog.category} />

          <h3 className="text-white font-bold text-lg leading-snug group-hover:text-gold transition-colors duration-200 line-clamp-2">
            {blog.title}
          </h3>

          {blog.excerpt && (
            <p className="text-white/50 text-sm leading-relaxed line-clamp-3 flex-1">
              {blog.excerpt}
            </p>
          )}

          {/* Author row */}
          <div className="flex items-center gap-3 pt-3 border-t border-dark-border mt-auto">
            {blog.author_image_url && (
              <Image
                src={blog.author_image_url}
                alt={blog.author}
                width={28}
                height={28}
                className="rounded-full border border-white/10 flex-shrink-0"
              />
            )}
            <div className="flex flex-col gap-0.5 min-w-0">
              <span className="text-white/80 text-xs font-semibold truncate">{blog.author}</span>
              <div className="flex items-center gap-2 text-white/30 text-[10px]">
                <span>{formatDate(blog.created_at)}</span>
                {blog.read_time_mins && (
                  <>
                    <span>·</span>
                    <span className="flex items-center gap-0.5">
                      <Clock size={10} />
                      {blog.read_time_mins} min
                    </span>
                  </>
                )}
              </div>
            </div>
            <ArrowRight
              size={14}
              className="ml-auto text-white/20 group-hover:text-gold group-hover:translate-x-1 transition-all duration-200 flex-shrink-0"
            />
          </div>
        </div>
      </Link>
    </motion.article>
  );
}

export default function BlogPage() {
  const [blogs, setBlogs] = useState<Blog[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState('All');
  const [search, setSearch] = useState('');

  useEffect(() => {
    const fetchBlogs = async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/blog/?limit=50`);
        if (!res.ok) throw new Error('Failed to load blogs');
        const data = await res.json();
        setBlogs(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load blogs');
      } finally {
        setIsLoading(false);
      }
    };
    fetchBlogs();
  }, []);

  const filtered = blogs.filter((b) => {
    const catMatch = activeCategory === 'All' || b.category === activeCategory;
    const searchMatch =
      !search ||
      b.title.toLowerCase().includes(search.toLowerCase()) ||
      (b.excerpt ?? '').toLowerCase().includes(search.toLowerCase());
    return catMatch && searchMatch;
  });

  const featuredBlog = filtered.find((b) => b.featured) ?? filtered[0] ?? null;
  const gridBlogs = (featured: Blog | null) => filtered.filter((b) => b.id !== featured?.id);

  return (
    <section className="min-h-[100dvh] bg-dark-surface pt-8 pb-24">
      {/* Halftone texture header */}
      <div className="relative overflow-hidden">
        <div className="absolute inset-0 halftone opacity-[0.03] pointer-events-none" />
        <div className="max-w-7xl mx-auto px-6 py-16 md:py-20 relative">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: 'spring', stiffness: 100, damping: 20 }}
          >
            <span className="text-gold text-xs font-semibold uppercase tracking-[0.25em] mb-4 block">
              Sold With Sweeney & Co.
            </span>
            <h1 className="text-white font-black text-4xl md:text-6xl leading-none mb-4">
              Real Estate<br />
              <span className="text-gold">Insights</span>
            </h1>
            <p className="text-white/50 text-lg max-w-xl mt-4 leading-relaxed">
              Expert perspectives on the Massachusetts and New Hampshire real estate market —
              from the desk of Brandon Sweeney&apos;s team.
            </p>
          </motion.div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6">
        {/* Filter + search bar */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: 'spring', stiffness: 100, damping: 20, delay: 0.1 }}
          className="flex flex-col md:flex-row gap-4 items-start md:items-center mb-10"
        >
          {/* Category pills */}
          <div className="flex flex-wrap gap-2 flex-1">
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setActiveCategory(cat)}
                className={`px-4 py-1.5 rounded-full text-xs font-semibold border transition-all duration-200 cursor-pointer ${
                  activeCategory === cat
                    ? 'bg-gold text-black border-gold'
                    : 'bg-transparent text-white/50 border-dark-border hover:border-white/20 hover:text-white/80'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
          {/* Search */}
          <div className="relative flex-shrink-0 w-full md:w-64">
            <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
            <input
              type="text"
              placeholder="Search articles..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-8 pr-4 py-2 bg-dark-card border border-dark-border rounded-full text-white/80 text-sm placeholder:text-white/20 focus:outline-none focus:border-gold/40 transition-colors"
            />
          </div>
        </motion.div>

        {/* Error state */}
        {error && (
          <div className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/20 rounded-xl mb-8">
            <WarningCircle weight="fill" className="w-5 h-5 text-red-400 flex-shrink-0" />
            <p className="text-red-400 text-sm">{error}</p>
          </div>
        )}

        {/* Grid */}
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {Array.from({ length: 6 }).map((_, i) => <BlogCardSkeleton key={i} />)}
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 text-center">
            <BookOpen size={40} className="text-white/10 mb-4" />
            <p className="text-white/40 text-lg font-semibold">No articles yet</p>
            <p className="text-white/25 text-sm mt-1">Check back soon — new posts are on the way.</p>
          </div>
        ) : (
          <AnimatePresence mode="wait">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {/* Featured hero — spans full width */}
              {featuredBlog && activeCategory === 'All' && !search && (
                <div className="col-span-full">
                  <HeroCard blog={featuredBlog} />
                </div>
              )}
              {/* Remaining grid cards */}
              {(activeCategory !== 'All' || search ? filtered : gridBlogs(featuredBlog)).map(
                (blog, i) => (
                  <BlogCard key={blog.id} blog={blog} index={i} />
                )
              )}
            </div>
          </AnimatePresence>
        )}
      </div>

      {/* KW Disclaimer */}
      <p className="text-white/20 text-xs text-center max-w-2xl mx-auto mt-20 px-6 leading-relaxed">
        Sold With Sweeney &amp; Co. is powered by Keller Williams Realty Success. This content is for informational
        purposes only and does not constitute legal or financial advice. Each office is independently owned and operated.
      </p>
    </section>
  );
}
