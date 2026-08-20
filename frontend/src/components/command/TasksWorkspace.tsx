'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import {
  Archive,
  ArrowCounterClockwise,
  Check,
  DotsThreeVertical,
  Plus,
  WarningCircle,
} from '@phosphor-icons/react';
import { TaskEditor } from '@/components/command/TaskEditor';
import { useFocusContainment } from '@/components/command/shell/useFocusContainment';
import { applyTaskWorkspaceView, type TaskWorkspaceView } from '@/components/command/workspaceFilters';
import {
  commandApi,
  CommandConflictError,
  CommandOutcomeUncertainError,
  currentTaskClientTimezone,
  type Agreement,
  type Contact,
  type Listing,
  type Opportunity,
  type Task,
  type TaskCreateInput,
  type TaskLifecycleRequest,
  type TaskLink,
} from '@/lib/command/api';

type LinkableRecords = {
  contact: Contact[];
  opportunity: Opportunity[];
  agreement: Agreement[];
  listing: Listing[];
};

type LifecycleVisibility = 'active' | 'archived';
type LifecycleAction = 'archive' | 'restore';

type TaskLifecycleIntent = Readonly<{
  action: LifecycleAction;
  task_id: number;
  request_id: string;
  expected_version: number;
  reason?: string;
}>;

type TaskLifecycleAttempt = Readonly<{
  intent: TaskLifecycleIntent;
  originalTask: Task;
}>;

type RefreshContext = Readonly<{
  kind: 'lifecycle';
  attempt: TaskLifecycleAttempt;
  phase: 'uncertain' | 'retry-acknowledged';
}> | Readonly<{
  kind: 'generic';
}>;

type TaskCreateAttempt = Readonly<{
  key: string;
  fingerprint: string;
  payload: TaskCreateInput;
  clientTimezone: string;
}>;

const TASK_REFRESH_REQUIRED_MESSAGE = 'Task state could not be refreshed. Refresh the page before making another task change.';

function sameTask(left: Task | undefined, right: Task): boolean {
  return left !== undefined
    && left.id === right.id
    && left.title === right.title
    && left.contact_id === right.contact_id
    && left.description === right.description
    && left.priority === right.priority
    && left.due_at === right.due_at
    && left.status === right.status
    && left.archived_at === right.archived_at
    && left.archive_reason === right.archive_reason
    && left.version === right.version;
}

function reachedDesiredState(intent: TaskLifecycleIntent, task: Task): boolean {
  if (task.version <= intent.expected_version) return false;
  return intent.action === 'archive' ? task.archived_at !== null : task.archived_at === null;
}

function apiLifecycleRequest(intent: TaskLifecycleIntent): TaskLifecycleRequest {
  const request: { request_id: string; expected_version: number; reason?: string } = {
    request_id: intent.request_id,
    expected_version: intent.expected_version,
  };
  if (intent.reason !== undefined) request.reason = intent.reason;
  return request;
}

function actionLabel(action: LifecycleAction): string {
  return action === 'archive' ? 'Archive' : 'Restore';
}

