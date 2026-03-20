'use client';

import { useEffect, useState } from 'react';
import { WarningCircle } from '@phosphor-icons/react';

interface DashboardStats {
  total_events: number;
  unique_visitors: number;
  page_views: number;
  period_days: number;
  top_pages: Array<{ page: string; count: number }>;
  top_events: Array<{ event_type: string; count: number }>;
}

interface AnalyticsEvent {
  id: number;
  event_type: string;
  page_url: string;
  created_at: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex-1 min-w-[160px] bg-dark-card border border-dark-border p-6 rounded-xl">
      <p className="text-white font-black text-2xl">{value.toLocaleString()}</p>
      <p className="text-white/40 text-xs uppercase tracking-widest mt-1">{label}</p>
    </div>
  );
}

function StatSkeleton() {
  return (
    <div className="flex-1 min-w-[160px] bg-dark-card border border-dark-border p-6 rounded-xl animate-pulse">
      <div className="h-7 w-20 bg-dark-border rounded mb-2" />
      <div className="h-3 w-28 bg-dark-border rounded" />
    </div>
  );
}

export default function AnalyticsPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [events, setEvents] = useState<AnalyticsEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      const token = localStorage.getItem('admin_token');
      if (!token) {
        setError('Not authenticated. Please log in.');
        setIsLoading(false);
        return;
      }
      try {
        const [statsRes, eventsRes] = await Promise.all([
          fetch(`${API_URL}/api/v1/analytics/dashboard?period_days=30`, {
            headers: { Authorization: `Bearer ${token}` },
          }),
          fetch(`${API_URL}/api/v1/analytics/?limit=50`, {
            headers: { Authorization: `Bearer ${token}` },
          }),
        ]);
        if (!statsRes.ok || !eventsRes.ok) throw new Error('Failed to load analytics');
        const [statsData, eventsData] = await Promise.all([
          statsRes.json(),
          eventsRes.json(),
        ]);
        setStats(statsData);
        setEvents(eventsData);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        setIsLoading(false);
      }
    };
    fetchData();
  }, []);

  const maxPageCount = stats ? Math.max(...stats.top_pages.map((p) => p.count), 1) : 1;
  const maxEventCount = stats ? Math.max(...stats.top_events.map((e) => e.count), 1) : 1;

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-white font-black text-2xl">Analytics</h1>
        <span className="border border-dark-border text-white/40 text-xs px-3 py-1 rounded-full uppercase tracking-widest">
          Last 30 Days
        </span>
      </div>

      {/* Error state */}
      {error && (
        <div className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/20 rounded mb-6">
          <WarningCircle weight="fill" className="w-5 h-5 text-red-400 flex-shrink-0" />
          <div>
            <p className="text-red-400 text-sm font-medium">Failed to load analytics</p>
            <p className="text-white/40 text-xs mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Stats strip */}
      <div className="flex flex-row gap-4 flex-wrap">
        {isLoading ? (
          <>
            <StatSkeleton />
            <StatSkeleton />
            <StatSkeleton />
            <StatSkeleton />
          </>
        ) : stats ? (
          <>
            <StatCard label="Total Events" value={stats.total_events} />
            <StatCard label="Unique Visitors" value={stats.unique_visitors} />
            <StatCard label="Page Views" value={stats.page_views} />
            <StatCard label="Period (Days)" value={stats.period_days} />
          </>
        ) : null}
      </div>

      {/* Two-col breakdown */}
      {!error && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mt-8">
          {/* Top Pages */}
          <div className="bg-dark-card border border-dark-border p-6 rounded-xl">
            <h2 className="text-white/40 text-xs uppercase tracking-widest font-semibold mb-4">
              Top Pages
            </h2>
            {isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="h-8 bg-dark-border rounded animate-pulse" />
                ))}
              </div>
            ) : stats && stats.top_pages.length > 0 ? (
              <div className="space-y-3">
                {stats.top_pages.map((p) => (
                  <div key={p.page} className="flex items-center justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-white/70 text-sm truncate">{p.page}</p>
                      <div
                        className="bg-gold/20 h-1 mt-1 rounded"
                        style={{ width: `${(p.count / maxPageCount) * 100}%` }}
                      />
                    </div>
                    <span className="text-gold font-black text-sm flex-shrink-0">{p.count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-white/20 text-sm">No page data yet</p>
            )}
          </div>

          {/* Top Events */}
          <div className="bg-dark-card border border-dark-border p-6 rounded-xl">
            <h2 className="text-white/40 text-xs uppercase tracking-widest font-semibold mb-4">
              Top Events
            </h2>
            {isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="h-8 bg-dark-border rounded animate-pulse" />
                ))}
              </div>
            ) : stats && stats.top_events.length > 0 ? (
              <div className="space-y-3">
                {stats.top_events.map((e) => (
                  <div key={e.event_type} className="flex items-center justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-white/70 text-sm truncate">{e.event_type}</p>
                      <div
                        className="bg-gold/20 h-1 mt-1 rounded"
                        style={{ width: `${(e.count / maxEventCount) * 100}%` }}
                      />
                    </div>
                    <span className="text-gold font-black text-sm flex-shrink-0">{e.count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-white/20 text-sm">No event data yet</p>
            )}
          </div>
        </div>
      )}

      {/* Recent Events table */}
      {!error && (
        <div className="mt-8">
          <h2 className="text-white/40 text-xs uppercase tracking-widest font-semibold mb-4">
            Recent Events
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full border border-dark-border text-sm">
              <thead>
                <tr className="border-b border-dark-border">
                  {['Event', 'Page', 'Time'].map((col) => (
                    <th
                      key={col}
                      className="text-white/40 text-xs tracking-widest uppercase font-semibold px-4 py-3 text-left"
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {isLoading
                  ? Array.from({ length: 5 }).map((_, i) => (
                      <tr key={i} className="border-b border-dark-border">
                        {Array.from({ length: 3 }).map((__, j) => (
                          <td key={j} className="px-4 py-4">
                            <div className="h-4 bg-dark-border rounded animate-pulse" />
                          </td>
                        ))}
                      </tr>
                    ))
                  : events.map((ev) => (
                      <tr
                        key={ev.id}
                        className="border-b border-dark-border hover:bg-dark-surface/50 transition-colors"
                      >
                        <td className="px-4 py-3 text-white text-sm">{ev.event_type}</td>
                        <td className="px-4 py-3 text-white/40 text-xs max-w-[240px] truncate">
                          {ev.page_url}
                        </td>
                        <td className="px-4 py-3 text-white/40 text-xs">
                          {new Date(ev.created_at).toLocaleString()}
                        </td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
