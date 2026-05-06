import type { Metadata } from 'next';
import { fetchPublicLinkPack, imageUrl } from '@/lib/link-pack/api';
import LinkPackPage from '@/components/link-pack/LinkPackPage';
import PreviewLoader from './preview-loader';

export const dynamic = 'force-dynamic';

export async function generateMetadata(): Promise<Metadata> {
  const snap = await fetchPublicLinkPack();
  if (!snap) return { title: 'Coming soon' };
  const photo = imageUrl(snap.profile.photo_url) ?? undefined;
  return {
    title: snap.profile.name,
    description: snap.profile.bio,
    openGraph: {
      title: snap.profile.name,
      description: snap.profile.bio,
      images: photo ? [{ url: photo, width: 800, height: 800 }] : undefined,
      type: 'profile',
      url: 'https://soldwithsweeney.com/links',
    },
    twitter: {
      card: 'summary_large_image',
      title: snap.profile.name,
      description: snap.profile.bio,
      images: photo ? [photo] : undefined,
    },
    alternates: { canonical: '/links' },
    robots: { index: true, follow: true },
  };
}

interface PageProps {
  searchParams: Promise<{ preview?: string }>;
}

export default async function Page({ searchParams }: PageProps) {
  const params = await searchParams;
  if (params.preview === '1') {
    return <PreviewLoader />;
  }
  const snapshot = await fetchPublicLinkPack();
  if (!snapshot) {
    return (
      <main style={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', background: '#c78829', color: '#fff' }}>
        <p>Coming soon.</p>
      </main>
    );
  }
  const sameAs = [
    snapshot.social.instagram, snapshot.social.facebook, snapshot.social.youtube,
    snapshot.social.website, snapshot.social.tiktok, snapshot.social.x,
  ].filter((v): v is string => Boolean(v));
  const ld = {
    '@context': 'https://schema.org',
    '@type': 'Person',
    name: snapshot.profile.name,
    image: imageUrl(snapshot.profile.photo_url) ?? undefined,
    url: 'https://soldwithsweeney.com/links',
    jobTitle: 'Realtor',
    sameAs,
  };
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(ld) }} />
      <LinkPackPage snapshot={snapshot} />
    </>
  );
}
