'use client';

import { useRef, useState, useEffect } from 'react';
import Image from 'next/image';
import { motion, useInView, AnimatePresence } from 'framer-motion';
import {
  Phone,
  EnvelopeSimple,
  MapPin,
  Star,
  Heart,
  ArrowUpRight,
  Trophy,
  Certificate,
  Users,
  CalendarBlank,
} from '@phosphor-icons/react';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';

// ─── Animation variants ────────────────────────────────────────────────────────

const containerVariants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.1, delayChildren: 0.2 },
  },
};

const fadeUp = {
  hidden: { opacity: 0, y: 32 },
  show: {
    opacity: 1,
    y: 0,
    transition: { type: 'spring' as const, stiffness: 100, damping: 20 },
  },
};

const fadeIn = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { type: 'spring' as const, stiffness: 100, damping: 20 },
  },
};

// ─── Section: Hero ─────────────────────────────────────────────────────────────

function HeroSection() {
  return (
    <AnimatePresence>
      <section className="relative min-h-[100dvh] flex flex-col justify-center overflow-hidden bg-[#0a0a0a]">
        {/* Gold bloom — top left */}
        <div
          className="absolute top-0 left-0 w-[700px] h-[700px] pointer-events-none"
          style={{
            background:
              'radial-gradient(ellipse at top left, rgba(234,196,105,0.09) 0%, transparent 65%)',
          }}
          aria-hidden="true"
        />

        {/* Halftone texture */}
        <HalftoneOverlay opacity={0.035} />

        <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12 w-full pt-24 pb-20 md:pt-32 md:pb-28">
          {/* Split layout: text left, image right */}
          <motion.div
            className="grid grid-cols-1 lg:grid-cols-2 gap-16 lg:gap-24 items-center"
            variants={containerVariants}
            initial="hidden"
            animate="show"
          >
            {/* Left — text */}
            <div>
              {/* Eyebrow */}
              <motion.div variants={fadeUp} className="mb-6">
                <span className="inline-block glass border border-gold/30 text-gold text-xs font-semibold tracking-[0.25em] uppercase px-4 py-2">
                  Meet Brandon
                </span>
              </motion.div>

              {/* H1 */}
              <motion.h1
                variants={fadeUp}
                className="font-black text-white leading-[0.92] tracking-tight mb-6"
                style={{ fontSize: 'clamp(2.6rem, 6.5vw, 5.5rem)' }}
              >
                Not Your{' '}
                <span
                  className="text-gold"
                  style={{ textShadow: '0 0 40px rgba(234,196,105,0.35)' }}
                >
                  AVERAGE
                </span>
                <br />
                REALTOR<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup>
              </motion.h1>

              {/* Subheading */}
              <motion.p
                variants={fadeUp}
                className="text-gold/70 text-sm font-semibold tracking-[0.18em] uppercase mb-6"
              >
                Licensed since 2017&nbsp;&nbsp;|&nbsp;&nbsp;MA &amp; NH&nbsp;&nbsp;|&nbsp;&nbsp;Keller Williams Realty Success
              </motion.p>

              {/* Intro paragraph */}
              <motion.p
                variants={fadeUp}
                className="text-white/65 text-base md:text-lg leading-relaxed font-light max-w-xl"
              >
                Brandon Sweeney is the CEO of Sold With Sweeney &amp; Co. — a top-producing team
                at Keller Williams Realty Success. Named{' '}
                <span className="text-gold font-medium">2025 Northeast Association of REALTORS<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup> Of The Year</span>{' '}
                and 2025 Northeast Association of REALTORS<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup> President, Brandon has built his career on market expertise, honest
                communication, and an unwavering commitment to the Merrimack Valley community where
                he grew up.
              </motion.p>

              {/* Bio detail chips */}
              <motion.div variants={fadeUp} className="flex flex-wrap gap-3 mt-8">
                {[
                  { id: 'licensed-since-2017', icon: CalendarBlank, label: 'Licensed salesperson since 2017' },
                  {
                    id: 'realtor-of-the-year',
                    icon: Trophy,
                    label: <span>REALTOR<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup> Of The Year 2025</span>,
                  },
                  { id: 'ma-nh-licensed', icon: Star, label: 'MA & NH Licensed' },
                ].map(({ id, icon: Icon, label }) => (
                  <span
                    key={id}
                    className="inline-flex items-center gap-2 glass border border-dark-border px-4 py-2 text-xs text-white/60 font-medium tracking-wide"
                  >
                    <Icon weight="bold" className="w-3.5 h-3.5 text-gold" />
                    {label}
                  </span>
                ))}
              </motion.div>
            </div>

            {/* Right — hero image */}
            <motion.div variants={fadeIn} className="relative">
              {/* Gold corner accent */}
              <div
                className="absolute -top-4 -right-4 w-24 h-24 pointer-events-none z-10"
                style={{
                  background:
                    'linear-gradient(135deg, rgba(234,196,105,0.3) 0%, transparent 60%)',
                }}
                aria-hidden="true"
              />

              <div className="relative overflow-hidden" style={{ aspectRatio: '4/5' }}>
                {/* Gold top line accent */}
                <div
                  className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-gold/80 via-gold/40 to-transparent z-10"
                  aria-hidden="true"
                />

                <Image
                  src="/headshots/Brandon Sweeney Headshot.jpg"
                  alt="Brandon Sweeney, REALTOR\u00ae — Sold With Sweeney &amp; Co."
                  fill
                  className="object-cover object-top"
                  priority
                  sizes="(max-width: 1024px) 100vw, 50vw"
                />

                {/* Dark gradient overlay at bottom */}
                <div
                  className="absolute bottom-0 left-0 right-0 h-40 pointer-events-none"
                  style={{
                    background:
                      'linear-gradient(to top, rgba(10,10,10,0.85) 0%, transparent 100%)',
                  }}
                  aria-hidden="true"
                />

                {/* Floating glass name badge */}
                <div className="absolute bottom-6 left-6 right-6 glass border border-gold/25 px-5 py-4 z-10">
                  <div className="text-white font-bold text-base tracking-tight">Brandon Sweeney</div>
                  <div className="text-gold text-xs font-semibold tracking-widest uppercase mt-0.5">
                    CEO, Sold With Sweeney &amp; Co. <span className="text-white/80">|</span>&nbsp; REALTOR<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup>
                  </div>
                </div>
              </div>
            </motion.div>
          </motion.div>
        </div>
      </section>
    </AnimatePresence>
  );
}

