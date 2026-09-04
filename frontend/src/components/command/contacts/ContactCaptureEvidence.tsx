'use client';

import { useEffect, useRef, useState } from 'react';
import type { ContactEvidence, ContactsApi } from '@/lib/command/contacts';
import { CommandEvidencePanel } from '../ui/CommandEvidencePanel';
import { CommandStatePanel } from '../ui/CommandStatePanel';

export function ContactCaptureEvidence({
  evidence,
  api,
  contactId,
}: Readonly<{
  evidence: ContactEvidence;
  api: ContactsApi;
  contactId: number;
}>) {
  const [busyArtifact, setBusyArtifact] = useState<number | null>(null);
  const [error, setError] = useState('');
  const controllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const requestIdRef = useRef(0);
  const contactIdRef = useRef(contactId);
  contactIdRef.current = contactId;
  const completeSectionChecks = evidence.section_matrix.filter((cell) => cell.capture_quality === 'complete').length;
  const capturedRows = evidence.section_matrix.reduce((total, cell) => total + cell.row_count, 0);
  const coverageTitle = evidence.capture_positions.length > 0
    ? `${evidence.capture_positions.length} recovered Command ${evidence.capture_positions.length === 1 ? 'capture' : 'captures'} linked`
    : evidence.provider_contact_rows > 0
      ? 'No recovered Command record is linked to this contact'
      : 'Recovered contact restoration is pending';
  const coverageMessage = evidence.capture_positions.length > 0
    ? `${completeSectionChecks} of ${evidence.section_matrix.length} section checks are complete, with ${capturedRows} captured ${capturedRows === 1 ? 'record' : 'records'}.`
    : evidence.provider_contact_rows > 0
      ? 'The recovered archive is available globally, but global totals do not prove that this contact has a captured position.'
      : 'No contact capture positions have been reconciled in this workspace yet. Protected source artifacts remain separate from current SWS records.';

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const controller = controllerRef.current;
      controllerRef.current = null;
      controller?.abort();
    };
  }, []);
  useEffect(() => {
    requestIdRef.current += 1;
    const controller = controllerRef.current;
    controllerRef.current = null;
    controller?.abort();
    setBusyArtifact(null);
    setError('');
  }, [contactId]);

  async function download(artifactId: number, artifactType: string) {
    if (busyArtifact !== null) return;
    const controller = new AbortController();
    const requestId = requestIdRef.current + 1;
    const ownedContactId = contactId;
    requestIdRef.current = requestId;
    controllerRef.current = controller;
    setBusyArtifact(artifactId);
    setError('');
    try {
      const blob = await api.artifactBlob(artifactId, { signal: controller.signal });
      if (!mountedRef.current || controller.signal.aborted || controllerRef.current !== controller || requestIdRef.current !== requestId || contactIdRef.current !== ownedContactId) return;
      const url = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `command-contact-evidence-${artifactId}.${artifactType}`;
        anchor.click();
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch {
      if (mountedRef.current && !controller.signal.aborted && controllerRef.current === controller && requestIdRef.current === requestId && contactIdRef.current === ownedContactId) {
        setError('Source artifact could not be downloaded.');
      }
    } finally {
      if (mountedRef.current && !controller.signal.aborted && controllerRef.current === controller && requestIdRef.current === requestId && contactIdRef.current === ownedContactId) {
        controllerRef.current = null;
        setBusyArtifact(null);
      }
    }
  }

  return (
    <section className="command-contact-capture-evidence" role="region" aria-label="Contact capture evidence">
      <section className="command-contact-evidence-overview" aria-label="Current contact recovery summary">
        <p className="command-contacts-kicker">Current contact coverage</p>
        <h3>{coverageTitle}</h3>
        <p>{coverageMessage}</p>
      </section>
      <section className="command-contact-global-evidence" aria-label="Recovered archive global evidence">
        <p className="command-contacts-kicker">Recovered archive (global)</p>
        <h3>Archive reconciliation totals</h3>
        <div className="command-contact-global-counts">
          <span>{evidence.provider_contact_rows} provider contact rows</span>
          <span>{evidence.resolved_provider_identities} resolved provider identities</span>
          <span>{evidence.coalesced_aliases} coalesced aliases</span>
          <span>{evidence.lead_backed_contacts} lead-backed contacts</span>
          <span>{evidence.reviewed_overlaps} reviewed overlaps</span>
          <span>{evidence.legacy_only_contacts} legacy-only contacts</span>
        </div>
      </section>
      <section aria-label="Current contact capture positions">
        <p className="command-contacts-kicker">Current contact</p>
        <h3>Capture positions and source records</h3>
        {evidence.capture_positions.length === 0 ? (
          <CommandStatePanel kind="evidence_only" title="No contact capture positions" message="Global archive totals do not prove this contact has a captured position." />
        ) : evidence.capture_positions.map((position) => (
          <CommandEvidencePanel
            key={position.capture_position_id}
            evidenceLevel="observed_record"
            captureQuality={position.capture_quality}
            displayLabel={`Capture position ${position.capture_ordinal}`}
            renderedCount={position.sections.reduce((total, section) => total + section.row_count, 0)}
            explanation={position.sections.flatMap((section) => section.limitation_codes).join(', ') || undefined}
          />
        ))}
      </section>
      <section aria-label="Current contact section matrix">
        <p className="command-contacts-kicker">Current contact</p>
        <h3>Section capture matrix</h3>
        {evidence.section_matrix.length === 0 ? (
          <CommandStatePanel kind="evidence_only" title="No section capture matrix" message="This contact has no section-level capture evidence." />
        ) : evidence.section_matrix.map((cell) => {
          const ordinal = evidence.capture_positions.find((position) => (
            position.capture_position_id === cell.capture_position_id
          ))?.capture_ordinal;
          return (
            <CommandEvidencePanel
              key={`${cell.capture_position_id}-${cell.section}-${cell.source_record_id}`}
              evidenceLevel="rendered_occurrence"
              captureQuality={cell.capture_quality}
              displayLabel={`Capture position ${ordinal ?? 'unknown'} · ${cell.section}`}
              renderedCount={cell.row_count}
              explanation={cell.limitation_codes.join(', ') || undefined}
            />
          );
        })}
      </section>
      {evidence.sources.map((source) => (
        <CommandEvidencePanel
          key={source.source_record_id}
          evidenceLevel={source.evidence_level}
          captureQuality={source.capture_quality}
          displayLabel={`${source.record_kind} · source ${source.source_record_id}`}
          artifactCount={source.artifacts.length}
          artifactActions={source.artifacts.map((artifact) => ({
            label: busyArtifact === artifact.artifact_id
              ? `Downloading ${artifact.artifact_type} source artifact ${artifact.artifact_id}…`
              : `Download ${artifact.artifact_type} source artifact ${artifact.artifact_id}`,
            disabled: busyArtifact !== null,
            onAction: () => void download(artifact.artifact_id, artifact.artifact_type),
          }))}
        />
      ))}
      {busyArtifact !== null ? <p role="status">Downloading source artifact {busyArtifact}…</p> : null}
      {error ? <p role="alert" className="command-contacts-form-error">{error}</p> : null}
    </section>
  );
}
