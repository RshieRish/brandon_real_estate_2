'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle, CircleNotch, Phone, WarningCircle } from '@phosphor-icons/react';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const spring = { type: 'spring' as const, stiffness: 100, damping: 20 };

interface FunnelRegistrationProps {
  slug: string;
  ctaText: string;
  ctaHeadline?: string;
  ctaSubtext?: string;
  audience: string;
}

export default function FunnelRegistration({
  slug,
  ctaText,
  ctaHeadline,
  ctaSubtext,
  audience,
}: FunnelRegistrationProps) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const audienceLabel =
    audience === 'buyer' || audience === 'buyers'
      ? 'For Buyers'
      : audience === 'seller' || audience === 'sellers'
        ? 'For Sellers'
        : audience === 'investor' || audience === 'investors'
          ? 'For Investors'
          : 'Register';

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
    } catch {
      setError('Something went wrong. Please try again or call (978) 987-2806.');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section className="relative py-24 md:py-32 px-6 md:px-12 bg-dark-card overflow-hidden">
      {/* Gold glow top */}
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-96 h-px"
        style={{ background: 'linear-gradient(90deg, transparent, rgba(234,196,105,0.6), transparent)' }}
        aria-hidden="true"
      />
      <HalftoneOverlay opacity={0.03} />

      <div className="relative z-10 max-w-7xl mx-auto">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-start">
          {/* Left — CTA copy */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ ...spring, delay: 0.1 }}
          >
            <span className="inline-block border border-gold/30 text-gold text-xs font-semibold tracking-widest uppercase px-3 py-1 mb-6">
              {audienceLabel}
            </span>
            <h2
              className="font-black text-white leading-tight tracking-tight mb-6"
              style={{ fontSize: 'clamp(1.75rem, 4.5vw, 3rem)' }}
            >
              {ctaHeadline ? (
                <>
                  {ctaHeadline.split(' ').slice(0, -1).join(' ')}{' '}
                  <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}>
                    {ctaHeadline.split(' ').slice(-1)}
                  </span>
                </>
              ) : (
                <>
                  Ready to{' '}
                  <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}>
                    {ctaText}
                  </span>
                  ?
                </>
              )}
            </h2>
            {ctaSubtext && (
              <p className="text-gray text-sm leading-relaxed mb-8 max-w-md">{ctaSubtext}</p>
            )}

            {/* Phone CTA */}
            <a
              href="tel:9789872806"
              className="inline-flex items-center gap-3 text-gold hover:text-white transition-colors duration-200 group"
            >
              <span className="w-10 h-10 flex items-center justify-center border border-gold/40 group-hover:border-gold/80 transition-colors duration-200">
                <Phone weight="bold" className="w-4 h-4" />
              </span>
              <div>
                <p className="text-xs text-gray uppercase tracking-widest font-medium">Call Direct</p>
                <p className="font-bold tracking-wide">(978) 987-2806</p>
              </div>
            </a>
          </motion.div>

          {/* Right — Form card */}
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...spring, delay: 0.25 }}
            className="bg-[#0a0a0a] border border-dark-border p-8"
          >
            <AnimatePresence mode="wait">
              {isSuccess ? (
                <motion.div
                  key="success"
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={spring}
                  className="text-center py-12"
                >
                  <div className="relative inline-block mb-6">
                    <CheckCircle weight="fill" className="w-20 h-20 text-gold" />
                    <div
                      className="absolute inset-0 rounded-full animate-pulse-gold"
                      aria-hidden="true"
                    />
                  </div>
                  <h3 className="text-white font-black text-2xl mb-2">You&apos;re In!</h3>
                  <p className="text-white/60 text-sm mb-8">
                    Brandon will be in touch with you shortly.
                  </p>
                  <a
                    href="tel:9789872806"
                    className="inline-flex items-center gap-2 bg-gold text-[#0a0a0a] px-8 py-3 font-bold text-sm tracking-widest uppercase hover:bg-gold-hover transition-colors"
                  >
                    <Phone weight="bold" className="w-4 h-4" />
                    Call Brandon Now
                  </a>
                </motion.div>
              ) : (
                <motion.form
                  key="form"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0, y: -10 }}
                  transition={{ duration: 0.25 }}
                  onSubmit={handleSubmit}
                >
                  {/* Error banner */}
                  {error && (
                    <motion.div
                      initial={{ opacity: 0, y: -8 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="bg-red-500/10 border border-red-500/20 text-red-400 p-3 text-sm mb-5 flex items-center gap-2"
                    >
                      <WarningCircle weight="fill" className="w-4 h-4 flex-shrink-0" />
                      {error}
                    </motion.div>
                  )}

                  {/* Name */}
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

                  {/* Email */}
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

                  {/* Phone */}
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

                  {/* Submit */}
                  <button
                    type="submit"
                    disabled={isLoading}
                    className="w-full bg-gold text-[#0a0a0a] font-bold text-sm tracking-widest uppercase px-6 py-4 hover:bg-gold-hover transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
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
          </motion.div>
        </div>
      </div>

      {/* KW Legal */}
      <p className="relative max-w-7xl mx-auto mt-16 text-gray/50 text-xs leading-relaxed border-t border-dark-border pt-6">
        Brandon Sweeney is a licensed REALTOR<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup> with Keller Williams Realty Success. All real
        estate services are subject to applicable state law and Keller Williams Realty
        International&apos;s policies. Equal Housing Opportunity. Information deemed reliable but
        not guaranteed.
      </p>
    </section>
  );
}
