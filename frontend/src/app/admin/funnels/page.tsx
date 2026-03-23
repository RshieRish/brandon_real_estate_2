'use client';

import { useEffect, useState, useCallback } from 'react';
import {
  Plus,
  WarningCircle,
  CircleNotch,
  X,
  CheckCircle,
  ArrowsClockwise,
  Link as LinkIcon,
  Eye,
  UploadSimple,
  Image as ImageIcon,
  Trash,
} from '@phosphor-icons/react';
import FunnelHero from '@/components/funnel/FunnelHero';
import FunnelRegistration from '@/components/funnel/FunnelRegistration';

interface FunnelRow {
  id: number;
  title: string;
  slug: string;
  audience: string;
  status: string;
  registrations: number | null;
  generated_content: string;
  hero_image_url: string | null;
  video_url: string | null;
  cta_text: string;
  created_at: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000';

const AUDIENCE_OPTIONS = ['buyer', 'seller', 'investor'] as const;

export default function FunnelsPage() {
  const [funnels, setFunnels] = useState<FunnelRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [previewFunnel, setPreviewFunnel] = useState<FunnelRow | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishSuccess, setPublishSuccess] = useState(false);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
  const [isUploadingImage, setIsUploadingImage] = useState(false);
  const [form, setForm] = useState({
    title: '',
    audience: 'buyer',
    description: '',
    cta_text: '',
    video_url: '',
  });

  const getToken = () => localStorage.getItem('admin_token');

