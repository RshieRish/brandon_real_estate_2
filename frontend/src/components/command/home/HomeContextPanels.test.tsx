import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { buildCommandHomeModel } from '@/lib/command/home';
import { completeHomeInput } from '@/test/fixtures/commandHome';
import { HomeContextPanels } from './HomeContextPanels';

describe('HomeContextPanels', () => {
  it('renders verified, yearless, and sentinel celebrations with canonical contact links and no fabricated year', () => {
    const model = buildCommandHomeModel({
      ...completeHomeInput,
      celebrations: {
        birthdays: [
          {
            contactId: 11,
            displayName: 'Verified Birthday',
            kind: 'birthday',
            month: 8,
            day: 11,
            year: 1984,
            yearQuality: 'verified',
            origin: 'internal_crm',
          },
          {
            contactId: 12,
            displayName: 'Yearless Birthday',
            kind: 'birthday',
            month: 8,
            day: 12,
            year: null,
            yearQuality: 'yearless',
            origin: 'recovered',
          },
        ],
        anniversaries: [{
          contactId: 13,
          displayName: 'Sentinel Anniversary',
          kind: 'anniversary',
          month: 8,
          day: 13,
          year: null,
          yearQuality: 'sentinel',
          origin: 'recovered',
        }],
      },
    }, new Date('2026-08-13T12:00:00.000Z'));

    const { container } = render(<HomeContextPanels model={model} />);

    expect(screen.getByRole('link', { name: 'Verified Birthday' })).toHaveAttribute(
      'href',
      '/admin/command/contacts/11',
    );
    expect(screen.getByRole('link', { name: 'Yearless Birthday' })).toHaveAttribute(
      'href',
      '/admin/command/contacts/12',
    );
    expect(screen.getByRole('link', { name: 'Sentinel Anniversary' })).toHaveAttribute(
      'href',
      '/admin/command/contacts/13',
    );
    expect(screen.getByText('Birthday · 8/11')).toBeInTheDocument();
    expect(screen.getByText('Birthday · 8/12')).toBeInTheDocument();
    expect(screen.getByText('Anniversary · 8/13')).toBeInTheDocument();
    expect(container).not.toHaveTextContent('1900');
    expect(container).not.toHaveTextContent('2026');
  });
});
