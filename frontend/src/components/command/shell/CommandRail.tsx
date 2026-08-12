'use client';

import Image from 'next/image';
import Link from 'next/link';
import { CaretLeft, List } from '@phosphor-icons/react';
import { usePathname } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  commandNavigation,
  isCommandDestinationActive,
  type CommandDestination,
} from './commandNavigation';
import { useFocusContainment } from './useFocusContainment';

const primaryDestinations = commandNavigation.filter((item) => item.group !== 'tools');
const toolDestinations = commandNavigation.filter((item) => item.group === 'tools');

function RailLink({ destination, pathname }: { destination: CommandDestination; pathname: string }) {
  const Icon = destination.icon;
  const active = isCommandDestinationActive(pathname, destination.href);

  return (
    <Link
      href={destination.href}
      aria-label={destination.label}
      aria-current={active ? 'page' : undefined}
      className={`command-rail-link command-touch-target${active ? ' is-active' : ''}`}
    >
      <Icon aria-hidden="true" size={22} weight={active ? 'fill' : 'regular'} />
      <span className="command-rail-tooltip" aria-hidden="true">
        {destination.label}
      </span>
    </Link>
  );
}

function ExpandedLinks({ pathname, onNavigate }: { pathname: string; onNavigate: () => void }) {
  return (
    <>
      {commandNavigation.map((destination) => {
        const Icon = destination.icon;
        const active = isCommandDestinationActive(pathname, destination.href);
        return (
          <Link
            key={destination.href}
            href={destination.href}
            onClick={onNavigate}
            aria-current={active ? 'page' : undefined}
            className={`command-expanded-link${active ? ' is-active' : ''}`}
          >
            <Icon aria-hidden="true" size={20} weight={active ? 'fill' : 'regular'} />
            <span>{destination.label}</span>
          </Link>
        );
      })}
    </>
  );
}

export function CommandRail() {
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const overlayRef = useRef<HTMLElement>(null);
  const close = useCallback(() => setExpanded(false), []);

  useFocusContainment({
    active: expanded,
    containerRef: overlayRef,
    onDismiss: close,
    restoreFocusRef: triggerRef,
  });

  useEffect(() => {
    if (!expanded) return;
    const root = triggerRef.current?.closest('.command-root');
    const background = Array.from(root?.querySelectorAll<HTMLElement>(
      '.command-utility-header, .command-mobile-header, .command-canvas',
    ) ?? []);
    const previous = background.map((element) => ({
      element,
      ariaHidden: element.getAttribute('aria-hidden'),
      inert: element.hasAttribute('inert'),
    }));

    background.forEach((element) => {
      element.setAttribute('aria-hidden', 'true');
      element.setAttribute('inert', '');
    });

    return () => {
      previous.forEach(({ element, ariaHidden, inert }) => {
        if (ariaHidden === null) element.removeAttribute('aria-hidden');
        else element.setAttribute('aria-hidden', ariaHidden);
        if (!inert) element.removeAttribute('inert');
      });
    };
  }, [expanded]);

  return (
    <>
      <aside className="command-rail command-print-hidden">
        <Link
          href="/admin/command"
          className="command-rail-brand command-touch-target"
          aria-label="Sold With Sweeney workspace"
        >
          <Image
            src="/logos/Sold With Sweeney Smiley.png"
            alt="Sold With Sweeney smiley mark"
            width={44}
            height={44}
            priority
          />
        </Link>
        <button
          ref={triggerRef}
          type="button"
          className="command-rail-link command-touch-target"
          aria-label="Expand Command navigation"
          aria-expanded={expanded}
          onClick={() => setExpanded(true)}
        >
          <List aria-hidden="true" size={22} />
          <span className="command-rail-tooltip" aria-hidden="true">
            Expand navigation
          </span>
        </button>
        <nav className="command-rail-primary" aria-label="Command modules">
          {primaryDestinations.map((destination) => (
            <RailLink key={destination.href} destination={destination} pathname={pathname} />
          ))}
        </nav>
        <div className="command-rail-tools">
          {toolDestinations.map((destination) => (
            <RailLink key={destination.href} destination={destination} pathname={pathname} />
          ))}
        </div>
      </aside>

      {expanded ? (
        <aside
          ref={overlayRef}
          role="dialog"
          aria-modal="true"
          className="command-rail-overlay command-print-hidden"
          data-testid="command-rail-overlay"
          aria-label="Expanded Command navigation"
        >
          <div className="command-expanded-heading">
            <Link href="/admin/command" onClick={close}>
              <span className="command-brand-kicker">SOLD WITH SWEENEY</span>
              <span className="command-brand-title">Workspace</span>
            </Link>
            <button
              type="button"
              className="command-icon-button command-touch-target"
              aria-label="Collapse Command navigation"
              onClick={close}
            >
              <CaretLeft aria-hidden="true" size={20} />
            </button>
          </div>
          <nav className="command-expanded-navigation" aria-label="Expanded modules">
            <ExpandedLinks pathname={pathname} onNavigate={close} />
          </nav>
        </aside>
      ) : null}
    </>
  );
}
