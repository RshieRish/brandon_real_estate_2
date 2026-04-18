import type { Metadata } from 'next';
import {
  ArrowDown,
  Phone,
  ChatCircleText,
  EnvelopeSimple,
} from '@phosphor-icons/react/dist/ssr';
import PropertyEvaluator from '@/components/seller/PropertyEvaluator';
import SellerSteps from '@/components/seller/SellerSteps';
import StagingChecklist from '@/components/seller/StagingChecklist';
import ReviewCard from '@/components/shared/ReviewCard';
import CTAButton from '@/components/shared/CTAButton';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';
import LeadCaptureForm from '@/components/shared/LeadCaptureForm';
import MarketingSphere from '@/components/sell/MarketingSphere';
export const metadata: Metadata = {
  title: 'Sell Your Home | Brandon Sweeney, REALTOR\u00ae | Sold With Sweeney & Co.',
  description:
    'Get a free market-based home valuation and work with award-winning REALTOR\u00ae Brandon Sweeney to sell your home faster, for more money.',
};


const SELLER_REVIEWS = [
  {
    quote:
      "Brandon did a phenomenal job in helping me sell my parents' home. He kept me informed at all times and was always available to answer any questions I had. He got the house listed and sold so quickly at a great price. I definitely would recommend Brandon to anyone looking to sell their home.",
    author: 'Jeannine R.',
    location: 'Realtor.com',
    rating: 5,
  },
  {
    quote:
      "I had the pleasure of working with Brandon to sell my Dad's home and I couldn't be happier with the experience. From our first meeting until the closing Brandon was professional, knowledgeable, and incredibly responsive. He went above and beyond to showcase my Dad's home using top-notch photography and marketing. He secured a fantastic offer that fully exceeded my expectations. I highly recommend him.",
    author: 'Melissa Simon',
    location: 'Google',
    rating: 5,
  },
  {
    quote:
      'Brandon is a true professional. He got me a great price for my house. He is honest and trustworthy. A real straight shooter. He made the process very easy — everything was explained and there were no surprises except that he got me more for my house than I expected. I highly recommend him to anyone looking to sell their home.',
    author: 'John Murphy',
    location: 'Facebook',
    rating: 5,
  },
  {
    quote:
      'After having a less than pleasant experience with a previous agent, when we decided to sell we knew we wanted to work with an experienced professional. From the first call with Brandon, we felt so much confidence that he knew what he was doing and was going to do what was best for us. The entire process was made seamless — he was extremely communicative and explained every step very clearly.',
    author: 'Zoe DiSabito',
    location: 'Google',
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
          src="/videos/sell_hero.mp4"
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
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-16 items-center">
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
                market-based home valuation below.
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

            {/* Right stat block — 2×2 glass grid matching invest page style */}
            <div className="hidden lg:grid grid-cols-2 gap-4 shrink-0">
              {[
                { label: 'Families Served', value: '100+' },
                { label: 'Avg. Rating', value: '5.0★' },
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

      {/* ── PROPERTY EVALUATOR ── */}
      <section id="evaluator" className="relative bg-dark-card py-24 md:py-32 overflow-hidden">
        <HalftoneOverlay opacity={0.025} />

        <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
          {/* Section header */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 mb-12">
            <div>
              <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
                Free Market Valuation
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
                This valuation model uses local pricing baselines, property specifics, and
                market-standard adjustments to give you a realistic starting range in seconds.
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

      {/* ── MARKETING CHANNELS — YOUR HOME, EVERYWHERE ── */}
      <section className="relative bg-[#0a0a0a] overflow-hidden w-full">
        <HalftoneOverlay opacity={0.02} />
        <MarketingSphere />
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
      <section className="relative py-24 px-6 md:px-12 bg-dark-card overflow-hidden">
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
                Ready to Sell?
              </span>
              <h2
                className="font-black text-white leading-tight tracking-tight mb-6"
                style={{ fontSize: 'clamp(1.75rem, 4.5vw, 3rem)' }}
              >
                Stop Listing.{' '}
                <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}>
                  Start Moving.
                </span>
              </h2>
              <p className="text-gray text-sm leading-relaxed mb-8 max-w-md">
                Fill out the form and Brandon will reach out to schedule your free home valuation
                meeting. No pressure — just a straight conversation about your goals.
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
                  href="mailto:brandon@soldwithsweeney.com"
                  className="inline-flex items-center gap-3 text-gold hover:text-white transition-colors duration-200 group"
                >
                  <span className="w-10 h-10 flex items-center justify-center border border-gold/40 group-hover:border-gold/80 transition-colors duration-200 shrink-0">
                    <EnvelopeSimple weight="bold" className="w-4 h-4" />
                  </span>
                  <div>
                    <p className="text-[10px] text-gray uppercase tracking-widest font-medium">Email</p>
                    <p className="text-sm font-bold tracking-wide">brandon@soldwithsweeney.com</p>
                  </div>
                </a>
              </div>
            </div>

            {/* Right form */}
            <div className="bg-[#0a0a0a] border border-dark-border p-8">
              <LeadCaptureForm
                source="seller-page"
                leadType="seller"
                ctaText="Book a Free Home Valuation"
              />
            </div>
          </div>
        </div>

        {/* KW Legal disclaimer */}
        <p className="relative max-w-7xl mx-auto mt-16 text-gray/50 text-xs leading-relaxed border-t border-dark-border pt-6">
          Brandon Sweeney is a licensed real estate professional with Keller Williams Realty Success. This
          market valuation tool provides an estimate only and is not a formal appraisal. Actual sale price may
          vary based on market conditions, property condition, and other factors. Equal Housing Opportunity.
          Information deemed reliable but not guaranteed.
        </p>
      </section>
    </>
  );
}
