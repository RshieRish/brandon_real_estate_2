import { MapPin } from '@phosphor-icons/react';
import type { ContactAddress } from '@/lib/command/contacts';

export function ContactObservedMap({ addresses }: { addresses: readonly ContactAddress[] }) {
  if (addresses.length === 0) {
    return (
      <section className="command-contact-map" aria-label="Observed address">
        <MapPin aria-hidden="true" size={20} />
        <div>
          <h3>Observed address</h3>
          <p>No address was captured</p>
          <small>Map location was not captured</small>
        </div>
      </section>
    );
  }

  return (
    <section className="command-contact-map" aria-label="Observed addresses">
      <MapPin aria-hidden="true" size={20} />
      <div>
        <h3>Observed address</h3>
        {addresses.map((address) => {
          const hasCoordinates = address.latitude !== null && address.longitude !== null;
          return (
            <article key={address.id}>
              <strong>{address.formatted ?? 'Address text was not captured'}</strong>
              {address.address_type ? <span>{address.address_type}</span> : null}
              {hasCoordinates ? (
                <>
                  <p>{address.latitude}, {address.longitude}</p>
                  <small>Static map preview is unavailable</small>
                </>
              ) : <small>Map location was not captured</small>}
            </article>
          );
        })}
      </div>
    </section>
  );
}
