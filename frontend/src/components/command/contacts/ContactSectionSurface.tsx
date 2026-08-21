import type {
  ContactEvidence,
  ContactInternalWorkspace,
  ContactMaterialization,
  ContactSectionName,
  ContactSectionPage,
} from '@/lib/command/contacts';
import { CommandEvidencePanel } from '../ui/CommandEvidencePanel';
import { CommandStatePanel } from '../ui/CommandStatePanel';

const sectionLabels: Readonly<Record<Exclude<ContactSectionName, 'timeline'>, string>> = {
  opportunities: 'opportunities',
  smart_plans: 'SmartPlans',
  notes: 'notes',
  saved_searches: 'saved searches',
  tasks_to_do: 'to-do tasks',
  tasks_completed: 'completed tasks',
  tasks_archived: 'archived tasks',
};

function occurrenceDetails(row: ContactMaterialization): readonly string[] {
  const value = row.value;
  if (value.kind === 'opportunity') {
    return [
      value.stage ? `Stage: ${value.stage}` : 'Stage was not captured',
      value.value_cents === null
        ? 'Value was not captured'
        : `Value: ${new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value.value_cents / 100)}`,
    ];
  }
  if (value.kind === 'smart_plan') return [value.status ?? 'Status was not captured'];
  if (value.kind === 'task') {
    return [
      value.description ?? 'Description was not captured',
      value.due_at ? `Due ${new Date(value.due_at).toLocaleString()}` : 'Due date was not captured',
    ];
  }
  if (value.kind === 'note') return [value.body ?? 'Note body was not captured'];
  return value.criteria_summary.length > 0
    ? value.criteria_summary
    : ['Search criteria were not captured'];
}

function internalTargetExists(
  row: ContactMaterialization,
  internal: ContactInternalWorkspace | null,
): boolean {
  if (row.status !== 'materialized' || internal === null) return false;
  const id = row.entity_id;
  if (row.entity_type === 'opportunity') return internal.opportunities.some((value) => value.id === id);
  if (row.entity_type === 'smart_plan') return internal.smart_plans.some((value) => value.id === id);
  if (row.entity_type === 'task') return internal.tasks.some((value) => value.id === id);
  if (row.entity_type === 'note') return internal.notes.some((value) => value.id === id);
  return internal.saved_searches.some((value) => value.id === id);
}

export function CapturedSection({
  section,
  page,
  evidence,
  internal,
  loading,
  error,
  onRetry,
  onViewEvidence,
}: Readonly<{
  section: Exclude<ContactSectionName, 'timeline'>;
  page: ContactSectionPage | null;
  evidence: ContactEvidence | null;
  internal: ContactInternalWorkspace | null;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  onViewEvidence: () => void;
}>) {
  const label = sectionLabels[section];
  const cells = evidence?.section_matrix.filter((cell) => (
    cell.section === section
    && evidence.capture_positions.some((position) => (
      position.capture_position_id === cell.capture_position_id
    ))
  )) ?? [];
  const hasCompleteCoverage = (evidence?.capture_positions.length ?? 0) > 0
    && cells.length === evidence?.capture_positions.length
    && evidence?.capture_positions.every((position) => cells.filter((cell) => (
      cell.capture_position_id === position.capture_position_id
    )).length === 1);

  return (
    <section className="command-contact-source-region" role="region" aria-label={`Captured source ${label}`}>
      <div className="command-contact-region-heading"><span>Captured source</span><h3>Recovered source {label}</h3></div>
      {loading ? <CommandStatePanel kind="loading" title={`Loading captured ${label}`} message="Reading the immutable source section." /> : null}
      {error ? <CommandStatePanel kind="error" title={`Captured ${label} are unavailable`} message="The source section could not be read." actionLabel="Retry" onAction={onRetry} /> : null}
      {!loading && !error && page && page.rows.length > 0 ? (
        <div className="command-contact-cards">
          {page.rows.map((row) => {
            const title = row.value.title;
            const targetExists = internalTargetExists(row, internal);
            const recoveredArchivedEvidence = section === 'tasks_archived'
              && row.status === 'source_only'
              && row.value.kind === 'task';
            return (
              <article key={`${row.source_record_id}-${row.source_key_hash}-${row.section}-${row.occurrence_ordinal}`} className="command-contact-record-card">
                <div className="command-contact-record-heading"><h4>{title}</h4><span>{row.capture_quality} capture</span></div>
                {occurrenceDetails(row).map((detail) => <p key={detail}>{detail}</p>)}
                {row.status === 'source_only' ? (
                  <div className="command-contact-record-status">
                    <strong>{recoveredArchivedEvidence ? 'Recovered evidence' : 'Source evidence only'}</strong>
                    {recoveredArchivedEvidence ? null : <button type="button" className="command-inline-button" onClick={onViewEvidence}>View source evidence</button>}
                  </div>
                ) : targetExists ? (
                  <div className="command-contact-record-status">
                    <strong>Materialized in SWS</strong>
                    <span>Linked {row.entity_type} #{row.entity_id}</span>
                  </div>
                ) : (
                  <div className="command-contact-record-status is-unavailable">
                    <strong>Internal target unavailable</strong>
                    <span>Expected {row.entity_type} #{row.entity_id}</span>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      ) : null}
      {!loading && !error && page && page.rows.length === 0 ? (
        hasCompleteCoverage && cells.every((cell) => (
          cell.capture_quality === 'complete' && cell.is_empty && cell.row_count === 0
        )) ? (
          <CommandStatePanel kind="empty" title={`No ${label} were captured`} message="Every matching capture position records a complete empty state." />
        ) : (
          <CommandStatePanel kind="partial_capture" title={`${label[0]?.toUpperCase()}${label.slice(1)} were not fully captured`} message="The source evidence does not prove that this section was empty." />
        )
      ) : null}
      {cells.map((cell) => (
        <CommandEvidencePanel
          key={`${cell.capture_position_id}-${cell.source_record_id}-${cell.section}`}
          evidenceLevel="rendered_occurrence"
          captureQuality={cell.capture_quality}
          displayLabel={`Capture position ${
            evidence?.capture_positions.find((position) => (
              position.capture_position_id === cell.capture_position_id
            ))?.capture_ordinal ?? 'unknown'
          } · ${label}`}
          renderedCount={cell.row_count}
          explanation={cell.limitation_codes.length > 0 ? cell.limitation_codes.join(', ') : undefined}
        />
      ))}
    </section>
  );
}

export function InternalState({
  label,
  loading,
  available,
  empty,
  onRetry,
  children,
}: Readonly<{
  label: string;
  loading: boolean;
  available: boolean;
  empty: boolean;
  onRetry: () => void;
  children: React.ReactNode;
}>) {
  return (
    <section className="command-contact-internal-region" role="region" aria-label={`SWS internal ${label}`}>
      <div className="command-contact-region-heading"><span>SWS internal</span><h3>SWS internal {label}</h3></div>
      {loading ? (
        <CommandStatePanel kind="loading" title={`Loading SWS internal ${label}`} message="Reading the current SWS-owned records." />
      ) : !available ? (
        <CommandStatePanel kind="error" title={`SWS internal ${label} are unavailable`} message="Current SWS records could not be verified. This is not an empty state." actionLabel="Retry" onAction={onRetry} />
      ) : empty ? (
        <CommandStatePanel kind="empty" title={`No SWS internal ${label}`} message={`There are no current SWS-owned ${label} for this contact.`} />
      ) : children}
    </section>
  );
}
