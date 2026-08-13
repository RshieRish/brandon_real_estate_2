'use client';

import { FloppyDisk, PencilSimple, X } from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';
import type {
  ContactUpdateInput,
  ContactsApi,
  LegacyContact,
} from '@/lib/command/contacts';

type Editable = Readonly<{
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  stage: string;
  birthday: string;
  anniversary: string;
}>;

function fields(contact: LegacyContact): Editable {
  return {
    first_name: contact.first_name,
    last_name: contact.last_name,
    email: contact.email ?? '',
    phone: contact.phone ?? '',
    stage: contact.stage,
    birthday: contact.birthday ?? '',
    anniversary: contact.anniversary ?? '',
  };
}

function changedInput(
  original: Editable,
  current: Editable,
  dirty: ReadonlySet<keyof Editable>,
): ContactUpdateInput {
  const result: {
    first_name?: string;
    last_name?: string;
    email?: string | null;
    phone?: string | null;
    stage?: string;
    birthday?: string | null;
    anniversary?: string | null;
  } = {};
  if (dirty.has('first_name') && current.first_name !== original.first_name) result.first_name = current.first_name.trim();
  if (dirty.has('last_name') && current.last_name !== original.last_name) result.last_name = current.last_name.trim();
  if (dirty.has('email') && current.email !== original.email) result.email = current.email.trim() || null;
  if (dirty.has('phone') && current.phone !== original.phone) result.phone = current.phone.trim() || null;
  if (dirty.has('stage') && current.stage !== original.stage) result.stage = current.stage.trim();
  if (dirty.has('birthday') && current.birthday !== original.birthday) result.birthday = current.birthday || null;
  if (dirty.has('anniversary') && current.anniversary !== original.anniversary) result.anniversary = current.anniversary || null;
  return result;
}

