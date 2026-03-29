import type { Metadata } from 'next';
import {
  ArrowDown,
  MegaphoneSimple,
  Phone,
} from '@phosphor-icons/react/dist/ssr';
import PropertyEvaluator from '@/components/seller/PropertyEvaluator';
import SellerSteps from '@/components/seller/SellerSteps';
import StagingChecklist from '@/components/seller/StagingChecklist';
import ReviewCard from '@/components/shared/ReviewCard';
import CTAButton from '@/components/shared/CTAButton';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';
import LeadCaptureForm from '@/components/shared/LeadCaptureForm';

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
  'Homes.com Ads',
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
  {
    quote:
      'Brandon helped my husband and me buy our dream home, and we\'re so grateful for him. The property was a total gem — and super competitive — but he guided us through it all with confidence and ease. His communication was always clear and timely, and he answered every single question we had.',
    author: 'Yasmine Turco',
    location: 'Facebook',
    rating: 5,
  },
  {
    quote:
      'From start to finish, the process with Brandon was smooth and as worry-free as it could possibly be. Always having answers to questions, scheduling showings quickly and being responsive to anything that came up. Just an overall A+++ experience.',
    author: 'Dan Emond',
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

      {/* ── MARKETING CHANNELS — YOUR HOME, EVERYWHERE ── */}
      <section className="relative bg-dark-card py-24 md:py-28 overflow-hidden">
        <HalftoneOverlay opacity={0.02} />

        <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12">
          {/* Section header */}
          <div className="mb-12">
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
            <p className="text-white/50 text-sm font-light leading-relaxed max-w-xl">
              Brandon markets every listing across 15+ channels simultaneously — digital, print,
              and in-person — ensuring maximum buyer exposure from day one.
            </p>
          </div>

          {/* Visual: listing mockup + channel grid */}
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.6fr] gap-12 items-center">

            {/* Left: listing card mockup */}
            <div className="glass border border-dark-border rounded-xl overflow-hidden">
              {/* Mock browser bar */}
              <div className="bg-dark-surface border-b border-dark-border px-4 py-3 flex items-center gap-2">
                <div className="flex gap-1.5">
                  <span className="w-3 h-3 rounded-full bg-red-500/50" />
                  <span className="w-3 h-3 rounded-full bg-yellow-500/50" />
                  <span className="w-3 h-3 rounded-full bg-green-500/50" />
                </div>
                <div className="flex-1 mx-4 bg-dark-card rounded px-3 py-1">
                  <span className="text-white/30 text-xs font-mono">soldwithsweeney.com/listing</span>
                </div>
              </div>
              {/* Mock listing content */}
              <div className="p-5">
                <div className="aspect-[16/9] bg-dark-surface rounded-lg mb-4 overflow-hidden relative">
                  <div
                    className="absolute inset-0"
                    style={{
                      background: 'linear-gradient(135deg, rgba(234,196,105,0.05) 0%, rgba(10,10,10,0.8) 100%)',
                      backgroundImage: 'url(/frames/frame_001.webp)',
                      backgroundSize: 'cover',
                      backgroundPosition: 'center',
                      opacity: 0.6,
                    }}
                  />
                  <div className="absolute bottom-3 left-3">
                    <span className="bg-gold text-[#0a0a0a] text-xs font-black px-3 py-1 uppercase tracking-wider">Listed</span>
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="h-4 bg-dark-surface rounded w-3/4" />
                  <div className="h-3 bg-dark-surface rounded w-1/2" />
                  <div className="flex gap-2 mt-3">
                    <div className="h-6 bg-gold/20 border border-gold/30 rounded px-3 w-20" />
                    <div className="h-6 bg-dark-surface rounded px-3 w-16" />
                  </div>
                </div>
              </div>
              {/* Broadcast arrow indicator */}
              <div className="px-5 pb-5 flex items-center gap-2">
                <MegaphoneSimple weight="fill" className="w-4 h-4 text-gold flex-shrink-0" />
                <span className="text-gold text-xs font-semibold tracking-widest uppercase">Broadcasting to {MARKETING_CHANNELS.length} channels</span>
              </div>
            </div>

            {/* Right: channel grid */}
            <div className="flex flex-wrap gap-2.5">
              {MARKETING_CHANNELS.map((channel) => (
                <div
                  key={channel}
                  className="flex items-center gap-2 px-4 py-3 border border-dark-border bg-dark-surface text-white/70 text-xs font-semibold tracking-widest uppercase hover:border-gold/40 hover:text-white/90 hover:bg-gold/5 transition-colors duration-200"
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
                Let&apos;s Get Your{' '}
                <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}>
                  Home Sold
                </span>
              </h2>
              <p className="text-gray text-sm leading-relaxed mb-8 max-w-md">
                Fill out the form and Brandon will reach out to schedule your free home valuation
                meeting. No pressure — just a straight conversation about your goals.
              </p>

              {/* Phone CTA */}
              <a
                href="tel:9789872806"
                className="inline-flex items-center gap-3 text-gold hover:text-white transition-colors duration-200 group"
              >
                <span className="w-10 h-10 flex items-center justify-center border border-gold/40 group-hover:border-gold/80 transition-colors duration-200">
                  <Phone weight="bold" className="w-4 h-4" />
                </span>
                <div>
                  <p className="text-xs text-gray uppercase tracking-widest font-medium">Call Direct</p>
                  <p className="font-bold tracking-wide">(978) 987-2806</p>
                </div>
              </a>
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
          AI valuation tool provides an estimate only and is not a formal appraisal. Actual sale price may
          vary based on market conditions, property condition, and other factors. Equal Housing Opportunity.
          Information deemed reliable but not guaranteed.
        </p>
      </section>
    </>
  );
}
