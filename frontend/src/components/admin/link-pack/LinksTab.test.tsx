import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { LinkPackItem } from '@/lib/link-pack/types';
import LinksTab from './LinksTab';

const listing: LinkPackItem = {
  id: 28, kind: 'thumbnail', title: 'Dracut Expanded Ranch',
  url: 'https://example.com/listing', thumbnail_url: null,
  gated_filename: null, gate_modal_headline: null, gate_modal_subtext: null,
  animation: 'none', is_active: true, children: [],
};

describe('LinksTab draft refresh', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('uses refreshed listing details even when the number of links stays the same', () => {
    const onChanged = vi.fn();
    const { rerender } = render(<LinksTab items={[listing]} onChanged={onChanged} />);
    expect(screen.getByText('Dracut Expanded Ranch')).toBeVisible();

    rerender(<LinksTab items={[{
      ...listing, title: 'Updated Dracut listing',
      thumbnail_url: '/api/v1/link-pack/images/items/28/thumbnail?v=new',
    }]} onChanged={onChanged} />);

    expect(screen.getByText('Updated Dracut listing')).toBeVisible();
    expect(screen.queryByText('Dracut Expanded Ranch')).not.toBeInTheDocument();
  });

  it.each([false, true])('refreshes a partially saved draft on cancel (inside group: %s)', async (inGroup) => {
    localStorage.setItem('admin_token', 'test-token');
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = vi.fn(() => 'blob:listing-preview');
      static revokeObjectURL = vi.fn();
    });
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/thumbnail')
      ? Response.json({ detail: 'Photo upload failed.' }, { status: 400 })
      : Response.json({ id: 29 })));
    const onChanged = vi.fn();
    const group: LinkPackItem = { ...listing, id: 10, title: 'Available Homes', kind: 'group', children: [listing] };
    const { container, rerender } = render(<LinksTab items={inGroup ? [group] : [listing]} onChanged={onChanged} />);
    if (inGroup) fireEvent.click(screen.getByRole('button', { name: 'Expand Available Homes' }));
    fireEvent.click(screen.getByRole('button', { name: inGroup ? 'Add child' : 'Add link' }));
    fireEvent.change(container.querySelector('input')!, { target: { value: 'New listing' } });
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'thumbnail' } });
    fireEvent.change(screen.getByLabelText('Thumbnail image'), {
      target: { files: [new File(['photo'], 'listing.png', { type: 'image/png' })] },
    });
    fireEvent.click(screen.getAllByRole('button', { name: 'Add link' })[1]);
    expect(await screen.findByRole('alert')).toHaveTextContent('Photo upload failed.');
    expect(onChanged).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onChanged).toHaveBeenCalledOnce();

    const refreshed = [listing, { ...listing, id: 29, title: 'New listing' }];
    rerender(<LinksTab items={inGroup ? [{ ...group, children: refreshed }] : refreshed} onChanged={onChanged} />);
    expect(screen.getByText('New listing')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
  });
});
