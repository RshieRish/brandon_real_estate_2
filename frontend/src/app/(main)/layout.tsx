import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';
import ClientWidgets from '@/components/layout/ClientWidgets';
import CookieConsent from '@/components/shared/CookieConsent';

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Navbar />
      <main className="pt-16">{children}</main>
      <Footer />
      <ClientWidgets />
      <CookieConsent />
    </>
  );
}
