import type { LinkPackSnapshot } from '@/lib/link-pack/types';
import { themeStyle } from '@/lib/link-pack/theme-css';
import { imageUrl } from '@/lib/link-pack/api';
import Avatar from './Avatar';
import LinkPackSocialRow from './LinkPackSocialRow';
import LinkPackButton from './LinkPackButton';
import LinkPackThumbnailCard from './LinkPackThumbnailCard';
import LinkPackGroup from './LinkPackGroup';
import LinkPackEmailGate from './LinkPackEmailGate';

export default function LinkPackPage({ snapshot }: { snapshot: LinkPackSnapshot }) {
  const bgUrl = imageUrl(snapshot.background_image_url);
  const useImageBg = snapshot.theme.background.type === 'image' && !!bgUrl;
  return (
    <main
      className="lp-root"
      style={{
        ...themeStyle(snapshot.theme),
        minHeight: '100dvh',
        // Dark body matches Linktree's "luminance: DARK" rendering — the
        // bg image only appears in the column-banner; outside is solid dark.
        background: '#000000',
        color: 'var(--lp-text-color)',
        fontFamily: 'var(--lp-font), system-ui, sans-serif',
        position: 'relative',
        overflowX: 'hidden',
      }}
    >
      <div
        style={{
          position: 'relative',
          zIndex: 1,
          maxWidth: 580,
          margin: '0 auto',
          padding: '56px 20px 64px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 16,
        }}
      >
        {/*
          Background image bound to the column width AND viewport height.
          Linktree's container is `100dvh` so its `background-size: cover` only
          covers ~580×909. Our content column is taller than viewport, so we
          can't put the bg on the column itself or the image scales to fit
          1829px+ of content.
        */}
        {useImageBg && (
          // Outer wrapper handles `position: fixed` + horizontal centering so
          // the banner stays anchored to the viewport while content scrolls
          // over it (matches Linktree). Inner div owns the bg image and the
          // drift animation — keeping the animation's `transform` separate
          // from the wrapper's centering `transform` so they don't conflict.
          <div
            aria-hidden
            style={{
              position: 'fixed',
              top: 0,
              left: '50%',
              transform: 'translateX(-50%)',
              width: '100%',
              maxWidth: 580,
              height: 909,
              zIndex: -1,
              pointerEvents: 'none',
            }}
          >
            <div
              className="lp-banner-drift"
              style={{
                width: '100%',
                height: '100%',
                backgroundImage: `url(${bgUrl})`,
                backgroundSize: 'cover',
                backgroundPosition: '50% 0%',
                backgroundRepeat: 'no-repeat',
                willChange: 'transform',
              }}
            />
          </div>
        )}
        <Avatar
          photoUrl={imageUrl(snapshot.profile.photo_url)}
          name={snapshot.profile.name}
          isVerified={snapshot.profile.is_verified}
        />
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: '12px 0 0', textAlign: 'center' }}>
          {snapshot.profile.name}
        </h1>
        {snapshot.profile.bio && (
          <p style={{ fontSize: 14, fontWeight: 400, margin: '8px 0 0', textAlign: 'center', maxWidth: 600, lineHeight: 1.4 }}>
            {snapshot.profile.bio}
          </p>
        )}
        <LinkPackSocialRow social={snapshot.social} />
        <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 16, marginTop: 16 }}>
          {snapshot.items.filter(i => i.is_active).map(item => {
            if (item.kind === 'classic') return <LinkPackButton key={item.id} item={item} />;
            if (item.kind === 'thumbnail') return <LinkPackThumbnailCard key={item.id} item={item} />;
            if (item.kind === 'group') return <LinkPackGroup key={item.id} item={item} />;
            if (item.kind === 'email_gate') return <LinkPackEmailGate key={item.id} item={item} />;
            return null;
          })}
        </div>
      </div>
    </main>
  );
}
