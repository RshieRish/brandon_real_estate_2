'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChatCircleDots, X } from '@phosphor-icons/react';
import ChatPanel from './ChatPanel';

export default function ChatWidget() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div style={{ position: 'fixed', bottom: '24px', right: '24px', zIndex: 50 }}>
      <AnimatePresence>
        {isOpen && <ChatPanel onClose={() => setIsOpen(false)} />}
      </AnimatePresence>

      <motion.button
        onClick={() => setIsOpen(prev => !prev)}
        whileHover={{ scale: 1.08 }}
        whileTap={{ scale: 0.95 }}
        transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
        className="relative w-14 h-14 rounded-full bg-gold shadow-lg flex items-center justify-center"
        aria-label={isOpen ? 'Close chat' : 'Open chat'}
      >
        {/* Pulse ring — only when closed */}
        {!isOpen && (
          <motion.span
            className="absolute inset-0 rounded-full bg-gold/30"
            animate={{ scale: [1, 1.5], opacity: [0.6, 0] }}
            transition={{ duration: 1.5, repeat: Infinity, ease: 'easeOut' }}
          />
        )}

        <AnimatePresence mode="wait" initial={false}>
          {isOpen ? (
            <motion.span
              key="close"
              initial={{ opacity: 0, rotate: -90 }}
              animate={{ opacity: 1, rotate: 0 }}
              exit={{ opacity: 0, rotate: 90 }}
              transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
            >
              <X weight="bold" className="w-6 h-6 text-[#0a0a0a]" />
            </motion.span>
          ) : (
            <motion.span
              key="open"
              initial={{ opacity: 0, rotate: 90 }}
              animate={{ opacity: 1, rotate: 0 }}
              exit={{ opacity: 0, rotate: -90 }}
              transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
            >
              <ChatCircleDots weight="fill" className="w-6 h-6 text-[#0a0a0a]" />
            </motion.span>
          )}
        </AnimatePresence>
      </motion.button>
    </div>
  );
}
