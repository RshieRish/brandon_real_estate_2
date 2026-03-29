'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  MagnifyingGlass,
  Camera,
  Storefront,
  Handshake,
  ClipboardText,
  Key,
  CaretDown,
  CheckCircle,
} from '@phosphor-icons/react';

interface Step {
  id: number;
  label: string;
  title: string;
  description: string;
  details: string[];
  Icon: React.ElementType;
}

const STEPS: Step[] = [
  {
    id: 1,
    label: 'Step 1',
    title: 'Prepare',
    Icon: MagnifyingGlass,
    description:
      'Brandon conducts a thorough home tour and seller consultation to assess your property, understand your goals, and build a winning pricing strategy.',
    details: ['Home tour & condition review', 'Seller consultation', 'Pricing strategy analysis', 'Timeline planning'],
  },
  {
    id: 2,
    label: 'Step 2',
    title: 'Pre-Listing',
    Icon: Camera,
    description:
      'Professional staging guidance, high-quality photography, and fully branded marketing materials are prepared before your home ever hits the market.',
    details: ['Professional staging guidance', 'HDR photography & video walkthrough', 'Branded marketing materials', '3D virtual tour'],
  },
  {
    id: 3,
    label: 'Step 3',
    title: 'Listing Time',
    Icon: Storefront,
    description:
      'Your home goes live across every major platform simultaneously — MLS, Zillow, Realtor.com, Homes.com, and a full social media campaign — generating maximum exposure.',
    details: ['MLS + syndication launch', 'Zillow, Realtor.com, Homes.com & more', 'Social media campaign', 'Open house scheduling'],
  },
  {
    id: 4,
    label: 'Step 4',
    title: 'Offer Process',
    Icon: Handshake,
    description:
      'Brandon reviews every offer with you in plain language, negotiates aggressively on your behalf, and guides you to the strongest possible terms.',
    details: ['Offer review & analysis', 'Expert negotiation', 'Contingency strategy', 'Counter-offer guidance'],
  },
  {
    id: 5,
    label: 'Step 5',
    title: 'Under Contract',
    Icon: ClipboardText,
    description:
      'Brandon coordinates every contingency from accepted offer to clear-to-close — inspections, appraisal, loan commitment, and all required documentation.',
    details: ['Home inspection coordination', 'Appraisal & loan commitment', 'Smoke certificate (MA)', "Buyer's agent, lender & attorney coordination"],
  },
  {
    id: 6,
    label: 'Step 6',
    title: 'Closing Time',
    Icon: Key,
    description:
      'From the final walkthrough to handing over keys, Brandon coordinates every detail so closing day is smooth, stress-free, and celebratory.',
    details: ['Final walkthrough coordination', 'Closing document review', 'Closing day attendance', 'Post-sale follow-up'],
  },
];

const SPRING = { type: 'spring' as const, stiffness: 100, damping: 20 };

export default function SellerSteps() {
  const [openId, setOpenId] = useState<number | null>(1);

  const toggle = (id: number) => setOpenId((prev) => (prev === id ? null : id));

  return (
    <section className="relative bg-dark-surface py-24 md:py-32 overflow-hidden">
      {/* Halftone texture */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(circle, #eac469 1px, transparent 1px)',
          backgroundSize: '24px 24px',
          opacity: 0.025,
        }}
        aria-hidden="true"
      />

      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={SPRING}
          className="mb-16 md:mb-20"
        >
          <span className="inline-block text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4 border border-gold/30 px-3 py-1">
            The Process
          </span>
          <h2
            className="font-black text-white leading-tight tracking-tight"
            style={{ fontSize: 'clamp(2rem, 4vw, 3.5rem)' }}
          >
            How We Get You{' '}
            <span className="text-gold" style={{ textShadow: '0 0 30px rgba(234,196,105,0.25)' }}>
              Sold
            </span>
          </h2>
          <p className="text-white/60 mt-4 max-w-xl text-base font-light leading-relaxed">
            A proven six-step system refined over hundreds of transactions — designed to maximize your
            sale price and minimize your stress.
          </p>
        </motion.div>

        {/* Accordion */}
        <div className="flex flex-col gap-3">
          {STEPS.map((step, idx) => {
            const isOpen = openId === step.id;
            const { Icon } = step;

            return (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, y: 24 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...SPRING, delay: idx * 0.08 }}
                className={`border rounded-none overflow-hidden transition-colors duration-300 ${
                  isOpen
                    ? 'border-gold/50 bg-dark-card'
                    : 'border-dark-border bg-dark-card/40 hover:border-gold/20'
                }`}
              >
                {/* Accordion trigger */}
                <button
                  onClick={() => toggle(step.id)}
                  aria-expanded={isOpen}
                  className="w-full flex items-center gap-5 px-6 py-5 text-left group"
                >
                  {/* Icon box */}
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
                      {step.label}
                    </span>
                    <span className="text-white font-bold text-lg leading-tight">{step.title}</span>
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
                          {step.description}
                        </p>

                        {/* Detail items */}
                        <ul className="flex flex-col gap-3">
                          {step.details.map((detail, dIdx) => (
                            <motion.li
                              key={detail}
                              initial={{ opacity: 0, x: -12 }}
                              animate={{ opacity: 1, x: 0 }}
                              transition={{ ...SPRING, delay: dIdx * 0.07 }}
                              className="flex items-center gap-3"
                            >
                              <CheckCircle weight="fill" className="text-gold w-4 h-4 flex-shrink-0" />
                              <span className="text-white/85 text-sm font-medium">{detail}</span>
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
