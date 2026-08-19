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

  it('ships explicit immutable source identities in the downloadable template', () => {
    expect(archiveTemplate.source_id).toBe('REPLACE_WITH_STABLE_UNIQUE_ARCHIVE_SOURCE_ID');
    expect(archiveTemplate.tasks?.[0]?.source_row_id).toBe('REPLACE_WITH_IMMUTABLE_SOURCE_ROW_ID');
    expect(validateArchiveBundle(archiveTemplate)).toBe(archiveTemplate);
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
});
