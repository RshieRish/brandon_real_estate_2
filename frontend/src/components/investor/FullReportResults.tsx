'use client';

import { motion } from 'framer-motion';
import type { InvestorAiReport } from './report-types';

interface FullReportResultsProps {
  report: InvestorAiReport;
}

const currency = (value: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value);

function Explanation({ text }: { text: string }) {
  const paragraphs = text
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);

  return (
    <div className="space-y-3">
      {paragraphs.map((paragraph, index) => (
        <p key={`${index}-${paragraph.slice(0, 24)}`} className="text-sm text-white/72 leading-relaxed font-light">
          {paragraph}
        </p>
      ))}
    </div>
  );
}

export default function FullReportResults({ report }: FullReportResultsProps) {
  const scenarios = report.hold_scenarios ?? [];
  const exitComparison = report.exit_comparison;
  const sensitivity = report.sensitivity;

  return (
    <div className="space-y-6">
      <div className="glass border border-dark-border rounded-xl p-5">
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <span className="text-gold text-xs font-semibold tracking-[0.18em] uppercase">
            AI Deal Verdict
          </span>
          {report.verdict && (
            <span className="border border-gold/30 bg-gold/10 px-3 py-1 text-xs font-bold tracking-widest uppercase text-gold">
              {report.verdict}
            </span>
          )}
        </div>
        {report.verdict_reason && (
          <p className="text-white text-sm font-medium leading-relaxed mb-3">{report.verdict_reason}</p>
        )}
        {report.ai_explanation && <Explanation text={report.ai_explanation} />}
      </div>

      {scenarios.length > 0 && (
        <div>
          <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-3">
            Hold Scenarios
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {scenarios.map((scenario) => (
              <motion.div
                key={scenario.years}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: 'spring', stiffness: 100, damping: 20 }}
                className="glass border border-dark-border rounded-xl p-4 space-y-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-white text-sm font-semibold">{scenario.years}-Year View</span>
                  <span className="text-white/40 text-xs uppercase tracking-widest">Projected</span>
                </div>
                <div className="grid grid-cols-1 gap-2 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-white/45">Equity Built</span>
                    <span className="text-white font-semibold">{currency(scenario.equity)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-white/45">Cumulative Cash Flow</span>
                    <span className="text-white font-semibold">{currency(scenario.cumulative_cash_flow)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-white/45">Projected Exit Value</span>
                    <span className="text-gold font-semibold">{currency(scenario.exit_value)}</span>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      )}

      {exitComparison && (
        <div>
          <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-3">
            Exit Paths
          </p>
          <div className="grid grid-cols-1 gap-3">
            {[
              { title: 'Sell', body: exitComparison.sell },
              { title: 'Refinance & Hold', body: exitComparison.refinance },
              { title: '1031 Exchange', body: exitComparison.exchange_1031 },
            ]
              .filter((item) => item.body)
              .map((item) => (
                <div key={item.title} className="glass border border-dark-border rounded-xl p-4">
                  <p className="text-white font-semibold text-sm mb-2">{item.title}</p>
                  <p className="text-white/68 text-sm font-light leading-relaxed">{item.body}</p>
                </div>
              ))}
          </div>
        </div>
      )}

      {sensitivity && (
        <div>
          <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-3">
            Stress Test
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {[
              {
                label: 'Taxes +10%',
                value: sensitivity.tax_increase_10pct,
              },
              {
                label: 'Vacancy at 10%',
                value: sensitivity.vacancy_10pct,
              },
              {
                label: 'Rents -5%',
                value: sensitivity.rent_drop_5pct,
              },
            ]
              .filter((item) => typeof item.value === 'number')
              .map((item) => (
                <div key={item.label} className="glass border border-dark-border rounded-xl p-4">
                  <p className="text-white/45 text-xs uppercase tracking-widest mb-2">{item.label}</p>
                  <p className="text-white text-lg font-black">{currency(item.value ?? 0)}</p>
                </div>
              ))}
          </div>
        </div>
      )}

      {report.disclaimer && (
        <div className="mt-10 pt-6 border-t border-white/10">
          <p className="text-white/50 text-xs leading-relaxed whitespace-pre-line">
            {report.disclaimer}
          </p>
        </div>
      )}
    </div>
  );
}
