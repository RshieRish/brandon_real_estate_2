'use client';

import { useEffect, useRef, useState } from 'react';
import { motion, useInView, AnimatePresence } from 'framer-motion';
import ReviewCard from '@/components/shared/ReviewCard';
import Image from 'next/image';

import AnimatedNumber from '@/components/shared/AnimatedNumber';

interface TrustSectionProps {
  volumeDone?: string;
  familiesServed?: string;
  yearsInBusiness?: string;
}

const ratingStats = [
  { label: 'Satisfaction', value: 4.9, max: 5.0, suffix: '/5.0', decimals: 1, prefix: '', progress: true },
  { label: 'Performance', value: 5.0, max: 5.0, suffix: '/5.0', decimals: 1, prefix: '', progress: true },
  { label: 'Recommendation', value: 5.0, max: 5.0, suffix: '/5.0', decimals: 1, prefix: '', progress: true },
];

const reviews = [
  {
    quote:
      "Brandon helped my husband and me buy our dream home, and we’re so grateful for him. The property was a total gem—and super competitive—but he guided us through it all with confidence and ease. His communication was always clear and timely, and he answered every single question we had (and we had a lot!). Brandon is not only a great negotiator, but also just a kind, down-to-earth person who makes a stressful process feel manageable.",
    author: 'Yasmine Turco',
    location: 'Facebook',
  },
  {
    quote:
      "Brandon did a phenomenal job in helping me sell my parents' home. He kept me informed at all times and was always available to answer any questions I had. He got the house listed and sold so quickly at a great price which was very important to me and my family. I definitely would recommend Brandon to anyone looking to sell their home.",
    author: 'Jeannine R.',
    location: 'Zillow',
  },
  {
    quote:
      "From start to finish, the homebuying process from Brandon was smooth and as worry-free as it could have possibly been for a pair of first-time homebuyers. Always having answers to questions, scheduling showings quickly and being responsive to anything that came up. Just an overall A+++ experience.",
    author: 'Dan Emond',
    location: 'Google',
  },
  {
    quote:
      "Brandon was fantastic. He was so patient, very responsive and so knowledgeable. He works where he grew up so he knows all about the area and the market. He answered all of my questions thoroughly and made me feel comfortable with the entire process. I knew I was in good hands working with him.",
    author: 'Sonya Reagan',
    location: 'RealSatisfied',
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



const containerVariants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { type: 'spring' as const, stiffness: 100, damping: 20 } },
};

export default function TrustSection({
  volumeDone = '100',
  familiesServed = '250',
  yearsInBusiness = '10',
}: TrustSectionProps) {
  const sectionRef = useRef<HTMLElement>(null);
  const inView = useInView(sectionRef, { once: true, margin: '-100px' });

  const dynStats = [
    { label: 'Real Estate Sold', value: parseFloat(volumeDone.replace(/[^0-9.]/g, '')), suffix: 'M+', decimals: 0, prefix: '$', progress: false },
    { label: 'Families Served', value: parseFloat(familiesServed.replace(/[^0-9.]/g, '')), suffix: '+', decimals: 0, prefix: '', progress: false },
    { label: 'Years in Business', value: parseFloat(yearsInBusiness.replace(/[^0-9.]/g, '')), suffix: '+', decimals: 0, prefix: '', progress: false },
  ];

  const allStats = [...dynStats, ...ratingStats];

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
            The Numbers Speak For Themselves
          </h2>
        </motion.div>

        {/* Stats — asymmetric bar chart style */}
        <motion.div
          className="grid grid-cols-1 md:grid-cols-3 gap-px bg-dark-border mb-20"
          variants={containerVariants}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
        >
          {allStats.map((stat) => (
            <motion.div
              key={stat.label}
              variants={fadeUp}
              className="bg-[#0a0a0a] p-8 md:p-10 flex flex-col gap-3"
            >
              <div
                className="text-gold font-black leading-none"
                style={{ fontSize: 'clamp(2.5rem, 5vw, 4rem)' }}
              >
                <AnimatedNumber target={stat.value} suffix={stat.suffix} prefix={stat.prefix} decimals={stat.decimals} />
              </div>
              <div className="text-white/50 text-sm tracking-widest uppercase font-medium">
                {stat.label}
              </div>
              {/* Progress bar */}
              {stat.progress && (
                <div className="h-0.5 bg-dark-border mt-2 overflow-hidden">
                  <motion.div
                    className="h-full bg-gold"
                    initial={{ width: 0 }}
                    animate={inView ? { width: `${(stat.value / 5) * 100}%` } : { width: 0 }}
                    transition={{ duration: 1.2, ease: 'easeOut', delay: 0.3 }}
                  />
                </div>
              )}
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
                className="relative h-12 w-auto flex items-center justify-center opacity-70 hover:opacity-100 transition-opacity duration-200"
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
