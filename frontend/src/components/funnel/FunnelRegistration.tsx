'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle, CircleNotch, Phone, WarningCircle } from '@phosphor-icons/react';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface FunnelRegistrationProps {
  slug: string;
  ctaText: string;
  audience: string;
}

export default function FunnelRegistration({ slug, ctaText }: FunnelRegistrationProps) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_URL}/api/v1/funnels/${slug}/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, phone: phone || undefined }),
      });
      if (!res.ok) throw new Error('Registration failed');
      setIsSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section className="relative bg-dark-card py-24 md:py-32">
      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12 text-center">
        {/* Eyebrow */}
        <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
          Reserve Your Spot
        </p>

        {/* Section heading */}
        <h2
          className="font-black text-white leading-tight tracking-tight mb-8"
          style={{ fontSize: 'clamp(1.8rem, 3.5vw, 3rem)' }}
        >
          {ctaText ?? 'Register Now'}
        </h2>

        {/* Form card */}
        <div className="glass border border-dark-border p-8 max-w-md mx-auto mt-8">
          <AnimatePresence mode="wait">
            {isSuccess ? (
              <motion.div
                key="success"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4 }}
                className="text-center py-12"
              >
                <CheckCircle weight="fill" className="w-16 h-16 text-gold mx-auto mb-4" />
                <h3 className="text-white font-black text-2xl mb-2">You&apos;re registered!</h3>
                <p className="text-white/60 mb-6">Brandon will be in touch with you shortly.</p>
                <a
                  href="tel:9789872806"
                  className="inline-flex items-center gap-2 border border-gold text-gold px-6 py-3 font-semibold text-sm tracking-widest uppercase hover:bg-gold hover:text-[#0a0a0a] transition-colors"
                >
                  <Phone weight="bold" className="w-4 h-4" />
                  Call Brandon Now
                </a>
              </motion.div>
            ) : (
              <motion.form
                key="form"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.3 }}
                onSubmit={handleSubmit}
              >
                {/* Error banner */}
                {error && (
                  <div className="bg-red-500/10 border border-red-500/20 text-red-400 p-3 text-sm mb-4 flex items-center gap-2">
                    <WarningCircle weight="fill" className="w-4 h-4 flex-shrink-0" />
                    {error}
                  </div>
                )}

                {/* Name field */}
                <div className="mb-4">
                  <label
                    htmlFor="funnel-name"
                    className="block text-white/60 text-xs font-semibold tracking-widest uppercase mb-2"
                  >
                    Full Name
                  </label>
                  <input
                    id="funnel-name"
                    type="text"
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Jane Smith"
                    className="w-full bg-dark-surface border border-dark-border text-white px-4 py-3 focus:outline-none focus:border-gold/60 transition-colors placeholder:text-white/20"
                  />
                </div>

                {/* Email field */}
                <div className="mb-4">
                  <label
                    htmlFor="funnel-email"
                    className="block text-white/60 text-xs font-semibold tracking-widest uppercase mb-2"
                  >
                    Email Address
                  </label>
                  <input
                    id="funnel-email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="jane@example.com"
                    className="w-full bg-dark-surface border border-dark-border text-white px-4 py-3 focus:outline-none focus:border-gold/60 transition-colors placeholder:text-white/20"
                  />
                </div>

                {/* Phone field */}
                <div className="mb-6">
                  <label
                    htmlFor="funnel-phone"
                    className="block text-white/60 text-xs font-semibold tracking-widest uppercase mb-2"
                  >
                    Phone{' '}
                    <span className="text-white/30 normal-case tracking-normal font-normal">(optional)</span>
                  </label>
                  <input
                    id="funnel-phone"
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="(978) 000-0000"
                    className="w-full bg-dark-surface border border-dark-border text-white px-4 py-3 focus:outline-none focus:border-gold/60 transition-colors placeholder:text-white/20"
                  />
                </div>

                {/* Submit button */}
                <button
                  type="submit"
                  disabled={isLoading}
                  className="w-full bg-gold text-[#0a0a0a] font-bold text-sm tracking-widest uppercase px-6 py-4 hover:bg-gold/90 transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  {isLoading ? (
                    <>
                      <CircleNotch className="w-4 h-4 animate-spin" />
                      Submitting...
                    </>
                  ) : (
                    ctaText ?? 'Register Now'
                  )}
                </button>
              </motion.form>
            )}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}
