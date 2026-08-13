import type { ContactEvidence, ContactTimelineEntry } from '@/lib/command/contacts';
import { CommandEvidencePanel } from '../ui/CommandEvidencePanel';
import { CommandStatePanel } from '../ui/CommandStatePanel';

export function ContactTimelineTab({
  rows,
  evidence,
  loading,
  error,
  hasMore,
  loadingMore,
  loadMoreError,
  onRetry,
  onLoadMore,
}: Readonly<{
  rows: readonly ContactTimelineEntry[];
  evidence: ContactEvidence | null;
  loading: boolean;
  error: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  loadMoreError: boolean;
  onRetry: () => void;
  onLoadMore: () => void;
}>) {
  const cells = evidence?.section_matrix.filter((cell) => (
    cell.section === 'timeline'
    && evidence.capture_positions.some((position) => (
      position.capture_position_id === cell.capture_position_id
    ))
  )) ?? [];
  const hasCompleteCoverage = (evidence?.capture_positions.length ?? 0) > 0
    && cells.length === evidence?.capture_positions.length
    && evidence?.capture_positions.every((position) => cells.filter((cell) => (
      cell.capture_position_id === position.capture_position_id
    )).length === 1);
  const verifiedEmpty = hasCompleteCoverage && cells.every((cell) => (
    cell.capture_quality === 'complete' && cell.is_empty && cell.row_count === 0
  ));
  return (
    <section className="command-contact-timeline" aria-label="Contact timeline">
      {loading ? <CommandStatePanel kind="loading" title="Loading timeline" message="Collecting the merged contact history." /> : null}
      {!loading && error && rows.length === 0 ? <CommandStatePanel kind="error" title="Timeline is unavailable" message="The merged contact history could not be read." actionLabel="Retry" onAction={onRetry} /> : null}
      {!loading && !error && rows.length === 0 ? (
        verifiedEmpty
          ? <CommandStatePanel kind="empty" title="No timeline events" message="Every matching capture position records a complete empty timeline." />
          : <CommandStatePanel kind="partial_capture" title="Timeline was not fully captured" message="The source evidence does not prove that this timeline is empty." />
      ) : null}
      {!loading && rows.map((row) => (
          <article key={row.key}>
            <div className="command-contact-timeline-marker" aria-hidden="true" />
            <div>
              <span>{row.origin} · {row.kind}</span>
              <h3>{row.title}</h3>
              {row.body ? <p>{row.body}</p> : null}
              {row.outcome ? <strong>{row.outcome}</strong> : null}
              <time dateTime={row.occurred_at ?? undefined}>{row.occurred_at ? new Date(row.occurred_at).toLocaleString() : 'Time was not captured'}</time>
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
