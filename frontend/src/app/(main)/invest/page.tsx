import type { Metadata } from 'next';
import {
  ArrowDown,
  Phone,
  ChatCircleText,
  EnvelopeSimple,
} from '@phosphor-icons/react/dist/ssr';
import InvestorCalculator from '@/components/investor/InvestorCalculator';
import FlipCaseStudy from '@/components/investor/FlipCaseStudy';
import ReviewCard from '@/components/shared/ReviewCard';
import CTAButton from '@/components/shared/CTAButton';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';
import LeadCaptureForm from '@/components/shared/LeadCaptureForm';

export const metadata: Metadata = {
  title: 'Invest in Real Estate | Brandon Sweeney, REALTOR\u00ae | Sold With Sweeney & Co.',
  description:
    'Analyze investment deals with a free calculator and work with REALTOR\u00ae Brandon Sweeney to find, evaluate, and close profitable properties in MA and NH.',
};

const INVESTOR_REVIEWS = [
  {
    quote:
      "Brandon helped my husband and me buy our dream home, and we're so grateful for him. The property was a total gem—and super competitive—but he guided us through it all with confidence and ease. His communication was always clear and timely, and he answered every single question we had (and we had a lot!). Brandon is not only a great negotiator, but also just a kind, down-to-earth person who makes a stressful process feel manageable.",
    author: 'Yasmine Turco',
    location: 'Facebook',
    rating: 5,
  },
  {
    quote:
      "From start to finish, the homebuying process from Brandon was smooth and as worry-free as it could have possibly been. Always having answers to questions, scheduling showings quickly and being responsive to anything that came up. Just an overall A+++ experience.",
    author: 'Dan Emond',
    location: 'Google',
    rating: 5,
  },
  {
    quote:
      "Brandon was excellent as an agent and a knowledgeable resource. He understood my needs when looking for an investment property and was creative in tracking down new leads, often forwarding me properties he found via unconventional sources. I highly recommend him!",
    author: 'Leominster Buyer',
    location: 'RealSatisfied',
    rating: 5,
  },
  {
    quote:
      "Having worked with Brandon on previous sales he again exceeded our expectations. This time he used the most innovative marketing techniques I've ever seen. Results count — it worked! Excellent experience, excellent results. Highly recommend Brandon and the Sold with Sweeney Team.",
    author: 'Paulette Geoffroy',
    location: 'RealSatisfied',
    rating: 5,
  },
];

