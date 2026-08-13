'use client';

import { Plus, WarningCircle } from '@phosphor-icons/react';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';
import { useRouter } from 'next/navigation';
import type {
  ContactBulkInput,
  ContactDirectoryPage,
  ContactDirectoryRequest,
  ContactSmartView,
  ContactsApi,
} from '@/lib/command/contacts';
import { contactsApi } from '@/lib/command/contacts';
import { CommandModuleHeader } from './ui/CommandModuleHeader';
import { CommandStatePanel } from './ui/CommandStatePanel';
import { CommandTabs } from './ui/CommandTabs';
import { useCommandToast } from './ui/CommandToastProvider';
import { ContactCreateDrawer } from './contacts/ContactCreateDrawer';
import {
  CONTACT_COLUMNS,
  ContactsTable,
  type ContactColumnKey,
} from './contacts/ContactsTable';
import { ContactsToolbar } from './contacts/ContactsToolbar';
import { useContactDirectoryQuery } from './contacts/useContactDirectoryQuery';

const SMART_VIEWS: readonly Readonly<{ value: ContactSmartView; label: string }>[] = [
  { value: 'all', label: 'All contacts' },
  { value: 'never_contacted', label: 'Never contacted' },
  { value: 'recently_active', label: 'Recently active' },
  { value: 'birthdays_this_month', label: 'Birthdays' },
  { value: 'anniversaries_this_month', label: 'Anniversaries' },
];

const STAGE_SUGGESTIONS = ['lead', 'nurture', 'appointment', 'client', 'past_client', 'lost'] as const;
type ContactViewport = 'desktop' | 'tablet' | 'mobile';

function contactViewport(): ContactViewport {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'desktop';
  if (window.matchMedia('(max-width: 767px)').matches) return 'mobile';
  return window.matchMedia('(max-width: 1100px)').matches ? 'tablet' : 'desktop';
}

function subscribeContactViewport(notify: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => undefined;
  const queries = [window.matchMedia('(max-width: 767px)'), window.matchMedia('(max-width: 1100px)')];
  queries.forEach((query) => query.addEventListener('change', notify));
  return () => queries.forEach((query) => query.removeEventListener('change', notify));
}

function defaultColumnVisible(key: ContactColumnKey, viewport: ContactViewport): boolean {
  if (viewport === 'desktop') return true;
  if (key === 'owner' || key === 'evidence') return false;
  return viewport !== 'mobile' || (key !== 'tags' && key !== 'health' && key !== 'activity');
}

function useContactColumns(): Readonly<{
  visible: ReadonlySet<ContactColumnKey>;
  update: (next: ReadonlySet<ContactColumnKey>) => void;
}> {
  const viewport = useSyncExternalStore<ContactViewport>(
    subscribeContactViewport,
    contactViewport,
    () => 'desktop',
  );
  const [preferences, setPreferences] = useState<ReadonlyMap<ContactColumnKey, boolean>>(
    new Map(),
  );
  const visible = useMemo(() => new Set(
    CONTACT_COLUMNS
      .map((column) => column.key)
      .filter((key) => preferences.get(key) ?? defaultColumnVisible(key, viewport)),
  ), [preferences, viewport]);
  const update = useCallback((next: ReadonlySet<ContactColumnKey>) => {
    setPreferences((current) => {
      const updated = new Map(current);
      CONTACT_COLUMNS.forEach(({ key }) => {
        if (next.has(key) !== visible.has(key)) updated.set(key, next.has(key));
      });
      return updated;
    });
  }, [visible]);
  return useMemo(() => ({ visible, update }), [update, visible]);
}

type FetchRecord = {
  key: string;
  controller: AbortController;
  active: number;
};

type SuccessfulDirectoryPage = Readonly<{
  key: string;
  universe: string;
  page: ContactDirectoryPage;
}>;

function requestKey(request: ContactDirectoryRequest): string {
  return JSON.stringify([
    request.query,
    request.stage,
    request.owner_actor_id,
    request.assignee_actor_id,
    request.tag,
    request.source,
    request.origin,
    request.health_min,
    request.health_max,
    request.birthday_month,
    request.anniversary_month,
    request.smart_view,
    request.sort,
    request.direction,
    request.page,
    request.page_size,
  ]);
}

