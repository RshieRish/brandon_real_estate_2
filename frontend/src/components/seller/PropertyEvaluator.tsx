'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowRight,
  SpinnerGap,
  CheckCircle,
  Warning,
  Phone,
  ArrowCounterClockwise,
} from '@phosphor-icons/react';
import { apiPost } from '@/lib/api';
import CTAButton from '@/components/shared/CTAButton';

// ─── Types ────────────────────────────────────────────────────────────────────

type PropertyType = 'single_family' | 'multi_family' | 'condo' | 'townhouse';
type Condition = 'excellent' | 'good' | 'fair' | 'needs_work';
type FormState = 'form' | 'loading' | 'result';
type EvaluatorRating = 'expected' | 'under' | 'above';

interface EvaluatorForm {
  address: string;
  property_type: PropertyType | '';
  bedrooms: string;
  bathrooms: string;
  sqft: string;
  year_built: string;
  condition: Condition | '';
  upgrades: string[];
  name: string;
  email: string;
  phone: string;
}

interface EvaluatorResult {
  calculation_id: number;
  address: string;
  price_low: number;
  price_high: number;
  confidence: 'High' | 'Medium' | 'Low';
  explanation: string;
  key_factors: string[];
  disclaimer: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const PROPERTY_TYPES: { value: PropertyType; label: string }[] = [
  { value: 'single_family', label: 'Single Family' },
  { value: 'multi_family', label: 'Multi Family' },
  { value: 'condo', label: 'Condo' },
  { value: 'townhouse', label: 'Townhouse' },
];

const CONDITIONS: { value: Condition; label: string }[] = [
  { value: 'excellent', label: 'Excellent' },
  { value: 'good', label: 'Good' },
  { value: 'fair', label: 'Fair' },
  { value: 'needs_work', label: 'Needs Work' },
];

const UPGRADE_OPTIONS = [
  'Kitchen remodel',
  'Bathrooms',
  'Roof',
  'HVAC',
  'Windows',
  'Flooring',
  'Addition',
];

const RATING_OPTIONS: { value: EvaluatorRating; label: string }[] = [
  { value: 'expected', label: 'This is what I expected to get' },
  { value: 'under', label: 'This is under what I expected to get' },
  { value: 'above', label: 'This is more than what I expected to get' },
];

const CONFIDENCE_CONFIG: Record<
  'High' | 'Medium' | 'Low',
  { color: string; bg: string; border: string }
> = {
  High: { color: 'text-emerald-400', bg: 'bg-emerald-400/10', border: 'border-emerald-400/30' },
  Medium: { color: 'text-yellow-400', bg: 'bg-yellow-400/10', border: 'border-yellow-400/30' },
  Low: { color: 'text-red-400', bg: 'bg-red-400/10', border: 'border-red-400/30' },
};

const INITIAL_FORM: EvaluatorForm = {
  address: '',
  property_type: '',
  bedrooms: '3',
  bathrooms: '2',
  sqft: '',
  year_built: '',
  condition: '',
  upgrades: [],
  name: '',
  email: '',
  phone: '',
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatCurrency(n: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function InputField({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-semibold text-white/60 uppercase tracking-widest">
        {label}
        {required && <span className="text-gold ml-1">*</span>}
      </label>
      {children}
    </div>
  );
}

const inputClass =
  'w-full bg-dark-surface border border-dark-border text-white text-sm px-4 py-3 focus:outline-none focus:border-gold/50 transition-colors placeholder:text-white/20 font-light';

const selectClass =
  'w-full bg-dark-surface border border-dark-border text-white text-sm px-4 py-3 focus:outline-none focus:border-gold/50 transition-colors appearance-none cursor-pointer';

// ─── Main Component ───────────────────────────────────────────────────────────

export default function PropertyEvaluator() {
  const [formState, setFormState] = useState<FormState>('form');
  const [form, setForm] = useState<EvaluatorForm>(INITIAL_FORM);
  const [result, setResult] = useState<EvaluatorResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rating, setRating] = useState<EvaluatorRating | null>(null);
  const [ratingSubmitted, setRatingSubmitted] = useState(false);
  const [ratingSubmitting, setRatingSubmitting] = useState(false);
  const [ratingError, setRatingError] = useState<string | null>(null);

  function setField<K extends keyof EvaluatorForm>(key: K, value: EvaluatorForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function toggleUpgrade(upgrade: string) {
    setForm((prev) => ({
      ...prev,
      upgrades: prev.upgrades.includes(upgrade)
        ? prev.upgrades.filter((u) => u !== upgrade)
        : [...prev.upgrades, upgrade],
    }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.address || !form.property_type || !form.condition) return;

    setFormState('loading');
    setError(null);

    try {
      const payload = {
        address: form.address,
        property_type: form.property_type,
        bedrooms: parseInt(form.bedrooms, 10),
        bathrooms: parseFloat(form.bathrooms),
        sqft: form.sqft ? parseInt(form.sqft, 10) : undefined,
        year_built: form.year_built ? parseInt(form.year_built, 10) : undefined,
        condition: form.condition,
        upgrades: form.upgrades,
        name: form.name || undefined,
        email: form.email || undefined,
        phone: form.phone || undefined,
      };

      const data = await apiPost<EvaluatorResult>('/api/v1/evaluator/', payload);
      setResult(data);
      setRating(null);
      setRatingSubmitted(false);
      setRatingError(null);
      setFormState('result');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
      setFormState('form');
    }
  }

  async function handleRatingSubmit(nextRating: EvaluatorRating) {
    if (!result?.calculation_id || ratingSubmitting || ratingSubmitted) return;

    setRating(nextRating);
    setRatingSubmitting(true);
    setRatingError(null);

    try {
      await apiPost(`/api/v1/evaluator/${result.calculation_id}/rating`, {
        rating: nextRating,
      });
      setRatingSubmitted(true);
    } catch (err) {
      setRatingError(err instanceof Error ? err.message : 'Could not save your feedback.');
    } finally {
      setRatingSubmitting(false);
    }
  }

  function handleReset() {
    setForm(INITIAL_FORM);
    setResult(null);
    setError(null);
    setRating(null);
    setRatingSubmitted(false);
    setRatingSubmitting(false);
    setRatingError(null);
    setFormState('form');
  }

  return (
    <div className="relative">
      <AnimatePresence mode="wait">
        {/* ── FORM ── */}
        {formState === 'form' && (
          <motion.form
            key="form"
            onSubmit={handleSubmit}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ type: 'spring', stiffness: 100, damping: 20 }}
            className="space-y-8"
          >
            {/* Error banner */}
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 px-4 py-3 text-red-400 text-sm"
              >
                <Warning weight="fill" className="w-4 h-4 flex-shrink-0" />
                {error}
              </motion.div>
            )}

            {/* Property details */}
            <div>
              <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-5">
                Property Details
              </p>
              <div className="grid grid-cols-1 gap-4">
                <InputField label="Property Address" required>
                  <input
                    type="text"
                    value={form.address}
                    onChange={(e) => setField('address', e.target.value)}
                    placeholder="123 Main St, Nashua, NH 03060"
                    required
                    className={inputClass}
                  />
                </InputField>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <InputField label="Property Type" required>
                    <select
                      value={form.property_type}
                      onChange={(e) => setField('property_type', e.target.value as PropertyType)}
                      required
                      className={selectClass}
                    >
                      <option value="" disabled>Select type…</option>
                      {PROPERTY_TYPES.map((pt) => (
                        <option key={pt.value} value={pt.value}>{pt.label}</option>
                      ))}
                    </select>
                  </InputField>

                  <InputField label="Square Feet">
                    <input
                      type="text"
                      inputMode="numeric"
                      value={form.sqft ? form.sqft.replace(/\B(?=(\d{3})+(?!\d))/g, ',') : ''}
                      onChange={(e) => setField('sqft', e.target.value.replace(/[^0-9]/g, ''))}
                      placeholder="e.g. 1,850"
                      className={inputClass}
                    />
                  </InputField>
                </div>

                <div className="grid grid-cols-3 gap-4">
                  <InputField label="Bedrooms" required>
                    <input
                      type="number"
                      min={1}
                      max={10}
                      value={form.bedrooms}
                      onChange={(e) => setField('bedrooms', e.target.value)}
                      required
                      className={inputClass}
                    />
                  </InputField>

                  <InputField label="Bathrooms" required>
                    <input
                      type="number"
                      min={1}
                      max={10}
                      step={0.5}
                      value={form.bathrooms}
                      onChange={(e) => setField('bathrooms', e.target.value)}
                      required
                      className={inputClass}
                    />
                  </InputField>

                  <InputField label="Year Built">
                    <input
                      type="text"
                      value={form.year_built}
                      onChange={(e) => setField('year_built', e.target.value)}
                      placeholder="e.g. 1998"
                      className={inputClass}
                    />
                  </InputField>
                </div>
              </div>
            </div>

            {/* Condition */}
            <div>
              <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
                Overall Condition <span className="text-gold">*</span>
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {CONDITIONS.map((c) => {
                  const selected = form.condition === c.value;
                  return (
                    <motion.button
                      key={c.value}
                      type="button"
                      onClick={() => setField('condition', c.value)}
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      transition={{ type: 'spring', stiffness: 100, damping: 20 }}
                      className={`px-4 py-3 text-sm font-semibold tracking-wide border transition-colors ${
                        selected
                          ? 'bg-gold text-[#0a0a0a] border-gold'
                          : 'bg-dark-surface border-dark-border text-white/60 hover:border-gold/40 hover:text-white'
                      }`}
                    >
                      {c.label}
                    </motion.button>
                  );
                })}
              </div>
            </div>

            {/* Upgrades */}
            <div>
              <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
                Recent Upgrades
              </p>
              <div className="flex flex-wrap gap-2">
                {UPGRADE_OPTIONS.map((upgrade) => {
                  const selected = form.upgrades.includes(upgrade);
                  return (
                    <motion.button
                      key={upgrade}
                      type="button"
                      onClick={() => toggleUpgrade(upgrade)}
                      whileHover={{ scale: 1.03 }}
                      whileTap={{ scale: 0.97 }}
                      transition={{ type: 'spring', stiffness: 100, damping: 20 }}
                      className={`px-4 py-2 text-xs font-semibold tracking-widest uppercase border transition-colors ${
                        selected
                          ? 'bg-gold/15 border-gold text-gold'
                          : 'bg-transparent border-dark-border text-white/50 hover:border-gold/40 hover:text-white/80'
                      }`}
                    >
                      {selected && <CheckCircle weight="fill" className="inline w-3 h-3 mr-1.5" />}
                      {upgrade}
                    </motion.button>
                  );
                })}
              </div>
            </div>

            {/* Contact (optional) */}
            <div>
              <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-2">
                Receive Results by Email
              </p>
              <p className="text-white/40 text-xs font-light mb-4">Optional — leave blank to see results instantly below.</p>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <InputField label="Name">
                  <input
                    type="text"
                    value={form.name}
                    onChange={(e) => setField('name', e.target.value)}
                    placeholder="Your name"
                    className={inputClass}
                  />
                </InputField>
                <InputField label="Email">
                  <input
                    type="email"
                    value={form.email}
                    onChange={(e) => setField('email', e.target.value)}
                    placeholder="you@email.com"
                    className={inputClass}
                  />
                </InputField>
                <InputField label="Phone">
                  <input
                    type="tel"
                    value={form.phone}
                    onChange={(e) => setField('phone', e.target.value)}
                    placeholder="(978) 000-0000"
                    className={inputClass}
                  />
                </InputField>
              </div>
            </div>

            {/* Submit */}
            <div className="pt-2">
              <CTAButton type="submit" variant="gold" className="w-full sm:w-auto justify-center">
                Get My Free Estimate
                <ArrowRight weight="bold" className="w-4 h-4" />
              </CTAButton>
            </div>
          </motion.form>
        )}

        {/* ── LOADING ── */}
        {formState === 'loading' && (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ type: 'spring', stiffness: 100, damping: 20 }}
            className="flex flex-col items-center justify-center py-24 gap-6"
          >
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ repeat: Infinity, duration: 1, ease: 'linear' }}
            >
              <SpinnerGap weight="bold" className="w-12 h-12 text-gold" />
            </motion.div>
            <p className="text-white/60 text-sm font-light tracking-widest uppercase">
              Analyzing your property&hellip;
            </p>
          </motion.div>
        )}

        {/* ── RESULT ── */}
        {formState === 'result' && result && (
          <motion.div
            key="result"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -24 }}
            transition={{ type: 'spring', stiffness: 100, damping: 20 }}
            className="space-y-6"
          >
            {/* Address */}
            <div>
              <p className="text-white/40 text-xs uppercase tracking-widest font-medium">Estimated value for</p>
              <p className="text-white font-semibold text-base mt-1">{result.address}</p>
            </div>

            {/* Price range + confidence */}
            <div className="flex flex-wrap items-center gap-4">
              <p
                className="font-black text-gold leading-none"
                style={{ fontSize: 'clamp(1.8rem, 4vw, 3rem)', textShadow: '0 0 30px rgba(234,196,105,0.3)' }}
              >
                {formatCurrency(result.price_low)}&nbsp;&ndash;&nbsp;{formatCurrency(result.price_high)}
              </p>
              <span
                className={`text-xs font-bold tracking-widest uppercase px-3 py-1.5 border ${
                  CONFIDENCE_CONFIG[result.confidence].color
                } ${CONFIDENCE_CONFIG[result.confidence].bg} ${CONFIDENCE_CONFIG[result.confidence].border}`}
              >
                {result.confidence} Confidence
              </span>
            </div>

            {/* Explanation */}
            <p className="text-white/70 text-sm leading-relaxed font-light">{result.explanation}</p>

            {/* Key factors */}
            {result.key_factors?.length > 0 && (
              <div>
                <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-3">Key Factors</p>
                <ul className="space-y-2">
                  {result.key_factors.map((factor, i) => (
                    <li key={i} className="flex items-start gap-3 text-sm text-white/70 font-light">
                      <span className="text-gold font-bold flex-shrink-0 mt-0.5">&rarr;</span>
                      {factor}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Disclaimer */}
            {result.disclaimer && (
              <p className="text-white/30 text-xs italic leading-relaxed">{result.disclaimer}</p>
            )}

            {result.calculation_id > 0 && (
              <div className="glass border border-dark-border rounded-xl p-5 space-y-4">
                <div>
                  <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-2">
                    How Did This Compare To Your Expectation?
                  </p>
                  <p className="text-white/55 text-sm font-light">
                    This helps Brandon calibrate the valuation experience over time.
                  </p>
                </div>

                <div className="grid grid-cols-1 gap-3">
                  {RATING_OPTIONS.map((option) => {
                    const selected = rating === option.value;
                    return (
                      <motion.button
                        key={option.value}
                        type="button"
                        onClick={() => handleRatingSubmit(option.value)}
                        whileHover={ratingSubmitted ? undefined : { scale: 1.01 }}
                        whileTap={ratingSubmitted ? undefined : { scale: 0.99 }}
                        transition={{ type: 'spring', stiffness: 100, damping: 20 }}
                        disabled={ratingSubmitting || ratingSubmitted}
                        className={`w-full border px-4 py-3 text-left text-sm transition-colors ${
                          selected || ratingSubmitted
                            ? 'border-gold bg-gold/10 text-white'
                            : 'border-dark-border bg-dark-surface text-white/60 hover:border-gold/40 hover:text-white'
                        } disabled:cursor-not-allowed disabled:opacity-80`}
                      >
                        {option.label}
                      </motion.button>
                    );
                  })}
                </div>

                {ratingSubmitted && (
                  <p className="text-gold text-xs font-semibold tracking-widest uppercase">
                    Feedback saved
                  </p>
                )}

                {ratingError && (
                  <p className="text-red-400 text-xs">{ratingError}</p>
                )}
              </div>
            )}

            {/* CTAs */}
            <div className="flex flex-wrap gap-4 pt-2">
              <CTAButton href="tel:9789872806" external variant="gold">
                <Phone weight="fill" className="w-4 h-4" />
                Book Brandon for a Free Valuation
              </CTAButton>
              <CTAButton onClick={handleReset} variant="outline">
                <ArrowCounterClockwise weight="bold" className="w-4 h-4" />
                Run Another Estimate
              </CTAButton>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
