'use client';

import { motion } from 'framer-motion';
import { TrendUp } from '@phosphor-icons/react';
const METRICS = [
  { label: 'Purchase Price', value: '$285,000' },
  { label: 'ARV', value: '$415,000' },
  { label: 'Rehab (TRB)', value: '$48,770' },
  { label: 'Holding Cost', value: '$14,983' },
  { label: 'Closing Cost', value: '$13,372' },
  { label: 'Net Profit', value: '$52,875' },
];

export default function FlipCaseStudy() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-60px' }}
      transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
      className="glass border border-dark-border rounded-xl overflow-hidden max-w-2xl"
    >
      {/* Gold top accent line */}
      <div className="h-1 w-full bg-gold" aria-hidden="true" />

      <div className="p-6 md:p-8">
        {/* Eyebrow */}
        <div className="flex items-center gap-3 mb-4">
          <span className="text-gold text-xs font-semibold tracking-[0.2em] uppercase">
            Real Deal
          </span>
          <TrendUp weight="fill" className="w-5 h-5 text-gold" aria-hidden="true" />
        </div>

        {/* Property name + location */}
        <h3 className="text-white font-black text-xl md:text-2xl tracking-tight mb-1">
          50 Cheever Ave
        </h3>
        <p className="text-white/50 text-sm font-light mb-6">Dracut, MA &mdash; Completed Flip</p>

        {/* Metrics grid — asymmetric 2+2+2 */}
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {METRICS.map((m, i) => (
            <motion.div
              key={m.label}
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{
                type: 'spring' as const,
                stiffness: 100,
                damping: 20,
                delay: i * 0.07,
              }}
              className="flex flex-col gap-1"
            >
              <span className="text-white/40 text-xs font-medium tracking-widest uppercase">
                {m.label}
              </span>
              <span className="text-white font-bold text-lg leading-tight">{m.value}</span>
            </motion.div>
          ))}
        </div>

        {/* Hold period callout */}
        <div className="mt-6 pt-4 border-t border-dark-border">
          <p className="text-white/40 text-xs font-light">
            Hold period: <span className="text-gold font-semibold">4 months</span>
            &nbsp;&middot;&nbsp;Exit strategy: sale at ARV
          </p>
        </div>
      </div>
    </motion.div>
  );
}
