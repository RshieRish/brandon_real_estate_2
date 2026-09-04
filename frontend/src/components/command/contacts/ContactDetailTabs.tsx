import {
  contactSectionCoverage,
  type ContactEvidence,
  type ContactEvidenceStatus,
  type ContactInternalWorkspace,
  type ContactSectionCoverage,
  type ContactSectionName,
} from '@/lib/command/contacts';
import type { ContactDetailView, ContactTaskView } from './ContactDetailWorkspace';
import { CommandTabs, type CommandTab } from '../ui/CommandTabs';

export const CONTACT_DETAIL_TABS: readonly Readonly<{ value: ContactDetailView; label: string }>[] = [
  { value: 'timeline', label: 'Timeline' },
  { value: 'opportunities', label: 'Opportunities' },
  { value: 'smart_plans', label: 'SmartPlans' },
  { value: 'tasks', label: 'Tasks' },
  { value: 'notes', label: 'Notes' },
  { value: 'saved_searches', label: 'Saved Searches' },
  { value: 'evidence', label: 'Source Evidence' },
  { value: 'bookings', label: 'Bookings · SWS internal' },
];

export const TASK_TABS: readonly Readonly<{ value: ContactTaskView; label: string }>[] = [
  { value: 'to_do', label: 'To Do' },
  { value: 'completed', label: 'Completed' },
  { value: 'archived', label: 'Archived' },
];

function sourceMetric(coverage: ContactSectionCoverage): string {
  if (coverage.state === 'captured') return `${coverage.recovered_count} captured`;
  if (coverage.state === 'verified_empty') return '0 verified';
  if (coverage.state === 'unreconciled') return 'Not restored';
  if (coverage.state === 'not_linked') return 'Not linked';
  return 'Source partial';
}

function sourceMetricFor(
  evidence: ContactEvidence | null,
  evidenceStatus: ContactEvidenceStatus,
  section: ContactSectionName,
): string {
  if (evidenceStatus === 'loading') return 'Checking source';
  if (evidenceStatus === 'unavailable' || evidence === null) return 'Source unavailable';
  return sourceMetric(contactSectionCoverage(evidence, section));
}

function internalMetric(
  count: number,
  internalStatus: ContactEvidenceStatus,
): string {
  if (internalStatus === 'loading') return 'SWS loading';
  if (internalStatus === 'unavailable') return 'SWS unavailable';
  return `${count} SWS`;
}

function combinedMetric(
  source: string,
  count: number,
  internalStatus: ContactEvidenceStatus,
): string {
  return `${source} · ${internalMetric(count, internalStatus)}`;
}

function taskSourceMetric(
  evidence: ContactEvidence | null,
  evidenceStatus: ContactEvidenceStatus,
): string {
  if (evidenceStatus !== 'available' || evidence === null) {
    return sourceMetricFor(evidence, evidenceStatus, 'tasks_to_do');
  }
  const coverages = (['tasks_to_do', 'tasks_completed', 'tasks_archived'] as const).map((section) => (
    contactSectionCoverage(evidence, section)
  ));
  if (coverages.some((coverage) => coverage.state === 'unreconciled')) return 'Not restored';
  if (coverages.some((coverage) => coverage.state === 'not_linked')) return 'Not linked';
  const recovered = coverages.reduce((total, coverage) => total + coverage.recovered_count, 0);
  if (recovered > 0) return `${recovered} captured`;
  return coverages.every((coverage) => coverage.state === 'verified_empty')
    ? '0 verified'
    : 'Source partial';
}

export function ContactDetailTabs({
  value,
  onChange,
  evidence,
  evidenceStatus,
  internal,
  internalStatus,
  timelineCount,
  timelineHasMore,
}: Readonly<{
  value: ContactDetailView;
  onChange: (value: ContactDetailView) => void;
  evidence: ContactEvidence | null;
  evidenceStatus: ContactEvidenceStatus;
  internal: ContactInternalWorkspace | null;
  internalStatus: ContactEvidenceStatus;
  timelineCount: number;
  timelineHasMore: boolean;
}>) {
  const tabs: readonly CommandTab<ContactDetailView>[] = [
    {
      value: 'timeline',
      label: 'Timeline',
      meta: `${timelineCount}${timelineHasMore ? '+' : ''} ${timelineCount === 1 && !timelineHasMore ? 'event' : 'events'}`,
    },
    {
      value: 'opportunities',
      label: 'Opportunities',
      meta: combinedMetric(sourceMetricFor(evidence, evidenceStatus, 'opportunities'), internal?.opportunities.length ?? 0, internalStatus),
    },
    {
      value: 'smart_plans',
      label: 'SmartPlans',
      meta: combinedMetric(sourceMetricFor(evidence, evidenceStatus, 'smart_plans'), internal?.smart_plans.length ?? 0, internalStatus),
    },
    {
      value: 'tasks',
      label: 'Tasks',
      meta: combinedMetric(taskSourceMetric(evidence, evidenceStatus), internal?.tasks.length ?? 0, internalStatus),
    },
    {
      value: 'notes',
      label: 'Notes',
      meta: combinedMetric(sourceMetricFor(evidence, evidenceStatus, 'notes'), internal?.notes.length ?? 0, internalStatus),
    },
    {
      value: 'saved_searches',
      label: 'Saved Searches',
      meta: combinedMetric(sourceMetricFor(evidence, evidenceStatus, 'saved_searches'), internal?.saved_searches.length ?? 0, internalStatus),
    },
    {
      value: 'evidence',
      label: 'Source Evidence',
      meta: evidenceStatus === 'loading'
        ? 'Checking coverage'
        : evidenceStatus === 'unavailable' || evidence === null
          ? 'Unavailable'
          : `${evidence.capture_positions.length} ${evidence.capture_positions.length === 1 ? 'capture' : 'captures'}`,
    },
    {
      value: 'bookings',
      label: 'Bookings · SWS internal',
      meta: internalMetric(internal?.bookings.length ?? 0, internalStatus),
    },
  ];
  return <CommandTabs idBase="contact-detail-view" ariaLabel="Contact detail views" tabs={tabs} value={value} onValueChange={onChange} />;
}

export function ContactTaskTabs({ value, onChange }: { value: ContactTaskView; onChange: (value: ContactTaskView) => void }) {
  return <CommandTabs idBase="contact-task-state" ariaLabel="Task states" tabs={TASK_TABS} value={value} onValueChange={onChange} />;
}
