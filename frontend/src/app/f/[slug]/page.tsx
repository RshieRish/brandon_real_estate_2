import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import FunnelHero from '@/components/funnel/FunnelHero';
import FunnelRegistration from '@/components/funnel/FunnelRegistration';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

// getFunnel is called in both generateMetadata and FunnelPage.
// Next.js 14 App Router deduplicates fetch() calls with identical URL+cache options
// within a single request, so no double network round-trip occurs.
// If this is ever rewritten to use a non-fetch data source, introduce explicit caching.
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
    description: funnel.content?.subheadline ?? funnel.title,
  };
}

export default async function FunnelPage({ params }: Props) {
  const { slug } = await params;
  const funnel = await getFunnel(slug);
  if (!funnel) notFound();

  return (
    <>
      <FunnelHero funnel={funnel} />
      <FunnelRegistration slug={funnel.slug} ctaText={funnel.cta_text} audience={funnel.audience} />
      <section className="bg-dark-surface py-8">
        <div className="max-w-3xl mx-auto px-6 text-center">
          <p className="text-white/20 text-xs font-light leading-relaxed">
            Brandon Sweeney is a licensed REALTOR&#174; with Keller Williams Realty Success.
            Equal Housing Opportunity. &copy; {new Date().getFullYear()} Sold With Sweeney &amp; Co.
          </p>
        </div>
      </section>
    </>
  );
}
