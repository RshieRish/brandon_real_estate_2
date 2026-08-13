import Link from 'next/link';
import type { CommandHomeModel } from '@/lib/command/home';
import { CommandStatePanel } from '../ui/CommandStatePanel';

export function HomeContextPanels({ model }: { model: CommandHomeModel }) {
  const recentlyActive = model.shortcuts.find((shortcut) => shortcut.key === 'recently_active');
  const celebrationRows = model.celebrations
    ? [
        ...model.celebrations.birthdays.map((contact) => ({ contact, kind: 'Birthday' })),
        ...model.celebrations.anniversaries.map((contact) => ({ contact, kind: 'Anniversary' })),
      ]
    : null;

  return (
    <div className="command-home-context-stack">
      <section className="command-home-panel" aria-labelledby="home-recent-heading">
        <div className="command-home-panel-heading">
          <div>
            <span className="command-eyebrow">CONTACT CONTEXT</span>
            <h2 id="home-recent-heading">Recent leads</h2>
          </div>
          <Link href="/admin/command/contacts">View contacts</Link>
        </div>
        {recentlyActive?.count === null ? (
          <CommandStatePanel
            kind="partial_capture"
            title="Recent activity unavailable"
            message="Recent-activity timestamps were not supplied for every contact."
          />
        ) : model.recentContacts.length > 0 ? (
          <ul className="command-home-contact-list">
            {model.recentContacts.slice(0, 5).map((contact) => (
              <li key={contact.id}>
                <Link href={`/admin/command/contacts/${contact.id}`}>
                  <strong>{contact.first_name} {contact.last_name}</strong>
                  <span>{contact.email ?? contact.phone ?? 'No contact method'}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="command-home-neutral-copy">No recently active contacts in the supplied records.</p>
        )}

        <h3 className="command-home-subheading">Celebrations</h3>
        {celebrationRows === null ? (
          <p className="command-home-neutral-copy">Birthday and anniversary records are unavailable.</p>
        ) : celebrationRows.length > 0 ? (
          <ul className="command-home-celebrations">
            {celebrationRows.slice(0, 5).map(({ contact, kind }) => (
              <li key={`${kind}-${contact.id}`}>
                <span>{contact.first_name} {contact.last_name}</span>
                <strong>{kind}</strong>
              </li>
            ))}
          </ul>
        ) : (
          <p className="command-home-neutral-copy">No celebrations in the current month.</p>
        )}
      </section>

      <section className="command-home-panel" aria-labelledby="home-bookings-heading">
        <div className="command-home-panel-heading">
          <div>
            <span className="command-eyebrow">PARTIAL CAPTURE</span>
            <h2 id="home-bookings-heading">Upcoming bookings</h2>
          </div>
        </div>
        <CommandStatePanel
          kind="partial_capture"
          title="Global booking list is unavailable"
          message="Booking histories remain available within individual contact workspaces."
        />
      </section>

      <section className="command-home-panel" aria-labelledby="home-briefing-heading">
        <div className="command-home-panel-heading">
          <div>
            <span className="command-eyebrow">INTERNAL AI</span>
            <h2 id="home-briefing-heading">Sweeney Briefing</h2>
          </div>
          <span className="command-review-badge">Review only</span>
        </div>
        {model.briefing ? (
          <>
            <p className="command-home-briefing">{model.briefing.summary}</p>
            <small>Saved source: {model.briefing.source}</small>
          </>
        ) : (
          <p className="command-home-neutral-copy">No saved briefing is available. Nothing was generated automatically.</p>
        )}
        <Link className="command-home-view-all command-touch-target" href="/admin/command/ai">
          Open Sweeney AI
        </Link>
      </section>
    </div>
  );
}
