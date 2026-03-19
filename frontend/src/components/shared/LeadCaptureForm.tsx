'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { apiPost } from '@/lib/api';

interface LeadPayload {
  name: string;
  email: string;
  phone?: string;
}

interface LeadResponse {
  id: number;
  name: string;
  email: string;
}

type FormState = 'idle' | 'loading' | 'success' | 'error';

const inputBase =
  'w-full bg-dark-card border border-dark-border rounded-none px-4 py-3 text-sm text-white placeholder-gray/50 focus:outline-none focus:border-gold transition-colors duration-200';

function SkeletonField() {
  return (
    <div className="h-12 bg-dark-card border border-dark-border rounded-none animate-pulse" />
  );
}

function CheckmarkIcon() {
  return (
    <motion.svg
      width="64"
      height="64"
      viewBox="0 0 64 64"
      fill="none"
      initial={{ scale: 0.5, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ type: 'spring', stiffness: 100, damping: 20, delay: 0.1 }}
    >
      <motion.circle
        cx="32"
        cy="32"
        r="30"
        stroke="#eac469"
        strokeWidth="2"
        fill="none"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
      />
      <motion.path
        d="M20 32l9 9 15-15"
        stroke="#eac469"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.4, ease: 'easeOut', delay: 0.4 }}
      />
    </motion.svg>
  );
}

export default function LeadCaptureForm({ className = '' }: { className?: string }) {
  const [formState, setFormState] = useState<FormState>('idle');
  const [error, setError] = useState('');
  const [fields, setFields] = useState({ name: '', email: '', phone: '' });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFields((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormState('loading');
    setError('');

    const payload: LeadPayload = {
      name: fields.name,
      email: fields.email,
      ...(fields.phone ? { phone: fields.phone } : {}),
    };

    try {
      await apiPost<LeadResponse>('/api/v1/leads/', payload);
      setFormState('success');
    } catch (err) {
      setFormState('error');
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    }
  };

  return (
    <div className={`w-full ${className}`}>
      <AnimatePresence mode="wait">
        {formState === 'success' ? (
          <motion.div
            key="success"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ type: 'spring', stiffness: 100, damping: 20 }}
            className="flex flex-col items-center gap-5 py-10 text-center"
          >
            <CheckmarkIcon />
            <div>
              <p className="text-gold font-bold text-lg tracking-wide">You&apos;re on the list.</p>
              <p className="text-gray text-sm mt-1">Brandon will be in touch shortly.</p>
            </div>
          </motion.div>
        ) : (
          <motion.form
            key="form"
            onSubmit={handleSubmit}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col gap-4"
            noValidate
          >
            {formState === 'loading' ? (
              <>
                <SkeletonField />
                <SkeletonField />
                <SkeletonField />
                <div className="h-12 bg-gold/20 rounded-none animate-pulse" />
              </>
            ) : (
              <>
                <div>
                  <label htmlFor="lead-name" className="sr-only">Full Name</label>
                  <input
                    id="lead-name"
                    name="name"
                    type="text"
                    required
                    placeholder="Full Name *"
                    value={fields.name}
                    onChange={handleChange}
                    className={inputBase}
                    autoComplete="name"
                  />
                </div>

                <div>
                  <label htmlFor="lead-email" className="sr-only">Email Address</label>
                  <input
                    id="lead-email"
                    name="email"
                    type="email"
                    required
                    placeholder="Email Address *"
                    value={fields.email}
                    onChange={handleChange}
                    className={inputBase}
                    autoComplete="email"
                  />
                </div>

                <div>
                  <label htmlFor="lead-phone" className="sr-only">Phone Number</label>
                  <input
                    id="lead-phone"
                    name="phone"
                    type="tel"
                    placeholder="Phone Number (optional)"
                    value={fields.phone}
                    onChange={handleChange}
                    className={inputBase}
                    autoComplete="tel"
                  />
                </div>

                {formState === 'error' && (
                  <motion.p
                    initial={{ opacity: 0, y: -6 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="text-xs text-red-400"
                  >
                    {error}
                  </motion.p>
                )}

                <motion.button
                  type="submit"
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  transition={{ type: 'spring', stiffness: 100, damping: 20 }}
                  className="w-full h-12 bg-gold text-black font-bold text-sm tracking-widest uppercase hover:bg-gold-hover transition-colors duration-200"
                  style={{ letterSpacing: '0.12em' }}
                >
                  Get Started
                </motion.button>
              </>
            )}
          </motion.form>
        )}
      </AnimatePresence>
    </div>
  );
}
