'use client';

import Image from 'next/image';
import Link from 'next/link';
import { List, X } from '@phosphor-icons/react';
import { usePathname } from 'next/navigation';
import { useCallback, useRef, useState } from 'react';
import { commandNavigation, isCommandDestinationActive } from './commandNavigation';
import { useFocusContainment } from './useFocusContainment';

export function CommandMobileNavigation() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const close = useCallback(() => setOpen(false), []);

  useFocusContainment({
    active: open,
    containerRef: drawerRef,
    onDismiss: close,
    restoreFocusRef: triggerRef,
  });

  return (
    <>
      <div className="command-mobile-header command-print-hidden">
        <Link href="/admin/command" className="command-mobile-brand" aria-label="Command Home">
          <Image
            src="/logos/Sold With Sweeney Smiley.png"
            alt="Sold With Sweeney smiley mark"
            width={36}
            height={36}
          />
          <span>SWS COMMAND</span>
        </Link>
        <button
          ref={triggerRef}
          type="button"
          className="command-icon-button command-touch-target"
          aria-label="Open Command navigation"
          aria-expanded={open}
          onClick={() => setOpen(true)}
        >
          <List aria-hidden="true" size={22} />
        </button>
      </div>

      {open ? (
        <div className="command-mobile-layer command-print-hidden">
          <button
            type="button"
            className="command-scrim"
            aria-label="Dismiss Command navigation"
            tabIndex={-1}
            onClick={close}
          />
          <aside
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Command navigation"
            className="command-mobile-drawer"
            tabIndex={-1}
          >
            <div className="command-mobile-drawer-heading">
              <div>
                <span className="command-brand-kicker">SOLD WITH SWEENEY</span>
                <strong>Command workspace</strong>
              </div>
              <button
                type="button"
                className="command-icon-button command-touch-target"
                aria-label="Close Command navigation"
                onClick={close}
              >
                <X aria-hidden="true" size={21} />
              </button>
            </div>
            <nav aria-label="Mobile Command modules" className="command-mobile-links">
              {commandNavigation.map((destination) => {
                const Icon = destination.icon;
                const active = isCommandDestinationActive(pathname, destination.href);
                return (
                  <Link
                    key={destination.href}
                    href={destination.href}
                    onClick={close}
                    aria-current={active ? 'page' : undefined}
                    className={`command-mobile-link${active ? ' is-active' : ''}`}
                  >
                    <Icon aria-hidden="true" size={20} weight={active ? 'fill' : 'regular'} />
                    <span>{destination.label}</span>
                  </Link>
                );
              })}
            </nav>
          </aside>
        </div>
      ) : null}
    </>
  );
}
