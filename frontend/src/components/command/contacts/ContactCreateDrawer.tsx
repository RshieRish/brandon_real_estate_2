'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent, RefObject } from 'react';
import type {
  ContactCreateInput,
  ContactCreated,
  ContactsApi,
} from '@/lib/command/contacts';
import { CommandOverlay } from '../ui/CommandOverlay';

const STAGE_SUGGESTIONS = ['lead', 'nurture', 'appointment', 'client', 'past_client', 'lost'] as const;
const EMPTY_DRAFT = {
  first_name: '',
  last_name: '',
  email: '',
  phone: '',
  stage: 'lead',
  birthday: '',
  anniversary: '',
} as const;

type ContactDraft = {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  stage: string;
  birthday: string;
  anniversary: string;
};

function within(value: string | null | undefined, maximum: number): boolean {
  return value == null || Array.from(value).length <= maximum;
}

export type ContactCreateDrawerProps = Readonly<{
  open: boolean;
  api: ContactsApi;
  triggerRef: RefObject<HTMLElement | null>;
  onOpenChange: (open: boolean) => void;
  onCreated: (contact: ContactCreated, displayName: string) => void;
}>;

function input(draft: ContactDraft): ContactCreateInput {
  return {
    first_name: draft.first_name.trim(),
    ...(draft.last_name.trim() ? { last_name: draft.last_name.trim() } : {}),
    ...(draft.email.trim() ? { email: draft.email.trim() } : {}),
    ...(draft.phone.trim() ? { phone: draft.phone.trim() } : {}),
    stage: draft.stage.trim(),
    ...(draft.birthday ? { birthday: draft.birthday } : {}),
    ...(draft.anniversary ? { anniversary: draft.anniversary } : {}),
  };
}

export function ContactCreateDrawer({
  open,
  api,
  triggerRef,
  onOpenChange,
  onCreated,
}: ContactCreateDrawerProps) {
  const [draft, setDraft] = useState<ContactDraft>({ ...EMPTY_DRAFT });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const submittingRef = useRef(false);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const update = (key: keyof ContactDraft, value: string) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const setOpen = useCallback((next: boolean) => {
    if (submittingRef.current && !next) return;
    if (!next) setError(null);
    onOpenChange(next);
  }, [onOpenChange]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const payload = input(draft);
    if (!payload.first_name) {
      setError('First name is required.');
      return;
    }
    if (
      !within(payload.first_name, 120)
      || !within(payload.last_name, 120)
      || !within(payload.email, 255)
      || !within(payload.phone, 50)
      || !within(payload.stage, 50)
    ) {
      setError('One or more fields are too long.');
      return;
    }
    if (payload.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(payload.email)) {
      setError('Enter a valid email address.');
      return;
    }
    if (!payload.stage) {
      setError('Stage is required.');
      return;
    }
    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;
    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.create(payload, { signal: controller.signal });
      if (controller.signal.aborted) return;
      const displayName = `${payload.first_name} ${payload.last_name ?? ''}`.trim();
      setDraft({ ...EMPTY_DRAFT });
      submittingRef.current = false;
      setSubmitting(false);
      onOpenChange(false);
      onCreated(created, displayName);
    } catch (caught) {
      if (controller.signal.aborted || (caught instanceof DOMException && caught.name === 'AbortError')) return;
      setError('Unable to create contact. Review the fields and try again.');
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <CommandOverlay
      variant="drawer"
      open={open}
      onOpenChange={setOpen}
      labelledBy="command-add-contact-title"
      closeLabel="Close add contact"
      triggerRef={triggerRef}
    >
      <form className="command-contacts-create-form" noValidate onSubmit={(event) => void submit(event)}>
        <div>
          <p className="command-contacts-kicker">Internal CRM</p>
          <h2 id="command-add-contact-title">Add contact</h2>
          <p>Create a writable SWS contact. Recovered provider evidence stays read-only.</p>
        </div>
        {error ? <p role="alert" className="command-contacts-form-error">{error}</p> : null}
        <div className="command-contacts-form-grid">
          <label>
            First name
            <input required value={draft.first_name} onChange={(event) => update('first_name', event.target.value)} />
          </label>
          <label>
            Last name
            <input value={draft.last_name} onChange={(event) => update('last_name', event.target.value)} />
          </label>
          <label>
            Email
            <input type="email" value={draft.email} onChange={(event) => update('email', event.target.value)} />
          </label>
          <label>
            Phone
            <input type="tel" value={draft.phone} onChange={(event) => update('phone', event.target.value)} />
          </label>
          <label>
            Stage
            <input
              list="command-contact-create-stages"
              required
              value={draft.stage}
              onChange={(event) => update('stage', event.target.value)}
            />
            <datalist id="command-contact-create-stages">
              {STAGE_SUGGESTIONS.map((stage) => <option key={stage} value={stage} />)}
            </datalist>
          </label>
          <label>
            Birthday
            <input type="date" value={draft.birthday} onChange={(event) => update('birthday', event.target.value)} />
          </label>
          <label>
            Anniversary
            <input type="date" value={draft.anniversary} onChange={(event) => update('anniversary', event.target.value)} />
          </label>
        </div>
        <div className="command-contacts-form-actions">
          <button type="button" className="command-secondary-button command-touch-target" disabled={submitting} onClick={() => setOpen(false)}>
            Cancel
          </button>
          <button type="submit" className="command-primary-button command-touch-target" disabled={submitting}>
            {submitting ? 'Creating contact…' : 'Create contact'}
          </button>
        </div>
      </form>
    </CommandOverlay>
  );
}
