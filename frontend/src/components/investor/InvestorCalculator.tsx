'use client';

import { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import { LockSimple } from '@phosphor-icons/react';
import { calculateMetrics, type InvestorInputs } from '@/lib/investor-calc';
import { apiPost } from '@/lib/api';
import MeetingGate from './MeetingGate';
import AnalysisResults from './AnalysisResults';

const DEFAULT_INPUTS: InvestorInputs = {
  purchasePrice: 300000,
  rehabCost: 40000,
  arv: 420000,
  holdMonths: 4,
  rentalIncome: 2400,
  propertyTax: 4800,
  insurance: 1500,
  downPaymentPct: 0.25,
  interestRate: 0.07,
  loanTermYears: 30,
};

interface InputFieldProps {
  label: string;
  name: keyof InvestorInputs;
  value: number;
  onChange: (name: keyof InvestorInputs, value: number) => void;
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
          onChange={(e) => onChange(name, parseFloat(e.target.value) || 0)}
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

const fmt = (value: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value);

const pct = (value: number) => value.toFixed(1) + '%';

export default function InvestorCalculator() {
  const [inputs, setInputs] = useState<InvestorInputs>(DEFAULT_INPUTS);
  const [isUnlocked, setIsUnlocked] = useState(false);

  const metrics = useMemo(() => calculateMetrics(inputs), [inputs]);

  function handleChange(name: keyof InvestorInputs, value: number) {
    setInputs((prev) => ({ ...prev, [name]: value }));
  }

  async function handleUnlock(email: string) {
    await apiPost('/api/v1/leads/', {
      name: 'Investor Lead',
      email,
      lead_type: 'investor',
      source: 'investor-calculator',
    });
    setIsUnlocked(true);
  }

  function handleBook() {
    window.location.href = 'tel:9789872806';
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
        {!isUnlocked ? (
          <>
            {/* Teaser — blurred locked metrics */}
            <div>
              <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-3">
                Preview
              </p>
              <div className="grid grid-cols-3 gap-3 mb-6">
                {[
                  { label: 'Cash-on-Cash', value: pct(metrics.cashOnCashReturn) },
                  { label: 'Flip Profit', value: fmt(metrics.flipProfit) },
                  { label: 'Cap Rate', value: pct(metrics.capRate) },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="glass border border-dark-border rounded-xl p-3 relative overflow-hidden"
                  >
                    <span className="text-white/40 text-xs font-medium tracking-widest uppercase block mb-1">
                      {item.label}
                    </span>
                    {/* Blurred value */}
                    <span
                      className="font-black text-lg text-white/20 block"
                      style={{ filter: 'blur(6px)', userSelect: 'none' }}
                      aria-hidden="true"
                    >
                      {item.value}
                    </span>
                    {/* Lock overlay */}
                    <div className="absolute inset-0 flex items-center justify-center">
                      <LockSimple weight="fill" className="w-5 h-5 text-gold/70" aria-hidden="true" />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <MeetingGate
              isUnlocked={isUnlocked}
              onUnlock={handleUnlock}
              onBook={handleBook}
              metrics={metrics}
            />
          </>
        ) : (
          <div className="space-y-6">
            <AnalysisResults metrics={metrics} />
            <motion.button
              onClick={handleBook}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
              className="
                w-full bg-gold text-[#0a0a0a] font-bold text-sm tracking-widest uppercase
                px-6 py-4 transition-colors duration-200 hover:bg-gold-hover
              "
            >
              Book a Strategy Call With Brandon
            </motion.button>
          </div>
        )}
      </motion.div>
    </div>
  );
}
