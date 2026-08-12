'use client';

import Link from 'next/link';
import { Bell, Plus, Question, UserCircle } from '@phosphor-icons/react';
import { usePathname } from 'next/navigation';
import { findCommandDestination } from './commandNavigation';
import { CommandGlobalSearch } from './CommandGlobalSearch';

export function CommandUtilityHeader() {
  const pathname = usePathname();
  const destination = findCommandDestination(pathname);

  return (
    <header className="command-utility-header command-print-hidden">
      <a className="command-skip-link" href="#command-main">
        Skip to workspace content
      </a>
      <div className="command-utility-context">
        <span className="command-context-kicker">SWS COMMAND</span>
        <strong>{destination?.shortLabel ?? 'Workspace'}</strong>
      </div>
      <div className="command-utility-actions">
        <CommandGlobalSearch />
        {destination?.createLabel && destination.createHref ? (
          <Link href={destination.createHref} className="command-create-action command-touch-target">
            <Plus aria-hidden="true" size={18} weight="bold" />
            <span>{destination.createLabel}</span>
          </Link>
        ) : null}
        <button type="button" className="command-icon-button command-touch-target" aria-label="Notifications">
          <Bell aria-hidden="true" size={20} />
        </button>
        <button type="button" className="command-icon-button command-touch-target" aria-label="Help">
          <Question aria-hidden="true" size={20} />
        </button>
        <button type="button" className="command-account-button command-touch-target" aria-label="Brandon account menu">
          <UserCircle aria-hidden="true" size={24} weight="fill" />
          <span>Brandon</span>
        </button>
      </div>
    </header>
  );
}
