import type { Metadata } from 'next';
import './globals.css';

const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? 'https://soldwithsweeney.com').replace(/\/$/, '');

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: 'Sold With Sweeney & Co. | Brandon Sweeney, REALTOR\u00ae',
  description: "NOT your AVERAGE, award winning, philanthropic REALTOR\u00ae OF THE YEAR '25. Serving MA & NH.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-dark-surface text-white font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
