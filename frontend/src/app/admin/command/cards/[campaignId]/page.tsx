import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { CardCampaignReview } from '@/components/command/cards/CardCampaignReview';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export const metadata: Metadata = {
  title: 'Card Campaign Review | SWS Command',
  referrer: 'no-referrer',
};

export default async function CardCampaignPage({
  params,
}: Readonly<{
  params: Promise<{ campaignId: string }>;
}>) {
  const { campaignId } = await params;
  if (!UUID_PATTERN.test(campaignId)) notFound();
  return <CardCampaignReview campaignId={campaignId} />;
}
