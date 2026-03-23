import type { Metadata } from 'next';
import {
  ArrowDown,
  MegaphoneSimple,
} from '@phosphor-icons/react/dist/ssr';
import PropertyEvaluator from '@/components/seller/PropertyEvaluator';
import SellerSteps from '@/components/seller/SellerSteps';
import StagingChecklist from '@/components/seller/StagingChecklist';
import ReviewCard from '@/components/shared/ReviewCard';
import CTAButton from '@/components/shared/CTAButton';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';

export const metadata: Metadata = {
  title: 'Sell Your Home | Brandon Sweeney, REALTOR\u00ae | Sold With Sweeney & Co.',
  description:
    'Get a free AI-powered home valuation and work with award-winning REALTOR\u00ae Brandon Sweeney to sell your home faster, for more money.',
};

const MARKETING_CHANNELS = [
  'MLS',
  'Zillow',
  'Realtor.com',
  'Trulia',
  'Facebook',
  'Instagram',
  'LinkedIn',
  'Local Groups',
  'Email Marketing',
  'Open Houses',
  'Video Marketing',
  'Adwerx Digital Ads',
  'Professional Flyers',
  'Signage',
  'Networking',
];

const SELLER_REVIEWS = [
  {
    quote:
      "Brandon did a phenomenal job in helping me sell my parents' home. He kept me informed at all times and was always available to answer any questions I had. He got the house listed and sold so quickly at a great price which was very important to me and my family. I definitely would recommend Brandon to anyone looking to sell their home.",
    author: 'Jeannine R.',
    location: 'Zillow',
    rating: 5,
  },
  {
    quote:
      "Brandon was fantastic. He was so patient, very responsive and so knowledgeable. He works where he grew up so he knows all about the area and the market. He answered all of my questions thoroughly and made me feel comfortable with the entire process. I knew I was in good hands working with him.",
    author: 'Sonya Reagan',
    location: 'RealSatisfied',
    rating: 5,
  },
];