  const fetchFunnels = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setError('Not authenticated. Please log in.');
      setIsLoading(false);
      return;
    }
    try {
      const res = await fetch(`${API_URL}/api/v1/funnels/`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Failed to load funnels');
      const data = await res.json();
      setFunnels(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchFunnels();
  }, [fetchFunnels]);

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setCreateError('Image too large. Maximum 5MB.');
      return;
    }
    setImageFile(file);
    setImagePreviewUrl(URL.createObjectURL(file));
  };

  const removeImage = () => {
    setImageFile(null);
    if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
    setImagePreviewUrl(null);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = getToken();
    if (!token) return;
    setIsCreating(true);
    setCreateError(null);

    try {
      // Step 1: Create the funnel
      const res = await fetch(`${API_URL}/api/v1/funnels/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          title: form.title,
          audience: form.audience,
          description: form.description,
          cta_text: form.cta_text || 'Register Now',
          video_url: form.video_url || undefined,
        }),
      });
      if (!res.ok) throw new Error('Failed to create funnel');
      let newFunnel: FunnelRow = await res.json();

      // Step 2: Upload image if selected
      if (imageFile) {
        setIsUploadingImage(true);
        const formData = new FormData();
        formData.append('file', imageFile);
        const imgRes = await fetch(`${API_URL}/api/v1/funnels/${newFunnel.id}/set-image`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: formData,
        });
        if (imgRes.ok) {
          const imgData = await imgRes.json();
          newFunnel = { ...newFunnel, hero_image_url: imgData.image_url };
        }
        setIsUploadingImage(false);
      }

      setFunnels((prev) => [newFunnel, ...prev]);
      setShowCreate(false);
      setForm({ title: '', audience: 'buyer', description: '', cta_text: '', video_url: '' });
      removeImage();
      // Show preview modal
      setPreviewFunnel(newFunnel);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create funnel. Please try again.');
    } finally {
      setIsCreating(false);
      setIsUploadingImage(false);
    }
  };

  const handlePublishAndShare = async () => {
    if (!previewFunnel) return;
    const token = getToken();
    if (!token) return;
    setIsPublishing(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/funnels/${previewFunnel.id}/publish`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Failed to publish');
      setFunnels((prev) =>
        prev.map((f) => (f.id === previewFunnel.id ? { ...f, status: 'published' } : f))
      );
      setPreviewFunnel((p) => (p ? { ...p, status: 'published' } : null));
      // Copy link to clipboard
      const url = `${SITE_URL}/f/${previewFunnel.slug}`;
      await navigator.clipboard.writeText(url);
      setPublishSuccess(true);
      setTimeout(() => setPublishSuccess(false), 4000);
    } catch (err) {
      console.error('Publish failed:', err);
    } finally {
      setIsPublishing(false);
    }
  };

  const handleRegenerate = async () => {
    if (!previewFunnel) return;
    const token = getToken();
    if (!token) return;
    setIsCreating(true);
    try {
      // Parse existing content to get original params
      const res = await fetch(`${API_URL}/api/v1/funnels/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          title: previewFunnel.title,
          audience: previewFunnel.audience,
          description: '',
          cta_text: previewFunnel.cta_text || 'Register Now',
          video_url: previewFunnel.video_url || undefined,
        }),
      });
      if (!res.ok) throw new Error('Failed to regenerate');
      const newFunnel: FunnelRow = await res.json();
      setFunnels((prev) => [newFunnel, ...prev]);
      setPreviewFunnel(newFunnel);
    } catch (err) {
      console.error('Regenerate failed:', err);
    } finally {
      setIsCreating(false);
    }
  };

  const handleCopyLink = (funnel: FunnelRow) => {
    navigator.clipboard.writeText(`${SITE_URL}/f/${funnel.slug}`);
    setCopiedId(funnel.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handlePreview = (funnel: FunnelRow) => {
    setPreviewFunnel(funnel);
    setPublishSuccess(false);
  };

  // Build the funnel data structure for the preview components
  const previewFunnelData = previewFunnel
    ? {
        title: previewFunnel.title,
        audience: previewFunnel.audience,
        event_date: null,
        video_url: previewFunnel.video_url,
        hero_image_url: previewFunnel.hero_image_url,
        cta_text: previewFunnel.cta_text,
        content: JSON.parse(previewFunnel.generated_content || '{}'),
      }
    : null;

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-white font-black text-2xl">Funnels</h1>
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="flex items-center gap-2 bg-gold text-dark-surface text-xs font-bold uppercase tracking-widest px-4 py-2.5 hover:bg-gold-hover transition-colors cursor-pointer"
        >
          <Plus size={14} weight="bold" />
          New Funnel
        </button>
      </div>

      {/* Error state */}
      {error && (
        <div className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/20 mb-6">
          <WarningCircle weight="fill" className="w-5 h-5 text-red-400 flex-shrink-0" />
          <div>
            <p className="text-red-400 text-sm font-medium">Failed to load funnels</p>
            <p className="text-white/40 text-xs mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Table */}
      {!error && (
        <div className="overflow-x-auto mb-6">
          <table className="w-full border border-dark-border text-sm">
            <thead>
              <tr className="border-b border-dark-border">
                {['Title', 'Audience', 'Status', 'Registrations', 'Date', 'Actions'].map((col) => (
                  <th
                    key={col}
                    className="text-white/40 text-xs tracking-widest uppercase font-semibold px-4 py-3 text-left"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading
                ? Array.from({ length: 4 }).map((_, i) => (
                    <tr key={i} className="border-b border-dark-border">
                      {Array.from({ length: 6 }).map((__, j) => (
                        <td key={j} className="px-4 py-4">
                          <div className="h-4 bg-dark-border animate-pulse" />
                        </td>
                      ))}
                    </tr>
                  ))
                : funnels.map((funnel) => (
                    <tr
                      key={funnel.id}
                      className="border-b border-dark-border hover:bg-dark-surface/50 transition-colors"
                    >
                      <td className="px-4 py-3 text-white font-medium">{funnel.title}</td>
                      <td className="px-4 py-3 text-white/70 capitalize">{funnel.audience}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block px-2.5 py-1 text-xs font-semibold uppercase tracking-wider ${
                            funnel.status === 'published'
                              ? 'bg-green-500/20 text-green-400'
                              : 'bg-white/10 text-white/40'
                          }`}
                        >
                          {funnel.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-white/70">
                        {funnel.registrations ?? 0}
                      </td>
                      <td className="px-4 py-3 text-white/40 text-xs">
                        {new Date(funnel.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => handlePreview(funnel)}
                            className="text-xs text-white/60 border border-dark-border hover:border-white/30 px-3 py-1.5 transition-colors cursor-pointer flex items-center gap-1"
                          >
                            <Eye size={12} /> Preview
                          </button>
                          {funnel.status === 'published' && (
                            <button
                              onClick={() => handleCopyLink(funnel)}
                              className="text-xs text-gold border border-gold/30 hover:bg-gold/10 px-3 py-1.5 transition-colors cursor-pointer flex items-center gap-1"
                            >
                              <LinkIcon size={12} />
                              {copiedId === funnel.id ? 'Copied!' : 'Share'}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div className="bg-dark-card border border-dark-border p-6 mt-4">
          <h2 className="text-white font-bold text-sm mb-4 uppercase tracking-widest">
            New Funnel
          </h2>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                  Title
                </label>
                <input
                  type="text"
                  required
                  value={form.title}
                  onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                  className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 focus:outline-none focus:border-gold"
                  placeholder="e.g. First-Time Buyer Guide"
                />
              </div>

              <div>
                <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                  Audience
                </label>
                <select
                  value={form.audience}
                  onChange={(e) => setForm((f) => ({ ...f, audience: e.target.value }))}
                  className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 focus:outline-none focus:border-gold cursor-pointer"
                >
                  {AUDIENCE_OPTIONS.map((a) => (
                    <option key={a} value={a} className="bg-dark-surface">
                      {a.charAt(0).toUpperCase() + a.slice(1)}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                Description
              </label>
              <textarea
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                rows={3}
                className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 resize-none focus:outline-none focus:border-gold"
                placeholder="Describe the funnel..."
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                  CTA Text
                </label>
                <input
                  type="text"
                  value={form.cta_text}
                  onChange={(e) => setForm((f) => ({ ...f, cta_text: e.target.value }))}
                  className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 focus:outline-none focus:border-gold"
                  placeholder="e.g. Reserve Your Spot"
                />
              </div>

              <div>
                <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                  Video URL <span className="text-white/20 normal-case tracking-normal">(optional)</span>
                </label>
                <input
                  type="url"
                  value={form.video_url}
                  onChange={(e) => setForm((f) => ({ ...f, video_url: e.target.value }))}
                  className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 focus:outline-none focus:border-gold"
                  placeholder="YouTube, Vimeo, or Loom URL"
                />
              </div>
            </div>

            {/* Image upload */}
            <div>
              <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                Hero Image <span className="text-white/20 normal-case tracking-normal">(optional, max 5MB)</span>
              </label>
              {imagePreviewUrl ? (
                <div className="relative inline-block">
                  <img
                    src={imagePreviewUrl}
                    alt="Preview"
                    className="h-32 object-cover border border-dark-border"
                  />
                  <button
                    type="button"
                    onClick={removeImage}
                    className="absolute -top-2 -right-2 w-6 h-6 bg-red-500 text-white flex items-center justify-center rounded-full cursor-pointer"
                  >
                    <Trash size={12} />
                  </button>
                </div>
              ) : (
                <label className="flex items-center gap-3 border border-dashed border-dark-border hover:border-gold/40 p-4 cursor-pointer transition-colors">
                  <div className="w-10 h-10 flex items-center justify-center border border-dark-border">
                    {imageFile ? <ImageIcon size={20} className="text-gold" /> : <UploadSimple size={20} className="text-white/30" />}
                  </div>
                  <div>
                    <p className="text-white/60 text-sm">
                      {imageFile ? imageFile.name : 'Click to upload or drag and drop'}
                    </p>
                    <p className="text-white/30 text-xs">JPEG, PNG, WebP up to 5MB</p>
                  </div>
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp,image/gif"
                    onChange={handleImageSelect}
                    className="hidden"
                  />
                </label>
              )}
            </div>

            {createError && (
              <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                <WarningCircle weight="fill" className="w-4 h-4 flex-shrink-0" />
                {createError}
              </div>
            )}

            <div className="flex gap-3 justify-end pt-2">
              <button
                type="button"
                onClick={() => {
                  setShowCreate(false);
                  setCreateError(null);
                  removeImage();
                }}
                className="text-xs text-white/40 border border-dark-border hover:border-white/20 px-4 py-2 transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isCreating}
                className="flex items-center gap-2 text-xs bg-gold text-dark-surface font-bold uppercase tracking-widest px-4 py-2 hover:bg-gold-hover transition-colors disabled:opacity-60 cursor-pointer"
              >
                {isCreating ? (
                  <>
                    <CircleNotch size={14} className="animate-spin" />
                    {isUploadingImage ? 'Uploading Image...' : 'Generating with AI...'}
                  </>
                ) : (
                  'Create Funnel'
                )}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Full-screen Preview Modal */}
      {previewFunnel && previewFunnelData && (
        <div className="fixed inset-0 z-50 bg-[#0a0a0a] overflow-y-auto">
          {/* Top control bar */}
          <div className="sticky top-0 z-60 bg-[#111111] border-b border-dark-border px-6 py-3 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <h3 className="text-white font-bold text-sm truncate max-w-[200px] md:max-w-none">
                {previewFunnel.title}
              </h3>
              <span
                className={`inline-block px-2.5 py-1 text-xs font-semibold uppercase tracking-wider ${
                  previewFunnel.status === 'published'
                    ? 'bg-green-500/20 text-green-400'
                    : 'bg-white/10 text-white/40'
                }`}
              >
                {previewFunnel.status}
              </span>
            </div>
            <div className="flex items-center gap-3">
              {previewFunnel.status === 'draft' && (
                <>
                  <button
                    onClick={handleRegenerate}
                    disabled={isCreating}
                    className="flex items-center gap-1.5 text-xs text-white/60 border border-dark-border hover:border-white/30 px-3 py-2 transition-colors cursor-pointer disabled:opacity-40"
                  >
                    {isCreating ? <CircleNotch size={12} className="animate-spin" /> : <ArrowsClockwise size={12} />}
                    Regenerate
                  </button>
                  <button
                    onClick={handlePublishAndShare}
                    disabled={isPublishing}
                    className="flex items-center gap-1.5 text-xs bg-gold text-dark-surface font-bold uppercase tracking-widest px-4 py-2 hover:bg-gold-hover transition-colors cursor-pointer disabled:opacity-60"
                  >
                    {isPublishing ? (
                      <CircleNotch size={12} className="animate-spin" />
                    ) : (
                      <CheckCircle size={14} weight="bold" />
                    )}
                    Publish & Share
                  </button>
                </>
              )}
              {previewFunnel.status === 'published' && (
                <button
                  onClick={() => handleCopyLink(previewFunnel)}
                  className="flex items-center gap-1.5 text-xs bg-gold text-dark-surface font-bold uppercase tracking-widest px-4 py-2 hover:bg-gold-hover transition-colors cursor-pointer"
                >
                  <LinkIcon size={14} />
                  {copiedId === previewFunnel.id ? 'Link Copied!' : 'Copy Share Link'}
                </button>
              )}
              <button
                onClick={() => {
                  setPreviewFunnel(null);
                  setPublishSuccess(false);
                }}
                className="text-white/40 hover:text-white p-2 transition-colors cursor-pointer"
              >
                <X size={20} />
              </button>
            </div>
          </div>

          {/* Publish success toast */}
          {publishSuccess && (
            <div className="sticky top-[57px] z-60 bg-green-500/10 border-b border-green-500/20 px-6 py-3 flex items-center gap-3">
              <CheckCircle size={18} weight="fill" className="text-green-400" />
              <p className="text-green-400 text-sm font-medium">
                Published! Link copied to clipboard: {SITE_URL}/f/{previewFunnel.slug}
              </p>
            </div>
          )}

          {/* Rendered funnel preview */}
          <div>
            <FunnelHero funnel={previewFunnelData} />
            <FunnelRegistration
              slug={previewFunnel.slug}
              ctaText={previewFunnel.cta_text}
              ctaHeadline={previewFunnelData.content.cta_headline}
              ctaSubtext={previewFunnelData.content.cta_subtext}
              audience={previewFunnel.audience}
            />
          </div>
        </div>
      )}
    </div>
  );
}
