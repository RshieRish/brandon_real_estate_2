'use client';

import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowArcRight, CheckCircle, CornersOut, XCircle } from '@phosphor-icons/react';

interface Mistake {
  id: number;
  mistake: string;
  mistakeDetail: string;
  fix: string;
}

const MISTAKES: Mistake[] = [
  {
    id: 1,
    mistake: 'Shopping before pre-approval',
    mistakeDetail:
      'Browsing homes without a pre-approval letter puts you at a severe disadvantage. Sellers and their agents won\'t take you seriously, and you risk falling in love with a home you can\'t afford.',
    fix: 'Get pre-approved before your first showing. A pre-approval letter tells sellers you\'re a serious, qualified buyer — and gives you a clear budget so you shop with confidence.',
  },
  {
    id: 2,
    mistake: 'Using all your savings for the down payment',
    mistakeDetail:
      'Draining every dollar into the down payment leaves you dangerously exposed. Closing costs, moving expenses, and unexpected repairs can arrive all at once.',
    fix: 'Budget for closing costs (2–5% of the purchase price), keep a reserves fund for immediate repairs, and factor in moving costs. A slightly lower down payment with healthy reserves is often smarter.',
  },
  {
    id: 3,
    mistake: 'Buying with the listing agent',
    mistakeDetail:
      'The listing agent\'s fiduciary duty is to the seller — not you. Working without your own representation means you\'re negotiating against someone whose job is to get the seller the highest price.',
    fix: 'Always have a dedicated buyer\'s agent representing your interests. Brandon provides exclusive buyer representation where his sole job is to get you the home for the best price with the best terms for you.',
  },
  {
    id: 4,
    mistake: 'Picking a lender based on rate alone',
    mistakeDetail:
      'Rates are similar across lenders — but customer service, communication, and ability to close on time are not. A lender who goes dark or misses a deadline can cost you the deal entirely.',
    fix: 'Choose a lender with a proven track record: fast communication, deep knowledge, and the ability to close on time. Brandon works with trusted local lenders who guide you through every step and fight for your timeline.',
  },
];

const SPRING = { type: 'spring' as const, stiffness: 100, damping: 20 };

export default function BuyerMistakes() {
  const [activeCard, setActiveCard] = useState<number>(1);

  return (
    <section className="relative py-24 px-6 md:px-12 bg-dark-card">
      {/* Subtle halftone */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(circle, #eac469 1px, transparent 1px)',
          backgroundSize: '24px 24px',
          opacity: 0.025,
        }}
        aria-hidden="true"
      />

      <div className="relative max-w-7xl mx-auto">
        {/* Header — asymmetric */}
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6 mb-14">
          <div className="max-w-xl">
            <div className="flex items-center gap-3 mb-4">
              <span className="text-gold text-xs font-semibold tracking-widest uppercase border border-gold/30 px-3 py-1">
                Common Mistakes
              </span>
            </div>
            <h2
              className="font-black text-white leading-tight tracking-tight"
              style={{ fontSize: 'clamp(1.75rem, 4.5vw, 3rem)' }}
            >
              What Most Buyers{' '}
              <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}>
                Get Wrong
              </span>
            </h2>
          </div>
          <p className="text-gray text-sm leading-relaxed max-w-sm md:text-right">
            Tap each flashcard to flip from the mistake to the move that keeps your deal clean,
            competitive, and protected.
          </p>
        </div>

        {/* Flashcard grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {MISTAKES.map((item, idx) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, y: 28 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ ...SPRING, delay: idx * 0.09 }}
              className="min-h-[320px]"
            >
              <motion.button
                type="button"
                onClick={() => setActiveCard((current) => (current === item.id ? 0 : item.id))}
                className="group relative h-full w-full overflow-hidden border border-dark-border bg-[#0a0a0a] p-0 text-left transition-colors duration-300 hover:border-gold/30"
                whileHover={{ y: -3 }}
                whileTap={{ scale: 0.99 }}
                transition={SPRING}
                aria-expanded={activeCard === item.id}
              >
                <div
                  className="absolute inset-0 opacity-70"
                  style={{
                    background:
                      activeCard === item.id
                        ? 'linear-gradient(145deg, rgba(234,196,105,0.12), rgba(255,255,255,0.02) 55%, rgba(234,196,105,0.08))'
                        : 'linear-gradient(145deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01) 55%, rgba(255,255,255,0.02))',
                  }}
                  aria-hidden="true"
                />
                <div className="absolute inset-px border border-white/4" aria-hidden="true" />
                <AnimatePresence mode="wait" initial={false}>
                  {activeCard === item.id ? (
                    <motion.div
                      key="back"
                      initial={{ opacity: 0, rotateY: -90 }}
                      animate={{ opacity: 1, rotateY: 0 }}
                      exit={{ opacity: 0, rotateY: 90 }}
                      transition={SPRING}
                      className="relative flex h-full min-h-[320px] flex-col justify-between gap-6 p-6 md:p-7"
                    >
                      <div>
                        <div className="mb-5 flex items-center justify-between gap-3">
                          <span className="inline-flex items-center gap-2 text-gold text-[10px] font-semibold tracking-[0.24em] uppercase">
                            <CheckCircle weight="fill" className="w-4 h-4" />
                            The Fix
                          </span>
                          <span className="text-white/25 text-[10px] tracking-[0.24em] uppercase">
                            Tap to flip back
                          </span>
                        </div>
                        <h3 className="text-white text-xl font-black leading-tight tracking-tight mb-4">
                          {item.mistake}
                        </h3>
                        <p className="text-white/75 text-sm leading-relaxed">
                          {item.fix}
                        </p>
                      </div>

                      <div className="flex items-center gap-2 text-gold/70 text-[11px] font-semibold tracking-[0.18em] uppercase">
                        <ArrowArcRight weight="bold" className="w-4 h-4" />
                        Brandon's buyer strategy
                      </div>
                    </motion.div>
                  ) : (
                    <motion.div
                      key="front"
                      initial={{ opacity: 0, rotateY: 90 }}
                      animate={{ opacity: 1, rotateY: 0 }}
                      exit={{ opacity: 0, rotateY: -90 }}
                      transition={SPRING}
                      className="relative flex h-full min-h-[320px] flex-col justify-between gap-6 p-6 md:p-7"
                    >
                      <div>
                        <div className="mb-5 flex items-center justify-between gap-3">
                          <span className="inline-flex items-center gap-2 text-red-400 text-[10px] font-semibold tracking-[0.24em] uppercase">
                            <XCircle weight="fill" className="w-4 h-4" />
                            Buyer Mistake
                          </span>
                          <span className="inline-flex items-center gap-2 text-white/25 text-[10px] tracking-[0.24em] uppercase">
                            <CornersOut weight="bold" className="w-4 h-4" />
                            Tap to flip
                          </span>
                        </div>
                        <h3 className="text-white text-xl font-black leading-tight tracking-tight mb-4">
                          {item.mistake}
                        </h3>
                        <p className="text-white/55 text-sm leading-relaxed">
                          {item.mistakeDetail}
                        </p>
                      </div>

                      <div className="pt-5 border-t border-dark-border">
                        <p className="text-gold/75 text-[11px] font-semibold tracking-[0.2em] uppercase">
                          Flip for Brandon&apos;s move
                        </p>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.button>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