export default function SellPage() {
  return (
    <>
      {/* ── HERO ── */}
      <section className="relative min-h-[100dvh] flex flex-col justify-center overflow-hidden bg-dark-surface">
        {/* Background video */}
        <video
          className="absolute inset-0 w-full h-full object-cover"
          src="/assets/black_gold.mp4"
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

        {/* Gold accent bar */}
        <div
          className="absolute left-0 top-0 bottom-0 w-1"
          style={{ background: 'linear-gradient(to bottom, transparent, #eac469 30%, #eac469 70%, transparent)' }}
          aria-hidden="true"
        />

        <div className="relative z-10 w-full max-w-7xl mx-auto px-6 md:px-12 pt-24 pb-32">
          <div className="max-w-3xl">
            {/* Eyebrow */}
            <div className="mb-6">
              <span className="inline-block glass border border-gold/30 text-gold text-xs font-semibold tracking-widest uppercase px-4 py-2">
                For Sellers
              </span>
            </div>

            {/* H1 */}
            <h1
              className="font-black text-white leading-[0.95] tracking-tight mb-6"
              style={{ fontSize: 'clamp(2.8rem, 7vw, 5.5rem)' }}
            >
              Sell With{' '}
              <span
                className="text-gold relative"
                style={{ textShadow: '0 0 50px rgba(234,196,105,0.35)' }}
              >
                Peace of Mind
              </span>
            </h1>

            {/* Subtext */}
            <p className="text-white/70 text-base md:text-lg leading-relaxed mb-10 max-w-2xl font-light">
              Brandon Sweeney combines cutting-edge marketing, expert negotiation, and white-glove
              service to get your home sold fast — and for top dollar. Start with a free,
              AI-powered home valuation below.
            </p>

            {/* CTA */}
            <div className="flex flex-wrap gap-4 items-center">
              <CTAButton href="#evaluator" variant="gold">
                Get Your Free Home Estimate
                <ArrowDown weight="bold" className="w-4 h-4" />
              </CTAButton>
              <CTAButton href="tel:9789872806" external variant="outline">
                Call Brandon Directly
              </CTAButton>
            </div>
          </div>
        </div>

        {/* Scroll nudge */}
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-2 pointer-events-none">
          <span className="text-white/30 text-xs tracking-[0.2em] uppercase font-medium">Scroll</span>
          <ArrowDown weight="light" className="w-5 h-5 text-gold/50 animate-bounce" />
        </div>
      </section>

      {/* ── PROPERTY EVALUATOR ── */}
      <section id="evaluator" className="relative bg-dark-card py-24 md:py-32 overflow-hidden">
        <HalftoneOverlay opacity={0.025} />

        <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
          {/* Section header */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 mb-12">
            <div>
              <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
                Free AI Valuation
              </p>
              <h2
                className="font-black text-white leading-tight tracking-tight"
                style={{ fontSize: 'clamp(1.8rem, 3.5vw, 3rem)' }}
              >
                What Is Your Home{' '}
                <span className="text-gold" style={{ textShadow: '0 0 28px rgba(234,196,105,0.25)' }}>
                  Worth?
                </span>
              </h2>
            </div>
            <div className="flex items-end">
              <p className="text-white/50 text-sm font-light leading-relaxed">
                Our AI analyzes comparable sales, market trends, and property-specific factors to
                give you an accurate price range in seconds — no obligation required.
              </p>
            </div>
          </div>

          {/* Evaluator card */}
          <div className="glass border border-dark-border rounded-xl p-6 md:p-10">
            <PropertyEvaluator />
          </div>
        </div>
      </section>

      {/* ── SELLER STEPS ── */}
      <SellerSteps />

      {/* ── MARKETING CHANNELS ── */}
      <section className="relative bg-dark-card py-24 md:py-28 overflow-hidden">
        <HalftoneOverlay opacity={0.02} />

        <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_2fr] gap-12 items-start">
            <div>
              <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
                Maximum Exposure
              </p>
              <h2
                className="font-black text-white leading-tight tracking-tight mb-4"
                style={{ fontSize: 'clamp(1.8rem, 3vw, 2.8rem)' }}
              >
                Your Home,{' '}
                <span className="text-gold" style={{ textShadow: '0 0 28px rgba(234,196,105,0.25)' }}>
                  Everywhere
                </span>
              </h2>
              <p className="text-white/50 text-sm font-light leading-relaxed">
                Brandon markets every listing across 15+ channels simultaneously — digital, print,
                and in-person — ensuring maximum buyer exposure.
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              {MARKETING_CHANNELS.map((channel, index) => (
                <div
                  key={channel}
                  className="flex items-center gap-2 px-4 py-2.5 border border-dark-border bg-dark-surface text-white/70 text-xs font-semibold tracking-widest uppercase"
                  style={{
                    animationDelay: `${index * 0.05}s`,
                  }}
                >
                  <MegaphoneSimple weight="fill" className="w-3.5 h-3.5 text-gold flex-shrink-0" />
                  {channel}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── STAGING CHECKLIST ── */}
      <StagingChecklist />

      {/* ── SELLER REVIEWS ── */}
      <section className="relative bg-dark-surface py-24 md:py-32 overflow-hidden">
        <HalftoneOverlay opacity={0.025} />

        <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
          <div className="mb-12">
            <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
              What Sellers Say
            </p>
            <h2
              className="font-black text-white leading-tight tracking-tight"
              style={{ fontSize: 'clamp(1.8rem, 3.5vw, 3rem)' }}
            >
              Real Results,{' '}
              <span className="text-gold" style={{ textShadow: '0 0 28px rgba(234,196,105,0.25)' }}>
                Real Clients
              </span>
            </h2>
          </div>

          {/* 2×2 review grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {SELLER_REVIEWS.map((review) => (
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
      <section className="relative bg-dark-card py-24 md:py-32 overflow-hidden">
        {/* Gold gradient sweep */}
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
            Ready to Sell?
          </p>
          <h2
            className="font-black text-white leading-tight tracking-tight mb-6"
            style={{ fontSize: 'clamp(2rem, 4vw, 3.5rem)' }}
          >
            Ready to Get Started?
          </h2>
          <p className="text-white/60 text-base font-light leading-relaxed mb-10 max-w-xl mx-auto">
            Schedule a free home valuation meeting with Brandon. No pressure, no obligation — just
            a clear plan to get your home sold.
          </p>

          <div className="flex flex-wrap gap-4 justify-center">
            <CTAButton href="#evaluator" variant="gold">
              Get Your Free Estimate
            </CTAButton>
            <CTAButton href="tel:9789872806" external variant="outline">
              Call (978) 987-2806
            </CTAButton>
          </div>

          {/* KW Legal Disclaimer */}
          <p className="text-white/20 text-xs font-light mt-12 leading-relaxed max-w-2xl mx-auto">
            Brandon Sweeney is a licensed REALTOR&#174; with Keller Williams Realty Success. This
            AI valuation tool provides an estimate only and is not a formal appraisal. Actual sale
            price may vary based on market conditions, property condition, and other factors. Equal
            Housing Opportunity. &copy; {new Date().getFullYear()} Sold With Sweeney &amp; Co. All
            rights reserved. Keller Williams Realty, Inc. is not responsible for the accuracy of
            third-party data.
          </p>
        </div>
      </section>
    </>
  );
}
