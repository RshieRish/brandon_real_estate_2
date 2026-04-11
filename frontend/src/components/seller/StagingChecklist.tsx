'use client';

import { useState } from 'react';
import Image from 'next/image';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle } from '@phosphor-icons/react';

const CHECKLIST_ITEMS = [
  { id: 'photos', label: 'Remove personal photos', video: '/videos/Removing_personal_photos_202603311933.mp4' },
  { id: 'clean', label: 'Deep clean every room', video: '/videos/Kitchen_deep_clean_202603311933.mp4' },
  { id: 'neutral', label: 'Apply fresh neutral paint where needed', video: '/videos/Apply_neutral_paint_202603311933.mp4' },
  { id: 'counters', label: 'Clear countertops', video: '/videos/Countertops_cleared_of_202603311934.mp4' },
  { id: 'declutter', label: 'Declutter all spaces', video: '/videos/Decluttering_transformation_of_202603311933.mp4' },
  { id: 'lawn', label: 'Manicure the lawn', video: '/videos/Manicure_the_lawn_202603311933.mp4' },
  { id: 'beds', label: 'Style beds with fresh linens', video: '/videos/styling-beds.mp4' },
  { id: 'closets', label: 'Organize closets', video: '/videos/Closet_organizes_itself_202603311934.mp4' },
  { id: 'cords', label: 'Hide cords and cables', video: '/videos/Hide_cords_and_202603311935.mp4' },
  { id: 'fixtures', label: 'Clean or replace light fixtures', video: '/videos/Clean_or_Replace_202603311935.mp4' },
  { id: 'flowers', label: 'Add fresh flowers or plants', video: '/videos/Add_fresh_flowers_202603311935.mp4' },
];

function CheckboxIcon({ checked }: { checked: boolean }) {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 22 22"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      className="flex-shrink-0"
    >
      <rect
        x="1"
        y="1"
        width="20"
        height="20"
        rx="4"
        stroke={checked ? '#eac469' : '#2a2a2a'}
        strokeWidth="1.5"
        fill={checked ? 'rgba(234,196,105,0.1)' : 'transparent'}
        style={{ transition: 'all 0.2s ease' }}
      />
      {checked && (
        <path
          d="M6 11l3.5 3.5L16 7.5"
          stroke="#eac469"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
    </svg>
  );
}

export default function StagingChecklist() {
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [activeVideo, setActiveVideo] = useState<string | null>('/videos/Home_from_listing_202603312328.mp4');

  function toggle(id: string, videoSrc?: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
        if (videoSrc) {
          setActiveVideo(videoSrc);
        }
      }
      return next;
    });
  }

  const completedCount = checked.size;
  const totalCount = CHECKLIST_ITEMS.length;
  const progressPercent = Math.round((completedCount / totalCount) * 100);
  const isComplete = completedCount === totalCount;

  return (
    <section className="relative bg-dark-card py-24 md:py-32 overflow-hidden">
      {/* Halftone */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(circle, #eac469 1px, transparent 1px)',
          backgroundSize: '28px 28px',
          opacity: 0.02,
        }}
        aria-hidden="true"
      />

      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
        {/* Header */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-start">
          <motion.div
            initial={{ opacity: 0, x: -30 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: '-80px' }}
            transition={{ type: 'spring', stiffness: 100, damping: 20 }}
          >
            <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
              Seller Toolkit
            </p>
            <h2
              className="font-black text-white leading-tight tracking-tight mb-4"
              style={{ fontSize: 'clamp(1.8rem, 3.5vw, 3rem)' }}
            >
              Pre-Listing{' '}
              <span className="text-gold" style={{ textShadow: '0 0 28px rgba(234,196,105,0.25)' }}>
                Staging
              </span>{' '}
              Checklist
            </h2>
            <p className="text-white/60 text-sm font-light leading-relaxed max-w-md">
              Staged homes sell up to 88% faster and for more money. Check off each item as you
              prepare your home for market — Brandon&apos;s team is here to guide every step.
            </p>

            {/* Progress */}
            <div className="mt-8">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-semibold text-white/50 uppercase tracking-widest">
                  Progress
                </span>
                <span className="text-xs font-bold text-gold tabular-nums">
                  {completedCount} / {totalCount}
                </span>
              </div>
              <div className="h-2 bg-dark-border rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-gold rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${progressPercent}%` }}
                  transition={{ type: 'spring', stiffness: 80, damping: 20 }}
                />
              </div>

              <AnimatePresence>
                {isComplete && (
                  <motion.div
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ type: 'spring', stiffness: 100, damping: 20 }}
                    className="mt-4 flex items-center gap-2 text-gold text-sm font-semibold"
                  >
                    <CheckCircle weight="fill" className="w-5 h-5" />
                    Your home is ready to list — reach out to Brandon!
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
            <p className="text-white/30 text-xs font-light mt-6 leading-relaxed">
              This is a standard tool. For a dedicated list based on your home, reach out to Brandon.
            </p>

            {/* Staging Media */}
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ type: 'spring', stiffness: 100, damping: 20, delay: 0.2 }}
              className="mt-8 relative rounded-xl overflow-hidden border border-dark-border aspect-[4/3] bg-black"
            >
              <AnimatePresence mode="wait">
                {activeVideo ? (
                  <motion.video
                    key={activeVideo}
                    src={activeVideo}
                    autoPlay
                    muted
                    loop
                    playsInline
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.6 }}
                    className="absolute inset-0 w-full h-full object-cover opacity-80"
                  />
                ) : (
                  <motion.div
                    key="fallback-image"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.6 }}
                    className="absolute inset-0"
                  >
                    <Image
                      src="/frames/frame_030.webp"
                      alt="Professionally staged home interior"
                      fill
                      className="object-cover opacity-70"
                      sizes="(max-width: 1024px) 100vw, 45vw"
                    />
                  </motion.div>
                )}
              </AnimatePresence>
              <div
                className="absolute inset-0 pointer-events-none"
                style={{ background: 'linear-gradient(to top, rgba(10,10,10,0.7) 0%, transparent 60%)' }}
                aria-hidden="true"
              />
              <div className="absolute bottom-4 left-4 right-4">
                <p className="text-white/80 text-xs font-semibold tracking-wider uppercase">
                  Staged homes sell up to 88% faster
                </p>
              </div>
            </motion.div>
          </motion.div>

          {/* Checklist */}
          <motion.div
            initial={{ opacity: 0, x: 30 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: '-80px' }}
            transition={{ type: 'spring', stiffness: 100, damping: 20 }}
            className="glass border border-dark-border rounded-xl p-6 md:p-8"
          >
            <ul className="space-y-1" role="list">
              {CHECKLIST_ITEMS.map((item, index) => {
                const isChecked = checked.has(item.id);
                return (
                  <motion.li
                    key={item.id}
                    initial={{ opacity: 0, y: 10 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true }}
                    transition={{
                      type: 'spring',
                      stiffness: 100,
                      damping: 20,
                      delay: index * 0.04,
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => toggle(item.id, item.video)}
                      className={`w-full flex items-center gap-3 px-3 py-3 rounded-lg text-left transition-colors ${
                        isChecked
                          ? 'bg-gold/5'
                          : 'hover:bg-white/5'
                      }`}
                      aria-pressed={isChecked}
                    >
                      <CheckboxIcon checked={isChecked} />
                      <span
                        className={`text-sm font-medium transition-colors ${
                          isChecked ? 'text-white/40 line-through' : 'text-white/80'
                        }`}
                      >
                        {item.label}
                      </span>
                    </button>
                  </motion.li>
                );
              })}
            </ul>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
