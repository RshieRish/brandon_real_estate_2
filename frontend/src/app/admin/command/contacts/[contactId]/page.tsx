'use client';

import { useParams } from 'next/navigation';
import { ContactDetailWorkspace } from '@/components/command/contacts/ContactDetailWorkspace';
import { CommandStatePanel } from '@/components/command/ui/CommandStatePanel';

export function canonicalContactId(raw: string): number | null {
  if (!/^[1-9][0-9]*$/.test(raw)) return null;
  const parsed = Number(raw);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

export default function ContactDetailPage() {
  const { contactId: rawContactId } = useParams<{ contactId: string }>();
  const contactId = canonicalContactId(rawContactId);
  if (contactId === null) {
    return (
      <CommandStatePanel
        kind="error"
        title="Invalid contact"
        message="The contact route does not contain a canonical positive decimal ID."
        actionLabel="Back to contacts"
        onAction={() => { window.location.href = '/admin/command/contacts'; }}
      />
    );
  }
  return <ContactDetailWorkspace contactId={contactId} />;
}
