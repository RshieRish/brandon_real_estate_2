import type { Metadata } from 'next';
import { ArrowDown } from '@phosphor-icons/react/dist/ssr';
import InvestorCalculator from '@/components/investor/InvestorCalculator';
import FlipCaseStudy from '@/components/investor/FlipCaseStudy';
import ReviewCard from '@/components/shared/ReviewCard';
import CTAButton from '@/components/shared/CTAButton';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';

export const metadata: Metadata = {
  title: 'Invest in Real Estate | Brandon Sweeney, REALTOR\u00ae | Sold With Sweeney & Co.',
  description:
    'Analyze investment deals with a free calculator and work with REALTOR\u00ae Brandon Sweeney to find, evaluate, and close profitable properties in MA and NH.',
};

const INVESTOR_REVIEWS = [
  {
    quote:
      'Brandon helped me analyze three potential rentals before I pulled the trigger on the right one. His market knowledge in the Merrimack Valley is unmatched — I cash-flow positive from day one.',
    author: 'Derek M.',
    location: 'Lawrence, MA',
    rating: 5,
  },
  {
    quote:
      'I was new to flipping and nervous about the numbers. Brandon walked me through the entire deal analysis, connected me with a great contractor, and we sold at ARV. Could not have done it without him.',
    author: 'Stephanie K.',
    location: 'Nashua, NH',
    rating: 5,
  },
];

