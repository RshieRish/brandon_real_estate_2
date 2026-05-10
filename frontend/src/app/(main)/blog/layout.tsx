import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Real Estate Blog | Sold With Sweeney & Co. — Brandon Sweeney, REALTOR®',
  description:
    'Expert insights on MA and NH real estate from the team at Sold With Sweeney & Co. Buying, selling, investing — we cover it all.',
};

export default function BlogLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
