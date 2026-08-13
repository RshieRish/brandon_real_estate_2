'use client';

import { CaretDown, CaretUp, DotsThree } from '@phosphor-icons/react';
import { useEffect, useRef } from 'react';
import type { KeyboardEvent, MouseEvent, ReactNode } from 'react';
import type {
  ContactDirectoryPage,
  ContactDirectoryRow,
  ContactSortKey,
  SortDirection,
} from '@/lib/command/contacts';

export type ContactColumnKey =
  | 'primary'
  | 'owner'
  | 'tags'
  | 'stage'
  | 'health'
  | 'activity'
  | 'evidence';

export const CONTACT_COLUMNS: readonly Readonly<{
  key: ContactColumnKey;
  label: string;
}>[] = [
  { key: 'primary', label: 'Primary contact' },
  { key: 'owner', label: 'Owner / Assignee' },
  { key: 'tags', label: 'Tags' },
  { key: 'stage', label: 'Stage' },
  { key: 'health', label: 'Health' },
  { key: 'activity', label: 'Last activity' },
  { key: 'evidence', label: 'Origin / source' },
];

const INTERACTIVE = 'a,button,input,label,select,textarea,[role="button"],[role="link"],[role="menu"]';
const ORIGIN_LABELS = {
  recovered: 'Recovered',
  lead_backed: 'Lead backed',
  legacy_only: 'Legacy only',
  internal_only: 'Internal only',
} as const;
const SOURCE_LABELS = {
  kw_command: 'KW Command source',
  internal_crm: 'Internal CRM source',
  legacy_lead: 'Legacy lead source',
} as const;

function displayDate(value: string | null): string {
  if (!value) return 'No activity';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return 'Unknown';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
  }).format(date);
}

function OriginAndSource({ row }: { row: ContactDirectoryRow }) {
  return (
    <div
      className="command-contacts-evidence-stack"
      title={[
        ...row.origins.map((origin) => ORIGIN_LABELS[origin]),
        ...row.sources.map((source) => SOURCE_LABELS[source]),
      ].join(', ')}
    >
      {row.origins.map((origin) => (
        <span key={origin} className={`command-contacts-origin is-${origin}`}>
          {ORIGIN_LABELS[origin]}
        </span>
      ))}
      {row.sources.map((source) => (
        <span key={source} className={`command-contacts-source is-${source}`}>
          {SOURCE_LABELS[source]}
        </span>
      ))}
    </div>
  );
}

function SortHeading({
  label,
  sortKey,
  activeSort,
  direction,
  onSort,
  className,
}: Readonly<{
  label: string;
  sortKey: ContactSortKey;
  activeSort: ContactSortKey;
  direction: SortDirection;
  onSort: (sort: ContactSortKey, direction: SortDirection) => void;
  className?: string;
}>) {
  const active = activeSort === sortKey;
  const nextDirection = active && direction === 'asc' ? 'desc' : 'asc';
  const Icon = active && direction === 'desc' ? CaretDown : CaretUp;
  return (
    <th
      scope="col"
      aria-label={label}
      aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}
      className={className}
    >
      <button
        type="button"
        className="command-contacts-sort command-touch-target"
        aria-label={`Sort by ${label}`}
        onClick={() => onSort(sortKey, nextDirection)}
      >
        <span>{label}</span>
        <Icon aria-hidden="true" size={13} />
      </button>
    </th>
  );
}

function TableState({ children, role, ariaLabel }: Readonly<{
  children: ReactNode;
  role?: 'status';
  ariaLabel?: string;
}>) {
  return (
    <tr>
      <td colSpan={10} className="command-contacts-state-cell">
        <div role={role} aria-label={ariaLabel} className="command-contacts-table-state">
          {children}
        </div>
      </td>
    </tr>
  );
}

export type ContactsTableProps = Readonly<{
  data: ContactDirectoryPage | null;
  loading: boolean;
  refreshing: boolean;
  selected: ReadonlySet<number>;
  visibleColumns: ReadonlySet<ContactColumnKey>;
  activeSort: ContactSortKey;
  direction: SortDirection;
  onSelectionChange: (selected: ReadonlySet<number>) => void;
  onActivate: (row: ContactDirectoryRow) => void;
  onSort: (sort: ContactSortKey, direction: SortDirection) => void;
  emptyState?: ReactNode;
}>;

