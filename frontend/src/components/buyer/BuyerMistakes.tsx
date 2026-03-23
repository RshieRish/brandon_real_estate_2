'use client';

import { motion } from 'framer-motion';
import { XCircle, CheckCircle, Warning } from '@phosphor-icons/react';

interface Mistake {
  id: number;
  mistake: string;
  mistakeDetail: string;
  fix: string;
}

const MISTAKES: Mistake[] = [
  {
    id: 1,
    mistake: 'Shopping before pre-approval',
    mistakeDetail:
      'Browsing homes without a pre-approval letter puts you at a severe disadvantage. Sellers and their agents won\'t take you seriously, and you risk falling in love with a home you can\'t afford.',
    fix: 'Get pre-approved before your first showing. A pre-approval letter tells sellers you\'re a serious, qualified buyer — and gives you a clear budget so you shop with confidence.',
  },
  {
    id: 2,
    mistake: 'Using all your savings for the down payment',
    mistakeDetail:
      'Draining every dollar into the down payment leaves you dangerously exposed. Closing costs, moving expenses, and unexpected repairs can arrive all at once.',
    fix: 'Budget for closing costs (2–5% of the purchase price), keep a reserves fund for immediate repairs, and factor in moving costs. A slightly lower down payment with healthy reserves is often smarter.',
  },
  {
    id: 3,
    mistake: 'Buying with the listing agent',
    mistakeDetail:
      'The listing agent\'s fiduciary duty is to the seller — not you. Working without your own representation means you\'re negotiating against someone whose job is to get the seller the highest price.',
    fix: 'Always have a dedicated buyer\'s agent representing your interests. Brandon provides exclusive buyer representation at no cost to you in most transactions — the seller pays the commission.',
  },
  {
    id: 4,
    mistake: 'Not comparing multiple lenders',
    mistakeDetail:
      'Accepting the first mortgage offer without shopping around can cost you tens of thousands over the life of the loan. Even a 0.25% rate difference makes a significant impact.',
    fix: 'Get quotes from at least 3 lenders before committing. Compare rates, fees, and loan products. Brandon has a network of trusted lenders who compete for your business.',
  },
];

const SPRING = { type: 'spring' as const, stiffness: 100, damping: 20 };

export default function BuyerMistakes() {
  return (
    <section className="relative py-24 px-6 md:px-12 bg-dark-card">
      {/* Subtle halftone */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(circle, #eac469 1px, transparent 1px)',
          backgroundSize: '24px 24px',
          opacity: 0.025,
        }}
        aria-hidden="true"
      />

      <div className="relative max-w-7xl mx-auto">
        {/* Header — asymmetric */}
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6 mb-14">
          <div className="max-w-xl">
            <div className="flex items-center gap-3 mb-4">
              <span className="text-gold text-xs font-semibold tracking-widest uppercase border border-gold/30 px-3 py-1">
                Common Mistakes
              </span>
            </div>
            <h2
              className="font-black text-white leading-tight tracking-tight"
              style={{ fontSize: 'clamp(1.75rem, 4.5vw, 3rem)' }}
            >
              What Most Buyers{' '}
              <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}>
                Get Wrong
              </span>
            </h2>
          </div>
          <p className="text-gray text-sm leading-relaxed max-w-sm md:text-right">
            Avoid the mistakes that derail most home purchases — and the cost overruns that follow.
          </p>
        </div>

        {/* Mistakes grid — 2-col on desktop */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {MISTAKES.map((item, idx) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, y: 28 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ ...SPRING, delay: idx * 0.09 }}
              className="bg-[#0a0a0a] border border-dark-border p-6 flex flex-col gap-5 hover:border-gold/20 transition-colors duration-300"
            >
              {/* Mistake */}
              <div className="flex flex-col gap-3">
                <div className="flex items-start gap-3">
                  <XCircle
                    weight="fill"
                    className="text-red-400 w-5 h-5 mt-0.5 flex-shrink-0"
                  />
                  <div>
                    <p className="text-white font-bold text-sm leading-snug">{item.mistake}</p>
                    <p className="text-gray text-xs leading-relaxed mt-1.5">{item.mistakeDetail}</p>
                  </div>
                </div>
              </div>

              {/* Divider */}
              <div className="border-t border-dark-border" />

              {/* Fix */}
              <div className="flex items-start gap-3">
                <CheckCircle
                  weight="fill"
                  className="text-gold w-5 h-5 mt-0.5 flex-shrink-0"
                />
                <div>
                  <p className="text-gold text-xs font-semibold tracking-wide uppercase mb-1">
                    The Fix
                  </p>
                  <p className="text-white/80 text-xs leading-relaxed">{item.fix}</p>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
