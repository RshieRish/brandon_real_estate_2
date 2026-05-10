'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MagnifyingGlass, MapPin, SpinnerGap, CheckCircle, Warning } from '@phosphor-icons/react';
import { calculateMetrics, type BuyHoldInputs } from '@/lib/investor-calc';
import { apiPost } from '@/lib/api';
import AddressAutocomplete from '@/components/shared/AddressAutocomplete';
import AnalysisResults from './AnalysisResults';
import MeetingGate from './MeetingGate';
import type {
  InvestorAiReport,
  InvestorAnalysisResponse,
  InvestorLeadCapture,
} from './report-types';

type BuyHoldInputValues = Record<Exclude<keyof BuyHoldInputs, 'strategy'>, string>;

const EMPTY_INPUTS: BuyHoldInputValues = {
  purchasePrice: '',
  rehabCost: '',
  rentalIncome: '',
  propertyTax: '',
  insurance: '',
  downPaymentPct: '',
  interestRate: '',
  loanTermYears: '',
  holdYears: '',
};

const POSITIVE_FIELDS: Array<keyof BuyHoldInputValues> = [
  'purchasePrice',
  'holdYears',
  'loanTermYears',
];

interface LookupResult {
  address: string;
  property_type: string;
  bedrooms: number | null;
  bathrooms: number | null;
  sqft: number | null;
  year_built: number | null;
  purchase_price: number;
  price_range_low: number | null;
  price_range_high: number | null;
  monthly_rent: number | null;
  rent_range_low: number | null;
  rent_range_high: number | null;
  annual_taxes: number;
  estimated_insurance: number;
  last_sale_date: string | null;
  last_sale_price: number | null;
  comparables: Array<{
    address: string;
    price: number;
    bedrooms: number;
    bathrooms: number;
    sqft: number;
    distance_miles: number;
    correlation: number;
    image_url?: string | null;
  }>;
  data_source: string;
}

function parseBuyHoldInputs(values: BuyHoldInputValues): BuyHoldInputs | null {
  const parsed = Object.entries(values).reduce<Partial<BuyHoldInputs>>((acc, [key, value]) => {
    const trimmed = value.trim();
    const numeric = trimmed ? Number(trimmed) : 0;
    return { ...acc, [key]: Number.isFinite(numeric) ? numeric : 0 };
  }, {});
  const hasValid = POSITIVE_FIELDS.every((k) => (parsed[k] ?? 0) > 0);
  if (!hasValid) return null;
  return { ...parsed, strategy: 'buy_hold' } as BuyHoldInputs;
}

interface InputFieldProps {
  label: string;
  name: keyof BuyHoldInputValues;
  value: string;
  onChange: (name: keyof BuyHoldInputValues, value: string) => void;
  prefix?: string;
  suffix?: string;
  step?: number;
  highlight?: boolean;
}

function InputField({ label, name, value, onChange, prefix, suffix, step = 1, highlight }: InputFieldProps) {
  const displayValue = useMemo(() => {
    if (!value && value !== '0') return value;
    const parts = value.toString().split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return parts.join('.');
  }, [value]);

  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={`input-${name}`}
        className="text-white/50 text-xs font-medium tracking-widest uppercase"
      >
        {label}
      </label>
      <div className="relative flex items-center">
        {prefix && (
          <span className="absolute left-3 text-white/40 text-sm pointer-events-none select-none">
            {prefix}
          </span>
        )}
        <input
          id={`input-${name}`}
          type="text"
          inputMode="decimal"
          value={displayValue}
          onChange={(e) => {
            let raw = e.target.value.replace(/[^0-9.]/g, '');
            const parts = raw.split('.');
            if (parts.length > 2) {
              raw = parts[0] + '.' + parts.slice(1).join('');
            }
            onChange(name, raw);
          }}
          className={`
            w-full bg-dark-surface border text-white text-sm
            ${prefix ? 'pl-7' : 'pl-4'} ${suffix ? 'pr-10' : 'pr-4'} py-2.5
            focus:outline-none focus:border-gold transition-all duration-300
            ${highlight ? 'border-gold/50 bg-gold/5' : 'border-dark-border'}
          `}
        />
        {suffix && (
          <span className="absolute right-3 text-white/40 text-sm pointer-events-none select-none">
            {suffix}
          </span>
        )}
      </div>
    </div>
  );
}

