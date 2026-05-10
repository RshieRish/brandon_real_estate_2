'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams, useRouter, usePathname } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { MagnifyingGlass, MapPin, SpinnerGap, CheckCircle, Warning } from '@phosphor-icons/react';
import {
  calculateMetrics,
  type BuyHoldInputs,
  type BrrrrInputs,
  type FlipInputs,
  type StrInputs,
  type Strategy,
  type InvestorInputs,
} from '@/lib/investor-calc';
import { apiPost } from '@/lib/api';
import AddressAutocomplete from '@/components/shared/AddressAutocomplete';
import AnalysisResults from './AnalysisResults';
import MeetingGate from './MeetingGate';
import StrategyToggle from './StrategyToggle';
import { STRATEGY_DEFAULTS, isStrategy } from './strategy-defaults';
import type {
  InvestorAiReport,
  InvestorAnalysisResponse,
  InvestorLeadCapture,
} from './report-types';

// Internal flat input record — we don't strongly type each strategy here because
// the same component renders different field sets depending on strategy.
type InputValues = Record<string, string>;

const EMPTY_INPUTS: InputValues = {
  purchasePrice: '',
  rehabCost: '',
  rentalIncome: '',
  propertyTax: '',
  insurance: '',
  downPaymentPct: '',
  interestRate: '',
  loanTermYears: '',
  // Strategy-specific (start empty)
  holdYears: '',
  holdMonths: '',
  arv: '',
  nightlyRate: '',
  occupancyPct: '',
  cleaningFeePerNight: '',
  strMgmtPct: '',
  monthlyUtilities: '',
  refiLtvPct: '',
  refiRate: '',
  refiTermYears: '',
  holdMonthsBeforeRefi: '',
};

function num(values: InputValues, key: string): number {
  const trimmed = (values[key] ?? '').trim();
  if (!trimmed) return 0;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : 0;
}

function parseInputs(strategy: Strategy, values: InputValues): InvestorInputs | null {
  const required: Record<Strategy, string[]> = {
    buy_hold: ['purchasePrice', 'holdYears', 'loanTermYears'],
    str: ['purchasePrice', 'nightlyRate', 'loanTermYears'],
    flip: ['purchasePrice', 'arv', 'holdMonths', 'loanTermYears'],
    brrrr: ['purchasePrice', 'arv', 'holdMonthsBeforeRefi', 'refiTermYears', 'loanTermYears'],
  };
  const missing = required[strategy].some((k) => num(values, k) <= 0);
  if (missing) return null;

  const baseFields = {
    purchasePrice: num(values, 'purchasePrice'),
    rehabCost: num(values, 'rehabCost'),
    propertyTax: num(values, 'propertyTax'),
    insurance: num(values, 'insurance'),
    downPaymentPct: num(values, 'downPaymentPct'),
    interestRate: num(values, 'interestRate'),
    loanTermYears: num(values, 'loanTermYears'),
  };

  switch (strategy) {
    case 'buy_hold':
      return {
        strategy: 'buy_hold',
        ...baseFields,
        rentalIncome: num(values, 'rentalIncome'),
        holdYears: num(values, 'holdYears'),
      } satisfies BuyHoldInputs;
    case 'str':
      return {
        strategy: 'str',
        ...baseFields,
        nightlyRate: num(values, 'nightlyRate'),
        occupancyPct: num(values, 'occupancyPct'),
        cleaningFeePerNight: num(values, 'cleaningFeePerNight'),
        strMgmtPct: num(values, 'strMgmtPct'),
        monthlyUtilities: num(values, 'monthlyUtilities'),
      } satisfies StrInputs;
    case 'flip':
      return {
        strategy: 'flip',
        ...baseFields,
        arv: num(values, 'arv'),
        holdMonths: num(values, 'holdMonths'),
      } satisfies FlipInputs;
    case 'brrrr':
      return {
        strategy: 'brrrr',
        ...baseFields,
        arv: num(values, 'arv'),
        rentalIncome: num(values, 'rentalIncome'),
        refiLtvPct: num(values, 'refiLtvPct'),
        refiRate: num(values, 'refiRate'),
        refiTermYears: num(values, 'refiTermYears'),
        holdMonthsBeforeRefi: num(values, 'holdMonthsBeforeRefi'),
      } satisfies BrrrrInputs;
    default: {
      const _exhaustive: never = strategy;
      return _exhaustive;
    }
  }
}

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

