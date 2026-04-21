'use client';

import { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { Robot, X, PaperPlaneTilt, CalendarBlank } from '@phosphor-icons/react';
import { useRouter } from 'next/navigation';
import { useChat, type ChatAction } from '@/hooks/useChat';
import { useState } from 'react';
import CalendarPickerCard from './CalendarPickerCard';

interface ChatPanelProps {
  onClose: () => void;
  bookingRequestId?: number;
}

const QUICK_REPLIES = [
  'What can I afford in MA?',
  'How do I sell fast?',
  'Is now a good time to invest?',
];

const DIRECT_BOOKING_MESSAGE =
  'How would you like to meet Brandon? Choose phone call, Google Meet, or in person to keep booking.';

export default function ChatPanel({ onClose, bookingRequestId = 0 }: ChatPanelProps) {
  const { messages, isLoading, error, sendMessage, triggerBooking, addMessage } = useChat();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const handledBookingRequestRef = useRef(0);
  const router = useRouter();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    if (!bookingRequestId || handledBookingRequestRef.current === bookingRequestId) return;

    handledBookingRequestRef.current = bookingRequestId;
    triggerBooking(DIRECT_BOOKING_MESSAGE, 'guided');
  }, [bookingRequestId, triggerBooking]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;
    setInput('');
    sendMessage(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleBookingComplete = (summary: string) => {
    addMessage('assistant', summary);
  };

  const handleActionClick = (action: ChatAction) => {
    if (isLoading) return;

    if (action.type === 'send_message') {
      sendMessage(action.message ?? action.label);
      return;
    }

    if (action.type === 'navigate' && action.href) {
      router.push(action.href);
      onClose();
      return;
    }

    if (action.type === 'open_widget' && action.widget === 'calendar_picker') {
      triggerBooking(DIRECT_BOOKING_MESSAGE, 'guided');
    }
  };

  const getActionEyebrow = (action: ChatAction) => {
    if (action.type === 'navigate') return 'Explore';
    if (action.type === 'open_widget') return 'Schedule';
    return 'Continue';
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 20, scale: 0.95 }}
      transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
      className="glass border border-dark-border rounded-xl flex flex-col overflow-hidden"
      style={{
        position: 'fixed',
        bottom: '96px',
        right: '24px',
        width: '380px',
        height: '520px',
        zIndex: 50,
      }}
    >
      {/* Header */}
      <div className="bg-[#0a0a0a] border-b border-dark-border px-4 py-3 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <Robot weight="fill" className="w-5 h-5 text-gold" />
          <div>
            <p className="text-white text-sm font-semibold leading-none">Ask Brandon&apos;s AI</p>
            <p className="text-white/40 text-xs mt-0.5">Powered by Gemini</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-white/60 hover:text-white transition-colors p-1 rounded"
          aria-label="Close chat"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <Robot weight="fill" className="w-10 h-10 text-gold" />
            <p className="text-white font-semibold text-sm">Hi! I&apos;m Brandon&apos;s AI assistant.</p>
            <p className="text-white/50 text-xs leading-relaxed px-2">
              Ask me anything about buying, selling, or investing in MA/NH real estate.
            </p>
            {/* Quick reply chips */}
            <div className="flex flex-col gap-2 mt-2 w-full">
              {QUICK_REPLIES.map(reply => (
                <button
                  key={reply}
                  onClick={() => { if (!isLoading) sendMessage(reply); }}
                  disabled={isLoading}
                  className="text-xs text-white/60 border border-dark-border rounded-full px-3 py-1.5 hover:border-gold/50 hover:text-white/80 transition-colors text-left disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {reply}
                </button>
              ))}
              {/* Book a Call quick action */}
              <button
                onClick={() => triggerBooking(DIRECT_BOOKING_MESSAGE, 'guided')}
                className="text-xs text-gold border border-gold/30 rounded-full px-3 py-1.5 hover:border-gold/60 hover:bg-gold/5 transition-colors text-left flex items-center gap-1.5"
              >
                <CalendarBlank weight="fill" className="w-3 h-3" />
                Book time with Brandon
              </button>
            </div>
          </div>
        ) : (
          <>
            {messages.map(msg => (
              <div key={msg.id}>
                <div className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[80%] rounded-xl px-3 py-2 text-sm ${
                      msg.role === 'user'
                        ? 'bg-gold text-[#0a0a0a] font-medium'
                        : 'bg-dark-card border border-dark-border text-white/80'
                    }`}
                    style={{ whiteSpace: 'pre-wrap' }}
                  >
                    {msg.content}
                  </div>
                </div>
                {msg.role === 'assistant' && msg.actions && msg.actions.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
                    className="mt-2 flex max-w-[88%] flex-wrap gap-2"
                  >
                    {msg.actions.map((action, index) => (
                      <motion.button
                        key={`${msg.id}-${action.type}-${action.label}-${index}`}
                        whileHover={{ y: -2 }}
                        whileTap={{ scale: 0.98 }}
                        transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
                        onClick={() => handleActionClick(action)}
                        disabled={isLoading}
                        className="group relative min-w-[140px] flex-1 overflow-hidden rounded-2xl border border-gold/20 bg-[linear-gradient(135deg,rgba(234,196,105,0.16),rgba(255,255,255,0.03))] px-3 py-2.5 text-left shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] transition-all duration-300 hover:border-gold/50 hover:bg-[linear-gradient(135deg,rgba(234,196,105,0.24),rgba(255,255,255,0.06))] disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <span className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.14),transparent_48%)] opacity-80" />
                        <span className="relative block text-[9px] uppercase tracking-[0.24em] text-gold/60">
                          {getActionEyebrow(action)}
                        </span>
                        <span className="relative mt-1 block text-sm font-medium leading-snug text-white/90 group-hover:text-white">
                          {action.label}
                        </span>
                      </motion.button>
                    ))}
                  </motion.div>
                )}
                {/* Render CalendarPickerCard inline after the message */}
                {msg.widget === 'calendar_picker' && (
                  <div className="mt-2">
                    <CalendarPickerCard
                      onBooked={handleBookingComplete}
                      initialMode={msg.widgetMode ?? 'next_available'}
                    />
                  </div>
                )}
              </div>
            ))}

            {/* Typing indicator */}
            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-dark-card border border-dark-border rounded-xl px-4 py-3 flex gap-1 items-center">
                  {[0, 1, 2].map(i => (
                    <motion.span
                      key={i}
                      className="w-1.5 h-1.5 rounded-full bg-white/50 block"
                      animate={{ opacity: [0.3, 1, 0.3] }}
                      transition={{
                        duration: 1,
                        repeat: Infinity,
                        delay: i * 0.2,
                        ease: 'easeInOut',
                      }}
                    />
                  ))}
                </div>
              </div>
            )}
          </>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Error banner */}
      {error && (
        <div className="bg-red-500/10 border-t border-red-500/20 px-4 py-2 flex-shrink-0">
          <p className="text-red-400 text-xs">{error}</p>
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-dark-border p-3 flex gap-2 flex-shrink-0">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question..."
          className="flex-1 bg-[#111111] border border-dark-border rounded-lg px-3 py-2 text-sm text-white placeholder-white/30 focus:outline-none focus:ring-1 focus:ring-gold/60 transition-all"
        />
        <button
          onClick={handleSend}
          disabled={!input.trim() || isLoading}
          className="bg-gold rounded-lg px-3 py-2 flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gold/90 transition-colors flex-shrink-0"
          aria-label="Send message"
        >
          <PaperPlaneTilt weight="fill" className="w-4 h-4 text-[#0a0a0a]" />
        </button>
      </div>
    </motion.div>
  );
}
