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
  if (metrics.strategy !== 'buy_hold') {
    return null; // Other strategies' result blocks added in Task 8
  }
  const { monthlyCashFlow, cashOnCashReturn, capRate, grm } = metrics;

  return (
    <div className="space-y-8">
      <div>
        <h3 className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
          Buy &amp; Hold Analysis
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
            valueColor={monthlyCashFlow < 0 ? 'text-red-400' : 'text-white'}
          />
          <MetricCard
            eyebrow="Rental"
            label="Cash-on-Cash Return"
            value={pct(cashOnCashReturn)}
            valueColor={cashOnCashReturn >= 8 ? 'text-emerald-400' : 'text-white'}
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
