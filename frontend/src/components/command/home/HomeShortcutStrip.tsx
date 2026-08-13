import Link from 'next/link';
import type { HomeShortcut } from '@/lib/command/home';

export function HomeShortcutStrip({ shortcuts }: { shortcuts: readonly HomeShortcut[] }) {
  return (
    <section className="command-home-shortcuts" aria-label="Home shortcuts">
      {shortcuts.map((shortcut) => (
        <Link key={shortcut.key} href={shortcut.href} className="command-home-shortcut command-touch-target">
          <span>{shortcut.label}</span>
          <strong>{shortcut.count === null ? 'Unavailable' : shortcut.count}</strong>
          <small>
            {shortcut.count === null
              ? 'Source data is unavailable for this shortcut.'
              : 'Observed internal records'}
          </small>
        </Link>
      ))}
    </section>
  );
}
