'use client';

import { useEffect, useState } from 'react';
import { WarningCircle, TextT } from '@phosphor-icons/react';

interface ContentBlock {
  id: number;
  block_id: string;
  content: string;
  content_type: string;
  page: string | null;
  updated_at: string;
}

const formatLabel = (id: string) => {
  return id
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export default function ContentPage() {
  const [blocks, setBlocks] = useState<ContentBlock[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState('');

  useEffect(() => {
    const fetchBlocks = async () => {
      const token = localStorage.getItem('admin_token');
      if (!token) {
        setError('Not authenticated. Please log in.');
        setIsLoading(false);
        return;
      }
      try {
        const res = await fetch(`${API_URL}/api/v1/content/`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error('Failed to load content blocks');
        const data = await res.json();
        setBlocks(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        setIsLoading(false);
      }
    };
    fetchBlocks();
  }, []);

  const handleEdit = (block: ContentBlock) => {
    setEditingId(block.id);
    setEditValue(block.content);
  };

  const handleCancel = () => {
    setEditingId(null);
    setEditValue('');
  };

  const handleSave = async (block: ContentBlock) => {
    const token = localStorage.getItem('admin_token');
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/api/v1/content/${block.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ content: editValue }),
      });
      if (!res.ok) throw new Error('Save failed');
      const updated: ContentBlock = await res.json();
      setBlocks((prev) => prev.map((b) => (b.id === block.id ? updated : b)));
      setEditingId(null);
      setEditValue('');
    } catch (err) {
      console.error('Failed to save:', err);
    }
  };

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-white font-black text-2xl">Content Blocks</h1>
        <p className="text-white/40 text-sm mt-1">Edit website copy and text content</p>
      </div>

      {/* Error state */}
      {error && (
        <div className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/20 rounded mb-6">
          <WarningCircle weight="fill" className="w-5 h-5 text-red-400 flex-shrink-0" />
          <div>
            <p className="text-red-400 text-sm font-medium">Failed to load content</p>
            <p className="text-white/40 text-xs mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && blocks.length === 0 && (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <TextT weight="fill" className="w-10 h-10 text-white/20 mb-4" />
          <p className="text-white/40 text-sm">No content blocks yet.</p>
        </div>
      )}

      {/* Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {isLoading
          ? Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="bg-dark-card border border-dark-border p-6 rounded animate-pulse"
              >
                <div className="h-3 w-24 bg-dark-border rounded mb-3" />
                <div className="h-4 w-full bg-dark-border rounded mb-2" />
                <div className="h-4 w-3/4 bg-dark-border rounded mb-4" />
                <div className="h-8 w-16 bg-dark-border rounded self-end" />
              </div>
            ))
          : blocks.map((block) => (
              <div
                key={block.id}
                className="bg-dark-card border border-dark-border p-6 rounded flex flex-col gap-3"
              >
                {/* Eyebrow */}
                <span className="text-xs tracking-widest uppercase text-gold font-semibold">
                  {formatLabel(block.block_id)}
                </span>

                {editingId === block.id ? (
                  <>
                    <textarea
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      className="w-full bg-dark-surface border border-dark-border text-white/80 text-sm px-3 py-2 rounded resize-none min-h-[80px] focus:outline-none focus:border-gold"
                    />
                    <div className="flex gap-2 justify-end">
                      <button
                        onClick={handleCancel}
                        className="text-xs text-white/40 border border-dark-border hover:border-white/20 px-3 py-1.5 rounded transition-colors cursor-pointer"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => handleSave(block)}
                        className="text-xs text-gold border border-gold/30 hover:bg-gold/10 px-3 py-1.5 rounded transition-colors cursor-pointer"
                      >
                        Save
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="text-white/70 text-sm flex-1">{block.content}</p>
                    <div className="flex justify-end">
                      <button
                        onClick={() => handleEdit(block)}
                        className="text-xs text-white/40 border border-dark-border hover:border-gold/30 hover:text-gold px-3 py-1.5 rounded transition-colors cursor-pointer"
                      >
                        Edit
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
      </div>
    </div>
  );
}
