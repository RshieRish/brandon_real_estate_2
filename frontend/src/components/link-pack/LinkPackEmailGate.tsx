'use client';
import { useState, useRef, useEffect } from 'react';
import type { LinkPackItem } from '@/lib/link-pack/types';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export default function LinkPackEmailGate({ item }: { item: LinkPackItem }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (open) dialogRef.current?.showModal();
    else dialogRef.current?.close();
  }, [open]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/link-pack/items/${item.id}/email-gate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, phone: phone || undefined }),
      });
      if (!res.ok) throw new Error('Failed');
      const { file_url, filename } = await res.json();
      const a = document.createElement('a');
      a.href = `${API_URL}${file_url}`;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setOpen(false);
      setToast('Sent! Check your inbox shortly.');
      setTimeout(() => setToast(null), 4000);
    } catch {
      setToast('Something went wrong. Please try again.');
      setTimeout(() => setToast(null), 4000);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`lp-btn lp-anim-${item.animation}`}
        style={{
          width: '100%',
          background: 'var(--lp-btn-bg)',
          color: 'var(--lp-btn-text)',
          borderRadius: 'var(--lp-btn-radius)',
          padding: '14px 24px',
          fontSize: 14,
          fontWeight: 700,
          boxShadow: '0 6px 0 0 var(--lp-btn-shadow)',
          border: '2px solid var(--lp-btn-shadow)',
          cursor: 'pointer',
        }}
      >
        {item.title}
      </button>

      <dialog
        ref={dialogRef}
        onClose={() => setOpen(false)}
        style={{
          padding: 0,
          border: 'none',
          background: 'transparent',
          maxWidth: 420,
          width: '90vw',
        }}
      >
        <form
          onSubmit={submit}
          style={{
            background: '#fff',
            borderRadius: 16,
            padding: 24,
            color: '#1E2330',
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}
        >
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
            {item.gate_modal_headline ?? 'Get your free guide'}
          </h3>
          {item.gate_modal_subtext && (
            <p style={{ margin: 0, fontSize: 14, color: '#555' }}>{item.gate_modal_subtext}</p>
          )}
          <input
            required
            placeholder="Your name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ padding: 10, borderRadius: 8, border: '1px solid #ddd' }}
          />
          <input
            required
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{ padding: 10, borderRadius: 8, border: '1px solid #ddd' }}
          />
          <input
            placeholder="Phone (optional)"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            style={{ padding: 10, borderRadius: 8, border: '1px solid #ddd' }}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            <button
              type="button"
              onClick={() => setOpen(false)}
              style={{ flex: 1, padding: 10, borderRadius: 8, border: '1px solid #ddd', background: '#fff', cursor: 'pointer' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              style={{ flex: 1, padding: 10, borderRadius: 8, border: 'none', background: '#1E2330', color: '#fff', cursor: 'pointer' }}
            >
              {submitting ? 'Sending…' : (item.title || 'Send me the guide')}
            </button>
          </div>
        </form>
      </dialog>

      {toast && (
        <div
          role="status"
          style={{
            position: 'fixed',
            bottom: 24,
            left: '50%',
            transform: 'translateX(-50%)',
            background: '#1E2330',
            color: '#fff',
            padding: '10px 16px',
            borderRadius: 8,
            zIndex: 100,
          }}
        >
          {toast}
        </div>
      )}
    </>
  );
}
