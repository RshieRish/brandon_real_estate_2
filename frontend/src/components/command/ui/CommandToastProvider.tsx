'use client';

import { X } from '@phosphor-icons/react';
import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

export type CommandToastTone = 'success' | 'info' | 'warning' | 'error';

export type CommandToastInput = Readonly<{
  tone: CommandToastTone;
  message: string;
  undoLabel?: string;
  onUndo?: () => void;
}>;

type CommandToast = CommandToastInput & Readonly<{ id: number }>;

type CommandToastContextValue = Readonly<{
  pushToast: (toast: CommandToastInput) => void;
}>;

const CommandToastContext = createContext<CommandToastContextValue | null>(null);

function ToastList({
  toasts,
  dismiss,
}: {
  toasts: readonly CommandToast[];
  dismiss: (id: number) => void;
}) {
  return (
    <div className="command-toast-list">
      {toasts.map((toast) => (
        <div key={toast.id} className={`command-toast is-${toast.tone}`}>
          <span>{toast.message}</span>
          {toast.onUndo ? (
            <button
              type="button"
              onClick={() => {
                toast.onUndo?.();
                dismiss(toast.id);
              }}
            >
              {toast.undoLabel ?? 'Undo'}
            </button>
          ) : null}
          <button type="button" aria-label={`Dismiss ${toast.message}`} onClick={() => dismiss(toast.id)}>
            <X aria-hidden="true" size={16} />
          </button>
        </div>
      ))}
    </div>
  );
}

export function CommandToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<readonly CommandToast[]>([]);
  const nextId = useRef(1);
  const pushToast = useCallback((toast: CommandToastInput) => {
    setToasts((current) => [...current, { ...toast, id: nextId.current++ }]);
  }, []);
  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);
  const context = useMemo(() => ({ pushToast }), [pushToast]);
  const politeToasts = toasts.filter((toast) => toast.tone === 'success' || toast.tone === 'info');
  const assertiveToasts = toasts.filter((toast) => toast.tone === 'warning' || toast.tone === 'error');

  return (
    <CommandToastContext.Provider value={context}>
      {children}
      <div className="command-toast-viewport command-print-hidden">
        {politeToasts.length > 0 ? (
          <div role="status" aria-live="polite" aria-atomic="true">
            <ToastList toasts={politeToasts} dismiss={dismiss} />
          </div>
        ) : null}
        {assertiveToasts.length > 0 ? (
          <div role="alert" aria-live="assertive" aria-atomic="true">
            <ToastList toasts={assertiveToasts} dismiss={dismiss} />
          </div>
        ) : null}
      </div>
    </CommandToastContext.Provider>
  );
}

export function useCommandToast(): CommandToastContextValue {
  const context = useContext(CommandToastContext);
  if (!context) throw new Error('useCommandToast must be used within CommandToastProvider');
  return context;
}
