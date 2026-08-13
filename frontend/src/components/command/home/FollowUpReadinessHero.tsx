import Link from 'next/link';
import type { FollowUpReadiness, HomeNextAction, ReadinessFactorKey } from '@/lib/command/home';

const actionLabels: Record<ReadinessFactorKey, string> = {
  overdue_tasks: 'Review overdue tasks',
  uncontacted_leads: 'Review never-contacted leads',
  contact_health: 'Complete contact profiles',
  active_opportunities: 'Review opportunity stages',
};

const queueLabels: Record<ReadinessFactorKey, string> = {
  overdue_tasks: 'Overdue tasks',
  uncontacted_leads: 'Never-contacted leads',
  contact_health: 'Incomplete contact profiles',
  active_opportunities: 'Inactive opportunity stages',
};

export function FollowUpReadinessHero({
  readiness,
  nextActions,
}: {
  readiness: FollowUpReadiness;
  nextActions: readonly HomeNextAction[];
}) {
  const primaryAction = nextActions[0];
  const unavailable = readiness.factors.filter((factor) => !factor.available);

  return (
    <section className={`command-home-readiness is-${readiness.status}`} aria-labelledby="follow-up-readiness-heading">
      <div className="command-home-readiness-summary">
        <div>
          <span className="command-eyebrow">PRIORITY DECISION</span>
          <h2 id="follow-up-readiness-heading">Follow-Up Readiness</h2>
          <p className="command-home-readiness-score">
            {readiness.status === 'partial' ? 'Partial' : `${readiness.score}%`}
          </p>
          <p className="command-home-readiness-coverage">{readiness.label}</p>
        </div>
        <div className="command-home-primary-action">
          <p>{primaryAction?.title ?? 'Your follow-up queue is clear.'}</p>
          {primaryAction ? (
            <Link className="command-primary-button command-touch-target" href={primaryAction.href}>
              {actionLabels[primaryAction.kind]}
            </Link>
          ) : null}
        </div>
      </div>

      <div className="command-readiness-rail" aria-label="Readiness factors">
        {readiness.factors.map((factor) => (
          <div
            key={factor.key}
            className={`command-readiness-segment${factor.available ? '' : ' is-unavailable'}`}
            style={{ flexGrow: factor.weight }}
            data-score={factor.score ?? undefined}
          >
            <span>{factor.label}</span>
            <strong>{factor.score === null ? 'Unavailable' : `${factor.score}%`}</strong>
          </div>
        ))}
      </div>

      <div className="command-home-readiness-lower">
        <div>
          <h3>Ranked next actions</h3>
          {nextActions.length > 0 ? (
            <ol className="command-home-action-queue">
              {nextActions.slice(0, 4).map((action) => (
                <li key={action.kind}>
                  <Link href={action.href}>
                    <span>{queueLabels[action.kind]}</span>
                    <strong>{action.affected} affected</strong>
                  </Link>
                </li>
              ))}
            </ol>
          ) : (
            <p className="command-home-neutral-copy">No action is currently ranked from the verified inputs.</p>
          )}
        </div>
        <details className="command-home-source-disclosure">
          <summary>Readiness source coverage</summary>
          {unavailable.length > 0 ? (
            <ul>
              {unavailable.map((factor) => <li key={factor.key}>{factor.insight}</li>)}
            </ul>
          ) : (
            <p>All four readiness inputs are available from current internal records.</p>
          )}
        </details>
      </div>
    </section>
  );
}
