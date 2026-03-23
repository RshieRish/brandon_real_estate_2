import Hero from '@/components/home/Hero';
import ExplodingHouseScroll from '@/components/home/ExplodingHouseScroll';
import TheProcess from '@/components/home/TheProcess';
import TrustSection from '@/components/home/TrustSection';
import AudienceCards from '@/components/home/AudienceCards';
import GivingBack from '@/components/home/GivingBack';
import InstagramFeed from '@/components/home/InstagramFeed';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const INSTAGRAM_ACCOUNT_ID = process.env.INSTAGRAM_ACCOUNT_ID;
const INSTAGRAM_ACCESS_TOKEN = process.env.INSTAGRAM_ACCESS_TOKEN;

async function fetchContentBlocks() {
  try {
    const res = await fetch(`${API_URL}/api/v1/content/`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return [];
    return await res.json();
  } catch (err) {
    console.error('Failed to fetch content blocks:', err);
    return [];
  }
}

async function fetchInstagramPosts() {
  if (!INSTAGRAM_ACCOUNT_ID || !INSTAGRAM_ACCESS_TOKEN) return [];
  try {
    const res = await fetch(
      `https://graph.facebook.com/v19.0/${INSTAGRAM_ACCOUNT_ID}/media?fields=id,caption,media_type,media_url,thumbnail_url,permalink&limit=5&access_token=${INSTAGRAM_ACCESS_TOKEN}`,
      { next: { revalidate: 3600 } }
    );
    if (!res.ok) {
      console.error('Failed to fetch Instagram posts:', await res.text());
      return [];
    }
    const data = await res.json();
    return data.data || [];
  } catch (err) {
    console.error('Failed to fetch Instagram posts error:', err);
    return [];
  }
}

export default async function Home() {
  const blocks = await fetchContentBlocks();
  const igPosts = await fetchInstagramPosts();

  const getBlockContent = (id: string, fallback: string) => {
    const block = blocks.find((b: { block_id: string }) => b.block_id === id);
    return block ? block.content : fallback;
  };

  return (
    <>
      <Hero />
      <ExplodingHouseScroll />
      <TrustSection
        volumeDone={getBlockContent('trust_volume_done', '100')}
        familiesServed={getBlockContent('trust_families_served', '250')}
        yearsInBusiness={getBlockContent('trust_years_in_business', '10')}
      />
      <AudienceCards />
      <GivingBack donationAmount={getBlockContent('giving_back_donated', '300000')} />
      <InstagramFeed posts={igPosts} />
    </>
  );
}
