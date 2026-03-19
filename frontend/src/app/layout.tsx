import type { Metadata } from 'next';
import './globals.css';
import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';

export const metadata: Metadata = {
  title: 'Sold With Sweeney & Co. | Brandon Sweeney, REALTOR\u00ae',
  description: "NOT your AVERAGE, award winning, philanthropic REALTOR\u00ae OF THE YEAR '25. Serving MA & NH.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-dark-surface text-white font-sans antialiased">
        <Navbar />
        <main className="pt-16">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
