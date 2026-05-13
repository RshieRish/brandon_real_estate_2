'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { motion } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ArrowLeft,
  ArrowRight,
  Clock,
  Calendar,
  Phone,
  CalendarCheck,
} from '@phosphor-icons/react';

export interface Blog {
  id: string;
  title: string;
  slug: string;
  content: string;
  excerpt: string | null;
  image_url: string | null;
  category: string | null;
  author: string;
  author_role: string | null;
  author_bio: string | null;
  author_image_url: string | null;
  read_time_mins: number | null;
  created_at: string;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });
}

const MarkdownComponents = {
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="text-white font-black text-3xl md:text-4xl leading-tight mb-6 mt-2">{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="text-white font-black text-xl md:text-2xl leading-tight mb-4 mt-10 pt-6 border-t border-dark-border">
      {children}
    </h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="text-white font-bold text-lg leading-snug mb-3 mt-6">{children}</h3>
  ),
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="text-white/70 leading-relaxed mb-5 text-base">{children}</p>
  ),
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="text-white font-semibold">{children}</strong>
  ),
  em: ({ children }: { children?: React.ReactNode }) => (
    <em className="text-white/80 italic">{children}</em>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="text-white/70 list-disc list-outside pl-5 mb-5 space-y-2">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="text-white/70 list-decimal list-outside pl-5 mb-5 space-y-2">{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li className="leading-relaxed">{children}</li>
  ),
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="border-l-4 border-gold pl-5 py-1 my-6 bg-gold/5 rounded-r-lg">
      <span className="text-gold/90 italic leading-relaxed block">{children}</span>
    </blockquote>
  ),
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a
      href={href}
      target={href?.startsWith('http') ? '_blank' : undefined}
      rel={href?.startsWith('http') ? 'noopener noreferrer' : undefined}
      className="text-gold underline underline-offset-2 hover:text-gold-hover transition-colors"
    >
      {children}
    </a>
  ),
  table: ({ children }: { children?: React.ReactNode }) => (
    <div className="overflow-x-auto my-6 rounded-xl border border-dark-border">
      <table className="w-full text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }: { children?: React.ReactNode }) => (
    <thead className="bg-dark-card border-b border-dark-border">{children}</thead>
  ),
  th: ({ children }: { children?: React.ReactNode }) => (
    <th className="text-gold font-semibold text-left px-4 py-3 text-xs uppercase tracking-widest">{children}</th>
  ),
  tbody: ({ children }: { children?: React.ReactNode }) => (
    <tbody className="divide-y divide-dark-border">{children}</tbody>
  ),
  tr: ({ children }: { children?: React.ReactNode }) => (
    <tr className="hover:bg-white/[0.02] transition-colors">{children}</tr>
  ),
  td: ({ children }: { children?: React.ReactNode }) => (
    <td className="text-white/60 px-4 py-3 leading-relaxed">{children}</td>
  ),
  hr: () => <hr className="border-dark-border my-8" />,
  code: ({ children, className }: { children?: React.ReactNode; className?: string }) => {
    const isInline = !className;
    return isInline ? (
      <code className="bg-dark-card text-gold px-1.5 py-0.5 rounded text-sm font-mono">{children}</code>
    ) : (
      <code className="block bg-dark-card text-white/80 p-4 rounded-xl text-sm font-mono overflow-x-auto my-4">
        {children}
      </code>
    );
  },
};

