import type { Metadata } from 'next';
import { ArrowDown, Phone } from '@phosphor-icons/react/dist/ssr';
import CTAButton from '@/components/shared/CTAButton';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';
import ReviewCard from '@/components/shared/ReviewCard';
import LeadCaptureForm from '@/components/shared/LeadCaptureForm';
import TheProcess from '@/components/home/TheProcess';
import BuyerMistakes from '@/components/buyer/BuyerMistakes';

export const metadata: Metadata = {
  title: 'Home Buying 101 | Sold With Sweeney & Co.',
  description:
    'Ready to buy a home in MA or NH? Brandon Sweeney, REALTOR\u00ae, guides buyers through every step — from pre-approval to closing. Book a free strategy call.',
};

const TEAM_MEMBERS = [
  'Your REALTOR\u00ae (Brandon)',
  'Lender / Loan Officer',
  'Real Estate Attorney',
  'Estate Planning Attorney',
  'Insurance Agent',
  'Financial Advisor',
  'Accountant',
];

const REVIEWS = [
  {
    author: 'Yasmine Turco',
    location: 'Facebook',
    quote:
      "Brandon helped my husband and me buy our dream home, and we're so grateful for him. The property was a total gem—and super competitive—but he guided us through it all with confidence and ease. His communication was always clear and timely, and he answered every single question we had (and we had a lot!). Brandon is not only a great negotiator, but also just a kind, down-to-earth person who makes a stressful process feel manageable.",
    rating: 5 as const,
  },
  {
    author: 'Dan Emond',
    location: 'Google',
    quote:
      "From start to finish, the homebuying process from Brandon was smooth and as worry-free as it could have possibly been for a pair of first-time homebuyers. Always having answers to questions, scheduling showings quickly and being responsive to anything that came up. Just an overall A+++ experience.",
    rating: 5 as const,
  },
  {
    author: 'Matt Perez',
    location: 'Facebook',
    quote:
      "Working with Brandon was a fantastic process. Everything was spelt out and very digestible from our very first meeting on. As first time home buyers, there were so many unknowns for us and Brandon took the time to make sure we were comfortable every step of the way. Highly recommend.",
    rating: 5 as const,
  },
  {
    author: 'Gabriel Reyes',
    location: 'Facebook',
    quote:
      "Just closed on our first home with Brandon and although it wasn't easy, it wouldn't have been possible without him. If you're looking to buy a home in this crazy market he is your guy!",
    rating: 5 as const,
  },
];