export function TasksWorkspace({
  initialView = { tab: 'all', due: 'all' },
}: {
  initialView?: TaskWorkspaceView;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [title, setTitle] = useState('');
  const [contactId, setContactId] = useState('');
  const [priority, setPriority] = useState<Task['priority']>('normal');
  const [dueAt, setDueAt] = useState('');
  const [status, setStatus] = useState<TaskWorkspaceView['tab']>(initialView.tab);
  const [dueScope, setDueScope] = useState<TaskWorkspaceView['due']>(initialView.due);
  const [visibility, setVisibility] = useState<LifecycleVisibility>('active');
  const [error, setError] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [mutationNotice, setMutationNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [links, setLinks] = useState<Record<number, readonly TaskLink[]>>({});
  const [entityType, setEntityType] = useState<keyof LinkableRecords>('opportunity');
  const [entityId, setEntityId] = useState('');
  const [records, setRecords] = useState<LinkableRecords>({
    contact: [],
    opportunity: [],
    agreement: [],
    listing: [],
  });
  const [loadingRecords, setLoadingRecords] = useState(false);
  const [editing, setEditing] = useState<Task | null>(null);
  const [mutationsLocked, setMutationsLocked] = useState(false);
  const [mutationRefreshRequired, setMutationRefreshRequired] = useState(false);
  const [refreshingTasks, setRefreshingTasks] = useState(false);
  const [creating, setCreating] = useState(false);
  const [menuTaskId, setMenuTaskId] = useState<number | null>(null);
  const [archiveCandidate, setArchiveCandidate] = useState<Task | null>(null);
  const [archiveReason, setArchiveReason] = useState('');
  const [lifecycleRetry, setLifecycleRetry] = useState<TaskLifecycleAttempt | null>(null);
  const [undoArchive, setUndoArchive] = useState<Task | null>(null);
  const [refreshContext, setRefreshContext] = useState<RefreshContext | null>(null);
  const [focusTarget, setFocusTarget] = useState<'active' | 'archived' | 'undo' | null>(null);

  const mutationPendingRef = useRef(false);
  const taskCreateAttemptRef = useRef<TaskCreateAttempt | null>(null);
  const taskReadGenerationRef = useRef(0);
  const linkReadGenerationRef = useRef(0);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuTriggerRefs = useRef(new Map<number, HTMLButtonElement>());
  const archiveDialogRef = useRef<HTMLElement>(null);
  const archiveTriggerRef = useRef<HTMLElement | null>(null);
  const activeVisibilityRef = useRef<HTMLButtonElement>(null);
  const archivedVisibilityRef = useRef<HTMLButtonElement>(null);
  const undoRef = useRef<HTMLButtonElement>(null);

  const beginTaskMutation = useCallback(() => {
    if (mutationPendingRef.current) return false;
    mutationPendingRef.current = true;
    taskReadGenerationRef.current += 1;
    linkReadGenerationRef.current += 1;
    setMutationError(null);
    setMutationNotice(null);
    setMutationRefreshRequired(false);
    setRefreshContext(null);
    setLifecycleRetry(null);
    setMutationsLocked(true);
    return true;
  }, []);

  const finishTaskMutation = useCallback(() => {
    mutationPendingRef.current = false;
    setMutationRefreshRequired(false);
    setRefreshContext(null);
    setMutationsLocked(false);
  }, []);

  const replaceTask = useCallback((replacement: Task) => {
    setTasks((current) => current.some((task) => task.id === replacement.id)
      ? current.map((task) => task.id === replacement.id ? replacement : task)
      : [...current, replacement]);
  }, []);

  const closeTransientTaskUi = useCallback(() => {
    setEditing(null);
    setSelected(null);
    setMenuTaskId(null);
    setArchiveCandidate(null);
    setArchiveReason('');
  }, []);

  const refetchAllTasks = useCallback(async (closeTransient = false): Promise<readonly Task[] | null> => {
    const generation = taskReadGenerationRef.current + 1;
    taskReadGenerationRef.current = generation;
    try {
      const rows = await commandApi.tasks({ visibility: 'all' });
      if (taskReadGenerationRef.current !== generation) return null;
      const authoritative = [...rows];
      setTasks(authoritative);
      if (closeTransient) closeTransientTaskUi();
      return authoritative;
    } catch (caught) {
      if (taskReadGenerationRef.current !== generation) return null;
      throw caught;
    }
  }, [closeTransientTaskUi]);

  useEffect(() => {
    void refetchAllTasks().catch((caught: unknown) => {
      setError(caught instanceof Error ? caught.message : 'Unable to load tasks');
    });
  }, [refetchAllTasks]);

  useEffect(() => {
    const target = focusTarget === 'undo'
      ? undoRef.current
      : focusTarget === 'archived'
        ? archivedVisibilityRef.current
        : focusTarget === 'active'
          ? activeVisibilityRef.current
          : null;
    if (target === null) return;
    target.focus();
    setFocusTarget(null);
  }, [focusTarget, undoArchive]);

  useEffect(() => {
    if (menuTaskId === null) return;
    menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  }, [menuTaskId]);

  const closeArchiveDialog = useCallback(() => {
    if (mutationPendingRef.current) return;
    setArchiveCandidate(null);
    setArchiveReason('');
  }, []);

  useFocusContainment({
    active: archiveCandidate !== null,
    containerRef: archiveDialogRef,
    onDismiss: closeArchiveDialog,
    restoreFocusRef: archiveTriggerRef,
  });

  function resolveLifecycleRows(
    attempt: TaskLifecycleAttempt,
    rows: readonly Task[],
    phase: 'uncertain' | 'retry-acknowledged',
  ) {
    const authoritative = rows.find((task) => task.id === attempt.intent.task_id);
    const label = actionLabel(attempt.intent.action);
    closeTransientTaskUi();
    setUndoArchive(null);

    if (authoritative !== undefined && reachedDesiredState(attempt.intent, authoritative)) {
      setLifecycleRetry(null);
      setMutationError(null);
      setMutationNotice(`${label} confirmed after refreshing.`);
      if (attempt.intent.action === 'archive') {
        setUndoArchive(authoritative);
        setFocusTarget('undo');
      } else {
        setFocusTarget(visibility);
      }
      finishTaskMutation();
      return;
    }

    if (phase === 'uncertain' && sameTask(authoritative, attempt.originalTask)) {
      setLifecycleRetry(attempt);
      setMutationError(`${label} outcome is unknown. Retry sends the same protected request, or review the task and start a fresh action.`);
      finishTaskMutation();
      return;
    }

    setLifecycleRetry(null);
    setMutationError(phase === 'retry-acknowledged'
      ? `${label} retry was acknowledged, but the task changed again. Review the authoritative task and start a fresh action.`
      : `${label} outcome could not be safely retried because the task changed. Review the authoritative task and start a fresh action.`);
    setFocusTarget(visibility);
    finishTaskMutation();
  }

  async function reconcileLifecycle(
    attempt: TaskLifecycleAttempt,
    phase: 'uncertain' | 'retry-acknowledged',
  ) {
    try {
      const rows = await refetchAllTasks(true);
      if (rows === null) {
        setMutationRefreshRequired(true);
        setRefreshContext({ kind: 'lifecycle', attempt, phase });
        return;
      }
      resolveLifecycleRows(attempt, rows, phase);
    } catch {
      setMutationRefreshRequired(true);
      setRefreshContext({ kind: 'lifecycle', attempt, phase });
    }
  }

  async function reconcileMutationFailure(caught: unknown, fallback: string) {
    if (caught instanceof CommandOutcomeUncertainError || caught instanceof CommandConflictError) {
      try {
        const reconciled = await refetchAllTasks(true);
        if (reconciled === null) {
          setMutationRefreshRequired(true);
          setRefreshContext({ kind: 'generic' });
          return;
        }
      } catch {
        setMutationRefreshRequired(true);
        setRefreshContext({ kind: 'generic' });
        return;
      }
      setMutationError(`${caught.message} Review the refreshed task and start a fresh action.`);
    } else {
      setMutationError(caught instanceof Error ? caught.message : fallback);
    }
    finishTaskMutation();
  }

  useEffect(() => {
    const loadContacts = async () => {
      const rows: Contact[] = [];
      for (let offset = 0; ; offset += 100) {
        const page = await commandApi.contacts(100, offset);
        rows.push(...page);
        if (page.length < 100) break;
      }
      setRecords((current) => ({ ...current, contact: rows }));
    };
    void loadContacts().catch((caught) => {
      setError(caught instanceof Error ? caught.message : 'Unable to load contacts');
    });
  }, []);

  async function add() {
    if (!title.trim() || !beginTaskMutation()) return;
    setCreating(true);
    const candidate: TaskCreateInput = {
      title: title.trim(),
      description: '',
      priority,
      contact_id: contactId ? Number(contactId) : null,
      due_at: dueAt ? new Date(dueAt).toISOString() : null,
    };
    const fingerprint = JSON.stringify(candidate);
    const attempt = taskCreateAttemptRef.current?.fingerprint === fingerprint
      ? taskCreateAttemptRef.current
      : {
          key: crypto.randomUUID(),
          fingerprint,
          payload: candidate,
          clientTimezone: currentTaskClientTimezone(),
        };
    taskCreateAttemptRef.current = attempt;
    try {
      const task = await commandApi.createTask(attempt.payload, attempt.key, {
        clientTimezone: attempt.clientTimezone,
      });
      taskCreateAttemptRef.current = null;
      replaceTask(task);
      setTitle('');
      setContactId('');
      setDueAt('');
      finishTaskMutation();
    } catch (caught) {
      await reconcileMutationFailure(caught, 'Unable to create task');
    } finally {
      setCreating(false);
    }
  }

  async function complete(task: Task) {
    if (!beginTaskMutation()) return;
    try {
      const updated = await commandApi.updateTask(task.id, {
        expected_version: task.version,
        status: task.status === 'completed' ? 'open' : 'completed',
      });
      replaceTask(updated);
      finishTaskMutation();
    } catch (caught) {
      await reconcileMutationFailure(caught, 'Unable to update task');
    }
  }

  async function assignContact(task: Task, nextContactId: string) {
    if (!beginTaskMutation()) return;
    try {
      const updated = await commandApi.updateTask(task.id, {
        expected_version: task.version,
        contact_id: nextContactId ? Number(nextContactId) : null,
      });
      replaceTask(updated);
      finishTaskMutation();
    } catch (caught) {
      await reconcileMutationFailure(caught, 'Unable to assign task contact');
    }
  }

  async function showLinks(taskId: number) {
    const generation = linkReadGenerationRef.current + 1;
    linkReadGenerationRef.current = generation;
    try {
      const rows = await commandApi.taskLinks(taskId);
      if (linkReadGenerationRef.current !== generation) return;
      setLinks((all) => ({ ...all, [taskId]: rows }));
    } catch (caught) {
      if (linkReadGenerationRef.current !== generation) return;
      setError(caught instanceof Error ? caught.message : 'Unable to load task links');
    }
  }

  async function openLinker(taskId: number) {
    setSelected(taskId);
    setEntityId('');
    setLoadingRecords(true);
    try {
      const contacts: Contact[] = [];
      for (let offset = 0; ; offset += 100) {
        const page = await commandApi.contacts(100, offset);
        contacts.push(...page);
        if (page.length < 100) break;
      }
      const [opportunity, agreement, listing] = await Promise.all([
        commandApi.opportunities(),
        commandApi.agreements(),
        commandApi.listings(),
      ]);
      setRecords({ contact: contacts, opportunity, agreement, listing });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load internal records');
    } finally {
      setLoadingRecords(false);
    }
  }

  async function linkTask() {
    if (!selected || !entityId) return;
    const task = tasks.find((candidate) => candidate.id === selected);
    if (!task || !beginTaskMutation()) return;
    try {
      const created = await commandApi.addTaskLink(selected, {
        expected_version: task.version,
        entity_type: entityType,
        entity_id: Number(entityId),
      });
      setTasks((all) => all.map((item) => item.id === selected
        ? { ...item, version: created.task_version }
        : item));
      await showLinks(selected);
      setEntityId('');
      setSelected(null);
      finishTaskMutation();
    } catch (caught) {
      await reconcileMutationFailure(caught, 'Unable to link task');
    }
  }

  async function runLifecycle(attempt: TaskLifecycleAttempt, retrying = false) {
    if (!beginTaskMutation()) return;
    setUndoArchive(null);
    setMenuTaskId(null);
    const request = apiLifecycleRequest(attempt.intent);
    try {
      const updated = attempt.intent.action === 'archive'
        ? await commandApi.archiveTask(attempt.intent.task_id, request)
        : await commandApi.restoreTask(attempt.intent.task_id, request);

      if (retrying) {
        await reconcileLifecycle(attempt, 'retry-acknowledged');
        return;
      }

      replaceTask(updated);
      setLifecycleRetry(null);
      setMutationError(null);
      closeTransientTaskUi();
      if (attempt.intent.action === 'archive') {
        setUndoArchive(updated);
        setMutationNotice(`${updated.title} was archived.`);
        setFocusTarget('undo');
      } else {
        setMutationNotice(`${updated.title} was restored.`);
        setFocusTarget(visibility);
      }
      finishTaskMutation();
    } catch (caught) {
      if (caught instanceof CommandConflictError) {
        replaceTask(caught.conflict.current_task);
        setLifecycleRetry(null);
        setUndoArchive(null);
        closeTransientTaskUi();
        setMutationError(`${attempt.originalTask.title} changed elsewhere. Review the authoritative task and start a fresh action.`);
        setFocusTarget(visibility);
        finishTaskMutation();
        return;
      }
      if (caught instanceof CommandOutcomeUncertainError) {
        setArchiveCandidate(null);
        setArchiveReason('');
        await reconcileLifecycle(attempt, 'uncertain');
        return;
      }
      closeTransientTaskUi();
      setLifecycleRetry(null);
      setMutationError(caught instanceof Error ? caught.message : `Unable to ${attempt.intent.action} task`);
      setFocusTarget(visibility);
      finishTaskMutation();
    }
  }

  function createLifecycleAttempt(action: LifecycleAction, task: Task, reason?: string): TaskLifecycleAttempt {
    const intent: {
      action: LifecycleAction;
      task_id: number;
      request_id: string;
      expected_version: number;
      reason?: string;
    } = {
      action,
      task_id: task.id,
      request_id: crypto.randomUUID(),
      expected_version: task.version,
    };
    if (reason !== undefined) intent.reason = reason;
    return { intent, originalTask: task };
  }

  function confirmArchive() {
    if (archiveCandidate === null || mutationPendingRef.current) return;
    const reason = archiveReason.trim();
    void runLifecycle(createLifecycleAttempt(
      'archive',
      archiveCandidate,
      reason.length > 0 ? reason : undefined,
    ));
  }

  function restoreTask(task: Task) {
    if (mutationPendingRef.current) return;
    void runLifecycle(createLifecycleAttempt('restore', task));
  }

  function undoLastArchive() {
    if (undoArchive === null || mutationPendingRef.current) return;
    const task = undoArchive;
    setUndoArchive(null);
    void runLifecycle(createLifecycleAttempt('restore', task));
  }

  function retryLifecycleRequest() {
    if (lifecycleRetry === null || mutationPendingRef.current) return;
    const attempt = lifecycleRetry;
    void runLifecycle(attempt, true);
  }

  async function refreshAuthoritativeTasks() {
    if (!mutationRefreshRequired || refreshingTasks) return;
    setRefreshingTasks(true);
    try {
      const rows = await refetchAllTasks(true);
      if (rows === null) return;
      if (refreshContext?.kind === 'lifecycle') {
        resolveLifecycleRows(refreshContext.attempt, rows, refreshContext.phase);
      } else {
        setMutationError('Task state refreshed. Review the authoritative task and start a fresh action.');
        finishTaskMutation();
      }
    } catch {
      setMutationRefreshRequired(true);
    } finally {
      setRefreshingTasks(false);
    }
  }

  function openArchiveConfirmation(task: Task) {
    archiveTriggerRef.current = menuTriggerRefs.current.get(task.id) ?? null;
    setMenuTaskId(null);
    setArchiveReason('');
    setArchiveCandidate(task);
  }

  function closeMenu(returnFocus: boolean) {
    const taskId = menuTaskId;
    setMenuTaskId(null);
    if (returnFocus && taskId !== null) menuTriggerRefs.current.get(taskId)?.focus();
  }

  function handleMenuKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));
    if (event.key === 'Escape') {
      event.preventDefault();
      closeMenu(true);
      return;
    }
    if ((event.key !== 'ArrowDown' && event.key !== 'ArrowUp') || items.length === 0) return;
    event.preventDefault();
    const currentIndex = items.indexOf(document.activeElement as HTMLElement);
    const offset = event.key === 'ArrowDown' ? 1 : -1;
    items[(currentIndex + offset + items.length) % items.length]?.focus();
  }

  function recordLabel(type: keyof LinkableRecords, record: Contact | Opportunity | Agreement | Listing) {
    if (type === 'contact') {
      const contact = record as Contact;
      return `${contact.first_name} ${contact.last_name}`.trim();
    }
    if (type === 'listing') return (record as Listing).address;
    if (type === 'opportunity') return (record as Opportunity).name;
    return (record as Agreement).title;
  }

  const visibleTasks = visibility === 'archived'
    ? tasks.filter((task) => task.archived_at !== null)
    : applyTaskWorkspaceView(tasks, { tab: status, due: dueScope }, new Date());
  const displayedError = mutationRefreshRequired
    ? TASK_REFRESH_REQUIRED_MESSAGE
    : mutationError ?? error;

  const archiveDialog = archiveCandidate === null ? null : createPortal(
    <>
      <div aria-hidden="true" className="fixed inset-0 z-[119] bg-black/80 backdrop-blur-sm" />
      <section
        ref={archiveDialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`archive-task-title-${archiveCandidate.id}`}
        tabIndex={-1}
        className="fixed left-1/2 top-1/2 z-[120] w-[min(92vw,34rem)] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-2xl border border-[#eac469]/35 bg-[#12110f] text-white shadow-[0_28px_90px_rgba(0,0,0,.65)]"
      >
        <div className="border-b border-white/10 bg-[radial-gradient(circle_at_top_right,rgba(234,196,105,.17),transparent_46%)] px-6 py-5">
          <p className="text-[10px] font-bold uppercase tracking-[.22em] text-[#eac469]">Task archive</p>
          <h2 id={`archive-task-title-${archiveCandidate.id}`} className="mt-2 text-xl font-black">Archive {archiveCandidate.title}</h2>
          <p className="mt-2 text-sm leading-6 text-white/60">This removes the task from active workflows. You can restore it from the archive at any time.</p>
        </div>
        <div className="p-6">
          <label className="grid gap-2 text-sm font-semibold text-white/80">
            Archive reason (optional)
            <textarea
              autoFocus
              disabled={mutationsLocked}
              value={archiveReason}
              maxLength={500}
              onChange={(event) => setArchiveReason(event.target.value)}
              className="command-touch-target min-h-24 min-w-11 resize-y rounded-xl border border-white/15 bg-black/35 px-3 py-3 font-normal text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#eac469]"
            />
          </label>
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <button type="button" disabled={mutationsLocked} onClick={closeArchiveDialog} className="command-touch-target min-h-11 min-w-11 rounded-lg border border-white/15 px-4 text-sm font-bold text-white/65 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#eac469] disabled:opacity-50">Cancel</button>
            <button type="button" disabled={mutationsLocked} onClick={confirmArchive} className="command-touch-target inline-flex min-h-11 min-w-11 items-center gap-2 rounded-lg bg-[#eac469] px-4 text-sm font-black text-black focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#eac469] disabled:opacity-50">
              <Archive aria-hidden="true" size={18} />
              {mutationsLocked ? 'Archiving…' : 'Archive'}
            </button>
          </div>
        </div>
      </section>
    </>,
    document.body,
  );

  return (
    <div className="min-h-[100dvh] bg-[#080807] p-4 text-white sm:p-6">
      <main className="mx-auto max-w-5xl">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[.25em] text-[#eac469]">Internal CRM</p>
            <h1 className="mt-1 text-3xl font-black">Tasks</h1>
          </div>
          <div role="group" aria-label="Task visibility" className="inline-flex rounded-xl border border-white/10 bg-white/[.04] p-1">
            {(['active', 'archived'] as const).map((option) => (
              <button
                key={option}
                ref={option === 'active' ? activeVisibilityRef : archivedVisibilityRef}
                type="button"
                aria-pressed={visibility === option}
                onClick={() => setVisibility(option)}
                className={`command-touch-target rounded-lg px-4 text-sm font-bold transition-colors ${visibility === option ? 'bg-[#eac469] text-black' : 'text-white/60 hover:text-white'}`}
              >
                {option === 'active' ? 'Active' : 'Archived'}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-[1fr_auto_auto_auto_auto]">
          <input disabled={mutationsLocked} value={title} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && void add()} placeholder="Add a task" className="command-touch-target rounded-xl border border-white/10 bg-white/5 px-4 py-3" />
          <select aria-label="Assign task contact" disabled={mutationsLocked} value={contactId} onChange={(event) => setContactId(event.target.value)} className="command-touch-target rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm">
            <option value="">No contact</option>
            {records.contact.map((contact) => <option key={contact.id} value={contact.id}>{contact.first_name} {contact.last_name}</option>)}
          </select>
          <select aria-label="Task priority" disabled={mutationsLocked} value={priority} onChange={(event) => setPriority(event.target.value as Task['priority'])} className="command-touch-target rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm">
            <option value="low">low</option><option value="normal">normal</option><option value="high">high</option>
          </select>
          <input disabled={mutationsLocked} value={dueAt} onChange={(event) => setDueAt(event.target.value)} type="datetime-local" aria-label="Task due date" className="command-touch-target rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm" />
          <button type="button" disabled={creating || mutationsLocked} onClick={() => void add()} aria-label="Add task" className="command-touch-target rounded-xl bg-[#eac469] px-4 text-black disabled:opacity-50"><Plus aria-hidden="true" size={19} /></button>
        </div>

        {visibility === 'active' ? (
          <div className="mt-4 flex flex-wrap gap-3">
            <select aria-label="Task status" value={status} onChange={(event) => setStatus(event.target.value as TaskWorkspaceView['tab'])} className="command-touch-target rounded-lg border border-white/10 bg-black/40 p-2 text-sm">
              <option value="all">All statuses</option><option value="todo">To do</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option>
            </select>
            <select aria-label="Task due scope" value={dueScope} onChange={(event) => setDueScope(event.target.value as TaskWorkspaceView['due'])} className="command-touch-target rounded-lg border border-white/10 bg-black/40 p-2 text-sm">
              <option value="all">All due dates</option><option value="past">Past due</option>
            </select>
          </div>
        ) : <p className="mt-4 max-w-2xl text-sm leading-6 text-white/45">Archived tasks stay available for audit history and can be restored directly.</p>}

        {displayedError ? (
          <div role="alert" aria-live="assertive" className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-red-300/20 bg-red-950/25 p-3 text-sm text-red-200">
            <WarningCircle aria-hidden="true" size={18} /><span>{displayedError}</span>
            {lifecycleRetry && !mutationRefreshRequired ? <button type="button" disabled={mutationsLocked} onClick={retryLifecycleRequest} className="command-touch-target ml-auto rounded-lg border border-red-200/25 px-3 font-bold text-white disabled:opacity-50">Retry</button> : null}
            {mutationRefreshRequired ? <button type="button" disabled={refreshingTasks} onClick={() => void refreshAuthoritativeTasks()} className="command-touch-target ml-auto rounded-lg border border-red-200/25 px-3 font-bold text-white disabled:opacity-50">{refreshingTasks ? 'Refreshing…' : 'Refresh tasks'}</button> : null}
          </div>
        ) : null}

        {mutationNotice ? (
          <div role="status" aria-live="polite" className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-[#eac469]/25 bg-[#eac469]/10 p-3 text-sm text-[#f7dda0]">
            <Check aria-hidden="true" size={18} /><span>{mutationNotice}</span>
            {undoArchive ? <button ref={undoRef} type="button" disabled={mutationsLocked} onClick={undoLastArchive} className="command-touch-target ml-auto inline-flex items-center gap-2 rounded-lg border border-[#eac469]/40 px-3 font-black text-[#eac469] disabled:opacity-50"><ArrowCounterClockwise aria-hidden="true" size={17} />Undo</button> : null}
          </div>
        ) : null}

        <div className="mt-6 space-y-3">
          {visibleTasks.map((task) => (
            <article key={task.id} aria-label={`Task ${task.title}`} className="relative overflow-visible rounded-2xl border border-white/10 bg-[linear-gradient(135deg,rgba(255,255,255,.055),rgba(255,255,255,.018))] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,.05)]">
              {task.archived_at !== null ? (
                <div className="grid gap-4 sm:grid-cols-[1fr_auto] sm:items-center">
                  <div>
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="rounded-full border border-[#eac469]/25 bg-[#eac469]/10 px-2.5 py-1 text-[10px] font-black uppercase tracking-[.16em] text-[#eac469]">Archived</span>
                      <h2 className="text-base font-bold text-white/85">{task.title}</h2>
                      <span className="text-xs uppercase tracking-[.12em] text-white/35">{task.priority}</span>
                    </div>
                    {task.description ? <p className="mt-2 text-sm leading-6 text-white/55">{task.description}</p> : null}
                    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-white/40">
                      <time dateTime={task.archived_at}>Archived {new Date(task.archived_at).toLocaleString()}</time>
                      <span>{task.archive_reason ?? 'No archive reason provided'}</span>
                    </div>
                  </div>
                  <button type="button" disabled={mutationsLocked} onClick={() => restoreTask(task)} aria-label={`Restore ${task.title}`} className="command-touch-target inline-flex items-center justify-center gap-2 rounded-xl border border-[#eac469]/35 bg-[#eac469]/10 px-4 text-sm font-black text-[#eac469] transition-colors hover:bg-[#eac469]/15 disabled:opacity-50"><ArrowCounterClockwise aria-hidden="true" size={18} />Restore</button>
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-3">
                    <button type="button" disabled={mutationsLocked} onClick={() => void complete(task)} aria-label={`Toggle ${task.title}`} className={`command-touch-target grid h-11 w-11 shrink-0 place-items-center rounded-full border ${task.status === 'completed' ? 'border-[#eac469] bg-[#eac469] text-black' : 'border-white/30'}`}>{task.status === 'completed' ? <Check aria-hidden="true" size={15} /> : null}</button>
                    <span className={task.status === 'completed' ? 'text-white/35 line-through' : 'font-medium'}>{task.title}</span>
                    <span className="text-xs uppercase text-white/45">{task.priority}</span>
                    <div className="ml-auto flex flex-wrap items-center gap-1">
                      <button type="button" disabled={mutationsLocked} onClick={() => setEditing(task)} className="command-touch-target px-2 text-xs text-white/55">Edit</button>
                      <button type="button" disabled={mutationsLocked} onClick={() => void openLinker(task.id)} className="command-touch-target px-2 text-xs font-bold text-[#eac469]">Link record</button>
                      <button type="button" onClick={() => void showLinks(task.id)} className="command-touch-target px-2 text-xs text-white/55">Show links</button>
                      <button
                        ref={(node) => { if (node) menuTriggerRefs.current.set(task.id, node); else menuTriggerRefs.current.delete(task.id); }}
                        type="button"
                        disabled={mutationsLocked}
                        aria-label={`Task actions for ${task.title}`}
                        aria-haspopup="menu"
                        aria-controls={`task-menu-${task.id}`}
                        aria-expanded={menuTaskId === task.id}
                        onClick={() => setMenuTaskId((current) => current === task.id ? null : task.id)}
                        onKeyDown={(event) => {
                          if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
                          event.preventDefault();
                          setMenuTaskId(task.id);
                        }}
                        className="command-touch-target grid w-11 place-items-center rounded-lg text-white/55 transition-colors hover:bg-white/5 hover:text-white"
                      ><DotsThreeVertical aria-hidden="true" size={22} weight="bold" /></button>
                    </div>
                  </div>
                  {task.description ? <p className="mt-2 text-sm text-white/60">{task.description}</p> : null}
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-white/40">
                    <span>{task.due_at ? `Due ${new Date(task.due_at).toLocaleString()}` : 'No due date'}</span>
                    <select aria-label={`Assign ${task.title} contact`} disabled={mutationsLocked} value={task.contact_id ?? ''} onChange={(event) => void assignContact(task, event.target.value)} className="command-touch-target rounded bg-black/30 px-2 py-1 text-xs">
                      <option value="">No contact</option>
                      {records.contact.map((contact) => <option key={contact.id} value={contact.id}>{contact.first_name} {contact.last_name}</option>)}
                    </select>
                  </div>
                  {links[task.id]?.length ? <p className="mt-2 text-xs text-white/45">{links[task.id].map((link) => `${link.entity_type}: ${link.display_name}`).join(' · ')}</p> : null}
                  {menuTaskId === task.id ? (
                    <div ref={menuRef} id={`task-menu-${task.id}`} role="menu" aria-label={`Task actions for ${task.title}`} onKeyDown={handleMenuKeyDown} className="absolute right-4 top-14 z-20 min-w-48 rounded-xl border border-[#eac469]/25 bg-[#11100e] p-1.5 shadow-[0_20px_50px_rgba(0,0,0,.55)]">
                      <button type="button" role="menuitem" tabIndex={-1} onClick={() => openArchiveConfirmation(task)} className="command-touch-target flex w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-bold text-white/75 hover:bg-[#eac469]/10 hover:text-[#eac469]"><Archive aria-hidden="true" size={18} />Archive task</button>
                    </div>
                  ) : null}
                </>
              )}
            </article>
          ))}
          {visibleTasks.length === 0 ? <p className="rounded-2xl border border-dashed border-white/15 p-10 text-center text-white/40">{visibility === 'archived' ? 'No archived tasks.' : 'No matching tasks.'}</p> : null}
        </div>

        {selected ? (
          <div className="fixed inset-0 z-40 grid place-items-center bg-black/70 p-4">
            <section className="w-full max-w-sm rounded-2xl border border-white/10 bg-[#12110f] p-6">
              <h2 className="text-lg font-bold">Link internal record</h2>
              <div className="mt-4 grid gap-3">
                <select aria-label="Internal record type" value={entityType} onChange={(event) => { setEntityType(event.target.value as keyof LinkableRecords); setEntityId(''); }} className="command-touch-target rounded-lg bg-black/40 p-3 text-sm"><option value="opportunity">Opportunity</option><option value="agreement">Agreement</option><option value="listing">Listing</option><option value="contact">Contact</option></select>
                <select aria-label="Internal record to link" disabled={loadingRecords} value={entityId} onChange={(event) => setEntityId(event.target.value)} className="command-touch-target rounded-lg bg-black/40 p-3 text-sm">
                  <option value="">{loadingRecords ? 'Loading internal records…' : 'Select internal record'}</option>
                  {records[entityType].map((record) => <option key={record.id} value={record.id}>{recordLabel(entityType, record)}</option>)}
                </select>
              </div>
              <div className="mt-5 flex justify-end gap-3">
                <button type="button" onClick={() => setSelected(null)} className="command-touch-target text-sm text-white/60">Cancel</button>
                <button type="button" disabled={!entityId || loadingRecords || mutationsLocked} onClick={() => void linkTask()} className="command-touch-target rounded-lg bg-[#eac469] px-4 py-2 text-sm font-bold text-black disabled:opacity-50">Link</button>
              </div>
            </section>
          </div>
        ) : null}

        {editing ? (
          <TaskEditor
            task={editing}
            disabled={mutationsLocked}
            onMutationStart={beginTaskMutation}
            onClose={() => setEditing(null)}
            onUpdated={(updated) => { replaceTask(updated); finishTaskMutation(); }}
            onMutationError={(caught) => reconcileMutationFailure(caught, 'Unable to save task')}
          />
        ) : null}
      </main>
      {archiveDialog}
    </div>
  );
}
