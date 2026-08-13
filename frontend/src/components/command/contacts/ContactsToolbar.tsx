'use client';

import { Funnel, MagnifyingGlass, SlidersHorizontal } from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';
import type {
  ContactDirectoryRequest,
  ContactOrigin,
  ContactSource,
} from '@/lib/command/contacts';
import { CommandOverlay } from '../ui/CommandOverlay';
import {
  CONTACT_COLUMNS,
  type ContactColumnKey,
} from './ContactsTable';

const STAGE_SUGGESTIONS = ['lead', 'nurture', 'appointment', 'client', 'past_client', 'lost'] as const;
const SOURCES: readonly Readonly<{ value: ContactSource; label: string }>[] = [
  { value: 'kw_command', label: 'KW Command source' },
  { value: 'internal_crm', label: 'Internal CRM source' },
  { value: 'legacy_lead', label: 'Legacy lead source' },
];
const ORIGINS: readonly Readonly<{ value: ContactOrigin; label: string }>[] = [
  { value: 'recovered', label: 'Recovered origin' },
  { value: 'lead_backed', label: 'Lead-backed origin' },
  { value: 'legacy_only', label: 'Legacy-only origin' },
  { value: 'internal_only', label: 'Internal-only origin' },
];
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
] as const;

function normalizedInput(value: string, maximum: number): string | undefined | null {
  const normalized = value.trim();
  if (!normalized) return undefined;
  return Array.from(normalized).length <= maximum ? normalized : null;
}

function parsedTags(value: string): readonly number[] | undefined | null {
  const tokens = value.split(',').map((token) => token.trim()).filter(Boolean);
  if (tokens.some((token) => !/^[1-9][0-9]*$/.test(token))) return null;
  const tags = [...new Set(tokens
    .map(Number)
    .filter((tag) => Number.isSafeInteger(tag) && tag > 0))]
    .sort((left, right) => left - right);
  return tags.length > 0 ? tags : undefined;
}

export type ContactsToolbarProps = Readonly<{
  searchDraft: string;
  request: ContactDirectoryRequest;
  visibleColumns: ReadonlySet<ContactColumnKey>;
  onSearchDraftChange: (value: string) => void;
  onReplace: (patch: Partial<ContactDirectoryRequest>) => void;
  onVisibleColumnsChange: (columns: ReadonlySet<ContactColumnKey>) => void;
}>;

