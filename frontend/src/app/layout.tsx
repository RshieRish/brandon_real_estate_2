import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: "Sold With Sweeney & Co. | Brandon Sweeney, REALTOR\u00ae",
  description: "NOT your AVERAGE, award winning, philanthropic REALTOR\u00ae OF THE YEAR '25. Serving MA & NH.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