export default function InvestPage() {
  return (
    <>
      {/* ── HERO ── */}
      <section className="relative min-h-[100dvh] flex flex-col justify-center overflow-hidden bg-dark-surface">
        {/* Background video */}
        <video
          className="absolute inset-0 w-full h-full object-cover"
          src="/videos/invest_hero.mp4"
          autoPlay
          muted
          loop
          playsInline
          aria-hidden="true"
        />

        {/* Gradient sweep */}
        <div
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(105deg, rgba(10,10,10,0.97) 0%, rgba(10,10,10,0.82) 50%, rgba(10,10,10,0.45) 100%)',
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
                BRRRR — run the numbers in seconds below. Start with a{' '}
                <span className="text-gold font-semibold">FREE AI DEAL EVALUATOR</span> below.
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
                { label: 'Investors Created', value: '50+' },
                { label: 'Markets', value: 'MA & NH' },
                { label: 'Years Active', value: '10+' },
                { label: 'Avg. Rating', value: '5.0★' },
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


      </section>

      {/* ── CALCULATOR ── */}
      <section id="calculator" className="relative bg-dark-card py-24 md:py-32 overflow-hidden">
        <HalftoneOverlay opacity={0.025} />

        <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
          {/* Section header */}
          <div className="mb-10 flex flex-col md:flex-row md:items-end md:justify-between gap-6">
            <div>
              <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-3">
                Free AI Deal Evaluator
              </p>
              <h2
                className="font-black text-white leading-tight tracking-tight"
                style={{ fontSize: 'clamp(1.8rem, 3.5vw, 3rem)' }}
              >
                Deal{' '}
                <span className="text-gold" style={{ textShadow: '0 0 28px rgba(234,196,105,0.25)' }}>
                  Analyzer
                </span>
              </h2>
            </div>
            <p className="text-white/50 text-sm font-light max-w-sm md:text-right">
              Run the numbers in seconds using our AI analyzer. Calculate flip profit, cash-on-cash return, cap rate, and more. AI-assisted estimates — not a formal appraisal.
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
                Brandon has a proven record helping investors execute profitable deals in
                Northern Massachusetts and Southern New Hampshire. Here is one real example.
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

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
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

      {/* ── LEAD CAPTURE ── */}
      <section className="relative py-24 px-6 md:px-12 bg-dark-surface overflow-hidden">
        {/* Gold glow top */}
        <div
          className="absolute top-0 left-1/2 -translate-x-1/2 w-96 h-px"
          style={{ background: 'linear-gradient(90deg, transparent, rgba(234,196,105,0.6), transparent)' }}
          aria-hidden="true"
        />
        <HalftoneOverlay opacity={0.03} />

        <div className="relative max-w-7xl mx-auto">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-start">
            {/* Left copy */}
            <div>
              <span className="inline-block border border-gold/30 text-gold text-xs font-semibold tracking-widest uppercase px-3 py-1 mb-6">
                Ready to Invest?
              </span>
              <h2
                className="font-black text-white leading-tight tracking-tight mb-6"
                style={{ fontSize: 'clamp(1.75rem, 4.5vw, 3rem)' }}
              >
                Find Deals.{' '}
                <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}>
                  Build Wealth.
                </span>
              </h2>
              <p className="text-gray text-sm leading-relaxed mb-8 max-w-md">
                Fill out the form and Brandon will reach out to schedule your free investor strategy
                call. Bring your deal or let him help you find one — no pressure, just numbers.
              </p>

              {/* Contact Options */}
              <div className="flex flex-col sm:flex-row flex-wrap gap-4 mt-2">
                <a
                  href="tel:9789872806"
                  className="inline-flex items-center gap-3 text-gold hover:text-white transition-colors duration-200 group"
                >
                  <span className="w-10 h-10 flex items-center justify-center border border-gold/40 group-hover:border-gold/80 transition-colors duration-200 shrink-0">
                    <Phone weight="bold" className="w-4 h-4" />
                  </span>
                  <div>
                    <p className="text-[10px] text-gray uppercase tracking-widest font-medium">Call Direct</p>
                    <p className="text-sm font-bold tracking-wide">(978) 987-2806</p>
                  </div>
                </a>
                
                <a
                  href="sms:9789872806"
                  className="inline-flex items-center gap-3 text-gold hover:text-white transition-colors duration-200 group"
                >
                  <span className="w-10 h-10 flex items-center justify-center border border-gold/40 group-hover:border-gold/80 transition-colors duration-200 shrink-0">
                    <ChatCircleText weight="bold" className="w-4 h-4" />
                  </span>
                  <div>
                    <p className="text-[10px] text-gray uppercase tracking-widest font-medium">Text Direct</p>
                    <p className="text-sm font-bold tracking-wide">(978) 987-2806</p>
                  </div>
                </a>

                <a
                  href="mailto:info@soldwithsweeney.com"
                  className="inline-flex items-center gap-3 text-gold hover:text-white transition-colors duration-200 group"
                >
                  <span className="w-10 h-10 flex items-center justify-center border border-gold/40 group-hover:border-gold/80 transition-colors duration-200 shrink-0">
                    <EnvelopeSimple weight="bold" className="w-4 h-4" />
                  </span>
                  <div>
                    <p className="text-[10px] text-gray uppercase tracking-widest font-medium">Email</p>
                    <p className="text-sm font-bold tracking-wide">info@soldwithsweeney.com</p>
                  </div>
                </a>
              </div>
            </div>

            {/* Right form */}
            <div className="bg-[#0a0a0a] border border-dark-border p-8">
              <LeadCaptureForm
                source="investor-page"
                leadType="investor"
                ctaText="Book a Free Investor Strategy Call"
              />
            </div>
          </div>
        </div>

        {/* KW Legal disclaimer */}
        <p className="relative max-w-7xl mx-auto mt-16 text-gray/50 text-xs leading-relaxed border-t border-dark-border pt-6">
          Brandon Sweeney is a licensed REALTOR<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup> with Keller Williams Realty Success. Deal
          analysis results are estimates for informational purposes only and do not constitute
          financial, legal, or investment advice. Actual returns depend on market conditions,
          financing, property condition, and other factors. Equal Housing Opportunity. &copy;{' '}
          {new Date().getFullYear()} Sold With Sweeney &amp; Co. All rights reserved. Keller
          Williams Realty, Inc. is not responsible for the accuracy of third-party data.
        </p>
      </section>
    </>
  );
}
