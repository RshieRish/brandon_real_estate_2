// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const importArchiveBundle = vi.hoisted(() => vi.fn());

vi.mock('@/lib/command/api', () => ({
  commandApi: {
    importArchiveBundle,
    importContacts: vi.fn(),
  },
}));

import ImportContactsPage, {
  archiveTemplate,
  validateArchiveBundle,
} from './page';


describe('Command archive import identities', () => {
  beforeEach(() => importArchiveBundle.mockReset());

  it('ships intentionally blank identities that must be replaced', () => {
    expect(archiveTemplate.source_id).toBe('');
    expect(archiveTemplate.tasks?.[0]?.source_row_id).toBe('');
    expect(() => validateArchiveBundle(archiveTemplate))
      .toThrow('Task archive source_id must be a non-empty string');
  });

  it('accepts explicit stable archive and row identities', () => {
    const bundle = {
      source_id: 'command-export-2026-08-18',
      tasks: [{ source_row_id: 'task-0001', title: 'Call Avery' }],
    };
    expect(validateArchiveBundle(bundle)).toBe(bundle);
  });

  it('explains that unrelated archives need different stable source identities', () => {
    render(<ImportContactsPage />);
    expect(screen.getByText(/Use one stable, unique source_id for each immutable archive source/))
      .toBeInTheDocument();
  });

  it('rejects task bundles without a source identity before submission', () => {
    expect(() => validateArchiveBundle({ tasks: [{ source_row_id: 'row-1', title: 'Call' }] }))
      .toThrow('Task archive source_id must be a non-empty string');
  });

  it('rejects task rows without a stable row identity before submission', () => {
    expect(() => validateArchiveBundle({ source_id: 'export-1', tasks: [{ title: 'Call' }] as never }))
      .toThrow('Task 1 source_row_id must be a non-empty string');
  });

  it('shows a clear file error and never enables submission for missing identities', async () => {
    const { container } = render(<ImportContactsPage />);
    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    const file = {
      name: 'archive.json',
      text: async () => JSON.stringify({ tasks: [{ title: 'Call' }] }),
    };
    fireEvent.change(input!, { target: { files: [file] } });

    expect(await screen.findByRole('alert')).toHaveTextContent('Task archive source_id must be a non-empty string');
    await waitFor(() => expect(importArchiveBundle).not.toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: 'Import archive' })).not.toBeInTheDocument();
  });

  it('shows an archive conflict message returned by the client', async () => {
    importArchiveBundle.mockRejectedValueOnce(
      new Error('Archive task identity was already used with different task data or authority'),
    );
    const { container } = render(<ImportContactsPage />);
    const input = container.querySelector('input[type="file"]');
    const file = {
      name: 'archive.json',
      text: async () => JSON.stringify({
        source_id: 'archive-1',
        tasks: [{ source_row_id: 'row-1', title: 'Call' }],
      }),
    };
    fireEvent.change(input!, { target: { files: [file] } });
    fireEvent.click(await screen.findByRole('button', { name: 'Import archive' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Archive task identity was already used with different task data or authority',
    );
  });
});
