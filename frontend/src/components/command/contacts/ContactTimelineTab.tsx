import {
  contactSectionCoverage,
  isTechnicalContactTimelineEntry,
  type ContactEvidence,
  type ContactEvidenceStatus,
  type ContactTimelineEntry,
} from '@/lib/command/contacts';
import { CommandEvidencePanel } from '../ui/CommandEvidencePanel';
import { CommandStatePanel } from '../ui/CommandStatePanel';
import { ContactExpandableValue } from './ContactExpandableValue';

const TIMELINE_ORIGIN_LABELS: Readonly<Record<ContactTimelineEntry['origin'], string>> = {
  recovered: 'Recovered Command',
  internal_crm: 'SWS internal',
  legacy_lead: 'Legacy lead',
  booking: 'SWS booking',
};

function timelineKindLabel(kind: string): string {
  return kind.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function timelineDateLabel(row: ContactTimelineEntry): string {
  if (row.occurred_at) return new Date(row.occurred_at).toLocaleString();
  const day = row.captured_date ? new Intl.DateTimeFormat('en-US', {
    year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC',
  }).format(new Date(`${row.captured_date}T12:00:00Z`)) : null;
  const parts = row.captured_time?.split(':');
  const hour = parts ? Number(parts[0]) : null;
  const clock = hour !== null ? `${hour % 12 || 12}:${parts?.[1]} ${hour < 12 ? 'AM' : 'PM'}` : null;
  if (day || clock) return `${[day, clock].filter(Boolean).join(' · ')} (as captured)`;
  return 'Time was not captured';
}

function TimelineCoverageState({
  evidence,
  evidenceStatus,
  filteredCaptureCount,
  onRetryEvidence,
}: Readonly<{
  evidence: ContactEvidence | null;
  evidenceStatus: ContactEvidenceStatus;
  filteredCaptureCount: number;
  onRetryEvidence: () => void;
}>) {
  if (evidenceStatus === 'loading') {
    return <CommandStatePanel kind="loading" title="Checking recovered source coverage" message="Reading this contact's captured Command timeline." />;
  }
  if (evidenceStatus === 'unavailable' || evidence === null) {
    return <CommandStatePanel kind="error" title="Recovered source coverage is unavailable" message="The captured Command timeline could not be verified. This is not an empty state." actionLabel="Retry source coverage" onAction={onRetryEvidence} />;
  }
  const coverage = contactSectionCoverage(evidence, 'timeline');
  if (coverage.state === 'unreconciled') {
    return <CommandStatePanel kind="evidence_only" title="Recovered Command timeline has not been restored" message="This workspace has no reconciled contact capture positions yet. Protected archive evidence may still exist, so this is not an empty timeline." />;
  }
  if (coverage.state === 'not_linked') {
    return <CommandStatePanel kind="evidence_only" title="No recovered Command record is linked to this contact" message="The recovered archive is available globally, but this contact has no matched capture position. This is not a verified empty timeline." />;
  }
  if (coverage.state === 'verified_empty') {
    return <CommandStatePanel kind="empty" title="No timeline events" message="Every matching capture position records a complete empty timeline." />;
  }
  if (coverage.state === 'captured') {
    if (filteredCaptureCount > 0 && filteredCaptureCount === coverage.recovered_count) {
      return <CommandStatePanel kind="empty" title="No activity entries in this capture" message="This capture contains profile information and page controls. They are kept in Source Evidence and excluded from the activity timeline." />;
    }
    return <CommandStatePanel kind="partial_capture" title="Recovered timeline events are not available" message={`Source evidence records ${coverage.recovered_count} timeline event${coverage.recovered_count === 1 ? '' : 's'}, but the merged timeline returned none.`} />;
  }
  return <CommandStatePanel kind="partial_capture" title="Timeline was not fully captured" message="The source evidence does not prove that this timeline is empty." />;
}

export function ContactTimelineTab({
  rows,
  filteredCaptureCount = 0,
  evidence,
  evidenceStatus,
  loading,
  error,
  hasMore,
  loadingMore,
  loadMoreError,
  onRetry,
  onRetryEvidence,
  onLoadMore,
}: Readonly<{
  rows: readonly ContactTimelineEntry[];
  filteredCaptureCount?: number;
  evidence: ContactEvidence | null;
  evidenceStatus: ContactEvidenceStatus;
  loading: boolean;
  error: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  loadMoreError: boolean;
  onRetry: () => void;
  onRetryEvidence: () => void;
  onLoadMore: () => void;
}>) {
  const visibleRows = rows.filter((row) => !isTechnicalContactTimelineEntry(row));
  const cells = evidence?.section_matrix.filter((cell) => (
    cell.section === 'timeline'
    && evidence.capture_positions.some((position) => (
      position.capture_position_id === cell.capture_position_id
    ))
  )) ?? [];

  return (
    <section className="command-contact-timeline" aria-label="Contact timeline">
      {loading ? <CommandStatePanel kind="loading" title="Loading timeline" message="Collecting the merged contact history." /> : null}
      {!loading && error && visibleRows.length === 0 ? <CommandStatePanel kind="error" title="Timeline is unavailable" message="The merged contact history could not be read." actionLabel="Retry" onAction={onRetry} /> : null}
      {!loading && !error && visibleRows.length === 0 ? (
        <TimelineCoverageState evidence={evidence} evidenceStatus={evidenceStatus} filteredCaptureCount={filteredCaptureCount} onRetryEvidence={onRetryEvidence} />
      ) : null}
      {!loading && visibleRows.map((row) => (
        <article key={row.key}>
          <div className="command-contact-timeline-marker" aria-hidden="true" />
          <div>
            <span>{TIMELINE_ORIGIN_LABELS[row.origin]} · {timelineKindLabel(row.kind)}</span>
            <ContactExpandableValue value={row.title} limit={180} element="h3" label="activity" />
            {row.body ? <ContactExpandableValue value={row.body} limit={520} element="p" label="activity details" /> : null}
            {row.outcome ? <ContactExpandableValue value={row.outcome} limit={260} element="strong" label="activity outcome" /> : null}
            <time dateTime={row.occurred_at ?? row.captured_date ?? undefined}
              title={!row.occurred_at && (row.captured_date || row.captured_time) ? 'Source date and local clock time. The capture did not specify a timezone.' : undefined}>
              {timelineDateLabel(row)}
            </time>
          </div>
        </article>
      ))}
      {cells.map((cell) => (
        <CommandEvidencePanel
          key={`${cell.capture_position_id}-${cell.source_record_id}-${cell.section}`}
          evidenceLevel="rendered_occurrence"
          captureQuality={cell.capture_quality}
          displayLabel={`Capture position ${
            evidence?.capture_positions.find((position) => (
              position.capture_position_id === cell.capture_position_id
            ))?.capture_ordinal ?? 'unknown'
          } · timeline`}
          renderedCount={cell.row_count}
          explanation={cell.limitation_codes.length > 0 ? cell.limitation_codes.join(', ') : undefined}
        />
      ))}
      {!loading && loadMoreError ? <p role="alert">More timeline events could not be loaded.</p> : null}
      {!loading && hasMore ? <button type="button" className="command-secondary-button command-print-hidden" disabled={loadingMore} onClick={onLoadMore}>{loadingMore ? 'Loading…' : loadMoreError ? 'Retry more timeline' : 'Load more timeline'}</button> : null}
    </section>
  );
}