export default function BlogArticleClient({ blog }: { blog: Blog }) {
  const [readProgress, setReadProgress] = useState(0);
  const articleRef = useRef<HTMLElement>(null);

  // Reading progress bar
  useEffect(() => {
    const onScroll = () => {
      if (!articleRef.current) return;
      const el = articleRef.current;
      const scrolled = window.scrollY - el.offsetTop;
      const total = el.scrollHeight - window.innerHeight;
      setReadProgress(Math.min(100, Math.max(0, (scrolled / total) * 100)));
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <>
      {/* Gold reading progress bar */}
      <motion.div
        className="fixed top-0 left-0 h-0.5 bg-gold z-50 origin-left"
        style={{ scaleX: readProgress / 100 }}
        transition={{ type: 'spring', stiffness: 400, damping: 40 }}
      />

      <div className="min-h-[100dvh] bg-dark-surface">
        {/* Hero image */}
        {blog.image_url && (
          <div className="relative w-full h-[360px] md:h-[500px]">
            <Image
              src={blog.image_url}
              alt={blog.title}
              fill
              className="object-cover"
              priority
            />
            <div className="absolute inset-0 bg-gradient-to-t from-dark-surface via-dark-surface/50 to-transparent" />
          </div>
        )}

        <div className="max-w-7xl mx-auto px-6 pb-24 -mt-16 relative">
          <div className="flex flex-col lg:flex-row gap-12 lg:gap-16">
            {/* Main article */}
            <article ref={articleRef} className="flex-1 min-w-0">
              {/* Back link */}
              <motion.div
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ type: 'spring', stiffness: 100, damping: 20 }}
              >
                <Link
                  href="/blog"
                  className="inline-flex items-center gap-1.5 text-white/40 text-sm hover:text-gold transition-colors mb-8"
                >
                  <ArrowLeft size={14} /> All Articles
                </Link>
              </motion.div>

              {/* Category + meta */}
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: 'spring', stiffness: 100, damping: 20, delay: 0.05 }}
                className="flex flex-wrap items-center gap-3 mb-6"
              >
                {blog.category && (
                  <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-gold border border-gold/30 px-3 py-1 rounded-full">
                    {blog.category}
                  </span>
                )}
                <span className="flex items-center gap-1.5 text-white/30 text-xs">
                  <Calendar size={12} /> {formatDate(blog.created_at)}
                </span>
                {blog.read_time_mins && (
                  <span className="flex items-center gap-1.5 text-white/30 text-xs">
                    <Clock size={12} /> {blog.read_time_mins} min read
                  </span>
                )}
              </motion.div>

              <div className="w-12 h-0.5 bg-gold mb-8" />

              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: 'spring', stiffness: 100, damping: 20, delay: 0.1 }}
                className="prose-blog"
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={MarkdownComponents}>
                  {blog.content}
                </ReactMarkdown>
              </motion.div>

              {/* Author card (bottom) */}
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: 'spring', stiffness: 100, damping: 20, delay: 0.15 }}
                className="mt-12 p-6 bg-dark-card border border-dark-border rounded-2xl flex gap-5"
              >
                {blog.author_image_url && (
                  <Image
                    src={blog.author_image_url}
                    alt={blog.author}
                    width={60}
                    height={60}
                    className="rounded-full border border-gold/20 flex-shrink-0 self-start"
                  />
                )}
                <div>
                  <p className="text-white font-bold text-base">{blog.author}</p>
                  {blog.author_role && (
                    <p className="text-gold text-xs font-semibold uppercase tracking-widest mt-0.5 mb-3">{blog.author_role}</p>
                  )}
                  {blog.author_bio && (
                    <p className="text-white/50 text-sm leading-relaxed">{blog.author_bio}</p>
                  )}
                </div>
              </motion.div>

              <p className="text-white/20 text-xs mt-10 leading-relaxed">
                Sold With Sweeney &amp; Co. is powered by Keller Williams Realty Success. This content is for
                informational purposes only and does not constitute legal or financial advice.
                Each Keller Williams office is independently owned and operated.
              </p>
            </article>

            {/* Sticky sidebar */}
            <aside className="lg:w-72 xl:w-80 flex-shrink-0">
              <div className="sticky top-24 flex flex-col gap-6">
                <motion.div
                  initial={{ opacity: 0, x: 16 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ type: 'spring', stiffness: 100, damping: 20, delay: 0.12 }}
                  className="bg-dark-card border border-gold/20 rounded-2xl p-6 overflow-hidden relative"
                >
                  <div className="absolute top-0 right-0 w-24 h-24 halftone opacity-10 rounded-bl-full" />
                  <span className="text-gold text-[10px] font-semibold uppercase tracking-[0.2em] block mb-3">
                    Ready to Move?
                  </span>
                  <h3 className="text-white font-black text-xl leading-snug mb-2">
                    Work With Brandon Sweeney
                  </h3>
                  <p className="text-white/50 text-sm leading-relaxed mb-5">
                    Northern MA and Southern NH&apos;s top-producing REALTOR®. 2025 NEAR President. REALTOR® of the Year.
                    Let&apos;s talk about your goals.
                  </p>
                  <Link
                    href="/about"
                    className="flex items-center justify-center gap-2 w-full bg-gold hover:bg-gold-hover text-black font-black text-sm py-3 rounded-xl transition-colors duration-200 mb-3"
                  >
                    <CalendarCheck size={16} weight="bold" />
                    Book a Strategy Call
                  </Link>
                  <a
                    href="tel:9789872806"
                    className="flex items-center justify-center gap-2 w-full bg-transparent border border-dark-border hover:border-gold/40 text-white/60 hover:text-white font-semibold text-sm py-2.5 rounded-xl transition-all duration-200"
                  >
                    <Phone size={14} />
                    (978) 987-2806
                  </a>
                </motion.div>

                <motion.div
                  initial={{ opacity: 0, x: 16 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ type: 'spring', stiffness: 100, damping: 20, delay: 0.18 }}
                  className="bg-dark-card border border-dark-border rounded-2xl p-5 flex gap-4"
                >
                  {blog.author_image_url && (
                    <Image
                      src={blog.author_image_url}
                      alt={blog.author}
                      width={48}
                      height={48}
                      className="rounded-full border border-white/10 flex-shrink-0"
                    />
                  )}
                  <div>
                    <p className="text-white font-semibold text-sm">{blog.author}</p>
                    {blog.author_role && (
                      <p className="text-white/40 text-xs mt-0.5">{blog.author_role}</p>
                    )}
                  </div>
                </motion.div>

                <Link
                  href="/blog"
                  className="flex items-center justify-between text-white/40 text-sm hover:text-white/70 transition-colors group px-1"
                >
                  <span>Browse all articles</span>
                  <ArrowRight size={14} className="group-hover:translate-x-1 transition-transform" />
                </Link>
              </div>
            </aside>
          </div>
        </div>
      </div>
    </>
  );
}