// ─── Section: Stats Strip ──────────────────────────────────────────────────────

const stats = [
  { id: 'licensed', value: '2017', label: 'Licensed Since', detail: 'Started building his client base at 22.' },
    id: 'president', 
    value: '2025', 
    label: <>Northeast Association of REALTORS<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup> President</>, 
    detail: 'Leading advocacy and standards for the association.' 
  },
  { id: 'ms', value: '$300K+', label: 'Raised For MS Is BS', detail: 'Grassroots impact fueled through closings and events.' },
];

function StatsStrip() {
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { once: true, margin: '-60px' });

  return (
    <section
      ref={ref}
      className="relative bg-dark-card border-t border-b border-dark-border overflow-hidden"
    >
      {/* Gold shimmer bar */}
      <div
        className="absolute top-0 left-0 right-0 h-px"
        style={{
          background: 'linear-gradient(90deg, transparent, rgba(234,196,105,0.5) 50%, transparent)',
        }}
        aria-hidden="true"
      />

      <div className="max-w-7xl mx-auto px-6 md:px-12 py-12">
        <motion.div
          className="grid grid-cols-1 lg:grid-cols-3 gap-px bg-dark-border"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          {stats.map(({ id, value, label, detail }) => (
            <motion.div
              key={id}
              variants={fadeUp}
              className="glass flex flex-col items-center justify-center text-center px-6 py-10 gap-3"
            >
              {Array.isArray(value) ? (
                <span
                  className="font-black text-gold leading-[0.9]"
                  style={{
                    fontSize: 'clamp(1.3rem, 3vw, 2.2rem)',
                    textShadow: '0 0 30px rgba(234,196,105,0.25)',
                  }}
                >
                  {value.map((line, idx) => (
                    <span key={idx} className="block">
                      {line}
                    </span>
                  ))}
                </span>
              ) : (
                <span
                  className="font-black text-gold leading-none"
                  style={{
                    fontSize: 'clamp(1.6rem, 3.5vw, 2.8rem)',
                    textShadow: '0 0 30px rgba(234,196,105,0.25)',
                  }}
                >
                  {value}
                </span>
              )}
              {label && (
                <span className="text-white/50 text-xs font-semibold tracking-[0.2em] uppercase">
                  {label}
                </span>
              )}
              <span className="max-w-[14rem] text-white/38 text-[11px] leading-relaxed">
                {detail}
              </span>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}

// ─── Section: Bio Deep Dive ────────────────────────────────────────────────────

type BioTab = 'foundation' | 'expert' | 'leader';

const BIO_IMAGES: Record<BioTab, string> = {
  foundation: '/headshots/Brandon Sweeney Headshot Zoomed In.png',
  expert: '/headshots/expert.jpg',
  leader: '/headshots/leader.jpg',
};

function BioSection() {
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { once: true, margin: '-80px' });
  const [activeTab, setActiveTab] = useState<BioTab>('foundation');

  return (
    <section
      ref={ref}
      className="relative bg-[#0a0a0a] py-28 md:py-36 overflow-hidden"
    >
      <HalftoneOverlay opacity={0.03} />

      {/* Gold bloom — bottom right */}
      <div
        className="absolute bottom-0 right-0 w-[500px] h-[500px] pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse at bottom right, rgba(234,196,105,0.08) 0%, transparent 65%)',
        }}
        aria-hidden="true"
      />

      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12 w-full">
        <motion.div
          className="grid grid-cols-1 lg:grid-cols-[1fr_1.1fr] gap-16 lg:gap-28 items-start"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          {/* Left: section header */}
          <div className="lg:sticky lg:top-28">
            <motion.div variants={fadeUp} className="flex items-center gap-3 mb-5">
              <Star weight="fill" className="w-4 h-4 text-gold" />
              <span className="text-gold text-xs font-semibold tracking-[0.25em] uppercase">
                Brandon&apos;s Story
              </span>
            </motion.div>

            <motion.h2
              variants={fadeUp}
              className="font-black text-white leading-[0.95] tracking-tight mb-8"
              style={{ fontSize: 'clamp(2rem, 4.5vw, 3.8rem)' }}
            >
              Built on{' '}
              <span className="text-gold">Trust,</span>
              <br />
              Driven by{' '}
              <span className="text-gold">Community</span>
            </motion.h2>

            {/* Zoomed headshot */}
            <motion.div variants={fadeIn} className="relative overflow-hidden mt-6" style={{ aspectRatio: '3/4', maxWidth: '380px' }}>
              <div
                className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-gold/70 via-gold/30 to-transparent z-10"
                aria-hidden="true"
              />
              <AnimatePresence mode="wait">
                <motion.div
                  key={activeTab}
                  initial={{ opacity: 0, scale: 1.05 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ duration: 0.4 }}
                  className="absolute inset-0"
                >
                  <Image
                    src={BIO_IMAGES[activeTab]}
                    alt="Brandon Sweeney close-up portrait"
                    fill
                    className="object-cover object-center"
                    sizes="(max-width: 1024px) 80vw, 400px"
                  />
                </motion.div>
              </AnimatePresence>
            </motion.div>
          </div>

          {/* Right: bio content */}
          <div className="flex flex-col gap-8">
            {/* Bio block 1 */}
            <motion.div
              variants={fadeUp}
              className={`glass border p-8 relative overflow-hidden transition-colors duration-300 ${
                activeTab === 'foundation' ? 'border-gold/35 bg-white/5' : 'border-dark-border'
              }`}
              onMouseEnter={() => setActiveTab('foundation')}
            >
              {/* Inner refraction border */}
              <div
                className="absolute inset-px pointer-events-none"
                style={{ border: '1px solid rgba(255,255,255,0.04)' }}
                aria-hidden="true"
              />
              <div
                className="absolute top-0 left-8 right-8 h-px bg-gradient-to-r from-transparent via-gold/50 to-transparent"
                aria-hidden="true"
              />
              <div className="relative z-10">
                <h3 className="text-white font-bold text-lg tracking-tight mb-4">
                  The Foundation
                </h3>
                <p className="text-white/60 text-sm md:text-base leading-relaxed font-light">
                  Brandon grew up in Dracut, MA — deeply embedded in the Merrimack Valley community.
                  He started his career in sales at 18 and earned his real estate license at 22 in 2017.
                  Licensed as a salesperson in MA and NH, he has built a reputation rooted in integrity and
                  results.
                </p>
              </div>
            </motion.div>

            {/* Bio block 2 */}
            <motion.div
              variants={fadeUp}
              className={`glass border p-8 relative overflow-hidden transition-colors duration-300 ${
                activeTab === 'expert' ? 'border-gold/35 bg-white/5' : 'border-dark-border'
              }`}
              onMouseEnter={() => setActiveTab('expert')}
            >
              <div
                className="absolute inset-px pointer-events-none"
                style={{ border: '1px solid rgba(255,255,255,0.04)' }}
                aria-hidden="true"
              />
              <div
                className="absolute top-0 left-8 right-8 h-px bg-gradient-to-r from-transparent via-gold/50 to-transparent"
                aria-hidden="true"
              />
              <div className="relative z-10">
                <h3 className="text-white font-bold text-lg tracking-tight mb-4">
                  The Expert
                </h3>
                <p className="text-white/60 text-sm md:text-base leading-relaxed font-light">
                  As CEO of Sold With Sweeney &amp; Co. at Keller Williams Realty Success, Brandon
                  specializes in residential and investment real estate across the
                  Merrimack Valley. His clients trust him for deep market knowledge, direct honest
                  communication, and a commitment to going above and beyond — every single time.
                </p>
              </div>
            </motion.div>

            {/* Bio block 3 */}
            <motion.div
              variants={fadeUp}
              className={`glass border p-8 relative overflow-hidden transition-colors duration-300 ${
                activeTab === 'leader' ? 'border-gold/35 bg-white/5' : 'border-dark-border'
              }`}
              onMouseEnter={() => setActiveTab('leader')}
            >
              <div
                className="absolute inset-px pointer-events-none"
                style={{ border: '1px solid rgba(255,255,255,0.04)' }}
                aria-hidden="true"
              />
              <div
                className="absolute top-0 left-8 right-8 h-px bg-gradient-to-r from-transparent via-gold/50 to-transparent"
                aria-hidden="true"
              />
              <div className="relative z-10">
                <h3 className="text-white font-bold text-lg tracking-tight mb-4">
                  The Leader
                </h3>
                <p className="text-white/60 text-sm md:text-base leading-relaxed font-light">
                  In 2025, Brandon was named{' '}
                  <span className="text-gold font-medium">Northeast Association of REALTORS<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup> Of The Year</span> —
                  the highest honor awarded by the Northeast Association of REALTORS<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup>. He
                  also serves as the 2025 Northeast Association of REALTORS<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup> President, guiding the direction of real estate
                  standards and advocacy across Massachusetts.
                </p>
              </div>
            </motion.div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

// ─── Section: Designations & Memberships ──────────────────────────────────────

const designations = [
  {
    src: '/logos/Designations-Associations/NEAR.png',
    alt: 'Northeast Association of REALTORS®',
    label: 'Northeast Association of REALTORS®',
    imageClassName: 'brightness-125 saturate-110',
  },
  {
    src: '/logos/Designations-Associations/MAR-Logo-Color-VERT-300dpi.png',
    alt: 'MAR',
    label: 'Massachusetts Association of REALTORS\u00ae',
    imageClassName: 'brightness-0 invert opacity-95',
  },
  {
    src: '/logos/Designations-Associations/National_Association_of_REALTORS_Logo.svg.png',
    alt: 'NAR',
    label: 'National Association of REALTORS\u00ae',
    imageClassName: 'brightness-0 invert opacity-95',
  },
  {
    src: '/logos/Designations-Associations/Green.jpg',
    alt: 'GREEN',
    label: 'GREEN Designation',
    imageClassName: 'brightness-125 saturate-110',
  },
  {
    src: '/logos/Designations-Associations/NAR-1424_C2EX_New Lockup_isolated_10.21.20[1].png',
    alt: 'C2EX',
    label: 'Commitment to Excellence (C2EX)',
    imageClassName: 'brightness-125 saturate-110',
  },
];

const awards = [
  {
    id: 'near-realtor-of-the-year-2025',
    icon: Trophy,
    title: <span>2025 Northeast Association of REALTORS<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup> Of The Year</span>,
    sub: <span>The Northeast Association of REALTORS<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup> highest annual honor.</span>,
  },
  {
    id: 'near-president-2025',
    icon: Star,
    title: '2025 NEAR President',
    sub: 'Helping guide standards, leadership, and advocacy for the association.',
  },
  {
    id: 'mar-good-neighbor-award',
    icon: Certificate,
    title: 'MAR Good Neighbor Award',
    sub: 'Recognized for community-first leadership and charitable impact.',
  },
  {
    id: 'heavy-hitter-award',
    icon: Trophy,
    title: 'Heavy Hitter Award',
    sub: 'Recognized for selling over $10 million in real estate in a single year.',
  },
  {
    id: 'near-good-neighbor-recognition',
    icon: Heart,
    title: 'Northeast Association of REALTORS® Good Neighbor Recognition',
    sub: 'Honoring real local impact through service and giving back.',
  },
  {
    id: 'distinguished-young-professional',
    icon: Users,
    title: 'Distinguished Young Professional',
    sub: 'Celebrating standout leadership early in a high-growth career.',
  },
];

function DesignationsSection() {
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { once: true, margin: '-80px' });

  return (
    <section
      ref={ref}
      className="relative bg-dark-card py-28 md:py-36 overflow-hidden"
    >
      <HalftoneOverlay opacity={0.025} />

      {/* Subtle top gold line */}
      <div
        className="absolute top-0 left-0 right-0 h-px pointer-events-none"
        style={{
          background: 'linear-gradient(90deg, transparent, rgba(234,196,105,0.35) 50%, transparent)',
        }}
        aria-hidden="true"
      />

      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12 w-full">
        {/* Section header */}
        <motion.div
          className="mb-16"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          <motion.div variants={fadeUp} className="flex items-center gap-3 mb-5">
            <Certificate weight="fill" className="w-4 h-4 text-gold" />
            <span className="text-gold text-xs font-semibold tracking-[0.25em] uppercase">
              Credentials
            </span>
          </motion.div>
          <motion.h2
            variants={fadeUp}
            className="font-black text-white leading-[0.95] tracking-tight"
            style={{ fontSize: 'clamp(1.8rem, 4vw, 3.2rem)' }}
          >
            Designations &amp;{' '}
            <span className="text-gold">Memberships</span>
          </motion.h2>
        </motion.div>

        {/* Logos grid */}
        <motion.div
          className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mb-16"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          {designations.map(({ src, alt, label, imageClassName }) => (
            <motion.div
              key={alt}
              variants={fadeUp}
              className="glass border border-dark-border flex flex-col items-center justify-center gap-4 p-6 relative overflow-hidden group"
              whileHover={{ borderColor: 'rgba(234,196,105,0.35)' }}
              transition={{ type: 'spring', stiffness: 100, damping: 20 }}
            >
              <div
                className="absolute top-0 left-4 right-4 h-px bg-gradient-to-r from-transparent via-gold/40 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300"
                aria-hidden="true"
              />
              <div className="relative h-16 w-full">
                <Image
                  src={src}
                  alt={alt}
                  fill
                  className={`object-contain transition-all duration-200 ${imageClassName}`}
                  sizes="160px"
                />
              </div>
              <span className="text-white/50 text-[10px] font-semibold tracking-wider uppercase text-center leading-tight">
                {label}
              </span>
            </motion.div>
          ))}
        </motion.div>

        {/* Awards row */}
        <motion.div
          className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          {awards.map(({ id, icon: Icon, title, sub }) => (
            <motion.div
              key={id}
              variants={fadeUp}
              className="glass border border-gold/20 p-6 md:p-8 flex items-start gap-5 relative overflow-hidden"
            >
              <div
                className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-gold/60 via-gold/30 to-transparent"
                aria-hidden="true"
              />
              <div className="shrink-0 w-12 h-12 flex items-center justify-center bg-gold/10 border border-gold/25">
                <Icon weight="fill" className="w-6 h-6 text-gold" />
              </div>
              <div>
                <div className="text-white font-bold text-base tracking-tight mb-1">{title}</div>
                <div className="text-white/45 text-sm font-light leading-relaxed">{sub}</div>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}

// ─── Section: MS is BS New England ────────────────────────────────────────────

function MSisBSSection() {
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { once: true, margin: '-80px' });

  return (
    <section
      ref={ref}
      className="relative bg-[#0a0a0a] py-28 md:py-36 overflow-hidden"
    >
      {/* Gold bloom — center */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse at 50% 50%, rgba(234,196,105,0.07) 0%, transparent 65%)',
        }}
        aria-hidden="true"
      />
      <HalftoneOverlay opacity={0.04} />

      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12 w-full">
        <motion.div
          className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-16 lg:gap-24 items-center"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          {/* Left: content */}
          <div>
            <motion.div variants={fadeUp} className="flex items-center gap-3 mb-5">
              <Heart weight="fill" className="w-4 h-4 text-gold" />
              <span className="text-gold text-xs font-semibold tracking-[0.25em] uppercase">
                Community Impact
              </span>
            </motion.div>

            <motion.h2
              variants={fadeUp}
              className="font-black text-white leading-[0.95] tracking-tight mb-6"
              style={{ fontSize: 'clamp(2rem, 4.5vw, 3.8rem)' }}
            >
              MS is BS{' '}
              <span className="text-gold">New England</span>
            </motion.h2>

            {/* Donation stat */}
            <motion.div variants={fadeUp} className="mb-8">
              <p className="text-white/35 text-xs font-semibold tracking-[0.2em] uppercase mb-2">
                Total Donated
              </p>
              <div
                className="font-black text-gold leading-none"
                style={{
                  fontSize: 'clamp(2.8rem, 7vw, 5.5rem)',
                  textShadow: '0 0 50px rgba(234,196,105,0.25)',
                }}
              >
                $300,000+
              </div>
            </motion.div>

            <motion.p
              variants={fadeUp}
              className="text-white/60 text-base md:text-lg leading-relaxed font-light mb-6"
            >
              What started as a college assignment in 2015 became one of the most impactful
              grassroots MS organizations in New England. Brandon&apos;s father John, uncle Gary,
              and late grandmother Rose all have — or had — Multiple Sclerosis. This cause is
              deeply personal.
            </motion.p>

            <motion.p
              variants={fadeUp}
              className="text-white/60 text-base leading-relaxed font-light mb-10"
            >
              When you close with Brandon, a portion of the sale is donated to a charity. Every transaction becomes part of something bigger.
            </motion.p>

            <motion.div variants={fadeUp}>
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
            </motion.div>
          </div>

          {/* Right: glassmorphism story panel */}
          <motion.div variants={fadeUp}>
            <div className="glass border border-dark-border p-8 md:p-10 relative overflow-hidden">
              {/* Inner refraction border */}
              <div
                className="absolute inset-px pointer-events-none"
                style={{ border: '1px solid rgba(255,255,255,0.05)' }}
                aria-hidden="true"
              />
              {/* Gold top accent */}
              <div
                className="absolute top-0 left-8 right-8 h-px bg-gradient-to-r from-transparent via-gold/60 to-transparent"
                aria-hidden="true"
              />

              <div className="relative z-10">
                <h3 className="font-black text-white text-xl md:text-2xl tracking-tight mb-5">
                  The Story Behind The Mission
                </h3>

                <div className="flex flex-col gap-5">
                  <div className="flex items-start gap-4 pb-5 border-b border-dark-border">
                    <div className="shrink-0 w-10 h-10 bg-gold/10 border border-gold/25 flex items-center justify-center mt-0.5">
                      <CalendarBlank weight="bold" className="w-5 h-5 text-gold" />
                    </div>
                    <div>
                      <div className="text-white font-semibold text-sm mb-1">Founded 2015</div>
                      <div className="text-white/45 text-sm leading-relaxed font-light">
                        Started as a college assignment. Turned into a movement.
                      </div>
                    </div>
                  </div>

                  <div className="flex items-start gap-4 pb-5 border-b border-dark-border">
                    <div className="shrink-0 w-10 h-10 bg-gold/10 border border-gold/25 flex items-center justify-center mt-0.5">
                      <Heart weight="fill" className="w-5 h-5 text-gold" />
                    </div>
                    <div>
                      <div className="text-white font-semibold text-sm mb-1">Deeply Personal</div>
                      <div className="text-white/45 text-sm leading-relaxed font-light">
                        Brandon&apos;s father John, uncle Gary, and late grandmother Rose have all
                        been affected by MS.
                      </div>
                    </div>
                  </div>

                  <div className="flex items-start gap-4">
                    <div className="shrink-0 w-10 h-10 bg-gold/10 border border-gold/25 flex items-center justify-center mt-0.5">
                      <Trophy weight="fill" className="w-5 h-5 text-gold" />
                    </div>
                    <div>
                      <div className="text-white font-semibold text-sm mb-1">$300,000+ Raised</div>
                      <div className="text-white/45 text-sm leading-relaxed font-light">
                        100% grassroots. Every closing contributes to MS advocacy and warrior
                        support across New England.
                      </div>
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

// ─── Section: The Team ─────────────────────────────────────────────────────────

const TEAM_IMAGES = [
  '/headshots/brandon-and-paige-maine-gala.jpeg',
  '/headshots/sws-team-casual.png',
  '/headshots/sws-team-formal.png',
];

function TeamSection() {
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { once: true, margin: '-80px' });
  const [currentImageIndex, setCurrentImageIndex] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentImageIndex((prev) => (prev + 1) % TEAM_IMAGES.length);
    }, 4500);
    return () => clearInterval(interval);
  }, []);

  return (
    <section
      ref={ref}
      className="relative bg-dark-card py-28 md:py-36 overflow-hidden"
    >
      <HalftoneOverlay opacity={0.025} />

      <div
        className="absolute top-0 left-0 right-0 h-px pointer-events-none"
        style={{
          background: 'linear-gradient(90deg, transparent, rgba(234,196,105,0.35) 50%, transparent)',
        }}
        aria-hidden="true"
      />

      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12 w-full">
        <motion.div
          className="grid grid-cols-1 lg:grid-cols-2 gap-16 lg:gap-24 items-center"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          {/* Left: team image */}
          <motion.div
            variants={fadeIn}
            className="relative overflow-hidden rounded-xl border border-white/10 shadow-2xl"
            style={{ aspectRatio: '4/5' }}
          >
            <AnimatePresence mode="wait">
              <motion.div
                key={currentImageIndex}
                initial={{ opacity: 0, scale: 1.05 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.8, ease: "easeInOut" }}
                className="absolute inset-0"
              >
                <Image
                  src={TEAM_IMAGES[currentImageIndex]}
                  alt="Sold With Sweeney & Co. Team"
                  fill
                  className="object-cover object-center"
                  sizes="(max-width: 1024px) 100vw, 50vw"
                />
              </motion.div>
            </AnimatePresence>
          </motion.div>

          {/* Right: text */}
          <div>
            <motion.div variants={fadeUp} className="flex items-center gap-3 mb-5">
              <Users weight="fill" className="w-4 h-4 text-gold" />
              <span className="text-gold text-xs font-semibold tracking-[0.25em] uppercase">
                The Team
              </span>
            </motion.div>

            <motion.h2
              variants={fadeUp}
              className="font-black text-white leading-[0.95] tracking-tight mb-6"
              style={{ fontSize: 'clamp(1.8rem, 4vw, 3.2rem)' }}
            >
              Sold With{' '}
              <span className="text-gold">Sweeney &amp; Co.</span>
            </motion.h2>

            <motion.p
              variants={fadeUp}
              className="text-white/60 text-base md:text-lg leading-relaxed font-light mb-6"
            >
              Brandon doesn&apos;t work alone. The Sold With Sweeney &amp; Co. team at Keller
              Williams Realty Success is a curated group of driven, client-first professionals who
              share Brandon&apos;s commitment to excellence and community.
            </motion.p>

            <motion.p
              variants={fadeUp}
              className="text-white/60 text-base leading-relaxed font-light mb-10"
            >
              Whether you&apos;re buying your first home, selling a high-end property, or building
              an investment portfolio, the Sold With Sweeney &amp; Co. team brings deep local
              knowledge, strategic thinking, and relentless hustle to every transaction.
            </motion.p>

            {/* Team highlights */}
            <motion.div variants={fadeUp} className="flex flex-col gap-4">
              {[
                'Merrimack Valley specialists — MA & NH',
                'Residential, Investment & Commercial expertise',
                'Dedicated buyer & seller representation',
              ].map((point) => (
                <div key={point} className="flex items-center gap-3">
                  <div className="w-1 h-1 rounded-full bg-gold shrink-0" />
                  <span className="text-white/55 text-sm font-light">{point}</span>
                </div>
              ))}
            </motion.div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

// ─── Section: Contact / CTA ────────────────────────────────────────────────────

function ContactSection() {
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { once: true, margin: '-80px' });

  return (
    <section
      ref={ref}
      className="relative bg-[#0a0a0a] py-28 md:py-36 overflow-hidden"
    >
      {/* Cinematic center bloom */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse at 50% 100%, rgba(234,196,105,0.1) 0%, transparent 60%)',
        }}
        aria-hidden="true"
      />
      <HalftoneOverlay opacity={0.04} />

      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12 w-full">
        <motion.div
          className="max-w-3xl mx-auto text-center"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          {/* Eyebrow */}
          <motion.div variants={fadeUp} className="flex items-center justify-center gap-3 mb-6">
            <Phone weight="fill" className="w-4 h-4 text-gold" />
            <span className="text-gold text-xs font-semibold tracking-[0.25em] uppercase">
              Get In Touch
            </span>
          </motion.div>

          {/* Heading */}
          <motion.h2
            variants={fadeUp}
            className="font-black text-white leading-[0.95] tracking-tight mb-6"
            style={{ fontSize: 'clamp(2.2rem, 5vw, 4.2rem)' }}
          >
            Ready to Work With{' '}
            <span className="text-gold">Brandon?</span>
          </motion.h2>

          <motion.p
            variants={fadeUp}
            className="text-white/55 text-base md:text-lg leading-relaxed font-light mb-12 max-w-xl mx-auto"
          >
            Whether you&apos;re buying, selling, or investing — Brandon and the Sold With Sweeney
            &amp; Co. team are ready to deliver results.
          </motion.p>

          {/* Contact details */}
          <motion.div
            variants={fadeUp}
            className="glass border border-dark-border p-8 md:p-10 mb-10 relative overflow-hidden"
          >
            {/* Inner refraction border */}
            <div
              className="absolute inset-px pointer-events-none"
              style={{ border: '1px solid rgba(255,255,255,0.05)' }}
              aria-hidden="true"
            />
            <div
              className="absolute top-0 left-8 right-8 h-px bg-gradient-to-r from-transparent via-gold/60 to-transparent"
              aria-hidden="true"
            />

            <div className="relative z-10 grid grid-cols-1 sm:grid-cols-3 gap-8">
              {/* Phone */}
              <div className="flex flex-col items-center gap-3">
                <div className="w-12 h-12 bg-gold/10 border border-gold/25 flex items-center justify-center">
                  <Phone weight="bold" className="w-5 h-5 text-gold" />
                </div>
                <div>
                  <div className="text-white/35 text-[10px] font-semibold tracking-[0.2em] uppercase mb-1">
                    Phone
                  </div>
                  <a
                    href="tel:9789872806"
                    className="text-white font-semibold text-sm hover:text-gold transition-colors duration-200"
                  >
                    (978) 987-2806
                  </a>
                </div>
              </div>

              {/* Email */}
              <div className="flex flex-col items-center gap-3">
                <div className="w-12 h-12 bg-gold/10 border border-gold/25 flex items-center justify-center">
                  <EnvelopeSimple weight="bold" className="w-5 h-5 text-gold" />
                </div>
                <div>
                  <div className="text-white/35 text-[10px] font-semibold tracking-[0.2em] uppercase mb-1">
                    Email
                  </div>
                  <a
                    href="mailto:info@SoldWithSweeney.com"
                    className="text-white font-semibold text-sm hover:text-gold transition-colors duration-200 break-all"
                  >
                    info@SoldWithSweeney.com
                  </a>
                </div>
              </div>

              {/* Office */}
              <div className="flex flex-col items-center gap-3">
                <div className="w-12 h-12 bg-gold/10 border border-gold/25 flex items-center justify-center">
                  <MapPin weight="bold" className="w-5 h-5 text-gold" />
                </div>
                <div>
                  <div className="text-white/35 text-[10px] font-semibold tracking-[0.2em] uppercase mb-1">
                    Office
                  </div>
                  <address className="text-white font-semibold text-sm not-italic leading-snug text-center">
                    101 Broadway Rd #21<br />Dracut, MA 01826
                  </address>
                </div>
              </div>
            </div>
          </motion.div>

          {/* CTA button */}
          <motion.div variants={fadeUp}>
            <a href="tel:9789872806">
              <motion.span
                className="inline-flex items-center gap-3 px-8 py-4 bg-gold text-[#0a0a0a] font-black text-sm tracking-widest uppercase hover:bg-gold-hover transition-colors duration-200"
                style={{ letterSpacing: '0.14em' }}
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
                transition={{ type: 'spring', stiffness: 100, damping: 20 }}
              >
                <Phone weight="bold" className="w-4 h-4" />
                Book a Call with Brandon
              </motion.span>
            </a>
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}

// ─── Page export ───────────────────────────────────────────────────────────────

export default function AboutPage() {
  return (
    <>
      <HeroSection />
      <StatsStrip />
      <BioSection />
      <DesignationsSection />
      <MSisBSSection />
      <TeamSection />
      <ContactSection />
    </>
  );
}
