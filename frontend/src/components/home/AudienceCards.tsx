'use client';

import Link from 'next/link';
import { useRef } from 'react';
import { motion, useInView } from 'framer-motion';
import { House, CurrencyDollar, ChartLine, ArrowRight } from '@phosphor-icons/react';

const cards = [
  {
    id: 'buy',
    label: 'Buying',
    heading: 'Find Your Perfect Home',
    sub: 'From your first showing to the closing table, Brandon guides you with local expertise and unwavering dedication.',
    href: '/buy',
    icon: House,
    accent: '#eac469',
    featured: true,
  },
  {
    id: 'sell',
    label: 'Selling',
    heading: 'Sell For More, Stress Less',
    sub: 'Award-winning marketing, expert pricing strategy, and results you can count on.',
    href: '/sell',
    icon: CurrencyDollar,
    accent: '#eac469',
    featured: false,
  },
  {
    id: 'invest',
    label: 'Investing',
    heading: 'Analyze Any Deal',
    sub: 'Cash flow projections, cap rate analysis, and market intelligence for serious investors.',
    href: '/invest',
    icon: ChartLine,
    accent: '#eac469',
    featured: false,
  },
] as const;

const containerVariants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.12 } },
};

const cardVariants = {
  hidden: { opacity: 0, y: 32 },
  show: { opacity: 1, y: 0, transition: { type: 'spring' as const, stiffness: 100, damping: 20 } },
};

