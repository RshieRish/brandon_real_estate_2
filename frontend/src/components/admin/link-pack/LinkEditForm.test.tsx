import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LinkPackItem } from '@/lib/link-pack/types';
import LinkEditForm from './LinkEditForm';

const listing: LinkPackItem = {
  id: 28, kind: 'thumbnail', title: 'Dracut Expanded Ranch',
  url: 'https://example.com/listing', thumbnail_url: null,
  gated_filename: null, gate_modal_headline: null, gate_modal_subtext: null,
  animation: 'none', is_active: true, children: [],
};

function photoInput(container: HTMLElement) {
  return container.querySelector<HTMLInputElement>('input[type="file"]')!;
}

describe('LinkEditForm photo saves', () => {
  beforeEach(() => {
    localStorage.setItem('admin_token', 'test-token');
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = vi.fn(() => 'blob:listing-preview');
      static revokeObjectURL = vi.fn();
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('keeps a rejected photo selected, shows the API error, and allows retry', async () => {
    let rejectUpload = true;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/thumbnail') && rejectUpload) {
        return Response.json({ detail: 'Image too large. Maximum 5MB.' }, { status: 400 });
      }
      return Response.json({ ok: true });
    }));
    const saved = vi.fn();
    const { container } = render(<LinkEditForm existing={listing} onCancel={vi.fn()} onSaved={saved} />);
    const file = new File(['photo'], 'listing.jpg', { type: 'image/jpeg' });
    fireEvent.change(photoInput(container), { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText(/Image too large/)).toBeVisible();
    expect(saved).not.toHaveBeenCalled();
    expect(photoInput(container).files?.[0]).toBe(file);

    rejectUpload = false;
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  });

  it('keeps the editor open when the upload error is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/thumbnail')
      ? new Response('Bad Gateway', { status: 502 })
      : Response.json({ ok: true })));
    const saved = vi.fn();
    const { container } = render(<LinkEditForm existing={listing} onCancel={vi.fn()} onSaved={saved} />);
    fireEvent.change(photoInput(container), {
      target: { files: [new File(['photo'], 'listing.png', { type: 'image/png' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/photo upload failed/i);
    expect(saved).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
  });

  it('reuses a newly created listing when retrying its failed photo upload', async () => {
    let rejectUpload = true;
    let created = 0;
    const uploadedIds: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit) => {
      if (url.endsWith('/items') && options.method === 'POST') {
        created += 1;
        return Response.json({ id: 29 });
      }
      if (url.endsWith('/thumbnail')) {
        uploadedIds.push(url);
        return rejectUpload
          ? Response.json({ detail: 'Photo upload failed.' }, { status: 500 })
          : Response.json({ ok: true });
      }
      return Response.json({ ok: true });
    }));
    const saved = vi.fn();
    const { container } = render(<LinkEditForm onCancel={vi.fn()} onSaved={saved} />);
    fireEvent.change(container.querySelector('input')!, { target: { value: 'New listing' } });
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'thumbnail' } });
    fireEvent.change(photoInput(container), {
      target: { files: [new File(['photo'], 'listing.jpg', { type: 'image/jpeg' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add link' }));
    expect(await screen.findByText('Photo upload failed.')).toBeVisible();
    expect(saved).not.toHaveBeenCalled();

    rejectUpload = false;
    fireEvent.click(screen.getByRole('button', { name: /save|add link/i }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(created).toBe(1);
    expect(uploadedIds).toHaveLength(2);
    expect(uploadedIds.every(url => url.endsWith('/items/29/thumbnail'))).toBe(true);
  });

  it('shows the stored photo when an existing listing is reopened', () => {
    render(<LinkEditForm
      existing={{ ...listing, thumbnail_url: '/api/v1/link-pack/images/items/28/thumbnail?v=photo1' }}
      onCancel={vi.fn()} onSaved={vi.fn()}
    />);
    expect(screen.getByRole('img', { name: /dracut expanded ranch/i })).toHaveAttribute(
      'src', expect.stringContaining('/images/items/28/thumbnail?v=photo1'),
    );
    expect(screen.getByText(/saved photo/i)).toBeVisible();
  });

  it('does not close until the thumbnail upload has finished', async () => {
    let finishUpload!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/thumbnail')
      ? new Promise<Response>(resolve => { finishUpload = resolve; })
      : Response.json({ ok: true })));
    const saved = vi.fn();
    const { container } = render(<LinkEditForm existing={listing} onCancel={vi.fn()} onSaved={saved} />);
    fireEvent.change(photoInput(container), {
      target: { files: [new File(['photo'], 'listing.jpg', { type: 'image/jpeg' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(finishUpload).toBeTypeOf('function'));
    expect(saved).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    finishUpload(Response.json({ ok: true }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  });

  it('keeps a rejected gated PDF open with its upload error', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/gated-file')
      ? Response.json({ detail: 'PDF too large. Maximum 10MB.' }, { status: 400 })
      : Response.json({ ok: true })));
    const saved = vi.fn();
    const { container } = render(<LinkEditForm existing={{ ...listing, kind: 'email_gate' }} onCancel={vi.fn()} onSaved={saved} />);
    fireEvent.change(photoInput(container), {
      target: { files: [new File(['pdf'], 'guide.pdf', { type: 'application/pdf' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText(/PDF too large/)).toBeVisible();
    expect(saved).not.toHaveBeenCalled();
  });
});
