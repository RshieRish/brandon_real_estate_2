'use client';

import { useState } from 'react';
import Image from 'next/image';
import { motion, AnimatePresence } from 'framer-motion';
import { CaretDown, CaretUp, CheckCircle } from '@phosphor-icons/react/dist/ssr';

const phases = [
  {
    id: 'phase-1',
    title: 'Phase 1',
    subtitle: 'The Swiping Phase',
    description: 'Before you start scrolling Zillow, get your financial foundation in place. This is where serious buyers separate themselves from window shoppers.',
    bullets: [
      'Pre-Approval for Budget',
      'Meet with Your REALTOR®',
      'Utilize Your Pre-Approval',
    ],
    image: '/frames/phase-1-swiping.jpg',
  },
  {
    id: 'phase-2',
    title: 'Phase 2',
    subtitle: 'The Engagement Phase',
    description: 'It’s time to hit the pavement. We schedule private showings, analyze market comps, and aggressively negotiate on your behalf to secure the home of your dreams.',
    bullets: [
      'Private Showings & Tours',
      'Market Analysis & Strategy',
      'Expert Offer Negotiation',
    ],
    image: '/frames/phase-2-touring.jpg',
  },
  {
    id: 'phase-3',
    title: 'Phase 3',
    subtitle: 'The Happily Ever After Phase',
    description: 'From accepted offer to the closing table. We manage the inspections, coordinate with lenders, and ensure a seamless, stress-free transfer of keys.',
    bullets: [
      'Home Inspection & Review',
      'Mortgage Commitment',
      'Final Walkthrough & Keys',
    ],
    image: '/frames/phase-3-keys.jpg',
  },
];

export default function TheProcess() {
  const [activePhase, setActivePhase] = useState(phases[0].id);

  return (
    <section className="bg-[#0a0a0a] text-white py-24 md:py-32 relative overflow-hidden">
      <div className="max-w-7xl mx-auto px-6 md:px-12">
        {/* Header */}
        <div className="mb-16 md:mb-24 max-w-2xl">
          <span className="text-gold text-xs font-semibold tracking-[0.25em] uppercase block mb-3">
            The Process
          </span>
          <h2 
            className="font-black text-white tracking-tight mb-6"
            style={{ fontSize: 'clamp(2rem, 4vw, 3.5rem)' }}
          >
            Your Home Buying Journey
          </h2>
          <p className="text-white/60 text-base md:text-lg leading-relaxed font-light">
            Three phases. Every step mapped. No surprises — just a clear path from pre-approval to keys in hand.
          </p>
        </div>

        {/* 2-Column Split Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-24 items-start">
          
          {/* Left: Accordion */}
          <div className="flex flex-col border-t border-white/10">
            {phases.map((phase) => {
              const isActive = activePhase === phase.id;
              
              return (
                <div 
                  key={phase.id} 
                  className="border-b border-white/10 overflow-hidden"
                >
                  <button
                    onClick={() => setActivePhase(phase.id)}
                    className="w-full text-left py-8 flex items-center justify-between group focus:outline-none focus-visible:bg-white/5 transition-colors"
                  >
                    <div>
                      <p className="text-gold text-sm font-medium tracking-widest uppercase mb-2">
                        {phase.title}
                      </p>
                      <h3 className={`text-2xl md:text-3xl font-bold tracking-tight transition-colors duration-300 ${isActive ? 'text-white' : 'text-white/40 group-hover:text-white'}`}>
                        {phase.subtitle}
                      </h3>
                    </div>
                    
                    <div className={`w-10 h-10 rounded-full border flex items-center justify-center transition-all duration-300 shrink-0 ${isActive ? 'border-gold bg-gold text-[#0a0a0a]' : 'border-white/20 text-white/40 group-hover:border-white/60 group-hover:text-white'}`}>
                      {isActive ? <CaretUp weight="bold" /> : <CaretDown weight="bold" />}
                    </div>
                  </button>

                  <AnimatePresence initial={false}>
                    {isActive && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.4, ease: [0.04, 0.62, 0.23, 0.98] }}
                      >
                        <div className="pb-8 pr-12">
                          <p className="text-white/60 text-base leading-relaxed font-light mb-6">
                            {phase.description}
                          </p>
                          
                          <ul className="space-y-3">
                            {phase.bullets.map((bullet, i) => (
                              <li key={i} className="flex items-start gap-3 text-sm md:text-base font-medium text-white/80">
                                <CheckCircle weight="fill" className="w-5 h-5 text-gold shrink-0 mt-0.5" />
                                {bullet}
                              </li>
                            ))}
                          </ul>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              );
            })}
          </div>

          {/* Right: Dynamic Image */}
          <div className="relative aspect-[3/4] lg:aspect-auto lg:h-[700px] rounded-2xl overflow-hidden bg-white/5 shadow-2xl">
            <AnimatePresence mode="wait">
              <motion.div
                key={activePhase}
                initial={{ opacity: 0, scale: 1.05 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ duration: 0.5, ease: "easeInOut" }}
                className="absolute inset-0"
              >
                <Image
                  src={phases.find(p => p.id === activePhase)?.image || phases[0].image}
                  alt="Process Phase"
                  fill
                  className="object-cover"
                  sizes="(max-width: 1024px) 100vw, 50vw"
                  priority
                  unoptimized={true}
                />
              </motion.div>
            </AnimatePresence>
          </div>

        </div>
      </div>
    </section>
  );
}