export default function InvestorCalculator() {
  const [inputs, setInputs] = useState<BuyHoldInputValues>(EMPTY_INPUTS);
  const [fullReport, setFullReport] = useState<InvestorAiReport | null>(null);
  const engagementRetryTimeoutRef = useRef<number | null>(null);

  // Address lookup state
  const [lookupAddress, setLookupAddress] = useState('');
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupResult, setLookupResult] = useState<LookupResult | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [filledFields, setFilledFields] = useState<Set<keyof BuyHoldInputValues>>(new Set());

  const parsedInputs = useMemo(() => parseBuyHoldInputs(inputs), [inputs]);
  const metrics = useMemo(
    () => (parsedInputs ? calculateMetrics(parsedInputs) : null),
    [parsedInputs],
  );

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;

    const alreadySent = window.sessionStorage.getItem('investor_engagement_sent') === '1';
    if (!parsedInputs || alreadySent) return undefined;

    const existingKey = window.sessionStorage.getItem('investor_engagement_key');
    const sessionKey = existingKey || window.crypto?.randomUUID?.() || `investor-${Date.now()}`;
    if (!existingKey) {
      window.sessionStorage.setItem('investor_engagement_key', sessionKey);
    }

    let cancelled = false;

    const sendEngagement = async () => {
      try {
        await apiPost<{ queued: boolean }>('/api/v1/investor/engagement', {
          session_key: sessionKey,
          purchase_price: parsedInputs.purchasePrice,
          rehab_costs: parsedInputs.rehabCost,
          arv: 0, // placeholder until Flip strategy returns in Task 7
          hold_months: parsedInputs.holdYears * 12,
        });
        window.sessionStorage.setItem('investor_engagement_sent', '1');
      } catch {
        if (cancelled) return;
        engagementRetryTimeoutRef.current = window.setTimeout(sendEngagement, 5000);
      }
    };

    engagementRetryTimeoutRef.current = window.setTimeout(sendEngagement, 1200);

    return () => {
      cancelled = true;
      if (engagementRetryTimeoutRef.current) {
        window.clearTimeout(engagementRetryTimeoutRef.current);
      }
    };
  }, [parsedInputs]);

  function handleChange(name: keyof BuyHoldInputValues, value: string) {
    setInputs((prev) => ({ ...prev, [name]: value }));
    setFullReport(null);
    // Clear highlight after manual edit
    setFilledFields((prev) => {
      const next = new Set(prev);
      next.delete(name);
      return next;
    });
  }

  async function handleLookup() {
    if (!lookupAddress.trim()) return;
    setLookupLoading(true);
    setLookupError(null);
    setLookupResult(null);
    setFilledFields(new Set());

    try {
      const result = await apiPost<LookupResult>('/api/v1/investor/lookup', {
        address: lookupAddress.trim(),
      });
      setLookupResult(result);

      // Auto-fill fields from lookup
      const newInputs = { ...inputs };
      const filled = new Set<keyof BuyHoldInputValues>();

      if (result.purchase_price) {
        newInputs.purchasePrice = String(result.purchase_price);
        filled.add('purchasePrice');
      }
      if (result.monthly_rent) {
        newInputs.rentalIncome = String(result.monthly_rent);
        filled.add('rentalIncome');
      }
      if (result.annual_taxes) {
        newInputs.propertyTax = String(result.annual_taxes);
        filled.add('propertyTax');
      }
      if (result.estimated_insurance) {
        newInputs.insurance = String(result.estimated_insurance);
        filled.add('insurance');
      }

      setInputs(newInputs);
      setFilledFields(filled);
      setFullReport(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Lookup failed';
      if (msg.includes('404')) {
        setLookupError('Property not found. Try the full address with city, state, and ZIP.');
      } else {
        setLookupError('Could not look up this property. Try entering your numbers manually.');
      }
    } finally {
      setLookupLoading(false);
    }
  }

  async function handleUnlock(contact: InvestorLeadCapture) {
    if (!parsedInputs) return;

    const response = await apiPost<InvestorAnalysisResponse>('/api/v1/investor/analyze', {
      property_type: 'single_family',
      units: 1,
      purchase_price: parsedInputs.purchasePrice,
      down_payment_pct: parsedInputs.downPaymentPct,
      interest_rate: parsedInputs.interestRate,
      loan_term_years: parsedInputs.loanTermYears,
      monthly_rent_total: parsedInputs.rentalIncome,
      rehab_costs: parsedInputs.rehabCost,
      annual_taxes: parsedInputs.propertyTax,
      annual_insurance: parsedInputs.insurance,
      monthly_maintenance: 0,
      vacancy_rate_pct: 8,
      mgmt_fee_pct: 0,
      hold_years: parsedInputs.holdYears,
      appreciation_rate_pct: 3,
      name: contact.name || undefined,
      email: contact.email,
      phone: contact.phone || undefined,
    });
    setFullReport(response.report);
  }

  return (
    <div className="space-y-8">
      {/* ── Address Lookup Bar ── */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
        className="glass border border-dark-border rounded-xl p-5 md:p-6"
      >
        <div className="flex items-center gap-2 mb-3">
          <MapPin weight="fill" className="w-4 h-4 text-gold" />
          <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase">
            Smart Property Lookup
          </p>
        </div>
        <p className="text-white/50 text-sm font-light mb-4">
          Enter a property address to auto-fill deal parameters from public records, tax data, and market comparables.
        </p>
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <AddressAutocomplete
              value={lookupAddress}
              onChange={setLookupAddress}
              onSelect={(suggestion) => {
                setLookupAddress(suggestion.formatted_address);
                // Auto-trigger lookup after selecting from dropdown
                setTimeout(() => {
                  const btn = document.getElementById('investor-lookup-btn');
                  btn?.click();
                }, 100);
              }}
              placeholder="Start typing an address..."
              className="w-full bg-dark-surface border border-dark-border text-white text-sm px-4 py-2.5 focus:outline-none focus:border-gold transition-colors duration-200 placeholder:text-white/25"
            />
          </div>
          <button
            id="investor-lookup-btn"
            onClick={handleLookup}
            disabled={lookupLoading || !lookupAddress.trim()}
            className="inline-flex items-center justify-center gap-2 bg-gold text-[#0a0a0a] font-semibold text-sm px-6 py-2.5 hover:bg-gold/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
          >
            {lookupLoading ? (
              <SpinnerGap weight="bold" className="w-4 h-4 animate-spin" />
            ) : (
              <MagnifyingGlass weight="bold" className="w-4 h-4" />
            )}
            {lookupLoading ? 'Looking Up...' : 'Look Up'}
          </button>
        </div>

        {/* Lookup result summary */}
        <AnimatePresence>
          {lookupResult && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.3 }}
              className="mt-4 pt-4 border-t border-dark-border"
            >
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle weight="fill" className="w-4 h-4 text-green-400" />
                <p className="text-white text-sm font-medium">
                  {lookupResult.address}
                </p>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <div>
                  <span className="text-white/40 uppercase tracking-wider">Est. Value</span>
                  <p className="text-gold font-bold text-sm mt-0.5">
                    ${lookupResult.purchase_price?.toLocaleString() || '—'}
                  </p>
                </div>
                <div>
                  <span className="text-white/40 uppercase tracking-wider">Est. Rent</span>
                  <p className="text-gold font-bold text-sm mt-0.5">
                    ${lookupResult.monthly_rent?.toLocaleString() || '—'}/mo
                  </p>
                </div>
                <div>
                  <span className="text-white/40 uppercase tracking-wider">Taxes</span>
                  <p className="text-white font-medium text-sm mt-0.5">
                    ${lookupResult.annual_taxes?.toLocaleString() || '—'}/yr
                  </p>
                </div>
                <div>
                  <span className="text-white/40 uppercase tracking-wider">Details</span>
                  <p className="text-white font-medium text-sm mt-0.5">
                    {lookupResult.bedrooms || '?'}bd / {lookupResult.bathrooms || '?'}ba · {lookupResult.sqft?.toLocaleString() || '?'} sqft
                  </p>
                </div>
              </div>
              <p className="text-white/30 text-[10px] mt-3 tracking-wide uppercase">
                Data sourced from public records · Fields auto-filled below
              </p>
            </motion.div>
          )}
          {lookupError && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-4 pt-4 border-t border-dark-border flex items-start gap-2"
            >
              <Warning weight="fill" className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <p className="text-amber-400/80 text-sm">{lookupError}</p>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* ── Main Calculator Grid ── */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.1fr] gap-8 lg:gap-12">
        {/* ── LEFT: Inputs ── */}
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
          className="space-y-4"
        >
          <div>
            <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-1">
              Deal Parameters
            </p>
            <h3 className="text-white font-black text-lg tracking-tight">
              Enter Your Numbers
            </h3>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <InputField
              label="Purchase Price"
              name="purchasePrice"
              value={inputs.purchasePrice}
              onChange={handleChange}
              prefix="$"
              step={1000}
              highlight={filledFields.has('purchasePrice')}
            />
            <InputField
              label="Rehab / Renovation Cost"
              name="rehabCost"
              value={inputs.rehabCost}
              onChange={handleChange}
              prefix="$"
              step={1000}
            />
            <InputField
              label="Hold Period (Years)"
              name="holdYears"
              value={inputs.holdYears}
              onChange={handleChange}
              suffix="yr"
              step={1}
            />
            <InputField
              label="Monthly Rental Income"
              name="rentalIncome"
              value={inputs.rentalIncome}
              onChange={handleChange}
              prefix="$"
              step={100}
              highlight={filledFields.has('rentalIncome')}
            />
            <InputField
              label="Property Tax / Year"
              name="propertyTax"
              value={inputs.propertyTax}
              onChange={handleChange}
              prefix="$"
              step={100}
              highlight={filledFields.has('propertyTax')}
            />
            <InputField
              label="Annual Insurance"
              name="insurance"
              value={inputs.insurance}
              onChange={handleChange}
              prefix="$"
              step={100}
              highlight={filledFields.has('insurance')}
            />
            <InputField
              label="Down Payment %"
              name="downPaymentPct"
              value={inputs.downPaymentPct}
              onChange={handleChange}
              suffix="%"
              step={0.01}
            />
            <InputField
              label="Interest Rate"
              name="interestRate"
              value={inputs.interestRate}
              onChange={handleChange}
              suffix="%"
              step={0.001}
            />
            <InputField
              label="Loan Term"
              name="loanTermYears"
              value={inputs.loanTermYears}
              onChange={handleChange}
              suffix="yr"
              step={1}
            />
          </div>
        </motion.div>

        {/* ── RIGHT: Preview + Gate ── */}
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ type: 'spring' as const, stiffness: 100, damping: 20, delay: 0.1 }}
          className="space-y-6"
        >
          <div>
            <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-1">
              Instant Snapshot
            </p>
            <h3 className="text-white font-black text-lg tracking-tight mb-3">
              Live Numbers As You Model The Deal
            </h3>
            <p className="text-white/50 text-sm font-light mb-5">
              These headline numbers update immediately. The gated step below is only for the deeper AI report.
            </p>
            {metrics ? (
              <AnalysisResults metrics={metrics} />
            ) : (
              <div className="glass border border-dark-border rounded-xl p-6 md:p-8 text-center">
                <p className="text-gold text-xs font-semibold tracking-[0.18em] uppercase mb-3">
                  Waiting On Deal Inputs
                </p>
                <h4 className="text-white font-black text-lg tracking-tight mb-3">
                  Your snapshot will appear here
                </h4>
                <p className="text-white/45 text-sm font-light leading-relaxed max-w-sm mx-auto">
                  Fill out the deal parameters on the left to reveal the instant numbers. The full AI report still unlocks only after email capture.
                </p>
              </div>
            )}
          </div>

          {metrics && (
            <MeetingGate
              fullReport={fullReport}
              onUnlock={handleUnlock}
            />
          )}
        </motion.div>
      </div>
    </div>
  );
}
