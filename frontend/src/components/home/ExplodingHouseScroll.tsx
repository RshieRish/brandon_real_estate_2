'use client';

import { useEffect, useRef } from 'react';

const TEXT_OVERLAYS = [
  {
    threshold: 0,
    eyebrow: 'CURATED VISION',
    heading: 'Every home has a story',
    sub: 'Sold With Sweeney & Co. helps you write yours.',
  },
  {
    threshold: 0.3,
    eyebrow: 'PROVEN STRATEGY',
    heading: 'Market expertise, real results',
    sub: 'Award-winning negotiation and marketing strategy across Massachusetts and New Hampshire.',
  },
  {
    threshold: 0.6,
    eyebrow: 'THE DIFFERENCE',
    heading: 'Not just listed — sold',
    sub: 'Precision pricing, maximum exposure, and expert negotiation to maximize what you walk away with.',
  },
  {
    threshold: 0.85,
    eyebrow: 'THE NEXT CHAPTER',
    heading: "Ready to make your move?",
    sub: "Let's curate the winning team and strategy and move you from A to B.",
  },
];

function getOverlayIndex(progress: number) {
  let idx = 0;
  for (let i = 0; i < TEXT_OVERLAYS.length; i++) {
    if (progress >= TEXT_OVERLAYS[i].threshold) idx = i;
  }
  return idx;
}

// Lerp factor — higher = snappier tracking, lower = smoother lag
// 0.12 balances responsiveness with smoothness at 60fps
const LERP_FACTOR = 0.12;

// Snap threshold — when close enough, jump to target to avoid infinite drift
const SNAP_THRESHOLD = 0.0001;

