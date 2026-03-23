'use client';

import dynamic from 'next/dynamic';

const ChatWidget = dynamic(() => import('@/components/chat/ChatWidget'), { ssr: false });
const PageViewTracker = dynamic(() => import('@/components/analytics/PageViewTracker'), { ssr: false });

export default function ClientWidgets() {
  return (
    <>
      <ChatWidget />
      <PageViewTracker />
    </>
  );
}
