'use client';

import { motion } from 'framer-motion';
import type { InvestorMetrics } from '@/lib/investor-calc';

interface AnalysisResultsProps {
  metrics: InvestorMetrics;
}

const fmt = (value: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value);

const pct = (value: number) => value.toFixed(1) + '%';

const containerVariants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.06,
    },
  },
};

const cardVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { type: 'spring' as const, stiffness: 100, damping: 20 },
  },
};

interface MetricCardProps {
  label: string;
  value: string;
  valueColor?: string;
  eyebrow: string;
}

function MetricCard({ label, value, valueColor = 'text-white', eyebrow }: MetricCardProps) {
  return (
    <motion.div
      variants={cardVariants}
      className="glass border border-dark-border rounded-xl p-4 md:p-5 flex flex-col gap-2"
    >
      <span className="text-gold text-xs font-semibold tracking-[0.18em] uppercase">{eyebrow}</span>
      <span className="text-white/40 text-xs font-medium tracking-widest uppercase leading-tight">
        {label}
      </span>
      <span className={`font-black text-2xl md:text-3xl leading-none ${valueColor}`}>{value}</span>
    </motion.div>
  );
}

export default function AnalysisResults({ metrics }: AnalysisResultsProps) {
  const {
    loanStructure,
    flipProfit,
    flipROI,
    flipAnnualizedROI,
    maxAllowableOffer,
    holdingCosts,
    closingCosts,
    totalProjectCost,
    monthlyCashFlow,
    cashOnCashReturn,
    capRate,
    grm,
  } = metrics;

  const cashFlowColor =
    monthlyCashFlow < 0 ? 'text-red-400' : 'text-white';
  const cocColor =
    cashOnCashReturn >= 8 ? 'text-emerald-400' : 'text-white';

  return (
    <div className="space-y-8">
      {/* Flip Analysis */}
      <div>
        <h3 className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
          Flip Analysis
        </h3>
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="grid grid-cols-2 gap-3"
        >
          <MetricCard
            eyebrow="Flip"
            label="Estimated Profit"
            value={fmt(flipProfit)}
            valueColor={flipProfit >= 0 ? 'text-emerald-400' : 'text-red-400'}
          />
          <MetricCard
            eyebrow="Flip"
            label="ROI"
            value={pct(flipROI)}
          />
          <MetricCard
            eyebrow="Flip"
            label="Annualized ROI"
            value={pct(flipAnnualizedROI)}
          />
          <MetricCard
            eyebrow="Flip"
            label="80% Rule Offer Cap"
            value={fmt(maxAllowableOffer)}
          />
          <MetricCard
            eyebrow="Flip"
            label="Holding Costs"
            value={fmt(holdingCosts)}
          />
          <MetricCard
            eyebrow="Flip"
            label="Closing Costs"
            value={fmt(closingCosts)}
          />
          <MetricCard
            eyebrow="Flip"
            label="Total Project Cost"
            value={fmt(totalProjectCost)}
            valueColor="text-gold"
          />
        </motion.div>
        <p className="mt-3 text-white/35 text-xs font-light leading-relaxed">
          Flip math assumes 1.5% buy-side closing costs and 1.25% sell-side closing costs.
          {' '}
          {loanStructure === 'interest_only'
            ? 'Short-term loan terms of 1-2 years are modeled as interest-only bridge or fix-and-flip debt.'
            : 'Loan terms of 3+ years are modeled with amortized payments.'}
          {' '}
          The 80% Rule Offer Cap is a conservative max purchase offer, not total project cost:
          ARV x 80% minus rehab.
        </p>
      </div>

      {/* Rental / BRRRR Analysis */}
      <div>
        <h3 className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
          Rental / BRRRR Analysis
        </h3>
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="grid grid-cols-2 gap-3"
        >
          <MetricCard
            eyebrow="Rental"
            label="Monthly Cash Flow"
            value={fmt(monthlyCashFlow)}
            valueColor={cashFlowColor}
          />
          <MetricCard
            eyebrow="Rental"
            label="Cash-on-Cash Return"
            value={pct(cashOnCashReturn)}
            valueColor={cocColor}
          />
          <MetricCard
            eyebrow="Rental"
            label="Cap Rate"
            value={pct(capRate)}
            valueColor="text-gold"
          />
          <MetricCard
            eyebrow="Rental"
            label="Gross Rent Multiplier"
            value={grm.toFixed(1)}
          />
        </motion.div>
      </div>
    </div>
  );
}
