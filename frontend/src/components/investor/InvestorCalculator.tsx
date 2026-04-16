'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { calculateMetrics, type InvestorInputs } from '@/lib/investor-calc';
import { apiPost } from '@/lib/api';
import AnalysisResults from './AnalysisResults';
import MeetingGate from './MeetingGate';
import type {
  InvestorAiReport,
  InvestorAnalysisResponse,
  InvestorLeadCapture,
} from './report-types';

type InvestorInputValues = Record<keyof InvestorInputs, string>;

const EMPTY_INPUTS: InvestorInputValues = {
  purchasePrice: '',
  rehabCost: '',
  arv: '',
  holdMonths: '',
  rentalIncome: '',
  propertyTax: '',
  insurance: '',
  downPaymentPct: '',
  interestRate: '',
  loanTermYears: '',
};

const POSITIVE_FIELDS: Array<keyof InvestorInputs> = [
  'purchasePrice',
  'arv',
  'holdMonths',
  'loanTermYears',
];

function parseInvestorInputs(values: InvestorInputValues): InvestorInputs | null {
  const parsed = Object.entries(values).reduce<Partial<InvestorInputs>>((acc, [key, value]) => {
    const typedKey = key as keyof InvestorInputs;
    const trimmed = value.trim();
    const numeric = trimmed ? Number(trimmed) : 0;
    if (!Number.isFinite(numeric)) {
      return { ...acc, [typedKey]: 0 };
    }
    return { ...acc, [typedKey]: numeric };
  }, {});

  const hasValidRequiredValues = POSITIVE_FIELDS.every((key) => (parsed[key] ?? 0) > 0);
  if (!hasValidRequiredValues) return null;

  return parsed as InvestorInputs;
}

interface InputFieldProps {
  label: string;
  name: keyof InvestorInputs;
  value: string;
  onChange: (name: keyof InvestorInputs, value: string) => void;
  prefix?: string;
  suffix?: string;
  step?: number;
}

function InputField({ label, name, value, onChange, prefix, suffix, step = 1 }: InputFieldProps) {
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
          type="number"
          step={step}
          value={value}
          onChange={(e) => onChange(name, e.target.value)}
          className={`
            w-full bg-dark-surface border border-dark-border text-white text-sm
            ${prefix ? 'pl-7' : 'pl-4'} ${suffix ? 'pr-10' : 'pr-4'} py-2.5
            focus:outline-none focus:border-gold transition-colors duration-200
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
  const [inputs, setInputs] = useState<InvestorInputValues>(EMPTY_INPUTS);
  const [fullReport, setFullReport] = useState<InvestorAiReport | null>(null);
  const engagementRetryTimeoutRef = useRef<number | null>(null);

  const parsedInputs = useMemo(() => parseInvestorInputs(inputs), [inputs]);
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
          arv: parsedInputs.arv,
          hold_months: parsedInputs.holdMonths,
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

  function handleChange(name: keyof InvestorInputs, value: string) {
    setInputs((prev) => ({ ...prev, [name]: value }));
    setFullReport(null);
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
      hold_years: Math.max(1, Math.ceil(parsedInputs.holdMonths / 12)),
      appreciation_rate_pct: 3,
      name: contact.name || undefined,
      email: contact.email,
      phone: contact.phone || undefined,
    });
    setFullReport(response.report);
  }

  return (
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
            label="After-Repair Value (ARV)"
            name="arv"
            value={inputs.arv}
            onChange={handleChange}
            prefix="$"
            step={1000}
          />
          <InputField
            label="Hold Period"
            name="holdMonths"
            value={inputs.holdMonths}
            onChange={handleChange}
            suffix="mo"
            step={1}
          />
          <InputField
            label="Monthly Rental Income"
            name="rentalIncome"
            value={inputs.rentalIncome}
            onChange={handleChange}
            prefix="$"
            step={100}
          />
          <InputField
            label="Property Tax / Year"
            name="propertyTax"
            value={inputs.propertyTax}
            onChange={handleChange}
            prefix="$"
            step={100}
          />
          <InputField
            label="Annual Insurance"
            name="insurance"
            value={inputs.insurance}
            onChange={handleChange}
            prefix="$"
            step={100}
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
  );
}
