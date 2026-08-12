'use client';

import { useEffect } from 'react';
import type { RefObject } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export type FocusContainmentOptions = Readonly<{
  active: boolean;
  containerRef: RefObject<HTMLElement | null>;
  onDismiss: () => void;
  restoreFocusRef?: RefObject<HTMLElement | null>;
}>;

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => !element.hasAttribute('hidden') && element.getAttribute('aria-hidden') !== 'true',
  );
}

export function useFocusContainment({
  active,
  containerRef,
  onDismiss,
  restoreFocusRef,
}: FocusContainmentOptions): void {
  useEffect(() => {
    if (!active) return;

    const container = containerRef.current;
    if (!container) return;
    const focusContainer: HTMLElement = container;

    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const restoreTarget = restoreFocusRef?.current ?? previousFocus;
    const previousOverflow = document.body.style.overflow;

    document.body.style.overflow = 'hidden';
    const firstFocusable = focusableElements(focusContainer)[0];
    (firstFocusable ?? focusContainer).focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onDismiss();
        return;
      }

      if (event.key !== 'Tab') return;

      const focusable = focusableElements(focusContainer);
      if (focusable.length === 0) {
        event.preventDefault();
        focusContainer.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement;

      if (event.shiftKey && (activeElement === first || !focusContainer.contains(activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
      restoreTarget?.focus();
    };
  }, [active, containerRef, onDismiss, restoreFocusRef]);
}
