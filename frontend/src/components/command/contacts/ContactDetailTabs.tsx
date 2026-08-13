import type { ContactDetailView, ContactTaskView } from './ContactDetailWorkspace';
import { CommandTabs } from '../ui/CommandTabs';

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

export function ContactDetailTabs({ value, onChange }: { value: ContactDetailView; onChange: (value: ContactDetailView) => void }) {
  return <CommandTabs idBase="contact-detail-view" ariaLabel="Contact detail views" tabs={CONTACT_DETAIL_TABS} value={value} onValueChange={onChange} />;
}

export function ContactTaskTabs({ value, onChange }: { value: ContactTaskView; onChange: (value: ContactTaskView) => void }) {
  return <CommandTabs idBase="contact-task-state" ariaLabel="Task states" tabs={TASK_TABS} value={value} onValueChange={onChange} />;
}
