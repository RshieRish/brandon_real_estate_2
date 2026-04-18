import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { Star, Quotes } from '@phosphor-icons/react/dist/ssr';
import FunnelHero from '@/components/funnel/FunnelHero';
import FunnelRegistration from '@/components/funnel/FunnelRegistration';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function getFunnel(slug: string) {
  try {
    const res = await fetch(`${API_URL}/api/v1/funnels/${slug}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

type Props = {
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const funnel = await getFunnel(slug);
  if (!funnel) return { title: 'Not Found' };
  return {
    title: `${funnel.title} | Sold With Sweeney & Co.`,
    description: funnel.content?.hero_subtext ?? funnel.title,
  };
}

export default async function FunnelPage({ params }: Props) {
  const { slug } = await params;
  const funnel = await getFunnel(slug);
  if (!funnel) notFound();

  const content = funnel.content ?? {};
  const valueProps: string[] = content.value_props ?? [];
  const testimonial: string | undefined = content.testimonial;

  return (
    <>
      <FunnelHero funnel={funnel} />

      {/* Social Proof Strip */}
      <section className="relative bg-[#0a0a0a] border-y border-dark-border">
        <div className="max-w-7xl mx-auto px-6 md:px-12 py-6 flex flex-wrap items-center justify-center gap-8 md:gap-16">
          <div className="flex items-center gap-2 text-white/60 text-sm font-medium tracking-wide">
            <span className="text-gold font-black text-lg">100+</span> Deals Closed
          </div>
          <div className="flex items-center gap-1 text-white/60 text-sm font-medium tracking-wide">
            <span className="text-gold font-black text-lg">5</span>
            <Star weight="fill" className="w-4 h-4 text-gold" />
            Avg. Rating
          </div>
          <div className="flex items-center gap-2 text-white/60 text-sm font-medium tracking-wide">
            <span className="text-gold font-black text-lg">2025</span> REALTOR<sup style={{ fontSize: '0.45em', verticalAlign: 'super', lineHeight: 0 }}>&reg;</sup> of the Year
          </div>
          <div className="flex items-center gap-2 text-white/60 text-sm font-medium tracking-wide">
            <span className="text-gold font-black text-lg">MA + NH</span> Markets
          </div>
        </div>
      </section>

      {/* Value Propositions */}
      {valueProps.length > 0 && (
        <section className="relative py-24 px-6 md:px-12 bg-[#0a0a0a] overflow-hidden">
          <HalftoneOverlay opacity={0.03} />
          <div className="relative max-w-7xl mx-auto">
            <div className="mb-14">
              <span className="inline-block border border-gold/30 text-gold text-xs font-semibold tracking-widest uppercase px-3 py-1 mb-5">
                What You&apos;ll Get
              </span>
              <h2
                className="font-black text-white leading-tight tracking-tight"
                style={{ fontSize: 'clamp(1.75rem, 4.5vw, 3rem)' }}
              >
                {content.details_heading ? (
                  <>
                    {content.details_heading.split(' ').slice(0, -1).join(' ')}{' '}
                    <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}>
                      {content.details_heading.split(' ').slice(-1)}
                    </span>
                  </>
                ) : (
                  <>
                    Why{' '}
                    <span className="text-gold" style={{ textShadow: '0 0 24px rgba(234,196,105,0.3)' }}>
                      Attend
                    </span>
                  </>
                )}
              </h2>
            </div>

            {/* Value prop cards — spotlight hover */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
              {valueProps.map((prop, i) => {
                const colonIdx = prop.indexOf(':');
                const title = colonIdx > -1 ? prop.slice(0, colonIdx) : `Benefit ${i + 1}`;
                const body = colonIdx > -1 ? prop.slice(colonIdx + 1).trim() : prop;

                return (
                  <div
                    key={i}
                    className="spotlight-card border border-dark-border bg-dark-card/60 backdrop-blur-sm p-8 relative"
                  >
                    <div className="relative z-10">
                      <p className="text-gold font-black text-sm tracking-widest uppercase mb-3">
                        {title}
                      </p>
                      <p className="text-white/70 text-sm leading-relaxed font-light">{body}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {/* Testimonial */}
      {testimonial && (
        <section className="relative py-20 px-6 md:px-12 bg-dark-card overflow-hidden">
          <HalftoneOverlay opacity={0.025} />
          <div className="relative max-w-3xl mx-auto text-center">
            <Quotes weight="fill" className="w-10 h-10 text-gold/30 mx-auto mb-6" />
            <blockquote className="text-white/80 text-lg md:text-xl leading-relaxed font-light italic mb-6">
              {testimonial}
            </blockquote>
            <div className="flex items-center justify-center gap-1">
              {[1, 2, 3, 4, 5].map((s) => (
                <Star key={s} weight="fill" className="w-4 h-4 text-gold" />
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Registration CTA */}
      <FunnelRegistration
        slug={funnel.slug}
        ctaText={funnel.cta_text}
        ctaHeadline={content.cta_headline}
        ctaSubtext={content.cta_subtext}
        audience={funnel.audience}
      />
    </>
  );
}
