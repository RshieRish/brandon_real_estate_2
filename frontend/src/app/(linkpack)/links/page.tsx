import type { Metadata } from 'next';
import { fetchPublicLinkPack, imageUrl } from '@/lib/link-pack/api';
import LinkPackPage from '@/components/link-pack/LinkPackPage';

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

function buildJsonLd(snap: Awaited<ReturnType<typeof fetchPublicLinkPack>>) {
  if (!snap) return null;
  const sameAs = [
    snap.social.instagram, snap.social.facebook, snap.social.youtube,
    snap.social.website, snap.social.tiktok, snap.social.x,
  ].filter((v): v is string => Boolean(v));
  return {
    '@context': 'https://schema.org',
    '@type': 'Person',
    name: snap.profile.name,
    image: imageUrl(snap.profile.photo_url) ?? undefined,
    url: 'https://soldwithsweeney.com/links',
    jobTitle: 'Realtor',
    sameAs,
  };
}

export default async function Page() {
  const snapshot = await fetchPublicLinkPack();
  if (!snapshot) {
    return (
      <main style={{
        minHeight: '100dvh',
        display: 'grid',
        placeItems: 'center',
        background: '#c78829',
        color: '#fff',
        fontFamily: 'system-ui, sans-serif',
      }}>
        <p>Coming soon.</p>
      </main>
    );
  }
  const ld = buildJsonLd(snapshot);
  return (
    <>
      {ld && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(ld) }}
        />
      )}
      <LinkPackPage snapshot={snapshot} />
    </>
  );
}
