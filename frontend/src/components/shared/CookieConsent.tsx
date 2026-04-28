'use client';

import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Cookie } from '@phosphor-icons/react';

export default function CookieConsent() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    // Check if user has already consented
    const consent = localStorage.getItem('cookie_consent');
    if (!consent) {
      // Small delay so it doesn't pop up immediately on first paint
      const timer = setTimeout(() => setShow(true), 1500);
      return () => clearTimeout(timer);
    }
  }, []);

  const handleAccept = () => {
    localStorage.setItem('cookie_consent', 'true');
    setShow(false);
  };

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0, y: 100 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 100 }}
          transition={{ type: 'spring', stiffness: 100, damping: 20 }}
          className="fixed bottom-6 left-0 right-0 z-50 px-4 flex justify-center pointer-events-none"
        >
          <div
            className="pointer-events-auto flex flex-col sm:flex-row items-center gap-4 sm:gap-6 bg-[#0a0a0a]/90 backdrop-blur-xl border border-gold/20 p-4 sm:px-6 sm:py-4 rounded-2xl shadow-2xl max-w-2xl w-full"
            style={{
              boxShadow: '0 0 0 1px rgba(234,196,105,0.04) inset, 0 32px 64px rgba(0,0,0,0.6)',
            }}
          >
            <div className="flex items-start gap-4">
              <div className="p-2 bg-gold/10 rounded-full shrink-0 mt-1 sm:mt-0">
                <Cookie weight="duotone" className="w-6 h-6 text-gold" />
              </div>
              <div className="text-left">
                <h3 className="text-white font-semibold text-sm mb-1">We value your privacy</h3>
                <p className="text-white/60 text-xs leading-relaxed max-w-md">
                  We use cookies to enhance your browsing experience, serve personalized content, and analyze our traffic. By clicking "Accept", you consent to our use of cookies.
                </p>
              </div>
            </div>
            <div className="w-full sm:w-auto shrink-0 flex gap-2">
              <button
                onClick={handleAccept}
                className="w-full sm:w-auto bg-gold hover:bg-gold-hover text-[#0a0a0a] font-bold text-xs uppercase tracking-wider px-6 py-3 transition-colors duration-200"
              >
                Accept
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