export function ContactsTable({
  data,
  loading,
  refreshing,
  selected,
  visibleColumns,
  activeSort,
  direction,
  onSelectionChange,
  onActivate,
  onSort,
  emptyState,
}: ContactsTableProps) {
  const rows = data?.rows ?? [];
  const ids = rows.map((row) => row.id);
  const allSelected = ids.length > 0 && ids.every((id) => selected.has(id));
  const someSelected = ids.some((id) => selected.has(id)) && !allSelected;
  const selectAllRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someSelected;
  }, [someSelected]);

  const interactiveTarget = (
    event: KeyboardEvent<HTMLTableRowElement> | MouseEvent<HTMLTableRowElement>,
  ): boolean => {
    const target = event.target;
    return target instanceof Element
      && target !== event.currentTarget
      && Boolean(target.closest(INTERACTIVE));
  };

  const toggleRow = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onSelectionChange(next);
  };

  return (
    <div
      role="region"
      aria-label="Contacts directory table"
      className="command-contacts-table-region"
      tabIndex={0}
    >
      <table className="command-contacts-table" aria-busy={refreshing ? 'true' : undefined}>
        <caption className="command-visually-hidden">Contacts directory</caption>
        <thead>
          <tr className="command-contacts-table-head">
            <th scope="col" className="command-contacts-select-column command-print-hidden">
              <label className="command-contacts-checkbox command-touch-target">
                <input
                  ref={selectAllRef}
                  type="checkbox"
                  aria-label="Select all contacts on this page"
                  checked={allSelected}
                  onChange={() => onSelectionChange(allSelected ? new Set() : new Set(ids))}
                />
              </label>
            </th>
            <SortHeading
              label="Name"
              sortKey="name"
              activeSort={activeSort}
              direction={direction}
              onSort={onSort}
              className="command-contacts-name-column"
            />
            {visibleColumns.has('primary') ? <th scope="col" className="command-contacts-primary-column">Primary contact</th> : null}
            {visibleColumns.has('owner') ? <th scope="col" className="command-contacts-owner-column">Owner / Assignee</th> : null}
            {visibleColumns.has('tags') ? <th scope="col" className="command-contacts-tags-column">Tags</th> : null}
            {visibleColumns.has('stage') ? (
              <SortHeading label="Stage" sortKey="stage" activeSort={activeSort} direction={direction} onSort={onSort} className="command-contacts-stage-column" />
            ) : null}
            {visibleColumns.has('health') ? (
              <SortHeading label="Health" sortKey="health_score" activeSort={activeSort} direction={direction} onSort={onSort} className="command-contacts-health-column" />
            ) : null}
            {visibleColumns.has('activity') ? (
              <SortHeading label="Last activity" sortKey="last_interaction_at" activeSort={activeSort} direction={direction} onSort={onSort} className="command-contacts-activity-column" />
            ) : null}
            {visibleColumns.has('evidence') ? <th scope="col" className="command-contacts-evidence-column">Origin / source</th> : null}
            <th scope="col" className="command-contacts-action-column command-print-hidden">Actions</th>
          </tr>
        </thead>
        <tbody>
          {loading && data === null ? (
            <TableState role="status" ariaLabel="Loading contacts">
              <span className="command-contacts-skeleton" aria-hidden="true" />
              <span className="command-contacts-skeleton" aria-hidden="true" />
              <span className="command-contacts-skeleton" aria-hidden="true" />
            </TableState>
          ) : rows.length === 0 ? (
            <TableState>{emptyState}</TableState>
          ) : rows.map((row) => (
            <tr
              key={row.id}
              className="command-contacts-row"
              tabIndex={0}
              onClick={(event) => {
                if (!interactiveTarget(event)) onActivate(row);
              }}
              onKeyDown={(event) => {
                if ((event.key === 'Enter' || event.key === ' ') && !interactiveTarget(event)) {
                  event.preventDefault();
                  onActivate(row);
                }
              }}
            >
              <td className="command-contacts-select-column command-print-hidden">
                <label className="command-contacts-checkbox command-touch-target">
                  <input
                    type="checkbox"
                    checked={selected.has(row.id)}
                    aria-label={`Select ${row.display_name}`}
                    onClick={(event) => event.stopPropagation()}
                    onChange={() => toggleRow(row.id)}
                  />
                </label>
              </td>
              <td className="command-contacts-name-column">
                <strong>{row.display_name}</strong>
                <span>#{row.id}</span>
              </td>
              {visibleColumns.has('primary') ? (
                <td className="command-contacts-primary-column">
                  <span>{row.primary_email ?? 'No email'}</span>
                  <small>{row.primary_phone ?? 'No phone'}</small>
                </td>
              ) : null}
              {visibleColumns.has('owner') ? (
                <td className="command-contacts-owner-column">
                  <span>{row.owner?.display_name ?? 'Unassigned owner'}</span>
                  <small>{row.assignee?.display_name ?? 'No assignee'}</small>
                </td>
              ) : null}
              {visibleColumns.has('tags') ? (
                <td className="command-contacts-tags-column" title={row.tags.map((tag) => tag.name).join(', ')}>
                  {row.tags.length > 0 ? row.tags.map((tag) => <span key={tag.id} className="command-contacts-tag">{tag.name}</span>) : '—'}
                </td>
              ) : null}
              {visibleColumns.has('stage') ? <td className="command-contacts-stage-column"><span className="command-contacts-stage">{row.stage.replaceAll('_', ' ')}</span></td> : null}
              {visibleColumns.has('health') ? <td className="command-contacts-health-column">{row.health_score === null ? '—' : `${row.health_score}%`}</td> : null}
              {visibleColumns.has('activity') ? <td className="command-contacts-activity-column">{displayDate(row.last_interaction_at)}</td> : null}
              {visibleColumns.has('evidence') ? <td className="command-contacts-evidence-column"><OriginAndSource row={row} /></td> : null}
              <td className="command-contacts-action-column command-print-hidden">
                <button
                  type="button"
                  className="command-icon-button command-touch-target"
                  aria-label={`Open ${row.display_name}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onActivate(row);
                  }}
                >
                  <DotsThree aria-hidden="true" size={20} weight="bold" />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
