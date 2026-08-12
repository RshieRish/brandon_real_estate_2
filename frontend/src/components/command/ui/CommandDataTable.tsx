'use client';

import { CaretDown, CaretUp, CaretUpDown } from '@phosphor-icons/react';
import { useEffect, useMemo, useRef } from 'react';
import type { KeyboardEvent, MouseEvent, ReactNode } from 'react';

export type CommandColumn<Row> = Readonly<{
  key: string;
  header: string;
  sortable?: boolean;
  width?: string;
  render: (row: Row) => ReactNode;
}>;

export type CommandSort = Readonly<{
  key: string;
  direction: 'ascending' | 'descending';
}>;

type CommandDataTableBaseProps<Row> = Readonly<{
  ariaLabel: string;
  columns: readonly CommandColumn<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string | number;
  sort?: CommandSort;
  onSortChange?: (sort: CommandSort) => void;
  selectedKeys?: readonly (string | number)[];
  onSelectionChange?: (keys: readonly (string | number)[]) => void;
  toolbar?: ReactNode;
  bulkActions?: ReactNode;
  emptyState?: ReactNode;
}>;

type CommandRowActivationProps<Row> =
  | Readonly<{
      onRowActivate: (row: Row) => void;
      rowActionLabel: (row: Row) => string;
    }>
  | Readonly<{
      onRowActivate?: never;
      rowActionLabel?: never;
    }>;

export type CommandDataTableProps<Row> = CommandDataTableBaseProps<Row> & CommandRowActivationProps<Row>;

const INTERACTIVE_SELECTOR = 'a, button, input, select, textarea, [role="button"], [role="link"]';

export function CommandDataTable<Row>({
  ariaLabel,
  columns,
  rows,
  rowKey,
  sort,
  onSortChange,
  selectedKeys = [],
  onSelectionChange,
  toolbar,
  bulkActions,
  emptyState,
  onRowActivate,
  rowActionLabel,
}: CommandDataTableProps<Row>) {
  const selectable = Boolean(onSelectionChange);
  const selectedSet = useMemo(() => new Set(selectedKeys.map(String)), [selectedKeys]);
  const rowEntries = rows.map((row) => ({ row, key: rowKey(row) }));
  const allSelected = rowEntries.length > 0 && rowEntries.every(({ key }) => selectedSet.has(String(key)));
  const someSelected = rowEntries.some(({ key }) => selectedSet.has(String(key))) && !allSelected;
  const selectAllRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someSelected;
  }, [someSelected]);

  function requestSort(column: CommandColumn<Row>) {
    if (!column.sortable || !onSortChange) return;
    onSortChange({
      key: column.key,
      direction: sort?.key === column.key && sort.direction === 'ascending' ? 'descending' : 'ascending',
    });
  }

  function toggleRow(key: string | number) {
    if (!onSelectionChange) return;
    const next = new Set(selectedSet);
    if (next.has(String(key))) next.delete(String(key));
    else next.add(String(key));
    const ordered = rowEntries.filter((entry) => next.has(String(entry.key))).map((entry) => entry.key);
    onSelectionChange(ordered);
  }

  function activateFromKeyboard(event: KeyboardEvent<HTMLTableRowElement>, row: Row) {
    if (
      !onRowActivate
      || (event.key !== 'Enter' && event.key !== ' ')
      || isInteractiveDescendant(event)
    ) return;
    event.preventDefault();
    onRowActivate(row);
  }

  function isInteractiveDescendant(
    event: KeyboardEvent<HTMLTableRowElement> | MouseEvent<HTMLTableRowElement>,
  ): boolean {
    const target = event.target;
    return target instanceof Element
      && target !== event.currentTarget
      && Boolean(target.closest(INTERACTIVE_SELECTOR));
  }

  return (
    <section className="command-table-frame">
      {toolbar ? (
        <div role="region" aria-label={`${ariaLabel} tools`} className="command-table-toolbar">
          {toolbar}
        </div>
      ) : null}
      {bulkActions && selectedSet.size > 0 ? (
        <div role="region" aria-label="Bulk actions" className="command-bulk-actions">
          <strong>{selectedSet.size} selected</strong>
          {bulkActions}
        </div>
      ) : null}
      <div role="region" aria-label={`${ariaLabel} table`} className="command-table-scroll" tabIndex={0}>
        <table aria-label={ariaLabel} className="command-data-table">
          <thead>
            <tr>
              {selectable ? (
                <th scope="col" className="command-selection-column">
                  <input
                    ref={selectAllRef}
                    type="checkbox"
                    aria-label={`Select all ${ariaLabel} rows`}
                    checked={allSelected}
                    onChange={() => onSelectionChange?.(allSelected ? [] : rowEntries.map((entry) => entry.key))}
                  />
                </th>
              ) : null}
              {columns.map((column) => {
                const direction = sort?.key === column.key ? sort.direction : 'none';
                const SortIcon = direction === 'ascending' ? CaretUp : direction === 'descending' ? CaretDown : CaretUpDown;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    style={column.width ? { width: column.width } : undefined}
                    aria-sort={column.sortable ? direction : undefined}
                  >
                    {column.sortable ? (
                      <button type="button" className="command-sort-button" aria-label={`Sort by ${column.header}`} onClick={() => requestSort(column)}>
                        <span>{column.header}</span>
                        <SortIcon aria-hidden="true" size={15} />
                      </button>
                    ) : column.header}
                  </th>
                );
              })}
              {onRowActivate ? <th scope="col" className="command-row-action-column">Actions</th> : null}
            </tr>
          </thead>
          <tbody>
            {rowEntries.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length + (selectable ? 1 : 0) + (onRowActivate ? 1 : 0)}
                  className="command-table-empty"
                >
                  {emptyState ?? 'No records to display.'}
                </td>
              </tr>
            ) : rowEntries.map(({ row, key }) => (
              <tr
                key={String(key)}
                tabIndex={onRowActivate ? 0 : undefined}
                className={onRowActivate ? 'is-activatable' : undefined}
                onClick={(event) => {
                  if (!isInteractiveDescendant(event)) onRowActivate?.(row);
                }}
                onKeyDown={(event) => activateFromKeyboard(event, row)}
              >
                {selectable ? (
                  <td className="command-selection-column">
                    <input
                      type="checkbox"
                      aria-label={`Select row ${String(key)}`}
                      checked={selectedSet.has(String(key))}
                      onClick={(event) => event.stopPropagation()}
                      onChange={() => toggleRow(key)}
                    />
                  </td>
                ) : null}
                {columns.map((column) => <td key={column.key}>{column.render(row)}</td>)}
                {onRowActivate && rowActionLabel ? (
                  <td className="command-row-action-column">
                    <button
                      type="button"
                      className="command-row-action command-touch-target"
                      aria-label={rowActionLabel(row)}
                      onClick={(event) => {
                        event.stopPropagation();
                        onRowActivate(row);
                      }}
                    >
                      Open
                    </button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
