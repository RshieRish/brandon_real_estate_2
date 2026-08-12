'use client';

import type { ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { CommandMobileNavigation } from './CommandMobileNavigation';
import { CommandRail } from './CommandRail';
import { CommandUtilityHeader } from './CommandUtilityHeader';

export function CommandShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="command-root">
      <CommandRail key={`rail-${pathname}`} />
      <CommandUtilityHeader key={`header-${pathname}`} />
      <CommandMobileNavigation key={`mobile-${pathname}`} />
      <div className="command-canvas">
        <main id="command-main" className="command-main" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
