'use client';

import { motion } from 'framer-motion';
import type { Strategy } from '@/lib/investor-calc';
import { STRATEGY_LABELS, STRATEGY_LIST, STRATEGY_TAGLINES } from './strategy-defaults';

interface StrategyToggleProps {
  value: Strategy;
  onChange: (next: Strategy) => void;
}

export default function StrategyToggle({ value, onChange }: StrategyToggleProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
      className="glass border border-dark-border rounded-xl p-4 md:p-5"
    >
      <div className="flex items-center gap-2 mb-3">
        <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase">
          Investment Strategy
        </p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {STRATEGY_LIST.map((s) => {
          const selected = s === value;
          return (
            <button
              key={s}
              type="button"
              onClick={() => onChange(s)}
              aria-pressed={selected}
              className={`px-4 py-3 text-sm font-semibold tracking-wide border transition-colors ${
                selected
                  ? 'bg-gold text-[#0a0a0a] border-gold'
                  : 'bg-dark-surface border-dark-border text-white/70 hover:border-gold/40 hover:text-white'
              }`}
            >
              {STRATEGY_LABELS[s]}
            </button>
          );
        })}
      </div>
      <p className="text-white/50 text-xs font-light mt-3">
        {STRATEGY_TAGLINES[value]}
      </p>
    </motion.div>
  );
}
