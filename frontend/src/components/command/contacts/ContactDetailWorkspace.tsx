'use client';

import Link from 'next/link';
import { ArrowLeft, ArrowRight, CaretDown, MagnifyingGlass, Plus, X } from '@phosphor-icons/react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { Ref } from 'react';
import type {
  ContactDetail,
  ContactDirectoryRequest,
  ContactEvidence,
  ContactInternalWorkspace,
  ContactMaterialization,
  ContactNeighbors,
  ContactSectionName,
  ContactSectionPage,
  ContactTimelineEntry,
  ContactWorkspaceSummary,
  ContactsApi,
} from '@/lib/command/contacts';
import { contactsApi, serializeDirectoryRequest } from '@/lib/command/contacts';
import { CommandHttpError } from '@/lib/command/http';
import { ContactActions } from '../ContactActions';
import { CommandModuleHeader } from '../ui/CommandModuleHeader';
import { CommandStatePanel } from '../ui/CommandStatePanel';
import { useCommandToast } from '../ui/CommandToastProvider';
import { ContactCaptureEvidence } from './ContactCaptureEvidence';
import { ContactDetailTabs, ContactTaskTabs } from './ContactDetailTabs';
import { ContactProfilePanel } from './ContactProfilePanel';
import { CapturedSection, InternalState } from './ContactSectionSurface';
import { ContactTimelineTab } from './ContactTimelineTab';
import {
  contactDetailLocationParams,
  contactLocationParamsForRequest,
  parseContactDetailSelection,
  parseContactDirectoryRequest,
} from './useContactDirectoryQuery';

export type ContactDetailView =
  | 'timeline' | 'opportunities' | 'smart_plans' | 'tasks' | 'notes'
  | 'saved_searches' | 'evidence' | 'bookings';
export type ContactTaskView = 'to_do' | 'completed' | 'archived';

const DETAIL_VIEWS: readonly ContactDetailView[] = [
  'timeline', 'opportunities', 'smart_plans', 'tasks', 'notes',
  'saved_searches', 'evidence', 'bookings',
];
const TASK_VIEWS: readonly ContactTaskView[] = ['to_do', 'completed', 'archived'];
const SECTION_FOR_VIEW: Readonly<Partial<Record<ContactDetailView, Exclude<ContactSectionName, 'timeline'>>>> = {
  opportunities: 'opportunities',
  smart_plans: 'smart_plans',
  notes: 'notes',
  saved_searches: 'saved_searches',
};
const SECTION_FOR_TASK: Readonly<Record<ContactTaskView, Exclude<ContactSectionName, 'timeline'>>> = {
  to_do: 'tasks_to_do',
  completed: 'tasks_completed',
  archived: 'tasks_archived',
};

type SectionState = Readonly<{
  rows: readonly ContactMaterialization[];
  page: number;
  total: number;
  page_size: number;
  page_count: number;
}>;
type CapturedSectionName = Exclude<ContactSectionName, 'timeline'>;

type LoadRecord = {
  key: string;
  controller: AbortController;
  promise: Promise<boolean>;
  active: number;
  settled: boolean;
};

type JumpResult = Readonly<{
  key: string;
  request: ContactDirectoryRequest;
  rows: readonly ContactDetail['contact'][];
}>;

type PendingMutationVerification = Readonly<{
  owner: 'task-create' | 'note-delete' | 'tag-remove';
  label: string;
  controller: AbortController;
  contactId: number;
}>;

function abortError(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'name' in error && error.name === 'AbortError';
}

function detailHref(
  contactId: number,
  request: ReturnType<typeof parseContactDirectoryRequest>,
  raw: URLSearchParams,
  view: ContactDetailView,
  taskView: ContactTaskView,
): string {
  const params = contactDetailLocationParams(request, raw, view, taskView);
  const query = params.toString();
  return `/admin/command/contacts/${contactId}${query ? `?${query}` : ''}`;
}

function internalRows(
  workspace: ContactInternalWorkspace,
  section: Exclude<ContactSectionName, 'timeline'>,
) {
  if (section === 'opportunities') return workspace.opportunities;
  if (section === 'smart_plans') return workspace.smart_plans;
  if (section === 'notes') return workspace.notes;
  if (section === 'saved_searches') return workspace.saved_searches;
  const state = section === 'tasks_to_do' ? 'open' : section === 'tasks_completed' ? 'completed' : 'archived';
  return workspace.tasks.filter((task) => task.status === state);
}

function sectionLabel(section: Exclude<ContactSectionName, 'timeline'>): string {
  return section === 'smart_plans' ? 'SmartPlans'
    : section === 'saved_searches' ? 'saved searches'
      : section.startsWith('tasks_') ? `${section.slice(6).replace('_', '-')} tasks`
        : section;
}

function InternalCards({
  section,
  workspace,
  onAddTask,
  onDeleteNote,
  mutationPending,
  addTaskRef,
}: Readonly<{
  section: Exclude<ContactSectionName, 'timeline'>;
  workspace: ContactInternalWorkspace;
  onAddTask: () => void;
  onDeleteNote: (noteId: number) => void;
  mutationPending: boolean;
  addTaskRef?: Ref<HTMLButtonElement>;
}>) {
  if (section === 'opportunities') {
    return <div className="command-contact-cards">{workspace.opportunities.map((row) => (
      <article key={row.id} className="command-contact-record-card" aria-label={`SWS internal opportunity ${row.id}`}>
        <h4>{row.name}</h4><p>{row.stage}</p><p>{row.role}</p>
      </article>
    ))}</div>;
  }
  if (section === 'smart_plans') {
    return <div className="command-contact-cards">{workspace.smart_plans.map((row) => (
      <article key={row.id} className="command-contact-record-card" aria-label={`SWS internal SmartPlan ${row.id}`}>
        <h4>Plan #{row.plan_id}</h4><p>{row.status}</p>
      </article>
    ))}</div>;
  }
  if (section === 'notes') {
    return <div className="command-contact-cards">{workspace.notes.map((row) => (
      <article key={row.id} className="command-contact-record-card" aria-label={`SWS internal note ${row.id}`}>
        <h4>{row.body}</h4>
        <button
          type="button"
          className="command-inline-button"
          aria-label={`Delete SWS note ${row.id}`}
          disabled={mutationPending}
          onClick={() => onDeleteNote(row.id)}
        >Delete SWS note</button>
      </article>
    ))}</div>;
  }
  if (section === 'saved_searches') {
    return <div className="command-contact-cards">{workspace.saved_searches.map((row) => (
      <article key={row.id} className="command-contact-record-card" aria-label={`SWS internal saved search ${row.id}`}>
        <h4>{row.name}</h4><code>{row.criteria}</code>
      </article>
    ))}</div>;
  }
  const state = section === 'tasks_to_do' ? 'open' : section === 'tasks_completed' ? 'completed' : 'archived';
  const rows = workspace.tasks.filter((task) => task.status === state);
  return (
    <div className="command-contact-cards">
      {section === 'tasks_to_do' ? <button ref={addTaskRef} type="button" className="command-primary-button command-print-hidden" disabled={mutationPending} onClick={onAddTask}><Plus aria-hidden="true" size={15} />Add task</button> : null}
      {rows.map((row) => (
        <article key={row.id} className="command-contact-record-card" aria-label={`SWS internal task ${row.id}`}>
          <h4>{row.title}</h4>{row.description ? <p>{row.description}</p> : null}<p>{row.status}</p>
        </article>
      ))}
    </div>
  );
}

