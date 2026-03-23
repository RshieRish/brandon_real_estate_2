'use client';

import { motion } from 'framer-motion';
import { CalendarBlank, CheckCircle, ArrowDown } from '@phosphor-icons/react';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';

interface FunnelContent {
  hero_headline?: string;
  hero_subtext?: string;
  details_heading?: string;
  details_body?: string;
  value_props?: string[];
  testimonial?: string;
  cta_headline?: string;
  cta_subtext?: string;
}

interface FunnelData {
  title: string;
  audience: string;
  event_date: string | null;
  video_url: string | null;
  hero_image_url: string | null;
  cta_text: string;
  content: FunnelContent;
}

interface FunnelHeroProps {
  funnel: FunnelData;
}

const spring = { type: 'spring' as const, stiffness: 100, damping: 20 };

function headlineWithGoldLastWord(text: string) {
  const words = text.split(' ');
  if (words.length <= 1) return <span className="text-gold">{text}</span>;
  const last = words.pop()!;
  return (
    <>
      {words.join(' ')}{' '}
      <span className="text-gold" style={{ textShadow: '0 0 48px rgba(234,196,105,0.4)' }}>
        {last}
      </span>
    </>
  );
}

function audienceLabel(audience: string): string {
  const map: Record<string, string> = {
    buyers: 'For Buyers',
    buyer: 'For Buyers',
    sellers: 'For Sellers',
    seller: 'For Sellers',
    investors: 'For Investors',
    investor: 'For Investors',
  };
  return map[audience.toLowerCase()] ?? audience;
}

function isSafeEmbedUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return (
      parsed.hostname === 'www.youtube.com' ||
      parsed.hostname === 'youtube.com' ||
      parsed.hostname === 'player.vimeo.com' ||
      parsed.hostname === 'www.loom.com'
    );
  } catch {
    return false;
  }
}

