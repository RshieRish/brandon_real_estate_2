'use client';

import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { CircleNotch } from '@phosphor-icons/react';
import AdminSidebar from '@/components/layout/AdminSidebar';

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [isChecking, setIsChecking] = useState(true);
  const [isAuthed, setIsAuthed] = useState(false);

  // Skip auth check on login page
  const isLoginPage = pathname === '/admin/login';

  useEffect(() => {
    if (isLoginPage) {
      setIsChecking(false);
      setIsAuthed(false);
      return;
    }

    const checkAuth = async () => {
      const token = localStorage.getItem('admin_token');
      if (!token) {
        router.push('/admin/login');
        setIsChecking(false);
        return;
      }

      try {
        const res = await fetch('/api/v1/auth/me', {
          headers: { Authorization: `Bearer ${token}` },
        });

        if (res.ok) {
          setIsAuthed(true);
        } else {
          localStorage.removeItem('admin_token');
          router.push('/admin/login');
        }
      } catch {
        localStorage.removeItem('admin_token');
        router.push('/admin/login');
      } finally {
        setIsChecking(false);
      }
    };

    checkAuth();
  }, [isLoginPage, router]);

  // Login page: render without shell
  if (isLoginPage) {
    return <>{children}</>;
  }

  // Checking auth: show centered spinner
  if (isChecking) {
    return (
      <div className="min-h-[100dvh] bg-dark-surface flex items-center justify-center">
        <CircleNotch className="animate-spin text-gold w-8 h-8" />
      </div>
    );
  }

  // Not authed: return null while redirect fires
  if (!isAuthed) {
    return null;
  }

  // Authenticated shell
  return (
    <div className="flex min-h-[100dvh] bg-dark-surface">
      <AdminSidebar />
      <main className="flex-1 ml-[240px] overflow-auto">
        {children}
      </main>
    </div>
  );
}