export default function InvestPage() {
  return (
    <>
      {/* ── HERO ── */}
      <section className="relative min-h-[100dvh] flex flex-col justify-center overflow-hidden bg-dark-surface">
        {/* Gradient sweep */}
        <div
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(135deg, rgba(10,10,10,1) 0%, rgba(10,10,10,0.9) 55%, rgba(192,130,53,0.09) 100%)',
          }}
          aria-hidden="true"
        />

        <HalftoneOverlay opacity={0.03} />

        {/* Gold accent bar left */}
        <div
          className="absolute left-0 top-0 bottom-0 w-1"
          style={{
            background: 'linear-gradient(to bottom, transparent, #eac469 30%, #eac469 70%, transparent)',
          }}
          aria-hidden="true"
        />

        <div className="relative z-10 w-full max-w-7xl mx-auto px-6 md:px-12 pt-24 pb-32">
          {/* Asymmetric layout: text left, decorative right */}
          <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-12 items-center">
            <div>
              {/* Eyebrow */}
              <div className="mb-6">
                <span className="inline-block glass border border-gold/30 text-gold text-xs font-semibold tracking-widest uppercase px-4 py-2">
                  For Investors
                </span>
              </div>

              {/* H1 */}
              <h1
                className="font-black text-white leading-[0.95] tracking-tight mb-6"
                style={{ fontSize: 'clamp(2.8rem, 7vw, 5.5rem)' }}
              >
                Invest With{' '}
                <span
                  className="text-gold relative"
                  style={{ textShadow: '0 0 50px rgba(234,196,105,0.35)' }}
                >
                  Confidence
                </span>
              </h1>

              {/* Subtitle */}
              <p className="text-white/70 text-base md:text-lg leading-relaxed mb-10 max-w-2xl font-light">
                Brandon Sweeney helps investors analyze deals, identify high-return properties, and
                execute smart strategies across Massachusetts and New Hampshire. Flip, rent, or
                BRRRR — run the numbers in seconds below.
              </p>

              {/* CTAs */}
              <div className="flex flex-wrap gap-4 items-center">
                <CTAButton href="#calculator" variant="gold">
                  Analyze a Deal
                  <ArrowDown weight="bold" className="w-4 h-4" />
                </CTAButton>
                <CTAButton href="tel:9789872806" external variant="outline">
                  Call Brandon
                </CTAButton>
              </div>
            </div>

            {/* Decorative stat block */}
            <div className="hidden lg:grid grid-cols-2 gap-4">
              {[
                { label: 'Deals Closed', value: '50+' },
                { label: 'Avg. Flip ROI', value: '58%' },
                { label: 'Markets', value: 'MA & NH' },
                { label: 'Years Active', value: '10+' },
              ].map((stat) => (
                <div
                  key={stat.label}
                  className="glass border border-dark-border rounded-xl p-5 flex flex-col gap-1"
                >
                  <span className="text-white/40 text-xs font-medium tracking-widest uppercase">
                    {stat.label}
                  </span>
                  <span
                    className="font-black text-3xl text-gold"
                    style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}
                  >
                    {stat.value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Scroll nudge */}
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-2 pointer-events-none">
          <span className="text-white/30 text-xs tracking-[0.2em] uppercase font-medium">Scroll</span>
          <ArrowDown weight="light" className="w-5 h-5 text-gold/50 animate-bounce" />
        </div>
      </section>

      {/* ── CALCULATOR ── */}
      <section id="calculator" className="relative bg-dark-card py-24 md:py-32 overflow-hidden">
        <HalftoneOverlay opacity={0.025} />

        <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
          {/* Section header */}
          <div className="mb-10">
            <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-3">
              Free Tool
            </p>
            <h2
              className="font-black text-white leading-tight tracking-tight mb-3"
              style={{ fontSize: 'clamp(1.8rem, 3.5vw, 3rem)' }}
            >
              Deal{' '}
              <span className="text-gold" style={{ textShadow: '0 0 28px rgba(234,196,105,0.25)' }}>
                Analyzer
              </span>
            </h2>
            <p className="text-white/50 text-sm font-light max-w-xl">
              Instantly calculate flip profit, cash-on-cash return, cap rate, and more. Enter your
              deal numbers and unlock your full analysis in seconds.
            </p>
          </div>

          {/* Calculator card */}
          <div className="glass border border-dark-border rounded-xl p-6 md:p-10">
            <InvestorCalculator />
          </div>
        </div>
      </section>

      {/* ── CASE STUDY ── */}
      <section className="relative bg-dark-surface py-24 md:py-28 overflow-hidden">
        <HalftoneOverlay opacity={0.02} />

        <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.4fr] gap-12 items-start">
            <div>
              <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
                Track Record
              </p>
              <h2
                className="font-black text-white leading-tight tracking-tight mb-4"
                style={{ fontSize: 'clamp(1.8rem, 3vw, 2.8rem)' }}
              >
                From Our{' '}
                <span className="text-gold" style={{ textShadow: '0 0 28px rgba(234,196,105,0.25)' }}>
                  Portfolio
                </span>
              </h2>
              <p className="text-white/50 text-sm font-light leading-relaxed">
                Brandon has a proven record helping investors execute profitable deals in the
                Merrimack Valley and southern NH. Here is one real example.
              </p>
            </div>

            <FlipCaseStudy />
          </div>
        </div>
      </section>

      {/* ── INVESTOR REVIEWS ── */}
      <section className="relative bg-dark-card py-24 md:py-28 overflow-hidden">
        <HalftoneOverlay opacity={0.02} />

        <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
          <div className="mb-10">
            <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-3">
              Investor Testimonials
            </p>
            <h2
              className="font-black text-white leading-tight tracking-tight"
              style={{ fontSize: 'clamp(1.8rem, 3.5vw, 3rem)' }}
            >
              Investors Trust{' '}
              <span className="text-gold" style={{ textShadow: '0 0 28px rgba(234,196,105,0.25)' }}>
                Brandon
              </span>
            </h2>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 max-w-4xl">
            {INVESTOR_REVIEWS.map((review) => (
              <ReviewCard
                key={review.author}
                quote={review.quote}
                author={review.author}
                location={review.location}
                rating={review.rating}
              />
            ))}
          </div>
        </div>
      </section>

      {/* ── FINAL CTA ── */}
      <section className="relative bg-dark-surface py-24 md:py-32 overflow-hidden">
        {/* Gold radial glow */}
        <div
          className="absolute inset-0"
          style={{
            background:
              'radial-gradient(ellipse 80% 60% at 50% 100%, rgba(234,196,105,0.07) 0%, transparent 70%)',
          }}
          aria-hidden="true"
        />
        <HalftoneOverlay opacity={0.03} />

        <div className="relative z-10 max-w-3xl mx-auto px-6 md:px-12 text-center">
          <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
            Take Action
          </p>
          <h2
            className="font-black text-white leading-tight tracking-tight mb-6"
            style={{ fontSize: 'clamp(2rem, 4vw, 3.5rem)' }}
          >
            Ready to Find Your Next Deal?
          </h2>
          <p className="text-white/60 text-base font-light leading-relaxed mb-10 max-w-xl mx-auto">
            Schedule a free investor review call with Brandon. Bring your deal — he will help you
            run the numbers, validate your strategy, and move fast.
          </p>

          <div className="flex flex-wrap gap-4 justify-center">
            <CTAButton href="tel:9789872806" external variant="gold">
              Call (978) 987-2806
            </CTAButton>
            <CTAButton href="#calculator" variant="outline">
              Analyze a Deal
            </CTAButton>
          </div>

          {/* KW Legal Disclaimer */}
          <p className="text-white/20 text-xs font-light mt-12 leading-relaxed max-w-2xl mx-auto">
            Brandon Sweeney is a licensed REALTOR&#174; with Keller Williams Realty Success. Deal
            analysis results are estimates for informational purposes only and do not constitute
            financial, legal, or investment advice. Actual returns depend on market conditions,
            financing, property condition, and other factors. Equal Housing Opportunity. &copy;{' '}
            {new Date().getFullYear()} Sold With Sweeney &amp; Co. All rights reserved. Keller
            Williams Realty, Inc. is not responsible for the accuracy of third-party data.
          </p>
        </div>
      </section>
    </>
  );
}
