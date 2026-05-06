import { fetchPublicLinkPack } from '@/lib/link-pack/api';
import LinkPackPage from '@/components/link-pack/LinkPackPage';

export const dynamic = 'force-dynamic';

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
  return <LinkPackPage snapshot={snapshot} />;
}
