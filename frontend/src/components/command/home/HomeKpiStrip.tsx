import Link from 'next/link';
import type { HomeKpi } from '@/lib/command/home';

export function HomeKpiStrip({ kpis }: { kpis: readonly HomeKpi[] }) {
  return (
    <section className="command-home-kpis" aria-label="Operational metrics">
      {kpis.map((kpi) => (
        <Link key={kpi.key} href={kpi.href} className="command-home-kpi" data-testid="home-kpi">
          <span>{kpi.label}</span>
          <strong>{kpi.value}</strong>
          <p>{kpi.value === 'Unavailable' ? 'This metric is not materialized.' : kpi.insight}</p>
        </Link>
      ))}
    </section>
  );
}
