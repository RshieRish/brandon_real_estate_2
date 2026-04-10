'use client';

import { useEffect, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { CheckCircle, CornersOut, XCircle } from '@phosphor-icons/react';

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
      "Browsing homes without a pre-approval letter puts you at a severe disadvantage. Sellers and their agents won't take you seriously, and you risk falling in love with a home you can't afford.",
    fix: "Get pre-approved before your first showing. A pre-approval letter tells sellers you're a serious, qualified buyer and gives you a clear budget so you shop with confidence.",
  },
  {
    id: 2,
    mistake: 'Using all your savings for the down payment',
    mistakeDetail:
      'Draining every dollar into the down payment leaves you dangerously exposed. Closing costs, moving expenses, and unexpected repairs can all arrive at once.',
    fix: 'Budget for closing costs, keep a reserves fund for immediate repairs, and factor in moving expenses. A slightly lower down payment with healthy reserves is often the smarter move.',
  },
  {
    id: 3,
    mistake: 'Buying with the listing agent',
    mistakeDetail:
      "The listing agent's fiduciary duty is to the seller, not you. Going in without your own representation means negotiating against someone hired to get the seller the best outcome.",
    fix: "Work with a dedicated buyer's agent representing your interests. Brandon's sole job is to protect your price, terms, leverage, and clarity from offer to close.",
  },
  {
    id: 4,
    mistake: 'Picking a lender based on rate alone',
    mistakeDetail:
      'Rates may be similar across lenders, but communication, problem solving, and the ability to close on time are not. A lender who disappears can cost you the house.',
    fix: 'Choose a lender with a proven reputation for speed, communication, and execution. Brandon connects buyers with trusted local lenders who can actually help win the deal.',
  },
];

const SPRING = { type: 'spring' as const, stiffness: 100, damping: 20 };
const AUTO_ADVANCE_MS = 4200;

