'use client';

import { useRef } from 'react';
import { motion, useInView } from 'framer-motion';
import { Heart, ArrowRight, ArrowUpRight } from '@phosphor-icons/react';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';

const containerVariants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.12 } },
};

const fadeUp = {
  hidden: { opacity: 0, y: 28 },
  show: { opacity: 1, y: 0, transition: { type: 'spring' as const, stiffness: 100, damping: 20 } },
};

export default function GivingBack() {
  const sectionRef = useRef<HTMLElement>(null);
  const inView = useInView(sectionRef, { once: true, margin: '-80px' });

  return (
    <section
      ref={sectionRef}
      className="relative bg-[#0a0a0a] min-h-[100dvh] flex flex-col justify-center overflow-hidden py-28 md:py-36"
    >
      {/* Halftone dot texture */}
      <HalftoneOverlay opacity={0.04} />

      {/* Cinematic gold gradient bloom — top-right */}
      <div
        className="absolute top-0 right-0 w-[600px] h-[600px] pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse at top right, rgba(234,196,105,0.12) 0%, transparent 65%)',
        }}
        aria-hidden="true"
      />

      {/* Bottom-left bloom */}
      <div
        className="absolute bottom-0 left-0 w-[400px] h-[400px] pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse at bottom left, rgba(192,130,53,0.08) 0%, transparent 60%)',
        }}
        aria-hidden="true"
      />

      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12 w-full">
        {/* Asymmetric two-column layout: large text left, story right */}
        <motion.div
          className="grid grid-cols-1 lg:grid-cols-2 gap-16 lg:gap-24 items-center"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          {/* Left: Impact statement */}
          <div>
            {/* Eyebrow */}
            <motion.div variants={fadeUp} className="flex items-center gap-3 mb-6">
              <Heart weight="fill" className="w-5 h-5 text-gold" />
              <span className="text-gold text-xs font-semibold tracking-[0.25em] uppercase">
                Giving Back
              </span>
            </motion.div>

            {/* Big donation headline */}
            <motion.div variants={fadeUp}>
              <p className="text-white/40 text-sm font-medium tracking-wider uppercase mb-2">
                Donated to MS Warriors
              </p>
              <div
                className="font-black text-gold leading-none tracking-tight mb-6"
                style={{
                  fontSize: 'clamp(3.5rem, 9vw, 7rem)',
                  textShadow: '0 0 60px rgba(234,196,105,0.25)',
                }}
              >
                $300,000+
              </div>
            </motion.div>

            <motion.p
              variants={fadeUp}
              className="text-white/60 text-base md:text-lg leading-relaxed font-light mb-10 max-w-lg"
            >
              Real estate is more than transactions — it&apos;s about community. Brandon donates a
              portion of every closing to&nbsp;
              <span className="text-gold font-medium">MS is BS New England</span>, funding research
              and support for those living with Multiple Sclerosis.
            </motion.p>

            {/* CTAs */}
            <motion.div variants={fadeUp} className="flex flex-wrap gap-4">
              <a
                href="https://www.MSisBSNewEngland.com"
                target="_blank"
                rel="noopener noreferrer"
              >
                <motion.span
                  className="inline-flex items-center gap-2.5 px-6 py-3.5 border border-gold text-gold font-semibold text-sm tracking-widest uppercase hover:bg-gold hover:text-[#0a0a0a] transition-colors duration-200"
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: 0.97 }}
                  transition={{ type: 'spring', stiffness: 100, damping: 20 }}
                >
                  <Heart weight="bold" className="w-4 h-4" />
                  Learn About MS is BS
                  <ArrowUpRight weight="bold" className="w-3.5 h-3.5 opacity-70" />
                </motion.span>
              </a>

              <a href="/about">
                <motion.span
                  className="inline-flex items-center gap-2.5 px-6 py-3.5 bg-gold text-[#0a0a0a] font-semibold text-sm tracking-widest uppercase hover:bg-gold-hover transition-colors duration-200"
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: 0.97 }}
                  transition={{ type: 'spring', stiffness: 100, damping: 20 }}
                >
                  Brandon&apos;s Story
                  <ArrowRight weight="bold" className="w-4 h-4" />
                </motion.span>
              </a>
            </motion.div>
          </div>

          {/* Right: Story panel — glassmorphism */}
          <motion.div variants={fadeUp}>
            <div className="glass border border-dark-border p-8 md:p-10 relative overflow-hidden">
              {/* Inner refraction border */}
              <div
                className="absolute inset-px pointer-events-none"
                style={{
                  border: '1px solid rgba(255,255,255,0.05)',
                  borderRadius: 'inherit',
                }}
                aria-hidden="true"
              />

              {/* Gold top accent line */}
              <div
                className="absolute top-0 left-8 right-8 h-px bg-gradient-to-r from-transparent via-gold/60 to-transparent"
                aria-hidden="true"
              />

              <div className="relative z-10">
                <h3 className="font-black text-white text-2xl md:text-3xl tracking-tight mb-4">
                  MS is BS New England
                </h3>
                <p className="text-white/60 text-sm md:text-base leading-relaxed mb-6 font-light">
                  Multiple Sclerosis has touched Brandon&apos;s life personally. That&apos;s why he
                  co-founded MS is BS New England — a grassroots movement raising awareness and
                  funds for MS research, events, and warrior support.
                </p>
                <p className="text-white/60 text-sm md:text-base leading-relaxed font-light">
                  Every home Brandon sells contributes to the cause. When you work with Sweeney
                  &amp; Co., your real estate transaction becomes part of something bigger.
                </p>

                {/* Stat row */}
                <div className="grid grid-cols-2 gap-4 mt-8 pt-8 border-t border-dark-border">
                  <div>
                    <div className="text-gold font-black text-2xl">100%</div>
                    <div className="text-white/40 text-xs tracking-widest uppercase font-medium mt-1">
                      Grassroots
                    </div>
                  </div>
                  <div>
                    <div className="text-gold font-black text-2xl">MA &amp; NH</div>
                    <div className="text-white/40 text-xs tracking-widest uppercase font-medium mt-1">
                      Service Area
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}
