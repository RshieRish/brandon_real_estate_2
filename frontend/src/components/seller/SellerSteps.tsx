'use client';

import { useRef } from 'react';
import { motion, useInView } from 'framer-motion';
import {
  MagnifyingGlass,
  Camera,
  Storefront,
  Handshake,
  Key,
} from '@phosphor-icons/react';

const STEPS = [
  {
    number: 1,
    label: 'Prepare',
    icon: MagnifyingGlass,
    description:
      'Brandon conducts a thorough home tour and listing appointment to assess your property, understand your goals, and build a winning pricing strategy.',
    details: ['Home tour & condition review', 'Listing appointment consultation', 'Pricing strategy analysis', 'Timeline planning'],
  },
  {
    number: 2,
    label: 'Pre-Listing',
    icon: Camera,
    description:
      'Professional staging guidance, high-quality photography, and fully branded marketing materials are prepared before your home ever hits the market.',
    details: ['Professional staging guidance', 'HDR photography & video walkthrough', 'Branded marketing materials', '3D virtual tour'],
  },
  {
    number: 3,
    label: 'Listing Time',
    icon: Storefront,
    description:
      'Your home goes live across every major platform simultaneously — MLS, Zillow, Realtor.com, and a full social media campaign — generating maximum exposure.',
    details: ['MLS + syndication launch', 'Zillow & Realtor.com featured', 'Social media campaign', 'Open house scheduling'],
  },
  {
    number: 4,
    label: 'Offer Process',
    icon: Handshake,
    description:
      'Brandon reviews every offer with you in plain language, negotiates aggressively on your behalf, and guides you to the strongest possible terms.',
    details: ['Offer review & analysis', 'Expert negotiation', 'Contingency strategy', 'Counter-offer guidance'],
  },
  {
    number: 5,
    label: 'Closing Time',
    icon: Key,
    description:
      'From the final walkthrough to handing over keys, Brandon coordinates every detail so closing day is smooth, stress-free, and celebratory.',
    details: ['Final walkthrough coordination', 'Closing document review', 'Closing day attendance', 'Post-sale follow-up'],
  },
] as const;

const containerVariants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.18, delayChildren: 0.1 },
  },
};

const stepVariants = {
  hidden: { opacity: 0, x: -40 },
  show: {
    opacity: 1,
    x: 0,
    transition: { type: 'spring' as const, stiffness: 100, damping: 20 },
  },
};

export default function SellerSteps() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: '-80px' });

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
          transition={{ type: 'spring', stiffness: 100, damping: 20 }}
          className="mb-16 md:mb-20"
        >
          <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
            The Process
          </p>
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
            A proven five-step system refined over hundreds of transactions — designed to maximize your
            sale price and minimize your stress.
          </p>
        </motion.div>

        {/* Timeline */}
        <motion.div
          ref={ref}
          variants={containerVariants}
          initial="hidden"
          animate={isInView ? 'show' : 'hidden'}
          className="relative"
        >
          {/* Vertical connector line */}
          <div
            className="absolute left-[27px] md:left-[31px] top-0 bottom-0 w-px bg-gradient-to-b from-gold/60 via-gold/20 to-transparent"
            aria-hidden="true"
          />

          <div className="flex flex-col gap-0">
            {STEPS.map((step, index) => {
              const Icon = step.icon;
              const isLast = index === STEPS.length - 1;

              return (
                <motion.div
                  key={step.number}
                  variants={stepVariants}
                  className={`relative flex gap-6 md:gap-10 ${isLast ? '' : 'pb-12 md:pb-16'}`}
                >
                  {/* Step circle */}
                  <div className="relative flex-shrink-0 z-10">
                    <div
                      className="w-14 h-14 md:w-16 md:h-16 rounded-full border-2 border-gold bg-dark-card flex items-center justify-center"
                      style={{ boxShadow: '0 0 20px rgba(234,196,105,0.15)' }}
                    >
                      <span className="text-gold font-black text-lg md:text-xl leading-none">
                        {step.number}
                      </span>
                    </div>
                  </div>

                  {/* Content card */}
                  <div className="flex-1 min-w-0 pb-2">
                    <motion.div
                      className="glass border border-dark-border rounded-xl p-6 md:p-8"
                      whileHover={{ y: -3, boxShadow: '0 8px 32px rgba(234,196,105,0.08)' }}
                      transition={{ type: 'spring', stiffness: 100, damping: 20 }}
                    >
                      {/* Step label row */}
                      <div className="flex items-center gap-3 mb-3">
                        <Icon weight="duotone" className="w-5 h-5 text-gold flex-shrink-0" />
                        <h3 className="font-bold text-white text-lg tracking-wide uppercase">
                          {step.label}
                        </h3>
                        <span className="ml-auto text-gold/40 text-xs font-semibold tracking-widest uppercase">
                          Step {step.number}
                        </span>
                      </div>

                      {/* Description */}
                      <p className="text-white/60 text-sm leading-relaxed font-light mb-4">
                        {step.description}
                      </p>

                      {/* Detail pills */}
                      <div className="flex flex-wrap gap-2">
                        {step.details.map((detail) => (
                          <span
                            key={detail}
                            className="text-xs text-gold/70 border border-gold/20 bg-gold/5 px-3 py-1 font-medium tracking-wide"
                          >
                            {detail}
                          </span>
                        ))}
                      </div>
                    </motion.div>
                  </div>
                </motion.div>
              );
            })}
          </div>
        </motion.div>
      </div>
    </section>
  );
}