export default function ExplodingHouseScroll() {
  const containerRef = useRef<HTMLDivElement>(null);
  const forwardVideoRef = useRef<HTMLVideoElement>(null);

  // DOM refs for direct manipulation (zero re-renders during scroll)
  const eyebrowRef = useRef<HTMLParagraphElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const subRef = useRef<HTMLParagraphElement>(null);
  const overlayWrapperRef = useRef<HTMLDivElement>(null);
  const textBlockRef = useRef<HTMLDivElement>(null);

  const targetProgressRef = useRef(0);
  const smoothProgressRef = useRef(0);
  const rafRef = useRef<number>(0);
  const currentOverlayIdxRef = useRef(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Manual scroll progress calculation — avoids Framer Motion's overhead
    const computeProgress = () => {
      const rect = container.getBoundingClientRect();
      const scrollHeight = container.scrollHeight - window.innerHeight;
      if (scrollHeight <= 0) return 0;
      const raw = -rect.top / scrollHeight;
      return Math.max(0, Math.min(1, raw));
    };

    // Passive scroll listener — just updates target, no heavy work
    const onScroll = () => {
      targetProgressRef.current = computeProgress();
    };

    // Set initial value
    targetProgressRef.current = computeProgress();
    smoothProgressRef.current = targetProgressRef.current;

    window.addEventListener('scroll', onScroll, { passive: true });

    // Direct DOM text update — no React reconciliation
    const updateOverlayText = (idx: number) => {
      if (idx === currentOverlayIdxRef.current) return;

      const eyebrow = eyebrowRef.current;
      const heading = headingRef.current;
      const sub = subRef.current;
      const block = textBlockRef.current;
      if (!eyebrow || !heading || !sub || !block) return;

      // Fade out
      block.style.opacity = '0';
      block.style.transform = 'translateY(-12px)';

      setTimeout(() => {
        eyebrow.textContent = TEXT_OVERLAYS[idx].eyebrow;
        heading.textContent = TEXT_OVERLAYS[idx].heading;
        sub.textContent = TEXT_OVERLAYS[idx].sub;
        // Fade in
        block.style.opacity = '1';
        block.style.transform = 'translateY(0)';
        currentOverlayIdxRef.current = idx;
      }, 180);
    };



    // Update overlay container opacity based on scroll edges
    const updateOverlayOpacity = (progress: number) => {
      const wrapper = overlayWrapperRef.current;
      if (!wrapper) return;
      let opacity = 1;
      if (progress < 0.05) opacity = progress / 0.05;
      else if (progress > 0.9) opacity = (1 - progress) / 0.1;
      wrapper.style.opacity = String(Math.max(0, Math.min(1, opacity)));
    };

    // Core animation loop — runs at display refresh rate
    const tick = () => {
      const target = targetProgressRef.current;
      let current = smoothProgressRef.current;

      const delta = target - current;

      // Snap when close enough to avoid asymptotic drift
      if (Math.abs(delta) < SNAP_THRESHOLD) {
        current = target;
      } else {
        current += delta * LERP_FACTOR;
      }

      smoothProgressRef.current = current;

      // Scrub the active video — Forward then backwards to create a perfect loop
      const fwd = forwardVideoRef.current;

      if (fwd && fwd.duration) {
        let t;
        if (current <= 0.5) {
          // Explode (0 to duration)
          t = Math.min((current / 0.5), 1) * fwd.duration;
        } else {
          // Reassemble (duration back to 0)
          t = Math.max((1 - current) / 0.5, 0) * fwd.duration;
        }
        
        // Only seek if the change is meaningful (> ~1 frame at 24fps)
        if (Math.abs(fwd.currentTime - t) > 0.02) {
          fwd.currentTime = t;
        }
      }

      // Update text and opacity — all direct DOM, zero React
      updateOverlayText(getOverlayIndex(current));
      updateOverlayOpacity(current);

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      window.removeEventListener('scroll', onScroll);
      cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <div ref={containerRef} className="relative" style={{ height: '300vh' }}>
      <div className="sticky top-0 min-h-[100dvh] overflow-hidden bg-[#0a0a0a]">

        {/* Scroll scrub timeline: 0-50% Explodes, 50-100% Reassembles perfectly backwards */}
        <video
          ref={forwardVideoRef}
          className="absolute inset-0 w-full h-full object-cover"
          src="/assets/house_blast_forward_kf.mp4"
          muted
          playsInline
          preload="auto"
          aria-hidden="true"
        />

        {/* Dark vignette */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              'radial-gradient(ellipse at center, transparent 40%, rgba(10,10,10,0.7) 100%)',
          }}
          aria-hidden="true"
        />

        {/* Text overlay — all direct DOM manipulation, no AnimatePresence */}
        <div
          ref={overlayWrapperRef}
          className="absolute inset-0 flex flex-col items-center justify-center z-10 px-6 text-center"
          style={{ opacity: 0 }}
        >
          <div
            ref={textBlockRef}
            className="w-[85%] max-w-[280px] md:max-w-[320px] mx-auto bg-[#0a0a0a]/30 backdrop-blur-md border border-white/10 shadow-2xl rounded-[2.5rem] py-16 px-8 md:py-20 md:px-10 flex flex-col items-center justify-center text-center"
            style={{
              transition: 'opacity 0.25s ease-out, transform 0.25s ease-out',
              opacity: 1,
              transform: 'translateY(0)',
            }}
          >
            <p
              ref={eyebrowRef}
              className="text-gold text-[0.6rem] md:text-[0.65rem] font-semibold tracking-[0.35em] md:tracking-[0.4em] uppercase mb-8"
            >
              {TEXT_OVERLAYS[0].eyebrow}
            </p>
            <h2
              ref={headingRef}
              className="font-black text-white text-3xl md:text-4xl leading-[1.1] tracking-tight mb-8"
            >
              {TEXT_OVERLAYS[0].heading}
            </h2>
            <p ref={subRef} className="text-white/70 text-xs md:text-sm leading-relaxed font-light">
              {TEXT_OVERLAYS[0].sub}
            </p>
          </div>
        </div>

        {/* Bottom gradient fade into next section */}
        <div
          className="absolute bottom-0 left-0 right-0 h-32 pointer-events-none"
          style={{ background: 'linear-gradient(to bottom, transparent, #0a0a0a)' }}
          aria-hidden="true"
        />
      </div>
    </div>
  );
}
