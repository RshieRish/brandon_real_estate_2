import type { Metadata } from 'next';
import './animations.css';

export const metadata: Metadata = {
  robots: { index: true, follow: true },
};

export default function LinkPackLayout({ children }: { children: React.ReactNode }) {
  return <div>{children}</div>;
}
