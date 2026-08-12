'use client';

import { X } from '@phosphor-icons/react';
import { useCallback, useRef } from 'react';
import type { ReactNode, RefObject } from 'react';
import { useFocusContainment } from '../shell/useFocusContainment';

export type CommandOverlayProps = Readonly<{
  variant?: 'dialog' | 'drawer';
  open: boolean;
  onOpenChange: (open: boolean) => void;
  labelledBy: string;
  triggerRef?: RefObject<HTMLElement | null>;
  children: ReactNode;
}>;

export function CommandOverlay({
  variant = 'dialog',
  open,
  onOpenChange,
  labelledBy,
  triggerRef,
  children,
}: CommandOverlayProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const dismiss = useCallback(() => onOpenChange(false), [onOpenChange]);

  useFocusContainment({
    active: open,
    containerRef: overlayRef,
    onDismiss: dismiss,
    restoreFocusRef: triggerRef,
  });

  if (!open) return null;

  return (
    <div className="command-overlay-layer">
      <button type="button" className="command-scrim" aria-label="Dismiss overlay" tabIndex={-1} onClick={dismiss} />
      <div
        ref={overlayRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        className={`command-overlay command-overlay-${variant}`}
        tabIndex={-1}
      >
        <button
          type="button"
          className="command-overlay-close command-icon-button command-touch-target"
          aria-label="Close detail"
          onClick={dismiss}
        >
          <X aria-hidden="true" size={20} />
        </button>
        <div className="command-overlay-content">{children}</div>
      </div>
    </div>
  );
}
