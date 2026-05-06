import type { Metadata } from 'next';
import { Montserrat, Inter, Roboto, Poppins, Playfair_Display } from 'next/font/google';
import './animations.css';

const montserrat = Montserrat({ subsets: ['latin'], weight: ['400', '600', '700'], variable: '--font-montserrat' });
const inter = Inter({ subsets: ['latin'], weight: ['400', '600', '700'], variable: '--font-inter' });
const roboto = Roboto({ subsets: ['latin'], weight: ['400', '500', '700'], variable: '--font-roboto' });
const poppins = Poppins({ subsets: ['latin'], weight: ['400', '600', '700'], variable: '--font-poppins' });
const playfair = Playfair_Display({ subsets: ['latin'], weight: ['400', '600', '700'], variable: '--font-playfair' });

export const metadata: Metadata = {
  robots: { index: true, follow: true },
};

export default function LinkPackLayout({ children }: { children: React.ReactNode }) {
  const fontVars = `${montserrat.variable} ${inter.variable} ${roboto.variable} ${poppins.variable} ${playfair.variable}`;
  return <div className={fontVars}>{children}</div>;
}