export type ContactDetailWorkspaceProps = Readonly<{
  contactId: number;
  api?: ContactsApi;
}>;

export function ContactDetailWorkspace({ contactId, api = contactsApi }: ContactDetailWorkspaceProps) {
  const validContactId = Number.isSafeInteger(contactId) && contactId > 0;
  const router = useRouter();
  const replaceRoute = router.replace;
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchString = searchParams.toString();
  const rawParams = useMemo(() => new URLSearchParams(searchString), [searchString]);
  const request = useMemo(() => parseContactDirectoryRequest(rawParams), [rawParams]);
  const requestKey = useMemo(() => serializeDirectoryRequest(request), [request]);
  const { pushToast } = useCommandToast();

  const initialSelection = useMemo(() => parseContactDetailSelection(rawParams), [rawParams]);
  const [view, setView] = useState<ContactDetailView>(initialSelection.view);
  const [taskView, setTaskView] = useState<ContactTaskView>(initialSelection.taskView);
  const [detail, setDetail] = useState<ContactDetail | null>(null);
  const [summary, setSummary] = useState<ContactWorkspaceSummary | null>(null);
  const [neighbors, setNeighbors] = useState<ContactNeighbors>({ previous_contact_id: null, next_contact_id: null });
  const [neighborUniverseKey, setNeighborUniverseKey] = useState<string | null>(null);
  const [neighborsFailed, setNeighborsFailed] = useState(false);
  const [internal, setInternal] = useState<ContactInternalWorkspace | null>(null);
  const [internalLoading, setInternalLoading] = useState(true);
  const [internalFailed, setInternalFailed] = useState(false);
  const [timelineRows, setTimelineRows] = useState<readonly ContactTimelineEntry[]>([]);
  const [timelineCursor, setTimelineCursor] = useState<string | null>(null);
  const [timelineHasMore, setTimelineHasMore] = useState(false);
  const [timelineLoading, setTimelineLoading] = useState(true);
  const [timelineLoadingMore, setTimelineLoadingMore] = useState(false);
  const [timelineFailed, setTimelineFailed] = useState(false);
  const [timelineLoadMoreFailed, setTimelineLoadMoreFailed] = useState(false);
  const [evidence, setEvidence] = useState<ContactEvidence | null>(null);
  const [evidenceFailed, setEvidenceFailed] = useState(false);
  const [sections, setSections] = useState<Readonly<Partial<Record<CapturedSectionName, SectionState>>>>({});
  const [sectionLoading, setSectionLoading] = useState<ReadonlySet<CapturedSectionName>>(new Set());
  const [sectionFailed, setSectionFailed] = useState<ReadonlySet<CapturedSectionName>>(new Set());
  const [sectionLoadingMore, setSectionLoadingMore] = useState<ReadonlySet<CapturedSectionName>>(new Set());
  const [sectionLoadMoreFailed, setSectionLoadMoreFailed] = useState<ReadonlySet<CapturedSectionName>>(new Set());
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [profileOpen, setProfileOpen] = useState(false);
  const [jump, setJump] = useState('');
  const [jumpResult, setJumpResult] = useState<JumpResult | null>(null);
  const [taskFormOpen, setTaskFormOpen] = useState(false);
  const [taskTitle, setTaskTitle] = useState('');
  const [taskError, setTaskError] = useState('');
  const [taskRestoreFocus, setTaskRestoreFocus] = useState(false);
  const [mutationPending, setMutationPending] = useState(false);
  const [mutationVerification, setMutationVerification] = useState<PendingMutationVerification | null>(null);
  const [mutationVerificationRetrying, setMutationVerificationRetrying] = useState(false);
  const [outsideUniverse, setOutsideUniverse] = useState(false);
  const profileDisclosureRef = useRef<HTMLButtonElement>(null);

  const mountedRef = useRef(true);
  const mountCountRef = useRef(0);
  const contactIdRef = useRef(contactId);
  const requestRef = useRef(request);
  const baseControllerRef = useRef<AbortController | null>(null);
  const baseIdRef = useRef(0);
  const summaryControllerRef = useRef<AbortController | null>(null);
  const summaryIdRef = useRef(0);
  const internalControllerRef = useRef<AbortController | null>(null);
  const internalIdRef = useRef(0);
  const timelineControllerRef = useRef<AbortController | null>(null);
  const timelineIdRef = useRef(0);
  const evidenceControllerRef = useRef<AbortController | null>(null);
  const evidenceIdRef = useRef(0);
  const sectionControllerRef = useRef(new Map<CapturedSectionName, AbortController>());
  const sectionIdRef = useRef(new Map<CapturedSectionName, number>());
  const jumpControllerRef = useRef<AbortController | null>(null);
  const mutationControllerRef = useRef<AbortController | null>(null);
  const mutationOwnerRef = useRef<string | null>(null);
  const mutationVerificationRefreshRef = useRef<(() => Promise<boolean>) | null>(null);
  const taskOpenerRef = useRef<HTMLButtonElement | null>(null);
  const baseRecordRef = useRef<LoadRecord | null>(null);
  const internalRecordRef = useRef<LoadRecord | null>(null);
  const timelineRecordRef = useRef<LoadRecord | null>(null);
  const evidenceRecordRef = useRef<LoadRecord | null>(null);
  const sectionRecordRef = useRef(new Map<CapturedSectionName, LoadRecord>());

  requestRef.current = request;
  contactIdRef.current = contactId;

  const mutationIsCurrent = (controller: AbortController, ownedContactId: number) => (
    mountedRef.current
    && !controller.signal.aborted
    && mutationControllerRef.current === controller
    && contactIdRef.current === ownedContactId
  );

  const acquireMutation = useCallback((owner: string): boolean => {
    if (mutationOwnerRef.current !== null) return false;
    mutationOwnerRef.current = owner;
    setMutationPending(true);
    return true;
  }, []);

  const releaseMutation = useCallback((owner: string) => {
    if (mutationOwnerRef.current !== owner) return;
    mutationOwnerRef.current = null;
    setMutationPending(false);
    setMutationVerification(null);
    setMutationVerificationRetrying(false);
    mutationVerificationRefreshRef.current = null;
  }, []);
  const acquireContactAction = useCallback(() => acquireMutation('contact-action'), [acquireMutation]);
  const releaseContactAction = useCallback(() => releaseMutation('contact-action'), [releaseMutation]);
  const acquireProfileMutation = useCallback(() => acquireMutation('profile'), [acquireMutation]);
  const releaseProfileMutation = useCallback(() => releaseMutation('profile'), [releaseMutation]);

  useEffect(() => {
    const sectionControllers = sectionControllerRef.current;
    mountCountRef.current += 1;
    mountedRef.current = true;
    return () => {
      mountCountRef.current -= 1;
      mountedRef.current = false;
      queueMicrotask(() => {
        if (mountCountRef.current !== 0) return;
        [baseControllerRef, summaryControllerRef, internalControllerRef, timelineControllerRef, evidenceControllerRef, jumpControllerRef, mutationControllerRef].forEach((ref) => {
          const controller = ref.current;
          ref.current = null;
          controller?.abort();
        });
        sectionControllers.forEach((controller) => controller.abort());
        sectionControllers.clear();
      });
    };
  }, []);

  const loadSummary = useCallback(async (): Promise<boolean> => {
    if (!validContactId) return false;
    const controller = new AbortController();
    summaryControllerRef.current?.abort();
    summaryControllerRef.current = controller;
    const requestId = summaryIdRef.current + 1;
    summaryIdRef.current = requestId;
    try {
      const value = await api.workspace(contactId, { signal: controller.signal });
      if (!mountedRef.current || controller.signal.aborted || summaryControllerRef.current !== controller || summaryIdRef.current !== requestId || contactIdRef.current !== contactId) return false;
      setSummary(value);
      return true;
    } catch {
      return false;
    } finally {
      if (summaryControllerRef.current === controller) summaryControllerRef.current = null;
    }
  }, [api, contactId, validContactId]);

  const loadBase = useCallback((reuse = false): Promise<boolean> => {
    if (!validContactId) return Promise.resolve(false);
    const neighborRequest = requestRef.current;
    const neighborRequestKey = serializeDirectoryRequest(neighborRequest);
    const key = `${contactId}:${neighborRequestKey}:${attempt}`;
    const currentRecord = baseRecordRef.current;
    if (reuse && currentRecord?.key === key && !currentRecord.controller.signal.aborted) {
      return currentRecord.promise;
    }
    const controller = new AbortController();
    baseControllerRef.current?.abort();
    baseControllerRef.current = controller;
    const requestId = baseIdRef.current + 1;
    baseIdRef.current = requestId;
    setLoading(true);
    setFailure(false);
    setNeighborUniverseKey(null);
    setNeighbors({ previous_contact_id: null, next_contact_id: null });
    setNeighborsFailed(false);
    setOutsideUniverse(false);
    setOutsideUniverse(false);
    const record: LoadRecord = {
      key,
      controller,
      promise: Promise.resolve(false),
      active: 0,
      settled: false,
    };
    baseRecordRef.current = record;
    record.promise = (async () => {
      try {
        const requestedNeighborUniverse = `${contactId}:${neighborRequestKey}`;
        const [nextDetail, nextSummary, neighborResult] = await Promise.all([
          api.detail(contactId, { signal: controller.signal }),
          api.workspace(contactId, { signal: controller.signal }),
          api.neighbors(contactId, neighborRequest, { signal: controller.signal }).then(
            (value) => ({ value, outside: false, failed: false }),
            (error: unknown) => {
              if (error instanceof CommandHttpError && (error.status === 404 || error.status === 409)) {
                return {
                  value: { previous_contact_id: null, next_contact_id: null },
                  outside: error.status === 409,
                  failed: false,
                };
              }
              return {
                value: { previous_contact_id: null, next_contact_id: null },
                outside: false,
                failed: true,
              };
            },
          ),
        ]);
        if (!mountedRef.current || controller.signal.aborted || baseRecordRef.current !== record || baseIdRef.current !== requestId) return false;
        setDetail(nextDetail);
        setSummary(nextSummary);
        setNeighbors(neighborResult.value);
        setNeighborUniverseKey(requestedNeighborUniverse);
        setNeighborsFailed(neighborResult.failed);
        setOutsideUniverse(neighborResult.outside);
        return true;
      } catch (error) {
        if (!controller.signal.aborted && !abortError(error) && mountedRef.current && baseRecordRef.current === record) {
          setFailure(true);
          controller.abort();
        }
        return false;
      } finally {
        record.settled = true;
        if (mountedRef.current && baseRecordRef.current === record && baseIdRef.current === requestId) {
          baseControllerRef.current = null;
          setLoading(false);
        }
      }
    })();
    return record.promise;
  }, [api, attempt, contactId, validContactId]);

  const loadInternal = useCallback((reuse = false): Promise<boolean> => {
    if (!validContactId) return Promise.resolve(false);
    const key = `${contactId}:${attempt}`;
    const currentRecord = internalRecordRef.current;
    if (reuse && currentRecord?.key === key && !currentRecord.controller.signal.aborted) {
      return currentRecord.promise;
    }
    const controller = new AbortController();
    internalControllerRef.current?.abort();
    internalControllerRef.current = controller;
    const requestId = internalIdRef.current + 1;
    internalIdRef.current = requestId;
    setInternalLoading(true);
    setInternalFailed(false);
    const record: LoadRecord = { key, controller, promise: Promise.resolve(false), active: 0, settled: false };
    internalRecordRef.current = record;
    record.promise = (async () => {
      try {
        const value = await api.internalWorkspace(contactId, { signal: controller.signal });
        if (!mountedRef.current || controller.signal.aborted || internalRecordRef.current !== record || internalIdRef.current !== requestId) return false;
        setInternal(value);
        return true;
      } catch (error) {
        if (!controller.signal.aborted && !abortError(error) && mountedRef.current && internalRecordRef.current === record) {
          setInternalFailed(true);
        }
        return false;
      } finally {
        record.settled = true;
        if (mountedRef.current && !controller.signal.aborted && internalRecordRef.current === record && internalIdRef.current === requestId) {
          internalControllerRef.current = null;
          setInternalLoading(false);
        }
      }
    })();
    return record.promise;
  }, [api, attempt, contactId, validContactId]);

  const loadTimeline = useCallback((
    append = false,
    cursor: string | null = null,
    reuse = false,
  ): Promise<boolean> => {
    if (!validContactId) return Promise.resolve(false);
    const key = `${contactId}:${attempt}:${cursor ?? 'first'}`;
    const currentRecord = timelineRecordRef.current;
    if (reuse && currentRecord?.key === key && !currentRecord.controller.signal.aborted) {
      return currentRecord.promise;
    }
    const controller = new AbortController();
    timelineControllerRef.current?.abort();
    timelineControllerRef.current = controller;
    const requestId = timelineIdRef.current + 1;
    timelineIdRef.current = requestId;
    if (append) {
      setTimelineLoadingMore(true);
      setTimelineLoadMoreFailed(false);
    } else {
      setTimelineLoading(true);
      setTimelineFailed(false);
    }
    const record: LoadRecord = { key, controller, promise: Promise.resolve(false), active: 0, settled: false };
    timelineRecordRef.current = record;
    record.promise = (async () => {
      try {
        const page = await api.timeline(contactId, cursor, 50, { signal: controller.signal });
        if (!mountedRef.current || controller.signal.aborted || timelineRecordRef.current !== record || timelineIdRef.current !== requestId) return false;
        setTimelineRows((current) => append ? [...current, ...page.rows] : page.rows);
        setTimelineCursor(page.next_cursor);
        setTimelineHasMore(page.has_more);
        return true;
      } catch (error) {
        if (!controller.signal.aborted && !abortError(error) && mountedRef.current && timelineRecordRef.current === record) {
          if (append) setTimelineLoadMoreFailed(true); else setTimelineFailed(true);
        }
        return false;
      } finally {
        record.settled = true;
        if (mountedRef.current && !controller.signal.aborted && timelineRecordRef.current === record && timelineIdRef.current === requestId) {
          timelineControllerRef.current = null;
          setTimelineLoading(false);
          setTimelineLoadingMore(false);
        }
      }
    })();
    return record.promise;
  }, [api, attempt, contactId, validContactId]);

  const loadEvidence = useCallback((reuse = false): Promise<boolean> => {
    if (!validContactId) return Promise.resolve(false);
    const key = `${contactId}:${attempt}`;
    const currentRecord = evidenceRecordRef.current;
    if (reuse && currentRecord?.key === key && !currentRecord.controller.signal.aborted) {
      return currentRecord.promise;
    }
    const controller = new AbortController();
    evidenceControllerRef.current?.abort();
    evidenceControllerRef.current = controller;
    const requestId = evidenceIdRef.current + 1;
    evidenceIdRef.current = requestId;
    setEvidenceFailed(false);
    const record: LoadRecord = { key, controller, promise: Promise.resolve(false), active: 0, settled: false };
    evidenceRecordRef.current = record;
    record.promise = (async () => {
      try {
        const value = await api.evidence(contactId, { signal: controller.signal });
        if (!mountedRef.current || controller.signal.aborted || evidenceRecordRef.current !== record || evidenceIdRef.current !== requestId) return false;
        setEvidence(value);
        return true;
      } catch (error) {
        if (!controller.signal.aborted && !abortError(error) && mountedRef.current && evidenceRecordRef.current === record) setEvidenceFailed(true);
        return false;
      } finally {
        record.settled = true;
        if (evidenceRecordRef.current === record) evidenceControllerRef.current = null;
      }
    })();
    return record.promise;
  }, [api, attempt, contactId, validContactId]);

  const loadSection = useCallback((
    section: CapturedSectionName,
    pageNumber = 1,
    append = false,
    reuse = false,
  ): Promise<boolean> => {
    if (!validContactId) return Promise.resolve(false);
    const key = `${contactId}:${attempt}:${section}:${pageNumber}`;
    const currentRecord = sectionRecordRef.current.get(section);
    if (reuse && currentRecord?.key === key && !currentRecord.controller.signal.aborted) {
      return currentRecord.promise;
    }
    const controller = new AbortController();
    sectionControllerRef.current.get(section)?.abort();
    sectionControllerRef.current.set(section, controller);
    setSectionLoading((current) => {
      const next = new Set(current);
      next.delete(section);
      return next;
    });
    setSectionLoadingMore((current) => {
      const next = new Set(current);
      next.delete(section);
      return next;
    });
    setSectionLoadMoreFailed((current) => {
      const next = new Set(current);
      next.delete(section);
      return next;
    });
    const requestId = (sectionIdRef.current.get(section) ?? 0) + 1;
    sectionIdRef.current.set(section, requestId);
    const setBusy = append ? setSectionLoadingMore : setSectionLoading;
    const setFailed = append ? setSectionLoadMoreFailed : setSectionFailed;
    setBusy((current) => new Set(current).add(section));
    setFailed((current) => {
      const next = new Set(current);
      next.delete(section);
      return next;
    });
    const record: LoadRecord = { key, controller, promise: Promise.resolve(false), active: 0, settled: false };
    sectionRecordRef.current.set(section, record);
    record.promise = (async () => {
      try {
        const page = await api.section(contactId, section, pageNumber, 50, { signal: controller.signal });
        if (!mountedRef.current || controller.signal.aborted || sectionRecordRef.current.get(section) !== record || sectionIdRef.current.get(section) !== requestId || contactIdRef.current !== contactId) return false;
        setSections((current) => ({
          ...current,
          [section]: {
            ...page,
            rows: append ? [...(current[section]?.rows ?? []), ...page.rows] : page.rows,
          },
        }));
        return true;
      } catch (error) {
        if (!controller.signal.aborted && !abortError(error) && mountedRef.current && sectionRecordRef.current.get(section) === record && contactIdRef.current === contactId) {
          setFailed((current) => new Set(current).add(section));
        }
        return false;
      } finally {
        record.settled = true;
        if (mountedRef.current && !controller.signal.aborted && sectionRecordRef.current.get(section) === record && sectionIdRef.current.get(section) === requestId && contactIdRef.current === contactId) {
          sectionControllerRef.current.delete(section);
          setBusy((current) => {
            const next = new Set(current);
            next.delete(section);
            return next;
          });
        }
      }
    })();
    return record.promise;
  }, [api, attempt, contactId, validContactId]);

  useEffect(() => {
    setView(initialSelection.view);
    setTaskView(initialSelection.taskView);
    const canonical = contactDetailLocationParams(
      request,
      rawParams,
      initialSelection.view,
      initialSelection.taskView,
    ).toString();
    if (canonical !== searchString) {
      replaceRoute(`${pathname}${canonical ? `?${canonical}` : ''}`, { scroll: false });
    }
  }, [initialSelection, pathname, rawParams, replaceRoute, request, searchString]);

  useEffect(() => {
    const summaryController = summaryControllerRef.current;
    summaryControllerRef.current = null;
    summaryController?.abort();
    const controller = mutationControllerRef.current;
    mutationControllerRef.current = null;
    mutationOwnerRef.current = null;
    controller?.abort();
    setMutationPending(false);
    setMutationVerification(null);
    setMutationVerificationRetrying(false);
    mutationVerificationRefreshRef.current = null;
    setTaskFormOpen(false);
    setTaskRestoreFocus(false);
    setTaskTitle('');
    setTaskError('');
    setProfileOpen(false);
    setJump('');
    setJumpResult(null);
    setNeighborUniverseKey(null);
    setNeighborsFailed(false);
    sectionControllerRef.current.forEach((sectionController) => sectionController.abort());
    sectionControllerRef.current.clear();
    sectionRecordRef.current.clear();
    sectionIdRef.current.clear();
    return () => {
      const pending = mutationControllerRef.current;
      mutationControllerRef.current = null;
      pending?.abort();
    };
  }, [contactId]);

  useEffect(() => {
    setDetail(null);
    setSummary(null);
    setInternal(null);
    setInternalLoading(true);
    setEvidence(null);
    sectionControllerRef.current.forEach((controller) => controller.abort());
    sectionControllerRef.current.clear();
    sectionRecordRef.current.clear();
    sectionIdRef.current.clear();
    setSections({});
    setSectionLoading(new Set());
    setSectionFailed(new Set());
    setSectionLoadingMore(new Set());
    setSectionLoadMoreFailed(new Set());
    setTimelineRows([]);
    setTimelineCursor(null);
    setTimelineHasMore(false);
    setTimelineLoadMoreFailed(false);
    setOutsideUniverse(false);
    setNeighborUniverseKey(null);
    setNeighborsFailed(false);

    void loadInternal(true);
    const internalRecord = internalRecordRef.current;
    void loadTimeline(false, null, true);
    const timelineRecord = timelineRecordRef.current;
    void loadEvidence(true);
    const evidenceRecord = evidenceRecordRef.current;
    const records = [internalRecord, timelineRecord, evidenceRecord].filter(
      (record): record is LoadRecord => record !== null,
    );
    records.forEach((record) => { record.active += 1; });
    return () => {
      records.forEach((record) => {
        record.active -= 1;
        queueMicrotask(() => {
          if (record.active === 0 && !record.settled) record.controller.abort();
        });
      });
    };
  }, [attempt, contactId, loadEvidence, loadInternal, loadTimeline]);

  useEffect(() => {
    void loadBase(true);
    const record = baseRecordRef.current;
    if (record === null) return undefined;
    record.active += 1;
    return () => {
      record.active -= 1;
      queueMicrotask(() => {
        if (record.active === 0 && !record.settled) record.controller.abort();
      });
    };
  }, [loadBase, requestKey]);

  const activeSection = view === 'tasks' ? SECTION_FOR_TASK[taskView] : SECTION_FOR_VIEW[view];
  useEffect(() => {
    if (
      activeSection
      && sections[activeSection] === undefined
      && !sectionLoading.has(activeSection)
      && !sectionFailed.has(activeSection)
    ) {
      void loadSection(activeSection, 1, false, true);
    }
  }, [activeSection, loadSection, sectionFailed, sectionLoading, sections]);

  useEffect(() => {
    const query = jump.trim();
    const prior = jumpControllerRef.current;
    jumpControllerRef.current = null;
    prior?.abort();
    setJumpResult(null);
    if (!query || Array.from(query).length > 200) {
      return undefined;
    }
    const destinationRequest: ContactDirectoryRequest = {
      ...request,
      query,
      page: 1,
      page_size: request.page_size ?? 50,
    };
    const lookupRequest: ContactDirectoryRequest = { ...destinationRequest, page_size: 10 };
    const key = serializeDirectoryRequest(lookupRequest);
    const timer = window.setTimeout(() => {
      const controller = new AbortController();
      jumpControllerRef.current = controller;
      void api.directory(lookupRequest, { signal: controller.signal }).then(
        (page) => {
          if (mountedRef.current && !controller.signal.aborted && jumpControllerRef.current === controller) {
            setJumpResult({ key, request: destinationRequest, rows: page.rows });
          }
        },
        () => {
          if (mountedRef.current && !controller.signal.aborted && jumpControllerRef.current === controller) {
            setJumpResult(null);
          }
        },
      );
    }, 200);
    return () => {
      window.clearTimeout(timer);
      const controller = jumpControllerRef.current;
      jumpControllerRef.current = null;
      controller?.abort();
    };
  }, [api, jump, request]);

  const writeView = (nextView: ContactDetailView, nextTask = taskView) => {
    if (mutationPending) return;
    setView(nextView);
    if (nextView !== 'tasks') setTaskView('to_do');
    const params = contactDetailLocationParams(request, rawParams, nextView, nextTask);
    const query = params.toString();
    router.replace(`${pathname}${query ? `?${query}` : ''}`, { scroll: false });
  };
  const writeTask = (next: ContactTaskView) => {
    if (mutationPending) return;
    setTaskView(next);
    writeView('tasks', next);
  };
  const openTaskForm = () => {
    if (mutationPending) return;
    const active = document.activeElement;
    taskOpenerRef.current = active instanceof HTMLButtonElement ? active : null;
    setTaskError('');
    setTaskFormOpen(true);
  };
  const closeTaskForm = () => {
    if (mutationPending) return;
    setTaskRestoreFocus(true);
    setTaskFormOpen(false);
    setTaskTitle('');
    setTaskError('');
  };

  useEffect(() => {
    if (!taskFormOpen && taskRestoreFocus) {
      taskOpenerRef.current?.focus();
      setTaskRestoreFocus(false);
    }
  }, [taskFormOpen, taskRestoreFocus]);

  const refreshAfterAction = async (surface: 'note' | 'search' | 'tag', outcome: 'success' | 'uncertain' | 'error') => {
    const refreshes = [loadInternal(), surface === 'tag' ? loadBase() : loadSummary()];
    if (surface === 'note') refreshes.push(loadTimeline(false, null));
    const results = await Promise.all(refreshes);
    if (!results.every(Boolean)) throw new Error('Authoritative contact refresh failed');
    if (outcome === 'success') pushToast({ tone: 'success', message: `${surface === 'search' ? 'Saved search' : surface[0]?.toUpperCase() + surface.slice(1)} saved` });
  };

  async function refreshMutation(promises: readonly Promise<boolean>[]): Promise<boolean> {
    const results = await Promise.all(promises);
    return results.every(Boolean);
  }

  async function createTask() {
    const title = taskTitle.trim();
    if (!title || mutationControllerRef.current) return;
    if (Array.from(title).length > 255) {
      setTaskError('Task title must be 255 characters or fewer.');
      return;
    }
    if (!acquireMutation('task-create')) return;
    const controller = new AbortController();
    const ownedContactId = contactId;
    mutationControllerRef.current = controller;
    let authoritative = false;
    try {
      await api.createTask({ title, contact_id: contactId, description: '', priority: 'normal', due_at: null }, { signal: controller.signal });
      if (!mutationIsCurrent(controller, ownedContactId)) return;
      const refreshed = await refreshMutation([loadInternal(), loadSummary(), loadTimeline(false, null)]);
      if (!mutationIsCurrent(controller, ownedContactId)) return;
      if (!refreshed) throw new Error('Authoritative contact refresh failed');
      authoritative = true;
      setTaskTitle('');
      setTaskError('');
      setTaskRestoreFocus(true);
      setTaskFormOpen(false);
      pushToast({ tone: 'success', message: 'Task added' });
    } catch {
      if (mutationIsCurrent(controller, ownedContactId)) {
        const refreshed = await refreshMutation([loadInternal(), loadSummary(), loadTimeline(false, null)]);
        if (!mutationIsCurrent(controller, ownedContactId)) return;
        authoritative = refreshed;
        if (!refreshed) {
          mutationVerificationRefreshRef.current = () => refreshMutation([loadInternal(), loadSummary(), loadTimeline(false, null)]);
          setMutationVerification({ owner: 'task-create', label: 'Task mutation', controller, contactId: ownedContactId });
        }
        pushToast({ tone: 'error', message: refreshed
          ? 'Task mutation status is unknown. Current contact data was refreshed.'
          : 'Task mutation status is unknown. Current contact data could not be verified.' });
      }
    } finally {
      if (authoritative && mutationIsCurrent(controller, ownedContactId)) {
        mutationControllerRef.current = null;
        releaseMutation('task-create');
      }
    }
  }

  async function deleteNote(noteId: number) {
    if (mutationControllerRef.current) return;
    if (!acquireMutation('note-delete')) return;
    const controller = new AbortController();
    const ownedContactId = contactId;
    mutationControllerRef.current = controller;
    let authoritative = false;
    try {
      await api.deleteNote(contactId, noteId, { signal: controller.signal });
      if (!mutationIsCurrent(controller, ownedContactId)) return;
      const refreshed = await refreshMutation([
        loadInternal(), loadSummary(), loadTimeline(false, null), loadSection('notes'),
      ]);
      if (!mutationIsCurrent(controller, ownedContactId)) return;
      if (!refreshed) throw new Error('Authoritative contact refresh failed');
      authoritative = true;
      pushToast({ tone: 'success', message: 'Note deleted' });
    } catch {
      if (mutationIsCurrent(controller, ownedContactId)) {
        const refreshed = await refreshMutation([
          loadInternal(), loadSummary(), loadTimeline(false, null), loadSection('notes'),
        ]);
        if (!mutationIsCurrent(controller, ownedContactId)) return;
        authoritative = refreshed;
        if (!refreshed) {
          mutationVerificationRefreshRef.current = () => refreshMutation([
            loadInternal(), loadSummary(), loadTimeline(false, null), loadSection('notes'),
          ]);
          setMutationVerification({ owner: 'note-delete', label: 'Note mutation', controller, contactId: ownedContactId });
        }
        pushToast({ tone: 'error', message: refreshed
          ? 'Note mutation status is unknown. Current contact data was refreshed.'
          : 'Note mutation status is unknown. Current contact data could not be verified.' });
      }
    } finally {
      if (authoritative && mutationIsCurrent(controller, ownedContactId)) {
        mutationControllerRef.current = null;
        releaseMutation('note-delete');
      }
    }
  }

  async function removeTag(tagId: number) {
    if (mutationControllerRef.current) return;
    if (!acquireMutation('tag-remove')) return;
    const controller = new AbortController();
    const ownedContactId = contactId;
    mutationControllerRef.current = controller;
    let authoritative = false;
    let timelineCouldChange = true;
    try {
      const removal = await api.removeTag(contactId, tagId, { signal: controller.signal });
      timelineCouldChange = removal.removed;
      if (!mutationIsCurrent(controller, ownedContactId)) return;
      const refreshed = await refreshMutation([
        loadBase(),
        loadInternal(),
        ...(removal.removed ? [loadTimeline(false, null)] : []),
      ]);
      if (!mutationIsCurrent(controller, ownedContactId)) return;
      if (!refreshed) throw new Error('Authoritative contact refresh failed');
      authoritative = true;
      if (removal.removed) pushToast({ tone: 'success', message: 'Tag removed' });
    } catch {
      if (mutationIsCurrent(controller, ownedContactId)) {
        const refreshed = await refreshMutation([
          loadBase(), loadInternal(), ...(timelineCouldChange ? [loadTimeline(false, null)] : []),
        ]);
        if (!mutationIsCurrent(controller, ownedContactId)) return;
        authoritative = refreshed;
        if (!refreshed) {
          mutationVerificationRefreshRef.current = () => refreshMutation([
            loadBase(), loadInternal(), ...(timelineCouldChange ? [loadTimeline(false, null)] : []),
          ]);
          setMutationVerification({ owner: 'tag-remove', label: 'Tag mutation', controller, contactId: ownedContactId });
        }
        pushToast({ tone: 'error', message: refreshed
          ? 'Tag mutation status is unknown. Current contact data was refreshed.'
          : 'Tag mutation status is unknown. Current contact data could not be verified.' });
      }
    } finally {
      if (authoritative && mutationIsCurrent(controller, ownedContactId)) {
        mutationControllerRef.current = null;
        releaseMutation('tag-remove');
      }
    }
  }

  async function retryMutationVerification() {
    const pending = mutationVerification;
    const refresh = mutationVerificationRefreshRef.current;
    if (!pending || !refresh || mutationVerificationRetrying || !mutationIsCurrent(pending.controller, pending.contactId)) return;
    setMutationVerificationRetrying(true);
    let refreshed = false;
    try {
      refreshed = await refresh();
    } catch {
      refreshed = false;
    }
    if (!mutationIsCurrent(pending.controller, pending.contactId)) return;
    if (!refreshed) {
      setMutationVerificationRetrying(false);
      pushToast({ tone: 'error', message: `${pending.label} status is unknown. Current contact data could not be verified.` });
      return;
    }
    mutationVerificationRefreshRef.current = null;
    setMutationVerification(null);
    setMutationVerificationRetrying(false);
    mutationControllerRef.current = null;
    releaseMutation(pending.owner);
    pushToast({ tone: 'success', message: `${pending.label} data was refreshed.` });
  }

  if (!validContactId) {
    return <CommandStatePanel kind="error" title="Invalid contact" message="The contact route does not contain a positive decimal ID." actionLabel="Back to contacts" onAction={() => router.push('/admin/command/contacts')} />;
  }
  const currentDetail = detail?.contact.id === contactId ? detail : null;
  const currentInternal = internal?.contact.id === contactId ? internal : null;
  const currentEvidence = evidence?.contact_id === contactId ? evidence : null;
  const currentNeighborUniverse = `${contactId}:${requestKey}`;
  const currentNeighbors = neighborUniverseKey === currentNeighborUniverse
    ? neighbors
    : { previous_contact_id: null, next_contact_id: null };
  const currentNeighborsFailed = neighborUniverseKey === currentNeighborUniverse && neighborsFailed;
  const currentOutsideUniverse = neighborUniverseKey === currentNeighborUniverse && outsideUniverse;
  if ((loading || detail !== currentDetail) && currentDetail === null) return <CommandStatePanel kind="loading" title="Loading contact workspace" message="Loading decoded profile and workspace data." />;
  if (failure && currentDetail === null) return <CommandStatePanel kind="error" title="Unable to load contact workspace" message="The contact detail request did not complete. No data was changed." actionLabel="Retry" onAction={() => setAttempt((value) => value + 1)} />;
  if (currentDetail === null) return null;

  const backParams = contactLocationParamsForRequest(request, rawParams);
  backParams.delete('contact_view');
  backParams.delete('task_state');
  const backQuery = backParams.toString();
  const backHref = `/admin/command/contacts${backQuery ? `?${backQuery}` : ''}`;

  const sectionState = activeSection ? sections[activeSection] ?? null : null;
  const page: ContactSectionPage | null = sectionState ? {
    rows: sectionState.rows,
    total: sectionState.total,
    page: sectionState.page,
    page_size: sectionState.page_size,
    page_count: sectionState.page_count,
  } : null;

  return (
    <section className="command-contact-detail-workspace">
      <CommandModuleHeader
        breadcrumbs={[{ label: 'Command', href: '/admin/command' }, { label: 'Contacts', href: backHref }, { label: currentDetail.contact.display_name }]}
        title={currentDetail.contact.display_name}
        description={`Contact #${contactId} · ${currentDetail.contact.stage}`}
        actions={(
          <>
            <Link className="command-secondary-button command-touch-target" href={backHref}><ArrowLeft aria-hidden="true" size={15} />Back to contacts</Link>
            <button type="button" className="command-secondary-button command-touch-target" aria-label="Previous contact" disabled={currentNeighbors.previous_contact_id === null} onClick={() => currentNeighbors.previous_contact_id && router.push(detailHref(currentNeighbors.previous_contact_id, request, rawParams, view, taskView))}><ArrowLeft aria-hidden="true" size={15} />Previous</button>
            <button type="button" className="command-secondary-button command-touch-target" aria-label="Next contact" disabled={currentNeighbors.next_contact_id === null} onClick={() => currentNeighbors.next_contact_id && router.push(detailHref(currentNeighbors.next_contact_id, request, rawParams, view, taskView))}>Next<ArrowRight aria-hidden="true" size={15} /></button>
          </>
        )}
        toolbar={(
          <div className="command-contact-detail-tools">
            <div className="command-contact-jump">
              <MagnifyingGlass aria-hidden="true" size={16} />
              <input type="search" aria-label="Jump to contact" placeholder="Jump to contact" value={jump} onChange={(event) => setJump(event.target.value)} />
              {jumpResult && jumpResult.rows.length > 0 ? <div className="command-contact-jump-results">{jumpResult.rows.map((row) => <button type="button" key={`${jumpResult.key}-${row.id}`} aria-label={`Open ${row.display_name}`} onClick={() => router.push(detailHref(row.id, jumpResult.request, rawParams, view, taskView))}>{row.display_name}</button>)}</div> : null}
            </div>
            <ContactActions
              contactId={contactId}
              api={api}
              onChanged={refreshAfterAction}
              mutationBlocked={mutationPending}
              acquireMutation={acquireContactAction}
              releaseMutation={releaseContactAction}
            />
          </div>
        )}
      />
      <div className="command-contact-detail-grid command-content-gutters">
        <div className="command-contact-profile-disclosure">
          <button
            ref={profileDisclosureRef}
            type="button"
            className="command-secondary-button command-touch-target"
            disabled={mutationPending}
            aria-expanded={profileOpen}
            aria-controls="command-contact-profile-region"
            onClick={() => setProfileOpen((value) => !value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape' && profileOpen) {
                event.preventDefault();
                setProfileOpen(false);
                profileDisclosureRef.current?.focus();
              }
            }}
          >Profile details<CaretDown aria-hidden="true" size={15} /></button>
        </div>
        <div
          id="command-contact-profile-region"
          className={profileOpen ? 'is-mobile-open' : ''}
          onKeyDown={(event) => {
            if (event.key === 'Escape' && profileOpen) {
              event.preventDefault();
              setProfileOpen(false);
              profileDisclosureRef.current?.focus();
            }
          }}
        >
          <ContactProfilePanel
            detail={currentDetail}
            rawContact={currentInternal?.contact ?? null}
            api={api}
            onProfileChanged={async () => {
              const refreshed = await refreshMutation([loadBase(), loadInternal(), loadTimeline(false, null)]);
              if (!refreshed) throw new Error('Authoritative contact refresh failed');
            }}
            onRemoveTag={(tagId) => void removeTag(tagId)}
            tagMutationPending={mutationPending}
            acquireProfileMutation={acquireProfileMutation}
            releaseProfileMutation={releaseProfileMutation}
          />
        </div>
        <div className="command-contact-detail-main">
          <ContactDetailTabs value={view} onChange={writeView} />
          {DETAIL_VIEWS.map((panelView) => {
            const selected = panelView === view;
            const panelId = `contact-detail-view-panel-${panelView}`;
            const tabId = `contact-detail-view-tab-${panelView}`;
            return (
              <section key={panelView} id={panelId} role="tabpanel" aria-labelledby={tabId} hidden={!selected} className="command-contact-detail-panel">
                {panelView === 'timeline' ? <ContactTimelineTab rows={timelineRows} evidence={currentEvidence} loading={timelineLoading} error={timelineFailed} hasMore={timelineHasMore} loadingMore={timelineLoadingMore} loadMoreError={timelineLoadMoreFailed} onRetry={() => void loadTimeline(false, null)} onLoadMore={() => void loadTimeline(true, timelineCursor)} /> : null}
                {panelView === 'tasks' ? (
                  <>
                    <ContactTaskTabs value={taskView} onChange={writeTask} />
                    {TASK_VIEWS.map((state) => {
                      const nestedSection = SECTION_FOR_TASK[state];
                      const nestedState = sections[nestedSection];
                      const nestedPage: ContactSectionPage | null = nestedState ? { ...nestedState } : null;
                      const internalTaskRows = currentInternal ? internalRows(currentInternal, nestedSection) : [];
                      return (
                        <section key={state} id={`contact-task-state-panel-${state}`} role="tabpanel" aria-labelledby={`contact-task-state-tab-${state}`} hidden={state !== taskView} className="command-contact-task-panel">
                          {state === taskView ? (
                            <>
                              <CapturedSection section={nestedSection} page={nestedPage} evidence={currentEvidence} internal={currentInternal} loading={sectionLoading.has(nestedSection)} error={sectionFailed.has(nestedSection)} onRetry={() => void loadSection(nestedSection)} onViewEvidence={() => writeView('evidence')} />
                              {nestedState && nestedState.page < nestedState.page_count ? <><button type="button" className="command-secondary-button command-print-hidden" disabled={mutationPending || sectionLoading.has(nestedSection) || sectionLoadingMore.has(nestedSection)} onClick={() => void loadSection(nestedSection, nestedState.page + 1, true)}>{sectionLoading.has(nestedSection) || sectionLoadingMore.has(nestedSection) ? 'Loading…' : sectionLoadMoreFailed.has(nestedSection) ? 'Retry more captured tasks' : 'Load more captured tasks'}</button>{sectionLoadMoreFailed.has(nestedSection) ? <p role="alert">More captured tasks could not be loaded.</p> : null}</> : null}
                              <InternalState label={`${state === 'to_do' ? 'to-do' : state} tasks`} loading={internalLoading} available={!internalFailed && currentInternal !== null} empty={internalTaskRows.length === 0} onRetry={() => void loadInternal()}>
                                {currentInternal ? <InternalCards section={nestedSection} workspace={currentInternal} onAddTask={openTaskForm} onDeleteNote={() => undefined} mutationPending={mutationPending} addTaskRef={taskOpenerRef} /> : null}
                              </InternalState>
                              {state === 'to_do' && currentInternal && internalTaskRows.length === 0 ? <button ref={taskOpenerRef} type="button" className="command-primary-button command-print-hidden" disabled={mutationPending} onClick={openTaskForm}><Plus aria-hidden="true" size={15} />Add task</button> : null}
                              {state === 'to_do' && taskFormOpen ? <section className="command-contact-action-form command-print-hidden" aria-label="Add task" onKeyDown={(event) => { if (event.key === 'Escape' && !mutationPending) { event.preventDefault(); closeTaskForm(); } }}><div><h3>Add task</h3><button type="button" className="command-touch-target" aria-label="Close task editor" disabled={mutationPending} onClick={closeTaskForm}><X aria-hidden="true" size={16} /></button></div><input aria-label="Task title" autoFocus disabled={mutationPending} value={taskTitle} onChange={(event) => { setTaskTitle(event.target.value); setTaskError(''); }} />{taskError ? <p role="alert" className="command-contacts-form-error">{taskError}</p> : null}<button type="button" className="command-primary-button command-touch-target" disabled={mutationPending || !taskTitle.trim()} onClick={() => void createTask()}>{mutationPending ? 'Saving…' : 'Save task'}</button></section> : null}
                            </>
                          ) : null}
                        </section>
                      );
                    })}
                  </>
                ) : null}
                {panelView !== 'timeline' && panelView !== 'tasks' && panelView !== 'evidence' && panelView !== 'bookings' ? (() => {
                  const section = SECTION_FOR_VIEW[panelView];
                  if (!section || section !== activeSection) return null;
                  const rows = currentInternal ? internalRows(currentInternal, section) : [];
                  return (
                    <>
                      <CapturedSection section={section} page={page} evidence={currentEvidence} internal={currentInternal} loading={sectionLoading.has(section)} error={sectionFailed.has(section)} onRetry={() => void loadSection(section)} onViewEvidence={() => writeView('evidence')} />
                      {sectionState && sectionState.page < sectionState.page_count ? <><button type="button" className="command-secondary-button command-print-hidden" disabled={mutationPending || sectionLoading.has(section) || sectionLoadingMore.has(section)} onClick={() => void loadSection(section, sectionState.page + 1, true)}>{sectionLoading.has(section) || sectionLoadingMore.has(section) ? 'Loading…' : sectionLoadMoreFailed.has(section) ? `Retry more captured ${sectionLabel(section)}` : `Load more captured ${sectionLabel(section)}`}</button>{sectionLoadMoreFailed.has(section) ? <p role="alert">More captured {sectionLabel(section)} could not be loaded.</p> : null}</> : null}
                      <InternalState label={sectionLabel(section)} loading={internalLoading} available={!internalFailed && currentInternal !== null} empty={rows.length === 0} onRetry={() => void loadInternal()}>
                        {currentInternal ? <InternalCards section={section} workspace={currentInternal} onAddTask={() => undefined} onDeleteNote={(id) => void deleteNote(id)} mutationPending={mutationPending} /> : null}
                      </InternalState>
                    </>
                  );
                })() : null}
                {panelView === 'evidence' ? currentEvidence ? <ContactCaptureEvidence evidence={currentEvidence} api={api} contactId={contactId} /> : evidenceFailed ? <CommandStatePanel kind="error" title="Source evidence is unavailable" message="The contact evidence graph could not be read." actionLabel="Retry" onAction={() => void loadEvidence()} /> : <CommandStatePanel kind="loading" title="Loading source evidence" message="Reading capture positions and source artifacts." /> : null}
                {panelView === 'bookings' ? (
                  <InternalState label="bookings" loading={internalLoading} available={!internalFailed && currentInternal !== null} empty={(currentInternal?.bookings.length ?? 0) === 0} onRetry={() => void loadInternal()}>
                    {currentInternal ? <section className="command-contact-bookings"><h3>{currentInternal.bookings.length} SWS internal bookings</h3>{currentInternal.bookings.map((booking) => <article key={booking.id} aria-label={`SWS internal booking ${booking.id}`}><h4>{booking.meeting_type}</h4><p>{booking.context}</p>{booking.location ? <p>{booking.location}</p> : null}{booking.notes ? <p>{booking.notes}</p> : null}<time>{new Date(booking.scheduled_at).toLocaleString()}</time></article>)}</section> : null}
                  </InternalState>
                ) : null}
              </section>
            );
          })}
        </div>
      </div>
      {currentOutsideUniverse ? <p className="command-contact-universe-state" role="status">This contact is outside the current directory view</p> : null}
      {currentNeighborsFailed ? <p className="command-contact-universe-state" role="status">Directory navigation is unavailable for the current view. <button type="button" className="command-inline-button" onClick={() => void loadBase()}>Retry</button></p> : null}
      {failure && currentDetail !== null ? <p className="command-contact-universe-state" role="alert">Current contact data could not be refreshed. <button type="button" className="command-inline-button" onClick={() => void loadBase()}>Retry contact data</button></p> : null}
      {mutationVerification ? <p className="command-contact-universe-state" role="alert">{mutationVerification.label} status is unknown. Current contact data could not be verified. <button type="button" className="command-secondary-button command-touch-target command-print-hidden" disabled={mutationVerificationRetrying} onClick={() => void retryMutationVerification()}>{mutationVerificationRetrying ? 'Refreshing…' : 'Retry contact refresh'}</button></p> : null}
      <aside className="command-contact-summary-strip" aria-label="Contact workspace counts">
        {summary && currentDetail ? Object.entries(summary).map(([key, value]) => <span key={key}><strong>{value}</strong>{key.replaceAll('_', ' ')}</span>) : null}
      </aside>
    </section>
  );
}
