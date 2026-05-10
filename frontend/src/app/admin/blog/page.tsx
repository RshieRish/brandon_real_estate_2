'use client';

import { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Article, PlusCircle, Robot, Trash, Eye, EyeSlash,
  CircleNotch, WarningCircle, CheckCircle, Pencil,
} from '@phosphor-icons/react';

interface Blog {
  id: string;
  title: string;
  slug: string;
  category: string | null;
  is_posted: boolean;
  featured: boolean;
  read_time_mins: number | null;
  created_at: string;
  author: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const CATEGORIES = ['MA Real Estate', 'NH Real Estate', 'Brandon Sweeney', 'REALTOR® Insights', 'First-Time Buyers'];

type Tab = 'posts' | 'generate' | 'manual';

function getToken() { return localStorage.getItem('admin_token') ?? ''; }

function Toast({ msg, ok }: { msg: string; ok: boolean }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}
      className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 px-5 py-3 rounded-xl border shadow-xl text-sm font-semibold ${ok ? 'bg-dark-card border-gold/30 text-white' : 'bg-dark-card border-red-500/30 text-red-400'}`}
    >
      {ok ? <CheckCircle weight="fill" className="text-gold w-4 h-4" /> : <WarningCircle weight="fill" className="w-4 h-4" />}
      {msg}
    </motion.div>
  );
}

export default function AdminBlogPage() {
  const [tab, setTab] = useState<Tab>('posts');
  const [blogs, setBlogs] = useState<Blog[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  // Generate tab state
  const [genTopic, setGenTopic] = useState('');
  const [genCategory, setGenCategory] = useState(CATEGORIES[0]);
  const [genLoading, setGenLoading] = useState(false);
  const [genResult, setGenResult] = useState<{ title: string; slug: string; id: string } | null>(null);

  // Manual tab state
  const [manTitle, setManTitle] = useState('');
  const [manContent, setManContent] = useState('');
  const [manCategory, setManCategory] = useState(CATEGORIES[0]);
  const [manPosted, setManPosted] = useState(false);
  const [manImage, setManImage] = useState<File | null>(null);
  const [manLoading, setManLoading] = useState(false);

  // Auto-pilot state
  const [autoLoading, setAutoLoading] = useState(false);

  const showToast = (msg: string, ok = true) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3500);
  };

  const fetchBlogs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/blog/admin/all?limit=100`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!res.ok) throw new Error();
      setBlogs(await res.json());
    } catch { showToast('Failed to load blogs', false); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchBlogs(); }, [fetchBlogs]);

  const togglePublish = async (blog: Blog) => {
    try {
      const res = await fetch(`${API_URL}/api/v1/blog/${blog.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ is_posted: !blog.is_posted }),
      });
      if (!res.ok) throw new Error();
      setBlogs(prev => prev.map(b => b.id === blog.id ? { ...b, is_posted: !b.is_posted } : b));
      showToast(blog.is_posted ? 'Post unpublished' : 'Post published');
    } catch { showToast('Failed to update', false); }
  };

  const deleteBlog = async (id: string) => {
    if (!confirm('Delete this blog post?')) return;
    try {
      const res = await fetch(`${API_URL}/api/v1/blog/${id}`, {
        method: 'DELETE', headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!res.ok) throw new Error();
      setBlogs(prev => prev.filter(b => b.id !== id));
      showToast('Post deleted');
    } catch { showToast('Failed to delete', false); }
  };

  const runAutoPilot = async () => {
    setAutoLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/blog/cron`, {
        method: 'POST', headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!res.ok) throw new Error();
      showToast('Auto blog generated and published!');
      fetchBlogs();
    } catch { showToast('Auto generation failed', false); }
    finally { setAutoLoading(false); }
  };

  const runGenerate = async () => {
    if (!genTopic.trim()) return;
    setGenLoading(true); setGenResult(null);
    try {
      const res = await fetch(`${API_URL}/api/v1/blog/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ topic: genTopic, category: genCategory }),
      });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setGenResult({ title: data.blog.title, slug: data.blog.slug, id: data.blog.id });
      showToast('Draft generated! Review it in All Posts.');
      fetchBlogs();
    } catch { showToast('Generation failed', false); }
    finally { setGenLoading(false); }
  };

  const submitManual = async () => {
    if (!manTitle.trim() || !manContent.trim()) return;
    setManLoading(true);
    try {
      const fd = new FormData();
      fd.append('title', manTitle);
      fd.append('content', manContent);
      fd.append('category', manCategory);
      fd.append('is_posted', String(manPosted));
      if (manImage) fd.append('image', manImage);
      const res = await fetch(`${API_URL}/api/v1/blog/`, {
        method: 'POST', headers: { Authorization: `Bearer ${getToken()}` }, body: fd,
      });
      if (!res.ok) throw new Error();
      showToast('Post created!');
      setManTitle(''); setManContent(''); setManPosted(false); setManImage(null);
      fetchBlogs(); setTab('posts');
    } catch { showToast('Create failed', false); }
    finally { setManLoading(false); }
  };

  const TABS: { id: Tab; label: string; icon: typeof Article }[] = [
    { id: 'posts', label: 'All Posts', icon: Article },
    { id: 'generate', label: 'Generate Draft', icon: Robot },
    { id: 'manual', label: 'Manual Create', icon: PlusCircle },
  ];

  return (
    <div className="p-8 w-full">
      <AnimatePresence>{toast && <Toast msg={toast.msg} ok={toast.ok} />}</AnimatePresence>

      {/* Header */}
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', stiffness: 100, damping: 20 }}>
        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="text-white font-black text-2xl">Blog Control</h1>
            <p className="text-white/40 text-sm mt-1">Manage posts, generate drafts, or publish manually</p>
          </div>
          {/* Auto-pilot button */}
          <button
            onClick={runAutoPilot}
            disabled={autoLoading}
            className="flex items-center gap-2 bg-gold hover:bg-gold-hover disabled:opacity-50 text-black font-black text-sm px-5 py-2.5 rounded-xl transition-colors cursor-pointer disabled:cursor-not-allowed"
          >
            {autoLoading ? <CircleNotch className="animate-spin w-4 h-4" /> : <Robot size={16} weight="fill" />}
            Auto-Pilot
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-dark-card border border-dark-border rounded-xl p-1 mb-8 w-fit">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all duration-200 cursor-pointer ${tab === id ? 'bg-gold text-black' : 'text-white/50 hover:text-white/80'}`}
            >
              <Icon size={15} weight={tab === id ? 'fill' : 'regular'} />
              {label}
            </button>
          ))}
        </div>
      </motion.div>

      <AnimatePresence mode="wait">
        {/* ── ALL POSTS ── */}
        {tab === 'posts' && (
          <motion.div key="posts" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ type: 'spring', stiffness: 100, damping: 20 }}>
            {loading ? (
              <div className="flex items-center justify-center py-24"><CircleNotch className="animate-spin text-gold w-7 h-7" /></div>
            ) : blogs.length === 0 ? (
              <div className="flex flex-col items-center py-24 text-center">
                <Article size={36} className="text-white/10 mb-3" />
                <p className="text-white/40 text-sm">No posts yet. Generate one or create manually.</p>
              </div>
            ) : (
              <div className="bg-dark-card border border-dark-border rounded-2xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="border-b border-dark-border">
                    <tr>
                      {['Title', 'Category', 'Status', 'Date', 'Actions'].map(h => (
                        <th key={h} className="text-left px-5 py-3 text-white/30 text-xs uppercase tracking-widest font-semibold">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-dark-border">
                    {blogs.map((blog, i) => (
                      <motion.tr
                        key={blog.id}
                        initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                        transition={{ delay: i * 0.03 }}
                        className="hover:bg-white/[0.02] transition-colors group"
                      >
                        <td className="px-5 py-3.5 max-w-xs">
                          <p className="text-white font-semibold truncate group-hover:text-gold transition-colors">{blog.title}</p>
                          <p className="text-white/30 text-xs truncate mt-0.5">/{blog.slug}</p>
                        </td>
                        <td className="px-5 py-3.5">
                          <span className="text-white/50 text-xs">{blog.category ?? '—'}</span>
                        </td>
                        <td className="px-5 py-3.5">
                          <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-0.5 rounded-full border ${blog.is_posted ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-white/5 text-white/40 border-dark-border'}`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${blog.is_posted ? 'bg-emerald-400' : 'bg-white/20'}`} />
                            {blog.is_posted ? 'Published' : 'Draft'}
                          </span>
                        </td>
                        <td className="px-5 py-3.5 text-white/30 text-xs whitespace-nowrap">
                          {new Date(blog.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-5 py-3.5">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => togglePublish(blog)}
                              title={blog.is_posted ? 'Unpublish' : 'Publish'}
                              className="p-1.5 rounded-lg hover:bg-white/5 text-white/40 hover:text-gold transition-colors cursor-pointer"
                            >
                              {blog.is_posted ? <EyeSlash size={15} /> : <Eye size={15} />}
                            </button>
                            <a
                              href={`/blog/${blog.slug}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="p-1.5 rounded-lg hover:bg-white/5 text-white/40 hover:text-white transition-colors"
                              title="View live"
                            >
                              <Pencil size={15} />
                            </a>
                            <button
                              onClick={() => deleteBlog(blog.id)}
                              className="p-1.5 rounded-lg hover:bg-red-500/10 text-white/30 hover:text-red-400 transition-colors cursor-pointer"
                              title="Delete"
                            >
                              <Trash size={15} />
                            </button>
                          </div>
                        </td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </motion.div>
        )}

        {/* ── GENERATE DRAFT ── */}
        {tab === 'generate' && (
          <motion.div key="generate" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ type: 'spring', stiffness: 100, damping: 20 }} className="max-w-2xl">
            <div className="bg-dark-card border border-dark-border rounded-2xl p-8 space-y-6">
              <div>
                <p className="text-white/30 text-xs uppercase tracking-widest font-semibold mb-1">Mode</p>
                <p className="text-white/60 text-sm">Provide a topic and category — Gemini writes a full draft, saved as a draft for your review.</p>
              </div>
              <div className="space-y-4">
                <div>
                  <label className="text-white/50 text-xs font-semibold uppercase tracking-widest block mb-2">Topic / Article Angle</label>
                  <input
                    type="text"
                    value={genTopic}
                    onChange={e => setGenTopic(e.target.value)}
                    placeholder="e.g. Why Southern NH is attracting MA buyers in 2025"
                    className="w-full bg-dark-surface border border-dark-border text-white px-4 py-3 rounded-xl text-sm placeholder:text-white/20 focus:outline-none focus:border-gold/40 transition-colors"
                  />
                </div>
                <div>
                  <label className="text-white/50 text-xs font-semibold uppercase tracking-widest block mb-2">Category</label>
                  <select
                    value={genCategory}
                    onChange={e => setGenCategory(e.target.value)}
                    className="w-full bg-dark-surface border border-dark-border text-white px-4 py-3 rounded-xl text-sm focus:outline-none focus:border-gold/40 transition-colors cursor-pointer"
                  >
                    {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>
              <button
                onClick={runGenerate}
                disabled={genLoading || !genTopic.trim()}
                className="flex items-center justify-center gap-2 w-full bg-gold hover:bg-gold-hover disabled:opacity-40 text-black font-black text-sm py-3.5 rounded-xl transition-colors cursor-pointer disabled:cursor-not-allowed"
              >
                {genLoading ? <><CircleNotch className="animate-spin w-4 h-4" /> Gemini is writing...</> : <><Robot size={16} weight="fill" /> Generate Draft with Gemini</>}
              </button>
              {genResult && (
                <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-xl">
                  <p className="text-emerald-400 text-sm font-semibold flex items-center gap-2">
                    <CheckCircle weight="fill" size={16} /> Draft saved: &ldquo;{genResult.title}&rdquo;
                  </p>
                  <p className="text-white/40 text-xs mt-1">Go to All Posts to review and publish.</p>
                </motion.div>
              )}
            </div>
          </motion.div>
        )}

        {/* ── MANUAL CREATE ── */}
        {tab === 'manual' && (
          <motion.div key="manual" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ type: 'spring', stiffness: 100, damping: 20 }} className="max-w-2xl">
            <div className="bg-dark-card border border-dark-border rounded-2xl p-8 space-y-5">
              <div>
                <label className="text-white/50 text-xs font-semibold uppercase tracking-widest block mb-2">Title</label>
                <input type="text" value={manTitle} onChange={e => setManTitle(e.target.value)} placeholder="Article title" className="w-full bg-dark-surface border border-dark-border text-white px-4 py-3 rounded-xl text-sm placeholder:text-white/20 focus:outline-none focus:border-gold/40 transition-colors" />
              </div>
              <div>
                <label className="text-white/50 text-xs font-semibold uppercase tracking-widest block mb-2">Category</label>
                <select value={manCategory} onChange={e => setManCategory(e.target.value)} className="w-full bg-dark-surface border border-dark-border text-white px-4 py-3 rounded-xl text-sm focus:outline-none focus:border-gold/40 transition-colors cursor-pointer">
                  {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className="text-white/50 text-xs font-semibold uppercase tracking-widest block mb-2">Content (Markdown)</label>
                <textarea value={manContent} onChange={e => setManContent(e.target.value)} placeholder={'# Title\n\nWrite your blog post in Markdown...'} rows={14} className="w-full bg-dark-surface border border-dark-border text-white/80 px-4 py-3 rounded-xl text-sm placeholder:text-white/20 focus:outline-none focus:border-gold/40 transition-colors resize-y font-mono" />
              </div>
              <div>
                <label className="text-white/50 text-xs font-semibold uppercase tracking-widest block mb-2">Cover Image (optional)</label>
                <input type="file" accept="image/*" onChange={e => setManImage(e.target.files?.[0] ?? null)} className="w-full text-white/50 text-sm file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border file:border-dark-border file:bg-dark-surface file:text-white/60 file:text-xs file:cursor-pointer hover:file:border-gold/30 transition-colors" />
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setManPosted(!manPosted)}
                  className={`relative w-10 h-5 rounded-full transition-colors cursor-pointer ${manPosted ? 'bg-gold' : 'bg-dark-border'}`}
                >
                  <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${manPosted ? 'translate-x-5' : 'translate-x-0.5'}`} />
                </button>
                <span className="text-white/60 text-sm">{manPosted ? 'Publish immediately' : 'Save as draft'}</span>
              </div>
              <button
                onClick={submitManual}
                disabled={manLoading || !manTitle.trim() || !manContent.trim()}
                className="flex items-center justify-center gap-2 w-full bg-gold hover:bg-gold-hover disabled:opacity-40 text-black font-black text-sm py-3.5 rounded-xl transition-colors cursor-pointer disabled:cursor-not-allowed"
              >
                {manLoading ? <><CircleNotch className="animate-spin w-4 h-4" /> Saving...</> : <><PlusCircle size={16} weight="fill" /> {manPosted ? 'Publish Post' : 'Save Draft'}</>}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
