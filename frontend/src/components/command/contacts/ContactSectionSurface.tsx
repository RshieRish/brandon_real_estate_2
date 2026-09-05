import type {
  ContactEvidence,
  ContactEvidenceStatus,
  ContactInternalWorkspace,
  ContactMaterialization,
  ContactSectionName,
  ContactSectionPage,
} from '@/lib/command/contacts';
import { contactSectionCoverage } from '@/lib/command/contacts';
import { CommandEvidencePanel } from '../ui/CommandEvidencePanel';
import { CommandStatePanel } from '../ui/CommandStatePanel';
import { ContactExpandableValue } from './ContactExpandableValue';

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
      ...(value.budget ? [`Budget: ${value.budget}`] : []),
    ];
  }
  if (value.kind === 'smart_plan') return [value.status ?? 'Status was not captured'];
  if (value.kind === 'task') {
    const due = value.due_at
      ? `Due ${new Date(value.due_at).toLocaleString()}`
      : value.due_date
        ? `Due ${new Intl.DateTimeFormat('en-US', {
          month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
        }).format(new Date(`${value.due_date}T00:00:00Z`))}`
        : value.due_date_text
          ? `Due date as captured: ${value.due_date_text}`
          : 'Due date was not captured';
    return [
      value.description ?? 'Description was not captured',
      due,
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

function CapturedCoverageState({
  evidence,
  evidenceStatus,
  section,
  label,
  onRetryEvidence,
}: Readonly<{
  evidence: ContactEvidence | null;
  evidenceStatus: ContactEvidenceStatus;
  section: Exclude<ContactSectionName, 'timeline'>;
  label: string;
  onRetryEvidence: () => void;
}>) {
  const titleLabel = `${label[0]?.toUpperCase()}${label.slice(1)}`;
  if (evidenceStatus === 'loading') {
    return <CommandStatePanel kind="loading" title="Checking recovered source coverage" message={`Reading this contact's captured Command ${label}.`} />;
  }
  if (evidenceStatus === 'unavailable' || evidence === null) {
    return <CommandStatePanel kind="error" title="Recovered source coverage is unavailable" message={`Captured Command ${label} could not be verified. This is not an empty state.`} actionLabel="Retry source coverage" onAction={onRetryEvidence} />;
  }
  const coverage = contactSectionCoverage(evidence, section);
  if (coverage.state === 'unreconciled') {
    return <CommandStatePanel kind="evidence_only" title={`Recovered Command ${label} have not been restored`} message="This workspace has no reconciled contact capture positions yet. Protected archive evidence may still exist, so this section is not empty by default." />;
  }
  if (coverage.state === 'not_linked') {
    return <CommandStatePanel kind="evidence_only" title="No recovered Command record is linked to this contact" message={`The recovered archive is available globally, but this contact has no matched capture position for ${label}. This is not a verified empty section.`} />;
  }
  if (coverage.state === 'verified_empty') {
    return <CommandStatePanel kind="empty" title={`No ${label} were captured`} message="Every matching capture position records a complete empty state." />;
  }
  if (coverage.state === 'captured') {
    return <CommandStatePanel kind="partial_capture" title={`Recovered ${label} are not available`} message={`Source evidence records ${coverage.recovered_count} captured item${coverage.recovered_count === 1 ? '' : 's'}, but this section returned none.`} />;
  }
  return <CommandStatePanel kind="partial_capture" title={`${titleLabel} were not fully captured`} message="The source evidence does not prove that this section was empty." />;
}

export function CapturedSection({
  section,
  page,
  evidence,
  evidenceStatus,
  internal,
  loading,
  error,
  onRetry,
  onRetryEvidence,
  onViewEvidence,
}: Readonly<{
  section: Exclude<ContactSectionName, 'timeline'>;
  page: ContactSectionPage | null;
  evidence: ContactEvidence | null;
  evidenceStatus: ContactEvidenceStatus;
  internal: ContactInternalWorkspace | null;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  onRetryEvidence: () => void;
  onViewEvidence: () => void;
}>) {
  const label = sectionLabels[section];
  const cells = evidence?.section_matrix.filter((cell) => (
    cell.section === section
    && evidence.capture_positions.some((position) => (
      position.capture_position_id === cell.capture_position_id
    ))
  )) ?? [];
  const coverage = evidence ? contactSectionCoverage(evidence, section) : null;

  return (
    <section className="command-contact-source-region" role="region" aria-label={`Captured source ${label}`}>
      <div className="command-contact-region-heading"><span>Captured source</span><h3>Recovered source {label}</h3></div>
      {loading ? <CommandStatePanel kind="loading" title={`Loading captured ${label}`} message="Reading the immutable source section." /> : null}
      {error ? <CommandStatePanel kind="error" title={`Captured ${label} are unavailable`} message="The source section could not be read." actionLabel="Retry" onAction={onRetry} /> : null}
      {!loading && !error && page && page.rows.length > 0 ? (
        <>
          <p className="command-contact-source-summary">
            <strong>{page.total} recovered source {page.total === 1 ? 'record' : 'records'}</strong>
            <span>{coverage?.state === 'captured'
              ? `${coverage.complete_positions} of ${coverage.capture_positions} capture positions complete`
              : evidenceStatus === 'unavailable' ? 'Source coverage unavailable' : 'Source coverage is still being verified'}</span>
          </p>
          <div className="command-contact-cards">
          {page.rows.map((row) => {
            const title = row.value.title;
            const targetExists = internalTargetExists(row, internal);
            const recoveredArchivedEvidence = section === 'tasks_archived'
              && row.status === 'source_only'
              && row.value.kind === 'task';
            return (
              <article key={`${row.source_record_id}-${row.source_key_hash}-${row.section}-${row.occurrence_ordinal}`} className="command-contact-record-card">
                <div className="command-contact-record-heading"><ContactExpandableValue value={title} limit={180} element="h4" label="recovered title" /><span>{row.capture_quality} capture</span></div>
                {occurrenceDetails(row).map((detail, index) => <ContactExpandableValue key={`${index}-${detail.slice(0, 32)}`} value={detail} limit={420} element="p" label="recovered value" />)}
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
        </>
      ) : null}
      {!loading && !error && page && page.rows.length === 0 ? (
        <CapturedCoverageState evidence={evidence} evidenceStatus={evidenceStatus} section={section} label={label} onRetryEvidence={onRetryEvidence} />
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
        <CommandStatePanel kind="empty" title={`No SWS internal ${label}`} message={`There are no current SWS-owned ${label} for this contact. Recovered Command records, when available, are shown separately above.`} />
      ) : children}
    </section>
  );
}
