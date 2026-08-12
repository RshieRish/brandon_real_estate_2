'use client';

import { MagnifyingGlass, X } from '@phosphor-icons/react';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { commandNavigation } from './commandNavigation';
import { useFocusContainment } from './useFocusContainment';

export function CommandGlobalSearch() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const close = useCallback(() => setOpen(false), []);
  const openSearch = useCallback(() => {
    setQuery('');
    setActiveIndex(0);
    setOpen(true);
  }, []);

  const destinations = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commandNavigation;
    return commandNavigation.filter((destination) =>
      [destination.label, destination.shortLabel, ...destination.searchTerms]
        .join(' ')
        .toLowerCase()
        .includes(needle),
    );
  }, [query]);

  useFocusContainment({
    active: open,
    containerRef: dialogRef,
    onDismiss: close,
    restoreFocusRef: triggerRef,
  });

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        openSearch();
      }
    }
    document.addEventListener('keydown', handleShortcut);
    return () => document.removeEventListener('keydown', handleShortcut);
  }, [openSearch]);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
  }, [open]);

  function moveActive(direction: 1 | -1) {
    if (destinations.length === 0) return;
    setActiveIndex((current) => (current + direction + destinations.length) % destinations.length);
  }

  function navigate(index: number) {
    const destination = destinations[index];
    if (!destination) return;
    setOpen(false);
    router.push(destination.href);
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="command-search-trigger command-touch-target"
        aria-label="Search Command"
        aria-haspopup="dialog"
        onClick={openSearch}
      >
        <MagnifyingGlass aria-hidden="true" size={18} />
        <span>Search</span>
        <kbd>⌘K</kbd>
      </button>

      {open ? (
        <div className="command-modal-layer">
          <button type="button" className="command-scrim" aria-label="Dismiss search" onClick={close} />
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="Search Command"
            className="command-search-dialog"
            tabIndex={-1}
          >
            <div className="command-search-input-row">
              <MagnifyingGlass aria-hidden="true" size={20} />
              <input
                ref={inputRef}
                role="combobox"
                aria-label="Search Command"
                aria-expanded="true"
                aria-controls="command-search-results"
                aria-autocomplete="list"
                aria-activedescendant={
                  destinations[activeIndex] ? `command-search-option-${activeIndex}` : undefined
                }
                value={query}
                placeholder="Search modules, records, and tools"
                onChange={(event) => {
                  setQuery(event.target.value);
                  setActiveIndex(0);
                }}
                onKeyDown={(event) => {
                  if (event.key === 'ArrowDown') {
                    event.preventDefault();
                    moveActive(1);
                  } else if (event.key === 'ArrowUp') {
                    event.preventDefault();
                    moveActive(-1);
                  } else if (event.key === 'Enter') {
                    event.preventDefault();
                    navigate(activeIndex);
                  }
                }}
              />
              <button type="button" className="command-icon-button" aria-label="Close search" onClick={close}>
                <X aria-hidden="true" size={18} />
              </button>
            </div>
            <div id="command-search-results" role="listbox" aria-label="Command destinations">
              {destinations.map((destination, index) => {
                const Icon = destination.icon;
                return (
                  <button
                    key={destination.href}
                    id={`command-search-option-${index}`}
                    type="button"
                    role="option"
                    aria-label={destination.label}
                    aria-selected={index === activeIndex}
                    className={`command-search-option${index === activeIndex ? ' is-active' : ''}`}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => navigate(index)}
                  >
                    <Icon aria-hidden="true" size={20} />
                    <span>{destination.label}</span>
                    <small>{destination.searchTerms.slice(0, 2).join(' · ')}</small>
                  </button>
                );
              })}
              {destinations.length === 0 ? (
                <p className="command-search-empty">No Command destination matches that search.</p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
