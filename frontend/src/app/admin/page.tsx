'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  ChartBar,
  Users,
  Eye,
  TextT,
  FunnelSimple,
  ArrowRight,
} from '@phosphor-icons/react';

interface DashboardStats {
  total_events: number;
  unique_visitors: number;
  page_views: number;
  period_days: number;
}

const quickActions = [
  { label: 'Manage Leads', href: '/admin/leads', icon: Users },
  { label: 'Edit Content', href: '/admin/content', icon: TextT },
  { label: 'View Funnels', href: '/admin/funnels', icon: FunnelSimple },
  { label: 'Analytics', href: '/admin/analytics', icon: ChartBar },
];

function StatSkeleton() {
  return (
    <div className="bg-dark-card border border-dark-border p-6 rounded-xl animate-pulse">
      <div className="w-8 h-8 bg-white/5 rounded-lg mb-4" />
      <div className="w-16 h-7 bg-white/5 rounded mb-2" />
      <div className="w-24 h-3 bg-white/5 rounded" />
    </div>
  );
}

export default function AdminDashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const token = localStorage.getItem('admin_token');
        const res = await fetch('/api/v1/analytics/dashboard', {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          setStats(data);
        }
      } catch {
        // Stats unavailable — silently fail, show empty state
      } finally {
        setIsLoading(false);
      }
    };

    fetchStats();
  }, []);

  const statCards = stats
    ? [
        { label: 'Total Events', value: stats.total_events.toLocaleString(), icon: ChartBar },
        { label: 'Unique Visitors', value: stats.unique_visitors.toLocaleString(), icon: Users },
        { label: 'Page Views', value: stats.page_views.toLocaleString(), icon: Eye },
        {
          label: `Last ${stats.period_days} Days`,
          value: stats.period_days.toString(),
          icon: ChartBar,
          subtitle: 'Period',
        },
      ]
    : null;

  return (
    <div className="p-8 max-w-5xl">
      {/* Page header */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
        className="flex flex-col gap-1"
      >
        <h1 className="text-white font-black text-2xl">Dashboard</h1>
        <p className="text-white/40 text-sm">
          {new Date().toLocaleDateString('en-US', {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric',
          })}
        </p>
      </motion.div>

      {/* Quick stats strip */}
      <div className="flex flex-row gap-4 mt-6 flex-wrap">
        {isLoading ? (
          <>
            <div className="flex-1 min-w-[180px]"><StatSkeleton /></div>
            <div className="flex-1 min-w-[180px]"><StatSkeleton /></div>
            <div className="flex-1 min-w-[180px]"><StatSkeleton /></div>
            <div className="flex-1 min-w-[180px]"><StatSkeleton /></div>
          </>
        ) : statCards ? (
          statCards.map(({ label, value, icon: Icon }, i) => (
            <motion.div
              key={label}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: 'spring' as const, stiffness: 100, damping: 20, delay: i * 0.06 }}
              className="flex-1 min-w-[180px] bg-dark-card border border-dark-border p-6 rounded-xl"
            >
              <Icon size={20} className="text-gold mb-4" />
              <p className="text-white font-black text-2xl">{value}</p>
              <p className="text-white/40 text-xs uppercase tracking-widest mt-1">{label}</p>
            </motion.div>
          ))
        ) : (
          <div className="text-white/30 text-sm py-4">Stats unavailable</div>
        )}
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-2 gap-4 mt-8">
        {quickActions.map(({ label, href, icon: Icon }, i) => (
          <motion.div
            key={href}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: 'spring' as const, stiffness: 100, damping: 20, delay: 0.1 + i * 0.06 }}
          >
            <Link
              href={href}
              className="group flex items-center justify-between bg-dark-card border border-dark-border hover:border-gold/30 p-6 rounded-xl transition-colors"
            >
              <div className="flex items-center gap-4">
                <Icon size={22} className="text-gold" weight="fill" />
                <span className="text-white font-semibold text-sm">{label}</span>
              </div>
              <ArrowRight
                size={16}
                className="text-white/30 group-hover:text-gold/60 transition-colors"
              />
            </Link>
          </motion.div>
        ))}
      </div>

      {/* Recent activity note */}
      <p className="text-white/40 text-sm mt-8">
        Full analytics, lead management, and content editing available in the sidebar navigation.
      </p>
    </div>
  );
}
