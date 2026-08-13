import { EnvelopeSimple, Phone, Pulse, UserCircle } from '@phosphor-icons/react';
import type {
  ContactCelebrationValue,
  ContactDetail,
  LegacyContact,
  ContactsApi,
} from '@/lib/command/contacts';
import { ContactProfileEditor } from '../ContactProfileEditor';
import { ContactObservedMap } from './ContactObservedMap';

const monthNames = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
] as const;

function celebration(
  label: 'Birthday' | 'Home anniversary' | 'Recovered birthday' | 'Recovered anniversary',
  value: ContactCelebrationValue,
): string {
  const date = `${monthNames[value.month - 1]} ${value.day}`;
  if (value.year_quality === 'sentinel') return `${label}: ${date} — source year treated as sentinel`;
  if (value.year_quality === 'yearless' || value.year === null || value.year_quality === 'unknown') {
    return `${label}: ${date} — year not captured`;
  }
  return `${label}: ${date}, ${value.year}`;
}

export function ContactProfilePanel({
  detail,
  rawContact,
  api,
  onProfileChanged,
  onRemoveTag,
  tagMutationPending = false,
  acquireProfileMutation,
  releaseProfileMutation,
}: Readonly<{
  detail: ContactDetail;
  rawContact: LegacyContact | null;
  api: ContactsApi;
  onProfileChanged: () => Promise<void>;
  onRemoveTag?: (tagId: number) => void;
  tagMutationPending?: boolean;
  acquireProfileMutation?: () => boolean;
  releaseProfileMutation?: () => void;
}>) {
  const { contact, recovered_profile: recovered } = detail;
  const recoveredBirthday = recovered?.birthday;
  const recoveredAnniversary = recovered?.anniversary;
  const duplicateBirthday = contact.birthday !== null
    && recoveredBirthday !== null
    && JSON.stringify(contact.birthday) === JSON.stringify(recoveredBirthday);
  const duplicateAnniversary = contact.anniversary !== null
    && recoveredAnniversary !== null
    && JSON.stringify(contact.anniversary) === JSON.stringify(recoveredAnniversary);

  return (
    <aside className="command-contact-profile-column">
      <section className="command-contact-identity-card">
        <div className="command-contact-avatar" aria-hidden="true">
          <UserCircle size={34} weight="duotone" />
        </div>
        <p className="command-contacts-kicker">Contact profile</p>
        <h2>SWS profile</h2>
        <p className="command-contact-profile-name">{contact.display_name}</p>
        <div className="command-contact-health" aria-label={`Contact health ${contact.health_score ?? 'not scored'}`}>
          <Pulse aria-hidden="true" size={17} />
          <span>{contact.health_score ?? '—'}</span>
          <small>Health</small>
        </div>
        <dl className="command-contact-methods">
          <div><dt><EnvelopeSimple aria-hidden="true" size={15} /> Email</dt><dd>{contact.primary_email ?? 'Not captured'}</dd></div>
          <div><dt><Phone aria-hidden="true" size={15} /> Phone</dt><dd>{contact.primary_phone ?? 'Not captured'}</dd></div>
          <div><dt>Stage</dt><dd>{contact.stage}</dd></div>
        </dl>
        {rawContact ? (
          <ContactProfileEditor
            contact={rawContact}
            api={api}
            onUpdated={onProfileChanged}
            mutationBlocked={tagMutationPending}
            acquireMutation={acquireProfileMutation}
            releaseMutation={releaseProfileMutation}
          />
        ) : <p className="command-contact-limitation">SWS profile fields are unavailable.</p>}
      </section>

      <section className="command-contact-profile-section">
        <h3>Relationships</h3>
        <dl className="command-contact-profile-list">
          {detail.ownership.map((actor, index) => (
            <div key={`${actor.role}-${actor.provider_actor_id ?? index}`}>
              <dt>{actor.role}</dt>
              <dd>{actor.display_name ?? actor.provider_actor_id ?? 'Name not captured'}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="command-contact-profile-section">
        <h3>Tags</h3>
        <div className="command-contact-tags">
          {detail.tags.length > 0
            ? detail.tags.map((tag) => (
              <span key={tag.id}>
                {tag.name}
                {onRemoveTag ? (
                  <button
                    type="button"
                    className="command-touch-target"
                    aria-label={`Remove ${tag.name} tag`}
                    disabled={tagMutationPending}
                    onClick={() => onRemoveTag(tag.id)}
                  >×</button>
                ) : null}
              </span>
            ))
            : <small>No tags</small>}
        </div>
      </section>

      {(contact.birthday || contact.anniversary || recoveredBirthday || recoveredAnniversary) ? (
        <section className="command-contact-profile-section">
          <h3>Celebrations</h3>
          <ul className="command-contact-celebrations">
            {contact.birthday ? <li>{celebration('Birthday', contact.birthday)}</li> : null}
            {contact.anniversary ? <li>{celebration('Home anniversary', contact.anniversary)}</li> : null}
            {recoveredBirthday && !duplicateBirthday
              ? <li>{celebration('Recovered birthday', recoveredBirthday)}</li>
              : null}
            {recoveredAnniversary && !duplicateAnniversary
              ? <li>{celebration('Recovered anniversary', recoveredAnniversary)}</li>
              : null}
          </ul>
        </section>
      ) : null}

      {recovered ? (
        <section className="command-contact-profile-section">
          <h3>Recovered profile</h3>
          <dl className="command-contact-profile-list">
            {recovered.legal_name ? <div><dt>Legal name</dt><dd>{recovered.legal_name}</dd></div> : null}
            {recovered.preferred_name ? <div><dt>Preferred name</dt><dd>{recovered.preferred_name}</dd></div> : null}
            {recovered.company ? <div><dt>Company</dt><dd>{recovered.company}</dd></div> : null}
            {recovered.title ? <div><dt>Title</dt><dd>{recovered.title}</dd></div> : null}
            {recovered.lead_source ? <div><dt>Lead source</dt><dd>{recovered.lead_source}</dd></div> : null}
            {recovered.account_name ? <div><dt>Account</dt><dd>{recovered.account_name}</dd></div> : null}
          </dl>
          {recovered.description ? <p>{recovered.description}</p> : null}
        </section>
      ) : null}

      <ContactObservedMap addresses={detail.addresses} />
    </aside>
  );
}