export default function BuyerMistakes() {
  const prefersReducedMotion = useReducedMotion();
  const [rotationIndex, setRotationIndex] = useState(0);
  const [isPaused, setIsPaused] = useState(false);
  const [flippedCards, setFlippedCards] = useState<Record<number, boolean>>({});

  useEffect(() => {
    if (prefersReducedMotion || isPaused) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      setRotationIndex((current) => (current + 1) % MISTAKES.length);
    }, AUTO_ADVANCE_MS);

    return () => window.clearInterval(intervalId);
  }, [isPaused, prefersReducedMotion]);

  const currentMistake = MISTAKES[rotationIndex];
  const isCurrentFlipped = Boolean(flippedCards[currentMistake.id]);

  const toggleCard = (id: number) => {
    setFlippedCards((current) => ({
      ...current,
      [id]: !current[id],
    }));
  };

  return (
    <section className="relative overflow-hidden bg-dark-card px-6 py-24 md:px-12">
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(circle, #eac469 1px, transparent 1px)',
          backgroundSize: '24px 24px',
          opacity: 0.025,
        }}
        aria-hidden="true"
      />

      <div className="relative mx-auto max-w-7xl">
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)] lg:items-center lg:gap-14">
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-80px' }}
            transition={SPRING}
            className="lg:sticky lg:top-28 self-start"
          >
            <div className="max-w-xl">
              <div className="mb-4 flex items-center gap-3">
                <span className="border border-gold/30 px-3 py-1 text-xs font-semibold uppercase tracking-widest text-gold">
                  Common Mistakes
                </span>
              </div>
              <h2
                className="font-black leading-tight tracking-tight text-white"
                style={{ fontSize: 'clamp(1.75rem, 4.5vw, 3rem)' }}
              >
                What Most Buyers{' '}
                <span
                  className="text-gold"
                  style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}
                >
                  Get Wrong
                </span>
              </h2>
              <p className="mt-5 max-w-lg text-sm leading-relaxed text-gray">
                The biggest buyer mistakes now rotate through one focused card at a time. Let it
                cycle on its own or tap the card whenever you want to flip from the mistake to
                Brandon&apos;s fix.
              </p>
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 28 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-80px' }}
            transition={{ ...SPRING, delay: 0.08 }}
          >
            <div
              className="relative overflow-hidden rounded-[36px] border border-dark-border bg-[#050505] p-3 shadow-[0_40px_120px_rgba(0,0,0,0.55)] sm:p-4"
              onMouseEnter={() => setIsPaused(true)}
              onMouseLeave={() => setIsPaused(false)}
            >
              <div
                className="absolute inset-0 opacity-60"
                style={{
                  background:
                    'linear-gradient(180deg, rgba(234,196,105,0.08) 0%, rgba(255,255,255,0.01) 28%, rgba(255,255,255,0.02) 100%)',
                }}
                aria-hidden="true"
              />
              <div
                className="absolute inset-0 opacity-40"
                style={{
                  backgroundImage:
                    'radial-gradient(circle at top right, rgba(234,196,105,0.18), transparent 26%), radial-gradient(circle at bottom left, rgba(255,255,255,0.06), transparent 30%)',
                }}
                aria-hidden="true"
              />

              <motion.button
                type="button"
                onClick={() => toggleCard(currentMistake.id)}
                className={`relative min-h-[420px] w-full overflow-hidden rounded-[30px] border p-0 text-left transition-colors duration-300 md:min-h-[500px] ${
                  isCurrentFlipped ? 'border-gold/35 bg-[#100e08]' : 'border-white/10 bg-[#0a0a0a]'
                }`}
                whileHover={{ y: -4, borderColor: 'rgba(234,196,105,0.55)' }}
                whileTap={{ scale: 0.995 }}
                transition={SPRING}
                aria-pressed={isCurrentFlipped}
              >
                <div
                  className="absolute inset-0"
                  style={{
                    background: isCurrentFlipped
                      ? 'linear-gradient(135deg, rgba(234,196,105,0.18), rgba(255,255,255,0.02) 48%, rgba(192,130,53,0.16))'
                      : 'linear-gradient(135deg, rgba(255,255,255,0.06), rgba(255,255,255,0.01) 48%, rgba(255,255,255,0.03))',
                  }}
                  aria-hidden="true"
                />
                <div className="absolute inset-px rounded-[29px] border border-white/5" aria-hidden="true" />

                <div className="relative flex min-h-[420px] flex-col justify-between p-6 md:min-h-[500px] md:p-8">
                  {/* Right side vertical indicator */}
                  <div className="absolute right-5 top-1/2 flex -translate-y-1/2 flex-col items-center gap-6 md:right-8">
                    <div className="flex flex-col items-center gap-2">
                      {MISTAKES.map((item, index) => (
                        <span
                          key={item.id}
                          className={`w-1.5 rounded-full transition-all duration-300 ${
                            index === rotationIndex ? 'h-8 bg-gold' : 'h-1.5 bg-white/15'
                          }`}
                          aria-hidden="true"
                        />
                      ))}
                    </div>
                    <span className="text-[10px] font-semibold uppercase tracking-[0.28em] text-white/30">
                      0{rotationIndex + 1}
                    </span>
                  </div>

                  <div className="flex items-start justify-end">
                    <span className="inline-flex items-center gap-2 text-[10px] uppercase tracking-[0.24em] text-white/25">
                      <CornersOut weight="bold" className="h-4 w-4" />
                      {isCurrentFlipped ? 'Tap to flip back' : 'Tap to flip'}
                    </span>
                  </div>

                  <div className="relative mt-8 flex-1 overflow-hidden pr-10 md:pr-12">
                    <AnimatePresence mode="wait" initial={false}>
                      {isCurrentFlipped ? (
                        <motion.div
                          key={`${currentMistake.id}-fix`}
                          initial={{ opacity: 0, y: 40 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -40 }}
                          transition={SPRING}
                          className="flex h-full flex-col justify-between"
                        >
                          <div>
                            <span className="inline-flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.24em] text-gold">
                              <CheckCircle weight="fill" className="h-4 w-4" />
                              The Fix
                            </span>
                            <h3 className="mt-5 max-w-xl text-[clamp(1.9rem,3vw,2.8rem)] font-black leading-[0.95] tracking-tight text-white">
                              {currentMistake.mistake}
                            </h3>
                            <p className="mt-6 max-w-2xl text-base leading-relaxed text-white/80 md:text-lg">
                              {currentMistake.fix}
                            </p>
                          </div>

                          <div className="mt-10 h-px w-full bg-gradient-to-r from-gold/40 via-white/10 to-transparent" />
                        </motion.div>
                      ) : (
                        <motion.div
                          key={`${currentMistake.id}-mistake`}
                          initial={{ opacity: 0, y: 40 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -40 }}
                          transition={SPRING}
                          className="flex h-full flex-col justify-between"
                        >
                          <div>
                            <span className="inline-flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.24em] text-red-400">
                              <XCircle weight="fill" className="h-4 w-4" />
                              Buyer Mistake
                            </span>
                            <h3 className="mt-5 max-w-xl text-[clamp(1.9rem,3vw,2.8rem)] font-black leading-[0.95] tracking-tight text-white">
                              {currentMistake.mistake}
                            </h3>
                            <p className="mt-6 max-w-2xl text-base leading-relaxed text-white/60 md:text-lg">
                              {currentMistake.mistakeDetail}
                            </p>
                          </div>

                          <div className="mt-10 h-px w-full bg-gradient-to-r from-white/15 via-white/10 to-transparent" />
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </div>
              </motion.button>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
