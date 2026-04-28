'use client';

import { useRef, useState, useEffect } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import { House, CurrencyDollar, ChartLine, ArrowDown } from '@phosphor-icons/react';
import RotatingText from '@/components/shared/RotatingText';

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: {
      staggerChildren: 0.12,
      delayChildren: 0.3,
    },
  },
};

const item = {
  hidden: { opacity: 0, y: 32 },
  show: {
    opacity: 1,
    y: 0,
    transition: { type: 'spring' as const, stiffness: 100, damping: 20 },
  },
};

const ctaButtons = [
  {
    label: 'Buy with Brandon',
    href: '/buy',
    icon: House,
    variant: 'gold',
  },
  {
    label: 'Sell With Brandon',
    href: '/sell',
    icon: CurrencyDollar,
    variant: 'outline',
  },
  {
    label: 'Analyze a Deal',
    href: '/invest',
    icon: ChartLine,
    variant: 'outline',
  },
] as const;

export default function Hero() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoReady, setVideoReady] = useState(false);
  const [videoSrc, setVideoSrc] = useState('/assets/aerial_drone_shot.mp4');

  useEffect(() => {
    // Check location for dynamic video
    fetch('https://get.geojs.io/v1/ip/geo.json')
      .then((res) => res.json())
      .then((data) => {
        if (data.city === 'Dracut' || data.city === 'Lowell') {
          setVideoReady(false);
          setVideoSrc('/assets/Dracut_compressed.mp4');
        } else if (data.city === 'Andover') {
          setVideoReady(false);
          setVideoSrc('/assets/Andover_compressed.mp4');
        }
      })
      .catch((err) => console.error('Failed to get location:', err));
  }, []);

  return (
    <AnimatePresence>
      <section className="relative min-h-[100dvh] flex flex-col justify-center overflow-hidden bg-[#0a0a0a]">
        {/* Background video */}
        <video
          key={videoSrc}
          ref={videoRef}
          className="absolute inset-0 w-full h-full object-cover"
          src={videoSrc}
          preload="auto"
          autoPlay
          muted
          loop
          playsInline
          onLoadedData={() => setVideoReady(true)}
          style={{
            opacity: videoReady ? 1 : 0,
            transition: 'opacity 480ms ease',
          }}
          aria-hidden="true"
        />

        {!videoReady && (
          <div
            className="absolute inset-0"
            style={{
              background:
                'radial-gradient(circle at 78% 18%, rgba(234,196,105,0.15) 0%, rgba(10,10,10,0.92) 40%, #0a0a0a 100%)',
            }}
            aria-hidden="true"
          />
        )}

        {/* Gradient overlay — dark left-dominant */}
        <div
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(105deg, rgba(10,10,10,0.97) 0%, rgba(10,10,10,0.82) 50%, rgba(10,10,10,0.45) 100%)',
          }}
          aria-hidden="true"
        />

        {/* Gold halftone texture */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage: 'radial-gradient(circle, #eac469 1px, transparent 1px)',
            backgroundSize: '24px 24px',
            opacity: 0.03,
          }}
          aria-hidden="true"
        />

        {/* Content — left-aligned, asymmetric */}
        <motion.div
          className="relative z-10 w-full max-w-7xl mx-auto px-6 md:px-12 pt-24 pb-32"
          variants={container}
          initial="hidden"
          animate="show"
        >
          <div className="max-w-2xl">
            {/* Eyebrow badge */}
            <motion.div variants={item} className="mb-6">
              <span className="inline-block glass border border-gold/30 text-gold text-xs font-semibold tracking-widest uppercase px-4 py-2 leading-relaxed">
                Northeast Association of REALTORS<sup className="text-[0.6em] uppercase font-bold relative -top-1 ml-[0.02em]">&reg;</sup> Realtor Of The Year 2025 <span className="mx-1.5 opacity-50">|</span> Keller Williams Realty Success
              </span>
            </motion.div>

            {/* H1 */}
            <motion.h1
              variants={item}
              className="font-black text-white leading-[0.95] tracking-tight mb-6"
              style={{ fontSize: 'clamp(2.8rem, 7vw, 6rem)' }}
            >
              <span className="inline-flex flex-wrap items-baseline gap-x-[0.3em]">
                <span>NOT</span>
                <RotatingText
                  text={[
                    'Your',       // English
                    'Tu',         // Spanish
                    'आपका',       // Hindi
                    'របស់អ្នក',    // Cambodian
                    'ของคุณ',     // Thai
                    'Votre',      // French
                    '你的',       // Chinese
                    'あなたの'    // Japanese
                  ]}
                  containerClassName="inline-flex items-baseline min-w-[5rem] py-1"
                />
              </span>
              <br />
              <span
                className="text-gold relative inline-block mt-1"
                style={{ textShadow: '0 0 40px rgba(234,196,105,0.35)' }}
              >
                AVERAGE
              </span>
              <br />
              REALTOR<sup className="text-[0.35em] font-normal opacity-60 ml-[0.02em] align-super relative -top-[0.4em]">&reg;</sup>
            </motion.h1>

            {/* Subtext */}
            <motion.p
              variants={item}
              className="text-white/70 text-base md:text-lg leading-relaxed mb-10 max-w-xl font-light"
            >
              Award-winning. Philanthropic. Results-driven. Serving buyers, sellers &amp; investors
              across MA &amp; NH.
            </motion.p>

            {/* CTA buttons */}
            <motion.div variants={item} className="flex flex-wrap sm:flex-nowrap gap-4">
              {ctaButtons.map(({ label, href, icon: Icon, variant }) => (
                <Link key={href} href={href}>
                  <motion.span
                    className={`inline-flex items-center gap-2.5 px-6 py-3.5 font-semibold text-sm tracking-widest uppercase transition-colors duration-200 ${
                      variant === 'gold'
                        ? 'bg-gold text-[#0a0a0a] hover:bg-gold-hover'
                        : 'border border-gold/60 text-gold hover:bg-gold hover:text-[#0a0a0a]'
                    }`}
                    whileHover={{ scale: 1.03 }}
                    whileTap={{ scale: 0.97 }}
                    transition={{ type: 'spring', stiffness: 100, damping: 20 }}
                  >
                    <Icon weight="bold" className="w-4 h-4" />
                    {label}
                  </motion.span>
                </Link>
              ))}
            </motion.div>
          </div>
        </motion.div>

        {/* Scroll indicator */}
        <motion.div
          className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-2"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.4, type: 'spring', stiffness: 100, damping: 20 }}
        >
          <span className="text-white/40 text-xs tracking-[0.2em] uppercase font-medium">Scroll</span>
          <motion.div
            animate={{ y: [0, 8, 0] }}
            transition={{ repeat: Infinity, duration: 1.6, ease: 'easeInOut' }}
          >
            <ArrowDown weight="light" className="w-5 h-5 text-gold/60" />
          </motion.div>
        </motion.div>
      </section>
    </AnimatePresence>
  );
}