export default function FunnelHero({ funnel }: FunnelHeroProps) {
  const headline = funnel.content?.hero_headline ?? funnel.title;
  const subtext = funnel.content?.hero_subtext;
  const detailsBody = funnel.content?.details_body;
  const valueProps = funnel.content?.value_props;
  return (
    <section
      className="relative min-h-[100dvh] flex flex-col justify-center overflow-hidden bg-[#0a0a0a]"
    >
      {/* Hero background image (if provided) */}
      {funnel.hero_image_url && (
        <img
          src={
            funnel.hero_image_url.startsWith('/')
              ? `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8001'}${funnel.hero_image_url}`
              : funnel.hero_image_url
          }
          alt=""
          className="absolute inset-0 w-full h-full object-cover"
          aria-hidden="true"
        />
      )}

      {/* Cinematic gradient — asymmetric sweep */}
      <div
        className="absolute inset-0"
        style={{
          background: funnel.hero_image_url
            ? 'linear-gradient(105deg, rgba(10,10,10,0.95) 0%, rgba(10,10,10,0.80) 50%, rgba(10,10,10,0.60) 100%)'
            : 'linear-gradient(105deg, rgba(10,10,10,0.97) 0%, rgba(10,10,10,0.88) 50%, rgba(192,130,53,0.06) 100%)',
        }}
        aria-hidden="true"
      />

      <HalftoneOverlay opacity={0.04} />

      {/* Gold accent — left edge */}
      <div
        className="absolute left-0 top-0 bottom-0 w-1 bg-gold"
        style={{ boxShadow: '0 0 40px rgba(234,196,105,0.5)' }}
        aria-hidden="true"
      />

      {/* Main content — asymmetric grid */}
      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12 pt-24 pb-32 w-full">
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-16 items-center">
          {/* Left column — text */}
          <div className="max-w-2xl">
            {/* Event date badge */}
            {funnel.event_date && (
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ ...spring, delay: 0.1 }}
                className="mb-6"
              >
                <span className="inline-flex items-center gap-2 glass border border-gold/30 text-gold text-xs font-semibold tracking-widest uppercase px-4 py-2">
                  <CalendarBlank weight="fill" className="w-4 h-4 flex-shrink-0" />
                  {new Date(funnel.event_date).toLocaleDateString('en-US', {
                    weekday: 'long',
                    month: 'long',
                    day: 'numeric',
                    year: 'numeric',
                  })}
                </span>
              </motion.div>
            )}

            {/* Audience eyebrow */}
            <motion.span
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...spring, delay: 0.15 }}
              className="inline-block border border-gold/40 text-gold text-xs font-semibold tracking-widest uppercase px-4 py-2 mb-6"
            >
              {audienceLabel(funnel.audience)}
            </motion.span>

            {/* Headline */}
            <motion.h1
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...spring, delay: 0.25 }}
              className="font-black text-white leading-[0.95] tracking-tight mb-6"
              style={{ fontSize: 'clamp(2.8rem, 7vw, 5.5rem)' }}
            >
              {headlineWithGoldLastWord(headline)}
            </motion.h1>

            {/* Subtext */}
            {subtext && (
              <motion.p
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...spring, delay: 0.35 }}
                className="text-white/65 text-base md:text-lg leading-relaxed mb-10 max-w-xl font-light"
              >
                {subtext}
              </motion.p>
            )}

            {/* Body copy */}
            {detailsBody && (
              <motion.p
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...spring, delay: 0.4 }}
                className="text-white/50 text-sm leading-relaxed mb-8 max-w-lg font-light"
              >
                {detailsBody}
              </motion.p>
            )}

            {/* Value props as bullet list */}
            {valueProps && valueProps.length > 0 && (
              <div className="space-y-4 mb-8">
                {valueProps.map((point, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, x: -16 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ ...spring, delay: 0.45 + i * 0.08 }}
                    className="flex items-start gap-3"
                  >
                    <CheckCircle weight="fill" className="w-5 h-5 text-gold flex-shrink-0 mt-0.5" />
                    <span className="text-white/70 text-sm leading-relaxed">{point}</span>
                  </motion.div>
                ))}
              </div>
            )}
          </div>

          {/* Right column — video embed or decorative stat block */}
          {funnel.video_url && isSafeEmbedUrl(funnel.video_url) ? (
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ ...spring, delay: 0.4 }}
              className="hidden lg:block w-[380px]"
            >
              <div className="glass border border-gold/20 p-2 shadow-2xl">
                <div className="aspect-video">
                  <iframe
                    src={funnel.video_url}
                    title={`Video: ${funnel.title}`}
                    className="w-full h-full"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowFullScreen
                  />
                </div>
              </div>
            </motion.div>
          ) : (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...spring, delay: 0.5 }}
              className="hidden lg:flex flex-col gap-1 border border-gold/20 bg-dark-card/60 backdrop-blur-sm p-8 min-w-[220px]"
            >
              <div className="border-b border-dark-border pb-5 mb-5">
                <p className="text-gold font-black text-4xl leading-none">100+</p>
                <p className="text-gray text-xs tracking-wide mt-1 uppercase font-medium">Deals Closed</p>
              </div>
              <div className="border-b border-dark-border pb-5 mb-5">
                <p className="text-gold font-black text-4xl leading-none">2025</p>
                <p className="text-gray text-xs tracking-wide mt-1 uppercase font-medium">REALTOR&reg; of the Year</p>
              </div>
              <div>
                <p className="text-gold font-black text-4xl leading-none">MA+NH</p>
                <p className="text-gray text-xs tracking-wide mt-1 uppercase font-medium">Markets Served</p>
              </div>
            </motion.div>
          )}
        </div>
      </div>

      {/* Scroll nudge */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1 }}
        className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-2 pointer-events-none"
      >
        <span className="text-white/30 text-xs tracking-[0.2em] uppercase font-medium">Scroll</span>
        <ArrowDown weight="light" className="w-5 h-5 text-gold/50 animate-bounce" />
      </motion.div>

      {/* Bottom gradient fade */}
      <div
        className="absolute bottom-0 left-0 right-0 h-32 pointer-events-none"
        style={{ background: 'linear-gradient(to bottom, transparent, #0a0a0a)' }}
        aria-hidden="true"
      />
    </section>
  );
}
