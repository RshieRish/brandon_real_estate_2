import type { ReactNode } from 'react';
import { ArrowClockwise, CircleNotch, Info, WarningCircle } from '@phosphor-icons/react';

export type CommandStateKind =
  | 'loading'
  | 'first_run'
  | 'empty'
  | 'evidence_only'
  | 'partial_capture'
  | 'error';

type CommandStatePanelBaseProps = Readonly<{
  title: string;
  message: string;
  children?: ReactNode;
}>;

export type CommandStatePanelProps = CommandStatePanelBaseProps & (
  | Readonly<{
      kind: 'error';
      actionLabel: string;
      onAction: () => void;
    }>
  | Readonly<{
      kind: Exclude<CommandStateKind, 'error'>;
      actionLabel?: string;
      onAction?: () => void;
    }>
);

export function CommandStatePanel({
  kind,
  title,
  message,
  actionLabel,
  onAction,
  children,
}: CommandStatePanelProps) {
  const Icon = kind === 'loading' ? CircleNotch : kind === 'error' ? WarningCircle : Info;
  const semanticProps = kind === 'loading'
    ? { role: 'status', 'aria-label': title }
    : kind === 'error'
      ? { role: 'alert' }
      : {};

  return (
    <section className={`command-state-panel is-${kind}`} {...semanticProps}>
      <Icon
        aria-hidden="true"
        size={kind === 'loading' ? 28 : 25}
        className={kind === 'loading' ? 'command-state-spinner' : undefined}
      />
      <div>
        <h3>{title}</h3>
        <p>{message}</p>
        {kind === 'loading' ? (
          <div className="command-state-skeleton" aria-hidden="true">
            <span className="command-state-skeleton-line" />
            <span className="command-state-skeleton-line" />
            <span className="command-state-skeleton-line" />
          </div>
        ) : null}
        {children}
      </div>
      {actionLabel && onAction ? (
        <button type="button" className="command-secondary-button" onClick={onAction}>
          {kind === 'error' ? <ArrowClockwise aria-hidden="true" size={17} /> : null}
          {actionLabel}
        </button>
      ) : null}
    </section>
  );
}
