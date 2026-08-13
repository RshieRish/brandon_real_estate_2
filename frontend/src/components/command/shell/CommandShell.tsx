'use client';

import type { ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { CommandToastProvider } from '../ui/CommandToastProvider';
import { CommandMobileNavigation } from './CommandMobileNavigation';
import { CommandRail } from './CommandRail';
import { CommandUtilityHeader } from './CommandUtilityHeader';

export function CommandShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="command-root">
      <CommandToastProvider>
        <a className="command-skip-link command-print-hidden" href="#command-main">
          Skip to workspace content
        </a>
        <CommandRail key={`rail-${pathname}`} />
        <CommandUtilityHeader key={`header-${pathname}`} />
        <CommandMobileNavigation key={`mobile-${pathname}`} />
        <div className="command-canvas">
          <main id="command-main" className="command-main" tabIndex={-1}>
            {children}
          </main>
        </div>
      </CommandToastProvider>
    </div>
  );
}