export default function BuyPage() {
  return (
    <>
      {/* ── Hero ─────────────────────────────────────────────────────── */}
      <section className="relative min-h-[100dvh] flex flex-col justify-center overflow-hidden bg-[#0a0a0a]">
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

        {/* Gradient overlay */}
        <div
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(105deg, rgba(10,10,10,0.97) 0%, rgba(10,10,10,0.82) 50%, rgba(10,10,10,0.45) 100%)',
          }}
          aria-hidden="true"
        />

        <HalftoneOverlay opacity={0.04} />

        {/* Gold accent line — left edge */}
        <div
          className="absolute left-0 top-0 bottom-0 w-1 bg-gold"
          style={{ boxShadow: '0 0 40px rgba(234,196,105,0.5)' }}
          aria-hidden="true"
        />

        <div className="relative z-10 w-full max-w-7xl mx-auto px-6 md:px-12 pt-20 pb-32">
          {/* Asymmetric split: large left text, right accent block */}
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-16 items-center">
            <div className="max-w-2xl">
              {/* Eyebrow */}
              <span className="inline-block border border-gold/40 text-gold text-xs font-semibold tracking-widest uppercase px-4 py-2 mb-6">
                For Buyers
              </span>

              {/* H1 */}
              <h1
                className="font-black text-white leading-[0.95] tracking-tight mb-6"
                style={{ fontSize: 'clamp(3rem, 8vw, 6.5rem)' }}
              >
                Home Buying{' '}
                <span
                  className="text-gold block"
                  style={{ textShadow: '0 0 48px rgba(234,196,105,0.4)' }}
                >
                  101
                </span>
              </h1>

              <p className="text-white/65 text-base md:text-lg leading-relaxed mb-10 max-w-xl font-light">
                Buying a home is the biggest financial decision of your life. Brandon Sweeney,
                REALTOR&#174;, takes you from pre-approval to closing — protecting your interests
                every step of the way in MA &amp; NH.
              </p>

              <CTAButton
                href="tel:9789872806"
                external
                variant="gold"
                className="gap-3"
              >
                <Phone weight="bold" className="w-4 h-4" />
                Book a Strategy Call
              </CTAButton>

              <div className="mt-5">
                <a
                  href="#find-the-one"
                  className="inline-flex items-center gap-2 text-gold text-sm font-semibold tracking-[0.18em] uppercase hover:text-white transition-colors duration-200"
                >
                  Find &quot;THE ONE&quot;
                  <ArrowDown weight="bold" className="w-4 h-4" />
                </a>
              </div>
            </div>

            {/* Right stat block — 2×2 glass grid */}
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
      </section>

      {/* ── The Process (accordion) ─────────────────────────────── */}
      <TheProcess />

      {/* ── Winning Home Buying Team ──────────────────────────────────── */}
      <section className="relative py-24 px-6 md:px-12 bg-[#0a0a0a] overflow-hidden">
        <HalftoneOverlay opacity={0.03} />

        <div className="relative max-w-7xl mx-auto">
          {/* Asymmetric header */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-start mb-14">
            <div>
              <span className="inline-block border border-gold/30 text-gold text-xs font-semibold tracking-widest uppercase px-3 py-1 mb-5">
                Your Power Team
              </span>
              <h2
                className="font-black text-white leading-tight tracking-tight"
                style={{ fontSize: 'clamp(1.75rem, 4.5vw, 3rem)' }}
              >
                The Winning Home{' '}
                <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}>
                  Buying Team
                </span>
              </h2>
            </div>
            <p className="text-gray text-sm leading-relaxed lg:pt-16">
              Buying a home isn&apos;t a solo mission. The most successful buyers build a team of
              trusted professionals — and Brandon helps connect you with every one of them.
            </p>
          </div>

          {/* Team grid: 4 on first row, 3 on second row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {TEAM_MEMBERS.slice(0, 4).map((member) => (
              <span
                key={member}
                className="flex items-center justify-center text-center px-4 py-4 border border-gold/30 text-gold text-sm font-semibold tracking-wide bg-dark-card hover:border-gold/70 hover:bg-gold/5 transition-colors duration-200 min-h-[64px]"
              >
                {member}
              </span>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-3 mt-3">
            {TEAM_MEMBERS.slice(4).map((member) => (
              <span
                key={member}
                className="flex items-center justify-center text-center px-4 py-4 border border-gold/30 text-gold text-sm font-semibold tracking-wide bg-dark-card hover:border-gold/70 hover:bg-gold/5 transition-colors duration-200 min-h-[64px]"
              >
                {member}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ── Buyer Mistakes ───────────────────────────────────────────── */}
      <BuyerMistakes />

      {/* ── Reviews 2×2 ─────────────────────────────────────────────── */}
      <section className="relative py-24 px-6 md:px-12 bg-[#0a0a0a]">
        <HalftoneOverlay opacity={0.035} />

        <div className="relative max-w-7xl mx-auto">
          <div className="mb-12">
            <span className="inline-block border border-gold/30 text-gold text-xs font-semibold tracking-widest uppercase px-3 py-1 mb-4">
              Client Stories
            </span>
            <h2
              className="font-black text-white leading-tight tracking-tight"
              style={{ fontSize: 'clamp(1.75rem, 4.5vw, 3rem)' }}
            >
              Buyers Who Won With{' '}
              <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}>
                Brandon
              </span>
            </h2>
          </div>

          {/* 2×2 grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            {REVIEWS.map((review) => (
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

      {/* ── Lead Capture ─────────────────────────────────────────────── */}
      <section id="find-the-one" className="relative py-24 px-6 md:px-12 bg-dark-card overflow-hidden">
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
                Ready to Start?
              </span>
              <h2
                className="font-black text-white leading-tight tracking-tight mb-6"
                style={{ fontSize: 'clamp(1.75rem, 4.5vw, 3rem)' }}
              >
                Let&apos;s Find Your{' '}
                <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}>
                  THE ONE
                </span>
              </h2>
              <p className="text-gray text-sm leading-relaxed mb-8 max-w-md">
                Fill out the form and Brandon will reach out to schedule your free buyer strategy
                call. No pressure — just a straight conversation about your goals.
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
                source="buyer-page"
                leadType="buyer"
                ctaText="Book a Buyer Strategy Call"
              />
            </div>
          </div>
        </div>

        {/* KW Legal disclaimer */}
        <p className="relative max-w-7xl mx-auto mt-16 text-gray/50 text-xs leading-relaxed border-t border-dark-border pt-6">
          Brandon Sweeney is a licensed real estate professional with Keller Williams Realty Success. All real
          estate services are subject to applicable state law and Keller Williams Realty
          International&apos;s policies. Equal Housing Opportunity. Information deemed reliable but
          not guaranteed.
        </p>
      </section>
    </>
  );
}
