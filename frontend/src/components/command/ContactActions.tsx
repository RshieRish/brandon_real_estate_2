'use client';

import { FloppyDisk, NotePencil, Tag, X } from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';
import type { ContactsApi } from '@/lib/command/contacts';

type Mode = 'note' | 'search' | 'tag' | null;
type ChangedSurface = 'note' | 'search' | 'tag';

export function ContactActions({
  contactId,
  api,
  onChanged,
  mutationBlocked = false,
  acquireMutation,
  releaseMutation,
}: Readonly<{
  contactId: number;
  api: ContactsApi;
  onChanged: (surface: ChangedSurface, outcome: 'success' | 'uncertain' | 'error') => Promise<void>;
  mutationBlocked?: boolean;
  acquireMutation?: () => boolean;
  releaseMutation?: () => void;
}>) {
  const [mode, setMode] = useState<Mode>(null);
  const [value, setValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [verificationRequired, setVerificationRequired] = useState(false);
  const [retryPending, setRetryPending] = useState(false);
  const [restoreFocus, setRestoreFocus] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const actionKeyRef = useRef(0);
  const mountedRef = useRef(true);
  const contactIdRef = useRef(contactId);
  contactIdRef.current = contactId;

  useEffect(() => {
    if (mode === null && restoreFocus) {
      openerRef.current?.focus();
      setRestoreFocus(false);
    }
  }, [mode, restoreFocus]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const controller = controllerRef.current;
      controllerRef.current = null;
      actionKeyRef.current += 1;
      controller?.abort();
      releaseMutation?.();
    };
  }, [releaseMutation]);
  useEffect(() => {
    const controller = controllerRef.current;
    controllerRef.current = null;
    controller?.abort();
    actionKeyRef.current += 1;
    releaseMutation?.();
    setMode(null);
    setSaving(false);
    setError('');
    setVerificationRequired(false);
    setRetryPending(false);
    setRestoreFocus(false);
  }, [contactId, releaseMutation]);

  const label = mode === 'note' ? 'Add note' : mode === 'search' ? 'Save search' : 'Add tag';
  const open = (next: Exclude<Mode, null>, opener: HTMLButtonElement) => {
    if (saving || mutationBlocked) return;
    openerRef.current = opener;
    setMode(next);
    setValue('');
    setError('');
    setVerificationRequired(false);
    setRetryPending(false);
  };
  const close = () => {
    if (saving) return;
    setRestoreFocus(true);
    setMode(null);
  };

  async function save() {
    const trimmed = value.trim();
    if (!mode || !trimmed || saving || mutationBlocked) return;
    const limit = mode === 'note' ? 20_000 : mode === 'search' ? 255 : 80;
    if (Array.from(trimmed).length > limit) {
      setError(`${mode === 'note' ? 'Note' : mode === 'search' ? 'Saved search name' : 'Tag name'} must be ${limit.toLocaleString()} characters or fewer.`);
      return;
    }
    if (acquireMutation && !acquireMutation()) return;
    const controller = new AbortController();
    const actionKey = actionKeyRef.current + 1;
    actionKeyRef.current = actionKey;
    controllerRef.current = controller;
    setSaving(true);
    setError('');
    const current = () => (
      !controller.signal.aborted
      && mountedRef.current
      && controllerRef.current === controller
      && actionKeyRef.current === actionKey
      && contactIdRef.current === contactId
    );

    let authoritative = false;
    try {
      if (mode === 'note') {
        await api.createNote(contactId, { body: trimmed }, { signal: controller.signal });
        if (!current()) return;
        await onChanged('note', 'success');
        if (!current()) return;
      } else if (mode === 'search') {
        await api.createSavedSearch(contactId, {
          name: trimmed,
          criteria: { contact_id: contactId, scope: 'contact_workspace', saved_from: 'command' },
        }, { signal: controller.signal });
        if (!current()) return;
        await onChanged('search', 'success');
        if (!current()) return;
      } else {
        const tag = await api.createTag({ name: trimmed }, { signal: controller.signal });
        if (!current()) return;
        try {
          await api.assignTag(contactId, tag.id, { signal: controller.signal });
        } catch {
          if (!current()) return;
          setError('Tag assignment status is unknown. Current contact data is being refreshed.');
          try {
            await onChanged('tag', 'uncertain');
            authoritative = true;
            if (current()) setError('Tag assignment status is unknown. Current contact data was refreshed.');
          } catch {
            if (current()) {
              setError('Tag assignment status is unknown. Current contact data could not be verified.');
              setVerificationRequired(true);
            }
          }
          return;
        }
        if (!current()) return;
        await onChanged('tag', 'success');
        authoritative = true;
        if (!current()) return;
      }
      authoritative = true;
      setRestoreFocus(true);
      setMode(null);
      setValue('');
    } catch {
      if (!current()) return;
      setError('Mutation status is unknown. Current contact data is being refreshed.');
      try {
        await onChanged(mode, 'error');
        authoritative = true;
        if (current()) setError('Mutation status is unknown. Current contact data was refreshed.');
      } catch {
        if (current()) {
          setError('Mutation status is unknown. Current contact data could not be verified.');
          setVerificationRequired(true);
        }
      }
    } finally {
      if (authoritative && current()) {
        controllerRef.current = null;
        setSaving(false);
        releaseMutation?.();
      }
    }
  }

  async function retryVerification() {
    if (!mode || !verificationRequired || !saving || retryPending) return;
    const controller = controllerRef.current;
    if (!controller || controller.signal.aborted) return;
    setRetryPending(true);
    setError('Mutation status is unknown. Current contact data is being refreshed.');
    try {
      await onChanged(mode, 'error');
      if (!mountedRef.current || controller.signal.aborted || controllerRef.current !== controller || contactIdRef.current !== contactId) return;
      controllerRef.current = null;
      setSaving(false);
      setVerificationRequired(false);
      setRetryPending(false);
      setError('Mutation status is unknown. Current contact data was refreshed.');
      releaseMutation?.();
    } catch {
      if (mountedRef.current && !controller.signal.aborted && controllerRef.current === controller && contactIdRef.current === contactId) {
        setError('Mutation status is unknown. Current contact data could not be verified.');
        setRetryPending(false);
      }
    }
  }

  return (
    <div className="command-contact-actions command-print-hidden">
      <div className="command-contact-action-buttons">
        <button type="button" className="command-secondary-button command-touch-target" disabled={mutationBlocked} onClick={(event) => open('note', event.currentTarget)}><NotePencil aria-hidden="true" size={15} />Add note</button>
        <button type="button" className="command-secondary-button command-touch-target" disabled={mutationBlocked} onClick={(event) => open('search', event.currentTarget)}>Save search</button>
        <button type="button" className="command-secondary-button command-touch-target" disabled={mutationBlocked} onClick={(event) => open('tag', event.currentTarget)}><Tag aria-hidden="true" size={15} />Add tag</button>
      </div>
      {mode ? (
        <section className="command-contact-action-form" aria-label={label} onKeyDown={(event) => { if (event.key === 'Escape' && !saving) { event.preventDefault(); close(); } }}>
          <div><h3>{label}</h3><button type="button" className="command-touch-target" aria-label="Close contact action" disabled={saving} onClick={close}><X aria-hidden="true" size={16} /></button></div>
          {mode === 'note' ? (
            <textarea aria-label="Note body" autoFocus disabled={saving} value={value} onChange={(event) => setValue(event.target.value)} />
          ) : (
            <input aria-label={mode === 'search' ? 'Saved search name' : 'Tag name'} autoFocus disabled={saving} value={value} onChange={(event) => setValue(event.target.value)} />
          )}
          {error ? <p role="alert" className="command-contacts-form-error">{error}</p> : null}
          {verificationRequired ? <button type="button" className="command-secondary-button command-touch-target" disabled={retryPending} onClick={() => void retryVerification()}>{retryPending ? 'Refreshing…' : 'Retry contact refresh'}</button> : null}
          <button type="button" className="command-primary-button command-touch-target" disabled={!value.trim() || saving} onClick={() => void save()}>
            <FloppyDisk aria-hidden="true" size={15} />
            {saving ? 'Saving…' : mode === 'note' ? 'Save note' : mode === 'search' ? 'Save search' : 'Add tag'}
          </button>
        </section>
      ) : null}
    </div>
  );
}