export default function AudienceCards() {
  const sectionRef = useRef<HTMLElement>(null);
  const inView = useInView(sectionRef, { once: true, margin: '-80px' });

  return (
    <section
      ref={sectionRef}
      className="relative bg-dark-card py-24 md:py-32 overflow-hidden"
    >
      {/* Subtle background texture */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(circle, #eac469 1px, transparent 1px)',
          backgroundSize: '32px 32px',
          opacity: 0.02,
        }}
        aria-hidden="true"
      />

      {/* Gold left border accent */}
      <div className="absolute left-0 top-0 bottom-0 w-px bg-gold/20" aria-hidden="true" />

      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
        {/* Section header — left-aligned */}
        <motion.div
          className="mb-16 max-w-xl"
          initial={{ opacity: 0, y: 24 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ type: 'spring', stiffness: 100, damping: 20 }}
        >
          <span className="text-gold text-xs font-semibold tracking-[0.25em] uppercase block mb-3">
            How Can Brandon Help?
          </span>
          <h2
            className="font-black text-white tracking-tight"
            style={{ fontSize: 'clamp(2rem, 4vw, 3.5rem)' }}
          >
            Your Goals,{' '}
            <span className="text-gold">Our Strategy</span>
          </h2>
        </motion.div>

        {/*
          ASYMMETRIC LAYOUT:
          — Featured (Buying) card: tall, left column, spans full height
          — Sell + Invest: right column, two stacked cards
          Mobile: single column stack
        */}
        <motion.div
          className="grid grid-cols-1 lg:grid-cols-5 gap-4 lg:gap-6 lg:items-stretch"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          {/* Featured card — Buying — takes 3/5 columns */}
          {(() => {
            const card = cards[0];
            const Icon = card.icon;
            return (
              <motion.div
                key={card.id}
                variants={cardVariants}
                className="lg:col-span-3"
              >
                <Link href={card.href} className="group block h-full">
                  <motion.div
                    className="relative h-full min-h-[420px] bg-[#0a0a0a] border border-dark-border overflow-hidden flex flex-col justify-end p-8 md:p-10"
                    whileHover={{ borderColor: 'rgba(234,196,105,0.4)' }}
                    transition={{ duration: 0.25 }}
                  >
                    {/* Background glow on hover */}
                    <div
                      className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"
                      style={{
                        background:
                          'radial-gradient(ellipse at 30% 70%, rgba(234,196,105,0.08) 0%, transparent 60%)',
                      }}
                      aria-hidden="true"
                    />

                    {/* Icon — large, top-left */}
                    <div className="absolute top-8 left-8">
                      <div className="w-16 h-16 border border-gold/30 flex items-center justify-center group-hover:border-gold/60 transition-colors duration-300">
                        <Icon weight="light" className="w-8 h-8 text-gold" />
                      </div>
                    </div>

                    {/* Gold top label */}
                    <div className="absolute top-8 right-8">
                      <span className="text-gold text-xs font-semibold tracking-[0.2em] uppercase">
                        {card.label}
                      </span>
                    </div>

                    {/* Bottom content */}
                    <div className="relative z-10">
                      <h3
                        className="font-black text-white tracking-tight mb-3"
                        style={{ fontSize: 'clamp(1.8rem, 3.5vw, 2.8rem)' }}
                      >
                        {card.heading}
                      </h3>
                      <p className="text-white/60 text-base leading-relaxed mb-6 max-w-sm font-light">
                        {card.sub}
                      </p>
                      <span className="inline-flex items-center gap-2 text-gold font-semibold text-sm tracking-widest uppercase group-hover:gap-3 transition-all duration-200">
                        Get Started
                        <ArrowRight weight="bold" className="w-4 h-4" />
                      </span>
                    </div>

                    {/* Bottom border accent */}
                    <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-gold/60 via-gold/20 to-transparent" aria-hidden="true" />
                  </motion.div>
                </Link>
              </motion.div>
            );
          })()}

          {/* Two stacked cards — Sell + Invest — 2/5 columns */}
          <div className="lg:col-span-2 flex flex-col gap-4 lg:gap-6">
            {cards.slice(1).map((card) => {
              const Icon = card.icon;
              return (
                <motion.div key={card.id} variants={cardVariants} className="flex-1">
                  <Link href={card.href} className="group block h-full">
                    <motion.div
                      className="relative h-full min-h-[196px] bg-[#0a0a0a] border border-dark-border overflow-hidden flex flex-col justify-between p-6 md:p-8"
                      whileHover={{ borderColor: 'rgba(234,196,105,0.4)' }}
                      transition={{ duration: 0.25 }}
                    >
                      {/* Background glow on hover */}
                      <div
                        className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"
                        style={{
                          background:
                            'radial-gradient(ellipse at 80% 20%, rgba(234,196,105,0.07) 0%, transparent 60%)',
                        }}
                        aria-hidden="true"
                      />

                      {/* Top row: label + icon */}
                      <div className="relative z-10 flex items-start justify-between mb-auto">
                        <span className="text-gold text-xs font-semibold tracking-[0.2em] uppercase">
                          {card.label}
                        </span>
                        <div className="w-10 h-10 border border-gold/20 flex items-center justify-center group-hover:border-gold/50 transition-colors duration-300">
                          <Icon weight="light" className="w-5 h-5 text-gold" />
                        </div>
                      </div>

                      {/* Content */}
                      <div className="relative z-10 mt-6">
                        <h3 className="font-black text-white text-xl leading-tight tracking-tight mb-2">
                          {card.heading}
                        </h3>
                        <p className="text-white/50 text-sm leading-relaxed mb-4 font-light">
                          {card.sub}
                        </p>
                        <span className="inline-flex items-center gap-1.5 text-gold font-semibold text-xs tracking-widest uppercase group-hover:gap-2.5 transition-all duration-200">
                          Learn More
                          <ArrowRight weight="bold" className="w-3.5 h-3.5" />
                        </span>
                      </div>

                      {/* Right border accent */}
                      <div className="absolute right-0 top-0 bottom-0 w-px bg-gradient-to-b from-gold/40 via-gold/10 to-transparent" aria-hidden="true" />
                    </motion.div>
                  </Link>
                </motion.div>
              );
            })}
          </div>
        </motion.div>
      </div>
    </section>
  );
}
