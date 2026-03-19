'use client';

import { useState, type FormEvent } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { LockSimple, LockOpen } from '@phosphor-icons/react';
import type { InvestorMetrics } from '@/lib/investor-calc';
import AnalysisResults from './AnalysisResults';

interface MeetingGateProps {
  isUnlocked: boolean;
  onUnlock: (email: string) => void;
  onBook: () => void;
  metrics: InvestorMetrics;
}

export default function MeetingGate({ isUnlocked, onUnlock, onBook, metrics }: MeetingGateProps) {
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setSubmitting(true);
    setError('');
    try {
      await onUnlock(email.trim());
    } catch {
      setError('Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AnimatePresence mode="wait">
      {!isUnlocked ? (
        <motion.div
          key="locked"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -16 }}
          transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
          className="glass border border-dark-border rounded-xl p-6 md:p-8"
        >
          {/* Blurred metric preview overlay */}
          <div
            className="absolute inset-0 rounded-xl pointer-events-none"
            style={{
              background:
                'radial-gradient(ellipse 70% 60% at 50% 0%, rgba(234,196,105,0.06) 0%, transparent 70%)',
            }}
            aria-hidden="true"
          />

          <div className="relative z-10 text-center">
            <div className="flex justify-center mb-4">
              <LockSimple weight="fill" className="w-8 h-8 text-gold" aria-hidden="true" />
            </div>

            <h3 className="text-white font-black text-xl md:text-2xl tracking-tight mb-2">
              Unlock Your Full Analysis
            </h3>
            <p className="text-white/50 text-sm font-light mb-6 max-w-xs mx-auto">
              Enter your email to see detailed projections for this deal.
            </p>

            <form onSubmit={handleSubmit} className="flex flex-col gap-3 max-w-sm mx-auto">
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="your@email.com"
                className="
                  w-full bg-dark-surface border border-dark-border text-white
                  placeholder:text-white/30 text-sm px-4 py-3 rounded-none
                  focus:outline-none focus:border-gold transition-colors duration-200
                "
              />
              {error && (
                <p className="text-red-400 text-xs text-left">{error}</p>
              )}
              <motion.button
                type="submit"
                disabled={submitting}
                whileHover={submitting ? undefined : { scale: 1.02 }}
                whileTap={submitting ? undefined : { scale: 0.98 }}
                transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
                className="
                  w-full bg-gold text-[#0a0a0a] font-bold text-sm tracking-widest uppercase
                  px-6 py-3 transition-colors duration-200 hover:bg-gold-hover
                  disabled:opacity-50 disabled:cursor-not-allowed
                "
              >
                {submitting ? 'Unlocking...' : 'Unlock Full Analysis'}
              </motion.button>
            </form>

            <p className="text-white/20 text-xs mt-4">
              No spam. No obligation. Instant access.
            </p>
          </div>
        </motion.div>
      ) : (
        <motion.div
          key="unlocked"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -16 }}
          transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
          className="space-y-6"
        >
          {/* Unlocked header */}
          <div className="glass border border-dark-border rounded-xl p-4 flex items-center gap-3">
            <LockOpen weight="fill" className="w-6 h-6 text-gold flex-shrink-0" aria-hidden="true" />
            <div>
              <p className="text-gold text-xs font-semibold tracking-[0.18em] uppercase">
                Analysis Unlocked
              </p>
              <p className="text-white/50 text-xs font-light">
                Full deal projections below
              </p>
            </div>
          </div>

          {/* Full analysis */}
          <AnalysisResults metrics={metrics} />

          {/* Book CTA */}
          <motion.button
            onClick={onBook}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
            className="
              w-full bg-gold text-[#0a0a0a] font-bold text-sm tracking-widest uppercase
              px-6 py-4 transition-colors duration-200 hover:bg-gold-hover
            "
          >
            Book a Strategy Call With Brandon
          </motion.button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
