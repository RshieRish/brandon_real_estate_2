'use client';

interface Props {
  current: string;
  onChange: (tab: string) => void;
}

const TABS = ['profile', 'social', 'links', 'theme'] as const;

export default function Tabs({ current, onChange }: Props) {
  return (
    <div className="flex border-b border-dark-border">
      {TABS.map(t => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className={`px-5 py-3 text-xs font-bold uppercase tracking-widest transition-colors cursor-pointer ${
            current === t
              ? 'text-gold border-b-2 border-gold'
              : 'text-white/40 hover:text-white/70'
          }`}
        >
          {t}
        </button>
      ))}
    </div>
  );
}
