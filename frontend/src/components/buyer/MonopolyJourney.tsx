'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { DeviceMobile, HeartStraight, House, CaretDown, CheckCircle } from '@phosphor-icons/react';

interface Phase {
  id: number;
  label: string;
  title: string;
  description: string;
  steps: string[];
  Icon: React.ElementType;
}

const PHASES: Phase[] = [
  {
    id: 1,
    label: 'Phase 1',
    title: 'The Swiping Phase',
    description:
      'Before you start swiping Zillow, get your financial foundation in place. This is where serious buyers separate themselves from window shoppers.',
    steps: [
      'Pre-Approval for Budget',
      'Meet with Your REALTOR\u00ae',
      'Utilize Your Pre-Approval',
    ],
    Icon: DeviceMobile,
  },
  {
    id: 2,
    label: 'Phase 2',
    title: 'The Engagement Phase',
    description:
      'You\'ve done the prep work — now it\'s time to hit the market. You\'ll tour homes, fall in love, and learn how to win in a competitive environment.',
    steps: [
      'Showings & Open Houses',
      'Finding the ONE',
      'Edging Out the Competition',
    ],
    Icon: HeartStraight,
  },
  {
    id: 3,
    label: 'Phase 3',
    title: 'The Happily Ever After Phase',
    description:
      'Offer accepted — now we protect your investment. This phase covers every step from inspection to keys in hand.',
    steps: [
      'Home Inspection',
      '3rd Party Appraisal',
      'Commitment / Clear to Close',
      'Closing Time!',
    ],
    Icon: House,
  },
];

const SPRING = { type: 'spring' as const, stiffness: 100, damping: 20 };

export default function MonopolyJourney() {
  const [openId, setOpenId] = useState<number | null>(1);

  const toggle = (id: number) => setOpenId((prev) => (prev === id ? null : id));

  return (
    <section className="relative py-24 px-6 md:px-12 bg-[#0a0a0a]">
      {/* Section header */}
      <div className="max-w-7xl mx-auto">
        <div className="mb-12 max-w-2xl">
          <span className="inline-block text-gold text-xs font-semibold tracking-widest uppercase mb-4 border border-gold/30 px-3 py-1">
            The Process
          </span>
          <h2
            className="font-black text-white leading-tight tracking-tight"
            style={{ fontSize: 'clamp(2rem, 5vw, 3.5rem)' }}
          >
            Your Home Buying{' '}
            <span className="text-gold" style={{ textShadow: '0 0 30px rgba(234,196,105,0.3)' }}>
              Journey
            </span>
          </h2>
          <p className="text-gray mt-4 text-base leading-relaxed">
            Three phases. Every step mapped. No surprises — just a clear path from pre-approval to keys in hand.
          </p>
        </div>

        {/* Accordion */}
        <div className="flex flex-col gap-3">
          {PHASES.map((phase, idx) => {
            const isOpen = openId === phase.id;
            const { Icon } = phase;

            return (
              <motion.div
                key={phase.id}
                initial={{ opacity: 0, y: 24 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...SPRING, delay: idx * 0.1 }}
                className={`border rounded-none overflow-hidden transition-colors duration-300 ${
                  isOpen
                    ? 'border-gold/50 bg-dark-card'
                    : 'border-dark-border bg-dark-card/40 hover:border-gold/20'
                }`}
              >
                {/* Accordion trigger */}
                <button
                  onClick={() => toggle(phase.id)}
                  aria-expanded={isOpen}
                  className="w-full flex items-center gap-5 px-6 py-5 text-left group"
                >
                  {/* Phase number + icon */}
                  <div
                    className={`flex-shrink-0 w-12 h-12 flex items-center justify-center border transition-colors duration-300 ${
                      isOpen
                        ? 'bg-gold border-gold text-[#0a0a0a]'
                        : 'bg-transparent border-dark-border text-gold group-hover:border-gold/40'
                    }`}
                  >
                    <Icon weight="bold" className="w-5 h-5" />
                  </div>

                  <div className="flex-1 min-w-0">
                    <span
                      className={`text-xs font-semibold tracking-widest uppercase block mb-0.5 transition-colors duration-200 ${
                        isOpen ? 'text-gold' : 'text-gray'
                      }`}
                    >
                      {phase.label}
                    </span>
                    <span className="text-white font-bold text-lg leading-tight">{phase.title}</span>
                  </div>

                  {/* Caret */}
                  <motion.span
                    animate={{ rotate: isOpen ? 180 : 0 }}
                    transition={SPRING}
                    className={`flex-shrink-0 transition-colors duration-200 ${
                      isOpen ? 'text-gold' : 'text-gray'
                    }`}
                  >
                    <CaretDown weight="bold" className="w-5 h-5" />
                  </motion.span>
                </button>

                {/* Accordion panel */}
                <AnimatePresence initial={false}>
                  {isOpen && (
                    <motion.div
                      key="panel"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={SPRING}
                      className="overflow-hidden"
                    >
                      <div className="px-6 pb-7 pt-1 border-t border-dark-border">
                        <p className="text-gray text-sm leading-relaxed mb-6 max-w-2xl">
                          {phase.description}
                        </p>

                        {/* Steps */}
                        <ul className="flex flex-col gap-3">
                          {phase.steps.map((step, sIdx) => (
                            <motion.li
                              key={step}
                              initial={{ opacity: 0, x: -12 }}
                              animate={{ opacity: 1, x: 0 }}
                              transition={{ ...SPRING, delay: sIdx * 0.07 }}
                              className="flex items-center gap-3"
                            >
                              <CheckCircle
                                weight="fill"
                                className="text-gold w-4 h-4 flex-shrink-0"
                              />
                              <span className="text-white/85 text-sm font-medium">{step}</span>
                            </motion.li>
                          ))}
                        </ul>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
