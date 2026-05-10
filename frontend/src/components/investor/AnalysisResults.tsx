'use client';

import { motion } from 'framer-motion';
import type { InvestorMetrics } from '@/lib/investor-calc';

interface AnalysisResultsProps {
  metrics: InvestorMetrics;
}

const fmt = (value: number) =>
  Number.isFinite(value)
    ? new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 0,
      }).format(value)
    : '∞';

const pct = (value: number) =>
  Number.isFinite(value) ? `${value.toFixed(1)}%` : 'Infinite';

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.06 } },
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

function MetricsGrid({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <div>
      <h3 className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">{title}</h3>
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="grid grid-cols-2 gap-3"
      >
        {children}
      </motion.div>
    </div>
  );
}

export default function AnalysisResults({ metrics }: AnalysisResultsProps) {
  if (metrics.strategy === 'buy_hold') {
    return (
      <MetricsGrid title="Buy & Hold Analysis">
        <MetricCard
          eyebrow="Rental"
          label="Monthly Cash Flow"
          value={fmt(metrics.monthlyCashFlow)}
          valueColor={metrics.monthlyCashFlow < 0 ? 'text-red-400' : 'text-white'}
        />
        <MetricCard
          eyebrow="Rental"
          label="Cash-on-Cash Return"
          value={pct(metrics.cashOnCashReturn)}
          valueColor={metrics.cashOnCashReturn >= 8 ? 'text-emerald-400' : 'text-white'}
        />
        <MetricCard eyebrow="Rental" label="Cap Rate" value={pct(metrics.capRate)} valueColor="text-gold" />
        <MetricCard eyebrow="Rental" label="GRM" value={metrics.grm.toFixed(1)} />
        <MetricCard eyebrow="Rental" label="Annual NOI" value={fmt(metrics.noi)} />
        <MetricCard eyebrow="Rental" label="5-Year Equity" value={fmt(metrics.fiveYearEquityBuild)} />
      </MetricsGrid>
    );
  }

  if (metrics.strategy === 'str') {
    return (
      <MetricsGrid title="Short-Term Rental Analysis">
        <MetricCard eyebrow="STR" label="Monthly Revenue" value={fmt(metrics.monthlyRevenue)} valueColor="text-gold" />
        <MetricCard
          eyebrow="STR"
          label="Monthly Cash Flow"
          value={fmt(metrics.monthlyCashFlow)}
          valueColor={metrics.monthlyCashFlow < 0 ? 'text-red-400' : 'text-white'}
        />
        <MetricCard eyebrow="STR" label="Cash-on-Cash" value={pct(metrics.cashOnCashReturn)} />
        <MetricCard
          eyebrow="STR"
          label="Break-Even Occupancy"
          value={pct(metrics.breakEvenOccupancyPct)}
        />
        <MetricCard eyebrow="STR" label="Gross / Night" value={fmt(metrics.grossPerNight)} />
        <MetricCard eyebrow="STR" label="Net / Night" value={fmt(metrics.netPerNight)} />
      </MetricsGrid>
    );
  }

  if (metrics.strategy === 'flip') {
    return (
      <MetricsGrid title="Flip Analysis">
        <MetricCard
          eyebrow="Flip"
          label="Estimated Profit"
          value={fmt(metrics.flipProfit)}
          valueColor={metrics.flipProfit >= 0 ? 'text-emerald-400' : 'text-red-400'}
        />
        <MetricCard eyebrow="Flip" label="ROI" value={pct(metrics.flipROI)} />
        <MetricCard eyebrow="Flip" label="Annualized ROI" value={pct(metrics.flipAnnualizedROI)} />
        <MetricCard eyebrow="Flip" label="70% Rule MAO" value={fmt(metrics.maxAllowableOffer70)} valueColor="text-gold" />
        <MetricCard eyebrow="Flip" label="80% Rule MAO" value={fmt(metrics.maxAllowableOffer80)} />
        <MetricCard eyebrow="Flip" label="Holding Costs" value={fmt(metrics.holdingCosts)} />
        <MetricCard eyebrow="Flip" label="Closing Costs" value={fmt(metrics.closingCosts)} />
        <MetricCard eyebrow="Flip" label="Total Project Cost" value={fmt(metrics.totalProjectCost)} valueColor="text-gold" />
      </MetricsGrid>
    );
  }

  // BRRRR
  return (
    <div className="space-y-6">
      <MetricsGrid title="BRRRR Analysis">
        <MetricCard eyebrow="BRRRR" label="Cash Into Deal" value={fmt(metrics.cashIntoDealUpfront)} />
        <MetricCard eyebrow="BRRRR" label="Refi Loan" value={fmt(metrics.refiLoanAmount)} />
        <MetricCard eyebrow="BRRRR" label="Cash Recovered" value={fmt(metrics.cashRecoveredAtRefi)} valueColor="text-emerald-400" />
        <MetricCard
          eyebrow="BRRRR"
          label="Cash Left In Deal"
          value={fmt(Math.max(0, metrics.cashLeftInDeal))}
          valueColor={metrics.isInfiniteRoi ? 'text-emerald-400' : 'text-white'}
        />
        <MetricCard
          eyebrow="BRRRR"
          label="Post-Refi Cash Flow"
          value={fmt(metrics.postRefiMonthlyCashFlow)}
          valueColor={metrics.postRefiMonthlyCashFlow < 0 ? 'text-red-400' : 'text-white'}
        />
        <MetricCard
          eyebrow="BRRRR"
          label="Post-Refi CoC"
          value={pct(metrics.postRefiCashOnCash)}
          valueColor={metrics.isInfiniteRoi ? 'text-emerald-400' : 'text-white'}
        />
      </MetricsGrid>
      {metrics.isInfiniteRoi && (
        <p className="text-emerald-400 text-xs font-semibold tracking-widest uppercase">
          Infinite-ROI deal — refi recovers all cash invested
        </p>
      )}
    </div>
  );
}
