'use client';

import { useEffect, useRef, useState } from 'react';
import { motion, useInView, AnimatePresence } from 'framer-motion';
import ReviewCard from '@/components/shared/ReviewCard';
import Image from 'next/image';

const stats = [
  { label: 'Satisfaction', value: 4.9, max: 5.0, display: '4.9/5.0' },
  { label: 'Performance', value: 5.0, max: 5.0, display: '5.0/5.0' },
  { label: 'Recommendation', value: 5.0, max: 5.0, display: '5.0/5.0' },
];

const reviews = [
  {
    quote:
      "Brandon went above and beyond throughout this process... He's a wonderful Realtor and an even better person.",
    author: 'Adam P',
    location: 'Lowell, MA',
  },
  {
    quote:
      'Working with Brandon was amazing! He made a generally stressful process feel much easier by being there for us every step of the way.',
    author: 'Jacqui',
    location: 'Westford, MA',
  },
  {
    quote:
      'Brandon was very responsive, very professional, presented a great marketing plan with a great price strategy.',
    author: 'Valerie W',
    location: 'Nashua, NH',
  },
  {
    quote:
      'Besides the outstanding assistance with valuing and marketing the property — the one that really stands out is patience.',
    author: 'Jim R',
    location: 'Dracut, MA',
  },
];

const designations = [
  { src: '/logos/Designations-Associations/NEAR.png', alt: 'NEAR — New England Association of REALTORS®' },
  { src: '/logos/Designations-Associations/MAR-Logo-Color-VERT-300dpi.png', alt: 'MAR — Massachusetts Association of REALTORS®' },
  {
    src: '/logos/Designations-Associations/National_Association_of_REALTORS_Logo.svg.png',
    alt: 'National Association of REALTORS®',
  },
  { src: '/logos/Designations-Associations/Green.jpg', alt: 'NAR Green Designation' },
];

function AnimatedNumber({ target, suffix = '' }: { target: number; suffix?: string }) {
  const [display, setDisplay] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: '-80px' });

  useEffect(() => {
    if (!inView) return;
    const start = performance.now();
    const duration = 1200;
    const from = 0;

    const animate = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // ease out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(parseFloat((from + (target - from) * eased).toFixed(1)));
      if (progress < 1) requestAnimationFrame(animate);
    };

    requestAnimationFrame(animate);
  }, [inView, target]);

  return (
    <span ref={ref}>
      {display.toFixed(1)}
      {suffix}
    </span>
  );
}

const containerVariants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { type: 'spring' as const, stiffness: 100, damping: 20 } },
};

export default function TrustSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const inView = useInView(sectionRef, { once: true, margin: '-100px' });

  return (
    <section
      ref={sectionRef}
      className="relative bg-[#0a0a0a] py-24 md:py-32 overflow-hidden"
    >
      {/* Subtle gold halftone */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(circle, #eac469 1px, transparent 1px)',
          backgroundSize: '28px 28px',
          opacity: 0.025,
        }}
        aria-hidden="true"
      />

      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
        {/* Section header */}
        <motion.div
          className="mb-16"
          initial={{ opacity: 0, y: 24 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ type: 'spring', stiffness: 100, damping: 20 }}
        >
          <span className="text-gold text-xs font-semibold tracking-[0.25em] uppercase block mb-3">
            Trusted By Hundreds
          </span>
          <h2
            className="font-black text-white tracking-tight"
            style={{ fontSize: 'clamp(2rem, 4vw, 3.5rem)' }}
          >
            The Numbers Speak
          </h2>
        </motion.div>

        {/* Stats — asymmetric bar chart style */}
        <motion.div
          className="grid grid-cols-1 md:grid-cols-3 gap-px bg-dark-border mb-20"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          {stats.map(({ label, value, display }) => (
            <motion.div
              key={label}
              variants={fadeUp}
              className="bg-[#0a0a0a] p-8 md:p-10 flex flex-col gap-3"
            >
              <div
                className="text-gold font-black leading-none"
                style={{ fontSize: 'clamp(2.5rem, 5vw, 4rem)' }}
              >
                <AnimatedNumber target={value} />/5.0
              </div>
              <div className="text-white/50 text-sm tracking-widest uppercase font-medium">
                {label}
              </div>
              {/* Progress bar */}
              <div className="h-0.5 bg-dark-border mt-2 overflow-hidden">
                <motion.div
                  className="h-full bg-gold"
                  initial={{ width: 0 }}
                  animate={inView ? { width: `${(value / 5) * 100}%` } : { width: 0 }}
                  transition={{ duration: 1.2, ease: 'easeOut', delay: 0.3 }}
                />
              </div>
            </motion.div>
          ))}
        </motion.div>

        {/* Reviews — asymmetric grid: 1 large left + 3 right stacked*/}
        <motion.div
          className="mb-20"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          <motion.h3
            variants={fadeUp}
            className="text-white/50 text-xs tracking-[0.25em] uppercase font-semibold mb-8"
          >
            Client Experiences
          </motion.h3>

          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
            {/* Large featured review */}
            <motion.div variants={fadeUp} className="lg:col-span-2">
              <ReviewCard
                quote={reviews[0].quote}
                author={reviews[0].author}
                location={reviews[0].location}
                className="h-full"
              />
            </motion.div>

            {/* Three stacked reviews */}
            <div className="lg:col-span-3 grid grid-cols-1 gap-4">
              {reviews.slice(1).map((review) => (
                <motion.div key={review.author} variants={fadeUp}>
                  <ReviewCard
                    quote={review.quote}
                    author={review.author}
                    location={review.location}
                  />
                </motion.div>
              ))}
            </div>
          </div>
        </motion.div>

        {/* Designation badges */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          <motion.p
            variants={fadeUp}
            className="text-white/30 text-xs tracking-[0.25em] uppercase font-semibold mb-6 text-center"
          >
            Designations &amp; Associations
          </motion.p>
          <motion.div
            variants={fadeUp}
            className="flex flex-wrap items-center justify-center gap-8 md:gap-12"
          >
            {designations.map(({ src, alt }) => (
              <div
                key={src}
                className="relative h-12 w-auto flex items-center justify-center opacity-50 hover:opacity-80 transition-opacity duration-200"
              >
                <Image
                  src={src}
                  alt={alt}
                  width={80}
                  height={48}
                  className="object-contain max-h-12 w-auto"
                  unoptimized
                />
              </div>
            ))}
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}
