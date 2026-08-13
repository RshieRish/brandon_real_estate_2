'use client';

import Link from 'next/link';
import { Plus, Question, UserCircle } from '@phosphor-icons/react';
import { usePathname } from 'next/navigation';
import { findCommandDestination } from './commandNavigation';
import { CommandGlobalSearch } from './CommandGlobalSearch';

export function CommandUtilityHeader() {
  const pathname = usePathname();
  const destination = findCommandDestination(pathname);

  return (
    <header className="command-utility-header command-print-hidden">
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
        <a
          href="mailto:info@soldwithsweeney.com?subject=Command%20workspace%20help"
          className="command-icon-button command-touch-target"
          aria-label="Get Command help"
        >
          <Question aria-hidden="true" size={20} />
        </a>
        <Link
          href="/admin/settings"
          className="command-account-button command-touch-target"
          aria-label="Brandon account settings"
        >
          <UserCircle aria-hidden="true" size={24} weight="fill" />
          <span>Brandon</span>
        </Link>
      </div>
    </header>
  );
}
