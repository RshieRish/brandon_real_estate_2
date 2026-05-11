'use client';

import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, CheckCircle, SpinnerGap, Warning, House } from '@phosphor-icons/react';
import { apiPost } from '@/lib/api';
import {
  AMENITY_OPTIONS,
  CONDITION_OPTIONS,
  MARKET_OPTIONS,
  PROPERTY_TYPE_OPTIONS,
  UPGRADE_OPTIONS,
  type Amenity,
  type EstimateRentPayload,
  type EstimateRentResponse,
  type PropertyType,
  type RentCondition,
  type RentMode,
  type StrMarketType,
} from '@/lib/rental-analyzer-types';

interface RentalAnalyzerModalProps {
  open: boolean;
  onClose: () => void;
  mode: RentMode; // ltr or str (caller decides based on strategy)
  prefill?: {
    address?: string;
    property_type?: string;
    bedrooms?: number;
    bathrooms?: number;
    sqft?: number;
    year_built?: number;
    purchase_price?: number;
  };
  onApply: (median: number) => void; // writes the median into the calculator field
}

const fmt = (value: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);

const CONFIDENCE_COLOR: Record<'High' | 'Medium' | 'Low', string> = {
  High: 'text-emerald-400',
  Medium: 'text-yellow-400',
  Low: 'text-red-400',
};

