import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { decodeContactTimelinePage } from '@/lib/command/contacts';
import { ContactTimelineTab } from './ContactTimelineTab';
import { ContactObservedMap } from './ContactObservedMap';

const event = {
  key: 'recovered:1', origin: 'recovered' as const, kind: 'note', title: 'Lake open house',
  body: 'Requested a follow-up.', outcome: 'Created', occurred_at: null,
  source_record_id: 12, entity_type: 'contact_timeline_event', entity_id: 1,
  captured_date: '2025-04-28', captured_time: '14:16:00',
};

describe('captured contact presentation', () => {
  it('decodes source-precision dates without assigning a timezone', () => {
    const decoded = decodeContactTimelinePage({ rows: [event], next_cursor: null, has_more: false });
    expect(decoded.rows[0]).toEqual(event);
  });

  it('displays a literal captured day and clock time', () => {
    render(<ContactTimelineTab rows={[event]} evidence={null} evidenceStatus="unavailable"
      loading={false} error={false} hasMore={false} loadingMore={false} loadMoreError={false}
      onRetry={vi.fn()} onRetryEvidence={vi.fn()} onLoadMore={vi.fn()} />);
    expect(screen.getByText('April 28, 2025 · 2:16 PM (as captured)')).toBeVisible();
    expect(screen.queryByText('Time was not captured')).not.toBeInTheDocument();
  });

  it('shows the recovered address and makes review provenance clear', () => {
    render(<ContactObservedMap addresses={[{ id: 1, address_type: 'mailing',
      formatted: '12 Example Ln.\nUnit 7\nDracut, MA, 01826', latitude: null,
      longitude: null, source_record_id: 12 }]} />);
    expect(screen.getByText(/12 Example Ln/)).toBeVisible();
    expect(screen.getByText('Recovered from Command. Confirm this is current before mailing.')).toBeVisible();
  });
});