export function ContactsToolbar({
  searchDraft,
  request,
  visibleColumns,
  onSearchDraftChange,
  onReplace,
  onVisibleColumnsChange,
}: ContactsToolbarProps) {
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [stageDraft, setStageDraft] = useState(() => request.stage ?? '');
  const [ownerDraft, setOwnerDraft] = useState(() => request.owner_actor_id ?? '');
  const [assigneeDraft, setAssigneeDraft] = useState(() => request.assignee_actor_id ?? '');
  const [tagDraft, setTagDraft] = useState(() => request.tag?.join(', ') ?? '');
  const filterTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!filtersOpen) return undefined;
    const timer = window.setTimeout(() => {
      setStageDraft((current) => (
        normalizedInput(current, 50) === request.stage ? current : request.stage ?? ''
      ));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [filtersOpen, request.stage]);

  useEffect(() => {
    if (!filtersOpen) return undefined;
    const timer = window.setTimeout(() => {
      setOwnerDraft((current) => (
        normalizedInput(current, 255) === request.owner_actor_id
          ? current
          : request.owner_actor_id ?? ''
      ));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [filtersOpen, request.owner_actor_id]);

  useEffect(() => {
    if (!filtersOpen) return undefined;
    const timer = window.setTimeout(() => {
      setAssigneeDraft((current) => (
        normalizedInput(current, 255) === request.assignee_actor_id
          ? current
          : request.assignee_actor_id ?? ''
      ));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [filtersOpen, request.assignee_actor_id]);

  useEffect(() => {
    if (!filtersOpen) return undefined;
    const timer = window.setTimeout(() => {
      setTagDraft((current) => (
        JSON.stringify(parsedTags(current)) === JSON.stringify(request.tag)
          ? current
          : request.tag?.join(', ') ?? ''
      ));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [filtersOpen, request.tag]);

  const toggleColumn = (key: ContactColumnKey) => {
    const next = new Set(visibleColumns);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onVisibleColumnsChange(next);
  };

  const toggleValue = <Value extends string>(
    key: 'source' | 'origin',
    current: readonly Value[] | undefined,
    value: Value,
  ) => {
    const next = new Set(current ?? []);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    onReplace({ [key]: next.size > 0 ? [...next].sort() : undefined });
  };

  const openFilters = () => {
    setStageDraft(request.stage ?? '');
    setOwnerDraft(request.owner_actor_id ?? '');
    setAssigneeDraft(request.assignee_actor_id ?? '');
    setTagDraft(request.tag?.join(', ') ?? '');
    setFiltersOpen(true);
  };

  return (
    <div className="command-contacts-toolbar command-print-hidden">
      <label className="command-contacts-search">
        <MagnifyingGlass aria-hidden="true" size={17} />
        <span className="command-visually-hidden">Search contacts</span>
        <input
          type="search"
          aria-label="Search contacts"
          value={searchDraft}
          placeholder="Search name, email, or phone"
          onChange={(event) => onSearchDraftChange(event.target.value)}
        />
      </label>
      <button
        ref={filterTriggerRef}
        type="button"
        className="command-secondary-button command-touch-target"
        aria-expanded={filtersOpen}
        onClick={openFilters}
      >
        <Funnel aria-hidden="true" size={16} />
        Filter contacts
      </button>
      <div className="command-contacts-column-picker">
        <button
          type="button"
          className="command-secondary-button command-touch-target"
          aria-expanded={columnsOpen}
          onClick={() => setColumnsOpen((current) => !current)}
        >
          <SlidersHorizontal aria-hidden="true" size={16} />
          Choose columns
        </button>
        {columnsOpen ? (
          <div role="group" aria-label="Visible contact columns" className="command-contacts-column-menu">
            {CONTACT_COLUMNS.map((column) => (
              <label key={column.key} className="command-touch-target">
                <input
                  type="checkbox"
                  checked={visibleColumns.has(column.key)}
                  onChange={() => toggleColumn(column.key)}
                />
                {column.label}
              </label>
            ))}
          </div>
        ) : null}
      </div>

      <CommandOverlay
        variant="drawer"
        open={filtersOpen}
        onOpenChange={setFiltersOpen}
        labelledBy="command-contact-filters-title"
        closeLabel="Close contact filters"
        triggerRef={filterTriggerRef}
      >
        <form className="command-contacts-filter-form" onSubmit={(event) => event.preventDefault()}>
          <div>
            <p className="command-contacts-kicker">Directory scope</p>
            <h2 id="command-contact-filters-title">Contact filters</h2>
          </div>
          <label>
            Stage
            <input
              list="command-contact-filter-stages"
              value={stageDraft}
              placeholder="All stages"
              onChange={(event) => {
                const value = event.target.value;
                setStageDraft(value);
                const normalized = normalizedInput(value, 50);
                if (normalized !== null) onReplace({ stage: normalized });
              }}
            />
            <datalist id="command-contact-filter-stages">
              {STAGE_SUGGESTIONS.map((stage) => <option key={stage} value={stage} />)}
            </datalist>
          </label>
          <label>
            Owner actor ID
            <input
              value={ownerDraft}
              onChange={(event) => {
                const value = event.target.value;
                setOwnerDraft(value);
                const normalized = normalizedInput(value, 255);
                if (normalized !== null) onReplace({ owner_actor_id: normalized });
              }}
            />
          </label>
          <label>
            Assignee actor ID
            <input
              value={assigneeDraft}
              onChange={(event) => {
                const value = event.target.value;
                setAssigneeDraft(value);
                const normalized = normalizedInput(value, 255);
                if (normalized !== null) onReplace({ assignee_actor_id: normalized });
              }}
            />
          </label>
          <label>
            Tag IDs
            <input
              inputMode="numeric"
              value={tagDraft}
              placeholder="3, 8"
              onChange={(event) => {
                const value = event.target.value;
                setTagDraft(value);
                const tags = parsedTags(value);
                if (tags !== null) onReplace({ tag: tags });
              }}
            />
          </label>
          <fieldset className="command-contacts-filter-options">
            <legend>Sources</legend>
            {SOURCES.map((source) => (
              <label key={source.value}>
                <input
                  type="checkbox"
                  checked={request.source?.includes(source.value) ?? false}
                  onChange={() => toggleValue('source', request.source, source.value)}
                />
                {source.label}
              </label>
            ))}
          </fieldset>
          <fieldset className="command-contacts-filter-options">
            <legend>Origins</legend>
            {ORIGINS.map((origin) => (
              <label key={origin.value}>
                <input
                  type="checkbox"
                  checked={request.origin?.includes(origin.value) ?? false}
                  onChange={() => toggleValue('origin', request.origin, origin.value)}
                />
                {origin.label}
              </label>
            ))}
          </fieldset>
          <div className="command-contacts-filter-pair">
            <label>
              Minimum health
              <input
                type="number"
                min={0}
                max={100}
                value={request.health_min ?? ''}
                onChange={(event) => onReplace({ health_min: event.target.value ? Number(event.target.value) : undefined })}
              />
            </label>
            <label>
              Maximum health
              <input
                type="number"
                min={0}
                max={100}
                value={request.health_max ?? ''}
                onChange={(event) => onReplace({ health_max: event.target.value ? Number(event.target.value) : undefined })}
              />
            </label>
          </div>
          <div className="command-contacts-filter-pair">
            <label>
              Birthday month
              <select
                value={request.birthday_month ?? ''}
                onChange={(event) => onReplace({ birthday_month: event.target.value ? Number(event.target.value) : undefined })}
              >
                <option value="">Any month</option>
                {MONTHS.map((month, index) => <option key={month} value={index + 1}>{month}</option>)}
              </select>
            </label>
            <label>
              Anniversary month
              <select
                value={request.anniversary_month ?? ''}
                onChange={(event) => onReplace({ anniversary_month: event.target.value ? Number(event.target.value) : undefined })}
              >
                <option value="">Any month</option>
                {MONTHS.map((month, index) => <option key={month} value={index + 1}>{month}</option>)}
              </select>
            </label>
          </div>
          <button type="button" className="command-primary-button command-touch-target" onClick={() => setFiltersOpen(false)}>
            View contacts
          </button>
        </form>
      </CommandOverlay>
    </div>
  );
}