export default function RentalAnalyzerModal({
  open, onClose, mode, prefill, onApply,
}: RentalAnalyzerModalProps) {
  const [address, setAddress] = useState(prefill?.address ?? '');
  const [bedrooms, setBedrooms] = useState<string>(prefill?.bedrooms?.toString() ?? '');
  const [bathrooms, setBathrooms] = useState<string>(prefill?.bathrooms?.toString() ?? '');
  const [sqft, setSqft] = useState<string>(prefill?.sqft?.toString() ?? '');
  const [yearBuilt, setYearBuilt] = useState<string>(prefill?.year_built?.toString() ?? '');
  const [propertyType, setPropertyType] = useState<PropertyType | ''>('');
  const [condition, setCondition] = useState<RentCondition | ''>('');
  const [upgrades, setUpgrades] = useState<string[]>([]);
  const [amenities, setAmenities] = useState<Amenity[]>([]);
  const [market, setMarket] = useState<StrMarketType | ''>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EstimateRentResponse | null>(null);

  const addressInputRef = useRef<HTMLInputElement>(null);
  const prevOpenRef = useRef(false);

  // ESC to close + auto-focus address input on open
  useEffect(() => {
    if (!open) return undefined;
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEsc);
    // Auto-focus the first input after a tick (lets the open transition land first)
    const timeout = setTimeout(() => addressInputRef.current?.focus(), 100);
    return () => {
      window.removeEventListener('keydown', handleEsc);
      clearTimeout(timeout);
    };
  }, [open, onClose]);

  // Reset when reopened (only on false → true transition)
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      // Modal just opened — apply prefill
      setAddress(prefill?.address ?? '');
      setBedrooms(prefill?.bedrooms?.toString() ?? '');
      setBathrooms(prefill?.bathrooms?.toString() ?? '');
      setSqft(prefill?.sqft?.toString() ?? '');
      setYearBuilt(prefill?.year_built?.toString() ?? '');
      setPropertyType('');
      setAmenities([]);
      setResult(null);
      setError(null);
    }
    prevOpenRef.current = open;
  }, [open, prefill]);

  function toggleUpgrade(u: string) {
    setUpgrades((prev) => (prev.includes(u) ? prev.filter((x) => x !== u) : [...prev, u]));
  }

  function toggleAmenity(a: Amenity) {
    setAmenities((prev) => (prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a]));
  }

  async function handleAnalyze() {
    if (!address.trim() || !condition || !propertyType) return;
    if (mode === 'str' && !market) return;

    setLoading(true);
    setError(null);
    setResult(null);

    const payload: EstimateRentPayload = {
      address: address.trim(),
      property_type: propertyType,
      bedrooms: bedrooms ? Number(bedrooms) : undefined,
      bathrooms: bathrooms ? Number(bathrooms) : undefined,
      sqft: sqft ? Number(sqft) : undefined,
      year_built: yearBuilt ? Number(yearBuilt) : undefined,
      condition,
      upgrades,
      amenities,
      mode,
      market_type: mode === 'str' ? (market as StrMarketType) : undefined,
      purchase_price: prefill?.purchase_price,
    };

    try {
      const data = await apiPost<EstimateRentResponse>('/api/v1/investor/estimate-rent', payload);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not estimate rent.');
    } finally {
      setLoading(false);
    }
  }

  function handleApply() {
    if (!result) return;
    const value = mode === 'str' ? (result.nightly_median ?? 0) : result.monthly_median;
    onApply(value);
    onClose();
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.98 }}
            transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
            onClick={(e) => e.stopPropagation()}
            className="glass border border-dark-border rounded-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto p-6 md:p-8"
          >
            <div className="flex items-start justify-between mb-6">
              <div>
                <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-1">
                  Rental Analyzer
                </p>
                <h2 className="text-white font-black text-xl tracking-tight">
                  Estimate {mode === 'str' ? 'Nightly Rate' : 'Monthly Rent'}
                </h2>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="text-white/40 hover:text-white transition-colors"
              >
                <X weight="bold" className="w-5 h-5" />
              </button>
            </div>

            {/* Inputs */}
            <div className="space-y-5">
              <div>
                <label className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-1.5 block">
                  Address
                </label>
                <input
                  ref={addressInputRef}
                  type="text"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder="123 Main St, Boston, MA"
                  className="w-full bg-dark-surface border border-dark-border text-white text-sm px-4 py-2.5 focus:outline-none focus:border-gold transition-colors"
                />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <input type="number" inputMode="numeric" min={0} placeholder="Beds" value={bedrooms} onChange={(e) => setBedrooms(e.target.value)}
                  className="bg-dark-surface border border-dark-border text-white text-sm px-3 py-2.5 focus:outline-none focus:border-gold" />
                <input type="number" inputMode="numeric" min={0} step={0.5} placeholder="Baths" value={bathrooms} onChange={(e) => setBathrooms(e.target.value)}
                  className="bg-dark-surface border border-dark-border text-white text-sm px-3 py-2.5 focus:outline-none focus:border-gold" />
                <input type="number" inputMode="numeric" min={0} placeholder="Sqft" value={sqft} onChange={(e) => setSqft(e.target.value)}
                  className="bg-dark-surface border border-dark-border text-white text-sm px-3 py-2.5 focus:outline-none focus:border-gold" />
                <input type="number" inputMode="numeric" min={1800} max={2030} placeholder="Year" value={yearBuilt} onChange={(e) => setYearBuilt(e.target.value)}
                  className="bg-dark-surface border border-dark-border text-white text-sm px-3 py-2.5 focus:outline-none focus:border-gold" />
              </div>

              <div>
                <p className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-2">
                  Property Type <span className="text-gold">*</span>
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2" role="radiogroup" aria-label="Property Type">
                  {PROPERTY_TYPE_OPTIONS.map((opt) => {
                    const selected = propertyType === opt.value;
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        onClick={() => setPropertyType(opt.value)}
                        className={`px-3 py-2.5 text-xs font-semibold tracking-wide border transition-colors ${
                          selected
                            ? 'bg-gold text-[#0a0a0a] border-gold'
                            : 'bg-dark-surface border-dark-border text-white/60 hover:border-gold/40 hover:text-white'
                        }`}
                      >
                        {opt.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <p className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-2">
                  Condition <span className="text-gold">*</span>
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {CONDITION_OPTIONS.map((c) => {
                    const selected = condition === c.value;
                    return (
                      <button
                        key={c.value}
                        type="button"
                        onClick={() => setCondition(c.value)}
                        className={`px-3 py-2.5 text-xs font-semibold tracking-wide border transition-colors ${
                          selected
                            ? 'bg-gold text-[#0a0a0a] border-gold'
                            : 'bg-dark-surface border-dark-border text-white/60 hover:border-gold/40 hover:text-white'
                        }`}
                      >
                        {c.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <p className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-2">
                  Recent Upgrades
                </p>
                <div className="flex flex-wrap gap-2">
                  {UPGRADE_OPTIONS.map((u) => {
                    const selected = upgrades.includes(u);
                    return (
                      <button
                        key={u}
                        type="button"
                        onClick={() => toggleUpgrade(u)}
                        className={`px-3 py-1.5 text-xs font-semibold tracking-widest uppercase border transition-colors ${
                          selected
                            ? 'bg-gold/15 border-gold text-gold'
                            : 'bg-transparent border-dark-border text-white/50 hover:border-gold/40'
                        }`}
                      >
                        {selected && <CheckCircle weight="fill" className="inline w-3 h-3 mr-1" />}
                        {u}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <p className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-2">
                  Amenities
                </p>
                <div className="flex flex-wrap gap-2" role="group" aria-label="Amenities (select any that apply)">
                  {AMENITY_OPTIONS.map((opt) => {
                    const selected = amenities.includes(opt.value);
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => toggleAmenity(opt.value)}
                        className={`px-3 py-1.5 text-xs font-semibold tracking-widest uppercase border transition-colors ${
                          selected
                            ? 'bg-gold/15 border-gold text-gold'
                            : 'bg-transparent border-dark-border text-white/50 hover:border-gold/40'
                        }`}
                      >
                        {selected && <CheckCircle weight="fill" className="inline w-3 h-3 mr-1" />}
                        {opt.label}
                      </button>
                    );
                  })}
                </div>
                {amenities.includes('garage') && amenities.includes('off_street_parking') && (
                  <p className="text-white/40 text-[10px] mt-2">
                    Parking supersedes — only the Garage premium applies.
                  </p>
                )}
              </div>

              {mode === 'str' && (
                <div>
                  <p className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-2">
                    Market Type <span className="text-gold">*</span>
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    {MARKET_OPTIONS.map((m) => {
                      const selected = market === m.value;
                      return (
                        <button
                          key={m.value}
                          type="button"
                          onClick={() => setMarket(m.value)}
                          className={`px-3 py-2 text-xs font-semibold tracking-wide border text-left transition-colors ${
                            selected
                              ? 'bg-gold text-[#0a0a0a] border-gold'
                              : 'bg-dark-surface border-dark-border text-white/60 hover:border-gold/40 hover:text-white'
                          }`}
                        >
                          <div>{m.label}</div>
                          <div className="text-[10px] opacity-60 mt-0.5">{m.hint}</div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              <button
                type="button"
                onClick={handleAnalyze}
                disabled={loading || !address.trim() || !condition || !propertyType || (mode === 'str' && !market)}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-gold text-[#0a0a0a] font-semibold text-sm px-6 py-3 hover:bg-gold/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {loading ? <SpinnerGap weight="bold" className="w-4 h-4 animate-spin" /> : <House weight="bold" className="w-4 h-4" />}
                {loading ? 'Analyzing…' : 'Estimate'}
              </button>

              {!loading && (!address.trim() || !condition || !propertyType || (mode === 'str' && !market)) && (address || condition || propertyType || market) && (
                <p className="text-white/40 text-xs">
                  {!address.trim() && 'Address required. '}
                  {!propertyType && 'Pick a property type. '}
                  {!condition && 'Pick a condition. '}
                  {mode === 'str' && !market && 'Pick a market type.'}
                </p>
              )}

              {error && (
                <div className="flex items-start gap-2 text-amber-400/80 text-sm">
                  <Warning weight="fill" className="w-4 h-4 mt-0.5 shrink-0" />
                  {error}
                </div>
              )}
            </div>

            {/* Result */}
            <AnimatePresence>
              {result && (
                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -12 }}
                  className="mt-6 pt-6 border-t border-dark-border space-y-4"
                >
                  <div className="flex flex-wrap items-baseline gap-3">
                    <p className="text-gold font-black text-3xl leading-none">
                      {mode === 'str' ? `${fmt(result.nightly_median ?? 0)}/night` : `${fmt(result.monthly_median)}/mo`}
                    </p>
                    <p className="text-white/50 text-xs">
                      {mode === 'str'
                        ? `${fmt(result.nightly_low ?? 0)} – ${fmt(result.nightly_high ?? 0)} per night`
                        : `${fmt(result.monthly_low)} – ${fmt(result.monthly_high)} per month`}
                    </p>
                    <span className={`text-xs font-bold tracking-widest uppercase ${CONFIDENCE_COLOR[result.confidence]}`}>
                      {result.confidence} confidence
                    </span>
                  </div>

                  {mode === 'str' && (
                    <p className="text-white/45 text-xs">
                      Based on {result.market_multiplier}× LTR baseline at {result.suggested_occupancy_pct}% occupancy.
                    </p>
                  )}

                  <div>
                    <p className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-2">
                      Breakdown
                    </p>
                    <ul className="space-y-1.5">
                      {result.breakdown.map((b, i) => (
                        <li key={i} className="flex items-center justify-between text-sm text-white/70">
                          <span>{b.label}</span>
                          <span className="font-mono text-white/90">
                            {b.pct_delta != null ? `${b.pct_delta > 0 ? '+' : ''}${b.pct_delta}%` : ''}{' '}
                            {b.pct_delta != null ? `(${fmt(b.value_dollars)})` : fmt(b.value_dollars)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <button
                    type="button"
                    onClick={handleApply}
                    className="w-full bg-gold text-[#0a0a0a] font-semibold text-sm px-6 py-3 hover:bg-gold/90 transition-colors"
                  >
                    Use {fmt(mode === 'str' ? (result.nightly_median ?? 0) : result.monthly_median)} in Calculator
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
