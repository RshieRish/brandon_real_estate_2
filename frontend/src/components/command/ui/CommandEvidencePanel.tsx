import Link from 'next/link';

export type EvidenceLevel = 'observed_record' | 'rendered_occurrence' | 'displayed_aggregate';
export type CaptureQuality = 'complete' | 'partial' | 'limitation';

export type CommandArtifactLink = Readonly<{
  label: string;
  href: string;
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
  artifactLinks?: readonly CommandArtifactLink[];
}>;

const evidenceLabels: Record<EvidenceLevel, string> = {
  observed_record: 'Observed record',
  rendered_occurrence: 'Rendered occurrence',
  displayed_aggregate: 'Displayed aggregate',
};

const captureLabels: Record<CaptureQuality, string> = {
  complete: 'Complete capture',
  partial: 'Partial capture',
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
  artifactLinks = [],
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
      {artifactLinks.length > 0 ? (
        <ul className="command-evidence-links" aria-label="Source artifacts">
          {artifactLinks.map((artifact) => (
            <li key={artifact.href}>
              <Link href={artifact.href}>{artifact.label}</Link>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
