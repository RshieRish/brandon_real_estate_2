export type EvidenceLevel = 'observed_record' | 'rendered_occurrence' | 'displayed_aggregate';
export type CaptureQuality = 'complete' | 'partial' | 'shell' | 'error' | 'limitation';

export type CommandArtifactAction = Readonly<{
  label: string;
  onAction: () => void;
  disabled?: boolean;
}>;

export type CommandEvidencePanelProps = Readonly<{
  evidenceLevel: EvidenceLevel;
  captureQuality: CaptureQuality;
  displayLabel: string;
  observedCount?: number;
  normalizedCount?: number | null;
  renderedCount?: number;
  displayedCount?: number;
  artifactCount?: number;
  explanation?: string;
  artifactActions?: readonly CommandArtifactAction[];
}>;

const evidenceLabels: Record<EvidenceLevel, string> = {
  observed_record: 'Observed record',
  rendered_occurrence: 'Rendered occurrence',
  displayed_aggregate: 'Displayed aggregate',
};

const captureLabels: Record<CaptureQuality, string> = {
  complete: 'Complete capture',
  partial: 'Partial capture',
  shell: 'Shell capture',
  error: 'Capture error',
  limitation: 'Capture limitation',
};

const numberFormatter = new Intl.NumberFormat('en-US');

export function CommandEvidencePanel({
  evidenceLevel,
  captureQuality,
  displayLabel,
  observedCount,
  normalizedCount,
  renderedCount,
  displayedCount,
  artifactCount,
  explanation,
  artifactActions = [],
}: CommandEvidencePanelProps) {
  const aggregateExplanation = evidenceLevel === 'displayed_aggregate' && displayedCount !== undefined
    ? observedCount === undefined
      ? `${numberFormatter.format(displayedCount)} was displayed; distinct records were not materialized.`
      : `${numberFormatter.format(displayedCount)} was displayed; ${numberFormatter.format(observedCount)} distinct identities were observed.`
    : null;

  return (
    <section className="command-evidence-panel" aria-label={`${displayLabel} evidence`}>
      <div className="command-evidence-heading">
        <div>
          <span className="command-eyebrow">SOURCE EVIDENCE</span>
          <h3>{displayLabel}</h3>
        </div>
        <div className="command-evidence-badges">
          <span data-level={evidenceLevel}>{evidenceLabels[evidenceLevel]}</span>
          <span data-quality={captureQuality}>{captureLabels[captureQuality]}</span>
        </div>
      </div>
      <dl className="command-evidence-counts">
        {observedCount !== undefined ? (
          <div>
            <dt>Observed records</dt>
            <dd>{numberFormatter.format(observedCount)}</dd>
          </div>
        ) : null}
        {normalizedCount !== undefined ? (
          <div>
            <dt>Normalized records</dt>
            <dd>{normalizedCount === null ? 'Not materialized' : numberFormatter.format(normalizedCount)}</dd>
          </div>
        ) : null}
        {renderedCount !== undefined ? (
          <div>
            <dt>Rendered occurrences</dt>
            <dd>{numberFormatter.format(renderedCount)}</dd>
          </div>
        ) : null}
        {displayedCount !== undefined ? (
          <div>
            <dt>Displayed count</dt>
            <dd>{numberFormatter.format(displayedCount)}</dd>
          </div>
        ) : null}
        {artifactCount !== undefined ? (
          <div>
            <dt>Source artifacts</dt>
            <dd>{numberFormatter.format(artifactCount)}</dd>
          </div>
        ) : null}
      </dl>
      {aggregateExplanation ? <p className="command-evidence-explanation">{aggregateExplanation}</p> : null}
      {explanation ? <p className="command-evidence-explanation">{explanation}</p> : null}
      {artifactActions.length > 0 ? (
        <ul className="command-evidence-links" aria-label="Source artifact actions">
          {artifactActions.map((artifact) => (
            <li key={artifact.label}>
              <button type="button" disabled={artifact.disabled} onClick={artifact.onAction}>
                {artifact.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