export function ContactProfileEditor({
  contact,
  api,
  onUpdated,
  mutationBlocked = false,
  acquireMutation,
  releaseMutation,
}: Readonly<{
  contact: LegacyContact;
  api: ContactsApi;
  onUpdated: () => Promise<void>;
  mutationBlocked?: boolean;
  acquireMutation?: () => boolean;
  releaseMutation?: () => void;
}>) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Editable>(() => fields(contact));
  const [original, setOriginal] = useState<Editable>(() => fields(contact));
  const [dirty, setDirty] = useState<ReadonlySet<keyof Editable>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [verificationRequired, setVerificationRequired] = useState(false);
  const [retryPending, setRetryPending] = useState(false);
  const [restoreFocus, setRestoreFocus] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const mountedRef = useRef(true);
  const contactIdRef = useRef(contact.id);
  const latestFieldsRef = useRef(fields(contact));
  contactIdRef.current = contact.id;
  latestFieldsRef.current = fields(contact);

  useEffect(() => {
    if (!open && restoreFocus) {
      triggerRef.current?.focus();
      setRestoreFocus(false);
    }
  }, [open, restoreFocus]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const controller = controllerRef.current;
      controllerRef.current = null;
      controller?.abort();
      releaseMutation?.();
    };
  }, [releaseMutation]);
  useEffect(() => {
    const controller = controllerRef.current;
    controllerRef.current = null;
    controller?.abort();
    releaseMutation?.();
    setOpen(false);
    setSaving(false);
    setVerificationRequired(false);
    setRetryPending(false);
    const next = latestFieldsRef.current;
    setOriginal(next);
    setDraft(next);
    setDirty(new Set());
  }, [contact.id, releaseMutation]);
  useEffect(() => {
    if (controllerRef.current !== null) return;
    const next = latestFieldsRef.current;
    setOriginal(next);
    setDraft((current) => ({
      first_name: dirty.has('first_name') ? current.first_name : next.first_name,
      last_name: dirty.has('last_name') ? current.last_name : next.last_name,
      email: dirty.has('email') ? current.email : next.email,
      phone: dirty.has('phone') ? current.phone : next.phone,
      stage: dirty.has('stage') ? current.stage : next.stage,
      birthday: dirty.has('birthday') ? current.birthday : next.birthday,
      anniversary: dirty.has('anniversary') ? current.anniversary : next.anniversary,
    }));
  }, [
    contact.first_name,
    contact.last_name,
    contact.email,
    contact.phone,
    contact.stage,
    contact.birthday,
    contact.anniversary,
    dirty,
  ]);

  const begin = () => {
    if (mutationBlocked) return;
    const next = latestFieldsRef.current;
    setOriginal(next);
    setDraft(next);
    setDirty(new Set());
    setError('');
    setVerificationRequired(false);
    setRetryPending(false);
    setOpen(true);
  };
  const close = () => {
    if (saving) return;
    setRestoreFocus(true);
    setOpen(false);
  };
  const update = (key: keyof Editable, value: string) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setDirty((current) => new Set(current).add(key));
  };

  async function save() {
    if (saving || mutationBlocked) return;
    if (!draft.first_name.trim()) {
      setError('First name is required.');
      return;
    }
    if (!draft.stage.trim() || Array.from(draft.stage.trim()).length > 50) {
      setError('Stage must be between 1 and 50 characters.');
      return;
    }
    const boundedFields: readonly Readonly<{ key: keyof Editable; label: string; limit: number }>[] = [
      { key: 'first_name', label: 'First name', limit: 120 },
      { key: 'last_name', label: 'Last name', limit: 120 },
      { key: 'email', label: 'Email', limit: 255 },
      { key: 'phone', label: 'Phone', limit: 50 },
    ];
    const invalidField = boundedFields.find(({ key, limit }) => Array.from(draft[key].trim()).length > limit);
    if (invalidField) {
      setError(`${invalidField.label} must be ${invalidField.limit} characters or fewer.`);
      return;
    }
    const input = changedInput(original, draft, dirty);
    if (Object.keys(input).length === 0) {
      setRestoreFocus(true);
      setOpen(false);
      return;
    }
    if (acquireMutation && !acquireMutation()) return;
    const controller = new AbortController();
    const ownedContactId = contact.id;
    controllerRef.current = controller;
    setSaving(true);
    setError('');
    let authoritative = false;
    try {
      await api.update(contact.id, input, { signal: controller.signal });
      if (!mountedRef.current || controller.signal.aborted || controllerRef.current !== controller || contactIdRef.current !== ownedContactId) return;
      await onUpdated();
      authoritative = true;
      if (!mountedRef.current || controller.signal.aborted || controllerRef.current !== controller || contactIdRef.current !== ownedContactId) return;
      setRestoreFocus(true);
      setOpen(false);
    } catch {
      if (mountedRef.current && !controller.signal.aborted && controllerRef.current === controller && contactIdRef.current === ownedContactId) {
        setError('Mutation status is unknown. Current contact data is being refreshed.');
        try {
          await onUpdated();
          authoritative = true;
          if (mountedRef.current && !controller.signal.aborted && controllerRef.current === controller && contactIdRef.current === ownedContactId) {
            setError('Mutation status is unknown. Current contact data was refreshed.');
          }
        } catch {
          if (mountedRef.current && !controller.signal.aborted && controllerRef.current === controller && contactIdRef.current === ownedContactId) {
            setError('Mutation status is unknown. Current contact data could not be verified.');
            setVerificationRequired(true);
          }
        }
      }
    } finally {
      if (authoritative && mountedRef.current && !controller.signal.aborted && controllerRef.current === controller && contactIdRef.current === ownedContactId) {
        controllerRef.current = null;
        setSaving(false);
        releaseMutation?.();
      }
    }
  }

  async function retryVerification() {
    if (!verificationRequired || !saving || retryPending) return;
    const controller = controllerRef.current;
    const ownedContactId = contact.id;
    if (!controller || controller.signal.aborted) return;
    setRetryPending(true);
    setError('Mutation status is unknown. Current contact data is being refreshed.');
    try {
      await onUpdated();
      if (!mountedRef.current || controller.signal.aborted || controllerRef.current !== controller || contactIdRef.current !== ownedContactId) return;
      controllerRef.current = null;
      setSaving(false);
      setVerificationRequired(false);
      setRetryPending(false);
      setError('Mutation status is unknown. Current contact data was refreshed.');
      releaseMutation?.();
    } catch {
      if (mountedRef.current && !controller.signal.aborted && controllerRef.current === controller && contactIdRef.current === ownedContactId) {
        setError('Mutation status is unknown. Current contact data could not be verified.');
        setRetryPending(false);
      }
    }
  }

  if (!open) {
    return (
      <button ref={triggerRef} type="button" className="command-secondary-button command-touch-target command-print-hidden" disabled={mutationBlocked} onClick={begin}>
        <PencilSimple aria-hidden="true" size={15} />
        Edit profile
      </button>
    );
  }

  return (
    <section className="command-contact-editor" aria-label="Edit SWS profile" onKeyDown={(event) => { if (event.key === 'Escape' && !saving) { event.preventDefault(); close(); } }}>
      <div className="command-contact-editor-heading">
        <h3>Edit SWS profile</h3>
        <button
          type="button"
          className="command-touch-target"
          aria-label="Close profile editor"
          disabled={saving}
          onClick={close}
        ><X aria-hidden="true" size={17} /></button>
      </div>
      <div className="command-contact-editor-fields">
        <label>First name<input aria-label="First name" disabled={saving} value={draft.first_name} onChange={(event) => update('first_name', event.target.value)} /></label>
        <label>Last name<input aria-label="Last name" disabled={saving} value={draft.last_name} onChange={(event) => update('last_name', event.target.value)} /></label>
        <label>Email<input aria-label="Email" disabled={saving} value={draft.email} onChange={(event) => update('email', event.target.value)} /></label>
        <label>Phone<input aria-label="Phone" disabled={saving} value={draft.phone} onChange={(event) => update('phone', event.target.value)} /></label>
        <label>Stage<input aria-label="Stage" disabled={saving} value={draft.stage} onChange={(event) => update('stage', event.target.value)} /></label>
        <label>Birthday<input aria-label="Birthday" disabled={saving} type="date" value={draft.birthday} onChange={(event) => update('birthday', event.target.value)} /></label>
        <label>Anniversary<input aria-label="Anniversary" disabled={saving} type="date" value={draft.anniversary} onChange={(event) => update('anniversary', event.target.value)} /></label>
      </div>
      {error ? <p role="alert" className="command-contacts-form-error">{error}</p> : null}
      {verificationRequired ? <button type="button" className="command-secondary-button command-touch-target" disabled={retryPending} onClick={() => void retryVerification()}>{retryPending ? 'Refreshing…' : 'Retry contact refresh'}</button> : null}
      <button type="button" className="command-primary-button command-touch-target" disabled={saving} onClick={() => void save()}>
        <FloppyDisk aria-hidden="true" size={15} />
        {saving ? 'Saving…' : 'Save profile'}
      </button>
    </section>
  );
}
