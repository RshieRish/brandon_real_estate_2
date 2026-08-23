'use client';

import {
  ArrowClockwise,
  Check,
  CheckCircle,
  ClockCountdown,
  EnvelopeSimple,
  FloppyDisk,
  LinkBreak,
  ListChecks,
  PaperPlaneTilt,
  ShieldCheck,
  Sparkle,
  WarningCircle,
  XCircle,
} from '@phosphor-icons/react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { ChangeEvent } from 'react';
import { CommandStatePanel } from './ui/CommandStatePanel';
import {
  consumeTaskSuggestionHandoffBootstrap,
  isSuggestionStaleError,
  taskSuggestionsApi,
  type ApprovalPrepare,
  type TaskSuggestion,
  type TaskSuggestionBlocker,
  type TaskSuggestionAuditEvent,
  type TaskSuggestionEditRequest,
  type TaskSuggestionPreview,
} from '@/lib/command/task-suggestions';

const spring = { type: 'spring' as const, stiffness: 100, damping: 20 };
const panelClass =
  'relative overflow-hidden rounded-[28px] border border-white/10 bg-white/[0.045] shadow-[inset_0_1px_0_rgba(255,255,255,0.09),0_28px_80px_rgba(0,0,0,0.32)] backdrop-blur-xl';
const fieldClass =
  'command-touch-target w-full rounded-2xl border border-white/10 bg-black/30 px-4 py-3 text-sm text-white outline-none transition focus:border-[#eac469] focus:ring-2 focus:ring-[#eac469]/20 disabled:cursor-not-allowed disabled:opacity-50';
const secondaryButtonClass =
  'command-touch-target inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-white/15 bg-white/[0.06] px-4 py-2.5 text-sm font-bold text-white transition hover:border-[#eac469]/55 hover:bg-[#eac469]/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#eac469] disabled:cursor-not-allowed disabled:opacity-40';
const primaryButtonClass =
  'command-touch-target inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[#eac469] px-5 py-2.5 text-sm font-black text-[#0a0a0a] transition hover:bg-[#f3d68e] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white disabled:cursor-not-allowed disabled:bg-[#eac469]/35 disabled:text-black/50';

const blockerLabels: Readonly<Record<TaskSuggestionBlocker, string>> = {
  missing_required_field: 'Task details need an explicit decision',
  ambiguous_due_at: 'Due date needs review',
  ambiguous_contact: 'Contact match needs review',
  multiple_actions: 'The source may contain multiple actions',
  unsupported_owner: 'Requested owner is not supported',
  unsupported_link: 'Requested linked record is not supported',
};

const auditEventLabels: Readonly<Record<TaskSuggestionAuditEvent['event_type'], string>> = {
  edit: 'Edited',
  clarification_asked: 'Clarification asked',
  clarification_answered: 'Clarification answered',
  clarification_timed_out: 'Clarification timed out',
  clarification_superseded: 'Clarification superseded',
  clarification_delivery_retry: 'Clarification delivery retried',
  dismiss: 'Dismissed',
  preview: 'Previewed',
  approve: 'Approved',
  apply: 'Applied to CRM',
  reprocess: 'Reprocessed',
  dismiss_proposed: 'Dismissal proposed',
};

const auditActorLabels: Readonly<Record<TaskSuggestionAuditEvent['actor_type'], string>> = {
  system: 'system',
  sydney: 'Sydney',
  command_admin: 'Command admin',
  untrusted_hermes_input: 'untrusted Hermes input',
};

type ResolutionChoices = Readonly<{
  resolve_owner_as_brandon: boolean;
  create_without_unsupported_link: boolean;
  accept_current_task_details: boolean;
  treat_as_single_action: boolean;
  confirm_not_duplicate: boolean;
}>;

const emptyResolutions: ResolutionChoices = {
  resolve_owner_as_brandon: false,
  create_without_unsupported_link: false,
  accept_current_task_details: false,
  treat_as_single_action: false,
  confirm_not_duplicate: false,
};

function sourceLabel(source: TaskSuggestion['source_type']): string {
  return source === 'gmail_message' ? 'Gmail review' : 'Sydney draft';
}

function stateLabel(suggestion: TaskSuggestion): string {
  if (suggestion.state === 'possible_duplicate') return 'Possible duplicate';
  if (suggestion.state === 'needs_clarification') return 'Needs clarification';
  if (suggestion.state === 'pending_review') return 'Ready for review';
  if (suggestion.state === 'applied') return 'Task created';
  return suggestion.state.charAt(0).toUpperCase() + suggestion.state.slice(1);
}