interface InputFieldProps {
  label: string;
  name: string;
  value: string;
  onChange: (name: string, value: string) => void;
  prefix?: string;
  suffix?: string;
  step?: number;
  highlight?: boolean;
}

function InputField({ label, name, value, onChange, prefix, suffix, highlight }: InputFieldProps) {
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
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const initialStrategy: Strategy = (() => {
    const fromUrl = searchParams.get('strategy');
    return isStrategy(fromUrl) ? fromUrl : 'buy_hold';
  })();

  const [strategy, setStrategyState] = useState<Strategy>(initialStrategy);
  const [inputs, setInputs] = useState<InputValues>(() => ({
    ...EMPTY_INPUTS,
    ...STRATEGY_DEFAULTS[initialStrategy],
  }));
  const [fullReport, setFullReport] = useState<InvestorAiReport | null>(null);
  const engagementRetryTimeoutRef = useRef<number | null>(null);
  const inputsRef = useRef<InputValues>(inputs);
  const strategyRef = useRef<Strategy>(strategy);

  // Address lookup state
  const [lookupAddress, setLookupAddress] = useState('');
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupResult, setLookupResult] = useState<LookupResult | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [filledFields, setFilledFields] = useState<Set<string>>(new Set());

  function setStrategy(next: Strategy) {
    setStrategyState(next);
    setFullReport(null);
    setInputs((prev) => {
      // Preserve all overlapping field values; layer in defaults only for empty fields.
      const merged = { ...prev };
      for (const [key, def] of Object.entries(STRATEGY_DEFAULTS[next])) {
        if (!merged[key] || merged[key].trim() === '') merged[key] = def;
      }
      return merged;
    });
    // URL sync
    const params = new URLSearchParams(searchParams.toString());
    if (next === 'buy_hold') {
      params.delete('strategy');
    } else {
      params.set('strategy', next);
    }
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const parsedInputs = useMemo(() => parseInputs(strategy, inputs), [strategy, inputs]);
  const metrics = useMemo(
    () => (parsedInputs ? calculateMetrics(parsedInputs) : null),
    [parsedInputs],
  );

  // Keep refs current with latest state
  useEffect(() => {
    inputsRef.current = inputs;
  }, [inputs]);

  useEffect(() => {
    strategyRef.current = strategy;
  }, [strategy]);

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
        const arvVal = num(inputsRef.current, 'arv') || num(inputsRef.current, 'purchasePrice');
        const holdMonthsVal =
          strategyRef.current === 'flip'
            ? num(inputsRef.current, 'holdMonths')
            : strategyRef.current === 'brrrr'
              ? num(inputsRef.current, 'holdMonthsBeforeRefi')
              : num(inputsRef.current, 'holdYears') * 12;

        await apiPost<{ queued: boolean }>('/api/v1/investor/engagement', {
          session_key: sessionKey,
          purchase_price: num(inputsRef.current, 'purchasePrice'),
          rehab_costs: num(inputsRef.current, 'rehabCost'),
          arv: arvVal,
          hold_months: holdMonthsVal,
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

  function handleChange(name: string, value: string) {
    setInputs((prev) => ({ ...prev, [name]: value }));
    setFullReport(null);
    setFilledFields((prev) => {
      if (!prev.has(name)) return prev;
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
      const filled = new Set<string>();

      if (result.purchase_price) {
        newInputs.purchasePrice = String(result.purchase_price);
        newInputs.arv = String(result.purchase_price); // ARV defaults to current value (used by Flip/BRRRR)
        filled.add('purchasePrice');
        filled.add('arv');
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

    const purchasePriceVal = num(inputs, 'purchasePrice');
    const rentVal = num(inputs, 'rentalIncome'); // 0 for flip/str
    const holdYears =
      strategy === 'flip'
        ? Math.max(1, Math.ceil(num(inputs, 'holdMonths') / 12))
        : strategy === 'brrrr'
          ? Math.max(1, Math.ceil(num(inputs, 'holdMonthsBeforeRefi') / 12))
          : Math.max(1, num(inputs, 'holdYears'));

    const response = await apiPost<InvestorAnalysisResponse>('/api/v1/investor/analyze', {
      property_type: 'single_family',
      units: 1,
      purchase_price: purchasePriceVal,
      down_payment_pct: num(inputs, 'downPaymentPct'),
      interest_rate: num(inputs, 'interestRate'),
      loan_term_years: num(inputs, 'loanTermYears'),
      monthly_rent_total: rentVal,
      rehab_costs: num(inputs, 'rehabCost'),
      annual_taxes: num(inputs, 'propertyTax'),
      annual_insurance: num(inputs, 'insurance'),
      monthly_maintenance: 0,
      vacancy_rate_pct: 8,
      mgmt_fee_pct: 0,
      hold_years: holdYears,
      appreciation_rate_pct: 3,
      name: contact.name || undefined,
      email: contact.email,
      phone: contact.phone || undefined,
      strategy, // NEW: thread strategy into the AI report
    });
    setFullReport(response.report);
  }

  return (
    <div className="space-y-8">
      <StrategyToggle value={strategy} onChange={setStrategy} />

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
            {/* Common fields — always shown */}
            <InputField label="Purchase Price" name="purchasePrice" value={inputs.purchasePrice}
              onChange={handleChange} prefix="$" highlight={filledFields.has('purchasePrice')} />
            <InputField label="Rehab / Renovation Cost" name="rehabCost" value={inputs.rehabCost}
              onChange={handleChange} prefix="$" />

            {/* Buy & Hold + BRRRR: monthly rent */}
            {(strategy === 'buy_hold' || strategy === 'brrrr') && (
              <InputField label="Monthly Rental Income" name="rentalIncome" value={inputs.rentalIncome}
                onChange={handleChange} prefix="$" highlight={filledFields.has('rentalIncome')} />
            )}

            {/* Flip + BRRRR: ARV */}
            {(strategy === 'flip' || strategy === 'brrrr') && (
              <InputField label="After-Repair Value (ARV)" name="arv" value={inputs.arv}
                onChange={handleChange} prefix="$" highlight={filledFields.has('arv')} />
            )}

            {/* STR-only fields */}
            {strategy === 'str' && (
              <>
                <InputField label="Nightly Rate" name="nightlyRate" value={inputs.nightlyRate}
                  onChange={handleChange} prefix="$" />
                <InputField label="Occupancy %" name="occupancyPct" value={inputs.occupancyPct}
                  onChange={handleChange} suffix="%" />
                <InputField label="Cleaning Fee / Night" name="cleaningFeePerNight"
                  value={inputs.cleaningFeePerNight} onChange={handleChange} prefix="$" />
                <InputField label="STR Mgmt %" name="strMgmtPct" value={inputs.strMgmtPct}
                  onChange={handleChange} suffix="%" />
                <InputField label="Monthly Utilities" name="monthlyUtilities"
                  value={inputs.monthlyUtilities} onChange={handleChange} prefix="$" />
              </>
            )}

            {/* Flip-only field */}
            {strategy === 'flip' && (
              <InputField label="Hold Period" name="holdMonths" value={inputs.holdMonths}
                onChange={handleChange} suffix="mo" />
            )}

            {/* Buy & Hold-only field */}
            {strategy === 'buy_hold' && (
              <InputField label="Hold Period" name="holdYears" value={inputs.holdYears}
                onChange={handleChange} suffix="yr" />
            )}

            {/* BRRRR-only fields */}
            {strategy === 'brrrr' && (
              <>
                <InputField label="Hold Months Before Refi" name="holdMonthsBeforeRefi"
                  value={inputs.holdMonthsBeforeRefi} onChange={handleChange} suffix="mo" />
                <InputField label="Refi LTV %" name="refiLtvPct" value={inputs.refiLtvPct}
                  onChange={handleChange} suffix="%" />
                <InputField label="Refi Rate" name="refiRate" value={inputs.refiRate}
                  onChange={handleChange} suffix="%" />
                <InputField label="Refi Term" name="refiTermYears" value={inputs.refiTermYears}
                  onChange={handleChange} suffix="yr" />
              </>
            )}

            {/* Common financial fields */}
            <InputField label="Property Tax / Year" name="propertyTax" value={inputs.propertyTax}
              onChange={handleChange} prefix="$" highlight={filledFields.has('propertyTax')} />
            <InputField label="Annual Insurance" name="insurance" value={inputs.insurance}
              onChange={handleChange} prefix="$" highlight={filledFields.has('insurance')} />
            <InputField label="Down Payment %" name="downPaymentPct" value={inputs.downPaymentPct}
              onChange={handleChange} suffix="%" />
            <InputField
              label={strategy === 'brrrr' ? 'Initial Rate' : 'Interest Rate'}
              name="interestRate" value={inputs.interestRate}
              onChange={handleChange} suffix="%" />
            <InputField
              label={strategy === 'brrrr' ? 'Initial Term' : 'Loan Term'}
              name="loanTermYears" value={inputs.loanTermYears}
              onChange={handleChange} suffix="yr" />
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
