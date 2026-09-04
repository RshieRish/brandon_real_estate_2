import type { Metadata } from 'next';
import { CardCampaignsWorkspace } from '@/components/command/cards/CardCampaignsWorkspace';

export const metadata: Metadata = {
  title: 'Client Cards | SWS Command',
  description: 'Review birthday and home-anniversary card campaigns before approval.',
};

export default async function CardsPage({
  searchParams,
}: Readonly<{
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}>) {
  const params = await searchParams;
  return <CardCampaignsWorkspace initialCreate={params.create === 'campaign'} />;
}