function universeKey(request: ContactDirectoryRequest): string {
  return JSON.stringify([
    request.query,
    request.stage,
    request.owner_actor_id,
    request.assignee_actor_id,
    request.tag,
    request.source,
    request.origin,
    request.health_min,
    request.health_max,
    request.birthday_month,
    request.anniversary_month,
    request.smart_view,
  ]);
}

function hasActiveFilters(request: ContactDirectoryRequest): boolean {
  return Boolean(
    request.query
      || request.stage
      || request.owner_actor_id
      || request.assignee_actor_id
      || request.tag?.length
      || request.source?.length
      || request.origin?.length
      || request.health_min !== undefined
      || request.health_max !== undefined
      || request.birthday_month !== undefined
      || request.anniversary_month !== undefined
      || (request.smart_view && request.smart_view !== 'all'),
  );
}

function isAbortError(error: unknown): boolean {
  return typeof error === 'object'
    && error !== null
    && 'name' in error
    && error.name === 'AbortError';
}

export type ContactsWorkspaceProps = Readonly<{
  initialView?: ContactSmartView;
  api?: ContactsApi;
}>;

export function ContactsWorkspace({
  initialView = 'all',
  api = contactsApi,
}: ContactsWorkspaceProps) {
  const router = useRouter();
  const { pushToast } = useCommandToast();
  const query = useContactDirectoryQuery(initialView);
  const request = query.request;
  const key = requestKey(request);
  const currentUniverse = universeKey(request);
  const [success, setSuccess] = useState<SuccessfulDirectoryPage | null>(null);
  const [failureKey, setFailureKey] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const fetchKey = `${key}:${attempt}`;
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const columns = useContactColumns();
  const visibleColumns = columns.visible;
  const [searchDraft, setSearchDraft] = useState(request.query ?? '');
  const [createOpen, setCreateOpen] = useState(false);
  const [bulkAction, setBulkAction] = useState<ContactBulkInput['action']['action']>('set_stage');
  const [bulkStage, setBulkStage] = useState('lead');
  const [bulkTagId, setBulkTagId] = useState('');
  const [bulkPending, setBulkPending] = useState(false);
  const addTriggerRef = useRef<HTMLButtonElement>(null);
  const drawerTriggerRef = useRef<HTMLElement | null>(null);
  const fetchRef = useRef<FetchRecord | null>(null);
  const bulkControllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const requestRef = useRef(request);
  const replaceRef = useRef(query.replace);

  useEffect(() => {
    requestRef.current = request;
    replaceRef.current = query.replace;
  }, [query.replace, request]);

  useEffect(() => {
    setSearchDraft(request.query ?? '');
  }, [request.query]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const committed = searchDraft.trim();
      if (Array.from(committed).length > 200) return;
      if (committed !== (requestRef.current.query ?? '')) {
        replaceRef.current({ query: committed || undefined });
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [searchDraft]);

  useEffect(() => {
    setSelected(new Set());

    let record = fetchRef.current;
    if (!record || record.key !== fetchKey || record.controller.signal.aborted) {
      if (record && record.key !== fetchKey) record.controller.abort();
      record = {
        key: fetchKey,
        controller: new AbortController(),
        active: 0,
      };
      fetchRef.current = record;
      const activeRecord = record;
      void api.directory(requestRef.current, { signal: activeRecord.controller.signal }).then(
        (page) => {
          if (
            activeRecord.active > 0
            && !activeRecord.controller.signal.aborted
            && fetchRef.current === activeRecord
          ) {
            setSuccess({ key: fetchKey, universe: currentUniverse, page });
            setFailureKey(null);
          }
        },
        (caught: unknown) => {
          if (
            activeRecord.active > 0
            && !activeRecord.controller.signal.aborted
            && fetchRef.current === activeRecord
            && !isAbortError(caught)
          ) {
            setFailureKey(fetchKey);
          }
        },
      );
    }
    record.active += 1;

    return () => {
      record.active -= 1;
      queueMicrotask(() => {
        if (record.active === 0) record.controller.abort();
      });
    };
  }, [api, currentUniverse, fetchKey]);

  const data = success?.universe === currentUniverse ? success.page : null;
  const error = failureKey === fetchKey ? 'Unable to load contacts.' : null;
  const loading = success?.key !== fetchKey && error === null;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      bulkControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (
      !loading
      && error === null
      && data !== null
      && data.total > 0
      && data.rows.length === 0
      && data.page_count > 0
      && (request.page ?? 1) > data.page_count
    ) {
      query.replace({ page: data.page_count });
    }
  }, [data, error, loading, query, request.page]);

  const selectedIds = useMemo(
    () => [...selected].filter((id) => data?.rows.some((row) => row.id === id)).sort((left, right) => left - right),
    [data?.rows, selected],
  );
  const refreshing = data !== null && loading;
  const pageCount = data === null
    ? 0
    : Math.ceil(data.total / (request.page_size ?? 50));

  async function applyBulk() {
    if (selectedIds.length === 0 || bulkPending) return;
    const tagId = Number(bulkTagId);
    const normalizedStage = bulkStage.trim();
    const action: ContactBulkInput['action'] = bulkAction === 'set_stage'
      ? { action: 'set_stage', stage: normalizedStage }
      : bulkAction === 'add_tag'
        ? { action: 'add_tag', tag_id: tagId }
        : { action: 'remove_tag', tag_id: tagId };
    if (bulkAction !== 'set_stage' && (!Number.isSafeInteger(tagId) || tagId < 1)) {
      pushToast({ tone: 'error', message: 'Enter a valid tag ID.' });
      return;
    }
    if (bulkAction === 'set_stage' && (normalizedStage.length < 1 || Array.from(normalizedStage).length > 50)) {
      pushToast({ tone: 'error', message: 'Enter a valid stage.' });
      return;
    }

    const controller = new AbortController();
    bulkControllerRef.current?.abort();
    bulkControllerRef.current = controller;
    setBulkPending(true);
    try {
      const result = await api.bulk({ contact_ids: selectedIds, action }, { signal: controller.signal });
      if (!mountedRef.current || controller.signal.aborted || bulkControllerRef.current !== controller) return;
      setSelected(new Set());
      pushToast({ tone: 'success', message: `${result.actioned_contact_ids.length} contacts updated` });
      setAttempt((current) => current + 1);
    } catch (caught) {
      if (mountedRef.current && bulkControllerRef.current === controller && !controller.signal.aborted && !isAbortError(caught)) {
        pushToast({ tone: 'error', message: 'Contacts were not updated. Review the selection and try again.' });
      }
    } finally {
      if (mountedRef.current && bulkControllerRef.current === controller) {
        bulkControllerRef.current = null;
        setBulkPending(false);
      }
    }
  }

  const emptyState = error ? (
      <CommandStatePanel
      kind="error"
      title="Unable to load contacts"
      message="The directory request did not complete. No contact data was changed."
      actionLabel="Retry"
      onAction={() => setAttempt((current) => current + 1)}
    />
  ) : data !== null && data.total > 0 ? (
    <CommandStatePanel
      kind="loading"
      title="Loading an available contact page"
      message="The requested page is outside the current directory. Returning to the last available page."
    />
  ) : hasActiveFilters(request) ? (
    <CommandStatePanel
      kind="empty"
      title="No contacts match these filters"
      message="Clear the current directory filters to return to all contacts."
      actionLabel="Clear filters"
      onAction={query.reset}
    />
  ) : (
    <CommandStatePanel
      kind="first_run"
      title="No contacts yet"
      message="Add the first writable SWS contact to begin the directory."
      actionLabel="Add your first contact"
      onAction={() => {
        drawerTriggerRef.current = document.activeElement instanceof HTMLElement
          ? document.activeElement
          : addTriggerRef.current;
        setCreateOpen(true);
      }}
    />
  );

  const bulkControls = selectedIds.length > 0 ? (
    <div role="region" aria-label="Bulk contact actions" className="command-contacts-bulk command-print-hidden">
      <strong>{selectedIds.length} selected</strong>
      <label>
        <span className="command-visually-hidden">Bulk action</span>
        <select aria-label="Bulk action" value={bulkAction} onChange={(event) => setBulkAction(event.target.value as ContactBulkInput['action']['action'])}>
          <option value="set_stage">Set stage</option>
          <option value="add_tag">Add tag</option>
          <option value="remove_tag">Remove tag</option>
        </select>
      </label>
      {bulkAction === 'set_stage' ? (
        <label>
          <span className="command-visually-hidden">Bulk stage</span>
          <input
            aria-label="Bulk stage"
            list="command-contact-bulk-stages"
            value={bulkStage}
            onChange={(event) => setBulkStage(event.target.value)}
          />
          <datalist id="command-contact-bulk-stages">
            {STAGE_SUGGESTIONS.map((stage) => <option key={stage} value={stage} />)}
          </datalist>
        </label>
      ) : (
        <label>
          <span className="command-visually-hidden">Tag ID</span>
          <input aria-label="Tag ID" type="number" min={1} value={bulkTagId} onChange={(event) => setBulkTagId(event.target.value)} />
        </label>
      )}
      <button type="button" className="command-primary-button command-touch-target" disabled={bulkPending} onClick={() => void applyBulk()}>
        {bulkPending ? 'Applying…' : 'Apply bulk action'}
      </button>
    </div>
  ) : null;

  return (
    <section className="command-contacts-workspace">
      <CommandModuleHeader
        breadcrumbs={[{ label: 'Command', href: '/admin/command' }, { label: 'Contacts' }]}
        title="Contacts"
        description={data ? `${data.total} contacts` : 'Loading contact count…'}
        actions={(
          <button
            ref={addTriggerRef}
            type="button"
            className="command-primary-button command-touch-target command-print-hidden"
            onClick={(event) => {
              drawerTriggerRef.current = event.currentTarget;
              setCreateOpen(true);
            }}
          >
            <Plus aria-hidden="true" size={16} />
            Add Contact
          </button>
        )}
        tabs={(
          <CommandTabs
            idBase="contact-smart-view"
            ariaLabel="Contact SmartViews"
            tabs={SMART_VIEWS}
            value={request.smart_view ?? 'all'}
            onValueChange={(smart_view) => query.replace({ smart_view })}
          />
        )}
        toolbar={(
          <ContactsToolbar
            searchDraft={searchDraft}
            request={request}
            visibleColumns={visibleColumns}
            onSearchDraftChange={setSearchDraft}
            onReplace={query.replace}
            onVisibleColumnsChange={columns.update}
          />
        )}
      />

      <div
        id={`contact-smart-view-panel-${request.smart_view ?? 'all'}`}
        role="tabpanel"
        aria-labelledby={`contact-smart-view-tab-${request.smart_view ?? 'all'}`}
        className="command-contacts-body command-content-gutters"
      >
        {bulkControls}
        {error && data !== null ? (
          <div role="alert" className="command-contacts-inline-error">
            <WarningCircle aria-hidden="true" size={17} />
            Refresh failed. The prior page remains visible.
            <button type="button" className="command-inline-button command-touch-target" onClick={() => setAttempt((current) => current + 1)}>Retry</button>
          </div>
        ) : null}
        <ContactsTable
          data={data}
          loading={loading}
          refreshing={refreshing}
          selected={selected}
          visibleColumns={visibleColumns}
          activeSort={request.sort ?? 'name'}
          direction={request.direction ?? 'asc'}
          onSelectionChange={setSelected}
          onActivate={(row) => router.push(`/admin/command/contacts/${row.id}`)}
          onSort={(sort, direction) => query.replace({ sort, direction })}
          emptyState={emptyState}
        />
        <nav aria-label="Contact pages" className="command-contacts-pagination command-print-hidden">
          <span>Page {request.page ?? 1} of {pageCount}</span>
          <label>
            Rows per page
            <select value={request.page_size ?? 50} onChange={(event) => query.replace({ page_size: Number(event.target.value) })}>
              {[25, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
            </select>
          </label>
          <button type="button" className="command-secondary-button command-touch-target" aria-label="Previous page" disabled={(request.page ?? 1) <= 1} onClick={() => query.replace({ page: Math.max(1, (request.page ?? 1) - 1) })}>Previous</button>
          <button
            type="button"
            className="command-secondary-button command-touch-target"
            aria-label="Next page"
            disabled={data === null || (request.page ?? 1) >= pageCount}
            onClick={() => query.replace({ page: (request.page ?? 1) + 1 })}
          >
            Next
          </button>
        </nav>
      </div>

      {SMART_VIEWS.filter((view) => view.value !== (request.smart_view ?? 'all')).map((view) => (
        <div
          key={view.value}
          id={`contact-smart-view-panel-${view.value}`}
          role="tabpanel"
          aria-labelledby={`contact-smart-view-tab-${view.value}`}
          hidden
        />
      ))}

      <ContactCreateDrawer
        open={createOpen}
        api={api}
        triggerRef={drawerTriggerRef}
        onOpenChange={setCreateOpen}
        onCreated={(contact, displayName) => {
          pushToast({ tone: 'success', message: `${displayName} created` });
          router.push(`/admin/command/contacts/${contact.id}`);
        }}
      />
    </section>
  );
}
