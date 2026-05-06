'use client';
import { useState } from 'react';
import { CheckCircle, CircleNotch } from '@phosphor-icons/react';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface Props {
  hasUnpublishedChanges: boolean;
  publishedAt: string | null;
  isPublished: boolean;
  onPublished: () => void;
}

export default function StatusBar({ hasUnpublishedChanges, publishedAt, isPublished, onPublished }: Props) {
  const [publishing, setPublishing] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const status = !isPublished
    ? { label: 'Not yet published', className: 'bg-white/10 text-white/40' }
    : hasUnpublishedChanges
    ? { label: 'Draft changes pending', className: 'bg-gold/20 text-gold' }
    : { label: 'Live', className: 'bg-green-500/20 text-green-400' };

  const publish = async () => {
    setPublishing(true);
    try {
      const token = localStorage.getItem('admin_token');
      const res = await fetch(`${API_URL}/api/v1/link-pack/publish`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Publish failed');
      onPublished();
      setConfirm(false);
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="sticky top-0 z-30 bg-[#111111] border-b border-dark-border -mx-8 px-8 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className={`inline-block px-2.5 py-1 text-xs font-semibold uppercase tracking-wider ${status.className}`}>
          {status.label}
        </span>
        {publishedAt && (
          <span className="text-white/40 text-xs">
            Last published {new Date(publishedAt).toLocaleString()}
          </span>
        )}
      </div>
      <div className="flex items-center gap-3">
        <a
          href="/links?preview=1"
          target="_blank"
          rel="noreferrer"
          className="text-xs text-white/60 border border-dark-border hover:border-white/30 px-4 py-2 cursor-pointer"
        >
          Preview
        </a>
        <button
          onClick={() => setConfirm(true)}
          disabled={!hasUnpublishedChanges}
          className="flex items-center gap-1.5 text-xs bg-gold text-dark-surface font-bold uppercase tracking-widest px-4 py-2 hover:bg-gold-hover transition-colors cursor-pointer disabled:opacity-40"
        >
          <CheckCircle size={14} weight="bold" /> Publish changes
        </button>
      </div>

      {confirm && (
        <div className="fixed inset-0 z-50 bg-black/70 grid place-items-center">
          <div className="bg-dark-card border border-dark-border p-6 max-w-md w-[90vw]">
            <h3 className="text-white font-bold text-sm uppercase tracking-widest mb-3">Publish?</h3>
            <p className="text-white/60 text-sm mb-5">
              This will replace the live link pack at <code>soldwithsweeney.com/links</code>.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setConfirm(false)}
                className="text-xs text-white/40 border border-dark-border px-4 py-2 cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={publish}
                disabled={publishing}
                className="flex items-center gap-1.5 text-xs bg-gold text-dark-surface font-bold uppercase tracking-widest px-4 py-2 cursor-pointer disabled:opacity-60"
              >
                {publishing ? <CircleNotch size={12} className="animate-spin" /> : <CheckCircle size={12} weight="bold" />}
                Confirm publish
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
