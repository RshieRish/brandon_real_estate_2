'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  SquaresFour,
  Gauge,
  Users,
  TextT,
  FunnelSimple,
  ChartBar,
  Gear,
  SignOut,
  LinkSimple,
  Article,
} from '@phosphor-icons/react';

const navItems = [
  { label: 'Dashboard', href: '/admin', icon: Gauge },
  { label: 'Leads', href: '/admin/leads', icon: Users },
  { label: 'Content', href: '/admin/content', icon: TextT },
  { label: 'Blog', href: '/admin/blog', icon: Article },
  { label: 'Funnels', href: '/admin/funnels', icon: FunnelSimple },
  { label: 'Link Pack', href: '/admin/link-pack', icon: LinkSimple },
  { label: 'Analytics', href: '/admin/analytics', icon: ChartBar },
  { label: 'Settings', href: '/admin/settings', icon: Gear },
];

export default function AdminSidebar() {
  const pathname = usePathname();
  const router = useRouter();

  const isActive = (href: string) => {
    if (href === '/admin') return pathname === '/admin';
    return pathname.startsWith(href);
  };

  const handleSignOut = () => {
    localStorage.removeItem('admin_token');
    router.push('/admin/login');
  };

  return (
    <aside className="fixed left-0 top-0 h-full w-[240px] bg-dark-card border-r border-dark-border flex flex-col z-40">
      {/* Header */}
      <div className="px-5 py-6 border-b border-dark-border">
        <div className="flex items-center gap-2">
          <SquaresFour size={18} className="text-gold flex-shrink-0" weight="fill" />
          <div>
            <p className="text-gold font-black text-sm leading-none tracking-tight">Sweeney &amp; Co.</p>
            <p className="text-white/40 text-xs mt-0.5 leading-none">Admin Panel</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 overflow-y-auto">
        <ul className="flex flex-col gap-0.5">
          {navItems.map(({ label, href, icon: Icon }) => {
            const active = isActive(href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors relative ${
                    active
                      ? 'bg-gold/10 text-gold border-r-2 border-gold'
                      : 'text-white/60 hover:text-white/90 hover:bg-white/5'
                  }`}
                >
                  <Icon size={16} weight={active ? 'fill' : 'regular'} />
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer / Sign out */}
      <div className="px-3 py-4 border-t border-dark-border">
        <button
          onClick={handleSignOut}
          className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm font-medium text-white/60 hover:text-white/90 hover:bg-white/5 transition-colors"
        >
          <SignOut size={16} />
          Sign Out
        </button>
      </div>
    </aside>
  );
}
