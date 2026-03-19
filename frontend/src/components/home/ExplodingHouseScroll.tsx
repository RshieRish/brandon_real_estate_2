'use client';

import { useEffect, useRef, useState } from 'react';
import { motion, useScroll, useTransform, AnimatePresence } from 'framer-motion';

const TOTAL_FRAMES = 60;
const FRAME_PATH = (n: number) =>
  `/frames/house-blast/frame_${String(n).padStart(4, '0')}.jpg`;

const TEXT_OVERLAYS = [
  {
    threshold: 0,
    heading: 'Every Home Has a Story',
    sub: 'Brandon Sweeney helps you write yours.',
  },
  {
    threshold: 0.4,
    heading: 'Market Expertise. Real Results.',
    sub: 'Award-winning strategy across MA & NH.',
  },
  {
    threshold: 0.75,
    heading: 'Ready to Make Your Move?',
    sub: 'Let\'s find your perfect property together.',
  },
];

function getOverlay(progress: number) {
  let active = TEXT_OVERLAYS[0];
  for (const o of TEXT_OVERLAYS) {
    if (progress >= o.threshold) active = o;
  }
  return active;
}

export default function ExplodingHouseScroll() {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const framesRef = useRef<HTMLImageElement[]>([]);
  const [useFallback, setUseFallback] = useState(false);
  const [framesLoaded, setFramesLoaded] = useState(false);
  const [currentOverlay, setCurrentOverlay] = useState(TEXT_OVERLAYS[0]);
  const progressRef = useRef(0);

  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ['start start', 'end end'],
  });

  // Load frames
  useEffect(() => {
    const firstFrame = new Image();
    firstFrame.onload = () => {
      // First frame loaded — proceed to load all
      const images: HTMLImageElement[] = [];
      let loaded = 0;

      for (let i = 1; i <= TOTAL_FRAMES; i++) {
        const img = new Image();
        img.src = FRAME_PATH(i);
        img.onload = () => {
          loaded++;
          if (loaded === TOTAL_FRAMES) {
            framesRef.current = images;
            setFramesLoaded(true);
          }
        };
        img.onerror = () => {
          loaded++;
          if (loaded === TOTAL_FRAMES) {
            framesRef.current = images;
            setFramesLoaded(true);
          }
        };
        images.push(img);
      }
    };
    firstFrame.onerror = () => {
      setUseFallback(true);
    };
    firstFrame.src = FRAME_PATH(1);
  }, []);

  // Draw frame on canvas
  useEffect(() => {
    if (!framesLoaded || useFallback) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const drawFrame = (index: number) => {
      const img = framesRef.current[index];
      if (!img || !img.complete) return;
      canvas.width = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
      const scale = Math.max(
        canvas.width / img.naturalWidth,
        canvas.height / img.naturalHeight
      );
      const w = img.naturalWidth * scale;
      const h = img.naturalHeight * scale;
      const x = (canvas.width - w) / 2;
      const y = (canvas.height - h) / 2;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, x, y, w, h);
    };

    const unsubscribe = scrollYProgress.on('change', (v) => {
      progressRef.current = v;
      const frameIndex = Math.min(
        Math.floor(v * TOTAL_FRAMES),
        TOTAL_FRAMES - 1
      );
      drawFrame(frameIndex);
      setCurrentOverlay(getOverlay(v));
    });

    // Draw first frame immediately
    drawFrame(0);

    return () => unsubscribe();
  }, [framesLoaded, useFallback, scrollYProgress]);

  // Sync fallback video with scroll
  useEffect(() => {
    if (!useFallback) return;
    const unsubscribe = scrollYProgress.on('change', (v) => {
      setCurrentOverlay(getOverlay(v));
    });
    return () => unsubscribe();
  }, [useFallback, scrollYProgress]);

  const overlayOpacity = useTransform(scrollYProgress, [0, 0.05, 0.9, 1], [0, 1, 1, 0]);

  return (
    <div ref={containerRef} className="relative" style={{ height: '300vh' }}>
      {/* Sticky viewport */}
      <div className="sticky top-0 min-h-[100dvh] overflow-hidden bg-[#0a0a0a]">
        {useFallback ? (
          <video
            ref={videoRef}
            className="absolute inset-0 w-full h-full object-cover"
            src="/assets/house_blast.mp4"
            autoPlay
            muted
            loop
            playsInline
            aria-hidden="true"
          />
        ) : (
          <canvas
            ref={canvasRef}
            className="absolute inset-0 w-full h-full"
            aria-hidden="true"
          />
        )}

        {/* Dark vignette */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              'radial-gradient(ellipse at center, transparent 40%, rgba(10,10,10,0.7) 100%)',
          }}
          aria-hidden="true"
        />

        {/* Text overlay */}
        <motion.div
          className="absolute inset-0 flex flex-col items-center justify-center z-10 px-6 text-center"
          style={{ opacity: overlayOpacity }}
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={currentOverlay.heading}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ type: 'spring', stiffness: 100, damping: 20 }}
              className="max-w-3xl"
            >
              <h2
                className="font-black text-white tracking-tight mb-4"
                style={{ fontSize: 'clamp(2rem, 5vw, 4rem)' }}
              >
                {currentOverlay.heading}
              </h2>
              <p className="text-white/70 text-lg md:text-xl font-light">
                {currentOverlay.sub}
              </p>
            </motion.div>
          </AnimatePresence>
        </motion.div>

        {/* Bottom gradient fade into next section */}
        <div
          className="absolute bottom-0 left-0 right-0 h-32 pointer-events-none"
          style={{
            background: 'linear-gradient(to bottom, transparent, #0a0a0a)',
          }}
          aria-hidden="true"
        />
      </div>
    </div>
  );
}