function dateTimeLocalValue(value: string | null): string {
  if (value === null) return '';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function dueAtPayload(value: string): string | null {
  if (value.trim() === '') return null;
  return new Date(value).toISOString();
}

function messageForError(error: unknown): string {
  if (error instanceof Error && error.message === 'Administrator session required') {
    return 'Administrator session required';
  }
  return 'The review service did not return a safe response. Refresh and try again.';
}

function mergeSuggestion(
  suggestions: readonly TaskSuggestion[],
  next: TaskSuggestion,
): readonly TaskSuggestion[] {
  const existing = suggestions.findIndex((suggestion) => suggestion.id === next.id);
  if (existing === -1) return [next, ...suggestions];
  return suggestions.map((suggestion) => (suggestion.id === next.id ? next : suggestion));
}

function suggestionVersion(suggestion: TaskSuggestion) {
  return {
    expected_version: suggestion.version,
    expected_payload_hash: suggestion.payload_hash,
  };
}

function ResolutionControl({
  checked,
  label,
  onChange,
  disabled = false,
}: {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex min-h-11 cursor-pointer items-start gap-3 rounded-2xl border border-[#eac469]/20 bg-[#eac469]/[0.06] px-4 py-3 text-sm text-white/80 transition hover:border-[#eac469]/50">
      <input
        type="checkbox"
        className="mt-0.5 size-5 accent-[#eac469]"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

function PreviewCard({ preview }: { preview: TaskSuggestionPreview }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      transition={spring}
      className="rounded-[24px] border border-[#eac469]/25 bg-[#eac469]/[0.07] p-5"
      aria-labelledby="task-suggestion-preview-title"
    >
      <div className="flex items-center gap-2 text-[#eac469]">
        <ShieldCheck aria-hidden="true" size={21} weight="fill" />
        <h3 id="task-suggestion-preview-title" className="text-sm font-black uppercase tracking-[0.16em]">
          Final task preview
        </h3>
      </div>
      <p className="mt-4 text-lg font-black text-white">{preview.task.title}</p>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-white/65">
        {preview.task.description || 'No description'}
      </p>
      <dl className="mt-5 grid gap-3 text-xs sm:grid-cols-2">
        <div>
          <dt className="uppercase tracking-[0.14em] text-white/40">Priority</dt>
          <dd className="mt-1 font-bold capitalize text-white">{preview.task.priority}</dd>
        </div>
        <div>
          <dt className="uppercase tracking-[0.14em] text-white/40">Contact</dt>
          <dd className="mt-1 font-bold text-white">
            {preview.task.contact_id === null ? 'No contact' : `Contact ${preview.task.contact_id}`}
          </dd>
        </div>
      </dl>
      <div className="mt-5 border-t border-white/10 pt-4">
        <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-white/40">
          Payload hash
        </span>
        <code className="mt-1 block break-all font-mono text-[11px] text-[#eac469]">
          {preview.payload_hash}
        </code>
      </div>
    </motion.section>
  );
}

export function TaskSuggestionsWorkspace({
  initialSuggestionId = null,
  initialSecurityError = null,
}: {
  initialSuggestionId?: string | null;
  initialSecurityError?: 'query_secret' | null;
}) {
  const [suggestions, setSuggestions] = useState<readonly TaskSuggestion[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(initialSuggestionId);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [acknowledgement, setAcknowledgement] = useState<string | null>(null);
  const [preview, setPreview] = useState<TaskSuggestionPreview | null>(null);
  const [approval, setApproval] = useState<ApprovalPrepare | null>(null);
  const [approvalSource, setApprovalSource] = useState<'command' | 'handoff' | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<TaskSuggestion['priority']>('normal');
  const [dueAt, setDueAt] = useState('');
  const [contactId, setContactId] = useState('');
  const [dismissalReason, setDismissalReason] = useState('');
  const [resolutions, setResolutions] = useState<ResolutionChoices>(emptyResolutions);
  const [focusTarget, setFocusTarget] = useState<'review' | 'notice' | 'success' | 'queue' | null>(null);
  const reviewHeadingRef = useRef<HTMLHeadingElement>(null);
  const queueHeadingRef = useRef<HTMLHeadingElement>(null);
  const noticeRef = useRef<HTMLParagraphElement>(null);
  const successRef = useRef<HTMLParagraphElement>(null);
  const capturedHandoffRef = useRef<ReturnType<typeof consumeTaskSuggestionHandoffBootstrap> | null>(null);
  const approvalRequestIdRef = useRef<string | null>(null);

  const selected = useMemo(
    () => suggestions.find((suggestion) => suggestion.id === selectedId) ?? null,
    [selectedId, suggestions],
  );
  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  useLayoutEffect(() => {
    if (selected === null) return;
    setTitle(selected.title);
    setDescription(selected.description);
    setPriority(selected.priority);
    setDueAt(dateTimeLocalValue(selected.due_at));
    setContactId(selected.contact_id === null ? '' : String(selected.contact_id));
    setDismissalReason('');
    setResolutions(emptyResolutions);
  }, [selected]);

  const applyRequestedFocus = useCallback(() => {
    if (focusTarget === null) return;
    const target = focusTarget === 'review'
      ? reviewHeadingRef.current
      : focusTarget === 'notice'
        ? noticeRef.current
        : focusTarget === 'success'
          ? successRef.current
          : queueHeadingRef.current;
    if (target === null) return;
    if (focusTarget === 'review' && target.textContent !== selected?.title) return;
    target.focus();
    setFocusTarget(null);
  }, [focusTarget, selected?.title]);

  useLayoutEffect(() => {
    applyRequestedFocus();
  }, [acknowledgement, applyRequestedFocus, selected?.id, selected?.version]);

  const loadQueue = useCallback(async (focusReview: boolean) => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await taskSuggestionsApi.list();
      setSuggestions(result.suggestions);
      const preferred = result.suggestions.find((row) => row.id === initialSuggestionId);
      const nextId = preferred?.id ?? result.suggestions[0]?.id ?? null;
      setSelectedId(nextId);
      setLoading(false);
      if (focusReview && nextId !== null) setFocusTarget('review');
    } catch (error) {
      setLoading(false);
      setLoadError(messageForError(error));
    }
  }, [initialSuggestionId]);

  useEffect(() => {
    if (capturedHandoffRef.current === null) {
      capturedHandoffRef.current = consumeTaskSuggestionHandoffBootstrap();
    }
    const captured = capturedHandoffRef.current;
    if (initialSecurityError === 'query_secret' || captured.invalid_query_secret) {
      setLoading(false);
      setLoadError(
        'Approval secrets are not accepted in the query string. Open a fresh fragment-only link.',
      );
      return;
    }
    if (captured.invalid_handoff) {
      setLoading(false);
      setLoadError('The Sydney handoff is malformed or incomplete. Request a fresh link.');
      return;
    }
    if (captured.handoff !== null && !localStorage.getItem('admin_token')?.trim()) {
      setLoading(false);
      setLoadError('Sign in, then reopen the unused Sydney link to continue.');
      return;
    }

    let active = true;
    async function initialize() {
      try {
        const listPromise = taskSuggestionsApi.list();
        const directPromise = initialSuggestionId === null
          ? Promise.resolve<TaskSuggestion | null>(null)
          : taskSuggestionsApi.get(initialSuggestionId);
        const [list, direct] = await Promise.all([listPromise, directPromise]);
        if (!active) return;
        const rows = direct === null ? list.suggestions : mergeSuggestion(list.suggestions, direct);
        const chosen = direct ?? rows[0] ?? null;
        setSuggestions(rows);
        setSelectedId(chosen?.id ?? null);
        if (captured.handoff !== null) {
          if (chosen === null || chosen.id !== initialSuggestionId) {
            throw new Error('Handoff suggestion unavailable');
          }
          const prepared = await taskSuggestionsApi.exchangeHandoff(chosen.id, {
            ...suggestionVersion(chosen),
            handoff: captured.handoff,
          });
          if (!active) return;
          setPreview(prepared);
          setApproval(prepared);
          setApprovalSource('handoff');
          approvalRequestIdRef.current = null;
        }
        setLoading(false);
      } catch (error) {
        if (!active) return;
        setLoading(false);
        setLoadError(messageForError(error));
      }
    }
    void initialize();
    return () => {
      active = false;
    };
  }, [initialSecurityError, initialSuggestionId]);

  function selectSuggestion(id: string) {
    setSelectedId(id);
    setActionError(null);
    setAcknowledgement(null);
    setPreview(null);
    setApproval(null);
    setApprovalSource(null);
    approvalRequestIdRef.current = null;
    setFocusTarget('review');
  }

  function setResolution(key: keyof ResolutionChoices, checked: boolean) {
    setResolutions((current) => ({ ...current, [key]: checked }));
  }

  const formEditable = selected !== null && [
    'pending_review',
    'needs_clarification',
    'possible_duplicate',
  ].includes(selected.state);
  const titleValid = title.trim().length >= 1 && title.trim().length <= 255;
  const contactIdValid = contactId.trim() === '' || (
    /^[1-9][0-9]*$/.test(contactId.trim())
    && Number(contactId.trim()) <= 2_147_483_647
  );
  const formValid = titleValid && contactIdValid;

  const editPayload = useMemo<TaskSuggestionEditRequest | null>(() => {
    if (selected === null || !formEditable || !formValid) return null;
    const payload: Record<string, unknown> = suggestionVersion(selected);
    if (title.trim() !== selected.title) payload.title = title.trim();
    if (description !== selected.description) payload.description = description;
    if (priority !== selected.priority) payload.priority = priority;
    const originalDueAt = dateTimeLocalValue(selected.due_at);
    if (dueAt !== originalDueAt) payload.due_at = dueAtPayload(dueAt);
    const originalContact = selected.contact_id === null ? '' : String(selected.contact_id);
    if (contactId.trim() !== originalContact) {
      payload.contact_id = contactId.trim() === '' ? null : Number(contactId);
    }
    for (const [key, value] of Object.entries(resolutions)) {
      if (value) payload[key] = true;
    }
    return Object.keys(payload).length > 2
      ? payload as TaskSuggestionEditRequest
      : null;
  }, [contactId, description, dueAt, formEditable, formValid, priority, resolutions, selected, title]);

  function isCurrentSuggestion(suggestion: TaskSuggestion): boolean {
    const current = selectedRef.current;
    return current !== null
      && current.id === suggestion.id
      && current.version === suggestion.version
      && current.payload_hash === suggestion.payload_hash;
  }

  async function refetchStale(suggestion: TaskSuggestion) {
    setPreview(null);
    setApproval(null);
    setApprovalSource(null);
    approvalRequestIdRef.current = null;
    try {
      const fresh = await taskSuggestionsApi.get(suggestion.id);
      setSuggestions((current) => mergeSuggestion(current, fresh));
      setActionError(null);
      setAcknowledgement('This suggestion changed elsewhere. Review the fresh version.');
      setFocusTarget('notice');
    } catch {
      setActionError('The suggestion changed, but the fresh version could not be loaded.');
    }
  }

  async function runSuggestionAction(
    actionName: string,
    action: (current: TaskSuggestion) => Promise<void>,
  ) {
    if (selected === null || busyAction !== null) return;
    setBusyAction(actionName);
    setActionError(null);
    setAcknowledgement(null);
    try {
      await action(selected);
    } catch (error) {
      if (isSuggestionStaleError(error)) await refetchStale(selected);
      else setActionError(messageForError(error));
    } finally {
      setBusyAction(null);
    }
  }

  async function saveChanges() {
    if (editPayload === null || !formValid || !formEditable) return;
    await runSuggestionAction('save', async (current) => {
      const updated = await taskSuggestionsApi.edit(current.id, editPayload);
      setSuggestions((rows) => mergeSuggestion(rows, updated));
      setPreview(null);
      setApproval(null);
      setApprovalSource(null);
      approvalRequestIdRef.current = null;
      setAcknowledgement('Review changes saved');
      setFocusTarget('notice');
    });
  }

  async function showPreview() {
    await runSuggestionAction('preview', async (current) => {
      setPreview(null);
      setApproval(null);
      setApprovalSource(null);
      approvalRequestIdRef.current = null;
      const nextPreview = await taskSuggestionsApi.preview(current.id, suggestionVersion(current));
      if (!isCurrentSuggestion(current)) return;
      setPreview(nextPreview);
      setAcknowledgement('Final preview refreshed');
    });
  }

  async function prepareApproval() {
    await runSuggestionAction('prepare', async (current) => {
      setPreview(null);
      setApproval(null);
      setApprovalSource(null);
      approvalRequestIdRef.current = null;
      const prepared = await taskSuggestionsApi.prepareApproval(
        current.id,
        suggestionVersion(current),
      );
      if (!isCurrentSuggestion(current)) return;
      setPreview(prepared);
      setApproval(prepared);
      setApprovalSource('command');
    });
  }

  async function approveTask() {
    if (approval === null) return;
    await runSuggestionAction('approve', async (current) => {
      const requestId = approvalRequestIdRef.current ?? crypto.randomUUID();
      approvalRequestIdRef.current = requestId;
      const result = await taskSuggestionsApi.approve(current.id, {
        ...suggestionVersion(current),
        approval: approval.approval,
        request_id: requestId,
        client_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
      });
      if (
        result.suggestion_id !== current.id
        || result.suggestion_version !== current.version + 1
        || result.request_id !== requestId
      ) {
        throw new Error('Approval response did not match the submitted suggestion');
      }
      let applied: TaskSuggestion = {
        ...current,
        state: 'applied',
        blocker_codes: [],
        resolution_requirements: [],
        applied_task_id: result.task_id,
        version: result.suggestion_version,
        audit_trail: [],
      };
      try {
        const authoritative = await taskSuggestionsApi.get(current.id);
        if (
          authoritative.id === current.id
          && authoritative.version >= result.suggestion_version
          && authoritative.state === 'applied'
          && authoritative.applied_task_id === result.task_id
        ) {
          applied = authoritative;
        }
      } catch {
        // The approval ACK is authoritative; keep the safe terminal fallback without stale audit data.
      }
      setSuggestions((rows) => mergeSuggestion(rows, applied));
      setApproval(null);
      setApprovalSource(null);
      approvalRequestIdRef.current = null;
      setAcknowledgement(`Task ${result.task_id} created`);
      setFocusTarget('success');
    });
  }

  async function dismissSuggestion() {
    const reason = dismissalReason.trim();
    if (reason === '') return;
    await runSuggestionAction('dismiss', async (current) => {
      const dismissed = await taskSuggestionsApi.dismiss(current.id, {
        ...suggestionVersion(current),
        reason,
      });
      setSuggestions((rows) => mergeSuggestion(rows, dismissed));
      setPreview(null);
      setApproval(null);
      setApprovalSource(null);
      approvalRequestIdRef.current = null;
      setAcknowledgement('Suggestion dismissed');
      setFocusTarget('queue');
    });
  }

  const approvalReady = selected !== null
    && selected.state === 'pending_review'
    && selected.blocker_codes.length === 0
    && selected.resolution_requirements.length === 0
    && (selected.clarification_state === 'not_required'
      || selected.clarification_state === 'answered');
  const artifactsAreCurrent = selected !== null
    && preview !== null
    && preview.suggestion_id === selected.id
    && preview.suggestion_version === selected.version
    && preview.payload_hash === selected.payload_hash;
  const preparedApprovalIsUsable = approvalReady
    && formValid
    && editPayload === null
    && approval !== null
    && artifactsAreCurrent;

  return (
    <div className="relative min-h-[100dvh] overflow-hidden bg-[#080807] text-white">
      <div className="halftone pointer-events-none absolute -right-24 top-20 h-80 w-80 opacity-[0.055]" />
      <div className="pointer-events-none absolute left-[12%] top-[-12rem] h-[34rem] w-[34rem] rounded-full bg-[#eac469]/[0.07] blur-[120px]" />
      <header className="relative border-b border-white/10 px-5 py-8 sm:px-8 lg:px-12 lg:py-10">
        <div className="mx-auto flex max-w-[1500px] flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-[#eac469]">
              <Sparkle aria-hidden="true" size={18} weight="fill" />
              <p className="text-xs font-black uppercase tracking-[0.24em]">Sydney intelligence desk</p>
            </div>
            <h1 className="mt-3 max-w-3xl text-3xl font-black tracking-[-0.035em] sm:text-4xl lg:text-5xl">
              Task suggestion review
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-white/55 sm:text-base">
              Turn email obligations and Sydney drafts into deliberate, attributable CRM work.
            </p>
          </div>
          <div className="flex items-center gap-3 rounded-2xl border border-[#eac469]/20 bg-[#eac469]/[0.06] px-4 py-3">
            <ShieldCheck aria-hidden="true" size={24} className="text-[#eac469]" />
            <div>
              <p className="text-xs font-black uppercase tracking-[0.14em] text-[#eac469]">Approval gate</p>
              <p className="text-xs text-white/55">No task is created before your final click.</p>
            </div>
          </div>
        </div>
      </header>

      <main className="relative mx-auto max-w-[1500px] px-5 py-7 sm:px-8 lg:px-12 lg:py-10">
        {loadError !== null ? (
          <div className="mx-auto max-w-3xl">
            {loadError.startsWith('The review service') ? (
              <CommandStatePanel
                kind="error"
                title="Task suggestions unavailable"
                message={loadError}
                actionLabel="Try again"
                onAction={() => void loadQueue(true)}
              />
            ) : (
              <section role="alert" className={`${panelClass} p-6`}>
                <WarningCircle aria-hidden="true" size={26} className="text-[#eac469]" />
                <h2 className="mt-4 text-xl font-black">Task suggestions unavailable</h2>
                <p className="mt-2 text-sm leading-6 text-white/60">{loadError}</p>
              </section>
            )}
          </div>
        ) : loading ? (
          <CommandStatePanel
            kind="loading"
            title="Loading task suggestions"
            message="Opening the authenticated review ledger."
          />
        ) : suggestions.length === 0 ? (
          <div className="mx-auto max-w-3xl">
            {acknowledgement !== null ? (
              <p className="mb-4 rounded-2xl border border-emerald-400/25 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100" role="status">
                {acknowledgement}
              </p>
            ) : null}
            <CommandStatePanel
              kind="empty"
              title="Review queue is clear"
              message="New Gmail obligations and Sydney drafts will appear here after intake."
            />
          </div>
        ) : (
          <div className="grid items-start gap-6 lg:grid-cols-[minmax(270px,0.68fr)_minmax(0,1.55fr)]">
            <section
              className={`${panelClass} p-4 sm:p-5 lg:sticky lg:top-24`}
              aria-label="Task suggestion queue"
            >
              <div className="mb-4 flex items-center justify-between gap-4">
                <div>
                  <p className="text-[10px] font-black uppercase tracking-[0.2em] text-[#eac469]">Decision ledger</p>
                  <h2 ref={queueHeadingRef} tabIndex={-1} className="mt-1 text-xl font-black outline-none">
                    Review queue
                  </h2>
                </div>
                <span className="rounded-full border border-white/10 bg-black/25 px-3 py-1 font-mono text-xs text-white/55">
                  {suggestions.length}
                </span>
              </div>
              <div className="space-y-2 [content-visibility:auto]">
                {suggestions.map((suggestion, index) => {
                  const isSelected = suggestion.id === selectedId;
                  return (
                    <motion.button
                      key={suggestion.id}
                      type="button"
                      initial={{ opacity: 0, x: -12 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ ...spring, delay: index * 0.035 }}
                      aria-label={`Review ${suggestion.title}`}
                      aria-pressed={isSelected}
                      disabled={busyAction !== null}
                      onClick={() => selectSuggestion(suggestion.id)}
                      className={`command-touch-target w-full rounded-2xl border p-4 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-[#eac469] ${isSelected ? 'border-[#eac469]/55 bg-[#eac469]/[0.11]' : 'border-white/8 bg-black/20 hover:border-white/20 hover:bg-white/[0.045]'}`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <span className="text-[10px] font-black uppercase tracking-[0.15em] text-[#eac469]">
                          {sourceLabel(suggestion.source_type)}
                        </span>
                        <span className="font-mono text-[10px] text-white/35">v{suggestion.version}</span>
                      </div>
                      <span className="mt-2 block text-sm font-bold leading-5 text-white">
                        {suggestion.title}
                      </span>
                      <span className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-white/45">
                        <span>{stateLabel(suggestion)}</span>
                        {suggestion.clarification_state === 'pending' ? (
                          <span className="rounded-full border border-[#eac469]/30 bg-[#eac469]/10 px-2 py-0.5 font-bold text-[#eac469]">
                            Sydney question pending
                          </span>
                        ) : null}
                      </span>
                    </motion.button>
                  );
                })}
              </div>
            </section>

            {selected !== null ? (
              <AnimatePresence mode="wait">
                <motion.article
                  key={`${selected.id}-${selected.version}`}
                  initial={{ opacity: 0, y: 14 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  transition={spring}
                  onAnimationComplete={applyRequestedFocus}
                  className={`${panelClass} p-5 sm:p-7 lg:p-9`}
                >
                  <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#eac469]/70 to-transparent" />
                  <div className="flex flex-col gap-5 border-b border-white/10 pb-6 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-[10px] font-black uppercase tracking-[0.14em] text-white/65">
                          {selected.source_type === 'gmail_message' ? <EnvelopeSimple aria-hidden="true" /> : <Sparkle aria-hidden="true" />}
                          {sourceLabel(selected.source_type)}
                        </span>
                        <span className="rounded-full border border-[#eac469]/25 bg-[#eac469]/10 px-3 py-1 text-[10px] font-black uppercase tracking-[0.14em] text-[#eac469]">
                          {stateLabel(selected)}
                        </span>
                      </div>
                      <h2
                        ref={reviewHeadingRef}
                        tabIndex={-1}
                        className="mt-4 text-2xl font-black tracking-[-0.025em] outline-none sm:text-3xl"
                      >
                        {selected.title}
                      </h2>
                      <p className="mt-2 text-xs text-white/40">Suggestion version {selected.version}</p>
                    </div>
                    <code className="max-w-full break-all rounded-xl border border-white/8 bg-black/25 px-3 py-2 font-mono text-[10px] leading-4 text-white/40">
                      {selected.payload_hash}
                    </code>
                  </div>

                  {acknowledgement !== null ? (
                    <p
                      ref={acknowledgement.startsWith('Task ') ? successRef : noticeRef}
                      tabIndex={-1}
                      role="status"
                      className="mt-5 rounded-2xl border border-emerald-400/25 bg-emerald-400/10 px-4 py-3 text-sm font-semibold text-emerald-100 outline-none"
                    >
                      {acknowledgement}
                    </p>
                  ) : null}
                  {actionError !== null ? (
                    <p role="alert" className="mt-5 rounded-2xl border border-red-400/25 bg-red-400/10 px-4 py-3 text-sm text-red-100">
                      {actionError}
                    </p>
                  ) : null}

                  {selected.clarification_state === 'pending' ? (
                    <div className="mt-5 flex items-start gap-3 rounded-2xl border border-[#eac469]/25 bg-[#eac469]/[0.07] p-4">
                      <PaperPlaneTilt aria-hidden="true" size={22} className="mt-0.5 shrink-0 text-[#eac469]" />
                      <div>
                        <p className="font-bold">Waiting for Sydney clarification</p>
                        <p className="mt-1 text-sm text-white/55">Approval stays locked until the active question is answered or reviewed here.</p>
                      </div>
                    </div>
                  ) : null}
                  {selected.clarification_state === 'timed_out' ? (
                    <div className="mt-5 flex items-start gap-3 rounded-2xl border border-amber-300/25 bg-amber-300/[0.07] p-4">
                      <ClockCountdown aria-hidden="true" size={22} className="mt-0.5 shrink-0 text-amber-200" />
                      <div>
                        <p className="font-bold text-amber-100">Clarification timed out</p>
                        <p className="mt-1 text-sm text-white/55">Complete the remaining fields in manual review before approval.</p>
                      </div>
                    </div>
                  ) : null}
                  {selected.clarification_state === 'manual_review_required' ? (
                    <div className="mt-5 flex items-start gap-3 rounded-2xl border border-amber-300/25 bg-amber-300/[0.07] p-4">
                      <WarningCircle aria-hidden="true" size={22} className="mt-0.5 shrink-0 text-amber-200" />
                      <div>
                        <p className="font-bold text-amber-100">Manual review required</p>
                        <p className="mt-1 text-sm text-white/55">Resolve each consequential blocker explicitly.</p>
                      </div>
                    </div>
                  ) : null}

                  <section className="mt-7 grid gap-4 lg:grid-cols-[minmax(0,0.82fr)_minmax(0,1.18fr)]" aria-label="Suggestion provenance">
                    <div className="rounded-2xl border border-white/8 bg-black/20 p-4">
                      <p className="text-[10px] font-black uppercase tracking-[0.16em] text-[#eac469]">Extraction evidence</p>
                      <p className="mt-3 text-lg font-black text-white">
                        {Math.round(selected.confidence * 100)}% confidence
                      </p>
                      <p className="mt-2 text-sm leading-6 text-white/55">
                        {selected.rationale || 'No extractor rationale was recorded.'}
                      </p>
                      <dl className="mt-4 space-y-3 border-t border-white/8 pt-4 text-xs">
                        <div>
                          <dt className="uppercase tracking-[0.12em] text-white/35">Schema</dt>
                          <dd className="mt-1 font-mono text-white/65">{selected.model_schema_version}</dd>
                        </div>
                        <div>
                          <dt className="uppercase tracking-[0.12em] text-white/35">Missing-field state</dt>
                          <dd className="mt-1 font-bold text-white/70">
                            {selected.blocker_codes.length === 0
                              ? 'No required fields missing'
                              : selected.blocker_codes.map((blocker) => blockerLabels[blocker]).join('; ')}
                          </dd>
                        </div>
                      </dl>
                    </div>
                    <div className="space-y-4">
                      <div className="rounded-2xl border border-white/8 bg-black/20 p-4">
                        <p className="text-[10px] font-black uppercase tracking-[0.16em] text-[#eac469]">Source direction and identifier</p>
                        {selected.sources.length === 0 ? (
                          <p className="mt-3 text-sm font-bold text-white/65">Direct Sydney request</p>
                        ) : (
                          <ul className="mt-3 space-y-2">
                            {selected.sources.map((source) => (
                              <li key={`${source.source_label}-${source.created_at}`} className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                                <span className="text-sm font-bold capitalize text-white/70">{source.direction.replace('_', ' ')}</span>
                                <code className="break-all font-mono text-[10px] text-white/40">{source.source_label}</code>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                      <div className="rounded-2xl border border-white/8 bg-black/20 p-4">
                        <p className="text-[10px] font-black uppercase tracking-[0.16em] text-[#eac469]">Audit trail</p>
                        {selected.audit_trail.length === 0 ? (
                          <p className="mt-3 text-sm text-white/45">No review mutations recorded yet.</p>
                        ) : (
                          <ol className="mt-3 space-y-2">
                            {selected.audit_trail.map((event) => (
                              <li key={`${event.created_at}-${event.event_type}-${event.suggestion_version}`} className="flex items-center justify-between gap-3 text-xs">
                                <span className="font-bold text-white/70">
                                  {auditEventLabels[event.event_type]} by {auditActorLabels[event.actor_type]}
                                </span>
                                <span className="shrink-0 font-mono text-white/35">v{event.suggestion_version}</span>
                              </li>
                            ))}
                          </ol>
                        )}
                      </div>
                    </div>
                  </section>

                  <div className="mt-7 grid gap-5 sm:grid-cols-2">
                    <label className="sm:col-span-2">
                      <span className="mb-2 block text-xs font-bold uppercase tracking-[0.12em] text-white/45">Task title</span>
                      <input
                        aria-label="Task title"
                        className={fieldClass}
                        value={title}
                        maxLength={255}
                        aria-invalid={formEditable && !titleValid}
                        aria-describedby={formEditable && !titleValid ? 'task-title-error' : undefined}
                        disabled={busyAction !== null || !formEditable}
                        onChange={(event) => setTitle(event.target.value)}
                      />
                      {formEditable && !titleValid ? (
                        <span id="task-title-error" className="mt-2 block text-xs text-red-200">
                          Enter a task title.
                        </span>
                      ) : null}
                    </label>
                    <label className="sm:col-span-2">
                      <span className="mb-2 block text-xs font-bold uppercase tracking-[0.12em] text-white/45">Task description</span>
                      <textarea
                        aria-label="Task description"
                        className={`${fieldClass} min-h-28 resize-y`}
                        value={description}
                        maxLength={5000}
                        disabled={busyAction !== null || !formEditable}
                        onChange={(event) => setDescription(event.target.value)}
                      />
                    </label>
                    <label>
                      <span className="mb-2 block text-xs font-bold uppercase tracking-[0.12em] text-white/45">Priority</span>
                      <select
                        aria-label="Priority"
                        className={fieldClass}
                        value={priority}
                        disabled={busyAction !== null || !formEditable}
                        onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                          setPriority(event.target.value as TaskSuggestion['priority'])}
                      >
                        <option value="low">Low</option>
                        <option value="normal">Normal</option>
                        <option value="high">High</option>
                      </select>
                    </label>
                    <label>
                      <span className="mb-2 block text-xs font-bold uppercase tracking-[0.12em] text-white/45">Due date and time</span>
                      <input
                        aria-label="Due date and time"
                        type="datetime-local"
                        className={fieldClass}
                        value={dueAt}
                        disabled={busyAction !== null || !formEditable}
                        onChange={(event) => setDueAt(event.target.value)}
                      />
                    </label>
                    <label>
                      <span className="mb-2 block text-xs font-bold uppercase tracking-[0.12em] text-white/45">Contact ID</span>
                      <input
                        aria-label="Contact ID"
                        type="number"
                        min={1}
                        max={2_147_483_647}
                        className={fieldClass}
                        value={contactId}
                        aria-invalid={formEditable && !contactIdValid}
                        aria-describedby={formEditable && !contactIdValid ? 'task-contact-error' : undefined}
                        disabled={busyAction !== null || !formEditable}
                        onChange={(event) => setContactId(event.target.value)}
                      />
                      {formEditable && !contactIdValid ? (
                        <span id="task-contact-error" className="mt-2 block text-xs text-red-200">
                          Use a whole-number Contact ID from 1 to 2147483647.
                        </span>
                      ) : null}
                    </label>
                    <div className="rounded-2xl border border-white/8 bg-black/20 px-4 py-3">
                      <span className="text-xs font-bold uppercase tracking-[0.12em] text-white/45">Owner</span>
                      <p className="mt-2 text-sm font-bold">Brandon</p>
                    </div>
                  </div>

                  {selected.blocker_codes.length > 0 || selected.resolution_requirements.length > 0 ? (
                    <section className="mt-7" aria-labelledby="task-suggestion-blockers">
                      <div className="flex items-center gap-2">
                        <LinkBreak aria-hidden="true" size={20} className="text-[#eac469]" />
                        <h3 id="task-suggestion-blockers" className="font-black">Explicit decisions</h3>
                      </div>
                      <ul className="mt-3 space-y-1 text-sm text-white/55">
                        {selected.blocker_codes.map((blocker) => <li key={blocker}>{blockerLabels[blocker]}</li>)}
                      </ul>
                      <div className="mt-4 grid gap-3">
                        {selected.resolution_requirements.includes('resolve_owner_as_brandon') ? (
                          <ResolutionControl
                            label="Assign this task to Brandon"
                            checked={resolutions.resolve_owner_as_brandon}
                            disabled={!formEditable || busyAction !== null}
                            onChange={(checked) => setResolution('resolve_owner_as_brandon', checked)}
                          />
                        ) : null}
                        {selected.resolution_requirements.includes('create_without_unsupported_link') ? (
                          <ResolutionControl
                            label="Create without the unsupported linked record"
                            checked={resolutions.create_without_unsupported_link}
                            disabled={!formEditable || busyAction !== null}
                            onChange={(checked) => setResolution('create_without_unsupported_link', checked)}
                          />
                        ) : null}
                        {selected.resolution_requirements.includes('accept_current_task_details') ? (
                          <ResolutionControl
                            label="Accept the current task details"
                            checked={resolutions.accept_current_task_details}
                            disabled={!formEditable || busyAction !== null}
                            onChange={(checked) => setResolution('accept_current_task_details', checked)}
                          />
                        ) : null}
                        {selected.resolution_requirements.includes('treat_as_single_action') ? (
                          <ResolutionControl
                            label="Treat this as one task"
                            checked={resolutions.treat_as_single_action}
                            disabled={!formEditable || busyAction !== null}
                            onChange={(checked) => setResolution('treat_as_single_action', checked)}
                          />
                        ) : null}
                        {selected.resolution_requirements.includes('confirm_not_duplicate') ? (
                          <ResolutionControl
                            label="Confirm this is not a duplicate"
                            checked={resolutions.confirm_not_duplicate}
                            disabled={!formEditable || busyAction !== null}
                            onChange={(checked) => setResolution('confirm_not_duplicate', checked)}
                          />
                        ) : null}
                      </div>
                    </section>
                  ) : null}

                  <div className="mt-7 flex flex-wrap gap-3 border-t border-white/10 pt-6">
                    <button
                      type="button"
                      className={secondaryButtonClass}
                      disabled={editPayload === null || !formValid || !formEditable || busyAction !== null}
                      onClick={() => void saveChanges()}
                    >
                      <FloppyDisk aria-hidden="true" size={18} />
                      Save review changes
                    </button>
                    <button
                      type="button"
                      className={secondaryButtonClass}
                      disabled={!approvalReady || !formValid || editPayload !== null || busyAction !== null}
                      onClick={() => void showPreview()}
                    >
                      <ListChecks aria-hidden="true" size={18} />
                      Preview final task
                    </button>
                    <button
                      type="button"
                      className={primaryButtonClass}
                      disabled={!approvalReady || !formValid || editPayload !== null || busyAction !== null}
                      onClick={() => void prepareApproval()}
                    >
                      <ShieldCheck aria-hidden="true" size={18} weight="fill" />
                      Prepare approval
                    </button>
                  </div>

                  <AnimatePresence>{artifactsAreCurrent && preview !== null ? <PreviewCard preview={preview} /> : null}</AnimatePresence>

                  {preparedApprovalIsUsable && approval !== null ? (
                    <motion.section
                      initial={{ opacity: 0, scale: 0.985 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={spring}
                      className="mt-5 flex flex-col gap-4 rounded-[24px] border border-emerald-400/25 bg-emerald-400/[0.07] p-5 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div>
                        <p className="flex items-center gap-2 font-black text-emerald-100">
                          <CheckCircle aria-hidden="true" size={20} weight="fill" />
                          {approvalSource === 'handoff' ? 'Sydney handoff verified' : 'Approval prepared'}
                        </p>
                        <p className="mt-1 text-xs text-white/50">
                          Expires {new Date(approval.expires_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}. The task still does not exist.
                        </p>
                      </div>
                      <button
                        type="button"
                        className={primaryButtonClass}
                        disabled={busyAction !== null}
                        onClick={() => void approveTask()}
                      >
                        <Check aria-hidden="true" size={19} weight="bold" />
                        Approve task
                      </button>
                    </motion.section>
                  ) : null}

                  {formEditable ? (
                    <section className="mt-8 border-t border-white/10 pt-7" aria-labelledby="dismiss-suggestion-heading">
                      <div className="flex items-center gap-2">
                        <XCircle aria-hidden="true" size={20} className="text-white/45" />
                        <h3 id="dismiss-suggestion-heading" className="font-black">Dismiss suggestion</h3>
                      </div>
                      <p className="mt-2 text-sm text-white/45">The bounded reason is saved with the source-specific suppression decision.</p>
                      <div className="mt-4 flex flex-col gap-3 sm:flex-row">
                        <input
                          aria-label="Dismissal reason"
                          className={fieldClass}
                          value={dismissalReason}
                          maxLength={500}
                          placeholder="Reason for dismissal"
                          disabled={busyAction !== null}
                          onChange={(event) => setDismissalReason(event.target.value)}
                        />
                        <button
                          type="button"
                          className={secondaryButtonClass}
                          disabled={dismissalReason.trim() === '' || busyAction !== null}
                          onClick={() => void dismissSuggestion()}
                        >
                          {busyAction === 'dismiss' ? <ArrowClockwise aria-hidden="true" className="animate-spin" /> : <XCircle aria-hidden="true" />}
                          Dismiss suggestion
                        </button>
                      </div>
                    </section>
                  ) : null}
                </motion.article>
              </AnimatePresence>
            ) : null}
          </div>
        )}
      </main>
    </div>
  );
}
